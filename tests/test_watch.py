"""scripts/watch.py on made-up docs: no network here."""
import os, sys, unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
import watch  # noqa: E402

DOC = """# Hooks
## Hook input and output
### Common input fields
session_id, transcript_path, cwd
### JSON output
systemMessage, hookSpecificOutput
## Hook events
### UserPromptSubmit
additionalContext
#### UserPromptSubmit input
prompt
### PostToolBatch
once per batch
### PreCompact
before a compact
### SessionStart
#### SessionStart input
prompt_cache_likely_expired, context_tokens, estimated_cache_write_usd
### PostCompact
after
"""
CACHE = " ".join(watch.FIELDS)
LOG = """# Changelog

## 2.1.12

- Fixed `PostToolBatch` hooks firing twice
- Fixed a typo in /help

## 2.1.11

- Changed the transcript format for compaction rows

## 2.1.9

- Fixed `PreCompact` input
"""


class Watch(unittest.TestCase):
    def baseline(self, version="2.1.12"):
        return dict(watch.snapshot(DOC, LOG), changelog=version)

    def test_nothing_moved(self):
        self.assertEqual(watch.changes(self.baseline(), DOC, CACHE, LOG), [])

    def test_section_runs_to_the_next_heading_but_keeps_subheadings(self):
        self.assertEqual(watch.section(DOC, "UserPromptSubmit"),
                         "additionalContext\n#### UserPromptSubmit input\nprompt")
        self.assertIsNone(watch.section(DOC, "Stop"))

    def test_whitespace_only_edit_is_not_a_change(self):
        doc = DOC.replace("once per batch", "once  per\nbatch")
        self.assertEqual(watch.changes(self.baseline(), doc, CACHE, LOG), [])

    def test_edited_section_is_named(self):
        doc = DOC.replace("once per batch", "once per tool")
        self.assertEqual(watch.changes(self.baseline(), doc, CACHE, LOG),
                         [f"hooks doc: 'PostToolBatch' changed ({watch.HOOKS_DOC})"])

    def test_edits_elsewhere_are_ignored(self):
        doc = DOC.replace("after", "right after")
        self.assertEqual(watch.changes(self.baseline(), doc, CACHE, LOG), [])

    def test_removed_section_is_gone(self):
        doc = DOC.replace("### PreCompact\n", "### PreCompactNow\n")
        self.assertIn(f"hooks doc: 'PreCompact' is gone ({watch.HOOKS_DOC})",
                      watch.changes(self.baseline(), doc, CACHE, LOG))

    def test_missing_usage_field(self):
        cache = CACHE.replace("ephemeral_1h_input_tokens", "")
        self.assertEqual(len(watch.changes(self.baseline(), DOC, cache, LOG)), 1)

    def test_new_changelog_lines_that_matter(self):
        self.assertEqual(watch.changes(self.baseline("2.1.9"), DOC, CACHE, LOG), [
            "changelog 2.1.12: Fixed `PostToolBatch` hooks firing twice",
            "changelog 2.1.11: Changed the transcript format for compaction rows"])

    def test_versions_compare_as_numbers(self):
        log = LOG.replace("## 2.1.12", "## 2.1.100")
        self.assertEqual(len(watch.changes(self.baseline("2.1.11"), DOC, CACHE, log)), 1)

    def test_snapshot_takes_the_newest_version(self):
        self.assertEqual(watch.snapshot(DOC, LOG)["changelog"], "2.1.12")


if __name__ == "__main__":
    unittest.main()
