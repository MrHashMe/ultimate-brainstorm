"""Detached worker launch, heartbeat, job state, foreground batch (KIT_SPEC 4.7, 6.3).

Frozen API (4.8):
    launch_job(job_path, expect_gen=None) -> dict   {"pid": int, "job_id": str} (+ "relaunches", "launched", "state",
                                                 "refused", "exit_code" attached; "state" is "done", "running",
                                                 "stuck", "failed" or "pending"; "refused" is "stopped")
    job_state(run_dir, job) -> str               done|running|dead|failed|pending
    running_jobs(run_dir) -> list                job ids with live markers (or a held execution lock)
    stop_all(run_dir) -> int                     kills the run's verified workers; returns the count
    stop_workers(run_dir, keep=None) -> dict     the same, {"stopped": int, "unverified": [pid, ...]}: a live worker
                                                 whose identity cannot be read keeps its marker and is listed
    run_foreground(jobs, parallel=4, budget_s=None) -> dict   {"done": [...], "failed": [...], "pending": [...]}

Extras: WorkerMarker (used by `family.py job`), JobLock, lock_state(run_dir, job_id), is_done(run_dir, job),
        job_gen(run_dir, job_id), relaunch_count(run_dir, job), reset_relaunch(run_dir, job_id),
        stop_requested(run_dir), worker_argv(job_path), marker_path(run_dir, job_id), lock_path(run_dir, job_id),
        stale_after_s(), RELAUNCH_LIMIT, STOP_FILE, EXIT_STOPPED, STOP_GRACE_S.

One worker per job (4.7, execution lock). A worker holds .ub/jobs/<id>.lock, an OS file lock (textio.try_lock_fd:
msvcrt.locking on Windows, flock on POSIX), from before it writes its running marker until after it has deleted it.
The OS drops the lock when the process ends, even when it is killed, so a dead worker never leaves a stale claim.
Therefore:
  - a worker starts no model call while another process holds the job, and it re-checks the done rule once it holds
    the lock: a job that finished meanwhile is never called again (the worker exits 0, "skipped"). Nor is a job that
    another worker finished running (ok or failed) since this one was launched: every worker that ran a job counts
    one more run in .ub/jobs/<id>.gen (the job's outcome generation) before it lets the lock go, and launch_job hands
    the generation it launched at to the worker (UB_EXPECT_GEN);
  - launch_job takes the same lock while it decides and spawns. It does not launch a job that is done, whose lock is
    held or whose marker stands, or whose generation moved since the caller read the job's state; and it writes the
    marker (with the child's pid, its process identity and a launch token) before the child can take the lock, so
    nothing races its write (a marker is never re-created after its worker deleted it). The worker recognizes that
    marker as its own by the token (UB_LAUNCH_TOKEN), not by the pid: in a Windows venv the pid launch_job sees is the
    venv redirector's, and the worker is its child;
  - job_state reports a job whose lock is held as running whatever its heartbeat says. A marker the worker wrote
    while it held the lock ("locked") is dead as soon as the lock is free. Only a launch marker (its worker has not
    taken the lock yet) is judged by its process and heartbeat.
On a file system without file locks the marker and heartbeat rules alone apply.

Process identity: a marker records the process identity (creation time, proc.process_identity) of its worker and of
the backend process the worker runs. A process is killed (stop_all, relaunch) only when its pid still has that
identity; an unknown identity is never killed, so a reused pid never is.

Stop: while <run>/.ub/STOP exists (`ub stop`), launch_job launches nothing and a starting worker exits with code 8
(EXIT_STOPPED) before any backend call, without a meta.

Test hooks (4.19): UB_NO_DETACH=1 runs the worker attached; UB_HEARTBEAT_STALE_S overrides the 60 s threshold.
"""

import binascii
import calendar
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
           "lock_state", "is_done", "job_gen", "relaunch_count", "reset_relaunch", "stop_requested", "worker_argv",
           "marker_path", "lock_path", "stale_after_s", "RELAUNCH_LIMIT", "HEARTBEAT_S", "STOP_FILE", "EXIT_STOPPED",
           "STOP_GRACE_S", "stop_workers", "stopping", "stopping_path"]

HEARTBEAT_S = 10.0
STALE_DEFAULT_S = 60.0
RELAUNCH_LIMIT = 3
POLL_S = 0.2
STOP_FILE = "STOP"         # <run>/.ub/STOP: the run is stopped (C3)
EXIT_STOPPED = 8           # the worker's exit code for a stopped run (no call, no meta)
LAUNCH_TOKEN_ENV = "UB_LAUNCH_TOKEN"  # launch_job -> worker: which launcher-written marker is the worker's own
EXPECT_GEN_ENV = "UB_EXPECT_GEN"      # launch_job -> worker: the job's outcome generation at launch
LOCK_WAIT_S = 30.0         # a starting worker waits this long for its launcher (or a state probe) to let go
LAUNCH_LOCK_WAIT_S = 1.0   # launch_job waits this long for the lock before it reports the job as running
MARKER_REMOVE_S = 2.0      # a worker retries deleting its marker this long (a reader may hold it open on Windows)
STOP_GRACE_S = proc.ABORT_GRACE_S + 5.0  # SIGTERM -> SIGKILL for a worker: it stops its own backend process first
STOPPING_MAX_AGE_S = 600.0  # a .ub/jobs/<id>.stopping file older than this is a crashed stopper's: ignored

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


def _gen_path(run_dir, job_id):
    return os.path.join(_jobs_dir(run_dir), "%s.gen" % job_id)


def stopping_path(run_dir, job_id):
    return os.path.join(_jobs_dir(run_dir), "%s.stopping" % job_id)


def stop_requested(run_dir):
    """True while <run>/.ub/STOP exists: `ub stop` creates it before it stops the workers, and an explicit resume
    removes it. launch_job launches nothing then, and a starting worker exits (code 8) before any backend call."""
    return os.path.exists(os.path.join(os.path.abspath(run_dir), ".ub", STOP_FILE))


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

class JobLock(object):
    """The execution lock of one job (module note): textio.try_lock_fd on .ub/jobs/<id>.lock (a byte far beyond EOF on
    Windows, so the file stays empty and readable). The file is never deleted: deleting a lock file races with a
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
            got = textio.try_lock_fd(fd)
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
        textio.unlock_fd(fd)
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

def _read_marker(path):
    """(exists, marker dict, {} when unreadable). A marker that vanished while it was read does not exist."""
    if not os.path.isfile(path):
        return False, {}
    m = _read_json_quiet(path)
    if m is None and not os.path.isfile(path):
        return False, {}
    return True, m or {}


def _heartbeat_age(path, marker):
    """Seconds since the marker's heartbeat (its file time when it has none). A heartbeat in the future (a clock step,
    a copied run folder) counts as infinitely old: it would otherwise keep a dead job "running" for ever."""
    hb = _parse_iso(marker.get("heartbeat_at"))
    if hb is None:
        try:
            hb = os.path.getmtime(path)
        except OSError:
            return float("inf")
    age = time.time() - hb
    return age if age >= -5.0 else float("inf")


def _alive(pid, ident):
    """For liveness only (never enough to kill): pid runs and, when an identity was recorded, it is still that process
    (a reused pid is not)."""
    return proc.same_process(pid, ident) if ident else proc.pid_alive(pid)


def _stands(path, marker, held):
    """True while a running marker may still stand for a live worker, so the job must not be relaunched. held is the
    job's lock_state() (a holder is running anyway). Where file locks work (held is False), a marker that its worker
    wrote while holding the lock ("locked") is dead: the lock is free only once that worker is gone. A launch marker
    (its worker has not taken the lock yet) and every marker on a file system without file locks (held is None) stand
    while the process they name runs (with the recorded identity) and the heartbeat is at most 2 x stale_after_s()
    old: a late heartbeat (sleep, heavy load) must not lead to a second worker."""
    if held is False and marker.get("locked"):
        return False
    if _heartbeat_age(path, marker) > 2 * stale_after_s():
        return False
    pid = _pid_of(marker)
    return not pid or _alive(pid, marker.get("ident"))


LEGACY_START_SLACK_S = 5.0  # kit 2.0.3's rule for its markers: the process started at most this long after started_at


def _legacy_ident(pid, marker):
    """The identity of pid when a marker without an "ident" key (written by kit 2.0.3, before identities) names it by
    2.0.3's own rule: the process that has pid now started no later than the marker's started_at + 5 s (a pid reused
    later is another process). None when that cannot be shown."""
    started_at = _parse_iso(marker.get("started_at"))
    started = proc.process_start_time(pid)
    if started_at is None or started is None or started > started_at + LEGACY_START_SLACK_S:
        return None
    return proc.process_identity(pid)


def _marker_processes(marker):
    """[(pid, identity)] of the worker a marker names and of the backend process that worker recorded (worker first).
    A 2.0.3 marker has no identity: its worker's is established by _legacy_ident, so an in-flight 2.0.3 worker can be
    stopped after an in-place update."""
    return [(pid, ident) for pid, ident, _rec in _marker_records(marker)]


def _marker_records(marker):
    """[(pid, identity, record)] behind _marker_processes: the record is the marker or its "child" dict."""
    child = marker.get("child") if isinstance(marker.get("child"), dict) else {}
    out = []
    for rec in (marker, child):
        pid = _pid_of(rec)
        if pid and pid != os.getpid():
            out.append((pid, rec.get("ident") if "ident" in rec or rec is child else _legacy_ident(pid, rec), rec))
    return out


def _unverifiable(pid, ident, rec, legacy):
    """True when pid runs but it cannot be told whether it is the process the marker names: no identity was recorded
    (a worker that could not read its own), or the process's identity cannot be read now (ps unavailable or failing on
    macOS). Such a process is never killed, and its marker is kept (#2). A 2.0.3 marker (legacy) is unverifiable only
    when its start-time rule cannot be applied; a process shown to start later is a reused pid. Where identities come
    from the system itself (Windows, Linux: this process reads its own), one that cannot be read belongs to another
    user (a service, SYSTEM), never to a worker of the run, which runs as this user: that marker goes."""
    if not proc.pid_alive(pid):
        return False
    now = proc.process_identity(pid)
    if now is None and (proc.process_identity(os.getpid()) or "").split(":", 1)[0] in ("win", "linux"):
        return False  # another user's process holds the pid (ps, by contrast, reads every user's processes)
    if legacy:
        started_at = _parse_iso(rec.get("started_at"))
        return started_at is None or proc.process_start_time(pid) is None
    return not ident or now is None


def _expected_gen():
    try:
        return int(os.environ.get(EXPECT_GEN_ENV) or "")
    except ValueError:
        return None


class WorkerMarker(object):
    """The worker's side of 4.7. On enter it takes the job's execution lock (waiting for its launcher to let go),
    re-checks the done rule, writes the running marker and refreshes its heartbeat from a thread; while the job runs,
    the marker also names the backend process the worker started (proc.set_spawn_hook), so that process can be stopped
    even when the worker is killed hard. On exit it leaves the crash evidence below, counts the run in the job's outcome
    generation, deletes the marker and only then releases the lock.

    `skipped` is set when the caller must not run the job: "running" (another process holds the job), "done" (the
    done rule already holds, so there is nothing to call), "finished" (another worker finished a run of the job since
    this one was launched, or since it started: its outcome stands, even a failure) or "stopped" (the run is stopped,
    stop_requested()). A skipped worker never writes the marker of the process that holds the job, nor any output.

    Crash evidence (4.7, C5): a worker that ran the job and ends without an outcome for its prompt (no meta, or a meta
    without the prompt hash) writes a minimal failed meta itself, so the job reads "failed" rather than "pending". That
    holds for an unexpected error (error_class "internal") and for a signal that ends the worker (error_class "killed":
    SystemExit from SIGTERM or SIGBREAK, KeyboardInterrupt from Ctrl+C), except in three cases that leave no evidence,
    so the job reads "pending": the run is stopped (`ub stop` creates STOP before it stops the workers; the stop exit
    code EXIT_STOPPED), the kit itself is stopping this job (its .ub/jobs/<id>.stopping file, stopping()), or the job's
    prompt changed or moved away while it ran (the job was superseded: a newer prompt is never marked). When even that
    write fails (a full disk), the marker stays: the job reads "dead" and the relaunch limit applies.
    """

    def __init__(self, run_dir, job_id, pid=None, job=None, lock_wait_s=None):
        self.run_dir = run_dir
        self.job_id = job_id
        self.job = job
        self.path = marker_path(run_dir, job_id)
        self.token = (os.environ.get(LAUNCH_TOKEN_ENV) or "").strip() or None
        pid = pid or os.getpid()
        self.data = {"pid": pid, "ident": proc.process_identity(pid), "started_at": textio.now_iso(),
                     "heartbeat_at": textio.now_iso(), "attempt": 0, "backend": None}
        if self.token:
            self.data["token"] = self.token
        gen = _expected_gen()  # the generation launch_job launched us at; else the one at our start
        self._gen0 = job_gen(run_dir, job_id) if gen is None else gen
        self._prompt_sha = None
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

    def _child(self, pid, ident):
        """proc's spawn hook: the backend process the worker runs now ({pid, ident}), removed once it is gone."""
        with self._lock:
            if pid:
                self.data["child"] = {"pid": pid, "ident": ident}
            else:
                self.data.pop("child", None)
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
        return bool(pid) and pid != os.getpid() and _alive(pid, m.get("ident"))

    def _remove_own_marker(self):
        if self._is_own(_read_json_quiet(self.path)):
            _remove_quiet(self.path)

    def _remove_marker(self):
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

    def _record_outcome(self, exc_type):
        """True when the job has an outcome for the prompt this run ran: it is done, or a failed meta exists for that
        prompt (the adapter's, or a crash meta without the prompt hash, which gets it here), or a minimal failed meta
        could be written now. False when nothing could be written."""
        if not self._prompt_sha or is_done(self.run_dir, self.job):
            return True
        job = _load(self.job)
        _run, _prompt, out_path = _paths(self.run_dir, job)
        meta = _read_json_quiet(out_path + ".meta.json") or {}
        failed = meta.get("id") == job.get("id") and bool(meta.get("status")) and meta.get("status") != "ok"
        if failed and meta.get("prompt_sha256") == self._prompt_sha:
            return True
        ours = (_parse_iso(meta.get("started")) or 0) >= (_parse_iso(self.data["started_at"]) or 0)
        if failed and ours and meta.get("prompt_sha256") is None:  # a crash meta of this run: it never counted
            rec, reason = dict(meta, prompt_sha256=self._prompt_sha), None
        else:
            # "killed": a signal stopped the worker (the engine's card then names hosts that stop background work)
            by_signal = exc_type is not None and not issubclass(exc_type, Exception)
            reason = ("the worker was stopped by a signal%s before it recorded an outcome" if by_signal else
                      "the worker ended without recording an outcome%s") % (
                " (%s)" % exc_type.__name__ if exc_type else "")
            rec = {"schema": 1, "id": job.get("id"), "family": job.get("family"),
                   "provisional": bool(job.get("provisional")), "status": "failed",
                   "attempts": self.data.get("attempt") or 0, "exit_code": None,
                   "error_class": "killed" if by_signal else "internal", "started": self.data["started_at"],
                   "duration_s": None, "prompt_sha256": self._prompt_sha, "out_sha256": None, "reason": reason}
        try:
            textio.write_json_atomic(out_path + ".meta.json", rec)
        except OSError:
            return False
        if reason:
            try:
                textio.write_text_atomic(out_path + ".failed.md", "FAMILY CALL FAILED: %s\n" % reason)
            except OSError:
                pass
        return True

    def _signal_evidence(self, exc):
        """True when a worker that a signal ends (SystemExit, KeyboardInterrupt) records its outcome like a crash: not
        in a stopped run, not while the kit itself stops this job (stopping()), and only while the job's prompt is
        still the one this worker ran."""
        if stop_requested(self.run_dir) or (isinstance(exc, SystemExit) and exc.code == EXIT_STOPPED):
            return False
        if stopping(self.run_dir, self.job_id):
            return False
        return bool(self._prompt_sha) and _prompt_sha(self.run_dir, self.job) == self._prompt_sha

    def __enter__(self):
        if not self.lock.acquire(self.lock_wait_s, give_up=self._held_elsewhere):
            self.skipped = "running"
            return self
        try:
            if self.job is not None:
                if is_done(self.run_dir, self.job):
                    self.skipped = "done"
                elif job_gen(self.run_dir, self.job_id) != self._gen0:
                    self.skipped = "finished"
                if self.skipped:
                    self._remove_own_marker()  # the launcher wrote it for us; the finished job needs no marker
                    return self
            if self.lock.exclusive:
                self.data["locked"] = True  # from now on, a free lock means this worker is gone
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            self._write()
            # After the marker is written: `ub stop` creates STOP before it stops the workers, so it either sees this
            # marker or this worker sees STOP.
            if stop_requested(self.run_dir):
                self.skipped = "stopped"
                self._remove_own_marker()
                return self
            if self.job is not None:
                self._prompt_sha = _prompt_sha(self.run_dir, self.job)
            self._thread = threading.Thread(target=self._beat, name="ub-heartbeat", daemon=True)
            self._thread.start()
            proc.set_spawn_hook(self._child)
        except BaseException:
            self.lock.release()
            raise
        return self

    def __exit__(self, exc_type, exc, tb):
        try:
            if self.skipped is None:
                proc.set_spawn_hook(None)
                self._stop.set()
                if self._thread is not None:
                    self._thread.join(timeout=5)
                recorded = True
                if self.job is not None:
                    if exc_type is None or issubclass(exc_type, Exception) or self._signal_evidence(exc):
                        recorded = self._record_outcome(exc_type)
                    _bump_gen(self.run_dir, self.job_id)
                if recorded:
                    self._remove_marker()
        finally:
            self.lock.release()  # after the marker is gone: see job_state
        return False


# ---------------------------------------------------------------- state

def _prompt_sha(run_dir, job):
    _run, prompt_path, _out = _paths(run_dir, _load(job))
    try:
        return textio.sha256_file(prompt_path)
    except OSError:
        return None


def job_gen(run_dir, job_id):
    """The job's outcome generation: how many worker runs of it have finished (.ub/jobs/<id>.gen; 0 when none). Read it
    BEFORE job_state() and pass it to launch_job(expect_gen=...): if a run finished in between, the state read is stale
    and launch_job launches nothing."""
    try:
        return int(textio.read_text(_gen_path(run_dir, job_id)).strip() or 0)
    except (OSError, ValueError):
        return 0


def _bump_gen(run_dir, job_id):
    """One more finished run (the worker counts it while it holds the job's execution lock)."""
    try:
        textio.write_text_atomic(_gen_path(run_dir, job_id), "%d\n" % (job_gen(run_dir, job_id) + 1))
    except OSError:
        pass


def is_done(run_dir, job):
    """The done rule (4.4): <out>.meta.json is this job's, has status ok and the prompt_sha256 of the current prompt
    file, and its out_sha256 is the hash of <out> as it is now (the adapter validated <out> once, when it wrote it).
    A meta without out_sha256 (older runs) instead needs <out> to validate against the contract. A host meta (backend
    "host") may also carry the hash of the decoded text of <out>, the form kit 2.0.3 wrote for host outputs."""
    job = _load(job)
    run_dir, prompt_path, out_path = _paths(run_dir, job)
    meta = _read_json_quiet(out_path + ".meta.json")
    if not meta or meta.get("status") != "ok" or meta.get("id") != job.get("id") or not os.path.isfile(out_path) \
            or not os.path.isfile(prompt_path):
        return False
    try:
        if meta.get("prompt_sha256") != textio.sha256_file(prompt_path):
            return False
        if meta.get("out_sha256"):
            if meta["out_sha256"] == textio.sha256_file(out_path):
                return True
            return meta.get("backend") == "host" and \
                meta["out_sha256"] == textio.sha256_text(textio.read_text(out_path))
        text = textio.read_text(out_path)
    except OSError:
        return False
    ok, _errors, _parsed = validate.check_contract(text, job.get("contract") or {"type": "text"}, run_dir)
    return ok


def _failed_meta(prompt_path, meta):
    """True when meta records a failed run (status set and not ok) of the current prompt."""
    if not meta or not meta.get("status") or meta.get("status") == "ok" or not os.path.isfile(prompt_path):
        return False
    try:
        return meta.get("prompt_sha256") == textio.sha256_file(prompt_path)
    except OSError:
        return False


def job_state(run_dir, job):
    """done | running | dead | failed | pending (4.7)."""
    job = _load(job)
    # Read the marker and the execution lock BEFORE the done check. A worker writes <out> and its meta, deletes its
    # marker, and only then releases its lock, so in this order "no marker and no lock holder" means the outputs of a
    # finished worker are already on disk. The other order lets a worker that finishes between the reads look
    # "pending" (not done yet, no marker any more), and the dispatcher would launch the finished job a second time.
    run_dir, prompt_path, out_path = _paths(run_dir, job)
    mpath = marker_path(run_dir, job.get("id"))
    exists, m = _read_marker(mpath)
    held = lock_state(run_dir, job.get("id"))
    if is_done(run_dir, job):
        return "done"
    if held:
        return "running"  # a worker (or a launcher starting one) holds the job, whatever its heartbeat says
    if exists and _stands(mpath, m, held):
        return "running"  # a starting worker, or no file locks here: a live process with a recent heartbeat
    meta = _read_json_quiet(out_path + ".meta.json")
    if exists:
        # A marker whose worker is gone although it wrote a failed meta during this launch: the job failed; it did not
        # die (a worker that fails writes its meta before it deletes its marker; a crash in between leaves both).
        return "failed" if _failed_during(m, prompt_path, meta) else "dead"
    return "failed" if _failed_meta(prompt_path, meta) else "pending"


def _failed_during(marker, prompt_path, meta):
    """True when meta records a failed run of the current prompt that started during the marker's launch (not an
    older failure the launch was a retry of)."""
    m_start = _parse_iso((marker or {}).get("started_at"))
    meta_start = _parse_iso((meta or {}).get("started"))
    return _failed_meta(prompt_path, meta) and m_start is not None and meta_start is not None and meta_start >= m_start


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


def reset_relaunch(run_dir, job_id):
    """Forget the job's relaunch count (the driver retries a BLOCKED step)."""
    _remove_quiet(_relaunch_path(run_dir, job_id))


def _markers(run_dir):
    """[(job id, marker path)] of the run's running markers. Ids starting with "_" are reserved (the driver lock)."""
    d = _jobs_dir(run_dir)
    if not os.path.isdir(d):
        return []
    return [(name[:-len(".running.json")], os.path.join(d, name)) for name in sorted(os.listdir(d))
            if name.endswith(".running.json") and not name.startswith("_")]


def running_jobs(run_dir):
    out = []
    for jid, path in _markers(run_dir):
        exists, m = _read_marker(path)
        held = lock_state(run_dir, jid)
        if held or (exists and _stands(path, m, held)):
            out.append(jid)
    return out


def stop_all(run_dir, keep=None):
    """Stop every worker of the run, and the backend process each one recorded, and remove their markers. A process is
    killed only when it verifiably is the one its marker names (same pid and process identity): an unknown identity
    is never killed. The worker goes first, with a grace (STOP_GRACE_S) longer than the one it gives its own backend
    process. keep: job ids whose workers go on untouched (a supersede stops only the jobs of the steps it redoes).
    Returns the number of jobs whose processes were stopped (stop_workers also names the unverifiable ones)."""
    return stop_workers(run_dir, keep)["stopped"]


def stop_workers(run_dir, keep=None):
    """stop_all's work: {"stopped": jobs whose processes were stopped, "unverified": [pids]}. A marker whose process
    runs but cannot be verified (_unverifiable) is kept, not removed, and its pid is listed, so `ub stop` can say
    which workers to stop by hand; every other marker is removed. While a job's processes are signalled, its
    .ub/jobs/<id>.stopping file tells the worker that the kit stopped it (no 'killed' evidence)."""
    count = 0
    unverified = []
    keep = set(keep or ())
    for _jid, path in _markers(run_dir):
        if _jid in keep:
            continue
        m = _read_json_quiet(path) or {}
        stopped, unknown = False, []
        with _Stopping(run_dir, _jid):
            for pid, ident, rec in _marker_records(m):
                if proc.same_process(pid, ident):  # checked again for the backend process, after its worker's stop
                    proc.kill_tree(pid, grace_s=STOP_GRACE_S, proc=_owned(pid))
                    stopped = True
                elif _unverifiable(pid, ident, rec, rec is m and "ident" not in m):
                    unknown.append(pid)
        count += 1 if stopped else 0
        unverified += unknown
        if not unknown:
            _remove_quiet(path)
    _reap()
    try:  # killed workers never ran their finally: delete their per-call folders (they can hold a provider token)
        from . import families as _fam
        from .backends import sweep_stale_calls
        if count:
            time.sleep(0.5)
        sweep_stale_calls(_fam.ub_home())
    except Exception:  # noqa: BLE001
        pass
    return {"stopped": count, "unverified": unverified}


class _Stopping(object):
    """.ub/jobs/<id>.stopping while the kit signals a job's processes (stop_workers, _stop_stale_worker): a worker that
    such a signal ends leaves no 'killed' failure evidence (WorkerMarker._signal_evidence), since the kit stopped it and
    the job reads pending again, not failed. A file older than STOPPING_MAX_AGE_S (a stopper that crashed) is
    ignored."""

    def __init__(self, run_dir, job_id):
        self.path = stopping_path(run_dir, job_id)

    def __enter__(self):
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            textio.write_text_atomic(self.path, "%d\n" % os.getpid())
        except OSError:
            pass
        return self

    def __exit__(self, exc_type, exc, tb):
        _remove_quiet(self.path)
        return False


def stopping(run_dir, job_id):
    """True while the kit is stopping the job's worker (a fresh .ub/jobs/<id>.stopping file)."""
    try:
        return time.time() - os.path.getmtime(stopping_path(run_dir, job_id)) < STOPPING_MAX_AGE_S
    except OSError:
        return False


# ---------------------------------------------------------------- launch

def _worker_env(token=None, gen=None):
    env = dict(os.environ)
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env.pop(LAUNCH_TOKEN_ENV, None)  # never inherited: only the launch that wrote the marker hands out its token
    env.pop(EXPECT_GEN_ENV, None)
    if token:
        env[LAUNCH_TOKEN_ENV] = token
    if gen is not None:
        env[EXPECT_GEN_ENV] = str(gen)
    return env


def _detach_kwargs(with_breakaway=True):
    if os.name == "nt":
        flags = _CREATE_NEW_PROCESS_GROUP | _DETACHED_PROCESS
        if with_breakaway:
            flags |= _CREATE_BREAKAWAY_FROM_JOB  # [U-24] survive a host that closes its job object
        return {"creationflags": flags}
    return {"start_new_session": True}


def _spawn_detached(argv, logf, run_dir, token=None, gen=None):
    try:
        return subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=logf, stderr=subprocess.STDOUT,
                                env=_worker_env(token, gen), cwd=run_dir, close_fds=True, **_detach_kwargs(True))
    except OSError:
        if os.name != "nt":
            raise
        # breakaway not allowed by the enclosing job object: retry without it  # [U-24]
        return subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=logf, stderr=subprocess.STDOUT,
                                env=_worker_env(token, gen), cwd=run_dir, close_fds=True, **_detach_kwargs(False))


def _stop_stale_worker(marker, run_dir, job_id):
    """A marker that no longer stands (job_state "dead"): stop the processes it names that verifiably still run (same
    pid and process identity) before a new worker starts: a worker that never took the lock or stopped beating on a
    file system without file locks, or the backend process of a worker that was killed hard. The job's .stopping file
    is held meanwhile (the kit stopped it: no 'killed' evidence). Returns False when one of them still runs."""
    procs = [(pid, ident) for pid, ident in _marker_processes(marker or {}) if proc.same_process(pid, ident)]
    if not procs:
        return True  # gone, or a reused pid (or unknown identity): never killed
    with _Stopping(run_dir, job_id):
        for pid, ident in procs:
            proc.kill_tree(pid, grace_s=STOP_GRACE_S, proc=_owned(pid))
            deadline = time.monotonic() + 10
            while proc.same_process(pid, ident) and time.monotonic() < deadline:
                time.sleep(0.1)
            if proc.same_process(pid, ident):
                return False
    return True


def launch_job(job_path, expect_gen=None):
    """Start `family.py job --job <abs job.json>` as a detached worker (attached with UB_NO_DETACH=1).

    The decision is re-checked under the job's execution lock: a job that is done, whose lock another process holds
    or whose marker stands is not launched ({"launched": false, "state": "done"|"running"}). Nor is one whose outcome
    generation moved from expect_gen, the job_gen() the caller read before its job_state(): a run finished since, so
    the caller's state is stale ({"launched": false, "state": "failed"|"pending"}). A dead marker is removed (the
    processes it names are stopped first when they verifiably still run) and the relaunch is counted in
    .ub/jobs/<id>.relaunch. When such a process cannot be stopped, nothing is launched and the state is "stuck" (the
    driver shows a BLOCKED card that suggests `ub stop`). While the run is stopped nothing is launched either
    ({"launched": false, "refused": "stopped"}). The running marker is written with the child's pid, its process
    identity and a launch token while the lock is still held, so a quick second poll never launches the job twice and
    the worker (which needs the lock) cannot finish and delete its marker before the write. The worker gets the
    generation it was launched at, and makes no call when another run finished before it got the lock.
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
        if stop_requested(run_dir):
            return {"pid": None, "job_id": jid, "relaunches": relaunches, "launched": False, "refused": "stopped"}
        if is_done(run_dir, job):
            return {"pid": None, "job_id": jid, "relaunches": relaunches, "launched": False, "state": "done"}
        gen = job_gen(run_dir, jid)
        if expect_gen is not None and gen != expect_gen:
            _run, prompt_path, out_path = _paths(run_dir, job)
            failed = _failed_meta(prompt_path, _read_json_quiet(out_path + ".meta.json"))
            return {"pid": None, "job_id": jid, "relaunches": relaunches, "launched": False,
                    "state": "failed" if failed else "pending"}
        exists, m = _read_marker(mpath)
        held = False if lock.exclusive else None  # we hold the lock, so no other process does
        if exists and _stands(mpath, m, held):
            return {"pid": _pid_of(m) or None, "job_id": jid, "relaunches": relaunches, "launched": False,
                    "state": "running"}
        if exists and not _stop_stale_worker(m, run_dir, jid):
            return {"pid": _pid_of(m) or None, "job_id": jid, "relaunches": relaunches, "launched": False,
                    "state": "stuck"}
        if exists:
            # The stopped worker may have finished meanwhile (it records its outcome and counts its run in the job's
            # generation on the way out): the outcome it recorded during its launch stands, and a new worker gets the
            # generation as it is now, or it would skip the job as "finished" by that old run.
            gen = job_gen(run_dir, jid)
            _run, prompt_path, out_path = _paths(run_dir, job)
            state = "done" if is_done(run_dir, job) else \
                "failed" if _failed_during(m, prompt_path, _read_json_quiet(out_path + ".meta.json")) else None
            if state:
                _remove_quiet(mpath)
                return {"pid": None, "job_id": jid, "relaunches": relaunches, "launched": False, "state": state}
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
                                     env=_worker_env(gen=gen), cwd=run_dir)
                rc = p.wait()
            return {"pid": p.pid, "job_id": jid, "relaunches": relaunches, "exit_code": rc, "launched": True}
        started = textio.now_iso()
        token = binascii.hexlify(os.urandom(12)).decode("ascii")
        with open(log_path, "ab") as logf:
            p = _spawn_detached(argv, logf, run_dir, token, gen)
        _keep(p)
        try:  # the identity is read while our Popen handle (Windows) or the unreaped child (POSIX) pins the pid
            textio.write_json_atomic(mpath, {"pid": p.pid, "ident": proc.process_identity(p.pid), "started_at": started,
                                             "heartbeat_at": textio.now_iso(), "attempt": 0, "backend": None,
                                             "token": token})
        except OSError:
            pass  # the worker writes its own marker as soon as it holds the lock
        return {"pid": p.pid, "job_id": jid, "relaunches": relaunches, "launched": True}
    finally:
        lock.release()


def _keep(p):
    _reap()
    _LIVE.append(p)


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
                if stop_requested(run_dir):
                    pending.append(jid)  # the run is stopped: its worker would exit without a call
                    continue
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
