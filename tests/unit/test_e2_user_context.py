"""E2: claude-cli workers isolate from the user's settings even when settings.json carries the login or the route
(finding 28), and the run-folder deny rules never deny the repository itself (reviewer note P3-backends-2).

- user_context "auto" used to inherit every user setting (hooks, plugins, CLAUDE.md) as soon as settings.json had an
  env block, which is common (DISABLE_TELEMETRY, a proxy). Now the call skips the user's settings sources and its own
  0600 --settings file carries apiKeyHelper, awsAuthRefresh, awsCredentialExport and env instead [U-43]. A provider
  backend takes over only the env entries a child environment keeps and never a helper command; its own values win.
  When the file cannot be secured, a native call falls back to loading the user's settings (the login still works).
- `ub init --root .` in a repository named "brainstorm" makes the repository the runs folder: the deny rules then
  name the run folders only.
Process calls are mocked at ublib.proc.run.
"""

import json
import os
import sys
import unittest
from unittest import mock

_KIT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(_KIT, "tests", "fixtures", "adapter"))

import adapter_testlib as tl  # noqa: E402
from ublib import adapter, detect, textio  # noqa: E402
from ublib.backends import CallContext, claude_cli  # noqa: E402

SUCCESS = tl.fixture_bytes("claude", "success.json")
HELPER_TOKEN = "helper-token-0123456789abcdef"


class Base(tl.AdapterTestCase):
    def settings(self, data):
        d = os.environ["CLAUDE_CONFIG_DIR"]
        os.makedirs(d, exist_ok=True)
        textio.write_json_atomic(os.path.join(d, "settings.json"), data)

    def call(self, family="claude", chain=("claude-cli",), job_id="u1", stderr=b""):
        """Run one claude job; returns (meta, argv, the --settings file's content during the call or None)."""
        seen = {}

        def respond(call):
            argv = call["argv"]
            if "--settings" in argv:
                seen["settings"] = textio.read_json(argv[argv.index("--settings") + 1])
            return tl.PR(0, SUCCESS, stderr)
        fake = tl.FakeRun([respond])
        det = tl.chain_detect({family: list(chain)}, host_family="claude")
        with mock.patch("ublib.proc.run", side_effect=fake), \
                mock.patch("ublib.proc.resolve_exe", side_effect=tl.fake_resolve()):
            meta = adapter.execute_job(self.make_job(family=family, job_id=job_id), detect_result=det)
        return meta, fake.calls[0]["argv"], seen.get("settings")


class CarriedSettingsTests(Base):
    ROUTE = {"env": {"HTTPS_PROXY": "http://proxy.corp:3128", "DISABLE_TELEMETRY": "1",
                     "ANTHROPIC_AUTH_TOKEN": HELPER_TOKEN},
             "apiKeyHelper": "/usr/local/bin/get-key", "awsAuthRefresh": "aws sso login",
             "hooks": {"SessionStart": [{"hooks": [{"type": "command", "command": "inject"}]}]},
             "enabledPlugins": {"superpowers@x": True}, "model": "opus"}

    def test_auto_isolates_and_carries_the_login_and_route_keys(self):
        self.settings(self.ROUTE)
        meta, argv, carried = self.call()
        self.assertEqual(meta["status"], "ok", meta)
        self.assertEqual(argv[argv.index("--setting-sources") + 1], "project")
        self.assertEqual(carried, {"env": self.ROUTE["env"], "apiKeyHelper": "/usr/local/bin/get-key",
                                   "awsAuthRefresh": "aws sso login"},
                         "hooks, plugins and the model preference stay behind")
        path = argv[argv.index("--settings") + 1]
        self.assertFalse(os.path.exists(path), "the settings file is deleted after the call")
        self.assertEqual(os.path.dirname(os.path.dirname(path)), os.path.join(self.home, "tmp"))
        self.assertNotIn(HELPER_TOKEN, self.all_output_text())

    def test_nothing_to_carry_means_no_settings_file(self):
        self.settings({"hooks": {"Stop": []}})
        _meta, argv, _carried = self.call()
        self.assertIn("--setting-sources", argv)
        self.assertNotIn("--settings", argv)

    def test_a_provider_takes_only_what_a_child_environment_keeps(self):
        os.environ["ZAI_API_KEY"] = "zai-test-token-0123456789"
        self.settings(dict(self.ROUTE, env=dict(self.ROUTE["env"], CLAUDE_CODE_USE_BEDROCK="1",
                                                ANTHROPIC_BASE_URL="https://api.anthropic.com")))
        meta, argv, carried = self.call(family="glm", chain=("claude-cli@glm",), job_id="p1")
        self.assertEqual(meta["status"], "ok", meta)
        self.assertIn("--setting-sources", argv)
        env = carried["env"]
        self.assertEqual((env["HTTPS_PROXY"], env["DISABLE_TELEMETRY"]), ("http://proxy.corp:3128", "1"))
        self.assertEqual(env["ANTHROPIC_AUTH_TOKEN"], "zai-test-token-0123456789", "the provider's own value wins")
        self.assertIn("api.z.ai", env["ANTHROPIC_BASE_URL"])
        self.assertNotIn("CLAUDE_CODE_USE_BEDROCK", env)
        self.assertEqual(set(carried), {"env"}, "no helper command reaches a provider call")

    def test_a_settings_file_that_cannot_be_secured_falls_back_to_the_user_settings(self):
        self.settings(self.ROUTE)
        with mock.patch("ublib.backends.claude_cli.write_secret_file", side_effect=OSError("no icacls")):
            meta, argv, _carried = self.call()
        self.assertEqual(meta["status"], "ok", meta)
        self.assertNotIn("--setting-sources", argv)
        self.assertNotIn("--settings", argv)

    def test_carried_secret_values_are_redacted(self):
        self.settings(self.ROUTE)
        meta, _argv, _carried = self.call(stderr=("warning: token %s rejected" % HELPER_TOKEN).encode())
        self.assertNotIn(HELPER_TOKEN, json.dumps(meta))
        self.assertNotIn(HELPER_TOKEN, self.all_output_text())

    def test_inherit_and_reclassified_are_unchanged(self):
        self.assertEqual(detect.claude_user_context({"user_context": "inherit"}, "claude"), "inherit")
        self.assertEqual(detect.claude_user_context({}, "glm"), "inherit")  # a native claude-cli seated as glm
        self.assertEqual(detect.claude_user_context({"provider": "glm"}, "glm"), "isolate")
        self.assertEqual(detect.claude_user_context({}, "claude"), "isolate")

    def test_explain_names_the_carried_keys_without_values(self):
        self.settings(self.ROUTE)
        import family  # noqa: E402  (scripts/family.py)
        from ublib import families
        entry = family._explain_backend(families.load_families(), "claude-cli", "claude", "none", "default")
        self.assertEqual(entry["carried_settings"], ["apiKeyHelper", "awsAuthRefresh", "env.ANTHROPIC_AUTH_TOKEN",
                                                     "env.DISABLE_TELEMETRY", "env.HTTPS_PROXY"])
        self.assertIn("--settings", entry["argv"])
        self.assertNotIn(HELPER_TOKEN, json.dumps(entry))


class RunFolderRuleTests(tl.AdapterTestCase):
    def ctx(self, repo, run_dir):
        return CallContext(job={"id": "x"}, backend_id="claude-cli", bcfg={"type": "claude-cli"}, btype="claude-cli",
                           tools="read", cwd_mode="repo", repo_root=repo, run_dir=run_dir, family="claude")

    def test_a_repository_that_is_the_runs_folder_is_never_denied(self):
        repo = os.path.join(self.tmp, "code", "brainstorm")
        runs = [os.path.join(repo, "2026-09-%02d-topic" % d) for d in range(1, 14)]
        for r in runs:
            os.makedirs(r)
            textio.write_json_atomic(os.path.join(r, "run.json"), {"schema": 2})
        os.makedirs(os.path.join(repo, "src"))
        rules = claude_cli.run_folder_rules(self.ctx(repo, runs[0]))
        whole = claude_cli.rule_path(repo)
        self.assertFalse([r for r in rules if r.endswith("(%s/**)" % whole)], "the whole repository is denied")
        denied = sorted(set(r.split("(", 1)[1] for r in rules))
        self.assertIn("%s/**)" % claude_cli.rule_path(runs[0]), denied, "this run first")
        self.assertEqual(len(denied), 1 + claude_cli.RUN_RULES_MAX, "at most RUN_RULES_MAX other runs")
        self.assertIn("%s/**)" % claude_cli.rule_path(runs[-1]), denied, "the newest runs")
        self.assertNotIn("%s/**)" % claude_cli.rule_path(os.path.join(repo, "src")), denied)

    def test_the_default_layout_denies_the_runs_folder(self):
        repo = os.path.join(self.tmp, "repo")
        run_dir = os.path.join(repo, "brainstorm", "2026-09-26-topic")
        os.makedirs(run_dir)
        rules = claude_cli.run_folder_rules(self.ctx(repo, run_dir))
        root = claude_cli.rule_path(os.path.join(repo, "brainstorm"))
        self.assertEqual(rules, ["Read(%s/**)" % root, "Grep(%s/**)" % root, "Glob(%s/**)" % root])


if __name__ == "__main__":
    unittest.main()
