#!/usr/bin/env python3
"""ub.py - the ultimate-brainstorm engine CLI (KIT_SPEC 4.11). Python 3.9+ standard library only.

  ub.py --version
  ub.py init      --host H --text "<raw user text>" [--components LIST] [--root DIR] [--lang CODE]
                  [--mode M] [--variant V] [--autopilot A] [--families auto|LIST] [--privacy default|private]
                  [--seeds-file F] [--idea-file F] [--no-preflight] [--json]          -> prints the G0 card
  ub.py next      [RUN] [--wait-s N] [--json]                                          -> one card
  ub.py answer    RUN GATE (--file F | --choice X | --default | --skip) [--json]       -> next card
  ub.py done      RUN STEP [--json]                               HOST step finished -> validate -> next card
  ub.py continue  [RUN] [--host H] [--root DIR] [--json]          newest unfinished run -> its current card
  ub.py status    [RUN] [--json]
  ub.py plan      [RUN] | --mode M --variant V --families LIST [--json]
  ub.py run       --text "<topic...>" [init options] | --continue [RUN]      terminal mode
  ub.py stop      RUN
  ub.py redo      RUN STEP [--yes]
  ub.py switch    RUN (--arch LABEL | --idea ID) [--yes]
  ub.py probe-result RUN (PASSED|MISSED|INCONCLUSIVE) [--note-file F]
  ub.py import    FILE [RUN]
  ub.py attach-s1 RUN --doc P --raw P
  ub.py render    RUN [--zip]
  ub.py export    RUN --format docx|html
  ub.py doctor    [--live] [--json]
  ub.py config    get|set KEY [VALUE]
  ub.py list      [--root DIR] [--json]

Exit codes: 0 whenever a card or result was printed (the status is inside the JSON), 2 usage, 1 internal error.
"""

import argparse
import json
import os
import re
import shutil
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ublib import textio  # noqa: E402
from ublib.engine import (APPROACH_VARIANTS, AUTOPILOTS, ENGINE_VERSION, FAMILY_ORDER, HOST_DEFAULT_FAMILY,  # noqa
                          HOST_WAIT_S, HOSTS, MODES, VARIANTS, EngineError, UsageError, base_family)
from ublib.engine import cards  # noqa: E402
from ublib.engine import gates  # noqa: E402
from ublib.engine import pipeline  # noqa: E402
from ublib.engine import privacy as privacy_mod  # noqa: E402
from ublib.engine import progress  # noqa: E402
from ublib.engine import registry  # noqa: E402
from ublib.engine import state as st  # noqa: E402

COMMAND_TOKENS = ("continue", "status", "doctor", "stop")
OPTION_TOKENS = ("private", "with-ce-ideate")
COMPONENT_KEYS = {"grilling": "grilling", "domain-modeling": "domain_modeling", "ce-ideate": "ce_ideate",
                  "ce-brainstorm": "ce_brainstorm", "ce-plan": "ce_plan", "bmad-brainstorming": "bmad_brainstorming",
                  "bmad-forge-idea": "bmad_forge_idea", "lateral-thinking": "lateral_thinking",
                  "claude-council": "claude_council", "speckit": "speckit"}
SOURCE_EXT = (".py", ".js", ".ts", ".tsx", ".jsx", ".go", ".rs", ".java", ".kt", ".rb", ".cs", ".cpp", ".c", ".h",
              ".swift", ".php", ".scala", ".vue", ".svelte")


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise UsageError(message)


# ================================================================ output

def emit(obj, as_json):
    if as_json:
        sys.stdout.write(json.dumps(obj, ensure_ascii=True) + "\n")
    else:
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
        if isinstance(obj, dict) and obj.get("type") in cards.CARD_TYPES:
            sys.stdout.write(cards.render_text(obj))
        elif isinstance(obj, dict) and "progress_file" in obj and "step" in obj:
            sys.stdout.write(status_text(obj))
        elif isinstance(obj, dict) and isinstance(obj.get("runs"), list) and "root" in obj:
            sys.stdout.write(list_text(obj))
        else:
            sys.stdout.write(json.dumps(obj, indent=1, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def status_text(obj):
    """`ub status` for people (--json keeps the full object)."""
    p = obj.get("progress") or {}
    lines = ["%s: %s (%s, %s, %s)" % (os.path.basename(obj.get("run") or ""), obj.get("status") or "active",
                                      obj.get("mode"), obj.get("variant"), obj.get("autopilot")),
             p.get("line") or ""]
    if obj.get("step"):
        lines.append("Now: step %s %s%s" % (obj["step"], obj.get("step_title") or "",
                                            ("  (waiting for your answer: %s)" % obj["gate"]) if obj.get("gate") else ""))
    lines.append("Time left: about %s" % progress._fmt_eta(p.get("eta_s") or [0, 0]))
    lines.append("Families: %s" % obj.get("families"))
    lines.append("Details: %s" % obj.get("progress_file"))
    return "\n".join(ln for ln in lines if ln) + "\n"


def list_text(obj):
    """`ub list` for people: one line per run."""
    runs = obj.get("runs") or []
    if not runs:
        return "No runs under %s\n" % obj.get("root")
    out = []
    for r in runs:
        step = r.get("step")
        out.append("%-48s %-8s %s%s" % (os.path.basename(r.get("run") or ""), r.get("status") or "",
                                        ("step %s  " % step) if step else "", r.get("topic") or ""))
    return "\n".join(out) + "\n"


# ================================================================ --text parsing (4.11)

def parse_text(text):
    """Leading tokens are consumed while they match; the rest is the topic (or the idea in proposal mode)."""
    out = {"mode": None, "variant": None, "autopilot": None, "private": False, "with_ce_ideate": False,
           "command": None, "rest": ""}
    words = (text or "").strip().split()
    i = 0
    while i < len(words):
        w = words[i].lower().strip(",")
        if w in MODES and out["mode"] is None:
            out["mode"] = w
        elif w in VARIANTS and out["variant"] is None:
            out["variant"] = w
        elif w in AUTOPILOTS and out["autopilot"] is None:
            out["autopilot"] = w
        elif w == "private":
            out["private"] = True
        elif w == "with-ce-ideate":
            out["with_ce_ideate"] = True
        elif w in COMMAND_TOKENS and i == 0:
            out["command"] = w
            i += 1
            break
        else:
            break
        i += 1
    out["rest"] = " ".join(words[i:]).strip()
    return out


VARIANT_RULES = [
    ("growth", r"\b(activation|onboarding|retention|churn|conversion)\b"),
    ("research", r"\b(research question|hypothes[ie]s|study|paper)\b"),
    ("marketing", r"\b(campaign|ads?|brand|marketing)\b"),
    ("naming", r"\b(name for|naming)\b"),
    ("creative", r"\b(story|film|art|song|creative)\b"),
    ("software", r"\b(feature|refactor|codebase|api|bug|in this repo)\b"),
    ("product", r"\b(startup|product|app|business|saas|platform)\b"),
]


def is_source_repo(cwd):
    if not os.path.isdir(os.path.join(cwd, ".git")):
        return False
    for dirpath, dirs, files in os.walk(cwd):
        depth = os.path.relpath(dirpath, cwd).count(os.sep)
        dirs[:] = [d for d in dirs if not d.startswith(".") and d not in ("node_modules", "brainstorm")] \
            if depth < 2 else []
        if any(f.endswith(SOURCE_EXT) for f in files):
            return True
    return False


def infer_variant(topic, cwd=None):
    low = (topic or "").lower()
    for variant, rx in VARIANT_RULES:
        if re.search(rx, low):
            if variant == "software" and not is_source_repo(cwd or os.getcwd()):
                continue
            return variant
    return "general"


def component_map(text):
    comps = dict((v, None) for v in COMPONENT_KEYS.values())
    for raw in re.split(r"[,\s]+", text or ""):
        name = raw.strip()
        if not name:
            continue
        leaf = name.split(":")[-1].split("/")[-1].lower()
        key = COMPONENT_KEYS.get(leaf)
        if key and not comps.get(key):
            comps[key] = name
    return comps


# ================================================================ context helpers

def make_deps():
    return pipeline.Deps()


def open_run(run_arg, root=None):
    if run_arg:
        run_dir = os.path.abspath(os.path.expanduser(run_arg))
        if not os.path.isdir(run_dir):
            raise EngineError("run folder not found: %s" % textio.to_posix(run_dir),
                              fix=["ub list --json"])
        return run_dir, None
    run_dir, how = st.newest_unfinished(root)
    if not run_dir:
        raise EngineError("no unfinished run found", fix=['ub init --host <host> --text "<topic>" --json'])
    return run_dir, how


def load_ctx(run_dir, deps=None):
    state = st.load(run_dir)
    return st.Ctx(run_dir, state, deps or make_deps())


def with_lock(ctx, fn):
    lock = st.Lock(ctx.run_dir, ctx.host_agent)
    if not lock.acquire():
        holder = lock.holder() or {}
        c = cards.auto(ctx, None, "another session is driving this run (pid %s, %s); waiting" % (
            holder.get("pid"), holder.get("host")), wait_s=30)
        return c
    try:
        return fn(lock)
    finally:
        lock.release()


# ================================================================ init

def family_table(detect_result, host_agent, host_family, only=None, cfg=None):
    fams = {}
    dfam = (detect_result or {}).get("families") or {}
    for f in FAMILY_ORDER:
        info = dfam.get(f) or {}
        chain = list(info.get("chain") or [])
        ok = bool(info.get("available"))
        backend = info.get("backend") or (chain[0] if chain else None)
        if chain == ["host"] or backend == "host":
            backend = "host"
        reason = "; ".join(info.get("notes") or []) if not ok else ""
        fams[f] = {"status": "ok" if ok else "unavailable", "backend": backend if ok else None,
                   "web": bool(info.get("web")) if ok else False, "reason": reason, "chain": chain}
        if only and f not in only and f != host_family:
            fams[f]["status"] = "excluded"
            fams[f]["reason"] = "not in --families"
    # the host family: a host agent can always answer through its own sub-agents (HOST_BATCH) [U-14]
    hf = fams.get(host_family)
    if host_agent != "terminal" and hf is not None and hf["status"] != "ok":
        hf.update({"status": "ok", "backend": "host", "web": False,
                   "reason": "no headless backend: the host agent runs these jobs (HOST_BATCH)"})
    if host_agent == "terminal":
        for f, info in fams.items():
            if info.get("backend") == "host":
                info.update({"status": "unavailable", "backend": None,
                             "reason": "reachable only through an agent's sub-agents; dropped in terminal mode"})
    return fams


def preflight(ctx, fams):
    """One parallel PING per candidate family (5.5). A failure marks the family unavailable."""
    jobs = []
    probes = {}
    vendors_ok = (ctx.state.get("privacy") or {}).get("vendors", True)
    web_ok = (ctx.state.get("privacy") or {}).get("web", True)
    from ublib import detect as detect_mod
    from ublib import families as fam_mod
    fake = bool(fam_mod.fake_families())
    for f, info in fams.items():
        if info.get("status") != "ok" or info.get("backend") == "host":
            continue
        if not vendors_ok and f != ctx.host_family:
            continue  # private: no call of any kind goes to another vendor
        jid = "0.1-ping-%s" % f
        prompt_rel = "prompts/%s.prompt.md" % jid
        from ublib.engine import builders
        text = registry.load_template("PING")
        try:
            text = builders.fill(ctx, text, {"family": f, "template": "PING"}) if text else None
        except EngineError:
            text = None
        ctx.write(prompt_rel, (text or "Reply with the single word PONG.").strip() + "\n")
        job = {"schema": 1, "run": textio.to_posix(ctx.run_dir), "id": jid, "step": "0.1", "kind": "ping",
               "template": "PING", "family": f, "tier": "fast", "prompt_file": prompt_rel,
               "out": "logs/ping/%s.txt" % f, "tools": "none", "cwd": "empty", "repo_root": None, "timeout_s": 60,
               "retries": 0, "contract": {"type": "text", "regex": "PONG", "min_chars": 4}, "schema_file": None,
               "split": None, "fallback": [], "provisional": False,
               "privacy": privacy_mod.job_privacy(ctx.state, f, "none", "empty"), "host_prompt_file": None,
               "stub": {}}
        ctx.write_json("jobs/%s.json" % jid, job)
        jobs.append(job)
        info["preflight"] = True
        # [U-5] `codex exec -c web_search=live` is not confirmed to search: one live web job checks it
        if info.get("web") and info.get("backend") == "codex-cli" and web_ok and not fake:
            wid = "0.1-webprobe-%s" % f
            wrel = "prompts/%s.prompt.md" % wid
            ctx.write(wrel, detect_mod.WEB_PROBE_PROMPT + "\n")
            wjob = dict(job, id=wid, prompt_file=wrel, out="logs/ping/%s.web.txt" % f, tools="web",
                        kind="researcher", tier="default", timeout_s=180,
                        contract={"type": "text", "min_chars": 1},
                        privacy=privacy_mod.job_privacy(ctx.state, f, "web", "empty"))
            ctx.write_json("jobs/%s.json" % wid, wjob)
            jobs.append(wjob)
            probes[f] = wjob
    if not jobs:
        return
    batch = ctx.deps.batch
    try:
        res = batch.run_foreground(jobs, parallel=4, budget_s=90)
    except TypeError:
        res = batch.run_foreground([ctx.path("jobs", j["id"] + ".json") for j in jobs], parallel=4, budget_s=90)
    done = set(res.get("done") or [])
    for j in jobs:
        if j["id"].startswith("0.1-webprobe-"):
            continue  # a failed web probe only turns web off (below); the family's PING decides availability
        f = j["family"]
        jid = j["id"]
        ok = jid in done or any(isinstance(d, dict) and d.get("id") == jid for d in res.get("done") or [])
        if not ok:
            meta = ctx.read_json(j["out"] + ".meta.json", {}) or {}
            reason = "preflight PING failed (%s)" % (meta.get("error_class") or meta.get("status") or "no answer")
            if f == ctx.host_family and ctx.host_agent != "terminal":
                fams[f].update({"backend": "host", "web": False, "reason": reason + "; host sub-agents used"})  # [U-14]
            else:
                fams[f].update({"status": "unavailable", "backend": None, "reason": reason})
    for f, wjob in probes.items():
        if fams[f].get("status") != "ok" or fams[f].get("backend") == "host":
            continue
        try:
            text = ctx.read(wjob["out"])
        except (OSError, ValueError):
            text = ""
        if not detect_mod.web_probe_passed(text):
            fams[f]["web"] = False
            st.add_note(ctx.state, "%s: the live web-search probe found no search results, so web jobs go to other "
                                   "families [U-5]" % f)


def cmd_init(a, deps=None, terminal=False):
    deps = deps or make_deps()
    parsed = parse_text(a.text or "")
    if parsed["command"] and not terminal:
        rest = parsed["rest"] or None
        if parsed["command"] == "continue":
            return cmd_continue(argparse.Namespace(run=rest, host=a.host, root=a.root, json=a.json), deps)
        if parsed["command"] == "status":
            return cmd_status(argparse.Namespace(run=rest, json=a.json, root=a.root), deps)
        if parsed["command"] == "doctor":
            return cmd_doctor(argparse.Namespace(live=False, json=a.json), deps)
        if parsed["command"] == "stop":
            return cmd_stop(argparse.Namespace(run=rest, json=a.json, root=a.root), deps)
    host = a.host or "other"
    if host not in HOSTS:
        raise UsageError("--host must be one of %s" % ", ".join(HOSTS))
    os.environ["UB_HOST"] = host
    mode = a.mode or parsed["mode"] or "standard"
    if a.idea_file:
        mode = "proposal"
    if mode not in MODES:
        raise UsageError("--mode must be one of %s" % ", ".join(MODES))
    topic = parsed["rest"]
    idea_text = ""
    if a.idea_file:
        idea_text = " ".join(textio.read_text(a.idea_file).split())
        topic = topic or idea_text
    elif mode == "proposal":
        idea_text = topic
    variant = a.variant or parsed["variant"] or infer_variant(topic)
    if variant not in VARIANTS:
        raise UsageError("--variant must be one of %s" % ", ".join(VARIANTS))
    autopilot = a.autopilot or parsed["autopilot"] or "guided"
    if autopilot not in AUTOPILOTS:
        raise UsageError("--autopilot must be one of %s" % ", ".join(AUTOPILOTS))
    root, root_note = st.run_root(a.root)
    run_dir = st.new_run_dir(root, topic or "untitled run")
    os.makedirs(run_dir, exist_ok=True)
    try:
        rc, _, _ = deps.bs(["init", run_dir], run_dir)
    except EngineError:
        pass
    st.ensure_run_dirs(run_dir)
    only = None
    if a.families and a.families != "auto":
        only = [base_family(f.strip()) for f in a.families.split(",") if f.strip()]
    detect_result = {}
    st_note = None
    try:
        detect_result = deps.detect(live=False, only=None) or {}
    except EngineError as e:
        detect_result = {"families": {}, "host": {}}
        st_note = str(e)
    host_info = detect_result.get("host") or {}
    host_family = host_info.get("family") or os.environ.get("UB_HOST_FAMILY") or HOST_DEFAULT_FAMILY.get(host)
    family_source = host_info.get("source") or ("env" if os.environ.get("UB_HOST_FAMILY") else "default")
    fams = family_table(detect_result, host, host_family, only)
    if host == "terminal" or not host_family:
        avail = [f for f in FAMILY_ORDER if fams[f]["status"] == "ok"]
        if host_family not in avail:
            host_family = avail[0] if avail else "claude"
            family_source = "default"
    runner = cards.default_runner()
    state = st.new_state(run_dir, topic, host, host_family, family_source, mode=mode, variant=variant,
                         autopilot=autopilot, lang=a.lang or "en", python=cards.python_launcher(), runner=runner,
                         project_dir=os.getcwd())
    state["families"] = fams
    state["idea_text"] = idea_text
    state["components"] = component_map(a.components)
    state["options"]["with_ce_ideate"] = bool(parsed["with_ce_ideate"])
    private = parsed["private"] or a.privacy == "private"
    defaults = st.config_get("privacy_defaults")
    if private:
        state["privacy"].update({"web": False, "vendors": False, "code": False})
        state["options"]["private"] = True
    elif isinstance(defaults, dict):
        for k in ("web", "vendors", "code"):
            if defaults.get(k) is not None:
                state["privacy"][k] = bool(defaults[k])
    state["options"]["explicit_privacy"] = bool(private or a.privacy)
    if root_note:
        st.add_note(state, root_note)
    if st_note:
        st.add_note(state, "family detection failed: %s" % st_note)
    ctx = st.Ctx(run_dir, state, deps)
    if a.seeds_file:
        shutil.copy2(a.seeds_file, ctx.path("00_HUMAN_SEEDS.md"))
    if not a.no_preflight:
        try:
            preflight(ctx, fams)
        except EngineError as e:
            st.add_note(state, "preflight skipped: %s" % e)
    registry.reseat(ctx)
    for f, info in fams.items():
        if info.get("status") == "unavailable" and info.get("reason"):
            st.add_note(state, "%s: %s" % (f, info["reason"]))
    st.set_step(state, "0.1", "done", note="run created")
    st.save(run_dir, state)
    st.register_run(run_dir, topic)
    st.append_event(run_dir, "init", host=host, mode=mode, variant=variant)
    steps = pipeline.load_steps()
    if terminal:
        return ctx
    return with_lock(ctx, lambda lock: pipeline.advance(ctx, steps, 0, lock))


# ================================================================ commands

def cmd_next(a, deps=None):
    run_dir, how = open_run(a.run)
    ctx = load_ctx(run_dir, deps)
    steps = pipeline.load_steps()
    wait = a.wait_s if a.wait_s is not None else int(((ctx.state.get("exec") or {}).get("wait_s", 540)))
    return with_lock(ctx, lambda lock: pipeline.advance(ctx, steps, wait, lock))


def cmd_answer(a, deps=None):
    run_dir, _ = open_run(a.run)
    ctx = load_ctx(run_dir, deps)
    steps = pipeline.load_steps()
    gid = a.gate
    if gid not in gates.FIELDS:
        raise UsageError("unknown gate %s" % gid)
    by = "human"
    if a.file:
        try:
            provided = textio.read_json(a.file)
        except (OSError, ValueError) as e:
            pgid, step = pipeline.pending_gate(ctx, steps)
            return pipeline.finalize(ctx, steps, pipeline.human_card(
                ctx, step, gid, error="the answer file is not valid JSON (%s); write it again" % e))
        if not isinstance(provided, dict):
            provided = {"reply": str(provided)}
    elif a.choice is not None:
        provided = gates.from_choice(gid, a.choice)
    elif a.default:
        provided = gates.default_answer(gid)
    elif a.skip:
        provided = {"reply": "skip", "skip": True}
        if gid == "G8a":
            provided = {"reply": "skip", "skip": True}
    else:
        raise UsageError("answer needs --file, --choice, --default or --skip")
    return with_lock(ctx, lambda lock: pipeline.answer_gate(ctx, steps, gid, provided, lock, by=by))


def cmd_done(a, deps=None):
    run_dir, _ = open_run(a.run)
    ctx = load_ctx(run_dir, deps)
    steps = pipeline.load_steps()
    return with_lock(ctx, lambda lock: pipeline.host_done(ctx, steps, a.step, lock))


def reseat_for_host(ctx, host):
    """Cross-host continue (6.10): re-detect families, re-seat what disappeared, record it as PROVISIONAL."""
    import copy as _copy
    from ublib.engine import seats as seats_mod
    s = ctx.state
    old_seats = _copy.deepcopy(s.get("seats") or {})
    old_host = ctx.host_family
    os.environ["UB_HOST"] = host
    try:
        det = ctx.deps.detect(live=False, only=None) or {}
    except EngineError:
        det = {}
    agent_family = ((det.get("host") or {}).get("family")) or HOST_DEFAULT_FAMILY.get(host) or old_host
    fams = family_table(det, host, agent_family)
    for f, info in (s.get("families") or {}).items():
        if info.get("status") == "excluded" and f in fams:
            fams[f]["status"] = "excluded"
    # the run keeps its host family while a real backend still reaches it; otherwise the new agent's family
    keep = (fams.get(old_host) or {}).get("status") == "ok" and (fams.get(old_host) or {}).get("backend") != "host"
    run_host = old_host if keep or old_host == agent_family else agent_family
    if not keep and host == "terminal":
        run_host = next((f for f in FAMILY_ORDER if (fams.get(f) or {}).get("status") == "ok"), old_host)
    s["families"] = fams
    s["host"] = {"agent": host, "family": run_host,
                 "family_source": (det.get("host") or {}).get("source", "default") if run_host == agent_family
                 else (s.get("host") or {}).get("family_source", "default")}
    s["exec"]["wait_s"] = HOST_WAIT_S.get(host, 50)
    registry.reseat(ctx)  # a full 6.6 assignment on what is left ...
    available = [f for f, i in fams.items() if i.get("status") == "ok" and st.family_allowed(s, f)]
    seats, changes = seats_mod.reseat_minimal(old_seats, s["seats"], available, run_host)  # ... applied minimally
    s["seats"] = seats
    if run_host != old_host:
        changes.insert(0, ("host family", old_host, run_host))
    for key, before, after in changes:
        st.add_provisional(s, "continue --host %s (%s)" % (host, key), before, after,
                           "%s is not available on this host" % before)
    return len(changes)


def cmd_continue(a, deps=None):
    run_dir, how = open_run(a.run, getattr(a, "root", None))
    ctx = load_ctx(run_dir, deps)
    steps = pipeline.load_steps()
    note = "continuing %s%s" % (os.path.basename(run_dir), (" (%s)" % how) if how else "")
    host = getattr(a, "host", None)
    if host and host != ctx.host_agent:
        n = reseat_for_host(ctx, host)
        note += "; host is now %s (%d seats changed)" % (host, n)
        st.save(run_dir, ctx.state)
    card = with_lock(ctx, lambda lock: pipeline.advance(ctx, steps, 0, lock))
    card.setdefault("notes", []).insert(0, note)
    return card


def cmd_status(a, deps=None):
    run_dir, _ = open_run(a.run, getattr(a, "root", None))
    ctx = load_ctx(run_dir, deps)
    steps = pipeline.load_steps()
    cur = pipeline.current_step(ctx, steps)
    block = progress.progress_block(ctx, steps, cur)
    return {"ub": ENGINE_VERSION, "run": textio.to_posix(run_dir), "status": ctx.state.get("status"),
            "mode": ctx.mode, "variant": ctx.variant, "autopilot": ctx.autopilot,
            "step": cur["id"] if cur else None, "step_title": cur.get("title") if cur else None,
            "gate": cur.get("gate") if cur and cur.get("type") == "HUMAN" else None, "progress": block,
            "families": progress.families_line(ctx), "provisional": ctx.state.get("provisional") or [],
            "progress_file": textio.to_posix(ctx.path("PROGRESS.md"))}


def synthetic_ctx(mode, variant, families, host="claude-code", deps=None):
    fams = [base_family(f) for f in families] or ["claude"]
    host_family = fams[0]
    state = st.new_state("plan-preview", "preview", host, host_family, mode=mode, variant=variant)
    state["run"] = "plan-preview"
    web_ok = {"claude": True, "gpt": True, "kimi": False, "glm": False}
    state["families"] = dict((f, {"status": "ok" if f in fams else "unavailable",
                                  "backend": "cli" if f in fams else None, "web": web_ok.get(f, False),
                                  "reason": ""}) for f in FAMILY_ORDER)
    ctx = st.Ctx(None, state, deps or make_deps(), sim=dict(pipeline.DEFAULT_SIM))
    registry.reseat(ctx)
    return ctx


def cmd_plan(a, deps=None):
    if a.run:
        run_dir, _ = open_run(a.run)
        ctx = load_ctx(run_dir, deps)
        ctx.sim = dict(pipeline.DEFAULT_SIM)
    else:
        mode = a.mode or "standard"
        variant = a.variant or "general"
        if mode not in MODES or variant not in VARIANTS:
            raise UsageError("plan needs a valid --mode and --variant")
        fams = [f.strip() for f in (a.families or "claude").split(",") if f.strip()]
        ctx = synthetic_ctx(mode, variant, fams, deps=deps)
    p = progress.plan(ctx)
    p["mode"], p["variant"] = ctx.mode, ctx.variant
    p["families"] = (ctx.state.get("seats") or {}).get("families")
    return p


def cmd_stop(a, deps=None):
    run_dir, _ = open_run(a.run, getattr(a, "root", None))
    ctx = load_ctx(run_dir, deps)
    n = 0
    try:
        n = ctx.deps.batch.stop_all(run_dir)
    except EngineError:
        raise
    st.append_event(run_dir, "stop", killed=n)
    return {"ub": ENGINE_VERSION, "run": textio.to_posix(run_dir), "stopped": int(n or 0),
            "say": "Stopped %d running worker(s). Continue later with: continue." % int(n or 0)}


def preview_from(ctx, sid):
    shadow = st.Ctx(ctx.run_dir, json.loads(json.dumps(ctx.state)), ctx.deps, sim=dict(pipeline.DEFAULT_SIM))
    steps = pipeline.load_steps()
    idx = pipeline.index_of(steps, sid)
    pipeline.current_step(shadow, steps)  # the same settling as supersede_from, so the preview counts what will run
    for s in steps[idx:]:
        st.set_step(shadow.state, s["id"], "pending")
    return progress.plan(shadow, pipeline.simulate(shadow, remaining_only=True))


def cmd_redo(a, deps=None):
    run_dir, _ = open_run(a.run)
    ctx = load_ctx(run_dir, deps)
    steps = pipeline.load_steps()
    pipeline.index_of(steps, a.step)
    prev = preview_from(ctx, a.step)
    if not a.yes:
        return {"ub": ENGINE_VERSION, "run": textio.to_posix(run_dir), "redo": a.step, "preview": prev,
                "say": "Redo moves the outputs of %s and every later step to _superseded/ and runs them again "
                       "(about %d calls). Confirm with --yes." % (a.step, prev["calls"]["expected"]),
                "confirm_cmd": '%s redo "%s" %s --yes' % (cards.runner_of(ctx.state), textio.to_posix(run_dir),
                                                          a.step)}

    def go(lock):
        moved = pipeline.supersede_from(ctx, steps, a.step)
        st.save(run_dir, ctx.state)
        card = pipeline.advance(ctx, steps, 0, lock)
        card.setdefault("notes", []).insert(0, "redo %s: %d files moved to _superseded/" % (a.step, len(moved)))
        return card
    return with_lock(ctx, go)


def cmd_switch(a, deps=None):
    run_dir, _ = open_run(a.run)
    ctx = load_ctx(run_dir, deps)
    steps = pipeline.load_steps()
    if not a.arch and not a.idea:
        raise UsageError("switch needs --arch LABEL or --idea ID")
    target = "12.10" if a.arch else "12.1"
    if a.arch and a.arch not in registry.arch_labels(ctx):
        raise EngineError("%s is not an architecture candidate (%s)" % (a.arch, ", ".join(registry.arch_labels(
            ctx)) or "none yet"))
    if not a.yes:
        prev = preview_from(ctx, target)
        return {"ub": ENGINE_VERSION, "run": textio.to_posix(run_dir), "switch": a.arch or a.idea, "redo": target,
                "preview": prev, "say": "Switching redoes %s onward (about %d calls). Confirm with --yes."
                                        % (target, prev["calls"]["expected"]),
                "confirm_cmd": '%s switch "%s" %s --yes' % (cards.runner_of(ctx.state), textio.to_posix(run_dir),
                                                            ("--arch %s" % a.arch) if a.arch else
                                                            ("--idea %s" % a.idea))}

    def go(lock):
        if a.arch:
            pipeline.switch_arch(ctx, steps, a.arch)
        else:
            pipeline.switch_idea(ctx, steps, a.idea)
        st.save(run_dir, ctx.state)
        return pipeline.advance(ctx, steps, 0, lock)
    return with_lock(ctx, go)


def cmd_probe_result(a, deps=None):
    run_dir, _ = open_run(a.run)
    ctx = load_ctx(run_dir, deps)
    steps = pipeline.load_steps()
    result = a.result.upper()
    if result not in ("PASSED", "MISSED", "INCONCLUSIVE"):
        raise UsageError("result must be PASSED, MISSED or INCONCLUSIVE")
    note = textio.read_text(a.note_file) if a.note_file else ""

    def go(lock):
        effects = gates.probe_result(ctx, result, note)
        if ctx.state.get("status") == "done" and effects:
            ctx.state["status"] = "active"
        pipeline.apply_effects(ctx, steps, effects)
        st.save(run_dir, ctx.state)
        card = pipeline.advance(ctx, steps, 0, lock)
        card.setdefault("notes", []).insert(0, "probe result recorded: %s" % result)
        return card
    return with_lock(ctx, go)


def cmd_import(a, deps=None):
    run_dir, _ = open_run(a.run)
    ctx = load_ctx(run_dir, deps)
    steps = pipeline.load_steps()
    name = re.sub(r"[^A-Za-z0-9_-]+", "_", os.path.splitext(os.path.basename(a.file))[0])[:40] or "import"
    rel = "pool/IMPORT_%s.md" % name
    ctx.write(rel, textio.read_text(a.file))

    def go(lock):
        if st.step_state(ctx.state, "5.1") in ("done", "running", "blocked"):
            pipeline.supersede_from(ctx, steps, "5.1")
        st.save(run_dir, ctx.state)
        card = pipeline.advance(ctx, steps, 0, lock)
        card.setdefault("notes", []).insert(0, "imported %s; the pool is re-curated from stage 5" % rel)
        return card
    return with_lock(ctx, go)


def cmd_attach_s1(a, deps=None):
    run_dir, _ = open_run(a.run)
    ctx = load_ctx(run_dir, deps)
    ctx.write("pool/S1_ce-ideate.md", textio.read_text(a.doc))
    if a.raw:
        ctx.write("pool/S1_ce-ideate_raw.md", textio.read_text(a.raw))
    return {"ub": ENGINE_VERSION, "run": textio.to_posix(run_dir), "ok": True,
            "written": [textio.to_posix(ctx.path("pool/S1_ce-ideate.md"))] +
            ([textio.to_posix(ctx.path("pool/S1_ce-ideate_raw.md"))] if a.raw else []),
            "then": '%s done "%s" 4.1c --json' % (cards.runner_of(ctx.state), textio.to_posix(run_dir))}


def cmd_render(a, deps=None):
    from ublib.engine import render
    run_dir, _ = open_run(a.run)
    ctx = load_ctx(run_dir, deps)
    if not ctx.exists("11_PROPOSAL/PROPOSAL.md"):
        raise EngineError("11_PROPOSAL/PROPOSAL.md does not exist yet")
    out = render.render_pack(ctx, make_zip=a.zip)
    return dict({"ub": ENGINE_VERSION, "run": textio.to_posix(run_dir), "ok": True}, **out)


def cmd_export(a, deps=None):
    from ublib.engine import render
    run_dir, _ = open_run(a.run)
    ctx = load_ctx(run_dir, deps)
    res = render.export(ctx, a.format)
    return dict({"ub": ENGINE_VERSION, "run": textio.to_posix(run_dir)}, **res)


def cmd_doctor(a, deps=None):
    from ublib.engine import SK_DIR, TEMPLATES_DIR, PIPELINE_FILE, ESTIMATES_FILE, BS_PY, FAMILY_PY
    deps = deps or make_deps()
    checks = []

    def add(cid, ok, msg, warn=False):
        checks.append({"id": cid, "status": "PASS" if ok else ("WARN" if warn else "FAIL"), "message": msg})
    add("python", sys.version_info >= (3, 9), "Python %s" % sys.version.split()[0])
    try:
        steps = pipeline.load_steps()
        add("pipeline", True, "%d steps" % len(steps))
    except EngineError as e:
        add("pipeline", False, str(e))
        steps = []
    add("estimates", os.path.exists(ESTIMATES_FILE), textio.to_posix(ESTIMATES_FILE), warn=True)
    missing = []
    for s in steps:
        tpl = (s.get("job") or {}).get("template")
        if tpl and "{" not in tpl and not os.path.exists(registry.template_path(tpl)):
            missing.append(tpl)
        if s.get("type") == "HUMAN" and not os.path.exists(os.path.join(TEMPLATES_DIR, "gates", s["gate"] + ".md")):
            missing.append("gates/" + s["gate"])
    add("templates", not missing, "missing: %s" % ", ".join(sorted(set(missing))) if missing else
        "all referenced templates present", warn=True)
    add("bs.py", os.path.exists(BS_PY), textio.to_posix(BS_PY))
    add("family.py", os.path.exists(FAMILY_PY), textio.to_posix(FAMILY_PY))
    home = st.ub_home()
    try:
        os.makedirs(home, exist_ok=True)
        probe = os.path.join(home, ".ub-write-test")
        textio.write_text_atomic(probe, "ok\n")
        os.remove(probe)
        add("ub_home", True, textio.to_posix(home))
    except OSError as e:
        add("ub_home", False, "%s: %s" % (textio.to_posix(home), e))
    detect = None
    if os.path.exists(FAMILY_PY):
        from ublib import proc
        argv = [sys.executable, FAMILY_PY, "detect", "--json"] + (["--live"] if a.live else [])
        try:
            res = proc.run(argv, timeout_s=180)
            detect = textio.extract_json(textio.decode_bytes(res.stdout_bytes))
            add("detect", res.returncode == 0, "family.py detect exit %d" % res.returncode, warn=True)
        except Exception as e:
            add("detect", False, "family.py detect failed: %s" % e, warn=True)
    fams = (detect or {}).get("families") or {}
    n_ok = len([f for f, i in fams.items() if isinstance(i, dict) and i.get("available")])
    if detect is not None:
        add("families", n_ok >= 1, "%d model families available%s" % (
            n_ok, "" if n_ok >= 2 else " (cross-family judging needs 2; runs are PROVISIONAL)"), warn=n_ok >= 1)
    status = "fail" if any(c["status"] == "FAIL" for c in checks) else (
        "warn" if any(c["status"] == "WARN" for c in checks) else "pass")
    return {"ub": ENGINE_VERSION, "status": status, "checks": checks, "detect": detect,
            "skill_dir": textio.to_posix(SK_DIR)}


def cmd_config(a, deps=None):
    if a.action == "get":
        return {"key": a.key, "value": st.config_get(a.key)}
    if a.value is None:
        raise UsageError("config set needs a VALUE")
    st.config_set(a.key, st.parse_config_value(a.value))
    return {"key": a.key, "value": st.config_get(a.key), "file": textio.to_posix(st.config_path())}


def cmd_list(a, deps=None):
    root, _ = st.run_root(a.root)
    out = []
    for d in st.list_runs(root):
        try:
            s = textio.read_json(st.run_json_path(d))
        except (OSError, ValueError):
            s = {"legacy_v1": True}
        steps_state = s.get("steps") or {}
        cur = None
        for sid, v in steps_state.items():
            if v.get("state") in ("running", "blocked"):
                cur = sid
        out.append({"run": textio.to_posix(d), "topic": s.get("topic"), "mode": s.get("mode"),
                    "status": "done" if st.is_finished(d) else (s.get("status") or "active"), "step": cur,
                    "created_at": s.get("created_at")})
    return {"ub": ENGINE_VERSION, "root": textio.to_posix(root), "runs": out}


def cmd_run(a, deps=None):
    from ublib.engine import terminal
    deps = deps or make_deps()
    if a.cont is not None or not a.text:
        run_dir, _ = open_run(a.cont or None, a.root)
        ctx = load_ctx(run_dir, deps)
        if ctx.host_agent != "terminal":
            reseat_for_host(ctx, "terminal")
            st.save(run_dir, ctx.state)
    else:
        a.host = "terminal"
        ctx = cmd_init(a, deps, terminal=True)
    ctx.state.setdefault("exec", {})["wait_s"] = terminal.TERMINAL_WAIT_S
    steps = pipeline.load_steps()
    return with_lock(ctx, lambda lock: terminal.run_loop(ctx, steps, lock))


# ================================================================ argument parsing

def add_init_options(p):
    p.add_argument("--host", default=None)
    p.add_argument("--text", default="")
    p.add_argument("--components", default="")
    p.add_argument("--root", default=None)
    p.add_argument("--lang", default=None)
    p.add_argument("--mode", default=None)
    p.add_argument("--variant", default=None)
    p.add_argument("--autopilot", default=None)
    p.add_argument("--families", default="auto")
    p.add_argument("--privacy", default=None, choices=["default", "private"])
    p.add_argument("--seeds-file", dest="seeds_file", default=None)
    p.add_argument("--idea-file", dest="idea_file", default=None)
    p.add_argument("--no-preflight", dest="no_preflight", action="store_true")


def build_parser():
    p = Parser(prog="ub.py", add_help=True, description="ultimate-brainstorm engine")
    p.add_argument("--version", action="store_true")
    sub = p.add_subparsers(dest="cmd")

    def sp(name):
        q = sub.add_parser(name)
        q.add_argument("--json", action="store_true")
        return q
    q = sp("init")
    add_init_options(q)
    q = sp("next")
    q.add_argument("run", nargs="?")
    q.add_argument("--wait-s", dest="wait_s", type=int, default=None)
    q = sp("answer")
    q.add_argument("run")
    q.add_argument("gate")
    g = q.add_mutually_exclusive_group()
    g.add_argument("--file")
    g.add_argument("--choice")
    g.add_argument("--default", action="store_true")
    g.add_argument("--skip", action="store_true")
    q = sp("done")
    q.add_argument("run")
    q.add_argument("step")
    q = sp("continue")
    q.add_argument("run", nargs="?")
    q.add_argument("--host", default=None)
    q.add_argument("--root", default=None)
    q = sp("status")
    q.add_argument("run", nargs="?")
    q.add_argument("--root", default=None)
    q = sp("plan")
    q.add_argument("run", nargs="?")
    q.add_argument("--mode")
    q.add_argument("--variant")
    q.add_argument("--families")
    q = sp("run")
    add_init_options(q)
    q.add_argument("--continue", dest="cont", nargs="?", const="", default=None)
    q = sp("stop")
    q.add_argument("run", nargs="?")
    q.add_argument("--root", default=None)
    q = sp("redo")
    q.add_argument("run")
    q.add_argument("step")
    q.add_argument("--yes", action="store_true")
    q = sp("switch")
    q.add_argument("run")
    q.add_argument("--arch")
    q.add_argument("--idea")
    q.add_argument("--yes", action="store_true")
    q = sp("probe-result")
    q.add_argument("run")
    q.add_argument("result")
    q.add_argument("--note-file", dest="note_file")
    q = sp("import")
    q.add_argument("file")
    q.add_argument("run", nargs="?")
    q = sp("attach-s1")
    q.add_argument("run")
    q.add_argument("--doc", required=True)
    q.add_argument("--raw")
    q = sp("render")
    q.add_argument("run")
    q.add_argument("--zip", action="store_true")
    q = sp("export")
    q.add_argument("run")
    q.add_argument("--format", required=True, choices=["docx", "html"])
    q = sp("doctor")
    q.add_argument("--live", action="store_true")
    q = sp("config")
    q.add_argument("action", choices=["get", "set"])
    q.add_argument("key")
    q.add_argument("value", nargs="?")
    q = sp("list")
    q.add_argument("--root", default=None)
    return p


COMMANDS = {"init": cmd_init, "next": cmd_next, "answer": cmd_answer, "done": cmd_done, "continue": cmd_continue,
            "status": cmd_status, "plan": cmd_plan, "run": cmd_run, "stop": cmd_stop, "redo": cmd_redo,
            "switch": cmd_switch, "probe-result": cmd_probe_result, "import": cmd_import, "attach-s1": cmd_attach_s1,
            "render": cmd_render, "export": cmd_export, "doctor": cmd_doctor, "config": cmd_config, "list": cmd_list}


def main(argv=None, deps=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    as_json = "--json" in argv
    try:
        args = build_parser().parse_args(argv)
    except UsageError as e:
        sys.stderr.write("usage error: %s\n" % e)
        return 2
    except SystemExit as e:  # --help
        return int(e.code or 0)
    if args.version:
        sys.stdout.write("ub.py %s\n" % ENGINE_VERSION)
        return 0
    if not args.cmd:
        sys.stderr.write(__doc__)
        return 2
    try:
        result = COMMANDS[args.cmd](args, deps)
    except UsageError as e:
        sys.stderr.write("usage error: %s\n" % e)
        return 2
    except EngineError as e:
        emit(cards.blocked(None, e.say or str(e), fix=e.fix, error=str(e)), as_json)
        return 0
    except Exception as e:  # internal error: still print a BLOCKED card when possible
        sys.stderr.write(traceback.format_exc())
        try:
            emit(cards.blocked(None, "internal error: %s" % e, fix=["ub doctor --json"], error=repr(e)), as_json)
        except Exception:
            pass
        return 1
    if hasattr(result, "state") and hasattr(result, "run_dir"):
        result = {"run": textio.to_posix(result.run_dir)}
    emit(result, as_json)
    return 0


if __name__ == "__main__":
    sys.exit(main())
