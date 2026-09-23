"""bs.py arch-matrix (KIT_SPEC 5.7, 7.2 step 12.7)."""

import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

_KIT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_SCRIPTS = os.path.join(_KIT, "skills", "ultimate-brainstorm", "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

import bs  # noqa: E402

QGS = [{"id": "QG1", "name": "Reliability", "weight": 30, "why": "w", "source": "STATED"},
       {"id": "QG2", "name": "Privacy", "weight": 25, "why": "w", "source": "STATED"},
       {"id": "QG3", "name": "Latency", "weight": 15, "why": "w", "source": "ASSUMPTION"}]
CRITERIA = ["QG1", "QG2", "QG3", "time_to_mvp", "team_fit", "run_cost", "reversibility", "operational_simplicity"]


def cand(label, score, veto=False, reason="", overrides=None, sens=(), trade=()):
    s = {c: score for c in CRITERIA}
    s.update(overrides or {})
    return {"label": label, "veto": veto, "veto_reason": reason,
            "scores": [{"criterion": c, "score": v, "reason": "r"} for c, v in s.items()],
            "sensitivity_points": list(sens), "tradeoff_points": list(trade), "risks": [], "non_risks": []}


class ArchMatrixTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ub-bs-arch-")
        self.run = os.path.join(self.tmp, "brainstorm", "2026-09-23-arch")
        self.arch = os.path.join(self.run, "10_ARCHITECTURE")
        os.makedirs(os.path.join(self.arch, "review"))
        os.makedirs(os.path.join(self.arch, "candidates"))
        self.drivers(QGS)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def drivers(self, qgs):
        with open(os.path.join(self.arch, "drivers.json"), "w") as f:
            json.dump({"product_goal": "x", "quality_goals": qgs}, f)

    def cmap(self, authors):
        with open(os.path.join(self.arch, "candidates", "map.json"), "w") as f:
            json.dump({k: {"family": v, "archetype": "A", "job": "12.4-" + k} for k, v in authors.items()}, f)

    def judge(self, fam, cands, steal=()):
        with open(os.path.join(self.arch, "review", "judge_%s.out.json" % fam), "w") as f:
            json.dump({"candidates": cands, "steal": list(steal), "confidence": 0.7}, f)

    def matrix(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            bs.arch_matrix(self.run)
        with open(os.path.join(self.arch, "matrix.json"), encoding="utf-8") as f:
            m = json.load(f)
        with open(os.path.join(self.arch, "tradeoff-matrix.md"), encoding="utf-8") as f:
            md = f.read()
        return m, {c["label"]: c for c in m["candidates"]}, md

    def test_own_family_exclusion_and_shape(self):
        self.cmap({"A": "gpt", "B": "kimi", "C": "claude"})
        self.judge("claude", [cand("A", 4), cand("B", 3), cand("C", 5)])
        self.judge("gpt", [cand("A", 5), cand("B", 3), cand("C", 2)])
        self.judge("kimi", [cand("A", 4), cand("B", 5), cand("C", 2)])
        m, c, md = self.matrix()
        self.assertEqual(c["A"]["judges"], ["claude", "kimi"])   # gpt wrote A
        self.assertEqual(c["B"]["judges"], ["claude", "gpt"])
        self.assertEqual(c["C"]["judges"], ["gpt", "kimi"])
        self.assertEqual(c["A"]["score"], 4.0)
        self.assertEqual(c["C"]["score"], 2.0)                  # claude's own 5s are ignored
        self.assertEqual(m["leader"], "A")
        self.assertEqual(m["leader_status"], "clear")
        self.assertEqual(c["A"]["range"], [1, 1])
        self.assertEqual([x["id"] for x in m["criteria"]], CRITERIA)
        self.assertEqual(sum(x["weight"] for x in m["criteria"]), 100)
        self.assertEqual(set(c["A"]), {"label", "score", "rank", "range", "veto", "veto_reasons", "means", "judges",
                                       "disagreements"})
        self.assertEqual(set(m), {"criteria", "candidates", "leader", "leader_status", "steal", "warnings"})
        self.assertEqual(m["warnings"], [])
        # the markdown never names the authors' families
        for fam in ("claude", "gpt", "kimi"):
            self.assertNotIn(fam, md)
        self.assertIn("Leader: A (clear", md)
        self.assertIn("| QG1 | Reliability | 30 |", md)
        self.assertIn("| time_to_mvp | Time to MVP | 10 |", md)

    def test_sole_judge_fallback(self):
        self.cmap({"A": "claude", "B": "gpt"})
        self.judge("claude", [cand("A", 4), cand("B", 3)])
        m, c, md = self.matrix()
        self.assertEqual(c["A"]["judges"], ["claude"])  # nobody else judged: all judges used
        self.assertIn("candidate A: no judge from another family; all judges used", m["warnings"])
        self.assertEqual(c["B"]["judges"], ["claude"])
        self.assertIn("no judge from another family", md)

    def test_alt_family_counts_as_own(self):
        self.cmap({"A": "claude", "B": "gpt"})
        self.judge("claude-alt", [cand("A", 5), cand("B", 3)])
        self.judge("gpt", [cand("A", 2), cand("B", 5)])
        m, c, _md = self.matrix()
        self.assertEqual(c["A"]["judges"], ["gpt"])
        self.assertEqual(c["B"]["judges"], ["claude-alt"])

    def test_veto_semantics(self):
        self.cmap({"A": "glm", "B": "glm", "C": "glm", "D": "kimi"})
        self.judge("claude", [cand("A", 3), cand("B", 5, True, "breaks HC-1"), cand("C", 4), cand("D", 3)])
        self.judge("gpt", [cand("A", 3), cand("B", 5, True, "no offline mode"), cand("C", 4, True, "cost"),
                           cand("D", 3)])
        self.judge("kimi", [cand("A", 3), cand("B", 5), cand("C", 4), cand("D", 5, True, "vendor lock")])
        m, c, md = self.matrix()
        self.assertEqual(c["B"]["veto"], "excluded")            # 2 judges
        self.assertIsNone(c["B"]["rank"])
        self.assertIsNone(c["B"]["range"])
        self.assertEqual(c["B"]["veto_reasons"], ["breaks HC-1", "no offline mode"])
        self.assertEqual(c["C"]["veto"], "flagged")             # 1 of 3 eligible
        self.assertEqual(c["C"]["veto_reasons"], ["cost"])
        self.assertEqual(c["D"]["veto"], "none")                # kimi's own-candidate veto does not count
        self.assertEqual(m["leader"], "C")                      # B scores higher but is excluded
        self.assertIn("- B: EXCLUDED (2 judges)", md)
        self.assertIn("- C: FLAGGED (1 judge)", md)

    def test_only_eligible_judge_veto_flags_with_note(self):
        self.cmap({"A": "claude", "B": "gpt"})
        self.judge("claude", [cand("A", 3), cand("B", 4, True, "misses QAS-01")])
        self.judge("gpt", [cand("A", 4), cand("B", 5)])
        m, c, _md = self.matrix()
        self.assertEqual(c["B"]["judges"], ["claude"])
        self.assertEqual(c["B"]["veto"], "flagged")
        self.assertIn("single-judge veto: the human decides", c["B"]["veto_reasons"])

    def test_rank_ranges_and_close_call(self):
        self.cmap({"A": "gpt", "B": "kimi"})
        # A is better on QG1, B on QG2; the totals are close, so weight changes swap the leader
        self.judge("claude", [cand("A", 3, overrides={"QG1": 5, "QG2": 2}),
                              cand("B", 3, overrides={"QG1": 2, "QG2": 5})])
        m, c, md = self.matrix()
        self.assertEqual(m["leader"], "A")
        self.assertEqual(m["leader_status"], "close-call")
        self.assertEqual(c["A"]["range"], [1, 2])
        self.assertEqual(c["B"]["range"], [1, 2])
        self.assertIn("Leader: A (close-call: B can also rank 1)", md)

    def test_disagreements_and_merged_points(self):
        self.cmap({"A": "glm", "B": "glm"})
        self.judge("claude", [cand("A", 4, overrides={"QG2": 1}, sens=["DB choice"], trade=["cost vs speed"]),
                              cand("B", 3)])
        self.judge("gpt", [cand("A", 4, overrides={"QG2": 4}, sens=["db choice", "queue depth"]), cand("B", 3)])
        m, c, md = self.matrix()
        self.assertEqual(c["A"]["disagreements"], ["QG2"])
        self.assertEqual(c["A"]["means"]["QG2"], 2.5)
        self.assertEqual(c["B"]["disagreements"], [])
        self.assertIn("- A: DB choice", md)
        self.assertIn("- A: queue depth", md)
        self.assertNotIn("- A: db choice", md)                  # merged case-insensitively
        self.assertIn("- A: cost vs speed", md)

    def test_steal_merge(self):
        self.cmap({"A": "gpt", "B": "kimi", "C": "glm"})
        self.judge("claude", [cand("A", 4), cand("B", 3), cand("C", 2)],
                   steal=[{"from": "B", "element": "Outbox pattern", "why": "exactly-once"},
                          {"from": "C", "element": "cold storage tier", "why": "cost"}])
        self.judge("glm", [cand("A", 4), cand("B", 3), cand("C", 2)],
                   steal=[{"from": "B", "element": "outbox  pattern", "why": "dup"},
                          {"from": "Z", "element": "ghost", "why": "unknown label"},
                          {"from": "A", "element": "Feature flags", "why": "rollout"}])
        m, c, md = self.matrix()
        self.assertEqual(m["steal"], [{"from": "A", "element": "Feature flags", "why": "rollout"},
                                      {"from": "B", "element": "Outbox pattern", "why": "exactly-once"},
                                      {"from": "C", "element": "cold storage tier", "why": "cost"}])
        self.assertTrue(any("unknown candidate 'Z'" in w for w in m["warnings"]))
        self.assertIn("- from B: Outbox pattern (exactly-once)", md)

    def test_bad_scores_and_weights_warn(self):
        self.drivers([{"id": "QG1", "name": "R", "weight": 40}, {"id": "QG2", "name": "P", "weight": 20}])
        self.cmap({"A": "gpt", "B": "kimi"})
        a = cand("A", 4)
        a["scores"].append({"criterion": "QG9", "score": 5, "reason": "?"})
        a["scores"][0]["score"] = 9
        self.judge("claude", [a, cand("B", 3), cand("X", 5)])
        m, c, _md = self.matrix()
        w = " | ".join(m["warnings"])
        self.assertIn("sum to 60, not 70", w)
        self.assertIn("unknown criterion 'QG9'", w)
        self.assertIn("outside 1-5", w)
        self.assertIn("unknown candidate 'X'", w)
        self.assertNotIn("QG1", c["A"]["means"])

    def test_cli_exit_codes(self):
        env = dict(os.environ, PYTHONIOENCODING="utf-8")
        cmd = [sys.executable, os.path.join(_SCRIPTS, "bs.py"), "arch-matrix", self.run]
        p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
        self.assertEqual(p.returncode, 4)  # map.json missing
        self.cmap({"A": "gpt", "B": "kimi"})
        p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
        self.assertEqual(p.returncode, 4)  # no judge outputs
        self.judge("claude", [cand("A", 4), cand("B", 3)])
        p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.drivers([])
        p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
        self.assertEqual(p.returncode, 5)


if __name__ == "__main__":
    unittest.main()
