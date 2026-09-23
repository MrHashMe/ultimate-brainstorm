"""Installer update and uninstall tests (KIT_SPEC 10.5, 11.4 "Update, uninstall"). Owner: B4."""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "harness"))
import paths  # noqa: E402
import inst  # noqa: E402

PLUGIN = "ultimate-brainstorm@ultimate-brainstorm"


def argvs(th, tool):
    return [c["argv"] for c in th.fake_calls(tool)]


class Update(unittest.TestCase):
    def setUp(self):
        inst.require_installer()

    def test_update_restages_kit_and_readds_codex(self):
        with inst.installer_home(tools=("claude", "codex", "node")) as th:
            self.assertEqual(inst.run(th, "install", "--yes", "--components", "none").returncode, 0)
            kit_dir = os.path.join(th.ub_home, "kit")
            os.remove(os.path.join(kit_dir, "VERSION"))
            th.write(os.path.join(kit_dir, "stray.txt"), "not part of the kit\n")
            th.clear_log()
            proc = inst.run(th, "update", "--yes", "--components", "none")
            self.assertEqual(proc.returncode, 0, paths.describe(proc))
            self.assertTrue(os.path.isfile(os.path.join(kit_dir, "VERSION")), "update re-stages the kit")
            self.assertFalse(os.path.exists(os.path.join(kit_dir, "stray.txt")))
            self.assertIn(["plugin", "add", PLUGIN, "--json"], argvs(th, "codex"), "update re-runs codex plugin add")

    def test_update_codex_failure_falls_back_to_remove_add(self):
        with inst.installer_home(tools=("codex", "node")) as th:
            self.assertEqual(inst.run(th, "install", "--yes", "--components", "none").returncode, 0)
            # a changed staged kit makes update re-run the plugin commands (an unchanged one is a no-op)
            th.write(os.path.join(th.ub_home, "kit", "stray.txt"), "not part of the kit\n")
            th.clear_log()
            th.add_rules([{"tool": "codex", "argv_regex": r"^plugin add ultimate-brainstorm", "action": "fail",
                           "exit": 1, "stderr": "simulated add failure", "max_hits": 1}])
            proc = inst.run(th, "update", "--yes", "--components", "none")
            self.assertEqual(proc.returncode, 0, paths.describe(proc))
            calls = argvs(th, "codex")
            removes = [i for i, a in enumerate(calls) if a == ["plugin", "remove", PLUGIN, "--json"]]
            adds = [i for i, a in enumerate(calls) if a == ["plugin", "add", PLUGIN, "--json"]]
            self.assertTrue(removes, "fallback runs codex plugin remove (U-10): %s" % calls)
            self.assertTrue(adds and adds[-1] > removes[-1], "and then add again: %s" % calls)


class Uninstall(unittest.TestCase):
    def setUp(self):
        inst.require_installer()

    def prepared(self, th):
        proc = inst.run(th, "install", "--yes", "--components", "none")
        self.assertEqual(proc.returncode, 0, paths.describe(proc))
        foreign = th.write(os.path.join(th.home, ".agents", "skills", "ultimate-brainstorm", "NOTES.md"), "foreign\n")
        keep_backup = th.write(os.path.join(th.ub_home, "backups", "old", "keep.txt"), "backup\n")
        run_file = th.write(os.path.join(th.project, "brainstorm", "2026-09-23-night-tutor", "run.json"), "{}\n")
        return foreign, keep_backup, run_file

    def test_uninstall_removes_owned_only(self):
        with inst.installer_home(tools=("claude", "codex", "kimi", "node"), zcode=True) as th:
            foreign, keep_backup, run_file = self.prepared(th)
            th.clear_log()
            proc = inst.run(th, "uninstall", "--yes")
            self.assertEqual(proc.returncode, 0, paths.describe(proc))
            for agent in ("kimi", "zcode"):
                self.assertFalse(os.path.exists(inst.copy_dest(th, agent)), agent)
            for p in (foreign, keep_backup, run_file):
                self.assertTrue(os.path.isfile(p), "uninstall must keep %s" % p)
            self.assertIn(["plugin", "uninstall", PLUGIN], [a[:3] for a in argvs(th, "claude")])
            self.assertIn(["plugin", "marketplace", "remove", "ultimate-brainstorm"],
                          [a[:4] for a in argvs(th, "claude")])
            self.assertIn(["plugin", "remove", PLUGIN, "--json"], argvs(th, "codex"))
            self.assertIn(["plugin", "marketplace", "remove", "ultimate-brainstorm", "--json"], argvs(th, "codex"))
            bin_dir = os.path.join(th.ub_home, "bin")
            self.assertFalse(os.path.isdir(bin_dir) and [n for n in os.listdir(bin_dir) if n.startswith("ub")],
                             "launchers are removed")
            text = proc.out + proc.err
            self.assertTrue("/plugins remove" in text or "ZCode" in text, "manual steps are printed")

    def test_uninstall_keeps_user_edits(self):
        with inst.installer_home(tools=("kimi", "node")) as th:
            self.assertEqual(inst.run(th, "install", "--yes", "--components", "none").returncode, 0)
            dest = inst.copy_dest(th, "kimi")
            edited = os.path.join(dest, "SKILL.md") if os.path.isfile(os.path.join(dest, "SKILL.md")) else \
                inst.find_files(dest, r"\.md$")[0]
            with open(edited, "a", encoding="utf-8") as f:
                f.write("\nUSER EDIT 91be\n")
            proc = inst.run(th, "uninstall", "--yes")
            self.assertEqual(proc.returncode, 0, paths.describe(proc))
            survivors = [p for p in inst.find_files(th.home, os.path.basename(edited) + "$")
                         if "USER EDIT 91be" in inst.read(p)]
            self.assertTrue(survivors, "an edited owned file is never silently deleted")

    def test_purge_keeps_backups(self):
        with inst.installer_home(tools=("kimi", "node")) as th:
            _foreign, keep_backup, run_file = self.prepared(th)
            proc = inst.run(th, "uninstall", "--yes", "--purge")
            self.assertEqual(proc.returncode, 0, paths.describe(proc))
            left = sorted(os.listdir(th.ub_home)) if os.path.isdir(th.ub_home) else []
            self.assertEqual(left, ["backups"], "--purge removes UB_HOME except backups/")
            self.assertTrue(os.path.isfile(keep_backup))
            self.assertTrue(os.path.isfile(run_file))


if __name__ == "__main__":
    unittest.main()
