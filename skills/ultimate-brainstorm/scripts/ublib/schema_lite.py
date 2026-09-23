"""A small JSON-schema subset validator (KIT_SPEC 4.8, 7.4).

validate(instance, schema) -> list of error strings (empty list = valid).

Supported keywords: type (a name or a list of names), required, properties, additionalProperties (bool or schema),
items (schema, or a list of schemas for tuple form), enum, minItems, maxItems, minimum, maximum, minLength,
maxLength. Annotation keywords ($id, $schema, title, description, default, examples) are ignored, and so is every
other unknown keyword (the kit's schemas use only the subset above, see 7.4 and [U-32]).

Types: object, array, string, number, integer, boolean, null. Booleans are never numbers; a float with an integral
value (3.0) counts as an integer, as in JSON Schema.
"""

import json

__all__ = ["validate", "is_valid", "MAX_ERRORS"]

MAX_ERRORS = 50

_TYPE_NAMES = ("object", "array", "string", "number", "integer", "boolean", "null")


def _type_ok(value, name):
    if name == "object":
        return isinstance(value, dict)
    if name == "array":
        return isinstance(value, list)
    if name == "string":
        return isinstance(value, str)
    if name == "boolean":
        return isinstance(value, bool)
    if name == "null":
        return value is None
    if name == "integer":
        if isinstance(value, bool):
            return False
        if isinstance(value, int):
            return True
        return isinstance(value, float) and value.is_integer()
    if name == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    return True  # unknown type names are not enforced


def _type_of(value):
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return type(value).__name__


def _short(value, limit=60):
    try:
        s = json.dumps(value, ensure_ascii=True)
    except (TypeError, ValueError):
        s = repr(value)
    return s if len(s) <= limit else s[:limit - 3] + "..."


def _is_number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _check(inst, schema, path, errors):
    if len(errors) >= MAX_ERRORS:
        return
    if schema is True or schema is None:
        return
    if schema is False:
        errors.append("%s: not allowed" % path)
        return
    if not isinstance(schema, dict):
        return

    t = schema.get("type")
    if t is not None:
        names = t if isinstance(t, list) else [t]
        if not any(_type_ok(inst, n) for n in names):
            errors.append("%s: expected %s, got %s" % (path, " or ".join(str(n) for n in names), _type_of(inst)))
            return

    if "enum" in schema and isinstance(schema["enum"], list):
        if not any(inst == e and _type_of(inst) == _type_of(e) or (_is_number(inst) and _is_number(e) and inst == e)
                   for e in schema["enum"]):
            errors.append("%s: %s is not one of %s" % (path, _short(inst), _short(schema["enum"], 120)))

    if isinstance(inst, str):
        if isinstance(schema.get("minLength"), int) and len(inst) < schema["minLength"]:
            errors.append("%s: string shorter than %d" % (path, schema["minLength"]))
        if isinstance(schema.get("maxLength"), int) and len(inst) > schema["maxLength"]:
            errors.append("%s: string longer than %d" % (path, schema["maxLength"]))

    if _is_number(inst):
        if _is_number(schema.get("minimum")) and inst < schema["minimum"]:
            errors.append("%s: %s is less than minimum %s" % (path, _short(inst), _short(schema["minimum"])))
        if _is_number(schema.get("maximum")) and inst > schema["maximum"]:
            errors.append("%s: %s is greater than maximum %s" % (path, _short(inst), _short(schema["maximum"])))

    if isinstance(inst, list):
        if isinstance(schema.get("minItems"), int) and len(inst) < schema["minItems"]:
            errors.append("%s: %d items, fewer than minItems %d" % (path, len(inst), schema["minItems"]))
        if isinstance(schema.get("maxItems"), int) and len(inst) > schema["maxItems"]:
            errors.append("%s: %d items, more than maxItems %d" % (path, len(inst), schema["maxItems"]))
        items = schema.get("items")
        if isinstance(items, list):
            for i, (value, sub) in enumerate(zip(inst, items)):
                _check(value, sub, "%s[%d]" % (path, i), errors)
        elif items is not None:
            for i, value in enumerate(inst):
                _check(value, items, "%s[%d]" % (path, i), errors)
                if len(errors) >= MAX_ERRORS:
                    return

    if isinstance(inst, dict):
        req = schema.get("required")
        if isinstance(req, list):
            for key in req:
                if key not in inst:
                    errors.append("%s: missing required property %s" % (path, _short(key)))
        props = schema.get("properties")
        props = props if isinstance(props, dict) else {}
        for key, sub in props.items():
            if key in inst:
                _check(inst[key], sub, "%s.%s" % (path, key), errors)
        addl = schema.get("additionalProperties", True)
        extra = [k for k in inst if k not in props]
        if addl is False:
            for key in extra:
                errors.append("%s: additional property %s is not allowed" % (path, _short(key)))
        elif isinstance(addl, dict):
            for key in extra:
                _check(inst[key], addl, "%s.%s" % (path, key), errors)


def validate(instance, schema):
    """Validate instance against schema; return a list of error strings (at most MAX_ERRORS)."""
    errors = []
    _check(instance, schema, "$", errors)
    if len(errors) >= MAX_ERRORS:
        errors = errors[:MAX_ERRORS] + ["... more errors omitted"]
    return errors


def is_valid(instance, schema):
    return not validate(instance, schema)
