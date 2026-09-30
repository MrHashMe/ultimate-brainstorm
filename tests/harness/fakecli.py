#!/usr/bin/env python3
"""Fake agent CLIs for tests (KIT_SPEC 4.18). Owner: B4.

Usage: fakecli.py <tool> [args...]   tool = claude | codex | kimi | npx (also node, npm, git, uv, any name)

shims.py installs `<tool>` (POSIX sh wrapper) or `<tool>.cmd` (Windows) into a temporary bin folder; each shim runs
this file with the tool name first, so the real `.cmd` quoting path is exercised on Windows.

Scenario rules come from the JSON list at UB_FAKE_SCENARIO; the first matching rule wins:
    {"tool": "codex", "argv_regex": "\\bexec\\b", "action": "stub"}
Rule keys: tool ("*" = any), argv_regex (searched in the args joined by single spaces), job_regex (searched in
UB_JOB_ID), max_hits (the rule applies only to its first N matching calls), action, exit, stdout, stderr, sleep_s,
spawn_child, then, create_dirs, result, kimi_variant ("tools": tool-call noise + text-part list).

Actions: stub | fail | sleep | garbage | fence | utf16 | bom | empty | is_error | record | static.
Without a matching rule: `--version` prints a default version, model calls (claude -p, codex exec, kimi -p) act as
`stub`, and `claude plugin ...` / `codex plugin ...` simulate a plugin registry kept in <HOME>/.fakecli-registry.json.

Every call appends one JSON line to UB_FAKE_LOG before acting:
    {"tool", "argv", "cwd", "env_names", "stdin_sha256", "job_id", "rule", "pid", ...}
plus, when present: "env" (allowlisted non-secret values), "settings" (claude --settings file snapshot; secret
values hashed), "agent_file" (kimi --agent-file snapshot), "o_file" (codex -o path). Secrets never reach the log.
"""

import hashlib
import json
import os
import re
import subprocess
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))

DEFAULT_VERSIONS = {
    "claude": "2.1.280 (Claude Code)",
    "codex": "codex-cli 0.156.1",
    "kimi": "2.0.2",
    "node": "v24.1.0",
    "npx": "10.9.0",
    "npm": "10.9.0",
    "git": "git version 2.51.0",
    "uv": "uv 0.8.0",
}

ENV_ALLOW = ("CODEX_HOME", "CLAUDE_CONFIG_DIR", "KIMI_CODE_HOME", "KIMI_CODE_NO_AUTO_UPDATE",
             "KIMI_CODE_BACKGROUND_PRINT_BACKGROUND_MODE", "KIMI_LOOP_MAX_STEPS_PER_TURN", "KIMI_SHELL_PATH",
             "ANTHROPIC_BASE_URL", "ANTHROPIC_MODEL", "OPENAI_BASE_URL", "UB_HOST_FAMILY", "UB_HOST", "NO_COLOR",
             "UB_JOB_ID", "UB_JOB_FILE", "DISABLE_TELEMETRY", "CLAUDECODE")

_SECRET_NAME = re.compile(r"(API_?KEY|AUTH_?TOKEN|ACCESS_?TOKEN|_TOKEN$|^TOKEN$|SECRET|PASSWORD|CREDENTIAL)", re.I)


def kit_root():
    marker = os.path.join(HERE, "_kit_path.txt")
    if os.path.isfile(marker):
        with open(marker, "r", encoding="utf-8") as f:
            path = f.read().strip()
        if path:
            return path
    return os.path.dirname(os.path.dirname(HERE))


def _sha(data):
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data or b"").hexdigest()


def _read_stdin(timeout=10.0):
    """Read all of stdin in a thread, so an inherited never-closed pipe cannot hang the fake."""
    box = {"data": b""}
    stream = getattr(sys.stdin, "buffer", None)
    if stream is None:
        return b""
    try:
        if sys.stdin.isatty():
            return b""
    except (ValueError, OSError):
        return b""

    def reader():
        try:
            box["data"] = stream.read() or b""
        except (OSError, ValueError):
            box["data"] = b""

    t = threading.Thread(target=reader)
    t.daemon = True
    t.start()
    t.join(timeout)
    return box["data"]


def _home():
    return os.environ.get("USERPROFILE") if os.name == "nt" and os.environ.get("USERPROFILE") else \
        os.environ.get("HOME") or os.path.expanduser("~")


def _expand(path):
    path = str(path)
    if path.startswith("~"):
        path = _home() + path[1:]
    return os.path.normpath(path)


def _append(path, line):
    if not path:
        return
    d = os.path.dirname(os.path.abspath(path))
    if d and not os.path.isdir(d):
        os.makedirs(d, exist_ok=True)
    with open(path, "a", encoding="utf-8", newline="\n") as f:
        f.write(line + "\n")


def _load_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _save_json(path, obj):
    tmp = "%s.%d.tmp" % (path, os.getpid())
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(obj, f, indent=1)
    for _ in range(20):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            time.sleep(0.05)
    os.replace(tmp, path)


# ---------------------------------------------------------------- rules

def _load_rules():
    path = os.environ.get("UB_FAKE_SCENARIO", "")
    if not path or not os.path.isfile(path):
        return []
    data = _load_json(path, [])
    return data if isinstance(data, list) else []


def _hits_path():
    log = os.environ.get("UB_FAKE_LOG", "")
    if log:
        return log + ".hits.json"
    return os.path.join(_home(), ".fakecli-hits.json")


def match_rule(tool, args, job_id):
    joined = " ".join(args)
    for idx, rule in enumerate(_load_rules()):
        if not isinstance(rule, dict):
            continue
        rt = rule.get("tool", "*")
        if rt not in ("*", tool):
            continue
        rx = rule.get("argv_regex")
        if rx and not re.search(rx, joined):
            continue
        jrx = rule.get("job_regex")
        if jrx and not re.search(jrx, job_id or ""):
            continue
        max_hits = rule.get("max_hits")
        if isinstance(max_hits, int):
            hp = _hits_path()
            hits = _load_json(hp, {})
            n = int(hits.get(str(idx), 0))
            if n >= max_hits:
                continue
            hits[str(idx)] = n + 1
            _save_json(hp, hits)
        return idx, rule
    return None, None


# ---------------------------------------------------------------- snapshots for the log

def _arg_after(args, flag):
    for i, a in enumerate(args):
        if a == flag and i + 1 < len(args):
            return args[i + 1]
        if a.startswith(flag + "="):
            return a[len(flag) + 1:]
    return None


def _settings_snapshot(path):
    snap = {"path": path, "exists": os.path.isfile(path)}
    if not snap["exists"]:
        return snap
    try:
        snap["mode"] = oct(os.stat(path).st_mode & 0o777)
    except OSError:
        pass
    data = _load_json(path, None)
    if isinstance(data, dict):
        env = data.get("env") if isinstance(data.get("env"), dict) else {}
        snap["keys"] = sorted(data.keys())
        snap["env"] = {k: ("sha256:" + _sha(str(v)) if _SECRET_NAME.search(k) else v) for k, v in env.items()}
    else:
        snap["parse_error"] = True
    return snap


def split_agent_file(text):
    """(frontmatter, body) of a markdown agent file with --- frontmatter."""
    text = text.replace("\r\n", "\n")
    if text.startswith("---\n"):
        end = text.find("\n---", 4)
        if end >= 0:
            nl = text.find("\n", end + 4)
            body = text[nl + 1:] if nl >= 0 else ""
            return text[4:end], body
    return "", text


def _agent_snapshot(path):
    snap = {"path": path, "exists": os.path.isfile(path)}
    if snap["exists"]:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            front, body = split_agent_file(f.read())
        snap["frontmatter"] = front
        snap["body_sha256"] = _sha(body)
        snap["body_has_dollar_brace"] = bool(re.search(r"\$\{[A-Za-z_]", body))
        snap["body_has_escaped"] = "$ {" in body
    return snap


def _agent_prompt(path):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return split_agent_file(f.read())[1]
    except OSError:
        return ""


# ---------------------------------------------------------------- plugin registry simulation

def _registry(tool):
    path = os.path.join(_home(), ".fakecli-registry.json")
    data = _load_json(path, {})
    scope = os.environ.get("CLAUDE_CONFIG_DIR", "") if tool == "claude" else os.environ.get("CODEX_HOME", "")
    key = "%s|%s" % (tool, os.path.normcase(scope))
    entry = data.setdefault(key, {"marketplaces": {}, "plugins": {}})
    return path, data, entry


def _marketplace_name(src):
    for rel in (os.path.join(".claude-plugin", "marketplace.json"), os.path.join(".agents", "plugins",
                                                                                   "marketplace.json")):
        p = os.path.join(src, rel)
        if os.path.isfile(p):
            name = _load_json(p, {}).get("name")
            if name:
                return str(name)
    base = src.replace("\\", "/").rstrip("/").split("@")[0].split("/")[-1]
    return base or "marketplace"


def plugin_sim(tool, args):
    """Simulate `claude plugin ...` and `codex plugin ...`. Returns (exit, stdout)."""
    path, data, reg = _registry(tool)
    rest = [a for a in args[1:] if a != "--json"]
    as_json = "--json" in args
    out, code = "", 0
    if rest[:1] == ["marketplace"]:
        sub = rest[1:2]
        if sub == ["add"] and len(rest) > 2:
            src = rest[2]
            name = _marketplace_name(src)
            reg["marketplaces"][name] = {"source": src}
            out = json.dumps({"name": name, "added": True}) if as_json else "Added marketplace %s" % name
        elif sub == ["list"]:
            items = [{"name": n, "source": m["source"], "path": m["source"]} for n, m in reg["marketplaces"].items()]
            out = json.dumps(items if tool == "claude" else {"marketplaces": items})
        elif sub in (["remove"], ["rm"]) and len(rest) > 2:
            code = 0 if reg["marketplaces"].pop(rest[2], None) is not None else 1
            out = json.dumps({"removed": code == 0}) if as_json else ""
        elif sub in (["update"], ["upgrade"]):
            out = json.dumps({"updated": True}) if as_json else "Updated"
        else:
            code = 2
    elif rest[:1] in (["install"], ["add"], ["i"]) and len(rest) > 1:
        pid = rest[1]
        scope = _arg_after(rest, "--scope") or "user"
        reg["plugins"][pid] = {"scope": scope}
        out = json.dumps({"installed": pid}) if as_json else "Installed %s" % pid
    elif rest[:1] in (["uninstall"], ["remove"], ["rm"]) and len(rest) > 1:
        code = 0 if reg["plugins"].pop(rest[1], None) is not None else 1
        out = json.dumps({"removed": code == 0}) if as_json else ""
    elif rest[:1] == ["list"]:
        items = []
        for pid, info in reg["plugins"].items():
            name, _sep, mk = pid.partition("@")
            items.append({"id": pid, "name": name, "marketplace": mk, "version": "2.0.0",
                          "scope": info.get("scope", "user"), "enabled": True, "installed": True})
        out = json.dumps(items if tool == "claude" else {"plugins": items})
    elif rest[:1] == ["validate"]:
        out = "Validation passed"
    else:
        code = 2
    _save_json(path, data)
    return code, out


# ---------------------------------------------------------------- stub emission

def _stub_text(tool, args, stdin_bytes):
    job_file = os.environ.get("UB_JOB_FILE", "")
    job = _load_json(job_file, {}) if job_file else {}
    if tool == "kimi":
        prompt = _agent_prompt(_arg_after(args, "--agent-file") or "")
    else:
        prompt = stdin_bytes.decode("utf-8", "replace")
    if not job:
        return "PONG. Stub output from the fake %s CLI without a job file." % tool, {}
    sys.path.insert(0, os.path.join(kit_root(), "tests", "harness"))
    import stubs  # noqa: E402 (path set at runtime; stubs puts the kit's scripts folder on sys.path)
    return stubs.respond(job, prompt), job


def _encode(text, rule):
    action = rule.get("action") if rule else None
    if action == "utf16":
        return text.encode("utf-16")
    if action == "bom":
        return b"\xef\xbb\xbf" + text.encode("utf-8")
    return text.encode("utf-8")


def _corrupt(text, job, action):
    if action == "garbage":
        return "I could not follow the format. ### random words without structure"
    if action == "empty":
        return ""
    if action == "fence":
        ctype = ((job or {}).get("contract") or {}).get("type")
        if ctype == "json":
            return "Here is the JSON you asked for:\n```json\n" + text.strip() + "\n```\n"
        return "Here is the result:\n\n" + text
    return text


def emit(tool, args, rule, stdin_bytes):
    action = (rule or {}).get("action", "stub")
    text, job = _stub_text(tool, args, stdin_bytes)
    text = _corrupt(text, job, action)
    exit_code = int((rule or {}).get("exit", 0))
    out = sys.stdout.buffer
    if tool == "claude":
        if action == "is_error":
            obj = {"type": "result", "subtype": "error_during_execution", "is_error": True,
                   "result": (rule or {}).get("result", "Invalid API key - Please run /login"),
                   "total_cost_usd": 0, "session_id": "fake"}
        else:
            obj = {"type": "result", "subtype": "success", "is_error": False, "result": text,
                   "total_cost_usd": 0, "session_id": "fake", "usage": {"input_tokens": 10, "output_tokens": 20}}
        out.write(_encode(json.dumps(obj), rule))
        out.flush()
        return exit_code
    if tool == "codex":
        if action == "is_error":
            sys.stderr.write((rule or {}).get("stderr", "error: 401 Unauthorized") + "\n")
            return exit_code or 1
        o_file = _arg_after(args, "-o") or _arg_after(args, "--output-last-message")
        if o_file:
            with open(o_file, "wb") as f:
                f.write(_encode(text, rule))
        if "--json" in args:
            events = [{"type": "thread.started", "thread_id": "fake"},
                      {"type": "item.completed", "item": {"type": "agent_message", "text": text}},
                      {"type": "turn.completed", "usage": {"input_tokens": 10, "output_tokens": 20}}]
            out.write(("\n".join(json.dumps(e) for e in events) + "\n").encode("utf-8"))
        elif not o_file:
            out.write(_encode(text, rule))
        out.flush()
        return exit_code
    if tool == "kimi":
        if action == "is_error":
            sys.stderr.write((rule or {}).get("stderr", "error: not logged in") + "\n")
            return exit_code or 1
        lines = []
        if (rule or {}).get("kimi_variant") == "tools":
            lines.append({"role": "assistant", "content": "",
                          "tool_calls": [{"id": "t1", "type": "function",
                                          "function": {"name": "ReadFile", "arguments": "{}"}}]})
            lines.append({"role": "tool", "tool_call_id": "t1", "content": "tool output noise"})
            lines.append({"role": "assistant", "content": [{"type": "text", "text": text}]})
        else:
            lines.append({"role": "assistant", "content": text})
        out.write(_encode("\n".join(json.dumps(x) for x in lines) + "\n", rule))
        out.flush()
        return exit_code
    out.write(_encode(text, rule))
    out.flush()
    return exit_code


# ---------------------------------------------------------------- main

def _default_action(tool, args):
    """The implied rule when no scenario rule matches."""
    if any(a in ("--version", "-V", "version") for a in args[:2]):
        return {"action": "static", "stdout": DEFAULT_VERSIONS.get(tool, "1.0.0") + "\n"}
    if tool == "claude" and "-p" in args:
        return {"action": "stub"}
    if tool == "codex" and args[:1] == ["exec"]:
        return {"action": "stub"}
    if tool == "kimi" and "-p" in args:
        return {"action": "stub"}
    if tool in ("claude", "codex") and args[:1] == ["plugin"]:
        return {"action": "plugin"}
    return {"action": "record"}


def main(argv):
    if len(argv) < 2:
        sys.stderr.write("usage: fakecli.py <tool> [args...]\n")
        return 2
    tool = os.path.splitext(os.path.basename(argv[1]))[0].lower()
    args = list(argv[2:])
    stdin_bytes = _read_stdin()
    job_id = os.environ.get("UB_JOB_ID", "")
    idx, rule = match_rule(tool, args, job_id)
    implied = rule if rule is not None else _default_action(tool, args)
    entry = {"tool": tool, "argv": args, "cwd": os.getcwd().replace("\\", "/"),
             "env_names": sorted(os.environ.keys()), "stdin_sha256": _sha(stdin_bytes), "job_id": job_id or None,
             "rule": idx, "action": implied.get("action", "stub"), "pid": os.getpid(), "ts": time.time()}
    entry["env"] = {k: os.environ[k] for k in ENV_ALLOW if k in os.environ}
    settings = _arg_after(args, "--settings")
    if tool == "claude" and settings:
        entry["settings"] = _settings_snapshot(settings)
    mcp = _arg_after(args, "--mcp-config")
    if tool == "claude" and mcp:
        entry["mcp_config"] = {"path": mcp, "exists": os.path.isfile(mcp)}
    agent = _arg_after(args, "--agent-file")
    if tool == "kimi" and agent:
        entry["agent_file"] = _agent_snapshot(agent)
    o_file = _arg_after(args, "-o")
    if tool == "codex" and o_file:
        entry["o_file"] = o_file.replace("\\", "/")
    _append(os.environ.get("UB_FAKE_LOG", ""), json.dumps(entry, ensure_ascii=True))

    action = implied.get("action", "stub")
    for d in implied.get("create_dirs") or []:
        os.makedirs(_expand(d), exist_ok=True)
    if action == "plugin":
        code, out = plugin_sim(tool, args)
        if out:
            sys.stdout.write(out + "\n")
        return code
    if action == "fail":
        sys.stderr.write(str(implied.get("stderr", "fake failure")) + "\n")
        if implied.get("stdout"):
            sys.stdout.write(str(implied["stdout"]))
        return int(implied.get("exit", 1))
    if action in ("record", "static"):
        if implied.get("stdout"):
            sys.stdout.write(str(implied["stdout"]))
        if implied.get("stderr"):
            sys.stderr.write(str(implied["stderr"]))
        sys.stdout.flush()
        return int(implied.get("exit", 0))
    if action == "sleep":
        if implied.get("spawn_child"):
            child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(%f)" %
                                      float(implied.get("sleep_s", 30))],
                                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            _append((os.environ.get("UB_FAKE_LOG", "") or os.path.join(_home(), "fake")) + ".children",
                    json.dumps({"parent": os.getpid(), "child": child.pid}))
        time.sleep(float(implied.get("sleep_s", 30)))
        then = implied.get("then", "stub")
        if then != "stub":
            return int(implied.get("exit", 0))
        return emit(tool, args, {"action": "stub", "exit": implied.get("exit", 0)}, stdin_bytes)
    # stub and the corruption actions
    return emit(tool, args, implied, stdin_bytes)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
