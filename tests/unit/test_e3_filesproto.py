"""Phase E3, the FILE protocol (KIT_SPEC 4.6): an END FILE line while no FILE block is open is structural wherever
it stands (finding 40), a failed commit stays undone when a concurrent recover() takes its journal the moment it is
unlocked (review note P3-validation-privacy-0), and every split temp is fsynced before its rename (finding 4)."""

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


class FramingTests(unittest.TestCase):
    def test_a_quoted_status_block_does_not_hide_the_cut(self):
        # finding 40 (a): the quoted END FILE closed sections/02.md, the quoted STATUS reset the check, and the real
        # END FILE was dropped as an orphan: the file was silently cut short
        out = ("=== FILE: sections/02.md ===\n## 2. P\nClose each file with:\n=== END FILE ===\nThen the trailer:\n"
               "=== STATUS ===\n{\"status\":\"complete\"}\n=== END STATUS ===\nSecond half of the section.\n"
               "=== END FILE ===\n=== STATUS ===\n{\"status\":\"complete\"}\n=== END STATUS ===\n")
        files, _status, warnings = filesproto.parse_file_blocks(out)
        errors = filesproto.structural_errors(warnings)
        self.assertTrue(any("FILE block sections/02.md: an '=== END FILE ===' line inside its content cut it short"
                            in e for e in errors), warnings)
        root = tempfile.mkdtemp(prefix="ub-e3-fp-")
        self.addCleanup(shutil.rmtree, root, True)
        res = filesproto.split_output(out, root, ["sections/*.md"])
        self.assertFalse(res["ok"])
        self.assertEqual(os.listdir(root), [])

    def test_an_end_file_line_after_chatter_or_before_any_block(self):
        after_chatter = "=== FILE: a.md ===\nx\n=== END FILE ===\nsome words\n=== END FILE ===\n"
        self.assertTrue(filesproto.structural_errors(filesproto.parse_file_blocks(after_chatter)[2]))
        before_any = "=== END FILE ===\n=== FILE: a.md ===\nx\n=== END FILE ===\n"
        errs = filesproto.structural_errors(filesproto.parse_file_blocks(before_any)[2])
        self.assertEqual(errs, ["an '=== END FILE ===' line outside any FILE block (ambiguous framing)"])
        clean = "intro\n=== FILE: a.md ===\nx\n=== END FILE ===\nbetween\n=== FILE: b.md ===\ny\n=== END FILE ===\n"
        self.assertEqual(filesproto.parse_file_blocks(clean)[2], [])


class CommitTests(unittest.TestCase):
    def setUp(self):
        self.root = os.path.realpath(tempfile.mkdtemp(prefix="ub-e3-commit-"))
        self.addCleanup(shutil.rmtree, self.root, True)
        for name in ("a.md", "b.md"):
            textio.write_text_atomic(os.path.join(self.root, name), "OLD %s\n" % name)

    def read(self, name):
        return textio.read_text(os.path.join(self.root, name))

    def test_a_recover_in_the_abort_window_finds_nothing_to_roll_forward(self):
        # P3 review note: the abort path unlocked and deleted the journal before removing the temps; a recover() that
        # locked the journal in between rolled the failed commit forward (the caller got WriteError, the disk had
        # the new files)
        b = os.path.join(self.root, "b.md")
        real_replace = textio._replace_with_retry

        def replace(src, dst, *a, **k):
            if os.path.normcase(src) == os.path.normcase(b) and dst.endswith(".bak"):
                raise PermissionError("b.md is held open")
            return real_replace(src, dst, *a, **k)
        real_unlock = textio.unlock_fd
        finished = []

        def unlock(fd):
            real_unlock(fd)
            if not finished:  # the window: the journal is unlocked and still on disk (recover's own unlock skips)
                finished.append(None)
                finished[0] = filesproto.recover(self.root)
        with mock.patch.object(filesproto.textio, "_replace_with_retry", side_effect=replace), \
                mock.patch.object(filesproto.textio, "unlock_fd", side_effect=unlock):
            with self.assertRaises(filesproto.WriteError):
                filesproto.write_file_blocks({"a.md": "NEW a\n", "b.md": "NEW b\n"}, self.root, ["*.md"])
        self.assertEqual(len(finished), 1)  # recover() ran in the window (it finds the journal and no temps)
        self.assertEqual((self.read("a.md"), self.read("b.md")), ("OLD a.md\n", "OLD b.md\n"))
        self.assertEqual(sorted(os.listdir(self.root)), ["a.md", "b.md"])

    def test_every_temp_is_fsynced_before_its_rename(self):
        # finding 4 (b): counting fsync calls could not tell a missing temp fsync on POSIX (the folder and journal
        # fsyncs made up the count); this follows each temp file from its creation to its rename
        paths, synced, order = {}, set(), []
        real_mkstemp, real_fsync, real_replace = filesproto.tempfile.mkstemp, os.fsync, textio._replace_with_retry

        def mkstemp(*a, **k):
            fd, path = real_mkstemp(*a, **k)
            paths[fd] = os.path.normcase(path)
            return fd, path

        def fsync(fd):
            if fd in paths:
                synced.add(paths[fd])
            return real_fsync(fd)

        def replace(src, dst, *a, **k):
            if src.endswith(".tmp"):
                order.append((os.path.normcase(src), os.path.normcase(src) in synced))
            return real_replace(src, dst, *a, **k)
        with mock.patch.object(filesproto.tempfile, "mkstemp", side_effect=mkstemp), \
                mock.patch.object(filesproto.os, "fsync", side_effect=fsync), \
                mock.patch.object(filesproto.textio, "_replace_with_retry", side_effect=replace):
            filesproto.write_file_blocks({"a.md": "NEW a\n", "sub/c.md": "NEW c\n"}, self.root, ["*.md", "sub/*.md"])
        self.assertEqual(len(order), 2)
        self.assertTrue(all(ok for _p, ok in order), order)


if __name__ == "__main__":
    unittest.main()
