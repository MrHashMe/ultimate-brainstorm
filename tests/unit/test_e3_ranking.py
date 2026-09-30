"""Phase E3, tournament ranking (KIT_SPEC 5.7): a judge's one-order verdicts are never evidence (review R-ranking-0,
findings 44 and 80), a seat's own -alt fallback stays paired under the seat, and an older result.json with a card
that has no debiased % ranks every card by raw points."""

import contextlib
import io
import itertools
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fixtures", "engine"))
import engine_testlib as tl  # noqa: E402

import bs  # noqa: E402
from ublib.engine import registry  # noqa: E402

# the reviewer's config 2: the true order I-001 (claude) > I-002 (human) > I-003 (gpt) > I-004 (human)
ORIGINS = {"I-001": "claude", "I-002": "human", "I-003": "gpt", "I-004": "human"}
STRENGTH = {"I-001": 4, "I-002": 3, "I-003": 2, "I-004": 1}


def quiet(fn, *args, **kw):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        fn(*args, **kw)
    return buf.getvalue()


class RunCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ub-e3-rank-")
        self.run = os.path.join(self.tmp, "brainstorm", "2026-09-26-e3-rank")
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
            return json.load(f)

    def tourney(self, judges, answered=None, missing=(), provisional=None, origins=ORIGINS, strength=STRENGTH):
        """A unanimous jury (every model names the stronger card in both orders). answered: {call base name: the
        family whose meta file answers it}; every other call gets its seat's own meta. missing: calls with no
        output (their job failed with no fallback)."""
        ids = sorted(origins)
        self.w("run.json", {"schema": 2, "run": "2026-09-26-e3-rank", "mode": "standard",
                            "seats": {"tournament_judges": judges}, "provisional": provisional or []})
        self.w("tournament/cards.md", "".join("## %s\nTitle: %s\n\n" % (i, i) for i in ids))
        self.w("tournament/header.md", "HEADER\n")
        self.w("origins.json", origins)
        quiet(bs.prepare_tournament, self.run)
        d = os.path.join(self.run, "tournament")
        for name in sorted(os.listdir(d)):
            if not name.endswith(".map.json"):
                continue
            call = name[: -len(".map.json")]
            if call in missing:
                continue
            m = self.r("tournament/" + name)
            out = [{"pair_id": pid, "winner": "FIRST" if strength[p["first"]] > strength[p["second"]] else "SECOND"}
                   for pid, p in m["pairs"].items()]
            self.w("tournament/%s.out.json" % call, {"verdicts": out})
            fam = (answered or {}).get(call, m["family"])
            self.w("tournament/%s.out.json.meta.json" % call, {"id": "9.4-" + call, "family": fam, "status": "ok"})
        text = quiet(bs.tournament, self.run)
        return self.r("tournament/result.json"), text

    def assert_true_order(self, res, method="bradley-terry"):
        self.assertEqual([d["id"] for d in res["debiased"]], ["I-001", "I-002", "I-003", "I-004"])
        self.assertEqual(res["condorcet"]["winner"], "I-001")
        self.assertEqual(res["flags"]["self_preference"], [])
        self.assertEqual(res["ranking"]["method"], method)


class OneOrderFallbackTests(RunCase):
    def test_control_no_fallback(self):
        res, _text = self.tourney(["claude", "gpt"])
        self.assert_true_order(res)

    def test_the_seats_own_alt_answering_one_order_keeps_the_seat_paired(self):
        # R-ranking-0 case (a): gpt_rev failed and gpt-alt (alt_model null: the same model) answered it. The seat
        # split into two one-order judges whose forced 0.5s counted as neutral evidence: I-002 ranked first
        prov = [{"stage": "Tournament judges", "seat": "gpt", "actual": "gpt-alt", "reason": "codex timed out"}]
        res, text = self.tourney(["claude", "gpt"], answered={"gpt_rev": "gpt-alt"}, provisional=prov)
        self.assert_true_order(res)
        self.assertEqual(res["families"], ["claude", "gpt"])
        self.assertEqual(res["consistency"]["gpt"], 1.0)
        self.assertEqual(res["provisional"], [])
        self.assertEqual(res["substitutions"], [{"seat": "gpt", "actual": "gpt-alt", "call": "gpt_rev.out.json"}])
        self.assertIn("- gpt_rev.out.json: the gpt seat was answered by gpt-alt", text)

    def test_both_orders_by_the_alt_stay_a_provisional_alt_judge(self):
        prov = [{"stage": "Tournament judges", "seat": "gpt", "actual": "gpt-alt", "reason": "codex failed"}]
        res, _text = self.tourney(["claude", "gpt"], answered={"gpt_fwd": "gpt-alt", "gpt_rev": "gpt-alt"},
                                  provisional=prov)
        self.assertEqual(res["families"], ["claude", "gpt-alt"])
        self.assertEqual(res["provisional"], ["gpt-alt"])

    def test_the_host_answering_one_order_is_no_evidence(self):
        # R-ranking-0 case (b): gpt_rev answered by the host; gpt keeps one order, claude answered three calls
        prov = [{"stage": "Tournament judges", "seat": "gpt", "actual": "claude", "reason": "codex failed"}]
        res, _text = self.tourney(["claude", "gpt"], answered={"gpt_rev": "claude"}, provisional=prov)
        # without gpt's both-order verdicts no neutral judge sees I-001 (claude's card): the ranking falls back to
        # raw points, with the reason, instead of deciding its pairs on forced ties
        self.assert_true_order(res, "raw-fallback")
        self.assertIn("do not connect the finalists", res["ranking"]["reason"])
        self.assertIsNone(res["consistency"]["gpt"])

    def test_a_missing_order_is_no_evidence(self):
        # R-ranking-0 case (c) and finding 80 residual (1): gpt's rev call is missing and no fallback ran
        res, text = self.tourney(["claude", "gpt"], missing=("gpt_rev",))
        self.assert_true_order(res, "raw-fallback")
        self.assertEqual([a["judge"] for a in res["audit"] if a["flag"]], [])
        self.assertIn("gpt: only one order judged; its verdicts count 0.5/0.5 in the raw standings and are left out "
                      "of the debiased ranking", text)

    def test_three_families_lone_gpt_card_keeps_rank_one(self):
        # finding 44 residual: 5 claude cards and the best card from gpt, a unanimous jury; kimi's rev call is gone,
        # so kimi (the only neutral judge of every claude-vs-gpt pair) had forced 0.5s that decided those pairs
        origins = dict(("I-%03d" % n, "claude") for n in range(1, 6))
        origins["I-006"] = "gpt"
        strength = {"I-006": 9, "I-001": 5, "I-002": 4, "I-003": 3, "I-004": 2, "I-005": 1}
        res, _text = self.tourney(["claude", "gpt", "kimi"], missing=("kimi_rev",), origins=origins,
                                  strength=strength)
        self.assertEqual([d["id"] for d in res["debiased"]], ["I-006", "I-001", "I-002", "I-003", "I-004", "I-005"])
        self.assertEqual(res["flags"]["self_preference"], [])

    def test_every_origin_assignment_with_one_half_drawn_judge(self):
        # the confirmer's sweep: unanimous juries, one gpt call answered by gpt-alt; 0 wrong orders and 0 flags
        judges = ["claude", "gpt"]
        ids = ["I-001", "I-002", "I-003", "I-004", "I-005"]
        strength = dict((i, 5 - n) for n, i in enumerate(ids))
        for combo in itertools.product(["claude", "gpt", "human"], repeat=5):
            origins = dict(zip(ids, combo))
            votes = []
            for f, order in itertools.product(judges, ("fwd", "rev")):
                label = "gpt-alt" if (f, order) == ("gpt", "rev") else f
                for a, b in itertools.combinations(ids, 2):
                    votes.append((label, (a, b), order, a if strength[a] > strength[b] else b))
            pts, kinds, cons = bs.tally(votes)
            labels = sorted(set(f for f, _p in pts))
            info = dict((j, {"provisional": j.endswith("-alt"), "vendor": bs.vendor(j), "actual": j})
                        for j in labels)
            res = bs.analyze_tournament(pts, kinds, cons, origins, info, judges)
            self.assertEqual([d["id"] for d in res["debiased"]], ids, combo)
            self.assertEqual(res["flags"]["self_preference"], [], combo)

    def test_only_one_order_everywhere_falls_back_with_the_right_reason(self):
        res, text = self.tourney(["gpt"], missing=("gpt_rev",))
        self.assertEqual(res["ranking"]["method"], "raw-fallback")
        self.assertIn("judged a pair in both orders", res["ranking"]["reason"])
        self.assertNotIn("flagged for position consistency", res["ranking"]["reason"])


class OlderResultTests(tl.EngineTestCase):
    def test_a_card_without_a_debiased_pct_ranks_everyone_by_raw_points(self):
        # finding 80 residual (2): a result.json kit 2.0.3 wrote where the lone gpt card has pct None was ranked last
        # (out of the red-team set) although it led on raw points
        ctx = self.make_ctx(run_name="2026-09-26-e3-older")
        fin = ["I-101", "I-102", "I-103", "I-900"]
        ctx.state["finalists"] = fin
        ctx.write_json("tournament/result.json", {
            "debiased": [{"id": "I-101", "pct": 70.0, "n": 2}, {"id": "I-102", "pct": 55.0, "n": 2},
                         {"id": "I-103", "pct": 40.0, "n": 2}, {"id": "I-900", "pct": None, "n": 0}],
            "raw": [{"id": "I-900", "points": 6.0, "max": 6}, {"id": "I-101", "points": 4.0, "max": 6},
                    {"id": "I-102", "points": 2.0, "max": 6}, {"id": "I-103", "points": 0.0, "max": 6}]})
        rk = registry.ranking(ctx)
        self.assertEqual(rk["order"], ["I-900", "I-101", "I-102", "I-103"])
        self.assertEqual(rk["method"], "raw")
        self.assertIn("I-900 without a debiased %", rk["note"])
        registry.SCRIPTS["top"](ctx, {"id": "10.1"})
        self.assertEqual(ctx.state["top"], ["I-900", "I-101", "I-102"])
        self.assertIn("Note: the ranking uses raw tournament points (an older tally", ctx.read("07_TOP.md"))

    def test_an_older_result_that_scores_every_card_keeps_its_percentages(self):
        ctx = self.make_ctx(run_name="2026-09-26-e3-older-ok")
        ctx.write_json("tournament/result.json", {
            "debiased": [{"id": "I-001", "pct": 30.0}, {"id": "I-002", "pct": 60.0}],
            "raw": [{"id": "I-001", "points": 2.0, "max": 2}, {"id": "I-002", "points": 0.0, "max": 2}]})
        rk = registry.ranking(ctx)
        self.assertEqual((rk["order"], rk["method"], rk["note"]), (["I-002", "I-001"], "debiased (older result)", ""))


if __name__ == "__main__":
    unittest.main()
