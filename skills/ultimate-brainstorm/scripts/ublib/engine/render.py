"""Stage 13 Proposal rendering (KIT_SPEC 8): evidence packs, PROPOSAL.md assembly with appendices A-F, the
single-file HTML pack (Markdown subset -> index.html), the zip and the pandoc export.

Scripts: proposal_packs (13.1), proposal_assemble (13.4 and 13.4b), proposal_render (13.7).
"""

import html
import os
import re
import shutil
import zipfile

from .. import filesproto, textio
from . import EngineError
from . import registry

PROP = "11_PROPOSAL"
ARCH = "10_ARCHITECTURE"
# [U-26] Mermaid: one exact version, the single-file build (an ESM entry imports chunks no integrity check covers),
# loaded with Subresource Integrity. MERMAID_SRI is the sha384 of that file; templates/docs/index.html.tpl carries it in
# the script tag, and build_index_html refuses a template whose hash differs. To bump: fetch the new file, compute
# `sha384-` + base64(sha384(bytes)), check it against the npm tarball, change both. Offline, blocked or with a hash
# that does not match, the mermaid source stays visible.
# [U-60] mermaid's single-file build renders under the page's Content-Security-Policy (no eval; inline styles only);
# if it did not, the diagram source would stay visible.
MERMAID_CDN = "https://cdn.jsdelivr.net/npm/mermaid@11.17.2/dist/mermaid.min.js"
MERMAID_SRI = "sha384-EOXBFmc3gx5mb+vn0vPvvGqACToJD24hhacX5Yx+8NUUQrHIle/Qi5Bg9o3zKwW2"
APPENDICES = ["## Appendix A. ADR Index", "## Appendix B. Assumptions Index", "## Appendix C. Candidate Comparison",
              "## Appendix D. Idea Selection Record", "## Appendix E. Glossary", "## Appendix F. Sources"]


def _p(rel):
    return "%s/%s" % (PROP, rel)


def _recover(ctx, *roots):
    """Finish the FILE-protocol commits a crash interrupted in these split roots, so a reader sees whole packages."""
    for root in roots:
        filesproto.recover(ctx.path(root))


# ================================================================ 13.1 packs

def proposal_packs(ctx, step):
    from . import render_arch
    _recover(ctx, ARCH)
    try:
        registry.bs(ctx, "sources", ctx.run_dir)
    except EngineError:
        if not ctx.exists("sources.json"):
            ctx.write_json("sources.json", {})
            ctx.write("sources.md", "# Sources\n\n| id | url | title | accessed | used in |\n|---|---|---|---|---|\n")
    iid = registry.chosen_idea(ctx)
    fr = registry.frame_text(ctx)
    arch = "10_ARCHITECTURE/"
    containers = ctx.read(arch + "chosen/containers.md")
    mblock = ""
    blocks = [b for lang, b in textio.fenced_blocks(containers) if lang == "mermaid"]
    if blocks:
        mblock = "```mermaid\n%s```" % blocks[-1] if blocks[-1].endswith("\n") else "```mermaid\n%s\n```" % blocks[-1]
    adrs = sorted(textio.glob_in(ctx.run_dir, "10_ARCHITECTURE", "adr", "*.md"))[:5]
    matrix = ctx.read_json(arch + "matrix.json", {}) or {}
    pack_a = ["# PACK A (problem, evidence, prior art, decision)", "", "## FRAME", fr, "",
              "## CONTEXT A (facts)", registry.context_section(ctx, "A"), "",
              "## CONTEXT B (landscape)", registry.context_section(ctx, "B") or "NOT SEARCHED", "",
              "## Checks of the chosen idea", ctx.read("checks/%s.md" % iid) if iid else "", "",
              "## Decision", ctx.read("08_DECISION.md") or ctx.read("QUICK_DECISION.md"), "",
              "## Card", registry.card_text(ctx, iid) if iid else ""]
    if ctx.state.get("build_type") == "approach":
        arch_part = ["## Approach", ctx.read(arch + "approach.md")]
    else:
        arch_part = ["## Architecture README", ctx.read(arch + "README.md"), "", "## Container view", mblock, "",
                     "## Top ADRs"] + [textio.read_text(p) for p in adrs] + [
            "", "## Matrix summary", "leader " + render_arch.leader_text(matrix),
            "", "## Deferred", ctx.read(arch + "chosen/deferred.md"), "", "## Drivers",
            ctx.read(arch + "goals-constraints.md")]
    pack_b = ["# PACK B (architecture, scope, roadmap)", ""] + arch_part + ["", "## Probe (Milestone 0)",
                                                                           ctx.read("09_PROBE.md")]
    oq = registry.frame_questions(ctx)
    pack_c = ["# PACK C (cost, risks, success)", "", "## Cost model", ctx.read(arch + "chosen/cost-model.md"), "",
              "## Risks", ctx.read(arch + "risks.md"), "", "## Pre-mortem", ctx.read(arch + "premortem.md"), "",
              "## Red-team kill-assumptions", "\n".join(re.findall(r"(Fails if[^\n]*)",
                                                                 registry._unfenced(ctx.read("07_REDTEAM.md"))))
              or "(none)", "", "## FRAME success", registry.section(fr, "Success looks like") or "NOT VERIFIED", "",
              "## Open questions", "\n".join("- %s (default: %s)" % (q["text"], q.get("default") or "none")
                                             for q in oq) or "(none)"]
    for name, parts in (("PACK_A", pack_a), ("PACK_B", pack_b), ("PACK_C", pack_c)):
        ctx.write(_p("_packs/%s.md" % name), "\n".join(str(x) for x in parts).rstrip() + "\n")
    return "evidence packs written"


# ================================================================ 13.4 assembly

KILLED_BANNER = "KILLED (K6): the chosen idea's pre-registered probe missed; no runner-up is left"


def k6_dead(state):
    """True when the chosen idea's own probe missed and no runner-up was left (gates.probe_result): K6 killed it (a
    decision_log line) and run.json probe records its MISSED. A switch to another finalist ends this state."""
    idea = (state.get("choice") or {}).get("idea")
    probe = state.get("probe") or {}
    return bool(idea) and idea in registry.k6_killed(state) and probe.get("idea") == idea and \
        probe.get("result") == "MISSED"


def status_banner(ctx):
    """DRAFT, APPROVED, AUTOPILOT DRAFT or PENDING MILESTONE 0 (8.2 13.4); KILLED (K6) before any of them once the
    chosen idea's probe missed with no runner-up left (k6_dead)."""
    s = ctx.state
    if k6_dead(s):
        return KILLED_BANNER
    passed = "RESULT: PASSED" in ctx.read("09_PROBE.md")
    if s.get("autopilot") == "full-auto":
        return "AUTOPILOT DRAFT: no human decisions were made"
    if s.get("signed_off"):
        return "APPROVED" if passed else "APPROVED - PENDING MILESTONE 0 (the pre-registered probe has not passed yet)"
    return "DRAFT"


def section_text(ctx, num, heading):
    text = ctx.read(_p("sections/%s.md" % num)).strip()
    if not text:
        if num == "08":
            return milestone0_section(ctx, heading)
        return "%s\n\nNot covered in %s mode." % (heading, ctx.mode)
    lines = text.split("\n")
    first = lines[0].strip() if lines else ""
    if re.match(r"^##\s*%d\." % int(num), first):
        # the canonical heading (lint P1; section 6 is "Approach" for the approach build type)
        return "\n".join([heading] + lines[1:])
    if first.startswith("#"):
        return heading + "\n\n" + re.sub(r"^#{1,3}\s*[^\n]*\n", "", text, count=1)
    return heading + "\n\n" + text


def appendix_a(ctx):
    from . import render_arch
    idx = render_arch.adr_index(ctx, prefix="../10_ARCHITECTURE/")
    if idx == "none":
        return "No ADRs (%s)." % ("approach build type" if ctx.state.get("build_type") == "approach" else
                                  "none written")
    return idx


def appendix_c(ctx):
    """PROPOSAL.md Appendix C: the candidate matrix and its leader as the README names it (render_arch.leader_text);
    a candidate vetoes EXCLUDED has no rank ('-')."""
    from . import render_arch
    m = ctx.read_json("10_ARCHITECTURE/matrix.json", {}) or {}
    cmap = ctx.read_json("10_ARCHITECTURE/candidates/map.json", {}) or {}
    rows = []
    for c in m.get("candidates") or []:
        if isinstance(c, dict):
            lab = c.get("label")
            rows.append("| %s | %s | %s | %s | %s | %s |" % (lab, c.get("score"), c.get("rank") or "-",
                                                            registry.fmt_range(c.get("range")), c.get("veto"),
                                                            (cmap.get(lab) or {}).get("family", "?")))
    if not rows:
        return "No candidate comparison (%s)." % ("approach build type" if ctx.state.get("build_type") ==
                                                  "approach" else "matrix missing")
    return ("| candidate | weighted score | rank | range | veto | author |\n|---|---|---|---|---|---|\n" +
            "\n".join(rows) + "\n\nLeader: %s." % render_arch.leader_text(m))


def appendix_d(ctx):
    """Idea selection record: finalists and judges, the gut pick, debiased standings (score %, scored pairs and the
    ranking method), the Condorcet winner and majority cycles, contested pairs, audit flags, red-team verdicts, the
    decision in the user's words and PROVISIONAL badges (from 06_TOURNAMENT, 07_REDTEAM and 08_DECISION)."""
    s = ctx.state
    info = registry.idea_lines(ctx)
    parts = []
    fin = s.get("finalists") or []
    if fin:
        parts.append("Finalists (%d): %s. Judges: %s." % (len(fin), ", ".join(
            "%s %s" % (i, info.get(i, {}).get("title", "")) for i in fin), registry.judges_line(ctx,
                                                                                               "tournament_judges")))
    gut = registry.gut_picks(ctx)
    parts.append("Gut pick before any tally: %s." % (", ".join(gut) or "skipped"))
    res = registry.tournament_result(ctx)
    deb = [d for d in res.get("debiased") or [] if isinstance(d, dict)]
    if deb:
        # result.json rows: a pair-level Bradley-Terry win share (or raw points) and the number of scored pairs
        rows = ["| rank | idea | score % | pairs |", "|---|---|---|---|"]
        rows += ["| %s | %s %s | %s | %s |" % (d.get("rank") or n, d.get("id"), registry.clean(info.get(
            d.get("id"), {}).get("title", "")), d.get("pct"), d.get("n")) for n, d in enumerate(deb, 1)]
        rk = res.get("ranking") if isinstance(res.get("ranking"), dict) else {}
        method = rk.get("method") or "not recorded"
        if method == "raw-fallback" and rk.get("reason"):
            method += " (%s)" % registry.clean(rk["reason"])
        parts.append("Debiased tournament standings (ranking method: %s):\n\n%s" % (method, "\n".join(rows)))
        cw = res.get("condorcet") if isinstance(res.get("condorcet"), dict) else {}
        cycles = [", ".join(str(c) for c in g) for g in cw.get("cycles") or [] if isinstance(g, list)]
        parts.append("Condorcet winner (beats every other finalist by pairwise majority): %s. Majority cycles: %s."
                     % (cw.get("winner") or "none", "; ".join(cycles) or "none"))
    contested = ["%s vs %s" % (c[0], c[1]) for c in res.get("contested") or [] if isinstance(c, (list, tuple))
                 and len(c) >= 2]
    parts.append("Contested pairs: %s." % ("; ".join(contested) or "none"))
    flags = res.get("flags") or {}
    parts.append("Judge audits: position-consistency flags: %s; self-preference flags: %s." % (
        ", ".join(flags.get("position") or []) or "none", ", ".join(flags.get("self_preference") or []) or "none"))
    verdicts = registry.review_verdicts(ctx)
    if verdicts:
        parts.append("Red-team verdicts:\n\n" + "\n".join("- %s" % v for i in sorted(verdicts) for v in verdicts[i]))
    dec = [ln.strip() for ln in ctx.read("08_DECISION.md").split("\n")
           if re.match(r"^(AUTO-DECISION|Chosen|Runner-up|Parked|Killed|Dissent|Not doing)", ln.strip())]
    if dec:
        parts.append("Decision record (08_DECISION.md):\n\n" + "\n".join("- %s" % d for d in dec))
    if s.get("provisional"):
        parts.append("PROVISIONAL seats:\n\n" + "\n".join("- %s: %s -> %s (%s)" % (
            p.get("stage"), p.get("seat"), p.get("actual"), p.get("reason")) for p in s["provisional"]
            if isinstance(p, dict)))
    if s.get("mode") == "quick":
        parts.append("Novelty NOT checked (quick mode).")
    return "\n\n".join(parts) or "(no selection record)"


def appendix_e(ctx):
    """The FRAME's Domain language, then the A2 terms under their own line (privacy.GLOSSARY_A2: another vendor's copy
    of PROPOSAL.md keeps only the A2 terms FACTS would keep, privacy.filter_glossary)."""
    from . import privacy
    fr = registry.frame_text(ctx)
    dl = registry.section(fr, "Domain language")
    a2 = registry.context_section(ctx, "A2")
    if a2:
        a2 = "%s\n%s" % (privacy.GLOSSARY_A2, a2)
    out = "\n\n".join(x for x in (dl, a2) if x)
    return out or "No domain terms were resolved in this run."


def assemble(ctx):
    """PROPOSAL.md: title block (PROPOSAL-HEAD) + status banner + sections 1-13 + appendices A-F
    (PROPOSAL-APPENDICES)."""
    from . import builders
    from . import gates
    s = ctx.state
    heads = registry.PROPOSAL_SECTIONS
    iid = registry.chosen_idea(ctx)
    info = registry.idea_lines(ctx).get(iid or "", {})
    title = info.get("title") or s.get("topic", "")
    ch = s.get("choice") or {}
    if s.get("build_type") == "approach":
        arch_choice = "approach (%s)" % s.get("variant")
    else:
        cand = registry.chosen_candidate_json(ctx)
        arch_choice = "candidate %s%s" % (ch.get("arch") or "?", (" - %s" % registry.clean(cand.get("paradigm")))
                                          if cand.get("paradigm") else "")
    head_map = {"PROPOSAL_TITLE": title, "STATUS_BANNER": "Status: %s" % status_banner(ctx),
                "PROVISIONAL_BANNER": gates.provisional_banner(ctx), "RUN_NAME": s.get("run", ""),
                "DATE": textio.now_iso()[:10], "MODE": s.get("mode", ""), "VARIANT": s.get("variant", ""),
                "CHOSEN": "%s %s" % (iid or "?", title), "ARCH_CHOICE": arch_choice}

    def head_builtin():
        lines = ["# Proposal: %s" % title, "", head_map["STATUS_BANNER"]]
        if head_map["PROVISIONAL_BANNER"]:
            lines.append(head_map["PROVISIONAL_BANNER"])
        lines.append("- Run: %s | Date: %s | Mode: %s | Variant: %s" % (s.get("run"), head_map["DATE"],
                                                                      s.get("mode"), s.get("variant")))
        return "\n".join(lines) + "\n"
    parts = [builders.render_doc("PROPOSAL-HEAD", head_map, fallback=head_builtin).rstrip()]
    for num, heading in heads:
        if num == "06" and s.get("build_type") == "approach":
            heading = "## 6. Approach"
        parts.append(section_text(ctx, num, heading).strip())
    assumptions = ctx.read(_p("assumptions.md")).strip()
    app_map = {"ADR_INDEX": appendix_a(ctx),
               "ASSUMPTIONS_INDEX": re.sub(r"^#[^\n]*\n", "", assumptions).strip() or "No assumptions recorded.",
               "CANDIDATE_COMPARISON": appendix_c(ctx), "SELECTION_RECORD": appendix_d(ctx),
               "GLOSSARY": appendix_e(ctx),
               "SOURCES_TABLE": re.sub(r"^#[^\n]*\n", "", ctx.read("sources.md")).strip() or "No sources."}

    def app_builtin():
        return "\n\n".join("%s\n\n%s" % (h, app_map[k]) for h, k in zip(APPENDICES, (
            "ADR_INDEX", "ASSUMPTIONS_INDEX", "CANDIDATE_COMPARISON", "SELECTION_RECORD", "GLOSSARY",
            "SOURCES_TABLE"))) + "\n"
    parts.append(builders.render_doc("PROPOSAL-APPENDICES", app_map, fallback=app_builtin).strip())
    return "\n\n".join(parts).rstrip() + "\n"


def proposal_assemble(ctx, step):
    _recover(ctx, PROP)  # the section drafts, registers and one-pager are FILE-protocol outputs
    try:
        registry.bs(ctx, "assumptions", ctx.run_dir)
    except EngineError:
        pass
    ctx.write(_p("PROPOSAL.md"), assemble(ctx))
    stamp_one_pager(ctx)
    write_readme(ctx)
    args = ["lint-proposal", ctx.run_dir] + (["--lite"] if ctx.mode == "quick" else [])
    rc = 0
    try:
        rc, out, err = registry.bs(ctx, *args, allow=(0, 1))
    except EngineError:
        rc = 1
    lint = ctx.read_json(_p("lint.json"), {}) or {}
    return "PROPOSAL.md assembled; lint-proposal: %s" % (lint.get("status") or ("fail" if rc else "pass"))


ONE_PAGER_STATUS_RX = re.compile(r"^Status: .* \| Run: .*$")


def stamp_one_pager(ctx):
    """Put 'Status: <banner> | <date> | Run: <run>' under the one-pager's H1 (replacing an earlier stamp). The
    one-pager is the file people forward, so an autopilot draft or an unapproved proposal must say so."""
    rel = _p("ONE-PAGER.md")
    if not ctx.exists(rel):
        return
    lines = textio.normalize_newlines(ctx.read(rel)).split("\n")
    lines = [ln for ln in lines if not ONE_PAGER_STATUS_RX.match(ln)]
    stamp = "Status: %s | %s | Run: %s" % (status_banner(ctx), textio.now_iso()[:10], ctx.state.get("run", ""))
    h1 = next((i for i, ln in enumerate(lines) if ln.startswith("# ")), None)
    if h1 is None:
        lines = [stamp, ""] + lines
    else:
        lines[h1 + 1:h1 + 1] = [stamp]
    ctx.write(rel, re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).rstrip("\n") + "\n")


def write_readme(ctx):
    from . import builders
    files = [["PROPOSAL.md", "the full proposal (sections 1-13 and appendices A-F)"],
             ["ONE-PAGER.md", "the one-pager"], ["index.html", "the single-file HTML pack"],
             ["sections/", "the section drafts"], ["assumptions.md, open-questions.md", "registers"],
             ["review/", "rubric, red-team and resolution"], ["lint.md, lint.json", "lint-proposal results"]]
    if ctx.exists(_p("PRFAQ.md")):
        files.insert(2, ["PRFAQ.md", "the press release and FAQ"])
    rows = ["| file | what |", "|---|---|"] + ["| %s | %s |" % (a, b) for a, b in files]
    mapping = {"RUN_NAME": ctx.state.get("run", ""), "STATUS_BANNER": "Status: %s" % status_banner(ctx),
               "FILE_MAP": "\n".join(rows)}
    ctx.write(_p("README.md"), builders.render_doc("PROPOSAL-README", mapping, fallback=lambda: (
        "# Proposal files: %(RUN_NAME)s\n%(STATUS_BANNER)s\n\n%(FILE_MAP)s\n" % mapping)))


# ================================================================ Markdown subset -> HTML

# A link target kept as it is: http(s) (any letter case), an in-page anchor, or a relative path that starts with a
# letter, digit, "_", "." or "-" (so never "/", "//host" or "\\host"); anything else becomes "#".
_SAFE_HREF_RE = re.compile(r"^(?:[Hh][Tt][Tt][Pp][Ss]?://|#|[A-Za-z0-9_.-][A-Za-z0-9_./#-]*$)")
_KEPT_RE = re.compile("\x00(\\d+)\x00")
# [label](target): neither part holds a bracket, so a failed attempt stops at the next '[' and the scan stays linear
# (label and target runs that could reach the end of the text cost quadratic time on text like "[a](b[a](b...")
_LINK_RE = re.compile(r"\[([^\[\]]+)\]\(([^)\s\[\]]+)\)")


def _inline(text):
    """Inline Markdown -> HTML. Code spans are taken out first (their text stays literal), then links, whose target is
    checked and escaped once, on the raw text; the rest is escaped and gets emphasis (which may span a link)."""
    kept = []

    def keep(fragment):
        kept.append(fragment)
        return "\x00%d\x00" % (len(kept) - 1)

    def restore(t):
        return _KEPT_RE.sub(lambda m: kept[int(m.group(1))], t)

    def emphasis(t):
        t = html.escape(t, quote=False)
        t = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", t)
        t = re.sub(r"(?<![\w*])\*([^*\n]+)\*(?![\w*])", r"<em>\1</em>", t)
        return re.sub(r"(?<![\w_])_([^_\n]+)_(?![\w_])", r"<em>\1</em>", t)

    def link(m):
        href = m.group(2) if _SAFE_HREF_RE.match(m.group(2)) else "#"
        return keep('<a href="%s">%s</a>' % (html.escape(href, quote=True), restore(emphasis(m.group(1)))))
    t = re.sub(r"`([^`]+)`", lambda m: keep("<code>%s</code>" % html.escape(m.group(1), quote=False)),
               text.replace("\x00", "\N{REPLACEMENT CHARACTER}"))
    t = _LINK_RE.sub(link, t)
    return restore(emphasis(t))


class Anchors(set):
    """The ids used in one page, with the next free number per base, so the Nth heading of one name costs O(1)
    instead of probing base-2 ... base-N again (10k identical headings took 12 s)."""

    def __init__(self, *args):
        set.__init__(self, *args)
        self.next = {}


def anchor(text, used):
    base = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "section"
    counters = getattr(used, "next", {})  # a plain set works too (without the shortcut)
    a, n = base, counters.get(base, 2)
    if a in used:
        a = "%s-%d" % (base, n)
        while a in used:
            n += 1
            a = "%s-%d" % (base, n)
        counters[base] = n + 1
    used.add(a)
    return a


def md_to_html(md, used=None, toc=None, shift=0):
    """Headings, paragraphs, lists, GFM tables, fenced code (mermaid -> pre.mermaid), emphasis, links, blockquotes."""
    used = used if used is not None else Anchors()
    lines = textio.normalize_newlines(md or "").split("\n")
    out = []
    i = 0
    para = []

    def flush():
        if para:
            out.append("<p>%s</p>" % _inline(" ".join(p.strip() for p in para)))
            del para[:]
    while i < len(lines):
        ln = lines[i]
        fence = textio.fence_open(ln)
        if fence:
            flush()
            lang = fence[2]
            body = []
            i += 1
            while i < len(lines) and not textio.fence_closes(lines[i], fence):
                body.append(lines[i])
                i += 1
            i += 1
            code = html.escape("\n".join(body), quote=False)
            if lang == "mermaid":
                out.append('<pre class="mermaid">%s</pre>' % code)
            else:
                out.append('<pre><code class="language-%s">%s</code></pre>' % (lang or "text", code))
            continue
        hm = textio.parse_heading(ln)
        if hm:
            flush()
            level = min(6, hm[0] + shift)
            text = hm[1]
            a = anchor(text, used)
            if toc is not None and level == 2:
                toc.append((a, text))
            out.append('<h%d id="%s">%s</h%d>' % (level, a, _inline(text), level))
            i += 1
            continue
        if re.match(r"^\s*\|.*\|\s*$", ln) and i + 1 < len(lines) and re.match(r"^\s*\|?\s*:?-{3,}", lines[i + 1]):
            flush()
            head = [c.strip() for c in ln.strip().strip("|").split("|")]
            i += 2
            rows = []
            while i < len(lines) and re.match(r"^\s*\|.*\|\s*$", lines[i]):
                rows.append([c.strip() for c in lines[i].strip().strip("|").split("|")])
                i += 1
            t = ["<table><thead><tr>%s</tr></thead><tbody>" % "".join("<th>%s</th>" % _inline(h) for h in head)]
            for r in rows:
                t.append("<tr>%s</tr>" % "".join("<td>%s</td>" % _inline(c) for c in r))
            t.append("</tbody></table>")
            out.append("".join(t))
            continue
        lm = re.match(r"^(\s*)([-*+]|\d+[.)])\s+(.*)$", ln)
        if lm:
            flush()
            ordered = lm.group(2)[0].isdigit()
            items = []
            while i < len(lines):
                m2 = re.match(r"^(\s*)([-*+]|\d+[.)])\s+(.*)$", lines[i])
                if not m2:
                    if lines[i].startswith("  ") and lines[i].strip() and items:
                        items[-1] += " " + lines[i].strip()
                        i += 1
                        continue
                    break
                items.append(("  " if m2.group(1) else "") + m2.group(3))
                i += 1
            tag = "ol" if ordered else "ul"
            out.append("<%s>%s</%s>" % (tag, "".join("<li>%s</li>" % _inline(x.strip()) for x in items), tag))
            continue
        if ln.startswith(">"):
            flush()
            quote = []
            while i < len(lines) and lines[i].startswith(">"):
                quote.append(lines[i][1:].strip())
                i += 1
            out.append("<blockquote>%s</blockquote>" % _inline(" ".join(quote)))
            continue
        if not ln.strip():
            flush()
            i += 1
            continue
        if re.match(r"^\s*(---|\*\*\*)\s*$", ln):
            flush()
            out.append("<hr>")
            i += 1
            continue
        para.append(ln)
        i += 1
    flush()
    return "\n".join(out)


def build_index_html(ctx):
    """11_PROPOSAL/index.html from templates/docs/index.html.tpl: cover, one-pager card, table of contents,
    sections 1-13 (ids sec-1..sec-13), architecture (diagrams, ADR cards, risk table), appendices (ids
    appendix-a..appendix-f). Mermaid blocks become <pre class="mermaid">."""
    from . import builders
    _recover(ctx, PROP, ARCH)
    s = ctx.state
    used = Anchors(["cover", "toc", "one-pager", "sections", "architecture", "appendices", "status-badge"])
    proposal = ctx.read(_p("PROPOSAL.md"))
    one = ctx.read(_p("ONE-PAGER.md"))
    m = re.search(r"^# (.*)$", proposal, re.M)
    title = m.group(1).strip() if m else "Proposal: %s" % s.get("topic", "")
    badge = status_banner(ctx)
    pitch = registry.idea_lines(ctx).get(registry.chosen_idea(ctx) or "", {}).get("pitch") or s.get("topic", "")
    sections, appendices, toc_sec, toc_app = [], [], [], []
    for head, body in split_h2(proposal):
        ms = re.match(r"^(\d{1,9})\.\s*(.*)$", head)  # int() refuses a 4301-digit heading number
        ma = re.match(r"^Appendix\s+([A-F])\.\s*(.*)$", head, re.I)
        if ms:
            hid = "sec-%d" % int(ms.group(1))
            toc_sec.append((hid, head))
            sections.append('<h2 id="%s">%s</h2>\n%s' % (hid, html.escape(head), md_to_html(body, used, None, 0)))
        elif ma:
            hid = "appendix-%s" % ma.group(1).lower()
            toc_app.append((hid, head))
            appendices.append('<h2 id="%s">%s</h2>\n%s' % (hid, html.escape(head), md_to_html(body, used, None, 0)))
    arch = ['<h2 id="architecture-view">Architecture</h2>']
    for rel in ("10_ARCHITECTURE/context.md", "10_ARCHITECTURE/chosen/containers.md"):
        for lang, b in textio.fenced_blocks(ctx.read(rel)):
            if lang == "mermaid":
                arch.append('<pre class="mermaid">%s</pre>' % html.escape(b.rstrip("\n"), quote=False))
    approach = ctx.read("10_ARCHITECTURE/approach.md")
    if approach and s.get("build_type") == "approach":
        arch.append(md_to_html(re.sub(r"^# .*\n", "", approach, count=1), used, None, 1))
    cards = []
    for p in sorted(textio.glob_in(ctx.run_dir, "10_ARCHITECTURE", "adr", "*.md")):
        t = re.sub(r"(?s)^---.*?---\s*", "", textio.read_text(p))
        cards.append('<div class="card adr">%s</div>' % md_to_html(t, used, None, 2))
    if cards:
        arch.append('<h3 id="adr-cards">Architecture decisions</h3>\n<div class="adr-cards">\n%s\n</div>'
                    % "\n".join(cards))
    risks = ctx.read("10_ARCHITECTURE/risks.md")
    if risks:
        arch.append('<h3 id="risk-table">Risks</h3>\n' + md_to_html(
            registry.section(risks, "Risks") or re.sub(r"^# .*\n", "", risks, count=1), used, None, 1))
    toc = ['<ul>', '<li><a href="#one-pager">One-pager</a></li>']  # the headings carry their own numbers
    toc += ['<li><a href="#%s">%s</a></li>' % (a, html.escape(t)) for a, t in toc_sec]
    toc.append('<li><a href="#architecture-view">Architecture</a></li>')
    toc += ['<li><a href="#%s">%s</a></li>' % (a, html.escape(t)) for a, t in toc_app]
    toc.append('</ul>')
    one_html = ('<h2 id="one-pager-title">One-pager</h2>\n' +
                md_to_html(re.sub(r"^# .*\n", "", one, count=1), used, None, 1)) if one else "<p>No one-pager.</p>"
    body = (['<section id="sections">'] + sections + ['</section>', '<section id="architecture">'] + arch +
            ['</section>', '<section id="appendices">'] + appendices + ['</section>'])
    mapping = {"LANG": html.escape(s.get("lang") or "en"), "TITLE": html.escape(title), "PITCH": html.escape(pitch),
               "BADGE": html.escape(badge), "DATE": textio.now_iso()[:10], "TOC": "\n".join(toc),
               "ONE_PAGER": one_html, "BODY": "\n".join(body), "MERMAID_CDN": MERMAID_CDN}
    tpl = registry.load_template("INDEX-HTML", "docs", raw=True)
    bad = EngineError("templates/docs/index.html.tpl is missing, uses a placeholder the engine does not fill, or "
                      "loads another Mermaid build than %s" % MERMAID_CDN,
                      fix=["reinstall the kit (templates and engine versions differ): install.py update"])
    if not tpl or 'integrity="%s"' % MERMAID_SRI not in tpl:
        raise bad
    if (s.get("privacy") or {}).get("web") is False:
        tpl = offline_template(tpl)
    doc = builders.fill_doc(tpl, mapping)
    if not doc:
        raise bad
    return doc.rstrip("\n") + "\n"


def offline_template(tpl):
    """The page template for a run without web access (privacy web = no, as `private` sets it): no <script> at all, a
    Content-Security-Policy with script-src 'none', and a footer that says so. Opening the page then contacts nobody
    (the CDN would receive the reader's IP address); diagrams show their Mermaid source. Refuses a template it cannot
    make script-free (EngineError), rather than let a private run's page load the CDN."""
    out = re.sub(r"<script\b[^>]*>.*?</script>[ \t]*\n?", "", tpl, flags=re.S | re.I)
    out = re.sub(r"script-src [^;\"]*", "script-src 'none'", out)
    out = re.sub(r'<footer class="footer">.*?</footer>',
                 '<footer class="footer">Generated by ultimate-brainstorm. This run allows no web access, so the page '
                 'loads no script: diagrams show their Mermaid source.</footer>', out, flags=re.S)
    if "<script" in out.lower() or "{{MERMAID_CDN}}" in out or "script-src 'none'" not in out:
        raise EngineError("templates/docs/index.html.tpl cannot be made script-free for a run without web access",
                          fix=["reinstall the kit (templates and engine versions differ): install.py update"])
    return out


def render_pack(ctx, make_zip=False):
    doc = build_index_html(ctx)
    ctx.write(_p("index.html"), doc)
    out = {"index": textio.to_posix(ctx.path(_p("index.html")))}
    if make_zip:
        out["zip"] = textio.to_posix(write_zip(ctx))
    return out


def page_is_current(ctx):
    """False when 11_PROPOSAL/index.html loads a script this kit would not load: any script in a run without web
    access, or a script without the pinned build's integrity (a page kit 2.0.x rendered imports a floating mermaid@11
    with no SRI and no CSP). A page without a script loads nothing and counts as current."""
    page = ctx.read(_p("index.html"))
    if "<script" not in page.lower():
        return True
    if (ctx.state.get("privacy") or {}).get("web") is False:
        return False
    return 'integrity="%s"' % MERMAID_SRI in page


def refresh_page(ctx):
    """Render 11_PROPOSAL/index.html again when it exists and is not current (page_is_current), so a page an older
    kit rendered is never published or exported as it is. Returns True when it did."""
    if not ctx.exists(_p("index.html")) or page_is_current(ctx):
        return False
    render_pack(ctx)
    return True


def write_zip(ctx):
    path = ctx.path(PROP, "export", "%s-proposal.zip" % ctx.state.get("run", "run"))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for rel in (_p("index.html"), _p("PROPOSAL.md"), _p("ONE-PAGER.md")):
            if ctx.exists(rel):
                z.write(ctx.path(rel), rel)
        root = ctx.path("10_ARCHITECTURE")
        for dirpath, dirs, files in os.walk(root):
            dirs[:] = [d for d in dirs if d != "_raw"]
            for f in sorted(files):
                if f.endswith((".meta.json", ".failed.md")):
                    continue
                full = os.path.join(dirpath, f)
                z.write(full, os.path.relpath(full, ctx.run_dir).replace("\\", "/"))
    return path


def proposal_render(ctx, step):
    render_pack(ctx)
    return "index.html rendered"


def export(ctx, fmt):
    """`ub export`: html = copy of index.html; docx via pandoc only when it is on PATH."""
    os.makedirs(ctx.path(PROP, "export"), exist_ok=True)
    if fmt == "html":
        if not ctx.exists(_p("index.html")) or not page_is_current(ctx):
            render_pack(ctx)
        dst = ctx.path(PROP, "export", "PROPOSAL.html")
        shutil.copy2(ctx.path(_p("index.html")), dst)
        return {"ok": True, "path": textio.to_posix(dst)}
    if fmt == "docx":
        from .. import proc
        pandoc = proc.which("pandoc")
        if not pandoc:
            return {"ok": False, "error": "pandoc is not on PATH; install it or use --format html"}
        # --sandbox (pandoc 2.15+): no network and no local file reads beyond the input, so image URLs written by a
        # model are never fetched
        try:
            ver = proc.run([pandoc, "--version"], cwd=ctx.path(PROP), timeout_s=60)
            m = re.search(r"(\d+)\.(\d+)", textio.decode_bytes(ver.stdout_bytes))
            vt = (int(m.group(1)), int(m.group(2))) if m else None
        except (OSError, proc.ProcError):
            vt = None
        if vt is None or vt < (2, 15):
            return {"ok": False, "error": "pandoc 2.15+ is required (for --sandbox); use --format html"}
        dst = ctx.path(PROP, "export", "PROPOSAL.docx")
        res = proc.run([pandoc, "--sandbox", "PROPOSAL.md", "-o", os.path.join("export", "PROPOSAL.docx")],
                       cwd=ctx.path(PROP), timeout_s=300)
        if res.returncode != 0:
            return {"ok": False, "error": textio.decode_bytes(res.stderr_bytes)[-500:]}
        return {"ok": True, "path": textio.to_posix(dst)}
    return {"ok": False, "error": "unknown format %s" % fmt}


def milestone0_section(ctx, heading):
    """Section 8 when no writer covered it (quick mode): Milestone 0 is the pre-registered probe (lint P5)."""
    probe = ctx.read("09_PROBE.md")
    kill = registry.section(probe, "4") or registry.section(probe, "Kill criterion") or "see 09_PROBE.md"
    design = registry.section(probe, "3") or registry.section(probe, "Probe") or "see 09_PROBE.md"
    return ("%s\n\n- Milestone 0: run the pre-registered probe (09_PROBE.md) before any build work. Probe: %s\n"
            "  The kill criterion: %s\n- Later milestones are planned only after Milestone 0 passes (quick mode wrote "
            "no further roadmap)." % (heading, " ".join(design.split()), " ".join(kill.split())))


def split_h2(md):
    """[(heading text, body markdown)] for every '## ' section of a Markdown text (the preamble is dropped). A '## '
    line inside a fenced code block is code, not a section (textio.headings)."""
    text = textio.normalize_newlines(md or "")
    lines = text.split("\n")
    heads = [(i, title) for i, level, title in textio.headings(text) if level == 2]
    return [(title, "\n".join(lines[i + 1:heads[k + 1][0] if k + 1 < len(heads) else len(lines)]))
            for k, (i, title) in enumerate(heads)]
