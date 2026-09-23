"""Installer safety regressions from the integration review (coverage rule, data loss, encodings). Owner: B4."""

import json
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "harness"))
import paths  # noqa: E402
import inst  # noqa: E402

SKILL = "ultimate-brainstorm"
PLUGIN = "ultimate-brainstorm@ultimate-brainstorm"


def plugins(th, tool):
    try:
        with open(os.path.join(th.home, ".fakecli-registry.json"), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return []
    out = []
    for key, reg in data.items():
        if key.startswith(tool + "|"):
            out.extend(reg.get("plugins", {}).keys())
    return out


class CoverageRule(unittest.TestCase):
    def setUp(self):
        inst.require_installer()

    def test_failed_native_install_keeps_the_copy(self):
        with inst.installer_home(tools=("claude", "node")) as th:
            proc = inst.run(th, "install", "--yes", "--components", "none", "--no-native")
            self.assertEqual(proc.returncode, 0, paths.describe(proc))
            dest = inst.copy_dest(th, "claude-code")
            self.assertTrue(os.path.isdir(dest))
            th.add_rules([{"tool": "claude", "argv_regex": r"^plugin install", "action": "fail", "exit": 1,
                           "stderr": "boom network"}])
            proc = inst.run(th, "install", "--yes", "--components", "none")
            self.assertEqual(proc.returncode, 1, paths.describe(proc))
            self.assertTrue(os.path.isdir(dest), "the only copy survives a failed plugin install")

    def test_switch_to_copy_removes_owned_native_first(self):
        with inst.installer_home(tools=("claude", "node")) as th:
            self.assertEqual(inst.run(th, "install", "--yes", "--components", "none").returncode, 0)
            self.assertIn(PLUGIN, plugins(th, "claude"))
            proc = inst.run(th, "install", "--yes", "--components", "none", "--no-native")
            self.assertEqual(proc.returncode, 0, paths.describe(proc))
            self.assertNotIn(PLUGIN, plugins(th, "claude"), "the kit's own plugin is removed before the copy")
            self.assertTrue(os.path.isdir(inst.copy_dest(th, "claude-code")))

    def test_foreign_plugin_blocks_a_second_copy(self):
        with inst.installer_home(tools=("claude", "node")) as th:
            self.assertEqual(inst.run(th, "install", "--yes", "--components", "none").returncode, 0)
            os.remove(os.path.join(th.ub_home, "install-manifest.json"))  # the plugin is now "not ours"
            plan = inst.run_plan(th, "--components", "none", "--no-native")
            copy = inst.rows(plan, agent="claude-code", how="copy")
            self.assertEqual([r["action"] for r in copy], ["blocked"], plan["rows"])

    def test_unowned_copy_is_not_duplicated_by_the_plugin(self):
        with inst.installer_home(tools=("claude", "codex", "node")) as th:
            th.write(os.path.join(th.home, ".agents", "skills", SKILL, "SKILL.md"),
                     "---\nname: ultimate-brainstorm\ndescription: someone else's\n---\n")
            plan = inst.run_plan(th, "--components", "none")
            self.assertEqual(plan["agents"]["codex"]["route"], "copy", plan["agents"])
            self.assertFalse(inst.rows(plan, agent="codex", how="native"))
            self.assertTrue(any("not owned" in w for w in plan["warnings"]), plan["warnings"])

    def test_foreign_shared_folder_is_not_kimi_coverage(self):
        with inst.installer_home(tools=("kimi", "node")) as th:
            th.write(os.path.join(th.home, ".agents", "skills", SKILL, "SKILL.md"),
                     "---\nname: ultimate-brainstorm\ndescription: foreign\n---\n")
            plan = inst.run_plan(th, "--components", "none")
            self.assertNotIn("covered by", plan["agents"]["kimi"].get("reason", ""))
            self.assertTrue(any("not owned" in w for w in plan["warnings"]), plan["warnings"])


class DataSafety(unittest.TestCase):
    def setUp(self):
        inst.require_installer()

    def test_routing_block_never_rewrites_a_non_utf8_file(self):
        with inst.installer_home(tools=("claude", "node")) as th:
            path = os.path.join(th.claude_home, "CLAUDE.md")
            os.makedirs(th.claude_home, exist_ok=True)
            original = "Café règles\n".encode("cp1252")
            with open(path, "wb") as f:
                f.write(original)
            proc = inst.run(th, "install", "--yes", "--components", "none", "--routing-block")
            self.assertEqual(proc.returncode, 4, paths.describe(proc))
            with open(path, "rb") as f:
                self.assertEqual(f.read(), original)

    def test_routing_block_keeps_utf8_bom_and_backs_up(self):
        with inst.installer_home(tools=("claude", "node")) as th:
            path = os.path.join(th.claude_home, "CLAUDE.md")
            os.makedirs(th.claude_home, exist_ok=True)
            with open(path, "wb") as f:
                f.write(b"\xef\xbb\xbfmy rules\n")
            proc = inst.run(th, "install", "--yes", "--components", "none", "--routing-block")
            self.assertEqual(proc.returncode, 0, paths.describe(proc))
            with open(path, "rb") as f:
                data = f.read()
            self.assertTrue(data.startswith(b"\xef\xbb\xbfmy rules\n"))
            self.assertIn(b"ultimate-brainstorm:begin", data)
            self.assertTrue(inst.find_files(os.path.join(th.ub_home, "backups"), r"CLAUDE\.md$"))
            proc = inst.run(th, "uninstall", "--yes")
            self.assertEqual(proc.returncode, 0, paths.describe(proc))
            with open(path, "rb") as f:
                self.assertEqual(f.read(), b"\xef\xbb\xbfmy rules\n")

    def test_purge_refuses_a_folder_without_an_install(self):
        with inst.installer_home(tools=("node",)) as th:
            precious = th.write(os.path.join(th.ub_home, "precious.txt"), "keep me\n")
            proc = inst.run(th, "uninstall", "--yes", "--purge")
            self.assertEqual(proc.returncode, 4, paths.describe(proc))
            self.assertTrue(os.path.isfile(precious))

    def test_purge_keeps_unknown_entries(self):
        with inst.installer_home(tools=("kimi", "node")) as th:
            self.assertEqual(inst.run(th, "install", "--yes", "--components", "none").returncode, 0)
            precious = th.write(os.path.join(th.ub_home, "docs", "thesis.md"), "mine\n")
            proc = inst.run(th, "uninstall", "--yes", "--purge")
            self.assertEqual(proc.returncode, 0, paths.describe(proc))
            self.assertTrue(os.path.isfile(precious))
            self.assertFalse(os.path.exists(os.path.join(th.ub_home, "kit")))

    def test_backups_of_two_scopes_do_not_collide(self):
        with inst.installer_home(tools=("node",), zcode=True) as th:
            for extra in ([], ["--scope", "project", "--project-dir", th.project]):
                proc = inst.run(th, "install", "--yes", "--components", "none", "--agents", "zcode", *extra)
                self.assertEqual(proc.returncode, 0, paths.describe(proc))
            user = os.path.join(th.home, ".zcode", "skills", SKILL, "SKILL.md")
            project = os.path.join(th.project, ".zcode", "skills", SKILL, "SKILL.md")
            for p, tag in ((user, "USER-EDIT"), (project, "PROJECT-EDIT")):
                with open(p, "a", encoding="utf-8") as f:
                    f.write("\n%s\n" % tag)
            proc = inst.run(th, "uninstall", "--yes", "--force", "--scope", "project", "--project-dir", th.project)
            self.assertEqual(proc.returncode, 0, paths.describe(proc))
            texts = [inst.read(p) for p in inst.find_files(os.path.join(th.ub_home, "backups"), r"SKILL\.md$")]
            self.assertTrue(any("USER-EDIT" in t for t in texts), "user-scope edit backed up")
            self.assertTrue(any("PROJECT-EDIT" in t for t in texts), "project-scope edit backed up")

    def test_update_does_not_downgrade_from_an_older_source(self):
        with inst.installer_home(tools=("kimi", "node")) as th:
            self.assertEqual(inst.run(th, "install", "--yes", "--components", "none").returncode, 0)
            older = inst.kit_source_copy(os.path.join(th.tmp, "old-kit"))
            with open(os.path.join(older, "VERSION"), "w", encoding="utf-8") as f:
                f.write("1.9.0\n")
            proc = inst.run(th, "update", "--yes", "--components", "none", "--source", older)
            self.assertEqual(proc.returncode, 4, paths.describe(proc))
            with open(os.path.join(th.ub_home, "kit", "VERSION"), encoding="utf-8") as f:
                self.assertNotEqual(f.read().strip(), "1.9.0")


if __name__ == "__main__":
    unittest.main()
