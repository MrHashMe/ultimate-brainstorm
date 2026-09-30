"""J: detection and backend follow-ups of the round-4 review (JF-backends-detect).

- A config.toml nesting an array or inline table about 1000 levels deep made detection (so `ub init`, a re-detection
  and `family.py detect`) crash with RecursionError: tomllib gives up on it and the reading without tomllib recursed
  once per level. A value nested deeper than the reader's limit is now an unread statement. Without tomllib a
  \\UXXXXXXXX escape in a quoted name was kept as written, so an MCP server named that way was never switched off.
- The note for a missing Kimi Codex home told the user to run `install.py setup-glm --codex`.
- Kimi Code configured for another vendor than Moonshot (Anthropic, OpenAI, any other host) stayed the kit's kimi
  family, only a GLM endpoint was caught, and only for its default model; a job carrying the driver's chain (C13)
  started kimi-cli after its config had been switched to Z.ai during the run.
- Windows: an HTTP backend's key_env written in another letter case than the variable was found by detection but
  reported "not set" by the worker.
No real CLI and no network: the CLIs are mocked at ublib.proc.run and the HTTP request at post_json."""

import os
import sys
import unittest
from unittest import mock

_KIT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(_KIT, "tests", "fixtures", "adapter"))

import adapter_testlib as tl  # noqa: E402
from ublib import adapter, detect, families, textio  # noqa: E402
from ublib.backends import CallContext, http_openai  # noqa: E402

NO_TOMLLIB = {"tomllib": None}  # what Python 3.9 / 3.10 see
VERSIONS = {"claude": "2.1.280 (Claude Code)\n", "codex": "codex-cli 0.160.0\n", "kimi": "kimi, version 2.0.2\n"}
KIMI_STRING = tl.fixture_bytes("kimi", "string.jsonl")
KEY = "sk-router-test-key-0123456789abcdef"


def detect_with(present=("claude", "codex", "kimi")):
    """detect.detect() with these CLIs on PATH (fake paths, mocked --version)."""
    mapping = {n: os.path.join(os.sep, "fakebin", n + ".exe") for n in present}

    def run(argv, **_kw):
        return tl.PR(0, VERSIONS.get(os.path.basename(argv[0]).split(".")[0], ""))
    with mock.patch("ublib.proc.resolve_exe", side_effect=lambda name, env=None: mapping.get(name)), \
            mock.patch("ublib.proc.run", side_effect=run):
        return detect.detect(families.load_families())


class TomlDepthTests(tl.AdapterTestCase):
    """NEW-I-HE-backends-worker-1: a deeply nested value is an unread statement, never a RecursionError."""

    def config(self, text):
        textio.write_text_atomic(os.path.join(self.tmp, "config.toml"), text)

    def deep(self, value):
        return '[mcp_servers.alpha]\ncommand = "x"\n[tools]\nx = %s\n[mcp_servers.beta]\ncommand = "y"\n' % value

    def test_a_deeply_nested_value_is_unread_and_the_rest_still_read(self):
        for label, value in (("array", "[" * 2000 + "]" * 2000), ("inline table", "{a = " * 2000 + "1" + "}" * 2000)):
            self.config(self.deep(value))
            for modules in ({}, NO_TOMLLIB):  # tomllib (3.11+) gives up on it too: the same reading follows
                with mock.patch.dict(sys.modules, modules):
                    self.assertEqual(detect.codex_mcp_unread(self.tmp), [4], label)
                    self.assertEqual(detect.codex_mcp_servers(self.tmp), [], label)
                    self.assertEqual(detect.codex_mcp_servers(self.tmp, unsafe=True), [], label)
                    data = detect._parse_toml(textio.read_text(os.path.join(self.tmp, "config.toml")))
                    self.assertEqual(sorted(data["mcp_servers"]), ["alpha", "beta"], label)

    def test_nesting_up_to_the_limit_is_still_read(self):
        text = "x = %s1%s\n" % ("[" * detect._TOML_MAX_DEPTH, "]" * detect._TOML_MAX_DEPTH)
        unread = []
        with mock.patch.dict(sys.modules, NO_TOMLLIB):
            data = detect._parse_toml(text, unread)
        self.assertEqual(unread, [])
        value = data["x"]
        for _n in range(detect._TOML_MAX_DEPTH):
            self.assertIsInstance(value, list)
            value = value[0]
        self.assertEqual(value, "1")
        unread = []
        with mock.patch.dict(sys.modules, NO_TOMLLIB):
            detect._parse_toml("y = 2\nx = [%s]\n" % text[4:-1], unread)
        self.assertEqual(unread, [2])

    def test_detection_survives_a_deeply_nested_codex_config(self):
        home = os.environ["CODEX_HOME"]
        textio.write_text_atomic(os.path.join(home, "config.toml"),
                                 'model = "gpt-5.5"\n[tools]\nx = %s\n' % ("[" * 2000 + "]" * 2000))
        self.assertEqual(detect.codex_config_family()[0], "gpt")
        gpt = detect_with()["families"]["gpt"]
        self.assertEqual(gpt["chain"], ["codex-cli"])
        self.assertTrue(any("could not read line 3" in n for n in gpt["notes"]), gpt["notes"])


class TomlEscapeTests(tl.AdapterTestCase):
    """NEW-I-HE-backends-worker-1: \\U escapes read without tomllib as tomllib reads them."""

    TEXT = 'a = "\\U0001F600|\\\\U00000041|\\U00000022|\\u00e9"\n'
    VALUE = "\U0001F600|\\U00000041|\"|\u00e9"

    def test_a_u_escaped_server_name_is_switched_off_without_tomllib(self):
        textio.write_text_atomic(os.path.join(self.tmp, "config.toml"),
                                 '[mcp_servers."\\U00000061lpha"]\ncommand = "node"\n')
        with mock.patch.dict(sys.modules, NO_TOMLLIB):
            self.assertEqual(detect.codex_mcp_servers(self.tmp), ["alpha"])
            self.assertEqual(detect.codex_mcp_servers(self.tmp, unsafe=True), [])

    def test_u_escapes_decode_like_tomllib(self):
        with mock.patch.dict(sys.modules, NO_TOMLLIB):
            self.assertEqual(detect._parse_toml(self.TEXT), {"a": self.VALUE})
        try:
            import tomllib
        except ImportError:
            return
        self.assertEqual(tomllib.loads(self.TEXT), {"a": self.VALUE})


class CodexHomeNoteTests(tl.AdapterTestCase):
    """[CONFIRMED P3] the note for a missing Codex home names the setup command of that backend's provider."""

    CLIS = {"codex": {"path": "/fakebin/codex.exe", "version": "0.160.0", "shim": False}}

    def status(self, bid):
        return detect._backend_status(families.load_families(), bid, self.CLIS, os.environ, "claude", "gpt", False)

    def test_each_provider_home_names_its_own_setup_command(self):
        os.environ.update({"KIMI_API_KEY": "kimi-test-key-0123456789", "ZAI_API_KEY": "zai-test-key-0123456789"})
        self.assertEqual(self.status("codex-cli@kimi"),
                         (False, None, "codex home missing: run install.py setup-kimi --codex"))
        self.assertEqual(self.status("codex-cli@glm"),
                         (False, None, "codex home missing: run install.py setup-glm --codex"))
        home = os.path.join(self.tmp, "proxy-home")
        self.write_families_override({"backends": {"codex-cli@proxy": {"type": "codex-cli", "codex_home": home}}})
        self.assertEqual(self.status("codex-cli@proxy"),
                         (False, None, "codex home %s missing" % textio.to_posix(os.path.abspath(home))))

    def test_the_kimi_family_notes_carry_the_kimi_command(self):
        os.environ["KIMI_API_KEY"] = "kimi-test-key-0123456789"
        kimi = detect_with(present=("codex",))["families"]["kimi"]
        self.assertFalse(kimi["available"])
        self.assertIn("codex home missing: run install.py setup-kimi --codex", kimi["notes"])
        self.assertFalse(any("setup-glm" in n for n in kimi["notes"]), kimi["notes"])


def kimi_config(url, extra=""):
    """A Kimi Code config.toml whose default model "m" is served at url (extra: more tables)."""
    return ('default_model = "m"\n[models.m]\nprovider = "p"\nmodel = "x"\n'
            '[providers.p]\ntype = "openai_legacy"\nbase_url = "%s"\napi_key = "k-test"\n%s' % (url, extra))


class KimiBase(tl.AdapterTestCase):
    def kimi_setup(self, config=None):
        home = os.environ["KIMI_CODE_HOME"]
        os.makedirs(os.path.join(home, "credentials"), exist_ok=True)
        if config is not None:
            textio.write_text_atomic(os.path.join(home, "config.toml"), config)

    def kimi(self):
        res = detect_with()
        for f, info in res["families"].items():
            if f != "kimi":
                self.assertNotIn("kimi-cli", info["chain"], f)  # never re-seated in another family
        return res["families"]["kimi"]


class KimiForeignDetectTests(KimiBase):
    """[CONFIRMED P2] Kimi Code configured for another vendor: kimi-cli is unavailable, never the kimi family."""

    def test_another_vendors_endpoint_makes_kimi_cli_unavailable(self):
        for url, served, host in (("https://api.openai.com/v1", "gpt", "api.openai.com"),
                                  ("https://api.anthropic.com", "claude", "api.anthropic.com"),
                                  ("https://api.deepseek.com/v1", "custom:api.deepseek.com", "api.deepseek.com")):
            self.kimi_setup(kimi_config(url))
            kimi = self.kimi()
            self.assertFalse(kimi["available"], url)
            self.assertIn(detect.KIMI_FOREIGN_NOTE % (served, host), kimi["notes"])
        self.kimi_setup(kimi_config("https://api.z.ai/api/anthropic"))
        self.assertIn(detect.KIMI_GLM_NOTE, self.kimi()["notes"])

    def test_kimi_endpoints_and_unknown_ones_stay_available(self):
        self.kimi_setup()
        self.assertEqual(self.kimi()["chain"], ["kimi-cli"])  # no config.toml
        for url in ("https://api.moonshot.ai/v1", "https://api.kimi.com/coding/v1"):
            self.kimi_setup(kimi_config(url))
            self.assertEqual(self.kimi()["chain"], ["kimi-cli"], url)
        # a provider without base_url uses its type's own endpoint: another provider's URL is never taken for it
        self.kimi_setup('default_model = "m"\n[models.m]\nprovider = "kimi"\n[providers.kimi]\ntype = "kimi"\n'
                        '[models.g]\nprovider = "zai"\n[providers.zai]\nbase_url = "https://api.z.ai/api/anthropic"\n')
        self.assertEqual(self.kimi()["chain"], ["kimi-cli"])

    def test_a_file_without_model_tables_is_read_by_its_base_url(self):
        self.kimi_setup('base_url = "https://api.openai.com/v1"\n')
        self.assertIn(detect.KIMI_FOREIGN_NOTE % ("gpt", "api.openai.com"), self.kimi()["notes"])

    def test_every_model_the_backend_can_pass_is_checked(self):
        extra = ('[models.g]\nprovider = "zai"\n[providers.zai]\nbase_url = "https://api.z.ai/api/anthropic"\n'
                 '[models.o]\nprovider = "oai"\n[providers.oai]\nbase_url = "https://api.openai.com/v1"\n')
        self.kimi_setup(kimi_config("https://api.moonshot.ai/v1", extra=extra))
        self.assertEqual(self.kimi()["chain"], ["kimi-cli"])
        for override, note in (({"backends": {"kimi-cli": {"model": "g"}}}, detect.KIMI_GLM_NOTE),
                               ({"backends": {"kimi-cli": {"fast_model": "g"}}}, detect.KIMI_GLM_NOTE),
                               ({"families": {"kimi": {"alt_model": "o"}}},
                                detect.KIMI_FOREIGN_NOTE % ("gpt", "api.openai.com"))):
            self.write_families_override(override)
            kimi = self.kimi()
            self.assertFalse(kimi["available"], override)
            self.assertIn(note, kimi["notes"])

    def test_env_model_takes_the_endpoint_from_kimi_model_base_url(self):
        self.kimi_setup(kimi_config("https://api.moonshot.ai/v1"))
        self.write_families_override({"backends": {"kimi-cli": {"env_model": True}}})
        os.environ.update({"KIMI_MODEL_NAME": "x", "KIMI_MODEL_BASE_URL": "https://api.openai.com/v1"})
        self.assertIn(detect.KIMI_FOREIGN_NOTE % ("gpt", "api.openai.com"), self.kimi()["notes"])
        os.environ["KIMI_MODEL_BASE_URL"] = "https://api.moonshot.ai/v1"
        self.kimi_setup(kimi_config("https://api.openai.com/v1"))
        self.assertEqual(self.kimi()["chain"], ["kimi-cli"])


class KimiCallTimeTests(KimiBase):
    """[CONFIRMED P2] a job carrying the driver's chain re-checks Kimi Code's config before the CLI starts."""

    def run_job(self, job_id, override=None):
        if override is not None:
            self.write_families_override(override)
        job = self.make_job(family="kimi", job_id=job_id, chain=["kimi-cli"])
        fake = tl.FakeRun([tl.PR(0, KIMI_STRING)])
        with mock.patch("ublib.proc.run", side_effect=fake), \
                mock.patch("ublib.proc.resolve_exe", side_effect=tl.fake_resolve()):
            meta = adapter.execute_job(job)
        return meta, fake.calls

    def test_a_config_switched_to_another_family_never_starts_the_cli(self):
        for n, (url, why) in enumerate((("https://api.z.ai/api/anthropic", "(not a GLM-supported tool)"),
                                        ("https://api.openai.com/v1", "configured for gpt (api.openai.com)"))):
            self.kimi_setup(kimi_config(url))
            meta, calls = self.run_job("4.2-K%d" % n)
            self.assertEqual((meta["status"], meta["error_class"], meta["requests"]), ("unavailable", "config", 0))
            self.assertIn(why, meta["reason"])
            self.assertIn("re-run detection (family.py detect)", meta["reason"])
            self.assertEqual(calls, [])
            self.assertEqual(adapter.exit_code_for(meta["status"]), 3)

    def test_the_model_of_the_call_decides(self):
        self.kimi_setup(kimi_config("https://api.moonshot.ai/v1", extra='[models.g]\nprovider = "zai"\n'
                                    '[providers.zai]\nbase_url = "https://api.z.ai/api/anthropic"\n'))
        meta, calls = self.run_job("4.2-OK")
        self.assertEqual(meta["status"], "ok", meta["reason"])
        self.assertEqual(len(calls), 1)
        meta, calls = self.run_job("4.2-G", {"backends": {"kimi-cli": {"model": "g"}}})
        self.assertEqual((meta["status"], meta["error_class"]), ("unavailable", "config"))
        self.assertIn(detect.KIMI_GLM_NOTE, meta["reason"])
        self.assertEqual(calls, [])


class KeyEnvLookupTests(tl.AdapterTestCase):
    """[CONFIRMED P3] the worker looks a key_env up as the platform does (any letter case on Windows)."""

    BCFG = {"type": "openai-chat-http", "url": "https://router.example.test/v1/chat/completions", "model": "m",
            "enabled": True, "key_env": "my_router_key"}

    def test_precheck_ignores_the_letter_case_where_the_platform_does(self):
        ctx = CallContext(backend_id="router-http", bcfg=self.BCFG, base_env={"MY_ROUTER_KEY": KEY})
        with mock.patch("ublib.proc.IS_WINDOWS", True):
            self.assertEqual(http_openai.precheck(ctx), (KEY, "m", None))
        with mock.patch("ublib.proc.IS_WINDOWS", False):  # POSIX names are case-sensitive: not this variable
            _key, _model, fail = http_openai.precheck(ctx)
        self.assertEqual((fail["status"], fail["error"]), ("unavailable", "my_router_key is not set"))


@unittest.skipUnless(os.name == "nt", "environment variable names ignore case only on Windows")
class KeyEnvCaseWindowsTests(tl.AdapterTestCase):
    """[CONFIRMED P3] Windows: detection seats an HTTP backend whose key_env is written in another letter case, and
    the worker now finds the key too (it said "<key_env> is not set" and sent nothing)."""

    ANSWERS = {"openai-chat-http": ("http_openai", tl.fixture_bytes("http", "openai_ok.json"), "Authorization",
                                    "Bearer " + KEY),
               "anthropic-http": ("http_anthropic", tl.fixture_bytes("http", "anthropic_ok.json"), "x-api-key", KEY)}

    def test_http_backends_find_a_key_env_in_another_letter_case(self):
        for btype, (module, answer, header, value) in sorted(self.ANSWERS.items()):
            for key_env, set_as in (("my_router_key", "MY_ROUTER_KEY"), ("My_Router_Key", "My_Router_Key")):
                label = "%s %s" % (btype, key_env)
                self.write_families_override({"backends": {"router-http": {
                    "type": btype, "url": "https://router.example.test/v1", "model": "m", "enabled": True,
                    "key_env": key_env}}})
                os.environ[set_as] = KEY
                ok = detect._backend_status(families.load_families(), "router-http", {}, os.environ, "claude", "gpt",
                                            False)[0]
                self.assertTrue(ok, label)
                sent = []

                def post(url, headers, payload, timeout_s):
                    sent.append(headers)
                    return 200, answer, None, 1, None
                job = self.make_job(family="gpt", job_id="4.2-%s-%s" % (module, key_env), chain=["router-http"])
                with mock.patch("ublib.backends.%s.post_json" % module, side_effect=post):
                    meta = adapter.execute_job(job)
                self.assertEqual((meta["status"], meta["requests"]), ("ok", 1), (label, meta["reason"]))
                self.assertEqual(sent[0][header], value, label)
                self.assertNotIn(KEY, self.all_output_text())
                del os.environ[set_as]


if __name__ == "__main__":
    unittest.main()
