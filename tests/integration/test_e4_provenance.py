"""Provenance checks name the release workflow and the tag (audit finding #71). Owner: E4.

`gh attestation verify --repo` alone accepts an attestation from ANY workflow run in the repository (a workflow pushed
on a branch with a stolen token can mint one). install.py, install.sh and install.ps1 therefore also pass
--signer-workflow <owner>/ultimate-brainstorm/.github/workflows/release.yml and --source-ref refs/tags/v<version>, and a
gh too old for those flags is "not checked" (a note, or an error with --require-attestation), never a pass. All three
also pin verify to github.com (--hostname github.com), so GH_HOST cannot send it to another host. The shims' checks run
here against a fake gh; tests never reach the network.
"""

import contextlib
import importlib.util
import io
import os
import re
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "harness"))
import paths  # noqa: E402
import inst  # noqa: E402
import shims  # noqa: E402
from tmphome import TmpHome  # noqa: E402
from test_bootstrap import find_powershell, find_sh  # noqa: E402

REPO = "MrHashMe/ultimate-brainstorm"
IDENTITY = ["--repo", REPO, "--signer-workflow", REPO + "/.github/workflows/release.yml", "--source-ref",
            "refs/tags/v2.1.0"]
PINNED = IDENTITY + ["--hostname", "github.com"]  # every verifier asks github.com, whatever GH_HOST says
TOO_OLD = {"tool": "gh", "argv_regex": "^attestation verify", "action": "fail", "exit": 1,
           "stderr": "unknown flag: --signer-workflow"}
BAD = {"tool": "gh", "argv_regex": "^attestation verify", "action": "fail", "exit": 1,
       "stderr": "Error: verifying with issuer \"sigstore.dev\": no matching attestation"}


def verify_calls(th):
    return [c["argv"] for c in th.fake_calls("gh") if c["argv"][:2] == ["attestation", "verify"]]


class InstallPy(unittest.TestCase):
    def setUp(self):
        inst.require_installer()

    def check(self, th, require=False):
        spec = importlib.util.spec_from_file_location("ub_install_e4_prov", paths.INSTALL_PY)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        env = {k: v for k, v in th.env.items() if k != "UB_RELEASE_DIR"}
        ctx = mod.Ctx(mod.build_parser().parse_args(["update"] + (["--require-attestation"] if require else [])),
                      environ=env)
        archive = th.write(os.path.join(th.root, "ultimate-brainstorm-2.1.0.tar.gz"), "archive bytes\n")
        err = None
        with contextlib.redirect_stderr(io.StringIO()):
            try:
                mod.verify_provenance(ctx, archive, "2.1.0")
            except mod.InstallError as exc:
                err = str(exc)
        return err, ctx.notes

    def test_signer_workflow_and_tag_are_required(self):
        with inst.installer_home(tools=("gh",)) as th:
            err, notes = self.check(th)
            self.assertIsNone(err)
            self.assertEqual(notes, [])
            argv = verify_calls(th)[0]
            self.assertEqual(argv[3:], PINNED)

    def test_an_attestation_from_another_workflow_refuses(self):
        with inst.installer_home(tools=("gh",)) as th:
            th.set_scenario([BAD])
            err, _notes = self.check(th)
            self.assertIn("provenance check failed", err or "")
            self.assertIn(".github/workflows/release.yml for the tag v2.1.0", err or "")

    def test_a_gh_without_the_identity_flags_is_not_a_pass(self):
        with inst.installer_home(tools=("gh",)) as th:
            th.set_scenario([TOO_OLD])
            err, notes = self.check(th)
            self.assertIsNone(err)
            self.assertTrue(notes and "update the GitHub CLI" in notes[0], notes)
            self.assertIn("--signer-workflow %s/.github/workflows/release.yml" % REPO, notes[0], "the manual check")
            err, _notes = self.check(th, require=True)
            self.assertIn("--require-attestation", err or "")


def extract(text, start, end):
    i = text.index(start)
    return text[i:text.index(end, i) + len(end)]


class InstallSh(unittest.TestCase):
    """The shim's ub_provenance function, run by sh against a fake gh."""

    def setUp(self):
        paths.require(paths.INSTALL_SH, owner="B1")
        self.sh = find_sh()
        if not self.sh:
            self.skipTest("no POSIX sh / Git Bash")

    def run_check(self, th):
        with open(paths.INSTALL_SH, encoding="utf-8") as f:
            func = extract(f.read(), "ub_provenance() {\n", "\n}\n")
        script = th.write(os.path.join(th.root, "prov.sh"), func + (
            'UB_OWNER=MrHashMe\nUB_VERSION=2.1.0\n'
            'if why=$(ub_provenance "$1"); then printf "ok[%s]\\n" "$why"; else printf "failed[%s]\\n" "$why"; fi\n'))
        gh_bin = os.path.join(th.root, "shbin")
        shims.install_fakes(gh_bin, ("gh",), windows=False)  # a sh script, also for Git Bash on Windows
        env = dict(th.env)
        env["PATH"] = gh_bin + os.pathsep + env["PATH"]
        if os.name != "nt":  # th.env's PATH has no coreutils (CI keeps Python outside /usr/bin); ub_provenance needs sed, grep
            env["PATH"] += os.pathsep + os.environ.get("PATH", "")  # after gh_bin, so the fake gh still wins
        archive = th.write(os.path.join(th.root, "ultimate-brainstorm-2.1.0.tar.gz"), "archive\n")
        proc = paths.run([self.sh, script.replace("\\", "/"), archive.replace("\\", "/")], env=env, timeout=120)
        self.assertEqual(proc.returncode, 0, paths.describe(proc))
        return proc.out.strip().splitlines()[-1]

    def test_verified_with_the_identity(self):
        with TmpHome(tools=()) as th:
            self.assertEqual(self.run_check(th), "ok[]")
            argv = verify_calls(th)[0]
            self.assertEqual(argv[3:], PINNED)

    def test_failed_and_too_old(self):
        with TmpHome(tools=()) as th:
            th.set_scenario([BAD])
            self.assertTrue(self.run_check(th).startswith("failed["))
            th.set_scenario([TOO_OLD])
            self.assertEqual(self.run_check(th), "ok[this gh has no --signer-workflow / --source-ref / --hostname: "
                                                 "update the GitHub CLI]")


class InstallPs1(unittest.TestCase):
    """The shim's Test-UbProvenance function, run by Windows PowerShell against a fake gh."""

    def setUp(self):
        paths.require(paths.INSTALL_PS1, owner="B1")
        self.ps = find_powershell()
        if not self.ps:
            self.skipTest("no Windows PowerShell")

    def run_check(self, th):
        with open(paths.INSTALL_PS1, encoding="utf-8") as f:
            func = extract(f.read().replace("\r\n", "\n"), "function Test-UbProvenance {\n", "\n}\n")
        script = os.path.join(th.root, "prov.ps1")
        with open(script, "w", encoding="ascii", newline="\r\n") as f:
            f.write("$ErrorActionPreference = 'Stop'\n" + func + "\ntry {\n"
                    "    $why = Test-UbProvenance -Archive $args[0] -Owner 'MrHashMe' -Version '2.1.0'\n"
                    "    Write-Output \"ok[$why]\"\n"
                    "} catch {\n    Write-Output \"failed[$($_.Exception.Message)]\"\n}\n")
        archive = th.write(os.path.join(th.root, "ultimate-brainstorm-2.1.0.zip"), "archive\n")
        env = dict(th.env)
        sysroot = os.environ.get("SYSTEMROOT", r"C:\Windows")
        env["PATH"] = os.pathsep.join([th.bin, os.path.join(sysroot, "System32"),
                                       os.path.join(sysroot, "System32", "WindowsPowerShell", "v1.0"),
                                       env["PATH"]])
        # 300 s like the other PowerShell 5.1 runs under a TmpHome: one takes about 25 s on GitHub's Windows runners,
        # and a slow runner once needed more than 120 s
        proc = paths.run([self.ps, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", script,
                          archive], env=env, timeout=300)
        self.assertEqual(proc.returncode, 0, paths.describe(proc))
        return [ln for ln in proc.out.splitlines() if re.match(r"^(ok|failed)\[", ln)][-1]

    def test_verified_with_the_identity(self):
        with TmpHome(tools=("gh",)) as th:
            self.assertEqual(self.run_check(th), "ok[]")
            argv = verify_calls(th)[0]
            self.assertEqual(argv[3:], PINNED)

    def test_failed_and_too_old(self):
        with TmpHome(tools=("gh",)) as th:
            th.set_scenario([BAD])
            self.assertIn("provenance check failed", self.run_check(th))
            th.set_scenario([TOO_OLD])
            self.assertEqual(self.run_check(th), "ok[this gh has no --signer-workflow / --source-ref / --hostname: "
                                                 "update the GitHub CLI]")


if __name__ == "__main__":
    unittest.main()
