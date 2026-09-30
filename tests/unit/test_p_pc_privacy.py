"""Phase P, PC-privacy (KIT_SPEC 6.8).

PROPOSAL.md Appendix E copies the A2 terms of 02_CONTEXT.md, and SECTIONS_ALL sends PROPOSAL.md to the proposal
rubric, red-team, one-pager and fix prompts. For another vendor the A2 part of Appendix E goes through the FACTS A2
filter: a CONTEXT.md term (one-line or heading-led) is left out, [proposed] terms and the FRAME's Domain language stay,
and the user's PROPOSAL.md keeps the whole glossary. A fallback copy of a host prompt is filtered the same way, and a
PROPOSAL.md an older kit assembled (no A2 line in Appendix E) has its whole appendix filtered.
"""

import os
import sys
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fixtures", "engine"))
import engine_testlib as tl  # noqa: E402

import stubs  # noqa: E402  (tests/harness, put on sys.path by engine_testlib)
from ublib import textio  # noqa: E402
from ublib.engine import builders, vendor_of  # noqa: E402
from ublib.engine import privacy as pv  # noqa: E402

INTRO = "These words describe the system as it is today, so ideas can be stated unambiguously.\n\n"
# the P-GROUND one-line form and a heading-led term with its source line and body below it (the NC entries' layout)
A2 = (INTRO + "- **Rota block** [CONTEXT.md]: a fixed template billed to cost centre SECRETLINE\n"
      "- **Swap offer** [proposed]: KEEPPROP a request to trade one shift\n\n"
      "### Float pool\nSource: CONTEXT.md\n\nNurses paid from budget line SECRETHEAD\n")
DOMAIN = "- **Hand-off note** (NEW): KEEPFRAME a note the outgoing nurse leaves"
SECRETS = ("SECRETLINE", "SECRETHEAD")


class GlossaryRunTests(tl.EngineTestCase):
    def test_no_other_vendor_prompt_holds_a_context_md_term(self):
        os.makedirs(os.path.join(self.project, ".git"))
        textio.write_text_atomic(os.path.join(self.project, "app.py"), "print('x')\n")
        real_body, real_rules = stubs._section_body, stubs._ensure_rules

        def body(ctx, heading, n):
            if ctx.template == "P-GROUND" and "a2" in heading.lower():
                return A2
            return real_body(ctx, heading, n)

        def rules(content, r):  # the FRAME's Domain language section
            return real_rules(content, r).replace("## Domain language\n\nAdded to satisfy the required outline.",
                                                  "## Domain language\n\n" + DOMAIN)

        with mock.patch.object(stubs, "_section_body", body), mock.patch.object(stubs, "_ensure_rules", rules):
            ctx = tl.full_auto_ctx(self, mode="standard", variant="software")
            self.assertEqual(tl.drive(ctx)["type"], "DONE")
        host = vendor_of(ctx.host_family)
        leaks, seen = [], []
        for p in sorted(textio.glob_in(ctx.run_dir, "jobs", "*.json")):
            job = textio.read_json(p)
            if p.endswith(".meta.json") or not isinstance(job, dict) or not job.get("prompt_file"):
                continue
            if vendor_of(job.get("family")) == host:
                continue
            text = ctx.read(job["prompt_file"])
            leaks += ["%s: %s" % (job["id"], w) for w in SECRETS if w in text]
            if "Appendix E" in text:
                seen.append(job["id"])
                self.assertIn("KEEPPROP", text, job["id"])
                self.assertIn("KEEPFRAME", text, job["id"])
        self.assertEqual(leaks, [])
        for jid in ("13.5-rubric_gpt", "13.5-rubric_kimi", "13.5-redteam"):  # the prompts the entries name
            self.assertIn(jid, seen)
        prop = ctx.read("11_PROPOSAL/PROPOSAL.md")
        for word in SECRETS + ("KEEPPROP", "KEEPFRAME", pv.GLOSSARY_A2):
            self.assertIn(word, prop)  # the user's copy keeps the whole glossary

        # a fallback copy of a host prompt that quotes PROPOSAL.md (privacy.refilter_prompt)
        jc = {"family": ctx.host_family, "template": "PROPOSAL-RUBRIC", "vars": {}, "item": {}, "tools": "none"}
        hostp = builders.fill(ctx, builders.template_text("PROPOSAL-RUBRIC"), jc)
        self.assertTrue(all(w in hostp for w in SECRETS))
        copy = pv.refilter_prompt(hostp, ctx.state, "gpt", ctx.run_dir)
        self.assertEqual([w for w in SECRETS if w in copy], [])
        self.assertIn("KEEPPROP", copy)
        self.assertIn("KEEPFRAME", copy)
        self.assertEqual(pv.refilter_prompt(hostp, ctx.state, ctx.host_family, ctx.run_dir), hostp)


PROPOSAL = ("# Proposal: x\n\n## 13. Open Questions\n- q\n\n## Appendix D. Idea Selection Record\n- d\n\n"
            "## Appendix E. Glossary\n%s\n\n## Appendix F. Sources\n| id | url |\n|---|---|\n| S1 | u |\n")


class FilterGlossaryTests(unittest.TestCase):
    def test_only_the_a2_part_is_filtered(self):
        text = PROPOSAL % (DOMAIN + "\n\n" + pv.GLOSSARY_A2 + "\n" + A2.rstrip("\n"))
        out = pv.filter_glossary(text)
        self.assertEqual([w for w in SECRETS if w in out], [])
        for keep in ("KEEPPROP", "KEEPFRAME", INTRO.strip(), "| S1 | u |", "- d", "## Appendix F. Sources"):
            self.assertIn(keep, out)

    def test_an_older_proposal_has_its_whole_appendix_filtered(self):
        out = pv.filter_glossary(PROPOSAL % (DOMAIN + "\n\n" + A2.rstrip("\n")))
        self.assertEqual([w for w in SECRETS + ("KEEPFRAME",) if w in out], [])  # fails closed
        self.assertIn("KEEPPROP", out)
        self.assertIn("| S1 | u |", out)

    def test_a_quoted_heading_or_an_open_fence_cannot_hide_the_appendix(self):
        glossary = pv.GLOSSARY_A2 + "\n" + A2.rstrip("\n")
        for lead in ("## Appendix E. Glossary\n(see below)\n\n", "```text\nan open fence\n\n",
                     "```\n## Appendix E. Glossary\n```\n\n"):
            text = (PROPOSAL % glossary).replace("## Appendix D.", lead + "## Appendix D.")
            out = pv.filter_glossary(text)
            self.assertEqual([w for w in SECRETS if w in out], [], lead)
            self.assertIn("KEEPPROP", out, lead)
        # a fenced '## ' line inside the A2 terms does not end the appendix
        fenced = pv.GLOSSARY_A2 + "\n" + INTRO + "```\n## Appendix E. x\n## B\n```\n- **Rota** [CONTEXT.md]: SECRETLINE"
        self.assertNotIn("SECRETLINE", pv.filter_glossary(PROPOSAL % fenced))

    def test_a_fallback_copy_for_another_vendor_is_filtered(self):
        state = {"privacy": {"code": False}, "host": {"family": "claude"}}
        prompt = "THE PROPOSAL\n%s\n" % pv.fence_data("SECTIONS_ALL", PROPOSAL % (pv.GLOSSARY_A2 + "\n" + A2))
        copy = pv.refilter_prompt(prompt, state, "gpt")
        self.assertEqual([w for w in SECRETS if w in copy], [])
        self.assertIn("KEEPPROP", copy)
        self.assertEqual(pv.refilter_prompt(prompt, state, "claude-alt"), prompt)

    def test_text_without_the_appendix_is_unchanged_and_the_scan_is_linear(self):
        self.assertEqual(pv.filter_glossary("## 1. Summary\r\n- **Rota** [CONTEXT.md]: x\r\n"),
                         "## 1. Summary\r\n- **Rota** [CONTEXT.md]: x\r\n")
        flood = "## Appendix E. Glossary\n" * 20000 + "\n".join([pv.GLOSSARY_A2] * 20000)
        t0 = time.perf_counter()
        pv.filter_glossary(flood + "\n## Appendix F. Sources\n")
        self.assertLess(time.perf_counter() - t0, 2.0)


if __name__ == "__main__":
    unittest.main()
