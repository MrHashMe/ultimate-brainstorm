#!/usr/bin/env python3
"""ultimate-brainstorm kit installer (KIT_SPEC 4.14-4.16, 10.2-10.7). Python 3.9+, standard library only.

    install.py [plan] [--json]              detect and print the plan; writes nothing (the default)
    install.py install [--yes] [--json]     plan -> one confirmation (a TTY or --yes) -> apply
    install.py update  [--yes] [--json]     re-stage the kit (local --source, or --tag / github) -> plan -> apply
    install.py uninstall [--yes] [--purge] [--json]
    install.py doctor [--live] [--json]     read-only health checks; exit 1 on any FAIL
    install.py list [--json]
    install.py setup-glm  [--region global|cn] [--launcher] [--codex] [--zai-mcp] [--yes]
    install.py setup-kimi [--provider kimi|kimi-code] [--region global|cn] [--launcher] [--codex] [--yes]
    install.py version

Common flags: --agents auto|claude-code,codex,kimi,zcode  --scope user|project  --project-dir DIR
              --source DIR|github  --tag vX.Y.Z  --components core|none|core,+<extra>,...
              --with-clis claude,codex,kimi  --login  --force  --migrate-v1  --routing-block
              --claude-config-dir DIR  --codex-home DIR  --kimi-home DIR  --no-native  --backup-dir DIR

Exit codes: 0 ok (also "nothing to do"), 1 failure, 2 usage, 3 no supported agent detected and none named,
            4 blocked rows present with --yes, 5 cancelled by the user.

Hard limits (10.4 item 8): no sudo or admin; refuses root without UB_ALLOW_ROOT=1; never edits PATH or shell rc files;
never reads or writes API key values (only variable NAMES are checked); never edits settings.json, config.toml,
CLAUDE.md or AGENTS.md except the marker-delimited routing block with --routing-block. Copy-only installs (no symlinks).
"""

import sys

sys.dont_write_bytecode = True  # plan must write nothing, not even __pycache__ next to the source kit

import argparse  # noqa: E402
import codecs  # noqa: E402
import importlib.util  # noqa: E402
import datetime  # noqa: E402
import hashlib  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import random  # noqa: E402
import re  # noqa: E402
import shutil  # noqa: E402
import stat  # noqa: E402
import string  # noqa: E402
import subprocess  # noqa: E402
import tarfile  # noqa: E402
import tempfile  # noqa: E402
import time  # noqa: E402
import urllib.request  # noqa: E402

KIT_VERSION = "2.0.2"
INSTALL_DIR = os.path.dirname(os.path.abspath(__file__))
KIT_ROOT = os.path.dirname(INSTALL_DIR)
_SCRIPTS_DIR = os.path.join(KIT_ROOT, "skills", "ultimate-brainstorm", "scripts")
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

try:
    from ublib import proc, redact, textio  # noqa: E402  (B2 foundation modules)
except ImportError as _exc:  # pragma: no cover - only when install.py was copied without its kit
    sys.stderr.write("install.py: cannot import ublib from %s (%s). Run install.py from a complete kit.\n"
                     % (_SCRIPTS_DIR, _exc))
    raise SystemExit(1)

IS_WINDOWS = os.name == "nt"
SKILL = "ultimate-brainstorm"
MARKER = ".ub-owned"
PLUGIN_ID = "ultimate-brainstorm@ultimate-brainstorm"  # the experimental bundles/stack entry is never used [U-15]
MARKETPLACE = "ultimate-brainstorm"
AGENTS = ("claude-code", "codex", "kimi", "zcode")
DISPLAY = {"claude-code": "Claude Code", "codex": "Codex", "kimi": "Kimi Code", "zcode": "ZCode"}
CLI_AGENT = {"claude": "claude-code", "codex": "codex", "kimi": "kimi"}
COMMANDS = ("plan", "install", "update", "uninstall", "doctor", "list", "setup-glm", "setup-kimi", "version")
MUTATING = ("install", "update", "uninstall", "setup-glm", "setup-kimi")
STACK_SKILLS = ("ultimate-brainstorm", "grilling", "domain-modeling")

# 10.4 item 1: never staged or copied.
EXCLUDE_ANYWHERE = {"__pycache__", ".git", ".build"}
EXCLUDE_TOP = {"tests", "tools", ".github", "dist"}
EXCLUDE_SUFFIX = (".pyc", ".pyo")

ROUTING_BEGIN = "<!-- ultimate-brainstorm:begin -->"
ROUTING_END = "<!-- ultimate-brainstorm:end -->"
# The guide's routing block (ULTIMATE_BRAINSTORMING_WORKFLOW.md 3.5), updated for the v2 hosts and stages 12-14.
ROUTING_BLOCK = "\n".join([
    ROUTING_BEGIN,
    "## Brainstorming routing (user instruction; takes precedence over skill auto-trigger rules)",
    "- Requests to brainstorm, ideate, explore ideas, choose among ideas, decide what to build, name something, find a",
    "  research question, or turn an idea into an architecture and a proposal: use the ultimate-brainstorm skill",
    "  (Claude Code /ultimate-brainstorm, Codex and ZCode $ultimate-brainstorm, Kimi Code /skill:ultimate-brainstorm)",
    "  and follow its cards.",
    "- Exception: a small, well-defined change to existing code skips it (use superpowers:brainstorming or ce-brainstorm",
    "  if installed, otherwise proceed normally).",
    "- While a brainstorm/<run>/ folder exists without 12_HANDOFF.md, do not start another brainstorming, ideation or",
    "  planning skill (superpowers:brainstorming, ce-ideate, ce-brainstorm, office-hours, bmad-brainstorming,",
    "  product-brainstorming) unless the current ultimate-brainstorm card names it.",
    "- When you are executing a single prompt file from brainstorm/<run>/prompts/ or brainstorm/<run>/tournament/,",
    "  follow only that prompt and ignore this section.",
    ROUTING_END,
])

# Provider data used only when SK/scripts/families.default.json (B2) cannot be read. Values copied from 4.9 / 4.16.
FALLBACK_PROVIDERS = {
    "glm": {"token_env": "ZAI_API_KEY",
            "base_url": {"global": "https://api.z.ai/api/anthropic", "cn": "https://open.bigmodel.cn/api/anthropic"}},
    "kimi": {"token_env": "KIMI_API_KEY", "base_url": {"global": "https://api.moonshot.ai/anthropic"}},
    "kimi-code": {"token_env": "KIMI_CODE_API_KEY",
                  "base_url": {"global": "https://api.kimi.ai/coding/", "cn": "https://api.kimi.com/coding/"}},
}
CODEX_HOMES = {
    # [U-6] CODEX_HOME isolation, never model_providers inside a --profile file.
    # [U-33] the Z.ai Responses endpoint for Coding Plan keys (and its cn twin) is not vendor-confirmed: doctor --live.
    # 4.16: never experimental_bearer_token, wire_api = "chat" or [profiles.*]. model_catalog_json omitted [U-28].
    "glm": {"model": "glm-5.3", "provider_id": "zai", "name": "Z.ai", "env_key": "ZAI_API_KEY",
            "base_url": {"global": "https://api.z.ai/api/v1", "cn": "https://open.bigmodel.cn/api/v1"},  # cn: [L]
            "extra": ['model_reasoning_effort = "high"']},
    "kimi": {"model": "kimi-k3", "provider_id": "kimi", "name": "Kimi", "env_key": "KIMI_API_KEY",
             "base_url": {"global": "https://api.moonshot.ai/v1"},
             "extra": ["model_context_window = 1048576"]},
}
POLICY_GLM = ("The GLM Coding Plan may be used only in supported tools; this kit sends GLM traffic only through "
              "Claude Code or Codex.")

# 10.5 --purge deletes only what the kit creates in UB_HOME; anything else is listed and kept.
PURGE_NAMES = ("kit", "bin", "codex-homes", "tmp", "config.json", "families.json", "install-manifest.json",
               "install.log", "runs.json")
PURGE_RE = re.compile(r"^kit\.(new|old)-[a-z0-9]{8}$")

RE_ALREADY = re.compile(r"already\s+(installed|exists|added|present|enabled|registered|configured)|is already",
                        re.IGNORECASE)
RE_ABSENT = re.compile(r"not\s+(installed|found|present|registered)|no such|does not exist|unknown (plugin|marketplace)",
                       re.IGNORECASE)


class InstallError(Exception):
    """A failure with a user-facing message; exit code 1 unless code says otherwise."""

    def __init__(self, message, code=1):
        Exception.__init__(self, message)
        self.code = code


# --------------------------------------------------------------------------------------------------------------------
# small helpers


def posix(path):
    return None if path is None else os.path.abspath(os.fspath(path)).replace("\\", "/")


def now_iso():
    return textio.now_iso()


def path_stamp():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")


def rand_suffix(n=8):
    rng = random.SystemRandom()
    return "".join(rng.choice(string.ascii_lowercase + string.digits) for _ in range(n))


def parse_version(text):
    if not text:
        return None
    m = re.search(r"(\d+)\.(\d+)(?:\.(\d+))?", text)
    if not m:
        return None
    return (int(m.group(1)), int(m.group(2)), int(m.group(3) or 0))


def vtext(v):
    return None if v is None else "%d.%d.%d" % v


def version_ge(v, minimum):
    if v is None:
        return False
    return v >= parse_version(minimum)


def load_json_file(path, default=None):
    try:
        return json.loads(textio.read_text(path))
    except (OSError, ValueError):
        return default


def write_bytes_atomic(path, data):
    path = os.path.abspath(path)
    parent = os.path.dirname(path)
    os.makedirs(parent, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix="." + os.path.basename(path)[:40] + ".", suffix=".tmp", dir=parent)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        for i in range(10):
            try:
                os.replace(tmp, path)
                tmp = None
                break
            except PermissionError:
                if i == 9:
                    raise
                time.sleep(0.05 * (i + 1))
    finally:
        if tmp is not None:
            try:
                os.unlink(tmp)
            except OSError:
                pass


def read_bytes(path):
    try:
        with open(path, "rb") as f:
            return f.read()
    except OSError:
        return None


def rmtree(path):
    """Remove a tree; clears read-only bits (Windows) and never follows links out of it."""
    if not os.path.lexists(path):
        return

    def _retry(func, p, _exc):
        try:
            os.chmod(p, stat.S_IWRITE | stat.S_IREAD)
            func(p)
        except OSError:
            pass

    if os.path.islink(path) or os.path.isfile(path):
        os.unlink(path)
        return
    if sys.version_info >= (3, 12):
        shutil.rmtree(path, onexc=_retry)
    else:
        shutil.rmtree(path, onerror=_retry)


def walk_files(root, top_exclude=True):
    """{relpath (posix): abspath} under root, skipping caches, VCS folders and ownership markers."""
    out = {}
    root = os.path.abspath(root)
    for dirpath, dirnames, filenames in os.walk(root):
        rel_dir = os.path.relpath(dirpath, root)
        keep = []
        for d in dirnames:
            if d in EXCLUDE_ANYWHERE or os.path.islink(os.path.join(dirpath, d)):
                continue
            if top_exclude and rel_dir == "." and d in EXCLUDE_TOP:
                continue
            keep.append(d)
        dirnames[:] = sorted(keep)
        for name in sorted(filenames):
            if name == MARKER or name.endswith(EXCLUDE_SUFFIX):
                continue
            full = os.path.join(dirpath, name)
            if os.path.islink(full):
                continue
            rel = name if rel_dir == "." else rel_dir.replace("\\", "/") + "/" + name
            out[rel] = full
    return out


def hash_files(files):
    return {rel: textio.sha256_file(p) for rel, p in sorted(files.items())}


def copy_files(files, dest):
    for rel, src in sorted(files.items()):
        target = os.path.join(dest, *rel.split("/"))
        os.makedirs(os.path.dirname(target), exist_ok=True)
        shutil.copy2(src, target)


def move_aside(dest, trash_dir=None):
    """Rename dest out of the way before deleting it. Old trees go to trash_dir (UB_HOME/tmp) so a half-deleted tree
    never sits in an agent's skills folder as a second copy; the sibling path is used only when that rename fails
    (for example across volumes)."""
    if trash_dir:
        try:
            os.makedirs(trash_dir, exist_ok=True)
            old = os.path.join(trash_dir, "old-%s" % rand_suffix())
            os.replace(dest, old)
            return old
        except OSError:
            pass
    old = "%s.ub-old-%s" % (dest, rand_suffix())
    os.replace(dest, old)
    return old


def rmtree_checked(path):
    """rmtree, then report a leftover (Windows file locks, antivirus): '' or a 'delete it by hand' note."""
    rmtree(path)
    if os.path.lexists(path):
        return "could not delete %s; delete it by hand" % posix(path)
    return ""


def swap_in(new_dir, dest, trash_dir=None):
    """Atomically replace dest with new_dir (same volume). Restores the old tree when the swap fails.
    Returns '' or a note naming an old tree that could not be deleted."""
    old = None
    if os.path.lexists(dest):
        old = move_aside(dest, trash_dir)
    try:
        os.replace(new_dir, dest)
    except BaseException:
        if old is not None:
            try:
                os.replace(old, dest)
            except OSError:
                pass
        raise
    if old is not None:
        return rmtree_checked(old)
    return ""


def read_frontmatter(path):
    """Minimal YAML frontmatter reader: top-level scalars plus one level of nesting as 'parent.key'."""
    try:
        text = textio.read_text(path)
    except OSError:
        return None
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        return None
    out = {}
    parent = None
    for line in lines[1:]:
        if line.strip() == "---":
            break
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        m = re.match(r"^(\s*)([A-Za-z0-9_.-]+):\s*(.*)$", line)
        if not m:
            continue
        indent, key, value = m.group(1), m.group(2), m.group(3).strip()
        if value[:1] in ("'", '"') and value[-1:] == value[:1] and len(value) >= 2:
            value = value[1:-1].replace('\\"', '"')
        if not indent:
            parent = key if value == "" else None
            out[key] = value
        elif parent:
            out[parent + "." + key] = value
    return out


def is_v1_skill(folder):
    fm = read_frontmatter(os.path.join(folder, "SKILL.md")) or {}
    return fm.get("metadata.version", fm.get("version", "")).strip() in ("1.0", "1", "1.0.0")


def json_find(obj, pred):
    """Depth-first search; returns the first node for which pred(node) is True."""
    stack = [obj]
    while stack:
        node = stack.pop()
        if pred(node):
            return node
        if isinstance(node, dict):
            stack.extend(reversed(list(node.values())))
        elif isinstance(node, list):
            stack.extend(reversed(node))
    return None


def plugin_listed(obj, name, marketplace=None):
    """Tolerant check of a `plugin list --json` payload [U-18]: is plugin `name` (optionally @marketplace) listed?"""
    full = name + "@" + marketplace if marketplace else None

    def str_match(s):
        if not isinstance(s, str):
            return False
        if full:
            return s == full
        return s == name or s.startswith(name + "@")

    def pred(node):
        if isinstance(node, str):
            return str_match(node)
        if isinstance(node, dict):
            if any(str_match(k) for k in node.keys()):
                return True
            for field in ("id", "name", "plugin", "pluginId", "plugin_id"):
                val = node.get(field)
                if str_match(val):
                    return True
                if val == name:
                    if not marketplace:
                        return True
                    mk = None
                    for mf in ("marketplace", "marketplaceName", "marketplace_name", "source"):
                        if isinstance(node.get(mf), str):
                            mk = node.get(mf)
                            break
                    if mk is None or marketplace in mk:
                        return True
        return False

    return json_find(obj, pred) is not None


# --------------------------------------------------------------------------------------------------------------------
# context


class Ctx(object):
    def __init__(self, args, environ=None):
        self.args = args
        self.env = dict(os.environ if environ is None else environ)
        self.home = os.path.abspath(os.path.expanduser("~"))
        self.ub_home = os.path.abspath(os.path.expanduser(self.env.get("UB_HOME") or os.path.join(self.home, ".ultimate-brainstorm")))
        self.kit_dir = os.path.join(self.ub_home, "kit")
        self.bin_dir = os.path.join(self.ub_home, "bin")
        self.manifest_path = os.path.join(self.ub_home, "install-manifest.json")
        self.log_path = os.path.join(self.ub_home, "install.log")
        self.backup_root = os.path.abspath(args.backup_dir) if getattr(args, "backup_dir", None) else \
            os.path.join(self.ub_home, "backups")
        self.targets = load_json_file(os.path.join(INSTALL_DIR, "targets.json"))
        self.components = load_json_file(os.path.join(INSTALL_DIR, "components.json"))
        if not isinstance(self.targets, dict) or not isinstance(self.components, dict):
            raise InstallError("install/targets.json or install/components.json is missing or invalid")
        self.offline = self.env.get("UB_INSTALL_OFFLINE") == "1"
        self.scope = getattr(args, "scope", "user") or "user"
        self.project = os.path.abspath(getattr(args, "project_dir", None) or os.getcwd())
        self.homes = {
            "claude-code": self._home("claude-code", getattr(args, "claude_config_dir", None)),
            "codex": self._home("codex", getattr(args, "codex_home", None)),
            "kimi": self._home("kimi", getattr(args, "kimi_home", None)),
            "zcode": self._home("zcode", None),
        }
        self.agents_skills = os.path.join(self.home, ".agents", "skills")
        self.manifest = load_json_file(self.manifest_path)
        if not isinstance(self.manifest, dict):
            self.manifest = None
        self.source = KIT_ROOT
        self.source_is_temp = False
        # a random suffix keeps two runs in the same second from merging their backups
        self.stamp = path_stamp() + "-" + rand_suffix(4)
        self.tmp_dir = os.path.join(self.ub_home, "tmp")
        self.log_lines = []
        self.purged = False
        self.cleanup = []
        self.cache = {}

    def _home(self, agent, flag):
        if flag:
            return os.path.abspath(os.path.expanduser(flag))
        for item in self.targets["agents"][agent]["detect"].get("home", []):
            if item.startswith("$"):
                val = self.env.get(item[1:])
                if val:
                    return os.path.abspath(os.path.expanduser(val))
            else:
                return self.expand(item)
        return None

    def expand(self, template, extra=None):
        values = {"kit_dir": posix(self.kit_dir), "claude_home": posix(self.homes.get("claude-code")) if hasattr(self, "homes") else "",
                  "kimi_home": posix(self.homes.get("kimi")) if hasattr(self, "homes") else "",
                  "project": posix(self.project), "claude_scope": "local" if self.scope == "project" else "user"}
        if extra:
            values.update(extra)
        out = template
        for k, v in values.items():
            out = out.replace("{" + k + "}", v or "")
        if out == "~" or out.startswith("~/"):
            out = self.home + out[1:]
        return out

    def child_env(self, extra=None, agent=None):
        env = dict(self.env)
        args = self.args
        if agent == "claude-code" and getattr(args, "claude_config_dir", None):
            env["CLAUDE_CONFIG_DIR"] = self.homes["claude-code"]
        if agent == "codex" and getattr(args, "codex_home", None):
            env["CODEX_HOME"] = self.homes["codex"]
        if extra:
            env.update(extra)
        return env

    def log(self, line):
        self.log_lines.append("%s %s" % (now_iso(), redact.redact(line)))

    def flush_log(self):
        if not self.log_lines or self.purged:
            return
        try:
            for line in self.log_lines:
                textio.append_line(self.log_path, line)
        except OSError:
            pass
        self.log_lines = []


def run_cmd(ctx, argv, timeout=60, env=None, cwd=None, log=False):
    """Run argv (argv[0] resolved on PATH, never a shell). Returns (rc or None, stdout text, stderr text)."""
    env = env if env is not None else dict(ctx.env)
    try:
        exe = proc.resolve_exe(argv[0], env)
        if not exe:
            raise proc.ExecutableNotFound(argv[0])
        res = proc.run([exe] + list(argv[1:]), cwd=cwd, env=env, stdin_bytes=None, timeout_s=timeout)
        rc = res.returncode if not res.timed_out else None
        out = textio.decode_bytes(res.stdout_bytes)
        err = textio.decode_bytes(res.stderr_bytes)
        if res.timed_out:
            err = (err + "\ntimed out after %ss" % timeout).strip()
    except proc.ExecutableNotFound:
        rc, out, err = None, "", "%s: not found on PATH" % argv[0]
    except proc.UnsafeArgument as exc:
        rc, out, err = None, "", "refused: %s" % exc
    except OSError as exc:
        rc, out, err = None, "", "%s: %s" % (argv[0], exc)
    if log:
        tail = redact.redact((err or out or "").strip().splitlines()[-1] if (err or out or "").strip() else "")
        ctx.log("exit=%s %s%s" % (rc, redact.format_cmd(list(argv)), (" | " + tail[:300]) if tail else ""))
    return rc, out, err


def cmd_version(ctx, argv):
    key = ("version",) + tuple(argv)
    if key not in ctx.cache:
        rc, out, err = run_cmd(ctx, argv, timeout=15)
        ctx.cache[key] = parse_version(out + "\n" + err) if rc == 0 else None
    return ctx.cache[key]


def plugin_list(ctx, agent, codex_home=None):
    """Parsed `<cli> plugin list --json` for claude-code or codex, cached; None when unavailable [U-18]."""
    key = ("plugins", agent, codex_home)
    if key in ctx.cache:
        return ctx.cache[key]
    native = ctx.targets["agents"][agent].get("native")
    result = None
    if native:
        extra = {"CODEX_HOME": codex_home} if codex_home else None
        rc, out, err = run_cmd(ctx, native["list"], timeout=60, env=ctx.child_env(extra, agent))
        if rc == 0:
            try:
                result = textio.extract_json(out)
            except ValueError:
                result = None
    ctx.cache[key] = result
    return result


def find_git_bash(ctx):
    ksp = ctx.env.get("KIMI_SHELL_PATH")
    if ksp and os.path.isfile(ksp):
        return posix(ksp)
    candidates = []
    git = proc.resolve_exe("git", ctx.env)
    if git:
        d = os.path.dirname(git)
        for up in (os.path.dirname(d), os.path.dirname(os.path.dirname(d))):
            candidates.append(os.path.join(up, "bin", "bash.exe"))
    for base in (ctx.env.get("ProgramFiles") or ctx.env.get("PROGRAMFILES"), ctx.env.get("ProgramW6432"),
                 ctx.env.get("ProgramFiles(x86)"), os.path.join(ctx.env.get("LOCALAPPDATA", ""), "Programs")):
        if base:
            candidates.append(os.path.join(base, "Git", "bin", "bash.exe"))
    for c in candidates:
        if c and os.path.isfile(c):
            return posix(c)
    return None


def detect_system(ctx):
    if "system" in ctx.cache:
        return ctx.cache["system"]
    osname = "windows" if IS_WINDOWS else ("macos" if sys.platform == "darwin" else "linux")
    info = {"os": osname,
            "python": "%d.%d.%d (%s)" % (sys.version_info[0], sys.version_info[1], sys.version_info[2],
                                         posix(sys.executable)),
            "git": vtext(cmd_version(ctx, ["git", "--version"])),
            "node": vtext(cmd_version(ctx, ["node", "--version"])),
            "git_bash": find_git_bash(ctx) if IS_WINDOWS else None}
    ctx.cache["system"] = info
    ctx.cache["npx"] = proc.resolve_exe("npx", ctx.env)
    ctx.cache["npm"] = proc.resolve_exe("npm", ctx.env)
    return info


def kimi_plugin_installed(ctx):
    data = read_bytes(os.path.join(ctx.homes["kimi"], "plugins", "installed.json"))
    return bool(data) and b'"' + SKILL.encode() + b'"' in data


def expand_env(ctx, path):
    """~ and %VAR% / $VAR expansion against the installer's environment (targets.json app locations)."""
    out = re.sub(r"%([A-Za-z0-9_()]+)%", lambda m: ctx.env.get(m.group(1), m.group(0)), path)
    out = re.sub(r"\$([A-Za-z_][A-Za-z0-9_]*)", lambda m: ctx.env.get(m.group(1), m.group(0)), out)
    if out == "~" or out.startswith("~/"):
        out = ctx.home + out[1:]
    return out


def parse_agents_flag(ctx):
    raw = getattr(ctx.args, "agents", None) or "auto"
    if raw.strip() == "auto":
        return None
    names = [a.strip() for a in raw.split(",") if a.strip()]
    for a in names:
        if a not in AGENTS:
            raise InstallError("unknown agent %r in --agents (use auto or %s)" % (a, ",".join(AGENTS)), 2)
    return names


def parse_clis_flag(ctx):
    raw = getattr(ctx.args, "with_clis", None)
    if not raw:
        return []
    names = [c.strip() for c in raw.split(",") if c.strip()]
    for c in names:
        if c not in CLI_AGENT:
            raise InstallError("unknown CLI %r in --with-clis (use claude,codex,kimi)" % c, 2)
    return names


def detect_agents(ctx):
    if "agents" in ctx.cache:
        return ctx.cache["agents"]
    named = parse_agents_flag(ctx)
    clis = parse_clis_flag(ctx)
    extra_named = set(CLI_AGENT[c] for c in clis)
    res = {}
    for a in AGENTS:
        t = ctx.targets["agents"][a]
        d = {"agent": a, "home": ctx.homes[a], "bin": None, "version": None, "detected": False, "legacy": False,
             "named": bool(named and a in named) or a in extra_named, "route": "skip", "reason": ""}
        b = t["detect"].get("bin")
        if b:
            exe = proc.resolve_exe(b, ctx.env)
            if exe:
                d["bin"] = exe
                d["detected"] = True
                d["version"] = cmd_version(ctx, [b, "--version"])
            elif a in ("claude-code", "codex") and d["home"] and os.path.isdir(d["home"]):
                # the desktop app / IDE extension uses the same home without a CLI on PATH: copy route
                d["detected"] = True
                d["app_only"] = True
        else:
            spots = [ctx.expand(h) for h in t["detect"].get("home", []) if not h.startswith("$")]
            spots += [expand_env(ctx, p) for p in t["detect"].get("apps", [])]  # [U-21] ZCode install locations
            d["detected"] = any(os.path.exists(p) for p in spots)
        if a == "kimi" and d["version"] is not None and not version_ge(d["version"], t["detect"]["min"]):
            d["legacy"] = True
        if named is None:
            d["selected"] = d["detected"] or d["named"]
        else:
            d["selected"] = d["named"]
        res[a] = d
    ctx.cache["agents"] = res
    return res


# --------------------------------------------------------------------------------------------------------------------
# source kit


def runtime_files(ctx, root):
    files = {}
    for rp in ctx.targets.get("runtime_paths", []):
        full = os.path.join(root, *rp.split("/"))
        if os.path.isfile(full):
            files[rp] = full
        elif os.path.isdir(full):
            for rel, p in walk_files(full).items():
                files[rp + "/" + rel] = p
    return files


def skill_source(ctx):
    return os.path.join(ctx.source, "skills", SKILL)


def kit_version(root):
    try:
        v = textio.read_text(os.path.join(root, "VERSION")).strip()
        return v or KIT_VERSION
    except OSError:
        return KIT_VERSION


def source_commit(ctx):
    if not os.path.isdir(os.path.join(ctx.source, ".git")):
        return "local"
    rc, out, _ = run_cmd(ctx, ["git", "-C", ctx.source, "rev-parse", "--short", "HEAD"], timeout=15)
    return out.strip() if rc == 0 and out.strip() else "local"


def validate_source(root):
    need = [os.path.join(root, "install", "targets.json"), os.path.join(root, "skills", SKILL)]
    return all(os.path.exists(p) for p in need)


def resolve_source(ctx, command):
    args = ctx.args
    src = getattr(args, "source", None)
    tag = getattr(args, "tag", None)
    if src and src != "github":
        root = os.path.abspath(os.path.expanduser(src))
        if not validate_source(root):
            raise InstallError("--source %s is not a kit folder (install/targets.json and skills/%s missing)"
                               % (posix(root), SKILL), 2)
        ctx.source = root
        return
    if src == "github" or tag:
        ctx.source = fetch_release(ctx, tag)
        ctx.source_is_temp = True
        return
    if command == "update" and ctx.manifest:
        prev = ctx.manifest.get("source")
        if prev and not _same(prev, ctx.kit_dir) and validate_source(prev):
            ctx.source = os.path.abspath(prev)
            return
    if command == "update" and _same(KIT_ROOT, ctx.kit_dir):
        # 10.5: the staged kit cannot update itself; it re-stages from the latest release instead.
        repo = ctx.targets["kit"]["repo"]
        if not ctx.env.get("UB_RELEASE_DIR") and (ctx.offline or repo.startswith("OWNER/")):
            raise InstallError("update: this kit was installed from a release; pass --source DIR or --tag vX.Y.Z", 2)
        ctx.source = fetch_release(ctx, None)
        ctx.source_is_temp = True
        return
    ctx.source = KIT_ROOT


def under_temp(path):
    """True when path lies in the system temp folder (a bootstrap or --tag download that is deleted afterwards)."""
    p = os.path.normcase(os.path.realpath(os.path.abspath(path)))
    for t in {tempfile.gettempdir(), os.path.realpath(tempfile.gettempdir())}:
        t = os.path.normcase(os.path.abspath(t)).rstrip("\\/")
        if p == t or p.startswith(t + os.sep):
            return True
    return False


def _safe_extract(archive, dest):
    with tarfile.open(archive, "r:gz") as tf:
        members = []
        for m in tf.getmembers():
            name = m.name.replace("\\", "/")
            if name.startswith("/") or ".." in name.split("/") or re.match(r"^[A-Za-z]:", name):
                raise InstallError("unsafe path in release archive: %s" % m.name)
            if m.issym() or m.islnk() or m.isdev():
                continue
            members.append(m)
        if sys.version_info >= (3, 12):
            tf.extractall(dest, members=members, filter="data")
        else:
            tf.extractall(dest, members=members)


def fetch_release(ctx, tag):
    """Download (or copy from UB_RELEASE_DIR) the release tarball, verify SHA256SUMS, extract; returns the kit root."""
    repo = ctx.targets["kit"]["repo"]
    rel_dir = ctx.env.get("UB_RELEASE_DIR")
    if not rel_dir:
        if ctx.offline:
            raise InstallError("UB_INSTALL_OFFLINE=1: cannot download a release; use --source DIR")
        if repo.startswith("OWNER/"):
            raise InstallError("this kit copy names no GitHub owner (repo %s); use --source DIR" % repo)
    ver = tag[1:] if tag and tag.startswith("v") else tag
    if not ver and rel_dir:
        found = sorted(n for n in os.listdir(rel_dir) if re.match(r"^ultimate-brainstorm-[\d.]+\.tar\.gz$", n))
        if not found:
            raise InstallError("UB_RELEASE_DIR has no ultimate-brainstorm-<ver>.tar.gz")
        ver = found[-1][len("ultimate-brainstorm-"):-len(".tar.gz")]
    if not ver:  # [L] releases/latest redirects to .../releases/tag/vX.Y.Z
        try:
            with urllib.request.urlopen("https://github.com/%s/releases/latest" % repo, timeout=30) as r:
                final = r.geturl()
        except OSError as exc:
            raise InstallError("cannot resolve the latest release: %s" % exc)
        m = re.search(r"/tag/v?([0-9][0-9A-Za-z.\-]*)$", final)
        if not m:
            raise InstallError("cannot resolve the latest release from %s" % final)
        ver = m.group(1)
    name = "ultimate-brainstorm-%s.tar.gz" % ver
    tmp = tempfile.mkdtemp(prefix="ub-src-")
    ctx.cleanup.append(tmp)

    def get(fname):
        dst = os.path.join(tmp, fname)
        if rel_dir:
            src = os.path.join(rel_dir, fname)
            if not os.path.isfile(src):
                raise InstallError("UB_RELEASE_DIR is missing %s" % fname)
            shutil.copyfile(src, dst)
        else:
            url = "https://github.com/%s/releases/download/v%s/%s" % (repo, ver, fname)
            try:
                with urllib.request.urlopen(url, timeout=120) as r, open(dst, "wb") as f:
                    shutil.copyfileobj(r, f)
            except OSError as exc:
                raise InstallError("download failed: %s (%s)" % (url, exc))
        return dst

    archive = get(name)
    sums = textio.read_text(get("SHA256SUMS"))
    want = None
    for line in sums.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[-1].lstrip("*") == name:
            want = parts[0].lower()
    if not want or textio.sha256_file(archive) != want:
        raise InstallError("SHA-256 check failed for %s" % name)
    out = os.path.join(tmp, "src")
    _safe_extract(archive, out)
    for cand in [out] + [os.path.join(out, d) for d in sorted(os.listdir(out))]:
        if validate_source(cand):
            return cand
    raise InstallError("the release archive holds no kit")


# --------------------------------------------------------------------------------------------------------------------
# rows


def new_row(agent, item, action, how, path=None, commands=None, **private):
    row = {"n": 0, "agent": agent, "item": item, "action": action, "how": how,
           "path": posix(path) if path else None, "commands": commands or []}
    for k, v in private.items():
        row[k if k.startswith("_") else "_" + k] = v
    return row


def public_row(row):
    return {k: v for k, v in row.items() if not k.startswith("_")}


def manifest_entry(ctx, route, path=None, agent=None):
    if not ctx.manifest:
        return None
    for e in ctx.manifest.get("entries", []):
        if e.get("route") != route:
            continue
        if path is not None and e.get("path") and os.path.normcase(os.path.abspath(e["path"])) == \
                os.path.normcase(os.path.abspath(path)):
            return e
        if path is None and agent and e.get("agent") == agent:
            return e
    return None


def native_entry(ctx, agent):
    """The manifest's native entry for agent in the default home (not a setup-glm/-kimi provider CODEX_HOME)."""
    for e in (ctx.manifest or {}).get("entries", []):
        if e.get("route") == "native" and e.get("agent") == agent and not e.get("profile"):
            return e
    return None


def native_installed(ctx, agent, codex_home=None):
    """Is the kit's plugin listed by `<cli> plugin list --json` (default home, or a provider CODEX_HOME)?"""
    listed = plugin_list(ctx, agent, codex_home)
    return bool(listed is not None and plugin_listed(listed, SKILL, MARKETPLACE))


def cmd_refusal(ctx, exe):
    """None, or why the kit folder cannot pass through exe when it is a .cmd shim (cmd.exe metacharacters)."""
    try:
        proc.check_cmd_args(exe, [posix(ctx.kit_dir)])
    except proc.UnsafeArgument as exc:
        return str(exc)
    return None


def uninstall_native_row(ctx, agent, e, last_for_marketplace=True, action="remove"):
    """Row removing the kit's native plugin recorded by manifest entry e (10.5): the recorded scope and project,
    and the marketplace only when no other native entry of this agent and home still uses it."""
    native = ctx.targets["agents"][agent]["native"]
    codex_home = e.get("codex_home") if (agent == "codex" and e and e.get("profile")) else None
    un = list(native["uninstall"])
    cwd = None
    if agent == "claude-code":
        scope = (e or {}).get("scope") or "user"
        un += ["--scope", scope]
        if scope == "local":
            cwd = (e or {}).get("project") or ctx.project
    cmds = [un]
    if last_for_marketplace:
        cmds.append([ctx.expand(a) for a in native["marketplace_remove"]])
    item = "plugin %s" % SKILL + (" (CODEX_HOME=%s)" % codex_home if codex_home else "")
    return new_row(agent, item, action, "native", None, cmds, _kind="uninstall-native", native_agent=agent,
                   env_extra={"CODEX_HOME": codex_home} if codex_home else None, cwd=cwd, entry=e)


def copy_dest(ctx, agent):
    t = ctx.targets["agents"][agent]["copy"]
    if ctx.scope == "project":
        if agent in ("codex", "kimi"):
            # 10.3: Codex and Kimi share <project>/.agents/skills in project scope.
            return os.path.join(ctx.project, ".agents", "skills", SKILL)
        return os.path.join(ctx.expand(t["project"]), SKILL)
    return os.path.join(ctx.expand(t["user"]), SKILL)


def analyze_copy(ctx, agent, dest, warnings):
    """Row for copying the skill into dest (create/unchanged/update/backup+update/skip-not-owned/migrate-v1)."""
    src = skill_source(ctx)
    src_files = walk_files(src, top_exclude=False)
    src_hash = hash_files(src_files)
    item = "skill %s" % SKILL
    if not os.path.lexists(dest):
        return new_row(agent, item, "create", "copy", dest, _kind="copy", dest=dest, src=src, backup=None, hashes=src_hash)
    if os.path.isfile(os.path.join(dest, MARKER)):
        cur = hash_files(walk_files(dest, top_exclude=False))
        if cur == src_hash:
            return new_row(agent, item, "unchanged", "copy", dest, _kind="copy", dest=dest, src=src, hashes=src_hash)
        entry = manifest_entry(ctx, "copy", dest)
        recorded = (entry or {}).get("files")
        if isinstance(recorded, dict):
            edited = sorted(r for r, h in cur.items() if recorded.get(r) != h)
        else:
            edited = sorted(r for r, h in cur.items() if src_hash.get(r) != h)
        action = "backup+update" if edited else "update"
        return new_row(agent, item, action, "copy", dest, _kind="copy", dest=dest, src=src, backup=edited or None,
                       hashes=src_hash)
    short = dest.replace(ctx.home, "~", 1) if dest.startswith(ctx.home) else posix(dest)
    short = short.replace("\\", "/")
    if is_v1_skill(dest):
        if not getattr(ctx.args, "migrate_v1", False):
            warnings.append("%s exists (v1, not owned): use --migrate-v1 to back it up and replace it" % short)
        return new_row(agent, item, "migrate-v1", "copy", dest, _kind="copy", dest=dest, src=src, backup="all",
                       hashes=src_hash, migrate=bool(getattr(ctx.args, "migrate_v1", False)))
    if getattr(ctx.args, "force", False):
        warnings.append("%s exists and is not owned by this kit: --force backs it up and replaces it" % short)
        return new_row(agent, item, "backup+update", "copy", dest, _kind="copy", dest=dest, src=src, backup="all",
                       hashes=src_hash)
    warnings.append("%s exists and is not owned by this kit: left alone (use --force to back it up and replace it)"
                    % short)
    return new_row(agent, item, "skip-not-owned", "copy", dest, _kind="noop")


def removal_row(ctx, agent, dest, reason, warnings):
    """Row removing an owned copy that the coverage rule no longer wants (e.g. the agent is now native)."""
    if not os.path.isfile(os.path.join(dest, MARKER)):
        return None
    cur = hash_files(walk_files(dest, top_exclude=False))
    entry = manifest_entry(ctx, "copy", dest)
    recorded = (entry or {}).get("files") if entry else None
    edited = sorted(r for r, h in cur.items() if not isinstance(recorded, dict) or recorded.get(r) != h)
    warnings.append("%s: removing the owned copy at %s (%s)" % (agent, posix(dest), reason))
    return new_row(agent, "skill %s (duplicate)" % SKILL, "remove", "copy", dest, _kind="remove", dest=dest,
                   backup=edited or None)


def native_row(ctx, agent, mode, codex_home=None):
    native = ctx.targets["agents"][agent]["native"]
    subst = lambda argv: [ctx.expand(a) for a in argv]  # noqa: E731
    listed = plugin_list(ctx, agent, codex_home)
    installed = bool(listed is not None and plugin_listed(listed, SKILL, MARKETPLACE))
    extra_env = {"CODEX_HOME": codex_home} if codex_home else None
    cwd = ctx.project if (agent == "claude-code" and ctx.scope == "project") else None
    item = "plugin %s" % SKILL + (" (CODEX_HOME=%s)" % posix(codex_home) if codex_home else "")
    common = dict(_kind="native", env_extra=extra_env, cwd=cwd, native_agent=agent, codex_home=codex_home)
    if installed and mode == "update":
        if agent == "claude-code":  # [U-16] the local marketplace loads in place; this refresh may fail
            cmds = [["claude", "plugin", "marketplace", "update", MARKETPLACE]]
            return new_row(agent, item, "update", "native", None, cmds, allow_fail=True, **common)
        cmds = [["codex", "plugin", "marketplace", "upgrade", MARKETPLACE, "--json"], subst(native["install"])]
        # [U-10] whether `codex plugin add` upgrades in place is unverified: fall back to remove + add
        return new_row(agent, item, "update", "native", None, cmds,
                       fallback=[subst(native["uninstall"]), subst(native["install"])], **common)
    if installed:
        return new_row(agent, item, "unchanged", "native", None, [], **common)
    cmds = [subst(native["marketplace_add"]), subst(native["install"])]
    return new_row(agent, item, "install", "native", None, cmds, **common)


def component_ids(ctx):
    raw = getattr(ctx.args, "components", None) or "core"
    comps = ctx.components["components"]
    ids = []
    for tok in [t.strip() for t in raw.split(",") if t.strip()]:
        if tok == "core":
            ids.extend(ctx.components.get("core", []))
        elif tok == "none":
            continue
        else:
            name = tok.lstrip("+")
            if name not in comps:
                raise InstallError("unknown component %r (known: core, none, %s)" % (name, ", ".join(sorted(comps))), 2)
            ids.append(name)
    seen = []
    for i in ids:
        if i not in seen:
            seen.append(i)
    return seen


def skill_dirs_for(ctx, agent):
    """Directories an agent scans for user skills (duplicates check, component presence)."""
    if agent == "claude-code":
        return [os.path.join(ctx.homes["claude-code"], "skills")]
    if agent == "codex":
        # [U-11] ~/.codex/skills is deprecated but still scanned; the installer only writes ~/.agents/skills.
        return [ctx.agents_skills, os.path.join(ctx.homes["codex"], "skills")]
    if agent == "kimi":
        return [os.path.join(ctx.homes["kimi"], "skills"), ctx.agents_skills]
    return [os.path.join(ctx.homes["zcode"], "skills")]


def component_present(ctx, cid, agent):
    if cid == "mattpocock-grilling":
        dirs = skill_dirs_for(ctx, agent)
        return all(any(os.path.isdir(os.path.join(d, s)) for d in dirs) for s in ("grilling", "domain-modeling"))
    if agent in ("claude-code", "codex") and cid in ("compound-engineering", "pm-skills"):
        agents = detect_agents(ctx)
        if not agents[agent]["bin"]:
            return False
        listed = plugin_list(ctx, agent)
        if listed is None:
            return False
        names = ["compound-engineering"] if cid == "compound-engineering" else ["pm-product-discovery", "pm-execution"]
        return all(plugin_listed(listed, n) for n in names)
    if cid == "speckit":
        return proc.resolve_exe("specify", ctx.env) is not None
    return False


def step_how(argv):
    exe = argv[0]
    if exe == "npx":
        return "npx"
    if exe == "npm":
        return "npm"
    return "native"


def component_rows(ctx, agents, warnings, manual):
    """Rows for the stack components (10.4 item 4). # [U-27] npx sources are pinned by CLI version only
    (skills@1.7.0 in components.json), never by upstream commit."""
    rows = []
    comps = ctx.components["components"]
    system = detect_system(ctx)
    node_v = parse_version(system.get("node"))
    npx = ctx.cache.get("npx")
    for cid in component_ids(ctx):
        c = comps[cid]
        planned = {}
        keys = [a for a in AGENTS if a in c and agents[a]["selected"] and not agents[a]["legacy"]]
        if "all" in c:
            keys.append("all")
        for key in keys:
            entry = c[key]
            item = "component %s" % cid
            man_text = entry.get("manual")
            if "steps" not in entry:
                rows.append(new_row(key, item, "manual", "print", None, [], _kind="noop"))
                manual.append("%s: %s" % (DISPLAY.get(key, "All agents"), man_text))
                continue
            steps = [list(s) for s in entry["steps"]]
            if not man_text:
                man_text = "  then  ".join(" ".join(s) for s in steps)
            if key != "all" and component_present(ctx, cid, key):
                rows.append(new_row(key, item, "unchanged", step_how(steps[0]), None, [], _kind="noop"))
                planned[key] = "unchanged"
                continue
            if key == "kimi" and entry.get("skip_if_codex_step_ran") and planned.get("codex") == "install":
                warnings.append("kimi: %s comes from the Codex step (~/.agents/skills, which Kimi reads)" % cid)
                continue
            reason = None
            if ctx.offline:
                reason = "UB_INSTALL_OFFLINE=1"
            elif c.get("needs", {}).get("node") and any(s[0] == "npx" for s in steps):
                need = c["needs"]["node"]
                if not npx:
                    reason = "npx not found (needs Node %s+)" % need
                elif node_v is not None and not version_ge(node_v, need):
                    reason = "Node %s is older than %s" % (vtext(node_v), need)
            if reason is None:
                for s in steps:
                    if s[0] != "npx" and proc.resolve_exe(s[0], ctx.env) is None:
                        reason = "%s not found" % s[0]
                        break
            if reason:
                rows.append(new_row(key, item, "manual", "print", None, [], _kind="noop"))
                manual.append("%s: %s   (%s)" % (DISPLAY.get(key, "All agents"), man_text, reason))
                planned[key] = "manual"
                continue
            cmds = [list(s) for s in steps]
            resolve = entry.get("install_resolve")
            if resolve:  # [U-18] CE's Claude marketplace name is read back from `marketplace list --json`
                cmds.append(["claude", "plugin", "install", "%s@<marketplace>" % resolve["plugin"], "--scope", "user"])
            cwd = ctx.expand(entry["cwd"]) if entry.get("cwd") else None
            env_extra = dict(c.get("env", {}))
            if any(s[0] == "npx" for s in steps):
                env_extra["DISABLE_TELEMETRY"] = "1"
            rows.append(new_row(key, item, "install", step_how(steps[0]), None, cmds, _kind="component", cid=cid,
                                resolve=resolve, cwd=cwd, env_extra=env_extra, manual_text=man_text,
                                ref=c.get("ref")))
            planned[key] = "install"
    return rows


def cli_rows(ctx, warnings, manual):
    rows = []
    clis = parse_clis_flag(ctx)
    system = detect_system(ctx)
    node_v = parse_version(system.get("node"))
    for c in clis:
        spec = ctx.components["clis"][c]
        agent = CLI_AGENT[c]
        item = "CLI %s (%s)" % (c, spec["npm"])
        if proc.resolve_exe(c, ctx.env):
            rows.append(new_row(agent, item, "unchanged", "npm", None, [], _kind="noop"))
            continue
        cmd = ["npm", "install", "-g", spec["npm"]]
        if ctx.offline:
            rows.append(new_row(agent, item, "manual", "print", None, [], _kind="noop"))
            manual.append("%s: %s" % (DISPLAY[agent], " ".join(cmd)))
            continue
        blocked = None
        if not ctx.cache.get("npm"):
            blocked = "npm not found: install Node.js 22.20+ first"
        elif spec.get("node") and node_v is not None and not version_ge(node_v, spec["node"]):
            blocked = "Node %s is older than %s" % (vtext(node_v), spec["node"])
        elif IS_WINDOWS and spec.get("windows_requires") and not system.get("git_bash"):
            blocked = "needs %s" % spec["windows_requires"]
        if blocked:
            warnings.append("%s: %s" % (item, blocked))
            rows.append(new_row(agent, item, "blocked", "npm", None, [cmd], _kind="noop", reason=blocked))
            continue
        rows.append(new_row(agent, item, "install", "npm", None, [cmd], _kind="cli", cli=c))
    if getattr(ctx.args, "login", False):
        for c in ("codex", "kimi", "claude"):
            spec = ctx.components["clis"][c]
            agent = CLI_AGENT[c]
            present = proc.resolve_exe(c, ctx.env) or c in clis
            if not present:
                continue
            if "login_hint" in spec:
                rows.append(new_row(agent, "login %s" % c, "manual", "print", None, [], _kind="noop"))
                manual.append("%s: %s" % (DISPLAY[agent], spec["login_hint"]))
                continue
            done = (c == "codex" and os.path.isfile(os.path.join(ctx.homes["codex"], "auth.json"))) or \
                   (c == "kimi" and os.path.isdir(os.path.join(ctx.homes["kimi"], "credentials")) and
                    os.listdir(os.path.join(ctx.homes["kimi"], "credentials")))
            if done:
                rows.append(new_row(agent, "login %s" % c, "unchanged", "native", None, [], _kind="noop"))
            else:
                rows.append(new_row(agent, "login %s" % c, "install", "native", None, [list(spec["login"])],
                                    _kind="login"))
    return rows


def stage_row(ctx, warnings=None):
    src = hash_files(runtime_files(ctx, ctx.source))
    item = "stage kit"
    reason = None
    if os.path.isdir(ctx.kit_dir):
        cur = hash_files(walk_files(ctx.kit_dir))
        action = "unchanged" if cur == src else "update"
        new_v, old_v = kit_version(ctx.source), kit_version(ctx.kit_dir)
        if action == "update" and os.path.isfile(os.path.join(ctx.kit_dir, "VERSION")) and new_v != old_v:
            item = "stage kit %s -> %s" % (old_v, new_v)
            nv, ov = parse_version(new_v), parse_version(old_v)
            if nv is not None and ov is not None and nv < ov and not getattr(ctx.args, "force", False):
                reason = ("the source %s holds kit %s, older than the staged %s: not downgrading (pass --source DIR "
                          "or --tag with the version you want, or --force to downgrade)" % (posix(ctx.source), new_v,
                                                                                            old_v))
                action = "blocked"
                if warnings is not None:
                    warnings.append(reason)
    else:
        action = "create"
    return new_row("all", item, action, "copy", ctx.kit_dir, [], _kind="stage", reason=reason)


# launchers --------------------------------------------------------------------------------------------------------


def _sh_quote(s):
    return "'" + s.replace("'", "'\\''") + "'"


def _ps_quote(s):
    return "'" + s.replace("'", "''") + "'"


def _cmd_quote(s):
    return '"' + s + '"'


def builtin_launcher(kind, py, script, fixed_args):
    head = "ultimate-brainstorm launcher (generated by install.py; re-run the installer instead of editing)"
    # the same refusal as launch.py: these characters break out of the quoted paths in .cmd / .ps1 / sh files
    bad_chars = '"%\r\n' + ("!^" if kind == "cmd" else "")
    for label, value in (("Python", py), ("UB_HOME", script)):
        bad = sorted(set(c for c in value if c in bad_chars))
        if bad:
            raise InstallError("the %s path %s contains %s, which a launcher cannot quote safely; use a folder "
                               "without these characters" % (label, value, ", ".join(repr(c) for c in bad)))
    if kind == "sh":
        args = "".join(" " + _sh_quote(a) for a in fixed_args)
        return "#!/bin/sh\n# %s\nexec %s %s%s \"$@\"\n" % (head, _sh_quote(py), _sh_quote(script), args)
    if kind == "cmd":
        args = "".join(" " + a for a in fixed_args)
        return ("@echo off\r\nrem %s\r\n%s %s%s %%*\r\nexit /b %%ERRORLEVEL%%\r\n"
                % (head, _cmd_quote(py), _cmd_quote(script), args))
    args = "".join(" " + _ps_quote(a) for a in fixed_args)
    return "# %s\r\n& %s %s%s @args\r\nexit $LASTEXITCODE\r\n" % (head, _ps_quote(py), _ps_quote(script), args)


def launch_module(ctx):
    """profiles/launch.py of the source kit (B1-packaging), loaded as a module for its rendering API; None if absent."""
    if "launchmod" in ctx.cache:
        return ctx.cache["launchmod"]
    mod = None
    path = os.path.join(ctx.source, "profiles", "launch.py")
    if os.path.isfile(path):
        try:
            spec = importlib.util.spec_from_file_location("ub_profiles_launch_%s" % rand_suffix(), path)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
        except Exception:  # noqa: BLE001 - fall back to the built-in launcher text
            mod = None
    ctx.cache["launchmod"] = mod
    return mod


def launch_args_for(ctx, tool, provider=None, region=None, zai_mcp=False):
    mod = launch_module(ctx)
    if mod is not None and hasattr(mod, "launcher_args"):
        try:
            return list(mod.launcher_args(tool, provider, region=region, zai_mcp=zai_mcp))
        except Exception:  # noqa: BLE001
            pass
    out = [tool]
    if provider:
        out += ["--provider", provider]
    if region and region != "global":
        out += ["--region", region]
    if zai_mcp:
        out.append("--zai-mcp")
    return out


def launcher_set(ctx, name, launch_args):
    """{abs path: bytes} for <bin>/<name>, <name>.cmd and <name>.ps1. Each calls
    PY UB_HOME/kit/profiles/launch.py <launch_args> -- <user args> (4.16)."""
    mod = launch_module(ctx)
    if mod is not None and hasattr(mod, "render_launchers"):
        try:
            rendered = mod.render_launchers(name, list(launch_args), ub_home_dir=ctx.ub_home,
                                            python_exe=sys.executable)
        except Exception as exc:  # noqa: BLE001 - launch.py refused (e.g. an unquotable path): never work around it
            raise InstallError("launcher %s: %s" % (name, exc))
        files = {os.path.join(ctx.bin_dir, fname): text.encode("utf-8") for fname, text in rendered.items()}
        if len(files) == 3:
            return files
    script = posix(os.path.join(ctx.kit_dir, "profiles", "launch.py"))
    py = posix(sys.executable)
    fixed = list(launch_args) + ["--"]
    return {os.path.join(ctx.bin_dir, name + suffix): builtin_launcher(kind, py, script, fixed).encode("utf-8")
            for kind, suffix in (("sh", ""), ("cmd", ".cmd"), ("ps1", ".ps1"))}


def launcher_row(ctx, label, files):
    states = [read_bytes(p) == data for p, data in files.items()]
    if all(states):
        action = "unchanged"
    elif not any(os.path.exists(p) for p in files):
        action = "create"
    else:
        action = "update"
    return new_row("all", "launchers %s" % label, action, "copy", ctx.bin_dir, [], _kind="launchers", files=files)


def ub_launchers(ctx):
    return launcher_set(ctx, "ub", ["ub"])


def launcher_row_for(ctx, label, name, launch_args, warnings):
    """launcher_row, or a 'blocked' row when the launcher text cannot be rendered safely."""
    try:
        files = launcher_set(ctx, name, launch_args)
    except InstallError as exc:
        warnings.append(str(exc))
        return new_row("all", "launchers %s" % label, "blocked", "copy", ctx.bin_dir, [], _kind="noop",
                       reason=str(exc))
    return launcher_row(ctx, label, files)


# routing blocks ---------------------------------------------------------------------------------------------------


def routing_files(ctx, agents):
    out = []
    names = {"claude-code": "CLAUDE.md", "codex": "AGENTS.md", "kimi": "AGENTS.md", "zcode": "AGENTS.md"}
    for a in AGENTS:
        if agents[a]["detected"] and agents[a]["selected"]:
            out.append((a, os.path.join(ctx.homes[a], names[a])))
    return out


def routing_span(text):
    i = text.find(ROUTING_BEGIN)
    if i < 0:
        return None
    j = text.find(ROUTING_END, i)
    if j < 0:
        return None
    return i, j + len(ROUTING_END)


def read_instruction(path):
    """(text, had_bom, error, real_path) for CLAUDE.md / AGENTS.md. Decoding is strict UTF-8 (a UTF-8 BOM is kept on
    write); UTF-16 or any other encoding is an error, never a lossy rewrite. A symlink is followed to its target, so
    a dotfiles link keeps pointing at the (updated) file."""
    real = os.path.realpath(path) if os.path.islink(path) else path
    raw = read_bytes(real)
    if raw is None:
        return "", False, None, real
    if raw.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)) or b"\x00" in raw:
        return None, False, "%s is not UTF-8 (UTF-16); add the routing block by hand" % posix(path), real
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return None, False, "%s is not UTF-8; add the routing block by hand" % posix(path), real
    return text, raw.startswith(codecs.BOM_UTF8), None, real


def routing_row(ctx, agent, path, warnings=None):
    text, _bom, err, _real = read_instruction(path)
    if err:
        if warnings is not None:
            warnings.append(err)
        return new_row(agent, "routing block", "blocked", "copy", path, [], _kind="noop", reason=err)
    span = routing_span(text)
    if span is None:
        action = "create"
    else:
        cur = text[span[0]:span[1]].replace("\r\n", "\n")
        action = "unchanged" if cur == ROUTING_BLOCK else "update"
    return new_row(agent, "routing block", action, "copy", path, [], _kind="routing", file=path)


# plan -------------------------------------------------------------------------------------------------------------


def build_plan(ctx, mode, skip_clis=False):
    """mode: install | update | plan. Returns the plan dict (4.14) with private row fields."""
    system = detect_system(ctx)
    agents = detect_agents(ctx)
    warnings, manual, nxt = [], [], []
    rows = []
    if not skip_clis:
        rows.extend(cli_rows(ctx, warnings, manual))
    selected = [a for a in AGENTS if agents[a]["selected"]]
    no_native = getattr(ctx.args, "no_native", False)

    # routes (10.3)
    for a in AGENTS:
        d = agents[a]
        t = ctx.targets["agents"][a]
        if not d["selected"]:
            d["route"], d["reason"] = "skip", ("not detected" if not d["detected"] else "not selected")
            continue
        if a in ("claude-code", "codex"):
            nmin = t["native"]["min"]
            dest0 = copy_dest(ctx, a)
            unowned = os.path.isdir(dest0) and not os.path.isfile(os.path.join(dest0, MARKER))
            if ctx.scope == "project" and a == "codex":
                if d["bin"] and native_installed(ctx, a):
                    d["route"], d["reason"] = "skip", "user-scope native plugin already covers this project"
                    d["covered"] = True
                else:
                    d["route"], d["reason"] = "copy", "project scope"
            elif no_native:
                d["route"], d["reason"] = "copy", "--no-native"
            elif not d["bin"]:
                d["route"], d["reason"] = "copy", ("app/IDE only (no CLI on PATH)" if d.get("app_only")
                                                   else "CLI not installed (pre-install copy)")
            elif d["version"] is None:
                d["route"], d["reason"] = "copy", "version unknown"
            elif not version_ge(d["version"], nmin):
                d["route"], d["reason"] = "copy", "%s %s is older than %s" % (t["detect"]["bin"], vtext(d["version"]), nmin)
            elif cmd_refusal(ctx, d["bin"]):
                d["route"], d["reason"] = "copy", "UB_HOME path cannot pass through %s" % os.path.basename(d["bin"])
                warnings.append("%s: %s; the copy route is used instead (a UB_HOME without & ! %% ^ allows the "
                                "native plugin)" % (DISPLAY[a], cmd_refusal(ctx, d["bin"])))
            elif unowned:
                # a copy the installer does not own (e.g. `npx skills add`) plus the plugin would be two copies
                d["route"], d["reason"] = "copy", "an unowned copy already exists at %s" % posix(dest0)
            else:
                d["route"], d["reason"] = "native", ""
        elif a == "kimi":
            if d["legacy"] and not parse_agents_flag(ctx):
                d["route"], d["reason"] = "skip", "legacy kimi-cli %s" % vtext(d["version"])
                warnings.append("kimi %s is the legacy kimi-cli (unavailable): upgrade: npm install -g "
                                "@moonshot-ai/kimi-code, then kimi migrate" % vtext(d["version"]))
            elif kimi_plugin_installed(ctx):
                d["route"], d["reason"] = "skip", "Kimi plugin installed"
            else:
                d["route"], d["reason"] = "copy", ""
        else:
            d["route"], d["reason"] = "copy", ""
    if agents["kimi"]["selected"] and IS_WINDOWS and not system.get("git_bash"):
        warnings.append("Kimi Code on Windows needs Git for Windows (Git Bash) or KIMI_SHELL_PATH")
    if os.path.isdir(os.path.join(ctx.home, ".kimi")) and agents["kimi"]["selected"]:
        warnings.append("legacy ~/.kimi exists (old kimi-cli); Kimi Code v2 uses %s" % posix(ctx.homes["kimi"]))

    if not selected:
        plan = assemble_plan(ctx, system, agents, [], warnings, manual, nxt)
        plan["no_agents"] = True
        return plan

    stage = stage_row(ctx, warnings)
    rows.append(stage)
    # an update whose staged kit did not change re-runs no plugin commands (idempotent)
    native_mode = "install" if (mode == "update" and stage["action"] == "unchanged") else mode

    # claude-code and codex
    codex_copy_dest = None
    codex_copy_row = None
    for a in ("claude-code", "codex"):
        d = agents[a]
        if not d["selected"] or d["route"] == "skip":
            if d["selected"] and d.get("covered"):
                warnings.append("%s: %s (%s); no project copy is made" % (DISPLAY[a], d["reason"], posix(ctx.project)))
            continue
        dest = copy_dest(ctx, a)
        if d["route"] == "native":
            nrow = native_row(ctx, a, native_mode)
            rows.append(nrow)
            r = removal_row(ctx, a, dest, "now installed as a native plugin", warnings)
            if r:
                r["_requires"] = nrow  # kept when the plugin install fails (never zero copies)
                r["_verify_native"] = a
                rows.append(r)
        else:
            pre = None
            plugin_there = bool(d["bin"]) and native_installed(ctx, a)
            if plugin_there and ctx.scope == "user" and native_entry(ctx, a) is not None:
                others = [e for e in (ctx.manifest or {}).get("entries", []) if e.get("route") == "native" and
                          e.get("agent") == a and not e.get("profile") and e is not native_entry(ctx, a)]
                pre = uninstall_native_row(ctx, a, native_entry(ctx, a), last_for_marketplace=not others)
                rows.append(pre)
                warnings.append("%s: removing the kit's native plugin first (the copy route is used: %s)"
                                % (DISPLAY[a], d["reason"]))
            crow = analyze_copy(ctx, a, dest, warnings)
            if plugin_there and pre is None:
                warnings.append("%s: the plugin %s is installed (not by this installer) and a copy would make %s see "
                                "two copies: remove the plugin first, or keep it and leave %s out of --agents"
                                % (DISPLAY[a], PLUGIN_ID, DISPLAY[a], a))
                if crow["action"] not in NOOP_ACTIONS:
                    crow["action"] = "blocked"
                    crow["_kind"] = "noop"
            if pre is not None:
                crow["_requires"] = pre
            rows.append(crow)
            if a == "codex":
                codex_copy_dest = dest
                codex_copy_row = crow

    # kimi (coverage rule)
    d = agents["kimi"]
    if d["selected"] and d["route"] != "skip":
        dest = copy_dest(ctx, "kimi")
        shared = os.path.join(ctx.agents_skills, SKILL) if ctx.scope == "user" else dest
        removing = any(r.get("_kind") == "remove" and os.path.normcase(r["_dest"]) == os.path.normcase(shared)
                       for r in rows)
        shared_owned = os.path.isfile(os.path.join(shared, MARKER))
        cover_row = None
        foreign_kept = False
        if codex_copy_dest and os.path.normcase(codex_copy_dest) == os.path.normcase(shared):
            if codex_copy_row is not None and (codex_copy_row["action"] in ("skip-not-owned", "blocked") or (
                    codex_copy_row["action"] == "migrate-v1" and not codex_copy_row.get("_migrate"))):
                d["route"], d["reason"] = "skip", "sees the unowned copy in %s (Kimi reads it)" % posix(shared)
                foreign_kept = True
            else:
                d["route"], d["reason"] = "skip", "covered by the Codex copy in %s (Kimi reads it)" % posix(shared)
                cover_row = codex_copy_row if (codex_copy_row is not None and
                                               codex_copy_row["action"] not in NOOP_ACTIONS) else None
            d["covered"] = True
        elif ctx.scope == "user" and os.path.isdir(shared) and not removing:
            if shared_owned:
                d["route"], d["reason"] = "skip", "covered by %s (Kimi reads it)" % posix(shared)
                d["covered"] = True
            elif getattr(ctx.args, "force", False):
                cover_row = analyze_copy(ctx, "kimi", shared, warnings)  # --force: back it up and replace it
                rows.append(cover_row)
                d["route"], d["reason"] = "skip", "covered by %s (replaced with --force)" % posix(shared)
                d["covered"] = True
            else:
                warnings.append("%s is not owned by this kit: Codex and Kimi see it next to the kit's copies; remove "
                                "it or re-run with --force (it is backed up first)" % posix(shared))
                d["route"], d["reason"] = "skip", "sees the unowned copy in %s (Kimi reads it)" % posix(shared)
                d["covered"] = True
                foreign_kept = True
        if ctx.scope == "project" and d["route"] != "skip" and agents["codex"].get("covered"):
            warnings.append("Kimi's project copy in %s is also seen by Codex, next to its user-scope plugin"
                            % posix(dest))
        if d["route"] == "skip":
            if os.path.normcase(dest) != os.path.normcase(shared) and not foreign_kept:
                r = removal_row(ctx, "kimi", dest, "Kimi already sees %s" % posix(shared), warnings)
                if r:
                    if cover_row is not None:
                        r["_requires"] = cover_row  # kept when the covering copy fails
                    rows.append(r)
        else:
            rows.append(analyze_copy(ctx, "kimi", dest, warnings))
            if ctx.scope == "project" and not os.path.isdir(os.path.join(ctx.project, ".git")):
                if getattr(ctx.args, "git_init", False):
                    rows.append(new_row("kimi", "git init (project root for Kimi)", "create", "native", ctx.project,
                                        [["git", "init"]], _kind="gitinit"))
                else:  # [U-29] [L] Kimi finds the project root by .git
                    warnings.append("Kimi finds the project root by .git and %s has none: re-run with --git-init"
                                    % posix(ctx.project))
    elif d["selected"] and d["reason"] == "Kimi plugin installed":
        r = removal_row(ctx, "kimi", copy_dest(ctx, "kimi"), "the Kimi plugin is installed", warnings)
        if r:
            rows.append(r)

    # zcode
    if agents["zcode"]["selected"]:
        rows.append(analyze_copy(ctx, "zcode", copy_dest(ctx, "zcode"), warnings))

    rows.extend(component_rows(ctx, agents, warnings, manual))
    rows.append(launcher_row_for(ctx, "ub", "ub", ["ub"], warnings))
    if getattr(ctx.args, "routing_block", False):
        for a, path in routing_files(ctx, agents):
            rows.append(routing_row(ctx, a, path, warnings))

    for a in AGENTS:
        dd = agents[a]
        t = ctx.targets["agents"][a]
        if dd["selected"] and (dd["route"] != "skip" or dd.get("covered") or dd["reason"].startswith("covered") or
                               dd["reason"] == "Kimi plugin installed"):
            nxt.append("Start %s in your project and type: %s   (%s)" % (DISPLAY[a], t["invoke"], t["reload"]))
    if not agents["zcode"]["detected"] and parse_agents_flag(ctx) is None:
        nxt.append("ZCode not detected; use --agents zcode to install for it anyway")
    nxt.append("Terminal: %s run \"<your topic>\"   (optional: add %s to PATH; the installer never edits PATH)"
               % (posix(os.path.join(ctx.bin_dir, "ub")), posix(ctx.bin_dir)))
    nxt.append("Check the setup any time: python \"%s\" doctor" % posix(os.path.join(ctx.kit_dir, "install",
                                                                                     "install.py")))
    return assemble_plan(ctx, system, agents, rows, warnings, manual, nxt)


def assemble_plan(ctx, system, agents, rows, warnings, manual, nxt):
    for i, r in enumerate(rows, 1):
        r["n"] = i
    ag = {}
    for a in AGENTS:
        d = agents[a]
        e = {"detected": d["detected"]}
        if d["detected"]:
            e["version"] = vtext(d["version"])
            e["home"] = posix(d["home"])
        e["route"] = d["route"]
        if d["reason"]:
            e["reason"] = d["reason"]
        ag[a] = e
    return {"schema": 1,
            "kit": {"name": SKILL, "version": kit_version(ctx.source), "source": posix(ctx.source),
                    "commit": source_commit(ctx)},
            "system": system, "agents": ag, "rows": rows, "warnings": warnings, "manual": manual, "next": nxt}


def public_plan(plan):
    out = {k: v for k, v in plan.items() if k not in ("rows", "replan")}
    out["rows"] = [public_row(r) for r in plan["rows"]]
    if plan.get("replan") is not None:
        out["replan"] = [public_row(r) for r in plan["replan"]]
    return out


NOOP_ACTIONS = ("unchanged", "skip-not-owned", "manual", "blocked")


def actionable(rows):
    out = []
    for r in rows:
        if r["action"] in NOOP_ACTIONS:
            continue
        if r["action"] == "migrate-v1" and not r.get("_migrate"):
            continue
        out.append(r)
    return out


# --------------------------------------------------------------------------------------------------------------------
# text rendering


def _fmt_cmd(argv):
    return " ".join(('"%s"' % a) if (" " in a or a == "") else a for a in argv)


def plan_text(plan, title):
    lines = []
    k = plan["kit"]
    s = plan["system"]
    lines.append("ultimate-brainstorm %s installer - %s" % (k["version"], title))
    lines.append("source: %s (%s)" % (k["source"], k["commit"]))
    sysline = "system: %s, Python %s, git %s, node %s" % (s["os"], s["python"], s["git"] or "-", s["node"] or "-")
    if s["os"] == "windows":
        sysline += ", Git Bash %s" % (s["git_bash"] or "not found")
    lines.append(sysline)
    lines.append("")
    lines.append("Agents:")
    for a, e in plan["agents"].items():
        det = ("detected %s" % (e.get("version") or "")).strip() if e["detected"] else "not detected"
        extra = ("  (%s)" % e["reason"]) if e.get("reason") else ""
        lines.append("  %-12s %-20s route %-6s%s" % (a, det, e["route"], extra))
    rows = plan["rows"]
    if rows:
        lines.append("")
        lines.append("Plan:")
        lines.append("  %-3s %-12s %-44s %-15s %-7s %s" % ("#", "agent", "item", "action", "how", "path / commands"))
        for r in rows:
            first = r["path"] or (_fmt_cmd(r["commands"][0]) if r["commands"] else "")
            lines.append("  %-3s %-12s %-44s %-15s %-7s %s" % (r["n"], r["agent"], r["item"][:44], r["action"],
                                                             r["how"], first))
            cmds = r["commands"] if r["path"] else r["commands"][1:]
            for c in cmds:
                lines.append("  %s %s" % (" " * 84, _fmt_cmd(c)))
    for key, label in (("warnings", "Warnings"), ("manual", "Manual steps"), ("next", "Next")):
        if plan.get(key):
            lines.append("")
            lines.append(label + ":")
            for w in plan[key]:
                lines.append("  - " + w)
    return "\n".join(lines)


def out(ctx, text):
    if not getattr(ctx.args, "json", False):
        sys.stdout.write(text + "\n")
        sys.stdout.flush()


def emit_json(obj):
    sys.stdout.write(json.dumps(obj, ensure_ascii=True) + "\n")
    sys.stdout.flush()


def ask(question):
    sys.stderr.write(question + " [y/N] ")
    sys.stderr.flush()
    try:
        ans = sys.stdin.readline()
    except (OSError, KeyboardInterrupt):
        return False
    return ans.strip().lower() in ("y", "yes")


def is_tty():
    """True only for an interactive console. On Windows the NUL device also reports isatty(), so the console mode of
    the stdin handle is checked as well."""
    try:
        if sys.stdin is None or not sys.stdin.isatty():
            return False
    except (AttributeError, ValueError, OSError):
        return False
    if not IS_WINDOWS:
        return True
    try:
        import ctypes
        import msvcrt
        handle = msvcrt.get_osfhandle(sys.stdin.fileno())
        mode = ctypes.c_uint32()
        return bool(ctypes.windll.kernel32.GetConsoleMode(ctypes.c_void_p(handle), ctypes.byref(mode)))
    except Exception:  # noqa: BLE001
        return False


# --------------------------------------------------------------------------------------------------------------------
# apply


def backup_container(ctx, agent, source):
    """UB_HOME/backups/<stamp>/<agent>/<hash8>-<name>/ (unique per source path, so the user-scope and project-scope
    copies of one agent never overwrite each other's backup), with ORIGIN.txt naming the source."""
    h = hashlib.sha256(os.path.normcase(os.path.abspath(source)).encode("utf-8")).hexdigest()[:8]
    container = os.path.join(ctx.backup_root, ctx.stamp, agent, "%s-%s" % (h, os.path.basename(source)))
    os.makedirs(container, exist_ok=True)
    origin = os.path.join(container, "ORIGIN.txt")
    if not os.path.exists(origin):
        with open(origin, "w", encoding="utf-8", newline="\n") as f:
            f.write(posix(source) + "\n")
    return container


def backup_file(ctx, agent, path):
    """Copy one file into its backup container; returns the backup path (posix) or None when path is missing."""
    if not os.path.isfile(path):
        return None
    dst = os.path.join(backup_container(ctx, agent, path), os.path.basename(path))
    shutil.copy2(path, dst)
    return posix(dst)


def backup_paths(ctx, agent, root, rels):
    """Copy files (rels) or the whole tree (rels == 'all') under root to
    UB_HOME/backups/<stamp>/<agent>/<hash8>-<name>/<name>/."""
    base = os.path.join(backup_container(ctx, agent, root), os.path.basename(root))
    if rels == "all":
        for rel, src in walk_files(root, top_exclude=False).items():
            t = os.path.join(base, *rel.split("/"))
            os.makedirs(os.path.dirname(t), exist_ok=True)
            shutil.copy2(src, t)
        m = os.path.join(root, MARKER)
        if os.path.isfile(m):
            shutil.copy2(m, os.path.join(base, MARKER))
    else:
        for rel in rels:
            src = os.path.join(root, *rel.split("/"))
            if os.path.isfile(src):
                t = os.path.join(base, *rel.split("/"))
                os.makedirs(os.path.dirname(t), exist_ok=True)
                shutil.copy2(src, t)
    return posix(base)


def marker_bytes(ctx):
    return (json.dumps({"kit": SKILL, "version": kit_version(ctx.source), "installed_at": now_iso(),
                        "manifest": posix(ctx.manifest_path)}, ensure_ascii=True) + "\n").encode("ascii")


def do_stage(ctx, row):
    files = runtime_files(ctx, ctx.source)
    if os.path.normcase(os.path.abspath(ctx.source)) == os.path.normcase(os.path.abspath(ctx.kit_dir)):
        return "source is the staged kit"
    os.makedirs(ctx.ub_home, exist_ok=True)
    new = os.path.join(ctx.ub_home, "kit.new-" + rand_suffix())
    try:
        copy_files(files, new)
        old = None
        if os.path.lexists(ctx.kit_dir):
            old = os.path.join(ctx.ub_home, "kit.old-" + rand_suffix())
            os.replace(ctx.kit_dir, old)
        try:
            os.replace(new, ctx.kit_dir)
        except BaseException:
            if old is not None:
                try:
                    os.replace(old, ctx.kit_dir)
                except OSError:
                    pass
            raise
        if old is not None:
            rmtree(old)
    finally:
        if os.path.lexists(new):
            rmtree(new)
    ctx.log("staged kit %s -> %s (%d files)" % (posix(ctx.source), posix(ctx.kit_dir), len(files)))
    return "%d files" % len(files)


def do_copy(ctx, row, updates):
    dest = row["_dest"]
    if row["action"] == "migrate-v1" and not row.get("_migrate"):
        return "skip-not-owned"
    note = ""
    replaced = None
    if row.get("_backup"):
        replaced = backup_paths(ctx, row["agent"], dest, row["_backup"])
        note = "backup: " + replaced
    parent = os.path.dirname(dest)
    make_parents(ctx, parent, updates)
    new = "%s.ub-new-%s" % (dest, rand_suffix())
    try:
        files = walk_files(row["_src"], top_exclude=False)
        copy_files(files, new)
        with open(os.path.join(new, MARKER), "wb") as f:
            f.write(marker_bytes(ctx))
        left = swap_in(new, dest, ctx.tmp_dir)
        if left:
            note = (note + "; " + left).strip("; ")
    finally:
        if os.path.lexists(new):
            rmtree(new)
    hashes = hash_files(walk_files(dest, top_exclude=False))
    entry = {"agent": row["agent"], "route": "copy", "path": posix(dest), "scope": ctx.scope, "files": hashes}
    prev = manifest_entry(ctx, "copy", dest)
    if row.get("_backup") == "all" and replaced:
        entry["replaced_backup"] = replaced  # a foreign or v1 folder this copy replaced (named on uninstall)
    elif prev and prev.get("replaced_backup"):
        entry["replaced_backup"] = prev["replaced_backup"]
    updates["entries"].append(entry)
    ctx.log("copied skill -> %s (%d files) %s" % (posix(dest), len(hashes), note))
    return note


def do_remove(ctx, row, updates):
    dest = row["_dest"]
    note = ""
    if row.get("_backup"):
        note = "backup: " + backup_paths(ctx, row["agent"], dest, row["_backup"])
    if os.path.lexists(dest):
        left = rmtree_checked(move_aside(dest, ctx.tmp_dir))
        if left:
            note = (note + "; " + left).strip("; ")
    updates["remove_paths"].append(posix(dest))
    ctx.log("removed %s %s" % (posix(dest), note))
    return note


def make_parents(ctx, folder, updates):
    """os.makedirs(folder), recording each folder it created under HOME or the project (removed on uninstall when
    empty)."""
    missing = []
    cur = os.path.abspath(folder)
    while cur and not os.path.isdir(cur):
        missing.append(cur)
        parent = os.path.dirname(cur)
        if parent == cur:
            break
        cur = parent
    os.makedirs(folder, exist_ok=True)
    roots = [os.path.normcase(os.path.abspath(r)) for r in (ctx.home, ctx.project)]
    for d in missing:
        nd = os.path.normcase(d)
        if any(nd.startswith(r.rstrip("\\/") + os.sep) for r in roots) and not nd.startswith(
                os.path.normcase(ctx.ub_home)):
            updates.setdefault("created_dirs", []).append(posix(d))


def run_logged(ctx, argv, env_extra=None, agent=None, cwd=None, timeout=300):
    env = ctx.child_env(env_extra, agent)
    rc, o, e = run_cmd(ctx, argv, timeout=timeout, env=env, cwd=cwd, log=True)
    return rc, o, e


def do_native(ctx, row, updates, result):
    agent = row.get("_native_agent", row["agent"])
    ok = True
    for argv in row["commands"]:
        rc, o, e = run_logged(ctx, argv, row.get("_env_extra"), agent, row.get("_cwd"))
        result["commands"].append({"argv": argv, "exit": rc})
        if rc != 0 and not RE_ALREADY.search(o + "\n" + e):
            ok = False
            result["detail"] = (e or o).strip()[-300:]
            break
    if not ok and row.get("_fallback"):
        ok = True
        for argv in row["_fallback"]:
            rc, o, e = run_logged(ctx, argv, row.get("_env_extra"), agent, row.get("_cwd"))
            result["commands"].append({"argv": argv, "exit": rc})
            if rc != 0 and not RE_ALREADY.search(o + "\n" + e) and not RE_ABSENT.search(o + "\n" + e):
                ok = False
                result["detail"] = (e or o).strip()[-300:]
                break
        if ok:
            result["detail"] = "upgraded by remove + add"
    if not ok and row.get("_allow_fail"):
        result["detail"] = "refresh failed (ignored: the local marketplace loads in place) [U-16]"
        ok = True
    if ok:
        e = {"agent": agent, "route": "native", "marketplace": MARKETPLACE, "plugin": PLUGIN_ID,
             "scope": "local" if (agent == "claude-code" and ctx.scope == "project") else "user"}
        if agent == "claude-code":
            e["config_dir"] = posix(ctx.homes["claude-code"])
            if e["scope"] == "local":
                e["project"] = posix(ctx.project)  # uninstall runs `--scope local` from this folder
        else:
            e["codex_home"] = posix(row.get("_codex_home") or ctx.homes["codex"])
            if row.get("_codex_home"):
                e["profile"] = True
        updates["entries"].append(e)
    return ok


def find_marketplace_name(obj, source_match):
    def pred(node):
        if not isinstance(node, dict) or not isinstance(node.get("name"), str):
            return False
        blob = json.dumps(node, ensure_ascii=True)
        return source_match.lower() in blob.lower()
    node = json_find(obj, pred)
    return node["name"] if node else None


def do_component(ctx, row, updates, result):
    agent = row["agent"] if row["agent"] in AGENTS else None
    cmds = row["commands"]
    resolve = row.get("_resolve")
    steps = cmds[:-1] if resolve else cmds
    for argv in steps:
        rc, o, e = run_logged(ctx, argv, row.get("_env_extra"), agent, row.get("_cwd"), timeout=900)
        result["commands"].append({"argv": argv, "exit": rc})
        if rc != 0 and not RE_ALREADY.search(o + "\n" + e):
            result["detail"] = (e or o).strip()[-300:]
            return False
    if resolve:  # [U-18]
        rc, o, e = run_logged(ctx, ["claude", "plugin", "marketplace", "list", "--json"], None, agent, None, 60)
        result["commands"].append({"argv": ["claude", "plugin", "marketplace", "list", "--json"], "exit": rc})
        name = None
        if rc == 0:
            try:
                name = find_marketplace_name(textio.extract_json(o), resolve["source_match"])
            except ValueError:
                name = None
        if not name:
            result["status"] = "manual"
            result["detail"] = "could not read the marketplace name; do it by hand: %s" % row.get("_manual_text")
            return True
        argv = ["claude", "plugin", "install", "%s@%s" % (resolve["plugin"], name), "--scope", "user"]
        rc, o, e = run_logged(ctx, argv, None, agent, None)
        result["commands"].append({"argv": argv, "exit": rc})
        if rc != 0 and not RE_ALREADY.search(o + "\n" + e):
            result["detail"] = (e or o).strip()[-300:]
            return False
    updates["components"].append({"id": row["_cid"], "agent": row["agent"],
                                  "route": row["how"] if row["how"] != "native" else "native",
                                  "ref": row.get("_ref")})
    return True


def do_launchers(ctx, row, updates):
    for path, data in sorted(row["_files"].items()):
        if read_bytes(path) == data:
            continue
        write_bytes_atomic(path, data)
        if not path.endswith((".cmd", ".ps1")) and not IS_WINDOWS:
            os.chmod(path, 0o755)
    updates["launchers"].extend(posix(p) for p in row["_files"])
    ctx.log("launchers %s" % ", ".join(sorted(os.path.basename(p) for p in row["_files"])))
    return ""


def do_routing(ctx, row, updates):
    path = row["_file"]
    text, bom, err, real = read_instruction(path)
    if err:
        raise InstallError(err)
    raw = read_bytes(real)
    created = raw is None
    backup = backup_file(ctx, row["agent"], real) if raw is not None else None
    nl = "\r\n" if "\r\n" in text else "\n"
    block = ROUTING_BLOCK.replace("\n", nl)
    span = routing_span(text)
    sep = ""
    if span:
        new = text[:span[0]] + block + text[span[1]:]
        prev = [b for b in (ctx.manifest or {}).get("routing_blocks", []) if isinstance(b, dict)
                and os.path.normcase(b.get("path", "")) == os.path.normcase(posix(path))]
        if prev:
            sep = prev[0].get("sep", "")
            created = bool(prev[0].get("created"))
            backup = prev[0].get("backup") or backup  # keep the backup of the file as it was before the kit
    else:
        if text:
            sep = ("" if text.endswith("\n") else nl) + nl
        new = text + sep + block + nl
    data = new.encode("utf-8")
    write_bytes_atomic(real, (codecs.BOM_UTF8 + data) if bom else data)
    rec = {"path": posix(path), "sep": sep, "created": created}
    if backup:
        rec["backup"] = backup
    updates["routing_blocks"].append(rec)
    ctx.log("routing block -> %s" % posix(path))
    return ""


def remove_routing(ctx, path, record):
    text, bom, err, real = read_instruction(path)
    if err:
        raise InstallError(err)
    if not os.path.isfile(real):
        return False
    span = routing_span(text)
    if not span:
        return False
    start, end = span
    if text[end:end + 2] == "\r\n":
        end += 2
    elif text[end:end + 1] == "\n":
        end += 1
    sep = (record or {}).get("sep")
    if sep and text[max(0, start - len(sep)):start] == sep:
        start -= len(sep)
    elif sep is None:
        for cand in ("\r\n", "\n"):
            if text[max(0, start - len(cand)):start] == cand and text[max(0, start - 2 * len(cand)):start - len(cand)] \
                    in ("\n", "\r\n"):
                start -= len(cand)
                break
    new = text[:start] + text[end:]
    backup_file(ctx, "routing", real)
    if not new and (record or {}).get("created"):
        os.unlink(real)
    else:
        data = new.encode("utf-8")
        write_bytes_atomic(real, (codecs.BOM_UTF8 + data) if bom else data)
    return True


def do_login(ctx, row, result):
    argv = row["commands"][0]
    exe = proc.resolve_exe(argv[0], ctx.env)
    if not exe:
        result["detail"] = "%s not found" % argv[0]
        return False
    proc.check_cmd_args(exe, argv[1:])
    sys.stderr.write("Running %s in the foreground; complete the sign-in, then come back.\n" % " ".join(argv))
    rc = subprocess.call([exe] + argv[1:])
    result["commands"].append({"argv": argv, "exit": rc})
    ctx.log("exit=%s %s" % (rc, " ".join(argv)))
    return rc == 0


def do_codexhome(ctx, row):
    write_bytes_atomic(row["_file"], row["_data"])
    ctx.log("codex home -> %s" % posix(row["_file"]))
    return ""


def do_families(ctx, row):
    path = os.path.join(ctx.ub_home, "families.json")
    cur = load_json_file(path, None)
    if cur is None and not os.path.exists(path):
        cur = {}
    if not isinstance(cur, dict):
        raise InstallError("%s is not valid JSON; fix or delete it first" % posix(path))
    backup_file(ctx, "all", path)
    prov = row["_provider"]
    node = cur.setdefault("providers", {}).setdefault(prov, {}).setdefault("base_url", {})
    if row["_value"] is None:
        node.pop("global", None)
        if not node:
            cur["providers"][prov].pop("base_url", None)
        if not cur["providers"][prov]:
            cur["providers"].pop(prov, None)
        if not cur["providers"]:
            cur.pop("providers", None)
    else:
        node["global"] = row["_value"]
    write_bytes_atomic(path, (json.dumps(cur, indent=1, ensure_ascii=True) + "\n").encode("ascii"))
    ctx.log("families.json providers.%s.base_url.global = %s" % (prov, row["_value"]))
    return ""


def apply_rows(ctx, rows, updates, status_of=None):
    results = []
    failed = False
    status_of = {} if status_of is None else status_of  # id(row) -> result status, for _requires
    for row in rows:
        res = {"n": row["n"], "item": row["item"], "status": "ok", "detail": "", "commands": []}
        results.append(res)
        status_of[id(row)] = res
        if row["action"] in NOOP_ACTIONS:
            res["status"] = row["action"] if row["action"] != "unchanged" else "unchanged"
            continue
        req = row.get("_requires")
        if req is not None:
            got = (status_of.get(id(req)) or {}).get("status")
            if got not in ("ok", "unchanged"):
                res["status"] = "skipped"
                res["detail"] = "kept: row %s (%s) did not succeed" % (req.get("n"), req.get("item"))
                continue
        if row.get("_verify_native"):
            va = row["_verify_native"]
            ctx.cache.pop(("plugins", va, None), None)
            if not native_installed(ctx, va):
                res["status"] = "skipped"
                res["detail"] = "kept: the plugin is not listed after the install, so this copy is still needed"
                continue
        kind = row.get("_kind")
        try:
            if kind == "stage":
                res["detail"] = do_stage(ctx, row)
            elif kind == "copy":
                d = do_copy(ctx, row, updates)
                if d == "skip-not-owned":
                    res["status"] = "skip-not-owned"
                else:
                    res["detail"] = d
            elif kind == "remove":
                res["detail"] = do_remove(ctx, row, updates)
            elif kind == "native":
                if not do_native(ctx, row, updates, res):
                    res["status"] = "failed"
            elif kind == "component":
                if not do_component(ctx, row, updates, res):
                    res["status"] = "failed"
            elif kind == "cli":
                rc, o, e = run_logged(ctx, row["commands"][0], None, None, None, timeout=900)
                res["commands"].append({"argv": row["commands"][0], "exit": rc})
                if rc != 0:
                    res["status"] = "failed"
                    res["detail"] = (e or o).strip()[-300:] + "  (never use sudo: fix npm's global prefix instead)"
            elif kind == "login":
                if not do_login(ctx, row, res):
                    res["status"] = "failed"
            elif kind == "launchers":
                res["detail"] = do_launchers(ctx, row, updates)
            elif kind == "routing":
                res["detail"] = do_routing(ctx, row, updates)
            elif kind == "gitinit":
                rc, o, e = run_logged(ctx, ["git", "init"], None, None, row["_cwd_dir"] if "_cwd_dir" in row
                                      else ctx.project, 60)
                res["commands"].append({"argv": ["git", "init"], "exit": rc})
                if rc != 0:
                    res["status"] = "failed"
            elif kind == "codexhome":
                res["detail"] = do_codexhome(ctx, row)
            elif kind == "families":
                res["detail"] = do_families(ctx, row)
            elif kind in ("uninstall-native",):
                if not do_uninstall_native(ctx, row, updates, res):
                    res["status"] = "failed"
            elif kind == "uninstall-copy":
                res["detail"] = do_remove(ctx, row, updates)
            elif kind == "uninstall-routing":
                remove_routing(ctx, row["_file"], row.get("_record"))
                updates["remove_routing"].append(posix(row["_file"]))
                if (row.get("_record") or {}).get("backup"):
                    res["detail"] = "the file as it was before the kit: %s" % row["_record"]["backup"]
            elif kind == "uninstall-files":
                for p in row["_files"]:
                    if os.path.lexists(p):
                        os.unlink(p)
                updates["remove_launchers"].extend(posix(p) for p in row["_files"])
            elif kind == "uninstall-tree":
                rmtree(row["_dest"])
            elif kind == "purge":
                do_purge(ctx, row.get("_names") or [])
            elif kind == "noop":
                res["status"] = row["action"]
        except InstallError as exc:
            res["status"] = "failed"
            res["detail"] = str(exc)
        except OSError as exc:
            res["status"] = "failed"
            res["detail"] = "%s: %s" % (type(exc).__name__, exc)
        if res["status"] == "failed":
            failed = True
            ctx.log("FAILED row %s %s: %s" % (row["n"], row["item"], res["detail"]))
            if kind == "stage":
                for r in rows[rows.index(row) + 1:]:
                    results.append({"n": r["n"], "item": r["item"], "status": "skipped",
                                    "detail": "not attempted: staging the kit failed", "commands": []})
                break
    return results, failed


def new_updates():
    return {"entries": [], "components": [], "launchers": [], "routing_blocks": [], "remove_paths": [],
            "remove_entries": [], "remove_routing": [], "remove_launchers": [], "created_dirs": []}


def _same(a, b):
    return bool(a) and bool(b) and os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


def entry_key(e):
    loc = e.get("path") or e.get("codex_home") or e.get("config_dir") or ""
    extra = ""
    if e.get("route") == "native":  # a user-scope and a local-scope (per project) Claude plugin are separate entries
        proj = e.get("project")
        extra = "%s|%s" % (e.get("scope") or "user", os.path.normcase(os.path.abspath(proj)) if proj else "")
    return (e.get("agent"), e.get("route"), os.path.normcase(os.path.abspath(loc)) if loc else "", extra)


def write_manifest(ctx, updates, drop_all=False):
    if drop_all:
        if os.path.exists(ctx.manifest_path):
            os.unlink(ctx.manifest_path)
        return
    m = ctx.manifest or {}
    m = {"schema": 1, "kit": SKILL, "version": kit_version(ctx.source), "commit": m.get("commit", "local"),
         "installed_at": m.get("installed_at"), "entries": list(m.get("entries", [])),
         "components": list(m.get("components", [])), "launchers": list(m.get("launchers", [])),
         "routing_blocks": list(m.get("routing_blocks", [])), "source": m.get("source"),
         "created_dirs": list(m.get("created_dirs", []))}
    m["commit"] = source_commit(ctx)
    m["installed_at"] = now_iso()
    if _same(ctx.source, ctx.kit_dir):
        pass  # the staged kit re-applied itself: the staged content (and its origin) did not change
    elif ctx.source_is_temp or under_temp(ctx.source):
        m["source"] = None  # a bootstrap or release download: `update` must not re-stage an older clone
    else:
        m["source"] = posix(ctx.source)
    for d in updates.get("created_dirs", []):
        if not any(_same(d, x) for x in m["created_dirs"]):
            m["created_dirs"].append(d)
    if not m["created_dirs"]:
        m.pop("created_dirs", None)
    for e in updates["entries"]:
        k = entry_key(e)
        m["entries"] = [x for x in m["entries"] if entry_key(x) != k] + [e]
    for p in updates["remove_paths"]:
        m["entries"] = [x for x in m["entries"] if not (x.get("route") == "copy" and _same(x.get("path"), p))]
    for k in updates["remove_entries"]:
        m["entries"] = [x for x in m["entries"] if entry_key(x) != k]
    for c in updates["components"]:
        m["components"] = [x for x in m["components"] if not (x.get("id") == c["id"] and x.get("agent") == c["agent"])]
        m["components"].append(c)
    for p in updates["launchers"]:
        if p not in m["launchers"]:
            m["launchers"].append(p)
    m["launchers"] = [p for p in m["launchers"] if p not in updates["remove_launchers"]]
    for b in updates["routing_blocks"]:
        m["routing_blocks"] = [x for x in m["routing_blocks"]
                               if not (isinstance(x, dict) and _same(x.get("path"), b["path"]))] + [b]
    m["routing_blocks"] = [x for x in m["routing_blocks"]
                           if not (isinstance(x, dict) and any(_same(x.get("path"), p) for p in updates["remove_routing"]))]
    if m.get("source") is None:
        m.pop("source", None)
    textio.write_json_atomic(ctx.manifest_path, m)
    ctx.manifest = m


def ensure_home_dirs(ctx):
    for d in (ctx.ub_home, ctx.bin_dir):
        os.makedirs(d, exist_ok=True)
    tmp = os.path.join(ctx.ub_home, "tmp")
    if not os.path.isdir(tmp):
        os.makedirs(tmp, exist_ok=True)
        if not IS_WINDOWS:
            os.chmod(tmp, 0o700)


def confirm_and_apply(ctx, plan, title, rebuild=None, finish=None):
    """Shared flow for install/update/uninstall/setup-*: confirmation rules of 10.4 item 9, then apply."""
    args = ctx.args
    rows = plan["rows"]
    todo = actionable(rows)
    blocked = [r for r in rows if r["action"] == "blocked"]
    as_json = getattr(args, "json", False)
    if not todo:
        plan["applied"] = False
        plan["result"] = "blocked rows present; nothing was applied" if blocked else "nothing to do"
        plan["results"] = [{"n": r["n"], "item": r["item"], "commands": [], "detail": "",
                            "status": "skip-not-owned" if r["action"] == "migrate-v1" else r["action"]} for r in rows]
        code = 4 if (blocked and getattr(args, "yes", False)) else 0
        plan["exit"] = code
        if as_json:
            emit_json(public_plan(plan))
        else:
            out(ctx, plan_text(public_plan(plan), title))
            out(ctx, "\nBlocked rows are present (see Warnings); nothing was applied." if blocked
                else "\nNothing to do.")
        return code
    if getattr(args, "yes", False):
        if blocked:
            plan["applied"] = False
            plan["result"] = "blocked rows present; nothing was applied"
            if as_json:
                emit_json(public_plan(plan))
            else:
                out(ctx, plan_text(public_plan(plan), title))
                out(ctx, "\nBlocked rows are present (see Warnings); nothing was applied.")
            return 4
    else:
        if not is_tty():
            plan["applied"] = False
            plan["result"] = "no TTY: re-run with --yes to apply"
            if as_json:
                emit_json(public_plan(plan))
            else:
                out(ctx, plan_text(public_plan(plan), title))
                out(ctx, "\nNothing was applied: re-run with --yes to apply this plan.")
            return 0
        sys.stderr.write(plan_text(public_plan(plan), title) + "\n\n")
        for r in rows:
            if r["action"] == "migrate-v1" and not r.get("_migrate"):
                if ask("Back up and replace the v1 copy at %s?" % r["path"]):
                    r["_migrate"] = True
        todo = actionable(rows)
        if not ask("Apply %d change(s)?" % len(todo)):
            plan["applied"] = False
            plan["result"] = "cancelled"
            if as_json:
                emit_json(public_plan(plan))
            else:
                out(ctx, "Cancelled; nothing was applied.")
            return 5
    if not ctx.root_ok():
        raise InstallError("refusing to run as root or administrator; set UB_ALLOW_ROOT=1 to allow it (never use "
                           "sudo or an elevated shell)")
    updates = new_updates()
    ensure_home_dirs(ctx)
    first = [r for r in rows if r.get("_kind") in ("cli", "login")]
    rest = [r for r in rows if r.get("_kind") not in ("cli", "login")]
    status_of = {}
    results, failed = apply_rows(ctx, first, updates, status_of)
    if rebuild and any(res["status"] == "ok" and r.get("_kind") == "cli" for res, r in zip(results, first)):
        ctx.cache = {}
        newplan = rebuild()
        start = len(rows)
        rest = [r for r in newplan["rows"]]
        for i, r in enumerate(rest, start + 1):
            r["n"] = i
        plan["replan"] = rest
        plan["warnings"].extend(w for w in newplan["warnings"] if w not in plan["warnings"])
    r2, f2 = apply_rows(ctx, rest, updates, status_of)
    results.extend(r2)
    failed = failed or f2
    # the Next lines must not tell the user to start an agent whose install failed
    all_rows = first + rest
    for row, res in zip(all_rows, results):
        a = row.get("agent")
        if res.get("status") == "failed" and a in DISPLAY:
            plan["next"] = [ln for ln in plan.get("next", []) if not ln.startswith("Start %s " % DISPLAY[a])]
            note = "%s: not installed (row %s failed)" % (DISPLAY[a], row.get("n"))
            if note not in plan["next"]:
                plan["next"].insert(0, note)
    if finish:
        finish(updates)
    else:
        write_manifest(ctx, updates)
    ctx.flush_log()
    plan["applied"] = True
    plan["results"] = results
    code = 1 if failed else 0
    plan["exit"] = code
    if as_json:
        emit_json(public_plan(plan))
    else:
        out(ctx, plan_text(public_plan(plan), title))
        out(ctx, "")
        out(ctx, "Results:")
        for res in results:
            line = "  %-3s %-44s %s" % (res["n"], res["item"][:44], res["status"])
            if res.get("detail"):
                line += "  " + res["detail"].replace("\n", " ")[:200]
            out(ctx, line)
        out(ctx, "\nDone." if not failed else "\nSome rows failed (see above and %s)." % posix(ctx.log_path))
    return code


# --------------------------------------------------------------------------------------------------------------------
# commands


def no_agent_hint(ctx, plan):
    clis = ctx.components["clis"]
    hints = ["No supported agent was detected and none was named. Install one, then re-run:",
             "Claude Code: npm install -g %s   then %s" % (clis["claude"]["npm"], clis["claude"]["login_hint"]),
             "Codex:       npm install -g %s   then codex login" % clis["codex"]["npm"],
             "Kimi Code:   npm install -g %s   (Windows: install Git for Windows first)  then kimi login"
             % clis["kimi"]["npm"],
             "Or let the installer do it: install.py install --with-clis claude,codex,kimi --login",
             "Or pre-install for a named agent: install.py install --agents kimi"]
    plan["next"] = hints + plan["next"]
    return plan


def cmd_plan(ctx, mode="plan"):
    plan = build_plan(ctx, mode)
    if plan.get("no_agents"):
        no_agent_hint(ctx, plan)
        if getattr(ctx.args, "json", False):
            emit_json(public_plan(plan))
        else:
            out(ctx, plan_text(public_plan(plan), "plan (nothing has been written)"))
        return 3
    if getattr(ctx.args, "json", False):
        emit_json(public_plan(plan))
    else:
        out(ctx, plan_text(public_plan(plan), "plan (nothing has been written)"))
        if actionable(plan["rows"]):
            if under_temp(ctx.source):
                # Bootstrap run (curl | sh or irm): this install.py sits in a temp folder that is deleted on exit.
                out(ctx, "\nApply it: run the same one-line command again with `install` in place of `plan`"
                         "   (asks once; add --yes to skip the question)")
            else:
                out(ctx, "\nApply it with: install.py install   (asks once; add --yes to skip the question)")
        else:
            out(ctx, "\nNothing to do: everything is up to date.")
    return 0


def cmd_install(ctx, mode):
    plan = build_plan(ctx, mode)
    if plan.get("no_agents"):
        no_agent_hint(ctx, plan)
        if getattr(ctx.args, "json", False):
            emit_json(public_plan(plan))
        else:
            out(ctx, plan_text(public_plan(plan), mode))
        return 3
    return confirm_and_apply(ctx, plan, mode, rebuild=lambda: build_plan(ctx, mode, skip_clis=True))


# uninstall ----------------------------------------------------------------------------------------------------------


def do_uninstall_native(ctx, row, updates, result):
    agent = row["_native_agent"]
    ok = True
    for argv in row["commands"]:
        rc, o, e = run_logged(ctx, argv, row.get("_env_extra"), agent, row.get("_cwd"))
        result["commands"].append({"argv": argv, "exit": rc})
        if rc != 0 and not RE_ABSENT.search(o + "\n" + e):
            ok = False
            result["detail"] = (e or o).strip()[-300:]
    if ok and row.get("_entry") is not None:
        updates["remove_entries"].append(entry_key(row["_entry"]))
    return ok


def build_uninstall_plan(ctx):
    system = detect_system(ctx)
    agents = detect_agents(ctx)
    for a in AGENTS:
        agents[a]["route"] = "skip"
        agents[a]["reason"] = ""
    warnings, manual, nxt = [], [], []
    rows = []
    m = ctx.manifest or {}
    entries = list(m.get("entries", []))
    force = getattr(ctx.args, "force", False)
    # native plugins
    seen_native = set()
    natives = [e for e in entries if e.get("route") == "native" and e.get("agent") in ("claude-code", "codex")]

    def home_key(e):
        return (e.get("agent"), os.path.normcase(e.get("codex_home") or e.get("config_dir") or "")
                if e.get("profile") or e.get("agent") == "claude-code" else "")

    for i, e in enumerate(natives):
        agent = e.get("agent")
        codex_home = e.get("codex_home") if (agent == "codex" and e.get("profile")) else None
        seen_native.add((agent, codex_home))
        # the marketplace goes with the last plugin entry of this agent and home
        last = not any(home_key(x) == home_key(e) for x in natives[i + 1:])
        row = uninstall_native_row(ctx, agent, e, last_for_marketplace=last)
        if not agents[agent]["bin"]:
            rows.append(new_row(agent, row["item"], "manual", "print", None, [], _kind="noop"))
            manual.append("%s: %s not found; remove the plugin by hand: %s"
                          % (DISPLAY[agent], agent, " ; ".join(" ".join(c) for c in row["commands"])))
            continue
        rows.append(row)
    for agent in ("claude-code", "codex"):
        if (agent, None) in seen_native or not agents[agent]["bin"]:
            continue
        listed = plugin_list(ctx, agent)
        if listed is not None and plugin_listed(listed, SKILL, MARKETPLACE):
            if force:
                rows.append(uninstall_native_row(ctx, agent, {"agent": agent, "scope": "user"}))
                rows[-1]["_entry"] = None
            else:
                warnings.append("%s: the plugin %s was installed outside this installer: kept; use --force to "
                                "remove it" % (DISPLAY[agent], PLUGIN_ID))
                rows.append(new_row(agent, "plugin %s (not installed by the kit)" % SKILL, "skip-not-owned", "native",
                                    None, [], _kind="noop"))
    # copies
    seen_paths = []
    candidates = [(e.get("agent"), e.get("path"), e) for e in entries if e.get("route") == "copy" and e.get("path")]
    for a in AGENTS:
        candidates.append((a, copy_dest(ctx, a), None))
    candidates.append(("codex", os.path.join(ctx.agents_skills, SKILL), None))
    for agent, path, entry in candidates:
        path = os.path.abspath(path)
        if any(_same(path, p) for p in seen_paths):
            continue
        seen_paths.append(path)
        if not os.path.isdir(path):
            if entry is not None:
                ctx.cache.setdefault("gone", []).append(path)
            continue
        if not os.path.isfile(os.path.join(path, MARKER)):
            continue
        entry = entry or manifest_entry(ctx, "copy", path)
        cur = hash_files(walk_files(path, top_exclude=False))
        recorded = (entry or {}).get("files")
        if (entry or {}).get("replaced_backup"):
            manual.append("%s replaced a folder you had there; restore it by hand if you want it back: copy %s to %s"
                          % (posix(path), entry["replaced_backup"], posix(path)))
        if isinstance(recorded, dict) and recorded == cur:
            rows.append(new_row(agent, "skill %s" % SKILL, "remove", "copy", path, [], _kind="uninstall-copy",
                                dest=path, backup=None))
        elif force:
            edited = sorted(r for r, h in cur.items() if not isinstance(recorded, dict) or recorded.get(r) != h)
            rows.append(new_row(agent, "skill %s" % SKILL, "remove", "copy", path, [], _kind="uninstall-copy",
                                dest=path, backup=edited or "all"))
        else:
            warnings.append("%s was edited after install (or is not in the manifest): kept; use --force to back it "
                            "up and remove it" % posix(path))
            rows.append(new_row(agent, "skill %s (edited)" % SKILL, "skip-not-owned", "copy", path, [], _kind="noop"))
    # routing blocks
    records = {os.path.normcase(os.path.abspath(b["path"])): b for b in m.get("routing_blocks", [])
               if isinstance(b, dict) and b.get("path")}
    files = set(records.keys())
    names = {"claude-code": "CLAUDE.md", "codex": "AGENTS.md", "kimi": "AGENTS.md", "zcode": "AGENTS.md"}
    for a in AGENTS:
        files.add(os.path.normcase(os.path.join(ctx.homes[a], names[a])))
    for f in sorted(files):
        raw = read_bytes(os.path.realpath(f) if os.path.islink(f) else f)
        if raw is None or routing_span(raw.decode("utf-8", "replace")) is None:
            continue
        text, _bom, err, _real = read_instruction(f)
        if err:
            warnings.append("%s holds the routing block but %s; remove the block by hand" % (posix(f), err))
            rows.append(new_row("all", "routing block", "manual", "print", f, [], _kind="noop"))
            continue
        rows.append(new_row("all", "routing block", "remove", "copy", f, [], _kind="uninstall-routing", file=f,
                            record=records.get(f)))
    # launchers
    lfiles = [p for p in m.get("launchers", []) if os.path.lexists(p)]
    for name in ("ub", "claude-glm", "claude-kimi", "codex-glm", "codex-kimi"):
        for suffix in ("", ".cmd", ".ps1"):
            p = posix(os.path.join(ctx.bin_dir, name + suffix))
            if os.path.lexists(p) and p not in lfiles:
                lfiles.append(p)
    if lfiles:
        rows.append(new_row("all", "launchers", "remove", "copy", ctx.bin_dir, [], _kind="uninstall-files",
                            files=lfiles))
    if os.path.isdir(ctx.kit_dir):
        rows.append(new_row("all", "staged kit", "remove", "copy", ctx.kit_dir, [], _kind="uninstall-tree",
                            dest=ctx.kit_dir))
    if getattr(ctx.args, "purge", False) and os.path.isdir(ctx.ub_home):
        refuse = None
        ub = os.path.normcase(os.path.abspath(ctx.ub_home))
        if ub == os.path.normcase(os.path.abspath(ctx.home)) or os.path.dirname(ub) == ub:
            refuse = "UB_HOME %s is your home folder or a drive root: not purging" % posix(ctx.ub_home)
        elif not (os.path.isfile(ctx.manifest_path) or os.path.isdir(ctx.kit_dir)):
            refuse = ("UB_HOME %s holds no kit install (no install-manifest.json and no kit/): not purging; check "
                      "UB_HOME" % posix(ctx.ub_home))
        if refuse:
            warnings.append(refuse)
            rows.append(new_row("all", "purge UB_HOME", "blocked", "copy", ctx.ub_home, [], _kind="noop",
                                reason=refuse))
        else:
            names, kept = [], []
            for n in sorted(os.listdir(ctx.ub_home)):
                if n == "backups":
                    continue
                (names if (n in PURGE_NAMES or PURGE_RE.match(n)) else kept).append(n)
            for n in kept:
                warnings.append("UB_HOME/%s was not created by the kit: kept by --purge" % n)
            rows.append(new_row("all", "purge UB_HOME (keeps backups/)", "remove", "copy", ctx.ub_home, [],
                                _kind="purge", names=names))
    manual.append("Kimi Code: if you installed the kit as a Kimi plugin, run /plugins remove ultimate-brainstorm")
    manual.append("ZCode: if you added the kit under Settings > Plugins, remove it there")
    nxt.append("Run folders (brainstorm/) and %s are kept." % posix(ctx.backup_root))
    nxt.append("Components (Compound Engineering, mattpocock skills) stay installed; remove them with their own tools.")
    plan = assemble_plan(ctx, system, agents, rows, warnings, manual, nxt)
    return plan


def do_purge(ctx, names):
    """Delete only the listed UB_HOME entries (names the kit creates, chosen at plan time); backups/ stays."""
    ctx.purged = True  # nothing (not even install.log) is written into UB_HOME afterwards
    for name in names:
        if name == "backups" or not (name in PURGE_NAMES or PURGE_RE.match(name)):
            continue
        p = os.path.join(ctx.ub_home, name)
        if not os.path.lexists(p):
            continue
        if os.path.isdir(p) and not os.path.islink(p):
            rmtree(p)
        else:
            try:
                os.unlink(p)
            except OSError:
                pass


def cmd_uninstall(ctx):
    plan = build_uninstall_plan(ctx)

    created = list((ctx.manifest or {}).get("created_dirs", []))

    def tidy():
        """Remove the empty folders the installer created (deepest first), and UB_HOME/bin and tmp when empty."""
        for d in sorted(created + [posix(ctx.bin_dir), posix(ctx.tmp_dir)], key=len, reverse=True):
            try:
                if os.path.isdir(d) and not os.listdir(d):
                    os.rmdir(d)
            except OSError:
                pass

    def finish(updates):
        if getattr(ctx.args, "purge", False) or not ctx.manifest:
            tidy()
            return
        write_manifest(ctx, updates)
        m = ctx.manifest
        m["entries"] = [e for e in m.get("entries", [])
                        if e.get("route") != "copy" or os.path.isdir(e.get("path") or "")]
        m["launchers"] = [p for p in m.get("launchers", []) if os.path.lexists(p)]
        m["routing_blocks"] = [b for b in m.get("routing_blocks", []) if isinstance(b, dict) and
                               routing_span((read_bytes(b.get("path", "")) or b"").decode("utf-8", "replace"))]
        if not m["entries"] and not m["launchers"] and not m["routing_blocks"]:
            write_manifest(ctx, updates, drop_all=True)
        else:
            textio.write_json_atomic(ctx.manifest_path, m)
        tidy()

    return confirm_and_apply(ctx, plan, "uninstall", finish=finish)


# setup-glm / setup-kimi -------------------------------------------------------------------------------------------


def providers_config(ctx):
    path = os.path.join(ctx.source, "skills", SKILL, "scripts", "families.default.json")
    data = load_json_file(path)
    if isinstance(data, dict) and isinstance(data.get("providers"), dict):
        return data["providers"]
    return FALLBACK_PROVIDERS


def codex_home_content(ctx, provider, region):
    """config.toml text for UB_HOME/codex-homes/<provider> (4.16): launch.py's renderer, else the built-in text."""
    spec = CODEX_HOMES[provider]
    base = spec["base_url"].get(region) or spec["base_url"]["global"]
    mod = launch_module(ctx)
    if mod is not None and hasattr(mod, "render_codex_home"):
        try:
            return mod.render_codex_home(provider, region).replace("\r\n", "\n").encode("utf-8")
        except Exception:  # noqa: BLE001
            pass
    lines = ["# ultimate-brainstorm Codex home for %s (written by install.py setup; holds no secrets:" % provider,
             "# Codex reads the key from %s)." % spec["env_key"],
             'model = "%s"' % spec["model"],
             'model_provider = "%s"' % spec["provider_id"]]
    lines += spec["extra"]
    lines += ["", "[model_providers.%s]" % spec["provider_id"], 'name = "%s"' % spec["name"],
              'base_url = "%s"' % base, 'env_key = "%s"' % spec["env_key"], 'wire_api = "responses"', ""]
    return "\n".join(lines).encode("utf-8")


def key_howto(var):
    return ['PowerShell: [Environment]::SetEnvironmentVariable("%s","<key>","User")' % var,
            "bash:       export %s=<key> in your profile" % var]


def cmd_setup(ctx, which):
    args = ctx.args
    region = getattr(args, "region", None) or "global"
    if which == "glm":
        provider = "glm"
    else:
        provider = getattr(args, "provider", None) or "kimi"
        if provider not in ("kimi", "kimi-code"):
            raise InstallError("--provider must be kimi or kimi-code", 2)
        if provider == "kimi" and region == "cn":
            # [U-22] the Moonshot China Anthropic endpoint is not vendor-documented: not offered.
            raise InstallError("--region cn is available only with --provider kimi-code (the Moonshot Platform China "
                               "endpoint is not documented for Claude Code)", 2)
    providers = providers_config(ctx)
    pspec = providers.get(provider) or FALLBACK_PROVIDERS[provider]
    token_env = pspec.get("token_env")
    system = detect_system(ctx)
    agents = detect_agents(ctx)
    for a in AGENTS:
        agents[a]["route"] = "skip"
        agents[a]["reason"] = ""
    warnings, manual, nxt = [], [], []
    rows = [stage_row(ctx, warnings)]
    if not ctx.env.get(token_env):
        warnings.append("%s is not set (only its name is checked). Set it for your shell:" % token_env)
        warnings.extend(key_howto(token_env))
    # region override in UB_HOME/families.json (read by launch.py and the adapter)
    fam_path = os.path.join(ctx.ub_home, "families.json")
    cur = load_json_file(fam_path, None)
    if cur is None and os.path.exists(fam_path):
        raise InstallError("%s is not valid JSON; fix or delete it first" % posix(fam_path))
    cur = cur or {}
    cur_global = (((cur.get("providers") or {}).get(provider) or {}).get("base_url") or {}).get("global") \
        if isinstance(cur, dict) else None
    cn_url = (pspec.get("base_url") or {}).get("cn")
    if region == "cn":
        if not cn_url:
            raise InstallError("provider %s has no cn endpoint" % provider, 2)
        if cur_global != cn_url:
            rows.append(new_row("all", "region cn for %s (UB_HOME/families.json)" % provider,
                                "update" if os.path.exists(fam_path) else "create", "copy", fam_path, [],
                                _kind="families", provider=provider, value=cn_url))
    elif cur_global and cn_url and cur_global == cn_url:
        rows.append(new_row("all", "region global for %s (UB_HOME/families.json)" % provider, "update", "copy",
                            fam_path, [], _kind="families", provider=provider, value=None))
    rows.append(launcher_row_for(ctx, "ub", "ub", ["ub"], warnings))
    want_launcher = getattr(args, "launcher", False) or getattr(args, "zai_mcp", False)
    lname = "glm" if provider == "glm" else "kimi"
    if want_launcher:
        zai = bool(getattr(args, "zai_mcp", False))
        if zai and provider != "glm":
            raise InstallError("--zai-mcp is only for setup-glm", 2)
        # [U-19] with --zai-mcp, launch.py renders zai-mcp.json.tpl into a 0600 temp file at launch time
        largs = launch_args_for(ctx, "claude", provider, region=region, zai_mcp=zai)
        rows.append(launcher_row_for(ctx, "claude-" + lname, "claude-" + lname, largs, warnings))
    if getattr(args, "codex", False):
        if provider == "kimi-code":
            warnings.append("--codex needs the Moonshot Platform key: re-run setup-kimi --provider kimi --codex "
                            "(the kimi-code membership key has no Codex home)")
        else:
            home = os.path.join(ctx.ub_home, "codex-homes", lname)
            cfg = os.path.join(home, "config.toml")
            data = codex_home_content(ctx, lname, region)
            cur_b = read_bytes(cfg)
            action = "unchanged" if cur_b == data else ("create" if cur_b is None else "update")
            rows.append(new_row("codex", "codex home %s" % lname, action, "copy", cfg, [], _kind="codexhome",
                                file=cfg, data=data))
            rows.append(launcher_row_for(ctx, "codex-" + lname, "codex-" + lname,
                                         launch_args_for(ctx, "codex", provider), warnings))
            cx = agents["codex"]
            nmin = ctx.targets["agents"]["codex"]["native"]["min"]
            shared = os.path.join(ctx.agents_skills, SKILL)
            if os.path.isdir(shared):
                # Codex under that CODEX_HOME also scans ~/.agents/skills: a plugin there would be a second copy
                rows.append(new_row("codex", "plugin %s (CODEX_HOME=%s)" % (SKILL, posix(home)), "unchanged",
                                    "native", None, [], _kind="noop"))
                warnings.append("Codex on %s sees %s already; no plugin is added to %s (it would be a second copy)"
                                % (provider, posix(shared), posix(home)))
            elif cx["bin"] and version_ge(cx["version"], nmin) and not cmd_refusal(ctx, cx["bin"]):
                rows.append(native_row(ctx, "codex", "install", codex_home=home))
            else:
                native = ctx.targets["agents"]["codex"]["native"]
                rows.append(new_row("codex", "plugin %s (CODEX_HOME=%s)" % (SKILL, posix(home)), "manual", "print",
                                    None, [], _kind="noop"))
                manual.append("Codex %s+ is needed for the plugin in that home; then run with CODEX_HOME=%s: %s ; %s"
                              % (nmin, posix(home), " ".join(ctx.expand(a) for a in native["marketplace_add"]),
                                 " ".join(native["install"])))
    if provider == "glm":
        nxt.append(POLICY_GLM)
    else:
        nxt.append("For the Kimi Code CLI itself run: kimi login   (it ignores %s)" % token_env)
    if want_launcher:
        nxt.append("Start Claude Code on %s: %s   (PowerShell: & \"%s.cmd\")"
                   % (provider, posix(os.path.join(ctx.bin_dir, "claude-" + lname)),
                      posix(os.path.join(ctx.bin_dir, "claude-" + lname))))
    if getattr(args, "codex", False) and provider != "kimi-code":
        nxt.append("Start Codex on %s: %s   (PowerShell: & \"%s.cmd\")"
                   % (provider, posix(os.path.join(ctx.bin_dir, "codex-" + lname)),
                      posix(os.path.join(ctx.bin_dir, "codex-" + lname))))
        nxt.append("Confirm that Codex on %s answers: python \"%s\" doctor --live   [U-33]"
                   % (provider, posix(os.path.join(ctx.kit_dir, "install", "install.py"))))
    plan = assemble_plan(ctx, system, agents, rows, warnings, manual, nxt)
    return confirm_and_apply(ctx, plan, "setup-" + which)


# doctor -------------------------------------------------------------------------------------------------------------


def classify_url(url):
    u = (url or "").lower()
    if not u or "anthropic.com" in u:
        return "claude"
    if "z.ai" in u or "bigmodel.cn" in u:
        return "glm"
    if "moonshot" in u or "kimi.ai" in u or "kimi.com" in u:
        return "kimi"
    m = re.match(r"^[a-z]+://([^/:]+)", u)
    return "custom:%s" % (m.group(1) if m else u)


def codex_provider(ctx):
    path = os.path.join(ctx.homes["codex"], "config.toml")
    raw = read_bytes(path)
    if raw is None:
        return None, None
    text = raw.decode("utf-8", "replace")
    provider, base = None, None
    try:
        import tomllib  # Python 3.11+
        data = tomllib.loads(text)
        provider = data.get("model_provider")
        if provider:
            base = ((data.get("model_providers") or {}).get(provider) or {}).get("base_url")
    except Exception:  # noqa: BLE001 - fall back to a regex (3.1 item 1)
        top = text.split("\n[", 1)[0]
        m = re.search(r'^\s*model_provider\s*=\s*"([^"]+)"', top, re.M)
        provider = m.group(1) if m else None
        if provider:
            m = re.search(r'^\[model_providers\.%s\]\s*$(.*?)(^\[|\Z)' % re.escape(provider), text, re.M | re.S)
            if m:
                b = re.search(r'^\s*base_url\s*=\s*"([^"]+)"', m.group(1), re.M)
                base = b.group(1) if b else None
    return provider, base


def cmd_doctor(ctx):
    checks = []

    def add(cid, status, detail, fix=""):
        checks.append({"id": cid, "status": status, "detail": detail, "fix": fix if status != "PASS" else ""})

    system = detect_system(ctx)
    agents = detect_agents(ctx)
    pv = sys.version_info
    add("env.python", "PASS" if pv >= (3, 9) else "FAIL", system["python"], "install Python 3.9 or newer")
    add("env.git", "PASS" if system["git"] else "WARN", system["git"] or "git not found",
        "install git (Kimi Code and software runs use it)")
    node_v = parse_version(system["node"])
    if node_v is None:
        add("env.node", "WARN", "node not found", "install Node.js 22.20+ (needed for npx skills and the agent CLIs)")
    elif not version_ge(node_v, "22.20.0"):
        add("env.node", "WARN", "node %s is older than 22.20" % system["node"], "upgrade Node.js to 22.20+")
    else:
        add("env.node", "PASS", "node %s" % system["node"])
    if IS_WINDOWS:
        add("env.git_bash", "PASS" if system["git_bash"] else "WARN",
            system["git_bash"] or "Git Bash not found (KIMI_SHELL_PATH unset)",
            "install Git for Windows, or set KIMI_SHELL_PATH to bash.exe (Kimi Code needs it)")
    # staged kit
    kv = os.path.join(ctx.kit_dir, "VERSION")
    if os.path.isfile(kv):
        v = kit_version(ctx.kit_dir)
        add("kit.staged", "PASS" if v == kit_version(KIT_ROOT) else "WARN", "%s (version %s)" % (posix(ctx.kit_dir), v),
            "run: install.py update")
    else:
        add("kit.staged", "WARN", "%s is missing" % posix(ctx.kit_dir), "run: install.py install")
    # agents
    names = {"claude-code": None, "codex": None}
    for a in AGENTS:
        d = agents[a]
        t = ctx.targets["agents"][a]
        if a in ("claude-code", "codex") and d["bin"]:
            nmin = t["native"]["min"]
            ok = version_ge(d["version"], nmin)
            add("agent.%s.version" % a, "PASS" if ok else "WARN",
                "%s %s" % (t["detect"]["bin"], vtext(d["version"]) or "?"),
                "upgrade to %s+ for the native plugin route (the copy route works meanwhile)" % nmin)
            listed = plugin_list(ctx, a)
            names[a] = listed
        elif a == "kimi" and d["bin"]:
            add("agent.kimi.version", "PASS" if not d["legacy"] else "FAIL",
                "kimi %s" % (vtext(d["version"]) or "?"),
                "upgrade: npm install -g @moonshot-ai/kimi-code, then kimi migrate")
    # duplicates and skill presence
    for skill in STACK_SKILLS:
        for a in AGENTS:
            where = []
            for dpath in skill_dirs_for(ctx, a):
                p = os.path.join(dpath, skill)
                if os.path.isdir(p):
                    where.append(posix(p))
            if a in ("claude-code", "codex") and names.get(a) is not None:
                if skill == SKILL and plugin_listed(names[a], SKILL):
                    where.append("native plugin")
            if a == "kimi" and skill == SKILL and kimi_plugin_installed(ctx):
                where.append("Kimi plugin")
            if skill == SKILL:
                if len(where) > 1:
                    add("dup.%s.%s" % (skill, a), "FAIL", "%s sees %d copies: %s" % (DISPLAY[a], len(where),
                                                                                   "; ".join(where)),
                        "keep one: run install.py install (coverage rule) or delete the extra folder")
                elif where and (agents[a]["detected"] or agents[a]["selected"]):
                    add("agent.%s.skill" % a, "PASS", "%s: %s" % (DISPLAY[a], where[0]))
                elif agents[a]["detected"]:
                    add("agent.%s.skill" % a, "WARN", "%s: %s is not installed" % (DISPLAY[a], SKILL),
                        "run: install.py install")
            elif len(where) > 1:
                add("dup.%s.%s" % (skill, a), "WARN", "%s sees %s %d times: %s" % (DISPLAY[a], skill, len(where),
                                                                                "; ".join(where)),
                    "delete the extra copy (for Codex keep ~/.agents/skills, not ~/.codex/skills)")
    # a provider Codex home (setup-glm/-kimi --codex) also scans ~/.agents/skills
    ch_root = os.path.join(ctx.ub_home, "codex-homes")
    if agents["codex"]["bin"] and os.path.isdir(ch_root):
        for p in sorted(os.listdir(ch_root)):
            h = os.path.join(ch_root, p)
            if not os.path.isdir(h):
                continue
            where = []
            shared = os.path.join(ctx.agents_skills, SKILL)
            if os.path.isdir(shared):
                where.append(posix(shared))
            if native_installed(ctx, "codex", codex_home=h):
                where.append("native plugin (CODEX_HOME=%s)" % posix(h))
            if len(where) > 1:
                add("dup.%s.codex-%s" % (SKILL, p), "FAIL", "Codex on %s sees %d copies: %s" % (p, len(where),
                                                                                              "; ".join(where)),
                    "keep one: remove the plugin from that CODEX_HOME or delete %s" % posix(shared))
    # frontmatter, ownership and legacy copies
    seen = set()
    for a in AGENTS:
        for dpath in skill_dirs_for(ctx, a) + [os.path.dirname(copy_dest(ctx, a))]:
            p = os.path.join(dpath, SKILL)
            key = os.path.normcase(os.path.abspath(p))
            if key in seen or not os.path.isdir(p):
                continue
            seen.add(key)
            fm = read_frontmatter(os.path.join(p, "SKILL.md"))
            sha = textio.sha256_file(os.path.join(p, "SKILL.md"))[:12] if os.path.isfile(os.path.join(p, "SKILL.md")) \
                else "-"
            if fm is None:
                add("skill.frontmatter:%s" % posix(p), "FAIL", "%s has no SKILL.md frontmatter" % posix(p),
                    "reinstall: install.py install --force")
                continue
            problems = []
            if fm.get("name") != os.path.basename(p):
                problems.append("name %r differs from the folder name" % fm.get("name"))
            if len(fm.get("description", "")) > 1024:
                problems.append("description is longer than 1024 characters")
            add("skill.frontmatter:%s" % posix(p), "FAIL" if problems else "PASS",
                "%s (SKILL.md sha256 %s)%s" % (posix(p), sha, (": " + "; ".join(problems)) if problems else ""),
                "reinstall: install.py install --force")
            owned = os.path.isfile(os.path.join(p, MARKER))
            if not owned and is_v1_skill(p):
                add("legacy.v1:%s" % posix(p), "WARN", "%s is the v1 skill (not owned)" % posix(p),
                    "run: install.py install --migrate-v1")
            elif owned:
                entry = manifest_entry(ctx, "copy", p)
                rec = (entry or {}).get("files")
                if isinstance(rec, dict) and rec != hash_files(walk_files(p, top_exclude=False)):
                    add("owned.edited:%s" % posix(p), "WARN", "%s was edited after install" % posix(p),
                        "run: install.py update (edited files are backed up first)")
    if os.path.isdir(os.path.join(ctx.home, ".kimi")):
        add("legacy.kimi_home", "WARN", "%s exists (legacy kimi-cli)" % posix(os.path.join(ctx.home, ".kimi")),
            "after moving to Kimi Code v2 run: kimi migrate")
    # endpoints (5.5): which family the CLIs really serve
    settings = load_json_file(os.path.join(ctx.homes["claude-code"], "settings.json"), {}) or {}
    url = ((settings.get("env") or {}) if isinstance(settings, dict) else {}).get("ANTHROPIC_BASE_URL")
    fam = classify_url(url)
    if fam == "claude":
        add("endpoint.claude", "PASS", "claude CLI serves the claude family")
    else:
        add("endpoint.claude", "WARN", "claude family reclassified as %s (settings.json ANTHROPIC_BASE_URL %s)"
            % (fam, url), "use a launcher (claude-glm / claude-kimi) instead of a global settings.json endpoint")
    cprov, cbase = codex_provider(ctx)
    cfam = "gpt"
    if cbase and classify_url(cbase) in ("glm", "kimi"):
        cfam = classify_url(cbase)
    elif cprov and cprov.lower() not in ("openai",):
        cfam = "glm" if re.search(r"z\.?ai|bigmodel|glm", cprov, re.I) else (
            "kimi" if re.search(r"moonshot|kimi", cprov, re.I) else "custom:%s" % cprov)
    if cfam == "gpt":
        add("endpoint.codex", "PASS", "codex CLI serves the gpt family")
    else:
        add("endpoint.codex", "WARN", "gpt family reclassified as %s (config.toml model_provider %s)" % (cfam, cprov),
            "use codex-glm / codex-kimi (separate CODEX_HOME) instead of changing ~/.codex/config.toml")
    # stack components
    for skill in ("grilling", "domain-modeling"):
        found = [a for a in AGENTS if any(os.path.isdir(os.path.join(dd, skill)) for dd in skill_dirs_for(ctx, a))]
        add("stack.%s" % skill, "PASS" if found else "WARN",
            ("present for %s" % ", ".join(found)) if found else "%s not found in any agent's skills folder" % skill,
            "install.py install (component mattpocock-grilling)")
    ce = [a for a in ("claude-code", "codex") if names.get(a) is not None and
          plugin_listed(names[a], "compound-engineering")]
    add("stack.compound-engineering", "PASS" if ce else "WARN",
        ("installed for %s" % ", ".join(ce)) if ce else "Compound Engineering plugin not found",
        "install.py install (component compound-engineering), or the guide's section 3 commands")
    # families via family.py (B2)
    fam_py = os.path.join(ctx.kit_dir, "skills", SKILL, "scripts", "family.py")
    if not os.path.isfile(fam_py):
        add("families", "WARN", "family.py not found in the staged kit", "run: install.py install")
    else:
        argv = [sys.executable, fam_py, "detect", "--json"] + (["--live"] if getattr(ctx.args, "live", False) else [])
        try:
            res = proc.run(argv, cwd=None, env=dict(ctx.env), stdin_bytes=None,
                           timeout_s=300 if getattr(ctx.args, "live", False) else 90)
            data = textio.extract_json(textio.decode_bytes(res.stdout_bytes)) if not res.timed_out else None
        except (OSError, ValueError, proc.ProcError):
            data = None
        fams = (data or {}).get("families") if isinstance(data, dict) else None
        if not isinstance(fams, dict):
            add("families", "WARN", "family.py detect failed", "run: python %s detect --json" % posix(fam_py))
        else:
            live = (data.get("live") or {}) if isinstance(data.get("live"), dict) else {}
            for name, f in fams.items():
                if not isinstance(f, dict):
                    continue
                if f.get("available"):
                    det = "%s via %s" % (name, f.get("backend"))
                    if name in live:
                        det += " (live: %s)" % live[name]
                    add("family.%s" % name, "PASS", det)
                else:
                    notes = "; ".join(str(n) for n in f.get("notes", [])) or "unavailable"
                    add("family.%s" % name, "WARN", "%s unavailable: %s" % (name, notes), notes)
    # backups
    broot = ctx.backup_root
    if os.path.isdir(broot):
        cutoff = time.time() - 90 * 86400
        stale = [n for n in os.listdir(broot) if os.path.getmtime(os.path.join(broot, n)) < cutoff]
        add("backups.stale", "WARN" if stale else "PASS",
            ("%d backup folder(s) older than 90 days in %s" % (len(stale), posix(broot))) if stale
            else "no stale backups", "delete old folders in %s when you no longer need them" % posix(broot))
    # invocation hints
    for a in AGENTS:
        if agents[a]["detected"]:
            t = ctx.targets["agents"][a]
            detail = "%s: %s" % (DISPLAY[a], t["invoke"])
            if a == "codex" and names.get("codex") is not None:
                # [U-4] show what `codex plugin list --json` reports for the kit
                node = json_find(names["codex"], lambda n: isinstance(n, dict) and
                                 SKILL in json.dumps(n, ensure_ascii=True) and len(n) < 20)
                if node is not None:
                    detail += " (codex plugin list: %s)" % json.dumps(node, ensure_ascii=True)[:200]
            add("invoke.%s" % a, "PASS", detail)
    code = 1 if any(c["status"] == "FAIL" for c in checks) else 0
    if getattr(ctx.args, "json", False):
        emit_json({"checks": checks, "exit": code})
    else:
        out(ctx, "ultimate-brainstorm doctor (read-only)")
        for c in checks:
            out(ctx, "  %-5s %-34s %s" % (c["status"], c["id"][:34], c["detail"]))
            if c["fix"]:
                out(ctx, "        fix: %s" % c["fix"])
        fails = sum(1 for c in checks if c["status"] == "FAIL")
        warns = sum(1 for c in checks if c["status"] == "WARN")
        out(ctx, "\n%d FAIL, %d WARN, %d PASS" % (fails, warns, len(checks) - fails - warns))
    return code


# list ---------------------------------------------------------------------------------------------------------------


def cmd_list(ctx):
    agents = detect_agents(ctx)
    items = []
    seen = set()
    for a in AGENTS:
        for d in skill_dirs_for(ctx, a) + [os.path.dirname(copy_dest(ctx, a))]:
            for skill in STACK_SKILLS:
                p = os.path.join(d, skill)
                key = (a, os.path.normcase(os.path.abspath(p)))
                if key in seen or not os.path.isdir(p):
                    continue
                seen.add(key)
                fm = read_frontmatter(os.path.join(p, "SKILL.md")) or {}
                items.append({"agent": a, "name": skill, "route": "copy", "path": posix(p),
                              "owned": os.path.isfile(os.path.join(p, MARKER)),
                              "version": fm.get("metadata.version") or fm.get("version") or None})
        if a in ("claude-code", "codex") and agents[a]["bin"]:
            listed = plugin_list(ctx, a)
            if listed is not None and plugin_listed(listed, SKILL, MARKETPLACE):
                owned = manifest_entry(ctx, "native", agent=a) is not None
                items.append({"agent": a, "name": SKILL, "route": "native", "path": None, "owned": owned,
                              "version": kit_version(ctx.kit_dir) if owned else None})
        if a == "kimi" and kimi_plugin_installed(ctx):
            items.append({"agent": a, "name": SKILL, "route": "kimi-plugin", "path": None, "owned": False,
                          "version": None})
    for e in (ctx.manifest or {}).get("entries", []):
        if e.get("route") == "native" and not any(i["agent"] == e.get("agent") and i["route"] == "native"
                                                   for i in items):
            items.append({"agent": e.get("agent"), "name": SKILL, "route": "native", "path": e.get("codex_home"),
                          "owned": True, "version": (ctx.manifest or {}).get("version"),
                          "note": "recorded in the manifest (CLI not checked)"})
    for c in (ctx.manifest or {}).get("components", []):
        items.append({"agent": c.get("agent"), "name": c.get("id"), "route": c.get("route"), "path": None,
                      "owned": False, "version": c.get("ref")})
    launchers = [p for p in (ctx.manifest or {}).get("launchers", []) if os.path.lexists(p)]
    result = {"schema": 1, "ub_home": posix(ctx.ub_home), "kit": posix(ctx.kit_dir) if os.path.isdir(ctx.kit_dir)
              else None, "items": items, "launchers": launchers}
    if getattr(ctx.args, "json", False):
        emit_json(result)
    else:
        out(ctx, "ultimate-brainstorm: installed items (UB_HOME %s)" % posix(ctx.ub_home))
        if not items:
            out(ctx, "  nothing found")
        for i in items:
            out(ctx, "  %-12s %-20s %-11s %-8s %-8s %s" % (i["agent"], i["name"], i["route"],
                                                          "owned" if i["owned"] else "foreign", i["version"] or "-",
                                                          i["path"] or ""))
        for p in launchers:
            out(ctx, "  launcher     %s" % p)
    return 0


# --------------------------------------------------------------------------------------------------------------------
# main


def build_parser():
    p = argparse.ArgumentParser(prog="install.py", description="ultimate-brainstorm kit installer (plan by default)")
    p.add_argument("command", nargs="?", default="plan", choices=COMMANDS)
    p.add_argument("--json", action="store_true")
    p.add_argument("--yes", "-y", action="store_true")
    p.add_argument("--agents", default="auto")
    p.add_argument("--scope", choices=("user", "project"), default="user")
    p.add_argument("--project-dir", dest="project_dir")
    p.add_argument("--source")
    p.add_argument("--tag")
    p.add_argument("--components", default="core")
    p.add_argument("--with-clis", dest="with_clis")
    p.add_argument("--login", action="store_true")
    p.add_argument("--force", action="store_true")
    p.add_argument("--migrate-v1", dest="migrate_v1", action="store_true")
    p.add_argument("--routing-block", dest="routing_block", action="store_true")
    p.add_argument("--claude-config-dir", dest="claude_config_dir")
    p.add_argument("--codex-home", dest="codex_home")
    p.add_argument("--kimi-home", dest="kimi_home")
    p.add_argument("--no-native", dest="no_native", action="store_true")
    p.add_argument("--backup-dir", dest="backup_dir")
    p.add_argument("--git-init", dest="git_init", action="store_true")
    p.add_argument("--purge", action="store_true")
    p.add_argument("--live", action="store_true")
    p.add_argument("--region", choices=("global", "cn"))
    p.add_argument("--launcher", action="store_true")
    p.add_argument("--codex", action="store_true")
    p.add_argument("--zai-mcp", dest="zai_mcp", action="store_true")
    p.add_argument("--provider", choices=("kimi", "kimi-code"))
    return p


def _is_root():
    """root on POSIX; an elevated (administrator) process on Windows (10.4 item 8: no sudo or admin)."""
    if IS_WINDOWS:
        try:
            import ctypes
            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except Exception:  # noqa: BLE001
            return False
    geteuid = getattr(os, "geteuid", None)
    return bool(geteuid and geteuid() == 0)


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            pass
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 2
    if args.command == "version":
        v = kit_version(KIT_ROOT)
        if args.json:
            emit_json({"version": v})
        else:
            sys.stdout.write(v + "\n")
        return 0
    ctx = None
    try:
        ctx = Ctx(args)
        allow_root = ctx.env.get("UB_ALLOW_ROOT") == "1"
        ctx.root_ok = lambda: allow_root or not _is_root()
        if args.command in MUTATING and not ctx.root_ok():
            raise InstallError("refusing to run as root or administrator; set UB_ALLOW_ROOT=1 to allow it (never use "
                               "sudo or an elevated shell)")
        if args.scope == "project" and not os.path.isdir(ctx.project):
            raise InstallError("--project-dir %s does not exist" % posix(ctx.project), 2)
        if args.command in ("plan", "install", "update", "setup-glm", "setup-kimi"):
            resolve_source(ctx, args.command)
        if args.command == "plan":
            return cmd_plan(ctx)
        if args.command == "install":
            return cmd_install(ctx, "install")
        if args.command == "update":
            return cmd_install(ctx, "update")
        if args.command == "uninstall":
            return cmd_uninstall(ctx)
        if args.command == "doctor":
            return cmd_doctor(ctx)
        if args.command == "list":
            return cmd_list(ctx)
        if args.command == "setup-glm":
            return cmd_setup(ctx, "glm")
        if args.command == "setup-kimi":
            return cmd_setup(ctx, "kimi")
        return 2
    except InstallError as exc:
        if ctx is not None:
            ctx.flush_log()
        if args.json:
            emit_json({"error": str(exc), "exit": exc.code})
        else:
            sys.stderr.write("install.py: %s\n" % exc)
        return exc.code
    except KeyboardInterrupt:
        sys.stderr.write("install.py: interrupted\n")
        return 5
    finally:
        if ctx is not None:
            for d in ctx.cleanup:
                rmtree(d)


if __name__ == "__main__":
    sys.exit(main())
