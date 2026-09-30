"""Phase H parsers: audit findings #34 and #41 (KIT_SPEC 4.5 Parsing, 4.12, 5.9).

- bs.py sources reads each line (and each JSON string and object) once: a run of '[' before a URL and thousands of URLs
  on one line or in one JSON string stay linear; a title never holds a URL and a date inside a URL is no access date
- free-text gate replies never match across a line break: G2 blank-line floods, G8b and G14 whitespace floods
- the section reader (registry.section, bs.py's seeds check) uses the contract's heading and fence rule: a '# comment'
  in a fenced block or a quoted '## N.' heading never cuts a section short or starts one
- 02_CONTEXT.md sections follow textio's fence rule also for unclosed '> ```' and '- ```bash x' lines
"""

import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fixtures", "engine"))
import engine_testlib as tl  # noqa: E402

from ublib import textio, validate  # noqa: E402
from ublib.engine import gates, privacy, registry, render  # noqa: E402

sys.path.insert(0, tl.SCRIPTS)
import bs  # noqa: E402

F = "```"
BUDGET = 1.0  # seconds; each input below took 5-25 s before the fix
with open(os.path.join(tl.TEMPLATES, "manifest.json"), encoding="utf-8") as _f:
    CONTRACTS = dict((k, v["contract"]) for k, v in json.load(_f)["prompts"].items())


def timed(fn):
    t0 = time.perf_counter()
    out = fn()
    return time.perf_counter() - t0, out


class SourcesCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ub-h-parsers-")
        self.run = os.path.join(self.tmp, "brainstorm", "2026-09-23-h-parsers")
        os.makedirs(self.run)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def w(self, rel, obj):
        p = os.path.join(self.run, *rel.split("/"))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8", newline="\n") as f:
            f.write(obj if isinstance(obj, str) else json.dumps(obj))

    def sources(self):
        with contextlib.redirect_stdout(io.StringIO()):
            bs.sources(self.run)
        with open(os.path.join(self.run, "sources.json"), encoding="utf-8") as f:
            return json.load(f)


class SourcesStayLinear(SourcesCase):
    def test_a_bracket_run_before_a_url(self):
        # '\[([^\]]*)\]\(\s*\)' rescanned the rest of the line from every '[': 80k took 10 s
        self.w("02_CONTEXT.md", "[" * 80000 + " https://a.example/x\n")
        dt, s = timed(self.sources)
        self.assertLess(dt, BUDGET)
        self.assertEqual([e["url"] for e in s.values()], ["https://a.example/x"])
        self.assertEqual(s["S-001"]["title"], "[" * 80)

    def test_thousands_of_urls_on_one_line(self):
        # the whole line was copied and cleaned once per URL: 8000 URLs took about 20 s
        urls = ["https://h%d.example/p" % i for i in range(8000)]
        self.w("02_CONTEXT.md", "Sources (2026-05-06): " + " ".join(urls) + "\n")
        dt, s = timed(self.sources)
        self.assertLess(dt, BUDGET)
        self.assertEqual([e["url"] for e in s.values()], urls)
        self.assertEqual(set(e["title"] for e in s.values()), {"Sources (2026-05-06)"})
        self.assertEqual(set(e["accessed"] for e in s.values()), {"2026-05-06"})

    def test_thousands_of_urls_in_one_json_string(self):
        urls = ["https://j%d.example/p" % i for i in range(8000)]
        self.w("10_ARCHITECTURE/stack.json", {"rows": [{"notes": "see " + " ".join(urls)}]})
        dt, s = timed(self.sources)
        self.assertLess(dt, BUDGET)
        self.assertEqual(len(s), 8000)
        self.assertEqual(set(e["title"] for e in s.values()), {"see"})

    def test_a_long_title_key_is_read_once_per_object(self):
        # the object's title keys were checked again for every URL of every string it holds
        urls = ["https://k%d.example/p" % i for i in range(8000)]
        title = "Queue benchmark " + "words " * 20000
        self.w("10_ARCHITECTURE/review/L1_gpt.json", {"findings": [{"issue": title, "evidence": " ".join(urls),
                                                                     "date": "2026-04-05"}]})
        dt, s = timed(self.sources)
        self.assertLess(dt, BUDGET)
        self.assertEqual(len(s), 8000)
        self.assertEqual(set(e["title"] for e in s.values()), {" ".join(title.split())[:80]})
        self.assertEqual(set(e["accessed"] for e in s.values()), {"2026-04-05"})


class SourceTitles(SourcesCase):
    def test_a_line_with_one_url_keeps_its_title_and_date(self):
        lines = {
            "- Survey of night nurses (2026-08-01): https://example.org/survey.":
                ("https://example.org/survey", "Survey of night nurses (2026-08-01)", "2026-08-01"),
            "- [Swap tools](https://example.org/tools), seen twice: https://example.org/tools;":
                ("https://example.org/tools", "Swap tools, seen twice", "2026-09-23"),
            "Match: SwapIt https://swapit.example.com/about) CROWDED":
                ("https://swapit.example.com/about", "Match: SwapIt ) CROWDED", "2026-09-23"),
            "See <https://example.net/postmortem>": ("https://example.net/postmortem", "See", "2026-09-23"),
            "| ShiftMate | https://shiftmate.example.com | 2026-07-30 | direct competitor |":
                ("https://shiftmate.example.com", "ShiftMate 2026-07-30 direct competitor", "2026-07-30"),
            "1. [Nurse forum thread](https://forum.example.org/t/123) (accessed 2026-05-06)":
                ("https://forum.example.org/t/123", "Nurse forum thread (accessed 2026-05-06)", "2026-05-06"),
            "## Prior art: https://x.example/y": ("https://x.example/y", "Prior art", "2026-09-23"),
        }
        for line, want in lines.items():
            self.w("02_CONTEXT.md", line + "\n")
            self.w("sources.json", {})  # a fresh registry: this line's URL is S-001
            e = self.sources()["S-001"]
            self.assertEqual((e["url"], e["title"], e["accessed"]), want, line)

    def test_a_title_never_holds_a_url_and_a_url_date_is_no_access_date(self):
        # each title was the line with only its own URL removed, so it quoted the other URLs of the line; and a date
        # inside one URL counted as the access date of the others
        self.w("02_CONTEXT.md", "Tools: https://a.example/x and https://b.example/2026-01-01/y\n"
                                "- [A](https://c.example/a) and [B](https://d.example/b)\n")
        s = self.sources()
        self.assertEqual([(e["url"], e["title"], e["accessed"]) for e in s.values()], [
            ("https://a.example/x", "Tools: and", "2026-09-23"),
            ("https://b.example/2026-01-01/y", "Tools: and", "2026-09-23"),
            ("https://c.example/a", "A and B", "2026-09-23"),
            ("https://d.example/b", "A and B", "2026-09-23")])


class RepliesStayOnTheirLine(unittest.TestCase):
    def assert_fast(self, gid, text):
        dt, out = timed(lambda: gates.parse_reply(gid, text))
        self.assertLess(dt, BUDGET, (gid, text[:20]))
        return out

    def test_a_g2_flood_of_blank_lines(self):
        # '^\s*(?:Q)?(\d+)\s*...' crossed newlines from every line start: 40k blank lines took 10 s
        self.assertEqual(self.assert_fast("G2", "x\n" + "\n" * 40000 + "prose here")["answers"], [])
        self.assertEqual(self.assert_fast("G2", "x\n" + " \n" * 40000 + "1. yes")["answers"], [{"q": "1", "a": "yes"}])

    def test_whitespace_floods_after_a_keyword(self):
        # '\s*:?\s*' split a whitespace run in every way before failing: 40k spaces took 4-10 s each
        ws = " " * 40000
        self.assertNotIn("runner_up", self.assert_fast("G8b", "runner up" + ws + "x"))
        self.assertNotIn("park", self.assert_fast("G8b", "park" + ws + "x"))
        self.assertNotIn("handoff", self.assert_fast("G14", "handoff" + ws + "x"))
        self.assertNotIn("merge_terms", self.assert_fast("G14", "merge" + ws + "x"))

    def test_a_g2_answer_is_the_rest_of_its_own_line(self):
        out = gates.parse_reply("G2", "Q1. yes\n2) no\n  3 - maybe later\n4:\n5: \n6. six\nok for the rest")
        self.assertEqual(out["answers"], [{"q": "1", "a": "yes"}, {"q": "2", "a": "no"}, {"q": "3", "a": "maybe later"},
                                          {"q": "6", "a": "six"}])
        self.assertTrue(out["accept_defaults"])
        self.assertEqual(gates.parse_reply("G2", "1: a\r\n2: b\r\n")["answers"], [{"q": "1", "a": "a"},
                                                                                {"q": "2", "a": "b"}])

    def test_keyword_answers_still_parse(self):
        out = gates.parse_reply("G8b", "I-002, runner up: I-003, park I-004 I-005")
        self.assertEqual((out["chosen"], out["runner_up"], out["park"]), ("I-002", "I-003", ["I-004", "I-005"]))
        self.assertEqual(gates.parse_reply("G8b", "I-002 runner-up\n\tI-003")["runner_up"], "I-003")
        out = gates.parse_reply("G14", "publish, handoff: speckit, merge :  some")
        self.assertEqual((out["publish"], out["handoff"], out["merge_terms"]), (True, "speckit", "some"))
        self.assertEqual(gates.parse_reply("G14", "handoff ce")["handoff"], "ce")


PROBE = ("# Probe\n\n## 1. Walk-through\nsteps\n\n## 2. Riskiest assumption\nTeams will pay.\n\n"
         "## 3. Probe design\nSend the landing page to 50 leads:\n\n" + F + "bash\n# build the list\n"
         "python make_list.py > leads.csv\n" + F + "\n\nThen count sign-ups after 7 days.\n\n"
         "## 4. Kill criterion\nFewer than 10 sign-ups out of 50.\n" + F + "text\n## 4. Kill criterion\nexample only\n"
         + F + "\n\nRESULT: PENDING\n")
REDTEAM = ("# Red team\n\n## 1. Per idea\n\n### I-001\n- Fails if: real kill\n\nThe decision brief template we used:\n\n"
           + F + "markdown\n## 2. Decision brief\n(template text, not the brief)\n" + F + "\n\n"
           "### I-002\n- Fails if: second kill\n\n## 2. Decision brief\nREAL BRIEF: pick I-001.\n\n"
           "## 3. Whole effort\nx\nWHOLE-EFFORT: CONTINUE\n")
CHECK = ("# Reality check I-001\n\n## 1. Prior art\nnone\n\n## 2. Steelman\nok\n\n## 3. Load-bearing claims\nx\n\n"
         "## 4. Kill-assumptions\n- Buyers answer within a week:\n" + F + "sql\n-- or with a shell:\n"
         "# SELECT count(*) FROM replies\n" + F + "\n- Budget exists this quarter.\n\n"
         "VERDICT: ADJACENT; DIFFERENTIATOR: night shifts\n")


class SectionsFollowTheContract(tl.EngineTestCase):
    def validated(self, text, prompt):
        ok, errs, parsed = validate.check_contract(text, CONTRACTS[prompt], None)
        self.assertTrue(ok, errs)
        return dict((k, v.strip()) for k, v in parsed["sections"].items())

    def test_a_fenced_comment_never_cuts_a_section(self):
        want = self.validated(PROBE, "PROBE")
        self.assertEqual(registry.section(PROBE, "3"), want["## 3. Probe design"])
        self.assertIn("Then count sign-ups after 7 days.", registry.section(PROBE, "3"))
        self.assertEqual(registry.section(PROBE, "4"), want["## 4. Kill criterion"])
        ctx = self.make_ctx(mode="quick")
        ctx.write("09_PROBE.md", PROBE)
        m0 = render.milestone0_section(ctx, "## 8. Roadmap")  # quick mode's proposal section 8
        self.assertIn("python make_list.py > leads.csv ``` Then count sign-ups after 7 days.", m0)
        self.assertIn("The kill criterion: Fewer than 10 sign-ups out of 50. ```text ## 4. Kill criterion", m0)
        want = self.validated(CHECK, "CHECK")
        self.assertEqual(registry.section(CHECK, "4"), want["## 4. Kill-assumptions"])
        ctx.state["choice"]["idea"] = "I-001"
        ctx.write("checks/I-001.md", CHECK)
        self.assertIn("- Budget exists this quarter.", registry._ph_kill_assumptions(ctx, {}))

    def test_a_quoted_heading_never_starts_a_section(self):
        want = self.validated(REDTEAM, "SYNTHESIS")
        self.assertEqual(registry.section(REDTEAM, "2"), "REAL BRIEF: pick I-001.")
        self.assertEqual(registry.section(REDTEAM, "2"), want["## 2. Decision brief"])
        self.assertEqual(registry.section(REDTEAM, "1"), want["## 1. Per idea"])
        self.assertIn("- Fails if: second kill", registry.section(REDTEAM, "1"))

    def test_the_section_rule(self):
        doc = ("# Title\n\n## Probe Design\nbody\n### Sub\nsub body\n## Probe design two\nsecond\n# Top\ntop\n"
               "## Success  looks like\nwin\n### Only three\nthree\n## Last")
        self.assertEqual(registry.section(doc, "probe design"), "body\n### Sub\nsub body")  # prefix, any case
        self.assertEqual(registry.section(doc, "Probe design two"), "second")  # a level-1 heading ends it
        self.assertEqual(registry.section(doc, "Success looks like"), "win\n### Only three\nthree")  # as the contract
        self.assertEqual(registry.section(doc, "Only three"), "")  # level 3 is not a level-2 section
        self.assertEqual(registry.section(doc, "Only three", 3), "three")
        self.assertEqual(registry.section(doc, "Last"), "")
        self.assertEqual(registry.section(doc, "Missing"), "")
        self.assertEqual(registry.section(None, "x"), "")
        self.assertEqual(registry.section(doc.replace("\n", "\r\n"), "Probe Design"), "body\n### Sub\nsub body")
        self.assertEqual(registry.sections_by_prefix(PROBE, ["2", "9"]), "## 2\nTeams will pay.")

    def test_bs_reads_the_seeds_as_the_engine_does(self):
        ctx = self.make_ctx()
        seeds = {"# Seeds\n\n## Ideas\n" + F + "\n# not a heading\n" + F + "\n- a real idea\n": True,
                 "# Seeds\n\n## Problem\nlike this:\n" + F + "md\n## Ideas\n- an example idea\n" + F + "\n": False,
                 "# Seeds\n\n## Ideas\n\n# Notes\n- later\n": False}
        for text, given in seeds.items():
            ctx.write("00_HUMAN_SEEDS.md", text)
            self.assertEqual(bs.seeds_done(ctx.run_dir)[0], given, text)
            self.assertEqual(registry.eval_when(ctx, ["no_seeds"]), not given, text)
        self.assertEqual(bs.section("## Ideas\n" + F + "\n## Primary idea\n" + F + "\nx\n## Obvious\n", "Ideas"),
                         F + "\n## Primary idea\n" + F + "\nx")


class ContextSectionsFollowTextioFences(tl.EngineTestCase):
    def test_unclosed_marker_fences_hide_nothing(self):
        """#41: privacy's fence rule opens a fence behind '> ' and '- ' and runs an unclosed one to the end; the P-GROUND
        contract (textio) reads those lines as text, so LANDSCAPE is there."""
        ctx = self.make_ctx()
        for first in ("> " + F + "\n> quoted", "- " + F + "bash make build"):
            doc = ("## A. FACTS\n- a fact\n%s\n## B. LANDSCAPE\n- competitor tool X\n## C. SEARCH BOUNDARY\n- q\n"
                   % first)
            self.assertTrue(any(privacy.fence_mask(doc.split("\n"))))  # the case where the two rules differ
            self.assertTrue(validate.check_contract(doc, CONTRACTS["P-GROUND"], None)[0])
            ctx.write("02_CONTEXT.md", doc)
            self.assertEqual(registry.context_section(ctx, "B"), "## B. LANDSCAPE\n- competitor tool X")
            self.assertEqual(registry.context_section(ctx, "C"), "- q")
            self.assertEqual(registry.context_section(ctx, "A"), "- a fact\n" + first)
            self.assertEqual([t for _i, _l, t in textio.headings(doc)], ["A. FACTS", "B. LANDSCAPE",
                                                                         "C. SEARCH BOUNDARY"])


if __name__ == "__main__":
    unittest.main()
