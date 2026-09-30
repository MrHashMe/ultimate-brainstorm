"""Release authenticity cannot be skipped by whoever writes release assets (audit finding #71, round-3 notes
NEW-G8-installer-supplychain-1 and -2, the round-4 installer-trust review). Owner: HG, J2C.

-1 The attestation check was skipped for a release tag older than 2.1.0 (the first attested release), and the
   downgrade guard read VERSION from inside the unverified archive: a "latest" v2.0.3 whose archive said 9.9.9 was
   staged with a note. Now the archive's VERSION must be the tag's, and a releases/latest older than 2.1.0 is refused
   (a named --tag of an old release keeps the note).
-2 A refusal quotes the certificate's identity (workflow path, branch), which the minter chooses; install.py read
   "network", "timed out" or "authenticat" anywhere in gh's output as "could not run" and went on. Like the shims, it
   now runs `gh attestation --help` and `gh auth status --active --hostname github.com` first, and after they pass
   every failed verification refuses, except a timeout, gh's exit code 4 (authentication required), `unknown flag`
   and a line starting `error creating Sigstore verifier` in gh's own words (outside the quoted values); the shims
   read the same two phrases.
J2C The shims ask only about the github.com account verify uses (a stale account on another host skipped their check),
   pin verify to github.com, and take gh's own "error creating Sigstore verifier" (Sigstore's trust root is out of
   reach) for "not checked" instead of a refusal; a refusal names the way out (--source DIR).
Tests never reach the network: urllib is patched in-process, gh is a fake.
"""

import contextlib
import hashlib
import importlib.util
import io
import os
import sys
import tarfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "harness"))
import paths  # noqa: E402
import inst  # noqa: E402
import test_e4_provenance as e4  # noqa: E402
from test_h_installer_guards import FORGED_NO_VERIFIER, NO_VERIFIER  # noqa: E402
from test_bootstrap import find_powershell, find_sh  # noqa: E402
from tmphome import TmpHome  # noqa: E402

REPO = "MrHashMe/ultimate-brainstorm"
PWNED = os.path.join("skills", "ultimate-brainstorm", "references", "hg-pwned.md")
SAN = ('Error: verifying with issuer "sigstore.dev": failed to verify certificate identity: no matching '
       'CertificateIdentity found, last error: expected SAN value to match regex "^https://github.com/%s/.github/'
       'workflows/release.yml@refs/tags/v2.1.0$", got "https://github.com/%s/.github/workflows/%s@refs/heads/%s"')
# refusals of an attestation from another workflow or branch, whose quoted identity holds trigger words
QUOTED_REFUSALS = [SAN % (REPO, REPO, "release.yml", "network"),
                   SAN % (REPO, REPO, "timeout.yml", "main"),
                   SAN % (REPO, REPO, "unknown flag.yml", "main"),
                   'Error: expected SourceRepositoryRef to be "refs/tags/v2.1.0", got "refs/heads/authentication-fix"',
                   'Error: got "refs/heads/a\\"network\\"b"']


def load_installer(name):
    spec = importlib.util.spec_from_file_location(name, paths.INSTALL_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def release_assets(th, tag_ver, inner_ver, folder):
    """ultimate-brainstorm-<tag_ver>.tar.gz (a kit whose VERSION says inner_ver) and its SHA256SUMS in folder."""
    src = inst.kit_source_copy(os.path.join(th.root, "kit-%s-%s" % (tag_ver, inner_ver)))
    with open(os.path.join(src, "VERSION"), "w", encoding="utf-8", newline="\n") as f:
        f.write(inner_ver + "\n")
    with open(os.path.join(src, PWNED), "w", encoding="utf-8", newline="\n") as f:
        f.write("not the release's content\n")
    out = th.mkdir(folder)
    name = "ultimate-brainstorm-%s.tar.gz" % tag_ver
    with tarfile.open(os.path.join(out, name), "w:gz") as tf:
        tf.add(src, arcname="ultimate-brainstorm-%s" % inner_ver)
    with open(os.path.join(out, name), "rb") as f:
        digest = hashlib.sha256(f.read()).hexdigest()
    with open(os.path.join(out, "SHA256SUMS"), "w", encoding="utf-8", newline="\n") as f:
        f.write("%s  %s\n" % (digest, name))
    return out


class Response(object):
    def __init__(self, url, path=None):
        self.url = url
        self.f = open(path, "rb") if path else io.BytesIO(b"")

    def geturl(self):
        return self.url

    def read(self, n=-1):
        return self.f.read(n)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.f.close()


def gh_verify_calls(th):
    return [c["argv"] for c in th.fake_calls("gh") if c["argv"][:2] == ["attestation", "verify"]]


class ArchiveVersion(unittest.TestCase):
    def setUp(self):
        inst.require_installer()

    def test_a_latest_release_older_than_the_first_attested_one_is_refused(self):
        with inst.installer_home(tools=("gh", "kimi", "node")) as th:
            self.assertEqual(inst.run(th, "install", "--yes", "--components", "none").returncode, 0)
            rel = release_assets(th, "2.0.3", "9.9.9", "rel")
            mod = load_installer("ub_install_hg_latest")

            def urlopen(url, timeout=None):  # releases/latest names v2.0.3; the assets come from rel
                if url.endswith("/releases/latest"):
                    return Response("https://github.com/%s/releases/tag/v2.0.3" % REPO)
                return Response(url, os.path.join(rel, url.rsplit("/", 1)[1]))
            out, err = io.StringIO(), io.StringIO()
            cwd = os.getcwd()
            with th.patched_environ(), mock.patch.object(mod.urllib.request, "urlopen", urlopen):
                os.chdir(th.project)
                try:
                    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                        rc = mod.main(["update", "--yes", "--source", "github", "--components", "none"])
                finally:
                    os.chdir(cwd)
            self.assertEqual(rc, 1, out.getvalue() + err.getvalue())
            self.assertIn("the latest release is v2.0.3, older than 2.1.0", err.getvalue())
            self.assertFalse(os.path.exists(os.path.join(th.ub_home, "kit", PWNED)), "nothing was staged")

    def test_the_archive_must_hold_the_tags_version(self):
        with inst.installer_home(tools=("kimi", "node")) as th:
            self.assertEqual(inst.run(th, "install", "--yes", "--components", "none").returncode, 0)
            rel = release_assets(th, "2.1.1", "9.9.9", "rel")
            data, proc = inst.run_json(th, "update", "--yes", "--source", "github", "--components", "none",
                                       env_extra={"UB_RELEASE_DIR": rel}, exit=1)
            self.assertIn("holds kit 9.9.9, not 2.1.1 (its tag v2.1.1)", data.get("error", ""))
            self.assertFalse(os.path.exists(os.path.join(th.ub_home, "kit", PWNED)), "nothing was staged")
            rel = release_assets(th, "2.1.1", "2.1.1", "rel-ok")
            data, proc = inst.run_json(th, "update", "--yes", "--source", "github", "--components", "none",
                                       env_extra={"UB_RELEASE_DIR": rel})
            self.assertTrue(os.path.isfile(os.path.join(th.ub_home, "kit", PWNED)), "the matching release installs")


class GhVerdicts(unittest.TestCase):
    """verify_provenance against a fake gh: pre-checks, then every failure refuses unless gh could not check."""

    def setUp(self):
        inst.require_installer()

    def check(self, th):
        mod = load_installer("ub_install_hg_verdicts")
        env = {k: v for k, v in th.env.items() if k != "UB_RELEASE_DIR"}
        ctx = mod.Ctx(mod.build_parser().parse_args(["update"]), environ=env)
        archive = th.write(os.path.join(th.root, "ultimate-brainstorm-2.1.0.tar.gz"), "archive bytes\n")
        err = None
        with contextlib.redirect_stderr(io.StringIO()):
            try:
                mod.verify_provenance(ctx, archive, "2.1.0")
            except mod.InstallError as exc:
                err = str(exc)
        return err, ctx.notes

    def test_a_quoted_identity_never_turns_a_refusal_into_a_note(self):
        for text in QUOTED_REFUSALS + ["Error: failed to fetch attestations: dial tcp: no such host"]:
            with inst.installer_home(tools=("gh",)) as th:
                th.set_scenario([{"tool": "gh", "argv_regex": "^attestation verify", "action": "fail", "exit": 1,
                                  "stderr": text}])
                err, notes = self.check(th)
                self.assertIn("provenance check failed", err or "", (text, notes))

    def test_gh_that_cannot_check_is_a_note(self):
        for rule in ({"tool": "gh", "argv_regex": "^auth status", "action": "fail", "exit": 1,
                      "stderr": "You are not logged into any GitHub hosts. To log in, run: gh auth login"},
                     {"tool": "gh", "argv_regex": "^attestation --help", "action": "fail", "exit": 1,
                      "stderr": 'unknown command "attestation" for "gh"'}):
            with inst.installer_home(tools=("gh",)) as th:
                th.set_scenario([rule])
                err, notes = self.check(th)
                self.assertIsNone(err)
                self.assertTrue(notes and "gh is not signed in, or has no attestation command" in notes[0], notes)
                self.assertEqual(gh_verify_calls(th), [], "no verdict is read from a gh that cannot check")


class Shims(unittest.TestCase):
    """install.sh and install.ps1 read `unknown flag` only outside gh's quoted values too, ask only about the account
    verify uses on github.com, and take gh's own `error creating Sigstore verifier` for "not checked"."""

    REFUSAL = SAN % (REPO, REPO, "unknown flag.yml", "main")
    # `gh auth status` exits 1 when any account on any host has a problem, although github.com's active one can verify
    STALE_HOST = {"tool": "gh", "argv_regex": "^auth status$", "action": "fail", "exit": 1,
                  "stderr": "ghe.example.invalid\n  X Failed to log in to ghe.example.invalid: The token in hosts.yml "
                            "is invalid."}
    SIGNED_OUT = {"tool": "gh", "argv_regex": "^auth status --active --hostname github.com$", "action": "fail",
                  "exit": 1, "stderr": "You are not logged into any GitHub hosts."}

    def sh(self):
        paths.require(paths.INSTALL_SH, owner="B1")
        self.sh = find_sh()
        if not self.sh:
            self.skipTest("no POSIX sh / Git Bash")
        return e4.InstallSh.run_check, ()

    def ps1(self):
        paths.require(paths.INSTALL_PS1, owner="B1")
        self.ps = find_powershell()
        if not self.ps:
            self.skipTest("no Windows PowerShell")
        return e4.InstallPs1.run_check, ("gh",)

    def quoted_words(self, run_check, tools):
        with TmpHome(tools=tools) as th:
            th.set_scenario([dict(e4.BAD, stderr=self.REFUSAL)])
            refusal = run_check(self, th)
            self.assertTrue(refusal.startswith("failed["), refusal)
            th.set_scenario([e4.TOO_OLD])
            self.assertIn("update the GitHub CLI", run_check(self, th))
        return refusal

    def signin(self, run_check, tools):
        with TmpHome(tools=tools) as th:
            th.set_scenario([self.STALE_HOST])
            self.assertEqual(run_check(self, th), "ok[]", "another host's sign-in problem skipped the check")
            calls = [c["argv"] for c in th.fake_calls("gh")]
            self.assertIn(["auth", "status", "--active", "--hostname", "github.com"], calls)
            self.assertEqual(len(gh_verify_calls(th)), 1, calls)
        with TmpHome(tools=tools) as th:
            th.set_scenario([self.SIGNED_OUT])
            self.assertEqual(run_check(self, th), "ok[gh is not signed in, or has no attestation command]")
            self.assertEqual(gh_verify_calls(th), [], "no verdict is read from a gh that cannot check")

    def sigstore(self, run_check, tools):
        with TmpHome(tools=tools) as th:
            th.set_scenario([dict(e4.BAD, stderr=NO_VERIFIER)])
            why = run_check(self, th)
            self.assertTrue(why.startswith("ok[gh could not build its Sigstore verifier: is the Sigstore TUF "
                                           "repository (tuf-repo-cdn.sigstore.dev) reachable from here? gh: "), why)
            for text in FORGED_NO_VERIFIER:  # the phrase inside gh's quoted values is no verdict
                th.set_scenario([dict(e4.BAD, stderr=text)])
                self.assertTrue(run_check(self, th).startswith("failed["), text)

    def test_install_sh(self):
        run_check, tools = self.sh()
        self.quoted_words(run_check, tools)

    def test_install_ps1(self):
        run_check, tools = self.ps1()
        refusal = self.quoted_words(run_check, tools)
        self.assertIn("provenance check failed", refusal)
        self.assertIn("did not confirm", refusal)
        self.assertIn("--hostname github.com) and install that checked archive's extracted folder with "
                      "'install.py update --source DIR'", refusal, "the refusal names the way out")

    def test_install_sh_asks_about_the_account_verify_uses(self):
        self.signin(*self.sh())

    def test_install_ps1_asks_about_the_account_verify_uses(self):
        self.signin(*self.ps1())

    def test_install_sh_without_a_sigstore_verifier_has_not_checked(self):
        self.sigstore(*self.sh())

    def test_install_ps1_without_a_sigstore_verifier_has_not_checked(self):
        self.sigstore(*self.ps1())


if __name__ == "__main__":
    unittest.main()
