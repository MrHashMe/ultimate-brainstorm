"""B2 adapter tests: HTTP backends against a local 127.0.0.1 server (KIT_SPEC 5.2), and the policy guards of
5.6 (worker exit 7 for every rule). No external network is used."""

import json
import os
import sys
import threading
import unittest
from unittest import mock

try:
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
except ImportError:  # pragma: no cover
    from http.server import BaseHTTPRequestHandler, HTTPServer as ThreadingHTTPServer

_KIT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(_KIT, "tests", "fixtures", "adapter"))

import adapter_testlib as tl  # noqa: E402
from ublib import adapter, backends, families, textio  # noqa: E402

OPENAI_OK = tl.fixture_bytes("http", "openai_ok.json")
ANTHROPIC_OK = tl.fixture_bytes("http", "anthropic_ok.json")
KEY = "sk-local-test-key-0123456789abcdef"


class Script(object):
    """Scripted responses: a list of (status, headers, body bytes); the last one repeats."""

    def __init__(self, steps):
        self.steps = list(steps)
        self.requests = []


def make_server(script):
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            n = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(n)
            script.requests.append({"path": self.path, "headers": {k.lower(): v for k, v in self.headers.items()},
                                    "body": json.loads(body.decode("utf-8"))})
            status, headers, payload = script.steps[min(len(script.requests) - 1, len(script.steps) - 1)]
            self.send_response(status)
            for k, v in headers.items():
                self.send_header(k, v)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *a):
            pass

    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    return srv


class HttpBase(tl.AdapterTestCase):
    def setUp(self):
        super(HttpBase, self).setUp()
        os.environ["NO_PROXY"] = "127.0.0.1,localhost"
        os.environ["no_proxy"] = "127.0.0.1,localhost"
        self.sleeps = []
        p = mock.patch.object(backends, "_sleep", side_effect=lambda s: self.sleeps.append(s))
        p.start()
        self.addCleanup(p.stop)

    def serve(self, steps):
        script = Script(steps)
        srv = make_server(script)
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        return script, "http://127.0.0.1:%d" % srv.server_address[1]

    def run_http(self, job, backend_id, chain_family):
        det = tl.chain_detect({chain_family: [backend_id]})
        return adapter.execute_job(job, detect_result=det)


class OpenAIChatTests(HttpBase):
    def configure(self, base, **extra):
        cfg = {"url": base + "/v1/chat/completions", "model": "test-model", "enabled": True, "key_env": "OPENAI_API_KEY"}
        cfg.update(extra)
        self.write_families_override({"backends": {"openai-http": cfg}})

    def test_ok_shape_headers_and_body(self):
        script, base = self.serve([(200, {}, OPENAI_OK)])
        self.configure(base)
        os.environ["OPENAI_API_KEY"] = KEY
        job = self.make_job(family="gpt")
        meta = self.run_http(job, "openai-http", "gpt")
        self.assertEqual(meta["status"], "ok", meta)
        self.assertEqual(textio.read_text(self.out_path(job)), "HTTP chat answer.")
        req = script.requests[0]
        self.assertEqual(req["path"], "/v1/chat/completions")
        self.assertEqual(req["headers"]["authorization"], "Bearer " + KEY)
        prompt = textio.read_text(os.path.join(self.run_dir, job["prompt_file"]))
        self.assertEqual(req["body"], {"model": "test-model", "messages": [{"role": "user", "content": prompt}],
                                       "max_tokens": 16000})
        self.assertEqual(meta["usage"]["input_tokens"], 11)
        self.assertEqual(meta["usage"]["source"], "reported")
        self.assertNotIn(KEY, self.all_output_text())
        self.assertEqual(meta["model"], "test-model")

    def test_429_then_200_honors_retry_after(self):
        script, base = self.serve([(429, {"Retry-After": "1"}, b'{"error":"rate"}'), (200, {}, OPENAI_OK)])
        self.configure(base)
        os.environ["OPENAI_API_KEY"] = KEY
        job = self.make_job(family="gpt")
        meta = self.run_http(job, "openai-http", "gpt")
        self.assertEqual(meta["status"], "ok")
        self.assertEqual(len(script.requests), 2)
        self.assertEqual(self.sleeps, [1.0])

    def test_5xx_backoff_at_most_two_retries(self):
        script, base = self.serve([(503, {}, b'{"error":"down"}')])
        self.configure(base)
        os.environ["OPENAI_API_KEY"] = KEY
        job = self.make_job(family="gpt", retries=0)
        meta = self.run_http(job, "openai-http", "gpt")
        self.assertEqual((meta["status"], meta["error_class"]), ("failed", "rate_limit"))
        self.assertEqual(len(script.requests), 3)
        self.assertEqual(len(self.sleeps), 2)  # full jitter: uniform in [0, 2] then [0, 4] seconds
        self.assertTrue(0 <= self.sleeps[0] <= 2 and 0 <= self.sleeps[1] <= 4, self.sleeps)
        self.assertEqual(meta["requests"], 3)
        self.assertEqual([row["requests"] for row in self.calls_log()], [3])

    def test_401_is_auth_and_unavailable(self):
        script, base = self.serve([(401, {}, b'{"error":{"message":"invalid api key"}}')])
        self.configure(base)
        os.environ["OPENAI_API_KEY"] = KEY
        job = self.make_job(family="gpt")
        meta = self.run_http(job, "openai-http", "gpt")
        self.assertEqual((meta["status"], meta["error_class"]), ("unavailable", "auth"))
        self.assertEqual(len(script.requests), 1)

    def test_off_unless_configured(self):
        job = self.make_job(family="gpt")
        meta = self.run_http(job, "openai-http", "gpt")  # default config: model null, no key
        self.assertEqual(meta["status"], "unavailable")
        os.environ["OPENAI_API_KEY"] = KEY
        meta = self.run_http(self.make_job(family="gpt", job_id="j2"), "openai-http", "gpt")
        self.assertEqual(meta["status"], "unavailable")
        self.assertIn("no model", meta["reason"])
        self.write_families_override({"backends": {"openai-http": {"model": "m", "enabled": False}}})
        meta = self.run_http(self.make_job(family="gpt", job_id="j3"), "openai-http", "gpt")
        self.assertIn("disabled", meta["reason"])

    def test_content_parts_list(self):
        body = json.dumps({"choices": [{"message": {"content": [{"type": "text", "text": "a"},
                                                                {"type": "text", "text": "b"}]}}]}).encode()
        _script, base = self.serve([(200, {}, body)])
        self.configure(base)
        os.environ["OPENAI_API_KEY"] = KEY
        job = self.make_job(family="gpt", contract={"type": "text", "min_chars": 1})
        meta = self.run_http(job, "openai-http", "gpt")
        self.assertEqual(meta["status"], "ok")
        self.assertEqual(textio.read_text(self.out_path(job)), "ab")


class AnthropicTests(HttpBase):
    def test_messages_headers_and_text_blocks(self):
        script, base = self.serve([(200, {}, ANTHROPIC_OK)])
        self.write_families_override({"backends": {"anthropic-http": {"url": base + "/v1/messages",
                                                                       "model": "claude-test"}}})
        os.environ["ANTHROPIC_API_KEY"] = KEY
        job = self.make_job(family="claude")
        meta = self.run_http(job, "anthropic-http", "claude")
        self.assertEqual(meta["status"], "ok", meta)
        self.assertEqual(textio.read_text(self.out_path(job)), "Anthropic answer.")
        req = script.requests[0]
        self.assertEqual(req["headers"]["x-api-key"], KEY)
        self.assertEqual(req["headers"]["anthropic-version"], "2023-06-01")
        self.assertEqual(req["body"]["max_tokens"], 16000)
        self.assertEqual(req["body"]["model"], "claude-test")
        self.assertNotIn("authorization", req["headers"])
        self.assertNotIn(KEY, self.all_output_text())


class PolicyTests(tl.AdapterTestCase):
    """5.6: every rule refuses the job with status refused, error_class policy, exit 7, and no process starts."""

    def run_policy(self, job, chain_family, chain):
        fake = tl.FakeRun([tl.PR(0, b'{"type":"result","subtype":"success","is_error":false,"result":"ok text"}')])
        det = tl.chain_detect({chain_family: chain}, host_family="claude")
        with mock.patch("ublib.proc.run", side_effect=fake), \
                mock.patch("ublib.proc.resolve_exe", side_effect=tl.fake_resolve()):
            meta = adapter.execute_job(job, detect_result=det)
        return meta, fake

    def assertRefused(self, meta, fake):
        self.assertEqual(meta["status"], "refused", meta)
        self.assertEqual(meta["error_class"], "policy")
        self.assertEqual(adapter.exit_code_for(meta["status"]), 7)
        self.assertEqual(fake.calls, [])
        with open(self.out_path({"out": meta_out(meta, self)}) + ".failed.md", encoding="utf-8") as f:
            self.assertTrue(f.readline().startswith("FAMILY CALL FAILED: "))

    def test_rule1_vendor_not_allowed(self):
        self.write_run_json(privacy={"web": True, "vendors": False, "code": False, "allowed_vendors": ["anthropic"]})
        meta, fake = self.run_policy(self.make_job(family="gpt"), "gpt", ["codex-cli"])
        self.assertRefused(meta, fake)
        meta, fake = self.run_policy(self.make_job(family="gpt-alt", job_id="a2"), "gpt", ["codex-cli"])
        self.assertRefused(meta, fake)

    def test_rule1_job_stamp(self):
        job = self.make_job(family="gpt", privacy={"vendor_ok": False, "web_ok": True, "code_ok": False})
        meta, fake = self.run_policy(job, "gpt", ["codex-cli"])
        self.assertRefused(meta, fake)

    def test_rule2_web_while_privacy_web_false(self):
        self.write_run_json(privacy={"web": False, "vendors": True, "code": False,
                                     "allowed_vendors": ["anthropic", "openai"]})
        meta, fake = self.run_policy(self.make_job(family="claude", tools="web"), "claude", ["claude-cli"])
        self.assertRefused(meta, fake)
        meta, fake = self.run_policy(self.make_job(family="claude", tools="read+web", job_id="r2"), "claude",
                                     ["claude-cli"])
        self.assertRefused(meta, fake)

    def test_rule3_repo_cwd_for_other_vendor(self):
        repo = os.path.join(self.tmp, "repo")
        os.makedirs(repo)
        self.write_run_json()
        job = self.make_job(family="gpt", tools="read", cwd="repo", repo_root=repo)
        meta, fake = self.run_policy(job, "gpt", ["codex-cli"])
        self.assertRefused(meta, fake)
        # the host vendor may read the repo
        job = self.make_job(family="claude", tools="read", cwd="repo", repo_root=repo, job_id="h1")
        meta, fake = self.run_policy(job, "claude", ["claude-cli"])
        self.assertEqual(meta["status"], "ok")
        # privacy.code = yes allows other vendors
        self.write_run_json(privacy={"web": True, "vendors": True, "code": True,
                                     "allowed_vendors": ["anthropic", "openai"]})
        job = self.make_job(family="gpt", tools="read", cwd="repo", repo_root=repo, job_id="g2",
                            privacy={"vendor_ok": True, "web_ok": True, "code_ok": True})
        meta, _fake = self.run_policy(job, "gpt", ["codex-cli"])
        self.assertNotEqual(meta["status"], "refused")
        # a stamp that disagrees with run.json is a mismatch: refused
        job = self.make_job(family="gpt", tools="read", cwd="repo", repo_root=repo, job_id="g3")
        meta, fake = self.run_policy(job, "gpt", ["codex-cli"])
        self.assertRefused(meta, fake)

    def test_rule4_glm_plan_over_http(self):
        self.write_families_override({"backends": {"openai-http@glm-payg": {
            "enabled": True, "key_env": "ZAI_API_KEY"}}})
        os.environ["ZAI_API_KEY"] = "zai-plan-key-0123456789"
        meta, fake = self.run_policy(self.make_job(family="glm"), "glm", ["openai-http@glm-payg"])
        self.assertRefused(meta, fake)
        self.write_families_override({"backends": {"openai-http@glm-payg": {
            "enabled": True, "url": "https://open.bigmodel.cn/api/coding/paas/v4/chat/completions"}}})
        meta, fake = self.run_policy(self.make_job(family="glm", job_id="g2"), "glm", ["openai-http@glm-payg"])
        self.assertRefused(meta, fake)
        cfg = families.load_families()
        self.assertIsNone(adapter.backend_policy_check(
            dict(cfg, backends=dict(cfg["backends"], **{"openai-http@glm-payg": {
                "type": "openai-chat-http", "url": "https://api.z.ai/api/paas/v4/chat/completions",
                "key_env": "ZAI_PAYG_API_KEY"}})), "openai-http@glm-payg", "glm"))

    def test_rule5_kimi_env_model_glm(self):
        self.write_families_override({"backends": {"kimi-cli": {"env_model": True}}})
        os.environ["KIMI_MODEL_BASE_URL"] = "https://open.bigmodel.cn/api/paas/v4"
        meta, fake = self.run_policy(self.make_job(family="kimi"), "kimi", ["kimi-cli"])
        self.assertRefused(meta, fake)

    def test_rule6_strict_glm_scripted_plan_use(self):
        self.write_families_override({"families": {"glm": {"allow_scripted_plan_use": False}}})
        os.environ["ZAI_API_KEY"] = "zai-plan-key-0123456789"
        cfg = families.load_families()
        self.assertTrue(adapter.backend_policy_check(cfg, "claude-cli@glm", "glm"))
        self.assertTrue(adapter.backend_policy_check(cfg, "codex-cli@glm", "glm"))
        self.assertTrue(adapter.backend_policy_check(cfg, "claude-cli", "glm"))  # a reclassified claude-cli
        self.assertIsNone(adapter.backend_policy_check(cfg, "claude-cli", "claude"))
        # the worker refuses a GLM job whose chain still names a worker-run GLM backend
        with mock.patch("ublib.families.resolve_chain", return_value=["claude-cli@glm"]):
            meta, fake = self.run_policy(self.make_job(family="glm"), "glm", ["claude-cli@glm"])
        self.assertRefused(meta, fake)
        # and resolve_chain itself drops it (GLM then runs only as the host family)
        det = tl.chain_detect({"glm": ["claude-cli@glm", "codex-cli@glm"]}, host_family="glm")
        self.assertEqual(families.resolve_chain(cfg, "glm", det), ["host"])
        det = tl.chain_detect({"glm": ["claude-cli@glm"]}, host_family="claude")
        self.assertEqual(families.resolve_chain(cfg, "glm", det), [])


def meta_out(meta, case):
    # every PolicyTests job uses the default out path pattern pool/<id>.md
    return "pool/%s.md" % meta["id"]


if __name__ == "__main__":
    unittest.main()
