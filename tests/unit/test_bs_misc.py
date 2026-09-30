"""bs.py quick-pick, split, sources, assumptions and coverage.json (KIT_SPEC 4.10, 5.7, 5.9)."""

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
LINT_GOOD = os.path.join(_KIT, "tests", "fixtures", "lint", "good")
BS = os.path.join(_SCRIPTS, "bs.py")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

import bs  # noqa: E402
from ublib import lints  # noqa: E402

CRIT = {"Value": 30, "Feasibility": 25, "Fit": 20, "Distinctiveness": 15, "Evidence": 10}


def quiet(fn, *args, **kw):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        fn(*args, **kw)
    return buf.getvalue()


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ub-bs-misc-")
        self.run = os.path.join(self.tmp, "brainstorm", "2026-09-23-misc")
        os.makedirs(self.run)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def p(self, rel):
        return os.path.join(self.run, *rel.split("/"))

    def w(self, rel, obj):
        os.makedirs(os.path.dirname(self.p(rel)), exist_ok=True)
        with open(self.p(rel), "w", encoding="utf-8", newline="\n") as f:
            f.write(obj if isinstance(obj, str) else json.dumps(obj))

    def r(self, rel):
        with open(self.p(rel), encoding="utf-8") as f:
            text = f.read()
        return json.loads(text) if rel.endswith(".json") else text

    def cli(self, *args, **kw):
        return subprocess.run([sys.executable, BS] + list(args), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              env=dict(os.environ, PYTHONIOENCODING="utf-8"), cwd=kw.get("cwd", self.tmp))


def qidea(iid, cluster, origin, scores, gates=(True, True, True)):
    return {"id": iid, "title": "Idea %s" % iid, "pitch": "pitch %s" % iid, "mechanism": "mechanism | %s" % iid,
            "cluster": cluster, "origin": origin, "gates": {"g1": gates[0], "g2": gates[1], "g3": gates[2]},
            "scores": [{"criterion": k, "score": v} for k, v in scores.items()],
            "fails_if": "nobody posts", "problem": "swaps take days", "for_whom": "night nurses",
            "first_version": "a shared sheet"}


def sc(value, feas=3, dist=3, fit=3, ev=3):
    return {"Value": value, "Feasibility": feas, "Fit": fit, "Distinctiveness": dist, "Evidence": ev}


class QuickPickTests(Base):
    def test_selection_rules(self):
        self.w("criteria.json", CRIT)
        self.w("quick/curated.json", {"ideas": [
            qidea("Q-01", "A", "claude", sc(5)),
            qidea("Q-02", "A", "gpt", sc(4)),                       # second in cluster A: not picked
            qidea("Q-03", "B", "gpt", sc(3)),
            qidea("Q-04", "C", "claude", sc(5), gates=(True, False, True)),   # gate fail
            qidea("Q-05", "A", "gpt", sc(2, feas=3, dist=5)),        # tail slot
            qidea("Q-06", "D", "human", sc(1)),                      # best of D anyway
            qidea("Q-07", "A", "human-mixed", sc(3)),                # best human-origin (higher than Q-06)
            qidea("Q-08", "E", "gpt", sc(2, feas=2, dist=5)),        # distinct but infeasible
        ]})
        out = quiet(bs.quick_pick, self.run)
        fin = self.r("quick/finalists.json")
        picks = {f["id"]: f["reason"] for f in fin["finalists"]}
        # cluster bests: Q-01 (A), Q-03 (B), Q-06 (D), Q-08 (E); tail Q-05; human Q-07 -> 6 picks. The cap of 5
        # drops the weakest pick that holds no protected slot: Q-06 (weighted 1.9; Q-08 has 2.3)
        self.assertEqual(sorted(picks), ["Q-01", "Q-03", "Q-05", "Q-07", "Q-08"])
        self.assertEqual(picks["Q-05"], "tail slot")
        self.assertEqual(picks["Q-07"], "best human-origin")
        self.assertIn("Q-04", fin["gate_failed"])
        self.assertIn("quick-pick: 5 finalists", out)
        origins = self.r("origins.json")
        self.assertEqual(origins["Q-07"], "human-mixed")
        self.assertEqual(len(origins), 8)
        cards = self.r("tournament/cards.md")
        self.assertEqual(cards.count("\n## ") + cards.startswith("## "), 5)
        self.assertIn("Prior art: NOT CHECKED", cards)
        self.assertIn("Mechanism: mechanism / Q-01", cards)       # pipes cleaned
        self.assertIn("Main risk: nobody posts", cards)
        self.assertNotIn("claude", cards)
        self.assertNotIn("human", cards)
        for line in ("Title:", "Problem:", "Mechanism:", "For whom:", "First version:", "Main risk:", "Prior art:"):
            self.assertEqual(cards.count(line), 5)
        # the cards feed prepare-tournament directly
        self.w("tournament/header.md", "H\n")
        self.w("run.json", {"schema": 2, "mode": "quick", "seats": {"tournament_judges": ["claude"]}})
        quiet(bs.prepare_tournament, self.run)
        self.assertTrue(os.path.exists(self.p("tournament/claude_fwd.prompt.md")))

    def test_needs_two(self):
        self.w("criteria.json", CRIT)
        self.w("quick/curated.json", {"ideas": [qidea("Q-01", "A", "gpt", sc(4)),
                                                qidea("Q-02", "A", "gpt", sc(3), gates=(False, True, True))]})
        p = self.cli("quick-pick", self.run)
        self.assertEqual(p.returncode, 5)
        self.assertIn(b"at least 2", p.stderr)
        self.assertFalse(os.path.exists(self.p("tournament/cards.md")))

    def test_missing_input(self):
        self.assertEqual(self.cli("quick-pick", self.run).returncode, 4)


class SplitTests(Base):
    GOOD = ("=== FILE: chosen/containers.md ===\n# Containers\nbody\n=== END FILE ===\n"
            "=== FILE: chosen/api/openapi.yaml ===\nopenapi: 3.1.0\n=== END FILE ===\n"
            "=== STATUS ===\n{\"status\":\"complete\",\"assumptions\":[\"a\"],\"open_questions\":[],\"reason\":\"\"}\n"
            "=== END STATUS ===\n")

    def split(self, text, *extra, **kw):
        self.w("_raw/out.md", text)
        args = ["split", self.run, "--in", self.p("_raw/out.md"), "--root", kw.get("root", "10_ARCHITECTURE"),
                "--allow", "chosen/*.md", "--allow", "chosen/api/*"] + list(extra)
        return self.cli(*args)

    def arch_files(self):
        out = []
        for dirpath, _d, names in os.walk(self.p("10_ARCHITECTURE")):
            out += [os.path.relpath(os.path.join(dirpath, n), self.run).replace("\\", "/") for n in names]
        return sorted(out)

    def test_ok_with_status(self):
        p = self.split(self.GOOD, "--status-out", "10_ARCHITECTURE/_raw/12.10.status.json")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(self.arch_files(), ["10_ARCHITECTURE/_raw/12.10.status.json",
                                             "10_ARCHITECTURE/chosen/api/openapi.yaml",
                                             "10_ARCHITECTURE/chosen/containers.md"])
        self.assertEqual(self.r("10_ARCHITECTURE/_raw/12.10.status.json")["status"], "complete")
        self.assertIn(b"wrote 2 file(s)", p.stdout)

    def test_input_relative_to_run(self):
        self.w("_raw/rel.md", self.GOOD)
        p = self.cli("split", self.run, "--in", "_raw/rel.md", "--root", "10_ARCHITECTURE", "--allow", "chosen/**")
        self.assertEqual(p.returncode, 0, p.stderr)

    def bad(self, block):
        text = self.GOOD.replace("=== STATUS ===", block + "=== STATUS ===")
        p = self.split(text)
        self.assertEqual(p.returncode, 5, (block, p.stdout, p.stderr))
        self.assertEqual(self.arch_files(), [], "nothing may be written when any block is invalid")
        return p

    def test_path_guards(self):
        self.bad("=== FILE: chosen/../../evil.md ===\nx\n=== END FILE ===\n")
        self.bad("=== FILE: /etc/evil.md ===\nx\n=== END FILE ===\n")
        self.bad("=== FILE: C:/evil.md ===\nx\n=== END FILE ===\n")
        self.bad("=== FILE: chosen/run.py ===\nprint(1)\n=== END FILE ===\n")        # extension
        self.bad("=== FILE: chosen/empty.md ===\n=== END FILE ===\n")                # empty content
        self.bad("=== FILE: docs/other.md ===\nx\n=== END FILE ===\n")               # not in allowlist
        self.bad("=== FILE: chosen/.hidden.md ===\nx\n=== END FILE ===\n")

    def test_a_duplicate_path_is_invalid(self):
        # 4.6 rule 3 (round 3, #40): a path printed twice is ambiguous framing (a quoted FILE marker can frame the
        # second copy), so nothing is written; it was 'the last copy wins' with a warning
        p = self.bad("=== FILE: chosen/containers.md ===\n# Second\n=== END FILE ===\n")
        self.assertIn(b"duplicate FILE block chosen/containers.md", p.stdout + p.stderr)

    def test_usage_and_missing(self):
        p = self.split(self.GOOD, root="../outside")
        self.assertEqual(p.returncode, 2)
        p = self.cli("split", self.run, "--in", "nope.md", "--root", "10_ARCHITECTURE", "--allow", "chosen/*.md")
        self.assertEqual(p.returncode, 4)


class SourcesTests(Base):
    def seed(self):
        self.w("02_CONTEXT.md", "# Context\n\n## B LANDSCAPE\n- Survey of night nurses (2026-08-01): "
                                "https://example.org/survey.\n- [Swap tools](https://example.org/tools), seen twice: "
                                "https://example.org/tools;\n")
        self.w("checks/I-002.md", "Match: SwapIt https://swapit.example.com/about) CROWDED\n")
        self.w("checks/I-001.md", "Prior art https://example.org/tools again\n")
        self.w("redteam/01_critic.md", "See <https://example.net/postmortem>\n")
        self.w("10_ARCHITECTURE/stack.json", {"rows": [{"layer": "data", "component": "database",
                                                         "choice": "PostgreSQL", "version": "17.6",
                                                         "source_url": "https://www.postgresql.org/docs/release/",
                                                         "status": "VERIFIED"}]})
        self.w("10_ARCHITECTURE/review/L1_gpt.json", {"findings": [{"id": "F1", "issue": "Old queue docs",
                                                                     "evidence": "https://example.org/queue"}]})

    def test_ids_titles_and_stability(self):
        self.seed()
        quiet(bs.sources, self.run)
        s = self.r("sources.json")
        self.assertEqual(list(s), ["S-001", "S-002", "S-003", "S-004", "S-005", "S-006"])
        self.assertEqual(s["S-001"]["url"], "https://example.org/survey")          # trailing '.' stripped
        self.assertEqual(s["S-001"]["accessed"], "2026-08-01")                      # date on the same line
        self.assertEqual(s["S-002"]["url"], "https://example.org/tools")
        self.assertEqual(s["S-002"]["used_in"], ["02_CONTEXT.md", "checks/I-001.md"])
        self.assertEqual(s["S-003"]["url"], "https://swapit.example.com/about")     # checks sorted: I-001, I-002
        self.assertEqual(s["S-003"]["accessed"], "2026-09-23")                      # run date from the folder name
        self.assertEqual(s["S-004"]["url"], "https://www.postgresql.org/docs/release/")
        self.assertEqual(s["S-004"]["title"], "database")
        self.assertEqual(s["S-005"]["title"], "Old queue docs")
        self.assertEqual(s["S-006"]["url"], "https://example.net/postmortem")
        self.assertTrue(all(len(v["title"]) <= 80 for v in s.values()))
        md = self.r("sources.md")
        self.assertIn("| S-001 |", md)
        # re-run with a new URL first in the scan order: old ids stay, the new one gets S-007
        self.w("02_CONTEXT.md", "# Context\nNew https://new.example.com/x\n" + self.r("02_CONTEXT.md"))
        os.remove(self.p("redteam/01_critic.md"))
        quiet(bs.sources, self.run)
        s2 = self.r("sources.json")
        for sid in ("S-001", "S-002", "S-003", "S-004", "S-005"):
            self.assertEqual(s2[sid]["url"], s[sid]["url"])
        self.assertEqual(s2["S-007"]["url"], "https://new.example.com/x")
        self.assertEqual(s2["S-006"]["url"], "https://example.net/postmortem")      # kept though no longer cited
        quiet(bs.sources, self.run)
        self.assertEqual(self.r("sources.json"), s2)                                # idempotent

    def test_run_date_from_run_json(self):
        self.w("run.json", {"schema": 2, "created_at": "2027-01-02T03:04:05Z"})
        self.w("02_CONTEXT.md", "x https://a.example/1\n")
        quiet(bs.sources, self.run)
        self.assertEqual(self.r("sources.json")["S-001"]["accessed"], "2027-01-02")

    def test_empty(self):
        quiet(bs.sources, self.run)
        self.assertEqual(self.r("sources.json"), {})
        self.assertIn("no sources found", self.r("sources.md"))


class AssumptionsTests(Base):
    def setUp(self):
        Base.setUp(self)
        shutil.rmtree(self.run)
        shutil.copytree(LINT_GOOD, self.run)
        os.remove(self.p("11_PROPOSAL/assumptions.md"))

    def test_collect(self):
        out = quiet(bs.assumptions, self.run)
        md = self.r("11_PROPOSAL/assumptions.md")
        rows = [ln for ln in md.splitlines() if ln.startswith("| A-")]
        texts = [ln.split("|")[2].strip() for ln in rows]
        self.assertIn("the team has two developers for the MVP", texts)
        self.assertIn("one hospital with 300 night-shift nurses", texts)
        self.assertIn("ESTIMATE: 5-10; two swaps a month", texts)
        self.assertIn("nurses have smartphones on shift", texts)
        self.assertIn("Most swaps happen after midnight", texts)                  # tag after the claim
        self.assertIn("Ward managers approve swaps within one shift.", texts)     # tag before the sentence
        self.assertIn("the roster export is a nightly CSV", texts)                # from the STATUS trailer
        self.assertNotIn("rejected candidates never reach the assumptions index", md)  # candidates/ skipped
        self.assertEqual(rows[0].split("|")[1].strip(), "A-001")
        self.assertIn("10_ARCHITECTURE/goals-constraints.md", md)
        oq = self.r("11_PROPOSAL/open-questions.md")
        self.assertIn("| Q-001 | Who signs the data processing agreement? | 10_ARCHITECTURE/_raw/12.10.status.json | "
                      "to assign | to assign |", oq)
        self.assertIn("| Q-002 | Which wards join the pilot? | 10_ARCHITECTURE/_raw/12.10.status.json | ward manager "
                      "| Milestone 0 |", oq)
        self.assertIn("assumptions: 7 assumption(s), 2 open question(s)", out)
        # P8 accepts what bs.py assumptions wrote
        res = lints.lint_proposal(self.run)
        self.assertNotIn("P8", [i["id"] for i in res["items"]])

    def test_dedupe(self):
        self.w("11_PROPOSAL/sections/04.md", "[ASSUMPTION: Nurses have smartphones on shift.]\n")
        quiet(bs.assumptions, self.run)
        md = self.r("11_PROPOSAL/assumptions.md")
        self.assertEqual(md.lower().count("nurses have smartphones on shift"), 1)
        self.assertIn("11_PROPOSAL/sections/02.md, 11_PROPOSAL/sections/04.md", md)


class CoverageTests(Base):
    def test_coverage_json(self):
        ideas = []
        cells = [["a", "x"], ["a", "x"], ["a", "y"], ["b", "x"]]
        for n, cell in enumerate(cells):
            ideas.append({"key": "k%d" % n, "title": "t%d" % n, "pitch": "p", "mechanism": "m",
                          "aliases": ["S3-%02d" % n], "cluster": "big" if n < 3 else "small", "cell": cell})
        self.w("merges.json", {"strategy_family": {"S3": "gpt"}, "axes": {"Stage": ["a", "b", "c"],
                                                                          "Channel": ["x", "y"]}, "ideas": ideas})
        quiet(bs.map_pool, self.run)
        cov = self.r("coverage.json")
        self.assertEqual(cov["axes"], {"Stage": ["a", "b", "c"], "Channel": ["x", "y"]})
        self.assertEqual(cov["empty"], [["b", "y"], ["c", "x"], ["c", "y"]])
        self.assertEqual(cov["single"], [["a", "y"], ["b", "x"]])
        self.assertTrue(cov["homogenized"])
        self.assertEqual(cov["largest_cluster"], {"name": "big", "share": 0.75})
        self.assertEqual(cov["clusters"], 2)
        self.assertEqual(cov["ideas"], 4)
        self.assertEqual(cov["covered_share"], 0.5)
        self.assertTrue(cov["gap_needed"])
        self.assertEqual(set(cov), {"axes", "empty", "single", "covered_share", "homogenized", "gap_needed",
                                    "largest_cluster", "clusters", "ideas"})
        lineage = self.r("ideas.json")
        self.assertEqual(sorted(lineage), ["I-001", "I-002", "I-003", "I-004"])
        self.assertEqual(set(lineage["I-001"]), {"key", "strategies", "families", "origin", "cluster"})
        self.assertEqual(lineage["I-001"]["strategies"], ["S3"])
        self.assertEqual(lineage["I-001"]["families"], ["gpt"])

    def pool(self, n, k, cells=None, axes=None):
        """merges.json with n ideas spread evenly over k clusters (and optional cells) -> coverage.json."""
        ideas = [{"key": "k%03d" % i, "title": "t%d" % i, "pitch": "p", "mechanism": "m", "aliases": ["S3-%02d" % i],
                  "cluster": "c%d" % (i % k), "cell": (cells[i % len(cells)] if cells else [])} for i in range(n)]
        self.w("merges.json", {"strategy_family": {"S3": "gpt"}, "axes": axes or {}, "ideas": ideas})
        quiet(bs.map_pool, self.run)
        return self.r("coverage.json"), self.r("03_POOL.md")

    def test_cluster_count_is_not_homogenization(self):
        # finding 54: 6 or 7 even clusters are inside the curator's instructed 6-15, so 40 ideas in 7 clusters of
        # 15% each are not homogenized (the old rule said yes whenever n >= 40 had fewer than 8 clusters)
        cov, pool = self.pool(40, 7)
        self.assertFalse(cov["homogenized"])
        self.assertFalse(cov["gap_needed"])
        self.assertIn("no: largest cluster", pool)
        cov, _pool = self.pool(40, 3)  # 34% in one cluster: still homogenized by the share rule
        self.assertTrue(cov["homogenized"])
        self.assertTrue(cov["gap_needed"])

    def test_gap_round_needs_under_80_percent_coverage(self):
        axes = {"A": ["a", "b", "c"], "B": ["x", "y", "z"]}
        grid = [[a, b] for a in axes["A"] for b in axes["B"]]
        cov, pool = self.pool(40, 10, cells=grid[:8], axes=axes)  # 8 of 9 cells: one empty cell is normal
        self.assertEqual(len(cov["empty"]), 1)
        self.assertFalse(cov["gap_needed"])
        self.assertIn("covered: 8 (89%; a gap round runs below 80%)", pool)
        cov, _pool = self.pool(40, 10, cells=grid[:7], axes=axes)  # 7 of 9 = 78%
        self.assertTrue(cov["gap_needed"])


if __name__ == "__main__":
    unittest.main()
