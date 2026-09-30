"""Phase H (HC-ranking-seats), the screen's own-origin correction on small pools (KIT_SPEC 5.7, findings 51 and 88).

A judge's own-origin gap was taken off its own-vendor scores at any positive value. On small pools (3 reference
ideas) most of such gaps are noise, so a judge without self-preference was lowered in most runs and the pick lost
accuracy. The gap now has a standard error from the spread of the per-idea differences, and only a gap above 1.5
standard errors is taken off (bs.GAP_Z, chosen by simulation); a clear self-preference is still corrected. The blind
quick screen shares the code (centered_means) and the rule.
"""

import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest

_KIT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_SCRIPTS = os.path.join(_KIT, "skills", "ultimate-brainstorm", "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

import bs  # noqa: E402

CRIT = {"Value": 30, "Feasibility": 25, "Fit": 20, "Distinctiveness": 15, "Evidence": 10}
QCRIT = {"Value": 40, "Feasibility": 30, "Distinctiveness": 30}


def rec(i, v, crit=CRIT):
    """A screen record that scores every criterion v (the weighted score is v)."""
    return {"id": i, "g1": True, "g2": True, "g3": True, "c": dict((k, v) for k in crit), "risk": "r"}


class Case(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ub-h-screen-")
        self.run = os.path.join(self.tmp, "brainstorm", "2026-09-27-h-screen")
        os.makedirs(self.run)
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def w(self, rel, obj):
        p = os.path.join(self.run, *rel.split("/"))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8", newline="\n") as f:
            f.write(obj if isinstance(obj, str) else json.dumps(obj))

    def r(self, rel):
        with open(os.path.join(self.run, *rel.split("/")), encoding="utf-8") as f:
            text = f.read()
        return json.loads(text) if rel.endswith(".json") else text

    def pool(self, own_claude, base_claude):
        """6 claude ideas, 6 gpt ideas and 3 human ideas; gpt scores every idea 3, claude scores its own ideas
        own_claude, the human ideas base_claude and the gpt ideas 3."""
        ids = ["I-%03d" % n for n in range(1, 16)]
        origins = dict((i, "claude" if n < 6 else "gpt" if n < 12 else "human") for n, i in enumerate(ids))
        claude = dict((i, own_claude[n] if n < 6 else 3 if n < 12 else base_claude[n - 12]) for n, i in enumerate(ids))
        return ids, origins, {"claude": [rec(i, claude[i]) for i in ids], "gpt": [rec(i, 3) for i in ids]}

    def screen(self, own_claude, base_claude):
        ids, origins, outs = self.pool(own_claude, base_claude)
        self.w("run.json", {"schema": 2, "run": "2026-09-27-h-screen", "seats": {"screen_judges": ["claude", "gpt"]}})
        self.w("criteria.json", CRIT)
        self.w("origins.json", origins)
        self.w("clusters.json", dict((i, "c%d" % (n % 6)) for n, i in enumerate(ids)))
        self.w("screen/ideas.md", "".join("%s | t | p | m\n" % i for i in ids))
        for label, rows in outs.items():
            self.w("screen/%s.out.json" % label, {"scores": rows})
        with contextlib.redirect_stdout(io.StringIO()):
            bs.screen(self.run)
        sl = self.r("screen/shortlist.json")
        return sl, dict((g["judge"], g) for g in sl["own_origin_gap"]), self.r("screen/table.md")


class NoiseAwareCorrectionTests(Case):
    def test_a_gap_within_noise_is_not_taken_off(self):
        # claude's differences to gpt on its own ideas are +1, -1, +1, -1, +1, 0 (mean +0.17) and on the human ideas
        # 0, +1, -1: a gap of +0.17 with a standard error of 0.70 is noise, yet it lowered claude's own ideas
        sl, gaps, text = self.screen([4, 2, 4, 2, 4, 3], [3, 4, 2])
        self.assertEqual(sl["lowered"], {})
        self.assertAlmostEqual(gaps["claude"]["gap"], 0.167, places=3)
        self.assertAlmostEqual(gaps["claude"]["se"], 0.703, places=3)
        self.assertFalse(gaps["claude"]["flag"])
        self.assertIn("- claude: +0.17 over 6 own-vendor ideas (against gpt; 3 ideas from neither vendor); not "
                      "corrected: within noise (SE 0.70, needs above 1.5 SE)", text)
        self.assertIn("Every judge's scores count; each judge is centered", text)

    def test_a_clear_gap_is_still_taken_off(self):
        # the same noise around a +1.5 self-preference: 1.5 is above 1.5 x 0.62, so it comes off in full
        sl, gaps, text = self.screen([5, 4, 5, 4, 5, 4], [3, 4, 2])
        self.assertAlmostEqual(gaps["claude"]["gap"], 1.5)
        self.assertLess(bs.GAP_Z * gaps["claude"]["se"], 1.5)
        self.assertEqual(sl["lowered"], {"claude": 1.5})
        self.assertIn("its own-vendor scores are lowered by 1.50  <- FLAG: gap above 0.5", text)

    def test_a_flagged_gap_within_noise_is_shown_not_corrected(self):
        # +1.0 on claude's own ideas, but the human-idea baseline (0, +2, -2) is too noisy to tell it from leniency
        # (SE 1.21): FLAG for the human, no correction
        sl, gaps, text = self.screen([5, 3, 4, 3, 5, 4], [3, 5, 1])
        self.assertEqual(sl["lowered"], {})
        self.assertAlmostEqual(gaps["claude"]["gap"], 1.0)
        self.assertAlmostEqual(gaps["claude"]["se"], 1.211, places=3)
        self.assertTrue(gaps["claude"]["flag"])
        self.assertGreater(bs.GAP_Z * gaps["claude"]["se"], gaps["claude"]["gap"])
        self.assertIn("not corrected: within noise", text)
        self.assertIn("<- FLAG: gap above 0.5", text)


class QuickPickNoiseTests(Case):
    def test_the_blind_quick_screen_uses_the_same_rule(self):
        # quick-pick's blind scores come from centered_means: a noise gap is not taken off there either
        ideas, rows = [], {"claude": [], "gpt": []}
        own = [4, 2, 4, 2, 4, 3]
        for n in range(6):
            for fam, prefix, v in (("claude", "QA", own[n]), ("gpt", "QB", 3)):
                iid = "Q-%02d" % (len(ideas) + 1)
                ideas.append({"id": iid, "title": "t", "pitch": "p", "mechanism": "m", "cluster": "c%d" % n,
                              "aliases": ["%s-%02d" % (prefix, n + 1)], "gates": {"g1": True, "g2": True, "g3": True},
                              "scores": [{"criterion": k, "score": 3} for k in QCRIT]})
                rows["claude"].append(rec(iid, v if fam == "claude" else 3, QCRIT))
                rows["gpt"].append(rec(iid, 3, QCRIT))
        for n, v in enumerate([3, 4, 2]):
            iid = "Q-%02d" % (len(ideas) + 1)
            ideas.append({"id": iid, "title": "t", "pitch": "p", "mechanism": "m", "cluster": "h%d" % n,
                          "aliases": ["H-%02d" % (n + 1)], "gates": {"g1": True, "g2": True, "g3": True},
                          "scores": [{"criterion": k, "score": 3} for k in QCRIT]})
            rows["claude"].append(rec(iid, v, QCRIT))
            rows["gpt"].append(rec(iid, 3, QCRIT))
        self.w("run.json", {"schema": 2, "run": "2026-09-27-h-screen", "mode": "quick",
                            "seats": {"screen_judges": ["claude", "gpt"], "tournament_judges": ["gpt"]}})
        self.w("criteria.json", QCRIT)
        self.w("pool/_families.json", {"QA": "claude", "QB": "gpt", "H": "human"})
        self.w("quick/curated.json", {"ideas": ideas})
        for label, rs in rows.items():
            self.w("screen/%s.out.json" % label, {"scores": rs})
        with contextlib.redirect_stdout(io.StringIO()):
            bs.quick_pick(self.run, "blind")
        fin = self.r("quick/finalists.json")
        self.assertEqual(fin["lowered"], {})
        self.assertAlmostEqual(dict((g["judge"], g["gap"]) for g in fin["own_origin_gap"])["claude"], 0.167, places=3)
        self.assertIn("not corrected: within noise", self.r("quick/screen.md"))


if __name__ == "__main__":
    unittest.main()
