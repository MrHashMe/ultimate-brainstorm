"""Worker checks for provider backends and Kimi Code endpoints (KIT_SPEC 4.9, 5.5).

- families.provider_settings_env keeps ANTHROPIC_BASE_URL only when it is an http(s) URL. A blank or non-URL value
  is no URL, so detection, the worker and the launchers all refuse the provider.
- A families.json provider entry of the wrong shape leaves that provider unavailable, with a note naming the key.
  Detection does not crash, the worker returns unavailable (config), and `family.py explain` reports it.
- kimi-cli reads a provider's endpoint the way Kimi Code does: first the table's base_url, then the `*_BASE_URL` key of
  its env sub-table, then the type's default. With env_model, KIMI_MODEL_NAME without KIMI_MODEL_BASE_URL uses the
  default endpoint of KIMI_MODEL_PROVIDER_TYPE.

Process calls are mocked at ublib.proc.run. No real CLI and no network are used."""

import json
import os
import sys
import unittest
from unittest import mock

_KIT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(_KIT, "tests", "fixtures", "adapter"))
sys.path.insert(0, os.path.join(_KIT, "profiles"))

import adapter_testlib as tl  # noqa: E402
import family  # noqa: E402  (the scripts folder is on sys.path through adapter_testlib)
import launch  # noqa: E402
from ublib import adapter, detect, families, textio  # noqa: E402

VERSIONS = {"claude": "2.1.280 (Claude Code)\n", "codex": "codex-cli 0.160.0\n", "kimi": "kimi, version 2.0.2\n"}
TOKEN = "zai-test-token-0123456789abcdef"
NO_URL_NOTE = "provider glm has no base_url in families config"
BLANK_OR_NOT_HTTP = {
    "whitespace": {"providers": {"glm": {"base_url": "   "}}},
    "global whitespace": {"providers": {"glm": {"base_url": {"global": " "}}}},
    "env whitespace over a good base_url": {"providers": {"glm": {"env": {"ANTHROPIC_BASE_URL": "  "}}}},
    "not http": {"providers": {"glm": {"base_url": "ftp://api.z.ai/api/anthropic"}}},
    "no scheme": {"providers": {"glm": {"base_url": "api.z.ai/api/anthropic"}}},
}
WRONG_SHAPE = {
    "base_url list": ({"providers": {"glm": {"base_url": ["https://api.z.ai/api/anthropic"]}}}, "base_url"),
    "base_url number": ({"providers": {"glm": {"base_url": 7}}}, "base_url"),
    "models list": ({"providers": {"glm": {"models": ["glm-5.3"]}}}, "models"),
    "env list": ({"providers": {"glm": {"env": ["A=1"]}}}, "env"),
    "token_env number": ({"providers": {"glm": {"token_env": 5}}}, "token_env"),
}


class Base(tl.AdapterTestCase):
    def detect(self):
        def run(argv, **_kw):
            return tl.PR(0, VERSIONS.get(os.path.basename(argv[0]).split(".")[0], ""))
        with mock.patch("ublib.proc.resolve_exe", side_effect=lambda name, env=None: tl.fake_resolve()(name)), \
                mock.patch("ublib.proc.run", side_effect=run):
            return detect.detect(families.load_families())

    def run_glm_job(self, job_id):
        """A job on the driver-resolved chain claude-cli@glm (seated before the config changed)."""
        job = self.make_job(family="glm", job_id=job_id)
        fake = tl.FakeRun([tl.PR(0, tl.fixture_bytes("claude", "success.json"))])
        det = tl.chain_detect({"glm": ["claude-cli@glm"]}, host_family="claude")
        with mock.patch("ublib.proc.run", side_effect=fake), \
                mock.patch("ublib.proc.resolve_exe", side_effect=tl.fake_resolve()):
            meta = adapter.execute_job(job, detect_result=det)
        return meta, fake


class BlankProviderUrlTests(Base):
    def test_a_blank_or_non_http_url_is_no_url(self):
        os.environ["ZAI_API_KEY"] = TOKEN
        for n, (label, override) in enumerate(BLANK_OR_NOT_HTTP.items()):
            with self.subTest(label):
                self.write_families_override(override)
                cfg = families.load_families()
                self.assertNotIn("ANTHROPIC_BASE_URL", families.provider_settings_env(cfg, "glm"))
                glm = self.detect()["families"]["glm"]
                self.assertNotIn("claude-cli@glm", glm["chain"])
                self.assertIn(NO_URL_NOTE, glm["notes"])
                meta, fake = self.run_glm_job("4.2-B%d" % (n + 1))
                self.assertEqual(meta["status"], "unavailable")
                self.assertEqual(fake.calls, [])  # claude never starts with the token toward api.anthropic.com
                self.assertNotIn(TOKEN, self.all_output_text())
                with self.assertRaises(launch.LaunchError) as cm:
                    launch.provider_settings_env(cfg, "glm")
                self.assertEqual(cm.exception.code, 2)

    def test_a_url_with_spaces_around_it_is_stripped(self):
        self.write_families_override({"providers": {"glm": {"base_url": "  https://api.z.ai/api/anthropic \n"}}})
        env = families.provider_settings_env(families.load_families(), "glm")
        self.assertEqual(env["ANTHROPIC_BASE_URL"], "https://api.z.ai/api/anthropic")

    def test_the_default_provider_keeps_its_url(self):
        os.environ["ZAI_API_KEY"] = TOKEN
        self.assertIn("claude-cli@glm", self.detect()["families"]["glm"]["chain"])


class WrongShapeProviderTests(Base):
    def test_detection_refuses_only_that_provider(self):
        os.environ["ZAI_API_KEY"] = TOKEN
        for label, (override, key) in WRONG_SHAPE.items():
            with self.subTest(label):
                self.write_families_override(override)
                fams = self.detect()["families"]  # never raises
                self.assertNotIn("claude-cli@glm", fams["glm"]["chain"])
                note = "providers.glm.%s in families config must be" % key
                self.assertTrue(any(n.startswith(note) for n in fams["glm"]["notes"]), fams["glm"]["notes"])
                self.assertEqual(fams["claude"]["chain"][:1], ["claude-cli"])  # the other families as usual

    def test_the_worker_returns_a_config_error_and_never_starts_claude(self):
        os.environ["ZAI_API_KEY"] = TOKEN
        for n, (label, (override, key)) in enumerate(WRONG_SHAPE.items()):
            with self.subTest(label):
                self.write_families_override(override)
                meta, fake = self.run_glm_job("4.2-W%d" % (n + 1))
                self.assertEqual(meta["status"], "unavailable")
                self.assertEqual(fake.calls, [])
                self.assertIn("providers.glm.%s" % key, json.dumps(meta))
                self.assertNotIn(TOKEN, self.all_output_text())

    def test_a_chain_seated_before_the_edit_is_refused_not_crashed(self):
        os.environ["ZAI_API_KEY"] = TOKEN
        for n, (override, key) in enumerate((({"providers": {"glm": "x"}}, "providers.glm"),
                                             ({"providers": {"glm": [1]}}, "providers.glm"),
                                             ({"providers": "x"}, "providers"))):
            with self.subTest(override):
                self.write_families_override(override)
                meta, fake = self.run_glm_job("4.2-S%d" % (n + 1))  # AttributeError in the adapter before
                self.assertEqual(meta["status"], "unavailable")
                self.assertEqual(fake.calls, [])
                self.assertEqual(meta["reason"], key + " in families config must be a JSON object")
                self.assertNotIn(TOKEN, self.all_output_text())

    def test_explain_names_the_key(self):
        self.write_families_override(WRONG_SHAPE["env list"][0])
        entry = family._explain_backend(families.load_families(), "claude-cli@glm", "glm", "none", "default")
        self.assertIn("providers.glm.env in families config must be a JSON object", entry["error"])
        self.assertNotIn("settings_env_names", entry)


class KimiEnvTableTests(Base):
    """A provider table without base_url takes the `*_BASE_URL` key of its env sub-table (Kimi Code's overrides.md)."""

    def kimi_config(self, provider):
        home = os.environ["KIMI_CODE_HOME"]
        os.makedirs(os.path.join(home, "credentials"), exist_ok=True)
        textio.write_text_atomic(os.path.join(home, "config.toml"), 'default_model = "m"\n[providers.p]\n' + provider
                                 + '\n[models.m]\nprovider = "p"\nmodel = "m-1"\n')

    def test_the_env_table_url_decides(self):
        cases = (
            ('type = "kimi"\n\n[providers.p.env]\nKIMI_BASE_URL = "https://api.z.ai/api/paas/v4"\n',
             detect.KIMI_GLM_NOTE),
            ('type = "openai"\n\n[providers.p.env]\nOPENAI_BASE_URL = "https://api.z.ai/api/paas/v4"\n',
             detect.KIMI_GLM_NOTE),
            ('type = "kimi"\n\n[providers.p.env]\nKIMI_BASE_URL = "https://api.openai.com/v1"\n',
             detect.KIMI_FOREIGN_NOTE % ("gpt", "api.openai.com")),
            ('type = "anthropic"\n\n[providers.p.env]\nANTHROPIC_BASE_URL = "https://api.z.ai/api/anthropic"\n',
             detect.KIMI_GLM_NOTE),
        )
        for provider, note in cases:
            with self.subTest(provider):
                self.kimi_config(provider)
                kimi = self.detect()["families"]["kimi"]
                self.assertNotIn("kimi-cli", kimi["chain"])
                self.assertIn(note, kimi["notes"])

    def test_base_url_comes_first_and_a_kimi_env_url_stays_kimi(self):
        for provider in ('type = "kimi"\nbase_url = "https://api.moonshot.ai/v1"\n\n[providers.p.env]\n'
                         'KIMI_BASE_URL = "https://api.z.ai/api/paas/v4"\n',
                         'type = "kimi"\n\n[providers.p.env]\nKIMI_BASE_URL = "https://api.moonshot.ai/v1"\n',
                         'type = "kimi"\n\n[providers.p.env]\nKIMI_BASE_URL = " "\n'):
            with self.subTest(provider):
                self.kimi_config(provider)
                self.assertEqual(self.detect()["families"]["kimi"]["chain"], ["kimi-cli"])

    def test_a_job_on_the_kimi_chain_never_starts_the_cli(self):
        self.kimi_config('type = "kimi"\n\n[providers.p.env]\nKIMI_BASE_URL = "https://api.z.ai/api/paas/v4"\n')
        job = self.make_job(family="kimi", job_id="4.2-K1", chain=["kimi-cli"])
        fake = tl.FakeRun([tl.PR(0, tl.fixture_bytes("kimi", "string.jsonl"))])
        with mock.patch("ublib.proc.run", side_effect=fake), \
                mock.patch("ublib.proc.resolve_exe", side_effect=tl.fake_resolve()):
            meta = adapter.execute_job(job)
        self.assertEqual((meta["status"], meta["error_class"]), ("unavailable", "config"))
        self.assertIn(detect.KIMI_GLM_NOTE, meta["reason"])
        self.assertEqual(fake.calls, [])


class KimiEnvModelTests(unittest.TestCase):
    """With env_model, Kimi Code builds its model from KIMI_MODEL_* (env-vars.md); the provider type defaults to kimi."""

    def mislabel(self, **extra):
        env = {"KIMI_CODE_HOME": os.path.join(os.sep, "no", "such", "kimi-home"), "KIMI_MODEL_NAME": "some-model",
               "KIMI_MODEL_API_KEY": "k"}
        env.update(extra)
        return detect.kimi_mislabel({"env_model": True}, env)

    def test_the_provider_type_default_endpoint_decides(self):
        self.assertEqual(self.mislabel(KIMI_MODEL_PROVIDER_TYPE="anthropic"),
                         detect.KIMI_FOREIGN_NOTE % ("claude", "api.anthropic.com"))
        self.assertEqual(self.mislabel(KIMI_MODEL_PROVIDER_TYPE="openai"),
                         detect.KIMI_FOREIGN_NOTE % ("gpt", "api.openai.com"))

    def test_the_kimi_type_and_an_explicit_url_still_decide(self):
        self.assertIsNone(self.mislabel())
        self.assertIsNone(self.mislabel(KIMI_MODEL_PROVIDER_TYPE="kimi"))
        self.assertIsNone(self.mislabel(KIMI_MODEL_PROVIDER_TYPE="anthropic",
                                        KIMI_MODEL_BASE_URL="https://api.moonshot.ai/anthropic"))


if __name__ == "__main__":
    unittest.main()
