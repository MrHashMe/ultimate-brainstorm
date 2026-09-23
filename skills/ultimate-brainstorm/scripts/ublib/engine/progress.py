"""Progress, estimates and budgets (KIT_SPEC 6.9): the card progress block, PROGRESS.md, `ub plan`, ETA.

plan: calls = exact counts from pipeline fanouts and seats, with min/max for conditional steps (and the preflight
pings); tokens = sum of per-kind priors x [0.7, 1.6]; minutes = critical path of waves / concurrency, recalibrated
from the median durations in logs/calls.jsonl once observed; dollars only when UB_HOME/families.json sets `prices`.
"""

import glob
import json
import math
import os
import statistics

from .. import textio
from . import (ESTIMATES_FILE, FAMILY_ORDER, LAST_STAGE, STAGE_NAMES, base_family, is_alt)
from . import state as st

DEFAULT_ESTIMATES = {
    "ping": {"in_tokens": 50, "out_tokens": 10, "seconds": 20},
    "generator": {"in_tokens": 6000, "out_tokens": 8000, "seconds": 180},
    "researcher": {"in_tokens": 5000, "out_tokens": 4000, "seconds": 360},
    "curator": {"in_tokens": 30000, "out_tokens": 12000, "seconds": 300},
    "judge": {"in_tokens": 9000, "out_tokens": 3000, "seconds": 120},
    "checker": {"in_tokens": 5000, "out_tokens": 3000, "seconds": 240},
    "normalizer": {"in_tokens": 8000, "out_tokens": 4000, "seconds": 150},
    "reviewer": {"in_tokens": 6000, "out_tokens": 3000, "seconds": 180},
    "synthesis": {"in_tokens": 15000, "out_tokens": 5000, "seconds": 200},
    "writer": {"in_tokens": 15000, "out_tokens": 8000, "seconds": 360},
    "arch-author": {"in_tokens": 8000, "out_tokens": 9000, "seconds": 360},
    "arch-judge": {"in_tokens": 20000, "out_tokens": 4000, "seconds": 200},
    "rubric": {"in_tokens": 25000, "out_tokens": 3000, "seconds": 150},
    "redteam": {"in_tokens": 25000, "out_tokens": 4000, "seconds": 200},
    "fixer": {"in_tokens": 30000, "out_tokens": 12000, "seconds": 400},
    "frame": {"in_tokens": 3000, "out_tokens": 3000, "seconds": 120},
}


def estimates():
    try:
        data = textio.read_json(ESTIMATES_FILE)
        if isinstance(data, dict):
            out = dict(DEFAULT_ESTIMATES)
            for k, v in data.items():
                if isinstance(v, dict) and not k.startswith("_"):
                    out[k] = v
            return out
    except (OSError, ValueError):
        pass
    return dict(DEFAULT_ESTIMATES)


# ---------------------------------------------------------------- families line

def families_line(ctx):
    s = ctx.state
    fams = s.get("families") or {}
    host = ctx.host_family
    prov = {}
    for p in s.get("provisional") or []:
        if isinstance(p, dict) and p.get("seat"):
            prov.setdefault(base_family(p["seat"]), p)
    parts = []
    for f in FAMILY_ORDER:
        info = fams.get(f) or {}
        status = info.get("status")
        if status == "ok" and st.family_allowed(s, f):
            tags = []
            if f == host:
                tags.append("host")
            if info.get("web") and (s.get("privacy") or {}).get("web", True):
                tags.append("web")
            if info.get("backend") == "host":
                tags.append("via host sub-agents")
            label = "%s OK" % f + (" (%s)" % ", ".join(tags) if tags else "")
            if f in prov:
                label = "%s PROVISIONAL->%s at %s" % (f, prov[f].get("actual"), prov[f].get("stage"))
            parts.append(label)
        elif status == "excluded" or (status == "ok" and not st.family_allowed(s, f)):
            parts.append("%s off (privacy/kickoff)" % f)
        elif f == host:
            parts.append("%s (host; no CLI)" % f)
        else:
            parts.append("%s not set up" % f)
    return " | ".join(parts)


# ---------------------------------------------------------------- calls

def job_files(run_dir):
    return sorted(glob.glob(os.path.join(run_dir, "jobs", "*.json")))


def calls_summary(ctx):
    done = failed = running = provisional = 0
    run_dir = ctx.run_dir
    if not run_dir:
        return {"done": 0, "failed": 0, "running": 0, "provisional": 0}
    live = set()
    for p in glob.glob(os.path.join(run_dir, ".ub", "jobs", "*.running.json")):
        live.add(os.path.basename(p)[:-len(".running.json")])
    for p in job_files(run_dir):
        try:
            job = textio.read_json(p)
        except (OSError, ValueError):
            continue
        jid = job.get("id")
        meta = ctx.read_json((job.get("out") or "") + ".meta.json", None) or {}
        if meta.get("id") == jid and meta.get("status") == "ok":
            done += 1
            if meta.get("provisional") or job.get("provisional"):
                provisional += 1
        elif jid in live:
            running += 1
        elif meta.get("id") == jid and meta.get("status") not in (None, "ok"):
            failed += 1
    return {"done": done, "failed": failed, "running": running, "provisional": provisional}


def observed_durations(run_dir):
    out = {}
    path = os.path.join(run_dir or "", "logs", "calls.jsonl")
    if not run_dir or not os.path.exists(path):
        return out
    try:
        text = textio.read_text(path)
    except OSError:
        return out
    for ln in text.split("\n"):
        if not ln.strip():
            continue
        try:
            rec = json.loads(ln)
        except ValueError:
            continue
        if rec.get("status") == "ok" and rec.get("duration_s"):
            out.setdefault(rec.get("kind") or "all", []).append(float(rec["duration_s"]))
            out.setdefault("all", []).append(float(rec["duration_s"]))
    return out


# ---------------------------------------------------------------- plan

def _parallel(ctx):
    try:
        return max(1, int(((ctx.deps.families_cfg() if ctx.deps else {}).get("defaults") or {}).get("parallel", 4)))
    except Exception:
        return 4


def _factor(ctx, est):
    """Wall-time recalibration (6.9): per job kind, the median observed duration over its prior, for kinds with at
    least 3 finished calls; preflight pings (seconds, against minute-long priors) never count. 1.0 until then."""
    obs = observed_durations(ctx.run_dir)
    ratios = []
    for kind, vals in obs.items():
        if kind in ("all", "ping") or len(vals) < 3 or kind not in est:
            continue
        prior = float(est[kind].get("seconds") or 0)
        if prior > 0:
            ratios.append(statistics.median(vals) / prior)
    if not ratios:
        return 1.0
    return max(0.2, min(5.0, statistics.median(ratios)))


def plan(ctx, sequence=None):
    """{"calls":{"min","max","expected","by_family"},"tokens":[lo,hi],"minutes":[lo,hi]} (6.9)."""
    from . import pipeline
    est = estimates()
    seq = sequence if sequence is not None else pipeline.simulate(ctx)
    cmin = cmax = 0
    tok_lo = tok_hi = 0.0
    secs = 0.0
    by_family = {}
    parallel = _parallel(ctx)
    factor = _factor(ctx, est)
    npings = len([f for f, i in (ctx.state.get("families") or {}).items() if i.get("preflight")])
    cmin += npings
    cmax += npings
    for item in seq:
        lo, hi = item["count"]
        kind = item.get("kind") or "generator"
        e = est.get(kind) or est["generator"]
        cmin += lo
        cmax += hi
        mid = (lo + hi) / 2.0
        per = float(e.get("in_tokens", 0) + e.get("out_tokens", 0))
        tok_lo += per * lo * 0.7
        tok_hi += per * hi * 1.6
        waves = math.ceil(mid / float(max(1, parallel))) if mid else 0
        secs += waves * float(e.get("seconds", 120)) * factor
        for fam, n in item.get("families", {}).items():
            by_family[fam] = by_family.get(fam, 0) + n
    expected = int(round((cmin + cmax) / 2.0))
    out = {"calls": {"min": int(cmin), "max": int(cmax), "expected": expected, "by_family": by_family},
           "tokens": [int(tok_lo), int(max(tok_hi, tok_lo))],
           "minutes": [int(secs * 0.7 / 60.0), int(math.ceil(secs * 1.6 / 60.0))]}
    prices = _prices()
    if prices:
        out["usd"] = _usd(by_family, est, prices)
        out["cost"] = "about $%.2f-%.2f" % tuple(out["usd"])
    else:
        out["cost"] = "counts against your plans"
    return out


def _prices():
    try:
        path = os.path.join(st.ub_home(), "families.json")
        data = textio.read_json(path) if os.path.exists(path) else {}
        return data.get("prices") if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def _usd(by_family, est, prices):
    mean_tok = statistics.mean([v["in_tokens"] + v["out_tokens"] for v in est.values()])
    lo = hi = 0.0
    for fam, n in by_family.items():
        p = prices.get(base_family(fam)) if isinstance(prices, dict) else None
        if not isinstance(p, dict):
            continue
        per_mtok = float(p.get("usd_per_mtok", 0) or 0)
        lo += n * mean_tok * 0.7 / 1e6 * per_mtok
        hi += n * mean_tok * 1.6 / 1e6 * per_mtok
    return [round(lo, 2), round(hi, 2)]


def plan_for_state(ctx):
    try:
        return plan(ctx)
    except Exception:
        return {"calls": {"min": 0, "max": 0, "expected": 0, "by_family": {}}, "tokens": [0, 0], "minutes": [0, 0],
                "cost": "unknown"}


# ---------------------------------------------------------------- progress block

def stage_marks(ctx, steps):
    """{stage: 'x' | '~' | ' '} from step states."""
    marks = {}
    for s in steps:
        stage = int(s.get("stage", 0))
        state = st.step_state(ctx.state, s["id"])
        marks.setdefault(stage, [])
        marks[stage].append(state)
    out = {}
    for stage in range(0, LAST_STAGE + 1):
        states = marks.get(stage, [])
        if states and all(x in ("done", "skipped") for x in states):
            out[stage] = "x"
        elif any(x in ("done", "running") for x in states):
            out[stage] = "~"
        else:
            out[stage] = " "
    return out


def progress_block(ctx, steps, current=None, extra_line=None):
    total = len(steps) or 1
    finished = len([s for s in steps if st.step_state(ctx.state, s["id"]) in ("done", "skipped")])
    pct = int(round(100.0 * finished / total))
    if ctx.state.get("status") == "done":
        pct = 100
    stage = int((current or {}).get("stage", LAST_STAGE if pct == 100 else 0))
    bar_n = 14
    filled = int(round(bar_n * pct / 100.0))
    calls = calls_summary(ctx)
    ideas = _counts_line(ctx)
    line = "[%s%s] %d/%d %s | %s%d calls" % ("#" * filled, "." * (bar_n - filled), stage, LAST_STAGE,
                                             STAGE_NAMES.get(stage, ""), (ideas + " | ") if ideas else "",
                                             calls["done"])
    eta = eta_s(ctx, steps)
    return {"pct": pct, "stage": stage, "of": LAST_STAGE, "line": line, "calls": calls, "eta_s": eta}


def _counts_line(ctx):
    if not ctx.run_dir:
        return ""
    parts = []
    cl = ctx.read_json("clusters.json", None)
    if isinstance(cl, dict) and cl:
        parts.append("%d ideas" % len(cl))
    sl = ctx.read_json("screen/shortlist.json", None)
    if isinstance(sl, dict) and sl.get("shortlist"):
        parts.append(str(len(sl["shortlist"])))
    fin = ctx.state.get("finalists")
    if fin:
        parts.append(str(len(fin)))
    return " -> ".join(parts)


def eta_s(ctx, steps):
    """[lo, hi] seconds for the remaining dispatch steps (a rough guide)."""
    from . import pipeline
    try:
        seq = pipeline.simulate(ctx, remaining_only=True)
    except Exception:
        return [0, 0]
    est = estimates()
    parallel = _parallel(ctx)
    factor = _factor(ctx, est)  # the same waves and recalibration as plan(), so G0 and PROGRESS.md agree
    secs = 0.0
    for item in seq:
        lo, hi = item["count"]
        e = est.get(item.get("kind") or "generator") or est["generator"]
        secs += math.ceil(((lo + hi) / 2.0) / float(parallel)) * float(e.get("seconds", 120)) * factor
    return [int(secs * 0.7), int(secs * 1.6)]


def _fmt_eta(eta):
    lo, hi = eta
    if hi <= 0:
        return "-"
    return "%d-%d min" % (max(1, lo // 60), max(1, hi // 60))


def write_progress(ctx, steps, current=None, next_text=""):
    s = ctx.state
    now = textio.now_iso()[11:16]
    block = progress_block(ctx, steps, current)
    marks = stage_marks(ctx, steps)
    calls = block["calls"]
    lines = ["# ultimate-brainstorm: %s (%s, %s, %s)                  updated %s"
             % (s.get("run"), s.get("mode"), s.get("variant"), s.get("autopilot"), now),
             "%d%% | stage %d/%d %s | ETA %s | NEXT: %s" % (block["pct"], block["stage"], LAST_STAGE,
                                                           STAGE_NAMES.get(block["stage"], ""), _fmt_eta(
                                                               block["eta_s"]), next_text or "-"),
             "Families: %s" % families_line(ctx),
             "Calls: %d done, %d running, %d failed, %d provisional | ~%.1fM tokens (est.)"
             % (calls["done"], calls["running"], calls["failed"], calls["provisional"],
                _tokens_done(calls["done"]) / 1e6)]
    if st.single_family(s):
        lines.append("PROVISIONAL: one model family only; cross-family seats are -alt substitutes")
    row = []
    for stage in range(0, LAST_STAGE + 1):
        row.append("[%s] %d %s" % (marks.get(stage, " "), stage, STAGE_NAMES[stage]))
    lines.append("  ".join(row[:8]))
    lines.append("  ".join(row[8:]))
    files = [f for f in ("03_POOL.md", "04_SHORTLIST.md", "06_TOURNAMENT.md", "07_REDTEAM.md", "08_DECISION.md",
                         "10_ARCHITECTURE/README.md", "11_PROPOSAL/PROPOSAL.md") if ctx.exists(f)]
    lines.append("Files: %s" % (" | ".join(files) or "-"))
    from . import builders
    from . import gates
    text = builders.render_doc("PROGRESS", {
        "SLUG": s.get("run", ""), "MODE": s.get("mode", ""), "VARIANT": s.get("variant", ""),
        "AUTOPILOT": s.get("autopilot", ""), "TIME": now, "PROGRESS_LINE": lines[1],
        "PROVISIONAL_BANNER": gates.provisional_banner(ctx), "FAMILIES_LINE": families_line(ctx),
        "CALLS_LINE": lines[3][len("Calls: "):], "STAGE_CHECKLIST": "\n".join(["  ".join(row[:8]),
                                                                              "  ".join(row[8:])]),
        "FILES_LINE": " | ".join(files) or "-"}, fallback="\n".join(lines) + "\n")
    ctx.write("PROGRESS.md", text)
    return block


def _tokens_done(n):
    return n * 12000.0


# ---------------------------------------------------------------- budget

def calls_used(state):
    return int((state.get("counters") or {}).get("launched", 0))


def over_budget(state, extra=1):
    cap = (state.get("budget") or {}).get("max_calls")
    if not cap:
        return False
    return calls_used(state) + extra > int(cap)
