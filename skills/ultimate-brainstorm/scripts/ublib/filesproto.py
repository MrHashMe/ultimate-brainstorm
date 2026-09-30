"""FILE protocol parse and path guards (KIT_SPEC 4.6).

    === FILE: chosen/containers.md ===
    ...content...
    === END FILE ===
    === STATUS ===
    {"status":"complete","assumptions":[],"open_questions":[],"reason":""}
    === END STATUS ===

Frozen API (4.8):
    parse_file_blocks(text) -> ({relpath: content}, status_dict_or_None, warnings)
    write_file_blocks(files, root, allowed_globs) -> list of written absolute paths; raises PathError

Extras: PathError, WriteError, ALLOWED_EXTS, STATUS_VALUES, check_relpath, glob_match, validate_files,
structural_errors, split_output, recover, inside, JOURNAL_PREFIX.

The write is all-or-nothing (rule 4.6.4), also across a crash: see write_file_blocks and recover.
"""

import hashlib
import json
import os
import re
import tempfile
import time
import unicodedata

from . import textio

__all__ = [
    "PathError", "WriteError", "ALLOWED_EXTS", "STATUS_VALUES",
    "parse_file_blocks", "write_file_blocks", "check_relpath", "glob_match", "validate_files", "split_output",
    "structural_errors", "recover", "inside", "JOURNAL_PREFIX",
]

ALLOWED_EXTS = (".md", ".yaml", ".yml", ".json", ".mmd")
STATUS_VALUES = ("complete", "partial", "blocked")

_DRIVE_RE = re.compile(r"^[A-Za-z]:")
_BAD_CHARS = set('<>:"|?*')
# Unicode categories never allowed in a path segment: controls, format characters (zero-width, bidi overrides),
# private use, surrogates, unassigned, line and paragraph separators. Spaces other than U+0020 are refused as well.
_BAD_CATEGORIES = ("Cc", "Cf", "Co", "Cs", "Cn", "Zl", "Zp")
# Parse warnings that make an output invalid (never written, 4.6.4): truncation, and ambiguous framing.
_STRUCTURAL = ("has no END FILE marker", "inside its content cut it short", "outside any FILE block",
               "duplicate FILE block")
_RESERVED = ({"con", "prn", "aux", "nul", "conin$", "conout$"} | {"com%d" % i for i in range(1, 10)} |
             {"lpt%d" % i for i in range(1, 10)} | {"com\u00b9", "com\u00b2", "com\u00b3", "lpt\u00b9", "lpt\u00b2",
                                                    "lpt\u00b3"})


class PathError(ValueError):
    """A FILE-protocol path or content that must not be written."""


class WriteError(PathError):
    """Valid FILE-protocol output that could not be written (an OSError on this machine, not a fault of the output).

    A subclass of PathError so existing handlers keep working; callers that retry model output tell the two apart:
    a write error is retried locally, never answered with a repair call."""


# ---------------------------------------------------------------- parsing

def _marker(line):
    """("file", path) | ("end_file", None) | ("status", None) | ("end_status", None) | None for one line. String
    operations only, so a long line costs linear time (the old lazy regex was quadratic in its whitespace)."""
    s = line.strip()
    if len(s) < 6 or not s.startswith("===") or not s.endswith("==="):
        return None
    inner = s[3:-3].strip()
    if inner.startswith("FILE:"):
        return "file", inner[5:].strip()
    word = " ".join(inner.split())
    if word in ("END FILE", "STATUS", "END STATUS"):
        return word.lower().replace(" ", "_"), None
    return None


def parse_file_blocks(text):
    """Parse FILE blocks and the optional STATUS trailer.

    Returns (files, status, warnings):
      files    {relpath: content} in first-seen order; a repeated path keeps the LAST copy, with a warning that
               structural_errors reports (a path printed twice is ambiguous framing: a document that quotes the
               protocol can frame a second copy). Paths are NFC-normalized.
      status   the STATUS JSON object, or None when absent or unparseable (warning logged)
      warnings list of strings
    Text outside the blocks is ignored. A block that is not closed ends at the next FILE/STATUS marker or at the end
    of the text, with a warning. An '=== END FILE ===' line while no FILE block is open means an earlier one was part
    of a file's content (a document that quotes the protocol, the file cut short there), wherever it stands: right
    after a close, after chatter, or after a STATUS block the content quoted. It is a warning that structural_errors
    reports, naming the FILE block seen last. Content keeps its lines exactly (LF), with one trailing newline.
    """
    files = {}
    warnings = []
    status = None
    status_seen = False
    lines = textio.normalize_newlines(text or "").split("\n")
    cur_path, cur_lines, mode = None, [], None  # mode: None | "file" | "status"
    last_file = None  # the FILE block seen last

    def close(unterminated):
        nonlocal status, status_seen
        if mode == "file":
            if unterminated:
                warnings.append("FILE block %s has no END FILE marker" % cur_path)
            if cur_path in files:
                warnings.append("duplicate FILE block %s (ambiguous framing: the path is printed twice)" % cur_path)
                del files[cur_path]
            body = "\n".join(cur_lines)
            files[cur_path] = body + "\n" if body and not body.endswith("\n") else body
        elif mode == "status":
            if unterminated:
                warnings.append("STATUS block has no END STATUS marker")
            if status_seen:
                warnings.append("duplicate STATUS block: the last copy wins")
            status_seen = True
            raw = "\n".join(cur_lines).strip()
            try:
                value = json.loads(raw) if raw else None
                if value is None:
                    raise ValueError("empty")
            except (ValueError, RecursionError):
                try:
                    value = textio.extract_json(raw)
                except (ValueError, RecursionError):
                    value = None
            if isinstance(value, dict):
                status = value
                if value.get("status") not in STATUS_VALUES:
                    warnings.append("STATUS status %r is not one of %s" % (value.get("status"), "|".join(STATUS_VALUES)))
            else:
                status = None
                warnings.append("STATUS block is not a JSON object")

    for line in lines:
        mk = _marker(line)
        kind = mk[0] if mk else None
        if kind == "file":
            if mode is not None:
                close(True)
            cur_path, cur_lines, mode = unicodedata.normalize("NFC", mk[1]), [], "file"
            last_file = cur_path
            continue
        if kind == "status":
            if mode is not None:
                close(True)
            cur_path, cur_lines, mode = None, [], "status"
            continue
        if mode == "file" and kind == "end_file":
            close(False)
            cur_path, cur_lines, mode = None, [], None
            continue
        if mode == "status" and kind == "end_status":
            close(False)
            cur_path, cur_lines, mode = None, [], None
            continue
        if mode is None and kind == "end_file":
            if last_file is not None:
                warnings.append("FILE block %s: an '=== END FILE ===' line inside its content cut it short (ambiguous "
                                "framing; write the marker text differently inside a file)" % last_file)
            else:
                warnings.append("an '=== END FILE ===' line outside any FILE block (ambiguous framing)")
            continue
        if mode is not None:
            cur_lines.append(line)
    if mode is not None:
        # A trailing empty line from the final "\n" split is not content.
        while cur_lines and cur_lines[-1] == "":
            cur_lines.pop()
        close(True)
    return files, status, warnings


# ---------------------------------------------------------------- globs and path guards

def _glob_to_regex(pattern):
    i, n, out = 0, len(pattern), []
    while i < n:
        c = pattern[i]
        if c == "*":
            if pattern[i:i + 2] == "**":
                if pattern[i:i + 3] == "**/":
                    out.append("(?:[^/]+/)*")
                    i += 3
                else:
                    out.append(".*")
                    i += 2
                continue
            out.append("[^/]*")
        elif c == "?":
            out.append("[^/]")
        elif c == "[":
            j = pattern.find("]", i + 1)
            if j > i + 1:
                body = pattern[i + 1:j]
                if body.startswith("!"):
                    body = "^" + body[1:]
                out.append("[" + body.replace("\\", "\\\\") + "]")
                i = j + 1
                continue
            out.append(re.escape(c))
        else:
            out.append(re.escape(c))
        i += 1
    return "^" + "".join(out) + "$"


_GLOB_CACHE = {}


def glob_match(path, pattern):
    """Case-sensitive glob match on forward-slash paths: * and ? stay inside one segment, ** spans segments."""
    rx = _GLOB_CACHE.get(pattern)
    if rx is None:
        rx = re.compile(_glob_to_regex(pattern.replace("\\", "/")))
        _GLOB_CACHE[pattern] = rx
    return bool(rx.match(path))


def _shown(path):
    """A path for an error message: invisible characters written as escapes."""
    return path.encode("ascii", "backslashreplace").decode("ascii")


def check_relpath(rel, allowed_globs=None):
    """Return the normalized relative path or raise PathError (rules 4.6.1 and 4.6.2).

    Rejected: empty, backslashes, absolute paths, drive letters, '..', any segment starting with '.', empty
    segments, control, invisible (zero-width, bidi), unassigned or Windows-reserved characters and spaces other than
    U+0020, reserved device names, segments ending in space or dot, extensions other than ALLOWED_EXTS, and (when
    allowed_globs is not None) paths matching no allowed glob. The returned path is NFC-normalized.
    """
    if not isinstance(rel, str) or not rel.strip():
        raise PathError("empty path")
    p = unicodedata.normalize("NFC", rel.strip())
    if "\\" in p:
        raise PathError("%s: use forward slashes" % p)
    if p.startswith("/") or _DRIVE_RE.match(p):
        raise PathError("%s: absolute paths and drive letters are not allowed" % p)
    segs = p.split("/")
    for seg in segs:
        if seg == "":
            raise PathError("%s: empty path segment" % p)
        if seg == "..":
            raise PathError("%s: '..' is not allowed" % p)
        if seg.startswith("."):
            raise PathError("%s: names starting with '.' are not allowed" % p)
        bad = [ch for ch in seg if ch in _BAD_CHARS or unicodedata.category(ch) in _BAD_CATEGORIES
               or (ch != " " and unicodedata.category(ch) == "Zs")]
        if bad:
            raise PathError("%s: invalid character U+%04X in path" % (_shown(p), ord(bad[0])))
        if seg.endswith(" ") or seg.endswith("."):
            raise PathError("%s: a name must not end with a space or a dot" % p)
        if seg.split(".")[0].rstrip(" ").lower() in _RESERVED:
            raise PathError("%s: reserved device name" % p)
    ext = os.path.splitext(segs[-1])[1].lower()
    if ext not in ALLOWED_EXTS:
        raise PathError("%s: extension %s is not allowed (allowed: %s)" % (p, ext or "(none)", " ".join(ALLOWED_EXTS)))
    if allowed_globs is not None:
        if not any(glob_match(p, g) for g in allowed_globs):
            raise PathError("%s: does not match any allowed glob (%s)" % (p, ", ".join(allowed_globs) or "none"))
    return p


def validate_files(files, allowed_globs=None):
    """Errors (list of str) for a parsed {relpath: content} map (rule 4.6.3): path guards, empty content, two paths
    that differ only in letter case (one file on Windows and macOS), and .json files that are not strict JSON (an
    object or array; one enclosing code fence is tolerated)."""
    errors = []
    if not files:
        errors.append("no FILE blocks found")
    folded = {}
    for rel, content in files.items():
        try:
            norm = check_relpath(rel, allowed_globs)
        except PathError as e:
            errors.append(str(e))
            continue
        if not (content or "").strip():
            errors.append("%s: content is empty" % rel)
            continue
        key = unicodedata.normalize("NFC", norm.casefold())
        if key in folded:
            errors.append("%s and %s differ only in letter case (one file on Windows and macOS)" % (folded[key], rel))
        folded.setdefault(key, rel)
        if norm.lower().endswith(".json"):
            try:
                textio.loads_strict(content)
            except ValueError as e:
                errors.append("%s: not valid JSON: %s" % (rel, e))
    return errors


def structural_errors(warnings):
    """Parse warnings that make an output invalid, so it is never written (rule 4.6.4): an unterminated FILE block
    (usually truncated output), an END FILE line inside a file's content (the file would be cut short) and a path
    printed twice (ambiguous framing). Other warnings (STATUS problems) stay warnings here."""
    return [w for w in warnings or [] if any(s in w for s in _STRUCTURAL)]


# ---------------------------------------------------------------- writing

JOURNAL_PREFIX = ".ub-split-"  # <root>/.ub-split-<random>.json: one per commit, locked while that commit runs
JOURNAL_STALE_S = 600  # without file locks, a younger journal may belong to a live commit and is left alone


def inside(root, path):
    """True when `path` is `root` or lies below it, compared after resolving symlinks and junctions (textio.real_path,
    see rule 4.6.6) and with the platform's case rules. The one containment test for split roots and their files."""
    r = os.path.normcase(textio.real_path(os.path.abspath(os.fspath(root)))).rstrip("\\/")
    p = os.path.normcase(textio.real_path(os.path.abspath(os.fspath(path))))
    return p == r or p.startswith(r + os.sep)


def _file_bytes(rel, content):
    """The bytes written for one FILE block: UTF-8 without BOM, LF, a final newline. A .json file is written as
    canonical JSON (indent 1), so a register on disk is plain JSON whatever fence or spacing the model used."""
    if rel.lower().endswith(".json"):
        text = json.dumps(textio.loads_strict(content), indent=1, ensure_ascii=False) + "\n"
    else:
        text = content[1:] if content.startswith("\ufeff") else content
        if not text.endswith("\n"):
            text += "\n"
    return textio.normalize_newlines(text).encode("utf-8")


def _plan(files, root_abs, allowed_globs):
    """[(target, bytes)] for validated files: every target resolves inside root_abs, is not a folder, and no two
    entries name the same file on this system."""
    plan, seen = [], {}
    for rel, content in files.items():
        norm = check_relpath(rel, allowed_globs)
        target = textio.real_path(os.path.join(root_abs, *norm.split("/")))
        if not inside(root_abs, target) or os.path.normcase(target) == os.path.normcase(root_abs):
            raise PathError("%s: resolves outside the output root" % rel)
        if os.path.isdir(target):
            raise PathError("%s: a folder with that name already exists" % textio.to_posix(target))
        key = os.path.normcase(target)
        if key in seen:
            raise PathError("%s and %s are the same file on this system" % (seen[key], rel))
        seen[key] = rel
        plan.append((target, _file_bytes(norm, content)))
    return plan


def write_file_blocks(files, root, allowed_globs):
    """Validate every path and content first, then write all files under root, all or none (rule 4.6.4).

    Nothing is written when any entry is invalid or allowed_globs names no glob (PathError: a writer never lets the
    model choose its paths freely). A write that fails on this machine raises WriteError and leaves every target as
    it was; a crash in the middle is finished by the next write into root (recover). Returns the written absolute
    paths (native form, in the order of `files`).
    """
    errors = validate_files(files, allowed_globs)
    if errors:
        raise PathError("; ".join(errors))
    return _write_validated(files, root, allowed_globs)


def _write_validated(files, root, allowed_globs):
    # A writer always names what it may write: None (check_relpath's "no glob check", for validation only) or an empty
    # list never lets a model choose paths freely.
    if not allowed_globs:
        raise PathError("no allowed globs: refusing to write")
    # textio.real_path, not os.path.realpath: parallel workers create the same new sub-folder (13.2-A/B/C all write
    # 11_PROPOSAL/sections/), and realpath() of a file in a folder that appears mid-call can come back with a \\?\
    # prefix on Windows, which the prefix comparison would report as "outside the output root".
    root_abs = textio.real_path(os.path.abspath(os.fspath(root)))
    plan = _plan(files, root_abs, allowed_globs)
    try:
        recover(root_abs)
        _commit(root_abs, plan)
    except OSError as e:
        raise WriteError("could not write the files: %s" % textio.explain_long_path(e, *[t for t, _d in plan]))
    return [target for target, _d in plan]


def _reserve(target, suffix, data=None):
    """A new file next to target named textio.temp_prefix(target) + random + suffix, holding data (fsynced)."""
    fd, path = tempfile.mkstemp(prefix=textio.temp_prefix(target), suffix=suffix, dir=os.path.dirname(target))
    try:
        with os.fdopen(fd, "wb") as f:
            if data:
                f.write(data)
                f.flush()
                try:
                    os.fsync(f.fileno())
                except OSError:
                    pass
    except BaseException:
        _remove_quiet([path])
        raise
    return path


def _remove_quiet(paths):
    for p in paths:
        try:
            if p and os.path.lexists(p):
                os.unlink(p)
        except OSError:
            pass


def _sha_or_none(path):
    try:
        return textio.sha256_file(path)
    except FileNotFoundError:
        return None


def _rel(root, path):
    return os.path.relpath(path, root).replace("\\", "/") if path else None


def _abs(root, rel):
    return os.path.join(root, *rel.split("/")) if rel else None


def _commit(root, plan):
    """Write plan [(target, bytes)] under root, all or none, also across a crash (rule 4.6.4):
    1. every file goes to a temp next to its target (fsynced), and every existing target gets a reserved backup name;
    2. a journal <root>/.ub-split-*.json lists them with the old and new SHA-256; it is fsynced and stays locked
       until the commit ends, so recover() never touches a live commit;
    3. existing targets move aside to their backup names. A target that another process holds open (Windows) fails
       here, before anything changed: the moved ones go back, the journal is marked aborted (recover() then only
       removes what is left), the temps and backups go and a WriteError follows;
    4. the temps are renamed onto the now free target names, and the folders are fsynced (POSIX);
    5. the backups, then the journal, are deleted.
    A crash after step 2 leaves the journal: recover() rolls that commit forward (back once it is marked aborted)."""
    made, entries = [], []
    dirs = sorted(set(os.path.dirname(t) for t, _d in plan) | {root})
    try:
        for target, data in plan:
            os.makedirs(os.path.dirname(target), exist_ok=True)
            tmp = _reserve(target, ".tmp", data)
            made.append(tmp)
            old = _sha_or_none(target)
            bak = None
            if old is not None:
                bak = _reserve(target, ".bak")
                made.append(bak)
            entries.append({"target": target, "tmp": tmp, "bak": bak, "old": old,
                            "new": hashlib.sha256(data).hexdigest()})
        for d in dirs:
            textio.fsync_dir(d)
        journal = _Journal.create(root, entries)
    except BaseException:
        _remove_quiet(made)
        raise
    try:
        moved = []
        try:
            for e in entries:
                if e["bak"]:
                    textio._replace_with_retry(e["target"], e["bak"])
                    moved.append(e)
        except OSError:
            for e in reversed(moved):  # nothing has changed yet: put the moved targets back
                textio._replace_with_retry(e["bak"], e["target"])
            # every target is as it was: the journal says so before anything is removed, so an interrupt from here on
            # leaves a commit recover() undoes, never one it rolls forward with only some of its temps. The temps go
            # while the journal is still locked, so a recover() that takes the lock after the unlock below finds
            # nothing left to do: the failed commit stays undone (the WriteError contract)
            journal.mark_aborted()
            _remove_quiet(made)
            journal.close(delete=True)
            raise
        for e in entries:
            textio._replace_with_retry(e["tmp"], e["target"])
        for d in dirs:
            textio.fsync_dir(d)
        _remove_quiet([e["bak"] for e in entries])
        journal.close(delete=True)
    finally:
        journal.close(delete=False)  # an exception above: the journal stays for recover()


class _Journal(object):
    """The journal file of one commit, locked (textio.try_lock_fd) while the commit runs."""

    def __init__(self, path, fd):
        self.path, self.fd = path, fd
        self.body = None

    @classmethod
    def create(cls, root, entries):
        fd, path = tempfile.mkstemp(prefix=JOURNAL_PREFIX, suffix=".json", dir=root)
        j = cls(path, fd)
        try:
            deadline = time.monotonic() + 5.0
            while textio.try_lock_fd(fd) is False and time.monotonic() < deadline:
                time.sleep(0.01)  # a recover() is reading this brand-new file: it lets go at once
            j.body = {"schema": 1, "entries": [dict(e, target=_rel(root, e["target"]), tmp=_rel(root, e["tmp"]),
                                                    bak=_rel(root, e["bak"])) for e in entries]}
            j._write(j.body)
            textio.fsync_dir(root)
        except BaseException:
            j.close(delete=True)
            raise
        return j

    def _write(self, body):
        data = (json.dumps(body, ensure_ascii=True) + "\n").encode("ascii")
        os.lseek(self.fd, 0, 0)
        os.ftruncate(self.fd, 0)
        view = memoryview(data)
        while view:
            view = view[os.write(self.fd, view):]
        try:
            os.fsync(self.fd)
        except OSError:
            pass

    def mark_aborted(self):
        """Rewrite the (still locked) journal as {"schema", "aborted": true, "entries"}: its targets are back as they
        were, so recover() removes what is left of the commit and never rolls it forward. A rewrite cut short leaves a
        journal recover() cannot parse, which it treats as a commit that changed nothing: also true here."""
        self._write(dict(self.body, aborted=True))

    def close(self, delete):
        fd, self.fd = self.fd, None
        if fd is not None:
            textio.unlock_fd(fd)
            try:
                os.close(fd)
            except OSError:
                pass
            if delete:
                _remove_quiet([self.path])  # (a recover() that opens it now finds a finished commit: a no-op)
                textio.fsync_dir(os.path.dirname(self.path))


def _roll_forward(root, entries):
    """Finish a journaled commit: every target gets its new content unless it changed since the commit began (a
    newer write won). Raises OSError when a file cannot be placed now; the journal then stays."""
    for e in entries:
        target, tmp, bak = _abs(root, e["target"]), _abs(root, e.get("tmp")), _abs(root, e.get("bak"))
        cur = _sha_or_none(target)
        if cur == e.get("new"):
            continue
        if tmp and os.path.exists(tmp) and cur in (None, e.get("old")):
            textio._replace_with_retry(tmp, target)
        elif cur is None and bak and os.path.exists(bak):
            textio._replace_with_retry(bak, target)  # the new content is gone: keep the old rather than nothing
    for d in sorted(set(os.path.dirname(_abs(root, e["target"])) for e in entries)):
        textio.fsync_dir(d)
    _remove_quiet([_abs(root, e.get(k)) for e in entries for k in ("tmp", "bak")])


def _roll_back(root, entries):
    """Finish an aborted commit (its journal says "aborted"): its targets were put back before it was marked, so no
    target gets new content; a target that is missing while its backup is there gets the backup back. Then the temps
    and backups go. Raises OSError when a backup cannot be put back now; the journal then stays."""
    for e in entries:
        target, bak = _abs(root, e["target"]), _abs(root, e.get("bak"))
        if bak and os.path.exists(bak) and not os.path.lexists(target):
            textio._replace_with_retry(bak, target)
    for d in sorted(set(os.path.dirname(_abs(root, e["target"])) for e in entries)):
        textio.fsync_dir(d)
    _remove_quiet([_abs(root, e.get(k)) for e in entries for k in ("tmp", "bak")])


def recover(root):
    """Finish every FILE-protocol commit into `root` that a crash interrupted (its journal is left and nobody holds
    its lock): roll it forward, or back when its journal says it was aborted. Journals of live commits are left alone.
    Best effort, never raises: a journal that cannot be finished now stays for the next call. Every write into root
    calls this first. Returns the number of commits finished."""
    root = textio.real_path(os.path.abspath(os.fspath(root)))
    try:
        names = [n for n in os.listdir(root) if n.startswith(JOURNAL_PREFIX) and n.endswith(".json")]
    except OSError:
        return 0
    paths = []
    for n in names:
        p = os.path.join(root, n)
        try:
            paths.append((os.path.getmtime(p), p))
        except OSError:
            continue
    done = 0
    for mtime, path in sorted(paths):
        try:
            fd = os.open(path, os.O_RDWR | getattr(os, "O_BINARY", 0))
        except OSError:
            continue
        j = _Journal(path, fd)
        finished = False
        try:
            got = textio.try_lock_fd(fd)
            old_enough = time.time() - mtime > JOURNAL_STALE_S
            if got is False or (got is None and not old_enough):
                continue  # a live commit
            os.lseek(fd, 0, 0)  # (taking the lock moved the file position on Windows)
            chunks = []
            while True:
                chunk = os.read(fd, 1 << 16)
                if not chunk:
                    break
                chunks.append(chunk)
            try:
                body = json.loads(b"".join(chunks).decode("utf-8"))
                entries = body["entries"]
                if not isinstance(entries, list) or not all(isinstance(e, dict) and e.get("target") for e in entries):
                    raise ValueError("bad entries")
            except (ValueError, KeyError, TypeError):
                # written only part way: a crash before step 3 (nothing moved yet) or while an aborted commit was
                # being marked (every target already back)
                finished = old_enough
                continue
            if body.get("aborted") is True:
                _roll_back(root, entries)
            else:
                _roll_forward(root, entries)
            finished = True
            done += 1
        except (OSError, ValueError, TypeError):
            continue
        finally:
            j.close(delete=finished)
    return done


def split_output(text, root, allowed_globs, status_out=None, required=None, status_required=False, parsed=None):
    """Parse FILE-protocol output and write it: the shared core of `bs.py split` and the adapter's `files` jobs.

    Returns {"ok": bool, "errors": [...], "warnings": [...], "written": [abs...], "status": dict|None,
    "io_error": bool}. Nothing is written unless all checks pass and allowed_globs names at least one glob (None or []
    is refused, as in write_file_blocks). The STATUS object goes to status_out (when given and present). io_error is
    True when the output was valid but writing it failed (an OSError here): a local, retryable problem, not a fault of
    the output. `parsed`: the "files" result check_contract already returned for this text
    ({"files", "status", "warnings"}); the text is then not parsed again.
    """
    if isinstance(parsed, dict) and isinstance(parsed.get("files"), dict):
        files, status, warnings = parsed["files"], parsed.get("status"), list(parsed.get("warnings") or [])
    else:
        files, status, warnings = parse_file_blocks(text)
    errors = structural_errors(warnings) + validate_files(files, allowed_globs)
    for req in required or []:
        if req not in files:
            errors.append("%s: required file missing" % req)
    if status_required and (status is None or status.get("status") not in STATUS_VALUES):
        errors.append("STATUS trailer missing or invalid")
    result = {"ok": False, "errors": errors, "warnings": warnings, "written": [], "status": status, "io_error": False}
    if errors:
        return result
    try:
        result["written"] = _write_validated(files, root, allowed_globs)
        if status_out and status is not None:
            textio.write_json_atomic(status_out, status)
    except WriteError as e:
        result["errors"], result["io_error"] = [str(e)], True
        return result
    except PathError as e:
        result["errors"] = [str(e)]
        return result
    except OSError as e:
        result["errors"], result["io_error"] = ["could not write the files: %s" % e], True
        return result
    result["ok"] = True
    return result
