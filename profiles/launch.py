#!/usr/bin/env python3
"""ultimate-brainstorm launcher logic (KIT_SPEC 4.16). Python 3.9+, standard library only.

Run by the launchers that install.py writes into UB_HOME/bin (claude-glm, claude-kimi, codex-glm, codex-kimi, ub):

    launch.py claude --provider glm|kimi|kimi-code [--region global|cn] [--tier default|fast] [--zai-mcp] -- <args>
    launch.py codex  --provider glm|kimi -- <args>
    launch.py ub     -- <args>

- claude: writes a 0600 settings file UB_HOME/tmp/launch-<pid>-<rand>.json holding {"env": provider env + token},
  sets UB_HOST_FAMILY, runs `claude --settings <file> <args>`, waits, deletes the file in `finally` and returns
  claude's exit code. The token never appears in argv, logs or output. The file also goes when the launcher ends
  abnormally (SIGTERM/SIGHUP on POSIX; console close, logoff or shutdown on Windows; atexit), and every claude
  launch first deletes the files of launchers that died without any cleanup (a kill): sweep_stale_secret_files. A
  `<file>.id` next to each file records which process wrote it (proc.process_identity), so a live launcher's file is
  never taken for a dead one's, whatever the clock did meanwhile.
- codex: sets CODEX_HOME=UB_HOME/codex-homes/<provider> and UB_HOST_FAMILY, then runs `codex <args>`.
- ub: runs `<this python> <kit>/skills/ultimate-brainstorm/scripts/ub.py <args>` (terminal mode and the other ub
  commands).

The user's ~/.claude/settings.json and ~/.codex/config.toml are never read or written.

The module also exposes the renderers install.py uses to write launchers and Codex homes (see the "Rendering API"
section below). It carries its own small config merge, and takes the security-critical process helpers (executable
lookup that never searches the current folder, the .cmd argument check, System32 tools, process liveness) from
ublib.proc, the kit's single copy of them, and a provider's endpoint and models from the worker's
ublib.families.provider_settings_env, so a launcher and a claude-cli@<provider> call agree (4.16).

Exit codes: the child's exit code; 2 usage or missing key/config; 1 other failure (tool not installed, bad file).
"""

import atexit
import json
import os
import re
import secrets
import signal
import stat
import subprocess
import sys
import threading
from pathlib import Path

KIT_VERSION = "2.1.0"
IS_WINDOWS = os.name == "nt"

PROFILES_DIR = Path(__file__).resolve().parent
KIT_DIR = PROFILES_DIR.parent
SK_DIR = KIT_DIR / "skills" / "ultimate-brainstorm"
FAMILIES_DEFAULT = SK_DIR / "scripts" / "families.default.json"
UB_PY = SK_DIR / "scripts" / "ub.py"

if str(SK_DIR / "scripts") not in sys.path:
    sys.path.insert(0, str(SK_DIR / "scripts"))
from ublib import families, proc  # noqa: E402  (provider_settings_env; which, check_cmd_args, system_tool, ...)

# launch-<pid>-<hex12>.json / zai-mcp-<pid>-<hex12>.json in UB_HOME/tmp (write_secret_file names; group 1, pid group
# 2), each with a <name>.id file holding the writer's process identity (group 3 = ".id")
SECRET_FILE_RE = re.compile(r"^((?:launch|zai-mcp)-(\d+)-[0-9a-f]{12}\.json)(\.id)?$")
IDENT_SUFFIX = ".id"
_SECRET_FILES = []  # the secret files this process wrote; a path leaves the list only once its file is gone
# Taken by every removal: the Windows console handler (its own thread) then waits for a removal in progress on the main
# thread instead of letting the process end while a file is still on disk. Re-entrant: a POSIX signal handler runs on
# the main thread, possibly inside a removal.
_SECRET_LOCK = threading.RLock()
_CLOSING = []  # set by the console handler: the process ends as soon as it returns, so no new secret file is written
_CONSOLE_HANDLER = []  # keeps the Windows console handler callback alive

# Which family a provider serves (sets UB_HOST_FAMILY for the launched host).
PROVIDER_FAMILY = {"glm": "glm", "kimi": "kimi", "kimi-code": "kimi"}
CLAUDE_PROVIDERS = ("glm", "kimi", "kimi-code")
CODEX_PROVIDERS = ("glm", "kimi")
TOOLS = ("claude", "codex", "ub")

INSTALL_HINTS = {
    "claude": "npm install -g @anthropic-ai/claude-code   (then run `claude` once and sign in)",
    "codex": "npm install -g @openai/codex   (then: codex login)",
}

# Z.ai MCP servers for --zai-mcp. The global URLs are in the Z.ai devpack docs [V]; the cn host follows the rule
# "--region cn switches every base URL to open.bigmodel.cn" (10.6) and is not confirmed by a vendor page. # [U-19]
ZAI_MCP_BASE = {"global": "https://api.z.ai/api/mcp", "cn": "https://open.bigmodel.cn/api/mcp"}

# Codex home base URLs (4.16). Kimi has no documented China base for this route. # [U-22]
# [U-33] the Z.ai Responses endpoint for Coding Plan keys (and its cn twin) is not vendor-confirmed; the live PING in
# `install.py doctor --live` checks it, and UB_HOME/families.json providers.<p>.codex_base_url overrides it.
# [U-6] CODEX_HOME isolation is used instead of model_providers inside a --profile file.
CODEX_HOME_BASE_URL = {
    "glm": {"global": "https://api.z.ai/api/v1", "cn": "https://open.bigmodel.cn/api/v1"},
    "kimi": {"global": "https://api.moonshot.ai/v1"},
}


class LaunchError(Exception):
    """A failure with a user-facing message and an exit code."""

    def __init__(self, message, code=1):
        Exception.__init__(self, message)
        self.code = code


# ---------------------------------------------------------------------------------------------------------------
# Paths and config
# ---------------------------------------------------------------------------------------------------------------

def ub_home(environ=None):
    """UB_HOME from the environment, otherwise ~/.ultimate-brainstorm (3.2)."""
    env = os.environ if environ is None else environ
    value = env.get("UB_HOME")
    if value:
        return Path(value).expanduser().resolve()
    return (Path.home() / ".ultimate-brainstorm").resolve()


def _read_json_file(path):
    raw = Path(path).read_bytes()
    if raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff"):
        text = raw.decode("utf-16")
    else:
        text = raw.decode("utf-8-sig")
    return json.loads(text)


def deep_merge(base, override):
    """Return base deep-merged with override: dicts merge recursively; any other value replaces."""
    if not isinstance(base, dict) or not isinstance(override, dict):
        return override
    out = dict(base)
    for key, value in override.items():
        if key in out and isinstance(out[key], dict) and isinstance(value, dict):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def load_config(home=None, defaults_path=None):
    """families.default.json deep-merged with UB_HOME/families.json (4.16 step 1)."""
    home = Path(home) if home is not None else ub_home()
    defaults_path = Path(defaults_path) if defaults_path is not None else FAMILIES_DEFAULT
    try:
        cfg = _read_json_file(defaults_path)
    except FileNotFoundError:
        raise LaunchError("The kit is incomplete: %s is missing. Re-run the installer (install.py install)."
                          % defaults_path.as_posix(), 1)
    except (ValueError, UnicodeDecodeError) as exc:
        raise LaunchError("Cannot read %s: %s" % (defaults_path.as_posix(), exc), 1)
    user_file = home / "families.json"
    if user_file.is_file():
        try:
            cfg = deep_merge(cfg, _read_json_file(user_file))
        except (ValueError, UnicodeDecodeError) as exc:
            raise LaunchError("%s is not valid JSON (%s). Fix or remove it, then try again."
                              % (user_file.as_posix(), exc), 2)
        bad = _shape_error(cfg)
        if bad:
            raise LaunchError("%s: %s must be %s. Fix or remove it, then try again."
                              % (user_file.as_posix(), bad[0], bad[1]), 2)
    return cfg


def _shape_error(cfg):
    """(key, what it must be) for the first value the launcher reads that a hand-edited families.json turned into
    something else, else None. A missing or empty value counts as absent, as every reader treats it; base_url may also
    be one URL (a string)."""
    obj, text = "a JSON object", "a string"
    if not isinstance(cfg, dict):
        return "the top level", obj
    if not isinstance(cfg.get("region") or "", str):
        return "region", text
    for sect in ("providers", "backends"):
        entries = cfg.get(sect) or {}
        if not isinstance(entries, dict):
            return sect, obj
        for name, entry in entries.items():
            entry = entry or {}
            if not isinstance(entry, dict):
                return "%s.%s" % (sect, name), obj
            for key, want, types in (("base_url", "a JSON object or a URL", (dict, str)), ("models", obj, (dict,)),
                                     ("env", obj, (dict,)), ("token_env", text, (str,)), ("token_var", text, (str,))):
                if not isinstance(entry.get(key) or types[0](), types):
                    return "%s.%s.%s" % (sect, name, key), want
    return None


def provider_settings_env(cfg, provider, tier="default", region=None):
    """The env block for a provider, WITHOUT the token: ublib.families.provider_settings_env, the worker's rule (4.9).

    region is an explicit --region: one the provider has no endpoint for is refused, never guessed. A families.json
    region the provider lacks falls back to global, as for the worker's claude-cli@<provider> calls. # [U-22]"""
    providers = cfg.get("providers") or {}
    p = providers.get(provider)
    if not isinstance(p, dict):
        raise LaunchError("Unknown provider %r. Known: %s" % (provider, ", ".join(sorted(providers)) or "none"), 2)
    base_urls = p.get("base_url") or {}
    if region and isinstance(base_urls, dict) and region not in base_urls:
        raise LaunchError("Provider %s has no %s endpoint. Use --region %s."
                          % (provider, region, " or --region ".join(sorted(base_urls)) or "global"), 2)
    env = families.provider_settings_env(cfg, provider, tier, region)
    if not env.get("ANTHROPIC_BASE_URL"):  # never start claude with a provider token and Anthropic's own endpoint
        raise LaunchError("Provider %s has no global base_url in families config." % provider, 2)
    return env


def token_env_for(cfg, tool, provider):
    """Name of the environment variable that must hold the provider's key."""
    if tool == "codex":
        backend = (cfg.get("backends") or {}).get("codex-cli@" + provider) or {}
        if backend.get("token_env"):
            return backend["token_env"]
    p = (cfg.get("providers") or {}).get(provider) or {}
    name = p.get("token_env")
    if not name:
        raise LaunchError("Provider %s has no token_env in families config." % provider, 2)
    return name


# ---------------------------------------------------------------------------------------------------------------
# Secret files
# ---------------------------------------------------------------------------------------------------------------

def ensure_private_dir(path):
    """Create path (and parents) and make it 0700 on POSIX."""
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    if not IS_WINDOWS:
        try:
            os.chmod(str(path), 0o700)
        except OSError:
            pass
    return path


def _user_principal():
    """'*<SID>' of the current user (whoami /user), else DOMAIN\\USER, else USER; None when unknown."""
    who = proc.system_tool("whoami")  # System32 only, never a PATH lookup (a planted whoami.exe must not run)
    if who:
        try:
            res = subprocess.run([who, "/user", "/fo", "csv", "/nh"], stdin=subprocess.DEVNULL,
                                 stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=30)
            m = re.search(r"(S-1-[0-9-]+)", res.stdout.decode("utf-8", "replace"))
            if res.returncode == 0 and m:
                return "*" + m.group(1)
        except (OSError, subprocess.SubprocessError):
            pass
    user = os.environ.get("USERNAME")
    if not user:
        return None
    dom = os.environ.get("USERDOMAIN")
    return ("%s\\%s" % (dom, user)) if dom else user


def _restrict_windows_acl(path):
    """icacls <f> /inheritance:r /grant:r "<user SID>:F" (3.1). Returns True on success."""
    user = _user_principal()
    icacls = proc.system_tool("icacls")
    if not user or not icacls:
        return False
    try:
        res = subprocess.run([icacls, str(path), "/inheritance:r", "/grant:r", user + ":F"],
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             timeout=30)
    except (OSError, subprocess.SubprocessError):
        return False
    return res.returncode == 0


def write_secret_file(directory, prefix, text, suffix=".json"):
    """Create a new file readable only by this user (0600 / owner-only ACL) and write text into it.

    The file is created empty first, restricted, and only then filled, so the secret never sits in a file with
    wider permissions."""
    directory = ensure_private_dir(directory)
    for _ in range(20):
        path = directory / ("%s-%d-%s%s" % (prefix, os.getpid(), secrets.token_hex(6), suffix))
        try:
            fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o600)
        except FileExistsError:
            continue
        os.close(fd)
        break
    else:
        raise LaunchError("Could not create a temporary file in %s" % directory.as_posix(), 1)
    with _SECRET_LOCK:  # a console close waits until the file is complete, then deletes it
        _SECRET_FILES.append(path)
        try:
            if _CLOSING:
                raise LaunchError("the console is closing; not writing the key", 1)
            _write_identity(path)
            if IS_WINDOWS:
                if not _restrict_windows_acl(path):
                    # 3.1 item 9: a secret goes only into an owner-only file; never write it with inherited ACLs
                    raise LaunchError("could not restrict %s with icacls; not writing the key" % path.name, 1)
            else:
                os.chmod(str(path), 0o600)
            with open(str(path), "w", encoding="utf-8", newline="\n") as f:
                f.write(text)
        except BaseException:
            remove_secret_files()
            raise
    return path


def _write_identity(path):
    """Record in <path>.id which process wrote the secret file (proc.process_identity: Windows creation time, Linux boot
    id + start ticks). The sweep compares it with the process that holds the pid now; no clock step changes either.
    Not a secret; best effort (without it the sweep keeps the file while its pid runs)."""
    ident = proc.process_identity(os.getpid())
    if not ident:
        return
    try:
        with open(str(path) + IDENT_SUFFIX, "w", encoding="utf-8", newline="\n") as f:
            f.write(ident + "\n")
    except OSError:
        pass


def remove_quietly(path, attempts=10):
    """Delete a file, retrying briefly on Windows sharing errors. Never raises."""
    if path is None:
        return
    import time
    for i in range(attempts):
        try:
            os.remove(str(path))
            return
        except FileNotFoundError:
            return
        except OSError:
            if i == attempts - 1:
                sys.stderr.write("warning: could not delete %s; delete it by hand.\n" % Path(path).as_posix())
                return
            time.sleep(0.2)


def remove_secret_files():
    """Delete every secret file this process wrote, then its .id file (finally, atexit, signal and console handlers).
    Idempotent: a path stays listed until its file is gone, and a caller that finds another removal in progress waits
    for it (_SECRET_LOCK) and then removes what is left. Never raises."""
    with _SECRET_LOCK:
        for path in list(_SECRET_FILES):
            remove_quietly(path)
            if os.path.lexists(str(path)):
                continue
            remove_quietly(str(path) + IDENT_SUFFIX)
            if path in _SECRET_FILES:
                _SECRET_FILES.remove(path)


def _launcher_gone(pid, secret_path, mtime):
    """True when the launcher that wrote secret_path (at mtime) no longer runs: its pid is free, or the process that
    holds the pid now is not the one recorded in secret_path.id (a reused pid). Only identities of the same kind are
    compared (Windows, Linux and macOS `ps` identities do not change with a clock step, and ps runs in UTC). A file
    without an .id (an older launcher) is judged by the Windows creation time, which no clock step moves; elsewhere it
    is kept while its pid runs. An unknown identity keeps the file."""
    if not proc.pid_alive(pid):
        return True
    now = proc.process_identity(pid)
    if not now:
        return False
    try:
        with open(secret_path + IDENT_SUFFIX, "r", encoding="utf-8") as f:
            recorded = f.read().strip()
    except (OSError, ValueError):  # an undecodable .id counts as no record (UnicodeDecodeError is a ValueError)
        recorded = ""
    kind = now.split(":", 1)[0]
    if recorded:
        return recorded != now and recorded.split(":", 1)[0] == kind
    if kind == "win":
        started = proc.process_start_time(pid)
        return started is not None and started > mtime + 1.0
    return False


def sweep_stale_secret_files(tmp_dir):
    """Delete UB_HOME/tmp/launch-<pid>-*.json and zai-mcp-<pid>-*.json (with their .id files) left by launchers that
    ended without any cleanup (TerminateProcess, SIGKILL, a crash): see _launcher_gone. A file of a live launcher is
    always kept: no age rule, since an interactive session can last longer than any limit. Returns the number of
    secret files removed."""
    removed = 0
    try:
        names = os.listdir(str(tmp_dir))
    except OSError:
        return 0
    for name in names:
        m = SECRET_FILE_RE.match(name)
        if not m or int(m.group(2)) == os.getpid():
            continue
        secret = os.path.join(str(tmp_dir), m.group(1))
        if m.group(3) and os.path.lexists(secret):
            continue  # an .id file goes with its secret file
        path = os.path.join(str(tmp_dir), name)
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            continue
        if not _launcher_gone(int(m.group(2)), secret, mtime):
            continue
        remove_quietly(path, attempts=3)
        if not m.group(3) and not os.path.exists(path):
            removed += 1
            remove_quietly(secret + IDENT_SUFFIX, attempts=3)
    return removed


def _on_signal(signum, _frame):
    """SIGTERM / SIGHUP (terminal closed) on POSIX: ignore further ones (bash forwards SIGHUP and the session end sends
    another, which must not interrupt the cleanup), pass it on to the child, delete the secret files, then unwind so
    the launcher exits with 128 + signum."""
    for name in ("SIGTERM", "SIGHUP"):
        sig = getattr(signal, name, None)
        if sig is not None:
            try:
                signal.signal(sig, signal.SIG_IGN)
            except (OSError, ValueError):
                pass
    for child in list(_CHILD):
        try:
            child.send_signal(signum)
        except OSError:
            pass
    remove_secret_files()
    raise SystemExit(128 + signum)


def _on_console_event(event):
    """Windows console control handler (SetConsoleCtrlHandler). The system ends the process right after a handler for
    CTRL_CLOSE_EVENT (2), CTRL_LOGOFF_EVENT (5) or CTRL_SHUTDOWN_EVENT (6) returns, without unwinding, so the secret
    files go here; when the main thread is removing them at that moment, remove_secret_files waits for it, so this
    never returns while a file it wrote is still on disk. CTRL_BREAK_EVENT (1) reaches the child too; like Ctrl+C the
    launcher keeps waiting for it (TRUE), and `finally` cleans up. CTRL_C_EVENT (0) is left to Python's own handler
    (FALSE)."""
    if event in (2, 5, 6):
        with _SECRET_LOCK:
            _CLOSING.append(event)
            remove_secret_files()
        return True
    return event == 1


def guard_secret_files():
    """Install the exit paths `finally` cannot see: atexit, SIGTERM/SIGHUP (POSIX), console events (Windows)."""
    atexit.register(remove_secret_files)
    if IS_WINDOWS:
        try:
            import ctypes
            from ctypes import wintypes
            routine = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.DWORD)(_on_console_event)
            if ctypes.WinDLL("kernel32").SetConsoleCtrlHandler(routine, True):
                _CONSOLE_HANDLER.append(routine)
        except (AttributeError, OSError, ValueError):
            pass
        return
    for name in ("SIGTERM", "SIGHUP"):
        sig = getattr(signal, name, None)
        if sig is not None:
            try:
                signal.signal(sig, _on_signal)
            except (OSError, ValueError):  # not the main thread
                pass


# ---------------------------------------------------------------------------------------------------------------
# Process helpers
# ---------------------------------------------------------------------------------------------------------------

_CHILD = []  # the running child (run_child), for the signal handler


def resolve_tool(name, environ=None):
    """Full path of name on the PATH of environ, never the current folder (ublib.proc.resolve_exe: a claude.cmd planted
    in a repository must not receive --settings)."""
    return proc.resolve_exe(name, os.environ if environ is None else environ)


def check_cmd_args(exe_path, args):
    """Refuse arguments that cannot pass safely through a .cmd/.bat shim (3.1; ublib.proc.check_cmd_args)."""
    try:
        proc.check_cmd_args(exe_path, args)
    except proc.UnsafeArgument as exc:
        raise LaunchError("%s. Leave that character out, or type it inside the session instead." % exc, 2)


def run_child(argv, env):
    """Run argv with inherited stdin/stdout/stderr, wait, return its exit code.

    Ctrl+C reaches the child directly (same console); the launcher keeps waiting so the child decides how to exit,
    and cleanup still runs afterwards."""
    try:
        child = subprocess.Popen(argv, env=env)
    except OSError as exc:
        raise LaunchError("Could not start %s: %s" % (argv[0], exc), 1)
    _CHILD.append(child)
    try:
        while True:
            try:
                return child.wait()
            except KeyboardInterrupt:
                continue
    finally:
        _CHILD.remove(child)


def _scrubbed(env, names):
    up = set(n.upper() for n in names)
    return dict((k, v) for k, v in env.items() if k.upper() not in up)


# ---------------------------------------------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------------------------------------------

def launch_claude(opts, args, environ=None):
    environ = dict(os.environ if environ is None else environ)
    provider = opts.get("provider")
    if provider not in CLAUDE_PROVIDERS:
        raise LaunchError("claude needs --provider %s" % "|".join(CLAUDE_PROVIDERS), 2)
    if opts.get("zai_mcp") and provider != "glm":
        raise LaunchError("--zai-mcp works only with --provider glm", 2)
    home = ub_home(environ)
    cfg = load_config(home)
    token_var_name = token_env_for(cfg, "claude", provider)
    token = proc._env_get(environ, token_var_name)  # in any letter case on Windows, as detection reads it
    if not token:
        raise LaunchError("Set %s first (see docs/FAMILIES.md)" % token_var_name, 2)
    settings_env = provider_settings_env(cfg, provider, opts.get("tier") or "default", opts.get("region"))
    region = opts.get("region") or cfg.get("region") or "global"  # of the Z.ai MCP endpoint (--zai-mcp)
    token_var = ((cfg.get("providers") or {}).get(provider) or {}).get("token_var") or "ANTHROPIC_AUTH_TOKEN"
    exe = resolve_tool("claude", environ)
    if not exe:
        raise LaunchError("claude is not installed or not on PATH. Install it: %s" % INSTALL_HINTS["claude"], 1)

    child_env = dict(environ)
    child_env["UB_HOST_FAMILY"] = PROVIDER_FAMILY[provider]
    child_env["UB_HOME"] = str(home)
    # The settings file env outranks shell exports for the same names [V]. The OTHER Anthropic auth variable is not
    # in the settings file, so a user's own ANTHROPIC_API_KEY / ANTHROPIC_AUTH_TOKEN could compete with the provider
    # token; drop both from this session's environment (the token is in the settings file). [L]
    child_env = _scrubbed(child_env, ["ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"])

    tmp_dir = home / "tmp"
    sweep_stale_secret_files(tmp_dir)
    guard_secret_files()
    try:
        payload = dict(settings_env)
        payload[token_var] = token
        settings_file = write_secret_file(tmp_dir, "launch", json.dumps({"env": payload}, indent=1) + "\n")
        argv = [exe, "--settings", str(settings_file)]
        if opts.get("zai_mcp"):
            mcp_file = write_secret_file(tmp_dir, "zai-mcp", render_zai_mcp(token, region))
            argv += ["--mcp-config", str(mcp_file)]  # [U-19] Z.ai MCP through --mcp-config: opt-in only
        argv += list(args)
        check_cmd_args(exe, argv[1:])
        return run_child(argv, child_env)
    finally:
        remove_secret_files()


def launch_codex(opts, args, environ=None):
    environ = dict(os.environ if environ is None else environ)
    provider = opts.get("provider")
    if provider not in CODEX_PROVIDERS:
        raise LaunchError("codex needs --provider %s" % "|".join(CODEX_PROVIDERS), 2)
    if opts.get("zai_mcp"):
        raise LaunchError("--zai-mcp works only with claude", 2)
    home = ub_home(environ)
    cfg = load_config(home)
    token_var_name = token_env_for(cfg, "codex", provider)
    if not proc._env_get(environ, token_var_name):  # in any letter case on Windows, as detection reads it
        raise LaunchError("Set %s first (see docs/FAMILIES.md)" % token_var_name, 2)
    codex_home = home / "codex-homes" / provider
    if not (codex_home / "config.toml").is_file():
        setup = "setup-glm" if provider == "glm" else "setup-kimi"
        raise LaunchError("%s is missing. Run: install.py %s --codex" % ((codex_home / "config.toml").as_posix(),
                                                                          setup), 2)
    exe = resolve_tool("codex", environ)
    if not exe:
        raise LaunchError("codex is not installed or not on PATH. Install it: %s" % INSTALL_HINTS["codex"], 1)
    child_env = dict(environ)
    # The user's own Codex home, so the kit's native gpt backend inside this session still uses ~/.codex (or the
    # user's CODEX_HOME) and never this provider home.
    own = proc._env_get(environ, "CODEX_HOME") or ""
    try:
        if own and Path(own).expanduser().resolve().is_relative_to(home / "codex-homes"):
            own = proc._env_get(environ, "UB_USER_CODEX_HOME") or ""
    except (AttributeError, OSError, ValueError):
        pass
    child_env = _scrubbed(child_env, ["CODEX_HOME", "UB_USER_CODEX_HOME"])
    child_env["UB_USER_CODEX_HOME"] = own
    child_env["CODEX_HOME"] = str(codex_home)
    child_env["UB_HOST_FAMILY"] = PROVIDER_FAMILY[provider]
    child_env["UB_HOME"] = str(home)
    argv = [exe] + list(args)
    check_cmd_args(exe, argv[1:])
    return run_child(argv, child_env)


def launch_ub(opts, args, environ=None):
    environ = dict(os.environ if environ is None else environ)
    if opts.get("provider") or opts.get("zai_mcp"):
        raise LaunchError("ub takes no --provider or --zai-mcp", 2)
    if not UB_PY.is_file():
        raise LaunchError("The kit is incomplete: %s is missing. Re-run the installer." % UB_PY.as_posix(), 1)
    environ.setdefault("UB_HOME", str(ub_home(environ)))
    return run_child([sys.executable, str(UB_PY)] + list(args), environ)


# ---------------------------------------------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------------------------------------------

USAGE = """usage:
  launch.py claude --provider glm|kimi|kimi-code [--region global|cn] [--tier default|fast] [--zai-mcp] -- ARGS
  launch.py codex  --provider glm|kimi -- ARGS
  launch.py ub     -- ARGS
  launch.py render-launcher NAME --bin DIR [--python EXE] [--ub-home DIR] -- LAUNCH_ARGS
  launch.py render-codex-home glm|kimi --out DIR [--region global|cn]
  launch.py version
"""


def parse_launch_args(argv):
    """Split `<tool> [options] [--] <passthrough>`.

    Known options are read until `--` (which is consumed) or the first other token; everything after is passed
    to the tool unchanged. Accepting a missing `--` keeps the launchers working if a shell drops it."""
    if not argv:
        raise LaunchError(USAGE, 2)
    tool = argv[0]
    opts = {"provider": None, "region": None, "tier": None, "zai_mcp": False}
    i = 1
    while i < len(argv):
        a = argv[i]
        if a == "--":
            i += 1
            break
        if a in ("--provider", "--region", "--tier"):
            if i + 1 >= len(argv):
                raise LaunchError("%s needs a value" % a, 2)
            opts[a[2:]] = argv[i + 1]
            i += 2
            continue
        if a.startswith(("--provider=", "--region=", "--tier=")):
            k, v = a[2:].split("=", 1)
            opts[k] = v
            i += 1
            continue
        if a == "--zai-mcp":
            opts["zai_mcp"] = True
            i += 1
            continue
        break
    if opts["region"] not in (None, "global", "cn"):
        raise LaunchError("--region must be global or cn", 2)
    if opts["tier"] not in (None, "default", "fast"):
        raise LaunchError("--tier must be default or fast", 2)
    return tool, opts, argv[i:]


def _cli_render_launcher(argv):
    if not argv:
        raise LaunchError(USAGE, 2)
    name = argv[0]
    bin_dir = python = home = None
    i = 1
    launch_args = []
    while i < len(argv):
        a = argv[i]
        if a == "--":
            launch_args = argv[i + 1:]
            break
        if a in ("--bin", "--python", "--ub-home") and i + 1 < len(argv):
            if a == "--bin":
                bin_dir = argv[i + 1]
            elif a == "--python":
                python = argv[i + 1]
            else:
                home = argv[i + 1]
            i += 2
            continue
        raise LaunchError("unknown option %r\n%s" % (a, USAGE), 2)
    if not bin_dir:
        raise LaunchError("--bin DIR is required", 2)
    if not launch_args:
        launch_args = default_launch_args(name)
    paths = write_launchers(bin_dir, name, launch_args, ub_home_dir=home, python_exe=python)
    for p in paths:
        print(Path(p).as_posix())
    return 0


def _cli_render_codex_home(argv):
    if not argv:
        raise LaunchError(USAGE, 2)
    provider = argv[0]
    out = None
    region = "global"
    i = 1
    while i < len(argv):
        if argv[i] == "--out" and i + 1 < len(argv):
            out = argv[i + 1]
        elif argv[i] == "--region" and i + 1 < len(argv):
            region = argv[i + 1]
        else:
            raise LaunchError("unknown option %r\n%s" % (argv[i], USAGE), 2)
        i += 2
    if not out:
        raise LaunchError("--out DIR is required", 2)
    print(write_codex_home(out, provider, region).as_posix())
    return 0


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    try:
        if not argv or argv[0] in ("-h", "--help", "help"):
            sys.stdout.write(USAGE)
            return 0 if argv else 2
        if argv[0] in ("version", "--version"):
            print(KIT_VERSION)
            return 0
        if argv[0] == "render-launcher":
            return _cli_render_launcher(argv[1:])
        if argv[0] == "render-codex-home":
            return _cli_render_codex_home(argv[1:])
        tool, opts, rest = parse_launch_args(argv)
        if tool == "claude":
            return launch_claude(opts, rest)
        if tool == "codex":
            return launch_codex(opts, rest)
        if tool == "ub":
            return launch_ub(opts, rest)
        raise LaunchError("unknown tool %r (expected one of %s)\n%s" % (tool, ", ".join(TOOLS), USAGE), 2)
    except LaunchError as exc:
        sys.stderr.write(str(exc).rstrip("\n") + "\n")
        return exc.code


# ---------------------------------------------------------------------------------------------------------------
# Rendering API (used by install.py; also callable through the render-* commands above)
# ---------------------------------------------------------------------------------------------------------------
#
# Launcher templates (profiles/launcher.{sh,cmd,ps1}.tpl) use these placeholders:
#   {{NAME}}         launcher name, e.g. claude-glm
#   {{VERSION}}      kit version
#   {{LAUNCH_ARGS}}  tokens for launch.py, e.g. `claude --provider glm --region cn` (validated: [A-Za-z0-9._-]+)
#   {{UB_HOME_SH}} {{PY_SH}}    POSIX paths, escaped for single quotes
#   {{UB_HOME_WIN}} {{PY_WIN}}  Windows paths (backslashes) for cmd.exe double quotes
#   {{UB_HOME_PS}} {{PY_PS}}    Windows paths escaped for PowerShell single quotes
#   {{UTF8}}         1 when UB_HOME or the Python path is not ASCII (the .cmd then switches to code page 65001), else 0
# Output files: <bin>/<name> (LF, mode 0755), <bin>/<name>.cmd (CRLF), <bin>/<name>.ps1 (CRLF), all UTF-8; a .ps1
# holding a non-ASCII path starts with a BOM (launcher_bytes).
# Codex home templates use {{BASE_URL}} and {{REGION}} only; zai-mcp.json.tpl uses {{ZAI_MCP_BASE}} and
# {{ZAI_API_KEY}} (filled only at launch time, into a 0600 temp file).

LAUNCHER_KINDS = (("", "launcher.sh.tpl", "\n"), (".cmd", "launcher.cmd.tpl", "\r\n"), (".ps1", "launcher.ps1.tpl", "\r\n"))

# Default launch.py arguments per launcher name (install.py may pass others, e.g. `--region cn`).
DEFAULT_LAUNCHERS = {
    "ub": ["ub"],
    "claude-glm": ["claude", "--provider", "glm"],
    "claude-kimi": ["claude", "--provider", "kimi"],
    "codex-glm": ["codex", "--provider", "glm"],
    "codex-kimi": ["codex", "--provider", "kimi"],
}

_TOKEN_RX = re.compile(r"^[A-Za-z0-9._-]+$")
_NAME_RX = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_PLACEHOLDER_RX = re.compile(r"\{\{[A-Z0-9_]+\}\}")


def default_launch_args(name):
    if name not in DEFAULT_LAUNCHERS:
        raise LaunchError("no default launch arguments for %r; pass them after --" % name, 2)
    return list(DEFAULT_LAUNCHERS[name])


def launcher_args(tool, provider=None, region=None, zai_mcp=False, tier=None):
    """Build the launch.py argument list for a launcher, e.g. launcher_args("claude", "glm", region="cn")."""
    out = [tool]
    if provider:
        out += ["--provider", provider]
    if region and region != "global":
        out += ["--region", region]
    if tier and tier != "default":
        out += ["--tier", tier]
    if zai_mcp:
        out.append("--zai-mcp")
    return out


def render_template(text, mapping):
    """Replace every {{KEY}} with mapping[KEY]; fail on any placeholder left unresolved."""
    for key, value in mapping.items():
        text = text.replace("{{%s}}" % key, value)
    left = _PLACEHOLDER_RX.findall(text)
    if left:
        raise LaunchError("unresolved template placeholders: %s" % ", ".join(sorted(set(left))), 1)
    return text


def _sq_sh(value):
    return str(value).replace("'", "'\\''")


def _sq_ps(value):
    return str(value).replace("'", "''")


def _read_template(name):
    return (PROFILES_DIR / name).read_text(encoding="ascii").replace("\r\n", "\n")


def render_launchers(name, launch_args, ub_home_dir=None, python_exe=None):
    """Return {filename: text} for the three launcher forms of `name` (texts already use their final newlines)."""
    if not _NAME_RX.match(name):
        raise LaunchError("bad launcher name %r" % name, 2)
    launch_args = list(launch_args)
    if not launch_args or launch_args[0] not in TOOLS:
        raise LaunchError("launch args must start with one of %s" % ", ".join(TOOLS), 2)
    for tok in launch_args:
        if not _TOKEN_RX.match(tok):
            raise LaunchError("bad launch argument %r" % tok, 2)
    home = Path(ub_home_dir).expanduser().resolve() if ub_home_dir else ub_home()
    py = Path(python_exe).resolve() if python_exe else Path(sys.executable).resolve()
    for label, value in (("UB_HOME", home), ("python", py)):
        if any(ch in str(value) for ch in '"%\r\n'):
            raise LaunchError("the %s path %s contains a character a launcher cannot quote" % (label, value), 1)
    mapping = {
        "NAME": name,
        "VERSION": KIT_VERSION,
        "LAUNCH_ARGS": " ".join(launch_args),
        "UB_HOME_SH": _sq_sh(home.as_posix()),
        "PY_SH": _sq_sh(py.as_posix()),
        "UB_HOME_WIN": str(home).replace("/", "\\"),
        "PY_WIN": str(py).replace("/", "\\"),
        "UB_HOME_PS": _sq_ps(str(home).replace("/", "\\") if IS_WINDOWS else home.as_posix()),
        "PY_PS": _sq_ps(str(py).replace("/", "\\") if IS_WINDOWS else py.as_posix()),
        # the .cmd reads its path lines as UTF-8 (code page 65001) when a path is not ASCII (launcher.cmd.tpl)
        "UTF8": "0" if (str(home) + str(py)).isascii() else "1",
    }
    out = {}
    for suffix, template, newline in LAUNCHER_KINDS:
        text = render_template(_read_template(template), mapping)
        out[name + suffix] = text.replace("\n", newline)
    return out


def launcher_bytes(fname, text):
    """A rendered launcher as the bytes install.py writes too: UTF-8, and a .ps1 that holds a non-ASCII path starts
    with a BOM (Windows PowerShell 5.1 reads a .ps1 without one in the ANSI code page)."""
    data = text.encode("utf-8")
    if fname.endswith(".ps1") and not text.isascii():
        data = b"\xef\xbb\xbf" + data
    return data


def _write_atomic(path, data, mode=None):
    path = Path(path)
    tmp = path.with_name(".%s.tmp-%s" % (path.name, secrets.token_hex(4)))
    try:
        with open(str(tmp), "wb") as f:
            f.write(data)
        if mode is not None and not IS_WINDOWS:
            os.chmod(str(tmp), mode)
        os.replace(str(tmp), str(path))
    finally:
        if tmp.exists():
            remove_quietly(tmp)
    return path


def write_launchers(bin_dir, name, launch_args, ub_home_dir=None, python_exe=None):
    """Write <bin>/<name>, <name>.cmd and <name>.ps1 atomically; return the written paths."""
    bin_dir = Path(bin_dir)
    bin_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for fname, text in render_launchers(name, launch_args, ub_home_dir, python_exe).items():
        is_sh = not fname.endswith((".cmd", ".ps1"))
        mode = (stat.S_IRWXU | stat.S_IRGRP | stat.S_IXGRP | stat.S_IROTH | stat.S_IXOTH) if is_sh else None
        written.append(_write_atomic(bin_dir / fname, launcher_bytes(fname, text), mode))
    return written


def render_codex_home(provider, region="global"):
    """Text of UB_HOME/codex-homes/<provider>/config.toml (4.16). Holds no secret."""
    if provider not in CODEX_HOME_BASE_URL:
        raise LaunchError("no Codex home template for provider %r" % provider, 2)
    urls = dict(CODEX_HOME_BASE_URL[provider])
    # [U-33] families.json providers.<p>.codex_base_url (a URL, or {region: URL}) overrides the built-in URL; a
    # families.json that cannot be read raises, so the Codex home is never silently rendered without the override
    over = ((load_config().get("providers") or {}).get(provider) or {}).get("codex_base_url")
    if isinstance(over, str) and over.strip():
        urls[region] = over.strip()
    elif isinstance(over, dict):
        urls.update(dict((k, v) for k, v in over.items() if isinstance(v, str) and v.strip()))
    if region not in urls:
        raise LaunchError("provider %s has no %s endpoint for Codex" % (provider, region), 2)  # [U-22]
    # model_catalog_json is omitted on purpose; Codex prints a metadata warning, which is expected. # [U-28]
    text = _read_template("codex-home.%s.toml.tpl" % provider)
    return render_template(text, {"BASE_URL": urls[region], "REGION": region, "VERSION": KIT_VERSION})


def write_codex_home(home_dir, provider, region="global"):
    """Write <home_dir>/config.toml (creating home_dir); return its path."""
    home_dir = Path(home_dir)
    home_dir.mkdir(parents=True, exist_ok=True)
    return _write_atomic(home_dir / "config.toml", render_codex_home(provider, region).encode("utf-8"))


def render_zai_mcp(token, region="global"):
    """The --mcp-config JSON for the Z.ai web-search-prime and web-reader servers, with the token filled in.

    Only launch_claude calls this, writing the result into a 0600 temp file that is deleted after the session."""
    base = ZAI_MCP_BASE.get(region)
    if not base:
        raise LaunchError("no Z.ai MCP endpoint for region %r" % region, 2)
    text = _read_template("zai-mcp.json.tpl")
    escaped = json.dumps(str(token))[1:-1]  # JSON-escape the value; the template puts it inside a string
    text = render_template(text, {"ZAI_MCP_BASE": base, "ZAI_API_KEY": escaped})
    json.loads(text)  # must stay valid JSON
    return text


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass
    sys.exit(main())
