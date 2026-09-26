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
