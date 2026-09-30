"""Phase E3, code privacy (KIT_SPEC 6.8): indented code under a paragraph or a list item, CommonMark list markers,
keyword-led and indexing inline spans (review R-validation-privacy-0, findings 55 and 58); fences behind a list marker
close as they open (finding 41); the A2 filter keeps a fallback prompt stable under strip_code and drops a dropped
term's sub-lines (R-validation-privacy-1); a same-vendor fallback of a repository job keeps the repository
(R-validation-privacy-2)."""

import os
import random
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fixtures", "engine"))
import engine_testlib as tl  # noqa: E402

from ublib import adapter, validate  # noqa: E402
from ublib.engine import builders, pipeline, registry  # noqa: E402
from ublib.engine import privacy as pv  # noqa: E402

MARK = pv.CODE_MARKER


def software_ctx(case, families=("claude", "gpt"), **kw):
    os.makedirs(os.path.join(case.project, ".git"), exist_ok=True)
    return case.make_ctx(variant="software", families=families, **kw)


class StripCodeShapeTests(unittest.TestCase):
    STRIPPED = {
        # R-validation-privacy-0 (the 2.0.3 strip_code removed all of these)
        "code under a text line": "The charge handler (src/pay.py:10) is:\n    def charge(amount, rate):\n"
                                  "        return amount * rate + SECRET\n",
        "code under a list item": "- F3: charge() in src/pay.py:10:\n      def charge(amount, rate):\n"
                                  "          return amount * SECRET\n",
        "tab-indented under text": "Config loader:\n\tdb_password = os.environ['SECRET']\n\tconnect(db_password)\n",
        "4 spaces after a list item and a blank": "- F3: the charge function:\n\n    def charge(amount, rate):\n"
                                                  "        return amount * SECRET\n",
        "no blank after the marker is not a list": "-see src/pay.py:40\n\n    total = amount * rate + SECRET\n",
        "a bold lead-in is not a list": "**F3** the charge (src/pay.py:10):\n\n    total = amount * rate + SECRET\n",
        "a number is not a list": "3.14 is the rate in src/pay.py:3\n\n    total = amount * rate + SECRET\n",
        "yaml under text": "The config (config/app.yaml:1) reads:\n    database:\n      password: SECRET\n",
        # finding 58's corpus additions
        "a\\n    x = f(k)": "a\n    x = f(SECRET)",
        "fact bullet then code": "- FACT (src/a.py:1):\n    x = f(SECRET)",
        "numbered fact then code": "1. FACT\n    return salt + SECRET;",
        # finding 55: inline spans that read as code without '=' or a call
        "indexed name": "the key is `os.environ[\"SECRET\"]` here",
        "sql": "it runs `SELECT SECRET FROM users`",
        "import": "it does `import SECRET_crypto`",
        "from import": "it does `from SECRET import x`",
    }
    KEPT = {
        "list continuation with a path": "1. FACT: swaps are manual\n    (source: src/swap.py:42)\n",
        "endpoints": "call `DELETE /swaps/1` and `POST /swaps` and `GET /users/{id}`",
        "paths with brackets": "see `pages/[id].tsx` and `src/app.py:10`",
        "prose call with a blank": "- F2: see them (what counts as a swap)\n    and why (src/a.py:3)\n",
        "one-line schema json": '{"type": "object", "properties": {"a": {"type": "string"}}}',
    }

    def test_code_shapes_are_stripped(self):
        for name, text in self.STRIPPED.items():
            out = pv.strip_code(text)
            self.assertNotIn("SECRET", out, name)
            self.assertIn(MARK, out, name)
            self.assertTrue(pv.contains_code(text), name)
            self.assertEqual(pv.strip_code(out), out, name)

    def test_prose_and_paths_are_kept(self):
        for name, text in self.KEPT.items():
            self.assertEqual(pv.strip_code(text), text, name)
            self.assertFalse(pv.contains_code(text), name)

    def test_idempotent_on_random_markdown_with_the_new_shapes(self):
        atoms = ["```", "~~~", "```mermaid", "    x = 1", "\tx", "- item", "1. item", "  - sub", "      deep", "",
                 "", "text line", "`a=1` and `b`", "<pre>", "</pre>", "## head", "> ```", "    - x", "   text",
                 "    return a;", "  y = 2", "-x", "**b** c", "3.14 x", "      z: 1", "    (source: a.py:1)", "- ```",
                 "    " + MARK, "  " + MARK, "1.   x", "     y = 2", "`os.environ[\"X\"]`", "`SELECT a FROM b`"]
        rnd = random.Random(55)
        for _ in range(3000):
            text = "\n".join(rnd.choice(atoms) for _ in range(rnd.randint(1, 14)))
            out = pv.strip_code(text)
            self.assertEqual(pv.strip_code(out), out, repr(text))
            self.assertFalse(pv.contains_code(out), repr(text))


class ListFenceTests(tl.EngineTestCase):
    DOCS = {
        "list marker": "## A. FACTS\n- builds with:\n- ```bash\n- make build\n- ```\n## A2. DOMAIN TERMS\n- **T** "
                       "[proposed]: t\n## B. LANDSCAPE\n- competitor tool X\n## C. SEARCH BOUNDARY\n- s\n",
        "blockquote": "## A. FACTS\n- builds with:\n> ```\n> make build\n> ```\n## A2. DOMAIN TERMS\n"
                      "- **T** [proposed]: t\n## B. LANDSCAPE\n- competitor tool X\n## C. SEARCH BOUNDARY\n- s\n",
    }

    def test_a_fence_opened_behind_a_list_marker_closes_behind_one(self):
        # finding 41 (2): '- ```' opened a fence that only '```' could close, so everything after it was masked
        self.assertEqual(pv.fence_mask(["- ```bash", "- make build", "- ```", "## B"]), [True, True, True, False])
        self.assertEqual(pv.fence_mask(["```", "- ```", "SECRET", "```", "after"]),
                         [True, True, True, True, False])  # a top-level fence still needs its own closer

    def test_contract_headings_and_context_sections_agree(self):
        # finding 41 (4): the P-GROUND contract passed these documents, and context_section lost B, A2 and C
        for name, doc in self.DOCS.items():
            ctx = self.make_ctx(variant="software", run_name="2026-09-26-e3-fence-" + name.replace(" ", "-"))
            contract = registry._ground_item(ctx, None, "claude", "02_CONTEXT.md")["contract"]
            self.assertIn("## A2", contract["headings"])
            self.assertEqual(validate.check_contract(doc, contract, ctx.run_dir)[:2], (True, []), name)
            ctx.write("02_CONTEXT.md", doc)
            self.assertEqual(registry.context_section(ctx, "B"), "## B. LANDSCAPE\n- competitor tool X", name)
            self.assertEqual(registry.context_section(ctx, "C"), "- s", name)
            self.assertEqual(registry.context_section(ctx, "A2"), "- **T** [proposed]: t", name)
            self.assertNotIn("competitor", registry.context_section(ctx, "A"), name)


class RepoCodeTests(tl.EngineTestCase):
    def test_code_under_a_fact_never_reaches_another_vendor(self):
        # R-validation-privacy-0, end to end: FACTS written by a repo-reading researcher with unfenced code under a
        # FACT line
        ctx = software_ctx(self)
        ctx.write("02_CONTEXT.md", "## A. FACTS\n- F3: the session code signs tokens (src/auth/session.py:40):\n"
                                   "    SECRET_A = jwt.encode(p, KEY)\nThe charge handler (src/pay.py:10) is:\n"
                                   "    def charge(a):\n        return a * SECRET_B\n## B. LANDSCAPE\n- l\n"
                                   "## C. SEARCH BOUNDARY\n- s\n")
        gpt = registry.PLACEHOLDERS["FACTS"](ctx, {"family": "gpt"})
        self.assertNotIn("SECRET_A", gpt)
        self.assertNotIn("SECRET_B", gpt)
        self.assertIn("src/auth/session.py:40", gpt)
        self.assertIn("SECRET_A", registry.PLACEHOLDERS["FACTS"](ctx, {"family": "claude"}))
        # the worker's byte check refuses the unfiltered text
        job = {"id": "x", "family": "gpt", "tools": "none", "cwd": "empty",
               "privacy": {"vendor_ok": True, "web_ok": True, "code_ok": True, "code_filtered": True},
               "prompt_file": "prompts/x.prompt.md", "run": ctx.run_dir}
        ctx.write("prompts/x.prompt.md", "Facts:\n" + ctx.read("02_CONTEXT.md"))
        self.assertIn("contains code", adapter.policy_check(job, {}, ctx.state, "claude") or "")

    def test_schema_and_drivers_are_one_line(self):
        ctx = software_ctx(self)
        jc = {"family": "gpt", "template": "ARCH-CANDIDATE", "contract": registry.tcontract("ARCH-CANDIDATE")}
        schema = registry.PLACEHOLDERS["SCHEMA_TEXT"](ctx, jc)
        self.assertNotIn("\n", schema)
        self.assertFalse(pv.contains_code(schema))
        self.assertNotIn("\n", registry.PLACEHOLDERS["DRIVERS_JSON"](ctx, jc))


A2_WITH_SUBLINES = """## A. FACTS
- src/swap.py holds the swap rules (src/swap.py:42)

## A2. DOMAIN TERMS (today's system)

- **Shift**: a work period (CONTEXT.md)
    - also called: rota slot
- **Swap** [proposed]: an exchange of two shifts.
"""


class FallbackPromptTests(tl.EngineTestCase):
    def test_the_fallback_copy_is_stable_under_strip_code(self):
        # R-validation-privacy-1: dropping the '**Shift**' term left its 4-space sub-line under a blank line, an
        # indented code block: the fallback prompt was refused by the worker (contains code)
        ctx = software_ctx(self)
        self.assertFalse(pv.contains_code(pv.filter_facts(A2_WITH_SUBLINES, ctx.state, "gpt")))
        self.assertNotIn("rota slot", pv.filter_facts(A2_WITH_SUBLINES, ctx.state, "gpt"))
        ctx.write("01_FRAME.md", "# FRAME: x\n## Job statement\nWhen x.\n## Problem\nHow might we y?\n")
        ctx.write("02_CONTEXT.md", A2_WITH_SUBLINES + "\n## B. LANDSCAPE\n- l\n## C. SEARCH BOUNDARY\n- s\n")
        item = registry._gen_item(ctx, "S5", "S5-OPS", "claude", "pool/S5_operators.md", "S5",
                                  vars_={"SOFTWARE_OP": "yes"})
        step = {"id": "4.2"}
        job = builders.make_job(ctx, step, item)
        self.assertIn("rota slot", ctx.read(job["prompt_file"]))  # the host vendor sees the whole A2
        fb = builders.fallback_job(ctx, step, job, "gpt")
        text = ctx.read(fb["prompt_file"])
        self.assertFalse(pv.contains_code(text))
        self.assertNotIn("rota slot", text)
        self.assertNotIn("**Shift**", text)
        self.assertIn("**Swap** [proposed]", text)
        self.assertIsNone(adapter.policy_check(fb, {}, ctx.state, "claude"))

    def test_a_dropped_terms_sub_lines_go_with_it(self):
        a2 = "## A2. X\nintro\n- **A**: a\n  - also called: aa\n\n- **B** [proposed]: b\n  - source: s.md\n\ntail\n"
        self.assertEqual(pv.filter_a2_terms(a2), "## A2. X\nintro\n\n- **B** [proposed]: b\n  - source: s.md\n\n"
                                                 "tail\n")


class SameVendorFallbackTests(tl.EngineTestCase):
    def test_a_repository_job_falling_back_to_its_alt_keeps_the_repository(self):
        # R-validation-privacy-2: the claude-alt copy of a cwd-repo CHECK ran in an empty folder while its prompt said
        # "your working folder is its root" and its contract required section 5 (Codebase fit)
        ctx = software_ctx(self)
        ctx.write_json("origins.json", {"I-001": "human"})
        step = {"id": "7.1"}
        job = builders.make_job(ctx, step, registry._check_item(ctx, "I-001"))
        self.assertEqual((job["family"], job["cwd"]), ("claude", "repo"))
        fb = builders.fallback_job(ctx, step, job, "claude-alt")
        self.assertEqual((fb["cwd"], fb["repo_root"]), (job["cwd"], job["repo_root"]))
        self.assertIn("read", fb["tools"])
        self.assertIn("## 5. Codebase fit", fb["contract"]["headings"])
        self.assertIn("You may read the repository; your working folder is its root", ctx.read(fb["prompt_file"]))
        self.assertTrue(fb["provisional"])

    def test_the_grounding_fallback_keeps_the_repository_too(self):
        ctx = software_ctx(self)
        item = registry._ground_item(ctx, None, "claude", "02_CONTEXT.md")
        step = {"id": "3.1"}
        job = builders.make_job(ctx, step, item)
        self.assertEqual(job["cwd"], "repo")
        fb = builders.fallback_job(ctx, step, job, "claude-alt")
        self.assertEqual((fb["cwd"], fb["repo_root"]), ("repo", job["repo_root"]))

    def test_a_family_that_may_not_read_the_repository_gets_a_rebuilt_job(self):
        # a cwd-repo job whose fallback family may not read the repository (another vendor, privacy code = yes):
        # rebuilt without the repository, section 5 and the REPO_SCOPE line
        ctx = software_ctx(self, privacy={"code": True})
        ctx.write_json("origins.json", {"I-001": "human"})
        ctx.write_json("screen/shortlist.json", {"shortlist": [{"id": "I-001", "reason": "best of cluster"}]})
        step = next(s for s in pipeline.load_steps() if s["id"] == "7.1")
        job = builders.build_jobs(ctx, step)[0]
        self.assertEqual((job["family"], job["cwd"]), ("claude", "repo"))
        fb = builders.fallback_job(ctx, step, job, "gpt")
        self.assertEqual((fb["cwd"], fb["repo_root"]), ("empty", None))
        self.assertNotIn("read", fb["tools"])
        self.assertNotIn("## 5. Codebase fit", fb["contract"].get("headings") or [])
        self.assertNotIn("You may read the repository", ctx.read(fb["prompt_file"]))


if __name__ == "__main__":
    unittest.main()
