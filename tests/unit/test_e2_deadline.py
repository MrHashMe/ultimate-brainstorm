"""E2: a back-off longer than the time left skips the retry, not the rest of the chain (reviewer note P3-backends-0).

A server's Retry-After of 60 s on the first backend of a job with a 40 s deadline used to end the whole job at once
("the job deadline of 40s passed"), although the deadline had not passed and switching to the next backend needs no
wait. Now the next backend is tried, and the reason names the wait when no backend is left.
Local 127.0.0.1 HTTP stub only; the back-off clock is a fake; the CLI is mocked at ublib.proc.run."""

import json
import os
import sys
import unittest
from unittest import mock

_KIT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(_KIT, "tests", "fixtures", "adapter"))
sys.path.insert(0, os.path.join(_KIT, "tests", "harness"))

import adapter_testlib as tl  # noqa: E402
from http_stub import HttpStub  # noqa: E402
from ublib import adapter, backends  # noqa: E402

KEY = "sk-local-test-key-0123456789abcdef"
CODEX_OK = "\n".join(json.dumps(e) for e in (
    {"type": "item.completed", "item": {"type": "agent_message", "text": "A fine sentence about PONG."}},
    {"type": "turn.completed", "usage": {"input_tokens": 5, "output_tokens": 7}})) + "\n"


class FakeClock(object):
    def __init__(self):
        self.t = 1000.0
        self.sleeps = []

    def now(self):
        return self.t

    def sleep(self, s):
        self.sleeps.append(s)
        self.t += s


class DeadlineFallbackTests(tl.AdapterTestCase):
    def setUp(self):
        super(DeadlineFallbackTests, self).setUp()
        os.environ["NO_PROXY"] = os.environ["no_proxy"] = "127.0.0.1,localhost"
        os.environ["OPENAI_API_KEY"] = KEY
        self.clock = FakeClock()
        for name, fn in (("_clock", self.clock.now), ("_sleep", self.clock.sleep)):
            p = mock.patch.object(backends, name, side_effect=fn)
            p.start()
            self.addCleanup(p.stop)

    def run_chain(self, chain):
        with HttpStub([{"status": 429, "headers": {"Retry-After": "60"}}] * 50) as hs:
            self.write_families_override({"backends": {"openai-http": {"url": hs.url(), "model": "m",
                                                                        "enabled": True}}})
            job = self.make_job(family="gpt", retries=1, timeout_s=20)  # job deadline 40 s
            fake = tl.FakeRun([tl.PR(0, CODEX_OK)])
            with mock.patch("ublib.proc.run", side_effect=fake), \
                    mock.patch("ublib.proc.resolve_exe", side_effect=tl.fake_resolve()):
                meta = adapter.execute_job(job, detect_result=tl.chain_detect({"gpt": list(chain)}, "claude"))
        return meta, fake

    def test_the_next_backend_is_tried_without_waiting(self):
        meta, fake = self.run_chain(["openai-http", "codex-cli"])
        self.assertEqual(len(fake.calls), 1, "codex-cli (the next backend) was never tried")
        self.assertEqual((meta["status"], meta["backend"]), ("ok", "codex-cli"), meta.get("reason"))
        self.assertLess(self.clock.t - 1000.0, 40.0, "within the job deadline")
        self.assertNotIn(60.0, self.clock.sleeps, "the 60 s back-off was never slept")

    def test_the_reason_names_the_wait_when_no_backend_is_left(self):
        meta, _fake = self.run_chain(["openai-http"])
        self.assertEqual((meta["status"], meta["error_class"]), ("failed", "rate_limit"))
        self.assertIn("a retry had to wait", meta["reason"])
        self.assertIn("job deadline of 40s", meta["reason"])
        self.assertNotIn("passed", meta["reason"], "the deadline had not passed")


if __name__ == "__main__":
    unittest.main()
