"""Static check: exactly one SKILL.md in the repo; fixtures use SKILL.md.fixture (KIT_SPEC 2, 11.7). Owner: B4."""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "harness"))
import paths  # noqa: E402
import kitcheck  # noqa: E402

vk = kitcheck.load_validate_kit()


class SingleSkillMd(unittest.TestCase):
    def test_no_stray_skill_md(self):
        found = vk.find_skill_md(paths.KIT)
        stray = [f for f in found if f != vk.SK_REL + "/SKILL.md"]
        self.assertEqual(stray, [], "only %s/SKILL.md may exist; fixtures use SKILL.md.fixture" % vk.SK_REL)

    def test_exactly_one(self):
        paths.require(paths.SKILL_MD, owner="B3")
        self.assertEqual(vk.check_single_skill_md(paths.KIT), [])


if __name__ == "__main__":
    unittest.main()
