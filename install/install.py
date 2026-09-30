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
              --require-attestation   (a downloaded release must pass `gh attestation verify`)

Exit codes: 0 ok (also "nothing to do"), 1 failure, 2 usage, 3 no supported agent detected and none named,
            4 blocked rows present with --yes, or the install changed after the plan was made (nothing applied),
            5 cancelled by the user.

Apply writes install-manifest.json and install.log after every row, under an exclusive lock on UB_HOME/install.lock.
Rows that would swap a kit tree wait (are blocked) while a run has live workers or a live driver; once the lock is
held, the plan's assumptions (no other installer changed the install, no run became live) are checked again.

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
import errno  # noqa: E402
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

KIT_VERSION = "2.1.0"
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
PLUGIN_ID = "ultimate-brainstorm@ultimate-brainstorm"
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

POLICY_GLM = ("The GLM Coding Plan may be used only in supported tools; this kit sends GLM traffic only through "
              "Claude Code or Codex.")

# 10.5 --purge deletes only what the kit creates in UB_HOME; anything else is listed and kept. Inside codex-homes/<p>/
# only the installer's config.toml is the kit's: Codex's own data (sessions, history) is moved to backups/ first.
PURGE_NAMES = ("kit", "bin", "codex-homes", "tmp", "config.json", "families.json", "install-manifest.json",
               "install.log", "runs.json", "install.lock")
PURGE_RE = re.compile(r"^kit\.(new|old)-[a-z0-9]{8}$")
# Staging and trash trees an installer killed mid-apply leaves behind (rand_suffix names; only installers make them):
# the kit's skill copies and the component skills it copies from a pinned archive.
LEFTOVER_SKILL_RE = re.compile(r"^(%s)\.ub-(new|old)-[a-z0-9]{8}$" % "|".join(re.escape(s) for s in STACK_SKILLS))
LEFTOVER_TMP_RE = re.compile(r"^old-[a-z0-9]{8}$")
LOCK_NAME = "install.lock"
# The first release whose assets carry a build provenance attestation (release.yml attest-build-provenance).
ATTESTED_SINCE = (2, 1, 0)
# The only workflow whose attestations count: a run of any other workflow in the repository can attest too.
RELEASE_WORKFLOW = ".github/workflows/release.yml"

RE_ALREADY = re.compile(r"already\s+(installed|exists|added|present|enabled|registered|configured)|is already",
                        re.IGNORECASE)
RE_ABSENT = re.compile(r"not\s+(installed|found|present|registered)|no such|does not exist|unknown (plugin|marketplace)",
                       re.IGNORECASE)
# [U-52] gh's exit code for "authentication required" (`gh help exit-codes`): the check could not run, not a verdict.
GH_EXIT_AUTH = 4
# a gh older than the identity flags of provenance_args (it cannot check the signer; not a verdict either). Matched in
# gh's own words only (gh_own_text): a refusal quotes the certificate's identity, which whoever minted it chose.
RE_GH_TOO_OLD = re.compile(r"unknown flag|unknown shorthand flag", re.IGNORECASE)
# [U-52] gh fails with these words, before it reads any attestation, when it cannot load its Sigstore trust root (the
# TUF repository is out of reach, for example behind a proxy that blocks it): the check could not run, not a verdict.
# Matched at the start of a line of gh's own words only (gh_own_text).
RE_GH_NO_VERIFIER = re.compile(r"^\s*(?:Error:\s*)?error creating Sigstore verifier\b", re.IGNORECASE | re.MULTILINE)
# [U-52] The releases' host. The sign-in pre-check asks about the account verify uses there: a bare `gh auth status`
# exits 1 when any account on any host has a problem. verify names it too, so GH_HOST (an enterprise default) cannot
# redirect it.
GH_HOST_ARGS = ["--hostname", "github.com"]
RE_QUOTED = re.compile(r'"(?:[^"\\]|\\.)*"')  # a double-quoted value as Go's %q writes it (backslash escapes)
# A git commit SHA (components.json "commit" pins).
RE_SHA = re.compile(r"\b[0-9a-f]{40}\b")


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


def manifest_digest(path):
    """SHA-256 of install-manifest.json (None when missing). Every apply rewrites it (installed_at), so a changed
    digest means another installer applied changes."""
    raw = read_bytes(path)
    return hashlib.sha256(raw).hexdigest() if raw is not None else None


class InstallLock(object):
    """UB_HOME/install.lock: an exclusive OS lock (msvcrt.locking / fcntl.flock, like the engine's job locks) held by
    the apply phase of every mutating command, so two installers never interleave their writes to the manifest and the
    agents' folders. The OS drops it when the process ends, even when it is killed."""

    _OFFSET = 0x7FFFFFF0  # the locked byte lies beyond EOF: the file stays empty

    def __init__(self, path):
        self.path = path
        self.fd = None

    def acquire(self):
        """True when held (or when this file system has no locks); False when another process holds it."""
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            fd = os.open(self.path, os.O_RDWR | os.O_CREAT | getattr(os, "O_BINARY", 0), 0o600)
        except OSError:
            return True  # no lock file here; the apply itself reports why UB_HOME is not writable
        try:
            if IS_WINDOWS:
                import msvcrt
                os.lseek(fd, self._OFFSET, 0)
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            os.close(fd)
            busy = exc.errno in (errno.EACCES, errno.EAGAIN, errno.EDEADLK, getattr(errno, "EWOULDBLOCK", 11)) or \
                getattr(exc, "winerror", None) in (5, 33)
            return not busy
        self.fd = fd
        return True

    def release(self):
        fd, self.fd = self.fd, None
        if fd is None:
            return
        try:
            if IS_WINDOWS:
                import msvcrt
                os.lseek(fd, self._OFFSET, 0)
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(fd, fcntl.LOCK_UN)
        except OSError:
            pass
        os.close(fd)


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


def unrecorded(root):
    """Relpaths (posix) under root that walk_files leaves out but a user may have put there: .git and .build content
    (an empty folder in them as `<relpath>/`: git refuses a .git without refs/ or objects/, which `git gc` leaves
    empty) and symlinks (one entry each, never followed). The marker and Python caches (__pycache__, *.pyc, *.pyo),
    which running the kit's scripts creates, do not count. A copy holding any of them counts as edited."""
    walked = walk_files(root, top_exclude=False)
    out = []
    root = os.path.abspath(root)
    for dirpath, dirnames, filenames in os.walk(root):
        rel_dir = os.path.relpath(dirpath, root)
        pre = "" if rel_dir == "." else rel_dir.replace("\\", "/") + "/"
        if not dirnames and not filenames and EXCLUDE_ANYWHERE & set(pre.split("/")):
            out.append(pre)
        links = [d for d in dirnames if os.path.islink(os.path.join(dirpath, d))]
        dirnames[:] = sorted(d for d in dirnames if d != "__pycache__" and d not in links)
        names = links + [n for n in filenames if n != MARKER and not n.endswith(EXCLUDE_SUFFIX)]
        out.extend(pre + n for n in names if pre + n not in walked)
    return sorted(out)


def hash_files(files):
    return {rel: textio.sha256_file(p) for rel, p in sorted(files.items())}


def doctor_hashes(p):
    """(hash_files of the folder p, None), or (None, "<file>: <error>") when a file in it cannot be read (held open
    without sharing, no read permission, or removed meanwhile): doctor reports it instead of crashing."""
    try:
        return hash_files(walk_files(p, top_exclude=False)), None
    except OSError as exc:
        return None, "%s: %s" % (posix(getattr(exc, "filename", None) or p), exc.strerror or exc)


def copy_files(files, dest):
    """Copy {rel: src} into dest. Every SKILL.md is copied last: a tree cut short by a hard kill (no finally runs)
    never holds a SKILL.md, so no agent registers it as a skill whose scripts are missing."""
    for rel, src in sorted(files.items(), key=lambda kv: (kv[0].rsplit("/", 1)[-1] == "SKILL.md", kv[0])):
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
        self.manifest_digest = manifest_digest(self.manifest_path)  # the install state this plan is made from
        self.source = KIT_ROOT
        self.source_is_temp = False
        # a random suffix keeps two runs in the same second from merging their backups
        self.stamp = path_stamp() + "-" + rand_suffix(4)
        self.tmp_dir = os.path.join(self.ub_home, "tmp")
        self.log_lines = []
        self.purged = False
        self.cleanup = []
        self.cache = {}
        self.notes = []  # warnings found before the plan exists (release provenance), shown in the plan's warnings

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
        if agent == "kimi" and getattr(args, "kimi_home", None):
            env["KIMI_CODE_HOME"] = self.homes["kimi"]
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


def home_env(agent, home):
    """The environment that points agent's CLI at agent home `home` (CLAUDE_CONFIG_DIR or CODEX_HOME); None for no
    home (the invocation's own home: its flags and environment)."""
    if not home:
        return None
    return {("CLAUDE_CONFIG_DIR" if agent == "claude-code" else "CODEX_HOME"): os.path.normpath(home)}


def entry_home(ctx, agent, e):
    """The agent home native manifest entry e was installed in (10.5): a setup-glm/-kimi provider CODEX_HOME, or a
    --claude-config-dir / --codex-home (or CLAUDE_CONFIG_DIR / CODEX_HOME) other than this invocation's home. None when
    it is this invocation's home, so a default-home entry runs exactly as before."""
    e = e or {}
    if agent == "codex" and e.get("profile"):
        return e.get("codex_home")
    rec = e.get("config_dir") if agent == "claude-code" else e.get("codex_home")
    return rec if rec and not _same(rec, ctx.homes.get(agent)) else None


def plugin_list(ctx, agent, home=None):
    """Parsed `<cli> plugin list --json` for claude-code or codex (in agent home `home`, else this invocation's),
    cached; None when unavailable [U-18]."""
    key = ("plugins", agent, home)
    if key in ctx.cache:
        return ctx.cache[key]
    native = ctx.targets["agents"][agent].get("native")
    result = None
    if native:
        extra = home_env(agent, home)
        rc, out, err = run_cmd(ctx, native["list"], timeout=60, env=ctx.child_env(extra, agent))
        if rc == 0:
            try:
                result = textio.extract_json(out)
            except ValueError:
                result = None
    ctx.cache[key] = result
    return result


def marketplace_list(ctx, agent, home=None):
    """Parsed `<cli> plugin marketplace list --json` for claude-code or codex (in agent home `home`, else this
    invocation's), cached; None when unavailable [U-18]."""
    key = ("marketplaces", agent, home)
    if key not in ctx.cache:
        result = None
        native = ctx.targets["agents"][agent].get("native") or {}
        if native.get("marketplace_list"):
            extra = home_env(agent, home)
            rc, out, _err = run_cmd(ctx, native["marketplace_list"], timeout=60, env=ctx.child_env(extra, agent))
            if rc == 0:
                try:
                    result = textio.extract_json(out)
                except ValueError:
                    result = None
        ctx.cache[key] = result
    return ctx.cache[key]


def _strings(obj, key=None):
    """(key, string) for every string value in a JSON tree (key = the nearest dict key, None in a top-level list)."""
    if isinstance(obj, str):
        yield key, obj
    elif isinstance(obj, dict):
        for k, v in obj.items():
            for item in _strings(v, k):
                yield item
    elif isinstance(obj, list):
        for v in obj:
            for item in _strings(v, key):
                yield item


def _local_path(ctx, value):
    """value as an absolute local path (plain, ~-relative or a file:// URL), else None."""
    v = value
    if v.lower().startswith("file://"):
        v = re.sub(r"^/([A-Za-z]:)", r"\1", v[len("file://"):])
    if v == "~" or v.startswith(("~/", "~\\")):
        v = ctx.home + v[1:]
    return v if os.path.isabs(v) else None


def _is_kit_path(ctx, value):
    v = _local_path(ctx, value)
    return v is not None and _same_real(v, ctx.kit_dir)


def marketplace_source(ctx, agent, home=None):
    """Where the kit's marketplace registration points [U-50]. Returns (state, text): ("kit", path) when a source value
    of the `ultimate-brainstorm` marketplace is UB_HOME/kit; ("foreign", source) when it names another source (a
    GitHub slug or URL, another marketplace folder, or a local folder that no longer exists), for example route 2 of
    10.2 or another (earlier) UB_HOME;
    ("absent", None) when no marketplace of that name is registered; (None, None) when the list is unavailable or its
    entry names nothing recognizable (then the caller keeps the name-only behavior of [U-18])."""
    listed = marketplace_list(ctx, agent, home)
    if listed is None:
        return None, None
    node = json_find(listed, lambda n: isinstance(n, dict) and n.get("name") == MARKETPLACE)
    if node is None:
        return "absent", None
    values = [(k, s) for k, s in _strings(node) if s and s != MARKETPLACE]
    if any(_is_kit_path(ctx, s) for _k, s in values):
        return "kit", posix(ctx.kit_dir)
    for k, s in values:
        if k not in ("source", "repo", "repository", "url", "path", "directory"):
            continue  # e.g. an install location (a clone or cache) says nothing about where it came from
        v = s.replace("\\", "/")
        path = _local_path(ctx, s)
        if path is not None:
            if os.path.isfile(os.path.join(path, ".claude-plugin", "marketplace.json")):
                return "foreign", s  # another marketplace folder (another UB_HOME, a clone)
            if not os.path.exists(path):  # an earlier UB_HOME/kit, moved or deleted: never the staged kit
                return "foreign", "%s (a folder that no longer exists)" % s
            continue
        if "://" in v or v.startswith("git@") or re.match(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(@\S+|#\S+)?$", v):
            return "foreign", s
    return None, None


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


def runtime_file_map(root, runtime_paths):
    """{relpath (posix): abspath} of the kit's runtime files under root (10.4 item 1). The installer stages exactly this
    set, read from the source kit's own targets.json (runtime_files), and tools/release.py archives it from the same
    list, so the two can never diverge."""
    files = {}
    for rp in runtime_paths:
        full = os.path.join(root, *rp.split("/"))
        if os.path.isfile(full):
            files[rp] = full
        elif os.path.isdir(full):
            for rel, p in walk_files(full).items():
                files[rp + "/" + rel] = p
    return files


def source_runtime_paths(ctx, root):
    """runtime_paths of the kit at root (its install/targets.json, which validate_source requires), as release.py
    reads them: an update run by an older installer still stages every path the newer kit adds. The running
    installer's list is the fallback for a missing or malformed list; an entry that could reach outside root (absolute,
    `..`, a drive or a backslash) makes the list malformed."""
    def inside(p):
        return isinstance(p, str) and p and not p.startswith("/") and ":" not in p and "\\" not in p and \
            ".." not in p.split("/")

    t = load_json_file(os.path.join(root, "install", "targets.json"))
    rps = t.get("runtime_paths") if isinstance(t, dict) else None
    if isinstance(rps, list) and rps and all(inside(p) for p in rps):
        return list(rps)
    return ctx.targets.get("runtime_paths", [])


def runtime_files(ctx, root):
    return runtime_file_map(root, source_runtime_paths(ctx, root))


def skill_source(ctx):
    return os.path.join(ctx.source, "skills", SKILL)


def kit_version(root):
    try:
        v = textio.read_text(os.path.join(root, "VERSION")).strip()
        return v or KIT_VERSION
    except OSError:
        return KIT_VERSION


def source_commit(ctx):
    key = ("commit", ctx.source)
    if key not in ctx.cache:  # the manifest is written after every applied row
        commit = "local"
        if os.path.isdir(os.path.join(ctx.source, ".git")):
            rc, out, _ = run_cmd(ctx, ["git", "-C", ctx.source, "rev-parse", "--short", "HEAD"], timeout=15)
            commit = out.strip() if rc == 0 and out.strip() else "local"
        ctx.cache[key] = commit
    return ctx.cache[key]


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
    # the staged kit, also when run through another spelling of UB_HOME (a junction, a symlink, subst, an 8.3 name)
    staged = _same_real(KIT_ROOT, ctx.kit_dir)
    if command == "update" and ctx.manifest and staged:
        # only the staged kit re-stages the clone it was installed from; any other kit copy stages itself (below)
        prev = ctx.manifest.get("source")
        if prev and not _same_real(prev, ctx.kit_dir) and validate_source(prev):
            ctx.source = os.path.abspath(prev)
            return
    if command == "update" and staged:
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
    """Extract a release archive: absolute, `..` and drive-letter names are refused, and links and device members are
    dropped. install/install.sh applies the same member filter before anything from the archive runs."""
    with tarfile.open(archive, "r:gz") as tf:
        members = []
        for m in tf.getmembers():
            name = m.name.replace("\\", "/")
            if name.startswith("/") or ".." in name.split("/") or re.match(r"^[A-Za-z]:", name):
                raise InstallError("unsafe path in release archive: %s" % m.name)
            if m.issym() or m.islnk() or m.isdev():
                continue
            members.append(m)
        if hasattr(tarfile, "data_filter"):  # 3.12+, and the 3.9-3.11 security backports
            tf.extractall(dest, members=members, filter="data")
        else:
            tf.extractall(dest, members=members)


def release_dir_version(rel_dir):
    """The newest X.Y.Z archive in a UB_RELEASE_DIR folder, compared as numbers (2.0.10 > 2.0.9). When the folder has
    a SHA256SUMS, only the archives it lists count, so the pick always has a checksum. Pre-release archives
    (2.1.0-rc1) are skipped, as releases/latest skips them."""
    rx = re.compile(r"^ultimate-brainstorm-(\d+(?:\.\d+)+)\.tar\.gz$")
    names = os.listdir(rel_dir)
    sums = os.path.join(rel_dir, "SHA256SUMS")
    if os.path.isfile(sums):
        listed = set(line.split()[-1].lstrip("*") for line in textio.read_text(sums).splitlines() if line.split())
        names = [n for n in names if n in listed]
    found = [(tuple(int(x) for x in m.group(1).split(".")), m.group(1)) for m in (rx.match(n) for n in names) if m]
    if not found:
        raise InstallError("UB_RELEASE_DIR has no ultimate-brainstorm-<ver>.tar.gz")
    return max(found)[1]


def provenance_args(repo, ver):
    """The identity `gh attestation verify` enforces for a release asset: built by this repository's release workflow
    (--signer-workflow) from the tag v<ver> (--source-ref), not by any other workflow run in the repository."""
    return ["--repo", repo, "--signer-workflow", "%s/%s" % (repo, RELEASE_WORKFLOW), "--source-ref",
            "refs/tags/v%s" % ver]


def gh_own_text(text):
    """gh's output without its double-quoted values: the words gh wrote itself. A refusal quotes the identity found in
    the certificate (workflow path, branch, tag), which whoever minted the attestation chose, so no verdict is read
    from inside the quotes."""
    return RE_QUOTED.sub('""', text or "")


def verify_provenance(ctx, archive, ver, latest=False):
    """Check the build provenance of a downloaded release archive with `gh attestation verify <archive>
    provenance_args(...) --hostname github.com` [U-52]. It first runs `gh attestation --help` and `gh auth status
    --active --hostname github.com` (the account verify uses; another account or host does not matter); after they
    pass, every failed verification raises, except a timeout, gh's exit code 4 (authentication required), a gh
    without the --signer-workflow / --source-ref / --hostname flags (`unknown flag` in gh's own words) and a gh that
    could not build its Sigstore verifier (RE_GH_NO_VERIFIER). Those, a failed pre-check, gh missing, local
    UB_RELEASE_DIR assets and a release older than ATTESTED_SINCE named with --tag cannot be checked: a note is added
    to the plan warnings, or with --require-attestation an InstallError is raised. A refusal names the way out when gh
    cannot reach GitHub or Sigstore: the check by hand elsewhere, then --source DIR.
    latest: ver was resolved from releases/latest. A latest release older than ATTESTED_SINCE is refused: every
    release from ATTESTED_SINCE on is attested, so an older one marked latest was not asked for."""
    repo = ctx.targets["kit"]["repo"]
    name = os.path.basename(archive)
    check = provenance_args(repo, ver) + GH_HOST_ARGS
    manual = "gh attestation verify %s %s" % (name, " ".join(check))
    required = bool(getattr(ctx.args, "require_attestation", False))

    def cannot(why):
        msg = "provenance of %s was not checked (%s); check it by hand: %s" % (name, why, manual)
        if required:
            raise InstallError("--require-attestation: " + msg)
        ctx.notes.append(msg)

    v = parse_version(ver)
    if v is not None and v < ATTESTED_SINCE:
        if latest:
            raise InstallError("the latest release is v%s, older than %s, the first release with a provenance "
                               "attestation: not installing a release that cannot be verified and was not asked for "
                               "(name it with --tag v%s to install it anyway)" % (ver, vtext(ATTESTED_SINCE), ver))
        return cannot("release %s predates provenance attestations" % ver)
    if ctx.env.get("UB_RELEASE_DIR"):
        return cannot("local release assets from UB_RELEASE_DIR")
    if not proc.resolve_exe("gh", ctx.env):
        return cannot("the GitHub CLI gh is not installed")
    for pre in (["gh", "attestation", "--help"], ["gh", "auth", "status", "--active"] + GH_HOST_ARGS):
        if run_cmd(ctx, pre, timeout=60)[0] != 0:
            return cannot("gh is not signed in, or has no attestation command: `%s` failed" % " ".join(pre))
    rc, o, e = run_cmd(ctx, ["gh", "attestation", "verify", archive] + check, timeout=120)
    if rc == 0:
        return None
    text = (e or o or "").strip()
    last = text.splitlines()[-1][:200] if text else "no output"
    own = gh_own_text(text)
    if RE_GH_TOO_OLD.search(own):
        return cannot("this gh has no --signer-workflow / --source-ref / --hostname: update the GitHub CLI")
    if RE_GH_NO_VERIFIER.search(own):
        return cannot("gh could not build its Sigstore verifier: is the Sigstore TUF repository "
                      "(tuf-repo-cdn.sigstore.dev) reachable from here? gh: %s" % last)
    if rc is None or rc == GH_EXIT_AUTH:
        return cannot("gh could not run the check: %s" % last)
    raise InstallError("provenance check failed for %s: gh attestation verify did not confirm that it was built by "
                       "%s's %s for the tag v%s (gh: %s). Do not install this archive. If gh could not reach GitHub or "
                       "Sigstore, run the command again; if they stay out of reach, run the check by hand where gh "
                       "reaches them (%s) and install that checked archive's extracted folder with "
                       "`install.py update --source DIR`." % (name, repo, RELEASE_WORKFLOW, ver, last, manual))


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
        ver = release_dir_version(rel_dir)
    latest = not ver
    if latest:  # [L] releases/latest redirects to .../releases/tag/vX.Y.Z
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
    # SHA256SUMS comes from the same release as the archive: integrity only. The attestation adds authenticity.
    verify_provenance(ctx, archive, ver, latest=latest)
    out = os.path.join(tmp, "src")
    _safe_extract(archive, out)
    for cand in [out] + [os.path.join(out, d) for d in sorted(os.listdir(out))]:
        if validate_source(cand):
            # the downgrade guard (stage_row) and the provenance rules read the version: it must be the tag's
            try:
                inner = textio.read_text(os.path.join(cand, "VERSION")).strip()
            except OSError:
                inner = ""
            if inner != ver:
                raise InstallError("the release archive %s holds kit %s, not %s (its tag v%s): not installing it"
                                   % (name, inner or "without a VERSION", ver, ver))
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
    """The manifest's native entry for agent in this invocation's home (the one native_installed checks), not a
    setup-glm/-kimi provider CODEX_HOME or another home recorded by an earlier --claude-config-dir / --codex-home."""
    for e in (ctx.manifest or {}).get("entries", []):
        if e.get("route") == "native" and e.get("agent") == agent and not e.get("profile") and \
                entry_home(ctx, agent, e) is None:
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


def uninstall_native_row(ctx, agent, e, last_for_marketplace=True, action="remove", warnings=None):
    """Row removing the kit's native plugin recorded by manifest entry e (10.5), in the agent home e was installed in
    (entry_home, whatever this invocation's flags): the recorded scope and project, and the marketplace only when no
    other native entry of this agent and home still uses it. A local-scope entry whose project folder is gone keeps
    only the marketplace removal (a user-level registration): its plugin setting went with the folder."""
    native = ctx.targets["agents"][agent]["native"]
    home = entry_home(ctx, agent, e)
    cmds = [list(native["uninstall"])]
    cwd = None
    if agent == "claude-code":
        scope = (e or {}).get("scope") or "user"
        cmds[0] += ["--scope", scope]
        if scope == "local":
            cwd = (e or {}).get("project") or ctx.project
            if not os.path.isdir(cwd):
                if warnings is not None:
                    warnings.append("%s no longer exists: its local plugin setting (.claude/settings.local.json) went "
                                    "with it, so only the marketplace registration is removed. If you moved the "
                                    "project, run `claude plugin uninstall %s --scope local` in its new folder"
                                    % (posix(cwd), PLUGIN_ID))
                cmds, cwd = [], None
    if last_for_marketplace:
        cmds.append([ctx.expand(a) for a in native["marketplace_remove"]])
    env_extra = home_env(agent, home)
    item = "plugin %s" % SKILL
    for k, v in (env_extra or {}).items():
        item += " (%s=%s)" % (k, posix(v))  # a row for another home than this invocation's names it
    return new_row(agent, item, action, "native", None, cmds, _kind="uninstall-native", native_agent=agent,
                   env_extra=env_extra, cwd=cwd, entry=e)


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
        entry = manifest_entry(ctx, "copy", dest)
        if cur == src_hash:
            record = None
            if (entry or {}).get("files") != src_hash:
                # the copy is byte-identical to the kit, but the manifest lost it (or holds stale hashes): an apply
                # that was interrupted before it wrote the manifest. Record it again, or uninstall would keep it.
                record = {"agent": agent, "route": "copy", "path": posix(dest), "scope": ctx.scope, "files": src_hash}
                if (entry or {}).get("replaced_backup"):
                    record["replaced_backup"] = entry["replaced_backup"]
                warnings.append("%s: install-manifest.json has no current record of this copy (an interrupted "
                                "install?): applying records it again" % posix(dest))
            return new_row(agent, item, "unchanged", "copy", dest, _kind="copy", dest=dest, src=src, hashes=src_hash,
                           record=record)
        recorded = (entry or {}).get("files")
        if isinstance(recorded, dict):
            edited = sorted(r for r, h in cur.items() if recorded.get(r) != h)
        else:
            edited = sorted(r for r, h in cur.items() if src_hash.get(r) != h)
        edited += unrecorded(dest)  # a .git or a link the user put there goes with the old tree: back it up
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
    edited += unrecorded(dest)
    warnings.append("%s: removing the owned copy at %s (%s)" % (agent, posix(dest), reason))
    return new_row(agent, "skill %s (duplicate)" % SKILL, "remove", "copy", dest, _kind="remove", dest=dest,
                   backup=edited or None)


def native_manifest_entry(ctx, agent, codex_home=None):
    """The manifest entry for the kit's plugin of agent (default home, or a setup-glm/-kimi provider CODEX_HOME)."""
    e = {"agent": agent, "route": "native", "marketplace": MARKETPLACE, "plugin": PLUGIN_ID,
         "scope": "local" if (agent == "claude-code" and ctx.scope == "project") else "user"}
    if agent == "claude-code":
        e["config_dir"] = posix(ctx.homes["claude-code"])
        if e["scope"] == "local":
            e["project"] = posix(ctx.project)  # uninstall runs `--scope local` from this folder
    else:
        e["codex_home"] = posix(codex_home or ctx.homes["codex"])
        if codex_home:
            e["profile"] = True
    return e


def has_entry(ctx, entry):
    """True when the manifest already holds an entry with the same key as entry."""
    k = entry_key(entry)
    return any(entry_key(x) == k for x in (ctx.manifest or {}).get("entries", []) if isinstance(x, dict))


def native_row(ctx, agent, mode, codex_home=None, warnings=None):
    """Row for the kit's native plugin. The `ultimate-brainstorm` marketplace must point at UB_HOME/kit [U-50]: one
    registered from anywhere else (route 2 of 10.2, another UB_HOME) is never trusted by name alone. Its row is
    blocked (--force replaces it), and a plugin the installer did not install is never recorded as the kit's."""
    native = ctx.targets["agents"][agent]["native"]
    subst = lambda argv: [ctx.expand(a) for a in argv]  # noqa: E731
    listed = plugin_list(ctx, agent, codex_home)
    installed = bool(listed is not None and plugin_listed(listed, SKILL, MARKETPLACE))
    source, source_text = marketplace_source(ctx, agent, codex_home)
    extra_env = {"CODEX_HOME": codex_home} if codex_home else None
    cwd = ctx.project if (agent == "claude-code" and ctx.scope == "project") else None
    item = "plugin %s" % SKILL + (" (CODEX_HOME=%s)" % posix(codex_home) if codex_home else "")
    common = dict(_kind="native", env_extra=extra_env, cwd=cwd, native_agent=agent, codex_home=codex_home,
                  mk_add=subst(native["marketplace_add"]))
    entry = native_manifest_entry(ctx, agent, codex_home)
    if source == "foreign":
        un = list(native["uninstall"]) + (["--scope", entry["scope"]] if agent == "claude-code" else [])
        replace = ([un] if installed else []) + [subst(native["marketplace_remove"]), subst(native["marketplace_add"]),
                                                 subst(native["install"])]
        if getattr(ctx.args, "force", False):
            if warnings is not None:
                warnings.append("%s: the marketplace %s is registered from %s: --force replaces it with the staged kit "
                                "%s" % (DISPLAY[agent], MARKETPLACE, source_text, posix(ctx.kit_dir)))
            return new_row(agent, item, "install", "native", None, replace, **common)
        reason = ("%s: the marketplace %s is registered from %s, not from the staged kit %s, so %s would run that "
                  "code: remove it (%s), or pass --force to replace it"
                  % (DISPLAY[agent], MARKETPLACE, source_text, posix(ctx.kit_dir), DISPLAY[agent],
                     " ; ".join(" ".join(c) for c in replace[:-2])))
        if warnings is not None:
            warnings.append(reason)
        return new_row(agent, item, "blocked", "native", None, replace, _kind="noop", reason=reason)
    if installed and mode == "update":
        # never adopt a plugin whose origin is unknown and that the manifest does not already hold
        adopt = source == "kit" or has_entry(ctx, entry)
        if agent == "claude-code":  # [U-16] the local marketplace loads in place; this refresh may fail
            cmds = [["claude", "plugin", "marketplace", "update", MARKETPLACE]]
            return new_row(agent, item, "update", "native", None, cmds, allow_fail=True, no_record=not adopt,
                           **common)
        cmds = [["codex", "plugin", "marketplace", "upgrade", MARKETPLACE, "--json"], subst(native["install"])]
        # [U-10] whether `codex plugin add` upgrades in place is unverified: fall back to remove + add
        return new_row(agent, item, "update", "native", None, cmds, no_record=not adopt,
                       fallback=[subst(native["uninstall"]), subst(native["install"])], **common)
    if installed:
        # a plugin from the staged kit that the manifest lost (an interrupted apply) is recorded again
        record = entry if (source == "kit" and not has_entry(ctx, entry)) else None
        if record is not None and warnings is not None:
            warnings.append("%s: install-manifest.json has no record of the kit's plugin (an interrupted install?): "
                            "applying records it again" % DISPLAY[agent])
        return new_row(agent, item, "unchanged", "native", None, [], record=record, **common)
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
    if ctx.components["components"][cid].get("archive"):
        dirs = skill_dirs_for(ctx, agent)
        skills = ctx.components["components"][cid].get("skills") or []
        return all(any(os.path.isdir(os.path.join(d, s)) for d in dirs) for s in skills)
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


def archive_manual(ctx, c, dest):
    """The by-hand step for an archive component: which folders of the pinned commit go where."""
    spec = c["archive"]
    return "download %s and copy %s into %s" % (spec["url"], " and ".join(
        s["path"] for _n, s in sorted(spec["skills"].items())), posix(dest))


def component_rows(ctx, agents, warnings, manual):
    """Rows for the stack components (10.4 item 4). Every source is pinned in components.json: skill folders by an
    upstream commit archive plus the SHA-256 of each folder's content (do_component_archive checks it, no npx and no
    npm dependency tree), marketplaces by tag plus a "commit" that do_component checks, uv tools by commit. [U-27]
    doctor compares the installed component skills with the hashes recorded at install."""
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
            if entry.get("copy_to") and c.get("archive"):
                dest = ctx.expand(entry["copy_to"])
                if component_present(ctx, cid, key):
                    rows.append(new_row(key, item, "unchanged", "archive", dest, [], _kind="noop"))
                    planned[key] = "unchanged"
                    continue
                if key == "kimi" and entry.get("skip_if_codex_step_ran") and planned.get("codex") == "install":
                    warnings.append("kimi: %s comes from the Codex step (~/.agents/skills, which Kimi reads)" % cid)
                    continue
                local = ctx.env.get("UB_COMPONENTS_DIR")  # a local archive needs no network, also offline
                reason = "UB_INSTALL_OFFLINE=1" if ctx.offline and not local else None
                if local and not os.path.isfile(os.path.join(local, c["archive"]["file"])):
                    reason = "UB_COMPONENTS_DIR has no %s" % c["archive"]["file"]
                if reason:
                    rows.append(new_row(key, item, "manual", "print", None, [], _kind="noop"))
                    manual.append("%s: %s   (%s)" % (DISPLAY.get(key, "All agents"), archive_manual(ctx, c, dest),
                                                     reason))
                    planned[key] = "manual"
                    continue
                rows.append(new_row(key, item, "install", "archive", dest, [], _kind="component", cid=cid,
                                    archive=c["archive"], dest=dest, ref=c.get("ref"), commit=c.get("commit")))
                planned[key] = "install"
                continue
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
                                ref=c.get("ref"), commit=c.get("commit"), source_match=c.get("source_match")))
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
    return new_row("all", item, action, "copy", ctx.kit_dir, [], _kind="stage", reason=reason,
                   downgrade=action == "blocked")


def block_downgrade(stage, rows):
    """A blocked downgrade (stage_row) blocks every row that would apply something from the older source: the copies,
    launchers and plugins would otherwise take the older kit while UB_HOME/kit stays newer, and the manifest would
    record the older version. `unchanged` rows that only re-record an entry (_record) are blocked too."""
    if not stage.get("_downgrade"):
        return
    for r in actionable(rows):
        r["action"], r["_kind"], r["_reason"] = "blocked", "noop", stage["_reason"]
        r.pop("_record", None)


def scanned_dirs(ctx):
    """[(agent, dir)]: the folders each agent scans for skills (skill_dirs_for) plus the parent of its copy destination
    (the project folder in project scope), once per agent and folder."""
    out = []
    for a in AGENTS:
        seen = set()
        for d in skill_dirs_for(ctx, a) + [os.path.dirname(copy_dest(ctx, a))]:
            key = os.path.normcase(os.path.abspath(d))
            if key not in seen:
                seen.add(key)
                out.append((a, d))
    return out


def skill_folders(ctx, skills=STACK_SKILLS):
    """[(agent, skill, path)] for every <dir>/<skill> folder in scanned_dirs(ctx). doctor and list share this scan."""
    out = []
    for a, d in scanned_dirs(ctx):
        for skill in skills:
            p = os.path.join(d, skill)
            if os.path.isdir(p):
                out.append((a, skill, p))
    return out


def leftovers(ctx):
    """Trees an installer killed mid-apply left behind (a hard kill runs no finally): <skills>/ultimate-brainstorm.ub-
    (new|old)-<rand> next to the agents' skill folders, and UB_HOME/kit.(new|old)-<rand> and UB_HOME/tmp/old-<rand>.
    Their random suffixes are made only by installers, so deleting them is safe (apply holds UB_HOME/install.lock)."""
    found, seen = [], set()
    places = [(d, LEFTOVER_SKILL_RE) for _a, d in scanned_dirs(ctx)]
    places += [(ctx.ub_home, PURGE_RE), (ctx.tmp_dir, LEFTOVER_TMP_RE)]
    for d, rx in places:
        key = os.path.normcase(os.path.abspath(d))
        if key in seen or not os.path.isdir(d):
            continue
        seen.add(key)
        for n in sorted(os.listdir(d)):
            p = os.path.join(d, n)
            if rx.match(n) and os.path.isdir(p) and not os.path.islink(p):
                found.append(p)
    return found


def leftover_rows(ctx):
    return [new_row("all", "installer leftover %s" % os.path.basename(p), "remove", "copy", p, [], _kind="sweep",
                    dest=p) for p in leftovers(ctx)]


def legacy_driver_alive(run_dir):
    """The .ub/lock.json record while a kit 2.0.x driver holds the run, else None: proc.legacy_driver_live, the one
    rule the engine applies too (KIT_SPEC 6.3, 10.4 item 8), on this installer's clock. A 2.0.x record {pid, host,
    heartbeat_at, heartbeat_ts} counts while its pid lives and its heartbeat is at most 120 s old, or older while the
    driver that wrote it still runs (for example a 2.0.x `ub run` waiting at a human gate, which beats no more): the
    process started no later than 1 s after the beat, or it runs ub.py on this run (proc.runs_ub_on). Kit 2.1+ records
    {pid, host, since, heartbeat_at, heartbeat_ts} carry "since" and decide nothing here: their heartbeat_ts, refreshed
    every 30 s while the 2.1 driver holds its kernel lock, is for 2.0.x drivers only, and a 2.1 driver is seen through
    that kernel lock (.ub/jobs/_driver.lock). A heartbeat more than 120 s in the future decides nothing either."""
    data = load_json_file(os.path.join(run_dir, ".ub", "lock.json"))
    return data if proc.legacy_driver_live(data, run_dir, now=time.time()) else None


def live_runs(ctx):
    """[(run dir, live job ids, driver)] for the runs in UB_HOME/runs.json and <project>/brainstorm/ that have a live
    worker (running marker or held execution lock) or a live driver: a kit 2.0.x driver's .ub/lock.json record
    (legacy_driver_alive; driver is that record), or a held .ub/jobs/_driver.lock (driver True). Those processes import
    kit modules lazily from the trees an update swaps, so a swap under them mixes versions."""
    if "live_runs" in ctx.cache:
        return ctx.cache["live_runs"]
    dirs = []
    data = load_json_file(os.path.join(ctx.ub_home, "runs.json"), {})
    for r in (data.get("runs") if isinstance(data, dict) else None) or []:
        if isinstance(r, dict) and isinstance(r.get("path"), str):
            dirs.append(r["path"])
    root = os.path.join(ctx.project, "brainstorm")
    if os.path.isdir(root):
        dirs.extend(os.path.join(root, n) for n in sorted(os.listdir(root)))
    out, seen = [], set()
    batch = None
    for d in dirs:
        d = os.path.abspath(d)
        key = os.path.normcase(d)
        if key in seen or not os.path.isdir(os.path.join(d, ".ub")):
            continue
        seen.add(key)
        jobs, driver = [], legacy_driver_alive(d)
        if os.path.isdir(os.path.join(d, ".ub", "jobs")):
            if batch is None:
                from ublib import batch  # lazy: plan and doctor of a fresh machine never need it
            try:
                jobs = [j for j in batch.running_jobs(d) if not j.startswith("_")]
                driver = driver or bool(batch.lock_state(d, "_driver"))
            except (OSError, ValueError):
                pass
        if jobs or driver:
            out.append((d, jobs, driver))
    ctx.cache["live_runs"] = out
    return out


def swaps_tree(row):
    """True for a row that replaces or deletes a tree a running worker or driver may import from."""
    kind, action = row.get("_kind"), row.get("action")
    if action in NOOP_ACTIONS:
        return False
    if kind in ("stage", "native"):
        return action == "update"
    if kind == "copy":
        return action in ("update", "backup+update", "migrate-v1")
    return kind in ("remove", "uninstall-native", "uninstall-copy", "uninstall-tree", "purge")


def describe_live(live):
    """The live runs for a message. A kit 2.0.x driver is named with its pid and host: one whose beat is older than
    proc.LEGACY_DRIVER_STALE_S is a `ub run` waiting for an answer in its terminal."""
    out = []
    for d, jobs, driver in live:
        what = ["%d live worker(s)" % len(jobs)] if jobs else []
        if isinstance(driver, dict):
            idle = time.time() - float(driver["heartbeat_ts"]) > proc.LEGACY_DRIVER_STALE_S
            what.append("a live driver: a kit 2.0.x session (pid %s, %s)%s" % (
                driver.get("pid"), driver.get("host") or "?",
                ", probably waiting for an answer in its terminal" if idle else ""))
        elif driver:
            what.append("a live driver")
        out.append("%s (%s)" % (posix(d), ", ".join(what)))
    return "; ".join(out)


def live_remedy(live):
    """How to end the live runs. `ub stop <run>` stops a 2.1 driver and the workers; a kit 2.0.x session ends only in
    its own terminal (2.0.x's `ub stop` stops its workers and leaves the session holding .ub/lock.json)."""
    ways = []
    if any(jobs or driver is True for _d, jobs, driver in live):
        ways.append("wait for them to finish, stop them (ub stop <run>)")
    if any(isinstance(driver, dict) for _d, _jobs, driver in live):
        ways.append("answer or close each kit 2.0.x session (Ctrl+C in its terminal; ub stop does not end it), then "
                    "run the command again")
    return ", ".join(ways) + ", or pass --force"


def guard_live_runs(ctx, rows, warnings):
    """Block the rows that swap kit trees while a run has live workers or a live driver (--force goes ahead)."""
    live = live_runs(ctx)
    todo = [r for r in rows if swaps_tree(r)]
    if not live or not todo:
        return
    what = describe_live(live)
    if getattr(ctx.args, "force", False):
        warnings.append("runs are active: %s; --force swaps the kit under them anyway (their jobs may fail and be "
                        "retried)" % what)
        return
    reason = ("runs are active: %s. Swapping the kit now would mix versions inside running processes: %s"
              % (what, live_remedy(live)))
    warnings.append(reason)
    for r in todo:
        r["action"], r["_kind"], r["_reason"] = "blocked", "noop", reason


# launchers --------------------------------------------------------------------------------------------------------


def launch_module(ctx):
    """profiles/launch.py of the source kit, loaded as a module for its rendering API (4.16). The launchers run the
    staged copy of this same file, so there is no other text to fall back to: when it is missing or fails to load, this
    raises InstallError and the launcher and Codex-home rows become `blocked` (the kit is incomplete or broken)."""
    cached = ctx.cache.get("launchmod")
    if isinstance(cached, InstallError):
        raise cached
    if cached is not None:
        return cached
    path = os.path.join(ctx.source, "profiles", "launch.py")
    try:
        if not os.path.isfile(path):
            raise InstallError("%s is missing: not a complete kit" % posix(path))
        try:
            spec = importlib.util.spec_from_file_location("ub_profiles_launch_%s" % rand_suffix(), path)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
        except Exception as exc:  # noqa: BLE001 - any import-time defect of launch.py
            raise InstallError("%s failed to load (%s: %s)" % (posix(path), type(exc).__name__, exc))
    except InstallError as exc:
        ctx.cache["launchmod"] = exc
        raise
    ctx.cache["launchmod"] = mod
    return mod


def launch_args_for(ctx, tool, provider=None, region=None, zai_mcp=False):
    return list(launch_module(ctx).launcher_args(tool, provider, region=region, zai_mcp=zai_mcp))


def launcher_set(ctx, name, launch_args):
    """{abs path: bytes} for <bin>/<name>, <name>.cmd and <name>.ps1. Each calls
    PY UB_HOME/kit/profiles/launch.py <launch_args> -- <user args> (4.16)."""
    mod = launch_module(ctx)
    try:
        rendered = mod.render_launchers(name, list(launch_args), ub_home_dir=ctx.ub_home, python_exe=sys.executable)
    except Exception as exc:  # noqa: BLE001 - launch.py refused (e.g. an unquotable path): never work around it
        raise InstallError("launcher %s: %s" % (name, exc))
    if sorted(rendered) != sorted([name, name + ".cmd", name + ".ps1"]):
        raise InstallError("launcher %s: profiles/launch.py rendered %s, not the three launcher forms"
                           % (name, ", ".join(sorted(rendered))))
    # UTF-8, plus a BOM for a .ps1 holding a non-ASCII path (launch.py launcher_bytes; a kit before 2.1 has none)
    encode = getattr(mod, "launcher_bytes", None) or (lambda _fname, text: text.encode("utf-8"))
    return {os.path.join(ctx.bin_dir, fname): encode(fname, text) for fname, text in rendered.items()}


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
    """launcher_row, or a 'blocked' row when the launcher text cannot be rendered safely (or profiles/launch.py is
    broken). launch_args is a list, or a function returning it (evaluated here, so its failure also blocks)."""
    try:
        files = launcher_set(ctx, name, launch_args() if callable(launch_args) else launch_args)
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
    rows.extend(leftover_rows(ctx))
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
            nrow = native_row(ctx, a, native_mode, warnings=warnings)
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
                          e.get("agent") == a and not e.get("profile") and e is not native_entry(ctx, a) and
                          entry_home(ctx, a, e) is None]  # the marketplace goes with this home's last entry
                pre = uninstall_native_row(ctx, a, native_entry(ctx, a), last_for_marketplace=not others,
                                           warnings=warnings)
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
    guard_live_runs(ctx, rows, warnings)
    block_downgrade(stage, rows)
    return assemble_plan(ctx, system, agents, rows, warnings, manual, nxt)


def assemble_plan(ctx, system, agents, rows, warnings, manual, nxt):
    warnings[:0] = [n for n in ctx.notes if n not in warnings]
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
    """Rows that apply changes. An `unchanged` row that re-records a lost manifest entry (_record) counts too."""
    out = []
    for r in rows:
        if r["action"] in NOOP_ACTIONS:
            if r["action"] == "unchanged" and r.get("_record"):
                out.append(r)
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
    """Copy files and empty folders (rels; a folder ends in `/`) or the whole tree (rels == 'all': every file and
    folder, .git, .build, caches and the marker included)
    under root to UB_HOME/backups/<stamp>/<agent>/<hash8>-<name>/<name>/. The caller deletes root afterwards, so
    nothing is left out silently. A symlink is never followed or re-created (copy-only): LINKS.txt next to ORIGIN.txt
    lists each one as `<relpath> -> <target>`; its target stays where it is."""
    container = backup_container(ctx, agent, root)
    base = os.path.join(container, os.path.basename(root))
    if rels == "all":
        rels = []
        for dirpath, dirnames, filenames in os.walk(root):
            rel_dir = os.path.relpath(dirpath, root)
            pre = "" if rel_dir == "." else rel_dir.replace("\\", "/") + "/"
            os.makedirs(os.path.join(base, *pre.split("/")), exist_ok=True)  # empty folders too
            links = [d for d in dirnames if os.path.islink(os.path.join(dirpath, d))]
            dirnames[:] = sorted(d for d in dirnames if d not in links)
            rels.extend(pre + n for n in sorted(links + filenames))
    links = []
    for rel in rels:
        src = os.path.join(root, *rel.split("/"))
        if rel.endswith("/"):  # an empty folder (unrecorded)
            os.makedirs(os.path.join(base, *rel.split("/")), exist_ok=True)
        elif os.path.islink(src):
            links.append("%s -> %s\n" % (rel, os.readlink(src)))
        elif os.path.isfile(src):
            t = os.path.join(base, *rel.split("/"))
            os.makedirs(os.path.dirname(t), exist_ok=True)
            shutil.copy2(src, t)
    if links:
        with open(os.path.join(container, "LINKS.txt"), "a", encoding="utf-8", newline="\n") as f:
            f.writelines(links)
    return posix(base)


def marker_bytes(ctx):
    return (json.dumps({"kit": SKILL, "version": kit_version(ctx.source), "installed_at": now_iso(),
                        "manifest": posix(ctx.manifest_path)}, ensure_ascii=True) + "\n").encode("ascii")


def do_stage(ctx, row):
    files = runtime_files(ctx, ctx.source)
    if _same_real(ctx.source, ctx.kit_dir):
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
    codex_home = row.get("_codex_home")
    ok = True
    for argv in row["commands"]:
        rc, o, e = run_logged(ctx, argv, row.get("_env_extra"), agent, row.get("_cwd"))
        result["commands"].append({"argv": argv, "exit": rc})
        if rc != 0 and (rc is None or not RE_ALREADY.search(o + "\n" + e)):  # rc None: the CLI never ran
            ok = False
            result["detail"] = (e or o).strip()[-300:]
            break
        if rc != 0 and argv == row.get("_mk_add"):
            # [U-18] "already added" counts as success only when that marketplace is the staged kit [U-50]
            ctx.cache.pop(("marketplaces", agent, codex_home), None)
            state, text = marketplace_source(ctx, agent, codex_home)
            if state == "foreign":
                ok = False
                result["detail"] = ("the marketplace %s is registered from %s, not from the staged kit %s: remove it "
                                    "(%s) or re-run with --force" % (MARKETPLACE, text, posix(ctx.kit_dir), " ".join(
                                        ctx.expand(a) for a in ctx.targets["agents"][agent]["native"]
                                        ["marketplace_remove"])))
                break
    if not ok and row.get("_fallback"):
        ok = True
        for argv in row["_fallback"]:
            rc, o, e = run_logged(ctx, argv, row.get("_env_extra"), agent, row.get("_cwd"))
            result["commands"].append({"argv": argv, "exit": rc})
            text = o + "\n" + e
            if rc != 0 and (rc is None or not (RE_ALREADY.search(text) or RE_ABSENT.search(text))):
                ok = False
                result["detail"] = (e or o).strip()[-300:]
                break
        if ok:
            result["detail"] = "upgraded by remove + add"
    if not ok and row.get("_allow_fail"):
        result["detail"] = "refresh failed (ignored: the local marketplace loads in place) [U-16]"
        ok = True
    if ok and row.get("_no_record"):
        result["detail"] = ("%s the plugin's marketplace source is unknown, so it is not recorded as the kit's [U-50]"
                            % result["detail"]).strip()
    elif ok:
        updates["entries"].append(native_manifest_entry(ctx, agent, codex_home))
    return ok


def find_marketplace_name(obj, source_match):
    def pred(node):
        if not isinstance(node, dict) or not isinstance(node.get("name"), str):
            return False
        blob = json.dumps(node, ensure_ascii=True)
        return source_match.lower() in blob.lower()
    node = json_find(obj, pred)
    return node["name"] if node else None


def pinned_commit_ok(ctx, row, agent, result, already=False):
    """After `<cli> plugin marketplace add <repo>@<tag>` of a component pinned to a commit in components.json: when
    `marketplace list --json` names a local clone of it that git can read, its HEAD must be that commit, so a moved
    tag installs nothing [U-51]. When no clone can be read the row goes on and its detail says "not verified".
    already: the add was answered "already ..." (RE_ALREADY), so the clone is an earlier registration of that
    marketplace (for example one added without the tag): a different HEAD is its ref, not a moved tag."""
    want, match = row.get("_commit"), row.get("_source_match")
    if not want or not match or agent not in ("claude-code", "codex"):
        return True
    ctx.cache.pop(("marketplaces", agent, None), None)
    listed = marketplace_list(ctx, agent)
    node = json_find(listed, lambda n: isinstance(n, dict) and isinstance(n.get("name"), str) and
                     match.lower() in json.dumps(n, ensure_ascii=True).lower()) if listed is not None else None
    head = None
    for _k, s in (_strings(node) if node is not None else []):
        if os.path.isabs(s) and os.path.isdir(s):
            rc, o, _e = run_cmd(ctx, ["git", "-C", s, "rev-parse", "HEAD"], timeout=30)
            m = RE_SHA.search(o or "") if rc == 0 else None
            if m:
                head = m.group(0)
                break
    if head is None:
        result["detail"] = "pinned commit %s not verified: no readable clone of %s [U-51]" % (want[:12], match)
        return True
    if head != want and already:
        cli = "claude" if agent == "claude-code" else "codex"
        result["detail"] = ("the marketplace %s (%s) was already registered and tracks commit %s, not the pinned %s "
                            "(%s): not installing from it. Remove it (%s plugin marketplace remove %s), then run "
                            "install.py install again" % (node.get("name"), match, head[:12], want[:12],
                                                          row.get("_ref"), cli, node.get("name")))
        return False
    if head != want:
        result["detail"] = ("%s at %s is commit %s, not the pinned %s (the tag moved): not installing it"
                            % (match, row.get("_ref"), head[:12], want[:12]))
        return False
    result["detail"] = "commit %s verified" % want[:12]
    return True


def tree_sha256(hashes):
    """One SHA-256 for a folder's content: of its `sha256sum` listing ("<sha256>  <relpath>" lines sorted by path).
    It pins what a component installs independently of how the archive holding it was compressed."""
    listing = "".join("%s  %s\n" % (h, rel) for rel, h in sorted(hashes.items()))
    return hashlib.sha256(listing.encode("utf-8")).hexdigest()


def fetch_component_archive(ctx, cid, spec):
    """The extracted top folder of a component's commit archive: downloaded once per run (or copied from
    UB_COMPONENTS_DIR, as UB_RELEASE_DIR does for the kit) and extracted with _safe_extract."""
    key = ("component-archive", cid)
    if key in ctx.cache:
        return ctx.cache[key]
    tmp = tempfile.mkdtemp(prefix="ub-comp-")
    ctx.cleanup.append(tmp)
    archive = os.path.join(tmp, spec["file"])
    local = ctx.env.get("UB_COMPONENTS_DIR")
    if local:
        src = os.path.join(local, spec["file"])
        if not os.path.isfile(src):
            raise InstallError("UB_COMPONENTS_DIR has no %s" % spec["file"])
        shutil.copyfile(src, archive)
    else:
        try:
            with urllib.request.urlopen(spec["url"], timeout=120) as r, open(archive, "wb") as f:
                shutil.copyfileobj(r, f)
        except OSError as exc:
            raise InstallError("download failed: %s (%s)" % (spec["url"], exc))
    out = os.path.join(tmp, "src")
    try:
        _safe_extract(archive, out)
    except (tarfile.TarError, EOFError, OSError) as exc:
        raise InstallError("%s is not a readable archive: %s" % (spec["file"], exc))
    tops = os.listdir(out)
    root = os.path.join(out, tops[0]) if len(tops) == 1 and os.path.isdir(os.path.join(out, tops[0])) else out
    ctx.cache[key] = root
    return root


def do_component_archive(ctx, row, updates, result):
    """Copy the skill folders of a component from its pinned commit archive into the agent's skills folder. Each folder
    must match its pinned content SHA-256 (components.json), or nothing is installed. A skill folder already there is
    kept as it is. The manifest records the installed files' hashes for doctor's drift check [U-27], and per skill
    folder the commit it came from (`commits`): a folder a re-install keeps still holds its earlier pin's content."""
    spec, dest_dir = row["_archive"], row["_dest"]
    root = fetch_component_archive(ctx, row["_cid"], spec)
    sources = {}
    for skill, pin in sorted(spec["skills"].items()):
        src = os.path.join(root, *pin["path"].split("/"))
        files = walk_files(src, top_exclude=False) if os.path.isdir(src) else {}
        got = tree_sha256(hash_files(files)) if files else None
        if got != pin["sha256"]:
            result["detail"] = ("%s in %s does not match its pinned SHA-256 (%s, not %s): not installing %s"
                                % (pin["path"], spec["url"], (got or "missing")[:12], pin["sha256"][:12], row["_cid"]))
            return False
        sources[skill] = files
    rec = {"id": row["_cid"], "agent": row["agent"], "route": "archive", "ref": row.get("_ref"),
           "commit": row.get("_commit"), "files": {}, "paths": {}, "commits": {}}
    # this record replaces the previous one of (id, agent): a folder the kit installed there keeps its record
    prev = next((c for c in (ctx.manifest or {}).get("components", []) if isinstance(c, dict) and
                 c.get("id") == row["_cid"] and c.get("agent") == row["agent"]), None) or {}
    kept = []
    for skill, files in sorted(sources.items()):
        dest = os.path.join(dest_dir, skill)
        if os.path.lexists(dest):
            kept.append(posix(dest))  # not the kit's to replace
            if _same((prev.get("paths") or {}).get(skill), dest) and (prev.get("files") or {}).get(skill):
                rec["files"][skill] = prev["files"][skill]  # installed by the kit: its edits stay drift
                rec["paths"][skill] = prev["paths"][skill]
                rec["commits"][skill] = ((prev.get("commits") or {}).get(skill) or prev.get("commit")
                                         or prev.get("ref"))
            continue
        make_parents(ctx, dest_dir, updates)
        new = "%s.ub-new-%s" % (dest, rand_suffix())
        try:
            copy_files(files, new)
            os.replace(new, dest)
        finally:
            if os.path.lexists(new):
                rmtree(new)
        rec["files"][skill] = hash_files(walk_files(dest, top_exclude=False))
        rec["paths"][skill] = posix(dest)
        rec["commits"][skill] = row.get("_commit")
    result["detail"] = "commit %s verified" % (row.get("_commit") or "")[:12] + (
        "; kept the existing %s" % ", ".join(kept) if kept else "")
    updates["components"].append(rec)
    ctx.log("component %s -> %s" % (row["_cid"], posix(dest_dir)))
    return True


def do_component(ctx, row, updates, result):
    if row.get("_archive"):
        return do_component_archive(ctx, row, updates, result)
    agent = row["agent"] if row["agent"] in AGENTS else None
    cmds = row["commands"]
    resolve = row.get("_resolve")
    steps = cmds[:-1] if resolve else cmds
    for argv in steps:
        rc, o, e = run_logged(ctx, argv, row.get("_env_extra"), agent, row.get("_cwd"), timeout=900)
        result["commands"].append({"argv": argv, "exit": rc})
        already = bool(RE_ALREADY.search(o + "\n" + e))  # [U-18] with exit 1 or exit 0
        if rc != 0 and not already:
            result["detail"] = (e or o).strip()[-300:]
            return False
        if argv[1:4] == ["plugin", "marketplace", "add"] and \
                not pinned_commit_ok(ctx, row, agent, result, already=already):
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
    rec = {"id": row["_cid"], "agent": row["agent"], "route": row["how"] if row["how"] != "native" else "native",
           "ref": row.get("_ref")}
    if row.get("_commit"):
        rec["commit"] = row["_commit"]
    updates["components"].append(rec)
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
    agent = row["agent"]
    flag = {"codex": "codex_home", "kimi": "kimi_home"}.get(agent)
    if flag and getattr(ctx.args, flag, None):
        os.makedirs(ctx.homes[agent], exist_ok=True)  # the named home may not exist yet; the CLI signs in there
    sys.stderr.write("Running %s in the foreground; complete the sign-in, then come back.\n" % " ".join(argv))
    # the sign-in lands in the home the plugin rows and the "signed in" check use (--codex-home / --kimi-home)
    rc = subprocess.call([exe] + argv[1:], env=ctx.child_env(None, agent))
    result["commands"].append({"argv": argv, "exit": rc})
    ctx.log("exit=%s %s" % (rc, " ".join(argv)))
    return rc == 0


def do_codexhome(ctx, row):
    write_bytes_atomic(row["_file"], row["_data"])
    ctx.log("codex home -> %s" % posix(row["_file"]))
    return ""


def base_url_node(path, cur, provider, allow_url=False):
    """providers.<provider>.base_url of a loaded UB_HOME/families.json, made on the way down. A missing or empty value
    counts as absent, as launch.py reads it; any other value that is not a JSON object is refused, except a single-URL
    base_url (a string, returned as is) when allow_url says the caller only reads it."""
    if cur is None:
        raise InstallError("%s is not valid JSON; fix or delete it first" % posix(path), 2)
    node, where = cur, []
    for key in ("providers", provider, "base_url"):
        if not isinstance(node, dict):
            break
        node[key] = node.get(key) or {}
        node = node[key]
        where.append(key)
    if not isinstance(node, dict) and not (allow_url and isinstance(node, str)):
        raise InstallError("%s: %s is not a JSON object; fix or delete it first"
                           % (posix(path), ".".join(where) or "the top level"), 2)
    return node


def do_families(ctx, row):
    path = os.path.join(ctx.ub_home, "families.json")
    cur = load_json_file(path, None)
    if cur is None and not os.path.exists(path):
        cur = {}
    prov = row["_provider"]
    node = base_url_node(path, cur, prov)
    backup_file(ctx, "all", path)
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


def apply_rows(ctx, rows, updates, status_of=None, persist=None):
    """Apply rows in order. persist() runs after every row that did something (the manifest and install.log are
    written incrementally), so an apply cut short at any point leaves a manifest that owns what was done."""
    results = []
    failed = False
    status_of = {} if status_of is None else status_of  # id(row) -> result status, for _requires
    for row in rows:
        res = {"n": row["n"], "item": row["item"], "status": "ok", "detail": "", "commands": []}
        results.append(res)
        status_of[id(row)] = res
        if row["action"] in NOOP_ACTIONS:
            res["status"] = row["action"] if row["action"] != "unchanged" else "unchanged"
            if row["action"] == "unchanged" and row.get("_record"):
                updates["entries"].append(row["_record"])  # re-record what an interrupted apply did not
                res["detail"] = "recorded in install-manifest.json"
                if persist:
                    persist()
            continue
        reqs = ([row["_requires"]] if row.get("_requires") is not None else []) + list(row.get("_requires_all") or [])
        bad = [r for r in reqs if (status_of.get(id(r)) or {}).get("status") not in ("ok", "unchanged")]
        if bad:
            res["status"] = "skipped"
            res["detail"] = "kept: row %s (%s) did not succeed" % (bad[0].get("n"), bad[0].get("item"))
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
            elif kind == "sweep":
                res["detail"] = rmtree_checked(row["_dest"])
                ctx.log("removed installer leftover %s %s" % (posix(row["_dest"]), res["detail"]))
            elif kind == "purge":
                res["detail"] = do_purge(ctx, row.get("_names") or [], row.get("_moves") or [])
            elif kind == "noop":
                res["status"] = row["action"]
        except InstallError as exc:
            res["status"] = "failed"
            res["detail"] = str(exc)
        except OSError as exc:
            res["status"] = "failed"
            res["detail"] = "%s: %s" % (type(exc).__name__, exc)
        except Exception as exc:  # noqa: BLE001 - e.g. proc.UnsafeArgument (a ValueError): this row fails, not the run
            res["status"] = "failed"
            res["detail"] = "%s: %s" % (type(exc).__name__, exc)
        if res["status"] == "failed":
            failed = True
            ctx.log("FAILED row %s %s: %s" % (row["n"], row["item"], res["detail"]))
        if persist:
            persist()
        if res["status"] == "failed":
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


def _same_real(a, b):
    """_same, or the same real folder under another spelling (a junction, a symlink, subst, an 8.3 name)."""
    return bool(a) and bool(b) and (_same(a, b) or _same(os.path.realpath(a), os.path.realpath(b)))


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
    if _same_real(ctx.source, ctx.kit_dir):
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


def recheck_under_lock(ctx, rows):
    """The plan may have waited (the confirmation question, another installer's apply), so once install.lock is held
    what it assumed is checked again, and nothing is applied (InstallError, exit 4) when another installer changed the
    install meanwhile (applying would write this plan's stale copy of install-manifest.json over its records), or when
    a run became live under a tree a planned row swaps (10.4 item 8; --force goes ahead)."""
    if manifest_digest(ctx.manifest_path) != ctx.manifest_digest:
        raise InstallError("another install.py changed this install (%s) after this plan was made; nothing was "
                           "applied: run the command again" % posix(ctx.manifest_path), 4)
    if getattr(ctx.args, "force", False) or not [r for r in actionable(rows) if swaps_tree(r)]:
        return
    ctx.cache.pop("live_runs", None)
    live = live_runs(ctx)
    if live:
        raise InstallError("runs became active after this plan was made: %s. Nothing was applied: %s"
                           % (describe_live(live), live_remedy(live)), 4)


def confirm_replan(ctx, confirmed, newplan, title):
    """The plan made again after --with-clis installed a CLI (its agent is now detected, so it can have new rows) is
    applied under the confirmation the first plan got: None applies it, (code, result) stops before its rows. With
    --yes a blocked row stops it (4, as a blocked first plan would); interactively, a plan with rows the user was not
    shown, or blocked rows, is shown and asked about again (5 on no)."""
    def key(r):
        return r["agent"], r["item"], r["path"], r["action"]

    rows = newplan["rows"]
    blocked = [r for r in rows if r["action"] == "blocked"]
    if getattr(ctx.args, "yes", False):
        if blocked:
            return 4, ("blocked rows present after the CLI install; only the CLI rows were applied: fix the warnings "
                       "and run the command again")
        return None
    seen = set(key(r) for r in confirmed)
    if not blocked and all(key(r) in seen for r in actionable(rows)):
        return None
    sys.stderr.write("The plan changed after the CLI install:\n\n" + plan_text(public_plan(newplan), title) + "\n\n")
    if ask("Apply %d change(s)?" % len(actionable(rows))):
        return None
    return 5, "cancelled after the CLI install; only the CLI rows were applied"


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
            plan["exit"] = 4
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
    lock = InstallLock(os.path.join(ctx.ub_home, LOCK_NAME))
    if not lock.acquire():
        raise InstallError("another install.py is applying changes (%s is locked): wait for it to finish, then run "
                           "this command again" % posix(lock.path))
    try:
        recheck_under_lock(ctx, rows)
    except BaseException:
        lock.release()
        raise

    def persist():
        """Write what is done so far: the manifest (atomically; every update is idempotent) and install.log."""
        if finish is None:
            write_manifest(ctx, updates)
        elif ctx.manifest and not ctx.purged and not getattr(args, "purge", False):
            write_manifest(ctx, updates)  # uninstall: finish() tidies up at the end
        ctx.flush_log()

    try:
        ensure_home_dirs(ctx)
        first = [r for r in rows if r.get("_kind") in ("cli", "login")]
        rest = [r for r in rows if r.get("_kind") not in ("cli", "login")]
        status_of = {}
        results, failed = apply_rows(ctx, first, updates, status_of, persist)
        halt = None
        if rebuild and any(res["status"] == "ok" and r.get("_kind") == "cli" for res, r in zip(results, first)):
            ctx.cache = {}
            newplan = rebuild()
            start = len(rows)
            rest = [r for r in newplan["rows"]]
            for i, r in enumerate(rest, start + 1):
                r["n"] = i
            plan["replan"] = rest
            plan["warnings"].extend(w for w in newplan["warnings"] if w not in plan["warnings"])
            halt = confirm_replan(ctx, rows, newplan, title)
            if halt:
                rest = []
        r2, f2 = apply_rows(ctx, rest, updates, status_of, persist)
        results.extend(r2)
        failed = failed or f2
        if finish:
            finish(updates)
        else:
            write_manifest(ctx, updates)
    except BaseException:
        # Ctrl+C or an unexpected error between rows: keep the records of what was done, then re-raise
        try:
            persist()
        except Exception:  # noqa: BLE001 - never mask the original error
            pass
        raise
    finally:
        ctx.flush_log()
        lock.release()
        if ctx.purged:
            try:
                os.unlink(lock.path)
            except OSError:
                pass
    # the Next lines must not tell the user to start an agent whose install failed
    all_rows = first + rest
    for row, res in zip(all_rows, results):
        a = row.get("agent")
        if res.get("status") == "failed" and a in DISPLAY:
            plan["next"] = [ln for ln in plan.get("next", []) if not ln.startswith("Start %s " % DISPLAY[a])]
            note = "%s: not installed (row %s failed)" % (DISPLAY[a], row.get("n"))
            if note not in plan["next"]:
                plan["next"].insert(0, note)
    plan["applied"] = True
    plan["results"] = results
    code = 1 if failed else (halt[0] if halt else 0)
    if halt:
        plan["result"] = halt[1]
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
        if failed:
            out(ctx, "\nSome rows failed (see above and %s)." % posix(ctx.log_path))
        else:
            out(ctx, "\n%s%s." % (halt[1][0].upper(), halt[1][1:]) if halt else "\nDone.")
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
        # "not installed" is read only from a CLI that ran: rc None (it could not start, e.g. in a missing cwd, or it
        # timed out) says nothing about the plugin, even when the error text reads "No such file or directory"
        if rc != 0 and (rc is None or not RE_ABSENT.search(o + "\n" + e)):
            ok = False
            result["detail"] = (e or o).strip()[-300:]
            break  # never remove the marketplace while the plugin that loads from it is still installed
    if ok and row.get("_entry") is not None:
        updates["remove_entries"].append(entry_key(row["_entry"]))
    return ok


def drop_done_removals(ctx, row, e):
    """A re-run after a partial uninstall: leave out the `plugin uninstall` of a plugin `plugin list` no longer shows,
    and the `marketplace remove` of a marketplace no longer registered, so the retry never depends on how the CLI words
    "not installed" [U-18]. Only for a user-scope entry, judged by the lists of the home the entry was installed in
    (entry_home), and only when the lists can be read."""
    agent = row["_native_agent"]
    if (e or {}).get("scope") == "local":
        return
    home = entry_home(ctx, agent, e)
    native = ctx.targets["agents"][agent]["native"]
    cmds = list(row["commands"])
    listed = plugin_list(ctx, agent, home)
    uninstalling = bool(cmds) and cmds[0][:len(native["uninstall"])] == native["uninstall"]
    if uninstalling and listed is not None and not plugin_listed(listed, SKILL, MARKETPLACE):
        cmds = cmds[1:]
    remove = [ctx.expand(a) for a in native["marketplace_remove"]]
    if cmds and cmds[-1] == remove and marketplace_source(ctx, agent, home)[0] == "absent":
        cmds = cmds[:-1]
    row["commands"] = cmds


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
        agent = e.get("agent")
        return agent, os.path.normcase(os.path.abspath(entry_home(ctx, agent, e) or ctx.homes.get(agent) or ""))

    keep_kit = []  # (agent, why) UB_HOME/kit must stay: a kept plugin may still load from it
    for i, e in enumerate(natives):
        agent = e.get("agent")
        if entry_home(ctx, agent, e) is None:
            seen_native.add(agent)  # this invocation's home has a record: no sweep for an unrecorded plugin
        # the marketplace goes with the last plugin entry of this agent and home
        last = not any(home_key(x) == home_key(e) for x in natives[i + 1:])
        row = uninstall_native_row(ctx, agent, e, last_for_marketplace=last, warnings=warnings)
        if not agents[agent]["bin"]:
            rows.append(new_row(agent, row["item"], "manual", "print", None, [], _kind="noop"))
            manual.append("%s: %s not found; remove the plugin by hand: %s"
                          % (DISPLAY[agent], agent, " ; ".join(" ".join(c) for c in row["commands"])))
            # the plugin stays registered against UB_HOME/kit until then; --force cannot remove it either, and without
            # the CLI no later run can see that it was removed by hand: --purge is the way out
            cli = ctx.targets["agents"][agent]["detect"]["bin"]
            keep_kit.append((agent, "%s is not on PATH; put it on PATH, then run uninstall again (without %s the "
                                    "installer cannot see a plugin removed by hand; if you no longer use %s, "
                                    "`uninstall --purge` also removes UB_HOME/kit)" % (cli, cli, DISPLAY[agent])))
            continue
        drop_done_removals(ctx, row, e)
        rows.append(row)
    for agent in ("claude-code", "codex"):
        if agent in seen_native or not agents[agent]["bin"]:
            continue
        listed = plugin_list(ctx, agent)
        if listed is not None and plugin_listed(listed, SKILL, MARKETPLACE):
            source, source_text = marketplace_source(ctx, agent)
            if force or source == "kit":
                if source == "kit" and not force:
                    # only this installer adds UB_HOME/kit as a marketplace: the manifest lost the record (#64)
                    warnings.append("%s: the plugin %s comes from the staged kit %s but install-manifest.json has no "
                                    "record of it: removing it" % (DISPLAY[agent], PLUGIN_ID, posix(ctx.kit_dir)))
                rows.append(uninstall_native_row(ctx, agent, {"agent": agent, "scope": "user"}))
                rows[-1]["_entry"] = None
            else:
                warnings.append("%s: the plugin %s was installed outside this installer%s: kept; use --force to "
                                "remove it" % (DISPLAY[agent], PLUGIN_ID,
                                               (" (from %s)" % source_text) if source_text else ""))
                rows.append(new_row(agent, "plugin %s (not installed by the kit)" % SKILL, "skip-not-owned", "native",
                                    None, [], _kind="noop"))
                if source is None:  # its source is unknown: it may load from UB_HOME/kit [U-50]
                    keep_kit.append((agent, "the plugin's source is unknown; remove the plugin first (or pass "
                                            "--force), then run uninstall again"))
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
        extra = unrecorded(path)  # .git, .build or links the user added: never deleted without a backup
        recorded = (entry or {}).get("files")
        if (entry or {}).get("replaced_backup"):
            manual.append("%s replaced a folder you had there; restore it by hand if you want it back: copy %s to %s"
                          % (posix(path), entry["replaced_backup"], posix(path)))
        if isinstance(recorded, dict) and recorded == cur and not extra:
            rows.append(new_row(agent, "skill %s" % SKILL, "remove", "copy", path, [], _kind="uninstall-copy",
                                dest=path, backup=None))
        elif force:
            edited = sorted(r for r, h in cur.items() if not isinstance(recorded, dict) or recorded.get(r) != h)
            rows.append(new_row(agent, "skill %s" % SKILL, "remove", "copy", path, [], _kind="uninstall-copy",
                                dest=path, backup=(edited + extra) or "all"))
        else:
            warnings.append("%s was edited after install, holds files the kit did not put there (.git, .build, "
                            "links) or is not in the manifest: kept; use --force to back it up and remove it"
                            % posix(path))
            rows.append(new_row(agent, "skill %s (edited)" % SKILL, "skip-not-owned", "copy", path, [], _kind="noop"))
    # routing blocks
    # normcase is only the key: a write through a lower-cased path renames CLAUDE.md to claude.md on Windows
    records, files = {}, {}
    for b in m.get("routing_blocks", []):
        if isinstance(b, dict) and b.get("path"):
            f = os.path.abspath(b["path"])
            records[os.path.normcase(f)] = b
            files.setdefault(os.path.normcase(f), f)
    names = {"claude-code": "CLAUDE.md", "codex": "AGENTS.md", "kimi": "AGENTS.md", "zcode": "AGENTS.md"}
    for a in AGENTS:
        f = os.path.abspath(os.path.join(ctx.homes[a], names[a]))
        files.setdefault(os.path.normcase(f), f)
    for key, f in sorted(files.items()):
        raw = read_bytes(os.path.realpath(f) if os.path.islink(f) else f)
        if raw is None or routing_span(raw.decode("utf-8", "replace")) is None:
            continue
        text, _bom, err, _real = read_instruction(f)
        if err:
            warnings.append("%s holds the routing block but %s; remove the block by hand" % (posix(f), err))
            rows.append(new_row("all", "routing block", "manual", "print", f, [], _kind="noop"))
            continue
        rows.append(new_row("all", "routing block", "remove", "copy", f, [], _kind="uninstall-routing", file=f,
                            record=records.get(key)))
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
    rows.extend(leftover_rows(ctx))
    purge = getattr(ctx.args, "purge", False)
    if os.path.isdir(ctx.kit_dir) and keep_kit and not purge:
        why = "UB_HOME/kit is the marketplace a kept plugin may load from: kept. " + " ".join(
            "%s: %s." % (DISPLAY[a], how) for a, how in keep_kit)
        warnings.append(why)
        rows.append(new_row("all", "staged kit (kept)", "skip-not-owned", "copy", ctx.kit_dir, [], _kind="noop",
                            reason=why))
    elif os.path.isdir(ctx.kit_dir):
        # UB_HOME/kit is the local marketplace the plugins load from: it goes only after every plugin removal worked
        rows.append(new_row("all", "staged kit", "remove", "copy", ctx.kit_dir, [], _kind="uninstall-tree",
                            dest=ctx.kit_dir,
                            requires_all=[r for r in rows if r.get("_kind") == "uninstall-native"]))
    if purge and os.path.isdir(ctx.ub_home):
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
            if keep_kit:
                warnings.append("--purge also removes UB_HOME/kit, which a kept plugin may load from (%s): remove that "
                                "plugin by hand" % ", ".join(DISPLAY[a] for a, _how in keep_kit))
            moves = codex_home_moves(ctx) if "codex-homes" in names else []
            for src, dst in moves:
                warnings.append("%s is Codex's own data (sessions, history, logs), not the kit's: --purge moves it to %s"
                                % (posix(src), posix(dst)))
            rows.append(new_row("all", "purge UB_HOME (keeps backups/)", "remove", "copy", ctx.ub_home, [],
                                _kind="purge", names=names, moves=moves,
                                requires_all=[r for r in rows if r.get("_kind") == "uninstall-native"]))
    manual.append("Kimi Code: if you installed the kit as a Kimi plugin, run /plugins remove ultimate-brainstorm")
    manual.append("ZCode: if you added the kit under Settings > Plugins, remove it there")
    # Components stay installed. The skill folders the kit copied from a pinned archive are named here: the manifest
    # that records them is deleted with the last entry, and no other tool knows them.
    copied = []
    for c in m.get("components", []):
        if not isinstance(c, dict) or c.get("route") != "archive":
            continue
        for _skill, p in sorted((c.get("paths") or {}).items()):
            if isinstance(p, str) and os.path.isdir(p) and not any(_same(p, x) for x in copied):
                copied.append(p)
    if copied:
        manual.append("Component skills the kit copied (uninstall keeps them): delete %s by hand if you no longer want "
                      "them" % ", ".join(posix(p) for p in copied))
    nxt.append("Run folders (brainstorm/) and %s are kept." % posix(ctx.backup_root))
    nxt.append("Components (Compound Engineering, mattpocock skills) stay installed: remove Compound Engineering with "
               "your agent's plugin commands and the mattpocock skill folders by hand%s."
               % (" (listed under Manual)" if copied else ""))
    guard_live_runs(ctx, rows, warnings)
    plan = assemble_plan(ctx, system, agents, rows, warnings, manual, nxt)
    return plan


def codex_home_moves(ctx):
    """[(src, dst)] for --purge: every entry of UB_HOME/codex-homes/<p>/ except the installer's own config.toml (the
    bytes setup-glm/-kimi --codex write) is Codex's data (sessions/, history.jsonl, log/, auth.json, plugin caches).
    It goes to <backups>/<stamp>/codex-homes/<p>/ instead of being deleted."""
    root = os.path.join(ctx.ub_home, "codex-homes")
    if not os.path.isdir(root) or os.path.islink(root):
        return []
    moves = []
    for p in sorted(os.listdir(root)):
        home = os.path.join(root, p)
        if not os.path.isdir(home) or os.path.islink(home):
            continue
        ours = []
        for region in ("global", "cn"):
            try:
                ours.append(codex_home_content(ctx, p, region))
            except InstallError:
                pass
        for child in sorted(os.listdir(home)):
            src = os.path.join(home, child)
            if child == "config.toml" and read_bytes(src) in ours:
                continue
            moves.append((src, os.path.join(ctx.backup_root, ctx.stamp, "codex-homes", p, child)))
    return moves


def do_purge(ctx, names, moves=()):
    """Move Codex's own data out of the provider homes into backups/ (nothing is deleted when a move fails), then
    delete only the listed UB_HOME entries (names the kit creates, chosen at plan time); backups/ stays."""
    for src, dst in moves:
        if not os.path.lexists(src):
            continue
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        try:
            os.replace(src, dst)
        except OSError:
            try:  # another volume (a --backup-dir elsewhere) or a locked file: copy, then delete the original
                if os.path.isdir(src) and not os.path.islink(src):
                    shutil.copytree(src, dst)
                else:
                    shutil.copy2(src, dst)
            except OSError as exc:
                raise InstallError("could not move %s to %s (%s); nothing was purged" % (posix(src), posix(dst), exc))
            rmtree(src)
        ctx.log("purge: moved %s -> %s" % (posix(src), posix(dst)))
    ctx.purged = True  # nothing (not even install.log) is written into UB_HOME afterwards
    for name in names:
        if name in ("backups", LOCK_NAME) or not (name in PURGE_NAMES or PURGE_RE.match(name)):
            continue  # the lock file goes after the lock is released
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
    if not moves:
        return ""
    return "Codex data moved to %s" % posix(os.path.join(ctx.backup_root, ctx.stamp, "codex-homes"))


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
    """The providers block of the source kit's families.default.json; InstallError when it cannot be read (launch.py
    reads the same file at every launch, so no launcher could work)."""
    path = os.path.join(ctx.source, "skills", SKILL, "scripts", "families.default.json")
    data = load_json_file(path)
    if isinstance(data, dict) and isinstance(data.get("providers"), dict):
        return data["providers"]
    raise InstallError("%s is missing or invalid: not a complete kit" % posix(path))


def codex_home_content(ctx, provider, region):
    """config.toml text for UB_HOME/codex-homes/<provider> (4.16), rendered by profiles/launch.py (which honors a
    families.json codex_base_url override [U-33]). InstallError when it cannot be rendered."""
    try:
        text = launch_module(ctx).render_codex_home(provider, region)
    except InstallError:
        raise
    except Exception as exc:  # noqa: BLE001 - LaunchError or a template defect: never write other text
        raise InstallError("codex home %s: %s" % (provider, exc))
    return text.replace("\r\n", "\n").encode("utf-8")


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
    pspec = providers_config(ctx).get(provider)
    if not isinstance(pspec, dict) or not pspec.get("token_env"):
        raise InstallError("families.default.json has no provider %s with a token_env: not a complete kit" % provider)
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
    # only --region cn writes base_url.global; a single-URL base_url is the user's own endpoint and stays untouched
    node = base_url_node(fam_path, {} if cur is None and not os.path.exists(fam_path) else cur, provider,
                         allow_url=region != "cn")
    cur_global = node.get("global") if isinstance(node, dict) else None
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
        rows.append(launcher_row_for(ctx, "claude-" + lname, "claude-" + lname,
                                     lambda: launch_args_for(ctx, "claude", provider, region=region, zai_mcp=zai),
                                     warnings))
    if getattr(args, "codex", False):
        if provider == "kimi-code":
            warnings.append("--codex needs the Moonshot Platform key: re-run setup-kimi --provider kimi --codex "
                            "(the kimi-code membership key has no Codex home)")
        else:
            home = os.path.join(ctx.ub_home, "codex-homes", lname)
            cfg = os.path.join(home, "config.toml")
            try:
                data = codex_home_content(ctx, lname, region)
                cur_b = read_bytes(cfg)
                action = "unchanged" if cur_b == data else ("create" if cur_b is None else "update")
                rows.append(new_row("codex", "codex home %s" % lname, action, "copy", cfg, [], _kind="codexhome",
                                    file=cfg, data=data))
            except InstallError as exc:
                warnings.append(str(exc))
                rows.append(new_row("codex", "codex home %s" % lname, "blocked", "copy", cfg, [], _kind="noop",
                                    reason=str(exc)))
            rows.append(launcher_row_for(ctx, "codex-" + lname, "codex-" + lname,
                                         lambda: launch_args_for(ctx, "codex", provider), warnings))
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
                rows.append(native_row(ctx, "codex", "install", codex_home=home, warnings=warnings))
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
    guard_live_runs(ctx, rows, warnings)
    block_downgrade(rows[0], rows)
    plan = assemble_plan(ctx, system, agents, rows, warnings, manual, nxt)
    return confirm_and_apply(ctx, plan, "setup-" + which)


# doctor -------------------------------------------------------------------------------------------------------------


def classify_url(url):
    u = url.lower() if isinstance(url, str) else ""  # a hand-edited settings.json may hold any JSON value
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
    # a hand-edited config.toml may hold any TOML value there (model_provider = 7): only a string names a provider
    return (provider if isinstance(provider, str) else None), (base if isinstance(base, str) else None)


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
        add("env.node", "WARN", "node not found", "install Node.js 22.20+ (needed to install the agent CLIs with npm)")
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
    folders = skill_folders(ctx)
    for skill in STACK_SKILLS:
        for a in AGENTS:
            where = [posix(p) for a2, s, p in folders if a2 == a and s == skill]
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
    # the kit's plugin must load from the staged kit, not from another marketplace of the same name [U-50]
    for a in ("claude-code", "codex"):
        if names.get(a) is None or not plugin_listed(names[a], SKILL, MARKETPLACE):
            continue
        source, text = marketplace_source(ctx, a)
        if source == "foreign":
            add("agent.%s.plugin_source" % a, "WARN", "%s: the plugin %s comes from %s, not from the staged kit %s"
                % (DISPLAY[a], PLUGIN_ID, text, posix(ctx.kit_dir)),
                "run: install.py install --force (replaces it with the staged kit), or remove that plugin")
        elif source == "kit":
            add("agent.%s.plugin_source" % a, "PASS", "%s: the plugin loads from %s" % (DISPLAY[a], text))
        node = json_find(names[a], lambda n: isinstance(n, dict) and n.get("version") and
                         (n.get("id") == PLUGIN_ID or n.get("name") == SKILL))
        if node is not None and os.path.isfile(kv) and str(node.get("version")) != kit_version(ctx.kit_dir):
            add("agent.%s.plugin_version" % a, "WARN", "%s: the plugin reports version %s, the staged kit is %s [U-18]"
                % (DISPLAY[a], node.get("version"), kit_version(ctx.kit_dir)), "run: install.py update")
    # frontmatter, ownership and legacy copies
    seen = set()
    for _a, _s, p in [f for f in folders if f[1] == SKILL]:
        key = os.path.normcase(os.path.abspath(p))
        if key in seen:
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
            if isinstance(rec, dict):
                hashes, err = doctor_hashes(p)
                if err:
                    add("owned.edited:%s" % posix(p), "WARN", "%s could not be checked: %s" % (posix(p), err),
                        "make the file readable (close the program holding it), then run install.py doctor again")
                elif rec != hashes:
                    add("owned.edited:%s" % posix(p), "WARN", "%s was edited after install" % posix(p),
                        "run: install.py update (edited files are backed up first)")
    # trees a killed installer left behind; one holding a SKILL.md is a second, broken ultimate-brainstorm
    for p in leftovers(ctx):
        fm = read_frontmatter(os.path.join(p, "SKILL.md")) or {}
        broken = fm.get("name") == SKILL
        add("leftover:%s" % posix(p), "FAIL" if broken else "WARN",
            "%s is an installer leftover%s" % (posix(p), " holding a SKILL.md named %s: an agent may load it" % SKILL
                                               if broken else ""),
            "run: install.py install (it removes installer leftovers), or delete the folder")
    if os.path.isdir(os.path.join(ctx.home, ".kimi")):
        add("legacy.kimi_home", "WARN", "%s exists (legacy kimi-cli)" % posix(os.path.join(ctx.home, ".kimi")),
            "after moving to Kimi Code v2 run: kimi migrate")
    # endpoints (5.5): which family the CLIs really serve
    settings = load_json_file(os.path.join(ctx.homes["claude-code"], "settings.json"), {}) or {}
    env = settings.get("env") if isinstance(settings, dict) else None
    url = env.get("ANTHROPIC_BASE_URL") if isinstance(env, dict) else None
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
        found = [a for a in AGENTS if any(a2 == a and s == skill for a2, s, _p in folders)]
        add("stack.%s" % skill, "PASS" if found else "WARN",
            ("present for %s" % ", ".join(found)) if found else "%s not found in any agent's skills folder" % skill,
            "install.py install (component mattpocock-grilling)")
    # [U-27] component skills installed from a pinned commit: their hashes were recorded at install time
    for c in (ctx.manifest or {}).get("components", []):
        for skill, rec in sorted(((c or {}).get("files") or {}).items()):
            p = ((c.get("paths") or {}).get(skill)) or ""
            if not os.path.isdir(p):
                continue
            hashes, err = doctor_hashes(p)
            if err:
                add("stack.%s.drift:%s" % (skill, posix(p)), "WARN", "%s could not be checked: %s" % (posix(p), err),
                    "make the file readable (close the program holding it), then run install.py doctor again")
            elif rec != hashes:
                # the commit this folder came from: a kept folder keeps its own (commits), older records have one
                commit = (c.get("commits") or {}).get(skill) or c.get("commit") or c.get("ref")
                add("stack.%s.drift:%s" % (skill, posix(p)), "WARN",
                    "%s changed since it was installed from %s at %s" % (posix(p), c.get("id"), commit),
                    "if you did not update it yourself, reinstall it: delete the folder, then run install.py install")
    # a component skill folder with no record (kit 2.0.x installed it unpinned with npx, or it was copied by hand) is
    # compared with the content pin instead
    recorded = set(os.path.normcase(os.path.abspath(p)) for c in (ctx.manifest or {}).get("components", [])
                   if isinstance(c, dict) for p in (c.get("paths") or {}).values() if isinstance(p, str))
    pins = {skill: (cid, pin, c.get("commit")) for cid, c in sorted(ctx.components["components"].items())
            for skill, pin in sorted(((c.get("archive") or {}).get("skills") or {}).items())}
    for _a, skill, p in folders:
        key = os.path.normcase(os.path.abspath(p))
        if skill not in pins or key in recorded:
            continue
        recorded.add(key)  # once per folder (Codex and Kimi share ~/.agents/skills)
        cid, pin, commit = pins[skill]
        hashes, err = doctor_hashes(p)
        if err:
            add("stack.%s.unpinned:%s" % (skill, posix(p)), "WARN",
                "%s could not be compared with the pinned content of %s: %s" % (posix(p), cid, err),
                "make the file readable (close the program holding it), then run install.py doctor again")
        elif tree_sha256(hashes) != pin["sha256"]:
            add("stack.%s.unpinned:%s" % (skill, posix(p)), "WARN",
                "%s is not the pinned content of %s (commit %s): the kit did not install it from the pinned archive "
                "(kit 2.0.x installed it unpinned with npx, or it was copied or edited by hand)"
                % (posix(p), cid, (commit or "")[:12]),
                "unless it is your own skill, delete the folder, then run install.py install")
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
    folders = skill_folders(ctx)
    for a in AGENTS:
        for _a, skill, p in [f for f in folders if f[0] == a]:
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
    p.add_argument("--require-attestation", dest="require_attestation", action="store_true")
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
