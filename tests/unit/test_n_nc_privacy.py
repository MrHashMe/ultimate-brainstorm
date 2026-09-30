"""Phase N, NC-privacy (KIT_SPEC 6.7 rule 6 and 6.8).

The origin-label check runs in linear time on a label word followed by a long run of markdown marks (a fill-in blank
'Strategy: ____' or a pasted rule after 'origin'), at every judge job make_job builds, and still refuses a label behind
such a run.

The A2 filter fails closed on headings: a heading after the A2 heading is a term, sent to another vendor only with
the proposed mark on its own line, and a dropped heading's body ends only at the next heading or kept term, so a
'Source: CONTEXT.md' or '**Definition**' line under it, a blank line and the body all go with it.
"""

import os
import re
import sys
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fixtures", "engine"))
import engine_testlib as tl  # noqa: E402

from ublib.engine import builders, registry  # noqa: E402
from ublib.engine import privacy as pv  # noqa: E402

N = 20000  # quadratic before the fix: about 20 s per case; linear: a few ms
LIMIT = 2.0  # seconds, generous for a slow machine
ALIASES = ["S1-01", "S2-01", "S3-01", "H-01"]
FLOODS = ("Strategy: " + "_" * N + " (to be decided)", "Origin:" + "*" * N + "x", "(origin" + "_" * N + "x",
          "Family = " + "`" * N + "x")


class OriginFloodTests(unittest.TestCase):
    def check(self, text):
        t0 = time.perf_counter()
        try:
            pv.check_origin_labels(text, "6.2-claude", aliases=ALIASES, labels=["claude", "gpt"])
            blocked = False
        except pv.PolicyBlock:
            blocked = True
        self.assertLess(time.perf_counter() - t0, LIMIT, text[:20])
        return blocked

    def test_a_run_of_marks_after_a_label_word_is_linear(self):
        for text in FLOODS:
            self.assertFalse(self.check(text), text[:20])

    def test_a_label_behind_a_run_of_marks_is_still_refused(self):
        for text in ("Origin:" + "*" * N + "gpt", "(origin: " + "_" * N + "human)", "written by " + "`" * N + "claude"):
            self.assertTrue(self.check(text), text[:20])


class OriginFloodJobTests(tl.EngineTestCase):
    def test_make_job_for_a_screen_judge_is_linear(self):
        ctx = self.make_ctx(families=("claude", "gpt"))
        ctx.write("pool/S2_vs.md", "### S2-01 Night swap board\n- Pitch: p\n")
        rows = "I-001 | Night swap board | a board | Strategy: %s (fill in at kickoff)\nI-002 | Rota lottery | x" % (
            "_" * N)
        ctx.write("screen/ideas.md", rows + "\n")
        ctx.write("screen/claude.prompt.md", "You are a judge.\n\nIDEAS\n" + pv.fence_data("IDEAS", rows) + "\n")
        spec = {"id": "claude", "template": None, "prompt_file": "screen/claude.prompt.md", "kind": "judge",
                "family": "claude", "tools": "none", "cwd": "empty", "out": "screen/claude.out.json",
                "contract": {"type": "text"}, "checks": ["origin_label"]}
        t0 = time.perf_counter()
        builders.make_job(ctx, {"id": "6.2"}, spec)
        self.assertLess(time.perf_counter() - t0, LIMIT)


INTRO = ("## A2. DOMAIN TERMS (today's system)\n"
         "These words describe the system as it is today, so ideas can be stated unambiguously.\n\n")
SWAP = "\n### Swap KEEPS [proposed]\nAn exchange of two shifts KEEPSB.\n"
# SECRET: text of a term another vendor may not see; KEEP: a [proposed] term's text, which stays
LAYOUTS = (
    # the entries' layouts: the source mark or the body below the heading
    "### Float pool SECRETA\nNurses paid from budget line OPS-449 SECRETAB.\nSource: CONTEXT.md\n",
    "### Bank shift SECRETB\n_Source: CONTEXT.md_\n\nBooked with code BANK-7 SECRETBB.\n",
    "### Rota SECRETC (CONTEXT.md)\nSource: CONTEXT.md\n\nThe weekly plan ROTA-9 SECRETCB.\n",
    "### Rota SECRETD [CONTEXT.md]\n**Definition**\n\nThe weekly plan ROTA-10 SECRETDB.\n",
    # fail closed: a proposed mark the filter cannot tie to the heading, a heading nested under a kept term, a table
    # under a heading, an indented source line
    "### Handover SECRETG\n[proposed]\nA shared note SECRETGB.\n",
    "- **Shift trade KEEPT** [proposed]: two nurses trade\n  ### Roster SECRETH\n\n  The slot record SECRETHB.\n",
    "### Glossary SECRETI\n| Term | Source | Def |\n|---|---|---|\n| Pair KEEPP | proposed | two nurses |\n"
    "| Ward SECRETIB | CONTEXT.md | a unit |\n",
    "### Float SECRETJ\n  Source: CONTEXT.md\nthe body SECRETJB\n",
    # controls: LD's heading case and the wrapped list form
    "### Rota SECRETE (CONTEXT.md)\nThe weekly plan SECRETEB.\n",
    "- **Float pool SECRETF** [CONTEXT.md]: nurses paid from\nbudget line SECRETFB.\n",
)


def marks(text, out):
    toks = sorted(set(re.findall(r"\b(?:SECRET|KEEP)\w*", text)))
    words = set(re.findall(r"\w+", out))
    return [t for t in toks if t.startswith("SECRET") and t in words], [t for t in toks
                                                                         if t.startswith("KEEP") and t not in words]


class A2HeadingTests(unittest.TestCase):
    def test_a_heading_term_goes_whole_unless_its_own_line_is_marked(self):
        for body in LAYOUTS:
            a2 = INTRO + body + SWAP
            out = pv.filter_a2_terms(a2)
            self.assertEqual(marks(a2, out), ([], []), body)
            self.assertIn("These words describe the system as it is today", out)
            self.assertIn("### Swap KEEPS [proposed]\nAn exchange of two shifts KEEPSB.", out)

    def test_a_marked_heading_keeps_its_body_and_a_heading_can_hold_marked_terms(self):
        a2 = (INTRO + "### Swap [proposed]\n**Definition**\n\nAn exchange KEEP1.\n\n### Terms\n"
                      "- **Pair** [proposed]: two nurses KEEP2\n- **Rota** [CONTEXT.md]: plan SECRET\n")
        out = pv.filter_a2_terms(a2)
        self.assertIn("### Swap [proposed]\n", out)
        self.assertIn("An exchange KEEP1.", out)
        self.assertIn("- **Pair** [proposed]: two nurses KEEP2", out)
        for word in ("SECRET", "### Terms", "**Definition**"):
            self.assertNotIn(word, out)


class A2HeadingFactsTests(tl.EngineTestCase):
    def test_facts_for_another_vendor_hold_no_heading_led_context_md_text(self):
        os.makedirs(os.path.join(self.project, ".git"), exist_ok=True)
        for n, body in enumerate(LAYOUTS):
            ctx = self.make_ctx(variant="software", families=("claude", "gpt"), run_name="2026-09-27-a%d" % n)
            a2 = INTRO + body + SWAP
            ctx.write("02_CONTEXT.md", "## A. FACTS\n- F1 FACT (src/swap.py:42): swaps are approved by hand\n\n" +
                      a2 + "\n## B. LANDSCAPE\n- l\n## C. SEARCH BOUNDARY\n- s\n")
            self.assertEqual(marks(a2, registry.facts_text(ctx, "gpt")), ([], []), body)
            host = registry.facts_text(ctx, "claude")  # the host vendor sees every term
            self.assertTrue(all(t in host for t in re.findall(r"\b(?:SECRET|KEEP)\w*", a2)), body)


if __name__ == "__main__":
    unittest.main()
