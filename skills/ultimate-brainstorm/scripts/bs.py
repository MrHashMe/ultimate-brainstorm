#!/usr/bin/env python3
"""bs.py - deterministic bookkeeping for the ultimate-brainstorm pipeline (kit v2).

Python 3.9+ standard library only. RUN is a run folder such as brainstorm/2026-09-23-habit-coach.
A run without run.json (schema 2) is a v1 run: every legacy command then behaves exactly as v1 bs.py
(two judge families, claude and gpt; byte-identical outputs). With run.json the judge families come from
run.json seats (N families).

  --version                       print the kit version
  init RUN                        create the run's sub-folders, brainstorm/LEDGER.md and an empty
                                  00_HUMAN_SEEDS.md template (each only if missing)
  status RUN                      list stage outputs present/missing and name the next stage
                                  (v2 runs: + stages 12 Architecture, 13 Proposal, 14 Handoff)
  schemas RUN                     write screen/screen.schema.json, tournament/verdicts.schema.json and
                                  prompts/lens.schema.json (criteria names come from RUN/criteria.json)
  map RUN                         merges.json (from the CURATOR) -> random I-### IDs, clusters.json,
                                  origins.json, primary.json, screen/ideas.md, 03_POOL.md and coverage.json
                                  (pool/_families.json, when present, is the authoritative prefix -> family map)
  prepare-screen RUN              screen/ideas.md + screen/header.md -> screen/<family>.prompt.md per judge
  screen RUN                      screen/*.out.json -> screen/table.md + screen/shortlist.json
                                  (v2 runs: + Judge agreement and Own-origin gap)
  prepare-tournament RUN [--per-pair]
                                  tournament/cards.md + tournament/header.md -> judge prompts + .map.json files
  tournament RUN                  tournament/*.out.json -> tournament/result.md + tournament/result.json
  dupcheck RUN [--threshold T]    flag near-duplicate ideas in screen/ideas.md (sentence-transformers
                                  embeddings if installed, otherwise word overlap)
  quick-pick RUN                  quick/curated.json -> quick/finalists.json, tournament/cards.md, origins.json
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
import glob
import hashlib
import itertools
import json
import os
import random
import re
import string
import sys
import tempfile
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from ublib import filesproto, lints, textio  # noqa: E402

VERSION = "2.0.3"
FAMILIES = ("claude", "gpt")  # v1 judge families (runs without run.json)
VENDORS = {"claude": "anthropic", "gpt": "openai", "kimi": "moonshot", "glm": "zhipu"}
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
    (12, "Handoff", ["10_HANDOFF.md"]),
]
QUICK_STAGES = [
    (1, "Quick: seeds and criteria", ["@seeds", "criteria.json"]),
    (2, "Quick: generate", ["pool/*"]),
    (3, "Quick: cards", ["tournament/cards.md"]),
    (4, "Quick: other-family check", ["tournament/result.md"]),
    (5, "Quick: decision", ["QUICK_DECISION.md"]),
]
# v2 (run.json schema 2): proposal mode skips diverge/map/screen; every mode ends with stages 12-14.
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
ID_RE = r"\b(?:I|E)-\d+\b"
STOP = set("the and for with that this from into your their them they are was were will would can could "
           "should have has had not but you our its via per use uses using make makes made each every "
           "what when where which who how why idea ideas user users".split())
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


def read_text(path):
    """Read UTF-8 (with or without BOM) or UTF-16 text (Windows PowerShell 5.1 '>' writes UTF-16)."""
    with open(path, "rb") as f:
        raw = f.read()
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return raw.decode("utf-16")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:  # v2: stray bytes (v1 raised here)
        return textio.decode_bytes(raw, normalize=False)
    if "\x00" in text:  # v2: BOM-less UTF-16 (v1 returned text with NULs that no parser accepts)
        return textio.decode_bytes(raw, normalize=False)
    return text


def load(path):
    """Parse JSON, tolerating ```json fences or a sentence of preamble around the object."""
    text = read_text(path)
    try:
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            start, end = text.find("{"), text.rfind("}")
            if start < 0 or end < start:
                raise
            return json.loads(text[start:end + 1])
    except json.JSONDecodeError as v1_error:
        try:  # v2: any fenced or embedded object/array
            return textio.extract_json(text)
        except ValueError:
            raise v1_error  # the v1 message (it appears in result.md warnings)


def write(path, text):
    """Write UTF-8 text with LF newlines as given (same bytes as v1), atomically (temp file + os.replace)."""
    path = os.path.abspath(path)
    folder = os.path.dirname(path)
    os.makedirs(folder, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix="." + os.path.basename(path) + ".", suffix=".tmp", dir=folder)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        for attempt in range(10):
            try:
                os.replace(tmp, path)
                break
            except PermissionError:  # Windows: a reader holds the target open
                if attempt == 9:
                    raise
                time.sleep(0.05 * (attempt + 1))
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


def opt_json(path):
    return load(path) if os.path.exists(path) else {}


def need_json(path, what=None):
    """Load a required JSON input: exit 4 when missing, 5 when unreadable."""
    if not os.path.exists(path):
        die("%s missing: %s" % (what or os.path.basename(path), path), 4)
    try:
        return load(path)
    except ValueError as exc:
        die("%s is not valid JSON: %s" % (path, exc), 5)


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


# ---------------------------------------------------------------- run.json (v2) and families

def run_json(root):
    """The run.json dict when it exists with schema 2, else None (a v1 run)."""
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


def base_family(label):
    label = str(label or "")
    return label[:-4] if label.endswith("-alt") else label


def vendor(label):
    """claude = anthropic, gpt = openai, kimi = moonshot, glm = zhipu; X-alt has the vendor of X; any other label is
    its own vendor. Origins human, human-mixed, ai-mixed and unknown belong to nobody (None)."""
    label = str(label or "").strip()
    if label in NOBODY:
        return None
    base = base_family(label)
    return VENDORS.get(base, base)


def judge_families(root, seat_key):
    """Judge family labels from run.json seats (v2) or the v1 pair."""
    rj = run_json(root)
    if rj is None:
        return list(FAMILIES)
    fams = (rj.get("seats") or {}).get(seat_key)
    out = []
    for f in fams if isinstance(fams, list) else []:
        f = str(f).strip()
        if f and f not in out:
            out.append(f)
    return out or list(FAMILIES)


def _stage_match(stage, which):
    s = str(stage or "").strip().lower()
    if which == "screen":
        return "screen" in s or s.startswith("6.")
    return "tournament" in s or s.startswith("9.") or s.startswith("q.5") or s == "quick"


def judge_info(root, labels, which):
    """{label: {"provisional": bool, "vendor": str|None, "actual": str}} for judge labels.

    PROVISIONAL: the label ends in -alt, or run.json.provisional has an entry for this stage whose seat or actual
    equals the label. The vendor comes from the actual family when one is recorded. v1 runs: 00_RUN.md other
    family = none / PROVISIONAL marks the non-host label as a same-vendor substitute.
    """
    rj = run_json(root)
    info = {}
    subs = {}
    if rj is not None:
        for p in rj.get("provisional") or []:
            if isinstance(p, dict) and _stage_match(p.get("stage"), which):
                seat, actual = str(p.get("seat", "")).strip(), str(p.get("actual", "")).strip()
                if seat:
                    subs[seat] = actual or seat + "-alt"
                if actual:
                    subs.setdefault(actual, actual)
    for lab in labels:
        actual = subs.get(lab, lab)
        prov = lab.endswith("-alt") or lab in subs
        info[lab] = {"provisional": prov, "vendor": vendor(actual), "actual": actual}
    if rj is None and other_family_provisional(root):
        m = re.search(r"host family\s*:\s*([A-Za-z]+)", run_text(root), re.I)
        host = m.group(1).lower() if m else None
        for lab in labels:
            if host in FAMILIES and lab == host:
                continue
            info[lab]["provisional"] = True
            if host in FAMILIES:
                info[lab]["vendor"] = vendor(host)
                info[lab]["actual"] = host + "-alt"
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


def mode_of(root):
    rj = run_json(root)
    if rj is not None and str(rj.get("mode", "")).lower() in ("quick", "standard", "deep", "proposal"):
        return str(rj["mode"]).lower()
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


def check_item(root, item, v2=False):
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
        if ok and v2 and re.search(r"^\W*RESULT\s*:\s*PENDING\b", read_text(path), re.M | re.I):
            return True, "designed; RESULT: PENDING"
        return bool(ok), "" if ok else "no 'RESULT:' line yet (probe designed but not reported)"
    return bool(glob.glob(os.path.join(root, item))), ""


def status(root):
    v2 = run_json(root) is not None
    mode = mode_of(root)
    if not v2:
        stages = QUICK_STAGES if mode == "quick" else FULL_STAGES
    elif mode == "quick":
        stages = QUICK_STAGES + V2_TAIL_STAGES
    elif mode == "proposal":
        stages = PROPOSAL_STAGES + V2_TAIL_STAGES
    else:
        stages = FULL_STAGES[:-1] + V2_TAIL_STAGES
    nxt = None
    print(f"run: {root}   mode: {mode}")
    for num, name, items in stages:
        results = [check_item(root, i, v2) for i in items]
        done = all(r[0] for r in results)
        notes = "; ".join(r[1] for r in results if r[1] and (not r[0] or v2))
        print(f"  [{'x' if done else ' '}] stage {num:>2} {name}: {', '.join(items)}" + (f"  ({notes})" if notes else ""))
        if not done and nxt is None:
            nxt = (num, name)
    print(f"next: stage {nxt[0]} ({nxt[1]})" if nxt else "all stages complete")


# ---------------------------------------------------------------- map (after the CURATOR)

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

    def prefix(alias):
        m = re.match(r"^(.*?)-\d+$", str(alias).strip())
        return m.group(1) if m else str(alias).strip()

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
    empty, single = [], []
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
    # v2 (additive file): coverage.json for the engine's gap-round predicate (4.10)
    textio.write_json_atomic(os.path.join(root, "coverage.json"), {
        "axes": {k: list(v) for k, v in axes.items()},
        "empty": [list(c) for c in empty],
        "single": [list(c) for c in single],
        "homogenized": bool(homog),
        "largest_cluster": {"name": str(big_name), "share": round(big / n, 2)},
        "clusters": len(sizes),
        "ideas": n})
    print(f"mapped {n} canonical ideas ({sum(raw.values())} raw); HOMOGENIZED: {'yes' if homog else 'no'}; "
          f"wrote 03_POOL.md, clusters.json, origins.json, primary.json, screen/ideas.md")
    for w in sorted(set(warnings)):
        print("WARNING: " + w)


# ---------------------------------------------------------------- schemas

def schemas(root):
    crit = list(need_json(os.path.join(root, "criteria.json")))
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
    fams = judge_families(root, "screen_judges")
    for fam in fams:
        rows = ideas[:]
        rng(root, "screen-" + fam).shuffle(rows)  # each judge family sees a different order
        write(os.path.join(d, fam + ".prompt.md"), header + "\n\nIDEAS\n" + "\n".join(rows) + "\n")
    if run_json(root) is None:
        print(f"wrote screen/claude.prompt.md and screen/gpt.prompt.md ({len(ideas)} ideas, different orders)")
    else:
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


def judge_weighted(record, weights):
    """One judge's weighted score for one idea (criteria it left out are skipped). None when it scored nothing."""
    vals = {c: as_float((record.get("c") or {}).get(c)) for c in weights}
    used = [c for c in weights if vals[c] is not None]
    if not used:
        return None
    return sum(weights[c] * vals[c] for c in used) / float(sum(weights[c] for c in used))


def screen_v2_sections(root, weights, per_judge, origins):
    """## Judge agreement and ## Own-origin gap (5.7). Returns (lines, summary dict for shortlist.json)."""
    labels = sorted(per_judge)
    info = judge_info(root, labels, "screen")
    ws = {j: {i: judge_weighted(r, weights) for i, r in per_judge[j].items()} for j in labels}
    ws = {j: {i: v for i, v in d.items() if v is not None} for j, d in ws.items()}

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
              "Report only; it does not change the shortlist. Gap = the mean weighted score a judge gave ideas from "
              "its own vendor minus the mean the other judges gave the same ideas. Flag when the gap exceeds 0.5."]
    gaps = []
    eligible = [j for j in labels if not info[j]["provisional"]]
    for j in labels:
        if info[j]["provisional"]:
            lines.append(f"- {tag(j)}: excluded (provisional seat)")
            continue
        v = info[j]["vendor"]
        own = [i for i in sorted(ws[j]) if vendor(origins.get(i)) == v and v is not None]
        own = [i for i in own if any(i in ws[g] for g in eligible if g != j)]
        if len(own) < 3:
            lines.append(f"- {j}: {len(own)} own-vendor idea(s) scored by other judges: not computed (needs 3)")
            continue
        mine = sum(ws[j][i] for i in own) / len(own)
        others = []
        for i in own:
            vals = [ws[g][i] for g in eligible if g != j and i in ws[g]]
            others.append(sum(vals) / len(vals))
        theirs = sum(others) / len(others)
        gap = mine - theirs
        flag = gap > 0.5
        gaps.append({"judge": j, "gap": round(gap, 3), "n": len(own), "flag": flag})
        lines.append(f"- {j}: {gap:+.2f} over {len(own)} own-vendor ideas (own {mine:.2f} vs others {theirs:.2f})"
                     + ("  <- FLAG: gap above 0.5" if flag else ""))
    summary = {"judges": [{"label": j, "provisional": info[j]["provisional"]} for j in labels],
               "agreement": {"pairs": pairs, "warn": warn}, "own_origin_gap": gaps}
    return lines, summary


def screen(root):
    weights = {k: float(v) for k, v in need_json(os.path.join(root, "criteria.json")).items()}
    clusters = opt_json(os.path.join(root, "clusters.json"))
    origins = opt_json(os.path.join(root, "origins.json"))
    judged = collections.defaultdict(list)
    per_judge = collections.OrderedDict()
    files = sorted(glob.glob(os.path.join(root, "screen", "*.out.json")))
    for path in files:
        label = os.path.basename(path)[: -len(".out.json")]
        rec = per_judge.setdefault(label, {})
        for s in load(path).get("scores", []):
            judged[str(s.get("id", "")).strip()].append(s)
            if str(s.get("id", "")).strip():
                rec[str(s.get("id", "")).strip()] = s
    judged.pop("", None)
    if not judged:
        die("no scores found in screen/*.out.json", 4 if not files else 5)

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
    shortlist = {
        "shortlist": [{"id": k, "reason": r, "score": round(info[k]["w"], 3)} for k, r in pick.items()],
        "killed_gate": [k for k in ids if info[k]["kill"]],
        "floor_fail": [k for k in ids if info[k]["floor"] and not info[k]["kill"]],
        "flagged_gate": [k for k in ids if info[k]["flag"] and not info[k]["kill"]],
        "borderline": borderline}
    if run_json(root) is not None:  # v2 sections (v1 runs keep the v1 table byte for byte)
        extra, summary = screen_v2_sections(root, weights, per_judge, origins)
        lines.extend(extra)
        shortlist.update(summary)
    table = "\n".join(lines) + "\n"
    write(os.path.join(root, "screen", "table.md"), table)
    write(os.path.join(root, "screen", "shortlist.json"), json.dumps(shortlist, indent=1))
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
        die("tournament/*.out.json already exist; move them to another folder before re-preparing", 5)
    for stale in glob.glob(os.path.join(d, "*.prompt.md")) + glob.glob(os.path.join(d, "*.map.json")):
        os.remove(stale)
    cards = parse_cards(os.path.join(d, "cards.md"))
    ids = list(cards)
    if not 2 <= len(ids) <= 26:
        die(f"need 2-26 cards (headings '## <ID>') in tournament/cards.md, found {len(ids)}", 5)
    header = read_text(os.path.join(d, "header.md")).rstrip()
    families = judge_families(root, "tournament_judges")
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
        for fam in families:
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
          f"families {', '.join(families)}, both orders")


def collect_votes(d):
    """{(family, sorted pair): [winner or None per judged order]} from tournament/*.map.json + *.out.json."""
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
    return votes, warnings


def tally(votes):
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
    return pts, consistent, total


def tournament_v1_text(root, pts, consistent, total, origins, warnings):
    """The v1 result.md, byte for byte (runs without run.json)."""
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
    return "\n".join(out) + "\n"


def analyze_tournament(pts, consistent, total, origins, info, order):
    """N-family analysis (5.7): raw and debiased standings, contested pairs, consistency, audits."""
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
    consistency = {f: (consistent[f] / total[f] if total[f] else None) for f in fams}
    pos_flag = [f for f in fams if consistency[f] is not None and consistency[f] < 0.6]

    contested = []
    for pair in pairs:
        decisive = [max(pts[(f, pair)], key=pts[(f, pair)].get) for f in fams
                    if (f, pair) in pts and max(pts[(f, pair)].values()) == 1.0]
        if not decisive:
            contested.append([pair[0], pair[1], "no order-consistent verdict"])
            continue
        modal = collections.Counter(decisive).most_common(1)[0][1]
        if modal * 3 < 2 * len(decisive):  # the modal winner holds less than 2/3 of the order-consistent families
            contested.append([pair[0], pair[1], "families disagree"])

    def card_vendor(k):
        return vendor(origins.get(k))

    kept = {}
    for (f, pair), s in pts.items():
        if f in pos_flag:
            continue
        vf = info.get(f, {}).get("vendor")
        own = [k for k in pair if vf is not None and card_vendor(k) == vf]
        if len(own) == 1:  # exactly one card is this judge's own vendor: drop the entry
            continue
        kept[(f, pair)] = s
    debiased = []
    for k in cards:
        entries = [s for (f, p), s in kept.items() if k in p]
        if entries:
            debiased.append({"id": k, "pct": round(100.0 * sum(s[k] for s in entries) / len(entries), 1),
                             "n": len(entries)})
        else:
            debiased.append({"id": k, "pct": None, "n": 0})
    debiased.sort(key=lambda d: (d["pct"] is None, -(d["pct"] or 0.0), d["id"]))

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
            if (f, p) in pts:
                mine.append(pts[(f, p)][own])
            for g in auditable:
                if g != f and (g, p) in pts:
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
    excl = raw_scores(set(clean_fams)) if flagged else None
    result = {
        "families": fams,
        "raw": [{"id": k, "points": round(raw[k], 2), "max": len(fams) * (n - 1)}
                for k in sorted(cards, key=lambda c: (-raw[c], c))],
        "debiased": debiased,
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


def tournament_v2_text(res, pts, consistent, total, origins, info, warnings):
    fams = res["families"]
    n_cards = len(res["raw"])

    def tag(f):
        return f + (" (PROVISIONAL)" if info.get(f, {}).get("provisional") else "")

    out = [f"## Standings (max = {len(fams)} families x {n_cards - 1} opponents = {len(fams) * (n_cards - 1)} points)"]
    for rank, r in enumerate(res["raw"], 1):
        out.append(f"{rank}. {r['id']}  {r['points']:.1f}  (origin: {origins.get(r['id'], '?')})")
    out += ["", "## Debiased standings (default for recommendations)",
            "Dropped: a judge family's verdict on a pair where exactly one card comes from its own vendor, and every "
            "family flagged for position consistency. % = points / possible verdicts left for the card."]
    for rank, d in enumerate(res["debiased"], 1):
        pct = "n/a" if d["pct"] is None else f"{d['pct']:.1f}%"
        out.append(f"{rank}. {d['id']}  {pct}  (n={d['n']}; origin: {origins.get(d['id'], '?')})")
    out += ["", "## Contested pairs (the human decides these)"]
    for a, b, why in res["contested"]:
        out.append(f"- {a} vs {b}: " + ("judge families disagree" if why == "families disagree" else why))
    if not res["contested"]:
        out.append("- none")
    out += ["", "## Judge position consistency (same winner in both orders)"]
    for f in fams:
        if total[f]:
            share = consistent[f] / total[f]
            flag = "  <- below 60%: discount this family's verdicts" if share < 0.6 else ""
            out.append(f"- {tag(f)}: {consistent[f]}/{total[f]} = {share:.0%}{flag}")
        else:
            out.append(f"- {tag(f)}: only one order judged; all its verdicts were split 0.5/0.5")
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
    d = os.path.join(root, "tournament")
    origins = opt_json(os.path.join(root, "origins.json"))
    votes, warnings = collect_votes(d)
    if not votes:
        has_out = bool(glob.glob(os.path.join(d, "*.out.json")))
        die("no verdicts found in tournament/*.out.json", 5 if has_out else 4)
    pts, consistent, total = tally(votes)
    labels = sorted({f for f, _ in pts})
    rj = run_json(root)
    info = judge_info(root, labels, "tournament")
    order = judge_families(root, "tournament_judges") if rj is not None else sorted(labels)
    res = analyze_tournament(pts, consistent, total, origins, info, order)
    if rj is None:
        text = tournament_v1_text(root, pts, consistent, total, origins, warnings)
    else:
        text = tournament_v2_text(res, pts, consistent, total, origins, info, warnings)
    write(os.path.join(d, "result.md"), text)
    if warnings:
        res["warnings"] = warnings
    textio.write_json_atomic(os.path.join(d, "result.json"), res)  # additive in v1 runs
    print(text)


# ---------------------------------------------------------------- dupcheck

def dupcheck(root, threshold=None):
    rows = []
    for line in read_text(os.path.join(root, "screen", "ideas.md")).splitlines():
        parts = [p.strip() for p in line.split("|")]
        if len(parts) >= 3 and re.match(r"^I-\d+", parts[0]):
            rows.append((parts[0], " ".join(parts[1:])))
    if len(rows) < 2:
        die("need at least 2 lines like 'I-001 | title | pitch | mechanism' in screen/ideas.md", 5)
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


# ---------------------------------------------------------------- quick-pick (quick mode)

def _one_line(value, default="not stated"):
    text = " ".join(str(value if value is not None else "").replace("|", "/").split())
    return text or default


def quick_pick(root):
    cur = need_json(os.path.join(root, "quick", "curated.json"), "quick/curated.json")
    weights = {str(k): float(v) for k, v in need_json(os.path.join(root, "criteria.json")).items()}
    ideas = cur.get("ideas") if isinstance(cur, dict) else None
    if not isinstance(ideas, list) or not ideas:
        die("quick/curated.json has no ideas", 5)
    by_id, lower = collections.OrderedDict(), {c.lower(): c for c in weights}
    for n, idea in enumerate(ideas):
        if not isinstance(idea, dict) or not str(idea.get("id", "")).strip():
            die(f"quick/curated.json ideas[{n}] lacks 'id'", 5)
        iid = str(idea["id"]).strip()
        if iid in by_id:
            die(f"duplicate id in quick/curated.json: {iid}", 5)
        by_id[iid] = idea
    vals, score = {}, {}
    for iid, idea in by_id.items():
        v = {}
        for s in idea.get("scores") or []:
            name = str((s or {}).get("criterion", "")).strip()
            key = name if name in weights else lower.get(name.lower())
            x = as_float((s or {}).get("score"))
            if key and x is not None:
                v[key] = x
        used = [c for c in weights if c in v]
        vals[iid] = v
        score[iid] = (sum(weights[c] * v[c] for c in used) / sum(weights[c] for c in used)) if used else 0.0
    passed = [i for i in by_id if all(not is_false((by_id[i].get("gates") or {}).get(g, True)) for g in GATES)]
    passed.sort(key=lambda i: (-score[i], i))
    picks, protected, seen = collections.OrderedDict(), set(), set()
    for i in passed:  # best of each cluster
        cl = str(by_id[i].get("cluster", "?"))
        if cl not in seen:
            seen.add(cl)
            picks[i] = "best of cluster"
    notes = []
    dk, fk = find_key(weights, "distinct"), find_key(weights, "feasib")
    if dk and fk:  # tail slot: highest Distinctiveness with Feasibility >= 3
        tail = [i for i in passed if vals[i].get(fk) is not None and vals[i][fk] >= 3 and dk in vals[i]]
        if tail:
            t = max(tail, key=lambda i: (vals[i][dk], score[i]))
            picks[t] = picks[t] + " + tail slot" if t in picks else "tail slot"
            protected.add(t)
    else:
        notes.append("no criteria named like 'Distinctiveness' and 'Feasibility': tail slot skipped")
    human = [i for i in passed if str(by_id[i].get("origin", "")).strip() in HUMAN_ORIGINS]
    if human:
        h = human[0]
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
                  "origin": str(by_id[i].get("origin", "?"))} for i in final]
    textio.write_json_atomic(os.path.join(root, "quick", "finalists.json"), {
        "finalists": finalists,
        "gate_failed": [i for i in by_id if i not in passed],
        "notes": notes})
    origins_path = os.path.join(root, "origins.json")
    origins = opt_json(origins_path) if os.path.exists(origins_path) else {}
    for i in by_id:
        origins[i] = str(by_id[i].get("origin", "?"))
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
    print(f"quick-pick: {len(final)} finalists ({', '.join(f'{i} ({picks[i]})' for i in final)}); "
          f"wrote quick/finalists.json, tournament/cards.md, origins.json")
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
    drivers = need_json(os.path.join(arch, "drivers.json"), "10_ARCHITECTURE/drivers.json")
    cmap = need_json(os.path.join(arch, "candidates", "map.json"), "10_ARCHITECTURE/candidates/map.json")
    judge_files = sorted(glob.glob(os.path.join(arch, "review", "judge_*.out.json")))
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
        fam = os.path.basename(path)[len("judge_"): -len(".out.json")]
        try:
            out = load(path)
        except ValueError as exc:
            warnings.append(f"unreadable {os.path.basename(path)} ({exc}): judge ignored")
            continue
        if not isinstance(out, dict):
            warnings.append(f"{os.path.basename(path)} is not an object: judge ignored")
            continue
        judges.append(fam)
        for cand in out.get("candidates") or []:
            if not isinstance(cand, dict):
                continue
            lab = str(cand.get("label", "")).strip()
            if lab not in data:
                warnings.append(f"judge {fam} scored unknown candidate '{lab}'")
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
            data[lab][fam] = {"veto": cand.get("veto") is True or str(cand.get("veto")).lower() == "true",
                              "reason": _one_line(cand.get("veto_reason"), ""),
                              "scores": scores,
                              "sens": [_one_line(x, "") for x in cand.get("sensitivity_points") or []],
                              "trade": [_one_line(x, "") for x in cand.get("tradeoff_points") or []]}
        for st in out.get("steal") or []:
            if isinstance(st, dict):
                steal_raw.append((fam, st))

    cands = []
    for lab in labels:
        judged_by = list(data[lab])
        eligible = [j for j in judged_by if base_family(j) != author[lab]]
        if not eligible and judged_by:
            eligible = judged_by
            warnings.append(f"candidate {lab}: no judge from another family; all judges used")
        if not judged_by:
            warnings.append(f"candidate {lab}: no judge scored it")
        means, disagree = collections.OrderedDict(), []
        for cid in weights:
            vals = [data[lab][j]["scores"][cid] for j in eligible if cid in data[lab][j]["scores"]]
            if vals:
                means[cid] = sum(vals) / len(vals)
                if max(vals) - min(vals) >= 2:
                    disagree.append(cid)
        vetoes = [j for j in eligible if data[lab][j]["veto"]]
        reasons = [data[lab][j]["reason"] for j in vetoes if data[lab][j]["reason"]]
        if len(vetoes) >= 2:
            veto = "excluded"
        elif len(vetoes) == 1:
            veto = "flagged"
            if len(eligible) == 1:
                reasons.append("single-judge veto: the human decides")
        else:
            veto = "none"

        def merged(key):
            seen, out = set(), []
            for j in eligible:
                for x in data[lab][j][key]:
                    if x and x.lower() not in seen:
                        seen.add(x.lower())
                        out.append(x)
            return out

        cands.append({"label": lab, "means": means, "judges": eligible, "disagreements": disagree, "veto": veto,
                      "veto_reasons": reasons, "vetoes": len(vetoes), "sens": merged("sens"),
                      "trade": merged("trade")})

    def w_score(c, w):
        used = [cid for cid in w if cid in c["means"]]
        if not used:
            return 0.0
        return sum(w[cid] * c["means"][cid] for cid in used) / sum(w[cid] for cid in used)

    rankable = [c for c in cands if c["veto"] != "excluded"]

    def ranks(w):
        order = sorted(rankable, key=lambda c: (-w_score(c, w), c["label"]))
        return {c["label"]: r + 1 for r, c in enumerate(order)}

    base = ranks(weights)
    lo, hi = dict(base), dict(base)
    for cid in weights:  # each weight at +/-25%, one at a time (as in screen)
        for f in (0.75, 1.25):
            w2 = collections.OrderedDict(weights)
            w2[cid] = weights[cid] * f
            for k, r in ranks(w2).items():
                lo[k], hi[k] = min(lo[k], r), max(hi[k], r)
    for c in cands:
        c["score"] = w_score(c, weights)
        c["rank"] = base.get(c["label"])
        c["range"] = [lo[c["label"]], hi[c["label"]]] if c["label"] in base else None
    ordered = sorted(cands, key=lambda c: (c["rank"] is None, c["rank"] or 0, c["label"]))
    leader = next((c["label"] for c in ordered if c["rank"] == 1), None)
    if leader is None:
        leader_status = "close-call"
        warnings.append("every candidate is EXCLUDED by vetoes: no leader; the human decides")
    else:
        others_reach = [c["label"] for c in cands if c["label"] != leader and c["range"] and c["range"][0] == 1]
        leader_status = "clear" if base and lo[leader] == 1 and hi[leader] == 1 and not others_reach \
            else "close-call"

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
        "leader": leader, "leader_status": leader_status, "steal": steal, "warnings": warnings}
    textio.write_json_atomic(os.path.join(arch, "matrix.json"), matrix)

    names = {cid: name for cid, name, _w in criteria}
    md = ["# Architecture trade-off matrix", "",
          "Computed by bs.py arch-matrix. A criterion score is the mean of the eligible judges' 1-5 scores (a judge "
          "never scores a candidate written by its own family). W = sum(weight x mean) / sum(weight) over the "
          "criteria with data. Rank ranges move each weight by +/-25%, one at a time. Veto: 2 or more judges -> "
          "EXCLUDED; 1 judge -> FLAGGED.", "",
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
    md += ["", "## Disagreements (eligible judges' scores span 2 or more points)", ""]
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
    if warnings:
        md += ["", "## Warnings", ""] + [f"- {w}" for w in warnings]
    md += ["", "## Leader", ""]
    if leader is None:
        md.append("Leader: none (every candidate is EXCLUDED; the human decides)")
    elif leader_status == "clear":
        md.append(f"Leader: {leader} (clear: rank 1 under every weight change)")
    else:
        rivals = [c["label"] for c in cands if c["label"] != leader and c["range"] and c["range"][0] == 1]
        md.append(f"Leader: {leader} (close-call" + (f": {', '.join(rivals)} can also rank 1" if rivals else "") + ")")
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


def _title_from_line(line, url):
    t = line.replace(url, " ")
    t = re.sub(r"\[([^\]]*)\]\(\s*\)", r"\1", t)          # [text]() left after removing the url
    t = re.sub(r"<\s*>|\(\s*\)", " ", t)
    t = re.sub(r"^\s*(?:[-*+]|\d+[.)]|#+)\s*", "", t)
    t = " ".join(t.replace("|", " ").split()).strip(" -:;,")
    return t[:80]


_JSON_TITLE_KEYS = ("title", "component", "choice", "claim", "issue", "name", "element", "evidence", "text")


def _json_urls(obj, found, parent=None):
    if isinstance(obj, dict):
        for v in obj.values():
            _json_urls(v, found, obj)
    elif isinstance(obj, list):
        for v in obj:
            _json_urls(v, found, parent)
    elif isinstance(obj, str):
        for m in URL_RE.finditer(obj):
            url = _clean_url(m.group(0))
            title, accessed = "", None
            if isinstance(parent, dict):
                for k in _JSON_TITLE_KEYS:
                    v = parent.get(k)
                    if isinstance(v, str) and v.strip() and not URL_RE.search(v):
                        title = " ".join(v.split())[:80]
                        break
                for k in ("accessed", "date"):
                    v = parent.get(k)
                    if isinstance(v, str) and re.match(r"^\d{4}-\d{2}-\d{2}", v):
                        accessed = v[:10]
                        break
            found.append((url, title or _title_from_line(obj, m.group(0)), accessed))


def sources(root):
    rd = run_date(root)
    scan = [os.path.join(root, "02_CONTEXT.md")]
    scan += sorted(glob.glob(os.path.join(root, "checks", "*.md")))
    scan += [os.path.join(root, "10_ARCHITECTURE", "stack.json")]
    scan += sorted(glob.glob(os.path.join(root, "10_ARCHITECTURE", "review", "*.json")))
    scan += sorted(glob.glob(os.path.join(root, "redteam", "*.md")))
    found = []  # (url, title, accessed, rel)
    for path in scan:
        if not os.path.isfile(path):
            continue
        rel = os.path.relpath(path, root).replace("\\", "/")
        text = read_text(path)
        if path.endswith(".json"):
            try:
                obj = load(path)
            except ValueError:
                obj = None
            if obj is not None:
                hits = []
                _json_urls(obj, hits)
                found += [(u, t, a, rel) for u, t, a in hits]
                continue
        for line in text.splitlines():
            for m in URL_RE.finditer(line):
                url = _clean_url(m.group(0))
                date = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", line.replace(m.group(0), " "))
                found.append((url, _title_from_line(line, m.group(0)), date.group(1) if date else None, rel))
    json_path = os.path.join(root, "sources.json")
    existing = collections.OrderedDict()
    if os.path.exists(json_path):
        try:
            old = load(json_path)
        except ValueError as exc:
            die(f"sources.json is not valid JSON: {exc}", 5)
        if isinstance(old, dict):
            for sid in sorted(old, key=lambda s: (int(re.sub(r"\D", "", s) or 0), s)):
                if re.match(r"^S-\d{3,}$", sid) and isinstance(old[sid], dict) and old[sid].get("url"):
                    existing[sid] = dict(old[sid])
    by_url = {v["url"]: sid for sid, v in existing.items()}
    nxt = max([int(s[2:]) for s in existing] or [0]) + 1
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
    for p in sorted(glob.glob(os.path.join(arch, "**", "*.md"), recursive=True)):
        rel = os.path.relpath(p, arch).replace("\\", "/")
        if rel.split("/")[0] in ("_raw", "candidates", "review") or rel == "lint.md":
            continue  # raw and rejected-candidate text is not part of the chosen package
        files.append(p)
    files += sorted(glob.glob(os.path.join(root, "11_PROPOSAL", "sections", "*.md")))
    return files


_Q_FIELD_RE = re.compile(r"[\s(;,.-]*\b(owner|decide[ _-]*by)\s*:\s*([^;|)]*?)\s*(?=[;|)]|\b(?:owner|decide[ _-]*by)"
                         r"\s*:|$)", re.I)


def _section13_questions(text):
    """[(question, owner, decide_by)] from the bullet (or numbered) lines of proposal section 13."""
    out = []
    for line in (text or "").split("\n"):
        m = re.match(r"^\s*(?:[-*+]|\d+[.)])\s+(.*\S)\s*$", line)
        if not m:
            continue
        body = m.group(1).replace("**", "")
        owner = by = None
        for fm in _Q_FIELD_RE.finditer(body):
            if fm.group(1).lower().startswith("owner"):
                owner = fm.group(2).strip(" .") or None
            else:
                by = fm.group(2).strip(" .") or None
        q = _Q_FIELD_RE.sub("", body).strip(" -;,")
        if q:
            out.append((" ".join(q.split()), owner, by))
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
    status_files = sorted(set(glob.glob(os.path.join(root, "10_ARCHITECTURE", "**", "*.status.json"), recursive=True)
                              + glob.glob(os.path.join(root, "11_PROPOSAL", "**", "*.status.json"), recursive=True)))
    for path in status_files:
        rel = os.path.relpath(path, root).replace("\\", "/")
        try:
            st = load(path)
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
    for name in ("init", "status", "schemas", "map", "prepare-screen", "screen", "tournament", "quick-pick",
                 "arch-matrix", "lint-frame", "sources", "assumptions"):
        sp = sub.add_parser(name)
        sp.add_argument("run")
    sp = sub.add_parser("prepare-tournament")
    sp.add_argument("run")
    sp.add_argument("--per-pair", action="store_true")
    sp = sub.add_parser("dupcheck")
    sp.add_argument("run")
    sp.add_argument("--threshold", type=float, default=None)
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
                  "quick-pick": quick_pick, "arch-matrix": arch_matrix, "sources": sources,
                  "assumptions": assumptions}
        if args.cmd in simple:
            simple[args.cmd](root)
        elif args.cmd == "prepare-tournament":
            prepare_tournament(root, per_pair=args.per_pair)
        elif args.cmd == "dupcheck":
            dupcheck(root, args.threshold)
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
