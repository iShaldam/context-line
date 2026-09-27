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
plant "line comparison flipped" 's/ctx >= cfg\["line"\]/ctx < cfg["line"]/'
plant "quiet checks save state" 's/^    if not due:$/    if _save(session_id, r) or not due:/'
plant "session id used raw"     's/name = "".join(c for c in session_id if c.isalnum() or c in "-_")/name = session_id/'
plant "renudge gap dropped"     's/ctx >= last + RENUDGE/True/'
plant "errors escape main"      's/        pass   # silence/        raise/'
plant "compaction ignored"      's/compacted = True$/compacted = False/'
plant "min growth ignored"      's/ctx - base >= cfg\["min_growth"\]/True/'
plant "baseline ignored"        's/base = r.get("baseline") or baseline_of(transcript)/base = 0/'
plant "baseline from the tail"  's/            read = 0$/            f.seek(max(0, f.seek(0, 2) - TAIL)); read = 0/'
plant "subagents not skipped"   's/if p.get("agent_id"):/if False:/'
plant "tool nudge as plain text" 's/if out and tool:/if False:/'
plant "batch nudge misnamed"   's/"hookEventName": event,/"hookEventName": "PostToolUse",/'
plant "rename step dropped"     's/first: rename session <id> to/first: to/'
plant "handed off never used"   's/handed off: <title>/done: <title>/'
plant "gap comparison flipped"  's/if gap < (cfg\["gap"\] or cache_ttl(transcript)):/if gap >= (cfg["gap"] or cache_ttl(transcript)):/'
plant "cache ttl ignored"       's/(cfg\["gap"\] or cache_ttl(transcript))/(cfg["gap"] or 3600)/'
plant "5m cache read as an hour" 's/                return 300$/                return 3600/'
plant "env gap loses to the cache" 's/(cfg\["gap"\] or cache_ttl(transcript))/cache_ttl(transcript)/'
plant "resend blocked again"    's/if r.get("gap_blocked") == when:/if False:/'
plant "gap check skips the line" 's/if not _heavy(ctx, base, cfg):/if False:/'
plant "gap off ignored"         's/ or not transcript or off:/ or not transcript:/'
plant "headless runs guarded"   's/if _headless() or /if /'
plant "block on tool events"    's/        if event == "UserPromptSubmit":/        if True:/'
plant "block on any non-tool event" 's/        if event == "UserPromptSubmit":/        if not tool:/'
plant "broken guard kills nudge" 's/                reason = ""   # a broken guard/                raise   # a broken guard/'
plant "compaction keeps the stale time" 's/when = None if compacted else _when(line)/when = _when(line)/'
plant "stale handoff recommended" 's/os.path.getmtime(path) >= since/True/'
plant "handoff write filter dropped" 's/_wrote(transcript, path, since) and //'
plant "read-only tools count as writes" 's/for t in ("Edit", "Write", "MultiEdit", "Bash")/for t in ("Edit", "Write", "MultiEdit", "Bash", "Read")/'
plant "write before the nudge counts" 's/if when is None or when < since:/if when is None:/'
plant "tilde path ignored"      's/tilde = "~" + path\[len(home):\] if/tilde = None if/'
plant "unreadable transcript escapes" '/^def _tail/,/^def /s/except OSError:/except ZeroDivisionError:/'
plant "resend logs every time"  's/if r.get("gap_resent") != when:/if True:/'
plant "resend logged once per session" 's/if r.get("gap_resent") != when:/if not r.get("gap_resent"):/'
plant "handoff resend not flagged" 's/handoff=wrap)/handoff=False)/'
plant "namespaced handoff missed" 's|("/handoff", "/context-line:handoff")|("/handoff",)|'
plant "first /handoff blocked"   's/        return ""   # already doing what/        pass   # already doing what/'
plant "prompt stored on resend" 's/handoff=wrap)/handoff=wrap, prompt=prompt)/'
exit $missed
