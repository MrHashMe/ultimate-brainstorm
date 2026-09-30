# -*- coding: utf-8 -*-
"""The findings of the fifth 2.1.0 verify round (KIT_SPEC 4.11, 4.12, 6.3): reply-reader rows turn by turn through
pipeline.answer_gate, the host moves of a run that answered `vendors: no`, and a terminal G0 with no input left.

A row is (finding, gate, reply, want, says): `want` is `ask` (asked again), `rb` (read back; nothing applied before a
yes) or `act` (applied at once); `says` is a phrase the card's error must hold. Findings: R1 an exclusion verb put
after a taken ID ('I-009 reject', 'I-009 vetoed', 'I-009 scrap') asks; R2 a no after a run of punctuation ('I-009 --
no', 'I-009 [no]', 'I-009 thanks, no') asks; D1 at G8a, which has no read-back, a rejection right after a taken ID and
a separator ('I-007: not good', "I-007, doesn't work") asks; R4 more take-backs ('a second thought', 'just had',
'get', 'keep having', 'me having'); R5 'changed my mind', 'second guessing', 'oops' and 'cancel that' take back; R6
longer deferrals ('the legal review is still pending', 'on hold until Friday', 'I will decide tomorrow'); O1 a later
item that repeats part of an earlier rewritten one stays as typed, and so do the cells of a JSON reply.
"""
import io
import json
import os
import sys
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fixtures", "engine"))
import engine_testlib as tl  # noqa: E402
import test_z_za_readback_turn2 as t2  # noqa: E402
import test_z_ze_privacy as ze  # noqa: E402

from ublib.engine import gates  # noqa: E402
from ublib.engine import state as st  # noqa: E402
from ublib.engine import terminal  # noqa: E402

sys.path.insert(0, tl.SCRIPTS)
import ub  # noqa: E402

BACK = "takes itself back"
LEAD = "I cannot tell whether it takes or leaves out I-009"
ROWS = [
    ("R1", "G8a", "I-003, I-007, I-009 reject", "ask", LEAD),
    ("R1", "G8a", "I-009 reject. I-003, I-007", "ask", LEAD),
    ("R1", "G8a", "I-003, I-007, I-009 vetoed", "ask", LEAD),
    ("R1", "G8a", "I-003, I-007, I-009 nix", "ask", LEAD),
    ("R1", "G8a", "I-003, I-007, I-009 scrap", "ask", LEAD),
    ("R1", "G8a", "I-003, I-007, I-009 skipped", "ask", LEAD),
    ("R1", "G8a", "I-003, I-007, I-009 kill", "ask", LEAD),
    ("R1", "G8a", "I-003, I-007, I-009 discarded", "ask", LEAD),
    ("R1", "G8a", "I-003, I-007, I-009 dead", "ask", LEAD),
    ("R1", "G7", "I-003, I-007, I-009 vetoed", "ask", LEAD),
    ("R1", "G6", "I-003, I-007, I-009 reject", "ask", LEAD),
    ("R1", "G8b", "I-009 ditched", "ask", LEAD),
    ("R1", "G6", "I-003,I-007,I-010 kill the others", "rb", None),
    ("R1", "G6", "I-003, I-007, I-010 kill the rest", "rb", None),
    ("R1", "G8a", "I-003, I-007 skip the rest", "act", None),
    ("R2", "G8a", "I-003, I-007, I-009 -- no", "ask", LEAD),
    ("R2", "G8a", "I-003, I-007, I-009... no", "ask", LEAD),
    ("R2", "G8a", "I-003, I-007, I-009 -> no", "ask", LEAD),
    ("R2", "G8a", "I-003, I-007, I-009 thanks, no", "ask", LEAD),
    ("R2", "G8a", "I-003, I-007, I-009 ~ no", "ask", LEAD),
    ("R2", "G8a", "I-003, I-007, I-009 [no]", "ask", LEAD),
    ("R2", "G8a", "I-009 -- no\nI-003\nI-007", "ask", LEAD),
    ("R2", "G7", "I-003, I-007, I-009 -- no", "ask", LEAD),
    ("R2", "G8b", "I-009 -- no", "ask", LEAD),
    ("R2", "G8a", "I-003 -- no risk", "act", None),
    ("R2", "G8a", "I-003, I-007 [no comment]", "act", None),
    ("R2", "G8a", "I-003 (no idea why)", "act", None),
    ("D1", "G8a", "I-007: doesnt work for us", "ask", "I-007"),
    ("D1", "G8a", "I-007: not good", "ask", "I-007"),
    ("D1", "G8a", "I-007: rejected", "ask", "I-007"),
    ("D1", "G8a", "I-007, doesn't work", "ask", "I-007"),
    ("D1", "G8a", "I-007 (not good)", "ask", "I-007"),
    ("D1", "G8a", "I-007 = no", "ask", "I-007"),
    ("D1", "G8a", "I-009 -- nope", "ask", "I-009"),
    ("D1", "G8a", "I-007, I-004 -- no", "ask", "I-004"),
    ("D1", "G8a", "I-003, I-007, I-009 (no)", "ask", "I-009"),
    ("D1", "G8a", "I-007, not sure", "act", None),
    ("D1", "G8a", "I-003, I-007, not I-009", "act", None),
    ("D1", "G8a", "I-003, I-007, I-009, no others", "act", None),
    ("D1", "G8b", "I-007: doesnt work for us", "rb", None),
    ("D1", "G8b", "I-007: won't scale", "rb", None),
    ("R4", "G8a", "I-003, I-007, I-001. I'm having a second thought", "ask", BACK),
    ("R4", "G8a", "I-003, I-007, I-001. I am starting to get second thoughts", "ask", BACK),
    ("R4", "G4", "rescue I-012: I've had a second thought", "ask", BACK),
    ("R4", "G4", "rescue I-012: I keep having second thoughts", "ask", BACK),
    ("R4", "G8b", "I-007: me having second thoughts", "rb", None),
    ("R4", "G11", "B + steal A: just had second thoughts", "rb", None),
    ("R4", "G9", "passed, 18/20. I am starting to get second thoughts", "rb", None),
    ("R4", "G4", "rescue I-012: let users have second thoughts before paying", "act", None),
    ("R4", "G4", "rescue I-012: I need a second thought leader page", "act", None),
    ("R5", "G8b", "I-007: I changed my mind", "rb", None),
    ("R5", "G8b", "I-007: oops", "rb", None),
    ("R5", "G8b", "I-007: disregard that", "rb", None),
    ("R5", "G4", "rescue I-012: second guessing", "ask", BACK),
    ("R5", "G9", "passed, 18/20. strike that", "rb", None),
    ("R5", "G11", "B + steal A: cancel that", "rb", None),
    ("R5", "G8a", "I-003, I-007, I-001. I changed my mind", "ask", BACK),
    ("R5", "G4", "rescue I-012: nurses did not change my mind about the price", "act", None),
    ("R5", "G11", "B + steal A: cancel that subscription flow", "act", None),
    ("R6", "G8b", "I-007: the legal review is still pending", "rb", None),
    ("R6", "G8b", "I-007: on hold until Friday", "rb", None),
    ("R6", "G4", "rescue I-012: approval from legal is still pending", "rb", None),
    ("R6", "G4", "rescue I-012: I will decide tomorrow", "rb", None),
    ("R6", "G11", "B + steal A: the decision is still pending on my side", "rb", None),
    ("R6", "G9", "passed, 18/20, I will decide tomorrow", "rb", None),
    ("R6", "G4", "rescue I-012: it speeds up the pending approval queue for nurses", "act", None),
    ("R6", "G4", "rescue I-012: we could pilot it on hold lines", "act", None),
    ("R6", "G8b", "I-007: hospitals will decide faster with it", "act", None),
]
# O1: (gate, reply, field, what the gate stores)
STORED = [
    ("G3", "- bot w/o login\n- out login", "ideas", ["bot w/o login", "out login"]),
    ("G3", "- 1 n 2 users\n- and", "ideas", ["1 n 2 users", "and"]),
    ("G2", "1: cheap w/ x\n2: with x", "answers", [{"q": "1", "a": "cheap w/ x"}, {"q": "2", "a": "with x"}]),
    ("G2", "1: it isnt fine\n2: it isn't fine", "answers",
     [{"q": "1", "a": "it isnt fine"}, {"q": "2", "a": "it isn't fine"}]),
]


class Chains(tl.EngineTestCase):
    """Turn by turn through pipeline.answer_gate on a hands-on run waiting at the gate."""
    at, answer, saved = t2.Turn2.at, t2.Turn2.answer, t2.Turn2.saved

    def test_rows(self):
        with mock.patch("os.fsync", lambda fd: None):
            for n, (finding, gate, reply, want, says) in enumerate(ROWS):
                with self.subTest(finding=finding, gate=gate, reply=reply):
                    ctx = self.at(gate, n)
                    card = self.answer(ctx, gate, {"reply": reply})
                    err = " ".join(str(card.get("error") or "").split())
                    got = "rb" if err.startswith(gates.READBACK_HEAD) else "ask" if err else "act"
                    self.assertEqual(got, want, card)
                    self.assertEqual(self.saved(ctx, gate) is None, want != "act", card)
                    if says:
                        self.assertIn(says, err)

    def test_a_long_pending_status_is_a_deferral_in_a_reason_but_not_after_changes(self):  # R6
        for text in ("the legal review is still pending", "approval from legal is still pending",
                     "the decision is still pending on my side"):
            with self.subTest(text=text):
                self.assertIn("puts the decision off", gates._label_doubt(text) or "")
                self.assertIsNone(gates._label_doubt(text, False))  # the `changes:` text is read back whole anyway
        for text in ("decision pending", "changes pending", "pending legal"):
            with self.subTest(text=text):
                self.assertIn("puts the decision off", gates._label_doubt(text, False) or "")
        for text in ("note that the pilot results are still pending", "add a step for the pending approvals"):
            with self.subTest(text=text):
                self.assertIsNone(gates._label_doubt(text, False))

    def test_a_later_item_that_repeats_an_earlier_one_stays_as_typed(self):  # O1
        with mock.patch("os.fsync", lambda fd: None):
            for n, (gate, reply, field, want) in enumerate(STORED):
                with self.subTest(gate=gate, reply=reply):
                    ctx = self.at(gate, 100 + n)
                    self.answer(ctx, gate, {"reply": reply})
                    self.assertEqual(self.saved(ctx, gate)[field], want)  # before, item 2 took item 1's rewrite

    def test_the_cells_of_a_json_reply_stay_as_typed(self):  # O1
        got = gates.parse_reply("G3", '{"ideas": [], "cells": [["bot w/o login", "x"]]}', None, [])
        self.assertEqual(got.get("cells"), [["bot w/o login", "x"]])  # before, 'bot without login'


class Moves(ze.Base):
    """`ub continue RUN --host X` after a kickoff that answered `vendors: no`."""

    def move(self, run, host, available, family=None):
        kw = {"host_family": family} if family else {}
        self.call(["continue", run, "--host", host, "--json"],
                  tl.FakeDeps(detect=tl.fake_detect(available=available, **kw)))
        return st.load(run)

    def test_a_host_of_no_known_family_keeps_no_unlisted_host_family(self):  # P4
        st.config_set("privacy_defaults", dict(ze.SAVED))
        ctx = self.kickoff("full-auto vendors: no payroll tool for HR")[0]
        self.move(ctx.run_dir, "codex", ("gpt",), "gpt")
        self.call(["continue", ctx.run_dir, "--host", "other", "--json"],
                  tl.FakeDeps(detect=tl.fake_detect(available=("claude", "gpt"), host_family=None)))
        s = st.load(ctx.run_dir)
        self.assertEqual((s["host"]["family"], s["privacy"]["allowed_vendors"]), ("claude", ["anthropic"]))
        self.assertEqual(s["families"]["gpt"]["status"], "excluded")
        self.assertNotIn('"gpt', json.dumps(s["seats"]))  # before, the run stayed on gpt

    def test_a_host_of_no_known_family_keeps_a_listed_host_family(self):  # P4
        st.config_set("privacy_defaults", dict(ze.SAVED))
        ctx = self.kickoff("full-auto payroll tool for HR")[0]
        self.move(ctx.run_dir, "codex", ("gpt",), "gpt")
        self.call(["continue", ctx.run_dir, "--host", "other", "--json"],
                  tl.FakeDeps(detect=tl.fake_detect(available=("claude", "gpt"), host_family=None)))
        self.assertEqual(st.load(ctx.run_dir)["host"]["family"], "gpt")  # both vendors were listed: no move

    def test_the_host_family_is_not_left_excluded_after_a_round_trip(self):  # P5
        st.config_set("privacy_defaults", dict(ze.SAVED))
        ctx = self.kickoff("full-auto vendors: no payroll tool for HR")[0]
        for host, available, family in (("codex", ("gpt",), "gpt"), ("claude-code", ("claude", "gpt"), "claude")):
            self.move(ctx.run_dir, host, available, family)
        s = self.move(ctx.run_dir, "codex", ("gpt",), "gpt")
        self.assertEqual((s["host"]["family"], s["families"]["gpt"]["status"]), ("gpt", "ok"))
        self.assertNotIn("was not listed", json.dumps(s["families"]["gpt"]))  # before, `gpt off (privacy/kickoff)`
        s = self.move(ctx.run_dir, "claude-code", ("claude", "gpt"), "claude")
        self.assertEqual((s["host"]["family"], s["families"]["gpt"]["status"]), ("claude", "excluded"))

    def test_a_kickoff_answered_again_lists_its_vendors_anew(self):  # P5
        st.config_set("privacy_defaults", dict(ze.SAVED))
        ctx = self.kickoff("full-auto payroll tool for HR")[0]
        s = self.move(ctx.run_dir, "codex", ("gpt",), "gpt")
        self.assertEqual(s["privacy"]["kickoff_vendors"], ["anthropic", "openai"])
        ctx = st.Ctx(ctx.run_dir, s, ctx.deps)
        gates._apply_g0(ctx, {"privacy": {"vendors": False}}, "human")  # a redo of the kickoff, answered `vendors: no`
        self.assertNotIn("kickoff_vendors", ctx.state["privacy"])  # before, the first list stayed


class ClosedStdin(ze.Base):
    """A terminal G0 that shows again after a typed reply is never answered with the saved yes."""
    real = staticmethod(terminal.run_loop)

    def run_typed(self, text, typed):
        out = io.StringIO()
        deps = tl.FakeDeps(detect=tl.fake_detect(available=ze.TWO))
        loop = lambda ctx, steps, lock=None, **k: self.real(ctx, steps, lock, stdin=io.StringIO(typed),  # noqa: E731
                                                           stdout=io.StringIO(), max_cards=6)
        before = self.runs()
        with mock.patch.object(terminal, "run_loop", loop), mock.patch.object(sys, "stdout", out):
            ub.main(["run", "--text", text, "--root", self.project, "--no-preflight", "--json"], deps=deps)
        return json.loads(out.getvalue()), st.load((self.runs() - before).pop()), deps

    def runs(self):
        return set(dp for dp, _, fs in os.walk(self.project) if "run.json" in fs)

    def test_a_no_that_was_read_back_is_never_answered_with_the_saved_yes(self):
        st.config_set("privacy_defaults", dict(ze.SAVED))
        for typed in ("no vendors please\n", "no openai\n", "no\n"):
            with self.subTest(typed=typed):
                card, s, deps = self.run_typed("guided Payroll tool for HR", typed)
                self.assertEqual(card.get("type"), "BLOCKED", card)
                self.assertIn("No answer for G0 on stdin (input closed).", json.dumps(card))
                self.assertIsNone(((s.get("gates") or {}).get("G0") or {}).get("state"))
                self.assertEqual(list(deps.batch.launched), [])  # before, the saved yes seated gpt and ran

    def test_the_fix_command_is_written_with_forward_slashes(self):  # D3
        st.config_set("privacy_defaults", dict(ze.SAVED))
        card = self.run_typed("guided Payroll tool for HR", "no vendors please\n")[0]
        self.assertTrue(card.get("fix"), card)
        self.assertNotIn("\\", "".join(card["fix"]), card)

    def test_a_first_reply_that_acts_and_an_empty_stdin_are_as_before(self):
        st.config_set("privacy_defaults", dict(ze.SAVED))
        s = self.run_typed("guided Payroll tool for HR", "go\n")[1]
        self.assertEqual(s["gates"]["G0"]["state"], "answered", s["gates"]["G0"])
        s = self.run_typed("guided Payroll tool for HR", "")[1]
        self.assertEqual((s["gates"]["G0"]["state"], s["gates"]["G0"].get("by")), ("auto", "auto"))


class Floods(tl.EngineTestCase):
    """Every new or changed pattern reads a 20000-character reply in under 3 s."""

    def test_linear(self):
        n = 20000
        replies = (("G12", "publish" + "\n" * n + "x"), ("G14", "publish" + "\n" * n + "x"),
                   ("G12", "ok" + "\n" * n + "x"), ("G14", "\n" * n + "publish x"),
                   ("G13", "ok" + " " * n + "ok"), ("G10", "ok" + " " * n + "ok"), ("G2c", "ok" + " " * n + "ok"),
                   ("G0", "ok" + " " * n + "ok"), ("G13", "-" * n + " x"), ("G10", "-" * n + " x"),
                   ("G2c", "-" * n + " pending"), ("G13", "'" * n + " x"), ("G4", "rescue I-012: ok" + " " * n + "x"),
                   ("G4", "rescue I-012: ok" + "　" * n + "x"), ("G0", "topic: ok" + "　" * n + "x"),
                   ("G0", "topic: ok" + " " * n + "x"), ("G8b", "I-007: " + "I am " * (n // 5) + "x"),
                   ("G8b", "I-007: on hold" + " " * n + "x"), ("G4", "rescue I-012: " + "word " * (n // 5) + "pending"),
                   ("G4", "rescue I-012: " + "cancel that " * (n // 12) + "x"),
                   ("G4", "rescue I-012: " + "I will decide " * (n // 14) + "x"),
                   ("G8a", "I-009 " + "- " * (n // 2) + "no"), ("G8a", "I-009" + "!" * n + " no"),
                   ("G8a", "I-009 " + "(" * n + " no"), ("G8a", "I-009 thanks " + "," * n + " no"),
                   ("G8a", "I-009, " * (n // 7) + "x"), ("G8a", "I-009 " + "vetoed " * (n // 7)),
                   ("G8a", "I-009: " * (n // 7) + "not"), ("G8b", "I-009 " + " " * n + "-- no"),
                   ("G6", "I-009 " + "skipped " * (n // 8)), ("G6", "I-009 kill" + " " * n + "x"),
                   ("G6", "I-009 kill " * (n // 11)))
        ctx = self.make_ctx(run_name="2026-09-29-zk-flood", autopilot="hands-on")
        for gid, text in replies:
            t0 = time.perf_counter()
            gates.parse_reply(gid, text, None, [])
            if gid not in ("G6", "G7", "G8a", "G8b"):
                gates.canonical(ctx, gid, {"reply": text})
            self.assertLess(time.perf_counter() - t0, 10.0, (gid, text[:24]))


if __name__ == "__main__":
    unittest.main()
