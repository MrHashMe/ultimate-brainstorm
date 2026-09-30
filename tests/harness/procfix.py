"""Worker and process test helpers: family.py under test instrumentation, and small polling helpers.

Not a test module. Product code carries no test hooks beyond KIT_SPEC 4.19, so the instrumentation lives here: run
as a program, this file patches ublib in its own process and then runs family.py (runpy), which imports the same,
patched modules:

    python procfix.py job --job <job.json>          (argv(...) builds this command line)

- UB_TEST_START_GATE=<path>: wait (up to 120 s) until <path> exists before family.py starts.
- UB_TEST_LOCK_SIGNAL=<path>: create <path> the first time the worker's try to take its job's execution lock fails.
  The worker has then taken its baselines and waits for the lock: tests wait for this file instead of sleeping.
- UB_TEST_INJECT=crash: the adapter's validation raises RuntimeError after the (stub) model call: an unexpected
  worker error, recorded by adapter.crash_meta.
- UB_TEST_INJECT=crash-nometa: the same, and adapter.crash_meta raises too: the worker ends with no meta at all.
- UB_TEST_INJECT=enospc: every write of a *.meta.json file fails with ENOSPC (a full disk).
"""

import errno
import os
import runpy
import sys
import time

HARNESS = os.path.dirname(os.path.abspath(__file__))
KIT = os.path.dirname(os.path.dirname(HARNESS))
SCRIPTS = os.path.join(KIT, "skills", "ultimate-brainstorm", "scripts")
FAMILY_PY = os.path.join(SCRIPTS, "family.py")
START_GATE_ENV = "UB_TEST_START_GATE"
LOCK_SIGNAL_ENV = "UB_TEST_LOCK_SIGNAL"
INJECT_ENV = "UB_TEST_INJECT"


def argv(*args):
    """[python, procfix.py, *args]: `family.py *args` under this file's instrumentation."""
    return [sys.executable, os.path.abspath(__file__)] + list(args)


def wait_until(pred, timeout=60.0, step=0.05):
    """Poll pred() until it is true or timeout seconds pass; returns its last value."""
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pred():
            return True
        time.sleep(step)
    return bool(pred())


def touch(path):
    with open(path, "w") as f:
        f.write(str(os.getpid()))


def _instrument():
    if SCRIPTS not in sys.path:
        sys.path.insert(0, SCRIPTS)
    from ublib import adapter, batch, textio

    gate = os.environ.get(START_GATE_ENV)
    if gate:
        wait_until(lambda: os.path.exists(gate), timeout=120)
    signal_path = os.environ.get(LOCK_SIGNAL_ENV)
    if signal_path:
        real_try = batch.JobLock.try_acquire

        def try_acquire(self):
            got = real_try(self)
            if not got and not os.path.exists(signal_path):
                touch(signal_path)
            return got
        batch.JobLock.try_acquire = try_acquire
    inject = os.environ.get(INJECT_ENV) or ""
    if inject.startswith("crash"):
        def boom(*_a, **_k):
            raise RuntimeError("injected worker error")
        adapter._validate_and_write = boom
        if inject == "crash-nometa":
            adapter.crash_meta = boom
    elif inject == "enospc":
        real_write = textio._write_bytes_atomic

        def no_space(path, data):
            if os.fspath(path).endswith(".meta.json"):
                raise OSError(errno.ENOSPC, "No space left on device (injected)")
            return real_write(path, data)
        textio._write_bytes_atomic = no_space


if __name__ == "__main__":
    _instrument()
    sys.argv = [FAMILY_PY] + sys.argv[1:]
    runpy.run_path(FAMILY_PY, run_name="__main__")
