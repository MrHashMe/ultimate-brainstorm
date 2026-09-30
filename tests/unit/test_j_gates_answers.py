"""Phase J (JA-gates-answers), the gate answers and the cards that hand them back (KIT_SPEC 4.12, 5.7, 6.2, 6.10).

- G4: a rescue reaches the checks, the survivors and bs.py's @checks: the shortlist is rendered from the answer being
  applied (the gate is recorded after it), and the `Rescued:` line holds IDs only, so an ID named in a reason (a K1
  kill) is never rescued with it
- G11: 'go with C', 'yes, B' and 'ok B + steal ...' choose the letter they name; a reply starting with the article
  'a' names no candidate; a choice the host wrote wins over an acceptance the parser only inferred, and an explicit
  choice against an explicit acceptance is asked again
- G11 with every candidate EXCLUDED: the default is the best-scored candidate, with a rule and a note, and the card
  and the pre-mortem say so
- G12: accept / reject name the ADRs by the card's numbers (3, "3", "ADR-0003", "0003-slug"); an unknown ADR or one
  both accepted and rejected is asked again; a status an older kit stored under such a key survives G13 approve
- probe MISSED with no runner-up (or a runner-up its own probe killed): mid-run the run stops before stage 12; after
  the run it re-renders, and the DONE card names the kill and the finalists left to switch to; a switch never makes a
  K6-killed idea the runner-up
- G4 card: a FLAGged judge is said to be corrected only when the screen lowered it
- G2: an answer after a no-break, ideographic or other non-newline space is read
- G13 and DONE cards render a page an older kit left (no pinned script) before they link it
"""

import contextlib
import io
import json
import os
import re
import sys
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fixtures", "engine"))
import engine_testlib as tl  # noqa: E402

import bs  # noqa: E402
from ublib import textio  # noqa: E402
from ublib.engine import gates, pipeline, registry, render, render_arch  # noqa: E402
from ublib.engine import state as st  # noqa: E402

sys.path.insert(0, tl.SCRIPTS)
import ub  # noqa: E402

IDEAS = "".join("I-%03d | Idea %d | pitch %d | mech %d\n" % (i, i, i, i) for i in range(1, 16))


def done_before(ctx, sid):
    """Every step before `sid` done, so `sid` is the run's current step."""
    for s in pipeline.load_steps():
        if s["id"] == sid:
            return
        st.set_step(ctx.state, s["id"], "done")


class Base(tl.EngineTestCase):
    def run_ub(self, deps, *args):
        out = io.StringIO()
        with mock.patch.object(sys, "stdout", out):
            rc = ub.main([str(a) for a in args], deps=deps)
        text = out.getvalue()
        return rc, (json.loads(text) if text.strip().startswith("{") else text)

    def reload(self, ctx):
        return st.Ctx(ctx.run_dir, st.load(ctx.run_dir), ctx.deps)

    def answer(self, ctx, gid, provided):
        ans, notes, errs = gates.prepare_answer(ctx, gid, provided)
        self.assertEqual(errs, [], (gid, provided))
        return gates.apply(ctx, gid, ans), ans


# ------------------------------------------------------------------------------------------------ G4 rescues

class G4RescueTests(Base):
    def screened(self, name="2026-09-27-j-g4"):
        ctx = self.make_ctx(autopilot="hands-on", families=("claude", "gpt"), run_name=name)
        ctx.write("screen/ideas.md", IDEAS)
        ctx.write_json("screen/shortlist.json", {
            "shortlist": [{"id": "I-001", "reason": "best of its cluster", "score": 4.0},
                          {"id": "I-002", "reason": "best of its cluster", "score": 3.8}],
            "killed_gate": ["I-003"], "floor_fail": ["I-012"], "flagged_gate": []})
        registry.render_shortlist(ctx)  # what step 6.3 leaves
        st.save(ctx.run_dir, ctx.state)
        return ctx

    def check_ids(self, ctx):
        return [j["id"] for j in registry.FANOUTS["shortlist"](ctx, {"id": "7.1"})]

    def test_a_rescue_joins_the_checks_and_the_survivors(self):
        # P1: _apply_g4 rendered 04_SHORTLIST.md before the answer was recorded, so the line always read 'none'
        ctx = self.screened()
        self.answer(ctx, "G4", "rescue I-012: it beats I-004 and I-007 on cost")
        text = ctx.read("04_SHORTLIST.md")
        self.assertIn("Rescued: I-012\n", text)
        self.assertIn("- I-012: it beats I-004 and I-007 on cost", text)
        self.assertEqual(registry.shortlist_ids(ctx), ["I-001", "I-002", "I-012"])
        self.assertEqual(registry.survivors(ctx), ["I-001", "I-002", "I-012"])
        self.assertEqual(self.check_ids(ctx), ["I-001", "I-002", "I-012"])
        ok, note = bs.check_item(ctx.run_dir, "@checks")
        self.assertFalse(ok)
        self.assertIn("I-012", note)
        self.assertNotIn("I-004", note)
        # a later render (step 7.2, G5) keeps the rescue: it reads the recorded answer
        registry.render_shortlist(ctx)
        self.assertIn("Rescued: I-012\n", ctx.read("04_SHORTLIST.md"))

    def test_an_id_in_a_reason_is_never_rescued(self):
        # P2: 'Rescued: I-012 (it is more practical than I-003)' brought the K1-killed I-003 back
        ctx = self.screened()
        self.answer(ctx, "G4", "rescue I-012, it is more practical than I-003")
        self.assertEqual(self.check_ids(ctx), ["I-001", "I-002", "I-012"])
        self.assertNotIn("I-003", registry.finalist_pool(ctx))
        ok, note = bs.check_item(ctx.run_dir, "@checks")
        self.assertNotIn("I-003", note)
        # nor past the 2-rescue cap, nor through a reason that spans lines
        ctx = self.screened("2026-09-27-j-g4-lines")
        self.answer(ctx, "G4", {"rescue": [{"id": "I-012", "reason": "better than I-003, I-004 and I-005\n"
                                                                     "Rescued: I-006"}]})
        self.assertEqual(registry.shortlist_ids(ctx), ["I-001", "I-002", "I-012"])
        self.assertIn("- I-012: better than I-003, I-004 and I-005 Rescued: I-006", ctx.read("04_SHORTLIST.md"))

    def test_a_line_an_older_kit_wrote_counts_only_its_ids(self):
        ctx = self.screened()
        ctx.write("04_SHORTLIST.md", "# Shortlist\n\nRescued: I-012 (it is more practical than I-003 (the cheap one)), "
                                     "I-004 (rescued by the user)\n")
        self.assertEqual(registry.shortlist_ids(ctx), ["I-001", "I-002", "I-012", "I-004"])

    def test_the_engine_checks_the_rescued_idea(self):
        ctx = self.screened()
        ctx.state["gates"] = {}
        done_before(ctx, "6.4")
        steps = pipeline.load_steps()
        card = pipeline.answer_gate(ctx, steps, "G4", {"reply": "rescue I-012: cheaper than I-003"})
        self.assertIn('rescue I-012 into the shortlist (reason: "cheaper than I-003")', card["error"])  # another ID
        card = pipeline.answer_gate(ctx, steps, "G4", {"reply": "yes"})
        self.assertNotEqual(card.get("gate"), "G4", card.get("error"))
        jobs = st.load(ctx.run_dir)["steps"]["7.1"]["jobs"]
        self.assertEqual(sorted(jobs), ["7.1-I-001", "7.1-I-002", "7.1-I-012"])


# ------------------------------------------------------------------------------------------------ G11

MATRIX = {"leader": "A", "leader_status": "clear", "candidates": [
    {"label": "A", "score": 4.0, "rank": 1, "veto": "none"}, {"label": "B", "score": 3.5, "rank": 2, "veto": "none"},
    {"label": "C", "score": 3.0, "rank": 3, "veto": "none"}], "steal": [{"from": "A", "element": "the cache"}]}


class G11ReplyTests(Base):
    def arch_ctx(self, matrix=None, families=tl.FAMS, autopilot="guided"):
        ctx = self.make_ctx(families=families, autopilot=autopilot, run_name="2026-09-27-j-g11")
        ctx.write_json("10_ARCHITECTURE/candidates/map.json", {"A": {"family": "claude"}, "B": {"family": "gpt"},
                                                               "C": {"family": "kimi"}})
        ctx.write_json("10_ARCHITECTURE/matrix.json", matrix or MATRIX)
        return ctx

    def test_a_reply_that_names_a_letter_chooses_it(self):
        cases = {"go with C": "C", "yes, B": "B", "Ok, C": "C", "y C": "C", "go C": "C", "ok, go with B": "B",
                 "let's go with C": "C", "option B": "B", "choose b": "B", "C please": "C", "I'd take C": "C",
                 "B, because it is cheaper": "B", "c": "C", "architecture C.": "C", "rather than A, B": "B",
                 "Not A. B.": "B"}
        for reply, want in cases.items():
            got = gates.parse_reply("G11", reply)
            self.assertEqual((got.get("choice"), got.get("accept_recommendation")), (want, False), reply)

    def test_a_steal_is_read_with_the_letter(self):
        got = gates.parse_reply("G11", "ok B + steal from A: the cache")
        self.assertEqual((got["choice"], got["steal"]), ("B", [{"from": "A", "element": "the cache"}]))
        self.assertEqual(gates.parse_reply("G11", "B+steal")["steal"], ["*"])
        self.assertEqual(gates.parse_reply("G11", "c + steal a: offline cache")["steal"],
                         [{"from": "A", "element": "offline cache"}])

    def test_acceptance_and_unclear_replies(self):
        for reply in ("ok", "Yes.", "go", "", "accept", "sure!"):
            self.assertEqual(gates.parse_reply("G11", reply), {"accept_recommendation": True}, reply)
        # the article 'a' is no candidate, and no chosen letter (or only a refused one) or a hedge before the letter
        # is unclear: asked again
        for reply in ("a mix of B and C please", "a bit unsure", "a bit unsure; B", "not A", "without A",
                      "e.g. the cache of A and the queue of B"):
            got = gates.parse_reply("G11", reply)
            self.assertNotIn("choice", got, reply)
            self.assertNotIn("accept_recommendation", got, reply)

    def test_the_hosts_choice_wins_over_an_inferred_acceptance(self):
        ctx = self.arch_ctx()
        self.assertFalse(gates.merge_answer("G11", {"reply": "ok", "choice": "C"}, ctx)["accept_recommendation"])
        for provided in ({"reply": "go with C", "choice": "C"}, "go with C", {"reply": "ok", "choice": "C"}):
            _effects, ans = self.answer(ctx, "G11", provided)
            self.assertEqual((ctx.state["choice"]["arch"], ans["choice"]), ("C", "C"), provided)
        _effects, ans = self.answer(ctx, "G11", "ok B + steal from A: the cache")
        self.assertEqual((ctx.state["choice"]["arch"], ans["steal"]), ("B", [{"from": "A", "element": "the cache"}]))
        self.answer(ctx, "G11", "ok")
        self.assertEqual(ctx.state["choice"]["arch"], "A")

    def test_an_explicit_choice_against_an_explicit_acceptance_is_asked_again(self):
        ctx = self.arch_ctx()
        _ans, _notes, errs = gates.prepare_answer(ctx, "G11", {"reply": "go with C", "choice": "C",
                                                                "accept_recommendation": True})
        self.assertEqual(errs, ["You named C and also accepted the suggestion (A): reply the letter you choose, or "
                                "`ok`."])
        _ans, _notes, errs = gates.prepare_answer(ctx, "G11", {"choice": "A", "accept_recommendation": True})
        self.assertEqual(errs, [])
        _ans, _notes, errs = gates.prepare_answer(ctx, "G11", "a mix of B and C")
        self.assertTrue(errs and errs[0].startswith("Reply `ok` for the suggestion or a letter"), errs)


class G11AllExcludedTests(Base):
    QGS = [{"id": "QG1", "name": "Reliability", "weight": 30}, {"id": "QG2", "name": "Privacy", "weight": 25},
           {"id": "QG3", "name": "Latency", "weight": 15}]
    CRITERIA = ["QG1", "QG2", "QG3", "time_to_mvp", "team_fit", "run_cost", "reversibility", "operational_simplicity"]

    def cand(self, label, score):
        return {"label": label, "veto": True, "veto_reason": "violates HC-%s" % label, "sensitivity_points": [],
                "tradeoff_points": [], "scores": [{"criterion": c, "score": score, "reason": "r"}
                                                  for c in self.CRITERIA]}

    def excluded(self, autopilot):
        ctx = self.make_ctx(families=("claude", "gpt", "kimi"), autopilot=autopilot, run_name="2026-09-27-j-" + autopilot)
        st.save(ctx.run_dir, ctx.state)
        ctx.write_json("10_ARCHITECTURE/drivers.json", {"product_goal": "x", "quality_goals": self.QGS})
        ctx.write_json("10_ARCHITECTURE/candidates/map.json", dict(
            (k, {"family": f, "archetype": k, "job": "12.4-" + k}) for k, f in (("A", "claude"), ("B", "gpt"),
                                                                                 ("C", "kimi"))))
        for fam in ("claude", "gpt", "kimi"):
            ctx.write_json("10_ARCHITECTURE/review/judge_%s.out.json" % fam, {
                "candidates": [self.cand("A", 3), self.cand("B", 4), self.cand("C", 2)], "steal": []})
        with contextlib.redirect_stdout(io.StringIO()):
            bs.arch_matrix(ctx.run_dir)
        m = ctx.read_json("10_ARCHITECTURE/matrix.json")
        self.assertIsNone(m["leader"])
        self.assertEqual([c["veto"] for c in m["candidates"]], ["excluded"] * 3)
        return ctx

    def test_the_default_is_the_best_scored_candidate_with_a_rule(self):
        ctx = self.excluded("full-auto")
        label, why = gates.g11_recommendation(ctx)
        self.assertEqual(label, "B")
        self.assertEqual(why, "every candidate is EXCLUDED by vetoes (A: violates HC-A; B: violates HC-B; C: violates "
                              "HC-C): no leader; B has the best weighted score")
        ctx.state.setdefault("choice", {})
        ans = {"accept_recommendation": True}
        gates._apply_g11(ctx, ans, "auto")
        self.assertEqual((ctx.state["choice"]["arch"], ans["rule"]), ("B", why))
        self.assertIn("G11 auto: " + why, ctx.state["notes"])
        self.assertEqual(registry.FANOUTS["premortem"](ctx, {"id": "12.13"})[0]["vars"]["LEADER"], "B")

    def test_the_card_says_no_leader(self):
        ctx = self.excluded("guided")
        self.assertTrue(gates.g11_contested(ctx))
        self.assertTrue(gates.gate_values(ctx, "G11")["ARCH_SUGGESTION"].startswith(
            "B (no leader: every candidate is EXCLUDED); every candidate is EXCLUDED by vetoes"))
        self.answer(ctx, "G11", "ok")
        self.assertEqual(ctx.state["choice"]["arch"], "B")


# ------------------------------------------------------------------------------------------------ G12

ADR = {"context": "c", "options": [{"name": "opt one", "pros": ["p"], "cons": ["c"]},
                                   {"name": "opt two", "pros": ["p"], "cons": ["c"]}],
       "chosen": "opt one", "rationale": "r", "consequences": ["x"], "risks": [], "qg": []}


class G12NumberTests(Base):
    def adrs(self, n=0):
        ctx = self.make_ctx(mode="deep", run_name="2026-09-27-j-g12-%d" % n)
        ctx.write_json("10_ARCHITECTURE/decisions.json", {"adrs": [dict(ADR, title="Use Postgres"),
                                                                   dict(ADR, title="Use a monolith"),
                                                                   dict(ADR, title="Use SMS for alerts")]})
        render_arch.rerender_adrs(ctx)
        return ctx

    def statuses(self, ctx):
        out = {}
        for p in sorted(textio.glob_in(ctx.run_dir, "10_ARCHITECTURE", "adr", "*.md")):
            m = re.search(r"(?im)^status:\s*(\w+)", textio.read_text(p))
            out[os.path.basename(p)[:4]] = m.group(1) if m else "?"
        return out

    def test_the_cards_numbers_name_the_adrs(self):
        # P2: the host filled accept ["1","2"] / reject ["3"] from 'accept 1 2, reject 3': all three stayed
        # proposed, and G13 approve then accepted the rejected one
        self.assertIn("3. Use SMS for alerts", gates._v_g12(self.adrs())["ADR_LIST"])
        for n, (accept, reject) in enumerate(((["1", "2"], ["3"]), ([1, 2], [3]),
                                              (["ADR-0001", "ADR-0002"], ["ADR-0003"]),
                                              (["0001-use-postgres", "2"], ["0003-use-sms-for-alerts"]), ("1, 2", "3"),
                                              ([], ["3"])), 1):
            ctx = self.adrs(n)
            reply = "accept 1 2, reject 3" if accept else "reject 3"
            self.answer(ctx, "G12", {"reply": reply, "accept": accept, "reject": reject})
            want = {"0001": "accepted", "0002": "accepted", "0003": "rejected"} if accept else \
                {"0001": "proposed", "0002": "proposed", "0003": "rejected"}
            self.assertEqual(self.statuses(ctx), want, (accept, reject))
            self.assertEqual(ctx.read_json("10_ARCHITECTURE/adr_status.json"),
                             dict((k, v) for k, v in want.items() if v != "proposed"))
            self.answer(ctx, "G13", {"reply": "approve"})
            self.assertEqual(self.statuses(ctx), {"0001": "accepted", "0002": "accepted", "0003": "rejected"},
                             (accept, reject))

    def test_an_unknown_or_contradictory_adr_is_asked_again(self):
        ctx = self.adrs()
        _ans, _notes, errs = gates.prepare_answer(ctx, "G12", {"accept": ["7"]})
        self.assertEqual(errs, ["ADR 7 does not exist (ADRs: 1, 2, 3)"])
        _ans, _notes, errs = gates.prepare_answer(ctx, "G12", {"accept": ["the first one"]})
        self.assertEqual(errs, ["ADR 'the first one' does not exist (ADRs: 1, 2, 3)"])
        _ans, _notes, errs = gates.prepare_answer(ctx, "G12", "accept 1 3, reject 3")
        self.assertEqual(errs, ["ADR 3 is both accepted and rejected: name it once"])
        ans, _notes, errs = gates.prepare_answer(ctx, "G12", "ok")
        self.assertEqual((errs, ans["accept"]), ([], ["all"]))

    def test_a_status_an_older_kit_stored_survives_the_sign_off(self):
        ctx = self.adrs()
        ctx.write_json("10_ARCHITECTURE/adr_status.json", {"1": "accepted", "2": "accepted", "3": "rejected"})
        self.answer(ctx, "G13", {"reply": "approve"})
        self.assertEqual(self.statuses(ctx), {"0001": "accepted", "0002": "accepted", "0003": "rejected"})
        # and after a 2.1.0 G13 approve stored its default under the number, the user's rejection still wins
        ctx.write_json("10_ARCHITECTURE/adr_status.json", {"3": "rejected", "0003": "accepted", "0001": "accepted"})
        self.answer(ctx, "G13", {"reply": "approve"})
        self.assertEqual(self.statuses(ctx)["0003"], "rejected")


# ------------------------------------------------------------------------------------------------ probe MISSED

class ProbeMissedTests(Base):
    def decided(self, autopilot="hands-on", runner_up=None):
        ctx = self.make_ctx(autopilot=autopilot, run_name="2026-09-27-j-probe")
        ctx.write("screen/ideas.md", IDEAS)
        ctx.state["finalists"] = ["I-001", "I-002", "I-003", "I-004"]
        ctx.state["choice"].update({"idea": "I-001", "runner_up": runner_up})
        ctx.write("09_PROBE.md", "# Probe\n\n## 3. The probe\nAsk 10 nurses to swap a shift.\nRESULT: PENDING\n")
        ctx.write("08_DECISION.md", "# DECISION\n")
        return ctx

    def test_mid_run_the_run_stops_before_the_architecture(self):
        # P2: the second G9 MISSED left the killed idea chosen, and stages 12-13 designed it (24 model calls)
        ctx = self.decided()
        done_before(ctx, "11.2")
        steps = pipeline.load_steps()
        card = pipeline.answer_gate(ctx, steps, "G9", {"reply": "missed: only one nurse swapped"})
        self.assertIn("MISSED: I-001 is killed (K6), and no runner-up is left", card["error"])  # read back (4.12)
        card = pipeline.answer_gate(ctx, steps, "G9", {"reply": "yes"})
        self.assertEqual((card["type"], card["say"]), ("DONE", "Stopped."), card.get("show"))
        state = st.load(ctx.run_dir)
        self.assertEqual((state["status"], state["stopped_reason"]), ("stopped", gates.K6_STOP))
        self.assertEqual(st.step_state(state, "12.1"), "pending")
        self.assertIn("Decision: I-001 Idea 1 - killed by its probe (K6); no runner-up is left", card["show"])
        self.assertIn("Next: choose another finalist (I-002, I-003, I-004), then type `/ultimate-brainstorm switch "
                      "idea <ID>`", card["show"])
        self.assertNotIn("Next: run the probe", card["show"])
        self.assertIn("Killed: I-001 - K6", ctx.read("08_DECISION.md"))
        # `continue` does not lift it; another host is given the command, and a run with no finalist left says so
        ctx.state["host"]["agent"] = "other"
        ctx.state["killed"] = ["I-003"]
        show = pipeline.done_card(ctx, stopped=gates.K6_STOP)["show"]
        self.assertIn('Next: choose another finalist (I-002, I-004), then run: python ub.py switch "%s" --idea <ID>'
                      % textio.to_posix(ctx.run_dir), show)
        ctx.state["decision_log"] += ["Killed: I-002 - K6 (x)", "Killed: I-004 - K6 (x)"]
        self.assertIn("Next: no finalist is left to test", pipeline.done_card(ctx, stopped=gates.K6_STOP)["show"])

    def test_after_the_run_the_documents_are_rendered_again(self):
        ctx = self.decided(autopilot="guided")
        for sid in pipeline.step_ref("probe_rerender"):
            st.set_step(ctx.state, sid, "done")
        effects = gates.probe_result(ctx, "MISSED", "1 of 10")
        self.assertEqual(effects[-1], ("reset", pipeline.step_ref("probe_rerender")))
        self.assertNotIn("stop", [e[0] for e in effects])

    def test_a_runner_up_its_own_probe_killed_is_not_chosen_again(self):
        # NEW-I-HA-engine-flow-2: a K6-killed idea became the runner-up after a switch, and a later MISSED chose it
        ctx = self.decided(autopilot="guided", runner_up="I-002")
        ctx.state["decision_log"] = ["Killed: I-002 - K6 (the pre-registered probe missed)"]
        effects = gates.probe_result(ctx, "MISSED", "no")
        self.assertEqual(ctx.state["choice"]["idea"], "I-001")
        self.assertNotIn("supersede", [e[0] for e in effects])

    def test_a_switch_never_makes_a_killed_idea_the_runner_up(self):
        ctx = self.decided(autopilot="guided")
        ctx.state["decision_log"] = ["Killed: I-001 - K6 (the pre-registered probe missed)"]
        ctx.state.update({"status": "stopped", "stopped_reason": gates.K6_STOP})
        pipeline.switch_idea(ctx, pipeline.load_steps(), "I-003")
        self.assertEqual(ctx.state["choice"], dict(ctx.state["choice"], idea="I-003", runner_up=None))
        self.assertEqual(ctx.state["status"], "active")
        self.assertNotIn("stopped_reason", ctx.state)
        # a runner-up a K6 kill left behind (an older kit's switch) is cleared too
        ctx.state["choice"]["runner_up"] = "I-001"
        pipeline.switch_idea(ctx, pipeline.load_steps(), "I-004")
        self.assertEqual((ctx.state["choice"]["idea"], ctx.state["choice"]["runner_up"]), ("I-004", "I-003"))
        ctx.state["decision_log"].append("Killed: I-003 - K6 (the pre-registered probe missed)")
        pipeline.switch_idea(ctx, pipeline.load_steps(), "I-002")
        self.assertEqual((ctx.state["choice"]["idea"], ctx.state["choice"]["runner_up"]), ("I-002", "I-004"))
        ctx.state["choice"]["runner_up"] = "I-003"
        pipeline.switch_idea(ctx, pipeline.load_steps(), "I-004")
        self.assertEqual(ctx.state["choice"]["runner_up"], "I-002")


@unittest.skipUnless(tl.stubs_available(), "B4 stubs or B2 bs.py missing")
class ProbeMissedFlowTests(Base):
    def test_a_second_missed_after_the_run_says_the_idea_is_dead(self):
        ctx = tl.full_auto_ctx(self, mode="quick")
        self.assertEqual(tl.drive(ctx)["type"], "DONE")
        first = st.load(ctx.run_dir)["choice"]
        rc, card = self.run_ub(ctx.deps, "probe-result", ctx.run_dir, "MISSED", "--json")
        self.assertEqual(rc, 0, card)
        ctx = self.reload(ctx)
        self.assertEqual(tl.drive(ctx)["type"], "DONE")
        ctx = self.reload(ctx)
        second = ctx.state["choice"]["idea"]
        self.assertEqual((second, ctx.state["choice"]["runner_up"]), (first["runner_up"], None))
        rc, card = self.run_ub(ctx.deps, "probe-result", ctx.run_dir, "MISSED", "--json")
        self.assertEqual(rc, 0, card)
        ctx = self.reload(ctx)
        card = tl.drive(ctx)
        self.assertEqual(card["type"], "DONE")
        self.assertNotIn("run the probe", card["show"])
        self.assertIn("Decision: %s " % second, card["show"])
        self.assertIn("killed by its probe (K6); no runner-up is left", card["show"])
        ctx = self.reload(ctx)
        self.assertIn("Killed: %s - K6" % second, ctx.read("11_PROPOSAL/PROPOSAL.md"))
        # a third MISSED (the same result for the same idea) changes nothing
        rc, card = self.run_ub(ctx.deps, "probe-result", ctx.run_dir, "MISSED", "--json")
        self.assertEqual(st.load(ctx.run_dir)["choice"]["idea"], second)


# ------------------------------------------------------------------------------------------------ G4 card audit

class G4CardAuditTests(Base):
    def card(self, shortlist):
        ctx = self.make_ctx(run_name="2026-09-27-j-g4-card")
        ctx.write_json("screen/shortlist.json", shortlist)
        return gates.gate_values(ctx, "G4")["SUMMARY"]

    ROW = {"judge": "claude", "gap": 1.0, "se": 1.211, "n": 6, "base": 3, "vs": ["gpt"], "flag": True}

    def test_a_flagged_gap_within_noise_is_not_called_corrected(self):
        summary = self.card({"shortlist": [], "lowered": {}, "own_origin_gap": [self.ROW]})
        self.assertIn("- claude: own-origin gap +1.00 (not corrected: within noise, SE 1.21; check whether the "
                      "shortlist leans to its vendor)", summary)
        self.assertNotIn("lowered", summary)

    def test_a_corrected_gap_names_the_correction(self):
        summary = self.card({"shortlist": [], "lowered": {"claude": 1.5},
                             "own_origin_gap": [dict(self.ROW, gap=1.5, se=0.62)]})
        self.assertIn("- claude: own-origin gap +1.50 (its own-vendor scores were lowered by 1.50)", summary)

    def test_a_shortlist_an_older_kit_wrote_corrected_nothing(self):
        # 2.0.3: report only, no `lowered` key
        row = dict(self.ROW, gap=0.8)
        row.pop("se")
        summary = self.card({"shortlist": [], "own_origin_gap": [row]})
        self.assertIn("- claude: own-origin gap +0.80 (not corrected; check whether the shortlist leans to its "
                      "vendor)", summary)

    def test_the_real_screen_within_noise(self):
        ctx = self.make_ctx(families=("claude", "gpt"), run_name="2026-09-27-j-g4-screen")
        ctx.state["seats"]["screen_judges"] = ["claude", "gpt"]
        st.save(ctx.run_dir, ctx.state)
        ids = ["I-%03d" % n for n in range(1, 16)]
        crit = {"Value": 30, "Feasibility": 25, "Fit": 20, "Distinctiveness": 15, "Evidence": 10}
        own, base = [5, 3, 4, 3, 5, 4], [3, 5, 1]
        claude = dict((i, own[n] if n < 6 else 3 if n < 12 else base[n - 12]) for n, i in enumerate(ids))

        def rec(i, v):
            return {"id": i, "g1": True, "g2": True, "g3": True, "c": dict((k, v) for k in crit), "risk": "r"}
        ctx.write_json("criteria.json", crit)
        ctx.write_json("origins.json", dict((i, "claude" if n < 6 else "gpt" if n < 12 else "human")
                                            for n, i in enumerate(ids)))
        ctx.write_json("clusters.json", dict((i, "c%d" % (n % 6)) for n, i in enumerate(ids)))
        ctx.write("screen/ideas.md", "".join("%s | t | p | m\n" % i for i in ids))
        ctx.write_json("screen/claude.out.json", {"scores": [rec(i, claude[i]) for i in ids]})
        ctx.write_json("screen/gpt.out.json", {"scores": [rec(i, 3) for i in ids]})
        with contextlib.redirect_stdout(io.StringIO()):
            bs.screen(ctx.run_dir)
        self.assertEqual(ctx.read_json("screen/shortlist.json")["lowered"], {})
        summary = gates.gate_values(ctx, "G4")["SUMMARY"]
        self.assertIn("- claude: own-origin gap +1.00 (not corrected: within noise, SE 1.21", summary)
        self.assertNotIn("were lowered", summary)


# ------------------------------------------------------------------------------------------------ G2 spaces

class G2SpaceTests(unittest.TestCase):
    def answers(self, text):
        return [(a["q"], a["a"]) for a in gates.parse_reply("G2", text)["answers"]]

    def test_a_non_newline_space_separates_an_answer(self):
        for sp in (" ", "　", " ", "\x0b", "\t", " "):
            self.assertEqual(self.answers("1.%sICU nurses\n2)%sweekly" % (sp, sp)), [("1", "ICU nurses"),
                                                                                     ("2", "weekly")], repr(sp))
        self.assertEqual(self.answers("1 : infirmiers de nuit\n2 : chaque semaine"),
                         [("1", "infirmiers de nuit"), ("2", "chaque semaine")])
        self.assertEqual(self.answers(" 1. a\n 2. b"), [("1", "a"), ("2", "b")])
        got = gates.parse_reply("G2", "1) ICU nurses only\n2) weekly\nok for the rest")
        self.assertEqual((len(got["answers"]), got["accept_defaults"]), (2, True))

    def test_an_answer_still_never_reaches_into_the_next_line(self):
        self.assertEqual(self.answers("4:\n5: x"), [("5", "x")])
        self.assertEqual(self.answers("4:\r\n5: x"), [("5", "x")])
        self.assertEqual(self.answers("4: \n5: x"), [("5", "x")])


class LinearReplyTests(unittest.TestCase):
    """The reply parser stays linear (#34) with the wider G2 spaces and the new G11 reading."""

    def assert_fast(self, gid, text):
        t0 = time.perf_counter()
        out = gates.parse_reply(gid, text)
        self.assertLess(time.perf_counter() - t0, 1.0, (gid, text[:20]))
        return out

    def test_space_floods(self):
        for sp in (" ", " ", "　"):
            self.assertEqual(self.assert_fast("G2", "x\n" + (sp + "\n") * 40000 + "1. yes")["answers"],
                             [{"q": "1", "a": "yes"}])
            self.assertEqual(self.assert_fast("G2", sp * 40000 + "1" + sp * 40000 + ":" + sp * 40000)["answers"], [])
        ws = " " * 40000
        for reply in ("ok" + ws + "x", "a" + ws + "x", "steal" + ws + "from" + ws + "x", "go" + ws + "with" + ws + "x",
                      "let's go" + ws + "x", "ok," + ws + "candidate" + ws + "x", "+" + ws + "steal"):
            self.assertNotIn("choice", self.assert_fast("G11", reply))
        self.assertEqual(self.assert_fast("G11", "C" + ws + "please")["choice"], "C")


# ------------------------------------------------------------------------------------------------ old pages

OLD_PAGE = ('<!doctype html>\n<html><head><meta charset="utf-8"><title>Proposal</title></head><body>\n'
            '<pre class="mermaid">flowchart LR\n  A --> B</pre>\n<script type="module">\n'
            'const m = await import("https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.esm.min.mjs");\n'
            'm.default.initialize({startOnLoad: false, securityLevel: "strict"});\n</script>\n</body></html>\n')


class OldPageCardTests(Base):
    def proposal(self, privacy=None):
        ctx = self.make_ctx(privacy=privacy, run_name="2026-09-27-j-page")
        ctx.write("10_ARCHITECTURE/README.md", "# Architecture\n")
        ctx.write("11_PROPOSAL/PROPOSAL.md", "# Proposal: a\n\n## 1. Executive Summary\na\n")
        ctx.write("11_PROPOSAL/ONE-PAGER.md", "# One-pager\n\n## Problem\na\n")
        ctx.write("11_PROPOSAL/index.html", OLD_PAGE)
        return ctx

    def page(self, ctx):
        return ctx.read("11_PROPOSAL/index.html")

    def test_the_g13_card_renders_it_again_before_it_links_it(self):
        ctx = self.proposal(privacy={"web": False, "vendors": False})
        show = gates.display(ctx, "G13")
        self.assertIn(textio.to_posix(ctx.path("11_PROPOSAL/index.html")), show)
        self.assertNotIn("<script", self.page(ctx).lower())
        ctx = self.proposal()
        gates.display(ctx, "G13")
        self.assertIn('integrity="%s"' % render.MERMAID_SRI, self.page(ctx))
        self.assertNotIn("mermaid@11/", self.page(ctx))

    def test_the_done_card_renders_it_again_before_it_links_it(self):
        for stopped in (None, "user"):
            ctx = self.proposal(privacy={"web": False})
            card = pipeline.done_card(ctx, stopped=stopped)
            self.assertIn("pack", card["links"])
            self.assertNotIn("<script", self.page(ctx).lower(), stopped)

    def test_a_pinned_page_in_a_run_that_turned_web_off_loses_its_script(self):
        ctx = self.proposal()
        render.render_pack(ctx)
        self.assertIn('integrity="%s"' % render.MERMAID_SRI, self.page(ctx))
        ctx.state["privacy"]["web"] = False
        self.assertFalse(render.page_is_current(ctx))
        gates.display(ctx, "G13")
        self.assertNotIn("<script", self.page(ctx).lower())

    def test_a_page_that_cannot_be_rendered_never_blocks_the_card(self):
        ctx = self.proposal()
        with mock.patch.object(render, "render_pack", side_effect=pipeline.EngineError("template missing")):
            show = gates.display(ctx, "G13")
            card = pipeline.done_card(ctx)
        self.assertIn("Files:", show)
        self.assertIn("pack", card["links"])


if __name__ == "__main__":
    unittest.main()
