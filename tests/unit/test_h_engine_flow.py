"""Phase H, engine flow (KIT_SPEC 6.3, 6.10, 6.11, 6.13; audit findings #4, #18, #96 and the round-3 open items).

- a redo moves only the outputs of steps of this run: a step of another mode that names the same files (quick Q.3p and
  6.1, proposal P.1 and 5.2) owns none of them, so `redo Q.3s`, `redo Q.4` and `redo P.2` keep what the finished
  earlier step wrote
- a switch and a K6 kill are kept in run.json decision_log, which every rewrite of 08_DECISION.md renders (quick Q.8
  rewrites the file after its supersede); a redo at or before the decision drops the log
- a '[' in the run path is taken literally by every engine, bs.py and lint scan (textio.glob_in)
- a displaced session's late write after a takeover is BLOCKED; a HOST step blocked while its card was issued is
  accepted once fixed; a HOST task's files are durable before `done` is recorded
- the HOST task holder gets its task back with the --lease of its done_cmd (SKILL.md loop step 1)
- a redo that starts after the gap step keeps the gap-round counters
"""

import io
import json
import os
import re
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fixtures", "engine"))
import engine_testlib as tl  # noqa: E402

import bs  # noqa: E402
from ublib import lints, textio  # noqa: E402
from ublib.engine import builders, cards, pipeline, privacy, registry  # noqa: E402
from ublib.engine import state as st  # noqa: E402

sys.path.insert(0, tl.SCRIPTS)
import ub  # noqa: E402

sys.path.insert(0, os.path.join(tl.KIT, "tests", "harness"))
from answerer import ub_args  # noqa: E402

BRACKET = "client [2026]"


def host_step(sid):
    s = dict(pipeline.step_by_id(pipeline.load_steps(), sid))
    s.pop("when", None)
    return s


def lease_of(card):
    return card["task"]["done_cmd"].split("--lease ")[1].split()[0]


class Base(tl.EngineTestCase):
    def run_ub(self, deps, *args):
        out = io.StringIO()
        with mock.patch.object(sys, "stdout", out):
            rc = ub.main([str(a) for a in args], deps=deps)
        text = out.getvalue()
        return rc, (json.loads(text) if text.strip().startswith("{") else text)

    def reload(self, ctx, deps=None):
        return st.Ctx(ctx.run_dir, st.load(ctx.run_dir), deps or ctx.deps)

    def drive_done(self, ctx):
        """Drive a run whose status a command set active again to DONE (in-process, like a host)."""
        ctx = self.reload(ctx)
        card = tl.drive(ctx)
        self.assertEqual(card["type"], "DONE", (card.get("say"), card.get("error")))
        return self.reload(ctx)


# ------------------------------------------------------------------------------------------------ outputs of this run

@unittest.skipUnless(tl.stubs_available(), "B4 stubs or B2 bs.py missing")
class OtherModeOutputs(Base):
    SCREEN = ("screen/ideas.md", "screen/header.md", "screen/claude.prompt.md", "screen/gpt.prompt.md",
              "screen/screen.schema.json")

    def test_the_cards_redo_of_a_failed_quick_screen_finishes_the_run(self):
        """The BLOCKED card of a failed quick screen offers `redo <run> Q.3s --yes`. It used to move Q.3p's prompts
        too (6.1, a step of standard mode, names the same files), so every later poll was BLOCKED for good."""
        ctx = tl.full_auto_ctx(self, mode="quick", families=("claude", "gpt"))
        ctx.deps.batch.fail = lambda job: job["id"].startswith("Q.3s")
        card = tl.drive(ctx)
        self.assertEqual((card["type"], card["step"]), ("BLOCKED", "Q.3s"), card.get("say"))
        redo = [f for f in card["fix"] if " redo " in f]
        self.assertEqual(len(redo), 1, card["fix"])
        ctx.deps.batch.fail = set()  # the family works again
        rc, card = self.run_ub(ctx.deps, *(ub_args(redo[0]) + ["--json"]))
        for _ in range(40):
            if card["type"] != "AUTO":
                break
            rc, card = self.run_ub(ctx.deps, *ub_args(card["then"]))
        self.assertNotEqual(card["type"], "BLOCKED", (card.get("say"), card.get("fix")))
        ctx = self.drive_done(ctx) if card["type"] != "DONE" else self.reload(ctx)
        self.assertEqual(ctx.read_json("quick/finalists.json")["scoring"], "blind")
        for rel in self.SCREEN:
            self.assertTrue(ctx.exists(rel), rel)

    def test_a_quick_redo_after_the_pick_leaves_the_screen_in_place(self):
        ctx = tl.full_auto_ctx(self, mode="quick", families=("claude", "gpt"))
        self.assertEqual(tl.drive(ctx)["type"], "DONE")
        ctx.state["status"] = "active"
        moved = pipeline.supersede_from(ctx, pipeline.load_steps(), "Q.4")
        self.assertEqual([m for m in moved if m.startswith("screen/")], [])
        self.assertIn("quick/finalists.json", moved)  # Q.4's own outputs still move
        for rel in self.SCREEN:
            self.assertTrue(ctx.exists(rel), rel)
        self.assertEqual(st.step_state(ctx.state, "Q.3p"), "done")

    def test_a_proposal_redo_keeps_the_users_idea(self):
        """Proposal mode: P.1 writes the user's idea as I-001 (screen/ideas.md, primary.json ...), and 5.2 of the
        idea-finding modes names the same files; `redo P.2` used to move them while P.1 stayed done."""
        ctx = tl.full_auto_ctx(self, mode="proposal", families=("claude", "gpt"))
        ctx.state["idea_text"] = "a shared shift-swap board for night nurses"
        st.save(ctx.run_dir, ctx.state)
        self.assertEqual(tl.drive(ctx)["type"], "DONE")
        ctx.state["status"] = "active"
        moved = pipeline.supersede_from(ctx, pipeline.load_steps(), "P.2")
        for rel in ("screen/ideas.md", "primary.json", "origins.json", "clusters.json"):
            self.assertNotIn(rel, moved)
            self.assertTrue(ctx.exists(rel), rel)
        ctx = self.drive_done(ctx)
        self.assertNotIn("idea text not found", registry.idea_text(ctx, "I-001"))
        for name in os.listdir(ctx.path("prompts")):
            self.assertNotIn("(idea text not found)", textio.read_text(ctx.path("prompts", name)), name)

    def test_a_step_of_another_mode_owns_no_files(self):
        ctx = self.make_ctx(mode="quick", families=("claude", "gpt"))
        for rel in ("screen/ideas.md", "screen/header.md", "screen/claude.prompt.md", "origins.json"):
            ctx.write(rel, "x\n")
        steps = pipeline.load_steps()
        st.set_step(ctx.state, "Q.3p", "done")
        self.assertIn("screen/claude.prompt.md", pipeline.step_outputs(ctx, pipeline.step_by_id(steps, "Q.3p")))
        # 6.1 and 5.2 never run in quick mode: skipped on the way, or still pending
        st.set_step(ctx.state, "6.1", "skipped", note="not in this mode/preset")
        self.assertEqual(pipeline.step_outputs(ctx, pipeline.step_by_id(steps, "6.1")), [])
        self.assertEqual(st.step_state(ctx.state, "5.2"), "pending")
        self.assertEqual(pipeline.step_outputs(ctx, pipeline.step_by_id(steps, "5.2")), [])


# ------------------------------------------------------------------------------------------------ decision log

@unittest.skipUnless(tl.stubs_available(), "B4 stubs or B2 bs.py missing")
class QuickDecisionLog(Base):
    def done_quick_run(self):
        ctx = tl.full_auto_ctx(self, mode="quick", families=("claude", "gpt"))
        self.assertEqual(tl.drive(ctx)["type"], "DONE")
        return self.reload(ctx)

    def test_a_quick_switch_is_recorded_after_the_rerun(self):
        ctx = self.done_quick_run()
        old = ctx.state["choice"]["idea"]
        new = [i for i in ctx.state["finalists"] if i != old][0]
        rc, card = self.run_ub(ctx.deps, "switch", ctx.run_dir, "--idea", new, "--yes", "--json")
        self.assertEqual(rc, 0, card)
        ctx = self.drive_done(ctx)
        dec = ctx.read("08_DECISION.md")
        self.assertEqual(dec.count("Switched ("), 1, dec)
        self.assertIn("chosen idea %s -> %s" % (old, new), dec)
        self.assertIn("Chosen (to test): %s" % new, dec)

    def test_a_quick_k6_kill_is_recorded_after_the_rerun(self):
        ctx = self.done_quick_run()
        old = ctx.state["choice"]["idea"]
        self.assertTrue(ctx.state["choice"]["runner_up"])
        rc, card = self.run_ub(ctx.deps, "probe-result", ctx.run_dir, "MISSED", "--json")
        self.assertEqual(rc, 0, card)
        ctx = self.drive_done(ctx)
        dec = ctx.read("08_DECISION.md")
        self.assertEqual(dec.count("Killed: %s - K6" % old), 1, dec)
        # the killed idea is not listed as merely 'not chosen at the decision'
        not_doing = re.search(r"^Not doing[^\n]*$", dec, re.M).group(0)
        self.assertNotIn(old, not_doing)


class DecisionLog(Base):
    def decided(self):
        ctx = self.make_ctx()
        ctx.state["choice"].update({"idea": "I-001", "runner_up": "I-002"})
        ctx.state["finalists"] = ["I-001", "I-002", "I-003"]
        for sid in ("10.5", "10.6"):
            st.set_step(ctx.state, sid, "done")
        registry.write_decision(ctx)
        return ctx

    def test_a_standard_switch_is_recorded_once_and_kept_by_a_rewrite(self):
        ctx = self.decided()
        pipeline.switch_idea(ctx, pipeline.load_steps(), "I-003")
        self.assertEqual(len(ctx.state["decision_log"]), 1)
        self.assertTrue(ctx.state["decision_log"][0].startswith("Switched ("))
        self.assertEqual(st.load(ctx.run_dir)["decision_log"], ctx.state["decision_log"])  # saved with the supersede
        self.assertEqual(ctx.read("08_DECISION.md").count("Switched ("), 1)
        registry.write_decision(ctx)  # 10.6 again (a redo from it)
        self.assertEqual(ctx.read("08_DECISION.md").count("Switched ("), 1)

    def test_a_refused_supersede_logs_nothing(self):
        ctx = self.decided()
        with mock.patch.object(st, "check_supersede_paths", side_effect=pipeline.EngineError("too long")):
            with self.assertRaises(pipeline.EngineError):
                pipeline.switch_idea(ctx, pipeline.load_steps(), "I-003")
        self.assertFalse(ctx.state.get("decision_log"))

    def test_a_redo_at_or_before_the_decision_drops_the_log(self):
        steps = pipeline.load_steps()
        ctx = self.decided()
        ctx.state["decision_log"] = ["Killed: I-001 - K6 (the pre-registered probe missed)"]
        pipeline.supersede_from(ctx, steps, "11.1")
        self.assertEqual(len(ctx.state["decision_log"]), 1)
        pipeline.supersede_from(ctx, steps, "10.5")
        self.assertNotIn("decision_log", ctx.state)
        q = self.make_ctx(mode="quick", run_name="quick")
        q.state["decision_log"] = ["Switched (x): chosen idea Q-01 -> Q-02 (the user asked to switch)"]
        pipeline.supersede_from(q, steps, "Q.6")
        self.assertEqual(len(q.state["decision_log"]), 1)
        pipeline.supersede_from(q, steps, "Q.7")
        self.assertNotIn("decision_log", q.state)


# ------------------------------------------------------------------------------------------------ '[' in the path

class BracketPath(Base):
    def setUp(self):
        Base.setUp(self)
        self.project = os.path.join(self.tmp, BRACKET)
        os.makedirs(self.project)

    def test_the_glob_helper_takes_the_folder_literally(self):
        d = os.path.join(self.tmp, BRACKET, "x")
        os.makedirs(os.path.join(d, "sub"))
        for rel in ("a.md", "b.txt", "sub/c.md"):
            textio.write_text_atomic(os.path.join(d, *rel.split("/")), "x\n")
        self.assertEqual(sorted(os.path.basename(p) for p in textio.glob_in(d, "*.md")), ["a.md"])
        self.assertEqual(sorted(os.path.basename(p) for p in textio.glob_in(d, "**", "*.md", recursive=True)),
                         ["a.md", "c.md"])
        self.assertEqual([os.path.basename(p) for p in textio.glob_in(d, "sub", "c.md")], ["c.md"])
        self.assertTrue(all(os.path.exists(p) for p in textio.glob_in(d, "*")))

    def test_a_redo_moves_outputs_under_a_bracket_path(self):
        ctx = self.make_ctx(mode="deep", variant="software")
        self.assertIn(BRACKET, ctx.run_dir)
        for rel in ("pool/G1_gap.md", "pool/R1_reopen.md", "jobs/5.3-G1.json", "answers/CONTEXT-MERGE.json"):
            ctx.write(rel, "x\n")
        steps = pipeline.load_steps()
        st.set_step(ctx.state, "5.3", "done")
        st.set_step(ctx.state, "14.1", "done")
        self.assertEqual(sorted(st.expand_globs(ctx.run_dir, ["pool/G[0-9]*_gap.md*", "jobs/5.3-*.json"])),
                         ["jobs/5.3-G1.json", "pool/G1_gap.md"])
        moved = pipeline.supersede_from(ctx, steps, "5.3")
        for rel in ("pool/G1_gap.md", "pool/R1_reopen.md", "jobs/5.3-G1.json", "answers/CONTEXT-MERGE.json"):
            self.assertIn(rel, moved)
            self.assertFalse(ctx.exists(rel), rel)

    def test_the_curator_bundles_read_the_pool_under_a_bracket_path(self):
        ctx = self.make_ctx()
        ctx.write("00_HUMAN_SEEDS.md", "# Seeds\n## Ideas\n- a nurse-run shift swap board\n")
        ctx.write("pool/S2_x.md", "### S2-01 A shift swap idea\n- Pitch: p\n- Mechanism: m\n- Fails if: f\n")
        self.assertIn("S2-01 A shift swap idea", registry.pool_bundle(ctx))
        self.assertIn("a nurse-run shift swap board", registry.seeds_bundle(ctx))
        self.assertIn("S2-01", registry.pool_aliases(ctx)[0])

    def test_the_leak_checks_read_the_seeds_and_pool_under_a_bracket_path(self):
        # the seed-leak and pool-leak checks (6.7 rules 1 and 3) read no file under a '[' path and passed everything
        ctx = self.make_ctx()
        seed = "a nurse-run marketplace for shift swaps with instant approval"
        ctx.write("00_HUMAN_SEEDS.md", "# Seeds\n## Ideas\n- %s\n" % seed)
        ctx.write("pool/S2_x.md", "### S2-01 A shift swap marketplace for night nurses\n- Pitch: p\n- Mechanism: m\n")
        self.assertTrue(privacy.seed_lines(ctx.run_dir))
        self.assertTrue(privacy.pool_titles(ctx.run_dir))
        with self.assertRaises(privacy.PolicyBlock):
            privacy.check_seed_leak("prompt: %s" % seed, ctx.run_dir)

    def test_the_runs_under_a_bracket_path_are_listed(self):
        ctx = self.make_ctx()
        st.save(ctx.run_dir, ctx.state)
        self.assertEqual(st.list_runs(os.path.dirname(ctx.run_dir)), [ctx.run_dir])

    def test_bs_and_lint_scans_under_a_bracket_path(self):
        root = os.path.join(self.project, "brainstorm", "run")
        os.makedirs(root)
        textio.write_text_atomic(os.path.join(root, "00_HUMAN_SEEDS.md"), "## Ideas\n- a seed\n")
        self.assertTrue(bs.seeds_done(root)[0])
        textio.write_text_atomic(os.path.join(root, "pool", "x.md"), "x\n")
        self.assertTrue(bs.check_item(root, "pool/*")[0])
        arch = os.path.join(root, "10_ARCHITECTURE")
        textio.write_text_atomic(os.path.join(arch, "adr", "0001-use-sqlite.md"), "# ADR\n")
        textio.write_text_atomic(os.path.join(arch, "chosen", "containers.md"), "# C\n")
        self.assertEqual([os.path.basename(p) for p in lints._adr_files(arch)], ["0001-use-sqlite.md"])
        self.assertEqual(sorted(os.path.basename(p) for p in lints._arch_doc_files(arch)),
                         ["0001-use-sqlite.md", "containers.md"])
        self.assertEqual(sorted(os.path.basename(p) for p in bs._assumption_files(root)),
                         ["0001-use-sqlite.md", "containers.md"])


# ------------------------------------------------------------------------------------------------ HOST tasks

class HostTasks(Base):
    def test_a_late_write_after_a_takeover_blocks_the_displaced_session(self):
        """#96: session A's task was taken over by B and accepted; A then overwrote the frame and ran its done. A gets
        a BLOCKED card (show it, then stop), not an AUTO card whose note the loop never voices."""
        steps = [host_step("1.2")]
        a = self.make_ctx(mode="deep")
        token_a = lease_of(pipeline.advance(a, steps, 0))
        b = self.reload(a, tl.FakeDeps())
        b.takeover = True
        token_b = lease_of(pipeline.advance(b, steps, 0))
        b.write("00_HUMAN_SEEDS.md", "## Ideas\n- from session B\n")
        b = self.reload(b)
        b.lease = token_b
        pipeline.host_done(b, steps, "1.2")
        a = self.reload(a, tl.FakeDeps())
        # session A's host writes the file itself (an engine write through Ctx keeps an accepted file accepted)
        textio.write_text_atomic(a.path("00_HUMAN_SEEDS.md"), "## Ideas\n- from session A, after the takeover\n")
        a.lease = token_a
        card = pipeline.host_done(a, steps, "1.2")
        self.assertEqual(card["type"], "BLOCKED", card)
        self.assertIn("00_HUMAN_SEEDS.md changed after that", card["say"])
        self.assertTrue(any(' redo "' in f and f.endswith(" 1.2 --yes") for f in card["fix"]), card["fix"])
        self.assertEqual(st.step_state(st.load(a.run_dir), "1.2"), "done")

    def test_a_host_step_blocked_while_issued_is_accepted_once_fixed(self):
        """#18: an EngineError while the card is issued (a template the kit update fixes) marks the step blocked; the
        next card issues it, and its done is accepted (it used to be re-issued forever)."""
        steps = [host_step("1.2")]
        ctx = self.make_ctx(mode="deep")
        real = builders.host_argument
        calls = []

        def flaky(*a, **k):
            calls.append(1)
            if len(calls) == 1:
                raise pipeline.EngineError("template BMAD-SEEDS uses unknown placeholders: X",
                                           fix=["reinstall the kit"])
            return real(*a, **k)
        with mock.patch.object(builders, "host_argument", flaky):
            self.assertEqual(pipeline.advance(ctx, steps, 0)["type"], "BLOCKED")
            self.assertEqual(st.step_state(ctx.state, "1.2"), "blocked")
            ctx = self.reload(ctx)
            card = pipeline.advance(ctx, steps, 0)
        self.assertEqual(card["type"], "HOST")
        ctx = self.reload(ctx)
        ctx.write("00_HUMAN_SEEDS.md", "## Ideas\n- written by the host\n")
        ctx.lease = lease_of(card)
        card = pipeline.host_done(ctx, steps, "1.2")
        self.assertEqual(st.step_state(st.load(ctx.run_dir), "1.2"), "done", card)

    def test_an_identical_merge_after_a_redo_is_done(self):
        """#18 (c): a redo moves the merge answer, so the same decision written again is accepted, not skipped."""
        steps = [host_step("14.1")]
        ctx = self.make_ctx(mode="deep", variant="software")
        merge = '{"merge_terms": "all", "terms": ["OldTerm"]}\n'
        for _ in range(2):
            ctx.lease = lease_of(pipeline.advance(ctx, steps, 0))
            ctx.write("answers/CONTEXT-MERGE.json", merge)
            pipeline.host_done(ctx, steps, "14.1")
            self.assertEqual(st.step_state(ctx.state, "14.1"), "done")
            self.assertTrue(ctx.state.get("context_merge"))
            ctx = self.reload(ctx)
            moved = pipeline.supersede_from(ctx, steps, "14.1")
            self.assertEqual(moved, ["answers/CONTEXT-MERGE.json"])
            self.assertNotIn("context_merge", ctx.state)

    def test_host_outputs_are_durable_before_done_is_saved(self):
        """#4: the kit never wrote a HOST task's files, so nothing flushed them: they are fsynced before the run.json
        save that records the task done."""
        steps = [host_step("2.1g")]
        ctx = self.make_ctx()
        ctx.lease = lease_of(pipeline.advance(ctx, steps, 0))
        ctx.write("01_FRAME.md", "# Frame\n## HMW\nHow might night nurses swap shifts?\n")
        ctx.write("criteria.json", '{"Value": 50, "Feasibility": 50}\n')
        idents = {}
        for rel in ("01_FRAME.md", "criteria.json"):
            with open(ctx.path(rel), "rb") as f:
                idents[rel] = (os.fstat(f.fileno()).st_dev, os.fstat(f.fileno()).st_ino)
        events = []
        real_fsync, real_save = os.fsync, st.save

        def fsync(fd):
            s = os.fstat(fd)
            events.append(("fsync", (s.st_dev, s.st_ino)))
            return real_fsync(fd)

        def save(run_dir, state, *a, **k):
            events.append(("save", st.step_state(state, "2.1g")))
            return real_save(run_dir, state, *a, **k)
        with mock.patch.object(os, "fsync", fsync), mock.patch.object(st, "save", save):
            pipeline.host_done(ctx, steps, "2.1g")
        self.assertEqual(st.step_state(st.load(ctx.run_dir), "2.1g"), "done")
        first_done = events.index(("save", "done"))
        for rel, ident in idents.items():
            self.assertIn(("fsync", ident), events[:first_done], rel)

    def test_a_host_file_still_open_leaves_the_task_waiting_for_done(self):
        steps = [host_step("2.1g")]
        ctx = self.make_ctx()
        ctx.lease = lease_of(pipeline.advance(ctx, steps, 0))
        ctx.write("01_FRAME.md", "# Frame\n## HMW\nHow might night nurses swap shifts?\n")
        ctx.write("criteria.json", '{"Value": 50, "Feasibility": 50}\n')
        with mock.patch.object(pipeline, "_make_durable", side_effect=PermissionError(13, "in use")):
            card = pipeline.host_done(ctx, steps, "2.1g")
        self.assertEqual(card["type"], "HOST")
        self.assertIn("run done_cmd again", card["say"])
        self.assertEqual(st.step_state(st.load(ctx.run_dir), "2.1g"), "running")
        card = pipeline.host_done(self.reload(ctx), steps, "2.1g")  # closed now: the same done is accepted
        self.assertEqual(st.step_state(st.load(ctx.run_dir), "2.1g"), "done", card)

    def test_the_holder_gets_its_task_back_with_the_lease_of_its_done_cmd(self):
        """SKILL.md loop step 1: a holder that falls back to `next` (an interrupted done_cmd, a lost card) presents
        the --lease of task.done_cmd and gets its HOST card again, never 'in progress in another session'."""
        steps = [host_step("2.1g")]
        ctx = self.make_ctx()
        ctx.state["runner"] = cards.default_runner()  # what state.load gives the reloaded ctx below
        card = pipeline.advance(ctx, steps, 0)
        token = lease_of(card)
        again = self.reload(ctx, tl.FakeDeps())
        again.lease = token
        card2 = pipeline.advance(again, steps, 0)
        self.assertEqual(card2["type"], "HOST", card2.get("say"))
        self.assertEqual(card2["task"]["done_cmd"], card["task"]["done_cmd"])
        nolease = self.reload(ctx, tl.FakeDeps())
        card3 = pipeline.advance(nolease, steps, 0)
        self.assertIn("in progress in another session", card3["say"])
        self.assertIn("done_cmd", card3["say"])
        skill = textio.read_text(os.path.join(tl.SK, "SKILL.md"))
        step1 = re.search(r"^1\. Run the card's \"then\" command.*?(?=^2\. )", skill, re.M | re.S).group(0)
        self.assertIn('"task.done_cmd"', step1)


# ------------------------------------------------------------------------------------------------ gap counters

class GapCounters(Base):
    def two_rounds(self):
        ctx = self.make_ctx(mode="deep")
        for s in pipeline.load_steps():
            if s["id"] == "5.3":
                break
            st.set_step(ctx.state, s["id"], "done", note="setup")
        for sid in ("5.3", "5.3c", "5.3m"):
            st.set_step(ctx.state, sid, "done", note="setup")
        ctx.state["counters"].update({"gap_rounds": 2, "gap_prefix": 3, "reopen_prefix": 2})
        for rel in ("pool/G1_gap.md", "pool/G2_gap.md", "pool/G3_gap.md", "pool/R1_reopen.md", "pool/R2_reopen.md"):
            ctx.write(rel, "### %s-01 idea\n" % rel.split("/")[1][:2])
        return ctx

    def counters(self, ctx):
        return dict((k, ctx.state["counters"].get(k)) for k in ("gap_rounds", "gap_prefix", "reopen_prefix"))

    def test_a_redo_after_the_gap_step_keeps_the_gap_counters(self):
        """A redo from 5.3c (or 5.3m, 5.4 ...) keeps 5.3 and every round's ideas: the counters stay, so 5.3m never
        opens another round numbered over existing G/R files."""
        ctx = self.two_rounds()
        pipeline.supersede_from(ctx, pipeline.load_steps(), "5.3c")
        self.assertEqual(self.counters(ctx), {"gap_rounds": 2, "gap_prefix": 3, "reopen_prefix": 2})
        self.assertEqual(st.step_state(ctx.state, "5.3"), "done")
        self.assertTrue(ctx.exists("pool/G2_gap.md"))
        self.assertFalse(registry.eval_when(ctx, ["homogenized_or_gaps"]))  # deep allows 2 rounds: none more

    def test_a_redo_at_the_gap_step_starts_the_rounds_over(self):
        ctx = self.two_rounds()
        pipeline.supersede_from(ctx, pipeline.load_steps(), "5.3")
        self.assertEqual(self.counters(ctx), {"gap_rounds": 0, "gap_prefix": 0, "reopen_prefix": 0})
        self.assertFalse(ctx.exists("pool/G2_gap.md"))


if __name__ == "__main__":
    unittest.main()
