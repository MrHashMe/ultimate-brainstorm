"""Phase L (LA-gate-replies): one reader for every free-text gate reply (KIT_SPEC 4.12, 6.10).

A reply is read in clauses, a clause with a negation refuses what it names, and one confirmation vocabulary serves
every gate. An unclear or negated reply is asked again with the reason; it never becomes a paid redo, a publish, a
kill, a PASSED probe, a raised budget or an architecture the user named against.

- G0: everyday confirmations ('yeah', 'Proceed.', 'go...', 'Go ahead' + emoji) confirm and seed nothing; the mode
  word of a confirmation sentence is kept
- G2c/G10: 'Confirmed.', 'LGTM', 'OK - go ahead' confirm; a bare `no` is asked again, never a paid drivers redo
- G11: a letter named in a negation ('avoid A', "I don't want C") or next to an acceptance ('Yes, go ahead. C seemed
  overkill') is no choice; multi-word acceptances ('yes please', 'accept the recommendation') take the suggestion
- G12: 'accept all, reject 3' and its siblings reject ADR 3, also after G13 approve; a number no verb places is asked
  again
- G9 / GB / GX: two results, a negated result, `stop` with a cap and "don't continue, stop" are read as said
- G14: 'do not publish', 'Don't publish' (typographic apostrophe), 'never publish', 'publish nothing' publish nothing
- G4 / G5: each verb governs its own IDs ('keep I-003, kill I-007'); a negated verb kills nothing
- G13: 'Yes.', 'ok.', 'Looks good, thanks' approve; a switch names another architecture; the card shows the cost of
  `switch` and `runner-up` before anything is redone
"""

import os
import re
import sys
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fixtures", "engine"))
import engine_testlib as tl  # noqa: E402

from ublib import textio  # noqa: E402
from ublib.engine import gates, render_arch  # noqa: E402

MATRIX = {"leader": "A", "leader_status": "clear", "candidates": [
    {"label": "A", "score": 4.0, "rank": 1, "veto": "none"}, {"label": "B", "score": 3.5, "rank": 2, "veto": "none"},
    {"label": "C", "score": 3.0, "rank": 3, "veto": "none"}]}
ADR = {"context": "c", "options": [{"name": "opt one", "pros": ["p"], "cons": ["c"]},
                                   {"name": "opt two", "pros": ["p"], "cons": ["c"]}],
       "chosen": "opt one", "rationale": "r", "consequences": ["x"], "risks": [], "qg": []}


def parse(gid, reply):
    return gates.parse_reply(gid, reply)


class Base(tl.EngineTestCase):
    def prepared(self, ctx, gid, reply):
        ans, _notes, errs = gates.prepare_answer(ctx, gid, reply)
        return ans, errs

    def answer(self, ctx, gid, reply):
        ans, errs = self.prepared(ctx, gid, reply)
        self.assertEqual(errs, [], (gid, reply))
        return gates.apply(ctx, gid, ans), ans

    def asked_again(self, ctx, gid, reply):
        _ans, errs = self.prepared(ctx, gid, reply)
        self.assertTrue(errs, (gid, reply))
        return errs[0]


# ------------------------------------------------------------------------------------------------ confirmations

class ConfirmationTests(Base):
    def test_kickoff_confirmations_seed_nothing(self):
        # J2B: each became a seed idea that went into the paid ideation fan-out
        for reply in ("yeah", "Yep!", "Proceed.", "go…", "Let's start", "Let’s start", "Sounds great",
                      "Go ahead \U0001F680", "sure thing", "Looks good - thanks!"):
            got = parse("G0", reply)
            self.assertEqual((got.get("confirm"), got["seeds"]["ideas"]), (True, []), reply)
        # a list item and a line that is no confirmation stay seeds
        self.assertEqual(parse("G0", "- deep")["seeds"]["ideas"], ["deep"])
        self.assertEqual(parse("G0", "Great, let us go")["seeds"]["ideas"], ["Great, let us go"])

    def test_the_mode_word_of_a_confirmation_sentence_is_kept(self):
        got = parse("G0", "OK, go ahead with standard please")
        self.assertEqual((got.get("mode"), got.get("confirm"), got["seeds"]["ideas"]), ("standard", True, []))
        got = parse("G0", "yes, deep mode with hands-on autopilot")
        self.assertEqual((got.get("mode"), got.get("autopilot"), got["seeds"]["ideas"]), ("deep", "hands-on", []))
        self.assertEqual(parse("G0", "go with deep learning ideas")["seeds"]["ideas"], ["go with deep learning ideas"])

    def test_g2c_and_g10_confirmations_are_no_correction(self):
        # KX: each was a correction, at G10 a paid drivers redo
        for gid in ("G2c", "G10"):
            for reply in ("Confirmed.", "confirm", "Correct.", "LGTM", "Fine.", "Perfect, thanks", "Yep", "Yeah!",
                          "Yes, that's right", "Looks good - thanks!", "OK — go ahead", "ok…",
                          "nothing to change"):
                self.assertEqual(parse(gid, reply), {"confirm": True}, (gid, reply))
        self.assertEqual(parse("G10", "No, the users are nurses."),
                         {"confirm": False, "corrections": "No, the users are nurses."})

    def test_a_bare_no_at_g10_is_asked_again_and_redoes_nothing(self):
        ctx = self.make_ctx(mode="deep", run_name="2026-09-27-l-g10")
        for reply in ("no", "No, thanks", "not sure"):
            err = self.asked_again(ctx, "G10", reply)
            self.assertIn("A bare `no` does not say what to correct.", err, reply)
        effects, _ans = self.answer(ctx, "G10", "Confirmed.")
        self.assertEqual((effects, (ctx.state.get("counters") or {}).get("g10_loops", 0)), ([], 0))

    def test_a_yes_no_field_reads_the_same_words(self):
        for reply, want in (("Yep", True), ("LGTM", True), ("nope", False), ("No, thanks", False), ("maybe", None)):
            self.assertIs(gates._yesno(reply), want, reply)
        self.assertEqual(parse("G0", "web: yeah\nvendors: nope")["privacy"], {"web": True, "vendors": False})


# ------------------------------------------------------------------------------------------------ G11

class G11Tests(Base):
    def arch_ctx(self):
        ctx = self.make_ctx(run_name="2026-09-27-l-g11")
        ctx.write_json("10_ARCHITECTURE/candidates/map.json", {"A": {"family": "claude"}, "B": {"family": "gpt"},
                                                               "C": {"family": "kimi"}})
        ctx.write_json("10_ARCHITECTURE/matrix.json", MATRIX)
        return ctx

    def test_a_letter_named_in_a_negation_is_no_choice(self):
        # NEW-K-JA-1: each recorded the rejected letter as the architecture
        ctx = self.arch_ctx()
        for reply in ("avoid A", "drop A", "skip A", "reject A, take the next best", "I don’t want C",
                      "A is too risky; go with the cheaper one", "B over A"):
            self.assertNotIn("choice", parse("G11", reply), reply)
            self.asked_again(ctx, "G11", reply)

    def test_an_acceptance_that_mentions_another_letter_is_asked_again(self):
        # line 313: the fallback took any capital anywhere as the choice
        ctx = self.arch_ctx()
        for reply in ("Go ahead with your pick. Plan B looks too risky to me.",
                      "Yes, go ahead. C seemed overkill for a pilot.", "Sounds good, B felt heavier to run."):
            got = parse("G11", reply)
            self.assertNotIn("choice", got, reply)
            self.assertNotIn("accept_recommendation", got, reply)
            self.assertIn("takes the suggestion and also names", self.asked_again(ctx, "G11", reply), reply)

    def test_multi_word_acceptances_take_the_suggestion(self):
        # line 390: each was asked again although G2c/G10 read it as yes
        for reply in ("yes please", "ok thanks", "ok, sounds good", "yes, go with your suggestion",
                      "accept the recommendation", "Looks good, thanks!"):
            self.assertEqual(parse("G11", reply), {"accept_recommendation": True}, reply)
        ctx = self.arch_ctx()
        self.answer(ctx, "G11", "accept the recommendation")
        self.assertEqual(ctx.state["choice"]["arch"], "A")

    def test_a_letter_named_as_the_choice_is_still_chosen(self):
        for reply, want in (("go with C because it is cheaper", "C"), ("B, please", "B"), ("i'd take c", "C")):
            self.assertEqual(parse("G11", reply).get("choice"), want, reply)


# ------------------------------------------------------------------------------------------------ G12

class G12Tests(Base):
    def adrs(self, n=0):
        ctx = self.make_ctx(mode="deep", run_name="2026-09-27-l-g12-%d" % n)
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

    def test_accept_all_and_reject_one_rejects_it(self):
        # line 7 / 1081: the reject clause was dropped, and the rejected ADR was accepted
        want = {"0001": "accepted", "0002": "accepted", "0003": "rejected"}
        for n, reply in enumerate(("accept all, reject 3", "ok, reject 3", "accept all except 3", "yes but reject 3",
                                   "approve all but ADR 3", "accept all but reject 3", "Accept all. Reject 3.",
                                   "ok, but reject 3", "accept 1 2, reject 3")):
            self.assertEqual(parse("G12", reply)["reject"], ["0003"], reply)
            ctx = self.adrs(n)
            self.answer(ctx, "G12", reply)
            self.answer(ctx, "G13", "approve")
            self.assertEqual(self.statuses(ctx), want, reply)

    def test_a_number_no_verb_places_is_asked_again(self):
        ctx = self.adrs()
        for reply in ("3 looks wrong", "ok, 3 looks wrong", "don't reject 3"):
            self.assertEqual(parse("G12", reply), {}, reply)
            self.assertIn("ADR 3 where it is unclear", self.asked_again(ctx, "G12", reply), reply)
        self.assertEqual(self.statuses(ctx), {"0001": "proposed", "0002": "proposed", "0003": "proposed"})


# ------------------------------------------------------------------------------------------------ G9, GB, GX

class KeywordTests(Base):
    def test_a_missed_probe_is_never_passed(self):
        # line 734: the first keyword won, so a missed probe was PASSED and K6 skipped
        for reply in ("3 of 10 passed, so the probe missed", "not passed: we missed the target", "Passed? No.",
                      "3/10 passed the test - that's a miss, missed"):
            self.assertIsNone(parse("G9", reply)["result"], reply)
        self.assertEqual(parse("G9", "Passed? No. Missed: 3 of 10")["result"], "MISSED")
        self.assertEqual(parse("G9", "passed: 7 of 10")["result"], "PASSED")
        ctx = self.make_ctx(run_name="2026-09-27-l-g9")
        self.assertIn("`missed` and `passed`", self.asked_again(ctx, "G9", "3 of 10 passed, so the probe missed"))

    def test_stop_with_a_number_never_raises_the_budget(self):
        for reply in ("stop at 120", "stop now, I set 300 as my hard limit"):
            self.assertEqual(parse("GB", reply), {}, reply)
        for reply in ("stop, do not go to 500", "no - 250 is too many, stop"):
            self.assertEqual(parse("GB", reply), {"stop": True}, reply)
        self.assertEqual(parse("GB", "raise to 1,000"), {"raise_to": 1000, "stop": False})
        ctx = self.make_ctx(run_name="2026-09-27-l-gb")
        self.assertIn("names `stop` and a cap", self.asked_again(ctx, "GB", "stop at 120"))

    def test_a_negated_action_is_not_taken(self):
        for reply in ("don't continue, stop", "stop; no reframe", "no, do not reframe; stop"):
            self.assertEqual(parse("GX", reply), {"action": "stop"}, reply)
        self.assertEqual(parse("GX", "discontinue it"), {})
        self.assertEqual(parse("G2f", "don't restore"), {"restore": False})


# ------------------------------------------------------------------------------------------------ G14

class G14Tests(unittest.TestCase):
    def test_a_refusal_publishes_nothing(self):
        # line 896: each recorded publish=True, and 14.3 wrote into the user's docs/
        for reply in ("do not publish", "Don’t publish. Handoff: none", "never publish anything; handoff none",
                      "please publish nothing", "I'd rather not publish anything", "publish: none",
                      "skip publishing", "no"):
            self.assertIs(parse("G14", reply).get("publish"), False, reply)

    def test_a_consent_publishes(self):
        for reply, want in (("publish", True), ("publish architecture", ["architecture"]),
                            ("yes, publish the proposal", ["proposal"]), ("publish, handoff: none", True),
                            ("publish, no handoff", True)):
            self.assertEqual(parse("G14", reply).get("publish"), want, reply)
        self.assertEqual(parse("G14", "publish, no handoff")["handoff"], "none")
        # the ADRs go with the architecture and proposal copies: leaving them out is asked, not guessed
        self.assertNotIn("publish", parse("G14", "publish the proposal, not the ADRs"))

    def test_a_reply_that_publishes_and_refuses_is_asked_again(self):
        why = []
        self.assertNotIn("publish", gates.parse_reply("G14", "don't publish the ADRs, but publish the proposal",
                                                      None, why))
        self.assertEqual(why, ["Your reply both publishes and refuses to publish."])


# ------------------------------------------------------------------------------------------------ G4, G5

class IdeaVerbTests(Base):
    def test_each_verb_governs_its_own_ids(self):
        # line 973: the first verb classified the whole line
        for reply, want in (("keep I-003, kill I-007", {"kill": ["I-007"], "keep": ["I-003"]}),
                            ("kill I-007, keep I-003", {"kill": ["I-007"], "keep": ["I-003"]}),
                            ("don't kill I-003", {"kill": [], "keep": ["I-003"]}),
                            ("I-003 - I don’t want to kill it", {"kill": [], "keep": ["I-003"]})):
            self.assertEqual(parse("G5", reply), want, reply)
        self.assertEqual(parse("G4", "confirm I-004, clear I-005"), {"rescue": [], "confirm_flags": ["I-004"]})
        self.assertEqual(parse("G4", "confirm I-004 and rescue I-002: strong niche"),
                         {"rescue": [{"id": "I-002", "reason": "strong niche"}], "confirm_flags": ["I-004"]})
        self.assertEqual(parse("G4", "rescue I-012, it is more practical than I-003")["rescue"],
                         [{"id": "I-012", "reason": "it is more practical than I-003"}])

    def test_an_idea_killed_and_kept_is_asked_again(self):
        ctx = self.make_ctx(run_name="2026-09-27-l-g5")
        ctx.state["k4_candidates"] = ["I-003", "I-007"]
        self.assertIn("I-007 is both killed and kept", self.asked_again(ctx, "G5", "kill I-007\nkeep I-007"))
        self.assertIn("I-004 is both confirmed (killed) and rescued",
                      self.asked_again(ctx, "G4", "confirm I-004\nrescue I-004: niche"))


# ------------------------------------------------------------------------------------------------ G13

class G13Tests(Base):
    def arch_ctx(self, arch="A", runner_up=None):
        ctx = self.make_ctx(run_name="2026-09-27-l-g13")
        ctx.write_json("10_ARCHITECTURE/candidates/map.json", {"A": {"family": "claude"}, "B": {"family": "gpt"}})
        ctx.state["choice"] = {"idea": "I-001", "arch": arch, "runner_up": runner_up}
        return ctx

    def test_a_confirmation_approves(self):
        # line 1153: each became `changes`, a paid fixer redo and one of the two loops
        ctx = self.arch_ctx()
        for reply in ("Yes.", "ok.", "Looks good, thanks", "yes please", "Approve."):
            self.assertEqual(parse("G13", reply), {"action": "approve"}, reply)
            _effects, ans = self.answer(ctx, "G13", reply)
            self.assertEqual(ans["action"], "approve", reply)
        self.assertEqual((ctx.state.get("counters") or {}).get("g13_loops", 0), 0)
        self.assertEqual(parse("G13", "changes: add a pilot budget"),
                         {"action": "changes", "changes": "add a pilot budget"})

    def test_a_switch_names_another_architecture(self):
        ctx = self.arch_ctx(arch="B")
        self.assertNotIn("switch_to", parse("G13", "switch to a simpler architecture"))
        self.assertIn("Name the architecture to switch to (A)",
                      self.asked_again(ctx, "G13", "switch to a simpler architecture"))
        self.assertIn("B is the current architecture", self.asked_again(ctx, "G13", "switch B"))
        ans, errs = self.prepared(ctx, "G13", "switch to a")
        self.assertEqual((errs, ans["switch_to"]), ([], "A"))

    def test_an_approval_with_changes_is_asked_again(self):
        ctx = self.arch_ctx()
        self.assertIn("both approves and asks for changes",
                      self.asked_again(ctx, "G13", "approve, but shorten section 4"))

    def test_the_card_shows_the_cost_before_anything_is_redone(self):
        ctx = self.arch_ctx(runner_up="I-002")
        show = gates.display(ctx, "G13")
        self.assertRegex(show, r"Cost before anything is redone: `switch <letter>` redoes 12\.10 onward \(about \d+ "
                               r"requests\); `runner-up` \(I-002\) redoes 11\.1 onward \(about \d+ requests\)\.")


# ------------------------------------------------------------------------------------------------ linear

class LinearTests(unittest.TestCase):
    """The shared reader stays linear (#34) on floods of spaces, dashes and negations."""

    def test_floods(self):
        for text in (" " * 40000, " - " * 20000, "don't " * 10000, "a-" * 20000, "no, " * 10000, "1 " * 20000,
                     "I-001 " * 5000 + "kill", "’" * 40000):
            for gid in ("G0", "G4", "G5", "G9", "G10", "G11", "G12", "G13", "G14", "GB", "GX"):
                t0 = time.perf_counter()
                gates.parse_reply(gid, text)
                self.assertLess(time.perf_counter() - t0, 1.0, (gid, text[:12]))


if __name__ == "__main__":
    unittest.main()
