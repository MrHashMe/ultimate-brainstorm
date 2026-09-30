"""Archive components: offline installs, drift records, content pins in doctor, uninstall, and 'already' answers
(round-3 note NEW-G8-installer-supplychain-3, reviewer notes P3-publish-installer-4 and two reviewer claims). Owner: HG.

- UB_INSTALL_OFFLINE=1 with UB_COMPONENTS_DIR holding the pinned archive installs from that local archive (an
  air-gapped machine sets both), like UB_RELEASE_DIR for the kit; without a local archive the row stays manual.
- A re-install that recreates one skill folder keeps the record of the folder the kit installed earlier, so doctor
  still WARNs stack.<skill>.drift after an edit.
- A component skill folder with no record (kit 2.0.x installed it unpinned with npx, or it was copied by hand) is
  compared with the components.json content pin: doctor WARNs stack.<skill>.unpinned when it differs.
- uninstall keeps the component folders but names the ones the kit copied: the manifest that recorded them is deleted.
- A `marketplace add` answered "already ..." with exit 0 is an earlier registration too, not a moved tag.
Archives come from UB_COMPONENTS_DIR (never the network).
"""

import json
import os
import shutil
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "harness"))
import paths  # noqa: E402
import inst  # noqa: E402
import test_e4_components as e4  # noqa: E402

ARGS = ("--agents", "claude-code", "--components", "core")


def record(th):
    return [c for c in inst.read_manifest(th)["components"] if c["id"] == e4.CID]


class OfflineLocalArchive(unittest.TestCase):
    def setUp(self):
        inst.require_installer()

    def test_offline_installs_from_the_local_archive(self):
        with inst.installer_home(tools=("claude", "node"), extra_env={"UB_INSTALL_OFFLINE": "1"}) as th:
            script = e4.pinned_kit(th, e4.FILES)
            plan = inst.run_plan(th, *ARGS, script=script)
            self.assertIn("codeload", " ".join(plan["manual"]), "no archive there: the by-hand step")
            e4.make_archive(e4.archive_path(th), e4.FILES)
            plan = inst.run_plan(th, *ARGS, script=script)
            rows = [(r["action"], r["how"]) for r in plan["rows"] if r["item"] == "component " + e4.CID]
            self.assertEqual(rows, [("install", "archive")], plan["rows"])
            data, _proc = inst.run_json(th, "install", "--yes", *ARGS, script=script)
            self.assertEqual([r["status"] for r in e4.result(data, "component " + e4.CID)], ["ok"], data["results"])
            self.assertTrue(os.path.isfile(os.path.join(th.claude_home, "skills", "grilling", "SKILL.md")))


class DriftRecord(unittest.TestCase):
    def setUp(self):
        inst.require_installer()

    def test_a_reinstall_keeps_the_record_of_the_folder_it_kept(self):
        with inst.installer_home(tools=("claude", "node")) as th:
            script = e4.pinned_kit(th, e4.FILES)
            e4.make_archive(e4.archive_path(th), e4.FILES)
            inst.run_json(th, "install", "--yes", *ARGS, script=script)
            skills = os.path.join(th.claude_home, "skills")
            shutil.rmtree(os.path.join(skills, "domain-modeling"))
            data, _proc = inst.run_json(th, "install", "--yes", *ARGS, script=script)
            self.assertIn("kept the existing", e4.result(data, "component " + e4.CID)[0]["detail"])
            rec = record(th)
            self.assertEqual([sorted(r["files"]) for r in rec], [["domain-modeling", "grilling"]], rec)
            with open(os.path.join(skills, "grilling", "SKILL.md"), "a", encoding="utf-8") as f:
                f.write("edited after install\n")
            doc, _p = inst.run_json(th, "doctor", script=script, exit=None)
            self.assertEqual([c["status"] for c in e4.check(doc, "stack.grilling.drift:")], ["WARN"], doc["checks"])
            self.assertEqual(e4.check(doc, "stack.grilling.unpinned"), [], "a recorded folder is judged by its record")

    def test_an_unrecorded_folder_that_is_not_the_pinned_content_warns(self):
        with inst.installer_home(tools=("claude", "node")) as th:
            script = e4.pinned_kit(th, e4.FILES)
            skills = os.path.join(th.claude_home, "skills")
            th.write(os.path.join(skills, "grilling", "SKILL.md"), "---\nname: grilling\n---\nunpinned HEAD\n")
            for rel, text in e4.FILES.items():  # domain-modeling: exactly the pinned content, copied by hand
                if rel.startswith("skills/engineering/domain-modeling/"):
                    th.write(os.path.join(skills, "domain-modeling", rel.rsplit("/", 1)[1]), text)
            doc, _p = inst.run_json(th, "doctor", script=script, exit=None)
            warn = e4.check(doc, "stack.grilling.unpinned:")
            self.assertEqual([c["status"] for c in warn], ["WARN"], doc["checks"])
            self.assertIn("is not the pinned content of %s" % e4.CID, warn[0]["detail"])
            self.assertEqual(e4.check(doc, "stack.domain-modeling.unpinned"), [], "the pinned content passes")


class UninstallNamesCopiedComponents(unittest.TestCase):
    def setUp(self):
        inst.require_installer()

    def test_the_folders_the_kit_copied_are_listed(self):
        with inst.installer_home(tools=("claude", "node")) as th:
            script = e4.pinned_kit(th, e4.FILES)
            e4.make_archive(e4.archive_path(th), e4.FILES)
            inst.run_json(th, "install", "--yes", *ARGS, script=script)
            data, _proc = inst.run_json(th, "uninstall", "--yes", script=script)
            skills = os.path.join(th.claude_home, "skills")
            listed = [m for m in data["manual"] if m.startswith("Component skills the kit copied")]
            self.assertEqual(len(listed), 1, data["manual"])
            for skill in ("grilling", "domain-modeling"):
                self.assertIn(paths.posix(os.path.join(skills, skill)), listed[0])
                self.assertTrue(os.path.isdir(os.path.join(skills, skill)), "components stay installed")
            self.assertFalse([n for n in data["next"] if "their own tools" in n], data["next"])


class AlreadyWithExitZero(unittest.TestCase):
    def setUp(self):
        inst.require_installer()

    def test_an_already_answer_with_exit_0_names_the_earlier_registration(self):
        with inst.installer_home(tools=("claude", "node", "git")) as th:
            listed = json.dumps([{"name": "compound-engineering-plugin",
                                  "source": {"source": "github", "repo": "EveryInc/compound-engineering-plugin"},
                                  "installLocation": th.home}])
            th.set_scenario([{"tool": "claude", "argv_regex": "^plugin marketplace add EveryInc/", "action": "static",
                              "stdout": "Marketplace 'compound-engineering-plugin' is already installed\n"},
                             {"tool": "claude", "argv_regex": "^plugin marketplace list --json", "action": "static",
                              "stdout": listed + "\n"},
                             {"tool": "git", "argv_regex": "rev-parse HEAD", "action": "static",
                              "stdout": e4.OTHER + "\n"}])
            data, _proc = inst.run_json(th, "install", "--yes", *ARGS, exit=1)
            res = e4.result(data, "component compound-engineering")[0]
            self.assertEqual(res["status"], "failed")
            self.assertNotIn("the tag moved", res["detail"])
            self.assertIn("was already registered and tracks commit 111111111111", res["detail"])


if __name__ == "__main__":
    unittest.main()
