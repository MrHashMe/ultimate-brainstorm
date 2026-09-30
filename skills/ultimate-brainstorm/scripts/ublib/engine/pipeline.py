"""pipeline.json interpreter and the driver loop (KIT_SPEC 6.3, 6.11).

advance(ctx, steps, wait_s) runs SCRIPT steps in-process, dispatches DISPATCH jobs as detached workers (B2
ublib.batch), and returns one card: AUTO while jobs run (after at most wait_s seconds), HUMAN at a gate, HOST for a
host task, HOST_BATCH when only host-backend jobs remain, DONE or BLOCKED. Workers outlive the call; a later call
collects their results through the content-addressed done rule (4.4), so nothing finished is ever lost.

B2 runtime modules are reached only through Deps (tests pass fakes).
"""

import calendar
import copy
import json
import math
import os
import re
import sys
import time

from .. import textio
from . import (BS_PY, PIPELINE_FILE, EngineError, base_family)
from . import builders
from . import cards
from . import gates
from . import privacy as privacy_mod
from . import progress
from . import registry
from . import render
from . import state as st

POLL_S = 2.0
HOST_JOB_MAX_INVALID = 2
HOST_LEASE_S = 3600  # a HOST task handed to one session is not handed to another for this long (or until `continue`)
RELAUNCH_ROUNDS = 2  # a dead job is relaunched at most this many times RELAUNCH_LIMIT for one prompt, retries included
DECISION_MD = "08_DECISION.md"  # an `append` effect to it is a decision line (run.json decision_log)


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

    def request_reserve(self, job):
        """Worst-case backend requests one worker launch of `job` can send (C6: adapter.request_reserve)."""
        from .. import adapter  # B2
        return int(adapter.request_reserve(job, self.families_cfg() or None) or 0)


# ================================================================ pipeline data

_CACHE = {}
STEP_TYPES = ("SCRIPT", "DISPATCH", "HUMAN", "HOST")


def load_data(path=None):
    """pipeline.json, checked once per process (check_data): {"steps": [...], "refs": {...}, "owners": {...}}."""
    path = path or PIPELINE_FILE
    if path not in _CACHE:
        try:
            data = textio.read_json(path)
        except (OSError, ValueError) as e:
            raise EngineError("scripts/pipeline.json is unreadable: %s" % e)
        if not isinstance(data, dict) or not data.get("steps"):
            raise EngineError("scripts/pipeline.json has no steps")
        problems = check_data(data)
        if problems:
            raise EngineError("scripts/pipeline.json is inconsistent: %s" % "; ".join(problems[:5]),
                              fix=["reinstall the kit (engine and pipeline.json versions differ): install.py update"])
        _CACHE[path] = data
    return _CACHE[path]


def load_steps(path=None):
    return load_data(path)["steps"]


def check_data(data):
    """Every step id the data or the engine refers to exists (#15): refs, owners, prelaunch, step_done/step_skipped
    arguments; and every predicate, fanout, script and gate a step names is registered. Returns the problems."""
    steps = data.get("steps") or []
    ids = [s.get("id") for s in steps]
    known = set(ids)
    out = ["duplicate step id %s" % i for i in sorted(set(i for i in ids if ids.count(i) > 1))]

    def need(sid, where):
        if sid not in known:
            out.append("%s names the unknown step %s" % (where, sid))
    for name, ref in (data.get("refs") or {}).items():
        for sid in (ref if isinstance(ref, list) else [ref]):
            need(sid, "refs.%s" % name)
    for key, owners in (data.get("owners") or {}).items():
        for sid in owners:
            need(sid, "owners.%s" % key)
    for s in steps:
        sid = s.get("id")
        if s.get("type") not in STEP_TYPES:
            out.append("step %s has an unknown type %s" % (sid, s.get("type")))
        for pid in s.get("prelaunch") or []:
            need(pid, "step %s prelaunch" % sid)
        for entry in (s.get("when") or []) + (s.get("prelaunch_when") or []):
            for part in str(entry).split("|"):
                name, _, arg = part.strip().lstrip("!").partition(":")
                if name not in registry.PREDICATES:
                    out.append("step %s uses the unknown predicate %s" % (sid, name))
                elif name in ("step_done", "step_skipped"):
                    need(arg, "step %s when" % sid)
        for name in ([s["script"]] if s.get("script") else []) + list(s.get("after") or []):
            if name not in registry.SCRIPTS:
                out.append("step %s names the unknown script %s" % (sid, name))
        if s.get("type") == "DISPATCH" and (s.get("fanout") or "single") not in registry.FANOUTS:
            out.append("step %s names the unknown fanout %s" % (sid, s.get("fanout")))
        if s.get("type") == "HUMAN" and s.get("gate") not in gates.FIELDS:
            out.append("step %s names the unknown gate %s" % (sid, s.get("gate")))
    return out


def step_ref(name, ctx=None):
    """The step id (or list of ids) pipeline.json names under refs; in quick mode <name>_quick when there is one."""
    refs = load_data().get("refs") or {}
    if ctx is not None and ctx.mode == "quick" and name + "_quick" in refs:
        return refs[name + "_quick"]
    if name not in refs:
        raise EngineError("scripts/pipeline.json has no refs.%s" % name,
                          fix=["reinstall the kit (engine and pipeline.json versions differ): install.py update"])
    return refs[name]


def owned_keys(ctx, steps, idx):
    """run.json keys whose owner step (owners in pipeline.json; the quick-mode owner in quick mode) is at or after
    steps[idx] (I10)."""
    out = []
    for key, owners in (load_data().get("owners") or {}).items():
        owner = owners[1] if ctx.mode == "quick" and len(owners) > 1 else owners[0]
        try:
            if index_of(steps, owner) >= idx:
                out.append(key)
        except EngineError:
            continue  # a step list without the owner (a partial list in a test) owns nothing here
    return out


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
        lo, hi = registry.fanout_count(sctx, s.get("fanout") or "single", s)
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
    """Run until a card is ready or wait_s seconds pass, and return the card. The caller holds the driver lock (C1)
    for the whole call (`lock`: the kernel lock cannot be lost while held, but a kit 2.0.3 driver, which knows only
    lock.json, takes the record of a driver that stalled for more than 120 s: lost_lock). The state is saved after
    every unit of progress, a compare-and-swap that writes nothing while nothing changed (C2)."""
    deps = ctx.deps
    deadline = deps.now() + max(0, int(wait_s or 0))
    guard = 0
    while True:
        guard += 1
        if guard > 5000:
            raise EngineError("the engine made no progress (internal loop guard)")
        try:
            card, waiting = step_once(ctx, steps)
        except st.Stale:
            raise  # never turned into a BLOCKED step: the caller re-reads run.json and shows the current card
        except privacy_mod.PolicyBlock as e:
            cur = current_step(ctx, steps)
            if cur:
                st.set_step(ctx.state, cur["id"], "blocked", note="refused by %s" % e.rule)
            # a refusal that names its own way out (a judge prompt a prepare step writes once: redo that step) keeps it
            card = cards.blocked(ctx, "BLOCKED by the %s rule: %s" % (e.rule, e), fix=e.fix or [
                "fix the named input file, then: %s" % cards.next_cmd(ctx.state, ctx.run_dir)], error=str(e),
                step=cur)
            waiting = False
        except EngineError as e:
            cur = current_step(ctx, steps)
            if cur:
                st.set_step(ctx.state, cur["id"], "blocked", note=str(e)[:200])
            card = cards.blocked(ctx, e.say or str(e), fix=e.fix, error=str(e), step=cur)
            waiting = False
        lost = lost_lock(ctx, steps, lock)
        if lost:
            return lost
        st.save(ctx.run_dir, ctx.state)
        if card is not None:
            return finalize(ctx, steps, card)
        if waiting:
            remaining = deadline - deps.now()
            if remaining <= 0:
                cur = current_step(ctx, steps)
                c = cards.auto(ctx, cur, say_for(ctx, cur, ctx.cache.get("waiting_on")))
                if cur and ctx.lease and _lease_state(ctx, (ctx.state.get("steps") or {}).get(cur["id"]) or {}) == \
                        "ours":
                    # the lease holder's next poll must present its token again, or it would wait for itself (#96)
                    c["then"] = cards.next_cmd(ctx.state, ctx.run_dir, lease=ctx.lease)
                return finalize(ctx, steps, c)
            deps.sleep(min(POLL_S, remaining))


def lost_lock(ctx, steps, lock):
    """The BLOCKED card when this driver lost its lock.json record (DriverLock.still_ours: a kit 2.0.3 driver took it
    over while this one was suspended or stalled), else None. The driver then stops without saving, so the other
    driver's run.json writes stand, as kit 2.0.3 did."""
    if lock is None or lock.still_ours():
        return None
    return cards.blocked(ctx, "another session took over this run; this one stopped without saving",
                         fix=[cards.next_cmd(ctx.state, ctx.run_dir)], error="driver lock lost",
                         step=current_step(ctx, steps))


def finalize(ctx, steps, card):
    cur = current_step(ctx, steps) if card.get("type") not in ("DONE",) else None
    if cur and ctx.lease and _lease_state(ctx, (ctx.state.get("steps") or {}).get(cur["id"]) or {}) == "ours":
        # a card to the holder of the step's lease (GB mid-step, a BLOCKED fix): its own answer, budget or next must
        # present the token again, or it would run as another session and wait for its own lease to expire (#96)
        runner = cards.runner_of(ctx.state)
        if card.get("answer_cmd"):
            card["answer_cmd"] = cards.with_lease(card["answer_cmd"], ctx.lease)
        card["fix"] = [cards.with_lease(f, ctx.lease) if any(runner + v in f for v in (" next ", " answer ",
                                                                                         " budget ")) else f
                       for f in card.get("fix") or []]
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
    ctx.cache.pop("waiting_on", None)
    if st.stop_requested(ctx.run_dir) and s.get("status") != "stopped":
        s["status"], s["stopped_reason"] = "stopped", "user"  # C3: `ub stop` asked; this driver stops here
    if s.get("supersede"):
        return supersede_blocked(ctx), False  # I6: nothing runs while moved-aside outputs are still in place
    budget_stop = s.get("status") == "stopped" and "budget" in (s.get("stopped_reason") or "")
    if (budget_stop or (s.get("interrupt") or {}).get("gate") == "GB") and not progress.budget_binds(ctx):
        clear_budget_stop(ctx)  # the cap was raised (`ub budget`): the run goes on by itself (#12)
    if s.get("status") == "stopped":
        reason = s.get("stopped_reason") or "stopped"
        if "budget" in reason:
            return budget_card(ctx, None, "The run stopped at its request cap."), False
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
        return host_step(ctx, step)
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
        ans, _notes, errs = gates.prepare_answer(ctx, gid, gates.default_answer(gid))
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
    rb = gates.pending_readback(ctx, gid) if error else None
    if rb:  # asked again, the card still offers its reading (4.12), which stays pending past this card's save
        error, rb["rev"] = "%s\n\n%s" % (rb.get("say"), error), st._rev(ctx.state) + 1
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


_AMENDS = "Your reply answers my reading and changes it: tell me the whole answer in one reply. "
_PRIVACY_LEFT = "Your last reply leaves out the privacy you asked for: to change it, tell me the whole answer in one " \
    "reply, privacy included."


def answer_gate(ctx, steps, gid, provided, lock=None, by="human"):
    """`ub answer`: type-check and validate (gates.prepare_answer), archive, apply, then continue (wait 0). Nothing is
    applied while a supersede journal is pending (I6): the answer could change what the journal still has to move.
    A free-text reply that is not in a documented form is read back first (gates.read_back, 4.12): its reading waits
    in run.json and the same card asks; confirmation words alone then apply it (a yes the host also wrote into its
    field changes nothing), a yes or no with more words asks for the whole answer, and any other answer replaces it.
    A reading the run moved past stays a marker until the user answers its gate, so a late yes asks again."""
    if ctx.state.get("supersede"):
        return finalize(ctx, steps, supersede_blocked(ctx))
    pgid, step = pending_gate(ctx, steps)
    if pgid != gid:
        card = advance(ctx, steps, 0, lock)
        card.setdefault("notes", []).append("%s is not the gate waiting for an answer (%s is)" % (gid, pgid or
                                                                                                  "none"))
        return card
    held = gates.pending_readback(ctx, gid)
    rb0 = ctx.state.get("readback") or {}
    # a reading of this gate the run moved past (a stop, redo, continue, default answer or another gate) stays in
    # run.json as a marker until the user answers this gate, so a late yes is asked again (4.12)
    stale = rb0.get("gate") == gid or gid in (rb0.get("stale") or [])
    reply = provided if isinstance(provided, str) else provided.get("reply") if isinstance(provided, dict) else None
    ans, notes, errs = gates.prepare_answer(ctx, gid, provided)
    readback, human = None, by == "human" and gates.only_reply(ctx, gid, provided, held)
    if stale and human:
        if held and gates.confirms_reading(reply, held):
            ans, notes, errs, readback = copy.deepcopy(held["answer"]), [], gates.validate(ctx, gid, held["answer"]), \
                "confirmed"
        elif gates.confirms_reading(reply, rb0) or held and gates.refuses_only(reply):
            # a yes to a reading the run has moved past since (or the user changed), or a plain no to the reading:
            # asked again, and the reading is used up
            errs = [("" if held else _AMENDS if rb0.get("amended") else "The reading I showed you is out of date (the "
                     "run changed since): tell me again what you want. ") + gates.how_to_reply(ctx, gid)]
            gates.drop_reading(ctx, gid)
        elif held and gates.approve_beside(reply, held):
            # G13 `approve` to a reading of a switch or a change round, `go` to a v1 stop, G14 `publish` to a reading
            # with a handoff or a narrower list: the reading or the card's?
            errs = ["%s Or reply %s." % (held.get("say") or "", "`go` again to extend this v1 run with an architecture "
                    "package and a full proposal (paid model calls)" if gid == "G0" else "`publish` again to publish "
                    "the architecture, the ADRs and the proposal with no handoff" if gid == "G14" else "`approve` "
                    "again to keep architecture %s as it is" % ((ctx.state.get("choice") or {}).get("arch") or ""))]
            held.update(approve_asked=True, rev=st._rev(ctx.state) + 1)  # still pending after the card's save
        elif held and (gates.amends_reading(reply) or not errs and gates.yes_beside(ctx, gid, reply, ans, held)) \
                and not (not errs and gates.canonical(ctx, gid, ans)):
            # 'yes and also kill I-007', 'no, I meant B': one reply says the whole answer, and the reading the user
            # changed stays a marker only, so a lone yes next asks again instead of applying it
            errs = [_AMENDS + gates.how_to_reply(ctx, gid)]
            held.update(rev=None, amended=True)
            st.save(ctx.run_dir, ctx.state)
        elif held and not errs and gates.drops_privacy(gid, ans, held):
            # 'start' beside "let's go, and keep it private": a new reading would drop the privacy asked for
            errs = ["%s %s" % (held.get("say") or "", _PRIVACY_LEFT)]
            held.update(rev=st._rev(ctx.state) + 1)  # still pending after the card's save
    if errs:  # any other reading stays pending: the card shows it again, and a yes applies it
        c = human_card(ctx, step, gid, error=errs[0])
        c.setdefault("notes", []).extend(notes)
        return finalize(ctx, steps, c)
    say = gates.read_back(ctx, gid, provided, ans) if by == "human" and not readback else None
    if say:
        rb0 = ctx.state.get("readback") or {}  # a reading of another gate stays a marker beside this one
        old = sorted(set(rb0.get("stale") or []) | set([rb0["gate"]] if rb0.get("gate") else []) - set([gid]))
        ctx.state["readback"] = dict({"gate": gid, "step": step["id"] if step else None, "reply": reply, "answer": ans,
                                      "say": say, "interrupt": copy.deepcopy(ctx.state.get("interrupt")),
                                      "rev": st._rev(ctx.state) + 1},  # pending after the save of the card that asks
                                     **({"stale": old} if old else {}))
        st.append_event(ctx.run_dir, "gate_read_back", gate=gid)
        c = human_card(ctx, step, gid, error=say)
        c.setdefault("notes", []).extend(notes)
        return finalize(ctx, steps, c)
    if human:
        gates.drop_reading(ctx, gid)  # the user answered this gate; a default or a host's fields leave the marker
    intr = ctx.state.get("interrupt") or {}
    effects = gates.apply(ctx, gid, ans, by=by)
    if step is not None:
        st.set_step(ctx.state, step["id"], "done", note="%s answered by %s" % (gid, by))
    elif intr.get("gate") == gid and ctx.state.get("interrupt") == intr:
        ctx.state["interrupt"] = None
    st.append_event(ctx.run_dir, "gate_answered", gate=gid, by=by, **({"readback": readback} if readback else {}))
    apply_effects(ctx, steps, effects)
    st.save(ctx.run_dir, ctx.state)
    card = advance(ctx, steps, 0, lock)
    card.setdefault("notes", []).extend(notes)
    return card


# ---------------------------------------------------------------- effects, reset, supersede

def apply_effects(ctx, steps, effects):
    """Effects in order. A line for 08_DECISION.md (a switch, a K6 kill) goes to run.json decision_log in the same save
    as the supersede that commits the change it records (#11: a supersede that refuses, a path too long, leaves no line
    behind that a retry would write a second time). Every rewrite of 08_DECISION.md renders the log (quick Q.8 writes
    the file again after a supersede from Q.6 moved it); the file in place gets the line at once."""
    effects = list(effects or [])
    unlogged = [e[2] for e in effects if e[0] == "append" and e[1] == DECISION_MD]
    for eff in effects:
        kind = eff[0]
        if kind == "reset":
            reset_steps(ctx, steps, eff[1])
        elif kind == "supersede":
            supersede_from(ctx, steps, eff[1], log=unlogged)
            unlogged = []
        elif kind == "append" and eff[1] == DECISION_MD:
            if eff[2] in unlogged:  # no supersede commits it: logged here, saved with the command
                unlogged.remove(eff[2])
                _log_decision(ctx, [eff[2]])
            if ctx.exists(DECISION_MD):
                ctx.write(DECISION_MD, registry.with_decision_log(ctx.read(DECISION_MD), [eff[2]]))
        elif kind == "append":
            ctx.write(eff[1], ctx.read(eff[1]).rstrip() + "\n" + eff[2])
        elif kind == "ledger":
            registry.append_ledger(ctx, eff[1])
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
    """Re-arm steps (a gate effect). A re-armed DISPATCH step first moves its outputs to _superseded/ through the
    journal (I5, I6), so no job, on the worker path or the host path, ever finds its previous output in place."""
    rel = []
    for sid in ids:
        try:
            s = step_by_id(steps, sid)
        except EngineError:
            continue
        if s.get("type") == "DISPATCH":
            rel += step_outputs(ctx, s)
    st.check_supersede_paths(ctx.run_dir, rel)  # before any change (#98)
    _rearm(ctx, steps, ids)
    if rel:
        st.supersede(ctx.run_dir, ctx.state, rel)


def _rearm(ctx, steps, ids, note="reset"):
    """Steps pending again with no jobs (their gates unanswered). A re-run is asked for, so the relaunch counts of
    their jobs start over (a BLOCKED retry never does that: _retry_blocked)."""
    batch = ctx.deps.batch if ctx.deps else None
    for sid in ids:
        try:
            s = step_by_id(steps, sid)
        except EngineError:
            continue
        for jid in ((ctx.state.get("steps") or {}).get(sid) or {}).get("jobs") or []:
            if hasattr(batch, "reset_relaunch"):
                batch.reset_relaunch(ctx.run_dir, jid)
        st.set_step(ctx.state, sid, "pending", note=note, jobs=[])
        if s.get("type") == "HUMAN" and s.get("gate"):
            (ctx.state.get("gates") or {}).pop(s["gate"], None)


def rearm_loop(ctx, ids, note):
    """Another round of a loop group (the gap rounds, refs.gap_loop): its steps are pending again. What a round
    writes again at the same path (the curator's raw merges, a job's meta, failure record, job and prompt files) moves
    to _superseded/ through the journal first (I5, I6); a step marked `accumulates` keeps its outputs, because every
    round writes new ones (the pool keeps each gap round's ideas). The new round is counted when it ends
    (`counters.gap_counted` holds the items of the round counted last)."""
    steps = load_steps()
    rel = []
    for sid in ids:
        s = step_by_id(steps, sid)
        if s.get("type") == "DISPATCH" and not s.get("accumulates"):
            rel += step_outputs(ctx, s)
    st.check_supersede_paths(ctx.run_dir, rel)
    _rearm(ctx, steps, ids, note)
    ctx.state.setdefault("counters", {}).pop("gap_counted", None)
    if rel:
        st.supersede(ctx.run_dir, ctx.state, rel)


def step_outputs(ctx, step):
    """The run-relative files a step wrote: its jobs' files, its gate files, and its declared `outputs` when the step
    belongs to this run (_in_this_run)."""
    rel = []
    for jid in ((ctx.state.get("steps") or {}).get(step["id"]) or {}).get("jobs") or []:
        job = builders.load_job(ctx, jid) or {}
        out = job.get("out")
        if out:
            rel += [out, out + ".meta.json", out + ".failed.md"]
        rel += ["jobs/%s.json" % jid, "prompts/%s.prompt.md" % jid, "prompts/%s.host.md" % jid]
    if _in_this_run(ctx, step):
        rel += st.expand_globs(ctx.run_dir, step.get("outputs") or [])
    if step.get("type") == "HUMAN" and step.get("gate"):
        rel += ["gates/%s.md" % step["gate"], "answers/%s.json" % step["gate"]]
    return rel


def _in_this_run(ctx, step):
    """Whether a step's declared `outputs` are its own files in this run: it ran (done, running, blocked), or it is
    pending and its `when` holds. A skipped step wrote nothing, and steps of another mode name the same files as a
    step of this one (6.1 and quick Q.3p, 5.2 and proposal P.1): those files belong to the step that wrote them."""
    state = st.step_state(ctx.state, step["id"])
    if state in ("done", "running", "blocked"):
        return True
    if state == "skipped":
        return False
    try:
        return bool(registry.eval_when(ctx, step.get("when")))
    except EngineError:
        return True


def supersede_from(ctx, steps, sid, stamp=None, log=None):
    """Reset `sid` and every downstream step, then move their outputs to _superseded/<ISO>/ (6.10). The reset and the
    list of files to move are committed in one save before any file moves (I6), and the run.json keys those steps own
    are dropped (pipeline.json owners, I10), so no stale idea id survives a re-curation (bs.py map renumbers the ideas)
    or the decision it was made on. `log`: decision lines (a switch, a K6 kill) committed in that same save (#11).
    Only the outputs of steps of this run move (_in_this_run), and the gap rounds start over only when the gap step
    itself runs again (a redo from 5.3c keeps 5.3, every round's ideas and the count of the last round, which its
    5.3m then does not count again; a round an older kit counted has no counters.gap_counted, so a done 5.3m's round
    is marked counted here)."""
    idx = index_of(steps, sid)
    ids = [s["id"] for s in steps[idx:]]
    gap = step_ref("gap_loop")
    c = ctx.state.setdefault("counters", {})
    if gap[0] not in ids and gap[-1] in ids and st.step_state(ctx.state, gap[-1]) == "done":
        c.setdefault("gap_counted", list(c.get("gap_round_items") or []))
    rel = []
    for s in steps[idx:]:
        rel += step_outputs(ctx, s)
    st.check_supersede_paths(ctx.run_dir, rel, stamp)  # before anything stops or changes (#98)
    # Only what is superseded stops: a running job of an earlier step (the 9.4 judges prelaunched at G8a) keeps its
    # worker, whose prompt and output stay valid; a signal would record it as a 'killed' failure (4.7).
    keep = set()
    for s in steps[:idx]:
        keep.update(((ctx.state.get("steps") or {}).get(s["id"]) or {}).get("jobs") or [])
    try:
        ctx.deps.batch.stop_all(ctx.run_dir, keep=sorted(keep))
    except Exception:
        pass
    _rearm(ctx, steps, ids)
    for key in owned_keys(ctx, steps, idx):
        if key == "choice":
            ctx.state.setdefault("choice", {}).update({"idea": None, "runner_up": None})
        else:
            ctx.state.pop(key, None)
    _log_decision(ctx, log)
    stage = int(steps[idx].get("stage", 0))
    if gap[0] in ids:
        for k in ("gap_rounds", "gap_prefix", "reopen_prefix"):
            c[k] = 0
        c.pop("gap_counted", None)
    if stage <= 10:
        ctx.state["ledger_written"] = False
    if stage <= 13:
        ctx.state["signed_off"] = False
    ctx.state["status"] = "active"
    moved = st.supersede(ctx.run_dir, ctx.state, rel, stamp)
    st.append_event(ctx.run_dir, "supersede", step=sid, moved=len(moved))
    return moved


def _log_decision(ctx, lines):
    """run.json decision_log: the decision lines 08_DECISION.md renders after the decision itself (6.10)."""
    lines = [str(x).strip() for x in lines or [] if str(x).strip()]
    if lines:
        ctx.state.setdefault("decision_log", []).extend(lines)


def supersede_blocked(ctx):
    """The card while the supersede journal still lists files in place (a program holds one of them open)."""
    batch = (ctx.state.get("supersede") or [{}])[0] or {}
    held = batch.get("held") or (batch.get("paths") or ["?"])[0]
    return cards.blocked(ctx, "A redo could not move %s to _superseded/ yet: another program has it open. Nothing "
                              "runs until every old output is moved aside." % held,
                         fix=["close the program that has %s open, then: %s" % (
                             textio.to_posix(ctx.path(held)), cards.next_cmd(ctx.state, ctx.run_dir, 0))],
                         error="supersede pending: %s" % (batch.get("error") or held))


def resume(ctx):
    """An explicit resume (`continue`, `run --continue`) under the driver lock lifts a `ub stop` (C3). `next` never
    does: it is the agent's own poll (every AUTO card's `then`), so a stop from a terminal or another session holds
    until the user continues the run."""
    stopped = ctx.state.get("status") == "stopped" and ctx.state.get("stopped_reason") == "user"
    if stopped or st.stop_requested(ctx.run_dir):
        st.clear_stop(ctx.run_dir)
        if stopped:
            ctx.state["status"] = "active"
            ctx.state.pop("stopped_reason", None)
        st.append_event(ctx.run_dir, "resume")


def clear_budget_stop(ctx):
    """Lift a budget stop (full-auto BLOCKED, or GB answered `stop`) and a waiting GB: the cap no longer binds."""
    s = ctx.state
    stopped = s.get("status") == "stopped" and "budget" in (s.get("stopped_reason") or "")
    asking = (s.get("interrupt") or {}).get("gate") == "GB"
    if not (stopped or asking):
        return
    if stopped:
        s["status"] = "active"
        s.pop("stopped_reason", None)
    if asking:
        s["interrupt"] = None
    (s.get("budget") or {}).pop("need", None)
    st.append_event(ctx.run_dir, "budget_resume", max_calls=(s.get("budget") or {}).get("max_calls"))


def budget_cmd(ctx, cap=None):
    """`ub budget RUN --max-calls N` with a cap that covers what is used plus about what the rest of the run needs."""
    b = progress.budget_status(ctx)
    if cap is None:
        try:
            left = sum(int(round((i["count"][0] + i["count"][1]) / 2.0)) for i in simulate(ctx, remaining_only=True))
        except Exception:
            left = 0
        cap = max(int(b["max_calls"] or 0) + 1, b["used"] + max(b["need"], 1) + left)
    return '%s budget "%s" --max-calls %d --json' % (cards.runner_of(ctx.state), textio.to_posix(ctx.run_dir), cap)


def budget_card(ctx, step, say):
    """BLOCKED at the request cap (full-auto): the requests sent and the job launches, and the command that raises
    the cap (the run then goes on by itself)."""
    return cards.blocked(ctx, "%s %s" % (say, progress.budget_line(ctx)), fix=[budget_cmd(ctx)], step=step)


def switch_arch(ctx, steps, label):
    ans = gates.merge_answer("G11", {"choice": label, "accept_recommendation": False,
                                     "notes": "via switch"}, ctx)
    gates.apply(ctx, "G11", ans, by="human")
    ctx.state["gates"]["G11"]["via"] = "switch"
    supersede_from(ctx, steps, step_ref("switch_arch_from"))


def switch_idea(ctx, steps, iid):
    """Make iid the chosen idea and redo from its probe design (11.1; quick mode: Q.6): the old idea's probe (and a
    PASSED result for it) never carries over to the new idea. The old idea becomes the runner-up, unless its own probe
    killed it (K6): an idea its probe killed is never the runner-up. A run the K6 stop ended goes on."""
    ch = ctx.state.setdefault("choice", {})
    k6 = registry.k6_killed(ctx.state)
    old = ch.get("idea")
    ch["idea"] = iid
    if ch.get("runner_up") in k6:
        ch["runner_up"] = None
    if old and old != iid and old not in k6 and (not ch.get("runner_up") or ch.get("runner_up") == iid):
        ch["runner_up"] = old
    if ch.get("runner_up") == iid:
        ch["runner_up"] = None
    if ctx.state.get("stopped_reason") == gates.K6_STOP:
        ctx.state.pop("stopped_reason")  # supersede_from sets the run active
    # the line is committed with the supersede (#11): a refused supersede leaves no line that a retry repeats
    apply_effects(ctx, steps, [("supersede", step_ref("probe_from", ctx)),
                               ("append", DECISION_MD, "Switched (%s): chosen idea %s -> %s (the user asked to "
                                                       "switch)" % (textio.now_iso(), old, iid))])


def finalists_left(state):
    """The finalists `switch --idea` can still choose: not the chosen idea, and ruled out neither by their own probe
    (K6) nor by a K4 kill. The DONE card of a K6-killed idea and a refused switch list them."""
    out = registry.k6_killed(state) | set(state.get("killed") or []) | {(state.get("choice") or {}).get("idea")}
    return [i for i in state.get("finalists") or [] if i not in out]


# ---------------------------------------------------------------- HOST

def _lease_state(ctx, sst):
    """'free' (no lease, expired, or `continue` takes it over), 'ours' (this session holds its token) or 'foreign'."""
    lease = sst.get("lease") or {}
    if not lease.get("token"):
        return "free"
    if ctx.lease and ctx.lease == lease.get("token"):
        return "ours"
    try:
        live = calendar.timegm(time.strptime(lease.get("expires"), "%Y-%m-%dT%H:%M:%SZ")) > ctx.deps.now()
    except (TypeError, ValueError):
        live = False
    return "foreign" if live and not ctx.takeover else "free"


def _issue_lease(ctx, sst, lease_s):
    """steps[sid].lease = {token, host, issued_at, expires}: the session given a HOST or HOST_BATCH card owns that work
    until the lease expires; other sessions wait instead of running it a second time (#96)."""
    if _lease_state(ctx, sst) != "ours":
        now = ctx.deps.now()
        sst["lease"] = {"token": os.urandom(8).hex(), "host": ctx.host_agent,
                        "issued_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)),
                        "expires": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now + lease_s))}
    ctx.lease = sst["lease"]["token"]
    return ctx.lease


def _wait_for_lease(ctx, sst, what, hint=None):
    """(None, waiting) with the say line of a poll that waits for another session's lease. hint: the card field whose
    --lease the holder presents to get its work back (a poll that lost the token looks foreign to itself)."""
    lease = sst.get("lease") or {}
    ctx.cache["waiting_on"] = ("%s is in progress in another session (%s, since %s). To take it over here, run: "
                               '%s continue "%s"' % (what, lease.get("host") or "?", lease.get("issued_at") or "?",
                                                     cards.runner_of(ctx.state), textio.to_posix(ctx.run_dir)))
    if hint:
        ctx.cache["waiting_on"] += " (if this session was given it, poll with the --lease of its %s instead)" % hint
    return None, True


def _fingerprints(ctx, rels):
    out = {}
    for rel in rels:
        try:
            out[rel] = textio.sha256_file(ctx.path(rel))
        except OSError:
            out[rel] = None
    return out


def host_step(ctx, step):
    """HOST: the task card for the session that holds (or now gets) the step's lease; (None, waiting) while another
    session holds it. The first issue records the files' fingerprints, so `done` sees what the host produced. A step
    blocked while its card was issued (an EngineError or a privacy refusal, fixed as that card said) is issued again
    and runs as before (#18); fingerprints recorded by an earlier issue are kept."""
    sst = (ctx.state.get("steps") or {}).get(step["id"]) or {}
    if _lease_state(ctx, sst) == "foreign":
        return _wait_for_lease(ctx, sst, "Host task %s" % step["id"], hint="task.done_cmd")
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
    for key, value in (h.get("vars") or {}).items():  # {IDEA} = the forge idea, as in host.writes
        jc["vars"][key] = forge_idea(ctx) if value == "{IDEA}" else value
    arg = builders.host_argument(ctx, name, jc)
    if arg is not None:
        ctx.write(arg_rel, arg)
    writes = host_writes(ctx, step)
    if st.step_state(ctx.state, step["id"]) in ("pending", "blocked"):
        fp = sst.get("host_fp") if isinstance(sst.get("host_fp"), dict) else _fingerprints(ctx, writes)
        sst = st.set_step(ctx.state, step["id"], "running", host_fp=fp)
    token = _issue_lease(ctx, sst, HOST_LEASE_S)
    task = {"template": textio.to_posix(tpl_path), "skill": comp, "argument_file": textio.to_posix(ctx.path(arg_rel)),
            "writes": [textio.to_posix(ctx.path(w)) for w in writes],
            "done_cmd": '%s done "%s" %s --lease %s --json' % (cards.runner_of(ctx.state),
                                                               textio.to_posix(ctx.run_dir), step["id"], token)}
    return cards.host(ctx, step, task, h.get("say") or "Host task: %s. Follow the template in this conversation, "
                                                           "then run done_cmd." % (step.get("title") or name)), False


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
    """`ub done`: accept a HOST task. Nothing is accepted while a supersede journal is pending (I6), for a task that
    was never handed out (the step is not running: files that existed before it prove nothing; the card is issued
    instead), or with a `--lease` token that is not the step's current lease, also when the step has none (the task
    was handed to another session, or reset by a redo). Only files the host wrote after the task was issued count
    (#18): a task that changed none of its files is recorded as skipped, never as done. An accepted task records its
    files' hashes (`accepted`), so a late write of a session whose task was taken over is named when that session's
    done is refused: a BLOCKED card, so that session stops instead of driving on (#96). The files are made durable
    before the task is recorded done (#4)."""
    if ctx.state.get("supersede"):
        return finalize(ctx, steps, supersede_blocked(ctx))
    step = step_by_id(steps, sid)
    cur = current_step(ctx, steps)
    sst = (ctx.state.get("steps") or {}).get(sid) or {}
    lease = (sst.get("lease") or {}).get("token")
    if step.get("type") != "HOST" or cur is None or cur["id"] != sid:
        stale = _late_writes(ctx, sst) if ctx.lease and ctx.lease != lease else []
        if stale:
            return finalize(ctx, steps, _late_write_card(ctx, step, stale))
        card = advance(ctx, steps, 0, lock)
        card.setdefault("notes", []).append("step %s is not waiting for a host task" % sid)
        return card
    if ctx.lease and ctx.lease != lease:
        ctx.lease = None  # the card goes to the session that holds the task now
        card = advance(ctx, steps, 0, lock)
        card.setdefault("notes", []).insert(0, "host task %s was handed to another session; this done was not applied"
                                            % sid)
        return card
    if sst.get("state") != "running":
        # never handed out (for example a `done` while a redo reset the step): the task card goes out now. (A running
        # task without host_fp was handed out by a kit before 2.1.0 and is accepted as that kit did.)
        card = advance(ctx, steps, 0, lock)
        card.setdefault("notes", []).insert(0, "host task %s had not been handed out yet, so this done was not "
                                               "applied; the task is on this card" % sid)
        return card
    ctx.lease = ctx.lease or lease  # a `done` without --lease (older cards) speaks for the task's holder
    writes = host_writes(ctx, step)
    missing = []
    for w in writes:
        p = ctx.path(w)
        if not os.path.exists(p) or not os.path.getsize(p):
            missing.append(w)
    fp = sst.get("host_fp")
    unchanged = not missing and isinstance(fp, dict) and _fingerprints(ctx, writes) == dict(
        (w, fp.get(w)) for w in writes)
    if unchanged or (missing and (step.get("host") or {}).get("optional")):
        # The host could not run the component (for example ce-ideate missing), or wrote nothing new since the task
        # was issued (a seeds file from the kickoff, a merge answer from before a redo): not done, skipped.
        why = "produced no output" if missing else "changed none of its files"
        st.set_step(ctx.state, sid, "skipped", note="host task %s" % why)
        st.add_note(ctx.state, "%s: the host task %s; %s" % (sid, why, "the engine fallback runs instead" if missing
                                                                      else "recorded as skipped, not done"))
        st.save(ctx.run_dir, ctx.state)
        return advance(ctx, steps, 0, lock)
    if missing:
        c = host_step(ctx, step)[0]
        c["error"] = "these files are missing or empty: %s" % ", ".join(missing)
        return finalize(ctx, steps, c)
    for w in writes:
        try:
            _make_durable(ctx.path(w))  # #4: the done record is durable, so the files it accepts must be too
        except OSError:
            c = host_step(ctx, step)[0]
            c["say"] = ("Host task %s: %s is still open in another program, so this done was not applied. Close it, "
                        "then run done_cmd again (the task itself is finished)." % (sid, w))
            return finalize(ctx, steps, c)
    for name in step.get("after") or []:
        registry.run_script(ctx, name, step)
    st.set_step(ctx.state, sid, "done", note="host task done", accepted=_fingerprints(ctx, writes))
    st.save(ctx.run_dir, ctx.state)
    return advance(ctx, steps, 0, lock)


def _late_writes(ctx, sst):
    """Files of an accepted HOST task that changed since it was accepted (steps[<id>].accepted)."""
    acc = sst.get("accepted")
    if sst.get("state") != "done" or not isinstance(acc, dict):
        return []
    now = _fingerprints(ctx, sorted(acc))
    return [rel for rel in sorted(acc) if now.get(rel) != acc.get(rel)]


def _late_write_card(ctx, step, rels):
    """BLOCKED for the displaced session's done after a takeover: show it and stop (a second driver would run on the
    replaced files)."""
    sid = step["id"]
    say = ("host task %s was taken over and accepted from another session; this done was not applied. %s changed after "
           "that: if this session wrote %s after the takeover, it replaced the accepted version. Check it, or run the "
           "task again." % (sid, ", ".join(rels), "them" if len(rels) > 1 else "it"))
    return cards.blocked(ctx, say, fix=["check %s" % ", ".join(textio.to_posix(ctx.path(r)) for r in rels),
                                        '%s redo "%s" %s --yes' % (cards.runner_of(ctx.state),
                                                                   textio.to_posix(ctx.run_dir), sid)], step=step)


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


def _relaunch_verdict(ctx, sst, job):
    """What a dead job gets: "relaunch", "blocked" (RELAUNCH_LIMIT relaunches since the step last started or was
    retried: the host kills background work) or "give_up" (RELAUNCH_ROUNDS x RELAUNCH_LIMIT relaunches for this prompt
    in all: the job is failed). The count is batch.relaunch_count, the relaunches of the job's CURRENT prompt; a
    BLOCKED retry never resets it, it only moves the step's baseline (relaunch_base), so `next` after `next` cannot
    relaunch a dead job without end (#13)."""
    limit = int(ctx.deps.batch.RELAUNCH_LIMIT)
    total = int(ctx.deps.batch.relaunch_count(ctx.run_dir, job) or 0)
    base = int((sst.get("relaunch_base") or {}).get(job["id"], 0))
    if total >= limit * RELAUNCH_ROUNDS:
        return "give_up", total
    if total - (base if base <= total else 0) >= limit:
        return "blocked", total
    return "relaunch", total


def _fail_unlaunched(ctx, job, status, error_class, reason):
    """The driver records a job as final without a (further) launch: a meta for the current prompt and its failure
    record, so every later poll reads it as failed too, and fallback and min_ok apply (4.4)."""
    rec = {"schema": 1, "id": job["id"], "family": job.get("family"), "status": status, "attempts": 0,
           "requests": 0, "exit_code": None, "error_class": error_class, "started": textio.now_iso(),
           "prompt_sha256": _prompt_sha(ctx, job), "out_sha256": None, "provisional": bool(job.get("provisional")),
           "reason": reason}
    textio.write_json_atomic(ctx.path(job["out"] + ".meta.json"), rec)
    textio.write_text_atomic(ctx.path(job["out"] + ".failed.md"), "FAMILY CALL FAILED: %s\n" % reason)
    st.append_event(ctx.run_dir, "not_launched", job=job["id"], error_class=error_class)


AUTH_FAILED = "authentication failed: "  # the reason prefix of a family _mark_unavailable took out


def _mark_unavailable(ctx, job):
    """5.2: a family whose call failed authentication (401/403, a rejected key; not a key that is merely unset) is
    unavailable for the rest of the run: no fallback goes to it and no job of it is launched again."""
    meta = ctx.read_json(job["out"] + ".meta.json", {}) or {}
    reason = str(meta.get("reason") or "")
    fam = base_family(job.get("family"))
    info = (ctx.state.get("families") or {}).get(fam) or {}
    if meta.get("error_class") != "auth" or "is not set" in reason or fam == ctx.host_family or \
            info.get("status") != "ok":
        return
    info.update({"status": "unavailable", "reason": "%s%s" % (AUTH_FAILED, reason[:120] or "401/403")})
    st.add_note(ctx.state, '%s: authentication failed, so %s is not used until it is detected again (log in again, '
                           'then: %s continue "%s")' % (job["id"], fam, cards.runner_of(ctx.state),
                                                        textio.to_posix(ctx.run_dir)))


def redetect_auth(ctx):
    """R-engine-2: families marked unavailable after an authentication failure (5.2) are detected again (`continue`,
    `run --continue`, a BLOCKED step's retry), so logging in again brings them back; seats are unchanged, so their
    later jobs launch as seated. Detection without --live cannot prove a login: a family that still fails is marked
    again at its next 401, one call later. Returns the families that are usable again."""
    fams = ctx.state.get("families") or {}
    stuck = [f for f in sorted(fams) if (fams[f] or {}).get("status") == "unavailable" and
             str((fams[f] or {}).get("reason") or "").startswith(AUTH_FAILED)]
    if not stuck:
        return []
    try:
        det = (ctx.deps.detect(live=False, only=stuck) or {}).get("families") or {}
    except EngineError:
        return []
    lifted = []
    for f in stuck:
        d = det.get(f) or {}
        chain = [b for b in d.get("chain") or [] if isinstance(b, str) and b != "host"]
        if d.get("available") and chain:
            fams[f].update({"status": "ok", "reason": "", "chain": chain,
                            "backend": d["backend"] if d.get("backend") in chain else chain[0]})
            lifted.append(f)
    if lifted:
        st.add_note(ctx.state, "%s detected again after the authentication failure: used again" % ", ".join(lifted))
        st.append_event(ctx.run_dir, "redetect", families=lifted)
    return lifted


def _prompt_sha(ctx, job):
    p = ctx.path(job.get("prompt_file") or "")
    try:
        return textio.sha256_file(p)
    except OSError:
        return "missing"


def host_job_state(ctx, job):
    """done | failed | pending | running for jobs whose family resolves to the host (HOST_BATCH).

    I5: an output is accepted only for the prompt the HOST_BATCH card handed out (host_issued[id], recorded when the
    card is issued). An output, meta or failure record from an earlier prompt (a reset or re-armed step, a changed
    brief, another job that wrote the same <out>) is moved to _superseded/ and the job is pending again: it is never
    re-stamped with the current prompt's hash. A valid JSON output is rewritten in the adapter's canonical form, and its
    ledger row sends no backend request (C6: "requests": 0)."""
    meta = ctx.read_json(job["out"] + ".meta.json", None) or {}
    sha = _prompt_sha(ctx, job)
    mine = meta.get("id") == job["id"]
    if mine and meta.get("prompt_sha256") == sha:
        return "done" if meta.get("status") == "ok" else "failed"
    issued = (ctx.state.get("host_issued") or {}).get(job["id"])
    if mine or (issued != sha and ctx.exists(job["out"])):
        try:
            st.supersede_paths(ctx.run_dir, [job["out"]] + ([job["out"] + ".meta.json", job["out"] + ".failed.md"]
                                                            if mine else []))
        except OSError:
            return "running"  # a sub-agent still has the file open: look again at the next poll
        return "pending"
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
                                      bool((job.get("contract") or {}).get("status_trailer")), parsed=parsed)
        ok, errors = res["ok"], res["errors"]
    if ok and (job.get("contract") or {}).get("type") == "json" and parsed is not None:
        # the canonical form the adapter writes for a worker (4.5): the extracted JSON with the engine's cover ids
        body = json.dumps(parsed, indent=1, ensure_ascii=False) + "\n"
        if body != text:
            try:
                textio.write_text_atomic(ctx.path(job["out"]), body)
            except OSError:
                return "running"  # a sub-agent still has the file open: look again at the next poll
    now = textio.now_iso()
    try:
        out_sha = textio.sha256_file(ctx.path(job["out"]))  # the bytes, as batch.is_done compares them (C4)
    except OSError:
        out_sha = None
    rec = {"schema": 1, "id": job["id"], "family": job.get("family"), "vendor": privacy_mod.family_vendor(
        job.get("family")), "backend": "host", "model": None, "tier": job.get("tier"),
        "provisional": bool(job.get("provisional")), "status": "ok" if ok else "invalid", "attempts": 1,
        "requests": 0, "exit_code": 0 if ok else 5, "error_class": None if ok else "bad_output", "started": now,
        "duration_s": None, "prompt_sha256": sha, "out_sha256": out_sha,
        "usage": {"input_tokens": None, "output_tokens": None, "cost_usd": None, "source": "none"},
        "tools": job.get("tools"), "web_used": False, "cwd": job.get("cwd"), "repaired": False,
        "cmd": "host sub-agent", "stderr_tail": ""}
    if ok:
        try:
            _make_durable(ctx.path(job["out"]))  # #4: the ok meta is durable, so the data it names must be too
        except OSError:
            return "running"  # a sub-agent still has the file open: look again at the next poll
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
    try:
        st.supersede_paths(ctx.run_dir, [job["out"]])
    except OSError:
        return "running"  # a sub-agent still has the file open: look again at the next poll
    return "pending"


def _make_durable(path):
    """fsync a file a host sub-agent wrote (the kit never wrote it, so nothing flushed it) and its folder, before the
    kit records it done with a durable meta: a power loss then never leaves an ok meta over lost or zeroed data."""
    fd = os.open(path, os.O_RDWR | getattr(os, "O_BINARY", 0))  # Windows flushes only a handle with write access
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
    textio.fsync_dir(os.path.dirname(path))


def _recorded_host_state(ctx, job):
    """A host job's state from its meta alone, read-only (nothing is validated or moved): done or failed when the meta
    records an outcome for the current prompt, else running. Used while another session holds the step's lease."""
    meta = ctx.read_json(job["out"] + ".meta.json", None) or {}
    if meta.get("id") == job["id"] and meta.get("prompt_sha256") == _prompt_sha(ctx, job):
        return "done" if meta.get("status") == "ok" else "failed"
    return "running"


def _job_sig(ctx, job):
    """(inode, mtime, size) of the files a job's state is derived from; None for a missing file."""
    sig = []
    for rel in ("jobs/%s.json" % job["id"], job.get("prompt_file") or "", job["out"], job["out"] + ".meta.json"):
        try:
            s = os.stat(ctx.path(rel))
            sig.append((s.st_ino, s.st_mtime_ns, s.st_size))
        except OSError:
            sig.append(None)
    return tuple(sig)


def _job_state(ctx, job):
    """A job's state. A final state (done, failed) is kept for this process while none of the job's files changed, so
    a poll re-derives only the jobs that can have changed (no re-hash, re-read or re-validation of finished work)."""
    memo = ctx.cache.setdefault("final_jobs", {})
    sig = _job_sig(ctx, job)
    hit = memo.get(job["id"])
    if hit and hit[0] == sig:
        return hit[1]
    if ctx.is_host_chain(job.get("family")):
        s_ = host_job_state(ctx, job)
    else:
        batch = ctx.deps.batch
        try:
            # #5: the outcome generation BEFORE the state; launch_job(expect_gen=) launches nothing when a run of the
            # job finished in between (the state read here is then stale)
            if hasattr(batch, "job_gen"):
                ctx.cache.setdefault("gens", {})[job["id"]] = batch.job_gen(ctx.run_dir, job["id"])
            s_ = batch.job_state(ctx.run_dir, job)
        except EngineError:
            raise
        except Exception as e:
            raise EngineError("could not read the state of job %s: %s" % (job.get("id"), e))
    if s_ in ("done", "failed"):
        memo[job["id"]] = (_job_sig(ctx, job), s_)
    return s_


def _family_usable(ctx, label):
    if base_family(label) == ctx.host_family:
        return True
    info = (ctx.state.get("families") or {}).get(base_family(label)) or {}
    return info.get("status") == "ok" and st.family_allowed(ctx.state, base_family(label))


def _reserve(ctx, job):
    """Worst-case requests one launch of `job` can send (C6; at least 1), cached per job for this process."""
    memo = ctx.cache.setdefault("reserve", {})
    key = (job["id"], job.get("family"), tuple(job.get("chain") or ()))
    if key not in memo:
        memo[key] = max(1, ctx.deps.request_reserve(job))
    return memo[key]


def _admission(ctx, need, jobs, states):
    """I8: None when a launch that can send `need` requests fits under budget.max_calls; "cap" when it does not even
    once the running jobs are done (requests_used + need > max_calls: GB or the full-auto stop); "wait" while the
    running jobs of the step still hold the headroom (their worst case counts until they are done)."""
    cap = (ctx.state.get("budget") or {}).get("max_calls")
    if not cap:
        return None
    used = progress.requests_used(ctx)
    if used + need > int(cap):
        return "cap"
    held = sum(_reserve(ctx, j) for j in jobs if states.get(j["id"]) == "running" and not ctx.is_host_chain(
        j.get("family")))
    return "wait" if used + held + need > int(cap) else None


def _refresh_stale(ctx, step, jobs, states, replaced):
    """#85: once per process and step, a job that has not run yet, is dead or failed is rebuilt when its input_digest
    (4.4) differs from what the engine would build now (an edited frame, a re-seat by `continue --host`, a changed
    privacy setting). The prompt-sha done rule then decides; a running or done job is never touched. A failed or dead
    job whose family changed (re-seated) did not fail on its new seat: its failure record and meta move to
    _superseded/ and its relaunch count starts over, so it runs on the new family instead of falling back from it."""
    old = dict((j["id"], j.get("input_digest")) for j in jobs if j["id"] not in replaced and
               states.get(j["id"]) in ("pending", "dead", "failed"))
    if not old:
        return
    fresh = builders.build_jobs(ctx, step, write=lambda job: job["id"] in old and job["input_digest"] != old[
        job["id"]])
    stale = dict((j["id"], j) for j in fresh if j["id"] in old and j["input_digest"] != old[j["id"]])
    if not stale:
        return
    batch = ctx.deps.batch
    for i, j in enumerate(jobs):
        if j["id"] in stale:
            if states.get(j["id"]) in ("dead", "failed") and stale[j["id"]].get("family") != j.get("family"):
                try:
                    st.supersede_paths(ctx.run_dir, [j["out"] + ".meta.json", j["out"] + ".failed.md"])
                except OSError:
                    pass  # a scanner holds the meta: the job stays failed and its fallback runs, as before
                if hasattr(batch, "reset_relaunch"):
                    batch.reset_relaunch(ctx.run_dir, j["id"])
            jobs[i] = stale[j["id"]]
            states[j["id"]] = _job_state(ctx, jobs[i])
    changed = sorted(jid for jid in stale if old[jid])  # a job file of an older kit has no digest: no news
    if changed:
        st.add_note(ctx.state, "%s: the inputs of %s changed since the job files were built; rebuilt" % (
            step["id"], ", ".join(changed)))
    st.append_event(ctx.run_dir, "jobs_rebuilt", step=step["id"], jobs=sorted(stale))


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
    loaded = bool(jobs)
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
    # While another session holds the step's HOST_BATCH lease its sub-agents may be writing: their outputs are
    # neither validated nor moved here, and the jobs are not handed out a second time (#96). A host job whose meta
    # already records an outcome for its current prompt is final all the same (read-only), so a finished step
    # completes whoever polls it.
    foreign = _lease_state(ctx, sst) == "foreign"
    states = dict((j["id"], "failed" if j["id"] in replaced else _recorded_host_state(ctx, j) if foreign and
                   ctx.is_host_chain(j.get("family")) else _job_state(ctx, j)) for j in jobs)
    checked = ctx.cache.setdefault("inputs_checked", set())
    if sid not in checked:
        checked.add(sid)
        if loaded and not foreign:
            _refresh_stale(ctx, step, jobs, states, replaced)
    if foreign and any(ctx.is_host_chain(j.get("family")) and states[j["id"]] == "running" for j in jobs):
        _wait_for_lease(ctx, sst, "The host sub-agent jobs of step %s" % sid)
    if sst.get("lease") and all(states[j["id"]] in ("done", "failed") for j in jobs
                                if ctx.is_host_chain(j.get("family"))):
        # every host job has its outcome: the lease protects nothing any more, so no poll (with or without --lease)
        # waits for it until it expires (#96)
        sst.pop("lease", None)
        foreign = False
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
        if st.stop_requested(ctx.run_dir):
            return None, True  # C3: `ub stop` asked; the next pass stops the run and launches nothing
        finfo = (ctx.state.get("families") or {}).get(fb)
        if finfo is not None and not _family_usable(ctx, j["family"]):
            # re-seated away, or unavailable since the job was built (5.2): its fallback runs instead (#85)
            _fail_unlaunched(ctx, j, "unavailable", "config", "family %s is unavailable in this run: %s" % (
                fb, finfo.get("reason") or finfo.get("status") or "not allowed"))
            states[jid] = "failed"
            continue
        if s_ == "dead":
            verdict, n = _relaunch_verdict(ctx, sst, j)
            if verdict == "give_up":
                _fail_unlaunched(ctx, j, "failed", "killed", "its worker was stopped %d times before it finished (the "
                                 "host agent stops background work; run the rest in a terminal: run --continue)" % n)
                states[jid] = "failed"
                continue
            if verdict == "blocked":
                st.set_step(ctx.state, sid, "blocked", note="job %s relaunched %d times" % (jid, n))
                return cards.blocked(ctx, relaunch_message(ctx), fix=[
                    '%s run --continue "%s"' % (cards.runner_of(ctx.state), textio.to_posix(ctx.run_dir)),
                    "raise the command timeout (references/hosts.md)"], step=step), False
        # I8: a launch, a relaunch of a dead job included, is admitted only while its worst-case requests fit the cap
        need = _reserve(ctx, j)
        verdict = _admission(ctx, need, jobs, states)
        if verdict == "wait":
            continue
        if verdict == "cap":
            ctx.state.setdefault("budget", {})["need"] = need
            if ctx.autopilot == "full-auto":
                ctx.state["status"] = "stopped"
                ctx.state["stopped_reason"] = "budget cap reached (%s requests)" % ctx.state["budget"]["max_calls"]
                return budget_card(ctx, step, "The run reached its request cap."), False
            ctx.state["interrupt"] = {"gate": "GB", "step": sid}
            return human_card(ctx, step, "GB"), False
        gen = (ctx.cache.get("gens") or {}).get(jid)
        path = ctx.path("jobs", jid + ".json")
        info = (ctx.deps.batch.launch_job(path) if gen is None else
                ctx.deps.batch.launch_job(path, expect_gen=gen)) or {}
        if info.get("refused"):
            # C3: launch_job started nothing (the run is being stopped): not a launch, nothing is counted
            st.append_event(ctx.run_dir, "launch_refused", job=jid, reason=info.get("refused"))
            return None, True
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
            # launch_job re-checks under the job's execution lock: the job finished, another worker holds it, or a run
            # of it finished since its state was read (#5: failed or pending; the next poll reads it again). Nothing
            # started, so nothing is counted.
            states[jid] = info.get("state") if info.get("state") in ("done", "failed", "pending") else "running"
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
        if foreign and ctx.is_host_chain(j.get("family")):
            continue  # the lease holder handles its host jobs' fallbacks; this session only waits for them
        _mark_unavailable(ctx, j)
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
    ok_note = "%d/%d ok" % (len(ok_roots), n)
    if (step.get("job") or {}).get("kind") == "judge":
        # a fallback can reuse a seated family, and bs.py counts one vote per family (#50): the card says so
        fams = set(base_family((ctx.read_json(j["out"] + ".meta.json", {}) or {}).get("family") or j.get("family"))
                   for j in jobs if states[j["id"]] == "done")
        ok_note += " (%d famil%s)" % (len(fams), "y" if len(fams) == 1 else "ies")
    st.set_step(ctx.state, sid, "done", note=ok_note + ("; " + "; ".join(notes) if notes else ""))
    st.append_event(ctx.run_dir, "step_done", step=sid)
    return None, False


def _retry_blocked(ctx, step, sst):
    """A BLOCKED dispatch step is retried on the next call: failed outputs move to _superseded and the fallbacks
    start over. The relaunch counts are NOT reset (#13): the retry only moves the step's baseline (relaunch_base), so
    each retry allows RELAUNCH_LIMIT more relaunches of a dead job, up to RELAUNCH_ROUNDS x RELAUNCH_LIMIT for its
    prompt, and every relaunch still passes the request budget. A family that failed authentication is detected
    again first (the BLOCKED fix says: log in again, then retry)."""
    redetect_auth(ctx)
    rel = []
    base = {}
    for jid in sst.get("jobs") or []:
        job = builders.load_job(ctx, jid) or {}
        out = job.get("out")
        meta = ctx.read_json((out or "") + ".meta.json", {}) or {}
        if out and meta.get("status") not in (None, "ok"):
            rel += [out + ".meta.json", out + ".failed.md"]
        if job and not ctx.is_host_chain(job.get("family")):
            base[jid] = int(ctx.deps.batch.relaunch_count(ctx.run_dir, job) or 0)
    st.supersede_paths(ctx.run_dir, rel)
    keep = [j for j in sst.get("originals") or sst.get("jobs") or []]
    st.set_step(ctx.state, step["id"], "running", jobs=keep, fallback_of={}, exhausted=[], originals=keep,
                relaunch_base=base)
    (ctx.state.get("host_invalid") or {}).clear()


def _failure_reason(ctx, job):
    meta = ctx.read_json(job["out"] + ".meta.json", {}) or {}
    ec = meta.get("error_class")
    if ec in ("config", "killed") and meta.get("reason"):
        return "%s (%s): %s" % (meta.get("status"), ec, str(meta["reason"])[:120])
    if ec:
        return "%s (%s)" % (meta.get("status"), ec)
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
            fixes.append('log in again for the %s family (for example: %s), then: %s continue "%s"' % (
                fam, {"gpt": "codex login", "kimi": "kimi login", "claude": "run claude once and sign in"}.get(
                    fam, "check its key"), runner, textio.to_posix(ctx.run_dir)))
        elif ec == "not_found":
            fixes.append("install the %s CLI (install.py install --with-clis ...), then continue" % fam)
        elif ec == "sandbox_network":
            fixes.append("Codex: approve network access for the ub command prefix (references/hosts.md)")  # [U-8]
        elif ec == "policy":
            fixes.append("privacy settings or the job's tool policy refused this call, or the model refused; see "
                         "%s.failed.md (references/families.md)" % textio.to_posix(ctx.path(j["out"])))
        elif ec == "config":
            fixes.append(str(meta.get("reason") or "fix the setup named in %s.failed.md" % textio.to_posix(
                ctx.path(j["out"])))[:200])
        elif ec == "killed":
            fixes.append(relaunch_message(ctx))
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
    """The HOST_BATCH card. It records the prompt hash each job is handed out with (host_issued: only an output
    written for that prompt is accepted, I5) and leases the step to this session for twice the longest job timeout;
    `then` carries the lease token, so this session's next poll reads the outputs and others wait (#96)."""
    sst = ctx.state["steps"][step["id"]]
    issued = ctx.state.setdefault("host_issued", {})
    items = []
    for j in jobs:
        issued[j["id"]] = _prompt_sha(ctx, j)
        items.append({"id": j["id"], "prompt_file": textio.to_posix(ctx.path(j.get("host_prompt_file") or
                                                                           j["prompt_file"])),
                      "out": textio.to_posix(ctx.path(j["out"])), "tools": j.get("tools", "none")})
    token = _issue_lease(ctx, sst, 2 * max([int(j.get("timeout_s") or 420) for j in jobs] + [300]))
    say = ("Run %d job(s) for %s in fresh sub-agents: each reads its prompt file and writes only its output file."
           % (len(items), step.get("title") or step["id"]))
    return cards.host_batch(ctx, step, items, say, lease=token)


# ---------------------------------------------------------------- DONE

# How the user reaches the skill from each agent host (the DONE card names this, not a `ub` the host has no PATH to).
HOST_ENTRY = {"claude-code": "/ultimate-brainstorm", "codex": "$ultimate-brainstorm", "zcode": "$ultimate-brainstorm",
              "kimi": "/skill:ultimate-brainstorm"}


def done_card(ctx, stopped=None):
    s = ctx.state
    try:
        render.refresh_page(ctx)  # a page an older kit rendered (no pinned script) is rendered again before the link
    except (EngineError, OSError):
        pass  # the card still links the page; G14, a publish and an export render it again
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
    if stopped == "user":
        lines.append('Continue later with: %s continue "%s"' % (cards.runner_of(s), textio.to_posix(ctx.run_dir)))
    # the chosen idea's probe missed and no runner-up was left (gates.probe_result): its recorded result, not a missing
    # 'RESULT: PASSED', decides the Next line
    dead = render.k6_dead(s)
    if ch.get("idea"):
        lines.append("Decision: %s %s%s%s" % (ch["idea"], info.get("title", ""),
                                              " (AUTO-DECISION)" if (s.get("gates", {}).get("G8b") or {}).get(
                                                  "by") == "auto" else "",
                                              " - killed by its probe (K6); no runner-up is left" if dead else ""))
    if ch.get("arch"):
        lines.append("Architecture: candidate %s (%s)" % (ch["arch"], ch.get("arch_family")))
    if links.get("proposal"):
        status = "KILLED (K6)" if dead else "APPROVED" if s.get("signed_off") else (
            "AUTOPILOT DRAFT" if s.get("autopilot") == "full-auto" else "DRAFT")
        lines.append("Proposal: %s (%s)" % (links["proposal"], status))
    probe = ctx.read("09_PROBE.md")
    agent = (s.get("host") or {}).get("agent") or ""
    entry = HOST_ENTRY.get(agent)
    if dead:
        left = finalists_left(s)  # one of them is the next idea to test
        if not left:
            lines.append("Next: no finalist is left to test (every other one was killed); start a new run with a "
                         "reframed topic.")
        elif entry:
            lines.append("Next: choose another finalist (%s), then type `%s switch idea <ID>`" % (", ".join(left),
                                                                                               entry))
        else:
            lines.append('Next: choose another finalist (%s), then run: %s switch "%s" --idea <ID>' % (
                ", ".join(left), cards.runner_of(s), textio.to_posix(ctx.run_dir)))
    elif not stopped and probe and "RESULT: PASSED" not in probe:  # a paused or stopped run has no probe to run yet
        design = " ".join((registry.section(probe, "3") or registry.section(probe, "Probe") or "").split())
        design = re.split(r"(?<=[.!?])\s", design, maxsplit=1)[0] if design else ""
        what = "the probe in 09_PROBE.md%s" % ((" (%s)" % design) if design else "")
        if entry:
            lines.append("Next: run %s, then type `%s probe passed|missed|inconclusive <what you saw>`"
                         % (what, entry))
        else:
            lines.append("Next: run %s (Milestone 0), then report it: %s probe-result \"%s\" "
                         "PASSED|MISSED|INCONCLUSIVE" % (what, cards.runner_of(s), textio.to_posix(ctx.run_dir)))
    if s.get("provisional"):
        lines.append("PROVISIONAL seats: %d (see run.json provisional)" % len(s["provisional"]))
    s["status"] = "stopped" if stopped else "done"
    return cards.done(ctx, "\n".join(lines) + "\n", links, say="Stopped." if stopped else "Done.")
