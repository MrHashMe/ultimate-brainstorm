"""WP2a: ublib.proc completes on the child's exit, bounds what it buffers, kills what is left of the child's tree, and
identifies processes exactly (KIT_SPEC 3.1, 4.7, 5.4).

These tests start real child processes (the current Python interpreter only); no model CLI and no network.
"""

import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import tracemalloc
import unittest

_KIT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_SCRIPTS = os.path.join(_KIT, "skills", "ultimate-brainstorm", "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

from ublib import proc  # noqa: E402

PY = sys.executable

# A "CLI" that answers, exits 0 and leaves a grandchild that inherited its stdout/stderr (a Node child spawned with
# stdio 'inherit', a .cmd shim's `start /b`, an MCP helper) sleeping for 30 s. argv: <info file> [setsid]
ORPHAN_CLI = r'''
import subprocess, sys, time
kw = {"close_fds": False}
if sys.platform == "win32":
    kw["creationflags"] = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
elif sys.argv[2:] == ["setsid"]:
    kw["start_new_session"] = True  # leaves our process group
g = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"], **kw)
sys.stdout.write("ANSWER\n")
sys.stdout.flush()
with open(sys.argv[1], "w") as f:
    f.write("%d %r" % (g.pid, time.time()))
'''

# A worker stand-in: SIGTERM raises SystemExit (as in family.py) while proc.run waits for a CLI that ignores SIGTERM.
# argv: <scripts> <cli pid file>
MINI_WORKER = r'''
import signal, sys
sys.path.insert(0, sys.argv[1])
from ublib import proc
signal.signal(signal.SIGTERM, lambda *_a: sys.exit(143))
CLI = ("import os, signal, sys, time\n"
       "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
       "open(sys.argv[1], 'w').write(str(os.getpid()))\n"
       "time.sleep(120)\n")
proc.run([sys.executable, "-c", CLI, sys.argv[2]], timeout_s=300)
'''


def wait_until(pred, timeout=15.0, step=0.05):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pred():
            return True
        time.sleep(step)
    return pred()


def read_int(path):
    try:
        with open(path) as f:
            return int(f.read().split()[0])
    except (OSError, ValueError, IndexError):
        return None


class CompletionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ub-wp2a-proc-")
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def orphan_run(self, *extra):
        info = os.path.join(self.tmp, "orphan.txt")
        r = proc.run([PY, "-c", ORPHAN_CLI, info] + list(extra), cwd=self.tmp, timeout_s=60)
        returned = time.time()
        with open(info) as f:
            gpid, exited = f.read().split()
        gpid = int(gpid)
        self.addCleanup(proc.kill_tree, gpid, 0.5)
        return r, gpid, returned - float(exited)

    def test_a_descendant_holding_the_pipes_does_not_hold_run_up(self):
        r, gpid, after_exit = self.orphan_run()
        self.assertLess(after_exit, 3.0, "run() returned %.1f s after the child's exit (the grandchild sleeps 30 s)"
                        % after_exit)
        self.assertEqual((r.returncode, r.timed_out, r.overflow), (0, False, False))
        self.assertEqual(r.stdout_bytes.strip(), b"ANSWER", "the answer is intact")
        self.assertTrue(wait_until(lambda: not proc.pid_alive(gpid), 5), "the grandchild %d survived" % gpid)

    @unittest.skipIf(proc.IS_WINDOWS, "POSIX: a descendant can leave the child's process group")
    def test_a_pipe_holder_outside_the_tree_costs_at_most_the_linger(self):
        r, gpid, after_exit = self.orphan_run("setsid")
        self.assertEqual((r.returncode, r.timed_out), (0, False))
        self.assertEqual(r.stdout_bytes.strip(), b"ANSWER")
        self.assertLess(after_exit, 4.0)

    def test_a_stdout_flood_is_capped_with_bounded_buffering(self):
        flood = "import sys\nb = b'x' * 65536\nfor _ in range(3200):\n    sys.stdout.buffer.write(b)\n"  # 200 MB
        cap = 1 << 20
        tracemalloc.start()
        try:
            t0 = time.monotonic()
            r = proc.run([PY, "-c", flood], cwd=self.tmp, timeout_s=120, max_stdout=cap)
            elapsed = time.monotonic() - t0
            _cur, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        self.assertTrue(r.overflow)
        self.assertFalse(r.timed_out)
        self.assertEqual(r.stdout_bytes, b"x" * cap, "the head up to the cap is kept")
        self.assertLess(peak, 8 * cap, "the readers kept %d bytes at their peak" % peak)
        self.assertLess(elapsed, 30)

    def test_the_default_stdout_cap_is_8_mb(self):
        self.assertEqual(proc.STDOUT_CAP_BYTES, 8 * 1024 * 1024)
        code = "import sys\nsys.stdout.buffer.write(b'y' * (9 * 1024 * 1024))\n"
        r = proc.run([PY, "-c", code], cwd=self.tmp, timeout_s=60)
        self.assertTrue(r.overflow)
        self.assertEqual(len(r.stdout_bytes), proc.STDOUT_CAP_BYTES)
        r = proc.run([PY, "-c", code], cwd=self.tmp, timeout_s=60, max_stdout=None)
        self.assertFalse(r.overflow)
        self.assertEqual(len(r.stdout_bytes), 9 * 1024 * 1024)

    def test_stderr_keeps_a_bounded_tail(self):
        code = "import sys\nfor i in range(20000):\n    sys.stderr.write('line %06d\\n' % i)\n"  # about 240 KB
        r = proc.run([PY, "-c", code], cwd=self.tmp, timeout_s=60)
        self.assertEqual(r.returncode, 0)
        self.assertEqual(len(r.stderr_bytes), 64 * 1024)
        self.assertTrue(r.stderr_bytes.rstrip().endswith(b"line 019999"))
        self.assertEqual(proc.STDERR_TAIL_BYTES, 64 * 1024)

    def test_binary_stdin_and_stdout_pass_unchanged(self):
        payload = b"a\r\nb\x1ac\x00\xff\n" * 50000
        code = "import sys; d = sys.stdin.buffer.read(); sys.stdout.buffer.write(d[::-1])"
        r = proc.run([PY, "-c", code], cwd=self.tmp, stdin_bytes=payload, timeout_s=60)
        self.assertEqual(r.returncode, 0, r.stderr_bytes)
        self.assertEqual(r.stdout_bytes, payload[::-1])

    def test_a_timeout_keeps_what_was_read(self):
        code = "import sys, time; sys.stdout.write('partial'); sys.stdout.flush(); time.sleep(60)"
        r = proc.run([PY, "-c", code], cwd=self.tmp, timeout_s=2)
        self.assertTrue(r.timed_out)
        self.assertEqual(r.stdout_bytes, b"partial")

    def test_a_stopped_worker_stops_its_backend_process_within_the_abort_grace(self):
        """ub stop: SIGTERM makes the worker raise SystemExit inside run(); run() kills a CLI that ignores SIGTERM
        after ABORT_GRACE_S. Windows: the worker is killed hard (TerminateProcess) and the CLI dies with the Job Object
        handle (KILL_ON_JOB_CLOSE)."""
        pidfile = os.path.join(self.tmp, "cli.pid")
        w = subprocess.Popen([PY, "-c", MINI_WORKER, _SCRIPTS, pidfile])
        self.addCleanup(w.wait)
        self.assertTrue(wait_until(lambda: read_int(pidfile), 30), "the CLI never started")
        cli = read_int(pidfile)
        self.addCleanup(proc.kill_tree, cli, 0.5)
        t0 = time.monotonic()
        if proc.IS_WINDOWS:
            w.kill()
        else:
            os.kill(w.pid, signal.SIGTERM)
        self.assertTrue(wait_until(lambda: not proc.pid_alive(cli), 12), "the CLI outlived its worker")
        self.assertLess(time.monotonic() - t0, 3.5, "a stop must not wait out a CLI that ignores SIGTERM")
        self.assertEqual(proc.ABORT_GRACE_S, 1.0)


class IdentityTests(unittest.TestCase):
    def test_an_identity_names_one_process(self):
        p = subprocess.Popen([PY, "-c", "import time; time.sleep(30)"])
        self.addCleanup(p.wait)
        self.addCleanup(p.kill)
        ident = proc.process_identity(p.pid)
        self.assertTrue(ident)
        self.assertEqual(proc.process_identity(p.pid), ident, "stable while the process runs")
        self.assertNotEqual(proc.process_identity(os.getpid()), ident)
        self.assertTrue(proc.same_process(p.pid, ident))
        self.assertFalse(proc.same_process(p.pid, ident + "0"), "another creation time: a reused pid")
        self.assertFalse(proc.same_process(p.pid, None), "an unknown identity never matches")
        self.assertIsNone(proc.process_identity(0))
        self.assertIsNone(proc.process_identity("x"))
        p.kill()
        p.wait()
        self.assertFalse(proc.same_process(p.pid, ident))

    def test_a_start_time_is_epoch_seconds(self):
        # profiles/launch.py compares it with a secret file's mtime to tell a reused pid from its launcher
        before = time.time()
        p = subprocess.Popen([PY, "-c", "import time; time.sleep(30)"])
        self.addCleanup(p.wait)
        self.addCleanup(p.kill)
        started = proc.process_start_time(p.pid)
        self.assertIsNotNone(started)
        self.assertLess(abs(started - before), 5.0)
        self.assertLess(proc.process_start_time(os.getpid()), started + 1.0)
        self.assertIsNone(proc.process_start_time(0))

    def test_the_spawn_hook_reports_each_child(self):
        seen = []
        proc.set_spawn_hook(lambda pid, ident: seen.append((pid, ident, bool(pid) and proc.same_process(pid, ident))))
        self.addCleanup(proc.set_spawn_hook, None)
        r = proc.run([PY, "-c", "import time; time.sleep(0.2)"], timeout_s=30)
        self.assertEqual(r.returncode, 0)
        self.assertEqual(len(seen), 2, seen)
        self.assertTrue(seen[0][0] and seen[0][1] and seen[0][2], "the child's pid and identity, while it ran")
        self.assertEqual(seen[1], (None, None, False), "then: gone")
        proc.set_spawn_hook(lambda pid, ident: 1 / 0)  # a failing hook never breaks a call
        self.assertEqual(proc.run([PY, "-c", "pass"], timeout_s=30).returncode, 0)


if __name__ == "__main__":
    unittest.main()
