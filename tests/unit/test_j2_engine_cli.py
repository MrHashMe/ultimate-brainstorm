"""Phase J2 (J2A-engine-cli), the Phase J requests on ub.py and the engine's render, handoff and dispatch code
(KIT_SPEC 4.4, 4.12, 6.3, 6.10, 8.2, 9).

- `switch --idea` refuses an idea its own probe killed (K6) and names the finalists left to switch to
- with the chosen idea killed by its probe and no runner-up left, the status banner reads KILLED (K6), and
  12_HANDOFF.md and the handoff seed no longer say the choice is settled
- the architecture README of a matrix with every candidate EXCLUDED names no leader (not 'None (close-call)') and
  gives the rule that took the default candidate
- the 'another session' card and the `ub stop` card name a kit 2.0.x `ub run` waiting at a gate with its remedy, and
  a gone holder's record another program holds open with that reason
- a git worktree or submodule (its .git is a file) is a repository for the variant guess and the shim check
- a BLOCKED card of a refused judge prompt carries the refusal's own fix (the step that prepares the prompt again)
- a DISPATCH step whose fanout yields one job id twice is refused before any job file is written
"""

import contextlib
import io
import json
import os
import subprocess
import sys
import time
import unittest
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fixtures", "engine"))
import engine_testlib as tl  # noqa: E402

import bs  # noqa: E402
import stubs  # noqa: E402  (tests/harness, put on sys.path by engine_testlib)
from ublib import proc, textio  # noqa: E402
from ublib.engine import EngineError, builders, gates, handoff, pipeline, registry, render, render_arch  # noqa: E402
from ublib.engine import privacy as pv  # noqa: E402
from ublib.engine import state as st  # noqa: E402

sys.path.insert(0, tl.SCRIPTS)
import ub  # noqa: E402

IDEAS = "".join("I-%03d | Idea %d | pitch %d | mech %d\n" % (i, i, i, i) for i in range(1, 6))
K6 = "Killed: %s - K6 (the pre-registered probe missed)"
# holds lock.json open the way any program that opens it with Python's open() does (no FILE_SHARE_DELETE on Windows,
# so the file can be neither replaced nor moved) until the release barrier appears
HOLD_OPEN = ("import os, sys, time\nf = open(sys.argv[1], 'rb')\nopen(sys.argv[2], 'w').close()\n"
             "while not os.path.exists(sys.argv[3]): time.sleep(0.02)\nf.close()\n")


class Base(tl.EngineTestCase):
    def run_ub(self, *args, **kw):
        out = io.StringIO()
        with mock.patch.object(sys, "stdout", out):
            rc = ub.main([str(a) for a in args], deps=kw.get("deps") or tl.FakeDeps(detect=tl.fake_detect()))
        text = out.getvalue()
        return rc, (json.loads(text) if text.strip().startswith("{") else text)

    def saved(self, ctx):
        st.save(ctx.run_dir, ctx.state)
        return ctx

    def reload(self, ctx):
        return st.Ctx(ctx.run_dir, st.load(ctx.run_dir), ctx.deps)

    def live_process(self):
        p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
        self.addCleanup(lambda: (p.kill(), p.wait()))
        return p


# ------------------------------------------------------------------------------------------------ K6 and switch

class K6Base(Base):
    def decided(self, chosen="I-002", killed=("I-001",), **kw):
        ctx = self.make_ctx(run_name="2026-09-27-j2-k6", **kw)
        ctx.write("screen/ideas.md", IDEAS)
        ctx.state["finalists"] = ["I-001", "I-002", "I-003", "I-004"]
        ctx.state["choice"].update({"idea": chosen, "runner_up": None})
        ctx.state["decision_log"] = [K6 % i for i in killed]
        ctx.write("09_PROBE.md", "# Probe\n\n## 3. The probe\nAsk 10 nurses to swap a shift.\nRESULT: PENDING\n")
        ctx.write("08_DECISION.md", "# DECISION\n")
        return ctx

    def dead(self, **kw):
        """The chosen idea's probe missed and no runner-up was left (gates.probe_result): I-001 is dead."""
        ctx = self.decided(chosen="I-001", killed=("I-001",), **kw)
        ctx.state["probe"] = {"idea": "I-001", "result": "MISSED", "at": "2026-09-27T10:00:00Z"}
        ctx.write("09_PROBE.md", "# Probe\n\n## Result\n1 of 10 swapped\nRESULT: MISSED (K6)\n")
        return ctx


class SwitchToAKilledIdea(K6Base):
    def switch(self, ctx, idea):
        return ub.switch_target(ctx, pipeline.load_steps(), SimpleNamespace(arch=None, idea=idea))

    def test_an_idea_its_probe_killed_is_refused(self):
        # JA request: the DONE card lists only the finalists left, but `switch --idea` took a K6-killed idea back
        ctx = self.decided()
        with self.assertRaises(EngineError) as cm:
            self.switch(ctx, "I-001")
        self.assertEqual(str(cm.exception), "I-001 was killed by its probe (K6); choose another finalist (I-003, "
                                            "I-004)")
        self.assertEqual(self.switch(ctx, "I-003"), pipeline.step_ref("probe_from", ctx))
        # a K4 kill is not offered either, and with no finalist left the card says so
        ctx.state["killed"] = ["I-004"]
        ctx.state["decision_log"].append(K6 % "I-003")
        with self.assertRaises(EngineError) as cm:
            self.switch(ctx, "I-003")
        self.assertEqual(str(cm.exception), "I-003 was killed by its probe (K6), and no other finalist is left to "
                                            "test; start a new run with a reframed topic")

    def test_the_command_is_refused_before_anything_changes(self):
        ctx = self.saved(self.dead())
        before = textio.read_bytes(os.path.join(ctx.run_dir, "run.json"))
        for extra in ([], ["--yes"]):
            rc, card = self.run_ub("switch", ctx.run_dir, "--idea", "I-001", *(extra + ["--json"]))
            self.assertEqual((rc, card["type"]), (0, "BLOCKED"), card)
            self.assertEqual(card["say"], "I-001 was killed by its probe (K6); choose another finalist (I-002, I-003, "
                                          "I-004)")
        self.assertEqual(textio.read_bytes(os.path.join(ctx.run_dir, "run.json")), before)


class KilledStatus(K6Base):
    def test_the_banner_says_killed(self):
        # JA request: a signed-off run whose chosen idea its probe killed still read APPROVED - PENDING MILESTONE 0
        for autopilot, signed in (("guided", True), ("guided", False), ("full-auto", False)):
            ctx = self.dead(autopilot=autopilot)
            ctx.state["signed_off"] = signed
            self.assertEqual(render.status_banner(ctx), "KILLED (K6): the chosen idea's pre-registered probe missed; "
                                                        "no runner-up is left", autopilot)

    def test_only_the_chosen_ideas_own_missed_probe_kills_it(self):
        ctx = self.decided(chosen="I-002", killed=("I-001",))  # the runner-up took over after I-001's probe missed
        ctx.state["probe"] = {"idea": "I-001", "result": "MISSED"}
        ctx.state["signed_off"] = True
        self.assertTrue(render.status_banner(ctx).startswith("APPROVED"))
        ctx = self.dead()
        ctx.state["probe"]["result"] = "PASSED"  # a later result for the same idea replaced the MISSED
        self.assertEqual(render.status_banner(ctx), "DRAFT")
        self.assertFalse(render.k6_dead(dict(ctx.state, choice={})))

    def test_the_handoff_no_longer_settles_the_choice(self):
        ctx = self.decided()
        handoff.handoff_final(ctx, {"id": "14.4"})
        self.assertIn(handoff.CLOSING, ctx.read("12_HANDOFF.md"))
        self.assertTrue(handoff.seed_text(ctx, "ce").endswith(handoff.CLOSING + "\n"))
        ctx = self.dead()
        ctx.state["handoff"] = "ce"
        handoff.handoff_final(ctx, {"id": "14.4"})
        text = ctx.read("12_HANDOFF.md")
        self.assertNotIn(handoff.CLOSING, text)
        self.assertIn("- Proposal: 11_PROPOSAL/PROPOSAL.md (%s)" % render.KILLED_BANNER, text)
        self.assertIn("- Milestone 0: MISSED (K6) (2026-09-27)", text)
        warning = ("WARNING: the pre-registered probe missed (K6) and no runner-up is left: do not build this idea; "
                   "switch to another finalist first.")
        self.assertTrue(text.endswith("\n%s\n" % warning), text)
        for kind in handoff.SEEDS:
            seed = handoff.seed_text(ctx, kind)
            self.assertNotIn(handoff.CLOSING, seed, kind)
            self.assertIn(warning, seed, kind)
            self.assertNotIn("riskiest assumption untested", seed, kind)


@unittest.skipUnless(tl.stubs_available(), "B4 stubs or B2 bs.py missing")
class KilledStatusFlow(Base):
    def test_a_second_missed_after_the_run_marks_the_documents(self):
        ctx = tl.full_auto_ctx(self, mode="quick", run_name="2026-09-27-j2-flow")
        self.assertEqual(tl.drive(ctx)["type"], "DONE")
        self.assertIn(handoff.CLOSING, self.reload(ctx).read("12_HANDOFF.md"))
        for _ in range(2):  # the first MISSED chooses the runner-up; the second leaves none
            rc, card = self.run_ub("probe-result", ctx.run_dir, "MISSED", "--json", deps=ctx.deps)
            self.assertEqual(rc, 0, card)
            ctx = self.reload(ctx)
            self.assertEqual(tl.drive(ctx)["type"], "DONE")
        ctx = self.reload(ctx)
        banner = "KILLED (K6): the chosen idea's pre-registered probe missed; no runner-up is left"
        self.assertIn("Status: %s" % banner, ctx.read("11_PROPOSAL/PROPOSAL.md"))
        self.assertIn("Status: %s | " % banner, ctx.read("11_PROPOSAL/ONE-PAGER.md"))
        self.assertIn(banner.replace("'", "&#x27;"), ctx.read("11_PROPOSAL/index.html"))
        text = ctx.read("12_HANDOFF.md")
        self.assertIn(banner, text)
        self.assertNotIn(handoff.CLOSING, text)
        self.assertTrue(text.endswith(handoff.K6_WARNING + "\n"), text)


# ------------------------------------------------------------------------------------------------ every arch EXCLUDED

class ReadmeWithEveryCandidateExcluded(Base):
    QGS = [{"id": "QG1", "name": "Reliability", "weight": 30}, {"id": "QG2", "name": "Privacy", "weight": 25},
           {"id": "QG3", "name": "Latency", "weight": 15}]
    CRITERIA = ["QG1", "QG2", "QG3", "time_to_mvp", "team_fit", "run_cost", "reversibility", "operational_simplicity"]

    def cand(self, label, score):
        return {"label": label, "veto": True, "veto_reason": "violates HC-%s" % label, "sensitivity_points": [],
                "tradeoff_points": [], "scores": [{"criterion": c, "score": score, "reason": "r"}
                                                  for c in self.CRITERIA]}

    def excluded(self):
        ctx = self.make_ctx(families=("claude", "gpt", "kimi"), autopilot="full-auto", run_name="2026-09-27-j2-arch")
        st.save(ctx.run_dir, ctx.state)
        ctx.write_json("10_ARCHITECTURE/drivers.json", {"product_goal": "x", "quality_goals": self.QGS})
        ctx.write_json("10_ARCHITECTURE/candidates/map.json", dict(
            (k, {"family": f, "archetype": k, "job": "12.4-" + k}) for k, f in (("A", "claude"), ("B", "gpt"),
                                                                                 ("C", "kimi"))))
        for fam in ("claude", "gpt", "kimi"):
            ctx.write_json("10_ARCHITECTURE/review/judge_%s.out.json" % fam, {
                "candidates": [self.cand("A", 3), self.cand("B", 4), self.cand("C", 2)], "steal": []})
        with contextlib.redirect_stdout(io.StringIO()):
            bs.arch_matrix(ctx.run_dir)
        self.assertIsNone(ctx.read_json("10_ARCHITECTURE/matrix.json")["leader"])
        return ctx

    def test_no_leader_and_the_rule_are_named(self):
        # JA request: the README read 'leader None (close-call)' and 'Decided by rule (AUTO-DECISION).' with no rule
        ctx = self.excluded()
        gates.apply(ctx, "G11", {"accept_recommendation": True}, by="auto")
        render_arch.write_readme(ctx)
        text = ctx.read("10_ARCHITECTURE/README.md")
        self.assertIn("; leader none (every candidate EXCLUDED).", text)
        self.assertNotIn("None", text)
        self.assertIn("Decided by rule (AUTO-DECISION): every candidate is EXCLUDED by vetoes (A: violates HC-A; B: "
                      "violates HC-B; C: violates HC-C): no leader; B has the best weighted score.", text)
        # the proposal writers' evidence pack says the same
        render.proposal_packs(ctx, {"id": "13.1"})
        self.assertIn("\nleader none (every candidate EXCLUDED)\n", ctx.read("11_PROPOSAL/_packs/PACK_B.md"))

    def test_a_leader_and_a_human_decision_read_as_before(self):
        self.assertEqual(render_arch.leader_text({"leader": "A", "leader_status": "clear"}), "A (clear)")
        ctx = self.excluded()
        gates.apply(ctx, "G11", {"choice": "C", "reply": "C, it is  the simplest"}, by="human")
        render_arch.write_readme(ctx)
        self.assertIn('Decided by the human: "C, it is the simplest".', ctx.read("10_ARCHITECTURE/README.md"))


# ------------------------------------------------------------------------------------------------ busy and stop cards

class LegacyHolderCards(Base):
    def run_dir(self):
        return self.saved(self.make_ctx(run_name="2026-09-27-j2-lock")).run_dir

    def legacy(self, run, age):
        """lock.json of a live kit 2.0.x driver whose last beat is `age` seconds old; its process started before that
        beat (the driver that wrote it still runs: a 2.0.x `ub run` waiting at a gate beats no more)."""
        p = self.live_process()
        beat = time.time() - age
        real = proc.process_start_time
        started = mock.patch.object(proc, "process_start_time", lambda pid: beat - 10 if pid == p.pid else real(pid))
        started.start()
        self.addCleanup(started.stop)
        textio.write_json_atomic(os.path.join(run, ".ub", "lock.json"),
                                 {"pid": p.pid, "host": "terminal", "heartbeat_at": "", "heartbeat_ts": beat})
        return p.pid

    def test_a_2_0_x_session_waiting_at_a_gate_is_named_with_its_remedy(self):
        # JC/JG request: the card said only 'another session is driving this run', so the agent's retries waited
        # with no hint that the user must answer (or close) the old terminal
        run = self.run_dir()
        pid = self.legacy(run, st.LEGACY_STALE_S + 400)
        before = textio.read_bytes(os.path.join(run, "run.json"))
        rc, card = self.run_ub("answer", run, "G0", "--default", "--json")
        self.assertEqual(card["type"], "AUTO", card)
        self.assertEqual(card["say"], "a kit 2.0.x session (pid %d, terminal) is waiting for an answer in its terminal"
                                      ": answer it there, or close it (Ctrl+C), to continue here; waiting" % pid)
        self.assertIn(" answer ", card["then"])
        self.assertEqual(textio.read_bytes(os.path.join(run, "run.json")), before)
        rc, card = self.run_ub("stop", run, "--json")
        self.assertIn(" A kit 2.0.x session (pid %d, terminal) is waiting for an answer in its terminal; it does not "
                      "see the stop, so close it there (Ctrl+C)." % pid, card["say"])
        self.assertNotIn("stop that session too", card["say"])

    def test_a_2_0_x_session_that_beats_is_driving(self):
        run = self.run_dir()
        pid = self.legacy(run, 5)
        rc, card = self.run_ub("answer", run, "G0", "--default", "--json")
        self.assertEqual(card["say"], "another session is driving this run (pid %d, terminal); waiting" % pid)
        rc, card = self.run_ub("stop", run, "--json")
        self.assertIn(" A session of an older kit (2.0.3) is driving this run (pid %d, terminal); it does not see the "
                      "stop, so stop that session too." % pid, card["say"])

    def test_a_record_held_open_is_named_with_that_reason(self):
        # JC request: the claim's reason was dropped (busy_card read lock.json again), and `ub stop` called such a
        # record a session of an older kit that must be stopped too
        run = self.run_dir()
        held = {"pid": 999999, "host": "codex; another program holds .ub/lock.json open"}
        with mock.patch.object(st.DriverLock, "claim", return_value=held):
            card = ub.with_run(run, tl.FakeDeps(), lambda ctx, lock: self.fail("drove the run"), host="claude-code")
            self.assertEqual(card["say"], "another session is driving this run (pid 999999, codex; another program "
                                          "holds .ub/lock.json open); waiting")
            rc, card = self.run_ub("stop", run, "--json")
        self.assertIn(" Another program holds .ub/lock.json open, so the stop is not recorded in run.json yet: close "
                      "that program, then run stop again.", card["say"])
        self.assertNotIn("older kit", card["say"])
        self.assertNotEqual(st.load(run).get("status"), "stopped")


@unittest.skipUnless(os.name == "nt", "a file open in another program blocks a replace only on Windows")
class HeldOpenForReal(Base):
    def test_the_cards_name_the_program_that_holds_lock_json(self):
        run = self.saved(self.make_ctx(run_name="2026-09-27-j2-held")).run_dir
        info = os.path.join(run, ".ub", "lock.json")
        textio.write_json_atomic(info, {"pid": 999999, "host": "codex", "heartbeat_at": "",
                                        "heartbeat_ts": time.time() - 500})
        opened, release = os.path.join(self.tmp, "opened"), os.path.join(self.tmp, "release")
        h = subprocess.Popen([sys.executable, "-c", HOLD_OPEN, info, opened, release])
        self.addCleanup(lambda: (open(release, "w").close(), h.wait()))
        end = time.monotonic() + 60
        while not os.path.exists(opened) and h.poll() is None and time.monotonic() < end:
            time.sleep(0.02)
        card = ub.with_run(run, tl.FakeDeps(), lambda ctx, lock: self.fail("drove the run"), host="claude-code")
        self.assertIn("(pid 999999, codex; another program holds .ub/lock.json open); waiting", card["say"])
        rc, card = self.run_ub("stop", run, "--json")
        self.assertIn("Another program holds .ub/lock.json open", card["say"])
        self.assertNotIn("older kit", card["say"])


# ------------------------------------------------------------------------------------------------ worktrees

class WorktreeRepository(Base):
    def worktree(self, name):
        project = os.path.join(self.tmp, name)
        os.makedirs(os.path.join(project, "src"))
        textio.write_text_atomic(os.path.join(project, ".git"), "gitdir: C:/code/main/.git/worktrees/%s\n" % name)
        textio.write_text_atomic(os.path.join(project, "src", "app.py"), "print('x')\n")
        return project

    def test_a_worktree_is_a_source_repository(self):
        # JE request: a project whose .git is a file (a git worktree or submodule) was never a software run
        project = self.worktree("wt")
        self.assertTrue(ub.is_source_repo(project))
        self.assertEqual(ub.infer_variant("refactor the billing api", cwd=project), "software")
        textio.write_text_atomic(os.path.join(project, ".git"), "not a git file\n")
        self.assertFalse(ub.is_source_repo(project))

    def test_a_worktrees_shims_are_checked_against_its_path(self):
        # JE request: the host vendor's .cmd shim was not checked against a worktree's path, which its jobs now read
        ctx = self.make_ctx(variant="software")
        project = self.worktree("R&D")
        fams = {"gpt": {"status": "ok", "backend": "codex-cli", "chain": ["codex-cli"], "web": True, "reason": ""},
                "claude": {"status": "ok", "backend": "claude-cli", "chain": ["claude-cli"], "web": True, "reason": ""}}
        with mock.patch.object(proc, "resolve_exe", side_effect=lambda name, env=None: "C:/bin/%s.cmd" % name):
            ub.shim_problems(ctx, fams, project)
        self.assertEqual(fams["gpt"]["status"], "ok", fams["gpt"]["reason"])
        self.assertEqual((fams["claude"]["status"], fams["claude"]["backend"]), ("ok", "host"))
        self.assertIn("the repository", fams["claude"]["reason"])


# ------------------------------------------------------------------------------------------------ policy block fix

class PolicyBlockFix(Base):
    STEP = [{"id": "0.1", "stage": 0, "title": "No-op", "type": "SCRIPT", "script": "noop"}]

    def blocked(self, fix):
        ctx = self.make_ctx(run_name="2026-09-27-j2-policy-%d" % bool(fix))
        err = pv.PolicyBlock("origin_label_check", "refused", "6.2-claude", fix=fix)
        with mock.patch.object(pipeline, "step_once", side_effect=err):
            return ctx, pipeline.advance(ctx, self.STEP, 0)

    def test_the_refusals_own_fix_is_the_cards(self):
        # JE request: the card offered 'fix the named input file, then: next', which never prepares the prompt again
        ctx, card = self.blocked(["remove the text from the file named above, then: ub redo \"x\" 6.1 --yes"])
        self.assertEqual((card["type"], card["fix"]), ("BLOCKED", ["remove the text from the file named above, then: "
                                                                   "ub redo \"x\" 6.1 --yes"]))
        ctx, card = self.blocked(None)
        self.assertEqual(card["fix"], ["fix the named input file, then: %s" % cards_next(ctx)])

    @unittest.skipUnless(tl.stubs_available(), "B4 stubs or B2 bs.py missing")
    def test_a_refused_quick_screen_offers_the_curation_redo(self):
        orig = stubs._quick_curated

        def curated(ctx):
            out = orig(ctx)
            out["ideas"][0]["pitch"] = "A shared swap board (Origin: gpt)."
            return out
        ctx = tl.full_auto_ctx(self, mode="quick", families=("claude", "gpt"), run_name="2026-09-27-j2-origin")
        with mock.patch.object(stubs, "_quick_curated", curated):
            card = tl.drive(ctx)
        self.assertEqual(card["type"], "BLOCKED", card.get("say"))
        self.assertEqual(card["fix"], ['remove the text from the file named above, then: %s redo "%s" Q.3p --yes'
                                       % (ctx.state["runner"], textio.to_posix(ctx.run_dir))])


def cards_next(ctx):
    from ublib.engine import cards
    return cards.next_cmd(ctx.state, ctx.run_dir)


# ------------------------------------------------------------------------------------------------ duplicate job ids

class DuplicateJobIds(Base):
    def test_a_fanout_that_lists_an_item_twice_is_refused(self):
        # JD request (defense in depth): the second item silently overwrote the first one's jobs/<id>.json
        ctx = self.make_ctx(run_name="2026-09-27-j2-dup")
        step = {"id": "7.1", "stage": 7, "title": "Check", "type": "DISPATCH", "fanout": "j2_twice",
                "job": {"kind": "checker", "template": "CHECK"}}
        for items in ([{"id": "I-001", "out": "checks/a.md"}, {"id": "I-002", "out": "checks/b.md"},
                       {"id": "I-001", "out": "checks/c.md"}],
                      [{"id": "I 001", "out": "checks/a.md"}, {"id": "I-001", "out": "checks/b.md"}]):
            with mock.patch.dict(registry.FANOUTS, {"j2_twice": lambda ctx, step, items=items: items}):
                with self.assertRaises(EngineError) as cm:
                    builders.build_jobs(ctx, step)
            self.assertEqual(str(cm.exception), "step 7.1 builds job 7.1-I-001 more than once (its fanout listed the "
                                                "same item twice)")
            self.assertEqual(textio.glob_in(ctx.run_dir, "jobs", "*.json"), [])


if __name__ == "__main__":
    unittest.main()
