"""Parsers over model output are linear (KIT_SPEC 4.5): adversarial 1 MB outputs validate in well under a second,
and there is one definition of a fenced code block and of an ATX heading (textio), shared by validate, lints and
render. Findings #33, #34, #37 and #41 (fences) of the architecture audit."""

import os
import random
import re
import sys
import time
import unittest

_KIT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_SCRIPTS = os.path.join(_KIT, "skills", "ultimate-brainstorm", "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

from ublib import filesproto, lints, textio, validate  # noqa: E402
from ublib.engine import render  # noqa: E402

BUDGET_S = 1.0  # the whole check_contract call, on a 1 MB input
PAD = ("The survey covered night-shift nurses in three rural wards; most swaps are arranged by phone. " * 11000)[:1000000]


def timed(fn, *args):
    t0 = time.perf_counter()
    try:
        out = fn(*args)
    except ValueError as e:
        out = e
    return out, time.perf_counter() - t0


class AdversarialBudget(unittest.TestCase):
    """REPORT 6.1 'sections output' and the worst shapes the verifiers measured (seconds to hours before)."""

    def assertFast(self, seconds, what):
        self.assertLess(seconds, BUDGET_S, "%s took %.2f s" % (what, seconds))

    def test_heading_with_long_whitespace_run(self):
        # '## A. FACTS' + 2,000 spaces + 'x' was cubic: 6 s per check, repeated on every poll
        c = {"type": "sections", "headings": ["## A. FACTS", "## B. LANDSCAPE"]}
        for ws in (" ", "\t", "\u00a0"):
            text = "## A. FACTS" + ws * 2000 + "x\nfact\n\n## B. LANDSCAPE\n" + PAD
            (ok, errors, _p), s = timed(validate.check_contract, text, c, None)
            self.assertTrue(ok, errors)
            self.assertFast(s, "sections check with a %r run" % ws)
        h, s = timed(textio.parse_heading, "## A" + " " * 200000 + "b")
        self.assertEqual(h, (2, "A" + " " * 200000 + "b"))
        self.assertFast(s, "parse_heading")
        h, s = timed(textio.parse_heading, "## " + "#" * 200000 + "b")  # was quadratic
        self.assertFast(s, "parse_heading on a '#' run")

    def test_sections_with_heading_run_and_8000_unclosed_json_openers(self):
        c = {"type": "sections", "headings": ["## A. FACTS"], "json_tail": True}
        text = "## A. FACTS" + " " * 2000 + "x\n" + PAD[:400000] + "\n" + "```json\n" * 8000 + PAD[:500000]
        (ok, errors, _p), s = timed(validate.check_contract, text, c, None)
        self.assertFalse(ok)
        self.assertTrue(any("json tail" in e for e in errors), errors)
        self.assertFast(s, "sections check with 8,000 unclosed openers")

    def test_json_contract_on_unclosed_fence_floods(self):
        for text in ("```json\n" * 130000, "Here is the JSON:\n```json\n{\"a\": 1, \"b\": [1, 2]}\n" * 20000,
                     "```mermaid\n" * 90000):
            (ok, _errors, _p), s = timed(validate.check_contract, text, {"type": "json"}, None)
            self.assertFast(s, "json check on %r..." % text[:20])

    def test_json_contract_on_bracket_floods(self):
        # retrying raw_decode at every '{' / '[' cost O(n * depth), and every JSONDecodeError counted newlines from 0
        for text in ("[" * 1000000, "{" * 1000000, "[1," * 330000, '{"a":' * 200000, "{" * 500000 + "}" * 500000,
                     "[" * 499999 + "x" + "]" * 500000, "[x]" * 330000, "{}" * 500000, '{"a": NaN}' * 100000):
            (ok, _errors, _p), s = timed(validate.check_contract, text, {"type": "json"}, None)
            self.assertFast(s, "json check on %r... (%d chars)" % (text[:12], len(text)))
        out, s = timed(textio.extract_json, "[" * 50000)
        self.assertIsInstance(out, ValueError)
        self.assertFast(s, "extract_json('[' * 50000)")

    def test_idea_blocks_with_blank_line_runs(self):
        # '^\s*[-*]...Fails if' with re.M was quadratic in a run of blank lines
        c = {"type": "idea-blocks", "prefix": "S3", "min": 1}
        good = "### S3-01 One\n- Pitch: p\n- Mechanism: m\n- Fails if: f\n"
        text = good + "### S3-02 Two\n- Pitch: p\n" + "\n" * 200000 + "- Mechanism: m\n"
        (ok, errors, parsed), s = timed(validate.check_contract, text, c, None)
        self.assertTrue(ok, errors)
        self.assertEqual([b["id"] for b in parsed], ["S3-01"])
        self.assertFast(s, "idea-blocks check with 200,000 blank lines")

    def test_file_marker_with_long_whitespace(self):
        text = "=== FILE: docs/a.md" + " " * 200000 + "x\ncontent\n"
        out, s = timed(filesproto.parse_file_blocks, text)
        self.assertEqual(out[0], {})
        self.assertFast(s, "parse_file_blocks on a 200,000-space marker line")
        text = "=== FILE: a.md" + " " * 200000 + "===\nbody\n=== END FILE ===\n"
        self.assertEqual(filesproto.parse_file_blocks(text)[0], {"a.md": "body\n"})

    def test_lints_on_blank_line_runs(self):
        text = "# Cost model\n\n## Assumptions\n" + "\n" * 200000 + "x\n## Sensitivity\n"
        _o, s = timed(lints.word_count, text)
        self.assertFast(s, "word_count")
        heads, s = timed(lints._headings, "## A" + " " * 3000 + "b\n" + "\n" * 100000)
        self.assertEqual(heads[0][:2], (2, "A" + " " * 3000 + "b"))
        self.assertFast(s, "lints._headings")

    def test_render_heading_and_fence(self):
        md = "## A" + " " * 3000 + "b\n\n" + "```json\n" * 20000
        _o, s = timed(render.md_to_html, md)
        self.assertFast(s, "md_to_html")
        _o, s = timed(render.split_h2, "## A" + " " * 3000 + "b\nbody\n")
        self.assertFast(s, "split_h2")


OLD_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")


class HeadingParserIsTheOldRegex(unittest.TestCase):
    def test_same_groups_as_the_old_pattern(self):
        rnd = random.Random(33)
        alphabet = ["#", " ", "\t", "a", "b", "C", "\u00a0", "\x0b", "#", " "]
        for _ in range(30000):
            line = "".join(rnd.choice(alphabet) for _ in range(rnd.randint(0, 14)))
            for s in (line, line.rstrip()):
                m = OLD_HEADING.match(s)
                want = (len(m.group(1)), m.group(2)) if m else None
                self.assertEqual(textio.parse_heading(s), want, repr(s))

    def test_headings_skip_fences(self):
        text = "# One\n```\n# not a heading\n```\n## Two ##\n~~~~\n### inside\n~~~\n### still inside\n"
        self.assertEqual(textio.headings(text), [(0, 1, "One"), (4, 2, "Two")])


class OneFenceDefinition(unittest.TestCase):
    """A fence closes on the same character, at least as long (CommonMark); an unclosed fence runs to the end. The
    validator, the lints and the renderer agree (they used three different rules before)."""

    LONGER_CLOSER = "# Doc\n\n```mermaid\nflowchart LR\n  A --> B\n````\n\nafter\n"

    def test_longer_closer(self):
        self.assertEqual(textio.fenced_blocks(self.LONGER_CLOSER), [("mermaid", "flowchart LR\n  A --> B\n")])
        self.assertEqual(lints.mermaid_blocks(self.LONGER_CLOSER), [(3, ["flowchart LR", "  A --> B"])])
        text = "=== FILE: a.md ===\n%s=== END FILE ===\n" % self.LONGER_CLOSER
        c = {"type": "files", "allowed": ["a.md"], "per_file": {"a.md": {"mermaid": ["flowchart"]}}}
        ok, errors, _ = validate.check_contract(text, c, None)
        self.assertTrue(ok, errors)
        self.assertIn('<pre class="mermaid">flowchart LR\n  A --&gt; B</pre>', render.md_to_html(self.LONGER_CLOSER))
        self.assertIn("<p>after</p>", render.md_to_html(self.LONGER_CLOSER))

    def test_rules(self):
        self.assertEqual(textio.fence_open("  ```JSON extra"), ("`", 3, "json"))
        self.assertEqual(textio.fence_open("~~~~"), ("~", 4, ""))
        self.assertIsNone(textio.fence_open("```inline``` code"))
        self.assertIsNone(textio.fence_open("``not"))
        f = textio.fence_open("````")
        self.assertFalse(textio.fence_closes("```", f))
        self.assertFalse(textio.fence_closes("~~~~", f))
        self.assertFalse(textio.fence_closes("```` x", f))
        self.assertTrue(textio.fence_closes(" ````` ", f))
        text = "a\n```\n## h\n````\n## real\n~~~\nopen to the end\n"
        self.assertEqual(textio.fence_spans(text), [(1, 3, "`", 3, ""), (5, None, "~", 3, "")])
        self.assertEqual(textio.fence_mask(text.split("\n")), [False, True, True, True, False, True, True, True])
        self.assertEqual(textio.fenced_blocks("```json\n{\"a\": 1}\n"), [("json", "{\"a\": 1}\n")])

    def test_validator_and_lints_mask_alike(self):
        text = "x\n~~~ \n## no\n~~~~\n```\n## no\n``` \n## yes\n"
        self.assertEqual(lints.fence_mask(text.split("\n")), textio.fence_mask(text.split("\n")))
        c = {"type": "sections", "headings": ["## yes"]}
        self.assertTrue(validate.check_contract(text, c, None)[0])
        self.assertFalse(validate.check_contract(text, {"type": "sections", "headings": ["## no"]}, None)[0])


if __name__ == "__main__":
    unittest.main()
