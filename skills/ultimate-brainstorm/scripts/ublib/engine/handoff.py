"""Stage 14 Handoff (KIT_SPEC 9): publish copies (each needs its own yes), handoff seeds, 12_HANDOFF.md.

Scripts: handoff_seed (14.3), handoff_final (14.4).
"""

import binascii
import filecmp
import json
import os
import posixpath
import re
import shutil
import stat
import tempfile
import time

from .. import filesproto, textio
from . import EngineError
from . import registry
from . import render
from . import state as st

SEEDS = ("ce", "speckit", "superpowers", "openspec")
SEED_TEMPLATE = {"ce": "HANDOFF-CE", "speckit": "HANDOFF-SPECKIT", "superpowers": "HANDOFF-SUPERPOWERS",
                 "openspec": "HANDOFF-OPENSPEC"}
CLOSING = "Do not reopen the choice of idea or architecture."
# a seed or handoff of an idea its probe killed with no runner-up left says so instead of CLOSING (render.k6_dead)
K6_WARNING = ("WARNING: the pre-registered probe missed (K6) and no runner-up is left: do not build this idea; switch "
              "to another finalist first.")
# item -> the run folder it copies. A copy keeps the run's layout under docs/<run>/ (docs/<run>/10_ARCHITECTURE/ with
# its adr/, docs/<run>/11_PROPOSAL/), so every relative link in it (the README's adr/..., the proposal's
# ../10_ARCHITECTURE/adr/...) resolves as it does in the run, and no published file is rewritten.
PUBLISH = {"architecture": "10_ARCHITECTURE", "adr": "10_ARCHITECTURE/adr", "proposal": "11_PROPOSAL"}
ALL_ITEMS = tuple(PUBLISH)
SKIP_DIRS = ("_raw", "_packs", "export")
RUN_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def g14(ctx):
    return ((ctx.state.get("gates") or {}).get("G14") or {}).get("answer") or {}


def chosen_handoff(ctx):
    ans = g14(ctx)
    h = ans.get("handoff")
    if h in SEEDS or h == "none":
        return h
    return "ce" if ctx.variant in ("software", "growth") else "none"


def publish_items(ctx):
    pub = g14(ctx).get("publish")
    if pub is True:
        return ["architecture", "adr", "proposal"]
    if isinstance(pub, list):
        return [p for p in PUBLISH if p in pub]
    return []


# What this run published: paths under docs/<run>/, kept in the run folder, with the id of this run's claim. It is
# written before a publish changes anything, so an interrupted publish still knows every file it may have written.
PUBLISH_RECORD = "handoff/published.json"
# docs/<run>/.ub-run.json: the claim of the run that owns the folder ({"schema", "run", "id", "run_dir": the run
# folder relative to the project}), created whole in one step on the first publish (_create_claim). Two runs share a name when they sit in
# different run roots of one project (the name is unique only within a root); a folder another run claimed is never
# written.
CLAIM = ".ub-run.json"
# The marker kit 2.0.x wrote into each docs folder it published to: read only to name this run's old copies.
LEGACY_MARKER = ".ub-published"
# Files an OS, a file browser or an editor drops into any folder: never published.
_IGNORED_NAMES = (".ds_store", "thumbs.db", "desktop.ini", ".gitkeep", ".keep", CLAIM)
# The tail of textio's atomic-write temp file names (.<name>.<8 random chars>.tmp)
_TEMP_TAIL_RE = re.compile(r"^[a-z0-9_]{8}\.tmp$")


def _ignored(name):
    """OS and editor litter, the folder's claim, and the files of a FILE-protocol commit in progress (its
    .ub-split-*.json journal and the hidden .tmp / .bak files next to its targets): never published."""
    low = name.lower()
    return (low in _IGNORED_NAMES or low.startswith(("._", ".#", filesproto.JOURNAL_PREFIX))
            or low.endswith((".swp", ".swo", "~")) or (low.startswith(".") and low.endswith((".tmp", ".bak"))))


def _is_link(path):
    """A symlink or (Windows) junction: its real path differs from the path under its real parent."""
    if os.path.islink(path):
        return True
    try:
        real = textio.real_path(path)
        expect = os.path.join(textio.real_path(os.path.dirname(os.path.abspath(path))), os.path.basename(path))
        return os.path.normcase(real) != os.path.normcase(expect)
    except OSError:
        return True


def _source_files(src):
    out = []
    for dirpath, dirs, files in os.walk(src):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
        for f in sorted(files):
            if f.endswith((".meta.json", ".failed.md")) or _ignored(f):
                continue
            full = os.path.join(dirpath, f)
            out.append((os.path.relpath(full, src).replace("\\", "/"), full))
    return out


def _safe_rel(rel):
    """A relative posix path that stays inside its folder and names a publishable file (record entries are read from
    disk)."""
    if not (isinstance(rel, str) and rel and not rel.startswith("/") and "\\" not in rel and ":" not in rel):
        return False
    parts = rel.split("/")
    return all(p not in ("", ".", "..") for p in parts) and not _ignored(parts[-1])


def _link_on_path(pd, rel):
    """The first of pd/docs, pd/docs/<run>, ... pd/<rel> that is a link or junction (as a relpath), or None."""
    parts = rel.split("/")
    for i in range(1, len(parts) + 1):
        p = os.path.join(pd, *parts[:i])
        if os.path.lexists(p) and _is_link(p):
            return "/".join(parts[:i])
    return None


def _run_name(ctx):
    return os.path.basename(ctx.state.get("run") or os.path.abspath(ctx.run_dir))


def _abs(ctx, rel):
    return os.path.join(ctx.state.get("project_dir") or ".", *rel.split("/"))


def _record(ctx, base):
    """The files this run published (paths under base = docs/<run>), from PUBLISH_RECORD."""
    data = ctx.read_json(PUBLISH_RECORD, {})
    if not isinstance(data, dict) or data.get("docs") != base or not isinstance(data.get("files"), list):
        return set()
    return set(f for f in data["files"] if _safe_rel(f))


def _claim_id(ctx):
    """The id of this run's claim on docs/<run>/ (kept in PUBLISH_RECORD), or None before its first publish."""
    data = ctx.read_json(PUBLISH_RECORD, {})
    cid = data.get("claim") if isinstance(data, dict) else None
    return cid if isinstance(cid, str) and re.match(r"^[0-9a-f]{32}$", cid) else None


_KEEP = object()


def _save_record(ctx, base, files, claim=_KEEP):
    ctx.write_json(PUBLISH_RECORD, {"schema": 1, "docs": base, "files": sorted(files),
                                    "claim": _claim_id(ctx) if claim is _KEEP else claim})


# An empty claim is one whose creation was interrupted before its bytes were written: kit 2.1 before the hard-linked
# claim, or a POSIX disk without hard links. It is this run's to replace (_read_claim: _EMPTY) when this run's record
# names docs/<run> and the id of the claim it was creating (saved first; a run that lost the race to claim keeps no
# id: _claim), once it is older than this: a younger one may be another run's claim being written.
EMPTY_CLAIM_GRACE_S = 60
_EMPTY = object()  # _read_claim: the claim is an empty one this run left
_EMPTY_OWNER = ("a publish whose claim %s/%s is empty (interrupted while it claimed the folder: the run that left it "
                "takes it over after %d s; for any other run, delete that file)")


def _left_empty(ctx, base, path):
    try:
        info = os.lstat(path)
    except OSError:
        return False
    record = ctx.read_json(PUBLISH_RECORD, {})
    return (stat.S_ISREG(info.st_mode) and info.st_size == 0 and time.time() - info.st_mtime > EMPTY_CLAIM_GRACE_S
            and isinstance(record, dict) and record.get("docs") == base and _claim_id(ctx) is not None)


def _read_claim(ctx, base):
    """(the claim of docs/<run>/ as read, None when there is none, _EMPTY for an empty claim this run left; and who
    holds the folder by that claim: None when it is this run's to write (no claim yet, this run's claim: its id, or its
    run folder, or an empty claim this run left), else 'the run at <path>'). One read decides both, so a claim is only
    ever adopted after it was judged."""
    path = _abs(ctx, "%s/%s" % (base, CLAIM))
    if not os.path.lexists(path):
        return None, None
    data = textio.read_json_or(path)
    if not isinstance(data, dict):
        if _left_empty(ctx, base, path):
            return _EMPTY, None
        if os.path.isfile(path) and os.path.getsize(path) == 0:
            return data, _EMPTY_OWNER % (base, CLAIM, EMPTY_CLAIM_GRACE_S)
        return data, "a run whose claim %s/%s cannot be read (an interrupted publish, or not the kit's)" % (base, CLAIM)
    mine = _claim_id(ctx)
    if mine and data.get("id") == mine:
        return data, None
    if data.get("run_dir") and _claim_path(ctx) == data["run_dir"]:
        return data, None
    return data, "the run at %s (a run of the same name in another run root)" % (
        data.get("run_dir") or "a folder on another drive")


def _owner(ctx, base):
    """None when docs/<run>/ is this run's to write, else who holds it (_read_claim)."""
    return _read_claim(ctx, base)[1]


def _claim_path(ctx):
    """The run folder as a claim names it: relative to the project folder (the claim is committed with the copies,
    so it never holds the user's absolute paths), posix; None on another drive (then only the id identifies it)."""
    try:
        rel = os.path.relpath(os.path.abspath(ctx.run_dir), os.path.abspath(ctx.state.get("project_dir") or "."))
    except ValueError:
        return None
    return rel.replace("\\", "/")


def _held_id(held):
    return held.get("id") if isinstance(held, dict) and isinstance(held.get("id"), str) else None


def _claim(ctx, base, files):
    """Claim docs/<run>/ for this run before its first change, then write the record of the files it may write.
    Returns None, or who holds the folder. A claim is adopted only as judged by the read that found it (this run's:
    its id, or its run folder); where none was found, this run's claim is created only if the name is still free
    (_create_claim), so of two runs that publish at the same moment exactly one gets it, and a claim that appeared in
    between is judged, never adopted. An empty claim this run left (_EMPTY) is written over, then read again. A run
    that loses the claim keeps the claim id its record held before, so it never takes over another run's empty claim."""
    held, owner = _read_claim(ctx, base)
    if owner:
        return owner
    prior = _claim_id(ctx)
    cid = _held_id(held) or prior or binascii.hexlify(os.urandom(16)).decode("ascii")
    if held is None or held is _EMPTY:
        path = _abs(ctx, "%s/%s" % (base, CLAIM))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        _save_record(ctx, base, _record(ctx, base), claim=cid)  # the id first: an interrupted publish keeps it
        body = json.dumps({"schema": 1, "run": _run_name(ctx), "id": cid, "run_dir": _claim_path(ctx)},
                          ensure_ascii=True) + "\n"
        if held is _EMPTY:
            _write_public(path, body.encode("ascii"), _public_mode())  # read again below: the last writer holds it
        if held is _EMPTY or not _create_claim(path, body.encode("ascii")):
            held, owner = _read_claim(ctx, base)  # another run claimed it a moment ago (or this run did, elsewhere)
            if held is _EMPTY:  # empty after this run wrote it, or one that appeared empty: never adopted unread
                owner = _EMPTY_OWNER % (base, CLAIM, EMPTY_CLAIM_GRACE_S)
            if owner:
                _save_record(ctx, base, _record(ctx, base), claim=prior)
                return owner
            cid = _held_id(held) or cid
    _save_record(ctx, base, files, claim=cid)
    return None


def _create_claim(path, data):
    """Create the claim file with its whole content in one step: a temp file (fsynced, with the umask mode) is hard
    linked to the claim's name, which fails when the name exists. So of two runs exactly one gets the name, no reader
    finds an empty claim, and an interrupted publish leaves either no claim or a whole one. On a disk without hard links
    (exFAT, FAT32, some network shares): on Windows a rename of the temp file, which never replaces an existing name,
    so the same holds; elsewhere O_EXCL and a write, whose interruption leaves an empty claim that the run which left
    it takes over later (_read_claim). Returns False when the name was taken."""
    fd, tmp = tempfile.mkstemp(prefix=textio.temp_prefix(path), suffix=".tmp", dir=os.path.dirname(path))
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        if _POSIX_MODES:
            os.chmod(tmp, _public_mode())
        try:
            os.link(tmp, path)
            return True
        except FileExistsError:
            return False
        except OSError:
            pass  # no hard links here
        if not _POSIX_MODES:
            try:
                os.rename(tmp, path)  # MoveFileEx without REPLACE_EXISTING: an existing name is refused
                return True
            except FileExistsError:
                return False
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o644)
        except FileExistsError:
            return False
        try:
            view = memoryview(data)
            while view:
                view = view[os.write(fd, view):]
            os.fsync(fd)
        finally:
            os.close(fd)
        return True
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass


_POSIX_MODES = os.name != "nt"


def _public_mode():
    """The mode a new file gets under this process's umask (0o644 under umask 022). textio's atomic writes create
    owner-only files (right for run files); the published copies are for everyone who can read the repository."""
    umask = os.umask(0o022)
    os.umask(umask)
    return 0o666 & ~umask


def _write_public(path, data, mode):
    """Write a published file through a temp file (named as textio names them, so _tidy finds an interrupted one) and
    a rename, with the umask mode set on the temp file first: the file never exists with the owner-only mode of
    textio's temp files, so a mode found on an unchanged file was set by someone on purpose and stays."""
    path = os.path.abspath(path)
    tmp = None
    try:
        fd, tmp = tempfile.mkstemp(prefix=textio.temp_prefix(path), suffix=".tmp", dir=os.path.dirname(path))
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        if _POSIX_MODES:
            os.chmod(tmp, mode)
        textio._replace_with_retry(tmp, path)
        tmp = None
    except OSError as e:
        err = textio.explain_long_path(e, path)
        if err is e:
            raise
        raise err from e
    finally:
        if tmp is not None:
            try:
                os.unlink(tmp)
            except OSError:
                pass


def _samefile(a, b):
    try:
        return os.path.samefile(a, b)
    except OSError:
        return False


def _holds(path, src):
    """True when path is a regular file (not a link) with the bytes of the file src."""
    return not os.path.islink(path) and os.path.isfile(path) and filecmp.cmp(path, src, shallow=False)


def _scan(ctx, rel, base):
    """The files under the folder rel (paths under base), OS and editor litter left out; folders that are links or
    junctions are not entered."""
    out = []
    for dirpath, dirs, names in os.walk(_abs(ctx, rel)):
        dirs[:] = [d for d in dirs if not _is_link(os.path.join(dirpath, d))]
        folder = os.path.relpath(dirpath, _abs(ctx, base)).replace("\\", "/")
        out += ["%s/%s" % (folder, n) for n in names if not _ignored(n)]
    return out


def _layout(ctx, items=None):
    """What an answer publishes: "asked" (the items it names; None = all three), "items" (those, plus the ADRs when
    the proposal, which links to them, is published; `architecture` holds them anyway), the source files of every
    item, "base" (docs/<run>), the "record" of the files this run published there that are still there, and
    "partial": the answer leaves out a copy this run published, which may link to any old file, so no old file leaves
    this time."""
    asked = list(ALL_ITEMS) if items is None else [i for i in ALL_ITEMS if i in items]
    for root in sorted(set(PUBLISH[i].split("/")[0] for i in ALL_ITEMS)):
        filesproto.recover(ctx.path(root))  # a FILE-protocol commit a crash interrupted is finished before any copy
    if "proposal" in asked:
        render.refresh_page(ctx)  # a page an older kit rendered (no pinned script) is rendered again first
    sources = dict((i, _source_files(ctx.path(PUBLISH[i]))) for i in ALL_ITEMS)
    chosen = set(asked)
    if "proposal" in chosen and sources["adr"]:
        chosen.add("adr")
    base = "docs/%s" % _run_name(ctx)
    record = set(f for f in _record(ctx, base) if os.path.lexists(_abs(ctx, "%s/%s" % (base, f))))
    roots = tuple(PUBLISH[i] + "/" for i in chosen)
    owner = _owner(ctx, base) if RUN_NAME_RE.match(_run_name(ctx)) else None
    return {"asked": asked, "items": [i for i in ALL_ITEMS if i in chosen], "sources": sources, "base": base,
            "record": record if not owner else set(), "partial": any(not f.startswith(roots) for f in record),
            "owner": owner}


def _plan(ctx, item, layout):
    src, base = PUBLISH[item], layout["base"]
    dst = "%s/%s" % (base, src)
    files = dict(("%s/%s" % (src, rel), full) for rel, full in layout["sources"][item])
    ours = set(f for f in layout["record"] if f.startswith(src + "/"))
    plan = {"item": item, "src": src, "dst": None, "state": "refused", "why": "", "blocker": None,
            "within": "architecture" if item == "adr" and "architecture" in layout["items"] else None,
            "files": files, "changed": [], "stale": [], "kept": [], "renamed": [], "other": []}
    if not files and not ours:
        plan.update(state="empty", why="no files")
        return plan
    if not RUN_NAME_RE.match(_run_name(ctx)):
        plan["why"] = "the run name is not a safe folder name"
        return plan
    if layout.get("owner"):
        plan.update(why="%s belongs to %s" % (base, layout["owner"]), blocker=base)
        return plan
    pd = ctx.state.get("project_dir") or "."
    for folder in sorted(set([dst]) | set(posixpath.dirname("%s/%s" % (base, f)) for f in set(files) | ours)):
        link = _link_on_path(pd, folder)
        if link:
            plan.update(why="%s is a link or junction" % link, blocker=link)
            return plan

    def at(f):
        return _abs(ctx, "%s/%s" % (base, f))
    plan.update(dst=dst, state="update" if ours else "new")
    plan["changed"] = sorted(f for f in files if os.path.lexists(at(f)) and not _holds(at(f), files[f]))
    stale = sorted(f for f in ours - set(files) if os.path.lexists(at(f)) and not os.path.isdir(at(f)))
    # a case-only rename on a case-insensitive disk: the old name is the new file, so it moves out before the write
    plan["renamed"] = [f for f in stale if any(q.lower() == f.lower() and _samefile(at(f), at(q)) for q in files)]
    plan["kept" if layout["partial"] else "stale"] = [f for f in stale if f not in plan["renamed"]]
    plan["other"] = sorted(f for f in _scan(ctx, dst, base) if f not in files and f not in layout["record"])
    return plan


def plan_target(ctx, item, items=None):
    """What publishing one item does, for the answer `items` (None = `publish`, all three; the G14 card shows that).
    Returns {"item", "src", "dst" (docs/<run>/<run folder>; None = not published), "state" (new, update, empty,
    refused), "why", "blocker" (the link or junction to move aside when refused), "within" ("architecture" when the adr
    copy is part of the architecture copy), "files" (path under docs/<run>/ -> source file), "changed" (files there
    with other content: backed up first), "stale" (files this run published there before and no longer has: moved to
    the backup), "kept" (the same, kept because the answer leaves out a copy this run published), "renamed" (old names
    that are the same file as a new one on a case-insensitive disk: moved to the backup first), "other" (files there
    this run did not publish: left alone)}."""
    return _plan(ctx, item, _layout(ctx, items))


def _legacy_copies(ctx):
    """This run's copies that kit 2.0.x published (docs/<item>, docs/<item>/ub-<run> or docs/<run>/<item>, with a
    marker naming this run). Publishing leaves them alone; the card names them."""
    run = _run_name(ctx)
    out = []
    for item in ALL_ITEMS:
        for rel in ("docs/%s" % item, "docs/%s/ub-%s" % (item, run), "docs/%s/%s" % (run, item)):
            marker = textio.read_json_or(os.path.join(_abs(ctx, rel), LEGACY_MARKER))
            if isinstance(marker, dict) and marker.get("run") == run:
                out.append(rel)
    return out


def card_lines(ctx):
    """The G14 card's publish block: one line per item (for the answer `publish`), then where the copies go."""
    layout = _layout(ctx)
    plans = [_plan(ctx, item, layout) for item in ALL_ITEMS]
    lines = [card_line(plan) for plan in plans]
    if any(plan["dst"] for plan in plans):
        lines.append("Each copy goes to %s/, a folder no other run writes, and keeps the run's layout, so its links "
                     "resolve unchanged: `architecture` holds the ADRs and `proposal` brings them along."
                     % layout["base"])
    if any(plan["stale"] for plan in plans):
        lines.append("Files this run no longer has leave only when every copy it published is published again; with a "
                     "partial answer they stay, so no copy loses a file it links to.")
    old = _legacy_copies(ctx)
    if old:
        lines.append("Kit 2.0.x published this run to %s: %s left as %s and no longer updated (move or delete %s "
                     "yourself)." % (", ".join(old), "that copy is" if len(old) == 1 else "those copies are",
                                     "it is" if len(old) == 1 else "they are", "it" if len(old) == 1 else "them"))
    return lines


def card_line(plan):
    """One G14 card line for a plan_target() result."""
    head = "- %s: %s -> " % (plan["item"], plan["src"])
    if plan["state"] == "empty":
        return "- %s: nothing to publish (%s has no files)" % (plan["item"], plan["src"])
    if not plan["dst"]:
        line = head + "not published (%s)." % plan["why"]
        if plan["blocker"]:
            line += " To publish it, move %s aside and redo step 14.2." % plan["blocker"]
        return line
    notes = []
    if plan["state"] == "update":
        notes.append("this run published it before" + ("" if plan["files"] else "; its package now has no files"))
    for files, one, many in (
            (plan["changed"], "1 file it replaces is backed up to _superseded/ first",
             "%d files it replaces are backed up to _superseded/ first"),
            (plan["stale"] + plan["renamed"], "1 file this run no longer has moves to _superseded/",
             "%d files this run no longer has move to _superseded/"),
            (plan["kept"], "1 file this run no longer has stays: a copy not in the answer may link to it",
             "%d files this run no longer has stay: a copy not in the answer may link to them"),
            (plan["other"], "1 file this run did not publish stays as it is",
             "%d files this run did not publish stay as they are")):
        if files:
            notes.append(one if len(files) == 1 else many % len(files))
    return head + plan["dst"] + ((" (%s)" % "; ".join(notes)) if notes else "")


def _backup_stamp(ctx):
    """A stamp whose _superseded/<stamp>/published/ does not exist yet, so a backup never overwrites an older one."""
    stamp = st.iso_stamp()
    n = 1
    while os.path.exists(ctx.path("_superseded", stamp if n == 1 else "%s-%d" % (stamp, n), "published")):
        n += 1
    return stamp if n == 1 else "%s-%d" % (stamp, n)


def _tidy(ctx, base, written, moved):
    """Remove the temp files an interrupted atomic write left next to the files written (paths under base), and the
    folders that moving this run's old files (moved) left empty (never base itself)."""
    prefixes = {}
    for f in written:
        folder, name = posixpath.split(f)
        prefixes.setdefault(folder, set()).add(textio.temp_prefix(name))  # the writer's own prefix, whatever its length
    for folder, heads in sorted(prefixes.items()):
        path = _abs(ctx, "%s/%s" % (base, folder))
        for name in (os.listdir(path) if os.path.isdir(path) else []):
            full = os.path.join(path, name)
            if (any(name.startswith(h) and _TEMP_TAIL_RE.match(name[len(h):]) for h in heads)
                    and os.path.isfile(full) and not os.path.islink(full)):
                os.unlink(full)
    top = os.path.normcase(_abs(ctx, base))
    for f in sorted(moved, key=lambda r: -r.count("/")):
        d = os.path.dirname(_abs(ctx, "%s/%s" % (base, f)))
        while os.path.normcase(d).startswith(top + os.sep):
            try:
                os.rmdir(d)
            except OSError:
                break
            d = os.path.dirname(d)


def publish(ctx, items):
    """Copy each approved item into <project>/docs/<run>/, where it keeps the run's layout, so no file is rewritten;
    `proposal` also publishes the ADRs it links to. Only docs/<run>/ is written, a folder this run claims before its
    first change (CLAIM; a folder another run of the same name claimed is refused), so runs never mix, also when two
    publish at the same moment. The copy is unconditional and idempotent: a file that already holds the run's bytes is
    left alone, its mode too; any other file or link at a planned name goes to
    _superseded/<stamp>/published/<path under docs/<run>/> first, and so does each file this run published there before
    and no longer has, but only when the answer publishes every copy this run published (a copy left out may link to
    it). Files are written through a temp file that already has the umask mode and a rename (a hard link is replaced,
    never written through). The record of what was published (PUBLISH_RECORD) is written before the first change, so
    an interrupted publish just runs again. Folders a link or junction sits on are never written.
    Returns {"published": [...], "not_published": [...]} (one short line each, for 12_HANDOFF.md)."""
    out = {"published": [], "not_published": []}
    if not ctx.state.get("project_dir"):
        return out
    layout = _layout(ctx, items)
    base = layout["base"]
    plans = [_plan(ctx, item, layout) for item in layout["items"]]
    # the adr copy of a published architecture copy is part of it: written once, with it
    written_with = set(p["item"] for p in plans if p["dst"])
    work = [p for p in plans if p["dst"] and p["within"] not in written_with]
    stamp = _backup_stamp(ctx)

    def at(f):
        return _abs(ctx, "%s/%s" % (base, f))

    def backup(f):
        path = ctx.path("_superseded", stamp, "published", *f.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        return path
    planned = dict((f, full) for p in work for f, full in p["files"].items())
    moved = dict((p["item"], []) for p in work)
    owner = _claim(ctx, base, layout["record"] | set(planned)) if work else None
    if owner:  # another run claimed docs/<run>/ between the plan and now: nothing is written
        for p in plans:
            if p["dst"]:
                p.update(dst=None, state="refused", why="%s belongs to %s" % (base, owner), blocker=base)
        work = []
    if work:
        mode = _public_mode()
        for p in work:
            for f in p["renamed"]:
                shutil.move(at(f), backup(f))
                moved[p["item"]].append(f)
        # the ADRs first, so a copy that links to them never points at a file that is not there yet
        for f in sorted(planned, key=lambda f: (not f.startswith(PUBLISH["adr"] + "/"), f)):
            target = at(f)
            if os.path.isdir(target) and not os.path.islink(target):
                continue
            if _holds(target, planned[f]):
                continue  # an unchanged file keeps its mode: a mode set on purpose stays
            if os.path.islink(target):
                shutil.move(target, backup(f))  # a link is moved aside, never followed or written through
            elif os.path.isfile(target):
                textio._write_bytes_atomic(backup(f), textio.read_bytes(target))  # fsynced, like every write
            os.makedirs(os.path.dirname(target), exist_ok=True)
            _write_public(target, textio.read_bytes(planned[f]), mode)
        # old files last: every copy already holds its new files
        for p in work:
            for f in p["stale"]:
                if os.path.lexists(at(f)):
                    shutil.move(at(f), backup(f))
                    moved[p["item"]].append(f)
        gone = set(f for fs in moved.values() for f in fs)
        _tidy(ctx, base, set(planned) | {CLAIM}, gone)  # (the claim's temp too, if a crash left it)
        _save_record(ctx, base, set(f for f in (layout["record"] | set(planned)) - gone if os.path.lexists(at(f))))
    for p in plans:
        if not p["dst"]:
            if p["item"] in layout["asked"] or p["state"] != "empty":
                out["not_published"].append("%s (%s)" % (p["src"], p["why"]))
            continue
        if p not in work:
            if p["item"] in layout["asked"]:
                out["published"].append("%s -> %s (in the architecture copy)" % (p["src"], p["dst"]))
            continue
        notes = [] if p["item"] in layout["asked"] else ["published with the proposal, which links to it"]
        if not p["files"]:
            notes.append("the package has no files; nothing copied")
        for files, one, many in (
                (moved[p["item"]], "1 old file moved to _superseded", "%d old files moved to _superseded"),
                (p["kept"], "1 old file kept: a copy not in the answer may link to it",
                 "%d old files kept: a copy not in the answer may link to them"),
                (p["other"], "1 file this run did not publish left as it is",
                 "%d files this run did not publish left as they are")):
            if files:
                notes.append(one if len(files) == 1 else many % len(files))
        out["published"].append("%s -> %s%s" % (p["src"], p["dst"], (" (%s)" % "; ".join(notes)) if notes else ""))
    return out


def seed_text(ctx, kind):
    """The handoff seed for `kind` from templates/docs/HANDOFF-<KIND>.md, ending with CLOSING; without it once the
    chosen idea's probe missed with no runner-up left (render.k6_dead): that choice is not settled."""
    s = ctx.state
    run_rel = "brainstorm/%s" % s.get("run", "")
    iid = registry.chosen_idea(ctx) or "?"
    info = registry.idea_lines(ctx).get(iid, {})
    check = ctx.read("checks/%s.md" % iid)
    dec = ctx.read("08_DECISION.md")
    not_doing = "; ".join(m.group(1).strip() for m in re.finditer(r"^Not doing[^:]*:\s*(.*)$", dec, re.M))
    kills = re.findall(r"(Fails if[^\n|]*)",
                       registry._unfenced(check) + "\n" + registry._unfenced(ctx.read("07_REDTEAM.md")))[:3]
    dissent = "; ".join(m.group(1).strip() for m in re.finditer(r"^Dissent recorded:\s*(.*)$", dec, re.M))
    verdict, diff = registry.check_verdict(ctx, iid)
    passed = "RESULT: PASSED" in ctx.read("09_PROBE.md")
    dead = render.k6_dead(s)
    warning = K6_WARNING if dead else "" if passed else \
        "WARNING: riskiest assumption untested (09_PROBE.md has no RESULT: PASSED)."
    mapping = {
        "TITLE": registry.clean(info.get("title") or s.get("topic", "")),
        "DESCRIPTION": registry.clean(info.get("pitch") or info.get("title") or s.get("topic", "")).rstrip("."),
        "IDEA_ID": iid, "RUN_PATH": run_rel,
        "BASIS": "prior-art verdict %s%s" % (verdict or "NOT CHECKED", ("; differentiator: %s" % diff) if diff else ""),
        "TRADEOFFS": "; ".join(kills + ([dissent] if dissent and dissent != "none" else [])) or "see 07_REDTEAM.md",
        "SETTLED": "Not doing: %s" % (not_doing or "see 08_DECISION.md"), "PROBE_RESULT": probe_status(ctx),
        "ARCH_README": "%s/10_ARCHITECTURE/README.md" % run_rel, "PROPOSAL": "%s/11_PROPOSAL/PROPOSAL.md" % run_rel,
        "DOMAIN_CLAUSE": domain_clause(ctx, run_rel), "DATE": textio.now_iso()[:10], "PROBE_WARNING": warning}
    from . import builders
    text = builders.render_doc(SEED_TEMPLATE[kind], mapping)
    if not text:
        raise EngineError("template %s is missing or uses a placeholder the engine does not fill (templates/docs/%s.md)"
                          % (SEED_TEMPLATE[kind], SEED_TEMPLATE[kind]),
                          fix=["reinstall the kit (templates and engine versions differ): install.py update"])
    text = text.rstrip()
    if dead:
        text = "\n".join(ln for ln in text.split("\n") if ln.strip() != CLOSING).rstrip()
    elif not text.endswith(CLOSING):
        text += "\n" + CLOSING
    return text + "\n"


def domain_clause(ctx, run_rel):
    if not ctx.exists("CONTEXT.proposed.md"):
        return ""
    merge = merge_decision(ctx)
    if merge in ("all", "some"):
        return "Domain language: use the terms in CONTEXT.md."
    if merge == "defer":
        return ("Domain language: use the terms in CONTEXT.md. Also use the terms the user approved in "
                "%s/CONTEXT.proposed.md." % run_rel)
    return ("The terms in %s/CONTEXT.proposed.md were NOT accepted into the glossary: do not copy them into "
            "CONTEXT.md, CONCEPTS.md or any other repo doc." % run_rel)


def handoff_seed(ctx, step):
    items = publish_items(ctx)
    res = publish(ctx, items) if items else {"published": [], "not_published": []}
    ctx.state["published"] = res["published"]
    ctx.state["not_published"] = res["not_published"]
    kind = chosen_handoff(ctx)
    if kind in SEEDS:
        ctx.write("handoff/%s-seed.md" % kind, seed_text(ctx, kind))
    ctx.state["handoff"] = kind
    return "handoff seed: %s; published: %s%s" % (kind, ", ".join(res["published"]) or "nothing", (
        "; not published: %s" % ", ".join(res["not_published"])) if res["not_published"] else "")


def handoff_final(ctx, step):
    """12_HANDOFF.md (templates/docs/HANDOFF.md) + the LEDGER probe row. It ends with CLOSING, or with K6_WARNING once
    the chosen idea's probe missed with no runner-up left."""
    from . import builders
    from . import render
    s = ctx.state
    kind = s.get("handoff") or "none"
    iid = registry.chosen_idea(ctx) or "?"
    info = registry.idea_lines(ctx).get(iid, {})
    ch = s.get("choice") or {}
    if s.get("build_type") == "approach":
        arch_choice = "approach (%s)" % s.get("variant")
    else:
        arch_choice = "candidate %s (%s)" % (ch.get("arch") or "?", ch.get("arch_family") or "?")
    domain = "none proposed"
    if ctx.exists("CONTEXT.proposed.md"):
        cm = s.get("context_merge") or {}
        merge = merge_decision(ctx) or "declined"
        terms = ", ".join(cm.get("terms") or [])
        domain = "%s%s; ADRs: %s" % ({"all": "merged", "some": "merged", "defer": "deferred"}.get(merge, "declined"),
                                     (" " + terms) if terms else "", ", ".join(cm.get("adrs") or []) or "none")
    comp = "none"
    if kind in SEEDS:
        comps = s.get("components") or {}
        comp = {"ce": comps.get("ce_brainstorm") or "compound-engineering:ce-brainstorm",
                "speckit": comps.get("speckit") or "speckit"}.get(kind, kind)
    mapping = {"RUN_NAME": s.get("run", ""), "CHOSEN": "%s %s" % (iid, info.get("title", "")),
               "ARCH_CHOICE": arch_choice, "STATUS_BANNER": render.status_banner(ctx),
               "PROBE_STATUS": probe_status(ctx), "COMPONENT_NAME": comp,
               "SEED_PATH": ("handoff/%s-seed.md" % kind) if kind in SEEDS else "none",
               "PUBLISHED": ", ".join(s.get("published") or []) or "none",
               "NOT_PUBLISHED": ", ".join(s.get("not_published") or []), "DOMAIN_DOCS": domain}

    def builtin():
        lines = ["# Handoff: %(RUN_NAME)s" % mapping, "- Decision: %(CHOSEN)s (08_DECISION.md)" % mapping,
                 "- Architecture: %(ARCH_CHOICE)s (10_ARCHITECTURE/README.md)" % mapping,
                 "- Proposal: 11_PROPOSAL/PROPOSAL.md (%(STATUS_BANNER)s)" % mapping,
                 "- Milestone 0: %(PROBE_STATUS)s" % mapping, "- Handed to: %(COMPONENT_NAME)s" % mapping,
                 "- Seed: %(SEED_PATH)s" % mapping, "- Published: %(PUBLISHED)s" % mapping]
        if mapping["NOT_PUBLISHED"]:
            lines.append("- Not published: %(NOT_PUBLISHED)s" % mapping)
        lines += ["- Domain docs: %(DOMAIN_DOCS)s" % mapping, K6_WARNING if render.k6_dead(s) else CLOSING]
        return "\n".join(lines) + "\n"
    mapping["HANDOFF_BODY"] = builtin().rstrip("\n")
    mapping["DATE"] = textio.now_iso()[:10]
    ctx.write("12_HANDOFF.md", builders.render_doc("HANDOFF", mapping, fallback=builtin))
    probe = s.get("probe") or {}
    # only a result for the chosen idea (a probe of an idea that was switched away from has its own MISSED row)
    if probe.get("result") and probe.get("idea") in (None, iid) and not s.get("ledger_probe_written"):
        registry.append_ledger(ctx, ["| %s | %s | %s | %s | probe %s | 09_PROBE.md | - |" % (
            textio.now_iso()[:10], s.get("run"), iid, registry.clean(info.get("title", "")),
            probe["result"].lower())])
        s["ledger_probe_written"] = True
    return "12_HANDOFF.md written"


def probe_status(ctx):
    """The probe RESULT line with its date: PENDING, PASSED, MISSED or INCONCLUSIVE."""
    probe = ctx.read("09_PROBE.md")
    results = re.findall(r"^RESULT:\s*(.+)$", probe, re.M)
    last = results[-1].strip() if results else "PENDING"
    when = ((ctx.state.get("probe") or {}).get("at") or "")[:10]
    if last.upper().startswith("PENDING"):
        return "PENDING (riskiest assumption untested)"
    return "%s%s" % (last, (" (%s)" % when) if when else "")


def merge_decision(ctx):
    cm = ctx.state.get("context_merge") or {}
    return cm.get("merge_terms") or g14(ctx).get("merge_terms")
