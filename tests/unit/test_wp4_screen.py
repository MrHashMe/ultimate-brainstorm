"""bs.py screen (KIT_SPEC 5.7): every judge counts, a judge's own-origin gap (a difference in differences) is taken
off its scores of its own vendor's ideas, per-judge centering on the reference ideas, one record per judge and id,
unknown ids and out-of-range scores ignored, and a fallback answer counted as the family that ran it."""

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


def quiet(fn, *args, **kw):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        fn(*args, **kw)
    return buf.getvalue()


def rec(i, value=3, rest=3, g1=True, **over):
    c = dict((k, rest) for k in CRIT)
    c["Value"] = value
    c.update(over)
    return {"id": i, "g1": g1, "g2": True, "g3": True, "c": c, "risk": "r"}


class ScreenCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ub-wp4-screen-")
        self.run = os.path.join(self.tmp, "brainstorm", "2026-09-26-screen")
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

    def setup_run(self, judges, origins, clusters):
        self.w("run.json", {"schema": 2, "run": "2026-09-26-screen", "seats": {"screen_judges": judges}})
        self.w("criteria.json", CRIT)
        self.w("origins.json", origins)
        self.w("clusters.json", clusters)
        self.w("screen/ideas.md", "".join("%s | t | p | m\n" % i for i in sorted(origins)))

    def screen(self, outs, meta=None):
        for label, rows in outs.items():
            self.w("screen/%s.out.json" % label, {"scores": rows})
            if meta and label in meta:
                self.w("screen/%s.out.json.meta.json" % label, {"family": meta[label], "status": "ok"})
        text = quiet(bs.screen, self.run)
        return self.r("screen/shortlist.json"), text


class SelfPreferenceTests(ScreenCase):
    def test_own_vendor_judge_no_longer_picks_the_cluster(self):
        # findings 51/88: each cluster holds a claude idea (3 everywhere) and a better gpt idea (Value 4); the
        # claude judge adds +1 to its own vendor's ideas. With raw means over both judges the claude idea won every
        # cluster (3.5 vs 3.3); the claude judge's measured gap (+1 on its own ideas beyond the human ones) is taken
        # off its own-vendor scores, so the better idea wins and both judges still count
        origins, clusters = {}, {}
        for n in range(6):
            a, b = "I-%03d" % (2 * n + 1), "I-%03d" % (2 * n + 2)
            origins[a], origins[b] = "claude", "gpt"
            clusters[a] = clusters[b] = "c%d" % n
        for n in range(13, 16):  # reference ideas: no judge's vendor wrote them
            origins["I-%03d" % n], clusters["I-%03d" % n] = "human", "h"
        self.setup_run(["claude", "gpt"], origins, clusters)

        def truth(i):
            return rec(i, value=4 if origins[i] == "gpt" else 3)

        def claude(i):
            if origins[i] == "claude":
                return rec(i, value=4, rest=4)
            return truth(i)
        sl, text = self.screen({"claude": [claude(i) for i in sorted(origins)],
                                "gpt": [truth(i) for i in sorted(origins)]})
        picks = [s["id"] for s in sl["shortlist"] if "best of cluster" in s["reason"]]
        self.assertEqual(sorted(p for p in picks if origins[p] != "human"),
                         sorted(i for i in origins if origins[i] == "gpt"))
        self.assertEqual(sl["scores"]["I-001"], 3.0)   # claude's 4 lowered by its gap of 1, and gpt's 3
        self.assertEqual(sl["scores"]["I-002"], 3.3)   # both judges
        self.assertEqual(sl["centering"]["basis"], "reference")
        self.assertEqual(sl["centering"]["reference"], ["I-013", "I-014", "I-015"])
        self.assertEqual(sl["lowered"], {"claude": 1.0})
        self.assertIn("Every judge's scores count; claude's scores of its own vendor's ideas are lowered by its "
                      "own-origin gap (1.00)", text)
        gaps = dict((g["judge"], g) for g in sl["own_origin_gap"])
        self.assertTrue(gaps["claude"]["flag"])       # the measured gap is reported
        self.assertEqual((gaps["claude"]["gap"], gaps["gpt"]["gap"]), (1.0, 0.0))

    def test_lenient_judge_does_not_move_the_cut(self):
        # a claude judge 1 point more lenient on everything: centering on the reference ideas cancels it
        origins = {"I-001": "claude", "I-002": "gpt", "I-003": "human", "I-004": "human", "I-005": "human"}
        self.setup_run(["claude", "gpt"], origins, dict((i, "c") for i in origins))
        sl, _text = self.screen({"claude": [rec(i, value=4, rest=4) for i in sorted(origins)],
                                 "gpt": [rec(i) for i in sorted(origins)]})
        self.assertEqual(sl["scores"]["I-001"], sl["scores"]["I-002"])
        self.assertEqual(sl["centering"]["offsets"], {"claude": 0.5, "gpt": -0.5})

    def test_idea_no_other_vendor_judged_is_self_judged(self):
        origins = {"I-001": "claude", "I-002": "claude", "I-003": "human"}
        self.setup_run(["claude", "claude-alt"], origins, dict((i, "c") for i in origins))
        sl, text = self.screen({"claude": [rec(i) for i in sorted(origins)],
                                "claude-alt": [rec(i) for i in sorted(origins)]})
        self.assertEqual(sl["self_judged"], ["I-001", "I-002"])
        self.assertIn("Self-judged (only judges of the idea's own vendor scored it", text)


class RecordTests(ScreenCase):
    def base(self):
        origins = dict(("I-%03d" % n, "human") for n in range(1, 5))
        self.setup_run(["claude", "gpt"], origins, dict((i, "c%d" % n) for n, i in enumerate(sorted(origins))))
        return sorted(origins)

    def test_duplicate_unknown_and_out_of_range(self):
        # finding 49: a repeated id counted twice, an invented id was shortlisted, a 0-10 score passed
        ids = self.base()
        claude = [rec(i) for i in ids] + [rec("I-003", value=5, rest=5), rec("I-999", value=5, rest=5)]
        claude[0] = rec("I-001", value=10)
        sl, text = self.screen({"claude": claude, "gpt": [rec(i) for i in ids]})
        self.assertNotIn("I-999", sl["scores"])
        self.assertEqual(sl["scores"]["I-003"], 3.0)   # the first record counts
        self.assertEqual(sl["scores"]["I-001"], 3.0)   # Value 10 ignored: gpt's 3 stands
        self.assertIn("WARNING: claude: I-003 scored twice; the first record counts", text)
        self.assertIn("WARNING: claude: unknown id I-999 ignored", text)
        self.assertIn("WARNING: claude, I-001, Value: score 10 outside 1-5 ignored", text)

    def test_one_model_answering_two_seats_is_one_judge(self):
        # finding 50: every non-host seat fell back to claude; K1 must not fire on one model's gate failure
        ids = ["I-001", "I-002", "I-003", "I-004"]
        self.setup_run(["claude", "gpt", "kimi"], dict((i, "human") for i in ids), dict((i, i) for i in ids))
        rows = [rec(i, g1=(i != "I-002")) for i in ids]
        sl, text = self.screen({"claude": rows, "gpt": rows, "kimi": rows},
                               meta={"claude": "claude", "gpt": "claude", "kimi": "claude"})
        self.assertEqual(sl["killed_gate"], [])
        self.assertEqual(sl["flagged_gate"], ["I-002"])
        self.assertEqual([j["label"] for j in sl["judges"]], ["claude"])
        self.assertIn("the gpt seat was answered by claude (fallback)", text)


if __name__ == "__main__":
    unittest.main()
