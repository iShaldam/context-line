# Changelog

Tags are plain `vX.Y.Z` from 0.5.0 on. Older releases were tagged
`context-line--vX.Y.Z` (the `claude plugin tag` default) and keep those tags.

## Unreleased

- Hooks call `hooks/run.sh` instead of an inline shell loop, so the plugin
  directory's hook check passes. Same python fallback, same silence without one.
- A weekly job (`scripts/watch.py`) opens an issue when the hooks doc, the usage
  fields or the Claude Code changelog move under the hook.
- Docs say `/context-line:handoff`; related tools name session-report and
  claude-code-tools; added CONTRIBUTING.md and SECURITY.md.
- Dependabot auto-merge waits for the test and zizmor checks itself.
- The opt-in resume guard reads `prompt_cache_likely_expired`, `context_tokens`
  and `estimated_cache_write_usd` from `SessionStart` on Claude Code 2.1.251+,
  and shows the re-cache cost. Older versions keep the transcript TTL estimate.
- Optional `statusline.sh` shows growth since the session opened against the
  line, using the hook's own transcript parsing.

## 0.5.0 (2026-11-20)

Covers 0.4.0 too, which was bumped but never tagged.

- The nudge fires on growth past where the session opened (120k by default,
  `CONTEXT_LINE_GROWTH`) instead of a fixed size, so a session that opens big
  isn't nagged right away.
- The nudge says why in one line, and after a compaction lists the edited files
  inline.
- New `/context-line:report` replays your own transcripts, cutting at the same
  growth the hook uses.
- The resume guard is opt-in (`CONTEXT_LINE_GAP`), since Claude Code warns on
  cold resumes itself.
- The handoff goes in the current folder outside a git repo, and
  `/context-line:handoff` asks the hook where, so both write the same file.
- CI runs the tests, the planted-bug canary and the leak scan on every push.
  `make check` fails when plugin.json is ahead of the last tag.

## 0.3.1 (2026-10-12), tag `context-line--v0.3.1`

- Say "continue" (or "keep going") after a nudge and later nudges in that
  session only note the size; a compaction still asks for the handoff.
- The handoff's rename line has the old session pick its own label (done or
  handed off). Both by @S3yon (#6, #7).

## 0.3.0 (2026-10-03), tag `context-line--v0.3.0`

- The replay script and the context-mode comparison
  ([docs/comparison.md](docs/comparison.md)).
- README section on what the PreCompact snapshot saves.
