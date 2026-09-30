"""B2 adapter tests: Claude Code CLI backend (KIT_SPEC 5.2, 5.3, 5.4, 4.7) - argv, env policy, settings file,
parsing, retries, repair, redaction and a real timeout tree-kill. Process calls are mocked at ublib.proc.run."""

import json
import os
import stat
import subprocess
import sys
import textwrap
import time
import unittest
from unittest import mock

_KIT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(_KIT, "tests", "fixtures", "adapter"))

import adapter_testlib as tl  # noqa: E402
from ublib import adapter, proc, textio  # noqa: E402
from ublib.backends import claude_cli  # noqa: E402

CLAUDE_P = "Follow the instructions in the piped input exactly. Output only the requested result."
SUCCESS = tl.fixture_bytes("claude", "success.json")
IS_ERROR = tl.fixture_bytes("claude", "is_error.json")
AUTH = tl.fixture_bytes("claude", "auth.json")
TOKEN = "zai-test-token-0123456789abcdef"


def ok_json(text):
    return json.dumps({"type": "result", "subtype": "success", "is_error": False, "result": text,
                       "total_cost_usd": 0.001, "usage": {"input_tokens": 3, "output_tokens": 4}}).encode("utf-8")


class ClaudeBase(tl.AdapterTestCase):
    def run_job(self, job, responses, chain=("claude-cli",), resolve=None):
        fake = tl.FakeRun(responses)
        det = tl.chain_detect({job["family"].replace("-alt", ""): list(chain)}, host_family="claude")
        with mock.patch("ublib.proc.run", side_effect=fake), \
                mock.patch("ublib.proc.resolve_exe", side_effect=tl.fake_resolve(resolve)):
            meta = adapter.execute_job(job, detect_result=det)
        return meta, fake


class ArgvTests(ClaudeBase):
    def test_tools_none_argv_exact_and_stdin(self):
        job = self.make_job(family="claude")
        meta, fake = self.run_job(job, [tl.PR(0, SUCCESS)])
        self.assertEqual(meta["status"], "ok")
        argv = fake.calls[0]["argv"]
        mcp = os.path.join(self.home, "tmp", "empty-mcp.json")
        self.assertEqual(argv[1:], ["-p", CLAUDE_P, "--output-format", "json", "--no-session-persistence",
                                    "--strict-mcp-config", "--mcp-config", mcp, "--disallowedTools", "mcp__*",
                                    "--setting-sources", "project", "--tools", "", "--max-turns", "3"])
        self.assertTrue(os.path.isabs(argv[0]))
        self.assertEqual(json.loads(textio.read_text(mcp)), {"mcpServers": {}})
        prompt = textio.read_text(os.path.join(self.run_dir, job["prompt_file"]))
        self.assertEqual(fake.calls[0]["stdin"], prompt.encode("utf-8"))
        for a in argv:
            self.assertNotIn("PONG", a)
        self.assertNotIn("--bare", argv)
        self.assertNotIn("--json-schema", argv)

    def test_cwd_is_empty_temp_dir_outside_run_and_removed(self):
        job = self.make_job(family="claude")
        _meta, fake = self.run_job(job, [tl.PR(0, SUCCESS)])
        cwd = fake.calls[0]["cwd"]
        self.assertEqual(fake.calls[0]["cwd_listing"], [])
        self.assertFalse(os.path.abspath(cwd).startswith(os.path.abspath(self.run_dir)))
        self.assertTrue(os.path.abspath(cwd).startswith(os.path.join(os.path.abspath(self.home), "tmp")))
        self.assertFalse(os.path.exists(cwd))

    def test_tools_web_and_read_profiles(self):
        job = self.make_job(family="claude", tools="web", job_id="3.2-R1")
        _m, fake = self.run_job(job, [tl.PR(0, SUCCESS)])
        self.assertEqual(fake.calls[0]["argv"][13:], ["--tools", "WebSearch,WebFetch", "--allowedTools",
                                                      "WebSearch,WebFetch", "--max-turns", "40"])
        repo = os.path.join(self.tmp, "repo")
        os.makedirs(repo)
        job = self.make_job(family="claude", tools="read", cwd="repo", repo_root=repo, job_id="3.2-R2")
        self.write_run_json()
        _m, fake = self.run_job(job, [tl.PR(0, SUCCESS)])
        argv = fake.calls[0]["argv"]
        self.assertEqual(argv[argv.index("--tools"):], ["--tools", "Read,Grep,Glob", "--allowedTools",
                                                        "Read,Grep,Glob", "--max-turns", "30"])
        self.assertEqual(os.path.abspath(fake.calls[0]["cwd"]), os.path.abspath(repo))

    def test_tier_fast_and_alt_model(self):
        job = self.make_job(family="claude", tier="fast")
        _m, fake = self.run_job(job, [tl.PR(0, SUCCESS)])
        self.assertEqual(fake.calls[0]["argv"][-2:], ["--model", "haiku"])
        job = self.make_job(family="claude-alt", job_id="alt-1")
        meta, fake = self.run_job(job, [tl.PR(0, SUCCESS)])
        self.assertEqual(fake.calls[0]["argv"][-2:], ["--model", "sonnet"])
        self.assertTrue(meta["provisional"])
        self.assertEqual(meta["vendor"], "anthropic")
        self.assertEqual(meta["model"], "sonnet")

    def test_cmd_shim_empty_tools_spelling_u13(self):
        job = self.make_job(family="claude")
        shim = os.path.join(self.tmp, "bin", "claude.cmd")
        _m, fake = self.run_job(job, [tl.PR(0, SUCCESS)], resolve={"claude": shim})
        self.assertIn("", fake.calls[0]["argv"])  # default: the empty element is kept
        self.write_families_override({"backends": {"claude-cli": {"tools_equals_on_cmd": True}}})
        job = self.make_job(family="claude", job_id="j2")
        _m, fake = self.run_job(job, [tl.PR(0, SUCCESS)], resolve={"claude": shim})
        argv = fake.calls[0]["argv"]
        self.assertIn("--tools=", argv)
        self.assertNotIn("", argv)

    def test_json_schema_only_when_native_and_not_cmd_u12(self):
        schema = {"type": "object", "required": ["a"], "properties": {"a": {"type": "string"}}}
        textio.write_json_atomic(os.path.join(self.run_dir, "s.schema.json"), schema)
        job = self.make_job(family="claude", schema_file="s.schema.json",
                            contract={"type": "json", "schema": "s.schema.json"})
        _m, fake = self.run_job(job, [tl.PR(0, ok_json('{"a": "x"}'))])
        self.assertNotIn("--json-schema", fake.calls[0]["argv"])
        self.write_families_override({"backends": {"claude-cli": {"native_schema": True}}})
        job = self.make_job(family="claude", job_id="j2", schema_file="s.schema.json",
                            contract={"type": "json", "schema": "s.schema.json"})
        _m, fake = self.run_job(job, [tl.PR(0, ok_json('{"a": "x"}'))])
        self.assertIn("--json-schema", fake.calls[0]["argv"])
        job = self.make_job(family="claude", job_id="j3", schema_file="s.schema.json",
                            contract={"type": "json", "schema": "s.schema.json"})
        _m, fake = self.run_job(job, [tl.PR(0, ok_json('{"a": "x"}'))],
                                resolve={"claude": os.path.join(self.tmp, "claude.cmd")})
        self.assertNotIn("--json-schema", fake.calls[0]["argv"])


class EnvPolicyTests(ClaudeBase):
    def test_zai_base_url_scrubbed_for_native_claude(self):
        os.environ.update({"ANTHROPIC_BASE_URL": "https://api.z.ai/api/anthropic",
                           "ANTHROPIC_AUTH_TOKEN": "zai-host-token-abcdefgh", "CLAUDECODE": "1",
                           "CLAUDE_CODE_CHILD_SESSION": "1", "API_TIMEOUT_MS": "3000000", "UB_HOST_FAMILY": "glm",
                           "CLAUDE_CODE_EFFORT_LEVEL": "max", "KIMI_MODEL_NAME": "x", "OPENAI_API_KEY": "sk-openai-12345678",
                           "UB_FAKE_SCENARIO": "scenario.json", "UB_STUB_DELAY_S": "0"})
        job = self.make_job(family="claude")
        _m, fake = self.run_job(job, [tl.PR(0, SUCCESS)])
        env = fake.calls[0]["env"]
        for name in ("ANTHROPIC_BASE_URL", "ANTHROPIC_AUTH_TOKEN", "CLAUDECODE", "CLAUDE_CODE_CHILD_SESSION",
                     "API_TIMEOUT_MS", "UB_HOST_FAMILY", "CLAUDE_CODE_EFFORT_LEVEL", "KIMI_MODEL_NAME",
                     "OPENAI_API_KEY"):
            self.assertNotIn(name, env)
        self.assertEqual(env["UB_JOB_ID"], job["id"])
        self.assertIn("UB_JOB_FILE", env)
        self.assertEqual(env["NO_COLOR"], "1")
        self.assertEqual(env["UB_FAKE_SCENARIO"], "scenario.json")
        self.assertEqual(env["UB_STUB_DELAY_S"], "0")

    def test_anthropic_base_url_restored(self):
        os.environ.update({"ANTHROPIC_BASE_URL": "https://api.anthropic.com",
                           "ANTHROPIC_API_KEY": "sk-ant-test-0123456789abcdef"})
        job = self.make_job(family="claude")
        _m, fake = self.run_job(job, [tl.PR(0, SUCCESS)])
        env = fake.calls[0]["env"]
        self.assertEqual(env["ANTHROPIC_BASE_URL"], "https://api.anthropic.com")
        self.assertEqual(env["ANTHROPIC_API_KEY"], "sk-ant-test-0123456789abcdef")

    def test_job_file_exported(self):
        job = self.make_job(family="claude")
        path = self.write_job(job)
        job["_path"] = path
        _m, fake = self.run_job(job, [tl.PR(0, SUCCESS)])
        self.assertEqual(fake.calls[0]["env"]["UB_JOB_FILE"], path)


class ProviderTests(ClaudeBase):
    def test_glm_settings_file_0600_deleted_and_token_hidden(self):
        os.environ["ZAI_API_KEY"] = TOKEN
        seen = {}

        def respond(call):
            argv = call["argv"]
            path = argv[argv.index("--settings") + 1]
            seen["path"] = path
            seen["exists"] = os.path.isfile(path)
            seen["data"] = json.loads(textio.read_text(path))
            if os.name != "nt":
                seen["mode"] = stat.S_IMODE(os.stat(path).st_mode)
            else:
                out = subprocess.run(["icacls", path], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                seen["acl"] = out.stdout.decode("utf-8", "replace")
            return tl.PR(0, SUCCESS)

        job = self.make_job(family="glm", job_id="4.2-S5")
        meta, fake = self.run_job(job, [respond], chain=("claude-cli@glm",))
        self.assertEqual(meta["status"], "ok")
        argv = fake.calls[0]["argv"]
        self.assertNotIn("--model", argv)
        self.assertTrue(seen["exists"])
        self.assertFalse(os.path.exists(seen["path"]))
        env_block = seen["data"]["env"]
        self.assertEqual(env_block["ANTHROPIC_BASE_URL"], "https://api.z.ai/api/anthropic")
        self.assertEqual(env_block["ANTHROPIC_MODEL"], "glm-5.3[1m]")
        self.assertEqual(env_block["ANTHROPIC_DEFAULT_HAIKU_MODEL"], "glm-5.3-flash[1m]")
        self.assertEqual(env_block["ANTHROPIC_DEFAULT_FABLE_MODEL"], "glm-5.3[1m]")
        self.assertEqual(env_block["ANTHROPIC_AUTH_TOKEN"], TOKEN)
        self.assertEqual(env_block["API_TIMEOUT_MS"], "3000000")
        if os.name != "nt":
            self.assertEqual(seen["mode"], 0o600)
        else:
            self.assertNotIn("(I)", seen["acl"])  # inheritance removed
            self.assertIn(os.environ.get("USERNAME", ""), seen["acl"])
        self.assertNotIn(TOKEN, " ".join(argv))
        self.assertNotIn(TOKEN, json.dumps(fake.calls[0]["env"]))
        self.assertNotIn("ZAI_API_KEY", fake.calls[0]["env"])
        self.assertNotIn(TOKEN, self.all_output_text())
        self.assertEqual(meta["model"], "glm-5.3[1m]")

    def test_fast_tier_is_expressed_in_settings(self):
        os.environ["KIMI_API_KEY"] = "moonshot-test-key-123456"
        seen = {}

        def respond(call):
            argv = call["argv"]
            seen["data"] = json.loads(textio.read_text(argv[argv.index("--settings") + 1]))
            return tl.PR(0, SUCCESS)

        job = self.make_job(family="kimi", tier="fast")
        _m, fake = self.run_job(job, [respond], chain=("claude-cli@kimi",))
        self.assertNotIn("--model", fake.calls[0]["argv"])
        self.assertEqual(seen["data"]["env"]["ANTHROPIC_MODEL"], "kimi-k2.7-code")
        self.assertEqual(seen["data"]["env"]["CLAUDE_CODE_EFFORT_LEVEL"], "max")

    def test_missing_token_is_unavailable(self):
        job = self.make_job(family="glm")
        meta, fake = self.run_job(job, [tl.PR(0, SUCCESS)], chain=("claude-cli@glm",))
        self.assertEqual(meta["status"], "unavailable")
        self.assertEqual(adapter.exit_code_for(meta["status"]), 3)
        self.assertEqual(fake.calls, [])


class ParseRetryTests(ClaudeBase):
    def test_success_writes_out_meta_and_log(self):
        job = self.make_job(family="claude")
        meta, _f = self.run_job(job, [tl.PR(0, SUCCESS)])
        self.assertEqual(textio.read_text(self.out_path(job)), "PONG. The answer is ready.")
        disk = self.read_meta(job)
        self.assertEqual(disk["status"], "ok")
        self.assertEqual(disk["prompt_sha256"], textio.sha256_file(os.path.join(self.run_dir, job["prompt_file"])))
        self.assertEqual(disk["out_sha256"], textio.sha256_file(self.out_path(job)))
        self.assertEqual(disk["usage"], {"input_tokens": 120, "output_tokens": 45, "cost_usd": 0.0123,
                                         "source": "reported"})
        for key in ("schema", "id", "family", "vendor", "backend", "model", "tier", "provisional", "status",
                    "attempts", "exit_code", "error_class", "started", "duration_s", "prompt_sha256", "out_sha256",
                    "usage", "tools", "web_used", "cwd", "repaired", "cmd", "stderr_tail"):
            self.assertIn(key, disk)
        self.assertEqual(disk["backend"], "claude-cli")
        self.assertEqual(disk["attempts"], 1)
        log = self.calls_log()
        self.assertEqual(len(log), 1)
        self.assertIn("ts", log[0])
        self.assertEqual(log[0]["status"], "ok")
        self.assertFalse(os.path.exists(self.out_path(job) + ".failed.md"))

    def test_multi_line_output_is_tolerated(self):
        job = self.make_job(family="claude")
        meta, _f = self.run_job(job, [tl.PR(0, tl.fixture_bytes("claude", "multi_line.jsonl"))])
        self.assertEqual(meta["status"], "ok")
        self.assertEqual(textio.read_text(self.out_path(job)), "Streamed final answer text.")

    def test_is_error_retried_then_failed_exit_4(self):
        job = self.make_job(family="claude")
        meta, fake = self.run_job(job, [tl.PR(1, IS_ERROR)])
        self.assertEqual(len(fake.calls), 2)
        self.assertEqual(meta["status"], "failed")
        self.assertEqual(adapter.exit_code_for(meta["status"]), 4)
        self.assertFalse(os.path.exists(self.out_path(job)))
        with open(self.out_path(job) + ".failed.md", encoding="utf-8") as f:
            self.assertTrue(f.readline().startswith("FAMILY CALL FAILED: "))
        self.assertEqual(len(self.calls_log()), 2)

    def test_auth_failure_no_retry(self):
        job = self.make_job(family="claude")
        meta, fake = self.run_job(job, [tl.PR(1, AUTH)])
        self.assertEqual(len(fake.calls), 1)
        self.assertEqual(meta["error_class"], "auth")
        self.assertEqual(meta["status"], "unavailable")
        self.assertEqual(adapter.exit_code_for(meta["status"]), 3)

    def test_fail_once_then_ok(self):
        job = self.make_job(family="claude")
        meta, fake = self.run_job(job, [tl.PR(1, b"", b"boom: internal error"), tl.PR(0, SUCCESS)])
        self.assertEqual(meta["status"], "ok")
        self.assertEqual(meta["attempts"], 2)
        self.assertEqual(len(fake.calls), 2)

    def test_garbage_output_retried_as_bad_output(self):
        job = self.make_job(family="claude", retries=0)
        meta, _f = self.run_job(job, [tl.PR(0, b"this is not json")])
        self.assertEqual(meta["status"], "failed")
        self.assertEqual(meta["error_class"], "bad_output")

    def test_chain_moves_to_next_backend_on_auth(self):
        job = self.make_job(family="claude")
        with mock.patch("ublib.backends.http_anthropic.run",
                        return_value={"status": "ok", "text": "from http", "error_class": None, "error": "",
                                      "exit_code": 200, "usage": {"input_tokens": 1, "output_tokens": 1,
                                                                  "cost_usd": None, "source": "reported"},
                                      "cmd": "POST x", "stderr_tail": "", "model": "m", "web_used": False}):
            meta, fake = self.run_job(job, [tl.PR(1, AUTH)], chain=("claude-cli", "anthropic-http"))
        self.assertEqual(meta["status"], "ok")
        self.assertEqual(meta["backend"], "anthropic-http")
        self.assertEqual(meta["attempts"], 2)
        self.assertEqual(textio.read_text(self.out_path(job)), "from http")

    def test_hard_failure_then_unavailable_reports_the_hard_backend(self):
        job = self.make_job(family="claude")
        with mock.patch("ublib.backends.http_anthropic.run",
                        return_value={"status": "unavailable", "text": None, "error_class": "auth",
                                      "error": "ANTHROPIC_API_KEY is not set", "exit_code": None,
                                      "usage": {"input_tokens": None, "output_tokens": None, "cost_usd": None,
                                                "source": "none"},
                                      "cmd": "", "stderr_tail": "", "model": None, "web_used": False}):
            meta, _fake = self.run_job(job, [tl.PR(1, IS_ERROR)], chain=("claude-cli", "anthropic-http"))
        self.assertEqual(meta["status"], "failed")
        self.assertEqual(meta["backend"], "claude-cli")
        self.assertEqual(meta["exit_code"], 1)
        self.assertIn("claude", meta["cmd"])

    def test_repair_call_fixes_invalid_json(self):
        schema = {"type": "object", "required": ["score"], "properties": {"score": {"type": "integer"}}}
        textio.write_json_atomic(os.path.join(self.run_dir, "v.schema.json"), schema)
        job = self.make_job(family="claude", contract={"type": "json", "schema": "v.schema.json"})
        meta, fake = self.run_job(job, [tl.PR(0, ok_json('{"score": "high"}')), tl.PR(0, ok_json('{"score": 4}'))])
        self.assertEqual(meta["status"], "ok")
        self.assertTrue(meta["repaired"])
        repair_prompt = fake.calls[1]["stdin"].decode("utf-8")
        self.assertTrue(repair_prompt.startswith("Your previous output failed validation: "))
        self.assertIn("Return only the corrected output.", repair_prompt)
        self.assertIn('{"score": "high"}', repair_prompt)
        self.assertEqual(json.loads(textio.read_text(self.out_path(job))), {"score": 4})

    def test_invalid_after_repair_exit_5(self):
        job = self.make_job(family="claude", contract={"type": "text", "regex": "NEVER-MATCHES-XYZ"})
        meta, fake = self.run_job(job, [tl.PR(0, SUCCESS)])
        self.assertEqual(len(fake.calls), 2)
        self.assertEqual(meta["status"], "invalid")
        self.assertEqual(adapter.exit_code_for(meta["status"]), 5)
        self.assertFalse(os.path.exists(self.out_path(job)))
        with open(self.out_path(job) + ".failed.md", encoding="utf-8") as f:
            self.assertTrue(f.readline().startswith("FAMILY CALL FAILED: output invalid after repair"))

    def test_mocked_timeout_exit_6_no_retry(self):
        job = self.make_job(family="claude")
        meta, fake = self.run_job(job, [tl.PR(-9, b"", b"", timed_out=True)])
        self.assertEqual(len(fake.calls), 1)
        self.assertEqual(meta["status"], "timeout")
        self.assertEqual(adapter.exit_code_for(meta["status"]), 6)

    def test_output_over_cap_is_invalid(self):
        job = self.make_job(family="claude")
        big = "x" * (2 * 1024 * 1024 + 10)
        meta, _f = self.run_job(job, [tl.PR(0, ok_json(big))])
        self.assertEqual(meta["status"], "invalid")

    def test_redaction_in_meta_and_logs(self):
        secret = "sk-ant-secretvalue-0123456789abcdef"
        os.environ["ANTHROPIC_API_KEY"] = secret
        job = self.make_job(family="claude", retries=0)
        meta, _f = self.run_job(job, [tl.PR(1, b"", ("upstream said bad key %s" % secret).encode())])
        self.assertEqual(meta["status"], "failed")
        blob = self.all_output_text()
        self.assertNotIn(secret, blob)
        self.assertIn("[REDACTED]", textio.read_text(self.out_path(job) + ".meta.json"))


class ParseUnitTests(unittest.TestCase):
    def test_parse_shapes(self):
        from ublib.backends import CallContext
        ctx = CallContext(bcfg={"web": True}, btype="claude-cli", timeout_s=5, tools="web")
        r = claude_cli.parse(tl.PR(0, SUCCESS), ctx, "cmd")
        self.assertEqual((r["status"], r["text"], r["web_used"]), ("ok", "PONG. The answer is ready.", True))
        r = claude_cli.parse(tl.PR(0, IS_ERROR), ctx, "cmd")
        self.assertEqual((r["status"], r["error_class"]), ("failed", "internal"))
        r = claude_cli.parse(tl.PR(1, AUTH), ctx, "cmd")
        self.assertEqual(r["error_class"], "auth")
        r = claude_cli.parse(tl.PR(1, b"", b"Error: 403 Forbidden"), ctx, "cmd")
        self.assertEqual(r["error_class"], "auth")
        r = claude_cli.parse(tl.PR(1, b"", b"getaddrinfo ENOTFOUND api.anthropic.com"), ctx, "cmd")
        self.assertEqual(r["error_class"], "network")


FAKE_CLAUDE = textwrap.dedent('''\
    import os, subprocess, sys, time
    marker = os.path.join(os.environ["UB_TEST_PID_DIR"], "child.pid")
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
    with open(marker, "w") as f:
        f.write(str(child.pid))
    sys.stdin.read()
    time.sleep(120)
''')


class RealTimeoutTreeKillTests(tl.AdapterTestCase):
    """A real fake `claude` that spawns a child and hangs: the whole tree dies and the job reports timeout (6)."""

    def test_timeout_kills_process_tree(self):
        bindir = os.path.join(self.tmp, "bin")
        os.makedirs(bindir)
        piddir = os.path.join(self.tmp, "pids")
        os.makedirs(piddir)
        script = os.path.join(bindir, "fake_claude.py")
        with open(script, "w", encoding="utf-8", newline="\n") as f:
            f.write(FAKE_CLAUDE)
        if os.name == "nt":
            with open(os.path.join(bindir, "claude.cmd"), "w", encoding="ascii", newline="\r\n") as f:
                f.write('@"%s" "%s" %%*\n' % (sys.executable, script))
        else:
            exe = os.path.join(bindir, "claude")
            with open(exe, "w", encoding="utf-8", newline="\n") as f:
                f.write("#!%s\n" % sys.executable + FAKE_CLAUDE)
            os.chmod(exe, 0o755)
        os.environ["PATH"] = bindir + os.pathsep + os.environ.get("PATH", "")
        os.environ["UB_TEST_PID_DIR"] = piddir
        job = self.make_job(family="claude", timeout_s=4, retries=1)
        det = tl.chain_detect({"claude": ["claude-cli"]})
        t0 = time.monotonic()
        meta = adapter.execute_job(job, detect_result=det)
        self.assertEqual(meta["status"], "timeout", meta)
        self.assertEqual(adapter.exit_code_for(meta["status"]), 6)
        self.assertLess(time.monotonic() - t0, 60)
        with open(os.path.join(piddir, "child.pid")) as f:
            child_pid = int(f.read().strip())
        deadline = time.monotonic() + 15
        while proc.pid_alive(child_pid) and time.monotonic() < deadline:
            time.sleep(0.2)
        self.assertFalse(proc.pid_alive(child_pid), "grandchild survived the tree kill")


if __name__ == "__main__":
    unittest.main()
