"""Full-auto vendor consent (KIT_SPEC 6.2, docs/PRIVACY.md): the privacy defaults full-auto saves at the first kickoff
keep, beside web / vendors / code, the vendors the G0 card listed as seeing idea text (`vendor_set`). A later full-auto
run asks G0 again when an enabled family's vendor is not in that set, and saves the new set; nothing changed, it is not
asked. Defaults saved without the set (2.0.x) are asked once. `private` typed with the topic and a saved `vendors: no`
behave as before: never asked again for a vendor, since no other vendor sees the idea text. Runs start with `ub init`.
"""

import io
import json
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fixtures", "engine"))
import engine_testlib as tl  # noqa: E402

from ublib.engine import pipeline  # noqa: E402
from ublib.engine import state as st  # noqa: E402

sys.path.insert(0, tl.SCRIPTS)
import ub  # noqa: E402

TWO = ("claude", "gpt")  # anthropic, openai
THREE = ("claude", "gpt", "kimi")  # and moonshot


class VendorConsent(tl.EngineTestCase):
    def kickoff(self, families, private=False):
        """`ub init` of a full-auto run: (the run, its first card: the G0 card when G0 is asked)."""
        deps = tl.FakeDeps(detect=tl.fake_detect(available=families))
        out = io.StringIO()
        with mock.patch.object(sys, "stdout", out):
            rc = ub.main(["init", "--host", "claude-code", "--text", ("private " if private else "") +
                          "full-auto shift-swap app for nurses", "--root", self.project, "--no-preflight", "--json"],
                         deps=deps)
        card = json.loads(out.getvalue())
        self.assertEqual(rc, 0, card)
        return st.Ctx(card["run"], st.load(card["run"]), deps), card

    def asked(self, card):
        return (card.get("type"), card.get("gate")) == ("HUMAN", "G0")

    def answer(self, ctx, reply="go"):
        pipeline.answer_gate(ctx, pipeline.load_steps(), "G0", {"reply": reply})
        self.assertEqual(st.step_state(ctx.state, "0.3"), "done")
        self.assertEqual(ctx.state["gates"]["G0"]["by"], "human")

    def test_the_first_kickoff_saves_the_vendor_set_it_showed(self):
        ctx, card = self.kickoff(TWO)
        self.assertTrue(self.asked(card), card)
        self.answer(ctx, "web: no\ngo")
        self.assertEqual(st.config_get("privacy_defaults"), {"web": False, "vendors": True, "code": False,
                                                             "vendor_set": ["anthropic", "openai"]})

    def test_a_new_vendor_asks_again_and_saves_the_new_set(self):
        st.config_set("privacy_defaults", {"web": True, "vendors": True, "code": False,
                                           "vendor_set": ["anthropic", "openai"]})
        ctx, card = self.kickoff(THREE)
        self.assertTrue(self.asked(card), card)
        self.assertIn("Asked again: your saved full-auto privacy choice did not list moonshot.", json.dumps(card))
        self.answer(ctx)
        self.assertEqual(st.config_get("privacy_defaults")["vendor_set"], ["anthropic", "moonshot", "openai"])
        ctx, card = self.kickoff(THREE)
        self.assertFalse(self.asked(card), card)
        self.assertEqual(ctx.state["gates"]["G0"]["by"], "auto")

    def test_an_unchanged_vendor_set_is_not_asked_again(self):
        ctx, card = self.kickoff(THREE)
        self.assertTrue(self.asked(card), card)
        self.answer(ctx)
        saved = st.config_get("privacy_defaults")
        self.assertEqual(saved["vendor_set"], ["anthropic", "moonshot", "openai"])
        for fams in (THREE, TWO):  # the same vendors, or fewer
            ctx, card = self.kickoff(fams)
            self.assertFalse(self.asked(card), (fams, card))
            self.assertEqual(ctx.state["gates"]["G0"]["by"], "auto")
            self.assertEqual(st.config_get("privacy_defaults"), saved)

    def test_defaults_saved_without_the_vendor_set_are_asked_once(self):
        st.config_set("privacy_defaults", {"web": True, "vendors": True, "code": False})  # as 2.0.x saved them
        ctx, card = self.kickoff(TWO)
        self.assertTrue(self.asked(card), card)
        self.assertNotIn("Asked again", json.dumps(card))
        self.answer(ctx)
        self.assertEqual(st.config_get("privacy_defaults"), {"web": True, "vendors": True, "code": False,
                                                             "vendor_set": ["anthropic", "openai"]})
        ctx, card = self.kickoff(TWO)
        self.assertFalse(self.asked(card), card)

    def test_private_and_a_saved_vendors_no_are_never_asked_for_a_vendor(self):
        st.config_set("privacy_defaults", {"web": True, "vendors": True, "code": False, "vendor_set": ["anthropic"]})
        ctx, card = self.kickoff(THREE, private=True)
        self.assertFalse(self.asked(card), card)  # `private` typed with the topic: as before
        self.assertEqual(ctx.state["privacy"]["allowed_vendors"], ["anthropic"])
        ctx, card = self.kickoff(THREE)
        self.assertTrue(self.asked(card), card)  # the same saved choice without `private`: a new vendor asks
        for saved in ({"web": True, "vendors": False, "code": False},
                      {"web": True, "vendors": False, "code": False, "vendor_set": ["anthropic"]}):
            st.config_set("privacy_defaults", saved)  # `vendors: no` keeps the idea text with the host's vendor
            ctx, card = self.kickoff(THREE)
            self.assertFalse(self.asked(card), (saved, card))
            self.assertEqual(ctx.state["privacy"]["allowed_vendors"], ["anthropic"])
            self.assertEqual(st.config_get("privacy_defaults"), saved)


if __name__ == "__main__":
    unittest.main()
