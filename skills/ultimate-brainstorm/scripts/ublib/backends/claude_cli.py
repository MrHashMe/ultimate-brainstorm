"""Claude Code CLI backend: `claude -p` (claude-cli, and the provider variants @glm, @kimi, @kimi-code). KIT_SPEC 5.2.

argv: [claude, "-p", CLAUDE_P, "--output-format", "json", "--no-session-persistence",
       "--strict-mcp-config", "--mcp-config", UB_HOME/tmp/empty-mcp.json, "--disallowedTools", "mcp__*"]
  + tools profile; + tier/alt model (native only); + ["--settings", <0600 temp file>] (provider backends).
The prompt goes on stdin, never in argv. Never --bare, never inline --settings JSON.
"""

import json
import os

from .. import families
from .. import proc
from .. import textio
from . import (child_env, classify_error, decode, remove_quietly, result, run_process, tail, tools_has,
               ub_tmp_dir, usage_block, write_secret_file)

CLAUDE_P = "Follow the instructions in the piped input exactly. Output only the requested result."
EMPTY_MCP = {"mcpServers": {}}


def ensure_empty_mcp(ub_home):
    """UB_HOME/tmp/empty-mcp.json ({"mcpServers":{}}), written once."""
    path = os.path.join(ub_tmp_dir(ub_home), "empty-mcp.json")
    if not os.path.isfile(path):
        textio.write_text_atomic(path, json.dumps(EMPTY_MCP) + "\n")
    return path


def _is_cmd(path):
    return str(path or "").lower().endswith((".cmd", ".bat"))


def tools_args(ctx, exe_path=None):
    tools = ctx.tools or "none"
    web, read = tools_has(tools, "web"), tools_has(tools, "read")
    if web and read:
        names = "Read,Grep,Glob,WebSearch,WebFetch"
        return ["--tools", names, "--allowedTools", names, "--max-turns", "40"]
    if web:
        return ["--tools", "WebSearch,WebFetch", "--allowedTools", "WebSearch,WebFetch", "--max-turns", "40"]
    if read:
        return ["--tools", "Read,Grep,Glob", "--allowedTools", "Read,Grep,Glob", "--max-turns", "30"]
    # [U-13] An empty argv element through an npm .cmd shim: switch to the "--tools=" spelling for .cmd/.bat
    # executables only when the backend config key "tools_equals_on_cmd" is true (default false).
    if _is_cmd(exe_path) and ctx.bcfg.get("tools_equals_on_cmd", False):
        return ["--tools=", "--max-turns", "3"]
    return ["--tools", "", "--max-turns", "3"]


def model_for(ctx):
    """The model this attempt uses (meta "model"); None means the CLI default."""
    if ctx.provider:
        try:
            return families.provider_settings_env(ctx.cfg, ctx.provider, ctx.tier).get("ANTHROPIC_MODEL")
        except KeyError:
            return None
    if ctx.alt and ctx.alt_model:
        return ctx.alt_model
    if ctx.tier == "fast":
        return "haiku"
    return ctx.bcfg.get("model")


def build_argv(ctx, paths):
    """paths: {"exe": resolved exe or name, "mcp": empty-mcp.json, "settings": settings file or None,
    "schema_json": compact schema text or None}."""
    exe = paths.get("exe") or ctx.exe_name
    argv = [exe, "-p", CLAUDE_P, "--output-format", "json", "--no-session-persistence",
            "--strict-mcp-config", "--mcp-config", paths["mcp"], "--disallowedTools", "mcp__*"]
    argv += tools_args(ctx, exe)
    if not ctx.provider:
        if ctx.alt and ctx.alt_model:
            argv += ["--model", ctx.alt_model]
        elif ctx.tier == "fast":
            argv += ["--model", "haiku"]
        elif ctx.bcfg.get("model"):
            argv += ["--model", ctx.bcfg["model"]]
    else:
        # tier is expressed by ANTHROPIC_MODEL inside the settings env; no --model flag
        argv += ["--settings", paths["settings"]]
    # [U-12] --json-schema only when native_schema is true AND the exe is not a .cmd/.bat shim (default: off).
    if paths.get("schema_json") and ctx.bcfg.get("native_schema") and not _is_cmd(exe):
        argv += ["--json-schema", paths["schema_json"]]
    return argv


def _find_result(stdout):
    s = (stdout or "").strip()
    if not s:
        return None
    try:
        obj = json.loads(s)
        if isinstance(obj, dict):
            return obj
        if isinstance(obj, list):  # some versions print an event array; take the last result object
            for item in reversed(obj):
                if isinstance(item, dict) and item.get("type") == "result":
                    return item
    except (ValueError, RecursionError):
        pass
    for line in reversed(s.split("\n")):
        line = line.strip()
        if line.startswith("{"):
            try:
                obj = json.loads(line)
            except (ValueError, RecursionError):
                continue
            if isinstance(obj, dict) and obj.get("type") == "result":
                return obj
    try:
        obj = textio.extract_json(s)
    except (ValueError, RecursionError):
        return None
    return obj if isinstance(obj, dict) else None


def _num(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def parse(pr, ctx, cmd, model=None):
    """Turn a ProcResult into a call result (5.2 parse rules)."""
    stdout, stderr = decode(pr.stdout_bytes), decode(pr.stderr_bytes)
    web_used = tools_has(ctx.tools, "web") and bool(ctx.bcfg.get("web"))
    common = {"cmd": cmd, "stderr_tail": tail(stderr), "model": model, "exit_code": pr.returncode,
              "web_used": web_used}
    if pr.timed_out:
        return result("timeout", error_class="timeout", error="claude -p timed out after %ss" % ctx.timeout_s,
                      **common)
    obj = _find_result(stdout)
    if obj is None or obj.get("type") not in ("result", None):
        msg = "claude -p printed no result JSON object"
        if pr.returncode != 0:
            text = stderr + "\n" + stdout[-2000:]
            return result("failed", error_class=classify_error(text), error="%s (exit %s)" % (msg, pr.returncode),
                          **common)
        return result("failed", error_class="bad_output", error=msg, **common)
    u = obj.get("usage") if isinstance(obj.get("usage"), dict) else {}
    usage = usage_block(_num(u.get("input_tokens")), _num(u.get("output_tokens")), _num(obj.get("total_cost_usd")))
    if obj.get("is_error") is False and obj.get("subtype") == "success":
        text = obj.get("result")
        if not isinstance(text, str):
            return result("failed", error_class="bad_output", error="result field is not text", usage=usage,
                          **common)
        return result("ok", text=text, usage=usage, **common)
    detail = obj.get("result") if isinstance(obj.get("result"), str) else ""
    errs = obj.get("errors")
    if isinstance(errs, list):
        detail += " " + " ".join(str(e) for e in errs)
    msg = "claude -p reported an error (subtype %s)" % (obj.get("subtype") or "unknown")
    return result("failed", error_class=classify_error(detail + "\n" + stderr), error=(msg + ": " + detail.strip())
                  [:500], usage=usage, **common)


def run(ctx):
    """One attempt. The settings file (provider backends) is 0600 and deleted in finally."""
    settings = None
    token = None
    try:
        mcp = ensure_empty_mcp(ctx.ub_home)
        env = child_env(ctx)
        exe_path = proc.resolve_exe(ctx.exe_name, env) or ctx.exe_name
        if ctx.provider:
            token_env, token_var, token = families.provider_token(ctx.cfg, ctx.provider, ctx.base_env)
            if not token:
                return result("unavailable", error_class="auth", error="%s is not set" % (token_env or "token"))
            block = families.provider_settings_env(ctx.cfg, ctx.provider, ctx.tier, ctx.cfg.get("region"))
            block[token_var] = token
            settings = os.path.join(ctx.call_dir, "settings-%s.json" % os.urandom(4).hex())
            try:
                write_secret_file(settings, json.dumps({"env": block}, indent=1) + "\n")
            except OSError as e:
                settings = None
                return result("unavailable", error_class="internal", error="cannot secure the settings file: %s"
                              % e.__class__.__name__)
        schema_json = None
        if ctx.schema_path and ctx.bcfg.get("native_schema"):
            try:
                schema_json = json.dumps(textio.read_json(ctx.schema_path), separators=(",", ":"))
            except (OSError, ValueError):
                schema_json = None
        argv = build_argv(ctx, {"exe": exe_path, "mcp": mcp, "settings": settings, "schema_json": schema_json})
        if ctx.cwd_mode == "repo" and ctx.repo_root:
            cwd = ctx.repo_root
        else:
            cwd = os.path.join(ctx.call_dir, "ub-empty")
            os.makedirs(cwd, exist_ok=True)
        pr, fail, cmd = run_process(ctx, argv, env, cwd, ctx.prompt.encode("utf-8"), secrets=[token] if token else ())
        if fail:
            return fail
        return parse(pr, ctx, cmd, model_for(ctx))
    finally:
        remove_quietly(settings)
