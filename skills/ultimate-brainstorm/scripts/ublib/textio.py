"""Tolerant text reads, atomic writes, JSON extraction and hashing (KIT_SPEC 3.1, 4.8).

Frozen API (4.8):
    read_text(path) -> str
    write_text_atomic(path, text) -> None
    write_json_atomic(path, obj) -> None
    extract_json(text) -> object
    sha256_text(text) -> str ; sha256_file(path) -> str ; is_ascii(text) -> bool

Extras (not frozen, safe to use): decode_bytes, normalize_newlines, read_json, append_line, now_iso, to_posix.
"""

import datetime
import hashlib
import json
import os
import re
import tempfile
import time

__all__ = [
    "read_text", "write_text_atomic", "write_json_atomic", "extract_json",
    "sha256_text", "sha256_file", "is_ascii",
    "decode_bytes", "normalize_newlines", "read_json", "append_line", "now_iso", "to_posix",
]

_UTF8_BOM = b"\xef\xbb\xbf"


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


def read_text(path, normalize=True):
    """Read a text file: UTF-8 (with or without BOM) or UTF-16 (PowerShell 5.1 '>' writes UTF-16).

    Line endings are normalized to LF unless normalize=False. Raises OSError when the file cannot be read.
    """
    with open(os.fspath(path), "rb") as f:
        raw = f.read()
    return decode_bytes(raw, normalize=normalize)


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


def _write_bytes_atomic(path, data):
    path = os.path.abspath(os.fspath(path))
    parent = os.path.dirname(path)
    os.makedirs(parent, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix="." + os.path.basename(path)[:40] + ".", suffix=".tmp", dir=parent)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            try:
                os.fsync(f.fileno())
            except OSError:
                pass
        _replace_with_retry(tmp, path)
        tmp = None
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


_FENCE_RE = re.compile(r"^[ \t]*(`{3,}|~{3,})[ \t]*([A-Za-z0-9_+-]*)[^\n]*\n(.*?)^[ \t]*\1[ \t]*$",
                       re.MULTILINE | re.DOTALL)


def fenced_blocks(text):
    """List of (lang_lowercase, body) for every fenced code block, in document order."""
    return [(m.group(2).lower(), m.group(3)) for m in _FENCE_RE.finditer(normalize_newlines(text or ""))]


def _scan_json(text):
    """Every decodable JSON object/array embedded in text, as (start, end, value), scanning left to right."""
    dec = json.JSONDecoder()
    found = []
    i, n = 0, len(text)
    while i < n:
        a = text.find("{", i)
        b = text.find("[", i)
        cands = [p for p in (a, b) if p >= 0]
        if not cands:
            break
        pos = min(cands)
        try:
            value, end = dec.raw_decode(text, pos)
        except (ValueError, RecursionError):
            i = pos + 1
            continue
        if isinstance(value, (dict, list)):
            found.append((pos, end, value))
            i = end
        else:
            i = pos + 1
    return found


def extract_json(text):
    """Extract a JSON object or array from model output.

    Order: the whole text; fenced blocks (```json first, then other fences, each in document order); then the
    longest JSON object/array embedded in surrounding prose. Raises ValueError when nothing parses.
    """
    if text is None:
        raise ValueError("no JSON found: empty output")
    if isinstance(text, bytes):
        text = decode_bytes(text)
    text = normalize_newlines(text).lstrip("\ufeff")
    stripped = text.strip()
    if not stripped:
        raise ValueError("no JSON found: empty output")
    try:
        value = json.loads(stripped)
        if isinstance(value, (dict, list)):
            return value
    except (ValueError, RecursionError):
        pass
    blocks = fenced_blocks(text)
    ordered = [b for lang, b in blocks if lang == "json"] + [b for lang, b in blocks if lang != "json"]
    for body in ordered:
        try:
            value = json.loads(body.strip())
        except (ValueError, RecursionError):
            continue
        if isinstance(value, (dict, list)):
            return value
    found = _scan_json(text)
    if found:
        best = max(found, key=lambda t: (t[1] - t[0], -t[0]))
        return best[2]
    raise ValueError("no JSON object or array found in output")


def read_json(path):
    """Read a JSON file tolerantly (BOM, UTF-16, fences, preamble). Raises OSError or ValueError."""
    text = read_text(path)
    try:
        return json.loads(text)
    except (ValueError, RecursionError):
        return extract_json(text)


def sha256_text(text):
    """SHA-256 hex of the UTF-8 encoding of text."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_file(path):
    """SHA-256 hex of the raw file bytes."""
    h = hashlib.sha256()
    with open(os.fspath(path), "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


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
