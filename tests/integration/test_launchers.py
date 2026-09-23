"""Launcher tests with a fake claude/codex (KIT_SPEC 4.16, 10.6, 11.4 "Launchers"). Owner: B4.

- `claude-glm --version` passes `--settings <file>`; the file exists while the fake runs, is 0600 on POSIX, holds the
  provider env block, and is deleted afterwards.
- The token never appears in argv or in UB_FAKE_LOG.
- A missing ZAI_API_KEY gives exit 2 with "Set ZAI_API_KEY first".
- `codex-glm` sets CODEX_HOME to UB_HOME/codex-homes/glm.
"""

import hashlib
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "harness"))
import paths  # noqa: E402
import inst  # noqa: E402

TOKEN = "zai-launcher-TOKEN-5e1f0c"


def launcher(th, name):
    base = os.path.join(th.ub_home, "bin", name)
    return base + ".cmd" if os.name == "nt" else base


def providers():
    with open(paths.FAMILIES_DEFAULT, encoding="utf-8") as f:
        return json.load(f)["providers"]


class Launchers(unittest.TestCase):
    def setUp(self):
        inst.require_installer()
        paths.require(paths.LAUNCH_PY, paths.FAMILIES_DEFAULT, owner="B1/B2")

    def setup_glm(self, th, *extra):
        proc = inst.run(th, "install", "--yes", "--agents", "claude-code", "--components", "none")
        self.assertEqual(proc.returncode, 0, paths.describe(proc))
        proc = inst.run(th, "setup-glm", "--launcher", "--yes", *extra, env_extra={"ZAI_API_KEY": TOKEN})
        self.assertEqual(proc.returncode, 0, paths.describe(proc))
        self.assertNotIn(TOKEN, proc.out + proc.err)

    def test_claude_glm_settings_file(self):
        with inst.installer_home(tools=("claude", "codex", "node")) as th:
            self.setup_glm(th)
            exe = launcher(th, "claude-glm")
            self.assertTrue(os.path.isfile(exe), os.listdir(os.path.dirname(exe)))
            env = dict(th.env, ZAI_API_KEY=TOKEN, ANTHROPIC_BASE_URL="https://api.anthropic.com")
            th.clear_log()
            proc = paths.run([exe, "--version"], env=env, cwd=th.project)
            self.assertEqual(proc.returncode, 0, paths.describe(proc))
            calls = th.fake_calls("claude")
            self.assertEqual(len(calls), 1, calls)
            call = calls[0]
            argv = call["argv"]
            self.assertIn("--settings", argv)
            self.assertEqual(argv[-1], "--version")
            snap = call["settings"]
            self.assertTrue(snap["exists"], "the settings file exists while claude runs")
            if os.name != "nt":
                self.assertEqual(snap["mode"], "0o600")
            p = providers()["glm"]
            senv = snap["env"]
            self.assertEqual(senv["ANTHROPIC_BASE_URL"], p["base_url"]["global"])
            self.assertEqual(senv["ANTHROPIC_MODEL"], p["models"]["default"])
            self.assertEqual(senv["ANTHROPIC_DEFAULT_HAIKU_MODEL"], p["models"]["fast"])
            for k in ("ANTHROPIC_DEFAULT_OPUS_MODEL", "ANTHROPIC_DEFAULT_SONNET_MODEL", "CLAUDE_CODE_SUBAGENT_MODEL"):
                self.assertEqual(senv[k], p["models"]["default"], k)
            for k, v in p["env"].items():
                self.assertEqual(senv[k], v, k)
            self.assertEqual(senv[p["token_var"]], "sha256:" + hashlib.sha256(TOKEN.encode()).hexdigest())
            self.assertFalse(os.path.exists(snap["path"]), "the settings file is deleted afterwards")
            self.assertEqual(call["env"].get("UB_HOST_FAMILY"), "glm")
            self.assertNotIn(TOKEN, json.dumps(argv))
            self.assertNotIn(TOKEN, th.log_text())
            self.assertNotIn(TOKEN, proc.out + proc.err)
            for name in ("claude-glm", "claude-glm.cmd", "claude-glm.ps1"):
                self.assertTrue(os.path.isfile(os.path.join(th.ub_home, "bin", name)), name)
                self.assertNotIn(TOKEN, inst.read(os.path.join(th.ub_home, "bin", name)))

    def test_missing_key_exit_2(self):
        with inst.installer_home(tools=("claude", "node")) as th:
            self.setup_glm(th)
            th.clear_log()
            proc = paths.run([launcher(th, "claude-glm"), "--version"], env=th.env, cwd=th.project)
            self.assertEqual(proc.returncode, 2, paths.describe(proc))
            self.assertIn("Set ZAI_API_KEY first", proc.out + proc.err)
            self.assertEqual(th.fake_calls("claude"), [], "claude never starts without the key")

    def test_codex_glm_sets_codex_home(self):
        with inst.installer_home(tools=("claude", "codex", "node")) as th:
            self.setup_glm(th, "--codex")
            home = os.path.join(th.ub_home, "codex-homes", "glm")
            cfg = os.path.join(home, "config.toml")
            self.assertTrue(os.path.isfile(cfg))
            text = inst.read(cfg)
            self.assertIn('env_key = "ZAI_API_KEY"', text)
            self.assertNotIn(TOKEN, text)
            for banned in ("experimental_bearer_token", 'wire_api = "chat"', "[profiles."):
                self.assertNotIn(banned, text)
            th.clear_log()
            proc = paths.run([launcher(th, "codex-glm"), "--version"], env=dict(th.env, ZAI_API_KEY=TOKEN),
                             cwd=th.project)
            self.assertEqual(proc.returncode, 0, paths.describe(proc))
            call = th.fake_calls("codex")[-1]
            self.assertTrue(paths.same_path(call["env"].get("CODEX_HOME"), home), call["env"])
            self.assertEqual(call["env"].get("UB_HOST_FAMILY"), "glm")
            self.assertNotIn(TOKEN, json.dumps(call["argv"]))

    def test_ub_launcher_runs_engine(self):
        paths.require(paths.UB_PY, owner="B3")
        with inst.installer_home(tools=("node", "kimi")) as th:
            proc = inst.run(th, "install", "--yes", "--components", "none")
            self.assertEqual(proc.returncode, 0, paths.describe(proc))
            proc = paths.run([launcher(th, "ub"), "--version"], env=th.env, cwd=th.project)
            self.assertEqual(proc.returncode, 0, paths.describe(proc))
            self.assertIn("2.0.0", proc.out + proc.err)


if __name__ == "__main__":
    unittest.main()
