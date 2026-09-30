"""Phase P (PA-gate-reader): the gate replies the Phase O audit found misread (KIT_SPEC 4.12, 6.10).

- G0 kickoff: a privacy request is kept ('private mode', 'web: no, vendors: no', 'web: off'); an unreadable one, or a
  seed line that mentions privacy, hedges, asks or refuses, is asked again; the v1-run offer asks again on a hedge
- G1 'almost done' / 'not yet', G2f anything but a clear `restore` / `keep`, GB a raise by an amount, G12 a long or
  reversed range, G14 a bare `yes`, G4 an ID with no rescue / confirm / clear verb: asked again
- G4 / G5: each verb takes only its own ID list ('kill I-003, not I-007'), 'kill both' takes the candidates, a
  preference before the verb ('I'd rather kill') is no negation, a deferral word in a reason is content
- G9: `pass` as a noun, or a miss in other words, is never PASSED; G14 'all but X' drops X
- every apostrophe negates ("don´t publish"); the new patterns stay linear on floods
"""

import os
import sys
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fixtures", "engine"))
import engine_testlib as tl  # noqa: E402

from ublib import textio  # noqa: E402
from ublib.engine import gates, pipeline  # noqa: E402
from ublib.engine import state as st  # noqa: E402

MATRIX = {"leader": "A", "leader_status": "clear", "candidates": [
    {"label": "A", "score": 4.0, "rank": 1, "veto": "none"}, {"label": "B", "score": 3.5, "rank": 2, "veto": "none"},
    {"label": "C", "score": 3.0, "rank": 3, "veto": "none"}]}


def parse(gid, reply):
    return gates.parse_reply(gid, reply, None, [])


class Base(tl.EngineTestCase):
    n = 0

    def ctx(self, **kw):
        Base.n += 1
        return self.make_ctx(run_name="2026-09-27-p-pa-%d" % Base.n, **kw)

    def answer(self, ctx, gid, reply):
        ans, _notes, errs = gates.prepare_answer(ctx, gid, {"reply": reply})
        self.assertEqual(errs, [], (gid, reply))
        with mock.patch.object(gates.registry, "render_shortlist", lambda *a, **k: None):
            gates.apply(ctx, gid, ans)
        return ans

    def asked_again(self, ctx, gid, reply):
        _ans, _notes, errs = gates.prepare_answer(ctx, gid, {"reply": reply})
        self.assertTrue(errs, (gid, reply))
        return errs[0]


class KickoffTests(Base):
    def test_privacy_requests_are_kept(self):
        # each started the run with web search on and the ideas going to all 4 vendors
        for reply in ("private mode\ngo", "keep it private, go"):
            ctx = self.ctx()
            self.answer(ctx, "G0", reply)
            self.assertTrue(ctx.state["options"]["private"], reply)
        for reply in ("- idea\nweb: no, vendors: no\ngo", "web: off\nvendor: none\ngo"):
            ctx = self.ctx()
            self.answer(ctx, "G0", reply)
            self.assertFalse(ctx.state["privacy"]["web"], reply)
            self.assertFalse(ctx.state["privacy"]["vendors"], reply)

    def test_an_unclear_privacy_request_or_seed_is_asked_again(self):
        ctx = self.ctx()
        for reply in ("no web search\ngo", "Go ahead, but keep it private", "no vendors please\ngo"):
            self.assertIn("Did you mean a privacy setting", self.asked_again(ctx, "G0", reply), reply)
        self.assertIn("`web: maybe` is unclear", self.asked_again(ctx, "G0", "web: maybe\ngo"))
        self.assertIn("reply `go`", self.asked_again(ctx, "G0", "hmm, not sure"))
        for reply in ("not yet, let me think", "Can you explain the modes?", "maybe an app for rota swaps",
                      "I don't know", "let me think"):
            self.assertIn("as a seed idea?", self.asked_again(ctx, "G0", reply), reply)
        self.assertEqual(ctx.state["seeds"] if "seeds" in ctx.state else None, None)
        ans = self.answer(ctx, "G0", "- no web search needed app\ngo")  # a list item is an idea, not a setting
        self.assertEqual(ans["seeds"]["ideas"], ["no web search needed app"])
        self.assertTrue(ctx.state["privacy"]["web"])

    def test_a_mode_request_in_a_sentence_is_no_seed(self):
        ctx = self.ctx()
        ans = self.answer(ctx, "G0", "use deep mode")
        self.assertEqual(ctx.state["mode"], "deep")
        self.assertEqual(ans["seeds"]["ideas"], [])

    def test_the_v1_offer_asks_again_on_a_hedge(self):
        # each stopped the run for good ('the user declined to extend the v1 run')
        for i, reply in enumerate(("hmm not sure", "Not sure what extend means", "I don't understand",
                                   "no idea what a v1 run is", "maybe not")):
            ctx = self.make_ctx(run_name="2026-09-27-p-pa-v1-%d" % i)
            ctx.state["legacy_v1"] = True
            ctx.state["interrupt"] = {"gate": "G0", "lite": True}
            st.save(ctx.run_dir, ctx.state)
            card = pipeline.answer_gate(ctx, pipeline.load_steps(), "G0", {"reply": reply})
            self.assertEqual((card.get("type"), card.get("gate")), ("HUMAN", "G0"), reply)
            self.assertEqual(ctx.state.get("status"), "active", reply)


class SmallGateTests(Base):
    def test_g1_asks_until_the_seeds_are_written(self):
        ctx = self.ctx()
        ctx.write("00_HUMAN_SEEDS.md", "# Seeds\n\n## Ideas\n- fax\n")
        self.assertIn("once the seeds file is written", self.asked_again(ctx, "G1", "almost done"))
        for reply in ("not yet", "not done yet, still writing", "skip? no, I'm still writing", "give me a minute"):
            self.asked_again(ctx, "G1", reply)
        self.assertNotIn("SKIPPED", textio.read_text(os.path.join(ctx.run_dir, "00_HUMAN_SEEDS.md")))

    def test_g2f_restores_on_everyday_words_and_asks_on_anything_unclear(self):
        # each kept the framing edit in the user's CONTEXT.md
        for reply in ("put it back", "revert it", "undo the change", "restore instead", "roll it back",
                      "don't keep it"):
            self.assertEqual(parse("G2f", reply), {"restore": True}, reply)
        ctx = self.ctx()
        for reply in ("yes", "no", "", "keep? no", "restore and keep"):
            self.assertIn("Reply `restore` or `keep`.", self.asked_again(ctx, "G2f", reply), reply)
        self.assertEqual(parse("G2f", "keep it"), {"restore": False})

    def test_gb_asks_for_the_total_on_a_relative_raise(self):
        ctx = self.ctx()
        for reply in ("raise by 100", "100 more", "add 50", "+50", "another 20"):
            self.assertIn("as the total number of requests", self.asked_again(ctx, "GB", reply), reply)
        self.assertIn("names `stop` and a cap", self.asked_again(ctx, "GB", "stop at 120"))
        self.assertEqual(parse("GB", "raise to 300"), {"raise_to": 300, "stop": False})

    def test_g9_never_reads_a_miss_as_passed(self):
        # 'pass' as a noun, an echoed 'Passed?' refused, and a miss said in other words were PASSED
        for reply in ("pass rate: 3 of 10", "below the pass bar", "pass", "Passed? Well, no.",
                      "passed with 3 of 10, which is a miss", "Passed? Not today.", "did not pass the bar",
                      "passed, but we didn't hit the target", "passed with 3 of 10, falls short"):
            self.assertNotEqual(parse("G9", reply).get("result"), "PASSED", reply)
        self.assertEqual(parse("G9", "failed: 2 of 10 passed the test")["result"], "MISSED")
        self.assertEqual(parse("G9", "fell short: 4/10")["result"], "MISSED")
        self.assertEqual(parse("G9", "passed, 8 of 10 joined the wait list")["result"], "PASSED")

    def test_gx_and_g11_read_the_refusal(self):
        self.assertEqual(parse("GX", "don't continue, stop"), {"action": "stop"})
        ctx = self.ctx()
        ctx.write_json("10_ARCHITECTURE/matrix.json", MATRIX)
        ctx.state["choice"] = {"idea": "I-001", "arch": None, "runner_up": None}
        for reply in ("B? Not today.", "B? Maybe not.", "B? Hmm, no.", "Fine with the suggestion; B was close"):
            self.assertIn("B", self.asked_again(ctx, "G11", reply), reply)
        self.assertEqual(parse("G11", "take B, it can hold more traffic").get("choice"), "B")


class ShortlistTests(Base):
    def g5(self):
        ctx = self.ctx()
        ctx.state["k4_candidates"] = ["I-003", "I-007"]
        ctx.state["killed"] = []
        return ctx

    def test_g5_kills_only_what_the_verb_names(self):
        for reply, kill in (("kill I-003, not I-007", ["I-003"]), ("I'd rather kill I-003", ["I-003"]),
                            ("Too much overlap so kill I-003", ["I-003"]), ("kill i-003", ["I-003"]),
                            ("I don't want to kill I-003", []), ("no need to kill I-003", []),
                            ("I-003: kill, I-007: keep", ["I-003"]), ("kill both", ["I-003", "I-007"]),
                            ("keep I-007 because nurses hate the wait list", [])):
            ctx = self.g5()
            self.answer(ctx, "G5", reply)
            self.assertEqual(sorted(ctx.state["killed"]), kill, reply)
        self.assertIn("by its ID", self.asked_again(self.g5(), "G5", "kill 3 and 7"))
        self.assertEqual(parse("G5", "kill both"), {"kill": [], "keep": []})  # no candidates known: nothing

    def test_g4_takes_each_listed_id_and_asks_without_a_verb(self):
        ans = parse("G4", "rescue I-004 and I-005 because nurses need a wait list")
        self.assertEqual([(r["id"], r["reason"]) for r in ans["rescue"]],
                         [("I-004", "nurses need a wait list"), ("I-005", "nurses need a wait list")])
        ctx = self.ctx()
        self.assertIn("names I-004 without `rescue`", self.asked_again(ctx, "G4", "kill I-004"))
        self.assertIn("by its ID", self.asked_again(ctx, "G4", "confirm all"))
        self.assertEqual(parse("G4", "clear all flags"), {"rescue": [], "confirm_flags": []})
        self.assertEqual(parse("G4", "confirm I-004, not I-005")["confirm_flags"], ["I-004"])

    def test_g12_expands_short_ranges_and_asks_on_long_ones(self):
        self.assertEqual(parse("G12", "reject 2-3")["reject"], ["0002", "0003"])
        ctx = self.ctx(mode="deep")
        for reply in ("reject 3-1", "reject 1-900"):
            self.assertIn("one by one", self.asked_again(ctx, "G12", reply), reply)


class ReviewGateTests(Base):
    def test_change_requests_and_sign_offs(self):
        self.assertEqual(parse("G13", "Please fix the proposal")["action"], "changes")
        self.assertEqual(parse("G13", "sign off"), {"action": "approve"})
        self.assertTrue(parse("G10", "Please fix the drivers")["corrections"])
        for reply in ("no notes", "ok, continue"):
            self.assertEqual(parse("G10", reply), {"confirm": True}, reply)
        ctx = self.ctx()
        self.assertIn("approves and also says more", self.asked_again(ctx, "G13", "approve and publish"))
        self.assertIn("confirms and also says more", self.asked_again(ctx, "G2c", "The problem statement is right"))

    def test_g14_items_and_a_bare_yes(self):
        for reply in ("publish all but the proposal", "publish everything except the proposal",
                      "publish the arch and decision records"):
            self.assertEqual(parse("G14", reply)["publish"], ["architecture", "adr"], reply)
        ctx = self.ctx()
        for reply in ("yes", "go ahead"):
            self.assertIn("Publish (all, or which", self.asked_again(ctx, "G14", reply), reply)
        self.assertIn("both publishes and refuses",
                      self.asked_again(ctx, "G14", "Don't publish, just the architecture"))
        self.assertEqual(parse("G14", "Publish? Hmm, no.")["publish"], False)


class ApostropheTests(unittest.TestCase):
    def test_every_apostrophe_negates(self):
        # the acute accent, backtick, prime and fullwidth apostrophe lost the negation
        for apos in ("´", "`", "′", "＇"):
            self.assertIs(parse("G14", "don%st publish" % apos).get("publish"), False, ascii(apos))
            self.assertEqual(parse("G5", "don%st kill I-003" % apos)["kill"], [], ascii(apos))


class FloodTests(unittest.TestCase):
    def test_the_new_patterns_stay_linear(self):
        n = 20000
        floods = (("G5", "kill I-1, " * n), ("G5", "kill " * n + "I-1"), ("G5", "I-1 " * n + "kill"),
                  ("G4", "rescue I-1, I-2 because " * n), ("G12", "1-2 " * n), ("G12", "9999-9999 " * n),
                  ("G2f", "roll " * n + "back"), ("G14", "publish but the adrs, " * n), ("GB", "+ " * n + "5"),
                  ("G1", "in " * n + "5"), ("G9", "didn't " * n + "pass"), ("G0", "web: no, vendors: no, " * n),
                  ("G0", "web:" * n), ("GX", "continue and wait " * n))
        # a refusal looks back and a question looks ahead: both stay linear ('no, no, ...' took 2.7 s at G13)
        floods += tuple((gid, text) for gid in ("G9", "G10", "G11", "G13", "G14", "GB")
                        for text in ("no, " * n, "B? " * n, "hmm? " * n + "x " * n))
        for gid, text in floods:
            t0 = time.perf_counter()
            gates.parse_reply(gid, text, None, [])
            self.assertLess(time.perf_counter() - t0, 10.0, (gid, text[:24]))


if __name__ == "__main__":
    unittest.main()
