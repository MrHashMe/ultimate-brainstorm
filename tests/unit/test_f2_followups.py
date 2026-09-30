"""F2 small follow-ups of Phase E.

X4  SKILL.md's fallback poll carries the HOST_BATCH lease (F96): the lease holder that polls with `UB next` instead of
    the card's "then" presents its --lease, or it waits for itself until the lease expires.
X5  templates/host/S1-CE.md has no s1_seen.json step (F18): 4.1c never writes that file and the engine never reads it.
X6  detect.shim_path_problem's docstring names why each path reaches a shim (F29), not the stale schema-file reason.
X7  (finding 34) E3 made the SKIPPED / RESULT line checks linear (test_e3_bs_status). The section-13 question parser
    of `bs.py assumptions` (Owner: / Decide by:) was quadratic too, 20-35 s on one line with a 40,000-space run; it is
    now linear, with the same results as the regex it replaces except that a field now takes its closing ')', ';' or
    '|' and its value no trailing ',' or '-' (Phase J).
"""

import os
import random
import re
import sys
import time
import unittest

_KIT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_SK = os.path.join(_KIT, "skills", "ultimate-brainstorm")
_SCRIPTS = os.path.join(_SK, "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

import bs  # noqa: E402
import ub  # noqa: E402
from ublib import detect, textio  # noqa: E402
from ublib.engine import cards  # noqa: E402


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


class SkillLoopLease(unittest.TestCase):
    def loop_step1(self):
        text = read(os.path.join(_SK, "SKILL.md"))
        loop = text[text.index("## The loop"):]
        return " ".join(loop[loop.index("1. "):loop.index("\n2. ")].split())

    def test_the_fallback_poll_presents_the_lease(self):
        self.assertEqual(self.loop_step1(), '1. Run the card\'s "then" command (or UB next "<run>" --wait-s W --json, '
                                            'adding the --lease <token> of the last "then" or "task.done_cmd" that '
                                            'had one) with your shell timeout above W (table).')

    def test_the_fallback_poll_is_what_the_engine_writes(self):
        # the command the SKILL.md line describes is the one cards.next_cmd puts in a lease holder's "then"
        run = os.path.join(_KIT, "brainstorm", "2026-09-26-r")
        then = cards.next_cmd({"runner": "UB"}, run, wait_s=50, lease="0123abcd")
        self.assertEqual(then, 'UB next "%s" --wait-s 50 --lease 0123abcd --json' % textio.to_posix(run))
        a = ub.build_parser().parse_args(["next", run, "--wait-s", "50", "--json", "--lease", "0123abcd"])
        self.assertEqual((a.cmd, a.run, a.wait_s, a.lease, a.json), ("next", run, 50, "0123abcd", True))


class S1CeTemplate(unittest.TestCase):
    def test_no_dead_s1_seen_step(self):
        text = read(os.path.join(_SK, "templates", "host", "S1-CE.md"))
        self.assertNotIn("s1_seen", text)
        self.assertNotIn("human_saw_s1_ranking", text)
        steps = [int(n) for n in re.findall(r"^(\d+)\. ", text, re.M)]
        self.assertEqual(steps, list(range(1, len(steps) + 1)))
        self.assertTrue(re.search(r"^%d\. Run task\.done_cmd\.$" % steps[-1], text, re.M), "done_cmd stays last")
        text.encode("ascii")


class ShimDocstring(unittest.TestCase):
    def test_the_reasons_match_the_callers(self):
        doc = " ".join(detect.shim_path_problem.__doc__.split())
        self.assertNotIn("schema files", doc)  # codex schemas live in the call folder under UB_HOME/tmp
        for needle in ("the run folder (claude's run-folder deny rules)", "the repository (codex -C)",
                       "only for families of the host's vendor in a repository run", "ub.shim_problems"):
            self.assertIn(needle, doc)


# the section-13 parser of F0: the reference for the differential test (quadratic on long runs)
_OLD_FIELD_RE = re.compile(r"[\s(;,.-]*\b(owner|decide[ _-]*by)\s*:\s*([^;|)]*?)\s*(?=[;|)]|\b(?:owner|decide[ _-]*by)"
                           r"\s*:|$)", re.I)


def old_section13_questions(text):
    out = []
    for line in (text or "").split("\n"):
        m = re.match(r"^\s*(?:[-*+]|\d+[.)])\s+(.*\S)\s*$", line)
        if not m:
            continue
        body = m.group(1).replace("**", "")
        owner = by = None
        for fm in _OLD_FIELD_RE.finditer(body):
            if fm.group(1).lower().startswith("owner"):
                owner = fm.group(2).strip(" .") or None
            else:
                by = fm.group(2).strip(" .") or None
        q = _OLD_FIELD_RE.sub("", body).strip(" -;,")
        if q:
            out.append((" ".join(q.split()), owner, by))
    return out


class Section13Questions(unittest.TestCase):
    TOKENS = ["owner", "Owner", "OWNER", "decide by", "Decide-by", "decide_by", "decide - _by", "decideby", "by",
              ":", " : ", ";", "|", ")", "(", ",", ".", "-", "*", "**", "+", " ", "  ", "\t", "\r", "\u00a0", "\x1c",
              "\u200b", "\u3000", "x", "Q", "who", "1.", "2)", "12.", "\u0663.", "?", "\u00e9", "owner:", "decide by:",
              "xowner:", "_owner:", "\n"]

    def test_same_results_as_the_regex(self):
        # the regex left a field's closing ')', ';' or '|' in the question and a trailing ',' or '-' in its value
        # (JD-ranking-validation): where none of those characters occurs the results are still the regex's, and every
        # result is clean
        rnd = random.Random(20260926)
        prefixes = ["- ", "* ", "+ ", "1. ", "3) ", "  - ", "-", "\t12. ", "", " - ", "-\u00a0", "\u00a0- "]
        for _ in range(8000):
            text = rnd.choice(prefixes) + "".join(rnd.choice(self.TOKENS) for _ in range(rnd.randint(0, 24)))
            got = bs._section13_questions(text)
            bodies = [m.group(1) for m in (re.match(r"^\s*(?:[-*+]|\d+[.)])\s+(.*\S)\s*$", ln)
                                           for ln in text.split("\n")) if m]
            if not set("".join(bodies)) & set(")|;,-"):
                # the parser also drops a '.' or '*' the regex left at the ends of a question or a value (LE-bs)
                old = [(q.strip(" .*"), o and o.strip(" .*") or None, b and b.strip(" .*") or None)
                       for q, o, b in old_section13_questions(text)]
                self.assertEqual(got, [r for r in old if r[0]], repr(text))
            for q, owner, by in got:
                self.assertEqual(q, q.strip(" -;,|"), repr(text))
                for value in (owner, by):
                    self.assertTrue(value is None or (value == value.strip(" .,;-") and value), repr(text))
                    depth = 0  # a ';', '|' or ')' stays in a value only inside a bracket the value opened
                    for ch in value or "":
                        self.assertTrue(depth or ch not in ";|)", repr(text))
                        depth += (ch == "(") - (ch == ")")

    def test_the_documented_shapes(self):
        # proposal.md: each section 13 item with "Owner: <role>" and "Decide by: <milestone>"
        text = ("# 13 Open questions\n\n- Which region hosts the data? Owner: ops lead; Decide by: 2026-10-01\n"
                "2) Who signs off? **Owner:** legal. **Decide by:** Milestone 1.\n"
                "1. Keep the free plan? | Owner: CEO\n- Only a question\n- \n"
                "- Which cloud? (Owner: CTO) (Decide by: M0)\n- Pricing tier? (Owner: CFO, Decide by: 2026-11-01)\n")
        expected = [("Which region hosts the data?", "ops lead", "2026-10-01"),
                    ("Who signs off?", "legal", "Milestone 1"), ("Keep the free plan?", "CEO", None),
                    ("Only a question", None, None), ("Which cloud?", "CTO", "M0"),
                    ("Pricing tier?", "CFO", "2026-11-01")]
        self.assertEqual(bs._section13_questions(text), expected)

    def test_floods_cost_linear_time(self):
        n = 40000
        lines = ["- q owner: a" + " " * n + "b",        # a whitespace run inside a value (35 s before)
                 "- q" + " " * n + "x",                 # separators not followed by a key (20 s)
                 "- q" + "-" * n + "x owner: y",
                 "-" + " " * n,                         # a bullet with nothing after it (3.5 s)
                 "- decide" + " " * n + "x",
                 "- " + "owner: " * (n // 7),           # many empty fields
                 "- q" + " ;" * n + " owner: z",
                 "- q" + " |" * n + " owner: z",
                 "- q" + " (" * n + " owner: z" + ")" * n]
        start = time.perf_counter()
        for line in lines:
            bs._section13_questions(line)
        self.assertLess(time.perf_counter() - start, 2.0)


if __name__ == "__main__":
    unittest.main()
