# -*- coding: utf-8 -*-
"""The second turn of a read-back (KIT_SPEC 4.12), driven through pipeline.answer_gate on a hands-on run waiting at the
gate, with the ub CLI for the commands in between: every confirmation word applies exactly the reading shown; a
refusal, a question or a condition applies nothing; a yes or no with more words asks again unless it is a documented
form itself; a reading the run moved past (a stop and continue, a redo, a default answer) is never applied by a late
yes; a host-filled field wins (a G13 `switch_to` beside `yes`); terminal mode prints the reading once.
"""

import contextlib
import copy
import io
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fixtures", "engine"))
import engine_testlib as tl  # noqa: E402

from ublib.engine import gates, pipeline, terminal  # noqa: E402
from ublib.engine import state as st  # noqa: E402

sys.path.insert(0, tl.SCRIPTS)
import ub  # noqa: E402

HEAD = gates.READBACK_HEAD
STALE = "The reading I showed you is out of date (the run changed since)"
AMENDS = "Your reply answers my reading and changes it: tell me the whole answer in one reply."
CONFIRM = ("yes", "y", "yep", "yeah", "sure", "correct", "exactly", "that's right", "do it", "go ahead", "ok", "k",
           "\U0001F44D", "yes please", "yes!!", "Yes.", "yes go ahead", "ok do it", "yup", "sounds good")
REFUSE = ("no", "nope", "not quite", "wrong", "that's not what I said", "what?", "why are you asking",
          "what does that cost", "yes if it is cheap", "yes, but let me check with my team first")
MATRIX = {"leader": "A", "leader_status": "clear", "candidates": [
    {"label": "A", "score": 4.0, "rank": 1, "veto": "none"}, {"label": "B", "score": 3.5, "rank": 2, "veto": "none"},
    {"label": "C", "score": 3.0, "rank": 3, "veto": "none"}]}


class Turn2(tl.EngineTestCase):
    def at(self, gate, n=0):
        """A hands-on run waiting at the gate: every earlier step done, the gate's `when` dropped."""
        ctx = self.make_ctx(run_name="2026-09-29-t2-%s-%d" % (gate.lower(), n), autopilot="hands-on")
        if gate == "G1":
            ctx.write("00_HUMAN_SEEDS.md", "# Seeds\n\n## Ideas\n- nurses swap shifts by SMS\n")
        if gate == "G5":
            ctx.state["k4_candidates"] = ["I-003", "I-007"]
            ctx.state["killed"] = []
        if gate == "G13":
            ctx.write_json("10_ARCHITECTURE/candidates/map.json", {"A": {"family": "claude"}, "B": {"family": "gpt"},
                                                                   "C": {"family": "kimi"}})
            ctx.write_json("10_ARCHITECTURE/matrix.json", MATRIX)
            ctx.state["choice"] = {"idea": "I-001", "arch": "A", "runner_up": "I-002"}
        self.steps, self.target = [], None
        for s in pipeline.load_steps():
            s = copy.deepcopy(s)
            if self.target is None and s.get("gate") == gate:
                s.pop("when", None)
                self.target = s["id"]
            elif self.target is None:
                st.set_step(ctx.state, s["id"], "done")
            self.steps.append(s)
        st.save(ctx.run_dir, ctx.state)
        card = pipeline.advance(ctx, self.steps, 0)
        self.assertEqual((card["type"], card["gate"]), ("HUMAN", gate))
        return ctx

    def answer(self, ctx, gate, provided):
        ctx = st.Ctx(ctx.run_dir, st.load(ctx.run_dir), ctx.deps)  # the run as a new `ub answer` reads it
        return pipeline.answer_gate(ctx, self.steps, gate, provided)

    def read_back(self, ctx, gate, reply):
        card = self.answer(ctx, gate, {"reply": reply})
        self.assertTrue((card.get("error") or "").startswith(HEAD), card.get("error"))
        return card

    def ub(self, ctx, *argv):
        with mock.patch.object(pipeline, "load_steps", lambda *a, **k: self.steps), \
                contextlib.redirect_stdout(io.StringIO()):
            ub.main(list(argv) + ["--json"], ctx.deps)

    def saved(self, ctx, gate):
        path = ctx.path("answers", gate + ".json")
        return tl.read_json(path) if os.path.exists(path) else None

    def killed(self, ctx):
        return st.load(ctx.run_dir).get("killed")

    def test_every_confirmation_word_applies_the_reading_shown(self):
        for n, reply in enumerate(CONFIRM):
            with self.subTest(reply=reply):
                ctx = self.at("G5", n)
                self.read_back(ctx, "G5", "kill both of them")
                self.answer(ctx, "G5", {"reply": reply})
                self.assertEqual(self.killed(ctx), ["I-003", "I-007"])
                self.assertEqual(self.saved(ctx, "G5")["reply"], "kill both of them")

    def test_do_it_and_a_thumbs_up_start_the_kickoff_as_read(self):
        for n, reply in enumerate(("do it", "\U0001F44D")):
            with self.subTest(reply=reply):
                ctx = self.at("G0", n)
                self.read_back(ctx, "G0", "start it in deep mode please, and keep it private")
                self.answer(ctx, "G0", {"reply": reply})
                s = st.load(ctx.run_dir)
                self.assertEqual((s["mode"], s["options"].get("private")), ("deep", True))

    def test_a_refusal_a_question_or_a_condition_applies_nothing(self):
        for n, reply in enumerate(REFUSE):
            with self.subTest(reply=reply):
                ctx = self.at("G5", n)
                self.read_back(ctx, "G5", "kill both of them")
                card = self.answer(ctx, "G5", {"reply": reply})
                self.assertEqual((card["type"], card["gate"]), ("HUMAN", "G5"))
                self.assertEqual((self.killed(ctx), self.saved(ctx, "G5")), ([], None))

    def test_a_yes_or_no_with_more_words_asks_for_the_whole_answer(self):
        for n, (t1, reply) in enumerate((("kill both of them", "yes but keep I-007"),
                                         ("drop I-003, keep I-007", "yes and also kill I-007"),
                                         ("kill both of them", "no, only I-003"),
                                         ("kill I-003 but not I-007", "yes, except kill I-007 too"))):
            with self.subTest(reply=reply):
                ctx = self.at("G5", n)
                self.read_back(ctx, "G5", t1)
                card = self.answer(ctx, "G5", {"reply": reply})
                self.assertTrue(card["error"].startswith(AMENDS), card["error"])
                self.assertEqual((self.killed(ctx), self.saved(ctx, "G5")), ([], None))
                self.assertFalse(card["show"].startswith(HEAD))  # the reading the user changed is not offered again
                card = self.answer(ctx, "G5", {"reply": "yes"})  # so a lone yes asks again instead of applying it
                self.assertTrue(card["error"].startswith(AMENDS), card["error"])
                self.assertEqual((self.killed(ctx), self.saved(ctx, "G5")), ([], None))

    def test_a_documented_form_in_the_second_turn_acts_as_written(self):
        ctx = self.at("G5")
        self.read_back(ctx, "G5", "kill both of them")
        self.answer(ctx, "G5", {"reply": "kill I-003, keep I-007"})
        self.assertEqual(self.killed(ctx), ["I-003"])
        ctx = self.at("G9", 1)
        self.read_back(ctx, "G9", "it passed, 12 of 15 nurses swapped a shift")
        self.answer(ctx, "G9", {"reply": "missed, 2 of 15"})
        self.assertEqual(self.saved(ctx, "G9")["result"], "MISSED")

    def test_a_late_yes_after_the_run_moved_on_is_never_applied(self):
        moves = (("stop and continue", lambda c: (self.ub(c, "stop", c.run_dir), self.ub(c, "continue", c.run_dir))),
                 ("redo", lambda c: self.ub(c, "redo", c.run_dir, self.target, "--yes")))
        for n, (name, move) in enumerate(moves):
            with self.subTest(move=name):
                ctx = self.at("G5", n)
                self.read_back(ctx, "G5", "kill both of them")
                move(ctx)
                self.assertTrue("readback" in st.load(ctx.run_dir))  # a marker, not a pending reading
                card = self.answer(ctx, "G5", {"reply": "yes"})
                self.assertTrue(card["error"].startswith(STALE), card["error"])
                self.assertEqual(self.killed(ctx), [])
                self.assertFalse("readback" in st.load(ctx.run_dir))
        ctx = self.at("G5", 9)
        self.read_back(ctx, "G5", "kill both of them")
        self.ub(ctx, "answer", ctx.run_dir, "G5", "--default")
        self.answer(ctx, "G5", {"reply": "yes"})
        self.assertEqual(self.killed(ctx), [])

    def test_a_host_field_beside_yes_wins(self):
        ctx = self.at("G13")
        self.read_back(ctx, "G13", "I want architecture C instead")
        self.answer(ctx, "G13", {"reply": "yes", "switch_to": "B"})  # not the reading (C), and not approve
        self.assertEqual(st.load(ctx.run_dir)["choice"]["arch"], "B")
        ctx = self.at("G13", 1)
        self.answer(ctx, "G13", {"reply": "yes", "switch_to": "C"})
        self.assertEqual(st.load(ctx.run_dir)["choice"]["arch"], "C")
        ctx = self.at("G5", 1)
        self.read_back(ctx, "G5", "kill both of them")
        self.answer(ctx, "G5", {"reply": "yes", "kill": ["I-007"]})
        self.assertEqual(self.killed(ctx), ["I-007"])
        # a field that says what `yes` alone would say is still the host's answer beside a reading, unlike `confirm`
        ctx = self.at("G1")
        self.read_back(ctx, "G1", "skip this one please, nothing from me")
        self.answer(ctx, "G1", {"reply": "yes", "done": True})
        self.assertEqual((self.saved(ctx, "G1").get("done"), self.saved(ctx, "G1").get("skip")), (True, None))
        ctx = self.at("G13", 2)
        self.read_back(ctx, "G13", "switch to B please")
        self.answer(ctx, "G13", {"reply": "yes", "action": "approve"})
        self.assertEqual((self.saved(ctx, "G13")["action"], st.load(ctx.run_dir)["choice"]["arch"]), ("approve", "A"))

    def test_approve_to_a_g13_switch_reading_is_asked_once(self):
        for n, (reply, then, arch) in enumerate((("approve", "approve", "A"), ("yes, approve", "yes", "B"),
                                                 ("approved", "do it", "B"))):
            with self.subTest(reply=reply, then=then):
                ctx = self.at("G13", n)
                self.read_back(ctx, "G13", "switch to B please")
                card = self.read_back(ctx, "G13", reply)  # before, `approve` approved A at once
                self.assertIn("reply `approve` again to keep architecture A", card["error"])
                self.assertEqual((self.saved(ctx, "G13"), st.load(ctx.run_dir)["choice"]["arch"]), (None, "A"))
                self.answer(ctx, "G13", {"reply": then})
                self.assertEqual(st.load(ctx.run_dir)["choice"]["arch"], arch)
        self.assertEqual(self.saved(ctx, "G13"), None)  # the switch redoes 12.10 onward
        ctx = self.at("G13", 3)
        self.read_back(ctx, "G13", "switch to B please")
        self.read_back(ctx, "G13", "approve")
        self.answer(ctx, "G13", {"reply": "approve"})
        self.assertEqual(self.saved(ctx, "G13")["action"], "approve")

    def test_terminal_mode_prints_the_reading_once_and_not_as_an_error(self):
        ctx = self.make_ctx(run_name="2026-09-29-t2-terminal")
        out = io.StringIO()
        terminal.run_loop(ctx, pipeline.load_steps(), stdin=io.StringIO("- a shift board by SMS\ngo\n\nyes\n\n"),
                          stdout=out, wait_s=0, max_cards=2)
        printed = out.getvalue()
        self.assertEqual(printed.count(HEAD), 1, printed[-600:])
        self.assertNotIn("ERROR: " + HEAD, printed)
        self.assertEqual(self.saved(ctx, "G0")["seeds"]["ideas"], ["a shift board by SMS"])


if __name__ == "__main__":
    unittest.main()
