"""The REAL adapter backends against fake executables (KIT_SPEC 5.2-5.4, 4.7, 11.5). Owner: B4.

Each test builds a run folder with run.json, a prompt and a job file in a TmpHome whose PATH holds the fake CLIs
(`.cmd` shims on Windows, so the real cmd.exe quoting path runs), then runs `python family.py job --job <file>` and
checks the exit code, the outputs and the fake log (argv, cwd, env names, stdin hash, settings/agent-file snapshots).
"""

import hashlib
import json
import os
import re
import sys
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "harness"))
import paths  # noqa: E402
from http_stub import HttpStub  # noqa: E402
from tmphome import TmpHome  # noqa: E402

PROMPT = ("Do not load or invoke any skill; this prompt is the whole task.\n"
          "PROMPT-MARKER-7c1d the nurses swap shifts ${name} and ${other_var}.\n"
          "Reply with the single word PONG.\n")
TOKEN = "zai-backend-TOKEN-a41c"
TEXT = {"type": "text", "regex": "PONG"}
JSON_C = {"type": "json", "schema": {"type": "object", "additionalProperties": False, "required": ["answer"],
                                     "properties": {"answer": {"type": "string"}}}}


def require_adapter():
    paths.require(paths.FAMILY_PY, paths.FAMILIES_DEFAULT,
                  os.path.join(paths.SCRIPTS, "ublib", "adapter.py"),
                  os.path.join(paths.SCRIPTS, "ublib", "batch.py"), owner="B2")


class Env(object):
    def __init__(self, tc, tools=("claude", "codex", "kimi"), extra_env=None, families=None, host="claude"):
        self.tc = tc
        self.th = TmpHome(tools=tools, extra_env=extra_env)
        self.families = families
        self.host = host

    def __enter__(self):
        th = self.th.__enter__()
        th.kimi_login()
        os.makedirs(th.ub_home, exist_ok=True)
        if self.families:
            with open(os.path.join(th.ub_home, "families.json"), "w", encoding="utf-8") as f:
                json.dump(self.families, f)
        self.run = os.path.join(th.project, "brainstorm", "2026-09-23-fake backends")
        os.makedirs(os.path.join(self.run, "jobs"))
        os.makedirs(os.path.join(self.run, "prompts"))
        run_json = {"schema": 2, "kit_version": "2.0.0", "run": os.path.basename(self.run), "mode": "standard",
                    "host": {"agent": "claude-code", "family": self.host, "family_source": "default"},
                    "privacy": {"web": True, "vendors": True, "code": False,
                                "allowed_vendors": ["anthropic", "openai", "moonshot", "zhipu"]}}
        with open(os.path.join(self.run, "run.json"), "w", encoding="utf-8") as f:
            json.dump(run_json, f)
        return self

    def __exit__(self, *exc):
        return self.th.__exit__(*exc)

    def job(self, jid, family, contract=TEXT, tools="none", prompt=PROMPT, **extra):
        pf = os.path.join(self.run, "prompts", jid + ".prompt.md")
        with open(pf, "w", encoding="utf-8", newline="\n") as f:
            f.write(prompt)
        job = {"schema": 1, "run": self.run.replace("\\", "/"), "id": jid, "step": "t", "kind": "generator",
               "template": "PING", "family": family, "tier": "default", "prompt_file": "prompts/%s.prompt.md" % jid,
               "out": "out/%s.md" % jid, "tools": tools, "cwd": "empty", "repo_root": None, "timeout_s": 60,
               "retries": 1, "contract": contract, "schema_file": None, "split": None, "fallback": [],
               "provisional": False, "privacy": {"vendor_ok": True, "web_ok": True, "code_ok": False},
               "host_prompt_file": None, "stub": {}}
        job.update(extra)
        path = os.path.join(self.run, "jobs", jid + ".json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(job, f)
        return path, job

    def run_job(self, path, env_extra=None, timeout=300):
        env = dict(self.th.env)
        env.update(env_extra or {})
        return paths.run_py(paths.FAMILY_PY, ["job", "--job", path], env=env, cwd=self.th.project, timeout=timeout)

    def outputs(self, job):
        out = os.path.join(self.run, *job["out"].split("/"))
        meta = None
        if os.path.isfile(out + ".meta.json"):
            with open(out + ".meta.json", encoding="utf-8") as f:
                meta = json.load(f)
        return out, meta

    def model_calls(self, tool):
        flag = {"claude": "-p", "kimi": "-p"}.get(tool)
        calls = self.th.fake_calls(tool)
        if tool == "codex":
            return [c for c in calls if c["argv"][:1] == ["exec"]]
        return [c for c in calls if flag in c["argv"]]


def pair(argv, a, b):
    return any(argv[i] == a and argv[i + 1] == b for i in range(len(argv) - 1))


def assert_no_prompt(tc, argv):
    blob = "\n".join(argv)
    tc.assertNotIn("PROMPT-MARKER-7c1d", blob, "prompt text never goes into argv")
    tc.assertTrue(all(len(a) < 400 for a in argv))


def under(path, root):
    p = os.path.normcase(os.path.abspath(path.replace("/", os.sep)))
    r = os.path.normcase(os.path.abspath(root))
    return p == r or p.startswith(r + os.sep)


class Claude(unittest.TestCase):
    def setUp(self):
        require_adapter()

    def test_argv_stdin_cwd_env(self):
        env_extra = {"ANTHROPIC_BASE_URL": "https://api.z.ai/api/anthropic", "CLAUDECODE": "1"}
        with Env(self, tools=("claude",), extra_env=env_extra) as e:
            path, job = e.job("t-claude-1", "claude")
            proc = e.run_job(path)
            self.assertEqual(proc.returncode, 0, paths.describe(proc))
            out, meta = e.outputs(job)
            self.assertTrue(os.path.isfile(out))
            self.assertEqual((meta["status"], meta["backend"]), ("ok", "claude-cli"))
            calls = e.model_calls("claude")
            self.assertEqual(len(calls), 1)
            c = calls[0]
            argv = c["argv"]
            self.assertIn("-p", argv)
            self.assertTrue(pair(argv, "--output-format", "json"))
            for flag in ("--no-session-persistence", "--strict-mcp-config"):
                self.assertIn(flag, argv)
            self.assertTrue(pair(argv, "--disallowedTools", "mcp__*"))
            self.assertTrue(pair(argv, "--tools", "") or "--tools=" in argv,
                            "tools none: an empty --tools element survives the shim [U-13]: %s" % argv)
            self.assertNotIn("--bare", argv)
            self.assertNotIn("--json-schema", argv)
            assert_no_prompt(self, argv)
            self.assertEqual(c["stdin_sha256"], hashlib.sha256(PROMPT.encode("utf-8")).hexdigest(),
                             "the prompt arrives on stdin")
            self.assertFalse(under(c["cwd"], e.run), "cwd is an empty temp dir outside the run folder")
            self.assertNotIn("ANTHROPIC_BASE_URL", c["env_names"], "a z.ai base URL never reaches family claude")
            self.assertNotIn("CLAUDECODE", c["env_names"])
            for name in ("UB_JOB_ID", "UB_JOB_FILE"):
                self.assertIn(name, c["env_names"])
            self.assertEqual(c["env"].get("NO_COLOR"), "1")
            mcp = c.get("mcp_config") or {}
            self.assertTrue(mcp.get("exists"), "--mcp-config points at the empty-mcp.json file")

    def test_glm_settings_file(self):
        with Env(self, tools=("claude",), extra_env={"ZAI_API_KEY": TOKEN}) as e:
            path, job = e.job("t-glm-1", "glm")
            proc = e.run_job(path)
            self.assertEqual(proc.returncode, 0, paths.describe(proc))
            c = e.model_calls("claude")[-1]
            self.assertIn("--settings", c["argv"])
            snap = c["settings"]
            self.assertTrue(snap["exists"], "the @glm settings file exists during the call")
            self.assertFalse(os.path.exists(snap["path"]), "and is gone afterwards")
            if os.name != "nt":
                self.assertEqual(snap["mode"], "0o600")
            self.assertIn("api.z.ai", snap["env"]["ANTHROPIC_BASE_URL"])
            self.assertTrue(snap["env"]["ANTHROPIC_AUTH_TOKEN"].startswith("sha256:"))
            self.assertNotIn("ZAI_API_KEY", c["env_names"], "the token goes only into the settings file")
            self.assertNotIn(TOKEN, e.th.log_text())
            self.assertNotIn(TOKEN, json.dumps(e.outputs(job)[1]))
            with open(os.path.join(e.run, "logs", "calls.jsonl"), encoding="utf-8") as f:
                self.assertNotIn(TOKEN, f.read())


class Codex(unittest.TestCase):
    def setUp(self):
        require_adapter()

    def check_base_argv(self, argv):
        self.assertEqual(argv[0], "exec")
        for flag in ("--skip-git-repo-check", "--ephemeral", "--json"):
            self.assertIn(flag, argv)
        self.assertTrue(pair(argv, "-s", "read-only"))
        i = argv.index("-C")
        self.assertTrue(os.path.isdir(os.path.dirname(argv[i + 1])) or argv[i + 1])
        self.assertIn("-o", argv)
        self.assertEqual(argv[-1], "-", "the prompt goes on stdin")
        for bad in ("--full-auto", "--yolo"):
            self.assertNotIn(bad, argv)
        self.assertFalse(any(a.startswith("--dangerously") for a in argv))
        assert_no_prompt(self, argv)

    def test_argv_web_and_schema(self):
        with Env(self, tools=("codex",)) as e:
            path, job = e.job("t-codex-none", "gpt")
            proc = e.run_job(path)
            self.assertEqual(proc.returncode, 0, paths.describe(proc))
            c = e.model_calls("codex")[-1]
            self.check_base_argv(c["argv"])
            self.assertNotIn("web_search=live", c["argv"])
            self.assertNotIn("--output-schema", c["argv"])
            self.assertTrue(paths.same_path(c["cwd"], c["argv"][c["argv"].index("-C") + 1]), "process cwd = -C dir")
            self.assertEqual(c["stdin_sha256"], hashlib.sha256(PROMPT.encode("utf-8")).hexdigest())

            path, job = e.job("t-codex-web", "gpt", tools="web")
            proc = e.run_job(path)
            self.assertEqual(proc.returncode, 0, paths.describe(proc))
            argv = e.model_calls("codex")[-1]["argv"]
            self.check_base_argv(argv)
            self.assertTrue(pair(argv, "-c", "web_search=live"), argv)

            with open(os.path.join(e.run, "answer.schema.json"), "w", encoding="utf-8") as f:
                json.dump(JSON_C["schema"], f)
            path, job = e.job("t-codex-schema", "gpt", contract=JSON_C, schema_file="answer.schema.json")
            proc = e.run_job(path)
            self.assertEqual(proc.returncode, 0, paths.describe(proc))
            argv = e.model_calls("codex")[-1]["argv"]
            self.assertIn("--output-schema", argv, "native OpenAI backend uses --output-schema")

    def test_glm_codex_home_and_no_schema(self):
        with Env(self, tools=("codex",), extra_env={"ZAI_API_KEY": TOKEN}) as e:
            home = os.path.join(e.th.ub_home, "codex-homes", "glm")
            os.makedirs(home)
            with open(os.path.join(home, "config.toml"), "w", encoding="utf-8") as f:
                f.write('model = "glm-5.3"\nmodel_provider = "zai"\n')
            with open(os.path.join(e.run, "answer.schema.json"), "w", encoding="utf-8") as f:
                json.dump(JSON_C["schema"], f)
            path, job = e.job("t-codex-glm", "glm", contract=JSON_C, schema_file="answer.schema.json")
            proc = e.run_job(path)
            self.assertEqual(proc.returncode, 0, paths.describe(proc))
            c = e.model_calls("codex")[-1]
            self.check_base_argv(c["argv"])
            self.assertTrue(paths.same_path(c["env"].get("CODEX_HOME"), home))
            self.assertNotIn("--output-schema", c["argv"], "U-7: no --output-schema on provider backends")
            self.assertIn("ZAI_API_KEY", c["env_names"], "codex-cli@glm adds back its token_env")
            self.assertEqual(e.outputs(job)[1]["backend"], "codex-cli@glm")


class Kimi(unittest.TestCase):
    def setUp(self):
        require_adapter()

    def test_agent_file_and_env(self):
        with Env(self, tools=("kimi",)) as e:
            path, job = e.job("t-kimi-1", "kimi")
            proc = e.run_job(path)
            self.assertEqual(proc.returncode, 0, paths.describe(proc))
            c = e.model_calls("kimi")[-1]
            argv = c["argv"]
            self.assertIn("--agent-file", argv)
            self.assertIn("--skills-dir", argv)
            self.assertTrue(pair(argv, "--output-format", "stream-json"))
            i = argv.index("-p")
            self.assertEqual(argv[i + 1],
                             "Carry out the task in your system instructions now. Output only the requested result.")
            for bad in ("--yolo", "--auto", "--plan"):
                self.assertNotIn(bad, argv)
            assert_no_prompt(self, argv)
            snap = c["agent_file"]
            self.assertRegex(snap["frontmatter"], r"(?m)^tools:\s*\[\]\s*$")
            self.assertRegex(snap["frontmatter"], r"(?m)^name:\s*ub-oneshot\s*$")
            self.assertTrue(snap["body_has_escaped"], "every ${identifier} is escaped to $ {identifier}")
            self.assertFalse(snap["body_has_dollar_brace"])
            self.assertEqual(c["env"].get("KIMI_CODE_NO_AUTO_UPDATE"), "1")
            self.assertEqual(c["env"].get("KIMI_CODE_BACKGROUND_PRINT_BACKGROUND_MODE"), "exit")
            self.assertEqual(c["env"].get("KIMI_LOOP_MAX_STEPS_PER_TURN"), "4")
            skills = argv[argv.index("--skills-dir") + 1]
            self.assertFalse(os.path.exists(skills) and os.listdir(skills), "the skills dir is empty (or gone)")

    def test_stream_json_tool_noise(self):
        with Env(self, tools=("kimi",)) as e:
            e.th.set_scenario([{"tool": "kimi", "argv_regex": "-p", "action": "stub", "kimi_variant": "tools"}])
            path, job = e.job("t-kimi-noise", "kimi", contract=JSON_C)
            proc = e.run_job(path)
            self.assertEqual(proc.returncode, 0, paths.describe(proc))
            out, meta = e.outputs(job)
            with open(out, encoding="utf-8") as f:
                self.assertEqual(sorted(json.load(f)), ["answer"])


class AllBackends(unittest.TestCase):
    def setUp(self):
        require_adapter()

    def test_brackets_and_spaces_survive_cmd_shims(self):
        fams = {"backends": {"codex-cli": {"model": "glm-5.3[1m]"}}}
        with Env(self, tools=("codex",), families=fams) as e:
            self.assertIn(" ", e.run)
            path, job = e.job("t-model-arg", "gpt")
            proc = e.run_job(path)
            self.assertEqual(proc.returncode, 0, paths.describe(proc))
            argv = e.model_calls("codex")[-1]["argv"]
            self.assertTrue(pair(argv, "-m", "glm-5.3[1m]"), argv)
            o = argv[argv.index("-o") + 1]
            self.assertTrue(os.path.isabs(o.replace("/", os.sep)))

    def test_ampersand_refused_on_cmd(self):
        if os.name != "nt":
            self.skipTest(".cmd argument-safety check applies to Windows shims")
        fams = {"backends": {"codex-cli": {"model": "a&b"}}}
        with Env(self, tools=("codex",), families=fams) as e:
            path, job = e.job("t-amp", "gpt")
            proc = e.run_job(path)
            self.assertNotEqual(proc.returncode, 0, paths.describe(proc))
            self.assertEqual(e.model_calls("codex"), [], "the .cmd exe never starts with an unsafe argument")

    def test_timeout_kills_tree(self):
        with Env(self, tools=("codex",)) as e:
            e.th.set_scenario([{"tool": "codex", "argv_regex": r"^exec", "action": "sleep", "sleep_s": 120,
                                "spawn_child": True}])
            path, job = e.job("t-timeout", "gpt", timeout_s=4, retries=0)
            t0 = time.time()
            proc = e.run_job(path, timeout=200)
            self.assertEqual(proc.returncode, 6, paths.describe(proc))
            self.assertLess(time.time() - t0, 90)
            self.assertEqual(e.outputs(job)[1]["status"], "timeout")
            with open(e.th.log + ".children", encoding="utf-8") as f:
                kids = [json.loads(l) for l in f if l.strip()]
            from ublib import proc as uproc
            deadline = time.time() + 15
            while time.time() < deadline and any(uproc.pid_alive(k["child"]) for k in kids):
                time.sleep(0.5)
            self.assertFalse([k for k in kids if uproc.pid_alive(k["child"])], "the whole process tree dies")

    def test_fail_once_then_retry_succeeds(self):
        with Env(self, tools=("claude",)) as e:
            e.th.set_scenario([{"tool": "claude", "argv_regex": "-p", "action": "fail", "exit": 1,
                                "stderr": "transient", "max_hits": 1}])
            path, job = e.job("t-fail-once", "claude")
            proc = e.run_job(path)
            self.assertEqual(proc.returncode, 0, paths.describe(proc))
            self.assertEqual(e.outputs(job)[1]["attempts"], 2)

    def test_garbage_repair_then_exit_5(self):
        with Env(self, tools=("claude",)) as e:
            e.th.set_scenario([{"tool": "claude", "argv_regex": "-p", "action": "garbage"}])
            path, job = e.job("t-garbage", "claude", contract=JSON_C)
            proc = e.run_job(path)
            self.assertEqual(proc.returncode, 5, paths.describe(proc))
            out, meta = e.outputs(job)
            self.assertEqual(meta["status"], "invalid")
            self.assertFalse(os.path.exists(out))
            with open(out + ".failed.md", encoding="utf-8") as f:
                self.assertTrue(f.readline().startswith("FAMILY CALL FAILED:"))
            calls = e.model_calls("claude")
            self.assertEqual(len(calls), 2, "one call plus exactly one repair call")
            self.assertNotEqual(calls[0]["stdin_sha256"], calls[1]["stdin_sha256"], "the repair prompt differs")

    def test_encodings_and_fences_parse(self):
        for action, tool, family in (("utf16", "claude", "claude"), ("bom", "claude", "claude"),
                                     ("fence", "claude", "claude"), ("utf16", "codex", "gpt"),
                                     ("bom", "kimi", "kimi"), ("fence", "codex", "gpt")):
            with self.subTest(action=action, tool=tool):
                with Env(self, tools=(tool,)) as e:
                    e.th.set_scenario([{"tool": tool, "action": action, "argv_regex": r"(^exec|-p)"}])
                    path, job = e.job("t-%s-%s" % (action, tool), family, contract=JSON_C)
                    proc = e.run_job(path)
                    self.assertEqual(proc.returncode, 0, paths.describe(proc))

    def test_is_error_fails_with_exit_4(self):
        with Env(self, tools=("claude",)) as e:
            e.th.set_scenario([{"tool": "claude", "argv_regex": "-p", "action": "is_error",
                                "result": "The model stopped during execution"}])
            path, job = e.job("t-is-error", "claude")
            proc = e.run_job(path)
            self.assertEqual(proc.returncode, 4, paths.describe(proc))
            self.assertEqual(e.outputs(job)[1]["status"], "failed")

    def test_is_error_auth_is_not_retried(self):
        with Env(self, tools=("claude",)) as e:
            e.th.set_scenario([{"tool": "claude", "argv_regex": "-p", "action": "is_error",
                                "result": "Invalid API key - Please run /login"}])
            path, job = e.job("t-auth", "claude")
            proc = e.run_job(path)
            self.assertIn(proc.returncode, (3, 4), paths.describe(proc))
            self.assertEqual(len(e.model_calls("claude")), 1, "no retry after an auth failure")
            self.assertEqual(e.outputs(job)[1]["error_class"], "auth")

    def test_http_backend_honors_retry_after(self):
        script = [{"status": 429, "headers": {"Retry-After": "1"}}, {"text": "PONG from the http stub"}]
        with HttpStub(script) as hs:
            fams = {"families": {"gpt": {"backends": ["openai-http"]}},
                    "backends": {"openai-http": {"url": hs.url("/v1/chat/completions"), "model": "gpt-test",
                                                 "enabled": True}}}
            key = "sk-http-SECRET-9a0b"
            with Env(self, tools=(), families=fams, extra_env={"OPENAI_API_KEY": key}) as e:
                path, job = e.job("t-http", "gpt")
                proc = e.run_job(path)
                self.assertEqual(proc.returncode, 0, paths.describe(proc))
                self.assertEqual(len(hs.requests), 2)
                self.assertGreaterEqual(hs.requests[1]["ts"] - hs.requests[0]["ts"], 0.9, "Retry-After honored")
                self.assertTrue(all(r["has_auth"] for r in hs.requests))
                body = hs.requests[0]["body"]
                self.assertEqual(body["model"], "gpt-test")
                self.assertEqual(body["messages"][0]["content"], PROMPT)
                out, meta = e.outputs(job)
                self.assertEqual(meta["backend"], "openai-http")
                self.assertNotIn(key, json.dumps(meta))


class WorkerProtocol(unittest.TestCase):
    """Running marker + heartbeat; kill the worker -> dead after UB_HEARTBEAT_STALE_S -> relaunch -> done."""

    def setUp(self):
        require_adapter()

    def wait(self, pred, timeout, what):
        deadline = time.time() + timeout
        while time.time() < deadline:
            if pred():
                return
            time.sleep(0.3)
        self.fail("timed out waiting for " + what)

    def test_marker_dead_relaunch(self):
        with Env(self, tools=("claude",), extra_env={"UB_HEARTBEAT_STALE_S": "3", "UB_NO_DETACH": "0"}) as e:
            e.th.set_scenario([{"tool": "claude", "argv_regex": "-p", "action": "sleep", "sleep_s": 120}])
            path, job = e.job("t-worker", "claude", timeout_s=300)
            with e.th.patched_environ():
                import importlib
                batch = importlib.import_module("ublib.batch")
                from ublib import proc as uproc
                marker = os.path.join(e.run, ".ub", "jobs", "t-worker.running.json")
                info = batch.launch_job(path)
                self.assertIn("pid", info)
                self.wait(lambda: os.path.isfile(marker), 60, "the running marker")
                with open(marker, encoding="utf-8") as f:
                    m = json.load(f)
                for k in ("pid", "started_at", "heartbeat_at", "attempt", "backend"):
                    self.assertIn(k, m)
                self.assertEqual(batch.job_state(e.run, job), "running")
                self.assertIn("t-worker", batch.running_jobs(e.run))
                uproc.kill_tree(m["pid"])
                self.wait(lambda: batch.job_state(e.run, job) == "dead", 30, "state dead")
                e.th.set_scenario([])
                batch.launch_job(path)
                self.wait(lambda: batch.job_state(e.run, job) == "done", 120, "state done after relaunch")
                self.assertGreaterEqual(batch.relaunch_count(e.run, job), 1)
                self.assertFalse(os.path.exists(marker), "the worker deletes its marker on exit")


if __name__ == "__main__":
    unittest.main()
