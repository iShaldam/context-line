---
description: Replay my own Claude Code transcripts and show what heavy sessions cost me
allowed-tools: Bash(python3:*)
---

These numbers come from replaying this machine's Claude Code transcripts
(aggregates only, nothing leaves the machine):

!`python3 "${CLAUDE_PLUGIN_ROOT}/scripts/replay.py"`

Explain them in plain words, in at most 6 short lines: how much of the
context sent went to turns past the line, what cutting to a fresh session at
the line would have saved, and what cold resumes cost. Then one line on
whether the default growth (120k, `CONTEXT_LINE_GROWTH`) looks right for these
sessions. Don't run anything else.
