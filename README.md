# context-line

A plugin for Claude Code that tells you when a session has gotten heavy and
it's time to start a fresh one — then writes the handoff and gives you the
prompt to paste.

It can feel like it's cutting you off mid-flow. It's for the better: every
turn re-sends the whole conversation, so a 200k-token session pays for 200k
tokens on every single prompt, and a compacted one has already lost detail.

## what it does

Before each prompt, and after each tool call so a long agentic turn can't
run past it, a hook reads how much context the last turn carried. Past the
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

It learns. If you act on a nudge, fine. If you talk past it (more than two
prompts), or the model keeps working (20k more context), the line drops 10k
for next time (once per session at most), down to a floor of 80k. The
point is to catch you earlier, not to give up. Repeat nudges in the same
session get firmer.

`/handoff` does the same wrap-up on demand, whenever you want it.

## install

```
/plugin marketplace add iShaldam/context-line
/plugin install context-line@context-line
```

Needs `python3` on the system (stdlib only, no packages).

## settings

Environment variables, all optional:

| variable | default | meaning |
|---|---|---|
| `CONTEXT_LINE_LINE` | `150000` | tokens of context that trigger a nudge |
| `CONTEXT_LINE_FLOOR` | `80000` | the learned line never drops below this |
| `CONTEXT_LINE_MIN_GROWTH` | `40000` | growth past the first turn needed before a nudge |
| `CONTEXT_LINE_ADAPT` | `1` | `0` keeps the line fixed |
| `CONTEXT_LINE_HANDOFF` | — | always write the handoff to this file |

On a 1M-context model you may want a higher line; on a tight plan, a lower one.

## privacy

Everything stays on your machine. The state file and `nudges.jsonl` log hold
session ids, token counts and timestamps — never prompt text. State lives in
the plugin data folder (or `~/.local/state/context-line/`) and prunes itself
after a week.

## never blocks

Any error — an unreadable transcript, a full disk, a format change — means
the hook prints nothing and your prompt or tool call goes through untouched.

## development

```
make check      # manifest validation, tests, and a canary that plants bugs
make leakscan   # run before any push
```

MIT licensed.
