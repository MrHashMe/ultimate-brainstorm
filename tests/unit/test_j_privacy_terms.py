"""Phase J, domain terms for other vendors (KIT_SPEC 6.8): the A2 filter keeps a term only by its 'proposed' source
mark, not by the word, and recognizes every term shape (numbered items, '+' items, table rows, lines naming
CONTEXT.md), so today's-system vocabulary from the repository's CONTEXT.md never reaches another vendor (hunt: A2
filter keeps CONTEXT.md terms)."""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fixtures", "engine"))
import engine_testlib as tl  # noqa: E402

from ublib import adapter  # noqa: E402
from ublib.engine import builders, registry  # noqa: E402
from ublib.engine import privacy as pv  # noqa: E402

A2_BODY = ("These words describe the system as it is today, so ideas can be stated unambiguously. They are not the "
           "solution space: an idea may split, merge, rename, redefine or remove any of these concepts; say which term "
           "it changes.\n\n"
           "- **Rota slot**: a fixed shift in the ward rota (CONTEXT.md)\n"
           "- **Offer**: a proposed shift trade that a manager has not approved yet (CONTEXT.md)\n"
           "- **Swap** (proposed): an exchange of two shifts\n"
           "  - source: the FRAME's domain language\n"
           "  - also called: Rota slot (CONTEXT.md)\n"
           "1. **Float pool**: nurses without a home ward (CONTEXT.md)\n"
           "+ **Charge nurse**: the nurse in charge of a ward on a shift (CONTEXT.md)\n"
           "| **Bank shift** | an extra paid shift outside the contract | CONTEXT.md |\n"
           "Agency cover: a shift filled by an outside agency (CONTEXT.md)\n"
           "| Handover | the proposed hand-over note | proposed |\n")
DROPPED = ("Rota slot", "Offer", "Float pool", "Charge nurse", "Bank shift", "Agency cover")


class A2FilterTests(unittest.TestCase):
    def test_only_terms_with_the_proposed_mark_stay(self):
        out = pv.filter_a2_terms("## A2. DOMAIN TERMS (today's system)\n" + A2_BODY)
        for term in DROPPED:
            self.assertNotIn(term, out, term)
        self.assertIn("These words describe the system as it is today", out)
        self.assertIn("- **Swap** (proposed): an exchange of two shifts\n  - source: the FRAME's domain language\n",
                      out)
        self.assertIn("| Handover | the proposed hand-over note | proposed |", out)
        self.assertNotIn("CONTEXT.md", out)

    def test_the_proposed_mark_shapes(self):
        for line in ("- **Swap** [proposed]: an exchange", "- **Swap**: an exchange (proposed)",
                     "- **Swap**: an exchange (source: proposed)", "**Swap** [ proposed ]: an exchange",
                     "- **Swap**: an exchange. Source: proposed"):
            self.assertEqual(pv.filter_a2_terms(line), line, line)
        for line in ("- **Swap**: a proposed exchange", "- **Swap** (proposed | CONTEXT.md): an exchange",
                     "- **Swap** [proposed]: an exchange, as in CONTEXT.md"):
            self.assertEqual(pv.filter_a2_terms(line), "", line)


class A2FactsTests(tl.EngineTestCase):
    def ctx_with_terms(self):
        os.makedirs(os.path.join(self.project, ".git"), exist_ok=True)
        ctx = self.make_ctx(variant="software", families=("claude", "gpt"))
        ctx.write("01_FRAME.md", "# FRAME: x\n## Job statement\nWhen x.\n## Problem\nHow might we y?\n")
        ctx.write("02_CONTEXT.md", "## A. FACTS\n- F1 FACT (src/swap.py:42): swaps are approved by hand\n\n"
                                   "## A2. DOMAIN TERMS (today's system)\n" + A2_BODY +
                                   "\n## B. LANDSCAPE\n- l\n## C. SEARCH BOUNDARY\n- s\n")
        return ctx

    def test_facts_for_another_vendor_hold_no_context_md_term(self):
        ctx = self.ctx_with_terms()
        text = registry.facts_text(ctx, "gpt")
        self.assertEqual([t for t in DROPPED if t in text], [])
        self.assertIn("**Swap** (proposed)", text)
        self.assertFalse(pv.contains_code(text))
        host = registry.facts_text(ctx, "claude")
        self.assertEqual([t for t in DROPPED if t not in host], [])

    def test_a_fallback_copy_for_another_vendor_holds_no_context_md_term(self):
        ctx = self.ctx_with_terms()
        item = registry._gen_item(ctx, "S5", "S5-OPS", "claude", "pool/S5_operators.md", "S5",
                                  vars_={"SOFTWARE_OP": "yes"})
        step = {"id": "4.2"}
        job = builders.make_job(ctx, step, item)
        fb = builders.fallback_job(ctx, step, job, "gpt")
        text = ctx.read(fb["prompt_file"])
        self.assertEqual([t for t in DROPPED if t in text], [])
        self.assertIn("**Swap** (proposed)", text)
        self.assertIsNone(adapter.policy_check(fb, {}, ctx.state, "claude"))


if __name__ == "__main__":
    unittest.main()
