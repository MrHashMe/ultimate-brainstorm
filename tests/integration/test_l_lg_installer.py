"""Installer fixes from the round-5 findings (phase L, package LG-installer). Owner: LG.

- doctor reads a settings.json ANTHROPIC_BASE_URL, or a config.toml model_provider / base_url, that is not a string as
  no endpoint override (it crashed with no JSON before).
- The staged installer run through another spelling of UB_HOME (a junction or a symlink) is still the staged kit:
  update re-stages the recorded clone, and install keeps that record.
- The backup of an owned copy holding a .git keeps its empty folders (refs/heads after `git gc`, refs/tags,
  objects/info), without which git refuses the backed-up .git.
- install --with-clis: the plan made again after the CLI install is applied only as confirmed. With --yes a blocked
  row in it stops it (exit 4, only the CLI rows applied); interactively a changed plan is shown and asked about again.
- uninstall on Windows keeps the case of CLAUDE.md / AGENTS.md (it wrote through a lower-cased path).
- setup-glm / setup-kimi refuse (exit 2) a UB_HOME/families.json whose way down to providers.<p>.base_url holds a
  value that is not a JSON object (a traceback before); launch.py refuses the same file (LF).
- install.sh forwards install.py's exit code (2 usage, 3 no agent, 4 blocked, 5 cancelled) instead of 1.
"""

import io
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "harness"))
import paths  # noqa: E402
import inst  # noqa: E402
import shims  # noqa: E402
import test_bootstrap as boot  # noqa: E402
import test_j_installer_ops as ops  # noqa: E402

SKILL = "ultimate-brainstorm"


def make_dir_link(link, target):
    """A directory symlink, or a junction on Windows without the symlink privilege; False when neither works."""
    try:
        os.symlink(target, link, target_is_directory=True)
        return True
    except (OSError, NotImplementedError, AttributeError):
        pass
    try:
        import _winapi
        _winapi.CreateJunction(target, link)
        return True
    except (ImportError, OSError, AttributeError):
        return False


def endpoint(doc, cid):
    return [c["status"] for c in doc["checks"] if c["id"] == cid]


class DoctorEndpointValues(ops.Setup):
    def test_a_base_url_that_is_not_a_string(self):
        for url in (7, ["https://api.z.ai/api/anthropic"], True):
            with inst.installer_home(tools=("claude", "node")) as th:
                th.write(os.path.join(th.claude_home, "settings.json"), json.dumps({"env": {"ANTHROPIC_BASE_URL": url}}))
                doc, proc = inst.run_json(th, "doctor", exit=None)
                self.assertEqual(endpoint(doc, "endpoint.claude"), ["PASS"], (url, paths.describe(proc)))

    def test_a_codex_provider_or_base_url_that_is_not_a_string(self):
        for toml, status in (('model_provider = 7\n', "PASS"),
                             ('model_provider = "zai"\n[model_providers.zai]\nbase_url = 7\n', "WARN")):
            with inst.installer_home(tools=("codex", "node")) as th:
                th.write(os.path.join(th.codex_home, "config.toml"), toml)
                doc, proc = inst.run_json(th, "doctor", exit=None)
                self.assertEqual(endpoint(doc, "endpoint.codex"), [status], (toml, paths.describe(proc)))


class StagedKitThroughAnAlias(ops.Setup):
    def test_update_through_an_alias_of_ub_home_restages_the_recorded_clone(self):
        with inst.installer_home(tools=("node",), zcode=True) as th:
            real = os.path.join(th.root, "real-ub")
            link = os.path.join(th.root, "ub-link")
            env = {"UB_HOME": real}
            a = inst.kit_source_copy(os.path.join(th.root, "clone-A"))
            self.install(th, "--agents", "zcode", script=os.path.join(a, "install", "install.py"), env_extra=env)
            if not make_dir_link(link, real):
                self.skipTest("cannot create a directory symlink or junction here")
            try:
                staged = os.path.join(link, "kit", "install", "install.py")
                ops.fill(os.path.join(a, "skills", SKILL), {"references/new-in-a.md": "A\n"})
                data, proc = inst.run_json(th, "update", "--yes", "--agents", "zcode", "--components", "none",
                                           script=staged, env_extra=env)
                self.assertTrue(paths.same_path(data["kit"]["source"], a), (data["kit"], paths.describe(proc)))
                self.assertTrue(os.path.isfile(os.path.join(real, "kit", "skills", SKILL, "references",
                                                            "new-in-a.md")), "the recorded clone was staged")
                # install through the alias is the staged kit re-applying itself (here with one new row, so it writes
                # the manifest): the clone stays the recorded source
                self.install(th, "--agents", "zcode", "--routing-block", script=staged, env_extra=env)
                with open(os.path.join(real, "install-manifest.json"), encoding="utf-8") as f:
                    self.assertTrue(paths.same_path(json.load(f).get("source"), a))
            finally:
                try:
                    os.unlink(link)
                except OSError:
                    os.rmdir(link)


GIT = {".git/HEAD": "ref: refs/heads/main\n", ".git/config": "[core]\n\trepositoryformatversion = 0\n",
       ".git/packed-refs": "# pack-refs with: peeled fully-peeled sorted\n"}
EMPTY = (".git/refs/heads", ".git/refs/tags", ".git/objects/info")  # what `git gc` leaves empty


class GitBackupKeepsEmptyFolders(ops.Setup):
    def check(self, command):
        with inst.installer_home(tools=("node",), zcode=True) as th:
            self.install(th, "--agents", "zcode")
            dest = inst.copy_dest(th, "zcode")
            ops.fill(dest, GIT)
            for rel in EMPTY:
                os.makedirs(os.path.join(dest, *rel.split("/")))
            if command == "update":
                newer = inst.kit_source_copy(os.path.join(th.root, "newer"))
                ops.fill(os.path.join(newer, "skills", SKILL), {"references/newer.md": "newer\n"})
                proc = inst.run(th, "update", "--yes", "--agents", "zcode", "--components", "none", "--source", newer)
            else:
                proc = inst.run(th, "uninstall", "--yes", "--force")
            self.assertEqual(proc.returncode, 0, paths.describe(proc))
            self.assertFalse(os.path.isdir(os.path.join(dest, ".git")), "the copy's .git went with the old tree")
            saved = [t for t in ops.backups(th) if os.path.isdir(os.path.join(t, ".git"))]
            self.assertEqual(len(saved), 1, ops.backups(th))
            for rel in list(GIT) + list(EMPTY):
                self.assertTrue(os.path.exists(os.path.join(saved[0], *rel.split("/"))), (command, rel))

    def test_update(self):
        self.check("update")

    def test_uninstall_force(self):
        self.check("uninstall")


class WithClisReplan(ops.Setup):
    """npm (a fake) installs kimi, so the plan made again after the CLI row has kimi rows the first plan had not."""

    def home(self, agents_md):
        th = inst.installer_home(tools=("claude", "node"), kimi_login=False)
        t = th.__enter__()
        self.addCleanup(th.__exit__, None, None, None)
        pending = t.mkdir("pending")
        kimi = shims.install_fakes(pending, ("kimi",))["kimi"]
        target = os.path.join(t.bin, os.path.basename(kimi))
        if os.name == "nt":
            npm = os.path.join(t.bin, "npm.cmd")
            with open(npm, "w", encoding="ascii", newline="") as f:
                f.write('@copy /y "%s" "%s" >nul\r\n@exit /b 0\r\n' % (kimi, target))
            t.env["KIMI_SHELL_PATH"] = sys.executable  # any existing file stands in for Git Bash
        else:
            npm = os.path.join(t.bin, "npm")
            with open(npm, "w", encoding="ascii", newline="\n") as f:
                f.write('#!/bin/sh\nexec "$UB_FAKE_PY" -c "import shutil, sys; shutil.copy(sys.argv[1], sys.argv[2])" '
                        '%s %s\n' % (shims._sh_quote(kimi), shims._sh_quote(target)))
            os.chmod(npm, 0o755)
        md = os.path.join(t.kimi_home, "AGENTS.md")
        os.makedirs(t.kimi_home, exist_ok=True)
        with open(md, "wb") as f:
            f.write(agents_md)
        return t, md, target

    ARGS = ("install", "--components", "none", "--with-clis", "kimi", "--routing-block")

    def test_yes_with_a_blocked_row_in_the_new_plan_applies_only_the_cli_rows(self):
        th, md, kimi = self.home("# my kimi rules\n".encode("utf-16"))
        data, proc = inst.run_json(th, *(self.ARGS + ("--yes",)), exit=4)
        self.assertTrue(os.path.isfile(kimi), "the CLI row ran")
        self.assertEqual([r["status"] for r in data["results"]], ["ok"], data["results"])
        self.assertTrue(inst.rows({"rows": data["replan"]}, agent="kimi", action="blocked"), data["replan"])
        self.assertEqual(data["exit"], 4)
        self.assertIn("only the CLI rows were applied", data["result"])
        self.assertFalse(os.path.isdir(os.path.join(th.ub_home, "kit")), "no row of the new plan was applied")

    def test_yes_applies_the_new_rows_of_the_plan(self):
        th, md, _kimi = self.home(b"# my kimi rules\n")
        data, proc = inst.run_json(th, *(self.ARGS + ("--yes",)))
        self.assertEqual(data["exit"], 0)
        self.assertIn("ultimate-brainstorm:begin", inst.read(md), "the new kimi routing row was applied")

    def test_interactive_asks_again_when_the_plan_changed(self):
        th, md, _kimi = self.home(b"# my kimi rules\n")
        mod = ops.load_installer()
        mod.is_tty = lambda: True
        asked = []
        answers = iter([True, False])
        mod.ask = lambda q: asked.append(q) or next(answers)
        saved, saved_cwd = (sys.stdout, sys.stderr), os.getcwd()
        try:
            with th.patched_environ():
                os.chdir(th.project)
                sys.stdout, sys.stderr = io.StringIO(), io.StringIO()
                code = mod.main(list(self.ARGS))
                shown = sys.stderr.getvalue()
        finally:
            sys.stdout, sys.stderr = saved
            os.chdir(saved_cwd)
        self.assertEqual(code, 5, shown)
        self.assertEqual(len(asked), 2, asked)
        self.assertIn("The plan changed after the CLI install", shown)
        self.assertEqual(inst.read(md), "# my kimi rules\n", "the new routing row was not applied")


@unittest.skipUnless(os.name == "nt", "normcase changes only Windows paths")
class UninstallKeepsInstructionFileCase(ops.Setup):
    def test_claude_md_and_agents_md_keep_their_names(self):
        with inst.installer_home(tools=("claude", "codex", "node")) as th:
            claude_md = th.write(os.path.join(th.claude_home, "CLAUDE.md"), "# mine\n")
            agents_md = th.write(os.path.join(th.codex_home, "AGENTS.md"), "# mine too\n")
            self.install(th, "--routing-block")
            self.assertIn("ultimate-brainstorm:begin", inst.read(claude_md))
            proc = inst.run(th, "uninstall", "--yes")
            self.assertEqual(proc.returncode, 0, paths.describe(proc))
            self.assertIn("CLAUDE.md", os.listdir(th.claude_home))
            self.assertIn("AGENTS.md", os.listdir(th.codex_home))
            self.assertEqual(inst.read(claude_md), "# mine\n")
            self.assertEqual(inst.read(agents_md), "# mine too\n")


class FamiliesJsonShape(unittest.TestCase):
    def test_a_region_on_a_families_json_that_is_no_object_is_refused(self):
        for doc, where in (([1], "the top level"), ({"providers": "x"}, "providers"),
                           ({"providers": {"glm": "x"}}, "providers.glm"),
                           ({"providers": {"glm": {"base_url": "https://x.test"}}}, "providers.glm.base_url")):
            with inst.installer_home(tools=("claude", "node")) as th:
                th.write(os.path.join(th.ub_home, "families.json"), json.dumps(doc))
                proc = inst.run(th, "setup-glm", "--region", "cn")
                self.assertEqual(proc.returncode, 2, paths.describe(proc))
                self.assertNotIn("Traceback", proc.out + proc.err)
                self.assertIn("%s is not a JSON object" % where, proc.out + proc.err)

    def test_a_single_url_base_url_is_refused_only_where_a_region_is_written(self):
        with inst.installer_home(tools=("claude", "node")) as th:
            fam = th.write(os.path.join(th.ub_home, "families.json"),
                           json.dumps({"providers": {"glm": {"base_url": "https://glm-gateway.example.test/api"}}}))
            proc = inst.run(th, "setup-glm", "--launcher")
            self.assertEqual(proc.returncode, 0, paths.describe(proc))
            self.assertNotIn("families.json", proc.out + proc.err)
            proc = inst.run(th, "setup-glm", "--region", "cn")
            self.assertEqual(proc.returncode, 2, paths.describe(proc))
            self.assertIn("providers.glm.base_url is not a JSON object", proc.out + proc.err)
            self.assertIn("glm-gateway", inst.read(fam))


class ShimExitCode(unittest.TestCase):
    @classmethod
    def tearDownClass(cls):
        boot.Release.cleanup()

    def test_install_sh_forwards_the_installer_exit_code(self):
        sh = boot.find_sh()
        if not sh:
            boot.shell_missing(self, "POSIX sh / Git Bash")
        dist = boot.Release.build(self)
        with tempfile.TemporaryDirectory() as home:
            proc = paths.run([sh, boot.fwd(os.path.join(dist, "install.sh")), "--bogus"],
                             env=boot.shim_env(home, boot.fwd(dist)), timeout=300)
        self.assertEqual(proc.returncode, 2, "install.py's usage error, not the shim's 1\n" + paths.describe(proc))


if __name__ == "__main__":
    unittest.main()
