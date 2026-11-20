# Contributing

Thanks for helping. Issues and pull requests are both welcome, small ones
most of all.

## Before you open a PR

```
make test selftest   # unit tests and the planted-bug canary, no install needed
make check           # also validates the plugin, needs the claude CLI
make leakscan        # home paths, keys, tokens in the tree and history
```

All three should exit 0. CI runs `make test selftest leakscan` on every push
and pull request.

## Rules for changes

- One change per PR, with a test for it. A new guard in the hook also gets a
  planted bug in `scripts/selftest.sh`, so the canary proves the test catches
  it.
- Tests use synthetic transcripts only. Never paste a real session, a session
  id, a home path or prompt text into a test, an issue or a commit.
- The hook never blocks on an error: an unreadable transcript or an unknown
  format means it prints nothing. The opt-in resume guard is the only
  deliberate block.
- Python standard library only, and it has to run on the system Python 3.9
  that macOS ships.
- Commit messages are short and lowercase, like `nudge counts growth from the
  first turn`.

## When Claude Code changes

If a hook event or the transcript format changed and the nudge stopped, use
the "Claude Code changed" issue template. A weekly job
(`scripts/watch.py`) also watches the hooks doc and changelog.

Security problems: see [SECURITY.md](SECURITY.md).
