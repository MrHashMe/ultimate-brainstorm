"""execute_job(): backend chain, retries, validation, repair, policy guards, outputs (KIT_SPEC 4.4-4.7, 5.4, 5.6).

Frozen API (4.8):
    execute_job(job: dict) -> dict        runs the chain in-process; returns the meta dict; writes outputs

Extra keyword arguments (optional, not frozen): detect_result (skip detection), log (append logs/calls.jsonl,
default True), progress (callback(attempt_no, backend_id) for the running marker), job_file (abs path of the job
JSON, exported to children as UB_JOB_FILE).

Outputs, all atomic: <out> only when valid; <out>.meta.json always; <out>.failed.md on final failure (first line
"FAMILY CALL FAILED: <reason>"); one line per attempt in <run>/logs/calls.jsonl (meta keys + ts), redacted.
"""

import json
import os
import re
import time

from . import families as fam
from . import filesproto
from . import redact
from . import textio
from . import validate
from .backends import (CallContext, host_of, module_for, new_call_dir, remove_quietly, result, sweep_stale_calls,
                       usage_block)

__all__ = ["execute_job", "load_job", "check_job", "exit_code_for", "policy_check", "backend_policy_check",
           "crash_meta", "JobError", "EXIT_CODES", "JOB_ID_RE"]

JOB_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,80}$")
EXIT_CODES = {"ok": 0, "unavailable": 3, "failed": 4, "invalid": 5, "timeout": 6, "refused": 7}
TOOLS = ("none", "web", "read", "read+web")
_GLM_HOSTS = ("api.z.ai", "open.bigmodel.cn")
FAILED_OUTPUT_CHARS = 4000


class JobError(ValueError):
    """The job JSON is unusable (worker exit 2)."""


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


def _inside(root, target):
    root = os.path.normcase(os.path.abspath(root))
    target = os.path.normcase(os.path.abspath(target))
    return target == root or target.startswith(root.rstrip("\\/") + os.sep)


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
    if not _inside(run_dir, out_path) or out_path == run_dir:
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


def policy_check(job, cfg, run, host_family=None):
    """Run-level guards 1-3. Returns a refusal reason or None."""
    label = job.get("family") or ""
    vendor = fam.vendor_of(label, cfg)
    tools = job.get("tools") or "none"
    jp = job.get("privacy") if isinstance(job.get("privacy"), dict) else {}
    rp = (run or {}).get("privacy") if isinstance((run or {}).get("privacy"), dict) else {}
    allowed = rp.get("allowed_vendors")
    if isinstance(allowed, list) and vendor not in allowed:
        return "vendor %s is not in run.json privacy.allowed_vendors" % vendor
    if jp.get("vendor_ok") is False:
        return "the job is stamped vendor_ok=false"
    if "web" in tools.split("+"):
        if rp.get("web") is False:
            return "web tools requested while privacy.web is false"
        if jp.get("web_ok") is False:
            return "web tools requested while the job is stamped web_ok=false"
    if (job.get("cwd") or "empty") == "repo":
        host_vendor = fam.vendor_of(host_family, cfg) if host_family else None
        if host_vendor is None or vendor != host_vendor:
            run_code = rp.get("code") if run is not None else None
            if run is not None and run_code is not True:
                return "cwd repo for vendor %s while privacy.code is false" % vendor
            if jp.get("code_ok") is False:
                return "cwd repo for vendor %s while the job is stamped code_ok=false" % vendor
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
    strict = not bool(((cfg.get("families") or {}).get("glm") or {}).get("allow_scripted_plan_use", True))
    if strict and t in ("claude-cli", "codex-cli") and (b.get("provider") == "glm" or base == "glm"):  # [U-20]
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


def _validate_and_write(text, job, run_dir, out_path):
    """Validate against the contract; on success write <out> (and split files).

    Returns (ok, errors, io_error). errors are faults of the output (they earn the one repair call, 4.5). io_error is
    set when the output is valid but writing it failed on this machine even after WRITE_ATTEMPTS local tries: a
    repair call would only repeat a model call whose answer was fine (and record a second "ok" call for the job).
    """
    contract = job.get("contract") or {"type": "text"}
    ok, errors, parsed = validate.check_contract(text, contract, run_dir)
    if not ok:
        return False, errors, None
    io_error = None
    for n in range(WRITE_ATTEMPTS):
        if n:
            time.sleep(0.25 * n)
        errors, io_error = _write_outputs(text, parsed, job, contract, run_dir, out_path)
        if errors:
            return False, errors, None
        if not io_error:
            return True, [], None
    return False, [], io_error


def _write_outputs(text, parsed, job, contract, run_dir, out_path):
    """Write the split files (FILE protocol) and <out>. Returns (output errors, io error text or None)."""
    split = job.get("split") if isinstance(job.get("split"), dict) else None
    if contract.get("type") == "files" and split and split.get("root"):
        root = os.path.join(run_dir, split["root"])
        if not _inside(run_dir, root):
            return ["split.root must stay inside the run folder"], None
        allowed = split.get("allowed") or contract.get("allowed") or None
        status_out = os.path.join(run_dir, split["status_out"]) if split.get("status_out") else None
        if status_out and not _inside(run_dir, status_out):
            return ["split.status_out must stay inside the run folder"], None
        res = filesproto.split_output(text, root, allowed, status_out=status_out,
                                      required=contract.get("required"),
                                      status_required=bool(contract.get("status_trailer")))
        if res.get("io_error"):
            return [], "; ".join(res["errors"]) or "could not write the files"
        if not res["ok"]:
            return res["errors"], None
    if contract.get("type") == "json" and parsed is not None:
        body = json.dumps(parsed, indent=1, ensure_ascii=False) + "\n"
    else:
        body = text
    try:
        textio.write_text_atomic(out_path, body)
    except OSError as e:
        return [], "could not write %s: %s" % (textio.to_posix(out_path), e.__class__.__name__)
    return [], None


def _attempt_secrets(cfg, bcfg, environ=None):
    """Values of the key variables this backend names (key_env, token_env, the provider's token_env), so redaction
    also scrubs keys whose variable names do not look secret (e.g. MY_ROUTER)."""
    env = os.environ if environ is None else environ
    names = [bcfg.get("key_env"), bcfg.get("token_env")]
    prov = bcfg.get("provider")
    if prov:
        names.append((((cfg or {}).get("providers") or {}).get(prov) or {}).get("token_env"))
    out = []
    for n in names:
        v = env.get(n) if isinstance(n, str) and n else None
        if isinstance(v, str) and v.strip():
            out.append(v.strip())
    return out


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
                  "reason": attempt_res.get("error", ""), "ts": textio.now_iso()})
    entry["out_sha256"] = None
    try:
        textio.append_line(os.path.join(run_dir, "logs", "calls.jsonl"),
                           json.dumps(redact.redact_obj(entry, secrets), ensure_ascii=True, sort_keys=False))
    except OSError:
        pass


def crash_meta(job, reason):
    """Write a 'failed' meta (and .failed.md) for a job whose worker hit an unexpected error; returns the meta."""
    _run_dir, _prompt, out_path = check_job(job)
    meta = {"schema": 1, "id": job.get("id"), "family": job.get("family"), "vendor": None, "backend": None,
            "model": None, "tier": job.get("tier") or "default", "provisional": bool(job.get("provisional")),
            "status": "failed", "attempts": 0, "exit_code": None, "error_class": "internal",
            "started": textio.now_iso(), "duration_s": 0.0, "prompt_sha256": None, "out_sha256": None,
            "usage": usage_block(), "tools": job.get("tools") or "none", "web_used": False,
            "cwd": job.get("cwd") or "empty", "repaired": False, "cmd": "", "stderr_tail": "", "reason": reason}
    clean = redact.redact_obj(meta)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    textio.write_json_atomic(out_path + ".meta.json", clean)
    _write_failed(out_path + ".failed.md", reason, clean)
    return clean


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
    retries = job.get("retries")
    if not isinstance(retries, int) or retries < 0:
        retries = int(((cfg.get("defaults") or {}).get("retries")) or 1)
    meta = {"schema": 1, "id": job["id"], "family": label, "vendor": fam.vendor_of(label, cfg), "backend": None,
            "model": None, "tier": job.get("tier") or "default",
            "provisional": bool(job.get("provisional")) or alt, "status": None, "attempts": 0, "exit_code": None,
            "error_class": None, "started": textio.now_iso(), "duration_s": 0.0,
            "prompt_sha256": textio.sha256_file(prompt_path), "out_sha256": None,
            "usage": usage_block(), "tools": tools, "web_used": False, "cwd": job.get("cwd") or "empty",
            "repaired": False, "cmd": "", "stderr_tail": "", "reason": ""}
    meta_path, failed_path = out_path + ".meta.json", out_path + ".failed.md"
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    job_file = job_file or job.get("_path") or ""
    run = _read_run(run_dir)
    if detect_result is None and base != "host" and not fam.fake_families() and base not in fam.fake_host_families():
        from . import detect as _detect  # lazy: detect imports adapter for the live preflight
        detect_result = _detect.detect(cfg, live=False, only=[base])
    host_family = ((run or {}).get("host") or {}).get("family") or ((detect_result or {}).get("host") or {}).get(
        "family")
    secrets = []  # key values of every backend tried so far (see _attempt_secrets)

    def finish(status, reason="", error_class=None, errors=None, last_output=None):
        meta["status"] = status
        meta["reason"] = reason
        meta["error_class"] = None if status == "ok" else (error_class or "internal")
        meta["duration_s"] = round(time.monotonic() - t0, 2)
        if status == "ok" and os.path.isfile(out_path):
            meta["out_sha256"] = textio.sha256_file(out_path)
        clean = redact.redact_obj(meta, secrets)
        textio.write_json_atomic(meta_path, clean)
        if status != "ok":
            _write_failed(failed_path, reason or status, clean, errors,
                          redact.redact(last_output, secrets) if last_output else last_output)
        return clean

    refusal = policy_check(job, cfg, run, host_family)
    if refusal:
        return finish("refused", refusal, "policy")
    if base == "host":
        return finish("unavailable", "host jobs run through a HOST_BATCH card, never in a worker", "not_found")
    chain = fam.resolve_chain(cfg, label, detect_result)
    runnable = [b for b in chain if b != "host"]
    if not runnable:
        if chain:
            return finish("unavailable", "the %s chain is the host (HOST_BATCH)" % base, "not_found")
        notes = (((detect_result or {}).get("families") or {}).get(base) or {}).get("notes") or []
        return finish("unavailable", "family %s is unavailable%s" % (base, (": " + "; ".join(notes)) if notes else ""),
                      "not_found")

    alt_model = ((cfg.get("families") or {}).get(base) or {}).get("alt_model") if alt else None
    schema_path = None
    if job.get("schema_file"):
        sp = os.path.abspath(os.path.join(run_dir, job["schema_file"]))
        schema_path = sp if os.path.isfile(sp) else None
    soft_fail_only = True  # every failure so far was unavailable/auth/not_found
    last = last_hard = None
    last_backend = last_hard_backend = None

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
                          timeout_s=timeout_s, run_dir=run_dir, schema_path=schema_path, ub_home=home)
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
                res = result("failed", error_class="internal", error="backend error: %s" % e.__class__.__name__)
        finally:
            remove_quietly(call_dir)
        for k in ("cmd", "stderr_tail", "error"):
            res[k] = redact.redact(res.get(k) or "", secrets)
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
        last_backend = bid
        for n in range(retries + 1):
            res = attempt(bid, prompt)
            last = res
            st = res.get("status")
            if st == "ok":
                text = res.get("text") or ""
                usage = _estimate(res.get("usage") or usage_block(), prompt, text)
                if len(text.encode("utf-8")) > validate.OUTPUT_CAP_BYTES:
                    meta["usage"] = usage
                    return finish("invalid", "output exceeds the 2 MB cap", "bad_output",
                                  ["output exceeds the 2 MB cap"], text[:validate.OUTPUT_CAP_BYTES])
                if not text.strip():
                    res = dict(res, status="failed", error_class="bad_output", error="empty output")
                    last = last_hard = res
                    last_hard_backend = bid
                    soft_fail_only = False
                    if n < retries:
                        continue
                    break
                ok, errors, io_error = _validate_and_write(text, job, run_dir, out_path)
                if ok:
                    meta["usage"] = usage
                    return finish("ok")
                if io_error:  # the answer is valid; only writing it failed: no repair call (it would call again)
                    meta["usage"] = usage
                    return finish("failed", "valid output could not be written: %s" % io_error[:300], "internal",
                                  None, text)
                # one repair call on the same backend (4.5)
                rep = attempt(bid, validate.repair_prompt(errors, text))
                if rep.get("status") == "ok" and (rep.get("text") or "").strip():
                    rtext = rep["text"]
                    if len(rtext.encode("utf-8")) <= validate.OUTPUT_CAP_BYTES:
                        ok2, errors2, io_error2 = _validate_and_write(rtext, job, run_dir, out_path)
                        if ok2:
                            meta["repaired"] = True
                            meta["usage"] = _estimate(rep.get("usage") or usage_block(), prompt, rtext)
                            return finish("ok")
                        if io_error2:
                            meta["usage"] = _estimate(rep.get("usage") or usage_block(), prompt, rtext)
                            return finish("failed", "valid output could not be written: %s" % io_error2[:300],
                                          "internal", None, rtext)
                        errors, text = errors2, rtext
                meta["usage"] = usage
                return finish("invalid", "output invalid after repair: %s" % "; ".join(errors)[:300], "bad_output",
                              errors, text)
            if st == "timeout":
                return finish("timeout", res.get("error") or "timed out", "timeout")
            if st == "refused":
                return finish("refused", res.get("error") or "refused", "policy")
            ec = res.get("error_class")
            if st == "unavailable" or ec in ("auth", "not_found"):
                break  # no retry; next backend
            soft_fail_only = False
            last_hard = res
            last_hard_backend = bid
            if n < retries:
                continue
        # next backend in the chain
    if not soft_fail_only and last_hard is not None:
        last = last_hard  # report the real failure, not a later "unavailable" fallback backend
        last_backend = last_hard_backend or last_backend
        meta.update({"exit_code": last.get("exit_code"), "cmd": last.get("cmd", ""),
                     "stderr_tail": last.get("stderr_tail", ""), "model": last.get("model"),
                     "web_used": bool(last.get("web_used"))})
    reason = (last or {}).get("error") or "every backend in the chain failed"
    ec = (last or {}).get("error_class") or "internal"
    meta["backend"] = last_backend
    if soft_fail_only:
        return finish("unavailable", reason, ec)
    return finish("failed", reason, ec)
