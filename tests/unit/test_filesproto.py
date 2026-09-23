"""Unit tests for ublib.filesproto (KIT_SPEC 4.6)."""

import json
import os
import shutil
import sys
import tempfile
import unittest

_KIT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_SCRIPTS = os.path.join(_KIT, "skills", "ultimate-brainstorm", "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

from ublib import filesproto  # noqa: E402
from ublib.filesproto import PathError, check_relpath, glob_match, parse_file_blocks  # noqa: E402

GOOD = """Some preamble the model wrote.
=== FILE: chosen/containers.md ===
# Containers
| C-1 | api |
=== END FILE ===
chatter between blocks is ignored
=== FILE: chosen/runtime.md ===
# Runtime

## F-1 failure and recovery
=== END FILE ===
=== STATUS ===
{"status":"complete","assumptions":["a1"],"open_questions":[],"reason":""}
=== END STATUS ===
trailing words
"""


class ParseTests(unittest.TestCase):
    def test_parse_good(self):
        files, status, warnings = parse_file_blocks(GOOD)
        self.assertEqual(list(files), ["chosen/containers.md", "chosen/runtime.md"])
        self.assertEqual(files["chosen/containers.md"], "# Containers\n| C-1 | api |\n")
        self.assertEqual(files["chosen/runtime.md"], "# Runtime\n\n## F-1 failure and recovery\n")
        self.assertEqual(status["status"], "complete")
        self.assertEqual(status["assumptions"], ["a1"])
        self.assertEqual(warnings, [])

    def test_crlf_input(self):
        files, status, _ = parse_file_blocks(GOOD.replace("\n", "\r\n"))
        self.assertEqual(files["chosen/containers.md"], "# Containers\n| C-1 | api |\n")
        self.assertEqual(status["status"], "complete")

    def test_duplicate_last_wins_with_warning(self):
        text = "=== FILE: a.md ===\nfirst\n=== END FILE ===\n=== FILE: a.md ===\nsecond\n=== END FILE ===\n"
        files, _, warnings = parse_file_blocks(text)
        self.assertEqual(files, {"a.md": "second\n"})
        self.assertTrue(any("duplicate" in w for w in warnings))

    def test_unterminated_block(self):
        text = "=== FILE: a.md ===\none\n=== FILE: b.md ===\ntwo\n"
        files, status, warnings = parse_file_blocks(text)
        self.assertEqual(files, {"a.md": "one\n", "b.md": "two\n"})
        self.assertIsNone(status)
        self.assertEqual(len(warnings), 2)

    def test_status_missing_and_bad(self):
        self.assertIsNone(parse_file_blocks("=== FILE: a.md ===\nx\n=== END FILE ===\n")[1])
        _, status, warnings = parse_file_blocks("=== STATUS ===\nnot json\n=== END STATUS ===\n")
        self.assertIsNone(status)
        self.assertTrue(any("not a JSON object" in w for w in warnings))
        _, status, warnings = parse_file_blocks("=== STATUS ===\n{\"status\":\"done\"}\n=== END STATUS ===\n")
        self.assertEqual(status, {"status": "done"})
        self.assertTrue(any("not one of" in w for w in warnings))

    def test_status_fenced_json_tolerated(self):
        text = "=== STATUS ===\n```json\n{\"status\":\"partial\",\"reason\":\"r\"}\n```\n=== END STATUS ===\n"
        self.assertEqual(parse_file_blocks(text)[1]["status"], "partial")

    def test_empty_and_none(self):
        self.assertEqual(parse_file_blocks(""), ({}, None, []))
        self.assertEqual(parse_file_blocks(None), ({}, None, []))


class PathGuardTests(unittest.TestCase):
    ALLOWED = ["chosen/*.md", "chosen/api/*", "adr/*.md", "**/*.mmd"]

    def test_accepts(self):
        for p in ("chosen/a.md", "chosen/api/openapi.yaml", "chosen/api/x.json", "adr/0001-x.md", "deep/er/d.mmd",
                  "d.mmd"):
            self.assertEqual(check_relpath(p, self.ALLOWED), p)

    def test_rejects(self):
        bad = ["../x.md", "chosen/../../x.md", "/etc/x.md", "C:/x.md", "c:x.md", "chosen\\a.md", ".hidden.md",
               "chosen/.x.md", ".git/config.md", "chosen//a.md", "chosen/a.txt", "chosen/a", "chosen/a.py",
               "chosen/sub/a.md", "other/a.md", "", "   ", "chosen/a?.md", "chosen/con.md", "chosen/a .md/b.md",
               "chosen/a\x01.md"]
        for p in bad:
            with self.assertRaises(PathError, msg=repr(p)):
                check_relpath(p, self.ALLOWED)

    def test_no_globs_means_extension_rules_only(self):
        self.assertEqual(check_relpath("any/where/x.yml", None), "any/where/x.yml")
        with self.assertRaises(PathError):
            check_relpath("any/x.exe", None)
        with self.assertRaises(PathError):
            check_relpath("x.md", [])

    def test_extension_case_insensitive(self):
        self.assertEqual(check_relpath("chosen/A.MD", ["chosen/*"]), "chosen/A.MD")

    def test_glob_semantics(self):
        self.assertTrue(glob_match("chosen/a.md", "chosen/*.md"))
        self.assertFalse(glob_match("chosen/x/a.md", "chosen/*.md"))
        self.assertTrue(glob_match("chosen/x/a.md", "chosen/**/*.md"))
        self.assertTrue(glob_match("chosen/a.md", "chosen/**/*.md"))
        self.assertTrue(glob_match("a/b/c.md", "**"))
        self.assertTrue(glob_match("sections/01.md", "sections/0?.md"))
        self.assertFalse(glob_match("sections/011.md", "sections/0?.md"))
        self.assertTrue(glob_match("adr/0001-a.md", "adr/[0-9]*.md"))
        self.assertFalse(glob_match("Chosen/a.md", "chosen/*.md"))


class WriteTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ub-files-")
        self.root = os.path.join(self.tmp, "10_ARCHITECTURE")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_write_good(self):
        files, _, _ = parse_file_blocks(GOOD)
        written = filesproto.write_file_blocks(files, self.root, ["chosen/*.md"])
        self.assertEqual(len(written), 2)
        for p in written:
            self.assertTrue(os.path.isabs(p))
            self.assertTrue(os.path.isfile(p))
        with open(os.path.join(self.root, "chosen", "containers.md"), "rb") as f:
            self.assertEqual(f.read(), b"# Containers\n| C-1 | api |\n")

    def test_nothing_written_when_any_path_invalid(self):
        files = {"chosen/a.md": "ok\n", "../escape.md": "bad\n"}
        with self.assertRaises(PathError):
            filesproto.write_file_blocks(files, self.root, ["chosen/*.md", "*.md"])
        self.assertFalse(os.path.exists(self.root))
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "escape.md")))

    def test_nothing_written_when_content_empty(self):
        with self.assertRaises(PathError) as cm:
            filesproto.write_file_blocks({"chosen/a.md": "ok", "chosen/b.md": "  \n"}, self.root, ["chosen/*"])
        self.assertIn("empty", str(cm.exception))
        self.assertFalse(os.path.exists(self.root))

    def test_disallowed_by_glob(self):
        with self.assertRaises(PathError):
            filesproto.write_file_blocks({"other/a.md": "x"}, self.root, ["chosen/*.md"])

    def test_trailing_newline_added(self):
        filesproto.write_file_blocks({"a.md": "no newline"}, self.root, ["*.md"])
        with open(os.path.join(self.root, "a.md"), "rb") as f:
            self.assertEqual(f.read(), b"no newline\n")

    def test_split_output_ok_with_status(self):
        status_out = os.path.join(self.tmp, "_raw", "12.9a.status.json")
        res = filesproto.split_output(GOOD, self.root, ["chosen/*.md"], status_out=status_out,
                                      required=["chosen/containers.md"], status_required=True)
        self.assertTrue(res["ok"], res)
        self.assertEqual(len(res["written"]), 2)
        with open(status_out, encoding="utf-8") as f:
            self.assertEqual(json.load(f)["status"], "complete")

    def test_split_output_missing_required_writes_nothing(self):
        res = filesproto.split_output(GOOD, self.root, ["chosen/*.md"], required=["chosen/stack.md"])
        self.assertFalse(res["ok"])
        self.assertIn("chosen/stack.md: required file missing", res["errors"])
        self.assertFalse(os.path.exists(self.root))

    def test_split_output_status_required(self):
        text = "=== FILE: a.md ===\nx\n=== END FILE ===\n"
        res = filesproto.split_output(text, self.root, ["*.md"], status_required=True)
        self.assertFalse(res["ok"])
        res = filesproto.split_output(text, self.root, ["*.md"])
        self.assertTrue(res["ok"])

    def test_split_output_rejects_unterminated_block(self):
        text = "\n".join(["=== FILE: a.md ===", "complete", "=== END FILE ===", "=== FILE: b.md ===",
                          "truncated mid-sent"])
        res = filesproto.split_output(text, self.root, ["*.md"])
        self.assertFalse(res["ok"])
        self.assertIn("FILE block b.md has no END FILE marker", res["errors"])
        self.assertFalse(os.path.exists(self.root))

    def test_structural_errors(self):
        self.assertEqual(filesproto.structural_errors(["duplicate FILE block a.md: the last copy wins"]), [])
        self.assertEqual(len(filesproto.structural_errors(["FILE block x.md has no END FILE marker"])), 1)

    def test_no_blocks(self):
        res = filesproto.split_output("just prose", self.root, ["*.md"])
        self.assertFalse(res["ok"])
        self.assertIn("no FILE blocks found", res["errors"])


if __name__ == "__main__":
    unittest.main()
