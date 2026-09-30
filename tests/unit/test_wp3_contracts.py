"""Contracts reject what the pipeline cannot consume (findings #35, #36, #39, #40, #41, #49 of the architecture audit):
exact-ID covers, bounded scores, strict JSON in FILE blocks with the register schemas, unambiguous FILE framing,
canonical paths, one idea-block parser for the contract and its consumers, and a JSON reader that never mines a
malformed document for a fragment. Includes the REPORT 6.1 poison pills that touch the validator."""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fixtures", "engine"))
import engine_testlib as tl  # noqa: E402

from ublib import filesproto, schema_lite, textio, validate  # noqa: E402
from ublib.engine import EngineError, registry, render_arch  # noqa: E402

IDS = ["I-%03d" % n for n in range(1, 9)]
CRIT = ["Impact", "Feasibility", "Distinctiveness"]
# the screen judge schema as bs.py schemas writes it once scores are bounded (C12)
SCREEN_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["scores"], "properties": {
    "scores": {"type": "array", "items": {
        "type": "object", "additionalProperties": False, "required": ["id", "c"],
        "properties": {"id": {"type": "string"},
                       "c": {"type": "object", "additionalProperties": False, "required": CRIT,
                             "properties": dict((c, {"type": "integer", "minimum": 1, "maximum": 5}) for c in CRIT)}}}}}}
SCREEN = {"type": "json", "schema": SCREEN_SCHEMA, "cover": {"array": "scores", "key": "id", "ids": IDS}}


def row(iid, score=3):
    return {"id": iid, "c": dict((c, score) for c in CRIT)}


def screen_out(rows):
    return json.dumps({"scores": rows}, ensure_ascii=False)


class ExactCover(unittest.TestCase):
    def test_poison_pill_screen_judge(self):
        # REPORT 6.1: every id, plus a duplicate I-008 with all scores 5, plus 'I-001' + U+200B, plus a score of 900
        rows = [row(i) for i in IDS] + [row("I-008", 5), row("I-001\u200b", 4)]
        rows[2]["c"]["Impact"] = 900
        ok, errors, _ = validate.check_contract(screen_out(rows), SCREEN, None)
        self.assertFalse(ok)
        self.assertTrue(any("greater than maximum 5" in e for e in errors), errors)
        self.assertTrue(any("more than once" in e and "I-008" in e and "I-001" in e for e in errors), errors)

    def test_duplicate_unknown_and_invisible_ids_fail(self):
        for extra, needle in ((row("I-003"), "more than once"), (row("I-999"), "unknown id I-999"),
                              (row("I-0O4"), "unknown id I-0O4"), (row("I-002\u200b"), "more than once"),
                              (row("I-00\u20283"), "unknown id")):
            ok, errors, _ = validate.check_contract(screen_out([row(i) for i in IDS] + [extra]), SCREEN, None)
            self.assertFalse(ok, extra)
            self.assertTrue(any(needle in e for e in errors), (extra, errors))

    def test_missing_message_unchanged(self):
        ok, errors, _ = validate.check_contract(screen_out([row(i) for i in IDS[:6]]), SCREEN, None)
        self.assertEqual(errors, ["cover: scores is missing id I-007, I-008"])

    def test_invisible_or_compatibility_forms_are_canonicalized(self):
        rows = [row(i) for i in IDS]
        rows[0]["id"] = "I-001\u200b"
        rows[1]["id"] = "\u202eI-002"
        rows[2]["id"] = "I-\uff10\uff10\uff13"  # fullwidth digits
        ok, errors, parsed = validate.check_contract(screen_out(rows), SCREEN, None)
        self.assertTrue(ok, errors)
        self.assertEqual([r["id"] for r in parsed["scores"]], IDS)  # what the adapter writes

    def test_scores_out_of_range_fail(self):
        for bad in (0, 6, 10, 900):
            rows = [row(i) for i in IDS]
            rows[5]["c"]["Feasibility"] = bad
            self.assertFalse(validate.check_contract(screen_out(rows), SCREEN, None)[0], bad)


class BoundedNumbers(unittest.TestCase):
    def test_non_finite_numbers_fail(self):
        s = {"type": "number", "minimum": 0, "maximum": 1}
        for v in (float("nan"), float("inf"), float("-inf")):
            self.assertTrue(schema_lite.validate(v, s), v)
            self.assertTrue(schema_lite.validate(v, {"minimum": 0}), v)
            self.assertTrue(schema_lite.validate(v, {"type": "number"}), v)
        self.assertEqual(schema_lite.validate(0.5, s), [])
        self.assertEqual(schema_lite.validate(10 ** 400, {"type": "integer", "minimum": 1}), [])

    def test_min_max_properties(self):
        s = validate.CRITERIA_SCHEMA
        self.assertEqual(schema_lite.validate({"Value": 60, "Fit": 40}, s), [])
        self.assertIn("fewer than minProperties 1", schema_lite.validate({}, s)[0])
        self.assertTrue(schema_lite.validate({"Value": 160}, s))
        self.assertIn("more than maxProperties 1", schema_lite.validate({"a": 1, "b": 2}, {"maxProperties": 1})[0])

    def test_extract_json_rejects_nan(self):
        for text in ('{"confidence": NaN}', '```json\n{"a": Infinity}\n```', 'x {"a": -Infinity} y'):
            with self.assertRaises(ValueError, msg=text):
                textio.extract_json(text)

    def test_template_scores_are_bounded(self):
        c = {"type": "json", "schema": "SK:templates/schemas/arch-judge.schema.json"}
        cand = {"label": "A", "veto": False, "veto_reason": "", "scores": [{"criterion": "QG1", "score": 7,
                                                                             "reason": "r"}],
                "sensitivity_points": [], "tradeoff_points": [], "risks": [], "non_risks": []}
        ok, errors, _ = validate.check_contract(json.dumps({"candidates": [cand], "steal": []}), c, None)
        self.assertFalse(ok)
        self.assertIn("greater than maximum 5", errors[0])
        cand["scores"][0]["score"] = 4
        self.assertTrue(validate.check_contract(json.dumps({"candidates": [cand], "steal": []}), c, None)[0])


class NoFragmentsOfMalformedDocuments(unittest.TestCase):
    MALFORMED = '{"adrs": [{"title": "A", "options": [{"name": "x"}]},], "risks": []}'

    def test_extract_json_never_returns_an_inner_fragment(self):
        for text in (self.MALFORMED, "```json\n%s\n```" % self.MALFORMED, '{"a": [1, 2}, "b": {"c": 1}',
                     '{"adrs": [{"title": "A"}, {"title": "B"}'):
            with self.assertRaises(ValueError, msg=text):
                textio.extract_json(text)

    def test_read_json_of_a_malformed_file_raises(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "decisions.json")
            with open(p, "w", encoding="utf-8") as f:
                f.write(self.MALFORMED)
            with self.assertRaises(ValueError):
                textio.read_json(p)
            with self.assertRaises(ValueError):
                textio.read_json_strict(p)

    def test_prose_salvage_still_works(self):
        for text, want in (('Ranking [draft, see below:\n{"winner": "A"}\n', {"winner": "A"}),
                           ('He said "use this.\n{"winner": "A"}\n', {"winner": "A"}),
                           ('[Note] then {"ok": 1}', {"ok": 1}),
                           ('x {"k": "v [ not a bracket \\" ]"} y', {"k": 'v [ not a bracket " ]'})):
            self.assertEqual(textio.extract_json(text), want, text)

    def test_loads_strict(self):
        self.assertEqual(textio.loads_strict('\ufeff```json\n{"a": 1}\n```\n'), {"a": 1})
        for bad in ('{"a": 1,}', '{"a": 1} trailing', '{"a": NaN}', '"text"', "", "```json\n{\"a\": 1}"):
            with self.assertRaises(ValueError, msg=bad):
                textio.loads_strict(bad)


ADR = {"title": "Use Postgres", "context": "c", "drivers": ["QG1"],
       "options": [{"name": "Postgres", "pros": ["p"], "cons": ["c"]}, {"name": "SQLite", "pros": [], "cons": []}],
       "chosen": "Postgres", "justification": "j", "good": ["g"], "bad": [{"text": "b", "risk_ids": ["R-001"]}],
       "confirmation": "review", "more_info": ""}
RISK = {"id": "R-001", "text": "outage", "likelihood": "L", "impact": "H", "mitigation": "m", "owner": "ops",
        "early_warning": "w", "source": "s"}
DECISIONS = {"adrs": [ADR], "risks": [RISK], "debt": []}
ARCH_FIX = {"type": "files", "allowed": ["chosen/*.md", "decisions.json", "review/resolution.md"],
            "required": ["review/resolution.md"], "status_trailer": False}


def files_out(blocks):
    return "".join("=== FILE: %s ===\n%s\n=== END FILE ===\n" % (rel, body) for rel, body in blocks)


class JsonFileBlocks(unittest.TestCase):
    RES = ("review/resolution.md", "# Resolution\n\n| finding | status |\n|---|---|\n| F-1 | FIXED |")

    def test_trailing_comma_decisions_json_earns_a_repair(self):
        body = json.dumps(DECISIONS, indent=1).replace('"debt": []', '"debt": [],')
        ok, errors, _ = validate.check_contract(files_out([("decisions.json", body), self.RES]), ARCH_FIX, None)
        self.assertFalse(ok)
        self.assertTrue(any(e.startswith("decisions.json: not valid JSON") for e in errors), errors)

    def test_decisions_json_is_checked_against_its_schema(self):
        body = json.dumps(ADR)  # valid JSON, but one ADR object instead of the register
        ok, errors, _ = validate.check_contract(files_out([("decisions.json", body), self.RES]), ARCH_FIX, None)
        self.assertFalse(ok)
        self.assertTrue(any("decisions.json: $: missing required property" in e for e in errors), errors)

    def test_valid_decisions_json_is_written_canonical(self):
        body = "```json\n" + json.dumps(DECISIONS) + "\n```"
        text = files_out([("decisions.json", body), self.RES])
        ok, errors, parsed = validate.check_contract(text, ARCH_FIX, None)
        self.assertTrue(ok, errors)
        self.assertEqual(parsed["json"]["decisions.json"], DECISIONS)
        with tempfile.TemporaryDirectory() as d:
            res = filesproto.split_output(text, d, ARCH_FIX["allowed"], parsed=parsed)
            self.assertTrue(res["ok"], res)
            with open(os.path.join(d, "decisions.json"), encoding="utf-8") as f:
                self.assertEqual(f.read(), json.dumps(DECISIONS, indent=1, ensure_ascii=False) + "\n")

    def test_criteria_json(self):
        c = {"type": "files", "allowed": ["01_FRAME.md", "criteria.json"], "required": ["01_FRAME.md", "criteria.json"]}
        frame = ("01_FRAME.md", "# FRAME\n\n## Criteria\n- Value")
        for body, ok_want in (('{"Value": 60, "Fit": 40}', True), ('{"Value": 60, "Fit": 40,}', False),
                              ("{}", False), ('{"Value": "high"}', False), ('{"Value": 400}', False),
                              ('["Value"]', False), ('// weights\n{"Value": 100}', False)):
            ok, errors, _ = validate.check_contract(files_out([frame, ("criteria.json", body)]), c, None)
            self.assertEqual(ok, ok_want, (body, errors))

    def test_per_file_schema_rule(self):
        c = {"type": "files", "allowed": ["x.json"], "per_file": {"x.json": {"schema": {
            "type": "object", "required": ["k"], "properties": {"k": {"type": "integer", "minimum": 1}}}}}}
        self.assertTrue(validate.check_contract(files_out([("x.json", '{"k": 2}')]), c, None)[0])
        ok, errors, _ = validate.check_contract(files_out([("x.json", '{"k": 0}')]), c, None)
        self.assertEqual(errors, ["x.json: $.k: 0 is less than minimum 1"])


class FileFraming(unittest.TestCase):
    def test_end_file_line_inside_content_is_a_contract_error(self):
        text = ("=== FILE: sections/02.md ===\n## 2. Problem and Evidence\nIntro.\n```\n=== END FILE ===\n```\n"
                "Second half.\n=== END FILE ===\n")
        c = {"type": "files", "allowed": ["sections/*.md"], "per_file": {"sections/02.md": {
            "headings": ["## 2. Problem"]}}}
        ok, errors, _ = validate.check_contract(text, c, None)
        self.assertFalse(ok)
        self.assertTrue(any("END FILE ===' line inside its content" in e for e in errors), errors)
        with tempfile.TemporaryDirectory() as d:
            res = filesproto.split_output(text, d, ["sections/*.md"])
            self.assertFalse(res["ok"])
            self.assertEqual(os.listdir(d), [])
        indented = "=== FILE: a.md ===\n# A\n    === END FILE ===\nrest\n=== END FILE ===\n"
        self.assertEqual(len(filesproto.structural_errors(filesproto.parse_file_blocks(indented)[2])), 1)

    def test_chatter_between_blocks_is_still_ignored(self):
        text = "pre\n=== FILE: a.md ===\nA\n=== END FILE ===\nchatter\n=== FILE: b.md ===\nB\n=== END FILE ===\nend\n"
        files, _s, warnings = filesproto.parse_file_blocks(text)
        self.assertEqual(files, {"a.md": "A\n", "b.md": "B\n"})
        self.assertEqual(warnings, [])


class CanonicalPaths(unittest.TestCase):
    ALLOWED = ["chosen/*.md", "sections/*.md"]

    def test_case_twins_are_rejected(self):
        text = files_out([("chosen/containers.md", "GOOD lower"), ("chosen/CONTAINERS.md", "EVIL upper")])
        ok, errors, _ = validate.check_contract(text, {"type": "files", "allowed": self.ALLOWED}, None)
        self.assertFalse(ok)
        self.assertTrue(any("differ only in letter case" in e for e in errors), errors)
        with tempfile.TemporaryDirectory() as d:
            self.assertFalse(filesproto.split_output(text, d, self.ALLOWED)["ok"])
            self.assertEqual(os.listdir(d), [])

    def test_invisible_bidi_and_odd_spaces_are_rejected(self):
        for p in ("chosen/x\u200b.md", "chosen/x\u202egpj.md", "chosen/CON\u200b.md", "chosen/a\u00a0b.md",
                  "chosen/a\x7fb.md", "chosen/a\u3000b.md", "sections/0\u20601.md", "chosen/\ue000.md"):
            with self.assertRaises(filesproto.PathError, msg=repr(p)):
                filesproto.check_relpath(p, self.ALLOWED)
        self.assertEqual(filesproto.check_relpath("chosen/a b.md", self.ALLOWED), "chosen/a b.md")
        self.assertEqual(filesproto.check_relpath("chosen/donne\u00e9s.md", self.ALLOWED), "chosen/donne\u00e9s.md")

    def test_keys_are_nfc(self):
        files, _s, _w = filesproto.parse_file_blocks(files_out([("chosen/cafe\u0301.md", "x")]))
        self.assertEqual(list(files), ["chosen/caf\u00e9.md"])
        text = files_out([("chosen/caf\u00e9.md", "one"), ("chosen/cafe\u0301.md", "two")])
        files, _s, warnings = filesproto.parse_file_blocks(text)
        self.assertEqual(files, {"chosen/caf\u00e9.md": "two\n"})
        self.assertTrue(any("duplicate" in w for w in warnings))


def idea(bid, missing=None):
    lines = ["### %s Idea %s" % (bid, bid), "- Pitch: p", "- **Mechanism**: m", "- For whom / when: nurses",
             "- Fails if: f"]
    return "\n".join(ln for ln in lines if not (missing and ln.startswith("- %s" % missing)))


class OneIdeaBlockParser(unittest.TestCase):
    C = {"type": "idea-blocks", "prefix": "E", "min": 2}

    def test_duplicate_id_fails_even_with_enough_blocks(self):
        text = "\n\n".join([idea("E-01"), idea("E-02"), idea("E-03"), idea("E-01")])
        ok, errors, _ = validate.check_contract(text, self.C, None)
        self.assertFalse(ok)
        self.assertIn("E-01 appears more than once: one block per ID", errors)

    def test_consumers_see_what_the_contract_accepted(self):
        text = "\n\n".join([idea("E-01"), idea("E-02"), "```\n%s\n```" % idea("E-09"), idea("E-05", "Fails"),
                            "## Notes\n- Pitch: not an idea", "###E-04 no space\n- Pitch: p\n- Mechanism: m\n"
                            "- Fails if: f", idea("E-\uff13")])
        ok, errors, parsed = validate.check_contract(text, self.C, None)
        self.assertTrue(ok, errors)
        blocks = registry.idea_blocks(text, "E")
        self.assertEqual([b["id"] for b in parsed], ["E-01", "E-02"])
        self.assertEqual([b["id"] for b in blocks], ["E-01", "E-02"])
        self.assertEqual(blocks[0]["fields"], {"pitch": "p", "mechanism": "m", "for whom / when": "nurses",
                                               "fails if": "f"})
        self.assertEqual(blocks, parsed)
        self.assertEqual([b["id"] for b in registry.idea_blocks(text)], ["E-01", "E-02"])  # any prefix

    def test_field_labels(self):
        body = ("- Pitch: one\n* **Fails if** : two\n**Mechanism**: not a bullet\n- Step 1: digits\n- a" + " " * 5000
                + "b: x\n- Pitch: second wins nothing")
        self.assertEqual(validate.idea_fields(body), {"pitch": "one", "fails if": "two", "a" + " " * 5000 + "b": "x"})


class RenderArchNeverDeletesOnAParseFailure(tl.EngineTestCase):
    def setUp(self):
        super(RenderArchNeverDeletesOnAParseFailure, self).setUp()
        self.ctx = self.make_ctx()
        self.ctx.write("10_ARCHITECTURE/adr/0001-use-postgres.md", "old ADR\n")
        self.ctx.write("10_ARCHITECTURE/adr/0002-old-choice.md", "old ADR 2\n")

    def adrs(self):
        return sorted(os.listdir(self.ctx.path("10_ARCHITECTURE", "adr")))

    def test_malformed_decisions_json_blocks_with_a_clear_error(self):
        self.ctx.write("10_ARCHITECTURE/decisions.json", NoFragmentsOfMalformedDocuments.MALFORMED)
        with self.assertRaises(EngineError) as cm:
            render_arch.rerender_adrs(self.ctx)
        self.assertIn("decisions.json is not valid JSON", str(cm.exception))
        self.assertEqual(self.adrs(), ["0001-use-postgres.md", "0002-old-choice.md"])

    def test_no_adrs_keeps_the_files(self):
        for body in ({"risks": [RISK]}, {"adrs": {}}, {"adrs": ["x"]}, {"adrs": []}):
            self.ctx.write_json("10_ARCHITECTURE/decisions.json", body)
            self.assertEqual(render_arch.rerender_adrs(self.ctx), [])
            self.assertEqual(self.adrs(), ["0001-use-postgres.md", "0002-old-choice.md"])

    def test_valid_decisions_replace_stale_files(self):
        self.ctx.write_json("10_ARCHITECTURE/decisions.json", DECISIONS)
        self.assertEqual(render_arch.rerender_adrs(self.ctx), ["adr/0001-use-postgres.md"])
        self.assertEqual(self.adrs(), ["0001-use-postgres.md"])


if __name__ == "__main__":
    unittest.main()
