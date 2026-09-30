"""E1: engine follow-ups of the phase D verification (KIT_SPEC 4.7, 4.11, 6.3, 6.10, 6.11; audit findings #4, #11,
#16, #18, #20, #29, #34, #41, #79, #82, #85, #87, #96 and the confirmed reviewer defects of the engine).

- a HOST_BATCH lease holder that follows its cards never waits for itself; a finished host job counts under any lease
- a stale --lease is refused also when the step has none; a done for a task never handed out issues the task; a late
  write of a session whose task was taken over is named
- `next` never lifts a `ub stop` (only continue / run --continue); a finished run is never stopped
- a family that failed authentication is detected again by continue and by a BLOCKED retry
- gap-round outputs of every round move on a supersede; a supersede stops only the workers of what it redoes
- a busy card never puts free text or unquotable arguments into a shell command line
- nothing is accepted or answered while a supersede journal is pending; decision lines follow the supersede
- answer files: a non-text reply, nested G3 cells and ID-list text without an ID are re-asked, never raised
- a failed job re-seated to another family runs there; a migrated v1 run is detected; a 2.0.3 driver is respected
- `ub run` command words and an empty topic; .cmd shims are checked only against the paths their calls receive
- the host sub-agent's output is made durable before its meta; blank-line floods and list-marker fences stay linear
"""

import io
import json
import os
import shutil
import subprocess
import sys
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fixtures", "engine"))
import engine_testlib as tl  # noqa: E402

from ublib import textio  # noqa: E402
from ublib.engine import builders, gates, migrate, pipeline, registry  # noqa: E402
from ublib.engine import state as st  # noqa: E402

sys.path.insert(0, tl.SCRIPTS)
import ub  # noqa: E402

sys.path.insert(0, os.path.join(tl.KIT, "tests", "harness"))
from answerer import ub_args  # noqa: E402

PROBE_OUT = "## 1. Walk-through\nx\n## 2. Riskiest assumption\ny\n## 3. Probe design\nz\n## 4. Kill criterion\nw\n" \
            "RESULT: PENDING\n"
DIVERGE = {"id": "4.2", "stage": 4, "title": "Diverge", "type": "DISPATCH", "fanout": "strategies",
           "job": {"kind": "generator"}, "min_ok": "all"}


def gen_text(job):
    return "### %s-01 t\n- Pitch: p\n- Mechanism: m\n- Fails if: f\n" % job["contract"].get("prefix", "S")


def probe_step(sid="11.1"):
    return {"id": sid, "stage": 11, "title": "Probe", "type": "DISPATCH", "fanout": "probe", "job": {"kind": "writer"},
            "min_ok": 1, "after": []}


def host_step(sid="1.2"):
    s = dict(pipeline.step_by_id(pipeline.load_steps(), sid))
    s.pop("when", None)
    return s


class Base(tl.EngineTestCase):
    def run_ub(self, *args, **kw):
        out = io.StringIO()
        with mock.patch.object(sys, "stdout", out):
            rc = ub.main([str(a) for a in args], deps=kw.get("deps") or tl.FakeDeps(detect=tl.fake_detect()))
        text = out.getvalue()
        return rc, (json.loads(text) if text.strip().startswith("{") else text)

    def reload(self, ctx, deps=None):
        return st.Ctx(ctx.run_dir, st.load(ctx.run_dir), deps or ctx.deps)

    def new_run(self, *extra, **kw):
        rc, card = self.run_ub("init", "--host", kw.get("host", "claude-code"), "--text", "shift-swap app for nurses",
                               "--root", self.project, "--no-preflight", "--json", *extra, deps=kw.get("deps"))
        self.assertEqual(rc, 0, card)
        return card["run"]


class HeldBatch(tl.FakeBatch):
    """CLI jobs are answered at launch; the held one reads 'running' until the fake clock reaches release_at."""

    def __init__(self, clock, **kw):
        tl.FakeBatch.__init__(self, **kw)
        self.clock = clock
        self.held = None
        self.release_at = 0

    def launch_job(self, job_path, expect_gen=None):
        if self.held is None:
            self.held = textio.read_json(job_path)["id"]
        return tl.FakeBatch.launch_job(self, job_path, expect_gen)

    def job_state(self, run_dir, job):
        if isinstance(job, dict) and job["id"] == self.held and self.clock() < self.release_at:
            return "running"
        return tl.FakeBatch.job_state(self, run_dir, job)

    def running_jobs(self, run_dir):
        return [self.held] if self.held and self.clock() < self.release_at else []


# ------------------------------------------------------------------------------------------------ #96 leases

class LeaseHolder(Base):
    @unittest.skipUnless(tl.stubs_available(), "B4 stubs or B2 bs.py missing")
    def test_the_lease_holder_following_its_cards_never_waits_for_itself(self):
        """R-engine-0: step 4.2 mixes host sub-agent jobs (claude) with CLI jobs; one CLI job outlasts the holder's
        `next --lease` (W = 50 s, zcode). Every card's `then` is run exactly as written: the step completes at the first
        poll after the CLI job, never at the lease's expiry, and no card says another session holds the work."""
        import stubs
        batch = HeldBatch(None, outputs=gen_text)
        deps = tl.FakeDeps(batch=batch)
        batch.clock = deps.now  # the fake clock the driver sleeps on
        ctx = self.make_ctx(agent="zcode", deps=deps)
        ctx.state["families"]["claude"]["backend"] = "host"
        ctx.state["exec"]["wait_s"] = 50
        for s in pipeline.load_steps():
            if s["id"] == "4.2":
                break
            st.set_step(ctx.state, s["id"], "done", note="setup")
        st.save(ctx.run_dir, ctx.state)
        t0 = deps.now()
        batch.release_at = t0 + 200
        rc, card = self.run_ub("next", ctx.run_dir, "--wait-s", "0", "--json", deps=deps)
        self.assertEqual(card["type"], "HOST_BATCH")
        for j in card["jobs"]:  # the sub-agents run and write their outputs
            job = textio.read_json(os.path.join(ctx.run_dir, "jobs", j["id"] + ".json"))
            textio.write_text_atomic(j["out"], stubs.respond(job, textio.read_text(j["prompt_file"])))
        deps.sleep(90)
        says = []
        for _ in range(30):
            rc, card = self.run_ub(*ub_args(card["then"]), deps=deps)
            says.append(card.get("say") or "")
            if st.step_state(st.load(ctx.run_dir), "4.2") == "done" or card["type"] != "AUTO":
                break
        self.assertEqual(st.step_state(st.load(ctx.run_dir), "4.2"), "done", says)
        self.assertLessEqual(deps.now() - t0, 200 + 50 + 5, "the step waited for the lease to expire")
        self.assertFalse([s for s in says if "another session" in s], says)

    def test_a_foreign_poll_counts_host_outcomes_already_recorded(self):
        """A poll without the token, while the lease is still live, reads a host job's meta read-only: an outcome for
        the current prompt is final, so a finished step completes instead of waiting until the lease expires."""
        a = self.make_ctx()
        a.state["families"]["claude"]["backend"] = "host"
        st.save(a.run_dir, a.state)
        card = pipeline.advance(a, [probe_step()], 0)
        self.assertEqual(card["type"], "HOST_BATCH")
        job = builders.load_job(a, "11.1")
        textio.write_text_atomic(a.path(job["out"]), PROBE_OUT)
        textio.write_json_atomic(a.path(job["out"] + ".meta.json"), {
            "id": "11.1", "status": "ok", "prompt_sha256": textio.sha256_file(a.path(job["prompt_file"]))})
        b = self.reload(a, tl.FakeDeps())  # another session, no token; the lease is live and not taken over
        self.assertEqual(pipeline._lease_state(b, b.state["steps"]["11.1"]), "foreign")
        card = pipeline.advance(b, [probe_step()], 0)
        self.assertEqual(card["type"], "DONE", card.get("say"))
        self.assertNotIn("lease", st.load(a.run_dir)["steps"]["11.1"])

    def test_a_stale_lease_is_refused_also_when_the_step_has_none(self):
        """F18 (b): after a redo reset the host task, a done with the old card's token is refused."""
        steps = [host_step("1.2")]
        ctx = self.make_ctx(mode="deep")
        card = pipeline.advance(ctx, steps, 0)
        token = card["task"]["done_cmd"].split("--lease ")[1].split()[0]
        pipeline.supersede_from(ctx, steps, "1.2")
        self.assertNotIn("lease", ctx.state["steps"]["1.2"])
        ctx.write("00_HUMAN_SEEDS.md", "## Ideas\n- written for the old card\n")
        ctx = self.reload(ctx)
        ctx.lease = token
        card = pipeline.host_done(ctx, steps, "1.2")
        self.assertNotEqual(st.step_state(st.load(ctx.run_dir), "1.2"), "done")
        self.assertTrue(any("handed to another session" in n for n in card["notes"]), card["notes"])

    def test_a_done_for_a_task_never_handed_out_hands_it_out(self):
        """F18 (a): 1.2 was never issued (pending, the seeds file from the kickoff): `done` issues the task."""
        steps = [host_step("1.2")]
        ctx = self.make_ctx(mode="deep")
        ctx.write("00_HUMAN_SEEDS.md", "## Ideas\n- from the kickoff\n")
        card = pipeline.host_done(ctx, steps, "1.2")
        self.assertEqual(card["type"], "HOST")
        self.assertEqual(st.step_state(ctx.state, "1.2"), "running")
        self.assertIn("had not been handed out yet", card["notes"][0])

    def test_a_late_write_after_a_takeover_is_named(self):
        """#96 (2): session A's task is taken over by B and accepted; A's late write and done are refused and named."""
        steps = [host_step("1.2")]
        a = self.make_ctx(mode="deep")
        token_a = pipeline.advance(a, steps, 0)["task"]["done_cmd"].split("--lease ")[1].split()[0]
        b = self.reload(a, tl.FakeDeps())
        b.takeover = True
        token_b = pipeline.advance(b, steps, 0)["task"]["done_cmd"].split("--lease ")[1].split()[0]
        b.write("00_HUMAN_SEEDS.md", "## Ideas\n- from session B\n")
        b = self.reload(b)
        b.lease = token_b
        pipeline.host_done(b, steps, "1.2")
        self.assertEqual(st.step_state(st.load(a.run_dir), "1.2"), "done")
        a = self.reload(a, tl.FakeDeps())
        # session A's host writes the file itself (an engine write through Ctx keeps an accepted file accepted)
        textio.write_text_atomic(a.path("00_HUMAN_SEEDS.md"), "## Ideas\n- from session A, after the takeover\n")
        a.lease = token_a
        card = pipeline.host_done(a, steps, "1.2")
        self.assertEqual(card["type"], "BLOCKED")
        self.assertIn("00_HUMAN_SEEDS.md changed after that", card["say"])
        self.assertIn("redo", card["fix"][-1])


# ------------------------------------------------------------------------------------------------ stop

class Slow(tl.FakeBatch):
    """Launched jobs keep running until stop_all kills them."""

    def job_state(self, run_dir, job):
        if isinstance(job, dict) and job["id"] in self.running:
            return "running"
        return tl.FakeBatch.job_state(self, run_dir, job)

    def launch_job(self, job_path, expect_gen=None):
        job = textio.read_json(job_path)
        self.launched.append(job["id"])
        self.running.add(job["id"])
        return {"pid": 1, "job_id": job["id"]}


class Stop(Base):
    def test_the_agents_next_poll_keeps_a_stop(self):
        """F87 / R-engine-1: `ub stop` lands between two polls; the `then` the agent already holds returns the stopped
        card, relaunches nothing and keeps .ub/STOP; only `continue` resumes."""
        batch = Slow()
        deps = tl.FakeDeps(batch=batch, detect=tl.fake_detect())
        st.config_set("privacy_defaults", {"web": True, "vendors": True, "code": False,
                                           "vendor_set": ["anthropic", "moonshot", "openai", "zhipu"]})
        rc, card = self.run_ub("init", "--host", "codex", "--text", "quick full-auto shift-swap app for nurses",
                               "--root", self.project, "--no-preflight", "--json", deps=deps)
        run = card["run"]
        for _ in range(20):
            if card["type"] == "AUTO" and batch.running:
                break
            rc, card = self.run_ub("next", run, "--wait-s", "0", "--json", deps=deps)
        self.assertTrue(batch.running)
        self.run_ub("stop", run, "--json", deps=deps)
        n = len(batch.launched)
        rc, card = self.run_ub(*ub_args(card["then"]), deps=deps)
        state = st.load(run)
        self.assertEqual((card["type"], state["status"], state.get("stopped_reason")), ("DONE", "stopped", "user"))
        self.assertEqual(card["say"], "Stopped.")
        self.assertNotIn("Next: run", card["show"])
        self.assertIn("continue", card["show"])
        self.assertTrue(os.path.exists(st.stop_path(run)))
        self.assertEqual(batch.launched[n:], [])
        rc, card = self.run_ub("continue", run, "--json", deps=deps)
        self.assertEqual(st.load(run)["status"], "active")
        self.assertFalse(os.path.exists(st.stop_path(run)))

    @unittest.skipUnless(tl.stubs_available(), "B4 stubs or B2 bs.py missing")
    def test_stop_on_a_finished_run_leaves_no_stop_behind(self):
        """P3-engine-0: `ub stop` on a done run writes no STOP, so probe-result PASSED re-renders to the end."""
        ctx = tl.full_auto_ctx(self, mode="quick")
        self.assertEqual(tl.drive(ctx)["type"], "DONE")
        rc, res = self.run_ub("stop", ctx.run_dir, "--json", deps=tl.stub_deps())
        self.assertIn("nothing to stop", res["say"])
        self.assertFalse(os.path.exists(st.stop_path(ctx.run_dir)))
        rc, card = self.run_ub("probe-result", ctx.run_dir, "PASSED", "--json", deps=tl.stub_deps())
        state = st.load(ctx.run_dir)
        self.assertEqual((card["type"], state["status"]), ("DONE", "done"), card.get("show"))
        self.assertFalse([k for k, v in state["steps"].items() if v.get("state") == "pending" and
                          k in pipeline.step_ref("probe_rerender")])

    def test_a_stop_left_on_a_finished_run_is_dropped(self):
        """A STOP an older kit's `ub stop` left on a finished run never stops a later command halfway."""
        ctx = self.make_ctx()
        for s in pipeline.load_steps():
            st.set_step(ctx.state, s["id"], "done", note="setup")
        ctx.state["status"] = "done"
        st.save(ctx.run_dir, ctx.state)
        st.request_stop(ctx.run_dir)
        self.run_ub("status", ctx.run_dir, "--json")
        self.assertTrue(os.path.exists(st.stop_path(ctx.run_dir)), "a read-only command changed the run")
        rc, card = self.run_ub("budget", ctx.run_dir, "--max-calls", "500", "--json")
        self.assertEqual((card["type"], st.load(ctx.run_dir)["status"]), ("DONE", "done"), card.get("show"))
        self.assertFalse(os.path.exists(st.stop_path(ctx.run_dir)))


# ------------------------------------------------------------------------------------------------ auth re-detection

class AuthRedetect(Base):
    def mark(self, run):
        ctx = st.Ctx(run, st.load(run), tl.FakeDeps())
        job = {"id": "x-1", "family": "gpt", "out": "logs/x-1.txt"}
        ctx.write_json("logs/x-1.txt.meta.json", {"id": "x-1", "error_class": "auth", "reason": "401 Unauthorized"})
        pipeline._mark_unavailable(ctx, job)
        self.assertEqual(ctx.state["families"]["gpt"]["status"], "unavailable")
        self.assertTrue(any('ub.py" continue "%s"' % textio.to_posix(run) in n
                            for n in ctx.state["notes"]), ctx.state["notes"])
        st.save(run, ctx.state)

    def test_continue_on_the_same_host_detects_the_family_again(self):
        """R-engine-2: log in again, then `continue` (with or without the same --host): the family is used again."""
        run = self.new_run()
        self.mark(run)
        rc, card = self.run_ub("continue", run, "--host", "claude-code", "--json")
        self.assertEqual(st.load(run)["families"]["gpt"]["status"], "ok")
        self.assertTrue(any("gpt detected again" in n for n in card["notes"]), card["notes"])
        self.mark(run)
        self.run_ub("continue", run, "--json")
        self.assertEqual(st.load(run)["families"]["gpt"]["status"], "ok")
        self.mark(run)  # still logged out: detection keeps it unavailable
        self.run_ub("continue", run, "--json", deps=tl.FakeDeps(detect=tl.fake_detect(available=("claude",))))
        self.assertEqual(st.load(run)["families"]["gpt"]["status"], "unavailable")

    def test_a_blocked_retry_detects_the_family_again(self):
        ctx = self.make_ctx(deps=tl.FakeDeps(batch=tl.FakeBatch(outputs=lambda j: PROBE_OUT), detect=tl.fake_detect()))
        ctx.state["families"]["gpt"].update({"status": "unavailable", "reason": "authentication failed: 401"})
        st.set_step(ctx.state, "11.1", "blocked", note="auth", jobs=[])
        pipeline._retry_blocked(ctx, probe_step(), ctx.state["steps"]["11.1"])
        self.assertEqual(ctx.state["families"]["gpt"]["status"], "ok")


# ------------------------------------------------------------------------------------------------ R-engine-3, supersede

class GapRounds(Base):
    def gap_round(self, ctx, prefixes, rnd):
        ids = ["5.3-%s" % p for p in prefixes]
        for p, jid in zip(prefixes, ids):
            out = "pool/%s_%s.md" % (p, "gap" if p.startswith("G") else "reopen")
            ctx.write_json("jobs/%s.json" % jid, {"id": jid, "out": out, "prompt_file": "prompts/%s.prompt.md" % jid})
            ctx.write("prompts/%s.prompt.md" % jid, "prompt\n")
            ctx.write(out, "### %s-01 round-%d idea\n" % (p, rnd))
            ctx.write_json(out + ".meta.json", {"id": jid, "status": "ok"})
        st.set_step(ctx.state, "5.3", "done", jobs=ids)

    def test_every_rounds_gap_ideas_move_on_a_supersede(self):
        """R-engine-3: two deep-mode gap rounds, then a reframe (and an import): no idea of either round stays in the
        pool, so the re-run curator never sees ideas made for the old frame."""
        for start in ("reframe_from", "import_from"):
            ctx = self.make_ctx(mode="deep", run_name="gap-" + start)
            self.gap_round(ctx, ["G1", "G2", "R1"], 1)
            pipeline.rearm_loop(ctx, pipeline.step_ref("gap_loop"), "another gap round")
            self.assertTrue(ctx.exists("pool/G1_gap.md"), "a round's ideas stay in the pool between rounds")
            self.gap_round(ctx, ["G3", "R2"], 2)
            pipeline.supersede_from(ctx, pipeline.load_steps(), pipeline.step_ref(start))
            left = sorted(os.listdir(ctx.path("pool")))
            self.assertEqual([f for f in left if f[:1] in "GR"], [], left)
            self.assertFalse([f for f in os.listdir(ctx.path("jobs")) if f.startswith("5.3-")])
            self.assertNotIn("round-1 idea", registry.pool_bundle(ctx))

    def test_a_supersede_stops_only_the_jobs_it_redoes(self):
        """R-worker-proc-0: the 9.4 judges prelaunched at G8a keep running through `switch --idea` (from 11.1)."""
        batch = tl.FakeBatch(running={"9.4-judge-claude", "11.1", "orphan-job"})
        ctx = self.make_ctx(deps=tl.FakeDeps(batch=batch))
        st.set_step(ctx.state, "9.4", "running", jobs=["9.4-judge-claude"])
        st.set_step(ctx.state, "11.1", "running", jobs=["11.1"])
        pipeline.supersede_from(ctx, pipeline.load_steps(), "11.1")
        self.assertEqual(sorted(batch.stopped), ["11.1", "orphan-job"])
        self.assertEqual(batch.running, {"9.4-judge-claude"})

    def test_stop_all_keeps_the_named_jobs(self):
        from ublib import batch
        run = self.make_ctx().run_dir
        for jid in ("a", "b"):
            textio.write_json_atomic(os.path.join(run, ".ub", "jobs", jid + ".running.json"), {"pid": None})
        self.assertEqual(batch.stop_all(run, keep=["a"]), 0)
        self.assertTrue(os.path.exists(os.path.join(run, ".ub", "jobs", "a.running.json")))
        self.assertFalse(os.path.exists(os.path.join(run, ".ub", "jobs", "b.running.json")))


# ------------------------------------------------------------------------------------------------ busy card retries

HOLD_CODE = ("import os, sys, time\nsys.path.insert(0, %r)\n"
             "from ublib.engine import state as st\n"
             "lk = st.DriverLock(sys.argv[1], 'helper')\nassert lk.acquire()\nlk.announce()\n"
             "open(sys.argv[2], 'w').close()\n"
             "while not os.path.exists(sys.argv[3]): time.sleep(0.02)\n"
             "lk.release()\n" % tl.SCRIPTS)


def wait_for(path, proc, timeout=60):
    end = time.monotonic() + timeout
    while not os.path.exists(path):
        if proc.poll() is not None or time.monotonic() > end:
            raise AssertionError("the helper never reached its barrier")
        time.sleep(0.02)


class BusyRetry(Base):
    def hold(self, run):
        barrier = os.path.join(self.tmp, "held-%d" % len(os.listdir(self.tmp)))
        release = barrier + ".go"
        p = subprocess.Popen([sys.executable, "-c", HOLD_CODE, run, barrier, release])

        def stop():
            if p.poll() is None:
                open(release, "w").close()
                p.wait(timeout=30)
        self.addCleanup(stop)
        wait_for(barrier, p)
        return stop

    def test_a_refused_choice_is_retried_through_a_file_never_as_shell_text(self):
        """P3-engine-1: `answer --choice <text>` refused by a busy run: `then` carries --file of the kept answer, not
        the text; the retry applies it and uses the file up."""
        run = self.new_run()
        release = self.hold(run)
        text = 'I-002 because it costs $5/month, see `echo INJECTED`, "the cheap one"'
        rc, card = self.run_ub("answer", run, "G0", "--choice", text, "--json")
        self.assertEqual(card["type"], "AUTO")
        for bad in ("$", "`", "INJECTED", "cheap"):
            self.assertNotIn(bad, card["then"])
        args = ub_args(card["then"])
        self.assertEqual(args[:2], ["answer", textio.to_posix(run)])
        self.assertIn("--file", args)
        kept = args[args.index("--file") + 1]
        self.assertEqual(textio.read_json(kept), {"reply": text})
        release()
        rc, card = self.run_ub(*args)
        self.assertFalse(os.path.exists(kept))
        # a seed line is read back before it goes to the vendors (4.12); the kept text is the reading's reply
        self.assertEqual((card.get("gate"), st.load(run)["readback"]["reply"]), ("G0", text), card.get("error"))
        self.run_ub("answer", run, "G0", "--choice", "yes", "--json")
        self.assertEqual((st.load(run).get("gates") or {}).get("G0", {}).get("by"), "human")

    def test_a_lease_holders_refused_poll_keeps_its_lease(self):
        run = self.new_run()
        release = self.hold(run)
        rc, card = self.run_ub("next", run, "--wait-s", "5", "--lease", "abc123", "--json")
        self.assertIn("--lease abc123", card["then"])
        release()

    def test_an_argument_no_shell_quotes_safely_is_not_repeated(self):
        run = self.new_run()
        release = self.hold(run)
        rc, card = self.run_ub("switch", run, "--arch", 'B"; rm -rf ~', "--yes", "--json")
        self.assertEqual(card["type"], "BLOCKED")
        self.assertIn("was not applied", card["say"])
        self.assertIsNone(card["then"])
        release()

    def test_shell_arg(self):
        self.assertEqual(ub.shell_arg("I-002"), "I-002")
        self.assertEqual(ub.shell_arg("C:\\runs\\my run"), '"C:/runs/my run"')
        self.assertEqual(ub.shell_arg("R&D (x)"), '"R&D (x)"')
        for bad in ("a$b", "a`b", 'a"b', "50%", "hi!", "a\nb"):
            self.assertIsNone(ub.shell_arg(bad), bad)


# ------------------------------------------------------------------------------------------------ #11 journal

class PendingJournal(Base):
    def test_no_done_or_answer_while_a_supersede_journal_is_pending(self):
        """F11: a redo's moves are still pending (a program holds 01_FRAME.md): `done` of the reset HOST step and an
        answer change nothing; the run shows the supersede card."""
        steps = [host_step("1.2")]
        ctx = self.make_ctx(mode="deep")
        pipeline.advance(ctx, steps, 0)
        ctx.state["supersede"] = [{"stamp": "20260926T000000Z", "paths": ["01_FRAME.md"], "held": "01_FRAME.md"}]
        ctx.write("00_HUMAN_SEEDS.md", "## Ideas\n- a seed\n")
        card = pipeline.host_done(ctx, steps, "1.2")
        self.assertEqual(card["type"], "BLOCKED")
        self.assertIn("supersede pending", card["error"])
        self.assertEqual(st.step_state(ctx.state, "1.2"), "running")
        gate = [{"id": "1.1", "stage": 1, "title": "Your seeds", "type": "HUMAN", "gate": "G1"}]
        card = pipeline.answer_gate(ctx, gate, "G1", {"reply": "skip"})
        self.assertEqual(card["type"], "BLOCKED")
        self.assertNotIn("G1", ctx.state.get("gates") or {})

    def test_a_command_under_a_held_journal_is_not_applied(self):
        run = self.new_run()
        state = st.load(run)
        textio.write_text_atomic(os.path.join(run, "held.md"), "x")
        state["supersede"] = [{"stamp": "20260926T000000Z", "paths": ["held.md"]}]
        st.save(run, state)
        real = st._move_aside

        def refuse(run_dir, rel, stamp):
            if rel == "held.md":
                raise PermissionError(13, "held by another program")
            return real(run_dir, rel, stamp)
        with mock.patch.object(st, "_move_aside", refuse):
            rc, card = self.run_ub("answer", run, "G0", "--default", "--json")
        self.assertEqual(card["type"], "BLOCKED")
        self.assertIn("this answer was not applied", card["notes"][0])
        self.assertNotIn("G0", st.load(run).get("gates") or {})

    def test_decision_lines_are_written_after_the_supersede(self):
        """F11 (minor): a switch whose supersede refuses writes nothing to 08_DECISION.md, so a retry adds one line."""
        ctx = self.make_ctx()
        ctx.state["choice"].update({"idea": "I-001", "runner_up": "I-002"})
        ctx.state["finalists"] = ["I-001", "I-002"]
        ctx.write("08_DECISION.md", "# DECISION\n")
        with mock.patch.object(st, "check_supersede_paths", side_effect=pipeline.EngineError("too long")):
            with self.assertRaises(pipeline.EngineError):
                pipeline.switch_idea(ctx, pipeline.load_steps(), "I-002")
        self.assertEqual(ctx.read("08_DECISION.md"), "# DECISION\n")
        pipeline.switch_idea(ctx, pipeline.load_steps(), "I-002")
        self.assertEqual(ctx.read("08_DECISION.md").count("Switched"), 1)


# ------------------------------------------------------------------------------------------------ #16 answers

class AnswerShapes(Base):
    def gate(self, gid, sid, **state):
        ctx = self.make_ctx(autopilot="hands-on", run_name="run-%s" % gid)
        ctx.state.update(state)
        steps = [{"id": sid, "stage": 7, "title": "Gate", "type": "HUMAN", "gate": gid}]
        self.assertEqual(pipeline.advance(ctx, steps, 0)["gate"], gid)
        return ctx, steps

    def test_a_reply_that_is_not_text_is_re_asked(self):
        ctx, steps = self.gate("G7", "10.1h", finalists=["I-001", "I-002", "I-003"])
        for reply in (5, ["I-001"], {"x": 1}):
            card = pipeline.answer_gate(ctx, steps, "G7", {"reply": reply})
            self.assertEqual((card["type"], card["gate"]), ("HUMAN", "G7"))
            self.assertIn("reply: expected string", card["error"])
        path = ctx.path("answers", "G7.json")
        textio.write_json_atomic(path, {"reply": ["I-001"]})
        st.save(ctx.run_dir, ctx.state)
        with mock.patch.object(pipeline, "load_steps", return_value=steps):
            rc, card = self.run_ub("answer", ctx.run_dir, "G7", "--file", path, "--json", deps=ctx.deps)
        self.assertEqual((rc, card["type"]), (0, "HUMAN"), card)

    def test_nested_g3_cells_are_refused(self):
        ctx = self.make_ctx()
        for cells in ([[1, 2]], [["a", None]], [[["x"]]]):
            errs = gates.prepare_answer(ctx, "G3", {"cells": cells})[2]
            self.assertTrue(errs and "cells" in errs[0], (cells, errs))
        self.assertEqual(gates.prepare_answer(ctx, "G3", {"cells": [["a", "b"], "c / d"]})[2], [])

    def test_id_list_text_without_an_id_is_an_error(self):
        ctx, steps = self.gate("G5", "7.3", k4_candidates=["I-004", "I-005"])
        card = pipeline.answer_gate(ctx, steps, "G5", {"kill": "all"})
        self.assertEqual(card["type"], "HUMAN")
        self.assertIn("names no idea ID", card["error"])
        self.assertNotIn("killed", ctx.state)
        card = pipeline.answer_gate(ctx, steps, "G5", {"kill": "none"})
        self.assertEqual(ctx.state["parked"], ["I-004", "I-005"])


# ------------------------------------------------------------------------------------------------ #85 re-seat

class ReseatedFailure(Base):
    def test_a_job_that_failed_on_a_family_re_seated_away_runs_on_its_new_seat(self):
        victim = {"fam": None}
        batch = tl.FakeBatch(fail=lambda j: j["family"] == victim["fam"], outputs=gen_text)
        deps = tl.FakeDeps(batch=batch)
        ctx = self.make_ctx(deps=deps)
        jobs = builders.build_jobs(ctx, DIVERGE, write=lambda j: False)
        vjob = next(j for j in jobs if j["family"] != ctx.host_family)
        victim["fam"] = vjob["family"]
        key = vjob["id"].split("-", 1)[1]
        new = next(f for f in ("glm", "kimi", "gpt") if f not in (victim["fam"], ctx.host_family))
        batch.running = set(j["id"] for j in jobs if j["id"] != vjob["id"])  # the step does not finish yet
        pipeline.advance(ctx, [DIVERGE], 0)
        self.assertEqual(batch.job_state(ctx.run_dir, builders.load_job(ctx, vjob["id"])), "failed")
        # continue --host: the victim family is gone; its seat is re-seated before the driver looks again
        ctx.state["families"][victim["fam"]]["status"] = "unavailable"
        ctx.state["seats"]["generators"][key] = new
        st.save(ctx.run_dir, ctx.state)
        ctx2 = st.Ctx(ctx.run_dir, st.load(ctx.run_dir), deps)  # a new process
        batch.running = set()
        card = pipeline.advance(ctx2, [DIVERGE], 30)
        self.assertEqual(card["type"], "DONE", card.get("say"))
        self.assertEqual(builders.load_job(ctx2, vjob["id"])["family"], new)
        self.assertEqual(batch.launched.count(vjob["id"]), 2)
        self.assertFalse([j for j in ctx2.state["steps"]["4.2"]["jobs"] if "-fb-" in j])
        self.assertFalse([p for p in ctx2.state.get("provisional") or [] if p.get("seat") == new])


# ------------------------------------------------------------------------------------------------ #79 / #20 / #82

class Upgrade(Base):
    def test_a_2_0_3_driver_sees_this_kits_holder_as_live(self):
        """#79 (1): 2.0.3's Lock.holder() takes a lock.json whose heartbeat_ts is older than 120 s or whose pid is
        dead."""
        run = self.make_ctx().run_dir
        lock = st.DriverLock(run, "claude-code")
        self.assertTrue(lock.acquire())
        try:
            lock.announce()
            rec = textio.read_json(os.path.join(run, ".ub", "lock.json"))
            age = time.time() - float(rec.get("heartbeat_ts", 0) or 0)  # the 2.0.3 rule, verbatim
            self.assertLessEqual(age, 120, "a 2.0.3 driver would take this live run")
            self.assertEqual(rec["pid"], os.getpid())
        finally:
            lock.release()

    def test_a_live_2_0_3_driver_is_not_overwritten(self):
        """#79 (2): a 2.0.3 driver holds the run through lock.json alone: this kit changes nothing and retries."""
        run = self.new_run()
        p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
        self.addCleanup(lambda: (p.kill(), p.wait()))
        path = os.path.join(run, ".ub", "lock.json")
        textio.write_json_atomic(path, {"pid": p.pid, "host": "codex", "heartbeat_at": textio.now_iso(),
                                        "heartbeat_ts": time.time()})
        before = textio.read_bytes(os.path.join(run, "run.json"))
        rc, card = self.run_ub("answer", run, "G0", "--default", "--json")
        self.assertEqual(card["type"], "AUTO")
        self.assertIn("another session is driving this run (pid %d, codex)" % p.pid, card["say"])
        self.assertEqual(textio.read_bytes(os.path.join(run, "run.json")), before)
        self.assertEqual(textio.read_json(path)["pid"], p.pid, "the 2.0.3 driver's record was replaced")
        p.kill()
        p.wait()
        rc, card = self.run_ub(*ub_args(card["then"]))  # its driver is gone: the retried answer applies
        self.assertEqual(st.load(run)["gates"]["G0"]["by"], "human")

    def test_the_terminal_does_not_take_a_run_a_2_0_3_driver_took_meanwhile(self):
        from ublib.engine import terminal
        run = self.make_ctx().run_dir
        p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
        self.addCleanup(lambda: (p.kill(), p.wait()))
        textio.write_json_atomic(os.path.join(run, ".ub", "lock.json"), {
            "pid": p.pid, "host": "codex", "heartbeat_at": textio.now_iso(), "heartbeat_ts": time.time()})
        lock = st.DriverLock(run, "terminal")
        self.assertFalse(terminal._relock(lock, io.StringIO()))
        self.assertFalse(lock.held)
        self.assertEqual(textio.read_json(os.path.join(run, ".ub", "lock.json"))["pid"], p.pid)

    def v1_run(self):
        run = os.path.join(self.project, "brainstorm", "2026-01-10-habit-coach")
        shutil.copytree(tl.fixture_path("v1_run", "2026-01-10-habit-coach"), run)
        return run

    def test_a_migrated_v1_run_detects_its_families(self):
        """#20: the v1 file asserts claude and gpt; the locked migration detects them (gpt is gone here)."""
        run = self.v1_run()
        self.run_ub("next", run, "--wait-s", "0", "--json",
                    deps=tl.FakeDeps(detect=tl.fake_detect(available=("claude",))))
        state = st.load(run)
        self.assertEqual(state["families"]["gpt"]["status"], "unavailable")
        self.assertNotIn("redetect", state["exec"])
        self.assertTrue(state["legacy_v1"])

    def test_a_repeated_migration_reads_the_kept_original(self):
        run = self.v1_run()
        textio.write_text_atomic(os.path.join(run, st.RUN_MD_V1), textio.read_text(os.path.join(run, st.RUN_MD)))
        textio.write_text_atomic(os.path.join(run, st.RUN_MD), "# Run: x\n- topic: the rendered v2 file\n")
        self.assertEqual(migrate.migrate_v1(run)["topic"], "habit coach for shift workers")


class RunCommandWords(Base):
    def test_run_command_words_never_start_a_run(self):
        """#82: `ub run continue|status|stop` act on the newest run; they never create a run named after the word."""
        run = self.new_run()
        before = sorted(os.listdir(os.path.dirname(run)))
        seen = []

        def fake_loop(ctx, steps, lock=None, **kw):  # never reads stdin
            seen.append(ctx.run_dir)
            return {"type": "DONE", "say": "x"}
        with mock.patch("ublib.engine.terminal.run_loop", fake_loop):
            rc, res = self.run_ub("run", "status", "--root", self.project, "--json")
            self.assertEqual(res.get("run"), textio.to_posix(run))
            self.run_ub("run", "continue", "--root", self.project, "--json")
            self.assertEqual([os.path.normcase(d) for d in seen], [os.path.normcase(run)])
            rc, res = self.run_ub("run", "stop", run, "--json")
            self.assertIn("Stopped", res.get("say") or "")
        self.assertEqual(sorted(os.listdir(os.path.dirname(run))), before)

    def test_a_terminal_start_without_a_topic_is_a_usage_error(self):
        err = io.StringIO()
        with mock.patch.object(sys, "stderr", err), \
                mock.patch("ublib.engine.terminal.run_loop", lambda *a, **k: {"type": "DONE", "say": "x"}):
            rc, out = self.run_ub("run", "quick", "--root", self.project, "--json")
        self.assertEqual(rc, 2)
        self.assertIn("give a topic", err.getvalue())
        self.assertFalse(os.path.isdir(os.path.join(self.project, "brainstorm")) and
                         os.listdir(os.path.join(self.project, "brainstorm")))


# ------------------------------------------------------------------------------------------------ #29 .cmd shims

class CmdShims(Base):
    def fams(self):
        return {"gpt": {"status": "ok", "backend": "codex-cli", "chain": ["codex-cli"], "web": True, "reason": ""},
                "claude": {"status": "ok", "backend": "claude-cli", "chain": ["claude-cli"], "web": True, "reason": ""}}

    def test_a_metacharacter_in_the_project_folder_blocks_only_the_repo_readers(self):
        """#29: a project under 'R&D' reaches only the host vendor's command lines (codex -C, claude's run-folder
        rules): the other vendor's .cmd family stays available; the host family goes to its sub-agents."""
        from ublib import proc
        ctx = self.make_ctx(variant="software")
        project = os.path.join(self.tmp, "R&D")
        os.makedirs(os.path.join(project, ".git"))
        fams = self.fams()
        with mock.patch.object(proc, "resolve_exe", side_effect=lambda name, env=None: "C:/bin/%s.cmd" % name):
            ub.shim_problems(ctx, fams, project)
        self.assertEqual(fams["gpt"]["status"], "ok", fams["gpt"]["reason"])
        self.assertEqual((fams["claude"]["status"], fams["claude"]["backend"]), ("ok", "host"))
        self.assertIn("the repository", fams["claude"]["reason"])
        fams = self.fams()  # not a repository: nothing reads it, nothing is blocked
        os.rmdir(os.path.join(project, ".git"))
        with mock.patch.object(proc, "resolve_exe", side_effect=lambda name, env=None: "C:/bin/%s.cmd" % name):
            ub.shim_problems(ctx, fams, project)
        self.assertEqual((fams["claude"]["backend"], fams["gpt"]["status"]), ("claude-cli", "ok"))


# ------------------------------------------------------------------------------------------------ #4 durability

class HostOutputDurable(Base):
    def test_the_host_output_is_fsynced_before_its_ok_meta(self):
        ctx = self.make_ctx()
        ctx.state["families"]["claude"]["backend"] = "host"
        card = pipeline.advance(ctx, [probe_step()], 0)
        out = card["jobs"][0]["out"]
        textio.write_text_atomic(out, PROBE_OUT)
        with open(out, "rb") as f:
            ident = (os.fstat(f.fileno()).st_dev, os.fstat(f.fileno()).st_ino)
        events = []
        real_fsync, real_write = os.fsync, textio.write_json_atomic

        def fsync(fd):
            s = os.fstat(fd)
            events.append(("fsync", (s.st_dev, s.st_ino)))
            return real_fsync(fd)

        def write_json(path, obj):
            if str(path).endswith(".meta.json"):
                events.append(("meta", None))
            return real_write(path, obj)
        ctx.lease = ctx.state["steps"]["11.1"]["lease"]["token"]
        with mock.patch.object(os, "fsync", fsync), mock.patch.object(textio, "write_json_atomic", write_json):
            self.assertEqual(pipeline.advance(ctx, [probe_step()], 0)["type"], "DONE")
        self.assertIn(("meta", None), events)
        self.assertIn(("fsync", ident), events[:events.index(("meta", None))], events)


# ------------------------------------------------------------------------------------------------ #34 / #41 parsers

class LinearScans(Base):
    """#34: a flood of blank lines in model or seeds text costs linear time (each took seconds to minutes)."""

    def timed(self, fn):
        t0 = time.perf_counter()
        fn()
        return time.perf_counter() - t0

    def test_the_kill_assumptions_scan_stays_on_its_line(self):
        ctx = self.make_ctx()
        ctx.state["choice"]["idea"] = "I-001"
        ctx.write("07_REDTEAM.md", "# Red team\n\n## 1. Per idea\n\n### I-001\n- Fails if: x\n" + "\n" * 60000 +
                  "end\n")
        self.assertLess(self.timed(lambda: registry._ph_kill_assumptions(ctx, {})), 1.0)
        ctx.write("07_REDTEAM.md", "## 1. Per idea\n\n### I-001\n- Fails if: x\n\n### I-002\n- Fails if: y\n")
        self.assertEqual(registry._ph_kill_assumptions(ctx, {}), "From the red-team:\n- Fails if: x")

    def test_the_skipped_marker_scans_stay_on_their_line(self):
        ctx = self.make_ctx()
        ctx.write("00_HUMAN_SEEDS.md", "\n" * 40000 + "x\n")
        self.assertLess(self.timed(lambda: registry.eval_when(ctx, ["no_seeds"])), 1.0)
        self.assertLess(self.timed(lambda: gates.validate(ctx, "G1", {"done": True})), 1.0)
        ctx.write("00_HUMAN_SEEDS.md", "\n\n  SKIPPED: no seeds\n")
        self.assertFalse(registry.eval_when(ctx, ["no_seeds"]))  # the marker still counts after blank lines
        self.assertEqual(gates.validate(ctx, "G1", {"done": True}), [])

    def test_the_v1_run_file_scan_stays_on_its_line(self):
        self.assertLess(self.timed(lambda: migrate.parse_run_md("\n" * 20000 + "x\n")), 1.0)
        self.assertEqual(migrate.parse_run_md("\n\n- mode: deep\n")["mode"], "deep")

    def test_context_sections_follow_the_contracts_fence_rule(self):
        """#41: '- ```' and '> ```' are not fences for the P-GROUND contract, so they never hide LANDSCAPE."""
        ctx = self.make_ctx()
        for marker in ("- ", "> "):
            ctx.write("02_CONTEXT.md", "## A. FACTS\n- a fact\n%s```bash\n%smake build\n%s```\n\n## B. LANDSCAPE\n"
                                       "- competitor tool X\n\n## C. SEARCH LOG\n- q\n" % (marker, marker, marker))
            heads = [t for _lvl, t in (textio.parse_heading(ln) or (0, None) for ln in
                                       ctx.read("02_CONTEXT.md").split("\n")) if t]
            self.assertIn("B. LANDSCAPE", heads)
            self.assertIn("competitor tool X", registry.context_section(ctx, "B"))
            self.assertNotIn("LANDSCAPE", registry.context_section(ctx, "A"))


if __name__ == "__main__":
    unittest.main()
