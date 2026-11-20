#!/bin/sh
# optional status line: growth since the session opened against the nudge's
# line, from the same transcript parsing the hook uses. same python fallback as
# hooks/run.sh, and silence without one. wire it in settings.json (README)
i=$(cat)
for p in python3 'py -3' python; do
  # $p unquoted on purpose: 'py -3' is a command and an argument
  o=$(printf %s "$i" | $p "${0%/*}/hooks/context_line.py" --status 2>/dev/null) && { [ -n "$o" ] && printf '%s\n' "$o"; exit 0; }
done
exit 0
