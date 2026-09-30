"""Phase V (VB) pins for 2.1.0 claims that held but had no test: Alternatives considered lists each veto reason once,
`uninstall` never reads a command that could not start as 'not installed', and the removed budget, counter, predicates
and `{item.x}` templating stay removed. No model call, no real CLI."""

import contextlib
import importlib.util
import io
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fixtures", "engine"))
import engine_testlib as tl  # noqa: E402
import bs  # noqa: E402  (the scripts folder is on sys.path through engine_testlib)
from ublib.engine import gates, registry, render_arch  # noqa: E402
from ublib.engine import state as st  # noqa: E402

CRITERIA = ["QG1", "time_to_mvp", "team_fit", "run_cost", "reversibility", "operational_simplicity"]


class VetoReasonsOnceTests(tl.EngineTestCase):
    def cand(self, label, score):
        return {"label": label, "veto": True, "veto_reason": "violates HC-%s" % label, "sensitivity_points": [],
                "tradeoff_points": [], "scores": [{"criterion": c, "score": score, "reason": "r"} for c in CRITERIA]}

    def test_every_judge_vetoing_with_one_reason_gives_it_once(self):
        ctx = self.make_ctx(families=("claude", "gpt", "kimi"), autopilot="full-auto", run_name="2026-09-28-vb-arch")
        st.save(ctx.run_dir, ctx.state)
        ctx.write_json("10_ARCHITECTURE/drivers.json", {"product_goal": "x", "quality_goals": [
            {"id": "QG1", "name": "Reliability", "weight": 30}]})
        ctx.write_json("10_ARCHITECTURE/candidates/map.json", dict(
            (k, {"family": f, "archetype": k, "job": "12.4-" + k}) for k, f in (("A", "claude"), ("B", "gpt"),
                                                                                 ("C", "kimi"))))
        for fam in ("claude", "gpt", "kimi"):
            ctx.write_json("10_ARCHITECTURE/review/judge_%s.out.json" % fam, {
                "candidates": [self.cand("A", 3), self.cand("B", 4), self.cand("C", 2)], "steal": []})
        with contextlib.redirect_stdout(io.StringIO()):
            bs.arch_matrix(ctx.run_dir)
        gates.apply(ctx, "G11", {"accept_recommendation": True}, by="auto")
        render_arch.write_readme(ctx)
        alts = ctx.read("10_ARCHITECTURE/README.md").split("### Alternatives considered", 1)[1].split("\n## ", 1)[0]
        for label in ("A", "C"):
            with self.subTest(label):
                row = [ln for ln in alts.split("\n") if ln.startswith("| %s " % label)]
                self.assertEqual(len(row), 1, alts)
                self.assertEqual(row[0].count("violates HC-%s" % label), 1, row[0])


class UninstallNativeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location("ub_install_vb", os.path.join(tl.KIT, "install", "install.py"))
        cls.inst = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.inst)

    def uninstall(self, rc, err):
        row = {"_native_agent": "claude-code", "commands": [["claude", "plugin", "uninstall", "x"]],
               "_entry": {"k": 1}}
        updates, result = {"remove_entries": []}, {"commands": []}
        with mock.patch.object(self.inst, "run_logged", return_value=(rc, "", err)), \
                mock.patch.object(self.inst, "entry_key", return_value="k"):
            ok = self.inst.do_uninstall_native(None, row, updates, result)
        return ok, updates["remove_entries"]

    def test_a_command_that_could_not_start_is_a_failure(self):
        self.assertEqual(self.uninstall(None, "No such file or directory\ntimed out after 60s"), (False, []))

    def test_a_cli_that_says_not_installed_counts_as_removed(self):
        self.assertEqual(self.uninstall(1, "Plugin x is not installed"), (True, ["k"]))
        self.assertEqual(self.uninstall(0, ""), (True, ["k"]))


class RemovedStaysRemovedTests(unittest.TestCase):
    def test_no_budget_counter_predicate_or_item_templating_is_left(self):
        for name in ("always", "mode_in", "variant_in", "autopilot_is", "privacy_web", "survivors_lt", "gate_asked"):
            self.assertNotIn(name, registry.PREDICATES)
        skill = os.path.join(tl.KIT, "skills", "ultimate-brainstorm")
        hits = []
        for folder, dirs, files in os.walk(skill):
            dirs[:] = [d for d in dirs if d != "__pycache__"]
            for f in files:
                with open(os.path.join(folder, f), "rb") as fh:
                    data = fh.read()
                hits += ["%s: %s" % (f, w) for w in ("max_usd", "g2c_loops", "{item.") if w.encode() in data]
        self.assertEqual(hits, [])


if __name__ == "__main__":
    unittest.main()
