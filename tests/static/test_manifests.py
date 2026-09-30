"""Static checks: manifests, repo tree, openai.yaml, targets/components/families shapes (KIT_SPEC 11.7). Owner: B4."""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "harness"))
import paths  # noqa: E402
import kitcheck  # noqa: E402

vk = kitcheck.load_validate_kit()


def rel(*parts):
    return os.path.join(paths.KIT, *parts)


class Manifests(unittest.TestCase):
    def setUp(self):
        paths.require(*[rel(*r.split("/")) for r in vk.MANIFESTS.values()], owner="B1")

    def test_manifests_parse_and_have_required_fields(self):
        self.assertEqual(vk.check_manifests(paths.KIT), [])

    def test_codex_default_prompts(self):
        with open(rel(".codex-plugin", "plugin.json"), encoding="utf-8") as f:
            dp = json.load(f)["interface"]["defaultPrompt"]
        self.assertLessEqual(len(dp), 3)
        self.assertTrue(all(len(s) <= 128 for s in dp))

    def test_names(self):
        for key in ("claude_plugin", "codex_plugin", "kimi_plugin", "claude_marketplace", "codex_marketplace"):
            with open(rel(*vk.MANIFESTS[key].split("/")), encoding="utf-8") as f:
                self.assertEqual(json.load(f).get("name"), "ultimate-brainstorm", key)


class Tree(unittest.TestCase):
    def test_no_forbidden_root_entries(self):
        self.assertEqual(vk.check_tree(paths.KIT), [])

    def test_no_init_py_under_tests(self):
        found = []
        for dirpath, dirnames, filenames in os.walk(os.path.join(paths.KIT, "tests")):
            dirnames[:] = [d for d in dirnames if d != "__pycache__"]
            if "__init__.py" in filenames:
                found.append(os.path.relpath(dirpath, paths.KIT))
        self.assertEqual(found, [], "tests/ is not a package (section 2)")


class OpenAIYaml(unittest.TestCase):
    def test_explicit_only_in_codex(self):
        paths.require(rel("skills", "ultimate-brainstorm", "agents", "openai.yaml"), owner="B1")
        self.assertEqual(vk.check_openai_yaml(paths.KIT), [])


class Configs(unittest.TestCase):
    def test_targets_json(self):
        paths.require(paths.TARGETS_JSON, owner="B1")
        self.assertEqual(vk.check_targets(paths.KIT), [])

    def test_components_json(self):
        paths.require(paths.COMPONENTS_JSON, owner="B1")
        self.assertEqual(vk.check_components(paths.KIT), [])

    def test_families_default_json(self):
        paths.require(paths.FAMILIES_DEFAULT, owner="B2")
        self.assertEqual(vk.check_families(paths.KIT), [])


class ValidatorSelfTest(unittest.TestCase):
    """The checks catch the failures they exist for, so a green run means something."""

    def test_detects_bad_manifests(self):
        with tempfile.TemporaryDirectory() as kit:
            def put(r, obj):
                p = os.path.join(kit, *r.split("/"))
                os.makedirs(os.path.dirname(p), exist_ok=True)
                with open(p, "w", encoding="utf-8") as f:
                    json.dump(obj, f)
            put(".claude-plugin/plugin.json", {"version": "2.0.0"})
            put(".claude-plugin/marketplace.json", {"plugins": [{"name": "x", "source": "./nope"}]})
            put(".codex-plugin/plugin.json", {"name": "x", "skills": ".\\skills",
                                              "interface": {"defaultPrompt": ["a", "b", "c", "d" * 200]}})
            put(".agents/plugins/marketplace.json", {"plugins": [{}]})
            put(".kimi-plugin/plugin.json", {"name": "Bad Name"})
            put(".kimi-plugin/marketplace.json", {"version": 2})
            os.makedirs(os.path.join(kit, "hooks"))
            problems = " | ".join(vk.check_manifests(kit) + vk.check_tree(kit))
            for needle in ("missing name", "owner.name", "./nope does not exist", "backslash", "more than 3",
                           "longer than 128", "lacks source", "does not match", 'version must be "2"', "hooks"):
                self.assertIn(needle, problems)

    def test_drift_detector(self):
        # the drift.yml path: tools/validate_kit.py --drift-agents-ts, on an agents.ts shaped like upstream's
        # (tests/static/test_wp7_drift.py covers the multi-line upstream form)
        ts = ("const home = homedir();\n"
              "const claudeHome = process.env.CLAUDE_CONFIG_DIR?.trim() || join(home, '.claude');\n"
              "const codexHome = process.env.CODEX_HOME?.trim() || join(home, '.codex');\n"
              "export const agents = {\n"
              "  'claude-code': { name: 'claude-code', skillsDir: '.claude/skills',"
              " globalSkillsDir: join(claudeHome, 'skills') },\n"
              "  codex: { name: 'codex', skillsDir: '.agents/skills', globalSkillsDir: join(codexHome, 'skills') },\n"
              "  'kimi-code-cli': { name: 'kimi-code-cli', skillsDir: '.agents/skills',"
              " globalSkillsDir: join(home, '.agents/skills') },\n"
              "  zcode: { name: 'zcode', skillsDir: '.zcode/skills', globalSkillsDir: join(home, '.zcode/skills') },\n"
              "};\n")
        self.assertEqual(vk.drift(ts), [])
        self.assertTrue(vk.drift(ts.replace(".zcode/skills", ".zcode/agent-skills")))

    def test_ci_summary_parser(self):
        ci = kitcheck.load_ci()
        text = ("test_a (m.C.test_a) ... skipped 'MISSING DEPENDENCY (B1): install/install.py'\n"
                "test_b (m.C.test_b) ... ok\n\n----\nRan 2 tests in 0.5s\n\nOK (skipped=1)\n")
        res = ci.parse_summary(text)
        self.assertEqual((res["ran"], res["skipped"], res["missing"], res["ok"]), (2, 1, 1, True))
        res = ci.parse_summary("Ran 3 tests in 1.0s\n\nFAILED (failures=1, errors=2)\n")
        self.assertEqual((res["failures"], res["errors"], res["ok"]), (1, 2, False))


if __name__ == "__main__":
    unittest.main()
