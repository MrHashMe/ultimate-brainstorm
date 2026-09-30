"""B3 engine: HUMAN gates (KIT_SPEC 4.12, 6.2): every gate has a template, an answer_template and a
default_answer; answer validation, errors and re-ask; the deterministic reply parser (terminal mode and hosts that fill
only `reply`); policies per autopilot preset; the answer file protocol."""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fixtures", "engine"))
import engine_testlib as tl  # noqa: E402

from ublib import textio  # noqa: E402
from ublib.engine import gates, pipeline, registry  # noqa: E402
from ublib.engine import state as st  # noqa: E402

GATES = ("G0", "G1", "G2", "G2c", "G2f", "G3", "G4", "G5", "G6", "G7", "G8a", "G8b", "G9", "G10", "G11", "G12",
         "G13", "G14", "GB", "GX")

# 4.12 gate list: answer_template fields beyond `reply`
SPEC_FIELDS = {
    "G0": ["confirm", "topic", "mode", "variant", "autopilot", "private", "privacy", "families", "with_ce_ideate",
           "seeds", "skip_seeds", "quick", "idea"],
    "G1": ["done", "skip"], "G2": ["answers", "accept_defaults"], "G2c": ["confirm", "corrections"],
    "G2f": ["restore"], "G3": ["ideas", "cells"], "G4": ["rescue", "confirm_flags"], "G5": ["kill", "keep"],
    "G6": ["finalists"], "G7": ["picks"], "G8a": ["picks", "skip", "notes"],
    "G8b": ["chosen", "runner_up", "bundle", "park", "why", "accept_recommendation"], "G9": ["result", "note"],
    "G10": ["confirm", "corrections"], "G11": ["choice", "steal", "notes", "accept_recommendation"],
    "G12": ["accept", "reject"], "G13": ["action", "changes", "switch_to"],
    "G14": ["publish", "merge_terms", "terms", "handoff"], "GB": ["raise_to", "stop"], "GX": ["action"],
}


class InventoryTests(unittest.TestCase):
    def test_every_gate_has_template_answer_template_and_default(self):
        self.assertEqual(sorted(gates.all_gates()), sorted(GATES))
        for gid in GATES:
            self.assertTrue(os.path.exists(os.path.join(tl.TEMPLATES, "gates", gid + ".md")), gid)
            tpl = gates.answer_template(gid)
            self.assertIn("reply", tpl)
            self.assertIsNone(tpl["reply"])
            self.assertEqual(sorted(k for k in tpl if k != "reply"), sorted(SPEC_FIELDS[gid]), gid)
            self.assertIn("reply", gates.default_answer(gid), gid)
            self.assertIn(gid, gates.TITLES)
            self.assertTrue(gates.HOW_TO_REPLY.get(gid), gid)

    def test_spec_defaults(self):
        self.assertEqual(gates.default_answer("G0")["confirm"], True)
        self.assertEqual(gates.default_answer("G0")["skip_seeds"], True)
        self.assertEqual(gates.default_answer("G8a")["skip"], True)
        self.assertEqual(gates.default_answer("G8b")["accept_recommendation"], True)
        self.assertEqual(gates.default_answer("G11")["accept_recommendation"], True)
        self.assertEqual(gates.default_answer("G13")["action"], "approve")
        self.assertEqual(gates.default_answer("G14")["publish"], False)
        self.assertEqual(gates.default_answer("G14")["handoff"], "none")


class ParserTests(unittest.TestCase):
    def test_g0_keyword_lines_vs_seeds(self):
        p = gates.parse_reply("G0", "deep guided\ndeep learning ideas\nPrimary: a shared ledger\nprivate")
        self.assertEqual(p["mode"], "deep")
        self.assertEqual(p["autopilot"], "guided")
        self.assertTrue(p["private"])
        self.assertEqual(p["seeds"]["ideas"], ["deep learning ideas"])  # a seed, not a keyword line
        self.assertEqual(p["seeds"]["primary"], "a shared ledger")
        p = gates.parse_reply("G0", "go")
        self.assertTrue(p["confirm"])
        self.assertEqual(p["seeds"]["ideas"], [])
        p = gates.parse_reply("G0", "criteria: speed, cost, trust\nconstraint: no new hardware\nweb: no")
        self.assertEqual(p["quick"]["criteria"], ["speed", "cost", "trust"])
        self.assertEqual(p["quick"]["hard_constraint"], "no new hardware")
        self.assertEqual(p["privacy"]["web"], False)

    def test_g8a_ids(self):
        p = gates.parse_reply("G8a", "I-031: they already use SMS\nI-004 second\nI-010")
        self.assertEqual(p["picks"], ["I-031", "I-004", "I-010"])
        self.assertTrue(gates.parse_reply("G8a", "skip")["skip"])

    def test_g8b(self):
        self.assertTrue(gates.parse_reply("G8b", "ok")["accept_recommendation"])
        p = gates.parse_reply("G8b", "I-014 because night staff already trust the ward chat; runner-up: I-004; "
                                     "park: I-010")
        self.assertEqual(p["chosen"], "I-014")
        self.assertEqual(p["runner_up"], "I-004")
        self.assertEqual(p["park"], ["I-010"])
        self.assertFalse(p["accept_recommendation"])
        self.assertIn("night staff", p["why"])

    def test_g13(self):
        self.assertEqual(gates.parse_reply("G13", "approve")["action"], "approve")
        p = gates.parse_reply("G13", "changes: shorten section 4 and add a pilot budget")
        self.assertEqual(p["action"], "changes")
        self.assertEqual(p["changes"], "shorten section 4 and add a pilot budget")
        self.assertEqual(gates.parse_reply("G13", "switch B"), {"action": "switch", "switch_to": "B"})
        self.assertEqual(gates.parse_reply("G13", "runner-up")["action"], "runner-up")

    def test_g11_steal(self):
        self.assertTrue(gates.parse_reply("G11", "ok")["accept_recommendation"])
        p = gates.parse_reply("G11", "B + steal A: offline cache")
        self.assertEqual(p["choice"], "B")
        self.assertEqual(p["steal"], [{"from": "A", "element": "offline cache"}])
        self.assertEqual(gates.parse_reply("G11", "C+steal")["steal"], ["*"])

    def test_other_gates(self):
        self.assertEqual(gates.parse_reply("G12", "accept 1 2 4, reject 3"), {"accept": ["0001", "0002", "0004"],
                                                                              "reject": ["0003"]})
        self.assertEqual(gates.parse_reply("G12", "ok")["accept"], ["all"])
        p = gates.parse_reply("G4", "rescue I-012: the budget gate is wrong\nconfirm I-004\nclear I-007")
        self.assertEqual(p["rescue"], [{"id": "I-012", "reason": "the budget gate is wrong"}])
        self.assertEqual(p["confirm_flags"], ["I-004"])
        self.assertEqual(gates.parse_reply("G5", "kill I-001 I-002\nkeep I-003"), {"kill": ["I-001", "I-002"],
                                                                                   "keep": ["I-003"]})
        self.assertEqual(gates.parse_reply("G9", "passed: 7 of 10")["result"], "PASSED")
        self.assertEqual(gates.parse_reply("GB", "raise to 250"), {"raise_to": 250, "stop": False})
        self.assertEqual(gates.parse_reply("GX", "reframe please"), {"action": "reframe"})
        p = gates.parse_reply("G14", "publish architecture, adr; handoff ce")
        self.assertEqual(p["publish"], ["architecture", "adr"])
        self.assertEqual(p["handoff"], "ce")
        self.assertEqual(gates.parse_reply("G14", "no"), {"publish": False, "handoff": "none"})
        p = gates.parse_reply("G2", "1: night nurses in small hospitals\n3: by March")
        self.assertEqual(p["answers"], [{"q": "1", "a": "night nurses in small hospitals"},
                                        {"q": "3", "a": "by March"}])
        self.assertTrue(gates.parse_reply("G2", "defaults")["accept_defaults"])
        self.assertEqual(gates.parse_reply("G3", "cell: app | night\nan idea"),
                         {"ideas": ["an idea"], "cells": ["app | night"]})

    def test_merge_answer_prefers_explicit_fields(self):
        ans = gates.merge_answer("G8b", {"reply": "I-002 because x", "chosen": "I-003"})
        self.assertEqual(ans["chosen"], "I-003")  # the host's explicit field wins over the parsed reply
        ans = gates.merge_answer("G8b", {"reply": "I-002 because x"})
        self.assertEqual(ans["chosen"], "I-002")


class PolicyTests(tl.EngineTestCase):
    def test_policy_table_6_2(self):
        def pol(gid, mode="standard", ap="guided"):
            return gates.policy(self.make_ctx(mode=mode, autopilot=ap), gid)
        self.assertEqual(pol("G0"), "ask")
        self.assertEqual(pol("G0", ap="full-auto"), "ask")  # privacy defaults unset
        st.config_set("privacy_defaults", {"web": True, "vendors": True, "code": False})
        self.assertEqual(pol("G0", ap="full-auto"), "ask")  # saved before the vendor set was kept: asked once
        st.config_set("privacy_defaults", {"web": True, "vendors": True, "code": False,
                                           "vendor_set": ["anthropic", "moonshot", "openai", "zhipu"]})
        self.assertEqual(pol("G0", ap="full-auto"), "auto")
        for gid in ("G1", "G2c", "G3", "G6", "G7", "G9"):
            self.assertEqual(pol(gid, ap="hands-on"), "ask", gid)
            self.assertEqual(pol(gid), "skip", gid)
        for gid in ("G4", "G5"):
            self.assertEqual(pol(gid, ap="hands-on"), "ask")
            self.assertEqual(pol(gid), "auto")
        self.assertEqual(pol("G8a"), "ask")
        self.assertEqual(pol("G8a", ap="full-auto"), "skip")
        self.assertEqual(pol("G8b"), "ask")
        self.assertEqual(pol("G8b", ap="full-auto"), "auto")
        self.assertEqual(pol("G10"), "auto")
        self.assertEqual(pol("G10", mode="deep"), "ask")
        self.assertEqual(pol("G11"), "ask")
        self.assertEqual(pol("G11", mode="quick"), "auto")
        self.assertEqual(pol("G11", ap="full-auto"), "auto")
        self.assertEqual(pol("G12"), "skip")
        self.assertEqual(pol("G12", mode="deep"), "ask")
        self.assertEqual(pol("G13"), "ask")
        self.assertEqual(pol("G13", ap="full-auto"), "auto")
        self.assertEqual(pol("G14"), "ask")
        self.assertEqual(pol("G14", ap="full-auto"), "skip")
        self.assertEqual(pol("G2f", ap="full-auto"), "ask")
        self.assertEqual(pol("GX", ap="full-auto"), "ask")
        self.assertEqual(pol("GB", ap="full-auto"), "skip")


class ValidationTests(tl.EngineTestCase):
    def setUp(self):
        tl.EngineTestCase.setUp(self)
        self.ctx = self.make_ctx()
        self.ctx.state["finalists"] = ["I-001", "I-002", "I-003"]
        self.ctx.state["top"] = ["I-001", "I-002", "I-003"]

    def v(self, gid, ans):
        return gates.validate(self.ctx, gid, gates.merge_answer(gid, ans, self.ctx))

    def test_g8a_and_g8b(self):
        self.assertEqual(self.v("G8a", {"picks": ["I-001"]}), [])
        self.assertTrue(self.v("G8a", {"picks": ["I-099"]}))
        self.assertTrue(self.v("G8a", {"picks": []}))
        self.assertEqual(self.v("G8a", {"skip": True}), [])
        self.assertEqual(self.v("G8b", {"accept_recommendation": True}), [])
        self.assertTrue(self.v("G8b", {"reply": "hmm"}))
        self.assertTrue(self.v("G8b", {"chosen": "I-042"}))

    def test_g0(self):
        self.assertEqual(self.v("G0", {"confirm": True}), [])
        self.assertTrue(self.v("G0", {"mode": "huge"}))
        self.assertTrue(self.v("G0", {"families": ["mistral"]}))
        self.ctx.state["topic"] = ""
        self.assertTrue(self.v("G0", {"confirm": True}))
        self.assertEqual(self.v("G0", {"topic": "a topic"}), [])

    def test_g13_and_gb(self):
        self.assertEqual(self.v("G13", {"action": "approve"}), [])
        self.assertTrue(self.v("G13", {"action": "runner-up"}))  # no runner-up recorded
        self.ctx.state["counters"]["g13_loops"] = 2
        self.assertTrue(self.v("G13", {"action": "changes", "changes": "x"}))
        # the cap counts backend requests (the ledger), not launches, and must cover the launch it refused
        self.ctx.state["counters"]["launched"] = 1
        self.ctx.write("logs/calls.jsonl", "".join('{"id": "j%d", "requests": 5}\n' % i for i in range(20)))
        self.ctx.state["budget"]["need"] = 3
        self.assertTrue(self.v("GB", {"raise_to": 50}))
        self.assertIn("at least 103", self.v("GB", {"raise_to": 102})[0])
        self.assertEqual(self.v("GB", {"raise_to": 103}), [])
        self.assertEqual(self.v("GB", {"stop": True}), [])

    def test_answer_file_protocol_reasks_with_error(self):
        ctx = self.ctx
        steps = [{"id": "9.5", "stage": 9, "title": "Gut pick", "type": "HUMAN", "gate": "G8a"}]
        card = pipeline.advance(ctx, steps, 0)
        self.assertEqual(card["type"], "HUMAN")
        self.assertEqual(card["gate"], "G8a")
        self.assertFalse(os.path.exists(card["answer_file"]))  # a stale answer file is deleted
        self.assertTrue(card["answer_cmd"].endswith('G8a --file "%s" --json' % card["answer_file"]))
        self.assertTrue(os.path.exists(card["show_file"]))
        again = pipeline.answer_gate(ctx, steps, "G8a", {"picks": ["I-042"]})
        self.assertEqual(again["type"], "HUMAN")
        self.assertIn("I-042", again["error"])
        self.assertTrue(again["show"].startswith("PLEASE FIX:"))
        done = pipeline.answer_gate(ctx, steps, "G8a", {"reply": "I-002: the ward already uses it"})
        self.assertEqual(done["type"], "DONE")
        self.assertEqual(ctx.state["gates"]["G8a"]["answer"]["picks"], ["I-002"])
        self.assertEqual(ctx.state["gates"]["G8a"]["by"], "human")
        self.assertTrue(os.path.exists(os.path.join(ctx.run_dir, "answers", "G8a.json")))
        self.assertIn("I-002", ctx.read("tournament/precommit.md"))

    def test_wrong_gate_is_not_applied(self):
        steps = [{"id": "9.5", "stage": 9, "title": "Gut pick", "type": "HUMAN", "gate": "G8a"}]
        card = pipeline.answer_gate(self.ctx, steps, "G13", {"action": "approve"})
        self.assertEqual(card["gate"], "G8a")
        self.assertTrue(any("not the gate" in n for n in card["notes"]))


class ApplyTests(tl.EngineTestCase):
    def test_g0_changes_the_plan_and_privacy(self):
        ctx = self.make_ctx()
        ans = gates.merge_answer("G0", {"reply": "quick\nprivate\nmy own idea one\nPrimary: test this idea"}, ctx)
        gates.apply(ctx, "G0", ans)
        self.assertEqual(ctx.state["mode"], "quick")
        self.assertEqual(ctx.state["budget"]["max_calls"], 60)
        self.assertEqual(ctx.state["privacy"]["vendors"], False)
        self.assertEqual(ctx.state["gates"]["G0"]["state"], "answered")
        registry.write_seeds(ctx, ans)
        seeds = ctx.read("00_HUMAN_SEEDS.md")
        self.assertIn("- my own idea one", seeds)
        self.assertIn("- test this idea", seeds)

    def test_g8b_rule_default_and_runner_up(self):
        ctx = self.make_ctx(autopilot="full-auto")
        ctx.state["finalists"] = ["I-001", "I-002", "I-003"]
        ctx.state["top"] = ["I-001", "I-002", "I-003"]
        ctx.write("tournament/result.json", '{"debiased": [{"id": "I-002", "pct": 80}, {"id": "I-001", "pct": 60},'
                                            ' {"id": "I-003", "pct": 10}]}')
        ctx.write("redteam/I-003_ADVOCATE_gpt.md", "x\nVERDICT: BACK; confidence 0.8\n")
        ctx.write("redteam/I-003_CRITIC_kimi.md", "x\nVERDICT: BACK IF pilots agree; confidence 0.6\n")
        ctx.write("redteam/I-002_ADVOCATE_gpt.md", "x\nVERDICT: DON'T BACK; confidence 0.8\n")
        ans = gates.merge_answer("G8b", gates.default_answer("G8b"), ctx)
        gates.apply(ctx, "G8b", ans, by="auto")
        self.assertEqual(ctx.state["choice"]["idea"], "I-003")  # most BACK + BACK IF verdicts wins
        self.assertEqual(ctx.state["choice"]["runner_up"], "I-002")  # then the best debiased %
        self.assertEqual(ctx.state["gates"]["G8b"]["by"], "auto")

    def test_g11_records_choice_and_writer(self):
        ctx = self.make_ctx()
        ctx.write("10_ARCHITECTURE/candidates/map.json", '{"A": {"family": "gpt", "n": "1"}, "B": {"family": "kimi",'
                                                          ' "n": "2"}}')
        ctx.write("10_ARCHITECTURE/matrix.json", '{"leader": "A", "steal": [{"from": "B", "element": "cache"}]}')
        gates.apply(ctx, "G11", gates.merge_answer("G11", {"reply": "B+steal"}, ctx))
        self.assertEqual(ctx.state["choice"]["arch"], "B")
        self.assertEqual(ctx.state["choice"]["arch_family"], "kimi")
        self.assertEqual(ctx.state["seats"]["arch_writer"], "kimi")
        gates.apply(ctx, "G11", gates.merge_answer("G11", {"reply": "ok"}, ctx))
        self.assertEqual(ctx.state["choice"]["arch"], "A")

    def test_g13_changes_resets_steps(self):
        ctx = self.make_ctx()
        effects = gates.apply(ctx, "G13", gates.merge_answer("G13", {"reply": "changes: add costs"}, ctx))
        self.assertEqual(effects[0][0], "reset")
        self.assertIn("13.6", effects[0][1])
        self.assertEqual(ctx.state["user_changes"], "add costs")

    def test_probe_missed_moves_to_runner_up(self):
        ctx = self.make_ctx()
        ctx.state["choice"].update({"idea": "I-001", "runner_up": "I-002"})
        ctx.write("09_PROBE.md", "## 4. Kill criterion\nx\nRESULT: PENDING\n")
        ctx.write("08_DECISION.md", "# DECISION\n")
        effects = gates.probe_result(ctx, "MISSED", "2 of 10 signed up")
        self.assertEqual(ctx.state["choice"]["idea"], "I-002")
        self.assertIn(("supersede", "11.1"), effects)
        self.assertIn("RESULT: MISSED (K6)", ctx.read("09_PROBE.md"))
        # the decision line and the ledger row follow the supersede that commits the kill (#11)
        self.assertEqual([e[0] for e in effects], ["supersede", "append", "ledger"])
        self.assertEqual(effects[1][1], "08_DECISION.md")
        self.assertIn("I-001 - K6", effects[1][2])
        self.assertNotIn("K6", ctx.read("08_DECISION.md"))


class DisplayTests(tl.EngineTestCase):
    def test_every_gate_renders_without_raw_placeholders(self):
        ctx = self.make_ctx()
        ctx.state["finalists"] = ["I-001", "I-002"]
        ctx.state["top"] = ["I-001", "I-002"]
        for gid in GATES:
            text = gates.display(ctx, gid)
            self.assertNotIn("{{", text, gid)
            self.assertIn(ctx.state["run"], text, gid)
            self.assertEqual(textio.read_text(os.path.join(ctx.run_dir, "gates", gid + ".md")), text)

    def test_g8b_shows_verdict_lines_before_the_synthesis(self):
        ctx = self.make_ctx()
        ctx.state["finalists"] = ["I-001", "I-002"]
        ctx.state["top"] = ["I-001", "I-002"]
        ctx.write("redteam/I-001_ADVOCATE_gpt.md", "x\nVERDICT: BACK; confidence 0.8\n")
        ctx.write("07_REDTEAM.md", "## 1. Per idea\nx\n## 2. Decision brief\nTHE SYNTHESIS TEXT\n## 3. Whole effort\n"
                                   "y\nWHOLE-EFFORT: CONTINUE - fine\n")
        text = gates.display(ctx, "G8b")
        self.assertLess(text.index("VERDICT: BACK"), text.index("THE SYNTHESIS TEXT"))
        self.assertNotIn("(gpt)", text)  # verdict lines carry no family names
        self.assertIn("Suggested by rule; you decide: I-001", text)

    def test_provisional_banner(self):
        ctx = self.make_ctx(families=("claude",))
        self.assertTrue(gates.provisional_banner(ctx).startswith("PROVISIONAL: "))
        ctx = self.make_ctx(run_name="other")
        self.assertEqual(gates.provisional_banner(ctx), "")
        st.add_provisional(ctx.state, "screen", "gpt", "gpt-alt", "codex failed")
        self.assertIn("gpt -> gpt-alt", gates.provisional_banner(ctx))


if __name__ == "__main__":
    unittest.main()
