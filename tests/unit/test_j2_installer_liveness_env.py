"""J2C (request JF-backends-detect 1 and 2): a provider's token_env is looked up as detection looks it up, in any
letter case on Windows (KIT_SPEC 4.9 provider_settings_env).

On Windows os.environ ignores the letter case of a name, but the worker and the launchers read the token from a dict
copy of it, whose keys are upper case. Detection seated claude-cli@glm for `"token_env": "zai_api_key"` with
ZAI_API_KEY set, and then every call failed with 'zai_api_key is not set'; `claude-glm` and `codex-glm` said
'Set zai_api_key first'. families.provider_token and profiles/launch.py now use proc._env_get. POSIX names keep their
case. Only ublib.proc.run is mocked (no model CLI, no network).
"""

import importlib.util
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

_KIT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(_KIT, "tests", "fixtures", "adapter"))

import adapter_testlib as tl  # noqa: E402
from ublib import adapter, families, proc, textio  # noqa: E402

TOKEN = "zai-test-token-0123456789abcdef"
LOWER = {"providers": {"glm": {"token_env": "zai_api_key"}},
         "backends": {"codex-cli@glm": {"token_env": "zai_api_key"}}}


def load_launch():
    spec = importlib.util.spec_from_file_location("ub_launch_j2c", os.path.join(_KIT, "profiles", "launch.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class ProviderToken(unittest.TestCase):
    def test_the_letter_case_is_ignored_where_the_platform_ignores_it(self):
        env = {"ZAI_API_KEY": TOKEN}  # a dict copy of os.environ on Windows: upper-case keys
        with mock.patch.object(proc, "IS_WINDOWS", True):
            self.assertEqual(families.provider_token(LOWER, "glm", env), ("zai_api_key", "ANTHROPIC_AUTH_TOKEN", TOKEN))
        with mock.patch.object(proc, "IS_WINDOWS", False):  # POSIX names are case-sensitive: not this variable
            self.assertEqual(families.provider_token(LOWER, "glm", env), ("zai_api_key", "ANTHROPIC_AUTH_TOKEN", None))


@unittest.skipUnless(os.name == "nt", "environment variable names ignore case only on Windows")
class ClaudeGlmWorker(tl.AdapterTestCase):
    def test_a_token_env_in_another_letter_case_reaches_the_settings_file(self):
        self.write_families_override({"providers": {"glm": {"token_env": "zai_api_key"}}})
        os.environ["ZAI_API_KEY"] = TOKEN
        seen = {}

        def respond(call):
            argv = call["argv"]
            seen["env"] = json.loads(textio.read_text(argv[argv.index("--settings") + 1]))["env"]
            return tl.PR(0, tl.fixture_bytes("claude", "success.json"))
        fake = tl.FakeRun([respond])
        job = self.make_job(family="glm", job_id="4.2-S5")
        det = tl.chain_detect({"glm": ["claude-cli@glm"]}, host_family="claude")
        with mock.patch("ublib.proc.run", side_effect=fake), \
                mock.patch("ublib.proc.resolve_exe", side_effect=tl.fake_resolve()):
            meta = adapter.execute_job(job, detect_result=det)
        self.assertEqual(meta["status"], "ok", meta.get("reason"))
        self.assertEqual(len(fake.calls), 1)
        self.assertEqual(seen["env"]["ANTHROPIC_AUTH_TOKEN"], TOKEN)
        self.assertNotIn(TOKEN, self.all_output_text())


class Launchers(unittest.TestCase):
    """launch_claude and launch_codex read the token as the platform names it (resolve_tool is mocked away, so a found
    token ends at 'not installed' before anything starts)."""

    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="ub-j2c-launch-")
        self.addCleanup(shutil.rmtree, self.home, True)
        textio.write_json_atomic(os.path.join(self.home, "families.json"), LOWER)
        textio.write_text_atomic(os.path.join(self.home, "codex-homes", "glm", "config.toml"), "# the kit's\n")
        self.mod = load_launch()
        self.env = {"UB_HOME": self.home, "ZAI_API_KEY": TOKEN, "PATH": os.environ.get("PATH", "")}

    def error(self, launch, windows):
        with mock.patch.object(self.mod.proc, "IS_WINDOWS", windows), \
                mock.patch.object(self.mod, "resolve_tool", return_value=None):
            with self.assertRaises(self.mod.LaunchError) as cm:
                launch({"provider": "glm"}, [], self.env)
        return str(cm.exception)

    def test_claude_glm(self):
        self.assertIn("claude is not installed", self.error(self.mod.launch_claude, True))
        self.assertIn("Set zai_api_key first", self.error(self.mod.launch_claude, False))

    def test_codex_glm(self):
        self.assertIn("codex is not installed", self.error(self.mod.launch_codex, True))
        self.assertIn("Set zai_api_key first", self.error(self.mod.launch_codex, False))


if __name__ == "__main__":
    unittest.main()
