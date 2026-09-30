"""Installer operations from the round-4 bug hunt (phase J, package JH-installer-ops). Owner: JH.

- Launchers: a non-ASCII UB_HOME or Python path works in ub.cmd (any console code page) and ub.ps1 (Windows PowerShell
  5.1), and ub.ps1 no longer exits 0 when its Python is missing.
- --force / --migrate-v1 back up the whole folder they replace (.git, .build, caches; symlinks are listed); an owned
  copy holding files the kit did not put there (.git) counts as edited.
- uninstall runs each native removal in the agent home the manifest recorded; a local-scope (project) Claude install
  whose project folder is gone still uninstalls.
- install.ps1 passes an unquoted comma list (--agents a,b) on as the list that was typed.
- update run from another kit copy stages that copy; the staged kit re-stages the recorded clone. A downgrade blocks
  every row that takes content from the older source. The staged set is the source kit's own runtime_paths.
- --login signs in to the --codex-home / --kimi-home the plugin rows use.
- The no-CLI uninstall remedy names the way out (`uninstall --purge`).
"""

import importlib.util
import io
import json
import os
import re
import subprocess
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "harness"))
import paths  # noqa: E402
import inst  # noqa: E402
import shims  # noqa: E402
import tmphome  # noqa: E402
import test_bootstrap as boot  # noqa: E402

SKILL = "ultimate-brainstorm"
PLUGIN = "ultimate-brainstorm@ultimate-brainstorm"
with open(os.path.join(paths.KIT, "VERSION"), encoding="utf-8") as _f:
    KIT_V = _f.read().strip()
CREATE_NO_WINDOW = 0x08000000  # a private (hidden) console: chcp in the child never changes the test runner's


def registry(th, tool, home):
    """(plugins, marketplaces) of the fake CLI registry for tool in agent home `home`."""
    try:
        with open(os.path.join(th.home, ".fakecli-registry.json"), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        data = {}
    reg = data.get("%s|%s" % (tool, os.path.normcase(home)), {})
    return sorted(reg.get("plugins", {})), sorted(reg.get("marketplaces", {}))


def backups(th):
    """{backed-up tree: its container} for every backup under UB_HOME/backups (containers hold ORIGIN.txt)."""
    out = {}
    for dirpath, _dirs, files in os.walk(os.path.join(th.ub_home, "backups")):
        if "ORIGIN.txt" in files:
            for n in os.listdir(dirpath):
                if os.path.isdir(os.path.join(dirpath, n)):
                    out[os.path.join(dirpath, n)] = dirpath
    return out


def tree(root):
    """{relpath: bytes} of every file under root."""
    out = {}
    for dirpath, _dirs, files in os.walk(root):
        for n in files:
            p = os.path.join(dirpath, n)
            with open(p, "rb") as f:
                out[os.path.relpath(p, root).replace("\\", "/")] = f.read()
    return out


def fill(folder, files):
    for rel, text in files.items():
        p = os.path.join(folder, *rel.split("/"))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "wb") as f:
            f.write(text.encode("utf-8"))


def load_installer():
    spec = importlib.util.spec_from_file_location("ub_install_jh_ops", paths.INSTALL_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def older_kit(th, version="1.9.0"):
    """A kit copy with an older VERSION and a marked SKILL.md (outside the child's TEMP)."""
    older = inst.kit_source_copy(os.path.join(th.root, "old-kit"))
    with open(os.path.join(older, "VERSION"), "w", encoding="utf-8") as f:
        f.write(version + "\n")
    with open(os.path.join(older, "skills", SKILL, "SKILL.md"), "a", encoding="utf-8") as f:
        f.write("\nOLDER-KIT-MARK\n")
    return older


def copy_skill(th, agent):
    with open(os.path.join(inst.copy_dest(th, agent), "SKILL.md"), encoding="utf-8") as f:
        return f.read()


class Setup(unittest.TestCase):
    def setUp(self):
        inst.require_installer()

    def install(self, th, *args, **kw):
        proc = inst.run(th, "install", "--yes", "--components", "none", *args, **kw)
        self.assertEqual(proc.returncode, 0, paths.describe(proc))
        return proc


# ---------------------------------------------------------------------------------------------------------------------
# launchers with a non-ASCII UB_HOME or Python path


@unittest.skipUnless(os.name == "nt", "the .cmd and .ps1 launchers run on Windows only")
class NonAsciiLaunchers(Setup):
    WRAP = (b"@echo off\r\nchcp %2 >nul\r\ncall %1 --version\r\nset \"rc=%ERRORLEVEL%\"\r\nchcp\r\n"
            b"exit /b %rc%\r\n")

    def run_cmd(self, th, launcher, cp, env):
        """launcher --version from an ASCII wrapper that first switches the console to code page cp (the launcher's
        path reaches it as %1, so the wrapper itself holds no non-ASCII byte), then prints the code page again."""
        wrap = os.path.join(th.root, "wrap_cp.bat")
        with open(wrap, "wb") as f:
            f.write(self.WRAP)
        comspec = os.environ.get("COMSPEC") or os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32",
                                                            "cmd.exe")
        # /s: cmd.exe drops only the outer quotes, so both quoted paths (they hold spaces) reach the wrapper intact
        line = '"%s" /d /s /c ""%s" "%s" %d"' % (comspec, wrap, launcher, cp)
        r = subprocess.run(line, env=env, cwd=th.project, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                           stdin=subprocess.DEVNULL, timeout=120, creationflags=CREATE_NO_WINDOW)
        return r.returncode, r.stdout.decode("utf-8", "replace")

    def run_ps1(self, th, launcher, env):
        ps = boot.find_powershell()
        if not ps:
            boot.shell_missing(self, "Windows PowerShell 5.1")
        env = {k: v for k, v in env.items() if k.upper() != "PSMODULEPATH"}
        r = subprocess.run([ps, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", launcher,
                            "--version"], env=env, cwd=th.project, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                           stdin=subprocess.DEVNULL, timeout=120)
        return r.returncode, r.stdout.decode("utf-8", "replace")

    def check(self, th, bin_dir, env):
        for cp in (437, 850, 65001):
            rc, out = self.run_cmd(th, os.path.join(bin_dir, "ub.cmd"), cp, env)
            self.assertEqual(rc, 0, "ub.cmd under code page %s: %s" % (cp, out))
            self.assertIn(KIT_V, out, "ub.cmd under code page %s" % cp)
            self.assertIn(str(cp), out.strip().splitlines()[-1], "ub.cmd restores the code page: %s" % out)
        rc, out = self.run_ps1(th, os.path.join(bin_dir, "ub.ps1"), env)
        self.assertEqual(rc, 0, "ub.ps1: %s" % out)
        self.assertIn(KIT_V, out)

    def test_accented_ub_home_with_ub_home_unset(self):
        with inst.installer_home(tools=("node",), zcode=True) as th:
            ub_home = os.path.join(th.root, "Jos\u00e9", ".ultimate-brainstorm")
            self.install(th, "--agents", "zcode", env_extra={"UB_HOME": ub_home})
            env = dict(th.env)
            env.pop("UB_HOME")  # a fresh terminal: the launcher's own default must work
            self.check(th, os.path.join(ub_home, "bin"), env)

    def test_accented_python_path(self):
        with inst.installer_home(tools=("node",), zcode=True) as th:
            venv = os.path.join(th.root, "Jos\u00e9", "py")
            subprocess.check_call([sys.executable, "-m", "venv", "--without-pip", venv], timeout=300)
            vpy = os.path.join(venv, "Scripts", "python.exe")
            proc = paths.run([vpy, paths.INSTALL_PY, "install", "--yes", "--agents", "zcode", "--components", "none"],
                             env=th.env, cwd=th.project, timeout=600)
            self.assertEqual(proc.returncode, 0, paths.describe(proc))
            with open(os.path.join(th.ub_home, "bin", "ub.cmd"), "rb") as f:
                self.assertIn("Jos\u00e9".encode("utf-8"), f.read(), "the launcher runs the installer's Python")
            self.check(th, os.path.join(th.ub_home, "bin"), dict(th.env))

    def test_ps1_launcher_fails_when_python_is_missing(self):
        with inst.installer_home(tools=("node",), zcode=True) as th:
            self.install(th, "--agents", "zcode")
            ps1 = os.path.join(th.ub_home, "bin", "ub.ps1")
            with open(ps1, "rb") as f:
                data = f.read()
            gone, n = re.subn(rb"'[^'\r\n]*python[^'\r\n]*\.exe'", b"'C:\\\\nope\\\\python.exe'", data, flags=re.I)
            self.assertEqual(n, 1, data)
            with open(ps1, "wb") as f:  # the Python the launcher names was uninstalled
                f.write(gone)
            rc, out = self.run_ps1(th, ps1, dict(th.env))
            self.assertNotEqual(rc, 0, out)
            self.assertIn("python", out.lower())


# ---------------------------------------------------------------------------------------------------------------------
# backups of replaced folders


FOREIGN = {"SKILL.md": "---\nname: ultimate-brainstorm\ndescription: someone else's\nversion: 3.0\n---\n",
           "notes.md": "my notes\n", ".git/HEAD": "ref: refs/heads/main\n", ".git/objects/ab/cdef": "blob\n",
           ".git/refs/heads/main": "0123\n", ".build/cache.json": "{}\n", "__pycache__/x.cpython-311.pyc": "pyc\n"}


class ReplacedFolderBackups(Setup):
    def replace(self, flag, version):
        with inst.installer_home(tools=("node",)) as th:
            dest = inst.copy_dest(th, "claude-code")
            files = dict(FOREIGN)
            files["SKILL.md"] = files["SKILL.md"].replace("3.0", version)
            fill(dest, files)
            self.install(th, "--agents", "claude-code", flag)
            self.assertTrue(os.path.isfile(os.path.join(dest, ".ub-owned")), "the folder was replaced")
            saved = list(backups(th))
            self.assertEqual(len(saved), 1, saved)
            self.assertEqual(tree(saved[0]), tree_of(files), "every file of the replaced folder is in the backup")

    def test_force_backs_up_the_whole_folder(self):
        self.replace("--force", "3.0")

    def test_migrate_v1_backs_up_the_whole_folder(self):
        self.replace("--migrate-v1", "1.0")

    def test_force_lists_symlinks_it_does_not_follow(self):
        with inst.installer_home(tools=("node",)) as th:
            dest = inst.copy_dest(th, "claude-code")
            fill(dest, {"SKILL.md": FOREIGN["SKILL.md"]})
            outside = th.mkdir("outside")
            fill(outside, {"big.txt": "outside\n"})
            try:
                os.symlink(os.path.join(outside, "big.txt"), os.path.join(dest, "link.txt"))
                os.symlink(outside, os.path.join(dest, "linkdir"), target_is_directory=True)
            except (OSError, NotImplementedError) as exc:
                self.skipTest("cannot create symlinks here: %s" % exc)
            self.install(th, "--agents", "claude-code", "--force")
            (saved, container), = backups(th).items()
            with open(os.path.join(container, "LINKS.txt"), encoding="utf-8") as f:
                listed = f.read()
            self.assertIn("link.txt -> %s" % os.path.join(outside, "big.txt"), listed)
            self.assertIn("linkdir -> %s" % outside, listed)
            self.assertEqual(sorted(tree(saved)), ["SKILL.md"])
            self.assertTrue(os.path.isfile(os.path.join(outside, "big.txt")), "a link target is never deleted")

    def test_owned_copy_with_a_git_folder_is_kept_by_uninstall(self):
        with inst.installer_home(tools=("node",), zcode=True) as th:
            self.install(th, "--agents", "zcode")
            dest = inst.copy_dest(th, "zcode")
            fill(dest, {".git/HEAD": "ref: refs/heads/main\n"})
            data, _proc = inst.run_json(th, "uninstall", "--yes")
            self.assertTrue(os.path.isfile(os.path.join(dest, ".git", "HEAD")), "uninstall deleted the user's .git")
            self.assertTrue(any(posix(dest) in w for w in data["warnings"]), data["warnings"])
            _data, _proc = inst.run_json(th, "uninstall", "--yes", "--force")
            self.assertFalse(os.path.exists(dest))
            saved = [t for t in backups(th) if ".git/HEAD" in tree(t)]
            self.assertTrue(saved, "uninstall --force backs up the .git it deletes")

    def test_update_of_an_owned_copy_backs_up_a_git_folder(self):
        with inst.installer_home(tools=("node",), zcode=True) as th:
            self.install(th, "--agents", "zcode")
            dest = inst.copy_dest(th, "zcode")
            fill(dest, {".git/HEAD": "ref: refs/heads/main\n"})
            newer = inst.kit_source_copy(os.path.join(th.root, "newer"))
            fill(os.path.join(newer, "skills", SKILL), {"references/new-file.md": "new\n"})
            proc = inst.run(th, "update", "--yes", "--agents", "zcode", "--components", "none", "--source", newer)
            self.assertEqual(proc.returncode, 0, paths.describe(proc))
            self.assertTrue(os.path.isfile(os.path.join(dest, "references", "new-file.md")))
            saved = [t for t in backups(th) if tree(t).get(".git/HEAD") == b"ref: refs/heads/main\n"]
            self.assertTrue(saved, "the update backs up the .git it replaces")


def tree_of(files):
    return {rel: text.encode("utf-8") for rel, text in files.items()}


def posix(p):
    return os.path.abspath(p).replace("\\", "/")


# ---------------------------------------------------------------------------------------------------------------------
# uninstall: the recorded agent home, a deleted project, a missing CLI


class UninstallRecordedHome(Setup):
    def test_claude_plugin_is_removed_from_the_recorded_config_dir(self):
        with inst.installer_home(tools=("claude", "node")) as th:
            other = th.mkdir("other claude")
            self.install(th, "--agents", "claude-code", "--claude-config-dir", other)
            self.assertEqual(registry(th, "claude", other)[0], [PLUGIN])
            th.clear_log()
            inst.run_json(th, "uninstall", "--yes")
            calls = inst.calls_matching(th, "claude", ["plugin", "uninstall"]) + \
                inst.calls_matching(th, "claude", ["plugin", "marketplace", "remove"])
            self.assertEqual(len(calls), 2, calls)
            for c in calls:
                self.assertTrue(paths.same_path(c["env"].get("CLAUDE_CONFIG_DIR"), other), c)
            self.assertEqual(registry(th, "claude", other), ([], []))
            self.assertFalse(os.path.isdir(os.path.join(th.ub_home, "kit")))

    def test_codex_plugin_is_removed_from_the_recorded_codex_home(self):
        with inst.installer_home(tools=("codex", "node")) as th:
            other = th.mkdir("other codex")
            self.install(th, "--agents", "codex", "--codex-home", other)
            self.assertEqual(registry(th, "codex", other)[0], [PLUGIN])
            inst.run_json(th, "uninstall", "--yes")
            self.assertEqual(registry(th, "codex", other), ([], []))
            self.assertFalse(os.path.isdir(os.path.join(th.ub_home, "kit")))

    def test_two_homes_each_lose_their_plugin_and_marketplace(self):
        for tool, agent, flag in (("claude", "claude-code", "--claude-config-dir"), ("codex", "codex", "--codex-home")):
            with inst.installer_home(tools=(tool, "node")) as th:
                default = th.env["CLAUDE_CONFIG_DIR" if tool == "claude" else "CODEX_HOME"]
                other = th.mkdir("other home")
                self.install(th, "--agents", agent)
                self.install(th, "--agents", agent, flag, other)
                th.clear_log()
                inst.run_json(th, "uninstall", "--yes")
                removes = inst.calls_matching(th, tool, ["plugin", "marketplace", "remove"])
                homes = sorted(os.path.normcase(c["env"]["CLAUDE_CONFIG_DIR" if tool == "claude" else "CODEX_HOME"])
                               for c in removes)
                self.assertEqual(homes, sorted(os.path.normcase(h) for h in (default, other)), removes)
                for home in (default, other):
                    self.assertEqual(registry(th, tool, home), ([], []), (tool, home))


class UninstallDeletedProject(Setup):
    def test_a_local_scope_install_whose_project_is_gone_uninstalls(self):
        with inst.installer_home(tools=("claude", "node")) as th:
            proj = th.mkdir("proj")
            self.install(th, "--scope", "project", "--project-dir", proj, "--agents", "claude-code")
            entry = [e for e in inst.read_manifest(th)["entries"] if e.get("route") == "native"]
            self.assertEqual([e.get("scope") for e in entry], ["local"], entry)
            tmphome.rmtree(proj)
            data, _proc = inst.run_json(th, "uninstall", "--yes")
            self.assertFalse(os.path.isdir(os.path.join(th.ub_home, "kit")))
            self.assertFalse(os.path.isfile(os.path.join(th.ub_home, "install-manifest.json")))
            self.assertEqual(registry(th, "claude", th.env["CLAUDE_CONFIG_DIR"])[1], [], "marketplace removed")
            self.assertTrue(any(posix(proj) in w and "no longer exists" in w for w in data["warnings"]),
                            data["warnings"])


class UninstallWithoutCli(Setup):
    def test_the_no_cli_remedy_names_purge_and_purge_ends_it(self):
        with inst.installer_home(tools=("claude", "node")) as th:
            self.install(th, "--agents", "claude-code")
            shims.remove_fake(th.bin, "claude")
            with open(os.path.join(th.home, ".fakecli-registry.json"), "w", encoding="utf-8") as f:
                json.dump({}, f)  # the user removed the plugin by hand
            data, _proc = inst.run_json(th, "uninstall", "--yes")
            kept = [w for w in data["warnings"] if w.startswith("UB_HOME/kit is the marketplace")]
            self.assertEqual(len(kept), 1, data["warnings"])
            self.assertIn("put it on PATH, then run uninstall again", kept[0])
            self.assertIn("uninstall --purge", kept[0])
            self.assertTrue(os.path.isdir(os.path.join(th.ub_home, "kit")))
            inst.run_json(th, "uninstall", "--yes", "--purge")
            self.assertFalse(os.path.isdir(os.path.join(th.ub_home, "kit")))


# ---------------------------------------------------------------------------------------------------------------------
# install.ps1: comma lists through the documented scriptblock route


class PowerShellCommaLists(unittest.TestCase):
    @classmethod
    def tearDownClass(cls):
        boot.Release.cleanup()

    def setUp(self):
        paths.require(paths.INSTALL_PS1, owner="B1")
        self.ps = boot.find_powershell()
        if not self.ps:
            if os.name == "nt":
                boot.shell_missing(self, "Windows PowerShell 5.1")
            self.skipTest("Windows PowerShell 5.1 is not available")

    def run_scriptblock(self, script, tail, env):
        env = {k: v for k, v in env.items() if k.upper() != "PSMODULEPATH"}
        cmd = "& ([scriptblock]::Create((Get-Content -Raw -LiteralPath '%s'))) %s" % (script.replace("'", "''"), tail)
        return paths.run([self.ps, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", cmd],
                         env=env, timeout=300)

    def test_unquoted_comma_lists_reach_install_py_as_typed(self):
        dist = boot.Release.build(self)
        script = os.path.join(dist, "install.ps1")
        with tmphome.TmpHome(tools=()) as th:
            env = dict(th.env, UB_RELEASE_DIR=dist)  # no real agent CLI on PATH: detection runs none
            proc = self.run_scriptblock(script, "plan --agents claude-code,zcode --with-clis claude,codex "
                                                "--components core,none --json", env)
            text = proc.out + proc.err
            self.assertEqual(proc.returncode, 0, paths.describe(proc))
            for bad in ("unknown agent", "unknown CLI", "unknown component", "claude-code zcode"):
                self.assertNotIn(bad, text)
            plan = paths.last_json(proc.out)
            self.assertEqual(plan["agents"]["zcode"]["route"], "copy", plan["agents"])

    def test_install_py_errors_on_stderr_do_not_abort_the_shim(self):
        dist = boot.Release.build(self)
        script = os.path.join(dist, "install.ps1")
        with tmphome.TmpHome(tools=()) as th:
            env = dict(th.env, UB_RELEASE_DIR=dist)  # no real agent CLI on PATH: detection runs none
            # the caller merges stderr into a pipeline: install.py's error line must not abort the shim
            proc = self.run_scriptblock(script, 'plan --agents claude-code,bogus --components none 2>&1 | '
                                                'ForEach-Object { "$_" }; exit $LASTEXITCODE', env)
            self.assertEqual(proc.returncode, 2, paths.describe(proc))
            self.assertIn("unknown agent 'bogus'", proc.out + proc.err)


# ---------------------------------------------------------------------------------------------------------------------
# update: which kit is staged, downgrades, the source kit's runtime_paths


class UpdateSource(Setup):
    def test_update_from_another_kit_copy_stages_that_copy(self):
        with inst.installer_home(tools=("node",), zcode=True) as th:
            a = inst.kit_source_copy(os.path.join(th.root, "clone-A"))
            b = inst.kit_source_copy(os.path.join(th.root, "clone-B"))
            with open(os.path.join(b, "VERSION"), "w", encoding="utf-8") as f:
                f.write("9.9.1\n")
            fill(os.path.join(b, "skills", SKILL), {"references/new-in-b.md": "B\n"})
            self.install(th, "--agents", "zcode", script=os.path.join(a, "install", "install.py"))
            self.assertTrue(paths.same_path(inst.read_manifest(th).get("source"), a))
            data, _proc = inst.run_json(th, "update", "--yes", "--agents", "zcode", "--components", "none",
                                        script=os.path.join(b, "install", "install.py"))
            self.assertTrue(paths.same_path(data["kit"]["source"], b), data["kit"])
            self.assertTrue(inst.rows(data, item="stage kit %s -> 9.9.1" % KIT_V), data["rows"])
            self.assertTrue(os.path.isfile(os.path.join(inst.copy_dest(th, "zcode"), "references", "new-in-b.md")))
            # the staged kit's own installer still re-stages the recorded clone (now B)
            fill(os.path.join(b, "skills", SKILL), {"references/later-in-b.md": "B2\n"})
            staged = os.path.join(th.ub_home, "kit", "install", "install.py")
            data, _proc = inst.run_json(th, "update", "--yes", "--agents", "zcode", "--components", "none",
                                        script=staged)
            self.assertTrue(paths.same_path(data["kit"]["source"], b), data["kit"])
            self.assertTrue(os.path.isfile(os.path.join(th.ub_home, "kit", "skills", SKILL, "references",
                                                        "later-in-b.md")))

    def test_update_stages_the_source_kits_own_runtime_paths(self):
        with inst.installer_home(tools=("node",), zcode=True) as th:
            self.install(th, "--agents", "zcode")
            newer = inst.kit_source_copy(os.path.join(th.root, "newer"))
            fill(newer, {"extras/needed.txt": "needed\n"})
            tpath = os.path.join(newer, "install", "targets.json")
            with open(tpath, encoding="utf-8") as f:
                targets = json.load(f)
            targets["runtime_paths"].append("extras")
            with open(tpath, "w", encoding="utf-8", newline="\n") as f:
                json.dump(targets, f, indent=1)
            staged = os.path.join(th.ub_home, "kit", "install", "install.py")
            inst.run_json(th, "update", "--yes", "--agents", "zcode", "--components", "none", "--source", newer,
                          script=staged)
            self.assertTrue(os.path.isfile(os.path.join(th.ub_home, "kit", "extras", "needed.txt")),
                            "a path the newer kit's targets.json adds is staged")


class DowngradeGuard(Setup):
    def test_a_downgrade_blocks_every_row_that_takes_the_older_kit(self):
        with inst.installer_home(tools=("node",), zcode=True) as th:
            self.install(th, "--agents", "zcode")
            older = older_kit(th)
            for cmd in ("install", "update"):
                plan = inst.run_plan(th, "--agents", "zcode", "--components", "none", "--source", older) \
                    if cmd == "install" else inst.run_json(th, "update", "--agents", "zcode", "--components", "none",
                                                           "--source", older)[0]
                acting = [(r["item"], r["action"]) for r in plan["rows"]
                          if r["action"] not in ("unchanged", "skip-not-owned", "manual", "blocked")]
                self.assertEqual(acting, [], plan["rows"])
            plan = inst.run_plan(th, "--agents", "zcode", "--components", "none", "--source", older, "--force")
            self.assertTrue(inst.rows(plan, agent="zcode", action="update"), "--force still downgrades everything")

    def test_an_interactive_downgrade_applies_nothing(self):
        with inst.installer_home(tools=("node",), zcode=True) as th:
            self.install(th, "--agents", "zcode")
            older = older_kit(th)
            manifest = os.path.join(th.ub_home, "install-manifest.json")
            with open(manifest, "rb") as f:
                before = f.read()
            mod = load_installer()
            mod.is_tty = lambda: True
            asked = []
            mod.ask = lambda q: asked.append(q) or True
            saved_out, saved_cwd = sys.stdout, os.getcwd()
            try:
                with th.patched_environ():
                    os.chdir(th.project)
                    sys.stdout = io.StringIO()
                    for cmd in ("install", "update"):
                        code = mod.main([cmd, "--agents", "zcode", "--components", "none", "--source", older])
                        self.assertEqual(code, 0)
            finally:
                sys.stdout = saved_out
                os.chdir(saved_cwd)
            self.assertEqual(asked, [], "nothing is left to confirm")
            self.assertNotIn("OLDER-KIT-MARK", copy_skill(th, "zcode"))
            with open(manifest, "rb") as f:
                self.assertEqual(f.read(), before, "the manifest keeps the staged version and source")


# ---------------------------------------------------------------------------------------------------------------------
# --login in a non-default agent home


class LoginHome(Setup):
    def test_codex_login_uses_the_codex_home_flag(self):
        with inst.installer_home(tools=("codex", "node")) as th:
            other = os.path.join(th.root, "work codex home")
            self.install(th, "--agents", "codex", "--codex-home", other, "--login")
            logins = inst.calls_matching(th, "codex", ["login"])
            self.assertEqual(len(logins), 1, logins)
            self.assertTrue(paths.same_path(logins[0]["env"].get("CODEX_HOME"), other), logins[0]["env"])
            with open(os.path.join(other, "auth.json"), "w", encoding="utf-8") as f:
                f.write("{}")  # what a finished sign-in writes
            plan = inst.run_plan(th, "--agents", "codex", "--components", "none", "--codex-home", other, "--login")
            self.assertEqual([r["action"] for r in inst.rows(plan, item="login codex")], ["unchanged"])

    def test_kimi_login_uses_the_kimi_home_flag(self):
        with inst.installer_home(tools=("kimi", "node"), kimi_login=False) as th:
            other = os.path.join(th.root, "work kimi home")
            self.install(th, "--agents", "kimi", "--kimi-home", other, "--login")
            logins = inst.calls_matching(th, "kimi", ["login"])
            self.assertEqual(len(logins), 1, logins)
            self.assertTrue(paths.same_path(logins[0]["env"].get("KIMI_CODE_HOME"), other), logins[0]["env"])


if __name__ == "__main__":
    unittest.main()
