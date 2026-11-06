# context-line vs context-mode (and the rest)

Checked 2026-09-30. Short version: they fix different leaks, and on one
heavy user's real transcripts the bigger leak was the one context-line fixes.

## what each one does

| | context-line | context-mode (mksglu) |
|---|---|---|
| leak it targets | a session that keeps growing and re-sends itself every turn | big tool output landing in the window |
| how | nudge at +120k past the session's opening, written handoff, hold the first prompt after the cache expires | sandbox tool output in SQLite, return a summary; snapshot and restore across compaction |
| size monitor / stop line | yes | no (throttles repeated calls instead) |
| handoff to a fresh session | yes | no (restores into the same session) |
| cold-cache resume guard | yes | no |
| shrinks tool output | no | yes, claims ~98% on big outputs |
| screenshots / images | n/a | not shrunk |
| adds to every session | 3 hooks, 0 tool definitions | 11 MCP tools (~4.9k tokens), 5 hook events (PreToolUse on Bash, Read, Grep, Agent, mcp__) |
| license | MIT, stdlib python | Elastic-2.0 (source-available, not OSI open source) |
| install side effects | none | its postinstall touches `~/.claude/settings.json` and `installed_plugins.json` (plugin "healing"); I installed it with scripts off in a scratch dir |

The others (RTK, Token Savior, Caveman, claude-context, memsearch, ccusage,
claude-powerline) each shrink output, index code, or display usage. None
documents a stop line plus handoff plus cold-cache guard. A Reddit skill
called cachebeat keeps the cache warm instead of guarding the resume; not
verified beyond the mention.

## proof on real transcripts

`scripts/replay.py` replays your own transcripts (aggregates only) under two
what-ifs, cost in input-token units (cache read 0.1, write 2.0):

One user, 2,130 sessions, 67k turns, 12B context tokens sent:

- turns 120k past their session's opening: 27% of turns, **42% of cost**
- tool-result tokens that are screenshots: ~22%, which context-mode cannot shrink
- context-mode, cautious (90% off results over 10KB): saves 3.1%, costs 3.1% in
  tool definitions, **0.0% net**
- context-mode, best case (98% off results over 1KB): saves 10.4%, **7.2% net**
- context-line, cutting to a fresh session at +120k: saves **15.3%**
- idle over an hour then resumed: 442 turns rewrote 68M tokens, 8% of cost
  (the resume guard's target)

## what this does not prove

- context-line's 15.3% is an upper bound. It assumes every nudge is obeyed and
  the job splits cleanly at the line. Real use of an earlier variant of this
  hook: 704 nudges in 505 sessions over 42 days, 64% acted on (the session
  went quiet within two prompts), 36% talked past.
- context-mode may cost less than 4.9k if the client defers MCP tool
  definitions, and helps more on text-heavy work (logs, DOM snapshots) than
  this user's screenshot-heavy sessions. Numbers are one person's.
- Image size is an estimate (1,500 tokens each); text is chars / 3.6.
- They stack. context-mode slows growth, context-line decides when to stop.
  Not tested together.
