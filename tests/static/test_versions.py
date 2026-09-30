"""Static checks: one version string everywhere (KIT_SPEC 3.4, 11.7). Owner: B4."""

import json
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "harness"))
import paths  # noqa: E402
import kitcheck  # noqa: E402

vk = kitcheck.load_validate_kit()


class Versions(unittest.TestCase):
    def setUp(self):
        paths.require(os.path.join(paths.KIT, "VERSION"), owner="B1")
        self.version = vk.read_version(paths.KIT)

    def test_version_file(self):
        self.assertRegex(self.version, r"^\d+\.\d+\.\d+$")
        self.assertEqual(self.version, "2.1.0")

    def test_manifests(self):
        for key in vk.VERSIONED:
            path = os.path.join(paths.KIT, *vk.MANIFESTS[key].split("/"))
            paths.require(path, owner="B1")
            with open(path, encoding="utf-8") as f:
                self.assertEqual(json.load(f).get("version"), self.version, vk.MANIFESTS[key])

    def test_skill_metadata(self):
        paths.require(paths.SKILL_MD, owner="B3")
        self.assertEqual(vk.skill_version(paths.KIT), self.version)

    def test_changelog_top_heading(self):
        paths.require(os.path.join(paths.KIT, "CHANGELOG.md"), owner="B1")
        self.assertIn(self.version, vk.changelog_heading(paths.KIT))

    def test_ublib_kit_version(self):
        from ublib import KIT_VERSION
        self.assertEqual(KIT_VERSION, self.version)

    def _cmd(self, rel, args, owner):
        paths.require(os.path.join(paths.KIT, *rel.split("/")), owner=owner)
        out, err = vk.command_version(paths.KIT, rel, args)
        self.assertIsNone(err, "%s\n%s" % (err, out))
        self.assertIn(self.version, out)

    def test_ub_version(self):
        self._cmd(vk.SK_REL + "/scripts/ub.py", ["--version"], "B3")

    def test_family_version(self):
        self._cmd(vk.SK_REL + "/scripts/family.py", ["--version"], "B2")

    def test_bs_version(self):
        self._cmd(vk.SK_REL + "/scripts/bs.py", ["--version"], "B2")

    def test_install_version(self):
        self._cmd("install/install.py", ["version"], "B1")


if __name__ == "__main__":
    unittest.main()
