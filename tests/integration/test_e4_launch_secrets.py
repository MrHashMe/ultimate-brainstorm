"""The launcher's token files: no cleanup race, and no sweep of a live launcher's file (audit finding #66, reviewer
note P3-publish-installer-2). Owner: E4.

#66 A path leaves launch.py's list only once its file is gone, and every removal holds one lock: the Windows console
    handler (its own thread) that arrives while the main thread's `finally` is deleting waits, then deletes what is left,
    so it never returns (and lets Windows end the process) while a token file is on disk. A POSIX SIGTERM/SIGHUP deletes
    the files itself and ignores further signals, which could otherwise interrupt the cleanup.
P3-2 Each secret file has a <file>.id holding its writer's process identity. The sweep compares identities, never the
    wall clock: after a clock step a live launcher's start time can look later than its file (Linux btime moves), and
    that file must stay.
"""

import importlib.util
import os
import signal
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "harness"))
import paths  # noqa: E402
from ublib import proc as ubproc  # noqa: E402


def load_launch():
    spec = importlib.util.spec_from_file_location("ub_launch_e4", paths.LAUNCH_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class CleanupRace(unittest.TestCase):
    def setUp(self):
        paths.require(paths.LAUNCH_PY, owner="B1")
        self.mod = load_launch()
        self.dir = tempfile.mkdtemp(prefix="ub-e4-launch-")
        self.addCleanup(lambda: __import__("shutil").rmtree(self.dir, ignore_errors=True))

    def test_console_close_during_the_finally_waits_for_the_removal(self):
        mod = self.mod
        path = mod.write_secret_file(self.dir, "launch", '{"env": {"T": "secret"}}\n')
        inside, go = threading.Event(), threading.Event()
        real = mod.remove_quietly

        def paused(p, attempts=10):
            if threading.current_thread().name == "main-finally" and str(p) == str(path):
                inside.set()
                go.wait(30)  # the main thread is in the middle of deleting the file
            return real(p, attempts)
        mod.remove_quietly = paused
        main = threading.Thread(target=mod.remove_secret_files, name="main-finally")
        main.start()
        self.assertTrue(inside.wait(30))
        seen = {}

        def handler():  # CTRL_CLOSE_EVENT arrives on the console handler thread
            seen["returned"] = mod._on_console_event(2)
            seen["on_disk"] = os.path.exists(str(path))
        h = threading.Thread(target=handler)
        h.start()
        h.join(1.0)  # an unfixed handler returns at once, the file still on disk
        go.set()
        main.join(30)
        h.join(30)
        self.assertIs(seen.get("returned"), True)
        self.assertIs(seen.get("on_disk"), False, "the handler returned while the token file was on disk")
        self.assertEqual(os.listdir(self.dir), [], "the .id file goes too")

    def test_the_writer_is_recorded(self):
        path = self.mod.write_secret_file(self.dir, "launch", "secret\n")
        ident = ubproc.process_identity(os.getpid())
        if not ident:
            self.skipTest("no process identity on this system")
        with open(str(path) + ".id", encoding="utf-8") as f:
            self.assertEqual(f.read().strip(), ident)
        self.mod.remove_secret_files()
        self.assertEqual(os.listdir(self.dir), [])

    def test_no_secret_file_is_written_once_the_console_closes(self):
        mod = self.mod
        self.assertIs(mod._on_console_event(2), True)
        with self.assertRaises(mod.LaunchError):
            mod.write_secret_file(self.dir, "zai-mcp", "secret\n")
        self.assertEqual(os.listdir(self.dir), [])

    def test_sigterm_deletes_the_files_and_ignores_the_next_signal(self):
        mod = self.mod
        path = mod.write_secret_file(self.dir, "launch", '{"env": {"T": "secret"}}\n')
        installed = []
        with mock.patch.object(mod.signal, "signal", lambda sig, h: installed.append((sig, h))):
            with self.assertRaises(SystemExit) as cm:
                mod._on_signal(signal.SIGTERM, None)
        self.assertEqual(cm.exception.code, 128 + signal.SIGTERM)
        self.assertFalse(os.path.exists(str(path)), "deleted by the handler itself")
        self.assertIn((signal.SIGTERM, signal.SIG_IGN), installed, "a second signal cannot cut the cleanup short")


class SweepByIdentity(unittest.TestCase):
    def setUp(self):
        paths.require(paths.LAUNCH_PY, owner="B1")
        self.mod = load_launch()
        self.dir = tempfile.mkdtemp(prefix="ub-e4-sweep-")
        self.addCleanup(lambda: __import__("shutil").rmtree(self.dir, ignore_errors=True))
        self.live = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(600)"],  # a running launcher
                                     stdin=subprocess.DEVNULL)
        self.addCleanup(self.live.wait)
        self.addCleanup(self.live.kill)

    def secret(self, ident=None):
        path = os.path.join(self.dir, "launch-%d-0123456789ab.json" % self.live.pid)
        with open(path, "w", encoding="utf-8") as f:
            f.write('{"env": {"T": "secret"}}\n')
        if ident is not None:
            with open(path + ".id", "w", encoding="utf-8") as f:
                f.write(ident + "\n")
        return path

    def sweep(self, start_offset=5.0):
        """The sweep after the wall clock stepped forward: the live pid's start time now looks start_offset seconds
        later than the file (Linux recomputes btime from the clock)."""
        mtime = os.path.getmtime(os.path.join(self.dir, "launch-%d-0123456789ab.json" % self.live.pid))
        with mock.patch.object(self.mod.proc, "process_start_time", return_value=mtime + start_offset):
            return self.mod.sweep_stale_secret_files(self.dir)

    def test_a_live_launchers_file_survives_a_clock_step(self):
        ident = ubproc.process_identity(self.live.pid)
        if not ident:
            self.skipTest("no process identity on this system")
        path = self.secret(ident)
        self.assertEqual(self.sweep(), 0)
        self.assertTrue(os.path.isfile(path) and os.path.isfile(path + ".id"))

    def test_a_reused_pid_is_swept_by_identity(self):
        ident = ubproc.process_identity(self.live.pid)
        if not ident or not ident.startswith(("win:", "linux:")):
            self.skipTest("identities are exact on Windows and Linux only")
        kind, _sep, value = ident.rpartition(":")
        path = self.secret("%s:%d" % (kind, int(value) - 1))  # the process that wrote it is another one
        self.assertEqual(self.sweep(start_offset=-5.0), 1)
        self.assertEqual(os.listdir(self.dir), [])

    def test_a_file_without_identity(self):
        path = self.secret()
        removed = self.sweep()
        if os.name == "nt":  # a Windows creation time cannot move with the clock: the old rule stays exact
            self.assertEqual(removed, 1)
        else:
            self.assertEqual(removed, 0, "kept while its pid runs")
            self.assertTrue(os.path.isfile(path))

    def test_an_orphan_identity_file_of_a_dead_launcher_goes(self):
        p = subprocess.Popen([sys.executable, "-c", "pass"])
        p.wait()
        orphan = os.path.join(self.dir, "zai-mcp-%d-0123456789ab.json.id" % p.pid)
        with open(orphan, "w", encoding="utf-8") as f:
            f.write("win:1\n")
        self.mod.sweep_stale_secret_files(self.dir)
        self.assertFalse(os.path.exists(orphan))


if __name__ == "__main__":
    unittest.main()
