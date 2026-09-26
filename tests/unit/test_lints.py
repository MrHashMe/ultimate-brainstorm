"""ublib.lints and the bs.py lint-* commands (KIT_SPEC 5.8).

tests/fixtures/lint/good is a run folder that passes every rule. Each bad case copies it and applies one mutation.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

_KIT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_SCRIPTS = os.path.join(_KIT, "skills", "ultimate-brainstorm", "scripts")
GOOD = os.path.join(_KIT, "tests", "fixtures", "lint", "good")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

from ublib import lints  # noqa: E402

LITE_ONLY_MISSING = ("tradeoff-matrix.md", "chosen/runtime.md", "chosen/deployment.md", "chosen/security-privacy.md",
                     "chosen/cost-model.md", "chosen/deferred.md")


class LintCase(unittest.TestCase):
    def setUp(self):
        # some tests call setUp() again for a fresh copy; every copy is removed in tearDown
        self.tmp = tempfile.mkdtemp(prefix="ub-lint-")
        self.__dict__.setdefault("_tmps", []).append(self.tmp)
        self.run = os.path.join(self.tmp, "2026-09-23-lint")
        shutil.copytree(GOOD, self.run)

    def tearDown(self):
        for tmp in self.__dict__.get("_tmps", []):
            shutil.rmtree(tmp, ignore_errors=True)

    def p(self, rel):
        return os.path.join(self.run, *rel.split("/"))

    def read(self, rel):
        with open(self.p(rel), encoding="utf-8") as f:
            return f.read()

    def write(self, rel, text):
        os.makedirs(os.path.dirname(self.p(rel)), exist_ok=True)
        with open(self.p(rel), "w", encoding="utf-8", newline="\n") as f:
            f.write(text)

    def sub(self, rel, old, new, count=1):
        text = self.read(rel)
        self.assertIn(old, text, "fixture drifted: %r not in %s" % (old, rel))
        self.write(rel, text.replace(old, new, count))

    def rm(self, rel):
        path = self.p(rel)
        if os.path.isdir(path):
            shutil.rmtree(path)
        else:
            os.remove(path)

    def ids(self, res, severity=None):
        return sorted({i["id"] for i in res["items"] if severity is None or i["severity"] == severity})

    def assertOnly(self, res, rule, severity="fail"):
        self.assertEqual(self.ids(res), [rule], res["items"])
        self.assertTrue(all(i["severity"] == severity for i in res["items"]), res["items"])
        self.assertEqual(res["status"], severity)


class ArchLintTests(LintCase):
    def arch(self, lite=False):
        return lints.lint_arch(self.run, lite=lite)

    def test_good_passes_and_writes_reports(self):
        res = self.arch()
        self.assertEqual(res["status"], "pass", res["items"])
        self.assertEqual(res["rules"], ["A1", "A2", "A3", "A4", "A5", "A6", "A7", "A8", "A9"])
        with open(self.p("10_ARCHITECTURE/lint.json"), encoding="utf-8") as f:
            self.assertEqual(json.load(f)["status"], "pass")
        self.assertIn("Status: PASS", self.read("10_ARCHITECTURE/lint.md"))

    def test_a1_required_files(self):
        self.rm("10_ARCHITECTURE/chosen/runtime.md")
        self.assertOnly(self.arch(), "A1")

    def test_a1_needs_an_adr(self):
        for name in os.listdir(self.p("10_ARCHITECTURE/adr")):
            self.rm("10_ARCHITECTURE/adr/" + name)
        self.sub("10_ARCHITECTURE/README.md", "| [ADR-0001](adr/0001-use-postgres.md) | Use a managed Postgres database "
                 "| proposed |\n| [ADR-0002](adr/0002-job-queue.md) | Use a managed job queue for SMS alerts | "
                 "proposed |\n", "")
        res = self.arch()
        self.assertEqual(self.ids(res), ["A1"])
        self.assertIn("adr/", [i["file"] for i in res["items"]])

    def test_lite_mode(self):
        for rel in LITE_ONLY_MISSING:
            self.rm("10_ARCHITECTURE/" + rel)
        self.assertEqual(self.arch(lite=True)["status"], "pass", self.arch(lite=True)["items"])
        full = self.arch()
        self.assertEqual(self.ids(full), ["A1"])
        self.assertEqual(len(full["items"]), len(LITE_ONLY_MISSING))
        self.rm("10_ARCHITECTURE/chosen/stack.md")  # lite file
        self.assertEqual(self.ids(self.arch(lite=True)), ["A1"])

    def test_a2_placeholders(self):
        self.sub("10_ARCHITECTURE/chosen/deployment.md", "## Observability", "## Observability\n\nTODO pick a vendor.")
        self.assertOnly(self.arch(), "A2")

    def test_a2_angle_and_braces(self):
        self.sub("10_ARCHITECTURE/risks.md", "| tech lead |", "| <owner name> |")
        res = self.arch()
        self.assertOnly(res, "A2")
        self.setUp()
        self.sub("10_ARCHITECTURE/README.md", "## Provenance", "## Provenance\n\n{{AUTHORS}}")
        self.assertOnly(self.arch(), "A2")

    def test_a2_allows_fences_inline_code_and_br(self):
        self.sub("10_ARCHITECTURE/README.md", "## Provenance",
                 "## Provenance\n\nLine one<br>line two. Use `<id>` and `TODO` in code.\n\n```\nTODO in a fence "
                 "<placeholder>\n```\n")
        self.assertEqual(self.arch()["status"], "pass", self.arch()["items"])

    def test_a2_ignores_raw_candidates(self):
        self.assertIn("TODO", self.read("10_ARCHITECTURE/candidates/A.md"))
        self.assertEqual(self.arch()["status"], "pass")

    def test_a3_frontmatter(self):
        self.sub("10_ARCHITECTURE/adr/0001-use-postgres.md", "date: 2026-09-23\n", "")
        self.assertOnly(self.arch(), "A3")

    def test_a3_headings(self):
        self.sub("10_ARCHITECTURE/adr/0002-job-queue.md", "### Confirmation", "### Checks")
        self.assertOnly(self.arch(), "A3")

    def test_a3_options_and_risk_refs(self):
        self.sub("10_ARCHITECTURE/adr/0002-job-queue.md", "* Send the SMS inside the request\n", "")
        res = self.arch()
        self.assertOnly(res, "A3")
        self.assertIn("at least 2 needed", res["items"][0]["message"])
        self.setUp()
        self.sub("10_ARCHITECTURE/adr/0002-job-queue.md", "(R-002)", "(R-009)")
        res = self.arch()
        self.assertOnly(res, "A3")
        self.assertIn("R-009", res["items"][0]["message"])

    def test_a4_versions(self):
        self.sub("10_ARCHITECTURE/chosen/stack.md", "| 17.6 |", "| latest |")
        self.assertOnly(self.arch(), "A4")
        self.setUp()
        self.sub("10_ARCHITECTURE/chosen/stack.md", "| 3.13.7 |", "|  |")
        self.assertOnly(self.arch(), "A4")

    def test_a4_unverified_warns(self):
        self.sub("10_ARCHITECTURE/chosen/stack.md", "| 17.6 |", "| 17.x TO-VERIFY |")
        self.sub("10_ARCHITECTURE/chosen/stack.md", "| VERIFIED | PSF", "| UNVERIFIED | PSF")
        res = self.arch()
        self.assertOnly(res, "A4", "warn")
        self.assertIn("2 stack row(s)", res["items"][0]["message"])

    def test_a4_no_version_column(self):
        self.write("10_ARCHITECTURE/chosen/stack.md", "# Stack\n\n| layer | choice |\n|---|---|\n| data | pg |\n")
        self.assertOnly(self.arch(), "A4")

    def test_a5_mermaid_type_and_brackets(self):
        self.sub("10_ARCHITECTURE/chosen/data-model.md", "erDiagram", "entityDiagram")
        self.assertOnly(self.arch(), "A5")
        self.setUp()
        self.sub("10_ARCHITECTURE/context.md", "nurse[Nurse] --> app[Swap app]", "nurse[Nurse --> app[Swap app]")
        self.assertOnly(self.arch(), "A5")
        self.setUp()
        self.sub("10_ARCHITECTURE/context.md", 'Person(nurse, "Nurse", "Works night shifts")',
                 'Person(nurse, "Nurse, "Works night shifts")')
        self.assertOnly(self.arch(), "A5")

    def test_a5_tabs_and_c4_fallback(self):
        self.sub("10_ARCHITECTURE/chosen/runtime.md", "  N->>W: post swap", "\tN->>W: post swap")
        self.assertOnly(self.arch(), "A5")
        self.setUp()
        text = self.read("10_ARCHITECTURE/context.md")
        start = text.index("```mermaid\nflowchart")
        end = text.index("```", start + 10) + 3
        self.write("10_ARCHITECTURE/context.md", text[:start] + text[end:])
        res = self.arch()
        self.assertOnly(res, "A5")
        self.assertIn("no flowchart/graph fallback", res["items"][0]["message"])

    def test_a5_er_block_braces(self):
        self.sub("10_ARCHITECTURE/chosen/data-model.md", "    string state\n  }", "    string state\n")
        self.assertOnly(self.arch(), "A5")

    def test_a6_quality_goal_trace(self):
        self.sub("10_ARCHITECTURE/README.md", "and QG3 with", "and latency with")
        self.sub("10_ARCHITECTURE/chosen/containers.md", "| QG3 | server-rendered pages", "| speed | server-rendered pages")
        res = self.arch()
        self.assertOnly(res, "A6")
        self.assertIn("QG3", res["items"][0]["message"])

    def test_a6_ext_and_containers(self):
        self.sub("10_ARCHITECTURE/context.md", "| EXT-2 | SMS gateway |", "| EXT-2 | SMS gateway |\n| EXT-3 | Payroll | x | "
                 "none |\n")
        res = self.arch()
        self.assertOnly(res, "A6")
        self.assertIn("EXT-3", res["items"][0]["message"])
        self.setUp()
        self.sub("10_ARCHITECTURE/chosen/containers.md", "| C-3 | Database |", "| C-4 | Cache | redis | cache | none | "
                 "RESP |\n| C-3 | Database |")
        res = self.arch()
        self.assertOnly(res, "A6")
        self.assertIn("C-4", res["items"][0]["message"])

    def test_a6_failure_flow(self):
        self.sub("10_ARCHITECTURE/chosen/runtime.md", "## F-2 Failure and recovery: roster system down",
                 "## F-2 Roster system down")
        self.assertOnly(self.arch(), "A6")

    def test_a7_word_counts_and_deferred(self):
        self.write("10_ARCHITECTURE/chosen/deployment.md", "# Deployment\n\nOne region, managed services.\n")
        self.assertOnly(self.arch(), "A7")
        self.sub("10_ARCHITECTURE/chosen/deferred.md", "| Milestone 2 |",
                 "| Milestone 2 |\n| deployment.md details | pilot only | go-live | Milestone 1 |")
        self.assertEqual(self.arch()["status"], "pass", self.arch()["items"])

    def test_a7_cost_model_structure(self):
        self.sub("10_ARCHITECTURE/chosen/cost-model.md", "## Assumptions", "## Inputs")
        self.assertOnly(self.arch(), "A7")
        self.setUp()
        self.sub("10_ARCHITECTURE/chosen/cost-model.md", "## Sensitivity", "## What if")
        self.assertOnly(self.arch(), "A7")

    def test_a8_risks(self):
        self.sub("10_ARCHITECTURE/risks.md", "| R-002 |", "| R-001 | duplicate | L | L | x | y | z | w |\n| R-002 |")
        res = self.arch()
        self.assertOnly(res, "A8")
        self.setUp()
        self.sub("10_ARCHITECTURE/risks.md", "## Technical debt", "## Debt")
        self.assertOnly(self.arch(), "A8")

    def test_a9_decision_index_warns(self):
        self.sub("10_ARCHITECTURE/README.md", "| [ADR-0002](adr/0002-job-queue.md) | Use a managed job queue for SMS "
                 "alerts | proposed |\n", "")
        res = self.arch()
        self.assertOnly(res, "A9", "warn")
        self.assertIn("ADR-0002", res["items"][0]["message"])


class ProposalLintTests(LintCase):
    def prop(self, lite=False):
        return lints.lint_proposal(self.run, lite=lite)

    def test_good_passes(self):
        res = self.prop()
        self.assertEqual(res["status"], "pass", res["items"])
        self.assertEqual(len(res["rules"]), 11)
        self.assertTrue(os.path.exists(self.p("11_PROPOSAL/lint.md")))

    def test_p1_missing_and_order(self):
        self.sub("11_PROPOSAL/PROPOSAL.md", "## 9. Team and Effort", "## 9. People")
        self.assertOnly(self.prop(), "P1")
        self.setUp()
        text = self.read("11_PROPOSAL/PROPOSAL.md")
        a = text.index("## 11. Risks")
        b = text.index("## 12. Success")
        c = text.index("## 13. Open")
        self.write("11_PROPOSAL/PROPOSAL.md", text[:a] + text[b:c] + text[a:b] + text[c:])
        res = self.prop()
        self.assertOnly(res, "P1")
        self.assertIn("out of order", res["items"][0]["message"])

    def test_p1_approach_variant(self):
        self.sub("11_PROPOSAL/PROPOSAL.md", "## 6. Architecture Summary", "## 6. Approach")
        self.assertEqual(self.prop()["status"], "pass")

    def test_lite(self):
        text = self.read("11_PROPOSAL/PROPOSAL.md")
        for key in ("## 4. Users", "## 5. Differentiation", "## 8. Roadmap", "## 9. Team", "## 10. Budget",
                    "## Appendix C.", "## Appendix D.", "## Appendix E."):
            start = text.index(key)
            end = text.index("\n## ", start + 3) + 1
            text = text[:start] + text[end:]
        self.write("11_PROPOSAL/PROPOSAL.md", text)
        self.assertEqual(self.prop(lite=True)["status"], "pass", self.prop(lite=True)["items"])
        full = self.prop()
        self.assertIn("P1", self.ids(full, "fail"))
        self.assertIn("P5", self.ids(full, "fail"))   # section 8 missing in a full proposal

    def test_p2_placeholder(self):
        self.sub("11_PROPOSAL/PROPOSAL.md", "Two developers and", "TBD developers and")
        self.assertOnly(self.prop(), "P2")

    def test_p3_unsourced_numbers_warn(self):
        self.sub("11_PROPOSAL/PROPOSAL.md", "The status quo costs sleep", "Each swap costs 3 hours. The status quo "
                 "costs sleep")
        res = self.prop()
        self.assertOnly(res, "P3", "warn")
        self.assertIn("section 2: 1 sentence", res["items"][0]["message"])

    def test_p4_word_caps(self):
        self.sub("11_PROPOSAL/PROPOSAL.md", "We are not building payroll", "word " * 300 + "We are not building payroll")
        self.assertOnly(self.prop(), "P4")
        self.setUp()
        self.sub("11_PROPOSAL/ONE-PAGER.md", "## The ask", "## The ask\n\n" + "more " * 520)
        self.assertOnly(self.prop(), "P4")

    def test_p5_milestone_zero(self):
        self.sub("11_PROPOSAL/PROPOSAL.md", "- Milestone 0: run", "- First: run")
        self.sub("11_PROPOSAL/PROPOSAL.md", "Milestone 0 probe.", "first probe.")
        self.assertOnly(self.prop(), "P5")
        self.setUp()
        self.sub("11_PROPOSAL/PROPOSAL.md", "kill criterion: fewer", "stop if fewer")
        self.assertOnly(self.prop(), "P5")

    def test_p6_cited_ids(self):
        self.sub("11_PROPOSAL/PROPOSAL.md", "[S-002]", "[S-009]")
        res = self.prop()
        self.assertOnly(res, "P6")
        self.assertIn("S-009", res["items"][0]["message"])
        self.setUp()
        self.sub("11_PROPOSAL/PROPOSAL.md", "(ADR-0001, ADR-0002)", "(ADR-0001, ADR-0007)")
        self.assertOnly(self.prop(), "P6")
        self.setUp()
        self.sub("11_PROPOSAL/PROPOSAL.md", "R-002 covers", "R-042 covers")
        self.assertOnly(self.prop(), "P6")
        self.setUp()
        self.rm("sources.json")
        self.assertOnly(self.prop(), "P6")

    def test_p7_open_questions(self):
        self.sub("11_PROPOSAL/PROPOSAL.md", "Owner: hospital IT. ", "")
        self.assertOnly(self.prop(), "P7")

    def test_p7_table_form(self):
        self.sub("11_PROPOSAL/PROPOSAL.md",
                 "- Which roster export exists? Owner: tech lead. Decide by: Milestone 0.\n"
                 "- Who signs the data processing agreement? Owner: hospital IT. Decide by: Milestone 1.\n",
                 "| id | question | owner | decide by |\n|---|---|---|---|\n| Q-001 | Which export? | tech lead | "
                 "Milestone 0 |\n")
        self.assertEqual(self.prop()["status"], "pass", self.prop()["items"])
        self.sub("11_PROPOSAL/PROPOSAL.md", "| tech lead | Milestone 0 |", "| tech lead |  |")
        self.assertOnly(self.prop(), "P7")

    def test_p8_assumptions_listed(self):
        self.sub("11_PROPOSAL/PROPOSAL.md", "Our honest moat", "[ASSUMPTION: wards keep one roster each] Our honest moat")
        res = self.prop()
        self.assertOnly(res, "P8")
        self.assertIn("wards keep one roster each", res["items"][0]["message"])
        self.setUp()
        self.rm("11_PROPOSAL/assumptions.md")
        self.assertOnly(self.prop(), "P8")

    def test_p9_novel_warns(self):
        self.sub("11_PROPOSAL/ONE-PAGER.md", "Night-first approval flow.", "A novel night-first approval flow.")
        self.assertOnly(self.prop(), "P9", "warn")

    def test_p10_dollar_figures_warn(self):
        self.sub("11_PROPOSAL/PROPOSAL.md", "rising to $2,100", "rising to $2,900")
        res = self.prop()
        self.assertOnly(res, "P10", "warn")
        self.assertIn("$2,900", res["items"][0]["message"])

    def test_p11_section_1_figure_missing_from_the_one_pager(self):
        # a fix moved the ask in section 1; the one-pager kept the old cap
        self.sub("11_PROPOSAL/PROPOSAL.md", "We are not building payroll",
                 "Approve Milestone 0 at [ESTIMATE: 9,000-27,000 USD; basis: 12 builder days at $600-$1,200 a day]. "
                 "We are not building payroll")
        self.sub("11_PROPOSAL/ONE-PAGER.md", "Two developers for ten weeks.", "Two developers; a $100 cap.")
        self.sub("11_PROPOSAL/PROPOSAL.md", "for two weeks;", "for two weeks with a $100 cap;")
        res = self.prop()
        self.assertOnly(res, "P11", "warn")
        self.assertEqual(res["items"][0]["file"], "ONE-PAGER.md")
        self.assertIn("section 1 states 9,000-27,000 USD; the one-pager does not", res["items"][0]["message"])
        self.assertNotIn("$600", res["items"][0]["message"])  # the basis of an estimate is not a headline figure
        # the same figure in another notation counts
        self.sub("11_PROPOSAL/ONE-PAGER.md", "Two developers; a $100 cap.",
                 "Two developers; a $100 cap; Milestone 0 costs $9k-$27k.")
        self.assertEqual(self.prop()["status"], "pass", self.prop()["items"])

    def test_p11_one_pager_figure_or_date_no_longer_in_the_proposal(self):
        self.sub("11_PROPOSAL/ONE-PAGER.md", "About $420 a month", "About $380 a month")
        res = self.prop()
        self.assertOnly(res, "P11", "warn")
        self.assertIn("the one-pager states $380; sections 1-13 do not", res["items"][0]["message"])
        self.setUp()
        self.sub("11_PROPOSAL/ONE-PAGER.md", "Milestone 0 probe, then", "Milestone 0 probe from 2026-09-28 (verdict "
                 "2026-10-09), then a pilot in 2026-11,")
        res = self.prop()
        self.assertOnly(res, "P11", "warn")
        self.assertIn("2026-09-28, 2026-10-09, 2026-11", res["items"][0]["message"])
        self.sub("11_PROPOSAL/PROPOSAL.md", "for two weeks;", "from 2026-09-28 to 2026-10-09;")
        self.sub("11_PROPOSAL/PROPOSAL.md", "pilot on three wards.", "pilot on three wards from 2026-11-16.")
        self.assertEqual(self.prop()["status"], "pass", self.prop()["items"])  # a month matches a date in it

    def test_p11_ignores_the_status_stamp_fences_and_appendices(self):
        self.sub("11_PROPOSAL/ONE-PAGER.md", "# One-pager: shift swap board\n", "# One-pager: shift swap board\n"
                 "Status: DRAFT | 2026-09-25 | Run: 2026-09-23-lint\n")
        self.sub("11_PROPOSAL/ONE-PAGER.md", "  web[Web client]", "  web[Web client $999]")
        self.assertEqual(self.prop()["status"], "pass", self.prop()["items"])
        self.sub("11_PROPOSAL/ONE-PAGER.md", "About $420 a month", "About $420 a month, $55 for SMS")
        self.sub("11_PROPOSAL/PROPOSAL.md", "- S-002 Shift swap tools", "- S-002 Shift swap tools ($55 a month)")
        self.assertOnly(self.prop(), "P11", "warn")  # sections 1-13 count; the appendices do not

    def test_p11_lite_checks_section_1_only(self):
        self.sub("11_PROPOSAL/ONE-PAGER.md", "About $420 a month", "About $380 a month")
        self.assertNotIn("P11", self.ids(self.prop(lite=True)))  # no budget section to compare with
        self.sub("11_PROPOSAL/PROPOSAL.md", "We are not building payroll", "The ask is 5,000 EUR. We are not "
                 "building payroll")
        res = self.prop(lite=True)
        self.assertEqual(self.ids(res), ["P11"])
        self.assertIn("section 1 states 5,000 EUR", res["items"][0]["message"])

    def test_missing_proposal(self):
        self.rm("11_PROPOSAL/PROPOSAL.md")
        res = self.prop()
        self.assertEqual(res["status"], "fail")
        self.assertIn("P1", self.ids(res))


class FrameLintTests(LintCase):
    def test_good_passes(self):
        res = lints.lint_frame(self.run)
        self.assertEqual(res["status"], "pass", res["items"])
        self.assertTrue(os.path.exists(self.p("frame/lint.json")))

    def test_warnings(self):
        self.sub("01_FRAME.md", "## Premises", "## Assumptions")
        self.write("criteria.json", json.dumps({"Value": 60, "Fit": 30}))
        self.sub("01_FRAME.md", "How might we help night nurses", "Build an app that helps night nurses")
        res = lints.lint_frame(self.run)
        self.assertEqual(res["status"], "warn")
        self.assertTrue(all(i["severity"] == "warn" for i in res["items"]))
        msgs = " | ".join(i["message"] for i in res["items"])
        self.assertIn("## Premises", msgs)
        self.assertIn("sum to 90", msgs)
        self.assertIn("Feasibility", msgs)
        self.assertIn("Distinctiveness", msgs)
        self.assertIn("an app that", msgs)
        self.assertEqual(self.ids(res), ["F1", "F2", "F3", "F4"])

    def test_missing_files_warn_only(self):
        self.rm("01_FRAME.md")
        self.rm("criteria.json")
        res = lints.lint_frame(self.run)
        self.assertEqual(res["status"], "warn")


class HelperTests(unittest.TestCase):
    def test_extract_assumptions(self):
        text = ("Cost is $5 [ASSUMPTION: five dollars a month]. [ASSUMPTION] Nurses read SMS within ten minutes. "
                "Most swaps are at night [ASSUMPTION].\n| a | [ESTIMATE: 10-20; one ward] |")
        got = [(k, t) for k, t, _n in lints.extract_assumptions(text)]
        self.assertIn(("assumption", "five dollars a month"), got)
        self.assertIn(("assumption", "Nurses read SMS within ten minutes."), got)
        self.assertIn(("assumption", "Most swaps are at night"), got)
        self.assertIn(("estimate", "ESTIMATE: 10-20; one ward"), got)

    def test_money_figures_and_dates(self):
        keys = [k for k, _s in lints._money_figures(
            "A $100 cap, 100 USD, USD 100, 0-6,600 USD, $3,000 to $6,000, 1,200-4,800 USD per month, EUR 5k, "
            "costs $420, rising; 12-14 builder days, 2026-09-28, ADR-0003 and S-146.\n```\n$999\n```\n")]
        self.assertEqual(keys, ["100", "100", "100", "0-6600", "3000-6000", "1200-4800", "5000", "420"])
        self.assertEqual(lints._money_figures("costs $420, rising")[0][1], "$420")
        # magnitudes are applied, so short and long notations of one amount agree
        for short, long_ in (("$9k-$27k", "9,000-27,000 USD"), ("$9-27k", "$9,000 to $27,000"), ("$1.2M", "$1.2 million"),
                             ("$0-$6.6k", "0-6,600 USD"), ("$5bn", "USD 5,000,000,000"), ("$5B", "5 billion USD")):
            self.assertEqual(lints._money_figures(short)[0][0], lints._money_figures(long_)[0][0], (short, long_))
        self.assertNotEqual(lints._money_figures("$5bn")[0][0], lints._money_figures("$5")[0][0])
        self.assertEqual(lints._money_figures("$1.2 million")[0][1], "$1.2 million")
        # the M of a milestone id is not a magnitude
        self.assertEqual(lints._money_figures("Cash: $6,600 M0, then M1"), [("6600", "$6,600")])
        # a range borrows a magnitude only when it stays in order; a smaller bare number after an amount is no range
        for a, b in (("$500-$2k", "$500-$2,000"), ("$900-1.2k", "$900-$1,200"), ("$2MM", "$2M"),
                     ("6 600 EUR", "EUR 6,600"), ("CHF 6'600", "6,600 CHF")):
            self.assertEqual(lints._money_figures(a)[0][0], lints._money_figures(b)[0][0], (a, b))
        self.assertEqual(lints._money_figures("Milestone 0: $6,600 - 2 builders"), [("6600", "$6,600")])
        # exact values: sub-cent prices stay apart
        self.assertNotEqual(lints._money_figures("$0.004 a call")[0][0], lints._money_figures("$0.0003 a call")[0][0])
        self.assertEqual(lints._money_figures("$1,000.50")[0][0], "1000.5")

    def test_basis_stripping_is_linear(self):
        import time
        start = time.time()
        for unit in ("; basis: x", "[a; basis: x"):
            lints._without_basis(unit * 100000)  # the first version needed minutes for this
        self.assertLess(time.time() - start, 5)
        self.assertEqual(lints._dates("M0 from 2026-09-28 to 2026-10-09; M1 2027-03; run 2026-09-24-name; 2026-13"),
                         ["2026-09-28", "2026-10-09", "2027-03"])
        self.assertEqual(lints._without_basis("[ESTIMATE: 0-6,600 USD; basis: host 3,000-6,000 USD]"),
                         "[ESTIMATE: 0-6,600 USD]")

    def test_norm_assumption(self):
        self.assertEqual(lints.norm_assumption(" A  | b. "), "a / b")


class CliTests(LintCase):
    def bs(self, *args):
        return subprocess.run([sys.executable, os.path.join(_SCRIPTS, "bs.py")] + list(args),
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              env=dict(os.environ, PYTHONIOENCODING="utf-8"))

    def test_exit_codes(self):
        self.assertEqual(self.bs("lint-arch", self.run).returncode, 0)
        self.assertEqual(self.bs("lint-proposal", self.run, "--lite").returncode, 0)
        self.sub("10_ARCHITECTURE/chosen/stack.md", "| VERIFIED | PSF", "| UNVERIFIED | PSF")
        self.assertEqual(self.bs("lint-arch", self.run).returncode, 0)  # warn only
        self.rm("10_ARCHITECTURE/risks.md")
        p = self.bs("lint-arch", self.run)
        self.assertEqual(p.returncode, 1)
        self.assertIn(b"FAIL A1 risks.md", p.stdout)
        self.rm("01_FRAME.md")
        self.assertEqual(self.bs("lint-frame", self.run).returncode, 0)
        with open(self.p("frame/lint.json"), encoding="utf-8") as f:
            self.assertEqual(json.load(f)["status"], "warn")
        self.rm("11_PROPOSAL/ONE-PAGER.md")
        self.assertEqual(self.bs("lint-proposal", self.run).returncode, 1)


if __name__ == "__main__":
    unittest.main()
