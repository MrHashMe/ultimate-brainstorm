"""Stage 14 Handoff (KIT_SPEC 9): publish copies (each needs its own yes), handoff seeds, 12_HANDOFF.md.

Scripts: handoff_seed (14.3), handoff_final (14.4).
"""

import filecmp
import json
import os
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


def plan_target(ctx, item):
    """Where one item goes. The fixed folder (docs/architecture, docs/adr, docs/proposal) when it is free or this run
    published it; when another run's package or the project's own files are there, the run's own folder
    docs/<run>/<item>, so two runs never mix (two ADR sets both numbered 0001, say) and nothing already there is
    touched. A copy this run made earlier (also in the 2.0.x fallback docs/<item>/ub-<run>/) is updated where it is,
    even when the package has no files any more. The G14 card shows this plan and publish() follows it.
    Returns {"item", "src", "base", "dst" (None = not published), "state" (new, update, other-run, foreign, refused,
    empty), "empty" (update of an earlier copy by a package with no files), "other_run", "why", "blocker" (the folder
    to move aside when refused), "stale" (files of this run's earlier copy that its package no longer has: moved to
    the backup), "kept" (files a pre-schema marker listed that the package does not have: left in place), "clash"
    (files a pre-schema publish left there that the package replaces with other content: backed up first)}."""
    src_rel, base_rel = PUBLISH[item]
    pd = ctx.state.get("project_dir") or "."
    run_name = _run_name(ctx)
    own_rel = "docs/%s/%s" % (run_name, item)
    legacy_rel = "%s/ub-%s" % (base_rel, run_name)
    plan = {"item": item, "src": src_rel, "base": base_rel, "dst": None, "state": "refused", "empty": False,
            "other_run": None, "why": "", "blocker": None, "stale": [], "kept": [], "clash": []}
    sources = dict(_source_files(ctx.path(src_rel)))
    planned = set(sources)
    base, other = _holder(pd, base_rel, run_name)
    own, own_other = _holder(pd, own_rel, run_name)
    mine = (base_rel if base == "mine" else own_rel if own == "mine" else
            legacy_rel if _holder(pd, legacy_rel, run_name)[0] == "mine" else None)
    if mine:
        plan.update(dst=mine, state="update", empty=not planned)
    elif not planned:
        plan.update(state="empty", why="no files")
        return plan
    elif base == "link":
        plan.update(why=_taken(base_rel, base, other), blocker=_shown(other, 4096))
        return plan
    elif base == "free":
        plan.update(dst=base_rel, state="new")
    elif own != "free" or not RUN_NAME_RE.match(run_name):
        plan.update(why="%s; %s" % (_taken(base_rel, base, other), _taken(own_rel, own, own_other) if own != "free"
                                    else "the run name is not a safe folder name"),
                    blocker=(_shown(own_other, 4096) if own == "link" else own_rel) if own != "free" else None)
        return plan
    else:
        plan.update(dst=own_rel, state="other-run" if base == "run" else "foreign", other_run=other,
                    why=_taken(base_rel, base, other))
    if plan["state"] == "update":
        dst = os.path.join(pd, *plan["dst"].split("/"))
        marker = _marker(dst)

        def on_disk(rel):
            return os.path.isfile(os.path.join(dst, *rel.split("/")))
        if marker["schema"] is None and plan["dst"] != legacy_rel:
            # written by kit 2.0.2 or earlier: its list may include another run's files (the cross-run bug), so the
            # files the package does not have stay, and the ones it replaces are flagged
            plan["kept"] = sorted(f for f in set(marker["files"]) - planned if on_disk(f))
            suspect = set(marker["files"]) if plan["kept"] else set()
        else:
            plan["stale"] = sorted(f for f in set(marker["files"]) - planned if on_disk(f))
            plan["kept"] = sorted(f for f in set(marker["legacy_files"]) - planned if on_disk(f))
            suspect = set(marker["legacy_files"])
        plan["clash"] = sorted(f for f in suspect & planned if on_disk(f) and not filecmp.cmp(
            os.path.join(dst, *f.split("/")), sources[f], shallow=False))
    return plan


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
        if plan["stale"]:
            n = len(plan["stale"])
            line += ". %s this run published there before and no longer has %s to the backup" % (
                _count(n, "file", "files"), "moves" if n == 1 else "move")
        if plan["kept"]:
            n = len(plan["kept"])
            line += (". WARNING: it also holds %s that this run's package does not have, published by kit 2.0.2 or "
                     "earlier and possibly from another run; %s in place" % (
                         _count(n, "file", "files"), "it stays" if n == 1 else "they stay"))
        if plan["clash"]:
            line += (". WARNING: it replaces %s that kit 2.0.2 or earlier published there, possibly another run's "
                     "(backed up first)" % _count(len(plan["clash"]), "file", "files"))
        return line + ("." if plan["stale"] or plan["kept"] or plan["clash"] else "")
    if plan["state"] == "other-run":
        return head + "%s. WARNING: %s already holds another run's package (%s); nothing there is changed." % (
            plan["dst"], plan["base"], _shown(plan["other_run"]))
    if plan["state"] == "foreign":
        return head + "%s. %s already holds files the kit did not publish; nothing there is changed." % (
            plan["dst"], plan["base"])
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


def _copy_replace(src, dst):
    """Copy src over dst through a temp file and a rename, so a hard link at dst is replaced, never written through."""
    tmp = None
    try:
        fd, tmp = tempfile.mkstemp(prefix=_TMP_PREFIX, suffix=".tmp", dir=os.path.dirname(dst))
        os.close(fd)
        shutil.copy2(src, tmp)
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


def publish(ctx, items):
    """Copy each approved item into <project>/docs/... file by file, at the place plan_target() names. Nothing is
    ever deleted, and only this run's own files are ever touched: a file that would be overwritten, or a file of this
    run's earlier copy that its package no longer has, goes to _superseded/<stamp>/published/<item>/ first. The marker
    is written before the first change, so an interrupted publish resumes in the same folder.
    Returns {"published": [...], "not_published": [...]} (one short line each, for 12_HANDOFF.md)."""
    pd = ctx.state.get("project_dir")
    out = {"published": [], "not_published": []}
    if not pd:
        return out
    stamp = _backup_stamp(ctx)
    run_name = _run_name(ctx)
    prog = _progress(ctx)
    for item in [i for i in PUBLISH if i in items]:
        plan = plan_target(ctx, item)
        src_rel, dst_rel = plan["src"], plan["dst"]
        if not dst_rel:
            out["not_published"].append("%s (%s)" % (src_rel, plan["why"]))
            continue
        dst = os.path.join(pd, *dst_rel.split("/"))
        files = _source_files(ctx.path(src_rel))
        planned = set(rel for rel, _f in files)
        entry = prog["items"].get(item)
        entry = entry if isinstance(entry, dict) and entry.get("dst") == dst_rel else {}
        entry = {"dst": dst_rel, "moved": _rels(entry.get("moved")), "clash": sorted(
            set(_rels(entry.get("clash"))) | set(plan["clash"]))}
        prog["items"][item] = entry
        textio.write_json_atomic(ctx.path(PUBLISH_PROGRESS), prog)
        os.makedirs(dst, exist_ok=True)
        # until a clashing file is replaced it stays a leftover, so a re-asked card still warns about it
        _write_marker(dst, run_name, (planned - set(plan["clash"])) | set(plan["stale"]),
                      set(plan["kept"]) | set(plan["clash"]))

        def backup(rel):
            path = ctx.path("_superseded", stamp, "published", item, *rel.split("/"))
            os.makedirs(os.path.dirname(path), exist_ok=True)
            return path
        for rel in plan["stale"]:
            path = os.path.join(dst, *rel.split("/"))
            if os.path.isfile(path) and not os.path.islink(path):
                shutil.move(path, backup(rel))
                entry["moved"] = sorted(set(entry["moved"]) | {rel})
                textio.write_json_atomic(ctx.path(PUBLISH_PROGRESS), prog)
        for rel, full in files:
            target = os.path.join(dst, *rel.split("/"))
            if os.path.isdir(target):
                continue
            if os.path.isfile(target):
                if filecmp.cmp(target, full, shallow=False):
                    continue
                shutil.copy2(target, backup(rel))
            os.makedirs(os.path.dirname(target), exist_ok=True)
            _copy_replace(full, target)
        _write_marker(dst, run_name, planned, plan["kept"])
        _tidy(dst, entry["moved"])
        textio.write_json_atomic(ctx.path(PUBLISH_PROGRESS), prog)
        notes = [plan["why"]] if plan["why"] else []
        if plan["empty"]:
            notes.append("the package has no files; nothing copied")
        if entry["moved"]:
            notes.append("%s moved to _superseded" % _count(len(entry["moved"]), "old file", "old files"))
        if entry["clash"]:
            notes.append("%s from kit 2.0.2 or earlier replaced, backed up" % _count(len(entry["clash"]), "file",
                                                                                        "files"))
        if plan["kept"]:
            notes.append("%s from kit 2.0.2 or earlier left in place" % _count(len(plan["kept"]), "file", "files"))
        out["published"].append("%s -> %s%s" % (src_rel, dst_rel, (" (%s)" % "; ".join(notes)) if notes else ""))
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
