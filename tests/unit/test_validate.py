"""Unit tests for ublib.validate: every contract type, positive and negative, and the repair prompt (KIT_SPEC 4.5)."""

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

from ublib import validate  # noqa: E402
from ublib.validate import check_contract  # noqa: E402

SCORES_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["scores"],
                 "properties": {"scores": {"type": "array", "items": {
                     "type": "object", "additionalProperties": False, "required": ["id", "score"],
                     "properties": {"id": {"type": "string"}, "score": {"type": "integer"}}}}}}


class RunDirCase(unittest.TestCase):
    def setUp(self):
        self.run = tempfile.mkdtemp(prefix="ub-validate-")

    def tearDown(self):
        shutil.rmtree(self.run, ignore_errors=True)

    def write_json(self, rel, obj):
        p = os.path.join(self.run, *rel.split("/"))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(obj, f)
        return p


class GeneralTests(RunDirCase):
    def test_return_shape(self):
        res = check_contract("hello world, this is long enough", {"type": "text"}, self.run)
        self.assertIsInstance(res, tuple)
        self.assertEqual(len(res), 3)
        self.assertTrue(res[0])
        self.assertEqual(res[1], [])

    def test_unknown_type(self):
        ok, errors, parsed = check_contract("x" * 50, {"type": "weird"}, self.run)
        self.assertFalse(ok)
        self.assertIn("unknown contract type", errors[0])
        self.assertIsNone(parsed)

    def test_empty_output(self):
        for ctype in validate.CONTRACT_TYPES:
            ok, errors, _ = check_contract("  \n", {"type": ctype}, self.run)
            self.assertFalse(ok, ctype)
            self.assertEqual(errors, ["output is empty"])

    def test_output_cap(self):
        big = "a" * (validate.OUTPUT_CAP_BYTES + 1)
        ok, errors, _ = check_contract(big, {"type": "text"}, self.run)
        self.assertFalse(ok)
        self.assertIn("2 MB", errors[0])

    def test_bytes_input_utf16(self):
        ok, _, _ = check_contract("PONG and some more characters".encode("utf-16"),
                                  {"type": "text", "regex": "PONG"}, self.run)
        self.assertTrue(ok)


class TextTests(RunDirCase):
    def test_min_chars_default_20(self):
        self.assertFalse(check_contract("too short", {"type": "text"}, self.run)[0])
        self.assertTrue(check_contract("x" * 20, {"type": "text"}, self.run)[0])
        self.assertTrue(check_contract("PONG", {"type": "text", "min_chars": 1, "regex": "PONG"}, self.run)[0])

    def test_regex_anywhere(self):
        c = {"type": "text", "regex": "^VERDICT: (BACK|DON'T BACK)$"}
        self.assertTrue(check_contract("Reasoning here.\nVERDICT: BACK\nmore text", c, self.run)[0])
        ok, errors, _ = check_contract("Reasoning without the verdict line at all.", c, self.run)
        self.assertFalse(ok)
        self.assertIn("does not match", errors[0])

    def test_final_line(self):
        c = {"type": "text", "final_line": r"^RESULT: (PENDING|PASSED)$"}
        self.assertTrue(check_contract("Some body text here.\n\nRESULT: PENDING\n\n", c, self.run)[0])
        ok, errors, _ = check_contract("RESULT: PENDING\nbut then more text follows", c, self.run)
        self.assertFalse(ok)
        self.assertIn("final line", errors[0])

    def test_bad_regex_reported(self):
        ok, errors, _ = check_contract("x" * 30, {"type": "text", "regex": "("}, self.run)
        self.assertFalse(ok)
        self.assertIn("invalid contract regex", errors[0])


def idea(n, prefix="S3", missing=None):
    lines = ["### %s-%02d Idea number %d" % (prefix, n, n),
             "- Pitch: one sentence.",
             "- Mechanism: how it works.",
             "- For whom / when: nurses.",
             "- Cell: onboarding / app",
             "- Fails if: nobody cares."]
    if missing:
        lines = [ln for ln in lines if not ln.startswith("- %s:" % missing)]
    return "\n".join(lines)


class IdeaBlockTests(RunDirCase):
    C = {"type": "idea-blocks", "prefix": "S3", "min": 3}

    def test_positive(self):
        text = "Warm-up (not counted): a, b, c\n\n" + "\n\n".join(idea(i) for i in range(1, 4))
        ok, errors, parsed = check_contract(text, self.C, self.run)
        self.assertTrue(ok, errors)
        self.assertEqual([b["id"] for b in parsed], ["S3-01", "S3-02", "S3-03"])
        self.assertEqual(parsed[0]["title"], "Idea number 1")

    def test_too_few(self):
        ok, errors, _ = check_contract("\n\n".join(idea(i) for i in range(1, 3)), self.C, self.run)
        self.assertFalse(ok)
        self.assertIn("found 2 valid S3-NN idea blocks, need at least 3", errors[0])

    def test_missing_line_does_not_count(self):
        text = "\n\n".join([idea(1), idea(2), idea(3, missing="Fails if")])
        ok, errors, parsed = check_contract(text, self.C, self.run)
        self.assertFalse(ok)
        self.assertTrue(any("S3-03 lacks - Fails if:" in e for e in errors), errors)
        self.assertEqual(len(parsed), 2)

    def test_wrong_prefix_ignored(self):
        text = "\n\n".join(idea(i, prefix="S2") for i in range(1, 5))
        self.assertFalse(check_contract(text, self.C, self.run)[0])

    def test_duplicates_count_once(self):
        text = "\n\n".join([idea(1), idea(1), idea(2)])
        ok, errors, _ = check_contract(text, self.C, self.run)
        self.assertFalse(ok)
        self.assertTrue(any("more than once" in e for e in errors))

    def test_other_heading_ends_block(self):
        text = "\n\n".join([idea(1), idea(2), "### S3-03 Third\n- Pitch: p\n## Notes\n- Mechanism: m\n- Fails if: f"])
        ok, _, parsed = check_contract(text, self.C, self.run)
        self.assertFalse(ok)
        self.assertEqual(len(parsed), 2)

    def test_prefix_is_escaped(self):
        c = {"type": "idea-blocks", "prefix": "H.P", "min": 1}
        self.assertFalse(check_contract(idea(1, prefix="HXP"), c, self.run)[0])
        self.assertTrue(check_contract(idea(1, prefix="H.P"), c, self.run)[0])


class JsonTests(RunDirCase):
    def test_inline_schema_and_fence(self):
        text = "Result:\n```json\n{\"scores\": [{\"id\": \"I-1\", \"score\": 3}]}\n```"
        ok, errors, parsed = check_contract(text, {"type": "json", "schema": SCORES_SCHEMA}, self.run)
        self.assertTrue(ok, errors)
        self.assertEqual(parsed["scores"][0]["id"], "I-1")

    def test_run_relative_schema(self):
        self.write_json("screen/scores.schema.json", SCORES_SCHEMA)
        c = {"type": "json", "schema": "screen/scores.schema.json"}
        self.assertTrue(check_contract('{"scores": []}', c, self.run)[0])
        ok, errors, parsed = check_contract('{"scores": [{"id": 1, "score": 3}]}', c, self.run)
        self.assertFalse(ok)
        self.assertIn("$.scores[0].id: expected string", errors[0])
        self.assertIsNotNone(parsed)

    def test_sk_schema_reference(self):
        sk = tempfile.mkdtemp(prefix="ub-sk-")
        try:
            p = os.path.join(sk, "templates", "schemas")
            os.makedirs(p)
            with open(os.path.join(p, "scores.schema.json"), "w", encoding="utf-8") as f:
                json.dump(SCORES_SCHEMA, f)
            with mock.patch.object(validate, "SK_DIR", sk):
                c = {"type": "json", "schema": "SK:templates/schemas/scores.schema.json"}
                self.assertTrue(check_contract('{"scores": []}', c, self.run)[0])
                self.assertFalse(check_contract('{"scores": [], "x": 1}', c, self.run)[0])
        finally:
            shutil.rmtree(sk, ignore_errors=True)

    def test_missing_schema(self):
        ok, errors, _ = check_contract('{"a": 1}', {"type": "json", "schema": "nope.json"}, self.run)
        self.assertFalse(ok)
        self.assertIn("schema not found", errors[0])

    def test_no_json(self):
        ok, errors, parsed = check_contract("I cannot comply with that.", {"type": "json"}, self.run)
        self.assertFalse(ok)
        self.assertIn("no valid JSON", errors[0])
        self.assertIsNone(parsed)

    def test_cover(self):
        c = {"type": "json", "schema": SCORES_SCHEMA,
             "cover": {"array": "scores", "key": "id", "ids": ["I-1", "I-2", "I-3"]}}
        full = {"scores": [{"id": i, "score": 3} for i in ("I-1", "I-2", "I-3")]}
        self.assertTrue(check_contract(json.dumps(full), c, self.run)[0])
        partial = {"scores": [{"id": "I-1", "score": 3}]}
        ok, errors, _ = check_contract(json.dumps(partial), c, self.run)
        self.assertFalse(ok)
        self.assertEqual(errors, ["cover: scores is missing id I-2, I-3"])

    def test_cover_array_not_list(self):
        c = {"type": "json", "cover": {"array": "pairs", "key": "pair", "ids": ["P1"]}}
        ok, errors, _ = check_contract('{"pairs": {}}', c, self.run)
        self.assertFalse(ok)
        self.assertIn("is not an array", errors[0])


PROPOSAL = """# Proposal

## 1. Executive Summary
Short summary with five words.

## 2. Problem and Evidence
Evidence here [S-001].

### 2.1 Detail
Nested detail stays in section 2.

## 3. Solution
The solution.

```json
{"verdict": "ok", "n": 2}
```
FINAL: READY
"""


class SectionsTests(RunDirCase):
    def test_positive_with_tail_and_final_line(self):
        c = {"type": "sections",
             "headings": ["## 1. Executive Summary", "## 2. Problem", "## 3. solution"],
             "final_line": "^FINAL: (READY|DRAFT)$",
             "json_tail": {"type": "object", "required": ["verdict"], "properties": {"verdict": {"enum": ["ok"]}}},
             "max_words": {"## 1. Executive Summary": 10}}
        ok, errors, parsed = check_contract(PROPOSAL, c, self.run)
        self.assertTrue(ok, errors)
        self.assertEqual(parsed["json_tail"], {"verdict": "ok", "n": 2})
        self.assertEqual(parsed["final_line"], "FINAL: READY")
        self.assertIn("Nested detail", parsed["sections"]["## 2. Problem"])

    def test_final_line_after_tail_or_before(self):
        c = {"type": "sections", "headings": ["## 1."], "final_line": "^FINAL:", "json_tail": True}
        text = "## 1. A\nbody\nFINAL: yes\n```json\n{\"a\": 1}\n```\n"
        self.assertTrue(check_contract(text, c, self.run)[0])

    def test_missing_and_out_of_order(self):
        c = {"type": "sections", "headings": ["## 1. Executive Summary", "## 3. Solution", "## 2. Problem",
                                              "## 9. Nope"]}
        ok, errors, _ = check_contract(PROPOSAL, c, self.run)
        self.assertFalse(ok)
        self.assertIn("heading '## 2. Problem' is out of order", errors)
        self.assertIn("heading '## 9. Nope' is missing", errors)

    def test_headings_inside_fences_ignored(self):
        text = "```\n## 1. Executive Summary\n```\nno real heading here at all"
        self.assertFalse(check_contract(text, {"type": "sections", "headings": ["## 1."]}, self.run)[0])

    def test_word_cap(self):
        c = {"type": "sections", "headings": ["## 1."], "max_words": {"## 1. Executive Summary": 3}}
        ok, errors, _ = check_contract(PROPOSAL, c, self.run)
        self.assertFalse(ok)
        self.assertIn("has 5 words, more than 3", errors[0])

    def test_json_tail_missing_or_invalid(self):
        c = {"type": "sections", "headings": ["## 1."], "json_tail": {"type": "object", "required": ["x"]}}
        ok, errors, _ = check_contract("## 1. A\nbody text\n", c, self.run)
        self.assertFalse(ok)
        self.assertIn("no fenced ```json tail block found", errors)
        ok, errors, _ = check_contract(PROPOSAL, c, self.run)
        self.assertFalse(ok)
        self.assertIn("json tail $: missing required property \"x\"", errors)
        ok, errors, _ = check_contract("## 1. A\n```json\n{bad\n```\n", c, self.run)
        self.assertFalse(ok)
        self.assertIn("not valid JSON", errors[0])

    def test_last_json_block_is_the_tail(self):
        text = "## 1. A\n```json\n{\"first\": 1}\n```\ntext\n```json\n{\"x\": 2}\n```\n"
        c = {"type": "sections", "headings": ["## 1."], "json_tail": {"type": "object", "required": ["x"]}}
        ok, errors, parsed = check_contract(text, c, self.run)
        self.assertTrue(ok, errors)
        self.assertEqual(parsed["json_tail"], {"x": 2})

    def test_final_line_negative(self):
        c = {"type": "sections", "headings": ["## 1."], "final_line": "^WHOLE-EFFORT: (CONTINUE|STOP)$"}
        ok, errors, _ = check_contract(PROPOSAL, c, self.run)
        self.assertFalse(ok)
        self.assertIn("final line", errors[0])


CARDS = """# Cards

## I-1
Title: Night nurse buddy
Pitch: A pitch.
Prior art: NOT CHECKED

## I-2: Second
Title: Other
Pitch: Another.
Prior art: ADJACENT
"""


class CardsTests(RunDirCase):
    C = {"type": "cards", "ids": ["I-1", "I-2"], "lines": ["Title:", "Pitch:", "Prior art:"]}

    def test_positive(self):
        ok, errors, parsed = check_contract(CARDS, self.C, self.run)
        self.assertTrue(ok, errors)
        self.assertEqual(parsed["I-1"]["Title:"], "Night nurse buddy")
        self.assertEqual(parsed["I-2"]["Prior art:"], "ADJACENT")

    def test_missing_card_and_line(self):
        c = dict(self.C, ids=["I-1", "I-2", "I-3"], lines=["Title:", "Mechanism:"])
        ok, errors, _ = check_contract(CARDS, c, self.run)
        self.assertFalse(ok)
        self.assertIn("card ## I-3 is missing", errors)
        self.assertIn("card I-1 lacks lines: Mechanism:", errors)

    def test_id_prefix_is_not_confused(self):
        text = CARDS.replace("## I-1\n", "## I-10\n")
        ok, errors, _ = check_contract(text, self.C, self.run)
        self.assertFalse(ok)
        self.assertIn("card ## I-1 is missing", errors)

    def test_duplicate_card(self):
        ok, errors, _ = check_contract(CARDS + "\n## I-1\nTitle: t\nPitch: p\nPrior art: x\n", self.C, self.run)
        self.assertFalse(ok)
        self.assertIn("card ## I-1 appears 2 times", errors)


FILES_OUT = """=== FILE: chosen/containers.md ===
# Containers

## How each quality goal is met

```mermaid
C4Container
  title x
```

```mermaid
flowchart LR
  a --> b
```
=== END FILE ===
=== FILE: chosen/runtime.mmd ===
sequenceDiagram
  A->>B: hi
=== END FILE ===
=== STATUS ===
{"status": "complete", "assumptions": [], "open_questions": [], "reason": ""}
=== END STATUS ===
"""


class FilesTests(RunDirCase):
    C = {"type": "files", "allowed": ["chosen/*"], "required": ["chosen/containers.md"],
         "per_file": {"chosen/containers.md": {"headings": ["# Containers", "## How each quality goal"],
                                               "mermaid": ["C4Container", "flowchart"]},
                      "chosen/runtime.mmd": {"mermaid": ["sequenceDiagram"]}},
         "status_trailer": True}

    def test_positive(self):
        ok, errors, parsed = check_contract(FILES_OUT, self.C, self.run)
        self.assertTrue(ok, errors)
        self.assertEqual(sorted(parsed["files"]), ["chosen/containers.md", "chosen/runtime.mmd"])
        self.assertEqual(parsed["status"]["status"], "complete")
        self.assertFalse(os.listdir(self.run), "check_contract must not write files")

    def test_required_missing(self):
        c = dict(self.C, required=["chosen/containers.md", "chosen/stack.md"])
        ok, errors, _ = check_contract(FILES_OUT, c, self.run)
        self.assertFalse(ok)
        self.assertIn("chosen/stack.md: required file missing", errors)

    def test_heading_and_mermaid_missing(self):
        c = dict(self.C, per_file={"chosen/containers.md": {"headings": ["## Data"], "mermaid": ["erDiagram"]}})
        ok, errors, _ = check_contract(FILES_OUT, c, self.run)
        self.assertFalse(ok)
        self.assertIn("chosen/containers.md: heading '## Data' is missing", errors)
        self.assertIn("chosen/containers.md: no mermaid erDiagram block", errors)

    def test_mermaid_type_is_whole_word(self):
        c = dict(self.C, per_file={"chosen/containers.md": {"mermaid": ["C4"]}})
        self.assertFalse(check_contract(FILES_OUT, c, self.run)[0])

    def test_status_trailer(self):
        text = FILES_OUT.split("=== STATUS ===")[0]
        ok, errors, _ = check_contract(text, self.C, self.run)
        self.assertFalse(ok)
        self.assertIn("STATUS trailer is missing or not valid JSON", errors)
        bad = FILES_OUT.replace('"complete"', '"finished"')
        ok, errors, _ = check_contract(bad, self.C, self.run)
        self.assertFalse(ok)
        self.assertTrue(any("STATUS status must be one of" in e for e in errors))
        self.assertTrue(check_contract(text, dict(self.C, status_trailer=False), self.run)[0])

    def test_path_guards(self):
        for bad_path in ("../x.md", "C:/x.md", "chosen/.x.md", "chosen/x.txt", "other/x.md"):
            text = "=== FILE: %s ===\ncontent\n=== END FILE ===\n" % bad_path
            c = {"type": "files", "allowed": ["chosen/*"]}
            self.assertFalse(check_contract(text, c, self.run)[0], bad_path)

    def test_unterminated_block_is_invalid(self):
        text = "=== FILE: chosen/a.md ===" + "\n" + "the model was cut off here"
        ok, errors, _ = check_contract(text, {"type": "files", "allowed": ["chosen/*"]}, self.run)
        self.assertFalse(ok)
        self.assertIn("FILE block chosen/a.md has no END FILE marker", errors)

    def test_empty_file(self):
        text = "=== FILE: chosen/a.md ===\n\n=== END FILE ===\n"
        ok, errors, _ = check_contract(text, {"type": "files", "allowed": ["chosen/*"]}, self.run)
        self.assertFalse(ok)
        self.assertIn("chosen/a.md: content is empty", errors)


class RepairPromptTests(unittest.TestCase):
    def test_exact_text(self):
        p = validate.repair_prompt(["$.a: missing", "cover: x"], "PREVIOUS")
        self.assertEqual(p, "Your previous output failed validation: $.a: missing; cover: x. "
                            "Return only the corrected output.\n\nPREVIOUS")

    def test_error_summary_capped_at_1500(self):
        p = validate.repair_prompt(["e" * 5000], "PREV")
        head = p.split(". Return only the corrected output.")[0]
        summary = head[len("Your previous output failed validation: "):]
        self.assertEqual(len(summary), 1500)
        self.assertTrue(summary.endswith("..."))
        self.assertTrue(p.endswith("\n\nPREV"))

    def test_string_errors_and_none_previous(self):
        p = validate.repair_prompt("single\nerror", None)
        self.assertTrue(p.startswith("Your previous output failed validation: single error. Return only"))


if __name__ == "__main__":
    unittest.main()
