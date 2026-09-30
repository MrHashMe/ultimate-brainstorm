"""B2 adapter tests: Codex CLI backend (KIT_SPEC 5.2, 5.3) - exact argv, web and schema flags, CODEX_HOME for
provider variants, env add-back, -o file and JSONL parsing, chain order. Process calls are mocked at proc.run."""

import json
import os
import sys
import unittest
from unittest import mock

_KIT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(_KIT, "tests", "fixtures", "adapter"))

import adapter_testlib as tl  # noqa: E402
from ublib import adapter, textio  # noqa: E402
from ublib.backends import CallContext, codex_cli  # noqa: E402

EVENTS = tl.fixture_bytes("codex", "events.jsonl")
ERROR_EVENTS = tl.fixture_bytes("codex", "error_events.jsonl")
ZAI = "zai-test-token-abcdef0123456789"


def writes_last(text, stdout=EVENTS, rc=0):
    """A fake codex exec: writes text to the -o file and prints JSONL."""
    def respond(call):
        argv = call["argv"]
        if text is not None:
            with open(argv[argv.index("-o") + 1], "wb") as f:
                f.write(text.encode("utf-8"))
        return tl.PR(rc, stdout)
    return respond


class CodexBase(tl.AdapterTestCase):
    def run_job(self, job, responses, chain=("codex-cli",)):
        fake = tl.FakeRun(responses)
        det = tl.chain_detect({job["family"].replace("-alt", ""): list(chain)}, host_family="claude")
        with mock.patch("ublib.proc.run", side_effect=fake), \
                mock.patch("ublib.proc.resolve_exe", side_effect=tl.fake_resolve()):
            meta = adapter.execute_job(job, detect_result=det)
        return meta, fake


class ArgvTests(CodexBase):
    def test_argv_exact_none(self):
        job = self.make_job(family="gpt")
        meta, fake = self.run_job(job, [writes_last("Answer text from codex.")])
        self.assertEqual(meta["status"], "ok")
        call = fake.calls[0]
        argv = call["argv"]
        cwd = argv[argv.index("-C") + 1]
        last = argv[argv.index("-o") + 1]
        features = ["apps", "plugins", "multi_agent", "hooks", "memories", "browser_use", "computer_use",
                    "image_generation", "unbounded_connection_retries", "shell_tool", "js_repl", "view_image"]
        self.assertEqual(argv[1:], ["exec", "--skip-git-repo-check", "--ephemeral", "-s", "read-only", "-C", cwd,
                                    "-o", last, "--json", "-c", "notify=[]"]
                         + [x for f in features for x in ("-c", "features.%s=false" % f)]
                         + ["-c", "web_search=disabled", "-"])
        self.assertNotIn("mcp_servers={}", argv, "an empty table is merged, not replaced: it would do nothing")
        self.assertEqual(os.path.abspath(call["cwd"]), os.path.abspath(cwd))
        self.assertEqual(call["cwd_listing"], [])
        self.assertEqual(os.path.basename(last), "last.txt")
        self.assertEqual(call["stdin"], textio.read_text(os.path.join(self.run_dir, job["prompt_file"])).encode())
        for bad in ("--full-auto", "--yolo", "--dangerously-bypass-approvals-and-sandbox"):
            self.assertNotIn(bad, argv)
        self.assertNotIn("web_search=live", argv)
        self.assertNotIn("--output-schema", argv)

    def test_web_flag_only_for_web_jobs(self):
        job = self.make_job(family="gpt", tools="web")
        _m, fake = self.run_job(job, [writes_last("ok text here")])
        argv = fake.calls[0]["argv"]
        self.assertEqual(argv[-3:], ["-c", "web_search=live", "-"])

    def test_output_schema_only_on_native_openai_backend(self):
        schema = {"type": "object", "required": ["v"], "properties": {"v": {"type": "string"}}}
        textio.write_json_atomic(os.path.join(self.run_dir, "tournament", "verdicts.schema.json"), schema)
        contract = {"type": "json", "schema": "tournament/verdicts.schema.json"}
        job = self.make_job(family="gpt", schema_file="tournament/verdicts.schema.json", contract=contract)
        seen = {}

        def respond(call):
            argv = call["argv"]
            seen["schema"] = textio.read_json(argv[argv.index("--output-schema") + 1])
            return writes_last('{"v": "A"}')(call)
        _m, fake = self.run_job(job, [respond])
        argv = fake.calls[0]["argv"]
        i = argv.index("--output-schema")
        # [U-85] a per-call copy (deleted with the call folder) in place of the run's schema file
        self.assertEqual(os.path.dirname(argv[i + 1]), os.path.dirname(argv[argv.index("-o") + 1]))
        self.assertEqual(seen["schema"], schema)
        self.assertFalse(os.path.exists(argv[i + 1]))
        # provider variant: native_schema false -> no --output-schema
        os.environ["ZAI_API_KEY"] = ZAI
        os.makedirs(os.path.join(self.home, "codex-homes", "glm"))
        job = self.make_job(family="glm", job_id="g1", schema_file="tournament/verdicts.schema.json",
                            contract=contract)
        _m, fake = self.run_job(job, [writes_last('{"v": "A"}')], chain=("codex-cli@glm",))
        self.assertNotIn("--output-schema", fake.calls[0]["argv"])

    def test_configured_model(self):
        self.write_families_override({"backends": {"codex-cli": {"model": "gpt-test-model"}}})
        job = self.make_job(family="gpt")
        _m, fake = self.run_job(job, [writes_last("ok text here")])
        argv = fake.calls[0]["argv"]
        self.assertEqual(argv[argv.index("-m") + 1], "gpt-test-model")
        self.assertEqual(argv[-1], "-")


class EnvTests(CodexBase):
    def test_glm_variant_sets_codex_home_and_token(self):
        os.environ.update({"ZAI_API_KEY": ZAI, "OPENAI_API_KEY": "sk-openai-shouldnotpass-123",
                           "CODEX_HOME": os.path.join(self.tmp, "user-codex")})
        home = os.path.join(self.home, "codex-homes", "glm")
        os.makedirs(home)
        job = self.make_job(family="glm")
        meta, fake = self.run_job(job, [writes_last("glm answer text")], chain=("codex-cli@glm",))
        self.assertEqual(meta["status"], "ok")
        env = fake.calls[0]["env"]
        self.assertEqual(os.path.abspath(env["CODEX_HOME"]), os.path.abspath(home))
        self.assertEqual(env["ZAI_API_KEY"], ZAI)
        self.assertNotIn("OPENAI_API_KEY", env)
        self.assertNotIn(ZAI, " ".join(fake.calls[0]["argv"]))
        self.assertNotIn(ZAI, self.all_output_text())
        self.assertEqual(meta["vendor"], "zhipu")

    def test_glm_variant_without_home_is_unavailable(self):
        os.environ["ZAI_API_KEY"] = ZAI
        job = self.make_job(family="glm")
        meta, fake = self.run_job(job, [writes_last("x")], chain=("codex-cli@glm",))
        self.assertEqual(meta["status"], "unavailable")
        self.assertEqual(fake.calls, [])

    def test_native_adds_back_user_openai_settings(self):
        user_home = os.path.join(self.tmp, "user-codex")
        os.environ.update({"OPENAI_API_KEY": "sk-openai-test-0123456789", "CODEX_HOME": user_home,
                           "OPENAI_BASE_URL": "https://api.openai.com/v1", "ZAI_API_KEY": ZAI,
                           "ANTHROPIC_BASE_URL": "https://api.z.ai/api/anthropic"})
        job = self.make_job(family="gpt")
        _m, fake = self.run_job(job, [writes_last("ok text here")])
        env = fake.calls[0]["env"]
        self.assertEqual(env["OPENAI_API_KEY"], "sk-openai-test-0123456789")
        self.assertEqual(env["CODEX_HOME"], user_home)
        self.assertEqual(env["OPENAI_BASE_URL"], "https://api.openai.com/v1")
        self.assertNotIn("ZAI_API_KEY", env)
        self.assertNotIn("ANTHROPIC_BASE_URL", env)


class ParseTests(CodexBase):
    def test_o_file_text_and_jsonl_usage(self):
        job = self.make_job(family="gpt")
        meta, _f = self.run_job(job, [writes_last("\ufeffText from the -o file.\r\n")])
        self.assertEqual(textio.read_text(self.out_path(job)), "Text from the -o file.\n")
        self.assertEqual(meta["usage"], {"input_tokens": 1500, "output_tokens": 320, "cost_usd": None,
                                         "source": "reported"})

    def test_utf16_o_file(self):
        def respond(call):
            argv = call["argv"]
            with open(argv[argv.index("-o") + 1], "wb") as f:
                f.write("UTF-16 answer text".encode("utf-16"))
            return tl.PR(0, EVENTS)
        job = self.make_job(family="gpt")
        meta, _f = self.run_job(job, [respond])
        self.assertEqual(meta["status"], "ok")
        self.assertEqual(textio.read_text(self.out_path(job)), "UTF-16 answer text")

    def test_missing_o_file_falls_back_to_agent_message(self):
        job = self.make_job(family="gpt")
        meta, _f = self.run_job(job, [writes_last(None)])
        self.assertEqual(meta["status"], "ok")
        self.assertEqual(textio.read_text(self.out_path(job)), "Final answer from the JSONL stream.")

    def test_error_events_classified_auth_no_retry(self):
        job = self.make_job(family="gpt")
        meta, fake = self.run_job(job, [writes_last(None, stdout=ERROR_EVENTS, rc=1)])
        self.assertEqual(len(fake.calls), 1)
        self.assertEqual(meta["error_class"], "auth")
        self.assertEqual(meta["status"], "unavailable")

    def test_empty_output_retried(self):
        job = self.make_job(family="gpt")
        meta, fake = self.run_job(job, [tl.PR(0, b'{"type":"turn.completed","usage":{}}'),
                                        writes_last("second try text")])
        self.assertEqual(len(fake.calls), 2)
        self.assertEqual(meta["status"], "ok")
        self.assertEqual(meta["attempts"], 2)

    def test_sandbox_network_error_class(self):
        ctx = CallContext(bcfg={}, btype="codex-cli", timeout_s=5)
        r = codex_cli.parse(tl.PR(1, b"", b"error: network access is restricted by the sandbox"), ctx, "c", None)
        self.assertEqual(r["error_class"], "sandbox_network")

    def test_chain_order_moves_on_after_retries(self):
        job = self.make_job(family="gpt")
        ok = {"status": "ok", "text": "http answer text", "error_class": None, "error": "", "exit_code": 200,
              "usage": {"input_tokens": 1, "output_tokens": 1, "cost_usd": None, "source": "reported"},
              "cmd": "POST x", "stderr_tail": "", "model": "m", "web_used": False}
        with mock.patch("ublib.backends.http_openai.run", return_value=ok) as http_run:
            meta, fake = self.run_job(job, [tl.PR(2, b"", b"panic: something broke")],
                                      chain=("codex-cli", "openai-http"))
        self.assertEqual(len(fake.calls), 2)  # 1 try + 1 retry on codex
        self.assertEqual(http_run.call_count, 1)
        self.assertEqual(meta["backend"], "openai-http")
        self.assertEqual(meta["attempts"], 3)
        self.assertEqual([e["backend"] for e in self.calls_log()], ["codex-cli", "codex-cli", "openai-http"])


if __name__ == "__main__":
    unittest.main()
