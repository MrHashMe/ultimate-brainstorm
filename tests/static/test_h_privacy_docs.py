"""Phase H, docs against behavior (KIT_SPEC 6.8, 11): PRIVACY.md promises for indented lines under a sentence or a list
item exactly what strip_code removes (NEW-G7-privacy-publish-2), and the spec's test list no longer describes a 0600
repair that publish deliberately does not do (NEW-G7-privacy-publish-3)."""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "harness"))
import paths  # noqa: E402

from ublib import textio  # noqa: E402
from ublib.engine import privacy as pv  # noqa: E402


def code_row():
    text = textio.read_text(os.path.join(paths.KIT, "docs", "PRIVACY.md"))
    return [ln for ln in text.split("\n") if ln.startswith("| **code**")][0]


class PrivacyDocTests(unittest.TestCase):
    def test_the_code_row_promises_what_strip_code_does(self):
        row = code_row()
        # the old promise ('indented code right under a sentence or a list item ... is removed') overstated it
        self.assertNotIn("indented code right under a sentence or a list item, and inline code", row)
        self.assertIn("ends with `:`", row)
        self.assertIn("reads as code", row)
        self.assertIn("indented prose that is not introduced by a `:`", row)
        # ... and each part of the promise holds
        self.assertNotIn("SECRET", pv.strip_code("The config reads:\n    plain SECRET words\n"))
        self.assertNotIn("SECRET", pv.strip_code("- F1: the key\n    API_KEY: SECRET\n"))
        self.assertNotIn("SECRET", pv.strip_code("- F1: deploy\n    curl -H SECRET https://x.internal\n"))
        prose = "- F1: the ward\n    and the SECRET night shift\n"
        self.assertEqual(pv.strip_code(prose), prose)
        cite = "The handler is here:\n    (source: src/pay.py:10)\n"
        self.assertEqual(pv.strip_code(cite), cite)


class SpecTestListTests(unittest.TestCase):
    def test_the_handoff_test_line_describes_the_mode_rule(self):
        spec = textio.read_text(os.path.join(paths.KIT, "docs", "design", "KIT_SPEC.md"))
        start = spec.index("- `test_engine_handoff.py`:")
        entry = spec[start:spec.index("\n- `", start + 1)]
        self.assertNotIn("0600 copies\n  repaired", entry)
        self.assertNotIn("repaired", entry)
        self.assertIn("an unchanged published file keeps whatever mode it has", " ".join(entry.split()))


if __name__ == "__main__":
    unittest.main()
