"""Synthetic transcripts only -- nothing here comes from a real session."""
import json, os, subprocess, sys, tempfile, time, unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOOK = os.path.join(ROOT, "hooks", "context_line.py")
sys.path.insert(0, os.path.join(ROOT, "hooks"))
import context_line as cl  # noqa: E402


def usage_row(ctx):
    return {"type": "assistant", "message": {"usage": {
        "input_tokens": 10, "cache_read_input_tokens": ctx - 10,
        "cache_creation_input_tokens": 0}}}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = self.tmp.name
        env = {"CLAUDE_PLUGIN_DATA": os.path.join(self.dir, "state"),
               "CONTEXT_LINE_LINE": "150000", "CONTEXT_LINE_FLOOR": "80000",
               "CONTEXT_LINE_ADAPT": "1"}
        self.env = mock.patch.dict(os.environ, env)
        self.env.start()
        os.environ.pop("CONTEXT_LINE_HANDOFF", None)
        self.transcript = os.path.join(self.dir, "t.jsonl")

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def write(self, *rows):
        with open(self.transcript, "w") as f:
            for r in rows:
                f.write((r if isinstance(r, str) else json.dumps(r)) + "\n")

    def at(self, ctx, base=20_000):
        """A session that started at `base` tokens and now carries `ctx`."""
        self.write(usage_row(base), usage_row(ctx))

    def state_file(self):
        return os.path.join(os.environ["CLAUDE_PLUGIN_DATA"], "state.json")

    def state(self):
        with open(self.state_file()) as f:
            return json.load(f)


class Threshold(Base):
    def test_under_line_is_silent(self):
        self.at(149_999)
        self.assertEqual(cl.check("s1", self.transcript), "")

    def test_over_line_nudges(self):
        self.at(150_000)
        out = cl.check("s1", self.transcript)
        self.assertIn("START A FRESH SESSION", out)
        self.assertIn("~150k tokens", out)
        self.assertIn("```text", out)

    def test_nudge_says_stop_not_finish(self):
        # "finish or pause the current step" read as permission to keep browsing
        self.at(150_000)
        out = cl.check("s1", self.transcript)
        self.assertIn("stop at the next safe point", out)
        self.assertNotIn("finish or pause", out)

    def test_last_usage_row_wins(self):
        self.write(usage_row(20_000), usage_row(200_000), {"type": "user"}, usage_row(90_000))
        self.assertEqual(cl.check("s1", self.transcript), "")

    def test_compacted_nudges_once_even_when_small(self):
        self.write({"isCompactSummary": True}, usage_row(20_000))
        self.assertIn("compacted", cl.check("s1", self.transcript))
        self.assertEqual(cl.check("s1", self.transcript), "")

    def test_renudge_needs_growth_and_escalates(self):
        self.at(150_000)
        self.assertTrue(cl.check("s1", self.transcript))
        self.at(175_000)
        self.assertEqual(cl.check("s1", self.transcript), "")
        self.at(180_000)
        out = cl.check("s1", self.transcript)
        self.assertIn("nudge #2", out)

    def test_env_line_is_respected(self):
        os.environ["CONTEXT_LINE_LINE"] = "100000"
        self.at(100_000)
        self.assertTrue(cl.check("s1", self.transcript))


class Baseline(Base):
    """A fresh session already carries ~100k of tools and skills; only growth counts."""

    def test_big_start_without_growth_is_silent(self):
        self.at(155_000, base=120_000)
        self.assertEqual(cl.check("s1", self.transcript), "")

    def test_enough_growth_past_the_line_nudges(self):
        self.at(160_000, base=120_000)
        self.assertIn("START A FRESH SESSION", cl.check("s1", self.transcript))

    def test_baseline_comes_from_session_start_not_tail(self):
        pad = {"type": "user", "message": {"content": "x" * (cl.TAIL + 10)}}
        self.write(usage_row(20_000), pad, usage_row(150_000), usage_row(160_000))
        self.assertIn("START A FRESH SESSION", cl.check("s1", self.transcript))

    def test_min_growth_env_zero_for_canaries(self):
        os.environ["CONTEXT_LINE_LINE"] = "1000"
        os.environ["CONTEXT_LINE_MIN_GROWTH"] = "0"
        self.write(usage_row(1_000))
        self.assertTrue(cl.check("s1", self.transcript))


class MidTurn(Base):
    def test_tool_event_nudges(self):
        self.at(150_000)
        self.assertIn("START A FRESH SESSION", cl.check("s1", self.transcript, event="tool"))

    def test_quiet_tool_event_writes_no_state(self):
        self.at(50_000)
        self.assertEqual(cl.check("s1", self.transcript, event="tool"), "")
        self.assertFalse(os.path.exists(self.state_file()))

    def test_tool_event_does_not_count_as_prompt(self):
        self.at(150_000)
        cl.check("s1", self.transcript)
        for _ in range(cl.TAKEN_WITHIN):
            cl.check("s1", self.transcript)
        cl.check("s1", self.transcript, event="tool")
        self.assertIsNone(self.state()["sessions"]["s1"].get("graded"))
        self.assertEqual(self.state()["line"], 150_000)

    def test_model_keeping_going_is_ignored(self):
        self.at(150_000)
        cl.check("s1", self.transcript)
        self.at(170_000)
        cl.check("s1", self.transcript, event="tool")
        self.assertEqual(self.state()["sessions"]["s1"]["graded"], "ignored")
        self.assertEqual(self.state()["line"], 140_000)


class Learning(Base):
    def ignore_one(self, sid):
        self.at(150_000)
        cl.check(sid, self.transcript)
        for _ in range(cl.TAKEN_WITHIN + 1):
            cl.check(sid, self.transcript)

    def test_ignored_nudge_lowers_line(self):
        self.ignore_one("s1")
        self.assertEqual(self.state()["line"], 140_000)

    def test_line_never_drops_below_floor(self):
        os.environ["CONTEXT_LINE_LINE"] = "85000"
        self.ignore_one("s1")
        self.ignore_one("s2")
        self.assertEqual(self.state()["line"], 80_000)

    def test_adapt_off_keeps_line(self):
        os.environ["CONTEXT_LINE_ADAPT"] = "0"
        self.ignore_one("s1")
        self.assertEqual(self.state()["line"], 150_000)

    def test_grade_once_per_session(self):
        self.ignore_one("s1")
        self.at(185_000)
        self.assertIn("nudge #2", cl.check("s1", self.transcript))
        for _ in range(cl.TAKEN_WITHIN + 1):
            cl.check("s1", self.transcript)
        self.assertEqual(self.state()["line"], 140_000)

    def test_quiet_session_is_taken(self):
        self.at(150_000)
        cl.check("s1", self.transcript)
        s = self.state()
        s["sessions"]["s1"]["seen"] = time.time() - cl.QUIET - 1
        cl._save(s)
        cl.check("s2", self.transcript)
        self.assertEqual(self.state()["sessions"]["s1"]["graded"], "taken")
        self.assertEqual(self.state()["line"], 150_000)

    def test_changed_env_line_resets_learned_line(self):
        self.ignore_one("s1")
        os.environ["CONTEXT_LINE_LINE"] = "120000"
        self.write(usage_row(10))
        cl.check("s3", self.transcript)
        self.assertEqual(self.state()["line"], 120_000)


class HandoffPath(Base):
    def test_git_repo_uses_repo_root(self):
        repo = os.path.join(self.dir, "repo")
        os.makedirs(os.path.join(repo, ".git"))
        os.makedirs(os.path.join(repo, "src", "deep"))
        self.assertEqual(cl.handoff_path(os.path.join(repo, "src", "deep"), "abcdef123"),
                         os.path.join(repo, "HANDOFF.md"))

    def test_outside_repo_uses_state_dir(self):
        p = cl.handoff_path(os.path.join(self.dir, "loose"), "abcdef123")
        self.assertTrue(p.startswith(os.environ["CLAUDE_PLUGIN_DATA"]))
        self.assertTrue(p.endswith("-abcdef12.md"))

    def test_override_wins(self):
        os.environ["CONTEXT_LINE_HANDOFF"] = os.path.join(self.dir, "mine.md")
        self.assertEqual(cl.handoff_path(self.dir, "x"), os.path.join(self.dir, "mine.md"))


class Concurrency(Base):
    def nudges_logged(self):
        with open(os.path.join(os.environ["CLAUDE_PLUGIN_DATA"], "nudges.jsonl")) as f:
            return sum(json.loads(l).get("event") == "nudge" for l in f)

    def test_parallel_tool_calls_nudge_once(self):
        # parallel tool calls fire their PostToolUse hooks at the same moment
        self.at(160_000)
        payload = json.dumps({"session_id": "s1", "transcript_path": self.transcript,
                              "hook_event_name": "PostToolUse"})
        real, other = cl.context_of, []

        def racing(transcript):   # a second hook runs while this one is mid-check
            if not other:
                p = subprocess.Popen([sys.executable, HOOK], stdin=subprocess.PIPE,
                                     stdout=subprocess.DEVNULL, text=True)
                p.stdin.write(payload)
                p.stdin.close()
                other.append(p)
                time.sleep(0.5)
            return real(transcript)

        with mock.patch.object(cl, "context_of", racing):
            cl.check("s1", self.transcript, event="tool")
        other[0].wait(timeout=10)
        self.assertEqual(self.nudges_logged(), 1)


class NeverBlocks(Base):
    def run_hook(self, stdin):
        env = dict(os.environ, PATH="/usr/bin:/bin")   # hooks don't get your PATH
        return subprocess.run([sys.executable, HOOK], input=stdin, text=True,
                              capture_output=True, env=env, timeout=10)

    def test_real_shaped_payload_through_entry_point(self):
        self.at(160_000)
        payload = {"session_id": "abc123", "transcript_path": self.transcript,
                   "cwd": self.dir, "permission_mode": "default",
                   "hook_event_name": "UserPromptSubmit", "prompt": "hi"}
        r = self.run_hook(json.dumps(payload))
        self.assertEqual(r.returncode, 0)
        self.assertIn("START A FRESH SESSION", r.stdout)

    def tool_payload(self, **extra):
        return dict({"session_id": "abc123", "transcript_path": self.transcript,
                     "cwd": self.dir, "permission_mode": "default",
                     "hook_event_name": "PostToolUse", "tool_name": "Bash",
                     "tool_input": {"command": "ls"}, "tool_response": {"stdout": ""},
                     "tool_use_id": "toolu_1"}, **extra)

    def test_post_tool_use_reaches_model_as_json(self):
        # plain stdout only reaches the model on UserPromptSubmit
        self.at(160_000)
        r = self.run_hook(json.dumps(self.tool_payload()))
        self.assertEqual(r.returncode, 0)
        out = json.loads(r.stdout)["hookSpecificOutput"]
        self.assertEqual(out["hookEventName"], "PostToolUse")
        self.assertIn("START A FRESH SESSION", out["additionalContext"])

    def test_subagent_tool_use_is_skipped(self):
        self.at(160_000)
        r = self.run_hook(json.dumps(self.tool_payload(agent_id="a1", agent_type="Explore")))
        self.assertEqual((r.returncode, r.stdout), (0, ""))

    def test_garbage_stdin_is_silent(self):
        r = self.run_hook("not json{")
        self.assertEqual((r.returncode, r.stdout, r.stderr), (0, "", ""))

    def test_garbage_transcript_is_silent(self):
        self.write("{{{", "null", "[1,2]", '{"message": "str"}')
        self.assertEqual(cl.check("s1", self.transcript), "")

    def test_missing_transcript_is_silent(self):
        self.assertEqual(cl.check("s1", os.path.join(self.dir, "nope.jsonl")), "")

    def test_unwritable_state_is_silent(self):
        os.environ["CLAUDE_PLUGIN_DATA"] = "/dev/null/state"
        self.at(200_000)
        r = self.run_hook(json.dumps({"session_id": "a", "transcript_path": self.transcript}))
        self.assertEqual((r.returncode, r.stdout), (0, ""))


if __name__ == "__main__":
    unittest.main()
