"""Tolerant text reads, atomic writes, JSON extraction and hashing (KIT_SPEC 3.1, 4.8).

Frozen API (4.8):
    read_text(path) -> str
    write_text_atomic(path, text) -> None
    write_json_atomic(path, obj) -> None
    extract_json(text) -> object
    sha256_text(text) -> str ; sha256_file(path) -> str ; is_ascii(text) -> bool

Extras (not frozen, safe to use): decode_bytes, normalize_newlines, read_json, read_bytes, read_json_or,
append_line, now_iso, to_posix, glob_in, real_path, loads_strict, read_json_strict, PathTooLong, explain_long_path,
long_paths_enabled, temp_prefix, fsync_dir, try_lock_fd, unlock_fd, and the Markdown line scanners fence_open,
fence_closes, fence_spans, fence_mask, fenced_blocks, parse_heading, headings.

Parsers over model output are linear (KIT_SPEC 4.5). There is one definition of a fenced code block and one of an
ATX heading; validate, lints and render all use them. A fence opens on a line that is 3+ backticks or tildes after
optional spaces/tabs (a backtick fence's info string holds no backtick) and closes on a line of only the same
character, at least as many; an unclosed fence runs to the end of the text. Headings inside fences are not headings.

Reads and concurrent replaces (Windows). Workers and drivers replace markers, heartbeats, job and result files with
os.replace while other processes read them. On Windows an open() that lands inside another process's replace (or
delete) fails with PermissionError for a moment, and a reader that holds the file open makes the writer's replace fail
the same way. Every read here (read_bytes, read_text, read_json, read_json_or, sha256_file) therefore retries a
transient PermissionError briefly (READ_RETRY_S in total) instead of reporting a file that is only mid-replace as
unreadable; atomic writes retry their replace. FileNotFoundError is never retried: a missing file is a real state.
"""

import datetime
import errno
import glob
import hashlib
import heapq
import json
import os
import re
import tempfile
import time

__all__ = [
    "read_text", "write_text_atomic", "write_json_atomic", "extract_json",
    "sha256_text", "sha256_file", "is_ascii",
    "decode_bytes", "normalize_newlines", "read_json", "read_bytes", "read_json_or", "append_line", "now_iso",
    "to_posix", "glob_in", "real_path", "loads_strict", "read_json_strict", "PathTooLong", "explain_long_path",
    "long_paths_enabled", "temp_prefix",
    "fsync_dir", "try_lock_fd", "unlock_fd",
    "fence_open", "fence_closes", "fence_spans", "fence_mask", "fenced_blocks", "parse_heading", "headings",
]

_UTF8_BOM = b"\xef\xbb\xbf"

# Transient read errors are retried on Windows only: there a file being replaced or deleted by another process is
# briefly unopenable (sharing violation / delete pending). On POSIX a rename never blocks readers, so a
# PermissionError there is real and is raised at once.
RETRY_TRANSIENT_READS = os.name == "nt"
READ_RETRY_S = 1.0
_TRANSIENT_WINERRORS = (5, 32, 33)  # ACCESS_DENIED (also: delete pending), SHARING_VIOLATION, LOCK_VIOLATION


def normalize_newlines(text):
    """CRLF and lone CR -> LF."""
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _looks_utf16(raw):
    """Return 'utf-16-le', 'utf-16-be' or None for BOM-less UTF-16 (many NUL bytes on one side)."""
    sample = raw[:400]
    if len(sample) < 4 or b"\x00" not in sample:
        return None
    pairs = len(sample) // 2
    even_zero = sum(1 for i in range(0, pairs * 2, 2) if sample[i] == 0)
    odd_zero = sum(1 for i in range(1, pairs * 2, 2) if sample[i] == 0)
    if odd_zero >= 0.4 * pairs and even_zero < 0.1 * pairs:
        return "utf-16-le"
    if even_zero >= 0.4 * pairs and odd_zero < 0.1 * pairs:
        return "utf-16-be"
    return None


def decode_bytes(raw, normalize=True):
    """Decode bytes tolerantly: UTF-16 BOM, UTF-8 BOM, BOM-less UTF-16, then UTF-8 with errors="replace".

    With normalize=True (default) line endings become LF.
    """
    if raw is None:
        return ""
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        text = raw.decode("utf-16", errors="replace")
    elif raw[:3] == _UTF8_BOM:
        text = raw[3:].decode("utf-8", errors="replace")
    else:
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            enc = _looks_utf16(raw)
            if enc:
                text = raw.decode(enc, errors="replace")
            else:
                text = raw.decode("utf-8", errors="replace")
        else:
            enc = _looks_utf16(raw) if "\x00" in text[:400] else None
            if enc:
                text = raw.decode(enc, errors="replace")
    if text.startswith("\ufeff"):
        text = text[1:]
    return normalize_newlines(text) if normalize else text


def _transient_read_error(exc):
    """True for the errors a concurrent replace or delete causes on Windows (never for a missing file)."""
    if not RETRY_TRANSIENT_READS or isinstance(exc, FileNotFoundError):
        return False
    if isinstance(exc, PermissionError):
        return True
    return getattr(exc, "winerror", None) in _TRANSIENT_WINERRORS or getattr(exc, "errno", None) == errno.EACCES


def _retrying(fn, path):
    """fn(path), retried while it fails with a transient read error, for at most READ_RETRY_S seconds."""
    deadline = time.monotonic() + READ_RETRY_S
    delay = 0.005
    while True:
        try:
            return fn(path)
        except OSError as e:
            if not _transient_read_error(e) or time.monotonic() >= deadline or os.path.isdir(path):
                raise  # (opening a folder also raises PermissionError on Windows: that one is final)
        time.sleep(delay)
        delay = min(delay * 2, 0.05)


def _read_all(path):
    with open(path, "rb") as f:
        return f.read()


def read_bytes(path):
    """The raw bytes of a file that another process may be replacing right now (see the module note).

    Raises OSError when the file cannot be read (FileNotFoundError at once when it does not exist).
    """
    return _retrying(_read_all, os.fspath(path))


def read_text(path, normalize=True):
    """Read a text file: UTF-8 (with or without BOM) or UTF-16 (PowerShell 5.1 '>' writes UTF-16).

    Line endings are normalized to LF unless normalize=False. Raises OSError when the file cannot be read. A read
    that collides with another process replacing the file is retried (module note).
    """
    return decode_bytes(read_bytes(path), normalize=normalize)


def _replace_with_retry(src, dst, attempts=10):
    """os.replace, retried briefly: on Windows a reader holding the target open makes it fail transiently."""
    delay = 0.02
    for i in range(attempts):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if i == attempts - 1:
                raise
            time.sleep(delay)
            delay = min(delay * 2, 0.5)


WINDOWS_MAX_PATH = 259  # the longest file path Win32 opens without long-path support (MAX_PATH 260 with the NUL)
TEMP_PREFIX_CHARS = 16  # temp names are "." + the first 16 characters of the target name + "." + 8 random + ".tmp"


class PathTooLong(OSError):
    """A write failed on Windows because a path is longer than MAX_PATH allows (no long-path support)."""


def temp_prefix(path):
    """The mkstemp prefix for a temp file next to `path`: short, so a temp name is never the longest path in a run
    folder (the Windows MAX_PATH budget)."""
    return "." + os.path.basename(path)[:TEMP_PREFIX_CHARS] + "."


_WINDOWS = os.name == "nt"
_LONG_PATH_ERRNOS = (errno.ENOENT, errno.EINVAL, errno.ENAMETOOLONG)
_LONG_PATH_WINERRORS = (2, 3, 206)  # FILE_NOT_FOUND, PATH_NOT_FOUND, FILENAME_EXCED_RANGE
_LONG_PATHS = []


def long_paths_enabled():
    """True / False from the Windows registry (LongPathsEnabled; read once); None when it cannot be read; True off
    Windows."""
    if not _WINDOWS:
        return True
    if not _LONG_PATHS:
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\FileSystem") as key:
                _LONG_PATHS.append(bool(winreg.QueryValueEx(key, "LongPathsEnabled")[0]))
        except (ImportError, OSError, ValueError):
            _LONG_PATHS.append(None)
    return _LONG_PATHS[0]


def explain_long_path(exc, *paths):
    """`exc` again, or a PathTooLong with an actionable message when it is a Windows error that a path longer than
    MAX_PATH causes (Win32 then reports only "file not found", "path not found" or "the filename or extension is too
    long") and long paths are not known to be enabled. Any other error (access denied, a full disk, ...) stays as it
    is, on a long path too."""
    if not _WINDOWS or isinstance(exc, PathTooLong) or not isinstance(exc, OSError):
        return exc
    if getattr(exc, "winerror", None) not in _LONG_PATH_WINERRORS and exc.errno not in _LONG_PATH_ERRNOS:
        return exc
    if long_paths_enabled() is True:
        return exc
    long_ones = [os.path.abspath(p) for p in paths if p and len(os.path.abspath(p)) > WINDOWS_MAX_PATH]
    if not long_ones:
        return exc
    p = max(long_ones, key=len)
    return PathTooLong(exc.errno, "path is %d characters, more than the %d Windows allows without long-path support; "
                       "move the run to a shorter folder (ub init --root <short path>) or enable Windows long paths "
                       "(LongPathsEnabled): %s" % (len(p), WINDOWS_MAX_PATH, to_posix(p)))


_LOCK_BYTE = 0x7FFFFFF0  # a byte far beyond any end of file: the locked file stays readable


def try_lock_fd(fd):
    """Lock an open file without blocking (msvcrt byte lock on Windows, flock on POSIX). True: locked; False: another
    open file holds it; None: this file system has no file locks. The OS drops the lock when the process dies."""
    if os.name == "nt":
        try:
            import msvcrt
        except ImportError:
            return None
        try:
            os.lseek(fd, _LOCK_BYTE, 0)
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            return True
        except OSError as e:
            if e.errno in (errno.EACCES, errno.EDEADLK) or getattr(e, "winerror", None) in (5, 33):
                return False
            return None
    try:
        import fcntl
    except ImportError:
        return None
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except OSError as e:
        if e.errno in (errno.EAGAIN, errno.EWOULDBLOCK, errno.EACCES):
            return False
        return None


def unlock_fd(fd):
    """Undo try_lock_fd (closing the file also drops the lock)."""
    try:
        if os.name == "nt":
            import msvcrt
            os.lseek(fd, _LOCK_BYTE, 0)
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(fd, fcntl.LOCK_UN)
    except (ImportError, OSError):
        pass


def fsync_dir(path):
    """Make renames in folder `path` durable (POSIX). Windows cannot open a folder for fsync: a no-op there."""
    if os.name == "nt":
        return
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def _write_bytes_atomic(path, data):
    path = os.path.abspath(os.fspath(path))
    parent = os.path.dirname(path)
    tmp = None
    try:
        os.makedirs(parent, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=temp_prefix(path), suffix=".tmp", dir=parent)
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            try:
                os.fsync(f.fileno())
            except OSError:
                pass
        _replace_with_retry(tmp, path)
        tmp = None
    except OSError as e:
        err = explain_long_path(e, path, tmp or os.path.join(parent, temp_prefix(path) + "12345678.tmp"))
        if err is e:
            raise
        raise err from e
    finally:
        if tmp is not None:
            try:
                os.unlink(tmp)
            except OSError:
                pass


def write_text_atomic(path, text):
    """Write UTF-8 without BOM, LF line endings, via a temp file in the same folder + os.replace.

    Parent folders are created. The target is either the old content or the full new content, never partial.
    """
    if not isinstance(text, str):
        raise TypeError("write_text_atomic expects str, got %s" % type(text).__name__)
    if text.startswith("\ufeff"):
        text = text[1:]
    _write_bytes_atomic(path, normalize_newlines(text).encode("utf-8"))


def write_json_atomic(path, obj):
    """JSON with indent=1, ensure_ascii=False and a trailing newline, written atomically."""
    write_text_atomic(path, json.dumps(obj, indent=1, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------- Markdown structure (linear line scanners)

# Candidate lines only (found in C): a fence line starts, after spaces/tabs, with 3 backticks or tildes; a heading line
# starts with '#'. fence_open / fence_closes / parse_heading then decide, so each rule has one definition.
_FENCE_CANDIDATE = re.compile(r"^[ \t]*(?:```|~~~)[^\n]*", re.MULTILINE)
_HEADING_CANDIDATE = re.compile(r"^#[^\n]*", re.MULTILINE)
_HEADING_OPEN = re.compile(r"(#{1,6})\s+")
_INFO_WORD = re.compile(r"[A-Za-z0-9_+-]*")


def fence_open(line):
    """(char, length, lang) when `line` opens a fenced code block, else None: optional spaces/tabs, then 3 or more
    backticks or tildes; a backtick fence's info string holds no backtick (```x``` is inline code). lang is the info
    string's first word, lowercased ('' when there is none)."""
    s = line.lstrip(" \t")
    ch = s[:1]
    if ch not in ("`", "~"):
        return None
    run = len(s) - len(s.lstrip(ch))
    if run < 3:
        return None
    info = s[run:]
    if ch == "`" and "`" in info:
        return None
    return ch, run, _INFO_WORD.match(info.strip()).group(0).lower()


def fence_closes(line, fence):
    """True when `line` closes the fence `fence` (char, length, ...) that fence_open returned: only that character,
    at least as many, with optional spaces/tabs around (CommonMark)."""
    t = line.strip(" \t")
    return len(t) >= fence[1] and not t.strip(fence[0])


def fence_spans(text):
    """[(open_line, close_line, char, length, lang)] for every fenced code block of `text` (LF line endings), in
    document order. Line numbers index text.split("\\n"). close_line is None for a fence left open: it runs to the end
    of the text. One pass; the cost is linear in the text."""
    text = text or ""
    spans, cur = [], None
    line_no, last = 0, 0
    for m in _FENCE_CANDIDATE.finditer(text):
        line_no += text.count("\n", last, m.start())
        last = m.start()
        if cur is None:
            f = fence_open(m.group(0))
            if f:
                cur = (line_no,) + f
        elif fence_closes(m.group(0), cur[1:3]):
            spans.append((cur[0], line_no) + cur[1:])
            cur = None
    if cur is not None:
        spans.append((cur[0], None) + cur[1:])
    return spans


def fence_mask(lines):
    """One bool per line of `lines` (a list): True inside a fenced code block, fence lines included."""
    mask = [False] * len(lines)
    for a, b, _c, _n, _lang in fence_spans("\n".join(lines)):
        end = len(lines) if b is None else b + 1
        mask[a:end] = [True] * (end - a)
    return mask


def fenced_blocks(text):
    """List of (lang_lowercase, body) for every fenced code block, in document order. A closed block's body keeps its
    lines with a trailing newline; a fence left open runs to the end of the text."""
    text = normalize_newlines(text or "")
    lines = text.split("\n")
    out = []
    for a, b, _c, _n, lang in fence_spans(text):
        if b is None:
            out.append((lang, "\n".join(lines[a + 1:])))
        else:
            body = lines[a + 1:b]
            out.append((lang, "\n".join(body) + "\n" if body else ""))
    return out


def parse_heading(line):
    """(level, title) for an ATX heading line such as '## Title ##', else None. The title is the rest of the line
    without trailing whitespace, a closing '#' run and the whitespace before it: the same result as the old pattern
    ^(#{1,6})\\s+(.*?)\\s*#*\\s*$, in linear time (that pattern backtracked cubically on long whitespace runs)."""
    m = _HEADING_OPEN.match(line)
    if m is None:
        return None
    return len(m.group(1)), line[m.end():].rstrip().rstrip("#").rstrip()


def headings(text):
    """[(line_index, level, title)] for the ATX headings of `text` (LF line endings) outside fenced code blocks, in
    order. Line indexes index text.split("\\n")."""
    text = text or ""
    spans = fence_spans(text)
    out, k = [], 0
    line_no, last = 0, 0
    for m in _HEADING_CANDIDATE.finditer(text):
        line_no += text.count("\n", last, m.start())
        last = m.start()
        while k < len(spans) and spans[k][1] is not None and spans[k][1] < line_no:
            k += 1
        if k < len(spans) and spans[k][0] <= line_no:
            continue  # inside a fence (spans[k] ends at or after this line)
        h = parse_heading(m.group(0))
        if h:
            out.append((line_no,) + h)
    return out


def section(text, heading, level=2):
    """Body of the first heading of `level` whose title starts with `heading` (case-insensitive, whitespace runs read
    as one space: the `sections` contract's prefix rule), up to the next heading of the same or a higher level,
    stripped; '' when there is none. Headings are headings() ones, so a heading line inside a fenced code block never
    starts or ends a section: the body is the one the contract validated."""
    text = normalize_newlines(text or "")
    want = " ".join(str(heading).split()).lower()
    heads = headings(text)
    for k, (i, lvl, title) in enumerate(heads):
        if lvl == level and " ".join(title.split()).lower().startswith(want):
            end = next((j for j, lv, _t in heads[k + 1:] if lv <= level), None)
            return "\n".join(text.split("\n")[i + 1:end]).strip()
    return ""


# ---------------------------------------------------------------- JSON from model output

def _reject_constant(name):
    raise ValueError("%s is not a JSON number" % name)


_JSON = json.JSONDecoder(parse_constant=_reject_constant)  # NaN and Infinity are not JSON
MAX_JSON_DEPTH = 512  # a deeper container is never an answer: the decoder is not tried on it
MAX_JSON_CANDIDATES = 64  # bracket spans tried (longest first) when salvaging JSON from prose
_JSON_TOKENS = re.compile(r'[\[\]{}"\\\n]')
_OPENER_OF = {"]": "[", "}": "{"}


def _json_spans(text):
    """(spans, lead_matched): the maximal bracket pairs of text as [(start, end_exclusive, depth)], from one linear
    pass, and whether the first non-space character is an opener that closes.

    Inside brackets JSON strings are skipped (a string also ends at a line break, which JSON never allows in a
    string); quotes outside brackets are prose. A closer that does not match the innermost opener abandons every open
    bracket, and so does nesting deeper than 8 * MAX_JSON_DEPTH (bounded memory): unmatched brackets never form a
    span. A pair is maximal when no matched pair encloses it, so JSON after a stray '[' in prose is still found, but a
    malformed container is one span and never yields a fragment of itself."""
    spans = []
    if "]" not in text and "}" not in text:
        return spans, False
    lead = len(text) - len(text.lstrip())
    lead_matched = False
    stack = []  # [pos, char, provisional maximal spans inside it, depth]
    in_str, skip = False, -1

    def abandon():
        for e in stack:
            if e[2]:
                spans.extend(e[2])
        del stack[:]

    for m in _JSON_TOKENS.finditer(text):
        i, ch = m.start(), m.group()
        if in_str:
            if ch == "\n":
                in_str = False
            elif i != skip:
                if ch == "\\":
                    skip = i + 1
                elif ch == '"':
                    in_str = False
            continue
        if ch == '"':
            in_str = bool(stack)
        elif ch == "[" or ch == "{":
            if len(stack) >= 8 * MAX_JSON_DEPTH:
                abandon()
            stack.append([i, ch, None, 1])
        elif ch == "]" or ch == "}":
            if not stack or stack[-1][1] != _OPENER_OF[ch]:
                abandon()
                continue
            e = stack.pop()
            span = (e[0], i + 1, e[3])
            if stack:
                top = stack[-1]
                if top[3] <= e[3]:
                    top[3] = e[3] + 1
                if top[2] is None:
                    top[2] = [span]
                else:
                    top[2].append(span)
            else:
                spans.append(span)
                lead_matched = lead_matched or e[0] == lead
    abandon()
    return spans, lead_matched


def extract_json(text):
    """Extract a JSON object or array from model output, in time linear in the text.

    Order: the whole text; fenced blocks (```json first, then other fences, each in document order); then the longest
    of the maximal bracket spans that decodes (at most MAX_JSON_CANDIDATES tried, longest first). A closed but
    malformed container is never mined for a fragment of itself, and a text that starts with an opener that never
    closes is a malformed document, not prose. A cut-off or mismatched document after other text (a preamble, an
    unclosed fence) can still yield an inner object, which the contract's schema then refuses: that keeps the salvage
    of 'Draft: <cut off> Final: <document>'. NaN and Infinity are rejected. Raises ValueError when nothing parses.
    """
    if text is None:
        raise ValueError("no JSON found: the text is empty")
    if isinstance(text, bytes):
        text = decode_bytes(text)
    text = normalize_newlines(text).lstrip("\ufeff")
    stripped = text.strip()
    if not stripped:
        raise ValueError("no JSON found: the text is empty")
    first_error = None
    try:
        value = _JSON.decode(stripped)
        if isinstance(value, (dict, list)):
            return value
    except RecursionError:
        first_error = "nested too deeply"
    except ValueError as e:
        first_error = str(e)
    blocks = fenced_blocks(text)
    ordered = [b for lang, b in blocks if lang == "json"] + [b for lang, b in blocks if lang != "json"]
    for body in ordered:
        try:
            value = _JSON.decode(body.strip())
        except (ValueError, RecursionError):
            continue
        if isinstance(value, (dict, list)):
            return value
    spans, lead_matched = _json_spans(text)
    if stripped[0] in "{[" and not lead_matched:
        raise ValueError("the text starts with JSON that is not valid: %s" % first_error)
    error = None
    for a, b, depth in heapq.nlargest(MAX_JSON_CANDIDATES, spans, key=lambda s: (s[1] - s[0], -s[0])):
        if depth > MAX_JSON_DEPTH:
            continue
        try:
            value, _end = _JSON.raw_decode(text[a:b])  # a slice: error positions (and their cost) stay local
        except RecursionError:
            continue
        except ValueError as e:
            error = error or "the JSON at character %d is not valid: %s" % (a, e)
            continue
        if isinstance(value, (dict, list)):
            return value
    raise ValueError("no JSON object or array found in the text" + ("; %s" % error if error else ""))


def loads_strict(text):
    """Parse text that must be exactly one JSON object or array: a file the engine reads back, or a FILE-protocol
    .json block. A BOM, surrounding whitespace and one enclosing code fence are tolerated; nothing else is, and no
    fragment is ever salvaged. NaN and Infinity are rejected. Raises ValueError."""
    if isinstance(text, bytes):
        text = decode_bytes(text)
    text = normalize_newlines(text or "").lstrip("\ufeff").strip()
    lines = text.split("\n")
    if len(lines) >= 2:
        f = fence_open(lines[0])
        if f and fence_closes(lines[-1], f):
            text = "\n".join(lines[1:-1])
    try:
        value = _JSON.decode(text)
    except RecursionError:
        raise ValueError("JSON nested too deeply")
    if not isinstance(value, (dict, list)):
        raise ValueError("expected a JSON object or array")
    return value


def read_json_strict(path):
    """read_text + loads_strict: for JSON files the engine owns. Raises OSError or ValueError."""
    return loads_strict(read_text(path))


def read_json(path):
    """Read a JSON file tolerantly (BOM, UTF-16, fences, preamble). A file that starts with a malformed document
    raises instead of yielding a fragment of itself (extract_json). Raises OSError or ValueError."""
    text = read_text(path)
    try:
        return json.loads(text)
    except (ValueError, RecursionError):
        return extract_json(text)


def read_json_or(path, default=None):
    """read_json, or `default` when the file is missing, unreadable after the transient retries, or not JSON."""
    try:
        return read_json(path)
    except (OSError, ValueError):
        return default


def sha256_text(text):
    """SHA-256 hex of the UTF-8 encoding of text."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_file(path):
    """SHA-256 hex of the raw file bytes (a read colliding with a concurrent replace is retried)."""
    return _retrying(_sha256_of, os.fspath(path))


def is_ascii(text):
    """True when every character is 7-bit ASCII."""
    try:
        text.encode("ascii")
    except UnicodeEncodeError:
        return False
    return True


def append_line(path, line):
    """Append one line (LF-terminated, UTF-8) in a single write call; creates parent folders."""
    path = os.fspath(path)
    parent = os.path.dirname(os.path.abspath(path))
    os.makedirs(parent, exist_ok=True)
    line = normalize_newlines(line).rstrip("\n").replace("\n", " ") + "\n"
    data = line.encode("utf-8")
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, "O_BINARY", 0), 0o644)
    try:
        locked = _lock_append(fd)
        try:
            view = memoryview(data)
            while view:
                n = os.write(fd, view)
                view = view[n:]
        finally:
            if locked:
                _unlock_append(fd)
    finally:
        os.close(fd)


_APPEND_LOCK_AT = 0x7FFFFFF0  # a byte far beyond any log's end: every appender locks the same byte (Windows)


def _lock_append(fd):
    """Windows: the CRT's O_APPEND (seek to end, then write) is not atomic across processes, so parallel workers
    appending to logs/calls.jsonl could interleave. Appenders serialize on a byte lock beyond EOF (no sidecar file;
    readers are not blocked). POSIX O_APPEND writes are atomic: no lock. Returns True when a lock is held."""
    if os.name != "nt":
        return False
    try:
        import msvcrt
    except ImportError:
        return False
    for _ in range(500):
        try:
            os.lseek(fd, _APPEND_LOCK_AT, 0)
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            return True
        except OSError:
            time.sleep(0.01)
    return False


def _unlock_append(fd):
    try:
        import msvcrt
        os.lseek(fd, _APPEND_LOCK_AT, 0)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
    except (ImportError, OSError):
        pass


def now_iso():
    """UTC ISO-8601 timestamp with a trailing Z, second precision (3.1 item 7)."""
    return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def to_posix(path):
    """Absolute path with forward slashes, for JSON, cards and docs (3.1 item 5)."""
    return os.path.abspath(os.fspath(path)).replace("\\", "/")


def glob_in(folder, *parts, recursive=False):
    """glob.glob of the pattern `parts` below `folder`, whose own path is taken literally (glob.escape): a run or
    project folder named 'client [2026]' matches itself, never the character class [2026]. Every glob over a folder
    the user named goes through here."""
    return glob.glob(os.path.join(glob.escape(os.fspath(folder)), *parts), recursive=recursive)


_LONG_PREFIX = "\\\\?\\"
_LONG_UNC_PREFIX = "\\\\?\\UNC\\"


def real_path(path):
    """os.path.realpath without a stray Windows extended-length prefix.

    On Windows, realpath() resolves the path twice and keeps the \\\\?\\ prefix when the two attempts fail with
    different errors. That happens when another process creates a missing parent folder in between (parallel workers
    writing into the same new folder), so the same path sometimes comes back as \\\\?\\C:\\... and sometimes as C:\\...,
    and a prefix comparison against the root wrongly says "outside". The prefix is dropped unless the caller passed
    it in.
    """
    path = os.fspath(path)
    real = os.path.realpath(path)
    if isinstance(real, str) and real.startswith(_LONG_PREFIX) and not path.startswith(_LONG_PREFIX):
        if real.startswith(_LONG_UNC_PREFIX):
            return "\\\\" + real[len(_LONG_UNC_PREFIX):]
        return real[len(_LONG_PREFIX):]
    return real
