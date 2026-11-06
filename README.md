# context-line

I kept letting Claude Code sessions run long past the point they were worth
it, and the bill for that shows up on every prompt. context-line is a plugin
that tells you when a session has gotten heavy, writes the handoff, and gives
you the prompt to paste into a fresh one.

Every turn re-sends the whole conversation. When I replayed my own sessions
(2,130 of them), a quarter of my turns came after a session had grown 120k
tokens past where it started, and those turns carried 48% of all the context I
sent.

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
turns past the line (+120k): 17,867 (26.6% of turns), 48.1% of tokens, 42.2% of cost
WHAT-IF context-line (cut to fresh at +120k, 456 cuts): saves 15.3% of cost
cold resumes (idle >1h): 442 turns, 68.4M tokens rewritten, 8.0% of cost
```

To see a nudge without waiting for a heavy session, start one with a tiny
growth and ask for something that takes two separate tool calls (growth is
measured between API calls, so the first call alone never trips it):

```
CONTEXT_LINE_GROWTH=100 claude
```

## what it does

Before each prompt, and after each batch of tool calls so a long agentic turn
can't run past it, a hook reads how much context the last turn carried. Once
the session has grown 120k past its own first turn (`CONTEXT_LINE_GROWTH`), or
right after a compaction, it asks Claude to:

1. stop at the next safe point: no new task, no browsing, builds or test runs,
2. add a dated section to a handoff file: what's done, what's next, what was
   decided,
3. give you one fenced block to paste into a new session.

You see one line saying why, like `context-line: ~210k in context, +125k since
it opened; asked Claude to wrap up and write a handoff`, so Claude never stops
for no visible reason.

The trigger is growth, not an absolute number. A fresh session already carries
its tools, skills and connectors: mine start between 80k and 110k, depending on
what's connected. A flat 150k line is 40k of work away for a session that opens
at 110k and 70k away for one that opens at 80k, so it nagged the heavy-setup
sessions early and let the light ones run on. Counting from each session's own
first turn gives every session the same room to work in.

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

The 120k of growth is a cost-and-focus heuristic, not a measured quality
cliff. Nobody has published one for current models. On a typical 80-100k
opening it lands around 200-220k, near Claude Code's own idle-compaction line,
so on a 200k-window model set `CONTEXT_LINE_LINE=150000` as well to get the
handoff before the platform summarizes for you.

Does it get acted on? I ran an earlier variant of this hook (a flat line, then
this growth rule) for 42 days: 704 nudges in 505 sessions, and 316 were taken
(the session went quiet within two prompts) against 178 ignored, 64% taken.
Since I moved to the growth rule (11 days) nudges dropped from about 19 a day
to 10, but the share I acted on fell too, from 67% to 44%. That is under two
weeks of data, not a result.

## resume guard (opt-in)

Come back to a heavy session after the prompt cache has expired (an hour on a
subscription, 5 minutes on an API key or usage credits) and your next prompt
re-sends the whole thing. With `CONTEXT_LINE_GAP=ttl` the first prompt into
such a session is held back once, with the cost and the handoff spelled out.
Send it again to go on.

It only fires on sessions past the line that have already written their
handoff, never on a prompt queued while a tool is running, and never in
scripted runs (`claude -p`, the SDK). It's off by default since 0.4.0:
Claude Code now warns on cold resumes and compacts idle sessions itself.

## settings

Environment variables, all optional:

| variable | default | meaning |
|---|---|---|
| `CONTEXT_LINE_GROWTH` | `120000` | tokens the session has grown past its first turn before a nudge. The main knob |
| `CONTEXT_LINE_LINE` | off | optional absolute line, for example `150000` on a 200k-window model. Nudges once the context passes it and the session has grown `CONTEXT_LINE_MIN_GROWTH` |
| `CONTEXT_LINE_MIN_GROWTH` | `40000` | growth needed before the absolute line counts, so a session that opens big isn't nudged on turn one |
| `CONTEXT_LINE_HANDOFF` | none | always write the handoff to this file |
| `CONTEXT_LINE_GAP` | off | `ttl` turns the resume guard on at the session's cache TTL; a number is seconds |

On a 1M-context model the window isn't the limit, cost is, so the same growth
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
