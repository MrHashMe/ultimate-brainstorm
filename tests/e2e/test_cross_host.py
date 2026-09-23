"""E5 cross-host continue (KIT_SPEC 11.6, 6.10). Owner: B4 (written at integration).

init with `--host claude-code`, drive to G8a, then `ub continue RUN --host codex` with `UB_FAKE_DISABLE=kimi`:
the re-seat is recorded in `run.json.provisional` and the run completes.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "harness"))
import e2elib  # noqa: E402
import paths  # noqa: E402
from answerer import Answerer  # noqa: E402
from tmphome import TmpHome  # noqa: E402


def _uses(seats, fam):
    """True when any seat value (nested) names `fam` exactly."""
    if isinstance(seats, dict):
        return any(_uses(v, fam) for k, v in seats.items() if k not in ("families", "others"))
    if isinstance(seats, list):
        return any(_uses(v, fam) for v in seats)
    return seats == fam


class CrossHost(unittest.TestCase):

    def setUp(self):
        paths.require(paths.UB_PY, paths.PIPELINE_JSON, owner="B3")

    def test_continue_on_codex_without_kimi(self):
        with TmpHome(tools=()) as th:
            env = e2elib.fake_env(th)
            a = Answerer(env=env, cwd=th.project, stop_at=lambda c: c.get("gate") == "G8a")
            card = a.ub("init", "--host", "claude-code", "--text", e2elib.TOPIC, "--root", th.project, "--json")
            card = a.drive(card)
            self.assertEqual(card.get("gate"), "G8a", "did not reach G8a: %r" % a.trace[-5:])
            run = card["run"]
            before = e2elib.run_json(run)
            self.assertTrue(_uses(before["seats"], "kimi"), "kimi held no seat before the switch: %r" %
                            before["seats"])
            n_prov = len(before.get("provisional") or [])

            env2 = e2elib.fake_env(th, UB_FAKE_DISABLE="kimi")
            b = Answerer(env=env2, cwd=th.project)
            card = b.ub("continue", run, "--host", "codex", "--json")
            final = b.drive(card)
            self.assertEqual(final.get("type"), "DONE", "final card: %r\ntrace: %r" % (final, b.trace[-8:]))

            after = e2elib.run_json(run)
            prov = after.get("provisional") or []
            self.assertGreater(len(prov), n_prov, "no re-seat recorded in run.json.provisional")
            self.assertTrue(any("kimi" in str(p) for p in prov[n_prov:]), prov)
            self.assertEqual(after["host"]["agent"], "codex")
            self.assertFalse(_uses({k: v for k, v in after["seats"].items() if k != "families"}, "kimi")
                             and "kimi" not in [p.get("seat") for p in prov[n_prov:]],
                             "kimi still holds a seat after it disappeared: %r" % after["seats"])
            e2elib.no_duplicate_ok(self, run)


if __name__ == "__main__":
    unittest.main()
