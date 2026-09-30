"""E1: the documented terminal entry with real `ub.py` processes (KIT_SPEC 4.11; audit #82).

- the README argv `ub run "<topic>" --mode quick --autopilot full-auto` runs to DONE with that topic
- `ub run status <run>` shows the run and `ub run quick` (no topic) is a usage error: neither creates a run folder
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "harness"))
import e2elib  # noqa: E402
import paths  # noqa: E402
from tmphome import TmpHome  # noqa: E402

README_TOPIC = "AI tutor for night-shift nurses"


class RunArgv(unittest.TestCase):

    def setUp(self):
        paths.require(paths.UB_PY, paths.PIPELINE_JSON, owner="B3")
        paths.require(os.path.join(paths.KIT, "tests", "harness", "stubs.py"), owner="B4")

    def test_the_readme_argv_runs_and_command_words_never_start_a_run(self):
        with TmpHome(tools=()) as th:
            env = e2elib.fake_env(th)
            proc = e2elib.ub(["run", README_TOPIC, "--mode", "quick", "--autopilot", "full-auto", "--root",
                              th.project], env, th.project)
            run = e2elib.the_run(self, th.project)
            e2elib.assert_done(self, proc, run)
            self.assertEqual(e2elib.run_json(run)["topic"], README_TOPIC)
            status = e2elib.ub(["run", "status", run, "--json"], env, th.project)
            self.assertEqual(status.returncode, 0, paths.describe(status))
            self.assertEqual(paths.last_json(status.out).get("status"), "done", paths.describe(status))
            bare = e2elib.ub(["run", "quick", "--root", th.project], env, th.project)
            self.assertEqual(bare.returncode, 2, paths.describe(bare))
            self.assertEqual(e2elib.run_dirs(th.project), [run], "a command word or an empty topic started a run")


if __name__ == "__main__":
    unittest.main()
