"""Detached worker launch, heartbeat, job state, foreground batch (KIT_SPEC 4.7, 6.3).

Frozen API (4.8):
    launch_job(job_path) -> dict                 {"pid": int, "job_id": str} (+ "relaunches", "launched", "state",
                                                 "exit_code" attached; "state" is "done", "running" or "stuck")
    job_state(run_dir, job) -> str               done|running|dead|failed|pending
    running_jobs(run_dir) -> list                job ids with live markers (or a held execution lock)
    stop_all(run_dir) -> int                     tree-kills live workers; returns the count
    run_foreground(jobs, parallel=4, budget_s=None) -> dict   {"done": [...], "failed": [...], "pending": [...]}

Extras: WorkerMarker (used by `family.py job`), JobLock, lock_state(run_dir, job_id), is_done(run_dir, job),
        relaunch_count(run_dir, job), worker_argv(job_path), marker_path(run_dir, job_id), lock_path(run_dir, job_id),
        stale_after_s(), RELAUNCH_LIMIT.

One worker per job (4.7, execution lock). A worker holds .ub/jobs/<id>.lock, an OS file lock (LockFile through
msvcrt.locking on Windows, flock on POSIX), from before it writes its running marker until after it has deleted it. The OS
drops the lock when the process ends, even when it is killed, so a dead worker never leaves a stale claim. Therefore:
  - a worker starts no model call while another process holds the job, and it re-checks the done rule once it holds
    the lock: a job that finished meanwhile is never called again (the worker exits 0, "skipped"). Nor is a job for
    which another worker wrote a meta (ok or failed) for the current prompt while this one waited for the lock;
  - launch_job takes the same lock while it decides and spawns. It does not launch a job that is done, whose lock is
    held or whose marker is live, and it writes the marker (with the child's pid and a launch token) before the child
    can take the lock, so nothing races its write (a marker is never re-created after its worker deleted it). The
    worker recognizes that marker as its own by the token (UB_LAUNCH_TOKEN), not by the pid: in a Windows venv the
    pid launch_job sees is the venv redirector's, and the worker is its child;
  - job_state reports a job whose lock is held as running whatever its heartbeat says, so a late heartbeat never
    leads to a second worker.
On a file system without file locks the marker and heartbeat rules alone apply.

Test hooks (4.19): UB_NO_DETACH=1 runs the worker attached; UB_HEARTBEAT_STALE_S overrides the 60 s threshold.
"""

import binascii
import calendar
import errno
import json
import os
import subprocess
import sys
import threading
import time

from . import SCRIPTS_DIR
from . import proc
from . import textio
from . import validate

__all__ = ["launch_job", "job_state", "running_jobs", "stop_all", "run_foreground", "WorkerMarker", "JobLock",
           "lock_state", "is_done", "relaunch_count", "worker_argv", "marker_path", "lock_path", "stale_after_s",
           "RELAUNCH_LIMIT", "HEARTBEAT_S"]

HEARTBEAT_S = 10.0
STALE_DEFAULT_S = 60.0
RELAUNCH_LIMIT = 3
POLL_S = 0.2
LAUNCH_TOKEN_ENV = "UB_LAUNCH_TOKEN"  # launch_job -> worker: which launcher-written marker is the worker's own
LOCK_WAIT_S = 30.0         # a starting worker waits this long for its launcher (or a state probe) to let go
LAUNCH_LOCK_WAIT_S = 1.0   # launch_job waits this long for the lock before it reports the job as running
MARKER_REMOVE_S = 2.0      # a worker retries deleting its marker this long (a reader may hold it open on Windows)
_LOCK_OFFSET = 0x7FFFFFF0  # the locked byte lies far beyond EOF, so the lock file stays empty and readable

_LIVE = []  # Popen objects of workers we started and do not wait for (reaped by _reap, no ResourceWarning)

_DETACHED_PROCESS = 0x00000008
_CREATE_NEW_PROCESS_GROUP = 0x00000200
_CREATE_BREAKAWAY_FROM_JOB = 0x01000000


# ---------------------------------------------------------------- paths and small helpers

def family_py():
    return os.path.join(SCRIPTS_DIR, "family.py")


def worker_argv(job_path):
    """PY SK/scripts/family.py job --job <abs job.json> (4.7)."""
    return [sys.executable, family_py(), "job", "--job", os.path.abspath(job_path)]


def stale_after_s():
    try:
        v = float(os.environ.get("UB_HEARTBEAT_STALE_S") or STALE_DEFAULT_S)
        return v if v > 0 else STALE_DEFAULT_S
    except ValueError:
        return STALE_DEFAULT_S


def _jobs_dir(run_dir):
    return os.path.join(os.path.abspath(run_dir), ".ub", "jobs")


def marker_path(run_dir, job_id):
    return os.path.join(_jobs_dir(run_dir), "%s.running.json" % job_id)


def lock_path(run_dir, job_id):
    return os.path.join(_jobs_dir(run_dir), "%s.lock" % job_id)


def _relaunch_path(run_dir, job_id):
    return os.path.join(_jobs_dir(run_dir), "%s.relaunch" % job_id)


def _parse_iso(ts):
    try:
        return float(calendar.timegm(time.strptime(ts, "%Y-%m-%dT%H:%M:%SZ")))
    except (TypeError, ValueError):
        return None


def _load(job):
    """A job given as a dict or a path -> dict (with "_path" when it came from a file)."""
    if isinstance(job, dict):
        return job
    path = os.path.abspath(os.fspath(job))
    data = textio.read_json(path)
    if not isinstance(data, dict):
        raise ValueError("job file is not a JSON object: %s" % textio.to_posix(path))
    data = dict(data)
    data["_path"] = path
    return data


def _paths(run_dir, job):
    run_dir = os.path.abspath(run_dir or job.get("run") or ".")
    return (run_dir, os.path.join(run_dir, job.get("prompt_file") or ""), os.path.join(run_dir, job.get("out") or ""))


def _read_json_quiet(path):
    """A JSON object from a file other processes may be replacing (reads retry that on Windows), or None."""
    data = textio.read_json_or(path)
    return data if isinstance(data, dict) else None


def _pid_of(marker):
    try:
        pid = int((marker or {}).get("pid") or 0)
    except (TypeError, ValueError):
        return 0
    return pid if pid > 0 else 0


# ---------------------------------------------------------------- execution lock

def _os_lock(fd):
    """Lock fd without blocking. True: locked; False: another process or handle holds it; None: no file locks here."""
    if os.name == "nt":
        try:
            import msvcrt
        except ImportError:
            return None
        try:
            os.lseek(fd, _LOCK_OFFSET, 0)
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            return True
        except OSError as e:
            if e.errno in (errno.EACCES, errno.EDEADLK) or getattr(e, "winerror", None) in (5, 33):
                return False
            return None
    try:
        import fcntl
    except ImportError:
        return None
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except OSError as e:
        if e.errno in (errno.EAGAIN, errno.EWOULDBLOCK, errno.EACCES):
            return False
        return None  # ENOLCK, EOPNOTSUPP, ...: this file system has no flock


def _os_unlock(fd):
    if os.name == "nt":
        try:
            import msvcrt
            os.lseek(fd, _LOCK_OFFSET, 0)
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        except (ImportError, OSError):
            pass
        return
    try:
        import fcntl
        fcntl.flock(fd, fcntl.LOCK_UN)
    except (ImportError, OSError):
        pass


class JobLock(object):
    """The execution lock of one job (module note). The file is never deleted: deleting a lock file races with a
    process that has just opened it. Locks are per open file, so a second JobLock in the same process conflicts too."""

    def __init__(self, run_dir, job_id):
        self.path = lock_path(run_dir, job_id)
        self._fd = None
        self.exclusive = False  # True only while held on a file system that has file locks

    @property
    def held(self):
        return self._fd is not None

    def _open(self):
        """The lock file's fd. A Windows open that collides with a scanner or indexer is retried for up to 1 s."""
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        deadline = time.monotonic() + 1.0
        while True:
            try:
                return os.open(self.path, os.O_RDWR | os.O_CREAT | getattr(os, "O_BINARY", 0), 0o644)
            except PermissionError:
                if os.name != "nt" or time.monotonic() >= deadline:
                    raise
                time.sleep(0.02)

    def try_acquire(self):
        """True when this object now holds the lock (or file locks are unsupported); False when it is taken."""
        if self._fd is not None:
            return True
        try:
            fd = self._open()
        except OSError:
            return True  # no usable lock file here (read-only or odd file system): the marker rules alone apply
        try:
            got = _os_lock(fd)
        except BaseException:
            os.close(fd)
            raise
        if got is False:
            os.close(fd)
            return False
        self._fd = fd
        self.exclusive = got is True
        return True

    def acquire(self, timeout_s=0.0, give_up=None):
        """try_acquire until it succeeds, timeout_s passes, or give_up() says the wait is pointless."""
        deadline = time.monotonic() + max(0.0, float(timeout_s or 0))
        while True:
            if self.try_acquire():
                return True
            if time.monotonic() >= deadline or (give_up is not None and give_up()):
                return False
            time.sleep(0.05)

    def release(self):
        fd, self._fd = self._fd, None
        self.exclusive = False
        if fd is None:
            return
        _os_unlock(fd)
        try:
            os.close(fd)
        except OSError:
            pass


def lock_state(run_dir, job_id):
    """True when some process holds the job's execution lock, False when none does, None when unknown (no file locks
    here). A probe: it takes the lock for a moment when it is free (lock takers retry, so this never hurts them)."""
    if not os.path.exists(lock_path(run_dir, job_id)):
        return False
    lk = JobLock(run_dir, job_id)
    try:
        if not lk.try_acquire():
            return True
        return False if lk.exclusive else None
    except OSError:
        return None
    finally:
        lk.release()


# ---------------------------------------------------------------- marker

def _marker_live(path):
    """(exists, live, marker dict or None). Live = heartbeat newer than the stale threshold and the pid runs."""
    if not os.path.isfile(path):
        return False, False, None
    m = _read_json_quiet(path)
    now = time.time()
    hb = _parse_iso((m or {}).get("heartbeat_at")) if m else None
    if hb is None:
        try:
            hb = os.path.getmtime(path)  # unreadable, or no heartbeat yet: use the file time
        except OSError:
            return False, False, None
    fresh = (now - hb) <= stale_after_s()
    pid = (m or {}).get("pid")
    alive = True if not pid else proc.pid_alive(pid)
    return True, bool(fresh and alive), m


class WorkerMarker(object):
    """The worker's side of 4.7. On enter it takes the job's execution lock (waiting for its launcher to let go),
    re-checks the done rule, writes the running marker and refreshes its heartbeat from a thread; on exit it deletes
    the marker and only then releases the lock.

    `skipped` is set when the caller must not run the job: "running" (another process holds the job), "done" (the
    done rule already holds, so there is nothing to call) or "finished" (another worker wrote a meta for the current
    prompt while this one waited for the lock: it ran the job, even if it failed). A skipped worker never writes the
    marker of the process that holds the job, nor any output.
    """

    def __init__(self, run_dir, job_id, pid=None, job=None, lock_wait_s=None):
        self.run_dir = run_dir
        self.job = job
        self.path = marker_path(run_dir, job_id)
        self.token = (os.environ.get(LAUNCH_TOKEN_ENV) or "").strip() or None
        self.data = {"pid": pid or os.getpid(), "started_at": textio.now_iso(), "heartbeat_at": textio.now_iso(),
                     "attempt": 0, "backend": None}
        if self.token:
            self.data["token"] = self.token
        self._meta_sig = _meta_sig(run_dir, job) if job is not None else None
        self.lock = JobLock(run_dir, job_id)
        self.lock_wait_s = LOCK_WAIT_S if lock_wait_s is None else lock_wait_s
        self.skipped = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._thread = None

    def _write(self):
        with self._lock:
            self.data["heartbeat_at"] = textio.now_iso()
            try:
                textio.write_json_atomic(self.path, self.data)
            except OSError:
                pass

    def update(self, attempt, backend):
        self.data["attempt"] = attempt
        self.data["backend"] = backend
        self._write()

    def _beat(self):
        interval = min(HEARTBEAT_S, max(0.5, stale_after_s() / 3.0))
        while not self._stop.wait(interval):
            self._write()

    def _is_own(self, m):
        """The marker is ours: our launcher wrote it for us (same launch token; its pid may be a venv redirector
        whose child we are) or we wrote it."""
        if not m:
            return False
        if self.token and m.get("token") == self.token:
            return True
        return _pid_of(m) == self.data["pid"]

    def _held_elsewhere(self):
        """True when the marker names another live worker: it holds the job, so waiting longer is pointless. (While our
        own launcher still holds the lock, the marker is ours or is not written yet.)"""
        m = _read_json_quiet(self.path)
        if not m or self._is_own(m):
            return False
        pid = _pid_of(m)
        return bool(pid) and pid != os.getpid() and proc.pid_alive(pid) and _is_worker(pid, m)

    def _remove_own_marker(self):
        if self._is_own(_read_json_quiet(self.path)):
            _remove_quiet(self.path)

    def _finished_meanwhile(self):
        """True when a meta for the current prompt appeared or changed while we waited for the lock: another worker
        ran the job (ok or failed). Running it again would be a second call for the same prompt."""
        sig = _meta_sig(self.run_dir, self.job)
        if sig is None or sig == self._meta_sig:
            return False
        job = _load(self.job)
        _run, prompt_path, out_path = _paths(self.run_dir, job)
        meta = _read_json_quiet(out_path + ".meta.json")
        if not meta or not meta.get("status") or not os.path.isfile(prompt_path):
            return False
        try:
            return meta.get("prompt_sha256") == textio.sha256_file(prompt_path)
        except OSError:
            return False

    def __enter__(self):
        if not self.lock.acquire(self.lock_wait_s, give_up=self._held_elsewhere):
            self.skipped = "running"
            return self
        try:
            if self.job is not None:
                if is_done(self.run_dir, self.job):
                    self.skipped = "done"
                elif self._finished_meanwhile():
                    self.skipped = "finished"
                if self.skipped:
                    self._remove_own_marker()  # the launcher wrote it for us; the finished job needs no marker
                    return self
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            self._write()
            self._thread = threading.Thread(target=self._beat, name="ub-heartbeat", daemon=True)
            self._thread.start()
        except BaseException:
            self.lock.release()
            raise
        return self

    def __exit__(self, *exc):
        try:
            if self.skipped is None:
                self._stop.set()
                if self._thread is not None:
                    self._thread.join(timeout=5)
                with self._lock:
                    deadline = time.monotonic() + MARKER_REMOVE_S
                    while True:
                        try:
                            if os.path.exists(self.path):
                                os.remove(self.path)
                            break
                        except PermissionError:  # a reader has it open (Windows): retry briefly
                            if time.monotonic() >= deadline:
                                break
                            time.sleep(0.05)
                        except OSError:
                            break
        finally:
            self.lock.release()  # after the marker is gone: see job_state
        return False


# ---------------------------------------------------------------- state

def _meta_sig(run_dir, job):
    """(mtime_ns, size) of the job's <out>.meta.json, or None when there is none."""
    try:
        _run, _prompt, out_path = _paths(run_dir, _load(job))
        st_ = os.stat(out_path + ".meta.json")
    except (OSError, ValueError):
        return None
    return (st_.st_mtime_ns, st_.st_size)


def is_done(run_dir, job):
    """The done rule (4.4): <out> exists, the contract validates, and <out>.meta.json has status ok and the
    prompt_sha256 of the current prompt file."""
    job = _load(job)
    run_dir, prompt_path, out_path = _paths(run_dir, job)
    meta = _read_json_quiet(out_path + ".meta.json")
    if not meta or meta.get("status") != "ok" or not os.path.isfile(out_path) or not os.path.isfile(prompt_path):
        return False
    try:
        if meta.get("prompt_sha256") != textio.sha256_file(prompt_path):
            return False
        text = textio.read_text(out_path)
    except OSError:
        return False
    ok, _errors, _parsed = validate.check_contract(text, job.get("contract") or {"type": "text"}, run_dir)
    return ok


def job_state(run_dir, job):
    """done | running | dead | failed | pending (4.7)."""
    job = _load(job)
    # Read the marker and the execution lock BEFORE the done check. A worker writes <out> and its meta, deletes its
    # marker, and only then releases its lock, so in this order "no marker and no lock holder" means the outputs of a
    # finished worker are already on disk. The other order lets a worker that finishes between the reads look
    # "pending" (not done yet, no marker any more), and the dispatcher would launch the finished job a second time.
    run_dir, prompt_path, out_path = _paths(run_dir, job)
    mpath = marker_path(run_dir, job.get("id"))
    exists, live, m = _marker_live(mpath)
    held = lock_state(run_dir, job.get("id"))
    if is_done(run_dir, job):
        return "done"
    if held:
        return "running"  # a worker (or a launcher starting one) holds the job, whatever its heartbeat says
    if exists and live:
        return "running"
    if exists and _stale_but_alive(mpath, m):
        return "running"  # a late heartbeat (sleep, heavy load): not dead yet, never relaunched twice
    meta = _read_json_quiet(out_path + ".meta.json")
    finished = False
    if meta and meta.get("status") and meta.get("status") != "ok" and os.path.isfile(prompt_path):
        try:
            finished = meta.get("prompt_sha256") == textio.sha256_file(prompt_path)
        except OSError:
            finished = False
    if exists:
        # A marker whose worker is gone although it wrote a failed meta during this launch: the job failed; it did not
        # die (a worker that fails writes its meta before it deletes its marker; a crash in between leaves both).
        m_start = _parse_iso((m or {}).get("started_at"))
        meta_start = _parse_iso((meta or {}).get("started"))
        if finished and m_start is not None and meta_start is not None and meta_start >= m_start:
            return "failed"
        return "dead"
    return "failed" if finished else "pending"


def relaunch_count(run_dir, job):
    """How often a dead job was relaunched for the CURRENT prompt hash (.ub/jobs/<id>.relaunch)."""
    job = _load(job)
    run_dir, prompt_path, _out = _paths(run_dir, job)
    data = _read_json_quiet(_relaunch_path(run_dir, job.get("id")))
    if not data or not os.path.isfile(prompt_path):
        return 0
    try:
        if data.get("prompt_sha256") != textio.sha256_file(prompt_path):
            return 0
    except OSError:
        return 0
    try:
        return int(data.get("count") or 0)
    except (TypeError, ValueError):
        return 0


def _note_relaunch(run_dir, job):
    _run, prompt_path, _out = _paths(run_dir, job)
    n = relaunch_count(run_dir, job) + 1
    try:
        sha = textio.sha256_file(prompt_path) if os.path.isfile(prompt_path) else None
    except OSError:
        sha = None
    textio.write_json_atomic(_relaunch_path(run_dir, job.get("id")), {"prompt_sha256": sha, "count": n,
                                                                        "at": textio.now_iso()})
    return n


def running_jobs(run_dir):
    d = _jobs_dir(run_dir)
    out = []
    if not os.path.isdir(d):
        return out
    for name in sorted(os.listdir(d)):
        if name.endswith(".running.json"):
            jid = name[:-len(".running.json")]
            _e, live, _m = _marker_live(os.path.join(d, name))
            if live or lock_state(run_dir, jid):
                out.append(jid)
    return out


def stop_all(run_dir):
    """Tree-kill every live worker of the run and remove its marker. Returns the number killed."""
    d = _jobs_dir(run_dir)
    count = 0
    if not os.path.isdir(d):
        return 0
    for name in sorted(os.listdir(d)):
        if not name.endswith(".running.json"):
            continue
        path = os.path.join(d, name)
        _e, live, m = _marker_live(path)
        pid = (m or {}).get("pid")
        # kill a live pid even when its heartbeat is stale (it would otherwise keep writing after the stop),
        # but only when that pid is really the worker (it started no later than the marker)
        if pid and int(pid) != os.getpid() and (live or (proc.pid_alive(pid) and _is_worker(pid, m))):
            proc.kill_tree(int(pid), proc=_owned(int(pid)))
            count += 1
        try:
            os.remove(path)
        except OSError:
            pass
    _reap()
    try:  # killed workers never ran their finally: delete their per-call folders (they can hold a provider token)
        from . import families as _fam
        from .backends import sweep_stale_calls
        if count:
            time.sleep(0.5)
        sweep_stale_calls(_fam.ub_home())
    except Exception:  # noqa: BLE001
        pass
    return count


# ---------------------------------------------------------------- launch

def _worker_env(token=None):
    env = dict(os.environ)
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env.pop(LAUNCH_TOKEN_ENV, None)  # never inherited: only the launch that wrote the marker hands out its token
    if token:
        env[LAUNCH_TOKEN_ENV] = token
    return env


def _detach_kwargs(with_breakaway=True):
    if os.name == "nt":
        flags = _CREATE_NEW_PROCESS_GROUP | _DETACHED_PROCESS
        if with_breakaway:
            flags |= _CREATE_BREAKAWAY_FROM_JOB  # [U-24] survive a host that closes its job object
        return {"creationflags": flags}
    return {"start_new_session": True}


def _spawn_detached(argv, logf, run_dir, token=None):
    try:
        return subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=logf, stderr=subprocess.STDOUT,
                                env=_worker_env(token), cwd=run_dir, close_fds=True, **_detach_kwargs(True))
    except OSError:
        if os.name != "nt":
            raise
        # breakaway not allowed by the enclosing job object: retry without it  # [U-24]
        return subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=logf, stderr=subprocess.STDOUT,
                                env=_worker_env(token), cwd=run_dir, close_fds=True, **_detach_kwargs(False))


def _stop_stale_worker(marker):
    """A dead marker whose pid still runs and verifiably is its worker (a process without the execution lock, e.g. on
    a file system without file locks): stop it before a new worker starts. Returns False when it still runs."""
    pid = _pid_of(marker)
    if not pid or pid == os.getpid() or not proc.pid_alive(pid):
        return True
    started = _parse_iso((marker or {}).get("started_at"))
    t = proc.process_start_time(pid)
    if started is None or t is None or t > started + 5:
        return True  # a reused pid: the worker itself is gone
    proc.kill_tree(pid, proc=_owned(pid))
    deadline = time.monotonic() + 10
    while proc.pid_alive(pid) and time.monotonic() < deadline:
        time.sleep(0.1)
    return not proc.pid_alive(pid)


def launch_job(job_path):
    """Start `family.py job --job <abs job.json>` as a detached worker (attached with UB_NO_DETACH=1).

    The decision is re-checked under the job's execution lock: a job that is done, whose lock another process holds
    or whose marker is live is not launched ({"launched": false, "state": "done"|"running"}). A dead marker is removed
    (a process still behind it is stopped first) and the relaunch is counted in .ub/jobs/<id>.relaunch. When that
    process cannot be stopped, nothing is launched and the state is "stuck" (the driver shows a BLOCKED card that
    suggests `ub stop`). The running marker is written with the child's pid and a launch token while the lock is still
    held, so a quick second poll never launches the job twice and the worker (which needs the lock) cannot finish and
    delete its marker before the write.
    """
    job_path = os.path.abspath(os.fspath(job_path))
    job = _load(job_path)
    jid = job.get("id")
    run_dir = os.path.abspath(job.get("run") or os.path.dirname(os.path.dirname(job_path)))
    mpath = marker_path(run_dir, jid)
    attached = (os.environ.get("UB_NO_DETACH") or "").strip() == "1"
    lock = JobLock(run_dir, jid)
    if not lock.acquire(LAUNCH_LOCK_WAIT_S):
        return {"pid": _pid_of(_read_json_quiet(mpath)) or None, "job_id": jid,
                "relaunches": relaunch_count(run_dir, job), "launched": False, "state": "running"}
    try:
        relaunches = relaunch_count(run_dir, job)
        if is_done(run_dir, job):
            return {"pid": None, "job_id": jid, "relaunches": relaunches, "launched": False, "state": "done"}
        exists, live, m = _marker_live(mpath)
        if exists and (live or _stale_but_alive(mpath, m)):
            return {"pid": _pid_of(m) or None, "job_id": jid, "relaunches": relaunches, "launched": False,
                    "state": "running"}
        if exists and not _stop_stale_worker(m):
            return {"pid": _pid_of(m) or None, "job_id": jid, "relaunches": relaunches, "launched": False,
                    "state": "stuck"}
        if exists:
            relaunches = _note_relaunch(run_dir, job)
            _remove_quiet(mpath)
        os.makedirs(os.path.join(run_dir, "logs"), exist_ok=True)
        os.makedirs(os.path.dirname(mpath), exist_ok=True)
        log_path = os.path.join(run_dir, "logs", "%s.log" % jid)
        argv = worker_argv(job_path)
        if attached:
            lock.release()  # the attached worker takes the lock itself
            with open(log_path, "ab") as logf:
                p = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=logf, stderr=subprocess.STDOUT,
                                     env=_worker_env(), cwd=run_dir)
                rc = p.wait()
            return {"pid": p.pid, "job_id": jid, "relaunches": relaunches, "exit_code": rc, "launched": True}
        started = textio.now_iso()
        token = binascii.hexlify(os.urandom(12)).decode("ascii")
        with open(log_path, "ab") as logf:
            p = _spawn_detached(argv, logf, run_dir, token)
        _keep(p)
        try:
            textio.write_json_atomic(mpath, {"pid": p.pid, "started_at": started, "heartbeat_at": textio.now_iso(),
                                             "attempt": 0, "backend": None, "token": token})
        except OSError:
            pass  # the worker writes its own marker as soon as it holds the lock
        return {"pid": p.pid, "job_id": jid, "relaunches": relaunches, "launched": True}
    finally:
        lock.release()


def _keep(p):
    _reap()
    _LIVE.append(p)


def _is_worker(pid, marker):
    """True when pid plausibly is the worker named by marker: the process started no later than the marker's
    started_at (a reused pid starts later). Unknown start times count only for markers younger than 6 h."""
    started = _parse_iso((marker or {}).get("started_at"))
    t = proc.process_start_time(pid)
    if t is not None and started is not None:
        return t <= started + 5
    return started is not None and time.time() - started < 6 * 3600


def _stale_but_alive(path, marker):
    """A marker whose heartbeat is stale for less than 2 x stale_after_s while its worker pid still runs."""
    pid = (marker or {}).get("pid")
    if not pid or not proc.pid_alive(pid) or not _is_worker(pid, marker):
        return False
    hb = _parse_iso((marker or {}).get("heartbeat_at"))
    if hb is None:
        try:
            hb = os.path.getmtime(path)
        except OSError:
            return False
    return (time.time() - hb) <= 2 * stale_after_s()


def _owned(pid):
    """The Popen object for pid when this process started it (so the kill also reaps it), else None."""
    for p in _LIVE:
        if p.pid == pid:
            return p
    return None


def _reap():
    for p in list(_LIVE):
        if p.poll() is not None:
            _LIVE.remove(p)


def _remove_quiet(path):
    try:
        os.remove(path)
    except OSError:
        pass


# ---------------------------------------------------------------- foreground batch

def _job_file_for(job):
    """A path for a job given as a path or a dict (dicts are written to <run>/.ub/jobs/<id>.job.json)."""
    if not isinstance(job, dict):
        return os.path.abspath(os.fspath(job))
    if job.get("_path") and os.path.isfile(job["_path"]):
        return job["_path"]
    run_dir = os.path.abspath(job.get("run") or ".")
    path = os.path.join(_jobs_dir(run_dir), "%s.job.json" % job.get("id"))
    textio.write_json_atomic(path, {k: v for k, v in job.items() if not str(k).startswith("_")})
    return path


def _settled_state(job):
    """job_state, re-read a few times while it says "running": a lock probe by another driver or `ub status` holds
    the lock for a moment and must not make a free job look held (run_foreground acts on the answer at once)."""
    st = job_state(job.get("run"), job)
    for _i in range(3):
        if st != "running":
            break
        time.sleep(0.1)
        st = job_state(job.get("run"), job)
    return st


def run_foreground(jobs, parallel=4, budget_s=None):
    """Run jobs as attached worker processes, at most `parallel` at a time.

    Jobs already done (content-addressed cache) are not re-run. When budget_s runs out, no new job starts;
    jobs still running keep running in the background and are reported as pending, like unstarted ones. A job that
    another worker holds (its own worker then exits without a call) is reported as pending too.
    """
    parallel = max(1, int(parallel or 1))
    t0 = time.monotonic()
    queue = []
    for j in jobs or []:
        path = _job_file_for(j)
        job = _load(path)
        queue.append((job.get("id"), path, job))
    done, failed, pending = [], [], []
    running = {}
    try:
        while queue or running:
            for jid in list(running):
                p, logf, path, job = running[jid]
                if p.poll() is None:
                    continue
                logf.close()
                del running[jid]
                st = _settled_state(job)
                if st == "done":
                    done.append(jid)
                elif st == "running":
                    pending.append(jid)  # another worker holds the job; ours exited without a call
                else:
                    failed.append(jid)
            if budget_s is not None and time.monotonic() - t0 >= float(budget_s):
                break
            while queue and len(running) < parallel:
                jid, path, job = queue.pop(0)
                st = _settled_state(job)
                if st == "done":
                    done.append(jid)
                    continue
                if st == "running":
                    pending.append(jid)  # another driver's live worker owns it
                    continue
                run_dir = os.path.abspath(job.get("run") or ".")
                os.makedirs(os.path.join(run_dir, "logs"), exist_ok=True)
                logf = open(os.path.join(run_dir, "logs", "%s.log" % jid), "ab")
                try:
                    p = subprocess.Popen(worker_argv(path), stdin=subprocess.DEVNULL, stdout=logf,
                                         stderr=subprocess.STDOUT, env=_worker_env(), cwd=run_dir)
                except OSError:
                    logf.close()
                    failed.append(jid)
                    continue
                running[jid] = (p, logf, path, job)
            if queue or running:
                time.sleep(POLL_S)
    finally:
        for jid in list(running):
            p, logf, _path, _job = running[jid]
            try:
                logf.close()
            except OSError:
                pass
            _keep(p)
            pending.append(jid)
    pending += [jid for jid, _p, _j in queue]
    return {"done": done, "failed": failed, "pending": pending, "elapsed_s": round(time.monotonic() - t0, 2)}


def dumps(obj):
    return json.dumps(obj, ensure_ascii=True)
