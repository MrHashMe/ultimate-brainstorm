"""E3 guided protocol: drive `ub init/next/answer/done --json` like a host (KIT_SPEC 11.6, 4.11-4.13).
Owner: B4 (written at integration).

HUMAN cards get `default_answer`, except G8b (a non-leader idea, with the user's `why`) and G11 (candidate B).
The HOST frame-grill step (`--components grilling`) writes the fixture frame files and runs `done_cmd`.
HOST_BATCH cards (`UB_FAKE_HOST_BACKEND=glm`) are answered with `stubs.respond(job, prompt)` (tests/harness/stubs.py).
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "harness"))
import e2elib  # noqa: E402
import paths  # noqa: E402
from answerer import Answerer, pick_non_leader  # noqa: E402
from tmphome import TmpHome  # noqa: E402

WHY = "the charge nurses asked for exactly this"


class GuidedProtocol(unittest.TestCase):

    def setUp(self):
        paths.require(paths.UB_PY, paths.PIPELINE_JSON, owner="B3")
        paths.require(os.path.join(paths.HARNESS, "stubs.py"), owner="B4")

    def test_guided_standard_to_done(self):
        chosen = {}

        def g8b(card):
            cid = pick_non_leader(card)
            chosen["id"] = cid
            return {"chosen": cid, "accept_recommendation": False, "why": WHY, "reply": "%s, %s" % (cid, WHY)}

        with TmpHome(tools=()) as th:
            env = e2elib.fake_env(th, UB_FAKE_HOST_BACKEND="glm")
            a = Answerer(env=env, cwd=th.project, choices={
                "G8b": g8b, "G11": {"choice": "B", "accept_recommendation": False, "reply": "B"}})
            card = a.ub("init", "--host", "claude-code", "--text", e2elib.TOPIC, "--components", "grilling",
                        "--root", th.project, "--json")
            self.assertEqual(card.get("type"), "HUMAN")
            self.assertEqual(card.get("gate"), "G0")
            for key in ("ub", "run", "runner", "say", "progress", "show", "answer_file", "answer_template",
                        "answer_cmd", "default_answer"):
                self.assertIn(key, card, "card field %s missing" % key)
            final = a.drive(card)
            self.assertEqual(final.get("type"), "DONE", "final card: %r\ntrace: %r" % (final, a.trace[-8:]))

            kinds = set(t["type"] for t in a.trace)
            self.assertIn("HOST", kinds, "the grilling HOST step never ran")
            self.assertIn("HOST_BATCH", kinds, "UB_FAKE_HOST_BACKEND=glm produced no HOST_BATCH card")
            gates = [t["gate"] for t in a.trace if t["type"] == "HUMAN"]
            for g in ("G0", "G8b", "G11", "G13"):
                self.assertIn(g, gates)

            run = e2elib.the_run(self, th.project)
            self.assertTrue(chosen.get("id"), "G8b was never asked")
            decision = e2elib.read(os.path.join(run, "08_DECISION.md"))
            self.assertIn(chosen["id"], decision.split("\n", 3)[1] if decision.count("\n") > 1 else decision)
            self.assertIn(WHY, decision)
            readme = e2elib.read(os.path.join(run, "10_ARCHITECTURE", "README.md"))
            self.assertRegex(readme, r"(?i)chosen:\s*candidate B\b")
            rj = e2elib.run_json(run)
            self.assertEqual(rj["choice"]["idea"], chosen["id"])
            self.assertEqual(rj["choice"]["arch"], "B")
            self.assertEqual(rj["gates"]["G8b"]["by"], "human")
            self.assertNotIn("AUTOPILOT DRAFT", e2elib.read(os.path.join(run, "11_PROPOSAL", "PROPOSAL.md")))
            e2elib.no_duplicate_ok(self, run)


if __name__ == "__main__":
    unittest.main()
