"""Phase H (HC-ranking-seats), seat assignment (KIT_SPEC 6.6, 6.10).

- Finding 89: a cross-host continue on which none of the old judge families is available seated the new host's model
  several times as a screen and tournament judge ([host, host-alt, host-alt] with alt_model null). A lost judge seat
  with no new family to take it is dropped once the stage has a judge, and `<host>-alt` is seated at most once, and
  only when the fresh seating seats it.
- Finding 51 (3): quick mode with 3 or more families seats the third family, which generates nothing, as a neutral
  third judge of the blind quick screen (Q.3s), so each generator family's own-origin gap can be measured and taken
  off (one more call).
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fixtures", "engine"))
import engine_testlib as tl  # noqa: E402

import ub  # noqa: E402
from ublib.engine import pipeline, seats  # noqa: E402

JUDGES = ("screen_judges", "tournament_judges")


def reseat(old_host, old_fams, new_host, available, mode="standard", new_alt=False):
    old = seats.assign("r", old_host, list(old_fams), {}, mode, alt_distinct=True)
    fresh = seats.assign("r", new_host, list(available), {}, mode, alt_distinct=new_alt)
    new, changes = seats.reseat_minimal(old, fresh, list(available), new_host)
    return old, fresh, new, changes


class ReseatJudgeTests(unittest.TestCase):
    def assert_judges(self, new, want):
        for key in JUDGES:
            self.assertEqual(new[key], want, key)

    def test_three_lost_judges_leave_one_judge_not_the_same_model_three_times(self):
        old, fresh, new, changes = reseat("claude", ("claude", "kimi", "glm"), "gpt", ("gpt",))
        self.assertEqual(old["tournament_judges"], ["claude", "kimi", "glm"])
        self.assertEqual(fresh["tournament_judges"], ["gpt"])
        self.assert_judges(new, ["gpt"])
        for key in JUDGES:
            self.assertIn((key, "claude", "gpt"), changes)
            self.assertIn((key, "kimi", "(dropped)"), changes)
            self.assertIn((key, "glm", "(dropped)"), changes)

    def test_two_lost_judges(self):
        _old, _fresh, new, _changes = reseat("claude", ("claude", "gpt"), "kimi", ("kimi",))
        self.assert_judges(new, ["kimi"])

    def test_deep_mode(self):
        _old, _fresh, new, _changes = reseat("claude", ("claude", "gpt", "kimi"), "glm", ("glm",), mode="deep")
        self.assert_judges(new, ["glm"])

    def test_a_one_family_run_moved_to_another_family(self):
        old, _fresh, new, _changes = reseat("claude", ("claude",), "gpt", ("gpt",))
        self.assertEqual(old["tournament_judges"], ["claude", "claude-alt"])
        self.assert_judges(new, ["gpt"])

    def test_a_distinct_alt_model_is_seated_once(self):
        # claude-alt runs another model (sonnet): it is a real second judge, as the fresh seating has it, but once
        _old, fresh, new, _changes = reseat("gpt", ("gpt", "kimi", "glm"), "claude", ("claude",), new_alt=True)
        self.assertEqual(fresh["tournament_judges"], ["claude", "claude-alt"])
        self.assert_judges(new, ["claude", "claude-alt"])

    def test_a_kept_judge_after_a_lost_one(self):
        _old, _fresh, new, changes = reseat("claude", ("claude", "gpt"), "gpt", ("gpt",))
        self.assert_judges(new, ["gpt"])
        self.assertIn(("tournament_judges", "claude", "(dropped)"), changes)


class QuickScreenSeatTests(tl.EngineTestCase):
    def test_a_third_family_judges_the_quick_screen(self):
        for fams, want in ((("claude", "gpt", "kimi"), ["claude", "gpt", "kimi"]),
                           (("claude", "gpt", "kimi", "glm"), ["claude", "gpt", "kimi"]),
                           (("claude", "gpt"), ["claude", "gpt"]),
                           (("claude",), ["claude-alt"])):
            s = seats.assign("r", "claude", list(fams), {}, "quick")
            self.assertEqual(s["screen_judges"], want, fams)
            self.assertEqual(s["tournament_judges"], [fams[1] if len(fams) > 1 else "claude-alt"])
            self.assertEqual(seats.quick_screen_ok(s), len(fams) > 1)

    def test_the_third_judge_generated_nothing_and_adds_one_call(self):
        ctx = self.make_ctx(mode="quick", families=("claude", "gpt", "kimi"), run_name="2026-09-27-h-quick3")
        gen = pipeline.plan_families(ctx, {"id": "Q.2", "fanout": "quick_gen"}, 2)
        self.assertEqual(sorted(gen), ["claude", "gpt"])
        self.assertNotIn("kimi", gen)
        self.assertEqual(pipeline.plan_families(ctx, {"id": "Q.3s", "fanout": "screen_judges"}, 3),
                         {"claude": 1, "gpt": 1, "kimi": 1})
        three = ub.cmd_plan(ub.build_parser().parse_args(["plan", "--mode", "quick", "--families", "claude,gpt,kimi"]))
        two = ub.cmd_plan(ub.build_parser().parse_args(["plan", "--mode", "quick", "--families", "claude,gpt"]))
        self.assertEqual((three["calls"]["expected"], two["calls"]["expected"]), (16, 15))


if __name__ == "__main__":
    unittest.main()
