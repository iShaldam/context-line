# Security

## What context-line reads and writes

- **Reads** the session transcript Claude Code names in the hook input: the
  last 400 KB, and up to the first 2 MB to find the opening size. Only token
  counts, timestamps, stop reasons and the paths of files the session edited
  are used.
- **Reads** your prompt from the hook input only to spot a `/handoff` or a
  "continue" after a nudge. When the opt-in resume guard holds a prompt back
  it shows you its first 300 characters. Prompt text is never stored.
- **Writes**, in the plugin data folder (or `~/.local/state/context-line/`):
  one small state file per nudged session, `nudges.jsonl` (session ids, token
  counts, timestamps), and before a compaction a list of the files the session
  edited. Never prompt text.
- **Writes** your handoff to `HANDOFF.md` in the repo root or the current
  folder, only when Claude follows a nudge or you run `/context-line:handoff`.
- `/context-line:report` reads every transcript under `~/.claude/projects` and
  prints aggregates.
- Nothing is sent anywhere. The hook makes no network calls and has no
  dependencies outside the Python standard library.

## Reporting a problem

Please don't put the details in a public issue. Open an issue titled
"security contact" with no details, and I'll reply with a private way to send
them. Fixes go out as a new release; there is only ever one supported version,
the latest.
