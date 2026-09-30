"""Release gates and provenance identity (audit findings #71, #91). Owner: E4.

#91 validate_kit: KIT_SPEC section 15 and docs/ACCEPTANCE.md list the same unverified items, and every [U-n] tag in the
    kit is one of them. release.py refuses to build (exit 3) while the acceptance record lacks a live result, unless
    --no-acceptance is given, which --notes then records in the release notes; release.yml passes it only behind the
    version's "Acceptance override:" CHANGELOG line.
#71 validate_kit: the publishing job fails when a release for the tag exists and never uploads to, edits or deletes a
    release. Every provenance check (install.py, install.sh, install.ps1) names the release workflow as the signer and
    the version tag as the source ref.
"""

import contextlib
import importlib.util
import io
import os
import re
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "harness"))
import paths  # noqa: E402
import kitcheck  # noqa: E402

vk = kitcheck.load_validate_kit()
REL = os.path.join(".github", "workflows", "release.yml")
TAG = "[U" + "-"  # built at run time, so this file itself holds no tag for check_unverified to find


def load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def read(rel):
    with open(os.path.join(paths.KIT, rel), encoding="utf-8") as f:
        return f.read()


def write(root, rel, text):
    path = os.path.join(root, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    return path


SPEC = """# spec

## 15. Unverified items

| Item | Where | Fallback | Verified by |
|---|---|---|---|
| U-1 | a | b | live |
| U-2 | a | b | live |

## 16. Milestones

| U-9 | not in section 15 | | |
"""

ACCEPTANCE = """# Live acceptance checklist

| Host | Versions | 1 Doctor | 2 Quick | 3 Standard | 4 Continue | 5 Requests / plan | Notes |
|---|---|---|---|---|---|---|---|
| Claude Code | 2.1 | PONG | %s | | | | |
| Codex | 0.156 | %s | | | | | |
| Kimi Code | | | | | | | |

| Check | How | Pass when | Result | Host and version | Date |
|---|---|---|---|---|---|
| Windows PowerShell 5.1 kickoff | x | y | confirmed | Codex 0.156, Windows 11 | 2026-09-30 |

| Item | Where | Live check to run | Result | Host and version | Date |
|---|---|---|---|---|---|
| U-1 `kimi -p` reading stdin (unused) | x | none needed | not yet verified live | | |
| U-2 Kimi stream-json field names | x | y | %s | %s | %s |
"""


def acceptance(doctor2="PONG", result="confirmed", host="Kimi Code 2.0.2", date="2026-09-30"):
    return ACCEPTANCE % ("DONE", doctor2, result, host, date)


class UnverifiedItems(unittest.TestCase):
    def test_repository_is_consistent(self):
        self.assertEqual(vk.check_unverified(paths.KIT), [])

    def test_drift_is_caught(self):
        with tempfile.TemporaryDirectory() as kit:
            write(kit, "docs/design/KIT_SPEC.md", SPEC)
            write(kit, "docs/ACCEPTANCE.md", acceptance())
            write(kit, "skills/x/scripts/a.py", "# %s1] assumed\n# %s2] assumed\n" % (TAG, TAG))
            self.assertEqual(vk.check_unverified(kit), [])
            # a spec row without its live check, and a code tag the spec does not list
            write(kit, "docs/design/KIT_SPEC.md", SPEC.replace("| U-2 | a | b | live |\n", ""))
            write(kit, "install/b.py", "x = 1  # %s7] new assumption\n" % TAG)
            problems = " | ".join(vk.check_unverified(kit))
            self.assertIn("U-2 has a row in docs/ACCEPTANCE.md but is not in KIT_SPEC section 15", problems)
            self.assertIn(TAG + "2] is used in skills/x/scripts/a.py", problems)
            self.assertIn(TAG + "7] is used in install/b.py", problems)
            self.assertNotIn("U-9", problems, "only section 15 counts")

    def test_a_row_missing_from_acceptance_is_caught(self):
        with tempfile.TemporaryDirectory() as kit:
            write(kit, "docs/design/KIT_SPEC.md", SPEC)
            write(kit, "docs/ACCEPTANCE.md", re.sub(r"(?m)^\| U-2 .*\n", "", acceptance()))
            self.assertEqual(vk.check_unverified(kit),
                             ["U-2 is in KIT_SPEC section 15 but has no row in docs/ACCEPTANCE.md"])


class AcceptanceGate(unittest.TestCase):
    def setUp(self):
        self.release = load_module(paths.RELEASE_PY, "ub_release_e4")

    def gaps(self, text):
        with tempfile.TemporaryDirectory() as kit:
            write(kit, "docs/ACCEPTANCE.md", text)
            return self.release.acceptance_gaps(kit)

    def test_complete_record(self):
        self.assertEqual(self.gaps(acceptance()), [], "(unused) items are exempt")

    def test_unverified_rows(self):
        for result in ("not yet verified live", "not tested", ""):
            self.assertEqual(self.gaps(acceptance(result=result)), ["U-2: no live result"], result)
        self.assertEqual(self.gaps(acceptance(host="")), ["U-2: the result has no host and date"])
        self.assertEqual(self.gaps(acceptance(date="")), ["U-2: the result has no host and date"])
        self.assertEqual(self.gaps(acceptance(doctor2="")),
                         ["the per-host checks ran on 1 host(s), not 2 (Doctor column)"])

    def test_the_repository_record_is_not_complete_yet(self):
        gaps = self.release.acceptance_gaps(paths.KIT)
        self.assertTrue(any(g.startswith("U-") for g in gaps), gaps)

    def test_build_is_refused_without_the_override(self):
        with tempfile.TemporaryDirectory() as kit:
            write(kit, "VERSION", "9.9.9\n")
            write(kit, "docs/ACCEPTANCE.md", acceptance(result="not tested"))
            out = os.path.join(kit, "dist")
            with self.assertRaises(self.release.ReleaseError) as cm:
                self.release.release("9.9.9", "someone", out, kit=kit)
            self.assertEqual(cm.exception.code, 3)
            self.assertIn("U-2: no live result", str(cm.exception))
            self.assertFalse(os.path.exists(out), "nothing is built")
            with open(os.path.join(paths.KIT, "VERSION"), encoding="utf-8") as f:
                version = f.read().strip()
            err = io.StringIO()
            with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
                rc = self.release.main(["--version", version, "--out", out])  # the repository's own record
            self.assertEqual(rc, 3, err.getvalue())
            self.assertIn("--no-acceptance", err.getvalue())
            self.assertFalse(os.path.exists(out))

    def test_override_is_recorded_in_the_notes(self):
        with tempfile.TemporaryDirectory() as d:
            notes = write(d, "release-notes.md", "Fixes.\n\nAcceptance override: no hosts yet.\n")
            with open(os.path.join(paths.KIT, "VERSION"), encoding="utf-8") as f:
                version = f.read().strip()
            with contextlib.redirect_stderr(io.StringIO()):
                result = self.release.release(version, "someone", os.path.join(d, "dist"), no_acceptance=True,
                                              notes=notes)
            self.assertFalse(result["acceptance"]["complete"])
            with open(notes, encoding="utf-8") as f:
                text = f.read()
            self.assertTrue(text.startswith("Fixes.\n"), "the CHANGELOG section stays first")
            self.assertIn("built with `--no-acceptance`", text)
            for gap in result["acceptance"]["gaps"]:
                self.assertIn("- " + gap, text)


class ReleaseWorkflow(unittest.TestCase):
    def check(self, old, new):
        with tempfile.TemporaryDirectory() as kit:
            for name in ("ci.yml", "release.yml", "drift.yml"):
                src = os.path.join(paths.KIT, ".github", "workflows", name)
                dst = os.path.join(kit, ".github", "workflows", name)
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.copyfile(src, dst)
            text = read(REL)
            self.assertIn(old, text)
            write(kit, REL, text.replace(old, new, 1))
            return " | ".join(vk.check_workflows(kit))

    def test_repository_workflow_passes(self):
        self.assertEqual(vk.check_workflows(paths.KIT), [])

    def test_removing_the_existing_release_refusal_is_caught(self):
        problems = self.check("            exit 1\n          fi\n          if [ -s assets", "          fi\n          if [ -s assets")
        self.assertIn("must fail (exit 1) when a release for the tag already exists", problems)

    def test_replacing_assets_is_caught(self):
        problems = self.check("          if [ -s assets/release-notes.md ]; then\n",
                              "          gh release upload \"$GITHUB_REF_NAME\" assets/dist/*\n"
                              "          if [ -s assets/release-notes.md ]; then\n")
        self.assertIn("gh release upload changes a published release", problems)

    def test_the_acceptance_gate_stays_in_the_build(self):
        problems = self.check("--notes release-notes.md\n", "--no-acceptance\n")
        self.assertIn("without --notes release-notes.md", problems)
        problems = self.check("if grep -q '^Acceptance override:' release-notes.md; then",
                              "if true; then")
        self.assertIn("without the CHANGELOG line 'Acceptance override:'", problems)


def signin_checks(text):
    """The `gh auth status` calls of a shim (comments left out), each up to its redirection."""
    code = "\n".join(ln for ln in text.splitlines() if not ln.lstrip().startswith("#"))
    return [c.strip() for c in re.findall(r"gh auth status[^>*\n]*", code)]


class ProvenanceIdentity(unittest.TestCase):
    """Every verifier passes the signer workflow and the tag, not just the repository, and pins github.com (its
    sign-in pre-check asks about the account verify uses there)."""

    def test_install_py(self):
        mod = load_module(paths.INSTALL_PY, "ub_install_e4_prov")
        self.assertEqual(mod.provenance_args("o/ultimate-brainstorm", "2.1.0"),
                         ["--repo", "o/ultimate-brainstorm", "--signer-workflow",
                          "o/ultimate-brainstorm/.github/workflows/release.yml", "--source-ref", "refs/tags/v2.1.0"])

    def test_install_sh(self):
        text = read(os.path.join("install", "install.sh"))
        m = re.search(r'gh attestation verify "\$1" --repo "\$ub_repo" \\\n\s+--signer-workflow '
                      r'"\$ub_repo/\.github/workflows/release\.yml" --source-ref "refs/tags/v\$UB_VERSION" \\\n'
                      r'\s+--hostname github\.com 2>&1\)', text)
        self.assertTrue(m, "install.sh verifies the signer workflow and the tag on github.com")
        self.assertEqual(len(re.findall(r"gh attestation verify \"", text)), 1)
        self.assertEqual(signin_checks(text), ["gh auth status --active --hostname github.com"])
        self.assertIn("did not confirm", text)
        self.assertIn("'install.py update --source DIR'", text, "the refusal names the way out")

    def test_install_ps1(self):
        text = read(os.path.join("install", "install.ps1")).replace("\r\n", "\n")
        m = re.search(r'& gh attestation verify \$Archive --repo \$repo --signer-workflow '
                      r'"\$repo/\.github/workflows/release\.yml" `\n\s+--source-ref "refs/tags/v\$Version" '
                      r'--hostname github\.com 2>&1', text)
        self.assertTrue(m, "install.ps1 verifies the signer workflow and the tag on github.com")
        self.assertEqual(len(re.findall(r"& gh attestation verify ", text)), 1)
        self.assertEqual(signin_checks(text), ["gh auth status --active --hostname github.com"])


if __name__ == "__main__":
    unittest.main()
