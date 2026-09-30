"""Phase R (RA-gate-reader): the reader paths the corpus test (test_r_ra_gate_corpus_q) does not pin (KIT_SPEC 4.12).

- G0: a privacy request or a setting in a sentence is a doubt (asked again), a list item never is; chat, header and
  no-seed lines are no seeds
- G13: a refused or unanswered switch beside other content is asked again, never a paid change round
- G14: a software or growth run asks for the handoff; a handoff the project does not offer is refused
- a field the host filled itself wins over the reply (G5, G13, G14, the v1-run offer)
- the new patterns stay linear on floods
"""

import os
import sys
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fixtures", "engine"))
import engine_testlib as tl  # noqa: E402

from ublib.engine import gates  # noqa: E402


class KickoffDoubts(unittest.TestCase):
    def read(self, text):
        doubts = []
        out = gates.parse_kickoff(text, doubts)
        return [k for k, _w in doubts], len(out["seeds"]["ideas"]), out

    def test_privacy_and_setting_sentences_are_doubts(self):
        for text in ("only use Claude", "no web-search", "web off, go", "go, keep everything local",
                     "don't send my idea to other companies", "Go ahead, but keep this confidential."):
            self.assertEqual(self.read(text)[0], ["privacy"], text)
        for text in ("I want full-auto for this one, go.", "Quick mode is enough for me, go ahead.", "hands-on please, "
                     "I want to review every step"):
            self.assertEqual(self.read(text)[0], ["setting"], text)

    def test_ideas_stay_seeds(self):
        for text in ("a Claude plugin for nurses", "an offline-first app for nurses", "a local farmers market app",
                     "qr code on break room wall", "- I want full-auto scheduling", "- keep it private: a vault app"):
            self.assertEqual(self.read(text)[:2], ([], 1), text)

    def test_chat_header_and_no_seed_lines(self):
        self.assertEqual(self.read("My ideas:\n- a\n- b\ngo")[1], 2)
        doubts, n, out = self.read("Looks good to me - go ahead, thanks!")
        self.assertEqual((doubts, n, out.get("confirm")), ([], 0, True))
        doubts, n, out = self.read("no seeds from me, just go")
        self.assertEqual((doubts, n, out.get("skip_seeds")), ([], 0, True))
        self.assertEqual(self.read("hands on")[2].get("autopilot"), "hands-on")


class HostAndAsks(tl.EngineTestCase):
    def test_g13_switch_beside_content_is_asked(self):
        ctx = self.make_ctx()
        ctx.write_json("10_ARCHITECTURE/candidates/map.json", {"A": {}, "B": {}, "C": {}})
        ctx.state["choice"] = {"idea": "I-001", "arch": "A", "runner_up": "I-002"}
        for reply in ("Switch to B? Costs matter more", "Switch to B? No. The risks are thin."):
            ans, _n, errs = gates.prepare_answer(ctx, "G13", {"reply": reply})
            self.assertIn("mentions a switch", errs[0] if errs else "", reply)
        ans, _n, errs = gates.prepare_answer(ctx, "G13", {"reply": "Switch to B? Costs matter more",
                                                          "action": "approve"})
        self.assertEqual((errs, ans["action"]), ([], "approve"))

    def test_g14_handoff(self):
        for variant, asked in (("software", True), ("growth", True), ("product", False)):
            ctx = self.make_ctx(variant=variant, run_name="2026-09-28-" + variant)
            errs = gates.prepare_answer(ctx, "G14", {"reply": "publish all"})[2]
            self.assertEqual(bool(errs and "Which handoff" in errs[0]), asked, variant)
            ans, _n, errs = gates.prepare_answer(ctx, "G14", {"reply": "publish all", "handoff": "ce"})
            self.assertEqual((errs, ans["publish"], ans["handoff"]), ([], True, "ce"))
            errs = gates.prepare_answer(ctx, "G14", {"reply": "publish all, superpowers"})[2]
            self.assertIn("must be one of ce, speckit, none", errs[0] if errs else "")

    def test_g5_host_fields_win(self):
        ctx = self.make_ctx()
        ctx.state["k4_candidates"] = ["I-003", "I-007"]
        ans, _n, errs = gates.prepare_answer(ctx, "G5", {"reply": "hmm", "kill": ["I-003"]})
        self.assertEqual((errs, ans["kill"]), ([], ["I-003"]))
        self.assertTrue(gates.prepare_answer(ctx, "G5", {"reply": "hmm"})[2])

    def test_v1_offer(self):
        self.assertEqual(gates._v1_offer({"reply": "", "confirm": False}), "stop")
        self.assertEqual(gates._v1_offer({"reply": "wait", "confirm": True}), "go")  # the host's confirm wins
        for reply in ("go later", "wait", "hold on", "go?", "what does extend mean?", "sign it off", "yes, sign off",
                      "signed off"):
            self.assertIsNone(gates._v1_offer({"reply": reply}), reply)
        for reply, want in (("Extend it? No.", "stop"), ("Don't stop, go!", "go"), ("No thanks, I'm done.", "stop"),
                            ("Hmm. Okay, go ahead.", "go")):
            self.assertEqual(gates._v1_offer({"reply": reply}), want, reply)


class Floods(unittest.TestCase):
    def test_linear(self):
        n = 20000
        floods = (("GB", "1" * n), ("GB", "add " * n + "5"), ("GB", "by " * n), ("G0", "no web search " * n),
                  ("G0", "keep " * n + "local"), ("G0", "other " * n + "companies"), ("G0", "quick is " * n),
                  ("G0", "no seeds " * n), ("G0", "leave " * n + "my machine"), ("G0", "go\n" * n),
                  ("G0", "web:no " * n), ("G2c", "\"a\" " * n), ("G10", "'a " * n), ("G10", "yes but " * n),
                  ("G13", "if " * n + "otherwise"), ("G13", "switch " * n), ("G13", "Switch to B? " * n),
                  ("G5", "keep " * n + "I-003"), ("G5", "not I-003 " * n), ("G4", "rescue I-012 later " * n),
                  ("G14", "publish everything other than " * n), ("G14", "later " * n), ("G11", "not A, " * n),
                  ("G12", "accept all except " * n))
        for gid, text in floods:
            t0 = time.perf_counter()
            gates.parse_reply(gid, text, None, [])
            if gid == "G0":
                gates.parse_kickoff(text, [])
            self.assertLess(time.perf_counter() - t0, 10.0, (gid, text[:24]))
        for text in ("wait " * n, "go " * n + "?"):
            t0 = time.perf_counter()
            gates._v1_offer({"reply": text})
            self.assertLess(time.perf_counter() - t0, 10.0, text[:24])


if __name__ == "__main__":
    unittest.main()
