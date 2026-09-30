"""Phase F1 engine follow-ups (cross-package requests X1, X2, X3, X8, X11, X12).

X1  the kickoff card and `ub doctor` name the user instructions that still reach an available family's worker calls
    (detect's "user context: " notes; finding 28).
X2  `ub stop` keeps the marker of a live worker whose identity cannot be read and names its pid on the stop card
    (it is never killed, and it used to vanish without a word).
X3  state.long_paths_enabled is textio's one (cached) registry reading.
X8  launch_job after stopping a stale worker: the outcome that worker recorded meanwhile stands, and a new worker gets
    the job's outcome generation as it is now; a job the kit itself is stopping leaves no 'killed' evidence.
X11 ARCH-FIX and PROPOSAL-FIX may write exactly the files they fix (a quoted FILE marker to a stray path fails).
X12 a kit 2.0.3 single-family run seated [host, host-alt] as judges with alt_model null keeps one judge.
No model CLI and no network.
"""

import argparse
import json
import os
import subprocess
import sys
import time
import types
import unittest
from unittest import mock

_TESTS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_TESTS, "fixtures", "engine"))
sys.path.insert(0, os.path.join(_TESTS, "fixtures", "adapter"))
import adapter_testlib as atl  # noqa: E402
import engine_testlib as tl  # noqa: E402

import ub  # noqa: E402
from ublib import batch, proc, textio, validate  # noqa: E402
from ublib.engine import migrate, pipeline, registry  # noqa: E402
from ublib.engine import state as st  # noqa: E402

CODEX_NOTE = "codex-cli workers load the user's Codex instructions C:/Users/u/.codex/AGENTS.md"
DETECT = {"schema": 1, "host": {"family": "claude", "source": "default"}, "families": {
    "claude": {"available": True, "backend": "claude-cli", "chain": ["claude-cli"], "web": True, "notes": []},
    "gpt": {"available": True, "backend": "codex-cli", "chain": ["codex-cli"], "web": True,
            "notes": ["user context: " + CODEX_NOTE, "codex 0.40 found"]},
    "kimi": {"available": False, "backend": None, "chain": [], "web": False,
             "notes": ["user context: kimi-cli workers read something", "kimi not set up"]},
    "glm": {"available": False, "backend": None, "chain": [], "web": False, "notes": []}}}


def sleeper():
    """A live process that is not a worker (a stand-in whose identity the test controls)."""
    return subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"], stdin=subprocess.DEVNULL,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def stop_proc(p):
    try:
        p.kill()
        p.wait(timeout=30)
    except OSError:
        pass


# ---------------------------------------------------------------- X1

class UserContextTests(tl.EngineTestCase):
    def test_family_table_keeps_the_notes_of_available_families(self):
        fams = ub.family_table(DETECT, "claude-code", "claude")
        self.assertEqual(fams["gpt"]["user_context"], [CODEX_NOTE])
        self.assertEqual(fams["gpt"]["status"], "ok")
        self.assertNotIn("user_context", fams["kimi"])   # unavailable: its notes are its reason, as before
        self.assertNotIn("user_context", fams["claude"])

    def test_the_kickoff_card_names_them(self):
        ctx = self.make_ctx(families=("claude", "gpt", "kimi"))
        ctx.state["families"]["gpt"]["user_context"] = [CODEX_NOTE]
        ctx.state["families"]["glm"]["user_context"] = ["glm is not seated: never shown"]
        st.set_step(ctx.state, "0.1", "done")
        card = pipeline.advance(ctx, pipeline.load_steps(), 0)
        self.assertEqual(card["gate"], "G0")
        self.assertIn("Still reaching worker calls: " + CODEX_NOTE, card["show"])
        self.assertNotIn("never shown", card["show"])

    def test_doctor_names_them(self):
        res = types.SimpleNamespace(returncode=0, stdout_bytes=json.dumps(DETECT).encode("ascii"), stderr_bytes=b"")
        with mock.patch.object(proc, "run", return_value=res):
            out = ub.cmd_doctor(argparse.Namespace(live=False, json=True))
        checks = dict((c["id"], c) for c in out["checks"])
        self.assertEqual(checks["user_context_gpt"]["status"], "WARN")
        self.assertEqual(checks["user_context_gpt"]["message"], "Still reaching worker calls: " + CODEX_NOTE)
        self.assertNotIn("user_context_kimi", checks)


# ---------------------------------------------------------------- X2

class UnverifiableWorkerTests(tl.EngineTestCase):
    def marker(self, run_dir, job_id, pid):
        path = batch.marker_path(run_dir, job_id)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        # a worker that could not read its own identity (ps unavailable on macOS, another user's process)
        textio.write_json_atomic(path, {"pid": pid, "ident": None, "started_at": textio.now_iso(),
                                        "heartbeat_at": textio.now_iso(), "attempt": 0, "backend": None})
        return path

    def test_its_marker_is_kept_and_its_pid_reported(self):
        ctx = self.make_ctx()
        p = sleeper()
        self.addCleanup(stop_proc, p)
        path = self.marker(ctx.run_dir, "4.2-S3", p.pid)
        res = batch.stop_workers(ctx.run_dir)
        self.assertEqual(res, {"stopped": 0, "unverified": [p.pid]})
        self.assertTrue(os.path.exists(path), "the marker of a worker that may still run is kept")
        self.assertIsNone(p.poll(), "a process that cannot be verified is never killed")
        self.assertEqual(batch.stop_all(ctx.run_dir), 0)

    def test_a_dead_workers_marker_goes(self):
        ctx = self.make_ctx()
        p = sleeper()
        stop_proc(p)
        path = self.marker(ctx.run_dir, "4.2-S3", p.pid)
        self.assertEqual(batch.stop_workers(ctx.run_dir), {"stopped": 0, "unverified": []})
        self.assertFalse(os.path.exists(path))

    def test_the_stop_card_names_them(self):
        ctx = self.make_ctx(deps=tl.FakeDeps(batch=batch))
        st.save(ctx.run_dir, ctx.state)
        p = sleeper()
        self.addCleanup(stop_proc, p)
        self.marker(ctx.run_dir, "4.2-S3", p.pid)
        out = ub.cmd_stop(argparse.Namespace(run=ctx.run_dir, root=None, json=True), tl.FakeDeps(batch=batch))
        self.assertEqual(out["unverified"], [p.pid])
        self.assertIn("1 worker(s) could not be verified (pid %d): stop them by hand" % p.pid, out["say"])


# ---------------------------------------------------------------- X3

class LongPathsTests(unittest.TestCase):
    def test_one_reading(self):
        with mock.patch.object(textio, "long_paths_enabled", return_value="textio's reading"):
            self.assertEqual(st.long_paths_enabled(), "textio's reading")


# ---------------------------------------------------------------- X8

class _Spawned(object):
    pid = 424242

    def poll(self):
        return 0


class LaunchAfterStaleStopTests(atl.AdapterTestCase):
    def setUp(self):
        super(LaunchAfterStaleStopTests, self).setUp()
        self.job = self.make_job(job_id="x8", family="claude")
        self.path = self.write_job(self.job)
        self.started = textio.now_iso()
        self.stale = {"pid": 4242, "ident": "win:1", "started_at": self.started, "heartbeat_at": self.started}
        self.spawned = []

    def spawn(self, argv, logf, run_dir, token=None, gen=None):
        self.spawned.append(gen)
        return _Spawned()

    def launch(self, during_stop):
        def stop(*_a, **_k):
            during_stop()
            return True
        with mock.patch.object(batch, "_stands", return_value=False), \
                mock.patch.object(batch, "_read_marker", return_value=(True, dict(self.stale))), \
                mock.patch.object(batch, "_stop_stale_worker", side_effect=stop), \
                mock.patch.object(batch, "_spawn_detached", side_effect=self.spawn):
            return batch.launch_job(self.path, expect_gen=0)

    def meta(self, status, started):
        prompt = os.path.join(self.run_dir, self.job["prompt_file"])
        rec = {"schema": 1, "id": "x8", "status": status, "started": started,
               "prompt_sha256": textio.sha256_file(prompt)}
        if status == "ok":
            textio.write_text_atomic(self.out_path(self.job), "A valid answer text.")
            rec["out_sha256"] = textio.sha256_file(self.out_path(self.job))
        textio.write_json_atomic(self.out_path(self.job) + ".meta.json", rec)

    def test_the_new_worker_gets_the_generation_as_it_is_now(self):
        # the stopped worker counted its run on the way out; a new worker launched with the old generation would
        # skip the job as "finished" by that run, and the job would stay without an outcome
        info = self.launch(lambda: batch._bump_gen(self.run_dir, "x8"))
        self.assertTrue(info["launched"])
        self.assertEqual(self.spawned, [1])

    def test_a_result_the_stopped_worker_wrote_stands(self):
        def finished():
            self.meta("ok", textio.now_iso())
            batch._bump_gen(self.run_dir, "x8")
        info = self.launch(finished)
        self.assertEqual((info["launched"], info["state"]), (False, "done"))
        self.assertEqual(self.spawned, [])
        self.assertFalse(os.path.exists(batch.marker_path(self.run_dir, "x8")))

    def test_a_failure_it_recorded_during_its_launch_stands(self):
        def failed():
            self.meta("failed", textio.now_iso())
            batch._bump_gen(self.run_dir, "x8")
        info = self.launch(failed)
        self.assertEqual((info["launched"], info["state"]), (False, "failed"))
        self.assertEqual(self.spawned, [])

    def test_an_older_failure_is_relaunched(self):
        # a failed meta from before the stale launch (the launch was its retry) is not the stopped worker's outcome
        self.meta("failed", "2026-01-01T00:00:00Z")
        info = self.launch(lambda: None)
        self.assertTrue(info["launched"])
        self.assertEqual(self.spawned, [0])


class KitStopEvidenceTests(atl.AdapterTestCase):
    def test_a_signal_while_the_kit_stops_the_job_records_nothing(self):
        job = self.make_job(job_id="x8s", family="claude")
        job["_path"] = self.write_job(job)
        stopping = os.path.join(self.run_dir, ".ub", "jobs", "x8s.stopping")
        with self.assertRaises(SystemExit):
            with batch.WorkerMarker(self.run_dir, "x8s", job=job) as marker:
                self.assertIsNone(marker.skipped)
                textio.write_text_atomic(stopping, "%d\n" % os.getpid())  # stop_workers / _stop_stale_worker
                raise SystemExit(143)
        self.assertFalse(os.path.exists(self.out_path(job) + ".meta.json"), "no 'killed' evidence")
        self.assertEqual(batch.job_state(self.run_dir, job), "pending")

    def test_an_old_stopping_file_is_ignored(self):
        path = batch.stopping_path(self.run_dir, "x8o")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        textio.write_text_atomic(path, "1\n")
        old = time.time() - batch.STOPPING_MAX_AGE_S - 5
        os.utime(path, (old, old))
        self.assertFalse(batch.stopping(self.run_dir, "x8o"))

    def test_stop_workers_holds_the_file_while_it_signals(self):
        p = sleeper()
        self.addCleanup(stop_proc, p)
        ident = proc.process_identity(p.pid)
        if not ident:
            self.skipTest("no process identity on this platform")
        path = batch.marker_path(self.run_dir, "x8k")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        textio.write_json_atomic(path, {"pid": p.pid, "ident": ident, "started_at": textio.now_iso(),
                                        "heartbeat_at": textio.now_iso()})
        seen = []

        def kill_tree(pid, grace_s=None, proc=None):
            seen.append(os.path.exists(os.path.join(self.run_dir, ".ub", "jobs", "x8k.stopping")))
            stop_proc(p)
        with mock.patch.object(batch.proc, "kill_tree", side_effect=kill_tree):
            self.assertEqual(batch.stop_all(self.run_dir), 1)
        self.assertEqual(seen, [True])
        self.assertFalse(os.path.exists(os.path.join(self.run_dir, ".ub", "jobs", "x8k.stopping")))


# ---------------------------------------------------------------- X11

STRAY = ("=== FILE: review/resolution.md ===\n| finding | resolution | reason |\n|---|---|---|\n| L2-1 | FIXED | done |\n"
         "=== END FILE ===\n=== FILE: %s ===\nstray content\n=== END FILE ===\n"
         "=== STATUS ===\n{\"status\": \"complete\", \"assumptions\": [], \"open_questions\": [], \"reason\": \"\"}\n"
         "=== END STATUS ===\n")


class ExactFixerFilesTests(tl.EngineTestCase):
    def item(self, fanout, sid, mode="standard"):
        ctx = self.make_ctx(mode=mode, sim=dict(pipeline.DEFAULT_SIM), run_name="2026-09-26-f1-%s" % mode)
        return ctx, registry.FANOUTS[fanout](ctx, {"id": sid})[0]

    def test_arch_fix(self):
        ctx, it = self.item("arch_fix", "12.14")
        self.assertEqual(it["contract"]["allowed"], registry.ARCH_FIX_FILES)
        self.assertEqual(it["split"]["allowed"], registry.ARCH_FIX_FILES)
        self.assertIn("chosen/deferred.md", it["vars"]["ALLOWED_FILES"])
        ok, errors, _ = validate.check_contract(STRAY % "chosen/extra.md", it["contract"], ctx.run_dir)
        self.assertFalse(ok)
        ok, errors, _ = validate.check_contract(STRAY % "chosen/deferred.md", it["contract"], ctx.run_dir)
        self.assertTrue(ok, errors)

    def test_proposal_fix(self):
        ctx, it = self.item("proposal_fix", "13.6")
        sections = ["sections/%02d.md" % n for n in range(1, 14)]
        self.assertEqual(it["contract"]["allowed"], sections + ["ONE-PAGER.md", "review/resolution.md"])
        ok, errors, _ = validate.check_contract(STRAY % "sections/99.md", it["contract"], ctx.run_dir)
        self.assertFalse(ok)
        ok, errors, _ = validate.check_contract(STRAY % "sections/07.md", it["contract"], ctx.run_dir)
        self.assertFalse(ok)  # round 3: a printed section keeps its heading (writer_rules)
        self.assertIn("sections/07.md: heading '## 7. Scope and MVP' is missing", errors)
        good = STRAY.replace("stray content", "## 7. Scope and MVP\nThe revised scope.")
        ok, errors, _ = validate.check_contract(good % "sections/07.md", it["contract"], ctx.run_dir)
        self.assertTrue(ok, errors)
        _ctx, quick = self.item("proposal_fix", "13.6", mode="quick")
        self.assertEqual(quick["contract"]["allowed"], ["sections/%s.md" % s for s in registry.LITE_SECTIONS] +
                         ["ONE-PAGER.md", "review/resolution.md"])
        _ctx, deep = self.item("proposal_fix", "13.6", mode="deep")
        self.assertIn("PRFAQ.md", deep["contract"]["allowed"])


class QuotedProtocolTests(tl.EngineTestCase):
    """Round 3 (#40): a document that quotes the FILE protocol (a bare END FILE, then a FILE marker for a path the
    fixer may write) cut the first file short and passed the contract: the quoted block overwrote a sibling file with
    headless text, or replaced the first half of the same file with only a warning."""
    RES = "=== FILE: review/resolution.md ===\n| item | ADDRESSED | x |\n=== END FILE ===\n"
    ST = "=== STATUS ===\n{\"status\": \"complete\"}\n=== END STATUS ===\n"

    def item(self, fanout, sid):
        ctx = self.make_ctx(sim=dict(pipeline.DEFAULT_SIM), run_name="2026-09-27-f40-%s" % fanout)
        return ctx, registry.FANOUTS[fanout](ctx, {"id": sid})[0]

    def check(self, ctx, it, out):
        return validate.check_contract(out, it["contract"], ctx.run_dir)[:2]

    def test_proposal_fix_another_allowed_file(self):
        ctx, it = self.item("proposal_fix", "13.6")
        out = ("=== FILE: sections/02.md ===\n## 2. Problem and Evidence\nIntro.\nClose with:\n=== END FILE ===\n"
               "=== FILE: sections/03.md ===\nSecond half.\n=== END FILE ===\n" + self.RES + self.ST)
        ok, errors = self.check(ctx, it, out)
        self.assertFalse(ok)
        self.assertIn("sections/03.md: heading '## 3. Solution' is missing", errors)

    def test_proposal_fix_the_same_file_twice(self):
        ctx, it = self.item("proposal_fix", "13.6")
        head = "=== FILE: sections/02.md ===\n## 2. Problem and Evidence\n"
        out = (head + "Intro.\nClose with:\n=== END FILE ===\n" + head + "Second half.\n=== END FILE ===\n" +
               self.RES + self.ST)
        ok, errors = self.check(ctx, it, out)
        self.assertFalse(ok)
        self.assertTrue([e for e in errors if e.startswith("duplicate FILE block sections/02.md")], errors)

    def test_arch_fix_another_allowed_file_with_rules(self):
        ctx, it = self.item("arch_fix", "12.14")
        out = ("=== FILE: chosen/deferred.md ===\n# Deferred\nIntro.\nClose with:\n=== END FILE ===\n"
               "=== FILE: chosen/runtime.md ===\nSecond half.\n=== END FILE ===\n" + self.RES + self.ST)
        ok, errors = self.check(ctx, it, out)
        self.assertFalse(ok)
        self.assertIn("chosen/runtime.md: no mermaid sequenceDiagram block", errors)


# ---------------------------------------------------------------- X12

class SingleJudgeUpgradeTests(tl.EngineTestCase):
    def test_upgrade(self):
        state = {"host": {"family": "claude"}, "seats": {"host": "claude", "screen_judges": ["claude", "claude-alt"],
                                                          "tournament_judges": ["claude", "claude-alt"]}}
        self.assertEqual(migrate.upgrade(state, alt_distinct=True), [])
        self.assertEqual(state["seats"]["screen_judges"], ["claude", "claude-alt"])  # another model: two judges
        self.assertEqual(migrate.upgrade(state, alt_distinct=False), ["screen_judges", "tournament_judges"])
        self.assertEqual((state["seats"]["screen_judges"], state["seats"]["tournament_judges"]),
                         (["claude"], ["claude"]))
        two = {"seats": {"host": "claude", "screen_judges": ["claude", "gpt"], "tournament_judges": ["claude", "gpt"]}}
        self.assertEqual(migrate.upgrade(two, alt_distinct=False), [])

    def test_a_203_run_is_reseated_when_it_is_driven(self):
        ctx = self.make_ctx(families=("claude",))  # seated as 2.0.3 did: the host twice
        self.assertEqual(ctx.seats["screen_judges"], ["claude", "claude-alt"])
        st.save(ctx.run_dir, ctx.state)
        deps = tl.FakeDeps(cfg={"defaults": {"parallel": 4}, "families": {"claude": {"alt_model": None}}})
        seen = ub.with_run(ctx.run_dir, deps, lambda c, lock: dict(c.seats))
        self.assertEqual((seen["screen_judges"], seen["tournament_judges"]), (["claude"], ["claude"]))
        saved = textio.read_json(os.path.join(ctx.run_dir, "run.json"))
        self.assertEqual(saved["seats"]["screen_judges"], ["claude"])
        self.assertTrue(any("claude-alt runs the same model" in n for n in saved["notes"]))


if __name__ == "__main__":
    unittest.main()
