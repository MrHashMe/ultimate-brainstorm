"""Phase J, docs against behavior (KIT_SPEC 6.8): PRIVACY.md's code row promises what strip_code does for a lead whose
':' sits inside emphasis and for code in quoted text at a nested list item's content column
(NEW-G7-privacy-publish-2), and each promise holds."""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "harness"))
import paths  # noqa: E402

from ublib import textio  # noqa: E402
from ublib.engine import privacy as pv  # noqa: E402


def code_row():
    text = textio.read_text(os.path.join(paths.KIT, "docs", "PRIVACY.md"))
    return " ".join([ln for ln in text.split("\n") if ln.startswith("| **code**")][0].split())


class PrivacyCodeRowTests(unittest.TestCase):
    def test_a_colon_inside_emphasis_introduces_code(self):
        self.assertIn("also inside bold or italics, as in `**Install:**`", code_row())
        self.assertNotIn("SECRET", pv.strip_code("**Install:**\n    npm install SECRET_pkg\n"))
        self.assertNotIn("SECRET", pv.strip_code("- F3: *the config reads:*\n    the SECRET word\n"))

    def test_quoted_text_loses_every_line_indented_four_columns(self):
        row = code_row()
        self.assertIn("in text quoted from earlier steps", row)
        self.assertIn("every line indented 4 or more columns is removed unless it is a list item or only cites", row)
        quoted = pv.fence_data("CHECKS", "- F1: payments\n  - the handler (src/pay.py:10)\n    charge the SECRET rate\n"
                                         "    - a nested item\n")
        out = pv.strip_code("CHECKS\n%s\n" % quoted)
        self.assertNotIn("SECRET", out)
        self.assertIn("- F1: payments", out)
        cite = pv.fence_data("CHECKS", "- F1: payments\n    (source: src/pay.py:10)\n")
        self.assertEqual(pv.strip_code(cite), cite)

    def test_domain_terms_and_worktrees(self):
        row = code_row()
        self.assertIn("marked `[proposed]`, never the terms of your repository's CONTEXT.md", row)
        self.assertIn("inside a git repository (a git worktree or submodule too)", row)
        self.assertEqual(pv.filter_a2_terms("1. **Float pool**: nurses without a home ward (CONTEXT.md)"), "")


if __name__ == "__main__":
    unittest.main()
