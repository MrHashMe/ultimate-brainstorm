"""Installer and launcher units from the round-4 bug hunt (phase J, package JH-installer-ops). Owner: JH.

- launch.py render-launcher with a non-ASCII UB_HOME no longer crashes (it wrote ASCII only): the .ps1 gets a BOM and
  the .cmd switches to UTF-8, while an ASCII install keeps BOM-less launchers.
- do_uninstall_native reads "not installed" only from a CLI that ran: a command that could not start (a missing cwd:
  "No such file or directory") fails the row instead of counting the plugin as gone.
- A whole-folder backup lists symlinks in LINKS.txt instead of dropping them; unrecorded() finds what the file hashes
  leave out of an owned copy (.git, .build, links), never Python caches.
- The staged set is the source kit's own runtime_paths (a malformed list falls back to the installer's).
- entry_home: a native entry runs in the home it was installed in; this invocation's home needs no override.
"""

import contextlib
import importlib.util
import io
import json
import os
import shutil
import sys
import tempfile
import types
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "harness"))
import paths  # noqa: E402

BOM = b"\xef\xbb\xbf"


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class RenderLauncher(unittest.TestCase):
    def setUp(self):
        paths.require(paths.LAUNCH_PY, owner="B1")
        self.launch = load(paths.LAUNCH_PY, "ub_launch_jh")
        self.tmp = tempfile.mkdtemp(prefix="ub-jh-launch-")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def render(self, home):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = self.launch.main(["render-launcher", "ub", "--bin", os.path.join(self.tmp, "bin"), "--ub-home", home,
                                     "--", "ub"])
        self.assertEqual(code, 0, out.getvalue())
        got = {}
        for name in ("ub", "ub.cmd", "ub.ps1"):
            with open(os.path.join(self.tmp, "bin", name), "rb") as f:
                got[name] = f.read()
        return got

    def test_a_non_ascii_ub_home_renders(self):
        home = os.path.join(self.tmp, "Jos\u00e9", ".ultimate-brainstorm")
        got = self.render(home)
        self.assertTrue(got["ub.ps1"].startswith(BOM), "Windows PowerShell 5.1 reads a BOM-less .ps1 as ANSI")
        self.assertIn("Jos\u00e9".encode("utf-8"), got["ub.ps1"])
        self.assertIn(b'if "1"=="1" chcp 65001 >nul', got["ub.cmd"])
        self.assertIn("Jos\u00e9".encode("utf-8"), got["ub.cmd"])
        self.assertFalse(got["ub"].startswith(BOM))

    def test_an_ascii_install_keeps_bom_less_launchers(self):
        got = self.render(os.path.join(self.tmp, "ascii", ".ultimate-brainstorm"))
        self.assertFalse(got["ub.ps1"].startswith(BOM))
        self.assertIn(b'if "0"=="1" chcp 65001 >nul', got["ub.cmd"])
        for data in got.values():
            data.decode("ascii")


class Installer(unittest.TestCase):
    def setUp(self):
        paths.require(paths.INSTALL_PY, owner="B1")
        self.mod = load(paths.INSTALL_PY, "ub_install_jh")
        self.tmp = tempfile.mkdtemp(prefix="ub-jh-inst-")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write(self, rel, text="x\n"):
        p = os.path.join(self.tmp, *rel.split("/"))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        return p

    def uninstall_row(self, rc, err):
        ctx = types.SimpleNamespace(child_env=lambda extra=None, agent=None: {})
        row = {"_native_agent": "claude-code", "commands": [["claude", "plugin", "uninstall", "x", "--scope", "local"]],
               "_entry": {"agent": "claude-code", "route": "native"}}
        with mock.patch.object(self.mod, "run_cmd", return_value=(rc, "", err)):
            return self.mod.do_uninstall_native(ctx, row, self.mod.new_updates(), {"commands": []})

    def test_a_cli_that_never_ran_is_not_an_absent_plugin(self):
        self.assertFalse(self.uninstall_row(None, "claude: [Errno 2] No such file or directory: '/gone/project'"))
        self.assertFalse(self.uninstall_row(None, "claude: not found on PATH"))
        self.assertTrue(self.uninstall_row(1, "Error: plugin not found"), "a CLI that ran and said so")

    def test_unrecorded_lists_git_build_and_links_but_not_caches(self):
        root = os.path.join(self.tmp, "copy")
        for rel in ("SKILL.md", ".ub-owned", ".git/HEAD", "sub/.build/x", "scripts/__pycache__/a.pyc", "b.pyc",
                    "sub/link.md", "linkdir/inner.md"):
            self.write("copy/" + rel)
        links = {os.path.join(root, "sub", "link.md"), os.path.join(root, "linkdir")}
        real = os.path.islink
        with mock.patch("os.path.islink", side_effect=lambda p: os.path.normpath(p) in links or real(p)):
            self.assertEqual(self.mod.unrecorded(root), [".git/HEAD", "linkdir", "sub/.build/x", "sub/link.md"])

    def test_a_whole_folder_backup_lists_links_and_keeps_everything_else(self):
        root = os.path.join(self.tmp, "foreign", "ultimate-brainstorm")
        for rel in ("SKILL.md", ".git/HEAD", "__pycache__/c.pyc", "link.md", "linkdir/inner.md"):
            self.write("foreign/ultimate-brainstorm/" + rel)
        links = {os.path.join(root, "link.md"): "/elsewhere/file.md", os.path.join(root, "linkdir"): "/elsewhere/dir"}
        ctx = types.SimpleNamespace(backup_root=os.path.join(self.tmp, "backups"), stamp="stamp")
        real = os.path.islink
        with mock.patch("os.path.islink", side_effect=lambda p: os.path.normpath(p) in links or real(p)), \
                mock.patch("os.readlink", side_effect=lambda p: links[os.path.normpath(p)]):
            base = self.mod.backup_paths(ctx, "claude-code", root, "all")
        saved = sorted(os.path.relpath(os.path.join(d, n), base).replace("\\", "/")
                       for d, _dirs, files in os.walk(base) for n in files)
        self.assertEqual(saved, [".git/HEAD", "SKILL.md", "__pycache__/c.pyc"])
        with open(os.path.join(os.path.dirname(base), "LINKS.txt"), encoding="utf-8") as f:
            self.assertEqual(f.read(), "link.md -> /elsewhere/file.md\nlinkdir -> /elsewhere/dir\n")

    def test_the_source_kits_runtime_paths_are_staged(self):
        ctx = types.SimpleNamespace(targets={"runtime_paths": ["skills", "VERSION"]})
        self.write("kit/install/targets.json", json.dumps({"runtime_paths": ["skills", "extras", "VERSION"]}))
        self.assertEqual(self.mod.source_runtime_paths(ctx, os.path.join(self.tmp, "kit")),
                         ["skills", "extras", "VERSION"])
        for bad in (["../outside"], ["/abs"], ["C:/x"], ["a\\b"], [], "skills", [""]):
            self.write("kit/install/targets.json", json.dumps({"runtime_paths": bad}))
            self.assertEqual(self.mod.source_runtime_paths(ctx, os.path.join(self.tmp, "kit")), ["skills", "VERSION"],
                             bad)

    def test_entry_home(self):
        home = os.path.join(self.tmp, "claude")
        other = os.path.join(self.tmp, "other")
        ctx = types.SimpleNamespace(homes={"claude-code": home, "codex": home})
        self.assertIsNone(self.mod.entry_home(ctx, "claude-code", {"config_dir": home.replace("\\", "/")}))
        self.assertIsNone(self.mod.entry_home(ctx, "claude-code", {}))
        self.assertEqual(self.mod.entry_home(ctx, "claude-code", {"config_dir": other}), other)
        self.assertEqual(self.mod.entry_home(ctx, "codex", {"codex_home": other}), other)
        self.assertEqual(self.mod.entry_home(ctx, "codex", {"codex_home": home, "profile": True}), home)
        self.assertEqual(self.mod.home_env("claude-code", other), {"CLAUDE_CONFIG_DIR": os.path.normpath(other)})
        self.assertIsNone(self.mod.home_env("codex", None))


if __name__ == "__main__":
    unittest.main()
