"""bs.py legacy behavior (KIT_SPEC 4.10, 5.7, 12.2): runs without run.json reproduce v1 byte for byte.

The goldens in tests/golden/bs/** were produced once by the v1 bs.py copy (tests/fixtures/bs/v1/bs_v1.py) with
tests/fixtures/bs/make_goldens.py. Covered: both v1 harnesses (the v1 test_bs.py and judge-uxtest), gate kills
and floor, human slot, primary ideas, both-order tallies, a position-biased judge, a self-preferring judge, the
PROVISIONAL skip, per-pair mode, fenced / UTF-16 / preamble / garbage / missing outputs, map, dupcheck fallback and
every status check.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

_KIT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_SCRIPTS = os.path.join(_KIT, "skills", "ultimate-brainstorm", "scripts")
_FIX = os.path.join(_KIT, "tests", "fixtures", "bs")
_GOLDEN = os.path.join(_KIT, "tests", "golden", "bs")
BS = os.path.join(_SCRIPTS, "bs.py")
for _p in (_SCRIPTS, _FIX):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import legacy_scenarios as ls  # noqa: E402


def _golden(name):
    base = os.path.join(_GOLDEN, name)
    files = {}
    root = os.path.join(base, "files")
    for dirpath, _d, names in os.walk(root):
        for n in names:
            p = os.path.join(dirpath, n)
            with open(p, "rb") as f:
                files[os.path.relpath(p, root).replace("\\", "/")] = f.read()
    with open(os.path.join(base, "stdout.txt"), "rb") as f:
        transcript = f.read().decode("utf-8")
    return files, transcript


def _run(bs_path, name):
    tmp = tempfile.mkdtemp(prefix="ub-bs-legacy-")
    try:
        return ls.run_scenario(bs_path, tmp, name)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


class GoldenTests(unittest.TestCase):
    maxDiff = 4000

    def check(self, name):
        want_files, want_out = _golden(name)
        got_files, got_out = _run(BS, name)
        extras = {rel for rel in got_files if rel not in want_files}
        allowed = {rel for rel in extras if any(rel.endswith("/" + x) for x in ls.V2_EXTRA_FILES)}
        self.assertEqual(extras - allowed, set(), "unexpected new files in a v1 run")
        missing = sorted(set(want_files) - set(got_files))
        self.assertEqual(missing, [], "v1 outputs not produced")
        # Line endings are compared normalized: v1 bs.py writes some prompt files in text mode (CRLF on Windows, LF
        # elsewhere), while git stores every golden with LF (.gitattributes). All other bytes must match exactly.
        for rel, data in sorted(want_files.items()):
            self.assertEqual(got_files[rel].replace(b"\r\n", b"\n"), data.replace(b"\r\n", b"\n"),
                             "byte mismatch in %s" % rel)
        self.assertEqual(got_out.replace("\r\n", "\n"), want_out.replace("\r\n", "\n"))
        return got_files

    def test_sp_basic(self):
        got = self.check("sp_basic")
        res = json.loads(got["2026-09-23-sp-basic/tournament/result.json"].decode("utf-8"))
        self.assertEqual(res["families"], ["claude", "gpt"])

    def test_ux_judges(self):
        self.check("ux_judges")

    def test_map_and_dupcheck(self):
        got = self.check("map_and_dupcheck")
        cov = json.loads(got["2026-09-23-night-shift-map/coverage.json"].decode("utf-8"))
        self.assertEqual(cov["ideas"], 6)
        self.assertTrue(cov["homogenized"])

    def test_status_walk(self):
        self.check("status_walk")

    def test_screen_rules(self):
        self.check("screen_rules")

    def test_tourn_selfpref(self):
        got = self.check("tourn_selfpref")
        res = json.loads(got["2026-09-23-self-pref/tournament/result.json"].decode("utf-8"))
        # after the PROVISIONAL rewrite of 00_RUN.md the non-host label is a same-vendor substitute
        self.assertEqual(res["provisional"], ["gpt"])

    def test_tourn_perpair(self):
        self.check("tourn_perpair")


class GoldenSourceTests(unittest.TestCase):
    """The committed goldens still match the v1 copy (guards against a drifted fixture or golden)."""

    def test_v1_copy_reproduces_goldens(self):
        for name, _run_name, _fn in ls.SCENARIOS:
            want_files, want_out = _golden(name)
            got_files, got_out = _run(ls.V1_BS, name)
            self.assertEqual(set(got_files), set(want_files), name)
            # Same line-ending normalization as GoldenTests.check: git stores the goldens with LF.
            for rel in want_files:
                self.assertEqual(got_files[rel].replace(b"\r\n", b"\n"), want_files[rel].replace(b"\r\n", b"\n"),
                                 "%s: %s" % (name, rel))
            self.assertEqual(got_out.replace("\r\n", "\n"), want_out.replace("\r\n", "\n"), name)


class CliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ub-bs-cli-")
        self.run_dir = os.path.join(self.tmp, "brainstorm", "2026-09-23-cli")
        os.makedirs(self.run_dir)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def bs(self, *args):
        env = dict(os.environ, PYTHONIOENCODING="utf-8")
        return subprocess.run([sys.executable, BS] + list(args), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              env=env, cwd=self.tmp)

    def test_version(self):
        p = self.bs("--version")
        self.assertEqual(p.returncode, 0)
        self.assertEqual(p.stdout.decode().strip(), "2.0.0")
        with open(os.path.join(_KIT, "VERSION")) as f:
            self.assertEqual(f.read().strip(), "2.0.0")

    def test_usage_exit_2(self):
        self.assertEqual(self.bs().returncode, 2)
        self.assertEqual(self.bs("nonsense", self.run_dir).returncode, 2)
        self.assertEqual(self.bs("split", self.run_dir).returncode, 2)  # missing required options

    def test_missing_input_exit_4(self):
        p = self.bs("map", self.run_dir)
        self.assertEqual(p.returncode, 4)
        self.assertIn(b"merges.json missing", p.stderr)
        self.assertEqual(self.bs("screen", self.run_dir).returncode, 4)  # criteria.json missing
        self.assertEqual(self.bs("prepare-screen", self.run_dir).returncode, 4)
        self.assertEqual(self.bs("status", os.path.join(self.tmp, "nope")).returncode, 4)

    def test_invalid_input_exit_5(self):
        with open(os.path.join(self.run_dir, "merges.json"), "w") as f:
            json.dump({"ideas": [{"key": "a", "title": "t"}]}, f)
        p = self.bs("map", self.run_dir)
        self.assertEqual(p.returncode, 5)
        self.assertIn(b"lacks 'pitch'", p.stderr)
        with open(os.path.join(self.run_dir, "merges.json"), "w") as f:
            f.write("not json at all")
        self.assertEqual(self.bs("map", self.run_dir).returncode, 5)
        os.makedirs(os.path.join(self.run_dir, "tournament"))
        with open(os.path.join(self.run_dir, "tournament", "cards.md"), "w") as f:
            f.write("## I-001\nTitle: x\n")
        with open(os.path.join(self.run_dir, "tournament", "header.md"), "w") as f:
            f.write("H\n")
        self.assertEqual(self.bs("prepare-tournament", self.run_dir).returncode, 5)  # only 1 card

    def test_bomless_utf16_json_reads(self):
        import bs
        p = os.path.join(self.run_dir, "x.json")
        with open(p, "wb") as f:
            f.write(json.dumps({"a": 1}).encode("utf-16-le"))
        self.assertEqual(bs.load(p), {"a": 1})


if __name__ == "__main__":
    unittest.main()
