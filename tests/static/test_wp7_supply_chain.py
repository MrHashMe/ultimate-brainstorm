"""Supply-chain static checks (audit findings #71, #72, #73, #77 and the WP7 prune items). Owner: WP7.

- Workflows: actions pinned to commit SHAs, no persisted credentials, `permissions: {}` plus least privilege per job,
  timeouts everywhere, ci.py --timeout, a release that attests and never replaces assets, one drift issue.
- components.json pins every third-party source (commit SHAs, exact versions).
- drift: the tested validate_kit.drift reads upstream's multi-line agents.ts form and compares with an explicit map.
- release.py archives exactly install.py's runtime file set; the experimental bundle is gone.
"""

import contextlib
import importlib.util
import io
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "harness"))
import paths  # noqa: E402
import kitcheck  # noqa: E402

vk = kitcheck.load_validate_kit()

# The workflow shape before the fix (release.yml of 2.0.3), for the checker's self-test.
BAD_RELEASE = """name: release
on:
  push:
    tags:
      - "v*"
permissions:
  contents: write
jobs:
  release:
    runs-on: ubuntu-latest
    steps:
      - name: Check out
        uses: actions/checkout@v4
      - name: Run all test suites
        run: python tools/ci.py all
      - name: Publish
        run: gh release upload "$GITHUB_REF_NAME" dist/* --clobber
"""

# Shaped like vercel-labs/skills src/agents.ts (multi-line entries, joins onto declared homes, arrow functions).
UPSTREAM = """import { homedir } from 'os';
import { join } from 'path';

const home = homedir();
const configHome = xdgConfig ?? join(home, '.config');
const codexHome = process.env.CODEX_HOME?.trim() || join(home, '.codex');
const claudeHome = process.env.CLAUDE_CONFIG_DIR?.trim() || join(home, '.claude');

export const agents: Record<AgentType, AgentConfig> = {
  amp: {
    name: 'amp',
    displayName: 'Amp',
    skillsDir: '.agents/skills',
    globalSkillsDir: join(configHome, 'agents/skills'),
  },
  'claude-code': {
    name: 'claude-code',
    displayName: 'Claude Code',
    skillsDir: '.claude/skills',
    globalSkillsDir: join(claudeHome, 'skills'),
    createProjectSkillsDirByDefault: true,
    detectInstalled: async () => {
      return existsSync(claudeHome);
    },
  },
  'openai-codex': {
    name: 'openai-codex',
    displayName: 'Not Codex',
    skillsDir: '.not-codex/skills',
    globalSkillsDir: join(home, '.not-codex/skills'),
  },
  codex: {
    name: 'codex',
    displayName: 'Codex',
    skillsDir: '.agents/skills',
    globalSkillsDir: join(codexHome, 'skills'),
    detectInstalled: async () => {
      return existsSync(codexHome) || existsSync('/etc/codex');
    },
  },
  'kimi-code-cli': {
    name: 'kimi-code-cli',
    displayName: 'Kimi Code CLI',
    skillsDir: '.agents/skills',
    globalSkillsDir: join(home, '.agents/skills'),
    detectInstalled: async () => {
      return existsSync(join(home, '.kimi-code')) || existsSync(join(home, '.kimi'));
    },
  },
  zcode: {
    name: 'zcode',
    displayName: 'ZCode',
    skillsDir: '.zcode/skills',
    globalSkillsDir: join(home, '.zcode/skills'),
    detectInstalled: async () => {
      return isZCodeInstalled();
    },
  },
};
"""


class Workflows(unittest.TestCase):
    def test_repository_workflows(self):
        self.assertEqual(vk.check_workflows(paths.KIT), [])

    def test_checker_catches_the_old_release_workflow(self):
        with tempfile.TemporaryDirectory() as kit:
            wf = os.path.join(kit, ".github", "workflows")
            os.makedirs(wf)
            for name in ("ci.yml", "drift.yml"):
                shutil.copyfile(os.path.join(paths.KIT, ".github", "workflows", name), os.path.join(wf, name))
            with open(os.path.join(wf, "release.yml"), "w", encoding="utf-8") as f:
                f.write(BAD_RELEASE)
            problems = " | ".join(vk.check_workflows(kit))
            for needle in ("permissions must be {}", "actions/checkout@v4 is not pinned", "persist-credentials",
                           "without --timeout", "--clobber", "has no timeout-minutes", "not attested",
                           "exactly one job"):
                self.assertIn(needle, problems)

    def test_pins_are_real_commit_shas_with_versions(self):
        for name in ("ci.yml", "release.yml", "drift.yml"):
            with open(os.path.join(paths.KIT, ".github", "workflows", name), encoding="utf-8") as f:
                for line in f:
                    if "uses:" in line and "./.github" not in line:
                        self.assertRegex(line, r"uses: [\w./-]+@[0-9a-f]{40} # v\d+\.\d+\.\d+$", name)


class Components(unittest.TestCase):
    def test_every_source_is_pinned(self):
        self.assertEqual(vk.check_components(paths.KIT), [])

    def test_unpinned_sources_are_caught(self):
        comp = {"ref": "compound-engineering-v3.28.2"}
        for step in (["npx", "-y", "skills@1.7.0", "add", "mattpocock/skills", "--skill", "grilling"],
                     ["npx", "-y", "skills", "add", "mattpocock/skills#" + "a" * 40],
                     ["claude", "plugin", "marketplace", "add", "phuryn/pm-skills"],
                     ["claude", "plugin", "marketplace", "add", "EveryInc/compound-engineering-plugin@v3"],
                     ["uv", "tool", "install", "specify-cli"]):
            self.assertTrue(vk._unpinned(step, comp), step)
        self.assertIsNone(vk._unpinned(["codex", "plugin", "marketplace", "add", "x/y@v1", "--json"],
                                       {"commit": "b" * 40}))

    def test_default_components_name_commits(self):
        with open(paths.COMPONENTS_JSON, encoding="utf-8") as f:
            comps = json.load(f)["components"]
        grill = comps["mattpocock-grilling"]
        self.assertRegex(grill["commit"], r"^[0-9a-f]{40}$")
        self.assertTrue(grill["archive"]["url"].endswith("/tar.gz/" + grill["commit"]), grill["archive"])
        for agent in ("claude-code", "codex", "kimi", "zcode"):
            self.assertNotIn("steps", grill[agent], "no npx: the skills come from the pinned archive")
            self.assertTrue(grill[agent]["copy_to"])
        self.assertRegex(comps["compound-engineering"]["commit"], r"^[0-9a-f]{40}$")


class Drift(unittest.TestCase):
    def test_upstream_form_has_no_drift(self):
        self.assertEqual(vk.drift(UPSTREAM), [])

    def test_a_moved_folder_is_drift(self):
        problems = vk.drift(UPSTREAM.replace("join(codexHome, 'skills')", "join(codexHome, 'agent-skills')"))
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("codex user folder", problems[0])

    def test_an_unknown_form_is_parser_outdated(self):
        problems = vk.drift(UPSTREAM.replace("globalSkillsDir: join(home, '.zcode/skills')",
                                             "globalSkillsDir: zcodeDir()"))
        self.assertEqual(problems, [p for p in problems if p.startswith("parser-outdated: zcode")])
        self.assertEqual(len(problems), 1)

    def test_cli_report_and_exit_codes(self):
        with tempfile.TemporaryDirectory() as d:
            ts = os.path.join(d, "agents.ts")
            with open(ts, "w", encoding="utf-8") as f:
                f.write(UPSTREAM.replace(".zcode/skills'", ".zcode/other'"))
            report = os.path.join(d, "report.md")
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(vk.main(["--drift-agents-ts", ts, "--report", report, "--json"]), 1)
                self.assertEqual(vk.main(["--drift-agents-ts", os.path.join(d, "missing.ts")]), 2)
            with open(report, encoding="utf-8") as f:
                text = f.read()
            self.assertRegex(text, r"<!-- drift-sha: [0-9a-f]{64} -->")
            self.assertIn("zcode user folder", text)


class ReleaseSet(unittest.TestCase):
    def load_release(self):
        spec = importlib.util.spec_from_file_location("ub_release_wp7", paths.RELEASE_PY)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_archive_set_is_the_staged_set(self):
        import inst
        release = self.load_release()
        with tempfile.TemporaryDirectory() as d:
            kit = inst.kit_source_copy(os.path.join(d, "kit"))
            # a folder named like a top-level exclusion inside a runtime path: staging skips it, so must the archive
            extra = os.path.join(kit, "skills", "tests", "notes.txt")
            os.makedirs(os.path.dirname(extra))
            with open(extra, "w", encoding="utf-8") as f:
                f.write("not a runtime file\n")
            files = release.collect(kit)
            self.assertNotIn("skills/tests/notes.txt", files)
            spec = importlib.util.spec_from_file_location("ub_install_wp7_set", os.path.join(kit, "install",
                                                                                              "install.py"))
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            with open(os.path.join(kit, "install", "targets.json"), encoding="utf-8") as f:
                rps = json.load(f)["runtime_paths"]
            self.assertEqual(sorted(files), sorted(mod.runtime_file_map(kit, rps)))

    def test_experimental_bundle_is_gone(self):
        with open(os.path.join(paths.KIT, ".claude-plugin", "marketplace.json"), encoding="utf-8") as f:
            market = json.load(f)
        self.assertEqual([p["name"] for p in market["plugins"]], ["ultimate-brainstorm"])
        self.assertNotIn("allowCrossMarketplaceDependenciesOn", market)
        self.assertFalse(os.path.exists(os.path.join(paths.KIT, "bundles")))
        with open(paths.TARGETS_JSON, encoding="utf-8") as f:
            self.assertNotIn("bundles", json.load(f)["runtime_paths"])


if __name__ == "__main__":
    unittest.main()
