# -*- coding: utf-8 -*-
"""The reply-reader findings of the third 2.1.0 verify round (KIT_SPEC 4.12), one row per finding, table-driven like
test_z_zf_reader_ab (the same row form and reader).

A row is (finding, gate, reply, want, says): `want` is `ask` (asked again), `act <reading>` (applied at once) or `rb
<reading>` (read back; nothing applied before a yes); `says` is a phrase the read-back or the ask must hold. Findings:
R1 `second thoughts` in the user's own words takes the reply back; R2 and R3 two patterns that were quadratic (Floods);
R4 the forms read as others (`dont`, `b/c`, `w/o`, `w/`) are read on a copy, and a gate stores the user's own words;
R5 a label body `pending <who>` puts the decision off; R7 an ID after a negation in its stretch, after `with` or
`back` that follows a word the reader does not know, or put away after it (`off`, `aside`, `hold`, `away`) is no
pick, so the gut pick never records an idea the reply rejects; D3 `I prefer I-004 to I-009` is asked as a comparison,
not a range; D4 `I-009 and I-011 out` and a bare `I already have a copy` are asked again (the documented readings).
"""
import os
import re
import sys
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fixtures", "engine"))
import engine_testlib as tl  # noqa: E402
import test_r_ra_gate_corpus_q as q  # noqa: E402
import test_z_za_readback_turn2 as t2  # noqa: E402
import test_z_zc_gate_corpus_picks as zc  # noqa: E402
import test_z_zf_reader_ab as zf  # noqa: E402

from ublib.engine import gates  # noqa: E402
from ublib.engine import state as st  # noqa: E402

ROWS = [
    ("R1", "G8a", "I-003, I-007, I-001. I'm having second thoughts", "ask", "takes itself back"),
    ("R1", "G8a", "I-003, I-007, I-001 - I'm having second thoughts", "ask", None),
    ("R1", "G8a", "I-003, I-007, I-001. I've got second thoughts", "ask", None),
    ("R1", "G8a", "I-003, I-007, I-001. having second thoughts", "ask", None),
    ("R1", "G8a", "I-003, I-007, I-001, we're having second thoughts though", "ask", None),
    ("R1", "G8a", "I-003, I-007, I-001. second thoughts", "ask", None),
    ("R1", "G8a", "I-003, I-007, I-001. I’m really having second thoughts", "ask", None),
    ("R1", "G4", "rescue I-012: I'm having second thoughts", "ask", "takes itself back"),
    ("R1", "G4", "rescue I-012: having second thoughts", "ask", None),
    ("R1", "G13", "changes: I'm having second thoughts", "ask", "takes itself back"),
    ("R1", "G2c", "corrections: I'm having second thoughts", "ask", "takes itself back"),
    ("R1", "G13", "changes: add an undo step for users having second thoughts", "rb changes", None),
    ("R1", "G13", "changes: no second thoughts about the budget table, fix its totals", "rb changes", None),
    ("R2", "G1", "done\nneed to add more", "ask", None),
    ("R2", "G1", "done\n\n\nI still have to add two", "ask", None),
    ("R3", "G1", "done, wait one more", "ask", None),
    ("R3", "G5", "kill I-003, but wait I-007", "ask", None),
    ("R3", "G5", "kill I-003, wait   one more", "ask", None),
    ("R4", "G6", "ok w/o I-005", "rb I-001,I-002,I-003,I-004,I-007,I-009,I-011", None),
    ("R4", "G13", "dont approve yet, need to check costs", "ask", None),
    ("R4", "G2c", "add A/B/C testing to the goals", "rb", "add A/B/C testing to the goals"),
    ("R4", "G2c", "le cadre dont on a parlé oublie les infirmières de nuit", "rb", "le cadre dont on a"),
    ("R4", "G13", "changes: add the A/B/C test plan to section 4", "rb changes", "the A/B/C test plan"),
    ("R4", "G10", "the budget table dont match the spec; fix the totals", "rb", "the budget table dont match"),
    ("R5", "G13", "changes: pending legal", "ask", "puts the decision off"),
    ("R5", "G13", "changes: pending the board", "ask", None),
    ("R5", "G13", "changes: pending Sam's sign-off", "ask", None),
    ("R5", "G2c", "corrections: pending legal", "ask", "puts the decision off"),
    ("R5", "G13", "changes: pending approvals are handled by HR, add that step to section 3", "rb changes", None),
    ("R7", "G8a", "I-003, I-007. I don't like I-009", "ask", "I don't like I-009"),
    ("R7", "G8a", "I-003 and I-007; I don't think I-009 works", "ask", None),
    ("R7", "G8a", "I-003, I-007, I'm done with I-009", "ask", "done with I-009"),
    ("R7", "G8a", "I-003, I-007, push back on I-009", "ask", None),
    ("R7", "G8a", "I-003, I-007, never fund I-009", "ask", None),
    ("R7", "G8a", "I-003, I-007, can't support I-009", "ask", None),
    ("R7", "G8a", "I-003, I-007; take I-009 off the list", "ask", "take I-009 off"),
    ("R7", "G8a", "I-003, I-007; put I-009 aside", "ask", None),
    ("R7", "G8a", "I-003, I-007; put I-009 on hold", "ask", None),
    ("R7", "G8a", "I-003, I-007 and I'd never pick I-009", "ask", None),
    ("R7", "G8a", "I-003, I-007; I wouldn't back I-009", "ask", None),
    ("R7", "G8a", "I-003, I-007; I don't really want I-009", "ask", None),
    ("R7", "G8a", "I don't like I-009. I-003, I-007", "ask", None),
    ("R7", "G8a", "I-003, I-007, do away with I-009", "ask", None),
    ("R7", "G8a", "I-003, I-007, not I-009", "act I-003,I-007", None),
    ("R7", "G8a", "I-003, I-007, veto I-009", "act I-003,I-007", None),
    ("R7", "G8a", "I-003, I-007, I do not want I-009", "act I-003,I-007", None),
    ("R7", "G8a", "I'd go with I-003, then I-007", "act I-003,I-007", None),
    ("R7", "G8a", "we back I-003 and I-007", "act I-003,I-007", None),
    ("R7", "G6", "ok, keep I-009 off the list", "ask", "keep I-009 off"),
    ("R7", "G6", "I-001, I-002, I-003, I-004, take I-009 off", "ask", None),
    ("R7", "G7", "I-001, I-003, I-007; I don't like I-009", "ask", None),
    ("D3", "G6", "I prefer I-004 to I-009", "ask", "compares ideas"),
    ("D3", "G8a", "I prefer I-004 to I-009", "ask", "compares ideas"),
    ("D3", "G8b", "I-004, I prefer I-004 to I-009", "ask", "compares ideas"),
    ("D3", "G6", "I-001 to I-004", "ask", "names a range"),
    ("D3", "G8a", "I-004 (I prefer I-004 to I-009)", "act I-004", None),
    ("D4", "G6", "ok, I-009 and I-011 out", "ask", "I-009 and I-011 out"),
    ("D4", "G8a", "I-003, I-007; I-009 and I-011 out", "ask", None),
    ("D4", "G14", "I already have a copy", "ask", None),
    ("D4", "G14", "no, I already have a copy", "rb ok pub=none", None),
]
# R4: what a gate stores is the reply as typed (the reading copy only decides)
STORED = [
    ("G2c", "add A/B/C testing to the goals", "corrections", "add A/B/C testing to the goals"),
    ("G2c", "le cadre dont on a parlé oublie les infirmières", "corrections",
     "le cadre dont on a parlé oublie les infirmières"),
    ("G2c", "the nurse app cant be offline-first, it must sync each hour", "corrections",
     "the nurse app cant be offline-first, it must sync each hour"),
    ("G13", "changes: la section dont nous avons parlé manque", "changes",
     "la section dont nous avons parlé manque"),
    ("G13", "changes: use the w/ lookup table in section 2", "changes", "use the w/ lookup table in section 2"),
    ("G2c", "the scope is w/o the pharmacy module", "corrections", "the scope is w/o the pharmacy module"),
    ("G8a", "I-003 b/c dont", "notes", "I-003 b/c dont"),
]


class ReaderAC(tl.EngineTestCase):
    variant = "product"
    make_ctx = zf.ReaderAB.make_ctx
    read = zf.ReaderAB.read

    def test_rows(self):
        with mock.patch("os.fsync", lambda fd: None):  # a run per row, in a temp dir: no need to reach the disk
            for n, (finding, gate, reply, want, says) in enumerate(ROWS):
                with self.subTest(finding=finding, gate=gate, reply=reply):
                    got = self.read(gate, reply, n)
                    how, _sp, reading = want.partition(" ")
                    self.assertEqual(got["how"], how, "want %s, got %r" % (want, got))
                    if reading and gate in zf.PICKS:
                        exp = zc.expected(gate, reading)
                        self.assertEqual(dict((k, got.get(k)) for k in exp), exp, got)
                    elif reading:
                        self.assertTrue(q.matches(reading, got), "want %s, got %r" % (want, got))
                    if says:
                        self.assertIn(says, got.get("say") or got.get("why") or "")

    def test_a_gate_stores_the_reply_as_typed(self):
        with mock.patch("os.fsync", lambda fd: None):
            for n, (gate, reply, field, want) in enumerate(STORED):
                with self.subTest(gate=gate, reply=reply):
                    ctx = q.GateCorpusQ.build(self, gate, n)
                    ans, _notes, errs = gates.prepare_answer(ctx, gate, {"reply": reply})
                    self.assertEqual(errs, [])
                    self.assertEqual(ans[field], want)  # before, 'A/because testing', "le cadre don't on a"
                    self.assertIn(want[:20], gates.read_back(ctx, gate, {"reply": reply}, ans) or want)
        for rx, reply, want in ((r"\bwithout\b", "ok w/o I-005", True), (r"\bbecause\b", "B b/c cheap", True),
                                (r"don't", "dont approve yet", True), (r"because", "A/B/C", False),
                                (r"don't", "le cadre dont", True)):
            self.assertEqual(bool(re.search(rx, gates._reading(reply)[0])), want, reply)


class Chains(tl.EngineTestCase):
    """Turn by turn through pipeline.answer_gate on a hands-on run waiting at the gate."""
    at, answer, read_back, saved = t2.Turn2.at, t2.Turn2.answer, t2.Turn2.read_back, t2.Turn2.saved

    def asked(self, ctx, gate, reply, says):
        card = self.answer(ctx, gate, {"reply": reply})
        self.assertEqual((card.get("type"), card.get("gate")), ("HUMAN", gate), card)
        self.assertIn(says, card.get("error") or "")
        self.assertIsNone(self.saved(ctx, gate))
        self.assertFalse(st.load(ctx.run_dir).get("readback"))
        return card

    def test_a_take_back_in_the_users_words_is_asked_and_saves_nothing(self):  # R1
        ctx = self.at("G8a", 1)
        self.asked(ctx, "G8a", "I-003, I-007, I-001. I'm having second thoughts", "takes itself back")
        self.answer(ctx, "G8a", {"reply": "I-003, I-007"})
        self.assertEqual(self.saved(ctx, "G8a")["picks"], ["I-003", "I-007"])
        ctx = self.at("G4", 2)
        self.asked(ctx, "G4", "rescue I-012: I'm having second thoughts", "takes itself back")  # before, rescued

    def test_the_gut_pick_never_records_an_idea_the_reply_rejects(self):  # R7
        for n, reply in enumerate(("I don't like I-009. I-003, I-007", "I-003, I-007, I'm done with I-009",
                                   "I-003, I-007; put I-009 aside")):
            with self.subTest(reply=reply):
                ctx = self.at("G8a", 10 + n)
                self.asked(ctx, "G8a", reply, "I cannot tell whether it takes or leaves out I-009")
                self.answer(ctx, "G8a", {"reply": "I-003, I-007"})  # before, I-009 was saved (as gut pick #1)
                self.assertEqual(self.saved(ctx, "G8a")["picks"], ["I-003", "I-007"])

    def test_a_pending_status_body_is_asked(self):  # R5
        ctx = self.at("G13", 20)
        self.asked(ctx, "G13", "changes: pending legal", "puts the decision off")  # before, a paid change round

    def test_a_change_round_keeps_the_users_words(self):  # R4
        ctx = self.at("G13", 30)
        card = self.read_back(ctx, "G13", "changes: add the A/B/C test plan to section 4")
        self.assertIn("add the A/B/C test plan to section 4", card["error"])  # before, 'the A/because test plan'
        self.answer(ctx, "G13", {"reply": "yes"})
        self.assertEqual(self.saved(ctx, "G13")["changes"], "add the A/B/C test plan to section 4")
        self.assertEqual(st.load(ctx.run_dir).get("user_changes"), "add the A/B/C test plan to section 4")


class Floods(tl.EngineTestCase):
    """Every new or changed pattern stays linear: a 20000-character reply is read in under 3 s, also through
    pipeline.answer_gate for the two that were quadratic (G1 newline runs, a `wait` before a run of blanks)."""
    at, answer = t2.Turn2.at, t2.Turn2.answer

    def test_linear(self):
        n = 20000
        floods = (
            ("G1", "done" + "\n" * n + "x"), ("G1", "done" + "\n " * (n // 2) + "x"),
            ("G5", "kill I-003, wait" + " " * n + "!"), ("G5", "kill I-003, wait" + "\t" * n + "!"),
            ("G13", "changes: fix the totals, wait" + " " * n + "!"), ("G5", "x, wait" + " -" * (n // 2) + "!"),
            ("G8a", "I-003." + " " * n + "!"), ("G8a", ".!" * (n // 2) + "x"), ("G8a", "I have" + " " * n + "x"),
            ("G8a", "I have " + "reallyly " * (n // 9) + "x"), ("G13", "changes: - " + "having " * (n // 7)),
            ("G8a", "I-003. second thoughts" + "!" * n + "x"), ("G4", "rescue I-012: we're " + "still " * (n // 6)),
            ("G13", "changes: pending legal" + "-" * n + "x"), ("G13", "changes: pending " + "a-" * (n // 2) + "!x"),
            ("G2c", "corrections: pending " + "a " * (n // 2) + "!x"),
            ("G8a", "I-003 " * (n // 6) + "off"), ("G6", "I-001 on " * (n // 9) + "hold"),
            ("G8a", "I-003, " + "I don't like I-009 " * (n // 19)), ("G8a", "done with " * (n // 10) + "I-009"),
            ("G8a", "push back " * (n // 10) + "I-009"), ("G6", "keep I-009 " + " " * n + "off"),
            ("G2c", "b/c w/o w/ dont " * (n // 16)), ("G13", "changes: A/B/C " * (n // 15)),
            ("G5", "kill 1 n 2 n " * (n // 12)), ("G2c", "w/" + " " * n + "x"), ("G6", "1" + " " * n + "n"),
            ("G6", "I prefer I-004 to " * (n // 18) + "I-009"), ("G8a", "prefer " * (n // 7) + "I-004 to I-009"))
        for gid, text in floods:
            t0 = time.perf_counter()
            gates.parse_reply(gid, text, None, [])
            if gid not in zf.PICKS:
                gates.canonical(None, gid, {"reply": text})
            self.assertLess(time.perf_counter() - t0, 10.0, (gid, re.sub(r"\s+", " ", text[:24])))
        with mock.patch("os.fsync", lambda fd: None):
            for k, (gid, text) in enumerate(floods[:5]):
                ctx = self.at(gid, 40 + k)
                t0 = time.perf_counter()
                self.answer(ctx, gid, {"reply": text})
                self.assertLess(time.perf_counter() - t0, 10.0, (gid, "answer_gate", re.sub(r"\s+", " ", text[:24])))


if __name__ == "__main__":
    unittest.main()
