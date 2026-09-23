"""E6 privacy and E7 seed leak (KIT_SPEC 11.6, 6.7, 6.8). Owner: B4 (written at integration).

E6 `private`: only host-family jobs, every other seat `-alt`, no job with `web` tools, PROVISIONAL banner.
E6 `code=false` in a fake git repo: jobs for other vendors never get `cwd: repo`, and no source line reaches their
prompts.
E7: a frame that carries one of the human's sealed seed lines reaches a generator prompt -> BLOCKED card naming the
seed-leak rule.
"""

import os
import subprocess
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "harness"))
import e2elib  # noqa: E402
import paths  # noqa: E402
from answerer import Answerer  # noqa: E402
from tmphome import TmpHome  # noqa: E402

HOST_FAMILY = "claude"
HOST_VENDOR_FAMILIES = ("claude", "claude-alt")
CODE_MARKER = "E2E-CODE-MARKER-9f3a"
SEED = "Nurses trade shifts through a points ledger that the ward can see"


def _seat_values(seats):
    skip = ("families", "others", "web_families", "host", "single_family", "rr_next", "s1_engine", "arch_archetypes",
            "arch_same_family")
    out = []

    def walk(v):
        if isinstance(v, dict):
            for x in v.values():
                walk(x)
        elif isinstance(v, list):
            for x in v:
                walk(x)
        elif isinstance(v, str):
            out.append(v)

    for k, v in (seats or {}).items():
        if k not in skip:
            walk(v)
    return out


def _tools(job):
    t = job.get("tools")
    return t if isinstance(t, list) else [t]


class Privacy(unittest.TestCase):

    def setUp(self):
        paths.require(paths.UB_PY, paths.PIPELINE_JSON, owner="B3")

    def test_private_run_stays_on_the_host_family(self):
        with TmpHome(tools=()) as th:
            proc = e2elib.ub(["run", "--text", "private " + e2elib.TOPIC, "--mode", "quick", "--autopilot",
                              "full-auto", "--root", th.project], e2elib.fake_env(th), th.project)
            run = e2elib.the_run(self, th.project)
            e2elib.assert_done(self, proc, run)
            rj = e2elib.run_json(run)
            self.assertEqual(rj["host"]["family"], HOST_FAMILY)
            self.assertFalse(rj["privacy"]["vendors"])
            self.assertFalse(rj["privacy"]["web"])
            fams = set(c.get("family") for c in e2elib.calls(run))
            self.assertTrue(fams, "no calls recorded")
            self.assertTrue(fams <= set(HOST_VENDOR_FAMILIES), "calls left the host family: %s" % sorted(fams))
            for seat in _seat_values(rj["seats"]):
                self.assertIn(seat, HOST_VENDOR_FAMILIES, "seat outside the host vendor: %s" % seat)
            for job in e2elib.jobs(run):
                self.assertIn(job.get("family"), HOST_VENDOR_FAMILIES, job.get("id"))
                self.assertNotIn("web", _tools(job), "private run job %s has web tools" % job.get("id"))
            text = "".join(e2elib.read(os.path.join(run, f)) for f in
                           ("08_DECISION.md", "11_PROPOSAL/PROPOSAL.md", "PROGRESS.md", "00_RUN.md"))
            self.assertIn("PROVISIONAL", text)

    def test_code_false_keeps_repo_out_of_other_vendors(self):
        try:
            have_git = subprocess.run(["git", "--version"], stdout=subprocess.DEVNULL,
                                      stderr=subprocess.DEVNULL).returncode == 0
        except OSError:
            have_git = False
        if not have_git:
            self.skipTest("git is not on PATH")
        with TmpHome(tools=()) as th:
            th.write(os.path.join(th.project, "src", "swap.py"),
                     "# %s\ndef request_swap(nurse, shift):\n    return (nurse, shift)\n" % CODE_MARKER)
            th.write(os.path.join(th.project, "README.md"), "# Roster service\n")
            subprocess.run(["git", "init", "-q", th.project], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            proc = e2elib.ub(["run", "--text", "add shift swaps to this repo", "--mode", "quick", "--variant",
                              "software", "--autopilot", "full-auto", "--root", th.project],
                             e2elib.fake_env(th), th.project)
            run = e2elib.the_run(self, th.project)
            e2elib.assert_done(self, proc, run)
            rj = e2elib.run_json(run)
            self.assertFalse(rj["privacy"]["code"])
            others = [j for j in e2elib.jobs(run) if j.get("family") not in HOST_VENDOR_FAMILIES]
            self.assertTrue(others, "no job went to another vendor")
            for job in others:
                self.assertNotEqual(job.get("cwd"), "repo", "job %s (%s) got the repo" % (job["id"], job["family"]))
                prompt = e2elib.read(os.path.join(run, job["prompt_file"].replace("/", os.sep)))
                self.assertNotIn(CODE_MARKER, prompt, job["id"])
                self.assertNotIn("def request_swap", prompt, job["id"])


class SeedLeak(unittest.TestCase):

    def setUp(self):
        paths.require(paths.UB_PY, paths.PIPELINE_JSON, owner="B3")

    def test_seed_line_in_a_generator_prompt_blocks(self):
        with TmpHome(tools=()) as th:
            env = e2elib.fake_env(th)
            seeds = {"problem": None, "primary": None, "ideas": [SEED], "obvious": [], "off_limits": []}
            a = Answerer(env=env, cwd=th.project, host_fixtures=os.path.join(paths.FIX_E2E, "host-seedleak"),
                         choices={"G0": {"seeds": seeds, "skip_seeds": False, "reply": SEED}})
            card = a.ub("init", "--host", "claude-code", "--text", e2elib.TOPIC, "--components", "grilling",
                        "--root", th.project, "--json")
            final = a.drive(card)
            self.assertEqual(final.get("type"), "BLOCKED", "expected BLOCKED, got %r" % final.get("type"))
            blob = " ".join(str(final.get(k) or "") for k in ("say", "error", "fix", "show"))
            self.assertRegex(blob, r"(?i)seed[_ -]leak")
            run = final["run"]
            seeds_file = e2elib.read(os.path.join(run, "00_HUMAN_SEEDS.md"))
            self.assertIn(SEED, seeds_file)
            # nothing generated from the leaking prompt
            gens = [c for c in e2elib.ok_calls(run) if str(c.get("id", "")).startswith("4.")]
            self.assertFalse(gens, "generators ran despite the leak: %s" % [c["id"] for c in gens])


if __name__ == "__main__":
    unittest.main()
