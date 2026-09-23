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
structural_errors, split_output.
"""

import json
import os
import re
import tempfile
import time

from . import textio

__all__ = [
    "PathError", "WriteError", "ALLOWED_EXTS", "STATUS_VALUES",
    "parse_file_blocks", "write_file_blocks", "check_relpath", "glob_match", "validate_files", "split_output",
    "structural_errors",
]

ALLOWED_EXTS = (".md", ".yaml", ".yml", ".json", ".mmd")
STATUS_VALUES = ("complete", "partial", "blocked")

_FILE_RE = re.compile(r"^\s*===\s*FILE:\s*(.*?)\s*===\s*$")
_END_FILE_RE = re.compile(r"^\s*===\s*END\s+FILE\s*===\s*$")
_STATUS_RE = re.compile(r"^\s*===\s*STATUS\s*===\s*$")
_END_STATUS_RE = re.compile(r"^\s*===\s*END\s+STATUS\s*===\s*$")
_DRIVE_RE = re.compile(r"^[A-Za-z]:")
_BAD_CHARS = set('<>:"|?*')
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

def parse_file_blocks(text):
    """Parse FILE blocks and the optional STATUS trailer.

    Returns (files, status, warnings):
      files    {relpath: content} in first-seen order; a repeated path keeps the LAST copy (warning logged)
      status   the STATUS JSON object, or None when absent or unparseable (warning logged)
      warnings list of strings
    Text outside the blocks is ignored. A block that is not closed ends at the next FILE/STATUS marker or at the end
    of the text, with a warning. Content keeps its lines exactly (LF), with one trailing newline.
    """
    files = {}
    warnings = []
    status = None
    status_seen = False
    lines = textio.normalize_newlines(text or "").split("\n")
    cur_path, cur_lines, mode = None, [], None  # mode: None | "file" | "status"

    def close(unterminated):
        nonlocal status, status_seen
        if mode == "file":
            if unterminated:
                warnings.append("FILE block %s has no END FILE marker" % cur_path)
            if cur_path in files:
                warnings.append("duplicate FILE block %s: the last copy wins" % cur_path)
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
        m = _FILE_RE.match(line)
        if m and not _END_FILE_RE.match(line):
            if mode is not None:
                close(True)
            cur_path, cur_lines, mode = m.group(1).strip(), [], "file"
            continue
        if _STATUS_RE.match(line):
            if mode is not None:
                close(True)
            cur_path, cur_lines, mode = None, [], "status"
            continue
        if mode == "file" and _END_FILE_RE.match(line):
            close(False)
            cur_path, cur_lines, mode = None, [], None
            continue
        if mode == "status" and _END_STATUS_RE.match(line):
            close(False)
            cur_path, cur_lines, mode = None, [], None
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


def check_relpath(rel, allowed_globs=None):
    """Return the normalized relative path or raise PathError (rules 4.6.1 and 4.6.2).

    Rejected: empty, backslashes, absolute paths, drive letters, '..', any segment starting with '.', empty
    segments, control or Windows-reserved characters, reserved device names, segments ending in space or dot,
    extensions other than ALLOWED_EXTS, and (when allowed_globs is not None) paths matching no allowed glob.
    """
    if not isinstance(rel, str) or not rel.strip():
        raise PathError("empty path")
    p = rel.strip()
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
        if any(ord(ch) < 32 for ch in seg) or any(ch in _BAD_CHARS for ch in seg):
            raise PathError("%s: invalid character in path" % p)
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
    """Errors (list of str) for a parsed {relpath: content} map: path guards and empty content (rule 4.6.3)."""
    errors = []
    if not files:
        errors.append("no FILE blocks found")
    for rel, content in files.items():
        try:
            check_relpath(rel, allowed_globs)
        except PathError as e:
            errors.append(str(e))
            continue
        if not (content or "").strip():
            errors.append("%s: content is empty" % rel)
    return errors


def structural_errors(warnings):
    """Parse warnings that make an output invalid: an unterminated FILE block usually means truncated output, so
    it is never written (rule 4.6.4). Other warnings (duplicates, STATUS problems) stay warnings here."""
    return [w for w in warnings or [] if "has no END FILE marker" in w]


# ---------------------------------------------------------------- writing

def _inside(root, target):
    root_n = os.path.normcase(root.rstrip("\\/")) + os.sep
    return os.path.normcase(target).startswith(root_n)


def write_file_blocks(files, root, allowed_globs):
    """Validate every path and content first, then write each file atomically under root.

    Nothing is written when any entry is invalid (rule 4.6.4). Returns the written absolute paths (native form, in
    the order of `files`). Raises PathError.
    """
    errors = validate_files(files, allowed_globs)
    if errors:
        raise PathError("; ".join(errors))
    # textio.real_path, not os.path.realpath: parallel workers create the same new sub-folder (13.2-A/B/C all write
    # 11_PROPOSAL/sections/), and realpath() of a file in a folder that appears mid-call can come back with a \\?\
    # prefix on Windows, which the prefix comparison below would report as "outside the output root".
    root_abs = textio.real_path(os.path.abspath(os.fspath(root)))
    plan = []
    for rel, content in files.items():
        norm = check_relpath(rel, allowed_globs)
        target = textio.real_path(os.path.join(root_abs, *norm.split("/")))
        if not _inside(root_abs, target):
            raise PathError("%s: resolves outside the output root" % rel)
        plan.append((target, content))
    for target, _content in plan:
        if os.path.isdir(target):
            raise PathError("%s: a folder with that name already exists" % textio.to_posix(target))
    # all-or-nothing: every file goes to a temp name next to its target first, then all are renamed into place
    temps = []
    try:
        for target, content in plan:
            if not content.endswith("\n"):
                content += "\n"
            parent = os.path.dirname(target)
            os.makedirs(parent, exist_ok=True)
            fd, tmp = tempfile.mkstemp(prefix="." + os.path.basename(target)[:40] + ".", suffix=".tmp", dir=parent)
            temps.append((tmp, target))
            if content.startswith("\ufeff"):
                content = content[1:]
            with os.fdopen(fd, "wb") as f:
                f.write(textio.normalize_newlines(content).encode("utf-8"))
        for tmp, target in temps:
            for i in range(10):
                try:
                    os.replace(tmp, target)
                    break
                except PermissionError:
                    if i == 9:
                        raise
                    time.sleep(0.05 * (i + 1))
    except OSError as e:
        for tmp, _t in temps:
            try:
                if os.path.exists(tmp):
                    os.unlink(tmp)
            except OSError:
                pass
        raise WriteError("could not write the files: %s" % e)
    return [target for target, _c in plan]


def split_output(text, root, allowed_globs, status_out=None, required=None, status_required=False):
    """Parse FILE-protocol output and write it: the shared core of `bs.py split` and the adapter's `files` jobs.

    Returns {"ok": bool, "errors": [...], "warnings": [...], "written": [abs...], "status": dict|None,
    "io_error": bool}. Nothing is written unless all checks pass. The STATUS object goes to status_out (when given and
    present). io_error is True when the output was valid but writing it failed (an OSError here): a local, retryable
    problem, not a fault of the output.
    """
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
        result["written"] = write_file_blocks(files, root, allowed_globs)
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
