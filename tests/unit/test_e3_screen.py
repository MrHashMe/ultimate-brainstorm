"""Phase E3, bs.py screen (KIT_SPEC 5.7): the own-origin gap as a difference in differences (a lenient judge is not
flagged), every judge's scores count and a positive gap is taken off the judge's own-vendor scores (findings 51 and
88), a pair that cannot be told apart is reported, not guessed; the K3 floor on centered means also trips on a
criterion every judge scored at the lowest anchor (review R-ranking-1); origins by vendor (finding 51); bs.py map
with an axis without values (review R-ranking-2)."""

import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

_KIT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_SCRIPTS = os.path.join(_KIT, "skills", "ultimate-brainstorm", "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

import bs  # noqa: E402

CRIT = {"Value": 30, "Feasibility": 25, "Fit": 20, "Distinctiveness": 15, "Evidence": 10}


def quiet(fn, *args, **kw):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        fn(*args, **kw)
    return buf.getvalue()


def rec(i, value=3, rest=3, **over):
    c = dict((k, rest) for k in CRIT)
    c["Value"] = value
    c.update(over)
    return {"id": i, "g1": True, "g2": True, "g3": True, "c": c, "risk": "r"}


class ScreenCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ub-e3-screen-")
        self.run = os.path.join(self.tmp, "brainstorm", "2026-09-26-e3-screen")
        os.makedirs(self.run)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def w(self, rel, obj):
        p = os.path.join(self.run, *rel.split("/"))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8", newline="\n") as f:
            f.write(obj if isinstance(obj, str) else json.dumps(obj))

    def r(self, rel):
        with open(os.path.join(self.run, *rel.split("/")), encoding="utf-8") as f:
            text = f.read()
        return json.loads(text) if rel.endswith(".json") else text

    def screen(self, judges, origins, clusters, outs):
        self.w("run.json", {"schema": 2, "run": "2026-09-26-e3-screen", "seats": {"screen_judges": judges}})
        self.w("criteria.json", CRIT)
        self.w("origins.json", origins)
        self.w("clusters.json", clusters)
        self.w("screen/ideas.md", "".join("%s | t | p | m\n" % i for i in sorted(origins)))
        for label, rows in outs.items():
            self.w("screen/%s.out.json" % label, {"scores": rows})
        text = quiet(bs.screen, self.run)
        return self.r("screen/shortlist.json"), text


class OwnOriginGapTests(ScreenCase):
    def pool(self, n_ref):
        """6 clusters, each a claude idea (true 3 everywhere) and a better gpt idea (Value 4), plus n_ref human
        ideas; the claude judge adds +1 to its own vendor's ideas."""
        origins, clusters = {}, {}
        for n in range(6):
            a, b = "I-%03d" % (2 * n + 1), "I-%03d" % (2 * n + 2)
            origins[a], origins[b] = "claude", "gpt"
            clusters[a] = clusters[b] = "c%d" % n
        for n in range(n_ref):
            origins["I-%03d" % (13 + n)], clusters["I-%03d" % (13 + n)] = "human", "h"
        return origins, clusters

    def test_a_lenient_judge_is_not_flagged(self):
        # finding 88 (3): a claude judge +1 on every idea and no self-preference got own-origin gap +1.00 FLAG
        origins, clusters = self.pool(3)
        sl, text = self.screen(["claude", "gpt"], origins, clusters, {
            "claude": [rec(i, value=5 if origins[i] == "gpt" else 4, rest=4) for i in sorted(origins)],
            "gpt": [rec(i, value=4 if origins[i] == "gpt" else 3) for i in sorted(origins)]})
        gaps = dict((g["judge"], g) for g in sl["own_origin_gap"])
        self.assertEqual((gaps["claude"]["gap"], gaps["claude"]["flag"]), (0.0, False))
        self.assertEqual(sl["lowered"], {})
        self.assertNotIn("<- FLAG", text)
        picks = sorted(s["id"] for s in sl["shortlist"]
                       if "best of cluster" in s["reason"] and origins[s["id"]] != "human")
        self.assertEqual(picks, sorted(i for i in origins if origins[i] == "gpt"))

    def test_every_judge_counts_and_the_self_preferring_one_is_corrected(self):
        # finding 88 (2): leaving the own-vendor judge out halved a 2-judge panel's measurements; now both judges
        # count, and claude's measured +1 comes off its own-vendor scores
        origins, clusters = self.pool(3)
        claude = [rec(i, value=4, rest=4) if origins[i] == "claude" else
                  rec(i, value=4 if origins[i] == "gpt" else 3) for i in sorted(origins)]
        gpt = [rec(i, value=4 if origins[i] == "gpt" else 3) for i in sorted(origins)]
        claude[0] = rec("I-001", value=5, rest=4)  # one claude idea claude rates even higher (+2 on Value)
        sl, text = self.screen(["claude", "gpt"], origins, clusters, {"claude": claude, "gpt": gpt})
        self.assertAlmostEqual(sl["lowered"]["claude"], 1.05)
        # I-001: claude's (5, 4, 4, 4, 4) lowered by 1.05, and gpt's 3s: both judges are in the mean
        self.assertAlmostEqual(sl["scores"]["I-001"], round((4.3 - 1.05 + 3.0) / 2, 3))
        picks = sorted(s["id"] for s in sl["shortlist"]
                       if "best of cluster" in s["reason"] and origins[s["id"]] != "human")
        self.assertEqual(picks, sorted(i for i in origins if origins[i] == "gpt"))
        self.assertIn("claude: +1.05 over 6 own-vendor ideas (against gpt; 3 ideas from neither vendor); its "
                      "own-vendor scores are lowered by 1.05  <- FLAG: gap above 0.5", text)

    def test_no_reference_three_judges_the_third_vendor_is_the_baseline(self):
        # the original repro without human ideas: a third judge family's ideas are outside the claude-gpt pair's
        # self-interest, so the gap is still measured and the better gpt ideas win every cluster
        origins, clusters = self.pool(0)
        for n in range(4):
            origins["I-%03d" % (20 + n)], clusters["I-%03d" % (20 + n)] = "kimi", "k%d" % n
        truth = dict((i, rec(i, value=4 if origins[i] == "gpt" else 3)) for i in origins)
        claude = [rec(i, value=4, rest=4) if origins[i] == "claude" else truth[i] for i in sorted(origins)]
        sl, _text = self.screen(["claude", "gpt", "kimi"], origins, clusters, {
            "claude": claude, "gpt": [truth[i] for i in sorted(origins)], "kimi": [truth[i] for i in sorted(origins)]})
        gaps = dict((g["judge"], g) for g in sl["own_origin_gap"])
        self.assertEqual((gaps["claude"]["gap"], gaps["claude"]["vs"]), (1.0, ["gpt", "kimi"]))
        self.assertEqual((gaps["gpt"]["gap"], gaps["kimi"]["gap"]), (0.0, 0.0))
        picks = [s["id"] for s in sl["shortlist"] if "best of cluster" in s["reason"] and origins[s["id"]] != "kimi"]
        self.assertEqual(sorted(picks), sorted(i for i in origins if origins[i] == "gpt"))

    def test_two_judges_without_ideas_from_neither_vendor_are_reported_not_guessed(self):
        # finding 51 (1): with no idea outside both judges' vendors, "claude adds 1 to its own" and "claude is 1
        # point more lenient and gpt adds 1 to its own" give the same scores. The pair's combined gap is reported
        # and no judge is flagged or corrected (the old per-judge gap flagged claude)
        origins, clusters = self.pool(0)
        claude = [rec(i, value=4, rest=4) if origins[i] == "claude" else rec(i, value=4) for i in sorted(origins)]
        gpt = [rec(i, value=4 if origins[i] == "gpt" else 3) for i in sorted(origins)]
        sl, text = self.screen(["claude", "gpt"], origins, clusters, {"claude": claude, "gpt": gpt})
        self.assertEqual(sl["own_origin_gap"], [])
        self.assertEqual(sl["lowered"], {})
        self.assertEqual(sl["own_origin_pairs"], [{"a": "claude", "b": "gpt", "gap": 1.0, "n_a": 6, "n_b": 6,
                                                   "warn": True}])
        self.assertIn("- WARN: claude and gpt together: +1.00 on their own vendors' ideas (6 and 6 ideas; fewer than "
                      "3 ideas from neither vendor, so which judge adds how much cannot be told", text)


class FloorTests(ScreenCase):
    def floor(self, harsh, lenient, only_harsh=None, only_lenient=None):
        """claude (harsh) and gpt (lenient) score 4 human reference ideas Feasibility `harsh` and `lenient`. I-005
        (claude origin) is scored by gpt only, I-006 (gpt origin) by claude only, with the given Feasibility."""
        origins = {"I-001": "human", "I-002": "human", "I-003": "human", "I-004": "human", "I-005": "claude",
                   "I-006": "gpt"}
        refs = ["I-001", "I-002", "I-003", "I-004"]
        claude = [rec(i, Feasibility=harsh) for i in refs] + [rec("I-006", Feasibility=only_harsh)]
        gpt = [rec(i, Feasibility=lenient) for i in refs] + [rec("I-005", Feasibility=only_lenient)]
        sl, _text = self.screen(["claude", "gpt"], origins, dict((i, i) for i in origins),
                                {"claude": claude, "gpt": gpt})
        return sl["floor_fail"]

    def test_a_scale_minimum_is_never_lifted_above_the_floor(self):
        # R-ranking-1: with a 2-point leniency gap, centering put a harsh judge's 1 at 2.0, above the 1.5 floor
        self.assertEqual(self.floor(harsh=3, lenient=5, only_harsh=1, only_lenient=4), ["I-006"])

    def test_centering_keeps_the_veto_fair_between_judges(self):
        # gap 1: the lenient judge's 2 and the harsh judge's 1 are the same verdict; both fail
        self.assertEqual(self.floor(harsh=3, lenient=4, only_harsh=1, only_lenient=2), ["I-005", "I-006"])
        # gap 0: a raw 2 passes
        self.assertEqual(self.floor(harsh=3, lenient=3, only_harsh=2, only_lenient=2), [])


class LineageTests(unittest.TestCase):
    def test_alt_labels_are_their_vendor(self):
        # finding 51 (3): parents claude and claude-alt gave ai-mixed, which belongs to nobody
        self.assertEqual(bs.lineage_origin({"claude", "claude-alt"}), "claude")
        self.assertEqual(bs.lineage_origin({"claude-alt"}), "claude-alt")
        self.assertEqual(bs.lineage_origin({"claude", "gpt-alt"}), "ai-mixed")
        self.assertEqual(bs.lineage_origin({"human", "gpt"}), "human-mixed")
        self.assertEqual(bs.lineage_origin({"human"}), "human")
        self.assertEqual(bs.lineage_origin({"claude", "?"}), "ai-mixed")


class MapTests(ScreenCase):
    def test_an_axis_without_values_does_not_crash_the_map(self):
        # R-ranking-2: an empty grid divided by zero (exit 1, traceback, no 03_POOL.md)
        self.w("pool/_families.json", {"S1": "claude", "S3": "gpt"})
        ideas = [{"key": "k%d" % n, "title": "T%d" % n, "pitch": "p", "mechanism": "m", "aliases": ["S1-%d" % n],
                  "cluster": "c%d" % (n % 3), "cell": ["a"]} for n in range(5)]
        self.w("merges.json", {"strategy_family": {}, "axes": {"Stage": ["a", "b"], "Channel": []}, "ideas": ideas})
        p = subprocess.run([sys.executable, os.path.join(_SCRIPTS, "bs.py"), "map", self.run],
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           env=dict(os.environ, PYTHONIOENCODING="utf-8"))
        self.assertEqual(p.returncode, 0, p.stderr.decode("utf-8", "replace"))
        cov = self.r("coverage.json")
        self.assertEqual(cov["covered_share"], 1.0)
        self.assertEqual(cov["gap_needed"], cov["homogenized"])
        pool = self.r("03_POOL.md")
        self.assertIn("No axis cells (axis Channel has no values): coverage not computed.", pool)
        self.assertIn("- axis Channel has no values: no axis cells, coverage not computed", pool)

    def test_origins_follow_the_vendor_of_every_alias(self):
        self.w("pool/_families.json", {"S1": "claude", "S2": "claude-alt", "S3": "gpt"})
        ideas = [{"key": "a", "title": "A", "pitch": "p", "mechanism": "m", "aliases": ["S1-1", "S2-1"],
                  "cluster": "c"},
                 {"key": "b", "title": "B", "pitch": "p", "mechanism": "m", "aliases": ["S1-2", "S3-1"],
                  "cluster": "d"}]
        self.w("merges.json", {"strategy_family": {}, "axes": {}, "ideas": ideas})
        quiet(bs.map_pool, self.run)
        lineage = self.r("ideas.json")
        by_key = dict((v["key"], v["origin"]) for v in lineage.values())
        self.assertEqual(by_key, {"a": "claude", "b": "ai-mixed"})


if __name__ == "__main__":
    unittest.main()
