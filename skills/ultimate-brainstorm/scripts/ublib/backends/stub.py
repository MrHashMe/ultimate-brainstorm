"""Stub backend: deterministic outputs for UB_FAKE_FAMILIES=1 (the chain is ["stub"]). KIT_SPEC 4.17, 5.2.

The outputs come from the test harness, <kit>/tests/harness/stubs.py respond(job, prompt), loaded from that fixed
place next to the kit (never from a path in the environment). A release archive has no tests/ folder: there the stub
answers only PING jobs (family.py selftest, a fake preflight) and reports every other job unavailable. The output
goes through the same validation path as any model output.
"""

import importlib.util
import os
import sys
import threading

from .. import SK_DIR
from .. import textio
from . import result, usage_block

KIT_DIR = os.path.dirname(os.path.dirname(SK_DIR))
HARNESS_STUBS = os.path.join(KIT_DIR, "tests", "harness", "stubs.py")
_MODULE = "ub_harness_stubs"
# The harness module is in sys.modules while it executes: without this lock a second thread (the parallel pings of a
# fake preflight) would take that half-loaded module and fail with "stub error: AttributeError".
_LOAD_LOCK = threading.Lock()


def load_stubs():
    """The harness module, or None when this kit has no tests/harness/stubs.py (an installed release). Loaded once
    per process; concurrent callers wait until it is complete."""
    with _LOAD_LOCK:
        mod = sys.modules.get(_MODULE)
        if mod is not None:
            return mod
        if not os.path.isfile(HARNESS_STUBS):
            return None
        spec = importlib.util.spec_from_file_location(_MODULE, HARNESS_STUBS)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[_MODULE] = mod
        try:
            spec.loader.exec_module(mod)
        except BaseException:
            sys.modules.pop(_MODULE, None)
            raise
        return mod


def run(ctx):
    try:
        stubs = load_stubs()
    except Exception as e:  # noqa: BLE001 - a broken harness is a failed attempt, never a crash
        return result("failed", error_class="internal", error="stub harness error: %s" % e.__class__.__name__,
                      cmd="stub", exit_code=1, requests=1)
    if stubs is None:
        if (ctx.job.get("template") or "") == "PING":
            return result("ok", text="PONG", usage=usage_block(source="none"), cmd="stub", exit_code=0, requests=1)
        return result("unavailable", error_class="not_found", cmd="stub", error="UB_FAKE_FAMILIES=1 needs the test "
                      "harness %s, which only a source checkout of the kit has" % textio.to_posix(HARNESS_STUBS))
    failure = getattr(stubs, "StubFailure", None)
    try:
        text = stubs.respond(ctx.job, ctx.prompt)
    except Exception as e:  # noqa: BLE001 - any stub error is a failed attempt, never a crash
        if failure is not None and isinstance(e, failure):
            return result("failed", error_class="internal", error="stub failure injected (UB_STUB_FAIL)", cmd="stub",
                          exit_code=1, requests=1)
        return result("failed", error_class="internal", error="stub error: %s" % e.__class__.__name__, cmd="stub",
                      exit_code=1, requests=1)
    if not isinstance(text, str):
        return result("failed", error_class="bad_output", error="stub returned no text", cmd="stub", exit_code=0,
                      requests=1)
    return result("ok", text=text, usage=usage_block(source="none"), cmd="stub", exit_code=0, model=None, requests=1)
