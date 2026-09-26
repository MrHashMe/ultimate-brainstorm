#!/usr/bin/env python3
"""ultimate-brainstorm launcher logic (KIT_SPEC 4.16). Python 3.9+, standard library only.

Run by the launchers that install.py writes into UB_HOME/bin (claude-glm, claude-kimi, codex-glm, codex-kimi, ub):

    launch.py claude --provider glm|kimi|kimi-code [--region global|cn] [--tier default|fast] [--zai-mcp] -- <args>
    launch.py codex  --provider glm|kimi -- <args>
    launch.py ub     -- <args>

- claude: writes a 0600 settings file UB_HOME/tmp/launch-<pid>-<rand>.json holding {"env": provider env + token},
  sets UB_HOST_FAMILY, runs `claude --settings <file> <args>`, waits, deletes the file in `finally` and returns
  claude's exit code. The token never appears in argv, logs or output.
- codex: sets CODEX_HOME=UB_HOME/codex-homes/<provider> and UB_HOST_FAMILY, then runs `codex <args>`.
- ub: runs `<this python> <kit>/skills/ultimate-brainstorm/scripts/ub.py <args>` (terminal mode and the other ub
  commands).

The user's ~/.claude/settings.json and ~/.codex/config.toml are never read or written.

The module also exposes the renderers install.py uses to write launchers and Codex homes (see the "Rendering API"
section below). By design it does not import ublib (4.16): it carries its own small config merge.

Exit codes: the child's exit code; 2 usage or missing key/config; 1 other failure (tool not installed, bad file).
"""

import json
import os
import re
import secrets
import stat
import subprocess
import sys
from pathlib import Path

KIT_VERSION = "2.0.3"
IS_WINDOWS = os.name == "nt"

PROFILES_DIR = Path(__file__).resolve().parent
KIT_DIR = PROFILES_DIR.parent
SK_DIR = KIT_DIR / "skills" / "ultimate-brainstorm"
FAMILIES_DEFAULT = SK_DIR / "scripts" / "families.default.json"
UB_PY = SK_DIR / "scripts" / "ub.py"

# Characters cmd.exe interprets even inside quotes; an argument holding one cannot pass safely through a .cmd/.bat
# shim (KIT_SPEC 3.1).
CMD_UNSAFE_CHARS = set('"&|<>^%!\r\n')

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
    return cfg


def provider_settings_env(cfg, provider, tier="default", region=None):
    """The env block for a provider, WITHOUT the token (same rules as ublib.families.provider_settings_env, 4.9)."""
    providers = cfg.get("providers") or {}
    if provider not in providers:
        raise LaunchError("Unknown provider %r. Known: %s" % (provider, ", ".join(sorted(providers)) or "none"), 2)
    p = providers[provider]
    region = region or cfg.get("region") or "global"
    base_urls = p.get("base_url") or {}
    if region not in base_urls:
        # No documented endpoint for this region; never guess one. # [U-22]
        raise LaunchError("Provider %s has no %s endpoint. Use --region %s."
                          % (provider, region, " or --region ".join(sorted(base_urls)) or "global"), 2)
    models = p.get("models") or {}
    if tier not in models:
        raise LaunchError("Provider %s has no %r model tier." % (provider, tier), 2)
    env = {
        "ANTHROPIC_BASE_URL": base_urls[region],
        "ANTHROPIC_MODEL": models[tier],
        "ANTHROPIC_DEFAULT_OPUS_MODEL": models.get("default"),
        "ANTHROPIC_DEFAULT_SONNET_MODEL": models.get("default"),
        "ANTHROPIC_DEFAULT_FABLE_MODEL": models.get("default"),
        "ANTHROPIC_DEFAULT_HAIKU_MODEL": models.get("fast"),
        "CLAUDE_CODE_SUBAGENT_MODEL": models.get("default"),
    }
    env = dict((k, v) for k, v in env.items() if v is not None)
    for k, v in (p.get("env") or {}).items():
        env[str(k)] = str(v)
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


def _system_tool(name):
    """%SystemRoot%\\System32\\<name>.exe, never a PATH lookup (a planted icacls.exe must not run)."""
    sysroot = os.environ.get("SystemRoot") or os.environ.get("SYSTEMROOT") or r"C:\Windows"
    candidate = os.path.join(sysroot, "System32", name + ".exe")
    return candidate if os.path.isfile(candidate) else None


def _user_principal():
    """'*<SID>' of the current user (whoami /user), else DOMAIN\\USER, else USER; None when unknown."""
    who = _system_tool("whoami")
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
    icacls = _system_tool("icacls")
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
    try:
        if IS_WINDOWS:
            if not _restrict_windows_acl(path):
                # 3.1 item 9: a secret goes only into an owner-only file; never write it with inherited ACLs
                raise LaunchError("could not restrict %s with icacls; not writing the key" % path.name, 1)
        else:
            os.chmod(str(path), 0o600)
        with open(str(path), "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
    except BaseException:
        remove_quietly(path)
        raise
    return path


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


# ---------------------------------------------------------------------------------------------------------------
# Process helpers
# ---------------------------------------------------------------------------------------------------------------

def resolve_tool(name, environ=None):
    """Full path of name on the PATH of environ, never the current folder (Python 3.9-3.11 on Windows search the
    current folder first with shutil.which, so a claude.cmd planted in a repository would receive --settings)."""
    env = os.environ if environ is None else environ
    path = _env_get(env, "PATH") if IS_WINDOWS else env.get("PATH")
    if path is None:
        path = os.defpath
    dirs = []
    for d in str(path).split(os.pathsep):
        d = os.path.expanduser(d.strip().strip('"'))
        if d and os.path.isabs(d):
            dirs.append(d)
    if IS_WINDOWS:
        pathext = [e.lower() for e in (os.environ.get("PATHEXT") or ".COM;.EXE;.BAT;.CMD").split(os.pathsep) if e]
        cands = [name] if os.path.splitext(name)[1].lower() in pathext else [name + e for e in pathext]
    else:
        cands = [name]
    for d in dirs:
        for c in cands:
            p = os.path.join(d, c)
            if os.path.isfile(p) and (IS_WINDOWS or os.access(p, os.X_OK)):
                return os.path.abspath(p)
    return None


def _env_get(env, name):
    up = name.upper()
    for k, v in env.items():
        if k.upper() == up:
            return v
    return None


def check_cmd_args(exe_path, args):
    """Refuse arguments that cannot pass safely through a .cmd/.bat shim (3.1)."""
    if not str(exe_path).lower().endswith((".cmd", ".bat")):
        return
    bad = sorted(set(ch for ch in str(exe_path) if ch in CMD_UNSAFE_CHARS))
    if bad:
        raise LaunchError("The path of %s contains %s, which cmd.exe re-parses; install the CLI under a folder "
                          "without these characters." % (os.path.basename(str(exe_path)), ", ".join(bad)), 1)
    for i, arg in enumerate(args):
        bad = sorted(set(ch for ch in str(arg) if ch in CMD_UNSAFE_CHARS))
        if bad:
            shown = ", ".join("CR" if c == "\r" else "LF" if c == "\n" else c for c in bad)
            raise LaunchError(
                "Argument %d contains %s, which cannot pass safely through %s (a Windows .cmd shim). "
                "Leave that character out, or type it inside the session instead."
                % (i + 1, shown, os.path.basename(str(exe_path))), 2)


def run_child(argv, env):
    """Run argv with inherited stdin/stdout/stderr, wait, return its exit code.

    Ctrl+C reaches the child directly (same console); the launcher keeps waiting so the child decides how to exit,
    and cleanup still runs afterwards."""
    try:
        proc = subprocess.Popen(argv, env=env)
    except OSError as exc:
        raise LaunchError("Could not start %s: %s" % (argv[0], exc), 1)
    while True:
        try:
            return proc.wait()
        except KeyboardInterrupt:
            continue


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
    token = environ.get(token_var_name)
    if not token:
        raise LaunchError("Set %s first (see docs/FAMILIES.md)" % token_var_name, 2)
    region = opts.get("region") or cfg.get("region") or "global"
    settings_env = provider_settings_env(cfg, provider, opts.get("tier") or "default", region)
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
    settings_file = None
    mcp_file = None
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
        remove_quietly(mcp_file)
        remove_quietly(settings_file)


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
    if not environ.get(token_var_name):
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
    own = _env_get(environ, "CODEX_HOME") or ""
    try:
        if own and Path(own).expanduser().resolve().is_relative_to(home / "codex-homes"):
            own = _env_get(environ, "UB_USER_CODEX_HOME") or ""
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
# Output files: <bin>/<name> (LF, mode 0755), <bin>/<name>.cmd (CRLF), <bin>/<name>.ps1 (CRLF).
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
    }
    out = {}
    for suffix, template, newline in LAUNCHER_KINDS:
        text = render_template(_read_template(template), mapping)
        out[name + suffix] = text.replace("\n", newline)
    return out


def _write_atomic(path, text, mode=None):
    path = Path(path)
    tmp = path.with_name(".%s.tmp-%s" % (path.name, secrets.token_hex(4)))
    try:
        with open(str(tmp), "w", encoding="ascii", newline="") as f:
            f.write(text)
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
        written.append(_write_atomic(bin_dir / fname, text, mode))
    return written


def render_codex_home(provider, region="global"):
    """Text of UB_HOME/codex-homes/<provider>/config.toml (4.16). Holds no secret."""
    if provider not in CODEX_HOME_BASE_URL:
        raise LaunchError("no Codex home template for provider %r" % provider, 2)
    urls = dict(CODEX_HOME_BASE_URL[provider])
    try:  # [U-33] families.json providers.<p>.codex_base_url (a URL, or {region: URL}) overrides the built-in URL
        over = ((load_config().get("providers") or {}).get(provider) or {}).get("codex_base_url")
    except Exception:  # noqa: BLE001 - no readable config: the built-in URLs
        over = None
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
    return _write_atomic(home_dir / "config.toml", render_codex_home(provider, region))


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
