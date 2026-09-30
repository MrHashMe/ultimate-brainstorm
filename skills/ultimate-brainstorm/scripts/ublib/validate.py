"""Output contracts (KIT_SPEC 4.5).

Frozen API (4.8):
    check_contract(text, contract, run_dir) -> (ok: bool, errors: list[str], parsed: object|None)

Extras: repair_prompt(errors, previous_output), load_schema(ref, run_dir), parse_idea_blocks(text, prefix),
idea_fields(body), canonical_id(value), REGISTER_SCHEMAS, OUTPUT_CAP_BYTES, CONTRACT_TYPES.

Contract types: text, idea-blocks, json, sections, cards, files. `parsed` per type:
    text         the stripped text
    idea-blocks  [{"id", "title", "body", "fields"}] for the valid blocks
    json         the extracted JSON value (cover keys canonicalized in place)
    sections     {"sections": {heading_prefix: body}, "json_tail": obj|None, "final_line": str}
    cards        {ID: {line_prefix: value}}
    files        {"files": {relpath: content}, "status": dict|None, "warnings": [...], "json": {relpath: value}}

Every parser here is linear in the output (headings and fences come from textio's line scanners).
"""

import os
import re
import unicodedata

from . import SK_DIR
from . import filesproto
from . import schema_lite
from . import textio

__all__ = ["check_contract", "repair_prompt", "load_schema", "OUTPUT_CAP_BYTES", "CONTRACT_TYPES", "REPAIR_MAX_CHARS",
           "parse_idea_blocks", "idea_fields", "canonical_id", "REGISTER_SCHEMAS", "card_sections"]

OUTPUT_CAP_BYTES = 2 * 1024 * 1024  # 5.4: larger output counts as invalid
REPAIR_MAX_CHARS = 1500
CONTRACT_TYPES = ("text", "idea-blocks", "json", "sections", "cards", "files")

# FILE-protocol .json files that the engine reads back as registers: their value must match this schema even when the
# contract's per_file names none (a per_file "schema" replaces it). Keyed by the path relative to the split root.
CRITERIA_SCHEMA = {"type": "object", "minProperties": 1,
                   "additionalProperties": {"type": "number", "minimum": 0, "maximum": 100}}
REGISTER_SCHEMAS = {"decisions.json": "SK:templates/schemas/arch-decisions.schema.json",
                    "criteria.json": CRITERIA_SCHEMA}


# ---------------------------------------------------------------- helpers

def repair_prompt(errors, previous_output):
    """The one repair call's prompt (4.5): the error summary (max 1500 chars), the fixed instruction, then the
    previous output."""
    if isinstance(errors, str):
        summary = errors
    else:
        summary = "; ".join(str(e) for e in errors)
    summary = " ".join(summary.split())
    if len(summary) > REPAIR_MAX_CHARS:
        summary = summary[:REPAIR_MAX_CHARS - 3] + "..."
    return ("Your previous output failed validation: %s. Return only the corrected output.\n\n%s"
            % (summary, previous_output or ""))


def load_schema(ref, run_dir):
    """Resolve a contract schema reference and load it.

    ref: a dict (inline schema), "SK:templates/schemas/<f>" (relative to the skill folder), an absolute path, or a
    path relative to run_dir. Raises ValueError when it cannot be loaded.
    """
    if isinstance(ref, dict):
        return ref
    if not isinstance(ref, str) or not ref.strip():
        raise ValueError("schema reference is empty")
    ref = ref.strip()
    if ref.startswith("SK:"):
        path = os.path.join(SK_DIR, *ref[3:].lstrip("/\\").split("/"))
    elif os.path.isabs(ref):
        path = ref
    else:
        path = os.path.join(os.fspath(run_dir or "."), *ref.split("/"))
    try:
        value = textio.read_json(path)
    except OSError:
        raise ValueError("schema not found: %s" % ref)
    except (ValueError, RecursionError) as e:
        raise ValueError("schema %s is not valid JSON: %s" % (ref, e))
    if not isinstance(value, dict):
        raise ValueError("schema %s is not a JSON object" % ref)
    return value


def _compile(rx, flags=0):
    try:
        return re.compile(rx, flags), None
    except re.error as e:
        return None, "invalid contract regex %r: %s" % (rx, e)


def _nonempty_lines(text):
    return [ln for ln in text.split("\n") if ln.strip()]


def _headings(text):
    """[(line_index, level, full_line_normalized, text_normalized)] for headings outside fences."""
    out = []
    for i, level, title in textio.headings(text):
        t = " ".join(title.split())
        out.append((i, level, ("#" * level + " " + t).lower(), t.lower()))
    return out


def _prefix_hit(heading, prefix):
    p = " ".join(str(prefix).split()).lower()
    if p.startswith("#"):
        return heading[2].startswith(p)
    return heading[3].startswith(p)


def _words(text):
    lines = text.split("\n")
    mask = textio.fence_mask(lines)
    return sum(len(ln.split()) for i, ln in enumerate(lines) if not mask[i])


def canonical_id(value):
    """An ID as a cover compares it: NFKC-normalized, with Unicode format characters (zero-width, bidi controls)
    removed and surrounding whitespace stripped. 'I-001' + U+200B and 'I-001' in fullwidth digits (U+FF10, U+FF11)
    are both 'I-001'."""
    s = unicodedata.normalize("NFKC", str(value))
    return "".join(ch for ch in s if unicodedata.category(ch) != "Cf").strip()


# ---------------------------------------------------------------- idea blocks (one parser: contract and consumers)

_BULLET_LINE = re.compile(r"^[ \t]*[-*][^\n]*", re.MULTILINE)
_BULLET = re.compile(r"[ \t]*[-*][ \t]*")
_LABEL_CHARS = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz /")
IDEA_REQUIRED_LINES = ("Pitch", "Mechanism", "Fails if")


def idea_fields(body):
    """{label_lowercase: value} for the '- Label: value' lines of an idea block (the first line of a label wins).
    A label is letters, spaces and '/', optionally in **bold**. String operations only: linear per line."""
    fields = {}
    for m in _BULLET_LINE.finditer(body or ""):
        line = m.group(0)
        rest = line[_BULLET.match(line).end():]
        colon = rest.find(":")
        if colon < 0:
            continue
        label = rest[:colon].rstrip()
        if label.startswith("**"):
            label = label[2:]
        if label.endswith("**"):
            label = label[:-2]
        label = label.strip()
        if label and all(ch in _LABEL_CHARS for ch in label):
            fields.setdefault(label.lower(), rest[colon + 1:].strip())
    return fields


def parse_idea_blocks(text, prefix=None):
    """The idea-blocks format (4.5), parsed once for the contract and for every consumer (registry.idea_blocks).

    A block starts at a '### <PREFIX>-NN <title>' heading outside fenced code (NN: ASCII digits; any prefix of the
    form [A-Z][A-Za-z0-9]* when prefix is None) and ends at the next heading of any level. It counts when it has
    '- Pitch:', '- Mechanism:' and '- Fails if:' lines. Only the first heading of an ID opens a block.
    Returns (blocks, problems, duplicates): blocks [{"id", "title", "body", "fields"}] that count, in order;
    problems for the blocks that do not count; the IDs that head more than one block.
    """
    pfx = re.escape(prefix) if prefix else r"[A-Z][A-Za-z0-9]*"
    head_rx = re.compile(r"^###\s+(%s-[0-9]+)[:.)]?\s+(\S.*)$" % pfx)
    text = text or ""
    lines = text.split("\n")
    heads = textio.headings(text)
    blocks, problems, dups, seen = [], [], [], set()
    for k, (i, _level, _title) in enumerate(heads):
        m = head_rx.match(lines[i].rstrip())
        if not m:
            continue
        bid = m.group(1)
        if bid in seen:
            if bid not in dups:
                dups.append(bid)
            continue
        seen.add(bid)
        end = heads[k + 1][0] if k + 1 < len(heads) else len(lines)
        body = "\n".join(lines[i + 1:end])
        fields = idea_fields(body)
        missing = [name for name in IDEA_REQUIRED_LINES if name.lower() not in fields]
        if missing:
            problems.append("%s lacks %s" % (bid, ", ".join("- %s:" % n for n in missing)))
            continue
        blocks.append({"id": bid, "title": m.group(2).strip(), "body": body.strip("\n"), "fields": fields})
    return blocks, problems, dups


# ---------------------------------------------------------------- contract types

def _check_text(text, c, run_dir):
    errors = []
    body = text.strip()
    min_chars = c.get("min_chars", 20)
    if isinstance(min_chars, int) and len(body) < min_chars:
        errors.append("output has %d characters, fewer than %d" % (len(body), min_chars))
    if c.get("regex"):
        rx, err = _compile(c["regex"], re.MULTILINE)
        if err:
            errors.append(err)
        elif not rx.search(body):
            errors.append("output does not match /%s/" % c["regex"])
    if c.get("final_line"):
        rx, err = _compile(c["final_line"])
        lines = _nonempty_lines(body)
        last = lines[-1].strip() if lines else ""
        if err:
            errors.append(err)
        elif not rx.search(last):
            errors.append("final line %r does not match /%s/" % (last[:120], c["final_line"]))
    return errors, body


def _check_idea_blocks(text, c, run_dir):
    prefix = str(c.get("prefix") or "").strip()
    need = c.get("min", 1)
    need = need if isinstance(need, int) else 1
    if not prefix:
        return ["contract idea-blocks has no prefix"], None
    blocks, problems, dups = parse_idea_blocks(text, prefix)
    errors = []
    if len(blocks) < need:
        errors.append("found %d valid %s-NN idea blocks, need at least %d (heading '### %s-NN <title>' with "
                      "'- Pitch:', '- Mechanism:' and '- Fails if:' lines)" % (len(blocks), prefix, need, prefix))
        errors.extend(problems[:10])
    # a repeated ID is ambiguous (which idea is meant?) however many blocks are valid: it earns the repair call
    errors.extend("%s appears more than once: one block per ID" % bid for bid in dups[:10])
    return errors, blocks


def _get_path(obj, dotted):
    if not dotted:
        return obj
    cur = obj
    for part in str(dotted).split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return None
    return cur


def _cover_key(value, loose=False):
    """canonical_id, and with `loose` also case and the separators '_', '-' and space folded ('Time to MVP' is
    'time_to_mvp'), as bs.py reads criterion ids."""
    k = canonical_id(value)
    return re.sub(r"[\s_-]+", "_", k.lower()) if loose else k


def _check_cover(value, cover, where=None):
    """The array's keys must be exactly the cover IDs: every ID once, no repeats, nothing else. Keys are compared by
    canonical_id (`loose`: also case and separators folded); a string key that differs from its expected ID only by
    that normalization is rewritten to that ID in place, so the written output carries the engine's IDs. `each` (a
    cover of the same shape) applies to the inner array of every item whose key is a cover ID, for example every
    criterion once in each candidate's scores."""
    errors = []
    if not isinstance(cover, dict):
        return errors
    arr_name, key, ids = cover.get("array"), cover.get("key", "id"), cover.get("ids") or []
    loose = bool(cover.get("loose"))
    arr = _get_path(value, arr_name)
    where = "%s.%s" % (where, arr_name or "$") if where else (arr_name or "$")
    if not isinstance(arr, list):
        return ["cover: %s is not an array" % where]
    expected = dict((_cover_key(i, loose), str(i)) for i in ids)
    counts, order, shown = {}, [], {}
    for item in arr:
        if isinstance(item, dict) and key in item:
            k = _cover_key(item[key], loose)
            if isinstance(item[key], str) and k in expected and item[key] != expected[k]:
                item[key] = expected[k]
            if k not in counts:
                order.append(k)
                shown[k] = expected.get(k, canonical_id(item[key]))
            counts[k] = counts.get(k, 0) + 1
    missing = [str(i) for i in ids if _cover_key(i, loose) not in counts]
    if missing:
        errors.append("cover: %s is missing %s %s" % (where, key, ", ".join(missing[:30])))
    repeated = [k for k in order if counts[k] > 1 and k in expected]
    if repeated:
        errors.append("cover: %s lists %s %s more than once (exactly one entry each)"
                      % (where, key, ", ".join(shown[k] for k in repeated[:30])))
    unknown = [k for k in order if k not in expected]
    if unknown:
        errors.append("cover: %s has unknown %s %s (only the listed ones)"
                      % (where, key, ", ".join(repr(shown[k]) if not textio.is_ascii(shown[k]) else shown[k]
                                               for k in unknown[:30])))
    inner = cover.get("each")
    if isinstance(inner, dict):
        for item in arr:
            if isinstance(item, dict) and isinstance(item.get(key), str) and _cover_key(item[key], loose) in expected:
                errors.extend(_check_cover(item, inner, "%s[%s]" % (where, item[key])))
    return errors


def _array_specs(value, specs):
    """[(spec, array path, array)] for the entries of a `unique` or `nonempty` option whose array exists (the schema
    reports a missing one)."""
    out = []
    for spec in specs if isinstance(specs, list) else []:
        arr = _get_path(value, spec.get("array")) if isinstance(spec, dict) else None
        if isinstance(arr, list):
            out.append((spec, spec.get("array") or "$", arr))
    return out


def _check_unique(value, specs):
    """`unique` [{"array", "key"}]: no two items of the array have the same key (compared by canonical_id), so a
    curator that lists one idea twice earns the repair call instead of blocking bs.py map or quick-pick later."""
    errors = []
    for spec, where, arr in _array_specs(value, specs):
        key = spec.get("key", "id")
        seen, repeated = set(), []
        for item in arr:
            k = canonical_id(item[key]) if isinstance(item, dict) and isinstance(item.get(key), str) else ""
            if k and k in seen and k not in repeated:
                repeated.append(k)
            seen.add(k)
        errors.extend("unique: %s lists %s %r more than once" % (where, key, r) for r in repeated[:30])
    return errors


def _check_nonempty(value, specs):
    """`nonempty` [{"array", "fields"}]: every listed field of every item is a string with a non-space character or a
    non-empty list (the schemas cannot say so, 7.4)."""
    errors = []
    for spec, where, arr in _array_specs(value, specs):
        for n, item in enumerate(arr):
            if not isinstance(item, dict):
                continue
            for f in spec.get("fields") or []:
                v = item.get(f)
                if (isinstance(v, str) and not v.strip()) or (isinstance(v, list) and not v):
                    errors.append("nonempty: %s[%d].%s is empty" % (where, n, f))
    return errors[:30]


def _check_json(text, c, run_dir):
    try:
        value = textio.extract_json(text)
    except (ValueError, RecursionError) as e:
        return ["no valid JSON found: %s" % e], None
    errors = []
    if c.get("schema") is not None:
        try:
            schema = load_schema(c["schema"], run_dir)
        except (ValueError, RecursionError) as e:
            return [str(e)], value
        errors.extend(schema_lite.validate(value, schema))
    if c.get("cover"):
        errors.extend(_check_cover(value, c["cover"]))
    errors.extend(_check_unique(value, c.get("unique")))
    errors.extend(_check_nonempty(value, c.get("nonempty")))
    return errors, value


def _check_sections(text, c, run_dir):
    errors = []
    lines = text.split("\n")
    heads = _headings(text)
    wanted = [h for h in (c.get("headings") or []) if str(h).strip()]
    pos, found = 0, {}
    for want in wanted:
        hit = None
        for k in range(pos, len(heads)):
            if _prefix_hit(heads[k], want):
                hit = k
                break
        if hit is None:
            anywhere = any(_prefix_hit(h, want) for h in heads)
            errors.append("heading %r %s" % (want, "is out of order" if anywhere else "is missing"))
            continue
        found[want] = hit
        pos = hit + 1

    def body_of(k):
        start, level = heads[k][0], heads[k][1]
        end = len(lines)
        for j in range(k + 1, len(heads)):
            if heads[j][1] <= level:
                end = heads[j][0]
                break
        return "\n".join(lines[start + 1:end]).strip("\n")

    sections = {want: body_of(k) for want, k in found.items()}

    tail_obj, remaining = None, text
    if c.get("json_tail"):
        tails = [s for s in textio.fence_spans(text) if s[4] == "json"]
        if not tails:
            errors.append("no fenced ```json tail block found")
        else:
            a, b = tails[-1][0], tails[-1][1]
            end = len(lines) if b is None else b + 1
            remaining = "\n".join(lines[:a] + lines[end:])
            try:
                tail_obj = textio.loads_strict("\n".join(lines[a + 1:b if b is not None else end]))
            except ValueError as e:
                errors.append("json tail is not valid JSON: %s" % e)
            else:
                if isinstance(c["json_tail"], (dict, str)):
                    try:
                        schema = load_schema(c["json_tail"], run_dir)
                    except (ValueError, RecursionError) as e:
                        errors.append(str(e))
                    else:
                        errors.extend("json tail " + e for e in schema_lite.validate(tail_obj, schema))

    rem_lines = _nonempty_lines(remaining)
    final = rem_lines[-1].strip() if rem_lines else ""
    if c.get("final_line"):
        rx, err = _compile(c["final_line"])
        if err:
            errors.append(err)
        elif not rx.search(final):
            errors.append("final line %r does not match /%s/" % (final[:120], c["final_line"]))

    caps = c.get("max_words") or {}
    if isinstance(caps, dict):
        for head, cap in caps.items():
            k = None
            for idx, h in enumerate(heads):
                if _prefix_hit(h, head):
                    k = idx
                    break
            if k is None:
                if head not in [str(w) for w in wanted]:
                    errors.append("max_words: heading %r is missing" % head)
                continue
            n = _words(body_of(k))
            if isinstance(cap, int) and n > cap:
                errors.append("section %r has %d words, more than %d" % (head, n, cap))
    return errors, {"sections": sections, "json_tail": tail_obj, "final_line": final}


# an ID at the start of a card heading: letters and digits, then (after an optional '-') digits: I-001, E-02, Q-03
_CARD_ID_RE = re.compile(r"[A-Za-z][A-Za-z0-9]*-?\d+(?![A-Za-z0-9_-])")


def card_heading_id(htext, ids=None):
    """The card ID that the text of a '## ' heading names: the listed ID it is or starts with, a title may follow
    ('## I-001 - Nurse swap board' and '## I-001: Title' are the card of I-001); without `ids`, its leading ID token
    ('## Notes' names none). None for any other heading."""
    if ids is None:
        m = _CARD_ID_RE.match(htext)
        return m.group(0) if m else None
    for want in ids:
        if htext == want or re.match(re.escape(want) + r"(?![A-Za-z0-9_-])", htext):
            return want
    return None


def card_sections(text, ids=None):
    """[(card ID, [lines])] of text's cards in order (the `cards` contract's rule, 4.5): a '## ' heading outside fences
    whose text names a card ID (card_heading_id) opens a card, which runs to the next level-1 or level-2 heading; any
    other such heading only ends the card before it. The engine reads tournament/cards.md with the same rule
    (registry.parse_cards), so the cards the contract accepted are the ones the tournament ranks."""
    lines = (text or "").split("\n")
    heads = [i for i, level, _t in textio.headings(text) if level <= 2]
    out = []
    for k, i in enumerate(heads):
        cid = card_heading_id(lines[i].lstrip("#").strip(), ids) if lines[i].startswith("## ") else None
        if cid is not None:
            out.append((cid, lines[i + 1:heads[k + 1] if k + 1 < len(heads) else len(lines)]))
    return out


def _check_cards(text, c, run_dir):
    ids = [str(i) for i in (c.get("ids") or [])]
    prefixes = [str(p) for p in (c.get("lines") or [])]
    cards, counts = {}, {}
    for cid, body in card_sections(text, ids):
        counts[cid] = counts.get(cid, 0) + 1
        values = {}
        for ln in body:
            s = ln.strip()
            for p in prefixes:
                if p not in values and s.lower().startswith(p.lower()):
                    values[p] = s[len(p):].strip()
        cards[cid] = values
    errors = []
    for cid in ids:
        if cid not in cards:
            errors.append("card ## %s is missing" % cid)
            continue
        if counts.get(cid, 0) > 1:
            errors.append("card ## %s appears %d times" % (cid, counts[cid]))
        missing = [p for p in prefixes if p not in cards[cid]]
        if missing:
            errors.append("card %s lacks lines: %s" % (cid, ", ".join(missing)))
    return errors, cards


def _mermaid_types(content, relpath):
    types = []
    if relpath.lower().endswith(".mmd"):
        first = _nonempty_lines(content)
        if first:
            types.append(first[0].strip())
    for lang, body in textio.fenced_blocks(content):
        if lang == "mermaid":
            first = _nonempty_lines(body)
            if first:
                types.append(first[0].strip())
    return types


def _check_files(text, c, run_dir):
    files, status, warnings = filesproto.parse_file_blocks(text)
    allowed = c.get("allowed")
    errors = filesproto.structural_errors(warnings)
    errors += filesproto.validate_files(files, allowed if allowed is not None else None)
    for req in c.get("required") or []:
        if req not in files:
            errors.append("%s: required file missing" % req)
    per_file = c.get("per_file") if isinstance(c.get("per_file"), dict) else {}
    for rel, rules in per_file.items():
        if rel not in files or not isinstance(rules, dict):
            continue
        content = files[rel]
        heads = _headings(content)
        for want in rules.get("headings") or []:
            if not any(_prefix_hit(h, want) for h in heads):
                errors.append("%s: heading %r is missing" % (rel, want))
        mtypes = [t.lower() for t in _mermaid_types(content, rel)]
        for want in rules.get("mermaid") or []:
            w = str(want).lower()
            if not any(t == w or t.startswith(w + " ") or t.startswith(w + "\t") for t in mtypes):
                errors.append("%s: no mermaid %s block" % (rel, want))
    # .json files: strict JSON (validate_files reported the ones that do not parse), then the per_file or register
    # schema, so a malformed or wrong register earns the repair call instead of reaching the engine
    values = {}
    for rel, content in files.items():
        if not rel.lower().endswith(".json"):
            continue
        try:
            values[rel] = textio.loads_strict(content)
        except ValueError:
            continue
        rules = per_file.get(rel) if isinstance(per_file.get(rel), dict) else {}
        ref = rules.get("schema", REGISTER_SCHEMAS.get(rel))
        if ref is None:
            continue
        try:
            schema = load_schema(ref, run_dir)
        except (ValueError, RecursionError) as e:
            errors.append("%s: %s" % (rel, e))
            continue
        errors.extend("%s: %s" % (rel, e) for e in schema_lite.validate(values[rel], schema))
    if c.get("status_trailer"):
        if status is None:
            errors.append("STATUS trailer is missing or not valid JSON")
        elif status.get("status") not in filesproto.STATUS_VALUES:
            errors.append("STATUS status must be one of %s" % "|".join(filesproto.STATUS_VALUES))
    return errors, {"files": files, "status": status, "warnings": warnings, "json": values}


_CHECKERS = {
    "text": _check_text,
    "idea-blocks": _check_idea_blocks,
    "json": _check_json,
    "sections": _check_sections,
    "cards": _check_cards,
    "files": _check_files,
}


def check_contract(text, contract, run_dir):
    """Validate model output against a contract (4.5). Returns (ok, errors, parsed); never raises for bad output."""
    if isinstance(text, bytes):
        text = textio.decode_bytes(text)
    text = textio.normalize_newlines(text or "").lstrip("\ufeff")
    contract = contract or {"type": "text"}
    ctype = contract.get("type", "text")
    fn = _CHECKERS.get(ctype)
    if fn is None:
        return False, ["unknown contract type %r" % ctype], None
    if len(text.encode("utf-8")) > OUTPUT_CAP_BYTES:
        return False, ["output exceeds the 2 MB cap"], None
    if not text.strip():
        return False, ["output is empty"], None
    errors, parsed = fn(text, contract, run_dir)
    return (not errors), errors, parsed
