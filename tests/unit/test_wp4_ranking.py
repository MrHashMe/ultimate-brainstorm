"""bs.py tournament ranking (KIT_SPEC 5.7): pair-level Bradley-Terry instead of the per-entry debiased %, the
raw-points fallback, Condorcet winner and majority cycles, graded position consistency (TIE in both orders),
one verdict per call and pair, fallback calls counted as the family that answered, and v2-only folders."""

import contextlib
import io
import itertools
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

IDS5 = ["I-001", "I-002", "I-003", "I-004", "I-005"]


def quiet(fn, *args, **kw):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        fn(*args, **kw)
    return buf.getvalue()


def by_strength(strength):
    def decide(fam, order, a, b):
        if strength[a] == strength[b]:
            return "TIE"
        return "FIRST" if strength[a] > strength[b] else "SECOND"
    return decide


def unanimous(cards, judges, strength):
    """pts/kinds/cons as bs.tally gives them when every judge names the stronger card in both orders."""
    pts, kinds = {}, {}
    for j in judges:
        for a, b in itertools.combinations(sorted(cards), 2):
            w, lose = (a, b) if strength[a] > strength[b] else (b, a)
            pts[(j, (a, b))], kinds[(j, (a, b))] = {w: 1.0, lose: 0.0}, "win"
    return pts, kinds, dict((j, [10.0, 10]) for j in judges)


def info_for(judges):
    return dict((j, {"provisional": False, "vendor": bs.vendor(j), "actual": j}) for j in judges)


class RunCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ub-wp4-rank-")
        self.run = os.path.join(self.tmp, "brainstorm", "2026-09-26-rank")
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

    def tourney(self, ids, origins, judges, decide, provisional=None, per_pair=False, meta=None):
        """prepare-tournament, one verdict file per call from decide(family, order, first, second), tournament.
        meta: {seat: family that answered} writes an ok meta file next to that seat's outputs."""
        self.w("run.json", {"schema": 2, "run": "2026-09-26-rank", "mode": "standard",
                            "seats": {"tournament_judges": judges}, "provisional": provisional or []})
        self.w("tournament/cards.md", "".join("## %s\nTitle: %s\n\n" % (i, i) for i in ids))
        self.w("tournament/header.md", "HEADER\n")
        self.w("origins.json", origins)
        quiet(bs.prepare_tournament, self.run, per_pair=per_pair)
        d = os.path.join(self.run, "tournament")
        for name in sorted(os.listdir(d)):
            if name.endswith(".map.json"):
                m = self.r("tournament/" + name)
                out = [{"pair_id": pid, "winner": decide(m["family"], m["order"], p["first"], p["second"])}
                       for pid, p in m["pairs"].items()]
                rel = "tournament/" + name.replace(".map.json", ".out.json")
                self.w(rel, {"verdicts": out})
                if meta and m["family"] in meta:
                    self.w(rel + ".meta.json", {"id": "9.4-x", "family": meta[m["family"]], "status": "ok"})
        text = quiet(bs.tournament, self.run)
        return self.r("tournament/result.json"), text


class PairLevelRankingTests(RunCase):
    def test_unanimous_jury_keeps_the_true_order(self):
        # finding 44: origins claude, claude, claude, gpt, gpt; every judge agrees on I-001 > ... > I-005. The
        # per-entry debiased % ranked I-004 (50%, n=6) above I-003 (25%, n=8)
        origins = {"I-001": "claude", "I-002": "claude", "I-003": "claude", "I-004": "gpt", "I-005": "gpt"}
        strength = dict((i, 5 - n) for n, i in enumerate(IDS5))
        res, text = self.tourney(IDS5, origins, ["claude", "gpt", "kimi"], by_strength(strength))
        self.assertEqual([d["id"] for d in res["debiased"]], IDS5)
        self.assertEqual(res["ranking"]["method"], "bradley-terry")
        self.assertEqual([d["n"] for d in res["debiased"]], [4, 4, 4, 4, 4])  # every opponent once
        self.assertIn("## Debiased ranking (default for recommendations)", text)
        self.assertIn("Condorcet winner (beats every other finalist by pairwise majority): I-001", text)

    def test_every_origin_assignment_three_families(self):
        judges = ["claude", "gpt", "kimi"]
        strength = dict((i, 5 - n) for n, i in enumerate(IDS5))
        inversions = 0
        for combo in itertools.product(["claude", "gpt", "kimi", "human"], repeat=5):
            origins = dict(zip(IDS5, combo))
            pts, kinds, cons = unanimous(IDS5, judges, strength)
            res = bs.analyze_tournament(pts, kinds, cons, origins, info_for(judges), judges)
            order = [d["id"] for d in res["debiased"]]
            inversions += sum(1 for a, b in itertools.combinations(range(5), 2)
                              if order.index(IDS5[a]) > order.index(IDS5[b]))
            self.assertEqual(res["ranking"]["method"], "bradley-terry", combo)
        self.assertEqual(inversions, 0)

    def test_two_families_unanimous_top1(self):
        # finding 80: judges claude + gpt drop every cross-vendor pair; both vendors' judges are kept there
        judges = ["claude", "gpt"]
        strength = dict((i, 5 - n) for n, i in enumerate(IDS5))
        for combo in itertools.product(["claude", "gpt", "human"], repeat=5):
            origins = dict(zip(IDS5, combo))
            pts, kinds, cons = unanimous(IDS5, judges, strength)
            res = bs.analyze_tournament(pts, kinds, cons, origins, info_for(judges), judges)
            self.assertEqual(res["debiased"][0]["id"], "I-001", combo)
            self.assertEqual([d["id"] for d in res["debiased"]], IDS5, combo)

    def test_lone_other_vendor_card_can_win(self):
        # finding 80, case A: five claude cards and one gpt card that both judges rank first everywhere; it had
        # pct None (n=0), which the engine read as 0% and left out of the red-team set
        ids = ["I-101", "I-102", "I-103", "I-104", "I-105", "I-900"]
        origins = dict((i, "claude") for i in ids[:5])
        origins["I-900"] = "gpt"
        strength = {"I-900": 9, "I-101": 5, "I-102": 4, "I-103": 3, "I-104": 2, "I-105": 1}
        res, text = self.tourney(ids, origins, ["claude", "gpt"], by_strength(strength))
        self.assertEqual(res["debiased"][0]["id"], "I-900")
        self.assertEqual(res["debiased"][0]["n"], 5)
        self.assertEqual(len(res["ranking"]["self_judged"]), 5)  # its 5 pairs rest on both vendors' judges
        self.assertIn("Self-judged pairs (no neutral judge; both vendors' judges kept): I-101 vs I-900", text)

    def test_every_judge_flagged_falls_back_to_raw_points(self):
        # finding 47: one judge below 60% consistency; every card had pct None, read as 0%, and id order decided
        ids = ["Q-01", "Q-02", "Q-03"]

        def decide(fam, order, a, b):
            if {a, b} == {"Q-02", "Q-03"}:
                return "FIRST" if a == "Q-03" else "SECOND"  # consistent: Q-03 wins in both orders
            return "FIRST"                                    # position-biased everywhere else
        res, text = self.tourney(ids, dict((i, "claude") for i in ids), ["gpt"], decide)
        self.assertEqual(res["flags"]["position"], ["gpt"])
        self.assertEqual(res["ranking"]["method"], "raw-fallback")
        self.assertIn("flagged for position consistency", res["ranking"]["reason"])
        self.assertEqual([(d["id"], d["pct"]) for d in res["debiased"]], [("Q-03", 75.0), ("Q-01", 50.0),
                                                                          ("Q-02", 25.0)])
        self.assertIsNone(res["debiased"][0]["ci"])
        self.assertIn("RANKING FELL BACK TO RAW POINTS: every judge family is flagged", text)
        self.assertNotIn("raw_excluding_flagged", res)  # no clean family left: no empty table

    def test_disconnected_comparison_graph_falls_back_to_raw_points(self):
        # quick mode: the only judge (gpt) generated half the pool, so the cross-vendor pair has no neutral judge
        res, text = self.tourney(["Q-01", "Q-02"], {"Q-01": "claude", "Q-02": "gpt"}, ["gpt"],
                                 by_strength({"Q-01": 1, "Q-02": 2}))
        self.assertEqual(res["ranking"]["method"], "raw-fallback")
        self.assertIn("do not connect the finalists", res["ranking"]["reason"])
        self.assertEqual(res["ranking"]["unscored"], [["Q-01", "Q-02"]])
        self.assertEqual(res["debiased"][0]["id"], "Q-02")  # raw points, never the id order
        self.assertEqual(res["debiased"][0]["pct"], 100.0)

    def test_bootstrap_is_seeded(self):
        strength = dict((i, 5 - n) for n, i in enumerate(IDS5))
        noisy = by_strength(strength)

        def decide(fam, order, a, b):
            if fam == "kimi" and {a, b} == {"I-002", "I-003"}:
                return "FIRST" if a == "I-003" else "SECOND"
            return noisy(fam, order, a, b)
        res1, _ = self.tourney(IDS5, dict((i, "human") for i in IDS5), ["claude", "gpt", "kimi"], decide)
        shutil.rmtree(os.path.join(self.run, "tournament"))
        res2, _ = self.tourney(IDS5, dict((i, "human") for i in IDS5), ["claude", "gpt", "kimi"], decide)
        self.assertEqual(res1["debiased"], res2["debiased"])
        ci = dict((d["id"], d["ci"]) for d in res1["debiased"])
        self.assertLess(ci["I-003"][0], ci["I-003"][1])  # the split pair widens the interval
        self.assertEqual(res1["debiased"][0]["rank_range"][0], 1)


class CondorcetTests(RunCase):
    def test_condorcet_winner_is_reported(self):
        # finding 48 (d): I-001 beats every rival 2-1 but the summed points rank it fourth
        prefs = {"claude": "ABCDEFG", "gpt": "ACDBEFG", "kimi": "DBCEFGA"}
        ids = ["I-%03d" % n for n in range(1, 8)]
        card = dict(zip("ABCDEFG", ids))

        def decide(fam, order, a, b):
            rank = dict((card[x], n) for n, x in enumerate(prefs[fam]))
            return "FIRST" if rank[a] < rank[b] else "SECOND"
        res, text = self.tourney(ids, dict((i, "human") for i in ids), ["claude", "gpt", "kimi"], decide)
        self.assertEqual(res["condorcet"]["winner"], "I-001")
        top = res["debiased"][0]["id"]
        if top != "I-001":
            self.assertIn([min("I-001", top), max("I-001", top),
                           "rank reversal: the pairwise-majority winner is not ranked first"], res["contested"])

    def test_unanimous_cycle_is_reported_as_a_cycle(self):
        beats = {("I-001", "I-002"), ("I-002", "I-003"), ("I-003", "I-001")}

        def decide(fam, order, a, b):
            return "FIRST" if (a, b) in beats else "SECOND"
        res, text = self.tourney(["I-001", "I-002", "I-003"], {}, ["claude", "gpt", "kimi"], decide)
        self.assertEqual(res["condorcet"], {"winner": None, "cycles": [["I-001", "I-002", "I-003"]]})
        self.assertEqual(res["contested"], [["I-001", "I-002", "majority cycle"], ["I-001", "I-003", "majority cycle"],
                                            ["I-002", "I-003", "majority cycle"]])
        self.assertIn("Majority cycles (these finalists beat each other in a circle): I-001, I-002, I-003", text)


class ConsistencyTests(RunCase):
    IDS = ["I-001", "I-002", "I-003", "I-004"]
    STRENGTH = {"I-001": 4, "I-002": 3, "I-003": 2, "I-004": 1}

    def run_with(self, gpt):
        shutil.rmtree(os.path.join(self.run, "tournament"), ignore_errors=True)
        truth = by_strength(self.STRENGTH)

        def decide(fam, order, a, b):
            return gpt(order, a, b, truth(fam, order, a, b)) if fam == "gpt" else truth(fam, order, a, b)
        return self.tourney(self.IDS, dict((i, "human") for i in self.IDS), ["claude", "gpt"], decide)

    def test_tie_in_both_orders_is_consistent(self):
        # finding 52: TIE/TIE on 3 of 6 pairs made gpt 50% "consistent", flagged and dropped
        ties = {frozenset(("I-001", "I-002")), frozenset(("I-003", "I-004")), frozenset(("I-001", "I-004"))}
        res, text = self.run_with(lambda order, a, b, v: "TIE" if frozenset((a, b)) in ties else v)
        self.assertEqual(res["consistency"]["gpt"], 1.0)
        self.assertEqual(res["flags"]["position"], [])
        self.assertIn("- gpt: 6/6 = 100%", text)

    def test_primacy_judge_is_still_flagged(self):
        # FIRST when the better card is shown first, TIE otherwise: position-driven, graded 0.5
        res, _ = self.run_with(lambda order, a, b, v: "FIRST" if v == "FIRST" else "TIE")
        self.assertEqual(res["consistency"]["gpt"], 0.5)
        self.assertEqual(res["flags"]["position"], ["gpt"])
        res, _ = self.run_with(lambda order, a, b, v: "FIRST")
        self.assertEqual(res["consistency"]["gpt"], 0.0)


class OneVerdictPerCallTests(RunCase):
    def test_repeated_pair_id_does_not_stand_in_for_the_missing_order(self):
        # finding 49: a fwd output repeating P01 with the rev output missing read as "both orders, consistent"
        self.w("run.json", {"schema": 2, "seats": {"tournament_judges": ["claude"]}})
        self.w("tournament/cards.md", "## I-001\nTitle: a\n\n## I-002\nTitle: b\n")
        self.w("tournament/header.md", "H\n")
        quiet(bs.prepare_tournament, self.run)
        m = self.r("tournament/claude_fwd.map.json")
        first = m["pairs"]["P01"]["first"]
        self.w("tournament/claude_fwd.out.json", {"verdicts": [{"pair_id": "P01", "winner": "FIRST"},
                                                               {"pair_id": "P01", "winner": "FIRST"}]})
        text = quiet(bs.tournament, self.run)
        res = self.r("tournament/result.json")
        self.assertEqual([r["points"] for r in res["raw"]], [0.5, 0.5])
        self.assertIsNone(res["consistency"]["claude"])
        self.assertIn("claude_fwd.out.json: P01 judged twice; the first verdict counts", text)
        self.assertIn("missing claude_rev.out.json", text)
        self.assertTrue(first)


class FallbackJudgeTests(RunCase):
    def test_fallback_call_counts_as_the_family_that_answered(self):
        # finding 50: the gpt seat failed and the host (claude) answered into gpt's files. The same model voted
        # twice, turned a claude-vs-kimi split into a 2/3 majority, and every audit went PROVISIONAL
        origins = {"I-001": "claude", "I-002": "human", "I-003": "kimi"}
        order = {"claude": ["I-001", "I-002", "I-003"], "kimi": ["I-003", "I-002", "I-001"]}

        def decide(fam, o, a, b):
            pref = order["kimi" if fam == "kimi" else "claude"]  # the gpt seat is claude
            return "FIRST" if pref.index(a) < pref.index(b) else "SECOND"
        prov = [{"stage": "Tournament judges", "seat": "gpt", "actual": "claude", "reason": "codex failed"}]
        res, text = self.tourney(["I-001", "I-002", "I-003"], origins, ["claude", "gpt", "kimi"], decide,
                                 provisional=prov, meta={"gpt": "claude", "claude": "claude", "kimi": "kimi"})
        self.assertEqual(res["families"], ["claude", "kimi"])
        self.assertIn(["I-001", "I-003", "families disagree"], res["contested"])
        self.assertEqual(res["provisional"], [])            # the host's own seat stays a real judge
        self.assertEqual([a["judge"] for a in res["audit"]], ["claude", "kimi"])
        self.assertEqual(res["raw"][0]["max"], 4)           # 2 families x 2 opponents
        self.assertEqual(sorted(s["call"] for s in res["substitutions"]), ["gpt_fwd.out.json", "gpt_rev.out.json"])
        self.assertIn("- gpt_fwd.out.json: the gpt seat was answered by claude", text)

    def test_fallback_to_a_new_family_is_provisional(self):
        prov = [{"stage": "Tournament judges", "seat": "gpt", "actual": "glm", "reason": "codex failed"}]
        res, text = self.tourney(["I-001", "I-002", "I-003"], {}, ["claude", "gpt"],
                                 by_strength({"I-001": 3, "I-002": 2, "I-003": 1}), provisional=prov,
                                 meta={"gpt": "glm"})
        self.assertEqual(res["families"], ["claude", "glm"])
        self.assertEqual(res["provisional"], ["glm"])
        self.assertIn("glm (PROVISIONAL): excluded from the audit", text)


class SchemaAndFolderTests(RunCase):
    def test_verdict_schema_has_only_read_fields(self):
        # finding 90: confidence and decisive_reason were required and never read
        self.w("criteria.json", {"Value": 60, "Feasibility": 40})
        quiet(bs.schemas, self.run)
        item = self.r("tournament/verdicts.schema.json")["properties"]["verdicts"]["items"]
        self.assertEqual(item["required"], ["pair_id", "winner"])
        self.assertEqual(sorted(item["properties"]), sorted(item["required"]))  # strict structured outputs
        crit = self.r("screen/screen.schema.json")["properties"]["scores"]["items"]["properties"]["c"]["properties"]
        self.assertEqual(crit["Value"], {"type": "integer", "minimum": 1, "maximum": 5})

    def test_v1_folder_points_to_ub_continue(self):
        self.w("00_RUN.md", "# Run\n- mode: standard\n")
        self.w("tournament/cards.md", "## I-001\nx\n\n## I-002\ny\n")
        env = dict(os.environ, PYTHONIOENCODING="utf-8")
        for cmd in ("status", "prepare-screen", "screen", "prepare-tournament", "tournament"):
            p = subprocess.run([sys.executable, os.path.join(_SCRIPTS, "bs.py"), cmd, self.run],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
            self.assertEqual(p.returncode, 4, cmd)
            self.assertIn(b"run.json (schema 2) missing", p.stderr, cmd)
            self.assertIn(b"ub.py\" continue", p.stderr, cmd)


if __name__ == "__main__":
    unittest.main()
