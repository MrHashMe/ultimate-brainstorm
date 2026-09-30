"""Phase J, engine CLI: the round-4 open items of `ub.py`'s commands and their arguments (KIT_SPEC 4.11, 4.12; audit
items P3-engine-1 and #82, and the round-4 reviewer and hunt claims on mistyped runs, `init` command words, imports,
missing files, card paths and variant inference).

- `ub run stop|status|continue <a run that does not exist>` is BLOCKED 'run folder not found', never a new run
- `init` kickoff text whose first word is a command word and whose rest is no run is BLOCKED with a hint
- `ub import` curates the pool again in quick mode (Q.3), is refused in proposal mode, and never claims a curation
  that does not happen
- a file the user named that cannot be read is a usage error (exit 2) and leaves no run folder behind
- a run folder whose path bash or PowerShell change inside double quotes is never started, and an agent is told how to
  resume one that exists
- common app words ('study', 'brand-new', 'ad-free', 'user story', 'state of the art') do not pick an approach
  variant, and the kickoff card says when the variant was inferred
"""

import io
import json
import os
import shutil
import subprocess
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fixtures", "engine"))
import engine_testlib as tl  # noqa: E402

from ublib import textio  # noqa: E402
from ublib.engine import cards, pipeline  # noqa: E402
from ublib.engine import state as st  # noqa: E402

sys.path.insert(0, tl.SCRIPTS)
import ub  # noqa: E402


def git_bash():
    """A bash that runs Windows programs (Git Bash) on Windows, the system bash elsewhere; None when absent. The bash of
    System32 and the WindowsApps alias start WSL."""
    cands = [shutil.which("bash")]
    if os.name == "nt":
        cands += [os.path.join(os.environ[v], "Git", "bin", "bash.exe") for v in ("ProgramW6432", "ProgramFiles")
                  if os.environ.get(v)]
    for c in cands:
        if c and os.path.isfile(c) and "system32" not in c.lower() and "windowsapps" not in c.lower():
            return c
    return None


class Base(tl.EngineTestCase):
    def run_ub(self, *args, **kw):
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(sys, "stdout", out), mock.patch.object(sys, "stderr", err), \
                mock.patch.object(sys, "stdin", io.StringIO("")):
            rc = ub.main([str(a) for a in args], deps=kw.get("deps") or tl.FakeDeps(detect=tl.fake_detect()))
        text = out.getvalue()
        self.last_stderr = err.getvalue()
        return rc, (json.loads(text) if text.strip().startswith("{") else text)

    def new_run(self, root=None, topic="shift-swap app for nurses"):
        rc, card = self.run_ub("init", "--host", "claude-code", "--text", topic, "--root", root or self.project,
                               "--no-preflight", "--json")
        self.assertEqual(rc, 0, (card, self.last_stderr))
        return card["run"]

    def run_terminal(self, *args):
        seen = []

        def fake_loop(ctx, steps, lock=None, **kw):  # never reads stdin
            seen.append(ctx)
            return {"type": "DONE", "say": "x"}
        with mock.patch("ublib.engine.terminal.run_loop", fake_loop):
            rc, res = self.run_ub("run", *args)
        return rc, res, seen

    def folders(self, root):
        """The folders under a run root (run folders and orphans alike)."""
        if not os.path.isdir(root):
            return []
        return sorted(d for d in os.listdir(root) if os.path.isdir(os.path.join(root, d)))

    def file(self, name, text):
        path = os.path.join(self.tmp, name)
        textio.write_text_atomic(path, text)
        return path


# ------------------------------------------------------------------------------------------------ run references

class MistypedRun(Base):
    def test_a_command_word_before_a_run_that_does_not_exist_is_blocked(self):
        """Review claim: `ub run stop <run path with a typo>` created, registered and drove a new run named after the
        command line, and the run meant was never stopped."""
        run = self.new_run()
        root = os.path.dirname(run)
        before = self.folders(root)
        for words in (["stop", run + "X"], ["continue", os.path.basename(run)[:-1]], ["status", "./nope"],
                      ["stop", "C:/nope/2026-01-01-x"], ["status", "brainstorm/nope"]):
            rc, res, seen = self.run_terminal(*(words + ["--root", self.project, "--no-preflight", "--json"]))
            self.assertEqual((rc, res.get("type"), seen), (0, "BLOCKED", []), words)
            self.assertIn("run folder not found", res["say"], words)
            self.assertEqual(res["fix"], ["ub list --json"])
        rc, res, seen = self.run_terminal("--text", "stop " + run + "X", "--root", self.project, "--json")
        self.assertEqual((res.get("type"), seen), ("BLOCKED", []))
        rc, card = self.run_ub("init", "--host", "claude-code", "--text", "stop " + run + "X", "--root", self.project,
                               "--json")
        self.assertIn("run folder not found", card["say"])
        self.assertEqual(self.folders(root), before)
        self.assertEqual(st.load(run)["status"], "active")

    def test_a_run_path_with_two_spaces_in_a_row_is_found(self):
        run = self.new_run(root=os.path.join(self.tmp, "a  b"))
        rc, res, seen = self.run_terminal("stop", run, "--json")
        self.assertEqual(seen, [])
        self.assertEqual(res.get("run"), textio.to_posix(run))
        self.assertEqual(st.load(run)["status"], "stopped")

    def test_a_topic_with_a_slash_inside_still_starts_a_run(self):
        rc, res, seen = self.run_terminal("status page for web/mobile teams", "--root", self.project, "--no-preflight",
                                          "--json")
        self.assertEqual([c.state["topic"] for c in seen], ["status page for web/mobile teams"])


class InitCommandWords(Base):
    def kickoff(self, text):
        path = os.path.join(self.project, "brainstorm", ".kickoff.txt")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        textio.write_text_atomic(path, text + "\n")
        with mock.patch.object(ub, "cmd_doctor", return_value={"doctor": "ran"}):
            return self.run_ub("init", "--host", "claude-code", "--text-file", path, "--root", self.project,
                               "--components=", "--no-preflight", "--json")

    def test_a_topic_that_starts_with_a_command_word_is_blocked_with_a_hint(self):
        """Hunt claim (#82 on the agent path): '/ultimate-brainstorm doctor appointment reminders ...' printed a doctor
        report, and 'stop smoking coach ...' said 'run folder not found: <cwd>/smoking coach ...'."""
        for topic in ("doctor appointment reminders for rural clinics", "status report generator for small agencies",
                      "stop smoking coach for night-shift nurses", "continue education tracker for nurses"):
            rc, card = self.kickoff(topic)
            self.assertEqual((rc, card.get("type")), (0, "BLOCKED"), topic)
            self.assertIn("for example: standard %s." % topic, card["say"])
            self.assertIn("ub list --json", card["fix"])
            self.assertEqual(self.folders(os.path.join(self.project, "brainstorm")), [], topic)
        self.assertIn("ub doctor --json", self.kickoff("doctor appointment reminders")[1]["fix"])
        rc, card = self.kickoff("standard doctor appointment reminders for rural clinics")  # the escape
        self.assertEqual(card["gate"], "G0")
        self.assertEqual(st.load(card["run"])["topic"], "doctor appointment reminders for rural clinics")

    def test_a_command_word_before_nothing_or_a_run_is_still_a_command(self):
        run = self.new_run()
        self.assertEqual(self.kickoff("doctor")[1], {"doctor": "ran"})
        rc, res = self.kickoff("status " + os.path.basename(run))  # a run's name under the run root
        self.assertEqual(res["run"], textio.to_posix(run))
        rc, card = self.kickoff("continue " + run)
        self.assertEqual((card["run"], card["gate"]), (textio.to_posix(run), "G0"))
        rc, res = self.kickoff("stop " + os.path.basename(run))
        self.assertEqual(st.load(run)["status"], "stopped")


# ------------------------------------------------------------------------------------------------ import

class Import(Base):
    def import_list(self, run, deps=None):
        f = self.file("ideas-from-tool.md", "## IMP-01 A totally new imported idea\nPitch: something new\n")
        return self.run_ub("import", f, run, "--json", deps=deps)

    def test_an_import_into_a_finished_quick_run_is_curated_again(self):
        """Hunt claim: in quick mode the import said 'the pool is re-curated' and nothing was (5.1 is skipped)."""
        ctx = tl.full_auto_ctx(self, mode="quick")
        self.assertEqual(tl.drive(ctx)["type"], "DONE")
        rc, card = self.import_list(ctx.run_dir, deps=ctx.deps)  # refs.import_from_quick: Q.3
        self.assertNotEqual(card["type"], "DONE")
        self.assertIn("pool/IMPORT_ideas-from-tool.md; the pool is curated again from step Q.3", card["notes"][0])
        state = st.load(ctx.run_dir)
        self.assertEqual(state["status"], "active")
        self.assertNotEqual(st.step_state(state, "Q.3"), "done")
        ctx = ub.load_ctx(ctx.run_dir, ctx.deps, persist=True)
        self.assertEqual(tl.drive(ctx)["type"], "DONE")
        self.assertIn("FILE: pool/IMPORT_ideas-from-tool.md", ctx.read("prompts/Q.3.prompt.md"))

    def test_an_import_before_the_curation_is_curated_there(self):
        ctx = self.make_ctx(mode="standard")
        st.set_step(ctx.state, "0.1", "done")
        st.save(ctx.run_dir, ctx.state)
        rc, card = self.import_list(ctx.run_dir, deps=ctx.deps)
        self.assertIn("pool/IMPORT_ideas-from-tool.md; step 5.1 curates it with the pool", card["notes"][0])
        self.assertTrue(ctx.exists("pool/IMPORT_ideas-from-tool.md"))

    def test_an_import_into_a_proposal_run_is_refused(self):
        ctx = self.make_ctx(mode="proposal")
        st.save(ctx.run_dir, ctx.state)
        rc, card = self.import_list(ctx.run_dir, deps=ctx.deps)
        self.assertEqual(card["type"], "BLOCKED")
        self.assertIn("proposal mode has no idea pool", card["say"])
        self.assertFalse(ctx.exists("pool/IMPORT_ideas-from-tool.md"))

    def test_an_import_no_curation_step_reads_is_refused(self):
        """A pipeline.json without a quick-mode curation ref: never the success note (5.1 does not run in quick)."""
        data = pipeline.load_data()
        refs = dict((k, v) for k, v in data["refs"].items() if k != "import_from_quick")
        ctx = self.make_ctx(mode="quick")
        st.save(ctx.run_dir, ctx.state)
        with mock.patch.dict(data, {"refs": refs}):
            rc, card = self.import_list(ctx.run_dir, deps=ctx.deps)
        self.assertEqual(card["type"], "BLOCKED")
        self.assertIn("step 5.1, which curates the pool, does not run in this quick run", card["say"])
        self.assertFalse(ctx.exists("pool/IMPORT_ideas-from-tool.md"))


# ------------------------------------------------------------------------------------------------ missing files

class MissingFiles(Base):
    def test_a_file_the_user_named_that_is_missing_is_a_usage_error(self):
        """Hunt claim: exit 1 with 'internal error' and the fix 'ub doctor'; --seeds-file left an orphan run folder."""
        missing = os.path.join(self.tmp, "nope.md")
        root = os.path.join(self.project, "brainstorm")
        for flag in ("--seeds-file", "--idea-file"):
            rc, out = self.run_ub("init", "--host", "claude-code", "--text", "a pricing page for nurses", flag, missing,
                                  "--root", self.project, "--no-preflight", "--json")
            self.assertEqual(rc, 2, flag)
            self.assertIn("usage error: cannot read %s %s" % (flag, missing), self.last_stderr)
            self.assertEqual(self.folders(root), [], flag)
        run = self.new_run()
        for args in (["import", missing, run], ["probe-result", run, "PASSED", "--note-file", missing],
                     ["attach-s1", run, "--doc", missing]):
            rc, out = self.run_ub(*(args + ["--json"]))
            self.assertEqual(rc, 2, args)
            self.assertIn("usage error: cannot read", self.last_stderr)
        rc, out = self.run_ub("attach-s1", run, "--doc", self.file("s1.md", "# S1\n"), "--raw", missing, "--json")
        self.assertEqual(rc, 2)
        self.assertFalse(os.path.exists(os.path.join(run, "pool", "S1_ce-ideate.md")))  # no half-done attach

    def test_a_seeds_file_is_written_as_utf8_with_lf(self):
        path = os.path.join(self.tmp, "seeds.md")
        with open(path, "wb") as f:
            f.write(b"\xef\xbb\xbf## Ideas\r\n- night swap board\r\n")
        rc, card = self.run_ub("init", "--host", "claude-code", "--text", "shift-swap app for nurses", "--seeds-file",
                               path, "--root", self.project, "--no-preflight", "--json")
        with open(os.path.join(card["run"], "00_HUMAN_SEEDS.md"), "rb") as f:
            self.assertEqual(f.read(), b"## Ideas\n- night swap board\n")


# ------------------------------------------------------------------------------------------------ card paths

class CardPaths(Base):
    def test_a_run_folder_the_card_commands_cannot_quote_is_never_started(self):
        """Hunt claim and P3-engine-1: in 'pay$app' every card command reached '<root>/pay/...' ('run folder not
        found'), and PowerShell ends a double-quoted string at U+201D."""
        for name in ("pay$app", "x$_y", "my`proj", "a\u201db"):
            root = os.path.join(self.tmp, name)
            rc, out = self.run_ub("init", "--host", "claude-code", "--text", "shift-swap app for nurses", "--root",
                                  root, "--no-preflight", "--json")
            self.assertEqual(rc, 2, ascii(name))
            self.assertIn("usage error: the run folder", self.last_stderr)
            self.assertIn("--root <folder>", self.last_stderr)
            self.assertFalse(os.path.exists(os.path.join(root, "brainstorm")), ascii(name))
        rc, res, seen = self.run_terminal("shift-swap app", "--root", os.path.join(self.tmp, "pay$app"), "--json")
        self.assertEqual((rc, seen), (2, []))

    def test_a_dollar_before_a_slash_a_percent_and_a_bang_stay(self):
        """'c$/' (an administrative share) and '%' or '!' reach bash and PowerShell unchanged in double quotes."""
        run = self.new_run(root=os.path.join(self.tmp, "c$", "100% ideas!"))
        self.assertTrue(os.path.isfile(os.path.join(run, "run.json")))
        for path, want in (("C:/a/pay$app", "$"), ("C:/a/b\u201d", "\u201d"), ("C:/a/c$/x", None), ("C:/a/c$", None)):
            self.assertEqual(cards.unquotable(path), want, ascii(path))

    def test_unquotable_names_what_bash_and_powershell_change(self):
        """The rule against the shells themselves: a double-quoted path comes back unchanged exactly when
        cards.unquotable finds nothing in it."""
        shells = []
        if git_bash():
            shells.append([git_bash(), "-c", "printf '%s' \"{}\""])
        if os.name == "nt" and shutil.which("powershell"):
            shells.append([shutil.which("powershell"), "-NoProfile", "-NonInteractive", "-Command",
                           "[Console]::Out.Write(\"{}\")"])
        if not shells:
            self.skipTest("no bash or PowerShell here")
        for s in ("/p/pay$app/x", "/p/x$_y/x", "/p/$tmp/x", "/p/my`proj/x", "/p/c$/x", "/p/100% ideas!/x", "/p/it's/x"):
            for argv in shells:
                p = subprocess.run(argv[:-1] + [argv[-1].replace("{}", s)], stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, timeout=120)
                back = textio.decode_bytes(p.stdout)
                self.assertEqual(back == s, cards.unquotable(s) is None, (argv[0], s, back, p.stderr))

    def test_the_kit_folder_is_checked_too(self):
        with mock.patch.object(cards, "UB_PY", os.path.join(self.tmp, "kit$1", "ub.py")):
            rc, out = self.run_ub("init", "--host", "claude-code", "--text", "shift-swap app", "--root", self.project,
                                  "--no-preflight", "--json")
        self.assertEqual(rc, 2)
        self.assertIn("the kit folder", self.last_stderr)

    def test_an_agent_is_told_how_to_resume_a_run_in_such_a_folder(self):
        """A run an older kit started there (or a folder renamed later): `continue` finds it without a path, but its
        cards would break again, so it is BLOCKED with a move and a terminal route; `run --continue` still works."""
        run = self.new_run()
        bad_root = os.path.join(self.tmp, "pay$app")
        shutil.move(self.project, bad_root)
        moved = os.path.join(bad_root, "brainstorm", os.path.basename(run))
        rc, card = self.run_ub("continue", "--host", "claude-code", "--root", bad_root, "--json")
        self.assertEqual(card["type"], "BLOCKED")
        self.assertIn("holds '$'", card["say"])
        self.assertIn("run --continue '%s'" % textio.to_posix(moved), card["fix"][1])
        rc, res, seen = self.run_terminal("--continue", moved, "--json")
        self.assertEqual([os.path.normcase(c.run_dir) for c in seen], [os.path.normcase(moved)])


# ------------------------------------------------------------------------------------------------ variants

class VariantInference(Base):
    def test_common_app_words_do_not_pick_an_approach_variant(self):
        """Hunt claim: 'study', 'brand-new', 'ad-free', 'user story' and 'state of the art' chose research, marketing
        or creative, whose build type skips the whole architecture stage."""
        for topic in ("a study planner app for nursing students", "brand-new shift scheduling app for nurses",
                      "an ad-free reading app for kids", "user story mapping tool for agile teams",
                      "state of the art triage app", "a paper trading app for students",
                      "an app to find study partners", "an art marketplace app",
                      "a case study library for SaaS founders", "a film photography app",
                      "apps for night-shift nurses"):
            self.assertEqual(ub.infer_variant(topic, cwd=self.project), "product", topic)
        for topic, want in (("improve onboarding activation", "growth"), ("a name for my bakery", "naming"),
                            ("a research question about sleep and shift work", "research"),
                            ("hypotheses for why nurses quit", "research"), ("a user study of triage apps", "research"),
                            ("a study of burnout in ICU nurses", "research"),
                            ("a marketing campaign for my SaaS product", "marketing"),
                            ("ad campaign for a dental clinic", "marketing"), ("ads for my yoga studio", "marketing"),
                            ("a brand for a coffee roaster", "marketing"),
                            ("a short story about a lighthouse keeper", "creative"),
                            ("a song for my sister's wedding", "creative"),
                            ("a film about climate migration", "creative"),
                            ("an art installation for a hospital lobby", "creative"),
                            ("fix the api bug", "general"), ("a novel way to cut waiting times", "general")):
            self.assertEqual(ub.infer_variant(topic, cwd=self.project), want, topic)

    def test_the_kickoff_card_says_when_the_variant_was_inferred(self):
        """Hunt claim: gates._v_g0 reads options.variant_inferred, which nothing set."""
        rc, card = self.run_ub("init", "--host", "claude-code", "--text", "an ad-free reading app for kids", "--root",
                               self.project, "--no-preflight", "--json")
        self.assertIn("Variant: product (inferred; start your reply with another variant to change it)", card["show"])
        self.assertTrue(st.load(card["run"])["options"]["variant_inferred"])
        for args in (["--text", "marketing an ad-free reading app"],
                     ["--text", "an ad-free app", "--variant", "product"]):
            rc, card = self.run_ub(*(["init", "--host", "claude-code", "--root", self.project, "--no-preflight",
                                      "--json"] + args))
            self.assertNotIn("(inferred;", card["show"], args)
            self.assertFalse(st.load(card["run"])["options"]["variant_inferred"], args)


if __name__ == "__main__":
    unittest.main()
