"""Unit tests for ublib.textio (KIT_SPEC 3.1, 4.8)."""

import json
import os
import re
import shutil
import sys
import tempfile
import unittest
from unittest import mock

_KIT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_SCRIPTS = os.path.join(_KIT, "skills", "ultimate-brainstorm", "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

from ublib import textio  # noqa: E402


class TmpDirCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ub-textio-")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def path(self, *parts):
        return os.path.join(self.tmp, *parts)

    def put(self, name, data):
        p = self.path(name)
        with open(p, "wb") as f:
            f.write(data)
        return p


class ReadTextTests(TmpDirCase):
    SAMPLE = "Caf\u00e9 line one\nline two \u2713\n"

    def test_utf8_plain(self):
        self.assertEqual(textio.read_text(self.put("a.txt", self.SAMPLE.encode("utf-8"))), self.SAMPLE)

    def test_utf8_bom(self):
        p = self.put("a.txt", b"\xef\xbb\xbf" + self.SAMPLE.encode("utf-8"))
        self.assertEqual(textio.read_text(p), self.SAMPLE)

    def test_utf16_le_bom(self):
        self.assertEqual(textio.read_text(self.put("a.txt", self.SAMPLE.encode("utf-16"))), self.SAMPLE)

    def test_utf16_be_bom(self):
        p = self.put("a.txt", b"\xfe\xff" + self.SAMPLE.encode("utf-16-be"))
        self.assertEqual(textio.read_text(p), self.SAMPLE)

    def test_utf16_le_without_bom(self):
        text = "{\"a\": 1, \"b\": \"plain ascii words here\"}\n"
        self.assertEqual(textio.read_text(self.put("a.json", text.encode("utf-16-le"))), text)

    def test_crlf_normalized(self):
        p = self.put("a.txt", b"one\r\ntwo\rthree\n")
        self.assertEqual(textio.read_text(p), "one\ntwo\nthree\n")
        self.assertEqual(textio.read_text(p, normalize=False), "one\r\ntwo\rthree\n")

    def test_invalid_utf8_is_replaced(self):
        text = textio.read_text(self.put("a.txt", b"ok \xff\xfe? no: \x80 end"))
        self.assertIn("ok", text)
        self.assertIn("end", text)
        self.assertIn("\ufffd", text)

    def test_powershell_utf16_json_parses(self):
        p = self.put("a.json", json.dumps({"k": "v\u00e9"}).encode("utf-16"))
        self.assertEqual(textio.read_json(p), {"k": "v\u00e9"})

    def test_missing_file_raises(self):
        with self.assertRaises(OSError):
            textio.read_text(self.path("nope.txt"))

    def test_decode_bytes_none_and_empty(self):
        self.assertEqual(textio.decode_bytes(None), "")
        self.assertEqual(textio.decode_bytes(b""), "")


class WriteTests(TmpDirCase):
    def test_write_text_atomic_creates_parents_utf8_lf_no_bom(self):
        p = self.path("a", "b", "c.md")
        textio.write_text_atomic(p, "\ufeffx\r\ny \u00e9\rz")
        with open(p, "rb") as f:
            raw = f.read()
        self.assertEqual(raw, "x\ny \u00e9\nz".encode("utf-8"))

    def test_overwrite_and_no_temp_left(self):
        p = self.path("f.txt")
        textio.write_text_atomic(p, "one")
        textio.write_text_atomic(p, "two")
        self.assertEqual(textio.read_text(p), "two")
        self.assertEqual(os.listdir(self.tmp), ["f.txt"])

    def test_failed_replace_keeps_old_content_and_cleans_temp(self):
        p = self.path("f.txt")
        textio.write_text_atomic(p, "old")
        with mock.patch.object(textio.os, "replace", side_effect=OSError("boom")):
            with self.assertRaises(OSError):
                textio.write_text_atomic(p, "new")
        self.assertEqual(textio.read_text(p), "old")
        self.assertEqual(os.listdir(self.tmp), ["f.txt"])

    def test_transient_permission_error_is_retried(self):
        p = self.path("f.txt")
        real = os.replace
        calls = {"n": 0}

        def flaky(src, dst):
            calls["n"] += 1
            if calls["n"] < 3:
                raise PermissionError("locked")
            return real(src, dst)

        with mock.patch.object(textio.os, "replace", side_effect=flaky), \
                mock.patch.object(textio.time, "sleep"):
            textio.write_text_atomic(p, "data")
        self.assertEqual(textio.read_text(p), "data")
        self.assertEqual(calls["n"], 3)

    def test_write_text_rejects_bytes(self):
        with self.assertRaises(TypeError):
            textio.write_text_atomic(self.path("x"), b"bytes")

    def test_write_json_atomic_format(self):
        p = self.path("j.json")
        textio.write_json_atomic(p, {"a": [1, 2], "b": "\u00e9"})
        with open(p, "rb") as f:
            raw = f.read().decode("utf-8")
        self.assertEqual(raw, json.dumps({"a": [1, 2], "b": "\u00e9"}, indent=1, ensure_ascii=False) + "\n")
        self.assertIn("\u00e9", raw)
        self.assertTrue(raw.endswith("}\n"))

    def test_append_line(self):
        p = self.path("logs", "calls.jsonl")
        textio.append_line(p, '{"a":1}')
        textio.append_line(p, '{"b":2}\n')
        with open(p, "rb") as f:
            self.assertEqual(f.read(), b'{"a":1}\n{"b":2}\n')


class ExtractJsonTests(unittest.TestCase):
    def test_plain_object(self):
        self.assertEqual(textio.extract_json('{"a": 1}'), {"a": 1})

    def test_plain_array(self):
        self.assertEqual(textio.extract_json(' [1, {"b": 2}] '), [1, {"b": 2}])

    def test_fenced_json(self):
        text = "Here you go:\n\n```json\n{\"a\": [1, 2]}\n```\nThanks."
        self.assertEqual(textio.extract_json(text), {"a": [1, 2]})

    def test_fenced_unlabeled(self):
        self.assertEqual(textio.extract_json("```\n{\"x\": true}\n```"), {"x": True})

    def test_json_fence_preferred_over_other_fence(self):
        text = "```python\nprint({'a': 1})\n```\n```json\n{\"real\": 1}\n```"
        self.assertEqual(textio.extract_json(text), {"real": 1})

    def test_preamble_and_trailer(self):
        text = 'Sure! The result is {"scores": [{"id": "I-1", "s": 3}]} and that is all.'
        self.assertEqual(textio.extract_json(text), {"scores": [{"id": "I-1", "s": 3}]})

    def test_prose_braces_then_object(self):
        text = "Use {placeholders} carefully [see note]. Output:\n{\"ok\": 1, \"list\": [1, 2, 3]}"
        self.assertEqual(textio.extract_json(text), {"ok": 1, "list": [1, 2, 3]})

    def test_longest_candidate_wins(self):
        text = 'small [1] then {"big": {"nested": [1, 2, 3]}, "k": "v"}'
        self.assertEqual(textio.extract_json(text), {"big": {"nested": [1, 2, 3]}, "k": "v"})

    def test_bom_and_bytes(self):
        self.assertEqual(textio.extract_json("\ufeff{\"a\": 1}"), {"a": 1})
        self.assertEqual(textio.extract_json('{"a": 2}'.encode("utf-16")), {"a": 2})

    def test_none_found_raises(self):
        for bad in ("", "   ", "no json here", "{broken: json", "42", '"just a string"', None):
            with self.assertRaises(ValueError, msg=repr(bad)):
                textio.extract_json(bad)

    def test_fenced_blocks_helper(self):
        blocks = textio.fenced_blocks("a\n```mermaid\nflowchart LR\n```\n~~~json\n{}\n~~~\n")
        self.assertEqual(blocks, [("mermaid", "flowchart LR\n"), ("json", "{}\n")])


class HashAndMiscTests(TmpDirCase):
    def test_sha256_text_and_file_agree(self):
        text = "hello \u00e9\n"
        p = self.put("h.txt", text.encode("utf-8"))
        self.assertEqual(textio.sha256_text(text), textio.sha256_file(p))
        self.assertEqual(textio.sha256_text(""), "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855")

    def test_is_ascii(self):
        self.assertTrue(textio.is_ascii("plain ASCII ~!@#\n\t"))
        self.assertTrue(textio.is_ascii(""))
        self.assertFalse(textio.is_ascii("caf\u00e9"))
        self.assertFalse(textio.is_ascii("dash \u2014"))

    def test_now_iso(self):
        self.assertRegex(textio.now_iso(), r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

    def test_to_posix(self):
        out = textio.to_posix(self.tmp)
        self.assertNotIn("\\", out)
        self.assertTrue(os.path.isabs(out.replace("/", os.sep)))


if __name__ == "__main__":
    unittest.main()
