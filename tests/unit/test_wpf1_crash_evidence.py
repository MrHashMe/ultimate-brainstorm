"""WPF1: crash evidence end to end (finding 3, contract C5) through a driver-like poll loop.

The loop does what pipeline.dispatch does with a real batch: read the job's outcome generation, then its state; launch
it (attached) when it is pending or dead, but a dead job only while its relaunch count for this prompt is below
batch.RELAUNCH_LIMIT; stop at done or failed. With both halves of C5 (adapter.crash_meta stamps the prompt hash, the
worker writes a failed meta itself or keeps its marker), a worker that crashes after its model call costs one call
and reads failed; one that cannot write any meta costs at most RELAUNCH_LIMIT + 1 calls and then blocks. Without them
the job read pending after every crash and was called again on every poll.

Real worker processes (family.py under tests/harness/procfix.py) with the stub backend. No model CLI, no network.
"""

import os
import sys
import unittest
from unittest import mock

_KIT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(_KIT, "tests", "fixtures", "adapter"))
sys.path.append(os.path.join(_KIT, "tests", "harness"))

import adapter_testlib as tl  # noqa: E402
import procfix  # noqa: E402
from ublib import batch  # noqa: E402

HAVE_STUBS = os.path.isfile(os.path.join(tl.KIT, "tests", "harness", "stubs.py"))
POLLS = 8


@unittest.skipUnless(HAVE_STUBS, "tests/harness/stubs.py not present")
class DriverLoopTests(tl.AdapterTestCase):
    def setUp(self):
        super(DriverLoopTests, self).setUp()
        os.environ.update({"UB_FAKE_FAMILIES": "1", "UB_NO_DETACH": "1", "UB_HEARTBEAT_STALE_S": "3"})
        real_argv = batch.worker_argv
        p = mock.patch.object(batch, "worker_argv", side_effect=lambda path: procfix.argv(*real_argv(path)[2:]))
        p.start()
        self.addCleanup(p.stop)

    def drive(self, inject):
        """Poll like the dispatcher until the job settles; returns (final state, launches, model calls)."""
        os.environ[procfix.INJECT_ENV] = inject
        job = self.make_job(family="claude", job_id="c-" + inject, contract={"type": "text", "min_chars": 5})
        path = self.write_job(job)
        state, launches = None, 0
        for _poll in range(POLLS):
            gen = batch.job_gen(self.run_dir, job["id"])
            state = batch.job_state(self.run_dir, job)
            if state == "dead" and batch.relaunch_count(self.run_dir, job) >= batch.RELAUNCH_LIMIT:
                state = "blocked"  # pipeline.dispatch: the BLOCKED card after RELAUNCH_LIMIT relaunches
            if state not in ("pending", "dead"):
                break
            info = batch.launch_job(path, expect_gen=gen)
            launches += 1 if info.get("launched") else 0
        return state, launches, len([r for r in self.calls_log() if r.get("id") == job["id"]])

    def test_a_recorded_crash_reads_failed_after_one_call(self):
        self.assertEqual(self.drive("crash"), ("failed", 1, 1))

    def test_a_crash_without_any_meta_from_the_adapter_reads_failed(self):
        self.assertEqual(self.drive("crash-nometa"), ("failed", 1, 1))

    def test_a_full_disk_ends_at_the_relaunch_limit(self):
        limit = batch.RELAUNCH_LIMIT
        self.assertEqual(self.drive("enospc"), ("blocked", limit + 1, limit + 1))


if __name__ == "__main__":
    unittest.main()
