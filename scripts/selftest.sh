#!/usr/bin/env bash
# canary for the test suite: plant known bugs in a copy of the hook and make
# sure the tests catch every one. a green suite that misses a plant means nothing.
set -u
root="$(cd "$(dirname "$0")/.." && pwd)"
missed=0
plant() {  # name, sed expression
  tmp="$(mktemp -d)"
  cp -R "$root/hooks" "$root/tests" "$tmp/"
  sed -i.bak "$2" "$tmp/hooks/context_line.py"
  if cmp -s "$tmp/hooks/context_line.py" "$tmp/hooks/context_line.py.bak"; then
    echo "selftest: plant '$1' did not apply -- the canary is stale"; missed=1
  elif (cd "$tmp" && python3 -m unittest discover -s tests >/dev/null 2>&1); then
    echo "selftest: MISSED '$1'"; missed=1
  else
    echo "selftest: caught '$1'"
  fi
  rm -rf "$tmp"
}
plant "line comparison flipped" 's/ctx >= s\["line"\]/ctx < s["line"]/'
plant "floor ignored"           's/max(cfg\["floor"\], s\["line"\] - STEP)/s["line"] - STEP/'
plant "adapt flag ignored"      's/if cfg\["adapt"\]:/if True:/'
plant "renudge gap dropped"     's/ctx >= last + RENUDGE/True/'
plant "errors escape main"      's/        pass   # silence/        raise/'
plant "compaction ignored"      's/compacted = True$/compacted = False/'
exit $missed
