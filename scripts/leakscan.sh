#!/usr/bin/env bash
# run before any push. scans the working tree AND every commit in history.
# generic patterns live here; personal ones (your name, email, employer) go in
# ${LEAKSCAN_PATTERNS:-~/.config/leakscan/patterns.txt}, one regex per line,
# outside this repo so the scanner itself never leaks them.
set -u
here="$(cd "$(dirname "$0")" && pwd)"
if [ "${1:-}" = "--selftest" ]; then
  # canary: a repo with a planted home path and a fake key must fail the scan
  t="$(mktemp -d)"; (cd "$t" && git init -q && mkdir scripts &&
    printf 'path /Users/someone/x\n' > a.txt &&
    printf 'k=AKIA%s\n' ABCDEFGHIJKLMNOP > b.txt && git add a.txt &&
    git -c user.name=t -c user.email=t@t commit -qm t)
  cp "$here/leakscan.sh" "$t/scripts/"
  if LEAKSCAN_PATTERNS=/dev/null bash "$t/scripts/leakscan.sh" >/dev/null 2>&1; then
    echo "leakscan selftest: MISSED planted leaks"; rm -rf "$t"; exit 1
  fi
  echo "leakscan selftest: caught planted leaks"; rm -rf "$t"; exit 0
fi
cd "$here/.."
generic='/Users/[A-Za-z]|/home/[a-z]+/|BEGIN [A-Z ]*PRIVATE KEY|ghp_[A-Za-z0-9]{20}|sk-[A-Za-z0-9-]{20}|AKIA[0-9A-Z]{16}|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}'
private="${LEAKSCAN_PATTERNS:-$HOME/.config/leakscan/patterns.txt}"
pats="$generic"
if [ -f "$private" ]; then
  pats="$pats|$(grep -v '^\s*$' "$private" | paste -sd'|' -)"
else
  echo "leakscan: no private patterns at $private (generic only)"
fi
fail=0
hits="$(git ls-files --cached --others --exclude-standard | grep -vx 'scripts/leakscan.sh' |
  while IFS= read -r f; do [ -f "$f" ] && grep -HnIiE "$pats" "$f"; done)"
[ -n "$hits" ] && { echo "leakscan: working tree:"; echo "$hits"; fail=1; }
if git rev-parse HEAD >/dev/null 2>&1; then
  hist="$(git log -p --all --format='commit %H%n%an <%ae>%n%B' -- . ':!scripts/leakscan.sh' | grep -nIiE "$pats")"
  [ -n "$hist" ] && { echo "leakscan: history:"; echo "$hist"; fail=1; }
fi
if command -v gitleaks >/dev/null; then
  gitleaks git --no-banner . || fail=1
else
  echo "leakscan: gitleaks not installed, skipped (brew install gitleaks)"
fi
[ $fail = 0 ] && echo "leakscan: clean"
exit $fail
