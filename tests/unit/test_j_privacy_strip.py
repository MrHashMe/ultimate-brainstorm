"""Phase J, code privacy (KIT_SPEC 6.8): the strict rule for DATA block bodies (R-validation-privacy-0, findings 58 and
55, NEW-I-HD-privacy-publish-1: every line indented 4+ columns that is not a list item and does not only cite is code,
also at a nested item's content column), a lead line that ends with ':' inside emphasis or after an element's closing
tag introduces code (NEW-I-HD-privacy-publish-2), a heading that holds a <code> element reads the same on both passes,
and a template value that reads differently in its line (a multi-line AUDIENCE) never makes the worker refuse an
engine-filtered prompt (NEW-I-HD-privacy-publish-3)."""

import os
import random
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fixtures", "engine"))
import engine_testlib as tl  # noqa: E402

from ublib import adapter  # noqa: E402
from ublib.engine import builders, registry  # noqa: E402
from ublib.engine import privacy as pv  # noqa: E402

MARK = pv.CODE_MARKER


def software_ctx(case):
    os.makedirs(os.path.join(case.project, ".git"), exist_ok=True)
    return case.make_ctx(variant="software", families=("claude", "gpt"))


def critic_jobs(ctx, claims):
    """The 10.3 red-team jobs (gpt CRITIC, claude ADVOCATE) of one checked idea whose section 3 holds `claims`."""
    ctx.write("checks/I-001.md", "## 1. Prior art\n- query: shift swap app; https://example.com; 2026-09-26\n"
                                 "VERDICT: ADJACENT\n## 2. Steelman\nx\n## 3. Load-bearing claims\n%s"
                                 "## 4. Kill-assumptions\n- Fails if nurses do not trade | M | survey | <30%%\n"
                                 "## 5. Codebase fit\nsrc/app.py:10.\nVERDICT: ADJACENT; DIFFERENTIATOR: d\n" % claims)
    ctx.write("tournament/cards.md", "## I-001\nTitle: Ward ledger\nProblem: p\nMechanism: m\nFor whom: f\n"
                                     "First version: v\nMain risk: r\nPrior art: ADJACENT\n")
    ctx.state["top"] = ["I-001"]
    jobs = builders.build_jobs(ctx, {"id": "10.3", "fanout": "redteam_pairs", "job": {"kind": "reviewer"}})
    return dict((j["family"], j) for j in jobs)


def facts_ctx(case, section_a):
    ctx = software_ctx(case)
    ctx.write("02_CONTEXT.md", "## A. FACTS\n%s## B. LANDSCAPE\n- l\n## C. SEARCH BOUNDARY\n- s\n" % section_a)
    return ctx


class StrictDataBodyTests(unittest.TestCase):
    # code the non-strict rule keeps: at a nested item's content column, under an item indented 1-3 columns, or
    # without a signal under a line that does not end with ':' (2.0.3 stripped every one of them)
    STRIPPED = {
        "nested item's content column": "- F1: payments\n  - the handler (src/pay.py:10) reads:\n"
                                        "    api_key = SECRET_KEY_1\n    charge(card, SECRET_AMOUNT_2)\n",
        "nested, no ':'": "- F1: payments\n  - the handler (src/pay.py:10)\n    def charge(SECRET):\n",
        "item indented 2": "  - F1: the handler (src/pay.py:10)\n    total = SECRET_amount * rate\n",
        "item indented 1": " - F1: the handler (src/pay.py:10)\n     charge(card, SECRET)\n",
        "yaml, several words": "- F1: the db credentials (config/app.yml:3)\n    password: correct horse SECRET_PW\n"
                               "    host: db.internal port 5432\n",
        "header and npm (finding 55)": "- OBSERVED the webhook call signs requests (src/hook.py:3)\n"
                                       "    Authorization: Bearer SECRET_TOKEN\n    npm run deploy SECRET_ENV\n",
        "lowercase sql": "- F2: the nightly job (jobs/report.sql:1)\n    select total from SECRET_orders\n",
        "a list item under the code goes with it": "- F1: the workflow (ci.yml:3)\n    steps\n"
                                                   "      - run: npm publish SECRET_pkg\n",
    }
    KEPT = {
        "a nested item": "- F1: payments\n  - the handler (src/pay.py:10)\n    - a nested item\n",
        "a citation": "- F1: payments\n    (source: src/pay.py:10)\n",
        "a hanging indent under 4 columns": "- F1: the ward swaps shifts by text message, which\n  the manager "
                                            "confirmed (src/a.py:3)\n",
        "a numbered item's continuation": "1. F1: the ward swaps shifts by text message\n   every week\n",
    }

    def test_code_in_a_data_body_is_stripped(self):
        for name, text in self.STRIPPED.items():
            out = pv.strip_code(text, strict=True)
            self.assertNotIn("SECRET", out, name)
            self.assertEqual(pv.strip_code(out, strict=True), out, name)
            prompt = "FACTS\n%s\n" % pv.fence_data("FACTS", text)
            self.assertTrue(pv.contains_code(prompt), name)  # the worker reads a DATA body by the strict rule
            clean = pv.strip_code(prompt)
            self.assertNotIn("SECRET", clean, name)
            self.assertFalse(pv.contains_code(clean), name)

    def test_the_strict_rule_keeps_items_citations_and_shallow_lines(self):
        for name, text in self.KEPT.items():
            self.assertEqual(pv.strip_code(text, strict=True), text, name)
            prompt = "FACTS\n%s\n" % pv.fence_data("FACTS", text)
            self.assertFalse(pv.contains_code(prompt), name)

    def test_template_text_around_a_data_block_keeps_the_prose_rule(self):
        # FRAME-QUESTIONS keeps '     source and cohort; ...' at column 5 under '   - growth:': template text is read
        # by the non-strict rule, and the line after a DATA block follows its END line (a text line)
        prose = "   - growth:\n     source and cohort; how many units\n"
        block = pv.fence_data("CHECKS", "- claim (src/a.py:1)\n    and the SECRET words")
        prompt = prose + "\nCHECKS\n" + block + "\n    and why, in one sentence\n"
        out = pv.strip_code(prompt)
        self.assertIn(prose, out)
        self.assertIn("\n    and why, in one sentence\n", out)
        self.assertNotIn("SECRET", out)
        self.assertEqual(pv.strip_code(out), out)


class EmphasisLeadTests(unittest.TestCase):
    # a ':' that ends the lead line inside emphasis or after an element still introduces the code under it
    STRIPPED = {
        "bold item": "- F3: **the config reads:**\n    the SECRET word\n",
        "bold line": "**The handler is:**\n    charge the SECRET rate\n",
        "bold label with a citation": "**Install (README.md:12):**\n    npm install SECRETpkg\n",
        "underscores": "__Install:__\n    npm install SECRETpkg\n",
        "italic": "*Install:*\n    npm install SECRETpkg\n",
        "html strong": "<strong>Install:</strong>\n    npm install SECRETpkg\n",
        "an element in the lead": "- F3: the handler <code>charge</code> reads:\n    the SECRET word\n",
        "an element in a bold lead": "- F3: **the handler <code>charge</code> reads:**\n    the SECRET word\n",
        "two lines under a bold lead": "**The deploy runs:**\n    heroku run SECRET_TASK\n    and SECRET_TWO\n",
    }
    KEPT = {
        "bold without ':'": "- F3: **the ward** swaps shifts\n    every week by text message\n",
        "':' inside, not at the end": "**Note:** the ward swaps shifts\n    every week by text message\n",
    }

    def test_code_under_an_emphasized_lead_is_stripped(self):
        for name, text in self.STRIPPED.items():
            out = pv.strip_code(text)
            self.assertNotIn("SECRET", out, name)
            self.assertIn(MARK, out, name)
            self.assertEqual(pv.strip_code(out), out, name)

    def test_prose_under_a_lead_without_a_final_colon_stays(self):
        for name, text in self.KEPT.items():
            self.assertEqual(pv.strip_code(text), text, name)

    def test_the_element_lead_keeps_its_colon(self):
        out = pv.strip_code("- F3: **the handler <code>charge</code> reads:**\n    the SECRET word\n")
        self.assertEqual(out, "- F3: **the handler %s:**\n  %s\n" % (MARK, MARK))


class HeadingElementTests(unittest.TestCase):
    def test_a_heading_with_an_element_reads_the_same_on_both_passes(self):
        for text in ("### The <code>charge</code> handler\n    maps `order -> invoice` first\n",
                     "## The <code>charge</code> handler\n    reads `{ id, total }` from the queue\n",
                     "## The <code>charge</code> handler\n    and nothing else\n",
                     "## A <pre>x\ny</pre>\n    maps `order -> invoice` first\n"):
            out = pv.strip_code(text)
            self.assertEqual(pv.strip_code(out), out, text)
            self.assertFalse(pv.contains_code(out), text)
            self.assertNotIn("order -> invoice", out, text)


class FuzzTests(unittest.TestCase):
    ATOMS = ["```", "```mermaid", "    x = 1", "\tx", "- item", "1. item", "  - sub", "      deep", "", "", "text line",
             "`a=1` and `b`", "<pre>", "</pre>", "## head", "    - x", "   text", "  y = 2", "-x", "**b** c",
             "    (source: a.py:1)", "    " + MARK, "  " + MARK, "    reads `os.environ[\"K\"]` here",
             "    uses <code>k</code>", "text:", "- item:", "    it is: <code>k</code>", "    user: admin",
             "    plain words here", "      plain deeper", "    STRIPE_KEY", "    <code>x</code>:", "text <code>y</code>:",
             "<code>", "</code>", "    " + MARK + " tail", "- " + MARK,
             "**Lead:**", "__Lead:__", "- F3: **reads:**", "*Lead:*", "<code>y</code>:**", "text <code>y</code> reads:",
             "text <code>y</code> reads:**", "**a <code>b</code> c:**", "<pre>x</pre>:", "    <code>x</code> c:**",
             "## head <code>x</code>:", "    the words", "<strong>Install:</strong>", "</pre>:**",
             "## The <code>charge</code> handler", "### Step 2: <code>sync</code>", "\t## <code>c</code>", "## A <pre>",
             "    maps `order -> invoice` first", "    and nothing else",
             "    - nested:", "      - deeper", "        nested code", "   - three", "       seven", "  plain two"]
    DELIMITERS = ["<<<DATA FACTS 0123456789abcdef>>>", "<<<END DATA 0123456789abcdef>>>",
                  "<<<DATA CHECKS fedcba9876543210>>>", "<<<END DATA fedcba9876543210>>>"]

    def test_idempotent_and_composable_on_random_markdown(self):
        rnd = random.Random(55)
        for _ in range(3000):
            text = "\n".join(rnd.choice(self.ATOMS) for _ in range(rnd.randint(1, 14)))
            for strict in (False, True):
                out = pv.strip_code(text, strict=strict)
                self.assertEqual(pv.strip_code(out, strict=strict), out, repr((strict, text)))
            # the resolver's path: a DATA value stripped by the strict rule, fenced, then the whole prompt checked
            prompt = "IDEA:\n%s\nBRIEF: x\n" % pv.fence_data("FACTS", pv.strip_code(text, strict=True))
            self.assertFalse(pv.contains_code(prompt), repr(text))
            mixed = "\n".join(rnd.choice(self.ATOMS + self.DELIMITERS * 3) for _ in range(rnd.randint(1, 16)))
            out = pv.strip_code(mixed)
            self.assertEqual(pv.strip_code(out), out, repr(mixed))


class RepoPromptTests(tl.EngineTestCase):
    def test_nested_fact_code_never_reaches_another_vendor(self):
        # NEW-I-HD-privacy-publish-1 and finding 58, through the FACTS placeholder
        ctx = facts_ctx(self, "- F1: payments\n  - the handler (src/pay.py:10) reads:\n"
                              "    api_key = SECRET_KEY_1\n    charge(card, SECRET_AMOUNT_2)\n"
                              "- F2: the db credentials (config/app.yml:3)\n    password: correct horse SECRET_PW\n")
        gpt = registry.PLACEHOLDERS["FACTS"](ctx, {"family": "gpt"})
        self.assertNotIn("SECRET", gpt)
        self.assertIn("- the handler (src/pay.py:10) reads:", gpt)
        self.assertIn("config/app.yml:3", gpt)
        self.assertIn("SECRET_KEY_1", registry.PLACEHOLDERS["FACTS"](ctx, {"family": "claude"}))

    def test_signal_less_lines_under_a_claim_never_reach_the_critic(self):
        # finding 55: a header line and an option-less npm line under a claim that does not end with ':'
        ctx = software_ctx(self)
        jobs = critic_jobs(ctx, "- OBSERVED the webhook call signs requests (src/hook.py:3)\n"
                                "    Authorization: Bearer SECRET_TOKEN\n    npm run deploy SECRET_ENV\n")
        gpt = jobs["gpt"]
        prompt = ctx.read(gpt["prompt_file"])
        self.assertTrue(gpt["privacy"]["code_filtered"])
        self.assertNotIn("SECRET", prompt)
        self.assertIn("- OBSERVED the webhook call signs requests (src/hook.py:3)", prompt)
        self.assertIsNone(adapter.policy_check(gpt, {}, ctx.state, "claude"))
        self.assertIn("SECRET_TOKEN", ctx.read(jobs["claude"]["prompt_file"]))

    def test_a_bold_lead_and_a_heading_element_never_refuse_the_critic(self):
        ctx = software_ctx(self)
        jobs = critic_jobs(ctx, "**The deploy script runs:**\n    heroku run SECRET_TASK\n"
                                "### The <code>charge</code> handler\n    maps `order -> invoice` first\n")
        gpt = jobs["gpt"]
        prompt = ctx.read(gpt["prompt_file"])
        self.assertNotIn("SECRET_TASK", prompt)
        self.assertNotIn("order -> invoice", prompt)
        self.assertIn("**The deploy script runs:**", prompt)
        self.assertIsNone(adapter.policy_check(gpt, {}, ctx.state, "claude"))


class InlineValueTests(tl.EngineTestCase):
    FRAME = ("# FRAME: x\n## Job statement\nWhen x.\n## Problem\nHow might we y?\n"
             "## Audience / boundary\n- charge nurses on wards\n\n    who swap night shifts every week\n"
             "## Hard constraints\n- none\n## Axes\n- Moment: day | night\n")

    def check_job(self, ctx, family, vars_=None):
        ctx.write("screen/ideas.md", "I-001 | Title one | pitch | mech\n")
        spec = {"id": "I-001-%s" % family, "template": "CHECK", "family": family, "kind": "checker", "tools": "none",
                "cwd": "empty", "out": "checks/I-001.%s.md" % family, "contract": registry.tcontract("CHECK"),
                "vars": dict({"IDEA_ID": "I-001"}, **(vars_ or {}))}
        return builders.make_job(ctx, {"id": "7.1"}, spec)

    def test_a_multi_line_audience_never_refuses_the_check_prompt(self):
        # NEW-I-HD-privacy-publish-3: 'AUDIENCE: {{AUDIENCE}}' put a list item's second paragraph under a text line,
        # which the whole prompt reads as an indented code block: the worker refused the prompt (exit 7)
        ctx = software_ctx(self)
        ctx.write("01_FRAME.md", self.FRAME)
        job = self.check_job(ctx, "gpt")
        prompt = ctx.read(job["prompt_file"])
        self.assertIn("AUDIENCE:\n- charge nurses on wards\n\n    who swap night shifts every week\n", prompt)
        self.assertIsNone(adapter.policy_check(job, {}, ctx.state, "claude"))

    def test_the_tournament_header_puts_the_audience_on_its_own_line(self):
        text = builders.template_text("TOURNAMENT-HEADER")
        self.assertIn("AUDIENCE:\n{{AUDIENCE}}\n", text)
        self.assertIn("AUDIENCE:\n{{AUDIENCE}}\n", builders.template_text("CHECK"))

    def test_the_whole_prompt_is_stripped_for_a_code_filtered_family(self):
        # a value that is clean on its own but reads as code in its template line ('BRIEF: {{HMW}}'): make_job strips
        # the whole prompt, so the worker never refuses what the engine built
        ctx = software_ctx(self)
        ctx.write("01_FRAME.md", self.FRAME)
        hmw = "- a brief\n\n    plain words"
        self.assertEqual(pv.strip_code(hmw), hmw)
        job = self.check_job(ctx, "gpt", {"HMW": hmw})
        self.assertIsNone(adapter.policy_check(job, {}, ctx.state, "claude"))
        host = self.check_job(ctx, "claude", {"HMW": hmw})
        self.assertIn("BRIEF: - a brief\n\n    plain words\n", ctx.read(host["prompt_file"]))


if __name__ == "__main__":
    unittest.main()
