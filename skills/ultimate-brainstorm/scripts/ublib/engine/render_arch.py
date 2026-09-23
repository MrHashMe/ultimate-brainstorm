"""Stage 12 Architecture (KIT_SPEC 7): deterministic documents rendered from JSON registers.

Scripts (registered in registry.SCRIPTS): arch_brief (12.1), drivers_after (after 12.2), candidates_after (12.5),
judges_after (after 12.6), arch_matrix (12.7), stack_lite (quick), arch_render_lint (12.12), arch_fix_after (after
12.14), arch_readme (12.15), approach_after (approach build type), decisions_after.
"""

import glob
import json
import os
import re

from .. import textio
from . import EngineError, FAMILY_ORDER, VENDORS
from . import privacy as privacy_mod
from . import registry
from . import seats as seats_mod

ARCH = "10_ARCHITECTURE"
QG_RE = re.compile(r"^QG\d+$")
FAMILY_WORDS = re.compile(r"\b(%s)\b" % "|".join(list(FAMILY_ORDER) + list(VENDORS.values()) +
                                                   ["codex", "claude code", "kimi code", "zhipu", "z\\.ai", "gemini"]),
                          re.I)


def _a(rel):
    return "%s/%s" % (ARCH, rel)


def md_cell(v):
    if isinstance(v, (list, tuple)):
        v = "; ".join(str(x) for x in v)
    return " ".join(str("" if v is None else v).replace("|", "/").split())


def mm_text(v, n=8):
    """Text safe inside a mermaid label: no quotes, brackets, braces, parentheses or pipes."""
    s = re.sub(r"[\"\[\]{}()|<>`#;]", " ", str(v or ""))
    s = " ".join(s.split())
    ws = s.split()
    return " ".join(ws[:n]) if ws else "item"


def mm_id(v):
    return re.sub(r"[^A-Za-z0-9_]", "_", str(v or "x"))


def table(headers, rows):
    out = ["| %s |" % " | ".join(headers), "|%s|" % "|".join(["---"] * len(headers))]
    for r in rows:
        out.append("| %s |" % " | ".join(md_cell(c) for c in r))
    return "\n".join(out)


def slug(text, n=6):
    words = re.findall(r"[a-z0-9]+", str(text or "").lower())
    return "-".join(words[:n]) or "decision"


# ================================================================ 12.1 brief

def arch_brief(ctx, step):
    fr = registry.frame_text(ctx)
    ch = ctx.state.get("choice") or {}
    iid = ch.get("idea")
    dec = ctx.read("08_DECISION.md") or ctx.read("QUICK_DECISION.md")
    probe = ctx.read("09_PROBE.md")
    red = ctx.read("07_REDTEAM.md")
    check = ctx.read("checks/%s.md" % iid) if iid else ""
    kill = re.findall(r"(Fails if[^\n]*)", check + "\n" + red)[:6]
    not_doing = [m.group(1).strip() for m in re.finditer(r"^Not doing[^:]*:\s*(.*)$", dec, re.M)]
    riskiest = registry.section(probe, "Riskiest assumption") or registry.first_line(
        registry.section(probe, "2") or "") or "see 09_PROBE.md"
    priv = ctx.state.get("privacy") or {}
    facts = ""
    if ctx.variant in ("software", "growth"):
        facts = registry.context_section(ctx, "A")
        if not priv.get("code"):
            facts = privacy_mod.strip_code(facts)
    parts = ["# Architecture brief (frozen before any candidate exists)", "",
             "## Job", registry.section(fr, "Job statement") or ctx.state.get("topic", ""), "",
             "## Audience", registry.section(fr, "Audience") or "(not stated)", "",
             "## Success", registry.section(fr, "Success looks like") or "NOT VERIFIED", "",
             "## Hard constraints", registry.section(fr, "Hard constraints") or "(none stated)", "",
             "## Soft constraints", registry.section(fr, "Soft constraints") or "(none stated)", "",
             "## Non-goals", registry.section(fr, "Non-goals") or "(none stated)", "",
             "## Chosen idea", "%s\n%s" % (iid or "?", registry.card_text(ctx, iid) if iid else ""), "",
             "## Scope and Not doing", "\n".join("- %s" % x for x in not_doing) or "(see 08_DECISION.md)", "",
             "## Kill-assumptions (checks and red-team)", "\n".join("- %s" % k for k in kill) or "(none recorded)",
             "", "## Riskiest assumption (probe)", riskiest, "",
             "## Privacy", "web: %s; other vendors: %s; code facts to other vendors: %s" % (
                 "yes" if priv.get("web") else "no", "yes" if priv.get("vendors") else "no",
                 "yes" if priv.get("code") else "no")]
    if facts:
        parts += ["", "## Repository facts", facts]
    ctx.write(_a("00_BRIEF.md"), "\n".join(parts).rstrip() + "\n")
    ctx.write_json(_a("brief.json"), {
        "job": registry.section(fr, "Job statement"), "audience": registry.section(fr, "Audience"),
        "success": registry.section(fr, "Success looks like"),
        "hard_constraints": registry.section(fr, "Hard constraints"),
        "soft_constraints": registry.section(fr, "Soft constraints"), "non_goals": registry.section(fr, "Non-goals"),
        "chosen": {"id": iid, "card": registry.card_text(ctx, iid) if iid else ""}, "not_doing": not_doing,
        "kill_assumptions": kill, "riskiest_assumption": riskiest,
        "privacy": {"web": bool(priv.get("web")), "vendors": bool(priv.get("vendors")), "code": bool(priv.get("code"))},
        "variant": ctx.variant, "build_type": ctx.state.get("build_type")})
    return "architecture brief frozen"


# ================================================================ 12.2 drivers

def _renumber(items, fmt, rx, key="id"):
    mapping = {}
    seen = set()
    for n, it in enumerate(items, 1):
        old = str(it.get(key) or "")
        new = old
        if not re.match(rx, old) or old in seen:
            new = fmt % n
            while new in seen:
                n += 100
                new = fmt % n
        seen.add(new)
        if old != new:
            mapping[old] = new
        it[key] = new
    return mapping


def normalize_drivers(d):
    """Check ID formats and counts, and scale quality-goal weights to 70. Returns (drivers, warnings)."""
    warnings = []
    d = dict(d or {})
    qg = [dict(q) for q in d.get("quality_goals") or [] if isinstance(q, dict)]
    m = _renumber(qg, "QG%d", r"^QG\d+$")
    if m:
        warnings.append("quality goal ids renumbered: %s" % ", ".join("%s->%s" % kv for kv in m.items()))
    if not 3 <= len(qg) <= 5:
        warnings.append("expected 3-5 quality goals, got %d" % len(qg))
    total = 0.0
    for q in qg:
        try:
            q["weight"] = float(q.get("weight") or 0)
        except (TypeError, ValueError):
            q["weight"] = 0.0
        total += q["weight"]
    if qg and abs(total - 70.0) > 0.01:
        if total <= 0:
            for q in qg:
                q["weight"] = round(70.0 / len(qg), 1)
        else:
            for q in qg:
                q["weight"] = round(q["weight"] * 70.0 / total, 1)
        diff = round(70.0 - sum(q["weight"] for q in qg), 1)
        if qg and diff:
            big = max(qg, key=lambda q: q["weight"])
            big["weight"] = round(big["weight"] + diff, 1)
        warnings.append("quality-goal weights summed to %g: normalized to 70" % total)
    for q in qg:
        if float(q["weight"]).is_integer():
            q["weight"] = int(q["weight"])
    d["quality_goals"] = qg
    hc = [dict(h) for h in d.get("hard_constraints") or [] if isinstance(h, dict)]
    if _renumber(hc, "HC-%d", r"^HC-\d+$"):
        warnings.append("hard constraint ids renumbered")
    d["hard_constraints"] = hc
    qas = [dict(q) for q in d.get("qas") or [] if isinstance(q, dict)]
    if _renumber(qas, "QAS-%02d", r"^QAS-\d{2,}$"):
        warnings.append("QAS ids renumbered")
    for q in qas:
        if q.get("qg") in m:
            q["qg"] = m[q["qg"]]
    if not 5 <= len(qas) <= 10:
        warnings.append("expected 5-10 quality scenarios, got %d" % len(qas))
    d["qas"] = qas
    ctxd = dict(d.get("context") or {})
    acts = [dict(a) for a in ctxd.get("actors") or [] if isinstance(a, dict)]
    _renumber(acts, "ACT-%d", r"^ACT-\d+$")
    ext = [dict(e) for e in ctxd.get("external") or [] if isinstance(e, dict)]
    _renumber(ext, "EXT-%d", r"^EXT-\d+$")
    ctxd["actors"], ctxd["external"] = acts, ext
    ctxd.setdefault("system", {"name": "The system", "description": ""})
    d["context"] = ctxd
    pa = [dict(p) for p in d.get("planning_assumptions") or [] if isinstance(p, dict)]
    _renumber(pa, "AS-%d", r"^AS-\d+$")
    d["planning_assumptions"] = pa
    for k in ("soft_constraints", "not_in_scope", "open_questions"):
        d.setdefault(k, [])
    d.setdefault("product_goal", "")
    return d, warnings


def render_goals(d):
    """goals-constraints.md (templates/docs/GOALS-CONSTRAINTS.md)."""
    from . import builders
    qg_table = table(["id", "goal", "weight", "why", "source"],
                     [[q.get("id"), q.get("name"), q.get("weight"), q.get("why"), q.get("source")]
                      for q in d.get("quality_goals") or []])
    qg_table += ("\n\nWeights sum to 70; a fixed 30 goes to time_to_mvp 10, team_fit 5, run_cost 5, reversibility 5 "
                 "and operational_simplicity 5.")
    mapping = {
        "PRODUCT_GOAL": d.get("product_goal") or "(not stated)",
        "QUALITY_GOALS_TABLE": qg_table,
        "HC_TABLE": table(["id", "constraint", "source"], [[h.get("id"), h.get("text"), h.get("source")]
                                                         for h in d.get("hard_constraints") or []]),
        "SOFT_CONSTRAINTS_LIST": "\n".join("- %s" % md_cell(s) for s in d.get("soft_constraints") or [])
        or "- none stated",
        "NOT_IN_SCOPE_LIST": "\n".join("- %s" % md_cell(s) for s in d.get("not_in_scope") or []) or "- none stated",
        "PLANNING_ASSUMPTIONS_TABLE": table(["id", "item", "value", "source"],
                                            [[p.get("id"), p.get("item"), p.get("value"), p.get("source")]
                                             for p in d.get("planning_assumptions") or []]),
        "OPEN_QUESTIONS_LIST": "\n".join("- %s (default: %s)" % (md_cell(q.get("q")), md_cell(q.get("default")) or
                                                                 "none")
                                         for q in d.get("open_questions") or [] if isinstance(q, dict))
        or "- none"}

    def builtin():
        return ("# Goals and constraints\n\n## Product goal\n\n%(PRODUCT_GOAL)s\n\n## Quality goals\n\n"
                "%(QUALITY_GOALS_TABLE)s\n\n## Hard constraints\n\n%(HC_TABLE)s\n\n## Soft constraints\n\n"
                "%(SOFT_CONSTRAINTS_LIST)s\n\n## Not in scope\n\n%(NOT_IN_SCOPE_LIST)s\n\n## Planning assumptions\n\n"
                "%(PLANNING_ASSUMPTIONS_TABLE)s\n\n## Open questions\n\n%(OPEN_QUESTIONS_LIST)s\n" % mapping)
    return builders.render_doc("GOALS-CONSTRAINTS", mapping, fallback=builtin)


def render_scenarios(d):
    """quality-scenarios.md (templates/docs/QUALITY-SCENARIOS.md)."""
    from . import builders
    mapping = {"UTILITY_TREE": utility_tree(d), "QAS_TABLE": qas_table(d)}
    return builders.render_doc("QUALITY-SCENARIOS", mapping, fallback=lambda: (
        "# Quality scenarios\n\n## Utility tree\n\n%(UTILITY_TREE)s\n\n## Scenarios\n\n%(QAS_TABLE)s\n" % mapping))


def render_context(d):
    """context.md (templates/docs/CONTEXT-VIEW.md): C4Context plus a flowchart fallback with the same elements."""
    from . import builders
    c = d.get("context") or {}
    sysd = c.get("system") or {}
    c4, fc = context_diagrams(d)
    mapping = {"SYSTEM_CONTEXT": "%s: %s" % (md_cell(sysd.get("name") or "The system"),
                                             md_cell(sysd.get("description") or "")),
               "C4_CONTEXT": c4, "CONTEXT_FLOWCHART": fc,
               "ACTORS_TABLE": table(["id", "actor", "description"], [[a.get("id"), a.get("name"),
                                                                       a.get("description")]
                                                                      for a in c.get("actors") or []]),
               "EXTERNAL_TABLE": table(["id", "external system", "description", "relationship"],
                                       [[e.get("id"), e.get("name"), e.get("description"), e.get("relationship")]
                                        for e in c.get("external") or []])}

    def builtin():
        return ("# Context\n\n## System context\n%(SYSTEM_CONTEXT)s\n\n```mermaid\n%(C4_CONTEXT)s\n```\n\n"
                "```mermaid\n%(CONTEXT_FLOWCHART)s\n```\n\n## Actors\n%(ACTORS_TABLE)s\n\n## External systems\n"
                "%(EXTERNAL_TABLE)s\n" % mapping)
    return builders.render_doc("CONTEXT-VIEW", mapping, fallback=builtin)


def drivers_after(ctx, step):
    raw = ctx.read_json(_a("drivers.json"), None)
    if not isinstance(raw, dict):
        raise EngineError("10_ARCHITECTURE/drivers.json is missing or not JSON")
    d, warnings = normalize_drivers(raw)
    ctx.write_json(_a("drivers.json"), d)
    ctx.write(_a("goals-constraints.md"), render_goals(d))
    ctx.write(_a("quality-scenarios.md"), render_scenarios(d))
    ctx.write(_a("context.md"), render_context(d))
    from . import state as st
    for w in warnings:
        st.add_note(ctx.state, "drivers: " + w)
    return "; ".join(warnings) or "drivers rendered"


# ================================================================ 12.5 labels, map, sheets

def _trunc(v, n=60):
    return registry.words(FAMILY_WORDS.sub("[model]", " ".join(str(v or "").split())), n)


def render_sheet(label, c):
    """Neutral judge sheet (templates/docs/ARCH-SHEET.md): fixed field order, every string cut to 60 words, no
    archetype or family names."""
    from . import builders
    data = c.get("data") or {}
    cost = c.get("cost_monthly_usd") or {}
    bw = c.get("build_person_weeks") or {}
    containers = table(["id", "name", "technology", "responsibility", "data owned", "interface"],
                       [[x.get("id"), _trunc(x.get("name"), 12), _trunc(x.get("tech"), 12),
                         _trunc(x.get("responsibility")), _trunc(x.get("data_owned"), 20),
                         _trunc(x.get("interface"), 20)] for x in c.get("containers") or [] if isinstance(x, dict)])
    ext = ", ".join("%s %s" % (e.get("id"), _trunc(e.get("name"), 8)) for e in c.get("external") or []
                    if isinstance(e, dict))
    if ext:
        containers += "\n\nExternal systems: %s." % ext
    mapping = {
        "SHEET_LABEL": label, "SHEET_SUMMARY": _trunc(c.get("summary")) or "(none)",
        "SHEET_PARADIGM": _trunc(c.get("paradigm")) or "(none)", "SHEET_CONTAINERS": containers,
        "SHEET_QAS": table(["QAS", "mechanism", "residual risk"],
                           [[m.get("qas"), _trunc(m.get("mechanism")), _trunc(m.get("residual_risk"))]
                            for m in c.get("qas_mechanisms") or [] if isinstance(m, dict)]),
        "SHEET_STACK": table(["layer", "component", "choice", "version"],
                             [[s.get("layer"), _trunc(s.get("component"), 10), _trunc(s.get("choice"), 10),
                               _trunc(s.get("version"), 5)] for s in c.get("stack") or [] if isinstance(s, dict)]),
        "SHEET_DATA": "Entities: %s. Storage: %s." % (", ".join(_trunc(e, 6) for e in data.get("entities") or [])
                                                      or "none", _trunc(data.get("storage"))),
        "SHEET_DEPLOYMENT": _trunc(c.get("deployment")) or "(none)",
        "SHEET_SECURITY": "\n".join("- %s -> %s" % (_trunc(t.get("threat"), 25), _trunc(t.get("mitigation"), 25))
                                    for t in c.get("security_threats") or [] if isinstance(t, dict))
        or "- none listed",
        "SHEET_COST": "Monthly run cost (USD): MVP %s-%s; 10x %s-%s.\nBuild effort: %s-%s person-weeks." % (
            cost.get("mvp_low"), cost.get("mvp_high"), cost.get("x10_low"), cost.get("x10_high"), bw.get("low"),
            bw.get("high")),
        "SHEET_TRADEOFFS": "\n".join("- %s" % _trunc(t) for t in c.get("tradeoffs") or []) or "- none listed",
        "SHEET_RISKS": "\n".join("- %s" % _trunc(r) for r in c.get("risks") or []) or "- none listed",
        "SHEET_REJECTED": "\n".join("- %s: %s" % (_trunc(r.get("approach"), 15), _trunc(r.get("why")))
                                    for r in c.get("rejected") or [] if isinstance(r, dict)) or "- none listed",
        "SHEET_TOKENS": "\n".join("- %s" % _trunc(t, 20) for t in c.get("innovation_tokens") or []) or "- none"}

    def builtin():
        order = [("Summary", "SHEET_SUMMARY"), ("Paradigm", "SHEET_PARADIGM"), ("Containers", "SHEET_CONTAINERS"),
                 ("Quality mechanisms", "SHEET_QAS"), ("Stack", "SHEET_STACK"), ("Data", "SHEET_DATA"),
                 ("Deployment", "SHEET_DEPLOYMENT"), ("Security threats", "SHEET_SECURITY"),
                 ("Cost and effort", "SHEET_COST"), ("Trade-offs", "SHEET_TRADEOFFS"), ("Risks", "SHEET_RISKS"),
                 ("Rejected approaches", "SHEET_REJECTED"), ("Innovation tokens", "SHEET_TOKENS")]
        return "# Candidate %s\n\n" % label + "\n\n".join("## %s\n%s" % (h, mapping[k]) for h, k in order) + "\n"
    return builders.render_doc("ARCH-SHEET", mapping, fallback=builtin)


def _json_tail(text):
    blocks = [b for lang, b in textio.fenced_blocks(text) if lang == "json"]
    for b in reversed(blocks):
        try:
            v = json.loads(b.strip())
            if isinstance(v, dict):
                return v
        except ValueError:
            continue
    return None


def candidates_after(ctx, step):
    from . import state as st
    job_ids = ((ctx.state.get("steps") or {}).get("12.4") or {}).get("jobs") or []
    valid = []
    for jid in job_ids:
        job = ctx.read_json("jobs/%s.json" % jid, {}) or {}
        out = job.get("out") or ""
        meta = ctx.read_json(out + ".meta.json", {}) or {}
        if meta.get("status") != "ok" or meta.get("id") != jid:
            continue
        tail = _json_tail(ctx.read(out))
        if tail is None:
            continue
        n = os.path.splitext(os.path.basename(out))[0]
        if any(v["n"] == n for v in valid):
            continue
        ctx.write_json(_a("candidates/%s.json" % n), tail)
        valid.append({"n": n, "family": meta.get("family") or job.get("family"), "job": jid,
                      "archetype": (job.get("engine") or {}).get("archetype") or
                      (ctx.seats.get("arch_archetypes") or {}).get(n), "json": tail})
    if len(valid) < 2 and ctx.mode != "quick":
        raise EngineError("fewer than 2 valid architecture candidates", fix=[
            '%s redo "%s" 12.4 --yes' % (ctx.state.get("runner") or "ub", textio.to_posix(ctx.run_dir))])
    if not valid:
        raise EngineError("no valid architecture candidate")
    letters = ["A", "B", "C", "D", "E", "F"][:len(valid)]
    shuffled = letters[:]
    seats_mod.rng(ctx.state.get("run", ""), "arch-labels").shuffle(shuffled)
    mapping = {}
    for v, label in zip(valid, shuffled):
        mapping[label] = {"family": v["family"], "archetype": v["archetype"], "job": v["job"], "n": v["n"]}
        ctx.write(_a("review/sheet_%s.md" % label), render_sheet(label, v["json"]))
    ctx.write_json(_a("candidates/map.json"), dict(sorted(mapping.items())))
    if ctx.seats.get("arch_same_family"):
        st.add_note(ctx.state, "architecture: same-family bake-off (fewer families than candidates)")
    return "%d candidates labeled" % len(mapping)


def judges_after(ctx, step):
    crit = set(registry.arch_criteria(ctx))
    miss = []
    for p in glob.glob(ctx.path(ARCH, "review", "judge_*.out.json")):
        try:
            data = textio.read_json(p)
        except (OSError, ValueError):
            continue
        changed = False
        for c in (data or {}).get("candidates") or []:
            if not isinstance(c, dict):
                continue
            got = set(s.get("criterion") for s in c.get("scores") or [] if isinstance(s, dict))
            if crit - got:
                miss.append("%s/%s" % (os.path.basename(p), c.get("label")))
            for s in c.get("scores") or []:
                if not isinstance(s, dict):
                    continue
                try:
                    v = int(s.get("score"))
                except (TypeError, ValueError):
                    v = 0
                if not 1 <= v <= 5:
                    s["score"] = max(1, min(5, v or 3))  # 7.4: score ranges are checked in Python
                    changed = True
        if changed:
            textio.write_json_atomic(p, data)
    if miss:
        from . import state as st
        st.add_note(ctx.state, "arch judges missed criteria for %s" % ", ".join(miss[:4]))
    return "judges checked"


def arch_matrix(ctx, step):
    registry.bs(ctx, "arch-matrix", ctx.run_dir)
    return "trade-off matrix computed"


def stack_lite(ctx, step):
    cand = registry.chosen_candidate_json(ctx)
    rows = []
    for s in cand.get("stack") or []:
        if isinstance(s, dict):
            rows.append({"layer": s.get("layer"), "component": s.get("component"), "choice": s.get("choice"),
                         "version": "UNVERIFIED", "release_date": "", "source_url": "", "status": "UNVERIFIED",
                         "license": "", "eol_note": "", "alternatives": "", "innovation_token": False})
    ctx.write_json(_a("stack.json"), {"rows": rows})
    return "stack.json from the candidate (every row UNVERIFIED)"


# ================================================================ 12.12 ADRs, risks, stack

def decisions(ctx):
    d = ctx.read_json(_a("decisions.json"), {}) or {}
    return d if isinstance(d, dict) else {}


def risk_rows(dec):
    seen, out = set(), []
    for n, r in enumerate(dec.get("risks") or [], 1):
        if not isinstance(r, dict):
            continue
        rid = str(r.get("id") or "")
        if not re.match(r"^R-\d{3}$", rid) or rid in seen:
            k = n
            rid = "R-%03d" % k
            while rid in seen:
                k += 100
                rid = "R-%03d" % k
        seen.add(rid)
        out.append(dict(r, id=rid))
    return out


def render_risks(dec):
    """risks.md (templates/docs/RISKS.md): risks and technical debt kept separate."""
    from . import builders
    risks = risk_rows(dec)
    debt = [t for t in dec.get("debt") or [] if isinstance(t, dict)]
    mapping = {"RISKS_TABLE": table(["id", "risk", "likelihood", "impact", "mitigation", "owner", "early warning",
                                     "source"],
                                    [[r.get("id"), r.get("text"), r.get("likelihood"), r.get("impact"),
                                      r.get("mitigation"), r.get("owner"), r.get("early_warning"), r.get("source")]
                                     for r in risks]),
               "DEBT_TABLE": table(["id", "debt", "why accepted", "payoff trigger"],
                                   [[t.get("id"), t.get("text"), t.get("why"), t.get("payoff_trigger")] for t in debt])}
    return builders.render_doc("RISKS", mapping, fallback=lambda: (
        "# Risks and technical debt\n\n## Risks\n\n%(RISKS_TABLE)s\n\n## Technical debt\n\n%(DEBT_TABLE)s\n"
        % mapping))


def render_adr(n, a, date, status, risk_ids, qg_names):
    """adr/NNNN-slug.md in MADR 4.0 minimal form (templates/docs/ADR-MADR.md)."""
    from . import builders
    opts = [o for o in a.get("options") or [] if isinstance(o, dict)]
    names = [md_cell(o.get("name")) for o in opts if md_cell(o.get("name"))] or [
        md_cell(a.get("chosen") or "Chosen option")]
    if len(names) < 2:
        names.append("Do nothing")
    cons = ["* Good, because %s" % md_cell(g) for g in a.get("good") or [] if md_cell(g)]
    for b in a.get("bad") or []:
        if isinstance(b, dict):
            cites = [r for r in b.get("risk_ids") or [] if r in risk_ids]
            cons.append("* Bad, because %s%s" % (md_cell(b.get("text")), (" (%s)" % ", ".join(cites)) if cites
                                                 else ""))
        elif md_cell(b):
            cons.append("* Bad, because %s" % md_cell(b))
    more = [str(a.get("more_info") or "").strip() or "Generated from decisions.json."]
    for o in opts:
        pros = "; ".join(md_cell(p) for p in o.get("pros") or [])
        conlist = "; ".join(md_cell(c) for c in o.get("cons") or [])
        more.append("* %s: pros %s; cons %s" % (md_cell(o.get("name")), pros or "-", conlist or "-"))
    just = str(a.get("justification") or "it best meets the decision drivers").strip().rstrip(".") + "."
    mapping = {"ADR_STATUS": status, "DATE": date, "DECISION_MAKERS": md_cell(a.get("decision_makers")) or
               "the proposal owner", "ADR_NUMBER": "%04d" % n, "ADR_TITLE": md_cell(a.get("title") or "Decision"),
               "ADR_CONTEXT": str(a.get("context") or "").strip() or "(context not given)",
               "ADR_DRIVERS": "\n".join("* %s %s" % (d, qg_names.get(d, "")) for d in a.get("drivers") or [])
               or "* none listed",
               "ADR_OPTIONS": "\n".join("* %s" % x for x in names),
               "ADR_CHOSEN": md_cell(a.get("chosen") or names[0]).replace('"', "'"), "ADR_JUSTIFICATION": just,
               "ADR_CONSEQUENCES": "\n".join(cons) or "* Good, because it follows the drivers",
               "ADR_CONFIRMATION": str(a.get("confirmation") or "Reviewed at Milestone 1.").strip(),
               "ADR_MORE_INFO": "\n".join(more)}

    def builtin():
        return ("---\nstatus: %(ADR_STATUS)s\ndate: %(DATE)s\ndecision-makers: %(DECISION_MAKERS)s\n---\n"
                "# ADR-%(ADR_NUMBER)s: %(ADR_TITLE)s\n\n## Context and Problem Statement\n%(ADR_CONTEXT)s\n\n"
                "## Decision Drivers\n%(ADR_DRIVERS)s\n\n## Considered Options\n%(ADR_OPTIONS)s\n\n"
                "## Decision Outcome\nChosen option: \"%(ADR_CHOSEN)s\", because %(ADR_JUSTIFICATION)s\n\n"
                "### Consequences\n%(ADR_CONSEQUENCES)s\n\n### Confirmation\n%(ADR_CONFIRMATION)s\n\n"
                "## More Information\n%(ADR_MORE_INFO)s\n" % mapping)
    return builders.render_doc("ADR-MADR", mapping, fallback=builtin)


def rerender_adrs(ctx):
    dec = decisions(ctx)
    if not dec:
        return []
    statuses = ctx.read_json(_a("adr_status.json"), {}) or {}
    drivers = registry.drivers(ctx)
    qg_names = dict((q.get("id"), md_cell(q.get("name"))) for q in drivers.get("quality_goals") or []
                    if isinstance(q, dict))
    risk_ids = set(r["id"] for r in risk_rows(dec))
    date = textio.now_iso()[:10]
    written = []
    old = glob.glob(ctx.path(ARCH, "adr", "*.md"))
    targets = []
    for n, a in enumerate([x for x in dec.get("adrs") or [] if isinstance(x, dict)], 1):
        num = "%04d" % n
        status = statuses.get(num, "proposed")
        rel = "adr/%s-%s.md" % (num, slug(a.get("title")))
        targets.append(rel)
        ctx.write(_a(rel), render_adr(n, a, date, status, risk_ids, qg_names))
        written.append(rel)
    for p in old:
        rel = "adr/" + os.path.basename(p)
        if rel not in targets:
            try:
                os.remove(p)
            except OSError:
                pass
    return written


def render_stack(rows):
    """chosen/stack.md (templates/docs/STACK.md) from stack.json rows."""
    from . import builders
    counts = {}
    for r in rows:
        stt = str(r.get("status") or "UNVERIFIED").upper()
        counts[stt] = counts.get(stt, 0) + 1
    note = "%d VERIFIED, %d UNVERIFIED, %d NOT SEARCHED (checked %s)" % (
        counts.get("VERIFIED", 0), counts.get("UNVERIFIED", 0), counts.get("NOT SEARCHED", 0), textio.now_iso()[:10])
    mapping = {"STACK_NOTE": note, "STACK_TABLE": table(
        ["layer", "component", "choice", "version", "release date", "source", "status", "license", "EOL note",
         "alternatives", "innovation token"],
        [[r.get("layer"), r.get("component"), r.get("choice"), _version(r.get("version")), r.get("release_date"),
          r.get("source_url"), r.get("status") or "UNVERIFIED", r.get("license"), r.get("eol_note"),
          r.get("alternatives"), "yes" if r.get("innovation_token") else "no"] for r in rows])}
    return builders.render_doc("STACK", mapping, fallback=lambda: "# Stack\n%(STACK_NOTE)s\n\n%(STACK_TABLE)s\n"
                               % mapping)


def _version(v):
    s = str(v or "").strip()
    if not s or s.lower() in ("latest", "n/a", "none", "-", "?"):
        return "UNVERIFIED"
    return s


def decisions_after(ctx, step):
    dec = decisions(ctx)
    if not dec:
        raise EngineError("10_ARCHITECTURE/decisions.json is missing or not JSON")
    return "%d ADRs, %d risks" % (len(dec.get("adrs") or []), len(dec.get("risks") or []))


def lint_arch(ctx):
    args = ["lint-arch", ctx.run_dir] + (["--lite"] if ctx.mode == "quick" else [])
    rc, out, err = registry.bs(ctx, *args, allow=(0, 1))
    data = ctx.read_json(_a("lint.json"), {}) or {}
    return rc, data


def arch_render_lint(ctx, step):
    rerender_adrs(ctx)
    ctx.write(_a("risks.md"), render_risks(decisions(ctx)))
    stack = ctx.read_json(_a("stack.json"), {}) or {}
    rows = [r for r in (stack.get("rows") or []) if isinstance(r, dict)]
    if not (ctx.state.get("privacy") or {}).get("web", True):
        for r in rows:
            r["status"] = "NOT SEARCHED"
    ctx.write(_a("chosen/stack.md"), render_stack(rows))
    write_readme(ctx)
    rc, data = lint_arch(ctx)
    return "lint-arch: %s" % (data.get("status") or ("fail" if rc else "pass"))


def arch_fix_after(ctx, step):
    msg = arch_render_lint(ctx, step)
    data = ctx.read_json(_a("lint.json"), {}) or {}
    unresolved = ["lint %s: %s" % (i.get("id"), i.get("message")) for i in data.get("items") or []
                  if isinstance(i, dict) and str(i.get("severity")).upper() == "FAIL"]
    res = ctx.read(_a("review/resolution.md"))
    for p in glob.glob(ctx.path(ARCH, "review", "L*_*.json")):
        if p.endswith(".meta.json"):
            continue
        try:
            fdata = textio.read_json(p)
        except (OSError, ValueError):
            continue
        for f in (fdata or {}).get("findings") or []:
            if isinstance(f, dict) and str(f.get("severity")).upper() == "P0":
                fid = str(f.get("id") or "")
                if not re.search(re.escape(fid) + r"[^\n]*FIXED", res):
                    unresolved.append("P0 finding %s: %s" % (fid, f.get("issue")))
    ctx.state["unresolved"] = unresolved[:12]
    return msg + ("; %d unresolved" % len(unresolved) if unresolved else "")


# ================================================================ 12.15 README

def write_readme(ctx):
    """10_ARCHITECTURE/README.md (templates/docs/ARCH-README.md): summary, the choice and why, alternatives,
    quality goals -> mechanisms, decision index, file map, provenance."""
    from . import builders
    from . import gates
    from . import render
    s = ctx.state
    ch = s.get("choice") or {}
    label = ch.get("arch")
    matrix = ctx.read_json(_a("matrix.json"), {}) or {}
    m = ctx.read_json(_a("candidates/map.json"), {}) or {}
    drivers = registry.drivers(ctx)
    cand = registry.chosen_candidate_json(ctx)
    iid = registry.chosen_idea(ctx)
    title = registry.idea_lines(ctx).get(iid or "", {}).get("title") or s.get("topic", "")
    mrow = next((c for c in matrix.get("candidates") or [] if isinstance(c, dict) and c.get("label") == label), {})
    g11 = ((s.get("gates") or {}).get("G11") or {})
    words = (g11.get("answer") or {}).get("reply") or (g11.get("answer") or {}).get("notes") or ""
    info = m.get(label) or {}
    why = ["Chosen: candidate %s, written by %s (revealed after the choice); archetype: %s." % (
        label or "?", info.get("family") or "?", registry.archetype_short(ctx, info.get("archetype") or "A")),
        "Matrix: weighted score %s, rank range %s, veto %s; leader %s (%s)." % (
            mrow.get("score"), registry.fmt_range(mrow.get("range")), mrow.get("veto"), matrix.get("leader"), matrix.get("leader_status")),
        "Decided %s%s." % ("by the human" if g11.get("by") == "human" else "by rule (AUTO-DECISION)",
                           (': "%s"' % " ".join(words.split())) if words and g11.get("by") == "human" else "")]
    alts = []
    for c in matrix.get("candidates") or []:
        if isinstance(c, dict) and c.get("label") != label:
            alts.append([c.get("label"), c.get("score"), registry.fmt_range(c.get("range")), c.get("veto"),
                         "; ".join(c.get("veto_reasons") or []) or ("lower weighted score" if c.get("rank") else
                                                                    "not chosen")])
    mech = {}
    for x in cand.get("qas_mechanisms") or []:
        if isinstance(x, dict):
            mech.setdefault(x.get("qas"), x.get("mechanism"))
    qas_by_qg = {}
    for q in drivers.get("qas") or []:
        if isinstance(q, dict):
            qas_by_qg.setdefault(q.get("qg"), []).append(q.get("id"))
    containers_md = ctx.read(_a("chosen/containers.md"))
    rows = []
    for q in drivers.get("quality_goals") or []:
        qs = qas_by_qg.get(q.get("id"), [])
        cids = sorted(set(re.findall(r"\bC-\d+\b", registry.section(containers_md, "How each quality goal is met"))))
        rows.append([q.get("id"), "; ".join(str(mech.get(x)) for x in qs if mech.get(x)) or
                     "see chosen/containers.md", ", ".join(cids) or "-", ", ".join(qs) or "-"])
    files = [["goals-constraints.md, quality-scenarios.md, context.md", "the drivers (rendered from drivers.json)"],
             ["candidates/, review/sheet_*.md, tradeoff-matrix.md, matrix.json", "the blind bake-off"],
             ["premortem.md", "how the leader fails"], ["chosen/", "the package for the chosen candidate"],
             ["adr/, risks.md, decisions.json", "decisions, risks and technical debt"],
             ["stack.json, chosen/stack.md", "the stack with verification status"],
             ["review/", "judge outputs, review lenses and the resolution log"], ["lint.md, lint.json", "lint-arch"]]
    prov = []
    for lab in sorted(m):
        inf = m[lab]
        prov.append("- candidate %s: author %s, archetype: %s%s" % (
            lab, inf.get("family"), registry.archetype_short(ctx, inf.get("archetype") or "A"),
            " (PROVISIONAL)" if "-alt" in str(inf.get("family")) else ""))
    prov.append("- judges: %s" % registry.judges_line(ctx, "arch_judges"))
    if ctx.seats.get("arch_same_family"):
        prov.append("- badge: same-family bake-off")
    lint = ctx.read_json(_a("lint.json"), {}) or {}
    prov.append("- lint-arch: %s" % (lint.get("status") or "not run yet"))
    lenses = [os.path.basename(p)[:-5] for p in sorted(glob.glob(ctx.path(ARCH, "review", "L*_*.json")))
              if not p.endswith(".meta.json")]
    prov.append("- review lenses: %s" % (", ".join(lenses) or "none"))
    for u in s.get("unresolved") or []:
        prov.append("- unresolved: %s" % u)
    mapping = {"ARCH_TITLE": title, "STATUS_BANNER": render.status_banner(ctx),
               "PROVISIONAL_BANNER": gates.provisional_banner(ctx),
               "ARCH_SUMMARY": registry.words(cand.get("summary") or "", 80) or "(see chosen/containers.md)",
               "CHOSEN_WHY": "\n".join(why),
               "ALTERNATIVES_TABLE": table(["candidate", "score", "rank range", "veto", "why not chosen"], alts)
               if alts else "none",
               "QG_MECHANISMS_TABLE": table(["QG", "mechanism", "containers", "QAS"], rows) if rows else "none",
               "ADR_INDEX": adr_index(ctx), "FILE_MAP": table(["file", "what"], files), "PROVENANCE": "\n".join(prov),
               "AT_A_GLANCE": at_a_glance(ctx, cand, containers_md)}

    def builtin():
        return ("# Architecture: %(ARCH_TITLE)s\n%(STATUS_BANNER)s\n\n## Summary\n%(ARCH_SUMMARY)s\n\n"
                "## At a glance\n%(AT_A_GLANCE)s\n\n"
                "## Chosen candidate and why\n%(CHOSEN_WHY)s\n\n### Alternatives considered\n%(ALTERNATIVES_TABLE)s\n\n"
                "## How each quality goal is met\n%(QG_MECHANISMS_TABLE)s\n\n## Decision index\n%(ADR_INDEX)s\n\n"
                "## Files\n%(FILE_MAP)s\n\n## Provenance\n%(PROVENANCE)s\n" % mapping)
    ctx.write(_a("README.md"), builders.render_doc("ARCH-README", mapping, fallback=builtin))


def _money(lo, hi):
    try:
        return "$%s-%s/month" % ("{:,}".format(int(lo)), "{:,}".format(int(hi)))
    except (TypeError, ValueError):
        return None


def at_a_glance(ctx, cand, containers_md):
    """The README's summary block: the container diagram, the stack, cost and build effort, the top risks - so a
    reader need not open five more files."""
    out = []
    diagram = None
    for lang, body in textio.fenced_blocks(containers_md or ""):
        if lang == "mermaid" and re.match(r"^\s*(flowchart|graph)\b", body):
            diagram = body.rstrip("\n")
            break
    if diagram:
        out.append("```mermaid\n%s\n```" % diagram)
    rows = (ctx.read_json(_a("stack.json"), {}) or {}).get("rows") or []
    rows = [r for r in rows if isinstance(r, dict)]
    if rows:
        out.append(table(["layer", "choice", "status"], [[r.get("layer"), r.get("choice") or r.get("component"),
                                                          r.get("status") or "UNVERIFIED"] for r in rows]))
    facts = []
    cost = cand.get("cost_monthly_usd") if isinstance(cand.get("cost_monthly_usd"), dict) else {}
    mvp = _money(cost.get("mvp_low"), cost.get("mvp_high"))
    x10 = _money(cost.get("x10_low"), cost.get("x10_high"))
    if mvp:
        facts.append("- Running cost: about %s at MVP%s (chosen/cost-model.md)" % (
            mvp, ("; about %s at 10x" % x10) if x10 else ""))
    pw = cand.get("build_person_weeks") if isinstance(cand.get("build_person_weeks"), dict) else {}
    if pw.get("low") is not None and pw.get("high") is not None:
        facts.append("- Build effort: %s-%s person-weeks" % (pw.get("low"), pw.get("high")))
    top = risk_rows(decisions(ctx))[:3]
    for r in top:
        facts.append("- Risk %s: %s (likelihood %s, impact %s)" % (r.get("id"), md_cell(r.get("text")),
                                                                   r.get("likelihood") or "?", r.get("impact") or "?"))
    if facts:
        out.append("\n".join(facts))
    return "\n\n".join(out) or "(see chosen/containers.md, stack.json, chosen/cost-model.md and risks.md)"


def arch_readme(ctx, step):
    write_readme(ctx)
    return "architecture README written"


def approach_after(ctx, step):
    text = ctx.read(_a("approach.md"))
    bad = []
    body = re.sub(r"(?s)```.*?```", "", text)
    for rx in (r"\bTODO\b", r"\bTBD\b", r"\bXXX\b", r"lorem", r"\{\{", r"<[a-z][a-z0-9 _-]{1,40}>"):
        if re.search(rx, body, re.I if rx == "lorem" else 0):
            bad.append(rx)
    ctx.write_json(_a("lint.json"), {"status": "fail" if bad else "pass",
                                     "items": [{"id": "A2", "severity": "FAIL", "file": "approach.md",
                                                "message": "placeholder %s" % b} for b in bad]})
    ctx.write(_a("lint.md"), "# lint (approach: A2 only)\n\n%s\n" % ("\n".join("- FAIL A2 %s" % b for b in bad)
                                                                    or "pass"))
    ctx.state["unresolved"] = ["approach.md placeholder %s" % b for b in bad]
    lines = ["# Approach: %s" % ctx.state.get("topic", ""), "", "Build type: approach (%s)." % ctx.variant, "",
             "## Files", "", "- approach.md: the approach", "- review/: the review lens findings",
             "- lint.md: placeholder check", "", "## Decision index", "", "- none (approach build type)"]
    ctx.write(_a("README.md"), "\n".join(lines) + "\n")
    return "approach checked (A2 only): %s" % ("fail" if bad else "pass")


def qas_table(d):
    return table(["id", "attribute", "source", "stimulus", "artifact", "environment", "response", "response measure",
                  "importance", "difficulty"],
                 [[q.get("id"), q.get("qg"), q.get("source"), q.get("stimulus"), q.get("artifact"),
                   q.get("environment"), q.get("response"), q.get("measure"), q.get("importance"),
                   q.get("difficulty")] for q in d.get("qas") or [] if isinstance(q, dict)])


def utility_tree(d):
    lines = []
    by = {}
    for q in d.get("qas") or []:
        if isinstance(q, dict):
            by.setdefault(q.get("qg"), []).append(q)
    for g in d.get("quality_goals") or []:
        lines.append("- %s %s (weight %s)" % (g.get("id"), md_cell(g.get("name")), g.get("weight")))
        for q in by.get(g.get("id"), []):
            lines.append("  - %s (%s/%s): %s" % (q.get("id"), q.get("importance"), q.get("difficulty"),
                                                md_cell(q.get("stimulus"))))
    return "\n".join(lines) or "- (no quality goals)"


def context_diagrams(d):
    """(C4Context body, flowchart body) generated from drivers.context; balanced brackets on every line."""
    c = d.get("context") or {}
    sysd = c.get("system") or {}
    name = mm_text(sysd.get("name") or "System", 6)
    c4 = ["C4Context", "  title System context - %s" % name,
          '  System(SYS, "%s", "%s")' % (name, mm_text(sysd.get("description"), 10))]
    for a in c.get("actors") or []:
        c4.append('  Person(%s, "%s", "%s")' % (mm_id(a.get("id")), mm_text(a.get("name")),
                                                mm_text(a.get("description"), 10)))
    for e in c.get("external") or []:
        c4.append('  System_Ext(%s, "%s", "%s")' % (mm_id(e.get("id")), mm_text(e.get("name")),
                                                    mm_text(e.get("description"), 10)))
    for a in c.get("actors") or []:
        c4.append('  Rel(%s, SYS, "uses")' % mm_id(a.get("id")))
    for e in c.get("external") or []:
        c4.append('  Rel(SYS, %s, "%s")' % (mm_id(e.get("id")), mm_text(e.get("relationship") or "uses", 6)))
    fc = ["flowchart LR", '  SYS["%s"]' % name]
    for a in c.get("actors") or []:
        fc.append('  %s["%s"] --> SYS' % (mm_id(a.get("id")), mm_text(a.get("name"))))
    for e in c.get("external") or []:
        fc.append('  SYS -->|%s| %s["%s"]' % (mm_text(e.get("relationship") or "uses", 4), mm_id(e.get("id")),
                                             mm_text(e.get("name"))))
    return "\n".join(c4), "\n".join(fc)


def adr_index(ctx, prefix=""):
    """| ADR | title | status | table of the files in adr/ (the README decision index and proposal Appendix A)."""
    rows = []
    for p in sorted(glob.glob(ctx.path(ARCH, "adr", "*.md"))):
        t = textio.read_text(p)
        m = re.search(r"^# (ADR-\d{4}): (.*)$", t, re.M)
        stat = re.search(r"^status:\s*(\S+)", t, re.M)
        rows.append(["[%s](%sadr/%s)" % (m.group(1) if m else "ADR-" + os.path.basename(p)[:4], prefix,
                                         os.path.basename(p)),
                     m.group(2).strip() if m else "", stat.group(1) if stat else "?"])
    if not rows:
        return "none"
    return table(["ADR", "title", "status"], rows)
