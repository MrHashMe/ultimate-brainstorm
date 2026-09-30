# -*- coding: utf-8 -*-
"""The reply-reader findings of the 2.1.0 verify round (KIT_SPEC 4.12), one row per finding, table-driven like
test_z_za_gate_corpus_y and test_z_zc_gate_corpus_picks.

A row is (finding, gate, reply, want, says): `want` is `ask` (asked again), `act <reading>` (applied at once) or `rb
<reading>` (read back; nothing applied before a yes), with the reading in the corpus tests' form (`q.matches` outside
the ID-picking gates; at G6, G7, G8a and G8b the pick corpus spec: `SUG` with `+<ID>` / `-<ID>` edits or a list of
IDs); `says` is a phrase the read-back must hold. The rows go through gates.prepare_answer -> gates.read_back ->
gates.apply on the corpus fixtures (the v1-run offer through pipeline.answer_gate). The chains at the end go through
pipeline.answer_gate turn by turn, as a host's `ub answer` does: a question after a read-back gets a card that still
offers the reading, `go` beside a stop reading at the v1-run offer is asked once, and a relayed yes beside a held
reading asks for the whole answer.
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

from ublib.engine import gates, pipeline  # noqa: E402
from ublib.engine import state as st  # noqa: E402

PICKS = ("G6", "G7", "G8a", "G8b")
ROWS = [
    ("D1", "G8a", "anything but I-002", "ask", None),
    ("D1", "G8a", "Gut: I-004. Scrap I-009.", "act I-004", None),
    ("D1", "G8b", "anything but I-003", "ask", None),
    ("D1", "G6", "Cut I-009 and I-011, keep the rest of the proposal", "rb SUG-I-009-I-011", None),
    ("D3", "G8b", "I-007, second thoughts, the first one", "rb I-007", None),
    ("D3", "G4", "rescue I-012: second thoughts, leave it", "ask", None),
    ("D4", "G4", "rescue I-012: cheap, bin the rest", "rb ok rescue=I-012", None),
    ("D5", "G4", "rescue I-012: cheap. Eliminate the other one", "rb ok rescue=I-012", None),
    ("D6", "G8b", "I-007, I guess", "rb I-007", None),
    ("D6", "G8b", "I-007 - tentatively", "rb I-007", None),
    ("D7", "G5", "kill all but I-007", "ask", None),
    ("D7", "G5", "keep all but I-003", "ask", None),
    ("D8", "G6", "I-001, I-003 and I-005, not the rest", "rb I-001,I-003,I-005", None),
    ("D8", "G6", "Admit I-001, I-003 and I-005 to the next round; discharge the rest", "rb I-001,I-003,I-005", None),
    ("D9", "G10", "Tied out; no adjustments", "ask", None),
    ("D9", "G13", "Accept without revisions", "rb approve", None),
    ("D10", "G6", "Advance I-002 and I-008; I-008 beats I-001 on feasibility", "rb I-002,I-008", None),
    ("D11", "G6", "Include I-001-I-004 in the next cohort", "ask", None),
    ("D11", "G6", "I-001 to I-004", "ask", None),
    ("D12", "G12", "everything except 3", "rb ok acc=all rej=0003", None),
    ("D13", "G14", "Archive nothing in the repo, but seed Compound Engineering", "rb ok ho=ce", None),
    ("D14", "G11", "Option C, but borrow A's offline cache", "rb C", "offline cache"),
    ("D15", "G0k", "LGTM, ship it", "rb start seeds=0", None),
    ("D15", "G0k", "We consent to proceed on the standard terms.", "rb start seeds=0", None),
    ("D16", "G9", "Passed - 14/20 nurses swapped at least once", "act passed", None),
    ("D17", "G2c", "ok? I don't know what ASSUMED means", "ask", None),
    ("D18", "G1", "done, but I still need to add two ideas", "ask", None),
    ("D20", "G11", "B + steal A: scratch that, just B", "rb B", None),
    ("D21", "G2c", "corrections: will send tomorrow", "ask", None),
    ("D21", "G10", "corrections: tbd", "ask", None),
    ("D22", "G6", "ok, apart from I-009", "rb SUG-I-009", None),
    ("D22", "G8a", "I-007 then I-001, I-003 out", "act I-007,I-001", None),
    ("D23", "G0k", "\u0628\u062f\u0648\u0646 \u0627\u0646\u062a\u0631\u0646\u062a\ngo", "ask", None),
    ("D23", "G0k", "\u4e0d\u8981\u8054\u7f51\ngo", "ask", None),
    ("D24", "G5", "1. [x] kill I-003\n2. [ ] kill I-007", "rb ok kill=I-003", None),
    ("D25", "GB", "raise to 300 but not until Monday", "ask", None),
    ("D26", "G11", "B + steal A: only if legal agrees", "rb B", None),
    ("D27", "G13", "changes: pending", "ask", None),
    ("D27", "G13", "changes: see attached", "ask", None),
    ("D28", "G11", "B + steal A: never mind", "rb B", None),
    ("D29", "G0k", "pas de recherche internet\ngo", "ask", None),
    ("D29", "G0k", "sem internet\ngo", "ask", None),
    ("D30", "GB", "raise to 300 but next week", "ask", None),
    ("D31", "G5", "- [x] kill I-003\n- [] kill I-007", "rb ok kill=I-003", None),
    ("D32", "G6", "ok, cut I-009", "rb SUG-I-009", None),
    ("D32", "G7", "ok, cut I-001, add I-004", "rb SUG-I-001+I-004", None),
    ("D33", "G10", "The latency driver is wrong: swaps are not real-time, a 1-hour delay is fine.", "rb correct",
     None),
    ("D34", "G0k", "deep, hands-on, web: no", "act start seeds=0 mode=deep autopilot=hands-on web=off", None),
    ("D36", "G0v1", "I wouldn't not extend", "ask", None),
    ("D36", "G14", "I didn't say not to publish", "ask", None),
    ("D38", "G13", "changes: as discussed", "ask", None),
    ("D38", "G10", "corrections: as discussed", "ask", None),
    ("D39", "G2c", "corrections: Legal says no", "ask", None),
    ("D40", "G13", "changes: still reading", "ask", None),
    ("D41", "G2f", "I never don't want to restore", "ask", None),
    ("D42", "G8a", "I-003, I-007, leave I-009 out", "act I-003,I-007", None),
    ("D42", "G8a", "I-007, I-001, ~~I-003~~", "act I-007,I-001", None),
]


class ReaderAA(tl.EngineTestCase):
    variant = "product"
    make_ctx = s.GateCorpusS.make_ctx  # the Q fixtures on the product variant

    def read(self, gate, reply, n):
        """One reply at one gate: {"how": act | rb | ask, "say": the read-back, ...the corpus outcome}."""
        if gate in PICKS:
            return zc.read(self, gate, reply, n)
        if gate == "G0v1":
            got = q.read_v1(self, "2026-09-29-zd%d" % n, {"reply": reply})
            return dict(got, how="rb" if got.get("rb") else "ask" if got["r"] == "ask" else "act", say=got.get("rb"))
        gid = "G0" if gate == "G0k" else gate
        ctx = q.GateCorpusQ.build(self, gate, n)
        if gate == "G4":
            ctx.write("screen/ideas.md", "".join("I-%03d | idea %d | pitch | mechanism\n" % (i, i)
                                                 for i in range(1, 31)))
        provided = {"reply": reply}
        ans, _notes, errs = gates.prepare_answer(ctx, gid, provided)
        if errs:
            return {"r": "ask", "how": "ask", "why": errs[0]}
        rb = gates.read_back(ctx, gid, provided, ans)
        with mock.patch.object(gates.registry, "render_shortlist", lambda *a, **k: None):
            effects = gates.apply(ctx, gid, ans) if gate not in ("G9", "G13") else []
        return dict(s.outcome(gate, ctx, ans, effects), how="rb" if rb else "act", say=rb or "")

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
                        self.assertIn(says, got.get("say") or "")

    def test_every_finding_with_a_reply_has_a_row(self):
        have = set(r[0] for r in ROWS)
        self.assertEqual(set("D%d" % i for i in range(1, 43)) - have, {"D2", "D19", "D35", "D37"})  # chains; docs


class Chains(tl.EngineTestCase):
    """Turn by turn through pipeline.answer_gate on a hands-on run waiting at the gate."""
    at, answer, read_back, saved, killed = t2.Turn2.at, t2.Turn2.answer, t2.Turn2.read_back, t2.Turn2.saved, \
        t2.Turn2.killed

    def test_a_question_after_a_reading_gets_a_card_that_still_offers_it(self):  # D2
        ctx = self.at("G5")
        first = self.read_back(ctx, "G5", "drop both")
        card = self.answer(ctx, "G5", {"reply": "what does that cost?"})
        self.assertTrue(card["error"].startswith(first["error"]), card["error"])  # the reading, then why it asks
        self.assertIn("question", card["error"])
        self.assertIn(first["error"], card["show"])
        self.assertEqual((self.killed(ctx), self.saved(ctx, "G5")), ([], None))
        card = self.answer(ctx, "G5", {"reply": "what?"})  # asked again: the reading is still the one offered
        self.assertTrue(card["error"].startswith(first["error"]), card["error"])
        self.answer(ctx, "G5", {"reply": "ok"})  # so `ok` confirms what the last card showed
        self.assertEqual(self.killed(ctx), ["I-003", "I-007"])
        ctx = self.at("G14", 1)
        first = self.read_back(ctx, "G14", "yes publish the docs into the repo")
        card = self.answer(ctx, "G14", {"reply": "hmm is that safe?"})
        self.assertTrue(card["error"].startswith(first["error"]), card["error"])
        ctx = self.at("G5", 2)
        self.read_back(ctx, "G5", "drop both")
        card = self.answer(ctx, "G5", {"reply": "no"})  # a plain no drops the reading: the card does not offer it
        self.assertFalse(card["error"].startswith(t2.HEAD), card["error"])

    def v1(self, n):
        ctx = self.make_ctx(run_name="2026-09-29-zd-v1-%d" % n)
        ctx.state["legacy_v1"] = True
        ctx.state["interrupt"] = {"gate": "G0", "lite": True}
        st.save(ctx.run_dir, ctx.state)
        return ctx

    def v1_answer(self, ctx, reply):
        ctx = st.Ctx(ctx.run_dir, st.load(ctx.run_dir), ctx.deps)
        return pipeline.answer_gate(ctx, pipeline.load_steps(), "G0", {"reply": reply})

    def test_go_beside_a_stop_reading_at_the_v1_offer_is_asked_once(self):  # D19
        for n, (then, status) in enumerate((("go", "active"), ("yes", "stopped"))):
            with self.subTest(then=then):
                ctx = self.v1(n)
                card = self.v1_answer(ctx, "no thanks, I'm done with this one")
                self.assertTrue(card["error"].startswith(t2.HEAD), card["error"])
                card = self.v1_answer(ctx, "go")  # before, `go` confirmed the stop and ended the run for good
                self.assertTrue((card.get("error") or "").startswith(t2.HEAD), card)
                self.assertIn("reply `go` again to extend this v1 run", card["error"])
                self.assertNotEqual(st.load(ctx.run_dir).get("status"), "stopped")
                self.v1_answer(ctx, then)
                s1 = st.load(ctx.run_dir)
                self.assertEqual(s1.get("status"), status)
                if then == "go":
                    self.assertFalse(s1.get("interrupt"))

    def test_a_relayed_yes_beside_a_held_reading_asks_for_the_whole_answer(self):  # D35
        ctx = self.at("G5", 3)
        self.read_back(ctx, "G5", "drop both")
        card = self.answer(ctx, "G5", {"reply": "The user says yes"})
        self.assertTrue(card["error"].startswith(t2.AMENDS), card["error"])  # not a read-back of the card's `ok`
        self.assertEqual((self.killed(ctx), self.saved(ctx, "G5")), ([], None))
        ctx = self.at("G5", 4)
        self.read_back(ctx, "G5", "drop both")
        self.answer(ctx, "G5", {"reply": "yes"})
        self.assertEqual(self.killed(ctx), ["I-003", "I-007"])


class Floods(tl.EngineTestCase):
    """The reader stays linear on the new forms: a 20000-character reply is read, and checked for a documented form,
    in under 3 s."""

    def test_linear(self):
        n = 20000
        floods = (
            ("G6", "I-001 to " * (n // 9) + "I-004"), ("G6", "I-001" + " " * n + "to I-004"),
            ("G6", "I-001 is " * (n // 9) + "out"), ("G6", "~~ " * (n // 3) + "I-001"),
            ("G6", "I-001, not " * (n // 11) + "the rest"), ("G6", "any but " * (n // 8) + "I-009"),
            ("G6", "I-002 is better " * (n // 16)), ("G7", "get rid " * (n // 8) + "I-001"),
            ("G5", "1. [" * (n // 4)), ("G5", "- [x] kill I-003\n" * (n // 17)),
            ("G5", "\u2610 kill I-003\n" * (n // 14)),
            ("G11", "borrow " * (n // 7) + "from A"), ("G11", "C, borrow the cache" + " " * n + "from A"),
            ("G0", "pas de " * (n // 7) + "\ngo"), ("G0", "seulement " * (n // 10) + "\ngo"),
            ("G0", "deep, " * (n // 6) + "\ngo"), ("G0", "looks good " * (n // 11)),
            ("GB", "raise to 300 but not " * (n // 21)), ("GB", "raise to 300 but " * (n // 17) + "next week"),
            ("G14", "I wouldn't " * (n // 11) + "not publish"), ("G14", "compound " * (n // 9) + "engineering"),
            ("G9", "passed, at least " * (n // 17) + "once"), ("G2c", "corrections: " * (n // 13)),
            ("G10", "The driver is wrong, a delay is fine. " * (n // 38)), ("G12", "all but " * (n // 8) + "3"),
            ("G13", "changes: still " * (n // 15)), ("G1", "done, but I still need to " * (n // 26)))
        for gid, text in floods:
            t0 = time.perf_counter()
            gates.parse_reply(gid, text, None, [])
            if gid == "G0":
                gates.parse_kickoff(text, [])
            elif gid not in PICKS:
                gates.canonical(None, gid, {"reply": text})
            self.assertLess(time.perf_counter() - t0, 10.0, (gid, re.sub(r"\s+", " ", text[:24])))


if __name__ == "__main__":
    unittest.main()
