"""Static checks: SKILL.md frontmatter and size (KIT_SPEC 6.13, 11.7). Owner: B4."""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "harness"))
import paths  # noqa: E402
import kitcheck  # noqa: E402

vk = kitcheck.load_validate_kit()


class SkillFrontmatter(unittest.TestCase):
    def setUp(self):
        paths.require(paths.SKILL_MD, owner="B3")
        with open(paths.SKILL_MD, "r", encoding="utf-8") as f:
            self.text = f.read()
        self.fm, err = vk.parse_frontmatter(self.text.lstrip("﻿"))
        self.assertIsNone(err, err)

    def test_all_rules(self):
        self.assertEqual(vk.check_skill(paths.KIT), [])

    def test_first_line(self):
        self.assertEqual(self.text.split("\n", 1)[0].rstrip("\r"), "---")

    def test_portable_keys_only(self):
        self.assertTrue(set(self.fm) <= vk.SKILL_KEYS, set(self.fm) - vk.SKILL_KEYS)
        for key in ("name", "description", "license", "compatibility", "metadata"):
            self.assertIn(key, self.fm)

    def test_name_and_lengths(self):
        self.assertEqual(self.fm["name"], "ultimate-brainstorm")
        self.assertLessEqual(len(self.fm["description"]), 1024)
        self.assertLessEqual(len(self.fm.get("compatibility", "")), 500)
        self.assertLessEqual(os.path.getsize(paths.SKILL_MD), 12 * 1024)

    def test_utf8_lf_no_bom(self):
        with open(paths.SKILL_MD, "rb") as f:
            raw = f.read()
        self.assertFalse(raw.startswith(b"\xef\xbb\xbf"))
        self.assertNotIn(b"\r\n", raw)


class FrontmatterParser(unittest.TestCase):
    def test_parser(self):
        fm, err = vk.parse_frontmatter('---\nname: x\ndescription: "a \\"q\\" b"\nmetadata:\n  version: "2.0.0"\n'
                                       'license: MIT\n---\n# body\n')
        self.assertIsNone(err)
        self.assertEqual(fm["description"], 'a "q" b')
        self.assertEqual(fm["metadata"]["version"], "2.0.0")
        self.assertIsNotNone(vk.parse_frontmatter("# no frontmatter\n")[1])


if __name__ == "__main__":
    unittest.main()
