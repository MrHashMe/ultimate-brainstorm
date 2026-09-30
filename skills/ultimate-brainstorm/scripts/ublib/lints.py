"""Lint rules for the architecture package, the proposal and the frame (KIT_SPEC 5.8).

Frozen API (4.8):
    lint_arch(run_dir, lite=False) -> dict        writes 10_ARCHITECTURE/lint.md + lint.json
    lint_proposal(run_dir, lite=False) -> dict    writes 11_PROPOSAL/lint.md + lint.json
    lint_frame(run_dir) -> dict                   writes frame/lint.json (+ frame/lint.md); warnings only

Each returns {"status": "pass|warn|fail", "items": [{"id", "severity", "file", "message"}], ...}.
`severity` is "fail" or "warn" (lowercase, like `status`). Extra keys: "rules" (rule ids checked), "lite", "scope".

Shared helpers that bs.py also uses (not frozen): extract_assumptions, norm_assumption, placeholder_hits,
parse_table, fence_mask, mermaid_blocks.
"""

import os
import re

from . import textio

__all__ = ["lint_arch", "lint_proposal", "lint_frame", "extract_assumptions", "norm_assumption",
           "placeholder_hits", "parse_table", "fence_mask", "mermaid_blocks", "word_count"]

ARCH_DIR = "10_ARCHITECTURE"
PROPOSAL_DIR = "11_PROPOSAL"

# A1: (path, required in --lite)
ARCH_REQUIRED = (
    ("README.md", True), ("goals-constraints.md", True), ("quality-scenarios.md", True), ("context.md", True),
    ("tradeoff-matrix.md", False), ("chosen/containers.md", True), ("chosen/runtime.md", False),
    ("chosen/data-model.md", True), ("chosen/deployment.md", False), ("chosen/security-privacy.md", False),
    ("chosen/cost-model.md", False), ("chosen/stack.md", True), ("chosen/deferred.md", False), ("risks.md", True),
)
ARCH_RULES = ("A1", "A2", "A3", "A4", "A5", "A6", "A7", "A8", "A9")
PROPOSAL_RULES = ("P1", "P2", "P3", "P4", "P5", "P6", "P7", "P8", "P9", "P10")
FRAME_RULES = ("F1", "F2", "F3", "F4")

# P1: (key, heading prefixes accepted, required in --lite)
PROPOSAL_HEADINGS = (
    ("1", ("## 1. Executive Summary",), True),
    ("2", ("## 2. Problem and Evidence",), True),
    ("3", ("## 3. Solution",), True),
    ("4", ("## 4. Users and Market",), False),
    ("5", ("## 5. Differentiation vs Prior Art",), False),
    ("6", ("## 6. Architecture Summary", "## 6. Approach"), True),
    ("7", ("## 7. Scope and MVP",), True),
    ("8", ("## 8. Roadmap and Milestones",), False),
    ("9", ("## 9. Team and Effort",), False),
    ("10", ("## 10. Budget and Cost",), False),
    ("11", ("## 11. Risks and Mitigations",), True),
    ("12", ("## 12. Success Metrics and Validation Plan",), True),
    ("13", ("## 13. Open Questions",), True),
    ("A", ("## Appendix A. ADR Index",), True),
    ("B", ("## Appendix B. Assumptions Index",), True),
    ("C", ("## Appendix C. Candidate Comparison",), False),
    ("D", ("## Appendix D. Idea Selection Record",), False),
    ("E", ("## Appendix E. Glossary",), False),
    ("F", ("## Appendix F. Sources",), True),
)

# v1 P-FRAME sections of 01_FRAME.md (Domain language is optional: software/growth only)
FRAME_SECTIONS = ("# FRAME", "## Job statement", "## Problem", "## Audience", "## Success looks like",
                  "## Hard constraints", "## Soft constraints", "## Non-goals", "## Decision ledger", "## Premises",
                  "## Kill condition", "## Criteria", "## Kill rules", "## Axes", "## Strategy plan",
                  "## Mode, privacy, budget")

MERMAID_TYPES = ("C4Context", "C4Container", "C4Component", "C4Dynamic", "C4Deployment", "flowchart", "graph",
                 "sequenceDiagram", "erDiagram", "stateDiagram-v2", "classDiagram")

_PLACEHOLDERS = (
    ("TODO", re.compile(r"\bTODO\b")),
    ("TBD", re.compile(r"\bTBD\b")),
    ("XXX", re.compile(r"\bXXX\b")),
    ("lorem", re.compile(r"\blorem\b", re.I)),
    ("{{", re.compile(r"\{\{")),
    # a placeholder stands alone; a type argument follows its type's name (list<string>, Promise<void>, Vec<u8>)
    ("<...>", re.compile(r"(?<![A-Za-z0-9_])<([a-z][a-z0-9 _-]{1,40})>")),
)
# Plain HTML tags that Markdown writers use legitimately (GFM tables); never placeholders.
_HTML_OK = {"br", "hr", "b", "i", "u", "em", "strong", "sup", "sub", "code", "kbd", "p", "details", "summary"}
_INLINE_CODE = re.compile(r"`[^`\n]*`")
_SOLUTION_RE = re.compile(r"\b(an?|the) (app|platform|tool|bot|AI assistant|marketplace|dashboard) (that|to|for)\b",
                          re.I)
# a tag text is at most 2000 characters (_SENTENCE_MAX) after the blanks that follow the colon; the text starts with a
# non-blank and the closing blanks belong to it, so no two blank runs compete and a line of unclosed tags stays linear
_ASSUMPTION_COLON = re.compile(r"\[ASSUMPTION:[^\S\n]*(?:([^\]\s](?:[^\]\n]{0,1998}[^\]\s])?)[^\S\n]*)?\]", re.I)
_ASSUMPTION_BARE = re.compile(r"\[ASSUMPTION\]", re.I)
_ESTIMATE_COLON = re.compile(r"\[ESTIMATE:[^\S\n]*(?:([^\]\s](?:[^\]\n]{0,1998}[^\]\s])?)[^\S\n]*)?\]", re.I)
_SENT_END = re.compile(r"(?<=[.!?])\s+")
_ID_TOKENS = re.compile(r"\[?\b(?:[A-Z]{1,6}-\d+|QG\d+|QAS-\d+)\b\]?")


# ---------------------------------------------------------------- small text helpers

def _read(path):
    try:
        return textio.read_text(path)
    except (OSError, ValueError):
        return None


def fence_mask(lines):
    """One bool per line: True when the line is part of a fenced code block (fence lines included)."""
    return textio.fence_mask(lines)


def _unfenced(text):
    lines = (text or "").split("\n")
    mask = fence_mask(lines)
    return "\n".join("" if m else line for line, m in zip(lines, mask))


def word_count(text):
    """Words outside fenced code blocks; heading and list markers are not words."""
    body = _unfenced(text)
    body = re.sub(r"^[ \t]*#{1,6}\s", " ", body, flags=re.M)
    return len([w for w in re.findall(r"\S+", body) if re.search(r"\w", w)])


def _headings(text):
    """[(level, title, line_index)] outside fences (textio.headings: one linear scanner)."""
    return [(level, title, i) for i, level, title in textio.headings(text or "")]


def _norm_heading(s):
    return " ".join(s.lower().split())


def _heading_matches(level, title, prefix):
    """prefix like '## 1. Executive Summary' (level from the hashes) matched case-insensitively."""
    m = re.match(r"^(#+)\s*(.*)$", prefix)
    want_level, want = (len(m.group(1)), m.group(2)) if m else (None, prefix)
    if want_level is not None and level != want_level:
        return False
    return _norm_heading(title).startswith(_norm_heading(want))


def _section(text, prefix):
    """Body (without the heading line) of the first heading matching prefix, up to the next heading of the same or
    a higher level. None when absent."""
    lines = (text or "").split("\n")
    heads = _headings(text)
    for n, (level, title, idx) in enumerate(heads):
        if _heading_matches(level, title, prefix):
            end = len(lines)
            for level2, _t, idx2 in heads[n + 1:]:
                if level2 <= level:
                    end = idx2
                    break
            return "\n".join(lines[idx + 1:end])
    return None


def parse_table(lines_or_text, start=0):
    """Parse the first GFM table at or after `start`. Returns (header_cells, rows, next_index) or (None, [], i)."""
    lines = lines_or_text.split("\n") if isinstance(lines_or_text, str) else lines_or_text
    i = start
    while i < len(lines) and not lines[i].strip().startswith("|"):
        i += 1
    if i >= len(lines):
        return None, [], i
    header = _cells(lines[i])
    rows = []
    i += 1
    while i < len(lines) and lines[i].strip().startswith("|"):
        if not _is_separator(lines[i]):
            cells = _cells(lines[i])
            if any(cells):
                rows.append(cells)
        i += 1
    return header, rows, i


def _cells(line):
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|") and not s.endswith("\\|"):
        s = s[:-1]
    parts = re.split(r"(?<!\\)\|", s)
    return [p.strip() for p in parts]


def _is_separator(line):
    cells = _cells(line)
    return bool(cells) and all(re.match(r"^:?-+:?$", c) for c in cells if c) and any(cells)


def placeholder_hits(text):
    """[(line_no 1-based, token, snippet)] for placeholders outside code fences and inline code (rule A2)."""
    lines = (text or "").split("\n")
    mask = fence_mask(lines)
    hits = []
    for n, (line, m) in enumerate(zip(lines, mask), 1):
        if m:
            continue
        plain = _INLINE_CODE.sub("", line)
        for name, rx in _PLACEHOLDERS:
            for hit in rx.finditer(plain):
                if name == "<...>" and hit.group(1).strip() in _HTML_OK:
                    continue
                hits.append((n, name, hit.group(0)))
    return hits


def mermaid_blocks(text):
    """[(first_line_no 1-based, body_lines)] of every ```mermaid block (a fence left open runs to the end)."""
    lines = (text or "").split("\n")
    return [(a + 1, lines[a + 1:len(lines) if b is None else b])
            for a, b, _c, _n, lang in textio.fence_spans(text or "") if lang == "mermaid"]


def _mermaid_type(body):
    lines = [ln for ln in body]
    k = 0
    # skip an optional '---' frontmatter block and '%%' comments
    while k < len(lines) and not lines[k].strip():
        k += 1
    if k < len(lines) and lines[k].strip() == "---":
        k += 1
        while k < len(lines) and lines[k].strip() != "---":
            k += 1
        k += 1
    while k < len(lines) and (not lines[k].strip() or lines[k].strip().startswith("%%")):
        k += 1
    if k >= len(lines):
        return None, ""
    first = lines[k].strip()
    word = re.split(r"[\s;]", first, maxsplit=1)[0]
    return (word if word in MERMAID_TYPES else None), first


def _norm_space(s):
    return " ".join(str(s).split())


def norm_assumption(text):
    """Comparison key for assumption texts (P8 and bs.py assumptions share it)."""
    s = _norm_space(str(text).replace("|", "/")).lower()
    return s.rstrip(" .;:,")


# the window a bare [ASSUMPTION] tag reads on each side: a longer 'sentence' is no sentence, and the bound keeps a line
# of many tags linear
_SENTENCE_MAX = 2000


def _clip_sentence(s):
    s = s.split("|")[0]
    parts = _SENT_END.split(s.strip(), 1)
    return parts[0].strip() if parts else ""


def extract_assumptions(text):
    """[(kind, text, line_no)] for [ASSUMPTION: x], [ASSUMPTION] <sentence> and [ESTIMATE: range; basis].

    A bare [ASSUMPTION] tag takes the sentence after it when one follows (3+ words starting with a capital, digit or
    quote); otherwise the tag closes a claim and it takes the sentence before it instead. kind is "assumption" or
    "estimate".
    """
    out = []
    for n, line in enumerate((text or "").split("\n"), 1):
        for m in _ASSUMPTION_COLON.finditer(line):
            t = _norm_space(m.group(1) or "")
            if t:
                out.append(("assumption", t, n))
        for m in _ESTIMATE_COLON.finditer(line):
            t = _norm_space(m.group(1) or "")
            if t:
                out.append(("estimate", "ESTIMATE: " + t, n))
        for m in _ASSUMPTION_BARE.finditer(line):
            after = _clip_sentence(line[m.end():m.end() + _SENTENCE_MAX])
            after = re.sub(r"^[\s:,-]+", "", after)
            # "[ASSUMPTION] <sentence>": a new sentence follows (capital, digit or quote). Otherwise the tag closes
            # the claim before it ("X happens [ASSUMPTION] and ...").
            if len(re.findall(r"\w+", after)) >= 3 and re.match(r"^[A-Z0-9\"'$(]", after):
                out.append(("assumption", _norm_space(after), n))
                continue
            before = line[max(0, m.start() - _SENTENCE_MAX):m.start()]
            before = before.split("|")[-1] if "|" in before else before
            pieces = _SENT_END.split(before.strip())
            prev = pieces[-1] if pieces else ""
            prev = re.sub(r"^\s*(?:[-*+]|\d+[.)])\s+", "", prev)
            prev = _norm_space(re.sub(r"\[(?:S-\d{3}|ESTIMATE[^\]]*)\]", "", prev))
            if prev:
                out.append(("assumption", prev, n))
    return out


# ---------------------------------------------------------------- results

def _item(rule, severity, path, message):
    return {"id": rule, "severity": severity, "file": path, "message": message}


def _status(items):
    if any(i["severity"] == "fail" for i in items):
        return "fail"
    if any(i["severity"] == "warn" for i in items):
        return "warn"
    return "pass"


def _write_report(out_dir, title, result, write_md=True):
    counts = {s: sum(1 for i in result["items"] if i["severity"] == s) for s in ("fail", "warn")}
    lines = ["# Lint: %s" % title, "",
             "Status: %s (%d FAIL, %d WARN). Rules checked: %s." % (
                 result["status"].upper(), counts["fail"], counts["warn"], ", ".join(result["rules"])), ""]
    if result["items"]:
        lines += ["| rule | severity | file | message |", "|---|---|---|---|"]
        for i in result["items"]:
            lines.append("| %s | %s | %s | %s |" % (i["id"], i["severity"].upper(), i["file"] or "-",
                                                    _norm_space(i["message"]).replace("|", "/")))
    else:
        lines.append("No findings.")
    os.makedirs(out_dir, exist_ok=True)
    textio.write_json_atomic(os.path.join(out_dir, "lint.json"), result)
    if write_md:
        textio.write_text_atomic(os.path.join(out_dir, "lint.md"), "\n".join(lines) + "\n")


def _rel(base, path):
    return os.path.relpath(path, base).replace("\\", "/")


# ---------------------------------------------------------------- lint-arch

def _arch_doc_files(arch):
    """The package documents that A2 and A5 check (not raw candidate outputs, review sheets or _raw/)."""
    files = []
    for name in ("README.md", "goals-constraints.md", "quality-scenarios.md", "context.md", "tradeoff-matrix.md",
                 "risks.md", "premortem.md"):
        p = os.path.join(arch, name)
        if os.path.isfile(p):
            files.append(p)
    for pattern in ("chosen/*.md", "chosen/**/*.md", "adr/*.md"):
        for p in sorted(textio.glob_in(arch, *pattern.split("/"), recursive=True)):
            if os.path.isfile(p) and p not in files:
                files.append(p)
    return files


def _adr_files(arch):
    return sorted(p for p in textio.glob_in(arch, "adr", "*.md")
                  if re.match(r"^\d{4}-.+\.md$", os.path.basename(p)))


def _ids(pattern, text):
    seen, out = set(), []
    for m in re.finditer(pattern, text or ""):
        if m.group(0) not in seen:
            seen.add(m.group(0))
            out.append(m.group(0))
    return out


def _risk_ids(arch):
    text = _read(os.path.join(arch, "risks.md")) or ""
    return set(re.findall(r"\bR-\d{3}\b", text))


def _check_adr(path, text, risk_ids, rel):
    items = []
    fm = re.match(r"^\ufeff?---[ \t]*\n(.*?)\n---[ \t]*(?:\n|$)", text, re.S)
    if not fm:
        items.append(_item("A3", "fail", rel, "no frontmatter (--- status: / date: ---)"))
    else:
        for key in ("status", "date"):
            if not re.search(r"^%s:[ \t]*\S" % key, fm.group(1), re.M):
                items.append(_item("A3", "fail", rel, "frontmatter lacks '%s:'" % key))
    heads = _headings(text)
    for level, want in ((2, "Context and Problem Statement"), (2, "Decision Drivers"), (2, "Considered Options"),
                        (2, "Decision Outcome"), (3, "Consequences"), (3, "Confirmation")):
        if not any(lv == level and _norm_heading(t).startswith(want.lower()) for lv, t, _i in heads):
            items.append(_item("A3", "fail", rel, "missing heading '%s %s'" % ("#" * level, want)))
    opts = _section(text, "## Considered Options")
    if opts is not None:
        bullets = [ln for ln in opts.split("\n") if re.match(r"^\s*(?:[-*+]|\d+[.)])\s+\S", ln)]
        if len(bullets) < 2:
            items.append(_item("A3", "fail", rel, "Considered Options lists %d option(s); at least 2 needed"
                               % len(bullets)))
    missing = sorted(set(re.findall(r"\bR-\d{3}\b", text)) - risk_ids)
    if missing:
        items.append(_item("A3", "fail", rel, "cites risks not in risks.md: " + ", ".join(missing)))
    return items


def unpinned_version(v):
    """True for a stack version that pins nothing: empty, '-', 'n/a', 'none', '?' or anything starting with 'latest'
    ('latest (managed service)'). The renderer shows such a version as UNVERIFIED (render_arch._version) and lint A4
    fails one it finds in a table, so a rendered chosen/stack.md never fails A4 on a verifier's wording."""
    s = str(v or "").strip().lower()
    return s in ("", "-", "n/a", "none", "?") or s.startswith("latest")


def _check_stack(text, rel):
    lines = text.split("\n")
    mask = fence_mask(lines)
    lines = ["" if m else ln for ln, m in zip(lines, mask)]
    i = 0
    while i < len(lines):
        header, rows, nxt = parse_table(lines, i)
        if header is None:
            break
        low = [h.lower() for h in header]
        vcol = next((k for k, h in enumerate(low) if "version" in h), None)
        if vcol is None:
            i = nxt
            continue
        scol = next((k for k, h in enumerate(low) if h == "status"), None)
        items, unverified = [], 0
        for n, row in enumerate(rows, 1):
            ver = row[vcol].strip() if vcol < len(row) else ""
            stat = row[scol].strip() if scol is not None and scol < len(row) else ""
            name = " / ".join(c for c in row[:3] if c) or "row %d" % n
            if unpinned_version(ver):
                items.append(_item("A4", "fail", rel, "no pinned version for '%s' (got '%s')" % (name, ver or "")))
            elif re.search(r"UNVERIFIED|TO[- ]VERIFY|NOT SEARCHED", ver + " " + stat, re.I):
                unverified += 1
        if unverified:
            items.append(_item("A4", "warn", rel, "%d stack row(s) UNVERIFIED or TO-VERIFY" % unverified))
        if not rows:
            items.append(_item("A4", "fail", rel, "stack table has no rows"))
        return items
    return [_item("A4", "fail", rel, "no table with a version column")]


# erDiagram relationship tokens such as ||--o{ or }|..|| use braces as cardinality marks, not brackets
_ER_REL = re.compile(r"[|}o]{1,2}(?:--|\.\.)[|{o]{1,2}")


def _balanced(line, braces=True):
    pairs = (("(", ")"), ("[", "]"), ("{", "}")) if braces else (("(", ")"), ("[", "]"))
    for a, b in pairs:
        if line.count(a) != line.count(b):
            return False
    return line.count('"') % 2 == 0


def _check_mermaid(text, rel):
    """A5. (), [] and quotes must balance on every line. Braces must balance on every line too, except in the
    diagram types whose syntax opens a { block on one line and closes it on a later one (erDiagram entities,
    classDiagram classes, stateDiagram-v2 composite states): there they must balance over the whole block, after
    erDiagram cardinality tokens are removed."""
    items = []
    blocks = mermaid_blocks(text)
    types = []
    for start, body in blocks:
        mtype, first = _mermaid_type(body)
        types.append(mtype)
        if mtype is None:
            items.append(_item("A5", "fail", rel, "mermaid block at line %d: unknown diagram type '%s'"
                               % (start, first[:40])))
        for k, line in enumerate(body, 1):
            if "\t" in line:
                items.append(_item("A5", "fail", rel, "mermaid block at line %d: tab character on line %d"
                                   % (start, start + k)))
                break
        block_braces = mtype in ("erDiagram", "classDiagram", "stateDiagram-v2")
        opened = closed = 0
        for k, line in enumerate(body, 1):
            if line.strip().startswith("%%"):
                continue
            if mtype == "erDiagram":
                line = _ER_REL.sub(" ", line)
            if block_braces:
                opened += line.count("{")
                closed += line.count("}")
            if not _balanced(line, braces=not block_braces):
                items.append(_item("A5", "fail", rel, "mermaid block at line %d: unbalanced brackets or quotes on "
                                   "line %d" % (start, start + k)))
                break
        if block_braces and opened != closed:
            items.append(_item("A5", "fail", rel, "mermaid block at line %d: unbalanced braces ({ %d vs } %d)"
                               % (start, opened, closed)))
    for n, t in enumerate(types):
        if t and t.startswith("C4") and not any(u in ("flowchart", "graph") for u in types[n + 1:]):
            items.append(_item("A5", "fail", rel, "%s block (line %d) has no flowchart/graph fallback after it"
                               % (t, blocks[n][0])))
    return items


def _deferred_names(arch):
    text = _read(os.path.join(arch, "chosen", "deferred.md")) or ""
    return text.lower()


def lint_arch(run_dir, lite=False):
    """Rules A1-A9 over RUN/10_ARCHITECTURE. Writes lint.md and lint.json there."""
    run_dir = os.path.abspath(os.fspath(run_dir))
    arch = os.path.join(run_dir, ARCH_DIR)
    items = []
    texts = {}

    def get(rel):
        if rel not in texts:
            texts[rel] = _read(os.path.join(arch, *rel.split("/")))
        return texts[rel]

    # A1 required files
    for rel, in_lite in ARCH_REQUIRED:
        if lite and not in_lite:
            continue
        if not os.path.isfile(os.path.join(arch, *rel.split("/"))):
            items.append(_item("A1", "fail", rel, "required file missing"))
    adrs = _adr_files(arch)
    if not adrs:
        items.append(_item("A1", "fail", "adr/", "no adr/NNNN-*.md file"))

    # A2 placeholders
    for path in _arch_doc_files(arch):
        hits = placeholder_hits(get(_rel(arch, path)) or "")
        if hits:
            shown = "; ".join("line %d %s" % (n, snip) for n, _k, snip in hits[:3])
            items.append(_item("A2", "fail", _rel(arch, path), "%d placeholder(s): %s" % (len(hits), shown)))

    # A3 ADRs
    risk_ids = _risk_ids(arch)
    for path in adrs:
        items += _check_adr(path, get(_rel(arch, path)) or "", risk_ids, _rel(arch, path))

    # A4 stack table
    stack = get("chosen/stack.md")
    if stack is not None:
        items += _check_stack(stack, "chosen/stack.md")

    # A5 mermaid
    for path in _arch_doc_files(arch):
        items += _check_mermaid(get(_rel(arch, path)) or "", _rel(arch, path))

    # A6 traceability
    items += _a6(arch, get, lite)

    # A7 cross-cutting documents
    deferred = _deferred_names(arch)
    for rel in ("chosen/deployment.md", "chosen/security-privacy.md", "chosen/cost-model.md"):
        stem = rel.split("/")[-1][:-3]
        text = get(rel)
        is_deferred = bool(re.search(r"(?<![\w-])%s(?:\.md)?(?![\w-])" % re.escape(stem), deferred))
        if text is None:
            if not lite and not is_deferred:
                pass  # already reported by A1
            continue
        if is_deferred:
            continue
        n = word_count(text)
        if n < 120:
            items.append(_item("A7", "fail", rel, "%d words (at least 120, or name it in chosen/deferred.md)" % n))
        if rel.endswith("cost-model.md"):
            assum = _section(text, "## Assumptions")
            if assum is None or not re.search(r"^[ \t]*\|", assum, re.M):
                items.append(_item("A7", "fail", rel, "no '## Assumptions' table"))
            has_sens = any("sensitivity" in t.lower() for _l, t, _i in _headings(text)) or \
                re.search(r"^[ \t]*\|.*sensitivity", _unfenced(text), re.I | re.M)
            if not has_sens:
                items.append(_item("A7", "fail", rel, "no Sensitivity heading or row"))

    # A8 risks
    risks = get("risks.md")
    if risks is not None:
        heads = _headings(risks)
        for want in ("Risks", "Technical debt"):
            if not any(lv == 2 and _norm_heading(t).startswith(want.lower()) for lv, t, _i in heads):
                items.append(_item("A8", "fail", "risks.md", "missing heading '## %s'" % want))
        seen, dups = set(), []
        for line in _unfenced(risks).split("\n"):
            m = re.match(r"^\s*\|\s*(R-\d{3})\s*\|", line)
            if m:
                if m.group(1) in seen and m.group(1) not in dups:
                    dups.append(m.group(1))
                seen.add(m.group(1))
        if dups:
            items.append(_item("A8", "fail", "risks.md", "duplicate risk ids: " + ", ".join(dups)))

    # A9 README decision index
    readme = get("README.md")
    if readme is not None:
        listed = set(re.findall(r"\bADR-(\d{4})\b", readme)) | set(re.findall(r"adr/(\d{4})-", readme))
        actual = {os.path.basename(p)[:4] for p in adrs}
        if listed != actual:
            parts = []
            if actual - listed:
                parts.append("not listed: " + ", ".join("ADR-" + x for x in sorted(actual - listed)))
            if listed - actual:
                parts.append("listed but no file: " + ", ".join("ADR-" + x for x in sorted(listed - actual)))
            items.append(_item("A9", "warn", "README.md", "decision index does not match adr/ (%s)"
                               % "; ".join(parts)))

    result = {"status": _status(items), "items": items, "rules": list(ARCH_RULES), "lite": bool(lite),
              "scope": ARCH_DIR}
    _write_report(arch, "architecture (%s%s)" % (ARCH_DIR, ", lite" if lite else ""), result)
    return result


def _a6(arch, get, lite):
    items = []
    drivers_path = os.path.join(arch, "drivers.json")
    qgs = []
    if os.path.isfile(drivers_path):
        try:
            drivers = textio.read_json(drivers_path)
            qgs = [str(q.get("id")) for q in drivers.get("quality_goals", []) if isinstance(q, dict) and q.get("id")]
        except (OSError, ValueError, AttributeError):
            items.append(_item("A6", "fail", "drivers.json", "unreadable"))
    else:
        items.append(_item("A6", "fail", "drivers.json", "missing: quality goals cannot be traced"))
    readme = get("README.md") or ""
    containers = get("chosen/containers.md")
    how = (_section(containers or "", "## How each quality goal is met") or "") if containers else ""
    for qg in qgs:
        rx = r"(?<![\w-])%s(?![\w-])" % re.escape(qg)
        if not re.search(rx, readme) and not re.search(rx, how):
            items.append(_item("A6", "fail", "chosen/containers.md",
                               "quality goal %s appears neither in README.md nor in 'How each quality goal is met'"
                               % qg))
    context = get("context.md")
    if context is not None and containers is not None:
        for ext in _ids(r"\bEXT-\d+\b", context):
            if not re.search(r"\b%s\b" % re.escape(ext), containers):
                items.append(_item("A6", "fail", "chosen/containers.md", "%s (from context.md) not mentioned" % ext))
    runtime = get("chosen/runtime.md")
    if runtime is None:
        if lite:
            return items
        return items  # A1 reports the missing file
    if containers is not None:
        missing = [c for c in _ids(r"\bC-\d+\b", containers) if not re.search(r"\b%s\b" % re.escape(c), runtime)]
        if missing:
            items.append(_item("A6", "fail", "chosen/runtime.md", "containers never used in a runtime flow: "
                               + ", ".join(missing)))
    if not any(lv == 2 and re.match(r"^F-", t) and re.search(r"failure|recovery", t, re.I)
               for lv, t, _i in _headings(runtime)):
        items.append(_item("A6", "fail", "chosen/runtime.md", "no '## F-n Failure and recovery' flow"))
    return items


# ---------------------------------------------------------------- lint-proposal

def _paragraph_units(body):
    """Sentences (and table rows / list items as units) of a section body, skipping fences and headings."""
    lines = body.split("\n")
    mask = fence_mask(lines)
    units, para = [], []

    def flush():
        if para:
            text = " ".join(p.strip() for p in para)
            units.extend(s for s in _SENT_END.split(text) if s.strip())
            del para[:]

    for line, m in zip(lines, mask):
        s = line.strip()
        if m or not s or re.match(r"^#{1,6}\s", s):
            flush()
            continue
        if s.startswith("|"):
            flush()
            if not _is_separator(s):
                units.append(s)
            continue
        if re.match(r"^(?:[-*+]|\d+[.)])\s+", s):
            flush()
        para.append(re.sub(r"^(?:[-*+]|\d+[.)])\s+", "", s))
    flush()
    return units


def _needs_source(unit):
    plain = _ID_TOKENS.sub(" ", unit)
    plain = re.sub(r"\xa7\s*\d+", " ", plain)
    if not re.search(r"[\d%$]", plain):
        return False
    return not re.search(r"\[S-\d{3}\]|https?://|\[ASSUMPTION|\[ESTIMATE", unit, re.I)


def _dollar_figures(text):
    return [m.group(0) for m in re.finditer(r"\$\s?\d[\d,]*(?:\.\d+)?(?:\s?[kKmMbB]\b)?", text)]


def _norm_money(s):
    return re.sub(r"[\s,]", "", s).lower()


def _open_question_problems(body):
    """P7: every open question (list item or table row) names an owner and a decide-by point.

    List items need the labels 'Owner:' and 'Decide by:'. A table with 'owner' and 'decide by' columns needs both
    cells filled on every row; any other table row needs both labels in its text.
    """
    lines = ["" if m else ln for ln, m in zip(body.split("\n"), fence_mask(body.split("\n")))]
    bad, cur = [], None

    def check_item(text):
        if not re.search(r"owner\s*:", text, re.I) or not re.search(r"decide\s*by\s*:", text, re.I):
            bad.append(_norm_space(text))

    i = 0
    while i < len(lines):
        s = lines[i].strip()
        if s.startswith("|"):
            if cur is not None:
                check_item(cur)
                cur = None
            header, rows, i = parse_table(lines, i)
            low = [h.lower() for h in header or []]
            ocol = next((k for k, h in enumerate(low) if "owner" in h), None)
            dcol = next((k for k, h in enumerate(low) if "decide" in h), None)
            for row in rows:
                if ocol is not None and dcol is not None:
                    o = row[ocol].strip() if ocol < len(row) else ""
                    d = row[dcol].strip() if dcol < len(row) else ""
                    if not o or not d:
                        bad.append(" | ".join(row))
                else:
                    check_item(" | ".join(row))
            continue
        if re.match(r"^(?:[-*+]|\d+[.)])\s+", s) and not lines[i].startswith((" ", "\t")):
            if cur is not None:
                check_item(cur)
            cur = s
        elif s and cur is not None:
            cur += " " + s
        elif not s and cur is not None:
            check_item(cur)
            cur = None
        i += 1
    if cur is not None:
        check_item(cur)
    return bad


def lint_proposal(run_dir, lite=False):
    """Rules P1-P10 over RUN/11_PROPOSAL. Writes lint.md and lint.json there."""
    run_dir = os.path.abspath(os.fspath(run_dir))
    prop = os.path.join(run_dir, PROPOSAL_DIR)
    arch = os.path.join(run_dir, ARCH_DIR)
    items = []
    text = _read(os.path.join(prop, "PROPOSAL.md"))
    one = _read(os.path.join(prop, "ONE-PAGER.md"))
    prfaq = _read(os.path.join(prop, "PRFAQ.md"))
    if text is None:
        items.append(_item("P1", "fail", "PROPOSAL.md", "file missing"))
        text = ""

    heads = _headings(text)
    # P1 headings in order
    found = {}
    pos = -1
    for key, prefixes, in_lite in PROPOSAL_HEADINGS:
        if lite and not in_lite:
            continue
        idxs = [n for n, (lv, t, _i) in enumerate(heads) if any(_heading_matches(lv, t, p) for p in prefixes)]
        if not idxs:
            if text:
                items.append(_item("P1", "fail", "PROPOSAL.md", "missing heading '%s'" % prefixes[0]))
            continue
        after = [n for n in idxs if n > pos]
        if not after:
            items.append(_item("P1", "fail", "PROPOSAL.md", "heading '%s' out of order" % prefixes[0]))
            continue
        pos = after[0]
        found[key] = prefixes

    def sec(key):
        for k, prefixes, _l in PROPOSAL_HEADINGS:
            if k == key:
                for p in prefixes:
                    body = _section(text, p)
                    if body is not None:
                        return body
        return None

    # P2 placeholders
    for rel, body in (("PROPOSAL.md", text), ("ONE-PAGER.md", one), ("PRFAQ.md", prfaq)):
        if body:
            hits = placeholder_hits(body)
            if hits:
                shown = "; ".join("line %d %s" % (n, snip) for n, _k, snip in hits[:3])
                items.append(_item("P2", "fail", rel, "%d placeholder(s): %s" % (len(hits), shown)))

    # P3 sourced numbers in 2, 4, 5, 10
    for key in ("2", "4", "5", "10"):
        body = sec(key)
        if body is None:
            continue
        bad = [u for u in _paragraph_units(body) if _needs_source(u)]
        if bad:
            items.append(_item("P3", "warn", "PROPOSAL.md", "section %s: %d sentence(s) with a number but no "
                               "[S-###], URL, [ASSUMPTION or [ESTIMATE; first: %s" % (key, len(bad), bad[0][:80])))

    # P4 word caps
    s1 = sec("1")
    if s1 is not None and word_count(s1) > 300:
        items.append(_item("P4", "fail", "PROPOSAL.md", "section 1 has %d words (max 300)" % word_count(s1)))
    if one is None:
        items.append(_item("P4", "fail", "ONE-PAGER.md", "file missing"))
    elif word_count(re.sub(r"(?m)^Status: .* \| Run: .*$", "", one)) > 550:  # the engine's status stamp is not prose
        items.append(_item("P4", "fail", "ONE-PAGER.md", "%d words (max 550)" % word_count(
            re.sub(r"(?m)^Status: .* \| Run: .*$", "", one))))

    # P5 Milestone 0 + kill criterion
    s8 = sec("8")
    if s8 is None:
        if not lite and text:
            items.append(_item("P5", "fail", "PROPOSAL.md", "section 8 missing: Milestone 0 cannot be checked"))
    else:
        if not re.search(r"milestone\s*0\b", s8, re.I):
            items.append(_item("P5", "fail", "PROPOSAL.md", "section 8 does not mention 'Milestone 0'"))
        if not re.search(r"kill[\s-]*criteri", s8, re.I):
            items.append(_item("P5", "fail", "PROPOSAL.md", "section 8 does not state the probe's kill criterion"))

    # P6 cited ids exist
    cited_text = "\n".join(t for t in (text, one) if t)
    s_ids = sorted(set(re.findall(r"\bS-\d{3}\b", cited_text)))
    if s_ids:
        known = set()
        src = os.path.join(run_dir, "sources.json")
        try:
            data = textio.read_json(src)
            known = set(data) if isinstance(data, dict) else set()
        except (OSError, ValueError):
            items.append(_item("P6", "fail", "../sources.json", "missing or unreadable, but %d source ids are cited"
                               % len(s_ids)))
            known = None
        if known is not None:
            miss = [s for s in s_ids if s not in known]
            if miss:
                items.append(_item("P6", "fail", "PROPOSAL.md", "sources not in sources.json: " + ", ".join(miss)))
    adr_ids = sorted(set(re.findall(r"\bADR-(\d{4})\b", cited_text)))
    if adr_ids:
        have = {os.path.basename(p)[:4] for p in _adr_files(arch)}
        miss = ["ADR-" + a for a in adr_ids if a not in have]
        if miss:
            items.append(_item("P6", "fail", "PROPOSAL.md", "ADRs with no file in 10_ARCHITECTURE/adr/: "
                               + ", ".join(miss)))
    r_ids = sorted(set(re.findall(r"\bR-\d{3}\b", cited_text)))
    if r_ids:
        have = _risk_ids(arch)
        miss = [r for r in r_ids if r not in have]
        if miss:
            items.append(_item("P6", "fail", "PROPOSAL.md", "risks not in 10_ARCHITECTURE/risks.md: "
                               + ", ".join(miss)))

    # P7 open questions carry Owner and Decide by
    s13 = sec("13")
    if s13 is not None:
        for it in _open_question_problems(s13):
            items.append(_item("P7", "fail", "PROPOSAL.md", "open question lacks 'Owner:' or 'Decide by:': %s"
                               % it[:80]))

    # P8 assumptions listed
    tags = extract_assumptions(text)
    raw_count = len(re.findall(r"\[ASSUMPTION", text, re.I))
    if raw_count:
        amd = _read(os.path.join(prop, "assumptions.md"))
        if amd is None:
            items.append(_item("P8", "fail", "assumptions.md", "missing, but PROPOSAL.md has %d [ASSUMPTION tags"
                               % raw_count))
        else:
            hay = norm_assumption(amd)
            miss = [t for kind, t, _n in tags if kind == "assumption" and norm_assumption(t) not in hay]
            if miss:
                items.append(_item("P8", "fail", "assumptions.md", "%d assumption(s) not listed; first: %s"
                                   % (len(miss), miss[0][:80])))

    # P9 "novel"
    for rel, body in (("PROPOSAL.md", text), ("ONE-PAGER.md", one), ("PRFAQ.md", prfaq)):
        if body and re.search(r"\bnovel\b", body, re.I):
            items.append(_item("P9", "warn", rel, "uses the word 'novel' (novelty only from evidence)"))

    # P10 dollar figures in section 10 found in the cost model
    s10 = sec("10")
    if s10:
        figs = _dollar_figures(_unfenced(s10))
        if figs:
            cost = _read(os.path.join(arch, "chosen", "cost-model.md"))
            hay = _norm_money(cost or "")
            miss = [f for f in figs if _norm_money(f) not in hay]
            if miss:
                items.append(_item("P10", "warn", "PROPOSAL.md", "section 10 figures not in chosen/cost-model.md: "
                                   + ", ".join(sorted(set(miss))[:5])))

    result = {"status": _status(items), "items": items, "rules": list(PROPOSAL_RULES), "lite": bool(lite),
              "scope": PROPOSAL_DIR}
    _write_report(prop, "proposal (%s%s)" % (PROPOSAL_DIR, ", lite" if lite else ""), result)
    return result


# ---------------------------------------------------------------- lint-frame

def lint_frame(run_dir):
    """Frame checks (warnings only). Writes frame/lint.json and frame/lint.md."""
    run_dir = os.path.abspath(os.fspath(run_dir))
    items = []
    frame = _read(os.path.join(run_dir, "01_FRAME.md"))
    if frame is None:
        items.append(_item("F1", "warn", "01_FRAME.md", "file missing"))
    else:
        heads = _headings(frame)
        for want in FRAME_SECTIONS:
            if not any(_heading_matches(lv, t, want) for lv, t, _i in heads):
                items.append(_item("F1", "warn", "01_FRAME.md", "missing section '%s'" % want))
        for want in ("## Job statement", "## Problem"):
            body = _section(frame, want)
            if body and _SOLUTION_RE.search(_unfenced(body)):
                hit = _SOLUTION_RE.search(_unfenced(body)).group(0)
                items.append(_item("F4", "warn", "01_FRAME.md", "%s reads like a solution ('%s'): keep the frame "
                                   "question-only" % (want[3:], hit)))
    crit_path = os.path.join(run_dir, "criteria.json")
    crit = None
    try:
        crit = textio.read_json(crit_path)
    except OSError:
        items.append(_item("F2", "warn", "criteria.json", "file missing"))
    except ValueError:
        items.append(_item("F2", "warn", "criteria.json", "not valid JSON"))
    if crit is not None:
        if not isinstance(crit, dict) or not crit:
            items.append(_item("F2", "warn", "criteria.json", "must be an object {criterion: weight}"))
        else:
            try:
                total = sum(float(v) for v in crit.values())
                if abs(total - 100) > 0.5:
                    items.append(_item("F2", "warn", "criteria.json", "weights sum to %g, not 100" % total))
            except (TypeError, ValueError):
                items.append(_item("F2", "warn", "criteria.json", "a weight is not a number"))
            keys = [k.lower() for k in crit]
            for needle, name in (("feasib", "Feasibility"), ("distinct", "Distinctiveness")):
                if not any(needle in k for k in keys):
                    items.append(_item("F3", "warn", "criteria.json", "no criterion like '%s': the tail slot is "
                                       "skipped" % name))
    result = {"status": _status(items), "items": items, "rules": list(FRAME_RULES), "lite": False,
              "scope": "frame"}
    _write_report(os.path.join(run_dir, "frame"), "frame (01_FRAME.md, criteria.json)", result)
    return result
