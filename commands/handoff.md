---
description: Write a handoff for this session and give me a prompt to start a fresh one
argument-hint: "[the one job for the next session]"
---

Wrap this session up so a fresh one can pick it up with nothing lost.

1. Finish or pause the current step. Do not start new work.
2. Pick the handoff file: `HANDOFF.md` at the root of the current git repo,
   or, outside a repo, `~/.local/state/context-line/handoffs/<today>-handoff.md`.
3. Add a dated section to it (keep what is already there) with:
   - what is done, with file paths and commit hashes where they exist
   - what is next, in order
   - decisions already made, so the next session does not re-ask them
   - anything that is easy to forget or cost time to find out
4. Reply with one fenced ```text block the user can paste into a new
   session. It names the one job ($ARGUMENTS if given, otherwise the
   obvious next job), says to read the handoff file first, and states the
   first next step. Keep it under 80 words.
5. If a tool can tell you this session's own id and title (in the Claude
   desktop app: `get_session` with `"self"`), add one last line to that
   block, outside the 80 words:
   `first: rename session <id> to "handed off: <title>" if get_session <id> shows its postTurnSummary status_category is not "completed" (blocked or open), otherwise to "done: <title>" (skip if it already starts with "done: " or "handed off: "; don't archive it; if the rename fails, say so and carry on)`
   Outside the desktop app there is no such tool; leave the line out.
