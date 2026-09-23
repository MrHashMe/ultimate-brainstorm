"""B3 engine: pipeline.json and the driver loop (KIT_SPEC 6.2-6.4, 6.11, 4.11-4.12): golden step and gate sequences
for every mode x autopilot, predicates and fanouts, min_ok / fallback / BLOCKED logic with a fake batch module, the
relaunch limit, budgets, HOST_BATCH, prelaunch during G8a, the crash hook, the ub.py CLI, and in-process runs driven
like a host."""

import io
import json
import os
import re
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fixtures", "engine"))
import engine_testlib as tl  # noqa: E402

from ublib import textio  # noqa: E402
from ublib.engine import EngineError, builders, cards, gates, pipeline, registry  # noqa: E402
from ublib.engine import state as st  # noqa: E402

sys.path.insert(0, tl.SCRIPTS)
import ub  # noqa: E402
_KIT_V = open(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "VERSION"),
              encoding="utf-8").read().strip()  # kit version, so a release bump needs no test edits

MODES = ("quick", "standard", "deep", "proposal")
PRESETS = ("hands-on", "guided", "full-auto")


def golden():
    with open(tl.fixture_path("golden_sequences.json"), encoding="utf-8") as f:
        return json.load(f)


class PipelineDataTests(unittest.TestCase):
    def test_pipeline_json_is_valid(self):
        steps = pipeline.load_steps()
        ids = [s["id"] for s in steps]
        self.assertEqual(len(ids), len(set(ids)))
        for s in steps:
            self.assertIn(s["type"], ("SCRIPT", "DISPATCH", "HUMAN", "HOST"), s["id"])
            self.assertIn("stage", s)
            self.assertTrue(0 <= int(s["stage"]) <= 14)
            for w in s.get("when") or []:
                for part in w.split("|"):
                    self.assertIn(part.lstrip("!").split(":")[0], registry.PREDICATES, s["id"])
            if s["type"] == "DISPATCH":
                self.assertIn(s["fanout"], registry.FANOUTS, s["id"])
                self.assertIn(s["job"]["kind"], ("ping", "generator", "researcher", "curator", "judge", "checker",
                                                 "normalizer", "reviewer", "synthesis", "writer", "arch-author",
                                                 "arch-judge", "rubric", "redteam", "fixer", "frame"))
            if s["type"] == "SCRIPT":
                self.assertIn(s["script"], registry.SCRIPTS, s["id"])
            for a in s.get("after") or []:
                self.assertIn(a, registry.SCRIPTS, s["id"])
            if s["type"] == "HUMAN":
                self.assertIn(s["gate"], gates.FIELDS)
            if s["type"] == "HOST":
                self.assertTrue(os.path.exists(registry.template_path(s["host"]["template"], "host")), s["id"])
        for sid in ("0.1", "0.2", "2.1q", "4.2", "5.1", "6.2", "7.1", "9.4", "9.5", "10.5", "11.1", "12.1", "12.4",
                    "12.9", "12.10", "12.11", "12.12", "13.2", "13.4", "13.8", "14.2", "14.4", "Q.2", "P.1"):
            self.assertIn(sid, ids)

    def test_estimates_cover_every_kind(self):
        est = textio.read_json(os.path.join(tl.SCRIPTS, "estimates.json"))
        for kind in ("ping", "generator", "researcher", "curator", "judge", "checker", "normalizer", "reviewer",
                     "synthesis", "writer", "arch-author", "arch-judge", "rubric", "redteam", "fixer", "frame"):
            self.assertIn(kind, est)
            self.assertEqual(sorted(est[kind]), ["in_tokens", "out_tokens", "seconds"])


class GoldenSequenceTests(tl.EngineTestCase):
    def test_every_mode_and_preset_matches_the_golden_lists(self):
        g = golden()
        for mode in MODES:
            for ap in PRESETS:
                ctx = self.make_ctx(mode=mode, autopilot=ap, run_name="%s-%s" % (mode, ap))
                seq = pipeline.simulate(ctx, with_gates=True)
                steps = [i["id"] for i in seq]
                gate_list = ["%s:%s" % (i["gate"], i["policy"]) for i in seq if i["type"] == "HUMAN"]
                self.assertEqual(steps, g["%s/%s" % (mode, ap)]["steps"], (mode, ap))
                self.assertEqual(gate_list, g["%s/%s" % (mode, ap)]["gates"], (mode, ap))

    def test_gate_table_6_2(self):
        g = golden()

        def asked(key):
            return [x.split(":")[0] for x in g[key]["gates"] if x.endswith(":ask")]
        self.assertEqual(asked("quick/guided"), ["G0", "G8b", "G13", "G14"])  # 3-4 replies
        self.assertEqual(asked("standard/guided"), ["G0", "G2", "G8a", "G8b", "G11", "G13", "G14"])
        self.assertEqual(asked("deep/guided"), ["G0", "G2", "G8a", "G8b", "G10", "G11", "G12", "G13", "G14"])
        for mode in MODES:
            self.assertEqual(asked("%s/full-auto" % mode), ["G0"])  # G0 asks only while privacy defaults are unset
        hands_on = asked("standard/hands-on")
        for gid in ("G2c", "G3", "G4", "G7", "G9", "G10", "G12"):
            self.assertIn(gid, hands_on)
        # hands-on: the gut pick is asked before the tournament judges run
        steps = g["standard/hands-on"]["steps"]
        self.assertLess(steps.index("9.5"), steps.index("9.4"))
        # full-auto frame draft; the architecture and proposal always run
        self.assertIn("2.1f", g["standard/full-auto"]["steps"])
        for key in g:
            for sid in ("12.1", "13.4", "14.4"):
                self.assertIn(sid, g[key]["steps"], key)
        self.assertIn("12.10l", g["quick/guided"]["steps"])
        self.assertIn("13.2l", g["quick/guided"]["steps"])
        self.assertIn("P.2", g["proposal/guided"]["steps"])
        self.assertNotIn("4.2", g["proposal/guided"]["steps"])

    def test_approach_build_type_and_grilling(self):
        ctx = self.make_ctx(variant="research")
        steps = [i["id"] for i in pipeline.simulate(ctx, with_gates=True)]
        self.assertIn("12.a", steps)
        self.assertNotIn("12.4", steps)
        self.assertNotIn("12.9", steps)  # no G11
        ctx = self.make_ctx(run_name="g")
        ctx.state["components"]["grilling"] = "mattpocock-skills:grilling"
        steps = [i["id"] for i in pipeline.simulate(ctx, with_gates=True)]
        self.assertIn("2.1g", steps)
        self.assertNotIn("2.1q", steps)
        ctx.state["host"]["agent"] = "terminal"
        steps = [i["id"] for i in pipeline.simulate(ctx, with_gates=True)]
        self.assertNotIn("2.1g", steps)


class PredicateTests(tl.EngineTestCase):
    def test_when_syntax(self):
        ctx = self.make_ctx(mode="deep", variant="growth", autopilot="hands-on")
        self.assertTrue(registry.eval_when(ctx, ["deep", "hands_on", "variant_in:software,growth"]))
        self.assertFalse(registry.eval_when(ctx, ["!deep"]))
        self.assertTrue(registry.eval_when(ctx, ["mode_is:quick|deep"]))
        self.assertTrue(registry.eval_when(ctx, ["autopilot_is:hands-on", "not_full_auto", "privacy_web"]))
        self.assertTrue(registry.eval_when(ctx, ["build_type:system"]))
        self.assertFalse(registry.eval_when(ctx, ["repo_variant"]))  # no .git in the project
        os.makedirs(os.path.join(self.project, ".git"))
        self.assertTrue(registry.eval_when(ctx, ["repo_variant"]))
        with self.assertRaises(EngineError):
            registry.eval_when(ctx, ["no_such_predicate"])

    def test_file_driven_predicates(self):
        ctx = self.make_ctx()
        self.assertTrue(registry.eval_when(ctx, ["no_seeds"]))
        ctx.write("00_HUMAN_SEEDS.md", "## Ideas\n- one idea\n")
        self.assertFalse(registry.eval_when(ctx, ["no_seeds"]))
        ctx.write("07_REDTEAM.md", "x\nWHOLE-EFFORT: STOP - nobody has this problem\n")
        self.assertTrue(registry.eval_when(ctx, ["synthesis_stop"]))
        ctx.write("coverage.json", '{"homogenized": true, "empty": []}')
        self.assertTrue(registry.eval_when(ctx, ["homogenized_or_gaps"]))
        ctx.state["counters"]["gap_rounds"] = 1
        self.assertFalse(registry.eval_when(ctx, ["homogenized_or_gaps"]))


class FanoutTests(tl.EngineTestCase):
    def test_strategies_seats_and_contracts(self):
        ctx = self.make_ctx()
        ctx.write("01_FRAME.md", "## Axes\n- Moment: day | night\n")
        items = registry.FANOUTS["strategies"](ctx, {"id": "4.2"})
        self.assertEqual([i["id"] for i in items], ["S2", "S3", "S4", "S5"])
        by = dict((i["id"], i) for i in items)
        self.assertEqual(by["S3"]["family"], "gpt")
        self.assertEqual(by["S4"]["tools"], "web")
        self.assertEqual(by["S3"]["contract"], {"type": "idea-blocks", "prefix": "S3", "min": 10})
        self.assertEqual(by["S2"]["stub"]["axes"], {"Moment": ["day", "night"]})
        self.assertIn("seed_leak", by["S2"]["checks"])
        deep = self.make_ctx(mode="deep", run_name="deep")
        ids = [i["id"] for i in registry.FANOUTS["strategies"](deep, {"id": "4.2"})]
        self.assertEqual(ids, ["S2", "S3", "S4", "S5", "L1", "L2", "L3", "L4", "L5", "L6"])
        research = self.make_ctx(variant="research", run_name="res")
        self.assertEqual(registry.FANOUTS["strategies"](research, {"id": "4.2"})[3]["template"], "S5-RESEARCH")

    def test_judges_cover_every_idea(self):
        ctx = self.make_ctx()
        ctx.write("screen/ideas.md", "I-001 | a | b | c\nI-002 | a | b | c\n")
        items = registry.FANOUTS["screen_judges"](ctx, {"id": "6.2"})
        self.assertEqual([i["family"] for i in items], ["claude", "gpt", "kimi"])
        self.assertEqual(items[0]["contract"]["cover"]["ids"], ["I-001", "I-002"])
        self.assertEqual(items[0]["checks"], ["origin_label"])

    def test_counts_for_plan(self):
        ctx = self.make_ctx()
        self.assertEqual(registry.fanout_count(ctx, "strategies"), (4, 4))
        self.assertEqual(registry.fanout_count(ctx, "arch_authors"), (3, 4))
        self.assertEqual(registry.fanout_count(ctx, "review_lenses"), (2, 2))


def dispatch_step(fanout="probe", min_ok=1, after=None):
    return {"id": "11.1", "stage": 11, "title": "Probe", "type": "DISPATCH", "fanout": fanout,
            "job": {"kind": "writer"}, "min_ok": min_ok, "after": after or []}


class DispatchTests(tl.EngineTestCase):
    def test_min_ok_parsing(self):
        self.assertEqual(pipeline.parse_min_ok("3/5", 5), 3)
        self.assertEqual(pipeline.parse_min_ok("2/3", 4), 3)
        self.assertEqual(pipeline.parse_min_ok(2, 1), 1)
        self.assertEqual(pipeline.parse_min_ok(None, 4), 4)
        self.assertEqual(pipeline.parse_min_ok(0, 4), 0)

    def test_all_jobs_done_advances(self):
        batch = tl.FakeBatch(outputs=lambda j: "## 1. Walk-through\nx\nRESULT: PENDING\n")
        ctx = self.make_ctx(deps=tl.FakeDeps(batch=batch))
        card = pipeline.advance(ctx, [dispatch_step()], 60)
        self.assertEqual(card["type"], "DONE")
        self.assertEqual(batch.launched, ["11.1"])
        self.assertEqual(st.step_state(ctx.state, "11.1"), "done")
        self.assertEqual(ctx.state["counters"]["launched"], 1)

    def test_running_job_returns_auto_after_the_wait(self):
        batch = tl.FakeBatch(running={"11.1"})
        ctx = self.make_ctx(deps=tl.FakeDeps(batch=batch))
        builders.build_jobs(ctx, dispatch_step())
        st.set_step(ctx.state, "11.1", "running", jobs=["11.1"], originals=["11.1"])
        card = pipeline.advance(ctx, [dispatch_step()], 10)
        self.assertEqual(card["type"], "AUTO")
        self.assertIn("next", card["then"])
        self.assertIn("--wait-s", card["then"])
        self.assertIsNotNone(card["progress"]["line"])

    def test_failure_uses_a_provisional_fallback(self):
        batch = tl.FakeBatch(fail={"11.1"}, outputs=lambda j: "text\nRESULT: PENDING\n")
        ctx = self.make_ctx(deps=tl.FakeDeps(batch=batch))
        card = pipeline.advance(ctx, [dispatch_step()], 60)
        self.assertEqual(card["type"], "DONE")
        self.assertEqual(batch.launched, ["11.1", "11.1-fb-claude-alt"])
        fb = textio.read_json(os.path.join(ctx.run_dir, "jobs", "11.1-fb-claude-alt.json"))
        self.assertTrue(fb["provisional"])
        self.assertEqual(fb["out"], "09_PROBE.md")
        self.assertEqual(ctx.state["provisional"][0]["actual"], "claude-alt")
        self.assertTrue(any("PROVISIONAL claude-alt" in n for n in ctx.state["notes"]))

    def test_exhausted_fallbacks_block_with_fixes(self):
        batch = tl.FakeBatch(fail=lambda j: True)
        ctx = self.make_ctx(deps=tl.FakeDeps(batch=batch))
        card = pipeline.advance(ctx, [dispatch_step()], 60)
        self.assertEqual(card["type"], "BLOCKED")
        self.assertIn("0 of 1", card["say"])
        self.assertTrue(any("doctor" in f for f in card["fix"]))
        self.assertTrue(any("redo" in f for f in card["fix"]))
        self.assertEqual(st.step_state(ctx.state, "11.1"), "blocked")
        # the next call retries the blocked step
        batch.fail = set()
        batch.outputs = lambda j: "text\nRESULT: PENDING\n"
        card = pipeline.advance(ctx, [dispatch_step()], 60)
        self.assertEqual(card["type"], "DONE")

    def test_min_ok_allows_partial_success(self):
        batch = tl.FakeBatch(fail=lambda j: j["id"].startswith("4.2-S5") or j["id"].startswith("4.2-S3"),
                             outputs=lambda j: "### %s-01 t\n- Pitch: p\n- Mechanism: m\n- Fails if: f\n" %
                             j["contract"].get("prefix", "S"))
        ctx = self.make_ctx(deps=tl.FakeDeps(batch=batch), families=("claude",))
        step = {"id": "4.2", "stage": 4, "title": "Diverge", "type": "DISPATCH", "fanout": "strategies",
                "job": {"kind": "generator"}, "min_ok": "2/4"}
        card = pipeline.advance(ctx, [step], 60)
        self.assertEqual(card["type"], "DONE")
        self.assertIn("2/4 ok", ctx.state["steps"]["4.2"]["note"])

    def test_dead_worker_relaunch_limit(self):
        batch = tl.FakeBatch(dead={"11.1"})
        ctx = self.make_ctx(deps=tl.FakeDeps(batch=batch))
        card = pipeline.advance(ctx, [dispatch_step()], 5)
        self.assertEqual(card["type"], "AUTO")
        batch.relaunches["11.1"] = 3
        card = pipeline.advance(ctx, [dispatch_step()], 5)
        self.assertEqual(card["type"], "BLOCKED")
        self.assertIn("Your agent stops background work before model calls finish", card["say"])
        self.assertTrue(any("run --continue" in f for f in card["fix"]))

    def test_budget_gate_guided_and_blocked_full_auto(self):
        ctx = self.make_ctx(deps=tl.FakeDeps(batch=tl.FakeBatch()))
        ctx.state["budget"]["max_calls"] = 1
        ctx.state["counters"]["launched"] = 1
        card = pipeline.advance(ctx, [dispatch_step()], 5)
        self.assertEqual(card["type"], "HUMAN")
        self.assertEqual(card["gate"], "GB")
        card = pipeline.answer_gate(ctx, [dispatch_step()], "GB", {"reply": "raise to 50"})
        self.assertIn(card["type"], ("AUTO", "DONE"))  # answer continues with wait 0
        card = pipeline.advance(ctx, [dispatch_step()], 5)
        self.assertEqual(card["type"], "DONE")
        self.assertEqual(ctx.state["budget"]["max_calls"], 50)
        fa = self.make_ctx(autopilot="full-auto", run_name="fa", deps=tl.FakeDeps(batch=tl.FakeBatch()))
        fa.state["budget"]["max_calls"] = 1
        fa.state["counters"]["launched"] = 1
        card = pipeline.advance(fa, [dispatch_step()], 5)
        self.assertEqual(card["type"], "BLOCKED")
        self.assertIn("call cap", card["say"])

    def test_host_batch_card(self):
        ctx = self.make_ctx(deps=tl.FakeDeps(batch=tl.FakeBatch()))
        ctx.state["families"]["claude"]["backend"] = "host"
        card = pipeline.advance(ctx, [dispatch_step()], 5)
        self.assertEqual(card["type"], "HOST_BATCH")
        job = card["jobs"][0]
        self.assertEqual(sorted(job), ["id", "out", "prompt_file", "tools"])
        self.assertTrue(job["prompt_file"].endswith("prompts/11.1.host.md"))
        self.assertIn("next", card["then"])
        # the host writes the output; the engine validates it and moves on
        textio.write_text_atomic(job["out"], "## 1. Walk-through\nx\n## 2. Riskiest assumption\ny\n## 3. Probe "
                                             "design\nz\n## 4. Kill criterion\nw\nRESULT: PENDING\n")
        card = pipeline.advance(ctx, [dispatch_step()], 5)
        self.assertEqual(card["type"], "DONE")
        meta = textio.read_json(job["out"] + ".meta.json")
        self.assertEqual(meta["backend"], "host")
        self.assertEqual(meta["status"], "ok")

    def test_prelaunch_during_the_gut_pick(self):
        batch = tl.FakeBatch(running=set())
        ctx = self.make_ctx(deps=tl.FakeDeps(batch=batch))
        ctx.state["finalists"] = ["I-001", "I-002"]
        steps = [{"id": "9.5", "stage": 9, "title": "Gut pick", "type": "HUMAN", "gate": "G8a", "prelaunch": ["11.1"],
                  "prelaunch_when": ["!hands_on"]}, dispatch_step()]
        card = pipeline.advance(ctx, steps, 5)
        self.assertEqual(card["type"], "HUMAN")
        self.assertEqual(batch.launched, ["11.1"])  # judges run sealed while the human answers

    def test_crash_hook(self):
        batch = tl.FakeBatch(outputs=lambda j: "text\nRESULT: PENDING\n")
        ctx = self.make_ctx(deps=tl.FakeDeps(batch=batch))
        with mock.patch.dict(os.environ, {"UB_TEST_CRASH_AT": "11.1"}), \
                mock.patch.object(pipeline.os, "_exit", side_effect=SystemExit(99)):
            with self.assertRaises(SystemExit):
                pipeline.advance(ctx, [dispatch_step()], 60)
        self.assertNotEqual(st.step_state(ctx.state, "11.1"), "done")


class CliTests(tl.EngineTestCase):
    def test_parse_text(self):
        p = ub.parse_text("quick private software full-auto add offline sync")
        self.assertEqual((p["mode"], p["variant"], p["autopilot"], p["private"]), ("quick", "software", "full-auto",
                                                                                    True))
        self.assertEqual(p["rest"], "add offline sync")
        self.assertEqual(ub.parse_text("continue")["command"], "continue")
        self.assertEqual(ub.parse_text("deep learning for nurses")["rest"], "learning for nurses")
        self.assertEqual(ub.parse_text("proposal a shared ledger")["rest"], "a shared ledger")

    def test_infer_variant(self):
        self.assertEqual(ub.infer_variant("improve onboarding activation"), "growth")
        self.assertEqual(ub.infer_variant("a name for my bakery"), "naming")
        self.assertEqual(ub.infer_variant("fix the api bug", cwd=self.project), "product" if False else "general")
        self.assertEqual(ub.infer_variant("a SaaS for dentists"), "product")
        os.makedirs(os.path.join(self.project, ".git"))
        textio.write_text_atomic(os.path.join(self.project, "app.py"), "x = 1\n")
        self.assertEqual(ub.infer_variant("fix the api bug", cwd=self.project), "software")

    def test_component_map(self):
        m = ub.component_map("mattpocock-skills:grilling compound-engineering:ce-ideate,bmad-brainstorming")
        self.assertEqual(m["grilling"], "mattpocock-skills:grilling")
        self.assertEqual(m["ce_ideate"], "compound-engineering:ce-ideate")
        self.assertEqual(m["bmad_brainstorming"], "bmad-brainstorming")
        self.assertIsNone(m["domain_modeling"])

    def run_ub(self, *args, **kw):
        out = io.StringIO()
        with mock.patch.object(sys, "stdout", out):
            rc = ub.main(list(args), deps=kw.get("deps"))
        return rc, out.getvalue()

    def test_version_and_usage(self):
        rc, out = self.run_ub("--version")
        self.assertEqual((rc, out), (0, "ub.py %s\n" % _KIT_V))
        err = io.StringIO()
        with mock.patch.object(sys, "stderr", err):
            rc, out = self.run_ub("answer")
        self.assertEqual(rc, 2)

    def test_init_prints_the_g0_card_and_plan(self):
        deps = tl.FakeDeps(detect=tl.fake_detect())
        rc, out = self.run_ub("init", "--host", "claude-code", "--text", "quick shift-swap app for nurses",
                              "--root", self.project, "--no-preflight", "--json", deps=deps)
        self.assertEqual(rc, 0)
        card = json.loads(out)
        self.assertEqual(card["type"], "HUMAN")
        self.assertEqual(card["gate"], "G0")
        self.assertEqual(card["ub"], _KIT_V)
        for key in ("run", "runner", "type", "step", "stage", "gate", "say", "progress", "show", "show_file",
                    "answer_file", "answer_template", "answer_cmd", "default_answer", "error", "task", "jobs", "then",
                    "next_wait_s", "fix", "notes"):
            self.assertIn(key, card)
        self.assertIn("Topic: shift-swap app for nurses", card["show"])
        self.assertEqual(card["next_wait_s"], 540)
        state = st.load(card["run"])
        self.assertEqual(state["mode"], "quick")
        self.assertEqual(state["variant"], "product")
        self.assertEqual(state["host"], {"agent": "claude-code", "family": "claude", "family_source": "default"})
        self.assertEqual(json.loads(out)["run"], textio.to_posix(card["run"]))
        # the same card is kept in .ub/last_card.json
        self.assertEqual(textio.read_json(os.path.join(card["run"], ".ub", "last_card.json"))["gate"], "G0")
        # plan preview
        rc, out = self.run_ub("plan", "--mode", "standard", "--variant", "product", "--families", "claude,gpt",
                              "--json")
        plan = json.loads(out)
        self.assertLessEqual(plan["calls"]["min"], plan["calls"]["expected"])
        self.assertLessEqual(plan["calls"]["expected"], plan["calls"]["max"])

    def test_empty_topic_asks_for_one(self):
        deps = tl.FakeDeps(detect=tl.fake_detect())
        rc, out = self.run_ub("init", "--host", "codex", "--text", "", "--root", self.project, "--no-preflight",
                              "--json", deps=deps)
        card = json.loads(out)
        self.assertEqual(card["gate"], "G0")
        self.assertEqual(card["next_wait_s"], 100)
        rc, out = self.run_ub("answer", card["run"], "G0", "--choice", "go", "--json", deps=deps)
        again = json.loads(out)
        self.assertEqual(again["gate"], "G0")
        self.assertIn("topic", again["error"])

    def test_blocked_card_on_missing_run(self):
        rc, out = self.run_ub("next", os.path.join(self.tmp, "nope"), "--json")
        self.assertEqual(rc, 0)
        self.assertEqual(json.loads(out)["type"], "BLOCKED")


@unittest.skipUnless(tl.stubs_available(), "B4 stubs or B2 bs.py missing")
class InProcessRunTests(tl.EngineTestCase):
    def test_guided_protocol_with_scripted_choices(self):
        ctx = self.make_ctx(mode="standard", autopilot="guided", deps=tl.stub_deps())
        st.set_step(ctx.state, "0.1", "done")
        chosen = {}

        def g8b(card):
            ids = re.findall(r"\bI-\d{3}\b", card["show"])
            sug = re.search(r"Suggested by rule; you decide: (I-\d{3})", card["show"]).group(1)
            pick = [i for i in ids if i != sug][0]
            chosen["id"] = pick
            return {"reply": "%s because night staff already trust it" % pick}
        trace = []
        card = tl.drive(ctx, answers={"G8b": g8b, "G11": {"reply": "B"}, "G2": {"reply": "defaults"},
                                      "G13": {"reply": "approve"}, "G14": {"reply": "no"}}, trace=trace)
        self.assertEqual(card["type"], "DONE", card.get("say"))
        dec = ctx.read("08_DECISION.md")
        self.assertIn(chosen["id"], dec.split("\n")[1] if dec.startswith("#") else dec)
        self.assertIn("night staff already trust it", dec)
        self.assertEqual(ctx.state["choice"]["arch"], "B")
        self.assertIn("candidate B", ctx.read("10_ARCHITECTURE/README.md"))
        self.assertTrue(ctx.state["signed_off"])
        self.assertIn("status: accepted", ctx.read(os.path.relpath(sorted(
            __import__("glob").glob(ctx.path("10_ARCHITECTURE", "adr", "*.md")))[0], ctx.run_dir)))
        gates_asked = [g for t, s, g in trace if t == "HUMAN"]
        self.assertEqual(gates_asked, ["G0", "G2", "G8a", "G8b", "G11", "G13", "G14"])
        self.assertTrue(ctx.exists("12_HANDOFF.md"))
        self.assertTrue(ctx.exists("11_PROPOSAL/index.html"))
        self.assertIn("APPROVED", ctx.read("11_PROPOSAL/PROPOSAL.md"))

    def test_full_auto_is_stamped(self):
        ctx = tl.full_auto_ctx(self, mode="quick")
        card = tl.drive(ctx)
        self.assertEqual(card["type"], "DONE", card.get("say"))
        for gid, g in ctx.state["gates"].items():
            self.assertEqual(g["by"], "auto", gid)
        self.assertIn("AUTOPILOT DRAFT", ctx.read("11_PROPOSAL/PROPOSAL.md"))
        self.assertIn("AUTO-DECISION", ctx.read("08_DECISION.md"))
        self.assertIn("100%", ctx.read("PROGRESS.md"))
        self.assertTrue(ctx.exists("QUICK_DECISION.md"))
        self.assertIn("Milestone 0", ctx.read("11_PROPOSAL/PROPOSAL.md"))

    def test_changes_loop_and_switch(self):
        ctx = self.make_ctx(mode="quick", autopilot="guided", deps=tl.stub_deps())
        st.set_step(ctx.state, "0.1", "done")
        seen = {"g13": 0}

        def g13(card):
            seen["g13"] += 1
            return {"reply": "changes: tighten section 7"} if seen["g13"] == 1 else {"reply": "approve"}
        card = tl.drive(ctx, answers={"G13": g13})
        self.assertEqual(card["type"], "DONE", card.get("say"))
        self.assertEqual(seen["g13"], 2)
        self.assertEqual(ctx.state["user_changes"], "tighten section 7")
        self.assertTrue(ctx.exists("11_PROPOSAL/review/resolution.md"))


if __name__ == "__main__":
    unittest.main()
