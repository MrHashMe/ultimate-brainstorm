"""Engine selection and ranking consumers (KIT_SPEC 5.7, 6.2, 6.4, 6.6): the finalist pool and cut (evolved ideas
inherit their parents' screen score, E quota, cap 8), the tournament ranking read by 07_TOP, G7/G8b and the
suggestion (never 0 for missing evidence, raw fallback shown, Condorcet winner), judge fallbacks, seat rotation,
single-model judge seats, and the removed deep-mode dupcheck loop."""

import contextlib
import io
import json
import os
import re
import subprocess
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fixtures", "engine"))
import engine_testlib as tl  # noqa: E402

import bs  # noqa: E402
from ublib.engine import gates, pipeline, registry, seats  # noqa: E402

VERDICTS = {1: "CROWDED", 2: "NOT LOCATED", 3: "ADJACENT", 4: "NOT CHECKED", 5: "NOT LOCATED"}
PARENTS = {1: "I-001, I-002", 2: "I-005, I-006", 3: "I-001", 4: "I-006", 5: ""}


def quiet(fn, *args, **kw):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        fn(*args, **kw)
    return buf.getvalue()


class FinalistTests(tl.EngineTestCase):
    def pool(self, mode, n_surv, n_e, tail=None, human=None, primary=None):
        """Survivors I-001.. scored 4.4, 4.3, ...; E-01.. with checks (VERDICTS) and parents (PARENTS)."""
        ctx = self.make_ctx(mode=mode, run_name="2026-09-26-fin-%s-%d-%d" % (mode, n_surv, n_e))
        rows = []
        for n in range(1, n_surv + 1):
            iid = "I-%03d" % n
            rows.append({"id": iid, "reason": "best of cluster" + (" + tail slot" if iid == tail else ""),
                         "score": round(4.5 - 0.1 * n, 3)})
        ctx.write_json("screen/shortlist.json", {"shortlist": rows})
        ctx.write_json("origins.json", dict((r["id"], "human" if r["id"] == human else "claude") for r in rows))
        ctx.write_json("primary.json", [primary] if primary else [])
        blocks = []
        for k in range(1, n_e + 1):
            blocks.append("### E-%02d Evolved %d\n- Pitch: p\n- Mechanism: m\n- Fails if: f\n- Parents: %s\n" % (k, k, PARENTS[k]))
            ctx.write("checks/E-%02d.md" % k, "## 1\nx\nVERDICT: %s; DIFFERENTIATOR: a pilot\n" % VERDICTS[k])
        ctx.write("05_EVOLVED.md", "# EVOLVED\n\n" + "\n".join(blocks))
        return ctx

    def finalists(self, ctx):
        registry.SCRIPTS["finalists"](ctx, {"id": "9.1"})
        return ctx.state["finalists"]

    def test_deep_six_survivors_and_five_evolved(self):
        # finding 45: E ideas scored 0 and were all cut (finalists I-001..I-006); now the quota keeps 2 of them (both
        # NOT LOCATED) and the screened survivors fill the rest before any further E idea
        ctx = self.pool("deep", 6, 5)
        self.assertTrue(registry.PREDICATES["more_than_8"](ctx, None))  # 11 in the pool: G6 can see the cut
        self.assertEqual(self.finalists(ctx), ["I-001", "I-002", "I-003", "I-004", "I-005", "I-006", "E-02", "E-05"])
        scores = registry.screen_scores(ctx)
        self.assertAlmostEqual(scores["E-01"], 4.35)   # mean of its parents I-001 and I-002
        self.assertAlmostEqual(scores["E-05"], 3.9)    # no parent: the lowest survivor score

    def test_deep_eight_survivors_and_five_evolved(self):
        # survivors 7-8 were cut although 8 survivors alone all qualify; now the protected tail (I-008) and human
        # (I-007) slots stay, the E quota takes 2 NOT LOCATED ideas and the best survivors fill the rest
        ctx = self.pool("deep", 8, 5, tail="I-008", human="I-007")
        self.assertEqual(self.finalists(ctx), ["I-001", "I-002", "I-003", "I-004", "I-007", "I-008", "E-02", "E-05"])

    def test_standard_five_survivors_and_four_evolved(self):
        # only E-01 survived before, chosen by id; now the quota orders by CHECK verdict (E-02 NOT LOCATED,
        # E-03 ADJACENT) and E-01 (parents' 4.35) wins a slot on its inherited score
        ctx = self.pool("standard", 5, 4)
        self.assertEqual(self.finalists(ctx), ["I-001", "I-002", "I-003", "I-004", "I-005", "E-01", "E-02", "E-03"])

    def test_cap_is_eight(self):
        # 6 by score + tail + human + primary reached 9
        ctx = self.pool("standard", 10, 0, tail="I-010", human="I-009", primary="I-008")
        fin = self.finalists(ctx)
        self.assertEqual(len(fin), 8)
        self.assertTrue(set(["I-008", "I-009", "I-010"]) <= set(fin))

    def test_small_pool_is_kept_whole(self):
        ctx = self.pool("standard", 3, 4)
        self.assertEqual(self.finalists(ctx), ["I-001", "I-002", "I-003", "E-01", "E-02", "E-03", "E-04"])
        self.assertFalse(registry.PREDICATES["more_than_8"](ctx, None))

    def test_evolved_origin_follows_lineage(self):
        # finding 51: every E idea was ai-mixed (nobody's own), so the host that wrote it judged it unchecked
        ctx = self.make_ctx(run_name="2026-09-26-evo-origin")
        ctx.write_json("origins.json", {"I-001": "gpt", "I-002": "claude", "I-003": "human"})
        body = "\n- Pitch: p\n- Mechanism: m\n- Fails if: f"
        ctx.write("05_EVOLVED.md", "### E-01 Hybrid%s\n- Parents: I-001, I-002\n\n### E-02 Simpler%s\n- Parents: I-002\n\n"
                                   "### E-03 Contrast%s\n- Parents: I-003\n" % (body, body, body))
        ctx.write_json("05_EVOLVED.md.meta.json", {"family": "claude", "status": "ok"})
        registry.SCRIPTS["add_evolved"](ctx, {"id": "8.1"})
        org = ctx.read_json("origins.json", {})
        self.assertEqual((org["E-01"], org["E-02"], org["E-03"]), ("ai-mixed", "claude", "claude"))

    def test_g6_lists_the_whole_pool(self):
        ctx = self.pool("deep", 6, 5)
        vals = gates.gate_values(ctx, "G6")
        self.assertIn("- E-01 ", vals["SURVIVORS_LIST"])
        self.assertIn("from its parents; check CROWDED", vals["SURVIVORS_LIST"])
        self.assertEqual(vals["SURVIVORS_LIST"].count("\n") + 1, 11)


class RankingConsumerTests(tl.EngineTestCase):
    def tally(self, ctx, judges, ids, origins, decide):
        """The real bs.py prepare-tournament + tournament in the ctx's run folder."""
        ctx.write_json("run.json", {"schema": 2, "run": ctx.state["run"], "mode": ctx.mode,
                                    "seats": {"tournament_judges": judges}})
        ctx.write("tournament/cards.md", "".join("## %s\nTitle: %s\n\n" % (i, i) for i in ids))
        ctx.write("tournament/header.md", "H\n")
        ctx.write_json("origins.json", origins)
        quiet(bs.prepare_tournament, ctx.run_dir)
        for name in sorted(os.listdir(ctx.path("tournament"))):
            if name.endswith(".map.json"):
                m = ctx.read_json("tournament/" + name, {})
                ctx.write_json("tournament/" + name.replace(".map.json", ".out.json"), {"verdicts": [
                    {"pair_id": pid, "winner": decide(m["order"], p["first"], p["second"])}
                    for pid, p in m["pairs"].items()]})
        quiet(bs.tournament, ctx.run_dir)

    def test_every_judge_flagged_suggests_the_raw_leader(self):
        # finding 47: quick mode, one position-biased judge; every % read as 0 and the suggestion was Q-01 (id order)
        ctx = self.make_ctx(mode="quick", autopilot="full-auto", run_name="2026-09-26-allflag")
        ids = ["Q-01", "Q-02", "Q-03"]

        def decide(order, a, b):
            if set((a, b)) == set(("Q-02", "Q-03")):
                return "FIRST" if a == "Q-03" else "SECOND"
            return "FIRST"
        self.tally(ctx, ["gpt"], ids, dict((i, "claude") for i in ids), decide)
        ctx.state["finalists"] = ctx.state["top"] = ids
        best, rule = registry.suggestion(ctx)
        self.assertEqual(best, "Q-03")
        self.assertIn("ranking fell back to raw points: every judge family is flagged", rule)
        self.assertEqual(registry.debiased_pct(ctx), {"Q-03": 75.0, "Q-01": 50.0, "Q-02": 25.0})
        standings = gates.gate_values(ctx, "G8b")["STANDINGS"]
        self.assertTrue(standings.startswith("Note: the ranking fell back to raw points"))
        self.assertIn("1. Q-03", standings)
        # full-auto: the AUTO-DECISION takes the raw leader and records the rule with the fallback reason
        gates.apply(ctx, "G8b", gates.merge_answer("G8b", gates.default_answer("G8b"), ctx), by="auto")
        self.assertEqual(ctx.state["choice"], dict(ctx.state["choice"], idea="Q-03", runner_up="Q-01"))
        registry.SCRIPTS["quick_decision"](ctx, {"id": "Q.8"})
        self.assertIn("AUTO-DECISION: chosen by rule (0 BACK/BACK IF verdicts, tournament score 75% (rank 1); "
                      "ranking fell back to raw points", ctx.read("QUICK_DECISION.md"))

    def test_top_takes_the_pair_level_order_and_the_condorcet_winner(self):
        ctx = self.make_ctx(run_name="2026-09-26-top")
        fin = ["I-001", "I-002", "I-003", "I-004", "I-005"]
        ctx.state["finalists"] = fin
        rows = [{"id": i, "pct": p, "n": 4, "rank": n + 1, "ci": None, "rank_range": None}
                for n, (i, p) in enumerate([("I-002", 70.0), ("I-003", 60.0), ("I-004", 55.0), ("I-001", 50.0),
                                            ("I-005", 10.0)])]
        ctx.write_json("tournament/result.json", {"debiased": rows, "raw": [],
                                                  "ranking": {"method": "bradley-terry"},
                                                  "condorcet": {"winner": "I-001", "cycles": []}})
        registry.SCRIPTS["top"](ctx, {"id": "10.1"})
        self.assertEqual(ctx.state["top"], ["I-002", "I-003", "I-004", "I-001"])
        ctx.state.setdefault("gates", {})["G8a"] = {"answer": {"picks": ["I-005"]}}
        registry.SCRIPTS["top"](ctx, {"id": "10.1"})
        self.assertEqual(ctx.state["top"], ["I-002", "I-003", "I-001", "I-005"])  # at most 4

    def test_older_result_never_reads_missing_as_zero(self):
        # finding 47 (S5): pct None for every card read as 0%, so the top 3 came from id order (I-004 was last on raw)
        ctx = self.make_ctx(run_name="2026-09-26-older")
        fin = ["I-004", "I-017", "I-031", "I-052"]
        ctx.state["finalists"] = fin
        ctx.write_json("tournament/result.json", {
            "debiased": [{"id": i, "pct": None, "n": 0} for i in fin],
            "raw": [{"id": "I-017", "points": 6.0, "max": 9}, {"id": "I-031", "points": 4.5, "max": 9},
                    {"id": "I-052", "points": 4.5, "max": 9}, {"id": "I-004", "points": 3.0, "max": 9}]})
        registry.SCRIPTS["top"](ctx, {"id": "10.1"})
        self.assertEqual(ctx.state["top"], ["I-017", "I-031", "I-052"])
        self.assertIn("raw tournament points", ctx.read("07_TOP.md"))


class SeatTests(tl.EngineTestCase):
    def test_judge_fallback_prefers_a_family_that_does_not_judge(self):
        # finding 50: a failed judge seat fell back to the host, which already judges
        ctx = self.make_ctx(run_name="2026-09-26-fb")
        ctx.write("screen/ideas.md", "I-001 | a | b | c\n")
        items = dict((i["family"], i) for i in registry.FANOUTS["screen_judges"](ctx, {"id": "6.2"}))
        self.assertEqual(sorted(items), ["claude", "gpt", "kimi"])
        self.assertEqual(items["gpt"]["fallback"], ["gpt-alt", "glm", "claude"])
        self.assertEqual(items["claude"]["fallback"], ["claude-alt", "glm"])

    def test_generators_rotate_across_runs(self):
        # finding 83: S3 always ran on the first non-host family, so its yield measured that family
        seen = set()
        for n in range(12):
            s = seats.assign("2026-09-26-r%d" % n, "claude", ["claude", "gpt", "kimi"], {"claude": True},
                             "standard")
            self.assertEqual((s["generators"]["S1"], s["generators"]["S2"]), ("claude", "claude"))
            self.assertIn(s["rotation"], (0, 1))
            self.assertNotEqual(s["generators"]["S3"], s["generators"]["S5"])
            self.assertEqual(seats.reopen_families(s, "standard"), [["gpt", "kimi"][s["rotation"]]])
            seen.add(s["generators"]["S3"])
        self.assertEqual(seen, {"gpt", "kimi"})
        a = seats.assign("same-run", "claude", ["claude", "gpt", "kimi"], {}, "deep")
        self.assertEqual(a, seats.assign("same-run", "claude", ["claude", "gpt", "kimi"], {}, "deep"))

    def test_same_model_alt_seat_is_not_a_second_judge(self):
        # finding 89: gpt, kimi and glm have alt_model null, so <host>-alt would run the host's model again
        s = seats.assign("r", "gpt", ["gpt"], {}, "standard", alt_distinct=False)
        self.assertEqual(s["screen_judges"], ["gpt"])
        self.assertEqual(s["tournament_judges"], ["gpt"])
        self.assertEqual(s["redteam_rotation"], ["gpt", "gpt-alt"])  # advocate and critic still differ
        cfg = {"families": {"gpt": {"alt_model": None}, "claude": {"alt_model": "sonnet"}}}
        ctx = self.make_ctx(host="gpt", families=("gpt",), deps=tl.FakeDeps(cfg=cfg), run_name="2026-09-26-alt")
        self.assertEqual(ctx.state["seats"]["tournament_judges"], ["gpt"])
        ctx = self.make_ctx(host="claude", families=("claude",), deps=tl.FakeDeps(cfg=cfg), run_name="r2")
        self.assertEqual(ctx.state["seats"]["tournament_judges"], ["claude", "claude-alt"])

    def test_judges_line_tags_the_substituted_seat(self):
        ctx = self.make_ctx(run_name="2026-09-26-jl")
        ctx.state["provisional"] = [{"stage": "Tournament judges", "seat": "gpt", "actual": "claude"}]
        self.assertEqual(registry.judges_line(ctx, "tournament_judges"), "claude, gpt (PROVISIONAL: claude), kimi")
        self.assertEqual(registry.judges_line(ctx, "screen_judges"), "claude, gpt, kimi")


class RemovedLoopTests(tl.EngineTestCase):
    def test_no_deep_dupcheck_loop(self):
        # finding 53: the curator never saw the I-### pairs, so pass 2 was a blind re-curation
        ids = [s["id"] for s in pipeline.load_steps()]
        self.assertNotIn("5.2d", ids)
        self.assertNotIn("5.2m", ids)
        self.assertNotIn("DUPCHECK_PAIRS", registry.PLACEHOLDERS)
        self.assertNotIn("DUP_PAIRS", registry.PLACEHOLDERS)
        self.assertNotIn("curator_single", registry.FANOUTS)
        ctx = self.make_ctx(mode="deep", run_name="2026-09-26-deep")
        self.assertEqual(registry.FANOUTS["curator"](ctx, {"id": "5.3c"})[0]["vars"], {})
        p = subprocess.run([sys.executable, tl.os.path.join(tl.SCRIPTS, "bs.py"), "dupcheck", ctx.run_dir],
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.assertEqual(p.returncode, 2)
        self.assertNotIn("DUPCHECK", tl.textio.read_text(os.path.join(tl.TEMPLATES, "prompts", "CURATOR.md")))

    def test_gap_round_follows_bs_coverage(self):
        # finding 54: any empty cell fired the gap round; bs.py now decides (homogenized or under 80% covered)
        ctx = self.make_ctx(run_name="2026-09-26-gap")
        ctx.write_json("coverage.json", {"homogenized": False, "empty": [["a", "x"]], "gap_needed": False})
        self.assertFalse(registry.eval_when(ctx, ["homogenized_or_gaps"]))
        ctx.write_json("coverage.json", {"homogenized": False, "empty": [], "gap_needed": True})
        self.assertTrue(registry.eval_when(ctx, ["homogenized_or_gaps"]))

    def test_reviewer_verdict_needs_no_confidence(self):
        # finding 90: the suffix was required and never read; older outputs with it still validate
        rx = registry.tcontract("REVIEWER")["final_line"]
        for line in ("VERDICT: BACK", "VERDICT: DON'T BACK", "VERDICT: BACK IF two wards agree",
                     "VERDICT: BACK; confidence 0.7"):
            self.assertTrue(re.search(rx, line), line)
        self.assertNotIn("confidence", tl.textio.read_text(os.path.join(tl.TEMPLATES, "prompts", "REVIEWER.md")))
        self.assertEqual(json.loads(json.dumps(registry.REVIEW_FINAL)), rx)


if __name__ == "__main__":
    unittest.main()
