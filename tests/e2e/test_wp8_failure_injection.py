"""WP8: the deterministic failure-injection suite of the architecture audit (REPORT section 6), against the
implemented design (phase A/B). Every vector maps to a test; where an existing test already asserts the oracle it is
referenced here instead of duplicated. New tests are the classes in this file (marked NEW) and
tests/unit/test_wp8_guards.py. No test sleeps for a fixed time: they wait on barrier files, printed prompts, lock
state or process exit, with bounded timeouts, on Windows and POSIX.

Oracles adapted to the implemented design:
- the driver lock is the kernel lock .ub/jobs/_driver.lock, not a 120 s lease, so the terminal-takeover vector needs no
  125 s wait: the terminal lets go of the lock at the prompt (I3)
- calls.jsonl has one row per attempt that carries the backend requests it sent (C6), not one row per HTTP request;
  the rows of a job sum to the requests the server received
- the relaunch cap is 7 launches per job per prompt (1 + RELAUNCH_ROUNDS x RELAUNCH_LIMIT = 1 + 2 x 3; WP1b keeps one
  allowance for the documented `run --continue` recovery), not 4; the budget is counted in backend requests
- a stdout flood ends the job invalid / bad_output (exit 5, WPF1), with an 8 MB transport cap
- publish goes to docs/<run>/ (WP6)

Mapping: REPORT 6 vector -> oracle -> tests (NEW = in this file; unit/ and e2e/ are folders under tests/).

6.1 kickoff: the SKILL.md Start line with the text  pricing for $29/month; `touch PWNED`; $(whoami)  in Git Bash
    and PowerShell -> run.json raw_text equals the input bytes, no PWNED file exists, the slug contains 29
  NEW KickoffPoisonPill.test_the_start_line_keeps_the_text_out_of_every_shell
  NEW KickoffPoisonPill.test_an_empty_component_list_survives_every_shell
      (its PowerShell 5.1 part runs once the Start line survives a dropped empty argument: WP8 cross-package request)
  unit/test_wp1a_ownership.py::Cli.test_init_reads_the_kickoff_text_from_a_file
6.1 screen judge: every id, a duplicate I-008 with all scores 5, 'I-001' + U+200B, one score of 900
    -> the contract fails
  unit/test_wp3_contracts.py::ExactCover.test_poison_pill_screen_judge
  unit/test_wpf2_followups.py::JudgeIdsEndToEndTests.test_bad_ids_and_scores_fail_the_contract
    -> exactly one repair call, the shortlist is unchanged
  NEW ScreenJudgePoisonPill.test_one_repair_call_and_the_shortlist_is_unchanged
6.1 ARCH-FIX: decisions.json {"adrs":[{"title":"A","options":[{"name":"x"}]},],"risks":[]}
    -> the contract fails and adr/ is untouched
  NEW ArchFixPoisonPill.test_the_report_decisions_json_fails_and_adr_is_untouched
  unit/test_wp3_contracts.py::JsonFileBlocks.test_trailing_comma_decisions_json_earns_a_repair
  unit/test_wp3_contracts.py::NoFragmentsOfMalformedDocuments.test_extract_json_never_returns_an_inner_fragment
6.1 sections output: '## A. FACTS' + 2,000 spaces + 'x', 8,000 unclosed json openers, 1 MB
    -> linear time (the tests' budget is 1 s; measured 0.008-0.019 s, so the 50 ms oracle holds)
  unit/test_wp3_linear_parsers.py::AdversarialBudget.test_heading_with_long_whitespace_run
  unit/test_wp3_linear_parsers.py::AdversarialBudget.test_sections_with_heading_run_and_8000_unclosed_json_openers
    -> validated once per output, not on every poll
  unit/test_wp2a_worker.py::DoneRule.test_done_compares_the_recorded_output_hash
  unit/test_wp1a_ownership.py::CompareAndSwap.test_a_finished_job_is_not_re_derived_on_every_poll
6.1 FILE content with a literal '=== END FILE ===' line -> rejected as ambiguous framing
  unit/test_wp3_contracts.py::FileFraming.test_end_file_line_inside_content_is_a_contract_error
6.2 terminal takeover: A `run --continue` waits at G0, B `answer G0 --file private.json`, then A types go
    -> B is not refused, privacy.vendors stays false, calls.jsonl has no other-vendor row
  e2e/test_wp1a_concurrency.py::TwoSessions.test_the_terminal_lets_go_at_a_gate_and_never_rolls_back_another_session
  unit/test_wp8_guards.py::TerminalGuard (the lock is free while the human types; a stale answer is not applied)
6.2 reseat under an active driver (`continue --host codex` while A polls a 30 s stub)
    -> the reseat persists after the card's retry, or the card claims none
  e2e/test_wp1a_concurrency.py::TwoSessions.test_continue_with_another_host_under_a_live_driver_persists
  unit/test_wp1a_ownership.py::DriverOwnership.test_a_busy_run_is_not_touched_and_the_command_is_retried
6.2 driver kill (kill -9 mid-poll), B runs `next` at once -> B acquires in under 1 s
  e2e/test_wp1a_concurrency.py::TwoSessions.test_a_killed_driver_frees_the_lock_at_once
6.2 redo 12.1 while another process holds a file without FILE_SHARE_DELETE -> dispatch refuses while the journal is
    pending, the roll-forward finishes after the holder closes, no done step lacks its outputs
  unit/test_wp1a_ownership.py::JournaledSupersede.test_redo_against_a_held_file_never_leaves_done_steps_without_outputs
6.2 vendor partition: an HTTP stub answers 529 forever; a CLI prints 'rate limit' and exits 1 -> the rows of a job sum
    to the requests the server received, each back-off lies in [0, min(60, 2^(n+1))] s, the job ends failed/rate_limit
    within its deadline, requests_used <= max_calls
  unit/test_wp2b_retries.py::VendorPartitionTests (four tests)
  unit/test_wp1b_engine_flow.py::RequestBudget.test_a_529_forever_ledger_stops_at_the_cap_and_ub_budget_resumes
  unit/test_wpf1_request_ledger.py::WorstCaseTests.test_the_reserve_is_reached_exactly
6.3 output flood: 200 MB of JSONL on stdout, exit 0 -> bounded memory, an 8 MB stream cap, invalid/bad_output
  unit/test_wp2a_proc.py::CompletionTests.test_a_stdout_flood_is_capped_with_bounded_buffering
  unit/test_wp2a_proc.py::CompletionTests.test_the_default_stdout_cap_is_8_mb
  unit/test_wpf1_backends.py::StdoutOverflowTests, ::ParserMemoryTests
  unit/test_wp8_guards.py::ProcGuard (a CLI past the cap is stopped at once, not at the timeout)
6.3 orphaned descendant holding the pipes for 30 s -> run returns about 1 s after the child's exit with the output
    intact, the grandchild is killed
  unit/test_wp2a_proc.py::CompletionTests.test_a_descendant_holding_the_pipes_does_not_hold_run_up
  unit/test_wp2a_proc.py::CompletionTests.test_a_pipe_holder_outside_the_tree_costs_at_most_the_linger (POSIX)
  unit/test_wp8_guards.py::ProcGuard.test_the_rest_of_the_tree_is_stopped_after_one_linger (one linger, not two)
6.3 relaunch storm: 120 jobs, every worker dead at spawn (a pid no process has, U-24)
    -> launches <= min(7 x 120, budget), relaunches pass the budget gate, `_retry_blocked` keeps the cap
  NEW RelaunchStorm.test_120_jobs_killed_at_spawn_launch_7_times_each
  NEW RelaunchStorm.test_dead_relaunches_stop_at_the_request_cap
  unit/test_wp1b_engine_flow.py::RelaunchStorm (one job)
  unit/test_wp8_guards.py::BudgetGuard (the cap is inclusive)
    -> a no-op poll writes nothing and calls no fsync (bound 0.5 s per poll of 120 jobs; measured 0.04 s)
  NEW RelaunchStorm.test_an_idle_poll_of_120_running_jobs_writes_nothing
  unit/test_wp1b_engine_flow.py::RelaunchStorm.test_a_poll_that_changes_nothing_writes_nothing
"""

import contextlib
import io
import json
import os
import re
import shutil
import sys
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "harness"))
import e2elib  # noqa: E402
import paths  # noqa: E402
from tmphome import TmpHome  # noqa: E402

sys.path.insert(0, os.path.join(paths.FIXTURES, "engine"))
sys.path.insert(0, os.path.join(paths.FIXTURES, "adapter"))
import adapter_testlib as atl  # noqa: E402
import engine_testlib as tl  # noqa: E402

from ublib import adapter, batch, textio  # noqa: E402
from ublib.engine import EngineError, builders, pipeline, progress, registry, render_arch  # noqa: E402
from ublib.engine import state as st  # noqa: E402

KICKOFF = "pricing for $29/month; `touch PWNED`; $(whoami)"
ZWSP = chr(0x200B)  # a Unicode format character (Cf): invisible, so a judge can repeat an id with it
DEAD_PID = 2147483632  # a process id no process has on any OS (Linux pid_max <= 2^22; Windows ids stay far lower)


def _found(root, name):
    return [os.path.join(d, name) for d, _dirs, files in os.walk(root) if name in files]


# ------------------------------------------------------------------------------------------------ 6.1 kickoff

def _git_bash():
    """A bash that runs Windows programs (Git Bash) on Windows, the system bash elsewhere; None when absent."""
    cands = [shutil.which("bash")]
    if paths.IS_WINDOWS:
        for var in ("ProgramW6432", "ProgramFiles", "ProgramFiles(x86)"):
            if os.environ.get(var):
                cands.append(os.path.join(os.environ[var], "Git", "bin", "bash.exe"))
    for c in cands:
        low = (c or "").lower()
        if c and os.path.isfile(c) and "system32" not in low and "windowsapps" not in low:
            return c  # System32\bash.exe and the WindowsApps alias start WSL, a Linux that cannot run this python
    return None


def _powershell():
    """Windows PowerShell 5.1 first: it is what Codex and the Claude Code PowerShell tool run on a stock Windows."""
    for name in ("powershell", "pwsh"):
        exe = shutil.which(name)
        if exe:
            return exe
    return None


class KickoffPoisonPill(unittest.TestCase):
    """NEW. REPORT 6.1 'kickoff': the SKILL.md start line, run by a host in Git Bash and in PowerShell."""

    def start_line(self):
        skill = textio.read_text(paths.SKILL_MD)
        m = re.search(r"^- Start: (.*?)^- Continue:", skill, re.S | re.M)
        self.assertIsNotNone(m, "SKILL.md has no Start command")
        start = m.group(1)
        cmd = [ln.strip() for ln in start.splitlines() if ln.strip().startswith("UB init ")]
        self.assertEqual(len(cmd), 1, start)
        self.assertIn("never through the shell", start)
        self.assertNotRegex(cmd[0], r"--text[ =]", "the user's text is put on the command line")
        file_arg = re.search(r"--text-file (\S+)", cmd[0])
        self.assertIsNotNone(file_arg, cmd[0])
        return cmd[0], file_arg.group(1)

    def run_start_line(self, th, env, shell, line, kick_rel, components="grilling"):
        # the host writes the user's words to the kickoff file with its file tool, byte for byte
        kick = os.path.join(th.project, *kick_rel.split("/"))
        os.makedirs(os.path.dirname(kick), exist_ok=True)
        with open(kick, "wb") as f:
            f.write(KICKOFF.encode("utf-8"))
        py, ub = paths.posix(sys.executable), paths.posix(paths.UB_PY)
        self.assertIn('"<list>"', line)
        cmd = line.replace('"<list>"', '"%s"' % components).replace("HOST", "claude-code")
        if os.path.basename(shell).lower().startswith("bash"):
            argv = [shell, "-c", cmd.replace("UB ", '"%s" "%s" ' % (py, ub), 1)]
        else:
            argv = [shell, "-NoProfile", "-NonInteractive", "-Command",
                    cmd.replace("UB ", "& '%s' '%s' " % (py, ub), 1)]
        p = paths.run(argv, env=env, cwd=th.project, timeout=600)
        self.assertEqual(p.returncode, 0, paths.describe(p))
        return paths.last_json(p.out)

    def test_the_start_line_keeps_the_text_out_of_every_shell(self):
        line, kick_rel = self.start_line()
        shells = [s for s in (_git_bash(), _powershell() if paths.IS_WINDOWS else None) if s]
        if not shells:
            self.skipTest("no bash or PowerShell here")
        with TmpHome(tools=()) as th:
            env = e2elib.fake_env(th)
            for shell in shells:
                card = self.run_start_line(th, env, shell, line, kick_rel)
                run = card.get("run")
                self.assertTrue(run, card)
                rj = e2elib.run_json(run)
                self.assertEqual(rj["raw_text"], KICKOFF, "%s changed the kickoff text" % shell)
                self.assertIn("29", os.path.basename(run), "the slug lost '$29' in %s" % shell)
                self.assertEqual(_found(th.root, "PWNED"), [], "%s ran the backquoted command" % shell)
                self.assertFalse(os.path.exists(os.path.join(th.project, *kick_rel.split("/"))))

    def test_an_empty_component_list_survives_every_shell(self):
        """A host with none of the optional skills fills `--components ""`. Windows PowerShell 5.1 drops an empty
        argument of a native command, so ub.py then sees `--components --json`; the start line must still work."""
        line, kick_rel = self.start_line()
        shells = [s for s in (_git_bash(), _powershell() if paths.IS_WINDOWS else None) if s]
        if not shells:
            self.skipTest("no bash or PowerShell here")
        if paths.IS_WINDOWS and not _empty_components_fix():
            shells = [s for s in shells if os.path.basename(s).lower().startswith("bash")]  # WP8 cross-package request
        with TmpHome(tools=()) as th:
            env = e2elib.fake_env(th)
            for shell in shells:
                card = self.run_start_line(th, env, shell, line, kick_rel, components="")
                self.assertEqual(e2elib.run_json(card["run"])["raw_text"], KICKOFF)


def _empty_components_fix():
    """True once the start line survives a dropped empty argument: SKILL.md passes `--components="<list>"`, or ub.py
    accepts `--components` without a value."""
    if '--components="<list>"' in textio.read_text(paths.SKILL_MD):
        return True
    sys.path.insert(0, paths.SCRIPTS)
    import ub
    try:
        with contextlib.redirect_stderr(io.StringIO()):
            ub.build_parser().parse_args(["init", "--components", "--json"])
        return True
    except (SystemExit, Exception):  # ub's parser raises UsageError
        return False


# ------------------------------------------------------------------------------------------------ 6.1 judges

CRIT = {"Impact": 40, "Feasibility": 30, "Distinctiveness": 30}
IDS = ["I-%03d" % i for i in range(1, 9)]


def srow(iid, scores=(4, 3, 3)):
    return {"id": iid, "g1": True, "g2": True, "g3": True, "risk": "r",
            "c": {"Impact": scores[0], "Feasibility": scores[1], "Distinctiveness": scores[2]}}


def claude_result(text):
    return atl.PR(0, json.dumps({"type": "result", "subtype": "success", "is_error": False, "result": text}))


class WorkerCase(tl.EngineTestCase):
    """A run with the real engine job builder and the real adapter; only the CLI process is scripted (proc.run)."""

    def run_worker(self, job, answer):
        """execute_job for `job` on claude-cli, every call answered with `answer`. Returns (meta, calls)."""
        fake = atl.FakeRun([claude_result(answer)])
        det = atl.chain_detect({job["family"]: ["claude-cli"]}, host_family="claude")
        with mock.patch("ublib.proc.run", side_effect=fake), \
                mock.patch("ublib.proc.resolve_exe", side_effect=atl.fake_resolve()), \
                mock.patch("ublib.backends._sleep"):
            meta = adapter.execute_job(dict(job), detect_result=det)
        return meta, fake.calls

    def rows(self, ctx, jid):
        path = ctx.path("logs", "calls.jsonl")
        text = textio.read_text(path) if os.path.exists(path) else ""
        return [r for r in (json.loads(x) for x in text.splitlines() if x.strip()) if r.get("id") == jid]


class ScreenJudgePoisonPill(WorkerCase):
    """NEW. REPORT 6.1 'screen judge': the poison pill costs one repair call and never reaches the shortlist."""

    def test_one_repair_call_and_the_shortlist_is_unchanged(self):
        ctx = self.make_ctx(families=("claude", "gpt"), deps=tl.FakeDeps(bs=tl.real_bs))
        ctx.write("screen/ideas.md", "".join("%s | Title %s | pitch | mechanism\n" % (i, i) for i in IDS))
        ctx.write_json("criteria.json", CRIT)
        ctx.write_json("origins.json", dict((i, "human") for i in IDS))
        ctx.write_json("clusters.json", dict((i, "c%d" % (n // 2)) for n, i in enumerate(IDS)))
        st.save(ctx.run_dir, ctx.state)
        steps = pipeline.load_steps()
        registry.run_script(ctx, "prepare_screen", pipeline.step_by_id(steps, "6.1"))
        jobs = dict((j["family"], j) for j in builders.build_jobs(ctx, pipeline.step_by_id(steps, "6.2")))
        honest = [srow(i, (5 - n % 5, 3, 1 + n % 5)) for n, i in enumerate(IDS)]
        ctx.write(jobs["gpt"]["out"], json.dumps({"scores": honest}, indent=1) + "\n")  # the other judge's answer
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(tl.real_bs(["screen", ctx.run_dir], ctx.run_dir)[0], 0)
        before = textio.read_bytes(ctx.path("screen", "shortlist.json"))

        # every id, plus a duplicate I-008 with all scores 5, plus 'I-001' + U+200B, plus one score of 900
        rows = [srow(i) for i in IDS] + [srow("I-008", (5, 5, 5)), srow("I-001" + ZWSP, (4, 4, 4))]
        rows[2]["c"]["Impact"] = 900
        meta, calls = self.run_worker(jobs["claude"], json.dumps({"scores": rows}))
        self.assertEqual((meta["status"], meta["error_class"]), ("invalid", "bad_output"), meta.get("reason"))
        self.assertEqual(len(calls), 2, "one attempt and exactly one repair call")
        self.assertIn("more than once", meta["reason"])
        self.assertIn("greater than maximum 5", meta["reason"])
        self.assertEqual(sum(r.get("requests", 1) for r in self.rows(ctx, jobs["claude"]["id"])), 2)
        self.assertFalse(os.path.exists(ctx.path(jobs["claude"]["out"])), "the poisoned output was written")
        with contextlib.redirect_stdout(io.StringIO()):
            tl.real_bs(["screen", ctx.run_dir], ctx.run_dir)
        self.assertEqual(textio.read_bytes(ctx.path("screen", "shortlist.json")), before, "the shortlist moved")


POISON_DECISIONS = '{"adrs":[{"title":"A","options":[{"name":"x"}]},],"risks":[]}'  # REPORT 6.1, byte for byte
RESOLUTION = "# Resolution\n\n| finding | status |\n|---|---|\n| F-1 | FIXED |"
STATUS = '{"status": "complete", "assumptions": ["a"], "open_questions": [], "reason": ""}'


class ArchFixPoisonPill(WorkerCase):
    """NEW. REPORT 6.1 'ARCH-FIX': a trailing comma inside decisions.json never re-renders the ADRs."""

    def arch_run(self):
        ctx = self.make_ctx(variant="software", families=("claude", "gpt"))
        ctx.write("10_ARCHITECTURE/decisions.json", json.dumps({"adrs": [
            {"title": "Keep one database", "options": [{"name": "Postgres"}, {"name": "SQLite"}]},
            {"title": "Queue the swaps", "options": [{"name": "outbox"}]}], "risks": []}, indent=1) + "\n")
        for name in ("0001-keep-one-database.md", "0002-queue-the-swaps.md"):
            ctx.write("10_ARCHITECTURE/adr/" + name, "# ADR %s\n\nThe human-reviewed record.\n" % name[:4])
        st.save(ctx.run_dir, ctx.state)
        return ctx

    def snapshot(self, ctx):
        root = ctx.path("10_ARCHITECTURE")
        out = {}
        for d, _dirs, files in os.walk(root):
            for n in files:
                p = os.path.join(d, n)
                rel = os.path.relpath(p, root).replace("\\", "/")
                if rel == "decisions.json" or rel.startswith("adr/"):
                    out[rel] = textio.read_bytes(p)
        return out

    def test_the_report_decisions_json_fails_and_adr_is_untouched(self):
        ctx = self.arch_run()
        before = self.snapshot(ctx)
        job = builders.build_jobs(ctx, pipeline.step_by_id(pipeline.load_steps(), "12.14"))[0]
        answer = ("=== FILE: decisions.json ===\n%s\n=== END FILE ===\n=== FILE: review/resolution.md ===\n%s\n"
                  "=== END FILE ===\n=== STATUS ===\n%s\n=== END STATUS ===\n" % (POISON_DECISIONS, RESOLUTION, STATUS))
        meta, calls = self.run_worker(job, answer)
        self.assertEqual((meta["status"], len(calls)), ("invalid", 2), meta.get("reason"))
        self.assertIn("decisions.json: not valid JSON", meta["reason"])
        self.assertEqual(self.snapshot(ctx), before, "the FILE blocks of a failed contract were written")
        self.assertFalse(os.path.exists(ctx.path("10_ARCHITECTURE", "review", "resolution.md")))
        # the same bytes on disk (a hand edit, a host sub-agent): the ADR render refuses and leaves adr/ alone
        textio.write_text_atomic(ctx.path("10_ARCHITECTURE", "decisions.json"), POISON_DECISIONS + "\n")
        before = self.snapshot(ctx)
        with self.assertRaises(EngineError) as cm:
            render_arch.rerender_adrs(ctx)
        self.assertIn("the ADRs were left as they are", str(cm.exception))
        self.assertEqual(self.snapshot(ctx), before)


# ------------------------------------------------------------------------------------------------ 6.3 relaunch storm

class _DeadWorker(object):
    """What _spawn_detached returns when the host kills the worker at spawn (U-24): a pid no process has."""

    pid = DEAD_PID

    def poll(self):
        return -9


class RelaunchStorm(tl.EngineTestCase):
    """NEW. REPORT 6.3 'relaunch storm' with the real batch module: 120 jobs whose workers die at spawn."""

    N = 120

    def storm_ctx(self, autopilot="guided", ledger=False, cap=None, reserve=2):
        """reserve: the worst-case requests of one launch (C6), fixed for the arithmetic of each test."""
        n = self.N

        class Deps(pipeline.Deps):
            def request_reserve(self, job):
                return reserve
        clock = {"t": 1000.0}

        def sleep(s):
            clock["t"] += s
        cfg = {"defaults": {"parallel": 1000, "retries": 1}, "families": {"claude": {"limit": 1000}}}
        ctx = self.make_ctx(families=("claude",), autopilot=autopilot, deps=Deps(
            bs=tl.FakeBs(), families_cfg=cfg, now=lambda: clock["t"], sleep=sleep))
        if cap:
            ctx.state["budget"]["max_calls"] = cap
        self.launches = {}

        def spawn(argv, logf, run_dir, token=None, gen=None):
            jid = os.path.basename(argv[-1])[:-len(".json")]
            self.launches[jid] = self.launches.get(jid, 0) + 1
            if ledger:  # the killed worker had sent one request before it died
                textio.append_line(os.path.join(run_dir, "logs", "calls.jsonl"), json.dumps(
                    {"ts": textio.now_iso(), "id": jid, "family": "claude", "backend": "claude-cli",
                     "status": "failed", "requests": 1}))
            return _DeadWorker()

        def fanout(ctx_, step):
            return [{"id": "%03d" % i, "template": "PROBE", "kind": "writer", "family": "claude", "tools": "none",
                     "cwd": "empty", "out": "storm/%03d.md" % i, "contract": {"type": "text", "min_chars": 5},
                     "fallback": []} for i in range(n)]
        for p in (mock.patch.object(batch, "_spawn_detached", spawn),
                  mock.patch.dict(registry.FANOUTS, {"wp8_storm": fanout})):
            p.start()
            self.addCleanup(p.stop)
        step = {"id": "11.1", "stage": 11, "title": "Storm", "type": "DISPATCH", "fanout": "wp8_storm",
                "job": {"kind": "writer"}, "min_ok": 1, "after": []}
        return ctx, [step]

    def host_loop(self, ctx, steps, calls):
        """A host that runs `next` after every card, BLOCKED included."""
        seen = []
        for _ in range(calls):
            card = pipeline.advance(ctx, steps, 10)
            seen.append(card["type"])
        return card, seen

    def test_120_jobs_killed_at_spawn_launch_7_times_each(self):
        ctx, steps = self.storm_ctx()
        cap = 1 + batch.RELAUNCH_LIMIT * pipeline.RELAUNCH_ROUNDS
        self.assertEqual(cap, 7)
        card, seen = self.host_loop(ctx, steps, 25)
        self.assertIn("BLOCKED", seen)
        self.assertEqual(len(self.launches), self.N)
        self.assertEqual(sorted(set(self.launches.values())), [cap], "launches per job: %s" % sorted(
            set(self.launches.values())))
        total = sum(self.launches.values())
        self.assertEqual(total, cap * self.N)
        # every job was given up (a driver-written 'killed' meta), so the step is BLOCKED on min_ok
        self.assertEqual(card["type"], "BLOCKED", card.get("say"))
        metas = [ctx.read_json("storm/%03d.md.meta.json" % i, {}) or {} for i in range(self.N)]
        self.assertEqual(set(m.get("error_class") for m in metas), {"killed"})
        # the cap holds however often `next` is called: no BLOCKED retry resets it
        self.host_loop(ctx, steps, 10)
        self.assertEqual(sum(self.launches.values()), total)

    def test_dead_relaunches_stop_at_the_request_cap(self):
        # Each dead launch leaves one request in the ledger. A launch in flight also holds its reserve (1) until it is
        # known to be dead, so the first pass admits (cap + 1) / 2 = 76 jobs; relaunching those without the budget
        # gate would then overshoot the odd cap by one request.
        cap = 151  # < 7 x 120 launches: the budget binds before the relaunch cap
        ctx, steps = self.storm_ctx(autopilot="full-auto", ledger=True, cap=cap, reserve=1)
        card, seen = self.host_loop(ctx, steps, 25)
        total = sum(self.launches.values())
        used = progress.requests_used(ctx)
        self.assertEqual(used, total)  # one ledger request per launch
        self.assertLessEqual(used, cap, "dead relaunches went past the request cap")
        self.assertEqual(used, cap, "the storm stopped before the cap bound (%d)" % used)
        self.assertGreater(total, len(self.launches), "no dead job was relaunched")
        self.assertEqual(card["type"], "BLOCKED")
        self.assertIn("request cap", card["say"])
        state = st.load(ctx.run_dir)
        self.assertEqual(state["status"], "stopped")
        self.host_loop(ctx, steps, 5)
        self.assertEqual(sum(self.launches.values()), total, "a relaunch went past the request cap")

    def test_an_idle_poll_of_120_running_jobs_writes_nothing(self):
        n = self.N

        def fanout(ctx_, step):
            return [{"id": "%03d" % i, "template": "PROBE", "kind": "writer", "family": "claude", "tools": "none",
                     "cwd": "empty", "out": "storm/%03d.md" % i, "contract": {"type": "text", "min_chars": 5},
                     "fallback": []} for i in range(n)]
        p = mock.patch.dict(registry.FANOUTS, {"wp8_storm": fanout})
        p.start()
        self.addCleanup(p.stop)
        fake = tl.FakeBatch(running=set("11.1-%03d" % i for i in range(n)))  # workers that keep running
        deps = tl.FakeDeps(batch=fake, cfg={"defaults": {"parallel": 1000, "retries": 1},
                                            "families": {"claude": {"limit": 1000}}})
        ctx = self.make_ctx(families=("claude",), deps=deps)
        ctx.state["budget"]["max_calls"] = 10000
        steps = [{"id": "11.1", "stage": 11, "title": "Storm", "type": "DISPATCH", "fanout": "wp8_storm",
                  "job": {"kind": "writer"}, "min_ok": 1, "after": []}]
        self.assertEqual(pipeline.advance(ctx, steps, 0)["type"], "AUTO")
        self.assertEqual(len((ctx.state["steps"]["11.1"] or {}).get("jobs") or []), n)
        counts, durations = [], []
        for wait in (4, 40):  # 2 polls, then 20 polls of jobs that keep running
            writes = []
            real = {"json": textio.write_json_atomic, "text": textio.write_text_atomic, "line": textio.append_line,
                    "fsync": os.fsync}

            def spy(kind):
                def fn(*a, **k):
                    writes.append((kind, a[0] if a else None))
                    return real[kind](*a, **k)
                return fn
            t0 = time.perf_counter()
            with mock.patch.object(textio, "write_json_atomic", spy("json")), \
                    mock.patch.object(textio, "write_text_atomic", spy("text")), \
                    mock.patch.object(textio, "append_line", spy("line")), \
                    mock.patch.object(os, "fsync", spy("fsync")):
                card = pipeline.advance(ctx, steps, wait)
            durations.append((time.perf_counter() - t0) / (wait / pipeline.POLL_S))
            self.assertEqual(card["type"], "AUTO")
            counts.append(len(writes))
        self.assertEqual(counts[0], counts[1], "idle polls wrote files: %s" % counts)
        self.assertEqual(fake.launched, [], "an idle poll launched a job")
        self.assertLess(max(durations), 0.5, "an idle poll of %d running jobs took %.3f s" % (n, max(durations)))


if __name__ == "__main__":
    unittest.main()
