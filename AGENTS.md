# AGENTS.md

context-line is a Claude Code plugin: a hook that nudges a session toward a
handoff before its context gets expensive, a resume guard for idle sessions,
and the `/handoff` command. `README.md` covers what it does and its settings;
this page is what an agent needs to change the plugin itself.

## Rules live in the owner's rules repo

The owner's always-on agent rules live in a separate private repo (its
`rules/` folder, loaded globally by every agent), not copied here. They win
over this page.

## Layout

- `hooks/context_line.py`: the whole hook (python3, stdlib only).
  `hooks/hooks.json` wires it to Claude Code events.
- `commands/handoff.md`: the `/handoff` command.
- `.claude-plugin/`: `plugin.json` and `marketplace.json`.
- `tests/`: `unittest` on synthetic transcripts only, never real sessions.
- `scripts/selftest.sh`: plants known bugs and fails if the tests miss them.
- `scripts/leakscan.sh`: blocks home paths, keys and personal patterns.

## Toolchain

- python3 (stdlib only), bash, git, make. Nothing to install for the tests.
- `claude` CLI for `make validate` (`claude plugin validate --strict .`).
- `gitleaks` is optional; leakscan runs it when installed.

## Test

```sh
make check      # validate + unittest + selftest, exit 0 = pass
make leakscan   # tree + full history; run before any push
```

Without the `claude` CLI, run `make test selftest` instead. Add a test for
every behaviour change, and a planted bug in `scripts/selftest.sh` for any
new guard.

## Hard stops

- The repo is public. Nothing personal goes in: no names, emails, home
  paths, session ids or prompt text. Personal patterns for leakscan live in
  `${LEAKSCAN_PATTERNS:-~/.config/leakscan/patterns.txt}`, outside the repo;
  never copy them in.
- Errors never block a prompt or tool call; the resume guard is the only
  deliberate block. Keep it that way.
- Never read `.env` / `.env.local`, anywhere.
- No AI attribution in commits, PRs or docs.
- Commits: small, casual, lowercase, no trailing period, author
  `iShaldam <45495222+iShaldam@users.noreply.github.com>` (the repo-local
  git config already sets it).
- `HANDOFF.md` is local notes, excluded from git. Never commit it.
- Claim the repo on the owner's handoff board (`handoff/parked.md` in the
  rules repo) before editing.
- Releases (`claude plugin tag .`, pushed tags) are the owner's call.

## Cloud session caveats

- `make test selftest` runs in a cloud VM as-is. `make validate` needs the
  `claude` CLI, so skip it there if it isn't installed.
- Without the private pattern file, leakscan checks generic patterns only,
  so run `make leakscan` on the owner's Mac too before merging.
- Local hooks (gitleaks pre-push) don't run in the cloud.
- Open a draft PR; never push to main.
