"""bs.py with N judge families (KIT_SPEC 5.7): runs with run.json schema 2."""

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


class RunCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ub-bs-nf-")
        self.run = os.path.join(self.tmp, "brainstorm", "2026-09-23-nfam")
        os.makedirs(self.run)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def w(self, rel, obj, enc="utf-8"):
        p = os.path.join(self.run, *rel.split("/"))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        text = obj if isinstance(obj, str) else json.dumps(obj)
        with open(p, "wb") as f:
            f.write(text.encode(enc))

    def r(self, rel):
        with open(os.path.join(self.run, *rel.split("/")), "r", encoding="utf-8") as f:
            text = f.read()
        return json.loads(text) if rel.endswith(".json") else text

    def exists(self, rel):
        return os.path.exists(os.path.join(self.run, *rel.split("/")))

    def run_json(self, screen=None, tournament=None, provisional=None, mode="standard"):
        self.w("run.json", {"schema": 2, "run": "2026-09-23-nfam", "created_at": "2026-09-23T09:00:00Z",
                            "mode": mode,
                            "seats": {"screen_judges": screen or ["claude", "gpt"],
                                      "tournament_judges": tournament or ["claude", "gpt"]},
                            "provisional": provisional or []})

    # -------- tournament helpers
    def cards(self, ids, origins):
        self.w("tournament/cards.md", "".join("## %s\nTitle: %s\nProblem: x\n\n" % (i, i) for i in ids))
        self.w("tournament/header.md", "HEADER\n")
        self.w("origins.json", origins)

    def verdicts(self, decide, per_pair=False):
        """decide(family, order, first, second) -> FIRST | SECOND | TIE."""
        d = os.path.join(self.run, "tournament")
        for name in sorted(os.listdir(d)):
            if not name.endswith(".map.json"):
                continue
            meta = self.r("tournament/" + name)
            out = [{"pair_id": pid, "winner": decide(meta["family"], meta["order"], p["first"], p["second"])}
                   for pid, p in meta["pairs"].items()]
            self.w("tournament/" + name.replace(".map.json", ".out.json"), {"verdicts": out})

    def tourney(self, ids, origins, judges, decide, provisional=None):
        self.run_json(tournament=judges, provisional=provisional)
        self.cards(ids, origins)
        quiet(bs.prepare_tournament, self.run)
        self.verdicts(decide)
        text = quiet(bs.tournament, self.run)
        return self.r("tournament/result.json"), text


def by_strength(strength):
    def decide(fam, order, a, b):
        if strength[a] == strength[b]:
            return "TIE"
        return "FIRST" if strength[a] > strength[b] else "SECOND"
    return decide


class TournamentTests(RunCase):
    def test_max_points_n3_n4(self):
        ids = ["I-001", "I-002", "I-003", "I-004", "I-005"]
        origins = {i: "human" for i in ids}
        strength = {i: n for n, i in enumerate(ids)}
        for judges in (["claude", "gpt", "kimi"], ["claude", "gpt", "kimi", "glm"]):
            shutil.rmtree(os.path.join(self.run, "tournament"), ignore_errors=True)
            res, text = self.tourney(ids, origins, judges, by_strength(strength))
            f, n = len(judges), len(ids)
            self.assertEqual(res["families"], judges)
            self.assertTrue(all(r["max"] == f * (n - 1) for r in res["raw"]))
            self.assertAlmostEqual(sum(r["points"] for r in res["raw"]), f * n * (n - 1) / 2)
            self.assertEqual(res["raw"][0], {"id": "I-005", "points": float(f * (n - 1)), "max": f * (n - 1)})
            self.assertIn("## Standings (max = %d families x %d opponents = %d points)" % (f, n - 1, f * (n - 1)),
                          text)
            self.assertEqual(res["contested"], [])

    def test_prepare_counts(self):
        ids = ["I-001", "I-002", "I-003", "I-004"]
        self.run_json(tournament=["claude", "gpt", "kimi"])
        self.cards(ids, {})
        quiet(bs.prepare_tournament, self.run)
        names = sorted(n for n in os.listdir(os.path.join(self.run, "tournament")) if n.endswith(".prompt.md"))
        self.assertEqual(len(names), 2 * 3)
        self.assertIn("kimi_rev.prompt.md", names)
        quiet(bs.prepare_tournament, self.run, per_pair=True)
        names = [n for n in os.listdir(os.path.join(self.run, "tournament")) if n.endswith(".prompt.md")]
        self.assertEqual(len(names), 2 * 3 * 6)
        self.assertIn("kimi_fwd_006.prompt.md", names)

    def test_contested_two_thirds_rule(self):
        pair = ("A", "B")

        def pts_for(winners):
            pts, kinds = {}, {}
            for f, w in winners.items():
                pts[(f, pair)] = {w: 1.0, ("B" if w == "A" else "A"): 0.0} if w else {"A": 0.5, "B": 0.5}
                kinds[(f, pair)] = "win" if w else "split"
            return pts, kinds

        info = {f: {"provisional": False, "vendor": bs.vendor(f)} for f in ("claude", "gpt", "kimi", "glm")}

        def contested(winners):
            fams = list(winners)
            pts, kinds = pts_for(winners)
            res = bs.analyze_tournament(pts, kinds, {f: [1.0, 1] for f in fams}, {}, info, fams)
            return res["contested"]

        self.assertEqual(contested({"claude": "A", "gpt": "A", "kimi": "B"}), [])          # 2/3 holds
        self.assertEqual(contested({"claude": "A", "gpt": "A", "kimi": "B", "glm": "B"}),
                         [["A", "B", "families disagree"]])                               # 2/4 < 2/3
        self.assertEqual(contested({"claude": "A", "gpt": "A", "kimi": "A", "glm": "B"}), [])  # 3/4
        self.assertEqual(contested({"claude": "A", "gpt": "B", "kimi": None}),
                         [["A", "B", "families disagree"]])                               # 1/2 of consistent
        self.assertEqual(contested({"claude": None, "gpt": None, "kimi": None}),
                         [["A", "B", "no order-consistent verdict"]])
        # N = 2: disagree -> contested; one consistent -> not contested
        self.assertEqual(contested({"claude": "A", "gpt": "B"}), [["A", "B", "families disagree"]])
        self.assertEqual(contested({"claude": "A", "gpt": None}), [])

    def test_debiased_drops_own_vendor_and_inconsistent(self):
        ids = ["I-001", "I-002", "I-003", "I-004"]
        origins = {"I-001": "claude", "I-002": "gpt", "I-003": "kimi", "I-004": "human"}
        strength = {"I-001": 4, "I-002": 3, "I-003": 2, "I-004": 1}

        def decide(fam, order, a, b):
            if fam == "glm":
                return "FIRST"  # position-biased: 0% consistent -> flagged and dropped
            return by_strength(strength)(fam, order, a, b)

        res, text = self.tourney(ids, origins, ["claude", "gpt", "kimi", "glm"], decide)
        self.assertEqual(res["flags"]["position"], ["glm"])
        self.assertEqual(res["consistency"]["glm"], 0.0)
        self.assertEqual(res["ranking"]["method"], "bradley-terry")
        self.assertEqual(res["ranking"]["families_used"], ["claude", "gpt", "kimi"])
        deb = {d["id"]: d for d in res["debiased"]}
        # every pair keeps a neutral judge (I-001 vs I-002: kimi; vs I-003: gpt; vs I-004: gpt and kimi), so all
        # 3 pairs of each card are scored, once each, and the fit follows the unanimous order
        self.assertEqual([d["id"] for d in res["debiased"]], ["I-001", "I-002", "I-003", "I-004"])
        self.assertEqual(deb["I-001"]["n"], 3)
        self.assertEqual(deb["I-004"]["n"], 3)
        self.assertEqual([d["rank"] for d in res["debiased"]], [1, 2, 3, 4])
        self.assertGreater(deb["I-001"]["pct"], deb["I-002"]["pct"])
        self.assertEqual(res["ranking"]["self_judged"], [])
        self.assertEqual(res["condorcet"], {"winner": "I-001", "cycles": []})
        # glm's 0.5 splits also pull the audit baseline down, so claude (whose own idea is best) is flagged too:
        # the spec compares against every other non-provisional judge
        self.assertIn("## Standings excluding flagged families (", text)
        self.assertIn("raw_excluding_flagged", res)
        self.assertNotIn("glm", res["raw_excluding_flagged"]["families"])
        self.assertIn("gpt", res["raw_excluding_flagged"]["families"])

    def test_self_preference_audit_and_provisional_exclusion(self):
        ids = ["I-001", "I-002", "I-003", "I-004"]
        origins = {"I-001": "gpt", "I-002": "claude", "I-003": "gpt", "I-004": "kimi"}
        strength = {"I-001": 1, "I-002": 0, "I-003": 2, "I-004": 3}

        def decide(fam, order, a, b):
            if fam in ("gpt", "kimi-alt") and (origins[a] == "gpt") != (origins[b] == "gpt"):
                return "FIRST" if origins[a] == "gpt" else "SECOND"  # prefers gpt-origin ideas
            if fam in ("kimi", "kimi-alt") and (origins[a] == "kimi") != (origins[b] == "kimi"):
                return "FIRST" if origins[a] == "kimi" else "SECOND"
            return by_strength(strength)(fam, order, a, b)

        res, text = self.tourney(ids, origins, ["claude", "gpt", "kimi"], decide,
                                 provisional=[{"stage": "tournament", "seat": "kimi", "actual": "kimi-alt",
                                               "reason": "kimi login expired"}])
        self.assertEqual(res["provisional"], ["kimi"])
        judged = [a["judge"] for a in res["audit"]]
        self.assertNotIn("kimi", judged)          # provisional judge not audited
        self.assertIn("gpt", res["flags"]["self_preference"])
        self.assertNotIn("claude", res["flags"]["self_preference"])
        gpt = [a for a in res["audit"] if a["judge"] == "gpt"][0]
        self.assertEqual(gpt["own_share"], 1.0)
        # the others' share excludes the provisional kimi seat: only claude judges the mixed pairs
        self.assertEqual(gpt["others_n"], gpt["n"])
        self.assertIn("kimi (PROVISIONAL): excluded from the audit", text)

        # an -alt label is provisional without a run.json entry
        shutil.rmtree(os.path.join(self.run, "tournament"))
        res, text = self.tourney(ids, origins, ["claude", "gpt", "kimi-alt"], decide)
        self.assertEqual(res["provisional"], ["kimi-alt"])
        self.assertNotIn("kimi-alt", [a["judge"] for a in res["audit"]])
        self.assertIn("gpt", res["flags"]["self_preference"])

    def test_result_json_shape(self):
        ids = ["I-001", "I-002", "I-003"]
        res, _text = self.tourney(ids, {"I-001": "claude"}, ["claude", "gpt", "kimi"],
                                  by_strength({"I-001": 1, "I-002": 2, "I-003": 3}))
        for key in ("families", "raw", "debiased", "contested", "consistency", "flags", "provisional"):
            self.assertIn(key, res)
        self.assertEqual(set(res["raw"][0]), {"id", "points", "max"})
        self.assertEqual(set(res["debiased"][0]), {"id", "pct", "n", "rank", "ci", "rank_range"})
        self.assertEqual(res["debiased"][0]["rank"], 1)
        lo, hi = res["debiased"][0]["ci"]
        self.assertLessEqual(lo, res["debiased"][0]["pct"])
        self.assertGreaterEqual(hi, res["debiased"][0]["pct"])
        self.assertEqual(set(res["ranking"]), {"method", "reason", "prior", "resamples", "families_used",
                                               "self_judged", "unscored"})
        self.assertEqual(res["ranking"]["resamples"], 200)
        self.assertEqual(set(res["condorcet"]), {"winner", "cycles"})
        self.assertEqual(set(res["flags"]), {"position", "self_preference"})
        self.assertEqual(res["consistency"], {"claude": 1.0, "gpt": 1.0, "kimi": 1.0})
        self.assertIsInstance(res["provisional"], list)
        json.dumps(res)

    def test_missing_order_splits_points(self):
        ids = ["I-001", "I-002", "I-003"]
        self.run_json(tournament=["claude", "gpt", "kimi"])
        self.cards(ids, {})
        quiet(bs.prepare_tournament, self.run)
        self.verdicts(by_strength({"I-001": 3, "I-002": 2, "I-003": 1}))
        os.remove(os.path.join(self.run, "tournament", "kimi_rev.out.json"))
        text = quiet(bs.tournament, self.run)
        res = self.r("tournament/result.json")
        self.assertIsNone(res["consistency"]["kimi"])
        self.assertEqual(res["raw"][0]["points"], 5.0)  # 2 + 2 + 0.5 + 0.5
        self.assertIn("missing kimi_rev.out.json", text)


class ScreenTests(RunCase):
    def screen_run(self, judges, scores_by_judge, origins, provisional=None):
        self.run_json(screen=judges, provisional=provisional)
        self.w("criteria.json", CRIT)
        ids = sorted(origins)
        self.w("origins.json", origins)
        self.w("clusters.json", {i: "C%d" % (n % 3) for n, i in enumerate(ids)})
        for fam, fn in scores_by_judge.items():
            self.w("screen/%s.out.json" % fam, {"scores": [
                {"id": i, "g1": True, "g2": True, "g3": True, "c": {k: fn(i) for k in CRIT}, "risk": "r"}
                for i in ids]})
        text = quiet(bs.screen, self.run)
        return text, self.r("screen/shortlist.json")

    def test_prepare_screen_per_seat(self):
        self.run_json(screen=["claude", "gpt", "kimi"])
        self.w("screen/header.md", "H\n")
        self.w("screen/ideas.md", "I-001 | a | b | c\nI-002 | d | e | f\nI-003 | g | h | i\n")
        out = quiet(bs.prepare_screen, self.run)
        for f in ("claude", "gpt", "kimi"):
            self.assertTrue(self.exists("screen/%s.prompt.md" % f))
        self.assertIn("3 judge families", out)

    def test_agreement_warn_and_gap_flag(self):
        ids = ["I-%03d" % i for i in range(1, 9)]
        origins = {i: ("gpt" if n < 4 else "claude") for n, i in enumerate(ids)}
        base = {i: 1 + (n % 5) for n, i in enumerate(ids)}
        judges = {
            "claude": lambda i: base[i],
            "gpt": lambda i: min(5, base[i] + (2 if origins[i] == "gpt" else 0)),   # boosts its own vendor
            "kimi": lambda i: 6 - base[i],                                           # anti-correlated
        }
        text, sl = self.screen_run(["claude", "gpt", "kimi"], judges, origins)
        self.assertIn("## Judge agreement", text)
        self.assertIn("## Own-origin gap", text)
        self.assertIn("WARN: kimi", text)
        self.assertEqual(sl["agreement"]["warn"], ["kimi"])
        gaps = {g["judge"]: g for g in sl["own_origin_gap"]}
        self.assertTrue(gaps["gpt"]["flag"])
        self.assertGreater(gaps["gpt"]["gap"], 0.5)
        self.assertEqual(gaps["gpt"]["n"], 4)
        self.assertFalse(gaps["claude"]["flag"])
        self.assertNotIn("kimi", gaps)  # no kimi-origin ideas
        self.assertIn("kimi: 0 own-vendor idea(s)", text)
        # the v1 table is still first and unchanged in shape
        self.assertTrue(text.startswith("| id | cluster | origin | score |"))

    def test_gap_excludes_provisional_and_needs_three(self):
        origins = {"I-001": "gpt-alt", "I-002": "gpt", "I-003": "gpt", "I-004": "claude", "I-005": "claude",
                   "I-006": "human", "I-007": "human", "I-008": "human"}  # the gap's baseline: 3 ideas from neither
        judges = {"claude": lambda i: 3, "gpt": lambda i: 5 if origins[i].startswith("gpt") else 3,
                  "gpt-alt": lambda i: 5}
        text, sl = self.screen_run(["claude", "gpt", "gpt-alt"], judges, origins)
        gaps = {g["judge"]: g for g in sl["own_origin_gap"]}
        self.assertEqual(gaps["gpt"]["n"], 3)   # gpt-alt origin has the vendor of gpt
        self.assertAlmostEqual(gaps["gpt"]["gap"], 2.0)  # others = claude only (gpt-alt judge is provisional)
        self.assertNotIn("gpt-alt", gaps)
        self.assertIn("gpt-alt (PROVISIONAL): excluded", text)
        self.assertNotIn("claude", gaps)  # 2 own ideas only
        judges_meta = {j["label"]: j["provisional"] for j in sl["judges"]}
        self.assertEqual(judges_meta, {"claude": False, "gpt": False, "gpt-alt": True})

    def screen_matrix(self, seats, table, metas=None):
        """table: {seat: {id: (failed gates, {criterion: score})}}, unnamed criteria score 3. Every idea is human
        (no vendor exclusion) and its own cluster; metas: {seat: family that answered it}."""
        self.run_json(screen=seats)
        self.w("criteria.json", CRIT)
        ids = sorted(set(i for per in table.values() for i in per))
        self.w("origins.json", {i: "human" for i in ids})
        self.w("clusters.json", {i: "C-" + i for i in ids})
        self.w("screen/ideas.md", "".join("%s | t | p | m\n" % i for i in ids))
        for seat, per in table.items():
            self.w("screen/%s.out.json" % seat, {"scores": [
                dict({"id": i, "c": dict((k, c.get(k, 3)) for k in CRIT), "risk": "r"},
                     **dict((g, g not in failed) for g in bs.GATES))
                for i, (failed, c) in sorted(per.items())]})
        for seat, fam in (metas or {}).items():
            self.w("screen/%s.out.json.meta.json" % seat, {"id": "5.1-" + seat, "family": fam, "status": "ok"})
        text = quiet(bs.screen, self.run)
        return text, self.r("screen/shortlist.json")

    @staticmethod
    def row(text, iid):
        return next(ln for ln in text.splitlines() if ln.startswith("| %s |" % iid))

    def test_k1_two_distinct_judges_failing_the_same_gate_kill(self):
        text, sl = self.screen_matrix(["claude", "gpt"], {
            "claude": {"I-001": (["g1"], {}), "I-002": (["g1"], {}), "I-003": ([], {}), "I-004": ([], {})},
            "gpt": {"I-001": (["g1"], {}), "I-002": (["g2"], {}), "I-003": (["g3"], {}), "I-004": ([], {})}})
        self.assertEqual(sl["killed_gate"], ["I-001"])                # both judges failed g1
        self.assertEqual(sl["flagged_gate"], ["I-002", "I-003"])      # different gates, or one judge: a flag only
        self.assertEqual(sorted(s["id"] for s in sl["shortlist"]), ["I-002", "I-003", "I-004"])
        self.assertIn("| KILL |", self.row(text, "I-001"))
        self.assertIn("| flag |", self.row(text, "I-002"))
        self.assertIn("| flag |", self.row(text, "I-003"))
        self.assertIn("| ok |", self.row(text, "I-004"))

    def test_k1_needs_two_distinct_judges(self):
        both_fail = {"I-001": (["g2"], {}), "I-002": ([], {}), "I-003": ([], {})}
        # one model answering both seats (gpt's seat fell back to claude) is one judge: its gate failure only flags
        text, sl = self.screen_matrix(["claude", "gpt"], {"claude": both_fail, "gpt": both_fail},
                                      metas={"claude": "claude", "gpt": "claude"})
        self.assertEqual(sl["killed_gate"], [])
        self.assertEqual(sl["flagged_gate"], ["I-001"])
        self.assertIn("I-001", [s["id"] for s in sl["shortlist"]])
        self.assertIn("the gpt seat was answered by claude (fallback)", text)
        # a single screen judge seat never kills either, and the table says K1 needs 2
        shutil.rmtree(os.path.join(self.run, "screen"))
        text, sl = self.screen_matrix(["claude"], {"claude": both_fail})
        self.assertEqual(sl["killed_gate"], [])
        self.assertEqual(sl["flagged_gate"], ["I-001"])
        self.assertIn("K1 needs 2", text)

    def test_k3_floor_on_the_criterion_means(self):
        # both judges have the same Feasibility mean (2.0), so centering leaves every value as scored
        text, sl = self.screen_matrix(["claude", "gpt"], {
            "claude": {"I-001": ([], {"Value": 5, "Feasibility": 1, "Fit": 5, "Distinctiveness": 5, "Evidence": 5}),
                       "I-002": ([], {"Feasibility": 2}), "I-003": ([], {"Feasibility": 1}),
                       "I-004": ([], {"Feasibility": 4})},
            "gpt": {"I-001": ([], {"Value": 5, "Feasibility": 1, "Fit": 5, "Distinctiveness": 5, "Evidence": 5}),
                    "I-002": ([], {"Feasibility": 1}), "I-003": ([], {"Feasibility": 3}),
                    "I-004": ([], {"Feasibility": 3})}})
        # I-001: mean 1.0 despite the best score; I-002: mean 1.5 (the floor is inclusive)
        self.assertEqual(sl["floor_fail"], ["I-001", "I-002"])
        self.assertEqual(max(sl["scores"], key=sl["scores"].get), "I-001")
        self.assertEqual(sl["killed_gate"], [])
        # I-003: one judge's 1 does not fail the floor when the mean (2.0) is above it
        self.assertEqual(sorted(s["id"] for s in sl["shortlist"]), ["I-003", "I-004"])
        self.assertIn("| FAIL |", self.row(text, "I-001"))
        self.assertIn("| FAIL |", self.row(text, "I-002"))
        self.assertNotIn("FAIL", self.row(text, "I-003"))

    def test_spearman(self):
        self.assertAlmostEqual(bs.spearman([1, 2, 3, 4], [10, 20, 30, 40]), 1.0)
        self.assertAlmostEqual(bs.spearman([1, 2, 3, 4], [4, 3, 2, 1]), -1.0)
        self.assertIsNone(bs.spearman([1, 2], [1, 2]))
        self.assertIsNone(bs.spearman([1, 1, 1], [1, 2, 3]))
        self.assertAlmostEqual(bs.spearman([1, 2, 2, 3], [1, 2, 3, 4]), 0.9486832980505138)


class MapAndStatusTests(RunCase):
    def test_families_json_is_authoritative(self):
        self.run_json()
        self.w("merges.json", {
            "strategy_family": {"S3": "claude"},
            "ideas": [
                {"key": "a", "title": "A", "pitch": "p", "mechanism": "m", "aliases": ["S3-01"], "cluster": "X"},
                {"key": "b", "title": "B", "pitch": "p", "mechanism": "m", "aliases": ["S5-01"], "cluster": "X"},
                {"key": "c", "title": "C", "pitch": "p", "mechanism": "m", "aliases": ["HP-01", "S3-02"],
                 "cluster": "Y"},
                {"key": "d", "title": "D", "pitch": "p", "mechanism": "m", "aliases": ["IMP-01"], "cluster": "Y"},
                {"key": "e", "title": "E", "pitch": "p", "mechanism": "m", "aliases": ["H2-01"], "cluster": "Z"}]})
        self.w("pool/_families.json", {"S3": "gpt", "S5": "kimi-alt", "IMP": "import", "HP": "claude"})
        quiet(bs.map_pool, self.run)
        origins = self.r("origins.json")
        clusters = self.r("clusters.json")
        by_title = {}
        for line in self.r("screen/ideas.md").splitlines():
            iid, title = [x.strip() for x in line.split("|")[:2]]
            by_title[title] = iid
        self.assertEqual(origins[by_title["A"]], "gpt")
        self.assertEqual(origins[by_title["B"]], "kimi-alt")
        self.assertEqual(origins[by_title["C"]], "human-mixed")  # HP is always human
        self.assertEqual(origins[by_title["D"]], "import")
        self.assertEqual(origins[by_title["E"]], "human")
        self.assertEqual(len(clusters), 5)
        cov = self.r("coverage.json")
        self.assertEqual(cov["ideas"], 5)
        self.assertEqual(cov["clusters"], 3)
        self.assertEqual(cov["axes"], {})

    def test_vendor_map(self):
        self.assertEqual(bs.vendor("claude"), "anthropic")
        self.assertEqual(bs.vendor("gpt-alt"), "openai")
        self.assertEqual(bs.vendor("kimi"), "moonshot")
        self.assertEqual(bs.vendor("glm"), "zhipu")
        self.assertEqual(bs.vendor("import"), "import")
        for nobody in ("human", "human-mixed", "ai-mixed", "?"):
            self.assertIsNone(bs.vendor(nobody))

    def test_status_v2_stages(self):
        self.run_json(mode="standard")
        self.w("09_PROBE.md", "# Probe\nRESULT: PENDING\n")
        self.w("10_ARCHITECTURE/README.md", "# A\n")
        out = quiet(bs.status, self.run)
        self.assertIn("stage 12 Architecture: 10_ARCHITECTURE/README.md", out)
        self.assertIn("stage 13 Proposal: 11_PROPOSAL/PROPOSAL.md", out)
        self.assertIn("stage 14 Handoff: 12_HANDOFF.md", out)
        self.assertNotIn("10_HANDOFF.md", out)
        self.assertIn("[x] stage 12 Architecture", out)
        self.assertIn("designed; RESULT: PENDING", out)
        self.run_json(mode="quick")
        out = quiet(bs.status, self.run)
        self.assertIn("mode: quick", out)
        self.assertIn("stage  5 Quick: decision", out)
        self.assertIn("stage 13 Proposal", out)
        self.run_json(mode="proposal")
        out = quiet(bs.status, self.run)
        self.assertIn("checks/I-001.md", out)
        self.assertNotIn("@pool", out)


if __name__ == "__main__":
    unittest.main()
