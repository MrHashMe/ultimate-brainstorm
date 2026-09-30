"""WP2a: worker processes and their bookkeeping (KIT_SPEC 4.7).

- process identity: a marker's pid is killed only while it has the recorded identity (never a reused pid);
- where file locks work, the lock alone decides whether a worker still runs;
- the stop sentinel (.ub/STOP): launch_job launches nothing, a worker exits 8 before any call;
- crash evidence: a worker that ends without an outcome leaves a failed meta, or else a dead marker (not when stopped);
- the outcome generation: a run that finished after the driver read the job's state is not repeated;
- the backend process of a hard-killed worker is stopped by stop_all and before a relaunch;
- the done rule compares the recorded out_sha256 instead of re-validating on every poll.

Real worker processes run family.py with the stub backend (UB_FAKE_FAMILIES=1). No model CLI and no network.
"""

import os
import shutil
import signal
import subprocess
import sys
import time
import unittest
from unittest import mock

_KIT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(_KIT, "tests", "fixtures", "adapter"))
sys.path.append(os.path.join(_KIT, "tests", "harness"))

import adapter_testlib as tl  # noqa: E402
import procfix  # noqa: E402
from ublib import batch, proc, textio  # noqa: E402

HAVE_STUBS = os.path.isfile(os.path.join(_KIT, "tests", "harness", "stubs.py"))  # the fake-mode responder

FAMILY_PY = os.path.join(tl.SCRIPTS, "family.py")
TEXT = {"type": "text", "min_chars": 5}
wait_until = procfix.wait_until

# A worker stand-in that holds a job's marker (and lock) while proc.run waits for a CLI that ignores SIGTERM.
# argv: <scripts> <run dir> <job id> <cli pid file> <finally file>
MINI_WORKER = r'''
import signal, sys
scripts, run_dir, job_id, pidfile, finfile = sys.argv[1:6]
sys.path.insert(0, scripts)
from ublib import batch, proc
signal.signal(signal.SIGTERM, lambda *_a: sys.exit(143))
CLI = ("import os, signal, sys, time\n"
       "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
       "open(sys.argv[1], 'w').write(str(os.getpid()))\n"
       "time.sleep(120)\n")
try:
    with batch.WorkerMarker(run_dir, job_id):
        proc.run([sys.executable, "-c", CLI, pidfile], timeout_s=300)
finally:
    open(finfile, "w").write("finally")
'''


def iso(age_s=0.0):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - age_s))


def read_marker(path):
    data = textio.read_json_or(path, {})
    return data if isinstance(data, dict) else {}


def read_int(path):
    try:
        with open(path) as f:
            return int(f.read().strip())
    except (OSError, ValueError):
        return None


def file_locks_work(run_dir):
    lk = batch.JobLock(run_dir, "probe-locks")
    try:
        return lk.try_acquire() and lk.exclusive
    finally:
        lk.release()


class Base(tl.AdapterTestCase):
    def setUp(self):
        super(Base, self).setUp()
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

    def bystander(self):
        """An unrelated live process (it stands in for whatever now owns a dead worker's pid)."""
        p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
        self.addCleanup(p.wait)
        self.addCleanup(p.kill)
        return p

    def gone_pid(self):
        p = subprocess.Popen([sys.executable, "-c", "pass"])
        p.wait()
        return p.pid

    def marker(self, job_id, **fields):
        m = {"pid": fields.pop("pid", os.getpid()), "started_at": iso(), "heartbeat_at": iso(), "attempt": 1,
             "backend": "stub"}
        m.update(fields)
        textio.write_json_atomic(batch.marker_path(self.run_dir, job_id), m)
        return m

    def worker(self, path, instrumented=False, **env):
        """Run `family.py job` to its end (under procfix's instrumentation when asked)."""
        argv = procfix.argv("job", "--job", path) if instrumented else [sys.executable, FAMILY_PY, "job", "--job", path]
        return subprocess.run(argv, env=dict(os.environ, **env), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              timeout=120)

    def require_locks(self):
        if not file_locks_work(self.run_dir):
            self.skipTest("no file locks on this file system")


# ---------------------------------------------------------------- 1. process identity (pid reuse)

class ProcessIdentity(Base):
    def test_stop_all_never_kills_a_reused_pid(self):
        other = self.bystander()
        self.marker("i1", pid=other.pid, ident="win:1", locked=True)  # a fresh heartbeat, but another process
        # a 2.0.3 marker (no identity) whose worker started 60 s before the process that has the pid now: 2.0.3's
        # own rule (started at most 5 s after started_at) says reused, so it is never killed either
        self.marker("i2", pid=other.pid, started_at=iso(60))
        self.assertEqual(batch.stop_all(self.run_dir), 0)
        self.assertTrue(proc.pid_alive(other.pid), "stop_all killed an unrelated process that reused a pid")
        self.assertFalse(os.path.exists(batch.marker_path(self.run_dir, "i1")))

    @unittest.skipUnless(HAVE_STUBS, "tests/harness/stubs.py not present")
    def test_a_relaunch_never_kills_a_reused_pid(self):
        other = self.bystander()
        job, path = self.job("i3")
        # the dead worker's marker names a pid a new process took 1 s after the worker started
        self.marker("i3", pid=other.pid, ident="win:1", started_at=iso(1), heartbeat_at=iso(130))
        self.assertEqual(batch.job_state(self.run_dir, job), "dead")
        os.environ["UB_NO_DETACH"] = "1"
        info = batch.launch_job(path)
        self.assertEqual((info.get("launched"), info.get("relaunches")), (True, 1))
        self.assertTrue(proc.pid_alive(other.pid), "the relaunch killed an unrelated process that reused a pid")
        self.assertEqual(batch.job_state(self.run_dir, job), "done")

    @unittest.skipUnless(HAVE_STUBS, "tests/harness/stubs.py not present")
    def test_the_worker_marker_records_its_identity_and_its_lock(self):
        os.environ["UB_STUB_DELAY_S"] = "3"
        job, path = self.job("i4")
        batch.launch_job(path)
        mpath = batch.marker_path(self.run_dir, "i4")
        self.assertTrue(wait_until(lambda: read_marker(mpath).get("backend") == "stub", timeout=30))
        m = read_marker(mpath)
        self.assertTrue(proc.same_process(m["pid"], m.get("ident")), m)
        self.assertEqual(bool(m.get("locked")), file_locks_work(self.run_dir))
        self.assertTrue(wait_until(lambda: batch.job_state(self.run_dir, job) == "done", timeout=40))


# ---------------------------------------------------------------- 2. the lock alone decides where locks work

class LockDecides(Base):
    def test_a_free_lock_means_a_locked_marker_is_dead(self):
        self.require_locks()
        job, _path = self.job("l1")
        # the pid runs and the heartbeat is fresh, but the worker that wrote the marker held the lock: it is gone
        self.marker("l1", locked=True)
        self.assertEqual(batch.job_state(self.run_dir, job), "dead")
        self.assertNotIn("l1", batch.running_jobs(self.run_dir))
        lock = batch.JobLock(self.run_dir, "l1")
        self.assertTrue(lock.try_acquire())
        try:
            self.assertEqual(batch.job_state(self.run_dir, job), "running")
        finally:
            lock.release()

    def test_a_launch_marker_stands_while_its_process_runs(self):
        job, _path = self.job("l2")
        other = self.bystander()
        self.marker("l2", pid=other.pid, heartbeat_at=iso(-3600))  # a heartbeat from the future proves nothing
        self.assertEqual(batch.job_state(self.run_dir, job), "dead")
        self.marker("l2", pid=other.pid, ident="win:1")  # the pid now belongs to another process
        self.assertEqual(batch.job_state(self.run_dir, job), "dead")
        ident = proc.process_identity(other.pid)
        self.marker("l2", pid=other.pid, ident=ident, heartbeat_at=iso(4))  # the worker has not taken the lock yet
        self.assertEqual(batch.job_state(self.run_dir, job), "running")
        self.marker("l2", pid=other.pid, ident=ident, heartbeat_at=iso(30))  # never took the lock (2 x 3 s)
        self.assertEqual(batch.job_state(self.run_dir, job), "dead")

    def test_without_file_locks_the_heartbeat_decides(self):
        job, _path = self.job("l3")
        with mock.patch.object(batch, "lock_state", return_value=None):
            self.marker("l3", locked=True)
            self.assertEqual(batch.job_state(self.run_dir, job), "running")
            self.assertEqual(batch.running_jobs(self.run_dir), ["l3"])
            self.marker("l3", locked=True, heartbeat_at=iso(30))
            self.assertEqual(batch.job_state(self.run_dir, job), "dead")

    def test_reserved_ids_are_never_enumerated(self):
        self.marker("_driver")
        self.assertEqual(batch.running_jobs(self.run_dir), [])
        self.assertEqual(batch.stop_all(self.run_dir), 0)
        self.assertTrue(os.path.exists(batch.marker_path(self.run_dir, "_driver")))


# ---------------------------------------------------------------- 3. the stop sentinel

@unittest.skipUnless(HAVE_STUBS, "tests/harness/stubs.py not present")
class StopSentinel(Base):
    def stop(self):
        path = os.path.join(self.run_dir, ".ub", "STOP")  # what `ub stop` creates (batch.STOP_FILE)
        textio.write_text_atomic(path, "")
        return path

    def test_launch_job_launches_nothing_while_stopped(self):
        job, path = self.job("t1")
        stop = self.stop()
        info = batch.launch_job(path)
        self.assertEqual((info.get("launched"), info.get("refused"), info.get("pid")), (False, "stopped", None))
        self.assertTrue(batch.stop_requested(self.run_dir))
        self.assertEqual(os.path.basename(stop), batch.STOP_FILE)
        self.assertFalse(os.path.exists(batch.marker_path(self.run_dir, "t1")))
        self.assertFalse(os.path.exists(os.path.join(self.run_dir, "logs", "t1.log")), "no worker started")
        os.remove(stop)
        os.environ["UB_NO_DETACH"] = "1"
        self.assertEqual(batch.launch_job(path).get("exit_code"), 0)
        self.assertEqual(batch.job_state(self.run_dir, job), "done")

    def test_a_worker_exits_8_before_any_call_while_stopped(self):
        job, path = self.job("t2")
        self.stop()
        cp = self.worker(path)
        self.assertEqual(cp.returncode, 8, cp.stderr)
        self.assertIn(b"skipped job=t2", cp.stdout)
        self.assertEqual(self.calls_log(), [])
        self.assertFalse(os.path.exists(self.out_path(job) + ".meta.json"), "no meta")
        self.assertFalse(os.path.exists(batch.marker_path(self.run_dir, "t2")))
        self.assertEqual(batch.job_state(self.run_dir, job), "pending")

    def test_run_foreground_starts_nothing_while_stopped(self):
        job, _path = self.job("t3")
        self.stop()
        res = batch.run_foreground([job])
        self.assertEqual((res["done"], res["failed"], res["pending"]), ([], [], ["t3"]))
        self.assertEqual(self.calls_log(), [])


# ---------------------------------------------------------------- 4. crash evidence

@unittest.skipUnless(HAVE_STUBS, "tests/harness/stubs.py not present")
class CrashEvidence(Base):
    def prompt_sha(self, job):
        return textio.sha256_file(os.path.join(self.run_dir, job["prompt_file"]))

    def test_a_crash_after_the_call_reads_failed(self):
        job, path = self.job("c1")
        cp = self.worker(path, True, UB_TEST_INJECT="crash")
        self.assertNotEqual(cp.returncode, 0)
        self.assertEqual(len(self.calls_log()), 1)
        self.assertEqual(batch.job_state(self.run_dir, job), "failed", "a recorded crash must never read as pending")
        self.assertEqual(self.read_meta(job)["prompt_sha256"], self.prompt_sha(job))
        self.assertFalse(os.path.exists(batch.marker_path(self.run_dir, "c1")))

    def test_a_crash_that_left_no_meta_reads_failed(self):
        job, path = self.job("c2")
        cp = self.worker(path, True, UB_TEST_INJECT="crash-nometa")
        self.assertNotEqual(cp.returncode, 0)
        self.assertTrue(os.path.exists(self.out_path(job) + ".meta.json"), "the worker left no evidence")
        meta = self.read_meta(job)
        self.assertEqual((meta["status"], meta["error_class"], meta["prompt_sha256"]),
                         ("failed", "internal", self.prompt_sha(job)))
        self.assertIn("RuntimeError", meta["reason"])
        self.assertTrue(textio.read_text(self.out_path(job) + ".failed.md").startswith("FAMILY CALL FAILED:"))
        self.assertEqual(batch.job_state(self.run_dir, job), "failed")

    def test_no_meta_at_all_leaves_a_dead_marker_and_every_relaunch_counts(self):
        """A full disk: neither the adapter nor the worker can write a meta. The marker stays, the job reads dead,
        and each relaunch is counted, so the driver's relaunch limit ends the loop."""
        job, path = self.job("c3")
        os.environ.update({"UB_NO_DETACH": "1", procfix.INJECT_ENV: "enospc"})
        real_argv = batch.worker_argv
        with mock.patch.object(batch, "worker_argv", side_effect=lambda p: procfix.argv(*real_argv(p)[2:])):
            self.assertEqual(batch.launch_job(path).get("relaunches"), 0)
            for n in range(1, batch.RELAUNCH_LIMIT + 1):
                self.assertEqual(batch.job_state(self.run_dir, job), "dead")
                self.assertEqual(batch.launch_job(path).get("relaunches"), n)
        self.assertEqual(batch.relaunch_count(self.run_dir, job), batch.RELAUNCH_LIMIT)
        self.assertEqual(len(self.calls_log()), batch.RELAUNCH_LIMIT + 1)

    def test_a_worker_stopped_by_ub_stop_leaves_no_evidence(self):
        """`ub stop` creates .ub/STOP, then stops the workers. (A signal outside a stop leaves a failed meta: WPG.)"""
        job, _path = self.job("c4")
        with self.assertRaises(SystemExit):
            with batch.WorkerMarker(self.run_dir, "c4", job=job):
                textio.write_text_atomic(os.path.join(self.run_dir, ".ub", batch.STOP_FILE), "")
                sys.exit(143)
        self.assertFalse(os.path.exists(self.out_path(job) + ".meta.json"))
        self.assertFalse(os.path.exists(batch.marker_path(self.run_dir, "c4")))
        self.assertEqual(batch.job_state(self.run_dir, job), "pending")


# ---------------------------------------------------------------- 5. the outcome generation (launch/fail TOCTOU)

@unittest.skipUnless(HAVE_STUBS, "tests/harness/stubs.py not present")
class OutcomeGeneration(Base):
    def test_a_run_that_finished_after_the_state_was_read_is_not_repeated(self):
        job, path = self.job("g1")
        gen = batch.job_gen(self.run_dir, "g1")  # the driver reads the generation, then the state
        self.assertEqual(batch.job_state(self.run_dir, job), "pending")
        cp = self.worker(path, UB_STUB_FAIL="^g1$")  # meanwhile another launcher runs the job, and it fails
        self.assertEqual(cp.returncode, 4, cp.stderr)
        self.assertEqual(batch.job_gen(self.run_dir, "g1"), gen + 1)
        calls = len(self.calls_log())
        info = batch.launch_job(path, expect_gen=gen)
        self.assertEqual((info.get("launched"), info.get("state")), (False, "failed"))
        # the failed meta moves away (a fallback copy takes the job over): the generation still tells
        meta = self.out_path(job) + ".meta.json"
        shutil.move(meta, meta + ".superseded")
        self.assertEqual(batch.job_state(self.run_dir, job), "pending")
        info = batch.launch_job(path, expect_gen=gen)
        self.assertEqual((info.get("launched"), info.get("state")), (False, "pending"))
        self.assertEqual(len(self.calls_log()), calls, "no second run for a prompt whose run already ended")
        os.environ["UB_NO_DETACH"] = "1"  # a fresh read of the generation launches it
        info = batch.launch_job(path, expect_gen=batch.job_gen(self.run_dir, "g1"))
        self.assertEqual((info.get("launched"), info.get("exit_code")), (True, 0))

    def test_a_worker_launched_before_another_run_ended_makes_no_call(self):
        job, path = self.job("g2")
        batch._bump_gen(self.run_dir, "g2")  # a run ended after this worker was launched (at generation 0)
        cp = self.worker(path, UB_EXPECT_GEN="0")
        self.assertEqual(cp.returncode, 0, cp.stderr)
        self.assertIn(b"skipped job=g2", cp.stdout)
        self.assertEqual(self.calls_log(), [])
        cp = self.worker(path, UB_EXPECT_GEN="1")
        self.assertEqual(cp.returncode, 0, cp.stderr)
        self.assertEqual(batch.job_state(self.run_dir, job), "done")
        self.assertEqual(batch.job_gen(self.run_dir, "g2"), 2, "every finished run counts")


# ---------------------------------------------------------------- 6. the backend process of a killed worker

class OrphanedBackend(Base):
    def start_mini_worker(self, job_id):
        pidfile, fin = os.path.join(self.tmp, job_id + ".cli"), os.path.join(self.tmp, job_id + ".fin")
        w = subprocess.Popen([sys.executable, "-c", MINI_WORKER, tl.SCRIPTS, self.run_dir, job_id, pidfile, fin])
        self.addCleanup(w.wait)
        self.assertTrue(wait_until(lambda: read_int(pidfile), timeout=60), "the CLI never started")
        cli = read_int(pidfile)
        self.addCleanup(proc.kill_tree, cli, 0.5)
        # the worker records its backend process as soon as proc.run has started it
        mpath = batch.marker_path(self.run_dir, job_id)
        wait_until(lambda: (read_marker(mpath).get("child") or {}).get("pid") == cli, timeout=5)
        return w, cli, fin

    def test_stop_all_stops_the_backend_process_of_a_hard_killed_worker(self):
        w, cli, _fin = self.start_mini_worker("o1")
        if proc.IS_WINDOWS:
            w.kill()  # TerminateProcess: no handler, no finally
        else:
            os.kill(w.pid, signal.SIGKILL)
        w.wait()
        batch.stop_all(self.run_dir)
        self.assertTrue(wait_until(lambda: not proc.pid_alive(cli), timeout=15), "the orphaned CLI kept running")

    @unittest.skipIf(proc.IS_WINDOWS, "Windows: taskkill /F runs no handler; the tree dies at once")
    def test_stop_all_lets_the_worker_stop_its_backend_process_first(self):
        _w, cli, fin = self.start_mini_worker("o2")
        t0 = time.monotonic()
        n = batch.stop_all(self.run_dir)
        elapsed = time.monotonic() - t0
        self.assertTrue(os.path.exists(fin), "the worker was killed before its own cleanup ran")
        self.assertFalse(proc.pid_alive(cli))
        self.assertEqual(n, 1)
        self.assertLess(elapsed, batch.STOP_GRACE_S, "the worker stopped its CLI within its own, shorter grace")

    @unittest.skipUnless(HAVE_STUBS, "tests/harness/stubs.py not present")
    def test_a_relaunch_stops_the_backend_process_of_the_dead_worker(self):
        job, path = self.job("o3")
        cli = self.bystander()  # stands in for the CLI a hard-killed worker left behind
        self.marker("o3", pid=self.gone_pid(), ident="gone", locked=True, heartbeat_at=iso(30),
                    child={"pid": cli.pid, "ident": proc.process_identity(cli.pid)})
        self.assertEqual(batch.job_state(self.run_dir, job), "dead")
        os.environ["UB_NO_DETACH"] = "1"
        info = batch.launch_job(path)
        self.assertEqual((info.get("launched"), info.get("relaunches")), (True, 1))
        self.assertTrue(wait_until(lambda: not proc.pid_alive(cli.pid), timeout=10), "the old call kept running")
        self.assertEqual(batch.job_state(self.run_dir, job), "done")


# ---------------------------------------------------------------- 7. the done rule and the relaunch counter

class DoneRule(Base):
    def write(self, job, text, **meta):
        out = self.out_path(job)
        textio.write_text_atomic(out, text)
        rec = {"schema": 1, "id": job["id"], "status": "ok",
               "prompt_sha256": textio.sha256_file(os.path.join(self.run_dir, job["prompt_file"]))}
        rec.update(meta)
        textio.write_json_atomic(out + ".meta.json", rec)
        return out

    def test_done_compares_the_recorded_output_hash(self):
        job, _path = self.job("d1", contract={"type": "text", "regex": "MUST-APPEAR"})
        out = self.write(job, "An answer that the adapter validated when it wrote it.")
        textio.write_json_atomic(out + ".meta.json", dict(textio.read_json(out + ".meta.json"),
                                                          out_sha256=textio.sha256_file(out)))
        with mock.patch.object(batch.validate, "check_contract", side_effect=AssertionError("re-validated")):
            self.assertTrue(batch.is_done(self.run_dir, job))
            self.assertEqual(batch.job_state(self.run_dir, job), "done")
            textio.write_text_atomic(out, "Changed after the meta was written.")
            self.assertFalse(batch.is_done(self.run_dir, job))

    def test_a_meta_without_the_output_hash_is_validated(self):
        job, _path = self.job("d2", contract={"type": "text", "regex": "MUST-APPEAR"})
        self.write(job, "No marker text here.")
        self.assertFalse(batch.is_done(self.run_dir, job))
        self.write(job, "It has MUST-APPEAR in it.")
        self.assertTrue(batch.is_done(self.run_dir, job))

    def test_a_meta_of_another_job_is_not_done(self):
        job, _path = self.job("d3")
        out = self.write(job, "A valid answer text.", id="d3~gpt")
        textio.write_json_atomic(out + ".meta.json", dict(textio.read_json(out + ".meta.json"),
                                                          out_sha256=textio.sha256_file(out)))
        self.assertFalse(batch.is_done(self.run_dir, job))

    def test_reset_relaunch(self):
        job, _path = self.job("d4")
        batch._note_relaunch(self.run_dir, job)
        self.assertEqual(batch.relaunch_count(self.run_dir, job), 1)
        batch.reset_relaunch(self.run_dir, "d4")
        self.assertEqual(batch.relaunch_count(self.run_dir, job), 0)
        batch.reset_relaunch(self.run_dir, "d4")  # nothing to forget: quiet


if __name__ == "__main__":
    unittest.main()
