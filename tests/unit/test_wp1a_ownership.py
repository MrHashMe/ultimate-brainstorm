"""WP1a: run ownership and run-state consistency (KIT_SPEC 6.3, 6.10, 4.11; audit findings P1-1, P1-2, P1-7, P1-8,
P2-1..P2-3, P2-12, P2-16). In-process engine tests plus small helper processes synchronized on barrier files.

- the driver lock is a kernel lock taken before run.json is read; a busy run is not touched and the command is retried
- run.json saves are a compare-and-swap on `rev`, and a poll that changes nothing writes nothing
- supersede is journaled: a file another program holds never leaves a done step without its outputs
- HOST / HOST_BATCH work is leased to one session; a HOST task counts only files written after it was issued
- a re-armed host job never re-stamps its old output; idea-id state never survives a re-curation
- probe results are tied to the probed idea; `switch --idea` is checked and re-designs the probe
- `ub init --text-file`, `ub run "<topic>"`, and v1 migration only under the lock
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
from ublib.engine import pipeline, registry  # noqa: E402
from ublib.engine import state as st  # noqa: E402

sys.path.insert(0, tl.SCRIPTS)
import ub  # noqa: E402

HOLD_CODE = ("import os, sys, time\nsys.path.insert(0, %r)\n"
             "from ublib.engine import state as st\n"
             "lk = st.DriverLock(sys.argv[1], 'helper')\nassert lk.acquire()\nlk.announce()\n"
             "open(sys.argv[2], 'w').close()\n"
             "while not os.path.exists(sys.argv[3]): time.sleep(0.02)\n"
             "lk.release()\n" % tl.SCRIPTS)
OPEN_CODE = ("import os, sys, time\nf = open(sys.argv[1], 'rb')\nopen(sys.argv[2], 'w').close()\n"
             "while not os.path.exists(sys.argv[3]): time.sleep(0.02)\nf.close()\n")


def wait_for(path, proc=None, timeout=60):
    end = time.monotonic() + timeout
    while not os.path.exists(path):
        if proc is not None and proc.poll() is not None:
            raise AssertionError("the helper process ended before its barrier (exit %s)" % proc.returncode)
        if time.monotonic() > end:
            raise AssertionError("barrier %s never appeared" % path)
        time.sleep(0.02)


def raw(path):
    with open(path, "rb") as f:
        return f.read()


def dispatch_step(fanout="probe", sid="11.1"):
    return {"id": sid, "stage": 11, "title": "Probe", "type": "DISPATCH", "fanout": fanout,
            "job": {"kind": "writer"}, "min_ok": 1, "after": []}


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

    def helper(self, code, *args):
        barrier = os.path.join(self.tmp, "ready-%d" % len(os.listdir(self.tmp)))
        release = barrier + ".release"
        p = subprocess.Popen([sys.executable, "-c", code] + [str(a) for a in args] + [barrier, release])

        def stop():
            if p.poll() is None:
                open(release, "w").close()
                p.wait(timeout=30)
        self.addCleanup(stop)
        wait_for(barrier, p)
        return stop

    def reload(self, ctx, deps=None):
        return st.Ctx(ctx.run_dir, st.load(ctx.run_dir), deps or ctx.deps)

    def new_run(self, *extra):
        rc, card = self.run_ub("init", "--host", "claude-code", "--text", "shift-swap app for nurses", "--root",
                               self.project, "--no-preflight", "--json", *extra)
        self.assertEqual(rc, 0, card)
        return card["run"]


# ------------------------------------------------------------------------------------------------ C1 / C2

class CompareAndSwap(Base):
    def test_a_stale_save_is_refused_and_overwrites_nothing(self):
        ctx = self.make_ctx()
        st.save(ctx.run_dir, ctx.state)
        a = st.load(ctx.run_dir)
        b = st.load(ctx.run_dir)
        b["topic"] = "the other session's topic"
        st.save(ctx.run_dir, b)
        a["topic"] = "a stale topic"
        with self.assertRaises(st.Stale):
            st.save(ctx.run_dir, a)
        self.assertEqual(st.load(ctx.run_dir)["topic"], "the other session's topic")

    def test_a_poll_that_changes_nothing_writes_nothing(self):
        batch = tl.FakeBatch(running={"11.1"})
        ctx = self.make_ctx(deps=tl.FakeDeps(batch=batch))
        st.save(ctx.run_dir, ctx.state)
        writes = []
        real = textio.write_json_atomic

        def counting(path, obj):
            if os.path.basename(str(path)) == "run.json":
                writes.append(path)
            return real(path, obj)
        with mock.patch.object(textio, "write_json_atomic", counting):
            card = pipeline.advance(ctx, [dispatch_step()], 30)  # 15 polls of a job that keeps running
        self.assertEqual(card["type"], "AUTO")
        self.assertLessEqual(len(writes), 2, "run.json was rewritten on idle polls")

    def test_a_finished_job_is_not_re_derived_on_every_poll(self):
        calls = {}

        class Counting(tl.FakeBatch):
            def job_state(self, run_dir, job):
                calls[job["id"]] = calls.get(job["id"], 0) + 1
                return tl.FakeBatch.job_state(self, run_dir, job)
        batch = Counting(running={"4.2-S3"}, outputs=lambda j: "### %s-01 t\n- Pitch: p\n- Mechanism: m\n- Fails "
                                                                 "if: f\n" % j["contract"].get("prefix", "S"))
        ctx = self.make_ctx(deps=tl.FakeDeps(batch=batch), families=("claude",))
        step = {"id": "4.2", "stage": 4, "title": "Diverge", "type": "DISPATCH", "fanout": "strategies",
                "job": {"kind": "generator"}, "min_ok": "all"}
        pipeline.advance(ctx, [step], 20)
        self.assertGreater(calls["4.2-S3"], 5)  # the running job is looked at on every poll
        self.assertLessEqual(calls["4.2-S2"], 2, calls)  # the finished one only until it is known to be done


class DriverOwnership(Base):
    def test_a_busy_run_is_not_touched_and_the_command_is_retried(self):
        run = self.new_run()
        before = raw(os.path.join(run, "run.json"))
        release = self.helper(HOLD_CODE, run)
        rc, card = self.run_ub("continue", run, "--host", "codex", "--json")
        self.assertEqual(card["type"], "AUTO")
        self.assertIn("another session is driving this run", card["say"])
        self.assertIn("helper", card["say"])
        self.assertIn("continue", card["then"])
        self.assertIn("--host codex", card["then"])
        self.assertEqual(raw(os.path.join(run, "run.json")), before, "a refused command wrote run.json")
        release()
        rc, card = self.run_ub(*self.args_of(card["then"]))
        self.assertEqual(st.load(run)["host"]["agent"], "codex")
        self.assertTrue(any("host is now codex" in n for n in card["notes"]))

    def args_of(self, cmd):
        sys.path.insert(0, os.path.join(tl.KIT, "tests", "harness"))
        from answerer import ub_args
        return ub_args(cmd)

    def test_the_lock_is_taken_before_run_json_is_read(self):
        run = self.new_run()
        seen = []
        real_load = st.load

        def load(run_dir, persist=True):
            probe = st.DriverLock(run_dir)  # a second handle: refused while the command holds the lock
            seen.append(probe.acquire())
            probe.release()
            return real_load(run_dir, persist)
        with mock.patch.object(st, "load", load):
            self.run_ub("next", run, "--wait-s", "0", "--json")
        self.assertEqual(seen, [False])


# ------------------------------------------------------------------------------------------------ I6 supersede

@unittest.skipUnless(tl.stubs_available(), "B4 stubs or B2 bs.py missing")
class JournaledSupersede(Base):
    HELD = "11_PROPOSAL/PROPOSAL.md"

    def test_redo_against_a_held_file_never_leaves_done_steps_without_outputs(self):
        ctx = tl.full_auto_ctx(self, mode="quick")
        self.assertEqual(tl.drive(ctx)["type"], "DONE")
        run = ctx.run_dir
        held = ctx.path(self.HELD)
        if os.name == "nt":  # a real sharing violation: a reader without FILE_SHARE_DELETE
            release = self.helper(OPEN_CODE, held)
            rc, card = self.run_ub("redo", run, "12.1", "--yes", "--json", deps=tl.stub_deps())
            release()
        else:
            real = os.replace

            def replace(src, dst):
                if os.path.normcase(os.path.abspath(src)) == os.path.normcase(held):
                    raise PermissionError(13, "held by another program", src)
                return real(src, dst)
            with mock.patch.object(os, "replace", replace):
                rc, card = self.run_ub("redo", run, "12.1", "--yes", "--json", deps=tl.stub_deps())
        self.assertEqual((rc, card["type"]), (0, "BLOCKED"), card)
        self.assertIn("supersede pending", card["error"])
        state = st.load(run)
        self.assertTrue(state.get("supersede"), "the pending moves are journaled in run.json")
        steps = pipeline.load_steps()
        idx = pipeline.index_of(steps, "12.1")
        self.assertFalse([s["id"] for s in steps[idx:] if st.step_state(state, s["id"]) == "done"])
        for s in steps:
            if st.step_state(state, s["id"]) == "done":
                for out in s.get("outputs") or []:
                    if "*" not in out:
                        self.assertTrue(os.path.exists(ctx.path(out)), "step %s is done but %s is gone" % (
                            s["id"], out))
        self.assertTrue(os.path.exists(held))
        # the holder is gone: the next command rolls the journal forward, then the run goes on from 12.1
        rc, card = self.run_ub("next", run, "--wait-s", "0", "--json", deps=tl.stub_deps())
        state = st.load(run)
        self.assertFalse(state.get("supersede"))
        moved = [os.path.join(dp, f) for dp, _d, fs in os.walk(ctx.path("_superseded")) for f in fs
                 if f == "PROPOSAL.md"]
        self.assertTrue(moved, "the held file was moved aside once it was free")
        final = tl.drive(st.Ctx(run, state, tl.stub_deps()))
        self.assertEqual(final["type"], "DONE", final.get("say"))
        self.assertTrue(os.path.exists(held))


# ------------------------------------------------------------------------------------------------ HOST leases / #18

class HostWork(Base):
    def test_a_host_task_goes_to_one_session_and_a_stale_done_is_refused(self):
        steps = [host_step("1.2")]
        a = self.make_ctx(mode="deep")
        st.save(a.run_dir, a.state)
        card = pipeline.advance(a, steps, 0)
        self.assertEqual(card["type"], "HOST")
        token = card["task"]["done_cmd"].split("--lease ")[1].split()[0]
        b = self.reload(a, tl.FakeDeps())
        card = pipeline.advance(b, steps, 0)
        self.assertEqual(card["type"], "AUTO", "a second session got the same host task")
        self.assertIn("in progress in another session", card["say"])
        b = self.reload(a, tl.FakeDeps())
        b.takeover = True  # `ub continue`
        card = pipeline.advance(b, steps, 0)
        self.assertEqual(card["type"], "HOST")
        token_b = card["task"]["done_cmd"].split("--lease ")[1].split()[0]
        self.assertNotEqual(token_b, token)
        a = self.reload(a, tl.FakeDeps())
        a.lease = token
        a.write("00_HUMAN_SEEDS.md", "## Ideas\n- written by the first session\n")
        card = pipeline.host_done(a, steps, "1.2")
        self.assertIn("handed to another session", card["notes"][0])
        self.assertEqual(st.step_state(st.load(a.run_dir), "1.2"), "running")
        b = self.reload(a, tl.FakeDeps())
        b.lease = token_b
        pipeline.host_done(b, steps, "1.2")
        self.assertEqual(st.step_state(st.load(a.run_dir), "1.2"), "done")

    def test_a_host_task_that_wrote_nothing_is_not_done(self):
        steps = [host_step("1.2")]
        ctx = self.make_ctx(mode="deep")
        self.assertTrue(ctx.exists("00_HUMAN_SEEDS.md"))  # the seeds file exists before the task
        self.assertEqual(pipeline.advance(ctx, steps, 0)["type"], "HOST")
        pipeline.host_done(ctx, steps, "1.2")
        self.assertEqual(st.step_state(ctx.state, "1.2"), "skipped")
        self.assertIn("changed none of its files", ctx.state["steps"]["1.2"]["note"])
        ctx2 = self.make_ctx(mode="deep", run_name="wrote")
        pipeline.advance(ctx2, steps, 0)
        ctx2.write("00_HUMAN_SEEDS.md", "## Ideas\n- a seed from the session\n")
        pipeline.host_done(ctx2, steps, "1.2")
        self.assertEqual(st.step_state(ctx2.state, "1.2"), "done")

    def test_host_batch_is_leased_and_a_foreign_poll_leaves_the_output_alone(self):
        a = self.make_ctx()
        a.state["families"]["claude"]["backend"] = "host"
        st.save(a.run_dir, a.state)
        card = pipeline.advance(a, [dispatch_step()], 0)
        self.assertEqual(card["type"], "HOST_BATCH")
        self.assertIn("--lease ", card["then"])
        out = card["jobs"][0]["out"]
        textio.write_text_atomic(out, "## 1. Walk-through\nhalf written")  # a sub-agent is still writing
        b = self.reload(a, tl.FakeDeps())
        card = pipeline.advance(b, [dispatch_step()], 0)
        self.assertEqual(card["type"], "AUTO", "the jobs were handed out a second time")
        self.assertEqual(textio.read_text(out), "## 1. Walk-through\nhalf written")
        self.assertFalse(st.load(a.run_dir).get("host_invalid"))
        textio.write_text_atomic(out, "## 1. Walk-through\nx\n## 2. Riskiest assumption\ny\n## 3. Probe design\nz\n"
                                      "## 4. Kill criterion\nw\nRESULT: PENDING\n")
        a = self.reload(a, tl.FakeDeps())
        a.lease = self.lease_of(a.state, "11.1")  # the token of the HOST_BATCH card's `then`
        self.assertTrue(a.lease)
        self.assertEqual(pipeline.advance(a, [dispatch_step()], 0)["type"], "DONE")

    @staticmethod
    def lease_of(state, sid):
        return ((state["steps"].get(sid) or {}).get("lease") or {}).get("token")

    @unittest.skipUnless(tl.stubs_available(), "B4 stubs missing")
    def test_g10_corrections_hand_the_drivers_job_out_again(self):
        import stubs  # tests/harness (on sys.path through engine_testlib)
        steps_all = pipeline.load_steps()
        steps = [pipeline.step_by_id(steps_all, "12.2"), pipeline.step_by_id(steps_all, "12.3")]
        ctx = self.make_ctx(mode="deep", autopilot="guided")
        ctx.state["families"]["claude"]["backend"] = "host"
        ctx.write("10_ARCHITECTURE/00_BRIEF.md", "# Brief\nOriginal brief: cloud-first.\n")
        card = pipeline.advance(ctx, steps, 0)
        self.assertEqual((card["type"], [j["id"] for j in card["jobs"]]), ("HOST_BATCH", ["12.2"]))
        job = textio.read_json(ctx.path("jobs", "12.2.json"))
        textio.write_text_atomic(card["jobs"][0]["out"], stubs.respond(job, textio.read_text(
            card["jobs"][0]["prompt_file"])))
        ctx.lease = self.lease_of(ctx.state, "12.2")
        card = pipeline.advance(ctx, steps, 0)
        self.assertEqual(card.get("gate"), "G10")
        card = pipeline.answer_gate(ctx, steps, "G10", {"reply": "Must run fully offline; drop the cloud DB."})
        self.assertTrue(card["error"].startswith("I read your reply as: add this correction"), card["error"])
        card = pipeline.answer_gate(ctx, steps, "G10", {"reply": "yes"})  # a correction is read back first (4.12)
        self.assertEqual(card["type"], "HOST_BATCH", "the corrected brief was never handed to the host")
        self.assertEqual([j["id"] for j in card["jobs"]], ["12.2"])
        self.assertFalse(ctx.exists("10_ARCHITECTURE/drivers.json"), "the round-1 drivers stayed in place")
        rows = [json.loads(ln) for ln in textio.read_text(ctx.path("logs", "calls.jsonl")).split("\n") if ln.strip()]
        self.assertEqual(len([r for r in rows if r.get("id") == "12.2"]), 1, "a host call was logged that never ran")

    def test_a_re_armed_host_job_never_re_stamps_its_old_output(self):
        ctx = self.make_ctx()
        ctx.state["families"]["claude"]["backend"] = "host"
        step = dispatch_step()
        card = pipeline.advance(ctx, [step], 0)
        out = card["jobs"][0]["out"]
        textio.write_text_atomic(out, "## 1. Walk-through\nx\n## 2. Riskiest assumption\ny\n## 3. Probe design\nz\n"
                                      "## 4. Kill criterion\nw\nRESULT: PENDING\n")
        ctx.lease = self.lease_of(ctx.state, "11.1")
        self.assertEqual(pipeline.advance(ctx, [step], 0)["type"], "DONE")
        # the step is re-armed the way gap_round_end does it, and its prompt changes
        st.set_step(ctx.state, "11.1", "pending", note="another round", jobs=[])
        ctx.write("08_DECISION.md", "# DECISION: a new decision\n")
        card = pipeline.advance(ctx, [step], 0)
        self.assertEqual(card["type"], "HOST_BATCH")
        self.assertFalse(os.path.exists(out))


# ------------------------------------------------------------------------------------------------ P1-8 idea ids

class IdeaIds(Base):
    def shortlist(self, ctx, crowded):
        ids = ["I-001", "I-002", "I-003", "I-004"]
        ctx.write_json("screen/shortlist.json", {"shortlist": [{"id": i, "score": 4.0, "reason": "r"} for i in ids]})
        for i in ids:
            v = "CROWDED; DIFFERENTIATOR: none" if i in crowded else "ADJACENT; DIFFERENTIATOR: a pilot"
            ctx.write("checks/%s.md" % i, "# Check %s\n\nVERDICT: %s\n" % (i, v))

    def test_renumbered_ids_do_not_exclude_the_wrong_idea(self):
        ctx = self.make_ctx()
        steps = pipeline.load_steps()
        self.shortlist(ctx, crowded=["I-003"])
        registry.run_script(ctx, "k4", {"id": "7.2"})
        self.assertNotIn("I-003", registry.survivors(ctx))
        pipeline.supersede_from(ctx, steps, "5.1")  # `ub import`: the pool is re-curated and bs.py map renumbers
        self.shortlist(ctx, crowded=["I-004"])  # I-003 now names another idea, which has a differentiator
        registry.run_script(ctx, "k4", {"id": "7.2"})
        self.assertIn("I-003", registry.survivors(ctx))
        self.assertEqual(ctx.state["parked"], ["I-004"])

    def test_a_park_is_lifted_when_the_check_changes(self):
        ctx = self.make_ctx()
        steps = pipeline.load_steps()
        self.shortlist(ctx, crowded=["I-003"])
        registry.run_script(ctx, "k4", {"id": "7.2"})
        pipeline.supersede_from(ctx, steps, "7.1")  # redo the checks; the ids stay
        self.shortlist(ctx, crowded=[])
        registry.run_script(ctx, "k4", {"id": "7.2"})
        self.assertEqual(ctx.state["parked"], [])
        self.assertIn("I-003", registry.survivors(ctx))


# ------------------------------------------------------------------------------------------------ probe, switch

@unittest.skipUnless(tl.stubs_available(), "B4 stubs or B2 bs.py missing")
class ProbeAndSwitch(Base):
    def done_run(self):
        ctx = tl.full_auto_ctx(self, mode="quick")
        self.assertEqual(tl.drive(ctx)["type"], "DONE")
        ch = st.load(ctx.run_dir)["choice"]
        self.assertTrue(ch["idea"] and ch["runner_up"], ch)
        return ctx.run_dir, ch

    def ledger_rows(self, run, kind):
        text = textio.read_text(os.path.join(os.path.dirname(run), "LEDGER.md"))
        return [ln for ln in text.split("\n") if "| %s |" % kind in ln]

    def test_a_repeated_missed_kills_only_the_probed_idea(self):
        run, ch = self.done_run()
        rc, card = self.run_ub("probe-result", run, "MISSED", "--json", deps=tl.stub_deps())
        self.assertEqual(st.load(run)["choice"]["idea"], ch["runner_up"])
        rc, again = self.run_ub("probe-result", run, "MISSED", "--json", deps=tl.stub_deps())
        self.assertEqual(again["type"], "BLOCKED", "a repeated MISSED killed the runner-up, whose probe never ran")
        state = st.load(run)
        self.assertEqual(state["choice"]["idea"], ch["runner_up"])
        decision = "".join(textio.read_text(os.path.join(dp, f)) for dp, _d, fs in os.walk(run) for f in fs
                           if f == "08_DECISION.md")
        self.assertNotIn("Killed: %s" % ch["runner_up"], decision)
        rows = self.ledger_rows(run, "probe missed")
        self.assertEqual(len(rows), 1, rows)
        self.assertIn("| %s |" % ch["idea"], rows[0])
        final = tl.drive(st.Ctx(run, state, tl.stub_deps()))
        self.assertEqual(final["type"], "DONE", final.get("say"))
        self.assertEqual(len(self.ledger_rows(run, "probe missed")), 1, "the runner-up got a 'probe missed' row")
        self.assertIn("RESULT: PENDING", textio.read_text(os.path.join(run, "09_PROBE.md")))

    def test_switch_checks_the_idea_and_designs_a_new_probe(self):
        run, ch = self.done_run()
        rc, card = self.run_ub("switch", run, "--idea", "I-999", "--yes", "--json", deps=tl.stub_deps())
        self.assertEqual(card["type"], "BLOCKED")
        self.assertIn("not one of the finalists", card["say"])
        rc, card = self.run_ub("probe-result", run, "PASSED", "--json", deps=tl.stub_deps())
        self.assertIn("RESULT: PASSED", textio.read_text(os.path.join(run, "09_PROBE.md")))
        rc, card = self.run_ub("switch", run, "--idea", ch["runner_up"], "--yes", "--json", deps=tl.stub_deps())
        state = st.load(run)
        self.assertEqual(state["choice"], dict(state["choice"], idea=ch["runner_up"], runner_up=ch["idea"]))
        self.assertIsNone(state.get("probe"), "the old idea's probe result carried over")
        final = tl.drive(st.Ctx(run, state, tl.stub_deps()))
        self.assertEqual(final["type"], "DONE", final.get("say"))
        self.assertNotIn("RESULT: PASSED", textio.read_text(os.path.join(run, "09_PROBE.md")))


# ------------------------------------------------------------------------------------------------ CLI, v1

class Cli(Base):
    def test_init_reads_the_kickoff_text_from_a_file(self):
        text = 'pricing page for $29/month, `touch PWNED`, $(echo hi), "quoted" ü\r\nsecond line'
        root = os.path.join(self.project, "brainstorm")
        os.makedirs(root)
        path = os.path.join(root, ".kickoff.txt")
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write(text)
        rc, card = self.run_ub("init", "--host", "claude-code", "--text-file", path, "--root", self.project,
                               "--no-preflight", "--json")
        self.assertEqual(card["gate"], "G0")
        state = st.load(card["run"])
        self.assertEqual(state["raw_text"], text)
        self.assertEqual(state["topic"], " ".join(text.split()))
        self.assertIn("29", os.path.basename(card["run"]))
        self.assertFalse(os.path.exists(path), "the kickoff file stays in the run root")
        self.assertEqual(textio.read_text(os.path.join(card["run"], ".ub", "kickoff.txt"), normalize=False), text)

    def test_text_and_text_file_are_one_or_the_other(self):
        err = io.StringIO()
        with mock.patch.object(sys, "stderr", err):
            rc, out = self.run_ub("init", "--host", "codex", "--text", "a", "--text-file", "b", "--json")
        self.assertEqual(rc, 2)
        self.assertIn("not allowed with argument", err.getvalue())

    def test_run_takes_the_topic_as_words(self):
        seen = {}

        def fake_init(a, deps=None, terminal=False):
            seen.update(text=a.text, terminal=terminal, host=a.host)
            return {"ok": True}
        with mock.patch.object(ub, "cmd_init", fake_init):
            rc, out = self.run_ub("run", "quick", "AI tutor for night-shift nurses", "--autopilot", "full-auto",
                                  "--json")
        self.assertEqual(rc, 0)
        self.assertEqual(seen, {"text": "quick AI tutor for night-shift nurses", "terminal": True, "host": "terminal"})
        err = io.StringIO()
        with mock.patch.object(sys, "stderr", err):
            self.assertEqual(self.run_ub("run", "a topic", "--continue", "x", "--json")[0], 2)

    def test_v1_runs_migrate_only_under_the_lock_and_keep_the_original(self):
        run = os.path.join(self.project, "brainstorm", "2026-01-10-habit-coach")
        shutil.copytree(tl.fixture_path("v1_run", "2026-01-10-habit-coach"), run)
        original = raw(os.path.join(run, "00_RUN.md"))
        rc, status = self.run_ub("status", run, "--json")
        self.assertEqual(status["step"], "6.1")
        self.assertFalse(os.path.exists(os.path.join(run, "run.json")), "a read-only command migrated the run")
        self.assertEqual(raw(os.path.join(run, "00_RUN.md")), original)
        self.run_ub("next", run, "--wait-s", "0", "--json")
        self.assertTrue(st.load(run)["legacy_v1"])
        self.assertEqual(raw(os.path.join(run, "00_RUN.v1.md")), original)


if __name__ == "__main__":
    unittest.main()
