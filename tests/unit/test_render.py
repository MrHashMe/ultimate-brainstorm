"""B3 engine: the Markdown subset converter and the single-file HTML pack (KIT_SPEC 8.5): index.html of a fixture
proposal has the table of contents, <pre class="mermaid"> blocks, the status badge and the section and appendix
anchors; PROPOSAL.md assembly (13.4); the zip contents; export without pandoc."""

import os
import re
import shutil
import sys
import unittest
import zipfile
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fixtures", "engine"))
import engine_testlib as tl  # noqa: E402

from ublib import textio  # noqa: E402
from ublib.engine import render, render_arch, registry  # noqa: E402

SECTIONS = [h for _, h in registry.PROPOSAL_SECTIONS]


def write_fixture(ctx):
    for num, heading in registry.PROPOSAL_SECTIONS:
        body = "Body of %s with **bold**, `code` and a [link](https://example.org)." % heading
        if num == "06":
            body += "\n\n```mermaid\nflowchart LR\n  A[\"web\"] --> B[\"api\"]\n```"
        if num == "08":
            body += "\n\n- Milestone 0: run the probe; kill criterion: fewer than 3 of 10 swap."
        if num == "13":
            body += "\n\n- Which ward first? Owner: lead. Decide by: Milestone 0."
        ctx.write("11_PROPOSAL/sections/%s.md" % num, "%s\n\n%s\n" % (heading, body))
    ctx.write("11_PROPOSAL/ONE-PAGER.md", "# One-pager\n\n## Problem\nx\n\n## Architecture at a glance\n\n```mermaid\n"
                                          "flowchart LR\n  U[\"nurse\"] --> S[\"app\"]\n```\n")
    ctx.write("10_ARCHITECTURE/context.md", "# Context\n\n```mermaid\nC4Context\n  System(SYS, \"x\", \"y\")\n```\n")
    ctx.write("10_ARCHITECTURE/chosen/containers.md", "## Containers\n\n```mermaid\nflowchart LR\n  C1[\"C-1 web\"]\n"
                                                      "```\n")
    ctx.write("10_ARCHITECTURE/adr/0001-use-sqlite.md", "---\nstatus: proposed\ndate: 2026-09-23\n---\n# ADR-0001: Use "
                                                        "SQLite\n## Context and Problem Statement\nx\n")
    ctx.write("10_ARCHITECTURE/risks.md", "# Risks\n\n## Risks\n\n| id | risk |\n|---|---|\n| R-001 | outage |\n\n"
                                          "## Technical debt\n\nnone\n")
    ctx.write("10_ARCHITECTURE/README.md", "# Architecture\n")
    ctx.write("sources.md", "# Sources\n\n| id | url |\n|---|---|\n| S-001 | https://example.org |\n")
    ctx.write("screen/ideas.md", "I-001 | Shared swap board | Nurses swap shifts on a board. | A board.\n")
    ctx.state["choice"]["idea"] = "I-001"


class MarkdownTests(unittest.TestCase):
    def test_subset(self):
        md = ("# Title\n\nPara with *em* and **strong** and `x<y` and [l](https://a.b/c).\n\n- one\n- two\n\n1. a\n2. b\n\n"
              "| h1 | h2 |\n|---|---|\n| a | b |\n\n> quote\n\n```mermaid\nflowchart LR\n  A --> B\n```\n\n```python\n"
              "print(1 < 2)\n```\n")
        toc = []
        out = render.md_to_html(md, set(), toc)
        self.assertIn("<h1 id=\"title\">Title</h1>", out)
        self.assertIn("<em>em</em>", out)
        self.assertIn("<strong>strong</strong>", out)
        self.assertIn("<code>x&lt;y</code>", out)
        self.assertIn('<a href="https://a.b/c">l</a>', out)
        self.assertIn("<ul><li>one</li><li>two</li></ul>", out)
        self.assertIn("<ol><li>a</li><li>b</li></ol>", out)
        self.assertIn("<table><thead><tr><th>h1</th><th>h2</th></tr></thead><tbody><tr><td>a</td><td>b</td></tr>", out)
        self.assertIn("<blockquote>quote</blockquote>", out)
        self.assertIn('<pre class="mermaid">flowchart LR\n  A --&gt; B</pre>', out)
        self.assertIn('<pre><code class="language-python">print(1 &lt; 2)</code></pre>', out)

    def test_unsafe_links_are_neutralized(self):
        out = render.md_to_html("[x](javascript:alert(1))", set())
        self.assertNotIn("javascript:", out)
        self.assertNotIn("<script", render.md_to_html("<script>alert(1)</script>", set()))


class PackTests(tl.EngineTestCase):
    def setUp(self):
        tl.EngineTestCase.setUp(self)
        self.ctx = self.make_ctx(deps=tl.FakeDeps())
        write_fixture(self.ctx)

    def test_assemble_proposal(self):
        text = render.assemble(self.ctx)
        self.assertTrue(text.startswith("# Proposal: Shared swap board"))
        pos = [text.index(h) for h in SECTIONS] + [text.index(h) for h in render.APPENDICES]
        self.assertEqual(pos, sorted(pos))
        self.assertIn("Status: DRAFT", text)
        self.assertIn("ADR-0001", text)
        self.assertIn("../10_ARCHITECTURE/adr/0001-use-sqlite.md", text)
        self.assertIn("S-001", text)
        self.ctx.state["autopilot"] = "full-auto"
        self.assertIn("AUTOPILOT DRAFT: no human decisions were made", render.assemble(self.ctx))

    def test_approach_section_heading(self):
        self.ctx.state["build_type"] = "approach"
        text = render.assemble(self.ctx)
        self.assertIn("## 6. Approach", text)
        self.assertFalse(re.search(r"^## 6\. Architecture Summary", text, re.M))

    def test_missing_section_8_gets_milestone_0(self):
        os.remove(self.ctx.path("11_PROPOSAL", "sections", "08.md"))
        self.ctx.write("09_PROBE.md", "## 3. Probe design\nask 10 nurses\n## 4. Kill criterion\nfewer than 3 swap\n"
                                      "RESULT: PENDING\n")
        text = render.section_text(self.ctx, "08", "## 8. Roadmap and Milestones")
        self.assertIn("Milestone 0", text)
        self.assertIn("kill criterion: fewer than 3 swap", text)

    def test_index_html(self):
        self.ctx.write("11_PROPOSAL/PROPOSAL.md", render.assemble(self.ctx))
        out = render.render_pack(self.ctx, make_zip=True)
        html = textio.read_text(out["index"])
        self.assertTrue(html.lstrip().lower().startswith("<!doctype html>"))
        self.assertIn('id="toc"', html)
        self.assertIn('<pre class="mermaid">', html)
        self.assertGreaterEqual(html.count('<pre class="mermaid">'), 3)
        self.assertIn(">DRAFT<", html)
        self.assertIn("status-badge", html)
        for n in range(1, 14):
            self.assertIn('id="sec-%d"' % n, html)
            self.assertIn('href="#sec-%d"' % n, html)
        for letter in "abcdef":
            self.assertIn('id="appendix-%s"' % letter, html)
            self.assertIn('href="#appendix-%s"' % letter, html)
        self.assertIn(render.MERMAID_CDN, html)
        self.assertIn("prefers-color-scheme", html)
        self.assertIn("@media print", html)
        self.assertIn("adr-cards", html)
        self.assertNotIn("{{", html)
        # ids are unique
        ids = re.findall(r'\bid="([^"]+)"', html)
        self.assertEqual(len(ids), len(set(ids)))
        with zipfile.ZipFile(out["zip"]) as z:
            names = set(z.namelist())
        for name in ("11_PROPOSAL/index.html", "11_PROPOSAL/PROPOSAL.md", "11_PROPOSAL/ONE-PAGER.md",
                     "10_ARCHITECTURE/README.md", "10_ARCHITECTURE/adr/0001-use-sqlite.md"):
            self.assertIn(name, names)

    def test_export(self):
        self.ctx.write("11_PROPOSAL/PROPOSAL.md", render.assemble(self.ctx))
        res = render.export(self.ctx, "html")
        self.assertTrue(res["ok"])
        self.assertTrue(os.path.exists(res["path"]))
        with mock.patch.object(shutil, "which", return_value=None):
            res = render.export(self.ctx, "docx")
        self.assertFalse(res["ok"])
        self.assertIn("pandoc", res["error"])


class ArchDocTests(tl.EngineTestCase):
    DRIVERS = {"product_goal": "swap shifts", "quality_goals": [
        {"id": "Q1", "name": "fast", "weight": 30, "why": "w", "source": "STATED"},
        {"id": "QG2", "name": "safe", "weight": 30, "why": "w", "source": "ASSUMPTION"},
        {"id": "QG3", "name": "cheap", "weight": 20, "why": "w", "source": "STATED"}],
        "hard_constraints": [{"id": "H1", "text": "no new hardware", "source": "FRAME"}],
        "soft_constraints": ["phone first"], "not_in_scope": ["payroll"],
        "qas": [{"id": "QAS-01", "qg": "Q1", "source": "nurse", "stimulus": "swap", "artifact": "app",
                 "environment": "night", "response": "ok", "measure": "2 s", "importance": "H", "difficulty": "M"}],
        "context": {"system": {"name": "Swap (board)", "description": "d"},
                    "actors": [{"id": "A1", "name": "Nurse", "description": "n"}],
                    "external": [{"id": "E1", "name": "Rota [system]", "description": "r", "relationship": "reads"}]},
        "planning_assumptions": [], "open_questions": [{"q": "which ward?", "default": "ward 3"}]}

    def test_normalize_drivers(self):
        d, warnings = render_arch.normalize_drivers(self.DRIVERS)
        self.assertEqual([q["id"] for q in d["quality_goals"]], ["QG1", "QG2", "QG3"])
        self.assertEqual(sum(q["weight"] for q in d["quality_goals"]), 70)
        self.assertEqual(d["qas"][0]["qg"], "QG1")  # renumbered references follow
        self.assertEqual(d["hard_constraints"][0]["id"], "HC-1")
        self.assertEqual(d["context"]["external"][0]["id"], "EXT-1")
        self.assertTrue(any("normalized to 70" in w for w in warnings))

    def test_rendered_docs(self):
        d, _ = render_arch.normalize_drivers(self.DRIVERS)
        goals = render_arch.render_goals(d)
        for h in ("# Goals and constraints", "## Product goal", "## Quality goals", "## Hard constraints",
                  "## Soft constraints", "## Not in scope", "## Planning assumptions", "## Open questions"):
            self.assertIn(h, goals)
        ctxmd = render_arch.render_context(d)
        blocks = [b for lang, b in textio.fenced_blocks(ctxmd) if lang == "mermaid"]
        self.assertTrue(blocks[0].startswith("C4Context"))
        self.assertTrue(blocks[1].startswith("flowchart"))
        for b in blocks:
            for ln in b.split("\n"):
                for o, c in ("()", "[]", "{}"):
                    self.assertEqual(ln.count(o), ln.count(c), ln)
                self.assertEqual(ln.count('"') % 2, 0, ln)
        self.assertIn("EXT-1", ctxmd)
        scen = render_arch.render_scenarios(d)
        self.assertIn("## Utility tree", scen)
        self.assertIn("QAS-01", scen)

    def test_adr_and_risks(self):
        dec = {"adrs": [{"title": "Use SQLite", "context": "c", "drivers": ["QG1"], "options": [
            {"name": "SQLite", "pros": ["small"], "cons": []}, {"name": "Postgres", "pros": [], "cons": ["ops"]}],
            "chosen": "SQLite", "justification": "it is enough.", "good": ["simple"],
            "bad": [{"text": "one writer", "risk_ids": ["R-001", "R-999"]}], "confirmation": "load test",
            "more_info": ""}], "risks": [{"id": "R-001", "text": "outage"}, {"id": "bad", "text": "x"}],
            "debt": [{"id": "TD-01", "text": "no cache", "why": "time", "payoff_trigger": "100 users"}]}
        adr = render_arch.render_adr(1, dec["adrs"][0], "2026-09-23", "proposed", {"R-001"}, {"QG1": "fast"})
        self.assertTrue(adr.startswith("---\nstatus: proposed\ndate: 2026-09-23\n"))
        for h in ("# ADR-0001: Use SQLite", "## Context and Problem Statement", "## Decision Drivers",
                  "## Considered Options", "## Decision Outcome", "### Consequences", "### Confirmation",
                  "## More Information"):
            self.assertIn(h, adr)
        self.assertIn('Chosen option: "SQLite", because it is enough.', adr)
        self.assertIn("* Bad, because one writer (R-001)", adr)
        self.assertNotIn("R-999", adr)
        risks = render_arch.render_risks(dec)
        self.assertIn("## Risks", risks)
        self.assertIn("## Technical debt", risks)
        self.assertIn("R-002", risks)  # an invalid id is renumbered
        stack = render_arch.render_stack([{"layer": "db", "component": "store", "choice": "sqlite", "version": "",
                                           "status": "VERIFIED"}])
        self.assertIn("UNVERIFIED", stack)  # a missing version is never shown as empty or 'latest'

    def test_judge_sheet_is_neutral(self):
        sheet = render_arch.render_sheet("B", {"paradigm": "Claude-built GPT-style monolith",
                                               "summary": " ".join(["word"] * 100),
                                               "containers": [{"id": "C-1", "name": "api", "tech": "python"}]})
        self.assertTrue(sheet.startswith("# Candidate B"))
        self.assertNotIn("Claude", sheet)
        self.assertNotIn("GPT", sheet)
        self.assertIn("C-1", sheet)
        self.assertLessEqual(len(re.findall(r"\bword\b", sheet)), 60)


if __name__ == "__main__":
    unittest.main()
