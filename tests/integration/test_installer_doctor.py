"""Installer doctor tests (KIT_SPEC 10.5 doctor, 11.4). Owner: B4.

doctor is read-only; each check reaches PASS, WARN and FAIL in at least one case; duplicates across ~/.agents/skills and
~/.codex/skills FAIL with exit 1; a Z.ai base URL in ~/.claude/settings.json WARNs "claude family reclassified as glm".
"""

import os
import re
import shutil
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "harness"))
import paths  # noqa: E402
import fsnap  # noqa: E402
import inst  # noqa: E402

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


if __name__ == "__main__":
    unittest.main()
