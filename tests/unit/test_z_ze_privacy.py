"""Privacy answers the kickoff card does not ask for (KIT_SPEC 6.2, docs/PRIVACY.md): `web: no` / `vendors: no` /
`code: no` typed with the topic apply to that run (a typed `yes` is still G0's to give); `ub config set
privacy_defaults.vendors no` stores a string, which is no saved answer, so G0 asks; `ub continue RUN --host X` never
seats a family of a vendor the answered kickoff did not list; and the 2000-character cap of an [ASSUMPTION: ...] or
[ESTIMATE: ...] tag counts the text, not the blanks around it, and stays linear on floods.
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

from ublib import lints  # noqa: E402
from ublib.engine import gates  # noqa: E402
from ublib.engine import pipeline  # noqa: E402
from ublib.engine import state as st  # noqa: E402

sys.path.insert(0, tl.SCRIPTS)
import ub  # noqa: E402

TWO = ("claude", "gpt")  # anthropic, openai
SAVED = {"web": True, "vendors": True, "code": False, "vendor_set": ["anthropic", "openai"]}


class Base(tl.EngineTestCase):
    def call(self, argv, deps=None):
        out = io.StringIO()
        with mock.patch.object(sys, "stdout", out):
            rc = ub.main(argv, deps=deps)
        card = json.loads(out.getvalue())
        self.assertEqual(rc, 0, card)
        return card

    def kickoff(self, text, families=TWO):
        deps = tl.FakeDeps(detect=tl.fake_detect(available=families))
        card = self.call(["init", "--host", "claude-code", "--text", text, "--root", self.project, "--no-preflight",
                          "--json"], deps)
        return st.Ctx(card["run"], st.load(card["run"]), deps), card

    def asked(self, card):
        return (card.get("type"), card.get("gate")) == ("HUMAN", "G0")


class TypedPrivacy(Base):
    def test_parse_text_takes_the_pairs_out_of_the_topic(self):
        for text in ("full-auto web: no, vendors: no payroll tool for HR", "full-auto payroll tool for HR\nweb:no; "
                     "vendor: off", "full-auto WEB : No payroll tool for HR vendors: false"):
            with self.subTest(text=text):
                p = ub.parse_text(text)
                self.assertEqual(p["privacy"], {"web": False, "vendors": False})
                self.assertEqual((p["autopilot"], p["rest"]), ("full-auto", "payroll tool for HR"))
        self.assertEqual(ub.parse_text("full-auto code: yes payroll tool")["privacy"], {"code": True})
        self.assertEqual(ub.parse_text("full-auto payroll tool for vendors")["privacy"], {})

    def test_the_values_the_kickoff_reads_as_no_count_and_a_no_stands_over_a_yes(self):
        for text in ("full-auto vendors: none payroll tool for HR", "full-auto payroll tool for HR, vendors: never",
                     "full-auto vendors： no payroll tool for HR", "full-auto ven​dors: nope payroll tool for HR",
                     "full-auto ｖｅｎｄｏｒｓ: ｎｏ payroll tool for HR",
                     "full-auto vendors: yes vendors: disabled payroll tool for HR"):
            with self.subTest(text=text):
                p = ub.parse_text(text)
                self.assertEqual((p["privacy"], p["rest"]), ({"vendors": False}, "payroll tool for HR"))
        p = ub.parse_text("full-auto vendors: no procurement tool with a 'preferred vendors: yes/no' column")
        self.assertEqual((p["privacy"], p["rest"]), ({"vendors": False},
                                                     "procurement tool with a 'preferred vendors: yes/no' column"))

    def test_pairs_inside_the_topic_or_idea_stay_there(self):
        for rest in ("Payroll kiosk for shift workers. Platforms - web: no, kiosk: yes. Source code: yes, on GitHub.",
                     "a code: yes/no review bot for pull requests", "web: no-code builder for florists",
                     "a survey app where each question is vendors: yes or no", "code: maybe a linter"):
            with self.subTest(rest=rest):
                p = ub.parse_text("full-auto proposal " + rest)
                self.assertEqual((p["privacy"], p["rest"]), ({}, rest))
        ctx = self.kickoff("full-auto proposal Payroll kiosk. Platforms - web: no, kiosk: yes.")[0]
        self.assertIs(ctx.state["privacy"]["web"], True)  # G0 is asked: nothing saved

    def test_a_no_the_kickoff_cannot_place_makes_the_kickoff_card_ask(self):
        st.config_set("privacy_defaults", dict(SAVED))
        for text in ("full-auto Payroll tool for HR (vendors: no)", "full-auto Payroll tool for HR. vendors: no!",
                     "full-auto Payroll tool for HR\nvendors: no (client NDA)", "full-auto Payroll tool for HR\n"
                     "vendors: no thanks", "full-auto Payroll tool for HR vendors: no and web: no",
                     "full-auto web: maybe vendors: no payroll tool"):
            with self.subTest(text=text):
                ctx, card = self.kickoff(text)
                self.assertTrue(self.asked(card), card)
                self.assertEqual(ctx.state["options"]["privacy_unread"], ["vendors"])
                self.assertIn("reply `vendors: no` to apply it", json.dumps(card))
        ctx, card = self.kickoff("full-auto proposal Payroll kiosk. Platforms - web: no, kiosk: yes.")
        self.assertTrue(self.asked(card), card)  # asked, and the idea keeps its words
        self.assertEqual(ctx.state["topic"], "Payroll kiosk. Platforms - web: no, kiosk: yes.")
        ctx, card = self.kickoff("full-auto a code: yes/no review bot, and a web: no-code builder")
        self.assertFalse(self.asked(card), card)

    def test_every_line_break_ends_a_line_and_the_topic_keeps_its_punctuation(self):
        for sep in ("\r", "\r\n", "\x0b", "\x0c", "\x85", " ", " "):
            with self.subTest(sep=repr(sep)):
                p = ub.parse_text("full-auto Payroll tool for HR%svendors: no%sIt must run on kiosks." % (sep, sep))
                self.assertEqual((p["privacy"], p["rest"]), ({"vendors": False},
                                                             "Payroll tool for HR It must run on kiosks."))
        for text, rest in (("full-auto Payroll tool for HR vendors: no...", "Payroll tool for HR ..."),
                           ("full-auto payroll tool for HR， vendors: none", "payroll tool for HR"),
                           ("full-auto, vendors: no payroll tool", "payroll tool")):
            with self.subTest(text=text):
                p = ub.parse_text(text)
                self.assertEqual((p["privacy"], p["rest"]), ({"vendors": False}, rest))
        with mock.patch("ublib.engine.terminal.run_loop", lambda *a, **k: {"type": "DONE", "say": "x"}):
            self.call(["run", "--text", "stop smoking coach for nurses, vendors: no", "--root", self.project,
                       "--no-preflight", "--json"], tl.FakeDeps(detect=tl.fake_detect(available=TWO)))
        runs = [os.path.join(dp, "run.json") for dp, _, fs in os.walk(self.project) if "run.json" in fs]
        s = st.load(os.path.dirname(runs[0]))
        self.assertEqual((s["topic"], s["privacy"]["vendors"]), ("stop smoking coach for nurses", False))

    def test_a_typed_no_applies_to_the_run_over_the_saved_defaults(self):
        st.config_set("privacy_defaults", dict(SAVED))
        ctx, card = self.kickoff("full-auto web: no, vendors: no payroll tool for HR")
        self.assertFalse(self.asked(card), card)
        p = ctx.state["privacy"]
        self.assertEqual((p["web"], p["vendors"], p["allowed_vendors"]), (False, False, ["anthropic"]))
        self.assertEqual(ctx.state["topic"], "payroll tool for HR")
        self.assertEqual(st.config_get("privacy_defaults"), SAVED)  # this run only

    def test_a_typed_yes_widens_nothing(self):
        st.config_set("privacy_defaults", {"web": False, "vendors": False, "code": False})
        ctx, card = self.kickoff("full-auto vendors: yes, web: yes payroll tool for HR")
        p = ctx.state["privacy"]
        self.assertEqual((p["web"], p["vendors"], p["allowed_vendors"]), (False, False, ["anthropic"]))
        self.assertEqual(ctx.state["topic"], "payroll tool for HR")
        st.config_set("privacy_defaults", None)
        ctx, card = self.kickoff("full-auto vendors: yes payroll tool for HR")
        self.assertTrue(self.asked(card), card)  # nothing saved: the kickoff card asks


class ConfigStrings(Base):
    def test_a_privacy_default_set_as_a_word_is_no_answer_and_g0_asks(self):
        st.config_set("privacy_defaults", dict(SAVED))
        self.call(["config", "set", "privacy_defaults.vendors", "no", "--json"])
        self.assertEqual(st.config_get("privacy_defaults")["vendors"], "no")
        ctx, card = self.kickoff("full-auto payroll tool for HR")
        self.assertIsNone(gates.new_vendors(ctx))
        self.assertTrue(self.asked(card), card)
        self.assertIsNot(ctx.state["privacy"].get("vendors"), "no")
        pipeline.answer_gate(ctx, pipeline.load_steps(), "G0", {"reply": "vendors: no\ngo"})
        self.assertEqual(ctx.state["privacy"]["allowed_vendors"], ["anthropic"])
        self.assertIs(st.config_get("privacy_defaults")["vendors"], False)


class ContinueOnAnotherHost(Base):
    def cont(self, run):
        deps = tl.FakeDeps(detect=tl.fake_detect(available=("gpt", "kimi"), host_family="gpt"))
        self.call(["continue", run, "--host", "codex", "--json"], deps)
        return st.load(run)

    def test_a_vendor_the_kickoff_never_listed_is_not_seated(self):
        st.config_set("privacy_defaults", dict(SAVED))
        ctx, card = self.kickoff("full-auto payroll tool for HR")
        self.assertFalse(self.asked(card), card)  # G0 answered from the saved defaults
        s = self.cont(ctx.run_dir)
        self.assertEqual(s["families"]["kimi"]["status"], "excluded")
        self.assertIn("moonshot was not listed at the kickoff", s["families"]["kimi"]["reason"])
        self.assertEqual(s["privacy"]["allowed_vendors"], ["anthropic", "openai"])  # claude stays allowed for later
        self.assertNotIn("kimi", json.dumps(s["seats"]))

    def test_a_terminal_continue_hosts_the_run_only_on_a_listed_vendor(self):
        st.config_set("privacy_defaults", dict(SAVED))
        ctx = self.kickoff("full-auto vendors: no payroll tool for HR")[0]
        self.assertEqual(ctx.state["privacy"]["allowed_vendors"], ["anthropic"])
        for available, host in ((("kimi",), "claude"), (("claude", "kimi"), "claude"), (("gpt", "kimi"), "claude")):
            with self.subTest(available=available):
                deps = tl.FakeDeps(detect=tl.fake_detect(available=available))
                self.call(["continue", ctx.run_dir, "--host", "terminal", "--json"], deps)
                s = st.load(ctx.run_dir)
                self.assertEqual((s["host"]["family"], s["privacy"]["allowed_vendors"]), (host, ["anthropic"]))
                self.assertNotIn("kimi", json.dumps(s["seats"]))
                self.assertNotIn("gpt", json.dumps(s["seats"]))

    def test_the_kickoff_vendor_is_never_called_unlisted_after_a_vendors_no_move(self):
        st.config_set("privacy_defaults", dict(SAVED))
        ctx = self.kickoff("full-auto vendors: no payroll tool for HR")[0]
        for host, available, family in (("codex", ("gpt",), "gpt"), ("claude-code", ("claude", "gpt"), "claude")):
            deps = tl.FakeDeps(detect=tl.fake_detect(available=available, host_family=family))
            self.call(["continue", ctx.run_dir, "--host", host, "--json"], deps)
        s = st.load(ctx.run_dir)
        self.assertEqual(s["privacy"]["kickoff_vendors"], ["anthropic"])
        self.assertNotEqual(s["families"]["claude"].get("status"), "excluded", s["families"]["claude"])
        self.call(["continue", ctx.run_dir, "--host", "codex", "--json"],
                  tl.FakeDeps(detect=tl.fake_detect(available=("gpt",), host_family="gpt")))
        self.call(["continue", ctx.run_dir, "--host", "terminal", "--json"],
                  tl.FakeDeps(detect=tl.fake_detect(available=("claude",))))
        s = st.load(ctx.run_dir)
        self.assertEqual((s["host"]["family"], s["privacy"]["allowed_vendors"]), ("claude", ["anthropic"]))

    def test_before_the_kickoff_is_answered_the_new_host_lists_its_vendors(self):
        ctx, card = self.kickoff("hands-on payroll tool for HR")
        self.assertTrue(self.asked(card), card)
        s = self.cont(ctx.run_dir)
        self.assertEqual(s["families"]["kimi"]["status"], "ok")
        self.assertIn("moonshot", s["privacy"]["allowed_vendors"])


class TagCap(unittest.TestCase):
    TEXT = ("Clinics share rosters " * 100)[:1999] + "x"

    def test_blanks_around_the_text_do_not_count(self):
        for tag in ("ASSUMPTION", "ESTIMATE"):
            for before, after in (("", " "), (" ", "\t "), (" ", ""), ("  ", " ")):
                with self.subTest(tag=tag, before=before, after=after):
                    got = lints.extract_assumptions("[%s:%s%s%s]" % (tag, before, self.TEXT, after))
                    self.assertEqual(len(got), 1)
                    self.assertTrue(got[0][1].endswith("x"))
            self.assertEqual(lints.extract_assumptions("[%s:  \t ]" % tag), [])

    def test_floods_stay_linear(self):
        for text in ("[ASSUMPTION:" + " " * 200000, ("[ESTIMATE:" + "\t" * 3000) * 200, "[ASSUMPTION: " * 20000,
                     "[ASSUMPTION:     x" * 20000):
            start = time.perf_counter()
            self.assertEqual(lints.extract_assumptions(text), [])
            self.assertLess(time.perf_counter() - start, 3.0, text[:20])


if __name__ == "__main__":
    unittest.main()
