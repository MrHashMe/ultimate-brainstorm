"""execute_job(): backend chain, retries, validation, repair, policy guards, outputs (KIT_SPEC 4.4-4.7, 5.4, 5.6).

Frozen API (4.8):
    execute_job(job: dict) -> dict        runs the chain in-process; returns the meta dict; writes outputs

Extra keyword arguments (optional, not frozen): detect_result (skip detection), log (append logs/calls.jsonl,
default True), progress (callback(attempt_no, backend_id) for the running marker), job_file (abs path of the job
JSON, exported to children as UB_JOB_FILE). A job may carry "chain" (backend ids the driver resolved): detection is
then skipped and only what can change since the launch is re-checked (the executable, the key or token variable).

    request_reserve(job, cfg=None) -> int   worst-case backend requests one worker launch of the job can send

Outputs, all atomic: <out> only when valid; <out>.meta.json always (plus "split_warnings" when the FILE protocol
warned about the output written); <out>.failed.md on final failure (first line "FAMILY CALL FAILED: <reason>"); one
line per attempt in <run>/logs/calls.jsonl (meta keys + ts + "requests": the backend requests that attempt sent; a
job refused before any attempt writes no line), redacted.

Retries: before each retry on the same backend the worker waits a full-jitter back-off, uniform in
[0, min(60, 2^(n+1))] s for retry n (0-based), or the server's Retry-After; no wait after empty output. All attempts,
back-offs and the repair call share one job deadline, JOB_DEADLINE_FACTOR x timeout_s from the start. An attempt
starts only while at least min_attempt_s(timeout_s) is left; otherwise no new attempt starts and the last failure is
reported. A retry whose wait would leave less than that is not made: the chain moves on to its next backend (switching
needs no wait). An attempt cut short by the deadline that times out reports the earlier failure, if there is one.
"""

import json
import os
import re
import time

from . import families as fam
from . import filesproto
from . import proc
from . import redact
from . import textio
from . import validate
from .backends import (CallContext, backoff_delay, host_of, module_for, new_call_dir, now, pause, remove_quietly,
                       result, sweep_stale_calls, usage_block)

__all__ = ["execute_job", "load_job", "check_job", "exit_code_for", "policy_check", "backend_policy_check",
           "crash_meta", "request_reserve", "JobError", "EXIT_CODES", "JOB_ID_RE", "JOB_DEADLINE_FACTOR",
           "MIN_ATTEMPT_S", "min_attempt_s"]

JOB_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,80}$")
EXIT_CODES = {"ok": 0, "unavailable": 3, "failed": 4, "invalid": 5, "timeout": 6, "refused": 7}
TOOLS = ("none", "web", "read", "read+web")
_GLM_HOSTS = ("api.z.ai", "open.bigmodel.cn")
FAILED_OUTPUT_CHARS = 4000
MAX_SPLIT_WARNINGS = 20
JOB_DEADLINE_FACTOR = 2.0  # every attempt of one job (retries, backends, repair) ends within 2 x timeout_s
MIN_ATTEMPT_S = 30.0  # no attempt starts with less time than this (a quarter of a shorter timeout) left


class JobError(ValueError):
    """The job JSON is unusable (worker exit 2)."""


def min_attempt_s(timeout_s):
    """The least time before the job deadline an attempt needs to be started: a shorter one would spend a request
    on a call that cannot finish."""
    return min(MIN_ATTEMPT_S, float(timeout_s) / 4.0)


def exit_code_for(status):
    return EXIT_CODES.get(status, 4)


def load_job(path):
    """Read a job JSON file (tolerant). Raises JobError."""
    try:
        job = textio.read_json(path)
    except (OSError, ValueError) as e:
        raise JobError("cannot read job file %s: %s" % (textio.to_posix(path), e.__class__.__name__))
    if not isinstance(job, dict):
        raise JobError("job file is not a JSON object")
    return job


def check_job(job):
    """Validate the fields the worker needs; returns (run_dir, prompt_path, out_path). Raises JobError."""
    jid = job.get("id")
    if not isinstance(jid, str) or not JOB_ID_RE.match(jid):
        raise JobError("job id must match %s" % JOB_ID_RE.pattern)
    run = job.get("run")
    if not isinstance(run, str) or not run.strip():
        raise JobError("job.run is missing")
    run_dir = os.path.abspath(run)
    if not os.path.isdir(run_dir):
        raise JobError("run folder does not exist: %s" % textio.to_posix(run_dir))
    for key in ("prompt_file", "out", "family"):
        if not isinstance(job.get(key), str) or not job[key].strip():
            raise JobError("job.%s is missing" % key)
    prompt_path = os.path.abspath(os.path.join(run_dir, job["prompt_file"]))
    out_path = os.path.abspath(os.path.join(run_dir, job["out"]))
    if not filesproto.inside(run_dir, out_path) or out_path == run_dir:
        raise JobError("job.out must stay inside the run folder")
    if not os.path.isfile(prompt_path):
        raise JobError("prompt file does not exist: %s" % textio.to_posix(prompt_path))
    tools = job.get("tools") or "none"
    if tools not in TOOLS:
        raise JobError("job.tools must be one of %s" % ", ".join(TOOLS))
    if (job.get("cwd") or "empty") not in ("empty", "repo"):
        raise JobError("job.cwd must be empty or repo")
    if job.get("cwd") == "repo" and not (job.get("repo_root") and os.path.isdir(job["repo_root"])):
        raise JobError("job.cwd is repo but repo_root is not a folder")
    c = job.get("contract")
    if c is not None and not isinstance(c, dict):
        raise JobError("job.contract must be an object")
    split = job.get("split")
    if isinstance(split, dict) and split.get("root") and (c or {}).get("type") == "files" and \
            not (split.get("allowed") or c.get("allowed")):
        raise JobError("job.split.allowed is empty: a files job must name the files it may write")
    chain = job.get("chain")
    if chain is not None and not (isinstance(chain, list) and all(isinstance(b, str) for b in chain)):
        raise JobError("job.chain must be a list of backend ids")
    return run_dir, prompt_path, out_path


# ---------------------------------------------------------------- policy (5.6)

def _read_run(run_dir):
    path = os.path.join(run_dir, "run.json")
    if not os.path.isfile(path):
        return None
    try:
        data = textio.read_json(path)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _prompt_text(job):
    try:
        return textio.read_text(os.path.join(os.path.abspath(job.get("run") or ""), job.get("prompt_file") or ""))
    except (OSError, ValueError):
        return None


def policy_check(job, cfg, run, host_family=None, prompt=None):
    """Run-level guards 1-3. Returns a refusal reason or None.

    Rule 3 also checks the prompt bytes (C8): a prompt for a vendor other than the host's, with privacy.code not true,
    in a repo-labeled run (or stamped code_filtered by the engine) is refused when it still contains code
    (privacy.contains_code, the exact complement of the strip_code the engine applied). `prompt` is the prompt text;
    it is read from job.prompt_file when not given."""
    from .engine import privacy  # lazy: the engine package imports nothing from the worker side
    label = job.get("family") or ""
    vendor = fam.vendor_of(label, cfg)
    tools = job.get("tools") or "none"
    jp = job.get("privacy") if isinstance(job.get("privacy"), dict) else {}
    rp = (run or {}).get("privacy") if isinstance((run or {}).get("privacy"), dict) else {}
    if run is not None and not privacy.vendor_allowed(run, label, vendor):
        return "vendor %s is not in run.json privacy.allowed_vendors" % vendor
    if jp.get("vendor_ok") is False:
        return "the job is stamped vendor_ok=false"
    if "web" in tools.split("+"):
        if rp.get("web") is False:
            return "web tools requested while privacy.web is false"
        if jp.get("web_ok") is False:
            return "web tools requested while the job is stamped web_ok=false"
    host_vendor = fam.vendor_of(host_family, cfg) if host_family else None
    if host_vendor is None or vendor != host_vendor:
        run_code = rp.get("code") if run is not None else None
        if (job.get("cwd") or "empty") == "repo":
            if run is not None and run_code is not True:
                return "cwd repo for vendor %s while privacy.code is false" % vendor
            if jp.get("code_ok") is False:
                return "cwd repo for vendor %s while the job is stamped code_ok=false" % vendor
        labeled = run is not None and run_code is not True and privacy.repo_labeled(run, job.get("run"))
        if jp.get("code_filtered") is True or labeled:
            text = prompt if prompt is not None else _prompt_text(job)
            if text is None or privacy.contains_code(text):
                return "the prompt for vendor %s contains code while privacy.code is false" % vendor
    return None


def _glm_host(url):
    h = host_of(url)
    return any(h == g or h.endswith("." + g) for g in _GLM_HOSTS) or h == "z.ai" or h.endswith("bigmodel.cn")


def backend_policy_check(cfg, backend_id, family, environ=None):
    """Backend guards 4-6. Returns a refusal reason or None."""
    environ = os.environ if environ is None else environ
    b = fam.backend_cfg(cfg, backend_id)
    t = fam.backend_type(cfg, backend_id)
    base, _alt = fam.split_label(family)
    if t in ("openai-chat-http", "anthropic-http") and _glm_host(b.get("url")):
        path = ""
        try:
            from urllib.parse import urlparse
            path = urlparse(b.get("url") or "").path or ""
        except ValueError:
            pass
        # only the pay-as-you-go key may reach Z.ai over raw HTTP; the Coding Plan key never does
        if b.get("key_env") != "ZAI_PAYG_API_KEY" or "/coding/" in path:
            return "the GLM Coding Plan may only be used through supported tools (%s)" % backend_id
    if t == "kimi-cli" and b.get("env_model") and _glm_host(environ.get("KIMI_MODEL_BASE_URL") or ""):
        return "Kimi Code is not a GLM-supported tool (KIMI_MODEL_BASE_URL points at Z.ai)"
    if fam.strict_glm(cfg) and t in ("claude-cli", "codex-cli") and \
            (b.get("provider") == "glm" or base == "glm"):  # [U-20]
        return "families.glm.allow_scripted_plan_use is false: GLM runs only as the host family (HOST_BATCH)"
    return None


# ---------------------------------------------------------------- helpers

def _estimate(usage, prompt, text):
    if usage.get("source") in ("reported",):
        return usage
    if usage.get("source") == "none" and text is None:
        return usage
    return {"input_tokens": len(prompt or "") // 4, "output_tokens": len(text or "") // 4 if text else None,
            "cost_usd": None, "source": "estimated"}


def _write_failed(path, reason, meta, errors=None, last_output=None):
    lines = ["FAMILY CALL FAILED: %s" % reason, "",
             "- job: %s" % meta.get("id"), "- family: %s" % meta.get("family"),
             "- backend: %s" % meta.get("backend"), "- status: %s" % meta.get("status"),
             "- error_class: %s" % meta.get("error_class"), "- attempts: %s" % meta.get("attempts"),
             "- at: %s" % textio.now_iso()]
    if errors:
        lines += ["", "Validation errors:"] + ["- %s" % e for e in errors[:30]]
    if meta.get("stderr_tail"):
        lines += ["", "stderr tail:", meta["stderr_tail"]]
    if last_output:
        lines += ["", "--- last output (first %d chars) ---" % FAILED_OUTPUT_CHARS, last_output[:FAILED_OUTPUT_CHARS]]
    textio.write_text_atomic(path, redact.redact("\n".join(lines)) + "\n")


WRITE_ATTEMPTS = 3  # local retries when valid output cannot be written (an OSError here, never a model call)


def _validate_and_write(text, job, run_dir, out_path, warnings=None):
    """Validate against the contract; on success write <out> (and split files).

    Returns (ok, errors, io_error). errors are faults of the output (they earn the one repair call, 4.5). io_error is
    set when the output is valid but writing it failed on this machine even after WRITE_ATTEMPTS local tries: a
    repair call would only repeat a model call whose answer was fine (and record a second "ok" call for the job).
    warnings: a list that receives the FILE-protocol warnings of the output written (a duplicate STATUS block, STATUS
    problems), for the meta's "split_warnings" (4.6.3).
    """
    contract = job.get("contract") or {"type": "text"}
    ok, errors, parsed = validate.check_contract(text, contract, run_dir)
    if not ok:
        return False, errors, None
    io_error = None
    for n in range(WRITE_ATTEMPTS):
        if n:
            time.sleep(0.25 * n)
        errors, io_error, notes = _write_outputs(text, parsed, job, contract, run_dir, out_path)
        if errors:
            return False, errors, None
        if not io_error:
            if warnings is not None:
                warnings.extend(notes)
            return True, [], None
    return False, [], io_error


def _write_outputs(text, parsed, job, contract, run_dir, out_path):
    """Write the split files (FILE protocol) and <out>. Returns (output errors, io error text or None, split
    warnings). `parsed` is check_contract's result for text: the FILE blocks are not parsed a second time."""
    split = job.get("split") if isinstance(job.get("split"), dict) else None
    warnings = []
    if contract.get("type") == "files" and split and split.get("root"):
        root = os.path.join(run_dir, split["root"])
        if not filesproto.inside(run_dir, root):
            return ["split.root must stay inside the run folder"], None, []
        allowed = split.get("allowed") or contract.get("allowed") or []  # none named: nothing may be written
        status_out = os.path.join(run_dir, split["status_out"]) if split.get("status_out") else None
        if status_out and not filesproto.inside(run_dir, status_out):
            return ["split.status_out must stay inside the run folder"], None, []
        res = filesproto.split_output(text, root, allowed, status_out=status_out,
                                      required=contract.get("required"),
                                      status_required=bool(contract.get("status_trailer")), parsed=parsed)
        if res.get("io_error"):
            return [], "; ".join(res["errors"]) or "could not write the files", []
        if not res["ok"]:
            return res["errors"], None, []
        warnings = [str(w) for w in res.get("warnings") or []]
    if contract.get("type") == "json" and parsed is not None:
        body = json.dumps(parsed, indent=1, ensure_ascii=False) + "\n"
    else:
        body = text
    try:
        textio.write_text_atomic(out_path, body)
    except OSError as e:
        return [], "could not write %s: %s" % (textio.to_posix(out_path), e.__class__.__name__), []
    return [], None, warnings


def _attempt_secrets(cfg, bcfg, environ=None):
    """Values of the key variables this backend names (key_env, token_env, the provider's token_env), so redaction
    also scrubs keys whose variable names do not look secret (e.g. MY_ROUTER)."""
    env = os.environ if environ is None else environ
    names = [bcfg.get("key_env"), bcfg.get("token_env")]
    prov = bcfg.get("provider")
    if prov:
        names.append(_provider_field(cfg, prov, "token_env"))
    out = []
    for n in names:
        v = env.get(n) if isinstance(n, str) and n else None
        if isinstance(v, str) and v.strip():
            out.append(v.strip())
    return out


def _requests_of(res):
    """Backend requests one attempt sent (C6); a result without the field counts as 1."""
    n = res.get("requests")
    return n if isinstance(n, int) and not isinstance(n, bool) and n >= 0 else 1


def _log_attempt(run_dir, meta, attempt_res, backend_id, attempt_no, t_attempt, enabled, secrets=(), kind=None):
    if not enabled:
        return
    entry = dict(meta)
    if kind:
        entry["kind"] = kind  # per-kind wall-time recalibration (progress.plan)
    entry.update({"backend": backend_id, "attempts": attempt_no, "status": attempt_res.get("status"),
                  "exit_code": attempt_res.get("exit_code"), "error_class": attempt_res.get("error_class"),
                  "cmd": attempt_res.get("cmd", ""), "stderr_tail": attempt_res.get("stderr_tail", ""),
                  "usage": attempt_res.get("usage") or usage_block(), "model": attempt_res.get("model"),
                  "web_used": bool(attempt_res.get("web_used")), "duration_s": round(time.monotonic() - t_attempt, 2),
                  "requests": _requests_of(attempt_res), "reason": attempt_res.get("error", ""),
                  "ts": textio.now_iso()})
    entry["out_sha256"] = None
    try:
        textio.append_line(os.path.join(run_dir, "logs", "calls.jsonl"),
                           json.dumps(redact.redact_obj(entry, secrets), ensure_ascii=True, sort_keys=False))
    except OSError:
        pass


def _prompt_sha(prompt_path):
    try:
        return textio.sha256_file(prompt_path)
    except OSError:
        return None


def crash_meta(job, reason):
    """Write a 'failed' meta (and .failed.md) for a job whose worker hit an unexpected error; returns the meta. It
    carries the current prompt's sha256 (C5), so the job reads as failed for this prompt, not pending."""
    _run_dir, prompt_path, out_path = check_job(job)
    cwd = job.get("cwd") or "empty"
    meta = {"schema": 1, "id": job.get("id"), "family": job.get("family"), "vendor": None, "backend": None,
            "model": None, "tier": job.get("tier") or "default", "provisional": bool(job.get("provisional")),
            "status": "failed", "attempts": 0, "requests": 0, "exit_code": None, "error_class": "internal",
            "started": textio.now_iso(), "duration_s": 0.0, "prompt_sha256": _prompt_sha(prompt_path),
            "out_sha256": None, "usage": usage_block(), "tools": job.get("tools") or "none", "web_used": False,
            "cwd": cwd, "repo_read": cwd == "repo", "repaired": False, "cmd": "", "stderr_tail": "",
            "reason": reason}
    clean = redact.redact_obj(meta)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    textio.write_json_atomic(out_path + ".meta.json", clean)
    _write_failed(out_path + ".failed.md", reason, clean)
    return clean


# ---------------------------------------------------------------- chain, retries, request reserve

def _job_retries(job, cfg):
    """job.retries, else defaults.retries (0 is honored), else 1."""
    for r in (job.get("retries"), ((cfg or {}).get("defaults") or {}).get("retries")):
        if isinstance(r, int) and not isinstance(r, bool) and r >= 0:
            return r
    return 1


def _tries(cfg, bid):
    """Requests one attempt on a backend can send: an HTTP backend retries 429/5xx inside the attempt."""
    if fam.backend_type(cfg, bid) in ("openai-chat-http", "anthropic-http"):
        from .backends.http_openai import MAX_TRIES
        return MAX_TRIES
    return 1


_NATIVE_FAMILY = {"claude-cli": "claude", "codex-cli": "gpt"}


def _reseatable(cfg, base):
    """Native claude-cli / codex-cli backends that detection can seat in family `base` although they are not
    configured there: their own config (settings.json, config.toml) serves that family's vendor (5.5)."""
    if base not in fam.FAMILY_VENDORS:
        return []
    out = []
    for bid in (cfg.get("backends") or {}):
        b, t = fam.backend_cfg(cfg, bid), fam.backend_type(cfg, bid)
        if _NATIVE_FAMILY.get(t, base) != base and not b.get("provider") and not b.get("codex_home"):
            out.append(bid)
    return out


def _chain_ids(job, cfg):
    """The backends one launch of job can try: job["chain"] when the driver resolved it (C13); else every backend
    detection can put in the family's chain (an upper bound): the configured ones that are not switched off
    (enabled false) and the native CLIs a reclassification can seat there. Strict GLM drops the worker-run GLM
    backends either way, as the worker does."""
    label = job.get("family") or ""
    base = fam.split_label(label)[0]
    if isinstance(job.get("chain"), list):
        chain = [b for b in job["chain"] if isinstance(b, str)]
    elif base == "host" or base in fam.fake_host_families():
        return ["host"]
    elif fam.fake_families():
        return [] if base in fam.fake_disabled() else ["stub"]
    else:
        chain = [b for b in ((cfg.get("families") or {}).get(base) or {}).get("backends") or []
                 if fam.backend_cfg(cfg, b).get("enabled") is not False]
        chain += [b for b in _reseatable(cfg, base) if b not in chain]
    return fam.drop_scripted_glm(cfg, label, chain)


def request_reserve(job, cfg=None):
    """Worst-case backend requests one worker launch of job can send (C6): every chain entry x (retries + 1) x its
    requests per attempt (3 for an HTTP backend: its internal retries; else 1), plus one repair call at the largest
    requests per attempt (a job makes at most one repair call). 0 for host jobs."""
    cfg = cfg or fam.load_families()
    tries = [_tries(cfg, b) for b in _chain_ids(job, cfg) if b != "host"]
    if not tries:
        return 0
    return (_job_retries(job, cfg) + 1) * sum(tries) + max(tries)


def _key_env(cfg, b, btype):
    if btype in ("openai-chat-http", "anthropic-http"):
        return b.get("key_env")
    if btype == "codex-cli":
        return b.get("token_env")
    if btype == "claude-cli" and b.get("provider"):
        return _provider_field(cfg, b["provider"], "token_env")
    return None


def _provider_field(cfg, prov, key):
    """providers.<prov>.<key>, or None when the entry is missing or of the wrong shape: the backend then refuses that
    provider with the config error (families.provider_entry) and the chain moves on."""
    try:
        return (fam.provider_entry(cfg, prov) or {}).get(key)
    except ValueError:
        return None


def _chain_now(cfg, label, chain):
    """C13: the driver-resolved chain, re-checked only for what can change after the launch: the CLI still resolves
    on PATH and the key or token variable is still set. Returns (usable backend ids, notes)."""
    usable, notes = [], []
    for bid in fam.drop_scripted_glm(cfg, label, chain):
        note = None
        if bid not in ("host", "stub"):
            b, t = fam.backend_cfg(cfg, bid), fam.backend_type(cfg, bid)
            key = _key_env(cfg, b, t)
            exe = b.get("exe") or t.split("-", 1)[0]
            if key and not (os.environ.get(key) or "").strip():
                note = "%s not set" % key
            elif t.endswith("-cli") and not proc.resolve_exe(exe):
                note = "%s not on PATH" % exe
        if note is None:
            usable.append(bid)
        elif note not in notes:
            notes.append(note)
    return usable, notes


def _retry_wait(prev, k):
    """Seconds to wait before retry k (0-based) on the same backend: full jitter or the server's Retry-After, none
    after empty output."""
    prev = prev or {}
    return 0.0 if prev.get("error_class") == "bad_output" else backoff_delay(k, prev.get("retry_after"))


# ---------------------------------------------------------------- main

def execute_job(job, detect_result=None, log=True, progress=None, job_file=None):
    """Run one job through its backend chain; write outputs; return the meta dict (4.7).

    Raises JobError for an unusable job (exit 2). Every other failure is reported in the meta status.
    """
    run_dir, prompt_path, out_path = check_job(job)
    cfg = fam.load_families()
    home = cfg.get("_ub_home") or fam.ub_home()
    label = job["family"].strip()
    base, alt = fam.split_label(label)
    prompt = textio.read_text(prompt_path)
    t0 = time.monotonic()
    tools = job.get("tools") or "none"
    kind = job.get("kind") or "generator"
    timeout_s = job.get("timeout_s") or fam.timeout_for(cfg, kind)
    retries = _job_retries(job, cfg)
    deadline_s = JOB_DEADLINE_FACTOR * float(timeout_s)
    deadline = now() + deadline_s
    min_left = min_attempt_s(timeout_s)
    cwd_mode = job.get("cwd") or "empty"
    meta = {"schema": 1, "id": job["id"], "family": label, "vendor": fam.vendor_of(label, cfg), "backend": None,
            "model": None, "tier": job.get("tier") or "default",
            "provisional": bool(job.get("provisional")) or alt, "status": None, "attempts": 0, "requests": 0,
            "exit_code": None, "error_class": None, "started": textio.now_iso(), "duration_s": 0.0,
            "prompt_sha256": textio.sha256_file(prompt_path), "out_sha256": None,
            "usage": usage_block(), "tools": tools, "web_used": False, "cwd": cwd_mode,
            "repo_read": cwd_mode == "repo",  # C8: the output may quote the repository (privacy label)
            "repaired": False, "cmd": "", "stderr_tail": "", "reason": ""}
    meta_path, failed_path = out_path + ".meta.json", out_path + ".failed.md"
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    job_file = job_file or job.get("_path") or ""
    run = _read_run(run_dir)
    job_chain = job.get("chain") if isinstance(job.get("chain"), list) else None
    if detect_result is None and job_chain is None and base != "host" and not fam.fake_families() and \
            base not in fam.fake_host_families():
        from . import detect as _detect  # lazy: detect imports adapter for the live preflight
        detect_result = _detect.detect(cfg, live=False, only=[base])
    host_family = ((run or {}).get("host") or {}).get("family") or ((detect_result or {}).get("host") or {}).get(
        "family")
    secrets = []  # key values of every backend tried so far (see _attempt_secrets)
    split_warnings = []  # FILE-protocol warnings of the output written (4.6.3)

    def finish(status, reason="", error_class=None, errors=None, last_output=None):
        meta["status"] = status
        meta["reason"] = reason
        meta["error_class"] = None if status == "ok" else (error_class or "internal")
        meta["duration_s"] = round(time.monotonic() - t0, 2)
        if status == "ok" and os.path.isfile(out_path):
            meta["out_sha256"] = textio.sha256_file(out_path)
        if status == "ok" and split_warnings:
            meta["split_warnings"] = split_warnings[:MAX_SPLIT_WARNINGS]
        clean = redact.redact_obj(meta, secrets)
        textio.write_json_atomic(meta_path, clean)
        if status != "ok":
            _write_failed(failed_path, reason or status, clean, errors,
                          redact.redact(last_output, secrets) if last_output else last_output)
        return clean

    refusal = policy_check(job, cfg, run, host_family, prompt=prompt)
    if refusal:
        return finish("refused", refusal, "policy")
    if base == "host":
        return finish("unavailable", "host jobs run through a HOST_BATCH card, never in a worker", "not_found")
    if job_chain is not None:
        chain, notes = _chain_now(cfg, label, job_chain)
    else:
        chain = fam.resolve_chain(cfg, label, detect_result)
        notes = (((detect_result or {}).get("families") or {}).get(base) or {}).get("notes") or []
    runnable = [b for b in chain if b != "host"]
    if not runnable:
        if chain:
            return finish("unavailable", "the %s chain is the host (HOST_BATCH)" % base, "not_found")
        return finish("unavailable", "family %s is unavailable%s" % (base, (": " + "; ".join(notes)) if notes else ""),
                      "not_found")

    alt_model = ((cfg.get("families") or {}).get(base) or {}).get("alt_model") if alt else None
    schema_path = None
    if job.get("schema_file"):
        sp = os.path.abspath(os.path.join(run_dir, job["schema_file"]))
        schema_path = sp if os.path.isfile(sp) else None
    soft_fail_only = True  # every failure so far was unavailable/auth/not_found
    deadline_hit = False
    long_wait = {}  # backend id -> (the wait a retry there needed, the seconds left then)
    last = last_hard = None
    last_backend = last_hard_backend = None

    def time_left():
        return deadline - now()

    def attempt(bid, the_prompt):
        meta["attempts"] += 1
        if progress:
            try:
                progress(meta["attempts"], bid)
            except Exception:  # noqa: BLE001 - a marker refresh must never break the call
                pass
        bcfg = fam.backend_cfg(cfg, bid)
        for s in _attempt_secrets(cfg, bcfg):
            if s not in secrets:
                secrets.append(s)
        ctx = CallContext(job=job, job_id=job["id"], job_file=job_file, prompt=the_prompt, backend_id=bid, bcfg=bcfg,
                          btype=fam.backend_type(cfg, bid), cfg=cfg, family=base, alt=alt, alt_model=alt_model,
                          tier=meta["tier"], tools=tools, cwd_mode=meta["cwd"], repo_root=job.get("repo_root"),
                          timeout_s=max(1, int(min(timeout_s, time_left()))), run_dir=run_dir,
                          schema_path=schema_path, ub_home=home)
        t_a = time.monotonic()
        call_dir = None
        try:
            if ctx.btype != "stub" and not ctx.btype.endswith("-http"):
                sweep_stale_calls(home)  # folders left by killed workers can hold a provider token
                call_dir = new_call_dir(home, job["id"])
                ctx.call_dir = call_dir
            try:
                mod = module_for(ctx.btype)
                res = mod.run(ctx)
            except KeyError as e:
                res = result("unavailable", error_class="not_found", error=str(e))
            except Exception as e:  # noqa: BLE001 - OSError, RecursionError from a parser, ...: a failed attempt
                res = result("failed", error_class="internal", error="backend error: %s" % e.__class__.__name__,
                             requests=1)
        finally:
            remove_quietly(call_dir)
        for k in ("cmd", "stderr_tail", "error"):
            res[k] = redact.redact(res.get(k) or "", secrets)
        meta["requests"] += _requests_of(res)
        meta.update({"backend": bid, "exit_code": res.get("exit_code"), "cmd": res.get("cmd", ""),
                     "stderr_tail": res.get("stderr_tail", ""), "model": res.get("model"),
                     "web_used": bool(res.get("web_used"))})
        _log_attempt(run_dir, meta, res, bid, meta["attempts"], t_a, log, secrets, kind)
        return res

    for bid in runnable:
        refusal = backend_policy_check(cfg, bid, label)
        if refusal:
            meta["backend"] = bid
            return finish("refused", refusal, "policy")
        if time_left() < min_left:
            deadline_hit = True
            break
        last_backend = bid
        for n in range(retries + 1):
            if n:
                wait, left = _retry_wait(last, n - 1), time_left()
                if left - wait < min_left:  # the job deadline comes first; the next backend needs no wait
                    long_wait[bid] = (wait, left)
                    break
                pause(wait)
            clipped = time_left() < timeout_s  # this attempt's timeout is the time left before the deadline
            res = attempt(bid, prompt)
            last = res
            st = res.get("status")
            if st == "ok":
                text = res.get("text") or ""
                usage = _estimate(res.get("usage") or usage_block(), prompt, text)
                if len(text.encode("utf-8")) > validate.OUTPUT_CAP_BYTES:
                    meta["usage"] = usage
                    return finish("invalid", "output exceeds the 2 MB cap", "bad_output",
                                  ["output exceeds the 2 MB cap"],
                                  text.encode("utf-8")[:validate.OUTPUT_CAP_BYTES].decode("utf-8", "ignore"))
                if res.get("truncated"):  # stopped at max_tokens: a repair call cannot fit either
                    meta["usage"] = usage
                    return finish("invalid", "output truncated at the backend's max_tokens", "bad_output",
                                  ["output truncated at max_tokens"], text)
                if not text.strip():
                    res = dict(res, status="failed", error_class="bad_output", error="empty output")
                    last = last_hard = res
                    last_hard_backend = bid
                    soft_fail_only = False
                    if n < retries:
                        continue
                    break
                ok, errors, io_error = _validate_and_write(text, job, run_dir, out_path, split_warnings)
                if ok:
                    meta["usage"] = usage
                    return finish("ok")
                if io_error:  # the answer is valid; only writing it failed: no repair call (it would call again)
                    meta["usage"] = usage
                    return finish("failed", "valid output could not be written: %s" % io_error[:300], "internal",
                                  None, text)
                if time_left() < min_left:
                    meta["usage"] = usage
                    return finish("invalid", "output invalid (the job deadline left no time for the repair call): %s"
                                  % "; ".join(errors)[:300], "bad_output", errors, text)
                # one repair call on the same backend (4.5)
                rep = attempt(bid, validate.repair_prompt(errors, text))
                rtext = rep.get("text") or ""
                if rep.get("status") == "ok" and rtext.strip():  # (check_contract applies the 2 MB cap first)
                    ok2, errors2, io_error2 = _validate_and_write(rtext, job, run_dir, out_path, split_warnings)
                    if ok2:
                        meta["repaired"] = True
                        meta["usage"] = _estimate(rep.get("usage") or usage_block(), prompt, rtext)
                        return finish("ok")
                    if io_error2:
                        meta["usage"] = _estimate(rep.get("usage") or usage_block(), prompt, rtext)
                        return finish("failed", "valid output could not be written: %s" % io_error2[:300],
                                      "internal", None, rtext)
                    errors, text = errors2, rtext
                elif rep.get("status") == "invalid":  # the repair call's own stdout passed the cap
                    errors = [rep.get("error") or "invalid output"]
                meta["usage"] = usage
                return finish("invalid", "output invalid after repair: %s" % "; ".join(errors)[:300], "bad_output",
                              errors, text)
            if st == "timeout":
                if clipped and last_hard is not None:  # the deadline cut it short: report the earlier failure
                    deadline_hit = True
                    break
                return finish("timeout", res.get("error") or "timed out", "timeout")
            if st == "refused":  # a policy refusal (C7): no retry, no repair, no other backend
                return finish("refused", res.get("error") or "refused", "policy")
            if st == "invalid":  # stdout past the cap: final like the 2 MB text cap (no retry, repair or backend)
                reason = res.get("error") or "invalid output"
                return finish("invalid", reason, res.get("error_class") or "bad_output", [reason])
            ec = res.get("error_class")
            if st == "unavailable" or ec in ("auth", "not_found"):
                break  # no retry; next backend
            soft_fail_only = False
            last_hard = res
            last_hard_backend = bid
            if not res.get("retryable", True):
                break  # the same prompt would fail the same way here; next backend
        if deadline_hit:
            break
        # next backend in the chain
    if not soft_fail_only and last_hard is not None:
        last = last_hard  # report the real failure, not a later "unavailable" fallback backend
        last_backend = last_hard_backend or last_backend
        meta.update({"exit_code": last.get("exit_code"), "cmd": last.get("cmd", ""),
                     "stderr_tail": last.get("stderr_tail", ""), "model": last.get("model"),
                     "web_used": bool(last.get("web_used"))})
    reason = (last or {}).get("error") or "every backend in the chain failed"
    if deadline_hit:
        why = ("the job deadline of %ds passed" % deadline_s if time_left() <= 0 else
               "less than %ds were left before the job deadline of %ds" % (min_left, deadline_s))
        reason = "%s (%s; no further attempt)" % (reason, why)
    elif last_backend in long_wait:
        wait, left = long_wait[last_backend]
        reason = "%s (a retry had to wait %ds, but only %ds were left before the job deadline of %ds%s)" % (
            reason, round(wait), round(left), deadline_s,
            "" if wait >= left else ", and an attempt needs at least %ds" % min_left)
    ec = (last or {}).get("error_class") or "internal"
    meta["backend"] = last_backend
    if soft_fail_only:
        return finish("unavailable", reason, ec)
    return finish("failed", reason, ec)
