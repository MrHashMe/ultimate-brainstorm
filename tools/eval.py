#!/usr/bin/env python3
"""Offline evaluation of finished ultimate-brainstorm run folders. Dev tool: standard library only, no network, no
model calls; it only reads run folders.

Usage:
    python tools/eval.py RUN_OR_FOLDER [RUN_OR_FOLDER ...] [--json] [--out FILE]

Each argument is a run folder (it has run.json) or a folder whose sub-folders are run folders (a brainstorm/
folder). Over every run it reports:
- per strategy (pool prefix: S1..S5, L1..L6, G1.., R1.., H, HP, IMP, E for evolved ideas) and per generating
  family: canonical ideas credited, shortlisted, finalists, chosen; survival = shortlisted / credited, finalist rate
  = finalists / credited, win rate = chosen / finalists, and the mean tournament score of its finalists;
- strategy x family cells, and the strategies seen on one family only (their yield cannot be told from that
  family's; the seeded seat rotation spreads the non-host strategies over the non-host families across runs);
- judge agreement per run: Kendall's W of the screen judges' weighted scores and of the tournament judges'
  per-card points (1 = every judge ranks the ideas the same way, 0 = no agreement);
- position consistency per tournament judge family, and a self-preference estimate per judge family: the
  tournament audit (own-vendor win share minus the other judges' share for the same pairs) and the screen
  own-origin gap, averaged over runs.
Exit codes: 0 ok, 2 usage, 4 no run folder found.
"""

import argparse
import collections
import json
import os
import re
import sys

KIT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(KIT, "skills", "ultimate-brainstorm", "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

import bs  # noqa: E402  (tally, collect_votes, weighted: the kit's own bookkeeping)
from ublib import textio  # noqa: E402

PREFIX_RE = re.compile(r"^(.*?)-\d+$")


def read_json(path, default=None):
    try:
        return textio.read_json(path)
    except (OSError, ValueError):
        return default


def run_folders(paths):
    out = []
    for p in paths:
        p = os.path.abspath(p)
        if os.path.isfile(os.path.join(p, "run.json")):
            out.append(p)
        elif os.path.isdir(p):
            out += sorted(os.path.join(p, d) for d in os.listdir(p)
                          if os.path.isfile(os.path.join(p, d, "run.json")))
    return list(collections.OrderedDict.fromkeys(out))


def kendall_w(rankings):
    """Kendall's coefficient of concordance for {judge: {item: score}} (higher score = better) over the items every
    judge scored, with the tie correction. None for fewer than 2 judges or items, or no variance at all."""
    judges = [j for j in rankings if rankings[j]]
    if len(judges) < 2:
        return None
    items = sorted(set.intersection(*[set(rankings[j]) for j in judges]))
    m, n = len(judges), len(items)
    if n < 2:
        return None
    totals = [0.0] * n
    ties = 0.0
    for j in judges:
        ranks = bs._avg_ranks([rankings[j][i] for i in items])
        for k in range(n):
            totals[k] += ranks[k]
        for t in collections.Counter(rankings[j][i] for i in items).values():
            ties += t ** 3 - t
    mean = m * (n + 1) / 2.0
    s = sum((r - mean) ** 2 for r in totals)
    denom = m * m * (n ** 3 - n) - m * ties
    return None if denom <= 0 else round(12.0 * s / denom, 3)


def lineage(root):
    """{idea id: [strategy prefixes]} from ideas.json (bs.py map), else from the Aliases of 03_POOL.md."""
    data = read_json(os.path.join(root, "ideas.json"))
    if isinstance(data, dict) and data:
        return dict((k, list(v.get("strategies") or [])) for k, v in data.items() if isinstance(v, dict))
    out = {}
    path = os.path.join(root, "03_POOL.md")
    text = textio.read_text(path) if os.path.isfile(path) else ""
    for m in re.finditer(r"^- (I-\d+) .*?Aliases: ([A-Za-z0-9, -]+)\.", text, re.M):
        out[m.group(1)] = sorted(set((PREFIX_RE.match(a.strip()) or re.match(r"(.*)", a.strip())).group(1)
                                     for a in m.group(2).split(",") if a.strip()))
    return out


def family_of(root, seats):
    """strategy prefix -> the family that produced it: pool/_families.json (actual, substitutes included), else the
    run.json generator seats; human prefixes are human."""
    fam = dict((k, str(v)) for k, v in (seats.get("generators") or {}).items())
    fam.update(dict((k, str(v)) for k, v in (read_json(os.path.join(root, "pool", "_families.json"), {}) or {})
                    .items()))

    def of(prefix):
        return fam.get(prefix) or ("human" if prefix.upper().startswith("H") else "?")
    return of


def screen_rankings(root):
    """{judge label: {idea: weighted score}} from screen/*.out.json (criteria.json weights), read by bs.py's own
    screen_records: a judge is the family that answered (a fallback copy counts as the model that ran it, merged with
    that family's seat), never the file name."""
    weights = read_json(os.path.join(root, "criteria.json"), {}) or {}
    weights = dict((k, float(v)) for k, v in weights.items() if bs.as_float(v) is not None)
    if not weights or not os.path.isdir(os.path.join(root, "screen")):
        return {}
    ideas_md = os.path.join(root, "screen", "ideas.md")
    known = set(ln.split("|")[0].strip() for ln in textio.read_text(ideas_md).splitlines() if ln.strip()) \
        if os.path.isfile(ideas_md) else set()
    try:
        judges = bs.screen_records(root, weights, known)[0]
    except (OSError, ValueError, bs.BsError):
        return {}
    out = {}
    for label, per in judges.items():
        out[label] = dict((i, w) for i, w in ((i, bs.weighted(r["c"], weights)) for i, r in per.items())
                          if w is not None)
    return out


def tournament_rankings(root):
    """{judge family: {card: points}} from the tournament calls (the both-order tally of bs.py)."""
    d = os.path.join(root, "tournament")
    if not os.path.isdir(d):
        return {}
    try:
        votes = bs.collect_votes(d)[0]
    except (OSError, ValueError, KeyError, bs.BsError):
        return {}
    pts = bs.tally(votes)[0]
    out = collections.defaultdict(lambda: collections.defaultdict(float))
    for (f, _pair), s in pts.items():
        for k, v in s.items():
            out[f][k] += v
    return dict((f, dict(v)) for f, v in out.items())


def one_run(root):
    rj = read_json(os.path.join(root, "run.json"), {}) or {}
    seats = rj.get("seats") or {}
    ideas = lineage(root)
    sl = read_json(os.path.join(root, "screen", "shortlist.json"), {}) or {}
    shortlisted = set(str(s.get("id")) for s in sl.get("shortlist") or [] if isinstance(s, dict))
    finalists = [str(i) for i in rj.get("finalists") or []]
    chosen = (rj.get("choice") or {}).get("idea")
    res = read_json(os.path.join(root, "tournament", "result.json"), {}) or {}
    score = dict((str(r.get("id")), r.get("pct")) for r in res.get("debiased") or [] if isinstance(r, dict))
    fam = family_of(root, seats)
    pairs = dict((i, [(s, fam(s)) for s in strategies]) for i, strategies in ideas.items())
    evolve_family = (rj.get("host") or {}).get("family") or seats.get("host") or "host"
    evolved_md = os.path.join(root, "05_EVOLVED.md")
    for e in re.findall(r"^#{2,3}\s*(E-\d+)", textio.read_text(evolved_md) if os.path.isfile(evolved_md) else "",
                        re.M):
        if os.path.isfile(os.path.join(root, "checks", e + ".md")):  # a checked E idea enters the finalist pool
            pairs.setdefault(e, [("E", evolve_family)])
    rows = []
    for i, ps in sorted(pairs.items()):
        rows.append({"id": i, "pairs": ps, "shortlisted": i in shortlisted or ps == [("E", evolve_family)],
                     "finalist": i in finalists, "chosen": i == chosen, "score": score.get(i)})
    gaps = dict((g.get("judge"), g.get("gap")) for g in sl.get("own_origin_gap") or [] if isinstance(g, dict))
    audit = dict((a.get("judge"), a.get("diff")) for a in res.get("audit") or [] if isinstance(a, dict))
    return {"run": os.path.basename(root), "mode": rj.get("mode"), "status": rj.get("status"),
            "generators": seats.get("generators") or {}, "rotation": seats.get("rotation"), "ideas": rows,
            "kendall_w": {"screen": kendall_w(screen_rankings(root)),
                          "tournament": kendall_w(tournament_rankings(root))},
            "consistency": res.get("consistency") or {}, "self_preference": {"tournament": audit, "screen": gaps},
            "ranking": (res.get("ranking") or {}).get("method")}


def _rates(c):
    def ratio(a, b):
        return round(float(a) / b, 3) if b else None
    scores = c.pop("_scores")
    out = dict(c)
    out.update({"survival": ratio(c["shortlisted"], c["credited"]),
                "finalist_rate": ratio(c["finalists"], c["credited"]),
                "win_rate": ratio(c["chosen"], c["finalists"]),
                "mean_score": round(sum(scores) / len(scores), 1) if scores else None})
    return out


def aggregate(runs):
    def counter():
        return {"credited": 0, "shortlisted": 0, "finalists": 0, "chosen": 0, "_scores": []}
    by_s, by_f, cells = (collections.defaultdict(counter) for _ in range(3))
    fams_of = collections.defaultdict(set)
    for r in runs:
        for idea in r["ideas"]:  # a merged idea is credited to each of its strategies and families once
            keys = [("s", s) for s in sorted(set(s for s, _f in idea["pairs"]))]
            keys += [("f", f) for f in sorted(set(f for _s, f in idea["pairs"]))]
            keys += [("c", "%s|%s" % sf) for sf in sorted(set(idea["pairs"]))]
            for s, f in idea["pairs"]:
                fams_of[s].add(f)
            for kind, k in keys:
                c = {"s": by_s, "f": by_f, "c": cells}[kind][k]
                c["credited"] += 1
                c["shortlisted"] += idea["shortlisted"]
                c["finalists"] += idea["finalist"]
                c["chosen"] += idea["chosen"]
                if idea["finalist"] and isinstance(idea["score"], (int, float)):
                    c["_scores"].append(float(idea["score"]))

    def mean_of(values):
        vals = [v for v in values if isinstance(v, (int, float))]
        return round(sum(vals) / len(vals), 3) if vals else None

    def per_family(key, sub=None):
        acc = collections.defaultdict(list)
        for r in runs:
            src = r[key] if sub is None else r[key][sub]
            for f, v in (src or {}).items():
                acc[f].append(v)
        return dict((f, mean_of(v)) for f, v in sorted(acc.items()))
    return {
        "runs": [r["run"] for r in runs],
        "strategies": dict((k, _rates(v)) for k, v in sorted(by_s.items())),
        "families": dict((k, _rates(v)) for k, v in sorted(by_f.items())),
        "cells": dict((k, _rates(v)) for k, v in sorted(cells.items())),
        "confounded_strategies": sorted(s for s, f in fams_of.items() if len(f) == 1),
        "judges": {"kendall_w": {"screen": mean_of(r["kendall_w"]["screen"] for r in runs),
                                 "tournament": mean_of(r["kendall_w"]["tournament"] for r in runs),
                                 "per_run": dict((r["run"], r["kendall_w"]) for r in runs)},
                   "position_consistency": per_family("consistency"),
                   "self_preference": {"tournament": per_family("self_preference", "tournament"),
                                       "screen": per_family("self_preference", "screen")}},
    }


def _pct(v):
    return "-" if v is None else "%.0f%%" % (100 * v)


def _num(v, fmt="%.2f"):
    return "-" if v is None else fmt % v


def markdown(agg):
    out = ["# ultimate-brainstorm evaluation", "", "Runs (%d): %s" % (len(agg["runs"]), ", ".join(agg["runs"]))]
    for title, key, col in (("Strategies", "strategies", "strategy"), ("Generating families", "families", "family"),
                            ("Strategy x family", "cells", "strategy|family")):
        out += ["", "## " + title, "", "| %s | credited | shortlisted | finalists | chosen | survival | finalist "
                "rate | win rate | mean score |" % col, "|---|---|---|---|---|---|---|---|---|"]
        for k, c in agg[key].items():
            out.append("| %s | %d | %d | %d | %d | %s | %s | %s | %s |" % (
                k, c["credited"], c["shortlisted"], c["finalists"], c["chosen"], _pct(c["survival"]),
                _pct(c["finalist_rate"]), _pct(c["win_rate"]), _num(c["mean_score"], "%.1f")))
    out += ["", "Strategies seen on one family only (yield confounded with that family): "
            + (", ".join(agg["confounded_strategies"]) or "none")]
    j = agg["judges"]
    out += ["", "## Judges", "", "Kendall's W (mean over runs): screen %s, tournament %s" % (
        _num(j["kendall_w"]["screen"]), _num(j["kendall_w"]["tournament"])), ""]
    out += ["| family | position consistency | self-preference (tournament) | own-origin gap (screen) |",
            "|---|---|---|---|"]
    fams = sorted(set(j["position_consistency"]) | set(j["self_preference"]["tournament"])
                  | set(j["self_preference"]["screen"]))
    for f in fams:
        out.append("| %s | %s | %s | %s |" % (f, _pct(j["position_consistency"].get(f)),
                                              _num(j["self_preference"]["tournament"].get(f), "%+.2f"),
                                              _num(j["self_preference"]["screen"].get(f), "%+.2f")))
    return "\n".join(out) + "\n"


def main(argv=None):
    p = argparse.ArgumentParser(prog="eval.py", description="Aggregate finished ultimate-brainstorm run folders.")
    p.add_argument("paths", nargs="+")
    p.add_argument("--json", action="store_true")
    p.add_argument("--out", default=None)
    args = p.parse_args(argv)
    roots = run_folders(args.paths)
    if not roots:
        print("no run folder (with run.json) found in: %s" % ", ".join(args.paths), file=sys.stderr)
        return 4
    agg = aggregate([one_run(r) for r in roots])
    text = json.dumps(agg, ensure_ascii=True) if args.json else markdown(agg)
    if args.out:
        textio.write_text_atomic(args.out, text if text.endswith("\n") else text + "\n")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
