"""H (NEW-G3-backends-2): no attempt is started that the job deadline leaves too little time for.

With 0.5 s of a 40 s job deadline left, the next backend used to be started with a 1 s timeout: the request was
wasted, and its timeout ended the job "timeout", hiding the earlier backend's real failure. An attempt whose timeout
the deadline clipped hid that failure the same way. Now an attempt starts only while at least
min(adapter.MIN_ATTEMPT_S, timeout_s / 4) is left, a retry is skipped when its back-off would leave less than that, and
a clipped attempt that times out reports the earlier failure with the deadline note.
The CLI is mocked at ublib.proc.run; the clock is a fake."""

import os
import sys
import unittest
from unittest import mock

_KIT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(_KIT, "tests", "fixtures", "adapter"))

import adapter_testlib as tl  # noqa: E402
from ublib import adapter, backends  # noqa: E402

NETWORK = "Error: connection reset by peer (ECONNRESET)"


class FakeClock(object):
    def __init__(self):
        self.t = 1000.0
        self.sleeps = []

    def now(self):
        return self.t

    def sleep(self, s):
        self.sleeps.append(s)
        self.t += s


class DeadlineTests(tl.AdapterTestCase):
    def setUp(self):
        super(DeadlineTests, self).setUp()
        self.clock = FakeClock()
        for name, fn in (("_clock", self.clock.now), ("_sleep", self.clock.sleep)):
            p = mock.patch.object(backends, name, side_effect=fn)
            p.start()
            self.addCleanup(p.stop)
        p = mock.patch.object(backends._rng, "uniform", return_value=1.0)  # every jittered back-off is 1 s
        p.start()
        self.addCleanup(p.stop)

    def failing_after(self, seconds):
        def respond(call):
            self.clock.t += seconds
            return tl.PR(1, "", NETWORK)
        return respond

    def times_out(self, call):
        self.clock.t += call["timeout_s"]
        return tl.PR(0, "", "", timed_out=True)

    def run_job(self, responses, chain, retries=1):
        job = self.make_job(family="gpt", retries=retries, timeout_s=20)  # job deadline 40 s, minimum attempt 5 s
        fake = tl.FakeRun(responses)
        with mock.patch("ublib.proc.run", side_effect=fake), \
                mock.patch("ublib.proc.resolve_exe", side_effect=tl.fake_resolve()):
            meta = adapter.execute_job(job, detect_result=tl.chain_detect({"gpt": list(chain)}, "claude"))
        return meta, fake

    def test_no_backend_is_started_with_a_doomed_budget(self):
        # codex fails after 17 s and, after a 1 s back-off, again after 18.5 s: 3.5 s are left for kimi-cli
        meta, fake = self.run_job([self.failing_after(17), self.failing_after(18.5), self.times_out],
                                  ["codex-cli", "kimi-cli"])
        self.assertEqual([c["timeout_s"] for c in fake.calls], [20, 20], "kimi-cli is never started")
        self.assertEqual((meta["status"], meta["error_class"], meta["backend"]), ("failed", "network", "codex-cli"))
        self.assertTrue(meta["reason"].startswith("codex exec exited 1"), meta["reason"])
        self.assertIn("ECONNRESET", meta["stderr_tail"])
        self.assertIn("less than 5s were left before the job deadline of 40s; no further attempt", meta["reason"])
        self.assertEqual(meta["requests"], 2)

    def test_a_clipped_attempt_that_times_out_reports_the_earlier_failure(self):
        # codex fails twice after 15 s (1 s back-off between): kimi-cli gets the 9 s left and times out
        meta, fake = self.run_job([self.failing_after(15), self.failing_after(15), self.times_out],
                                  ["codex-cli", "kimi-cli"])
        self.assertEqual([c["timeout_s"] for c in fake.calls], [20, 20, 9])
        self.assertEqual((meta["status"], meta["error_class"], meta["backend"]), ("failed", "network", "codex-cli"),
                         meta["reason"])
        self.assertTrue(meta["reason"].startswith("codex exec exited 1"), meta["reason"])
        self.assertIn("ECONNRESET", meta["stderr_tail"])
        self.assertIn("the job deadline of 40s passed; no further attempt", meta["reason"])
        self.assertEqual(meta["exit_code"], 1, "the meta describes the failure it reports")
        self.assertEqual(meta["requests"], 3)

    def test_a_retry_that_would_leave_too_little_time_is_not_made(self):
        # retries 2: fails after 18 s, 1 s back-off, fails after 17 s; 4 s are left, and a 1 s back-off would leave 3
        meta, fake = self.run_job([self.failing_after(18), self.failing_after(17)], ["codex-cli"], retries=2)
        self.assertEqual(len(fake.calls), 2)
        self.assertEqual(self.clock.sleeps, [1.0], "no back-off is slept for a retry that is not made")
        self.assertEqual((meta["status"], meta["error_class"]), ("failed", "network"))
        self.assertIn("a retry had to wait 1s, but only 4s were left before the job deadline of 40s, and an attempt "
                      "needs at least 5s", meta["reason"])

    def test_a_full_length_timeout_still_ends_the_job_timeout(self):
        # not clipped by the deadline: the backend itself is too slow, which is the failure to report
        meta, fake = self.run_job([self.failing_after(1), self.times_out], ["codex-cli", "kimi-cli"])
        self.assertEqual([c["timeout_s"] for c in fake.calls], [20, 20])
        self.assertEqual((meta["status"], meta["error_class"]), ("timeout", "timeout"))

    def test_no_repair_call_without_the_minimum_left(self):
        def too_short_answer(call):  # valid JSONL, but 2 characters fail the job's min_chars 5
            self.clock.t += 17
            argv = call["argv"]
            with open(argv[argv.index("-o") + 1], "w", encoding="utf-8") as f:
                f.write("ok")
            return tl.PR(0, "")
        meta, fake = self.run_job([self.failing_after(18), too_short_answer], ["codex-cli"])
        self.assertEqual(len(fake.calls), 2, "4 s are left: no repair call")
        self.assertEqual((meta["status"], meta["error_class"]), ("invalid", "bad_output"))
        self.assertIn("the job deadline left no time for the repair call", meta["reason"])

    def test_the_minimum_is_a_quarter_of_short_timeouts_and_capped(self):
        self.assertEqual(adapter.min_attempt_s(20), 5.0)
        self.assertEqual(adapter.min_attempt_s(420), adapter.MIN_ATTEMPT_S)


if __name__ == "__main__":
    unittest.main()
