"""Phase F1, the blind quick screen (finding 51, quick mode).

Quick mode used to take its finalists from QUICK-CURATE's own scores: one host call that reads the raw generator files
(the ideas in their authors' own wording) scored every idea, and nothing else scored them, so the host's preference
for its own family's ideas could decide which ideas reached the quick tournament. Now the curated neutral Q-lines are
scored blind by both quick generator families (Q.3p prepares the screen prompts, Q.3s runs the screen judges, with the
screen's origin-label check), and `bs.py quick-pick` averages them with the screen's own-origin correction and per-judge
centering. A one-family run has no quick screen: it keeps the curator's scores, flagged in finalists.json and in a
run note. No model CLI and no network: bs.py runs in-process or as a subprocess, the engine with fake workers.
"""

import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fixtures", "engine"))
import engine_testlib as tl  # noqa: E402

import bs  # noqa: E402
import ub  # noqa: E402
from ublib import textio  # noqa: E402
from ublib.engine import builders, pipeline, privacy, registry, seats  # noqa: E402
from ublib.engine import state as st  # noqa: E402

BS = os.path.join(tl.SCRIPTS, "bs.py")
CRIT = {"Value": 40, "Feasibility": 30, "Distinctiveness": 30}
FAMILIES = {"QA": "claude", "QB": "gpt", "H": "human", "HP": "human"}


def quiet(fn, *args, **kw):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        fn(*args, **kw)
    return buf.getvalue()


def qidea(iid, cluster, aliases, curator, gates=(True, True, True)):
    """A quick/curated.json idea whose curator scores every criterion `curator`."""
    return {"id": iid, "title": "Idea %s" % iid, "pitch": "pitch %s" % iid, "mechanism": "mechanism %s" % iid,
            "cluster": cluster, "aliases": list(aliases),
            "gates": {"g1": gates[0], "g2": gates[1], "g3": gates[2]},
            "scores": [{"criterion": k, "score": curator} for k in CRIT],
            "fails_if": "nobody posts", "problem": "swaps take days", "for_whom": "night nurses",
            "first_version": "a shared sheet"}


def blind(iid, value, gates=(True, True, True)):
    """One screen judge record for a Q-line: every criterion `value`."""
    return {"id": iid, "g1": gates[0], "g2": gates[1], "g3": gates[2], "c": dict((k, value) for k in CRIT),
            "risk": "adoption"}


class QuickPickCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ub-f1-quick-")
        self.run = os.path.join(self.tmp, "brainstorm", "2026-09-26-f1-quick")
        os.makedirs(self.run)
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def w(self, rel, obj):
        path = os.path.join(self.run, *rel.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        textio.write_text_atomic(path, obj if isinstance(obj, str) else json.dumps(obj))

    def r(self, rel):
        path = os.path.join(self.run, *rel.split("/"))
        return textio.read_json(path) if rel.endswith(".json") else textio.read_text(path)

    def setup_run(self, ideas, outs=None, judges=("claude", "gpt")):
        self.w("run.json", {"schema": 2, "run": "2026-09-26-f1-quick", "mode": "quick",
                            "seats": {"screen_judges": list(judges), "tournament_judges": ["gpt"]}})
        self.w("criteria.json", CRIT)
        self.w("pool/_families.json", FAMILIES)
        self.w("quick/curated.json", {"ideas": ideas})
        for label, rows in (outs or {}).items():
            self.w("screen/%s.out.json" % label, {"scores": rows})

    def finalists(self):
        return sorted(f["id"] for f in self.r("quick/finalists.json")["finalists"])

    def cli(self, *args):
        return subprocess.run([sys.executable, BS] + list(args), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              env=dict(os.environ, PYTHONIOENCODING="utf-8"), cwd=self.tmp)


class BlindScoresPickTests(QuickPickCase):
    def pool(self):
        """Three clusters, each a claude idea the curator (the host, claude) rates 5 and a gpt idea it rates 2."""
        return [qidea("Q-01", "A", ["QA-01"], 5), qidea("Q-02", "A", ["QB-01"], 2),
                qidea("Q-03", "B", ["QA-02"], 5), qidea("Q-04", "B", ["QB-02"], 2),
                qidea("Q-05", "C", ["QA-03", "QA-04"], 5), qidea("Q-06", "C", ["QB-03"], 2)]

    def test_the_blind_judges_pick_not_the_curator(self):
        # finding 51 (3): quick-pick took the best of each cluster by the host curator's own scores, so its own
        # family's ideas won every cluster; the two blind judges both prefer the gpt ideas
        judge = [blind("Q-01", 3), blind("Q-02", 5), blind("Q-03", 3), blind("Q-04", 5), blind("Q-05", 2),
                 blind("Q-06", 4)]
        self.setup_run(self.pool(), {"claude": judge, "gpt": judge})
        out = quiet(bs.quick_pick, self.run)
        self.assertEqual(self.finalists(), ["Q-02", "Q-04", "Q-06"])
        fin = self.r("quick/finalists.json")
        self.assertEqual(fin["scoring"], "blind")
        self.assertEqual([j["label"] for j in fin["judges"]], ["claude", "gpt"])
        self.assertEqual(dict((f["id"], f["score"]) for f in fin["finalists"]), {"Q-02": 5.0, "Q-04": 5.0,
                                                                                  "Q-06": 4.0})
        self.assertIn("by the blind quick screen (claude, gpt)", out)
        md = self.r("quick/screen.md")
        self.assertIn("# Quick screen (blind)", md)
        self.assertIn("| Q-01 | A | claude | 3.00 | 5.00 | ok |  |", md)  # the curator's 5 is shown, not used
        self.assertIn("## Own-origin gap", md)

    def test_a_self_preferring_judge_is_corrected(self):
        # the screen's correction: with 3 human ideas as the reference, claude's +2 on its own vendor's ideas is
        # measured (difference in differences against gpt) and taken off; the plain mean would pick claude's ideas
        ideas = self.pool() + [qidea("Q-07", "D", ["H-01"], 3), qidea("Q-08", "E", ["H-02"], 3),
                               qidea("Q-09", "F", ["HP-01"], 3)]
        truth = {"Q-01": 3, "Q-02": 3.5, "Q-03": 3, "Q-04": 3.5, "Q-05": 3, "Q-06": 3.5, "Q-07": 3, "Q-08": 3,
                 "Q-09": 3}
        gpt = [blind(i, v) for i, v in sorted(truth.items())]
        claude = [blind(i, v + 2 if i in ("Q-01", "Q-03", "Q-05") else v) for i, v in sorted(truth.items())]
        self.setup_run(ideas, {"claude": claude, "gpt": gpt})
        quiet(bs.quick_pick, self.run)
        fin = self.r("quick/finalists.json")
        self.assertEqual(fin["lowered"], {"claude": 2.0})
        self.assertEqual(self.finalists(), ["Q-02", "Q-04", "Q-06", "Q-07", "Q-08"])
        self.assertEqual([g["judge"] for g in fin["own_origin_gap"] if g["flag"]], ["claude"])

    def test_gates_follow_the_screens_k1_rule(self):
        ideas = self.pool() + [qidea("Q-07", "D", ["QA-05"], 4, gates=(False, True, True)),
                               qidea("Q-08", "E", ["QB-04"], 4), qidea("Q-09", "F", ["QB-05"], 4)]
        claude = [blind(i, 3) for i in ("Q-01", "Q-02", "Q-03", "Q-04", "Q-05", "Q-06", "Q-07")]
        gpt = [blind(i, 3) for i in ("Q-01", "Q-02", "Q-03", "Q-04", "Q-05", "Q-06", "Q-07")]
        claude.append(blind("Q-08", 3, gates=(True, False, True)))  # two judges fail the same gate: K1
        gpt.append(blind("Q-08", 3, gates=(True, False, True)))
        claude.append(blind("Q-09", 3, gates=(True, True, False)))  # one judge only: a flag
        gpt.append(blind("Q-09", 3))
        self.setup_run(ideas, {"claude": claude, "gpt": gpt})
        quiet(bs.quick_pick, self.run)
        fin = self.r("quick/finalists.json")
        # the curator's failed gate alone no longer drops Q-07 (the blind judges both passed it): it is flagged
        self.assertEqual(fin["gate_failed"], ["Q-08"])
        self.assertEqual(sorted(fin["gate_flagged"]), ["Q-07", "Q-09"])

    def test_with_one_blind_judge_the_curator_is_the_second_gate_voter(self):
        ideas = [qidea("Q-01", "A", ["QA-01"], 3, gates=(False, True, True)), qidea("Q-02", "B", ["QB-01"], 3),
                 qidea("Q-03", "C", ["QB-02"], 3), qidea("Q-04", "D", ["QA-02"], 3)]
        rows = [blind("Q-01", 3, gates=(False, True, True)), blind("Q-02", 3, gates=(False, True, True)),
                blind("Q-03", 4), blind("Q-04", 4)]
        self.setup_run(ideas, {"gpt": rows}, judges=("claude", "gpt"))
        quiet(bs.quick_pick, self.run)
        fin = self.r("quick/finalists.json")
        self.assertEqual(fin["gate_failed"], ["Q-01"])       # the judge and the curator both failed g1
        self.assertEqual(fin["gate_flagged"], ["Q-02"])      # the judge alone
        self.assertIn("one blind judge (gpt) scored the ideas", " ".join(fin["notes"]))

    def test_curator_scores_are_flagged(self):
        # a one-family run (or --scores curator) keeps the curator's scores, and says so
        judge = [blind(i, 5 if i in ("Q-02", "Q-04", "Q-06") else 1) for i in ("Q-01", "Q-02", "Q-03", "Q-04",
                                                                               "Q-05", "Q-06")]
        self.setup_run(self.pool(), {"claude": judge, "gpt": judge})
        p = self.cli("quick-pick", self.run, "--scores", "curator")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(self.finalists(), ["Q-01", "Q-03", "Q-05"])
        fin = self.r("quick/finalists.json")
        self.assertEqual(fin["scoring"], "curator")
        self.assertIn(bs.CURATOR_SCORES_NOTE, fin["notes"])
        self.assertIn("No blind quick screen ran", self.r("quick/screen.md"))

    def test_blind_scores_are_required_when_asked_for(self):
        self.setup_run(self.pool())
        p = self.cli("quick-pick", self.run, "--scores", "blind")
        self.assertEqual(p.returncode, 4)
        self.assertIn(b"no blind quick-screen scores", p.stderr)
        self.assertFalse(os.path.exists(os.path.join(self.run, "quick", "finalists.json")))
        p = self.cli("quick-pick", self.run)  # auto: no screen outputs, so the curator's scores, flagged
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(self.r("quick/finalists.json")["scoring"], "curator")

    def test_the_screen_itself_is_unchanged_by_the_shared_scoring(self):
        # centered_means is the screen's own code, moved: the screen's scores for the same records are the quick
        # pick's
        judge = [blind("Q-01", 3), blind("Q-02", 5), blind("Q-03", 3), blind("Q-04", 4), blind("Q-05", 2),
                 blind("Q-06", 4)]
        other = [blind(r["id"], min(5, r["c"]["Value"] + 1)) for r in judge]
        self.setup_run(self.pool(), {"claude": judge, "gpt": other})
        quiet(bs.quick_pick, self.run)
        picked = dict((f["id"], f["score"]) for f in self.r("quick/finalists.json")["finalists"])
        self.w("origins.json", self.r("origins.json"))
        self.w("clusters.json", dict((i["id"], i["cluster"]) for i in self.pool()))
        self.w("screen/ideas.md", "".join("%s | t | p | m\n" % i["id"] for i in self.pool()))
        quiet(bs.screen, self.run)
        scores = self.r("screen/shortlist.json")["scores"]
        for iid, score in picked.items():
            self.assertAlmostEqual(scores[iid], score)


class QuickScreenEngineTests(tl.EngineTestCase):
    def quick_ctx(self, families=("claude", "gpt"), deps=None, run_name="2026-09-26-f1-qs"):
        ctx = self.make_ctx(mode="quick", families=families, deps=deps, run_name=run_name)
        ctx.write_json("criteria.json", CRIT)
        ctx.write_json("pool/_families.json", {"QA": ctx.host_family, "QB": (ctx.seats.get("others") or
                                                                          [ctx.host_family + "-alt"])[0]})
        return ctx

    def curated(self, ctx, title="Shared swap board"):
        ctx.write_json("quick/curated.json", {"ideas": [
            qidea("Q-01", "A", ["QA-01"], 4), qidea("Q-02", "B", ["QB-01"], 3), qidea("Q-03", "C", ["QA-02"], 3)]})
        cur = ctx.read_json("quick/curated.json", {})
        cur["ideas"][0]["title"] = title
        ctx.write_json("quick/curated.json", cur)

    def test_seats_and_plan(self):
        ctx = self.quick_ctx(families=("claude", "gpt", "kimi"))
        # both quick generator families, and kimi, which generated nothing, as a neutral third judge
        self.assertEqual(ctx.seats["screen_judges"], ["claude", "gpt", "kimi"])
        self.assertEqual(ctx.seats["tournament_judges"], ["gpt"])
        steps = [i["id"] for i in pipeline.simulate(ctx)]
        self.assertEqual(steps[:4], ["Q.2", "Q.3", "Q.3s", "9.4"])
        plan = ub.cmd_plan(ub.build_parser().parse_args(["plan", "--mode", "quick", "--families", "claude,gpt,kimi"]))
        self.assertEqual(plan["calls"]["expected"], 16)
        one = self.quick_ctx(families=("claude",), run_name="2026-09-26-f1-one")
        self.assertFalse(seats.quick_screen_ok(one.seats))
        self.assertNotIn("Q.3s", [i["id"] for i in pipeline.simulate(one)])
        plan = ub.cmd_plan(ub.build_parser().parse_args(["plan", "--mode", "quick", "--families", "claude"]))
        self.assertEqual(plan["calls"]["expected"], 13)

    def test_the_prompts_are_blind_and_shuffled_per_judge(self):
        ctx = self.quick_ctx(deps=tl.FakeDeps(bs=tl.real_bs))
        st.save(ctx.run_dir, ctx.state)  # bs.py prepare-screen reads the seats from run.json
        self.curated(ctx)
        registry.SCRIPTS["prepare_quick_screen"](ctx, {"id": "Q.3p"})
        self.assertEqual(ctx.read("screen/ideas.md").split("\n")[0],
                         "Q-01 | Shared swap board | pitch Q-01 | mechanism Q-01")
        jobs = builders.build_jobs(ctx, {"id": "Q.3s", "fanout": "screen_judges", "job": {"kind": "judge"}})
        self.assertEqual(sorted(j["family"] for j in jobs), ["claude", "gpt"])
        for j in jobs:
            prompt = ctx.read(j["prompt_file"])
            self.assertIn("without source labels", prompt)
            self.assertNotRegex(prompt, r"\bQ[AB]-\d+\b")
            self.assertNotIn("claude", prompt.lower())
            self.assertEqual(sorted(j["contract"]["cover"]["ids"]), ["Q-01", "Q-02", "Q-03"])

    def test_a_line_naming_a_generator_idea_is_refused(self):
        ctx = self.quick_ctx(deps=tl.FakeDeps(bs=tl.real_bs))
        self.curated(ctx, title="Shared swap board (from QB-01)")
        with self.assertRaises(privacy.PolicyBlock) as cm:
            registry.SCRIPTS["prepare_quick_screen"](ctx, {"id": "Q.3p"})
        self.assertEqual(cm.exception.rule, "origin_label_check")
        self.assertIn("QB-01", str(cm.exception))
        self.assertFalse(ctx.exists("screen/ideas.md"))

    def test_quick_pick_asks_for_the_blind_scores_only_after_the_quick_screen(self):
        fake = tl.FakeBs()
        ctx = self.quick_ctx(deps=tl.FakeDeps(bs=fake))
        st.set_step(ctx.state, "Q.3s", "done")
        registry.SCRIPTS["quick_pick"](ctx, {"id": "Q.4"})
        self.assertEqual(fake.calls[-1], ["quick-pick", ctx.run_dir, "--scores", "blind"])
        self.assertNotIn(registry.QUICK_CURATOR_NOTE, ctx.state.get("notes") or [])
        one = self.quick_ctx(families=("claude",), deps=tl.FakeDeps(bs=fake), run_name="2026-09-26-f1-one")
        st.set_step(one.state, "Q.3s", "skipped")
        registry.SCRIPTS["quick_pick"](one, {"id": "Q.4"})
        self.assertEqual(fake.calls[-1], ["quick-pick", one.run_dir, "--scores", "curator"])
        self.assertIn(registry.QUICK_CURATOR_NOTE, one.state["notes"])

    def test_a_run_past_the_quick_pick_skips_the_quick_screen(self):
        # an in-flight run (or a migrated v1 run) whose quick pick is done never scores its ideas after the fact
        ctx = self.quick_ctx()
        for sid in ("0.1", "0.2", "0.3", "2.1k", "2.2", "Q.2", "Q.3", "Q.4"):
            st.set_step(ctx.state, sid, "done")
        cur = pipeline.current_step(ctx, pipeline.load_steps())
        self.assertNotIn(cur["id"], ("Q.3p", "Q.3s"))
        self.assertEqual((st.step_state(ctx.state, "Q.3p"), st.step_state(ctx.state, "Q.3s")),
                         ("skipped", "skipped"))

    def test_a_two_family_run_scores_blind_end_to_end(self):
        if not tl.stubs_available():
            self.skipTest("tests/harness/stubs.py not present")
        ctx = tl.full_auto_ctx(self, mode="quick", families=("claude", "gpt"))
        card = tl.drive(ctx)
        self.assertEqual(card["type"], "DONE", card.get("say"))
        self.assertEqual(st.step_state(ctx.state, "Q.3s"), "done")
        self.assertEqual(sorted(ctx.state["steps"]["Q.3s"]["jobs"]), ["Q.3s-claude", "Q.3s-gpt"])
        fin = ctx.read_json("quick/finalists.json", {})
        self.assertEqual(fin["scoring"], "blind")
        self.assertTrue(ctx.exists("screen/claude.out.json") and ctx.exists("screen/gpt.out.json"))

    def test_a_one_family_run_keeps_the_curator_scores_flagged(self):
        if not tl.stubs_available():
            self.skipTest("tests/harness/stubs.py not present")
        ctx = tl.full_auto_ctx(self, mode="quick", families=("claude",))
        card = tl.drive(ctx)
        self.assertEqual(card["type"], "DONE", card.get("say"))
        self.assertEqual(st.step_state(ctx.state, "Q.3s"), "skipped")
        self.assertEqual(ctx.read_json("quick/finalists.json", {})["scoring"], "curator")
        self.assertIn(registry.QUICK_CURATOR_NOTE, ctx.state["notes"])


if __name__ == "__main__":
    unittest.main()
