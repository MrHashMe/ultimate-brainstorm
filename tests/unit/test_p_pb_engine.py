"""Phase P (PB-engine), the round-7 findings on ub.py's variant inference and the engine's run.json shape check
(KIT_SPEC 4.11, 6.10).

- variant inference: a product subject with its own modifier ('our app FOR nurses needs a marketing campaign', 'my
  startup IN Dubai needs a brand', 'the platform THAT we launched needs ...') keeps the approach variant, as kit 2.0.3
  had it: a main verb ends the subject's clause, so the subject's own link word leads to no approach phrase; a verb
  right after a relative word belongs to the relative clause ('an app that needs no ads' stays a product)
- a run.json whose interrupt, supersede journal, families, seats, host or exec.wait_s hold a value of the wrong type
  gives `continue` (bare or of that run) and `next` the BLOCKED card naming that run.json, never an internal error;
  every seats layout a run writes (quick/standard/deep/proposal, one to four families, a v1 migration) still loads
"""

import io
import json
import os
import shutil
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fixtures", "engine"))
import engine_testlib as tl  # noqa: E402

from ublib import textio  # noqa: E402
from ublib.engine import migrate  # noqa: E402
from ublib.engine import state as st  # noqa: E402

sys.path.insert(0, tl.SCRIPTS)
import ub  # noqa: E402


class Base(tl.EngineTestCase):
    def run_ub(self, *args):
        out = io.StringIO()
        with mock.patch.object(sys, "stdout", out):
            rc = ub.main([str(a) for a in args], deps=tl.FakeDeps(detect=tl.fake_detect()))
        text = out.getvalue()
        return rc, (json.loads(text) if text.strip().startswith("{") else text)


# ------------------------------------------------------------------------------------------------ variant inference

# (topic, variant in a git repo with source files, what kit 2.0.3 (4d4991b) / T5b (tree 5aff285) / T0 (tree 284bfbe)
# inferred): the Phase O reviewers' subject-with-modifier topics and the guards that must stay product
TABLE = [
    # a product subject with a prepositional or relative modifier, then the main verb and the approach work
    ("our app for nurses needs a marketing campaign", "marketing", "marketing/product/product"),
    ("our SaaS product for dentists needs a go-to-market campaign", "marketing", "marketing/product/product"),
    ("my startup for pet owners needs a brand and a marketing plan", "marketing", "marketing/product/product"),
    ("our platform for small shops needs a brand refresh", "marketing", "marketing/product/product"),
    ("my app for runners needs a launch campaign", "marketing", "marketing/product/product"),
    ("our app for runners needs a marketing plan", "marketing", "marketing/product/product"),
    ("my startup in Dubai needs a brand", "marketing", "marketing/product/product"),
    ("a SaaS for dentists needs a go-to-market campaign", "marketing", "marketing/product/product"),
    ("our SaaS for dentists needs a go-to-market plan", "marketing", "product/product/product"),
    ("my business in Austin needs Facebook ads", "marketing", "marketing/product/product"),
    ("my bakery business in Leeds wants an ad campaign", "marketing", "marketing/product/product"),
    ("the startup that I cofounded needs a marketing strategy", "marketing", "marketing/product/product"),
    ("the platform that we launched needs a marketing strategy", "marketing", "marketing/product/product"),
    ("the app that we built for nurses needs a marketing campaign", "marketing", "marketing/product/product"),
    ("a startup that I run needs a brand", "marketing", "marketing/product/product"),
    ("our startup which sells candles needs an ad campaign", "marketing", "marketing/product/product"),
    ("our fintech app with 10k users needs a marketing campaign", "marketing", "marketing/product/product"),
    ("our app with 50k users wants an ad campaign on TikTok", "marketing", "marketing/product/product"),
    ("my product on Shopify needs a better brand", "marketing", "marketing/product/product"),
    ("my e-commerce business for handmade jewelry needs a marketing strategy", "marketing",
     "marketing/product/product"),
    ("my business with 3 employees wants a brand", "marketing", "marketing/product/product"),
    ("our tool for teachers requires a rebrand campaign", "marketing", "marketing/product/product"),
    ("my SaaS for gyms lacks a brand", "marketing", "marketing/product/product"),
    ("our app for nurses is launching an ad campaign", "marketing", "marketing/product/product"),
    ("our app for nurses has no brand yet", "marketing", "marketing/product/product"),
    ("our product for dentists, a scheduling tool, needs ads", "marketing", "marketing/product/product"),
    ("our startup, a tool for farmers, wants ads", "marketing", "marketing/product/product"),
    ("we run a SaaS for HR teams and need a go-to-market plan", "marketing", "product/product/product"),
    ("we built a platform for freelancers and need a marketing plan", "marketing", "marketing/product/product"),
    ("we are a startup in the edtech space and want a brand", "marketing", "marketing/product/product"),
    ("we sell apps to schools and need ads", "marketing", "marketing/product/product"),
    ("our startup for pet owners needs a naming shortlist", "naming", "naming/product/product"),
    ("a startup in Berlin wants naming ideas", "naming", "naming/product/product"),
    ("our app for nurses deserves a better name for the store", "naming", "naming/product/product"),
    ("our startup in Berlin needs a name for its second product", "naming", "naming/product/product"),
    ("our app for diabetics needs a user study", "research", "research/product/product"),
    ("my startup in healthcare wants a white paper", "research", "research/product/product"),
    ("my startup in healthcare wants a white paper on AI triage", "research", "research/product/product"),
    ("our product for nurses needs a research paper to back its claims", "research", "research/product/product"),
    ("our app for nurses needs a research paper on its outcomes", "research", "research/product/product"),
    ("a startup that helps farmers wants a white paper", "research", "research/product/product"),
    ("our app for kids needs a story about a dragon mascot", "creative", "creative/product/product"),
    ("our app for kids needs a short story for its mascot", "creative", "creative/product/product"),
    # the phrase names what the product handles: a verb in the relative clause, 'need of', a product after the verb
    ("an app that needs no ads", "product", "marketing/product/product"),
    ("a tool for shops that need a brand", "product", "marketing/product/product"),
    ("a platform where artists need marketing campaigns", "product", "marketing/product/product"),
    ("a platform for teams who really need marketing campaigns", "product", "marketing/product/product"),
    ("an app where users have a brand page", "product", "marketing/product/product"),
    ("a tool for small shops in need of a brand", "product", "marketing/product/product"),
    ("a SaaS that runs ad campaigns for dentists", "product", "marketing/product/product"),
    ("a startup that wants to build a tool for branding small shops", "product", "product/product/product"),
    ("I want a tool for branding small shops", "product", "general/product/product"),
    ("my idea is an app for ad campaigns", "product", "marketing/product/product"),
    ("our startup needs an app for tracking ad campaigns", "product", "marketing/product/product"),
]
# Phase Q rows (topic, variant, what T6 (tree 284bfbe) / T7 (tree 346e513) inferred): a verb in a `whose` or
# subordinate clause is that clause's own; plural naming and marketing keywords count (KIT_SPEC 4.11)
TABLE_Q = [
    ("a booking app for salons whose owners have no marketing skills", "product", "product/marketing"),
    ("a scheduling tool for clinics whose staff have no time for branding", "product", "product/marketing"),
    ("a CRM tool for realtors whose listings need ads", "product", "product/marketing"),
    ("a SaaS for landlords whose tenants need a user study", "product", "product/research"),
    ("a platform for musicians whose fans want lyrics", "product", "product/creative"),
    ("a tool for startups whose founders need a name for the company", "product", "product/naming"),
    ("an app for gyms since most gyms have no marketing team", "product", "product/marketing"),
    ("a tool for farmers because farmers lack branding", "product", "product/marketing"),
    ("an app for teachers while their students need a short story every week", "product", "product/creative"),
    ("a booking app for salons that owners use for marketing", "product", "product/product"),
    ("my startup since 2015 needs a brand", "marketing", "marketing/marketing"),
    ("names for my pet grooming business", "naming", "product/product"),
    ("company names for a vegan bakery", "naming", "general/general"),
    ("product names for our meditation app", "naming", "product/product"),
    ("two brands for my bakery chain", "marketing", "general/general"),
    ("a brand monitoring SaaS", "product", "product/product"),
    ("a tool that suggests names for babies", "product", "product/product"),
    ("a platform that tracks brands for retailers", "product", "product/product"),
    ("a brands monitoring tool", "product", "product/product"),
]


class VariantTable(Base):
    def test_every_topic(self):
        os.makedirs(os.path.join(self.project, ".git"))  # a source repo: the software rule is live
        textio.write_text_atomic(os.path.join(self.project, "main.py"), "print('x')\n")
        wrong = [(topic, want, ub.infer_variant(topic, cwd=self.project)) for topic, want, _ in TABLE + TABLE_Q
                 if ub.infer_variant(topic, cwd=self.project) != want]
        self.assertEqual(wrong, [])

    def test_full_auto_init_plans_the_approach(self):
        # full-auto nobody sees G0: a marketing topic whose subject product has a 'for <audience>' modifier got the
        # 8 system-architecture steps of stage 12
        rc, card = self.run_ub("init", "--host", "claude-code", "--text",
                               "full-auto quick our app for nurses needs a marketing campaign", "--root", self.project,
                               "--no-preflight", "--json")
        s = st.load(card["run"], persist=False)
        self.assertEqual((s["variant"], s["build_type"], s["options"]["variant_inferred"]),
                         ("marketing", "approach", True))

    def test_linear(self):
        for flood in ("our app for runners needs " * 5000 + "a marketing plan", "that x needs " * 10000 + "ads",
                      "app for " * 20000 + "a marketing plan", "needs of " * 20000 + "ads"):
            ub.infer_variant(flood)  # quadratic scans of 100-200k characters would take minutes


# ------------------------------------------------------------------------------------------------ run.json shapes

class RunJsonInnerTypes(Base):
    SHAPES = ({"interrupt": "x"}, {"interrupt": []}, {"supersede": "x"}, {"supersede": ["x"]},
              {"families": {"gpt": "x"}}, {"families": {"gpt": None}}, {"seats": {"screen_judges": 5}},
              {"seats": {"families": [5]}}, {"seats": {"generators": []}}, {"seats": {"rr_next": "x"}},
              {"host": {"agent": 5, "family": 5}}, {"exec": {"wait_s": "x"}}, {"seats": {"host": 5}},
              {"seats": {"s1_engine": []}}, {"seats": {"arch_writer": {}}}, {"seats": {"single_family": "no"}},
              {"seats": {"arch_same_family": 1}})

    def assert_blocked(self, card, shape):
        self.assertEqual(card["type"], "BLOCKED", (shape, card))
        self.assertNotIn("internal error", card["say"], shape)
        self.assertIn("2026-09-27-odd/run.json has an unknown schema", card["say"], shape)
        self.assertIn("ub list --json", card["fix"][0], shape)

    def test_continue_and_next_name_the_run(self):
        root = os.path.join(self.project, "brainstorm")
        good = self.make_ctx(run_name="2026-09-26-good")
        st.save(good.run_dir, good.state)
        os.utime(st.run_json_path(good.run_dir), (1e9, 1e9))  # older: a bare continue picks the odd run
        odd = os.path.join(root, "2026-09-27-odd")
        for shape in self.SHAPES:
            for args in (["continue", "--root", root, "--host", "claude-code"], ["continue", odd], ["next", odd]):
                shutil.rmtree(odd, True)  # no PROGRESS.md or lock left by the command before
                os.makedirs(odd)
                body = {"schema": 2, "status": "active", "topic": "odd"}
                body.update(shape)
                textio.write_json_atomic(st.run_json_path(odd), body)
                rc, card = self.run_ub(*(args + ["--json"]))
                self.assert_blocked(card, (shape, args))
            rc, out = self.run_ub("list", "--root", root, "--json")
            self.assertEqual((rc, len(out["runs"])), (0, 2), (shape, out))

    def test_every_layout_a_run_writes_loads(self):
        saved = []
        orig = st.save

        def spy(run_dir, state):
            saved.append(json.loads(json.dumps(state)))
            return orig(run_dir, state)
        with mock.patch.object(st, "save", spy):
            for n, fams in enumerate((tl.FAMS, ("claude", "gpt"), ("claude",))):
                for mode in ("quick", "standard", "deep", "proposal"):
                    ctx = self.make_ctx(mode=mode, families=fams, run_name="r-%d-%s" % (n, mode))
                    saved.append(json.loads(json.dumps(ctx.state)))
            ctx = tl.full_auto_ctx(self, mode="quick", variant="growth", families=("claude", "gpt"), run_name="q")
            self.assertEqual(tl.drive(ctx)["type"], "DONE")
        for sub in ("2026-01-02-done-run", "2026-01-10-habit-coach"):  # v1 runs, migrated
            run = os.path.join(self.tmp, sub)
            shutil.copytree(tl.fixture_path("v1_run", sub), run)
            saved.append(json.loads(json.dumps(migrate.migrate_v1(run))))
        self.assertGreater(len(saved), 20)
        self.assertEqual([s.get("run") for s in saved if not st._shape_ok(s)], [])
        # the nulls a run writes: no interrupt, no supersede journal pending
        self.assertTrue(st._shape_ok({"interrupt": None, "supersede": None, "host": {"agent": None, "family": None}}))


if __name__ == "__main__":
    unittest.main()
