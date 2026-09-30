"""Static check: every glob over a folder goes through textio.glob_in (round 3, a '[' in the run path).

glob.glob(os.path.join(run_dir, ...)) reads a folder named 'client [2026]' as the character class [2026] and finds
nothing, so supersede, the curator bundles, the privacy leak checks and the bs.py scans silently saw no files.
textio.glob_in escapes the folder; a new direct call would bring the bug back.
"""

import os
import re
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "harness"))
import paths  # noqa: E402

DIRECT = re.compile(r"\b(?:glob|_g)\.i?glob\(|^\s*from\s+glob\s+import\b", re.M)
ROOTS = ("skills", "install", "profiles", "tools")
ALLOWED = {os.path.join("skills", "ultimate-brainstorm", "scripts", "ublib", "textio.py")}


class GlobGoesThroughGlobIn(unittest.TestCase):
    def test_no_direct_glob_calls(self):
        found = []
        for root in ROOTS:
            for dirpath, dirnames, filenames in os.walk(os.path.join(paths.KIT, root)):
                dirnames[:] = [d for d in dirnames if d != "__pycache__"]
                for fn in filenames:
                    if not fn.endswith(".py"):
                        continue
                    path = os.path.join(dirpath, fn)
                    rel = os.path.relpath(path, paths.KIT)
                    if rel in ALLOWED:
                        continue
                    with open(path, encoding="utf-8") as f:
                        text = f.read()
                    for m in DIRECT.finditer(text):
                        found.append("%s:%d" % (rel, text.count("\n", 0, m.start()) + 1))
        self.assertEqual(found, [], "use textio.glob_in (it escapes the folder) instead of glob.glob at: %s"
                         % ", ".join(found))


if __name__ == "__main__":
    unittest.main()
