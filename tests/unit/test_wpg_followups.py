"""WPG follow-ups of phase B: the host sub-agent's ledger row and canonical JSON output (pipeline.host_job_state), the
quick curation stub's aliases (tests/harness/stubs.py), fallback copies of repo-reading jobs rebuilt for a family
whose prompts carry no code (builders.fallback_job), and architecture judges for four families (seats.assign).

The fifth follow-up (crash evidence of a worker ended by a signal) is in test_wpg_worker_signals.py."""

import json
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fixtures", "engine"))
import engine_testlib as tl  # noqa: E402

import stubs  # noqa: E402  (tests/harness, on sys.path through engine_testlib)
from ublib import adapter, batch, textio, validate  # noqa: E402
from ublib.engine import base_family, builders, pipeline, seats  # noqa: E402
from ublib.engine import privacy as pv  # noqa: E402

ALL = ("claude", "gpt", "kimi", "glm")
CODEBASE_HEADING = "## 5. Codebase fit"
REPO_LINE = "You may read the repository"
CHECK_ANSWER = ("## 1. Prior art\nq\n## 2. Steelman\ns\n## 3. Load-bearing claims\nc\n## 4. Kill-assumptions\nk\n"
                "VERDICT: ADJACENT; DIFFERENTIATOR: ward-visible\n")
CONTEXT = ("## A. FACTS\n- src/swap.py holds the swap rules (src/swap.py:42)\n## A2. DOMAIN TERMS\n- **Swap**: x\n"
           "## B. LANDSCAPE\n- ShiftBoard does swaps\n```python\nLANDSCAPE_SECRET = 1\n```\n"
           "## C. SEARCH BOUNDARY\n- s\n")


# ================================================================ items 1 and 4: host sub-agent outputs

class HostJobTests(tl.EngineTestCase):
    def host_job(self, ctx, contract, out="screen/claude.out.json"):
        ctx.state["families"]["claude"]["backend"] = "host"
        ctx.write("prompts/6.2-claude.prompt.md", "Score the ideas.\n")
        job = {"id": "6.2-claude", "family": "claude", "prompt_file": "prompts/6.2-claude.prompt.md", "out": out,
               "contract": contract, "tools": "none", "cwd": "empty"}
        ctx.state.setdefault("host_issued", {})[job["id"]] = textio.sha256_file(ctx.path(job["prompt_file"]))
        return job

    def ledger(self, ctx):
        return [json.loads(ln) for ln in ctx.read("logs/calls.jsonl").splitlines() if ln.strip()]

    def test_the_ledger_row_of_a_host_job_sends_no_request(self):
        """C6: a host sub-agent row carries "requests": 0 (a row without the field would count as one request)."""
        ctx = self.make_ctx()
        job = self.host_job(ctx, {"type": "text", "min_chars": 5}, out="probe.md")
        ctx.write(job["out"], "A probe that runs for one week.\n")
        self.assertEqual(pipeline.host_job_state(ctx, job), "done")
        rows = [r for r in self.ledger(ctx) if r.get("id") == job["id"]]
        self.assertEqual([(r["backend"], r["requests"]) for r in rows], [("host", 0)])

    def test_a_json_output_is_written_back_in_canonical_form(self):
        """As the adapter writes a worker's JSON (4.5): the extracted value, cover ids rewritten to the engine's ids,
        so every reader of the file sees the engine's ids; the meta's out_sha256 is the rewritten file's."""
        ctx = self.make_ctx()
        cover = {"array": "scores", "key": "id", "ids": ["I-001", "I-002"]}
        job = self.host_job(ctx, {"type": "json", "cover": cover})
        raw = ("Here are the scores.\n```json\n" + json.dumps({"scores": [{"id": "I-0​01", "v": 5},
                                                                          {"id": "I-００２", "v": 2}]})
               + "\n```\n")
        ctx.write(job["out"], raw)
        self.assertEqual(pipeline.host_job_state(ctx, job), "done")
        text = ctx.read(job["out"])
        parsed = {"scores": [{"id": "I-001", "v": 5}, {"id": "I-002", "v": 2}]}
        self.assertEqual(text, json.dumps(parsed, indent=1, ensure_ascii=False) + "\n")
        meta = ctx.read_json(job["out"] + ".meta.json")
        self.assertEqual((meta["status"], meta["out_sha256"]), ("ok", textio.sha256_file(ctx.path(job["out"]))))
        self.assertTrue(batch.is_done(ctx.run_dir, job))
        self.assertEqual(pipeline.host_job_state(ctx, job), "done")

    def test_other_outputs_stay_as_written(self):
        ctx = self.make_ctx()
        job = self.host_job(ctx, {"type": "text", "min_chars": 5}, out="probe.md")
        ctx.write(job["out"], "```json\n{\"a\": 1}\n```\n")
        self.assertEqual(pipeline.host_job_state(ctx, job), "done")
        self.assertEqual(ctx.read(job["out"]), "```json\n{\"a\": 1}\n```\n")


# ================================================================ item 2: the quick curation stub

class QuickCurateStubTests(unittest.TestCase):
    CONTRACT = {"type": "json", "schema": "SK:templates/schemas/quick-curated.schema.json"}

    def curated(self, aliases=None):
        job = {"id": "Q.3", "template": "QUICK-CURATE", "kind": "curator", "contract": self.CONTRACT,
               "stub": {"aliases": aliases} if aliases is not None else {}}
        text = stubs.respond(job, "")
        ok, errors, _parsed = validate.check_contract(text, self.CONTRACT, None)
        self.assertTrue(ok, errors)
        return json.loads(text)["ideas"]

    def test_ideas_carry_aliases_from_the_pool_and_seeds(self):
        pool = ["QA-%02d" % i for i in range(1, 9)] + ["QB-%02d" % i for i in range(1, 9)] + ["H-01", "H-02"]
        ideas = self.curated(pool)
        self.assertEqual(len(ideas), 6)
        for idea in ideas:
            self.assertNotIn("origin", idea)
            self.assertTrue(1 <= len(idea["aliases"]) <= 3, idea["aliases"])
            self.assertTrue(set(idea["aliases"]) <= set(pool), idea["aliases"])
            self.assertEqual(len(set(bs_prefix(a) for a in idea["aliases"])), 1, idea["aliases"])
        seen = [a for i in ideas for a in i["aliases"]]
        self.assertEqual(len(seen), len(set(seen)), "an alias is merged into one idea only")
        prefixes = [bs_prefix(i["aliases"][0]) for i in ideas]
        self.assertEqual(prefixes, ["QA", "QB", "H", "QA", "QB", "QA"])  # both generators and the human seeds

    def test_without_facts_every_idea_has_one_generated_alias(self):
        self.assertEqual([i["aliases"] for i in self.curated()], [["QA-%02d" % (i + 1)] for i in range(6)])

    def test_a_small_pool_is_reused(self):
        ideas = self.curated(["QA-01", "QB-01"])
        self.assertEqual([i["aliases"] for i in ideas], [["QA-01"], ["QB-01"], ["QA-01"], ["QB-01"], ["QA-01"],
                                                         ["QB-01"]])


def bs_prefix(alias):
    head, sep, tail = alias.rpartition("-")
    return head if sep and tail.isdecimal() else alias


# ================================================================ item 3: fallback copies of repo-reading jobs

class FallbackRebuildTests(tl.EngineTestCase):
    def software(self):
        os.makedirs(os.path.join(self.project, ".git"), exist_ok=True)
        ctx = self.make_ctx(variant="software", families=("claude", "gpt"))
        ctx.write("02_CONTEXT.md", CONTEXT)
        return ctx

    def check_job(self, ctx):
        ctx.write_json("origins.json", {"I-001": "human"})
        ctx.write("screen/ideas.md", "I-001 | Ward ledger | Nurses swap on a ledger. | A shared ledger.\n")
        ctx.write_json("screen/shortlist.json", {"shortlist": [{"id": "I-001"}]})
        step = {"id": "7.1", "fanout": "shortlist", "job": {"kind": "checker"}}
        job = builders.build_jobs(ctx, step)[0]
        prompt = ctx.read(job["prompt_file"])
        self.assertEqual((job["family"], job["cwd"]), ("claude", "repo"))  # the host vendor reads the repository
        self.assertIn(CODEBASE_HEADING, job["contract"]["headings"])
        for text in (CODEBASE_HEADING, REPO_LINE, "LANDSCAPE_SECRET"):
            self.assertIn(text, prompt)
        return step, job

    def assert_rebuilt_for(self, ctx, fb, fam):
        prompt = ctx.read(fb["prompt_file"])
        for text in (CODEBASE_HEADING, "Codebase fit", REPO_LINE, "LANDSCAPE_SECRET"):
            self.assertNotIn(text, prompt)
        self.assertFalse(pv.contains_code(prompt))
        self.assertEqual((fb["family"], fb["cwd"], fb["repo_root"], fb["provisional"], fb["fallback"]),
                         (fam, "empty", None, True, []))
        self.assertNotIn("read", fb["tools"])
        self.assertTrue(fb["privacy"]["code_filtered"])
        self.assertIsNone(adapter.policy_check(fb, {}, ctx.state, "claude"))
        self.assertEqual(ctx.read_json("jobs/%s.json" % fb["id"]), fb)
        self.assertEqual(fb["input_digest"], builders.input_digest(fb, prompt))
        return prompt

    def test_a_check_for_another_vendor_is_rebuilt_without_the_codebase_ask(self):
        ctx = self.software()
        step, job = self.check_job(ctx)
        fb = builders.fallback_job(ctx, step, job, "gpt")
        self.assertEqual((fb["id"], fb["out"], fb["template"]), ("7.1-I-001-fb-gpt", job["out"], "CHECK"))
        prompt = self.assert_rebuilt_for(ctx, fb, "gpt")
        self.assertIn("Run no shell commands and read no local files", prompt)
        self.assertNotIn(CODEBASE_HEADING, fb["contract"]["headings"])
        self.assertTrue(validate.check_contract(CHECK_ANSWER, fb["contract"], ctx.run_dir)[0])

    def test_a_grounding_job_for_another_vendor_is_rebuilt(self):
        ctx = self.software()
        ctx.write("01_FRAME.md", "# FRAME: x\n## Job statement\nWhen x.\n## Problem\nHow might we y?\n")
        step = {"id": "3.1", "fanout": "ground", "job": {"kind": "researcher"}}
        job = builders.build_jobs(ctx, step)[0]
        self.assertEqual((job["family"], job["cwd"]), ("claude", "repo"))
        self.assertIn(REPO_LINE, ctx.read(job["prompt_file"]))
        fb = builders.fallback_job(ctx, step, job, "gpt")
        self.assertEqual(fb["template"], "P-GROUND")
        self.assert_rebuilt_for(ctx, fb, "gpt")

    def test_a_same_vendor_fallback_is_still_a_copy(self):
        ctx = self.software()
        step, job = self.check_job(ctx)
        fb = builders.fallback_job(ctx, step, job, "claude-alt")
        self.assertEqual(ctx.read(fb["prompt_file"]), ctx.read(job["prompt_file"]))
        self.assertEqual(fb["contract"], job["contract"])

    def test_a_job_its_step_no_longer_yields_is_copied_and_filtered(self):
        ctx = self.software()
        _step, job = self.check_job(ctx)
        fb = builders.fallback_job(ctx, {"id": "7.1"}, job, "gpt")  # no fanout: nothing to rebuild it from
        prompt = ctx.read(fb["prompt_file"])
        self.assertNotIn("LANDSCAPE_SECRET", prompt)
        self.assertFalse(pv.contains_code(prompt))


# ================================================================ item 5: architecture judges

def assign(host, fams, mode="standard"):
    F = seats.family_list(host, list(fams))
    return seats.assign("2026-09-23-x", host, F, dict((f, tl.WEB.get(f, False)) for f in F), mode, "product")


def eligible(s, author):
    return [j for j in s["arch_judges"] if base_family(j) != base_family(author)]


class ArchJudgeSeatTests(unittest.TestCase):
    def test_four_families_standard_seat_every_family_as_a_judge(self):
        for mode in ("standard", "proposal"):
            s = assign("claude", ALL, mode)
            self.assertEqual(s["arch_authors"], ["gpt", "kimi", "glm"])
            self.assertEqual(s["arch_judges"], ["claude", "gpt", "kimi", "glm"], mode)
            for author in s["arch_authors"]:
                self.assertEqual(len(eligible(s, author)), 3, (mode, author))
        s = assign("gpt", ALL)
        self.assertEqual(s["arch_judges"], ["gpt", "claude", "kimi", "glm"])

    def test_three_families_and_quick_are_unchanged(self):
        self.assertEqual(assign("claude", ("claude", "gpt", "kimi"))["arch_judges"], ["claude", "gpt", "kimi"])
        self.assertEqual(assign("claude", ALL, "quick")["arch_judges"], ["claude"])
        self.assertEqual(assign("claude", ("claude", "gpt", "kimi"), "quick")["arch_judges"], ["claude"])
        self.assertEqual(assign("claude", ALL, "deep")["arch_judges"], list(ALL))

    def test_every_candidate_has_two_eligible_judges_where_families_allow(self):
        import itertools
        for mode in ("standard", "proposal", "deep"):
            for n in range(1, 5):
                for fams in itertools.combinations(ALL, n):
                    for host in fams:
                        s = assign(host, fams, mode)
                        for author in s["arch_authors"]:
                            self.assertGreaterEqual(len(eligible(s, author)), min(2, n - 1), (mode, fams, host, s))


if __name__ == "__main__":
    unittest.main()
