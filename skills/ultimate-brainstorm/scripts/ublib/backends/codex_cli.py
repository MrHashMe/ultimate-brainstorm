"""Codex CLI backend: `codex exec` (codex-cli, and the provider variants @glm, @kimi). KIT_SPEC 5.2.

argv: [codex, "exec", "--skip-git-repo-check", "--ephemeral", "-s", "read-only", "-C", CWD,
       "-o", <tmp>/last.txt, "--json"]
  + ["--output-schema", <abs schema>]   native_schema true (OpenAI backend) and the job has schema_file
  + ["-m", model]                       model configured (alt seat: families.<f>.alt_model)
  + ["-c", "web_search=live"]           web jobs on a web-capable backend   [L; U-5]
  final element "-" (prompt on stdin). Process cwd = CWD as well.
Never --full-auto, --yolo, --dangerously-*, wire_api="chat", [profiles.*].
"""

import json
import os

from .. import proc
from .. import textio
from . import child_env, classify_error, decode, result, run_process, tail, tools_has, usage_block


def model_for(ctx):
    if ctx.alt and ctx.alt_model:
        return ctx.alt_model
    if ctx.tier == "fast" and ctx.bcfg.get("fast_model"):
        return ctx.bcfg["fast_model"]
    return ctx.bcfg.get("model")


def web_on(ctx):
    return tools_has(ctx.tools, "web") and bool(ctx.bcfg.get("web"))


def build_argv(ctx, paths):
    """paths: {"exe", "cwd", "last", "schema" (abs or None)}."""
    exe = paths.get("exe") or ctx.exe_name
    argv = [exe, "exec", "--skip-git-repo-check", "--ephemeral", "-s", "read-only", "-C", paths["cwd"],
            "-o", paths["last"], "--json"]
    # [U-7] native_schema is false for codex-cli@glm/@kimi: their Responses endpoints may reject --output-schema
    if ctx.bcfg.get("native_schema") and paths.get("schema"):
        argv += ["--output-schema", paths["schema"]]
    model = model_for(ctx)
    if model:
        argv += ["-m", model]
    if web_on(ctx):
        argv += ["-c", "web_search=live"]  # [L] no quotes: a non-TOML value is read as a string. [U-5]
    argv.append("-")
    return argv


def _events(stdout):
    out = []
    for line in (stdout or "").split("\n"):
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            obj = json.loads(line)
        except (ValueError, RecursionError):
            continue
        if isinstance(obj, dict):
            out.append(obj)
    return out


def _num(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def parse(pr, ctx, cmd, last_path, model=None):
    stdout, stderr = decode(pr.stdout_bytes), decode(pr.stderr_bytes)
    common = {"cmd": cmd, "stderr_tail": tail(stderr), "model": model, "exit_code": pr.returncode,
              "web_used": web_on(ctx)}
    if pr.timed_out:
        return result("timeout", error_class="timeout", error="codex exec timed out after %ss" % ctx.timeout_s,
                      **common)
    events = _events(stdout)
    usage = usage_block()
    errors = []
    agent_text = None
    for ev in events:
        et = ev.get("type")
        if et == "turn.completed" and isinstance(ev.get("usage"), dict):
            u = ev["usage"]
            usage = usage_block(_num(u.get("input_tokens")), _num(u.get("output_tokens")), None)
        elif et in ("error", "turn.failed"):
            err = ev.get("error")
            msg = ev.get("message")
            if not msg and isinstance(err, dict):
                msg = err.get("message")
            if not msg and isinstance(err, str):
                msg = err
            if msg:
                errors.append(str(msg))
        elif et == "item.completed" and isinstance(ev.get("item"), dict):
            item = ev["item"]
            if item.get("type") in ("agent_message", "assistant_message") and isinstance(item.get("text"), str):
                agent_text = item["text"]
    text = None
    if last_path and os.path.isfile(last_path):
        try:
            text = textio.read_text(last_path)
        except OSError:
            text = None
    if (text is None or not text.strip()) and agent_text:
        text = agent_text  # tolerant: the -o file is missing but the JSONL carries the final message
    if pr.returncode != 0:
        detail = "\n".join(errors) + "\n" + stderr
        return result("failed", error_class=classify_error(detail), error=("codex exec exited %s: %s" % (
            pr.returncode, " | ".join(errors)[:300])).strip(), usage=usage, **common)
    if errors and not (text and text.strip()):
        return result("failed", error_class=classify_error("\n".join(errors) + "\n" + stderr),
                      error=" | ".join(errors)[:500], usage=usage, **common)
    if text is None or not text.strip():
        return result("failed", error_class="bad_output", error="codex exec produced no output", usage=usage,
                      **common)
    return result("ok", text=text, usage=usage, **common)


def run(ctx):
    env = child_env(ctx)
    if ctx.bcfg.get("codex_home"):
        home = env.get("CODEX_HOME")
        if not home or not os.path.isdir(home):
            return result("unavailable", error_class="not_found", error="codex home for %s is missing (run "
                          "install.py setup-%s --codex)" % (ctx.backend_id, ctx.provider or ctx.family))
        tok = ctx.bcfg.get("token_env")
        if tok and not env.get(tok):
            return result("unavailable", error_class="auth", error="%s is not set" % tok)
    exe_path = proc.resolve_exe(ctx.exe_name, env) or ctx.exe_name
    if ctx.cwd_mode == "repo" and ctx.repo_root:
        cwd = ctx.repo_root
    else:
        cwd = os.path.join(ctx.call_dir, "ub-empty")
        os.makedirs(cwd, exist_ok=True)
    last = os.path.join(ctx.call_dir, "last.txt")
    argv = build_argv(ctx, {"exe": exe_path, "cwd": cwd, "last": last, "schema": ctx.schema_path})
    secrets = [env[ctx.bcfg["token_env"]]] if ctx.bcfg.get("token_env") and env.get(ctx.bcfg["token_env"]) else ()
    pr, fail, cmd = run_process(ctx, argv, env, cwd, ctx.prompt.encode("utf-8"), secrets=secrets)
    if fail:
        return fail
    return parse(pr, ctx, cmd, last, model_for(ctx))
