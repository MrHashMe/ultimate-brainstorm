#!/usr/bin/env python3
"""family.py: model-family adapter CLI and worker entry point (ultimate-brainstorm kit, KIT_SPEC 4.7, 4.8, 5).

    family.py --version
    family.py detect   [--json] [--live] [--families claude,gpt,kimi,glm]
    family.py job      --job FILE                                  worker entry point (4.7)
    family.py call     --family F --prompt-file P --out O [--kind K] [--tools none|web|read|read+web]
                       [--cwd empty|repo] [--repo DIR] [--contract-file F | --contract-json JSON] [--schema F]
                       [--tier default|fast] [--timeout S] [--retries N] [--meta M] [--json]
    family.py batch    --jobs FILE [--parallel 4] [--budget-s 540] [--json]
    family.py selftest [--family F|all] [--live] [--json]
    family.py explain  --family F [--tools T] [--tier T] [--json]   argv and env var NAMES, never values

Exit codes: 0 ok, 2 usage, 3 family unavailable, 4 failed after retries and chain, 5 output invalid after repair,
6 timeout, 7 refused by policy, 8 run stopped (`job` only: no call, no meta). Python 3.9+, standard library only.
"""

import argparse
import json
import os
import shutil
import signal
import sys
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from ublib import KIT_VERSION  # noqa: E402
from ublib import adapter  # noqa: E402
from ublib import batch  # noqa: E402
from ublib import detect as detect_mod  # noqa: E402
from ublib import families as fam  # noqa: E402
from ublib import textio  # noqa: E402

EXIT_USAGE = 2
EXIT_STOPPED = batch.EXIT_STOPPED  # 8: the run is stopped (`job` only)
TOOLS = ("none", "web", "read", "read+web")
_SKIPPED = {"done": "already done for this prompt (the cached result stands; no call)",
            "running": "another worker holds this job (no call)",
            "finished": "another worker ran this job while this one waited (its result stands; no call)",
            "stopped": "the run is stopped (ub stop); continue the run to start it (no call)"}


def _utf8_stdout():
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def _print_json(obj):
    sys.stdout.write(json.dumps(obj, ensure_ascii=True) + "\n")
    sys.stdout.flush()


def _err(msg):
    sys.stderr.write("family.py: %s\n" % msg)


# ---------------------------------------------------------------- detect

def cmd_detect(args):
    only = [x.strip() for x in (args.families or "").split(",") if x.strip()] or None
    res = detect_mod.detect(fam.load_families(), live=args.live, only=only)
    if args.json:
        _print_json(res)
        return 0
    h = res["host"]
    print("host: %s (family %s, from %s)%s" % (h.get("agent"), h.get("family"), h.get("source"),
                                               "   [fake families]" if res.get("fake") else ""))
    for name, info in res["clis"].items():
        print("cli %-7s %s %s" % (name, info.get("version") or "-", info.get("path") or "not found"))
    for f, info in res["families"].items():
        state = "OK" if info["available"] else "unavailable"
        print("family %-7s %-11s backend=%s chain=%s web=%s %s" % (
            f, state, info.get("backend"), ",".join(info.get("chain") or []) or "-", "yes" if info.get("web") else "no",
            ("; ".join(info.get("notes") or [])) or ""))
    for r in res.get("reclassified") or []:
        print("reclassified: %s (%s -> %s) serves %s" % (r["cli"], r["source"], r["endpoint"], r["as"]))
    for f, line in (res.get("live") or {}).items():
        print("live %-7s %s" % (f, line))
    return 0


# ---------------------------------------------------------------- job (worker)

def _graceful_signals():
    """SIGTERM (and SIGBREAK on Windows) raise SystemExit, so finally blocks run and secret temp files are deleted."""
    def _exit(*_a):
        sys.exit(143)
    for name in ("SIGTERM", "SIGBREAK"):
        sig = getattr(signal, name, None)
        if sig is None:
            continue
        try:
            signal.signal(sig, _exit)
        except (ValueError, OSError, RuntimeError):
            pass


WORKER_MODULES = ("claude-cli", "codex-cli", "kimi-cli", "openai-chat-http", "anthropic-http", "stub")


def _preload():
    """Import every module a job can reach lazily (the backends, the privacy check) before the worker waits for its
    job: an update that replaces the kit while this worker runs must never mix two versions inside it. A module that
    cannot be imported is left alone here: the attempt that needs it fails and is recorded in the meta."""
    try:
        from ublib import backends
        from ublib.engine import privacy  # noqa: F401  (adapter.policy_check imports it lazily)
        for btype in WORKER_MODULES:
            backends.module_for(btype)
    except Exception:  # noqa: BLE001
        pass


def cmd_job(args):
    path = os.path.abspath(args.job)
    try:
        job = adapter.load_job(path)
        run_dir, _p, _o = adapter.check_job(job)
    except adapter.JobError as e:
        _err(str(e))
        return EXIT_USAGE
    job["_path"] = path
    _graceful_signals()
    _preload()
    # One worker per job (4.7): the marker takes the job's execution lock and re-checks the done rule first. A job
    # that another worker holds, or that is already done for this prompt, is not called again: exit 0, no outputs.
    # A stopped run (ub stop) starts no call either: exit 8, no outputs.
    with batch.WorkerMarker(run_dir, job["id"], job=job) as marker:
        if marker.skipped:
            sys.stdout.write("%s skipped job=%s: %s\n" % (textio.now_iso(), job["id"], _SKIPPED.get(
                marker.skipped, marker.skipped)))
            return EXIT_STOPPED if marker.skipped == "stopped" else 0
        try:
            meta = adapter.execute_job(job, progress=marker.update, job_file=path)
        except adapter.JobError as e:
            _err(str(e))
            return EXIT_USAGE
        except Exception as e:  # noqa: BLE001 - never die without a meta file (the job would count as dead)
            meta = adapter.crash_meta(job, "worker error: %s" % e.__class__.__name__)
    code = adapter.exit_code_for(meta.get("status"))
    sys.stdout.write("%s %s job=%s backend=%s attempts=%s exit=%d %s\n" % (
        textio.now_iso(), meta.get("status"), meta.get("id"), meta.get("backend"), meta.get("attempts"), code,
        meta.get("reason") or ""))
    return code


# ---------------------------------------------------------------- call (ad hoc)

def _load_contract(args):
    if args.contract_file:
        c = textio.read_json(args.contract_file)
    elif args.contract_json:
        c = json.loads(args.contract_json)
    else:
        c = {"type": "text"}
    if not isinstance(c, dict):
        raise ValueError("the contract must be a JSON object")
    if args.schema and c.get("type") == "json" and not c.get("schema"):
        c["schema"] = os.path.abspath(args.schema)
    return c


def cmd_call(args):
    prompt = os.path.abspath(args.prompt_file)
    out = os.path.abspath(args.out)
    if not os.path.isfile(prompt):
        _err("prompt file not found: %s" % args.prompt_file)
        return EXIT_USAGE
    try:
        contract = _load_contract(args)
    except (OSError, ValueError) as e:
        _err("bad contract: %s" % e)
        return EXIT_USAGE
    run_dir = os.path.dirname(out)
    os.makedirs(run_dir, exist_ok=True)
    jid = "call-%s" % os.urandom(4).hex()
    job = {"schema": 1, "run": textio.to_posix(run_dir), "id": jid, "step": "adhoc", "kind": args.kind,
           "template": "ADHOC", "family": args.family, "tier": args.tier, "prompt_file": textio.to_posix(prompt),
           "out": os.path.basename(out), "tools": args.tools, "cwd": args.cwd,
           "repo_root": os.path.abspath(args.repo) if args.repo else None, "timeout_s": args.timeout,
           "retries": args.retries, "contract": contract,
           "schema_file": textio.to_posix(os.path.abspath(args.schema)) if args.schema else None, "split": None,
           "fallback": [], "provisional": False, "privacy": {}, "host_prompt_file": None, "stub": {}}
    tmp = os.path.join(fam.ub_home(), "tmp")
    os.makedirs(tmp, exist_ok=True)
    job_file = os.path.join(tmp, "%s.job.json" % jid)
    textio.write_json_atomic(job_file, job)
    try:
        meta = adapter.execute_job(job, log=False, job_file=job_file)
    except adapter.JobError as e:
        _err(str(e))
        return EXIT_USAGE
    finally:
        try:
            os.remove(job_file)
        except OSError:
            pass
    if args.meta:
        textio.write_json_atomic(os.path.abspath(args.meta), meta)
    if args.json:
        _print_json(meta)
    else:
        print("%s family=%s backend=%s attempts=%s out=%s %s" % (meta["status"], meta["family"], meta["backend"],
                                                                  meta["attempts"], textio.to_posix(out),
                                                                  meta.get("reason") or ""))
    return adapter.exit_code_for(meta.get("status"))


# ---------------------------------------------------------------- batch

def cmd_batch(args):
    path = os.path.abspath(args.jobs)
    try:
        data = textio.read_json(path)
    except (OSError, ValueError) as e:
        _err("cannot read %s: %s" % (args.jobs, e.__class__.__name__))
        return EXIT_USAGE
    items = data.get("jobs") if isinstance(data, dict) else data
    if not isinstance(items, list):
        _err("the jobs file must hold a list (or {\"jobs\": [...]})")
        return EXIT_USAGE
    base = os.path.dirname(path)
    jobs = []
    for it in items:
        if isinstance(it, str):
            jobs.append(it if os.path.isabs(it) else os.path.join(base, it))
        elif isinstance(it, dict):
            jobs.append(it)
        else:
            _err("each job is a path or an object")
            return EXIT_USAGE
    try:
        res = batch.run_foreground(jobs, parallel=args.parallel, budget_s=args.budget_s)
    except (OSError, ValueError) as e:
        _err(str(e))
        return EXIT_USAGE
    if args.json:
        _print_json(res)
    else:
        print("done %d, failed %d, pending %d (%.1fs)" % (len(res["done"]), len(res["failed"]), len(res["pending"]),
                                                          res.get("elapsed_s", 0.0)))
    if res["failed"]:
        return 4
    if res["pending"]:
        return 6
    return 0


# ---------------------------------------------------------------- selftest

def cmd_selftest(args):
    cfg = fam.load_families()
    names = [f for f in cfg.get("order") or [] if f in (cfg.get("families") or {})]
    if args.family and args.family != "all":
        names = [args.family]
    saved = os.environ.get("UB_FAKE_FAMILIES")
    if not args.live:
        os.environ["UB_FAKE_FAMILIES"] = "1"  # fake round trip through the stub backend
    base = os.path.join(fam.ub_home(), "tmp")
    os.makedirs(base, exist_ok=True)
    results = {}
    try:
        det = detect_mod.detect(cfg, live=False, only=names)
        for f in names:
            run_dir = tempfile.mkdtemp(prefix="selftest-%s-" % f, dir=base)
            try:
                textio.write_text_atomic(os.path.join(run_dir, "prompts", "ping.prompt.md"),
                                         detect_mod.PING_PROMPT + "\n")
                job = {"schema": 1, "run": textio.to_posix(run_dir), "id": "selftest-%s" % f, "step": "selftest",
                       "kind": "ping", "template": "PING", "family": f, "tier": "default",
                       "prompt_file": "prompts/ping.prompt.md", "out": "ping.txt", "tools": "none", "cwd": "empty",
                       "timeout_s": detect_mod.PING_TIMEOUT_S, "retries": 0,
                       "contract": {"type": "text", "regex": "PONG", "min_chars": 1}, "privacy": {}, "stub": {}}
                meta = adapter.execute_job(job, detect_result=det, log=False)
                results[f] = {"status": meta["status"], "backend": meta.get("backend"),
                              "duration_s": meta.get("duration_s"), "reason": meta.get("reason") or ""}
            finally:
                shutil.rmtree(run_dir, ignore_errors=True)
    finally:
        if not args.live:
            if saved is None:
                os.environ.pop("UB_FAKE_FAMILIES", None)
            else:
                os.environ["UB_FAKE_FAMILIES"] = saved
    if args.json:
        _print_json({"live": bool(args.live), "families": results})
    else:
        for f, r in results.items():
            print("%-7s %-11s backend=%s %.1fs %s" % (f, r["status"], r["backend"], r["duration_s"] or 0.0,
                                                     r["reason"]))
    return 0 if results and all(r["status"] == "ok" for r in results.values()) else 4


# ---------------------------------------------------------------- explain

def _explain_backend(cfg, bid, label, tools, tier):
    from ublib import backends as bk
    base, alt = fam.split_label(label)
    b = fam.backend_cfg(cfg, bid)
    t = fam.backend_type(cfg, bid)
    ctx = bk.CallContext(job={"id": "explain"}, job_id="explain", job_file="<job.json>", backend_id=bid, bcfg=b,
                         btype=t, cfg=cfg, family=base, alt=alt,
                         alt_model=((cfg.get("families") or {}).get(base) or {}).get("alt_model") if alt else None,
                         tier=tier, tools=tools, cwd_mode="empty", call_dir="<tmp>", timeout_s=60,
                         ub_home=cfg.get("_ub_home"))
    entry = {"backend": bid, "type": t}
    if t in ("openai-chat-http", "anthropic-http"):
        entry["request"] = "POST %s" % b.get("url")
        entry["headers"] = (["Authorization"] if t == "openai-chat-http" else ["x-api-key", "anthropic-version"])
        entry["key_env"] = b.get("key_env")
        entry["enabled"] = b.get("enabled", True)
        return entry
    mod = bk.module_for(t)
    extra = {}
    if t == "claude-cli":
        from ublib import detect
        isolate = detect.claude_user_context(b, base, os.environ) == "isolate"
        carried = detect.claude_carried_settings(os.environ, bool(ctx.provider)) if isolate else {}
        if carried:  # names only: the values can be credentials
            entry["carried_settings"] = sorted(k for k in carried if k != "env") + \
                sorted("env.%s" % k for k in (carried.get("env") or {}))
        paths = {"exe": ctx.exe_name, "mcp": "<UB_HOME>/tmp/empty-mcp.json", "isolate": isolate,
                 "settings": "<tmp>/settings-XXXX.json (0600, deleted after the call)" if ctx.provider or carried
                 else None}
        if ctx.provider:
            try:
                token_env, token_var, _none = fam.provider_token(cfg, ctx.provider, {})  # names only
                names = sorted(fam.provider_settings_env(cfg, ctx.provider, tier).keys())
            except (KeyError, ValueError) as e:  # an unknown provider or a hand-edited entry of the wrong shape
                entry["error"] = str(e.args[0])
                return entry
            entry["settings_env_names"] = names + [token_var]
            entry["token_env"] = token_env
    elif t == "codex-cli":
        paths = {"exe": ctx.exe_name, "cwd": "<tmp>/ub-empty", "last": "<tmp>/last.txt",
                 "schema": "<schema_file>" if b.get("native_schema") else None}
    elif t == "kimi-cli":
        paths = {"exe": ctx.exe_name, "agent": "<tmp>/ub-<job-id>-agent.md", "skills": "<tmp>/ub-empty-skills"}
        extra = mod.extra_env(ctx)
        entry["agent_tools"] = mod.tools_list(tools)
    else:
        return entry
    entry["argv"] = mod.build_argv(ctx, paths)
    env = bk.child_env(ctx, extra)
    removed = sorted(k for k in os.environ if k not in env and k.upper() not in (x.upper() for x in env))
    entry["env_removed"] = removed
    entry["env_set"] = sorted(set(["UB_JOB_ID", "UB_JOB_FILE", "NO_COLOR"] + list(extra.keys()) +
                                  [k for k in env if k.upper() in ("CODEX_HOME", "ANTHROPIC_API_KEY",
                                                                   "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL",
                                                                   "OPENAI_API_KEY", "CODEX_API_KEY",
                                                                   "OPENAI_BASE_URL")
                                   or k.upper().startswith("KIMI_MODEL_") or k == b.get("token_env")]))
    entry["stdin"] = "prompt bytes" if t != "kimi-cli" else "none (the prompt is the agent-file body)"
    return entry


def cmd_explain(args):
    cfg = fam.load_families()
    base, _alt = fam.split_label(args.family)
    fcfg = (cfg.get("families") or {}).get(base)
    if not fcfg:
        _err("unknown family %r" % args.family)
        return EXIT_USAGE
    entries = [_explain_backend(cfg, bid, args.family, args.tools, args.tier) for bid in fcfg.get("backends") or []]
    res = {"family": args.family, "vendor": fam.vendor_of(args.family, cfg), "tools": args.tools, "tier": args.tier,
           "backends": entries}
    if args.json:
        _print_json(res)
        return 0
    print("family %s (vendor %s), tools %s, tier %s" % (args.family, res["vendor"], args.tools, args.tier))
    for e in entries:
        print("")
        print("[%s] type %s" % (e["backend"], e["type"]))
        if e.get("error"):
            print("  error: %s" % e["error"])
        if "argv" in e:
            print("  argv: %s" % json.dumps(e["argv"], ensure_ascii=True))
            print("  stdin: %s" % e["stdin"])
            print("  env set (names): %s" % ", ".join(e["env_set"]))
            print("  env removed (names): %s" % (", ".join(e["env_removed"]) or "-"))
        if e.get("settings_env_names"):
            print("  settings file env (names): %s" % ", ".join(e["settings_env_names"]))
        if e.get("agent_tools") is not None:
            print("  agent file tools: [%s]" % ", ".join(e["agent_tools"]))
        if "request" in e:
            print("  %s  headers: %s  key from: %s  enabled: %s" % (e["request"], ", ".join(e["headers"]),
                                                                    e["key_env"], e["enabled"]))
    return 0


# ---------------------------------------------------------------- main

def build_parser():
    p = argparse.ArgumentParser(prog="family.py", description="ultimate-brainstorm model-family adapter")
    p.add_argument("--version", action="version", version="family.py %s" % KIT_VERSION)
    sub = p.add_subparsers(dest="cmd")

    d = sub.add_parser("detect", help="detect CLIs, keys, endpoints and family chains")
    d.add_argument("--json", action="store_true")
    d.add_argument("--live", action="store_true")
    d.add_argument("--families", default=None)
    d.set_defaults(func=cmd_detect)

    j = sub.add_parser("job", help="worker entry point")
    j.add_argument("--job", required=True)
    j.set_defaults(func=cmd_job)

    c = sub.add_parser("call", help="ad hoc single call")
    c.add_argument("--family", required=True)
    c.add_argument("--prompt-file", required=True)
    c.add_argument("--out", required=True)
    c.add_argument("--kind", default="generator")
    c.add_argument("--tools", default="none", choices=TOOLS)
    c.add_argument("--cwd", default="empty", choices=("empty", "repo"))
    c.add_argument("--repo", default=None)
    g = c.add_mutually_exclusive_group()
    g.add_argument("--contract-file", default=None)
    g.add_argument("--contract-json", default=None)
    c.add_argument("--schema", default=None)
    c.add_argument("--tier", default="default", choices=("default", "fast"))
    c.add_argument("--timeout", type=int, default=None)
    c.add_argument("--retries", type=int, default=None)
    c.add_argument("--meta", default=None)
    c.add_argument("--json", action="store_true")
    c.set_defaults(func=cmd_call)

    b = sub.add_parser("batch", help="foreground batch")
    b.add_argument("--jobs", required=True)
    b.add_argument("--parallel", type=int, default=4)
    b.add_argument("--budget-s", type=float, default=None)
    b.add_argument("--json", action="store_true")
    b.set_defaults(func=cmd_batch)

    s = sub.add_parser("selftest", help="fake round trip (or --live PONG)")
    s.add_argument("--family", default="all")
    s.add_argument("--live", action="store_true")
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_selftest)

    e = sub.add_parser("explain", help="print argv and env var NAMES for a family")
    e.add_argument("--family", required=True)
    e.add_argument("--tools", default="none", choices=TOOLS)
    e.add_argument("--tier", default="default", choices=("default", "fast"))
    e.add_argument("--json", action="store_true")
    e.set_defaults(func=cmd_explain)
    return p


def main(argv=None):
    _utf8_stdout()
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_usage(sys.stderr)
        return EXIT_USAGE
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
