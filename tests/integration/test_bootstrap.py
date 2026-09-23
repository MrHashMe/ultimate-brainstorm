"""Bootstrap shim tests (KIT_SPEC 10.7, 11.4 "Bootstrap"). Owner: B4.

- `sh -n install.sh` passes (the template).
- Git Bash / POSIX sh: the rendered install.sh with UB_RELEASE_DIR succeeds; a wrong hash aborts before extraction;
  root is refused (POSIX CI only, when running as root or with passwordless sudo).
- PowerShell 5.1 (`powershell -NoProfile -File`, when available): the same cases for install.ps1, plus a parse check
  via [System.Management.Automation.Language.Parser]::ParseFile for the template and the rendered file.
Shell availability is an environment property: missing shells skip (never "MISSING DEPENDENCY").
"""

import glob
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "harness"))
import paths  # noqa: E402
import tmphome  # noqa: E402


def find_sh():
    """A POSIX sh: $UB_TEST_SH, else Git Bash on Windows (never WSL's System32 bash), else `sh` on PATH."""
    override = os.environ.get("UB_TEST_SH")
    if override and os.path.isfile(override):
        return override
    if os.name == "nt":
        cands = []
        for base in (os.environ.get("ProgramFiles", r"C:\Program Files"), os.environ.get("ProgramFiles(x86)", ""),
                     os.environ.get("LOCALAPPDATA", "")):
            if base:
                cands += [os.path.join(base, "Git", "bin", "bash.exe"),
                          os.path.join(base, "Programs", "Git", "bin", "bash.exe")]
        git = shutil.which("git")
        if git:
            root = os.path.dirname(os.path.dirname(git))
            cands += [os.path.join(root, "bin", "bash.exe"), os.path.join(root, "usr", "bin", "bash.exe")]
        for c in cands:
            if os.path.isfile(c) and "system32" not in c.lower():
                return c
        return None
    return shutil.which("sh")


def find_powershell():
    return shutil.which("powershell") if os.name == "nt" else None


def read_bytes(path):
    with open(path, "rb") as f:
        return f.read()


def fwd(p):
    return p.replace("\\", "/")


class Release(object):
    """Render the release assets once per test class."""
    dir = None
    tmp = None

    @classmethod
    def build(cls, tc):
        paths.require(paths.RELEASE_PY, paths.INSTALL_SH, paths.INSTALL_PS1, paths.INSTALL_PY, owner="B1")
        if cls.dir:
            return cls.dir
        cls.tmp = tempfile.mkdtemp(prefix="ub-release-")
        out = os.path.join(cls.tmp, "dist")
        with open(os.path.join(paths.KIT, "VERSION"), encoding="utf-8") as f:
            version = f.read().strip()
        proc = paths.run_py(paths.RELEASE_PY, ["--version", version, "--owner", "test", "--out", out], cwd=paths.KIT,
                            timeout=600)
        tc.assertEqual(proc.returncode, 0, paths.describe(proc))
        cls.dir = out
        cls.version = version
        return out

    @classmethod
    def cleanup(cls):
        if cls.tmp:
            tmphome.rmtree(cls.tmp)
        cls.dir = cls.tmp = None


def tampered_copy(src_dir, dest_dir, pattern):
    shutil.copytree(src_dir, dest_dir)
    hits = glob.glob(os.path.join(dest_dir, pattern))
    for h in hits:
        with open(h, "ab") as f:
            f.write(b"tampered")
    return hits


def shim_env(home, release_dir, extra=None):
    env = dict(os.environ)
    for k in list(env):
        if k.startswith("UB_"):
            env.pop(k)
    env.update({"HOME": home, "USERPROFILE": home, "UB_HOME": os.path.join(home, ".ultimate-brainstorm"),
                "UB_RELEASE_DIR": release_dir, "PYTHONDONTWRITEBYTECODE": "1"})
    env["PATH"] = os.path.dirname(sys.executable) + os.pathsep + env.get("PATH", "")
    env.update(extra or {})
    return env


class PosixShim(unittest.TestCase):
    @classmethod
    def tearDownClass(cls):
        Release.cleanup()

    def setUp(self):
        paths.require(paths.INSTALL_SH, owner="B1")
        self.sh = find_sh()
        if not self.sh:
            self.skipTest("no POSIX sh / Git Bash on this machine")

    def run_sh(self, script, args, env, timeout=300):
        return paths.run([self.sh, script] + list(args), env=env, timeout=timeout)

    def test_syntax_template(self):
        proc = paths.run([self.sh, "-n", paths.INSTALL_SH], timeout=60)
        self.assertEqual(proc.returncode, 0, paths.describe(proc))

    def test_template_shape(self):
        text = read_bytes(paths.INSTALL_SH)
        self.assertNotIn(b"\r\n", text, "install.sh uses LF")
        lines = [l for l in text.decode("utf-8").splitlines() if l.strip()]
        self.assertEqual(lines[-1].strip(), 'main "$@" || exit 1')

    def test_rendered_with_release_dir(self):
        dist = Release.build(self)
        script = os.path.join(dist, "install.sh")
        proc = paths.run([self.sh, "-n", script], timeout=60)
        self.assertEqual(proc.returncode, 0, paths.describe(proc))
        with tempfile.TemporaryDirectory() as home:
            proc = self.run_sh(fwd(script), ["version"], shim_env(home, fwd(dist)))
            self.assertEqual(proc.returncode, 0, paths.describe(proc))
            self.assertIn(Release.version, proc.out + proc.err)

    def test_wrong_hash_aborts(self):
        dist = Release.build(self)
        with tempfile.TemporaryDirectory() as tmp:
            bad = os.path.join(tmp, "bad dist")
            self.assertTrue(tampered_copy(dist, bad, "*.tar.gz"))
            home = os.path.join(tmp, "home")
            os.makedirs(home)
            proc = self.run_sh(fwd(os.path.join(bad, "install.sh")), ["version"], shim_env(home, fwd(bad)))
            self.assertNotEqual(proc.returncode, 0, paths.describe(proc))
            self.assertRegex((proc.out + proc.err).lower(), r"sha|hash|checksum")
            self.assertFalse(os.path.exists(os.path.join(home, ".ultimate-brainstorm", "kit")))

    def test_root_refused(self):
        if os.name == "nt":
            self.skipTest("root refusal is tested on POSIX CI only")
        dist = Release.build(self)
        script = os.path.join(dist, "install.sh")
        with tempfile.TemporaryDirectory() as home:
            env = shim_env(home, dist)
            if hasattr(os, "geteuid") and os.geteuid() == 0:
                proc = self.run_sh(script, ["version"], env)
            else:
                sudo = shutil.which("sudo")
                if not sudo or subprocess.run([sudo, "-n", "true"], stdin=subprocess.DEVNULL,
                                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode != 0:
                    self.skipTest("not root and no passwordless sudo")
                proc = paths.run([sudo, "-n", "env", "HOME=" + home, "UB_RELEASE_DIR=" + dist, "PATH=" + env["PATH"],
                                  self.sh, script, "version"], timeout=120)
            self.assertNotEqual(proc.returncode, 0, paths.describe(proc))
            self.assertIn("root", (proc.out + proc.err).lower())


class PowerShellShim(unittest.TestCase):
    @classmethod
    def tearDownClass(cls):
        Release.cleanup()

    def setUp(self):
        paths.require(paths.INSTALL_PS1, owner="B1")
        self.ps = find_powershell()
        if not self.ps:
            self.skipTest("Windows PowerShell 5.1 is not available")

    def parse_check(self, path):
        cmd = ("$t = $null; $e = $null; "
               "[void][System.Management.Automation.Language.Parser]::ParseFile('%s', [ref]$t, [ref]$e); "
               "if ($e -and $e.Count -gt 0) { $e | ForEach-Object { $_.Message }; exit 1 } else { exit 0 }"
               % path.replace("'", "''"))
        return paths.run([self.ps, "-NoProfile", "-NonInteractive", "-Command", cmd], timeout=120)

    def run_ps(self, script, args, env):
        return paths.run([self.ps, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", script]
                         + list(args), env=env, timeout=300)

    def test_template_parses_and_uses_crlf(self):
        proc = self.parse_check(paths.INSTALL_PS1)
        self.assertEqual(proc.returncode, 0, paths.describe(proc))
        raw = read_bytes(paths.INSTALL_PS1)
        self.assertIn(b"\r\n", raw)
        self.assertNotIn(b"\n", raw.replace(b"\r\n", b""), "install.ps1 uses CRLF only")
        lines = [l for l in raw.decode("utf-8").splitlines() if l.strip()]
        self.assertEqual(lines[-1].strip(), "Main $args")

    def test_rendered_parses_and_runs(self):
        dist = Release.build(self)
        script = os.path.join(dist, "install.ps1")
        proc = self.parse_check(script)
        self.assertEqual(proc.returncode, 0, paths.describe(proc))
        with tempfile.TemporaryDirectory() as home:
            proc = self.run_ps(script, ["version"], shim_env(home, dist))
            self.assertEqual(proc.returncode, 0, paths.describe(proc))
            self.assertIn(Release.version, proc.out + proc.err)

    def test_wrong_hash_aborts(self):
        dist = Release.build(self)
        with tempfile.TemporaryDirectory() as tmp:
            bad = os.path.join(tmp, "bad dist")
            self.assertTrue(tampered_copy(dist, bad, "*.zip"))
            home = os.path.join(tmp, "home")
            os.makedirs(home)
            proc = self.run_ps(os.path.join(bad, "install.ps1"), ["version"], shim_env(home, bad))
            self.assertNotEqual(proc.returncode, 0, paths.describe(proc))
            self.assertRegex((proc.out + proc.err).lower(), r"sha|hash|checksum")


if __name__ == "__main__":
    unittest.main()
