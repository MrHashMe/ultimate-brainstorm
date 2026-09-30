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
        # per-judge centering: claude's mean is 4, gpt's 3.33, kimi's 3.67 (panel 3.67). A = (claude 4 - 0.33 +
        # kimi 4 + 0) / 2; C = (gpt 2 + 0.33 + kimi 2 + 0) / 2, and claude's own 5s are ignored
        self.assertEqual(c["A"]["score"], 3.83)
        self.assertEqual(c["C"]["score"], 2.17)
        self.assertEqual(m["judge_offsets"], {"claude": 0.33, "gpt": -0.33, "kimi": 0.0})
        self.assertEqual(m["leader"], "A")
        # every judge favours its own family's candidate here (gpt gives its A a 5 where the others give 4); gpt
        # judges the runner-up B but not A, so its centering tilts the A-B comparison: the lead is not clear
        self.assertEqual(m["leader_status"], "close-call")
        self.assertEqual(dict((g["judge"], g["flag"]) for g in m["own_candidate_gap"]),
                         {"claude": True, "gpt": True, "kimi": True})
        self.assertEqual(c["A"]["range"], [1, 1])
        self.assertEqual([x["id"] for x in m["criteria"]], CRITERIA)
        self.assertEqual(sum(x["weight"] for x in m["criteria"]), 100)
        self.assertEqual(set(c["A"]), {"label", "score", "rank", "range", "veto", "veto_reasons", "means", "judges",
                                       "disagreements"})
        self.assertEqual(set(m), {"criteria", "candidates", "leader", "leader_status", "steal", "warnings", "design",
                                  "judge_offsets", "self_judged", "own_candidate_gap", "own_candidate_pairs"})
        self.assertEqual(m["design"], {"confounded": False, "judges": "eligible"})  # every pair shares a judge
        self.assertEqual(m["warnings"], [])
        self.assertEqual(m["self_judged"], [])
        # the markdown never names the authors' families
        for fam in ("claude", "gpt", "kimi"):
            self.assertNotIn(fam, md)
        self.assertIn("Leader: A (close-call: a judge that favours its own family's candidate", md)
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
        self.assertEqual(c["D"]["veto"], "flagged")             # kimi vetoes its own candidate: admission against
        self.assertEqual(c["D"]["veto_reasons"], ["vendor lock"])  # interest, so it counts (finding 81)
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

    def test_labels_are_compared_as_the_cover_compares_them(self):
        # a host sub-agent's file keeps the label as written; the contract accepted "B" + U+200B as candidate B
        self.cmap({"A": "gpt", "B": "kimi"})
        self.judge("claude", [cand("A", 4), cand("B​", 2)])
        m, c, _md = self.matrix()
        self.assertEqual(c["B"]["judges"], ["claude"])
        self.assertFalse(any("unknown candidate" in w for w in m["warnings"]))

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

    def test_leniency_offset_is_not_a_clear_lead(self):
        # findings 46/81: two families judge each other's candidates, so A and C (gpt) are scored only by claude and
        # B (claude) only by gpt. Both judges rank A first on their own scale; gpt is one point more lenient. The
        # raw means made B the leader, "clear"
        self.cmap({"A": "gpt", "B": "claude", "C": "gpt"})
        self.judge("claude", [cand("A", 3, overrides={"QG1": 4}), cand("B", 3), cand("C", 3)])
        self.judge("gpt", [cand("A", 4, overrides={"QG1": 5}), cand("B", 4), cand("C", 4)])
        m, c, md = self.matrix()
        self.assertEqual(m["leader"], "A")
        self.assertNotEqual(m["leader_status"], "clear")
        self.assertEqual(m["leader_status"], "confounded")  # A and runner-up B share no eligible judge
        self.assertEqual(m["design"], {"confounded": True, "judges": "all (balanced own-family judges)"})
        self.assertEqual(c["B"]["score"], c["C"]["score"])  # the +1 leniency cancels
        self.assertEqual(m["judge_offsets"], {"claude": -0.5, "gpt": 0.5})
        self.assertTrue(any(w.startswith("confounded design: A and B") for w in m["warnings"]))
        self.assertIn("Leader: A (confounded", md)

    def test_extreme_disjoint_case(self):
        # the audit's case: claude A=3 C=2 B=1, gpt A=5 C=5 B=4; both judges rank B last
        self.cmap({"A": "gpt", "B": "claude", "C": "gpt"})
        self.judge("claude", [cand("A", 3), cand("B", 1), cand("C", 2)])
        self.judge("gpt", [cand("A", 5), cand("B", 4), cand("C", 5)])
        m, c, _md = self.matrix()
        self.assertEqual(c["B"]["rank"], 3)
        self.assertEqual(m["leader"], "A")

    def test_two_vetoes_exclude_with_two_families(self):
        # finding 81: with one eligible judge per candidate, EXCLUDED could never fire; the author family's veto
        # of its own candidate is an admission against interest and counts
        self.cmap({"A": "gpt", "B": "claude"})
        self.judge("claude", [cand("A", 5, True, "breaks HC-1"), cand("B", 3)])
        self.judge("gpt", [cand("A", 5, True, "cannot meet QAS-02"), cand("B", 3)])
        m, c, _md = self.matrix()
        self.assertEqual(c["A"]["veto"], "excluded")
        self.assertEqual(m["leader"], "B")

    def test_exact_tie_is_a_close_call(self):
        self.cmap({"A": "gpt", "B": "kimi"})
        self.judge("claude", [cand("A", 4), cand("B", 4)])
        m, c, md = self.matrix()
        self.assertEqual(c["A"]["range"], [1, 1])
        self.assertEqual(m["leader_status"], "close-call")

    def test_missing_criterion_leaves_w_for_everyone(self):
        self.cmap({"A": "gpt", "B": "kimi"})
        b = cand("B", 4)
        b["scores"] = [s for s in b["scores"] if s["criterion"] != "time_to_mvp"]
        self.judge("claude", [cand("A", 4, overrides={"time_to_mvp": 1}), b])
        m, c, _md = self.matrix()
        self.assertIn("criteria without an eligible judge's score for every ranked candidate are left out of W: "
                      "time_to_mvp", m["warnings"])
        self.assertEqual(c["A"]["score"], c["B"]["score"])  # A's weak time_to_mvp does not count for A alone

    def test_fallback_judge_counts_as_its_family(self):
        # judge_gpt.out.json was written by a claude fallback: its score of the claude candidate is an own score
        self.cmap({"A": "claude", "B": "kimi"})
        self.judge("gpt", [cand("A", 5), cand("B", 3)])
        with open(os.path.join(self.arch, "review", "judge_gpt.out.json.meta.json"), "w") as f:
            json.dump({"family": "claude", "status": "ok"}, f)
        self.judge("kimi", [cand("A", 3), cand("B", 4)])
        m, c, _md = self.matrix()
        self.assertEqual(c["A"]["judges"], ["kimi"])
        self.assertIn("the gpt judge seat was answered by claude (fallback): scored as claude", m["warnings"])

    def test_cli_exit_codes(self):
        env = dict(os.environ, PYTHONIOENCODING="utf-8")
        cmd = [sys.executable, os.path.join(_SCRIPTS, "bs.py"), "arch-matrix", self.run]
        p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, timeout=300)
        self.assertEqual(p.returncode, 4)  # map.json missing
        self.cmap({"A": "gpt", "B": "kimi"})
        p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, timeout=300)
        self.assertEqual(p.returncode, 4)  # no judge outputs
        self.judge("claude", [cand("A", 4), cand("B", 3)])
        p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, timeout=300)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.drivers([])
        p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, timeout=300)
        self.assertEqual(p.returncode, 5)


if __name__ == "__main__":
    unittest.main()
