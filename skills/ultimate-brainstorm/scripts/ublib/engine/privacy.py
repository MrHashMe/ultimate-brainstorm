"""Privacy and evidence guards (KIT_SPEC 6.7, 6.8).

- vendor gating: which families a run may use (vendor_allowed: one rule for the engine and the worker), and the
  job.privacy stamp the adapter re-checks (5.6);
- code privacy: FACTS for other vendors keep file paths but drop code, and A2 terms (in FACTS and in PROPOSAL.md's
  Appendix E) keep only those with the "proposed" source mark; in a repo-labeled run (repo_labeled) every value of a
  prompt for another vendor goes through strip_code while privacy.code is false (a DATA block's body by the strict
  rule), and the worker refuses such a prompt when contains_code (the exact complement of strip_code) still finds
  code in its bytes;
- untrusted text: model- and web-derived values sit in prompts inside <<<DATA NAME ID>>> ... <<<END DATA ID>>> blocks
  that their content cannot forge (fence_data);
- seed-leak check: a generator/frame/ground prompt may not contain a 20+ character line from the seed sections Ideas,
  Primary idea or Obvious (the curator is the only job allowed to see seeds);
- pool-leak check: a generator prompt may not contain a 20+ character idea title from any pool file;
- origin-label check: judge prompts may not contain the run's alias IDs or an origin label ('Origin: gpt').
"""

import bisect
import hashlib
import os
import re

from .. import textio
from . import FAMILY_ORDER, REPO_VARIANTS, base_family, vendor_of

SEED_SECTIONS = ("Ideas", "Primary idea", "Obvious")
MIN_LEAK_CHARS = 20
# the kit's alias ID prefixes (QA/QB: the quick generators; a team seed file adds H<name>: builders.run_aliases), and
# the shapes of alias IDs for a check that has no run to take the exact IDs from
ALIAS_PREFIXES = r"S\d+|G\d+|R\d+|L\d+|H|HP|H2|IMP|S1R|QA|QB"
ALIAS_RE = re.compile(r"\b(%s)-\d+\b" % ALIAS_PREFIXES)
CODE_MARKER = "[code omitted: privacy code = no]"


class PolicyBlock(Exception):
    """A dispatch refused by an evidence or privacy rule (becomes a BLOCKED card naming the rule); `fix`: the card's
    fix lines when the generic ones would not work."""

    def __init__(self, rule, message, job_id=None, fix=None):
        Exception.__init__(self, message)
        self.rule = rule
        self.job_id = job_id
        self.fix = fix


# ---------------------------------------------------------------- vendors

def allowed_vendors(host_family, families, vendors_ok):
    """privacy.allowed_vendors: every available family's vendor, or only the host vendor when vendors = no."""
    if not vendors_ok:
        return [vendor_of(host_family)]
    return sorted(v for v in {vendor_of(f) for f in families} | {vendor_of(host_family)} if v)


def vendor_allowed(state, family, vendor=None):
    """5.6 rule 1, the one rule the engine and the worker share: a stored privacy.allowed_vendors list is exact, and an
    empty list allows no vendor. A run that was never seated (no list yet, or the empty placeholder a new run holds
    until its first seating) allows what that seating will store (allowed_vendors above). `state` is run.json or the
    engine state; `vendor` overrides the vendor of `family` (the worker passes its configured vendor)."""
    priv = state.get("privacy") or {}
    vend = vendor if vendor is not None else vendor_of(family)
    allowed = priv.get("allowed_vendors")
    if isinstance(allowed, list) and (allowed or state.get("seats")):
        return vend in allowed
    host = (state.get("host") or {}).get("family")
    fams = [f for f, info in (state.get("families") or {}).items() if (info or {}).get("status") == "ok"]
    return vend in allowed_vendors(host, fams, priv.get("vendors", True))


def job_privacy(state, family, tools, cwd, run_dir=None):
    """The job.privacy stamp (4.4): vendor_ok, web_ok, code_ok, and code_filtered (every value of the prompt went
    through strip_code, so the worker re-checks the prompt bytes with contains_code)."""
    priv = state.get("privacy") or {}
    host_vendor = vendor_of((state.get("host") or {}).get("family"))
    vend = vendor_of(family)
    web_ok = ("web" not in (tools or "none")) or bool(priv.get("web", True))
    code_ok = cwd != "repo" or vend == host_vendor or bool(priv.get("code", False))
    return {"vendor_ok": bool(vendor_allowed(state, family)), "web_ok": bool(web_ok), "code_ok": bool(code_ok),
            "code_filtered": bool(code_filtered(state, family, run_dir))}


def needs_code_strip(state, family):
    """True when prompts for this family must drop code (privacy code = no and a different vendor than the host)."""
    priv = state.get("privacy") or {}
    if priv.get("code", False):
        return False
    return vendor_of(family) != vendor_of((state.get("host") or {}).get("family"))


def repo_labeled(state, run_dir=None):
    """The repo label (C8), kept per run: True when text in this run can carry repository content.

    A job that reads the repo (meta repo_read, cwd repo) labels what it writes, and every host-vendor job sees
    FACTS, checks and packs unfiltered, so after the first repo read any model-written run file can carry what was
    read: the label covers every run file. It is set by privacy.repo_read (recorded when the engine builds a cwd-repo
    job), by a software or growth run whose project folder is a git repository (its jobs and its host can read the
    repo), and, for a run whose project folder moved, by any jobs/*.json with cwd repo."""
    priv = state.get("privacy") or {}
    if priv.get("repo_read"):
        return True
    if state.get("variant") not in REPO_VARIANTS:
        return False
    if is_git_repo(state.get("project_dir")):
        return True
    return bool(run_dir) and _repo_jobs(run_dir)


def is_git_repo(path):
    """True when `path` is the top of a git working tree: it holds a .git folder, or a .git file that starts with
    'gitdir:' (a git worktree or a submodule). The one test for repository access (registry.is_repo) and the repo
    label (repo_labeled)."""
    if not path:
        return False
    dot = os.path.join(path, ".git")
    if os.path.isdir(dot):
        return True
    try:
        with open(dot, "rb") as f:
            head = f.read(64)
    except OSError:
        return False
    return head.lstrip(b"\xef\xbb\xbf \t\r\n").startswith(b"gitdir:")


_REPO_JOB_SCAN = {}  # run folder -> (job files already read, whether one of them has cwd repo)


def _repo_jobs(run_dir):
    seen, found = _REPO_JOB_SCAN.get(run_dir, (set(), False))
    for path in [] if found else textio.glob_in(run_dir, "jobs", "*.json"):
        name = os.path.basename(path)
        if name in seen:
            continue
        try:
            job = textio.read_json(path)
        except (OSError, ValueError):
            continue
        seen.add(name)
        if isinstance(job, dict) and job.get("cwd") == "repo":
            found = True
            break
    _REPO_JOB_SCAN[run_dir] = (seen, found)
    return found


def code_filtered(state, family, run_dir=None):
    """True when every value of a prompt for `family` goes through strip_code: privacy.code is false, the family's
    vendor is not the host's and the run is repo-labeled. The worker then refuses the prompt if contains_code."""
    return needs_code_strip(state, family) and repo_labeled(state, run_dir)


# ---------------------------------------------------------------- code stripping (6.8)
#
# One line scanner decides what "code" is: strip_code replaces it and contains_code is its exact complement, so a
# prompt the engine filtered never trips the worker's byte check. Every rule is linear in the text. Code is:
# - a fenced block: textio's fence rule (textio.fence_open / fence_closes: 3+ backticks with no backtick in the info
#   string, or 3+ tildes; closed by a line of the same character at least as long), also after list markers and ">"
#   in front of the fence line, up to its closing line or to the end of the text when none follows. A closed
#   ```mermaid block stays: diagrams are design content, not code;
# - an indented block (CommonMark): lines indented 4+ columns (a tab counts to the next multiple of 4) that do not
#   continue a paragraph, with the blank lines inside it; within a list item the 4 columns count from the item's
#   content column;
# - an indented line that CommonMark would read as a paragraph's or a list item's continuation (right under a text
#   line, or inside a list item) but reads as code: indented 4+ columns from the open list item's marker (or from
#   the margin), not a list item itself, not a line that only cites (_CITATION_RE: paths with '/' or ':line' and
#   URLs, as in '(source: src/app.py:10)'), and either
#   - introduced: the last text line above it that is not such a continuation line (code blocks aside) ends with
#     ':', also inside emphasis or after an element's closing tag (_INTRO_END_RE: 'The config (config/app.yml:3)
#     reads:', '- F3: the handler is:', '**The handler is:**', 'the <code>charge</code> handler reads:'), or
#   - holding a code signal (_CODE_LINE_RE or only names; read with its inline spans, the rest of the line from a
#     <pre>/<code> tag and markers as ' x ', so a second pass reads what the first read): '=', ';', a brace, '->',
#     '::', a call with arguments, a trailing ':', a leading keyword (def, return, import, SELECT, ...) or Dockerfile
#     instruction (FROM, RUN, COPY, ...), 'key: value' with a one-word or quoted value, '"key":', '#include' and
#     other directives, '#!', a decorator ('@name'), require '...', export default|const|..., a shell prompt '$ ',
#     an option after a word (' -H', ' --prod'), or a line of names holding '_' or '.' (STRIPE_KEY, os.environ).
#   It starts an omitted run over the following blank lines and lines indented as far, and takes the continuation
#   lines right above it (up to the last blank or narrower line) with it. Prose continuations without a signal
#   under a line that does not end with ':' stay (the templates' hanging indents, '    and why (src/a.py:3)');
# - inside the body of a DATA block (fence_data: quoted run files, never template text), the strict rule: every
#   line indented 4+ columns from the margin that is not a list item and does not only cite is code, whatever list
#   item it sits in (a nested item's content column included), with the same run over the lines below it. Each body
#   is read on its own, as builders.resolver strips the value before fencing it (strict=True), and the text around
#   the blocks is read without them (the line after a block's END line follows a text line);
# - a <pre> or <code> HTML element, from its opening tag to the end of the line that closes it (an unclosed <pre>
#   runs to the end of the text, an unclosed <code> to the end of its paragraph); a ':' that ended the closing line
#   stays after the marker, and a heading that holds one stays a heading for the next line;
# - an inline code span (CommonMark: a run of n backticks up to the next run of exactly n, here on one line) that
#   reads as code: it contains "=" or ";", a call with arguments ("name(x"), an indexed name ('os.environ["X"]'), or
#   it starts with a code keyword (import x, from x, return x, def, class, const, let, var, function) or is SQL
#   (SELECT ... FROM, INSERT INTO, UPDATE x SET, DELETE FROM, CREATE TABLE). Paths (src/app.py:10), identifiers,
#   empty calls (useSwap()) and endpoints (POST /swaps, DELETE /swaps/1) stay: spec 6.8 keeps file paths, and spans
#   are how FACTS cite code.
# A list item needs a blank or the end of the line after its marker (-x, a **bold** lead-in and a number such as
# 3.14 are text).
# A block becomes one CODE_MARKER line (indented to the open list item's content column, so a second pass sees the
# same list); an element or a span becomes CODE_MARKER within its line.

_CONTAINERS_RE = re.compile(r"(?:[ \t>]|(?:[-*+]|\d{1,9}[.)])(?=[ \t]))*")  # list markers and '>' before a fence
_CONTAINER_RE = re.compile(r"^[ \t>]*")
_LIST_ITEM_RE = re.compile(r"^([ \t]*)([-*+]|\d{1,9}[.)])(?:([ \t]+)(?=\S)|[ \t]*$)")
# an indented continuation line that reads as code (see the rules above). Linear: a call's name starts only at the
# start of a run of name characters (the lookbehind), and the run holds a letter or '_' (the lookahead).
_CODE_LINE_RE = re.compile(
    r"[=;{}]|->|::|(?<![\w.])(?=[\w.]*[A-Za-z_])[\w.]+\((?!\))|:[ \t]*$"
    r"|^[ \t]*(?:(?:def|class|return|function|const|let|var|import|from|public|private|package|func|fn|SELECT|INSERT"
    r"|UPDATE|DELETE|FROM|RUN|COPY|ADD|ENV|ARG|WORKDIR|CMD|ENTRYPOINT|EXPOSE|USER)\b"
    r"|[A-Za-z_][\w.-]*:[ \t]+(?:[^ \t]+[ \t]*$|[\"'\[])"  # key: value (one word, or quoted)
    r"|\"[^\"]*\"[ \t]*:"  # "key":
    r"|#!|#[ \t]*(?:include|define|import|pragma|ifn?def|endif)\b|@[A-Za-z_]"  # a shebang, a directive, a decorator
    r"|require[ \t]*\(?[ \t]*[\"']|export[ \t]+(?:default|const|function|class|let|var|async|type|interface|enum)\b"
    r"|\$[ \t])"  # a shell prompt
    r"|[^ \t][ \t]+--?[A-Za-z][\w-]*(?=[ \t=]|$)")  # an option after a word (curl -H ..., npm run x --prod)
_NAME_RE = re.compile(r"^[A-Za-z_][\w.]*$")  # a word of a line of names (_names_only)
# a line that only cites: paths (with a '/' or a ':line'), URLs, optionally '(source: ...)'; it never reads as code
_CITE = r"`?(?:https?://[^\s(),`]+|[\w.-]*/[\w./-]*(?::\d+(?:-\d+)?)?|[\w.-]+\.[A-Za-z]\w*:\d+(?:-\d+)?)`?"
_CITATION_RE = re.compile(r"^[ \t]*\(?(?:(?:source|sources|see)(?::[ \t]*|[ \t]+))?%s(?:[ \t]*,[ \t]*%s)*\)?[.,]?"
                          r"[ \t]*$" % (_CITE, _CITE), re.I)
# an inline span that starts like a statement, is SQL, or indexes a name
_SPAN_KEYWORD_RE = re.compile(r"^[ \t]*(?:import|from|return|def|class|const|let|var|function)[ \t]+[\w.{*(\[\"']")
_SPAN_SQL_RE = re.compile(r"\bSELECT\b.+\bFROM\b|\bINSERT[ \t]+INTO\b|\bUPDATE[ \t]+\S+[ \t]+SET\b|\bDELETE[ \t]+FROM\b"
                          r"|\bCREATE[ \t]+(?:TABLE|INDEX|VIEW|UNIQUE|DATABASE|SCHEMA)\b", re.I)
_SPAN_INDEX_RE = re.compile(r"(?<![\w.])[A-Za-z_][\w.]*\[[^\]\s]")
_BLOCK_LINE_RE = re.compile(r"^[ \t]{0,3}(?:#{1,6}(?:[ \t]|$)|(?:[-*_][ \t]*){3,}$)")
_HTML_CODE_RE = re.compile(r"<(pre|code)([ \t>])", re.I)  # the tag ends at the next '>' (see _html_open)
_BACKTICKS_RE = re.compile(r"`+")
# a lead line that introduces what follows: it ends with ':', also inside emphasis ('**The handler is:**', '__Run:__',
# '<strong>Install:</strong>'); after an element, the ':' that followed its closing tag (strip_code keeps it)
_INTRO_END_RE = re.compile(r":(?:[*_]|</(?:b|strong|em|i)[ \t]*>)*[ \t]*$", re.I)
# A call with arguments: a run of name characters (starting a run: the lookbehind keeps the search linear) holding a
# letter or '_', then optional blanks and '(' not followed by ')'.
_CALL_RE = re.compile(r"(?<![\w.])([\w.]+)[ \t]*\((?![ \t]*\))")
_NAME_START_RE = re.compile(r"[A-Za-z_]")


def _indent(line):
    n = 0
    for ch in line:
        if ch == " ":
            n += 1
        elif ch == "\t":
            n += 4 - n % 4
        else:
            break
    return n


def _fence_open(line):
    """(textio.fence_open's (char, length, lang), behind a list marker) for a fence line, also behind list markers and
    '>'; else None. A fence opened behind a list marker ('- ```') may close behind one too (the next item's '- ```'),
    so the fence rule is the same in both directions; a fence opened without one closes as textio's does."""
    prefix = _CONTAINERS_RE.match(line).group(0)
    fence = textio.fence_open(line[len(prefix):])
    return (fence, bool(prefix.strip(" \t>"))) if fence else None


def _fence_close(line, opened):
    fence, listed = opened
    rest = line[_CONTAINERS_RE.match(line).end():] if listed else _CONTAINER_RE.sub("", line)
    return textio.fence_closes(rest, fence)


def fence_mask(lines):
    """Per line: True when the line is inside a fenced block or is one of its delimiter lines (the rule above; an
    unclosed block runs to the end). textio.fence_mask, looking through list markers and '>' as well."""
    mask, fence = [], None
    for ln in lines:
        if fence is None:
            fence = _fence_open(ln)
            mask.append(bool(fence))
        else:
            mask.append(True)
            if _fence_close(ln, fence):
                fence = None
    return mask


def _list_item(line):
    """(marker column, content column) of a list item line ('- x', '1. x', a bare '-'), else None."""
    m = _LIST_ITEM_RE.match(line)
    if not m:
        return None
    sp = len((m.group(3) or "").expandtabs(4))
    marker = _indent(line)
    return marker, marker + len(m.group(2)) + (sp if 1 <= sp <= 4 else 1)


def _spans(text):
    """[(start, end, size)] of the inline code spans of one line, left to right (end excludes the closing run)."""
    runs = [(m.start(), m.end() - m.start()) for m in _BACKTICKS_RE.finditer(text)]
    by_len = {}
    for idx, (_pos, size) in enumerate(runs):
        by_len.setdefault(size, []).append(idx)
    out, idx = [], 0
    while idx < len(runs):
        pos, size = runs[idx]
        same = by_len[size]
        k = bisect.bisect_right(same, idx)
        if k == len(same):
            idx += 1  # no later run of the same length: literal backticks
            continue
        close = same[k]
        out.append((pos, runs[close][0], size))
        idx = close + 1
    return out


def _code_like(span):
    """True when an inline span's text reads as code: '=' or ';', a call with arguments ('name(x'), an indexed name
    ('os.environ["X"]'), a leading code keyword ('import x', 'return x') or SQL ('SELECT a FROM b')."""
    if "=" in span or ";" in span:
        return True
    if _SPAN_KEYWORD_RE.match(span) or _SPAN_SQL_RE.search(span) or _SPAN_INDEX_RE.search(span):
        return True
    return any(_NAME_START_RE.search(m.group(1)) for m in _CALL_RE.finditer(span))


def _strip_spans(text):
    """Code-like inline spans of one line (or line part) -> CODE_MARKER; everything else unchanged."""
    out, done = [], 0
    for pos, end, size in _spans(text):
        if _code_like(text[pos + size:end]):
            out.append(text[done:pos])
            out.append(CODE_MARKER)
            done = end + size
    out.append(text[done:])
    return "".join(out)


def _html_open(line):
    """(start, end, tag) of the first <pre>/<code> opening tag of a line ('<pre>', or '<pre ' up to the next '>') that
    is not inside an inline code span, else None. Linear: a tag with attributes counts only when a '>' follows it
    somewhere in the line, which the line's last '>' tells without a scan per tag."""
    spans = starts = None
    last_gt = line.rfind(">")
    for m in _HTML_CODE_RE.finditer(line):
        if m.group(2) != ">" and last_gt < m.end():
            continue
        if spans is None:
            spans = _spans(line)
            starts = [s[0] for s in spans]
        k = bisect.bisect_right(starts, m.start()) - 1
        if k < 0 or m.start() >= spans[k][1] + spans[k][2]:
            return m.start(), line.index(">", m.start(2)) + 1, m.group(1)
    return None


def _omit(out, indent):
    marker = " " * (indent or 0) + CODE_MARKER
    if not out or out[-1] != marker:
        out.append(marker)


def _signal_text(line):
    """A continuation line as its code-signal test reads it: every inline span, the rest of the line from a <pre> or
    <code> tag, and every CODE_MARKER become ' x '. A second pass sees a marker where the first saw a span or an
    element, so both passes read the same text and strip_code stays idempotent."""
    tag = _html_open(line)
    if tag:
        line = line[:tag[0]] + CODE_MARKER
    out, done = [], 0
    for pos, end, size in _spans(line):
        out.append(line[done:pos])
        out.append(" x ")
        done = end + size
    out.append(line[done:])
    return "".join(out).replace(CODE_MARKER, " x ")


def _names_only(text):
    """True when a line holds only names with '_' or '.' in them (STRIPE_SECRET_KEY, os.environ), commas between."""
    words = text.replace(",", " ").split()
    return bool(words) and all(_NAME_RE.match(w) and ("_" in w or "." in w.strip(".")) for w in words)


def _code_continuation(line, intro):
    """True when a continuation line reads as code (see the rules above): not a marker or a line that only cites, and
    under a line that ends with ':' (intro) or holding a code signal."""
    if line.strip() == CODE_MARKER or _CITATION_RE.match(line):
        return False
    if intro:
        return True
    text = _signal_text(line)
    return bool(_CODE_LINE_RE.search(text)) or _names_only(text)


def strip_code(text, strict=False):
    """The text without code (see the rules above); file paths, prose and mermaid diagrams stay. Idempotent. The body of
    each DATA block follows the strict rule; `strict` applies it to the whole text (a DATA value before fence_data)."""
    if not text:
        return text
    lines = textio.normalize_newlines(text).split("\n")
    if strict:
        return "\n".join(_strip_lines(lines, True))
    out, done = [], 0
    for start, end in _data_bodies(lines):
        out += _strip_lines(lines[done:start], prev="para" if done else "blank")
        out.append(lines[start])
        out += _strip_lines(lines[start + 1:end], True)
        out.append(lines[end])
        done = end + 1
    out += _strip_lines(lines[done:], prev="para" if done else "blank")
    return "\n".join(out)


_DATA_OPEN_LINE_RE = re.compile(r"<<<DATA [A-Z][A-Z0-9_]* ([0-9a-f]{16})>>>")
_DATA_END_LINE_RE = re.compile(r"<<<END DATA ([0-9a-f]{16})>>>")


def _data_bodies(lines):
    """[(open, end)]: the line numbers of the delimiter lines of each DATA block, as _DATA_BLOCK_RE finds the blocks
    (left to right, the first END line of the block's id at least two lines on, blocks do not overlap)."""
    ends = {}
    for k, ln in enumerate(lines):
        m = _DATA_END_LINE_RE.fullmatch(ln)
        if m:
            ends.setdefault(m.group(1), []).append(k)
    out, k = [], 0
    while ends and k < len(lines):
        m = _DATA_OPEN_LINE_RE.fullmatch(lines[k])
        found = ends.get(m.group(1), []) if m else []
        pos = bisect.bisect_left(found, k + 2)
        if pos < len(found):
            out.append((k, found[pos]))
            k = found[pos]
        k += 1
    return out


def _strip_lines(lines, strict=False, prev="blank"):
    """strip_code over lines: `strict` reads them as a DATA block's body; `prev` is the kind of the line above them."""
    out = []
    n = len(lines)
    i = 0
    # prev: the previous line: blank | para | block (a heading, a rule, the end of a code block)
    list_indent = list_marker = None  # the content and marker columns of the open list item
    intro = False  # the last text line that is not a continuation line (code blocks aside) ends with ':'
    run = None  # where in `out` the continuation lines right above this line start (code under them takes them)
    while i < n:
        ln = lines[i]
        if not ln.strip():
            out.append(ln)
            prev, run = "blank", None
            i += 1
            continue
        width = _indent(ln)
        item = _list_item(ln)
        fence = _fence_open(ln)
        # a line left of the item's content ends the list unless it lazily continues a paragraph
        if list_indent is not None and width < list_indent and item is None and (
                prev != "para" or fence or _BLOCK_LINE_RE.match(ln)):
            list_indent = list_marker = None
        limit = (list_indent or 0) + 4  # an indented code block (CommonMark)
        # a continuation line this far in that reads as code is code too; in a DATA body, any line 4 columns in
        soft = 4 if strict else (list_marker or 0) + 4
        if fence:
            j = i + 1
            while j < n and not _fence_close(lines[j], fence):
                j += 1
            if j < n and fence[0][2] == "mermaid":
                out.extend(lines[i:j + 1])
            else:
                _omit(out, list_indent)
            i, prev, run = min(j + 1, n), "block", None
            continue
        block = width >= limit and prev != "para"
        cont = not block and item is None and width >= soft  # a paragraph's or a list item's continuation line
        if block or (cont and _code_continuation(ln, intro or strict)):
            reach = limit if block else soft
            j = last = i
            while j < n and (not lines[j].strip() or _indent(lines[j]) >= reach):
                if lines[j].strip():
                    last = j
                j += 1
            if run is not None:
                del out[run:]  # the continuation lines right above it belong to the same code
            _omit(out, list_indent)
            i, prev, run = last + 1, "block", None
            continue
        if cont:
            run = len(out) if run is None else run
        else:
            run = None
        if item is not None:
            list_marker, list_indent = item
        tag = _html_open(ln)
        if tag:
            start, end, name = tag
            close = re.compile(r"</%s[ \t]*>" % name, re.I)
            m = close.search(ln, end)
            tail = ln[m.end():] if m else ""
            j = i + 1
            if not m:
                while j < n:
                    m = close.search(lines[j])
                    if m:
                        tail = lines[j][m.end():]
                        j += 1
                        break
                    if name.lower() == "code" and not lines[j].strip():
                        break
                    j += 1
            # the rest of the closing line goes with the element, but a ':' that ended it stays (with its closing
            # emphasis), so the line still introduces what follows, on this pass and on the next (which reads the
            # marker and the ':'); a continuation line gets none (its signal test would read a trailing ':')
            lead = _INTRO_END_RE.search(tail) if not cont else None
            colon = lead.group(0).rstrip() if lead else ""
            out.append(_strip_spans(ln[:start]) + CODE_MARKER + colon)
            if not cont:
                intro = bool(colon)
            i, prev = j, "block" if _BLOCK_LINE_RE.match(ln) else "para"  # a heading, as the next pass reads it
            continue
        out.append(_strip_spans(ln))
        if not cont:
            intro = bool(_INTRO_END_RE.search(out[-1]))  # read on the text a second pass reads
        prev = "block" if _BLOCK_LINE_RE.match(ln) else "para"
        i += 1
    return out


def contains_code(text):
    """True when strip_code would change the text: the worker's byte check (C8), strip_code's exact complement."""
    if not text:
        return False
    text = textio.normalize_newlines(text)
    return strip_code(text) != text


# an A2 term (filter_a2_terms): a list or numbered item, a table row, a bold-led line, a heading (after the A2 heading),
# or any line that names CONTEXT.md; it stays for another vendor only with the 'proposed' source mark on its own line
# ('[proposed]', '(source: proposed)', a table cell '| proposed |'), not the word alone ('a proposed shift trade
# (CONTEXT.md)' is today's system)
_A2_TERM_RE = re.compile(r"^(?:[-*+][ \t]|\d{1,9}[.)][ \t]|\||\*\*|__)|CONTEXT\.md", re.I)
_A2_PROPOSED_RE = re.compile(r"[\[(][ \t]*(?:source:[ \t]*)?proposed[ \t]*[\])]|\bsource:[ \t]*proposed\b"
                             r"|\|[ \t]*proposed[ \t]*\|", re.I)
# a term nested under a kept term: a bold-led item or line, a table row or a heading (a plain sub-item such as
# '- source: s.md' belongs to the term above it)
_A2_SUBTERM_RE = re.compile(r"^(?:(?:[-*+]|\d{1,9}[.)])[ \t]+)?(?:\*\*|__)|^[|#]")


def _a2_kept(s):
    """True for a term line that stays for another vendor: its own proposed mark, and no CONTEXT.md."""
    return bool(_A2_PROPOSED_RE.search(s)) and "context.md" not in s.lower()


def filter_a2_terms(a2_text):
    """Keep the A2 intro line(s) and only the terms with the 'proposed' source mark that name no CONTEXT.md. A dropped
    term takes its continuation with it: the lines indented further than the term line (up to the next line at or left
    of its indent, blank lines between them included), the wrapped lines right under it (no blank line between, up to a
    term or a heading) and, for a heading, its body up to the next heading or kept term; so an alias, a source line
    or a wrapped definition goes too, and a heading whose mark sits on a line below it goes whole (fail closed: the
    filter cannot tie that mark to it). A kept term keeps its own lines, except a line under it that names CONTEXT.md or
    is a term without its own proposed mark (_A2_SUBTERM_RE), dropped the same way. The A2 heading (the first line) is
    dropped when it names CONTEXT.md, but never takes the intro with it."""
    if not a2_text:
        return a2_text
    out, blanks = [], []
    dropped = kept = None  # the indent of the term line being dropped / kept
    body = False  # the dropped term is a heading: every line up to the next heading or kept term goes with it
    for n, ln in enumerate(a2_text.split("\n")):
        s = ln.strip()
        head = bool(n) and s.startswith("#")
        if dropped is not None:
            if not s:
                blanks.append(ln)  # kept only when the dropped term ends right after them
                continue
            # a heading's body ends only at a heading or a kept term (its 'Source: CONTEXT.md' line is body)
            term = head or _A2_TERM_RE.search(s) and (not body or _a2_kept(s))
            if _indent(ln) > dropped or not term and (body or not blanks):
                blanks = []
                continue
            dropped = None
            out.extend(blanks)
            blanks = []
        if kept is not None and s and _indent(ln) > kept:
            if "context.md" in s.lower() or _A2_SUBTERM_RE.match(s) and not _a2_kept(s):
                dropped, body = _indent(ln), head
            else:
                out.append(ln)
            continue
        if s:
            kept = None
        if head or _A2_TERM_RE.search(s):
            if not _a2_kept(s):
                if n or not s.startswith("#"):  # the A2 heading itself goes alone
                    dropped, body = _indent(ln), s.startswith("#")
                continue
            kept = _indent(ln)
        out.append(ln)
    return "\n".join(out + blanks)


def _facts_for_other_vendor(text):
    """FACTS for another vendor: code stripped (FACTS is always a DATA block's body: the strict rule), A2 terms
    filtered, and stripped again, since dropping a term line can leave an indented line under a blank line or a
    heading, which is an indented code block (strip_code is idempotent, so text that needs nothing more stays as it
    is)."""
    text = strip_code(text, strict=True)
    m = re.search(r"^##\s*A2\b.*?(?=^##\s|\Z)", text, re.M | re.S)
    if m:
        text = text[:m.start()] + filter_a2_terms(m.group(0)) + text[m.end():]
    return strip_code(text, strict=True)


def filter_facts(facts_text, state, family):
    """FACTS text as a given family may see it."""
    if not needs_code_strip(state, family):
        return facts_text
    return _facts_for_other_vendor(facts_text)


GLOSSARY_A2 = "### Domain terms (today's system)"  # render.appendix_e writes the A2 terms under this line
_APPENDIX_E_RE = re.compile(r"##\s*Appendix E\b", re.I)


def filter_glossary(text):
    """PROPOSAL.md text for another vendor (SECTIONS_ALL): the A2 terms render.appendix_e copied into Appendix E go
    through filter_a2_terms as in FACTS, from the GLOSSARY_A2 line to the end of the appendix (the next '## ' line by
    textio's fence rule), and the FRAME's terms above that line stay. Without that line (a PROPOSAL.md an older kit
    assembled) the whole appendix is filtered: the filter cannot tell the two apart there, so it fails closed. Every
    '## Appendix E' line counts, inside a fence too, so neither a quoted one nor a fence a section left open can hide
    the engine's. Linear: the appendices found are disjoint and each line is read once."""
    lines = textio.normalize_newlines(text or "").split("\n")
    mask = textio.fence_mask(lines)
    found, end = [], len(lines)  # [first heading line, end] of each appendix, from the bottom
    for i in range(len(lines) - 1, -1, -1):
        if _APPENDIX_E_RE.match(lines[i]):
            if found and found[-1][1] == end:
                found[-1][0] = i  # a second heading line before the same end: one appendix
            else:
                found.append([i, end])
        if not mask[i] and re.match(r"##\s", lines[i]):
            end = i
    for h, end in found:  # bottom first, so the line numbers above stay valid
        start = next((i for i in range(h + 1, end) if lines[i].strip() == GLOSSARY_A2), h)
        lines[start:end] = filter_a2_terms("\n".join(lines[start:end])).split("\n")
    return "\n".join(lines) if found else text


ONE_PAGER_MARK = "--- FILE: ONE-PAGER.md ---"  # SECTIONS_ALL: registry._ph_sections appends ONE-PAGER.md after this line
_ONE_PAGER_MARK_RE = re.compile(r"(?m)^(?=%s$)" % re.escape(ONE_PAGER_MARK))


def mark_free(text):
    """`text` (LF) with every line equal to ONE_PAGER_MARK indented one space, so the engine's is the only one."""
    return _ONE_PAGER_MARK_RE.sub(" ", text)


def filter_sections_all(text):
    """SECTIONS_ALL for another vendor: filter_glossary on the proposal and, on its own, on the ONE-PAGER.md after the
    engine's marker line, so an Appendix E that runs to the end of the proposal (the last part, or a fence a section
    left open hides the '## ' lines below it) cannot take the one-pager with it. No other line equals the marker
    (mark_free), so model text cannot move the split."""
    head, mark, tail = textio.normalize_newlines(text or "").rpartition("\n%s\n" % ONE_PAGER_MARK)
    if not mark:
        return filter_glossary(text)
    return filter_glossary(head) + mark + filter_glossary(tail)


# ---------------------------------------------------------------- untrusted text (DATA blocks)
#
# A value quoted from run files (model output, much of it written from web pages) goes into a prompt as
#     <<<DATA NAME ID>>>
#     ...
#     <<<END DATA ID>>>
# and every template that inlines such a value says the text inside is quoted data, never instructions. ID is the first
# 16 hex digits of sha256(NAME, text), a per-block nonce: the text cannot contain its own delimiter (that would be a
# hash fixed point), and a prompt rebuilt from the same files stays byte-identical (the done rule keys on the prompt's
# sha256, so a random nonce would re-run finished jobs). "<<<DATA" and "<<<END DATA" inside the text are neutralized
# to "<<", so no line of the text can even look like a delimiter.

DATA_OPEN = "<<<DATA %s %s>>>"
DATA_CLOSE = "<<<END DATA %s>>>"
# a whole run of 3+ '<' before DATA or END DATA (the lookbehind starts the match only at the run's first '<', so a
# long run of '<' costs linear time, not a rescan from every position)
_DATA_TOKEN_RE = re.compile(r"(?<!<)<{3,}(?=[ \t]*(?:END[ \t]+)?DATA\b)", re.I)
_DATA_BLOCK_RE = re.compile(r"^<<<DATA ([A-Z][A-Z0-9_]*) ([0-9a-f]{16})>>>\n(.*?)\n<<<END DATA \2>>>$", re.M | re.S)


def fence_data(name, text):
    """`text` (a placeholder value) as a DATA block; an empty value stays as it is (its template line is removed)."""
    if text is None or not str(text).strip():
        return text
    body = _DATA_TOKEN_RE.sub("<<", textio.normalize_newlines(str(text))).strip("\n")
    nonce = hashlib.sha256(("%s\n%s" % (name, body)).encode("utf-8")).hexdigest()[:16]
    return "\n".join([DATA_OPEN % (name, nonce), body, DATA_CLOSE % nonce])


def data_blocks(text):
    """[(name, id, body)] of the DATA blocks of a prompt, in order."""
    return [m.groups() for m in _DATA_BLOCK_RE.finditer(textio.normalize_newlines(text or ""))]


def refilter_prompt(prompt, state, family, run_dir=None):
    """A prompt written for one family, as `family` may see it (fallback copies, 6.8). Nothing changes for the host
    vendor or with privacy.code = yes. Otherwise FACTS and SECTIONS_ALL blocks are filtered like those placeholders,
    and in a repo-labeled run (or for an older prompt without DATA blocks) the whole prompt goes through strip_code,
    which leaves the template text alone because templates carry no code."""
    if not needs_code_strip(state, family):
        return prompt
    text = textio.normalize_newlines(prompt or "")
    if repo_labeled(state, run_dir) or not _DATA_BLOCK_RE.search(text):
        text = strip_code(text)
    filters = {"FACTS": _facts_for_other_vendor, "SECTIONS_ALL": filter_sections_all}

    def refilter(m):
        fn = filters.get(m.group(1))
        if fn is None:
            return m.group(0)
        return "\n".join([DATA_OPEN % (m.group(1), m.group(2)), fn(m.group(3)), DATA_CLOSE % m.group(2)])
    return _DATA_BLOCK_RE.sub(refilter, text)


# ---------------------------------------------------------------- seed leak (6.7 rule 1)

def _section(text, heading):
    return textio.section(text, heading)  # the engine's reading of the seeds file (fenced '## ' lines are text)


def seed_lines(run_dir):
    """Lines of 20+ characters from the seed sections Ideas, Primary idea, Obvious of every seeds file."""
    lines = []
    for path in sorted(textio.glob_in(run_dir, "00_HUMAN_SEEDS*.md") +
                       textio.glob_in(run_dir, "00b_HUMAN_ROUND2.md")):
        try:
            text = textio.read_text(path)
        except OSError:
            continue
        for sec in SEED_SECTIONS:
            for ln in _section(text, sec).split("\n"):
                s = _norm(re.sub(r"^\s*(?:[-*]|\d+[.)])\s*", "", ln))
                if len(s) >= MIN_LEAK_CHARS:
                    lines.append(s)
    return lines


def _norm(s):
    return " ".join(str(s).split()).strip()


def check_seed_leak(prompt_text, run_dir, job_id=None, allow=()):
    """allow: texts the prompt may legitimately carry (the run topic; the proposal-mode idea)."""
    norm = _norm(prompt_text).lower()
    allowed = [_norm(a).lower() for a in allow if a]
    for s in seed_lines(run_dir):
        low = s.lower()
        if any(low in a for a in allowed):
            continue
        if low in norm:
            raise PolicyBlock("seed_leak_check",
                              "Human-first rule: the prompt for %s contains a line from your seeds (%r...). Seeds "
                              "may only reach the curator." % (job_id or "a job", s[:40]), job_id)


# ---------------------------------------------------------------- pool leak (6.7 rule 3)

# an idea heading ('### S3-04 Title'), on one line; the title is the rest of the line (a lazy title followed by
# \s*$ cost quadratic time on a long run of blanks)
_TITLE_RE = re.compile(r"^#{2,4}[ \t]*[A-Z][A-Za-z0-9]*-\d+[:.)]?[ \t]+(\S[^\n]*)", re.M)


def pool_titles(run_dir):
    titles = []
    for path in textio.glob_in(run_dir, "pool", "*.md"):
        try:
            text = textio.read_text(path)
        except OSError:
            continue
        for m in _TITLE_RE.finditer(text):
            t = _norm(m.group(1))
            if len(t) >= MIN_LEAK_CHARS:
                titles.append(t)
    return titles


def check_pool_leak(prompt_text, run_dir, job_id=None, exclude_files=()):
    norm = _norm(prompt_text).lower()
    for t in pool_titles(run_dir):
        if t.lower() in norm:
            raise PolicyBlock("pool_leak_check",
                              "Isolation rule: the generator prompt for %s contains an idea title from pool/ (%r...)."
                              % (job_id or "a job", t[:40]), job_id)


# ---------------------------------------------------------------- origin labels (6.7 rule 6)

#
# A judge prompt may reveal no idea's origin. It may hold no alias ID of the run (the IDs of its pool, lens, import and
# seed ideas and the curators' alias lists that have an alias shape of the kit: builders.run_aliases; ALIAS_RE's shapes
# only when no run is given) and no origin label in the kit's own syntax (03_POOL.md's 'Origin: X.', the tournament's
# '(origin: X)', 'written by <family>'), also with markdown emphasis or code marks around the label and the value
# ('**Origin:** `gpt`'):
# - a label word (origin, strategy, family, generated by, written by) with ':' or '=', or right after '(', then an
#   origin value;
# - a bare 'generated by' or 'written by' before a family label, its -alt or its vendor.
# An origin value is a family label, its -alt or its vendor, or, only as the whole value (its closing marks and then
# a punctuation mark or the line end follow it), human, human-mixed, ai-mixed, unknown, import, evolved or a prefix of
# the run's alias IDs (S2). Ordinary words stay ('Deployment strategy: blue-green', 'Storage strategy: S3 buckets',
# 'CORS origin:', 'rotas generated by a solver', 'written by human volunteers', 'the origin S3 bucket', 'an L4-7 load
# balancer'), a label never spans two lines, and the run's topic and proposal-mode idea are taken out of the prompt
# first, so the user's own words never block their run.

_ORIGIN_NAMES = ("human", "human-mixed", "ai-mixed", "unknown", "import", "evolved")
_ORIGIN_RES = {}


def _alt(values):
    return "|".join(re.escape(v) for v in sorted(values, key=lambda v: (-len(v), v)))


def _origin_label_re(labels=(), aliases=None):
    """The origin-label pattern for the kit's families, a run's own family labels and the prefixes of its alias IDs
    (None: the kit's prefixes)."""
    fams = frozenset(base_family(f) for f in tuple(FAMILY_ORDER) + tuple(labels or ()) if f)
    prefixes = ALIAS_PREFIXES if aliases is None else _alt(set(a.rsplit("-", 1)[0] for a in aliases if "-" in a))
    rx = _ORIGIN_RES.get((fams, prefixes))
    if rx is None:
        names = set()
        for f in fams:
            names.update((f, f + "-alt", vendor_of(f) or f))
        # the value's opening marks are the gap's, never its own: two stars over the same marks would try every split
        # of a run of marks from every start, quadratic on 'Strategy: ____...'
        fam = r"(?:%s)(?![^\W_]|-)" % _alt(names)
        whole = _alt(_ORIGIN_NAMES) + ("|" + prefixes if prefixes else "")
        value = r"(?:%s|(?:%s)(?![^\W_]|-)[*_`]*(?=[ \t]*(?:[).,;:|\]]|\n|$)))" % (fam, whole)
        word, gap = r"(?:origin|strategy|family|generated[ \t]+by|written[ \t]+by)", r"[ \t*_`]*"
        rx = _ORIGIN_RES[(fams, prefixes)] = re.compile(
            r"(?<![^\W_])%s%s[:=]%s%s" % (word, gap, gap, value) +  # 'Origin: gpt', '**Strategy:** S2'
            r"|(?<=\()%s%s%s(?:[:=]%s)?%s" % (gap, word, gap, gap, value) +  # '(written by human)'
            r"|(?<![^\W_])(?:generated|written)[ \t]+by[ \t]+[*_`]*%s" % fam, re.I)  # 'generated by Claude'
    return rx


def _alias_re(aliases):
    if aliases is None:
        return ALIAS_RE
    ids = sorted(set(a for a in aliases if a), key=lambda a: (-len(a), a))
    return re.compile(r"\b(?:%s)\b" % "|".join(re.escape(a) for a in ids)) if ids else None


def _without(text, allow):
    """`text` with each run of blanks as one space (line breaks stay, so a label never spans two lines) and every
    allowed text (any case, any white space between its words) taken out."""
    text = re.sub(r"[^\S\n]+", " ", textio.normalize_newlines(str(text)))
    for a in allow or ():
        words = str(a or "").split()
        if words:
            text = re.sub(r"\s+".join(re.escape(w) for w in words), " | ", text, flags=re.I)
    return text


def _origin_source(run_dir, rx, sources, allow):
    """The first of `sources` (run-relative paths or globs) whose text matches rx, or None."""
    for rel in sources or ():
        for path in sorted(textio.glob_in(run_dir, *rel.split("/"))) if run_dir else ():
            try:
                if rx.search(_without(textio.read_text(path), allow)):
                    return os.path.relpath(path, run_dir).replace("\\", "/")
            except OSError:
                continue
    return None


def check_origin_labels(prompt_text, job_id=None, run_dir=None, allow=(), aliases=None, labels=(), sources=()):
    """Refuse a judge prompt that reveals an idea's origin (the rules above). The refusal names the first of `sources`
    that holds the match."""
    text = _without(prompt_text or "", allow)
    for rx, what in ((_alias_re(aliases), "the alias ID %s"), (_origin_label_re(labels, aliases), "%r")):
        m = rx.search(text) if rx is not None else None
        if m:
            where = _origin_source(run_dir, rx, sources, allow)
            raise PolicyBlock("origin_label_check",
                              ("Debiasing rule: the judge prompt for %s contains " + what + "%s, which reveals an "
                               "idea's origin.") % (job_id or "a job", m.group(0), " (in %s)" % where if where else ""),
                              job_id)


def run_checks(prompt_text, checks, run_dir, job_id=None, allow=(), aliases=None, labels=(), sources=()):
    """Apply the named checks ('seed_leak', 'pool_leak', 'origin_label') to a prompt. `aliases`, `labels` and
    `sources`: the run's alias IDs, family labels and judge input files (check_origin_labels)."""
    for name in checks or ():
        if name in ("seed_leak", "seed_leak_check"):
            check_seed_leak(prompt_text, run_dir, job_id, allow=allow)
        elif name in ("pool_leak", "pool_leak_check"):
            check_pool_leak(prompt_text, run_dir, job_id)
        elif name in ("origin_label", "origin_label_check"):
            check_origin_labels(prompt_text, job_id, run_dir, allow, aliases, labels, sources)


def family_vendor(label):
    return vendor_of(label)
