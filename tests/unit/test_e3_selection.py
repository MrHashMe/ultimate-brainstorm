"""Phase E3, selection and seats: the finalist cut fills with screened survivors before further evolved ideas
(finding 45), evolved ideas' origin by vendor (finding 51), a cross-host re-seat never seats the host's model twice
as a judge (finding 89), and tools/eval.py labels screen judges by who answered (finding 83)."""

import importlib.util
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fixtures", "engine"))
import engine_testlib as tl  # noqa: E402

from ublib.engine import gates, registry, seats  # noqa: E402

_EVAL = os.path.join(tl.KIT, "tools", "eval.py")
_spec = importlib.util.spec_from_file_location("ub_eval_e3", _EVAL)
ev = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ev)


class FinalistCutTests(tl.EngineTestCase):
    def test_evolve_shaped_parents_never_displace_screened_survivors(self):
        # finding 45 residual: EVOLVE's E-03 (a simpler top idea) and E-05 (another mechanism for its outcome) name
        # the top survivor as parent and inherit its score; the cut then took 4 survivors + 4 E ideas (three variants
        # of I-001) in deep mode and dropped the screen's best-of-cluster picks 5-8 without a gate
        ctx = self.make_ctx(mode="deep", run_name="2026-09-26-e3-evolve")
        rows = [{"id": "I-%03d" % n, "reason": "best of cluster", "score": round(4.5 - 0.1 * n, 3)}
                for n in range(1, 9)]
        ctx.write_json("screen/shortlist.json", {"shortlist": rows})
        ctx.write_json("origins.json", dict((r["id"], "claude") for r in rows))
        ctx.write_json("primary.json", [])
        parents = {1: "I-001, I-002", 2: "I-003", 3: "I-001", 4: "I-002, I-004", 5: "I-001"}
        blocks = []
        for k in range(1, 6):
            blocks.append("### E-%02d Evolved %d\n- Pitch: p\n- Mechanism: m\n- Fails if: f\n- Parents: %s\n"
                          % (k, k, parents[k]))
            ctx.write("checks/E-%02d.md" % k, "## 1\nx\nVERDICT: ADJACENT; DIFFERENTIATOR: a pilot\n")
        ctx.write("05_EVOLVED.md", "# EVOLVED\n\n" + "\n".join(blocks))
        registry.SCRIPTS["finalists"](ctx, {"id": "9.1"})
        fin = ctx.state["finalists"]
        self.assertEqual(len(fin), 8)
        self.assertEqual([i for i in fin if i.startswith("I-")], ["I-%03d" % n for n in range(1, 7)])
        self.assertEqual([i for i in fin if i.startswith("E-")], ["E-01", "E-02"])  # the quota of 2, by id on a tie


class EvolvedOriginTests(tl.EngineTestCase):
    def test_an_alt_writer_is_its_vendor(self):
        # finding 51 (3): writer claude-alt with a claude parent gave ai-mixed (nobody's), so the host's own-vendor
        # correction skipped it
        ctx = self.make_ctx(run_name="2026-09-26-e3-evo")
        ctx.write_json("origins.json", {"I-001": "claude", "I-002": "gpt", "I-003": "human"})
        body = "\n- Pitch: p\n- Mechanism: m\n- Fails if: f"
        ctx.write("05_EVOLVED.md", "### E-01 A%s\n- Parents: I-001\n\n### E-02 B%s\n- Parents: I-001, I-002\n\n"
                                   "### E-03 C%s\n- Parents: I-003\n" % (body, body, body))
        ctx.write_json("05_EVOLVED.md.meta.json", {"family": "claude-alt", "status": "ok"})
        registry.SCRIPTS["add_evolved"](ctx, {"id": "8.1"})
        org = ctx.read_json("origins.json", {})
        self.assertEqual((org["E-01"], org["E-02"], org["E-03"]), ("claude", "ai-mixed", "claude-alt"))

    def test_a_redo_of_evolve_replaces_the_old_e_origins(self):
        # round 3 (#51): 8.1 used setdefault, so a redone EVOLVE (same E ids, other ideas) kept the first run's
        # origins, and an E id the redo no longer wrote stayed in origins.json
        ctx = self.make_ctx(run_name="2026-09-27-e3-evo-redo")
        ctx.write_json("origins.json", {"I-001": "claude", "I-002": "gpt", "I-003": "gpt"})
        body = "\n- Pitch: p\n- Mechanism: m\n- Fails if: f"
        ctx.write("05_EVOLVED.md", "### E-01 A%s\n- Parents: I-001\n\n### E-02 B%s\n- Parents: I-001\n" % (body, body))
        ctx.write_json("05_EVOLVED.md.meta.json", {"family": "claude", "status": "ok"})
        registry.SCRIPTS["add_evolved"](ctx, {"id": "8.1"})
        self.assertEqual(ctx.read_json("origins.json", {})["E-01"], "claude")
        ctx.write("05_EVOLVED.md", "### E-01 C%s\n- Parents: I-002, I-003\n" % body)
        ctx.write_json("05_EVOLVED.md.meta.json", {"family": "gpt", "status": "ok"})
        registry.SCRIPTS["add_evolved"](ctx, {"id": "8.1"})
        org = ctx.read_json("origins.json", {})
        self.assertEqual(org["E-01"], "gpt")
        self.assertNotIn("E-02", org)
        self.assertEqual(org["I-001"], "claude")  # pool origins are kept


class G4AuditTests(tl.EngineTestCase):
    def test_the_card_shows_a_flagged_judge_and_an_uncorrectable_pair(self):
        # round 3 (#88): the own-origin FLAG and the pair WARN were only in 04_SHORTLIST.md, while the docs leave the
        # uncorrectable two-judge case to the human's G4 review
        ctx = self.make_ctx(run_name="2026-09-27-e3-g4")
        ctx.write_json("screen/shortlist.json", {"shortlist": [], "own_origin_gap": [
            {"judge": "claude", "gap": 0.8, "n": 4, "base": 3, "vs": ["gpt"], "flag": True},
            {"judge": "gpt", "gap": 0.1, "n": 4, "base": 3, "vs": ["claude"], "flag": False}],
            "own_origin_pairs": [{"a": "gpt", "b": "kimi", "gap": 0.9, "n_a": 3, "n_b": 3, "warn": True}]})
        summary = gates.gate_values(ctx, "G4")["SUMMARY"]
        self.assertIn("Judge self-preference", summary)
        self.assertIn("- claude: own-origin gap +0.80", summary)
        self.assertNotIn("- gpt: own-origin gap", summary)
        self.assertIn("- gpt and kimi together: +0.90", summary)

    def test_no_audit_section_without_a_flag_or_warn(self):
        ctx = self.make_ctx(run_name="2026-09-27-e3-g4-quiet")
        ctx.write_json("screen/shortlist.json", {"shortlist": [], "own_origin_gap": [
            {"judge": "claude", "gap": 0.2, "n": 4, "base": 3, "vs": ["gpt"], "flag": False}],
            "own_origin_pairs": [{"a": "gpt", "b": "kimi", "gap": "x", "warn": True}]})
        self.assertNotIn("Judge self-preference", gates.gate_values(ctx, "G4")["SUMMARY"])


class ReseatTests(unittest.TestCase):
    def test_a_lost_judge_is_dropped_not_replaced_by_the_same_model(self):
        # finding 89 residual: a gpt-hosted gpt + claude run continues where claude is gone; gpt's alt_model is null,
        # so the fresh seating has one judge, but reseat_minimal put gpt-alt in claude's judge seats
        old = seats.assign("r", "gpt", ["gpt", "claude"], {}, "standard", alt_distinct=False)
        self.assertEqual(old["tournament_judges"], ["gpt", "claude"])
        fresh = seats.assign("r", "gpt", ["gpt"], {}, "standard", alt_distinct=False)
        new, changes = seats.reseat_minimal(old, fresh, ["gpt"], "gpt")
        self.assertEqual((new["screen_judges"], new["tournament_judges"]), (["gpt"], ["gpt"]))
        self.assertIn(("tournament_judges", "claude", "(dropped)"), changes)
        # an alt model that is another model (claude-alt = sonnet) is a real second judge: seated as fresh seats it
        old = seats.assign("r", "claude", ["claude", "gpt"], {}, "standard")
        fresh = seats.assign("r", "claude", ["claude"], {}, "standard", alt_distinct=True)
        new, _changes = seats.reseat_minimal(old, fresh, ["claude"], "claude")
        self.assertEqual(new["tournament_judges"], ["claude", "claude-alt"])


class EvalScreenJudgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ub-e3-eval-")
        self.run = os.path.join(self.tmp, "brainstorm", "2026-09-26-e3-eval")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def w(self, rel, obj):
        p = os.path.join(self.run, *rel.split("/"))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8", newline="\n") as f:
            f.write(obj if isinstance(obj, str) else json.dumps(obj))

    def test_a_fallback_copy_counts_as_the_family_that_answered(self):
        # finding 83: eval.py named screen judges by file name, so gpt.out.json answered by claude (fallback) was a
        # separate judge and Kendall's W measured claude's agreement with itself
        self.w("run.json", {"schema": 2, "mode": "standard", "seats": {"screen_judges": ["claude", "gpt"]}})
        self.w("criteria.json", {"Value": 60, "Feasibility": 40})
        self.w("screen/ideas.md", "I-001 | a | p | m\nI-002 | b | p | m\nI-003 | c | p | m\n")
        rows = [{"id": i, "c": {"Value": v, "Feasibility": v}} for i, v in (("I-001", 5), ("I-002", 3), ("I-003", 1))]
        for seat in ("claude", "gpt"):
            self.w("screen/%s.out.json" % seat, {"scores": rows})
            self.w("screen/%s.out.json.meta.json" % seat, {"family": "claude", "status": "ok"})
        self.assertEqual(sorted(ev.screen_rankings(self.run)), ["claude"])
        self.assertIsNone(ev.one_run(self.run)["kendall_w"]["screen"])  # one judge: no agreement to measure


if __name__ == "__main__":
    unittest.main()
