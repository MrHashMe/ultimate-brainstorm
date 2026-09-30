"""B3 engine: progress, estimates and budgets (KIT_SPEC 6.9): `ub plan` shape and monotonicity in families and mode,
the PROGRESS.md format, the card progress block, calls counting and the budget check."""

import json
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fixtures", "engine"))
import engine_testlib as tl  # noqa: E402

from ublib import textio  # noqa: E402
from ublib.engine import pipeline, progress  # noqa: E402
from ublib.engine import state as st  # noqa: E402

sys.path.insert(0, tl.SCRIPTS)
import ub  # noqa: E402


class PlanTests(tl.EngineTestCase):
    def plan(self, mode, fams, variant="product"):
        ctx = ub.synthetic_ctx(mode, variant, list(fams), deps=tl.FakeDeps())
        return progress.plan(ctx)

    def test_shape(self):
        p = self.plan("standard", ("claude", "gpt"))
        self.assertEqual(sorted(p), ["calls", "cost", "minutes", "requests", "tokens"])
        self.assertEqual(sorted(p["calls"]), ["by_family", "expected", "max", "min"])
        self.assertLessEqual(p["calls"]["min"], p["calls"]["expected"])
        self.assertLessEqual(p["calls"]["expected"], p["calls"]["max"])
        # requests are the budget unit: one per call when nothing is retried, more at the worst case
        self.assertEqual(sorted(p["requests"]), ["cap", "expected", "max", "min"])
        self.assertEqual(p["requests"]["expected"], p["calls"]["expected"])
        self.assertGreaterEqual(p["requests"]["max"], p["calls"]["max"])
        self.assertEqual(p["requests"]["cap"], 180)
        self.assertLessEqual(p["tokens"][0], p["tokens"][1])
        self.assertLessEqual(p["minutes"][0], p["minutes"][1])
        self.assertEqual(p["cost"], "counts against your plans")
        self.assertEqual(sorted(p["calls"]["by_family"]), ["claude", "gpt"])

    def test_monotonic_in_mode(self):
        for fams in (("claude",), ("claude", "gpt"), ("claude", "gpt", "kimi", "glm")):
            q, s, d = (self.plan(m, fams)["calls"] for m in ("quick", "standard", "deep"))
            self.assertLess(q["max"], s["min"], fams)
            self.assertLess(s["max"], d["max"], fams)
            self.assertLessEqual(s["expected"], d["expected"])

    def test_plan_counts_are_the_jobs_the_fanouts_build(self):
        """#15: a fanout whose items do not come from files earlier steps write is counted by building its items, so
        `ub plan` and the ETA cannot drift from the dispatch (the approach review builds one lens, not 2 or 4)."""
        from ublib.engine import registry
        for mode in ("quick", "standard", "deep", "proposal"):
            for variant in ("product", "research", "software"):
                for fams in (("claude",), ("claude", "gpt", "kimi"), ("claude", "gpt", "kimi", "glm")):
                    ctx = ub.synthetic_ctx(mode, variant, list(fams), deps=tl.FakeDeps())
                    for s in pipeline.load_steps():
                        fan = s.get("fanout")
                        if s.get("type") != "DISPATCH" or fan in registry.SIM_COUNTS:
                            continue
                        n = len(registry.FANOUTS[fan](ctx, s))
                        self.assertEqual(registry.fanout_count(ctx, fan, s), (n, n), (mode, variant, fams, s["id"]))
        ctx = ub.synthetic_ctx("deep", "research", ["claude", "gpt", "kimi"], deps=tl.FakeDeps())
        self.assertEqual(registry.fanout_count(ctx, "review_lenses", {"id": "12.13a"}), (1, 1))
        self.assertEqual(sorted(registry.SIM_COUNTS), ["evolved", "gap_cells", "rebuttals", "redteam_pairs",
                                                       "shortlist", "tournament_prompts"])

    def test_spec_ranges_are_plausible(self):
        s = self.plan("standard", ("claude", "gpt", "kimi"))["calls"]
        self.assertTrue(40 <= s["expected"] <= 110, s)
        q = self.plan("quick", ("claude", "gpt", "kimi"))["calls"]
        self.assertTrue(10 <= q["expected"] <= 40, q)

    def test_prices_give_dollars(self):
        home = os.environ["UB_HOME"]
        os.makedirs(home, exist_ok=True)
        textio.write_json_atomic(os.path.join(home, "families.json"), {"prices": {"claude": {"usd_per_mtok": 10}}})
        p = self.plan("standard", ("claude",))
        self.assertIn("usd", p)
        self.assertTrue(p["cost"].startswith("about $"))

    def test_plan_cli(self):
        import io
        from unittest import mock
        out = io.StringIO()
        with mock.patch.object(sys, "stdout", out):
            rc = ub.main(["plan", "--mode", "deep", "--variant", "software", "--families", "claude,gpt,kimi", "--json"],
                         deps=tl.FakeDeps())
        self.assertEqual(rc, 0)
        data = json.loads(out.getvalue())
        self.assertEqual(data["mode"], "deep")
        self.assertIn("calls", data)


class ProgressFileTests(tl.EngineTestCase):
    def test_progress_md_format(self):
        ctx = self.make_ctx()
        steps = pipeline.load_steps()
        for s in steps[:12]:
            st.set_step(ctx.state, s["id"], "done")
        ctx.write("03_POOL.md", "# pool\n")
        block = progress.write_progress(ctx, steps, pipeline.current_step(ctx, steps), "your turn - Gut pick (G8a)")
        text = ctx.read("PROGRESS.md")
        lines = text.rstrip("\n").split("\n")
        self.assertTrue(re.match(r"^# ultimate-brainstorm: \S+ \(standard, product, guided\) +updated \d\d:\d\d$",
                                 lines[0]), lines[0])
        self.assertTrue(re.match(r"^\d+% \| stage \d+/14 \S.* \| ETA .* \| NEXT: your turn - Gut pick \(G8a\)$",
                                 lines[1]), lines[1])
        self.assertTrue(any(ln.startswith("Families: claude OK (host, web)") for ln in lines))
        self.assertTrue(any(re.match(r"^Calls: \d+ done, \d+ running, \d+ failed, \d+ provisional", ln) for ln in lines))
        self.assertIn("[x] 0 Kickoff", text)
        self.assertIn("[ ] 14 Handoff", text)
        self.assertTrue(lines[-1].startswith("Files: 03_POOL.md"))
        self.assertEqual(sorted(block), ["calls", "eta_s", "line", "of", "pct", "stage"])
        self.assertEqual(block["of"], 14)
        self.assertTrue(block["line"].startswith("["))

    def test_families_line(self):
        ctx = self.make_ctx(families=("claude", "gpt"))
        line = progress.families_line(ctx)
        self.assertEqual(line, "claude OK (host, web) | gpt OK (web) | kimi not set up | glm not set up")
        st.add_provisional(ctx.state, "screen", "gpt", "gpt-alt", "x")
        self.assertIn("gpt PROVISIONAL->gpt-alt at screen", progress.families_line(ctx))

    def test_calls_summary_counts_meta(self):
        ctx = self.make_ctx()
        for jid, status in (("a", "ok"), ("b", "failed"), ("c", "ok")):
            ctx.write_json("jobs/%s.json" % jid, {"id": jid, "out": "o/%s.md" % jid, "provisional": jid == "c"})
            ctx.write_json("o/%s.md.meta.json" % jid, {"id": jid, "status": status})
        c = progress.calls_summary(ctx)
        self.assertEqual(c, {"done": 2, "failed": 1, "running": 0, "provisional": 1})

    def test_json_that_is_no_object_is_skipped(self):
        """A job, meta file or calls.jsonl line holding a list, a number or null crashed every progress block."""
        ctx = self.make_ctx()
        ctx.write_json("jobs/a.json", {"id": "a", "out": "o/a.md"})
        ctx.write_json("o/a.md.meta.json", {"id": "a", "status": "ok"})
        ctx.write_json("jobs/b.json", ["b"])
        ctx.write_json("jobs/c.json", {"id": "c", "out": 7})
        ctx.write_json("jobs/d.json", {"id": "d", "out": "o/d.md"})
        ctx.write_json("o/d.md.meta.json", [{"id": "d", "status": "ok"}])
        self.assertEqual(progress.calls_summary(ctx), {"done": 1, "failed": 0, "running": 0, "provisional": 0})
        ctx.write("logs/calls.jsonl", '[1]\nnull\n{"status": "ok", "duration_s": "slow"}\n'
                                      '{"status": "ok", "duration_s": 12, "kind": "judge"}\n')
        self.assertEqual(progress.observed_durations(ctx.run_dir), {"judge": [12.0], "all": [12.0]})


class BudgetTests(tl.EngineTestCase):
    def test_the_cap_counts_ledger_requests(self):
        """I8 / C6: requests_used sums logs/calls.jsonl `requests` (a row without it counts 1, a host sub-agent row
        0); launches never count; a line still being appended waits for its newline."""
        ctx = self.make_ctx()
        ctx.state["budget"]["max_calls"] = 10
        ctx.state["counters"]["launched"] = 99
        self.assertEqual(progress.requests_used(ctx), 0)
        self.assertFalse(progress.budget_binds(ctx, 10))
        path = ctx.path("logs", "calls.jsonl")
        textio.append_line(path, json.dumps({"id": "a", "requests": 3}))
        textio.append_line(path, json.dumps({"id": "b"}))
        textio.append_line(path, json.dumps({"id": "c", "backend": "host"}))
        textio.append_line(path, json.dumps({"id": "d", "backend": "host", "requests": 0}))
        self.assertEqual(progress.requests_used(ctx), 4)
        with open(path, "ab") as f:
            f.write(b'{"id": "e", "requests": 5}')  # no newline yet: a worker is still writing it
        self.assertEqual(progress.requests_used(ctx), 4)
        with open(path, "ab") as f:
            f.write(b"\n")
        self.assertEqual(progress.requests_used(ctx), 9)
        self.assertFalse(progress.budget_binds(ctx, 1))
        self.assertTrue(progress.budget_binds(ctx, 2))
        ctx.state["budget"]["max_calls"] = None
        self.assertFalse(progress.budget_binds(ctx, 100))
        self.assertIn("Requests sent: 9 of None (budget.max_calls); job launches: 99.", progress.budget_line(ctx))


class EstimatesTests(unittest.TestCase):
    def test_estimates_file(self):
        est = progress.estimates()
        for kind, v in est.items():
            self.assertGreater(v["seconds"], 0, kind)
            self.assertGreaterEqual(v["in_tokens"], 0, kind)


if __name__ == "__main__":
    unittest.main()
