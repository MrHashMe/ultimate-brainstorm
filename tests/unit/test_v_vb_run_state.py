"""Phase V (VB) run-state checks: an unreadable run.json is named with its JSON error (not model-output wording),
`run --continue` detects an auth-failed family again, bs.py names `ub continue` for a v1 run folder, and `ub doctor`
reports the Windows long-path setting (6.10, 5.2). No model call."""

import io
import json
import os
import shutil
import subprocess
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fixtures", "engine"))
import engine_testlib as tl  # noqa: E402
from ublib import textio  # noqa: E402
from ublib.engine import pipeline  # noqa: E402
from ublib.engine import state as st  # noqa: E402

sys.path.insert(0, tl.SCRIPTS)
import ub  # noqa: E402


class Base(tl.EngineTestCase):
    def run_ub(self, *args, **kw):
        out = io.StringIO()
        with mock.patch.object(sys, "stdout", out):
            rc = ub.main([str(a) for a in args], deps=kw.get("deps") or tl.FakeDeps(detect=tl.fake_detect()))
        text = out.getvalue()
        return rc, (json.loads(text) if text.strip().startswith("{") else text)


class UnreadableRunJsonTests(Base):
    def test_a_cut_off_run_json_is_named_with_its_json_error(self):
        run = os.path.join(self.project, "brainstorm", "2026-09-27-odd")
        os.makedirs(run)
        for body, reason in (('{"schema": 2, "status": "act', "Unterminated string"), ("", "empty")):
            textio.write_text_atomic(os.path.join(run, "run.json"), body)
            for cmd in (("continue", run, "--host", "claude-code"), ("next", run), ("status", run)):
                with self.subTest(body=body, cmd=cmd[0]):
                    rc, card = self.run_ub(*(cmd + ("--json",)))
                    self.assertEqual(card["type"], "BLOCKED", card)
                    self.assertIn("2026-09-27-odd/run.json is unreadable", card["say"])
                    self.assertIn(reason, card["say"])
                    self.assertNotIn("output", card["say"])  # the user's file is no model output
                    self.assertIn("ub list --json", card["fix"][0])


class RunContinueRedetectsTests(Base):
    def test_a_family_that_failed_its_login_is_used_again(self):
        ctx = self.make_ctx(agent="terminal")
        ctx.state["families"]["gpt"].update({"status": "unavailable", "reason": pipeline.AUTH_FAILED + "401"})
        st.save(ctx.run_dir, ctx.state)
        with mock.patch("ublib.engine.terminal.run_loop", return_value=0) as loop:
            self.run_ub("run", "--continue", ctx.run_dir)
        self.assertTrue(loop.called)
        gpt = st.load(ctx.run_dir, persist=False)["families"]["gpt"]
        self.assertEqual((gpt["status"], gpt["reason"]), ("ok", ""))


class BsNamesContinueForAV1RunTests(tl.EngineTestCase):
    def test_screen_and_tournament_exit_4_naming_ub_continue(self):
        run = os.path.join(self.project, "brainstorm", "2026-01-10-habit-coach")
        shutil.copytree(tl.fixture_path("v1_run", "2026-01-10-habit-coach"), run)
        for cmd in ("screen", "tournament"):
            with self.subTest(cmd):
                p = subprocess.run([sys.executable, os.path.join(tl.SCRIPTS, "bs.py"), cmd, run],
                                   capture_output=True, cwd=self.project, timeout=120,
                                   env=dict(os.environ, PYTHONIOENCODING="utf-8"))
                err = p.stderr.decode("utf-8", "replace")
                self.assertEqual(p.returncode, 4, err)
                self.assertIn('ub.py" continue "', err)
                self.assertIn("migrates the folder to run.json", err)
        self.assertFalse(os.path.exists(os.path.join(run, "run.json")))  # bs.py never migrates it


class DoctorLongPathsTests(Base):
    def entry(self, reading):
        with mock.patch.object(textio, "long_paths_enabled", return_value=reading):
            _rc, card = self.run_ub("doctor", "--json")
        return next((c for c in card["checks"] if c["id"] == "long_paths"), None)

    @unittest.skipUnless(os.name == "nt", "the long-path check runs on Windows only")
    def test_off_and_unknown_are_warnings(self):
        self.assertEqual(self.entry(True)["status"], "PASS")
        off = self.entry(False)
        self.assertEqual(off["status"], "WARN")
        self.assertIn("259 characters", off["message"])
        self.assertEqual((self.entry(None)["status"], "unknown" in self.entry(None)["message"]), ("WARN", True))

    @unittest.skipIf(os.name == "nt", "Windows has the check")
    def test_other_systems_have_no_entry(self):
        self.assertIsNone(self.entry(False))


if __name__ == "__main__":
    unittest.main()
