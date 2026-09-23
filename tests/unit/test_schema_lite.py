"""Unit tests for ublib.schema_lite (KIT_SPEC 4.8, 7.4)."""

import os
import sys
import unittest

_KIT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_SCRIPTS = os.path.join(_KIT, "skills", "ultimate-brainstorm", "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

from ublib import schema_lite  # noqa: E402
from ublib.schema_lite import validate  # noqa: E402


class TypeTests(unittest.TestCase):
    def test_each_type(self):
        cases = [("object", {}, []), ("array", [], {}), ("string", "s", 1), ("number", 1.5, "1"),
                 ("integer", 3, 3.5), ("boolean", False, 0), ("null", None, 0)]
        for name, good, bad in cases:
            self.assertEqual(validate(good, {"type": name}), [], name)
            self.assertEqual(len(validate(bad, {"type": name})), 1, name)

    def test_bool_is_not_a_number(self):
        self.assertTrue(validate(True, {"type": "integer"}))
        self.assertTrue(validate(False, {"type": "number"}))

    def test_integral_float_is_integer(self):
        self.assertEqual(validate(3.0, {"type": "integer"}), [])
        self.assertEqual(validate(3, {"type": "number"}), [])

    def test_type_list(self):
        s = {"type": ["string", "null"]}
        self.assertEqual(validate(None, s), [])
        self.assertEqual(validate("x", s), [])
        self.assertIn("expected string or null", validate(1, s)[0])

    def test_type_error_stops_deeper_checks(self):
        errs = validate("x", {"type": "object", "required": ["a"]})
        self.assertEqual(len(errs), 1)


class KeywordTests(unittest.TestCase):
    def test_required_and_properties(self):
        s = {"type": "object", "required": ["a", "b"], "properties": {"a": {"type": "string"}}}
        self.assertEqual(validate({"a": "x", "b": 1}, s), [])
        errs = validate({"a": 1}, s)
        self.assertEqual(len(errs), 2)
        self.assertTrue(any("$.a: expected string" in e for e in errs))
        self.assertTrue(any("missing required property \"b\"" in e for e in errs))

    def test_additional_properties_false(self):
        s = {"type": "object", "additionalProperties": False, "properties": {"a": {}}}
        self.assertEqual(validate({"a": 1}, s), [])
        self.assertIn("additional property \"z\"", validate({"a": 1, "z": 2}, s)[0])

    def test_additional_properties_schema(self):
        s = {"type": "object", "properties": {}, "additionalProperties": {"type": "integer"}}
        self.assertEqual(validate({"x": 1, "y": 2}, s), [])
        self.assertEqual(validate({"x": "no"}, s), ["$.x: expected integer, got string"])

    def test_items_and_counts(self):
        s = {"type": "array", "items": {"type": "integer"}, "minItems": 2, "maxItems": 3}
        self.assertEqual(validate([1, 2], s), [])
        self.assertIn("fewer than minItems 2", validate([1], s)[0])
        self.assertIn("more than maxItems 3", validate([1, 2, 3, 4], s)[0])
        self.assertEqual(validate([1, "x"], s), ["$[1]: expected integer, got string"])

    def test_items_tuple_form(self):
        s = {"type": "array", "items": [{"type": "string"}, {"type": "integer"}]}
        self.assertEqual(validate(["a", 1, None], s), [])
        self.assertEqual(len(validate([1, "a"], s)), 2)

    def test_enum(self):
        s = {"enum": ["H", "M", "L"]}
        self.assertEqual(validate("M", s), [])
        self.assertIn("is not one of", validate("X", s)[0])

    def test_enum_does_not_confuse_bool_and_int(self):
        self.assertTrue(validate(True, {"enum": [1, 2]}))
        self.assertTrue(validate(1, {"enum": [True]}))
        self.assertEqual(validate(1.0, {"enum": [1]}), [])

    def test_min_max(self):
        s = {"type": "integer", "minimum": 1, "maximum": 5}
        self.assertEqual(validate(1, s), [])
        self.assertEqual(validate(5, s), [])
        self.assertIn("less than minimum 1", validate(0, s)[0])
        self.assertIn("greater than maximum 5", validate(6, s)[0])

    def test_string_length(self):
        s = {"type": "string", "minLength": 2, "maxLength": 4}
        self.assertEqual(validate("abc", s), [])
        self.assertIn("shorter than 2", validate("a", s)[0])
        self.assertIn("longer than 4", validate("abcde", s)[0])

    def test_annotations_and_unknown_keywords_ignored(self):
        s = {"$id": "x", "$schema": "y", "title": "t", "description": "d", "pattern": "^z$", "type": "string"}
        self.assertEqual(validate("anything", s), [])

    def test_boolean_schemas(self):
        self.assertEqual(validate(1, True), [])
        self.assertEqual(validate({"a": 1}, {"properties": {"a": False}}), ["$.a: not allowed"])

    def test_nested_paths(self):
        s = {"type": "object", "properties": {"rows": {"type": "array", "items": {
            "type": "object", "required": ["id"], "properties": {"id": {"type": "string"}}}}}}
        errs = validate({"rows": [{"id": "a"}, {"id": 2}, {}]}, s)
        self.assertEqual(errs, ["$.rows[1].id: expected string, got integer",
                                "$.rows[2]: missing required property \"id\""])

    def test_error_cap(self):
        s = {"type": "array", "items": {"type": "string"}}
        errs = validate(list(range(500)), s)
        self.assertLessEqual(len(errs), schema_lite.MAX_ERRORS + 1)
        self.assertEqual(errs[-1], "... more errors omitted")

    def test_is_valid(self):
        self.assertTrue(schema_lite.is_valid({}, {"type": "object"}))
        self.assertFalse(schema_lite.is_valid([], {"type": "object"}))


class SpecSchemaTests(unittest.TestCase):
    """The arch-drivers schema from KIT_SPEC 7.4 (structured-output style: all required, no extras)."""

    SCHEMA = {"$id": "arch-drivers", "type": "object", "additionalProperties": False,
              "required": ["product_goal", "quality_goals", "open_questions"],
              "properties": {
                  "product_goal": {"type": "string"},
                  "quality_goals": {"type": "array", "items": {
                      "type": "object", "additionalProperties": False,
                      "required": ["id", "name", "weight", "why", "source"],
                      "properties": {"id": {"type": "string"}, "name": {"type": "string"},
                                     "weight": {"type": "number"}, "why": {"type": "string"},
                                     "source": {"type": "string", "enum": ["STATED", "ASSUMPTION"]}}}},
                  "open_questions": {"type": "array", "items": {
                      "type": "object", "additionalProperties": False, "required": ["q", "default"],
                      "properties": {"q": {"type": "string"}, "default": {"type": "string"}}}}}}

    def test_valid_instance(self):
        inst = {"product_goal": "g", "quality_goals": [
            {"id": "QG1", "name": "Latency", "weight": 40, "why": "w", "source": "STATED"},
            {"id": "QG2", "name": "Cost", "weight": 30.0, "why": "w", "source": "ASSUMPTION"}],
            "open_questions": [{"q": "q?", "default": "d"}]}
        self.assertEqual(validate(inst, self.SCHEMA), [])

    def test_invalid_instance(self):
        inst = {"product_goal": "g", "quality_goals": [
            {"id": "QG1", "name": "Latency", "weight": "40", "why": "w", "source": "GUESS", "extra": 1}],
            "open_questions": []}
        errs = validate(inst, self.SCHEMA)
        self.assertEqual(len(errs), 3, errs)


if __name__ == "__main__":
    unittest.main()
