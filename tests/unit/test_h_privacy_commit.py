"""Phase H, the FILE protocol (KIT_SPEC 4.6.4): a commit that fails and is interrupted while it cleans up is undone by
the next recover(), never rolled forward with only some of its temps (review note P3-validation-privacy-0): the abort
path marks its journal aborted once every target is back, and recover() rolls an aborted journal back."""

import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

_KIT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_SCRIPTS = os.path.join(_KIT, "skills", "ultimate-brainstorm", "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

from ublib import filesproto, textio  # noqa: E402

NAMES = ("a.md", "b.md", "c.md")


class AbortTests(unittest.TestCase):
    def setUp(self):
        self.root = os.path.realpath(tempfile.mkdtemp(prefix="ub-h-commit-"))
        self.addCleanup(shutil.rmtree, self.root, True)
        for name in NAMES:
            textio.write_text_atomic(os.path.join(self.root, name), "OLD %s\n" % name)

    def texts(self):
        return [textio.read_text(os.path.join(self.root, n)) for n in NAMES]

    def test_an_interrupt_while_a_failed_commit_cleans_up_leaves_every_target_old(self):
        # c.md is held open (Windows), so the commit fails at step 3 and puts a.md and b.md back; a SIGTERM (SystemExit
        # from the worker's handler) after the first temp is removed left a journal whose other temps recover() then
        # rolled forward: a.md old, b.md and c.md new
        c = os.path.normcase(os.path.join(self.root, "c.md"))
        real_replace, real_unlink = textio._replace_with_retry, os.unlink
        removed = []

        def replace(src, dst, *a, **k):
            if os.path.normcase(src) == c and dst.endswith(".bak"):
                raise PermissionError("c.md is held open")
            return real_replace(src, dst, *a, **k)

        def unlink(path, *a, **k):
            real_unlink(path, *a, **k)
            if str(path).endswith(".tmp") and not removed:
                removed.append(path)
                raise SystemExit(143)
        with mock.patch.object(filesproto.textio, "_replace_with_retry", side_effect=replace), \
                mock.patch.object(filesproto.os, "unlink", side_effect=unlink):
            with self.assertRaises(SystemExit):
                filesproto.write_file_blocks(dict((n, "NEW %s\n" % n) for n in NAMES), self.root, ["*.md"])
        self.assertEqual(len(removed), 1)
        journals = [n for n in os.listdir(self.root) if n.startswith(filesproto.JOURNAL_PREFIX)]
        self.assertEqual(len(journals), 1)  # the interrupted clean-up left its journal
        self.assertEqual(filesproto.recover(self.root), 1)
        self.assertEqual(self.texts(), ["OLD a.md\n", "OLD b.md\n", "OLD c.md\n"])
        self.assertEqual(sorted(os.listdir(self.root)), list(NAMES))  # temps, backups and the journal are gone

    def test_an_aborted_journal_is_rolled_back(self):
        # a crash left a target at its backup name under a journal marked aborted: the backup comes back, the new
        # content never goes in
        a, tmp, bak = (os.path.join(self.root, n) for n in ("a.md", ".a.md.x1.tmp", ".a.md.x1.bak"))
        textio.write_text_atomic(tmp, "NEW a.md\n")
        os.replace(a, bak)
        entry = {"target": "a.md", "tmp": ".a.md.x1.tmp", "bak": ".a.md.x1.bak", "old": textio.sha256_file(bak),
                 "new": textio.sha256_file(tmp)}
        journal = os.path.join(self.root, filesproto.JOURNAL_PREFIX + "x1.json")
        with open(journal, "w", encoding="ascii") as f:
            json.dump({"schema": 1, "aborted": True, "entries": [entry]}, f)
        self.assertEqual(filesproto.recover(self.root), 1)
        self.assertEqual(textio.read_text(a), "OLD a.md\n")
        self.assertEqual(sorted(os.listdir(self.root)), list(NAMES))

    def test_a_failed_commit_still_leaves_nothing(self):
        c = os.path.normcase(os.path.join(self.root, "c.md"))
        real_replace = textio._replace_with_retry

        def replace(src, dst, *a, **k):
            if os.path.normcase(src) == c and dst.endswith(".bak"):
                raise PermissionError("c.md is held open")
            return real_replace(src, dst, *a, **k)
        with mock.patch.object(filesproto.textio, "_replace_with_retry", side_effect=replace):
            with self.assertRaises(filesproto.WriteError):
                filesproto.write_file_blocks(dict((n, "NEW %s\n" % n) for n in NAMES), self.root, ["*.md"])
        self.assertEqual(self.texts(), ["OLD a.md\n", "OLD b.md\n", "OLD c.md\n"])
        self.assertEqual(sorted(os.listdir(self.root)), list(NAMES))


if __name__ == "__main__":
    unittest.main()
