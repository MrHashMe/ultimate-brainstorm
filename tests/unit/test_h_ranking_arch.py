"""Phase H (HC-ranking-seats), bs.py arch-matrix and the G11 card (KIT_SPEC 5.7, 4.12, 6.2).

- Finding 46: two families judging each other's candidates (the balanced design) report the pair's combined
  self-preference, which the per-judge gap measures only diluted; a flagged pair keeps a lead over the other family's
  candidates from being 'clear'. A criterion left out of W (a judge omitted a candidate's score) makes the lead a
  close call instead of 'clear' with a warning line only.
- Finding 81 (option a): a candidate only its author family's judge scored is self-judged also when no judge of
  another family was seated for it (2-family quick mode: the one arch judge is the host, which wrote a candidate), so
  quick guided runs ask at G11; a one-family run is not self-judged.
- NEW-G5-ranking-1: the G11 card never says a candidate was scored by a judge of another family when only its author
  family's judge scored it.
"""

import contextlib
import io
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fixtures", "engine"))
import engine_testlib as tl  # noqa: E402

import bs  # noqa: E402
from ublib.engine import gates  # noqa: E402
from ublib.engine import state as st  # noqa: E402

QGS = [{"id": "QG1", "name": "Reliability", "weight": 30}, {"id": "QG2", "name": "Privacy", "weight": 25},
       {"id": "QG3", "name": "Latency", "weight": 15}]
CRITERIA = ["QG1", "QG2", "QG3", "time_to_mvp", "team_fit", "run_cost", "reversibility", "operational_simplicity"]


def cand(label, score, overrides=None, drop=()):
    s = dict((c, score) for c in CRITERIA if c not in drop)
    s.update(overrides or {})
    return {"label": label, "veto": False, "veto_reason": "", "sensitivity_points": [], "tradeoff_points": [],
            "scores": [{"criterion": c, "score": v, "reason": "r"} for c, v in s.items()]}


class Case(tl.EngineTestCase):
    def ctx_for(self, mode="standard", families=tl.FAMS, autopilot="guided"):
        ctx = self.make_ctx(mode=mode, families=families, autopilot=autopilot, run_name="2026-09-27-h-arch")
        st.save(ctx.run_dir, ctx.state)  # bs.py arch-matrix reads the seated arch judges from run.json
        ctx.write_json("10_ARCHITECTURE/drivers.json", {"product_goal": "x", "quality_goals": QGS})
        return ctx

    def cmap(self, ctx, authors):
        ctx.write_json("10_ARCHITECTURE/candidates/map.json",
                       dict((k, {"family": v, "archetype": "A", "job": "12.4-" + k}) for k, v in authors.items()))

    def judge(self, ctx, fam, cands):
        ctx.write_json("10_ARCHITECTURE/review/judge_%s.out.json" % fam, {"candidates": cands, "steal": []})

    def matrix(self, ctx):
        with contextlib.redirect_stdout(io.StringIO()):
            bs.arch_matrix(ctx.run_dir)
        return ctx.read_json("10_ARCHITECTURE/matrix.json"), ctx.read("10_ARCHITECTURE/tradeoff-matrix.md")

    def line(self, ctx, label):
        return next(ln for ln in gates.gate_values(ctx, "G11")["MATRIX_SUMMARY"].split("\n")
                    if ln.startswith("- %s" % label))


class PairSelfPreferenceTests(Case):
    """2 families judging each other's candidates: A and C are gpt's, B is claude's. gpt adds 1 to its own two
    candidates; truly B is best (QG2 4), A next, C last. The per-judge gaps split the +1 between the judges (and flag
    the honest one), so before the fix the lead of A was 'clear'."""

    def scores(self, ctx, bias):
        truth = {"A": cand("A", 3, {"QG1": 4}), "B": cand("B", 3, {"QG1": 4, "QG2": 4}),
                 "C": cand("C", 3, {"QG1": 4, "QG3": 2})}
        self.judge(ctx, "claude", [truth[x] for x in "ABC"])
        self.judge(ctx, "gpt", [cand("A", 3 + bias, {"QG1": 4 + bias}), truth["B"],
                                cand("C", 3 + bias, {"QG1": 4 + bias, "QG3": 2 + bias})])

    def test_a_flagged_pair_self_preference_keeps_the_lead_from_being_clear(self):
        ctx = self.ctx_for(families=("claude", "gpt"))
        self.cmap(ctx, {"A": "gpt", "B": "claude", "C": "gpt"})
        self.scores(ctx, 1)
        m, md = self.matrix(ctx)
        self.assertEqual(m["design"]["judges"], "all (balanced own-family judges)")
        self.assertEqual(m["own_candidate_pairs"], [{"a": "claude", "b": "gpt", "gap": 1.0, "n_a": 1, "n_b": 2,
                                                     "flag": True}])
        self.assertEqual((m["leader"], m["leader_status"]), ("A", "close-call"))
        self.assertIn("Leader: A (close-call: two families' judges favour their own family's candidates by +1.00 "
                      "combined (which one adds how much cannot be told), which can put B behind)", md)
        self.assertIn("- two judges together: +1.00 on their own families' candidates", md)
        for fam in ("claude", "gpt"):
            self.assertNotIn(fam, md)  # the markdown stays blind to the authors' families

    def test_without_self_preference_the_pair_is_not_flagged(self):
        ctx = self.ctx_for(families=("claude", "gpt"))
        self.cmap(ctx, {"A": "gpt", "B": "claude", "C": "gpt"})
        self.scores(ctx, 0)
        m, _md = self.matrix(ctx)
        self.assertEqual([p["flag"] for p in m["own_candidate_pairs"]], [False])
        self.assertEqual(m["leader"], "B")

    def test_three_families_report_no_pair(self):
        # every candidate has two eligible judges: the per-judge gap applies, the pair statistic is not needed
        ctx = self.ctx_for(families=("claude", "gpt", "kimi"))
        self.cmap(ctx, {"A": "claude", "B": "gpt", "C": "kimi"})
        for fam in ("claude", "gpt", "kimi"):
            self.judge(ctx, fam, [cand("A", 3), cand("B", 5), cand("C", 2)])
        m, _md = self.matrix(ctx)
        self.assertEqual(m["own_candidate_pairs"], [])
        self.assertEqual((m["leader"], m["leader_status"]), ("B", "clear"))


class DroppedCriterionTests(Case):
    def test_a_criterion_left_out_of_w_makes_the_lead_a_close_call(self):
        # gpt leaves out C's weak QG1 (it would give 1): QG1 leaves W for everyone and C leads; that was 'clear'
        ctx = self.ctx_for(families=("claude", "gpt"))
        self.cmap(ctx, {"A": "claude", "B": "gpt", "C": "claude"})
        self.judge(ctx, "claude", [cand("A", 4), cand("B", 3), cand("C", 4)])
        self.judge(ctx, "gpt", [cand("A", 4), cand("B", 3), cand("C", 5, drop=("QG1",))])
        m, md = self.matrix(ctx)
        self.assertEqual((m["leader"], m["leader_status"]), ("C", "close-call"))
        self.assertIn("criteria without an eligible judge's score for every ranked candidate are left out of W: QG1",
                      m["warnings"])
        self.assertIn("Leader: C (close-call: criteria left out of W (no eligible judge's score for every ranked "
                      "candidate): QG1)", md)


class QuickSelfJudgedTests(Case):
    def quick(self, families, authors, autopilot="guided"):
        ctx = self.ctx_for(mode="quick", families=families, autopilot=autopilot)
        self.cmap(ctx, authors)
        judge = ctx.seats["arch_judges"]
        self.assertEqual(len(judge), 1)  # quick mode seats one arch judge
        self.judge(ctx, judge[0], [cand("A", 3), cand("C", 5)])
        return ctx

    def test_two_families_the_hosts_own_candidate_is_self_judged_and_guided_asks(self):
        # finding 81: the one quick arch judge is the host (claude), which also wrote C; its own C wins with a lead
        # that was 'clear' and auto-accepted in every quick autopilot mode
        ctx = self.quick(("claude", "gpt"), {"A": "gpt", "C": "claude"})
        self.assertEqual(ctx.seats["arch_judges"], ["claude"])
        m, md = self.matrix(ctx)
        self.assertEqual(m["self_judged"], ["C"])
        self.assertEqual((m["leader"], m["leader_status"]), ("C", "self-judged"))
        self.assertIn("Leader: C (self-judged: only its author family's judge scored it; the human decides)", md)
        label, why = gates.g11_recommendation(ctx)
        self.assertEqual(label, "C")
        self.assertIn("(no judge of another family did; quick mode seats one arch judge, of that family)", why)
        self.assertEqual(gates.policy(ctx, "G11"), "ask")
        # NEW-G5-ranking-1: the card says who scored each candidate
        self.assertTrue(self.line(ctx, "C").endswith("scored by its author family's judge only"), self.line(ctx, "C"))
        self.assertTrue(self.line(ctx, "A").endswith("scored by 1 judge of other families"), self.line(ctx, "A"))

    def test_full_auto_takes_the_self_judged_leader_with_a_note(self):
        ctx = self.quick(("claude", "gpt"), {"A": "gpt", "C": "claude"}, autopilot="full-auto")
        self.matrix(ctx)
        self.assertEqual(gates.policy(ctx, "G11"), "auto")
        ans = gates.merge_answer("G11", gates.default_answer("G11"), ctx)
        gates.apply(ctx, "G11", ans, by="auto")
        self.assertEqual(ctx.state["choice"]["arch"], "C")
        self.assertIn("G11 auto: the lead of C is self-judged", " ".join(ctx.state.get("notes") or []))

    def test_one_family_is_not_self_judged_and_the_card_says_who_scored(self):
        # a one-family run: the only family wrote and judged both candidates; nothing to flag, but the card said
        # 'scored by 1 judge of other families' (NEW-G5-ranking-1)
        ctx = self.quick(("claude",), {"A": "claude", "C": "claude"})
        m, _md = self.matrix(ctx)
        self.assertEqual(m["self_judged"], [])
        self.assertNotEqual(m["leader_status"], "self-judged")
        self.assertEqual(gates.policy(ctx, "G11"), "auto")
        for label in ("A", "C"):
            self.assertTrue(self.line(ctx, label).endswith(
                "scored by its author family's judge only (one model family: no other family's judge)"),
                self.line(ctx, label))

    def test_three_families_the_quick_judge_wrote_nothing(self):
        ctx = self.quick(("claude", "gpt", "kimi"), {"A": "gpt", "C": "kimi"})
        m, _md = self.matrix(ctx)
        self.assertEqual(m["self_judged"], [])
        self.assertEqual((m["leader"], m["leader_status"]), ("C", "clear"))
        self.assertEqual(gates.policy(ctx, "G11"), "auto")
        for label in ("A", "C"):
            self.assertTrue(self.line(ctx, label).endswith("scored by 1 judge of other families"))


if __name__ == "__main__":
    import unittest
    unittest.main()
