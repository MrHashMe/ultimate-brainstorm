"""Claude Code CLI backend: `claude -p` (claude-cli, and the provider variants @glm, @kimi, @kimi-code). KIT_SPEC 5.2.

argv: [claude, "-p", CLAUDE_P, "--output-format", "json", "--no-session-persistence",
       "--strict-mcp-config", "--mcp-config", UB_HOME/tmp/empty-mcp.json, "--disallowedTools", "mcp__*"]
  + ["Read(//<runs>/**)", "Grep(//<runs>/**)", "Glob(//<runs>/**)"]   more --disallowedTools values: cwd=repo jobs
                                      with read tools stay out of the run folders (backend key exclude_runs); only
                                      the run folders themselves when the runs folder holds the repository [U-44]
  + ["--setting-sources", "project"]  user settings, hooks, plugins and memory skipped (detect.claude_user_context)
                                      [U-43]
  + tools profile; + tier/alt model (native only); + ["--settings", <0600 temp file>]: provider backends (the tier
  or alt seat model is ANTHROPIC_MODEL in its env), and isolated native calls whose user settings.json carries the
  login or route (detect.claude_carried_settings) [U-43].
The prompt goes on stdin, never in argv. Never --bare, never inline --settings JSON.
"""

import json
import os
import re

from .. import detect
from .. import families
from .. import proc
from .. import redact
from .. import textio
from . import (child_env, classify_error, decode, num, remove_quietly, result, run_process, tail, tools_has,
               ub_tmp_dir, usage_block, work_dir, write_secret_file)

CLAUDE_P = "Follow the instructions in the piped input exactly. Output only the requested result."
EMPTY_MCP = {"mcpServers": {}}
RUN_FOLDER_TOOLS = ("Read", "Grep", "Glob")
RUN_RULES_MAX = 10  # other run folders denied one by one when the runs folder holds the repository (argv length)
RUN_NAME_RE = re.compile(r"^[A-Za-z0-9._-]{1,120}$")


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


def rule_path(path):
    """An absolute path in the form of a Claude Code permission rule: "//" + the POSIX path; a Windows drive path
    C:/x/y (any separators) becomes //c/x/y."""  # [U-44]
    p = os.path.abspath(path).replace("\\", "/")
    drive, rest = os.path.splitdrive(p)
    if len(drive) == 2 and drive[1] == ":":
        return "//%s%s" % (drive[0].lower(), rest)
    return p if p.startswith("//") else "/" + p


def _inside(path, root):
    p, r = os.path.normcase(os.path.abspath(path)), os.path.normcase(os.path.abspath(root))
    return p == r or p.startswith(r.rstrip("\\/") + os.sep)


def run_folder_rules(ctx):
    """--disallowedTools values that keep a job reading the repository out of the kit's run folders: Read, Grep and
    Glob of <folder of the runs>/** (every run, this one included; the .gitignore files only cover ripgrep). When that
    folder is the repository itself or holds it (`ub init --root` at or above the repository), only the run folders are
    denied: this run and at most RUN_RULES_MAX other folders there that hold a run.json (newest names first). Only for
    cwd=repo jobs with read tools; backend key exclude_runs (default true) turns them off."""  # [U-44]
    wanted = ctx.cwd_mode == "repo" and tools_has(ctx.tools, "read") and ctx.bcfg.get("exclude_runs", True)
    if not (wanted and ctx.run_dir):
        return []
    run_dir = os.path.abspath(ctx.run_dir)
    runs = os.path.dirname(run_dir)
    if not (ctx.repo_root and _inside(ctx.repo_root, runs)):
        folders = [runs]
    else:
        try:
            names = sorted((n for n in os.listdir(runs) if RUN_NAME_RE.match(n)
                            and os.path.isfile(os.path.join(runs, n, "run.json"))), reverse=True)
        except OSError:
            names = []
        others = [os.path.join(runs, n) for n in names if not _inside(ctx.repo_root, os.path.join(runs, n))
                  and os.path.normcase(os.path.join(runs, n)) != os.path.normcase(run_dir)]
        folders = [run_dir] + others[:RUN_RULES_MAX]
    return ["%s(%s/**)" % (tool, rule_path(d)) for d in folders for tool in RUN_FOLDER_TOOLS]


def provider_env(ctx):
    """The env block of a provider backend's settings file, without the token: the tier's model, or the alt seat's
    model (families.<f>.alt_model) as ANTHROPIC_MODEL. Raises KeyError for an unknown provider and ValueError for an
    entry of the wrong shape."""
    block = families.provider_settings_env(ctx.cfg, ctx.provider, ctx.tier, ctx.cfg.get("region"))
    if ctx.alt and ctx.alt_model:
        block["ANTHROPIC_MODEL"] = ctx.alt_model
    return block


def model_for(ctx):
    """The model this attempt uses (meta "model"); None means the CLI default."""
    if ctx.provider:
        try:
            return provider_env(ctx).get("ANTHROPIC_MODEL")
        except (KeyError, ValueError):
            return None
    if ctx.alt and ctx.alt_model:
        return ctx.alt_model
    if ctx.tier == "fast":
        return "haiku"
    return ctx.bcfg.get("model")


def build_argv(ctx, paths):
    """paths: {"exe": resolved exe or name, "mcp": empty-mcp.json, "settings": settings file or None,
    "schema_json": compact schema text or None, "isolate": bool (default: detect.claude_user_context)}."""
    exe = paths.get("exe") or ctx.exe_name
    argv = [exe, "-p", CLAUDE_P, "--output-format", "json", "--no-session-persistence",
            "--strict-mcp-config", "--mcp-config", paths["mcp"], "--disallowedTools", "mcp__*"] + run_folder_rules(ctx)
    isolate = paths.get("isolate")
    if isolate is None:
        isolate = detect.claude_user_context(ctx.bcfg, ctx.family, ctx.base_env) == "isolate"
    if isolate:
        argv += ["--setting-sources", "project"]  # [U-43] the --settings file still applies
    argv += tools_args(ctx, exe)
    if not ctx.provider:
        if ctx.alt and ctx.alt_model:
            argv += ["--model", ctx.alt_model]
        elif ctx.tier == "fast":
            argv += ["--model", "haiku"]
        elif ctx.bcfg.get("model"):
            argv += ["--model", ctx.bcfg["model"]]
    # provider backends: the tier (or alt seat) model is ANTHROPIC_MODEL inside the settings env; no --model flag.
    # An isolated native call gets a settings file only when it carries the user's login or route keys.
    if paths.get("settings"):
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


def parse(pr, ctx, cmd, model=None):
    """Turn a ProcResult into a call result (5.2 parse rules)."""
    stdout, stderr = decode(pr.stdout_bytes), decode(pr.stderr_bytes)
    common = {"cmd": cmd, "stderr_tail": tail(stderr), "model": model, "exit_code": pr.returncode, "requests": 1,
              "web_used": tools_has(ctx.tools, "web") and bool(ctx.bcfg.get("web"))}
    if pr.timed_out:
        return result("timeout", error_class="timeout", error="claude -p timed out after %ss" % ctx.timeout_s,
                      **common)
    obj = _find_result(stdout)
    if obj is None or obj.get("type") not in ("result", None):
        msg = "claude -p printed no result JSON object"
        if pr.returncode != 0:
            # classify error channels only: stderr, plus stdout when it is a raw CLI message rather than JSON events
            raw = "" if stdout.lstrip().startswith(("{", "[")) else stdout[-2000:]
            return result("failed", error_class=classify_error(stderr + "\n" + raw),
                          error="%s (exit %s)" % (msg, pr.returncode), **common)
        return result("failed", error_class="bad_output", error=msg, **common)
    u = obj.get("usage") if isinstance(obj.get("usage"), dict) else {}
    usage = usage_block(num(u.get("input_tokens")), num(u.get("output_tokens")), num(obj.get("total_cost_usd")))
    stu = u.get("server_tool_use")
    if isinstance(stu, dict) and num(stu.get("web_search_requests")) is not None:
        common["web_used"] = stu["web_search_requests"] > 0  # evidence beats capability when the CLI reports it
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
    # error_max_turns: the same prompt would use up its turns again (up to 40 web turns): try the next backend
    return result("failed", error_class=classify_error(detail + "\n" + stderr), error=(msg + ": " + detail.strip())
                  [:500], usage=usage, retryable=obj.get("subtype") != "error_max_turns", **common)


def run(ctx):
    """One attempt. The settings file (provider backends, and isolated native calls that carry the user's login or
    route keys) is 0600 and deleted in finally."""
    settings = None
    secrets = []
    try:
        if not ctx.provider:
            served = detect.endpoint_family(detect.claude_settings_endpoint(ctx.base_env)[0])
            if served != (ctx.family or "claude"):  # the user's settings.json now routes elsewhere
                return result("unavailable", error_class="config", retryable=False, error="the native claude-cli is "
                              "configured for %s, not %s; re-run detection (family.py detect)"
                              % (served, ctx.family or "claude"))
        mcp = ensure_empty_mcp(ctx.ub_home)
        env = child_env(ctx)
        exe_path = proc.resolve_exe(ctx.exe_name, env) or ctx.exe_name
        isolate = detect.claude_user_context(ctx.bcfg, ctx.family, ctx.base_env) == "isolate"
        data = detect.claude_carried_settings(ctx.base_env, bool(ctx.provider)) if isolate else {}  # [U-43]
        if ctx.provider:
            try:
                token_env, token_var, token = families.provider_token(ctx.cfg, ctx.provider, ctx.base_env)
            except ValueError as e:  # a hand-edited families.json entry of the wrong shape (detection refuses it too)
                return result("unavailable", error_class="config", retryable=False, error=str(e))
            if not token:
                return result("unavailable", error_class="auth", error="%s is not set" % (token_env or "token"))
            penv = provider_env(ctx)
            if not penv.get("ANTHROPIC_BASE_URL"):  # never start claude with a provider token and Anthropic's endpoint
                return result("unavailable", error_class="config", retryable=False,
                              error="provider %s has no base_url in families config" % ctx.provider)
            block = dict(data.get("env") or {})
            block.update(penv)
            block[token_var] = token
            data = {"env": block}
            secrets.append(token)
        secrets += [v for k, v in (data.get("env") or {}).items()
                    if isinstance(v, str) and redact.is_secret_name(k) and v not in secrets]
        if data:
            settings = os.path.join(ctx.call_dir, "settings-%s.json" % os.urandom(4).hex())
            try:
                write_secret_file(settings, json.dumps(data, indent=1) + "\n")
            except OSError as e:
                settings = None
                if ctx.provider:
                    return result("unavailable", error_class="internal", error="cannot secure the settings file: %s"
                                  % e.__class__.__name__)
                isolate = False  # the user's login cannot be carried over: the call loads the user's settings
        schema_json = None
        if ctx.schema_path and ctx.bcfg.get("native_schema"):
            try:
                schema_json = json.dumps(textio.read_json(ctx.schema_path), separators=(",", ":"))
            except (OSError, ValueError):
                schema_json = None
        argv = build_argv(ctx, {"exe": exe_path, "mcp": mcp, "settings": settings, "schema_json": schema_json,
                                "isolate": isolate})
        cwd = work_dir(ctx)
        pr, fail, cmd = run_process(ctx, argv, env, cwd, ctx.prompt.encode("utf-8"), secrets=secrets)
        res = fail or parse(pr, ctx, cmd, model_for(ctx))
        for k in ("cmd", "stderr_tail", "error"):  # values carried from settings.json are not in the environment
            res[k] = redact.redact(res.get(k) or "", secrets)
        return res
    finally:
        remove_quietly(settings)
