"""Codex CLI backend: `codex exec` (codex-cli, and the provider variants @glm, @kimi). KIT_SPEC 5.2.

argv: [codex, "exec", "--skip-git-repo-check", "--ephemeral", "-s", "read-only", "-C", CWD,
       "-o", <tmp>/last.txt, "--json", "-c", "notify=[]"]
  + ["-c", "mcp_servers.<name>.enabled=false"]   each MCP server the Codex home's config.toml names     [U-40]
  + ["-c", "features.<f>=false"] for f in OFF_FEATURES          backend key disable_features (default true)   [U-42]
  + ["-c", "features.<f>=false"] for f in NO_READ_FEATURES
                                        tools without read, backend key disable_shell (default true)     [U-42]
  + ["--output-schema", <tmp>/output-schema.json]
                                        native_schema true (OpenAI backend) and the job has schema_file: a copy
                                        without minimum/maximum/minProperties/maxProperties              [U-85]
  + ["-m", model]                       model configured (alt seat: families.<f>.alt_model)
  + ["-c", "web_search=live"]           web jobs on a web-capable backend   [L; U-5]
    ["-c", "web_search=disabled"]       every other job                     [U-41]
  final element "-" (prompt on stdin). Process cwd = CWD as well.
Never --full-auto, --yolo, --dangerously-*, wire_api="chat", [profiles.*].

`-c` overrides are deep-merged into the loaded config (Codex >= 0.80), so an empty `mcp_servers={}` table would change
nothing: each server is disabled by name, and only names read from that config.toml are passed (a name the config does
not define would make Codex refuse to load it; a name with a dot cannot be addressed at all).

Tool policy (C7) is an allowlist: the JSONL stream is read as it arrives (every event, however long the run) and each
item type must be one the job may produce: BASE_ITEMS always, command_execution with read, web_search with web, plus
the backend key allow_items. Anything else (a shell command without read, a file change, an MCP or sub-agent call, a
type this list does not know) makes the attempt "refused" (error_class policy): the output is discarded and there is
no retry, repair or fallback. The answer is the -o file (last.txt), else the last agent_message.
"""

import os
import re

from .. import proc
from .. import textio
from . import (JsonLines, child_env, classify_error, decode, model_for, num, remove_quietly, result, run_process,
               tail, tools_has, usage_block, work_dir)

MAX_ERRORS = 20  # error events kept for the message and the classifier
# [U-85] Keywords --output-schema does not get: whether the Responses endpoint accepts them in strict mode is not
# verified, and a rejected schema would fail every call. The local validator enforces them on the output either way.
SCHEMA_DROP = ("minimum", "maximum", "minProperties", "maxProperties")
_SCHEMA_MAPS = ("properties", "patternProperties", "$defs", "definitions")  # name -> subschema
_SCHEMA_SUBS = ("items", "prefixItems", "additionalItems", "additionalProperties", "propertyNames", "contains", "not",
                "if", "then", "else", "anyOf", "allOf", "oneOf")  # a subschema or a list of them
# [U-42] Default-on Codex features no worker call needs, off on every call: connectors (apps: the codex_apps MCP server
# of a ChatGPT login), plugins (their MCP servers and skills), sub-agents (multi_agent), lifecycle hooks, memories of
# earlier sessions, browser and computer use, image generation, and endless reconnects (0.158+ retries a dead
# endpoint until the job's timeout, so the attempt ends "timeout" and the chain never falls back). An unknown key only
# warns (older CLIs).
OFF_FEATURES = ("apps", "plugins", "multi_agent", "hooks", "memories", "browser_use", "computer_use",
                "image_generation", "unbounded_connection_retries")
# [U-42] ...and on jobs without read, every way to reach local files: the shell (with unified exec), the JS REPL and
# view_image.
NO_READ_FEATURES = ("shell_tool", "js_repl", "view_image")
BASE_ITEMS = ("agent_message", "assistant_message", "reasoning", "todo_list", "error")
TOOL_ITEMS = ("command_execution", "web_search", "file_change", "mcp_tool_call", "collab_tool_call")
UNREADABLE_ITEM = "an oversized event of unknown type"
# The head of an event line longer than proc.LINE_CAP_BYTES: its event type, and an item's type ({"id":..,"type":..}).
_EVENT_HEAD_RE = re.compile(rb'^\s*\{\s*"type"\s*:\s*"([^"\\]{1,64})"')
_ITEM_HEAD_RE = re.compile(rb'"item"\s*:\s*\{[^{}]{0,512}?"type"\s*:\s*"([^"\\]{1,64})"')


def web_on(ctx):
    return tools_has(ctx.tools, "web") and bool(ctx.bcfg.get("web"))


def allowed_items(tools, bcfg=None):
    """JSONL item types a job with these tools may produce: BASE_ITEMS, command_execution with read, web_search with
    web, and the backend key allow_items (a type Codex added later; never one of TOOL_ITEMS)."""
    allowed = set(BASE_ITEMS)
    extra = (bcfg or {}).get("allow_items")
    if isinstance(extra, list):
        allowed.update(t for t in extra if isinstance(t, str) and t not in TOOL_ITEMS)
    if tools_has(tools, "read"):
        allowed.add("command_execution")
    if tools_has(tools, "web"):
        allowed.add("web_search")
    return allowed


def cli_schema(schema):
    """A copy of a JSON schema without the SCHEMA_DROP keywords at any schema position (a property that is merely
    named "minimum" stays)."""
    if not isinstance(schema, dict):
        return schema
    out = {}
    for k, v in schema.items():
        if k in SCHEMA_DROP:
            continue
        if k in _SCHEMA_MAPS and isinstance(v, dict):
            v = dict((name, cli_schema(sub)) for name, sub in v.items())
        elif k in _SCHEMA_SUBS:
            v = [cli_schema(sub) for sub in v] if isinstance(v, list) else cli_schema(v)
        out[k] = v
    return out


def _schema_file(ctx):
    """<call_dir>/output-schema.json: the job's schema through cli_schema() (deleted with the call folder), or None
    when the backend does not take --output-schema or the schema cannot be read."""
    if not (ctx.bcfg.get("native_schema") and ctx.schema_path and ctx.call_dir):
        return None
    try:
        schema = textio.read_json(ctx.schema_path)
        path = os.path.join(ctx.call_dir, "output-schema.json")
        textio.write_json_atomic(path, cli_schema(schema))
    except (OSError, ValueError):
        return None  # the local validator still checks the output
    return path


def build_argv(ctx, paths):
    """paths: {"exe", "cwd", "last", "schema" (abs or None), "mcp" (MCP server names to disable, optional)}."""
    exe = paths.get("exe") or ctx.exe_name
    argv = [exe, "exec", "--skip-git-repo-check", "--ephemeral", "-s", "read-only", "-C", paths["cwd"],
            "-o", paths["last"], "--json", "-c", "notify=[]"]
    # [U-40] the user's MCP servers stay off: -c overrides are merged into config.toml, so each one by name
    for name in paths.get("mcp") or ():
        argv += ["-c", "mcp_servers.%s.enabled=false" % name]
    off = list(OFF_FEATURES) if ctx.bcfg.get("disable_features", True) else []  # [U-42]
    # [U-42] a job without read gets no shell, JS REPL or image viewer; parse() refuses any command it runs anyway
    if not tools_has(ctx.tools, "read") and ctx.bcfg.get("disable_shell", True):
        off += NO_READ_FEATURES
    for feature in off:
        argv += ["-c", "features.%s=false" % feature]
    # [U-7] native_schema is false for codex-cli@glm/@kimi: their Responses endpoints may reject --output-schema
    if ctx.bcfg.get("native_schema") and paths.get("schema"):
        argv += ["--output-schema", paths["schema"]]
    model = model_for(ctx)
    if model:
        argv += ["-m", model]
    if web_on(ctx):
        argv += ["-c", "web_search=live"]  # [L] no quotes: a non-TOML value is read as a string. [U-5]
    else:
        argv += ["-c", "web_search=disabled"]  # [U-41] overrides a user's "live" setting and the cached default
    argv.append("-")
    return argv


class _Scan(object):
    """What parse() needs from a codex --json stream, kept as the events arrive (no list of events): usage (the last
    turn.completed), error messages, the last agent_message and every item type seen."""

    def __init__(self):
        self.usage = usage_block()
        self.errors = []
        self.agent_text = None
        self.used = set()
        self.lines = JsonLines(self.event, self.oversized)

    def event(self, ev):
        et = ev.get("type")
        if et == "turn.completed" and isinstance(ev.get("usage"), dict):
            u = ev["usage"]
            self.usage = usage_block(num(u.get("input_tokens")), num(u.get("output_tokens")), None)
        elif et in ("error", "turn.failed"):
            err = ev.get("error")
            msg = ev.get("message")
            if not msg and isinstance(err, dict):
                msg = err.get("message")
            if not msg and isinstance(err, str):
                msg = err
            if msg and len(self.errors) < MAX_ERRORS:
                self.errors.append(str(msg)[:500])
        elif isinstance(et, str) and et.startswith("item."):
            item = ev.get("item") if isinstance(ev.get("item"), dict) else {}
            itype = item.get("type")
            self.used.add(itype if isinstance(itype, str) and itype else UNREADABLE_ITEM)
            if et == "item.completed" and itype in ("agent_message", "assistant_message") \
                    and isinstance(item.get("text"), str):
                self.agent_text = item["text"]

    def oversized(self, head):
        """An event line longer than proc.LINE_CAP_BYTES (e.g. a command's whole output): only its type counts."""
        head = head[:8192]
        if head[:3] == b"\xef\xbb\xbf":
            head = head[3:]
        m = _EVENT_HEAD_RE.match(head)
        if m is None and not head.lstrip().startswith(b"{"):
            return  # not a JSON event
        if m is None or m.group(1).startswith(b"item."):
            it = _ITEM_HEAD_RE.search(head) if m is not None else None
            self.used.add(it.group(1).decode("ascii", "replace") if it else UNREADABLE_ITEM)


def parse(pr, ctx, cmd, last_path, model=None, scan=None):
    """A ProcResult (and the _Scan that read its stream while the CLI ran, if any) -> a call result."""
    stderr = decode(pr.stderr_bytes)
    common = {"cmd": cmd, "stderr_tail": tail(stderr), "model": model, "exit_code": pr.returncode, "requests": 1}
    if pr.timed_out:
        return result("timeout", error_class="timeout", error="codex exec timed out after %ss" % ctx.timeout_s,
                      **common)
    if scan is None or not scan.lines.fed:
        scan = _Scan()
        scan.lines.feed_bytes(pr.stdout_bytes)  # not streamed (a mocked runner): one pass over the bytes
    scan.lines.finish()
    usage, errors, used, agent_text = scan.usage, scan.errors, set(scan.used), scan.agent_text
    if scan.lines.undecodable:
        used.add(UNREADABLE_ITEM)
    common["web_used"] = "web_search" in used
    violations = sorted(used - allowed_items(ctx.tools, ctx.bcfg))
    if violations:
        remove_quietly(last_path)  # the text never reaches <out> or another vendor's prompt
        new = [v for v in violations if v not in TOOL_ITEMS and v != UNREADABLE_ITEM]
        hint = (" (if %s is a harmless new Codex item type, add it to backends.%s.allow_items in UB_HOME/families.json)"
                % (", ".join(new), ctx.backend_id or "codex-cli")) if new else ""
        return result("refused", error_class="policy", error="codex used %s on a tools=%s job; the output was "
                      "discarded%s" % (", ".join(violations), ctx.tools or "none", hint), retryable=False,
                      usage=usage, **common)
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


def _mislabeled(ctx):
    """For the native backend: why the user's Codex setup answers for another family than this call's, else None."""
    from ..detect import codex_config_family  # lazy: detect imports this package
    served, _prov, base, _path = codex_config_family(ctx.base_env)
    if served == (ctx.family or "gpt"):
        return None
    return ("the native codex-cli is configured for %s (%s), not %s; re-run detection (family.py detect)"
            % (served, base or "config.toml", ctx.family or "gpt"))


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
    else:
        why = _mislabeled(ctx)
        if why:
            return result("unavailable", error_class="config", error=why, retryable=False)
    from ..detect import codex_mcp_servers
    exe_path = proc.resolve_exe(ctx.exe_name, env) or ctx.exe_name
    cwd = work_dir(ctx)
    last = os.path.join(ctx.call_dir, "last.txt")
    codex_home = env.get("CODEX_HOME") or os.path.join(os.path.expanduser("~"), ".codex")
    argv = build_argv(ctx, {"exe": exe_path, "cwd": cwd, "last": last, "schema": _schema_file(ctx),
                            "mcp": codex_mcp_servers(codex_home)})
    secrets = [env[ctx.bcfg["token_env"]]] if ctx.bcfg.get("token_env") and env.get(ctx.bcfg["token_env"]) else ()
    scan = _Scan()
    pr, fail, cmd = run_process(ctx, argv, env, cwd, ctx.prompt.encode("utf-8"), secrets=secrets, stream=scan.lines)
    if fail:
        return fail
    return parse(pr, ctx, cmd, last, model_for(ctx), scan)
