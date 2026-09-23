"""pipeline.json interpreter and the driver loop (KIT_SPEC 6.3, 6.11).

advance(ctx, steps, wait_s) runs SCRIPT steps in-process, dispatches DISPATCH jobs as detached workers (B2
ublib.batch), and returns one card: AUTO while jobs run (after at most wait_s seconds), HUMAN at a gate, HOST for a
host task, HOST_BATCH when only host-backend jobs remain, DONE or BLOCKED. Workers outlive the call; a later call
collects their results through the content-addressed done rule (4.4), so nothing finished is ever lost.

B2 runtime modules are reached only through Deps (tests pass fakes).
"""

import copy
import json
import math
import os
import re
import sys
import time

from .. import textio
from . import (BS_PY, PIPELINE_FILE, EngineError, base_family, is_alt)
from . import builders
from . import cards
from . import gates
from . import privacy as privacy_mod
from . import progress
from . import registry
from . import state as st

POLL_S = 2.0
MAX_RELAUNCH = 3
HOST_JOB_MAX_INVALID = 2


# ================================================================ dependencies

class Deps(object):
    """B2 runtime access: batch (worker launch and state), bs.py, detect, families config. All lazy."""

    def __init__(self, batch=None, bs=None, detect=None, families_cfg=None, now=None, sleep=None):
        self._batch = batch
        self._bs = bs
        self._detect = detect
        self._cfg = families_cfg
        self.now = now or time.time
        self.sleep = sleep or time.sleep
        self._cfg_cache = None

    @property
    def batch(self):
        if self._batch is None:
            try:
                from .. import batch as _b  # B2
            except ImportError as e:
                raise EngineError("the worker module ublib/batch.py is missing (%s)" % e,
                                  fix=["reinstall the kit: install.py update"])
            self._batch = _b
        return self._batch

    def bs(self, args, run_dir=None):
        if self._bs is not None:
            return self._bs(args, run_dir)
        if not os.path.exists(BS_PY):
            raise EngineError("scripts/bs.py is missing", fix=["reinstall the kit: install.py update"])
        from .. import proc
        res = proc.run([sys.executable, BS_PY] + [str(a) for a in args], cwd=run_dir or None, timeout_s=900)
        return res.returncode, textio.decode_bytes(res.stdout_bytes), textio.decode_bytes(res.stderr_bytes)

    def detect(self, live=False, only=None):
        if self._detect is not None:
            return self._detect(live=live, only=only)
        try:
            from .. import detect as _d  # B2
            from .. import families as _f  # B2
        except ImportError as e:
            raise EngineError("the detection module ublib/detect.py is missing (%s)" % e,
                              fix=["reinstall the kit: install.py update"])
        return _d.detect(cfg=_f.load_families(), live=live, only=only)

    def families_cfg(self):
        if self._cfg is not None:
            return self._cfg() if callable(self._cfg) else self._cfg
        if self._cfg_cache is None:
            try:
                from .. import families as _f  # B2
                self._cfg_cache = _f.load_families()
            except Exception:
                self._cfg_cache = {}
        return self._cfg_cache


# ================================================================ pipeline data

_CACHE = {}


def load_steps(path=None):
    path = path or PIPELINE_FILE
    if path not in _CACHE:
        try:
            data = textio.read_json(path)
        except (OSError, ValueError) as e:
            raise EngineError("scripts/pipeline.json is unreadable: %s" % e)
        steps = data.get("steps") if isinstance(data, dict) else None
        if not steps:
            raise EngineError("scripts/pipeline.json has no steps")
        _CACHE[path] = steps
    return _CACHE[path]


def index_of(steps, sid):
    for i, s in enumerate(steps):
        if s["id"] == sid:
            return i
    raise EngineError("unknown step %s" % sid)


def step_by_id(steps, sid):
    return steps[index_of(steps, sid)]


# ================================================================ current step

def current_step(ctx, steps):
    """The first step that is not done or skipped; steps whose `when` fails are marked skipped on the way."""
    for s in steps:
        state = st.step_state(ctx.state, s["id"])
        if state in ("done", "skipped"):
            continue
        if state == "pending":
            if not registry.eval_when(ctx, s.get("when")):
                st.set_step(ctx.state, s["id"], "skipped", note="not in this mode/preset")
                continue
        return s
    return None


# ================================================================ simulation (`ub plan`, ETA, golden sequences)

DEFAULT_SIM = {"homogenized": True, "survivors": 7, "k4": False, "footprint": False, "synthesis_stop": False,
               "round2": False, "context_proposed": False, "seeds_given": True}


def simulate(ctx, remaining_only=False, facts=None, with_gates=False):
    """Walk the pipeline without running anything. Returns [{"id","type","kind","count":(lo,hi),"families":{},
    "gate","policy"}] for the steps that would run."""
    sim = dict(DEFAULT_SIM)
    if isinstance(ctx.sim, dict):
        sim.update(ctx.sim)
    if facts:
        sim.update(facts)
    shadow = copy.deepcopy(ctx.state)
    sctx = st.Ctx(ctx.run_dir, shadow, ctx.deps, sim=sim)
    steps = load_steps()
    out = []
    for s in steps:
        cur = st.step_state(shadow, s["id"])
        if cur in ("done", "skipped"):
            if not remaining_only:
                if cur == "done":
                    out.append(_sim_item(sctx, s))
            continue
        if not registry.eval_when(sctx, s.get("when")):
            st.set_step(shadow, s["id"], "skipped")
            continue
        item = _sim_item(sctx, s)
        out.append(item)
        st.set_step(shadow, s["id"], "done")
        if s.get("type") == "HUMAN" and s.get("gate"):
            st.record_gate(shadow, s["gate"], "answered", "sim", {})
    return out if with_gates else [i for i in out if i["type"] == "DISPATCH"]


def _sim_item(sctx, s):
    item = {"id": s["id"], "type": s.get("type"), "kind": (s.get("job") or {}).get("kind") or s.get("kind"),
            "count": (0, 0), "families": {}, "gate": s.get("gate"), "policy": None}
    if s.get("type") == "DISPATCH":
        lo, hi = registry.fanout_count(sctx, s.get("fanout") or "single")
        if s.get("conditional"):
            lo = 0
        rounds = int(s.get("rounds_" + sctx.mode, 1)) if s.get("loops") else 1
        hi = hi * rounds
        item["count"] = (int(lo), int(hi))
        item["families"] = plan_families(sctx, s, (lo + hi) / 2.0)
    elif s.get("type") == "HUMAN":
        item["policy"] = gates.policy(sctx, s["gate"])
    return item


def plan_families(ctx, step, n):
    seats = ctx.seats
    host = ctx.host_family
    fan = step.get("fanout") or "single"
    pool = None
    if fan == "strategies":
        gens = seats.get("generators") or {}
        pool = [gens[k] for k in sorted(gens) if k not in ("S1",)]
    elif fan == "screen_judges":
        pool = seats.get("screen_judges")
    elif fan == "tournament_prompts":
        pool = seats.get("tournament_judges")
    elif fan in ("shortlist", "evolved"):
        pool = seats.get("checker_pool")
    elif fan in ("redteam_pairs", "rebuttals"):
        pool = seats.get("redteam_rotation")
    elif fan == "arch_authors":
        pool = seats.get("arch_authors")
    elif fan == "arch_judges":
        pool = seats.get("arch_judges")
    elif fan in ("review_lenses", "gap_cells"):
        pool = seats.get("others") or [host + "-alt"]
    elif fan == "proposal_review":
        prop = seats.get("proposal") or {}
        pool = list(prop.get("rubric") or []) + ([prop.get("redteam")] if prop.get("redteam") else [])
    elif fan == "quick_gen":
        pool = [host] + (seats.get("others") or [host + "-alt"])[:1]
    elif fan == "ground":
        pool = (seats.get("researcher") or [host])[:1]
    elif fan == "ground2":
        pool = (seats.get("researcher") or [host, host])[1:2]
    pool = [p for p in (pool or [host]) if p] or [host]
    out = {}
    for i in range(int(round(n))):
        f = pool[i % len(pool)]
        out[f] = out.get(f, 0) + 1
    return out


# ================================================================ the driver loop

def advance(ctx, steps, wait_s=0, lock=None):
    """Run until a card is ready or wait_s seconds pass. Always saves state and returns a card."""
    deps = ctx.deps
    deadline = deps.now() + max(0, int(wait_s or 0))
    last_beat = deps.now()
    guard = 0
    while True:
        guard += 1
        if guard > 5000:
            raise EngineError("the engine made no progress (internal loop guard)")
        try:
            card, waiting = step_once(ctx, steps)
        except privacy_mod.PolicyBlock as e:
            cur = current_step(ctx, steps)
            if cur:
                st.set_step(ctx.state, cur["id"], "blocked", note="refused by %s" % e.rule)
            card = cards.blocked(ctx, "BLOCKED by the %s rule: %s" % (e.rule, e), fix=[
                "fix the named input file, then: %s" % cards.next_cmd(ctx.state, ctx.run_dir)], error=str(e),
                step=cur)
            waiting = False
        except EngineError as e:
            cur = current_step(ctx, steps)
            if cur:
                st.set_step(ctx.state, cur["id"], "blocked", note=str(e)[:200])
            card = cards.blocked(ctx, e.say or str(e), fix=e.fix, error=str(e), step=cur)
            waiting = False
        ours = getattr(lock, "still_ours", None) if lock is not None else None
        if ours is not None and not ours():
            # another driver took the lock: stop without saving, so its run.json writes are not overwritten
            return cards.blocked(ctx, "another session took over this run; this one stopped without saving",
                                 fix=[cards.next_cmd(ctx.state, ctx.run_dir)], error="driver lock lost",
                                 step=current_step(ctx, steps))
        st.save(ctx.run_dir, ctx.state)
        if card is not None:
            return finalize(ctx, steps, card)
        if lock is not None and deps.now() - last_beat > 20:
            lock.beat()
            last_beat = deps.now()
        if waiting:
            remaining = deadline - deps.now()
            if remaining <= 0:
                cur = current_step(ctx, steps)
                c = cards.auto(ctx, cur, say_for(ctx, cur))
                return finalize(ctx, steps, c)
            deps.sleep(min(POLL_S, remaining))


def finalize(ctx, steps, card):
    cur = current_step(ctx, steps) if card.get("type") not in ("DONE",) else None
    nxt = next_text(card)
    try:
        block = progress.write_progress(ctx, steps, cur, nxt)
    except Exception:
        block = None
    if card.get("progress") is None:
        card["progress"] = block
    st.save(ctx.run_dir, ctx.state)
    st.write_last_card(ctx.run_dir, card)
    st.append_event(ctx.run_dir, "card", type=card.get("type"), step=card.get("step"), gate=card.get("gate"))
    return card


def next_text(card):
    t = card.get("type")
    if t == "HUMAN":
        return "your turn - %s (%s)" % (gates.TITLES.get(card.get("gate"), ""), card.get("gate"))
    if t == "HOST":
        return "host task %s" % card.get("step")
    if t == "HOST_BATCH":
        return "host sub-agents run %d jobs" % len(card.get("jobs") or [])
    if t == "DONE":
        return "done"
    if t == "BLOCKED":
        return "blocked - see the card"
    return "working (unattended)"


def say_for(ctx, step, extra=None):
    if step is None:
        return "Working."
    stage = int(step.get("stage", 0))
    title = step.get("title") or cards.stage_title(stage)
    sst = (ctx.state.get("steps") or {}).get(step["id"]) or {}
    jobs = sst.get("jobs") or []
    base = "Stage %d %s: %s" % (stage, cards.stage_title(stage), title)
    if jobs:
        done = 0
        for jid in jobs:
            job = builders.load_job(ctx, jid) or {}
            meta = ctx.read_json((job.get("out") or "") + ".meta.json", {}) or {}
            if meta.get("id") == jid and meta.get("status") == "ok":
                done += 1
        base += " (%d of %d jobs done)" % (done, len(jobs))
    return base + (". " + extra if extra else ".")


def step_once(ctx, steps):
    """One unit of progress. Returns (card or None, waiting)."""
    s = ctx.state
    if s.get("status") == "stopped":
        reason = s.get("stopped_reason") or "stopped"
        if "budget" in reason:
            return cards.blocked(ctx, "The run stopped at its call cap.", fix=[
                "%s config set budget.%s <calls>  (or raise it in run.json budget.max_calls)" % (
                    cards.runner_of(s), s.get("mode")),
                "%s redo \"%s\" <step> --yes" % (cards.runner_of(s), textio.to_posix(ctx.run_dir))]), False
        return done_card(ctx, stopped=reason), False
    intr = s.get("interrupt")
    if intr and intr.get("gate"):
        return human_card(ctx, None, intr["gate"]), False
    step = current_step(ctx, steps)
    if step is None:
        s["status"] = "done"
        return done_card(ctx), False
    t = step.get("type")
    if t == "SCRIPT":
        return run_script_step(ctx, step), False
    if t == "HUMAN":
        return human_step(ctx, steps, step)
    if t == "HOST":
        return host_step(ctx, step), False
    if t == "DISPATCH":
        return dispatch(ctx, steps, step)
    raise EngineError("step %s has an unknown type %s" % (step["id"], t))


# ---------------------------------------------------------------- SCRIPT

def run_script_step(ctx, step):
    notes = []
    for name in ([step["script"]] if step.get("script") else []) + list(step.get("after") or []):
        n = registry.run_script(ctx, name, step)
        if n:
            notes.append(n)
    if ctx.cache.pop("rearmed", False):
        return None  # the script re-armed its own loop (another gap round)
    st.set_step(ctx.state, step["id"], "done", note="; ".join(notes)[:300])
    st.append_event(ctx.run_dir, "step_done", step=step["id"])
    return None


# ---------------------------------------------------------------- HUMAN

def human_step(ctx, steps, step):
    gid = step["gate"]
    gstate = st.gate_state(ctx.state, gid)
    if gstate in ("answered", "auto", "skipped"):
        st.set_step(ctx.state, step["id"], "done" if gstate != "skipped" else "skipped")
        return None, False
    pol = gates.policy(ctx, gid)
    if pol == "skip":
        st.record_gate(ctx.state, gid, "skipped", "auto", {})
        if gid == "G8a":
            gates.apply(ctx, gid, {"skip": True}, by="auto")
            st.record_gate(ctx.state, gid, "skipped", "auto", {"skip": True})
        st.set_step(ctx.state, step["id"], "skipped", note="%s skipped (%s)" % (gid, ctx.autopilot))
        return None, False
    if pol == "auto":
        ans = gates.merge_answer(gid, gates.default_answer(gid), ctx)
        errs = gates.validate(ctx, gid, ans)
        if not errs:
            effects = gates.apply(ctx, gid, ans, by="auto")
            st.set_step(ctx.state, step["id"], "done", note="%s auto (%s)" % (gid, ctx.autopilot))
            apply_effects(ctx, steps, effects)
            return None, False
    # ask
    if st.step_state(ctx.state, step["id"]) == "pending":
        try:
            os.remove(ctx.path("answers", gid + ".json"))
        except OSError:
            pass
        st.set_step(ctx.state, step["id"], "running")
    if step.get("prelaunch") and registry.eval_when(ctx, step.get("prelaunch_when") or []):
        for pid in step["prelaunch"]:
            pstep = step_by_id(steps, pid)
            if registry.eval_when(ctx, pstep.get("when")):
                res = dispatch(ctx, steps, pstep, launch_only=True)
                if res and res[0] is not None:
                    return res
    return human_card(ctx, step, gid), False


def human_card(ctx, step, gid, error=None):
    show = gates.display(ctx, gid, error=error)
    return cards.human(ctx, step, gid, show, gates.answer_template(gid), gates.default_answer(gid), error=error)


def pending_gate(ctx, steps):
    intr = ctx.state.get("interrupt")
    if intr and intr.get("gate"):
        return intr["gate"], None
    step = current_step(ctx, steps)
    if step and step.get("type") == "HUMAN":
        return step["gate"], step
    return None, step


def answer_gate(ctx, steps, gid, provided, lock=None, by="human"):
    """`ub answer`: validate, archive, apply, then continue (wait 0)."""
    pgid, step = pending_gate(ctx, steps)
    if pgid != gid:
        card = advance(ctx, steps, 0, lock)
        card.setdefault("notes", []).append("%s is not the gate waiting for an answer (%s is)" % (gid, pgid or
                                                                                                  "none"))
        return card
    ans = gates.merge_answer(gid, provided, ctx)
    errs = gates.validate(ctx, gid, ans)
    if errs:
        c = human_card(ctx, step, gid, error=errs[0])
        return finalize(ctx, steps, c)
    intr = ctx.state.get("interrupt") or {}
    effects = gates.apply(ctx, gid, ans, by=by)
    if step is not None:
        st.set_step(ctx.state, step["id"], "done", note="%s answered by %s" % (gid, by))
    elif intr.get("gate") == gid and ctx.state.get("interrupt") == intr:
        ctx.state["interrupt"] = None
    st.append_event(ctx.run_dir, "gate_answered", gate=gid, by=by)
    apply_effects(ctx, steps, effects)
    st.save(ctx.run_dir, ctx.state)
    return advance(ctx, steps, 0, lock)


# ---------------------------------------------------------------- effects, reset, supersede

def apply_effects(ctx, steps, effects):
    for eff in effects or []:
        kind = eff[0]
        if kind == "reset":
            reset_steps(ctx, steps, eff[1])
        elif kind == "supersede":
            supersede_from(ctx, steps, eff[1])
        elif kind == "stop":
            ctx.state["status"] = "stopped"
            ctx.state["stopped_reason"] = eff[1]
        elif kind == "interrupt_clear":
            ctx.state["interrupt"] = None
        elif kind == "switch_arch":
            switch_arch(ctx, steps, eff[1])
        elif kind == "switch_idea":
            switch_idea(ctx, steps, eff[1])


def reset_steps(ctx, steps, ids):
    for sid in ids:
        try:
            s = step_by_id(steps, sid)
        except EngineError:
            continue
        st.set_step(ctx.state, sid, "pending", note="reset", jobs=[])
        if s.get("type") == "HUMAN" and s.get("gate"):
            (ctx.state.get("gates") or {}).pop(s["gate"], None)


def step_outputs(ctx, step):
    rel = []
    for jid in ((ctx.state.get("steps") or {}).get(step["id"]) or {}).get("jobs") or []:
        job = builders.load_job(ctx, jid) or {}
        out = job.get("out")
        if out:
            rel += [out, out + ".meta.json", out + ".failed.md"]
        rel += ["jobs/%s.json" % jid, "prompts/%s.prompt.md" % jid, "prompts/%s.host.md" % jid]
    rel += st.expand_globs(ctx.run_dir, step.get("outputs") or [])
    if step.get("type") == "HUMAN" and step.get("gate"):
        rel += ["gates/%s.md" % step["gate"], "answers/%s.json" % step["gate"]]
    return rel


def supersede_from(ctx, steps, sid, stamp=None):
    """Move the outputs of `sid` and every downstream step to _superseded/<ISO>/ and reset them (6.10)."""
    idx = index_of(steps, sid)
    rel = []
    for s in steps[idx:]:
        rel += step_outputs(ctx, s)
    try:
        ctx.deps.batch.stop_all(ctx.run_dir)
    except Exception:
        pass
    moved = st.supersede_paths(ctx.run_dir, rel, stamp)
    reset_steps(ctx, steps, [s["id"] for s in steps[idx:]])
    stage = int(steps[idx].get("stage", 0))
    c = ctx.state.setdefault("counters", {})
    if stage <= 5:
        for k in ("gap_rounds", "gap_prefix", "reopen_prefix"):
            c[k] = 0
    if stage <= 10:
        ctx.state["ledger_written"] = False
    if stage <= 13:
        ctx.state["signed_off"] = False
    ctx.state["status"] = "active"
    st.append_event(ctx.run_dir, "supersede", step=sid, moved=len(moved))
    return moved


def switch_arch(ctx, steps, label):
    ans = gates.merge_answer("G11", {"choice": label, "accept_recommendation": False,
                                     "notes": "via switch"}, ctx)
    gates.apply(ctx, "G11", ans, by="human")
    ctx.state["gates"]["G11"]["via"] = "switch"
    supersede_from(ctx, steps, "12.10")


def switch_idea(ctx, steps, iid):
    old = (ctx.state.get("choice") or {}).get("idea")
    ctx.state["choice"]["idea"] = iid
    if old and old != iid and not (ctx.state.get("choice") or {}).get("runner_up"):
        ctx.state["choice"]["runner_up"] = old
    dec = ctx.read("08_DECISION.md")
    ctx.write("08_DECISION.md", dec.rstrip() + "\nSwitched (%s): chosen idea %s -> %s (the user asked to switch)\n"
              % (textio.now_iso(), old, iid))
    supersede_from(ctx, steps, "12.1")


# ---------------------------------------------------------------- HOST

def host_step(ctx, step):
    h = step.get("host") or {}
    name = h.get("template")
    tpl_path = registry.template_path(name, "host")
    arg_rel = "prompts/%s.host-task.md" % step["id"]
    skills = h.get("skills") or []
    comps = ctx.state.get("components") or {}
    comp = comps.get(skills[0]) if skills else None
    # the second named skill (FRAME-GRILL-DOCS: domain-modeling) goes into COMPONENT_NAME; else the first
    comp_name = (comps.get(skills[1]) if len(skills) > 1 else comp) or ""
    jc = {"family": ctx.host_family, "template": name, "vars": {"COMPONENT_NAME": comp_name},
          "item": {"tools": "none"}}
    if step["id"] == "10.3f":
        jc["vars"]["IDEA_ID"] = forge_idea(ctx)
    arg = builders.host_argument(ctx, name, jc)
    if arg is not None:
        ctx.write(arg_rel, arg)
    writes = [textio.to_posix(ctx.path(w)) for w in host_writes(ctx, step)]
    task = {"template": textio.to_posix(tpl_path), "skill": comp, "argument_file": textio.to_posix(ctx.path(arg_rel)),
            "writes": writes,
            "done_cmd": '%s done "%s" %s --json' % (cards.runner_of(ctx.state), textio.to_posix(ctx.run_dir),
                                                    step["id"])}
    if st.step_state(ctx.state, step["id"]) == "pending":
        st.set_step(ctx.state, step["id"], "running")
    return cards.host(ctx, step, task, h.get("say") or "Host task: %s. Follow the template in this conversation, "
                                                           "then run done_cmd." % (step.get("title") or name))


def forge_idea(ctx):
    """The idea the deep-mode FORGE host task pressure-tests: the gut pick #1 when it is in the top set, else the
    first top idea."""
    top = ctx.state.get("top") or ctx.state.get("finalists") or []
    gut = registry.gut_picks(ctx)
    if gut and gut[0] in top:
        return gut[0]
    return top[0] if top else (registry.chosen_idea(ctx) or "I-001")


def host_writes(ctx, step):
    """Run-relative files a HOST step must write ({IDEA} = the forge idea)."""
    out = []
    for w in (step.get("host") or {}).get("writes") or []:
        if "{IDEA}" in w:
            w = w.replace("{IDEA}", forge_idea(ctx))
        out.append(w)
    return out


def host_done(ctx, steps, sid, lock=None):
    step = step_by_id(steps, sid)
    cur = current_step(ctx, steps)
    if step.get("type") != "HOST" or cur is None or cur["id"] != sid:
        card = advance(ctx, steps, 0, lock)
        card.setdefault("notes", []).append("step %s is not waiting for a host task" % sid)
        return card
    missing = []
    for w in host_writes(ctx, step):
        p = ctx.path(w)
        if not os.path.exists(p) or not os.path.getsize(p):
            missing.append(w)
    if missing and (step.get("host") or {}).get("optional"):
        # The host could not run the component (for example ce-ideate missing): the engine path takes over.
        st.set_step(ctx.state, sid, "skipped", note="host task produced no output; engine fallback used")
        st.add_note(ctx.state, "%s: no output from the host task; the engine fallback runs instead" % sid)
        st.save(ctx.run_dir, ctx.state)
        return advance(ctx, steps, 0, lock)
    if missing:
        c = host_step(ctx, step)
        c["error"] = "these files are missing or empty: %s" % ", ".join(missing)
        return finalize(ctx, steps, c)
    for name in step.get("after") or []:
        registry.run_script(ctx, name, step)
    st.set_step(ctx.state, sid, "done", note="host task done")
    st.save(ctx.run_dir, ctx.state)
    return advance(ctx, steps, 0, lock)


# ---------------------------------------------------------------- DISPATCH

def parse_min_ok(spec, n):
    if n <= 0:
        return 0
    if spec is None or spec == "all":
        return n
    if isinstance(spec, int):
        return min(spec, n)
    s = str(spec)
    if "/" in s:
        a, b = s.split("/", 1)
        return min(n, int(math.ceil(n * float(a) / float(b))))
    return min(int(s), n)


def _limits(ctx):
    cfg = {}
    try:
        cfg = ctx.deps.families_cfg() or {}
    except Exception:
        cfg = {}
    parallel = int((cfg.get("defaults") or {}).get("parallel", 4))
    fam_limits = dict((f, int((v or {}).get("limit", 3))) for f, v in (cfg.get("families") or {}).items())
    return parallel, fam_limits


def _relaunch_count(ctx, job, reset=False):
    """Relaunches of a dead job for its CURRENT prompt hash. B2's batch.launch_job counts them in
    .ub/jobs/<id>.relaunch ({prompt_sha256, count, at}); reset removes the counter (a BLOCKED step is retried)."""
    path = ctx.path(".ub", "jobs", "%s.relaunch" % job["id"])
    if reset:
        try:
            os.remove(path)
        except OSError:
            pass
        return 0
    fn = getattr(ctx.deps.batch, "relaunch_count", None)
    if fn is not None:
        try:
            return int(fn(ctx.run_dir, job) or 0)
        except Exception:
            pass
    try:
        data = textio.read_json(path) or {}
    except (OSError, ValueError):
        return 0
    if data.get("prompt_sha256") and data.get("prompt_sha256") != _prompt_sha(ctx, job):
        return 0
    return int(data.get("count") or 0)


def _prompt_sha(ctx, job):
    p = ctx.path(job.get("prompt_file") or "")
    try:
        return textio.sha256_file(p)
    except OSError:
        return "missing"


def host_job_state(ctx, job):
    """done | pending | invalid for jobs whose family resolves to the host (HOST_BATCH)."""
    meta = ctx.read_json(job["out"] + ".meta.json", None) or {}
    sha = _prompt_sha(ctx, job)
    if meta.get("id") == job["id"] and meta.get("status") == "ok" and meta.get("prompt_sha256") == sha:
        return "done"
    if meta.get("id") == job["id"] and meta.get("status") not in (None, "ok"):
        return "failed"
    if not ctx.exists(job["out"]):
        return "pending"
    from .. import filesproto, validate
    text = ctx.read(job["out"])
    ok, errors, parsed = validate.check_contract(text, job.get("contract"), ctx.run_dir)
    split = job.get("split")
    if ok and split:
        res = filesproto.split_output(text, ctx.path(split["root"]), split.get("allowed") or [],
                                      ctx.path(split["status_out"]) if split.get("status_out") else None,
                                      (job.get("contract") or {}).get("required"),
                                      bool((job.get("contract") or {}).get("status_trailer")))
        ok, errors = res["ok"], res["errors"]
    now = textio.now_iso()
    rec = {"schema": 1, "id": job["id"], "family": job.get("family"), "vendor": privacy_mod.family_vendor(
        job.get("family")), "backend": "host", "model": None, "tier": job.get("tier"),
        "provisional": bool(job.get("provisional")), "status": "ok" if ok else "invalid", "attempts": 1,
        "exit_code": 0 if ok else 5, "error_class": None if ok else "bad_output", "started": now,
        "duration_s": None, "prompt_sha256": sha, "out_sha256": textio.sha256_text(text),
        "usage": {"input_tokens": None, "output_tokens": None, "cost_usd": None, "source": "none"},
        "tools": job.get("tools"), "web_used": False, "cwd": job.get("cwd"), "repaired": False,
        "cmd": "host sub-agent", "stderr_tail": ""}
    if ok:
        textio.write_json_atomic(ctx.path(job["out"] + ".meta.json"), rec)
        line = dict(rec, ts=now)
        textio.append_line(ctx.path("logs", "calls.jsonl"), json.dumps(line, ensure_ascii=True))
        return "done"
    counts = ctx.state.setdefault("host_invalid", {})
    counts[job["id"]] = int(counts.get(job["id"], 0)) + 1
    st.add_note(ctx.state, "host output for %s was invalid: %s" % (job["id"], "; ".join(errors)[:200]))
    if counts[job["id"]] >= HOST_JOB_MAX_INVALID:
        textio.write_json_atomic(ctx.path(job["out"] + ".meta.json"), rec)
        textio.write_text_atomic(ctx.path(job["out"] + ".failed.md"),
                                 "FAMILY CALL FAILED: host output invalid: %s\n" % "; ".join(errors)[:1000])
        return "failed"
    st.supersede_paths(ctx.run_dir, [job["out"]])
    return "pending"


def _job_state(ctx, job):
    if ctx.is_host_chain(job.get("family")):
        return host_job_state(ctx, job)
    try:
        return ctx.deps.batch.job_state(ctx.run_dir, job)
    except EngineError:
        raise
    except Exception as e:
        raise EngineError("could not read the state of job %s: %s" % (job.get("id"), e))


def _family_usable(ctx, label):
    if base_family(label) == ctx.host_family:
        return True
    info = (ctx.state.get("families") or {}).get(base_family(label)) or {}
    return info.get("status") == "ok" and st.family_allowed(ctx.state, base_family(label))


def dispatch(ctx, steps, step, launch_only=False):
    """Returns (card or None, waiting)."""
    sid = step["id"]
    sst = (ctx.state.get("steps") or {}).get(sid) or {}
    if sst.get("state") == "blocked":
        _retry_blocked(ctx, step, sst)
        sst = (ctx.state.get("steps") or {}).get(sid) or {}
    jobs = []
    ids = list(sst.get("jobs") or [])
    if ids:
        for jid in ids:
            j = builders.load_job(ctx, jid)
            if j is None:
                jobs = []
                break
            jobs.append(j)
    if not jobs:
        jobs = builders.build_jobs(ctx, step)
        ids = [j["id"] for j in jobs]
        st.set_step(ctx.state, sid, "running", jobs=ids, originals=ids[:])
        sst = ctx.state["steps"][sid]
        if not jobs:
            st.set_step(ctx.state, sid, "done", note="nothing to dispatch")
            for name in step.get("after") or []:
                registry.run_script(ctx, name, step)
            return None, False
    elif sst.get("state") == "pending":
        st.set_step(ctx.state, sid, "running")
    # A job that already has a fallback copy is final: the copy writes the same <out> and meta, so the original is
    # never relaunched (it would overwrite the copy's result and the two would ping-pong).
    replaced = set((sst.get("fallback_of") or {}).values())
    states = dict((j["id"], "failed" if j["id"] in replaced else _job_state(ctx, j)) for j in jobs)
    parallel, fam_limits = _limits(ctx)
    try:
        live = set(ctx.deps.batch.running_jobs(ctx.run_dir) or [])
    except Exception:
        live = set(j for j, s_ in states.items() if s_ == "running")
    running_total = len(live | set(j for j, s_ in states.items() if s_ == "running"))
    fam_running = {}
    for j in jobs:
        if states[j["id"]] == "running":
            fb = base_family(j["family"])
            fam_running[fb] = fam_running.get(fb, 0) + 1
    for j in jobs:
        jid = j["id"]
        s_ = states[jid]
        if ctx.is_host_chain(j.get("family")) or s_ not in ("pending", "dead"):
            continue
        fb = base_family(j["family"])
        if running_total >= parallel or fam_running.get(fb, 0) >= fam_limits.get(fb, 3):
            continue
        if s_ == "dead":
            n = _relaunch_count(ctx, j)
            if n >= MAX_RELAUNCH:
                st.set_step(ctx.state, sid, "blocked", note="job %s relaunched %d times" % (jid, n))
                return cards.blocked(ctx, relaunch_message(ctx), fix=[
                    '%s run --continue "%s"' % (cards.runner_of(ctx.state), textio.to_posix(ctx.run_dir)),
                    "raise the command timeout (references/hosts.md)"], step=step), False
        elif progress.over_budget(ctx.state):
            if ctx.autopilot == "full-auto":
                ctx.state["status"] = "stopped"
                ctx.state["stopped_reason"] = "budget cap reached (%s calls)" % ctx.state["budget"]["max_calls"]
                return cards.blocked(ctx, "The run reached its call cap (%s calls)." % ctx.state["budget"][
                    "max_calls"], fix=["raise budget.max_calls in run.json, then: %s" % cards.next_cmd(
                        ctx.state, ctx.run_dir)], step=step), False
            ctx.state["interrupt"] = {"gate": "GB", "step": sid}
            return human_card(ctx, step, "GB"), False
        info = ctx.deps.batch.launch_job(ctx.path("jobs", jid + ".json")) or {}
        if info.get("launched") is False and info.get("state") == "stuck":
            # the dead job's old worker still runs and could not be stopped: waiting would never end
            st.set_step(ctx.state, sid, "blocked", note="job %s: old worker (pid %s) could not be stopped" % (
                jid, info.get("pid")))
            return cards.blocked(ctx, "Job %s has an old worker (pid %s) that is still running and could not be "
                                 "stopped, so it cannot be relaunched." % (jid, info.get("pid")), fix=[
                                     '%s stop "%s"' % (cards.runner_of(ctx.state), textio.to_posix(ctx.run_dir)),
                                     '%s run --continue "%s"' % (cards.runner_of(ctx.state),
                                                                 textio.to_posix(ctx.run_dir))], step=step), False
        if info.get("launched") is False:
            # launch_job re-checks under the job's execution lock: the job finished or another worker holds it since
            # the states above were read. Nothing started, so nothing is counted against the budget.
            states[jid] = "done" if info.get("state") == "done" else "running"
            if states[jid] == "running":
                running_total += 1
                fam_running[fb] = fam_running.get(fb, 0) + 1
            st.append_event(ctx.run_dir, "launch_skipped", job=jid, state=states[jid])
            continue
        c = ctx.state.setdefault("counters", {})
        c["launched"] = int(c.get("launched", 0)) + 1
        states[jid] = "running"
        running_total += 1
        fam_running[fb] = fam_running.get(fb, 0) + 1
        st.append_event(ctx.run_dir, "launch", job=jid, family=j.get("family"), relaunch=(s_ == "dead"))
    if launch_only:
        return None, False
    # fallbacks for failed jobs (4.4 / 5.4): a PROVISIONAL copy on the next usable fallback family
    originals = list(sst.get("originals") or ids)
    fb_of = dict(sst.get("fallback_of") or {})
    added = False
    handled = set()
    for j in list(jobs):
        if states.get(j["id"]) != "failed" or j["id"] in (sst.get("exhausted") or []):
            continue
        root = fb_of.get(j["id"], j["id"])
        if root in handled:
            continue
        handled.add(root)
        tried = [x for x, r in fb_of.items() if r == root]
        if any(states.get(t) in ("pending", "running", "dead", "done") for t in tried):
            continue
        rootjob = next((x for x in jobs if x["id"] == root), j)
        used = set([rootjob.get("family")] + [next((x for x in jobs if x["id"] == t), {}).get("family") for t in
                                               tried])
        cand = [f for f in (rootjob.get("fallback") or []) if f not in used and _family_usable(ctx, f)]
        if not cand:
            sst.setdefault("exhausted", []).append(j["id"])
            continue
        fam = cand[0]
        reason = _failure_reason(ctx, j)
        new = builders.fallback_job(ctx, step, rootjob, fam)
        # the copy writes the same <out>: the failed attempt's meta moves to _superseded/ (its <out>.failed.md stays,
        # so the failure is never silent), otherwise the copy would read as already failed
        st.supersede_paths(ctx.run_dir, [j["out"] + ".meta.json"], "%s-%s" % (st.iso_stamp(), new["id"]))
        jobs.append(new)
        states[new["id"]] = "pending"
        fb_of[new["id"]] = root
        sst["jobs"] = sst.get("jobs", []) + [new["id"]]
        st.add_provisional(ctx.state, step.get("title") or sid, rootjob.get("family"), fam, reason)
        st.add_note(ctx.state, "%s: %s failed (%s); PROVISIONAL %s used instead" % (
            sid, rootjob.get("family"), reason, fam))
        added = True
    sst["fallback_of"] = fb_of
    if added:
        return None, False
    host_pending = [j for j in jobs if ctx.is_host_chain(j.get("family")) and states[j["id"]] == "pending"]
    others_unlaunched = [j for j in jobs if not ctx.is_host_chain(j.get("family")) and
                         states[j["id"]] in ("pending",)]
    if host_pending and not others_unlaunched:
        return host_batch_card(ctx, step, host_pending), False
    if any(v in ("pending", "running", "dead") for v in states.values()):
        return None, True
    # every job is final
    ok_roots = set()
    for j in jobs:
        if states[j["id"]] == "done":
            ok_roots.add(fb_of.get(j["id"], j["id"]))
    n = len(originals)
    need = parse_min_ok(step.get("min_ok"), n)
    if len([r for r in originals if r in ok_roots]) < need:
        st.set_step(ctx.state, sid, "blocked", note="%d of %d jobs succeeded; %d needed" % (len(ok_roots), n, need))
        return blocked_for_failures(ctx, step, [j for j in jobs if states[j["id"]] == "failed"],
                                    len(ok_roots), n, need), False
    crash = os.environ.get("UB_TEST_CRASH_AT")  # test hook (4.19)
    if crash and crash == sid:
        st.save(ctx.run_dir, ctx.state)
        sys.stdout.flush()
        os._exit(99)
    notes = []
    for name in step.get("after") or []:
        r = registry.run_script(ctx, name, step)
        if r:
            notes.append(r)
    st.set_step(ctx.state, sid, "done", note=("%d/%d ok" % (len(ok_roots), n)) + ("; " + "; ".join(notes)
                                                                                    if notes else ""))
    st.append_event(ctx.run_dir, "step_done", step=sid)
    return None, False


def _retry_blocked(ctx, step, sst):
    """A BLOCKED dispatch step is retried on the next call: failed outputs move to _superseded, counters reset."""
    rel = []
    for jid in sst.get("jobs") or []:
        job = builders.load_job(ctx, jid) or {}
        out = job.get("out")
        meta = ctx.read_json((out or "") + ".meta.json", {}) or {}
        if out and meta.get("status") not in (None, "ok"):
            rel += [out + ".meta.json", out + ".failed.md"]
        if job:
            _relaunch_count(ctx, job, reset=True)
    st.supersede_paths(ctx.run_dir, rel)
    keep = [j for j in sst.get("originals") or sst.get("jobs") or []]
    st.set_step(ctx.state, step["id"], "running", jobs=keep, fallback_of={}, exhausted=[], originals=keep)
    (ctx.state.get("host_invalid") or {}).clear()


def _failure_reason(ctx, job):
    meta = ctx.read_json(job["out"] + ".meta.json", {}) or {}
    if meta.get("error_class"):
        return "%s (%s)" % (meta.get("status"), meta.get("error_class"))
    first = registry.first_line(ctx.read(job["out"] + ".failed.md"))
    return first.replace("FAMILY CALL FAILED:", "").strip() or meta.get("status") or "failed"


def blocked_for_failures(ctx, step, failed, ok, n, need):
    runner = cards.runner_of(ctx.state)
    fixes = []
    classes = set()
    for j in failed:
        meta = ctx.read_json(j["out"] + ".meta.json", {}) or {}
        ec = meta.get("error_class")
        fam = base_family(j.get("family"))
        classes.add(ec)
        if ec == "auth":
            fixes.append("log in again for the %s family (for example: %s), then continue" % (
                fam, {"gpt": "codex login", "kimi": "kimi login", "claude": "run claude once and sign in"}.get(
                    fam, "check its key")))
        elif ec == "not_found":
            fixes.append("install the %s CLI (install.py install --with-clis ...), then continue" % fam)
        elif ec == "sandbox_network":
            fixes.append("Codex: approve network access for the ub command prefix (references/hosts.md)")  # [U-8]
        elif ec == "policy":
            fixes.append("privacy settings refuse this call; see references/families.md")
    fixes += ["%s doctor --json" % runner, cards.next_cmd(ctx.state, ctx.run_dir, 0) + "   (retries the step)",
              '%s redo "%s" %s --yes' % (runner, textio.to_posix(ctx.run_dir), step["id"])]
    seen, out = set(), []
    for f in fixes:
        if f not in seen:
            seen.add(f)
            out.append(f)
    say = "Stage %s %s: only %d of %d model calls succeeded (%d needed). Failures: %s." % (
        step.get("stage"), step.get("title"), ok, n, need,
        ", ".join("%s (%s)" % (j["id"], _failure_reason(ctx, j)) for j in failed[:6]) or "none")
    return cards.blocked(ctx, say, fix=out, step=step)


def relaunch_message(ctx):
    return ("Your agent stops background work before model calls finish. Run this in a terminal instead: "
            '`%s run --continue "%s"` (it asks the remaining questions there), or raise the command timeout (see '
            "references/hosts.md)." % (cards.runner_of(ctx.state), textio.to_posix(ctx.run_dir)))


def host_batch_card(ctx, step, jobs):
    items = []
    for j in jobs:
        items.append({"id": j["id"], "prompt_file": textio.to_posix(ctx.path(j.get("host_prompt_file") or
                                                                           j["prompt_file"])),
                      "out": textio.to_posix(ctx.path(j["out"])), "tools": j.get("tools", "none")})
    say = ("Run %d job(s) for %s in fresh sub-agents: each reads its prompt file and writes only its output file."
           % (len(items), step.get("title") or step["id"]))
    return cards.host_batch(ctx, step, items, say)


# ---------------------------------------------------------------- DONE

# How the user reaches the skill from each agent host (the DONE card names this, not a `ub` the host has no PATH to).
HOST_ENTRY = {"claude-code": "/ultimate-brainstorm", "codex": "$ultimate-brainstorm", "zcode": "$ultimate-brainstorm",
              "kimi": "/skill:ultimate-brainstorm"}


def done_card(ctx, stopped=None):
    s = ctx.state
    links = {}
    for key, rel in (("proposal", "11_PROPOSAL/PROPOSAL.md"), ("pack", "11_PROPOSAL/index.html"),
                     ("architecture", "10_ARCHITECTURE/README.md"), ("handoff", "12_HANDOFF.md"),
                     ("decision", "08_DECISION.md"), ("progress", "PROGRESS.md")):
        if ctx.exists(rel):
            links[key] = textio.to_posix(ctx.path(rel))
    ch = s.get("choice") or {}
    info = registry.idea_lines(ctx).get(ch.get("idea") or "", {})
    lines = ["ultimate-brainstorm run %s: %s" % (s.get("run"), "stopped (%s)" % stopped if stopped else "done"),
             "Topic: %s" % s.get("topic", "")]
    if ch.get("idea"):
        lines.append("Decision: %s %s%s" % (ch["idea"], info.get("title", ""),
                                            " (AUTO-DECISION)" if (s.get("gates", {}).get("G8b") or {}).get(
                                                "by") == "auto" else ""))
    if ch.get("arch"):
        lines.append("Architecture: candidate %s (%s)" % (ch["arch"], ch.get("arch_family")))
    if links.get("proposal"):
        status = "APPROVED" if s.get("signed_off") else ("AUTOPILOT DRAFT" if s.get("autopilot") == "full-auto"
                                                         else "DRAFT")
        lines.append("Proposal: %s (%s)" % (links["proposal"], status))
    probe = ctx.read("09_PROBE.md")
    if "RESULT: PASSED" not in probe:
        design = " ".join((registry.section(probe, "3") or registry.section(probe, "Probe") or "").split())
        design = re.split(r"(?<=[.!?])\s", design, maxsplit=1)[0] if design else ""
        what = "the probe in 09_PROBE.md%s" % ((" (%s)" % design) if design else "")
        agent = (s.get("host") or {}).get("agent") or ""
        entry = HOST_ENTRY.get(agent)
        if entry:
            lines.append("Next: run %s, then type `%s probe passed|missed|inconclusive <what you saw>`"
                         % (what, entry))
        else:
            lines.append("Next: run %s (Milestone 0), then report it: %s probe-result \"%s\" "
                         "PASSED|MISSED|INCONCLUSIVE" % (what, cards.runner_of(s), textio.to_posix(ctx.run_dir)))
    if s.get("provisional"):
        lines.append("PROVISIONAL seats: %d (see run.json provisional)" % len(s["provisional"]))
    s["status"] = "stopped" if stopped else "done"
    return cards.done(ctx, "\n".join(lines) + "\n", links)
