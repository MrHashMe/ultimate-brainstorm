"""Detached worker launch, heartbeat, job state, foreground batch (KIT_SPEC 4.7, 6.3).

Frozen API (4.8):
    launch_job(job_path) -> dict                 {"pid": int, "job_id": str} (+ "relaunches", "exit_code" attached)
    job_state(run_dir, job) -> str               done|running|dead|failed|pending
    running_jobs(run_dir) -> list                job ids with live markers
    stop_all(run_dir) -> int                     tree-kills live workers; returns the count
    run_foreground(jobs, parallel=4, budget_s=None) -> dict   {"done": [...], "failed": [...], "pending": [...]}

Extras: WorkerMarker (used by `family.py job`), is_done(run_dir, job), relaunch_count(run_dir, job),
        worker_argv(job_path), marker_path(run_dir, job_id), stale_after_s(), RELAUNCH_LIMIT.

Test hooks (4.19): UB_NO_DETACH=1 runs the worker attached; UB_HEARTBEAT_STALE_S overrides the 60 s threshold.
"""

import calendar
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

__all__ = ["launch_job", "job_state", "running_jobs", "stop_all", "run_foreground", "WorkerMarker", "is_done",
           "relaunch_count", "worker_argv", "marker_path", "stale_after_s", "RELAUNCH_LIMIT", "HEARTBEAT_S"]

HEARTBEAT_S = 10.0
STALE_DEFAULT_S = 60.0
RELAUNCH_LIMIT = 3
POLL_S = 0.2

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
    try:
        data = textio.read_json(path)
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


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
            hb = os.path.getmtime(path)  # unreadable mid-replace, or no heartbeat yet: use the file time
        except OSError:
            return False, False, None
    fresh = (now - hb) <= stale_after_s()
    pid = (m or {}).get("pid")
    alive = True if not pid else proc.pid_alive(pid)
    return True, bool(fresh and alive), m


class WorkerMarker(object):
    """The worker's running marker: written at start, heartbeat refreshed from a thread, deleted on exit."""

    def __init__(self, run_dir, job_id, pid=None):
        self.path = marker_path(run_dir, job_id)
        self.data = {"pid": pid or os.getpid(), "started_at": textio.now_iso(), "heartbeat_at": textio.now_iso(),
                     "attempt": 0, "backend": None}
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

    def __enter__(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        self._write()
        self._thread = threading.Thread(target=self._beat, name="ub-heartbeat", daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
        with self._lock:
            for _ in range(10):
                try:
                    if os.path.exists(self.path):
                        os.remove(self.path)
                    break
                except PermissionError:
                    time.sleep(0.05)
                except OSError:
                    break
        return False


# ---------------------------------------------------------------- state

def is_done(run_dir, job):
    """The done rule (4.4): <out> exists, the contract validates, and <out>.meta.json has status ok and the
    prompt_sha256 of the current prompt file."""
    job = _load(job)
    run_dir, prompt_path, out_path = _paths(run_dir, job)
    meta = _read_json_quiet(out_path + ".meta.json")
    if not meta or meta.get("status") != "ok" or not os.path.isfile(out_path) or not os.path.isfile(prompt_path):
        return False
    if meta.get("prompt_sha256") != textio.sha256_file(prompt_path):
        return False
    try:
        text = textio.read_text(out_path)
    except OSError:
        return False
    ok, _errors, _parsed = validate.check_contract(text, job.get("contract") or {"type": "text"}, run_dir)
    return ok


def job_state(run_dir, job):
    """done | running | dead | failed | pending (4.7)."""
    job = _load(job)
    if is_done(run_dir, job):
        return "done"
    run_dir, prompt_path, out_path = _paths(run_dir, job)
    exists, live, m = _marker_live(marker_path(run_dir, job.get("id")))
    if exists and live:
        return "running"
    if exists and _stale_but_alive(marker_path(run_dir, job.get("id")), m):
        return "running"  # a late heartbeat (sleep, heavy load): not dead yet, never relaunched twice
    meta = _read_json_quiet(out_path + ".meta.json")
    finished = False
    if meta and meta.get("status") and meta.get("status") != "ok" and os.path.isfile(prompt_path):
        finished = meta.get("prompt_sha256") == textio.sha256_file(prompt_path)
    if exists:
        # A stale marker left by launch_job's pid write racing a worker that already exited: the worker of THIS
        # launch wrote its meta after the marker was created, so the job failed; it did not die.
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
    if data.get("prompt_sha256") != textio.sha256_file(prompt_path):
        return 0
    try:
        return int(data.get("count") or 0)
    except (TypeError, ValueError):
        return 0


def _note_relaunch(run_dir, job):
    _run, prompt_path, _out = _paths(run_dir, job)
    n = relaunch_count(run_dir, job) + 1
    sha = textio.sha256_file(prompt_path) if os.path.isfile(prompt_path) else None
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
            _e, live, _m = _marker_live(os.path.join(d, name))
            if live:
                out.append(name[:-len(".running.json")])
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

def _worker_env():
    env = dict(os.environ)
    env.setdefault("PYTHONIOENCODING", "utf-8")
    return env


def _detach_kwargs(with_breakaway=True):
    if os.name == "nt":
        flags = _CREATE_NEW_PROCESS_GROUP | _DETACHED_PROCESS
        if with_breakaway:
            flags |= _CREATE_BREAKAWAY_FROM_JOB  # [U-24] survive a host that closes its job object
        return {"creationflags": flags}
    return {"start_new_session": True}


def launch_job(job_path):
    """Start `family.py job --job <abs job.json>` as a detached worker (attached with UB_NO_DETACH=1).

    The running marker is pre-written with the child's pid so a quick second poll never launches it twice.
    A relaunch of a `dead` job is counted in .ub/jobs/<id>.relaunch.
    """
    job_path = os.path.abspath(os.fspath(job_path))
    job = _load(job_path)
    jid = job.get("id")
    run_dir = os.path.abspath(job.get("run") or os.path.dirname(os.path.dirname(job_path)))
    mpath = marker_path(run_dir, jid)
    relaunches = relaunch_count(run_dir, job)
    exists, live, _m = _marker_live(mpath)
    if exists and not live:
        relaunches = _note_relaunch(run_dir, job)
        try:
            os.remove(mpath)
        except OSError:
            pass
    os.makedirs(os.path.join(run_dir, "logs"), exist_ok=True)
    os.makedirs(os.path.dirname(mpath), exist_ok=True)
    log_path = os.path.join(run_dir, "logs", "%s.log" % jid)
    argv = worker_argv(job_path)
    attached = (os.environ.get("UB_NO_DETACH") or "").strip() == "1"
    with open(log_path, "ab") as logf:
        if attached:
            p = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=logf, stderr=subprocess.STDOUT,
                                 env=_worker_env(), cwd=run_dir)
            rc = p.wait()
            return {"pid": p.pid, "job_id": jid, "relaunches": relaunches, "exit_code": rc}
        textio.write_json_atomic(mpath, {"pid": None, "started_at": textio.now_iso(),
                                         "heartbeat_at": textio.now_iso(), "attempt": 0, "backend": None})
        try:
            p = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=logf, stderr=subprocess.STDOUT,
                                 env=_worker_env(), cwd=run_dir, close_fds=True, **_detach_kwargs(True))
        except OSError:
            if os.name != "nt":
                _remove_quiet(mpath)
                raise
            try:
                # breakaway not allowed by the enclosing job object: retry without it  # [U-24]
                p = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=logf, stderr=subprocess.STDOUT,
                                     env=_worker_env(), cwd=run_dir, close_fds=True, **_detach_kwargs(False))
            except OSError:
                _remove_quiet(mpath)
                raise
    _keep(p)
    m = _read_json_quiet(mpath)
    if m is not None and not m.get("pid"):
        m["pid"] = p.pid
        try:
            textio.write_json_atomic(mpath, m)
        except OSError:
            pass
    return {"pid": p.pid, "job_id": jid, "relaunches": relaunches}


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


def run_foreground(jobs, parallel=4, budget_s=None):
    """Run jobs as attached worker processes, at most `parallel` at a time.

    Jobs already done (content-addressed cache) are not re-run. When budget_s runs out, no new job starts;
    jobs still running keep running in the background and are reported as pending, like unstarted ones.
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
                (done if job_state(job.get("run"), job) == "done" else failed).append(jid)
            if budget_s is not None and time.monotonic() - t0 >= float(budget_s):
                break
            while queue and len(running) < parallel:
                jid, path, job = queue.pop(0)
                st = job_state(job.get("run"), job)
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
