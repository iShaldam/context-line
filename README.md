# context-line

A plugin for Claude Code that tells you when a session has gotten heavy and
it's time to start a fresh one — then writes the handoff and gives you the
prompt to paste.

It can feel like it's cutting you off mid-flow. It's for the better: every
turn re-sends the whole conversation, so a 200k-token session pays for 200k
tokens on every single prompt, and a compacted one has already lost detail.

## what it does

Before each prompt, a hook reads how much context the last turn carried.
Past the line (150k by default), or right after a compaction, the model is
asked to:

1. finish or pause the current step,
2. add a dated section to a handoff file — what's done, what's next, what
   was decided,
3. give you one fenced block to paste into a new session.

The handoff goes to `HANDOFF.md` at the root of the current git repo, or to
the plugin's state folder when you're not in one.

It learns. If you act on a nudge, fine. If you talk past it (more than two
prompts), the line drops 10k for next time, down to a floor of 80k. The
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
the hook prints nothing and your prompt goes through untouched.

## development

```
make check      # manifest validation, tests, and a canary that plants bugs
make leakscan   # run before any push
```

MIT licensed.
