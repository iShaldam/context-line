#!/usr/bin/env python3
"""Tell the model to stop and hand off once a session gets heavy.

Every turn re-sends the whole context, so a big session pays its size on
every prompt. This UserPromptSubmit hook reads the transcript's last usage
row and, once the session crosses a line (or gets compacted), asks the model
to write a handoff and give the user a paste-ready prompt for a new session.

It learns from what the user does next. A nudge followed by the session going
quiet is "taken"; one the user talks past is "ignored". Ignored nudges lower
the line for next time -- the point is to catch it earlier, not to give up --
and every nudge after the first in a session is firmer.

Stdlib only. Any failure means silence: this hook must never block a prompt.
"""
import datetime, json, os, sys, time

STEP = 10000         # how far one ignored nudge moves the line
RENUDGE = 60000      # context growth before nudging the same session again
TAKEN_WITHIN = 2     # prompts after a nudge that still count as acting on it
QUIET = 3600         # seconds of silence after a nudge that count as taken
TAIL = 400_000       # bytes of transcript to read from the end


def _int_env(name, default):
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


def settings():
    return {
        "line": _int_env("CONTEXT_LINE_LINE", 150000),
        "floor": _int_env("CONTEXT_LINE_FLOOR", 80000),
        "adapt": os.environ.get("CONTEXT_LINE_ADAPT", "1") != "0",
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
    with open(os.path.join(state_dir(), "nudges.jsonl"), "a") as f:
        f.write(json.dumps(row) + "\n")


def context_of(transcript):
    """(context tokens carried by the last turn, whether it was compacted)."""
    ctx, compacted = 0, False
    try:
        with open(transcript, "rb") as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - TAIL))
            lines = f.read().decode("utf-8", "ignore").splitlines()
    except OSError:
        return 0, False
    for line in reversed(lines):
        if '"isCompactSummary":true' in line.replace(" ", ""):
            compacted = True
        if ctx:
            continue
        try:
            u = (json.loads(line).get("message") or {}).get("usage")
        except (ValueError, AttributeError):
            continue
        if u:
            ctx = ((u.get("input_tokens") or 0) + (u.get("cache_read_input_tokens") or 0)
                   + (u.get("cache_creation_input_tokens") or 0))
    return ctx, compacted


def _settle(s, cfg):
    """Grade nudges whose session has moved on: taken if it went quiet."""
    now = time.time()
    for sid, r in s["sessions"].items():
        if r.get("nudged_at") and r.get("graded") is None:
            if r.get("prompts_since_nudge", 0) > TAKEN_WITHIN:
                r["graded"] = "ignored"
                if cfg["adapt"]:
                    s["line"] = max(cfg["floor"], s["line"] - STEP)
            elif now - r.get("seen", now) > QUIET:
                r["graded"] = "taken"
            else:
                continue
            _log({"ts": now, "session": sid, "outcome": r["graded"],
                  "ctx": r.get("nudge_ctx"), "line_now": s["line"]})


def message(ctx, compacted, n, path):
    why = ("this session was compacted, so earlier detail is already lossy"
           if compacted else f"this session carries ~{ctx // 1000}k tokens, re-sent every turn")
    tone = ("Say it plainly before anything else" if n == 1
            else f"This is nudge #{n} and the user kept going -- lead with it, firmly")
    return (f"context-line: START A FRESH SESSION. {why}. {tone}: finish or pause the "
            f"current step, then (1) add a dated section to {path} with what is done, what "
            "is next and any decisions made, keeping what is already there, (2) give the "
            "user one fenced ```text block to paste into a new session: the one job, "
            f"'read {path} first', and the first next step. "
            "Do not start new heavy work in this session.")


def check(session_id, transcript, cwd=""):
    """Return an instruction for the model, or '' when the session is fine."""
    if not session_id or not transcript:
        return ""
    cfg = settings()
    s = _load(cfg)
    r = s["sessions"].setdefault(session_id, {})
    r["seen"] = time.time()
    if r.get("nudged_at"):
        r["prompts_since_nudge"] = r.get("prompts_since_nudge", 0) + 1
    os.makedirs(state_dir(), exist_ok=True)
    _settle(s, cfg)

    ctx, compacted = context_of(transcript)
    last = r.get("nudge_ctx")
    due = (compacted and not r.get("nudged_compact")) or (
        ctx >= s["line"] and (last is None or ctx >= last + RENUDGE))
    if not due:
        _save(s)
        return ""

    n = r.get("nudges", 0) + 1
    r.update(nudges=n, nudged_at=time.time(), nudge_ctx=ctx,
             prompts_since_nudge=0, graded=None)
    if compacted:
        r["nudged_compact"] = True
    _log({"ts": time.time(), "session": session_id, "event": "nudge",
          "ctx": ctx, "compacted": compacted, "line": s["line"], "n": n})
    _save(s)
    return message(ctx, compacted, n, handoff_path(cwd, session_id))


def main():
    try:
        p = json.load(sys.stdin)
        out = check(p.get("session_id"), p.get("transcript_path"), p.get("cwd") or "")
        if out:
            print(out)
    except Exception:
        pass   # silence over a blocked prompt, always
    return 0


if __name__ == "__main__":
    sys.exit(main())
