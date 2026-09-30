"""B2 adapter tests: detection, reclassification, provider gating, fake mode, host family, live preflight
(KIT_SPEC 4.8 detect shape, 5.5, 3.3 test seams). CLI probes are mocked at proc.resolve_exe / proc.run."""

import os
import shutil
import sys
import unittest
from unittest import mock

_KIT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(_KIT, "tests", "fixtures", "adapter"))

import adapter_testlib as tl  # noqa: E402
from ublib import detect, families, textio  # noqa: E402

HAVE_STUBS = os.path.isfile(os.path.join(tl.KIT, "tests", "harness", "stubs.py"))  # the fake-mode responder

VERSIONS = {"claude": "2.1.280 (Claude Code)\n", "codex": "codex-cli 0.156.1\n", "kimi": "kimi, version 2.0.2\n"}


def versions(overrides=None):
    table = dict(VERSIONS)
    table.update(overrides or {})

    def run(argv, cwd=None, env=None, stdin_bytes=None, timeout_s=None, **_kw):
        name = os.path.basename(argv[0]).split(".")[0]
        assert argv[1:] == ["--version"], argv
        assert timeout_s == 15
        return tl.PR(0, table.get(name, ""))
    return run


class DetectBase(tl.AdapterTestCase):
    def detect(self, present=("claude", "codex", "kimi"), vers=None, **kw):
        mapping = {n: os.path.join(self.tmp, "bin", n + (".cmd" if n == "codex" else ".exe")) for n in present}

        def resolve(name, env=None):
            return mapping.get(name)
        with mock.patch("ublib.proc.resolve_exe", side_effect=resolve), \
                mock.patch("ublib.proc.run", side_effect=versions(vers)):
            return detect.detect(families.load_families(), **kw)

    def kimi_login(self):
        os.makedirs(os.path.join(os.environ["KIMI_CODE_HOME"], "credentials"))

    def claude_settings(self, fixture):
        d = os.environ["CLAUDE_CONFIG_DIR"]
        os.makedirs(d, exist_ok=True)
        shutil.copy(tl.fixture_path("detect", fixture), os.path.join(d, "settings.json"))

    def codex_config(self, fixture):
        d = os.environ["CODEX_HOME"]
        os.makedirs(d, exist_ok=True)
        shutil.copy(tl.fixture_path("detect", fixture), os.path.join(d, "config.toml"))


class ShapeTests(DetectBase):
    def test_shape_and_native_chains(self):
        self.kimi_login()
        res = self.detect()
        for key in ("schema", "generated_at", "fake", "host", "clis", "keys", "families", "reclassified", "live"):
            self.assertIn(key, res)
        self.assertFalse(res["fake"])
        self.assertEqual(res["clis"]["claude"]["version"], "2.1.280")
        self.assertFalse(res["clis"]["claude"]["shim"])
        self.assertTrue(res["clis"]["codex"]["shim"])
        self.assertEqual(res["clis"]["kimi"]["version"], "2.0.2")
        self.assertFalse(res["clis"]["kimi"]["legacy"])
        self.assertEqual(sorted(res["keys"]), sorted(detect.KEY_NAMES))
        fams = res["families"]
        self.assertEqual(list(fams), ["claude", "gpt", "kimi", "glm"])
        self.assertEqual(fams["claude"]["chain"], ["claude-cli"])
        self.assertTrue(fams["claude"]["web"])
        self.assertEqual(fams["gpt"]["chain"], ["codex-cli"])
        self.assertEqual(fams["kimi"]["chain"], ["kimi-cli"])
        self.assertFalse(fams["kimi"]["web"])
        self.assertFalse(fams["glm"]["available"])
        self.assertIn("ZAI_API_KEY not set", fams["glm"]["notes"])
        for f, v in (("claude", "anthropic"), ("gpt", "openai"), ("kimi", "moonshot"), ("glm", "zhipu")):
            self.assertEqual(fams[f]["vendor"], v)
        self.assertEqual(res["reclassified"], [])
        self.assertEqual(res["live"], {})

    def test_missing_clis(self):
        res = self.detect(present=())
        self.assertFalse(res["families"]["claude"]["available"])
        self.assertIn("claude not on PATH", res["families"]["claude"]["notes"])
        self.assertIsNone(res["clis"]["codex"]["path"])

    def test_only_filters_families(self):
        res = self.detect(only=["gpt-alt"])
        self.assertEqual(list(res["families"]), ["gpt"])


class ReclassifyTests(DetectBase):
    def test_claude_settings_pointing_at_zai_is_glm(self):
        self.claude_settings("claude_settings_zai.json")
        res = self.detect()
        fams = res["families"]
        self.assertNotIn("claude-cli", fams["claude"]["chain"])
        self.assertFalse(fams["claude"]["available"])
        self.assertIn("claude-cli", fams["glm"]["chain"])
        self.assertTrue(fams["glm"]["available"])
        self.assertEqual(len(res["reclassified"]), 1)
        r = res["reclassified"][0]
        self.assertEqual((r["cli"], r["endpoint"], r["as"]), ("claude", "api.z.ai", "glm"))
        self.assertTrue(r["source"].endswith("settings.json"))

    def test_claude_settings_on_anthropic_stays_claude(self):
        self.claude_settings("claude_settings_anthropic.json")
        res = self.detect()
        self.assertEqual(res["families"]["claude"]["chain"], ["claude-cli"])
        self.assertEqual(res["reclassified"], [])

    def test_process_env_base_url_does_not_reclassify_cli(self):
        os.environ["ANTHROPIC_BASE_URL"] = "https://api.z.ai/api/anthropic"  # scrubbed for the child (5.3)
        res = self.detect()
        self.assertEqual(res["families"]["claude"]["chain"], ["claude-cli"])

    def test_codex_config_with_zai_provider_is_glm(self):
        self.codex_config("codex_config_zai.toml")
        res = self.detect()
        self.assertNotIn("codex-cli", res["families"]["gpt"]["chain"])
        self.assertIn("codex-cli", res["families"]["glm"]["chain"])
        self.assertEqual(res["reclassified"][0]["as"], "glm")
        self.assertEqual(res["reclassified"][0]["cli"], "codex")

    def test_codex_config_regex_fallback_without_tomllib(self):
        self.codex_config("codex_config_kimi.toml")
        with mock.patch.dict(sys.modules, {"tomllib": None}):
            fam, provider, base, _path = detect.codex_config_family()
        self.assertEqual((fam, provider, base), ("kimi", "kimi", "https://api.moonshot.ai/v1"))
        self.codex_config("codex_config_openai.toml")
        self.assertEqual(detect.codex_config_family()[0], "gpt")

    def test_endpoint_family_table(self):
        self.assertEqual(detect.endpoint_family(None), "claude")
        self.assertEqual(detect.endpoint_family("https://api.anthropic.com"), "claude")
        self.assertEqual(detect.endpoint_family("https://api.z.ai/api/anthropic"), "glm")
        self.assertEqual(detect.endpoint_family("https://open.bigmodel.cn/api/anthropic"), "glm")
        self.assertEqual(detect.endpoint_family("https://api.moonshot.ai/anthropic"), "kimi")
        self.assertEqual(detect.endpoint_family("https://api.kimi.com/coding/"), "kimi")
        self.assertEqual(detect.endpoint_family("https://proxy.example.com/v1"), "custom:proxy.example.com")


class KimiTests(DetectBase):
    def test_kimi_1x_is_legacy_unavailable(self):
        self.kimi_login()
        res = self.detect(vers={"kimi": "kimi, version 1.9.4\n"})
        self.assertTrue(res["clis"]["kimi"]["legacy"])
        self.assertFalse(res["families"]["kimi"]["available"])
        self.assertIn(detect.LEGACY_KIMI_NOTE, res["families"]["kimi"]["notes"])
        self.assertIn("kimi migrate", detect.LEGACY_KIMI_NOTE)

    def test_kimi_without_login(self):
        res = self.detect()
        self.assertFalse(res["families"]["kimi"]["available"])
        self.assertIn("run: kimi login", res["families"]["kimi"]["notes"])
        os.environ["KIMI_MODEL_NAME"] = "kimi-k3"
        res = self.detect()  # KIMI_MODEL_* never reach a worker unless env_model is on (5.3): still no login
        self.assertFalse(res["families"]["kimi"]["available"])
        self.write_families_override({"backends": {"kimi-cli": {"env_model": True}}})
        res = self.detect()
        self.assertTrue(res["families"]["kimi"]["available"])

    def test_kimi_code_configured_for_glm_is_unavailable(self):
        self.kimi_login()
        home = os.environ.get("KIMI_CODE_HOME") or os.path.join(os.path.expanduser("~"), ".kimi-code")
        textio.write_text_atomic(os.path.join(home, "config.toml"),
                                 'default_model = "g"\n[models.g]\nprovider = "z"\n'
                                 '[providers.z]\nbase_url = "https://api.z.ai/api/anthropic"\n')
        res = self.detect()
        self.assertFalse(res["families"]["kimi"]["available"])
        self.assertIn(detect.KIMI_GLM_NOTE, res["families"]["kimi"]["notes"])


class CodexLauncherHomeTests(DetectBase):
    def test_gpt_survives_a_codex_glm_launcher_home(self):
        self.kimi_login()
        glm_home = os.path.join(os.environ["UB_HOME"], "codex-homes", "glm")
        textio.write_text_atomic(os.path.join(glm_home, "config.toml"),
                                 'model_provider = "zai"\n[model_providers.zai]\nbase_url = "https://api.z.ai/api/v1"\n')
        os.environ["UB_HOST"] = "codex"
        os.environ["UB_HOST_FAMILY"] = "glm"
        os.environ["CODEX_HOME"] = glm_home
        os.environ["UB_USER_CODEX_HOME"] = ""
        res = self.detect()
        self.assertEqual(res["host"]["family"], "glm")
        self.assertTrue(res["families"]["gpt"]["available"], res["families"]["gpt"])
        self.assertEqual(res["families"]["gpt"]["chain"][0], "codex-cli")

    def test_child_env_never_adds_back_a_ub_codex_home(self):
        from ublib import backends
        glm_home = os.path.join(os.environ["UB_HOME"], "codex-homes", "glm")
        ctx = backends.CallContext(btype="codex-cli", bcfg={"type": "codex-cli"}, ub_home=os.environ["UB_HOME"],
                                   base_env={"CODEX_HOME": glm_home, "UB_USER_CODEX_HOME": "", "PATH": "x"})
        self.assertNotIn("CODEX_HOME", backends.child_env(ctx))
        ctx.base_env = {"CODEX_HOME": glm_home, "UB_USER_CODEX_HOME": "/users/me/.codex-work", "PATH": "x"}
        self.assertEqual(backends.child_env(ctx)["CODEX_HOME"], "/users/me/.codex-work")


class HttpGuardTests(DetectBase):
    def test_anthropic_http_to_zai_with_plan_key_is_refused(self):
        from ublib import adapter
        self.write_families_override({"backends": {"anthropic-http": {
            "url": "https://api.z.ai/api/anthropic/v1/messages", "key_env": "ZAI_API_KEY"}}})
        cfg = families.load_families()
        self.assertIsNotNone(adapter.backend_policy_check(cfg, "anthropic-http", "claude"))

    def test_web_probe_reading(self):
        self.assertTrue(detect.web_probe_passed("https://www.python.org/"))
        self.assertFalse(detect.web_probe_passed("NO WEB ACCESS"))
        self.assertFalse(detect.web_probe_passed("I cannot browse the web, but https://www.python.org is it"))
        self.assertFalse(detect.web_probe_passed("PONG"))


class ProviderGatingTests(DetectBase):
    def test_glm_backends_gated_by_key_and_codex_home(self):
        self.kimi_login()
        os.environ["ZAI_API_KEY"] = "zai-test-key-0123456789"
        res = self.detect()
        self.assertTrue(res["keys"]["ZAI_API_KEY"])
        self.assertEqual(res["families"]["glm"]["chain"], ["claude-cli@glm"])
        self.assertFalse(res["families"]["glm"]["web"])
        os.makedirs(os.path.join(os.environ["UB_HOME"], "codex-homes", "glm"))
        res = self.detect()
        self.assertEqual(res["families"]["glm"]["chain"], ["claude-cli@glm", "codex-cli@glm"])
        res = self.detect(present=("codex",))
        self.assertEqual(res["families"]["glm"]["chain"], ["codex-cli@glm"])

    def test_kimi_provider_backends(self):
        os.environ["KIMI_CODE_API_KEY"] = "kimi-code-key-0123456789"
        res = self.detect(present=("claude",))
        self.assertEqual(res["families"]["kimi"]["chain"], ["claude-cli@kimi-code"])

    def test_http_backends_need_enable_key_and_model(self):
        os.environ["OPENAI_API_KEY"] = "sk-openai-0123456789"
        res = self.detect(present=())
        self.assertFalse(res["families"]["gpt"]["available"])
        self.write_families_override({"backends": {"openai-http": {"model": "gpt-test"}}})
        res = self.detect(present=())
        self.assertEqual(res["families"]["gpt"]["chain"], ["openai-http"])
        self.assertFalse(res["families"]["gpt"]["web"])

    def test_strict_glm_drops_scripted_backends(self):
        self.write_families_override({"families": {"glm": {"allow_scripted_plan_use": False}}})
        os.environ["ZAI_API_KEY"] = "zai-test-key-0123456789"
        res = self.detect()
        self.assertEqual(res["families"]["glm"]["chain"], [])
        os.environ["UB_HOST_FAMILY"] = "glm"
        res = self.detect()
        self.assertEqual(res["families"]["glm"]["chain"], ["host"])


class HostTests(DetectBase):
    def test_host_family_order(self):
        os.environ["UB_HOST"] = "codex"
        self.assertEqual(self.detect()["host"], {"agent": "codex", "family": "gpt", "source": "default"})
        os.environ["UB_HOST"] = "claude-code"
        self.claude_settings("claude_settings_zai.json")
        self.assertEqual(self.detect()["host"], {"agent": "claude-code", "family": "glm", "source": "endpoint"})
        os.environ["UB_HOST_FAMILY"] = "kimi"
        self.assertEqual(self.detect()["host"]["family"], "kimi")
        self.assertEqual(self.detect()["host"]["source"], "env")
        os.environ.pop("UB_HOST_FAMILY")
        os.environ["UB_HOST"] = "zcode"
        self.assertEqual(self.detect()["host"]["family"], "glm")
        os.environ["UB_HOST"] = "codex"
        self.codex_config("codex_config_kimi.toml")
        self.assertEqual(self.detect()["host"], {"agent": "codex", "family": "kimi", "source": "endpoint"})


class FakeModeTests(DetectBase):
    def test_fake_families(self):
        os.environ["UB_FAKE_FAMILIES"] = "1"
        os.environ["UB_FAKE_DISABLE"] = "kimi"
        os.environ["UB_FAKE_HOST_BACKEND"] = "glm"
        res = self.detect(present=())
        self.assertTrue(res["fake"])
        fams = res["families"]
        self.assertEqual(fams["claude"]["chain"], ["stub"])
        self.assertTrue(fams["claude"]["web"])
        self.assertEqual(fams["gpt"]["chain"], ["stub"])
        self.assertFalse(fams["kimi"]["available"])
        self.assertEqual(fams["glm"]["chain"], ["host"])
        cfg = families.load_families()
        self.assertEqual(families.resolve_chain(cfg, "claude-alt", None), ["stub"])
        self.assertEqual(families.resolve_chain(cfg, "kimi", None), [])
        self.assertEqual(families.resolve_chain(cfg, "glm", None), ["host"])
        self.assertEqual(families.resolve_chain(cfg, "host", None), ["host"])

    @unittest.skipUnless(HAVE_STUBS, "tests/harness/stubs.py not present")
    def test_live_preflight_in_fake_mode(self):
        os.environ["UB_FAKE_FAMILIES"] = "1"
        os.environ["UB_HOST"] = "claude-code"
        os.environ["UB_STUB_FAIL"] = "^ping-(gpt|claude)$"
        res = self.detect(present=(), live=True, only=["claude", "gpt", "kimi"])
        self.assertTrue(res["live"]["kimi"].startswith("PONG ok"))
        self.assertTrue(res["live"]["gpt"].startswith("FAIL"))
        self.assertFalse(res["families"]["gpt"]["available"])
        # the failing host family falls back to HOST_BATCH  # [U-14]
        self.assertEqual(res["families"]["claude"]["chain"], ["host"])
        self.assertTrue(res["families"]["claude"]["available"])
        leftovers = [n for n in os.listdir(os.path.join(os.environ["UB_HOME"], "tmp")) if n.startswith("ping-")]
        self.assertEqual(leftovers, [])


class ConfigTests(tl.AdapterTestCase):
    def test_load_and_merge(self):
        cfg = families.load_families()
        self.assertEqual(cfg["order"], ["claude", "gpt", "kimi", "glm"])
        self.write_families_override({"region": "cn", "families": {"claude": {"limit": 1}},
                                      "backends": {"kimi-cli": {"web": True}}})
        cfg = families.load_families()
        self.assertEqual(cfg["region"], "cn")
        self.assertEqual(cfg["families"]["claude"]["limit"], 1)
        self.assertEqual(cfg["families"]["claude"]["alt_model"], "sonnet")
        self.assertTrue(cfg["backends"]["kimi-cli"]["web"])
        self.assertEqual(cfg["backends"]["kimi-cli"]["min_version"], "2.0.0")
        textio.write_text_atomic(os.path.join(os.environ["UB_HOME"], "families.json"), "{broken")
        cfg = families.load_families()
        self.assertEqual(cfg["region"], "global")
        self.assertTrue(cfg["_warnings"])

    def test_every_referenced_backend_exists(self):
        cfg = families.load_families()
        for f, fc in cfg["families"].items():
            for b in fc["backends"]:
                self.assertIn(b, cfg["backends"], (f, b))
            for p in [cfg["backends"][b].get("provider") for b in fc["backends"]]:
                if p:
                    self.assertIn(p, cfg["providers"])

    def test_provider_settings_env(self):
        cfg = families.load_families()
        env = families.provider_settings_env(cfg, "glm")
        self.assertEqual(env["ANTHROPIC_BASE_URL"], "https://api.z.ai/api/anthropic")
        self.assertEqual(env["ANTHROPIC_MODEL"], "glm-5.3[1m]")
        for k in ("ANTHROPIC_DEFAULT_OPUS_MODEL", "ANTHROPIC_DEFAULT_SONNET_MODEL", "ANTHROPIC_DEFAULT_FABLE_MODEL",
                  "CLAUDE_CODE_SUBAGENT_MODEL"):
            self.assertEqual(env[k], "glm-5.3[1m]")
        self.assertEqual(env["ANTHROPIC_DEFAULT_HAIKU_MODEL"], "glm-5.3-flash[1m]")
        self.assertEqual(env["CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"], "1")
        self.assertNotIn("ANTHROPIC_AUTH_TOKEN", env)
        self.assertEqual(families.provider_settings_env(cfg, "glm", "fast", "cn")["ANTHROPIC_BASE_URL"],
                         "https://open.bigmodel.cn/api/anthropic")
        self.assertEqual(families.provider_settings_env(cfg, "glm", "fast")["ANTHROPIC_MODEL"], "glm-5.3-flash[1m]")
        # no cn Anthropic endpoint for Moonshot: falls back to global  # [U-22]
        self.assertEqual(families.provider_settings_env(cfg, "kimi", region="cn")["ANTHROPIC_BASE_URL"],
                         "https://api.moonshot.ai/anthropic")
        kc = families.provider_settings_env(cfg, "kimi-code")
        self.assertEqual(kc["CLAUDE_CODE_MAX_CONTEXT_TOKENS"], "262144")

    def test_labels_and_paths(self):
        self.assertEqual(families.split_label("gpt-alt"), ("gpt", True))
        self.assertEqual(families.vendor_of("kimi-alt"), "moonshot")
        self.assertEqual(families.vendor_of("human"), "human")
        home = os.environ["UB_HOME"]
        self.assertEqual(families.expand_path("~/.ultimate-brainstorm/codex-homes/glm"),
                         os.path.join(os.path.abspath(home), "codex-homes", "glm"))
        self.assertEqual(families.timeout_for(families.load_families(), "researcher"), 600)
        self.assertEqual(families.timeout_for(families.load_families(), "unknown-kind"), 420)

    def test_version_tuple(self):
        self.assertEqual(detect.version_tuple("2.1.280 (Claude Code)"), (2, 1, 280))
        self.assertEqual(detect.version_tuple("codex-cli 0.156"), (0, 156, 0))
        self.assertIsNone(detect.version_tuple("no version"))


if __name__ == "__main__":
    unittest.main()
