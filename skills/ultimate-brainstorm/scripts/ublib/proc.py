"""Process runner: argv, cwd, env, stdin, timeout, tree kill (KIT_SPEC 3.1 item 2, 5.4, 12.2).

run(argv, cwd, env, stdin_bytes, timeout_s, max_stdout=STDOUT_CAP_BYTES, on_line=None)
    -> ProcResult(returncode, stdout_bytes, stderr_bytes, timed_out, overflow)

This is the single process seam: every backend starts its model CLI through run(), and B2 unit tests mock it.

Rules:
- never shell=True; argv[0] is resolved with which() below (against the child env's PATH, never the current folder)
  and passed as a full path;
- when the resolved executable is a .cmd or .bat file, every argument is checked: any of  " & | < > ^ % !  CR LF
  fails with UnsafeArgument before anything starts (cmd.exe would re-parse them);
- stdin is the given bytes (or DEVNULL), written from a thread; stdout/stderr are read by threads as bytes (decoding
  is the caller's job). stdout is capped (8 MB by default): past the cap the process tree is killed, `overflow` is
  True and the first max_stdout bytes are returned. Only the last 64 KB of stderr are kept;
- streaming (on_line given, for the JSONL CLIs): stdout is not buffered; every line (without its newline) is passed to
  on_line(line_bytes, whole) as it arrives, on the reader thread and in order. A line longer than LINE_CAP_BYTES is
  passed once as its first LINE_CAP_BYTES bytes with whole=False (the rest of it is dropped). max_stdout then caps the
  whole stream (past it: tree killed, `overflow`) and stdout_bytes holds only its first STREAM_HEAD_BYTES. on_line is
  never called after run() returns; an exception it raises stops further calls and is raised by run() once the child
  is gone;
- completion is the child's exit, not the end of its pipes: a descendant that inherited the pipes cannot hold run()
  up. After the exit the readers get 1 s to drain; then whatever is left of the child's tree is killed (Windows: its
  Job Object; POSIX: its process group) and the bytes read so far are returned;
- on timeout the whole process tree is killed: Windows `taskkill /PID <pid> /T /F` and the child's Job Object; POSIX
  killpg SIGTERM, then SIGKILL after the grace period (5 s; 1 s when run() itself is interrupted, e.g. by `ub stop`,
  so a worker always finishes its own cleanup before the stop's longer grace runs out);
- the child runs in its own process group / session, and on Windows without a console window (a detached worker
  has no console, so a console child would otherwise pop one up) and inside a Job Object with
  JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE: its tree also dies with this process;
- in the main thread, SIGTERM / SIGINT / SIGBREAK are held from before the child starts until it is recorded (Job
  Object, spawn hook) inside the block whose error path kills it: a stop that lands while the child starts kills the
  child instead of leaving it running unrecorded in its own session;
- kill_tree signals a process group only when the target leads it (POSIX): a worker that shares its launcher's group
  (an attached `family.py batch` worker) is stopped alone, never with its launcher and siblings.

legacy_driver_live (with process_args and runs_ub_on) is the one rule by which the engine and the installer tell a
live kit 2.0.x driver from its .ub/lock.json record (KIT_SPEC 6.3, 10.4 item 8).
"""

import calendar
import collections
import os
import shutil
import signal
import subprocess
import sys
import threading
import time

__all__ = ["ProcResult", "ProcError", "ExecutableNotFound", "UnsafeArgument", "CMD_UNSAFE_CHARS",
           "run", "resolve_exe", "which", "system_tool", "check_cmd_args", "kill_tree", "pid_alive", "IS_WINDOWS",
           "process_identity", "same_process", "set_spawn_hook", "STDOUT_CAP_BYTES", "STDERR_TAIL_BYTES",
           "ABORT_GRACE_S", "LINE_CAP_BYTES", "STREAM_HEAD_BYTES", "legacy_driver_live", "process_args",
           "runs_ub_on", "LEGACY_DRIVER_STALE_S"]

IS_WINDOWS = os.name == "nt"
LEGACY_DRIVER_STALE_S = 120  # a kit 2.0.x driver's .ub/lock.json beat this recent is live (legacy_driver_live)

# overflow (a default keeps four-field results valid): stdout passed max_stdout and the process tree was killed
ProcResult = collections.namedtuple("ProcResult", ["returncode", "stdout_bytes", "stderr_bytes", "timed_out",
                                                   "overflow"], defaults=(False,))

CMD_UNSAFE_CHARS = '"&|<>^%!\r\n'

STDOUT_CAP_BYTES = 8 * 1024 * 1024  # run()'s default stdout cap
STDERR_TAIL_BYTES = 64 * 1024       # run() keeps only this tail of stderr
ABORT_GRACE_S = 1.0                 # SIGTERM -> SIGKILL grace when run() itself is interrupted (e.g. ub stop)
# Streaming mode (on_line): the longest stdout line passed whole: 6 x the 2 MB answer cap (validate.OUTPUT_CAP_BYTES,
# JSON-escaped at worst 6 bytes per character) + 64 KB; and the head of the stream kept as stdout_bytes.
LINE_CAP_BYTES = 6 * 2 * 1024 * 1024 + 64 * 1024
STREAM_HEAD_BYTES = 1024 * 1024
_HOLD_SIGNALS = ("SIGTERM", "SIGINT", "SIGBREAK")

_CREATE_NEW_PROCESS_GROUP = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
_CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
_GRACE_S = 5.0
_LINGER_S = 1.0   # after the child's exit its readers get this long (twice: before and after the rest of the tree dies)
_CHUNK = 65536
_PROCESS_TERMINATE = 0x0001
_PROCESS_SET_QUOTA = 0x0100
_PROCESS_QUERY_LIMITED = 0x1000
_JOB_EXTENDED_LIMITS = 9          # JobObjectExtendedLimitInformation
_JOB_BREAKAWAY_OK = 0x0800        # a descendant that explicitly asks to break away may (it then leaves our control)
_JOB_KILL_ON_CLOSE = 0x2000
_SPAWN_HOOK = [None]
_BOOT_ID = []


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


def set_spawn_hook(fn):
    """fn(pid, ident) is called right after run() starts a child and fn(None, None) once run() is done with it. The
    worker records its backend process in its running marker this way, so `ub stop` and a relaunch can stop that
    process even when the worker itself was killed hard. None removes the hook; errors in fn are ignored."""
    _SPAWN_HOOK[0] = fn


def _notify_spawn(pid):
    fn = _SPAWN_HOOK[0]
    if fn is None:
        return
    try:
        fn(pid, process_identity(pid) if pid else None)
    except Exception:  # noqa: BLE001 - bookkeeping must never break a call
        pass


class _SignalHold(object):
    """In the main thread (the only one that runs Python signal handlers): from creation until release(), SIGTERM,
    SIGINT and SIGBREAK are recorded instead of handled; release() restores the handlers and replays what came in, so
    a handler that raises (SystemExit from `ub stop`, KeyboardInterrupt) does so where run() can kill the child. In any
    other thread nothing is held."""

    def __init__(self):
        self.saved, self.caught = {}, []
        if threading.current_thread() is not threading.main_thread():
            return
        for name in _HOLD_SIGNALS:
            sig = getattr(signal, name, None)
            try:
                old = signal.getsignal(sig) if sig is not None else None
                if old is None or old == signal.SIG_IGN:
                    continue  # not set from Python, or ignored: nothing to hold
                signal.signal(sig, self._record)
            except (ValueError, OSError, RuntimeError, TypeError):
                continue
            self.saved[sig] = old

    def _record(self, signum, _frame):
        if signum not in self.caught:
            self.caught.append(signum)

    def release(self):
        saved, self.saved = self.saved, {}
        caught, self.caught = self.caught, []
        for sig, old in saved.items():
            try:
                signal.signal(sig, old)
            except (ValueError, OSError, RuntimeError, TypeError):
                pass
        for sig in caught:
            old = saved.get(sig)
            if callable(old):
                old(sig, None)  # may raise: that is the point
            elif old == signal.SIG_DFL:
                signal.raise_signal(sig)


def run(argv, cwd=None, env=None, stdin_bytes=None, timeout_s=None, max_stdout=STDOUT_CAP_BYTES, on_line=None):
    """Run argv and wait for it to exit. Returns ProcResult(returncode, stdout_bytes, stderr_bytes, timed_out,
    overflow).

    cwd: folder for the child (None = inherit). env: the complete child environment (None = inherit).
    stdin_bytes: bytes to feed on stdin (None = DEVNULL). timeout_s: seconds (None = no limit); on expiry the
    process tree is killed and timed_out is True. max_stdout: stdout byte cap (None = no cap); past it the process
    tree is killed, overflow is True and stdout_bytes holds the first max_stdout bytes. on_line: streaming mode (module
    note): stdout lines go to on_line(line, whole) as they arrive and stdout_bytes is only the head of the stream.
    Raises ExecutableNotFound, UnsafeArgument, TypeError (bad argv/env) or OSError (start failure), and whatever
    on_line raised.
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
    hold = _SignalHold()
    try:
        p = subprocess.Popen(
            [exe] + args,
            cwd=os.fspath(cwd) if cwd is not None else None,
            env=child_env,
            stdin=subprocess.PIPE if stdin_bytes is not None else subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,
            **_popen_kwargs()
        )
    except BaseException:
        hold.release()
        raise
    job = None
    timed_out = False
    readers, owned = [], []  # owned: pipes a thread reads or writes (only that thread closes them)
    try:
        job = _Job.contain(p.pid) if IS_WINDOWS else None
        _notify_spawn(p.pid)
        hold.release()  # a stop that came in since the start is handled here, where the except below kills the child
        out = _Reader(p.stdout, cap=max_stdout, on_line=on_line)
        owned.append(p.stdout)
        readers.append(out)
        readers.append(_Reader(p.stderr, tail=STDERR_TAIL_BYTES))
        owned.append(p.stderr)
        if stdin_bytes is not None:
            threading.Thread(target=_feed, args=(p.stdin, stdin_bytes), name="ub-proc-stdin", daemon=True).start()
            owned.append(p.stdin)
        deadline = None if timeout_s is None else time.monotonic() + float(timeout_s)
        while not _exited(p, 0.1 if deadline is None else min(0.1, max(0.0, deadline - time.monotonic()))):
            if out.overflow:
                kill_tree(p.pid, grace_s=ABORT_GRACE_S, proc=p)
                break
            if deadline is not None and time.monotonic() >= deadline:
                timed_out = True
                kill_tree(p.pid, proc=p)
                break
        _drain(p, job, readers)
    except BaseException:
        if p.poll() is None:
            kill_tree(p.pid, grace_s=ABORT_GRACE_S, proc=p)
        _kill_rest(p, job)
        _close_pipes(p, owned)
        raise
    finally:
        for r in readers:
            r.finish()  # an abandoned reader (a pipe holder outside the tree) reports nothing after this
        if job is not None:
            job.close()
        _notify_spawn(None)
        hold.release()
    if out.error is not None:
        raise out.error
    rc = p.returncode if p.returncode is not None else -9
    return ProcResult(rc, out.data(), readers[1].data(), timed_out, out.overflow)


def _exited(p, timeout):
    try:
        p.wait(timeout=timeout)
        return True
    except subprocess.TimeoutExpired:
        return False


def _join(readers, timeout):
    end = time.monotonic() + timeout
    for r in readers:
        r.thread.join(max(0.0, end - time.monotonic()))


def _drain(p, job, readers):
    """After the child is gone: its readers get _LINGER_S to reach EOF; then whatever is left of its tree is killed (a
    descendant that kept the pipes open, or any other leftover) and they get _LINGER_S more. A reader still blocked
    after that (the pipe holder is outside the tree) stays with its daemon thread; the bytes read so far count."""
    _join(readers, _LINGER_S)
    _kill_rest(p, job)
    _join(readers, _LINGER_S)


def _kill_rest(p, job):
    """Kill what is left of the child's tree once the child itself is gone: Windows terminates its Job Object (which
    reaches descendants whose parent has exited; taskkill /T cannot); POSIX kills its process group."""
    if job is not None:
        job.terminate()
    elif not IS_WINDOWS and _group_alive(p.pid):
        _signal(p.pid, p.pid, getattr(signal, "SIGKILL", signal.SIGTERM))  # start_new_session: pgid == pid


def _close_pipes(p, owned=()):
    """Close the child's pipes that no thread owns (a reader or writer thread closes its own pipe when it is done:
    on Windows, closing a pipe while another thread's read on it is pending blocks until that read returns)."""
    for f in (p.stdin, p.stdout, p.stderr):
        if not f or any(f is o for o in owned):
            continue
        try:
            f.close()
        except OSError:
            pass


def _feed(f, data):
    """Write the child's stdin, then close it (on its own thread: a child that does not read must not stall run())."""
    try:
        view = memoryview(data)
        while view:
            n = f.write(view)
            if not n:
                break
            view = view[n:]
    except (OSError, ValueError):
        pass  # the child exited or closed its stdin
    finally:
        try:
            f.close()
        except OSError:
            pass


class _Reader(object):
    """Reads one pipe of the child on a daemon thread until EOF, keeping at most `cap` bytes (the head; `overflow` is
    set when more arrived) or only the last `tail` bytes; with on_line, it passes the stream on line by line and keeps
    only its first STREAM_HEAD_BYTES (`cap` then limits the whole stream). The thread owns the file object: nothing
    else closes the pipe while a read on it may be pending, and its reference keeps the garbage collector from closing
    it either. After finish() it keeps and reports nothing more."""

    def __init__(self, f, cap=None, tail=None, on_line=None):
        self.cap, self.tail, self.on_line = cap, tail, on_line
        self._stream = on_line is not None
        self.size = 0
        self.overflow = False
        self.error = None  # what on_line raised
        self._head = 0
        self._line = bytearray()
        self._whole = True
        self._eof = self._closed = False
        self._chunks = collections.deque()
        self._lock = threading.Lock()
        self.thread = threading.Thread(target=self._run, args=(f,), name="ub-proc-reader", daemon=True)
        self.thread.start()

    def _run(self, f):
        try:
            fd = f.fileno()
            while True:
                chunk = os.read(fd, _CHUNK)
                if not chunk:
                    break
                self._keep(chunk)
        except (OSError, ValueError):
            pass
        finally:
            with self._lock:
                self._eof = True
                if self._stream and not self._closed:
                    self._flush()
            try:
                f.close()
            except OSError:
                pass

    def _keep(self, chunk):
        with self._lock:
            if self._closed:
                return
            if self.cap is not None and self.size + len(chunk) > self.cap:
                chunk = chunk[:max(0, self.cap - self.size)]
                self.overflow = True
            if self._stream:
                self.size += len(chunk)
                if self._head < STREAM_HEAD_BYTES and chunk:
                    self._chunks.append(chunk[:STREAM_HEAD_BYTES - self._head])
                    self._head += len(self._chunks[-1])
                self._split(chunk)
                return
            if chunk:
                self._chunks.append(chunk)
                self.size += len(chunk)
            while self.tail is not None and len(self._chunks) > 1 and self.size - len(self._chunks[0]) >= self.tail:
                self.size -= len(self._chunks.popleft())

    def _split(self, chunk):
        """Cut a chunk into lines for on_line; a line keeps at most LINE_CAP_BYTES (the rest is dropped)."""
        start, n = 0, len(chunk)
        while start < n:
            nl = chunk.find(b"\n", start)
            end = n if nl < 0 else nl
            room = LINE_CAP_BYTES - len(self._line)
            self._line += chunk[start:start + min(room, end - start)]
            if end - start > room:
                self._whole = False
            if nl < 0:
                return
            self._emit(True)
            start = nl + 1

    def _emit(self, ended):
        line, whole = bytes(self._line), self._whole and ended
        self._line, self._whole = bytearray(), True
        if self.on_line is None:
            return
        try:
            self.on_line(line, whole)
        except Exception as e:  # noqa: BLE001 - run() raises it once the child is gone
            self.error, self.on_line = e, None

    def _flush(self):
        """The last line of the stream (no newline after it): whole only when the stream really ended."""
        if self._line or not self._whole:
            self._emit(self._eof)

    def finish(self):
        """run() is done with this pipe: pass on a pending line, then keep nothing more (a reader left blocked on a
        pipe that a process outside the tree holds may still get bytes)."""
        with self._lock:
            if self._stream and not self._closed:
                self._flush()
            self._closed = True

    def data(self):
        with self._lock:
            data = b"".join(self._chunks)
        return data[-self.tail:] if self.tail is not None else data


class _Job(object):
    """Windows: a Job Object that holds a child's process tree. KILL_ON_JOB_CLOSE ends every process still in it when
    the handle closes (at the end of run(), or when this process dies), including descendants whose parent has
    already exited."""

    def __init__(self, handle):
        self.handle = handle

    @classmethod
    def contain(cls, pid):
        """A _Job holding pid, or None when one cannot be set up (then taskkill /T alone kills the tree). The child is
        assigned right after it starts, before it starts descendants of its own, and the backend CLIs are assumed to
        run unchanged inside a (nested) job."""  # [U-80]
        try:
            w = _win()
            k32 = w["k32"]
            job = k32.CreateJobObjectW(None, None)
            if not job:
                return None
            info = w["limits"]()
            info.BasicLimitInformation.LimitFlags = _JOB_KILL_ON_CLOSE | _JOB_BREAKAWAY_OK
            ok = k32.SetInformationJobObject(job, _JOB_EXTENDED_LIMITS, w["ctypes"].byref(info),
                                             w["ctypes"].sizeof(info))
            handle = k32.OpenProcess(_PROCESS_SET_QUOTA | _PROCESS_TERMINATE, False, pid) if ok else None
            if handle:
                try:
                    ok = k32.AssignProcessToJobObject(job, handle)
                finally:
                    k32.CloseHandle(handle)
            if not (ok and handle):
                k32.CloseHandle(job)
                return None
            return cls(job)
        except Exception:  # noqa: BLE001 - containment is best effort; taskkill /T remains
            return None

    def terminate(self):
        if self.handle:
            _win()["k32"].TerminateJobObject(self.handle, 1)

    def close(self):
        handle, self.handle = self.handle, None
        if handle:
            _win()["k32"].CloseHandle(handle)


_WIN = {}


def _win():
    """kernel32 with the prototypes used here, and the job-limits structure (Windows only; built on first use)."""
    if not _WIN:
        import ctypes
        from ctypes import wintypes
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        h, d, b = wintypes.HANDLE, wintypes.DWORD, wintypes.BOOL
        for name, res, args in (("OpenProcess", h, [d, b, d]), ("CloseHandle", b, [h]),
                                ("GetExitCodeProcess", b, [h, ctypes.POINTER(d)]),
                                ("GetProcessTimes", b, [h] + [ctypes.POINTER(wintypes.FILETIME)] * 4),
                                ("CreateJobObjectW", h, [ctypes.c_void_p, wintypes.LPCWSTR]),
                                ("SetInformationJobObject", b, [h, ctypes.c_int, ctypes.c_void_p, d]),
                                ("AssignProcessToJobObject", b, [h, h]),
                                ("TerminateJobObject", b, [h, wintypes.UINT])):
            fn = getattr(k32, name)
            fn.restype, fn.argtypes = res, args

        class Basic(ctypes.Structure):  # JOBOBJECT_BASIC_LIMIT_INFORMATION
            _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                        ("LimitFlags", d), ("MinimumWorkingSetSize", ctypes.c_size_t),
                        ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", d),
                        ("Affinity", ctypes.c_size_t), ("PriorityClass", d), ("SchedulingClass", d)]

        class Extended(ctypes.Structure):  # JOBOBJECT_EXTENDED_LIMIT_INFORMATION (IoInfo: six ULONGLONG counters)
            _fields_ = [("BasicLimitInformation", Basic), ("IoInfo", ctypes.c_uint64 * 6),
                        ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                        ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]

        _WIN.update(ctypes=ctypes, wintypes=wintypes, k32=k32, limits=Extended)
    return _WIN


def _taskkill_path():
    found = system_tool("taskkill")
    if found:
        return found
    root = os.environ.get("SYSTEMROOT") or os.environ.get("SystemRoot") or r"C:\Windows"
    return os.path.join(root, "System32", "taskkill.exe")


def kill_tree(pid, grace_s=_GRACE_S, proc=None):
    """Kill pid and all its descendants. Never raises for a process that is already gone.

    Windows: taskkill /PID <pid> /T /F. POSIX: SIGTERM to the process group when pid leads it (the CLIs run() starts
    and detached workers do; never our own group), else to pid alone; wait up to grace_s, then SIGKILL. A process that
    shares another's group (an attached worker in its launcher's group) is stopped alone: its launcher and siblings are
    never signaled, and its backend CLI (its own group, recorded in the worker's marker) is stopped separately.
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
    if pgid is not None and (pgid != int(pid) or pgid == os.getpgid(0)):
        pgid = None  # a group pid does not lead is someone else's (and our own group is never signaled)
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


def process_identity(pid):
    """An exact identity of the process that now has pid (its creation time), or None when it cannot be read (no
    such process, another user's, or no way to ask). A reused pid gets a different identity, so a recorded
    (pid, identity) pair names one process only. Windows "win:<creation FILETIME>" (GetProcessTimes); Linux
    "linux:<boot id>:<start ticks>" (/proc/<pid>/stat field 22); other POSIX systems "ps:<ps -o lstart=, in UTC>"
    (seconds)."""
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return None
    if pid <= 0:
        return None
    if IS_WINDOWS:
        try:
            w = _win()
            k32 = w["k32"]
            handle = k32.OpenProcess(_PROCESS_QUERY_LIMITED, False, pid)
            if not handle:
                return None
            try:
                t = [w["wintypes"].FILETIME() for _ in range(4)]
                if not k32.GetProcessTimes(handle, *[w["ctypes"].byref(x) for x in t]):
                    return None
                return "win:%d" % ((t[0].dwHighDateTime << 32) | t[0].dwLowDateTime)
            finally:
                k32.CloseHandle(handle)
        except (OSError, AttributeError, ValueError):
            return None
    if sys.platform.startswith("linux") and os.path.isdir("/proc/self"):
        try:
            with open("/proc/%d/stat" % pid, "r") as f:
                fields = f.read().rsplit(")", 1)[-1].split()
            return "linux:%s:%d" % (_boot_id(), int(fields[19]))
        except (OSError, ValueError, IndexError):
            return None
    return _ps_start(pid)


def _boot_id():
    if not _BOOT_ID:
        try:
            with open("/proc/sys/kernel/random/boot_id", "r") as f:
                _BOOT_ID.append(f.read().strip())
        except OSError:
            _BOOT_ID.append("")
    return _BOOT_ID[0]


def _ps_start(pid):
    """The start time `ps -o lstart=` prints for pid (macOS, BSD), or None. ps prints local time, so it runs in UTC
    (TZ=UTC0, LC_ALL=C): the identity must not depend on the caller's time zone (a worker and a `ub stop` from another
    shell read the same process)."""
    exe = "/bin/ps" if os.path.isfile("/bin/ps") else which("ps")
    if not exe:
        return None
    try:
        cp = subprocess.run([exe, "-o", "lstart=", "-p", str(pid)], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL, timeout=10, env=dict(os.environ, LC_ALL="C", TZ="UTC0"))
    except (OSError, subprocess.SubprocessError):
        return None
    text = " ".join(cp.stdout.decode("ascii", "replace").split())
    return "ps:" + text if cp.returncode == 0 and text else None


def process_start_time(pid):
    """When the process that now has pid started, in epoch seconds, or None when unknown. Derived from
    process_identity(): Windows FILETIME, Linux start ticks plus /proc/stat btime, ps lstart elsewhere (1 s)."""
    ident = process_identity(pid)
    if not ident:
        return None
    kind, _sep, value = ident.partition(":")
    try:
        if kind == "win":
            return (int(value) - 116444736000000000) / 1e7  # 100 ns ticks since 1601 -> epoch seconds
        if kind == "linux":
            ticks = int(value.rsplit(":", 1)[-1])
            with open("/proc/stat", "r") as f:
                btime = [ln.split()[1] for ln in f if ln.startswith("btime ")]
            return int(btime[0]) + ticks / float(os.sysconf("SC_CLK_TCK")) if btime else None
        if kind == "ps":
            return float(calendar.timegm(time.strptime(value, "%a %b %d %H:%M:%S %Y")))  # _ps_start prints UTC
    except (OSError, ValueError, IndexError, OverflowError):
        return None
    return None


def same_process(pid, ident):
    """True when pid runs and is the process whose process_identity() was recorded as ident. An unknown identity
    (None) never matches: a process that cannot be identified is never killed."""
    return bool(ident) and pid_alive(pid) and process_identity(pid) == ident


def pid_alive(pid):
    """Best-effort liveness check for a pid (True when it runs, False when it exited or never existed)."""
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    if IS_WINDOWS:
        w = _win()
        k32 = w["k32"]
        handle = k32.OpenProcess(_PROCESS_QUERY_LIMITED, False, pid)
        if not handle:
            return w["ctypes"].get_last_error() == 5  # access denied: it exists
        try:
            code = w["wintypes"].DWORD()
            if not k32.GetExitCodeProcess(handle, w["ctypes"].byref(code)):
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
    elif not sys.platform.startswith("linux") and _ps_zombie(pid):
        return False  # macOS, BSD: a killed child its parent has not reaped still answers signal 0
    return True


def _ps_zombie(pid):
    """True when `ps -o stat=` shows pid as a zombie (no /proc on macOS and BSD). Any failure to ask reads as not one."""
    exe = "/bin/ps" if os.path.isfile("/bin/ps") else which("ps")
    if not exe:
        return False
    try:
        cp = subprocess.run([exe, "-o", "stat=", "-p", str(pid)], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL, timeout=10, env=dict(os.environ, LC_ALL="C"))
    except (OSError, subprocess.SubprocessError):
        return False
    return cp.returncode == 0 and cp.stdout.decode("ascii", "replace").strip().startswith("Z")


def legacy_driver_live(data, run_dir, now=None, exclude_pid=None):
    """True when data, run_dir's .ub/lock.json record, names a live kit 2.0.x driver: the one rule of the engine
    (state.DriverLock.legacy_holder) and the installer (legacy_driver_alive), KIT_SPEC 6.3 and 10.4 item 8. A 2.0.x
    record {pid, host, heartbeat_at, heartbeat_ts} has no `since`; a kit 2.1+ record has it and decides nothing here
    (its driver is seen through its kernel lock). It is live when its pid lives and is not exclude_pid, and its
    heartbeat_ts is at most LEGACY_DRIVER_STALE_S old, or older while the driver that wrote it still runs, for example
    a 2.0.x `ub run` waiting at a human gate, which beats no more: the process with that pid started no later than 1 s
    after the beat (one that started later got a reused pid), or it runs ub.py on this run (runs_ub_on: a forward
    wall-clock step after the beat moves a POSIX start time, which is derived from the boot time). A beat more than
    LEGACY_DRIVER_STALE_S ahead decides nothing. now: the caller's clock (time.time() by default)."""
    if not isinstance(data, dict) or "since" in data:
        return False
    try:
        beat = float(data.get("heartbeat_ts"))
        pid = int(data.get("pid"))
    except (TypeError, ValueError):
        return False
    age = (time.time() if now is None else now) - beat
    if age < -LEGACY_DRIVER_STALE_S or pid == exclude_pid or not pid_alive(pid):
        return False
    if age <= LEGACY_DRIVER_STALE_S:
        return True
    started = process_start_time(pid)
    if started is not None and started <= beat + 1:
        return True
    return runs_ub_on(pid, run_dir)


def process_args(pid):
    """(arguments, working folder or None) of the process pid: Linux /proc/<pid>/cmdline and /proc/<pid>/cwd, other
    POSIX systems `ps -o args=` (split at blanks; no working folder). ([], None) on Windows, whose process start times
    no clock step moves, and when they cannot be read."""
    if IS_WINDOWS:
        return [], None
    cmdline = "/proc/%d/cmdline" % pid
    if os.path.isfile(cmdline):
        try:
            with open(cmdline, "rb") as f:
                args = [a.decode("utf-8", "replace") for a in f.read().split(b"\0") if a]
        except OSError:
            return [], None
        try:
            cwd = os.readlink("/proc/%d/cwd" % pid)
        except OSError:
            cwd = None
        return args, cwd
    exe = "/bin/ps" if os.path.isfile("/bin/ps") else which("ps")
    if not exe:
        return [], None
    try:
        cp = subprocess.run([exe, "-o", "args=", "-p", str(pid)], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL, timeout=10, env=dict(os.environ, LC_ALL="C"))
    except (OSError, subprocess.SubprocessError):
        return [], None
    return (cp.stdout.decode("utf-8", "replace").split() if cp.returncode == 0 else []), None


def runs_ub_on(pid, run_dir):
    """True when the process pid runs ub.py on run_dir: an argument is ub.py, and its working folder or an argument
    (relative ones resolved against that folder) is the run folder, the run root holding it (<cwd>/brainstorm, or
    --root) or the folder above that root, or an argument ends with the run folder's name. The step-proof signal of a
    2.0.x driver for legacy_driver_live."""
    args, cwd = process_args(pid)
    if not any(os.path.basename(a) == "ub.py" for a in args):
        return False
    run = os.path.abspath(run_dir)
    places = set(os.path.normcase(os.path.realpath(p)) for p in (run, os.path.dirname(run),
                                                                 os.path.dirname(os.path.dirname(run))))
    named = [cwd] + [os.path.join(cwd, a) if cwd else a for a in args if cwd or os.path.isabs(a)]
    if any(os.path.normcase(os.path.realpath(p)) in places for p in named if p):
        return True
    name = os.path.basename(run)
    return any(os.path.basename(a.rstrip("/\\")) == name for a in args)
