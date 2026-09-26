"""Synthetic transcripts only -- nothing here comes from a real session."""
import contextlib, datetime, io, json, os, subprocess, sys, tempfile, time, unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOOK = os.path.join(ROOT, "hooks", "context_line.py")
sys.path.insert(0, os.path.join(ROOT, "hooks"))
import context_line as cl  # noqa: E402


def usage_row(ctx, ts=None):
    row = {"type": "assistant", "message": {"usage": {
        "input_tokens": 10, "cache_read_input_tokens": ctx - 10,
        "cache_creation_input_tokens": 0}}}
    if ts is not None:
        row["timestamp"] = iso(ts)
    return row


def edit_row(path, ts, ctx=200_000, tool="Edit"):
    """An assistant turn that runs `tool` on `path`: a tool_use row that carries usage."""
    row = usage_row(ctx, ts=ts)
    inp = {"command": f"cat >> {path}"} if tool == "Bash" else {"file_path": path}
    row["message"]["content"] = [{"type": "tool_use", "name": tool, "input": inp}]
    return row


def iso(t):
    """A transcript timestamp: UTC, milliseconds, trailing Z."""
    d = datetime.datetime.fromtimestamp(t, datetime.timezone.utc)
    return d.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


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
        for k in ("CLAUDE_CODE_ENTRYPOINT", "CLAUDE_CODE_SESSION_ATTENDED"):
            os.environ.pop(k, None)   # the suite may itself run under claude -p
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

    def idle(self, ctx=200_000, base=20_000, secs=2 * 3600):
        """A session whose last API call was `secs` ago."""
        now = time.time()
        self.write(usage_row(base, ts=now - secs - 60), usage_row(ctx, ts=now - secs))

    def handed_off(self, sid="s1", ctx=200_000, base=20_000, secs=2 * 3600):
        """idle(), but s1 was nudged and then wrote its handoff before going
        quiet: the one case the resume guard holds a prompt back."""
        now = time.time()
        t = now - secs - 600
        path = os.environ["CONTEXT_LINE_HANDOFF"] = os.path.join(self.dir, "HANDOFF.md")
        open(path, "w").close()
        self.write(usage_row(base, ts=t - 60), usage_row(ctx, ts=t),
                   edit_row(path, ts=now - secs, ctx=ctx))
        s = cl._load(cl.settings())
        s["sessions"].setdefault(sid, {}).update(
            seen=now, nudged_at=t, nudge_ctx=ctx, nudges=1, prompts_since_nudge=0)
        cl._save(s)
        return path

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


class Timestamps(Base):
    def test_context_of_returns_last_call_time(self):
        # the new prompt is already written when the hook runs: fresh stamp, no usage
        t = time.time() - 7200
        self.write(usage_row(20_000, ts=t - 60), usage_row(150_000, ts=t),
                   {"type": "user", "timestamp": iso(time.time())})
        ctx, compacted, when = cl.context_of(self.transcript)
        self.assertEqual((ctx, compacted), (150_000, False))
        self.assertAlmostEqual(when, t, places=2)

    def test_no_timestamp_is_none(self):
        self.at(150_000)
        self.assertIsNone(cl.context_of(self.transcript)[2])

    def test_bad_timestamp_is_none(self):
        row = usage_row(150_000)
        row["timestamp"] = "yesterday"
        self.write(row)
        self.assertIsNone(cl.context_of(self.transcript)[2])

    def test_missing_transcript_has_no_time(self):
        self.assertEqual(cl.context_of(os.path.join(self.dir, "nope.jsonl")), (0, False, None))

    def test_compaction_older_than_last_usage_keeps_time(self):
        t = time.time() - 7200
        self.write({"isCompactSummary": True}, usage_row(20_000, ts=t - 60),
                   usage_row(200_000, ts=t))
        self.assertAlmostEqual(cl.context_of(self.transcript)[2], t, places=2)


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


class Gap(Base):
    """A heavy session idle past the prompt cache: hold the first prompt back once."""

    def guard(self, **kw):
        return cl.resume_guard("s1", self.transcript, self.dir, **kw)

    def events(self):
        with open(os.path.join(os.environ["CLAUDE_PLUGIN_DATA"], "nudges.jsonl")) as f:
            return [json.loads(l).get("event") for l in f]

    def test_idle_heavy_session_is_held_back(self):
        self.handed_off()
        out = self.guard()
        self.assertIn("not sent", out)
        self.assertIn("~200k", out)
        self.assertIn("idle 2h", out)
        self.assertEqual(self.events(), ["gap_block"])

    def test_compaction_newer_than_last_usage_gives_no_time_or_block(self):
        t = time.time() - 7200
        self.write(usage_row(20_000, ts=t - 60), usage_row(200_000, ts=t),
                   {"isCompactSummary": True})
        self.assertIsNone(cl.context_of(self.transcript)[2])
        self.assertEqual(self.guard(), "")

    def test_short_idle_goes_through(self):
        self.handed_off(secs=30 * 60)
        self.assertEqual(self.guard(), "")

    def test_under_line_goes_through(self):
        self.handed_off(ctx=140_000)
        self.assertEqual(self.guard(), "")

    def test_under_min_growth_goes_through(self):
        self.handed_off(ctx=160_000, base=130_000)
        self.assertEqual(self.guard(), "")

    def test_resend_goes_through(self):
        self.handed_off()
        self.assertTrue(self.guard())
        self.assertEqual(self.guard(), "")
        self.assertEqual(self.events(), ["gap_block", "gap_resent"])

    def rows(self, event):
        with open(os.path.join(os.environ["CLAUDE_PLUGIN_DATA"], "nudges.jsonl")) as f:
            return [r for r in (json.loads(l) for l in f) if r.get("event") == event]

    def test_resend_logs_once_per_gap(self):
        self.handed_off()
        for _ in range(3):
            self.guard()
        self.assertEqual(self.events(), ["gap_block", "gap_resent"])

    def test_each_new_gap_logs_its_own_resend(self):
        self.handed_off()
        self.guard()
        self.guard()
        self.handed_off(ctx=210_000, secs=90 * 60)   # the resend ran, then it sat again
        self.guard()
        self.guard()
        self.assertEqual(self.events(), ["gap_block", "gap_resent"] * 2)

    def resend_flag(self, prompt):
        self.handed_off()
        self.guard()
        self.guard(prompt=prompt)
        rows = self.rows("gap_resent")
        self.assertEqual(len(rows), 1)
        return rows[0]["handoff"]

    def test_resend_flags_the_handoff_command(self):
        self.assertIs(self.resend_flag("/handoff"), True)

    def test_resend_flags_the_namespaced_handoff_command(self):
        # the one real /handoff in the transcripts arrived as /context-line:handoff
        self.assertIs(self.resend_flag("  /context-line:handoff"), True)

    def test_plain_resend_flags_no_handoff(self):
        self.assertIs(self.resend_flag("go on, not /handoff"), False)

    def test_new_gap_after_a_new_turn_blocks_again(self):
        self.handed_off()
        self.guard()
        self.guard()
        self.handed_off(ctx=210_000, secs=90 * 60)   # the resend ran, then it sat again
        self.assertIn("not sent", self.guard())

    def test_gap_zero_turns_it_off(self):
        os.environ["CONTEXT_LINE_GAP"] = "0"
        self.handed_off()
        self.assertEqual(self.guard(), "")

    def test_missing_timestamp_goes_through(self):
        self.at(200_000)
        self.assertEqual(self.guard(), "")

    def test_headless_runs_go_through(self):
        # claude -p --resume, the SDK, scheduled jobs: nobody is there to send it again
        for env in ({"CLAUDE_CODE_ENTRYPOINT": "sdk-cli"}, {"CLAUDE_CODE_ENTRYPOINT": "sdk-ts"},
                    {"CLAUDE_CODE_SESSION_ATTENDED": "0"}):
            with mock.patch.dict(os.environ, env):
                self.handed_off()
                self.assertEqual(self.guard(), "")

    def test_interactive_entrypoints_still_guard(self):
        with mock.patch.dict(os.environ, {"CLAUDE_CODE_ENTRYPOINT": "claude-desktop"}):
            self.handed_off()
            self.assertIn("not sent", self.guard())

    def nudged(self, ago=3 * 3600):
        """Nudge s1, then move its nudge `ago` seconds back. Returns nudged_at."""
        self.idle()
        cl.check("s1", self.transcript)
        s = self.state()
        t = s["sessions"]["s1"]["nudged_at"] = time.time() - ago
        cl._save(s)
        return t

    def handoff(self, mtime=None):
        """A handoff file on disk (the override path), optionally back-dated."""
        path = os.environ["CONTEXT_LINE_HANDOFF"] = os.path.join(self.dir, "HANDOFF.md")
        open(path, "w").close()
        if mtime is not None:
            os.utime(path, (mtime, mtime))
        return path

    def after_nudge(self, t, *rows):
        """A transcript that crossed the line around the nudge at `t`, then `rows`."""
        self.write(usage_row(20_000, ts=t - 60), usage_row(190_000, ts=t + 60), *rows)

    def test_reason_points_at_existing_handoff(self):
        t = self.nudged()
        path = self.handoff()   # written now, after the nudge
        self.after_nudge(t, edit_row(path, ts=time.time() - 2 * 3600))
        out = self.guard()
        self.assertIn(path, out)
        self.assertIn("updated", out)
        self.assertNotIn("send /handoff", out)

    def test_handoff_written_by_another_session_is_not_named(self):
        # a repo's HANDOFF.md is shared: fresh on disk, but this transcript never wrote it
        t = self.nudged()
        path = self.handoff()
        self.after_nudge(t, usage_row(200_000, ts=time.time() - 2 * 3600))
        self.assertEqual(self.guard(), "")

    def test_read_only_mention_is_not_a_write(self):
        t = self.nudged()
        path = self.handoff()
        self.after_nudge(t, edit_row(path, ts=time.time() - 2 * 3600, tool="Read"))
        self.assertEqual(self.guard(), "")

    def test_write_before_the_nudge_is_not_named(self):
        # this session wrote it once, before the nudge; someone else touched it since
        t = self.nudged()
        path = self.handoff()
        self.write(usage_row(20_000, ts=t - 120), edit_row(path, ts=t - 60),
                   usage_row(190_000, ts=t + 60), usage_row(200_000, ts=time.time() - 2 * 3600))
        self.assertEqual(self.guard(), "")

    def test_written_but_stale_on_disk_goes_through(self):
        # written after the nudge, but the file on disk predates it (reverted):
        # the mtime check must still bite even though the write check passes
        t = self.nudged()
        path = self.handoff(mtime=t - 60)
        self.after_nudge(t, edit_row(path, ts=time.time() - 2 * 3600))
        self.assertEqual(self.guard(), "")

    def test_bash_write_to_tilde_path_counts(self):
        # never create files under the real home: unit-test _wrote directly
        self.write(edit_row("~/x/HANDOFF.md", ts=time.time() - 60, tool="Bash"))
        path = os.path.join(os.path.expanduser("~"), "x", "HANDOFF.md")
        self.assertTrue(cl._wrote(self.transcript, path, time.time() - 3600))

    def test_unreadable_transcript_is_not_a_write(self):
        missing = os.path.join(self.dir, "gone.jsonl")
        self.assertFalse(cl._wrote(missing, os.path.join(self.dir, "HANDOFF.md"), 0))

    def test_stale_handoff_goes_through(self):
        path = os.path.join(self.dir, "HANDOFF.md")
        os.environ["CONTEXT_LINE_HANDOFF"] = path
        self.idle()
        cl.check("s1", self.transcript)   # nudges: sets nudged_at
        nudged_at = self.state()["sessions"]["s1"]["nudged_at"]
        open(path, "w").close()
        os.utime(path, (nudged_at - 60, nudged_at - 60))   # handoff predates the nudge
        self.assertEqual(self.guard(), "")
        # never nudged at all: same existing file, but nothing to compare it against
        self.assertEqual(cl.resume_guard("s2", self.transcript, self.dir), "")

    def test_no_handoff_goes_through(self):
        # /handoff into the cold session re-sends it all anyway: blocking saves nothing
        self.idle()
        self.assertEqual(self.guard(), "")
        self.assertFalse(os.path.exists(self.state_file()))

    def test_handoff_goes_through_on_the_first_try(self):
        for prompt in ("/handoff", " /context-line:handoff next job"):
            self.handed_off()
            self.assertEqual(self.guard(prompt=prompt), "")
        self.assertIn("not sent", self.guard(prompt="go on"))

    def test_reason_error_does_not_store_the_block(self):
        # if building the reason fails, nothing should be spent on this gap
        self.handed_off()
        with mock.patch.object(cl, "gap_reason", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                self.guard()
        self.assertNotIn("gap_blocked", self.state()["sessions"]["s1"])
        nudges = os.path.join(os.environ["CLAUDE_PLUGIN_DATA"], "nudges.jsonl")
        self.assertFalse(os.path.exists(nudges))

    def test_prompt_echoed_but_never_stored(self):
        prompt = "secret plan " + "x" * 400
        self.handed_off()
        out = self.guard(prompt=prompt)
        self.assertTrue(out.endswith(prompt[:300]))
        self.assertNotIn(prompt[:301], out)
        self.guard(prompt=prompt)   # the resend
        for name in ("state.json", "nudges.jsonl"):
            with open(os.path.join(os.environ["CLAUDE_PLUGIN_DATA"], name)) as f:
                self.assertNotIn("secret plan", f.read())


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

    def test_line_set_below_floor_is_never_raised(self):
        os.environ["CONTEXT_LINE_LINE"] = "60000"
        self.ignore_one("s1")
        self.assertEqual(self.state()["line"], 60_000)

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


class DoneLabel(Base):
    """The old session names itself in the paste block; the new one labels it
    done:, or handed off: when its last turn didn't complete (blocked, open)."""
    LINE = 'first: rename session <id> to "handed off: <title>" if'

    def test_nudge_asks_for_the_rename_line(self):
        self.at(150_000)
        out = cl.check("s1", self.transcript)
        self.assertIn(self.LINE, out)
        self.assertIn('get_session with "self"', out)
        self.assertIn("don't archive it", out)

    def test_rename_line_picks_the_label_from_the_last_turn_status(self):
        self.at(150_000)
        out = cl.check("s1", self.transcript)
        self.assertIn('postTurnSummary status_category is not "completed"', out)
        self.assertIn('otherwise to "done: <title>"', out)
        self.assertIn('starts with "done: " or "handed off: "', out)

    def test_compaction_nudge_asks_too(self):
        self.write({"isCompactSummary": True}, usage_row(20_000))
        self.assertIn(self.LINE, cl.check("s1", self.transcript))

    def test_handoff_command_carries_the_same_line(self):
        with open(os.path.join(ROOT, "commands", "handoff.md")) as f:
            text = f.read()
        self.assertIn(self.LINE, text)
        self.assertIn("don't archive it", text)


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


class StuckLock(Base):
    @unittest.skipUnless(cl.fcntl, "no flock here")
    def test_stuck_lock_holder_fails_open(self):
        # a hook stalled while holding the lock must not stall every tool call
        import fcntl
        self.at(160_000)
        os.makedirs(os.environ["CLAUDE_PLUGIN_DATA"])
        payload = json.dumps({"session_id": "s1", "transcript_path": self.transcript,
                              "hook_event_name": "PostToolUse"})
        with open(os.path.join(os.environ["CLAUDE_PLUGIN_DATA"], "state.lock"), "w") as held:
            fcntl.flock(held, fcntl.LOCK_EX)
            t = time.time()
            r = subprocess.run([sys.executable, HOOK], input=payload, text=True,
                               capture_output=True, timeout=5)
            self.assertLess(time.time() - t, 3)
            self.assertEqual((r.returncode, r.stdout), (0, ""))
        r = subprocess.run([sys.executable, HOOK], input=payload, text=True,
                           capture_output=True, timeout=5)
        self.assertIn("START A FRESH SESSION", r.stdout)   # nothing was lost


class HookCommand(Base):
    """hooks.json: a missing or stub python3 must not be a hook error on every call."""

    def hooks(self):
        with open(os.path.join(ROOT, "hooks", "hooks.json")) as f:
            return [h for groups in json.load(f)["hooks"].values()
                    for g in groups for h in g["hooks"]]

    def test_every_hook_has_a_short_timeout(self):
        self.assertEqual([h.get("timeout") for h in self.hooks()], [5, 5])

    def run_command(self, pythons):
        """Run the hooks.json command with only `pythons` ({name: target}) on PATH."""
        import shutil
        bin_ = os.path.join(self.dir, "bin")
        os.makedirs(bin_)
        os.symlink(shutil.which("cat"), os.path.join(bin_, "cat"))
        for name, target in pythons.items():
            os.symlink(target, os.path.join(bin_, name))
        self.at(160_000)
        payload = json.dumps({"session_id": "s1", "transcript_path": self.transcript,
                              "hook_event_name": "UserPromptSubmit", "prompt": "hi"})
        env = dict(os.environ, PATH=bin_, CLAUDE_PLUGIN_ROOT=ROOT)
        cmd = self.hooks()[0]["command"]
        return subprocess.run([shutil.which("bash"), "-c", cmd], input=payload, text=True,
                              capture_output=True, env=env, timeout=10)

    def stub(self):
        """A python3 like the Windows store alias or the CLT-less macOS stub."""
        path = os.path.join(self.dir, "stub")
        with open(path, "w") as f:
            f.write("#!/bin/sh\necho 'Python was not found'; echo 'Python was not found' >&2; exit 49\n")
        os.chmod(path, 0o755)
        return path

    def test_no_python_is_silent(self):
        r = self.run_command({})
        self.assertEqual((r.returncode, r.stdout, r.stderr), (0, "", ""))

    def test_stub_python3_is_silent(self):
        r = self.run_command({"python3": self.stub()})
        self.assertEqual((r.returncode, r.stdout, r.stderr), (0, "", ""))

    def test_stub_python3_falls_back_to_python(self):
        r = self.run_command({"python3": self.stub(), "python": sys.executable})
        self.assertEqual(r.returncode, 0)
        self.assertTrue(r.stdout.startswith("context-line: START A FRESH SESSION"))

    def test_real_python3_runs(self):
        r = self.run_command({"python3": sys.executable})
        self.assertIn("START A FRESH SESSION", r.stdout)


class NeverBlocks(Base):
    def run_hook(self, stdin):
        env = dict(os.environ, PATH="/usr/bin:/bin")   # hooks don't get your PATH
        return subprocess.run([sys.executable, HOOK], input=stdin, text=True,
                              capture_output=True, env=env, timeout=10)

    def prompt_payload(self, **extra):
        return dict({"session_id": "abc123", "transcript_path": self.transcript,
                     "cwd": self.dir, "permission_mode": "default",
                     "hook_event_name": "UserPromptSubmit", "prompt": "hi"}, **extra)

    def test_idle_prompt_prints_block_json(self):
        self.handed_off("abc123")
        r = self.run_hook(json.dumps(self.prompt_payload()))
        self.assertEqual(r.returncode, 0)
        out = json.loads(r.stdout)
        self.assertEqual(out["decision"], "block")
        self.assertIn("not sent", out["reason"])

    def test_idle_tool_event_never_blocks(self):
        self.idle()
        r = self.run_hook(json.dumps(self.tool_payload()))
        out = json.loads(r.stdout)
        self.assertNotIn("decision", out)
        self.assertEqual(out["hookSpecificOutput"]["hookEventName"], "PostToolUse")

    def test_held_back_prompt_does_not_count_toward_grading(self):
        self.handed_off("abc123")   # nudged, wrote its handoff, then sat for 2h
        r = self.run_hook(json.dumps(self.prompt_payload()))
        self.assertEqual(json.loads(r.stdout)["decision"], "block")
        self.assertEqual(self.state()["sessions"]["abc123"]["prompts_since_nudge"], 0)

    def test_broken_guard_still_nudges(self):
        self.at(160_000)
        out = io.StringIO()
        with mock.patch.object(cl, "resume_guard", side_effect=RuntimeError("boom")), \
                mock.patch("sys.stdin", io.StringIO(json.dumps(self.prompt_payload()))), \
                contextlib.redirect_stdout(out):
            self.assertEqual(cl.main(), 0)
        self.assertIn("START A FRESH SESSION", out.getvalue())

    @unittest.skipUnless(os.path.exists("/usr/bin/python3"), "no system python here")
    def test_system_python_parses_timestamps(self):
        # hooks get the system python (3.9 on macOS); its fromisoformat rejects a trailing Z
        self.handed_off("abc123")
        env = dict(os.environ, PATH="/usr/bin:/bin")
        r = subprocess.run(["/usr/bin/python3", HOOK], input=json.dumps(self.prompt_payload()),
                           text=True, capture_output=True, env=env, timeout=10)
        self.assertEqual(json.loads(r.stdout)["decision"], "block")

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
