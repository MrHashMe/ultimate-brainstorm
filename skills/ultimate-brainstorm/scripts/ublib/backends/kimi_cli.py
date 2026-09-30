"""Kimi Code CLI v2 backend: `kimi -p` with the whole prompt in an --agent-file body. KIT_SPEC 0.3 item 2, 5.2.

files: <tmp>/ub-<job-id>-agent.md  (frontmatter name/description/tools/subagents; body = the prompt with every
       "${" rewritten as "$ {"), <tmp>/ub-empty-skills/ (empty dir)
argv:  [kimi, "--agent-file", <agent.md>, "--skills-dir", <empty-skills>, "--output-format", "stream-json",
        ("-m", model when configured), "-p", KIMI_P]
cwd:   an empty temp dir (there is no --work-dir flag [V]); no .git there, so no project skills or agents load
env:   + KIMI_CODE_NO_AUTO_UPDATE=1, KIMI_CODE_BACKGROUND_PRINT_BACKGROUND_MODE=exit,
         KIMI_LOOP_MAX_STEPS_PER_TURN=4 (tools none) | 40 (web/read)
No prompt text ever goes into argv ([U-1]: stdin is not used; the prompt is the agent-file body). Never --yolo, --auto, --plan.
A call whose model Kimi Code serves from another family's endpoint (detect.kimi_mislabel, [U-34]) never starts the CLI:
"unavailable", error_class config, not retried.
The stream-json stdout is read line by line as it arrives (nothing is buffered, however long the run).
Raw transcripts of the first SAMPLE_LIMIT calls of a run are kept in <run>/logs/kimi-samples/ (U-2), at most their first
SAMPLE_CAP_BYTES, never for jobs that read the repository, and never outside the run folder.
"""

import os
import re

from .. import proc
from .. import redact
from .. import textio
from . import (JsonLines, child_env, classify_error, decode, model_for, result, run_process, tail, tools_has,
               work_dir)

KIMI_P = "Carry out the task in your system instructions now. Output only the requested result."
AGENT_NAME = "ub-oneshot"
AGENT_DESCRIPTION = ("Isolated one-shot worker for ultimate-brainstorm. The final message is the complete "
                     "result.")
SAMPLE_LIMIT = 3
SAMPLE_CAP_BYTES = 1024 * 1024  # a sample keeps the stream's first 1 MB (cut at a line end), redacted
WEB_TOOLS = ("WebSearch", "FetchURL")
MAX_ERRORS = 20
_ROLE_HEAD_RE = re.compile(rb'"role"\s*:\s*"([A-Za-z_]{1,32})"')  # the head of a line past proc.LINE_CAP_BYTES


def escape_body(text):
    """Rewrite every "${" as "$ {" so the agent-file body has no template substitutions (0.3 item 2)."""
    return (text or "").replace("${", "$ {")


def tools_list(tools):
    names = []
    if tools_has(tools, "read"):
        names += ["Read", "Grep", "Glob"]
    if tools_has(tools, "web"):
        names += list(WEB_TOOLS)
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
    if not tc:
        return []
    return tc if isinstance(tc, list) else [tc]


def _call_name(call):
    fn = call.get("function") if isinstance(call, dict) else None
    name = fn.get("name") if isinstance(fn, dict) else (call.get("name") if isinstance(call, dict) else None)
    return name if isinstance(name, str) else None


def _error_text(obj):
    """The message of a stream-json error record, else None. Assistant, tool and user content never counts."""
    if not ("error" in obj or "error_code" in obj or _role(obj) == "error"):
        return None
    err = obj.get("error")
    if isinstance(err, dict):
        err = err.get("message") or err.get("code") or err.get("type")
    msg = obj.get("message") if isinstance(obj.get("message"), str) else None
    parts = [str(x) for x in (err, obj.get("error_code"), msg) if x is not None and x != "" and not isinstance(x, bool)]
    return " ".join(parts)[:500] or None


class _Scan(object):
    """The final assistant text, the error record texts and whether a web tool was called, kept as the stream-json
    objects arrive (never the list of events).

    Tolerant: role = obj.role or obj.type or obj.message.role; content = string | [{type:"text",text}] |
    obj.message.content; objects with non-empty tool_calls are skipped; the answer is the LAST assistant object
    after the last tool message. A line past proc.LINE_CAP_BYTES counts by its role only: a tool result resets the
    answer; an assistant message that long cannot be an answer (the cap is 2 MB), so it resets it and is remembered
    (`too_long`).
    """

    def __init__(self):
        self.answer, self.errors, self.web, self.too_long = None, [], False, False
        self.lines = JsonLines(self.event, self.oversized)

    def event(self, obj):
        role = _role(obj)
        if role == "tool":
            self.answer = None
        elif role == "assistant":
            calls = _tool_calls(obj)
            if calls:
                self.web = self.web or any(_call_name(c) in WEB_TOOLS for c in calls)
            else:
                text = _content(obj)
                if text is not None and text.strip():
                    self.answer, self.too_long = text, False
        err = _error_text(obj)
        if err and len(self.errors) < MAX_ERRORS:
            self.errors.append(err)

    def oversized(self, head):
        m = _ROLE_HEAD_RE.search(head[:8192])
        role = m.group(1) if m else None
        if role == b"tool":
            self.answer = None
        elif role == b"assistant":
            self.answer, self.too_long = None, True


def scan_stream(stdout):
    """One pass over a whole stream-json transcript (bytes or str): (final assistant text or None, error record texts,
    whether a web tool was called). See _Scan."""
    scan = _Scan()
    scan.lines.feed_bytes(stdout)
    return scan.answer, scan.errors, scan.web


def parse_stream(stdout):
    """The final assistant text of a stream-json transcript, or None (see scan_stream)."""
    return scan_stream(stdout)[0]


def _save_sample(ctx, raw):
    """Keep the raw stream-json of the first SAMPLE_LIMIT calls of a run in <run>/logs/kimi-samples/ (fixture
    capture, U-2), at most its first SAMPLE_CAP_BYTES (cut after the last whole line), redacted. Never for jobs that
    can read the repository. Each slot is claimed with O_EXCL, so concurrent workers never exceed the limit, and the
    bytes are decoded only once a slot is ours."""
    if not ctx.run_dir or ctx.cwd_mode == "repo" or tools_has(ctx.tools, "read"):
        return
    d = os.path.join(ctx.run_dir, "logs", "kimi-samples")
    try:
        os.makedirs(d, exist_ok=True)
    except OSError:
        return
    for i in range(1, SAMPLE_LIMIT + 1):
        try:
            fd = os.open(os.path.join(d, "sample-%d.jsonl" % i),
                         os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o600)
        except FileExistsError:
            continue
        except OSError:
            return
        if len(raw) >= SAMPLE_CAP_BYTES:  # (a streamed run hands over only its first proc.STREAM_HEAD_BYTES)
            raw = raw[:SAMPLE_CAP_BYTES]
            raw = raw[:raw.rfind(b"\n") + 1] or raw
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(redact.redact(decode(raw)).encode("utf-8"))
        except OSError:
            pass
        return


def parse(pr, ctx, cmd, model=None, scan=None):
    """A ProcResult (and the _Scan that read its stream while the CLI ran, if any) -> a call result."""
    stderr = decode(pr.stderr_bytes)
    common = {"cmd": cmd, "stderr_tail": tail(stderr), "model": model, "exit_code": pr.returncode, "requests": 1,
              "web_used": False}
    if pr.timed_out:
        return result("timeout", error_class="timeout", error="kimi -p timed out after %ss" % ctx.timeout_s, **common)
    if scan is None or not scan.lines.fed:
        scan = _Scan()
        scan.lines.feed_bytes(pr.stdout_bytes)  # not streamed (a mocked runner): one pass over the bytes
    scan.lines.finish()
    text, errors, common["web_used"] = scan.answer, scan.errors, scan.web
    if scan.lines.undecodable and pr.returncode == 0:
        return result("invalid", error_class="bad_output", error="kimi printed a UTF-16 stream larger than %d MB"
                      % (proc.LINE_CAP_BYTES // (1024 * 1024)), retryable=False, **common)
    if pr.returncode != 0:
        # error channels only: stderr and error records, never assistant text or tool results (fetched pages)
        detail = stderr + "\n" + "\n".join(errors)
        return result("failed", error_class=classify_error(detail), error="kimi -p exited %s" % pr.returncode,
                      **common)
    if text is None and scan.too_long:
        return result("invalid", error_class="bad_output", error="kimi's final message is longer than %d MB (the "
                      "answer cap is 2 MB)" % (proc.LINE_CAP_BYTES // (1024 * 1024)), retryable=False, **common)
    if text is None:
        return result("failed", error_class="bad_output", error="kimi stream-json had no final assistant message",
                      **common)
    return result("ok", text=text, **common)


def _mislabeled(ctx):
    """Why Kimi Code would answer this call's model from another family's endpoint (its config.toml, or
    KIMI_MODEL_BASE_URL with env_model), else None. Jobs carry the chain the driver detected (C13), so a config
    switched during a run is caught here."""
    from ..detect import kimi_mislabel  # lazy: detect imports this package
    why = kimi_mislabel(ctx.bcfg, ctx.base_env, (model_for(ctx),))
    return "%s; re-run detection (family.py detect)" % why if why else None


def run(ctx):
    why = _mislabeled(ctx)
    if why:
        return result("unavailable", error_class="config", error=why, retryable=False)
    env = child_env(ctx, extra_env(ctx))
    exe_path = proc.resolve_exe(ctx.exe_name, env) or ctx.exe_name
    safe_id = re.sub(r"[^A-Za-z0-9._-]", "_", ctx.job_id)[:60]
    agent = os.path.join(ctx.call_dir, "ub-%s-agent.md" % safe_id)
    skills = os.path.join(ctx.call_dir, "ub-empty-skills")
    os.makedirs(skills, exist_ok=True)
    textio.write_text_atomic(agent, agent_file_text(ctx.prompt, ctx.tools))
    cwd = work_dir(ctx)
    argv = build_argv(ctx, {"exe": exe_path, "agent": agent, "skills": skills})
    scan = _Scan()
    pr, fail, cmd = run_process(ctx, argv, env, cwd, None, stream=scan.lines)
    if fail:
        return fail
    if pr.stdout_bytes and not pr.timed_out:
        _save_sample(ctx, pr.stdout_bytes)  # streamed: the head of the stream (proc.STREAM_HEAD_BYTES)
    return parse(pr, ctx, cmd, model_for(ctx), scan)
