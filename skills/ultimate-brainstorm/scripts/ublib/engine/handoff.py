"""Stage 14 Handoff (KIT_SPEC 9): publish copies (each needs its own yes), handoff seeds, 12_HANDOFF.md.

Scripts: handoff_seed (14.3), handoff_final (14.4).
"""

import os
import re
import shutil

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
        return [p for p in pub if p in PUBLISH]
    return []


PUBLISHED_MARKER = ".ub-published"


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
            if f.endswith((".meta.json", ".failed.md")):
                continue
            full = os.path.join(dirpath, f)
            out.append((os.path.relpath(full, src).replace("\\", "/"), full))
    return out


def _published_list(dst):
    try:
        data = textio.read_json(os.path.join(dst, PUBLISHED_MARKER))
    except (OSError, ValueError):
        return []
    files = data.get("files") if isinstance(data, dict) else None
    return [f for f in files if isinstance(f, str)] if isinstance(files, list) else []


def _existing_files(dst):
    out = []
    for dirpath, _dirs, files in os.walk(dst):
        for f in files:
            if f == PUBLISHED_MARKER:
                continue
            out.append(os.path.relpath(os.path.join(dirpath, f), dst).replace("\\", "/"))
    return out


def publish(ctx, items):
    """Copy each approved item into <project>/docs/... file by file. Nothing is ever deleted: a file that would be
    overwritten is backed up to _superseded/<stamp>/published/ first. When the target folder already holds files the
    kit did not publish (the project's own ADRs, say), the item goes to docs/<item>/ub-<run>/ instead."""
    pd = ctx.state.get("project_dir")
    done = []
    if not pd:
        return done
    stamp = st.iso_stamp()
    run_name = ctx.state.get("run") or os.path.basename(os.path.abspath(ctx.run_dir))
    for item in items:
        src_rel, dst_rel = PUBLISH[item]
        src = ctx.path(src_rel)
        if not os.path.isdir(src):
            continue
        dst = os.path.join(pd, *dst_rel.split("/"))
        if os.path.lexists(dst) and _is_link(dst):
            done.append("%s -> %s refused: the target is a link or junction" % (src_rel, dst_rel))
            continue
        if os.path.isdir(dst):
            owned = set(_published_list(dst))
            if any(f not in owned for f in _existing_files(dst)):
                dst_rel = "%s/ub-%s" % (dst_rel, run_name)
                dst = os.path.join(pd, *dst_rel.split("/"))
                if os.path.lexists(dst) and _is_link(dst):
                    done.append("%s -> %s refused: the target is a link or junction" % (src_rel, dst_rel))
                    continue
        files = _source_files(src)
        for rel, full in files:
            target = os.path.join(dst, *rel.split("/"))
            if os.path.isdir(target):
                continue
            if os.path.exists(target):
                backup = ctx.path("_superseded", stamp, "published", *(dst_rel.split("/") + rel.split("/")))
                os.makedirs(os.path.dirname(backup), exist_ok=True)
                shutil.copy2(target, backup)
            os.makedirs(os.path.dirname(target), exist_ok=True)
            shutil.copy2(full, target)
        owned = sorted(set(_published_list(dst)) | set(rel for rel, _f in files))
        textio.write_json_atomic(os.path.join(dst, PUBLISHED_MARKER), {"run": run_name, "files": owned})
        done.append("%s -> %s" % (src_rel, dst_rel))
    return done


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
    published = publish(ctx, items) if items else []
    ctx.state["published"] = published
    kind = chosen_handoff(ctx)
    if kind in SEEDS:
        ctx.write("handoff/%s-seed.md" % kind, seed_text(ctx, kind))
    ctx.state["handoff"] = kind
    return "handoff seed: %s; published: %s" % (kind, ", ".join(published) or "nothing")


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
               "PUBLISHED": ", ".join(s.get("published") or []) or "none", "DOMAIN_DOCS": domain}

    def builtin():
        lines = ["# Handoff: %(RUN_NAME)s" % mapping, "- Decision: %(CHOSEN)s (08_DECISION.md)" % mapping,
                 "- Architecture: %(ARCH_CHOICE)s (10_ARCHITECTURE/README.md)" % mapping,
                 "- Proposal: 11_PROPOSAL/PROPOSAL.md (%(STATUS_BANNER)s)" % mapping,
                 "- Milestone 0: %(PROBE_STATUS)s" % mapping, "- Handed to: %(COMPONENT_NAME)s" % mapping,
                 "- Seed: %(SEED_PATH)s" % mapping, "- Published: %(PUBLISHED)s" % mapping,
                 "- Domain docs: %(DOMAIN_DOCS)s" % mapping, CLOSING]
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
