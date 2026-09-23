"""Kimi Code CLI v2 backend: `kimi -p` with the whole prompt in an --agent-file body. KIT_SPEC 0.3 item 2, 5.2.

files: <tmp>/ub-<job-id>-agent.md  (frontmatter name/description/tools/subagents; body = the prompt with every
       "${" rewritten as "$ {"), <tmp>/ub-empty-skills/ (empty dir)
argv:  [kimi, "--agent-file", <agent.md>, "--skills-dir", <empty-skills>, "--output-format", "stream-json",
        ("-m", model when configured), "-p", KIMI_P]
cwd:   an empty temp dir (there is no --work-dir flag [V]); no .git there, so no project skills or agents load
env:   + KIMI_CODE_NO_AUTO_UPDATE=1, KIMI_CODE_BACKGROUND_PRINT_BACKGROUND_MODE=exit,
         KIMI_LOOP_MAX_STEPS_PER_TURN=4 (tools none) | 40 (web/read)
No prompt text ever goes into argv ([U-1]: stdin is not used; the prompt is the agent-file body). Never --yolo, --auto, --plan.
"""

import json
import os
import re

from .. import proc
from .. import redact
from .. import textio
from . import child_env, classify_error, decode, result, run_process, tail, tools_has, ub_tmp_dir

KIMI_P = "Carry out the task in your system instructions now. Output only the requested result."
AGENT_NAME = "ub-oneshot"
AGENT_DESCRIPTION = ("Isolated one-shot worker for ultimate-brainstorm. The final message is the complete "
                     "result.")
SAMPLE_LIMIT = 3


def escape_body(text):
    """Rewrite every "${" as "$ {" so the agent-file body has no template substitutions (0.3 item 2)."""
    return (text or "").replace("${", "$ {")


def tools_list(tools):
    names = []
    if tools_has(tools, "read"):
        names += ["Read", "Grep", "Glob"]
    if tools_has(tools, "web"):
        names += ["WebSearch", "FetchURL"]
    return names


def agent_file_text(prompt, tools):
    lines = ["---",
             "name: %s" % AGENT_NAME,
             "description: %s" % AGENT_DESCRIPTION,
             "tools: [%s]" % ", ".join(tools_list(tools)),
             "subagents: []",
             "---",
             escape_body(prompt)]
    text = "\n".join(lines)
    return text if text.endswith("\n") else text + "\n"


def model_for(ctx):
    if ctx.alt and ctx.alt_model:
        return ctx.alt_model
    if ctx.tier == "fast" and ctx.bcfg.get("fast_model"):
        return ctx.bcfg["fast_model"]
    return ctx.bcfg.get("model")


def extra_env(ctx):
    steps = "4" if (ctx.tools or "none") == "none" else "40"
    return {"KIMI_CODE_NO_AUTO_UPDATE": "1", "KIMI_CODE_BACKGROUND_PRINT_BACKGROUND_MODE": "exit",
            "KIMI_LOOP_MAX_STEPS_PER_TURN": steps}


def build_argv(ctx, paths):
    """paths: {"exe", "agent", "skills"}."""
    exe = paths.get("exe") or ctx.exe_name
    argv = [exe, "--agent-file", paths["agent"], "--skills-dir", paths["skills"], "--output-format", "stream-json"]
    model = model_for(ctx)
    if model:
        argv += ["-m", model]
    argv += ["-p", KIMI_P]
    return argv


# ---------------------------------------------------------------- stream-json parsing  # [U-2]

def _role(obj):
    r = obj.get("role") or obj.get("type")
    if not r and isinstance(obj.get("message"), dict):
        r = obj["message"].get("role")
    if r in ("message", "assistant_message") and isinstance(obj.get("message"), dict):
        r = obj["message"].get("role") or r
    return r


def _content(obj):
    c = obj.get("content")
    if c is None and isinstance(obj.get("message"), dict):
        c = obj["message"].get("content")
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        parts = []
        for p in c:
            if isinstance(p, str):
                parts.append(p)
            elif isinstance(p, dict) and p.get("type", "text") in ("text", "output_text") \
                    and isinstance(p.get("text"), str):
                parts.append(p["text"])
        return "".join(parts)
    return None


def _tool_calls(obj):
    tc = obj.get("tool_calls")
    if not tc and isinstance(obj.get("message"), dict):
        tc = obj["message"].get("tool_calls")
    return bool(tc)


def parse_stream(stdout):
    """The final assistant text of a stream-json transcript, or None.

    Tolerant: role = obj.role or obj.type or obj.message.role; content = string | [{type:"text",text}] |
    obj.message.content; objects with non-empty tool_calls are dropped; the result is the LAST assistant object
    after the last tool message.
    """
    objs = []
    for line in (stdout or "").split("\n"):
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            obj = json.loads(line)
        except (ValueError, RecursionError):
            continue
        if isinstance(obj, dict):
            objs.append(obj)
    last_tool = -1
    for i, obj in enumerate(objs):
        if _role(obj) == "tool":
            last_tool = i
    answer = None
    for i, obj in enumerate(objs):
        if i <= last_tool or _role(obj) != "assistant" or _tool_calls(obj):
            continue
        text = _content(obj)
        if text is not None and text.strip():
            answer = text
    return answer


def _save_sample(ctx, stdout):
    """Keep the raw JSONL of the first 3 live calls in UB_HOME/tmp/kimi-samples/ (fixture capture, U-2)."""
    try:
        d = os.path.join(ub_tmp_dir(ctx.ub_home), "kimi-samples")
        os.makedirs(d, exist_ok=True)
        if len([n for n in os.listdir(d) if n.endswith(".jsonl")]) >= SAMPLE_LIMIT:
            return
        name = "%s-%s.jsonl" % (textio.now_iso().replace(":", ""), re.sub(r"[^A-Za-z0-9._-]", "_", ctx.job_id))
        textio.write_text_atomic(os.path.join(d, name), redact.redact(stdout))
    except OSError:
        pass


def parse(pr, ctx, cmd, model=None):
    stdout, stderr = decode(pr.stdout_bytes), decode(pr.stderr_bytes)
    common = {"cmd": cmd, "stderr_tail": tail(stderr), "model": model, "exit_code": pr.returncode,
              "web_used": tools_has(ctx.tools, "web") and bool(ctx.bcfg.get("web"))}
    if pr.timed_out:
        return result("timeout", error_class="timeout", error="kimi -p timed out after %ss" % ctx.timeout_s, **common)
    if pr.returncode != 0:
        detail = stderr + "\n" + stdout[-2000:]
        return result("failed", error_class=classify_error(detail), error="kimi -p exited %s" % pr.returncode,
                      **common)
    text = parse_stream(stdout)
    if text is None:
        return result("failed", error_class="bad_output", error="kimi stream-json had no final assistant message",
                      **common)
    return result("ok", text=text, **common)


def run(ctx):
    env = child_env(ctx, extra_env(ctx))
    exe_path = proc.resolve_exe(ctx.exe_name, env) or ctx.exe_name
    safe_id = re.sub(r"[^A-Za-z0-9._-]", "_", ctx.job_id)[:60]
    agent = os.path.join(ctx.call_dir, "ub-%s-agent.md" % safe_id)
    skills = os.path.join(ctx.call_dir, "ub-empty-skills")
    os.makedirs(skills, exist_ok=True)
    textio.write_text_atomic(agent, agent_file_text(ctx.prompt, ctx.tools))
    if ctx.cwd_mode == "repo" and ctx.repo_root:
        cwd = ctx.repo_root
    else:
        cwd = os.path.join(ctx.call_dir, "ub-empty")
        os.makedirs(cwd, exist_ok=True)
    argv = build_argv(ctx, {"exe": exe_path, "agent": agent, "skills": skills})
    pr, fail, cmd = run_process(ctx, argv, env, cwd, None)
    if fail:
        return fail
    if pr.stdout_bytes and not pr.timed_out:
        _save_sample(ctx, decode(pr.stdout_bytes))
    return parse(pr, ctx, cmd, model_for(ctx))
