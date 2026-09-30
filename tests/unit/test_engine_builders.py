"""B3 engine: job construction from templates (KIT_SPEC 4.4, 4.17, 6.11, 6.12): the template rendering rules, every
prompt and host template resolves every placeholder, host prompt variants end with `OUTPUT FILE:`, contracts follow
templates/manifest.json, and job JSON carries the `stub` facts listed in 4.17."""

import glob
import json
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fixtures", "engine"))
import engine_testlib as tl  # noqa: E402

from ublib import textio  # noqa: E402
from ublib.engine import EngineError, builders, pipeline, registry  # noqa: E402

GUARD = "Do not load or invoke any skill; this prompt is the whole task."
JOB_KEYS = ("schema", "run", "id", "step", "kind", "template", "family", "tier", "prompt_file", "out", "tools", "cwd",
            "repo_root", "timeout_s", "retries", "contract", "schema_file", "split", "fallback", "provisional",
            "privacy", "host_prompt_file", "stub", "input_digest")  # + "chain" when detection resolved one (C13)
KINDS = ("ping", "generator", "researcher", "curator", "judge", "checker", "normalizer", "reviewer", "synthesis",
         "writer", "arch-author", "arch-judge", "rubric", "redteam", "fixer", "frame")
SAMPLE_VARS = {"STRATEGY_ID": "L2", "ARCHETYPE_ID": "C", "REVIEW_LENS": "L2", "CELL": "app | night",
               "IDEA_ID": "I-001", "STANCE": "CRITIC", "OTHER_REVIEW": "## 3. Kill\nx", "LEADER": "A",
               "ARCHETYPE": "fallback archetype", "OTHER_ARCHETYPES": "Boring by default; Cost-minimal",
               "COMPONENT_NAME": "mattpocock-skills:domain-modeling", "DUP_PAIRS": "I-001 ~ I-002"}


def manifest():
    with open(os.path.join(tl.TEMPLATES, "manifest.json"), encoding="utf-8") as f:
        return json.load(f)


class RenderRuleTests(unittest.TestCase):
    def test_choices_comments_lone_lines_and_one_pass(self):
        text = ("line1\n<!-- ub-choices: PICK key=KEY\nA | alpha {{X}}\nB | beta\n-->\n<!-- a comment -->\n"
                "pick: {{PICK}}\n{{EMPTY}}\nkeep {{EMPTY}} inline\nvalue: {{V}}\n")
        vals = {"KEY": "A", "X": "x1", "EMPTY": "", "V": "{{X}} stays"}
        out = builders.render(text, lambda n: vals.get(n), template="T")
        self.assertEqual(out, "line1\npick: alpha x1\nkeep  inline\nvalue: {{X}} stays\n")

    def test_unknown_placeholder_raises(self):
        with self.assertRaises(EngineError) as cm:
            builders.render("{{NOPE}} and {{ALSO}}", lambda n: None, template="T")
        self.assertIn("NOPE", str(cm.exception))
        self.assertIn("ALSO", str(cm.exception))

    def test_fill_doc_returns_none_on_unknown(self):
        self.assertIsNone(builders.fill_doc("<!-- ub-template: X v1 kind=doc -->\n{{A}}\n", {}))
        self.assertEqual(builders.fill_doc("<!-- ub-template: X v1 kind=doc -->\n# {{A}}\n{{B}}\nz\n",
                                           {"A": "a", "B": ""}), "# a\nz\n")


class PromptTemplateTests(tl.EngineTestCase):
    def setUp(self):
        tl.EngineTestCase.setUp(self)
        self.ctx = self.make_ctx(variant="software")
        c = self.ctx
        c.write("01_FRAME.md", "# FRAME: x\n## Job statement\nWhen x.\n## Problem\nHow might we y?\n## Audience / "
                               "boundary\nnurses\n## Hard constraints\n- none\n## Criteria\n| criterion | weight | 1 = "
                               "| 3 = | 5 = |\n|---|---|---|---|---|\n| Value | 60 | low | mid | high |\n| "
                               "Distinctiveness | 40 | obvious | some | far |\n## Axes\n- Moment: day | night\n")
        c.write("criteria.json", '{"Value": 60, "Distinctiveness": 40}')
        c.write("02_CONTEXT.md", "## A. FACTS\n- f\n## A2. DOMAIN TERMS\n- **T** [proposed]: t\n## B. LANDSCAPE\n"
                                 "- l\n## C. SEARCH BOUNDARY\n- s\n")
        c.write("screen/ideas.md", "I-001 | Title one | pitch | mech\n")
        c.write("10_ARCHITECTURE/drivers.json", json.dumps({"quality_goals": [{"id": "QG1", "name": "speed",
                                                                                "weight": 70}],
                                                             "qas": [{"id": "QAS-01", "qg": "QG1"}]}))
        c.write("10_ARCHITECTURE/candidates/map.json", '{"A": {"family": "gpt", "n": "1"}}')
        c.write("10_ARCHITECTURE/candidates/1.json", '{"stack": [{"layer": "db", "component": "store", '
                                                      '"choice": "sqlite", "version": ""}]}')
        c.state["choice"]["idea"] = "I-001"
        c.state["choice"]["arch"] = "A"

    def jc(self, name, host=False):
        return {"family": "claude", "template": name, "vars": dict(SAMPLE_VARS), "item": {"tools": "none"},
                "contract": registry.tcontract(name), "out": "x/out.md", "host": host}

    def test_every_prompt_template_resolves(self):
        names = sorted(n for n in manifest()["prompts"] if n != "GEN-HEADER")
        self.assertGreater(len(names), 40)
        for name in names:
            body = builders.template_text(name)
            text = builders.fill(self.ctx, body, self.jc(name))
            self.assertNotIn("{{", text, name)
            self.assertNotIn("<!--", text, name)
            self.assertNotIn("${", text, name)
            lines = [ln for ln in text.split("\n") if ln.strip()]
            if name not in ("SCREEN-HEADER", "TOURNAMENT-HEADER"):
                self.assertEqual(lines[0], GUARD, name)
            self.assertEqual(lines[-1], "Print only the result.", name)
            host = builders.fill(self.ctx, body, self.jc(name, host=True)).rstrip().split("\n")
            self.assertTrue(host[-1].startswith("OUTPUT FILE: "), name)
            self.assertTrue(host[-1].endswith("/x/out.md"), name)

    def test_choices_pick_the_engine_value(self):
        text = builders.fill(self.ctx, builders.template_text("ARCH-CANDIDATE"), self.jc("ARCH-CANDIDATE"))
        self.assertIn("The approach the other candidates would not pick. The others are: Boring by default; "
                      "Cost-minimal.", text)
        lens = builders.fill(self.ctx, builders.template_text("LENS"), self.jc("LENS"))
        self.assertIn("Remote analogy", lens)
        rev = builders.fill(self.ctx, builders.template_text("ARCH-REVIEW"), self.jc("ARCH-REVIEW"))
        self.assertIn("LENS L2", rev)

    def test_generators_include_the_gen_header(self):
        text = builders.fill(self.ctx, builders.template_text("S3-EDE"), dict(self.jc("S3-EDE"),
                                                                              vars={"STRATEGY_ID": "S3"}))
        self.assertIn("### S3-NN", text)
        self.assertIn("- Moment: day | night", text)
        self.assertEqual(text.count(GUARD), 1)

    def test_every_host_template_argument_resolves(self):
        for name in manifest()["host"]:
            arg = builders.host_argument(self.ctx, name, {"family": "claude", "vars": dict(SAMPLE_VARS),
                                                          "item": {"tools": "none"}})
            self.assertIsNotNone(arg, name)
            self.assertNotIn("{{", arg, name)
            self.assertNotIn("ub-argument", arg, name)

    def test_contracts_follow_the_manifest(self):
        for name, entry in manifest()["prompts"].items():
            if entry.get("contract"):
                self.assertEqual(registry.tcontract(name), entry["contract"], name)
        c = registry.tcontract("ARCH-JUDGE", cover={"ids": ["A"]})
        self.assertEqual(c["cover"], {"ids": ["A"]})
        self.assertEqual(registry.tcontract("NO-SUCH", {"type": "text", "min_chars": 5}), {"type": "text",
                                                                                           "min_chars": 5})


class JobTests(tl.EngineTestCase):
    def test_job_json_shape(self):
        ctx = self.make_ctx()
        step = {"id": "3.1", "stage": 3, "type": "DISPATCH", "fanout": "ground", "job": {"kind": "researcher"}}
        jobs = builders.build_jobs(ctx, step)
        self.assertEqual(len(jobs), 1)
        job = textio.read_json(os.path.join(ctx.run_dir, "jobs", "3.1.json"))
        self.assertEqual(sorted(job), sorted(JOB_KEYS))
        self.assertEqual(job["schema"], 1)
        self.assertEqual(job["kind"], "researcher")
        self.assertEqual(job["family"], "claude")
        self.assertEqual(job["tools"], "web")
        self.assertTrue(re.match(r"^[A-Za-z0-9._-]{1,80}$", job["id"]))
        self.assertTrue(os.path.exists(os.path.join(ctx.run_dir, job["prompt_file"])))
        self.assertEqual(job["privacy"], {"vendor_ok": True, "web_ok": True, "code_ok": True, "code_filtered": False})
        self.assertIsNone(job["host_prompt_file"])
        self.assertEqual(job["run"], textio.to_posix(ctx.run_dir))

    def test_host_chain_writes_the_host_variant(self):
        ctx = self.make_ctx()
        ctx.state["families"]["claude"]["backend"] = "host"
        step = {"id": "3.1", "stage": 3, "type": "DISPATCH", "fanout": "ground", "job": {"kind": "researcher"}}
        job = builders.build_jobs(ctx, step)[0]
        self.assertEqual(job["host_prompt_file"], "prompts/3.1.host.md")
        last = ctx.read(job["host_prompt_file"]).rstrip().split("\n")[-1]
        self.assertEqual(last, "OUTPUT FILE: %s" % textio.to_posix(ctx.path("02_CONTEXT.md")))

    def test_host_variant_for_bs_prompts(self):
        ctx = self.make_ctx()
        text = builders.host_variant(ctx, "judge these\nPrint only the result.\n\nCARDS\n...", "screen/claude.out.json")
        self.assertTrue(text.rstrip().endswith("OUTPUT FILE: %s" % textio.to_posix(ctx.path(
            "screen/claude.out.json"))))
        self.assertNotIn("Print only the result.", text)

    def test_timeouts_and_fallbacks(self):
        ctx = self.make_ctx()
        self.assertEqual(builders.timeout_for(ctx, "writer"), 720)
        self.assertEqual(registry._fallbacks(ctx, "gpt"), ["gpt-alt", "claude"])
        self.assertEqual(registry._fallbacks(ctx, "claude"), ["claude-alt"])
        self.assertEqual(registry._fallbacks(ctx, "gpt-alt"), ["claude"])


@unittest.skipUnless(tl.stubs_available(), "B4 stubs or B2 bs.py missing")
class StubFactsTests(tl.EngineTestCase):
    """A full-auto run driven in-process with B4's stubs; every job's contract validates and carries its 4.17
    facts."""

    def run_mode(self, mode, variant="product"):
        ctx = tl.full_auto_ctx(self, mode=mode, variant=variant, run_name="2026-09-23-%s-%s" % (mode, variant))
        card = tl.drive(ctx)
        self.assertEqual(card["type"], "DONE", card.get("say"))
        self.assertEqual(ctx.deps.batch.invalid, [])
        jobs = [textio.read_json(p) for p in glob.glob(os.path.join(ctx.run_dir, "jobs", "*.json"))]
        return ctx, jobs

    def test_standard_run_stub_facts(self):
        ctx, jobs = self.run_mode("standard")
        by_kind = {}
        for j in jobs:
            self.assertIn(j["kind"], KINDS)
            by_kind.setdefault(j["kind"], []).append(j)
        for j in by_kind["generator"]:
            if j["template"] not in ("EVOLVE", "EVOLVE-CONTRAST"):
                self.assertIn("axes", j["stub"], j["id"])
        cur = [j for j in by_kind["curator"]][0]
        for k in ("aliases", "axes", "primary_aliases"):
            self.assertIn(k, cur["stub"])
        self.assertTrue(cur["stub"]["aliases"])
        for j in by_kind["checker"]:
            self.assertEqual(j["stub"]["idea_id"], j["id"].split("-", 1)[1])
        for j in [j for j in by_kind["reviewer"] if j["template"] == "REVIEWER"]:
            self.assertIn(j["stub"]["stance"], ("ADVOCATE", "CRITIC"))
            self.assertTrue(j["stub"]["idea_id"])
        for j in by_kind["arch-author"]:
            self.assertTrue(j["stub"]["qas_ids"])
            self.assertTrue(j["stub"]["hc_ids"] is not None)
        for j in by_kind["arch-judge"]:
            self.assertTrue(j["stub"]["labels"])
            self.assertIn("time_to_mvp", j["stub"]["criteria"])
        for j in by_kind["writer"]:
            if j["template"].startswith("ARCH-PACKAGE") or j["template"] == "ARCH-DECISIONS":
                for k in ("containers", "qg_ids", "ext_ids", "r_ids"):
                    self.assertIn(k, j["stub"], j["id"])
            if j["template"].startswith("PROPOSAL-") or j["template"] == "EXEC-ONEPAGER":
                for k in ("sections", "adr_numbers", "r_ids", "source_ids"):
                    self.assertIn(k, j["stub"], j["id"])
        for j in by_kind["judge"]:
            self.assertIn("cover", j["contract"])
        # judge prompts carry no alias IDs or origin words
        for j in by_kind["judge"] + by_kind["arch-judge"]:
            text = ctx.read(j["prompt_file"])
            self.assertIsNone(re.search(r"\b(S\d+|G\d+|R\d+|L\d+|H|HP|H2|IMP|S1R)-\d+\b", text), j["id"])
        # every prompt is filled
        for j in jobs:
            self.assertNotIn("{{", ctx.read(j["prompt_file"]), j["id"])

    def test_quick_and_proposal_and_approach_runs(self):
        for mode, variant in (("quick", "product"), ("proposal", "product"), ("standard", "research")):
            ctx, jobs = self.run_mode(mode, variant)
            self.assertTrue(ctx.exists("11_PROPOSAL/PROPOSAL.md"), mode)
            if variant == "research":
                self.assertTrue(ctx.exists("10_ARCHITECTURE/approach.md"))
                self.assertIn("## 6. Approach", ctx.read("11_PROPOSAL/PROPOSAL.md"))


if __name__ == "__main__":
    unittest.main()
