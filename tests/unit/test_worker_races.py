"""Regressions for the Windows-only CI failures after 2.0.1 (KIT_SPEC 4.5, 4.6, 4.7).

1. "jobs with status ok recorded twice" (13.2-C in proposal mode). The three 13.2 workers write into the same new folder
   11_PROPOSAL/sections/. When a sibling creates it while os.path.realpath() resolves a target, Windows realpath()
   returns the \\\\?\\ form, the split write said "resolves outside the output root", and the adapter answered with a
   repair call: a second model call for one job and one prompt. Now the prefix is normalized, valid output that cannot
   be written is retried locally (never repaired), and one job has at most one worker executing it (execution lock +
   done re-check under the lock), so a running or finished job is never called twice.
2. PermissionError opening a running marker that a worker was replacing. Every read of a marker, meta, job or result
   file now retries that transient error, so no state decision is made on a half-seen file.

Real worker processes run family.py with the stub backend (UB_FAKE_FAMILIES=1). No model CLI and no network.
"""

import builtins
import contextlib
import errno
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

_KIT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(_KIT, "tests", "fixtures", "adapter"))

import adapter_testlib as tl  # noqa: E402
from ublib import adapter, batch, filesproto, proc, textio  # noqa: E402

try:
    from ublib import stubs as _stubs  # noqa: F401  (B4)
    HAVE_STUBS = True
except ImportError:  # pragma: no cover
    HAVE_STUBS = False

FAMILY_PY = os.path.join(tl.SCRIPTS, "family.py")
TEXT = {"type": "text", "min_chars": 5}
SECTIONS = ["sections/05.md", "sections/06.md"]
LONG_PREFIX = "\\\\?\\"


def files_job_fields(job_id):
    """A 13.2-like job: FILE-protocol output split into 11_PROPOSAL/sections/."""
    per = {"sections/05.md": {"headings": ["## 5. Solution"]}, "sections/06.md": {"headings": ["## 6. Architecture"]}}
    contract = {"type": "files", "allowed": SECTIONS, "required": SECTIONS, "status_trailer": True, "per_file": per}
    split = {"root": "11_PROPOSAL", "allowed": SECTIONS, "status_out": "11_PROPOSAL/_raw/%s.status.json" % job_id}
    return {"contract": contract, "split": split, "out": "11_PROPOSAL/_raw/%s.out.md" % job_id, "kind": "writer"}


def wait_until(pred, timeout=30.0, step=0.1):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pred():
            return True
        time.sleep(step)
    return pred()


def read_marker(path):
    """The marker dict, or {} while it is missing (or unreadable)."""
    try:
        data = textio.read_json(path)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


@contextlib.contextmanager
def transient_permission_errors(suffix, times):
    """The first `times` opens of files ending in `suffix` fail like a read that lands in another process's
    os.replace on Windows (sharing violation: PermissionError errno 13); later opens work."""
    real_open = builtins.open
    state = {"left": times}

    def fake_open(file, *a, **kw):
        if isinstance(file, (str, bytes, os.PathLike)) and os.fsdecode(file).endswith(suffix) and state["left"] > 0:
            state["left"] -= 1
            raise PermissionError(errno.EACCES, "Permission denied", os.fsdecode(file))
        return real_open(file, *a, **kw)

    retry = mock.patch.object(textio, "RETRY_TRANSIENT_READS", True, create=True)  # the Windows behavior, anywhere
    with mock.patch.object(builtins, "open", fake_open), retry:
        yield state


def racing_finalpath(folder):
    """ntpath._getfinalpathname that lets a 'sibling worker' create `folder` right after the first lookup of a path
    inside it failed: the interleaving in which Windows realpath() keeps the \\\\?\\ prefix."""
    import ntpath
    real = ntpath._getfinalpathname
    state = {"created": False}
    inside = os.path.normcase(folder) + os.sep

    def fake(path):
        try:
            return real(path)
        except OSError:
            if not state["created"] and os.path.normcase(os.fsdecode(path)).startswith(inside):
                state["created"] = True
                os.makedirs(folder, exist_ok=True)
            raise

    return mock.patch.object(ntpath, "_getfinalpathname", side_effect=fake), state


class RaceBase(tl.AdapterTestCase):
    def setUp(self):
        super(RaceBase, self).setUp()
        os.environ["UB_FAKE_FAMILIES"] = "1"
        os.environ["UB_HEARTBEAT_STALE_S"] = "3"
        self.addCleanup(self._stop)

    def _stop(self):
        try:
            batch.stop_all(self.run_dir)
        except OSError:
            pass

    def job(self, job_id, **kw):
        job = self.make_job(job_id=job_id, family=kw.pop("family", "claude"), contract=kw.pop("contract", TEXT), **kw)
        path = self.write_job(job)
        job["_path"] = path
        return job, path

    def ok_calls(self, job_id):
        return [c for c in self.calls_log() if c.get("id") == job_id and c.get("status") == "ok"]

    def run_worker(self, path, timeout=120):
        return subprocess.run([sys.executable, FAMILY_PY, "job", "--job", path], env=dict(os.environ),
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)

    def worker_log(self, job_id):
        try:
            return textio.read_text(os.path.join(self.run_dir, "logs", "%s.log" % job_id))
        except OSError:
            return ""

    def write_done(self, job):
        out = self.out_path(job)
        textio.write_text_atomic(out, "A valid answer text.")
        prompt = os.path.join(self.run_dir, job["prompt_file"])
        textio.write_json_atomic(out + ".meta.json", {"schema": 1, "id": job["id"], "status": "ok",
                                                      "prompt_sha256": textio.sha256_file(prompt)})


# ---------------------------------------------------------------- 1. the realpath race and the repair call

class RealPath(unittest.TestCase):
    def test_a_stray_long_prefix_is_dropped(self):
        with mock.patch.object(textio.os.path, "realpath", side_effect=lambda p: LONG_PREFIX + "C:\\r\\sections\\a.md"):
            self.assertEqual(textio.real_path("C:\\r\\sections\\a.md"), "C:\\r\\sections\\a.md")
        with mock.patch.object(textio.os.path, "realpath",
                               side_effect=lambda p: LONG_PREFIX + "UNC\\srv\\share\\r\\a.md"):
            self.assertEqual(textio.real_path("\\\\srv\\share\\r\\a.md"), "\\\\srv\\share\\r\\a.md")
        with mock.patch.object(textio.os.path, "realpath", side_effect=lambda p: p):
            self.assertEqual(textio.real_path(LONG_PREFIX + "C:\\r\\a.md"), LONG_PREFIX + "C:\\r\\a.md")


@unittest.skipUnless(os.name == "nt", "the extended-length prefix race is specific to ntpath.realpath")
class SiblingCreatesTheFolder(RaceBase):
    """The exact interleaving of 13.2-A/B/C, reproduced in-process with the real realpath() code."""

    def setUp(self):
        super(SiblingCreatesTheFolder, self).setUp()
        self.root = os.path.join(self.run_dir, "11_PROPOSAL")
        os.makedirs(os.path.join(self.root, "_raw"))
        self.folder = os.path.join(os.path.realpath(self.root), "sections")
        patch, state = racing_finalpath(self.folder)
        with patch:
            premise = os.path.realpath(os.path.join(self.folder, "05.md"))
        if not (state["created"] and premise.startswith(LONG_PREFIX)):
            self.skipTest("this Python's realpath() no longer keeps the extended-length prefix here")
        shutil.rmtree(self.folder)

    def test_split_write_stays_inside_the_root(self):
        patch, state = racing_finalpath(self.folder)
        with patch:
            written = filesproto.write_file_blocks({"sections/05.md": "## 5. Solution\n\nText.\n"}, self.root,
                                                   ["sections/*.md"])
        self.assertTrue(state["created"])
        self.assertEqual([os.path.normcase(p) for p in written],
                         [os.path.normcase(os.path.join(self.folder, "05.md"))])

    @unittest.skipUnless(HAVE_STUBS, "ublib.stubs (B4) not present")
    def test_no_second_model_call_for_the_job(self):
        job, path = self.job("13.2-B", **files_job_fields("13.2-B"))
        patch, state = racing_finalpath(self.folder)
        with patch:
            meta = adapter.execute_job(job, job_file=path)
        self.assertTrue(state["created"])
        self.assertEqual((meta["status"], meta["attempts"], meta["repaired"]), ("ok", 1, False))
        self.assertEqual(len(self.ok_calls("13.2-B")), 1, "one job, one prompt: one model call")
        self.assertTrue(os.path.isfile(os.path.join(self.folder, "05.md")))


class SplitIoErrors(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ub-race-")
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_io_error_is_reported_apart_from_output_errors(self):
        text = "=== FILE: a.md ===\nx\n=== END FILE ===\n"
        with mock.patch.object(filesproto.os, "replace", side_effect=OSError(errno.EIO, "I/O error")):
            res = filesproto.split_output(text, self.tmp, ["*.md"])
        self.assertEqual((res["ok"], res.get("io_error")), (False, True))
        res = filesproto.split_output("=== FILE: ../a.md ===\nx\n=== END FILE ===\n", self.tmp, ["*.md"])
        self.assertEqual((res["ok"], res.get("io_error")), (False, False))


@unittest.skipUnless(HAVE_STUBS, "ublib.stubs (B4) not present")
class WriteErrorsAreNotRepaired(RaceBase):
    """Valid output that cannot be written is a local problem: retried here, never answered with a repair call."""

    def flaky_section_replace(self, fail_times):
        real = os.replace
        state = {"failed": 0}

        def flaky(src, dst):
            if "sections" in os.fsdecode(dst) and state["failed"] < fail_times:
                state["failed"] += 1
                raise OSError(errno.EIO, "I/O error (simulated)")
            return real(src, dst)

        return mock.patch.object(filesproto.os, "replace", side_effect=flaky), state

    def test_a_transient_write_error_costs_no_second_call(self):
        job, path = self.job("13.2-A", **files_job_fields("13.2-A"))
        patch, state = self.flaky_section_replace(1)
        with patch:
            meta = adapter.execute_job(job, job_file=path)
        self.assertEqual(state["failed"], 1)
        self.assertEqual((meta["status"], meta["attempts"], meta["repaired"]), ("ok", 1, False))
        self.assertEqual(len(self.ok_calls("13.2-A")), 1)

    def test_a_lasting_write_error_fails_without_a_repair_call(self):
        job, path = self.job("13.2-C", **files_job_fields("13.2-C"))
        patch, _state = self.flaky_section_replace(10 ** 6)
        with patch:
            meta = adapter.execute_job(job, job_file=path)
        self.assertEqual((meta["status"], meta["error_class"], meta["attempts"]), ("failed", "internal", 1))
        self.assertEqual(len(self.calls_log()), 1, "no repair call for a write error")
        self.assertFalse(os.path.exists(self.out_path(job)))
        self.assertTrue(textio.read_text(self.out_path(job) + ".failed.md").startswith("FAMILY CALL FAILED:"))


# ---------------------------------------------------------------- 2. one worker per job

@unittest.skipUnless(HAVE_STUBS, "ublib.stubs (B4) not present")
class OneWorkerPerJob(RaceBase):
    def test_a_second_worker_for_a_running_job_makes_no_call(self):
        os.environ["UB_STUB_DELAY_S"] = "3"
        job, path = self.job("r1")
        info = batch.launch_job(path)
        marker = batch.marker_path(self.run_dir, "r1")
        self.assertTrue(wait_until(lambda: read_marker(marker).get("backend") == "stub", timeout=20))
        # the worker's own marker; its pid is the worker's, which in a Windows venv is a child of info["pid"]
        own = read_marker(marker)
        self.assertTrue(info.get("launched", True) and own.get("pid") and own.get("token"))
        t0 = time.monotonic()
        cp = self.run_worker(path)
        self.assertEqual(cp.returncode, 0, cp.stderr)
        self.assertIn(b"skipped job=r1", cp.stdout)
        self.assertLess(time.monotonic() - t0, 20, "the marker names a live worker: no long wait for the lock")
        now = read_marker(marker)
        self.assertEqual((now.get("pid"), now.get("token")), (own["pid"], own["token"]),
                         "the running worker's marker is untouched")
        self.assertTrue(wait_until(lambda: batch.job_state(self.run_dir, job) == "done", timeout=40))
        self.assertEqual(len(self.ok_calls("r1")), 1)

    def test_a_worker_for_a_finished_job_makes_no_call(self):
        job, path = self.job("r2")
        cp = self.run_worker(path)
        self.assertEqual(cp.returncode, 0, cp.stderr)
        meta = self.read_meta(job)
        cp = self.run_worker(path)
        self.assertEqual(cp.returncode, 0, cp.stderr)
        self.assertIn(b"already done", cp.stdout)
        self.assertEqual(self.read_meta(job), meta, "the cached result stands")
        self.assertEqual(len(self.ok_calls("r2")), 1)
        self.assertFalse(os.path.exists(batch.marker_path(self.run_dir, "r2")))

    def test_launch_job_does_not_launch_a_running_or_finished_job(self):
        os.environ["UB_STUB_DELAY_S"] = "3"
        job, path = self.job("r3")
        marker = batch.marker_path(self.run_dir, "r3")
        first = batch.launch_job(path)
        self.assertTrue(first.get("launched", True))
        token = read_marker(marker).get("token")
        self.assertTrue(token, "launch_job writes the marker (with its launch token) before it returns")
        second = batch.launch_job(path)  # a second driver poll with a stale view of the job
        self.assertEqual((second.get("launched"), second.get("state")), (False, "running"))
        self.assertEqual(read_marker(marker).get("token"), token, "the first launch's worker still owns the job")
        self.assertTrue(wait_until(lambda: batch.job_state(self.run_dir, job) == "done", timeout=40))
        third = batch.launch_job(path)
        self.assertEqual((third.get("launched"), third.get("state")), (False, "done"))
        self.assertEqual(len(self.ok_calls("r3")), 1)
        self.assertEqual(batch.relaunch_count(self.run_dir, job), 0)

    def test_the_launch_marker_never_outlives_its_worker(self):
        """launch_job used to read the marker, then write it back with the child's pid. A worker that finished in
        between (a descheduled driver) had its deleted marker re-created: a stale marker for a finished job."""
        job, path = self.job("r4")
        marker = batch.marker_path(self.run_dir, "r4")
        meta_path = self.out_path(job) + ".meta.json"
        real_write = textio.write_json_atomic

        def slow_launcher_write(p, obj):
            launcher_record = isinstance(obj, dict) and obj.get("pid") and obj.get("attempt") == 0 and \
                not obj.get("backend")
            if launcher_record and os.path.normcase(os.fspath(p)) == os.path.normcase(marker):
                wait_until(lambda: os.path.exists(meta_path), timeout=4)  # the worker gets every chance to finish
            return real_write(p, obj)

        with mock.patch.object(batch.textio, "write_json_atomic", side_effect=slow_launcher_write):
            batch.launch_job(path)
        self.assertTrue(wait_until(lambda: batch.job_state(self.run_dir, job) == "done", timeout=40))
        self.assertTrue(wait_until(lambda: not os.path.exists(marker), timeout=10),
                        "a marker outlived its worker: %r" % read_marker(marker))
        self.assertEqual(len(self.ok_calls("r4")), 1)

    def test_a_held_lock_is_running_whatever_the_heartbeat_says(self):
        job, path = self.job("r5")
        gone = subprocess.Popen([sys.executable, "-c", "pass"])
        gone.wait()
        ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 30))
        textio.write_json_atomic(batch.marker_path(self.run_dir, "r5"), {"pid": gone.pid, "started_at": ts,
                                                                          "heartbeat_at": ts, "attempt": 1,
                                                                          "backend": "stub"})
        self.assertEqual(batch.job_state(self.run_dir, job), "dead")
        lock = batch.JobLock(self.run_dir, "r5")  # a worker whose heartbeat is late (sleep, heavy load)
        self.assertTrue(lock.try_acquire())
        try:
            if not lock.exclusive:
                self.skipTest("no file locks on this file system")
            self.assertEqual(batch.job_state(self.run_dir, job), "running")
            self.assertIn("r5", batch.running_jobs(self.run_dir))
            info = batch.launch_job(path)
            self.assertEqual((info.get("launched"), info.get("state")), (False, "running"))
        finally:
            lock.release()
        self.assertEqual(batch.job_state(self.run_dir, job), "dead")
        self.assertEqual(self.calls_log(), [])


    def test_a_worker_behind_a_wrapper_process_owns_its_launch_marker(self):
        """In a Windows venv, sys.executable is a redirector that runs the real interpreter as its child, so the pid
        launch_job records is not the worker's. A worker whose first lock try failed (its launcher, or any driver's
        lock probe, still held the lock) took its own launch marker for another worker's, exited without a call, and
        the job turned "dead" and was relaunched. The launch token makes the marker the worker's own."""
        job, path = self.job("r6")
        wrapper = os.path.join(self.tmp, "wrapper.py")
        with open(wrapper, "w") as f:
            f.write("import subprocess, sys\nsys.exit(subprocess.call([sys.executable] + sys.argv[1:]))\n")
        real_argv = batch.worker_argv
        with mock.patch.object(batch, "worker_argv", side_effect=lambda p: [sys.executable, wrapper] +
                               real_argv(p)[1:]):
            info = batch.launch_job(path)
        self.assertTrue(info.get("launched", True))
        probe = batch.JobLock(self.run_dir, "r6")  # e.g. another driver's lock probe while the worker starts
        self.assertTrue(probe.try_acquire())
        try:
            if not probe.exclusive:
                self.skipTest("no file locks on this file system")
            time.sleep(1.5)
        finally:
            probe.release()
        self.assertTrue(wait_until(lambda: batch.job_state(self.run_dir, job) == "done", timeout=40),
                        "state %s; log: %s" % (batch.job_state(self.run_dir, job), self.worker_log("r6")))
        self.assertNotIn("skipped", self.worker_log("r6"))
        self.assertEqual(len(self.ok_calls("r6")), 1)
        self.assertEqual(batch.relaunch_count(self.run_dir, job), 0)
        self.assertTrue(wait_until(lambda: not os.path.exists(batch.marker_path(self.run_dir, "r6")), timeout=10))

    def test_a_waiting_worker_does_not_repeat_a_job_another_worker_ran(self):
        """A worker that waited for the lock while another one ran the job (and failed) makes no second call."""
        job, path = self.job("r7")
        holder = batch.JobLock(self.run_dir, "r7")
        self.assertTrue(holder.try_acquire())
        try:
            if not holder.exclusive:
                self.skipTest("no file locks on this file system")
            waiter = subprocess.Popen([sys.executable, FAMILY_PY, "job", "--job", path], env=dict(os.environ),
                                      stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            time.sleep(1.5)  # the waiter has started and waits for the lock
            prompt = os.path.join(self.run_dir, job["prompt_file"])
            textio.write_json_atomic(self.out_path(job) + ".meta.json", {
                "schema": 1, "id": "r7", "status": "failed", "error_class": "timeout",
                "prompt_sha256": textio.sha256_file(prompt), "started": textio.now_iso()})
        finally:
            holder.release()
        out, err = waiter.communicate(timeout=60)
        self.assertEqual(waiter.returncode, 0, err)
        self.assertIn(b"skipped job=r7", out)
        self.assertEqual(self.calls_log(), [], "no second call for a job another worker ran")
        self.assertEqual(self.read_meta(job)["status"], "failed", "the other worker's result stands")

    def test_a_stale_worker_that_cannot_be_stopped_is_stuck(self):
        """launch_job used to answer "running" here, while job_state kept saying "dead": the driver waited forever."""
        job, path = self.job("r8")
        with mock.patch.object(batch, "_stop_stale_worker", return_value=False), \
                mock.patch.object(batch, "_stale_but_alive", return_value=False), \
                mock.patch.object(batch, "_marker_live", return_value=(True, False, {"pid": 4242})):
            info = batch.launch_job(path)
        self.assertEqual((info.get("launched"), info.get("state"), info.get("pid")), (False, "stuck", 4242))
        self.assertEqual(batch.relaunch_count(self.run_dir, job), 0)
        self.assertEqual(self.calls_log(), [])


# ---------------------------------------------------------------- 3. reads of files being replaced

@unittest.skipUnless(HAVE_STUBS, "ublib.stubs (B4) not present")
class ReadsDuringReplace(RaceBase):
    def test_a_finished_job_stays_done(self):
        job, _path = self.job("p1")
        self.write_done(job)
        with transient_permission_errors(".meta.json", times=1):
            self.assertEqual(batch.job_state(self.run_dir, job), "done")

    def test_stop_all_still_stops_the_worker(self):
        os.environ["UB_STUB_DELAY_S"] = "30"
        _job, path = self.job("p2")
        batch.launch_job(path)
        marker = batch.marker_path(self.run_dir, "p2")
        self.assertTrue(wait_until(lambda: read_marker(marker).get("backend") == "stub", timeout=20))
        pid = read_marker(marker)["pid"]
        with transient_permission_errors(".running.json", times=2):
            self.assertEqual(batch.stop_all(self.run_dir), 1)
        self.assertTrue(wait_until(lambda: not proc.pid_alive(pid), timeout=15))

    def test_textio_retries_only_transient_errors(self):
        p = os.path.join(self.tmp, "m.json")
        textio.write_json_atomic(p, {"pid": 1})
        with transient_permission_errors("m.json", times=3):
            self.assertEqual(textio.read_json(p), {"pid": 1})
            self.assertEqual(textio.sha256_file(p), textio.sha256_text(textio.read_text(p)))
        with self.assertRaises(FileNotFoundError):
            textio.read_json(os.path.join(self.tmp, "missing.json"))
        with mock.patch.object(textio, "READ_RETRY_S", 0.2), transient_permission_errors("m.json", times=10 ** 6):
            with self.assertRaises(PermissionError):
                textio.read_text(p)
        self.assertEqual(textio.read_json_or(os.path.join(self.tmp, "missing.json"), {}), {})
        t0 = time.monotonic()
        with mock.patch.object(textio, "RETRY_TRANSIENT_READS", True, create=True):
            with self.assertRaises(OSError):  # a folder (PermissionError on Windows) is final at once
                textio.read_text(self.tmp)
        self.assertLess(time.monotonic() - t0, 0.5)


if __name__ == "__main__":
    unittest.main()
