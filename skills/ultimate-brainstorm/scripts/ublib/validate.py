"""Output contracts (KIT_SPEC 4.5).

Frozen API (4.8):
    check_contract(text, contract, run_dir) -> (ok: bool, errors: list[str], parsed: object|None)

Extras: repair_prompt(errors, previous_output), load_schema(ref, run_dir), OUTPUT_CAP_BYTES, CONTRACT_TYPES.

Contract types: text, idea-blocks, json, sections, cards, files. `parsed` per type:
    text         the stripped text
    idea-blocks  [{"id", "title", "body"}] for the valid blocks
    json         the extracted JSON value
    sections     {"sections": {heading_prefix: body}, "json_tail": obj|None, "final_line": str}
    cards        {ID: {line_prefix: value}}
    files        {"files": {relpath: content}, "status": dict|None, "warnings": [...]}
"""

import json
import os
import re

from . import SK_DIR
from . import filesproto
from . import schema_lite
from . import textio

__all__ = ["check_contract", "repair_prompt", "load_schema", "OUTPUT_CAP_BYTES", "CONTRACT_TYPES", "REPAIR_MAX_CHARS"]

OUTPUT_CAP_BYTES = 2 * 1024 * 1024  # 5.4: larger output counts as invalid
REPAIR_MAX_CHARS = 1500
CONTRACT_TYPES = ("text", "idea-blocks", "json", "sections", "cards", "files")


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


def _mask_fences(lines):
    """Per line: True when the line is inside (or is a delimiter of) a fenced code block."""
    inside, fence, mask = False, None, []
    for ln in lines:
        s = ln.strip()
        if not inside:
            m = re.match(r"^(`{3,}|~{3,})", s)
            if m:
                inside, fence = True, m.group(1)
                mask.append(True)
                continue
            mask.append(False)
        else:
            mask.append(True)
            if s.startswith(fence) and s.strip("`~") == "":
                inside, fence = False, None
    return mask


_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")


def _headings(lines, mask):
    """[(line_index, level, full_line_normalized, text_normalized)] for headings outside fences."""
    out = []
    for i, ln in enumerate(lines):
        if mask[i]:
            continue
        m = _HEADING_RE.match(ln.rstrip())
        if m:
            text = " ".join(m.group(2).split())
            out.append((i, len(m.group(1)), (m.group(1) + " " + text).lower(), text.lower()))
    return out


def _prefix_hit(heading, prefix):
    p = " ".join(str(prefix).split()).lower()
    if p.startswith("#"):
        return heading[2].startswith(p)
    return heading[3].startswith(p)


def _words(text):
    lines = text.split("\n")
    mask = _mask_fences(lines)
    return sum(len(re.findall(r"\S+", ln)) for i, ln in enumerate(lines) if not mask[i])


_JSON_FENCE_RE = re.compile(r"^[ \t]*(`{3,}|~{3,})[ \t]*json[^\n]*\n(.*?)^[ \t]*\1[ \t]*$",
                            re.MULTILINE | re.DOTALL | re.IGNORECASE)


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


_BLOCK_LINES = (("Pitch", re.compile(r"^\s*[-*]\s*(?:\*\*)?Pitch(?:\*\*)?\s*:", re.I | re.M)),
                ("Mechanism", re.compile(r"^\s*[-*]\s*(?:\*\*)?Mechanism(?:\*\*)?\s*:", re.I | re.M)),
                ("Fails if", re.compile(r"^\s*[-*]\s*(?:\*\*)?Fails if(?:\*\*)?\s*:", re.I | re.M)))


def _check_idea_blocks(text, c, run_dir):
    prefix = str(c.get("prefix") or "").strip()
    need = c.get("min", 1)
    need = need if isinstance(need, int) else 1
    if not prefix:
        return ["contract idea-blocks has no prefix"], None
    head_rx = re.compile(r"^###\s+(%s-\d+)[:.)]?\s+(\S.*)$" % re.escape(prefix))
    lines = text.split("\n")
    mask = _mask_fences(lines)
    starts = []
    for i, ln in enumerate(lines):
        if mask[i]:
            continue
        if re.match(r"^#{1,6}\s", ln):
            m = head_rx.match(ln.rstrip())
            starts.append((i, m))
    blocks, problems, seen = [], [], set()
    for k, (i, m) in enumerate(starts):
        if not m:
            continue
        end = starts[k + 1][0] if k + 1 < len(starts) else len(lines)
        body = "\n".join(lines[i + 1:end])
        missing = [name for name, rx in _BLOCK_LINES if not rx.search(body)]
        bid = m.group(1)
        if missing:
            problems.append("%s lacks %s" % (bid, ", ".join("- %s:" % n for n in missing)))
            continue
        if bid in seen:
            problems.append("%s appears more than once" % bid)
            continue
        seen.add(bid)
        blocks.append({"id": bid, "title": m.group(2).strip(), "body": body.strip("\n")})
    errors = []
    if len(blocks) < need:
        errors.append("found %d valid %s-NN idea blocks, need at least %d (heading '### %s-NN <title>' with "
                      "'- Pitch:', '- Mechanism:' and '- Fails if:' lines)" % (len(blocks), prefix, need, prefix))
        errors.extend(problems[:10])
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


def _check_cover(value, cover):
    errors = []
    if not isinstance(cover, dict):
        return errors
    arr_name, key, ids = cover.get("array"), cover.get("key", "id"), cover.get("ids") or []
    arr = _get_path(value, arr_name)
    if not isinstance(arr, list):
        return ["cover: %s is not an array" % (arr_name or "$")]
    present = set()
    for item in arr:
        if isinstance(item, dict) and key in item:
            present.add(str(item[key]))
    missing = [str(i) for i in ids if str(i) not in present]
    if missing:
        errors.append("cover: %s is missing %s %s" % (arr_name or "$", key, ", ".join(missing[:30])))
    return errors


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
    return errors, value


def _check_sections(text, c, run_dir):
    errors = []
    lines = text.split("\n")
    mask = _mask_fences(lines)
    heads = _headings(lines, mask)
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
        blocks = list(_JSON_FENCE_RE.finditer(text))
        if not blocks:
            errors.append("no fenced ```json tail block found")
        else:
            last = blocks[-1]
            remaining = text[:last.start()] + text[last.end():]
            try:
                tail_obj = json.loads(last.group(2).strip())
            except (ValueError, RecursionError) as e:
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


def _check_cards(text, c, run_dir):
    ids = [str(i) for i in (c.get("ids") or [])]
    prefixes = [str(p) for p in (c.get("lines") or [])]
    lines = text.split("\n")
    mask = _mask_fences(lines)
    heads = []  # (index, heading text) for level 1-2 headings
    for i, ln in enumerate(lines):
        if not mask[i] and re.match(r"^#{1,2}\s", ln):
            heads.append((i, ln.lstrip("#").strip()))
    cards, counts = {}, {}
    for k, (i, htext) in enumerate(heads):
        if not lines[i].startswith("## "):
            continue
        cid = None
        for want in ids:
            if htext == want or re.match(re.escape(want) + r"(?![A-Za-z0-9_-])", htext):
                cid = want
                break
        if cid is None:
            continue
        counts[cid] = counts.get(cid, 0) + 1
        end = heads[k + 1][0] if k + 1 < len(heads) else len(lines)
        values = {}
        for ln in lines[i + 1:end]:
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
    per_file = c.get("per_file") or {}
    if isinstance(per_file, dict):
        for rel, rules in per_file.items():
            if rel not in files or not isinstance(rules, dict):
                continue
            content = files[rel]
            lines = content.split("\n")
            heads = _headings(lines, _mask_fences(lines))
            for want in rules.get("headings") or []:
                if not any(_prefix_hit(h, want) for h in heads):
                    errors.append("%s: heading %r is missing" % (rel, want))
            mtypes = [t.lower() for t in _mermaid_types(content, rel)]
            for want in rules.get("mermaid") or []:
                w = str(want).lower()
                if not any(t == w or t.startswith(w + " ") or t.startswith(w + "\t") for t in mtypes):
                    errors.append("%s: no mermaid %s block" % (rel, want))
    if c.get("status_trailer"):
        if status is None:
            errors.append("STATUS trailer is missing or not valid JSON")
        elif status.get("status") not in filesproto.STATUS_VALUES:
            errors.append("STATUS status must be one of %s" % "|".join(filesproto.STATUS_VALUES))
    return errors, {"files": files, "status": status, "warnings": warnings}


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
