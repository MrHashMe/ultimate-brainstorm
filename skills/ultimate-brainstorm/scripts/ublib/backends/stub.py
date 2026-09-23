"""Stub backend: deterministic outputs from ublib.stubs.respond(job, prompt) (B4). KIT_SPEC 4.17, 5.2.

Used when UB_FAKE_FAMILIES=1 (the chain is ["stub"]). The output goes through the same validation path as any
model output. ublib.stubs is imported lazily, so the adapter works before B4's module lands.
"""

from . import result, usage_block


def run(ctx):
    try:
        from .. import stubs  # lazy: owned by B4
    except ImportError:
        return result("unavailable", error_class="not_found", error="ublib.stubs is not installed", cmd="stub")
    failure = getattr(stubs, "StubFailure", None)
    try:
        text = stubs.respond(ctx.job, ctx.prompt)
    except Exception as e:  # noqa: BLE001 - any stub error is a failed attempt, never a crash
        if failure is not None and isinstance(e, failure):
            return result("failed", error_class="internal", error="stub failure injected (UB_STUB_FAIL)", cmd="stub",
                          exit_code=1)
        return result("failed", error_class="internal", error="stub error: %s" % e.__class__.__name__, cmd="stub",
                      exit_code=1)
    if not isinstance(text, str):
        return result("failed", error_class="bad_output", error="stub returned no text", cmd="stub", exit_code=0)
    return result("ok", text=text, usage=usage_block(source="none"), cmd="stub", exit_code=0, model=None)
