#!/usr/bin/env python3
"""bs.py - deterministic bookkeeping for the ultimate-brainstorm pipeline (kit v2).

Python 3.9+ standard library only. RUN is a run folder such as brainstorm/2026-09-23-habit-coach.
The judge families come from run.json seats (schema 2). status, prepare-screen, screen, prepare-tournament and
tournament need run.json; on a v1 run folder they exit 4 and name `ub continue`, which migrates the folder.

  --version                       print the kit version
  init RUN                        create the run's sub-folders, brainstorm/LEDGER.md and an empty
                                  00_HUMAN_SEEDS.md template (each only if missing)
  status RUN                      list stage outputs present/missing and name the next stage
  schemas RUN                     write screen/screen.schema.json, tournament/verdicts.schema.json and
                                  prompts/lens.schema.json (criteria names come from RUN/criteria.json)
  map RUN                         merges.json (from the CURATOR) -> random I-### IDs, clusters.json,
                                  origins.json, primary.json, ideas.json, screen/ideas.md, 03_POOL.md and
                                  coverage.json (pool/_families.json is the authoritative prefix -> family map)
  prepare-screen RUN              screen/ideas.md + screen/header.md -> screen/<family>.prompt.md per judge
  screen RUN                      screen/*.out.json -> screen/table.md + screen/shortlist.json
  prepare-tournament RUN [--per-pair]
                                  tournament/cards.md + tournament/header.md -> judge prompts + .map.json files
  tournament RUN                  tournament/*.out.json -> tournament/result.md + tournament/result.json
  quick-pick RUN [--scores auto|blind|curator]
                                  quick/curated.json (+ the blind quick screen's screen/*.out.json) ->
                                  quick/finalists.json, quick/screen.md, tournament/cards.md, origins.json
  arch-matrix RUN                 10_ARCHITECTURE drivers + candidates/map.json + review/judge_*.out.json
                                  -> 10_ARCHITECTURE/tradeoff-matrix.md + matrix.json
  lint-arch RUN [--lite]          -> 10_ARCHITECTURE/lint.md + lint.json (exit 1 on FAIL)
  lint-proposal RUN [--lite]      -> 11_PROPOSAL/lint.md + lint.json (exit 1 on FAIL)
  lint-frame RUN                  -> frame/lint.json (warnings only)
  split RUN --in FILE --root REL --allow GLOB [--allow GLOB ...] [--status-out REL]
                                  FILE-protocol output -> files under RUN/REL (exit 5 when invalid)
  sources RUN                     -> sources.json + sources.md (stable S-### ids)
  assumptions RUN                 -> 11_PROPOSAL/assumptions.md + 11_PROPOSAL/open-questions.md

Exit codes: 0 ok, 1 lint fail, 2 usage, 4 missing input, 5 invalid input. Errors go to stderr.
"""
import argparse
import collections
import datetime
import itertools
import json
import math
import os
import re
import string
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from ublib import filesproto, lints, textio, validate  # noqa: E402
from ublib.engine import base_family, seats  # noqa: E402
from ublib.engine.privacy import fence_data  # noqa: E402
from ublib.families import vendor_of  # noqa: E402

VERSION = "2.1.1"
NOBODY = ("human", "human-mixed", "ai-mixed", "?", "")  # origins that count as nobody's own
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
]
QUICK_STAGES = [
    (1, "Quick: seeds and criteria", ["@seeds", "criteria.json"]),
    (2, "Quick: generate", ["pool/*"]),
    (3, "Quick: cards", ["tournament/cards.md"]),
    (4, "Quick: other-family check", ["tournament/result.md"]),
    (5, "Quick: decision", ["QUICK_DECISION.md"]),
]
# proposal mode skips diverge/map/screen; every mode ends with stages 12-14.
PROPOSAL_STAGES = [
    (1, "Sealed human seeds", ["@seeds"]),
    (2, "Frame", ["01_FRAME.md", "criteria.json"]),
    (3, "Ground", ["02_CONTEXT.md"]),
    (7, "Reality checks", ["checks/I-001.md"]),
    (9, "Tournament", ["tournament/result.md", "06_TOURNAMENT.md"]),
    (10, "Red-team and decide", ["07_REDTEAM.md", "08_DECISION.md"]),
    (11, "Probe", ["09_PROBE.md", "@probe-result"]),
]
V2_TAIL_STAGES = [
    (12, "Architecture", ["10_ARCHITECTURE/README.md"]),
    (13, "Proposal", ["11_PROPOSAL/PROPOSAL.md"]),
    (14, "Handoff", ["12_HANDOFF.md"]),
]
POSITION_FLAG = 0.6  # a judge family below this position consistency is left out of the ranking (5.7)
GAP_FLAG = 0.5       # an own-origin (screen) or own-candidate (arch-matrix) gap above this is flagged (5.7)
GAP_MIN = 3          # ideas needed on each side of an own-origin gap's difference in differences
GAP_Z = 1.5          # an own-origin gap is taken off a judge's own-vendor scores only above this many standard errors
BT_PRIOR = 0.5       # Bradley-Terry: pseudo-win per card and pair (a virtual tie; keeps the fit defined)
BOOTSTRAP = 200      # seeded bootstrap resamples of the judges' pair verdicts for the 90% intervals
COVERED_MIN = 0.8    # a gap round runs when fewer than 80% of the axis cells hold an idea (5.3)
# arch-matrix fixed criteria (5.7): id, display name, weight
FIXED_CRITERIA = (("time_to_mvp", "Time to MVP", 10.0), ("team_fit", "Team fit", 5.0), ("run_cost", "Run cost", 5.0),
                  ("reversibility", "Reversibility", 5.0), ("operational_simplicity", "Operational simplicity", 5.0))
URL_RE = re.compile(r"https?://[^\s)>\]\"']+")


class BsError(Exception):
    """A user-facing error with an exit code (2 usage, 4 missing input, 5 invalid input)."""

    def __init__(self, message, code=5):
        Exception.__init__(self, message)
        self.message = message
        self.code = code


def die(message, code=5):
    raise BsError(message, code)


read_text = textio.read_text   # UTF-8 with or without BOM, or UTF-16; LF line endings
write = textio.write_text_atomic  # UTF-8, LF, temp file + os.replace


def load(path):
    """Strict JSON: files the engine or bs.py wrote (run.json, origins.json, *.map.json, ...)."""
    return json.loads(read_text(path))


def load_model(path):
    """Tolerant JSON for model output (judge outputs, curated ideas, drivers): fences, preamble, BOM, UTF-16."""
    return textio.read_json(path)


def opt_json(path):
    return load(path) if os.path.exists(path) else {}


def need_json(path, what=None, model=False):
    """Load a required JSON input (tolerantly when it is model output): exit 4 when missing, 5 when unreadable."""
    if not os.path.exists(path):
        die("%s missing: %s" % (what or os.path.basename(path), path), 4)
    try:
        return load_model(path) if model else load(path)
    except ValueError as exc:
        die("%s is not valid JSON: %s" % (path, exc), 5)


def run_name(root):
    return os.path.basename(os.path.normpath(os.path.abspath(root)))


def rng(root, tag):
    """Reproducible randomness per run and per call (same run -> same shuffles); the seeding of seats.rng."""
    return seats.rng(run_name(root), tag)


def is_false(value):
    return value is False or str(value).strip().lower() == "false"


def as_float(value):
    try:
        return float(value)
    except (TypeError, ValueError, OverflowError):  # OverflowError: a JSON integer too large for a float
        return None


def find_key(keys, needle):
    for key in keys:
        if needle in key.lower():
            return key
    return None


def weighted(values, weights):
    """Weighted mean over the criteria that have a value (None when none has one)."""
    used = [c for c in weights if values.get(c) is not None]
    if not used:
        return None
    return sum(weights[c] * values[c] for c in used) / float(sum(weights[c] for c in used))


def rank_ranges(ids, score, weights):
    """(base, lo, hi) ranks of `ids` under `weights`, and the range when each weight moves by -25% and +25%, one
    at a time (5.7). score(id, weights) -> number; ties go to the lower id."""
    def ranks(w):
        order = sorted(ids, key=lambda k: (-score(k, w), k))
        return {k: r + 1 for r, k in enumerate(order)}

    base = ranks(weights)
    lo, hi = dict(base), dict(base)
    for c in weights:
        for f in (0.75, 1.25):
            w2 = collections.OrderedDict(weights)
            w2[c] = weights[c] * f
            for k, r in ranks(w2).items():
                lo[k], hi[k] = min(lo[k], r), max(hi[k], r)
    return base, lo, hi


def protected_slots(ranked, values, score, weights, origin):
    """(tail, human, note) for ids ranked best first (screen and quick-pick). Tail slot: the most distinctive idea
    whose Feasibility is at least 3 (ties: the higher score, then the rank). Human slot: the best idea with a human
    origin. values[id] = {criterion: value}; origin(id) -> origin label."""
    dk, fk = find_key(weights, "distinct"), find_key(weights, "feasib")
    tail, note = None, None
    if dk and fk:
        cands = [k for k in ranked if values[k].get(fk) is not None and values[k][fk] >= 3
                 and values[k].get(dk) is not None]
        if cands:
            tail = max(cands, key=lambda k: (values[k][dk], score[k]))
    else:
        note = "no criteria named like 'Distinctiveness' and 'Feasibility': tail slot skipped"
    human = next((k for k in ranked if origin(k) in HUMAN_ORIGINS), None)
    return tail, human, note


# ---------------------------------------------------------------- run.json and families

def run_json(root):
    """The run.json dict when it exists with schema 2, else None."""
    path = os.path.join(root, "run.json")
    if not os.path.exists(path):
        return None
    try:
        data = load(path)
    except ValueError as exc:
        die(f"run.json is not valid JSON: {exc}", 5)
    if isinstance(data, dict) and data.get("schema") == 2:
        return data
    return None


def need_run_json(root, cmd):
    """run.json (schema 2), or exit 4 naming `ub continue`, which migrates a v1 run folder to run.json (6.10)."""
    rj = run_json(root)
    if rj is None:
        ub = os.path.join(_HERE, "ub.py").replace("\\", "/")
        die(f"run.json (schema 2) missing in {root}: bs.py {cmd} needs a v2 run folder. For a v1 run folder, run "
            f"`python \"{ub}\" continue \"{root}\"` once (it migrates the folder to run.json and resumes it), "
            "then retry.", 4)
    return rj


def vendor(label):
    """The vendor of a family label (families.vendor_of: claude = anthropic, gpt = openai, kimi = moonshot,
    glm = zhipu; X-alt has the vendor of X; any other label is its own vendor). Origins human, human-mixed,
    ai-mixed and unknown belong to nobody (None)."""
    label = str(label or "").strip()
    if label in NOBODY:
        return None
    return vendor_of(label)


def judge_families(root, seat_key, cmd):
    """Judge family labels from run.json seats."""
    fams = (need_run_json(root, cmd).get("seats") or {}).get(seat_key)
    out = []
    for f in fams if isinstance(fams, list) else []:
        f = str(f).strip()
        if f and f not in out:
            out.append(f)
    if not out:
        die(f"run.json seats.{seat_key} is empty", 5)
    return out


def _stage_match(stage, which):
    s = str(stage or "").strip().lower()
    if which == "screen":
        return "screen" in s or s.startswith("6.")
    return "tournament" in s or s.startswith("9.") or s.startswith("q.5") or s == "quick"


def answered_by(out_path, seat):
    """(label, confirmed): the family that actually answered a judge call. A fallback copy writes the failed seat's
    output file, so the call's meta file (family, status ok) names the model; without one the seat label stands
    (confirmed False)."""
    try:
        meta = load(out_path + ".meta.json")
    except (OSError, ValueError):
        return seat, False
    fam = str(meta.get("family") or "").strip() if isinstance(meta, dict) and meta.get("status") == "ok" else ""
    return (fam, True) if fam else (seat, False)


def judge_info(root, labels, which, answered=()):
    """{label: {"provisional": bool, "vendor": str|None, "actual": str}} for judge labels (5.7).

    Labels are the families that answered (`answered`: labels read from the calls' meta files). PROVISIONAL: an
    -alt label; a family that answered only for another seat (a run.json.provisional actual that holds no judge
    seat of this stage); or a seat label with a provisional entry whose calls carry no meta file (its vendor is
    then the recorded actual's). The host's own seat stays non-provisional when it also answered for a failed seat.
    """
    rj = run_json(root) or {}
    seated = set(str(f).strip() for f in ((rj.get("seats") or {}).get(
        "screen_judges" if which == "screen" else "tournament_judges") or []))
    subs = {}
    for p in rj.get("provisional") or []:
        if isinstance(p, dict) and _stage_match(p.get("stage"), which):
            seat, actual = str(p.get("seat", "")).strip(), str(p.get("actual", "")).strip()
            if seat:
                subs[seat] = actual or seat + "-alt"
    stand_ins = set(subs.values())
    info = {}
    for lab in labels:
        unverified = lab in subs and lab not in answered
        actual = subs[lab] if unverified else lab
        prov = lab.endswith("-alt") or unverified or (lab in stand_ins and lab not in seated)
        info[lab] = {"provisional": prov, "vendor": vendor(actual), "actual": actual}
    return info


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


def mode_of(rj):
    mode = str(rj.get("mode", "")).lower()
    return mode if mode in ("quick", "standard", "deep", "proposal") else "standard"


def section(text, heading):
    """Body of a '## <heading>...' section, read as the engine reads it (registry.section, textio.section)."""
    return textio.section(text, heading)


def seeds_done(root):
    files = textio.glob_in(root, "00_HUMAN_SEEDS*.md")
    for path in files:
        text = read_text(path)
        if re.search(r"^[^\w\n]*SKIPPED\b", text, re.M) or section(text, "Ideas") or section(text, "Primary idea"):
            return True, ""
    return False, "Ideas section empty (write ideas or 'SKIPPED: <reason>')" if files else "file missing"


def strategies(root):
    """Strategy keys from the '- strategy -> family map: S1=claude S2=claude S3=gpt ...' line of 00_RUN.md."""
    match = re.search(r"strategy\s*->\s*family map\s*:\s*(.*)$", run_text(root), re.M | re.I)
    keys = re.findall(r"(?<![\w-])([A-Z]+\d*)(?:-[A-Za-z-]+)?\s*[=:]\s*[A-Za-z]", match.group(1)) if match else []
    return keys or list(DEFAULT_STRATEGIES)


def check_item(root, item):
    """Return (done, note) for one stage requirement."""
    if item == "@seeds":
        return seeds_done(root)
    if item == "@pool":
        miss = [s for s in strategies(root) if not textio.glob_in(root, "pool", s + "[_.]*")]
        return not miss, ("missing pool files for " + ", ".join(miss)) if miss else ""
    if item == "@checks":
        path = os.path.join(root, "screen", "shortlist.json")
        if not os.path.exists(path):
            return False, "screen/shortlist.json missing"
        want = [s["id"] for s in load(path).get("shortlist", [])]
        short = os.path.join(root, "04_SHORTLIST.md")
        if os.path.exists(short):
            # the engine's reading of the Rescued: line (lazy: only this check needs it): IDs only, never an ID in
            # the reason an older kit wrote in parentheses there
            from ublib.engine.registry import rescued_ids
            want += rescued_ids(read_text(short))
        miss = sorted({i for i in want if not os.path.exists(os.path.join(root, "checks", i + ".md"))})
        return not miss, ("no check for " + ", ".join(miss)) if miss else ""
    if item == "@evolved-checks":
        path = os.path.join(root, "05_EVOLVED.md")
        # the E ideas as the idea-blocks contract and the engine parse them (fenced examples and incomplete blocks are
        # not ideas)
        eids = [b["id"] for b in validate.parse_idea_blocks(read_text(path), "E")[0]] if os.path.exists(path) else []
        miss = sorted({i for i in eids if not os.path.exists(os.path.join(root, "checks", i + ".md"))})
        return not miss, ("no check for " + ", ".join(miss)) if miss else ""
    if item == "@probe-result":
        path = os.path.join(root, "09_PROBE.md")
        ok = os.path.exists(path) and re.search(r"^[^\w\n]*RESULT[ \t]*:", read_text(path), re.M)
        if ok and re.search(r"^[^\w\n]*RESULT[ \t]*:[ \t]*PENDING\b", read_text(path), re.M | re.I):
            return True, "designed; RESULT: PENDING"
        return bool(ok), "" if ok else "no 'RESULT:' line yet (probe designed but not reported)"
    return bool(textio.glob_in(root, *item.split("/"))), ""


def status(root):
    mode = mode_of(need_run_json(root, "status"))
    if mode == "quick":
        stages = QUICK_STAGES + V2_TAIL_STAGES
    elif mode == "proposal":
        stages = PROPOSAL_STAGES + V2_TAIL_STAGES
    else:
        stages = FULL_STAGES + V2_TAIL_STAGES
    nxt = None
    print(f"run: {root}   mode: {mode}")
    for num, name, items in stages:
        results = [check_item(root, i) for i in items]
        done = all(r[0] for r in results)
        notes = "; ".join(r[1] for r in results if r[1])
        print(f"  [{'x' if done else ' '}] stage {num:>2} {name}: {', '.join(items)}" + (f"  ({notes})" if notes else ""))
        if not done and nxt is None:
            nxt = (num, name)
    print(f"next: stage {nxt[0]} ({nxt[1]})" if nxt else "all stages complete")


# ---------------------------------------------------------------- map (after the CURATOR)

def alias_prefix(alias):
    """'S3-04' -> 'S3', 'HP-1' -> 'HP'; an alias without a '-<digits>' tail is its own prefix."""
    alias = str(alias).strip()
    head, sep, tail = alias.rpartition("-")
    return head if sep and tail.isdecimal() else alias


lineage_origin = seats.lineage_origin  # human, human-mixed, the one AI vendor's label or ai-mixed (by vendor)


def map_pool(root):
    src = os.path.join(root, "merges.json")
    if not os.path.exists(src):
        die("merges.json missing: run the CURATOR prompt first", 4)
    data = load(src)
    fam_of = {str(k): str(v) for k, v in data.get("strategy_family", {}).items()}
    fam_file = os.path.join(root, "pool", "_families.json")
    authoritative = os.path.exists(fam_file)
    if authoritative:  # v2: B3 writes the authoritative prefix -> family map
        fam_of = {str(k): str(v) for k, v in (load(fam_file) or {}).items()}
    axes = collections.OrderedDict((str(k), [str(x) for x in v]) for k, v in data.get("axes", {}).items())
    ideas = data.get("ideas", [])
    if not ideas:
        die("merges.json has no ideas", 5)
    warnings, seen_keys, seen_alias = [], set(), {}
    for n, idea in enumerate(ideas):
        for field in ("key", "title", "pitch", "mechanism", "aliases", "cluster"):
            if not idea.get(field):
                die(f"merges.json ideas[{n}] lacks '{field}'", 5)
        if idea["key"] in seen_keys:
            die(f"duplicate mechanism key in merges.json: {idea['key']}", 5)
        seen_keys.add(idea["key"])
        for a in idea["aliases"]:
            if a in seen_alias:
                warnings.append(f"alias {a} appears under two canonical ideas")
            seen_alias[a] = idea["key"]

    def family(p):
        if authoritative and p.upper().startswith("H"):  # human prefixes (H, HP, H2, H<name>) are always human
            return "human"
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
    clusters, origins, primary, lineage = {}, {}, [], {}
    raw, credited, only = collections.Counter(), collections.Counter(), collections.Counter()
    for k in keys:
        idea, iid = by_key[k], ident[k]
        prefixes = [alias_prefix(a) for a in idea["aliases"]]
        origin = lineage_origin({family(p) for p in prefixes})
        clusters[iid], origins[iid] = str(idea["cluster"]), origin
        lineage[iid] = {"key": k, "strategies": sorted(set(prefixes)),
                        "families": sorted(set(family(p) for p in prefixes)), "origin": origin,
                        "cluster": str(idea["cluster"])}
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
    # which strategies and families produced each canonical idea (tools/eval.py attributes yield with it)
    textio.write_json_atomic(os.path.join(root, "ideas.json"), lineage)

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
    empty, single, covered = [], [], 1.0
    no_values = [k for k, v in axes.items() if not v]
    if no_values:
        # merges.schema.json allows an empty value list; the grid of such axes has no cell (2.0.3 printed Cells: 0)
        warnings.append("axis %s has no values: no axis cells, coverage not computed" % ", ".join(no_values))
        out.append(f"No axis cells (axis {', '.join(no_values)} has no values): coverage not computed.")
    elif axes:
        count = collections.Counter()
        for k in keys:
            cell = by_key[k].get("cell") or []
            count[tuple(str(c) for c in cell)] += 1
        grid = list(itertools.product(*axes.values()))
        empty = [c for c in grid if count[c] == 0]
        single = [c for c in grid if count[c] == 1]
        covered = (len(grid) - len(empty)) / float(len(grid))
        out.append(f"Axes: {' x '.join(axes)}. Cells: {len(grid)}; covered: {len(grid) - len(empty)} "
                   f"({covered:.0%}; a gap round runs below {COVERED_MIN:.0%}); empty: {len(empty)}; "
                   f"single-idea: {len(single)}.")
        out.append("Empty cells: " + ("; ".join(" / ".join(c) for c in empty) or "none"))
        out.append("Single-idea cells: " + ("; ".join(" / ".join(c) for c in single) or "none"))
        off = [ident[k] for k in keys if tuple(str(c) for c in (by_key[k].get("cell") or [])) not in set(grid)]
        if off:
            out.append("Ideas whose cell does not match the axes: " + ", ".join(sorted(off)))
    else:
        out.append("No axes in merges.json: coverage not computed.")
    sizes = collections.Counter(clusters.values())
    big_name, big = sizes.most_common(1)[0]
    # the largest cluster's share only: the cluster count is the curator's labeling choice (6-15 by its prompt)
    homog = big / n > 0.25
    out += ["", "## HOMOGENIZED", "",
            f"{'yes' if homog else 'no'}: largest cluster '{big_name}' holds {big}/{n} = {big / n:.0%} "
            f"(limit 25%); {len(sizes)} clusters for {n} canonical ideas."]
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
    # coverage.json for the engine's gap-round predicate (4.10): a gap round is needed when the pool is homogenized
    # or fewer than COVERED_MIN of the axis cells hold an idea (a few empty cells are normal in a 27-125 cell grid)
    textio.write_json_atomic(os.path.join(root, "coverage.json"), {
        "axes": {k: list(v) for k, v in axes.items()},
        "empty": [list(c) for c in empty],
        "single": [list(c) for c in single],
        "covered_share": round(covered, 3),
        "homogenized": bool(homog),
        "gap_needed": bool(homog or covered < COVERED_MIN),
        "largest_cluster": {"name": str(big_name), "share": round(big / n, 2)},
        "clusters": len(sizes),
        "ideas": n})
    print(f"mapped {n} canonical ideas ({sum(raw.values())} raw); HOMOGENIZED: {'yes' if homog else 'no'}; "
          f"wrote 03_POOL.md, clusters.json, origins.json, primary.json, ideas.json, screen/ideas.md")
    for w in sorted(set(warnings)):
        print("WARNING: " + w)


# ---------------------------------------------------------------- schemas

def schemas(root):
    crit = list(need_json(os.path.join(root, "criteria.json"), model=True))
    item = {"type": "object", "additionalProperties": False,
            "required": ["id", "g1", "g2", "g3", "c", "risk"],
            "properties": {"id": {"type": "string"}, "g1": {"type": "boolean"},
                           "g2": {"type": "boolean"}, "g3": {"type": "boolean"},
                           "risk": {"type": "string"},
                           "c": {"type": "object", "additionalProperties": False, "required": crit,
                                 "properties": {c: {"type": "integer", "minimum": 1, "maximum": 5}
                                                for c in crit}}}}
    screen_s = {"type": "object", "additionalProperties": False, "required": ["scores"],
                "properties": {"scores": {"type": "array", "items": item}}}
    # required == properties (strict structured outputs); nothing reads a judge's confidence or reason
    verdict = {"type": "object", "additionalProperties": False,
               "required": ["pair_id", "winner"],
               "properties": {"pair_id": {"type": "string"},
                              "winner": {"type": "string", "enum": ["FIRST", "SECOND", "TIE"]}}}
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
    fams = judge_families(root, "screen_judges", "prepare-screen")
    d = os.path.join(root, "screen")
    header = read_text(os.path.join(d, "header.md")).rstrip()
    ideas = [line for line in read_text(os.path.join(d, "ideas.md")).splitlines() if line.strip()]
    for fam in fams:
        rows = ideas[:]
        rng(root, "screen-" + fam).shuffle(rows)  # each judge family sees a different order
        # the idea lines are model-written: quoted as data that cannot forge its own end (privacy.fence_data)
        write(os.path.join(d, fam + ".prompt.md"),
              header + "\n\nIDEAS\n" + fence_data("IDEAS", "\n".join(rows)) + "\n")
    print(f"wrote {', '.join('screen/' + f + '.prompt.md' for f in fams)} ({len(ideas)} ideas, "
          f"{len(fams)} judge families, different orders)")


def _avg_ranks(values):
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        for k in range(i, j + 1):
            ranks[order[k]] = (i + j) / 2.0 + 1
        i = j + 1
    return ranks


def spearman(xs, ys):
    """Spearman rank correlation (average ranks for ties). None when n < 3 or a side has no variance."""
    n = len(xs)
    if n < 3 or n != len(ys):
        return None
    rx, ry = _avg_ranks(xs), _avg_ranks(ys)
    mx, my = sum(rx) / n, sum(ry) / n
    sxy = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    sxx = sum((a - mx) ** 2 for a in rx)
    syy = sum((b - my) ** 2 for b in ry)
    if sxx <= 0 or syy <= 0:
        return None
    return sxy / (sxx * syy) ** 0.5


def screen_records(root, weights, known):
    """Judge records from screen/*.out.json: ({label: {id: {"c": {criterion: 1-5}, "fail": {gate: bool},
    "risk": str}}}, labels confirmed by a meta file, warnings, files read).

    A label is the family that answered (answered_by); a fallback copy that ran on a family which also holds a seat
    is merged into that family's record (criteria averaged, a gate failed only when every merged record failed it),
    so one model never counts as two judges. Each file counts one record per id: ids are compared as the contract's
    cover compares them (validate.canonical_id: NFKC, format characters such as zero-width spaces removed), a repeated
    id keeps its first record, an id missing from screen/ideas.md is dropped and a score outside 1-5 is ignored, each
    with a warning. (The contract already refuses all of these; a file written some other way is still safe here.)"""
    files = sorted(textio.glob_in(root, "screen", "*.out.json"))
    recs, answered, warnings = collections.OrderedDict(), set(), []
    for path in files:
        seat = os.path.basename(path)[: -len(".out.json")]
        label, confirmed = answered_by(path, seat)
        if confirmed:
            answered.add(label)
        if label != seat:
            warnings.append(f"the {seat} seat was answered by {label} (fallback): its scores count as {label}'s")
        try:
            data = load_model(path)
        except ValueError as exc:
            warnings.append(f"unreadable {os.path.basename(path)} ({exc}): that judge is ignored")
            continue
        per, seen = recs.setdefault(label, collections.OrderedDict()), set()
        for s in (data.get("scores") if isinstance(data, dict) else None) or []:
            i = validate.canonical_id(s.get("id", "")) if isinstance(s, dict) else ""
            if not i:
                continue
            if known and i not in known:
                warnings.append(f"{seat}: unknown id {i if textio.is_ascii(i) else ascii(i)} ignored (not in "
                                f"screen/ideas.md)")
                continue
            if i in seen:
                warnings.append(f"{seat}: {i} scored twice; the first record counts")
                continue
            seen.add(i)
            crit = s.get("c") if isinstance(s.get("c"), dict) else {}
            c = {}
            for k in weights:
                v = as_float(crit.get(k))
                if v is not None and not 1 <= v <= 5:
                    warnings.append(f"{seat}, {i}, {k}: score {v:g} outside 1-5 ignored")
                elif v is not None:
                    c[k] = v
            per.setdefault(i, []).append({"c": c, "fail": {g: is_false(s.get(g, True)) for g in GATES},
                                          "risk": str(s.get("risk", "")).strip()})
    judges = collections.OrderedDict()
    for label, per in recs.items():
        judges[label] = {}
        for i, rs in per.items():
            c = {}
            for k in weights:
                vals = [r["c"][k] for r in rs if k in r["c"]]
                if vals:
                    c[k] = sum(vals) / len(vals)
            judges[label][i] = {"c": c, "fail": {g: all(r["fail"][g] for r in rs) for g in GATES},
                                "risk": next((r["risk"] for r in rs if r["risk"]), "")}
    return judges, answered, list(collections.OrderedDict.fromkeys(warnings)), len(files)


def _weighted_scores(judges, weights):
    """{judge: {id: weighted raw score}} for the ideas each judge scored on at least one criterion."""
    ws = {j: {i: weighted(r["c"], weights) for i, r in judges[j].items()} for j in judges}
    return {j: {i: v for i, v in d.items() if v is not None} for j, d in ws.items()}


def own_origin_cut(gap, se):
    """How much a judge's scores of its own vendor's ideas are lowered for an own-origin gap with standard error se:
    the whole gap when it is above GAP_Z standard errors, else nothing (a gap that noise explains is not taken off)."""
    return gap if gap > 0 and gap > GAP_Z * se else 0.0


def own_origin_gaps(judges, info, origins, weights):
    """Self-preference of the screen judges as a difference in differences (5.7): leniency cancels, so a judge that is
    only lenient or harsh is never flagged.

    For judge j and another non-provisional judge g of another vendor: d = mean over the ideas of j's vendor of (j's
    weighted score - g's), minus the same mean over the ideas that belong to neither vendor (only ideas both scored;
    at least GAP_MIN on each side). Such an idea is outside both judges' self-interest, so the second mean is their
    leniency difference and d is what j adds to its own vendor's ideas. j's gap is the mean d over its comparators; it
    is flagged above GAP_FLAG. Its standard error se is that of one comparison, sqrt(var(own)/n_own + var(base)/n_base)
    of the per-idea differences (averaged in square over the comparators), and `cut` (own_origin_cut) is what the
    screen takes off: the gap when it is above GAP_Z se. Provisional judges are neither audited nor comparators.
    Two judges whose pair has fewer than GAP_MIN ideas from neither vendor (typical: two families, no human seeds)
    cannot be told apart, unless each of them has a gap measured against a third judge: what each adds to its own
    vendor's ideas is then indistinguishable from the other's leniency. Their pair is reported as the sum of both
    judges' self-preference (mean of (a - b) over a's own ideas minus over b's own ideas) and flags neither judge.
    Returns (gaps {judge: {"gap", "se", "cut", "n", "base", "vs", "flag"}}, notes {judge: why no gap}, pairs [{"a",
    "b", "gap", "n_a", "n_b", "warn"}])."""
    ws = _weighted_scores(judges, weights)
    audited = sorted(j for j in judges if not info[j]["provisional"] and info[j]["vendor"] is not None)

    def mean(xs):
        return sum(xs) / float(len(xs))

    def sq_se(xs):
        m = mean(xs)
        return sum((x - m) ** 2 for x in xs) / (len(xs) - 1.0) / len(xs)

    def owned_by(i, v):
        return vendor(origins.get(i)) == v

    gaps, notes, pairs = collections.OrderedDict(), {}, []
    for j in audited:
        vj = info[j]["vendor"]
        own_all = [i for i in ws[j] if owned_by(i, vj)]
        ds, ses, n_own, n_base, vs = [], [], 0, 0, []
        for g in audited:
            vg = info[g]["vendor"]
            if g == j or vg == vj:
                continue
            common = [i for i in sorted(ws[j]) if i in ws[g]]
            own = [ws[j][i] - ws[g][i] for i in common if owned_by(i, vj)]
            base = [ws[j][i] - ws[g][i] for i in common if not owned_by(i, vj) and not owned_by(i, vg)]
            if len(own) < GAP_MIN or len(base) < GAP_MIN:
                continue
            ds.append(mean(own) - mean(base))
            ses.append(sq_se(own) + sq_se(base))
            n_own, n_base = max(n_own, len(own)), max(n_base, len(base))
            vs.append(g)
        if ds:
            # the comparisons share j's own scores, so the gap's standard error is taken as one comparison's
            gap, se = mean(ds), mean(ses) ** 0.5
            gaps[j] = {"gap": gap, "se": se, "cut": own_origin_cut(gap, se), "n": n_own, "base": n_base, "vs": vs,
                       "flag": gap > GAP_FLAG}
        elif len(own_all) < GAP_MIN:
            notes[j] = "%d own-vendor idea(s): not computed (needs %d)" % (len(own_all), GAP_MIN)
        else:
            notes[j] = ("not computed: no other judge shares %d or more scored ideas from neither vendor with it"
                        % GAP_MIN)
    for a, b in itertools.combinations(audited, 2):
        va, vb = info[a]["vendor"], info[b]["vendor"]
        # a pair is unattributable only while one of its judges has no gap: two gaps measured against a third judge
        # (the quick screen's third family, a small third vendor) already tell who adds how much
        if va == vb or (a in gaps and b in gaps):
            continue
        common = [i for i in sorted(ws[a]) if i in ws[b]]
        own_a = [i for i in common if owned_by(i, va)]
        own_b = [i for i in common if owned_by(i, vb)]
        if len(own_a) < GAP_MIN or len(own_b) < GAP_MIN:
            continue
        both = mean([ws[a][i] - ws[b][i] for i in own_a]) - mean([ws[a][i] - ws[b][i] for i in own_b])
        pairs.append({"a": a, "b": b, "gap": both, "n_a": len(own_a), "n_b": len(own_b), "warn": both > GAP_FLAG})
    return gaps, notes, pairs


def screen_sections(weights, judges, info, gaps):
    """## Judge agreement and ## Own-origin gap (5.7): agreement on each judge's raw weighted scores, the gaps from
    own_origin_gaps. Returns (lines, summary dict for shortlist.json)."""
    labels = sorted(judges)
    ws = _weighted_scores(judges, weights)
    gap, notes, pair_gaps = gaps

    def tag(j):
        return j + (" (PROVISIONAL)" if info[j]["provisional"] else "")

    lines = ["", "## Judge agreement", "",
             "Spearman rank correlation of each pair of judges' weighted scores over the ideas both scored. "
             "WARN when a judge's best correlation is below 0.2."]
    pairs, best, warn = [], {}, []
    if len(labels) < 2:
        lines.append("- only one judge: agreement not computed")
    else:
        for a, b in itertools.combinations(labels, 2):
            common = sorted(set(ws[a]) & set(ws[b]))
            rho = spearman([ws[a][i] for i in common], [ws[b][i] for i in common])
            pairs.append({"a": a, "b": b, "rho": None if rho is None else round(rho, 3), "n": len(common)})
            lines.append(f"- {tag(a)} vs {tag(b)}: " + ("n/a" if rho is None else f"{rho:.2f}") + f" (n={len(common)})")
            for j in (a, b):
                if rho is not None and (j not in best or rho > best[j]):
                    best[j] = rho
        for j in labels:
            if j in best and best[j] < 0.2:
                warn.append(j)
                lines.append(f"- WARN: {tag(j)}: best correlation {best[j]:.2f} is below 0.2 (its ranking barely "
                             f"agrees with any other judge)")
            elif j not in best:
                lines.append(f"- {tag(j)}: no correlation computable (fewer than 3 common ideas or constant scores)")
    lines += ["", "## Own-origin gap", "",
              "Gap = how much more a judge scores ideas from its own vendor than another judge does, beyond how the "
              "two differ on ideas from neither vendor (a difference in differences, so a lenient or harsh judge shows "
              f"no gap; needs {GAP_MIN} ideas on each side). Every judge's scores count in the shortlist; a judge's "
              f"scores of its own vendor's ideas are lowered by its gap when the gap is above {GAP_Z:g} standard "
              f"errors (SE, from the spread of the per-idea differences; a smaller gap is within noise). FLAG when "
              f"the gap exceeds {GAP_FLAG:g}."]
    rows, pair_rows = [], []
    for j in labels:
        if info[j]["provisional"]:
            lines.append(f"- {tag(j)}: excluded (provisional seat)")
            continue
        if j not in gap:
            lines.append(f"- {j}: {notes.get(j) or 'no vendor: not computed'}")
            continue
        g = gap[j]
        rows.append({"judge": j, "gap": round(g["gap"], 3), "se": round(g["se"], 3), "n": g["n"], "base": g["base"],
                     "vs": g["vs"], "flag": g["flag"]})
        lines.append(f"- {j}: {g['gap']:+.2f} over {g['n']} own-vendor ideas (against {', '.join(g['vs'])}; "
                     f"{g['base']} ideas from neither vendor)"
                     + (f"; its own-vendor scores are lowered by {g['cut']:.2f}" if g["cut"] > 0 else
                        f"; not corrected: within noise (SE {g['se']:.2f}, needs above {GAP_Z:g} SE)"
                        if g["gap"] > 0 else "")
                     + (f"  <- FLAG: gap above {GAP_FLAG:g}" if g["flag"] else ""))
    for p in pair_gaps:
        pair_rows.append({"a": p["a"], "b": p["b"], "gap": round(p["gap"], 3), "n_a": p["n_a"], "n_b": p["n_b"],
                          "warn": p["warn"]})
        lines.append(f"- {'WARN: ' if p['warn'] else ''}{p['a']} and {p['b']} together: {p['gap']:+.2f} on their own "
                     f"vendors' ideas ({p['n_a']} and {p['n_b']} ideas; fewer than {GAP_MIN} ideas from neither "
                     "vendor, so which judge adds how much cannot be told and neither score is corrected)")
    summary = {"judges": [{"label": j, "provisional": info[j]["provisional"]} for j in labels],
               "agreement": {"pairs": pairs, "warn": warn}, "own_origin_gap": rows, "own_origin_pairs": pair_rows}
    return lines, summary


def centered_means(judges, jinfo, origins, weights):
    """The screen's scoring (5.7), shared by `screen` and quick-pick's blind quick screen.

    Every judge's scores count (all measurements: a two-judge panel keeps both). Self-preference is measured as a
    difference in differences (own_origin_gaps), and a judge whose gap is above GAP_Z standard errors has its scores
    of its own vendor's ideas lowered by that gap (never below 1; a gap within noise is left alone, so a small pool
    is not "corrected" for noise; a gap above GAP_FLAG is also flagged for the human). Per-judge
    centering (location, per criterion) then moves each judge's mean to the panel mean, so a lenient or harsh judge
    shifts nothing, also for an idea some judge did not score. The means are taken over the reference ideas, which
    belong to no judge's vendor (human, mixed, imported), so a self-preferring judge cannot shift them; with fewer
    than 3 reference ideas, over every idea the judge scored.
    Returns {"means": {id: {criterion: centered mean or None}}, "judges": {id: [labels that scored it]}, "missing":
    {ids some judge scored without every criterion}, "gaps": own_origin_gaps(...), "lowered": {judge: gap},
    "reference": [ids], "use_ref": bool, "mu": {judge: {criterion: mean}}, "panel": {criterion: mean}}."""
    labels = list(judges)
    ids = sorted(set(i for per in judges.values() for i in per))
    gaps = own_origin_gaps(judges, jinfo, origins, weights)
    lowered = dict((j, g["cut"]) for j, g in gaps[0].items() if g["cut"] > 0)
    scored = {}
    for j in labels:
        scored[j] = {}
        for i, r in judges[j].items():
            cut = lowered.get(j, 0.0) if vendor(origins.get(i)) == jinfo[j]["vendor"] else 0.0
            scored[j][i] = dict((k, max(1.0, x - cut)) for k, x in r["c"].items())
    judge_vendors = set(jinfo[j]["vendor"] for j in labels)
    reference = [i for i in ids if vendor(origins.get(i)) not in judge_vendors]
    use_ref = len(reference) >= 3
    basis = reference if use_ref else ids
    mu = {}
    for j in labels:
        mu[j] = {}
        for k in weights:
            vals = [scored[j][i][k] for i in basis if i in scored[j] and k in scored[j][i]] or \
                [c[k] for c in scored[j].values() if k in c]
            if vals:
                mu[j][k] = sum(vals) / len(vals)
    panel = {}
    for k in weights:
        vals = [mu[j][k] for j in labels if k in mu[j]]
        if vals:
            panel[k] = sum(vals) / len(vals)
    means, by, missing = {}, {}, set()
    for i in ids:
        by[i] = [j for j in labels if i in judges[j]]
        means[i] = {}
        for k in weights:
            vals = [scored[j][i][k] - mu[j][k] + panel[k] for j in by[i] if k in scored[j][i]]
            if len(vals) < len(by[i]):
                missing.add(i)
            means[i][k] = sum(vals) / len(vals) if vals else None
    return {"means": means, "judges": by, "missing": missing, "gaps": gaps, "lowered": lowered,
            "reference": reference, "use_ref": use_ref, "mu": mu, "panel": panel}


def screen(root):
    rj = need_run_json(root, "screen")
    weights = {k: float(v) for k, v in need_json(os.path.join(root, "criteria.json"), model=True).items()}
    clusters = opt_json(os.path.join(root, "clusters.json"))
    origins = opt_json(os.path.join(root, "origins.json"))
    ideas_md = os.path.join(root, "screen", "ideas.md")
    known = set(ln.split("|")[0].strip() for ln in read_text(ideas_md).splitlines() if ln.strip()) \
        if os.path.exists(ideas_md) else set()
    judges, answered, warnings, nfiles = screen_records(root, weights, known)
    ids = sorted(set(i for per in judges.values() for i in per))
    if not ids:
        die("no scores found in screen/*.out.json", 4 if not nfiles else 5)
    labels = list(judges)
    jinfo = judge_info(root, labels, "screen", answered)

    scoring = centered_means(judges, jinfo, origins, weights)
    gaps, lowered, reference, use_ref = scoring["gaps"], scoring["lowered"], scoring["reference"], scoring["use_ref"]
    mu, panel, missing = scoring["mu"], scoring["panel"], scoring["missing"]

    info, self_judged = {}, []
    for i in ids:
        js = scoring["judges"][i]
        v = vendor(origins.get(i))
        if v is not None and all(jinfo[j]["vendor"] == v for j in js):
            self_judged.append(i)  # only judges of the idea's own vendor scored it
        means = scoring["means"][i]
        present = [x for x in means.values() if x is not None]
        # K3 on the centered means; a criterion every judge scored at the lowest anchor (1) always trips it, since
        # centering can lift a harsh judge's 1 above the floor (a scale-minimum verdict is never lifted)
        bottom = any(all(judges[j][i]["c"][k] <= 1 for j in js if k in judges[j][i]["c"])
                     and any(k in judges[j][i]["c"] for j in js) for k in weights)
        fails = [judges[j][i]["fail"] for j in js]
        info[i] = dict(
            means=means, w=weighted(means, weights) or 0.0, judges=len(js),
            # K1: at least two judges and all of them failed the same gate; a single failing judge only flags
            kill=len(js) >= 2 and any(all(f[g] for f in fails) for g in GATES),
            flag=any(f[g] for f in fails for g in GATES),                       # at least one judge did
            floor=(bool(present) and min(present) <= 1.5) or bottom,           # K3 multiplicative floor
            cluster=clusters.get(i, "?"), origin=origins.get(i, "?"),
            risk=" / ".join(judges[j][i]["risk"] for j in js if judges[j][i]["risk"]))

    base, lo, hi = rank_ranges(ids, lambda k, w: weighted(info[k]["means"], w) or 0.0, weights)
    ok = sorted([k for k in ids if not info[k]["kill"] and not info[k]["floor"]],
                key=lambda k: (-info[k]["w"], k))
    pick, seen = collections.OrderedDict(), set()
    for k in ok:  # diversity quota: best idea of each cluster, at most 10
        if info[k]["cluster"] not in seen and len(pick) < 10:
            seen.add(info[k]["cluster"])
            pick[k] = "best of cluster"
    tail, human, note = protected_slots(ok, {k: info[k]["means"] for k in ids}, {k: info[k]["w"] for k in ids},
                                        weights, lambda k: info[k]["origin"])
    if tail:  # protected tail slot: most distinctive idea that is still feasible
        pick[tail] = pick[tail] + " + tail slot" if tail in pick else "tail slot"
    if human and human not in pick:  # protected human slot (only ideas with a human seed behind them)
        pick[human] = "best human-origin"
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
    centering = (f"the {len(reference)} ideas no judge's vendor wrote" if use_ref else
                 "every idea it scored (fewer than 3 ideas belong to no judge's vendor)")
    lowered_txt = "".join("; %s's scores of its own vendor's ideas are lowered by its own-origin gap (%.2f)"
                          % (j, lowered[j]) for j in sorted(lowered))
    lines.append(f"Auto-shortlist: {len(pick)} ideas. Judge files read: {nfiles}. Every judge's scores count"
                 f"{lowered_txt}; each judge is centered on the panel by its mean over {centering}.")
    if borderline:
        lines.append("Borderline (rank range reaches the shortlist size): " + ", ".join(borderline))
    if self_judged:
        lines.append("Self-judged (only judges of the idea's own vendor scored it): " + ", ".join(self_judged))
    if missing:
        lines.append(f"WARNING: criterion keys missing for {sorted(missing)}; judge JSON must use exactly "
                     f"{list(weights)}")
    one_judge = [k for k in ids if info[k]["judges"] < 2]
    if one_judge and len((rj.get("seats") or {}).get("screen_judges") or []) == 1:
        lines.append("NOTE: one screen judge seat (one model): no second judge checked these scores; K1 needs 2")
    elif one_judge:
        lines.append(f"WARNING: only one judge scored {one_judge} (second family missing or failed)")
    lines.extend(f"WARNING: {w}" for w in warnings)
    if note:
        lines.append(note)
    shortlist = {
        "shortlist": [{"id": k, "reason": r, "score": round(info[k]["w"], 3)} for k, r in pick.items()],
        "killed_gate": [k for k in ids if info[k]["kill"]],
        "floor_fail": [k for k in ids if info[k]["floor"] and not info[k]["kill"]],
        "flagged_gate": [k for k in ids if info[k]["flag"] and not info[k]["kill"]],
        "borderline": borderline,
        "scores": {k: round(info[k]["w"], 3) for k in ids},
        "self_judged": self_judged,
        "centering": {"basis": "reference" if use_ref else "all", "reference": reference,
                      "offsets": {j: round(sum(mu[j][k] - panel[k] for k in mu[j]) / len(mu[j]), 3)
                                  for j in labels if mu[j]}},
        "lowered": dict((j, round(g, 3)) for j, g in sorted(lowered.items()))}
    extra, summary = screen_sections(weights, judges, jinfo, gaps)
    lines.extend(extra)
    shortlist.update(summary)
    table = "\n".join(lines) + "\n"
    write(os.path.join(root, "screen", "table.md"), table)
    write(os.path.join(root, "screen", "shortlist.json"), json.dumps(shortlist, indent=1))
    print(table)


# ---------------------------------------------------------------- tournament

def prepare_tournament(root, per_pair=False):
    from ublib.engine.registry import parse_cards  # the engine's card parser (lazy: only this command needs it)
    d = os.path.join(root, "tournament")
    families = judge_families(root, "tournament_judges", "prepare-tournament")
    if textio.glob_in(d, "*.out.json"):
        die("tournament/*.out.json already exist; move them to another folder before re-preparing", 5)
    for stale in textio.glob_in(d, "*.prompt.md") + textio.glob_in(d, "*.map.json"):
        os.remove(stale)
    # the run's finalists name the cards, as registry.canonical_cards read them at 9.3 (a curated quick id such as
    # 'Q 01' or 'Q-04b' has no leading ID token); a run without finalists reads each heading's leading ID token
    fin = [str(i) for i in run_json(root).get("finalists") or []]
    order, cards = parse_cards(read_text(os.path.join(d, "cards.md")), fin or None)
    ids = list(collections.OrderedDict.fromkeys(order))
    if not 2 <= len(ids) <= 26:
        die(f"need 2-26 cards (headings '## <ID>') in tournament/cards.md, found {len(ids)}", 5)
    header = read_text(os.path.join(d, "header.md")).rstrip()
    # each card is model-written text, quoted as data under its engine label; the block id depends only on the card, so
    # a card reads the same in every call
    quoted = {k: fence_data("CARD", "\n".join(cards[k])).split("\n") for k in ids}
    pairs = list(itertools.combinations(ids, 2))
    pair_rule = "PAIRS (the first card named in a pair is FIRST, the second is SECOND)"
    written = 0
    if not per_pair:
        for fam in families:
            for order in ("fwd", "rev"):
                r = rng(root, f"tournament-{fam}-{order}")  # new letters and pair order for every call
                shown = ids[:]
                r.shuffle(shown)
                label = {k: string.ascii_uppercase[i] for i, k in enumerate(shown)}
                ps = pairs[:]
                r.shuffle(ps)
                body = [header, "", "CARDS"]
                for k in shown:
                    body += ["", f"[Card {label[k]}]"] + quoted[k]
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
        for fam in families:
            for n, (x, y) in enumerate(pairs, 1):
                for order in ("fwd", "rev"):
                    first, second = (x, y) if order == "fwd" else (y, x)
                    body = ([header, "", "CARDS", "", "[Card A]"] + quoted[first] + ["", "[Card B]"] + quoted[second]
                            + ["", pair_rule, "P01: Card A vs Card B"])
                    base = os.path.join(d, f"{fam}_{order}_{n:03d}")
                    write(base + ".prompt.md", "\n".join(body) + "\n")
                    write(base + ".map.json", json.dumps(
                        {"family": fam, "order": order, "pairs": {"P01": {"first": first, "second": second}}},
                        indent=1))
                    written += 1
    mode = "per-pair" if per_pair else "batched"
    print(f"wrote {written} judge prompts ({mode}): {len(ids)} cards, {len(pairs)} pairs, "
          f"families {', '.join(families)}, both orders")


def collect_votes(d):
    """([(label, pair, order, winner or None)], warnings, substitutions, confirmed labels) from
    tournament/*.map.json + *.out.json.

    label = the family that answered the call (answered_by), so a fallback call is counted as the model that ran it;
    except that a call answered by the seat's own `<seat>-alt` (its vendor; by default its model) stays under the seat
    when another call of that seat was answered by the seat itself, so the seat's two orders still pair (one judge,
    not two one-order judges). The substitution is recorded either way.
    One verdict per (call, pair id), pair ids compared as the contract's cover compares them (validate.canonical_id): a
    repeated pair id keeps its first verdict. TIE is None."""
    votes, warnings, subs, answered = [], [], [], set()
    calls = []
    for mp in sorted(textio.glob_in(d, "*.map.json")):
        meta = load(mp)
        out = mp[: -len(".map.json")] + ".out.json"
        if not os.path.exists(out):
            warnings.append(f"missing {os.path.basename(out)}: that call is ignored")
            continue
        try:
            verdict_list = load_model(out).get("verdicts", [])
        except (ValueError, AttributeError) as exc:
            warnings.append(f"unreadable {os.path.basename(out)} ({exc}): that call is ignored")
            continue
        seat = meta["family"]
        label, confirmed = answered_by(out, seat)
        if confirmed:
            answered.add(label)
        if label != seat:
            subs.append({"seat": seat, "actual": label, "call": os.path.basename(out)})
        calls.append((meta, out, seat, label, verdict_list))
    by_self = set(seat for _m, _o, seat, label, _v in calls if label == seat)
    for meta, out, seat, label, verdict_list in calls:
        if label == seat + "-alt" and seat in by_self:
            label = seat
        seen = set()
        for v in verdict_list if isinstance(verdict_list, list) else []:
            if not isinstance(v, dict):
                continue
            pid = validate.canonical_id(v.get("pair_id", ""))
            p = meta["pairs"].get(pid)
            if p is None:
                continue
            if pid in seen:
                warnings.append(f"{os.path.basename(out)}: {pid} judged twice; the first verdict counts")
                continue
            seen.add(pid)
            verdict = str(v.get("winner", "")).strip().upper()
            winner = {"FIRST": p["first"], "SECOND": p["second"]}.get(verdict)
            votes.append((label, tuple(sorted((p["first"], p["second"]))), meta.get("order"), winner))
    return votes, warnings, subs, answered


def tally(votes):
    """(pts, kinds, cons) per (judge, pair) (5.7).

    pts: 1/0 when both orders were judged and every verdict of that judge on the pair names the same card; otherwise
    0.5/0.5 (TIE, an order-dependent verdict, or one order missing: balanced position calibration). kinds: win, tie
    (TIE in both orders), split (order-dependent) or single (one order only).
    cons: {judge: [consistent, pairs]} over the pairs the judge saw in both orders, graded as 1 - |s_fwd - s_rev|,
    s = the first card's mean share in that order (win 1, TIE 0.5, loss 0): the same winner and TIE in both orders
    are consistent, TIE in one order counts half, a flip counts 0."""
    by = collections.OrderedDict()
    for label, pair, order, winner in votes:
        by.setdefault((label, pair), {}).setdefault(order, []).append(winner)
    pts, kinds, cons = {}, {}, collections.OrderedDict()
    for (f, pair), ws in by.items():
        both = bool(ws.get("fwd")) and bool(ws.get("rev"))
        allw = [w for o in ws for w in ws[o]]
        c = cons.setdefault(f, [0.0, 0])
        if both and allw[0] is not None and all(w == allw[0] for w in allw):
            loser = pair[1] if allw[0] == pair[0] else pair[0]
            pts[(f, pair)], kinds[(f, pair)] = {allw[0]: 1.0, loser: 0.0}, "win"
        else:
            pts[(f, pair)] = {pair[0]: 0.5, pair[1]: 0.5}
            kinds[(f, pair)] = "single" if not both else ("tie" if all(w is None for w in allw) else "split")
        if both:
            s = [sum(1.0 if w == pair[0] else (0.5 if w is None else 0.0) for w in ws[o]) / len(ws[o])
                 for o in ("fwd", "rev")]
            c[0] += 1.0 - abs(s[0] - s[1])
            c[1] += 1
    return pts, kinds, cons


def pair_evidence(entries, origins, info):
    """({pair: share of pair[0]}, {pair: "neutral" | "self-judged"}) from [((judge, pair), points)].

    Every pair weighs 1, whatever its number of judges. A judge whose vendor owns exactly one of the two cards is
    self-interested; the neutral judges decide the pair. With no neutral judge, the pair is decided by the
    self-interested judges only when both cards' vendors judged it (each vendor's mean counts once, so the two pulls
    cancel) and is marked self-judged; a pair that only one card's vendor judged stays unscored (missing, never 0)."""
    neutral, conflicted = collections.defaultdict(list), collections.defaultdict(dict)
    for (f, pair), s in entries:
        vf = info.get(f, {}).get("vendor")
        owns = sum(1 for k in pair if vf is not None and vendor(origins.get(k)) == vf)
        if owns == 1:
            conflicted[pair].setdefault(vf, []).append(s[pair[0]])
        else:
            neutral[pair].append(s[pair[0]])
    share, how = {}, {}
    for pair in sorted(set(neutral) | set(conflicted)):
        if neutral.get(pair):
            share[pair], how[pair] = sum(neutral[pair]) / len(neutral[pair]), "neutral"
        elif len(conflicted.get(pair, {})) == 2:
            means = [sum(v) / len(v) for v in conflicted[pair].values()]
            share[pair], how[pair] = sum(means) / 2.0, "self-judged"
    return share, how


def bradley_terry(cards, share, start=None, tol=1e-10, iters=5000):
    """Bradley-Terry strengths {card: p} by Hunter's (2004) MM iterations on one observation per scored pair (the
    share is a fractional win, a TIE half a win) plus BT_PRIOR wins for each card of every pair, a virtual tie that
    keeps the fit defined for incomplete or one-sided designs. Strengths are normalized to geometric mean 1."""
    n = len(cards)
    ix = {c: i for i, c in enumerate(cards)}
    w = [[0.0] * n for _ in range(n)]
    tot = [[2.0 * BT_PRIOR] * n for _ in range(n)]
    for (a, b), s in share.items():
        i, j = ix[a], ix[b]
        w[i][j] += s
        w[j][i] += 1.0 - s
        tot[i][j] += 1.0
        tot[j][i] += 1.0
    wins = [BT_PRIOR * (n - 1) + sum(w[i]) for i in range(n)]
    p = [start[c] for c in cards] if start else [1.0] * n
    for _ in range(iters):
        new = [wins[i] / sum(tot[i][j] / (p[i] + p[j]) for j in range(n) if j != i) for i in range(n)]
        g = math.exp(sum(math.log(x) for x in new) / n)
        new = [x / g for x in new]
        step = max(abs(math.log(new[i] / p[i])) for i in range(n))
        p = new
        if step < tol:
            break
    return dict(zip(cards, p))


def win_share(cards, p):
    """{card: expected win share in percent against the other cards} for Bradley-Terry strengths p."""
    n = len(cards)
    return {c: 100.0 * sum(p[c] / (p[c] + p[d]) for d in cards if d != c) / (n - 1) for c in cards}


def _groups(cards, share):
    """Connected components of the comparison graph (cards as nodes, scored pairs as edges), sorted."""
    parent = {c: c for c in cards}

    def root(c):
        while parent[c] != c:
            parent[c] = parent[parent[c]]
            c = parent[c]
        return c
    for a, b in share:
        parent[root(a)] = root(b)
    out = collections.defaultdict(list)
    for c in cards:
        out[root(c)].append(c)
    return sorted(sorted(g) for g in out.values())


def _cycles(cards, beats):
    """Majority cycles: the strongly connected groups (2 or more cards) of the beat graph."""
    reach = {c: set(beats[c]) for c in cards}
    for k in cards:  # transitive closure (Floyd-Warshall; at most 26 cards)
        for c in cards:
            if k in reach[c]:
                reach[c] |= reach[k]
    out, done = [], set()
    for c in cards:
        if c in done:
            continue
        group = sorted({c} | {d for d in reach[c] if c in reach[d]})
        done |= set(group)
        if len(group) > 1:
            out.append(group)
    return out


def _quantile(values, q, up):
    vals = sorted(values)
    k = q * (len(vals) - 1)
    return vals[int(math.ceil(k) if up else math.floor(k))]


def analyze_tournament(pts, kinds, cons, origins, info, order, rnd=None, resamples=BOOTSTRAP):
    """N-family analysis (5.7): raw points, the debiased ranking (pair-level Bradley-Terry with seeded bootstrap
    intervals, or raw points with a visible reason when the bias-free comparison graph is disconnected or every
    judge is position-flagged), the Condorcet winner and majority cycles, contested pairs, consistency, audits.
    rnd: a seeded random.Random for the bootstrap (None: no intervals)."""
    present = {f for f, _ in pts}
    fams = [f for f in order if f in present] + sorted(present - set(order))
    pairs = sorted({p for _, p in pts})
    cards = sorted({k for p in pairs for k in p})
    n = len(cards)

    def raw_scores(use):
        score = collections.Counter({k: 0.0 for k in cards})
        for (f, _p), s in pts.items():
            if f in use:
                for k, v in s.items():
                    score[k] += v
        return score

    raw = raw_scores(set(fams))
    consistency = {f: (cons[f][0] / cons[f][1] if f in cons and cons[f][1] else None) for f in fams}
    pos_flag = [f for f in fams if consistency[f] is not None and consistency[f] < POSITION_FLAG]

    contested = []
    for pair in pairs:
        decisive = [max(pts[(f, pair)], key=pts[(f, pair)].get) for f in fams if kinds.get((f, pair)) == "win"]
        if not decisive:
            tie = any(kinds.get((f, pair)) == "tie" for f in fams)
            contested.append([pair[0], pair[1], "the judges call it a tie" if tie else "no order-consistent verdict"])
            continue
        modal = collections.Counter(decisive).most_common(1)[0][1]
        if modal * 3 < 2 * len(decisive):  # the modal winner holds less than 2/3 of the order-consistent families
            contested.append([pair[0], pair[1], "families disagree"])

    # A judge's verdict on a pair it saw in one order only (kind single: one of its calls failed or is missing) is no
    # evidence: it is a forced 0.5/0.5, and counted as neutral it would outweigh the both-order verdicts of the
    # self-interested judges. It stays in the raw standings (0.5/0.5 for each such pair of that judge).
    kept = [((f, p), s) for (f, p), s in sorted(pts.items()) if f not in pos_flag and kinds.get((f, p)) != "single"]
    share, how = pair_evidence(kept, origins, info)
    method, reason = "bradley-terry", None
    if not kept and fams and all(f in pos_flag for f in fams):
        method, reason = "raw-fallback", "every judge family is flagged for position consistency (below 60%)"
    elif not kept:
        method, reason = "raw-fallback", ("no judge family that is not flagged judged a pair in both orders (a "
                                          "one-order verdict is no evidence)")
    else:
        groups = _groups(cards, share)
        if len(groups) > 1:
            method = "raw-fallback"
            reason = ("the pairs left after removing self-interested verdicts do not connect the finalists (%d "
                      "separate groups: %s)" % (len(groups), "; ".join(", ".join(g) for g in groups)))
    fb_fams = [f for f in fams if f not in pos_flag] or fams
    fb = raw_scores(set(fb_fams))
    fb_max = len(fb_fams) * (n - 1)

    rows = []
    if method == "bradley-terry":
        p = bradley_terry(cards, share)
        pct = win_share(cards, p)
        ranked = sorted(cards, key=lambda c: (-round(pct[c], 9), -raw[c], c))
        ci, rr = {}, {}
        if rnd is not None and resamples:
            draws, ranks = {c: [] for c in cards}, {c: [] for c in cards}
            for _ in range(resamples):  # resample the judges' (judge, pair) verdicts with replacement
                sample = [kept[rnd.randrange(len(kept))] for _ in kept]
                pb = win_share(cards, bradley_terry(cards, pair_evidence(sample, origins, info)[0], start=p, tol=1e-7))
                for r, c in enumerate(sorted(cards, key=lambda c: (-round(pb[c], 9), -raw[c], c)), 1):
                    ranks[c].append(r)
                    draws[c].append(pb[c])
            ci = {c: [round(_quantile(draws[c], 0.05, False), 1), round(_quantile(draws[c], 0.95, True), 1)]
                  for c in cards}
            rr = {c: [_quantile(ranks[c], 0.05, False), _quantile(ranks[c], 0.95, True)] for c in cards}
        scored = collections.Counter(k for pair in share for k in pair)
        for r, c in enumerate(ranked, 1):
            rows.append({"id": c, "pct": round(pct[c], 1), "n": scored[c], "rank": r, "ci": ci.get(c),
                         "rank_range": rr.get(c)})
        evidence = share
    else:
        ranked = sorted(cards, key=lambda c: (-fb[c], -raw[c], c))
        for r, c in enumerate(ranked, 1):
            rows.append({"id": c, "pct": round(100.0 * fb[c] / fb_max, 1) if fb_max else 0.0, "n": n - 1,
                         "rank": r, "ci": None, "rank_range": None})
        evidence = {}
        for pair in pairs:
            vals = [pts[(f, pair)][pair[0]] for f in fb_fams if (f, pair) in pts]
            if vals:
                evidence[pair] = sum(vals) / len(vals)

    beats = {c: set() for c in cards}
    for (a, b), s in evidence.items():
        if s > 0.5:
            beats[a].add(b)
        elif s < 0.5:
            beats[b].add(a)
    condorcet = next((c for c in cards if len(beats[c]) == n - 1), None)
    cycles = _cycles(cards, beats)
    listed = {(a, b) for a, b, _w in contested}
    for group in cycles:
        for a in group:
            for b in sorted(beats[a] & set(group)):
                pair = tuple(sorted((a, b)))
                if pair not in listed:
                    listed.add(pair)
                    contested.append([pair[0], pair[1], "majority cycle"])
    if condorcet and ranked[0] != condorcet:
        pair = tuple(sorted((condorcet, ranked[0])))
        if pair not in listed:
            contested.append([pair[0], pair[1], "rank reversal: the pairwise-majority winner is not ranked first"])
    contested.sort(key=lambda c: (c[0], c[1]))

    def card_vendor(k):
        return vendor(origins.get(k))

    def both_orders(g, p):
        return (g, p) in pts and kinds.get((g, p)) != "single"  # a one-order 0.5 says nothing about preference

    audit, self_flag = [], []
    auditable = [f for f in fams if not info.get(f, {}).get("provisional")]
    for f in fams:
        if info.get(f, {}).get("provisional"):
            continue
        vf = info.get(f, {}).get("vendor")
        if vf is None or not any(card_vendor(k) == vf for k in cards):
            continue
        mixed = [p for p in pairs if sum(1 for k in p if card_vendor(k) == vf) == 1]
        mine, theirs = [], []
        for p in mixed:
            own = p[0] if card_vendor(p[0]) == vf else p[1]
            if both_orders(f, p):
                mine.append(pts[(f, p)][own])
            for g in auditable:
                if g != f and both_orders(g, p):
                    theirs.append(pts[(g, p)][own])
        if not mine or not theirs:
            continue
        m_share, t_share = sum(mine) / len(mine), sum(theirs) / len(theirs)
        diff = m_share - t_share
        flag = diff > 0.15
        if flag:
            self_flag.append(f)
        audit.append({"judge": f, "vendor": vf, "own_share": round(m_share, 3), "n": len(mine),
                      "others_share": round(t_share, 3), "others_n": len(theirs), "diff": round(diff, 3),
                      "flag": flag})

    flagged = [f for f in fams if f in pos_flag or f in self_flag]
    clean_fams = [f for f in fams if f not in flagged]
    excl = raw_scores(set(clean_fams)) if flagged and clean_fams else None
    result = {
        "families": fams,
        "raw": [{"id": k, "points": round(raw[k], 2), "max": len(fams) * (n - 1)}
                for k in sorted(cards, key=lambda c: (-raw[c], c))],
        "debiased": rows,
        "ranking": {"method": method, "reason": reason, "prior": BT_PRIOR,
                    "resamples": resamples if method == "bradley-terry" and rnd is not None else 0,
                    "families_used": fb_fams if method != "bradley-terry" else [f for f in fams if f not in pos_flag],
                    "self_judged": [list(p) for p in pairs if how.get(p) == "self-judged"],
                    "unscored": [list(p) for p in pairs if p not in share] if kept else []},
        "condorcet": {"winner": condorcet, "cycles": cycles},
        "contested": contested,
        "consistency": {f: (None if v is None else round(v, 2)) for f, v in consistency.items()},
        "flags": {"position": pos_flag, "self_preference": self_flag},
        "provisional": [f for f in fams if info.get(f, {}).get("provisional")],
        "audit": audit,
    }
    if excl is not None:
        result["raw_excluding_flagged"] = {
            "families": clean_fams,
            "standings": [{"id": k, "points": round(excl[k], 2), "max": len(clean_fams) * (n - 1)}
                          for k in sorted(cards, key=lambda c: (-excl[c], c))]}
    return result


def tournament_text(res, cons, origins, info, warnings):
    fams = res["families"]
    n_cards = len(res["raw"])

    def tag(f):
        return f + (" (PROVISIONAL)" if info.get(f, {}).get("provisional") else "")

    def vs(pairs):
        return "; ".join(f"{a} vs {b}" for a, b in pairs)

    out = [f"## Standings (max = {len(fams)} families x {n_cards - 1} opponents = {len(fams) * (n_cards - 1)} points)"]
    for rank, r in enumerate(res["raw"], 1):
        out.append(f"{rank}. {r['id']}  {r['points']:.1f}  (origin: {origins.get(r['id'], '?')})")
    rk = res["ranking"]
    out += ["", "## Debiased ranking (default for recommendations)"]
    if rk["method"] == "bradley-terry":
        out.append("Bradley-Terry fit (MM iterations, Hunter 2004) on one share per pair, so every pair weighs 1. A "
                   "judge family's verdict on a pair where exactly one card comes from its own vendor is left out; a "
                   "pair with no neutral judge keeps both vendors' judges (self-judged); a verdict from one order "
                   "only and families flagged for position consistency are left out. TIE = half a win; a prior of "
                   f"{rk['prior']:g} wins per card and "
                   "pair. % = expected win share against the other finalists"
                   + (f"; 90% intervals from {rk['resamples']} seeded bootstrap resamples of the judges' pair "
                      "verdicts" if rk["resamples"] else "") + ". Ties: raw points.")
    else:
        out.append(f"RANKING FELL BACK TO RAW POINTS: {rk['reason']}. % = raw points / possible "
                   f"({', '.join(rk['families_used'])}).")
    for d in res["debiased"]:
        extra = (f"90% CI {d['ci'][0]:.1f}-{d['ci'][1]:.1f}, rank {d['rank_range'][0]}-{d['rank_range'][1]}; "
                 if d.get("ci") else "")
        out.append(f"{d['rank']}. {d['id']}  {d['pct']:.1f}%  ({extra}pairs {d['n']}; "
                   f"origin: {origins.get(d['id'], '?')})")
    if rk["self_judged"]:
        out.append("Self-judged pairs (no neutral judge; both vendors' judges kept): " + vs(rk["self_judged"]))
    if rk["unscored"]:
        out.append("Pairs without bias-free evidence (no neutral judge and not both cards' vendors judged them in both "
                   "orders): " + vs(rk["unscored"]))
    cw = res["condorcet"]
    out.append("Condorcet winner (beats every other finalist by pairwise majority): " + (cw["winner"] or "none"))
    if cw["cycles"]:
        out.append("Majority cycles (these finalists beat each other in a circle): "
                   + "; ".join(", ".join(g) for g in cw["cycles"]))
    out += ["", "## Contested pairs (the human decides these)"]
    for a, b, why in res["contested"]:
        out.append(f"- {a} vs {b}: " + ("judge families disagree" if why == "families disagree" else why))
    if not res["contested"]:
        out.append("- none")
    out += ["", "## Judge position consistency (same winner in both orders; TIE in both orders is consistent, "
                "TIE in one order counts half)"]
    for f in fams:
        c = cons.get(f)
        if c and c[1]:
            share = c[0] / c[1]
            flag = "  <- below 60%: discount this family's verdicts" if share < POSITION_FLAG else ""
            out.append(f"- {tag(f)}: {c[0]:g}/{c[1]} = {share:.0%}{flag}")
        else:
            out.append(f"- {tag(f)}: only one order judged; its verdicts count 0.5/0.5 in the raw standings and are "
                       "left out of the debiased ranking")
    if res.get("substitutions"):
        out += ["", "## Judge substitutions (a fallback call counts as the family that answered it)"]
        out += [f"- {s['call']}: the {s['seat']} seat was answered by {s['actual']}" for s in res["substitutions"]]
    out += ["", "## Self-preference audit (own-vendor win share in mixed pairs vs the other non-provisional judges)"]
    for f in fams:
        if info.get(f, {}).get("provisional"):
            out.append(f"- {tag(f)}: excluded from the audit (provisional seat)")
    for a in res["audit"]:
        flag = "  <- favours its own vendor's ideas by >15 points: discount it" if a["flag"] else ""
        out.append(f"- judge {a['judge']} on {a['vendor']}-origin ideas: {a['own_share']:.0%} (n={a['n']}) vs "
                   f"other judges {a['others_share']:.0%} (n={a['others_n']}): {100 * a['diff']:+.0f} points{flag}")
    if not res["audit"]:
        out.append("- no judge had own-vendor finalists in mixed pairs")
    if "raw_excluding_flagged" in res:
        ex = res["raw_excluding_flagged"]
        flagged = [f for f in fams if f not in ex["families"]]
        out += ["", f"## Standings excluding flagged families ({', '.join(flagged)})"]
        for rank, r in enumerate(ex["standings"], 1):
            out.append(f"{rank}. {r['id']}  {r['points']:.1f} / {r['max']}  (origin: {origins.get(r['id'], '?')})")
    if warnings:
        out += ["", "## Warnings"] + [f"- {w}" for w in warnings]
    return "\n".join(out) + "\n"


def tournament(root):
    order = judge_families(root, "tournament_judges", "tournament")
    d = os.path.join(root, "tournament")
    origins = opt_json(os.path.join(root, "origins.json"))
    votes, warnings, subs, answered = collect_votes(d)
    if not votes:
        has_out = bool(textio.glob_in(d, "*.out.json"))
        die("no verdicts found in tournament/*.out.json", 5 if has_out else 4)
    pts, kinds, cons = tally(votes)
    labels = sorted({f for f, _ in pts})
    info = judge_info(root, labels, "tournament", answered)
    res = analyze_tournament(pts, kinds, cons, origins, info, order, rnd=rng(root, "tournament-bootstrap"))
    if subs:
        res["substitutions"] = subs
    text = tournament_text(res, cons, origins, info, warnings)
    write(os.path.join(d, "result.md"), text)
    if warnings:
        res["warnings"] = warnings
    textio.write_json_atomic(os.path.join(d, "result.json"), res)
    print(text)


# ---------------------------------------------------------------- quick-pick (quick mode)

def _one_line(value, default="not stated"):
    text = " ".join(str(value if value is not None else "").replace("|", "/").split())
    return text or default


def quick_origins(root, by_id):
    """({id: origin}, warnings) for quick/curated.json ideas. The curator scores blind to the model families (#51), so
    an idea's origin comes from its aliases and pool/_families.json by map's rule (a human prefix H... is human), never
    from the scoring model. An idea without aliases (a curated.json an older kit wrote) keeps its own origin field."""
    fam_path = os.path.join(root, "pool", "_families.json")
    fam_of = {str(k): str(v) for k, v in (opt_json(fam_path) or {}).items()}
    out, warnings = {}, []
    for iid, idea in by_id.items():
        aliases = [str(a).strip() for a in idea.get("aliases") or [] if str(a).strip()]
        if not aliases:
            out[iid] = str(idea.get("origin", "?")).strip() or "?"
            continue
        fams = set()
        for p in (alias_prefix(a) for a in aliases):
            if p.upper().startswith("H"):
                fams.add("human")
            elif p in fam_of:
                fams.add(fam_of[p])
            else:
                warnings.append(f"{iid}: alias prefix {p} is not in pool/_families.json: origin '?'")
                fams.add("?")
        out[iid] = lineage_origin(fams)
    return out, warnings


QUICK_SCORES = ("auto", "blind", "curator")
CURATOR_SCORES_NOTE = ("scores: the curator's own (no blind quick screen scored the ideas: it needs screen judges of two "
                       "model vendors, so a one-family run keeps the curator's scores)")


def curator_scores(by_id, weights):
    """The curator's own criterion scores and gate verdicts in quick/curated.json: ({id: {criterion: score}},
    {id: {gate: failed}})."""
    lower = {c.lower(): c for c in weights}
    vals, fails = {}, {}
    for iid, idea in by_id.items():
        v = {}
        for s in idea.get("scores") or []:
            name = str((s or {}).get("criterion", "")).strip()
            key = name if name in weights else lower.get(name.lower())
            x = as_float((s or {}).get("score"))
            if key and x is not None:
                v[key] = x
        vals[iid] = v
        fails[iid] = {g: is_false((idea.get("gates") or {}).get(g, True)) for g in GATES}
    return vals, fails


def quick_screen(root, by_id, origin, weights, curator_fails):
    """The blind quick screen (Q.3s, #51): the quick screen judges' scores of the curated ideas' neutral lines
    (screen/*.out.json, read like `screen` reads them), with the screen's scoring (centered_means: every judge counts,
    an own-origin gap above its noise lowers that judge's scores of its own vendor's ideas, per-judge centering), so the
    curator's own scores never pick the finalists. Gates, as the screen's K1: an idea fails when at least two voters
    scored it and all of them failed the same gate; the voters are the blind judges, and the curator only where a
    single blind judge scored the idea. Any other failed gate (one judge, or the curator) flags the idea.
    Returns None when no screen/*.out.json exists, else {"vals": {id: {criterion: centered mean}}, "failed": {id:
    bool}, "flagged": [ids], "judges": [labels], "lines": the Judge agreement and Own-origin gap sections, "summary":
    their shortlist.json-style summary plus "lowered", "notes", "lowered", "use_ref", "reference"}."""
    judges, answered, warnings, nfiles = screen_records(root, weights, set(by_id))
    if not nfiles:
        return None
    labels = list(judges)
    if not any(judges.values()):
        die("no scores found in screen/*.out.json (the blind quick screen)", 5)
    jinfo = judge_info(root, labels, "screen", answered)
    scoring = centered_means(judges, jinfo, origin, weights)
    vals, failed, flagged, unscored = {}, {}, [], []
    for iid in by_id:
        js = scoring["judges"].get(iid) or []
        vals[iid] = dict((k, x) for k, x in (scoring["means"].get(iid) or {}).items() if x is not None)
        votes = [judges[j][iid]["fail"] for j in js] + ([curator_fails[iid]] if len(js) < 2 else [])
        failed[iid] = len(votes) >= 2 and any(all(v[g] for v in votes) for g in GATES)
        if not failed[iid] and any(v[g] for v in votes + [curator_fails[iid]] for g in GATES):
            flagged.append(iid)
        if not js:
            unscored.append(iid)
    notes = list(warnings)
    if unscored:
        notes.append("no blind judge scored %s: ranked last" % ", ".join(unscored))
    if len(labels) < 2:
        notes.append("one blind judge (%s) scored the ideas: no second judge checked these scores, and the curator's "
                      "gates are the second gate voter" % ", ".join(labels))
    if scoring["missing"]:
        notes.append(f"criterion keys missing for {sorted(scoring['missing'])}; judge JSON must use exactly "
                     f"{list(weights)}")
    lines, summary = screen_sections(weights, judges, jinfo, scoring["gaps"])
    lines = [ln.replace("count in the shortlist", "count in the quick pick") for ln in lines]
    summary["lowered"] = dict((j, round(g, 3)) for j, g in sorted(scoring["lowered"].items()))
    return {"vals": vals, "failed": failed, "flagged": flagged, "judges": labels, "lines": lines,
            "summary": summary, "notes": notes, "lowered": scoring["lowered"], "use_ref": scoring["use_ref"],
            "reference": scoring["reference"]}


def _quick_screen_md(by_id, origin, score, cur_score, failed, flagged, picks, blind):
    """quick/screen.md: how the finalists were scored, for the human (the judges never see it)."""
    if blind is None:
        head = ["# Quick screen", "", "No blind quick screen ran: the curator's own scores picked the finalists "
                "(one model family, or `--scores curator`).", ""]
    else:
        centering = (f"the {len(blind['reference'])} ideas no judge's vendor wrote" if blind["use_ref"] else
                     "every idea it scored (fewer than 3 ideas belong to no judge's vendor)")
        lowered = "".join("; %s's scores of its own vendor's ideas are lowered by its own-origin gap (%.2f)"
                          % (j, blind["lowered"][j]) for j in sorted(blind["lowered"]))
        head = ["# Quick screen (blind)", "",
                f"Scored by {', '.join(blind['judges'])} from the curated neutral lines, without source labels and "
                f"each in its own random order. Every judge's scores count{lowered}; each judge is centered on the "
                f"panel by its mean over {centering}. The curator's scores are shown for comparison only.", ""]
    rows = ["| id | cluster | origin | score | curator score | gates | finalist |", "|---|---|---|---|---|---|---|"]
    for i in sorted(by_id, key=lambda k: (-score[k], k)):
        gate = "FAIL" if failed[i] else ("flag" if i in flagged else "ok")
        rows.append(f"| {i} | {_one_line(by_id[i].get('cluster'), '?')} | {origin[i]} | {score[i]:.2f} | "
                    f"{cur_score[i]:.2f} | {gate} | {picks.get(i, '')} |")
    return "\n".join(head + rows + (blind["lines"] if blind else [])) + "\n"


def quick_pick(root, scores="auto"):
    """quick/curated.json -> finalists (5.7). scores: "blind" takes the blind quick screen (screen/*.out.json; exit 4
    without it), "curator" the curator's own scores and gates (a one-family run, flagged), "auto" the blind quick
    screen when its outputs exist, else the curator's."""
    cur = need_json(os.path.join(root, "quick", "curated.json"), "quick/curated.json", model=True)
    weights = {str(k): float(v) for k, v in need_json(os.path.join(root, "criteria.json"), model=True).items()}
    ideas = cur.get("ideas") if isinstance(cur, dict) else None
    if not isinstance(ideas, list) or not ideas:
        die("quick/curated.json has no ideas", 5)
    by_id = collections.OrderedDict()
    for n, idea in enumerate(ideas):
        if not isinstance(idea, dict) or not str(idea.get("id", "")).strip():
            die(f"quick/curated.json ideas[{n}] lacks 'id'", 5)
        iid = str(idea["id"]).strip()
        if iid in by_id:
            die(f"duplicate id in quick/curated.json: {iid}", 5)
        by_id[iid] = idea
    origin, warnings = quick_origins(root, by_id)
    cur_vals, cur_fails = curator_scores(by_id, weights)
    blind = quick_screen(root, by_id, origin, weights, cur_fails) if scores != "curator" else None
    if blind is None and scores == "blind":
        die("no blind quick-screen scores (screen/*.out.json): run the quick screen (Q.3p, Q.3s) first, or pass "
            "--scores curator", 4)
    if blind is None:
        vals, failed, flagged = cur_vals, dict((i, any(f.values())) for i, f in cur_fails.items()), []
        warnings = [CURATOR_SCORES_NOTE] + warnings
    else:
        vals, failed, flagged = blind["vals"], blind["failed"], blind["flagged"]
        warnings += blind["notes"]
    score = dict((i, weighted(vals[i], weights) or 0.0) for i in by_id)
    cur_score = dict((i, weighted(cur_vals[i], weights) or 0.0) for i in by_id)
    passed = [i for i in by_id if not failed[i]]
    passed.sort(key=lambda i: (-score[i], i))
    picks, protected, seen = collections.OrderedDict(), set(), set()
    for i in passed:  # best of each cluster
        cl = str(by_id[i].get("cluster", "?"))
        if cl not in seen:
            seen.add(cl)
            picks[i] = "best of cluster"
    t, h, note = protected_slots(passed, vals, score, weights, lambda i: origin[i])
    notes = ([note] if note else []) + list(collections.OrderedDict.fromkeys(warnings))
    if t:  # tail slot: highest Distinctiveness with Feasibility >= 3
        picks[t] = picks[t] + " + tail slot" if t in picks else "tail slot"
        protected.add(t)
    if h:
        picks[h] = picks[h] + " + best human-origin" if h in picks else "best human-origin"
        protected.add(h)
    while len(picks) > 5:  # cap at 5: drop the weakest pick that holds no protected slot
        droppable = [i for i in picks if i not in protected] or list(picks)
        lowest = min(score[i] for i in droppable)
        del picks[max(i for i in droppable if score[i] == lowest)]  # ties: the later id goes
    if len(picks) < 2:
        die(f"quick-pick found {len(picks)} finalist(s) whose gates all pass; at least 2 are needed", 5)
    final = sorted(picks)
    finalists = [{"id": i, "title": _one_line(by_id[i].get("title")), "reason": picks[i],
                  "score": round(score[i], 3), "cluster": str(by_id[i].get("cluster", "?")),
                  "origin": origin[i]} for i in final]
    record = {"finalists": finalists, "scoring": "blind" if blind else "curator", "judges": [],
              "gate_failed": [i for i in by_id if i not in passed], "gate_flagged": flagged, "notes": notes}
    if blind:
        record.update(blind["summary"])
    textio.write_json_atomic(os.path.join(root, "quick", "finalists.json"), record)
    write(os.path.join(root, "quick", "screen.md"),
          _quick_screen_md(by_id, origin, score, cur_score, failed, flagged, picks, blind))
    origins_path = os.path.join(root, "origins.json")
    origins = opt_json(origins_path) if os.path.exists(origins_path) else {}
    origins.update(origin)
    write(origins_path, json.dumps(origins, indent=1))
    body = []
    for i in final:
        idea = by_id[i]
        body += [f"## {i}",
                 f"Title: {_one_line(idea.get('title'))}",
                 f"Problem: {_one_line(idea.get('problem') or idea.get('pitch'))}",
                 f"Mechanism: {_one_line(idea.get('mechanism'))}",
                 f"For whom: {_one_line(idea.get('for_whom'))}",
                 f"First version: {_one_line(idea.get('first_version'))}",
                 f"Main risk: {_one_line(idea.get('fails_if'))}",
                 "Prior art: NOT CHECKED",
                 ""]
    write(os.path.join(root, "tournament", "cards.md"), "\n".join(body))
    how = f"the blind quick screen ({', '.join(blind['judges'])})" if blind else "the curator's own scores"
    print(f"quick-pick: {len(final)} finalists ({', '.join(f'{i} ({picks[i]})' for i in final)}) by {how}; "
          f"wrote quick/finalists.json, quick/screen.md, tournament/cards.md, origins.json")
    for n in notes:
        print("NOTE: " + n)


# ---------------------------------------------------------------- arch-matrix (stage 12)

def _crit_lookup(criteria):
    table = {}
    for cid, _name, _w in criteria:
        table[cid.lower()] = cid
        table[cid.lower().replace("_", " ")] = cid
        table[cid.lower().replace("_", "-")] = cid
    return table


def arch_matrix(root):
    arch = os.path.join(root, "10_ARCHITECTURE")
    drivers = need_json(os.path.join(arch, "drivers.json"), "10_ARCHITECTURE/drivers.json", model=True)
    cmap = need_json(os.path.join(arch, "candidates", "map.json"), "10_ARCHITECTURE/candidates/map.json")
    judge_files = sorted(textio.glob_in(arch, "review", "judge_*.out.json"))
    if not judge_files:
        die("no 10_ARCHITECTURE/review/judge_*.out.json", 4)
    if not isinstance(cmap, dict) or not cmap:
        die("candidates/map.json must map labels to {family, archetype, job}", 5)
    warnings = []
    qgs = []
    for q in (drivers.get("quality_goals") if isinstance(drivers, dict) else None) or []:
        w = as_float((q or {}).get("weight"))
        if not isinstance(q, dict) or not q.get("id") or w is None:
            warnings.append(f"drivers.json quality goal ignored (id or weight missing): {q}")
            continue
        qgs.append((str(q["id"]), _one_line(q.get("name"), str(q["id"])), w))
    if not qgs:
        die("drivers.json has no quality goals with id and weight", 5)
    qsum = sum(w for _i, _n, w in qgs)
    if abs(qsum - 70) > 0.5:
        warnings.append(f"quality-goal weights sum to {qsum:g}, not 70")
    criteria = qgs + list(FIXED_CRITERIA)
    weights = collections.OrderedDict((cid, w) for cid, _n, w in criteria)
    lookup = _crit_lookup(criteria)
    labels = sorted(str(k) for k in cmap)
    author = {lab: base_family((cmap[lab] or {}).get("family") if isinstance(cmap[lab], dict) else "")
              for lab in labels}
    data = {lab: collections.OrderedDict() for lab in labels}
    steal_raw = []
    judges = []
    for path in judge_files:
        seat = os.path.basename(path)[len("judge_"): -len(".out.json")]
        fam = answered_by(path, seat)[0]  # a fallback copy counts as the family that answered
        try:
            out = load_model(path)
        except ValueError as exc:
            warnings.append(f"unreadable {os.path.basename(path)} ({exc}): judge ignored")
            continue
        if not isinstance(out, dict):
            warnings.append(f"{os.path.basename(path)} is not an object: judge ignored")
            continue
        if fam != seat:
            warnings.append(f"the {seat} judge seat was answered by {fam} (fallback): scored as {fam}")
        if fam not in judges:
            judges.append(fam)
        for cand in out.get("candidates") or []:
            if not isinstance(cand, dict):
                continue
            lab = validate.canonical_id(cand.get("label", ""))  # compared as the contract's cover compares it
            if lab not in data:
                warnings.append(f"judge {fam} scored unknown candidate {ascii(lab)}")
                continue
            scores = {}
            for s in cand.get("scores") or []:
                s = s if isinstance(s, dict) else {}
                crit_name, raw_score = s.get("criterion"), s.get("score")
                cid = lookup.get(str(crit_name or "").strip().lower())
                val = as_float(raw_score)
                if cid is None:
                    warnings.append(f"judge {fam}, candidate {lab}: unknown criterion '{crit_name}' ignored")
                    continue
                if val is None or not 1 <= val <= 5:
                    warnings.append(f"judge {fam}, candidate {lab}, {cid}: score {raw_score!r} outside 1-5 ignored")
                    continue
                scores[cid] = val
            rec = {"veto": cand.get("veto") is True or str(cand.get("veto")).lower() == "true",
                   "reason": _one_line(cand.get("veto_reason"), ""),
                   "scores": scores,
                   "sens": [_one_line(x, "") for x in cand.get("sensitivity_points") or []],
                   "trade": [_one_line(x, "") for x in cand.get("tradeoff_points") or []]}
            prev = data[lab].get(fam)
            if prev:  # the same model answered two seats: one judge (scores averaged, one veto at most)
                for cid, v in scores.items():
                    prev["scores"][cid] = (prev["scores"][cid] + v) / 2.0 if cid in prev["scores"] else v
                prev["veto"] = prev["veto"] or rec["veto"]
                prev["reason"] = prev["reason"] or rec["reason"]
                prev["sens"] += rec["sens"]
                prev["trade"] += rec["trade"]
            else:
                data[lab][fam] = rec
        for st in out.get("steal") or []:
            if isinstance(st, dict):
                steal_raw.append((fam, st))

    # Per-judge centering (location): a judge's mean on each criterion, over every candidate it scored (its own
    # family's included), moves to the panel mean, so a lenient or harsh judge no longer lifts the candidates it
    # happens to score. Every judge scores every label (the cover rule), which makes the offsets comparable.
    mu = {}
    for j in judges:
        mu[j] = {}
        for cid in weights:
            vals = [data[lab][j]["scores"][cid] for lab in labels if j in data[lab] and cid in data[lab][j]["scores"]]
            if vals:
                mu[j][cid] = sum(vals) / len(vals)
    panel = {}
    for cid in weights:
        vals = [mu[j][cid] for j in judges if cid in mu[j]]
        if vals:
            panel[cid] = sum(vals) / len(vals)
    offsets = {j: round(sum(mu[j][c] - panel[c] for c in mu[j]) / len(mu[j]), 2) for j in judges if mu[j]}

    # a candidate only its author family's judges scored is self-judged: another family's arch judge failed, or none
    # was seated for it (quick mode with 2 families seats one arch judge, the host, which also wrote a candidate).
    # Not in a one-family run, where one family wrote, judged (and was seated to judge) every candidate.
    try:
        seated = ((run_json(root) or {}).get("seats") or {}).get("arch_judges")
    except BsError:
        seated = None
    one_family = len(set(author.values()) | set(base_family(j) for j in judges)
                     | set(base_family(str(f)) for f in (seated if isinstance(seated, list) else []))) == 1
    eligible, vetoes, self_judged = {}, {}, []
    for lab in labels:
        judged_by = list(data[lab])
        eligible[lab] = [j for j in judged_by if base_family(j) != author[lab]]
        if not eligible[lab] and judged_by:
            eligible[lab] = judged_by
            if not one_family:
                self_judged.append(lab)
            warnings.append(f"candidate {lab}: no judge from another family; all judges used")
        if not judged_by:
            warnings.append(f"candidate {lab}: no judge scored it")
        # every judge's veto counts: an author family vetoing its own candidate is an admission against interest
        vetoes[lab] = [j for j in judged_by if data[lab][j]["veto"]]
    ranked_labels = [lab for lab in labels if len(vetoes[lab]) < 2]
    disjoint = [(a, b) for a, b in itertools.combinations(ranked_labels, 2)
                if not set(eligible[a]) & set(eligible[b])]
    own = {lab: sum(1 for j in data[lab] if base_family(j) == author[lab]) for lab in ranked_labels}
    # Confounded design (e.g. two families judging each other's candidates): some candidates share no eligible
    # judge, so their scores come from different judges. When every candidate has the same number of own-family
    # judges, every judge's centered score counts: an equal self-preference then lifts every candidate alike.
    balanced = bool(disjoint) and len(set(own.values())) == 1 and min(own.values()) >= 1
    if disjoint:
        how = ("scores use every judge's centered scores (each candidate has one own-family judge)" if balanced
               else "their comparison rests on the per-judge centering")
        warnings.append("confounded design: " + "; ".join(f"{a} and {b}" for a, b in disjoint)
                        + " share no eligible judge; " + how)

    cands = []
    for lab in labels:
        used = list(data[lab]) if balanced else eligible[lab]
        means, disagree = collections.OrderedDict(), []
        for cid in weights:
            raw = [data[lab][j]["scores"][cid] for j in used if cid in data[lab][j]["scores"]]
            if raw:
                means[cid] = sum(data[lab][j]["scores"][cid] - mu[j][cid] + panel[cid] for j in used
                                 if cid in data[lab][j]["scores"]) / len(raw)
                if max(raw) - min(raw) >= 2:  # the judges' own 1-5 scores, as shown to them
                    disagree.append(cid)
        reasons = [data[lab][j]["reason"] for j in vetoes[lab] if data[lab][j]["reason"]]
        if len(vetoes[lab]) >= 2:
            veto = "excluded"
        elif len(vetoes[lab]) == 1:
            veto = "flagged"
            if len(eligible[lab]) == 1:
                reasons.append("single-judge veto: the human decides")
        else:
            veto = "none"

        def merged(key):
            seen, out = set(), []
            for j in eligible[lab]:
                for x in data[lab][j][key]:
                    if x and x.lower() not in seen:
                        seen.add(x.lower())
                        out.append(x)
            return out

        cands.append({"label": lab, "means": means, "judges": eligible[lab], "disagreements": disagree,
                      "veto": veto, "veto_reasons": reasons, "vetoes": len(vetoes[lab]), "sens": merged("sens"),
                      "trade": merged("trade")})

    rankable = [c for c in cands if c["veto"] != "excluded"]
    # W uses the criteria every ranked candidate has an eligible (other-family) judge's score for, so a missing weak
    # score never lifts one candidate, also not in the balanced design, where an own-family score would fill it
    shared = [cid for cid in weights
              if all(any(cid in data[c["label"]][j]["scores"] for j in eligible[c["label"]]) for c in rankable)]
    dropped = [cid for cid in weights if cid not in shared and any(cid in c["means"] for c in rankable)]
    if not shared:
        shared, dropped = list(weights), []
    if dropped:
        warnings.append("criteria without an eligible judge's score for every ranked candidate are left out of W: "
                        + ", ".join(dropped))
    by_label = {c["label"]: c for c in cands}

    def w_score(lab, w):
        return weighted(by_label[lab]["means"], collections.OrderedDict((c, w[c]) for c in shared)) or 0.0

    # Own-candidate gap: how much a judge's centered W for its own family's candidates exceeds the other families'
    # judges' centered W for them. The centering takes every candidate a judge scored, its own included, so a judge
    # that favours its own candidate also shifts its scores of the others down; when such a judge counts for only one
    # of the leader and the runner-up (or its own candidate is one of them, in the balanced design), the lead is not
    # 'clear'.
    shared_w = collections.OrderedDict((c, weights[c]) for c in shared)

    def judge_w(j, lab):
        return weighted(dict((c, v - mu[j][c] + panel[c]) for c, v in data[lab][j]["scores"].items()
                             if c in shared_w), shared_w)
    self_pref = []
    for j in judges:
        diffs = []
        for lab in labels:
            if base_family(j) != author[lab] or j not in data[lab]:
                continue
            mine = judge_w(j, lab)
            theirs = [x for x in (judge_w(g, lab) for g in data[lab] if base_family(g) != author[lab]) if x is not None]
            if mine is not None and theirs:
                diffs.append(mine - sum(theirs) / len(theirs))
        if diffs:
            gap = sum(diffs) / len(diffs)
            self_pref.append({"judge": j, "gap": round(gap, 2), "n": len(diffs), "flag": gap > GAP_FLAG})
    favouring = [s["judge"] for s in self_pref if s["flag"]]
    # Two families judging each other's candidates (the balanced design): a judge's gap above is diluted by the
    # centering (its own candidates are in its mean) and cannot be told from the other judge's leniency, but the pair's
    # combined self-preference can: the mean over a's family's candidates of (a's centered W - b's) minus the same mean
    # over b's family's candidates (their leniency difference cancels). Flagged, it can reorder the two families'
    # candidates, so a lead over the other family's candidates is not 'clear'.
    own_pairs = []
    for a, b in itertools.combinations(judges if balanced else [], 2):
        fa, fb = base_family(a), base_family(b)
        if fa == fb:
            continue
        diffs = {fa: [], fb: []}
        for lab in labels:
            if author[lab] in diffs and a in data[lab] and b in data[lab]:
                wa, wb = judge_w(a, lab), judge_w(b, lab)
                if wa is not None and wb is not None:
                    diffs[author[lab]].append(wa - wb)
        if diffs[fa] and diffs[fb]:
            s = sum(diffs[fa]) / len(diffs[fa]) - sum(diffs[fb]) / len(diffs[fb])
            own_pairs.append({"a": a, "b": b, "gap": round(s, 2), "n_a": len(diffs[fa]), "n_b": len(diffs[fb]),
                              "flag": s > GAP_FLAG})

    base, lo, hi = rank_ranges([c["label"] for c in rankable], w_score, weights)
    for c in cands:
        c["score"] = w_score(c["label"], weights)
        c["rank"] = base.get(c["label"])
        c["range"] = [lo[c["label"]], hi[c["label"]]] if c["label"] in base else None
    ordered = sorted(cands, key=lambda c: (c["rank"] is None, c["rank"] or 0, c["label"]))
    leader = next((c["label"] for c in ordered if c["rank"] == 1), None)
    runner = next((c for c in ordered if c["rank"] == 2), None)

    def tilts(j):
        """True when judge j's own-candidate bias moves the leader and the runner-up differently: it counts for only
        one of them, or its own family wrote one of them and it counts for it (the balanced design)."""
        if runner is None:
            return False
        pair = (leader, runner["label"])
        counted = [j in (list(data[lab]) if balanced else eligible[lab]) for lab in pair]
        own = base_family(j) in (author[pair[0]], author[pair[1]])
        return counted[0] != counted[1] or (own and any(counted))

    def pair_rival(p):
        """For a flagged pair self-preference whose families wrote the leader: the best-ranked candidate of the other
        family, which that self-preference may have put behind the leader (which judge adds how much is unknown)."""
        fams = (base_family(p["a"]), base_family(p["b"]))
        if not p["flag"] or author[leader] not in fams:
            return None
        other = fams[1] if author[leader] == fams[0] else fams[0]
        return next((c["label"] for c in ordered if c["rank"] and author[c["label"]] == other), None)
    close_why = []
    if leader is None:
        leader_status = "close-call"
        warnings.append("every candidate is EXCLUDED by vetoes: no leader; the human decides")
    elif leader in self_judged or (runner and runner["label"] in self_judged):
        leader_status = "self-judged"  # only its author family's judge scored the leader or the runner-up
    elif runner and not set(eligible[leader]) & set(eligible[runner["label"]]):
        leader_status = "confounded"  # the lead compares two judges' scales, not two judgments of one judge
    else:
        others_reach = [c["label"] for c in cands if c["label"] != leader and c["range"] and c["range"][0] == 1]
        if others_reach:
            close_why.append("%s can also rank 1" % ", ".join(others_reach))
        if runner is not None and abs(by_label[leader]["score"] - runner["score"]) < 1e-9:
            close_why.append("tied with %s" % runner["label"])
        if any(tilts(j) for j in favouring):  # the markdown stays blind to the authors' families: no judge named
            close_why.append("a judge that favours its own family's candidate (own-candidate gap above %g) counts "
                             "for one of the leader and the runner-up only" % GAP_FLAG)
        for p in own_pairs:
            rival = pair_rival(p)
            if rival:
                close_why.append("two families' judges favour their own family's candidates by %+.2f combined (which "
                                 "one adds how much cannot be told), which can put %s behind" % (p["gap"], rival))
        if dropped:
            close_why.append("criteria left out of W (no eligible judge's score for every ranked candidate): "
                             + ", ".join(dropped))
        leader_status = "clear" if base and lo[leader] == 1 and hi[leader] == 1 and not close_why else "close-call"

    steal, seen = [], {}
    for fam, st in steal_raw:
        frm = str(st.get("from", "")).strip()
        element = _one_line(st.get("element"), "")
        if frm not in data:
            warnings.append(f"judge {fam}: steal from unknown candidate '{frm}' ignored")
            continue
        if not element:
            continue
        key = (frm, element.lower())
        if key in seen:
            continue
        seen[key] = True
        steal.append({"from": frm, "element": element, "why": _one_line(st.get("why"), "")})
    steal.sort(key=lambda s: s["from"])  # stable: first-seen order within each candidate

    matrix = {
        "criteria": [{"id": cid, "weight": w} for cid, w in weights.items()],
        "candidates": [{"label": c["label"], "score": round(c["score"], 2), "rank": c["rank"], "range": c["range"],
                        "veto": c["veto"], "veto_reasons": c["veto_reasons"],
                        "means": {k: round(v, 2) for k, v in c["means"].items()}, "judges": c["judges"],
                        "disagreements": c["disagreements"]} for c in ordered],
        "leader": leader, "leader_status": leader_status, "steal": steal, "warnings": warnings,
        "design": {"confounded": bool(disjoint), "judges": "all (balanced own-family judges)" if balanced else
                   "eligible"},
        "judge_offsets": offsets, "self_judged": self_judged, "own_candidate_gap": self_pref,
        "own_candidate_pairs": own_pairs}
    textio.write_json_atomic(os.path.join(arch, "matrix.json"), matrix)

    names = {cid: name for cid, name, _w in criteria}
    md = ["# Architecture trade-off matrix", "",
          "Computed by bs.py arch-matrix. A criterion score is the mean of the eligible judges' 1-5 scores (a judge "
          "never scores a candidate written by its own family) after per-judge centering: each judge's mean per "
          "criterion is moved to the panel mean, so a lenient judge lifts nothing. When candidates share no "
          "eligible judge and each has one own-family judge, every judge's centered score counts. W = sum(weight x "
          "mean) / sum(weight) over the criteria every ranked candidate has an eligible judge's score for. Rank "
          "ranges move each weight by +/-25%, one at a time. Veto (any judge, an author family's veto of its own "
          "candidate included): 2 or more judges -> EXCLUDED; 1 judge -> FLAGGED.", "",
          "## Weights", "", "| id | criterion | weight |", "|---|---|---|"]
    for cid, w in weights.items():
        md.append(f"| {cid} | {names[cid]} | {w:g} |")
    md += ["", f"Quality goals: {qsum:g} of 70; fixed criteria: 30.", "", "## Scores", "",
           "| rank | candidate | W | rank range | veto | " + " | ".join(weights) + " | judges |",
           "|---|---|---|---|---|" + "---|" * len(weights) + "---|"]
    for c in ordered:
        rng_txt = f"{c['range'][0]}-{c['range'][1]}" if c["range"] else "-"
        cells = [f"{c['means'][cid]:.1f}" if cid in c["means"] else "-" for cid in weights]
        md.append(f"| {c['rank'] if c['rank'] is not None else '-'} | {c['label']} | {c['score']:.2f} | {rng_txt} | "
                  f"{c['veto'].upper()} | " + " | ".join(cells) + f" | {len(c['judges'])} |")
    md += ["", "## Vetoes", ""]
    vetoed = [c for c in ordered if c["veto"] != "none"]
    for c in vetoed:
        md.append(f"- {c['label']}: {c['veto'].upper()} ({c['vetoes']} judge{'s' if c['vetoes'] != 1 else ''}): "
                  + ("; ".join(c["veto_reasons"]) or "no reason given"))
    if not vetoed:
        md.append("- none")
    md += ["", "## Disagreements (the scoring judges' 1-5 scores span 2 or more points)", ""]
    dis = [c for c in ordered if c["disagreements"]]
    for c in dis:
        md.append(f"- {c['label']}: " + ", ".join(c["disagreements"]))
    if not dis:
        md.append("- none")
    for title, key in (("Sensitivity points", "sens"), ("Trade-off points", "trade")):
        md += ["", f"## {title}", ""]
        rows = [f"- {c['label']}: {x}" for c in ordered for x in c[key]]
        md += rows or ["- none"]
    md += ["", "## Steal list", ""]
    md += [f"- from {s['from']}: {s['element']}" + (f" ({s['why']})" if s["why"] else "") for s in steal] or ["- none"]
    # judges stay unnamed here: a judge's name next to "its own family's candidate" would reveal an author
    md += ["", "## Own-candidate gap (a judge's centered W for its own family's candidates minus the other families' "
               f"judges'; FLAG above {GAP_FLAG:g})", ""]
    md += [f"- a judge: {s['gap']:+.2f} over {s['n']} candidate{'s' if s['n'] != 1 else ''}"
           + ("  <- FLAG" if s["flag"] else "") for s in sorted(self_pref, key=lambda s: -s["gap"])] or [
        "- no judge scored its own family's candidate next to another family's judge"]
    md += [f"- two judges together: {p['gap']:+.2f} on their own families' candidates ({p['n_a']} and {p['n_b']}; "
           "each judge's share cannot be told apart from the other's leniency)" + ("  <- FLAG" if p["flag"] else "")
           for p in own_pairs]
    if warnings:
        md += ["", "## Warnings", ""] + [f"- {w}" for w in warnings]
    md += ["", "## Leader", ""]
    if leader is None:
        md.append("Leader: none (every candidate is EXCLUDED; the human decides)")
    elif leader_status == "clear":
        md.append(f"Leader: {leader} (clear: rank 1 under every weight change)")
    elif leader_status == "self-judged":
        md.append(f"Leader: {leader} (self-judged: "
                  + ("only its author family's judge scored it" if leader in self_judged else
                     "only the runner-up %s's author family's judge scored it" % runner["label"])
                  + "; the human decides)")
    elif leader_status == "confounded":
        md.append(f"Leader: {leader} (confounded: it and the runner-up share no eligible judge, so the lead compares "
                  f"two judges' scales; the human decides)")
    else:
        md.append(f"Leader: {leader} (close-call" + (": " + "; ".join(close_why) if close_why else "") + ")")
    write(os.path.join(arch, "tradeoff-matrix.md"), "\n".join(md) + "\n")
    print("\n".join(md))


# ---------------------------------------------------------------- lints

def lint_cmd(root, which, lite=False):
    if which == "arch":
        res = lints.lint_arch(root, lite=lite)
        where = "10_ARCHITECTURE/lint.md"
    elif which == "proposal":
        res = lints.lint_proposal(root, lite=lite)
        where = "11_PROPOSAL/lint.md"
    else:
        res = lints.lint_frame(root)
        where = "frame/lint.json"
    fails = sum(1 for i in res["items"] if i["severity"] == "fail")
    warns = sum(1 for i in res["items"] if i["severity"] == "warn")
    print(f"lint-{which}: {res['status'].upper()} ({fails} FAIL, {warns} WARN); wrote {where}")
    for i in res["items"]:
        print(f"  {i['severity'].upper()} {i['id']} {i['file']}: {i['message']}")
    if which == "frame":
        return 0
    return 1 if res["status"] == "fail" else 0


# ---------------------------------------------------------------- split / sources / assumptions

def _inside_run(root, rel, what):
    if not rel or os.path.isabs(rel) or re.match(r"^[A-Za-z]:", rel) or ".." in re.split(r"[\\/]", rel):
        die(f"{what} must be a relative path inside the run folder: {rel!r}", 2)
    return os.path.join(root, *re.split(r"[\\/]", rel))


def split(root, in_file, rel_root, allows, status_out=None):
    src = in_file if os.path.isabs(in_file) or os.path.exists(in_file) else os.path.join(root, in_file)
    if not os.path.exists(src):
        die(f"input missing: {in_file}", 4)
    out_root = _inside_run(root, rel_root, "--root")
    status_path = _inside_run(root, status_out, "--status-out") if status_out else None
    res = filesproto.split_output(textio.read_text(src), out_root, allows, status_out=status_path)
    for w in res["warnings"]:
        print("WARNING: " + str(w), file=sys.stderr)
    if not res["ok"]:
        die("split failed (nothing written): " + "; ".join(str(e) for e in res["errors"]), 5)
    rels = [os.path.relpath(p, root).replace("\\", "/") for p in res["written"]]
    print(f"split: wrote {len(rels)} file(s): " + ", ".join(rels)
          + (f"; status -> {status_out} ({res['status'].get('status')})" if status_path and res["status"] else ""))


def run_date(root):
    rj = run_json(root)
    if rj is not None and re.match(r"^\d{4}-\d{2}-\d{2}", str(rj.get("created_at", ""))):
        return str(rj["created_at"])[:10]
    m = re.match(r"^(\d{4}-\d{2}-\d{2})", os.path.basename(os.path.normpath(os.path.abspath(root))))
    if m:
        return m.group(1)
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")


def _clean_url(url):
    return url.rstrip(".,;:")


def _title_from_line(rest):
    """Title of the URLs of a line (or JSON string) from `rest`, that text with its URLs replaced by spaces. Every
    pattern is linear: a '[' ends each [text]() attempt, so a long run of '[' is not rescanned (#34)."""
    t = re.sub(r"\[([^\[\]]*)\]\(\s*\)", r"\1", rest)      # [text]() left after removing the url
    t = re.sub(r"<\s*>|\(\s*\)", " ", t)
    t = re.sub(r"^\s*(?:[-*+]|\d+[.)]|#+)\s*", "", t)
    t = " ".join(t.replace("|", " ").split()).strip(" -:;,")
    return t[:80]


_JSON_TITLE_KEYS = ("title", "component", "choice", "claim", "issue", "name", "element", "evidence", "text")


def _json_label(obj):
    """(title, accessed) that a JSON object gives the URLs of its strings: its first title key without a URL, and its
    accessed or date key."""
    title, accessed = "", None
    for k in _JSON_TITLE_KEYS:
        v = obj.get(k)
        if isinstance(v, str) and v.strip() and not URL_RE.search(v):
            title = " ".join(v.split())[:80]
            break
    for k in ("accessed", "date"):
        v = obj.get(k)
        if isinstance(v, str) and re.match(r"^\d{4}-\d{2}-\d{2}", v):
            accessed = v[:10]
            break
    return title, accessed


def _json_urls(obj, found, label=("", None)):
    """(url, title, accessed) for the URLs of every string in a JSON value. Each object is labeled once and each
    string read once, so the cost stays linear in the document (#34)."""
    if isinstance(obj, dict):
        label = _json_label(obj)
        for v in obj.values():
            _json_urls(v, found, label)
    elif isinstance(obj, list):
        for v in obj:
            _json_urls(v, found, label)
    elif isinstance(obj, str):
        urls = [_clean_url(u) for u in URL_RE.findall(obj)]
        if urls:
            title = label[0] or _title_from_line(URL_RE.sub(" ", obj))
            found.extend((url, title, label[1]) for url in urls)


# the adapter's records next to a model output (its meta with the backend's command line, a kept failure record, a
# STATUS file): never a source, which would put an endpoint URL or a failed call's text into the proposal
_NOT_OUTPUT = (".meta.json", ".failed.md", ".status.json")


def sources(root):
    rd = run_date(root)
    scan = [os.path.join(root, "02_CONTEXT.md")]
    scan += sorted(textio.glob_in(root, "checks", "*.md"))
    scan += [os.path.join(root, "10_ARCHITECTURE", "stack.json")]
    scan += sorted(textio.glob_in(root, "10_ARCHITECTURE", "review", "*.json"))
    scan += sorted(textio.glob_in(root, "redteam", "*.md"))
    scan = [p for p in scan if not p.endswith(_NOT_OUTPUT)]
    found = []  # (url, title, accessed, rel)
    for path in scan:
        if not os.path.isfile(path):
            continue
        rel = os.path.relpath(path, root).replace("\\", "/")
        text = read_text(path)
        if path.endswith(".json"):
            try:
                obj = load_model(path)
            except ValueError:
                obj = None
            if obj is not None:
                hits = []
                _json_urls(obj, hits)
                found += [(u, t, a, rel) for u, t, a in hits]
                continue
        for line in text.splitlines():
            urls = [_clean_url(u) for u in URL_RE.findall(line)]
            if not urls:
                continue
            # one title and one date per line, from the line without its URLs: linear however many URLs it holds
            rest = URL_RE.sub(" ", line)
            date = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", rest)
            title = _title_from_line(rest)
            found.extend((url, title, date.group(1) if date else None, rel) for url in urls)
    json_path = os.path.join(root, "sources.json")
    existing = collections.OrderedDict()
    nxt = 1  # above every id sources.json ever held, so a dropped id is never reused for another URL
    if os.path.exists(json_path):
        try:
            old = load(json_path)
        except ValueError as exc:
            die(f"sources.json is not valid JSON: {exc}", 5)
        if isinstance(old, dict):
            for sid in sorted(old, key=lambda s: (int(re.sub(r"\D", "", s) or 0), s)):
                if not re.match(r"^S-\d{3,}$", sid):
                    continue
                nxt = max(nxt, int(sid[2:]) + 1)
                if isinstance(old[sid], dict) and old[sid].get("url"):
                    entry = dict(old[sid])
                    cited = entry.get("used_in") if isinstance(entry.get("used_in"), list) else []
                    kept = [u for u in cited if not str(u).endswith(_NOT_OUTPUT)]
                    if cited and not kept:
                        continue  # only an adapter record cited it (an older kit scanned them)
                    entry["used_in"] = kept
                    existing[sid] = entry
    by_url = {v["url"]: sid for sid, v in existing.items()}
    used = collections.defaultdict(list)
    info = {}
    for url, title, accessed, rel in found:
        if url not in by_url:
            sid = f"S-{nxt:03d}"
            nxt += 1
            by_url[url] = sid
            existing[sid] = {"url": url, "title": title or url, "accessed": accessed or rd, "used_in": []}
        sid = by_url[url]
        if rel not in used[sid]:
            used[sid].append(rel)
        info.setdefault(sid, (title, accessed))
    for sid, entry in existing.items():
        if used.get(sid):
            entry["used_in"] = used[sid]
        entry.setdefault("used_in", [])
        if not entry.get("title"):
            entry["title"] = (info.get(sid, ("", None))[0]) or entry["url"]
        if not entry.get("accessed"):
            entry["accessed"] = (info.get(sid, ("", None))[1]) or rd
    out = collections.OrderedDict((sid, {"url": e["url"], "title": e["title"], "accessed": e["accessed"],
                                         "used_in": e["used_in"]}) for sid, e in existing.items())
    textio.write_json_atomic(json_path, out)
    md = ["# Sources", "", "Stable ids (bs.py sources): cite them as [S-###].", "",
          "| id | title | url | accessed | used in |", "|---|---|---|---|---|"]
    for sid, e in out.items():
        md.append(f"| {sid} | {_one_line(e['title'], '-')} | {e['url']} | {e['accessed']} | "
                  f"{', '.join(e['used_in']) or '-'} |")
    if not out:
        md.append("| - | no sources found | - | - | - |")
    write(os.path.join(root, "sources.md"), "\n".join(md) + "\n")
    print(f"sources: {len(out)} source(s) in sources.json ({len(found)} URL occurrence(s) scanned); wrote sources.md")


def _assumption_files(root):
    files = []
    arch = os.path.join(root, "10_ARCHITECTURE")
    for p in sorted(textio.glob_in(arch, "**", "*.md", recursive=True)):
        rel = os.path.relpath(p, arch).replace("\\", "/")
        if rel.split("/")[0] in ("_raw", "candidates", "review") or rel == "lint.md":
            continue  # raw and rejected-candidate text is not part of the chosen package
        files.append(p)
    files += sorted(textio.glob_in(root, "11_PROPOSAL", "sections", "*.md"))
    return files


_Q_BULLET_RE = re.compile(r"(?:[-*+]|\d+[.)])(?=\s)")
_Q_KEY_RE = re.compile(r"\b(owner|decide[ _-]*by)\s*:", re.I)
_Q_ENDS = " .,;|-*\u2013\u2014"  # what a question and a value drop at their ends (en and em dash included)


def _q_fields(body):
    """[(start, end, key, value)] for the Owner: / Decide by: fields of one question. A field takes the separators
    (whitespace and "([;,.-|") before its key; its value runs to the next key or the end of the line, or before that
    to the first ";", "|", ")" or "]" outside a bracket the value opened itself, without the whitespace around it. The
    stop after the value belongs to the field when it is a ";" or "|", or a ")" or "]" that closes a bracket a field
    took, so "Q? (Owner: X; Decide by: Y)", "Q? [Owner: X]" and "Q? | Owner: X |" leave "Q?", "Owner: Alice (CTO);
    Decide by: M1 (before pilot)" keeps both values whole and "Keep (b)? Owner: X" keeps its "(b)". Linear in the line
    (finding 34): the keys are found once and every character is walked at most once (a regex took 20-35 s on one
    line with a 40,000-space run)."""
    keys = list(_Q_KEY_RE.finditer(body))
    out, prev, opened = [], 0, 0
    for n, k in enumerate(keys):
        start = k.start()
        while start > prev and (body[start - 1].isspace() or body[start - 1] in "([;,.-|"):
            start -= 1
            opened += body[start] in "(["
        limit = keys[n + 1].start() if n + 1 < len(keys) else len(body)
        v = k.end()
        while v < limit and body[v].isspace():
            v += 1
        end, depth = v, 0
        while end < limit and (depth or body[end] not in ";|)]"):
            depth += (body[end] in "([") - (body[end] in ")]")
            end += 1
        value = body[v:end].rstrip()
        if end < limit and (body[end] in ";|" or opened):  # a ")" or "]" here closes a bracket a field took
            opened -= body[end] in ")]"
            end += 1
        out.append((start, end, k.group(1), value))
        prev = end
    return out


def _section13_questions(text):
    """[(question, owner, decide_by)] from the bullet (or numbered) lines of proposal section 13."""
    out = []
    for line in (text or "").split("\n"):
        line = line.lstrip()
        m = _Q_BULLET_RE.match(line)
        body = line[m.end():].strip() if m else ""
        if not body:
            continue
        body = body.replace("**", "")
        owner = by = None
        parts, pos = [], 0
        for start, end, key, value in _q_fields(body):
            if key.lower().startswith("owner"):
                owner = value.strip(_Q_ENDS) or None
            else:
                by = value.strip(_Q_ENDS) or None
            parts.append(body[pos:start])
            pos = end
        q = " ".join(("".join(parts) + body[pos:]).split()).strip(_Q_ENDS)
        if q:
            out.append((q, owner, by))
    return out


def assumptions(root):
    rows = collections.OrderedDict()  # norm text -> [text, [where]]
    for path in _assumption_files(root):
        rel = os.path.relpath(path, root).replace("\\", "/")
        for _kind, text, _n in lints.extract_assumptions(read_text(path)):
            key = lints.norm_assumption(text)
            if not key:
                continue
            row = rows.setdefault(key, [text, []])
            if rel not in row[1]:
                row[1].append(rel)
    questions = collections.OrderedDict()  # norm q -> [q, source, owner, decide_by]
    status_files = sorted(set(textio.glob_in(root, "10_ARCHITECTURE", "**", "*.status.json", recursive=True)
                              + textio.glob_in(root, "11_PROPOSAL", "**", "*.status.json", recursive=True)))
    for path in status_files:
        rel = os.path.relpath(path, root).replace("\\", "/")
        try:
            st = load_model(path)
        except ValueError:
            print(f"WARNING: unreadable {rel}: skipped", file=sys.stderr)
            continue
        if not isinstance(st, dict):
            continue
        for a in st.get("assumptions") or []:
            text = a.get("text") if isinstance(a, dict) else a
            key = lints.norm_assumption(text or "")
            if key:
                row = rows.setdefault(key, [" ".join(str(text).split()), []])
                if rel not in row[1]:
                    row[1].append(rel)
        for q in st.get("open_questions") or []:
            if isinstance(q, dict):
                text = q.get("q") or q.get("question") or q.get("text") or ""
                owner, by = q.get("owner"), q.get("decide_by") or q.get("decide by")
            else:
                text, owner, by = q, None, None
            key = lints.norm_assumption(text or "")
            if key and key not in questions:
                questions[key] = [" ".join(str(text).split()), rel, owner, by]
    # section 13 (Open Questions) of the proposal: one bullet per question, with optional Owner: / Decide by:
    s13 = os.path.join(root, "11_PROPOSAL", "sections", "13.md")
    if os.path.isfile(s13):
        for text, owner, by in _section13_questions(read_text(s13)):
            key = lints.norm_assumption(text)
            if key and key not in questions:
                questions[key] = [text, "sections/13.md", owner, by]
    out_dir = os.path.join(root, "11_PROPOSAL")
    md = ["# Assumptions", "", "Collected by bs.py assumptions from the architecture package, the proposal sections "
          "and the STATUS trailers. Each needs a test or an owner.", "",
          "| id | assumption | where |", "|---|---|---|"]
    for n, (text, where) in enumerate(rows.values(), 1):
        md.append(f"| A-{n:03d} | {_one_line(text)} | {', '.join(where)} |")
    write(os.path.join(out_dir, "assumptions.md"), "\n".join(md) + "\n")
    oq = ["# Open questions", "", "| id | question | source | owner | decide by |", "|---|---|---|---|---|"]
    for n, (text, src, owner, by) in enumerate(questions.values(), 1):
        oq.append(f"| Q-{n:03d} | {_one_line(text)} | {src} | {_one_line(owner, 'to assign')} | "
                  f"{_one_line(by, 'to assign')} |")
    if not questions:
        oq.append("| - | none recorded | - | - | - |")
    write(os.path.join(out_dir, "open-questions.md"), "\n".join(oq) + "\n")
    print(f"assumptions: {len(rows)} assumption(s), {len(questions)} open question(s); wrote "
          f"11_PROPOSAL/assumptions.md, 11_PROPOSAL/open-questions.md")


# ---------------------------------------------------------------- CLI

class _Parser(argparse.ArgumentParser):
    def error(self, message):
        self.print_usage(sys.stderr)
        print(f"bs.py: error: {message}", file=sys.stderr)
        sys.exit(2)


def build_parser():
    p = _Parser(prog="bs.py", description="Deterministic bookkeeping for ultimate-brainstorm runs.",
                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--version", action="version", version=VERSION)
    sub = p.add_subparsers(dest="cmd", parser_class=_Parser)
    for name in ("init", "status", "schemas", "map", "prepare-screen", "screen", "tournament", "arch-matrix",
                 "lint-frame", "sources", "assumptions"):
        sp = sub.add_parser(name)
        sp.add_argument("run")
    sp = sub.add_parser("quick-pick")
    sp.add_argument("run")
    sp.add_argument("--scores", choices=QUICK_SCORES, default="auto")
    sp = sub.add_parser("prepare-tournament")
    sp.add_argument("run")
    sp.add_argument("--per-pair", action="store_true")
    for name in ("lint-arch", "lint-proposal"):
        sp = sub.add_parser(name)
        sp.add_argument("run")
        sp.add_argument("--lite", action="store_true")
    sp = sub.add_parser("split")
    sp.add_argument("run")
    sp.add_argument("--in", dest="in_file", required=True)
    sp.add_argument("--root", dest="rel_root", required=True)
    sp.add_argument("--allow", action="append", required=True)
    sp.add_argument("--status-out", default=None)
    return p


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = build_parser()
    if not argv:
        parser.print_help(sys.stderr)
        return 2
    args = parser.parse_args(argv)
    if not args.cmd:
        parser.print_help(sys.stderr)
        return 2
    root = args.run
    try:
        if args.cmd != "init" and not os.path.isdir(root):
            die(f"run folder not found: {root}", 4)
        simple = {"init": init, "status": status, "schemas": schemas, "map": map_pool,
                  "prepare-screen": prepare_screen, "screen": screen, "tournament": tournament,
                  "arch-matrix": arch_matrix, "sources": sources, "assumptions": assumptions}
        if args.cmd in simple:
            simple[args.cmd](root)
        elif args.cmd == "quick-pick":
            quick_pick(root, scores=args.scores)
        elif args.cmd == "prepare-tournament":
            prepare_tournament(root, per_pair=args.per_pair)
        elif args.cmd == "lint-arch":
            return lint_cmd(root, "arch", args.lite)
        elif args.cmd == "lint-proposal":
            return lint_cmd(root, "proposal", args.lite)
        elif args.cmd == "lint-frame":
            return lint_cmd(root, "frame")
        elif args.cmd == "split":
            split(root, args.in_file, args.rel_root, args.allow, args.status_out)
        return 0
    except BsError as exc:
        print(exc.message, file=sys.stderr)
        return exc.code
    except FileNotFoundError as exc:
        print(f"missing input: {exc.filename or exc}", file=sys.stderr)
        return 4
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        print(f"invalid input: {exc.__class__.__name__}: {exc}", file=sys.stderr)
        return 5


if __name__ == "__main__":
    sys.exit(main())
