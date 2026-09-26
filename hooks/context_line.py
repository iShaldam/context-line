#!/usr/bin/env python3
"""Tell the model to stop and hand off once a session gets heavy.

Every turn re-sends the whole context, so a big session pays its size on
every prompt. This hook runs on UserPromptSubmit and, so long agentic turns
can't blow past the line, on PostToolUse too. It reads the transcript's last
usage row and, once the session crosses a line (or gets compacted), asks the
model to stop, write a handoff and give the user a paste-ready prompt for a
new session. Only growth since the session's first turn counts: a fresh
session already carries its tools and skills, and nagging on turn one helps
no one.

It learns from what the user does next. A nudge followed by the session going
quiet is "taken"; one the user talks past is "ignored". Ignored nudges lower
the line for next time -- the point is to catch it earlier, not to give up --
and every nudge after the first in a session is firmer. So does context that
keeps growing after a nudge: that's the model talking past it.

One prompt can be held back on purpose: the first one into a heavy session
that sat idle past the prompt cache, which would re-send everything. Sending
it again goes through. Otherwise stdlib only, and any failure means silence:
an error must never block a prompt.
"""
import datetime, json, os, sys, time
try:
    import fcntl
except ImportError:   # windows: no lock, parallel tool calls may double-nudge
    fcntl = None

STEP = 10000         # how far one ignored nudge moves the line
RENUDGE = 30000      # context growth before nudging the same session again
KEPT_GOING = 20000   # growth past a nudge that means it was ignored
TAKEN_WITHIN = 2     # prompts after a nudge that still count as acting on it
QUIET = 3600         # seconds of silence after a nudge that count as taken
TAIL = 400_000       # bytes of transcript to read from the end
HEAD = 2_000_000     # bytes to search from the start for the first usage row


def _int_env(name, default):
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


def settings():
    return {
        "line": _int_env("CONTEXT_LINE_LINE", 150000),
        "floor": _int_env("CONTEXT_LINE_FLOOR", 80000),
        "min_growth": _int_env("CONTEXT_LINE_MIN_GROWTH", 40000),
        "adapt": os.environ.get("CONTEXT_LINE_ADAPT", "1") != "0",
        "gap": _int_env("CONTEXT_LINE_GAP", 3600),
    }


def state_dir():
    d = os.environ.get("CLAUDE_PLUGIN_DATA")
    if d:
        return d
    base = os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state")
    return os.path.join(base, "context-line")


def handoff_path(cwd, session_id):
    """Explicit override, else the repo's HANDOFF.md, else the state dir."""
    override = os.environ.get("CONTEXT_LINE_HANDOFF")
    if override:
        return os.path.expanduser(override)
    d = os.path.abspath(cwd) if cwd else ""
    while d and d != os.path.dirname(d):
        if os.path.exists(os.path.join(d, ".git")):
            return os.path.join(d, "HANDOFF.md")
        d = os.path.dirname(d)
    day = datetime.date.today().isoformat()
    return os.path.join(state_dir(), "handoffs", f"{day}-{session_id[:8]}.md")


def _load(cfg):
    try:
        with open(os.path.join(state_dir(), "state.json")) as f:
            s = json.load(f)
    except (OSError, ValueError):
        s = {}
    s.setdefault("sessions", {})
    # a changed CONTEXT_LINE_LINE wins over whatever the line learned before
    if s.get("base") != cfg["line"] or "line" not in s:
        s["base"] = s["line"] = cfg["line"]
    return s


def _save(s):
    cut = time.time() - 7 * 86400   # keep the file small
    s["sessions"] = {k: v for k, v in s["sessions"].items() if v.get("seen", 0) > cut}
    d = state_dir()
    os.makedirs(d, exist_ok=True)
    tmp = os.path.join(d, f"state.json.{os.getpid()}")
    with open(tmp, "w") as f:
        json.dump(s, f)
    os.replace(tmp, os.path.join(d, "state.json"))   # atomic: sessions share it


def _log(row):
    os.makedirs(state_dir(), exist_ok=True)
    with open(os.path.join(state_dir(), "nudges.jsonl"), "a") as f:
        f.write(json.dumps(row) + "\n")


def _usage(line):
    """Context tokens one transcript row carried, or 0 if it has no usage."""
    try:
        u = (json.loads(line).get("message") or {}).get("usage")
        if not u:
            return 0
        return ((u.get("input_tokens") or 0) + (u.get("cache_read_input_tokens") or 0)
                + (u.get("cache_creation_input_tokens") or 0))
    except (ValueError, AttributeError, TypeError):
        return 0


def _when(line):
    """Epoch seconds of a transcript row's timestamp, or None.

    Hooks get the system python (3.9 on macOS), whose fromisoformat rejects a
    trailing Z -- without the swap every timestamp fails to parse.
    """
    try:
        ts = json.loads(line).get("timestamp")
        return datetime.datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
    except (ValueError, AttributeError, TypeError):
        return None


def baseline_of(transcript):
    """Context the session started with: its first usage row, read from the head."""
    try:
        with open(transcript, "rb") as f:
            read = 0
            for raw in f:
                read += len(raw)
                ctx = _usage(raw.decode("utf-8", "ignore"))
                if ctx or read > HEAD:
                    return ctx
    except OSError:
        pass
    return 0


def context_of(transcript):
    """(context tokens carried by the last turn, whether it was compacted,
    epoch time of that last API call or None).

    The time comes from the last row that carries usage, not the last row:
    by the time a prompt hook runs, the new prompt may already be written.
    If a compaction row is NEWER than that usage row, when is None instead:
    the next prompt re-sends the compacted context, not the old, larger one,
    so there is no real "last call" size to warn about. A compaction OLDER
    than the last usage row doesn't affect when.
    """
    ctx, compacted, when = 0, False, None
    try:
        with open(transcript, "rb") as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - TAIL))
            lines = f.read().decode("utf-8", "ignore").splitlines()
    except OSError:
        return 0, False, None
    for line in reversed(lines):
        if '"isCompactSummary":true' in line.replace(" ", ""):
            compacted = True
        if not ctx:
            ctx = _usage(line)
            if ctx:
                when = None if compacted else _when(line)
    return ctx, compacted, when


def _grade(s, cfg, sid, r, outcome):
    """Once per session, so one stubborn session moves the line one STEP."""
    r["graded"] = outcome
    if outcome == "ignored" and cfg["adapt"]:
        s["line"] = max(min(cfg["floor"], s["line"]), s["line"] - STEP)
    _log({"ts": time.time(), "session": sid, "outcome": outcome,
          "ctx": r.get("nudge_ctx"), "line_now": s["line"]})


def _settle(s, cfg):
    """Grade nudges whose session has moved on: taken if it went quiet.
    Returns whether anything was graded."""
    now, graded = time.time(), False
    for sid, r in s["sessions"].items():
        if not r.get("nudged_at") or r.get("graded") is not None:
            continue
        if r.get("prompts_since_nudge", 0) > TAKEN_WITHIN:
            _grade(s, cfg, sid, r, "ignored")
        elif now - r.get("seen", now) > QUIET:
            _grade(s, cfg, sid, r, "taken")
        else:
            continue
        graded = True
    return graded


# The paste block names the old session so the NEW one labels it done:
# labelling at handoff time would mark it before anything replaced it, and a
# hook can't reach the desktop app's session tools anyway. Keep the line in
# sync with commands/handoff.md (a test checks).
RENAME_STEP = (
    "if a tool can tell you this session's own id and title (in the Claude desktop "
    "app: get_session with \"self\"), add one last line to that block, outside any "
    "word limit:\n"
    "first: rename session <id> to \"done: <title>\" (skip if it already starts with "
    "\"done: \"; don't archive it; if the rename fails, say so and carry on)")


def message(ctx, compacted, n, path):
    why = ("this session was compacted, so earlier detail is already lossy"
           if compacted else f"this session carries ~{ctx // 1000}k tokens, re-sent every turn")
    tone = ("Say it plainly before anything else" if n == 1
            else f"This is nudge #{n} and the session kept going -- lead with it, firmly")
    return (f"context-line: START A FRESH SESSION. {why}. {tone}: stop at the next safe "
            "point -- no new task and no tool-heavy steps (browsing, big reads, builds, test "
            f"runs). Then (1) add a dated section to {path} with what is done, what is next "
            "and any decisions made, keeping what is already there, (2) end with exactly ONE "
            "fenced ```text block for the user to paste into a new session: the one job, "
            f"'read {path} first', and the first next step. (3) {RENAME_STEP}")


def _heavy(ctx, base, s, cfg):
    """Over the line, counting only growth past the session's first turn."""
    return ctx >= s["line"] and ctx - base >= cfg["min_growth"]


def check(session_id, transcript, cwd="", event="prompt"):
    """Return an instruction for the model, or '' when the session is fine.

    event is "prompt" (UserPromptSubmit) or "tool" (PostToolUse, mid-turn).
    Only prompts count toward grading a nudge; a tool event that neither
    nudges nor grades writes nothing, since every session shares the state.
    """
    if not session_id or not transcript:
        return ""
    os.makedirs(state_dir(), exist_ok=True)
    with open(os.path.join(state_dir(), "state.lock"), "w") as lock:
        if fcntl:   # parallel tool calls fire their hooks at the same moment
            fcntl.flock(lock, fcntl.LOCK_EX)
        return _check(session_id, transcript, cwd, event)


def _check(session_id, transcript, cwd, event):
    cfg = settings()
    s = _load(cfg)
    r = s["sessions"].setdefault(session_id, {})
    r["seen"] = time.time()
    prompt = event == "prompt"
    if prompt and r.get("nudged_at"):
        r["prompts_since_nudge"] = r.get("prompts_since_nudge", 0) + 1
    changed = _settle(s, cfg) or prompt

    ctx, compacted, _ = context_of(transcript)
    base = r.get("baseline") or baseline_of(transcript)
    if base:
        r["baseline"] = base
    last = r.get("nudge_ctx")
    if last is not None and r.get("graded") is None and ctx >= last + KEPT_GOING:
        _grade(s, cfg, session_id, r, "ignored")   # the session talked past it
        changed = True
    due = (compacted and not r.get("nudged_compact")) or (
        _heavy(ctx, base, s, cfg) and (last is None or ctx >= last + RENUDGE))
    if not due:
        if changed:
            _save(s)
        return ""

    n = r.get("nudges", 0) + 1
    r.update(nudges=n, nudged_at=time.time(), nudge_ctx=ctx, prompts_since_nudge=0)
    if compacted:
        r["nudged_compact"] = True
    _log({"ts": time.time(), "session": session_id, "event": "nudge",
          "ctx": ctx, "compacted": compacted, "line": s["line"], "n": n})
    _save(s)
    return message(ctx, compacted, n, handoff_path(cwd, session_id))


def _ago(secs):
    secs = int(secs)
    if secs >= 3600:
        return f"{secs // 3600}h"
    if secs >= 60:
        return f"{secs // 60}m"
    return f"{secs}s"


def gap_reason(ctx, gap, path, prompt=""):
    """What the held-back prompt would cost. Shown to the user, never the model."""
    k = ctx // 1000
    if os.path.exists(path):
        cheaper = (f"start a new session and read {path} "
                   f"(updated {_ago(time.time() - os.path.getmtime(path))} ago)")
    else:
        cheaper = "send /handoff once to wrap up here, then start a new session from it"
    out = (f"context-line: not sent. This session carries ~{k}k and sat idle {_ago(gap)}, "
           f"past the prompt cache, so this prompt would re-send all {k}k. Cheaper: "
           f"{cheaper}. To go on here, send it again.")
    if prompt:   # the app may drop a blocked prompt; shown to the user, never stored
        out += "\n\nYour prompt, to copy back:\n" + prompt[:300]
    return out


def resume_guard(session_id, transcript, cwd="", prompt=""):
    """The reason to hold this prompt back, or '' to let it through.

    A session idle past the prompt cache re-sends all of its context on the
    next prompt. When that session is over the line, hold the first prompt
    back once and say what it would cost; the same prompt sent again goes
    through (no API call has happened since, so the last call's time matches).
    """
    if not session_id or not transcript or settings()["gap"] <= 0:
        return ""
    os.makedirs(state_dir(), exist_ok=True)
    with open(os.path.join(state_dir(), "state.lock"), "w") as lock:
        if fcntl:
            fcntl.flock(lock, fcntl.LOCK_EX)
        return _resume_guard(session_id, transcript, cwd, prompt)


def _resume_guard(session_id, transcript, cwd, prompt):
    cfg = settings()
    ctx, _, when = context_of(transcript)
    if when is None:
        return ""
    gap = time.time() - when
    if gap < cfg["gap"]:
        return ""
    s = _load(cfg)
    r = s["sessions"].setdefault(session_id, {})
    base = r.get("baseline") or baseline_of(transcript)
    if not _heavy(ctx, base, s, cfg):
        return ""
    r["seen"] = time.time()
    if base:
        r["baseline"] = base
    row = {"ts": time.time(), "session": session_id, "ctx": ctx, "gap": int(gap)}
    if r.get("gap_blocked") == when:
        _log(dict(row, event="gap_resent"))
        _save(s)
        return ""
    r["gap_blocked"] = when
    _log(dict(row, event="gap_block"))
    _save(s)
    return gap_reason(ctx, gap, handoff_path(cwd, session_id), prompt)


def main():
    try:
        p = json.load(sys.stdin)
        if p.get("agent_id"):
            return 0   # a subagent's tool call; its parent gets checked on its own
        tool = p.get("hook_event_name") == "PostToolUse"
        sid, transcript = p.get("session_id"), p.get("transcript_path")
        cwd = p.get("cwd") or ""
        if not tool:
            try:
                reason = resume_guard(sid, transcript, cwd, p.get("prompt") or "")
            except Exception:
                reason = ""   # a broken guard never blocks, and never costs the nudge
            if reason:   # held back once; the same prompt sent again goes through
                print(json.dumps({"decision": "block", "reason": reason}))
                return 0
        out = check(sid, transcript, cwd, event="tool" if tool else "prompt")
        if out and tool:   # plain stdout only reaches the model on UserPromptSubmit
            out = json.dumps({"hookSpecificOutput": {
                "hookEventName": "PostToolUse", "additionalContext": out}})
        if out:
            print(out)
    except Exception:
        pass   # silence over a blocked prompt, always
    return 0


if __name__ == "__main__":
    sys.exit(main())
