# Softer retire: done label + resume-gap guard. Implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Handed-off sessions get labelled `done: ` by their successor, and the first prompt into a heavy session that sat idle past the prompt cache is held back once.

**Architecture:** Everything lives in the one hook, `hooks/context_line.py`. Part A only changes text: the nudge message and `commands/handoff.md` ask the old session to add a rename line to its paste block, and the successor follows that line. Part B adds `resume_guard()`, which runs first on UserPromptSubmit. It reads the time of the last API call from the transcript tail, and when the session is over the line and idle past `CONTEXT_LINE_GAP`, it prints `{"decision": "block", ...}` once per idle gap. Part B ships only if the Task 2 spike shows a blocked prompt skips the API call.

**Tech Stack:** Python 3 stdlib (must run on 3.9), unittest, bash `selftest.sh` plants, `claude -p` for live canaries.

**Spec:** `docs/superpowers/specs/2026-09-25-retire-migrated-softer-design.md`. Read it first.

## Global Constraints

- Stdlib only. The hook must run on the system Python hooks get (3.9 on macOS). No 3.10+ syntax.
- Errors never block. The only deliberate block is the resume-gap guard, once per idle gap. Sending again always goes through.
- State and `nudges.jsonl` never hold prompt text.
- The label is exactly `done: ` as a title prefix. Never archive, delete or move a session or transcript.
- `CONTEXT_LINE_GAP` is in seconds: default `3600`, `0` = off.
- `make check` exits 0 at the end of every task. `make leakscan` exits 0 before anything is pushed.
- This repo is going public. Nothing private goes in it. The private sibling port is listed in the local `HANDOFF.md` (git-excluded).
- Work on `main`, commit after each task, push nothing. Commit messages are short and lowercase, with no trailing period and no attribution footers.
- Tests use synthetic transcripts only, never a real session.

## Review Focus

1. **The new prompt is already in the transcript when the hook runs.** It has a fresh timestamp and no usage, so the gap must come from the last *usage* row, or it's always ~0. Pinned in Task 3 (`test_context_of_returns_last_call_time`).
2. **System Python 3.9 rejects the trailing `Z`.** Without the swap every timestamp fails to parse and the guard never fires, with no error. Pinned in Task 5 (`test_system_python_parses_timestamps`, run through `/usr/bin/python3`).
3. **A bug inside the guard.** It must not block, and it must not cost the normal nudge. Pinned in Task 5 (`test_broken_guard_still_nudges`).
4. **The echoed prompt.** It is shown to the user in the block reason and must never reach state or the log. Pinned in Task 4 (`test_prompt_echoed_but_never_stored`).
5. **A tool call in a long-idle session.** Mid-turn events never block, even when the transcript looks idle and heavy. Pinned in Task 5 (`test_idle_tool_event_never_blocks`).

---

### Task 1: rename line in the nudge and in /handoff (part A)

**Files:**
- Modify: `hooks/context_line.py:175-185` (`message()`; new `RENAME_STEP` just above it)
- Modify: `commands/handoff.md` (new step 5)
- Modify: `tests/test_context_line.py` (new class `DoneLabel`)
- Modify: `scripts/selftest.sh` (one plant)

**Interfaces:**
- Produces: module constant `RENAME_STEP: str`. `message(ctx, compacted, n, path)` keeps its signature and now ends with `(3) {RENAME_STEP}`.

- [ ] **Step 1: Write the failing tests**

Add this class to `tests/test_context_line.py`, after `class Threshold`:

```python
class DoneLabel(Base):
    """The old session names itself in the paste block; the new one labels it done."""
    LINE = 'first: rename session <id> to "done: <title>"'

    def test_nudge_asks_for_the_rename_line(self):
        self.at(150_000)
        out = cl.check("s1", self.transcript)
        self.assertIn(self.LINE, out)
        self.assertIn('get_session with "self"', out)
        self.assertIn("don't archive it", out)

    def test_compaction_nudge_asks_too(self):
        self.write({"isCompactSummary": True}, usage_row(20_000))
        self.assertIn(self.LINE, cl.check("s1", self.transcript))

    def test_handoff_command_carries_the_same_line(self):
        with open(os.path.join(ROOT, "commands", "handoff.md")) as f:
            text = f.read()
        self.assertIn(self.LINE, text)
        self.assertIn("don't archive it", text)
```

- [ ] **Step 2: Run them and watch them fail**

Run: `python3 -m unittest discover -s tests -k DoneLabel -v`
Expected: 3 FAIL (`LINE` not found).

- [ ] **Step 3: Implement**

In `hooks/context_line.py`, insert above `def message(`:

```python
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
```

In `message()`, change the last line of the return from

```python
            f"'read {path} first', and the first next step.")
```

to

```python
            f"'read {path} first', and the first next step. (3) {RENAME_STEP}")
```

In `commands/handoff.md`, append after step 4:

```markdown
5. If a tool can tell you this session's own id and title (in the Claude
   desktop app: `get_session` with `"self"`), add one last line to that
   block, outside the 80 words:
   `first: rename session <id> to "done: <title>" (skip if it already starts with "done: "; don't archive it; if the rename fails, say so and carry on)`
   Outside the desktop app there is no such tool; leave the line out.
```

In `scripts/selftest.sh`, add before `exit $missed`:

```bash
plant "rename step dropped"     's/first: rename session <id> to/first: to/'
```

- [ ] **Step 4: Run everything**

Run: `make check`
Expected: exit 0. All tests pass, and selftest prints `caught 'rename step dropped'` with no `MISSED`.

- [ ] **Step 5: Commit**

```bash
git add hooks/context_line.py commands/handoff.md tests/test_context_line.py scripts/selftest.sh
git commit -m "handoff paste block names the old session so the new one labels it done"
```

---

### Task 2: spike: does a blocked prompt skip the API call? (go/no-go for part B)

**Files:** none in the repo. Throwaway files go in a temp dir. The result goes in the local `HANDOFF.md`.

**Interfaces:** Produces a decision. **PASS**: do Tasks 3-5, then Task 6 and Task 7 in full. **FAIL**: skip Tasks 3-5, do only the "B dropped" steps of Tasks 6-7.

- [ ] **Step 1: Run the CLI spike** (uses haiku, costs cents)

```bash
T=$(mktemp -d) && mkdir -p "$T/plug/.claude-plugin" "$T/plug/hooks" "$T/repo" && cd "$T/repo" && git init -q
cat > "$T/plug/.claude-plugin/plugin.json" <<'EOF'
{"name": "block-spike", "version": "0.0.0", "description": "throwaway: always blocks the prompt"}
EOF
cat > "$T/plug/hooks/hooks.json" <<'EOF'
{"hooks": {"UserPromptSubmit": [{"hooks": [{"type": "command",
  "command": "echo '{\"decision\": \"block\", \"reason\": \"spike: blocked\"}'"}]}]}}
EOF
SID=$(claude -p --model haiku --output-format json "say ok" | python3 -c 'import json,sys; print(json.load(sys.stdin)["session_id"])')
TR=$(find ~/.claude/projects -name "$SID.jsonl" | head -1)
before=$(grep -c '"usage"' "$TR")
claude -p --model haiku --output-format json --plugin-dir "$T/plug" --resume "$SID" "say ok again" > "$T/resume.json" 2> "$T/resume.err"; echo "resume exit=$?"
after=$(grep -c '"usage"' "$TR")
claude -p --model haiku --output-format json --plugin-dir "$T/plug" "say ok" > "$T/fresh.json" 2> "$T/fresh.err"; echo "fresh exit=$?"
echo "usage rows: before=$before after=$after"
for f in resume fresh; do echo "== $f"; cat "$T/$f.json" "$T/$f.err"; echo; done
echo "T=$T"
```

**PASS** means all three hold: `after == before`, `resume.json` shows no input tokens (no `usage`, or `input_tokens` 0, or `total_cost_usd` 0), and `fresh.json` shows the same. Anything else is a **FAIL**.

- [ ] **Step 2: Desktop check: does the blocked text stay in the input box?**

Only if Step 1 passed. Create `$T/repo2/.claude/settings.json` (a project-level hook only, never a global one):

```bash
mkdir -p "$T/repo2/.claude" && cd "$T/repo2" && git init -q
cat > .claude/settings.json <<'EOF'
{"hooks": {"UserPromptSubmit": [{"hooks": [{"type": "command",
  "command": "echo '{\"decision\": \"block\", \"reason\": \"spike: blocked\"}'"}]}]}}
EOF
echo "$T/repo2"
```

Ask the user with AskUserQuestion: "Open a desktop session in `<T>/repo2`, type `hello there` and send. After the block, is `hello there` still in the input box?" Offer three options: kept, lost, can't check. **Kept**: remove the echo in Task 4 Step 5. **Lost** or **can't check**: keep the echo.

- [ ] **Step 3: Record the result**

Add a dated section to the local `HANDOFF.md` with the Step 1 numbers (before/after rows, the JSON usage fields), the verdict (PASS/FAIL) and the Step 2 answer. Remove the throwaway dirs with `rm -rf "$T"`. The throwaway session transcripts stay; they're harmless.

---

### Task 3: last-call timestamp and a shared "over the line" test

Skip if Task 2 failed.

**Files:**
- Modify: `hooks/context_line.py`: new `_when()` after `_usage()`; `context_of()` at :131-146; new `_heavy()` above `_check`; `_check()` at :214 and :222-224
- Modify: `tests/test_context_line.py`: imports, `usage_row`, new `iso()`, `Base.idle()`, new class `Timestamps`

**Interfaces:**
- Produces: `context_of(transcript) -> (ctx: int, compacted: bool, when: float | None)`. `when` is the epoch time of the last row that carries usage.
- Produces: `_heavy(ctx: int, base: int, s: dict, cfg: dict) -> bool`
- Produces (tests): `usage_row(ctx, ts=None)`, `iso(t) -> str`, `Base.idle(ctx=200_000, base=20_000, secs=7200)`

- [ ] **Step 1: Test helpers and the failing tests**

In `tests/test_context_line.py`, change the import line to

```python
import datetime, json, os, subprocess, sys, tempfile, time, unittest
```

Replace `usage_row` with this and add `iso` below it:

```python
def usage_row(ctx, ts=None):
    row = {"type": "assistant", "message": {"usage": {
        "input_tokens": 10, "cache_read_input_tokens": ctx - 10,
        "cache_creation_input_tokens": 0}}}
    if ts is not None:
        row["timestamp"] = iso(ts)
    return row


def iso(t):
    """A transcript timestamp: UTC, milliseconds, trailing Z."""
    d = datetime.datetime.fromtimestamp(t, datetime.timezone.utc)
    return d.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
```

Add to `class Base`, after `at()`:

```python
    def idle(self, ctx=200_000, base=20_000, secs=2 * 3600):
        """A session whose last API call was `secs` ago."""
        now = time.time()
        self.write(usage_row(base, ts=now - secs - 60), usage_row(ctx, ts=now - secs))
```

Add this class after `class Baseline`:

```python
class Timestamps(Base):
    def test_context_of_returns_last_call_time(self):
        # the new prompt is already written when the hook runs: fresh stamp, no usage
        t = time.time() - 7200
        self.write(usage_row(20_000, ts=t - 60), usage_row(150_000, ts=t),
                   {"type": "user", "timestamp": iso(time.time())})
        ctx, compacted, when = cl.context_of(self.transcript)
        self.assertEqual((ctx, compacted), (150_000, False))
        self.assertAlmostEqual(when, t, places=2)

    def test_no_timestamp_is_none(self):
        self.at(150_000)
        self.assertIsNone(cl.context_of(self.transcript)[2])

    def test_bad_timestamp_is_none(self):
        row = usage_row(150_000)
        row["timestamp"] = "yesterday"
        self.write(row)
        self.assertIsNone(cl.context_of(self.transcript)[2])

    def test_missing_transcript_has_no_time(self):
        self.assertEqual(cl.context_of(os.path.join(self.dir, "nope.jsonl")), (0, False, None))
```

- [ ] **Step 2: Watch them fail**

Run: `python3 -m unittest discover -s tests -k Timestamps -v`
Expected: FAIL/ERROR (`context_of` returns 2 values).

- [ ] **Step 3: Implement**

In `hooks/context_line.py`, add after `_usage()`:

```python
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
```

Replace `context_of()` with:

```python
def context_of(transcript):
    """(context tokens carried by the last turn, whether it was compacted,
    epoch time of that last API call or None).

    The time comes from the last row that carries usage, not the last row:
    by the time a prompt hook runs, the new prompt may already be written.
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
                when = _when(line)
    return ctx, compacted, when
```

Add above `def check(`:

```python
def _heavy(ctx, base, s, cfg):
    """Over the line, counting only growth past the session's first turn."""
    return ctx >= s["line"] and ctx - base >= cfg["min_growth"]
```

In `_check`, change `ctx, compacted = context_of(transcript)` to

```python
    ctx, compacted, _ = context_of(transcript)
```

and change the `due` expression to

```python
    due = (compacted and not r.get("nudged_compact")) or (
        _heavy(ctx, base, s, cfg) and (last is None or ctx >= last + RENUDGE))
```

- [ ] **Step 4: Run everything**

Run: `make check`
Expected: exit 0. The existing plants `line comparison flipped` and `min growth ignored` now land inside `_heavy` and are still caught.

- [ ] **Step 5: Commit**

```bash
git add hooks/context_line.py tests/test_context_line.py
git commit -m "read the last api call's time and share the over-the-line test"
```

---

### Task 4: resume_guard (part B logic)

Skip if Task 2 failed.

**Files:**
- Modify: `hooks/context_line.py`: `settings()` at :43-49; new `_ago()`, `gap_reason()`, `resume_guard()`, `_resume_guard()` placed after `_check()`
- Modify: `tests/test_context_line.py`: new class `Gap`
- Modify: `scripts/selftest.sh`: four plants

**Interfaces:**
- Consumes: `context_of() -> (ctx, compacted, when)`, `_heavy()`, `baseline_of()`, `handoff_path()`, `_load()`, `_save()`, `_log()`, `state_dir()`
- Produces: `resume_guard(session_id, transcript, cwd="", prompt="") -> str` (the block reason, or `""`)
- Produces: `gap_reason(ctx: int, gap: float, path: str, prompt: str = "") -> str`
- Produces: `settings()["gap"]: int`
- State: `sessions[sid]["gap_blocked"] = when` (float). Log events: `gap_block`, `gap_resent`, each with `ctx` and `gap`.

- [ ] **Step 1: Write the failing tests**

Add after `class MidTurn`:

```python
class Gap(Base):
    """A heavy session idle past the prompt cache: hold the first prompt back once."""

    def guard(self, **kw):
        return cl.resume_guard("s1", self.transcript, self.dir, **kw)

    def events(self):
        with open(os.path.join(os.environ["CLAUDE_PLUGIN_DATA"], "nudges.jsonl")) as f:
            return [json.loads(l).get("event") for l in f]

    def test_idle_heavy_session_is_held_back(self):
        self.idle()
        out = self.guard()
        self.assertIn("not sent", out)
        self.assertIn("~200k", out)
        self.assertIn("idle 2h", out)
        self.assertEqual(self.events(), ["gap_block"])

    def test_short_idle_goes_through(self):
        self.idle(secs=30 * 60)
        self.assertEqual(self.guard(), "")

    def test_under_line_goes_through(self):
        self.idle(ctx=140_000)
        self.assertEqual(self.guard(), "")

    def test_under_min_growth_goes_through(self):
        self.idle(ctx=160_000, base=130_000)
        self.assertEqual(self.guard(), "")

    def test_resend_goes_through(self):
        self.idle()
        self.assertTrue(self.guard())
        self.assertEqual(self.guard(), "")
        self.assertEqual(self.events(), ["gap_block", "gap_resent"])

    def test_new_gap_after_a_new_turn_blocks_again(self):
        self.idle()
        self.guard()
        self.guard()
        self.idle(ctx=210_000, secs=90 * 60)   # the resend ran, then it sat again
        self.assertIn("not sent", self.guard())

    def test_gap_zero_turns_it_off(self):
        os.environ["CONTEXT_LINE_GAP"] = "0"
        self.idle()
        self.assertEqual(self.guard(), "")

    def test_missing_timestamp_goes_through(self):
        self.at(200_000)
        self.assertEqual(self.guard(), "")

    def test_reason_points_at_existing_handoff(self):
        path = os.path.join(self.dir, "HANDOFF.md")
        os.environ["CONTEXT_LINE_HANDOFF"] = path
        open(path, "w").close()
        self.idle()
        out = self.guard()
        self.assertIn(path, out)
        self.assertIn("updated", out)
        self.assertNotIn("send /handoff", out)

    def test_reason_suggests_handoff_when_none_exists(self):
        self.idle()
        self.assertIn("send /handoff", self.guard())

    def test_prompt_echoed_but_never_stored(self):
        prompt = "secret plan " + "x" * 400
        self.idle()
        out = self.guard(prompt=prompt)
        self.assertTrue(out.endswith(prompt[:300]))
        self.assertNotIn(prompt[:301], out)
        for name in ("state.json", "nudges.jsonl"):
            with open(os.path.join(os.environ["CLAUDE_PLUGIN_DATA"], name)) as f:
                self.assertNotIn("secret plan", f.read())
```

- [ ] **Step 2: Watch them fail**

Run: `python3 -m unittest discover -s tests -k Gap -v`
Expected: ERROR (`module 'context_line' has no attribute 'resume_guard'`).

- [ ] **Step 3: Implement**

In `settings()`, add a key:

```python
        "gap": _int_env("CONTEXT_LINE_GAP", 3600),
```

Add after `_check()`:

```python
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
```

In `scripts/selftest.sh`, add before `exit $missed`:

```bash
plant "gap comparison flipped"  's/if gap < cfg\["gap"\]:/if gap >= cfg["gap"]:/'
plant "resend blocked again"    's/if r.get("gap_blocked") == when:/if False:/'
plant "gap check skips the line" 's/if not _heavy(ctx, base, s, cfg):/if False:/'
plant "gap off ignored"         's/ or settings()\["gap"\] <= 0:/:/'
```

- [ ] **Step 4: Run everything**

Run: `make check`
Expected: exit 0, with all four new plants `caught`.

- [ ] **Step 5: Only if Task 2 Step 2 answered "kept"**

Delete the two `if prompt:` lines in `gap_reason()` and the test `test_prompt_echoed_but_never_stored`, then run `make check` again (exit 0).

- [ ] **Step 6: Commit**

```bash
git add hooks/context_line.py tests/test_context_line.py scripts/selftest.sh
git commit -m "hold back the first prompt into a heavy session idle past the cache"
```

---

### Task 5: wire the guard into main()

Skip if Task 2 failed.

**Files:**
- Modify: `hooks/context_line.py:240-255` (`main()`)
- Modify: `tests/test_context_line.py`: imports, class `NeverBlocks`
- Modify: `scripts/selftest.sh`: two plants

**Interfaces:**
- Consumes: `resume_guard(session_id, transcript, cwd, prompt) -> str`, `check(...)`
- Produces: on UserPromptSubmit, stdout `{"decision": "block", "reason": <str>}` when held back. Nothing else changes.

- [ ] **Step 1: Write the failing tests**

Change the import line to

```python
import contextlib, datetime, io, json, os, subprocess, sys, tempfile, time, unittest
```

Add to `class NeverBlocks`:

```python
    def prompt_payload(self, **extra):
        return dict({"session_id": "abc123", "transcript_path": self.transcript,
                     "cwd": self.dir, "permission_mode": "default",
                     "hook_event_name": "UserPromptSubmit", "prompt": "hi"}, **extra)

    def test_idle_prompt_prints_block_json(self):
        self.idle()
        r = self.run_hook(json.dumps(self.prompt_payload()))
        self.assertEqual(r.returncode, 0)
        out = json.loads(r.stdout)
        self.assertEqual(out["decision"], "block")
        self.assertIn("not sent", out["reason"])

    def test_idle_tool_event_never_blocks(self):
        self.idle()
        r = self.run_hook(json.dumps(self.tool_payload()))
        out = json.loads(r.stdout)
        self.assertNotIn("decision", out)
        self.assertEqual(out["hookSpecificOutput"]["hookEventName"], "PostToolUse")

    def test_held_back_prompt_does_not_count_toward_grading(self):
        self.write(usage_row(20_000, ts=time.time() - 60), usage_row(200_000, ts=time.time()))
        self.assertTrue(cl.check("abc123", self.transcript))   # nudged
        self.idle()                                            # then it sat for 2h
        r = self.run_hook(json.dumps(self.prompt_payload()))
        self.assertEqual(json.loads(r.stdout)["decision"], "block")
        self.assertEqual(self.state()["sessions"]["abc123"]["prompts_since_nudge"], 0)

    def test_broken_guard_still_nudges(self):
        self.at(160_000)
        out = io.StringIO()
        with mock.patch.object(cl, "resume_guard", side_effect=RuntimeError("boom")), \
                mock.patch("sys.stdin", io.StringIO(json.dumps(self.prompt_payload()))), \
                contextlib.redirect_stdout(out):
            self.assertEqual(cl.main(), 0)
        self.assertIn("START A FRESH SESSION", out.getvalue())

    @unittest.skipUnless(os.path.exists("/usr/bin/python3"), "no system python here")
    def test_system_python_parses_timestamps(self):
        # hooks get the system python (3.9 on macOS); its fromisoformat rejects a trailing Z
        self.idle()
        env = dict(os.environ, PATH="/usr/bin:/bin")
        r = subprocess.run(["/usr/bin/python3", HOOK], input=json.dumps(self.prompt_payload()),
                           text=True, capture_output=True, env=env, timeout=10)
        self.assertEqual(json.loads(r.stdout)["decision"], "block")
```

- [ ] **Step 2: Watch them fail**

Run: `python3 -m unittest discover -s tests -k NeverBlocks -v`
Expected: the block/grading/system-python tests FAIL (no block printed). `test_idle_tool_event_never_blocks` and `test_broken_guard_still_nudges` may already pass; that's fine, since they guard against the wiring going wrong.

- [ ] **Step 3: Implement**

Replace `main()` with:

```python
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
```

In `scripts/selftest.sh`, add before `exit $missed`:

```bash
plant "block on tool events"    's/        if not tool:$/        if True:/'
plant "broken guard kills nudge" 's/                reason = ""   # a broken guard/                raise   # a broken guard/'
```

- [ ] **Step 4: Run everything**

Run: `make check`
Expected: exit 0. Both new plants are `caught`, and the existing `errors escape main` plant still applies.

- [ ] **Step 5: Commit**

```bash
git add hooks/context_line.py tests/test_context_line.py scripts/selftest.sh
git commit -m "prompt hook runs the resume guard first and prints the block"
```

---

### Task 6: README and module docstring

**Files:**
- Modify: `README.md`
- Modify: `hooks/context_line.py:1-20` (docstring; only if B shipped)

- [ ] **Step 1: Done label (always)**

In `README.md`, after the line "`/handoff` does the same wrap-up on demand, whenever you want it.", add:

```markdown
In the Claude desktop app the paste block ends with one more line naming
the old session, and the new session renames it to `done: <title>`, so the
sidebar shows what's finished. Nothing gets archived or deleted: archived
sessions drop out of transcript search. Outside the desktop app there's no
session tool, so the line is left out.
```

- [ ] **Step 2a: If B shipped: resume guard, settings, promise**

After the paragraph from Step 1, add:

```markdown
The prompt cache lasts about an hour. Come back to a heavy session after
that and your next prompt re-sends the whole thing, so the first prompt
after an hour idle is held back once, with the cost and the handoff spelled
out. Send it again to go on. It only fires on sessions already over the line.
```

Add a row to the settings table:

```markdown
| `CONTEXT_LINE_GAP` | `3600` | seconds idle before the resume guard holds a prompt back; `0` turns it off |
```

After "On a 1M-context model you may want a higher line; on a tight plan, a lower one." add:

```markdown
With the API's 5-minute prompt cache, set `CONTEXT_LINE_GAP=300`.
```

In `## privacy`, after the first sentence about what state holds, add:

```markdown
When the resume guard holds a prompt back it shows you its first 300
characters so you can copy them back; that text isn't stored.
```

(Leave that sentence out if Task 4 Step 5 removed the echo.)

Replace the `## never blocks` section with:

```markdown
## blocks only on purpose

Errors never block: an unreadable transcript, a full disk or a format
change means the hook prints nothing and your prompt or tool call goes
through untouched. The one deliberate block is the resume guard, once per
idle gap; sending again always goes through. `CONTEXT_LINE_GAP=0` turns it off.
```

In `hooks/context_line.py`, replace the docstring's last paragraph (`Stdlib only. Any failure means silence: this hook must never block a prompt.`) with:

```
One prompt can be held back on purpose: the first one into a heavy session
that sat idle past the prompt cache, which would re-send everything. Sending
it again goes through. Otherwise stdlib only, and any failure means silence:
an error must never block a prompt.
```

- [ ] **Step 2b: If B was dropped (Task 2 failed)**

After the paragraph from Step 1, add (fill in the version from `claude --version` and the numbers the spike saw):

```markdown
There's no guard for coming back to a session after the prompt cache
expired: a blocked prompt still reached the API in testing (Claude Code
<version>: <what the spike saw>), so a hook can't stop that re-send.
```

- [ ] **Step 3: Check and commit**

Run: `make check`
Expected: exit 0.

```bash
git add README.md hooks/context_line.py
git commit -m "readme covers the done label and the resume guard"
```

---

### Task 7: live canaries and acceptance

**Files:** none in the repo, except the local `HANDOFF.md`.

- [ ] **Step 1: Canary A (CLI: nudge, handoff, no rename line)**

```bash
T=$(mktemp -d) && cd "$T" && git init -q && echo "# scratch" > README.md
CONTEXT_LINE_LINE=1000 CONTEXT_LINE_MIN_GROWTH=0 claude -p --model haiku \
  --plugin-dir ~/Projects/context-line "list the files here, then read README.md"
ls "$T"; cat "$T/HANDOFF.md"
```

Expected: the reply stops and gives one ```text block, and `HANDOFF.md` exists. There is **no** `first: rename session` line, because the CLI has no session tool. No archive or delete is attempted.

- [ ] **Step 2: Canary B (only if B shipped)**

```bash
T=$(mktemp -d) && cd "$T" && git init -q
export CONTEXT_LINE_LINE=1000 CONTEXT_LINE_MIN_GROWTH=0 CONTEXT_LINE_GAP=5
P=~/Projects/context-line
SID=$(claude -p --model haiku --plugin-dir $P --output-format json "say ok" | python3 -c 'import json,sys; print(json.load(sys.stdin)["session_id"])')
TR=$(find ~/.claude/projects -name "$SID.jsonl" | head -1)
sleep 6
n0=$(grep -c '"usage"' "$TR")
claude -p --model haiku --plugin-dir $P --resume "$SID" "say ok again"; echo "exit=$?"
n1=$(grep -c '"usage"' "$TR")
claude -p --model haiku --plugin-dir $P --resume "$SID" "say ok again"; echo "exit=$?"
n2=$(grep -c '"usage"' "$TR")
echo "usage rows: $n0 -> $n1 (blocked) -> $n2 (resent)"
unset CONTEXT_LINE_LINE CONTEXT_LINE_MIN_GROWTH CONTEXT_LINE_GAP
```

Expected: the first resume prints the "not sent" reason and `n1 == n0`. The second goes through and `n2 > n1`.

- [ ] **Step 3: Label stays searchable (desktop app)**

Ask the user (AskUserQuestion) for one session that is truly finished. Rename it with `set_session_title` to `done: <its title>`. Then run `search_session_transcripts` with default arguments (no `include_archived`) for a phrase only that session contains. Expected: it's in the hits. If it isn't, stop and tell the user, because the spec's searchability claim is wrong.

- [ ] **Step 4: Final gates**

```bash
cd ~/Projects/context-line && make check; echo "check exit=$?"; make leakscan; echo "leakscan exit=$?"
```

Expected: both `exit=0`.

- [ ] **Step 5: Handoff**

Add a dated section to the local `HANDOFF.md`: what shipped (commits), the canary results, whether B shipped, and next steps. The next steps are the private sibling port already listed there, a look at `gap_block` / `gap_resent` counts in `nudges.jsonl` after two weeks, and re-running the context-loss measures around 2026-10-02. Push nothing.
