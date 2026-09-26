"""Stage 14 Handoff (KIT_SPEC 9): publish copies (each needs its own yes), handoff seeds, 12_HANDOFF.md.

Scripts: handoff_seed (14.3), handoff_final (14.4).
"""

import filecmp
import json
import os
import posixpath
import re
import shutil
import tempfile

from .. import textio
from . import registry
from . import state as st

SEEDS = ("ce", "speckit", "superpowers", "openspec")
SEED_TEMPLATE = {"ce": "HANDOFF-CE", "speckit": "HANDOFF-SPECKIT", "superpowers": "HANDOFF-SUPERPOWERS",
                 "openspec": "HANDOFF-OPENSPEC"}
CLOSING = "Do not reopen the choice of idea or architecture."
PUBLISH = {"architecture": ("10_ARCHITECTURE", "docs/architecture"), "adr": ("10_ARCHITECTURE/adr", "docs/adr"),
           "proposal": ("11_PROPOSAL", "docs/proposal")}
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


PUBLISHED_MARKER = ".ub-published"
# Marker schema 2 (written since the cross-run fix): {"schema": 2, "run", "files": this run's files there,
# "legacy_files": files a pre-schema marker listed that the run's package does not have (kit 2.0.2 may have mixed
# another run in; they are left alone)}. A marker without "schema" comes from kit 2.0.2 or earlier.
MARKER_SCHEMA = 2
# What the files moved to _superseded by the current G14 answer's publish were, per item (so a retry after an
# interruption still reports them in 12_HANDOFF.md).
PUBLISH_PROGRESS = "handoff/publish-progress.json"
# Files an OS, a file browser or an editor drops into any folder: never published, and never make a folder "taken".
_IGNORED_NAMES = (".ds_store", "thumbs.db", "desktop.ini", ".gitkeep", ".keep")
_TMP_PREFIX = ".ub-copy."


def _kit_temp(name):
    low = name.lower()
    return low.endswith(".tmp") and low.startswith((_TMP_PREFIX, "." + PUBLISHED_MARKER + "."))


def _ignored(name):
    low = name.lower()
    return (low in _IGNORED_NAMES or low.startswith(("._", ".#")) or low.endswith((".swp", ".swo", "~"))
            or _kit_temp(name))


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
            if f.endswith((".meta.json", ".failed.md")) or f == PUBLISHED_MARKER or _ignored(f):
                continue
            full = os.path.join(dirpath, f)
            out.append((os.path.relpath(full, src).replace("\\", "/"), full))
    return out


def _safe_rel(rel):
    """A relative posix path that stays inside its folder and names a publishable file (marker entries are read from
    the repository)."""
    if not (isinstance(rel, str) and rel and not rel.startswith("/") and "\\" not in rel and ":" not in rel):
        return False
    parts = rel.split("/")
    return all(p not in ("", ".", "..") for p in parts) and parts[-1] != PUBLISHED_MARKER and not _ignored(parts[-1])


def _shown(text, limit=80):
    """A run name or path read from disk, safe to put on a card: one line, ASCII; cut at limit, visibly."""
    if len(text) <= 160 and all(32 <= ord(c) < 127 for c in text):
        return text
    if len(text) > limit:
        return json.dumps(text[:limit], ensure_ascii=True)[:-1] + '..."'
    return json.dumps(text, ensure_ascii=True)


def _marker(dst):
    """The .ub-published marker of a target folder, every field checked (it is read from the repository)."""
    try:
        data = textio.read_json(os.path.join(dst, PUBLISHED_MARKER))
    except (OSError, ValueError):
        data = None
    data = data if isinstance(data, dict) else {}

    def rels(key):
        v = data.get(key)
        return sorted(set(f for f in v if _safe_rel(f))) if isinstance(v, list) else []
    run = data.get("run")
    return {"run": run if isinstance(run, str) and run else None, "files": rels("files"),
            "legacy_files": rels("legacy_files"),
            "schema": data.get("schema") if isinstance(data.get("schema"), int) else None}


def _write_marker(dst, run_name, files, legacy_files=()):
    data = {"schema": MARKER_SCHEMA, "run": run_name, "files": sorted(set(files))}
    if legacy_files:
        data["legacy_files"] = sorted(set(legacy_files))
    textio.write_json_atomic(os.path.join(dst, PUBLISHED_MARKER), data)


def _scan(dst):
    """(files, link): the files under dst (posix relpaths; the marker and OS/editor litter left out) and the first
    folder or file under dst that is a link or junction (publish could write through it), or None."""
    files, link = [], None
    for dirpath, dirs, names in os.walk(dst):
        keep = []
        for d in sorted(dirs):
            if _is_link(os.path.join(dirpath, d)):
                link = link or os.path.relpath(os.path.join(dirpath, d), dst).replace("\\", "/")
            else:
                keep.append(d)
        dirs[:] = keep
        for f in names:
            full = os.path.join(dirpath, f)
            if os.path.islink(full):
                link = link or os.path.relpath(full, dst).replace("\\", "/")
            if f == PUBLISHED_MARKER or _ignored(f):
                continue
            files.append(os.path.relpath(full, dst).replace("\\", "/"))
    return files, link


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


def _holder(pd, rel, run_name):
    """Who holds the target folder pd/rel: ("mine", None) this run's marker lists every file in it (also when only the
    marker is left); ("run", <name>) another run's marker is there with files, or a schema-2 one listing files;
    ("free", None) absent or empty (an old marker of another run or OS litter alone does not count); ("foreign",
    None) it holds files the kit did not publish; ("link", <relpath>) it, a folder above it (up to docs/) or
    something inside it is a link or junction."""
    link = _link_on_path(pd, rel)
    if link:
        return "link", link
    dst = os.path.join(pd, *rel.split("/"))
    if not os.path.exists(dst):
        return "free", None
    if not os.path.isdir(dst):
        return "foreign", None
    files, inner = _scan(dst)
    if inner:
        return "link", "%s/%s" % (rel, inner)
    marker = _marker(dst)
    if marker["run"] == run_name and set(files) <= set(marker["files"]) | set(marker["legacy_files"]):
        return "mine", None
    if marker["run"] and marker["run"] != run_name and (files or (marker["schema"] == MARKER_SCHEMA
                                                                  and marker["files"])):
        return "run", marker["run"]
    if not files:
        return "free", None
    return "foreign", None


def _taken(rel, holder, other):
    if holder == "link":
        return "%s is a link or junction" % _shown(other)
    if holder == "run":
        return "%s holds run %s" % (rel, _shown(other))
    return "%s holds files the kit did not publish" % rel


ALL_ITEMS = ("architecture", "adr", "proposal")


def _place(ctx, item, planned):
    """Where one item goes (the target half of plan_target): the fixed folder (docs/architecture, docs/adr,
    docs/proposal) when it is free or this run published it; when another run's package or the project's own files are
    there, or it is a link or junction, the run's own folder docs/<run>/<item>, so two runs never mix (two ADR sets both
    numbered 0001, say) and nothing already there is touched or written through. A copy this run made earlier (also
    in the 2.0.x fallback docs/<item>/ub-<run>/) is updated where it is, even when the package has no files any more."""
    src_rel, base_rel = PUBLISH[item]
    pd = ctx.state.get("project_dir") or "."
    run_name = _run_name(ctx)
    own_rel = "docs/%s/%s" % (run_name, item)
    legacy_rel = "%s/ub-%s" % (base_rel, run_name)
    plan = {"item": item, "src": src_rel, "base": base_rel, "dst": None, "state": "refused", "empty": False,
            "other_run": None, "why": "", "blocker": None, "legacy_dst": legacy_rel, "retire": []}
    base, other = _holder(pd, base_rel, run_name)
    own, own_other = _holder(pd, own_rel, run_name)
    mines = [rel for rel, held in ((base_rel, base), (own_rel, own), (legacy_rel, _holder(pd, legacy_rel, run_name)[0]))
             if held == "mine"]
    mine = mines[0] if mines else None
    if mine:
        # this run's other copies of the item (a link that came and went, say) are retired, so no two remain
        plan.update(dst=mine, state="update", empty=not planned, retire=mines[1:])
    elif not planned:
        plan.update(state="empty", why="no files")
    elif base == "free":
        plan.update(dst=base_rel, state="new")
    elif own != "free" or not RUN_NAME_RE.match(run_name):
        reasons = [_taken(base_rel, base, other), _taken(own_rel, own, own_other) if own != "free"
                   else "the run name is not a safe folder name"]
        plan.update(why="; ".join(r for i, r in enumerate(reasons) if r not in reasons[:i]),
                    blocker=(_shown(own_other, 4096) if own == "link" else own_rel) if own != "free" else None)
    else:
        plan.update(dst=own_rel, state={"run": "other-run", "link": "linked"}.get(base, "foreign"), other_run=other,
                    why=_taken(base_rel, base, other))
    return plan


def _abs(ctx, rel):
    return os.path.join(ctx.state.get("project_dir") or ".", *rel.split("/"))


def _layout(ctx, items=None):
    """Where every item goes, and "home": the adr copy's folder, the one place the ADRs are published to and every
    ADR link of the architecture and proposal copies points at (None when the run has no ADRs or the adr folder cannot
    be placed; the links are then left as they are). Publishing `architecture` or `proposal` publishes the ADRs too,
    so every link is written against a fresh copy; the architecture copy never holds adr/. items None: all three (the
    card shows the plan for the answer `publish`)."""
    asked = list(ALL_ITEMS) if items is None else [i for i in ALL_ITEMS if i in items]
    sources = dict((i, _source_files(ctx.path(PUBLISH[i][0]))) for i in ALL_ITEMS)
    places = dict((i, _place(ctx, i, set(rel for rel, _f in sources[i]))) for i in ALL_ITEMS)
    run_items = list(asked)
    if "adr" not in asked and sources["adr"] and any(places[i]["dst"] for i in ("architecture", "proposal")
                                                     if i in asked):
        run_items.append("adr")
    home = places["adr"]["dst"] if sources["adr"] else None
    return {"asked": asked, "items": [i for i in ALL_ITEMS if i in run_items], "sources": sources, "places": places,
            "home": home, "cache": {}}


def _relpath(to_rel, from_rel):
    """Project-relative folder to_rel as seen from folder from_rel (forward slashes)."""
    return posixpath.relpath("/" + to_rel, "/" + from_rel)


def _adr_links(src_rel, dst_rel, rel, target):
    """(old, new) link prefix to the ADRs for file rel of a copy: the run's 10_ARCHITECTURE/adr as seen from the
    file's folder in the run, and the ADRs' target folder as seen from the file's folder in the copy."""
    folder = posixpath.dirname(rel)
    return (_relpath(PUBLISH["adr"][0], posixpath.join(src_rel, folder)) + "/",
            _relpath(target, posixpath.join(dst_rel, folder)) + "/")


def _relink(raw, old, new):
    """raw (bytes) with every Markdown link, <angle> link, reference definition and HTML href/src whose target starts
    with old (optionally written as ./old) pointed at new instead. Works on the bytes, so the encoding, a BOM and the
    line endings stay as they are; UTF-16 files are left alone."""
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw
    pattern = (br"(\]\([ \t]*<?|(?:href|src)=[\"']|^[ \t]{0,3}\[[^\]\r\n]+\]:[ \t]*<?)(?:\./)?"
               + re.escape(old.encode("utf-8")))
    return re.sub(pattern, lambda m: m.group(1) + new.encode("utf-8"), raw, flags=re.M)


# the link forms _relink rewrites, as targets: ](x), ](<x>), href="x" / src='x', and [ref]: x (any line ending/title)
_LINK_TARGET_RE = re.compile(br"\]\([ \t]*<?([^)\s>]+)|(?:href|src)=[\"']([^\"']+)"
                             br"|^[ \t]{0,3}\[[^\]\r\n]+\]:[ \t]*<?([^\s>]+)", re.M)


def _link_targets(ctx, dst_rel):
    """The project-relative paths the Markdown and HTML files of the published copy at dst_rel link to (only the
    files its marker lists)."""
    out = set()
    dst = _abs(ctx, dst_rel)
    for f in _marker(dst)["files"]:
        if not f.lower().endswith((".md", ".html")):
            continue
        try:
            with open(os.path.join(dst, *f.split("/")), "rb") as fh:
                raw = fh.read()
        except OSError:
            continue
        for m in _LINK_TARGET_RE.finditer(raw):
            link = (m.group(1) or m.group(2) or m.group(3) or b"").decode("utf-8", "replace")
            link = link.split("#")[0].split("?")[0]
            if not link or link.startswith("/") or re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", link):
                continue
            out.add(posixpath.normpath(posixpath.join(dst_rel, posixpath.dirname(f), link)))
    return out


def _outside_links(ctx, layout):
    """Every path that a published copy of this run links to, other than the copies this answer rewrites: the
    folders whose marker names this run (fixed, docs/<run>/<item>, 2.0.x ub-<run>), whatever their state."""
    if "outside" not in layout["cache"]:
        pd = ctx.state.get("project_dir") or "."
        run_name = _run_name(ctx)
        rewritten = set(layout["places"][i]["dst"] for i in layout["items"] if layout["places"][i]["dst"])
        rewritten |= set(r for i in layout["items"] for r in layout["places"][i]["retire"])
        out = set()
        for item in ALL_ITEMS:
            base = PUBLISH[item][1]
            for rel in (base, "docs/%s/%s" % (run_name, item), "%s/ub-%s" % (base, run_name)):
                if rel in rewritten or _link_on_path(pd, rel) or not os.path.isdir(_abs(ctx, rel)):
                    continue
                if _marker(_abs(ctx, rel))["run"] == run_name:
                    out |= _link_targets(ctx, rel)
        layout["cache"]["outside"] = out
    return layout["cache"]["outside"]


def _package(ctx, item, layout):
    """rel -> (source path, bytes to write or None to copy the file as it is): what the item's copy holds. The
    architecture copy leaves out adr/ (the ADRs live only in the adr copy), and the ADR links of the Markdown and HTML
    files of the architecture and proposal copies point at home."""
    place, target = layout["places"][item], layout["home"]
    src_rel, dst_rel = place["src"], place["dst"]
    out = {}
    for rel, full in layout["sources"][item]:
        if item == "architecture" and rel.startswith("adr/"):
            continue
        data = None
        if target and dst_rel and item != "adr" and rel.lower().endswith((".md", ".html")):
            old, new = _adr_links(src_rel, dst_rel, rel, target)
            if old != new:
                try:
                    with open(full, "rb") as fh:
                        raw = fh.read()
                except OSError:
                    raw = None
                if raw is not None:
                    relinked = _relink(raw, old, new)
                    if relinked != raw:
                        data = relinked
        out[rel] = (full, data)
    return out


def _samefile(a, b):
    try:
        return os.path.samefile(a, b)
    except OSError:
        return False


def _same(path, full, data):
    """True when the file at path already holds what the copy would write."""
    if data is None:
        return filecmp.cmp(path, full, shallow=False)
    with open(path, "rb") as fh:
        return fh.read() == data


def _plan(ctx, item, layout):
    plan = dict(layout["places"][item], stale=[], kept=[], clash=[], pinned=[], relocated=[], renamed=[],
                home=layout["home"])
    if plan["state"] != "update":
        return plan
    package = _package(ctx, item, layout)
    planned = set(package)
    dst = _abs(ctx, plan["dst"])
    marker = _marker(dst)

    def on_disk(rel):
        return os.path.isfile(os.path.join(dst, *rel.split("/")))

    def alias(f):
        """f names the same file as a planned name of other letter case (a case-insensitive disk)."""
        return any(q.lower() == f.lower() and q != f and _samefile(os.path.join(dst, *f.split("/")),
                                                                  os.path.join(dst, *q.split("/"))) for q in planned)
    if marker["schema"] is None and plan["dst"] != plan["legacy_dst"]:
        # written by kit 2.0.2 or earlier: its list may include another run's files (the cross-run bug), so the
        # files the package does not have stay, and the ones it replaces are flagged
        plan["kept"] = sorted(f for f in set(marker["files"]) - planned if on_disk(f))
        suspect = set(marker["files"]) if plan["kept"] else set()
        stale = []
    else:
        stale = sorted(f for f in set(marker["files"]) - planned if on_disk(f))
        plan["kept"] = sorted(f for f in set(marker["legacy_files"]) - planned if on_disk(f))
        suspect = set(marker["legacy_files"])
    # a case-only rename on a case-insensitive disk: the old name is the same file as a new one (links to it still
    # resolve), so it is moved out before the new file is written, never kept or moved later
    plan["renamed"] = sorted(f for f in stale if alias(f))
    stale = sorted(set(stale) - set(plan["renamed"]))
    if stale:
        # never take away a file that another published copy of this run, not rewritten now, links to
        linked = _outside_links(ctx, layout)
        by_lower = {}
        for target in linked:
            by_lower.setdefault(target.lower(), []).append(target)

        def is_linked(f):
            rel = posixpath.join(plan["dst"], f)
            if rel in linked:
                return True
            # a link spelled with other letter case reaches the same file on a case-insensitive disk
            return any(_samefile(_abs(ctx, target), _abs(ctx, rel)) for target in by_lower.get(rel.lower(), []))
        plan["pinned"] = sorted(f for f in stale if is_linked(f))
    plan["stale"] = sorted(set(stale) - set(plan["pinned"]))
    if item == "architecture":
        plan["relocated"] = [f for f in stale if f.startswith("adr/")]
    plan["clash"] = sorted(f for f in suspect & planned if on_disk(f) and not _same(
        os.path.join(dst, *f.split("/")), *package[f]))
    # a leftover that is a case variant of a new file is that file: it is replaced (backed up), not kept
    for f in [f for f in plan["kept"] if alias(f)]:
        plan["kept"].remove(f)
        twin = [q for q in planned if q.lower() == f.lower()][0]
        if twin not in plan["clash"] and not _same(os.path.join(dst, *f.split("/")), *package[twin]):
            plan["clash"] = sorted(plan["clash"] + [twin])
    return plan


def plan_target(ctx, item, items=None):
    """What publishing one item does: where it goes and what happens there. The G14 card shows this plan (for the
    answer `publish`, items None) and publish() follows it.
    Returns {"item", "src", "base", "dst" (None = not published), "state" (new, update, other-run, foreign, refused,
    empty), "empty" (update of an earlier copy by a package with no files), "other_run", "why", "blocker" (the folder
    to move aside when refused), "stale" (files of this run's earlier copy that its package no longer has: moved to
    the backup), "relocated" (the stale adr/ files of an architecture copy whose ADRs now live in the adr copy),
    "pinned" (stale files another published copy of this run links to: kept), "kept" (files a pre-schema marker
    listed that the package does not have: left in place), "clash" (files a pre-schema publish left there that the
    package replaces with other content: backed up first)}."""
    return _plan(ctx, item, _layout(ctx, items))


def adr_card_note(ctx, layout):
    """The G14 card line that says where the ADRs end up ("" when there is nothing to say)."""
    adr = layout["places"]["adr"]
    linking = [i for i in ("architecture", "proposal") if layout["places"][i]["dst"]]
    names = " and ".join("`%s`" % i for i in linking)
    if layout["sources"]["adr"]:
        if adr["dst"] and linking:
            return ("ADRs are published once, to %s: %s %s them there too, and %s ADR links point there. An old ADR "
                    "file that a copy not published in the same answer still links to stays until nothing links to it."
                    % (adr["dst"], names, "publish" if len(linking) > 1 else "publishes",
                       "their" if len(linking) > 1 else "its"))
        if adr["dst"]:
            return "ADRs are published once, to %s." % adr["dst"]
        if linking:
            return ("The adr folder cannot be used (see above), so the ADR links of the %s %s are left as they are "
                    "and will not resolve; move that folder aside and redo step 14.2." % (
                        " and ".join(linking), "copies" if len(linking) > 1 else "copy"))
        return ""
    if adr["state"] == "update":
        return ("This run has no ADRs now: `adr` moves its old ADR copy in %s to the backup (except files a published "
                "copy of this run still links to)." % adr["dst"])
    return ""


def card_lines(ctx):
    """The G14 card's publish block: one line per item (for the answer `publish`), then where the ADRs end up."""
    layout = _layout(ctx)
    note = adr_card_note(ctx, layout)
    return [card_line(_plan(ctx, item, layout)) for item in ALL_ITEMS] + ([note] if note else [])


def _count(n, one, many):
    return "%d %s" % (n, one if n == 1 else many)


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
    if plan["state"] == "update":
        line = head + "%s (this run published here before; %s)" % (
            plan["dst"], "its package now has no files" if plan["empty"] else "files it replaces are backed up first")
        moving = [f for f in plan["stale"] if f in plan["relocated"]]
        other = [f for f in plan["stale"] + plan["renamed"] if f not in plan["relocated"]]
        pinned_adrs = [f for f in plan["pinned"] if f in plan["relocated"]]
        pinned_other = [f for f in plan["pinned"] if f not in plan["relocated"]]
        if moving:
            n = len(moving)
            line += ". Its old %s of %s (%s) %s to the backup" % (
                "copy" if n == 1 else "copies", _count(n, "ADR", "ADRs"),
                "ADRs live only in the adr copy now" if plan["home"] else "the architecture copy holds no ADRs now",
                "moves" if n == 1 else "move")
        if other:
            n = len(other)
            line += ". %s this run published there before and no longer has %s to the backup" % (
                _count(n, "file", "files"), "moves" if n == 1 else "move")
        if pinned_adrs:
            n = len(pinned_adrs)
            line += ". Its old %s of %s %s, because another published copy of this run links to %s" % (
                "copy" if n == 1 else "copies", _count(n, "ADR", "ADRs"), "stays" if n == 1 else "stay",
                "it" if n == 1 else "them")
        if pinned_other:
            n = len(pinned_other)
            line += ". %s this run no longer has %s, because another published copy of this run links to %s" % (
                _count(n, "file", "files"), "stays" if n == 1 else "stay", "it" if n == 1 else "them")
        if plan["kept"]:
            n = len(plan["kept"])
            line += (". WARNING: it also holds %s that this run's package does not have, published by kit 2.0.2 or "
                     "earlier and possibly from another run; %s in place" % (
                         _count(n, "file", "files"), "it stays" if n == 1 else "they stay"))
        if plan["clash"]:
            line += (". WARNING: it replaces %s that kit 2.0.2 or earlier published there, possibly another run's "
                     "(backed up first)" % _count(len(plan["clash"]), "file", "files"))
        if plan["retire"]:
            line += (". This run's other copy in %s moves to the backup (files another published copy links to stay)"
                     % " and ".join(plan["retire"]))
        return line + ("." if plan["stale"] or plan["renamed"] or plan["pinned"] or plan["kept"] or plan["clash"]
                       or plan["retire"] else "")
    if plan["state"] == "other-run":
        return head + "%s. WARNING: %s already holds another run's package (%s); nothing there is changed." % (
            plan["dst"], plan["base"], _shown(plan["other_run"]))
    if plan["state"] == "foreign":
        return head + "%s. %s already holds files the kit did not publish; nothing there is changed." % (
            plan["dst"], plan["base"])
    if plan["state"] == "linked":
        return head + "%s. %s; nothing is written through it." % (plan["dst"], plan["why"])
    return head + plan["dst"]


def _tidy(dst, moved):
    """Remove the kit's own temp files an interrupted publish left under dst, and the folders that moving this run's
    old files (moved: relpaths) left empty."""
    for dirpath, _dirs, names in os.walk(dst):
        for f in names:
            full = os.path.join(dirpath, f)
            if _kit_temp(f) and os.path.isfile(full) and not os.path.islink(full):
                try:
                    os.unlink(full)
                except OSError:
                    pass
    top = os.path.normcase(os.path.abspath(dst))
    for rel in sorted(moved, key=lambda r: -r.count("/")):
        d = os.path.dirname(os.path.abspath(os.path.join(dst, *rel.split("/"))))
        while os.path.normcase(d).startswith(top + os.sep):
            try:
                os.rmdir(d)
            except OSError:
                break
            d = os.path.dirname(d)


def _copy_replace(src, dst, data=None):
    """Copy src (or write data, when given) over dst through a temp file and a rename, so a hard link at dst is
    replaced, never written through."""
    tmp = None
    try:
        fd, tmp = tempfile.mkstemp(prefix=_TMP_PREFIX, suffix=".tmp", dir=os.path.dirname(dst))
        os.close(fd)
        if data is None:
            shutil.copy2(src, tmp)
        else:
            with open(tmp, "wb") as fh:
                fh.write(data)
        textio._replace_with_retry(tmp, dst)
        tmp = None
    finally:
        if tmp is not None and os.path.exists(tmp):
            os.unlink(tmp)


def _backup_stamp(ctx):
    """A stamp whose _superseded/<stamp>/published/ does not exist yet, so a backup never overwrites an older one."""
    stamp = st.iso_stamp()
    n = 1
    while os.path.exists(ctx.path("_superseded", stamp if n == 1 else "%s-%d" % (stamp, n), "published")):
        n += 1
    return stamp if n == 1 else "%s-%d" % (stamp, n)


def _rels(value):
    """A list of safe relpaths from the progress file (it is only ever written by publish(); checked anyway)."""
    return sorted(set(f for f in value if _safe_rel(f))) if isinstance(value, list) else []


def _progress(ctx):
    """The moves already made for the current G14 answer (reset when G14 is answered again)."""
    session = ((ctx.state.get("gates") or {}).get("G14") or {}).get("at") or ""
    prog = ctx.read_json(PUBLISH_PROGRESS, {}) if session else {}
    if not isinstance(prog, dict) or prog.get("g14_at") != session or not isinstance(prog.get("items"), dict):
        prog = {"g14_at": session, "items": {}}
    return prog


def _retire(ctx, layout, item, plan, run_name, backup):
    """Move this run's other copies of the item (plan["retire"]) to the backup, except files a published copy of this
    run that stays links to. Returns [(folder, moved, kept)]."""
    out = []
    linked = _outside_links(ctx, layout)
    for k, old_rel in enumerate(plan["retire"], 1):
        old = _abs(ctx, old_rel)
        marker = _marker(old)
        files = [f for f in marker["files"] + marker["legacy_files"]
                 if os.path.isfile(os.path.join(old, *f.split("/")))]
        keep = [f for f in files if posixpath.join(old_rel, f) in linked]
        moved = 0
        for f in files:
            path = os.path.join(old, *f.split("/"))
            if f in keep or os.path.islink(path):
                continue
            shutil.move(path, backup("%s-retired%d" % (item, k), f))
            moved += 1
        if keep:
            _write_marker(old, run_name, keep)
        else:
            shutil.move(os.path.join(old, PUBLISHED_MARKER), backup("%s-retired%d" % (item, k), PUBLISHED_MARKER))
        _tidy(old, files)
        for folder in (old, os.path.dirname(old)) if old_rel.startswith("docs/%s/" % run_name) else (old,):
            try:
                os.rmdir(folder)
            except OSError:
                break
        out.append((old_rel, moved, len(keep)))
    return out


def publish(ctx, items):
    """Copy each approved item into <project>/docs/... file by file, at the place plan_target() names; `architecture`
    and `proposal` publish the ADRs too (the one folder their ADR links point at). Nothing is ever deleted, and only
    this run's own files are ever touched: a file that would be overwritten, or a file of this run's earlier copy that
    its package no longer has, goes to _superseded/<stamp>/published/<item>/ first. Two phases: every copy gets its new
    files first (the adr copy before the copies that link to it); only then do old files leave, except the ones a
    published copy of this run outside the answer still links to. The marker is written before the first change, so
    an interrupted publish resumes in the same folder.
    Returns {"published": [...], "not_published": [...]} (one short line each, for 12_HANDOFF.md)."""
    pd = ctx.state.get("project_dir")
    out = {"published": [], "not_published": []}
    if not pd:
        return out
    stamp = _backup_stamp(ctx)
    run_name = _run_name(ctx)
    prog = _progress(ctx)
    layout = _layout(ctx, items)
    home = layout["home"]
    lines = {}
    work = []

    def backup(item, rel):
        path = ctx.path("_superseded", stamp, "published", item, *rel.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        return path
    for item in sorted(layout["items"], key=lambda i: i != "adr"):
        plan = _plan(ctx, item, layout)
        src_rel, dst_rel = plan["src"], plan["dst"]
        if not dst_rel:
            if item in layout["asked"] or plan["state"] != "empty":
                lines[item] = ("not_published", "%s (%s)" % (src_rel, plan["why"]))
            continue
        dst = os.path.join(pd, *dst_rel.split("/"))
        package = _package(ctx, item, layout)
        planned = set(package)
        entry = prog["items"].get(item)
        entry = entry if isinstance(entry, dict) and entry.get("dst") == dst_rel else {}
        entry = {"dst": dst_rel, "moved": _rels(entry.get("moved")),
                 "moving": sorted(set(_rels(entry.get("moving"))) | set(plan["stale"])),
                 "clash": sorted(set(_rels(entry.get("clash"))) | set(plan["clash"]))}
        prog["items"][item] = entry
        textio.write_json_atomic(ctx.path(PUBLISH_PROGRESS), prog)
        os.makedirs(dst, exist_ok=True)
        # until a clashing file is replaced it stays a leftover, so a re-asked card still warns about it
        _write_marker(dst, run_name, (planned - set(plan["clash"])) | set(plan["stale"]) | set(plan["pinned"])
                      | set(plan["renamed"]), set(plan["kept"]) | set(plan["clash"]))
        for rel in plan["renamed"]:
            # a case-only rename on a case-insensitive disk: the old name is the new file, so move it out first
            path = os.path.join(dst, *rel.split("/"))
            if os.path.isfile(path) and not os.path.islink(path):
                shutil.move(path, backup(item, rel))
                entry["moved"] = sorted(set(entry["moved"]) | {rel})
                textio.write_json_atomic(ctx.path(PUBLISH_PROGRESS), prog)
        for rel in sorted(package):
            full, data = package[rel]
            target = os.path.join(dst, *rel.split("/"))
            if os.path.isdir(target):
                continue
            if os.path.isfile(target):
                if _same(target, full, data):
                    continue
                shutil.copy2(target, backup(item, rel))
            os.makedirs(os.path.dirname(target), exist_ok=True)
            _copy_replace(full, target, data)
        work.append((item, plan, dst_rel, dst, planned, entry))
    for item, plan, dst_rel, dst, planned, entry in work:
        keep = [os.path.join(dst, *q.split("/")) for q in sorted(planned | set(plan["pinned"]))]
        for rel in plan["stale"]:
            path = os.path.join(dst, *rel.split("/"))
            if any(_samefile(path, q) for q in keep if q.lower() == path.lower()):
                continue  # another name for a file that stays (a case-insensitive disk)
            if os.path.isfile(path) and not os.path.islink(path):
                shutil.move(path, backup(item, rel))
                entry["moved"] = sorted(set(entry["moved"]) | {rel})
                textio.write_json_atomic(ctx.path(PUBLISH_PROGRESS), prog)
        _write_marker(dst, run_name, planned | set(plan["pinned"]), plan["kept"])
        retired = _retire(ctx, layout, item, plan, run_name, backup)
        moved = set(entry["moved"]) | set(f for f in entry["moving"] if f not in planned
                                          and not os.path.lexists(os.path.join(dst, *f.split("/"))))
        _tidy(dst, sorted(moved))
        textio.write_json_atomic(ctx.path(PUBLISH_PROGRESS), prog)
        notes = [plan["why"]] if plan["why"] else []
        if item not in layout["asked"]:
            notes.append("published with the copies that link to it")
        if plan["empty"]:
            notes.append("the package has no files; nothing copied")
        if item == "architecture" and home:
            notes.append("its ADRs are in %s" % home)
        if item in ("architecture", "proposal") and not home and layout["sources"]["adr"]:
            notes.append("its ADR links are not rewritten: the adr folder cannot be used")
        if moved:
            notes.append("%s moved to _superseded" % _count(len(moved), "old file", "old files"))
        for old_rel, n_moved, n_kept in retired:
            notes.append("this run's other copy in %s: %s moved to _superseded%s" % (
                old_rel, _count(n_moved, "file", "files"), ("; %d kept (linked)" % n_kept) if n_kept else ""))
        if plan["pinned"]:
            notes.append("%s kept: another published copy of this run links to %s" % (
                _count(len(plan["pinned"]), "old file", "old files"), "it" if len(plan["pinned"]) == 1 else "them"))
        if entry["clash"]:
            notes.append("%s from kit 2.0.2 or earlier replaced, backed up" % _count(len(entry["clash"]), "file",
                                                                                        "files"))
        if plan["kept"]:
            notes.append("%s from kit 2.0.2 or earlier left in place" % _count(len(plan["kept"]), "file", "files"))
        lines[item] = ("published", "%s -> %s%s" % (plan["src"], dst_rel,
                                                    (" (%s)" % "; ".join(notes)) if notes else ""))
    for item in ALL_ITEMS:
        if item in lines:
            out[lines[item][0]].append(lines[item][1])
    return out


def seed_text(ctx, kind):
    s = ctx.state
    run_rel = "brainstorm/%s" % s.get("run", "")
    iid = registry.chosen_idea(ctx) or "?"
    info = registry.idea_lines(ctx).get(iid, {})
    check = ctx.read("checks/%s.md" % iid)
    dec = ctx.read("08_DECISION.md")
    not_doing = "; ".join(m.group(1).strip() for m in re.finditer(r"^Not doing[^:]*:\s*(.*)$", dec, re.M))
    kills = re.findall(r"(Fails if[^\n|]*)", check + "\n" + ctx.read("07_REDTEAM.md"))[:3]
    dissent = "; ".join(m.group(1).strip() for m in re.finditer(r"^Dissent recorded:\s*(.*)$", dec, re.M))
    why = ""
    m = re.search(r"^Chosen[^:]*:\s*[IEQ]-\d+[^-]*-\s*(.*)$", dec, re.M)
    if m:
        why = m.group(1).strip()
    verdict, diff = registry.check_verdict(ctx, iid)
    mapping = {
        "IDEA_TITLE": registry.clean(info.get("title") or s.get("topic", "")),
        "IDEA_ONE_LINER": registry.clean(info.get("pitch") or info.get("title") or s.get("topic", "")).rstrip("."),
        "BASIS": "prior-art verdict %s%s" % (verdict or "NOT CHECKED", ("; differentiator: %s" % diff) if diff else ""),
        "WHY_IT_MATTERS": why or "see 08_DECISION.md",
        "TRADEOFFS": "; ".join(kills + ([dissent] if dissent and dissent != "none" else [])) or "see 07_REDTEAM.md",
        "SETTLED": "Not doing: %s" % (not_doing or "see 08_DECISION.md"), "PROBE_STATUS": probe_status(ctx),
        "DOMAIN_CLAUSE": domain_clause(ctx, run_rel), "RUN_NAME": s.get("run", ""),
        "NOT_DOING": not_doing or "see 08_DECISION.md"}
    # the names of the first engine version's mapping (templates may use either set)
    passed = "RESULT: PASSED" in ctx.read("09_PROBE.md")
    mapping.update({"TITLE": mapping["IDEA_TITLE"], "DESCRIPTION": mapping["IDEA_ONE_LINER"], "IDEA_ID": iid,
                    "RUN_PATH": run_rel, "PROBE_RESULT": mapping["PROBE_STATUS"],
                    "ARCH_README": "%s/10_ARCHITECTURE/README.md" % run_rel,
                    "PROPOSAL": "%s/11_PROPOSAL/PROPOSAL.md" % run_rel, "DATE": textio.now_iso()[:10],
                    "PROBE_WARNING": "" if passed else "WARNING: riskiest assumption untested (09_PROBE.md has no "
                                                        "RESULT: PASSED)."})
    from . import builders
    text = builders.render_doc(SEED_TEMPLATE[kind], mapping)
    if not text:
        text = builtin_seed(kind, dict(mapping, RUN_PATH=run_rel, ARCH_README="%s/10_ARCHITECTURE/README.md" % run_rel,
                                       PROPOSAL="%s/11_PROPOSAL/PROPOSAL.md" % run_rel))
    text = text.rstrip()
    if not text.endswith(CLOSING):
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


def builtin_seed(kind, m):
    arch = ("Architecture decisions: %s (ADRs accepted). Milestone 0 (09_PROBE.md) runs first; do not plan beyond "
            "its kill criterion." % m["ARCH_README"])
    if kind == "ce":
        body = ("%s - %s. Basis: %s. Why it matters: %s. Known tradeoffs: %s. Settled decisions: %s. Probe result: "
                "%s. %s %s" % (m["IDEA_TITLE"], m["IDEA_ONE_LINER"], m["BASIS"], m["WHY_IT_MATTERS"], m["TRADEOFFS"],
                               m["SETTLED"], m["PROBE_STATUS"], m["DOMAIN_CLAUSE"], arch))
    elif kind == "speckit":
        body = ("%s - %s. Specify what %s describes in sections 3, 6, 7 and 8, using %s/10_ARCHITECTURE/chosen/. "
                "Out of scope: %s. Probe result: %s. %s" % (m["IDEA_TITLE"], m["IDEA_ONE_LINER"], m["PROPOSAL"],
                                                            m["RUN_PATH"], m["NOT_DOING"], m["PROBE_STATUS"], arch))
    elif kind == "superpowers":
        body = ("Architectural path. Inputs: %s/08_DECISION.md, %s/09_PROBE.md and %s - read them fully first. The "
                "decision, scope, Not doing list and kill criteria are approved by me. Stop after the spec for my "
                "review. Probe result: %s. %s" % (m["RUN_PATH"], m["RUN_PATH"], m["ARCH_README"], m["PROBE_STATUS"],
                                                  arch))
    else:
        body = ("Direction already chosen: %s/08_DECISION.md and %s. Test it against the current specs and code and "
                "raise conflicts one question at a time. Do not write anything until I ask. Probe result: %s."
                % (m["RUN_PATH"], m["ARCH_README"], m["PROBE_STATUS"]))
    return "%s\n%s\n" % (body, CLOSING)


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
    """12_HANDOFF.md (templates/docs/HANDOFF.md) + the LEDGER probe row."""
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
        lines += ["- Domain docs: %(DOMAIN_DOCS)s" % mapping, CLOSING]
        return "\n".join(lines) + "\n"
    mapping["HANDOFF_BODY"] = builtin().rstrip("\n")
    mapping["DATE"] = textio.now_iso()[:10]
    ctx.write("12_HANDOFF.md", builders.render_doc("HANDOFF", mapping, fallback=builtin))
    probe = s.get("probe") or {}
    if probe.get("result") and not s.get("ledger_probe_written"):
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
