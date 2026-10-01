"""Installer doctor tests (KIT_SPEC 10.5 doctor, 11.4). Owner: B4.

doctor is read-only; each check reaches PASS, WARN and FAIL in at least one case; duplicates across ~/.agents/skills and
~/.codex/skills FAIL with exit 1; a Z.ai base URL in ~/.claude/settings.json WARNs "claude family reclassified as glm".
"""

import json
import os
import re
import shutil
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "harness"))
import paths  # noqa: E402
import fsnap  # noqa: E402
import inst  # noqa: E402
import shims  # noqa: E402

SEEN = set()


def doctor(tc, th, expect_exit=None):
    proc = inst.run(th, "doctor", "--json")
    data = paths.last_json(proc.out)
    tc.assertIn("checks", data, data)
    tc.assertIn("exit", data)
    tc.assertEqual(data["exit"], proc.returncode)
    for c in data["checks"]:
        for k in ("id", "status", "detail", "fix"):
            tc.assertIn(k, c, c)
        tc.assertIn(c["status"], ("PASS", "WARN", "FAIL"))
        SEEN.add(c["status"])
        if c["status"] == "FAIL":
            tc.assertTrue(str(c.get("fix") or "").strip(), "every FAIL comes with a fix: %s" % c)
    tc.assertEqual(proc.returncode, 1 if any(c["status"] == "FAIL" for c in data["checks"]) else 0)
    if expect_exit is not None:
        tc.assertEqual(proc.returncode, expect_exit, paths.describe(proc))
    return data


def text_of(c):
    return "%s %s %s" % (c.get("id"), c.get("detail"), c.get("fix"))


class Doctor(unittest.TestCase):
    def setUp(self):
        inst.require_installer()

    def test_healthy_install_passes_and_is_read_only(self):
        with inst.installer_home(tools=("kimi", "node")) as th:
            self.assertEqual(inst.run(th, "install", "--yes", "--components", "none").returncode, 0)
            before = fsnap.snapshot(th.root)
            data = doctor(self, th)
            fsnap.assert_unchanged(self, before, fsnap.snapshot(th.root),
                                   ignore=["fake.log", "fake.log.*"] + inst.home_snapshot_ignores(), msg="doctor")
            self.assertTrue(any(c["status"] == "PASS" for c in data["checks"]))
            self.assertFalse([c for c in data["checks"] if c["status"] == "FAIL"],
                             "fresh install has no FAIL: %s" % [c for c in data["checks"] if c["status"] == "FAIL"])

    def test_duplicate_skill_fails(self):
        with inst.installer_home(tools=("codex", "node")) as th:
            fixture = os.path.join(paths.FIX_INSTALLER, "skill-v2", "SKILL.md.fixture")
            for base in (os.path.join(th.home, ".agents", "skills"), os.path.join(th.codex_home, "skills")):
                d = os.path.join(base, "ultimate-brainstorm")
                os.makedirs(d)
                shutil.copyfile(fixture, os.path.join(d, "SKILL.md"))
            data = doctor(self, th, expect_exit=1)
            fails = [c for c in data["checks"] if c["status"] == "FAIL"]
            self.assertTrue(any(re.search(r"(?i)dup|twice|both|\.codex/skills", text_of(c)) for c in fails), fails)

    def test_zai_settings_reclassify_warn(self):
        with inst.installer_home(tools=("claude", "node")) as th:
            shutil.copyfile(os.path.join(paths.FIX_INSTALLER, "claude-settings-zai.json"),
                            os.path.join(th.mkdir("home", ".claude"), "settings.json"))
            data = doctor(self, th)
            warns = [c for c in data["checks"] if c["status"] == "WARN"]
            self.assertTrue(any(re.search(r"(?i)claude family reclassified as glm", text_of(c)) for c in warns),
                            warns)

    def test_statuses_all_reached(self):
        with inst.installer_home(tools=("claude", "codex", "node")) as th:
            shutil.copyfile(os.path.join(paths.FIX_INSTALLER, "claude-settings-zai.json"),
                            os.path.join(th.mkdir("home", ".claude"), "settings.json"))
            fixture = os.path.join(paths.FIX_INSTALLER, "skill-v2", "SKILL.md.fixture")
            for base in (os.path.join(th.home, ".agents", "skills"), os.path.join(th.codex_home, "skills")):
                d = os.path.join(base, "ultimate-brainstorm")
                os.makedirs(d)
                shutil.copyfile(fixture, os.path.join(d, "SKILL.md"))
            data = doctor(self, th, expect_exit=1)
            self.assertEqual(set(c["status"] for c in data["checks"]), {"PASS", "WARN", "FAIL"})


class UnreadPluginList(unittest.TestCase):
    """Native plugins are seen only through `plugin list --json`: without it doctor says "not checked", never "not
    found" (the desktop apps without their CLI on PATH)."""

    def setUp(self):
        inst.require_installer()

    def test_an_app_only_agent_is_not_checked_rather_than_not_found(self):
        with inst.installer_home(tools=("node",)) as th:
            th.mkdir("home", ".claude")
            th.mkdir("home", ".codex")
            checks = {c["id"]: c for c in doctor(self, th)["checks"]}
            for a, cli in (("claude-code", "claude"), ("codex", "codex")):
                c = checks["agent.%s.plugin_list" % a]
                self.assertEqual(c["status"], "WARN", c)
                self.assertIn("plugin list could not be read (%s is not on PATH)" % cli, c["detail"])
                self.assertIn("put the %s CLI on PATH" % cli, c["fix"])
                skill = checks["agent.%s.skill" % a]
                self.assertIn("could not be checked (%s is not on PATH)" % cli, skill["detail"])
                self.assertNotIn("is not installed", skill["detail"])
            ce = checks["stack.compound-engineering"]
            self.assertEqual(ce["status"], "WARN")
            self.assertEqual(ce["detail"], "Compound Engineering plugin not checked for Claude Code (claude is not on "
                                           "PATH), Codex (codex is not on PATH)")

    def test_a_stale_native_plugin_hidden_without_the_cli_is_named_as_not_checked(self):
        with inst.installer_home(tools=("codex", "node")) as th:
            with open(os.path.join(th.home, ".fakecli-registry.json"), "w", encoding="utf-8") as f:
                json.dump({"codex|%s" % os.path.normcase(th.env["CODEX_HOME"]): {
                    "marketplaces": {}, "plugins": {"ultimate-brainstorm@ultimate-brainstorm": {"scope": "user"}}}}, f)
            d = th.mkdir("home", ".agents", "skills", "ultimate-brainstorm")
            shutil.copyfile(os.path.join(paths.FIX_INSTALLER, "skill-v2", "SKILL.md.fixture"),
                            os.path.join(d, "SKILL.md"))
            ids = [c["id"] for c in doctor(self, th, expect_exit=1)["checks"] if c["status"] == "FAIL"]
            self.assertIn("dup.ultimate-brainstorm.codex", ids)
            th.mkdir("home", ".codex")
            shims.remove_fake(th.bin, "codex")  # the Codex app only
            checks = {c["id"]: c for c in doctor(self, th, expect_exit=0)["checks"]}
            self.assertEqual(checks["agent.codex.plugin_list"]["status"], "WARN")
            self.assertIn("a duplicate ultimate-brainstorm", checks["agent.codex.plugin_list"]["detail"])
            self.assertEqual(checks["agent.codex.skill"]["status"], "PASS", "the copy is there")

    def test_a_failing_plugin_list_is_named(self):
        with inst.installer_home(tools=("claude", "node")) as th:
            th.set_scenario([{"tool": "claude", "argv_regex": "^plugin list", "action": "fail", "exit": 1}])
            checks = {c["id"]: c for c in doctor(self, th)["checks"]}
            c = checks["agent.claude-code.plugin_list"]
            self.assertIn("(`claude plugin list --json` failed)", c["detail"])
            self.assertIn("run `claude plugin list --json` to see why", c["fix"])
            self.assertIn("not checked for Claude Code", checks["stack.compound-engineering"]["detail"])


if __name__ == "__main__":
    unittest.main()
