"""Progress, estimates and budgets (KIT_SPEC 6.9): the card progress block, PROGRESS.md, `ub plan`, ETA.

plan: calls = exact counts from pipeline fanouts and seats, with min/max for conditional steps (and the preflight
pings); tokens = sum of per-kind priors x [0.7, 1.6]; minutes = critical path of waves / concurrency, recalibrated
from the median durations in logs/calls.jsonl once observed; dollars only when UB_HOME/families.json sets `prices`.
"""

import json
import math
import os
import statistics

from .. import textio
from . import (ESTIMATES_FILE, FAMILY_ORDER, LAST_STAGE, STAGE_NAMES, base_family)
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
    return sorted(textio.glob_in(run_dir, "jobs", "*.json"))


def calls_summary(ctx):
    done = failed = running = provisional = 0
    run_dir = ctx.run_dir
    if not run_dir:
        return {"done": 0, "failed": 0, "running": 0, "provisional": 0}
    live = set()
    for p in textio.glob_in(run_dir, ".ub", "jobs", "*.running.json"):
        live.add(os.path.basename(p)[:-len(".running.json")])
    for p in job_files(run_dir):
        try:
            job = textio.read_json(p)
        except (OSError, ValueError):
            continue
        if not isinstance(job, dict):
            continue
        jid, out = job.get("id"), job.get("out")
        if not isinstance(jid, str) or not jid:
            continue
        meta = ctx.read_json(out + ".meta.json", None) if isinstance(out, str) and out else None
        meta = meta if isinstance(meta, dict) else {}
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
            secs = float(rec["duration_s"]) if rec.get("status") == "ok" and rec.get("duration_s") else None
        except (ValueError, TypeError, AttributeError, OverflowError):  # OverflowError: an integer past a float
            continue
        if secs and math.isfinite(secs) and secs > 0:
            kind = rec.get("kind")
            out.setdefault(kind if isinstance(kind, str) and kind else "all", []).append(secs)
            out.setdefault("all", []).append(secs)
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


def _reserve_of(ctx, memo, fam):
    """Worst-case requests of one launch on `fam` (C6), or 1 when the adapter cannot tell."""
    if fam not in memo:
        try:
            memo[fam] = max(1, int(ctx.deps.request_reserve({"id": "plan", "family": fam,
                                                              "chain": ctx.family_chain(fam)})))
        except Exception:  # noqa: BLE001 - a plan never fails on an estimate
            memo[fam] = 1
    return memo[fam]


def plan(ctx, sequence=None):
    """{"calls":{"min","max","expected","by_family"},"requests":{"min","expected","max","cap"},"tokens":[lo,hi],
    "minutes":[lo,hi]} (6.9). requests are the budget unit: one per call when nothing is retried; max counts every
    call at its worst case (every backend of its chain, every retry, one repair)."""
    from . import pipeline
    est = estimates()
    seq = sequence if sequence is not None else pipeline.simulate(ctx)
    cmin = cmax = 0
    rmax = 0
    reserves = {}
    tok_lo = tok_hi = 0.0
    secs = 0.0
    by_family = {}
    parallel = _parallel(ctx)
    factor = _factor(ctx, est)
    pinged = [f for f, i in (ctx.state.get("families") or {}).items() if i.get("preflight")]
    cmin += len(pinged)
    cmax += len(pinged)
    rmax += sum(_reserve_of(ctx, reserves, f) for f in pinged)
    for item in seq:
        lo, hi = item["count"]
        kind = item.get("kind") or "generator"
        e = est.get(kind) or est["generator"]
        cmin += lo
        cmax += hi
        rmax += hi * max([_reserve_of(ctx, reserves, f) for f in item.get("families") or {}] or [1])
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
           "requests": {"min": int(cmin), "expected": expected, "max": int(max(rmax, cmax)),
                        "cap": (ctx.state.get("budget") or {}).get("max_calls")},
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


def progress_block(ctx, steps, current=None):
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


# ---------------------------------------------------------------- budget (I8)

def _row_requests(line):
    """Backend requests of one calls.jsonl row (C6): its integer `requests`; a row without it counts as 1, except the
    engine's host sub-agent rows (backend host), which sent nothing."""
    try:
        rec = json.loads(line)
    except ValueError:
        return 1
    n = rec.get("requests") if isinstance(rec, dict) else None
    if isinstance(n, int) and not isinstance(n, bool) and n >= 0:
        return n
    return 0 if isinstance(rec, dict) and rec.get("backend") == "host" else 1


def requests_used(ctx):
    """Backend requests the run has sent: the sum over logs/calls.jsonl (the request ledger, one row per attempt).
    Read incrementally: a call parses only the complete lines appended since the last call in this process."""
    if not ctx.run_dir:
        return 0
    path = os.path.join(ctx.run_dir, "logs", "calls.jsonl")
    memo = ctx.cache.get("ledger")
    try:
        size = os.path.getsize(path)
    except OSError:
        size = 0
    if memo is None or size < memo["pos"]:
        memo = ctx.cache["ledger"] = {"pos": 0, "total": 0}
    if size > memo["pos"]:
        try:
            with open(path, "rb") as f:
                f.seek(memo["pos"])
                data = f.read(size - memo["pos"])
        except OSError:
            return memo["total"]
        end = data.rfind(b"\n") + 1  # a line still being appended is counted at the next call
        for ln in data[:end].split(b"\n"):
            if ln.strip():
                memo["total"] += _row_requests(ln.decode("utf-8", "replace"))
        memo["pos"] += end
    return memo["total"]


def launches(state):
    """Job launches (and relaunches) the driver made: shown next to the requests, never the budget unit."""
    return int((state.get("counters") or {}).get("launched", 0))


def budget_status(ctx):
    b = ctx.state.get("budget") or {}
    return {"max_calls": b.get("max_calls"), "used": requests_used(ctx), "need": int(b.get("need") or 0),
            "launches": launches(ctx.state)}


def budget_binds(ctx, need=None):
    """True while budget.max_calls refuses a launch that can send up to `need` backend requests (default: what the
    launch the cap refused needed, budget.need): requests_used + need > max_calls."""
    b = ctx.state.get("budget") or {}
    cap = b.get("max_calls")
    if not cap:
        return False
    if need is None:
        need = int(b.get("need") or 1)
    return requests_used(ctx) + int(need) > int(cap)


def budget_line(ctx):
    b = budget_status(ctx)
    return ("Requests sent: %d of %s (budget.max_calls); job launches: %d.%s"
            % (b["used"], b["max_calls"], b["launches"],
               (" The next job can send up to %d requests." % b["need"]) if b["need"] else ""))
