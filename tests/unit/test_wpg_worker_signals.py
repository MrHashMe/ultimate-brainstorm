"""WPG: crash evidence for a worker that ends by a signal (contract C5, the WP1b residual).

A worker ended by SIGTERM or SIGBREAK (SystemExit, family.py's graceful handler) or by Ctrl+C (KeyboardInterrupt), not
by a hard kill, used to leave nothing: its marker was deleted, no meta was written, the job read "pending" and every
relaunch escaped the relaunch count. It now leaves the same minimal failed meta as a worker that ends by an error, for
the prompt it ran (error_class "killed", whose BLOCKED card names hosts that stop background work), so the job reads
"failed" and its fallback runs. Nothing is recorded when the run is stopped (`ub stop`: the .ub/STOP
sentinel, or the worker's stop exit code 8), and never when the job's prompt changed or moved away while it ran (a
superseded job): a newer prompt is never marked, and the job reads "pending".

In-process WorkerMarker and `family.py job` tests, plus a driver-like poll loop over real worker processes (family.py
with the stub backend, interrupted after its model call). No model CLI and no network.
"""

import os
import signal
import sys
import unittest
from unittest import mock

_KIT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(_KIT, "tests", "fixtures", "adapter"))
sys.path.append(os.path.join(_KIT, "tests", "harness"))

import adapter_testlib as tl  # noqa: E402
import family  # noqa: E402
import procfix  # noqa: E402
from ublib import adapter, batch, textio  # noqa: E402

HAVE_STUBS = os.path.isfile(os.path.join(_KIT, "tests", "harness", "stubs.py"))
POLLS = 5

# `family.py job ...` whose adapter is interrupted (Ctrl+C) after the stub's model call, while it validates the output.
# argv: <scripts dir> job --job <job.json>
INTERRUPTED_WORKER = r'''
import runpy, sys
scripts = sys.argv[1]
sys.path.insert(0, scripts)
from ublib import adapter

def interrupted(*_a, **_k):
    raise KeyboardInterrupt

adapter._validate_and_write = interrupted
sys.argv = [scripts + "/family.py"] + sys.argv[2:]
runpy.run_path(sys.argv[0], run_name="__main__")
'''


class Base(tl.AdapterTestCase):
    def setUp(self):
        super(Base, self).setUp()
        os.environ["UB_FAKE_FAMILIES"] = "1"

    def job(self, job_id):
        job = self.make_job(job_id=job_id, family="claude")
        job["_path"] = self.write_job(job)
        return job

    def prompt_path(self, job):
        return os.path.join(self.run_dir, job["prompt_file"])

    def meta_path(self, job):
        return self.out_path(job) + ".meta.json"

    def end_by(self, job, exc, during=None):
        """Run the job's worker bookkeeping and end it with `exc` (after `during()`, the outside event)."""
        with self.assertRaises(type(exc)):
            with batch.WorkerMarker(self.run_dir, job["id"], job=job) as marker:
                self.assertIsNone(marker.skipped)
                if during:
                    during()
                raise exc

    def assert_failed_for_the_prompt_it_ran(self, job, exc_name):
        meta = self.read_meta(job)
        self.assertEqual((meta["id"], meta["status"], meta["error_class"], meta["prompt_sha256"]),
                         (job["id"], "failed", "killed", textio.sha256_file(self.prompt_path(job))))
        self.assertIn("stopped by a signal (%s)" % exc_name, meta["reason"])
        self.assertTrue(textio.read_text(self.out_path(job) + ".failed.md").startswith("FAMILY CALL FAILED:"))
        self.assertEqual(batch.job_state(self.run_dir, job), "failed")
        self.assertFalse(os.path.exists(batch.marker_path(self.run_dir, job["id"])))

    def assert_no_evidence(self, job):
        self.assertFalse(os.path.exists(self.meta_path(job)), "a stopped or superseded worker recorded an outcome")
        self.assertFalse(os.path.exists(batch.marker_path(self.run_dir, job["id"])))
        self.assertEqual(batch.job_state(self.run_dir, job), "pending")


class SignalExits(Base):
    def test_sigterm_leaves_a_failed_meta_for_the_prompt_it_ran(self):
        job = self.job("s1")
        self.end_by(job, SystemExit(143))
        self.assert_failed_for_the_prompt_it_ran(job, "SystemExit")

    def test_ctrl_c_leaves_a_failed_meta_for_the_prompt_it_ran(self):
        job = self.job("s2")
        self.end_by(job, KeyboardInterrupt())
        self.assert_failed_for_the_prompt_it_ran(job, "KeyboardInterrupt")

    def test_the_adapters_own_failed_meta_is_kept(self):
        job = self.job("s3")

        def adapter_failed():
            textio.write_json_atomic(self.meta_path(job), {
                "id": job["id"], "status": "failed", "error_class": "timeout", "started": textio.now_iso(),
                "prompt_sha256": textio.sha256_file(self.prompt_path(job)), "reason": "timed out"})
        self.end_by(job, SystemExit(143), during=adapter_failed)
        self.assertEqual(self.read_meta(job)["error_class"], "timeout")
        self.assertEqual(batch.job_state(self.run_dir, job), "failed")

    def test_a_stopped_run_records_nothing(self):
        """`ub stop` creates .ub/STOP before it stops the workers: the job reads pending, so continue relaunches it."""
        job = self.job("s4")
        stop = os.path.join(self.run_dir, ".ub", batch.STOP_FILE)
        self.end_by(job, SystemExit(143), during=lambda: textio.write_text_atomic(stop, ""))
        self.assert_no_evidence(job)

    def test_the_stop_exit_code_records_nothing(self):
        job = self.job("s5")
        self.assertEqual(family.EXIT_STOPPED, batch.EXIT_STOPPED)
        self.end_by(job, SystemExit(batch.EXIT_STOPPED))
        self.assert_no_evidence(job)

    def test_a_changed_prompt_is_never_marked(self):
        job = self.job("s6")
        self.end_by(job, SystemExit(143), during=lambda: textio.write_text_atomic(self.prompt_path(job), "newer\n"))
        self.assert_no_evidence(job)

    def test_a_moved_prompt_is_never_marked(self):
        job = self.job("s7")
        self.end_by(job, KeyboardInterrupt(), during=lambda: os.remove(self.prompt_path(job)))
        self.assertFalse(os.path.exists(self.meta_path(job)))
        self.assertFalse(os.path.exists(batch.marker_path(self.run_dir, job["id"])))


class WorkerCommand(Base):
    def test_family_job_records_the_interrupt_and_re_raises_it(self):
        job = self.job("w1")
        args = family.build_parser().parse_args(["job", "--job", job["_path"]])

        def interrupted(*_a, **_k):
            raise KeyboardInterrupt
        with mock.patch.object(family, "_graceful_signals"), mock.patch.object(family, "_preload"), \
                mock.patch.object(adapter, "execute_job", side_effect=interrupted):
            with self.assertRaises(KeyboardInterrupt):
                family.cmd_job(args)
        self.assert_failed_for_the_prompt_it_ran(job, "KeyboardInterrupt")


@unittest.skipUnless(HAVE_STUBS, "tests/harness/stubs.py not present")
class DriverLoop(Base):
    """What pipeline.dispatch does with a real batch: launch a pending (or dead) job, stop at done or failed. An
    interrupted worker used to read pending after every run, so every poll paid for another model call."""

    def setUp(self):
        super(DriverLoop, self).setUp()
        os.environ["UB_NO_DETACH"] = "1"
        script = os.path.join(self.tmp, "interrupted_worker.py")
        textio.write_text_atomic(script, INTERRUPTED_WORKER)
        real_argv = batch.worker_argv
        p = mock.patch.object(batch, "worker_argv",
                              side_effect=lambda path: [sys.executable, script, tl.SCRIPTS] + real_argv(path)[2:])
        p.start()
        self.addCleanup(p.stop)

    def test_an_interrupted_worker_costs_one_call_and_reads_failed(self):
        job = self.job("d1")
        state, launches = None, 0
        for _poll in range(POLLS):
            gen = batch.job_gen(self.run_dir, job["id"])
            state = batch.job_state(self.run_dir, job)
            if state not in ("pending", "dead"):
                break
            info = batch.launch_job(job["_path"], expect_gen=gen)
            launches += 1 if info.get("launched") else 0
        calls = [r for r in self.calls_log() if r.get("id") == job["id"]]
        self.assertEqual((state, launches, len(calls)), ("failed", 1, 1))
        self.assertIn("KeyboardInterrupt", self.read_meta(job)["reason"])


@unittest.skipUnless(HAVE_STUBS and os.name == "posix", "a real SIGTERM (POSIX) with the stub backend")
class RealSigterm(Base):
    """A detached worker in its model call gets SIGTERM (family.py turns it into SystemExit(143))."""

    def setUp(self):
        super(RealSigterm, self).setUp()
        os.environ.update({"UB_STUB_DELAY_S": "30", "UB_HEARTBEAT_STALE_S": "3"})
        self.addCleanup(batch.stop_all, self.run_dir)

    def terminate_in_call(self, job, before=None):
        batch.launch_job(job["_path"])
        mpath = batch.marker_path(self.run_dir, job["id"])
        self.assertTrue(procfix.wait_until(lambda: (textio.read_json_or(mpath, {}) or {}).get("backend") == "stub",
                                           timeout=30))
        pid = textio.read_json_or(mpath, {})["pid"]
        if before:
            before()
        os.kill(pid, signal.SIGTERM)
        self.assertTrue(procfix.wait_until(lambda: not os.path.exists(mpath), timeout=30), "the worker did not end")

    def test_sigterm_reads_failed(self):
        job = self.job("r1")
        self.terminate_in_call(job)
        self.assertEqual(batch.job_state(self.run_dir, job), "failed")
        self.assertIn("SystemExit", self.read_meta(job)["reason"])

    def test_sigterm_after_ub_stop_reads_pending(self):
        job = self.job("r2")
        stop = os.path.join(self.run_dir, ".ub", batch.STOP_FILE)
        self.terminate_in_call(job, before=lambda: textio.write_text_atomic(stop, ""))
        self.assertFalse(os.path.exists(self.meta_path(job)))
        self.assertEqual(batch.job_state(self.run_dir, job), "pending")


if __name__ == "__main__":
    unittest.main()
