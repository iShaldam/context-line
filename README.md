# context-line

A plugin for Claude Code that tells you when a session has gotten heavy and
it's time to start a fresh one — then writes the handoff and gives you the
prompt to paste.

It can feel like it's cutting you off mid-flow. It's for the better: every
turn re-sends the whole conversation, so a 200k-token session pays for 200k
tokens on every single prompt, and a compacted one has already lost detail.

## what it does

Before each prompt, and after each batch of tool calls so a long agentic
turn can't run past it, a hook reads how much context the last turn carried. Past the
line (150k by default), or right after a compaction, the model is asked to:

1. stop at the next safe point — no new task, no browsing, builds or test runs,
2. add a dated section to a handoff file — what's done, what's next, what
   was decided,
3. give you one fenced block to paste into a new session.

Only growth counts: a fresh session already carries its tools, skills and
connectors (often 100k+), so there's no nudge until the session has grown at
least 40k past its first turn. A fresh one would be just as big.

The handoff goes to `HANDOFF.md` at the root of the current git repo, or to
the plugin's state folder when you're not in one.

Keep going past a nudge and the next one comes 30k later, firmer.

`/handoff` does the same wrap-up on demand, whenever you want it.

In the Claude desktop app the paste block ends with one more line naming
the old session, and the new session renames it to `done: <title>`, so the
sidebar shows what's finished. If the old session's last turn didn't complete
(blocked, or a question left open) it gets `handed off: <title>` instead, so
nobody mistakes an unfinished job for a done one. Nothing gets archived or deleted: archived
sessions drop out of transcript search. Outside the desktop app there's no
session tool, so the line is left out.

The prompt cache lasts an hour on a subscription and 5 minutes on an API key
or usage credits; the hook reads which from the session's last cache write.
Come back to a heavy session after that and your next prompt re-sends the
whole thing, so the first prompt after the cache has expired is held back
once, with the cost and the handoff spelled out. Send it again to go on. It only fires on sessions already over the line
that have written their handoff: without one, `/handoff` would re-send it all
anyway, so the prompt just goes through.
Scripts and agents that resume heavy sessions (`claude -p --resume`, the
SDK, scheduled jobs) have nobody to send it again, so the guard skips them
(`CLAUDE_CODE_ENTRYPOINT` starting with `sdk`). `CONTEXT_LINE_GAP=0` turns it
off everywhere.

## install

```
/plugin marketplace add iShaldam/context-line
/plugin install context-line@context-line
```

Needs Python 3 on the system as `python3`, `py -3` or `python` (stdlib only,
no packages). Without one the hooks stay silent instead of erroring.

## settings

Environment variables, all optional:

| variable | default | meaning |
|---|---|---|
| `CONTEXT_LINE_LINE` | `150000` | tokens of context that trigger a nudge |
| `CONTEXT_LINE_MIN_GROWTH` | `40000` | growth past the first turn needed before a nudge |
| `CONTEXT_LINE_HANDOFF` | — | always write the handoff to this file |
| `CONTEXT_LINE_GAP` | the cache's TTL | seconds idle before the resume guard holds a prompt back; `0` turns it off |

On a 1M-context model you may want a higher line; on a tight plan, a lower one.

## privacy

Everything stays on your machine. State (one small file per nudged session)
and the `nudges.jsonl` log hold session ids, token counts and timestamps —
never prompt text. When the resume guard holds a prompt back it shows you its
first 300 characters so you can copy them back; that text isn't stored. It all
lives in the plugin data folder (or `~/.local/state/context-line/`); deleting
it only resets the nudge counts.

## blocks only on purpose

Errors never block: an unreadable transcript, a full disk or a format
change means the hook prints nothing and your prompt or tool call goes
through untouched. The one deliberate block is the resume guard, once per
idle gap; sending again always goes through. `CONTEXT_LINE_GAP=0` turns it off.

## development

```
make check      # manifest validation, tests, and a canary that plants bugs
make leakscan   # run before any push
```

MIT licensed.
