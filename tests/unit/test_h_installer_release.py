"""Release gate: the per-host Doctor column counts only recorded results (audit finding #91, round-3 note). Owner: HG.

tools/release.py refuses to build while fewer than 2 rows of the per-host table of docs/ACCEPTANCE.md record the Doctor
check. "not tested" and "not yet verified live", the Procedure's own words for "no result", record no check, so a
release can no longer pass the gate with two such cells.
"""

import importlib.util
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "harness"))
import paths  # noqa: E402

ACCEPTANCE = """# Live acceptance checklist

| Host | Versions | 1 Doctor | 2 Quick | 3 Standard | 4 Continue | 5 Requests / plan | Notes |
|---|---|---|---|---|---|---|---|
| Claude Code | 2.1 | %s | | | | | |
| Codex | 0.156 | %s | | | | | |
| Kimi Code | | | | | | | |

| Check | How | Pass when | Result | Host and version | Date |
|---|---|---|---|---|---|
| Windows PowerShell 5.1 kickoff | x | y | confirmed | Codex 0.156, Windows 11 | 2026-09-30 |
"""
HOSTS_GAP = "the per-host checks ran on %d host(s), not 2 (Doctor column)"


def load_release():
    spec = importlib.util.spec_from_file_location("ub_release_hg", paths.RELEASE_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class DoctorColumn(unittest.TestCase):
    def setUp(self):
        self.release = load_release()

    def gaps(self, first, second):
        with tempfile.TemporaryDirectory() as kit:
            os.makedirs(os.path.join(kit, "docs"))
            with open(os.path.join(kit, "docs", "ACCEPTANCE.md"), "w", encoding="utf-8", newline="\n") as f:
                f.write(ACCEPTANCE % (first, second))
            return self.release.acceptance_gaps(kit)

    def test_no_result_words_are_not_a_host_check(self):
        self.assertEqual(self.gaps("not tested", "not tested"), [HOSTS_GAP % 0])
        self.assertEqual(self.gaps("PONG", "Not yet verified live"), [HOSTS_GAP % 1])

    def test_two_recorded_results_pass(self):
        self.assertEqual(self.gaps("PONG from claude, gpt", "PONG"), [])


if __name__ == "__main__":
    unittest.main()
