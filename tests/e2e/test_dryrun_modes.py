"""E1 modes and E2 variants: full-auto dry runs with the stubs (KIT_SPEC 11.6). Owner: B4 (written at integration).

E1: `ub run --text "shift-swap app for nurses" --mode M --autopilot full-auto --root <tmp>` for quick, standard, deep
and proposal. Exit 0, DONE, every mode file exists, PROGRESS.md at 100%, calls.jsonl ok-count within
`ub plan --json` [min, max], every gate `by: auto`, the AUTOPILOT DRAFT banner, and no writes outside the temporary
root and UB_HOME. The four runs are started in parallel to keep the suite short.

E2: research (approach build type, `## 6. Approach`, no G11) and software in a git repo (archetype A text).
"""

import os
import subprocess
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "harness"))
import e2elib  # noqa: E402
import fsnap  # noqa: E402
import paths  # noqa: E402
from tmphome import TmpHome  # noqa: E402

MODES = ("quick", "standard", "deep", "proposal")
ALLOWED = ("project/*", "home/.ultimate-brainstorm/*", "tmp/*")


def _run_mode(mode, text=e2elib.TOPIC, extra=(), repo=False, env_extra=None):
    th = TmpHome(tools=())
    th.__enter__()
    try:
        if repo:
            _make_repo(th)
        before = fsnap.snapshot(th.root)
        env = e2elib.fake_env(th, **(env_extra or {}))
        args = ["run", "--text", text, "--mode", mode, "--autopilot", "full-auto", "--root", th.project] + list(extra)
        proc = e2elib.ub(args, env, th.project)
        after = fsnap.snapshot(th.root)
        runs = e2elib.run_dirs(th.project)
        plan = None
        if len(runs) == 1:
            plan = e2elib.ub(["plan", runs[0], "--json"], env, th.project, timeout=300)
        return {"th": th, "proc": proc, "before": before, "after": after, "runs": runs, "plan": plan, "env": env}
    except BaseException:
        th.__exit__(None, None, None)
        raise


def _make_repo(th):
    src = os.path.join(th.project, "src")
    os.makedirs(src, exist_ok=True)
    th.write(os.path.join(src, "swap.py"),
             "# E2E-CODE-MARKER-9f3a\ndef request_swap(nurse, shift):\n    return {'nurse': nurse, 'shift': shift}\n")
    th.write(os.path.join(th.project, "README.md"), "# Shift swap service\n\nThe existing roster service.\n")
    subprocess.run(["git", "init", "-q", th.project], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                   env=dict(os.environ, GIT_CONFIG_NOSYSTEM="1"))


def _git_available():
    try:
        return subprocess.run(["git", "--version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0
    except OSError:
        return False


class DryRunModes(unittest.TestCase):
    """E1."""

    @classmethod
    def setUpClass(cls):
        paths.require(paths.UB_PY, paths.PIPELINE_JSON, owner="B3")
        paths.require(os.path.join(paths.HARNESS, "stubs.py"), paths.FAMILY_PY, owner="B2/B4")
        cls.kit_before = fsnap.snapshot(paths.SK)
        results = e2elib.parallel([lambda m=m: _run_mode(m) for m in MODES])
        cls.results = dict(zip(MODES, results))
        cls.kit_after = fsnap.snapshot(paths.SK)

    @classmethod
    def tearDownClass(cls):
        for r in (getattr(cls, "results", None) or {}).values():
            if isinstance(r, dict):
                r["th"].__exit__(None, None, None)

    def _result(self, mode):
        r = self.results[mode]
        if isinstance(r, BaseException):
            raise r
        return r

    def check_mode(self, mode):
        r = self._result(mode)
        proc = r["proc"]
        self.assertEqual(len(r["runs"]), 1, paths.describe(proc))
        run = r["runs"][0]
        e2elib.assert_done(self, proc, run)
        e2elib.assert_files(self, run, e2elib.expected_files(mode))
        self.assertTrue(os.path.isfile(os.path.join(r["th"].project, "brainstorm", "LEDGER.md")))

        rj = e2elib.run_json(run)
        self.assertEqual(rj.get("schema"), 2)
        self.assertEqual(rj.get("mode"), mode)
        self.assertEqual(rj.get("autopilot"), "full-auto")
        self.assertTrue(rj.get("gates"), "run.json has no gates")
        for gate, g in rj["gates"].items():
            self.assertEqual(g.get("by"), "auto", "gate %s was not decided by autopilot: %r" % (gate, g))

        progress = e2elib.read(os.path.join(run, "PROGRESS.md"))
        self.assertIn("100%", progress.split("\n", 3)[1] if progress.count("\n") > 1 else progress)

        proposal = e2elib.read(os.path.join(run, "11_PROPOSAL", "PROPOSAL.md"))
        self.assertIn("AUTOPILOT DRAFT", proposal)

        # 11.3: stub packages are coherent enough to pass lint (a should; guarded here against regressions)
        for sub in ("10_ARCHITECTURE", "11_PROPOSAL"):
            lint = e2elib.read_json(os.path.join(run, sub, "lint.json"))
            self.assertNotEqual(lint.get("status"), "fail", "%s %s lint FAIL: %r" % (mode, sub, lint.get("items")))

        plan = r["plan"]
        self.assertEqual(plan.returncode, 0, paths.describe(plan))
        pj = paths.last_json(plan.out)
        lo, hi = pj["calls"]["min"], pj["calls"]["max"]
        n_ok = len(e2elib.ok_calls(run))
        self.assertTrue(lo <= n_ok <= hi, "%s: %d ok calls, plan says [%d, %d]" % (mode, n_ok, lo, hi))
        e2elib.no_duplicate_ok(self, run)

        fsnap.assert_only(self, r["before"], r["after"], ALLOWED, msg="%s run:" % mode)

    def test_quick(self):
        self.check_mode("quick")
        run = self._result("quick")["runs"][0]
        self.assertIn("Novelty NOT checked", e2elib.read(os.path.join(run, "QUICK_DECISION.md")) +
                      e2elib.read(os.path.join(run, "11_PROPOSAL", "PROPOSAL.md")) +
                      e2elib.read(os.path.join(run, "08_DECISION.md")))

    def test_standard(self):
        self.check_mode("standard")

    def test_deep(self):
        self.check_mode("deep")

    def test_proposal(self):
        self.check_mode("proposal")
        run = self._result("proposal")["runs"][0]
        self.assertEqual(e2elib.run_json(run)["choice"]["idea"], "I-001",
                         "proposal mode: the default decision is the user's idea")

    def test_no_writes_into_the_kit(self):
        fsnap.assert_unchanged(self, self.kit_before, self.kit_after, msg="skill tree (the engine must not write into the kit):")


class DryRunVariants(unittest.TestCase):
    """E2."""

    @classmethod
    def setUpClass(cls):
        paths.require(paths.UB_PY, paths.PIPELINE_JSON, owner="B3")
        jobs = [lambda: _run_mode("quick", extra=["--variant", "research"])]
        cls.have_git = _git_available()
        if cls.have_git:
            jobs.append(lambda: _run_mode("quick", text="add shift swaps to this repo", extra=["--variant", "software"],
                                          repo=True))
        res = e2elib.parallel(jobs)
        cls.research = res[0]
        cls.software = res[1] if cls.have_git else None

    @classmethod
    def tearDownClass(cls):
        for r in (getattr(cls, "research", None), getattr(cls, "software", None)):
            if isinstance(r, dict):
                r["th"].__exit__(None, None, None)

    def test_research_approach(self):
        r = self.research
        if isinstance(r, BaseException):
            raise r
        run = r["runs"][0]
        e2elib.assert_done(self, r["proc"], run)
        rj = e2elib.run_json(run)
        self.assertEqual(rj["variant"], "research")
        self.assertEqual(rj["build_type"], "approach")
        self.assertTrue(os.path.isfile(os.path.join(run, "10_ARCHITECTURE", "approach.md")))
        proposal = e2elib.read(os.path.join(run, "11_PROPOSAL", "PROPOSAL.md"))
        self.assertIn("## 6. Approach", proposal)
        self.assertNotIn("## 6. Architecture Summary", proposal)
        g11 = (rj.get("gates") or {}).get("G11")
        self.assertTrue(g11 is None or g11.get("state") == "skipped", "research runs have no G11: %r" % g11)

    def test_software_archetype_a(self):
        if not self.have_git:
            self.skipTest("git is not on PATH")
        r = self.software
        if isinstance(r, BaseException):
            raise r
        run = r["runs"][0]
        e2elib.assert_done(self, r["proc"], run)
        rj = e2elib.run_json(run)
        self.assertEqual(rj["variant"], "software")
        arch = rj["seats"].get("arch_archetypes") or {}
        a_slots = [n for n, a in arch.items() if a == "A"]
        self.assertTrue(a_slots, "no candidate got archetype A: %r" % arch)
        found = False
        for job in e2elib.jobs(run):
            if job.get("step") == "12.4" and job.get("id", "").endswith("c" + a_slots[0]):
                prompt = e2elib.read(os.path.join(run, job["prompt_file"].replace("/", os.sep)))
                self.assertIn("Smallest change", prompt)
                found = True
        self.assertTrue(found, "no 12.4 job for archetype A slot %s" % a_slots[0])


if __name__ == "__main__":
    unittest.main()
