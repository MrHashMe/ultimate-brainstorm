"""WP2b: error classification (finding 23) and credential redaction (finding 31).

classify_error tested auth before rate limits, with bare words ("login", "credential"), and kimi/claude fed it model
output and tool results: a Kimi web job whose fetched page said "Log in" and that hit a 429 was classed auth, skipped
its retry and ended unavailable. redact() knew literal env values and three key shapes only: JWTs, key=value query
parameters, Basic and URL-userinfo credentials and PEM keys reached meta, calls.jsonl and .failed.md."""

import json
import os
import sys
import unittest
from unittest import mock

_KIT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(_KIT, "tests", "fixtures", "adapter"))

import adapter_testlib as tl  # noqa: E402
from ublib import adapter, redact  # noqa: E402
from ublib.backends import CallContext, claude_cli, classify_error, kimi_cli  # noqa: E402

JWT = "eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiJ1c2VyLTEyMzQ1Njc4OSJ9.c2lnbmF0dXJlLXZhbHVlLTAxMjM0NTY3ODk"
PROXY_PW = "hunter2hunter2"


class ClassifyTests(unittest.TestCase):
    def test_table(self):
        table = [
            ("429 Too Many Requests. Please log in to the console to see your limits", "rate_limit"),
            ("API Error: 529 Overloaded", "rate_limit"),
            ('{"type":"error","error":{"type":"overloaded_error","message":"Overloaded"}}', "rate_limit"),
            ("Error code: 429 - {'error': {'type': 'rate_limit_reached_error'}}", "rate_limit"),
            ("insufficient_quota: You exceeded your current quota", "rate_limit"),
            ("Invalid API key - Please run /login", "auth"),
            ("Error: 403 Forbidden", "auth"),
            ("stream error: unexpected status 401 Unauthorized", "auth"),
            ("Error: not logged in. Run kimi login", "auth"),
            ("authentication_error: invalid x-api-key", "auth"),
            ("passwordless login flow for the nurses", "internal"),
            ("500 internal error while refreshing the credentials cache", "internal"),
            ("the Log in button on the fetched page", "internal"),
            ("getaddrinfo ENOTFOUND api.anthropic.com", "network"),
            ("error: network access is restricted by the sandbox", "sandbox_network"),
            ("unknown model gpt-9", "not_found"),
        ]
        for text, want in table:
            self.assertEqual(classify_error(text), want, text)


def kimi_transcript():
    """A kimi web job that died mid-loop: the fetched page and the assistant both talk about logging in."""
    lines = [{"role": "assistant", "content": "", "tool_calls": [{"id": "t1", "type": "function",
                                                                   "function": {"name": "FetchURL"}}]},
             {"role": "tool", "tool_call_id": "t1", "content": "Log in | Sign in to see pricing. Forbidden area."},
             {"role": "assistant", "content": "The passwordless login flow is the key idea."}]
    return ("\n".join(json.dumps(x) for x in lines) + "\n").encode("utf-8")


class ErrorChannelTests(tl.AdapterTestCase):
    def test_kimi_classifies_stderr_and_error_records_only(self):
        ctx = CallContext(bcfg={"web": False}, btype="kimi-cli", timeout_s=5, tools="web")
        r = kimi_cli.parse(tl.PR(1, kimi_transcript(), b"Error code: 429 rate_limit_reached_error"), ctx, "kimi")
        self.assertEqual(r["error_class"], "rate_limit")
        self.assertTrue(r["web_used"], "a FetchURL call is evidence of web use")
        r = kimi_cli.parse(tl.PR(1, kimi_transcript(), b"connection reset by peer"), ctx, "kimi")
        self.assertEqual(r["error_class"], "network")
        err = kimi_transcript() + b'{"type":"error","error":{"message":"401 Unauthorized"}}\n'
        r = kimi_cli.parse(tl.PR(1, err, b""), ctx, "kimi")
        self.assertEqual(r["error_class"], "auth", "error records still count")

    def test_kimi_transient_failure_is_retried(self):
        job = self.make_job(family="kimi", tools="web")
        ok = tl.fixture_bytes("kimi", "string.jsonl")
        fake = tl.FakeRun([tl.PR(1, kimi_transcript(), b"Error code: 429 rate_limit_reached_error"), tl.PR(0, ok)])
        with mock.patch("ublib.proc.run", side_effect=fake), \
                mock.patch("ublib.proc.resolve_exe", side_effect=tl.fake_resolve()):
            meta = adapter.execute_job(job, detect_result=tl.chain_detect({"kimi": ["kimi-cli"]}, "claude"))
        self.assertEqual((meta["status"], meta["attempts"]), ("ok", 2))

    def test_claude_json_events_are_not_classified(self):
        ctx = CallContext(bcfg={}, btype="claude-cli", timeout_s=5)
        stdout = b'{"type":"assistant","message":{"content":"please log in to the passwordless login flow"}}\n'
        r = claude_cli.parse(tl.PR(1, stdout, b"connection reset"), ctx, "claude")
        self.assertEqual(r["error_class"], "network")
        r = claude_cli.parse(tl.PR(1, b"Error: not logged in", b""), ctx, "claude")
        self.assertEqual(r["error_class"], "auth", "a raw CLI message on stdout still counts")


class RedactShapeTests(unittest.TestCase):
    def check(self, text, gone, kept=()):
        out = redact.redact(text)
        for g in gone:
            self.assertNotIn(g, out, out)
        for k in kept:
            self.assertIn(k, out, out)
        self.assertIn(redact.MASK, out)
        return out

    def test_shapes(self):
        self.check('{"access_token": "%s", "refresh_token": "rt-0123456789abcdef"}' % JWT, [JWT, "rt-0123456789abcdef"],
                   ['"access_token": "'])
        self.check("GET /v1/x?key=AIzaSyA0123456789abcdefgh&model=m", ["AIzaSyA0123456789abcdefgh"], ["model=m"])
        self.check("https://h.example/cb?code=1&access_token=tok0123456789&sig=abcdef0123456789",
                   ["tok0123456789", "abcdef0123456789"])
        self.check("api_key=0123456789abcdef0123456789abcdef.AbCdEfGhIjKlMnOp", ["0123456789abcdef0123456789abcdef"])
        self.check("Authorization: Basic dXNlcjpwYXNzd29yZDEyMw==", ["dXNlcjpwYXNzd29yZDEyMw=="], ["Basic "])
        self.check("proxy https://alice:%s@proxy.corp:8080 refused" % PROXY_PW, [PROXY_PW],
                   ["https://alice:", "@proxy.corp:8080"])
        self.check("token ghp_" + "a1" * 18 + " leaked", ["ghp_" + "a1" * 18])
        self.check("Authorization: Bearer %s" % JWT, [JWT], ["Bearer "])
        self.check("x-api-key: k-0123456789abcdef", ["k-0123456789abcdef"])
        pem = "-----BEGIN OPENSSH PRIVATE KEY-----\nb3BlbnNzaC1rZXktdjEAAAAA\nQUJDREVGRw==\n" \
              "-----END OPENSSH PRIVATE KEY-----\ntail text"
        self.check(pem, ["b3BlbnNzaC1rZXktdjEAAAAA", "QUJDREVGRw=="],
                   ["-----BEGIN OPENSSH PRIVATE KEY-----", "-----END OPENSSH PRIVATE KEY-----", "tail text"])
        self.check("-----BEGIN RSA PRIVATE KEY-----\nMIIEpAIBAAKCAQEA0123456789", ["MIIEpAIBAAKCAQEA0123456789"])

    def test_ordinary_text_is_kept(self):
        for text in ('{"max_tokens": 16000, "input_tokens": 1500, "output_tokens": 320}',
                     "HTTP Basic authentication failed", "The key: understanding the nurses' handover",
                     "https://example.com:8080/path@anchor", "token_env ZAI_API_KEY", "C:/Users/me/proj/file.md",
                     'codex exec -c mcp_servers={} -c web_search=disabled -c features.shell_tool=false'):
            self.assertEqual(redact.redact(text), text)

    def test_env_values_and_proxy_password(self):
        with mock.patch.dict(os.environ, {"MY_SERVICE_TOKEN": "tok-abcdefgh1234",
                                          "HTTPS_PROXY": "http://bob:%s@proxy:3128" % PROXY_PW}):
            self.assertIn(PROXY_PW, redact.known_secret_values())
            self.assertEqual(redact.redact("x tok-abcdefgh1234 y %s" % PROXY_PW), "x [REDACTED] y [REDACTED]")


class RedactEndToEndTests(tl.AdapterTestCase):
    def test_cli_credentials_never_reach_meta_logs_or_failed_md(self):
        basic = "dXNlcjpwYXNzd29yZDEyMw=="
        stderr = ('error: refresh failed {"access_token":"%s"} via https://u:%s@proxy.corp:8080 '
                  "(Authorization: Basic %s)" % (JWT, PROXY_PW, basic)).encode()
        job = self.make_job(family="claude", retries=0)
        fake = tl.FakeRun([tl.PR(1, b"", stderr)])
        with mock.patch("ublib.proc.run", side_effect=fake), \
                mock.patch("ublib.proc.resolve_exe", side_effect=tl.fake_resolve()):
            meta = adapter.execute_job(job, detect_result=tl.chain_detect({"claude": ["claude-cli"]}, "claude"))
        self.assertEqual(meta["status"], "failed")
        blob = self.all_output_text()
        for secret in (JWT, PROXY_PW, basic):
            self.assertNotIn(secret, blob)
        self.assertIn(redact.MASK, blob)


if __name__ == "__main__":
    unittest.main()
