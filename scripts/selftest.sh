#!/usr/bin/env bash
# canary for the test suite: plant known bugs in a copy of the hook and make
# sure the tests catch every one. a green suite that misses a plant means nothing.
set -u
root="$(cd "$(dirname "$0")/.." && pwd)"
missed=0
fresh() {  # a scratch copy of everything the tests read
  tmp="$(mktemp -d)"
  cp -R "$root/hooks" "$root/tests" "$root/commands" "$tmp/"
}
plant() {  # name, sed expression
  fresh
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
# control: the unplanted copy must pass, or every plant reads "caught"
fresh
if ! (cd "$tmp" && python3 -m unittest discover -s tests >/dev/null 2>&1); then
  echo "selftest: the unplanted copy fails -- no plant can be trusted"; missed=1
fi
rm -rf "$tmp"
plant "line comparison flipped" 's/ctx >= s\["line"\]/ctx < s["line"]/'
plant "floor ignored"           's/max(min(cfg\["floor"\], s\["line"\]), s\["line"\] - STEP)/s["line"] - STEP/'
plant "low line pushed to floor" 's/max(min(cfg\["floor"\], s\["line"\]), /max(cfg["floor"], /'
plant "adapt flag ignored"      's/ and cfg\["adapt"\]:/:/'
plant "renudge gap dropped"     's/ctx >= last + RENUDGE/True/'
plant "errors escape main"      's/        pass   # silence/        raise/'
plant "compaction ignored"      's/compacted = True$/compacted = False/'
plant "min growth ignored"      's/ctx - base >= cfg\["min_growth"\]/True/'
plant "baseline ignored"        's/base = r.get("baseline") or baseline_of(transcript)/base = 0/'
plant "baseline from the tail"  's/            read = 0$/            f.seek(max(0, f.seek(0, 2) - TAIL)); read = 0/'
plant "tools count as prompts"  's/if prompt and r.get("nudged_at"):/if r.get("nudged_at"):/'
plant "kept going not graded"   's/ctx >= last + KEPT_GOING:/False:/'
plant "graded every nudge"      's/prompts_since_nudge=0)$/prompts_since_nudge=0, graded=None)/'
plant "quiet tools save state"  's/        if changed:$/        if True:/'
plant "subagents not skipped"   's/if p.get("agent_id"):/if False:/'
plant "tool nudge as plain text" 's/if out and tool:/if False:/'
plant "no lock on state"        's/            fcntl.flock(lock, fcntl.LOCK_EX)/            pass/'
plant "rename step dropped"     's/first: rename session <id> to/first: to/'
plant "gap comparison flipped"  's/if gap < cfg\["gap"\]:/if gap >= cfg["gap"]:/'
plant "resend blocked again"    's/if r.get("gap_blocked") == when:/if False:/'
plant "gap check skips the line" 's/if not _heavy(ctx, base, s, cfg):/if False:/'
plant "gap off ignored"         's/ or settings()\["gap"\] <= 0:/:/'
plant "block on tool events"    's/        if not tool:$/        if True:/'
plant "broken guard kills nudge" 's/                reason = ""   # a broken guard/                raise   # a broken guard/'
plant "compaction keeps the stale time" 's/when = None if compacted else _when(line)/when = _when(line)/'
exit $missed
