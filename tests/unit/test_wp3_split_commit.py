"""The FILE-protocol write is all-or-nothing, also across a crash (KIT_SPEC 4.6 rule 4; findings #38, #4 and #98 of the
architecture audit): a target another process holds open leaves every target as it was; a process killed in the middle
leaves a journal that the next write (or filesproto.recover) rolls forward; temps are fsynced; temp names are short
and a Windows MAX_PATH failure says so."""

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from unittest import mock

_KIT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_SCRIPTS = os.path.join(_KIT, "skills", "ultimate-brainstorm", "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

from ublib import filesproto, textio  # noqa: E402
from ublib.engine import render_arch  # noqa: E402

NAMES = ["sections/02.md", "sections/03.md", "sections/04.md", "sections/05.md", "review/resolution.md"]
ALLOWED = ["sections/*.md", "review/resolution.md"]


class SplitCase(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix="ub-wp3-split-"))
        self.root = os.path.join(self.tmp, "11_PROPOSAL")
        self.addCleanup(lambda: __import__("shutil").rmtree(self.tmp, True))

    def p(self, rel):
        return os.path.join(self.root, *rel.split("/"))

    def files(self, tag):
        return dict((n, "%s %s\n" % (tag, n)) for n in NAMES)

    def contents(self):
        out = {}
        for n in NAMES:
            try:
                with open(self.p(n), encoding="utf-8") as f:
                    out[n] = f.read().split(" ")[0]
            except FileNotFoundError:
                out[n] = None
        return out

    def leftovers(self):
        found = []
        for dirpath, _dirs, names in os.walk(self.root):
            found += [os.path.relpath(os.path.join(dirpath, n), self.root).replace("\\", "/") for n in names
                      if n.startswith(".")]
        return sorted(found)

    def assertAll(self, tag):
        self.assertEqual(self.contents(), dict((n, tag) for n in NAMES))
        self.assertEqual(self.leftovers(), [])


class AllOrNothing(SplitCase):
    def test_a_held_target_leaves_every_file_old(self):
        filesproto.write_file_blocks(self.files("OLD"), self.root, ALLOWED)
        held = self.p("sections/04.md")
        real = os.replace

        def replace(src, dst):
            if os.path.normcase(held) in (os.path.normcase(src), os.path.normcase(dst)):
                raise PermissionError(13, "held by another process (simulated)", held)
            return real(src, dst)

        with mock.patch("os.replace", side_effect=replace), mock.patch("time.sleep"):
            with self.assertRaises(filesproto.WriteError):
                filesproto.write_file_blocks(self.files("NEW"), self.root, ALLOWED)
        self.assertAll("OLD")
        filesproto.write_file_blocks(self.files("NEW"), self.root, ALLOWED)  # the holder is gone: a retry works
        self.assertAll("NEW")

    @unittest.skipUnless(os.name == "nt", "Windows only: an open file blocks a rename there")
    def test_a_real_open_handle_on_windows(self):
        filesproto.write_file_blocks(self.files("OLD"), self.root, ALLOWED)
        with mock.patch("time.sleep"):
            with open(self.p("sections/04.md"), "rb"):  # Python opens without FILE_SHARE_DELETE
                res = filesproto.split_output("".join("=== FILE: %s ===\nNEW %s\n=== END FILE ===\n" % (n, n)
                                                      for n in NAMES), self.root, ALLOWED)
        self.assertFalse(res["ok"])
        self.assertTrue(res["io_error"])
        self.assertAll("OLD")

    def test_temps_are_fsynced(self):
        with mock.patch("os.fsync", wraps=os.fsync) as fsync:
            filesproto.write_file_blocks(self.files("NEW"), self.root, ALLOWED)
        self.assertGreaterEqual(fsync.call_count, len(NAMES))
        self.assertAll("NEW")


CRASH = textwrap.dedent("""
    import os, sys
    sys.path.insert(0, %(scripts)r)
    from ublib import filesproto
    real, seen = os.replace, {"n": 0}
    def replace(src, dst):
        if %(match)s:
            seen["n"] += 1
            if seen["n"] == 3:
                os._exit(9)  # killed: no finally, no cleanup
        return real(src, dst)
    os.replace = replace
    names = %(names)r
    filesproto.write_file_blocks(dict((n, "NEW %%s\\n" %% n) for n in names), %(root)r, %(allowed)r)
    """)


class CrashInTheMiddle(SplitCase):
    def crash(self, match):
        filesproto.write_file_blocks(self.files("OLD"), self.root, ALLOWED)
        code = CRASH % {"scripts": _SCRIPTS, "names": NAMES, "root": self.root, "allowed": ALLOWED, "match": match}
        rc = subprocess.run([sys.executable, "-c", code], stdout=subprocess.PIPE, stderr=subprocess.PIPE).returncode
        self.assertEqual(rc, 9)
        self.assertEqual(len([n for n in os.listdir(self.root) if n.startswith(filesproto.JOURNAL_PREFIX)]), 1)
        self.assertNotEqual(self.contents(), dict((n, "NEW") for n in NAMES))

    def test_killed_while_renaming_temps_rolls_forward(self):
        self.crash('src.endswith(".tmp")')
        self.assertEqual(filesproto.recover(self.root), 1)
        self.assertAll("NEW")
        self.assertEqual(filesproto.recover(self.root), 0)

    def test_killed_while_moving_targets_aside_rolls_forward(self):
        self.crash('dst.endswith(".bak")')
        self.assertEqual(filesproto.recover(self.root), 1)
        self.assertAll("NEW")

    def test_the_next_write_finishes_the_interrupted_one_first(self):
        self.crash('src.endswith(".tmp")')
        filesproto.write_file_blocks({"sections/06.md": "other job\n"}, self.root, ALLOWED)
        self.assertEqual(self.contents(), dict((n, "NEW") for n in NAMES))
        self.assertEqual(self.leftovers(), [])

    def test_a_live_commit_is_left_alone(self):
        filesproto.write_file_blocks(self.files("OLD"), self.root, ALLOWED)
        target, data = self.p("sections/02.md"), b"NEW sections/02.md\n"
        fd_tmp, tmp = tempfile.mkstemp(prefix=".02.md.", suffix=".tmp", dir=os.path.dirname(target))
        os.write(fd_tmp, data)
        os.close(fd_tmp)
        entry = {"target": "sections/02.md", "tmp": os.path.relpath(tmp, self.root).replace("\\", "/"), "bak": None,
                 "old": textio.sha256_file(target), "new": hashlib.sha256(data).hexdigest()}
        fd, journal = tempfile.mkstemp(prefix=filesproto.JOURNAL_PREFIX, suffix=".json", dir=self.root)
        try:
            if textio.try_lock_fd(fd) is not True:
                self.skipTest("no file locks on this file system")
            os.lseek(fd, 0, 0)
            os.write(fd, json.dumps({"schema": 1, "entries": [entry]}).encode("ascii"))
            self.assertEqual(filesproto.recover(self.root), 0)  # its owner is alive (holds the lock)
            self.assertEqual(self.contents()["sections/02.md"], "OLD")
        finally:
            textio.unlock_fd(fd)
            os.close(fd)
        self.assertEqual(filesproto.recover(self.root), 1)  # the owner died: roll forward
        self.assertEqual(self.contents()["sections/02.md"], "NEW")
        self.assertFalse(os.path.exists(journal))
        self.assertFalse(os.path.exists(tmp))

    def test_a_target_changed_after_the_crash_is_not_overwritten(self):
        self.crash('src.endswith(".tmp")')
        missing = [n for n, v in self.contents().items() if v is None]
        self.assertTrue(missing)
        with open(self.p(NAMES[0]), "w", encoding="utf-8") as f:
            f.write("NEWER by a later job\n")
        filesproto.recover(self.root)
        self.assertEqual(self.contents()[NAMES[0]], "NEWER")
        self.assertTrue(all(self.contents()[n] == "NEW" for n in missing))


class ShortTempNamesAndLongPaths(unittest.TestCase):
    def test_temp_prefix_is_short(self):
        with tempfile.TemporaryDirectory() as d:
            long_name = "judge_claude-alt.out.json.meta.json" + "x" * 30
            with mock.patch("tempfile.mkstemp", wraps=tempfile.mkstemp) as mk:
                textio.write_text_atomic(os.path.join(d, long_name), "x")
                filesproto.write_file_blocks({"review/%s.md" % ("y" * 60): "x"}, d, ["review/*.md"])
            prefixes = [c.kwargs.get("prefix", "") for c in mk.call_args_list]
            self.assertTrue(prefixes)
            self.assertTrue(all(len(p) <= textio.TEMP_PREFIX_CHARS + 2 for p in prefixes), prefixes)
            self.assertEqual(textio.temp_prefix(os.path.join(d, ".ub-published")), "..ub-published.")

    def test_adr_slug_is_capped(self):
        s = render_arch.slug("Authenticate every ward nurse through the hospital identity provider single sign on")
        self.assertLessEqual(len(s), render_arch.SLUG_MAX)
        self.assertFalse(s.endswith("-"))
        self.assertEqual(render_arch.slug("Use Postgres"), "use-postgres")
        self.assertEqual(render_arch.slug("!!!"), "decision")

    @unittest.skipUnless(os.name == "nt", "the MAX_PATH explanation is Windows-only")
    def test_a_path_over_max_path_is_explained(self):
        with tempfile.TemporaryDirectory() as d:
            deep = os.path.join(d, *(["d" * 40] * 7), "x.md")
            with mock.patch("tempfile.mkstemp", side_effect=FileNotFoundError(2, "No such file or directory")), \
                    mock.patch("os.makedirs"), mock.patch.object(textio, "long_paths_enabled", return_value=False):
                with self.assertRaises(textio.PathTooLong) as cm:
                    textio.write_text_atomic(deep, "x")
                self.assertIn("more than the 259 Windows allows", str(cm.exception))
                self.assertIn("--root", str(cm.exception))
                with self.assertRaises(filesproto.WriteError) as cm:
                    filesproto.write_file_blocks({"a/%s.md" % ("z" * 200): "x"}, os.path.join(d, "r" * 60),
                                                 ["a/*.md"])
                self.assertIn("Windows allows without long-path support", str(cm.exception))
        with mock.patch("tempfile.mkstemp", side_effect=FileNotFoundError(2, "No such file or directory")):
            with self.assertRaises(FileNotFoundError) as cm:  # a short path keeps its own error
                textio.write_text_atomic(os.path.join(tempfile.gettempdir(), "short.md"), "x")
            self.assertNotIsInstance(cm.exception, textio.PathTooLong)


if __name__ == "__main__":
    unittest.main()
