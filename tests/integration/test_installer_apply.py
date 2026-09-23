"""Installer apply tests (KIT_SPEC 4.14, 10.3, 10.4, 11.4 "Install"). Owner: B4."""

import contextlib
import hashlib
import importlib.util
import io
import json
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "harness"))
import paths  # noqa: E402
import fsnap  # noqa: E402
import inst  # noqa: E402

SECRETS = {"ZAI_API_KEY": "zai-SECRET-value-0001", "ZAI_PAYG_API_KEY": "payg-SECRET-value-0002",
           "KIMI_API_KEY": "kimi-SECRET-value-0003", "KIMI_CODE_API_KEY": "kcode-SECRET-value-0004",
           "OPENAI_API_KEY": "sk-openai-SECRET-0005", "ANTHROPIC_API_KEY": "sk-ant-SECRET-0006",
           "GITHUB_TOKEN": "ghp-SECRET-value-0007"}


def sha256(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def load_targets():
    with open(paths.TARGETS_JSON, encoding="utf-8") as f:
        return json.load(f)


def load_components():
    with open(paths.COMPONENTS_JSON, encoding="utf-8") as f:
        return json.load(f)


class InstallBasics(unittest.TestCase):
    def setUp(self):
        inst.require_installer()

    def test_install_creates_markers_manifest_and_kit(self):
        with inst.installer_home(zcode=True) as th:
            proc = inst.run(th, "install", "--yes", "--components", "none")
            self.assertEqual(proc.returncode, 0, paths.describe(proc))
            kit_dir = os.path.join(th.ub_home, "kit")
            self.assertTrue(os.path.isfile(os.path.join(kit_dir, "VERSION")))
            self.assertTrue(os.path.isdir(os.path.join(kit_dir, "skills", "ultimate-brainstorm", "scripts")))
            for banned in ("tests", "tools", ".git", ".github", ".build"):
                self.assertFalse(os.path.exists(os.path.join(kit_dir, banned)), "staged kit must exclude " + banned)
            self.assertEqual(inst.find_files(kit_dir, r"__pycache__|\.pyc$"), [])
            manifest = inst.read_manifest(th)
            self.assertEqual((manifest["schema"], manifest["kit"], manifest["version"]),
                             (1, "ultimate-brainstorm", "2.0.0"))
            for key in ("commit", "installed_at", "entries", "components", "launchers", "routing_blocks"):
                self.assertIn(key, manifest)
            copies = [e for e in manifest["entries"] if e.get("route") == "copy"]
            self.assertEqual(sorted(e["agent"] for e in copies), ["kimi", "zcode"])
            for e in copies:
                dest = e["path"]
                self.assertTrue(paths.same_path(dest, inst.copy_dest(th, e["agent"])), dest)
                marker = os.path.join(dest, inst.MARKER)
                self.assertTrue(os.path.isfile(marker), marker)
                with open(marker, encoding="utf-8") as f:
                    m = json.load(f)
                self.assertEqual((m["kit"], m["version"]), ("ultimate-brainstorm", "2.0.0"))
                self.assertTrue(paths.same_path(m["manifest"], os.path.join(th.ub_home, "install-manifest.json")))
                self.assertIn("installed_at", m)
                self.assertTrue(e["files"], "manifest records a SHA-256 per file")
                for rel, digest in e["files"].items():
                    p = os.path.join(dest, *rel.split("/"))
                    self.assertTrue(os.path.isfile(p), rel)
                    self.assertEqual(sha256(p), digest, rel)
                self.assertTrue(os.path.isdir(os.path.join(dest, "scripts")))
            natives = sorted(e["agent"] for e in manifest["entries"] if e.get("route") == "native")
            self.assertEqual(natives, ["claude-code", "codex"])
            # native rows execute exactly the argv lists from targets.json
            t = load_targets()["agents"]
            kit_posix = paths.posix(kit_dir)
            for agent, tool in (("claude-code", "claude"), ("codex", "codex")):
                native = t[agent]["native"]
                for key in ("marketplace_add", "install"):
                    argv = [a.replace("{kit_dir}", kit_posix).replace("{claude_scope}", "user")
                            for a in native[key]]
                    self.assertTrue(inst.calls_matching(th, tool, argv[1:]) and
                                    any(inst.norm(c["argv"]) == inst.norm(argv[1:]) for c in th.fake_calls(tool)),
                                    "%s not run exactly: %s" % (key, argv))
            for launcher in ("ub",):
                names = os.listdir(os.path.join(th.ub_home, "bin"))
                self.assertTrue(any(n.startswith(launcher) for n in names), names)

    def test_second_run_is_unchanged(self):
        with inst.installer_home(zcode=True) as th:
            proc = inst.run(th, "install", "--yes", "--components", "none")
            self.assertEqual(proc.returncode, 0, paths.describe(proc))
            plan = inst.run_plan(th, "--components", "none")
            not_unchanged = [(r["agent"], r["item"], r["action"]) for r in plan["rows"] if r["action"] != "unchanged"]
            self.assertEqual(not_unchanged, [], "a second run shows every row unchanged")
            before = fsnap.snapshot(th.home)
            proc = inst.run(th, "install", "--yes", "--components", "none")
            self.assertEqual(proc.returncode, 0, paths.describe(proc))
            fsnap.assert_unchanged(self, before, fsnap.snapshot(th.home),
                                   ignore=["install.log"] + inst.home_snapshot_ignores(), msg="second install")

    def test_non_tty_without_yes_applies_nothing(self):
        with inst.installer_home() as th:
            before = fsnap.snapshot(th.root)
            proc = inst.run(th, "install", "--components", "none")
            self.assertEqual(proc.returncode, 0, paths.describe(proc))
            self.assertIn("--yes", proc.out + proc.err)
            fsnap.assert_unchanged(self, before, fsnap.snapshot(th.root),
                                   ignore=["fake.log", "fake.log.*"] + inst.home_snapshot_ignores(), msg="no --yes")
            self.assertFalse(os.path.exists(os.path.join(th.ub_home, "kit")))


class Coverage(unittest.TestCase):
    def setUp(self):
        inst.require_installer()

    def test_codex_copy_route_skips_kimi_copy(self):
        with inst.installer_home(tools=("codex", "kimi", "node"), versions={"codex": "codex-cli 0.140.0"}) as th:
            proc = inst.run(th, "install", "--yes", "--components", "none")
            self.assertEqual(proc.returncode, 0, paths.describe(proc))
            agents_copy = inst.copy_dest(th, "codex")
            self.assertTrue(os.path.isfile(os.path.join(agents_copy, inst.MARKER)))
            self.assertFalse(os.path.exists(inst.copy_dest(th, "kimi")),
                             "Kimi reads ~/.agents/skills: its own copy would be a duplicate")
            self.assertFalse(os.path.exists(os.path.join(th.codex_home, "skills", "ultimate-brainstorm")),
                             "never the deprecated ~/.codex/skills (U-11)")

    def test_codex_native_kimi_gets_own_copy(self):
        with inst.installer_home(tools=("codex", "kimi", "node")) as th:
            proc = inst.run(th, "install", "--yes", "--components", "none")
            self.assertEqual(proc.returncode, 0, paths.describe(proc))
            self.assertTrue(os.path.isfile(os.path.join(inst.copy_dest(th, "kimi"), inst.MARKER)))
            self.assertFalse(os.path.exists(inst.copy_dest(th, "codex")))


class Ownership(unittest.TestCase):
    def setUp(self):
        inst.require_installer()

    def test_edited_owned_file_backup_update(self):
        with inst.installer_home(tools=("kimi", "node")) as th:
            self.assertEqual(inst.run(th, "install", "--yes", "--components", "none").returncode, 0)
            dest = inst.copy_dest(th, "kimi")
            entry = [e for e in inst.read_manifest(th)["entries"] if e["agent"] == "kimi"][0]
            rel = sorted(entry["files"])[0]
            target = os.path.join(dest, *rel.split("/"))
            with open(target, "a", encoding="utf-8") as f:
                f.write("\nUSER EDIT 7f3a\n")
            plan = inst.run_plan(th, "--components", "none")
            self.assertTrue(inst.rows(plan, agent="kimi", action="backup+update"), plan["rows"])
            proc = inst.run(th, "install", "--yes", "--components", "none")
            self.assertEqual(proc.returncode, 0, paths.describe(proc))
            self.assertEqual(sha256(target), entry["files"][rel], "the file is restored to the kit version")
            backups = [p for p in inst.find_files(os.path.join(th.ub_home, "backups"), re.escape(rel.split("/")[-1]))]
            self.assertTrue(any("USER EDIT 7f3a" in inst.read(p) for p in backups),
                            "the edited file is backed up under UB_HOME/backups")

    def test_foreign_folder_skip_then_force(self):
        with inst.installer_home(tools=("kimi", "node")) as th:
            dest = inst.copy_dest(th, "kimi")
            mine = th.write(os.path.join(dest, "NOTES.md"), "my own skill 4d2c\n")
            plan = inst.run_plan(th, "--components", "none")
            self.assertTrue(inst.rows(plan, agent="kimi", action="skip-not-owned"), plan["rows"])
            self.assertEqual(inst.run(th, "install", "--yes", "--components", "none").returncode, 0)
            self.assertFalse(os.path.exists(os.path.join(dest, inst.MARKER)))
            self.assertEqual(inst.read(mine), "my own skill 4d2c\n")
            proc = inst.run(th, "install", "--yes", "--components", "none", "--force")
            self.assertEqual(proc.returncode, 0, paths.describe(proc))
            self.assertTrue(os.path.isfile(os.path.join(dest, inst.MARKER)))
            backups = inst.find_files(os.path.join(th.ub_home, "backups"), r"NOTES\.md$")
            self.assertTrue(backups, "--force backs the foreign folder up first")

    def test_v1_folder_migrate(self):
        with inst.installer_home(tools=("kimi", "node")) as th:
            dest = inst.copy_dest(th, "kimi")
            with open(os.path.join(paths.FIX_INSTALLER, "v1", "SKILL.md.fixture"), encoding="utf-8") as f:
                th.write(os.path.join(dest, "SKILL.md"), f.read())
            plan = inst.run_plan(th, "--components", "none")
            self.assertTrue(inst.rows(plan, agent="kimi", action="migrate-v1") or
                            inst.rows(plan, agent="kimi", action="skip-not-owned"), plan["rows"])
            self.assertTrue(any("--migrate-v1" in w for w in plan["warnings"]), plan["warnings"])
            plan = inst.run_plan(th, "--components", "none", "--migrate-v1")
            self.assertTrue(inst.rows(plan, agent="kimi", action="migrate-v1"), plan["rows"])
            proc = inst.run(th, "install", "--yes", "--components", "none", "--migrate-v1")
            self.assertEqual(proc.returncode, 0, paths.describe(proc))
            self.assertTrue(os.path.isfile(os.path.join(dest, inst.MARKER)))
            backups = inst.find_files(os.path.join(th.ub_home, "backups"), r"SKILL\.md$")
            self.assertTrue(any('version: "1.0"' in inst.read(p) for p in backups))


class Atomicity(unittest.TestCase):
    """A failure injected during the swap leaves the old tree intact and cleans up the temp folders (10.4)."""

    def setUp(self):
        inst.require_installer()

    def test_swap_failure_keeps_old_tree(self):
        with inst.installer_home(tools=("kimi", "node")) as th:
            src = inst.kit_source_copy(os.path.join(th.root, "src kit"))
            proc = inst.run(th, "install", "--yes", "--components", "none", "--source", src)
            self.assertEqual(proc.returncode, 0, paths.describe(proc))
            dest = inst.copy_dest(th, "kimi")
            kit_dir = os.path.join(th.ub_home, "kit")
            # change the source so both the staged kit and the Kimi copy need an update
            with open(os.path.join(src, "skills", "ultimate-brainstorm", "scripts", "ublib", "__init__.py"), "a",
                      encoding="utf-8") as f:
                f.write("\n# source changed by the atomicity test\n")
            snap_copy, snap_kit = fsnap.snapshot(dest), fsnap.snapshot(kit_dir)

            spec = importlib.util.spec_from_file_location("ub_install_under_test", paths.INSTALL_PY)
            mod = importlib.util.module_from_spec(spec)
            real_replace, real_rename = os.replace, os.rename
            state = {"raised": 0}

            def failing(real):
                def fn(a, b, *args, **kw):
                    if not state["raised"] and re.search(r"[.-]new-", os.path.basename(str(a).rstrip("/\\"))):
                        state["raised"] += 1
                        raise OSError("injected swap failure")
                    return real(a, b, *args, **kw)
                return fn

            out, err = io.StringIO(), io.StringIO()
            cwd = os.getcwd()
            with th.patched_environ():
                os.chdir(th.project)
                os.replace, os.rename = failing(real_replace), failing(real_rename)
                try:
                    spec.loader.exec_module(mod)
                    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                        try:
                            rc = mod.main(["install", "--yes", "--components", "none", "--source", src])
                        except SystemExit as e:
                            rc = e.code
                finally:
                    os.replace, os.rename = real_replace, real_rename
                    os.chdir(cwd)
            self.assertEqual(state["raised"], 1, "the swap was attempted (output: %s %s)" % (out.getvalue()[-800:],
                                                                                            err.getvalue()[-800:]))
            self.assertNotEqual(rc, 0, "a failed swap is reported")
            fsnap.assert_unchanged(self, snap_copy, fsnap.snapshot(dest), msg="kimi copy after failed swap")
            fsnap.assert_unchanged(self, snap_kit, fsnap.snapshot(kit_dir), msg="staged kit after failed swap")
            leftovers = [n for base in (os.path.dirname(dest), th.ub_home) for n in os.listdir(base)
                         if re.search(r"(ub-new|ub-old|kit\.new|kit\.old)", n)]
            self.assertEqual(leftovers, [], "temp folders are cleaned up")


class Components(unittest.TestCase):
    def setUp(self):
        inst.require_installer()

    def expected_steps(self, comp, agent):
        return load_components()["components"][comp][agent]["steps"]

    def test_component_argv_exact(self):
        with inst.installer_home(tools=("claude", "codex", "npx", "node")) as th:
            proc = inst.run(th, "install", "--yes", "--components", "core")
            self.assertEqual(proc.returncode, 0, paths.describe(proc))
            for agent, tool in (("claude-code", "claude"), ("codex", "codex")):
                for step in self.expected_steps("compound-engineering", agent):
                    self.assertTrue(any(c["argv"] == step[1:] for c in th.fake_calls(tool)),
                                    "missing exact CE step %s" % step)
            # [U-18] CE Claude install resolves the marketplace name from `marketplace list --json`
            self.assertTrue(any(c["argv"][:3] == ["plugin", "install", "compound-engineering@compound-engineering-plugin"]
                                for c in th.fake_calls("claude")), [c["argv"] for c in th.fake_calls("claude")])
            npx = [c for c in th.fake_calls("npx")]
            for agent in ("claude-code", "codex"):
                step = self.expected_steps("mattpocock-grilling", agent)[0]
                hits = [c for c in npx if c["argv"] == step[1:]]
                self.assertTrue(hits, "missing exact grilling step for %s: %s" % (agent, step))
                if agent == "codex":
                    self.assertTrue(paths.same_path(hits[0]["cwd"], th.home), "codex skills step runs in ~")
            for c in npx:
                self.assertEqual(c["env"].get("DISABLE_TELEMETRY"), "1", "npx skills runs with DISABLE_TELEMETRY=1")

    def test_node_20_makes_npx_rows_manual(self):
        with inst.installer_home(tools=("claude", "npx", "node"), versions={"node": "v20.11.0"}) as th:
            plan = inst.run_plan(th, "--components", "core")
            grill = [r for r in plan["rows"] if "grilling" in r["item"]]
            self.assertTrue(grill)
            self.assertTrue(all(r["action"] == "manual" for r in grill), grill)

    def test_offline_rows_are_manual(self):
        with inst.installer_home(tools=("claude", "codex", "npx", "node"),
                                 extra_env={"UB_INSTALL_OFFLINE": "1"}) as th:
            plan = inst.run_plan(th, "--components", "core")
            comp = [r for r in plan["rows"] if "component" in r["item"] or "grilling" in r["item"]
                    or "compound" in r["item"]]
            self.assertTrue(comp)
            self.assertTrue(all(r["action"] == "manual" for r in comp), comp)


class RoutingBlock(unittest.TestCase):
    BEGIN, END = "<!-- ultimate-brainstorm:begin -->", "<!-- ultimate-brainstorm:end -->"

    def setUp(self):
        inst.require_installer()

    def test_inserted_once_and_removed_exactly(self):
        with inst.installer_home(tools=("claude", "codex", "node")) as th:
            claude_md = th.write(os.path.join(th.claude_home, "CLAUDE.md"), "# Mine\n\nkeep this line\n")
            original = inst.read(claude_md)
            for _ in range(2):
                proc = inst.run(th, "install", "--yes", "--components", "none", "--routing-block")
                self.assertEqual(proc.returncode, 0, paths.describe(proc))
                text = inst.read(claude_md)
                self.assertEqual(text.count(self.BEGIN), 1)
                self.assertEqual(text.count(self.END), 1)
                self.assertIn("keep this line", text)
            agents_md = os.path.join(th.codex_home, "AGENTS.md")
            self.assertEqual(inst.read(agents_md).count(self.BEGIN), 1)
            self.assertFalse(os.path.exists(os.path.join(th.home, ".zcode", "AGENTS.md")), "detected agents only")
            proc = inst.run(th, "uninstall", "--yes")
            self.assertEqual(proc.returncode, 0, paths.describe(proc))
            text = inst.read(claude_md)
            self.assertNotIn(self.BEGIN, text)
            self.assertEqual(text.strip(), original.strip(), "uninstall removes exactly the inserted block")
            if os.path.exists(agents_md):
                self.assertNotIn(self.BEGIN, inst.read(agents_md))


class ArgvAudit(unittest.TestCase):
    def setUp(self):
        inst.require_installer()

    def test_no_secret_in_any_command(self):
        with inst.installer_home(tools=("claude", "codex", "kimi", "npx", "node"), extra_env=SECRETS, zcode=True) as th:
            proc = inst.run(th, "install", "--yes", "--components", "core")
            self.assertEqual(proc.returncode, 0, paths.describe(proc))
            calls = th.fake_calls()
            self.assertTrue(calls)
            for c in calls:
                for arg in c["argv"]:
                    for name, value in SECRETS.items():
                        self.assertNotIn(value, arg, "%s value in argv of %s" % (name, c["tool"]))
            logs = [th.log_text(), proc.out, proc.err]
            log_path = os.path.join(th.ub_home, "install.log")
            if os.path.isfile(log_path):
                logs.append(inst.read(log_path))
            logs.append(json.dumps(inst.read_manifest(th)))
            for text in logs:
                for name, value in SECRETS.items():
                    self.assertNotIn(value, text, "%s value leaked into output or logs" % name)


if __name__ == "__main__":
    unittest.main()
