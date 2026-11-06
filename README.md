# context-line

I kept letting Claude Code sessions run long past the point they were worth
it, and the bill for that shows up on every prompt. context-line is a plugin
that tells you when a session has gotten heavy, writes the handoff, and gives
you the prompt to paste into a fresh one.

Every turn re-sends the whole conversation. When I replayed 45 days of my own
sessions, half my turns ran past 150k tokens, and those turns carried 71% of
all the context I sent.

Claude Code already shows you the size (`/context`, the status line) and
summarizes for you when it runs out (auto-compact, and idle compaction past
about 200k). It doesn't stop at a safe point and leave you a handoff you can
read. That's the part this plugin does.

## install

```
/plugin marketplace add iShaldam/context-line
/plugin install context-line@context-line
```

Needs Python 3 on the system as `python3`, `py -3` or `python` (stdlib only,
no packages). Without one the hooks stay silent instead of erroring. Tested
on Claude Code 2.1.317.

## try it now

`/context-line:report` replays your own transcripts and tells you how much of
your context went to turns past the line, and what cutting there would have
saved. Nothing leaves your machine. Mine:

```
turns above 150k: 33,096 (49.4% of turns), 70.9% of tokens, 62.8% of cost
WHAT-IF context-line (cut to fresh at 150k, 1560 cuts): saves 8.3% of cost
cold resumes (idle >1h): 441 turns, 68.4M tokens rewritten, 8.0% of cost
```

To see a nudge without waiting for a heavy session, start one with a tiny
line and ask for anything that runs a tool:

```
CONTEXT_LINE_LINE=1000 CONTEXT_LINE_MIN_GROWTH=0 claude
```

## what it does

Before each prompt, and after each batch of tool calls so a long agentic turn
can't run past it, a hook reads how much context the last turn carried. Past
the line (150k by default), or right after a compaction, it asks Claude to:

1. stop at the next safe point: no new task, no browsing, builds or test runs,
2. add a dated section to a handoff file: what's done, what's next, what was
   decided,
3. give you one fenced block to paste into a new session.

You see one line saying why, like `context-line: ~162k in context (line 150k);
asked Claude to wrap up and write a handoff`, so Claude never stops for no
visible reason.

Only growth counts: a fresh session already carries its tools, skills and
connectors (mine start around 80k), so there's no nudge until the session has
grown at least 40k past its first turn.

The handoff goes to `HANDOFF.md` at the root of the current git repo, or in the
current folder when you're not in one. `/handoff` does the same wrap-up
whenever you want it, and writes to the same file.

Keep going past a nudge and the next one comes 30k later, firmer. Answer a
nudge with "continue" (or "keep going", "go on", "carry on", "proceed") and
later nudges in that session only note the size; a compaction still asks for
the handoff.

A compaction drops detail, so just before one runs (`PreCompact`) the hook
saves the files the session edited, newest first. The nudge after the
compaction hands Claude that list so the handoff can carry it. Only what the
transcript states: decisions can't be scraped, Claude still writes those.

In the Claude desktop app the paste block ends with one more line naming the
old session and its label, and the new session runs the rename: `done:
<title>` when the old session's work is finished, or `handed off: <title>`
when work is left. The old session picks the label, since it knows. Nothing
gets archived or deleted. Outside the desktop app there's no session tool, so
the line is left out.

## what's already built in

| | Claude Code | context-line |
|---|---|---|
| shows context size | `/context`, status line `context_window` | the nudge says it |
| summarizes a full session | auto-compact, idle compaction past ~200k | no |
| warns on a cold resume | yes, for Pro and Max (2.1.304) | opt-in guard, below |
| stops at a safe point mid-turn | no | yes, after each tool batch |
| writes a handoff you can read and edit | no | `HANDOFF.md`, dated sections |
| paste block for the next session | no | yes |

The 150k line is a cost-and-focus heuristic, not a measured quality cliff.
Nobody has published one for current models. It sits below Claude Code's own
idle-compaction line, so you get the handoff before the platform summarizes
for you.

## resume guard (opt-in)

Come back to a heavy session after the prompt cache has expired (an hour on a
subscription, 5 minutes on an API key or usage credits) and your next prompt
re-sends the whole thing. With `CONTEXT_LINE_GAP=ttl` the first prompt into
such a session is held back once, with the cost and the handoff spelled out.
Send it again to go on.

It only fires on sessions over the line that have already written their
handoff, never on a prompt queued while a tool is running, and never in
scripted runs (`claude -p`, the SDK). It's off by default since 0.4.0:
Claude Code now warns on cold resumes and compacts idle sessions itself.

## settings

Environment variables, all optional:

| variable | default | meaning |
|---|---|---|
| `CONTEXT_LINE_LINE` | `150000` | tokens of context that trigger a nudge |
| `CONTEXT_LINE_MIN_GROWTH` | `40000` | growth past the first turn needed before a nudge |
| `CONTEXT_LINE_HANDOFF` | none | always write the handoff to this file |
| `CONTEXT_LINE_GAP` | off | `ttl` turns the resume guard on at the session's cache TTL; a number is seconds |

On a 1M-context model the window isn't the limit, cost is, so the same line
still makes sense. On a tight plan, try a lower one.

## related tools

- [claude-hud](https://github.com/jarrodwatts/claude-hud) and
  [ccstatusline](https://github.com/sirmalloc/ccstatusline) show context size
  all the time. Use one of them with this: they show, this acts.
- [context-mode](https://github.com/mksglu/context-mode) keeps big tool output
  out of the window. On my transcripts that would have saved 3.1% of cost,
  against 8.3% for cutting at the line; [docs/comparison.md](docs/comparison.md)
  has the replay.
- [claude-mem](https://github.com/thedotmack/claude-mem) carries memory between
  sessions automatically. context-line leaves a file you read and edit
  instead.
- [auto-handoff](https://github.com/obie/auto-handoff) writes a handoff after
  50 idle minutes, while the cache is still warm. It triggers on time, this
  one on size, so they don't overlap much.

## privacy

Everything stays on your machine. State (one small file per nudged session)
and the `nudges.jsonl` log hold session ids, token counts and timestamps,
never prompt text. When the resume guard holds a prompt back it shows you its
first 300 characters so you can copy them back; that text isn't stored. It all
lives in the plugin data folder (or `~/.local/state/context-line/`); deleting
it only resets the nudge counts.

## blocks only on purpose

Errors never block: an unreadable transcript, a full disk or a format change
means the hook prints nothing and your prompt or tool call goes through
untouched. The one deliberate block is the opt-in resume guard, once per idle
gap; sending again always goes through.

## development

```
make check      # manifest validation, tests, and a canary that plants bugs
make leakscan   # run before any push
```

MIT licensed.
