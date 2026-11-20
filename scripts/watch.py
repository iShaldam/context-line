#!/usr/bin/env python3
"""Weekly watch on what the hook leans on, since a format change makes it go
quiet by design and nobody would notice.

- the hooks doc sections for the events and fields the hook uses
- the usage fields it adds up, in the prompt caching doc
- Claude Code changelog lines that touch those events, the transcript or
  compaction, in versions newer than the baseline

check: exit 0 nothing moved, 1 something did (printed), 2 a fetch failed.
update: take what's live now as the new baseline in watch.json.
"""
import hashlib
import json
import os
import re
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASELINE = os.path.join(ROOT, "watch.json")
HOOKS_DOC = "https://code.claude.com/docs/en/hooks.md"
CACHE_DOC = "https://platform.claude.com/docs/en/build-with-claude/prompt-caching.md"
CHANGELOG = "https://raw.githubusercontent.com/anthropics/claude-code/main/CHANGELOG.md"
SECTIONS = ("Common input fields", "JSON output", "UserPromptSubmit",
            "PostToolBatch", "PreCompact", "SessionStart")
FIELDS = ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens",
          "ephemeral_5m_input_tokens", "ephemeral_1h_input_tokens")
TERMS = re.compile(r"UserPromptSubmit|PostToolBatch|PreCompact|SessionStart|"
                   r"prompt_cache_likely_expired|hookSpecificOutput|"
                   r"additionalContext|systemMessage|CLAUDE_PLUGIN_(ROOT|DATA)|"
                   r"transcript (file|format)|\.jsonl|isCompactSummary|"
                   r"cache_(read|creation)|hook (input|output)")


def section(doc, name):
    """The text under the `## name` or `### name` heading, up to the next one
    of those, or None when the heading is gone."""
    out = None
    for line in doc.splitlines():
        if re.match(r"#{2,3} ", line):
            if out is not None:
                break
            if line.split(" ", 1)[1].strip() == name:
                out = []
        elif out is not None:
            out.append(line)
    return None if out is None else "\n".join(out)


def digest(text):
    return hashlib.sha256(" ".join(text.split()).encode()).hexdigest()[:16]


def _version(v):
    return tuple(int(x) for x in v.split("."))


def versions(changelog):
    """[(version, [entry lines])], newest first, as the changelog lists them."""
    out = []
    for line in changelog.splitlines():
        m = re.match(r"## (\d+(?:\.\d+)+)\s*$", line)
        if m:
            out.append((m[1], []))
        elif out and line.startswith("- "):
            out[-1][1].append(line[2:])
    return out


def snapshot(hooks_doc, changelog):
    sections = {}
    for name in SECTIONS:
        text = section(hooks_doc, name)
        sections[name] = digest(text) if text is not None else "gone"
    return {"changelog": versions(changelog)[0][0], "sections": sections}


def changes(baseline, hooks_doc, cache_doc, changelog):
    now = snapshot(hooks_doc, changelog)
    out = []
    for name in SECTIONS:
        if now["sections"][name] != baseline["sections"].get(name):
            what = "is gone" if now["sections"][name] == "gone" else "changed"
            out.append(f"hooks doc: '{name}' {what} ({HOOKS_DOC})")
    for field in FIELDS:
        if field not in cache_doc:
            out.append(f"prompt caching doc no longer mentions {field} ({CACHE_DOC})")
    seen = _version(baseline["changelog"])
    for v, lines in versions(changelog):
        if _version(v) > seen:
            out += [f"changelog {v}: {line}" for line in lines if TERMS.search(line)]
    return out


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "context-line-watch"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read().decode("utf-8", "replace")


def main(argv):
    if argv not in (["check"], ["update"]):
        print("usage: watch.py check|update")
        return 2
    try:
        hooks_doc, changelog = fetch(HOOKS_DOC), fetch(CHANGELOG)
        cache_doc = fetch(CACHE_DOC) if argv == ["check"] else ""
    except OSError as e:   # URLError and timeouts are OSErrors
        print(f"watch: fetch failed: {e}", file=sys.stderr)
        return 2
    if argv == ["update"]:
        with open(BASELINE, "w") as f:
            json.dump(snapshot(hooks_doc, changelog), f, indent=2)
            f.write("\n")
        return 0
    with open(BASELINE) as f:
        found = changes(json.load(f), hooks_doc, cache_doc, changelog)
    print("\n".join(found))
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
