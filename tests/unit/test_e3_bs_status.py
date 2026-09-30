"""Phase E3, bs.py status inputs: the SKIPPED and RESULT line checks stay linear on long blank runs (finding 34), and
@evolved-checks counts the E ideas the idea-blocks contract counts (finding 41)."""

import json
import os
import shutil
import sys
import tempfile
import time
import unittest

_KIT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_SCRIPTS = os.path.join(_KIT, "skills", "ultimate-brainstorm", "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

import bs  # noqa: E402


class StatusCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ub-e3-status-")
        self.run = os.path.join(self.tmp, "brainstorm", "2026-09-26-e3-status")
        os.makedirs(self.run)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def w(self, rel, text):
        p = os.path.join(self.run, *rel.split("/"))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8", newline="\n") as f:
            f.write(text if isinstance(text, str) else json.dumps(text))


class LinearLineChecks(StatusCase):
    def test_blank_line_floods_cost_linear_time(self):
        # finding 34 (3): '^\W*SKIPPED' and '^\W*RESULT\s*:' crossed newlines at every line start: 40k blank lines
        # took 7-9 s
        self.w("00_HUMAN_SEEDS.md", "# Human seeds\n" + "\n" * 60000 + "x\n")
        self.w("09_PROBE.md", "# Probe\n" + "\n" * 60000 + "x\n")
        start = time.perf_counter()
        self.assertFalse(bs.seeds_done(self.run)[0])
        self.assertFalse(bs.check_item(self.run, "@probe-result")[0])
        self.assertLess(time.perf_counter() - start, 3.0)

    def test_the_line_checks_still_match(self):
        self.w("00_HUMAN_SEEDS.md", "# Human seeds\n\n**SKIPPED**: no time\n")
        self.assertTrue(bs.seeds_done(self.run)[0])
        self.w("09_PROBE.md", "# Probe\n\n- RESULT: PENDING\n")
        self.assertEqual(bs.check_item(self.run, "@probe-result"), (True, "designed; RESULT: PENDING"))
        self.w("09_PROBE.md", "# Probe\n\n> RESULT : PASSED\n")
        self.assertEqual(bs.check_item(self.run, "@probe-result"), (True, ""))


class EvolvedChecks(StatusCase):
    def test_only_real_idea_blocks_need_a_check(self):
        # finding 41 (3): a fenced example and an incomplete block were E ideas to @evolved-checks only
        self.w("05_EVOLVED.md", "# EVOLVED\n\n```\n### E-09 an example\n```\n\n### E-01 Real\n- Pitch: p\n"
                                "- Mechanism: m\n- Fails if: f\n\n### E-05 Cut off\n- Pitch: p\n")
        self.assertEqual(bs.check_item(self.run, "@evolved-checks"), (False, "no check for E-01"))
        self.w("checks/E-01.md", "x\n")
        self.assertEqual(bs.check_item(self.run, "@evolved-checks"), (True, ""))


if __name__ == "__main__":
    unittest.main()
