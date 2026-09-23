"""Process runner: argv, cwd, env, stdin, timeout, tree kill (KIT_SPEC 3.1 item 2, 5.4, 12.2).

run(argv, cwd, env, stdin_bytes, timeout_s) -> ProcResult(returncode, stdout_bytes, stderr_bytes, timed_out)

This is the single process seam: every backend starts its model CLI through run(), and B2 unit tests mock it.

Rules:
- never shell=True; argv[0] is resolved with which() below (against the child env's PATH, never the current folder)
  and passed as a full path;
- when the resolved executable is a .cmd or .bat file, every argument is checked: any of  " & | < > ^ % !  CR LF
  fails with UnsafeArgument before anything starts (cmd.exe would re-parse them);
- stdin is the given bytes (or DEVNULL); stdout/stderr are captured as bytes (decoding is the caller's job);
- on timeout the whole process tree is killed: Windows `taskkill /PID <pid> /T /F`; POSIX killpg SIGTERM, then
  SIGKILL after the grace period (default 5 s);
- the child runs in its own process group / session, and on Windows without a console window (a detached worker
  has no console, so a console child would otherwise pop one up).
"""

import collections
import os
import shutil
import signal
import subprocess
import sys
import time

__all__ = ["ProcResult", "ProcError", "ExecutableNotFound", "UnsafeArgument", "CMD_UNSAFE_CHARS",
           "run", "resolve_exe", "which", "system_tool", "check_cmd_args", "kill_tree", "pid_alive", "IS_WINDOWS"]

IS_WINDOWS = os.name == "nt"

ProcResult = collections.namedtuple("ProcResult", ["returncode", "stdout_bytes", "stderr_bytes", "timed_out"])

CMD_UNSAFE_CHARS = '"&|<>^%!\r\n'

_CREATE_NEW_PROCESS_GROUP = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
_CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
_GRACE_S = 5.0
_DRAIN_S = 10.0


class ProcError(Exception):
    """Base class for runner errors raised before a process starts."""


class ExecutableNotFound(ProcError, FileNotFoundError):
    """argv[0] could not be resolved to an executable."""


class UnsafeArgument(ProcError, ValueError):
    """An argument cannot pass safely through a .cmd/.bat shim."""


def _env_get(env, name):
    if env is None:
        env = os.environ
    if IS_WINDOWS:
        up = name.upper()
        for k, v in env.items():
            if k.upper() == up:
                return v
        return None
    return env.get(name)


def which(name, path=None):
    """shutil.which without the implicit current-directory lookup. On Windows, Python 3.9-3.11 search the current
    folder before PATH, so a `codex.cmd` planted in an untrusted repository would run. Only absolute PATH entries are
    searched (empty, '.' and other relative entries are cwd-relative and dropped)."""
    if not name:
        return None
    if path is None:
        path = _env_get(None, "PATH") or os.defpath
    dirs = []
    for d in str(path).split(os.pathsep):
        d = d.strip().strip('"')
        if not d:
            continue
        d = os.path.expanduser(d)
        if not os.path.isabs(d):
            continue
        dirs.append(d)
    if IS_WINDOWS:
        pathext = [e.lower() for e in (os.environ.get("PATHEXT") or ".COM;.EXE;.BAT;.CMD").split(os.pathsep) if e]
        if os.path.splitext(name)[1].lower() in pathext:
            cands = [name]
        else:
            cands = [name + e for e in pathext]
    else:
        cands = [name]
    seen = set()
    for d in dirs:
        key = os.path.normcase(os.path.abspath(d))
        if key in seen:
            continue
        seen.add(key)
        for c in cands:
            p = os.path.join(d, c)
            if os.path.isfile(p) and (IS_WINDOWS or os.access(p, os.X_OK)):
                return os.path.abspath(p)
    return None


def system_tool(name):
    """Absolute path of a Windows system tool (icacls, taskkill, whoami) in %SystemRoot%\\System32, never a PATH
    lookup; elsewhere a which() lookup. None when absent."""
    if IS_WINDOWS:
        root = os.environ.get("SystemRoot") or os.environ.get("SYSTEMROOT") or os.environ.get("windir") or "C:\\Windows"
        p = os.path.join(root, "System32", name + ".exe")
        return p if os.path.isfile(p) else None
    return which(name)


def resolve_exe(name, env=None):
    """Full path of an executable, searched on the PATH of env (default: this process's PATH); None if absent.
    The current folder is never searched implicitly (see which())."""
    if not name:
        return None
    if os.path.isabs(name) or os.sep in name or (os.altsep and os.altsep in name):
        if os.path.isfile(name):
            return os.path.abspath(name)
        found = shutil.which(name)
        return os.path.abspath(found) if found else None
    return which(name, path=_env_get(env, "PATH"))


def check_cmd_args(exe_path, args):
    """Raise UnsafeArgument when exe_path is a .cmd/.bat file and an argument (or the shim's own path) holds a cmd.exe
    metacharacter."""
    if not str(exe_path).lower().endswith((".cmd", ".bat")):
        return
    bad = sorted(set(ch for ch in str(exe_path) if ch in CMD_UNSAFE_CHARS))
    if bad:
        raise UnsafeArgument(
            "the path of %s contains %s, which cmd.exe re-parses; install the CLI under a folder without these "
            "characters" % (os.path.basename(str(exe_path)), ", ".join(repr(c) for c in bad)))
    # Empty arguments are allowed here; whether `--tools ""` survives an npm .cmd shim is the backend's call. # [U-13]
    for i, arg in enumerate(args):
        bad = sorted(set(ch for ch in str(arg) if ch in CMD_UNSAFE_CHARS))
        if bad:
            shown = ", ".join("CR" if c == "\r" else "LF" if c == "\n" else repr(c) for c in bad)
            raise UnsafeArgument(
                "argument %d for %s contains %s, which cannot pass safely through a .cmd/.bat shim; "
                "put this value in a file instead" % (i + 1, os.path.basename(str(exe_path)), shown))


def _child_env(env):
    if env is None:
        return None
    out = {}
    for k, v in env.items():
        if not isinstance(k, str) or not isinstance(v, str):
            raise TypeError("environment entries must be str (bad entry: %r)" % (k,))
        out[k] = v
    if IS_WINDOWS and _env_get(out, "SYSTEMROOT") is None and os.environ.get("SYSTEMROOT"):
        out["SYSTEMROOT"] = os.environ["SYSTEMROOT"]  # many Windows programs (Python too) fail without it
    if IS_WINDOWS and _env_get(out, "NoDefaultCurrentDirectoryInExePath") is None:
        out["NoDefaultCurrentDirectoryInExePath"] = "1"  # cmd.exe shims must not run programs from the cwd either
    return out


def _popen_kwargs():
    if IS_WINDOWS:
        return {"creationflags": _CREATE_NEW_PROCESS_GROUP | _CREATE_NO_WINDOW}
    return {"start_new_session": True}


def run(argv, cwd=None, env=None, stdin_bytes=None, timeout_s=None):
    """Run argv and wait. Returns ProcResult(returncode, stdout_bytes, stderr_bytes, timed_out).

    cwd: folder for the child (None = inherit). env: the complete child environment (None = inherit).
    stdin_bytes: bytes to feed on stdin (None = DEVNULL). timeout_s: seconds (None = no limit); on expiry the
    process tree is killed and timed_out is True.
    Raises ExecutableNotFound, UnsafeArgument, TypeError (bad argv/env) or OSError (start failure).
    """
    if not argv or not all(isinstance(a, str) for a in argv):
        raise TypeError("argv must be a non-empty list of str")
    child_env = _child_env(env)
    exe = resolve_exe(argv[0], child_env)
    if exe is None:
        raise ExecutableNotFound("executable not found: %s" % argv[0])
    args = list(argv[1:])
    check_cmd_args(exe, args)
    if isinstance(stdin_bytes, str):
        stdin_bytes = stdin_bytes.encode("utf-8")
    p = subprocess.Popen(
        [exe] + args,
        cwd=os.fspath(cwd) if cwd is not None else None,
        env=child_env,
        stdin=subprocess.PIPE if stdin_bytes is not None else subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        **_popen_kwargs()
    )
    timed_out = False
    try:
        try:
            out, err = p.communicate(input=stdin_bytes, timeout=timeout_s)
        except subprocess.TimeoutExpired:
            timed_out = True
            kill_tree(p.pid, proc=p)
            try:
                out, err = p.communicate(timeout=_DRAIN_S)
            except subprocess.TimeoutExpired as e:
                # A grandchild outside the tree still holds the pipes: give up reading.
                out, err = e.output or b"", e.stderr or b""
                _close_pipes(p)
                try:
                    p.kill()
                    p.wait(timeout=_GRACE_S)
                except (OSError, subprocess.TimeoutExpired):
                    pass
    except BaseException:
        if p.poll() is None:
            kill_tree(p.pid, proc=p)
        _close_pipes(p)
        raise
    rc = p.returncode if p.returncode is not None else -9
    return ProcResult(rc, out or b"", err or b"", timed_out)


def _close_pipes(p):
    for f in (p.stdin, p.stdout, p.stderr):
        try:
            if f:
                f.close()
        except OSError:
            pass


def _taskkill_path():
    found = system_tool("taskkill")
    if found:
        return found
    root = os.environ.get("SYSTEMROOT") or os.environ.get("SystemRoot") or r"C:\Windows"
    return os.path.join(root, "System32", "taskkill.exe")


def kill_tree(pid, grace_s=_GRACE_S, proc=None):
    """Kill pid and all its descendants. Never raises for a process that is already gone.

    Windows: taskkill /PID <pid> /T /F. POSIX: SIGTERM to the process group, wait up to grace_s, then SIGKILL.
    proc: the Popen object when available (used to reap the child).
    """
    if not pid:
        return
    if IS_WINDOWS:
        try:
            subprocess.run([_taskkill_path(), "/PID", str(int(pid)), "/T", "/F"],
                           stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           timeout=30, creationflags=_CREATE_NO_WINDOW)
        except (OSError, subprocess.SubprocessError):
            pass
        if proc is not None:
            try:
                proc.wait(timeout=grace_s)
            except subprocess.TimeoutExpired:
                try:
                    proc.kill()
                except OSError:
                    pass
        return
    try:
        pgid = os.getpgid(pid)
    except (ProcessLookupError, PermissionError, OSError):
        pgid = None
    if pgid is not None and pgid == os.getpgid(0):
        pgid = None  # never signal our own group
    _signal(pid, pgid, signal.SIGTERM)
    deadline = time.monotonic() + grace_s
    while time.monotonic() < deadline:
        if proc is not None:
            if proc.poll() is not None and not _group_alive(pgid):
                break
        elif not _group_alive(pgid) and not pid_alive(pid):
            break
        time.sleep(0.05)
    _signal(pid, pgid, getattr(signal, "SIGKILL", signal.SIGTERM))
    if proc is not None:
        try:
            proc.wait(timeout=grace_s)
        except subprocess.TimeoutExpired:
            pass


def _signal(pid, pgid, sig):
    try:
        if pgid is not None:
            os.killpg(pgid, sig)
        else:
            os.kill(pid, sig)
    except (ProcessLookupError, PermissionError, OSError):
        pass


def _group_alive(pgid):
    if pgid is None:
        return False
    try:
        os.killpg(pgid, 0)
        return True
    except (ProcessLookupError, PermissionError, OSError):
        return False


def process_start_time(pid):
    """Epoch seconds when process pid started, or None when unknown (Windows: GetProcessTimes; Linux: /proc)."""
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return None
    if pid <= 0:
        return None
    if IS_WINDOWS:
        try:
            import ctypes
            from ctypes import wintypes
            k32 = ctypes.WinDLL("kernel32", use_last_error=True)
            k32.OpenProcess.restype = wintypes.HANDLE
            k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
            k32.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
            k32.GetProcessTimes.restype = wintypes.BOOL
            k32.CloseHandle.argtypes = [wintypes.HANDLE]
            handle = k32.OpenProcess(0x1000, False, pid)
            if not handle:
                return None
            try:
                t = [wintypes.FILETIME() for _ in range(4)]
                if not k32.GetProcessTimes(handle, *[ctypes.byref(x) for x in t]):
                    return None
                ticks = (t[0].dwHighDateTime << 32) | t[0].dwLowDateTime
                return ticks / 1e7 - 11644473600.0
            finally:
                k32.CloseHandle(handle)
        except (OSError, AttributeError, ValueError):
            return None
    stat = "/proc/%d/stat" % pid
    if sys.platform.startswith("linux") and os.path.exists(stat):
        try:
            with open(stat, "r") as f:
                fields = f.read().rsplit(")", 1)[-1].split()
            ticks = int(fields[19])
            hz = os.sysconf("SC_CLK_TCK")
            with open("/proc/stat", "r") as f:
                btime = next(int(line.split()[1]) for line in f if line.startswith("btime"))
            return btime + ticks / float(hz)
        except (OSError, ValueError, IndexError, StopIteration):
            return None
    return None


def pid_alive(pid):
    """Best-effort liveness check for a pid (True when it runs, False when it exited or never existed)."""
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    if IS_WINDOWS:
        import ctypes
        from ctypes import wintypes
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.OpenProcess.restype = wintypes.HANDLE
        k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        k32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        k32.GetExitCodeProcess.restype = wintypes.BOOL
        k32.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = k32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return ctypes.get_last_error() == 5  # access denied: it exists
        try:
            code = wintypes.DWORD()
            if not k32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return False
            return code.value == 259  # STILL_ACTIVE
        finally:
            k32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    stat = "/proc/%d/stat" % pid
    if sys.platform.startswith("linux") and os.path.exists(stat):
        try:
            with open(stat, "r") as f:
                fields = f.read().rsplit(")", 1)[-1].split()
            if fields and fields[0] == "Z":
                return False
        except OSError:
            pass
    return True
