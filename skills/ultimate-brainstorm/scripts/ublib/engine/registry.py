"""Registries used by pipeline.json (KIT_SPEC 6.11): predicates, fanouts, placeholders and scripts.

- PREDICATES[name](ctx, arg) -> bool          `when` entries: "name", "name:arg", "!name", "a|b"
- FANOUTS[name](ctx, step) -> [item, ...]     one job per item (see builders.build_jobs)
- SIM_COUNTS[name](ctx) -> (min, max)         the simulated count of a fanout whose items come from files that earlier
                                             steps write (fanout_count builds every other fanout's items and counts
                                             them)
- PLACEHOLDERS[NAME](ctx, jc) -> str          {{NAME}} in templates; jc = the job context (family, item, ...)
- SCRIPTS[name](ctx, step) -> note|None       SCRIPT steps and `after` hooks

In simulation (`ctx.sim` is a dict) predicates read facts from ctx.sim instead of files.
"""

import json
import math
import os
import re

from .. import textio
from . import FAMILY_ORDER, REPO_VARIANTS, TEMPLATES_DIR, EngineError, base_family, is_alt, vendor_of
from . import privacy as privacy_mod
from . import seats as seats_mod
from . import state as st

DEFAULT_CRITERIA = {"Value": 30, "Feasibility": 25, "Fit": 20, "Distinctiveness": 15, "Evidence": 10}
QUICK_DEFAULT_CRITERIA = ["Value", "Feasibility", "Distinctiveness"]
CARD_LINES = ["Title:", "Problem:", "Mechanism:", "For whom:", "First version:", "Main risk:", "Prior art:"]
CHECK_FINAL = r"^VERDICT: (CROWDED|ADJACENT|NOT LOCATED|NOT CHECKED); DIFFERENTIATOR: .+$"
# nothing reads a reviewer's confidence: the suffix is no longer asked for, and still accepted from older outputs
REVIEW_FINAL = r"^VERDICT: (BACK IF .+|BACK|DON'T BACK)(; confidence (0(\.\d+)?|1(\.0+)?))?$"
CHECK_RANK = {"NOT LOCATED": 0, "ADJACENT": 1, "NOT CHECKED": 2, "CROWDED": 3}  # E-idea finalist order (9.1)
SYNTH_FINAL = r"^WHOLE-EFFORT: (CONTINUE|STOP)"
PROBE_FINAL = r"^RESULT: PENDING$"
ARCH_HEADINGS = ["## 1 Paradigm", "## 2 Container view", "## 3 Stack", "## 4 Quality mechanisms", "## 5 Data",
                 "## 6 Deployment and operations", "## 7 Security and privacy", "## 8 Cost", "## 9 Trade-offs",
                 "## 10 Risks", "## 11 Rejected approaches", "## 12 Innovation tokens"]
FIXED_ARCH_CRITERIA = [("time_to_mvp", 10), ("team_fit", 5), ("run_cost", 5), ("reversibility", 5),
                       ("operational_simplicity", 5)]
ARCHETYPE_TEXT = {
    "A": "Boring by default: a modular monolith on managed services (managed database, managed auth). Use at most 3 "
         "innovation tokens. Build the simplest design that meets every H-importance quality scenario.",
    "C": "The approach the other candidates would not pick. The others are: {others}. Make its strongest case, and "
         "still meet every hard constraint.",
    "D": "Cost-minimal: the cheapest design that still meets the H-importance quality scenarios.",
}
ARCHETYPE_NAMES = {"A": "boring modular monolith", "B": "variant-specific", "C": "contrarian", "D": "cost-minimal"}
SOFTWARE_ARCHETYPES = {"A": "Smallest change to the current architecture (cite files)",
                       "B": "One new bounded component or service"}
PROPOSAL_SECTIONS = [
    ("01", "## 1. Executive Summary"), ("02", "## 2. Problem and Evidence"), ("03", "## 3. Solution"),
    ("04", "## 4. Users and Market"), ("05", "## 5. Differentiation vs Prior Art"),
    ("06", "## 6. Architecture Summary"), ("07", "## 7. Scope and MVP"), ("08", "## 8. Roadmap and Milestones"),
    ("09", "## 9. Team and Effort"), ("10", "## 10. Budget and Cost"), ("11", "## 11. Risks and Mitigations"),
    ("12", "## 12. Success Metrics and Validation Plan"), ("13", "## 13. Open Questions"),
]
PROPOSAL_PARTS = {"A": ["02", "03", "04", "05"], "B": ["06", "07", "08", "09"], "C": ["10", "11", "12", "13"]}
LITE_SECTIONS = ["01", "02", "03", "06", "07", "11", "12", "13"]
ONEPAGER_HEADINGS = ["## Problem", "## Solution", "## Why now", "## Who", "## Differentiation",
                     "## Architecture at a glance", "## MVP", "## Roadmap", "## Budget", "## Top risks", "## Metrics",
                     "## The ask"]
REVIEW_LENSES = {"L1": "web-verified tech", "L2": "divergence adversary", "L3": "failure modes + prior art",
                 "L4": "security and privacy"}


# ================================================================ shared helpers

def section(text, heading, level=2):
    """Body of the first '## <heading>...' section (prefix match, case-insensitive), up to the next heading of the
    same or a higher level. Headings in fenced code blocks are code (textio.section: the contract's rule, #41)."""
    return textio.section(text, heading, level)


def sections_by_prefix(text, prefixes, level=2):
    out = []
    for p in prefixes:
        body = section(text, p, level)
        if body:
            out.append("%s %s\n%s" % ("#" * level, p, body))
    return "\n\n".join(out)


def clean(text):
    return " ".join(str(text or "").replace("|", "/").split())


def words(text, n):
    ws = str(text or "").split()
    return " ".join(ws[:n]) + (" ..." if len(ws) > n else "")


def fmt_range(r):
    """[1, 2] -> '1-2' (rank ranges in tables)."""
    if isinstance(r, (list, tuple)) and len(r) == 2:
        return "%s-%s" % (r[0], r[1])
    return str(r if r is not None else "-")


def first_line(text):
    for ln in str(text or "").split("\n"):
        if ln.strip():
            return ln.strip()
    return ""


def final_line(text):
    lines = [ln for ln in str(text or "").split("\n") if ln.strip()]
    return lines[-1].strip() if lines else ""


def load_template(name, folder="prompts", raw=False):
    """Template text without its ub-template header line (raw=True keeps it), or None when the file does not
    exist."""
    path = template_path(name, folder)
    if not os.path.exists(path):
        return None
    text = textio.read_text(path)
    if raw:
        return text
    lines = text.split("\n")
    if lines and lines[0].lstrip().startswith("<!-- ub-template:"):
        lines = lines[1:]
    return "\n".join(lines)


def template_path(name, folder="prompts"):
    fname = "index.html.tpl" if (folder == "docs" and name == "INDEX-HTML") else name + ".md"
    return os.path.join(TEMPLATES_DIR, folder, fname)


_MANIFEST = {}


def manifest():
    """templates/manifest.json (the template inventory with per-template contracts); {} when missing."""
    if "m" not in _MANIFEST:
        try:
            data = textio.read_json(os.path.join(TEMPLATES_DIR, "manifest.json"))
        except (OSError, ValueError):
            data = {}
        _MANIFEST["m"] = data if isinstance(data, dict) else {}
    return _MANIFEST["m"]


def tcontract(name, default=None, **override):
    """The contract of prompt template `name` from the manifest (a deep copy), else `default`; keys in `override`
    replace the manifest's."""
    entry = ((manifest().get("prompts") or {}).get(name) or {})
    c = entry.get("contract")
    c = json.loads(json.dumps(c)) if isinstance(c, dict) else json.loads(json.dumps(default or {"type": "text"}))
    c.update(override)
    return c


def split_root(name, default="."):
    return ((manifest().get("prompts") or {}).get(name) or {}).get("split_root") or default


def schema_ref(name):
    return "SK:templates/schemas/%s.schema.json" % name


def bs(ctx, *args, **kw):
    """Run bs.py <args> <run> as a subprocess; raise EngineError on a failing exit code unless allowed. redo: the step
    that wrote the model output the command reads; bs.py's exit 5 (invalid input, such as a curated key or id listed
    twice or an empty field) is fixed by running that step again, so that redo is the fix instead of the doctor."""
    allowed = kw.get("allow", (0,))
    rc, out, err = ctx.deps.bs(list(args), ctx.run_dir)
    if rc not in allowed:
        redo = kw.get("redo") if rc == 5 else None
        raise EngineError("bs.py %s failed (exit %s): %s" % (" ".join(args), rc, (err or out or "").strip()[-600:]),
                          fix=[redo_cmd(ctx, redo) if redo else "%s doctor --json" % (ctx.state.get("runner") or "ub")])
    return rc, out, err


def redo_cmd(ctx, step_id):
    """The command that redoes `step_id` and every later step of this run (a BLOCKED card's fix)."""
    return '%s redo "%s" %s --yes' % (ctx.state.get("runner") or "ub", textio.to_posix(ctx.run_dir), step_id)


def curation_before(step_id):
    """The curation step whose output a later step reads: the closest curator step before `step_id` (5.1 for 5.2, 5.3c
    for 5.3m, 5.4c for 5.4m, Q.3 for Q.3p and Q.4)."""
    from . import pipeline  # lazy: pipeline imports this module
    steps = pipeline.load_steps()
    return next(s["id"] for s in reversed(steps[:pipeline.index_of(steps, step_id)])
                if (s.get("job") or {}).get("kind") == "curator")


# ---------------------------------------------------------------- frame, context, criteria

def frame_text(ctx):
    return ctx.read("01_FRAME.md")


def seeds_text(ctx):
    return ctx.read("00_HUMAN_SEEDS.md")


def seeds_section(ctx, name):
    return section(seeds_text(ctx), name)


def brief_text(ctx):
    fr = frame_text(ctx)
    if fr.strip():
        return sections_by_prefix(fr, ["Job statement", "Problem", "Audience", "Success looks like",
                                       "Hard constraints", "Soft constraints", "Non-goals", "Axes"])
    parts = ["Topic: %s" % ctx.state.get("topic", "")]
    prob = seeds_section(ctx, "Problem")
    if prob:
        parts.append("Problem (the user's words): %s" % prob)
    off = seeds_section(ctx, "Off-limits")
    if off:
        parts.append("Off-limits: %s" % off)
    q = ctx.state.get("quick") or {}
    if q.get("hard_constraint"):
        parts.append("Hard constraint: %s" % q["hard_constraint"])
    return "\n".join(parts)


CONTEXT_HEADINGS = {"A": r"##\s*A\.?\s+FACTS", "A2": r"##\s*A2\b", "B": r"##\s*B\b", "C": r"##\s*C\.?\s+SEARCH"}


def _h2_sections(text):
    """[(heading line, body)] for every '## ' heading outside fenced blocks, so a '## ' line quoted inside a code block
    never cuts a section short (a cut would also leave an unclosed fence behind). The fence rule is textio's, the one
    the P-GROUND contract validated the file with (#41): a line that rule does not open never hides a heading."""
    lines = textio.normalize_newlines(text or "").split("\n")
    mask = textio.fence_mask(lines)
    heads = [i for i, ln in enumerate(lines) if not mask[i] and re.match(r"##\s", ln)]
    return [(lines[h], "\n".join(lines[h + 1:(heads[k + 1] if k + 1 < len(heads) else len(lines))]))
            for k, h in enumerate(heads)]


def context_section(ctx, letter):
    rx = CONTEXT_HEADINGS.get(letter)
    if rx is None:
        return ""
    hits = [(h, body) for h, body in _h2_sections(ctx.read("02_CONTEXT.md")) if re.match(rx, h, re.I)]
    if letter == "B":
        return "\n\n".join(("%s\n%s" % (h, body)).strip() for h, body in hits)
    return hits[0][1].strip() if hits else ""


def facts_text(ctx, family):
    a = context_section(ctx, "A")
    parts = []
    if a:
        parts.append("## A. FACTS\n" + a)
    if ctx.variant in REPO_VARIANTS:
        a2 = context_section(ctx, "A2")
        if a2:
            parts.append("## A2. DOMAIN TERMS (today's system)\n" + a2)
    text = "\n\n".join(parts) or "(no FACTS: grounding was skipped in this mode)"
    return privacy_mod.filter_facts(text, ctx.state, family or ctx.host_family)


def criteria(ctx):
    data = ctx.read_json("criteria.json", None)
    if isinstance(data, dict) and data:
        out = {}
        for k, v in data.items():
            try:
                out[str(k)] = float(v)
            except (TypeError, ValueError):
                continue
        if out:
            return out
    return dict((k, float(v)) for k, v in DEFAULT_CRITERIA.items())


def axes(ctx):
    """{axis: [values]} from the FRAME Axes section ('- Name: a, b, c' lines)."""
    body = section(frame_text(ctx), "Axes")
    out = {}
    for ln in body.split("\n"):
        s = re.sub(r"^\s*(?:[-*]|\d+[.)])\s*", "", ln).strip()
        if ":" not in s:
            continue
        name, vals = s.split(":", 1)
        name = name.strip(" *_`")
        values = [v.strip(" *_`.") for v in re.split(r"[,;/|]", vals) if v.strip(" *_`.")]
        if name and len(values) >= 2:
            out[name] = values[:6]
    return out


def is_repo(ctx):
    """True when the project folder is a git repository: a .git folder, or a git worktree or submodule (a .git file
    'gitdir: ...'), as privacy.is_git_repo decides for the repo label too."""
    if ctx.sim is not None:
        return bool(ctx.sim.get("repo", ctx.variant in REPO_VARIANTS))
    return privacy_mod.is_git_repo(ctx.state.get("project_dir"))


def repo_access(ctx, fam):
    """True when a checker, researcher, architecture author or writer of `fam` may read the repository: a software or
    growth run in a git repository and a family of the host's vendor (the one rule for every repo-reading job; 6.8
    also removes the repo from any other vendor's job in builders.make_job)."""
    return ctx.variant in REPO_VARIANTS and is_repo(ctx) and vendor_of(fam) == vendor_of(ctx.host_family)


# ---------------------------------------------------------------- ideas

def idea_lines(ctx):
    """{id: {"title","pitch","mechanism"}} from screen/ideas.md, E ideas, proposal and quick ideas."""
    out = {}
    for ln in ctx.read("screen/ideas.md").split("\n"):
        parts = [p.strip() for p in ln.split("|")]
        if len(parts) >= 4 and re.match(r"^[IE]-\d+$", parts[0]):
            out[parts[0]] = {"title": parts[1], "pitch": parts[2], "mechanism": parts[3]}
    for b in idea_blocks(ctx.read("05_EVOLVED.md"), "E"):
        out.setdefault(b["id"], {"title": b["title"], "pitch": b["fields"].get("pitch", ""),
                                 "mechanism": b["fields"].get("mechanism", "")})
    cur = ctx.read_json("quick/curated.json", None)
    if isinstance(cur, dict):
        for it in cur.get("ideas") or []:
            if isinstance(it, dict) and it.get("id"):
                out.setdefault(str(it["id"]), {"title": it.get("title", ""), "pitch": it.get("pitch", ""),
                                               "mechanism": it.get("mechanism", "")})
    return out


def idea_blocks(text, prefix=None):
    """'### P-NN Title' blocks with '- Label: value' lines ({"id", "title", "body", "fields"}), exactly as the
    idea-blocks contract parses them (validate.parse_idea_blocks): fenced examples, incomplete blocks and repeated IDs
    are not ideas here either."""
    from .. import validate
    return validate.parse_idea_blocks(text or "", prefix)[0]


def idea_text(ctx, iid):
    info = idea_lines(ctx).get(iid)
    if not info:
        return "%s: (idea text not found)" % iid
    lines = ["%s: %s" % (iid, info.get("title", "")),
             "Pitch: %s" % info.get("pitch", ""),
             "Mechanism: %s" % info.get("mechanism", "")]
    return "\n".join(lines)


def origins(ctx):
    data = ctx.read_json("origins.json", {})
    return data if isinstance(data, dict) else {}


def check_verdict(ctx, iid):
    """(verdict, differentiator) from the final line of checks/<ID>.md."""
    text = ctx.read("checks/%s.md" % iid)
    m = re.search(r"VERDICT:\s*(CROWDED|ADJACENT|NOT LOCATED|NOT CHECKED)\s*;\s*DIFFERENTIATOR:\s*(.*)$",
                  final_line(text), re.I)
    if not m:
        return None, None
    return m.group(1).upper(), m.group(2).strip()


def rescued_ids(text):
    """The idea IDs on the `Rescued:` lines of 04_SHORTLIST.md (also bs.py's @checks). IDs only: an older kit wrote
    each rescue's reason in parentheses on this line, and an ID named in a reason is not rescued (a K1 kill would come
    back), so every balanced (...) group, nested ones included, is dropped first, in one pass over the line."""
    ids = []
    for ln in (text or "").split("\n"):
        if not re.match(r"^\W*Rescued\W*:", ln, re.I):
            continue
        out, opened = [], []  # opened: where each '(' not closed yet sits in out
        for ch in ln:
            if ch == ")" and opened:
                del out[opened.pop():]
                ch = " "
            elif ch == "(":
                opened.append(len(out))
            out.append(ch)
        ids += re.findall(r"\b[IE]-\d+\b", "".join(out))
    return ids


def shortlist_ids(ctx):
    data = ctx.read_json("screen/shortlist.json", {}) or {}
    ids = [str(s.get("id")) for s in data.get("shortlist", []) if isinstance(s, dict) and s.get("id")]
    ids += rescued_ids(ctx.read("04_SHORTLIST.md"))
    prim = ctx.read_json("primary.json", []) or []
    ids += [str(p) for p in prim if isinstance(p, str)]
    seen, out = set(), []
    for i in ids:
        if i not in seen:
            seen.add(i)
            out.append(i)
    return out


def survivors(ctx):
    if ctx.sim is not None:
        return ["I-%03d" % i for i in range(1, int(ctx.sim.get("survivors", 7)) + 1)]
    if ctx.mode == "proposal":
        return ["I-001"]
    killed = set(ctx.state.get("killed") or [])
    parked = set(ctx.state.get("parked") or [])
    return [i for i in shortlist_ids(ctx) if i not in killed and i not in parked]


def evolved_ids(ctx):
    """The E ideas of 05_EVOLVED.md that have a check (8.2); only those can become finalists."""
    return [b["id"] for b in idea_blocks(ctx.read("05_EVOLVED.md"), "E") if ctx.exists("checks/%s.md" % b["id"])]


def finalist_pool(ctx):
    """Survivors plus the checked E ideas (9.1): what the finalist cut, the more_than_8 predicate and G6 see."""
    surv = survivors(ctx)
    if ctx.sim is not None:
        return surv
    return surv + [e for e in evolved_ids(ctx) if e not in surv]


def screen_scores(ctx):
    """Screen score per idea: every judged idea (screen/shortlist.json `scores`; older files: the shortlist rows).
    An E idea inherits the mean score of the parents named on its `Parents:` line, else the lowest survivor score
    (E ideas are written after the screen, so they have no score of their own)."""
    data = ctx.read_json("screen/shortlist.json", {}) or {}
    out = dict((str(s.get("id")), float(s.get("score") or 0)) for s in data.get("shortlist", [])
               if isinstance(s, dict))
    for k, v in (data.get("scores") or {}).items() if isinstance(data.get("scores"), dict) else ():
        try:
            out[str(k)] = float(v)
        except (TypeError, ValueError):
            pass
    floor = min([out[i] for i in survivors(ctx) if i in out] or [0.0])
    for b in idea_blocks(ctx.read("05_EVOLVED.md"), "E"):
        parents = [out[p] for p in re.findall(r"\bI-\d+\b", b["fields"].get("parents", "")) if p in out]
        out.setdefault(b["id"], sum(parents) / len(parents) if parents else floor)
    return out


def parse_cards(text, ids=None):
    """(order, {id: [non-empty lines]}) of a cards file by the NORMALIZER contract's rule (validate.card_sections): a
    heading '## I-001 - Title' is the card of I-001, and a heading that names no card ID ('## Notes') ends a card and
    is none. ids: the card IDs to look for (default: a heading's leading ID token). A repeated ID keeps its first
    card."""
    from .. import validate
    order, cards = [], {}
    for cid, lines in validate.card_sections(text, ids):
        if cid not in cards:
            order.append(cid)
            cards[cid] = [ln for ln in lines if ln.strip()]
    return order, cards


def canonical_cards(ctx):
    """Rewrite tournament/cards.md as one '## <ID>' card per finalist, in finalist order, read by the contract's rule
    (parse_cards: a title after the heading's ID, a '## Notes' section and text outside the cards are dropped), with
    each 'Title:' line set to the pool title, so one idea ID has one name everywhere (G8a, G8b, 06_TOURNAMENT.md,
    07_TOP.md, 08_DECISION.md, the proposal) and bs.py prepare-tournament ranks exactly the finalists (9.3)."""
    text = ctx.read("tournament/cards.md")
    fin = [str(i) for i in ctx.state.get("finalists") or []]
    order, cards = parse_cards(text, fin or None)
    if not order:
        return False
    titles = idea_lines(ctx)
    blocks = []
    for cid in [i for i in fin if i in cards] or order:
        title = (titles.get(cid) or {}).get("title")
        body = [("Title: %s" % title) if title and re.match(r"^\s*Title\s*:", ln) else ln for ln in cards[cid]]
        blocks.append("\n".join(["## %s" % cid] + body))
    new = "\n\n".join(blocks) + "\n"
    if new == text:
        return False
    ctx.write("tournament/cards.md", new)
    return True


def card_text(ctx, iid):
    order, cards = parse_cards(ctx.read("tournament/cards.md"), [iid])
    if iid in cards:
        return "\n".join(cards[iid])
    return idea_text(ctx, iid)


def tournament_result(ctx):
    data = ctx.read_json("tournament/result.json", None)
    return data if isinstance(data, dict) else {}


def _num(value):
    try:
        return None if value is None or isinstance(value, bool) else float(value)
    except (TypeError, ValueError):
        return None


def ranking(ctx):
    """The tournament ranking (5.7) from tournament/result.json: {"order": [ids, best first], "score": {id: %},
    "method": "bradley-terry" | "raw-fallback" | "debiased (older result)" | "raw", "note": a line to show with the
    ranking ("" when the pair-level ranking stands), "condorcet": id or None}.

    Missing evidence is never read as 0: an older result (no `ranking` block) whose rows do not score every card is
    ranked by raw points for every card (a card without a debiased % was one no neutral judge could score, not a weak
    one, so ranking it after the scored cards would push it out of the red-team set)."""
    res = tournament_result(ctx)
    rk = res.get("ranking") if isinstance(res.get("ranking"), dict) else {}
    rows = [r for r in res.get("debiased") or [] if isinstance(r, dict) and r.get("id") is not None]
    raw = {}
    for r in res.get("raw") or []:
        if isinstance(r, dict) and r.get("id") is not None and _num(r.get("points")) is not None:
            raw[str(r["id"])] = 100.0 * _num(r["points"]) / (_num(r.get("max")) or 1.0)
    if not raw:
        text = ctx.read("tournament/result.md")
        for m in re.finditer(r"^\d+\.\s+([IEQ]-\d+)\s+([\d.]+)", text, re.M):
            raw.setdefault(m.group(1), float(m.group(2)))
    score = dict((str(r["id"]), _num(r.get("pct"))) for r in rows if _num(r.get("pct")) is not None)
    method, note = rk.get("method"), ""
    if method == "raw-fallback":
        note = "ranking fell back to raw points: %s" % (rk.get("reason") or "no bias-free comparison")
    elif not method:
        unscored = sorted(i for i in raw if i not in score)
        if score and not unscored:
            method = "debiased (older result)"
        else:
            why = ("%s without a debiased %% in tournament/result.json" % ", ".join(unscored) if score else
                   "no debiased ranking in tournament/result.json")
            method, score = "raw", dict(raw)
            note = "ranking uses raw tournament points (an older tally: %s)" % why
    order = [str(r["id"]) for r in rows if str(r["id"]) in score] if rk.get("method") else \
        sorted(score, key=lambda i: (-score[i], -raw.get(i, 0.0), i))
    rest = sorted((i for i in raw if i not in score), key=lambda i: (-raw[i], i))
    cw = res.get("condorcet") if isinstance(res.get("condorcet"), dict) else {}
    return {"order": order + rest, "score": score, "method": method, "note": note, "condorcet": cw.get("winner")}


def debiased_pct(ctx):
    """{id: tournament score in percent} for the cards the ranking scored (see ranking)."""
    return ranking(ctx)["score"]


def rank_finalists(ctx, ids, rk=None):
    """ids in tournament order (best first); ids the tournament did not rank go last, by id."""
    order = (rk or ranking(ctx))["order"]
    pos = dict((i, n) for n, i in enumerate(order))
    return sorted(ids, key=lambda i: (pos.get(i, len(pos)), i))


def default_top(ctx, fin, rk=None):
    """The default red-team set (10.1): the top 3 of the ranking, plus the Condorcet winner (beats every finalist
    by pairwise majority) and gut pick #1 when they are outside it; with both outside, the third-ranked idea makes
    room, so the set holds at most 4 ideas."""
    rk = rk or ranking(ctx)
    ranked = rank_finalists(ctx, fin, rk)
    gut = gut_picks(ctx)
    extra = [i for i in dict.fromkeys([rk["condorcet"], gut[0] if gut else None]) if i in fin
             and i not in ranked[:3]]
    return ranked[:2 if len(extra) == 2 else 3] + extra


def suggested_top(ctx, rk=None):
    """The red-team set G7 suggests and 10.1 takes when G7 names none: the first 3 finalists in proposal mode, else
    default_top."""
    fin = ctx.state.get("finalists") or []
    return fin[:3] if ctx.mode == "proposal" else default_top(ctx, fin, rk)


def gut_picks(ctx):
    ans = ((ctx.state.get("gates") or {}).get("G8a") or {}).get("answer") or {}
    return [str(p) for p in (ans.get("picks") or []) if p]


# A red-team file (10.3, 10.3r): redteam/<ID>_<STANCE>_<seat family>.md is a review, the same with .rebuttal.md its
# rebuttal. A fallback writes the original job's out, so the family is always a seat; the adapter's kept
# <out>.failed.md (a failure record) never matches.
REVIEW_FILE_RE = re.compile(r"^([IEQ]-\d+)_(ADVOCATE|CRITIC)_((?:%s)(?:-alt)?)(\.rebuttal)?\.md$"
                            % "|".join(FAMILY_ORDER))


def review_files(ctx, pattern="*_*_*.md"):
    """[(path, match)] of the red-team reviews (never a rebuttal or a failure record) among redteam/<pattern>, sorted."""
    out = []
    for path in sorted(textio.glob_in(ctx.run_dir, "redteam", pattern)):
        m = REVIEW_FILE_RE.match(os.path.basename(path))
        if m and not m.group(4):
            out.append((path, m))
    return out


def review_verdicts(ctx):
    """{idea_id: [verdict line, ...]} from the red-team reviews redteam/<ID>_<stance>_<family>.md."""
    out = {}
    for path, m in review_files(ctx):
        line = final_line(textio.read_text(path))
        out.setdefault(m.group(1), []).append("%s %s (%s): %s" % (m.group(1), m.group(2), m.group(3), line))
    return out


def suggestion(ctx):
    """G8b rule default (6.2): most BACK + BACK IF verdicts, then the tournament ranking, then gut #1."""
    top = ctx.state.get("top") or ctx.state.get("finalists") or []
    if ctx.mode == "proposal" and "I-001" in top:
        return "I-001", "proposal mode: the default choice is your own idea"
    if not top:
        return None, "no finalists"
    verdicts = review_verdicts(ctx)
    rk = ranking(ctx)
    pos = dict((i, n) for n, i in enumerate(rk["order"]))
    gut = gut_picks(ctx)

    def backs(i):
        n = 0
        for v in verdicts.get(i, []):
            if re.search(r"VERDICT:\s*BACK\b", v) and "DON'T" not in v:
                n += 1
        return n

    def key(i):
        return (-backs(i), pos.get(i, len(pos)), 0 if (gut and gut[0] == i) else 1, i)

    best = sorted(top, key=key)[0]
    score = rk["score"].get(best)
    rule = "%d BACK/BACK IF verdicts, tournament %s" % (
        backs(best), ("score %.0f%% (rank %d)" % (score, pos[best] + 1)) if score is not None and best in pos
        else "score n/a (not ranked)")
    return best, rule + ("; " + rk["note"] if rk["note"] else "")


def default_runner(ctx, chosen):
    """The runner-up G8b records when the answer names none: the red-teamed idea (or finalist) other than `chosen`
    with the best tournament score."""
    pct = debiased_pct(ctx)
    rest = [i for i in (ctx.state.get("top") or ctx.state.get("finalists") or []) if i != chosen]
    rest.sort(key=lambda i: (-pct.get(i, 0.0), i))
    return rest[0] if rest else None


def chosen_idea(ctx):
    return (ctx.state.get("choice") or {}).get("idea")


# ================================================================ predicates

PREDICATES = {}


def predicate(name):
    def deco(fn):
        PREDICATES[name] = fn
        return fn
    return deco


@predicate("not_quick")
def _p_not_quick(ctx, arg):
    return ctx.mode != "quick"


@predicate("deep")
def _p_deep(ctx, arg):
    return ctx.mode == "deep"


@predicate("mode_is")
def _p_mode_is(ctx, arg):
    return ctx.mode == arg


@predicate("hands_on")
def _p_hands_on(ctx, arg):
    return ctx.autopilot == "hands-on"


@predicate("full_auto")
def _p_full_auto(ctx, arg):
    return ctx.autopilot == "full-auto"


@predicate("not_full_auto")
def _p_not_full_auto(ctx, arg):
    return ctx.autopilot != "full-auto"


@predicate("has_component")
def _p_has_component(ctx, arg):
    return bool((ctx.state.get("components") or {}).get(arg))


@predicate("host_can_run_skills")
def _p_host_skills(ctx, arg):
    return ctx.host_agent not in ("terminal",)


@predicate("repo_variant")
def _p_repo_variant(ctx, arg):
    return ctx.variant in REPO_VARIANTS and is_repo(ctx)


@predicate("build_type")
def _p_build_type(ctx, arg):
    return ctx.state.get("build_type", "system") == arg


@predicate("step_done")
def _p_step_done(ctx, arg):
    return st.step_state(ctx.state, arg) == "done"


@predicate("step_skipped")
def _p_step_skipped(ctx, arg):
    return st.step_state(ctx.state, arg) == "skipped"


@predicate("s1_engine")
def _p_s1_engine(ctx, arg):
    return ctx.seats.get("s1_engine", "s1f") == arg


@predicate("no_seeds")
def _p_no_seeds(ctx, arg):
    if ctx.sim is not None:
        return not ctx.sim.get("seeds_given", False)
    text = seeds_text(ctx)
    if re.search(r"^[^\w\n]*SKIPPED\b", text, re.M):
        return False
    return not (section(text, "Ideas") or section(text, "Primary idea"))


@predicate("footprint_changed")
def _p_footprint(ctx, arg):
    if ctx.sim is not None:
        return bool(ctx.sim.get("footprint", False))
    return bool((ctx.state.get("facts") or {}).get("footprint_changed"))


@predicate("homogenized_or_gaps")
def _p_homog(ctx, arg):
    rounds = 2 if ctx.mode == "deep" else 1
    done = int((ctx.state.get("counters") or {}).get("gap_rounds", 0))
    if ctx.sim is not None:
        return bool(ctx.sim.get("homogenized", True)) and done < rounds
    if done >= rounds:
        return False
    cov = ctx.read_json("coverage.json", {}) or {}
    if "gap_needed" in cov:  # bs.py map: homogenized, or under 80% of the axis cells covered
        return bool(cov["gap_needed"])
    if cov.get("homogenized") or cov.get("empty"):
        return True
    pool = ctx.read("03_POOL.md")
    return bool(re.search(r"^yes:", section(pool, "HOMOGENIZED"), re.M)) or \
        bool(re.search(r"Empty cells:\s*(?!none)\S", pool))


@predicate("has_round2")
def _p_round2(ctx, arg):
    if ctx.sim is not None:
        return bool(ctx.sim.get("round2", False))
    return bool(section(ctx.read("00b_HUMAN_ROUND2.md"), "Ideas"))


@predicate("evolve_needed")
def _p_evolve(ctx, arg):
    return ctx.mode == "deep" or len(survivors(ctx)) < 6


@predicate("more_than_8")
def _p_more_than_8(ctx, arg):
    return len(finalist_pool(ctx)) > 8


@predicate("k4_candidates")
def _p_k4(ctx, arg):
    if ctx.sim is not None:
        return bool(ctx.sim.get("k4", False))
    return bool(ctx.state.get("k4_candidates"))


@predicate("synthesis_stop")
def _p_synth_stop(ctx, arg):
    if ctx.sim is not None:
        return bool(ctx.sim.get("synthesis_stop", False))
    return bool(re.match(r"^WHOLE-EFFORT:\s*STOP", final_line(ctx.read("07_REDTEAM.md")), re.I))


@predicate("context_proposed")
def _p_context_proposed(ctx, arg):
    if ctx.sim is not None:
        return bool(ctx.sim.get("context_proposed", False))
    return ctx.exists("CONTEXT.proposed.md")


@predicate("fix_requested")
def _p_fix_requested(ctx, arg):
    return bool(ctx.state.get("user_changes"))


@predicate("quick_screen")
def _p_quick_screen(ctx, arg):
    """A quick run that seats screen judges of two vendors: it scores its curated ideas blind (#51)."""
    return ctx.mode == "quick" and seats_mod.quick_screen_ok(ctx.seats)


def eval_when(ctx, when):
    """All entries must hold. Entry syntax: 'name', 'name:arg', '!entry', 'a|b' (any)."""
    for entry in when or []:
        if not _eval_entry(ctx, entry):
            return False
    return True


def _eval_entry(ctx, entry):
    entry = str(entry).strip()
    if "|" in entry:
        return any(_eval_entry(ctx, e) for e in entry.split("|"))
    neg = entry.startswith("!")
    if neg:
        entry = entry[1:]
    name, _, arg = entry.partition(":")
    fn = PREDICATES.get(name)
    if fn is None:
        raise EngineError("pipeline.json uses an unknown predicate: %s" % name)
    val = bool(fn(ctx, arg or None))
    return (not val) if neg else val


# ================================================================ fanouts

FANOUTS = {}
SIM_COUNTS = {}


def fanout(name, sim_count=None):
    """Register a fanout. sim_count only for a fanout whose items come from files an earlier step writes (the
    shortlist, the tournament maps, ...): a simulation (`ub plan`, ETA) cannot build those items."""
    def deco(fn):
        FANOUTS[name] = fn
        if sim_count is not None:
            SIM_COUNTS[name] = sim_count
        return fn
    return deco


def _stub_axes(ctx):
    if ctx.sim is not None:
        return {}  # stub facts only matter to the fake-mode responder, never in a simulation
    ax = axes(ctx)
    return ax or {"Stage": ["first use", "daily use", "renewal"], "Channel": ["app", "email", "in person"]}


def _web_tools(ctx, fam):
    return "web" if ctx.family_web(fam) else "none"


def _gen_item(ctx, sid, template, family, out, prefix, tools="none", vars_=None, minimum=None):
    c = tcontract(template, {"type": "idea-blocks", "prefix": prefix, "min": minimum or 10})
    if c.get("type") == "idea-blocks":
        c["prefix"] = prefix
        if minimum:
            c["min"] = minimum
    return {"id": sid, "template": template, "kind": "generator", "family": family, "tools": tools, "cwd": "empty",
            "out": out, "contract": c, "stub": {"axes": _stub_axes(ctx)}, "vars": dict(vars_ or {}, STRATEGY_ID=prefix),
            "checks": ["seed_leak", "pool_leak"]}


@fanout("single")
def _f_single(ctx, step):
    return [{}]


@fanout("strategies")
def _f_strategies(ctx, step):
    g = ctx.seats.get("generators") or {}
    host = ctx.host_family
    deep = ctx.mode == "deep"
    items = [
        _gen_item(ctx, "S2", "S2-VS", g.get("S2", host), "pool/S2_vs.md", "S2"),
        _gen_item(ctx, "S3", "S3-EDE", g.get("S3", host + "-alt"), "pool/S3_enumerate.md", "S3",
                  vars_={"TITLES": "100" if deep else "40"}),
        _gen_item(ctx, "S4", "S4-TRANSFER", g.get("S4", host), "pool/S4_transfer.md", "S4",
                  tools=_web_tools(ctx, g.get("S4", host))),
    ]
    if ctx.variant == "research":
        items.append(_gen_item(ctx, "S5", "S5-RESEARCH", g.get("S5", host + "-alt"), "pool/S5_research.md", "S5"))
    else:
        items.append(_gen_item(ctx, "S5", "S5-OPS", g.get("S5", host + "-alt"), "pool/S5_operators.md", "S5",
                               vars_={"SOFTWARE_OP": "yes" if ctx.variant == "software" else "no"}))
    if deep:
        lenses = ["Inversion", "Remote analogy", "Constraint flip", "Assumption removal", "Audience shift",
                  "Subtraction"]
        for i, lens in enumerate(lenses, 1):
            lid = "L%d" % i
            items.append({"id": lid, "template": "LENS", "kind": "generator", "family": g.get(lid, host + "-alt"),
                          "tools": "none", "cwd": "empty", "out": "pool/%s.json" % lid,
                          "contract": tcontract("LENS", {"type": "json", "schema": "prompts/lens.schema.json"}),
                          "schema": "prompts/lens.schema.json",
                          "stub": {"axes": _stub_axes(ctx)}, "vars": {"LENS": "%s %s" % (lid, lens),
                                                                       "STRATEGY_ID": lid},
                          "checks": ["seed_leak", "pool_leak"]})
    for it in items:
        it["fallback"] = _fallbacks(ctx, it["family"])
    return items


def _fallbacks(ctx, family):
    """Fallback labels after a job's chain fails: <family>-alt, then the host family (never the same label)."""
    out = []
    base = base_family(family)
    if not is_alt(family):
        out.append(base + "-alt")
    if base != ctx.host_family:
        out.append(ctx.host_family)
    return [f for f in out if f != family]


@fanout("s1f")
def _f_s1f(ctx, step):
    it = _gen_item(ctx, None, "S1F", ctx.seats.get("generators", {}).get("S1", ctx.host_family),
                   "pool/S1_frames.md", "S1")
    it["fallback"] = _fallbacks(ctx, it["family"])
    return [it]


@fanout("quick_gen")
def _f_quick_gen(ctx, step):
    host = ctx.host_family
    others = ctx.seats.get("others") or []
    items = [_gen_item(ctx, "QA", "QUICK-GEN", host, "pool/QA_quick.md", "QA")]
    items.append(_gen_item(ctx, "QB", "QUICK-GEN", others[0] if others else host + "-alt", "pool/QB_quick.md", "QB"))
    for it in items:
        it["checks"] = ["pool_leak"]  # QUICK-GEN may restate nothing, but it must see the user's brief
        it["fallback"] = _fallbacks(ctx, it["family"])
    return items


@fanout("ground")
def _f_ground(ctx, step):
    fam = (ctx.seats.get("researcher") or [ctx.host_family])[0]
    return [_ground_item(ctx, None, fam, "02_CONTEXT.md")]


@fanout("ground2")
def _f_ground2(ctx, step):
    rs = ctx.seats.get("researcher") or []
    fam = rs[1] if len(rs) > 1 else ctx.host_family + "-alt"
    return [_ground_item(ctx, None, fam, "ground/02_CONTEXT.second.md")]


def _ground_item(ctx, sid, fam, out):
    tools = _web_tools(ctx, fam)
    cwd, repo_root = "empty", None
    if repo_access(ctx, fam):
        tools = "read+web" if tools == "web" else "read"
        cwd, repo_root = "repo", ctx.state.get("project_dir")
    c = tcontract("P-GROUND", {"type": "sections", "headings": ["## A. FACTS", "## B. LANDSCAPE",
                                                                 "## C. SEARCH BOUNDARY"]})
    if ctx.variant in REPO_VARIANTS:
        heads = list(c.get("headings") or [])
        c["headings"] = heads[:1] + ["## A2"] + heads[1:]
    return {"id": sid, "template": "P-GROUND", "kind": "researcher", "family": fam, "tools": tools, "cwd": cwd,
            "repo_root": repo_root, "out": out, "contract": c,
            "checks": ["seed_leak"], "fallback": _fallbacks(ctx, fam),
            "vars": {"WEB": "yes" if "web" in tools else "no"}}


def pool_aliases(ctx):
    """Alias IDs present in the pool and seeds (the curator stub facts)."""
    aliases = []
    if ctx.sim is not None:
        return aliases, []
    for path in sorted(textio.glob_in(ctx.run_dir, "pool", "*.md")):
        for b in idea_blocks(textio.read_text(path)):
            aliases.append(b["id"])
    for path in sorted(textio.glob_in(ctx.run_dir, "pool", "L*.json")):
        lid = os.path.splitext(os.path.basename(path))[0]
        data = ctx.read_json("pool/" + os.path.basename(path), {}) or {}
        n = 0
        for tier in data.get("tiers") or []:
            for _ in (tier or {}).get("responses") or []:
                n += 1
                aliases.append("%s-%02d" % (lid, n))
    for path in sorted(textio.glob_in(ctx.run_dir, "pool", "IMPORT_*.md")):
        for n, b in enumerate(idea_blocks(textio.read_text(path)), 1):
            aliases.append("IMP-%02d" % n)
    seeds = seeds_text(ctx)
    for n, _ in enumerate(_seed_items(section(seeds, "Ideas")), 1):
        aliases.append("H-%02d" % n)
    prim = []
    for n, _ in enumerate(_seed_items(section(seeds, "Primary idea")), 1):
        aliases.append("HP-%02d" % n)
        prim.append("HP-%02d" % n)
    for n, _ in enumerate(_seed_items(section(ctx.read("00b_HUMAN_ROUND2.md"), "Ideas")), 1):
        aliases.append("H2-%02d" % n)
    return aliases, prim


def _seed_items(body):
    out = []
    for ln in (body or "").split("\n"):
        s = re.sub(r"^\s*(?:[-*]|\d+[.)])\s*", "", ln).strip()
        if s and not s.startswith("<") and not s.lower().startswith("skipped"):
            out.append(s)
    return out


def seeds_bundle(ctx):
    """Every human seed file inlined under a '--- FILE: <name> ---' line (the curator is the only job that sees
    them). A skipped seeds file is reported as such."""
    parts = []
    paths = sorted(textio.glob_in(ctx.run_dir, "00_HUMAN_SEEDS*.md"))
    if os.path.exists(ctx.path("00b_HUMAN_ROUND2.md")):
        paths.append(ctx.path("00b_HUMAN_ROUND2.md"))
    for path in paths:
        text = textio.read_text(path).strip()
        if text:
            parts.append("--- FILE: %s ---\n%s" % (os.path.basename(path), text))
    return "\n\n".join(parts) or "(no human seed files)"


def pool_bundle(ctx):
    """Every pool file inlined under a '--- FILE: pool/<name> ---' line (curator jobs only)."""
    parts = []
    for path in sorted(textio.glob_in(ctx.run_dir, "pool", "*")):
        name = os.path.basename(path)
        if name.startswith("_") or not os.path.isfile(path) or name.endswith((".meta.json", ".failed.md")):
            continue
        parts.append("--- FILE: pool/%s ---\n%s" % (name, textio.read_text(path).strip()))
    return "\n\n".join(parts) or "(the pool is empty)"


def _curator_item(ctx, sid, out, extra_vars=None):
    aliases, prim = pool_aliases(ctx)
    return {"id": sid, "template": "CURATOR", "kind": "curator", "family": ctx.host_family, "tools": "none",
            "cwd": "empty", "out": out,
            "contract": tcontract("CURATOR", {"type": "json", "schema": schema_ref("merges")}),
            "schema": schema_ref("merges"),
            "stub": {"aliases": aliases, "axes": _stub_axes(ctx), "primary_aliases": prim},
            "vars": dict(extra_vars or {}), "fallback": _fallbacks(ctx, ctx.host_family)}


@fanout("curator")
def _f_curator(ctx, step):
    return [_curator_item(ctx, None, "merges.raw.%s.json" % step["id"])]


def gap_cells(ctx, limit=6):
    cov = ctx.read_json("coverage.json", {}) or {}
    cells = [list(c) for c in (cov.get("empty") or []) if isinstance(c, (list, tuple))]
    if not cells:
        text = ctx.read("03_POOL.md")
        m = re.search(r"^Empty cells:\s*(.+)$", text, re.M)
        if m and m.group(1).strip().lower() != "none":
            cells = [[v.strip() for v in c.split(" / ")] for c in m.group(1).split(";") if c.strip()]
    marked = ((ctx.state.get("gates") or {}).get("G3") or {}).get("answer") or {}
    for c in marked.get("cells") or []:
        cell = [v.strip() for v in re.split(r"\s*/\s*", str(c))] if isinstance(c, str) else list(c)
        if cell not in cells:
            cells.append(cell)
    single = [list(c) for c in (cov.get("single") or []) if isinstance(c, (list, tuple))]

    def adjacent(c):
        return sum(1 for s in single if sum(1 for a, b in zip(c, s) if a != b) == 1)

    cells.sort(key=lambda c: -adjacent(c))
    return cells[:limit]


@fanout("gap_cells", lambda ctx: (2, 8) if ctx.mode == "deep" else (2, 7))
def _f_gap(ctx, step):
    cells = gap_cells(ctx)
    start = int((ctx.state.get("counters") or {}).get("gap_prefix", 0))
    fams = seats_mod.gap_families(ctx.seats, len(cells) + start)[start:]
    items = []
    for i, cell in enumerate(cells):
        n = start + i + 1
        prefix = "G%d" % n
        it = _gen_item(ctx, prefix, "GAP", fams[i], "pool/%s_gap.md" % prefix, prefix,
                       vars_={"CELL": " | ".join(cell)})
        it["contract"] = tcontract("GAP", {"type": "text", "min_chars": 20})
        it["fallback"] = _fallbacks(ctx, it["family"])
        items.append(it)
    rstart = int((ctx.state.get("counters") or {}).get("reopen_prefix", 0))
    for j, fam in enumerate(seats_mod.reopen_families(ctx.seats, ctx.mode)):
        prefix = "R%d" % (rstart + j + 1)
        it = _gen_item(ctx, prefix, "REOPEN", fam, "pool/%s_reopen.md" % prefix, prefix)
        it["fallback"] = _fallbacks(ctx, fam)
        items.append(it)
    ctx.state.setdefault("counters", {})["gap_round_items"] = [it["id"] for it in items]
    return items


def _judge_fallbacks(ctx, family, seated):
    """Fallbacks for a judge seat: <family>-alt, then the families that hold no judge seat in this step, then the
    host. A family that already judges comes last: bs.py counts its answer as that family's one vote (5.7)."""
    taken = set(base_family(f) for f in seated)
    out = [] if is_alt(family) else [base_family(family) + "-alt"]
    out += [f for f in ctx.seats.get("families") or [] if base_family(f) not in taken]
    if base_family(family) != ctx.host_family:
        out.append(ctx.host_family)
    return [f for f in dict.fromkeys(out) if f != family]


@fanout("screen_judges")
def _f_screen(ctx, step):
    ids = [ln.split("|")[0].strip() for ln in ctx.read("screen/ideas.md").split("\n") if ln.strip()]
    items = []
    seated = ctx.seats.get("screen_judges") or [ctx.host_family]
    for fam in seated:
        items.append({"id": fam, "template": None, "prompt_file": "screen/%s.prompt.md" % fam, "kind": "judge",
                      "family": fam, "tools": "none", "cwd": "empty", "out": "screen/%s.out.json" % fam,
                      "contract": {"type": "json", "schema": "screen/screen.schema.json",
                                   "cover": {"array": "scores", "key": "id", "ids": ids}},
                      "schema": "screen/screen.schema.json", "checks": ["origin_label"],
                      "fallback": _judge_fallbacks(ctx, fam, seated)})
    return items


# CHECK section 5 (software and growth): asked, and required by the contract, only of a checker whose prompts may carry
# code, so another vendor with privacy code = no is never asked to cite the repository (#63)
CODEBASE_FIT = ("## 5. Codebase fit\n"
                "Does the product already do this (cite file:line)? Does it conflict with the current architecture, "
                "CONCEPTS.md, feature flags or analytics? Which files would change?")


def _check_item(ctx, iid, out=None):
    orig = origins(ctx).get(iid, "?")
    fam, same = seats_mod.checker_for(ctx.seats, vendor_of(orig) if orig not in ("human", "human-mixed",
                                                                                  "ai-mixed", "?") else None)
    tools = _web_tools(ctx, fam)
    cwd, repo_root = "empty", None
    c = tcontract("CHECK", {"type": "sections", "headings": ["## 1", "## 2", "## 3", "## 4"],
                            "final_line": CHECK_FINAL})
    heads = list(c.get("headings") or [])
    # section 5 only where the code is known: a git repository (in a folder without one no job reads code, so the
    # checker could cite no file:line) and a checker whose prompts may carry code (6.8)
    fit = ctx.variant in REPO_VARIANTS and is_repo(ctx) and not privacy_mod.needs_code_strip(ctx.state, fam)
    if fit:
        heads.append("## 5. Codebase fit")
    if repo_access(ctx, fam):
        tools = "read+web" if tools == "web" else "read"
        cwd, repo_root = "repo", ctx.state.get("project_dir")
    return {"id": iid, "template": "CHECK", "kind": "checker", "family": fam, "tools": tools, "cwd": cwd,
            "repo_root": repo_root, "out": out or "checks/%s.md" % iid,
            "contract": dict(c, headings=heads),
            "stub": {"idea_id": iid}, "vars": {"IDEA_ID": iid, "WEB": "yes" if "web" in tools else "no",
                                               "CODEBASE_FIT": CODEBASE_FIT if fit else ""},
            "fallback": _fallbacks(ctx, fam)}


@fanout("shortlist", lambda ctx: (3, 3) if ctx.mode == "proposal" else (4, 12))
def _f_shortlist(ctx, step):
    if ctx.mode == "proposal":
        ids = ["I-001"] + [b["id"] for b in idea_blocks(ctx.read("05_EVOLVED.md"), "E")]
    else:
        ids = shortlist_ids(ctx)
    return [_check_item(ctx, i) for i in ids]


@fanout("evolved", lambda ctx: (4, 5))
def _f_evolved(ctx, step):
    return [_check_item(ctx, b["id"]) for b in idea_blocks(ctx.read("05_EVOLVED.md"), "E")]


def _tp_count(ctx):
    n = len(ctx.seats.get("tournament_judges") or [1, 2]) * 2
    if ctx.mode == "deep":
        return (n, n * 15)
    return (n, n)


@fanout("tournament_prompts", _tp_count)
def _f_tournament(ctx, step):
    items = []
    for mp in sorted(textio.glob_in(ctx.run_dir, "tournament", "*.map.json")):
        base = os.path.basename(mp)[:-len(".map.json")]
        meta = ctx.read_json("tournament/%s.map.json" % base, {}) or {}
        fam = meta.get("family") or base.split("_")[0]
        pairs = sorted((meta.get("pairs") or {}).keys())
        items.append({"id": base, "template": None, "prompt_file": "tournament/%s.prompt.md" % base, "kind": "judge",
                      "family": fam, "tools": "none", "cwd": "empty", "out": "tournament/%s.out.json" % base,
                      "contract": {"type": "json", "schema": "tournament/verdicts.schema.json",
                                   "cover": {"array": "verdicts", "key": "pair_id", "ids": pairs}},
                      "schema": "tournament/verdicts.schema.json", "checks": ["origin_label"],
                      "fallback": _judge_fallbacks(ctx, fam, ctx.seats.get("tournament_judges") or [fam])})
    return items


@fanout("redteam_pairs", lambda ctx: (6, 8))
def _f_redteam(ctx, step):
    items = []
    for i, iid in enumerate(ctx.state.get("top") or []):
        adv, crit = seats_mod.redteam_pair(ctx.seats, i)
        for stance, fam in (("ADVOCATE", adv), ("CRITIC", crit)):
            items.append({"id": "%s_%s" % (iid, stance), "template": "REVIEWER", "kind": "reviewer", "family": fam,
                          "tools": "none", "cwd": "empty",
                          "out": "redteam/%s_%s_%s.md" % (iid, stance, fam),
                          "contract": tcontract("REVIEWER", {"type": "sections", "headings": [
                              "## 1", "## 2", "## 3", "## 4", "## 5"], "final_line": REVIEW_FINAL}),
                          "stub": {"stance": stance, "idea_id": iid},
                          "vars": {"STANCE": stance, "IDEA_ID": iid}, "fallback": _fallbacks(ctx, fam)})
    return items


def other_review_text(text):
    """Sections 3 and 4 of the other reviewer's review (the REBUTTAL input); the whole text when absent."""
    parts = sections_by_prefix(text, ["3", "4"])
    return parts or text


@fanout("rebuttals", lambda ctx: (6, 8))
def _f_rebuttal(ctx, step):
    items = []
    for _path, m in review_files(ctx):
        iid, stance, fam = m.group(1), m.group(2), m.group(3)
        other = "CRITIC" if stance == "ADVOCATE" else "ADVOCATE"
        others = [p for p, _m in review_files(ctx, "%s_%s_*.md" % (iid, other))]
        if not others:
            continue
        items.append({"id": "%s_%s" % (iid, stance), "template": "REBUTTAL", "kind": "reviewer", "family": fam,
                      "tools": "none", "cwd": "empty", "out": "redteam/%s_%s_%s.rebuttal.md" % (iid, stance, fam),
                      "contract": tcontract("REBUTTAL", {"type": "text", "min_chars": 20}),
                      "vars": {"STANCE": stance, "IDEA_ID": iid,
                               "OTHER_REVIEW": other_review_text(textio.read_text(others[0]))},
                      "fallback": _fallbacks(ctx, fam)})
    return items


def archetype_text(ctx, letter, all_letters):
    if ctx.variant in REPO_VARIANTS and letter in SOFTWARE_ARCHETYPES:
        return SOFTWARE_ARCHETYPES[letter]
    if letter == "B":
        return archetype_b(ctx)
    if letter == "C":
        others = [archetype_short(ctx, x) for x in all_letters if x != "C"]
        return ARCHETYPE_TEXT["C"].format(others="; ".join(others) or "boring by default")
    return ARCHETYPE_TEXT.get(letter, ARCHETYPE_TEXT["A"])


def archetype_id(ctx, letter):
    """The ub-choices key of ARCH-CANDIDATE for an archetype letter (7.3 rules)."""
    if ctx.variant in REPO_VARIANTS and letter in SOFTWARE_ARCHETYPES:
        return "%s-software" % letter
    if letter == "B":
        b = archetype_b(ctx)
        if b.startswith("Local-first"):
            return "B-local-first"
        if b.startswith("Buy-and-integrate"):
            return "B-buy"
        return "B-event"
    return letter if letter in ("A", "C", "D") else "A"


def archetype_short(ctx, letter):
    if ctx.variant in REPO_VARIANTS and letter in SOFTWARE_ARCHETYPES:
        return SOFTWARE_ARCHETYPES[letter]
    if letter == "B":
        return archetype_b(ctx).split(":")[0]
    return {"A": "Boring by default (modular monolith on managed services)", "D": "Cost-minimal",
            "C": "Contrarian"}.get(letter, letter)


def archetype_b(ctx):
    brief = (ctx.read("10_ARCHITECTURE/00_BRIEF.md") + "\n" + frame_text(ctx)).lower()
    hard = section(frame_text(ctx), "Hard constraints").lower()
    if re.search(r"\b(pii|on-prem|on prem|offline|data residency)\b", hard):
        return "Local-first / offline-first"
    if re.search(r"budget[^\n]{0,40}\blow\b|\bsolo\b", brief):
        return "Buy-and-integrate: SaaS plus glue code"
    return "Event-driven / serverless: managed functions, queues and events; scale to zero"


def drivers(ctx):
    data = ctx.read_json("10_ARCHITECTURE/drivers.json", {}) or {}
    return data if isinstance(data, dict) else {}


@fanout("arch_authors")
def _f_arch_authors(ctx, step):
    authors = ctx.seats.get("arch_authors") or [ctx.host_family]
    arche = ctx.seats.get("arch_archetypes") or {}
    letters = [arche.get("%d" % (i + 1), "A") for i in range(len(authors))]
    d = drivers(ctx)
    qas_ids = [q.get("id") for q in d.get("qas") or [] if isinstance(q, dict)]
    hc_ids = [h.get("id") for h in d.get("hard_constraints") or [] if isinstance(h, dict)]
    items = []
    for i, fam in enumerate(authors):
        n = "%d" % (i + 1)
        letter = letters[i]
        tools, cwd, repo_root = _writer_tools(ctx, fam)
        items.append({"id": "c%s" % n, "template": "ARCH-CANDIDATE", "kind": "arch-author", "family": fam,
                      "tools": tools, "cwd": cwd, "repo_root": repo_root,
                      "out": "10_ARCHITECTURE/candidates/%s.md" % n,
                      "contract": tcontract("ARCH-CANDIDATE", {"type": "sections", "headings": ARCH_HEADINGS,
                                                               "json_tail": schema_ref("arch-candidate")}),
                      "schema": schema_ref("arch-candidate"),
                      "stub": {"qas_ids": qas_ids, "hc_ids": hc_ids},
                      "vars": {"ARCHETYPE": archetype_text(ctx, letter, letters),
                               "ARCHETYPE_ID": archetype_id(ctx, letter),
                               "OTHER_ARCHETYPES": "; ".join(archetype_short(ctx, x) for x in letters if x != letter)},
                      "fallback": _fallbacks(ctx, fam), "meta": {"archetype": letter, "n": n}})
    return items


def arch_labels(ctx):
    m = ctx.read_json("10_ARCHITECTURE/candidates/map.json", {}) or {}
    return sorted(m.keys())


def arch_criteria(ctx):
    d = drivers(ctx)
    qg = [q.get("id") for q in d.get("quality_goals") or [] if isinstance(q, dict) and q.get("id")]
    return qg + [c for c, _ in FIXED_ARCH_CRITERIA]


@fanout("arch_judges")
def _f_arch_judges(ctx, step):
    labels = arch_labels(ctx)
    items = []
    for fam in ctx.seats.get("arch_judges") or [ctx.host_family]:
        items.append({"id": fam, "template": "ARCH-JUDGE", "kind": "arch-judge", "family": fam, "tools": "none",
                      "cwd": "empty", "out": "10_ARCHITECTURE/review/judge_%s.out.json" % fam,
                      "contract": tcontract("ARCH-JUDGE", {"type": "json", "schema": schema_ref("arch-judge")},
                                            cover={"array": "candidates", "key": "label", "ids": labels,
                                                   "each": {"array": "scores", "key": "criterion",
                                                            "ids": arch_criteria(ctx), "loose": True}}),
                      "schema": schema_ref("arch-judge"),
                      "stub": {"labels": labels, "criteria": arch_criteria(ctx)},
                      "checks": ["origin_label"], "fallback": _fallbacks(ctx, fam)})
    return items


def arch_writer(ctx):
    return ctx.seats.get("arch_writer") or (ctx.state.get("choice") or {}).get("arch_family") or ctx.host_family


def chosen_candidate_json(ctx):
    label = (ctx.state.get("choice") or {}).get("arch")
    m = ctx.read_json("10_ARCHITECTURE/candidates/map.json", {}) or {}
    info = m.get(label) or {}
    n = info.get("n")
    if not n:
        return {}
    data = ctx.read_json("10_ARCHITECTURE/candidates/%s.json" % n, {}) or {}
    return data if isinstance(data, dict) else {}


def _pkg_stub(ctx):
    if ctx.sim is not None:
        return {}
    cand = chosen_candidate_json(ctx)
    d = drivers(ctx)
    containers = [c for c in cand.get("containers") or [] if isinstance(c, dict)]
    return {"containers": containers,
            "qg_ids": [q.get("id") for q in d.get("quality_goals") or [] if isinstance(q, dict)],
            "ext_ids": [e.get("id") for e in (d.get("context") or {}).get("external") or [] if isinstance(e, dict)],
            "r_ids": risk_ids(ctx)}


def risk_ids(ctx):
    dec = ctx.read_json("10_ARCHITECTURE/decisions.json", {}) or {}
    ids = [r.get("id") for r in dec.get("risks") or [] if isinstance(r, dict) and r.get("id")]
    return ids or ["R-001", "R-002", "R-003"]


def _writer_tools(ctx, fam):
    if repo_access(ctx, fam):
        return "read", "repo", ctx.state.get("project_dir")
    return "none", "empty", None


def _files_item(ctx, sid, template, kind, fam, root, allowed, required, per_file=None, status=True, stub=None,
                vars_=None, raw_name=None, repo_ok=True, exact=False, rules=None):
    """A FILE-protocol job. Writers and fixers read the repo where repo_access allows it, unless repo_ok is False
    (proposal writers work from their evidence packs only). exact: `allowed` replaces the manifest's allowed list
    (the fixers' exact file names). rules: per-file rules that replace the manifest's (the fixers' writer_rules)."""
    repo = repo_ok and kind in ("writer", "fixer")
    tools, cwd, repo_root = _writer_tools(ctx, fam) if repo else ("none", "empty", None)
    raw = raw_name or sid or template
    default = {"type": "files", "allowed": allowed, "required": required, "status_trailer": bool(status)}
    if per_file:
        default["per_file"] = per_file
    override = {"allowed": list(allowed)} if exact else {}
    if rules:
        override["per_file"] = rules
    contract = tcontract(template, default, **override)
    allowed = list(contract.get("allowed") or allowed)
    root = split_root(template, root)
    status_out = "%s/_raw/%s.status.json" % (root, raw) if root != "." else "frame/_raw/%s.status.json" % raw
    return {"id": sid, "template": template, "kind": kind, "family": fam, "tools": tools, "cwd": cwd,
            "repo_root": repo_root,
            "out": ("%s/_raw/%s.out.md" % (root, raw)) if root != "." else "frame/_raw/%s.out.md" % raw,
            "contract": contract, "split": {"root": root, "allowed": allowed, "status_out": status_out},
            "stub": stub or {}, "vars": dict(vars_ or {}, ALLOWED_FILES=", ".join(allowed)),
            "fallback": _fallbacks(ctx, fam)}


FRAME_HEADINGS = ["## Job statement", "## Problem", "## Criteria", "## Axes"]


@fanout("frame_files")
def _f_frame_files(ctx, step):
    tpl = (step.get("job") or {}).get("template") or "FRAME-FINAL"  # 2.1f drafts (FRAME-DRAFT)
    it = _files_item(ctx, None, tpl, "frame", ctx.host_family, ".", ["01_FRAME.md", "criteria.json"],
                     ["01_FRAME.md", "criteria.json"], per_file={"01_FRAME.md": {"headings": FRAME_HEADINGS}},
                     status=True, raw_name=step["id"])
    if ctx.variant in REPO_VARIANTS:
        pf = (it["contract"].get("per_file") or {}).get("01_FRAME.md") or {}
        heads = list(pf.get("headings") or [])
        if "## Domain language" not in heads:
            k = next((i + 1 for i, h in enumerate(heads) if h.startswith("## Kill condition")), len(heads))
            heads.insert(k, "## Domain language")
            pf["headings"] = heads
    it["checks"] = ["seed_leak"]
    it["stub"] = {"axes": _stub_axes(ctx)}
    return [it]


@fanout("arch_structure")
def _f_arch_structure(ctx, step):
    fam = arch_writer(ctx)
    allowed = ["chosen/containers.md", "chosen/runtime.md", "chosen/data-model.md", "chosen/api.md",
               "chosen/api/openapi.yaml", "chosen/api/cli.md"]
    per = {"chosen/containers.md": {"headings": ["## Containers", "## How each quality goal is met"],
                                    "mermaid": ["flowchart"]},
           "chosen/runtime.md": {"headings": ["## F-"], "mermaid": ["sequenceDiagram"]},
           "chosen/data-model.md": {"headings": ["## Entities"], "mermaid": ["erDiagram"]}}
    return [_files_item(ctx, None, "ARCH-PACKAGE-STRUCTURE", "writer", fam, "10_ARCHITECTURE", allowed,
                        ["chosen/containers.md", "chosen/runtime.md", "chosen/data-model.md", "chosen/api.md"],
                        per_file=per, stub=_pkg_stub(ctx), raw_name=step["id"])]


@fanout("arch_package_lite")
def _f_arch_lite(ctx, step):
    fam = arch_writer(ctx)
    allowed = ["chosen/containers.md", "chosen/data-model.md", "decisions.json"]
    per = {"chosen/containers.md": {"headings": ["## Containers", "## How each quality goal is met"],
                                    "mermaid": ["flowchart"]},
           "chosen/data-model.md": {"headings": ["## Entities"], "mermaid": ["erDiagram"]}}
    return [_files_item(ctx, None, "ARCH-PACKAGE-LITE", "writer", fam, "10_ARCHITECTURE", allowed, allowed,
                        per_file=per, stub=_pkg_stub(ctx), raw_name=step["id"])]


@fanout("arch_parallel")
def _f_arch_parallel(ctx, step):
    fam = arch_writer(ctx)
    allowed = ["chosen/deployment.md", "chosen/security-privacy.md", "chosen/cost-model.md", "chosen/deferred.md"]
    per = {"chosen/cost-model.md": {"headings": ["## Assumptions", "## Sensitivity"]}}
    crosscut = _files_item(ctx, "crosscut", "ARCH-PACKAGE-CROSSCUT", "writer", fam, "10_ARCHITECTURE", allowed,
                           allowed, per_file=per, stub=_pkg_stub(ctx), raw_name=step["id"])
    dec = {"id": "decisions", "template": "ARCH-DECISIONS", "kind": "writer", "family": fam, "tools": "none",
           "cwd": "empty", "out": "10_ARCHITECTURE/decisions.json",
           "contract": {"type": "json", "schema": schema_ref("arch-decisions")},
           "schema": schema_ref("arch-decisions"), "stub": _pkg_stub(ctx), "fallback": _fallbacks(ctx, fam)}
    sv_fam = seats_mod.stack_verify_family(ctx.seats, fam)
    sv = {"id": "stack", "template": "STACK-VERIFY", "kind": "researcher", "family": sv_fam,
          "tools": _web_tools(ctx, sv_fam), "cwd": "empty", "out": "10_ARCHITECTURE/stack.json",
          "contract": {"type": "json", "schema": schema_ref("stack-verify")}, "schema": schema_ref("stack-verify"),
          "vars": {"WEB": "yes" if ctx.family_web(sv_fam) else "no"}, "fallback": _fallbacks(ctx, sv_fam)}
    return [crosscut, dec, sv]


def review_lenses(ctx):
    if ctx.state.get("build_type") == "approach":
        return ["L2"]
    return ["L1", "L2", "L3", "L4"] if ctx.mode == "deep" else ["L1", "L2"]


@fanout("review_lenses")
def _f_review(ctx, step):
    writer = arch_writer(ctx)
    lenses = review_lenses(ctx)
    fams = seats_mod.review_lens_families(ctx.seats, writer, lenses)
    items = []
    for lens in lenses:
        fam = fams[lens]
        tools = _web_tools(ctx, fam) if lens == "L1" else "none"
        items.append({"id": lens, "template": "ARCH-REVIEW", "kind": "reviewer", "family": fam, "tools": tools,
                      "cwd": "empty", "out": "10_ARCHITECTURE/review/%s_%s.json" % (lens, fam),
                      "contract": tcontract("ARCH-REVIEW", {"type": "json", "schema": schema_ref("findings")}),
                      "schema": schema_ref("findings"),
                      "vars": {"REVIEW_LENS": lens}, "fallback": _fallbacks(ctx, fam)})
    return items


# The templates that write what ARCH-FIX / PROPOSAL-FIX rewrite: a fixer prints a file whole, so the file keeps its
# writer's per-file rules (headings, diagram types) and a quoted FILE block without them is refused (#40).
ARCH_WRITERS = ("ARCH-PACKAGE-STRUCTURE", "ARCH-PACKAGE-LITE", "ARCH-PACKAGE-CROSSCUT")
PROPOSAL_WRITERS = ("PROPOSAL-A", "PROPOSAL-B", "PROPOSAL-C", "PROPOSAL-LITE", "EXEC-ONEPAGER", "PRFAQ")


def writer_rules(templates, files):
    """{file: per-file rules} for `files` from the manifest contracts of the templates that write them (the first
    template that names a file wins)."""
    out = {}
    for t in templates:
        for rel, rules in (tcontract(t).get("per_file") or {}).items():
            if rel in files and rel not in out and isinstance(rules, dict):
                out[rel] = rules
    return out


# The files a fixer may rewrite, exactly (#40): a wildcard would let a quoted '=== FILE: sections/99.md ===' after a
# quoted END FILE write a stray file; with exact names that path fails the allowed check and gets a repair call.
ARCH_FIX_FILES = ["chosen/containers.md", "chosen/runtime.md", "chosen/data-model.md", "chosen/api.md",
                  "chosen/api/openapi.yaml", "chosen/api/cli.md", "chosen/deployment.md", "chosen/security-privacy.md",
                  "chosen/cost-model.md", "chosen/deferred.md", "decisions.json", "review/resolution.md"]


@fanout("arch_fix")
def _f_arch_fix(ctx, step):
    fam = arch_writer(ctx)
    return [_files_item(ctx, None, "ARCH-FIX", "fixer", fam, "10_ARCHITECTURE", list(ARCH_FIX_FILES),
                        ["review/resolution.md"], stub=_pkg_stub(ctx), raw_name=step["id"], exact=True,
                        rules=writer_rules(ARCH_WRITERS, ARCH_FIX_FILES))]


@fanout("approach")
def _f_approach(ctx, step):
    return [_files_item(ctx, None, "APPROACH", "writer", ctx.host_family, "10_ARCHITECTURE", ["approach.md"],
                        ["approach.md"], raw_name=step["id"])]


def _proposal_stub(ctx, secs):
    if ctx.sim is not None:
        return {}
    heads = dict(PROPOSAL_SECTIONS)
    adrs = [os.path.basename(p)[:4] for p in textio.glob_in(ctx.run_dir, "10_ARCHITECTURE", "adr", "*.md")]
    src = ctx.read_json("sources.json", {}) or {}
    return {"sections": [heads[s] for s in secs if s in heads], "adr_numbers": sorted(adrs), "r_ids": risk_ids(ctx),
            "source_ids": sorted(src.keys()) if isinstance(src, dict) else []}


def _section_files(secs):
    return ["sections/%s.md" % s for s in secs]


@fanout("proposal_parts")
def _f_proposal_parts(ctx, step):
    fam = (ctx.seats.get("proposal") or {}).get("drafter") or ctx.host_family
    heads = dict(PROPOSAL_SECTIONS)
    items = []
    for part in ("A", "B", "C"):
        secs = PROPOSAL_PARTS[part]
        files = _section_files(secs)
        per = dict((f, {"headings": [_section_heading(ctx, s, heads)]}) for f, s in zip(files, secs))
        items.append(_files_item(ctx, part, "PROPOSAL-%s" % part, "writer", fam, "11_PROPOSAL", files, files,
                                 per_file=per, stub=_proposal_stub(ctx, secs),
                                 raw_name="%s-%s" % (step["id"], part),
                                 vars_={"PACK": "PACK_%s" % part}, repo_ok=False))
    return items


def _section_heading(ctx, s, heads):
    if s == "06" and ctx.state.get("build_type") == "approach":
        return "## 6. Approach"
    return heads[s]


@fanout("proposal_lite")
def _f_proposal_lite(ctx, step):
    fam = (ctx.seats.get("proposal") or {}).get("drafter") or ctx.host_family
    heads = dict(PROPOSAL_SECTIONS)
    files = _section_files(LITE_SECTIONS) + ["ONE-PAGER.md"]
    per = dict(("sections/%s.md" % s, {"headings": [_section_heading(ctx, s, heads)]}) for s in LITE_SECTIONS)
    per["ONE-PAGER.md"] = {"headings": ONEPAGER_HEADINGS}
    it = _files_item(ctx, None, "PROPOSAL-LITE", "writer", fam, "11_PROPOSAL", files, files, per_file=per,
                     stub=_proposal_stub(ctx, LITE_SECTIONS), raw_name=step["id"], repo_ok=False)
    return [it]


@fanout("onepager")
def _f_onepager(ctx, step):
    fam = (ctx.seats.get("proposal") or {}).get("drafter") or ctx.host_family
    files = ["sections/01.md", "ONE-PAGER.md"]
    per = {"sections/01.md": {"headings": ["## 1. Executive Summary"]},
           "ONE-PAGER.md": {"headings": ONEPAGER_HEADINGS, "mermaid": ["flowchart"]}}
    items = [_files_item(ctx, "onepager", "EXEC-ONEPAGER", "writer", fam, "11_PROPOSAL", files, files,
                         per_file=per, stub=_proposal_stub(ctx, ["01"]), raw_name=step["id"], repo_ok=False)]
    if ctx.mode == "deep":
        items.append(_files_item(ctx, "prfaq", "PRFAQ", "writer", fam, "11_PROPOSAL", ["PRFAQ.md"], ["PRFAQ.md"],
                                 raw_name="%s-prfaq" % step["id"], repo_ok=False))
    return items


@fanout("proposal_review")
def _f_proposal_review(ctx, step):
    prop = ctx.seats.get("proposal") or {}
    items = []
    for fam in prop.get("rubric") or [ctx.host_family + "-alt"]:
        items.append({"id": "rubric_%s" % fam, "template": "PROPOSAL-RUBRIC", "kind": "rubric", "family": fam,
                      "tools": "none", "cwd": "empty", "out": "11_PROPOSAL/review/rubric_%s.json" % fam,
                      "contract": {"type": "json", "schema": schema_ref("rubric")}, "schema": schema_ref("rubric"),
                      "fallback": _fallbacks(ctx, fam)})
    if ctx.mode != "quick":
        fam = prop.get("redteam") or ctx.host_family + "-alt"
        items.append({"id": "redteam", "template": "PROPOSAL-REDTEAM", "kind": "redteam", "family": fam,
                      "tools": "none", "cwd": "empty", "out": "11_PROPOSAL/review/redteam.json",
                      "contract": {"type": "json", "schema": schema_ref("redteam")}, "schema": schema_ref("redteam"),
                      "fallback": _fallbacks(ctx, fam)})
    return items


def proposal_fix_files(ctx):
    """The files PROPOSAL-FIX may rewrite, exactly (#40): the run's sections (quick: the lite ones), ONE-PAGER.md,
    PRFAQ.md (deep, which writes one) and review/resolution.md."""
    secs = LITE_SECTIONS if ctx.mode == "quick" else [s for s, _ in PROPOSAL_SECTIONS]
    return (["sections/%s.md" % s for s in secs] + ["ONE-PAGER.md"] + (["PRFAQ.md"] if ctx.mode == "deep" else []) +
            ["review/resolution.md"])


@fanout("proposal_fix")
def _f_proposal_fix(ctx, step):
    fam = (ctx.seats.get("proposal") or {}).get("drafter") or ctx.host_family
    it = _files_item(ctx, None, "PROPOSAL-FIX", "fixer", fam, "11_PROPOSAL", proposal_fix_files(ctx),
                     ["review/resolution.md"], rules=writer_rules(PROPOSAL_WRITERS, proposal_fix_files(ctx)),
                     stub=_proposal_stub(ctx, [s for s, _ in PROPOSAL_SECTIONS]),
                     raw_name="%s-%d" % (step["id"], int((ctx.state.get("counters") or {}).get("g13_loops", 0))),
                     repo_ok=False, exact=True)
    return [it]


def _single_job(template, kind, out, contract, family_fn=None, vars_=None, schema=None, stub=None, tools="none",
                checks=None):
    def fn(ctx, step):
        fam = family_fn(ctx) if family_fn else ctx.host_family
        it = {"id": None, "template": template, "kind": kind, "family": fam, "tools": tools, "cwd": "empty",
              "out": out, "contract": dict(contract), "fallback": _fallbacks(ctx, fam)}
        if schema:
            it["schema"] = schema
        if stub:
            it["stub"] = stub(ctx) if callable(stub) else stub
        if vars_:
            it["vars"] = vars_(ctx) if callable(vars_) else dict(vars_)
        if checks:
            it["checks"] = list(checks)
        return [it]
    return fn


FANOUTS["frame_questions"] = _single_job("FRAME-QUESTIONS", "frame", "frame/questions.json",
                                         {"type": "json", "schema": schema_ref("frame-questions")},
                                         schema=schema_ref("frame-questions"), checks=["seed_leak"])
FANOUTS["evolve"] = _single_job("EVOLVE", "generator", "05_EVOLVED.md",
                                tcontract("EVOLVE", {"type": "idea-blocks", "prefix": "E", "min": 4}),
                                vars_=lambda ctx: {"EVOLVE_COUNT": "5" if ctx.mode == "deep" else "4"},
                                stub=lambda ctx: {"axes": _stub_axes(ctx)})
FANOUTS["evolve_contrast"] = _single_job("EVOLVE-CONTRAST", "generator", "05_EVOLVED.md",
                                         tcontract("EVOLVE-CONTRAST", {"type": "idea-blocks", "prefix": "E", "min": 2}),
                                         stub=lambda ctx: {"axes": _stub_axes(ctx)})
FANOUTS["normalizer"] = lambda ctx, step: [{
    "id": None, "template": "NORMALIZER", "kind": "normalizer", "family": ctx.host_family, "tools": "none",
    "cwd": "empty", "out": "tournament/cards.md",
    "contract": tcontract("NORMALIZER", {"type": "cards", "lines": CARD_LINES},
                          ids=list(ctx.state.get("finalists") or [])),
    "fallback": _fallbacks(ctx, ctx.host_family)}]
FANOUTS["precommit"] = _single_job("PRECOMMIT", "synthesis", "redteam/00_precommit.md",
                                   tcontract("PRECOMMIT", {"type": "text", "min_chars": 20}))
FANOUTS["synthesis"] = _single_job("SYNTHESIS", "synthesis", "07_REDTEAM.md",
                                   tcontract("SYNTHESIS", {"type": "text", "min_chars": 50, "final_line": SYNTH_FINAL}))
FANOUTS["probe"] = _single_job("PROBE", "writer", "09_PROBE.md",
                               tcontract("PROBE", {"type": "text", "min_chars": 50, "final_line": PROBE_FINAL}))
FANOUTS["quick_curate"] = lambda ctx, step: [{
    "id": None, "template": "QUICK-CURATE", "kind": "curator", "family": ctx.host_family, "tools": "none",
    "cwd": "empty", "out": "quick/curated.json",
    "contract": tcontract("QUICK-CURATE", {"type": "json", "schema": schema_ref("quick-curated")}),
    "schema": schema_ref("quick-curated"),
    "stub": {"aliases": pool_aliases(ctx)[0], "axes": _stub_axes(ctx), "primary_aliases": pool_aliases(ctx)[1]},
    "fallback": _fallbacks(ctx, ctx.host_family)}]
FANOUTS["quick_probe"] = _single_job("QUICK-PROBE", "writer", "quick/probe.json",
                                     {"type": "json", "schema": schema_ref("quick-probe")},
                                     schema=schema_ref("quick-probe"))
FANOUTS["arch_drivers"] = _single_job("ARCH-DRIVERS", "writer", "10_ARCHITECTURE/drivers.json",
                                      {"type": "json", "schema": schema_ref("arch-drivers")},
                                      schema=schema_ref("arch-drivers"))


def _premortem(ctx, step):
    from . import gates
    matrix = ctx.read_json("10_ARCHITECTURE/matrix.json", {}) or {}
    # no leader (every candidate EXCLUDED): the candidate the G11 default takes, never simply the first label
    leader = matrix.get("leader") or gates.g11_recommendation(ctx)[0]
    m = ctx.read_json("10_ARCHITECTURE/candidates/map.json", {}) or {}
    author = (m.get(leader) or {}).get("family") or ctx.host_family
    fam = seats_mod.premortem_family(ctx.seats, author)
    return [{"id": None, "template": "ARCH-PREMORTEM", "kind": "reviewer", "family": fam, "tools": "none",
             "cwd": "empty", "out": "10_ARCHITECTURE/premortem.md",
             "contract": tcontract("ARCH-PREMORTEM", {"type": "text", "min_chars": 50}),
             "vars": {"LEADER": leader or "A"}, "fallback": _fallbacks(ctx, fam)}]


FANOUTS["premortem"] = _premortem


def fanout_count(ctx, name, step=None):
    """(min, max) jobs of a fanout in a simulation: SIM_COUNTS for a fanout whose items come from files earlier steps
    write; otherwise the fanout builds its items from the state (seats, mode, variant) and they are counted, so `ub
    plan`, the ETA and the real dispatch never disagree (#15)."""
    fn = SIM_COUNTS.get(name)
    if fn is not None:
        return fn(ctx)
    n = len(FANOUTS[name](ctx, step or {"id": ""}) or [])
    return (n, n)


# ================================================================ placeholders

PLACEHOLDERS = {}

# Values quoted from run files that models wrote (checks, landscape, cards, reviews, packs, architecture files, ...),
# much of it from web pages: builders.resolver puts each in a DATA block its content cannot forge, and every template
# that uses one says the text inside is quoted data, never instructions (#94). The frame-derived brief (BRIEF, HMW,
# AUDIENCE, HARD_CONSTRAINTS, AXES, CRITERIA_*, FRAME_FULL) and the user's own words stay plain: they are the task.
DATA_PLACEHOLDERS = frozenset((
    "FACTS", "LANDSCAPE", "IDEA", "CARD", "CHECKS", "TOP_CARDS", "TOP_CHECKS", "SURVIVORS", "FINALISTS",
    "FINALIST_IDEAS", "KILL_ASSUMPTIONS", "REVIEWS", "OTHER_REVIEW", "PRECOMMIT_NOTE", "POOL_BUNDLE", "PROBE",
    "ARCH_BRIEF", "DRIVERS_JSON", "QAS_TABLE", "CANDIDATE_SHEETS", "CHOSEN_CANDIDATE", "STACK_ROWS", "STRUCTURE_FILES",
    "PREMORTEM", "FINDINGS", "LINT_REPORT", "PACK", "PACK_A", "PACK_B", "PACK_C", "SOURCES_TABLE", "SECTIONS_ALL",
    "RUBRIC_FIXES", "REDTEAM_ITEMS", "ADR_CANDIDATES", "LEDGER_TITLES", "CLUSTER_NAMES", "DECISION", "ARCH_CRITERIA",
    "STEAL_NOTES"))


def placeholder(*names):
    def deco(fn):
        for n in names:
            PLACEHOLDERS[n] = fn
        return fn
    return deco


def _fam(jc):
    return (jc or {}).get("family")


@placeholder("BRIEF")
def _ph_brief(ctx, jc):
    return brief_text(ctx)


@placeholder("FACTS")
def _ph_facts(ctx, jc):
    return facts_text(ctx, _fam(jc))


@placeholder("LANDSCAPE")
def _ph_landscape(ctx, jc):
    return context_section(ctx, "B") or "NOT SEARCHED"


@placeholder("AXES")
def _ph_axes(ctx, jc):
    ax = axes(ctx)
    if ax:
        return "\n".join("- %s: %s" % (k, " | ".join(v)) for k, v in ax.items())
    return section(frame_text(ctx), "Axes") or "(no axes: use your own judgment for Cell)"


@placeholder("HMW")
def _ph_hmw(ctx, jc):
    prob = section(frame_text(ctx), "Problem")
    return first_line(prob) or ctx.state.get("topic", "")


@placeholder("AUDIENCE")
def _ph_audience(ctx, jc):
    return section(frame_text(ctx), "Audience") or "(not stated)"


@placeholder("HARD_CONSTRAINTS")
def _ph_hard(ctx, jc):
    hc = section(frame_text(ctx), "Hard constraints")
    if not hc:
        q = ctx.state.get("quick") or {}
        hc = q.get("hard_constraint") or "(none stated)"
    return hc


def criteria_anchors(ctx):
    """{criterion: (a1, a3, a5)} from the FRAME Criteria table (| criterion | weight | 1 = | 3 = | 5 = |)."""
    out = {}
    for ln in section(frame_text(ctx), "Criteria").split("\n"):
        cells = [c.strip() for c in ln.strip().strip("|").split("|")]
        if len(cells) >= 5 and "|" in ln and not re.match(r"^:?-{2,}", cells[0]) and \
                cells[0].lower() not in ("criterion", "name", "#"):
            out[cells[0]] = (cells[2], cells[3], cells[4])
    return out


@placeholder("CRITERIA_ANCHORS")
def _ph_anchors(ctx, jc):
    anchors = criteria_anchors(ctx)
    lines = []
    for k in criteria(ctx):
        a = anchors.get(k)
        if a:
            lines.append("%s: 1 = %s; 3 = %s; 5 = %s" % (k, a[0], a[1], a[2]))
        else:
            lines.append("%s: 1 = poor; 3 = acceptable; 5 = excellent" % k)
    return "\n".join(lines)


@placeholder("CRITERIA_WEIGHTS")
def _ph_weights(ctx, jc):
    anchors = criteria_anchors(ctx)
    return "\n".join("%s %g: %s" % (k, v, (anchors.get(k) or ("", "", ""))[2] or "excellent")
                     for k, v in criteria(ctx).items())


@placeholder("STRATEGY_ID")
def _ph_strategy(ctx, jc):
    return str(((jc or {}).get("vars") or {}).get("STRATEGY_ID") or "")


@placeholder("IDEA")
def _ph_idea(ctx, jc):
    iid = ((jc or {}).get("vars") or {}).get("IDEA_ID") or chosen_idea(ctx)
    return idea_text(ctx, iid) if iid else ""


@placeholder("CARD")
def _ph_card(ctx, jc):
    iid = ((jc or {}).get("vars") or {}).get("IDEA_ID") or chosen_idea(ctx)
    return ("## %s\n%s" % (iid, card_text(ctx, iid))) if iid else ""


@placeholder("CHECKS")
def _ph_checks(ctx, jc):
    iid = ((jc or {}).get("vars") or {}).get("IDEA_ID") or chosen_idea(ctx)
    if iid:
        return ctx.read("checks/%s.md" % iid) or "(no check for %s)" % iid
    return ""


@placeholder("CELL")
def _ph_cell(ctx, jc):
    return str(((jc or {}).get("vars") or {}).get("CELL") or "")


@placeholder("CLUSTER_NAMES")
def _ph_clusters(ctx, jc):
    cl = ctx.read_json("clusters.json", {}) or {}
    return "\n".join("- %s" % c for c in sorted(set(cl.values()))) or "(none)"


@placeholder("LEDGER_TITLES")
def _ph_ledger(ctx, jc):
    ledger = os.path.join(os.path.dirname(ctx.run_dir), "LEDGER.md")
    out = []
    try:
        text = textio.read_text(ledger)
    except OSError:
        return "(none)"
    for ln in text.split("\n"):
        cells = [c.strip() for c in ln.strip().strip("|").split("|")]
        if len(cells) >= 5 and cells[4].lower() in ("killed", "parked"):
            out.append("- %s (%s)" % (cells[3], cells[4]))
    return "\n".join(out[-40:]) or "(none)"


@placeholder("POOL_BUNDLE")
def _ph_pool(ctx, jc):
    return pool_bundle(ctx)


@placeholder("SEEDS_BUNDLE")
def _ph_seeds(ctx, jc):
    return seeds_bundle(ctx)


@placeholder("FRAME_FULL")
def _ph_frame(ctx, jc):
    return frame_text(ctx) or brief_text(ctx)


@placeholder("DECISION")
def _ph_decision(ctx, jc):
    return ctx.read("08_DECISION.md") or ctx.read("QUICK_DECISION.md") or "(no decision yet)"


@placeholder("PROBE")
def _ph_probe(ctx, jc):
    return ctx.read("09_PROBE.md") or "(no probe yet)"


@placeholder("ARCH_BRIEF")
def _ph_arch_brief(ctx, jc):
    return ctx.read("10_ARCHITECTURE/00_BRIEF.md")


@placeholder("QAS_TABLE")
def _ph_qas(ctx, jc):
    from . import render_arch
    d = drivers(ctx)
    return render_arch.qas_table(d) if d.get("qas") else (ctx.read("10_ARCHITECTURE/quality-scenarios.md") or
                                                          "(no quality scenarios)")


@placeholder("ARCHETYPE")
def _ph_archetype(ctx, jc):
    return str(((jc or {}).get("vars") or {}).get("ARCHETYPE") or "")


@placeholder("OTHER_ARCHETYPES")
def _ph_other_arche(ctx, jc):
    return str(((jc or {}).get("vars") or {}).get("OTHER_ARCHETYPES") or "")


@placeholder("CANDIDATE_SHEETS")
def _ph_sheets(ctx, jc):
    parts = []
    for p in sorted(textio.glob_in(ctx.run_dir, "10_ARCHITECTURE", "review", "sheet_*.md")):
        parts.append(textio.read_text(p).strip())
    return "\n\n".join(parts)


@placeholder("CHOSEN_CANDIDATE")
def _ph_chosen(ctx, jc):
    label = ((jc or {}).get("vars") or {}).get("LEADER") or (ctx.state.get("choice") or {}).get("arch")
    m = ctx.read_json("10_ARCHITECTURE/candidates/map.json", {}) or {}
    n = (m.get(label) or {}).get("n")
    if not n:
        return "(no candidate chosen)"
    return ctx.read("10_ARCHITECTURE/candidates/%s.md" % n) or "(candidate text missing)"


@placeholder("DRIVERS_JSON")
def _ph_drivers(ctx, jc):
    # one line: an indented JSON block reads as code to privacy.strip_code (6.8), which a prompt must not carry
    return json.dumps(drivers(ctx), separators=(", ", ": "), ensure_ascii=True)


@placeholder("STRUCTURE_FILES")
def _ph_structure(ctx, jc):
    parts = []
    rels = ["chosen/containers.md", "chosen/runtime.md", "chosen/data-model.md", "chosen/api.md",
            "chosen/api/openapi.yaml", "chosen/api/cli.md", "chosen/deployment.md", "chosen/security-privacy.md",
            "chosen/cost-model.md", "chosen/deferred.md", "chosen/stack.md", "decisions.json", "risks.md"]
    rels += ["adr/" + os.path.basename(p) for p in sorted(textio.glob_in(ctx.run_dir, "10_ARCHITECTURE", "adr",
                                                                          "*.md"))]
    for rel in rels:
        t = ctx.read("10_ARCHITECTURE/" + rel)
        if t.strip():
            parts.append("--- FILE: %s ---\n%s" % (rel, t.strip()))
    return "\n\n".join(parts) or "(no package files yet)"


@placeholder("PREMORTEM")
def _ph_premortem(ctx, jc):
    return ctx.read("10_ARCHITECTURE/premortem.md") or "(no pre-mortem)"


@placeholder("FINDINGS")
def _ph_findings(ctx, jc):
    out = []
    for p in sorted(textio.glob_in(ctx.run_dir, "10_ARCHITECTURE", "review", "L*_*.json")):
        if p.endswith(".meta.json"):
            continue
        try:
            data = textio.read_json(p)
        except (OSError, ValueError):
            continue
        for f in (data or {}).get("findings") or []:
            if isinstance(f, dict) and str(f.get("severity") or "").upper() in ("P0", "P1"):
                out.append("%s | %s | %s | %s | %s" % (clean(f.get("id")), clean(f.get("severity")),
                                                     clean(f.get("file")), clean(f.get("issue")), clean(f.get("fix"))))
    return "\n".join(out) or "none"


@placeholder("LINT_REPORT")
def _ph_lint(ctx, jc):
    tpl = (jc or {}).get("template") or ""
    if tpl.startswith("PROPOSAL"):
        return ctx.read("11_PROPOSAL/lint.md") or "(no lint report)"
    return ctx.read("10_ARCHITECTURE/lint.md") or "(no lint report)"


@placeholder("PACK_A")
def _ph_pack_a(ctx, jc):
    return ctx.read("11_PROPOSAL/_packs/PACK_A.md")


@placeholder("PACK_B")
def _ph_pack_b(ctx, jc):
    return ctx.read("11_PROPOSAL/_packs/PACK_B.md")


@placeholder("PACK_C")
def _ph_pack_c(ctx, jc):
    return ctx.read("11_PROPOSAL/_packs/PACK_C.md")


@placeholder("SOURCES_TABLE")
def _ph_sources(ctx, jc):
    return ctx.read("sources.md") or "(no sources)"


@placeholder("SECTIONS_ALL")
def _ph_sections(ctx, jc):
    """PROPOSAL.md (or the section drafts before it exists); for another vendor its Appendix E keeps only the A2 terms
    FACTS would keep (privacy.filter_glossary), the one place PROPOSAL.md text reaches a prompt."""
    text = ctx.read("11_PROPOSAL/PROPOSAL.md") or "\n\n".join(
        textio.read_text(p) for p in sorted(textio.glob_in(ctx.run_dir, "11_PROPOSAL", "sections", "*.md")))
    if privacy_mod.needs_code_strip(ctx.state, _fam(jc) or ctx.host_family):
        text = privacy_mod.filter_glossary(text)
    return text


@placeholder("RUBRIC_FIXES")
def _ph_rubric_fixes(ctx, jc):
    out = []
    for p in sorted(textio.glob_in(ctx.run_dir, "11_PROPOSAL", "review", "rubric_*.json")):
        if p.endswith(".meta.json"):
            continue
        try:
            data = textio.read_json(p)
        except (OSError, ValueError):
            continue
        for f in (data or {}).get("must_fix") or []:
            if isinstance(f, dict):
                out.append("- %s: %s -> %s" % (f.get("section"), f.get("issue"), f.get("fix")))
    return "\n".join(out) or "(none)"


def ranked_redteam(ctx):
    data = ctx.read_json("11_PROPOSAL/review/redteam.json", {}) or {}
    score = {"H": 3, "M": 2, "L": 1}
    items = [i for i in (data.get("items") or []) if isinstance(i, dict)][:8]
    items.sort(key=lambda i: -(score.get(str(i.get("impact")).upper(), 1) *
                               score.get(str(i.get("likelihood")).upper(), 1) *
                               score.get(str(i.get("cheapness")).upper(), 1)))
    return items


@placeholder("REDTEAM_ITEMS")
def _ph_redteam(ctx, jc):
    items = ranked_redteam(ctx)[:5]
    return "\n".join("%d. %s | fails if: %s | cheapest test: %s" % (n, i.get("claim"), i.get("fails_if"),
                                                                  i.get("cheapest_test"))
                     for n, i in enumerate(items, 1)) or "(none)"


@placeholder("USER_CHANGES")
def _ph_user_changes(ctx, jc):
    return ctx.state.get("user_changes") or "(none)"


@placeholder("LANG")
def _ph_lang(ctx, jc):
    return ctx.state.get("lang") or "en"


@placeholder("VARIANT")
def _ph_variant(ctx, jc):
    return ctx.variant


@placeholder("MODE")
def _ph_mode(ctx, jc):
    return ctx.mode


@placeholder("DATE")
def _ph_date(ctx, jc):
    return textio.now_iso()[:10]


@placeholder("RUN_NAME")
def _ph_run(ctx, jc):
    return ctx.state.get("run", "")


@placeholder("OUTPUT_RULE")
def _ph_output_rule(ctx, jc):
    """Worker jobs: 'Print only the result.'; HOST_BATCH variants: the host rule and the OUTPUT FILE line."""
    if (jc or {}).get("host") and (jc or {}).get("out"):
        return "Write only the requested output to the file on the next line.\nOUTPUT FILE: %s" % textio.to_posix(
            ctx.path(jc["out"]))
    return "Print only the result."


@placeholder("SCHEMA_TEXT")
def _ph_schema(ctx, jc):
    from .. import validate
    contract = (jc or {}).get("contract") or {}
    ref = contract.get("schema") or contract.get("json_tail")
    if not ref or ref is True:
        name = (jc or {}).get("template")
        ref = (tcontract(name) or {}).get("schema") if name else None
    if not ref or ref is True:
        return "(no schema)"
    try:
        schema = validate.load_schema(ref, ctx.run_dir)
    except ValueError:
        return "(schema %s not found)" % ref
    return json.dumps(schema, separators=(", ", ": "), ensure_ascii=True)  # one line, as DRIVERS_JSON


@placeholder("ALLOWED_FILES")
def _ph_allowed(ctx, jc):
    contract = (jc or {}).get("contract") or {}
    split = ((jc or {}).get("item") or {}).get("split") or {}
    return ", ".join(split.get("allowed") or contract.get("allowed") or []) or "none"


@placeholder("ROUND_CAP")
def _ph_round_cap(ctx, jc):
    return "1" if ctx.autopilot == "guided" else "3"


@placeholder("COMPONENT_NAME")
def _ph_component(ctx, jc):
    return str(((jc or {}).get("vars") or {}).get("COMPONENT_NAME") or "")


# ---- engine extras (documented in the B3-engine notes)

@placeholder("TOPIC")
def _ph_topic(ctx, jc):
    return ctx.state.get("topic", "")


@placeholder("SEED_PROBLEM")
def _ph_seed_problem(ctx, jc):
    return seeds_section(ctx, "Problem") or "(not given)"


@placeholder("SEED_OFF_LIMITS")
def _ph_seed_off(ctx, jc):
    return seeds_section(ctx, "Off-limits") or "(none)"


@placeholder("FRAME_QA")
def _ph_frame_qa(ctx, jc):
    qs = frame_questions(ctx)
    ans = ctx.read_json("frame/answers.json", {}) or {}
    amap = dict((str(a.get("q")), a.get("a")) for a in ans.get("answers") or [] if isinstance(a, dict))
    lines = []
    for q in qs:
        a = amap.get(q["id"])
        src = "STATED"
        if not a and q.get("default") and (ans.get("accept_defaults") or ctx.autopilot == "full-auto"):
            a, src = q["default"], "DEFAULT (accepted recommendation)"
        if not a:
            a, src = "UNANSWERED", "ASSUMED"
        lines.append("%s. %s\n   Answer (%s): %s" % (q["id"], q["text"], src, a))
    if ans.get("reply"):
        lines.append("User's own words: %s" % ans["reply"])
    for c in ans.get("corrections") or []:
        lines.append("Correction: %s" % c)
    return "\n".join(lines) or "(no questions were asked)"


@placeholder("TITLES")
def _ph_titles(ctx, jc):
    return str(((jc or {}).get("vars") or {}).get("TITLES") or "40")


@placeholder("LENS")
def _ph_lens(ctx, jc):
    return str(((jc or {}).get("vars") or {}).get("LENS") or "")


@placeholder("STANCE")
def _ph_stance(ctx, jc):
    return str(((jc or {}).get("vars") or {}).get("STANCE") or "")


@placeholder("IDEA_ID")
def _ph_idea_id(ctx, jc):
    return str(((jc or {}).get("vars") or {}).get("IDEA_ID") or chosen_idea(ctx) or "")


@placeholder("OTHER_REVIEW")
def _ph_other_review(ctx, jc):
    return str(((jc or {}).get("vars") or {}).get("OTHER_REVIEW") or "")


@placeholder("TOP_CARDS")
def _ph_top_cards(ctx, jc):
    ids = ctx.state.get("top") or ctx.state.get("finalists") or []
    return "\n\n".join("## %s\n%s" % (i, card_text(ctx, i)) for i in ids)


@placeholder("TOP_CHECKS")
def _ph_top_checks(ctx, jc):
    ids = ctx.state.get("top") or []
    return "\n\n".join("=== checks/%s.md ===\n%s" % (i, ctx.read("checks/%s.md" % i).strip()) for i in ids)


@placeholder("REVIEWS")
def _ph_reviews(ctx, jc):
    """Every red-team review and rebuttal (never a failure record), family names removed, under '--- REVIEW <ID>
    <STANCE> ---' lines."""
    parts = []
    for p in sorted(textio.glob_in(ctx.run_dir, "redteam", "*.md")):
        m = REVIEW_FILE_RE.match(os.path.basename(p))
        if not m:
            continue
        label = "%s %s%s" % (m.group(1), m.group(2), " REBUTTAL" if m.group(4) else "")
        parts.append("--- REVIEW %s ---\n%s" % (label, textio.read_text(p).strip()))
    return "\n\n".join(parts) or "(no reviews)"


@placeholder("SURVIVORS")
def _ph_survivors(ctx, jc):
    ids = survivors(ctx)
    out = []
    for i in ids:
        out.append(idea_text(ctx, i))
        chk = ctx.read("checks/%s.md" % i)
        if chk:
            out.append("CHECK:\n" + chk.strip())
    return "\n\n".join(out)


@placeholder("FINALIST_IDEAS", "FINALISTS")
def _ph_finalists(ctx, jc):
    ids = ctx.state.get("finalists") or []
    out = []
    for i in ids:
        out.append(idea_text(ctx, i))
        v, d = check_verdict(ctx, i)
        risk = _top_kill_assumption(ctx.read("checks/%s.md" % i))
        out.append("Prior art: %s - differentiator: %s" % (v or "NOT CHECKED", d or "none found"))
        if risk:
            out.append("Main risk (from the check): %s" % risk)
    return "\n\n".join(out)


def _top_kill_assumption(check_text):
    m = re.search(r"(Fails if[^\n|]*)", _unfenced(check_text or ""))  # a fenced example is not the risk
    return m.group(1).strip() if m else ""


@placeholder("EVOLVE_COUNT")
def _ph_evolve_count(ctx, jc):
    return str(((jc or {}).get("vars") or {}).get("EVOLVE_COUNT") or "4")


@placeholder("WEB")
def _ph_web(ctx, jc):
    return str(((jc or {}).get("vars") or {}).get("WEB") or ("yes" if (ctx.state.get("privacy") or {}).get("web")
                                                             else "no"))


@placeholder("PACK")
def _ph_pack(ctx, jc):
    name = ((jc or {}).get("vars") or {}).get("PACK") or "PACK_A"
    return ctx.read("11_PROPOSAL/_packs/%s.md" % name)


@placeholder("LEADER")
def _ph_leader(ctx, jc):
    return str(((jc or {}).get("vars") or {}).get("LEADER") or "")


@placeholder("SOFTWARE_OP")
def _ph_software_op(ctx, jc):
    return str(((jc or {}).get("vars") or {}).get("SOFTWARE_OP") or "no")


@placeholder("CODEBASE_FIT")
def _ph_codebase_fit(ctx, jc):
    """CHECK section 5 as _check_item set it (CODEBASE_FIT, or empty: the line goes)."""
    return str(((jc or {}).get("vars") or {}).get("CODEBASE_FIT") or "")


@placeholder("QUICK_CRITERIA")
def _ph_quick_criteria(ctx, jc):
    return _ph_weights(ctx, jc)


@placeholder("BUILD_TYPE")
def _ph_build_type(ctx, jc):
    return ctx.state.get("build_type", "system")


# ---- placeholders named in templates/manifest.json that are not in the 6.12 standard list

PRIVACY_NOTE_OFF = {
    "P-GROUND": "Write section B as NOT SEARCHED and say so in section C.",
    "CHECK": "Do not search; end with VERDICT: NOT CHECKED (it can never trigger K4).",
    "STACK-VERIFY": "Do not search; mark every row NOT SEARCHED.",
    "S4-TRANSFER": "Do not search; use reasoned or direct Basis lines only.",
    "ARCH-REVIEW": "Do not search; mark claims you cannot verify as UNVERIFIED findings.",
}


@placeholder("GEN_HEADER")
def _ph_gen_header(ctx, jc):
    from . import builders
    body = load_template("GEN-HEADER")
    if body is None:
        raise EngineError("template GEN-HEADER is missing (templates/prompts/GEN-HEADER.md)",
                          fix=["reinstall the kit: install.py update"])
    return builders.fill(ctx, body, dict(jc or {}, template="GEN-HEADER")).strip("\n")


@placeholder("PRIVACY_NOTE")
def _ph_privacy_note(ctx, jc):
    tools = str((jc or {}).get("tools") or ((jc or {}).get("item") or {}).get("tools") or "none")
    if "web" in tools:
        return "Web search is allowed for this job."
    tail = PRIVACY_NOTE_OFF.get((jc or {}).get("template") or "", "Do not search the web.")
    reason = "privacy says no web" if not (ctx.state.get("privacy") or {}).get("web", True) else \
        "this model family has no web tool in this run"
    return "Web search is NOT allowed for this job (%s). %s" % (reason, tail)


@placeholder("REPO_SCOPE")
def _ph_repo_scope(ctx, jc):
    """For a job that reads the repository (cwd repo) only, so no other prompt changes: the run folders are not part
    of the codebase (#97), and code is cited, never pasted (C8)."""
    root = (jc or {}).get("repo_root")
    if (jc or {}).get("cwd") != "repo" or not root or not ctx.run_dir:
        return ""
    try:
        rel = os.path.relpath(os.path.dirname(os.path.abspath(ctx.run_dir)), os.path.abspath(root))
        if rel == os.curdir:  # runs directly in the project folder: name this run's folder
            rel = os.path.relpath(os.path.abspath(ctx.run_dir), os.path.abspath(root))
    except ValueError:  # another drive: outside the repository
        rel = os.pardir
    never = "" if rel.startswith(os.pardir) else (
        "Never open %s/ or anything under it: those are this kit's run folders (ideas, checks, candidates, earlier "
        "runs), not part of the codebase. " % rel.replace("\\", "/"))
    return "%s %sCite code as path:line; never paste source lines or code blocks." % (REPO_SCOPE_START, never)


REPO_SCOPE_START = "You may read the repository; your working folder is its root."  # a copy drops this line


def privacy_line(state):
    priv = state.get("privacy") or {}
    return "(a) web + other vendors: %s; (b) code facts / repo files to other vendors: %s; web search: %s" % (
        "yes" if priv.get("web", True) and priv.get("vendors", True) else "no", "yes" if priv.get("code") else "no",
        "allowed" if priv.get("web", True) else "not allowed")


@placeholder("PRIVACY_LINE")
def _ph_privacy_line(ctx, jc):
    return privacy_line(ctx.state)


@placeholder("STRATEGY_MAP")
def _ph_strategy_map(ctx, jc):
    return st.strategy_map_line(ctx.state)


@placeholder("FAMILY_MAP")
def _ph_family_map(ctx, jc):
    fm = ctx.read_json("pool/_families.json", None)
    if not isinstance(fm, dict) or not fm:
        fm = pool_families(ctx)
    return "\n".join("%s = %s" % (k, fm[k]) for k in sorted(fm, key=st._strategy_sort_key)) or "(empty)"


@placeholder("LENS_TEXT")
def _ph_lens_text(ctx, jc):
    return str(((jc or {}).get("vars") or {}).get("LENS") or "")


@placeholder("REVIEW_LENS")
def _ph_review_lens(ctx, jc):
    return str(((jc or {}).get("vars") or {}).get("REVIEW_LENS") or "L1")


@placeholder("LENS_QUESTION")
def _ph_lens_question(ctx, jc):
    lens = str(((jc or {}).get("vars") or {}).get("REVIEW_LENS") or "L1")
    return REVIEW_LENSES.get(lens, lens)


@placeholder("ARCHETYPE_ID")
def _ph_archetype_id(ctx, jc):
    return str(((jc or {}).get("vars") or {}).get("ARCHETYPE_ID") or "A")


@placeholder("ARCH_CRITERIA")
def _ph_arch_criteria(ctx, jc):
    d = drivers(ctx)
    lines = ["%s %s (weight %s)" % (q.get("id"), clean(q.get("name")), q.get("weight"))
             for q in d.get("quality_goals") or [] if isinstance(q, dict) and q.get("id")]
    lines += ["%s (weight %d)" % (c, w) for c, w in FIXED_ARCH_CRITERIA]
    return "\n".join(lines)


@placeholder("ARCH_LABELS")
def _ph_arch_labels(ctx, jc):
    return ", ".join(arch_labels(ctx)) or "A, B"


_NEXT_IDEA = re.compile(r"^[-*#]*[ \t]*[IEQ]-\d+")


def _unfenced(text):
    """`text` without its fenced code blocks (the fence lines included)."""
    lines = textio.normalize_newlines(text).split("\n")
    return "\n".join(ln for ln, fenced in zip(lines, textio.fence_mask(lines)) if not fenced)


@placeholder("KILL_ASSUMPTIONS")
def _ph_kill_assumptions(ctx, jc):
    iid = chosen_idea(ctx)
    out = []
    if iid:
        ka = section(ctx.read("checks/%s.md" % iid), "4")
        if ka:
            out.append("From the reality check of %s:\n%s" % (iid, ka))
    red = ctx.read("07_REDTEAM.md")
    if red:
        kills = re.findall(r"(Fails if[^\n]*)", _unfenced(red))
        per = _unfenced(section(red, "1") or "")
        if iid and iid in per:
            # the chosen idea's block runs to the next idea line; fenced examples were dropped above, so a quoted
            # '### I-002' cannot end it early (#41). Line by line, so a flood of blank lines stays linear (#34)
            lines = per.split("\n")
            start = next(i for i, ln in enumerate(lines) if iid in ln)
            end = next((j for j in range(start + 1, len(lines)) if _NEXT_IDEA.match(lines[j])), len(lines))
            block = "\n".join([lines[start].split(iid, 1)[1]] + lines[start + 1:end])
            kills = re.findall(r"(Fails if[^\n]*)", block) or kills
        if kills:
            out.append("From the red-team:\n" + "\n".join("- %s" % k for k in kills[:6]))
    return "\n\n".join(out) or "(none recorded; derive them from the decision and the brief)"


@placeholder("PRECOMMIT_NOTE")
def _ph_precommit_note(ctx, jc):
    return ctx.read("redteam/00_precommit.md").strip() or "(no pre-commit note)"


@placeholder("STACK_ROWS")
def _ph_stack_rows(ctx, jc):
    cand = chosen_candidate_json(ctx)
    rows = [r for r in cand.get("stack") or [] if isinstance(r, dict)]
    if not rows:
        return "(the chosen candidate lists no stack rows; take them from the package files)"
    lines = ["| layer | component | choice | version |", "|---|---|---|---|"]
    for r in rows:
        lines.append("| %s | %s | %s | %s |" % (clean(r.get("layer")), clean(r.get("component")), clean(r.get("choice")),
                                               clean(r.get("version")) or "TO VERIFY"))
    return "\n".join(lines)


@placeholder("STEAL_NOTES")
def _ph_steal_notes(ctx, jc):
    g11 = ((ctx.state.get("gates") or {}).get("G11") or {}).get("answer") or {}
    notes = ["- from %s: %s" % (s.get("from"), s.get("element")) for s in g11.get("steal") or []
             if isinstance(s, dict) and s.get("element")]
    return "\n".join(notes) or "none"


@placeholder("RUN_DIR")
def _ph_run_dir(ctx, jc):
    return textio.to_posix(ctx.run_dir) if ctx.run_dir else ""


@placeholder("S1_DIALS")
def _ph_s1_dials(ctx, jc):
    dials = []
    if ctx.mode == "deep":
        dials.append("go deep")
    priv = ctx.state.get("privacy") or {}
    if not priv.get("web", True) or not priv.get("code", False) and ctx.variant in REPO_VARIANTS:
        dials.append("no external research")
    return " ".join(dials)


@placeholder("ADR_CANDIDATES")
def _ph_adr_candidates(ctx, jc):
    out = []
    for ln in section(frame_text(ctx), "Decision ledger").split("\n"):
        if "ADR-CANDIDATE" in ln:
            out.append("- " + clean(ln.strip().strip("|")))
    for p in sorted(textio.glob_in(ctx.run_dir, "10_ARCHITECTURE", "adr", "*.md")):
        t = textio.read_text(p)
        m = re.search(r"^# (ADR-\d{4}: .*)$", t, re.M)
        if m:
            out.append("- %s (10_ARCHITECTURE/adr/%s)" % (m.group(1).strip(), os.path.basename(p)))
    return "\n".join(out) or "none"


def frame_questions(ctx):
    """Tolerant read of frame/questions.json: [{"id","text","default"}]."""
    data = ctx.read_json("frame/questions.json", None)
    items = data.get("questions") if isinstance(data, dict) else data
    out = []
    for n, q in enumerate(items or [], 1):
        if isinstance(q, str):
            out.append({"id": str(n), "text": q, "default": None})
            continue
        if not isinstance(q, dict):
            continue
        qid = str(q.get("id") or n)
        text = q.get("q") or q.get("question") or q.get("text") or ""
        default = q.get("default")
        if isinstance(default, str) and not default.strip():
            default = None
        out.append({"id": qid, "text": str(text), "default": default, "topic": q.get("topic") or q.get("kind")})
    return out


# ================================================================ scripts

SCRIPTS = {}


def script(name):
    def deco(fn):
        SCRIPTS[name] = fn
        return fn
    return deco


@script("noop")
def _s_noop(ctx, step):
    return None


@script("apply_kickoff")
def _s_apply_kickoff(ctx, step):
    """0.3: seeds file (v1 format), seats, budget, privacy defaults."""
    from . import gates
    ans = ((ctx.state.get("gates") or {}).get("G0") or {}).get("answer") or {}
    write_seeds(ctx, ans)
    reseat(ctx)
    if ctx.autopilot == "full-auto" and ((ctx.state.get("gates") or {}).get("G0") or {}).get("by") == "human":
        if gates.new_vendors(ctx) != []:  # none saved, saved without the vendor set, or a vendor it never listed
            try:
                p = ctx.state.get("privacy") or {}
                st.config_set("privacy_defaults", {"web": p.get("web"), "vendors": p.get("vendors"),
                                                   "code": p.get("code"), "vendor_set": gates.vendor_set(ctx)})
            except OSError:
                pass
    return gates.kickoff_note(ctx)


SEED_HEADINGS = (("Problem", "Problem"), ("Primary idea", "Primary idea (to pressure-test)"), ("Ideas", "Ideas"),
                 ("Obvious", "Obvious"), ("Off-limits", "Off-limits"))
SEEDS_KICKOFF = ".ub/seeds_kickoff.json"  # {"before": the seeds file 0.3 merged into, "sha256": of the file it left}


def write_seeds(ctx, ans):
    """0.3: the G0 reply's seeds go into 00_HUMAN_SEEDS.md (v1 format). A file that holds the user's own seeds (a
    --seeds-file, or the file the G0 card names, written while G0 waited) is kept as written: the reply's Ideas,
    Obvious and Off-limits items are added to its sections, its Problem is filled only when empty, and its Primary
    idea is the reply's `primary:`, else its own, else (proposal mode) the proposal idea. A file of the user's own
    that is not in the v1 form (an idea list, free text, '###' headings) is put in that form first (_v1_seeds). A file
    without seeds gets the reply's seeds. With no seeds at all, a SKIPPED line (hands-on leaves that to G1) replaces an
    empty file and goes above the sections of a file with only Obvious or Off-limits items, which stay. The version 0.3
    merged into is kept (SEEDS_KICKOFF), so 0.3 run again (a redo, a new G0 answer) merges into it, never into its own
    earlier result; a file the user changed since is the user's version."""
    seeds = ans.get("seeds") or {}
    cur = seeds_text(ctx)
    rec = ctx.read_json(SEEDS_KICKOFF, None)
    base = cur
    if isinstance(rec, dict) and isinstance(rec.get("before"), str) and rec.get("sha256") == textio.sha256_text(cur):
        base = rec["before"]
    ideas, obvious, off = ([s for s in ([v] if isinstance(v, str) else v or []) if s]
                           for v in (seeds.get("ideas"), seeds.get("obvious"), seeds.get("off_limits")))
    primary, problem = seeds.get("primary"), seeds.get("problem")
    proposal_idea = ctx.state.get("idea_text") if ctx.mode == "proposal" else None
    own = any(section(base, key) for key, _heading in SEED_HEADINGS)
    into = base
    if not own and _own_lines(base) and not re.search(r"^[^\w\n]*SKIPPED\b", base, re.M):
        into, own = _v1_seeds(base), True
    if own:
        text = _merge_seeds(into, {"Problem": ([problem] if problem else [], "if_empty"),
                                   "Primary idea": (["- %s" % primary], "replace") if primary
                                   else (["- %s" % proposal_idea] if proposal_idea else [], "if_empty"),
                                   "Ideas": (["- %s" % s for s in ideas], "add"),
                                   "Obvious": (["- %s" % s for s in obvious], "add"),
                                   "Off-limits": (["- %s" % s for s in off], "add")})
    elif ideas or primary or proposal_idea or problem or obvious or off:
        text = st.seeds_doc(problem, primary or proposal_idea, ideas, obvious, off)
    else:
        text = base
    seeded = (ideas or primary or problem or obvious or off or section(text, "Ideas") or
              section(text, "Primary idea") or section(text, "Problem") or re.search(r"^[^\w\n]*SKIPPED\b", text, re.M))
    if not seeded and not (ctx.autopilot == "hands-on" and not ans.get("skip_seeds")):  # hands-on: G1 asks for them
        text = skipped_seeds(text, "full-auto" if ctx.autopilot == "full-auto" else
                             "the user replied without seeds at kickoff")
    ctx.write_json(SEEDS_KICKOFF, {"before": base, "sha256": textio.sha256_text(text)})
    if text != cur:
        ctx.write("00_HUMAN_SEEDS.md", text)


def skipped_seeds(text, reason):
    """The seeds file `text` with the line 'SKIPPED: <reason>' (0.3 without seeds, `skip` at G1): above the first
    '## ' section (else at the top) of a file with text of the user's own (a Problem, Obvious or Off-limits item
    stays, and the Off-limits a prompt quotes stay the user's lines alone), else the line alone replaces the file."""
    if not _own_lines(text):
        return "SKIPPED: %s\n" % reason
    lines = text.split("\n")
    at = next((i for i, lvl, _t in textio.headings(text) if lvl == 2), 0)
    return "\n".join(lines[:at] + ["SKIPPED: %s" % reason, ""] + lines[at:])


def _own_lines(text):
    """The indexes of the lines of a seeds file that the user wrote: neither blank nor a heading (the empty template
    is headings only)."""
    heads = set(i for i, _lvl, _t in textio.headings(text))
    return [n for n, ln in enumerate(text.split("\n")) if ln.strip() and n not in heads]


def _v1_seeds(text):
    """A seeds file of the user's own that is not in the v1 form (an idea list as `ub import` takes it, free text,
    '#' or '###' headings), in that form: a heading named like a seed section becomes that '## ' section, and a file
    that still has no seed section gets '## Ideas' above its first line of text, so its lines are the Ideas items."""
    text = textio.normalize_newlines(text)
    lines = text.split("\n")
    for i, lvl, title in textio.headings(text):
        if lvl != 2 and any(" ".join(title.split()).lower().startswith(k.lower()) for k, _h in SEED_HEADINGS):
            lines[i] = "## " + title
    out = "\n".join(lines)
    if any(section(out, key) for key, _heading in SEED_HEADINGS):
        return out
    at = _own_lines(out)[0]
    return "\n".join(lines[:at] + ["## Ideas"] + lines[at:])


def _merge_seeds(text, fill):
    """`text` with the kickoff's seed lines put into its sections in place, so everything else stays as the user wrote
    it. fill: {section: (lines, how)}; how is `add` (the lines whose item the section does not list yet go below its
    last line), `if_empty` (the lines only when the section is empty) or `replace`. A missing section is added at the
    end."""
    lines = textio.normalize_newlines(text).rstrip("\n").split("\n")
    for key, heading in SEED_HEADINGS:
        new, how = fill.get(key) or ([], "add")
        if not new:
            continue
        heads = textio.headings("\n".join(lines))
        k = next((n for n, (_i, lvl, title) in enumerate(heads)
                  if lvl == 2 and " ".join(title.split()).lower().startswith(key.lower())), None)
        if k is None:
            lines += ["", "## " + heading] + new
            continue
        start = heads[k][0] + 1
        end = next((i for i, lvl, _t in heads[k + 1:] if lvl <= 2), len(lines))
        body = lines[start:end]
        filled = [n for n, ln in enumerate(body) if ln.strip()]
        if how == "replace":
            lines[start:end] = new + ([""] if end < len(lines) else [])
        elif how == "if_empty" and filled:
            continue
        else:
            have = set(" ".join(x.split()).lower() for x in _seed_items("\n".join(body)))
            add = [ln for ln in new if " ".join(" ".join(_seed_items(ln)).split()).lower() not in have]
            at = start + (filled[-1] + 1 if filled else 0)
            lines[at:at] = add
    return "\n".join(lines) + "\n"


def alt_distinct(ctx, host):
    """False when families config sets <host>.alt_model to null: <host>-alt would run the same model again. Unknown
    (no config entry): True, the spec's <host>-alt seat."""
    cfg = (ctx.deps.families_cfg() if ctx.deps else None) or {}
    entry = (cfg.get("families") or {}).get(host)
    return not (isinstance(entry, dict) and "alt_model" in entry and not entry.get("alt_model"))


def reseat(ctx):
    host = ctx.host_family
    fams = ctx.state.get("families") or {}
    available = [f for f in fams if (fams.get(f) or {}).get("status") == "ok"]
    priv = ctx.state.setdefault("privacy", {})
    allowed = privacy_mod.allowed_vendors(host, available, priv.get("vendors", True))
    priv["allowed_vendors"] = allowed
    F = seats_mod.family_list(host, available, allowed)
    web = {}
    for f in F:
        web[f] = bool((fams.get(f) or {}).get("web")) and bool(priv.get("web", True))
    s1 = "s1f"
    comps = ctx.state.get("components") or {}
    if comps.get("ce_ideate") and ctx.host_agent != "terminal" and ctx.mode not in ("quick", "proposal"):
        if ctx.autopilot == "hands-on" or (ctx.autopilot == "guided" and
                                           (ctx.state.get("options") or {}).get("with_ce_ideate")):
            s1 = "ce-ideate"
    old = ctx.state.get("seats") or {}
    new = seats_mod.assign(ctx.state.get("run", ""), host, F, web, ctx.mode, ctx.variant, s1,
                           alt_distinct=alt_distinct(ctx, host))
    if old.get("arch_writer"):
        new["arch_writer"] = old["arch_writer"]
    ctx.state["seats"] = new
    return old, new


@script("context_snapshot")
def _s_context_snapshot(ctx, step):
    pd = ctx.state.get("project_dir")
    src = os.path.join(pd, "CONTEXT.md")
    if os.path.exists(src):
        ctx.write("CONTEXT.before.md", textio.read_text(src))
    ctx.write_json("frame/footprint.json", footprint(pd))
    return "context snapshot taken"


def footprint(project_dir):
    out = {}
    for rel in ["CONTEXT.md", "CONTEXT-MAP.md"] + [os.path.relpath(p, project_dir).replace("\\", "/")
                                                    for p in textio.glob_in(project_dir, "docs", "adr", "*.md")]:
        p = os.path.join(project_dir, rel)
        if os.path.isfile(p):
            out[rel] = textio.sha256_file(p)
    return out


@script("quick_frame")
def _s_quick_frame(ctx, step):
    q = ctx.state.get("quick") or {}
    names = [c for c in (q.get("criteria") or []) if c][:3] or QUICK_DEFAULT_CRITERIA
    weights = [40, 35, 25][:len(names)]
    total = float(sum(weights))
    crit = dict((n, round(100.0 * w / total, 1)) for n, w in zip(names, weights))
    prob = seeds_section(ctx, "Problem") or ctx.state.get("topic", "")
    hard = q.get("hard_constraint") or "(none stated)"
    body = [
        "# FRAME: %s" % ctx.state.get("topic", ""),
        "## Job statement (anchor-stripped)", prob,
        "## Problem", "How might we address: %s" % prob,
        "## Audience / boundary", "(quick mode: from the kickoff brief)",
        "## Success looks like", "NOT VERIFIED (quick mode)",
        "## Hard constraints (gates)", hard,
        "## Soft constraints", "(none stated)",
        "## Non-goals", "(none stated)",
        "## Criteria", "\n".join("- %s %g: 1 = poor; 3 = acceptable; 5 = excellent" % (k, v) for k, v in crit.items()),
        "## Axes", "(quick mode: none)",
        "## Mode, privacy, budget", "quick",
    ]
    ctx.write("01_FRAME.md", "\n".join(body) + "\n")
    ctx.write_json("criteria.json", crit)
    return "mini frame from the kickoff brief"


@script("frame_check")
def _s_frame_check(ctx, step):
    notes = []
    try:
        bs(ctx, "lint-frame", ctx.run_dir, allow=(0, 1, 2, 4, 5))
    except EngineError:
        pass
    crit = ctx.read_json("criteria.json", None)
    fixed = None
    if not isinstance(crit, dict) or not crit:
        fixed = dict(DEFAULT_CRITERIA)
        notes.append("criteria.json missing: default criteria used")
    else:
        # the file bs.py and the judges read is validate.CRITERIA_SCHEMA's (a weight is a number, 0 to 100): a value
        # that is not a finite number is no criterion, and a negative weight counts as 0
        vals, bad = {}, []
        for k, v in crit.items():
            try:
                f = None if isinstance(v, bool) else float(v)
            except (TypeError, ValueError, OverflowError):  # OverflowError: a JSON integer too large for a float
                f = None
            if f is None or not math.isfinite(f):
                bad.append("%s dropped (not a number)" % k)
            else:
                if f < 0:
                    bad.append("%s counted as 0 (negative)" % k)
                vals[str(k)] = max(f, 0.0)
        total = sum(vals.values())
        if bad:
            notes.append("criteria.json: " + "; ".join(bad))
        if total <= 0:
            fixed = dict(DEFAULT_CRITERIA)
            notes.append("criteria weights missing: defaults used")
        elif abs(total - 100.0) > 0.5:
            fixed = dict((k, round(v * 100.0 / total, 1)) for k, v in vals.items())
            notes.append("criteria weights summed to %g: normalized to 100" % total)
        elif vals != crit:
            fixed = vals
    if fixed is not None:
        ctx.write_json("criteria.json", fixed)
    pd = ctx.state.get("project_dir")
    base = ctx.read_json("frame/footprint.json", None)
    if base is not None and pd:
        changed = footprint(pd) != base
        ctx.state.setdefault("facts", {})["footprint_changed"] = changed
        if changed:
            notes.append("CONTEXT.md, CONTEXT-MAP.md or docs/adr changed during framing")
    for n in notes:
        st.add_note(ctx.state, n)
    return "; ".join(notes) or "frame checked"


@script("merge_ground")
def _s_merge_ground(ctx, step):
    second = ctx.read("ground/02_CONTEXT.second.md")
    if not second:
        return "no second researcher output"
    # the section the P-GROUND contract validated (textio's headings and fences: a fenced '## C' line never cuts it)
    hits = [b for h, b in _h2_sections(second) if re.match(CONTEXT_HEADINGS["B"], h, re.I)]
    body = "\n\n".join(b.strip() for b in hits) or second.strip()
    main = ctx.read("02_CONTEXT.md")
    if "## B (second family)" in main:
        return "already merged"
    ctx.write("02_CONTEXT.md", main.rstrip() + "\n\n## B (second family)\n" + body + "\n")
    return "second researcher's LANDSCAPE appended"


@script("proposal_idea")
def _s_proposal_idea(ctx, step):
    idea = ctx.state.get("idea_text") or ctx.state.get("topic", "")
    title = " ".join(idea.split()[:8])
    ctx.write("screen/ideas.md", "I-001 | %s | %s | %s\n" % (clean(title), clean(idea), clean(idea)))
    ctx.write_json("origins.json", {"I-001": "human"})
    ctx.write_json("primary.json", ["I-001"])
    ctx.write_json("clusters.json", {"I-001": "the user's idea"})
    return "your idea is I-001"


@script("bs_schemas")
def _s_bs_schemas(ctx, step):
    bs(ctx, "schemas", ctx.run_dir)
    return "judge and lens schemas written"


@script("add_evolved")
def _s_add_evolved(ctx, step):
    blocks = idea_blocks(ctx.read("05_EVOLVED.md"), "E")
    if not blocks:
        if not ctx.exists("05_EVOLVED.md"):
            ctx.write("05_EVOLVED.md", "# EVOLVED\n\nskipped (the evolve call failed)\n")
        return "no evolved ideas"
    # a redo of 8.1 rewrites 05_EVOLVED.md with the same E ids, so the E origins of an earlier run are dropped first:
    # they described other ideas (#51)
    org = dict((k, v) for k, v in origins(ctx).items() if not re.match(r"^E-\d+$", k))
    cl = ctx.read_json("clusters.json", {}) or {}
    meta = ctx.read_json("05_EVOLVED.md.meta.json", {}) or {}
    writer = (meta.get("family") if meta.get("status") == "ok" else None) or ctx.host_family
    for b in blocks:
        # origin by lineage (as bs.py map): the family that wrote the E idea plus its AI parents' families, compared
        # by vendor (claude and claude-alt are one); one vendor -> that family (its judges' own-vendor correction then
        # applies), several -> ai-mixed
        fams = set([writer]) | set(org.get(p) for p in re.findall(r"\bI-\d+\b", b["fields"].get("parents", ""))
                                   if org.get(p) not in (None, "human", "human-mixed", "?", ""))
        org[b["id"]] = seats_mod.lineage_origin(fams)
        cl.setdefault(b["id"], "evolved")
    ctx.write_json("origins.json", org)
    ctx.write_json("clusters.json", cl)
    return "%d evolved ideas added" % len(blocks)


@script("evolve_skipped")
def _s_evolve_skipped(ctx, step):
    if not ctx.exists("05_EVOLVED.md"):
        ctx.write("05_EVOLVED.md", "# EVOLVED\n\nskipped (%d survivors; evolve runs when fewer than 6 survive)\n"
                  % len(survivors(ctx)))
    return "evolve skipped"


def write_pool_families(ctx):
    fam_map = pool_families(ctx)
    ctx.write_json("pool/_families.json", fam_map)
    return fam_map


def pool_families(ctx):
    """prefix -> the family that actually produced the pool file (a substitute is recorded as its own label, e.g.
    gpt-alt); human prefixes are `human`, imports `import`."""
    fam_map, ok_map = {}, {}
    for path in sorted(textio.glob_in(ctx.run_dir, "jobs", "*.json")):
        try:
            job = textio.read_json(path)
        except (OSError, ValueError):
            continue
        if job.get("kind") != "generator":
            continue
        out = job.get("out") or ""
        if not out.startswith("pool/"):
            continue
        prefix = (job.get("contract") or {}).get("prefix")
        if not prefix:
            m = re.match(r"^pool/([A-Z][A-Za-z0-9]*)", out)
            prefix = m.group(1) if m else None
        if not prefix:
            continue
        fam_map.setdefault(prefix, job.get("family"))
        meta = ctx.read_json(out + ".meta.json", {}) or {}
        if meta.get("status") == "ok":
            ok_map[prefix] = meta.get("family") or job.get("family")
    fam_map.update(ok_map)
    if ctx.exists("pool/S1_ce-ideate.md"):
        fam_map.setdefault("S1", ctx.host_family)
        fam_map.setdefault("S1R", ctx.host_family)
    for h in ("H", "HP", "H2"):
        fam_map[h] = "human"
    if textio.glob_in(ctx.run_dir, "pool", "IMPORT_*.md"):
        fam_map["IMP"] = "import"
    for path in textio.glob_in(ctx.run_dir, "00_HUMAN_SEEDS_*.md"):
        name = os.path.basename(path)[len("00_HUMAN_SEEDS_"):-3]
        if re.match(r"^[A-Za-z0-9]+$", name):
            fam_map["H" + name] = "human"
    return fam_map


@script("s1_after")
def _s_s1_after(ctx, step):
    """After the ce-ideate host task: record whether the human saw its ranked list (00_RUN.md line). The task never
    writes a file that says so (4.1c writes only the pool file), so the answer is always no."""
    if ctx.exists("pool/S1_ce-ideate.md"):
        ctx.state.setdefault("human_saw_s1", "no")
    return "ce-ideate output attached"


@script("context_merge_after")
def _s_context_merge_after(ctx, step):
    """After the CONTEXT-MERGE host task: keep the user's merge decision for the handoff seed and 12_HANDOFF.md."""
    data = ctx.read_json("answers/CONTEXT-MERGE.json", None)
    if isinstance(data, dict):
        ctx.state["context_merge"] = {"merge_terms": data.get("merge_terms"), "terms": data.get("terms") or [],
                                      "adrs": data.get("adrs") or []}
        return "domain terms: %s" % (data.get("merge_terms") or "none")
    return "no merge decision recorded"


@script("write_pool_families")
def _s_pool_families(ctx, step):
    fm = write_pool_families(ctx)
    return "pool/_families.json: %d prefixes" % len(fm)


@script("convert_merges")
def _s_convert_merges(ctx, step):
    raw = None
    for jid in (ctx.state.get("steps", {}).get(step["id"], {}) or {}).get("jobs") or []:
        job = ctx.read_json("jobs/%s.json" % jid, {}) or {}
        if job.get("kind") == "curator" and ctx.exists(job.get("out", "")):
            raw = ctx.read_json(job["out"], None)
    if not isinstance(raw, dict):
        raise EngineError("the curator output is missing or not JSON", fix=[redo_cmd(ctx, step["id"])])
    fam_map = write_pool_families(ctx)
    ax = {}
    for a in raw.get("axes") or []:
        if isinstance(a, dict) and a.get("name"):
            ax[str(a["name"])] = [str(v) for v in a.get("values") or []]
    if isinstance(raw.get("axes"), dict):
        ax = dict((str(k), [str(x) for x in v]) for k, v in raw["axes"].items())
    ideas = []
    for it in raw.get("ideas") or []:
        if not isinstance(it, dict):
            continue
        ideas.append({"key": it.get("key"), "title": it.get("title"), "pitch": it.get("pitch"),
                      "mechanism": it.get("mechanism"), "aliases": list(it.get("aliases") or []),
                      "cluster": it.get("cluster"), "cell": list(it.get("cell") or []),
                      "siblings": list(it.get("siblings") or []), "baseline": bool(it.get("baseline")),
                      "primary": bool(it.get("primary"))})
    ctx.write_json("merges.json", {"strategy_family": fam_map, "axes": ax, "ideas": ideas})
    notes = raw.get("notes") or {}

    def lst(v):
        return "\n".join("- %s" % x for x in (v or [])) or "- none"
    ctx.write("03_POOL_NOTES.md", "## RE-RUN\n%s\n\n## LEAK CHECK\n%s\n\n## Merge log\n%s\n"
              % (lst(notes.get("rerun")), lst(notes.get("leak_check")), lst(notes.get("merge_log"))))
    return "merges.json: %d canonical ideas" % len(ideas)


@script("bs_map")
def _s_bs_map(ctx, step):
    bs(ctx, "map", ctx.run_dir, redo=curation_before(step["id"]))
    return "pool mapped"


@script("gap_round_end")
def _s_gap_round_end(ctx, step):
    bs(ctx, "map", ctx.run_dir, redo=curation_before(step["id"]))
    c = ctx.state.setdefault("counters", {})
    items = c.get("gap_round_items") or []
    if c.get("gap_counted") != items:  # a redo from 5.3c or 5.3m ends a round this step counted already: once
        c["gap_rounds"] = int(c.get("gap_rounds", 0)) + 1
        c["gap_prefix"] = int(c.get("gap_prefix", 0)) + len([i for i in items if str(i).startswith("G")])
        c["reopen_prefix"] = int(c.get("reopen_prefix", 0)) + len([i for i in items if str(i).startswith("R")])
        c["gap_counted"] = list(items)
    pool = ctx.read("03_POOL.md")
    saturated = False
    for ln in pool.split("\n"):
        cells = [x.strip() for x in ln.strip().strip("|").split("|")]
        if len(cells) >= 8 and re.match(r"^[GR]\d+$", cells[0]) and cells[0] in items and "SATURATED" in cells[7]:
            saturated = True
    if not saturated and _p_homog(ctx, None):
        from . import pipeline  # lazy: pipeline imports this module
        pipeline.rearm_loop(ctx, pipeline.step_ref("gap_loop"), "another gap round")
        ctx.cache["rearmed"] = True
        return "gap round %d done; another round follows" % c["gap_rounds"]
    return "gap round %d done%s" % (c["gap_rounds"], " (saturated)" if saturated else "")


@script("prepare_screen")
def _s_prepare_screen(ctx, step):
    bs(ctx, "schemas", ctx.run_dir)
    header = fill_partial(ctx, "SCREEN-HEADER")
    ctx.write("screen/header.md", header)
    bs(ctx, "prepare-screen", ctx.run_dir)
    return "screen prompts prepared"


QUICK_ALIAS_RE = re.compile(r"\bQ[AB]-\d+\b")  # the quick generators' idea IDs (QUICK-GEN: QA-01, QB-07)


@script("prepare_quick_screen")
def _s_prepare_quick_screen(ctx, step):
    """Q.3p (#51): the curated quick ideas as the screen's neutral lines (`Q-01 | title | pitch | mechanism`, the
    curator's neutral wording, no origin), then the screen's schema, header and one shuffled prompt per quick screen
    judge, as 6.1 prepares the screen. A line that names a quick generator's idea ID (QA-03) would tell the judges who
    wrote the idea: it is refused like the screen's origin-label check (6.7 rule 6)."""
    cur = ctx.read_json("quick/curated.json", None)
    ideas = cur.get("ideas") if isinstance(cur, dict) else None
    redo = [redo_cmd(ctx, curation_before(step["id"]))]  # a curation an older kit left, or one its contract missed
    if not isinstance(ideas, list) or not ideas:
        raise EngineError("quick/curated.json has no ideas, so the quick screen has nothing to score", fix=redo)
    rows, seen = [], set()
    for idea in ideas:
        iid = clean(idea.get("id")) if isinstance(idea, dict) else ""
        if not iid or iid in seen:
            raise EngineError("quick/curated.json: %s" % ("an idea without an id" if not iid else
                                                           "the id %s appears twice" % iid), fix=redo)
        seen.add(iid)
        row = "%s | %s | %s | %s" % (iid, clean(idea.get("title")), clean(idea.get("pitch")),
                                     clean(idea.get("mechanism")))
        m = QUICK_ALIAS_RE.search(row)
        if m:
            raise privacy_mod.PolicyBlock(
                "origin_label_check", "Debiasing rule: the quick screen line of %s contains the idea ID %s, which "
                "reveals which model wrote it; remove it from that idea's title, pitch or mechanism in "
                "quick/curated.json." % (iid, m.group(0)))
        rows.append(row)
    ctx.write("screen/ideas.md", "\n".join(rows) + "\n")
    _s_prepare_screen(ctx, step)
    return "quick screen prepared: %d ideas, judges %s" % (len(rows), ", ".join(ctx.seats.get("screen_judges") or []))


def fill_partial(ctx, name):
    """Fill a partial template (SCREEN-HEADER, TOURNAMENT-HEADER); a missing template is a clear error."""
    from . import builders
    text = load_template(name)
    if text is None:
        raise EngineError("template %s is missing (templates/prompts/%s.md)" % (name, name),
                          fix=["reinstall the kit: install.py update"])
    return builders.fill(ctx, text, {"family": ctx.host_family, "template": name}).rstrip() + "\n"


@script("screen_tally")
def _s_screen_tally(ctx, step):
    bs(ctx, "screen", ctx.run_dir)
    render_shortlist(ctx)
    return "%d ideas shortlisted" % len(shortlist_ids(ctx))


def _md_table(headers, rows):
    out = ["| %s |" % " | ".join(headers), "|%s|" % "|".join(["---"] * len(headers))]
    for r in rows:
        out.append("| %s |" % " | ".join(clean(c) for c in r))
    return "\n".join(out)


def _judge_stage(stage, key):
    """True when a run.json.provisional stage label belongs to the screen (6.x) or tournament (9.x, Q.5) judges."""
    s = str(stage or "").strip().lower()
    if key == "screen_judges":
        return "screen" in s or s.startswith("6.")
    return "tournament" in s or s.startswith("9.") or s.startswith("q.5") or s == "quick"


def judges_line(ctx, key):
    """The judge seats of a stage; a seat answered by a substitute reads '<seat> (PROVISIONAL: <actual>)'."""
    subs = {}
    for p in ctx.state.get("provisional") or []:
        if isinstance(p, dict) and _judge_stage(p.get("stage"), key):
            subs.setdefault(p.get("seat"), []).append(str(p.get("actual") or "?"))
    fams = ctx.seats.get(key) or []
    return ", ".join("%s%s" % (f, " (PROVISIONAL: %s)" % " -> ".join(subs[f]) if f in subs else
                               " (PROVISIONAL)" if is_alt(f) else "") for f in fams) or "none"


def render_shortlist(ctx, g4=None):
    """04_SHORTLIST.md from templates/docs/SHORTLIST.md (the Rescued: line is what bs.py and the engine read). g4: the
    G4 answer being applied (the recorded one otherwise). The Rescued: line holds the rescued IDs only, since every ID
    on it is rescued; each reason follows on its own `- <ID>: <reason>` line, its line breaks collapsed."""
    from . import builders
    from . import gates
    data = ctx.read_json("screen/shortlist.json", {}) or {}
    info = idea_lines(ctx)
    rescued = g4 if g4 is not None else ((ctx.state.get("gates") or {}).get("G4") or {}).get("answer") or {}
    rescues = [r for r in rescued.get("rescue") or [] if isinstance(r, dict) and r.get("id")]
    rescued_text = "none"
    if rescues:
        rescued_text = "%s\n\n%s" % (", ".join(dict.fromkeys(str(r["id"]) for r in rescues)), "\n".join(
            "- %s: %s" % (r["id"], " ".join(str(r.get("reason") or "").split()) or "rescued by the user")
            for r in rescues))
    parked = ctx.state.get("parked") or []
    table = ctx.read("screen/table.md")
    audits = "\n\n".join(x for x in (sections_by_prefix(table, ["Judge agreement", "Own-origin gap"]),) if x)
    killed = [[i, info.get(i, {}).get("title", ""), "K1 (gate failed by 2+ judges)"] for i in data.get("killed_gate")
              or []]
    killed += [[i, info.get(i, {}).get("title", ""), "K3 floor FAIL (you may rescue)"] for i in data.get("floor_fail")
               or []]
    killed += [[i, info.get(i, {}).get("title", ""), "killed by the user (confirmed flag or K4)"]
               for i in ctx.state.get("killed") or []]
    mapping = {
        "RUN_NAME": ctx.state.get("run", ""), "JUDGES_LINE": judges_line(ctx, "screen_judges"),
        "PROVISIONAL_BANNER": gates.provisional_banner(ctx),
        "SHORTLIST_TABLE": _md_table(["id", "title", "score", "reason"], [
            [s.get("id"), info.get(s.get("id"), {}).get("title", ""), s.get("score"), s.get("reason")]
            for s in data.get("shortlist") or [] if isinstance(s, dict)]),
        "KILLED_TABLE": _md_table(["id", "title", "rule"], killed) if killed else "none",
        "FLAGS_TABLE": _md_table(["id", "title"], [[i, info.get(i, {}).get("title", "")] for i in
                                                    data.get("flagged_gate") or []]) if data.get("flagged_gate")
        else "none",
        "BORDERLINE_TABLE": ", ".join(data.get("borderline") or []) or "none",
        "PARKED_TABLE": _md_table(["id", "title", "matches"], [
            [p, info.get(p, {}).get("title", ""), "CROWDED with no differentiator (checks/%s.md)" % p]
            for p in parked]) if parked else "none",
        "SCREEN_AUDITS": audits or "none", "RESCUED": rescued_text}
    text = builders.render_doc("SHORTLIST", mapping,
                               fallback=lambda: _shortlist_builtin(ctx, data, rescued_text, parked))
    ctx.write("04_SHORTLIST.md", text)


def _shortlist_builtin(ctx, data, rescued_text, parked):
    lines = ["# SHORTLIST", "", "Screened by %s (neutral lines, random orders)." %
             ", ".join(ctx.seats.get("screen_judges") or []), "", "## Shortlist", ""]
    for s in data.get("shortlist") or []:
        if isinstance(s, dict):
            info = idea_lines(ctx).get(s.get("id"), {})
            lines.append("- %s %s (score %s): %s" % (s.get("id"), info.get("title", ""), s.get("score"),
                                                     s.get("reason")))
    for key, title in (("killed_gate", "Killed by gate (K1)"), ("floor_fail", "Floor FAIL (K3; you may rescue)"),
                       ("flagged_gate", "Flagged by one judge"), ("borderline", "Borderline")):
        vals = data.get(key) or []
        lines += ["", "## %s" % title, "", ", ".join(vals) if vals else "none"]
    lines += ["", "Rescued: %s" % rescued_text]
    if parked:
        lines += ["", "## Parked (K4 candidate)", ""] + ["- %s: CROWDED with no differentiator" % p for p in parked]
    table = ctx.read("screen/table.md")
    if table:
        lines += ["", "## Screen table", "", table.strip()]
    return "\n".join(lines) + "\n"


@script("k4")
def _s_k4(ctx, step):
    # parked and killed are derived here from this step's checks and the gate answers, never accumulated over runs of
    # the step (I10): killed = the flags confirmed at G4 (G5 adds its kills when it is answered); parked = the K4
    # candidates (hands-on: the ones G5 neither kills nor keeps, set when G5 is answered)
    before = (ctx.state.get("killed") or [], ctx.state.get("parked") or [])
    g4 = ((ctx.state.get("gates") or {}).get("G4") or {}).get("answer") or {}
    cands = []
    if ctx.variant == "growth" or (ctx.variant == "software" and is_repo(ctx)):
        note = "K4 does not apply in this variant (prior art is evidence it works)"
    else:
        for iid in shortlist_ids(ctx):
            v, d = check_verdict(ctx, iid)
            if v == "CROWDED" and (not d or re.match(r"^(none|none found|-)\W*$", d, re.I)):
                cands.append(iid)
        note = "K4 candidates: %s" % (", ".join(cands) or "none")
    ctx.state["k4_candidates"] = cands
    ctx.state["killed"] = sorted(set(i for i in g4.get("confirm_flags") or [] if i))
    ctx.state["parked"] = list(cands) if ctx.autopilot != "hands-on" else []
    if ctx.state["parked"]:
        note = "K4 candidates parked (not killed): %s" % ", ".join(cands)
    if (ctx.state["killed"], ctx.state["parked"]) != before:
        render_shortlist(ctx)
    return note


@script("finalists")
def _s_finalists(ctx, step):
    if ctx.mode == "proposal":
        ids = ["I-001"] + [b["id"] for b in idea_blocks(ctx.read("05_EVOLVED.md"), "E")]
        ctx.state["finalists"] = ids[:3]
        return "finalists: %s" % ", ".join(ctx.state["finalists"])
    pool, ev = finalist_pool(ctx), set(evolved_ids(ctx))
    evolved = [i for i in pool if i in ev]
    surv = [i for i in pool if i not in ev]
    if len(pool) <= 8:
        fin = pool
    else:
        # at most 8: the protected survivors (primary, tail slot, best human), then min(2, |E|) E ideas by CHECK
        # verdict (NOT LOCATED, ADJACENT, NOT CHECKED, CROWDED) and id, then the other survivors by screen score, and
        # further E ideas (by their parents' score) only when the survivors run out: an E idea's inherited score is a
        # proxy (an EVOLVE variant of the top idea inherits the top score), not a measured one (#45)
        scores = screen_scores(ctx)
        ranked = sorted(surv, key=lambda i: (-scores.get(i, 0.0), i))
        protected = [p for p in (ctx.read_json("primary.json", []) or []) if p in surv]
        data = ctx.read_json("screen/shortlist.json", {}) or {}
        protected += [s["id"] for s in data.get("shortlist") or [] if isinstance(s, dict)
                      and "tail slot" in str(s.get("reason")) and s.get("id") in surv]
        org = origins(ctx)
        protected += [i for i in ranked if org.get(i) in ("human", "human-mixed")][:1]
        protected = list(dict.fromkeys(protected))[:8]
        quota = sorted(evolved, key=lambda e: (CHECK_RANK.get(check_verdict(ctx, e)[0], 4), e))[:2]
        rest = sorted((i for i in pool if i not in protected and i not in quota),
                      key=lambda i: (i in ev, -scores.get(i, 0.0), i))
        chosen = set((protected + quota[:8 - len(protected)] + rest)[:8])
        fin = [i for i in pool if i in chosen]
    ctx.state["finalists"] = fin
    return "%d finalists" % len(fin)


@script("prepare_tournament")
def _s_prepare_tournament(ctx, step):
    canonical_cards(ctx)
    if not ctx.exists("tournament/verdicts.schema.json"):
        bs(ctx, "schemas", ctx.run_dir)  # quick and proposal modes skip 6.1
    ctx.write("tournament/header.md", fill_partial(ctx, "TOURNAMENT-HEADER"))
    args = ["prepare-tournament", ctx.run_dir]
    if ctx.mode == "deep" and len(ctx.state.get("finalists") or []) <= 6:
        args.append("--per-pair")
    bs(ctx, *args)
    return "tournament prompts prepared"


@script("tournament_tally")
def _s_tournament_tally(ctx, step):
    from . import builders
    from . import gates
    bs(ctx, "tournament", ctx.run_dir)
    pre = ctx.read("tournament/precommit.md") or "(no gut pick: %s)" % (
        "skipped" if gut_picks(ctx) == [] else "missing")
    pre = re.sub(r"^# .*\n?", "", pre, count=1).strip() or pre  # its own H1 would break the section outline
    fin = ctx.state.get("finalists") or []
    info = idea_lines(ctx)
    result = ctx.read("tournament/result.md")
    res = tournament_result(ctx)
    raw = [[r.get("id"), info.get(r.get("id"), {}).get("title", ""), r.get("points"), r.get("max")]
           for r in res.get("raw") or [] if isinstance(r, dict)]
    deb = [[d.get("rank") or n, d.get("id"), info.get(d.get("id"), {}).get("title", ""), d.get("pct"),
            "%s-%s" % tuple(d["ci"]) if d.get("ci") else "-",
            "%s-%s" % tuple(d["rank_range"]) if d.get("rank_range") else "-", d.get("n")]
           for n, d in enumerate([d for d in res.get("debiased") or [] if isinstance(d, dict)], 1)]
    ranking_text = section(result, "Debiased ranking") or section(result, "Debiased standings")
    notes = "\n".join(ln for ln in ranking_text.split("\n") if ln.strip() and not re.match(r"^\d+\.", ln))
    contested = ["- %s vs %s: %s" % (c[0], c[1], c[2] if len(c) > 2 else "the judges disagree")
                 for c in res.get("contested") or [] if isinstance(c, (list, tuple)) and len(c) >= 2]
    audits = sections_by_prefix(result, ["Judge position consistency", "Judge substitutions", "Self-preference audit",
                                         "Standings excluding flagged", "Warnings"])
    prov = gates.provisional_banner(ctx)
    if not prov and (ctx.seats.get("single_family") or any(is_alt(j) for j in ctx.seats.get("tournament_judges")
                                                           or [])):
        prov = "PROVISIONAL: at least one judge seat was a same-vendor substitute (-alt)."
    mapping = {"RUN_NAME": ctx.state.get("run", ""), "JUDGES_LINE": judges_line(ctx, "tournament_judges"),
               "PROVISIONAL_BANNER": prov, "GUT_PICK": pre.strip(),
               "FINALISTS_TABLE": _md_table(["id", "title"], [[i, info.get(i, {}).get("title", "")] for i in fin]),
               "STANDINGS": ((notes + "\n\n" if notes else "") + _md_table(
                   ["rank", "id", "title", "score %", "90% CI", "rank range", "pairs"], deb)) if deb else
               (ranking_text or "(no debiased standings)"),
               "RAW_STANDINGS": _md_table(["id", "title", "points", "max"], raw) if raw else
               (section(result, "Standings") or "(no raw standings)"),
               "CONTESTED": "\n".join(contested) or "none", "AUDITS": audits or "none"}

    def builtin():
        lines = ["# TOURNAMENT", "", "## Pre-commit (your gut pick, written before any tally)", "", pre.strip(), "",
                 "## Finalists", ""] + ["- %s %s" % (i, info.get(i, {}).get("title", "")) for i in fin]
        lines += ["", result.strip()]
        if prov:
            lines += ["", prov]
        return "\n".join(lines) + "\n"
    ctx.write("06_TOURNAMENT.md", builders.render_doc("TOURNAMENT", mapping, fallback=builtin))
    return "tournament tallied"


@script("top")
def _s_top(ctx, step):
    fin = ctx.state.get("finalists") or []
    rk = ranking(ctx)
    top = suggested_top(ctx, rk)
    g7 = ((ctx.state.get("gates") or {}).get("G7") or {}).get("answer") or {}
    if g7.get("picks"):
        top = [p for p in g7["picks"] if p in fin] or top
    ctx.state["top"] = top
    parts = ["# TOP", ""]
    if rk["note"]:
        parts += ["Note: the %s." % rk["note"], ""]
    for i in top:
        parts += ["## %s" % i, card_text(ctx, i), "", "### Check", ctx.read("checks/%s.md" % i).strip() or "(none)",
                  ""]
    ctx.write("07_TOP.md", "\n".join(parts) + "\n")
    return "top: %s" % ", ".join(top)


@script("decision")
def _s_decision(ctx, step):
    write_decision(ctx)
    return "08_DECISION.md written"


K6_LINE = re.compile(r"^Killed: (\S+) - K6\b", re.M)


def k6_killed(state):
    """The ideas their own probe killed (the `Killed: <ID> - K6` lines of run.json decision_log; a run an older kit
    started gets them from 08_DECISION.md when it loads, migrate.upgrade_decisions): never the runner-up or the chosen
    idea again."""
    return set(K6_LINE.findall("\n".join(str(x) for x in state.get("decision_log") or [])))


def with_decision_log(text, lines):
    """08_DECISION.md text with decision lines (a switch, a K6 kill) after it, one paragraph each."""
    lines = [str(x).strip() for x in lines or [] if str(x).strip()]
    return text.rstrip() + "".join("\n\n" + x for x in lines) + "\n" if lines else text


def write_decision(ctx):
    """08_DECISION.md from the G8b answer and the choice, then the run's decision_log (the switches and K6 kills
    recorded since the decision): 10.6 and quick Q.8 rewrite the file, and the log survives every rewrite (6.10)."""
    g = (ctx.state.get("gates") or {}).get("G8b") or {}
    ans = g.get("answer") or {}
    choice = ctx.state.get("choice") or {}
    chosen = choice.get("idea")
    info = idea_lines(ctx)
    auto = g.get("by") == "auto"
    why = ans.get("why") or _why_from_reply(ans.get("reply") or "", chosen)
    fin = ctx.state.get("finalists") or []
    log = ctx.state.get("decision_log") or []
    k6 = k6_killed(ctx.state)  # killed by their probe, not unchosen
    lines = ["# DECISION: %s" % ctx.state.get("run", "")]
    if auto:
        lines.append("AUTO-DECISION: no human decision was made (full-auto); rule: %s" % (ans.get("rule") or
                                                                                         "suggested by rule"))
    lines.append("Chosen (to test): %s - %s - why, in the user's words: %s"
                 % (chosen, info.get(chosen, {}).get("title", ""), why or "(accepted the suggestion)"))
    if ans.get("bundle"):
        lines.append("Chosen bundle (growth): %s" % ", ".join(ans["bundle"]))
    lines.append("Runner-up: %s" % (choice.get("runner_up") or "none"))
    for p in ans.get("park") or []:
        lines.append("Parked: %s - revisit when the chosen idea's probe result is known" % p)
    for p in ctx.state.get("parked") or []:
        lines.append("Parked: %s - K4 candidate (CROWDED, no differentiator)" % p)
    for k in ctx.state.get("killed") or []:
        lines.append("Killed: %s - K4 confirmed by the user" % k)
    dissent = []
    for i, vs in review_verdicts(ctx).items():
        if i == chosen:
            dissent += [v for v in vs if "DON'T BACK" in v]
    lines.append("Dissent recorded: %s" % ("; ".join(dissent) or "none"))
    not_doing = [i for i in fin if i not in (chosen, choice.get("runner_up")) and i not in k6]
    lines.append("Not doing (and why): %s" % ("; ".join("%s %s (not chosen at the decision)" %
                                                        (i, info.get(i, {}).get("title", "")) for i in not_doing[:5])
                                             or "none listed"))
    lines.append("Pre-registered test: see 09_PROBE.md (written at Stage 11 before running)")
    date = textio.now_iso()[:10]
    run = ctx.state.get("run", "")
    rows = []
    if chosen:
        rows.append("| %s | %s | %s | %s | chosen | %s | - |" % (date, run, chosen, clean(info.get(chosen, {}).get(
            "title", "")), _cut_words(clean(why), 60) or "decision"))
    if choice.get("runner_up"):
        r = choice["runner_up"]
        rows.append("| %s | %s | %s | %s | runner-up | - | if the chosen idea's probe misses |" %
                    (date, run, r, clean(info.get(r, {}).get("title", ""))))
    for p in (ans.get("park") or []) + (ctx.state.get("parked") or []):
        rows.append("| %s | %s | %s | %s | parked | K4 or user | new evidence |" %
                    (date, run, p, clean(info.get(p, {}).get("title", ""))))
    for k in ctx.state.get("killed") or []:
        rows.append("| %s | %s | %s | %s | killed | K4 | - |" % (date, run, k, clean(info.get(k, {}).get("title",
                                                                                                          ""))))
    lines.append("LEDGER rows:")
    lines += rows
    from . import builders
    parked = ["%s - revisit when the chosen idea's probe result is known" % p for p in ans.get("park") or []]
    parked += ["%s - K4 candidate (CROWDED, no differentiator)" % p for p in ctx.state.get("parked") or []]
    killed = ["%s - K4 confirmed by the user" % k for k in ctx.state.get("killed") or []]
    stamp = ""
    if auto:
        stamp = "AUTO-DECISION: chosen by rule (%s); no human decision was made." % (ans.get("rule") or
                                                                                   "suggested by rule")
    mapping = {"RUN_NAME": run, "DECISION_STAMP": stamp,
               "CHOSEN": "%s %s" % (chosen, info.get(chosen, {}).get("title", "")),
               "WHY": ('"%s"' % " ".join(why.split())) if why else "(accepted the suggestion by rule)",
               "BUNDLE_LINE": ("Chosen bundle (growth): %s" % ", ".join(ans["bundle"])) if ans.get("bundle") else "",
               "RUNNER_UP": "%s %s" % (choice.get("runner_up"), info.get(choice.get("runner_up"), {}).get("title", ""))
               if choice.get("runner_up") else "none",
               "PARKED": "; ".join(parked) or "none", "KILLED": "; ".join(killed) or "none",
               "DISSENT": "; ".join(dissent) or "none",
               "NOT_DOING": "; ".join("%s %s (not chosen at the decision)" % (i, info.get(i, {}).get("title", ""))
                                      for i in not_doing[:5]) or "none listed",
               "LEDGER_ROWS": "\n".join(rows) or "none"}
    # a Markdown hard line break (two trailing spaces) after each field, so viewers do not merge the lines into one
    # paragraph while every field stays on its own line for the parsers; the LEDGER table stays together
    head = lines[:lines.index("LEDGER rows:")] if "LEDGER rows:" in lines else lines
    tail = lines[len(head):]
    mapping["DECISION_BODY"] = "\n".join(head[:1] + [ln + "  " for ln in head[1:]]) + (
        ("\n\n" + tail[0] + "\n\n" + "\n".join(tail[1:])) if tail else "")
    mapping["DATE"] = date
    body = builders.render_doc("DECISION", mapping, fallback=mapping["DECISION_BODY"] + "\n")
    ctx.write("08_DECISION.md", with_decision_log(body, log))
    if not ctx.state.get("ledger_written"):
        append_ledger(ctx, rows)
        ctx.state["ledger_written"] = True


_DIRECTIVE_RE = re.compile(r"\b(runner[ -]?up|park(?:ed)?|bundle)\s*:.*$", re.I)


def _why_from_reply(reply, chosen):
    """The user's reason from a free G8b reply: directive lines (runner-up:, park:, bundle:) and a leading chosen ID
    are removed, so 08_DECISION.md quotes only the reason."""
    kept = []
    for line in (reply or "").split("\n"):
        line = _DIRECTIVE_RE.sub("", line).strip()
        if chosen:
            line = re.sub(r"^\s*(?:choose|pick|chosen)?\s*:?\s*%s\b[\s,.:;-]*" % re.escape(chosen), "", line,
                          flags=re.I).strip()
        if line:
            kept.append(line)
    return " ".join(kept)


def _cut_words(text, n):
    text = " ".join((text or "").split())
    if len(text) <= n:
        return text
    cut = text[:n].rsplit(" ", 1)[0].rstrip(" ,.;:")
    return (cut or text[:n]) + "..."


def append_ledger(ctx, rows):
    ledger = os.path.join(os.path.dirname(ctx.run_dir), "LEDGER.md")
    if not os.path.exists(ledger):
        textio.write_text_atomic(ledger, st.LEDGER_HEADER)
    for r in rows:
        textio.append_line(ledger, r)


@script("synthesis_check")
def _s_synthesis_check(ctx, step):
    stop = _p_synth_stop(ctx, None)
    return "WHOLE-EFFORT: STOP (the whole effort is in question)" if stop else "WHOLE-EFFORT: CONTINUE"


QUICK_CURATOR_NOTE = ("quick mode: the curator's own scores picked the finalists (no blind quick screen: it needs "
                      "screen judges of two model vendors)")


@script("quick_pick")
def _s_quick_pick(ctx, step):
    """Q.4: bs.py quick-pick on the blind quick screen's scores when Q.3s ran (#51); a run without it (one model
    family, or seated by an older kit) keeps the curator's scores, flagged in finalists.json and in a run note."""
    from . import pipeline  # lazy: pipeline imports this module
    blind = st.step_state(ctx.state, pipeline.step_ref("quick_screen")) == "done"
    bs(ctx, "quick-pick", ctx.run_dir, "--scores", "blind" if blind else "curator", redo=curation_before(step["id"]))
    if not blind:
        st.add_note(ctx.state, QUICK_CURATOR_NOTE)
    fin = ctx.read_json("quick/finalists.json", None)
    ids = []
    if isinstance(fin, dict):
        fin = fin.get("finalists") or fin.get("ideas") or []
    for f in fin or []:
        ids.append(str(f.get("id")) if isinstance(f, dict) else str(f))
    if not ids:
        order, _ = parse_cards(ctx.read("tournament/cards.md"))
        ids = order
    ctx.state["finalists"] = ids
    ctx.state["top"] = ids
    return "%d quick finalists" % len(ids)


def quick_probe_for(ctx, iid):
    data = ctx.read_json("quick/probe.json", {}) or {}
    for key in ("probes", "ideas", "items"):
        for p in data.get(key) or []:
            if isinstance(p, dict) and str(p.get("id")) == str(iid):
                return p
    return data if isinstance(data, dict) else {}


@script("quick_decision")
def _s_quick_decision(ctx, step):
    choice = ctx.state.get("choice") or {}
    chosen = choice.get("idea")
    info = idea_lines(ctx).get(chosen, {})
    probe = quick_probe_for(ctx, chosen)

    def g(*keys):
        for k in keys:
            if probe.get(k):
                return str(probe[k])
        return "NOT STATED"
    from . import builders
    ans = ((ctx.state.get("gates") or {}).get("G8b") or {}).get("answer") or {}
    auto = ((ctx.state.get("gates") or {}).get("G8b") or {}).get("by") == "auto"
    why = ans.get("why") or ans.get("reply") or ""
    test = g("probe", "cheapest_test", "test")
    extra = [x for x in ("metric: " + g("metric") if probe.get("metric") else "",
                         "sample: " + g("sample") if probe.get("sample") else "",
                         "deadline: " + g("deadline") if probe.get("deadline") else "") if x]
    if extra:
        test = "%s (%s)" % (test, "; ".join(extra))
    runner = choice.get("runner_up")
    mapping = {"RUN_NAME": ctx.state.get("run", ""),
               "DECISION_STAMP": "AUTO-DECISION: chosen by rule (%s); no human decision was made." % (
                   ans.get("rule") or "suggested by rule") if auto else "",
               "CHOSEN": "%s %s" % (chosen, info.get("title", "")),
               "WHY": ('"%s"' % " ".join(why.split())) if why else "(accepted the suggestion by rule)",
               "RUNNER_UP": ("%s %s" % (runner, idea_lines(ctx).get(runner, {}).get("title", ""))) if runner
               else "none",
               "RISKIEST_ASSUMPTION": g("riskiest_assumption", "assumption"), "CHEAPEST_TEST": test,
               "PASS_THRESHOLD": g("pass_threshold", "threshold"), "KILL_CRITERION": g("kill_criterion"),
               "NEXT_ACTION": g("next_action")}
    lines = ["# QUICK DECISION: %s" % ctx.state.get("run", ""),
             "Chosen (to test): %s - %s" % (mapping["CHOSEN"], mapping["WHY"]),
             "Runner-up: %s" % mapping["RUNNER_UP"],
             "Riskiest assumption: %s" % mapping["RISKIEST_ASSUMPTION"],
             "Cheapest test: %s" % test, "Pass threshold (written before running): %s" % mapping["PASS_THRESHOLD"],
             "Kill criterion: %s" % mapping["KILL_CRITERION"], "Next action: %s" % mapping["NEXT_ACTION"],
             "Novelty NOT checked - run Stage 7 before investing."]
    if auto:
        lines.insert(1, mapping["DECISION_STAMP"])
    ctx.write("QUICK_DECISION.md", builders.render_doc("QUICK-DECISION", mapping, fallback="\n".join(lines) + "\n"))
    write_decision(ctx)
    probe_md = ["# PROBE (quick): %s" % mapping["CHOSEN"], "",
                "## 1. Walk-through", "Quick mode: no walk-through; see QUICK_DECISION.md.", "",
                "## 2. Riskiest assumption", mapping["RISKIEST_ASSUMPTION"], "",
                "## 3. Probe design", test, "", "Pass threshold (written before running): %s" % mapping["PASS_THRESHOLD"],
                "", "## 4. Kill criterion", mapping["KILL_CRITERION"], "", "RESULT: PENDING"]
    if not ctx.exists("09_PROBE.md"):
        ctx.write("09_PROBE.md", "\n".join(probe_md) + "\n")
    return "QUICK_DECISION.md written"


# ---- stage 12-14 scripts live in render_arch / render / handoff; registered here by name.

def _arch(fn_name):
    def fn(ctx, step):
        from . import render_arch
        return getattr(render_arch, fn_name)(ctx, step)
    return fn


def _render(fn_name):
    def fn(ctx, step):
        from . import render
        return getattr(render, fn_name)(ctx, step)
    return fn


def _handoff(fn_name):
    def fn(ctx, step):
        from . import handoff
        return getattr(handoff, fn_name)(ctx, step)
    return fn


for _n in ("arch_brief", "drivers_after", "candidates_after", "judges_after", "arch_matrix", "stack_lite",
           "arch_render_lint", "arch_fix_after", "arch_readme", "approach_after", "decisions_after"):
    SCRIPTS[_n] = _arch(_n)
for _n in ("proposal_packs", "proposal_assemble", "proposal_render"):
    SCRIPTS[_n] = _render(_n)
for _n in ("handoff_seed", "handoff_final"):
    SCRIPTS[_n] = _handoff(_n)


def run_script(ctx, name, step):
    fn = SCRIPTS.get(name)
    if fn is None:
        raise EngineError("pipeline.json names an unknown script: %s" % name)
    return fn(ctx, step)
