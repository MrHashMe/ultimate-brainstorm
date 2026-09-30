"""WP2b: retries, back-off, job deadline and request accounting (findings 24, 25; contract C6).

Adapter retries used to fire with no delay, HTTP-internal retries were never logged, there was no deadline across
attempts, defaults.retries 0 became 1, and the HTTP backends ignored stop_reason / finish_reason and read responses
with neither a size cap nor a deadline. Local 127.0.0.1 servers only; the back-off clock is a fake."""

import json
import os
import socket
import sys
import threading
import time
import unittest
from unittest import mock

try:
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
except ImportError:  # pragma: no cover
    from http.server import BaseHTTPRequestHandler, HTTPServer as ThreadingHTTPServer

_KIT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(_KIT, "tests", "fixtures", "adapter"))
sys.path.insert(0, os.path.join(_KIT, "tests", "harness"))

import adapter_testlib as tl  # noqa: E402
from http_stub import HttpStub, anthropic_body, openai_body  # noqa: E402
from ublib import adapter, backends, families, textio  # noqa: E402
from ublib.backends import http_openai  # noqa: E402

KEY = "sk-local-test-key-0123456789abcdef"


class FakeClock(object):
    """backends.now() / backends.pause(): sleeping advances the clock, nothing really waits."""

    def __init__(self):
        self.t = 1000.0
        self.sleeps = []

    def now(self):
        return self.t

    def sleep(self, s):
        self.sleeps.append(s)
        self.t += s


class Base(tl.AdapterTestCase):
    def setUp(self):
        super(Base, self).setUp()
        os.environ["NO_PROXY"] = os.environ["no_proxy"] = "127.0.0.1,localhost"
        os.environ["OPENAI_API_KEY"] = os.environ["ANTHROPIC_API_KEY"] = KEY
        self.clock = FakeClock()
        for name, fn in (("_clock", self.clock.now), ("_sleep", self.clock.sleep)):
            p = mock.patch.object(backends, name, side_effect=fn)
            p.start()
            self.addCleanup(p.stop)

    def configure(self, backend, url, **extra):
        cfg = {"url": url, "model": "test-model", "enabled": True}
        cfg.update(extra)
        self.write_families_override({"backends": {backend: cfg}})

    def run_chain(self, job, chain, family="gpt", responses=None):
        det = tl.chain_detect({family: list(chain)}, host_family="claude")
        fake = tl.FakeRun(responses or [tl.PR(1, b"", b"unused")])
        with mock.patch("ublib.proc.run", side_effect=fake), \
                mock.patch("ublib.proc.resolve_exe", side_effect=tl.fake_resolve()):
            return adapter.execute_job(job, detect_result=det), fake


class VendorPartitionTests(Base):
    """REPORT 6.2 'vendor partition': an HTTP stub that answers 529 forever."""

    def test_529_forever_rows_equal_requests_and_backoff_is_bounded(self):
        with HttpStub([{"status": 529}] * 50) as hs:
            self.configure("openai-http", hs.url())
            job = self.make_job(family="gpt", retries=1, timeout_s=60)
            meta, _f = self.run_chain(job, ["openai-http"])
        self.assertEqual((meta["status"], meta["error_class"]), ("failed", "rate_limit"))
        rows = self.calls_log()
        self.assertEqual(len(rows), 2, "one calls.jsonl row per attempt")
        self.assertEqual([r["requests"] for r in rows], [3, 3], "HTTP-internal retries are counted")
        self.assertEqual(sum(r["requests"] for r in rows), len(hs.requests))
        self.assertEqual(meta["requests"], len(hs.requests))
        self.assertLessEqual(len(hs.requests), adapter.request_reserve(job))
        # 2 internal back-offs, 1 adapter back-off, 2 internal back-offs; retry n waits U(0, min(60, 2^(n+1)))
        bounds = [2, 4, 2, 2, 4]
        self.assertEqual(len(self.clock.sleeps), len(bounds), self.clock.sleeps)
        for s, b in zip(self.clock.sleeps, bounds):
            self.assertTrue(0 <= s <= b, (s, b))
        self.assertLessEqual(self.clock.t - 1000.0, adapter.JOB_DEADLINE_FACTOR * 60)

    def test_job_deadline_stops_further_attempts(self):
        with HttpStub([{"status": 529, "headers": {"Retry-After": "8"}}] * 50) as hs:
            self.configure("openai-http", hs.url())
            job = self.make_job(family="gpt", retries=3, timeout_s=10)
            meta, _f = self.run_chain(job, ["openai-http"])
        self.assertEqual((meta["status"], meta["error_class"]), ("failed", "rate_limit"))
        self.assertIn("deadline", meta["reason"])
        self.assertLessEqual(self.clock.t - 1000.0, adapter.JOB_DEADLINE_FACTOR * 10, "ends within its deadline")
        self.assertTrue(all(s == 8.0 for s in self.clock.sleeps), "Retry-After is honored: %s" % self.clock.sleeps)
        self.assertLess(len(self.calls_log()), 4, "retries=3 would allow 4 attempts without the deadline")
        self.assertEqual(sum(r["requests"] for r in self.calls_log()), len(hs.requests))

    def test_cli_rate_limit_retry_waits(self):
        job = self.make_job(family="claude", retries=1)
        rl = tl.PR(1, b"", b"API Error: 429 rate_limit_error")
        meta, fake = self.run_chain(job, ["claude-cli"], family="claude", responses=[rl])
        self.assertEqual((meta["status"], meta["error_class"], len(fake.calls)), ("failed", "rate_limit", 2))
        self.assertEqual(len(self.clock.sleeps), 1)
        self.assertTrue(0 <= self.clock.sleeps[0] <= 2)
        self.assertEqual([r["requests"] for r in self.calls_log()], [1, 1])

    def test_no_wait_after_empty_output(self):
        job = self.make_job(family="claude", retries=1)
        empty = tl.PR(0, json.dumps({"type": "result", "subtype": "success", "is_error": False, "result": " "}))
        meta, fake = self.run_chain(job, ["claude-cli"], family="claude", responses=[empty])
        self.assertEqual(len(fake.calls), 2)
        self.assertEqual(self.clock.sleeps, [])


class RetryAfterTests(unittest.TestCase):
    def test_seconds_and_http_date(self):
        self.assertEqual(backends.parse_retry_after("12"), 12.0)
        self.assertEqual(backends.parse_retry_after("-3"), 0.0)
        self.assertIsNone(backends.parse_retry_after(""))
        self.assertIsNone(backends.parse_retry_after("soon"))
        now = 1445412480.0  # Wed, 21 Oct 2015 07:28:00 GMT
        self.assertEqual(backends.parse_retry_after("Wed, 21 Oct 2015 07:28:30 GMT", now_epoch=now), 30.0)
        self.assertEqual(backends.parse_retry_after("Wed, 21 Oct 2015 07:27:00 GMT", now_epoch=now), 0.0)

    def test_backoff_bounds(self):
        for n in range(8):
            for _ in range(50):
                d = backends.backoff_delay(n)
                self.assertTrue(0 <= d <= min(60, 2 ** (n + 1)), (n, d))
        self.assertEqual(backends.backoff_delay(0, retry_after=5), 5.0)
        self.assertEqual(backends.backoff_delay(0, retry_after=600), 60.0)


class RetriesSettingTests(Base):
    def test_defaults_retries_zero_is_honored(self):
        self.write_families_override({"defaults": {"retries": 0}})
        job = self.make_job(family="claude", retries=None)
        meta, fake = self.run_chain(job, ["claude-cli"], family="claude",
                                    responses=[tl.PR(1, b"", b"boom: internal error")])
        self.assertEqual((meta["status"], len(fake.calls)), ("failed", 1))


class RequestReserveTests(tl.AdapterTestCase):
    def test_reserve(self):
        cfg = families.load_families()
        job = {"family": "claude", "retries": 1}
        # claude-cli (1 request per attempt) + anthropic-http (3) + the native codex-cli detection can re-seat as
        # claude (1), 2 attempts each, + a repair of up to 3
        self.assertEqual(adapter.request_reserve(job, cfg), 2 * (1 + 3 + 1) + 3)
        self.assertEqual(adapter.request_reserve(dict(job, chain=["claude-cli"]), cfg), 2 * 1 + 1)
        self.assertEqual(adapter.request_reserve(dict(job, retries=0, chain=["claude-cli"]), cfg), 1 + 1)
        self.assertEqual(adapter.request_reserve({"family": "host"}, cfg), 0)
        self.assertEqual(adapter.request_reserve(dict(job, chain=["host"]), cfg), 0)
        os.environ["UB_FAKE_FAMILIES"] = "1"
        self.assertEqual(adapter.request_reserve({"family": "kimi-alt", "retries": 1}, cfg), 3)


class StopReasonTests(Base):
    def test_anthropic_max_tokens_is_invalid_without_repair(self):
        body = anthropic_body("a long answer cut at the token limit")
        body["stop_reason"] = "max_tokens"
        with HttpStub([{"body": body}] * 5) as hs:
            self.configure("anthropic-http", hs.url("/v1/messages"))
            job = self.make_job(family="claude", contract={"type": "text", "min_chars": 5})
            meta, _f = self.run_chain(job, ["anthropic-http"], family="claude")
        self.assertEqual((meta["status"], meta["error_class"]), ("invalid", "bad_output"))
        self.assertIn("max_tokens", meta["reason"])
        self.assertEqual(len(hs.requests), 1, "no repair call: it could not fit either")
        self.assertFalse(os.path.exists(self.out_path(job)))

    def test_openai_length_is_invalid(self):
        body = openai_body("cut text here")
        body["choices"][0]["finish_reason"] = "length"
        with HttpStub([{"body": body}] * 5) as hs:
            self.configure("openai-http", hs.url())
            job = self.make_job(family="gpt")
            meta, _f = self.run_chain(job, ["openai-http"])
        self.assertEqual(meta["status"], "invalid")
        self.assertEqual(len(hs.requests), 1)

    def test_refusal_is_not_retried_and_the_chain_moves_on(self):
        body = anthropic_body("")
        body["content"], body["stop_reason"] = [], "refusal"
        ok = tl.PR(0, json.dumps({"type": "result", "subtype": "success", "is_error": False,
                                  "result": "answer from the next backend"}))
        with HttpStub([{"body": body}] * 5) as hs:
            self.configure("anthropic-http", hs.url("/v1/messages"))
            job = self.make_job(family="claude", retries=1)
            meta, fake = self.run_chain(job, ["anthropic-http", "claude-cli"], family="claude", responses=[ok])
        self.assertEqual(len(hs.requests), 1, "a refusal is not retried on the same backend")
        self.assertEqual((meta["status"], meta["backend"], len(fake.calls)), ("ok", "claude-cli", 1))
        self.assertEqual([(r["status"], r["error_class"]) for r in self.calls_log()],
                         [("failed", "policy"), ("ok", None)])

    def test_openai_content_filter_is_a_refusal(self):
        body = openai_body(None)
        body["choices"][0]["finish_reason"] = "content_filter"
        with HttpStub([{"body": body}] * 5) as hs:
            self.configure("openai-http", hs.url())
            meta, _f = self.run_chain(self.make_job(family="gpt"), ["openai-http"])
        self.assertEqual((meta["status"], meta["error_class"], len(hs.requests)), ("failed", "policy", 1))

    def test_oversized_response_is_bad_output_and_not_retried(self):
        with HttpStub([{"text": "x" * 5000}] * 5) as hs, mock.patch.object(http_openai, "RESPONSE_CAP_BYTES", 1000):
            self.configure("openai-http", hs.url())
            meta, _f = self.run_chain(self.make_job(family="gpt", retries=1), ["openai-http"])
        self.assertEqual((meta["status"], meta["error_class"]), ("failed", "bad_output"))
        self.assertEqual(len(hs.requests), 1)


def trickle_server(stop):
    """A 200 response whose body arrives one byte every 0.2 s (a stalled proxy)."""
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            self.rfile.read(int(self.headers.get("Content-Length") or 0))
            body = json.dumps(openai_body("PONG")).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            try:
                for b in body:
                    if stop.is_set():
                        return
                    self.wfile.write(bytes([b]))
                    self.wfile.flush()
                    time.sleep(0.2)
            except (OSError, socket.error):
                pass

        def log_message(self, *a):
            pass

    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


class ReadDeadlineTests(tl.AdapterTestCase):
    def test_a_trickling_body_is_bounded_by_the_deadline(self):
        os.environ["NO_PROXY"] = os.environ["no_proxy"] = "127.0.0.1,localhost"
        os.environ["OPENAI_API_KEY"] = KEY
        stop = threading.Event()
        srv = trickle_server(stop)
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        self.addCleanup(stop.set)
        self.write_families_override({"backends": {"openai-http": {
            "url": "http://127.0.0.1:%d/v1/chat/completions" % srv.server_address[1], "model": "m",
            "enabled": True}}})
        job = self.make_job(family="gpt", timeout_s=2, retries=0)
        t0 = time.monotonic()
        meta = adapter.execute_job(job, detect_result=tl.chain_detect({"gpt": ["openai-http"]}))
        self.assertLess(time.monotonic() - t0, 6, "the body takes about 40 s to arrive")
        self.assertEqual(meta["status"], "timeout", meta)


if __name__ == "__main__":
    unittest.main()
