"""tools/eval.py (finding 83): offline aggregation of finished run folders - per-strategy and per-family yield,
strategy x family confounding, Kendall's W, position consistency and self-preference estimates."""

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

_KIT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_EVAL = os.path.join(_KIT, "tools", "eval.py")
_spec = importlib.util.spec_from_file_location("ub_eval", _EVAL)
ev = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ev)

CRIT = {"Value": 60, "Feasibility": 40}


class EvalTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ub-wp4-eval-")
        self.root = os.path.join(self.tmp, "brainstorm")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def w(self, run, rel, obj):
        p = os.path.join(self.root, run, *rel.split("/"))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8", newline="\n") as f:
            f.write(obj if isinstance(obj, str) else json.dumps(obj))

    def make_run(self, run, s3_family, chosen, gpt_reverses=False):
        """Three canonical ideas: I-001 from S3 (s3_family), I-002 from S1 (claude), I-003 merged S1 + S3."""
        self.w(run, "run.json", {"schema": 2, "mode": "standard", "status": "done", "host": {"family": "claude"},
                                 "seats": {"generators": {"S1": "claude", "S3": s3_family}, "rotation": 0},
                                 "finalists": ["I-001", "I-002", "E-01"], "choice": {"idea": chosen}})
        self.w(run, "ideas.json", {
            "I-001": {"key": "a", "strategies": ["S3"], "families": [s3_family], "origin": s3_family, "cluster": "x"},
            "I-002": {"key": "b", "strategies": ["S1"], "families": ["claude"], "origin": "claude", "cluster": "y"},
            "I-003": {"key": "c", "strategies": ["S1", "S3"], "families": ["claude", s3_family],
                      "origin": "ai-mixed", "cluster": "y"}})
        self.w(run, "05_EVOLVED.md", "# EVOLVED\n\n### E-01 Hybrid\n- Parents: I-001, I-002\n")
        self.w(run, "checks/E-01.md", "## 1\nx\nVERDICT: ADJACENT; DIFFERENTIATOR: y\n")
        self.w(run, "screen/shortlist.json", {"shortlist": [{"id": "I-001"}, {"id": "I-002"}],
                                              "own_origin_gap": [{"judge": "claude", "gap": 0.4, "n": 3}]})
        self.w(run, "criteria.json", CRIT)
        rows = [("I-001", 5, 4), ("I-002", 3, 3), ("I-003", 2, 1)]
        for judge in ("claude", "gpt"):
            order = rows[::-1] if (judge == "gpt" and gpt_reverses) else rows
            self.w(run, "screen/%s.out.json" % judge, {"scores": [
                {"id": i, "c": {"Value": v, "Feasibility": f}} for (i, _v, _f), (_i, v, f) in zip(rows, order)]})
        self.w(run, "tournament/result.json", {
            "debiased": [{"id": "I-001", "pct": 80.0}, {"id": "E-01", "pct": 50.0}, {"id": "I-002", "pct": 20.0}],
            "consistency": {"claude": 1.0, "gpt": 0.5}, "ranking": {"method": "bradley-terry"},
            "audit": [{"judge": "claude", "diff": 0.2}]})

    def test_aggregate_over_runs(self):
        self.make_run("2026-09-26-a", "gpt", "I-001")
        self.make_run("2026-09-26-b", "kimi", "I-002", gpt_reverses=True)
        agg = ev.aggregate([ev.one_run(r) for r in ev.run_folders([self.root])])
        self.assertEqual(agg["runs"], ["2026-09-26-a", "2026-09-26-b"])
        s3, s1 = agg["strategies"]["S3"], agg["strategies"]["S1"]
        self.assertEqual((s3["credited"], s3["shortlisted"], s3["finalists"], s3["chosen"]), (4, 2, 2, 1))
        self.assertEqual(s3["survival"], 0.5)
        self.assertEqual(s3["win_rate"], 0.5)
        self.assertEqual(s3["mean_score"], 80.0)
        self.assertEqual((s1["finalists"], s1["chosen"]), (2, 1))
        self.assertEqual(agg["strategies"]["E"]["finalists"], 2)
        self.assertEqual(agg["families"]["gpt"]["credited"], 2)
        self.assertEqual(agg["cells"]["S3|kimi"]["chosen"], 0)
        # S3 ran on gpt in one run and kimi in the other; S1 and E only ever ran on claude
        self.assertEqual(agg["confounded_strategies"], ["E", "S1"])
        w = agg["judges"]["kendall_w"]
        self.assertEqual(w["per_run"]["2026-09-26-a"]["screen"], 1.0)
        self.assertEqual(w["per_run"]["2026-09-26-b"]["screen"], 0.0)
        self.assertEqual(w["screen"], 0.5)
        self.assertEqual(agg["judges"]["position_consistency"], {"claude": 1.0, "gpt": 0.5})
        self.assertEqual(agg["judges"]["self_preference"], {"tournament": {"claude": 0.2},
                                                            "screen": {"claude": 0.4}})
        md = ev.markdown(agg)
        self.assertIn("| S3 | 4 | 2 | 2 | 1 | 50% | 50% | 50% | 80.0 |", md)
        self.assertIn("(yield confounded with that family): E, S1", md)

    def test_kendall_w(self):
        same = {"a": {"x": 3, "y": 2, "z": 1}, "b": {"x": 30, "y": 20, "z": 10}}
        self.assertEqual(ev.kendall_w(same), 1.0)
        self.assertEqual(ev.kendall_w({"a": {"x": 1, "y": 2}, "b": {"x": 2, "y": 1}}), 0.0)
        self.assertIsNone(ev.kendall_w({"a": {"x": 1, "y": 2}}))

    def test_cli(self):
        self.make_run("2026-09-26-a", "gpt", "I-001")
        out = os.path.join(self.tmp, "eval.json")
        p = subprocess.run([sys.executable, _EVAL, os.path.join(self.root, "2026-09-26-a"), "--json", "--out", out],
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.assertEqual(p.returncode, 0, p.stderr)
        data = json.loads(p.stdout.decode("ascii"))
        self.assertEqual(data["runs"], ["2026-09-26-a"])
        with open(out, encoding="utf-8") as f:
            self.assertEqual(json.load(f), data)
        p = subprocess.run([sys.executable, _EVAL, self.tmp], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.assertEqual(p.returncode, 4)


if __name__ == "__main__":
    unittest.main()
