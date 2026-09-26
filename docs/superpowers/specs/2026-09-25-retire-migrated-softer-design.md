# Retire migrated sessions, the softer version

Date: 2026-09-25. Status: design approved, plan next.

## Why

Once context-line nudges a session into a fresh one, the old session keeps
sitting in the sidebar. They pile up, and resuming one by mistake re-sends
its whole context. The first idea was to remove the migrated-from session,
but only if that provably loses no context and has no downside.

A study of the local transcript history (133 sessions, 16 handoff-based
migrations) came back **softer**. Don't remove anything. Label the old
session instead:

- **No measured context loss.** Across four measures (tool reach-back into
  the predecessor, prompts sent back to the old session, re-explaining in
  the successor, gaps the handoff missed) the count is 0. The sample is
  small (95% upper bounds of 11-18%), and most migrations are under 3h old.
- **Removal has a real cost.** Archiving hides a transcript from default
  `search_session_transcripts` (only `include_archived: true` finds it), and
  32 of 34 past searches used the default. Moving the jsonl breaks `--resume`.
- **Removal saves nothing measurable.** 0 tokens were re-sent by a
  migrated-from session after its successor existed.
- **The waste is somewhere else.** Coming back to a fat session after
  more than 1h re-sends all of it, because the prompt cache has expired:
  24.9M tokens across 73 resumes, median 239k-307k depending on the gap.

That makes two parts: a done label (A) and a resume-gap guard (B). They're
independent, so either can ship without the other.

## Decisions (don't re-ask)

- Label, never remove: no archiving, no moving transcripts.
- The label is a title prefix, `done: `. The sidebar's `mark_completed` is
  out: it only clears a "needs input" dot, and the dot comes back on its own.
- The **successor** applies the label on its first turn, so it lands only
  once a successor really exists.
- The resume-gap guard **blocks once** and lets the resend through. It ships
  only if the spike (B0) shows the block really skips the API call.
- It lands in the plugin first. A private sibling copy of this hook, the one
  that runs for the author today, gets the same change afterwards as
  separate code, the same as the mid-turn fix. That port is tracked in the
  local HANDOFF.md, not in this repo.

## A. Done label

Hooks can't rename sessions. Neither the CLI nor a hook can reach the
desktop app's session tools, so the model does the renaming, on instructions
the plugin already gives.

**Old session (writes the handoff).** Both the nudge text (`message()` in
`hooks/context_line.py`) and `commands/handoff.md` gain one conditional step:

> If a tool can tell you this session's own id and title (in the Claude
> desktop app: `get_session` with `"self"`), add a last line to the paste
> block: `first: rename session <id> to "done: <title>" (don't archive it)`.

The desktop session id (`local_…`) is not the transcript's `session_id`, so
the hook can't fill it in. The model has to look it up. Outside the desktop
app no such tool exists, and the line is left out. The paste block's
80-word cap does not count this line.

**Successor (reads the paste).** It follows the line: `set_session_title`
on the old id. A title that already starts with `done: ` is left alone. If
the rename asks for approval or fails, the successor mentions it and moves
on. It never blocks the job.

**Searchability.** A rename touches the title only. Search matches message
content and filters only on the archive flag, so a labeled session stays in
default search. One live check confirms this (see Testing).

Not handled: going back to a session already labeled done. That happened
0 times in 16 migrations, so the fix is a manual rename.

## B. Resume-gap guard

**B0. Spike first (go/no-go).** A throwaway plugin whose UserPromptSubmit
hook always returns `{"decision": "block", "reason": "…"}`:

1. `claude -p --output-format json` with a fresh session, then with
   `--resume` on a throwaway session. Pass = 0 input tokens / $0, and no
   new assistant usage row in the transcript.
2. Whether the blocked prompt's text stays in the input box, observed in a
   throwaway project that has only a project-level hook, never a global
   one. If nobody can observe it, assume the text is lost.

If 1 fails, drop B and write the finding into the README and HANDOFF.md.

**Trigger.** Checked on UserPromptSubmit only, never on tool events or
subagents. All of these must hold:

- `gap` = now minus the `timestamp` of the transcript's last row that
  carries usage (the last API call, i.e. the last cache touch), and
  `gap >= CONTEXT_LINE_GAP` (seconds, default `3600`, `0` = off)
- the session is over the line, as the nudge defines it: `ctx >= line`
  (the learned line) and `ctx - baseline >= CONTEXT_LINE_MIN_GROWTH`
- this gap hasn't been blocked yet: `state["gap_blocked"] != last_ts`
- a compaction row newer than the last usage row means no block (the next
  prompt re-sends the compacted context, not the old one)

A missing or unparseable timestamp, or any error at all, means no block.
Hooks get the system Python (3.9 on macOS), whose `datetime.fromisoformat`
rejects the transcript's trailing `Z`. Replace it with `+00:00` before
parsing, or every timestamp fails to parse and the guard quietly never fires.
The timestamp comes from the same tail scan `context_of` already does, and
"over the line" is one shared helper (`_heavy`) that the nudge uses too.

**Block once.** On block, store `gap_blocked = last_ts`, log
`{"event": "gap_block", "ctx", "gap"}` to `nudges.jsonl`, and print the block
JSON. The next prompt sees the same `last_ts`, because no API call has
happened since. It goes through and logs `gap_resent`. The resend can be
anything, `/handoff` included. A later gap after new turns blocks again.

**Reason text** (shown to the user; the model never sees it):

> context-line: not sent. This session carries ~240k and sat idle 3h, past
> the prompt cache, so this prompt would re-send all 240k. Cheaper: start a
> new session and read `<handoff path>` (updated 2h ago). To go on here,
> send it again.

If no handoff file exists yet, the text instead suggests sending `/handoff`.
The handoff is named only if it was written at or after this session's last
nudge; otherwise the text suggests `/handoff` too, since a repo's handoff
is shared and may predate this session.
If B0.2 found the text is lost, the reason ends with the first 300
characters of the prompt so it can be copied. Nothing is logged.

**Order in `main()`.** The gap check runs first. A block skips the nudge
check, so the blocked prompt doesn't count toward grading.

**Promise change.** The README's "never blocks" becomes: "Errors never
block. The one deliberate block is the resume-gap guard, once per idle
gap; sending again always goes through. `CONTEXT_LINE_GAP=0` turns it off."
The module docstring changes to match. The README also notes that API-key
users on the 5-minute cache want `CONTEXT_LINE_GAP=300`.

## Testing

Unit tests (synthetic transcripts only; `usage_row` gains an optional
`timestamp`):

- idle 2h at 200k (base 20k) blocks; idle 30m doesn't
- under the line, or under min growth, doesn't block
- a resend with an unchanged last row passes and logs `gap_resent`; a new
  turn followed by another gap blocks again
- `CONTEXT_LINE_GAP=0`, a missing timestamp, and a tool event never block
- entry point: a block prints `{"decision":"block","reason":…}`; an error
  prints nothing
- the reason names the handoff path, and falls back to `/handoff` when none exists
- `message()` and `commands/handoff.md` both carry the `done: ` rename step

`scripts/selftest.sh` plants: gap comparison flipped, resend blocked again,
line/growth condition dropped from the gap check, block on tool events.

Live:

- canary: `CONTEXT_LINE_LINE=1000 CONTEXT_LINE_MIN_GROWTH=0
  CONTEXT_LINE_GAP=5`, one turn, wait 6s, then `claude -p --resume` blocks,
  and a resend goes through
- label: rename a throwaway desktop session to `done: …`, then from
  another session run a default `search_session_transcripts` for a unique
  string in it. It must hit.
- `make check` and `make leakscan` exit 0.

## Success

- A: every desktop handoff ends with a rename line, the successor applies
  it, and the old session still turns up in default search.
- B: after two weeks, `nudges.jsonl` shows how many gaps got blocked and
  how often they were resent. A resend rate near 100% means the guard is
  just friction and gets turned off by default.

## Rejected

- Archive or remove the old session: 0 tokens saved, it drops out of
  default search, and moving files breaks `--resume`.
- The sidebar's "mark as completed" as the label: it only clears the
  attention dot, which comes back on its own. It isn't a lasting label, so
  whether it changes search doesn't matter.
- The old session labels itself at handoff (a PostToolUse check spots its
  Write/Edit to the handoff after a nudge, then it renames `"self"`). This
  needs no ids, but it labels before any successor exists.
- Writing title rows into transcripts or app storage: those formats are
  undocumented.
- A resume-gap nudge instead of a block: by the time it shows, the full
  re-send has already happened.

## Later, not in this spec

- Re-run the "going back" and "re-explaining" measures around 2026-10-02,
  once the 09-25 migrations have aged.
- Anything that archives or hides done sessions.
