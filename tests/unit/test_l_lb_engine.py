"""Phase L (LB-engine-registry-render), the round-5 findings on the engine's registry, render and pipeline code
(KIT_SPEC 4.2, 6.3, 6.10, 7.2, 8.2).

- a run kit 2.0.3 started recorded its K6 kills and switches only as lines of 08_DECISION.md (no run.json
  decision_log, a probe record without `idea`): they seed decision_log when the run loads, so such a dead run reads
  KILLED (K6), and neither `switch --idea`, a MISSED nor a G13 `runner-up` takes a killed idea back
- a redo from 5.3c or 5.3m does not count again a gap round an older kit counted (no counters.gap_counted)
- 0.3 keeps a seeds file of the user's own that is not in the v1 form (an idea list, free text, '###' headings)
- after a K6 kill with no runner-up, the handoff seed and the published docs copy say so too (14.3 renders again),
  and the DONE card's proposal status reads KILLED (K6)
- PROPOSAL.md Appendix C of a matrix with every candidate EXCLUDED names no leader and no rank
- 2.2 drops a criteria.json value that is not a number and counts a negative weight as 0
"""

import io
import json
import os
import subprocess
import sys
import unittest
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fixtures", "engine"))
import engine_testlib as tl  # noqa: E402

from ublib import schema_lite, textio, validate  # noqa: E402
from ublib.engine import EngineError, gates, handoff, migrate, pipeline, registry, render  # noqa: E402
from ublib.engine import state as st  # noqa: E402

sys.path.insert(0, tl.SCRIPTS)
import ub  # noqa: E402
import test_j2_engine_cli as j2  # noqa: E402  (the every-candidate-EXCLUDED matrix)

IDEAS = "".join("I-%03d | Idea %d | pitch %d | mech %d\n" % (i, i, i, i) for i in range(1, 6))
K6 = "Killed: %s - K6 (the pre-registered probe missed)"
SWITCHED = "Switched (2026-09-02T09:00:00Z): chosen idea %s -> %s (the user asked to switch)"
# 08_DECISION.md as kit 2.0.3's write_decision left it (a K4 line is not a K6 kill)
DECISION_203 = ("# DECISION\n\nChosen: I-001 Idea 1\nRunner-up: none\nKilled: I-005 - K4 confirmed by the user\n\n"
                "LEDGER rows:\n\n| 2026-09-01 | run | I-001 | Idea 1 | chosen | decision | - |\n")


class Base(tl.EngineTestCase):
    def run_ub(self, *args, **kw):
        out = io.StringIO()
        with mock.patch.object(sys, "stdout", out):
            rc = ub.main([str(a) for a in args], deps=kw.get("deps") or tl.FakeDeps(detect=tl.fake_detect()))
        text = out.getvalue()
        return rc, (json.loads(text) if text.strip().startswith("{") else text)

    def reload(self, ctx):
        return st.Ctx(ctx.run_dir, st.load(ctx.run_dir), ctx.deps)


# ------------------------------------------------------------------------------------------------ 2.0.3 K6 records

class Upgraded203(Base):
    def run_203(self, chosen, runner_up, lines):
        """A finished run kit 2.0.3 left: its gates.probe_result appended each K6 kill (and its switch_idea each
        switch) to 08_DECISION.md only, and stored run.json probe as {result, at}."""
        ctx = self.make_ctx(run_name="2026-09-01-l-203")
        ctx.write("screen/ideas.md", IDEAS)
        ctx.state.update({"kit_version": "2.0.3", "status": "done", "signed_off": True,
                          "finalists": ["I-001", "I-002", "I-003", "I-004"],
                          "probe": {"result": "MISSED", "at": "2026-09-01T10:00:00Z"}})
        ctx.state["choice"].update({"idea": chosen, "runner_up": runner_up})
        self.assertNotIn("decision_log", ctx.state)
        text = DECISION_203
        for line in lines:
            text = text.rstrip() + "\n%s\n" % line
        ctx.write("08_DECISION.md", text)
        ctx.write("09_PROBE.md", "# Probe\n\n## 3. The probe\nAsk 10 nurses.\n\n## Result\n1 of 10\n"
                                 "RESULT: MISSED (K6)\n")
        ctx.write("11_PROPOSAL/PROPOSAL.md", "# Proposal\n\nStatus: APPROVED\n")
        st.save(ctx.run_dir, ctx.state)
        return self.reload(ctx)

    def dead(self):
        """I-001's probe missed (its runner-up I-002 took over), then I-002's missed with no runner-up left: 2.0.3
        kept I-002 as the decision."""
        return self.run_203("I-002", None, [K6 % "I-001", K6 % "I-002"])

    def test_the_record_seeds_decision_log_once(self):
        ctx = self.dead()
        self.assertEqual(ctx.state["decision_log"], [K6 % "I-001", K6 % "I-002"])
        self.assertEqual(ctx.state["probe"]["idea"], "I-002")  # the last kill is the probe the record holds
        self.assertEqual(registry.k6_killed(ctx.state), {"I-001", "I-002"})
        # the next locked save keeps it, and a load after that seeds nothing again
        st.save(ctx.run_dir, ctx.state)
        ctx.write("08_DECISION.md", ctx.read("08_DECISION.md") + "\n%s\n" % (K6 % "I-003"))
        self.assertEqual(self.reload(ctx).state["decision_log"], [K6 % "I-001", K6 % "I-002"])

    def test_a_dead_2_0_3_run_reads_killed(self):
        # probe-result MISSED item and bullet 1: the DONE card advised running the probe of the killed idea again
        ctx = self.dead()
        self.assertTrue(render.k6_dead(ctx.state))
        self.assertEqual(render.status_banner(ctx), render.KILLED_BANNER)
        show = pipeline.done_card(ctx)["show"]
        self.assertIn("Decision: I-002 Idea 2 - killed by its probe (K6); no runner-up is left", show)
        self.assertIn("Next: choose another finalist (I-003, I-004)", show)
        self.assertIn("11_PROPOSAL/PROPOSAL.md (KILLED (K6))", show)
        self.assertNotIn("Next: run the probe", show)

    def test_switch_refuses_an_idea_2_0_3_killed(self):
        ctx = self.dead()
        before = textio.read_bytes(os.path.join(ctx.run_dir, "run.json"))
        for extra in ([], ["--yes"]):
            rc, card = self.run_ub("switch", ctx.run_dir, "--idea", "I-001", *(extra + ["--json"]))
            self.assertEqual((rc, card.get("type")), (0, "BLOCKED"), card)
            self.assertEqual(card["say"], "I-001 was killed by its probe (K6); choose another finalist (I-003, I-004)")
        self.assertEqual(textio.read_bytes(os.path.join(ctx.run_dir, "run.json")), before)

    def test_the_same_missed_again_writes_nothing(self):
        # reporting the MISSED again wrote a second K6 line and a second ledger row
        ctx = self.dead()
        rc, card = self.run_ub("probe-result", ctx.run_dir, "MISSED", "--json")
        self.assertEqual(rc, 0, card)
        self.assertEqual(self.reload(ctx).read("08_DECISION.md").count(K6 % "I-002"), 1)
        ledger = os.path.join(os.path.dirname(ctx.run_dir), "LEDGER.md")
        self.assertNotIn("probe missed", textio.read_text(ledger) if os.path.exists(ledger) else "")

    def test_a_killed_runner_up_is_never_chosen_again(self):
        # NEW-I-HA-engine-flow-2: 2.0.3's switch made the killed idea the runner-up
        ctx = self.run_203("I-003", "I-001", [K6 % "I-001", SWITCHED % ("I-001", "I-003")])
        self.assertEqual(ctx.state["decision_log"], [K6 % "I-001", SWITCHED % ("I-001", "I-003")])
        self.assertIsNone(ctx.state["choice"]["runner_up"])
        self.assertEqual(ctx.state["probe"]["idea"], "I-001")
        self.assertFalse(render.k6_dead(ctx.state))  # the probe that missed was I-001's
        with self.assertRaises(EngineError) as cm:
            ub.switch_target(ctx, pipeline.load_steps(), SimpleNamespace(arch=None, idea="I-001"))
        self.assertEqual(str(cm.exception), "I-001 was killed by its probe (K6); choose another finalist (I-002, "
                                            "I-004)")
        self.assertEqual(gates.validate(ctx, "G13", {"action": "runner-up"}),
                         ["No runner-up was recorded at the decision."])
        effects = gates.probe_result(ctx, "MISSED", "0 of 10")
        self.assertEqual(ctx.state["choice"]["idea"], "I-003")
        self.assertNotIn("supersede", [e[0] for e in effects])

    def test_a_run_this_kit_started_is_left_alone(self):
        ctx = self.run_203("I-002", None, [K6 % "I-001"])
        ctx.state["decision_log"] = []
        ctx.state["probe"] = {"result": "MISSED"}
        migrate.upgrade_decisions(ctx.state, ctx.run_dir)
        self.assertEqual((ctx.state["decision_log"], ctx.state["probe"]), ([], {"result": "MISSED"}))
        # nor while a redo from the decision is pending: the file it moves still has the lines
        ctx.state.pop("decision_log")
        ctx.state["supersede"] = {"from": "10.5"}
        migrate.upgrade_decisions(ctx.state, ctx.run_dir)
        self.assertNotIn("decision_log", ctx.state)


# ------------------------------------------------------------------------------------------------ gap rounds

class GapRoundCountedByAnOlderKit(Base):
    def test_a_redo_counts_that_round_once(self):
        # NEW-I-HA-engine-flow-1: round 1's 5.3m ran under kit 2.0.3 (no counters.gap_counted)
        for redo in ("5.3c", "5.3m"):
            ctx = self.make_ctx(mode="deep", run_name="2026-09-01-l-gap-" + redo)
            for s in pipeline.load_steps():
                st.set_step(ctx.state, s["id"], "done", note="setup")
                if s["id"] == "5.3m":
                    break
            ctx.state["counters"].update({"gap_rounds": 1, "gap_prefix": 2, "reopen_prefix": 1,
                                          "gap_round_items": ["G1", "G2", "R1"]})
            for rel in ("pool/G1_gap.md", "pool/G2_gap.md", "pool/R1_reopen.md"):
                ctx.write(rel, "### %s-01 idea\n" % rel.split("/")[1][:2])
            pipeline.supersede_from(ctx, pipeline.load_steps(), redo)
            ctx.write_json("coverage.json", {"gap_needed": True})
            ctx.write("03_POOL.md", "# Pool\n")
            with mock.patch.object(registry, "bs", lambda *a, **kw: None):
                note = registry.run_script(ctx, "gap_round_end", pipeline.step_by_id(pipeline.load_steps(), "5.3m"))
            self.assertEqual(note, "gap round 1 done; another round follows", redo)
            self.assertEqual([ctx.state["counters"][k] for k in ("gap_rounds", "gap_prefix", "reopen_prefix")],
                             [1, 2, 1], redo)


# ------------------------------------------------------------------------------------------------ kickoff seeds

IMPORTED = "# Ideas from tool\n\n- IMPORTED-ALPHA: a shared swap board\n- IMPORTED-BETA: auto-match by skills\n"
FREE = "My ideas for this:\nIMPORTED-ALPHA a shared swap board\nIMPORTED-BETA auto-match by skills\n"
H3 = ("# Seeds\n\n### Problem\nNurses swap shifts by phone at 3 a.m.\n\n### Ideas\n- IMPORTED-ALPHA\n"
      "- IMPORTED-BETA\n\n### Off-limits\n- anything needing new hardware\n")


class SeedsFileOfTheUsersOwn(Base):
    def kickoff(self, ctx, text, reply="go"):
        ctx.write("00_HUMAN_SEEDS.md", text)
        ans = gates.merge_answer("G0", {"reply": reply}, ctx)
        ctx.state.setdefault("gates", {})["G0"] = {"state": "answered", "by": "human", "answer": ans}
        registry.write_seeds(ctx, ans)
        return ctx.read("00_HUMAN_SEEDS.md")

    def test_an_idea_list_free_text_and_h3_headings_are_kept(self):
        # 0.3 replaced such a --seeds-file with the reply's seeds or a bare SKIPPED line
        for n, (mode, text) in enumerate([(m, t) for m in ("standard", "proposal") for t in (IMPORTED, FREE, H3)]):
            ctx = self.make_ctx(mode=mode, run_name="2026-09-01-l-seeds-%d" % n)
            ctx.state["idea_text"] = "a shared swap board per ward"
            out = self.kickoff(ctx, text)
            ideas = registry.section(out, "Ideas")
            self.assertIn("IMPORTED-ALPHA", ideas, out)
            self.assertIn("IMPORTED-BETA", ideas, out)
            self.assertNotRegex(out, r"(?m)^SKIPPED\b")
            if text is H3:
                self.assertEqual(registry.section(out, "Problem"), "Nurses swap shifts by phone at 3 a.m.")
                self.assertEqual(registry.section(out, "Off-limits"), "- anything needing new hardware")
            if mode == "proposal":
                self.assertEqual(registry.section(out, "Primary idea"), "- a shared swap board per ward", out)
        out = self.kickoff(self.make_ctx(run_name="2026-09-01-l-seeds-reply"), FREE, "go\nlet charge nurses approve")
        self.assertIn("- let charge nurses approve", registry.section(out, "Ideas"))
        self.assertIn("IMPORTED-ALPHA", registry.section(out, "Ideas"))

    def test_a_skip_keeps_free_text(self):
        self.assertEqual(registry.skipped_seeds(FREE, "full-auto"), "SKIPPED: full-auto\n\n" + FREE)
        self.assertEqual(registry.skipped_seeds(st.seeds_doc(), "full-auto"), "SKIPPED: full-auto\n")

    @unittest.skipUnless(tl.stubs_available(), "B4 stubs or B2 bs.py missing")
    def test_a_full_auto_run_reads_the_ideas(self):
        ctx = tl.full_auto_ctx(self, mode="quick", run_name="2026-09-01-l-seeds-auto")
        ctx.write("00_HUMAN_SEEDS.md", IMPORTED)
        self.assertEqual(tl.drive(ctx)["type"], "DONE")
        self.assertIn("IMPORTED-ALPHA", registry.section(ctx.read("00_HUMAN_SEEDS.md"), "Ideas"))


# ------------------------------------------------------------------------------------------------ K6 after the run

@unittest.skipUnless(tl.stubs_available(), "B4 stubs or B2 bs.py missing")
class SeedAndPublishedCopyAfterAKill(Base):
    def test_they_say_killed(self):
        # bullet 2: 14.3 was not rendered again, so the seed kept CLOSING and docs/<run>/ kept AUTOPILOT DRAFT
        self.assertIn("14.3", pipeline.step_ref("probe_rerender"))
        with mock.patch.object(handoff, "g14", lambda ctx: {"handoff": "ce", "publish": True}):
            ctx = tl.full_auto_ctx(self, mode="quick", variant="growth", run_name="2026-09-01-l-seed")
            self.assertEqual(tl.drive(ctx)["type"], "DONE")
            for _ in range(2):  # the first MISSED chooses the runner-up; the second leaves none
                rc, card = self.run_ub("probe-result", ctx.run_dir, "MISSED", "--json", deps=ctx.deps)
                self.assertEqual(rc, 0, card)
                ctx = self.reload(ctx)
                card = tl.drive(ctx)
                self.assertEqual(card["type"], "DONE")
        ctx = self.reload(ctx)
        self.assertTrue(render.k6_dead(ctx.state))
        seed = ctx.read("handoff/ce-seed.md")
        self.assertNotIn(handoff.CLOSING, seed)
        self.assertIn(handoff.K6_WARNING, seed)
        published = textio.read_text(os.path.join(ctx.state["project_dir"], "docs", ctx.state["run"], "11_PROPOSAL",
                                                  "PROPOSAL.md"))
        self.assertIn("Status: %s" % render.KILLED_BANNER, published)
        self.assertIn("PROPOSAL.md (KILLED (K6))", card["show"])


# ------------------------------------------------------------------------------------------------ Appendix C

class AppendixCWithEveryCandidateExcluded(Base):
    X = j2.ReadmeWithEveryCandidateExcluded
    QGS, CRITERIA, cand, excluded = X.QGS, X.CRITERIA, X.cand, X.excluded

    def test_no_leader_and_no_rank(self):
        # bullet 4: 'Leader: None (close-call).' and rank None in every row
        ctx = self.excluded()
        gates.apply(ctx, "G11", {"accept_recommendation": True}, by="auto")
        text = render.appendix_c(ctx)
        self.assertTrue(text.endswith("\n\nLeader: none (every candidate EXCLUDED)."), text)
        self.assertNotIn("None", text)
        self.assertRegex(text, r"(?m)^\| A \| [\d.]+ \| - \| ")


# ------------------------------------------------------------------------------------------------ criteria.json

class CriteriaValues(Base):
    def frame_check(self, n, crit):
        ctx = self.make_ctx(run_name="2026-09-01-l-crit-%d" % n)
        st.save(ctx.run_dir, ctx.state)
        ctx.write_json("criteria.json", crit)
        note = registry.run_script(ctx, "frame_check", {"id": "2.2"})
        return ctx, note, ctx.read_json("criteria.json")

    def test_a_value_that_is_no_weight_is_dropped(self):
        ctx, note, crit = self.frame_check(0, {"Value": 40, "Feasibility": 60, "Novelty": "n/a"})
        self.assertEqual(crit, {"Value": 40.0, "Feasibility": 60.0})
        self.assertIn("criteria.json: Novelty dropped (not a number)", note)
        ctx, note, crit = self.frame_check(1, {"Value": 150, "Cost": -50, "Reach": True})
        self.assertEqual(crit, {"Value": 100.0, "Cost": 0.0})
        self.assertIn("Cost counted as 0 (negative)", note)
        for n, bad in enumerate(({"Value": "40", "Feasibility": 60}, {"Value": float("nan"), "Reach": 100})):
            crit = self.frame_check(2 + n, bad)[2]
            self.assertEqual(schema_lite.validate(crit, validate.CRITERIA_SCHEMA), [], crit)
        self.assertEqual(self.frame_check(4, {"Value": 40, "Feasibility": 60})[1], "frame checked")

    @unittest.skipUnless(tl.stubs_available(), "B4 stubs or B2 bs.py missing")
    def test_bs_reads_only_numbers(self):
        ctx = self.frame_check(5, {"Value": 40, "Feasibility": 60, "Novelty": "n/a"})[0]
        p = subprocess.run([sys.executable, os.path.join(tl.SCRIPTS, "bs.py"), "screen", ctx.run_dir],
                           capture_output=True, text=True, encoding="utf-8", timeout=120)
        self.assertNotIn("could not convert", p.stdout + p.stderr)
        self.assertEqual(registry.criteria(ctx), {"Value": 40.0, "Feasibility": 60.0})


if __name__ == "__main__":
    unittest.main()
