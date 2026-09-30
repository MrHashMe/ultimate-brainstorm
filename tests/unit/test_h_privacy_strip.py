"""Phase H, code privacy (KIT_SPEC 6.8): unfenced code without a code signal right under a sentence or a list item no
longer reaches another vendor (review R-validation-privacy-0, findings 58 and 55): a continuation line under a line
that ends with ':' is code, so are the code shapes a signal did not cover ('key: value', '"key":', '#include', a
decorator, require '...', export default, Dockerfile instructions, '$ ', options, bare names) and the continuation
lines right above the first code line of a run; the templates' hanging-indent prose and lines that only cite stay. An
inline span or a <code> element on a continuation line no longer makes an engine-filtered prompt read as code on the
worker's second pass (NEW-G7-privacy-publish-1), and the continuation test is linear."""

import os
import random
import sys
import time
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


def redteam_jobs(ctx, check_text):
    """The 10.3 red-team jobs (the gpt CRITIC and the claude ADVOCATE) of one checked idea."""
    ctx.write("checks/I-001.md", check_text)
    ctx.write("tournament/cards.md", "## I-001\nTitle: Ward ledger\nProblem: p\nMechanism: m\nFor whom: f\n"
                                     "First version: v\nMain risk: r\nPrior art: ADJACENT\n")
    ctx.state["top"] = ["I-001"]
    jobs = builders.build_jobs(ctx, {"id": "10.3", "fanout": "redteam_pairs", "job": {"kind": "reviewer"}})
    return dict((j["family"], j) for j in jobs)


def check_text(claims):
    return ("## 1. Prior art\n- query: shift swap app; https://example.com; 2026-09-26\nVERDICT: ADJACENT\n"
            "## 2. Steelman\nx\n## 3. Load-bearing claims\n%s## 4. Kill-assumptions\n"
            "- Fails if nurses do not trade | M | survey | <30%%\n## 5. Codebase fit\n"
            "The product already swaps shifts in src/app.py:10.\n"
            "VERDICT: ADJACENT; DIFFERENTIATOR: ward-visible ledger\n" % claims)


class SignalLessCodeTests(unittest.TestCase):
    STRIPPED = {
        # the verifier's p0_signalless shapes: the 2.0.3 strip_code removed every one of them
        "key under a sentence": "The config (config/app.yml:3) sets:\n    password: SECRET_PW\n",
        "keys under a FACT bullet": "- FACT: the db credentials are in config/app.yml:3\n    user: admin\n"
                                    "    password: SECRET_PW\n",
        "dockerfile": "The image (Dockerfile:1) is built with:\n    FROM python:3.11\n    RUN pip install SECRET_pkg\n",
        "shell": "The deploy script (scripts/deploy.sh:4) runs:\n"
                 "    curl -H \"Authorization: Bearer SECRET_TOK\" https://api.internal\n",
        "require": "Boot code (config/boot.rb:1):\n    require 'SECRET_gem'\n",
        "export default": "The entry (src/index.js:9) ends with:\n    export default SECRET_App\n",
        "include": "The header (src/a.c:1):\n    #include \"SECRET.h\"\n",
        "json key": "The settings (settings.json:2):\n    \"apiKey\": \"SECRET_KEY\",\n",
        "decorator then def": "The route (src/app.py:10):\n    @login_required_SECRET\n    def pay(req):\n"
                              "        return 1\n",
        "makefile recipe": "The build target (Makefile:3):\n\tgo build -ldflags SECRET ./...\n",
        "a lead line of several lines": "The charge handler, which is long,\nlives in src/pay.py:10 and reads:\n"
                                        "    charge the SECRET rate\n",
        # inside a list item: the lines above the first code line of the run go with it
        "list: the lines above a signal line": "- F3: the handler (src/pay.py:10)\n    charge the SECRET_rate first\n"
                                               "    total = amount * rate\n",
        "list: under a line that ends with ':'": "- F3: the config reads:\n    the SECRET word\n",
        "list: ':' and a blank line": "- F3: the config reads:\n\n    the SECRET word\n",
        "list: decorator": "- F3: the route (src/app.py:10)\n    @login_required_SECRET\n",
        "list: option": "- F3: deploy (scripts/deploy.sh:4)\n    curl -H SECRET_TOK https://api.internal\n",
        "list: json key": "- F3: settings (settings.json:2)\n    \"apiKey\": \"SECRET_KEY\",\n",
        "list: shell prompt": "- F3: deploy (scripts/deploy.sh:4)\n    $ make SECRET\n",
        "list: bare names": "- F3: the app reads (src/config.py:3)\n    STRIPE_SECRET_KEY, DATABASE_URL\n",
        # the list-marker rule: '-see' is text, so the indented line after the blank is a code block; were '-see' a
        # list item, the signal-less line would be a continuation that stays
        "-see is not a list item": "-see src/pay.py:40\n\n    the SECRET word\n",
    }
    KEPT = {
        # the templates' hanging-indent prose (S5-OPS, P-GROUND, FRAME-DRAFT): every prompt carries it
        "S5-OPS": "(b) Subtraction: remove the component everyone assumes: the core feature, the interface, the "
                  "payment,\n    the human step, the server, the meeting). What still delivers the outcome?\n",
        "P-GROUND key word": "B1. 5-15 existing solutions, products, papers or workarounds: name, mechanism, URL. "
                             "Product\n    variant: include today's workarounds (the workaround is the real "
                             "competitor)\n",
        "P-GROUND one word": "B3. 3-6 mechanism analogues from distant fields, with\n    URL.\n",
        "FRAME-DRAFT": "  - product: Value/pain 30, Reachability 20, Feasibility 20;\n    B2B: Value/pain 25, "
                       "Willingness to pay 20,\n    Evidence of demand 10\n",
        # lines that only cite, also under a line that ends with ':'
        "a citation under ':'": "The handler is here:\n    (source: src/pay.py:10)\n",
        "a source key": "- FACT: swaps are manual\n    source: src/swap.py:42\n",
        "a url": "- FACT: swaps are manual\n    see https://example.com/a\n",
        "a note": "- F2: the cost\n    Note: this is a rough estimate from two sources\n",
        "a path span": "- OBSERVED the session code signs tokens (src/auth/session.py:40)\n"
                       "    with the key from `src/auth/keys.py:3` at start-up\n",
    }

    def test_signal_less_code_is_stripped(self):
        for name, text in self.STRIPPED.items():
            out = pv.strip_code(text)
            self.assertNotIn("SECRET", out, name)
            self.assertIn(MARK, out, name)
            self.assertTrue(pv.contains_code(text), name)
            self.assertEqual(pv.strip_code(out), out, name)

    def test_prose_and_citations_are_kept(self):
        for name, text in self.KEPT.items():
            self.assertEqual(pv.strip_code(text), text, name)
            self.assertFalse(pv.contains_code(text), name)

    def test_the_lead_line_stays(self):
        out = pv.strip_code(self.STRIPPED["decorator then def"])
        self.assertEqual(out, "The route (src/app.py:10):\n" + MARK + "\n")
        out = pv.strip_code(self.STRIPPED["list: the lines above a signal line"])
        self.assertEqual(out, "- F3: the handler (src/pay.py:10)\n  " + MARK + "\n")


class SecondPassTests(unittest.TestCase):
    SHAPES = {
        # NEW-G7-privacy-publish-1: the first pass turned the span or element into the marker, whose '=' was a code
        # signal on the second pass (the worker's contains_code)
        "span": "- FACT: it\n    reads `os.environ[\"K\"]` here\n",
        "sql span": "1. FACT: the query\n    runs `SELECT a FROM b` nightly\n",
        "code element": "- FACT: it\n    uses <code>k</code>\n",
        "element under a sentence": "The handler (src/a.py:3)\n    uses <code>secret</code> here\n",
        # a span or an element that ends the line: blanked the same way on both passes
        "':' then a span": "- FACT: it\n    it is: `import x`\n",
        "':' then an element": "- FACT: it\n    it is: <code>k</code>\n",
        "a span then ':'": "- FACT: it\n    `import x`: blah\n",
    }

    def test_a_filtered_continuation_line_stays_filtered(self):
        for name, text in self.SHAPES.items():
            once = pv.strip_code(text)
            self.assertNotEqual(once, text, name)
            self.assertEqual(pv.strip_code(once), once, name)
            self.assertFalse(pv.contains_code(once), name)

    def test_idempotent_on_random_markdown_with_the_new_shapes(self):
        atoms = ["```", "~~~", "```mermaid", "    x = 1", "\tx", "- item", "1. item", "  - sub", "      deep", "",
                 "", "text line", "`a=1` and `b`", "<pre>", "</pre>", "## head", "> ```", "    - x", "   text",
                 "    return a;", "  y = 2", "-x", "**b** c", "3.14 x", "      z: 1", "    (source: a.py:1)", "- ```",
                 "    " + MARK, "  " + MARK, "1.   x", "     y = 2", "`os.environ[\"X\"]`", "`SELECT a FROM b`",
                 "    reads `os.environ[\"K\"]` here", "    uses <code>k</code>", "    runs `SELECT a FROM b` nightly",
                 "text:", "- item:", "1.   item:", "    it is: `import x`", "    it is: <code>k</code>",
                 "    `import x`: blah", "    user: admin", "    curl -H x y", "    @dec", "    plain words here",
                 "      plain deeper", "    FROM x", "    STRIPE_KEY", "    src/a.py:3", "    see https://x.y/z",
                 "    a `b` c:", "    <code>x</code>:", "text `x`:", "text <code>y</code>:", "  - sub:", "     five",
                 "    \"k\": 1", "<code>", "</code>", "    $ ls", "\t\tdeep tab", "    (src/a.py:3)",
                 "    " + MARK + " tail", "- " + MARK]
        rnd = random.Random(58)
        for _ in range(4000):
            text = "\n".join(rnd.choice(atoms) for _ in range(rnd.randint(1, 16)))
            out = pv.strip_code(text)
            self.assertEqual(pv.strip_code(out), out, repr(text))
            self.assertFalse(pv.contains_code(out), repr(text))

    def test_a_long_continuation_line_is_scanned_in_linear_time(self):
        # the call signal restarted at every '.' of a name run: 80,000 characters took about 9 s
        for text in ("- x\n    " + "a." * 40000, "- x\n    " + "a_b, " * 16000, "x:\n    (" + "a/" * 40000):
            t0 = time.perf_counter()
            pv.strip_code(text)
            self.assertLess(time.perf_counter() - t0, 1.0, text[:20])


class RepoPromptTests(tl.EngineTestCase):
    def test_a_span_on_a_continuation_line_does_not_refuse_the_critic(self):
        # NEW-G7-privacy-publish-1, end to end: the worker refused the engine-filtered 10.3 CRITIC (exit 7, 'contains
        # code') although the prompt held no code
        ctx = software_ctx(self)
        claims = ("- OBSERVED the session code signs tokens (src/auth/session.py:40)\n"
                  "    with the key from `os.environ[\"SIGNING_KEY\"]` at start-up\n"
                  "- OBSERVED the check runs nightly (src/jobs.py:3)\n    as <code>run_check(db)</code>\n")
        gpt = redteam_jobs(ctx, check_text(claims))["gpt"]
        prompt = ctx.read(gpt["prompt_file"])
        self.assertTrue(gpt["privacy"]["code_filtered"])
        self.assertNotIn("SIGNING_KEY", prompt)
        self.assertNotIn("run_check", prompt)
        self.assertIn("(src/auth/session.py:40)\n  %s\n" % MARK, prompt)  # CHECKS is a DATA body: the strict rule
        self.assertFalse(pv.contains_code(prompt))
        self.assertIsNone(adapter.policy_check(gpt, {}, ctx.state, "claude"))

    def test_a_shell_line_under_a_sentence_never_reaches_another_vendor(self):
        # finding 55: a signal-less shell line under a sentence reached the gpt CRITIC through CHECKS
        ctx = software_ctx(self)
        claims = ("- OBSERVED the deploy is scripted (scripts/deploy.sh:4)\nThe deploy script runs:\n"
                  "    curl -H \"Authorization: Bearer SECRET_TOKEN\" https://deploy.internal/hook\n")
        jobs = redteam_jobs(ctx, check_text(claims))
        gpt, claude = jobs["gpt"], jobs["claude"]
        prompt = ctx.read(gpt["prompt_file"])
        self.assertNotIn("SECRET_TOKEN", prompt)
        self.assertIn("The deploy script runs:", prompt)
        self.assertIsNone(adapter.policy_check(gpt, {}, ctx.state, "claude"))
        self.assertIn("SECRET_TOKEN", ctx.read(claude["prompt_file"]))  # the host vendor may see the code

    def test_facts_keep_no_signal_less_code(self):
        # finding 58: unfenced code without a signal under a FACT bullet or a prose line, through FACTS
        ctx = software_ctx(self)
        ctx.write("02_CONTEXT.md", "## A. FACTS\n- F1: the db credentials are in config/app.yml:3\n"
                                   "    user: admin\n    password: SECRET_PW\nThe route (src/app.py:10):\n"
                                   "    @login_required_SECRET\n    def pay(req):\n## B. LANDSCAPE\n- l\n"
                                   "## C. SEARCH BOUNDARY\n- s\n")
        gpt = registry.PLACEHOLDERS["FACTS"](ctx, {"family": "gpt"})
        self.assertNotIn("SECRET", gpt)
        self.assertIn("config/app.yml:3", gpt)
        self.assertIn("The route (src/app.py:10):", gpt)
        self.assertFalse(pv.contains_code(gpt))
        self.assertIn("SECRET_PW", registry.PLACEHOLDERS["FACTS"](ctx, {"family": "claude"}))


if __name__ == "__main__":
    unittest.main()
