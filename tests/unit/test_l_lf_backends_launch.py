"""Phase L, package LF-backends-launch (round-5 findings on the HTTP backends and profiles/launch.py).

- A loopback http:// model backend (the documented "local" family) is called directly. Behind HTTP_PROXY, or a
  Windows system proxy whose "<local>" bypass misses 127.0.0.1, every request went to the proxy with its key and the
  whole prompt in clear text, and the local server was never reached. http_openai.post_json (shared by
  anthropic-http) now uses a proxy-less opener for a loopback host; any other host keeps the proxy.
- launch.py resolves a provider's endpoint and models with the worker's ublib.families.provider_settings_env: a
  families.json "region" the provider lacks falls back to global (U-22), as for claude-cli@<provider> calls, instead of
  refusing every claude-kimi start. An explicit --region the provider lacks is still refused.
- A families.json that is valid JSON but the wrong shape ([] or a string, or a providers/backends entry, base_url,
  models or env that is not an object, or a region, token_env or token_var that is not a string) exits 2 with a
  message naming the key, not a traceback with exit 1. The Codex home is not rendered from such a file (it silently
  dropped the codex_base_url override).
No real CLI and no network: the servers are local stubs and resolve_tool is mocked away.
"""

import contextlib
import importlib.util
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
import urllib.request
from unittest import mock

_KIT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for _p in (os.path.join(_KIT, "skills", "ultimate-brainstorm", "scripts"), os.path.join(_KIT, "tests", "harness")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from http_stub import HttpStub  # noqa: E402
from ublib import families  # noqa: E402
from ublib.backends import http_openai  # noqa: E402

KEY = "sk-local-proxy-test-0123456789"


def load_launch():
    spec = importlib.util.spec_from_file_location("ub_launch_lf", os.path.join(_KIT, "profiles", "launch.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class LoopbackSkipsTheProxy(unittest.TestCase):
    def setUp(self):
        self.proxy = HttpStub(default_text="FROM-PROXY").__enter__()
        self.addCleanup(self.proxy.__exit__, None, None, None)
        self.server = HttpStub(default_text="FROM-SERVER").__enter__()
        self.addCleanup(self.server.__exit__, None, None, None)
        env = mock.patch.dict(os.environ)
        env.start()
        self.addCleanup(env.stop)
        for name in ("NO_PROXY", "no_proxy"):
            os.environ.pop(name, None)
        os.environ["HTTP_PROXY"] = os.environ["http_proxy"] = self.proxy.url("")
        # urllib's ProxyHandler reads the proxy settings when an opener is built: the module's one saw none
        opener = mock.patch.object(http_openai, "_OPENER", urllib.request.build_opener(http_openai._NoRedirect))
        opener.start()
        self.addCleanup(opener.stop)

    def post(self, host):
        url = "http://%s:%d/v1/chat/completions" % (host, self.server.port)
        return http_openai.post_json(url, {"Authorization": "Bearer " + KEY}, {"prompt": "FACTS"}, 30, max_retries=0)

    def test_a_loopback_backend_is_called_directly(self):
        for host in ("127.0.0.1", "localhost"):
            code, body, exc, _sent, _ra = self.post(host)
            self.assertEqual((code, exc), (200, None), host)
            self.assertIn(b"FROM-SERVER", body, host)
        self.assertEqual(len(self.server.requests), 2)
        self.assertEqual(self.proxy.requests, [], "the key and the prompt never reach the proxy")

    def test_any_other_host_still_uses_the_proxy(self):
        code, body, _exc, _sent, _ra = http_openai.post_json("http://api.example.test/v1/chat/completions", {},
                                                             {"x": 1}, 30, max_retries=0)
        self.assertEqual(code, 200)
        self.assertIn(b"FROM-PROXY", body)
        self.assertEqual([r["path"] for r in self.proxy.requests], ["http://api.example.test/v1/chat/completions"])


class LauncherCase(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="ub-lf-launch-")
        self.addCleanup(shutil.rmtree, self.home, True)
        self.mod = load_launch()
        self.env = {"UB_HOME": self.home, "KIMI_API_KEY": "kimi-test", "ZAI_API_KEY": "zai-test", "PATH": self.home}

    def override(self, data):
        with open(os.path.join(self.home, "families.json"), "w", encoding="utf-8") as f:
            f.write(json.dumps(data))

    def launch(self, tool, opts):
        """(exit code, stderr) of launch_claude / launch_codex; claude and codex are never found."""
        err = io.StringIO()
        fn = self.mod.launch_claude if tool == "claude" else self.mod.launch_codex
        with mock.patch.object(self.mod, "resolve_tool", return_value=None):
            try:
                with contextlib.redirect_stderr(err):
                    fn(opts, [], self.env)
            except self.mod.LaunchError as exc:
                return exc.code, str(exc)
        return 0, err.getvalue()


class LauncherRegion(LauncherCase):
    def worker_env(self, provider, tier="default"):
        cfg = families.load_families(ub_home=self.home)
        return families.provider_settings_env(cfg, provider, tier, cfg.get("region"))

    def test_a_config_region_the_provider_lacks_falls_back_to_global_as_in_the_worker(self):
        self.override({"region": "cn"})
        code, msg = self.launch("claude", {"provider": "kimi"})
        self.assertEqual((code, msg.split(" or not")[0]), (1, "claude is not installed"), msg)
        cfg = self.mod.load_config(self.home)
        for provider in ("glm", "kimi", "kimi-code"):
            for tier in ("default", "fast"):
                self.assertEqual(self.mod.provider_settings_env(cfg, provider, tier), self.worker_env(provider, tier),
                                 (provider, tier))
        self.assertEqual(self.mod.provider_settings_env(cfg, "kimi")["ANTHROPIC_BASE_URL"],
                         "https://api.moonshot.ai/anthropic")
        self.assertEqual(self.mod.provider_settings_env(cfg, "glm")["ANTHROPIC_BASE_URL"],
                         "https://open.bigmodel.cn/api/anthropic")

    def test_an_explicit_region_the_provider_lacks_is_refused(self):
        code, msg = self.launch("claude", {"provider": "kimi", "region": "cn"})
        self.assertEqual(code, 2)
        self.assertIn("Provider kimi has no cn endpoint. Use --region global.", msg)

    def test_a_single_url_base_url_serves_every_region_as_in_the_worker(self):
        self.override({"region": "cn", "providers": {"kimi": {"base_url": "https://kimi.example.test/anthropic"}}})
        cfg = self.mod.load_config(self.home)
        self.assertEqual(self.mod.provider_settings_env(cfg, "kimi"), self.worker_env("kimi"))
        self.assertEqual(self.mod.provider_settings_env(cfg, "kimi")["ANTHROPIC_BASE_URL"],
                         "https://kimi.example.test/anthropic")

    def test_the_worker_reads_a_region_that_is_no_string_as_global(self):
        self.override({"region": ["cn"]})
        self.assertEqual(self.worker_env("glm")["ANTHROPIC_BASE_URL"], "https://api.z.ai/api/anthropic")

    def test_no_endpoint_at_all_is_refused(self):
        self.override({"providers": {"kimi": {"base_url": {"global": None}}}})
        code, msg = self.launch("claude", {"provider": "kimi"})
        self.assertEqual(code, 2)
        self.assertIn("Provider kimi has no global base_url", msg)


class LauncherConfigShape(LauncherCase):
    def test_a_wrong_shape_exits_2_with_the_key_named(self):
        cases = [
            ("claude", [], "the top level"),
            ("claude", "glm", "the top level"),
            ("claude", None, "the top level"),
            ("claude", {"providers": "x"}, "providers must"),
            ("claude", {"providers": {"glm": "x"}}, "providers.glm must"),
            ("claude", {"providers": {"glm": {"models": "m"}}}, "providers.glm.models must"),
            ("claude", {"providers": {"glm": {"base_url": ["https://x.test"]}}}, "providers.glm.base_url must"),
            ("claude", {"providers": {"glm": {"env": ["A=1"]}}}, "providers.glm.env must"),
            ("claude", {"region": ["cn"]}, "region must be a string"),
            ("claude", {"region": 7}, "region must be a string"),
            ("claude", {"providers": {"glm": {"token_env": ["ZAI_API_KEY"]}}}, "providers.glm.token_env must be a str"),
            ("claude", {"providers": {"glm": {"token_var": 5}}}, "providers.glm.token_var must be a string"),
            ("codex", [], "the top level"),
            ("codex", {"backends": "x"}, "backends must"),
            ("codex", {"backends": {"codex-cli@glm": 5}}, "backends.codex-cli@glm must"),
            ("codex", {"backends": {"codex-cli@glm": {"token_env": ["Z"]}}}, "backends.codex-cli@glm.token_env must"),
        ]
        for tool, data, key in cases:
            self.override(data)
            code, msg = self.launch(tool, {"provider": "glm"})
            self.assertEqual(code, 2, (tool, data, msg))
            self.assertIn(key, msg, (tool, data))
            self.assertIn(". Fix or remove it", msg, (tool, data))

    def test_the_codex_home_is_never_rendered_without_the_override_of_a_bad_file(self):
        over = {"providers": {"glm": {"codex_base_url": "https://glm-gateway.example.test/api/v1"}}}
        with mock.patch.dict(os.environ, {"UB_HOME": self.home}):
            self.override(over)
            self.assertIn("https://glm-gateway.example.test/api/v1", self.mod.render_codex_home("glm"))
            over["backends"] = {"kimi-cli": True}
            self.override(over)
            with self.assertRaises(self.mod.LaunchError) as cm:
                self.mod.render_codex_home("glm")
        self.assertIn("backends.kimi-cli must be a JSON object", str(cm.exception))

    def test_main_prints_the_message_instead_of_a_traceback(self):
        self.override({"providers": {"glm": "x"}})
        err = io.StringIO()
        with mock.patch.dict(os.environ, self.env), mock.patch.object(self.mod, "resolve_tool", return_value=None), \
                contextlib.redirect_stderr(err):
            code = self.mod.main(["claude", "--provider", "glm", "--", "-p", "x"])
        self.assertEqual(code, 2)
        self.assertIn("providers.glm must be a JSON object", err.getvalue())
        self.assertNotIn("Traceback", err.getvalue())

    def test_the_defaults_and_empty_values_pass(self):
        self.override({"providers": {"glm": {"env": None, "models": {}}}, "backends": {"kimi-cli": None}})
        code, msg = self.launch("claude", {"provider": "glm"})
        self.assertEqual((code, msg.split(" or not")[0]), (1, "claude is not installed"), msg)


if __name__ == "__main__":
    unittest.main()
