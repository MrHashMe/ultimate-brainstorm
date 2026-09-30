"""Phase H, engine CLI: the round-3 open items of `ub.py` and the engine it drives (KIT_SPEC 4.11, 4.12, 6.3, 6.10;
audit items F16, F82, P3-engine-1, R-engine-0, X12, NEW-G1-engine-host-stop-1, NEW-G2-engine-misc-1 and the reviewer
claims on busy retries and cross-host shim checks).

- a busy card never double-quotes an argument with a typographic double quote (PowerShell ends the string there)
- `init --text "continue RUN"` refused by a busy run is retried as `continue RUN`, never BLOCKED
- an answer file holds an object or a string; any other JSON value re-asks the gate
- an idea ID named twice in a list counts once; the G8b runner-up is another idea than the chosen one
- `ub run "<topic>"` whose first word is a command word starts a run with that topic
- `ub run --continue` takes over a host task another session holds
- `continue --host` checks the .cmd shims of the families that will read the repository
- the lease holder's HUMAN and BLOCKED cards carry its --lease; a lease is dropped once every host job has its outcome
- a judge seat an upgrade removed leaves the judge step in flight: its jobs, workers, outputs and prompts
"""

import io
import json
import os
import subprocess
import sys
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fixtures", "engine"))
import engine_testlib as tl  # noqa: E402

from ublib import textio  # noqa: E402
from ublib.engine import builders, gates, pipeline, progress, registry  # noqa: E402
from ublib.engine import state as st  # noqa: E402

sys.path.insert(0, tl.SCRIPTS)
import ub  # noqa: E402

sys.path.insert(0, os.path.join(tl.KIT, "tests", "harness"))
from answerer import ub_args  # noqa: E402

HOLD_CODE = ("import os, sys, time\nsys.path.insert(0, %r)\n"
             "from ublib.engine import state as st\n"
             "lk = st.DriverLock(sys.argv[1], 'helper')\nassert lk.acquire()\nlk.announce()\n"
             "open(sys.argv[2], 'w').close()\n"
             "while not os.path.exists(sys.argv[3]): time.sleep(0.02)\n"
             "lk.release()\n" % tl.SCRIPTS)


def gen_text(job):
    return "### %s-01 t\n- Pitch: p\n- Mechanism: m\n- Fails if: f\n" % job["contract"].get("prefix", "S")


def step(sid):
    """A step of the pipeline without its `when`, so a test can put it first."""
    s = dict(pipeline.step_by_id(pipeline.load_steps(), sid))
    s.pop("when", None)
    return s


def done_before(ctx, sid):
    for s in pipeline.load_steps():
        if s["id"] == sid:
            break
        st.set_step(ctx.state, s["id"], "done", note="setup")
    st.save(ctx.run_dir, ctx.state)


class Base(tl.EngineTestCase):
    def run_ub(self, *args, **kw):
        out = io.StringIO()
        stdin = io.StringIO(kw.get("stdin", ""))
        with mock.patch.object(sys, "stdout", out), mock.patch.object(sys, "stdin", stdin):
            rc = ub.main([str(a) for a in args], deps=kw.get("deps") or tl.FakeDeps(detect=tl.fake_detect()))
        text = out.getvalue()
        return rc, (json.loads(text) if text.strip().startswith("{") else text)

    def new_run(self, *extra, **kw):
        rc, card = self.run_ub("init", "--host", kw.get("host", "claude-code"), "--text", "shift-swap app for nurses",
                               "--root", self.project, "--no-preflight", "--json", *extra, deps=kw.get("deps"))
        self.assertEqual(rc, 0, card)
        return card["run"]

    def hold(self, run):
        """A helper process drives the run until the returned function releases it (barrier files)."""
        barrier = os.path.join(self.tmp, "held-%d" % len(os.listdir(self.tmp)))
        release = barrier + ".go"
        p = subprocess.Popen([sys.executable, "-c", HOLD_CODE, run, barrier, release])

        def stop():
            if p.poll() is None:
                open(release, "w").close()
                p.wait(timeout=30)
        self.addCleanup(stop)
        end = time.monotonic() + 60
        while not os.path.exists(barrier):
            if p.poll() is not None or time.monotonic() > end:
                raise AssertionError("the helper never reached its barrier")
            time.sleep(0.02)
        return stop


# ------------------------------------------------------------------------------------------------ busy retries

class BusyRetry(Base):
    def test_a_typographic_double_quote_is_never_quoted(self):
        """P3-engine-1: PowerShell ends a double-quoted string at U+201C, U+201D and U+201E, so an argument holding one
        of them has no quoting all three shells keep."""
        for bad in ("B\u201d; Write-Output INJECTED; \u201cx", "a\u201cb", "a\u201eb"):
            self.assertIsNone(ub.shell_arg(bad), ascii(bad))
        self.assertEqual(ub.shell_arg("C:\\runs\\my \u2019s run"), '"C:/runs/my \u2019s run"')  # a single quote is fine
        run = self.new_run()
        release = self.hold(run)
        rc, card = self.run_ub("switch", run, "--arch", "B\u201d; Write-Output INJECTED; \u201cx", "--yes", "--json")
        self.assertEqual(card["type"], "BLOCKED")
        self.assertIn("was not applied", card["say"])
        self.assertIsNone(card["then"])
        release()

    def test_continue_through_init_text_is_retried_as_continue(self):
        """The Start path writes `continue RUN` to the kickoff text and runs init: refused by a busy run, its `then` is
        the `continue` command itself, not a BLOCKED card about unquotable arguments."""
        run = self.new_run()
        release = self.hold(run)
        rc, card = self.run_ub("init", "--host", "claude-code", "--text", "continue " + run, "--json")
        self.assertEqual(card["type"], "AUTO", card.get("say"))
        self.assertIn("another session is driving", card["say"])
        self.assertEqual(ub_args(card["then"]), ["continue", textio.to_posix(run), "--host", "claude-code", "--json"])
        release()
        rc, card = self.run_ub(*ub_args(card["then"]))
        self.assertNotIn("another session", card.get("say") or "")


# ------------------------------------------------------------------------------------------------ answers

class AnswerShapes(Base):
    def at_gate(self, gid, sid, **state):
        ctx = self.make_ctx(autopilot="hands-on", run_name="run-%s" % gid)
        ctx.state.update(state)
        steps = [{"id": sid, "stage": 13, "title": "Gate", "type": "HUMAN", "gate": gid}]
        self.assertEqual(pipeline.advance(ctx, steps, 0)["gate"], gid)
        st.save(ctx.run_dir, ctx.state)
        return ctx, steps

    def answer_file(self, ctx, steps, gid, value):
        path = os.path.join(self.tmp, "answer-%s.json" % gid)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(value, f)
        with mock.patch.object(pipeline, "load_steps", return_value=steps):
            return self.run_ub("answer", ctx.run_dir, gid, "--file", path, "--json", deps=ctx.deps)[1]

    def test_an_answer_file_that_is_not_an_object_or_a_string_is_re_asked(self):
        """F16: `true` or `["approve"]` at G13 were applied as the free text 'True' / "['approve']" and started a paid
        change round."""
        ctx, steps = self.at_gate("G13", "13.8")
        for value in (True, ["approve"], 5, None):
            card = self.answer_file(ctx, steps, "G13", value)
            self.assertEqual((card["type"], card["gate"]), ("HUMAN", "G13"), value)
            self.assertIn("must be a JSON object like the answer template, or the reply as a JSON string",
                          card["error"] or "")
            state = st.load(ctx.run_dir)
            self.assertEqual(int((state.get("counters") or {}).get("g13_loops", 0)), 0, value)
            self.assertNotIn("G13", state.get("gates") or {})
        card = self.answer_file(ctx, steps, "G13", "approve")  # a string is the reply
        self.assertEqual(st.load(ctx.run_dir)["gates"]["G13"]["answer"]["action"], "approve")

    def test_a_duplicate_id_counts_once(self):
        """NEW-G2-engine-misc-1: G6 [X, X] passed 'at least 2 finalists' and blocked the tournament later."""
        pool = ["I-001", "I-002", "I-003"]
        ctx, steps = self.at_gate("G6", "9.1h")
        with mock.patch.object(registry, "finalist_pool", return_value=pool):
            ans, notes, errs = gates.prepare_answer(ctx, "G6", {"finalists": ["I-001", "I-001"]})
            self.assertEqual(ans["finalists"], ["I-001"])
            self.assertTrue(errs and "at least 2 finalists" in errs[0], errs)
            self.assertIn("G6 finalists: duplicate IDs removed (I-001)", notes)
            ans, notes, errs = gates.prepare_answer(ctx, "G6", {"finalists": "I-002, I-001, I-002"})
            self.assertEqual((ans["finalists"], errs), (["I-002", "I-001"], []))
        ctx.state["finalists"] = pool
        ans, notes, errs = gates.prepare_answer(ctx, "G7", {"picks": ["I-001", "I-001", "I-001"]})
        self.assertEqual(ans["picks"], ["I-001"])

    def test_the_runner_up_is_another_idea(self):
        ctx, steps = self.at_gate("G8b", "10.5", finalists=["I-001", "I-002"], top=["I-001", "I-002"])
        errs = gates.prepare_answer(ctx, "G8b", {"chosen": "I-002", "runner_up": "I-002"})[2]
        self.assertTrue(errs and "runner-up must be another idea" in errs[0], errs)
        with mock.patch.object(registry, "suggestion", return_value=("I-001", "leader")):
            errs = gates.prepare_answer(ctx, "G8b", {"accept_recommendation": True, "runner_up": "I-001"})[2]
            self.assertTrue(errs and "runner-up must be another idea" in errs[0], errs)
            self.assertEqual(gates.prepare_answer(ctx, "G8b", {"accept_recommendation": True,
                                                               "runner_up": "I-002"})[2], [])


# ------------------------------------------------------------------------------------------------ ub run words

class RunTopicWords(Base):
    def run_terminal(self, *args):
        seen = []

        def fake_loop(ctx, steps, lock=None, **kw):  # never reads stdin
            seen.append(ctx)
            return {"type": "DONE", "say": "x"}
        with mock.patch("ublib.engine.terminal.run_loop", fake_loop):
            rc, res = self.run_ub("run", *args)
        return rc, res, seen

    def test_a_topic_that_starts_with_a_command_word_starts_a_run(self):
        """F82: `ub run "stop smoking coach for nurses"` ran `stop` on a folder 'smoking coach for nurses'."""
        for topic in ("stop smoking coach for nurses", "status page for small SaaS", "continue education platform",
                      "doctor appointment reminders"):
            rc, res, seen = self.run_terminal(topic, "--root", self.project, "--no-preflight", "--json")
            self.assertEqual(rc, 0, res)
            self.assertEqual(len(seen), 1, (topic, res))
            self.assertEqual(seen[0].state["topic"], topic)
        path = os.path.join(self.tmp, "topic.txt")
        textio.write_text_atomic(path, "stop smoking coach for night nurses\n")
        rc, res, seen = self.run_terminal("--text-file", path, "--root", self.project, "--no-preflight", "--json")
        self.assertEqual(seen[0].state["topic"], "stop smoking coach for night nurses")

    def test_a_command_word_before_a_run_folder_or_nothing_stays_a_command(self):
        run = self.new_run()
        before = sorted(os.listdir(os.path.dirname(run)))
        rc, res, seen = self.run_terminal("status", "--root", self.project, "--json")
        self.assertEqual((res.get("run"), seen), (textio.to_posix(run), []))
        rc, res, seen = self.run_terminal("status", os.path.basename(run), "--root", self.project, "--json")
        self.assertEqual(res.get("run"), textio.to_posix(run))  # a run's name under the run root
        rc, res, seen = self.run_terminal("continue", run, "--json")
        self.assertEqual([os.path.normcase(c.run_dir) for c in seen], [os.path.normcase(run)])
        self.assertEqual(sorted(os.listdir(os.path.dirname(run))), before)


class TerminalTakeover(Base):
    def test_run_continue_takes_over_an_agents_host_task(self):
        """NEW-G1-engine-host-stop-1: an agent got the HOST card (a lease of an hour), then the user resumes in a
        terminal: the terminal skips the host task at once instead of waiting for the lease to expire."""
        deps = tl.FakeDeps(detect=tl.fake_detect())
        ctx = self.make_ctx(mode="deep", deps=deps)
        st.save(ctx.run_dir, ctx.state)
        steps = [step("1.2")]
        with mock.patch.object(pipeline, "load_steps", return_value=steps):
            rc, card = self.run_ub("next", ctx.run_dir, "--wait-s", "0", "--json", deps=deps)
            self.assertEqual(card["type"], "HOST")
            t0 = deps.now()
            rc, text = self.run_ub("run", "--continue", ctx.run_dir, deps=deps)
        self.assertLess(deps.now() - t0, 60, text)
        self.assertNotIn("in progress in another session", text)
        self.assertEqual(st.step_state(st.load(ctx.run_dir), "1.2"), "skipped")


# ------------------------------------------------------------------------------------------------ .cmd shims

def detect_two(host_family):
    def detect(live=False, only=None):
        fams = {}
        for f in tl.FAMS:
            bid = {"claude": "claude-cli", "gpt": "codex-cli"}.get(f)
            fams[f] = {"available": bool(bid), "backend": bid, "chain": [bid] if bid else [], "web": bool(bid),
                       "notes": [] if bid else ["not set up"]}
        return {"schema": 1, "host": {"family": host_family, "source": "default"}, "families": fams}
    return detect


class CrossHostShims(Base):
    def reseat(self, shims):
        """`continue --host codex` of a claude-hosted software run in a git repository under 'R&D'; `shims`: the
        programs that resolve to a .cmd shim."""
        from ublib import proc
        project = os.path.join(self.tmp, "R&D")
        os.makedirs(os.path.join(project, ".git"))
        ctx = self.make_ctx(variant="software", families=("claude", "gpt"), deps=tl.FakeDeps(detect=detect_two("gpt")))
        ctx.state["project_dir"] = project
        ext = lambda name, env=None: "C:/bin/%s.%s" % (name, "cmd" if name in shims else "exe")  # noqa: E731
        with mock.patch.object(proc, "resolve_exe", side_effect=ext):
            ub.reseat_for_host(ctx, "codex")
        return ctx, ctx.state["families"]

    def test_the_family_that_keeps_the_repository_is_checked(self):
        """claude keeps the run's host family (its CLI still reaches it), so its jobs keep reading the repository:
        its claude.cmd is checked against the 'R&D' paths. It cannot take them, so the new agent's family hosts the
        run, and claude stays available for the jobs that read no repository."""
        ctx, fams = self.reseat({"claude"})
        self.assertEqual(ctx.host_family, "gpt")
        self.assertEqual((fams["claude"]["status"], fams["claude"]["backend"]), ("ok", "claude-cli"))
        self.assertFalse(registry.repo_access(ctx, "claude"))
        self.assertEqual(fams["gpt"]["backend"], "codex-cli")

    def test_the_new_agents_family_is_not_taken_off_its_cli_for_nothing(self):
        ctx, fams = self.reseat({"codex"})
        self.assertEqual(ctx.host_family, "claude")
        self.assertEqual((fams["gpt"]["status"], fams["gpt"]["backend"]), ("ok", "codex-cli"), fams["gpt"]["reason"])
        self.assertEqual(fams["claude"]["backend"], "claude-cli")


# ------------------------------------------------------------------------------------------------ R-engine-0 leases

class HeldBatch(tl.FakeBatch):
    """CLI jobs are answered at launch; the first one reads 'running' until the fake clock reaches release_at."""

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


class LeaseHolder(Base):
    def mixed_4_2(self, batch, **kw):
        """Step 4.2 with claude's jobs on host sub-agents and the other families on their CLIs (zcode, W = 50 s)."""
        deps = tl.FakeDeps(batch=batch)
        if isinstance(batch, HeldBatch):
            batch.clock = deps.now
        ctx = self.make_ctx(agent="zcode", deps=deps, **kw)
        ctx.state["families"]["claude"]["backend"] = "host"
        ctx.state["exec"]["wait_s"] = 50
        done_before(ctx, "4.2")
        rc, card = self.run_ub("next", ctx.run_dir, "--wait-s", "0", "--json", deps=deps)
        self.assertEqual(card["type"], "HOST_BATCH")
        return ctx, deps, card

    def test_a_gb_card_to_the_lease_holder_carries_its_lease(self):
        """R-engine-0 (a): the holder's own poll hits the request cap while one of its sub-agent outputs must be
        handed out again. Its GB answer_cmd carries --lease, so the answer re-issues the job at once instead of
        waiting, as 'another session', for the lease to expire."""
        import stubs
        batch = tl.FakeBatch(outputs=gen_text, requests=1)
        ctx, deps, card = self.mixed_4_2(batch)
        victim = batch.launched[0]  # a CLI job failed meanwhile: its fallback needs a launch the cap refuses
        job = builders.load_job(ctx, victim)
        textio.write_json_atomic(ctx.path(job["out"] + ".meta.json"), {
            "id": victim, "family": job["family"], "status": "failed", "error_class": "internal",
            "prompt_sha256": textio.sha256_file(ctx.path(job["prompt_file"]))})
        s = st.load(ctx.run_dir)
        s.setdefault("budget", {})["max_calls"] = progress.requests_used(st.Ctx(ctx.run_dir, s, deps))
        st.save(ctx.run_dir, s)
        for i, j in enumerate(card["jobs"]):  # the first sub-agent writes a valid output, the second an invalid one
            hjob = textio.read_json(ctx.path("jobs", j["id"] + ".json"))
            textio.write_text_atomic(j["out"], stubs.respond(hjob, textio.read_text(j["prompt_file"])) if i == 0 else
                                     "x\n")
        token = card["then"].split("--lease ")[1].split()[0]
        rc, card = self.run_ub(*ub_args(card["then"]), deps=deps)
        self.assertEqual((card["type"], card["gate"]), ("HUMAN", "GB"))
        self.assertIn("--lease %s" % token, card["answer_cmd"])
        textio.write_json_atomic(card["answer_file"], {"reply": "raise to 500", "raise_to": 500, "stop": None})
        t0 = deps.now()
        rc, card = self.run_ub(*ub_args(card["answer_cmd"]), deps=deps)
        self.assertEqual(card["type"], "HOST_BATCH", card.get("say"))  # the invalid output's job, handed out again
        self.assertIn("--lease", card["then"])
        self.assertLess(deps.now() - t0, 60)

    def test_a_blocked_fix_for_the_lease_holder_carries_its_lease(self):
        """R-engine-0 (a): the full-auto budget stop of the holder's poll: its fix (`ub budget`) carries --lease."""
        import stubs
        batch = tl.FakeBatch(outputs=gen_text, requests=1)
        ctx, deps, card = self.mixed_4_2(batch, autopilot="full-auto")
        victim = batch.launched[0]
        job = builders.load_job(ctx, victim)
        textio.write_json_atomic(ctx.path(job["out"] + ".meta.json"), {
            "id": victim, "family": job["family"], "status": "failed", "error_class": "internal",
            "prompt_sha256": textio.sha256_file(ctx.path(job["prompt_file"]))})
        s = st.load(ctx.run_dir)
        s.setdefault("budget", {})["max_calls"] = progress.requests_used(st.Ctx(ctx.run_dir, s, deps))
        st.save(ctx.run_dir, s)
        for j in card["jobs"]:
            hjob = textio.read_json(ctx.path("jobs", j["id"] + ".json"))
            textio.write_text_atomic(j["out"], "x\n")  # invalid: handed out again after the cap is raised
        token = card["then"].split("--lease ")[1].split()[0]
        rc, card = self.run_ub(*ub_args(card["then"]), deps=deps)
        self.assertEqual(card["type"], "BLOCKED", card.get("say"))
        fixes = [f for f in card["fix"] if " budget " in f]
        self.assertTrue(fixes and all("--lease %s --json" % token in f for f in fixes), card["fix"])

    @unittest.skipUnless(tl.stubs_available(), "B4 stubs or B2 bs.py missing")
    def test_the_holder_waits_only_for_its_own_open_file(self):
        """R-engine-0 (b), pins the AUTO `then` of the holder (#96): a sub-agent output that cannot be made durable
        yet (still open) reads 'running'; every card's `then` carries the lease, so the step is done right after the
        file is released, never at the lease's expiry, and no card blames another session."""
        import stubs
        batch = tl.FakeBatch(outputs=gen_text)
        ctx, deps, card = self.mixed_4_2(batch)
        for j in card["jobs"]:
            hjob = textio.read_json(ctx.path("jobs", j["id"] + ".json"))
            textio.write_text_atomic(j["out"], stubs.respond(hjob, textio.read_text(j["prompt_file"])))
        t0 = deps.now()
        release_at = t0 + 120
        real = pipeline._make_durable

        def held(path):
            if deps.now() < release_at:
                raise PermissionError(13, "the sub-agent still has the file open")
            return real(path)
        says = []
        with mock.patch.object(pipeline, "_make_durable", held):
            for _ in range(40):
                rc, card = self.run_ub(*ub_args(card["then"]), deps=deps)
                says.append(card.get("say") or "")
                if st.step_state(st.load(ctx.run_dir), "4.2") == "done" or card["type"] != "AUTO":
                    break
        self.assertEqual(st.step_state(st.load(ctx.run_dir), "4.2"), "done", says)
        self.assertLessEqual(deps.now() - t0, 120 + 50 + 5, says)
        self.assertFalse([s for s in says if "another session" in s], says)

    @unittest.skipUnless(tl.stubs_available(), "B4 stubs or B2 bs.py missing")
    def test_the_lease_goes_once_every_host_job_has_its_outcome(self):
        """R-engine-0 (b), pins the lease drop (#96): the holder's poll records every host outcome while a CLI job
        still runs; the step's lease is gone at once, so no poll waits for it."""
        import stubs
        batch = HeldBatch(None, outputs=gen_text)
        batch.release_at = 10 ** 9
        ctx, deps, card = self.mixed_4_2(batch)
        for j in card["jobs"]:
            hjob = textio.read_json(ctx.path("jobs", j["id"] + ".json"))
            textio.write_text_atomic(j["out"], stubs.respond(hjob, textio.read_text(j["prompt_file"])))
        self.assertIn("lease", st.load(ctx.run_dir)["steps"]["4.2"])
        rc, card = self.run_ub(*ub_args(card["then"]), deps=deps)
        sst = st.load(ctx.run_dir)["steps"]["4.2"]
        self.assertEqual((card["type"], sst["state"]), ("AUTO", "running"))
        self.assertNotIn("lease", sst)


# ------------------------------------------------------------------------------------------------ X12 in flight

class Holding(tl.FakeBatch):
    """Launched jobs write their output at once and then read 'running' until the test empties `running`."""

    def launch_job(self, job_path, expect_gen=None):
        info = tl.FakeBatch.launch_job(self, job_path, expect_gen)
        self.running.add(info["job_id"])
        return info


class InFlightJudges(Base):
    CFG = {"defaults": {"parallel": 4, "retries": 1}, "families": {"claude": {"alt_model": None}}}

    def two_judge_run(self, batch):
        ctx = self.make_ctx(families=("claude",), deps=tl.FakeDeps(batch=batch))  # seated as 2.0.3 did: the host twice
        self.assertEqual(ctx.seats["screen_judges"], ["claude", "claude-alt"])
        return ctx

    def test_a_judge_step_in_flight_drops_the_seat_the_upgrade_removed(self):
        """X12: 6.2 was built with [claude, claude-alt] and is running when the kit is updated (alt_model null): the
        claude-alt judge leaves the step, its worker stops and its output and prompt move aside, so the tally counts
        one judge."""
        batch = Holding()
        ctx = self.two_judge_run(batch)
        ctx.write("screen/ideas.md", "I-001 | a\nI-002 | b\n")
        for label in ("claude", "claude-alt"):
            ctx.write("screen/%s.prompt.md" % label, "prompt for %s\n" % label)
        done_before(ctx, "6.2")
        card = pipeline.advance(ctx, [step("6.2")], 0)
        self.assertEqual(card["type"], "AUTO")
        self.assertTrue(ctx.exists("screen/claude-alt.out.json"))  # the alt judge had already answered
        ub.with_run(ctx.run_dir, tl.FakeDeps(batch=batch, cfg=self.CFG), lambda c, lock: None)
        state = st.load(ctx.run_dir)
        sst = state["steps"]["6.2"]
        self.assertEqual((sst["jobs"], sst["originals"]), (["6.2-claude"], ["6.2-claude"]))
        self.assertEqual(state["seats"]["screen_judges"], ["claude"])
        self.assertEqual(batch.stopped, ["6.2-claude-alt"])
        self.assertEqual(batch.running, {"6.2-claude"})
        for rel in ("screen/claude-alt.out.json", "screen/claude-alt.prompt.md", "jobs/6.2-claude-alt.json"):
            self.assertFalse(ctx.exists(rel), rel)
        self.assertTrue(ctx.exists("screen/claude.out.json"))
        self.assertTrue([p for p in os.listdir(ctx.path("_superseded"))])
        batch.running = set()
        ctx = st.Ctx(ctx.run_dir, st.load(ctx.run_dir), tl.FakeDeps(batch=batch, cfg=self.CFG))
        n = len(batch.launched)
        self.assertEqual(pipeline.advance(ctx, [step("6.2")], 0)["type"], "DONE")
        self.assertEqual(batch.launched[n:], [])
        self.assertEqual(ctx.state["steps"]["6.2"]["note"], "1/1 ok (1 family)")

    def test_prepared_tournament_prompts_of_the_removed_seat_move_aside(self):
        """X12: 9.3 prepared prompts for both judges; the 9.4 fan-out reads them: after the upgrade it builds the
        seated judge's jobs only."""
        ctx = self.two_judge_run(tl.FakeBatch())
        for label in ("claude", "claude-alt"):
            for order in ("fwd", "rev"):
                ctx.write("tournament/%s_%s.prompt.md" % (label, order), "prompt\n")
                ctx.write_json("tournament/%s_%s.map.json" % (label, order), {"family": label, "order": order,
                                                                               "pairs": {"P01": {}}})
        done_before(ctx, "9.4")
        ub.with_run(ctx.run_dir, tl.FakeDeps(cfg=self.CFG), lambda c, lock: None)
        ctx = st.Ctx(ctx.run_dir, st.load(ctx.run_dir), tl.FakeDeps(cfg=self.CFG))
        ids = [j["id"] for j in builders.build_jobs(ctx, step("9.4"), write=False)]
        self.assertEqual(sorted(ids), ["9.4-claude_fwd", "9.4-claude_rev"])

    def test_a_done_judge_step_keeps_what_it_counted(self):
        ctx = self.two_judge_run(tl.FakeBatch())
        ctx.write("screen/claude-alt.out.json", "{}\n")
        done_before(ctx, "6.3")
        st.set_step(ctx.state, "6.2", "done", jobs=["6.2-claude", "6.2-claude-alt"])
        st.save(ctx.run_dir, ctx.state)
        ub.with_run(ctx.run_dir, tl.FakeDeps(cfg=self.CFG), lambda c, lock: None)
        self.assertEqual(st.load(ctx.run_dir)["steps"]["6.2"]["jobs"], ["6.2-claude", "6.2-claude-alt"])
        self.assertTrue(ctx.exists("screen/claude-alt.out.json"))


if __name__ == "__main__":
    unittest.main()
