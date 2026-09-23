"""Isolated home folders for tests (KIT_SPEC 11.1). Owner: B4.

    with TmpHome(tools=("claude", "codex")) as th:
        proc = paths.run_py(paths.INSTALL_PY, ["plan", "--json"], env=th.env, cwd=th.project)
        calls = th.fake_calls("claude")

Settings (11.1): HOME, USERPROFILE, APPDATA, LOCALAPPDATA, XDG_CONFIG_HOME, CLAUDE_CONFIG_DIR, CODEX_HOME,
KIMI_CODE_HOME and UB_HOME point into a fresh temporary directory; PATH = the fake bin folder + the directory of
sys.executable (+ C:/Windows/System32 on Windows); UB_FAKE_PY = sys.executable. The environment is built from scratch
(only OS plumbing variables are copied), so no real key, agent home or endpoint of the developer leaks in.

Layout under th.root (a resolved path that contains a space, so path quoting is always exercised):
    home/                    HOME / USERPROFILE (UB_HOME = home/.ultimate-brainstorm, not created)
    bin/                     fake CLIs (shims.py)
    project/                 a working folder for commands
    tmp/                     TEMP / TMP / TMPDIR
    fake.log, scenario.json  UB_FAKE_LOG, UB_FAKE_SCENARIO
"""

import contextlib
import json
import os
import shutil
import sys
import tempfile
import time

import shims

_COPY_WINDOWS = ("SYSTEMROOT", "SystemRoot", "WINDIR", "COMSPEC", "PATHEXT", "SYSTEMDRIVE", "PROCESSOR_ARCHITECTURE",
                 "NUMBER_OF_PROCESSORS", "OS", "USERNAME", "USERDOMAIN", "ProgramData", "ProgramFiles",
                 "ProgramFiles(x86)", "ProgramW6432", "CommonProgramFiles")
_COPY_POSIX = ("USER", "LOGNAME", "LANG", "LC_ALL", "LC_CTYPE", "SHELL")


def _elevated():
    try:
        import ctypes
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:  # noqa: BLE001
        return False


class TmpHome(object):
    def __init__(self, tools=shims.DEFAULT_TOOLS, scenario=None, versions=None, extra_env=None, agent_homes=True,
                 space=True, prefix="ub-test-"):
        self.tools = tuple(tools or ())
        self.scenario = list(scenario or [])
        self.versions = dict(versions or {})
        self.extra_env = dict(extra_env or {})
        self.agent_homes = agent_homes
        self.space = space
        self.prefix = prefix
        self.env = {}

    # ------------------------------------------------------------ lifecycle
    def __enter__(self):
        base = os.path.realpath(tempfile.mkdtemp(prefix=self.prefix))
        self._base = base
        self.root = os.path.join(base, "ub root") if self.space else base
        self.home = os.path.join(self.root, "home")
        self.bin = os.path.join(self.root, "bin")
        self.project = os.path.join(self.root, "project")
        self.tmp = os.path.join(self.root, "tmp")
        for d in (self.home, self.bin, self.project, self.tmp):
            os.makedirs(d, exist_ok=True)
        self.ub_home = os.path.join(self.home, ".ultimate-brainstorm")
        self.claude_home = os.path.join(self.home, ".claude")
        self.codex_home = os.path.join(self.home, ".codex")
        self.kimi_home = os.path.join(self.home, ".kimi-code")
        self.log = os.path.join(self.root, "fake.log")
        self.scenario_path = os.path.join(self.root, "scenario.json")
        if self.tools:
            shims.install_fakes(self.bin, self.tools)
        self.env = self._build_env()
        self.set_scenario(self.scenario)
        return self

    def __exit__(self, *exc):
        if os.environ.get("UB_KEEP_TMP") == "1":
            sys.stderr.write("UB_KEEP_TMP: kept %s\n" % self._base)
            return False
        rmtree(self._base)
        return False

    def _build_env(self):
        env = {}
        names = _COPY_WINDOWS if os.name == "nt" else _COPY_POSIX
        for k in names:
            if k in os.environ:
                env[k] = os.environ[k]
        path = [self.bin, shims.python_dir()]
        if os.name == "nt":
            sysroot = os.environ.get("SYSTEMROOT", "C:\\Windows")
            path.append(os.path.join(sysroot, "System32"))
        env.update({
            "HOME": self.home, "USERPROFILE": self.home,
            "APPDATA": os.path.join(self.home, "AppData", "Roaming"),
            "LOCALAPPDATA": os.path.join(self.home, "AppData", "Local"),
            "XDG_CONFIG_HOME": os.path.join(self.home, ".config"),
            "TEMP": self.tmp, "TMP": self.tmp, "TMPDIR": self.tmp,
            "PATH": os.pathsep.join(path),
            "UB_HOME": self.ub_home,
            "UB_FAKE_PY": sys.executable,
            "UB_FAKE_LOG": self.log,
            "UB_FAKE_SCENARIO": self.scenario_path,
            "PYTHONDONTWRITEBYTECODE": "1",
        })
        if os.name == "nt":
            drive, rest = os.path.splitdrive(self.home)
            env["HOMEDRIVE"], env["HOMEPATH"] = drive, rest
            if _elevated():
                env["UB_ALLOW_ROOT"] = "1"  # CI runners are elevated; install.py refuses admin otherwise
        if self.agent_homes:
            env["CLAUDE_CONFIG_DIR"] = self.claude_home
            env["CODEX_HOME"] = self.codex_home
            env["KIMI_CODE_HOME"] = self.kimi_home
        env.update({k: str(v) for k, v in self.extra_env.items() if v is not None})
        for k, v in self.extra_env.items():
            if v is None:
                env.pop(k, None)
        return env

    # ------------------------------------------------------------ scenario and log
    def set_scenario(self, rules):
        """Replace the scenario rules; version rules from `versions` are appended after them."""
        self.scenario = list(rules or [])
        self._write_scenario()

    def set_versions(self, versions):
        self.versions = dict(versions or {})
        self._write_scenario()

    def add_rules(self, rules, first=True):
        self.scenario = list(rules) + self.scenario if first else self.scenario + list(rules)
        self._write_scenario()

    def _write_scenario(self):
        rules = list(self.scenario)
        for tool, version in self.versions.items():
            rules.append({"tool": tool, "argv_regex": r"^(--version|-V)\b", "action": "static",
                          "stdout": version + "\n"})
        with open(self.scenario_path, "w", encoding="utf-8", newline="\n") as f:
            json.dump(rules, f, indent=1)

    def fake_calls(self, tool=None):
        out = []
        if not os.path.isfile(self.log):
            return out
        with open(self.log, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except ValueError:
                    continue
                if tool is None or entry.get("tool") == tool:
                    out.append(entry)
        return out

    def log_text(self):
        if not os.path.isfile(self.log):
            return ""
        with open(self.log, "r", encoding="utf-8") as f:
            return f.read()

    def clear_log(self):
        for p in (self.log, self.log + ".hits.json"):
            if os.path.exists(p):
                os.remove(p)

    # ------------------------------------------------------------ helpers
    def mkdir(self, *parts):
        p = os.path.join(self.root, *parts)
        os.makedirs(p, exist_ok=True)
        return p

    def write(self, path, text):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        return path

    def kimi_login(self):
        """Make the fake Kimi Code CLI look logged in (5.5: $KIMI_CODE_HOME/credentials/)."""
        return self.mkdir("home", ".kimi-code", "credentials")

    @contextlib.contextmanager
    def patched_environ(self):
        """Temporarily replace os.environ with self.env (for in-process imports of product code)."""
        saved = dict(os.environ)
        os.environ.clear()
        os.environ.update(self.env)
        try:
            yield self
        finally:
            os.environ.clear()
            os.environ.update(saved)


def rmtree(path):
    """Remove a tree, retrying on Windows file locks (antivirus, slow process exit)."""
    def onerror(func, p, _exc):
        try:
            os.chmod(p, 0o700)
            func(p)
        except OSError:
            pass
    for attempt in range(6):
        if not os.path.exists(path):
            return
        if sys.version_info >= (3, 12):
            shutil.rmtree(path, onexc=onerror)
        else:
            shutil.rmtree(path, onerror=onerror)
        if not os.path.exists(path):
            return
        time.sleep(0.5 * (attempt + 1))
