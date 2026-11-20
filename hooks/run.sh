#!/bin/sh
# runs the hook with the first python that works: python3, then py -3
# (windows), then python. no python, a stub one or a crash means silence and
# exit 0, never a hook error. hooks.json calls this file by path because the
# plugin directory blocks inline loops and command substitution in hooks.json
i=$(cat)
for p in python3 'py -3' python; do
  # $p unquoted on purpose: 'py -3' is a command and an argument
  o=$(printf %s "$i" | $p "${0%/*}/context_line.py" 2>/dev/null) && { printf %s "$o"; exit 0; }
done
exit 0
