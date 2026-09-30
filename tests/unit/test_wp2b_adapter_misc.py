"""WP2b: family labels (26), user context (28), .cmd shim refusals (29), Kimi samples (30), bounded parsers (32),
fail-closed split writes (42), crash evidence (3, C5), the driver-resolved chain (C13), privacy labels (C8) and the
stub loader (the responder moved to tests/harness). Process calls are mocked at ublib.proc.run."""

import json
import os
import shutil
import sys
import threading
import unittest
from unittest import mock

_KIT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(_KIT, "tests", "fixtures", "adapter"))

import adapter_testlib as tl  # noqa: E402
from ublib import adapter, backends, batch, detect, families, proc, textio  # noqa: E402
from ublib.backends import CallContext, kimi_cli, stub  # noqa: E402

SUCCESS = tl.fixture_bytes("claude", "success.json")
EVENTS = tl.fixture_bytes("codex", "events.jsonl")
STRING = tl.fixture_bytes("kimi", "string.jsonl")
VERSIONS = {"claude": "2.1.280 (Claude Code)\n", "codex": "codex-cli 0.156.1\n", "kimi": "kimi, version 2.0.2\n"}


def run_job(job, responses, family, chain, resolve=None, detect_result=True):
    fake = tl.FakeRun(responses)
    det = tl.chain_detect({family: list(chain)}, host_family="claude") if detect_result else None
    with mock.patch("ublib.proc.run", side_effect=fake), \
            mock.patch("ublib.proc.resolve_exe", side_effect=resolve or tl.fake_resolve()):
        meta = adapter.execute_job(job, detect_result=det)
    return meta, fake


def detect_with(present=("claude", "codex", "kimi"), shim=()):
    """detect() with fake CLIs on PATH (names in shim resolve to .cmd files)."""
    def resolve(name, env=None):
        if name not in present:
            return None
        return os.path.join(os.path.abspath(os.sep), "fakebin", name + (".cmd" if name in shim else ".exe"))

    def versions(argv, cwd=None, env=None, stdin_bytes=None, timeout_s=None, **_kw):
        return tl.PR(0, VERSIONS.get(os.path.basename(argv[0]).split(".")[0], ""))
    with mock.patch("ublib.proc.resolve_exe", side_effect=resolve), mock.patch("ublib.proc.run", side_effect=versions):
        return detect.detect(families.load_families())


class FamilyLabelTests(tl.AdapterTestCase):
    """26: OPENAI_BASE_URL, the Codex default profile and Bedrock/Vertex switches."""

    def test_foreign_openai_base_url_never_answers_as_gpt(self):
        os.environ.update({"OPENAI_BASE_URL": "https://api.moonshot.ai/v1", "OPENAI_API_KEY": "sk-moonshot-0123456789"})
        meta, fake = run_job(self.make_job(family="gpt"), [tl.PR(0, EVENTS)], "gpt", ["codex-cli"])
        self.assertEqual((meta["status"], meta["error_class"]), ("unavailable", "config"))
        self.assertEqual(fake.calls, [], "no call goes out under the wrong label")
        ctx = CallContext(btype="codex-cli", bcfg={"type": "codex-cli"}, family="gpt", base_env=dict(os.environ))
        self.assertNotIn("OPENAI_BASE_URL", backends.child_env(ctx))
        ctx.family = "kimi"  # the same backend seated as kimi by detection
        self.assertEqual(backends.child_env(ctx)["OPENAI_BASE_URL"], "https://api.moonshot.ai/v1")

    def test_detect_reclassifies_codex_by_openai_base_url(self):
        os.environ["OPENAI_BASE_URL"] = "https://api.moonshot.ai/v1"
        res = detect_with()
        self.assertNotIn("codex-cli", res["families"]["gpt"]["chain"])
        self.assertIn("codex-cli", res["families"]["kimi"]["chain"])
        rec = [r for r in res["reclassified"] if r["cli"] == "codex"][0]
        self.assertEqual((rec["source"], rec["as"]), ("OPENAI_BASE_URL", "kimi"))
        os.environ["OPENAI_BASE_URL"] = "https://myres.openai.azure.com/openai"  # Azure OpenAI serves gpt
        self.assertIn("codex-cli", detect_with()["families"]["gpt"]["chain"])

    def test_codex_default_profile_selects_the_provider(self):
        textio.write_text_atomic(os.path.join(os.environ["CODEX_HOME"], "config.toml"),
                                 'profile = "k"\nmodel_provider = "openai"\n[profiles.k]\nmodel = "kimi-k3"\n'
                                 'model_provider = "moonshot"\n[model_providers.moonshot]\n'
                                 'base_url = "https://api.moonshot.ai/v1"\nenv_key = "MOONSHOT_API_KEY"\n')
        self.assertEqual(detect.codex_config_family()[:3], ("kimi", "moonshot", "https://api.moonshot.ai/v1"))
        with mock.patch.dict(sys.modules, {"tomllib": None}):  # the 3.9/3.10 regex reading
            self.assertEqual(detect.codex_config_family()[0], "kimi")

    def test_provider_children_drop_bedrock_and_vertex_switches(self):
        base = {"CLAUDE_CODE_USE_BEDROCK": "1", "CLAUDE_CODE_USE_VERTEX": "1", "PATH": "x"}
        prov = CallContext(btype="claude-cli", bcfg={"type": "claude-cli", "provider": "glm"}, base_env=base)
        env = backends.child_env(prov)
        self.assertNotIn("CLAUDE_CODE_USE_BEDROCK", env)
        self.assertNotIn("CLAUDE_CODE_USE_VERTEX", env)
        native = CallContext(btype="claude-cli", bcfg={"type": "claude-cli"}, base_env=base)
        self.assertEqual(backends.child_env(native)["CLAUDE_CODE_USE_BEDROCK"], "1")

    def test_native_claude_refuses_when_settings_route_elsewhere(self):
        d = os.environ["CLAUDE_CONFIG_DIR"]
        os.makedirs(d)
        shutil.copy(tl.fixture_path("detect", "claude_settings_zai.json"), os.path.join(d, "settings.json"))
        meta, fake = run_job(self.make_job(family="claude"), [tl.PR(0, SUCCESS)], "claude", ["claude-cli"])
        self.assertEqual((meta["status"], meta["error_class"], fake.calls), ("unavailable", "config", []))
        meta, fake = run_job(self.make_job(family="glm", job_id="g1"), [tl.PR(0, SUCCESS)], "glm", ["claude-cli"])
        self.assertEqual(meta["status"], "ok", "seated as glm, the same CLI is right")


class UserContextTests(tl.AdapterTestCase):
    """28: worker calls skip the user's Claude settings sources when that cannot change their login or route."""

    def argv(self, family="claude", chain=("claude-cli",), job_id="u1"):
        _meta, fake = run_job(self.make_job(family=family, job_id=job_id), [tl.PR(0, SUCCESS)], family, chain)
        return fake.calls[0]["argv"]

    def settings(self, data):
        d = os.environ["CLAUDE_CONFIG_DIR"]
        os.makedirs(d, exist_ok=True)
        textio.write_json_atomic(os.path.join(d, "settings.json"), data)

    def test_isolated_without_route_keys(self):
        self.assertIn("--setting-sources", self.argv())
        self.settings({"hooks": {"SessionStart": [{"hooks": [{"type": "command", "command": "inject"}]}]},
                       "enabledPlugins": {"superpowers@x": True}})
        argv = self.argv(job_id="u2")
        self.assertEqual(argv[argv.index("--setting-sources") + 1], "project")

    def test_isolated_when_settings_carry_the_login(self):
        """E2 / 28: the login and route keys travel in the call's own settings file (test_e2_user_context.py)."""
        for data in ({"env": {"HTTPS_PROXY": "http://proxy:3128"}}, {"apiKeyHelper": "/bin/get-key"}):
            self.settings(data)
            argv = self.argv(job_id="u-%d" % len(json.dumps(data)))
            self.assertIn("--setting-sources", argv)
            self.assertIn("--settings", argv)
            res = detect_with()
            self.assertFalse([n for n in res["families"]["claude"]["notes"]
                              if n.startswith(detect.USER_CONTEXT_NOTE) and "settings" in n])

    def test_config_key_overrides(self):
        self.settings({"env": {"X": "1"}})
        self.write_families_override({"backends": {"claude-cli": {"user_context": "isolate"}}})
        self.assertIn("--setting-sources", self.argv(job_id="k1"))
        self.write_families_override({"backends": {"claude-cli": {"user_context": "inherit"}}})
        os.remove(os.path.join(os.environ["CLAUDE_CONFIG_DIR"], "settings.json"))
        self.assertNotIn("--setting-sources", self.argv(job_id="k2"))

    def test_provider_backend_is_isolated_and_keeps_its_settings_file(self):
        os.environ["ZAI_API_KEY"] = "zai-test-token-0123456789"
        argv = self.argv(family="glm", chain=("claude-cli@glm",), job_id="p1")
        self.assertIn("--setting-sources", argv)
        self.assertIn("--settings", argv)

    def test_user_codex_instructions_are_reported(self):
        textio.write_text_atomic(os.path.join(os.environ["CODEX_HOME"], "AGENTS.md"), "Always answer in French.\n")
        notes = detect_with()["families"]["gpt"]["notes"]
        self.assertTrue([n for n in notes if n.startswith(detect.USER_CONTEXT_NOTE) and "AGENTS.md" in n], notes)


class CmdShimTests(tl.AdapterTestCase):
    """29: a kit path a .cmd shim cannot receive is a setup problem: unavailable/config, no retry, a clear fix."""

    def test_ub_home_with_ampersand(self):
        home = os.path.join(self.tmp, "R&D", "ubhome")
        os.makedirs(home)
        os.environ["UB_HOME"] = home
        shim = os.path.join(self.tmp, "bin", "claude.cmd")

        def run(argv, cwd=None, env=None, stdin_bytes=None, timeout_s=None, **_kw):
            proc.check_cmd_args(argv[0], argv[1:])  # what the real runner does before it starts anything
            return tl.PR(0, SUCCESS)
        job = self.make_job(family="claude", retries=1)
        with mock.patch("ublib.proc.run", side_effect=run), \
                mock.patch("ublib.proc.resolve_exe", side_effect=tl.fake_resolve({"claude": shim})):
            meta = adapter.execute_job(job, detect_result=tl.chain_detect({"claude": ["claude-cli"]}, "claude"))
        self.assertEqual((meta["status"], meta["error_class"], meta["attempts"]), ("unavailable", "config", 1))
        self.assertIn("UB_HOME", meta["reason"])
        self.assertIn("set UB_HOME", meta["reason"])
        self.assertEqual(self.calls_log()[0]["requests"], 0)

    def test_shim_path_problem_helper(self):
        shim, ok_home = "C:/bin/codex.cmd", os.path.join(self.tmp, "ub")
        self.assertIsNone(detect.shim_path_problem(shim, ok_home, os.path.join(self.tmp, "run")))
        self.assertIsNone(detect.shim_path_problem("C:/bin/codex.exe", os.path.join(self.tmp, "R&D")))
        self.assertIn("the run folder", detect.shim_path_problem(shim, ok_home, os.path.join(self.tmp, "Work R&D")))
        self.assertIn("the repository", detect.shim_path_problem(shim, ok_home, None, os.path.join(self.tmp, "a%b")))
        self.assertIn("install the CLI", detect.shim_path_problem("C:/R&D/bin/codex.cmd", ok_home))

    def test_detect_reports_it(self):
        os.environ["UB_HOME"] = os.path.join(self.tmp, "R&D", "ubhome")
        res = detect_with(shim=("codex",))
        gpt = res["families"]["gpt"]
        self.assertFalse(gpt["available"])
        self.assertTrue([n for n in gpt["notes"] if "UB_HOME" in n], gpt["notes"])
        self.assertTrue(res["families"]["claude"]["available"], "an .exe is not a shim")


class KimiSampleTests(tl.AdapterTestCase):
    """30: transcripts stay in the run folder, never for repo readers, at most SAMPLE_LIMIT even when concurrent."""

    def ctx(self, **kw):
        base = dict(bcfg={}, btype="kimi-cli", run_dir=self.run_dir, ub_home=self.home, tools="none", job_id="k")
        base.update(kw)
        return CallContext(**base)

    def test_concurrent_workers_never_exceed_the_limit(self):
        barrier = threading.Barrier(12)

        def worker():
            barrier.wait()
            kimi_cli._save_sample(self.ctx(), STRING)
        threads = [threading.Thread(target=worker) for _ in range(12)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        d = os.path.join(self.run_dir, "logs", "kimi-samples")
        self.assertEqual(len(os.listdir(d)), kimi_cli.SAMPLE_LIMIT)
        self.assertFalse(os.path.exists(os.path.join(self.home, "tmp", "kimi-samples")))

    def test_repo_readers_are_never_sampled(self):
        kimi_cli._save_sample(self.ctx(tools="read"), STRING)
        kimi_cli._save_sample(self.ctx(cwd_mode="repo", repo_root=self.tmp), STRING)
        self.assertFalse(os.path.exists(os.path.join(self.run_dir, "logs", "kimi-samples")))


class BoundedParserTests(unittest.TestCase):
    """32: parsers keep only what they need (a capped stdout never reaches them: tests/unit/test_wpf1_backends.py)."""

    def test_streams_as_bytes(self):
        lines = [{"role": "assistant", "content": "café first"}, {"role": "tool", "content": "noise"},
                 {"role": "assistant", "content": "final é"}]
        raw = "\n".join(json.dumps(x, ensure_ascii=False) for x in lines).encode("utf-8")
        self.assertEqual(kimi_cli.parse_stream(raw), "final é")
        self.assertEqual(kimi_cli.parse_stream(b"\xef\xbb\xbf" + raw), "final é")
        self.assertEqual(kimi_cli.parse_stream(raw.decode("utf-8").encode("utf-16")), "final é")
        self.assertEqual(kimi_cli.parse_stream(raw.decode("utf-8")), "final é", "str input still works")
        bad = b'{"role":"assistant","content":"ok \xff text"}\n'
        self.assertIn("ok", kimi_cli.parse_stream(bad), "an invalid byte does not drop the line")
        self.assertEqual(list(backends.iter_json_objects(b'[1]\n{"a":1}\r\nnot json\n{"b":\n')), [{"a": 1}])


class FailClosedSplitTests(tl.AdapterTestCase):
    """42: a files job without allowed globs writes nothing (worker and host paths agree)."""

    TEXT = "=== FILE: run.json ===\n{\"x\": 1}\n=== END FILE ===\n"

    def test_missing_globs_write_nothing(self):
        run_json = self.write_run_json()
        before = textio.read_text(os.path.join(self.run_dir, "run.json"))
        job = self.make_job(contract={"type": "files"}, split={"root": ".", "allowed": []})
        ok, errors, _io = adapter._validate_and_write(self.TEXT, job, self.run_dir, self.out_path(job))
        self.assertFalse(ok)
        self.assertTrue(errors)
        self.assertEqual(textio.read_text(os.path.join(self.run_dir, "run.json")), before)
        self.assertTrue(run_json)

    def test_check_job_refuses_such_a_job(self):
        job = self.make_job(contract={"type": "files"}, split={"root": "."})
        with self.assertRaises(adapter.JobError):
            adapter.check_job(job)
        job = self.make_job(contract={"type": "files", "allowed": ["x.md"]}, split={"root": "."})
        adapter.check_job(job)


class CrashEvidenceTests(tl.AdapterTestCase):
    """3 / C5: a recorded worker crash reads as failed for the current prompt, so relaunch caps apply."""

    def test_crash_meta_counts_as_failed(self):
        job = self.make_job()
        meta = adapter.crash_meta(job, "worker error: RuntimeError")
        self.assertEqual(meta["prompt_sha256"], textio.sha256_file(os.path.join(self.run_dir, job["prompt_file"])))
        self.assertEqual(batch.job_state(self.run_dir, job), "failed")
        self.assertFalse(meta["repo_read"])


class DriverChainTests(tl.AdapterTestCase):
    """C13: a job that carries its chain skips detection; only the executable and the key are re-checked."""

    def test_chain_in_job_skips_detect(self):
        job = self.make_job(family="claude", chain=["claude-cli"])
        with mock.patch("ublib.detect.detect", side_effect=AssertionError("detect must not run")):
            meta, fake = run_job(job, [tl.PR(0, SUCCESS)], "claude", [], detect_result=False)
        self.assertEqual((meta["status"], meta["backend"], len(fake.calls)), ("ok", "claude-cli", 1))

    def test_rechecks_executable_and_key(self):
        def resolve(name, env=None):
            return None if name == "claude" else os.path.join(os.path.abspath(os.sep), "fakebin", name)
        job = self.make_job(family="glm", chain=["claude-cli@glm", "codex-cli@glm"], job_id="g1")
        with mock.patch("ublib.detect.detect", side_effect=AssertionError("detect must not run")):
            meta, fake = run_job(job, [tl.PR(0, EVENTS)], "glm", [], resolve=resolve, detect_result=False)
        self.assertEqual((meta["status"], fake.calls), ("unavailable", []))
        self.assertIn("ZAI_API_KEY not set", meta["reason"])
        os.environ["ZAI_API_KEY"] = "zai-test-token-0123456789"
        job = self.make_job(family="glm", chain=["claude-cli@glm"], job_id="g2")
        with mock.patch("ublib.detect.detect", side_effect=AssertionError("detect must not run")):
            meta, fake = run_job(job, [tl.PR(0, SUCCESS)], "glm", [], resolve=resolve, detect_result=False)
        self.assertIn("claude not on PATH", meta["reason"])

    def test_bad_chain_is_a_job_error(self):
        with self.assertRaises(adapter.JobError):
            adapter.check_job(self.make_job(chain="claude-cli"))


class PrivacyLabelTests(tl.AdapterTestCase):
    """C8: meta.repo_read marks outputs of jobs that ran in the repository."""

    def test_repo_read(self):
        repo = os.path.join(self.tmp, "repo")
        os.makedirs(repo)
        self.write_run_json()
        job = self.make_job(family="claude", tools="read", cwd="repo", repo_root=repo)
        meta, _f = run_job(job, [tl.PR(0, SUCCESS)], "claude", ["claude-cli"])
        self.assertTrue(meta["repo_read"])
        meta, _f = run_job(self.make_job(family="claude", job_id="e1"), [tl.PR(0, SUCCESS)], "claude", ["claude-cli"])
        self.assertFalse(meta["repo_read"])


class StubLoaderTests(tl.AdapterTestCase):
    """The fake-mode responder lives in tests/harness; a release (no tests/) still answers PING."""

    def setUp(self):
        super(StubLoaderTests, self).setUp()
        os.environ["UB_FAKE_FAMILIES"] = "1"
        saved = sys.modules.pop(stub._MODULE, None)
        self.addCleanup(lambda: sys.modules.__setitem__(stub._MODULE, saved) if saved else
                        sys.modules.pop(stub._MODULE, None))

    def test_harness_answers_in_a_checkout(self):
        self.assertTrue(os.path.isfile(stub.HARNESS_STUBS))
        self.assertFalse(os.path.exists(os.path.join(tl.SCRIPTS, "ublib", "stubs.py")), "never shipped")
        meta = adapter.execute_job(self.make_job(family="gpt"))
        self.assertEqual((meta["status"], meta["backend"]), ("ok", "stub"))

    def test_release_without_harness(self):
        with mock.patch.object(stub, "HARNESS_STUBS", os.path.join(self.tmp, "missing", "stubs.py")):
            meta = adapter.execute_job(self.make_job(family="gpt", template="PING",
                                                     contract={"type": "text", "regex": "PONG", "min_chars": 1}))
            self.assertEqual(meta["status"], "ok")
            meta = adapter.execute_job(self.make_job(family="gpt", job_id="other"))
        self.assertEqual((meta["status"], meta["error_class"]), ("unavailable", "not_found"))
        self.assertIn("source checkout", meta["reason"])
        self.assertTrue(stub.HARNESS_STUBS.replace("\\", "/").endswith("tests/harness/stubs.py"))


if __name__ == "__main__":
    unittest.main()
