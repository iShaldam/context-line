#!/bin/sh
# fails when plugin.json's version isn't the latest tag, unless RELEASE_PENDING
# names that version (unreleased on purpose). delete RELEASE_PENDING when you tag
v=$(python3 -c 'import json; print(json.load(open(".claude-plugin/plugin.json"))["version"])')
t=$(git describe --tags --abbrev=0 2>/dev/null | sed 's/.*v//')
if [ "$v" = "$t" ]; then
  [ ! -f RELEASE_PENDING ] && exit 0
  echo "release: $v is tagged, delete RELEASE_PENDING"; exit 1
fi
grep -qx "$v" RELEASE_PENDING 2>/dev/null && { echo "release: $v pending, last tag ${t:-none}"; exit 0; }
echo "release: plugin.json is $v but the latest tag is ${t:-none}; tag it or put $v in RELEASE_PENDING"; exit 1
