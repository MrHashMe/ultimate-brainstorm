# -*- coding: utf-8 -*-
"""The findings of the fourth 2.1.0 verify round (KIT_SPEC 4.11, 4.12, 6.2): reply-reader rows turn by turn through
pipeline.answer_gate, and the kickoff privacy reads end to end through `ub`.

A row is (finding, gate, reply, want, says): `want` is `ask` (asked again), `rb` (read back; nothing applied before a
yes) or `act` (applied at once); `says` is a phrase the card's error must hold. Findings: R1 and R2 a contraction
typed without its apostrophe ('havent decided', 'doesnt work') reads as the contraction, so the reply is read back; R3
a take-back in other tenses ('I've had second thoughts') asks at G8a and G4 and is read back elsewhere; R4 a negation
or a no right after a taken ID ('I-009 is not good', 'I-003, I-007, I-009, no', 'I-009 - nope.') asks; R5 `decision
pending` puts the decision off; R6 a gate stores the answers, ideas and reasons as typed (`w/`, `dont`, `B/C`); R7
`can't` and `cannot` after an ID ask and quote the user; R8 `prefer` or `rather` a few words before a range compares
ideas. Privacy: P1 a no the kickoff cannot place (quoted, marked up, `=`, an emoji, a sentence such as `no vendors
please`, `don't send anything to OpenAI`, `only Claude`) asks G0 and names what was unread; P2 a move between hosts
never keeps a host family of a vendor the kickoff did not list; P3 a terminal run with no input never answers such a
G0 with the saved yes; P4 a pair on its own line or after a CJK or Arabic comma or a format mark leaves no punctuation
in the topic.
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
    ("R1", "G4", "rescue I-012: havent decided", "rb", None),
    ("R1", "G4", "rescue I-012: legal hasnt reviewed it", "rb", None),
    ("R1", "G4", "rescue I-012: didnt decide yet", "rb", None),
    ("R1", "G4", "rescue I-012: havent made up my mind", "rb", None),
    ("R1", "G4", "rescue I-012: I wont decide till Friday", "rb", None),
    ("R1", "G4", "rescue I-012: cheap to run", "act", None),
    ("R1", "G11", "B + steal A: havent decided which part", "rb", None),
    ("R1", "G11", "B + steal A: didnt read it", "rb", None),
    ("R1", "G11", "B + steal A: offline cache", "act", None),
    ("R2", "G8b", "I-007: havent decided", "rb", None),
    ("R2", "G8b", "I-007: hasnt been reviewed", "rb", None),
    ("R2", "G8b", "I-007: doesnt work for us", "rb", None),
    ("R2", "G8b", "I-007: wont scale", "rb", None),
    ("R2", "G8b", "I-007: cheap to run", "act", None),
    ("R2", "G9", "passed, 18/20 wasnt conclusive", "rb", None),
    ("R2", "G9", "passed, 18/20 doesnt count", "rb", None),
    ("R2", "G9", "passed, 18/20 used it", "act", None),
    ("R3", "G8a", "I-003, I-007, I-001. I've had second thoughts", "ask", BACK),
    ("R3", "G8a", "I-003, I-007, I-001. Having 2nd thoughts", "ask", BACK),
    ("R3", "G8a", "I-003, I-007, I-001\nsecond thoughts", "ask", BACK),
    ("R3", "G8a", "I-003, I-007, I-001. I had second thoughts", "ask", BACK),
    ("R3", "G4", "rescue I-012: I've had second thoughts", "ask", BACK),
    ("R3", "G4", "rescue I-012: had second thoughts", "ask", BACK),
    ("R3", "G4", "rescue I-012: I'm getting second thoughts", "ask", BACK),
    ("R3", "G8b", "I-007: I've had second thoughts", "rb", None),
    ("R3", "G11", "B + steal A: had second thoughts", "rb", None),
    ("R3", "G9", "passed, 18/20 I got second thoughts", "rb", None),
    ("R4", "G8a", "I-009 is not good. I-003, I-007", "ask", LEAD),
    ("R4", "G8a", "I-009 won't work, I-003, I-007", "ask", LEAD),
    ("R4", "G8a", "I-009 doesnt work. I-003, I-007", "ask", LEAD),
    ("R4", "G8a", "I-003, I-007, I-009 not", "ask", LEAD),
    ("R4", "G8a", "I-003, I-007, I-009 never", "ask", LEAD),
    ("R4", "G8a", "I-003, I-007, I-009 nah", "ask", LEAD),
    ("R4", "G8a", "I-003, I-007, I-009, no", "ask", LEAD),
    ("R4", "G8a", "I-003, I-007, I-009, no thanks", "ask", LEAD),
    ("R4", "G8a", "I-003, I-007, I-009 - nope.", "ask", LEAD),
    ("R4", "G7", "I-009 is not good. I-003, I-007", "ask", LEAD),
    ("R4", "G7", "I-003, I-007, I-009, no", "ask", LEAD),
    ("R4", "G6", "I-003, I-007, I-009 not", "ask", LEAD),
    ("R4", "G8b", "I-003, I-007, I-009 not", "ask", LEAD),
    ("R4", "G8b", "I-009, no", "ask", LEAD),
    ("R4", "G8a", "not I-009. I-003, I-007", "act", None),
    ("R4", "G8a", "I-003, I-007, I-009, no others", "act", None),
    ("R4", "G8a", "I-003, I-007, I-009", "act", None),
    ("R4", "G8a", "I-007 not I-003", "act", None),
    ("R4", "G8a", "I-007 - cheap to run, I-003", "act", None),
    ("R5", "G8b", "I-007: decision pending", "rb", None),
    ("R5", "G4", "rescue I-012: decision pending", "rb", None),
    ("R5", "G4", "rescue I-012: approval pending", "rb", None),
    ("R5", "G11", "B + steal A: approval pending", "rb", None),
    ("R7", "G8a", "I-009 can't work. I-003, I-007", "ask", '"I-009 can\'t"'),
    ("R7", "G8a", "I-009 cannot work. I-003, I-007", "ask", '"I-009 cannot"'),
    ("R8", "G8a", "I prefer idea I-004 to I-009", "ask", "compares ideas"),
    ("R8", "G8b", "I prefer the cheaper I-004 to I-009", "ask", "compares ideas"),
    ("R8", "G8a", "I'd rather have I-004 to I-009", "ask", "compares ideas"),
    ("R8", "G8a", "I-004 to I-009", "ask", "names a range"),
]
# R6: (gate, reply, field, what the gate stores)
STORED = [
    ("G2", "1: offline w/\n2: nurses", "answers", [{"q": "1", "a": "offline w/"}, {"q": "2", "a": "nurses"}]),
    ("G2", "1. we cant use cloud\n2. B/C and D", "answers",
     [{"q": "1", "a": "we cant use cloud"}, {"q": "2", "a": "B/C and D"}]),
    ("G3", "- l'appli dont on a parlé\n- bot w/o login", "ideas", ["l'appli dont on a parlé", "bot w/o login"]),
    ("G4", "rescue I-012: runs offline w/\nconfirm I-004", "rescue", [{"id": "I-012", "reason": "runs offline w/"}]),
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

    def test_a_gate_stores_the_reply_as_typed(self):  # R6
        with mock.patch("os.fsync", lambda fd: None):
            for n, (gate, reply, field, want) in enumerate(STORED):
                with self.subTest(gate=gate, reply=reply):
                    ctx = self.at(gate, 100 + n)
                    self.answer(ctx, gate, {"reply": reply})
                    self.assertEqual(self.saved(ctx, gate)[field], want)  # before, 'offline with', "don't"


class Kickoff(ze.Base):
    def setUp(self):
        super().setUp()
        st.config_set("privacy_defaults", dict(ze.SAVED))

    def test_a_no_the_kickoff_cannot_place_asks_g0(self):  # P1
        for line, key in (('vendors: "no"', "vendors"), ("vendors: `no`", "vendors"), ("vendors: (no)", "vendors"),
                          ("vendors: *no*", "vendors"), ("**vendors:** no", "vendors"), ("`vendors`: no", "vendors"),
                          ('"vendors": "no"', "vendors"), ('{"vendors": false}', "vendors"),
                          ("vendors = no", "vendors"), ("vendors=no", "vendors"), ("web search: no", "web"),
                          ("vendors: ❌", "vendors"), ("vendors: \U0001f44e", "vendors"),
                          ("vendors - no", "vendors"), ("no vendors please", "vendors"),
                          ("no other AI vendors", "vendors"), ("without web search", "web"),
                          ("don’t use web-search", "web"), ("websearch: no", "web"),
                          ("don't send anything to OpenAI", "vendors"), ("only Claude", "vendors"),
                          ("Claude only", "vendors"), ("never let GPT see it", "vendors")):
            for sep in ("\n", ", "):
                with self.subTest(line=line, sep=sep):
                    ctx, card = self.kickoff("full-auto Payroll tool for HR%s%s" % (sep, line))
                    self.assertTrue(self.asked(card), card)  # before, G0 was answered with the saved yes
                    self.assertEqual(ctx.state["options"]["privacy_unread"], [key])
                    self.assertIs(ctx.state["privacy"]["vendors"], True)  # nothing applied before G0's answer
                    self.assertIn("reply `%s: no` to apply it" % key, json.dumps(card))

    def test_topic_words_and_a_typed_no_do_not_ask(self):
        for text in ("full-auto a web app for florists", "full-auto vendor management tool",
                     "full-auto a no-code tool for vendors", "full-auto a GPT wrapper for lawyers",
                     "full-auto a Claude-powered tutor", "full-auto an app that uses OpenAI embeddings",
                     "full-auto an offline app for areas with no internet"):
            with self.subTest(text=text):
                self.assertFalse(self.asked(self.kickoff(text)[1]))
        ctx, card = self.kickoff("full-auto vendors: no Payroll tool for HR, no vendors please")
        self.assertFalse(self.asked(card), card)  # the typed no is taken, so the sentence adds nothing
        self.assertEqual(ctx.state["privacy"]["allowed_vendors"], ["anthropic"])

    def test_the_topic_keeps_no_punctuation_of_a_taken_pair(self):  # P4
        for text, rest in (("full-auto payroll tool for HR,\nvendors: no", "payroll tool for HR"),
                           ("full-auto payroll tool for HR,\r\nvendors: no", "payroll tool for HR"),
                           ("full-auto proposal A kiosk for shift workers,\nweb: no,\nvendors: no",
                            "A kiosk for shift workers"),
                           ("full-auto 工资工具、vendors: no", "工资工具"),
                           ("full-auto أداة رواتب، vendors: no",
                            "أداة رواتب"),
                           ("full-auto payroll tool for HR ‏vendors: no‏", "payroll tool for HR"),
                           ("full-auto payroll tool for HR​, vendors: no", "payroll tool for HR")):
            with self.subTest(text=text):
                p = ub.parse_text(text)
                self.assertEqual((p["rest"], p["privacy"]["vendors"]), (rest, False))
        ctx = self.kickoff("full-auto Payroll tool for HR,\r\nvendors: no\r\n")[0]
        self.assertEqual(ctx.state["topic"], "Payroll tool for HR")


class Moves(ze.Base):
    """P2: `ub continue RUN --host X` twice; the second host never keeps the first host's unlisted family."""

    def move(self, run, host, available, family=None):
        kw = {"host_family": family} if family else {}
        self.call(["continue", run, "--host", host, "--json"],
                  tl.FakeDeps(detect=tl.fake_detect(available=available, **kw)))
        return st.load(run)

    def test_back_from_a_host_of_an_unlisted_vendor(self):
        st.config_set("privacy_defaults", dict(ze.SAVED))
        for host in ("claude-code", "terminal"):
            with self.subTest(host=host):
                ctx = self.kickoff("full-auto vendors: no payroll tool for HR")[0]
                self.move(ctx.run_dir, "codex", ("gpt",), "gpt")
                s = self.move(ctx.run_dir, host, ("claude", "gpt"), "claude" if host != "terminal" else None)
                self.assertEqual((s["host"]["family"], s["privacy"]["allowed_vendors"]), ("claude", ["anthropic"]))
                self.assertIn("openai was not listed at the kickoff", s["families"]["gpt"]["reason"])
                self.assertNotIn('"gpt', json.dumps(s["seats"]))  # before, the run stayed on gpt

    def test_a_third_vendor_host_is_dropped_on_the_next_move(self):
        st.config_set("privacy_defaults", dict(ze.SAVED))
        ctx = self.kickoff("full-auto payroll tool for HR")[0]
        self.move(ctx.run_dir, "kimi", ("kimi",), "kimi")
        for host, family in (("claude-code", "claude"), ("terminal", None)):
            s = self.move(ctx.run_dir, host, ("claude", "gpt", "kimi"), family)
            self.assertEqual((s["host"]["family"], s["privacy"]["allowed_vendors"]),
                             ("claude", ["anthropic", "openai"]))
            self.assertEqual(s["families"]["kimi"]["status"], "excluded")
            self.assertNotIn('"kimi', json.dumps(s["seats"]))


class ClosedStdin(ze.Base):
    """P3: `ub run --text ...` with stdin closed stops at a G0 that asks about an unread no."""
    real = staticmethod(terminal.run_loop)

    def run_closed(self, text):
        out = io.StringIO()
        deps = tl.FakeDeps(detect=tl.fake_detect(available=ze.TWO))
        loop = lambda ctx, steps, lock=None, **k: self.real(ctx, steps, lock, stdin=io.StringIO(""),  # noqa: E731
                                                           stdout=io.StringIO(), max_cards=6)
        before = self.runs()
        with mock.patch.object(terminal, "run_loop", loop), mock.patch.object(sys, "stdout", out):
            ub.main(["run", "--text", text, "--root", self.project, "--no-preflight", "--json"], deps=deps)
        return json.loads(out.getvalue()), st.load((self.runs() - before).pop()), deps

    def runs(self):
        return set(dp for dp, _, fs in os.walk(self.project) if "run.json" in fs)

    def test_an_unread_no_is_never_answered_with_the_saved_yes(self):
        st.config_set("privacy_defaults", dict(ze.SAVED))
        for text in ("full-auto Payroll tool for HR (vendors: no)", "guided Payroll tool for HR\nno vendors please"):
            with self.subTest(text=text):
                card, s, deps = self.run_closed(text)
                self.assertEqual(card.get("type"), "BLOCKED", card)
                self.assertIn("No answer for G0 on stdin (input closed).", json.dumps(card))
                self.assertIsNone(((s.get("gates") or {}).get("G0") or {}).get("state"))
                self.assertEqual(list(deps.batch.launched), [])  # before, the saved yes seated gpt and ran

    def test_a_typed_no_runs_on(self):
        st.config_set("privacy_defaults", dict(ze.SAVED))
        card, s, deps = self.run_closed("full-auto vendors: no Payroll tool for HR")
        self.assertEqual((s["gates"]["G0"]["state"], s["privacy"]["allowed_vendors"]), ("auto", ["anthropic"]))
        self.assertTrue(list(deps.batch.launched))


class Floods(tl.EngineTestCase):
    """Every new or changed pattern reads a 20000-character reply or kickoff in under 3 s."""

    def test_linear(self):
        n = 20000
        kickoffs = ("full-auto x " + "no " * (n // 3), "full-auto no" + " " * n + "x", "full-auto no " + ", " * n,
                    "full-auto vendors" + " " * n + "-", "full-auto vendors " + "-" * n + "x",
                    "full-auto " + "vendors - " * (n // 10), "full-auto vendors:" + "*" * n + "-",
                    "full-auto " + "vendors*" * (n // 8), "full-auto " + "don't use " * (n // 10) + "web",
                    "full-auto without" + " -" * (n // 2) + " vendors", "full-auto only" + " " * n + "x",
                    "full-auto Claude " + "a " * (n // 2) + "only", "full-auto openai" + " " * n + "-" * n + "x",
                    "full-auto " + "only " * (n // 5) + "claude")
        for text in kickoffs:
            t0 = time.perf_counter()
            ub.parse_text(text)
            self.assertLess(time.perf_counter() - t0, 10.0, text[:30])
        replies = (("G8a", "I-003, " + "I-009, no " * (n // 10)), ("G8a", "I-009" + " " * n + "- nope"),
                   ("G8a", "I-009 -" + " " * n + "x"), ("G8a", "I-009, no" + " " * n + "thanks x"),
                   ("G8a", "I-003. " + "I've had " * (n // 9) + "x"), ("G4", "rescue I-012: " + "had " * (n // 4)),
                   ("G8b", "I-007: decision " * (n // 16) + "x"), ("G8b", "I-007: " + "havent " * (n // 7)),
                   ("G8a", "I prefer " + "idea " * (n // 5) + "I-004 to I-009"),
                   ("G8a", "rather " * (n // 7) + "I-004 to I-009"), ("G2", "1: " + "w/ " * (n // 3)),
                   ("G8a", "I-009 " * (n // 6) + "cannot"))
        for gid, text in replies:
            t0 = time.perf_counter()
            gates.parse_reply(gid, text, None, [])
            if gid not in ("G6", "G7", "G8a", "G8b"):
                gates.canonical(None, gid, {"reply": text})
            self.assertLess(time.perf_counter() - t0, 10.0, (gid, text[:24]))


if __name__ == "__main__":
    unittest.main()
