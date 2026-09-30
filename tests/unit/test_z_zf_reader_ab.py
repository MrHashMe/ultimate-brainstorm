# -*- coding: utf-8 -*-
"""The reply-reader findings of the second 2.1.0 verify round (KIT_SPEC 4.12), one row per finding, table-driven like
test_z_zd_reader_aa.

A row is (finding, gate, reply, want, says): `want` is `ask` (asked again), `act <reading>` (applied at once) or `rb
<reading>` (read back; nothing applied before a yes), with the reading in the corpus tests' form (`q.matches` outside
the ID-picking gates; at G6, G7, G8a and G8b the pick corpus spec); `says` is a phrase the read-back or the ask must
hold. The direction of the fixes: the reader acts only on the forms it positively understands and reads back or asks
for the rest; an ID beside a word it does not know at a pick gate is not a pick. The chains go through
pipeline.answer_gate turn by turn, as a host's `ub answer` does.
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
import test_t_ta_gate_corpus_s as s  # noqa: E402
import test_z_za_readback_turn2 as t2  # noqa: E402
import test_z_zc_gate_corpus_picks as zc  # noqa: E402
import test_z_zd_reader_aa as zd  # noqa: E402

from ublib.engine import gates  # noqa: E402
from ublib.engine import state as st  # noqa: E402

PICKS = zd.PICKS
ROWS = [
    ("F1", "G8a", "veto I-009", "ask", None),
    ("F1", "G8a", "no to I-009", "ask", None),
    ("F1", "G8a", "I-004 and axe I-009", "act I-004", None),
    ("F1", "G8a", "I-004, I-003, skip I-009", "act I-004,I-003", None),
    ("F2", "G4", "rescue I-012: cheap, get rid of everything else", "rb ok rescue=I-012", None),
    ("F2", "G4", "rescue I-012: cheap, the leftovers can go", "rb ok rescue=I-012", None),
    ("F3", "G8a", "I-003, I-007, and don't forget I-001", "ask", None),
    ("F3", "G6", "keep them all, don't cut I-009", "ask", "don't cut I-009"),
    ("F4", "G14", "publish all, and we launch next week", "rb ok pub=all", None),
    ("F4", "G5", "kill I-003, then we regroup tomorrow", "rb ok kill=I-003", None),
    ("F4", "GB", "raise to 300, and we review spend next week", "rb raise cap=300", None),
    ("F4", "G6", "I-001, I-003, I-007 and then we meet tomorrow", "rb I-001,I-003,I-007", None),
    ("F5", "G13", "changes: the flow should let users have second thoughts before paying", "rb changes", None),
    ("F5", "G13", "changes: add a section for users still reviewing paper forms", "rb changes", None),
    ("F6", "G1", "done - nurses still have to add their shifts by hand today", "rb done", None),
    ("F6", "G1", "done - the seeds say clerks still need to write each claim twice", "rb done", None),
    ("F7", "G8a", "I-004 (I prefer I-004 to I-009)", "act I-004", None),
    ("F7", "G8a", "I-003, I-007 (prefer I-007 to I-001)", "act I-003,I-007", None),
    ("F7", "G7", "I-003, I-007, I-001 - I prefer I-001 to I-004", "rb I-001,I-003,I-007", None),
    ("F8", "G0k", "uniquement Claude\ngo", "ask", "privacy"),
    ("F8", "G0k", "hors ligne\ngo", "ask", "privacy"),
    ("F8", "G0k", "bidoon internet\ngo", "ask", "privacy"),
    ("F8", "G0k", "只用 Claude\ngo", "ask", "privacy"),
    ("F9", "G6", "I-001, I-003, I-005; forget the rest", "ask", None),
    ("F9", "G6", "I-001, I-003, I-005; the rest can go", "ask", None),
    ("F9", "G6", "I-002, I-008; I-008 outperforms I-001", "ask", None),
    ("F9", "G6", "I-001 until I-004", "ask", None),
    ("F9", "G6", "from I-001 up to I-004", "ask", None),
    ("F9", "G6", "ok, strike I-009", "rb SUG-I-009", None),
    ("F9", "G6", "Axe I-009, keep the rest", "rb SUG-I-009", None),
    ("F9", "G6", "ok, I-009 can go", "ask", None),
    ("F10", "G8b", "I-007, I suppose", "rb I-007", None),
    ("F10", "G8b", "I-007 - for now", "rb I-007", None),
    ("F10", "G8b", "I-007 - provisionally", "rb I-007", None),
    ("F12", "G13", "Accept with no edits whatsoever", "rb approve", None),
    ("F12", "G2c", "no rework needed", "rb confirm", None),
    ("F13", "G12", "every ADR except 3", "rb ok acc=all rej=0003", None),
    ("F13", "G12", "all of the ADRs but 3", "rb ok acc=all rej=0003", None),
    ("F14", "G0k", "I consent", "rb start seeds=0", None),
    ("F14", "G0k", "consent given", "rb start seeds=0", None),
    ("F14", "G0k", "I do not consent", "ask", None),
    ("F15", "G1", "done, one more to add", "ask", None),
    ("F15", "G1", "done, need to add one more though", "ask", None),
    ("F16", "G5", "a. [x] kill I-003\nb. [ ] kill I-007", "rb ok kill=I-003", None),
    ("F16", "G5", "(1) [x] kill I-003\n(2) [ ] kill I-007", "rb ok kill=I-003", None),
    ("F16", "G5", "✅ kill I-003\n⬜ kill I-007", "ask", None),
    ("F17", "GB", "raise to 300, just not today", "ask", None),
    ("F17", "GB", "raise to 300 though not till Monday", "ask", None),
    ("F18", "G13", "changes: to come", "ask", None),
    ("F18", "G13", "changes: attached", "ask", None),
    ("F18", "G13", "changes: halfway through reading", "ask", None),
    ("F18", "G13", "changes: per our discussion", "ask", None),
    ("F19", "G0v1", "I'm not against extending", "ask", None),
    ("F19", "G0v1", "no reason not to extend", "ask", None),
    ("F28", "G14", "none, Compound Eng.", "ask", None),
    ("F42", "G8a", "[17:00] Joe: my top 3 is I-001 I-002 I-003", "ask", None),
    ("F42", "G8a", "[17:00] Joe: I-001\n[17:01] me: mine: I-003, I-007", "act I-003,I-007", None),
    ("F42", "GB", "[21:00] Finance: max 250 pls", "ask", None),
    ("F42", "G4", "[09:30] Sam: rescue I-012: pls", "ask", None),
    ("F43", "G6", "ok w/o I-005", "rb SUG-I-005", None),
    ("F43", "G7", "ok w/o I-001, add I-002", "rb SUG-I-001+I-002", None),
    ("F43", "G1", "done b/c i wrote 5 ideas", "rb done", None),
    ("F44", "G8a", "I-003 or not", "ask", None),
    ("F45", "G13", "dont approve yet, need to check costs", "ask", None),
    ("F46", "G12", "[12:00] Sam (Slack): reject 3\n[12:01] me: agreed, rest ok", "rb ok acc=all rej=0003", None),
    ("F46", "G5", "Mia: kill I-003 its a dup\nme: yes", "rb ok kill=I-003", None),
    ("F46", "G2c", "[08:00] Priya: frame is fine\n[08:01] me: +1", "ask", "someone else"),
    ("F47", "G0v1", "go without the proposal pls", "ask", None),
    ("F48", "G7", "ok? or should I add I-004", "ask", None),
    ("F49", "G14", "publica todo, ce", "ask", None),
    ("F49", "G14", "alles veröffentlichen, ce", "ask", None),
    ("F50", "G0k", "başla ama web yok", "ask", "privacy"),
    ("F51", "G1", "done - wait one more", "ask", None),
    ("F54", "G14", "no, I already have a copy", "rb ok pub=none", None),
    ("F54", "G14", "none, thanks, I keep a printed copy", "rb ok pub=none", None),
    ("F56", "G5", "no, keep both of them", "rb ok kill=- keep=I-003,I-007", None),
]


class ReaderAB(tl.EngineTestCase):
    variant = "product"
    make_ctx = s.GateCorpusS.make_ctx  # the Q fixtures on the product variant
    read = zd.ReaderAA.read

    def test_rows(self):
        with mock.patch("os.fsync", lambda fd: None):  # a run per row, in a temp dir: no need to reach the disk
            for n, (finding, gate, reply, want, says) in enumerate(ROWS):
                with self.subTest(finding=finding, gate=gate, reply=reply):
                    got = self.read(gate, reply, n)
                    how, _sp, reading = want.partition(" ")
                    self.assertEqual(got["how"], how, "want %s, got %r" % (want, got))
                    if reading and gate in PICKS:
                        exp = zc.expected(gate, reading)
                        self.assertEqual(dict((k, got.get(k)) for k in exp), exp, got)
                    elif reading:
                        self.assertTrue(q.matches(reading, got), "want %s, got %r" % (want, got))
                    if says:
                        self.assertIn(says, got.get("say") or got.get("why") or "")

    def test_every_finding_with_a_reply_has_a_row(self):
        have = set(r[0] for r in ROWS)
        dup = set("F%d" % i for i in range(20, 42)) - {"F28"}  # the same causes as F1-F19
        self.assertEqual(set("F%d" % i for i in range(1, 57)) - have - dup,
                         {"F11", "F52", "F53", "F55"})  # chains below; F52 left as it is (plain replies asked)


class Chains(tl.EngineTestCase):
    """Turn by turn through pipeline.answer_gate on a hands-on run waiting at the gate."""
    at, answer, read_back, saved, killed = t2.Turn2.at, t2.Turn2.answer, t2.Turn2.read_back, t2.Turn2.saved, \
        t2.Turn2.killed
    v1, v1_answer = zd.Chains.v1, zd.Chains.v1_answer

    def test_go_with_a_yes_beside_a_stop_reading_at_the_v1_offer_is_asked_once(self):  # F11
        for n, reply in enumerate(("ok go", "yes, go", "go go", "let's go", "sure, go")):
            with self.subTest(reply=reply):
                ctx = self.v1(10 + n)
                card = self.v1_answer(ctx, "no thanks, I'm done with this one")
                self.assertTrue(card["error"].startswith(t2.HEAD), card["error"])
                card = self.v1_answer(ctx, reply)  # before, the stop was confirmed and the run ended for good
                self.assertIn("reply `go` again to extend this v1 run", card.get("error") or "", card)
                self.assertNotEqual(st.load(ctx.run_dir).get("status"), "stopped")
                self.v1_answer(ctx, "go")
                self.assertEqual(st.load(ctx.run_dir).get("status"), "active")

    def test_a_confirmation_outside_the_old_yes_words_applies_the_reading(self):  # F53
        for n, reply in enumerate(("alright", "all right", "That's what I meant.", "aye", "make it so")):
            with self.subTest(reply=reply):
                ctx = self.at("G5", 10 + n)
                self.read_back(ctx, "G5", "kill both of them")
                self.answer(ctx, "G5", {"reply": reply})
                self.assertEqual(self.killed(ctx), ["I-003", "I-007"])  # before, a new reading: park both
                ctx = self.at("G0", 10 + n)
                self.read_back(ctx, "G0", "let's go, and keep it private")
                self.answer(ctx, "G0", {"reply": reply})
                self.assertTrue(st.load(ctx.run_dir)["options"].get("private"), reply)

    def test_a_kickoff_reply_that_leaves_out_the_waiting_privacy_is_asked(self):  # F53
        ctx = self.at("G0", 20)
        self.read_back(ctx, "G0", "let's go, and keep it private")
        card = self.answer(ctx, "G0", {"reply": "start"})  # before, read back as a start with vendors and web on
        self.assertTrue(card["error"].startswith(t2.HEAD), card["error"])  # the privacy reading is still offered
        self.assertIn("leaves out the privacy you asked for", card["error"])
        self.assertIsNone(self.saved(ctx, "G0"))
        self.answer(ctx, "G0", {"reply": "yes"})
        self.assertTrue(st.load(ctx.run_dir)["options"].get("private"))
        ctx = self.at("G0", 21)
        self.read_back(ctx, "G0", "let's go, and keep it private")
        self.answer(ctx, "G0", {"reply": "start"})
        card = self.answer(ctx, "G0", {"reply": "start, keep it private"})  # the whole answer again: read back
        self.assertTrue(card["error"].startswith(t2.HEAD), card["error"])

    def test_the_word_copy_beside_a_waiting_reading_is_not_a_publish(self):  # F54
        for n, reply in enumerate(("I already have a copy, so yes, do that.", "Fine. I'll keep my own copy. So yes.",
                                   "we rebuilt it from the paper copy on the fridge. Anyway, yes, do that.")):
            with self.subTest(reply=reply):
                ctx = self.at("G14", 10 + n)
                self.read_back(ctx, "G14", "don't publish anything")
                card = self.answer(ctx, "G14", {"reply": reply})
                if (card.get("error") or "").startswith(t2.HEAD):
                    self.assertIn("publish nothing", card["error"])
                    self.answer(ctx, "G14", {"reply": "yes"})
                self.assertIs(self.saved(ctx, "G14")["publish"], False)

    def test_the_card_word_publish_beside_a_narrower_reading_is_asked_once(self):  # F55
        for n, (then, pub, ho) in enumerate((("publish", True, "none"), ("yes", False, "ce"))):
            with self.subTest(then=then):
                ctx = self.at("G14", 20 + n)
                self.read_back(ctx, "G14", "no publishing, handoff ce")
                card = self.answer(ctx, "G14", {"reply": "publish"})  # before, it published everything at once
                self.assertTrue((card.get("error") or "").startswith(t2.HEAD), card)
                self.assertIn("`publish` again to publish", card["error"])
                self.assertIsNone(self.saved(ctx, "G14"))
                self.answer(ctx, "G14", {"reply": then})
                got = self.saved(ctx, "G14")
                self.assertEqual((bool(got["publish"]), got.get("handoff") or "none"), (pub, ho), got)

    def test_a_correction_repeated_as_the_ask_requests_keeps(self):  # F56
        ctx = self.at("G5", 30)
        self.read_back(ctx, "G5", "kill both of them")
        card = self.answer(ctx, "G5", {"reply": "no, keep both of them"})
        self.assertTrue(card["error"].startswith(t2.AMENDS), card["error"])
        card = self.answer(ctx, "G5", {"reply": "no, keep both of them"})
        self.assertIn("keep I-003, I-007", card["error"])  # before: park I-003, I-007
        self.answer(ctx, "G5", {"reply": "yes"})
        self.assertEqual((self.killed(ctx), self.saved(ctx, "G5")["keep"]), ([], ["I-003", "I-007"]))


class Floods(tl.EngineTestCase):
    """The new and changed forms stay linear: a 20000-character reply is read in under 3 s."""

    def test_linear(self):
        n = 20000
        floods = (
            ("G14", "publish all, and we " * (n // 20)), ("G5", "kill I-003, then then we " * (n // 25)),
            ("G8a", "veto " * (n // 5) + "I-009"), ("G8a", "I-004 and axe " * (n // 14) + "I-009"),
            ("G8a", "I-003, and don't forget " * (n // 24)), ("G8a", "I-003 or " * (n // 9) + "not"),
            ("G6", "I-001; forget the " * (n // 18) + "rest"), ("G6", "I-008 trumps " * (n // 13) + "I-001"),
            ("G6", "I-001 until " * (n // 12) + "I-004"), ("G6", "from I-001 up to " * (n // 17)),
            ("G6", "ok w/o " * (n // 7) + "I-005"), ("G6", "ok, I-009 can " * (n // 14)),
            ("G7", "ok? or should I add " * (n // 20) + "I-004"), ("G8a", "I-004 (I prefer I-004 to " * (n // 25)),
            ("G8a", "[17:00] " * (n // 8) + "Joe: I-001"), ("G8a", "[29/09/26, 17:00:12" * (n // 19)),
            ("GB", "[1:00 PM " * (n // 9)), ("G5", "Mia: kill I-003\n" + "me: yes\n" * (n // 8)),
            ("G5", "me: " * (n // 4) + "yes"), ("G5", "a. [x] kill I-003\n" * (n // 18)), ("G5", "(1) [" * (n // 5)),
            ("GB", "raise to 300, just not " * (n // 23)), ("GB", "raise to 300 though not till " * (n // 29)),
            ("G5", "she says no to " * (n // 15)), ("G1", "done, wait " * (n // 11)),
            ("G13", "accept with no edits " * (n // 21)), ("G10", "no " * (n // 3) + "updates"),
            ("G2c", "no rework " * (n // 10)), ("G13", "dont approve yet " * (n // 17)), ("G13", "dont " * (n // 5)),
            ("G0", "uniquement Claude " * (n // 18) + "\ngo"), ("G0", "hors " * (n // 5) + "ligne\ngo"),
            ("G0", "I do not consent " * (n // 17)), ("G0", "web yok " * (n // 8)),
            ("G12", "every ADR except " * (n // 17) + "3"), ("G12", "all of the ADRs but " * (n // 20)),
            ("G1", "done, one more to add " * (n // 22)), ("G1", "done, but I want to add " * (n // 24) + "later"),
            ("G8b", "I-007, I suppose " * (n // 17)), ("G8b", "I-007 - for " * (n // 12)),
            ("G14", "paper copy " * (n // 11)), ("G14", "copy " * (n // 5)), ("G14", "no, " * (n // 4) + "none"),
            ("G14", "no foo " * (n // 7)), ("G13", "changes: to " * (n // 12)),
            ("G13", "changes: in the attached " * (n // 25)), ("G4", "rescue I-012: cheap, get rid of " * (n // 32)),
            ("G2c", "corrections: users don't know what " * (n // 35)),
            ("G13", "changes: we have second " * (n // 24)), ("G0", "I consent " * (n // 10)))
        for gid, text in floods:
            t0 = time.perf_counter()
            gates.parse_reply(gid, text, None, [])
            if gid == "G0":
                gates.parse_kickoff(text, [])
            elif gid not in PICKS:
                gates.canonical(None, gid, {"reply": text})
            self.assertLess(time.perf_counter() - t0, 3.0, (gid, re.sub(r"\s+", " ", text[:24])))
        for text in ("no don't " * (n // 9) + "extend", "ok go " * (n // 6), "go without the " * (n // 15)):
            t0 = time.perf_counter()
            gates._offer(text)  # the v1-run offer
            self.assertLess(time.perf_counter() - t0, 3.0, text[:24])
        for text in ("all right " * (n // 10), "that's what i meant " * (n // 20), "alright " * (n // 8)):
            t0 = time.perf_counter()
            gates.confirms_reading(text)
            gates.amends_reading(text)
            self.assertLess(time.perf_counter() - t0, 3.0, text[:24])


if __name__ == "__main__":
    unittest.main()
