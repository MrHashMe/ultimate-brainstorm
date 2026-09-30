"""Phase E3, bs.py arch-matrix and G11 (KIT_SPEC 5.7, 6.2): shared criteria need an eligible judge's score for every
ranked candidate, also in the balanced design (finding 46); a judge that favours its own family's candidate keeps a
lead it tilts from being 'clear'; a leader or runner-up only its author family judged is 'self-judged' and G11 says
so, shows judges per candidate and the matrix warnings (finding 81)."""

import contextlib
import io
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fixtures", "engine"))
import engine_testlib as tl  # noqa: E402

import bs  # noqa: E402
from ublib.engine import gates  # noqa: E402

QGS = [{"id": "QG1", "name": "Reliability", "weight": 30}, {"id": "QG2", "name": "Privacy", "weight": 25},
       {"id": "QG3", "name": "Latency", "weight": 15}]
CRITERIA = ["QG1", "QG2", "QG3", "time_to_mvp", "team_fit", "run_cost", "reversibility", "operational_simplicity"]


def cand(label, score, veto=False, overrides=None, drop=()):
    s = dict((c, score) for c in CRITERIA if c not in drop)
    s.update(overrides or {})
    return {"label": label, "veto": veto, "veto_reason": "", "sensitivity_points": [], "tradeoff_points": [],
            "scores": [{"criterion": c, "score": v, "reason": "r"} for c, v in s.items()]}


class MatrixCase(tl.EngineTestCase):
    def setUp(self):
        tl.EngineTestCase.setUp(self)
        self.ctx = self.make_ctx(run_name="2026-09-26-e3-arch")
        self.arch = self.ctx.path("10_ARCHITECTURE")
        self.ctx.write_json("10_ARCHITECTURE/drivers.json", {"product_goal": "x", "quality_goals": QGS})

    def cmap(self, authors):
        self.ctx.write_json("10_ARCHITECTURE/candidates/map.json",
                            dict((k, {"family": v, "archetype": "A", "job": "12.4-" + k}) for k, v in authors.items()))

    def judge(self, fam, cands):
        self.ctx.write_json("10_ARCHITECTURE/review/judge_%s.out.json" % fam, {"candidates": cands, "steal": []})

    def matrix(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            bs.arch_matrix(self.ctx.run_dir)
        m = self.ctx.read_json("10_ARCHITECTURE/matrix.json")
        return m, dict((c["label"], c) for c in m["candidates"]), self.ctx.read("10_ARCHITECTURE/tradeoff-matrix.md")


class SharedCriteriaTests(MatrixCase):
    def test_an_own_family_score_never_fills_a_criterion_the_other_family_left_out(self):
        # finding 46 residual (1): two families judging each other's candidates (balanced design). B's only
        # other-family judge (gpt) omits B's weak time_to_mvp; claude's own score for B filled it, with no warning
        self.cmap({"A": "gpt", "B": "claude", "C": "gpt"})
        self.judge("claude", [cand("A", 3), cand("B", 4, overrides={"time_to_mvp": 1}), cand("C", 3)])
        self.judge("gpt", [cand("A", 4), cand("B", 4, drop=("time_to_mvp",)), cand("C", 4)])
        m, c, _md = self.matrix()
        self.assertEqual(m["design"]["judges"], "all (balanced own-family judges)")
        self.assertIn("criteria without an eligible judge's score for every ranked candidate are left out of W: "
                      "time_to_mvp", m["warnings"])
        weak = c["B"]["score"]
        self.judge("claude", [cand("A", 3), cand("B", 4, overrides={"time_to_mvp": 5}), cand("C", 3)])
        _m, c, _md = self.matrix()
        self.assertEqual(c["B"]["score"], weak)  # B's own family's time_to_mvp score no longer moves its W


class LeniencyAndSelfPreferenceTests(MatrixCase):
    def test_leniency_in_a_three_family_design_cancels(self):
        # finding 46 (3): no test covered leniency when every candidate has two eligible judges. gpt is one point
        # more lenient on everything; B (gpt's) is truly best by 0.3 on QG1 but only claude and kimi score it
        self.cmap({"A": "claude", "B": "gpt", "C": "kimi"})
        self.judge("claude", [cand("A", 3), cand("B", 3, overrides={"QG1": 4}), cand("C", 3)])
        self.judge("gpt", [cand("A", 4, overrides={"QG1": 4}), cand("B", 4, overrides={"QG1": 5}), cand("C", 4)])
        self.judge("kimi", [cand("A", 3), cand("B", 3, overrides={"QG1": 4}), cand("C", 3)])
        m, c, _md = self.matrix()
        self.assertEqual(m["leader"], "B")
        self.assertEqual(m["judge_offsets"]["gpt"], max(m["judge_offsets"].values()))

    def test_an_own_candidate_favourite_never_reads_clear(self):
        # finding 46 residual (2): gpt gives its own B a 5 where the others give 3. That raises gpt's mean, so its
        # centered score of the leader C (which it judges) drops against the runner-up B (which it does not): a lead
        # the bias tilts is a close call, and the gap is reported without naming the judge
        self.cmap({"A": "claude", "B": "gpt", "C": "kimi"})
        self.judge("claude", [cand("A", 3), cand("B", 3), cand("C", 4)])
        self.judge("gpt", [cand("A", 3), cand("B", 5), cand("C", 4)])
        self.judge("kimi", [cand("A", 3), cand("B", 3), cand("C", 3)])
        m, c, md = self.matrix()
        gaps = dict((g["judge"], g) for g in m["own_candidate_gap"])
        self.assertTrue(gaps["gpt"]["flag"])
        self.assertFalse(gaps["kimi"]["flag"])
        self.assertEqual(m["leader"], "C")
        self.assertEqual(m["leader_status"], "close-call")
        self.assertIn("a judge that favours its own family's candidate (own-candidate gap above 0.5) counts for one "
                      "of the leader and the runner-up only", md)
        for fam in ("claude", "gpt", "kimi"):
            self.assertNotIn(fam, md)

    def test_a_lead_nobody_tilts_stays_clear(self):
        self.cmap({"A": "claude", "B": "gpt", "C": "kimi"})
        for fam in ("claude", "gpt", "kimi"):
            self.judge(fam, [cand("A", 3), cand("B", 5), cand("C", 2)])
        m, _c, md = self.matrix()
        self.assertEqual((m["leader"], m["leader_status"]), ("B", "clear"))


class SelfJudgedLeaderTests(MatrixCase):
    def setup_missing_judge(self, seated=("claude", "gpt")):
        # finding 81 residual: 2 families, the gpt arch judge failed (no output): claude alone scores its own B
        self.ctx.write_json("run.json", {"schema": 2, "run": self.ctx.state["run"], "mode": self.ctx.mode,
                                         "seats": {"arch_judges": list(seated)}})
        self.cmap({"A": "gpt", "B": "claude", "C": "gpt"})
        self.judge("claude", [cand("A", 3), cand("B", 5), cand("C", 2)])

    def test_the_matrix_calls_it_self_judged(self):
        self.setup_missing_judge()
        m, c, md = self.matrix()
        self.assertEqual((m["leader"], m["leader_status"]), ("B", "self-judged"))
        self.assertEqual(m["self_judged"], ["B"])
        self.assertIn("Leader: B (self-judged: only its author family's judge scored it; the human decides)", md)

    def test_one_seated_judge_of_the_authors_family_is_self_judged_too(self):
        # 2-family quick mode seats one arch judge, the host, which also wrote a candidate: only its author family
        # scored that candidate, which is self-judged by design (finding 81, option a), so quick guided asks at G11
        self.setup_missing_judge(seated=("claude",))
        m, _c, _md = self.matrix()
        self.assertEqual(m["self_judged"], ["B"])
        self.assertEqual(m["leader_status"], "self-judged")

    def test_g11_explains_it_and_shows_judges_and_warnings(self):
        self.setup_missing_judge()
        self.matrix()
        label, why = gates.g11_recommendation(self.ctx)
        self.assertEqual(label, "B")
        self.assertIn("the lead of B is self-judged: only the author family's judge scored it", why)
        self.assertTrue(gates.g11_contested(self.ctx))  # quick and guided ask; full-auto records the note
        vals = gates.gate_values(self.ctx, "G11")
        self.assertIn("- B", vals["MATRIX_SUMMARY"])
        self.assertIn("scored by its author family's judge only", vals["MATRIX_SUMMARY"])
        self.assertIn("scored by 1 judge of other families", vals["MATRIX_SUMMARY"])
        self.assertIn("Matrix warnings:\n  - candidate B: no judge from another family; all judges used",
                      vals["MATRIX_SUMMARY"])
        self.assertTrue(vals["ARCH_SUGGESTION"].startswith("B (self-judged); the lead of B is self-judged"))
        ans = gates.merge_answer("G11", gates.default_answer("G11"), self.ctx)
        gates.apply(self.ctx, "G11", ans, by="auto")
        self.assertIn("G11 auto: the lead of B is self-judged", " ".join(self.ctx.state.get("notes") or []))

    def test_a_replaced_vetoed_leader_shows_the_suggestions_own_status(self):
        # finding 81 (4): the card showed the vetoed leader's status next to the replacement ('C (confounded)')
        self.cmap({"A": "claude", "B": "gpt", "C": "kimi"})
        self.judge("claude", [cand("A", 3), cand("B", 5, veto=True), cand("C", 4)])
        self.judge("gpt", [cand("A", 3), cand("B", 5), cand("C", 4)])
        self.judge("kimi", [cand("A", 3), cand("B", 5), cand("C", 4)])
        m, _c, _md = self.matrix()
        self.assertEqual(m["leader"], "B")
        vals = gates.gate_values(self.ctx, "G11")
        self.assertTrue(vals["ARCH_SUGGESTION"].startswith("C (best-ranked without a veto); leader B was vetoed"),
                        vals["ARCH_SUGGESTION"])


if __name__ == "__main__":
    unittest.main()
