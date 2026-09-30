"""Phase V (VB) worker checks. A claude-cli@<provider> backend whose provider resolves no base URL is unavailable at
detection and never starts claude (the launchers' rule, KIT_SPEC 4.16 step 1). A Kimi Code provider without base_url
is read by its `type` (Kimi Code's documented Anthropic setup is not the kimi family, 5.5). Process calls are mocked at
ublib.proc.run; no real CLI and no network."""

import json
import os
import sys
import unittest
from unittest import mock

_KIT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(_KIT, "tests", "fixtures", "adapter"))

import adapter_testlib as tl  # noqa: E402
from ublib import adapter, detect, families, textio  # noqa: E402

VERSIONS = {"claude": "2.1.280 (Claude Code)\n", "codex": "codex-cli 0.160.0\n", "kimi": "kimi, version 2.0.2\n"}
TOKEN = "zai-test-token-0123456789abcdef"
NO_URL = {
    "global null": {"providers": {"glm": {"base_url": {"global": None}}}},
    "empty string": {"providers": {"glm": {"base_url": ""}}},
}


class Base(tl.AdapterTestCase):
    def detect(self):
        def run(argv, **_kw):
            return tl.PR(0, VERSIONS.get(os.path.basename(argv[0]).split(".")[0], ""))
        with mock.patch("ublib.proc.resolve_exe", side_effect=lambda name, env=None: tl.fake_resolve()(name)), \
                mock.patch("ublib.proc.run", side_effect=run):
            return detect.detect(families.load_families())


class ProviderWithoutBaseUrlTests(Base):
    def test_detection_leaves_the_provider_backend_out(self):
        os.environ["ZAI_API_KEY"] = TOKEN
        for label, override in NO_URL.items():
            with self.subTest(label):
                self.write_families_override(override)
                glm = self.detect()["families"]["glm"]
                self.assertFalse(glm["available"])
                self.assertNotIn("claude-cli@glm", glm["chain"])
                self.assertIn("provider glm has no base_url in families config", glm["notes"])

    def test_a_job_on_the_provider_chain_never_starts_claude(self):
        os.environ["ZAI_API_KEY"] = TOKEN
        for n, (label, override) in enumerate(NO_URL.items()):
            with self.subTest(label):
                self.write_families_override(override)
                job = self.make_job(family="glm", job_id="4.2-S%d" % (n + 1))
                fake = tl.FakeRun([tl.PR(0, tl.fixture_bytes("claude", "success.json"))])
                det = tl.chain_detect({"glm": ["claude-cli@glm"]}, host_family="claude")
                with mock.patch("ublib.proc.run", side_effect=fake), \
                        mock.patch("ublib.proc.resolve_exe", side_effect=tl.fake_resolve()):
                    meta = adapter.execute_job(job, detect_result=det)
                self.assertEqual(meta["status"], "unavailable")
                self.assertEqual(fake.calls, [])
                self.assertIn("no base_url", json.dumps(meta))
                self.assertNotIn(TOKEN, self.all_output_text())

    def test_the_default_provider_still_starts_with_its_url(self):
        os.environ["ZAI_API_KEY"] = TOKEN
        self.assertIn("claude-cli@glm", self.detect()["families"]["glm"]["chain"])


class KimiTypedProviderTests(Base):
    """A provider table without base_url is served by its type's own endpoint (Kimi Code's providers.md)."""

    def kimi_config(self, typ):
        home = os.environ["KIMI_CODE_HOME"]
        os.makedirs(os.path.join(home, "credentials"), exist_ok=True)
        textio.write_text_atomic(os.path.join(home, "config.toml"), 'default_model = "m"\n[models.m]\nprovider = "p"\n'
                                 '[providers.p]\ntype = "%s"\napi_key = "k"\n' % typ)

    def test_another_vendors_type_makes_kimi_cli_unavailable(self):
        for typ, served, host in (("anthropic", "claude", "api.anthropic.com"), ("openai", "gpt", "api.openai.com"),
                                  ("google-genai", "custom:generativelanguage.googleapis.com",
                                   "generativelanguage.googleapis.com")):
            with self.subTest(typ):
                self.kimi_config(typ)
                kimi = self.detect()["families"]["kimi"]
                self.assertFalse(kimi["available"])
                self.assertIn(detect.KIMI_FOREIGN_NOTE % (served, host), kimi["notes"])

    def test_the_kimi_type_and_an_unknown_type_stay_available(self):
        for typ in ("kimi", "a-future-type"):
            with self.subTest(typ):
                self.kimi_config(typ)
                self.assertEqual(self.detect()["families"]["kimi"]["chain"], ["kimi-cli"])

    def test_a_job_on_the_kimi_chain_never_starts_the_cli(self):
        self.kimi_config("anthropic")
        job = self.make_job(family="kimi", job_id="4.2-K1", chain=["kimi-cli"])
        fake = tl.FakeRun([tl.PR(0, tl.fixture_bytes("kimi", "string.jsonl"))])
        with mock.patch("ublib.proc.run", side_effect=fake), \
                mock.patch("ublib.proc.resolve_exe", side_effect=tl.fake_resolve()):
            meta = adapter.execute_job(job)
        self.assertEqual((meta["status"], meta["error_class"]), ("unavailable", "config"))
        self.assertIn("configured for claude (api.anthropic.com)", meta["reason"])
        self.assertEqual(fake.calls, [])


if __name__ == "__main__":
    unittest.main()
