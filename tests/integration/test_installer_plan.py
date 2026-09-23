"""Installer plan tests (KIT_SPEC 4.14, 10.3, 11.4 "Plan"). Owner: B4.

The plan writes nothing, and the golden cases in tests/fixtures/installer/plans/ hold for every detection scenario.
"""

import json
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "harness"))
import paths  # noqa: E402
import fsnap  # noqa: E402
import inst  # noqa: E402


class PlanWritesNothing(unittest.TestCase):
    def setUp(self):
        inst.require_installer()

    def test_plan_json_and_text_write_nothing(self):
        with inst.installer_home(zcode=True) as th:
            before = fsnap.snapshot(th.root)
            plan = inst.run_plan(th)
            proc = inst.run(th)  # no command = plan (text)
            self.assertEqual(proc.returncode, 0, paths.describe(proc))
            after = fsnap.snapshot(th.root)
            fsnap.assert_unchanged(self, before, after, ignore=["fake.log", "fake.log.*"] + inst.home_snapshot_ignores(),
                                   msg="plan")
            self.assertFalse(os.path.exists(th.ub_home), "plan must not create UB_HOME")
            self.assertEqual(plan["schema"], 1)
            for key in ("kit", "system", "agents", "rows", "warnings", "manual", "next"):
                self.assertIn(key, plan)
            self.assertEqual(plan["kit"]["name"], "ultimate-brainstorm")
            self.assertEqual(plan["kit"]["version"], "2.0.0")
            for r in plan["rows"]:
                for k in ("n", "agent", "item", "action", "how", "path", "commands"):
                    self.assertIn(k, r)
                self.assertIn(r["action"], ("create", "update", "unchanged", "backup+update", "install", "remove",
                                            "skip-not-owned", "migrate-v1", "manual", "blocked"))
                self.assertIn(r["how"], ("copy", "native", "npx", "npm", "print"))
                for cmd in r["commands"]:
                    self.assertTrue(isinstance(cmd, list) and all(isinstance(a, str) for a in cmd), cmd)
            text = proc.out
            for r in plan["rows"]:
                self.assertIn(r["action"], text, "the text plan shows the same rows as a table")

    def test_plan_is_default_command(self):
        with inst.installer_home(tools=("codex", "node")) as th:
            a = inst.run_json(th)[0]
            b = inst.run_plan(th)
            self.assertEqual([(r["agent"], r["action"], r["how"]) for r in a["rows"]],
                             [(r["agent"], r["action"], r["how"]) for r in b["rows"]])


class GoldenPlans(unittest.TestCase):
    def setUp(self):
        inst.require_installer()

    def check_case(self, name):
        case = inst.load_case(name)
        with inst.installer_home(tools=tuple(case.get("tools") or ()), versions=case.get("versions"),
                                 zcode=case.get("zcode", False)) as th:
            for k, v in (case.get("env") or {}).items():
                th.env[k] = inst.expand(v, th).replace("/", os.sep)
                os.makedirs(th.env[k], exist_ok=True)
            if "kimi" in (case.get("tools") or ()):
                os.makedirs(os.path.join(th.env.get("KIMI_CODE_HOME", th.kimi_home), "credentials"), exist_ok=True)
            proc = inst.run(th, "plan", "--json", *case.get("args", []))
            self.assertEqual(proc.returncode, case.get("exit", 0), "%s: %s" % (name, paths.describe(proc)))
            for needle in case.get("output_contains") or []:
                self.assertIn(needle, proc.out + proc.err, name)
            if not (case.get("agents") or case.get("rows") or case.get("absent_rows") or case.get("warnings")):
                return
            plan = paths.last_json(proc.out)
            for agent, want in (case.get("agents") or {}).items():
                got = plan["agents"].get(agent)
                self.assertIsNotNone(got, "%s: agents.%s missing" % (name, agent))
                self.assertTrue(inst.subset(inst.expand(want, th), got),
                                "%s: agents.%s = %s, want %s" % (name, agent, got, want))
            for want in case.get("rows") or []:
                want = inst.expand(want, th)
                self.assertTrue(any(inst.subset(want, r) for r in plan["rows"]),
                                "%s: no row matches %s\nrows: %s" % (name, want, json.dumps(plan["rows"], indent=1)))
            for bad in case.get("absent_rows") or []:
                bad = inst.expand(bad, th)
                hits = [r for r in plan["rows"] if inst.subset(bad, r)]
                self.assertEqual(hits, [], "%s: rows matching %s must be absent" % (name, bad))
            for rx in case.get("warnings") or []:
                self.assertTrue(any(re.search(rx, w) for w in plan["warnings"] + plan.get("manual", [])),
                                "%s: no warning matches %s: %s" % (name, rx, plan["warnings"]))

    def test_no_agents(self):
        self.check_case("no_agents")

    def test_all_agents(self):
        self.check_case("all_agents")

    def test_only_codex(self):
        self.check_case("only_codex")

    def test_codex_0140_copy_route(self):
        self.check_case("codex_0140")

    def test_claude_2_1_200_copy_route(self):
        self.check_case("claude_2_1_200")

    def test_kimi_legacy(self):
        self.check_case("kimi_legacy")

    def test_agent_homes_honored(self):
        self.check_case("homes_honored")

    def test_named_but_not_detected_gets_copy(self):
        """10.3: an agent named in --agents whose CLI is not installed gets the copy route."""
        with inst.installer_home(tools=("node",)) as th:
            plan = inst.run_plan(th, "--agents", "kimi", "--components", "none")
            self.assertTrue(inst.rows(plan, agent="kimi", action="create", how="copy"), plan["rows"])


if __name__ == "__main__":
    unittest.main()
