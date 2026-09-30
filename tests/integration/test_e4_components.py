"""Stack components come from pinned content (audit finding #73, reviewer note P3-publish-installer-4). Owner: E4.

#73 The mattpocock skills are no longer installed with `npx skills@1.7.0` (whose npm dependencies are caret ranges
    resolved at every install). install.py copies them from the upstream commit archive, extracted with _safe_extract,
    and each skill folder must match the SHA-256 of its content pinned in components.json (tree_sha256), so a changed
    archive installs nothing. The manifest records the installed files, and doctor WARNs stack.<skill>.drift after an
    edit. The marketplace components keep their tag, and the clone's HEAD must be the pinned "commit".
P3-4 A marketplace add answered "already ..." means an earlier registration: a different HEAD is reported as that
    registration's ref, with the command that removes it, not as a moved tag.
Archives come from UB_COMPONENTS_DIR (inst.installer_home points it at an empty folder), never from the network.
"""

import hashlib
import io
import json
import os
import sys
import tarfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "harness"))
import paths  # noqa: E402
import inst  # noqa: E402

CID = "mattpocock-grilling"
CE_PIN = "020c5e10d49aed19ee9354917780e94e665f5977"
OTHER = "1111111111111111111111111111111111111111"
FILES = {
    "skills/productivity/grilling/SKILL.md": "---\nname: grilling\ndescription: test copy\n---\nAsk hard questions.\n",
    "skills/productivity/grilling/agents/openai.yaml": "interface:\n  display_name: grilling\n",
    "skills/engineering/domain-modeling/SKILL.md": "---\nname: domain-modeling\ndescription: test copy\n---\nModel.\n",
    "README.md": "not a skill folder\n",
}


def components():
    with open(paths.COMPONENTS_JSON, encoding="utf-8") as f:
        return json.load(f)


def content_sha256(files, folder):
    """The documented pin: SHA-256 of the folder's `sha256sum` listing, sorted by relative path."""
    rows = sorted((rel[len(folder) + 1:], hashlib.sha256(text.encode("utf-8")).hexdigest())
                  for rel, text in files.items() if rel.startswith(folder + "/"))
    return hashlib.sha256("".join("%s  %s\n" % (h, rel) for rel, h in rows).encode("utf-8")).hexdigest()


def make_archive(path, files, top=None, extra=()):
    commit = components()["components"][CID]["commit"]
    with tarfile.open(path, "w:gz") as tf:
        for rel, text in sorted(files.items()):
            data = text.encode("utf-8")
            info = tarfile.TarInfo("%s/%s" % (top or "skills-" + commit, rel))
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
        for info, data in extra:
            tf.addfile(info, io.BytesIO(data))
    return path


def archive_path(th):
    return os.path.join(th.env["UB_COMPONENTS_DIR"], components()["components"][CID]["archive"]["file"])


def pinned_kit(th, files):
    """A kit copy whose components.json pins the content of `files` (the real pins name upstream's bytes)."""
    kit = inst.kit_source_copy(os.path.join(th.root, "pinned kit"))
    path = os.path.join(kit, "install", "components.json")
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    for skill, pin in data["components"][CID]["archive"]["skills"].items():
        pin["sha256"] = content_sha256(files, pin["path"])
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, indent=1)
    return os.path.join(kit, "install", "install.py")


def result(data, item):
    return [r for r in data["results"] if r["item"] == item]


def check(data, prefix):
    return [c for c in data["checks"] if c["id"].startswith(prefix)]


class ArchiveComponent(unittest.TestCase):
    def setUp(self):
        inst.require_installer()

    def test_pinned_content_is_installed_recorded_and_watched(self):
        with inst.installer_home(tools=("claude", "node")) as th:
            script = pinned_kit(th, FILES)
            make_archive(archive_path(th), FILES)
            data, proc = inst.run_json(th, "install", "--yes", "--agents", "claude-code", "--components", "core",
                                       script=script)
            res = result(data, "component " + CID)
            self.assertEqual([r["status"] for r in res], ["ok"], data["results"])
            self.assertIn("verified", res[0]["detail"])
            skills = os.path.join(th.claude_home, "skills")
            self.assertEqual(inst.read(os.path.join(skills, "grilling", "SKILL.md")),
                             FILES["skills/productivity/grilling/SKILL.md"])
            self.assertTrue(os.path.isfile(os.path.join(skills, "domain-modeling", "SKILL.md")))
            self.assertFalse(os.path.exists(os.path.join(skills, "README.md")), "only the pinned folders")
            self.assertEqual(th.fake_calls("npx"), [])
            rec = [c for c in inst.read_manifest(th)["components"] if c["id"] == CID][0]
            self.assertEqual((rec["route"], rec["commit"]), ("archive", components()["components"][CID]["commit"]))
            self.assertEqual(sorted(rec["files"]["grilling"]), ["SKILL.md", "agents/openai.yaml"])
            self.assertTrue(paths.same_path(rec["paths"]["grilling"], os.path.join(skills, "grilling")))
            doc, _p = inst.run_json(th, "doctor", script=script, exit=None)
            self.assertEqual(check(doc, "stack.grilling.drift"), [])
            with open(os.path.join(skills, "grilling", "SKILL.md"), "a", encoding="utf-8") as f:
                f.write("edited after install\n")
            doc, _p = inst.run_json(th, "doctor", script=script, exit=None)
            drift = check(doc, "stack.grilling.drift:")
            self.assertEqual([c["status"] for c in drift], ["WARN"], doc["checks"])
            self.assertEqual(check(doc, "stack.domain-modeling.drift"), [])
            plan = inst.run_plan(th, "--agents", "claude-code", "--components", "core", script=script)
            rows = [r for r in plan["rows"] if r["item"] == "component " + CID]
            self.assertEqual([r["action"] for r in rows], ["unchanged"], "installed skills are never replaced")

    def test_content_that_is_not_the_pinned_content_installs_nothing(self):
        with inst.installer_home(tools=("claude", "node")) as th:
            make_archive(archive_path(th), FILES)  # the real pins name upstream's files, not these
            data, proc = inst.run_json(th, "install", "--yes", "--agents", "claude-code", "--components", "core",
                                       exit=1)
            res = result(data, "component " + CID)
            self.assertEqual([r["status"] for r in res], ["failed"], data["results"])
            self.assertIn("does not match its pinned SHA-256", res[0]["detail"])
            for skill in ("grilling", "domain-modeling"):
                self.assertFalse(os.path.exists(os.path.join(th.claude_home, "skills", skill)))
            self.assertFalse(inst.find_files(os.path.join(th.claude_home, "skills"), r"\.ub-new-"))

    def test_an_unsafe_archive_is_refused(self):
        with inst.installer_home(tools=("claude", "node")) as th:
            script = pinned_kit(th, FILES)
            evil = tarfile.TarInfo("../evil.txt")
            evil.size = 1
            make_archive(archive_path(th), FILES, extra=[(evil, b"x")])
            data, proc = inst.run_json(th, "install", "--yes", "--agents", "claude-code", "--components", "core",
                                       script=script, exit=1)
            res = result(data, "component " + CID)
            self.assertIn("unsafe path", res[0]["detail"])
            self.assertFalse(os.path.exists(os.path.join(th.root, "evil.txt")))

    def test_a_skill_folder_already_there_is_kept(self):
        with inst.installer_home(tools=("claude", "node")) as th:
            script = pinned_kit(th, FILES)
            make_archive(archive_path(th), FILES)
            mine = th.write(os.path.join(th.claude_home, "skills", "grilling", "SKILL.md"), "my own grilling\n")
            data, proc = inst.run_json(th, "install", "--yes", "--agents", "claude-code", "--components", "core",
                                       script=script)
            res = result(data, "component " + CID)
            self.assertIn("kept the existing", res[0]["detail"])
            self.assertEqual(inst.read(mine), "my own grilling\n")
            self.assertTrue(os.path.isfile(os.path.join(th.claude_home, "skills", "domain-modeling", "SKILL.md")))
            rec = [c for c in inst.read_manifest(th)["components"] if c["id"] == CID][0]
            self.assertEqual(sorted(rec["files"]), ["domain-modeling"], "a folder it did not write is not recorded")


class PinnedCommit(unittest.TestCase):
    """pinned_commit_ok: `git -C <clone> rev-parse HEAD` of the marketplace clone against components.json "commit"."""

    def setUp(self):
        inst.require_installer()

    def scenario(self, th, head, already=False):
        listed = json.dumps([{"name": "compound-engineering-plugin",
                              "source": {"source": "github", "repo": "EveryInc/compound-engineering-plugin"},
                              "installLocation": th.home}])
        rules = [{"tool": "claude", "argv_regex": "^plugin marketplace list --json", "action": "static",
                  "stdout": listed + "\n"},
                 {"tool": "git", "argv_regex": "rev-parse HEAD", "action": "static", "stdout": head + "\n"}]
        if already:
            rules.insert(0, {"tool": "claude", "argv_regex": "^plugin marketplace add EveryInc/", "action": "fail",
                             "exit": 1, "stderr": "Marketplace 'compound-engineering-plugin' is already installed"})
        th.set_scenario(rules)

    def install(self, th, code):
        data, _proc = inst.run_json(th, "install", "--yes", "--agents", "claude-code", "--components", "core",
                                    exit=code)
        installs = [c["argv"] for c in th.fake_calls("claude") if c["argv"][:2] == ["plugin", "install"] and
                    c["argv"][2].startswith("compound-engineering@")]
        return result(data, "component compound-engineering")[0], installs

    def test_a_moved_tag_installs_nothing(self):
        with inst.installer_home(tools=("claude", "node", "git")) as th:
            self.scenario(th, OTHER)
            res, installs = self.install(th, 1)
            self.assertEqual(res["status"], "failed")
            self.assertIn("(the tag moved)", res["detail"])
            self.assertEqual(installs, [])

    def test_the_pinned_commit_is_verified(self):
        with inst.installer_home(tools=("claude", "node", "git")) as th:
            self.scenario(th, CE_PIN)
            res, installs = self.install(th, 0)
            self.assertEqual(res["status"], "ok")
            self.assertIn("commit %s verified" % CE_PIN[:12], res["detail"])
            self.assertEqual(len(installs), 1, installs)

    def test_an_earlier_registration_is_named_not_blamed_on_the_tag(self):
        with inst.installer_home(tools=("claude", "node", "git")) as th:
            self.scenario(th, OTHER, already=True)
            res, installs = self.install(th, 1)
            self.assertEqual(res["status"], "failed")
            self.assertNotIn("the tag moved", res["detail"])
            self.assertIn("was already registered and tracks commit 111111111111", res["detail"])
            self.assertIn("claude plugin marketplace remove compound-engineering-plugin", res["detail"])
            self.assertEqual(installs, [])


if __name__ == "__main__":
    unittest.main()
