"""The read-back (KIT_SPEC 4.12): a free-text reply the host wrote alone acts at once only in a documented form; any
other reply is shown back as what the engine will do, and acts after a yes. Driven end to end through
pipeline.answer_gate on a real run folder: store, confirm with `yes`, a re-shown card, another reply, a plain `no`, a
stale reading, a host yes flag, host fields that win; and every documented reply form acting directly.
"""

import json
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fixtures", "engine"))
import engine_testlib as tl  # noqa: E402
import test_r_ra_gate_corpus_q as q  # noqa: E402

from ublib.engine import gates, pipeline  # noqa: E402
from ublib.engine import state as st  # noqa: E402

HEAD = gates.READBACK_HEAD
SEEDED = "- a shift board by SMS\ngo"

# every reply form HOW_TO_REPLY, the cards and GUIDE.md document, each acting at once (no read-back)
DOC_FORMS = [
    ("G0", "go"), ("G0", "quick"), ("G0", "deep\ngo"), ("G0", "hands-on"), ("G0", "full-auto"), ("G0", "private"),
    ("G0", "web: no"), ("G0", "vendors: no"), ("G0", "code: yes"), ("G0", "web: no, vendors: no\ngo"),
    ("G0", "topic: shift swaps for night nurses\ngo"), ("G0", "Primary: an SMS swap board\ngo"),
    ("G1", "done"), ("G1", "skip"), ("G2c", "ok"), ("G2f", "restore"), ("G2f", "keep"), ("G2f", "restore CONTEXT.md"),
    ("G4", "rescue I-012: nurses asked for it"), ("G4", "confirm I-004"), ("G4", "clear I-004"), ("G4", "ok"),
    ("G5", "kill I-003"), ("G5", "keep I-003"), ("G5", "ok"),
    ("G9", "passed"), ("G9", "missed"), ("G9", "inconclusive"), ("G9", "passed: 8 of 10"), ("G10", "ok"),
    ("G9", "passed, 18/20 used it"), ("G9", "inconclusive: only 5 replies"),
    ("G11", "ok"), ("G11", "B"), ("G11", "B + steal A: offline cache"), ("G11", "B+steal"),
    ("G11", "B."), ("G11", "b"), ("G11", "**B**"), ("G11", "go with B"),
    ("G12", "ok"), ("G12", "ok, reject 3"), ("G12", "accept 1 2, reject 3"),
    ("G13", "approve"), ("G13", "switch B"), ("G13", "runner-up"),
    ("G14", "publish"), ("G14", "publish architecture"), ("G14", "publish proposal"), ("G14", "publish adr"),
    ("G14", "no"), ("G14", "publish, ce"), ("G14", "no, speckit"), ("G14", "publish, none"),
    ("GB", "raise to 300"), ("GB", "stop"), ("GX", "reframe"), ("GX", "continue"), ("GX", "stop"),
    # the GUIDE's forms
    ("G0", "no seeds, go"), ("G14", "publish all"), ("G14", "publish all, ce"), ("G14", "publish everything, speckit"),
    ("G14", "publish architecture, proposal"), ("G14", "no, none"),
]


def events(ctx):
    path = os.path.join(ctx.run_dir, ".ub", "events.jsonl")
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


class ReadBackFlow(tl.EngineTestCase):
    """The kickoff (G0 at step 0.2): a seed line is free text, so it is read back before the run starts."""

    def start(self):
        self.steps = pipeline.load_steps()
        ctx = self.make_ctx()
        card = pipeline.advance(ctx, self.steps, 0)
        self.assertEqual((card["type"], card["gate"]), ("HUMAN", "G0"))
        return ctx

    def answer(self, ctx, provided, gid="G0"):
        return pipeline.answer_gate(ctx, self.steps, gid, provided)

    def read_back(self, ctx, reply=SEEDED):
        card = self.answer(ctx, {"reply": reply})
        self.assertEqual((card["type"], card["gate"]), ("HUMAN", "G0"))
        self.assertTrue(card["error"].startswith(HEAD), card["error"])
        return card

    def assert_waiting(self, ctx):
        self.assertNotEqual(st.step_state(ctx.state, "0.2"), "done")
        self.assertFalse(os.path.exists(ctx.path("answers", "G0.json")))

    def test_a_free_text_reply_is_shown_back_and_nothing_is_applied(self):
        ctx = self.start()
        card = self.read_back(ctx)
        self.assertIn('ideas "a shift board by SMS"', card["error"])
        self.assertIn("start the run (paid model calls)", card["error"])
        self.assertTrue(card["error"].endswith("Reply yes to do that, or tell me what you want instead."))
        self.assertNotIn("`ok`", card["error"])
        self.assert_waiting(ctx)
        rb = st.load(ctx.run_dir)["readback"]
        self.assertEqual((rb["gate"], rb["step"], rb["reply"]), ("G0", "0.2", SEEDED))
        self.assertEqual(rb["answer"]["seeds"]["ideas"], ["a shift board by SMS"])
        self.assertEqual([e["event"] for e in events(ctx)].count("gate_read_back"), 1)

    def test_yes_applies_the_stored_reading_with_the_original_reply(self):
        ctx = self.start()
        self.read_back(ctx)
        card = self.answer(ctx, {"reply": "yes"})
        self.assertNotEqual(card.get("gate"), "G0")
        self.assertEqual(st.step_state(ctx.state, "0.2"), "done")
        saved = tl.read_json(ctx.path("answers", "G0.json"))
        self.assertEqual(saved["reply"], SEEDED)
        self.assertEqual(saved["seeds"]["ideas"], ["a shift board by SMS"])
        self.assertNotIn("readback", st.load(ctx.run_dir))
        done = [e for e in events(ctx) if e["event"] == "gate_answered"]
        self.assertEqual(done[-1].get("readback"), "confirmed")

    def test_confirmation_words_confirm_too(self):
        for n, reply in enumerate(("Yes, do it.", "ok thanks", "go ahead", "yep")):
            with self.subTest(reply=reply):
                ctx = self.make_ctx(run_name="2026-09-28-c%d" % n)
                self.steps = pipeline.load_steps()
                pipeline.advance(ctx, self.steps, 0)
                self.read_back(ctx)
                self.answer(ctx, {"reply": reply})
                self.assertEqual(tl.read_json(ctx.path("answers", "G0.json"))["seeds"]["ideas"],
                                 ["a shift board by SMS"])

    def test_the_card_shown_again_still_carries_the_reading(self):
        ctx = self.start()
        self.read_back(ctx)
        card = pipeline.advance(ctx, self.steps, 0)  # `ub next` before the user answers
        self.assertEqual(card["gate"], "G0")
        self.assertTrue(card["show"].startswith(HEAD), card["show"][:120])
        self.assertNotIn("PLEASE FIX", card["show"])
        self.answer(ctx, {"reply": "yes"})
        self.assertEqual(tl.read_json(ctx.path("answers", "G0.json"))["reply"], SEEDED)

    def test_another_reply_replaces_the_reading(self):
        ctx = self.start()
        self.read_back(ctx)
        self.answer(ctx, {"reply": "deep\ngo"})  # documented: acts at once, without the seed (`go` alone is a yes)
        saved = tl.read_json(ctx.path("answers", "G0.json"))
        self.assertEqual((saved["reply"], saved["mode"], saved["seeds"]["ideas"]), ("deep\ngo", "deep", []))
        self.assertNotIn("readback", st.load(ctx.run_dir))

    def test_another_free_text_reply_is_read_back_in_turn(self):
        ctx = self.start()
        self.read_back(ctx)
        card = self.read_back(ctx, "- swap credits\ngo")
        self.assertIn('ideas "swap credits"', card["error"])
        self.assertNotIn("shift board", card["error"])
        self.answer(ctx, {"reply": "yes"})
        self.assertEqual(tl.read_json(ctx.path("answers", "G0.json"))["seeds"]["ideas"], ["swap credits"])

    def test_a_plain_no_asks_again_with_the_reply_forms(self):
        ctx = self.start()
        self.read_back(ctx)
        card = self.answer(ctx, {"reply": "no"})
        self.assertEqual((card["type"], card["gate"], card["error"]), ("HUMAN", "G0", gates.HOW_TO_REPLY["G0"]))
        self.assert_waiting(ctx)
        self.assertNotIn("readback", st.load(ctx.run_dir))

    def test_a_yes_to_a_reading_the_run_moved_past_asks_again(self):
        ctx = self.start()
        self.read_back(ctx)
        ctx.state["note"] = "another command changed the run"
        st.save(ctx.run_dir, ctx.state)
        card = self.answer(ctx, {"reply": "yes"})
        self.assertEqual((card["type"], card["gate"]), ("HUMAN", "G0"))
        self.assertTrue(card["error"].startswith("The reading I showed you is out of date"), card["error"])
        self.assert_waiting(ctx)
        self.assertNotIn("readback", st.load(ctx.run_dir))

    def test_a_stale_reading_stays_a_marker_so_a_late_yes_to_the_plain_card_asks_again(self):
        ctx = self.start()
        self.read_back(ctx)
        ctx.state["note"] = "another command changed the run"
        st.save(ctx.run_dir, ctx.state)
        card = pipeline.advance(ctx, self.steps, 0)
        self.assertFalse(card["show"].startswith(HEAD))
        self.assertIn("readback", st.load(ctx.run_dir))
        card = self.answer(ctx, {"reply": "yes"})  # the user may be answering the reading they saw
        self.assertTrue(card["error"].startswith("The reading I showed you is out of date"), card["error"])
        self.assert_waiting(ctx)
        self.answer(ctx, {"reply": "yes"})  # asked once: `yes` to the plain card is `go`
        self.assertEqual(tl.read_json(ctx.path("answers", "G0.json"))["seeds"]["ideas"], [])

    def test_a_reading_is_pending_only_for_its_gate_and_interrupt(self):
        ctx = self.start()
        self.read_back(ctx)
        self.assertIsNotNone(gates.pending_readback(ctx, "G0"))
        self.assertIsNone(gates.pending_readback(ctx, "G1"))
        ctx.state["interrupt"] = {"gate": "G0", "lite": True}
        self.assertIsNone(gates.pending_readback(ctx, "G0"))

    def test_a_host_yes_flag_on_the_confirming_reply_keeps_the_stored_reading(self):
        ctx = self.start()
        self.read_back(ctx)
        self.answer(ctx, {"reply": "yes", "confirm": True})
        saved = tl.read_json(ctx.path("answers", "G0.json"))
        self.assertEqual((saved["reply"], saved["seeds"]["ideas"]), (SEEDED, ["a shift board by SMS"]))

    def test_host_fields_win_and_drop_the_stored_reading(self):
        ctx = self.start()
        self.read_back(ctx)
        self.answer(ctx, {"reply": "yes", "mode": "deep"})
        saved = tl.read_json(ctx.path("answers", "G0.json"))
        self.assertEqual((saved["mode"], saved["seeds"]["ideas"]), ("deep", []))
        self.assertEqual(ctx.state["mode"], "deep")
        self.assertNotIn("readback", [e.get("readback") for e in events(ctx)])

    def test_a_host_filled_field_is_never_read_back(self):
        ctx = self.start()
        card = self.answer(ctx, {"reply": SEEDED, "mode": "deep"})
        self.assertFalse((card.get("error") or "").startswith(HEAD))
        self.assertEqual(tl.read_json(ctx.path("answers", "G0.json"))["seeds"]["ideas"], ["a shift board by SMS"])

    def test_the_autopilot_is_never_read_back(self):
        ctx = self.start()
        pipeline.answer_gate(ctx, self.steps, "G0", {"reply": SEEDED}, by="auto")
        self.assertEqual(st.step_state(ctx.state, "0.2"), "done")

    def test_the_v1_offer_reads_back_a_refusal_in_other_words(self):
        got = q.read_v1(self, "2026-09-28-v1", {"reply": "No thanks, I'm done"})
        self.assertEqual(got["r"], "stop")
        self.assertEqual(got["rb"], HEAD + "stop this run for good (it is not extended). Reply yes to do that, or tell "
                                          "me what you want instead.")
        self.assertEqual(q.read_v1(self, "2026-09-28-v2", {"reply": "stop"}), {"r": "stop"})
        self.assertEqual(q.read_v1(self, "2026-09-28-v3", {"reply": "go"}), {"r": "extend"})
        self.assertEqual(q.read_v1(self, "2026-09-28-v4", {"reply": "Extend."}), {"r": "extend"})  # the card's word


class DocumentedForms(tl.EngineTestCase):
    def test_every_documented_form_acts_at_once(self):
        for n, (gid, reply) in enumerate(DOC_FORMS):
            with self.subTest(gate=gid, reply=reply):
                ctx = q.GateCorpusQ.build(self, gid, n)
                ans, _notes, errs = gates.prepare_answer(ctx, gid, {"reply": reply})
                self.assertEqual(errs, [])
                self.assertTrue(gates.canonical(ctx, gid, ans), ans)
                self.assertIsNone(gates.read_back(ctx, gid, {"reply": reply}, ans))

    def test_the_handoffs_of_the_repository_are_documented_forms_too(self):
        for n, (reply, folder) in enumerate((("publish, superpowers", "docs/superpowers"),
                                             ("publish, openspec", "openspec"))):
            with self.subTest(reply=reply):
                os.makedirs(os.path.join(self.project, folder), exist_ok=True)
                ctx = q.GateCorpusQ.build(self, "G14", 100 + n)
                ans, _notes, errs = gates.prepare_answer(ctx, "G14", {"reply": reply})
                self.assertEqual(errs, [])
                self.assertIsNone(gates.read_back(ctx, "G14", {"reply": reply}, ans))

    def test_a_correction_a_change_round_and_a_seed_are_always_read_back(self):
        for n, (gid, reply) in enumerate((("G2c", "the users are nurses, not doctors"),
                                          ("G10", "add latency as a driver"), ("G0", "- shift swap by SMS\ngo"),
                                          ("G13", "changes: add a pilot budget"))):
            with self.subTest(gate=gid, reply=reply):
                ctx = q.GateCorpusQ.build(self, gid, 200 + n)
                ans, _notes, errs = gates.prepare_answer(ctx, gid, {"reply": reply})
                self.assertEqual(errs, [])
                self.assertTrue(gates.read_back(ctx, gid, {"reply": reply}, ans).startswith(HEAD))

    def test_gates_outside_the_read_back_never_read_back(self):
        ctx = self.make_ctx()  # G2 and G3 store the user's own words as written; G8a only records the gut picks
        for gid in ("G2", "G3", "G8a"):
            self.assertIsNone(gates.read_back(ctx, gid, {"reply": "something in my own words"}, {}))


if __name__ == "__main__":
    unittest.main()
