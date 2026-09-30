"""E2: worker process fixes (findings 2 and 6, reviewer notes P3-worker-proc-0 to -4).

- kill_tree signals a process group only when the target leads it: a `family.py batch` worker shares its launcher's
  group, and stopping it used to kill the launcher and every sibling (2);
- a stop that lands while proc.run starts a child (in Popen, or in the spawn hook that records it) kills the child;
  it used to escape run() and leave the CLI running unrecorded in its own session (6, P3-worker-proc-0);
- explain_long_path relabels only the errors a too-long path causes, and not when long paths are enabled (-1);
- the done rule accepts a kit 2.0.3 host meta, which hashed the decoded text of <out> (-2);
- stop_all stops an in-flight kit 2.0.3 worker (its marker has no identity) by 2.0.3's own start-time rule (-3);
- the macOS/BSD process identity (ps lstart) does not depend on the caller's time zone (-4).
Real child processes are the current Python interpreter only.
"""

import calendar
import errno
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

_KIT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_SCRIPTS = os.path.join(_KIT, "skills", "ultimate-brainstorm", "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

from ublib import batch, proc, textio  # noqa: E402

PY = sys.executable
SLEEPER = [PY, "-c", "import time; time.sleep(60)"]


def wait_until(pred, timeout=15.0, step=0.05):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pred():
            return True
        time.sleep(step)
    return pred()


def iso(age_s=0.0):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - age_s))


class Tmp(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ub-e2-proc-")
        self.addCleanup(shutil.rmtree, self.tmp, True)


# ---------------------------------------------------------------- 2: whose group is signaled

class KillTreeGroupTests(unittest.TestCase):
    def kill(self, pid, pgid_of):
        calls = []

        def killpg(g, s):
            calls.append(("group", g))
        with mock.patch.object(proc, "IS_WINDOWS", False), \
                mock.patch.object(proc.os, "getpgid", create=True, side_effect=lambda p: pgid_of.get(p, 999)), \
                mock.patch.object(proc.os, "killpg", create=True, side_effect=killpg), \
                mock.patch.object(proc.os, "kill", side_effect=lambda p, s: calls.append(("pid", p))), \
                mock.patch.object(proc, "pid_alive", return_value=False), \
                mock.patch.object(proc, "_group_alive", return_value=False):
            proc.kill_tree(pid, grace_s=0.1)
        return calls

    def test_a_worker_in_its_launchers_group_is_signaled_alone(self):
        calls = self.kill(4242, {4242: 4200, 0: 999})  # the worker's group is its launcher's (4200)
        self.assertTrue(calls)
        self.assertEqual(set(calls), {("pid", 4242)}, "the launcher's group was signaled: %s" % calls)

    def test_a_group_leader_takes_its_group(self):
        self.assertEqual(set(self.kill(4242, {4242: 4242, 0: 999})), {("group", 4242)})

    def test_our_own_group_is_never_signaled(self):
        self.assertEqual(set(self.kill(999, {999: 999, 0: 999})), {("pid", 999)})

    @unittest.skipIf(proc.IS_WINDOWS, "POSIX process groups")
    def test_stopping_an_attached_worker_spares_its_launcher_and_siblings(self):
        launcher = ("import subprocess, sys, time\n"
                    "w = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
                    "b = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
                    "print(w.pid, b.pid, flush=True)\n"
                    "time.sleep(60)\n")
        p = subprocess.Popen([PY, "-c", launcher], stdout=subprocess.PIPE, start_new_session=True)
        self.addCleanup(proc.kill_tree, p.pid, 0.5)
        worker, bystander = [int(x) for x in p.stdout.readline().split()]
        self.addCleanup(proc.kill_tree, bystander, 0.5)
        self.assertEqual(os.getpgid(worker), p.pid)
        proc.kill_tree(worker, grace_s=1.0)
        self.assertTrue(wait_until(lambda: not proc.pid_alive(worker), 5))
        self.assertTrue(proc.pid_alive(bystander), "a sibling in the launcher's group was killed")
        self.assertTrue(proc.pid_alive(p.pid), "the launcher was killed")


# ---------------------------------------------------------------- 6: a stop while the child starts

class StartWindowTests(Tmp):
    def tearDown(self):
        proc.set_spawn_hook(None)

    def test_a_spawn_hook_that_raises_leaves_no_child_running(self):
        seen = []

        def hook(pid, ident):
            if pid:
                seen.append(pid)
                raise SystemExit(143)  # SIGTERM from `ub stop` while the worker writes its marker
        proc.set_spawn_hook(hook)
        with self.assertRaises(SystemExit):
            proc.run(SLEEPER, cwd=self.tmp, timeout_s=120)
        self.assertEqual(len(seen), 1)
        self.addCleanup(proc.kill_tree, seen[0], 0.5)
        self.assertTrue(wait_until(lambda: not proc.pid_alive(seen[0]), 10), "the CLI outlived the stop")

    def test_a_signal_while_popen_returns_kills_the_child(self):
        real = subprocess.Popen
        started = []

        def popen(*a, **kw):
            p = real(*a, **kw)
            if not started:  # the CLI; later calls are the kill's own (taskkill on Windows)
                started.append(p.pid)
                signal.raise_signal(signal.SIGINT)  # its handler runs before Popen's caller gets the object
            return p
        old = signal.signal(signal.SIGINT, lambda *_a: sys.exit(143))
        self.addCleanup(signal.signal, signal.SIGINT, old)
        with mock.patch.object(proc.subprocess, "Popen", side_effect=popen):
            with self.assertRaises(SystemExit):
                proc.run(SLEEPER, cwd=self.tmp, timeout_s=120)
        self.assertEqual(len(started), 1)
        self.addCleanup(proc.kill_tree, started[0], 0.5)
        self.assertTrue(wait_until(lambda: not proc.pid_alive(started[0]), 10), "the CLI outlived the stop")
        handler = signal.getsignal(signal.SIGINT)
        self.assertNotIsInstance(getattr(handler, "__self__", None), proc._SignalHold, "the handler is restored")

    def test_no_signal_means_no_change(self):
        handler = signal.getsignal(signal.SIGINT)
        r = proc.run([PY, "-c", "print('ok')"], cwd=self.tmp, timeout_s=60)
        self.assertEqual(r.stdout_bytes.strip(), b"ok")
        self.assertIs(signal.getsignal(signal.SIGINT), handler)


# ---------------------------------------------------------------- P3-worker-proc-1: long paths

class LongPathTests(unittest.TestCase):
    LONG = "C:/" + "/".join(["d" * 40] * 7) + "/x.md"

    def explain(self, exc, enabled):
        with mock.patch.object(textio, "_WINDOWS", True), \
                mock.patch.object(textio, "long_paths_enabled", return_value=enabled):
            return textio.explain_long_path(exc, self.LONG)

    def test_only_errors_a_long_path_causes_are_relabeled(self):
        self.assertIsInstance(self.explain(FileNotFoundError(errno.ENOENT, "missing"), False), textio.PathTooLong)
        self.assertIsInstance(self.explain(OSError(errno.ENAMETOOLONG, "too long"), None), textio.PathTooLong)
        denied = PermissionError(errno.EACCES, "Access is denied")
        self.assertIs(self.explain(denied, False), denied, "access denied is not a path length problem")
        full = OSError(errno.ENOSPC, "no space")
        self.assertIs(self.explain(full, False), full)

    def test_nothing_is_relabeled_when_long_paths_are_enabled(self):
        missing = FileNotFoundError(errno.ENOENT, "missing")
        self.assertIs(self.explain(missing, True), missing)

    def test_a_read_only_long_path_keeps_its_error(self):
        with mock.patch.object(textio, "_WINDOWS", True), \
                mock.patch.object(textio, "long_paths_enabled", return_value=True), \
                mock.patch("tempfile.mkstemp", side_effect=PermissionError(errno.EACCES, "Access is denied")), \
                mock.patch("os.makedirs"):
            with self.assertRaises(PermissionError) as cm:
                textio.write_text_atomic(self.LONG, "x")
        self.assertNotIsInstance(cm.exception, textio.PathTooLong)


# ---------------------------------------------------------------- P3-worker-proc-2: 2.0.3 host metas

class LegacyHostMetaTests(Tmp):
    def job(self, backend):
        run = os.path.join(self.tmp, "run")
        textio.write_text_atomic(os.path.join(run, "prompts", "h.prompt.md"), "the host prompt\n")
        out = os.path.join(run, "pool", "h.md")
        os.makedirs(os.path.dirname(out))
        with open(out, "wb") as f:  # a host sub-agent's file: a BOM and CRLF line ends
            f.write(b"\xef\xbb\xbfIdea one\r\nIdea two\r\n")
        job = {"id": "h1", "run": run, "prompt_file": "prompts/h.prompt.md", "out": "pool/h.md",
               "contract": {"type": "text", "min_chars": 5}}
        meta = {"id": "h1", "status": "ok", "backend": backend,
                "prompt_sha256": textio.sha256_file(os.path.join(run, "prompts", "h.prompt.md")),
                "out_sha256": textio.sha256_text(textio.read_text(out))}  # 2.0.3's host form: the decoded text
        textio.write_json_atomic(out + ".meta.json", meta)
        return run, job

    def test_a_203_host_output_stays_done(self):
        run, job = self.job("host")
        self.assertTrue(batch.is_done(run, job))

    def test_a_worker_meta_is_still_compared_byte_for_byte(self):
        run, job = self.job("claude-cli")
        self.assertFalse(batch.is_done(run, job))


# ---------------------------------------------------------------- P3-worker-proc-3: 2.0.3 markers

class LegacyMarkerTests(Tmp):
    def test_stop_all_stops_an_in_flight_203_worker(self):
        run = os.path.join(self.tmp, "run")
        worker = subprocess.Popen(SLEEPER)
        self.addCleanup(worker.wait)
        self.addCleanup(proc.kill_tree, worker.pid, 0.5)
        # the 2.0.3 marker format: pid, started_at, heartbeat_at; no identity
        textio.write_json_atomic(batch.marker_path(run, "j1"), {"pid": worker.pid, "started_at": iso(),
                                                                 "heartbeat_at": iso(), "attempt": 1,
                                                                 "backend": "claude-cli"})
        with mock.patch("ublib.backends.sweep_stale_calls"):
            self.assertEqual(batch.stop_all(run), 1)
        self.assertTrue(wait_until(lambda: worker.poll() is not None, 15), "the 2.0.3 worker kept running")


# ---------------------------------------------------------------- P3-worker-proc-4: ps identity

class PsIdentityTests(unittest.TestCase):
    INSTANT = (2026, 9, 21, 13, 13, 20)

    def fake_ps(self, argv, **kw):
        """ps prints lstart in the local time of the TZ it gets (UTC0 or a zone 7 hours behind)."""
        t = list(self.INSTANT)
        if (kw.get("env") or {}).get("TZ") != "UTC0":
            t[3] -= 7
        text = time.strftime("%a %b %d %H:%M:%S %Y", tuple(t) + (0, 0, 0))
        return subprocess.CompletedProcess(argv, 0, (text + "\n").encode("ascii"), b"")

    def test_the_identity_does_not_depend_on_the_callers_time_zone(self):
        seen = []
        with mock.patch.object(proc, "which", return_value="/usr/bin/ps"), \
                mock.patch.object(proc.subprocess, "run", side_effect=self.fake_ps):
            for tz in ("America/Los_Angeles", "UTC0"):
                with mock.patch.dict(os.environ, {"TZ": tz}):
                    seen.append(proc._ps_start(1234))
        self.assertEqual(seen[0], seen[1], seen)
        self.assertEqual(seen[0], "ps:Mon Sep 21 13:13:20 2026")

    def test_the_start_time_is_read_as_utc(self):
        with mock.patch.object(proc, "process_identity", return_value="ps:Mon Sep 21 13:13:20 2026"):
            self.assertEqual(proc.process_start_time(1234), float(calendar.timegm(self.INSTANT + (0, 0, 0))))


class ZombieTests(unittest.TestCase):
    """macOS and BSD have no /proc: a killed child its parent has not reaped (a zombie) still answers signal 0, so
    pid_alive asks ps for its state there, as it reads /proc/<pid>/stat on Linux."""

    def alive(self, stat, returncode=0):
        def fake_ps(argv, **kw):
            return subprocess.CompletedProcess(argv, returncode, (stat + "\n").encode("ascii"), b"")
        with mock.patch.object(proc, "IS_WINDOWS", False), mock.patch.object(proc.sys, "platform", "darwin"), \
                mock.patch.object(proc.os, "kill"), mock.patch.object(proc, "which", return_value="/usr/bin/ps"), \
                mock.patch.object(proc.subprocess, "run", side_effect=fake_ps):
            return proc.pid_alive(1234)

    def test_a_zombie_is_not_alive(self):
        self.assertFalse(self.alive("Z+"))
        self.assertFalse(self.alive("Zs"))

    def test_a_running_or_unreadable_process_is_alive(self):
        self.assertTrue(self.alive("S"))
        self.assertTrue(self.alive("Ss+"))
        self.assertTrue(self.alive("", returncode=1))  # ps could not say: alive, so nothing is killed by mistake


if __name__ == "__main__":
    unittest.main()
