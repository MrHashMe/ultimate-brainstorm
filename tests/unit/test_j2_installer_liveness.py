"""J2C: one rule decides whether a .ub/lock.json record is a live kit 2.0.x driver, for the engine and the installer
(KIT_SPEC 6.3, 10.4 item 8; requests JG-installer-trust 1 and JC-state-pipeline 1 of the round-4 fixes).

- The installer counted a 2.0.x `ub run` idle at a human gate as live when a forward wall-clock step had moved its
  POSIX start time past its last beat, by its command line (ub.py on that run). The engine had its own copy of the rule
  without that clause: `ub next`, `ub stop` and every claim moved such a record aside and drove the run while the
  installer still blocked an update for it. Both now call proc.legacy_driver_live; the installer keeps no copy.
- state.LEGACY_STALE_S, the age past which the engine calls a live 2.0.x driver idle, is the rule's.
Process start times and command lines are mocked at ublib.proc, except in the POSIX test that reads a real one.
"""

import contextlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fixtures", "engine"))
import engine_testlib as tl  # noqa: E402

from ublib import proc, textio  # noqa: E402
from ublib.engine import state as st  # noqa: E402

sys.path.insert(0, tl.SCRIPTS)
import ub  # noqa: E402

AGO = 4000.0  # the 2.0.x driver's last beat: it has waited at a gate for over an hour


def sleeper(*args):
    """A live process (it sleeps 300 s) whose command line ends with args."""
    return subprocess.Popen([sys.executable, "-c", "import time; time.sleep(300)"] + list(args))


@contextlib.contextmanager
def stepped(beat, args=(), cwd=None):
    """The clock stepped forward after the beat: every process reads as started an hour after it (a reused pid by the
    start-time rule), and its command line is args (run in cwd)."""
    with mock.patch.object(proc, "process_start_time", lambda pid: beat + 3600), \
            mock.patch.object(proc, "process_args", lambda pid: (list(args), cwd), create=True):
        yield


class Base(tl.EngineTestCase):
    def setUp(self):
        tl.EngineTestCase.setUp(self)
        self.driver = sleeper()
        self.addCleanup(self.driver.wait)
        self.addCleanup(self.driver.kill)
        self.beat = time.time() - AGO

    def run_ub(self, *args):
        out = io.StringIO()
        with mock.patch.object(sys, "stdout", out):
            rc = ub.main([str(a) for a in args], deps=tl.FakeDeps(detect=tl.fake_detect()))
        text = out.getvalue()
        return rc, (json.loads(text) if text.strip().startswith("{") else text)

    def new_run(self):
        rc, card = self.run_ub("init", "--host", "claude-code", "--text", "shift-swap app for nurses", "--root",
                               self.project, "--no-preflight", "--json")
        self.assertEqual(rc, 0, card)
        return card["run"]

    def legacy(self, beat=None, pid=None):
        """A kit 2.0.x driver's record (no `since`)."""
        return {"pid": pid or self.driver.pid, "host": "terminal", "heartbeat_at": textio.now_iso(),
                "heartbeat_ts": self.beat if beat is None else beat}

    def put(self, run, record):
        textio.write_json_atomic(os.path.join(run, ".ub", "lock.json"), record)

    def ub_py(self, *args):
        return [sys.executable, os.path.join(tl.SCRIPTS, "ub.py")] + list(args)


class EngineKeepsTheRun(Base):
    def test_a_claim_leaves_a_driver_its_command_line_names(self):
        """The start time reads later than the beat (a clock step), and the process runs ub.py on this run: the claim
        returns its record and moves nothing aside (it moved the record aside and drove the run)."""
        run = self.new_run()
        rec = self.legacy()
        self.put(run, rec)
        lock = st.DriverLock(run, "claude-code")
        self.assertTrue(lock.acquire())
        try:
            with stepped(self.beat, self.ub_py("run", "--root", os.path.dirname(run), "--text", "shift swap")):
                self.assertEqual(lock.claim(), rec)
                self.assertEqual(lock.legacy_holder(), rec)
        finally:
            lock.release()
        self.assertEqual(textio.read_json(os.path.join(run, ".ub", "lock.json")), rec)

    def test_next_and_stop_leave_it_alone(self):
        run = self.new_run()
        rec = self.legacy()
        self.put(run, rec)
        before = textio.read_bytes(os.path.join(run, "run.json"))
        with stepped(self.beat, ["ub.py", "next", run, "--wait-s", "60"]):
            rc, card = self.run_ub("next", run, "--json")
            self.assertEqual(card["type"], "AUTO", card)
            self.assertIn("pid %d" % self.driver.pid, card["say"])
            rc, res = self.run_ub("stop", run, "--json")
            self.assertIn("pid %d" % self.driver.pid, res["say"])
        self.assertEqual(textio.read_json(os.path.join(run, ".ub", "lock.json")), rec, "the record was moved aside")
        self.assertEqual(textio.read_bytes(os.path.join(run, "run.json")), before, "run.json was driven")

    def test_a_reused_pid_is_still_taken_over(self):
        """Another program, or ub.py on another run, under the dead driver's pid: the record is moved aside."""
        run = self.new_run()
        other = os.path.join(os.path.dirname(run), "2026-09-20-another-run")
        for args in ([sys.executable, os.path.join(self.tmp, "tool.py"), run], self.ub_py("next", other)):
            self.put(run, self.legacy())
            lock = st.DriverLock(run, "claude-code")
            self.assertTrue(lock.acquire())
            try:
                with stepped(self.beat, args):
                    self.assertIsNone(lock.claim(), args)
                self.assertEqual(lock.holder()["pid"], os.getpid())
            finally:
                lock.release()

    @unittest.skipIf(os.name == "nt", "POSIX: Windows process start times do not move with the clock")
    def test_the_command_line_is_read_from_the_process(self):
        run = self.new_run()
        driver = sleeper(os.path.join(self.tmp, "kit", "ub.py"), "next", run)
        self.addCleanup(driver.wait)
        self.addCleanup(driver.kill)
        lock = st.DriverLock(run, "claude-code")
        with mock.patch.object(proc, "process_start_time", lambda pid: self.beat + 3600):
            self.put(run, self.legacy(pid=driver.pid))
            self.assertTrue(lock.legacy_holder(), proc.process_args(driver.pid))
            self.put(run, self.legacy())  # the sleeper of setUp: no ub.py
            self.assertIsNone(lock.legacy_holder())


class OneRule(Base):
    def load_installer(self):
        spec = importlib.util.spec_from_file_location("ub_install_j2c", os.path.join(tl.KIT, "install", "install.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_the_installer_and_the_engine_agree(self):
        install = self.load_installer()
        run = self.new_run()
        now = time.time()
        gone = sleeper()
        gone.kill()
        gone.wait()
        cases = [  # (label, record, start time, command line, live)
            ("a fresh beat", self.legacy(now - 5), now + 3600, [], True),
            ("an old beat, started before it", self.legacy(), self.beat - 10, [], True),
            ("an old beat after a clock step, ub.py on this run", self.legacy(), self.beat + 3600,
             self.ub_py("continue", os.path.basename(run)), True),
            ("an old beat of a reused pid", self.legacy(), self.beat + 3600, [sys.executable, "tool.py"], False),
            ("a beat more than 120 s ahead", self.legacy(now + 600), self.beat - 10, self.ub_py("next", run), False),
            ("a kit 2.1 record", dict(self.legacy(now - 5), since=textio.now_iso()), self.beat - 10, [], False),
            ("a dead pid", self.legacy(now - 5, pid=gone.pid), self.beat - 10, [], False),
        ]
        lock = st.DriverLock(run, "claude-code")
        for label, rec, started, args, want in cases:
            self.put(run, rec)
            with mock.patch.object(proc, "process_start_time", lambda pid, t=started: t), \
                    mock.patch.object(proc, "process_args", lambda pid, a=args: (a, None), create=True):
                self.assertEqual(bool(lock.legacy_holder()), want, "engine: " + label)
                self.assertEqual(bool(install.legacy_driver_alive(run)), want, "installer: " + label)
        self.assertFalse(hasattr(install, "process_args") or hasattr(install, "runs_ub_on"), "a copy of the rule")

    def test_the_engine_never_counts_itself(self):
        run = self.new_run()
        self.put(run, self.legacy(time.time(), pid=os.getpid()))
        self.assertIsNone(st.DriverLock(run).legacy_holder())

    def test_the_idle_age_is_the_rules(self):
        self.assertEqual(st.LEGACY_STALE_S, getattr(proc, "LEGACY_DRIVER_STALE_S", None))


if __name__ == "__main__":
    unittest.main()
