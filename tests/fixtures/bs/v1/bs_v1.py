#!/usr/bin/env python3
"""bs.py - deterministic bookkeeping for the ultimate-brainstorm pipeline.

Python 3.8+ standard library only. RUN is a run folder such as brainstorm/2026-09-23-habit-coach.

  init RUN                        create the run's sub-folders, brainstorm/LEDGER.md and an empty
                                  00_HUMAN_SEEDS.md template (each only if missing)
  status RUN                      list stage outputs present/missing and name the next stage
  schemas RUN                     write screen/screen.schema.json, tournament/verdicts.schema.json and
                                  prompts/lens.schema.json (criteria names come from RUN/criteria.json)
  map RUN                         merges.json (from the CURATOR) -> random I-### IDs, clusters.json,
                                  origins.json, primary.json, screen/ideas.md and 03_POOL.md (YIELD,
                                  COVERAGE, HOMOGENIZED computed here; 03_POOL_NOTES.md appended)
  prepare-screen RUN              screen/ideas.md + screen/header.md -> screen/claude.prompt.md, screen/gpt.prompt.md
  screen RUN                      screen/*.out.json -> screen/table.md + screen/shortlist.json
  prepare-tournament RUN [--per-pair]
                                  tournament/cards.md + tournament/header.md -> judge prompts + .map.json files
  tournament RUN                  tournament/*.out.json -> tournament/result.md
  dupcheck RUN [--threshold T]    flag near-duplicate ideas in screen/ideas.md (sentence-transformers
                                  embeddings if installed, otherwise word overlap)
"""
import collections
import glob
import hashlib
import itertools
import json
import os
import random
import re
import string
import sys

FAMILIES = ("claude", "gpt")
HUMAN_ORIGINS = ("human", "human-mixed")
GATES = ("g1", "g2", "g3")
SUBDIRS = ("prompts", "pool", "screen", "checks", "tournament", "redteam", "logs")
LEDGER_HEADER = (
    "# Brainstorm ledger (append-only; one row per finalist, parked or killed shortlist idea)\n\n"
    "| date | run | id | title | status | reason / K-rule | revive trigger |\n"
    "|---|---|---|---|---|---|---|\n"
)
SEEDS_TEMPLATE = (
    "# Human seeds (write alone, before seeing any AI idea; or replace everything with 'SKIPPED: <reason>')\n\n"
    "## Problem\n\n## Primary idea (to pressure-test)\n\n## Ideas\n\n## Obvious\n\n## Off-limits\n"
)
DEFAULT_STRATEGIES = ("S1", "S2", "S3", "S4", "S5")
# Stage checks: plain file patterns, or special tokens handled in check_item():
#   @seeds (Ideas or Primary idea section non-empty, or SKIPPED), @pool (every strategy in the 00_RUN.md
#   strategy -> family map has a pool file), @checks (a checks/<ID>.md for every shortlisted, rescued and
#   primary ID), @evolved-checks (a check for every E-ID in 05_EVOLVED.md), @probe-result (a RESULT: line).
FULL_STAGES = [
    (1, "Sealed human seeds", ["@seeds"]),
    (2, "Frame", ["01_FRAME.md", "criteria.json"]),
    (3, "Ground", ["02_CONTEXT.md"]),
    (4, "Diverge", ["@pool"]),
    (5, "Merge and map", ["03_POOL.md", "clusters.json", "origins.json", "screen/ideas.md"]),
    (6, "Screen", ["04_SHORTLIST.md", "screen/shortlist.json"]),
    (7, "Reality checks", ["@checks"]),
    (8, "Evolve", ["05_EVOLVED.md", "@evolved-checks"]),
    (9, "Tournament", ["tournament/result.md", "06_TOURNAMENT.md"]),
    (10, "Red-team and decide", ["07_REDTEAM.md", "08_DECISION.md"]),
    (11, "Probe", ["09_PROBE.md", "@probe-result"]),
    (12, "Handoff", ["10_HANDOFF.md"]),
]
QUICK_STAGES = [
    (1, "Quick: seeds and criteria", ["@seeds", "criteria.json"]),
    (2, "Quick: generate", ["pool/*"]),
    (3, "Quick: cards", ["tournament/cards.md"]),
    (4, "Quick: other-family check", ["tournament/result.md"]),
    (5, "Quick: decision", ["QUICK_DECISION.md"]),
]
ID_RE = r"\b(?:I|E)-\d+\b"
STOP = set("the and for with that this from into your their them they are was were will would can could "
           "should have has had not but you our its via per use uses using make makes made each every "
           "what when where which who how why idea ideas user users".split())


def read_text(path):
    """Read UTF-8 (with or without BOM) or UTF-16 text (Windows PowerShell 5.1 '>' writes UTF-16)."""
    with open(path, "rb") as f:
        raw = f.read()
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return raw.decode("utf-16")
    return raw.decode("utf-8-sig")


def load(path):
    """Parse JSON, tolerating ```json fences or a sentence of preamble around the object."""
    text = read_text(path)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end < start:
            raise
        return json.loads(text[start:end + 1])


def write(path, text):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def opt_json(path):
    return load(path) if os.path.exists(path) else {}


def rng(root, tag):
    """Reproducible randomness per run and per call (same run -> same shuffles)."""
    name = os.path.basename(os.path.normpath(os.path.abspath(root)))
    return random.Random(hashlib.sha256(f"{name}|{tag}".encode("utf-8")).hexdigest())


def is_false(value):
    return value is False or str(value).strip().lower() == "false"


def as_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def find_key(keys, needle):
    for key in keys:
        if needle in key.lower():
            return key
    return None


# ---------------------------------------------------------------- init / status

def init(root):
    for sub in SUBDIRS:
        os.makedirs(os.path.join(root, sub), exist_ok=True)
    ledger = os.path.join(os.path.dirname(os.path.normpath(os.path.abspath(root))), "LEDGER.md")
    if not os.path.exists(ledger):
        write(ledger, LEDGER_HEADER)
    seeds = os.path.join(root, "00_HUMAN_SEEDS.md")
    if not os.path.exists(seeds):
        write(seeds, SEEDS_TEMPLATE)
    print(f"ready: {root} (sub-folders: {', '.join(SUBDIRS)}); ledger: {ledger}; "
          f"seeds template: {os.path.abspath(seeds)}")


def run_text(root):
    path = os.path.join(root, "00_RUN.md")
    return read_text(path) if os.path.exists(path) else ""


def mode_of(root):
    match = re.search(r"^\W*mode\W*:\W*(quick|standard|deep)", run_text(root), re.M | re.I)
    return match.group(1).lower() if match else "standard"


def other_family_provisional(root):
    """True when 00_RUN.md says the second judge is a same-vendor substitute (none / PROVISIONAL)."""
    match = re.search(r"other family\s*:\s*(.*)$", run_text(root), re.M | re.I)
    return bool(match) and bool(re.search(r"\bnone\b|provisional", match.group(1), re.I))


def section(text, heading):
    """Body of a '## <heading>...' section (up to the next '## ' heading)."""
    match = re.search(r"^##\s*" + re.escape(heading) + r"[^\n]*\n(.*?)(?=^##\s|\Z)", text, re.M | re.S | re.I)
    return match.group(1).strip() if match else ""


def seeds_done(root):
    files = glob.glob(os.path.join(root, "00_HUMAN_SEEDS*.md"))
    for path in files:
        text = read_text(path)
        if re.search(r"^\W*SKIPPED\b", text, re.M) or section(text, "Ideas") or section(text, "Primary idea"):
            return True, ""
    return False, "Ideas section empty (write ideas or 'SKIPPED: <reason>')" if files else "file missing"


def strategies(root):
    """Strategy keys from the '- strategy -> family map: S1=claude S2=claude S3=gpt ...' line of 00_RUN.md."""
    match = re.search(r"strategy\s*->\s*family map\s*:\s*(.*)$", run_text(root), re.M | re.I)
    keys = re.findall(r"(?<![\w-])([A-Z]+\d*)(?:-[A-Za-z-]+)?\s*[=:]\s*[A-Za-z]", match.group(1)) if match else []
    return keys or list(DEFAULT_STRATEGIES)


def ids_in(text):
    return re.findall(ID_RE, text)


def check_item(root, item):
    """Return (done, note) for one stage requirement."""
    if item == "@seeds":
        return seeds_done(root)
    if item == "@pool":
        miss = [s for s in strategies(root) if not glob.glob(os.path.join(root, "pool", s + "[_.]*"))]
        return not miss, ("missing pool files for " + ", ".join(miss)) if miss else ""
    if item == "@checks":
        path = os.path.join(root, "screen", "shortlist.json")
        if not os.path.exists(path):
            return False, "screen/shortlist.json missing"
        want = [s["id"] for s in load(path).get("shortlist", [])]
        short = os.path.join(root, "04_SHORTLIST.md")
        if os.path.exists(short):
            for line in read_text(short).splitlines():
                if re.match(r"^\W*Rescued\W*:", line, re.I):
                    want += ids_in(line)
        miss = sorted({i for i in want if not os.path.exists(os.path.join(root, "checks", i + ".md"))})
        return not miss, ("no check for " + ", ".join(miss)) if miss else ""
    if item == "@evolved-checks":
        path = os.path.join(root, "05_EVOLVED.md")
        eids = re.findall(r"^#+\s*(E-\d+)", read_text(path), re.M) if os.path.exists(path) else []
        miss = sorted({i for i in eids if not os.path.exists(os.path.join(root, "checks", i + ".md"))})
        return not miss, ("no check for " + ", ".join(miss)) if miss else ""
    if item == "@probe-result":
        path = os.path.join(root, "09_PROBE.md")
        ok = os.path.exists(path) and re.search(r"^\W*RESULT\s*:", read_text(path), re.M)
        return bool(ok), "" if ok else "no 'RESULT:' line yet (probe designed but not reported)"
    return bool(glob.glob(os.path.join(root, item))), ""


def status(root):
    mode = mode_of(root)
    stages = QUICK_STAGES if mode == "quick" else FULL_STAGES
    nxt = None
    print(f"run: {root}   mode: {mode}")
    for num, name, items in stages:
        results = [check_item(root, i) for i in items]
        done = all(r[0] for r in results)
        notes = "; ".join(r[1] for r in results if not r[0] and r[1])
        print(f"  [{'x' if done else ' '}] stage {num:>2} {name}: {', '.join(items)}" + (f"  ({notes})" if notes else ""))
        if not done and nxt is None:
            nxt = (num, name)
    print(f"next: stage {nxt[0]} ({nxt[1]})" if nxt else "all stages complete")


# ---------------------------------------------------------------- map (after the CURATOR)

def map_pool(root):
    src = os.path.join(root, "merges.json")
    if not os.path.exists(src):
        sys.exit("merges.json missing: run the CURATOR prompt first")
    data = load(src)
    fam_of = {str(k): str(v) for k, v in data.get("strategy_family", {}).items()}
    axes = collections.OrderedDict((str(k), [str(x) for x in v]) for k, v in data.get("axes", {}).items())
    ideas = data.get("ideas", [])
    if not ideas:
        sys.exit("merges.json has no ideas")
    warnings, seen_keys, seen_alias = [], set(), {}
    for n, idea in enumerate(ideas):
        for field in ("key", "title", "pitch", "mechanism", "aliases", "cluster"):
            if not idea.get(field):
                sys.exit(f"merges.json ideas[{n}] lacks '{field}'")
        if idea["key"] in seen_keys:
            sys.exit(f"duplicate mechanism key in merges.json: {idea['key']}")
        seen_keys.add(idea["key"])
        for a in idea["aliases"]:
            if a in seen_alias:
                warnings.append(f"alias {a} appears under two canonical ideas")
            seen_alias[a] = idea["key"]

    def prefix(alias):
        m = re.match(r"^(.*?)-\d+$", str(alias).strip())
        return m.group(1) if m else str(alias).strip()

    def family(p):
        if p in fam_of:
            return fam_of[p]
        if p.upper().startswith("H"):
            return "human"
        warnings.append(f"prefix {p} not in strategy_family: origin '?'")
        fam_of[p] = "?"
        return "?"

    keys = sorted(i["key"] for i in ideas)
    rng(root, "map").shuffle(keys)  # random neutral IDs, not grouped by strategy or origin
    ident = {k: f"I-{n:03d}" for n, k in enumerate(keys, 1)}
    by_key = {i["key"]: i for i in ideas}
    clusters, origins, primary = {}, {}, []
    raw, credited, only = collections.Counter(), collections.Counter(), collections.Counter()
    for k in keys:
        idea, iid = by_key[k], ident[k]
        prefixes = [prefix(a) for a in idea["aliases"]]
        fams = {family(p) for p in prefixes}
        ai = fams - {"human"}
        if "human" in fams:
            origin = "human-mixed" if ai else "human"
        else:
            origin = next(iter(ai)) if len(ai) == 1 else "ai-mixed"
        clusters[iid], origins[iid] = str(idea["cluster"]), origin
        if idea.get("primary"):
            primary.append(iid)
        for p in prefixes:
            raw[p] += 1
        for p in set(prefixes):
            credited[p] += 1
        if len(set(prefixes)) == 1:
            only[prefixes[0]] += 1
    n = len(keys)

    def clean(text):
        return " ".join(str(text).replace("|", "/").split())

    rows = [f"{ident[k]} | {clean(by_key[k]['title'])} | {clean(by_key[k]['pitch'])} | "
            f"{clean(by_key[k]['mechanism'])}" for k in sorted(keys, key=lambda k: ident[k])]
    write(os.path.join(root, "screen", "ideas.md"), "\n".join(rows) + "\n")
    write(os.path.join(root, "clusters.json"), json.dumps(clusters, indent=1))
    write(os.path.join(root, "origins.json"), json.dumps(origins, indent=1))
    write(os.path.join(root, "primary.json"), json.dumps(primary, indent=1))

    out = [f"# POOL: {n} canonical ideas from {sum(raw.values())} raw ideas (IDs and counts computed by bs.py map)",
           "", "## YIELD", "",
           "| strategy | family | raw | canonical credited | unique share | only here | duplicate share | saturated |",
           "|---|---|---|---|---|---|---|---|"]
    for p in sorted(raw):
        dup = 1 - only[p] / raw[p]
        out.append(f"| {p} | {fam_of.get(p, 'human' if p.upper().startswith('H') else '?')} | {raw[p]} | "
                   f"{credited[p]} | {credited[p] / raw[p]:.0%} | {only[p]} | {dup:.0%} | "
                   f"{'SATURATED' if dup >= 0.4 else ''} |")
    out += ["", "Duplicate share = share of a strategy's raw ideas that are not 'only here'. The saturation stop "
                "applies to gap (G*) and reopen (R*) rounds."]
    out += ["", "## COVERAGE", ""]
    if axes:
        count = collections.Counter()
        for k in keys:
            cell = by_key[k].get("cell") or []
            count[tuple(str(c) for c in cell)] += 1
        grid = list(itertools.product(*axes.values()))
        empty = [c for c in grid if count[c] == 0]
        single = [c for c in grid if count[c] == 1]
        out.append(f"Axes: {' x '.join(axes)}. Cells: {len(grid)}; covered: {len(grid) - len(empty)}; "
                   f"empty: {len(empty)}; single-idea: {len(single)}.")
        out.append("Empty cells: " + ("; ".join(" / ".join(c) for c in empty) or "none"))
        out.append("Single-idea cells: " + ("; ".join(" / ".join(c) for c in single) or "none"))
        off = [ident[k] for k in keys if tuple(str(c) for c in (by_key[k].get("cell") or [])) not in set(grid)]
        if off:
            out.append("Ideas whose cell does not match the axes: " + ", ".join(sorted(off)))
    else:
        out.append("No axes in merges.json: coverage not computed.")
    sizes = collections.Counter(clusters.values())
    big_name, big = sizes.most_common(1)[0]
    homog = big / n > 0.25 or (len(sizes) < 8 and n >= 40)
    out += ["", "## HOMOGENIZED", "",
            f"{'yes' if homog else 'no'}: largest cluster '{big_name}' holds {big}/{n} = {big / n:.0%} "
            f"(limit 25%); {len(sizes)} clusters for {n} canonical ideas (at least 8 needed when ideas >= 40)."]
    out += ["", "## CLUSTERS", ""]
    for name in sorted(sizes, key=lambda c: (-sizes[c], c)):
        out.append(f"### {name} ({sizes[name]})")
        for k in sorted((k for k in keys if by_key[k]["cluster"] == name), key=lambda k: ident[k]):
            idea = by_key[k]
            marks = [m for m, on in (("BASELINE", idea.get("baseline")), ("PRIMARY", idea.get("primary"))) if on]
            sib = [ident.get(s, s) for s in idea.get("siblings", [])]
            out.append(f"- {ident[k]} {clean(idea['title'])}{' [' + ', '.join(marks) + ']' if marks else ''} - "
                       f"{clean(idea['pitch'])} Mechanism: {clean(idea['mechanism'])} Key: {k}. "
                       f"Origin: {origins[ident[k]]}. Cell: {' / '.join(str(c) for c in idea.get('cell') or []) or '-'}. "
                       f"Aliases: {', '.join(idea['aliases'])}." + (f" Siblings: {', '.join(sib)}." if sib else ""))
        out.append("")
    if warnings:
        out += ["## Warnings", ""] + [f"- {w}" for w in sorted(set(warnings))] + [""]
    notes = os.path.join(root, "03_POOL_NOTES.md")
    if os.path.exists(notes):
        out += ["---", "", read_text(notes).rstrip(), ""]
    write(os.path.join(root, "03_POOL.md"), "\n".join(out) + "\n")
    print(f"mapped {n} canonical ideas ({sum(raw.values())} raw); HOMOGENIZED: {'yes' if homog else 'no'}; "
          f"wrote 03_POOL.md, clusters.json, origins.json, primary.json, screen/ideas.md")
    for w in sorted(set(warnings)):
        print("WARNING: " + w)


# ---------------------------------------------------------------- schemas

def schemas(root):
    crit = list(load(os.path.join(root, "criteria.json")))
    item = {"type": "object", "additionalProperties": False,
            "required": ["id", "g1", "g2", "g3", "c", "risk"],
            "properties": {"id": {"type": "string"}, "g1": {"type": "boolean"},
                           "g2": {"type": "boolean"}, "g3": {"type": "boolean"},
                           "risk": {"type": "string"},
                           "c": {"type": "object", "additionalProperties": False, "required": crit,
                                 "properties": {c: {"type": "integer"} for c in crit}}}}
    screen_s = {"type": "object", "additionalProperties": False, "required": ["scores"],
                "properties": {"scores": {"type": "array", "items": item}}}
    verdict = {"type": "object", "additionalProperties": False,
               "required": ["pair_id", "winner", "confidence", "decisive_reason"],
               "properties": {"pair_id": {"type": "string"},
                              "winner": {"type": "string", "enum": ["FIRST", "SECOND", "TIE"]},
                              "confidence": {"type": "number"},
                              "decisive_reason": {"type": "string"}}}
    verdicts = {"type": "object", "additionalProperties": False, "required": ["verdicts"],
                "properties": {"verdicts": {"type": "array", "items": verdict}}}
    response = {"type": "object", "additionalProperties": False,
                "required": ["text", "mechanism", "probability"],
                "properties": {"text": {"type": "string"}, "mechanism": {"type": "string"},
                               "probability": {"type": "number"}}}
    tier = {"type": "object", "additionalProperties": False, "required": ["max_probability", "responses"],
            "properties": {"max_probability": {"type": "number"},
                           "responses": {"type": "array", "items": response}}}
    lens = {"type": "object", "additionalProperties": False,
            "required": ["draft_titles", "bolder_titles", "tiers"],
            "properties": {"draft_titles": {"type": "array", "items": {"type": "string"}},
                           "bolder_titles": {"type": "array", "items": {"type": "string"}},
                           "tiers": {"type": "array", "items": tier}}}
    for rel, obj in (("screen/screen.schema.json", screen_s),
                     ("tournament/verdicts.schema.json", verdicts),
                     ("prompts/lens.schema.json", lens)):
        write(os.path.join(root, rel), json.dumps(obj, indent=1))
    print("wrote screen/screen.schema.json, tournament/verdicts.schema.json, prompts/lens.schema.json")


# ---------------------------------------------------------------- screen

def prepare_screen(root):
    d = os.path.join(root, "screen")
    header = read_text(os.path.join(d, "header.md")).rstrip()
    ideas = [line for line in read_text(os.path.join(d, "ideas.md")).splitlines() if line.strip()]
    for fam in FAMILIES:
        rows = ideas[:]
        rng(root, "screen-" + fam).shuffle(rows)  # each judge family sees a different order
        write(os.path.join(d, fam + ".prompt.md"), header + "\n\nIDEAS\n" + "\n".join(rows) + "\n")
    print(f"wrote screen/claude.prompt.md and screen/gpt.prompt.md ({len(ideas)} ideas, different orders)")


def screen(root):
    weights = {k: float(v) for k, v in load(os.path.join(root, "criteria.json")).items()}
    clusters = opt_json(os.path.join(root, "clusters.json"))
    origins = opt_json(os.path.join(root, "origins.json"))
    judged = collections.defaultdict(list)
    files = sorted(glob.glob(os.path.join(root, "screen", "*.out.json")))
    for path in files:
        for s in load(path).get("scores", []):
            judged[str(s.get("id", "")).strip()].append(s)
    judged.pop("", None)
    if not judged:
        sys.exit("no scores found in screen/*.out.json")

    def wscore(means, w):
        return sum(w[c] * means[c] for c in w) / float(sum(w.values()))

    info, missing = {}, set()
    for i, js in judged.items():
        means = {}
        for c in weights:
            vals = [as_float(j.get("c", {}).get(c)) for j in js]
            vals = [v for v in vals if v is not None]
            if len(vals) < len(js):
                missing.add(i)
            means[c] = sum(vals) / len(vals) if vals else 0.0
        info[i] = dict(
            means=means, w=wscore(means, weights), judges=len(js),
            # K1: at least two judges and all of them failed the same gate; a single failing judge only flags
            kill=len(js) >= 2 and any(all(is_false(j.get(g, True)) for j in js) for g in GATES),
            flag=any(is_false(j.get(g, True)) for j in js for g in GATES),       # at least one judge did
            floor=min(means.values()) <= 1.5,                                    # K3 multiplicative floor
            cluster=clusters.get(i, "?"), origin=origins.get(i, "?"),
            risk=" / ".join(str(j.get("risk", "")).strip() for j in js if j.get("risk")))
    ids = sorted(info)

    def ranks(w):
        order = sorted(ids, key=lambda k: (-wscore(info[k]["means"], w), k))
        return {k: r + 1 for r, k in enumerate(order)}

    base = ranks(weights)
    lo, hi = dict(base), dict(base)
    for c in weights:  # one-at-a-time weight sensitivity: each weight -25% / +25%
        for f in (0.75, 1.25):
            w2 = dict(weights)
            w2[c] = weights[c] * f
            for k, r in ranks(w2).items():
                lo[k], hi[k] = min(lo[k], r), max(hi[k], r)

    ok = sorted([k for k in ids if not info[k]["kill"] and not info[k]["floor"]],
                key=lambda k: (-info[k]["w"], k))
    pick, seen = collections.OrderedDict(), set()
    for k in ok:  # diversity quota: best idea of each cluster, at most 10
        if info[k]["cluster"] not in seen and len(pick) < 10:
            seen.add(info[k]["cluster"])
            pick[k] = "best of cluster"
    dk, fk = find_key(weights, "distinct"), find_key(weights, "feasib")
    notes = []
    if dk and fk:  # protected tail slot: most distinctive idea that is still feasible
        tail = [k for k in ok if info[k]["means"][fk] >= 3]
        if tail:
            t = max(tail, key=lambda k: (info[k]["means"][dk], info[k]["w"]))
            pick[t] = pick[t] + " + tail slot" if t in pick else "tail slot"
    else:
        notes.append("no criteria named like 'Distinctiveness' and 'Feasibility': tail slot skipped")
    human = [k for k in ok if info[k]["origin"] in HUMAN_ORIGINS]
    if human and human[0] not in pick:  # protected human slot (only ideas with a human seed behind them)
        pick[human[0]] = "best human-origin"
    for k in opt_json(os.path.join(root, "primary.json")) or []:  # the user's idea to pressure-test: always in
        if k in info:
            why = "primary idea" + (" (gate KILL: human confirms)" if info[k]["kill"] else "") + \
                  (" (floor FAIL: human decides)" if info[k]["floor"] else "")
            pick[k] = pick[k] + " + " + why if k in pick else why
    borderline = [k for k in ok if k not in pick and lo[k] <= len(pick)]

    lines = ["| id | cluster | origin | score | rank (range, weights +/-25%) | gates | floor | shortlist | top risk |",
             "|---|---|---|---|---|---|---|---|---|"]
    for k in sorted(ids, key=lambda k: base[k]):
        d = info[k]
        gate = "KILL" if d["kill"] else ("flag" if d["flag"] else "ok")
        lines.append(f"| {k} | {d['cluster']} | {d['origin']} | {d['w']:.2f} | {base[k]} ({lo[k]}-{hi[k]}) "
                     f"| {gate} | {'FAIL' if d['floor'] else 'ok'} | {pick.get(k, '')} | {d['risk'][:80]} |")
    lines.append("")
    lines.append(f"Auto-shortlist: {len(pick)} ideas. Judge files read: {len(files)}.")
    if borderline:
        lines.append("Borderline (rank range reaches the shortlist size): " + ", ".join(borderline))
    if missing:
        lines.append(f"WARNING: criterion keys missing for {sorted(missing)}; judge JSON must use exactly "
                     f"{list(weights)}")
    one_judge = [k for k in ids if info[k]["judges"] < 2]
    if one_judge:
        lines.append(f"WARNING: only one judge scored {one_judge} (second family missing or failed)")
    lines.extend(notes)
    table = "\n".join(lines) + "\n"
    write(os.path.join(root, "screen", "table.md"), table)
    write(os.path.join(root, "screen", "shortlist.json"), json.dumps({
        "shortlist": [{"id": k, "reason": r, "score": round(info[k]["w"], 3)} for k, r in pick.items()],
        "killed_gate": [k for k in ids if info[k]["kill"]],
        "floor_fail": [k for k in ids if info[k]["floor"] and not info[k]["kill"]],
        "flagged_gate": [k for k in ids if info[k]["flag"] and not info[k]["kill"]],
        "borderline": borderline}, indent=1))
    print(table)


# ---------------------------------------------------------------- tournament

def parse_cards(path):
    cards, cur = collections.OrderedDict(), None
    for line in read_text(path).splitlines():
        if line.startswith("## "):
            cur = line[3:].strip()
            cards[cur] = []
        elif cur is not None and line.strip():
            cards[cur].append(line)
    return cards


def prepare_tournament(root, per_pair=False):
    d = os.path.join(root, "tournament")
    if glob.glob(os.path.join(d, "*.out.json")):
        sys.exit("tournament/*.out.json already exist; move them to another folder before re-preparing")
    for stale in glob.glob(os.path.join(d, "*.prompt.md")) + glob.glob(os.path.join(d, "*.map.json")):
        os.remove(stale)
    cards = parse_cards(os.path.join(d, "cards.md"))
    ids = list(cards)
    if not 2 <= len(ids) <= 26:
        sys.exit(f"need 2-26 cards (headings '## <ID>') in tournament/cards.md, found {len(ids)}")
    header = read_text(os.path.join(d, "header.md")).rstrip()
    pairs = list(itertools.combinations(ids, 2))
    pair_rule = "PAIRS (the first card named in a pair is FIRST, the second is SECOND)"
    written = 0
    if not per_pair:
        for fam in FAMILIES:
            for order in ("fwd", "rev"):
                r = rng(root, f"tournament-{fam}-{order}")  # new letters and pair order for every call
                shown = ids[:]
                r.shuffle(shown)
                label = {k: string.ascii_uppercase[i] for i, k in enumerate(shown)}
                ps = pairs[:]
                r.shuffle(ps)
                body = [header, "", "CARDS"]
                for k in shown:
                    body += ["", f"[Card {label[k]}]"] + cards[k]
                body += ["", pair_rule]
                meta = {"family": fam, "order": order, "pairs": {}}
                for i, (x, y) in enumerate(ps, 1):
                    first, second = (x, y) if order == "fwd" else (y, x)  # rev = same pairs, swapped
                    pid = f"P{i:02d}"
                    body.append(f"{pid}: Card {label[first]} vs Card {label[second]}")
                    meta["pairs"][pid] = {"first": first, "second": second}
                base = os.path.join(d, f"{fam}_{order}")
                write(base + ".prompt.md", "\n".join(body) + "\n")
                write(base + ".map.json", json.dumps(meta, indent=1))
                written += 1
    else:
        for fam in FAMILIES:
            for n, (x, y) in enumerate(pairs, 1):
                for order in ("fwd", "rev"):
                    first, second = (x, y) if order == "fwd" else (y, x)
                    body = ([header, "", "CARDS", "", "[Card A]"] + cards[first] + ["", "[Card B]"] + cards[second]
                            + ["", pair_rule, "P01: Card A vs Card B"])
                    base = os.path.join(d, f"{fam}_{order}_{n:03d}")
                    write(base + ".prompt.md", "\n".join(body) + "\n")
                    write(base + ".map.json", json.dumps(
                        {"family": fam, "order": order, "pairs": {"P01": {"first": first, "second": second}}},
                        indent=1))
                    written += 1
    mode = "per-pair" if per_pair else "batched"
    print(f"wrote {written} judge prompts ({mode}): {len(ids)} cards, {len(pairs)} pairs, "
          f"families {', '.join(FAMILIES)}, both orders")


def tournament(root):
    d = os.path.join(root, "tournament")
    origins = opt_json(os.path.join(root, "origins.json"))
    votes = collections.defaultdict(list)
    warnings = []
    for mp in sorted(glob.glob(os.path.join(d, "*.map.json"))):
        meta = load(mp)
        out = mp[: -len(".map.json")] + ".out.json"
        if not os.path.exists(out):
            warnings.append(f"missing {os.path.basename(out)}: that call is ignored")
            continue
        try:
            verdict_list = load(out).get("verdicts", [])
        except (ValueError, AttributeError) as exc:
            warnings.append(f"unreadable {os.path.basename(out)} ({exc}): that call is ignored")
            continue
        for v in verdict_list:
            p = meta["pairs"].get(str(v.get("pair_id", "")).strip())
            if p is None:
                continue
            verdict = str(v.get("winner", "")).strip().upper()
            winner = {"FIRST": p["first"], "SECOND": p["second"]}.get(verdict)
            votes[(meta["family"], tuple(sorted((p["first"], p["second"]))))].append(winner)
    if not votes:
        sys.exit("no verdicts found in tournament/*.out.json")

    pts, consistent, total = {}, collections.Counter(), collections.Counter()
    for (fam, pair), ws in votes.items():
        both = len(ws) >= 2
        total[fam] += both
        if both and ws[0] is not None and all(w == ws[0] for w in ws):
            consistent[fam] += 1  # same winner in both orders: full point
            loser = pair[1] if ws[0] == pair[0] else pair[0]
            pts[(fam, pair)] = {ws[0]: 1.0, loser: 0.0}
        else:  # order-dependent, tie, missing order: split the point (balanced position calibration)
            pts[(fam, pair)] = {pair[0]: 0.5, pair[1]: 0.5}
    fams = sorted({f for f, _ in pts})
    pairs = sorted({p for _, p in pts})
    score = collections.Counter({k: 0.0 for p in pairs for k in p})
    for s in pts.values():
        for k, v in s.items():
            score[k] += v
    n_cards = len(score)

    out = [f"## Standings (max = {len(fams)} families x {n_cards - 1} opponents = {len(fams) * (n_cards - 1)} points)"]
    for rank, (k, v) in enumerate(sorted(score.items(), key=lambda kv: (-kv[1], kv[0])), 1):
        out.append(f"{rank}. {k}  {v:.1f}  (origin: {origins.get(k, '?')})")
    out += ["", "## Contested pairs (the human decides these)"]
    contested = 0
    for pair in pairs:
        decisive = [max(pts[(f, pair)], key=pts[(f, pair)].get) for f in fams
                    if (f, pair) in pts and max(pts[(f, pair)].values()) == 1.0]
        if len(set(decisive)) > 1:
            out.append(f"- {pair[0]} vs {pair[1]}: judge families disagree")
            contested += 1
        elif not decisive:
            out.append(f"- {pair[0]} vs {pair[1]}: no order-consistent verdict")
            contested += 1
    if not contested:
        out.append("- none")
    out += ["", "## Judge position consistency (same winner in both orders)"]
    for f in fams:
        if total[f]:
            share = consistent[f] / total[f]
            flag = "  <- below 60%: discount this family's verdicts" if share < 0.6 else ""
            out.append(f"- {f}: {consistent[f]}/{total[f]} = {share:.0%}{flag}")
        else:
            out.append(f"- {f}: only one order judged; all its verdicts were split 0.5/0.5")
    out += ["", "## Self-preference audit (win share of each family's own ideas in mixed pairs, by judge)"]
    provisional = other_family_provisional(root)
    if provisional:
        out.append("- SKIPPED: Self-preference audit invalid: second judge is the same vendor (00_RUN.md other "
                   "family = none / PROVISIONAL). The files labeled 'claude' or 'gpt' for the second judge were "
                   "judged by the substitute model: read that label as 'alt'.")
    audited = provisional
    for f in (() if provisional else FAMILIES):
        shares = {g: [] for g in fams}
        for pair in pairs:
            a, b = pair
            if (origins.get(a) == f) == (origins.get(b) == f):
                continue
            own = a if origins.get(a) == f else b
            for g in fams:
                if (g, pair) in pts:
                    shares[g].append(pts[(g, pair)][own])
        present = {g: sum(v) / len(v) for g, v in shares.items() if v}
        if present:
            audited = True
            text = ", ".join(f"judge {g} {s:.0%} (n={len(shares[g])})" for g, s in present.items())
            others = [s for g, s in present.items() if g != f]
            flag = ""
            if f in present and others and present[f] - max(others) > 0.15:
                flag = "  <- own-family judge favours its own ideas by >15 points: discount it"
            out.append(f"- {f}-origin ideas: {text}{flag}")
    if not audited:
        out.append("- no mixed-origin pairs (origins.json missing or single-origin finalists)")
    if warnings:
        out += ["", "## Warnings"] + [f"- {w}" for w in warnings]
    text = "\n".join(out) + "\n"
    write(os.path.join(d, "result.md"), text)
    print(text)


# ---------------------------------------------------------------- dupcheck

def dupcheck(root, threshold=None):
    rows = []
    for line in read_text(os.path.join(root, "screen", "ideas.md")).splitlines():
        parts = [p.strip() for p in line.split("|")]
        if len(parts) >= 3 and re.match(r"^I-\d+", parts[0]):
            rows.append((parts[0], " ".join(parts[1:])))
    if len(rows) < 2:
        sys.exit("need at least 2 lines like 'I-001 | title | pitch | mechanism' in screen/ideas.md")
    method, th, score = None, None, None
    try:
        from sentence_transformers import SentenceTransformer, util  # optional dependency
        model = SentenceTransformer("all-MiniLM-L6-v2")
        emb = model.encode([t for _, t in rows], convert_to_tensor=True, normalize_embeddings=True)
        sim = util.cos_sim(emb, emb)
        method, th = "embeddings (all-MiniLM-L6-v2, cosine)", 0.8 if threshold is None else threshold

        def score(i, j):
            return float(sim[i][j])
    except Exception:  # not installed, no model download, torch problems: fall back to word overlap
        toks = [set(w for w in re.findall(r"[a-z0-9]+", t.lower()) if len(w) > 2 and w not in STOP)
                for _, t in rows]
        method, th = "word overlap (Jaccard)", 0.5 if threshold is None else threshold

        def score(i, j):
            union = toks[i] | toks[j]
            return len(toks[i] & toks[j]) / len(union) if union else 0.0
    hits = [(rows[i][0], rows[j][0], score(i, j)) for i in range(len(rows)) for j in range(i + 1, len(rows))]
    hits = sorted([h for h in hits if h[2] >= th], key=lambda h: -h[2])
    print(f"method: {method}; threshold {th}")
    for a, b, s in hits:
        print(f"{a} ~ {b}  similarity={s:.2f}  (merge only if actor, mechanism and outcome all match; "
              f"otherwise keep as siblings)")
    print(f"{len(hits)} candidate near-duplicate pairs among {len(rows)} ideas")


def main(argv):
    if len(argv) < 3:
        sys.exit(__doc__)
    cmd, root, rest = argv[1], argv[2], argv[3:]
    if cmd == "init":
        init(root)
    elif cmd == "status":
        status(root)
    elif cmd == "schemas":
        schemas(root)
    elif cmd == "map":
        map_pool(root)
    elif cmd == "prepare-screen":
        prepare_screen(root)
    elif cmd == "screen":
        screen(root)
    elif cmd == "prepare-tournament":
        prepare_tournament(root, per_pair="--per-pair" in rest)
    elif cmd == "tournament":
        tournament(root)
    elif cmd == "dupcheck":
        th = None
        if "--threshold" in rest:
            th = float(rest[rest.index("--threshold") + 1])
        dupcheck(root, th)
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main(sys.argv)
