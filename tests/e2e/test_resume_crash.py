"""E4 crash and resume (KIT_SPEC 11.6, 4.19, 6.10). Owner: B4 (written at integration).

`UB_TEST_CRASH_AT=6.2` and then `12.11` make the engine exit 99 after those steps' jobs finish; `ub run --continue`
then reaches DONE, and no job with status ok appears twice in calls.jsonl for the same (id, prompt_sha256).
Killing live workers mid-step with `ub stop` followed by `ub run --continue` also completes.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "harness"))
import e2elib  # noqa: E402
import paths  # noqa: E402
from answerer import Answerer  # noqa: E402
from tmphome import TmpHome  # noqa: E402


class ResumeCrash(unittest.TestCase):

    def setUp(self):
        paths.require(paths.UB_PY, paths.PIPELINE_JSON, owner="B3")

    def test_crash_at_steps_then_continue(self):
        with TmpHome(tools=()) as th:
            args = ["run", "--text", e2elib.TOPIC, "--mode", "standard", "--autopilot", "full-auto",
                    "--root", th.project]
            p1 = e2elib.ub(args, e2elib.fake_env(th, UB_TEST_CRASH_AT="6.2"), th.project)
            self.assertEqual(p1.returncode, 99, paths.describe(p1))
            run = e2elib.the_run(self, th.project)
            rj = e2elib.run_json(run)
            self.assertNotEqual((rj.get("steps") or {}).get("6.2", {}).get("state"), "done",
                                "the crashed step must not be marked done")

            p2 = e2elib.ub(["run", "--continue", run], e2elib.fake_env(th, UB_TEST_CRASH_AT="12.11"), th.project)
            self.assertEqual(p2.returncode, 99, paths.describe(p2))
            self.assertEqual(e2elib.run_json(run)["steps"].get("6.2", {}).get("state"), "done")

            p3 = e2elib.ub(["run", "--continue", run], e2elib.fake_env(th), th.project)
            e2elib.assert_done(self, p3, run)
            e2elib.no_duplicate_ok(self, run)
            e2elib.assert_files(self, run, e2elib.expected_files("standard"))

    def test_stop_live_workers_then_continue(self):
        with TmpHome(tools=()) as th:
            env = e2elib.fake_env(th, UB_STUB_DELAY_S="4")

            def running(card):
                calls = ((card.get("progress") or {}).get("calls") or {})
                return card.get("type") == "AUTO" and (calls.get("running") or 0) > 0

            a = Answerer(env=env, cwd=th.project, wait_s=1, stop_at=running)
            card = a.ub("init", "--host", "claude-code", "--text", e2elib.TOPIC, "--mode", "quick",
                        "--root", th.project, "--json")
            card = a.drive(card)
            self.assertTrue(running(card), "never saw a card with running workers: %r" % a.trace[-5:])
            run = card["run"]
            stop = e2elib.ub(["stop", run], env, th.project, timeout=120)
            self.assertEqual(stop.returncode, 0, paths.describe(stop))

            p = e2elib.ub(["run", "--continue", run], e2elib.fake_env(th), th.project)
            e2elib.assert_done(self, p, run)
            e2elib.no_duplicate_ok(self, run)


if __name__ == "__main__":
    unittest.main()
