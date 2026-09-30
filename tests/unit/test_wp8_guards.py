"""WP8: guard tests that kill the mutants the phase A/B suites let survive (REPORT 5 invariants I1-I11).

Each class pins one guard with an in-process test (no fixed sleeps; another session is simulated by taking the driver
lock in the same process, which the kernel lock refuses exactly as it refuses another process):
- TerminalGuard: `ub run` lets go of the driver lock while the human types, and applies the answer only when nothing
  changed the run meanwhile (I3)
- BudgetGuard: a launch is admitted iff requests_used + reserve <= max_calls; the boundary is inclusive (I8)
- HostStampGuard: a host output is accepted only for the prompt its card handed out; an output or own meta of another
  prompt is moved aside, never re-stamped (I5)
- ProcGuard: a CLI past the stdout cap is stopped when it crosses the cap, not at the timeout (6.3 output flood); a
  descendant that holds the pipes is killed one linger after the child exits, not waited for (6.3 orphaned descendant)
- RedactGuard: a bare JWT and an opaque Bearer token are masked by their own shapes
"""

import io
import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fixtures", "engine"))
import engine_testlib as tl  # noqa: E402

from ublib import batch, proc, redact, textio  # noqa: E402
from ublib.engine import builders, pipeline, terminal  # noqa: E402
from ublib.engine import state as st  # noqa: E402

sys.path.insert(0, tl.SCRIPTS)
import ub  # noqa: E402


class Base(tl.EngineTestCase):
    def run_ub(self, *args, **kw):
        out = io.StringIO()
        with mock.patch.object(sys, "stdout", out):
            rc = ub.main([str(a) for a in args], deps=kw.get("deps") or tl.FakeDeps(detect=tl.fake_detect()))
        text = out.getvalue()
        return rc, (json.loads(text) if text.strip().startswith("{") else text)

    def new_run(self):
        rc, card = self.run_ub("init", "--host", "claude-code", "--text", "shift-swap app for nurses", "--root",
                               self.project, "--no-preflight", "--json")
        self.assertEqual((rc, card.get("gate")), (0, "G0"), card)
        return card["run"]


# ------------------------------------------------------------------------------------------------ I3 terminal

class OtherSessionStdin(object):
    """The terminal user's stdin. On the first read it records whether the driver lock is free (the terminal must
    have let go of it) and, when `change`, takes the lock as another session would and changes the run (G0 stays
    the gate that waits). Then the user types `go`."""

    def __init__(self, run_dir, change):
        self.run_dir = run_dir
        self.change = change
        self.lock_free = []
        self.lines = ["go\n", "\n"]

    def readline(self):
        if not self.lock_free:
            self.lock_free.append(batch.lock_state(self.run_dir, "_driver") is False)
            other = st.DriverLock(self.run_dir, "other")
            if self.change and other.acquire():
                try:
                    s = st.load(self.run_dir)
                    s.setdefault("notes", []).append("changed by another session")
                    st.save(self.run_dir, s)
                finally:
                    other.release()
        return self.lines.pop(0) if self.lines else ""


class TerminalGuard(Base):
    def answer_in_terminal(self, change):
        """One G0 card of `ub run --continue`, answered `go` on stdin. Returns (run, stdin, card, printed)."""
        run = self.new_run()
        stdin = OtherSessionStdin(run, change)
        lock = st.DriverLock(run, "terminal")
        self.assertTrue(lock.acquire())
        try:
            ctx = st.Ctx(run, st.load(run), tl.FakeDeps(detect=tl.fake_detect()))
            out = io.StringIO()
            card = terminal.run_loop(ctx, pipeline.load_steps(), lock, stdin=stdin, stdout=out, wait_s=0,
                                     max_cards=1)
            self.assertTrue(lock.held, "the terminal did not take the driver lock back after the answer")
        finally:
            lock.release()
        self.assertEqual(stdin.lock_free, [True], "the driver lock was held while the terminal waited for input")
        return run, card, out.getvalue()

    def test_the_lock_is_free_while_the_human_types(self):
        run, _card, _out = self.answer_in_terminal(change=False)
        g0 = st.load(run)["gates"]["G0"]
        self.assertEqual((g0["state"], g0["by"]), ("answered", "human"))  # nothing changed: the answer counts

    def test_an_answer_typed_while_another_session_changed_the_run_is_not_applied(self):
        run, card, out = self.answer_in_terminal(change=True)
        self.assertIn("changed in another session", out)
        state = st.load(run)
        self.assertIn("changed by another session", state.get("notes") or [])
        self.assertNotEqual((state["gates"].get("G0") or {}).get("state"), "answered",
                            "the terminal applied an answer typed for a run that changed meanwhile")
        self.assertEqual((card.get("type"), card.get("gate")), ("HUMAN", "G0"))


# ------------------------------------------------------------------------------------------------ I8 budget

PROBE_OUT = "## 1. Walk-through\nx\n## 2. Riskiest assumption\ny\n## 3. Probe design\nz\n## 4. Kill criterion\nw\n" \
            "RESULT: PENDING\n"


def probe_step():
    return {"id": "11.1", "stage": 11, "title": "Probe", "type": "DISPATCH", "fanout": "probe",
            "job": {"kind": "writer"}, "min_ok": 1, "after": []}


class BudgetGuard(Base):
    """requests_used + reserve <= max_calls admits a launch: the cap is inclusive."""

    def capped(self, cap, used):
        batch_ = tl.FakeBatch(outputs=lambda j: PROBE_OUT)
        ctx = self.make_ctx(deps=tl.FakeDeps(batch=batch_), families=("claude",))
        ctx.state["families"]["claude"]["chain"] = ["claude-cli"]  # (1 retry + 1) x 1 CLI run + 1 repair = 3
        ctx.state["budget"]["max_calls"] = cap
        if used:
            ctx.write("logs/calls.jsonl", '{"id": "earlier", "requests": %d}\n' % used)
        return ctx, batch_

    def test_a_launch_that_exactly_fits_the_cap_is_admitted(self):
        ctx, batch_ = self.capped(cap=7, used=4)  # 4 + 3 == 7
        self.assertEqual(pipeline._reserve(ctx, builders.build_jobs(ctx, probe_step())[0]), 3)
        card = pipeline.advance(ctx, [probe_step()], 0)
        self.assertEqual(batch_.launched, ["11.1"], card.get("say"))
        self.assertIsNone(ctx.state.get("interrupt"))

    def test_one_request_more_than_the_cap_is_refused(self):
        ctx, batch_ = self.capped(cap=7, used=5)  # 5 + 3 > 7
        card = pipeline.advance(ctx, [probe_step()], 0)
        self.assertEqual((card["type"], card.get("gate"), batch_.launched), ("HUMAN", "GB", []))


# ------------------------------------------------------------------------------------------------ I5 host outputs

class HostStampGuard(Base):
    """A host sub-agent's output is accepted only for the prompt its HOST_BATCH card handed out; an output or meta
    of another prompt is moved aside, never stamped with the current prompt's hash."""

    def host_ctx(self):
        ctx = self.make_ctx()
        ctx.state["families"]["claude"]["backend"] = "host"
        return ctx

    def rearm_with_new_input(self, ctx):
        """What gap_round_end / a G10 correction does: the step runs again and its prompt changes."""
        st.set_step(ctx.state, "11.1", "pending", note="another round", jobs=[])
        ctx.write("08_DECISION.md", "# DECISION: a new decision\n")

    def test_an_output_written_for_an_earlier_prompt_is_never_stamped(self):
        ctx = self.host_ctx()
        card = pipeline.advance(ctx, [probe_step()], 0)
        self.assertEqual(card["type"], "HOST_BATCH")
        job = card["jobs"][0]
        issued = textio.sha256_file(job["prompt_file"])
        # the sub-agent answers the prompt it was given, but the step is re-armed before the driver reads it
        textio.write_text_atomic(job["out"], PROBE_OUT)
        self.rearm_with_new_input(ctx)
        card = pipeline.advance(ctx, [probe_step()], 0)
        self.assertNotEqual(textio.sha256_file(job["prompt_file"]), issued, "the prompt did not change")
        self.assertEqual(card["type"], "HOST_BATCH", "an answer to the old prompt was accepted for the new one")
        self.assertFalse(os.path.exists(job["out"] + ".meta.json"))
        self.assertFalse(os.path.exists(job["out"]), "the old answer stayed in place")
        moved = [os.path.join(d, f) for d, _s, fs in os.walk(ctx.path("_superseded")) for f in fs]
        self.assertEqual([textio.read_text(p) for p in moved], [PROBE_OUT])

    def test_an_own_meta_of_another_prompt_always_moves_aside(self):
        ctx = self.host_ctx()
        card = pipeline.advance(ctx, [probe_step()], 0)
        out = card["jobs"][0]["out"]
        textio.write_text_atomic(out, PROBE_OUT)
        ctx.lease = ((ctx.state["steps"]["11.1"] or {}).get("lease") or {}).get("token")
        self.assertEqual(pipeline.advance(ctx, [probe_step()], 0)["type"], "DONE")
        old_meta = textio.read_json(out + ".meta.json")
        self.rearm_with_new_input(ctx)
        job = builders.build_jobs(ctx, probe_step())[0]
        sha = textio.sha256_file(ctx.path(job["prompt_file"]))
        self.assertNotEqual(old_meta["prompt_sha256"], sha)
        # whatever host_issued says (here: as if the new prompt's card were already out), an own meta of another
        # prompt is never re-validated and stamped
        ctx.state.setdefault("host_issued", {})[job["id"]] = sha
        self.assertEqual(pipeline.host_job_state(ctx, job), "pending")
        self.assertFalse(os.path.exists(out))
        self.assertFalse(os.path.exists(out + ".meta.json"))


# ------------------------------------------------------------------------------------------------ proc

# A CLI that answers, exits 0 and leaves a grandchild holding its stdout/stderr for 60 s (a Node child with stdio
# 'inherit', a .cmd shim's `start /b`). argv: <info file>; the info file gets "<grandchild pid> <exit time>".
ORPHAN_CLI = r'''
import subprocess, sys, time
kw = {"close_fds": False}
if sys.platform == "win32":
    kw["creationflags"] = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
g = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"], **kw)
sys.stdout.write("ANSWER\n")
sys.stdout.flush()
with open(sys.argv[1], "w") as f:
    f.write("%d %r" % (g.pid, time.time()))
'''


class ProcGuard(unittest.TestCase):
    def test_the_rest_of_the_tree_is_stopped_after_one_linger(self):
        """After the child exits, its readers get one linger to reach EOF; then the rest of its tree (the grandchild
        holding the pipes) is killed, so run() returns about one linger after the exit, not two."""
        tmp = tempfile.mkdtemp(prefix="ub-wp8-proc-")
        self.addCleanup(shutil.rmtree, tmp, True)
        info = os.path.join(tmp, "orphan.txt")
        linger = 3.0
        with mock.patch.object(proc, "_LINGER_S", linger):
            r = proc.run([sys.executable, "-c", ORPHAN_CLI, info], cwd=tmp, timeout_s=120)
        returned = time.time()
        with open(info) as f:
            gpid, exited = f.read().split()
        self.addCleanup(proc.kill_tree, int(gpid), 0.5)
        self.assertEqual((r.returncode, r.timed_out, r.stdout_bytes.strip()), (0, False, b"ANSWER"))
        after = returned - float(exited)
        self.assertLess(after, 1.5 * linger, "run() returned %.1f s after the child's exit: the grandchild was not "
                                             "stopped after the first linger (%.0f s)" % (after, linger))

    def test_a_child_past_the_stdout_cap_is_stopped_at_once(self):
        """A CLI that overflows the cap and keeps running is stopped when the cap is crossed, not at the timeout."""
        cap = 1 << 16
        code = ("import sys, time\nsys.stdout.buffer.write(b'z' * %d)\nsys.stdout.flush()\nt = time.time()\n"
                "while time.time() - t < 120:\n    time.sleep(0.05)\n" % (cap + 1))
        r = proc.run([sys.executable, "-c", code], timeout_s=60, max_stdout=cap)
        self.assertTrue(r.overflow)
        self.assertFalse(r.timed_out, "the overflowing child ran on until the timeout")
        self.assertEqual(len(r.stdout_bytes), cap)


# ------------------------------------------------------------------------------------------------ redaction

class RedactGuard(unittest.TestCase):
    JWT = "eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiJudXJzZS0wMDEifQ.c2lnbmF0dXJlLWJ5dGVzLTAx"

    def test_a_bare_jwt_is_masked(self):
        out = redact.redact("claude: session refreshed, id %s cached" % self.JWT)
        self.assertNotIn(self.JWT, out)
        self.assertNotIn(self.JWT.split(".")[1], out)
        self.assertIn(redact.MASK, out)

    def test_an_opaque_bearer_token_is_masked(self):
        token = "0pq8rStUvWxYz12345"  # no known key prefix: only the Bearer shape can catch it
        out = redact.redact("curl -H 'Authorization: Bearer %s' https://api.example" % token)
        self.assertNotIn(token, out)
        self.assertIn("Bearer " + redact.MASK, out)


if __name__ == "__main__":
    unittest.main()
