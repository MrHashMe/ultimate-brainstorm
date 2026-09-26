"""Stage 13 fix passes (KIT_SPEC 8.2): PROPOSAL-FIX sees ONE-PAGER.md, 13.6b runs one more fix pass when a lint FAIL
or a P11 one-pager drift is left after 13.6, and the G13 card lists what is still open.

Regression for the 2026-09-25 run: 13.6 moved the ask in section 1 (cash 0-6,600 USD plus people time, M0 'no earlier
than' a date) but could not reprint ONE-PAGER.md, whose text was not in its prompt, so the one-pager kept the old
'$100 cap'; and a P4 FAIL the fix introduced reached G13 as a bare 'Lint: proposal fail'."""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fixtures", "engine"))
import engine_testlib as tl  # noqa: E402

from ublib import textio  # noqa: E402
from ublib.engine import builders, gates, pipeline, registry  # noqa: E402
from ublib.engine import state as st  # noqa: E402

PROPOSAL = "# Proposal: shift swap board\n\nStatus: DRAFT\n\n## 1. Executive Summary\n\nThe ask is 0-6,600 USD.\n"
ONE_PAGER = ("# One-pager: shift swap board\nStatus: DRAFT | 2026-09-25 | Run: 2026-09-23-shift-swap-app-nurses\n\n"
             "## Problem\n\nNight swaps cost sleep.\n\n## The ask\n\nApprove Milestone 0 with a $100 cap.\n")
P4 = ("P4", "fail", "PROPOSAL.md", "section 1 has 592 words (max 300)")
P11 = ("P11", "warn", "ONE-PAGER.md", "section 1 states 0-6,600 USD; the one-pager does not")
P3 = ("P3", "warn", "PROPOSAL.md", "section 2: 1 sentence(s) with a number but no source")


def write_lint(ctx, *items):
    status = "fail" if any(i[1] == "fail" for i in items) else ("warn" if items else "pass")
    ctx.write_json("11_PROPOSAL/lint.json", {"status": status, "items": [
        {"id": r, "severity": s, "file": f, "message": m} for r, s, f, m in items]})


def step(sid):
    return pipeline.step_by_id(pipeline.load_steps(), sid)


def done_before(ctx, sid):
    """Every step before `sid` is done (a run that just finished the previous step)."""
    for s in pipeline.load_steps():
        if s["id"] == sid:
            return
        st.set_step(ctx.state, s["id"], "done")


class FixPromptTests(tl.EngineTestCase):
    def setUp(self):
        tl.EngineTestCase.setUp(self)
        self.ctx = self.make_ctx()
        self.ctx.write("11_PROPOSAL/PROPOSAL.md", PROPOSAL)
        self.ctx.write("11_PROPOSAL/ONE-PAGER.md", ONE_PAGER)

    def sections_all(self, template):
        return registry.PLACEHOLDERS["SECTIONS_ALL"](self.ctx, {"template": template})

    def test_fix_prompt_carries_the_one_pager_after_the_sections(self):
        text = self.sections_all("PROPOSAL-FIX")
        self.assertIn("The ask is 0-6,600 USD.", text)
        self.assertIn("--- FILE: ONE-PAGER.md ---\n# One-pager: shift swap board\n", text)
        self.assertIn("with a $100 cap", text)
        self.assertLess(text.index("## 1. Executive Summary"), text.index("--- FILE: ONE-PAGER.md ---"))
        self.assertNotIn("Run: 2026-09-23", text)  # the engine's status stamp is not content

    def test_reviewers_see_it_but_the_one_pager_writer_does_not(self):
        for tpl in ("PROPOSAL-RUBRIC", "PROPOSAL-REDTEAM"):
            self.assertIn("--- FILE: ONE-PAGER.md ---", self.sections_all(tpl), tpl)
        self.assertNotIn("ONE-PAGER", self.sections_all("EXEC-ONEPAGER"))
        os.remove(self.ctx.path("11_PROPOSAL", "ONE-PAGER.md"))
        self.assertEqual(self.sections_all("PROPOSAL-FIX"), PROPOSAL)

    def test_fix_jobs_write_the_one_pager_prompt_and_name_their_raw_output(self):
        job = builders.build_jobs(self.ctx, step("13.6"))[0]
        self.assertEqual(job["out"], "11_PROPOSAL/_raw/13.6-0.out.md")
        prompt = self.ctx.read(job["prompt_file"])
        self.assertIn("--- FILE: ONE-PAGER.md ---", prompt)
        self.assertIn("print ONE-PAGER.md in full too", prompt)
        self.assertIn("ONE-PAGER.md", job["contract"]["allowed"])
        self.assertIn("## The ask", job["contract"]["per_file"]["ONE-PAGER.md"]["headings"])
        self.ctx.state["counters"]["g13_loops"] = 1
        self.assertEqual(builders.build_jobs(self.ctx, step("13.6"))[0]["out"], "11_PROPOSAL/_raw/13.6-1.out.md")
        second = builders.build_jobs(self.ctx, step("13.6b"))[0]
        self.assertEqual(second["id"], "13.6b")
        self.assertEqual(second["out"], "11_PROPOSAL/_raw/13.6b-1.out.md")
        self.assertEqual(second["template"], "PROPOSAL-FIX")


class SecondPassTests(tl.EngineTestCase):
    def setUp(self):
        tl.EngineTestCase.setUp(self)
        self.ctx = self.make_ctx()
        done_before(self.ctx, "13.6b")

    def current(self):
        return pipeline.current_step(self.ctx, pipeline.load_steps())["id"]

    def test_runs_when_a_lint_fail_is_left(self):
        write_lint(self.ctx, P4, P3)
        self.assertEqual(self.current(), "13.6b")

    def test_runs_when_the_one_pager_drifted(self):
        write_lint(self.ctx, P11, P3)
        self.assertEqual(self.current(), "13.6b")

    def test_skipped_when_only_other_warnings_are_left(self):
        write_lint(self.ctx, P3)
        self.assertEqual(self.current(), "13.7")
        self.assertEqual(st.step_state(self.ctx.state, "13.6b"), "skipped")
        self.assertEqual(st.step_state(self.ctx.state, "13.4c"), "skipped")

    def test_skipped_when_13_6_did_not_run(self):
        st.set_step(self.ctx.state, "13.6", "skipped")  # quick mode without `changes`
        st.set_step(self.ctx.state, "13.4b", "skipped")
        write_lint(self.ctx, P4)
        self.assertEqual(self.current(), "13.7")

    def test_never_after_sign_off_started(self):
        # a run that reached G13 under an older kit (card shown, or approved) is not re-fixed behind the user's back
        for state in ("running", "done"):
            ctx = self.make_ctx(run_name="g13-%s" % state)
            done_before(ctx, "13.6b")
            for sid in ("13.7", "13.8") + (("13.9", "14.1", "14.2", "14.3", "14.4") if state == "done" else ()):
                st.set_step(ctx.state, sid, "done")
            st.set_step(ctx.state, "13.8", state)
            write_lint(ctx, P4)
            cur = pipeline.current_step(ctx, pipeline.load_steps())
            self.assertEqual(st.step_state(ctx.state, "13.6b"), "skipped", state)
            self.assertEqual(st.step_state(ctx.state, "13.4c"), "skipped", state)
            self.assertEqual(cur["id"] if cur else None, "13.8" if state == "running" else None, state)

    def test_redo_on_a_run_signed_off_under_the_older_kit_does_not_unlock_it(self):
        # run.json from 2.0.2 has no 13.6b entry; `redo 13.7` / `redo 13.8` reset G13 to pending
        sys.path.insert(0, tl.SCRIPTS)
        import ub
        for sid in ("13.7", "13.8"):
            ctx = self.make_ctx(run_name="redo-%s" % sid)
            steps = pipeline.load_steps()
            for s in steps:
                if s["id"] not in ("13.6b", "13.4c"):
                    st.set_step(ctx.state, s["id"], "done")
            write_lint(ctx, P4)
            self.assertEqual(ub.preview_from(ctx, sid)["calls"]["max"], 0, sid)  # the preview counts no fix call
            pipeline.supersede_from(ctx, steps, sid)
            self.assertEqual(pipeline.current_step(ctx, steps)["id"], sid, sid)
            self.assertEqual(st.step_state(ctx.state, "13.6b"), "skipped", sid)

    def test_assembles_again_after_the_second_pass(self):
        write_lint(self.ctx, P4)
        st.set_step(self.ctx.state, "13.6b", "done")
        self.assertEqual(self.current(), "13.4c")
        self.assertEqual(step("13.4c")["script"], "proposal_assemble")

    def test_g13_changes_reruns_both_fix_passes(self):
        for sid in ("13.6b", "13.4c", "13.7", "13.8"):
            st.set_step(self.ctx.state, sid, "done")
        write_lint(self.ctx, P4)
        effects = gates.apply(self.ctx, "G13", gates.merge_answer("G13", {"reply": "changes: fix the lint items"},
                                                                    self.ctx))
        pipeline.apply_effects(self.ctx, pipeline.load_steps(), effects)
        for sid in ("13.6", "13.4b", "13.6b", "13.4c", "13.7", "13.8"):
            self.assertEqual(st.step_state(self.ctx.state, sid), "pending", sid)
        self.assertEqual(self.ctx.state["user_changes"], "fix the lint items")
        st.set_step(self.ctx.state, "13.6", "done")
        st.set_step(self.ctx.state, "13.4b", "done")
        self.assertEqual(self.current(), "13.6b")  # the change round gets its second pass too

    def test_plan_counts_the_second_pass_as_optional(self):
        ctx = self.make_ctx(run_name="plan")
        seq = dict((i["id"], i) for i in pipeline.simulate(ctx))
        self.assertEqual(seq["13.6"]["count"], (1, 1))
        self.assertEqual(seq["13.6b"]["count"], (0, 1))
        seq = [i["id"] for i in pipeline.simulate(ctx, facts={"proposal_lint_open": False})]
        self.assertNotIn("13.6b", seq)


class G13CardTests(tl.EngineTestCase):
    def setUp(self):
        tl.EngineTestCase.setUp(self)
        self.ctx = self.make_ctx()

    def test_lists_open_items_and_offers_a_fix_pass(self):
        write_lint(self.ctx, P4, P11, P3)
        text = gates.display(self.ctx, "G13")
        self.assertIn("Lint: proposal fail", text)
        self.assertIn("Lint P4 FAIL, PROPOSAL.md: section 1 has 592 words (max 300)", text)
        self.assertIn("Lint P11 WARN, ONE-PAGER.md: section 1 states 0-6,600 USD; the one-pager does not", text)
        self.assertNotIn("Lint P3", text)  # other warnings stay in lint.md
        self.assertIn("reply `changes: fix the lint items` (a fix round of up to 2 calls; 2 of 2 change rounds left)",
                      text)
        self.assertEqual(gates.parse_reply("G13", "changes: fix the lint items")["action"], "changes")

    def test_no_offer_once_the_change_rounds_are_used(self):
        write_lint(self.ctx, P4)
        self.ctx.state["counters"]["g13_loops"] = 2
        text = gates.display(self.ctx, "G13")
        self.assertIn("Lint P4 FAIL", text)
        self.assertIn("No change rounds are left: `approve` signs off with these items open.", text)
        self.assertNotIn("changes: fix the lint items", text)

    def test_clean_lint_adds_nothing(self):
        write_lint(self.ctx, P3)
        text = gates.display(self.ctx, "G13")
        self.assertNotIn("Lint P", text)
        self.assertNotIn("fix the lint items", text)

    def test_long_lists_are_cut(self):
        write_lint(self.ctx, *[("P7", "fail", "PROPOSAL.md", "open question %d lacks 'Owner:'" % n)
                               for n in range(10)])
        lines = gates.g13_lint_lines(self.ctx)
        self.assertEqual(len([ln for ln in lines if ln.startswith("Lint P7")]), gates.G13_LINT_SHOWN)
        self.assertIn("... and 2 more in 11_PROPOSAL/lint.md", lines)


FIX_13_6 = """=== FILE: sections/01.md ===
## 1. Executive Summary

Night-shift nurses lose sleep arranging swaps. Approve Milestone 0 only, at [ESTIMATE: 9,000-27,000 USD in total;
basis: a host and people time]. Nothing else starts before the verdict. We are not building payroll.
=== END FILE ===
=== FILE: review/resolution.md ===
# Resolution

| item | status | where or reason |
|---|---|---|
| the ask leaves out people time | ADDRESSED | section 1 |
=== END FILE ===
=== STATUS ===
{"status": "complete", "assumptions": [], "open_questions": [], "reason": ""}
=== END STATUS ===
"""


def fix_13_6b(job):
    one = textio.read_text(os.path.join(job["run"], "11_PROPOSAL", "ONE-PAGER.md"))
    one = one.replace("## The ask\n", "## The ask\n\nMilestone 0 costs [ESTIMATE: 9,000-27,000 USD; basis: section "
                                      "1].\n", 1)
    return ("=== FILE: ONE-PAGER.md ===\n%s=== END FILE ===\n=== FILE: review/resolution.md ===\n# Resolution\n\n"
            "| item | status | where or reason |\n|---|---|---|\n| P11 | ADDRESSED | ONE-PAGER.md, The ask |\n"
            "=== END FILE ===\n=== STATUS ===\n{\"status\": \"complete\", \"assumptions\": [], \"open_questions\": [], "
            "\"reason\": \"\"}\n=== END STATUS ===\n" % one)


@unittest.skipUnless(tl.stubs_available(), "B4 stubs or B2 bs.py missing")
class EndToEndTests(tl.EngineTestCase):
    """A guided standard run on the stubs whose 13.6 moves the ask in section 1 but leaves ONE-PAGER.md alone."""

    def drive(self, sync_one_pager):
        from ublib import stubs
        real = stubs.respond

        def respond(job, prompt):
            if job["id"] == "13.6":
                return FIX_13_6
            if job["id"] == "13.6b" and sync_one_pager:
                return fix_13_6b(job)
            return real(job, prompt)
        ctx = self.make_ctx(mode="standard", autopilot="guided", deps=tl.stub_deps())
        st.set_step(ctx.state, "0.1", "done")
        seen = {}

        def g13(card):
            seen["show"] = card["show"]
            return {"reply": "approve"}
        with mock.patch.object(stubs, "respond", side_effect=respond):
            card = tl.drive(ctx, answers={"G2": {"reply": "defaults"}, "G13": g13, "G14": {"reply": "no"}})
        self.assertEqual(card["type"], "DONE", card.get("say"))
        self.assertEqual(st.step_state(ctx.state, "13.6b"), "done")
        self.assertEqual(st.step_state(ctx.state, "13.4c"), "done")
        self.assertIn("--- FILE: ONE-PAGER.md ---", ctx.read("prompts/13.6.prompt.md"))
        self.assertIn("| P11 | WARN | ONE-PAGER.md | section 1 states 9,000-27,000 USD", ctx.read(
            "prompts/13.6b.prompt.md"))
        self.assertTrue(ctx.exists("11_PROPOSAL/_raw/13.6b-0.out.md"))
        return ctx, seen["show"]

    def test_second_pass_brings_the_one_pager_in_line(self):
        ctx, show = self.drive(sync_one_pager=True)
        one = ctx.read("11_PROPOSAL/ONE-PAGER.md")
        self.assertIn("9,000-27,000 USD", one)
        self.assertEqual(len([ln for ln in one.split("\n") if ln.startswith("Status: ")]), 1)
        self.assertNotIn("P11", [i["id"] for i in ctx.read_json("11_PROPOSAL/lint.json")["items"]])
        self.assertNotIn("Lint P11", show)

    def test_drift_left_after_both_passes_is_on_the_g13_card(self):
        ctx, show = self.drive(sync_one_pager=False)
        self.assertIn("Lint P11 WARN, ONE-PAGER.md: section 1 states 9,000-27,000 USD; the one-pager does not", show)
        self.assertIn("reply `changes: fix the lint items`", show)


if __name__ == "__main__":
    unittest.main()
