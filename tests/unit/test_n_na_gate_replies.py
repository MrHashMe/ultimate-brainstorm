"""Phase N (NA-gate-replies): refusals, deferrals and wordless replies at every free-text gate (KIT_SPEC 4.12, 6.10).

- a clause of refusal words alone refuses what the clause before it named: 'B? no.' at G11, 'Publish? No.' at G14,
  'Passed? Not really' at G9, 'raise to 300? no.' at GB, 'kill I-003? no.' at G5, 'reject 3? no' at G12
- stop, wait, hold, later, cancel, defer, postpone and pause refuse like `no`: 'publish? not yet', 'cancel publishing'
- a paid, irreversible or budget action is taken only from an affirmative clause that names it; anything else is asked
  again with the reason (G13 'stop' and "don't approve", G10 'not yet', G12 'accept 1 2, 3 is wrong')
- G9 / GX read a keyword with a note ('missed: we did not reach 10 sign-ups'); `miss` / `failed` name `missed`
- G10 / G2c / G13 take everyday confirmations ("Yes, that's correct", 'approve it', 'I approve') as no change
- a reply with no word at all ('?', '...', an emoji) is asked again, never the suggested architecture
- G0: a refusal at the kickoff is no seed, and a refusal at the v1-run offer stops the run
- GB: a number too long to be a cap is asked again, never an internal error; G11 stays linear in one-letter words
"""

import os
import sys
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fixtures", "engine"))
import engine_testlib as tl  # noqa: E402

from ublib import textio  # noqa: E402
from ublib.engine import gates, pipeline, render_arch  # noqa: E402
from ublib.engine import state as st  # noqa: E402

MATRIX = {"leader": "A", "leader_status": "clear", "candidates": [
    {"label": "A", "score": 4.0, "rank": 1, "veto": "none"}, {"label": "B", "score": 3.5, "rank": 2, "veto": "none"},
    {"label": "C", "score": 3.0, "rank": 3, "veto": "none"}]}
ADR = {"context": "c", "options": [{"name": "opt one", "pros": ["p"], "cons": ["c"]},
                                   {"name": "opt two", "pros": ["p"], "cons": ["c"]}],
       "chosen": "opt one", "rationale": "r", "consequences": ["x"], "risks": [], "qg": []}


def parse(gid, reply, why=None):
    return gates.parse_reply(gid, reply, None, why if why is not None else [])


class Base(tl.EngineTestCase):
    n = 0

    def ctx(self, **kw):
        Base.n += 1
        return self.make_ctx(run_name="2026-09-27-n-na-%d" % Base.n, **kw)

    def prepared(self, ctx, gid, reply):
        ans, _notes, errs = gates.prepare_answer(ctx, gid, {"reply": reply})
        return ans, errs

    def answer(self, ctx, gid, reply):
        ans, errs = self.prepared(ctx, gid, reply)
        self.assertEqual(errs, [], (gid, reply))
        return gates.apply(ctx, gid, ans), ans

    def asked_again(self, ctx, gid, reply):
        _ans, errs = self.prepared(ctx, gid, reply)
        self.assertTrue(errs, (gid, reply))
        return errs[0]

    def arch_ctx(self):
        ctx = self.ctx()
        ctx.write_json("10_ARCHITECTURE/candidates/map.json", {"A": {"family": "claude"}, "B": {"family": "gpt"},
                                                               "C": {"family": "kimi"}})
        ctx.write_json("10_ARCHITECTURE/matrix.json", MATRIX)
        ctx.state["choice"] = {"idea": "I-001", "arch": None, "runner_up": None}
        return ctx

    def loops(self, ctx, name):
        return (ctx.state.get("counters") or {}).get(name, 0)


# ------------------------------------------------------------------------------------------------ G11

class G11Tests(Base):
    def test_a_letter_refused_by_the_next_clause_is_no_choice(self):
        # NEW-K-JA-1 / G11 letter-then-no: each became the architecture
        ctx = self.arch_ctx()
        for reply in ("B? no.", "B? No way.", "A - no", "B. No.", "C? nope, too slow", "C? Not really."):
            self.assertIn("names %s in a negation" % reply[0], self.asked_again(ctx, "G11", reply), reply)
        self.assertIn("takes the suggestion and also names B", self.asked_again(ctx, "G11", "ok. B? no."))
        self.assertIsNone(ctx.state["choice"]["arch"])
        self.assertEqual(parse("G11", "No, B.").get("choice"), "B")

    def test_a_wordless_reply_is_asked_again(self):
        # the leader was taken for '?', '...', an emoji, '-'
        ctx = self.arch_ctx()
        for reply in ("?", "???", "...", "\U0001F914", "-", "—"):
            self.assertEqual(parse("G11", reply), {}, ascii(reply))
            self.assertIn("Your reply has no words in it.", self.asked_again(ctx, "G11", reply), ascii(reply))
        self.assertIsNone(ctx.state["choice"]["arch"])
        self.assertEqual(parse("G11", ""), {"accept_recommendation": True})  # an empty reply still accepts

    def test_the_reader_is_linear_in_one_letter_words(self):
        # 'a '*20000 took 9 s, prepare_answer('A '*20000) 19 s
        ctx = self.arch_ctx()
        for text in ("a " * 20000, "A " * 20000, "A. " * 15000, "B? no. " * 6000):
            t0 = time.perf_counter()
            parse("G11", text)
            gates.prepare_answer(ctx, "G11", {"reply": text})
            self.assertLess(time.perf_counter() - t0, 3.0, text[:6])  # the 3 s of the other floods: CI load


# ------------------------------------------------------------------------------------------------ G14

class G14Tests(unittest.TestCase):
    def test_a_refusal_after_the_question_publishes_nothing(self):
        # each wrote the architecture, the ADRs and the proposal into the user's docs/
        for reply in ("Publish? No.", "Publish? Nope.", "publish: no", "Publish -> no", "Publish — no.",
                      "publish? not yet", "Publish? Not now.", "Hold off on publishing", "cancel publishing",
                      "publishing can wait", "publish later, not now", "Publish? No thanks. Handoff: none"):
            self.assertIs(parse("G14", reply).get("publish"), False, reply)
        self.assertEqual(parse("G14", "Publish? No. Handoff: ce"), {"publish": False, "handoff": "ce"})

    def test_a_consent_still_publishes(self):
        for reply, want in (("publish", True), ("publishing is fine", True), ("publish, no handoff", True)):
            self.assertEqual(parse("G14", reply).get("publish"), want, reply)
        self.assertNotIn("publish", parse("G14", "publish the proposal, not the ADRs"))  # asked: the ADRs go too


# ------------------------------------------------------------------------------------------------ G9, GX, G2f, GB

class KeywordTests(Base):
    def test_an_echoed_result_answered_with_a_negative_is_no_result(self):
        # 'Passed? Not really, only 3 of 10' was PASSED and K6 was skipped
        ctx = self.ctx()
        for reply in ("Passed? Not really, only 3 of 10 signed up", "Passed? Sadly not. 3 of 10",
                      "Passed - not really, 3 of 10", "Passed: no, 3 of 10"):
            self.assertIsNone(parse("G9", reply)["result"], reply)
            self.assertIn("names `passed` in a negation", self.asked_again(ctx, "G9", reply), reply)
        self.assertEqual(parse("G9", "Passed? No. Missed: 3 of 10")["result"], "MISSED")

    def test_a_miss_in_other_words_is_no_pass(self):
        ctx = self.ctx()
        for reply in ("passed with 3 of 10, which is a miss", "passed 3 of 10 - that failed the bar",
                      "passed, missed", "passed but it missed"):
            self.assertIsNone(parse("G9", reply)["result"], reply)
            self.assertIn("`missed` and `passed`", self.asked_again(ctx, "G9", reply), reply)
        self.assertIsNone(parse("G9", "passed: 3 of 10, so it did not pass the 6 of 10 bar")["result"])

    def test_a_keyword_with_a_note_is_read(self):
        # the negation in the note re-asked the reply as 'names `missed` in a negation'
        ctx = self.ctx()
        for reply, want in (("missed: we did not reach 10 sign-ups", "MISSED"),
                            ("passed: 12 of 10 needed and no churn", "PASSED"),
                            ("inconclusive: too few visitors, not enough data", "INCONCLUSIVE")):
            self.assertEqual(parse("G9", reply)["result"], want, reply)
            self.assertEqual(self.prepared(ctx, "G9", reply)[1], [], reply)
        for reply in ("stop: this is not worth it", "stop: too expensive", "Continue? No. Stop."):
            self.assertEqual(parse("GX", reply), {"action": "stop"}, reply)
        why = []
        self.assertEqual(parse("GX", "Reframe? Not really.", why), {})
        self.assertEqual(why, ["Your reply names `reframe` in a negation."])
        self.assertEqual(parse("G2f", "Restore? Not really."), {"restore": False})

    def test_a_refused_cap_raises_nothing(self):
        ctx = self.ctx()
        for reply in ("raise to 300? no.", "raise to 500: not more", "raise to 300? not yet"):
            self.assertEqual(parse("GB", reply), {}, reply)
            self.assertIn("in a negation", self.asked_again(ctx, "GB", reply), reply)
        self.assertEqual(parse("GB", "stop: no more requests"), {"stop": True})
        self.assertEqual(parse("GB", "raise to 1,000"), {"raise_to": 1000, "stop": False})

    def test_a_number_too_long_for_a_cap_is_asked_again(self):
        # int() raised 'Exceeds the limit (4300 digits)' out of parse_reply: an internal-error BLOCKED card
        ctx = self.ctx()
        for reply in ("raise to " + "1" * 4400, "1" * 5000, "raise to 1234567890"):
            self.assertEqual(parse("GB", reply), {}, reply[:12])
            self.asked_again(ctx, "GB", reply)


# ------------------------------------------------------------------------------------------------ G10, G2c, G13

class ConfirmationTests(Base):
    def test_g10_and_g2c_confirmations_are_no_correction(self):
        # each was a correction, at G10 a paid 12.2 drivers redo
        for gid in ("G2c", "G10"):
            for reply in ("Yes, that's correct", "That is correct", "Looks right to me", "I agree", "Spot on",
                          "that works", "ok as is", "Exactly", "All correct", "Correct as is"):
                self.assertEqual(parse(gid, reply), {"confirm": True}, (gid, reply))
        ctx = self.ctx(mode="deep")
        effects, _ans = self.answer(ctx, "G10", "I agree")
        self.assertEqual((effects, self.loops(ctx, "g10_loops")), ([], 0))

    def test_a_deferral_or_wordless_reply_at_g10_redoes_nothing(self):
        ctx = self.ctx(mode="deep")
        for reply in ("stop", "not yet", "wait", "No, thanks"):
            self.assertIn("A bare `no` does not say what to correct.", self.asked_again(ctx, "G10", reply), reply)
        self.assertIn("neither confirms nor says what to correct", self.asked_again(ctx, "G10", "Great"))
        for reply in ("?", "..."):
            self.assertIn("Your reply has no words in it.", self.asked_again(ctx, "G10", reply), reply)
            self.assertIn("Your reply has no words in it.", self.asked_again(ctx, "G2c", reply), reply)
        self.assertEqual(self.loops(ctx, "g10_loops"), 0)
        self.assertEqual(parse("G10", "No, the users are nurses."),
                         {"confirm": False, "corrections": "No, the users are nurses."})

    def g13_ctx(self):
        ctx = self.ctx()
        ctx.write_json("10_ARCHITECTURE/candidates/map.json", {"A": {"family": "claude"}, "B": {"family": "gpt"}})
        ctx.state["choice"] = {"idea": "I-001", "arch": "A", "runner_up": None}
        return ctx

    def test_g13_approvals_start_no_change_round(self):
        # each became `changes`: a paid PROPOSAL-FIX redo and one of the two loops
        ctx = self.g13_ctx()
        redo = ("reset", pipeline.step_ref("changes_redo"))
        for reply in ("approve it", "Approve the proposal", "Approve as is", "approve all", "approve everything",
                      "I approve", "Approved as is.", "approve it, thanks", "That's correct", "Looks right"):
            self.assertEqual(parse("G13", reply), {"action": "approve"}, reply)
            effects, _ans = self.answer(ctx, "G13", reply)
            self.assertNotIn(redo, effects, reply)
        self.assertEqual(self.loops(ctx, "g13_loops"), 0)

    def test_g13_replies_that_ask_for_no_change_are_asked_again(self):
        ctx = self.g13_ctx()
        for reply in ("stop", "don't approve", "add a pilot budget? no"):
            self.assertIn("says no without saying what to change", self.asked_again(ctx, "G13", reply), reply)
        self.assertIn("puts the action off", self.asked_again(ctx, "G13", "not yet"))  # a lone deferral (XA)
        for reply in ("Great work", "Nice, ship it", "Well done!", "Excellent.", "Love it"):
            self.assertIn("neither approves nor says what to change", self.asked_again(ctx, "G13", reply), reply)
        self.assertIn("Your reply has no words in it.", self.asked_again(ctx, "G13", "?"))
        self.assertIn("`changes:` needs what to change", self.asked_again(ctx, "G13", "changes: none"))
        self.assertEqual((self.loops(ctx, "g13_loops"), ctx.state.get("user_changes")), (0, None))
        self.assertEqual(parse("G13", "changes: add a pilot budget"),
                         {"action": "changes", "changes": "add a pilot budget"})


# ------------------------------------------------------------------------------------------------ G4, G5, G12

class IdeaAndAdrTests(Base):
    def killed(self, gid, reply):
        ctx = self.ctx()
        ctx.state["k4_candidates"] = ["I-003", "I-007"]
        ctx.state["killed"] = []
        with mock.patch.object(gates.registry, "render_shortlist", lambda *a, **k: None):  # not the subject
            self.answer(ctx, gid, reply)
        return ctx.state.get("killed")

    def test_a_negated_or_postfix_verb_kills_only_what_it_names(self):
        # "I don't want to kill I-003" and 'I-003: kill, I-007: keep' killed the idea the user spared
        for reply, want in (("I don't want to kill I-003", {"kill": [], "keep": ["I-003"]}),
                            ("no need to kill I-003", {"kill": [], "keep": ["I-003"]}),
                            ("I-003: kill, I-007: keep", {"kill": ["I-003"], "keep": ["I-007"]}),
                            ("I-003 kill; I-007 keep", {"kill": ["I-003"], "keep": ["I-007"]}),
                            ("kill I-003? no.", {"kill": [], "keep": []})):
            self.assertEqual(parse("G5", reply), want, reply)
        for reply, want in (("I don't want to confirm I-004", []), ("no need to confirm I-004", []),
                            ("I-004: confirm, I-005: clear", ["I-004"]), ("confirm I-003? no", [])):
            self.assertEqual(parse("G4", reply), {"rescue": [], "confirm_flags": want}, reply)
        self.assertEqual(self.killed("G5", "I don't want to kill I-003"), [])
        self.assertEqual(self.killed("G5", "I-003: kill, I-007: keep"), ["I-003"])
        self.assertNotIn("I-007", self.killed("G5", "kill I-007? no.") or [])

    def adrs(self):
        ctx = self.ctx(mode="deep")
        ctx.write_json("10_ARCHITECTURE/decisions.json", {"adrs": [dict(ADR, title="Use Postgres"),
                                                                   dict(ADR, title="Use a monolith"),
                                                                   dict(ADR, title="Use SMS for alerts")]})
        render_arch.rerender_adrs(ctx)
        return ctx

    def test_g12_carries_no_number_the_next_clause_speaks_against(self):
        # 'accept 1 2, 3 is wrong' accepted 0003; 'reject 3, 2 is fine' rejected 0002
        ctx = self.adrs()
        for reply, n in (("accept 1 2, 3 is wrong", 3), ("accept 1 and 2; 3 looks wrong", 3),
                         ("reject 3, 2 is fine", 2), ("reject 3? no, keep it", 3)):
            self.assertEqual(parse("G12", reply), {}, reply)
            self.assertIn("ADR %d where it is unclear" % n, self.asked_again(ctx, "G12", reply), reply)
        self.assertEqual(parse("G12", "reject 3, 4"), {"accept": [], "reject": ["0003", "0004"]})
        self.assertEqual(parse("G12", "accept 1 2, reject 3"), {"accept": ["0001", "0002"], "reject": ["0003"]})
        text = "".join(textio.read_text(p) for p in textio.glob_in(ctx.run_dir, "10_ARCHITECTURE", "adr", "*.md"))
        self.assertNotIn("rejected", text.lower())


# ------------------------------------------------------------------------------------------------ G0, G1

class KickoffTests(Base):
    def test_a_refusal_at_the_kickoff_is_no_seed(self):
        # 'no', 'stop', 'cancel', 'not now' started the run as seed ideas for the paid fan-out
        ctx = self.ctx()
        for reply in ("no", "stop", "cancel", "not now", "no thanks", "wait"):
            got = parse("G0", reply)
            self.assertEqual((got.get("confirm"), got["seeds"]["ideas"]), (False, []), reply)
            self.assertIn("Tell me what to change, or reply `go`.", self.asked_again(ctx, "G0", reply), reply)
        self.assertEqual(parse("G0", "- deep")["seeds"]["ideas"], ["deep"])

    def offer(self, reply):
        ctx = self.ctx()
        ctx.state["legacy_v1"] = True
        ctx.state["interrupt"] = {"gate": "G0", "lite": True}
        st.save(ctx.run_dir, ctx.state)
        card = pipeline.answer_gate(ctx, pipeline.load_steps(), "G0", {"reply": reply})
        return ctx, card

    def test_a_refusal_declines_the_v1_run_offer(self):
        # 'No, stop.' and its siblings extended the v1 run into the paid architecture and proposal stages; since the
        # read-back (4.12) a refusal in other words than `stop` shows the stop first and a yes applies it
        for reply in ("stop", "No, stop.", "please stop", "stop, thanks", "No, don't extend it", "not now", "no"):
            ctx, card = self.offer(reply)
            if reply not in ("stop", "please stop", "stop, thanks"):
                self.assertEqual((card["type"], card["error"]), ("HUMAN", gates.READBACK_HEAD + "stop this run for "
                                 "good (it is not extended). Reply yes to do that, or tell me what you want instead."),
                                 reply)
                card = pipeline.answer_gate(ctx, pipeline.load_steps(), "G0", {"reply": "yes"})
            self.assertEqual((card["type"], ctx.state.get("status")), ("DONE", "stopped"), reply)

    def test_the_v1_run_offer_extends_only_on_go(self):
        ctx, card = self.offer("go")
        self.assertEqual((ctx.state.get("status"), ctx.state.get("interrupt")), ("active", None))
        self.assertNotEqual(card["type"], "DONE")
        for reply in ("what does extend mean?", "\U0001F914"):
            ctx, card = self.offer(reply)
            self.assertEqual((card["type"], card.get("gate"), ctx.state.get("status")), ("HUMAN", "G0", "active"),
                             ascii(reply))
            self.assertTrue(ctx.state.get("interrupt"), ascii(reply))

    def test_g1_takes_done_or_skip_only_from_an_affirmative_clause(self):
        # 'not yet' was done; "skip? no, I'm still writing" wrote SKIPPED into 00_HUMAN_SEEDS.md
        ctx = self.ctx()
        seeds = ctx.read("00_HUMAN_SEEDS.md")
        for reply in ("not yet", "not done yet, still writing", "skip? no, I'm still writing", "wait"):
            self.assertEqual(parse("G1", reply), {}, reply)
            self.assertIn("Reply `done` when the seeds file is written", self.asked_again(ctx, "G1", reply), reply)
        self.assertEqual(ctx.read("00_HUMAN_SEEDS.md"), seeds)
        for reply, want in (("done", {"done": True}), ("Done!", {"done": True}), ("skip", {"skip": True})):
            self.assertEqual(parse("G1", reply), want, reply)


if __name__ == "__main__":
    unittest.main()
