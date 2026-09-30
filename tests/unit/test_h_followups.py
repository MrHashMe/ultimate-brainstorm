"""Phase H follow-ups that crossed package lines: every arch judge scores every criterion of every candidate (a
nested cover; F46), an older kit's judge list made only of the host and <host>-alt is one judge (F89), and the red
team's kill assumptions ignore fenced examples (F41)."""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fixtures", "engine"))
import engine_testlib as tl  # noqa: E402

from ublib import validate  # noqa: E402
from ublib.engine import migrate, registry  # noqa: E402


def judge_output(scores_a, scores_b):
    def cand(label, scores):
        return {"label": label, "veto": False, "veto_reason": "",
                "scores": [{"criterion": c, "score": 3, "reason": "r"} for c in scores],
                "sensitivity_points": [], "tradeoff_points": [], "risks": [], "non_risks": []}
    return {"candidates": [cand("A", scores_a), cand("B", scores_b)], "steal": []}


class NestedCoverTests(unittest.TestCase):
    COVER = {"array": "candidates", "key": "label", "ids": ["A", "B"],
             "each": {"array": "scores", "key": "criterion", "ids": ["QG1", "time_to_mvp"], "loose": True}}

    def test_a_criterion_left_out_of_one_candidate_is_an_error(self):
        # F46: a judge that omitted a candidate's weak criterion removed that criterion from W for everyone
        errors = validate._check_cover(judge_output(["QG1", "time_to_mvp"], ["QG1"]), self.COVER)
        self.assertEqual(errors, ["cover: candidates[B].scores is missing criterion time_to_mvp"])

    def test_repeated_and_unknown_criteria_are_errors(self):
        errors = validate._check_cover(judge_output(["QG1", "QG1", "time_to_mvp"], ["QG1", "time_to_mvp", "QG9"]),
                                       self.COVER)
        self.assertEqual(len(errors), 2, errors)
        self.assertIn("candidates[A].scores lists criterion QG1 more than once", errors[0])
        self.assertIn("candidates[B].scores has unknown criterion QG9", errors[1])

    def test_a_criterion_name_is_rewritten_to_its_id(self):
        value = judge_output(["qg1", "Time to MVP"], ["QG1", "time-to-mvp"])
        self.assertEqual(validate._check_cover(value, self.COVER), [])
        self.assertEqual([s["criterion"] for c in value["candidates"] for s in c["scores"]],
                         ["QG1", "time_to_mvp", "QG1", "time_to_mvp"])

    def test_the_outer_cover_stays_exact(self):
        cover = dict(self.COVER, each=None)
        self.assertEqual(validate._check_cover(judge_output(["x"], ["y"]), cover), [])
        self.assertEqual(validate._check_cover({"candidates": [{"label": "a"}, {"label": "B"}]},
                                               {"array": "candidates", "key": "label", "ids": ["A", "B"]}),
                         ["cover: candidates is missing label A", "cover: candidates has unknown label a (only the "
                                                                  "listed ones)"])

    def test_the_arch_judge_contract_carries_it(self):
        case = tl.EngineTestCase("run")
        case.setUp()
        try:
            ctx = case.make_ctx(run_name="2026-09-27-h-cover")
            ctx.write_json("10_ARCHITECTURE/candidates/map.json", {"A": {"n": 1}, "B": {"n": 2}})
            it = registry.FANOUTS["arch_judges"](ctx, {"id": "12.7"})[0]
            each = it["contract"]["cover"]["each"]
            self.assertEqual((each["array"], each["key"], each["ids"]), ("scores", "criterion",
                                                                          registry.arch_criteria(ctx)))
        finally:
            case.tearDown()


class HostAltJudgeListTests(unittest.TestCase):
    def test_any_list_of_the_host_model_is_one_judge(self):
        # F89: a cross-host continue of an older kit could seat [host, host-alt, host-alt]
        state = {"host": {"family": "gpt"}, "seats": {"host": "gpt", "screen_judges": ["gpt", "gpt-alt", "gpt-alt"],
                                                       "tournament_judges": ["gpt-alt", "gpt"]}}
        self.assertEqual(migrate.upgrade(state, alt_distinct=False), ["screen_judges", "tournament_judges"])
        self.assertEqual((state["seats"]["screen_judges"], state["seats"]["tournament_judges"]), (["gpt"], ["gpt"]))

    def test_other_lists_are_left_alone(self):
        seats = {"host": "gpt", "screen_judges": ["gpt", "gpt-alt", "claude"], "tournament_judges": ["gpt"]}
        state = {"host": {"family": "gpt"}, "seats": dict(seats)}
        self.assertEqual(migrate.upgrade(state, alt_distinct=False), [])
        self.assertEqual(migrate.upgrade(dict(state, seats=dict(seats, screen_judges=["gpt", "gpt-alt"])),
                                         alt_distinct=True), [])  # another model: two judges


class KillAssumptionFenceTests(tl.EngineTestCase):
    def test_a_fenced_idea_heading_does_not_end_the_chosen_ideas_kills(self):
        ctx = self.make_ctx()
        ctx.state["choice"]["idea"] = "I-001"
        ctx.write("07_REDTEAM.md", "# Red team\n\n## 1. Per idea\n\n### I-001\nExample:\n```md\n### I-002\n"
                                   "- Fails if: quoted\n```\n- Fails if: nurses keep swapping by text\n\n### I-002\n"
                                   "- Fails if: other idea\n\n## 2. Decision brief\npick I-001\n")
        self.assertEqual(registry._ph_kill_assumptions(ctx, {}),
                         "From the red-team:\n- Fails if: nurses keep swapping by text")


if __name__ == "__main__":
    unittest.main()
