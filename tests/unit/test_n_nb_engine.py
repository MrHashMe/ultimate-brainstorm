"""Phase N (NB-engine), the round-6 findings on ub.py and the engine's state and migrate code (KIT_SPEC 4.2, 4.11, 6.3,
6.10).

- variant inference: an approach phrase in a product topic leaves it a product only when it names what the product
  handles (a link or relative word right after a product word leads to it, or it modifies the product word right
  after it); the product as the subject, a modifier or an object keeps the approach variant, as kit 2.0.3 had it. The
  plurals features, APIs, bugs and conversions count after any of the change words KIT_SPEC 4.11 lists
- a run.json whose steps, gates or other objects hold a value of the wrong type never breaks `ub list` or a bare `ub
  continue`; `continue` of that run is BLOCKED with its run.json path and a fix
- a dead run kit 2.0.3 left (its K6 kill only in 08_DECISION.md) renders its documents, the handoff seed and the G14
  copies under docs/<run>/ again, once, on the next `continue` or the same MISSED again, with no paid call
"""

import io
import json
import os
import re
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fixtures", "engine"))
import engine_testlib as tl  # noqa: E402

from ublib import textio  # noqa: E402
from ublib.engine import handoff, render  # noqa: E402
from ublib.engine import state as st  # noqa: E402

sys.path.insert(0, tl.SCRIPTS)
import ub  # noqa: E402


class Base(tl.EngineTestCase):
    def run_ub(self, *args, **kw):
        out = io.StringIO()
        with mock.patch.object(sys, "stdout", out):
            rc = ub.main([str(a) for a in args], deps=kw.get("deps") or tl.FakeDeps(detect=tl.fake_detect()))
        text = out.getvalue()
        return rc, (json.loads(text) if text.strip().startswith("{") else text)


# ------------------------------------------------------------------------------------------------ variant inference

# (topic, variant in a git repo with source files, what kit 2.0.3 / T4 (tree 0bbbf47) / T0 (tree 5aff285) inferred):
# every topic of the round-6 findings and of the Phase J and L variant tests, the KIT_SPEC 4.11 examples and a few
# more forms of the same rules
TABLE = [
    # the product as subject, modifier or object of the approach work
    ("our SaaS product needs a go-to-market campaign", "marketing", "marketing/marketing/product"),
    ("product launch campaign for our new running shoes", "marketing", "marketing/marketing/product"),
    ("my startup needs a brand and a marketing plan", "marketing", "marketing/marketing/product"),
    ("app store ads for our meditation app", "marketing", "marketing/marketing/product"),
    ("naming our new budgeting app", "naming", "naming/naming/product"),
    ("a startup naming shortlist", "naming", "naming/naming/product"),
    ("my business wants a research paper on remote work", "research", "research/research/product"),
    ("advertising our app on TikTok", "marketing", "product/marketing/product"),
    ("branding our coffee startup", "marketing", "product/marketing/product"),
    ("a research paper comparing note-taking apps", "research", "research/research/product"),
    ("a white paper comparing our platform with rivals", "research", "research/research/product"),
    ("an ad campaign announcing our new app", "marketing", "marketing/marketing/product"),
    ("a launch campaign for the product", "marketing", "marketing/marketing/marketing"),
    ("a user study of how nurses use our scheduling app", "research", "research/research/research"),
    ("our platform: a user study on why nurses churn", "growth", "growth/growth/growth"),
    ("a literature review of mobile health apps", "research", "general/research/research"),
    ("marketing our new meditation app", "marketing", "marketing/marketing/product"),
    ("my startup wants to run an ad campaign", "marketing", "marketing/marketing/product"),
    ("a name for startups", "naming", "naming/naming/naming"),
    # the plurals after any change word
    ("add search features", "software", "general/software/software"),
    ("improve search features", "software", "general/software/general"),
    ("increase the export features", "software", "general/software/general"),
    ("improve the export features", "software", "general/software/general"),
    ("lift features", "software", "general/software/general"),
    ("boost our APIs", "software", "general/software/software"),
    ("raise bugs", "software", "general/software/general"),
    ("improve bugs", "software", "general/software/general"),
    ("boost checkout conversions", "growth", "general/growth/growth"),
    ("fix checkout conversions", "growth", "general/growth/general"),
    ("add checkout conversions", "growth", "general/growth/general"),
    ("implement conversions", "growth", "general/growth/general"),
    ("ship conversions", "growth", "general/growth/general"),
    ("an app with social features", "product", "product/software/product"),
    ("a tool that tracks conversions", "product", "general/growth/product"),
    # KIT_SPEC 4.11 examples
    ("fix bugs in the export", "software", "general/software/software"),
    ("our APIs are slow", "software", "general/software/software"),
    ("a name for my app", "naming", "naming/naming/naming"),
    ("a thesis writing app", "product", "product/research/product"),
    ("a brand monitoring SaaS", "product", "marketing/marketing/product"),
    ("public APIs for travel agents", "general", "general/software/general"),
    ("players squash bugs", "general", "general/software/general"),
    # what a product handles or what modifies it
    ("a marketing automation platform", "product", "marketing/marketing/product"),
    ("a brand design tool", "product", "marketing/marketing/product"),
    ("our startup needs a brand monitoring app", "product", "marketing/marketing/product"),
    # Phase L (test_l_lc_engine_cli_state VariantInference)
    ("a habit tracker app with social features", "product", "product/software/product"),
    ("a meal planning app with offline features", "product", "product/software/product"),
    ("a SaaS that aggregates public APIs for travel agents", "product", "product/software/product"),
    ("a marketplace app for rare plants with auction features", "product", "product/software/product"),
    ("a kids game where players squash bugs", "general", "general/software/general"),
    ("a tool that tracks e-commerce conversions", "product", "general/growth/product"),
    ("a unit conversions calculator app", "product", "product/growth/product"),
    ("an app that suggests songs for workouts", "product", "product/creative/product"),
    ("an app that reads stories about local history", "product", "product/creative/product"),
    ("a platform to find films about climate", "product", "product/creative/product"),
    ("an app that writes poems for birthday cards", "product", "product/creative/product"),
    ("a marketplace app for novels about sailing", "product", "product/creative/product"),
    ("a streaming app for films for kids", "product", "product/creative/product"),
    ("a karaoke app with songs for kids", "product", "product/creative/product"),
    ("a podcast app for stories about entrepreneurs", "product", "product/creative/product"),
    ("a tool to organize research papers", "product", "general/research/product"),
    ("an app that summarizes papers about AI", "product", "product/research/product"),
    ("a platform for clinical studies on sleep", "product", "product/research/product"),
    ("a thesis writing app for grad students", "product", "product/research/product"),
    ("an app that blocks adverts", "product", "product/marketing/product"),
    ("a tool for branding small shops", "product", "general/marketing/product"),
    ("an app that plans campaigns for tabletop RPGs", "product", "product/marketing/product"),
    ("add social features to our app", "software", "product/software/software"),
    ("fix bugs in the checkout flow", "software", "general/software/software"),
    ("migrate our APIs to GraphQL", "software", "general/software/software"),
    ("refactor the billing api", "software", "software/software/software"),
    ("a new feature for the export page", "software", "software/software/software"),
    ("improve our conversions", "growth", "general/growth/growth"),
    ("reduce churn in my SaaS product", "growth", "growth/growth/growth"),
    ("a name for my budgeting app", "naming", "naming/naming/naming"),
    ("songs for a children's album", "creative", "general/creative/creative"),
    ("poems for my grandmother's funeral", "creative", "general/creative/creative"),
    ("a marketing campaign for my SaaS product", "marketing", "marketing/marketing/marketing"),
    ("a go-to-market plan for a B2B SaaS tool", "marketing", "product/marketing/marketing"),
    ("a user study of triage apps", "research", "research/research/research"),
    # Phase J (test_j_engine_cli VariantInference) and test_engine_pipeline
    ("a study planner app for nursing students", "product", "research/product/product"),
    ("brand-new shift scheduling app for nurses", "product", "marketing/product/product"),
    ("an ad-free reading app for kids", "product", "marketing/product/product"),
    ("user story mapping tool for agile teams", "product", "creative/product/product"),
    ("state of the art triage app", "product", "creative/product/product"),
    ("a paper trading app for students", "product", "research/product/product"),
    ("an app to find study partners", "product", "research/product/product"),
    ("an art marketplace app", "product", "creative/product/product"),
    ("a case study library for SaaS founders", "product", "research/product/product"),
    ("a film photography app", "product", "creative/product/product"),
    ("apps for night-shift nurses", "product", "general/product/product"),
    ("improve onboarding activation", "growth", "growth/growth/growth"),
    ("a name for my bakery", "naming", "naming/naming/naming"),
    ("a research question about sleep and shift work", "research", "research/research/research"),
    ("hypotheses for why nurses quit", "research", "research/research/research"),
    ("a study of burnout in ICU nurses", "research", "research/research/research"),
    ("ad campaign for a dental clinic", "marketing", "marketing/marketing/marketing"),
    ("ads for my yoga studio", "marketing", "marketing/marketing/marketing"),
    ("a brand for a coffee roaster", "marketing", "marketing/marketing/marketing"),
    ("a short story about a lighthouse keeper", "creative", "creative/creative/creative"),
    ("a song for my sister's wedding", "creative", "creative/creative/creative"),
    ("a film about climate migration", "creative", "creative/creative/creative"),
    ("an art installation for a hospital lobby", "creative", "creative/creative/creative"),
    ("fix the api bug", "software", "software/software/software"),
    ("a novel way to cut waiting times", "general", "general/general/general"),
    ("a SaaS for dentists", "product", "product/product/product"),
]


class VariantTable(Base):
    def test_every_topic(self):
        os.makedirs(os.path.join(self.project, ".git"))  # a source repo: the software rule is live
        textio.write_text_atomic(os.path.join(self.project, "main.py"), "print('x')\n")
        wrong = [(topic, want, ub.infer_variant(topic, cwd=self.project)) for topic, want, _ in TABLE
                 if ub.infer_variant(topic, cwd=self.project) != want]
        self.assertEqual(wrong, [])

    def test_full_auto_init_plans_the_approach(self):
        # full-auto nobody sees G0: the variant stuck, with the 8 system-architecture steps of stage 12
        rc, card = self.run_ub("init", "--host", "claude-code", "--text",
                               "full-auto quick a research paper comparing note-taking apps", "--root", self.project,
                               "--no-preflight", "--json")
        s = st.load(card["run"], persist=False)
        self.assertEqual((s["variant"], s["build_type"], s["options"]["variant_inferred"]),
                         ("research", "approach", True))


# ------------------------------------------------------------------------------------------------ run.json shapes

class RunJsonWrongTypes(Base):
    SHAPES = ({"steps": {"0.1": None}}, {"gates": {"G13": "x"}}, {"steps": []}, {"options": []},
              {"gates": {"G13": {"state": "answered", "answer": "approve"}}}, {"notes": "x"}, {"choice": None})

    def test_list_and_a_bare_continue_name_the_run(self):
        root = os.path.join(self.project, "brainstorm")
        good = self.make_ctx(run_name="2026-09-26-good")
        st.save(good.run_dir, good.state)
        os.utime(st.run_json_path(good.run_dir), (1e9, 1e9))  # older: a bare continue picks the odd run
        odd = os.path.join(root, "2026-09-27-odd")
        os.makedirs(odd)
        for shape in self.SHAPES:
            body = {"schema": 2, "status": "active", "topic": "odd"}
            body.update(shape)
            textio.write_json_atomic(st.run_json_path(odd), body)
            rc, out = self.run_ub("list", "--root", root, "--json")
            self.assertEqual(rc, 0, (shape, out))
            self.assertEqual([(os.path.basename(r["run"]), r["status"]) for r in out["runs"]],
                             [("2026-09-27-odd", "active"), ("2026-09-26-good", "active")], shape)
            rc, card = self.run_ub("continue", "--root", root, "--host", "claude-code", "--json")
            self.assertEqual(card["type"], "BLOCKED", (shape, card))
            self.assertNotIn("internal error", card["say"], shape)
            self.assertIn("2026-09-27-odd/run.json has an unknown schema", card["say"], shape)
            self.assertIn("ub list --json", card["fix"][0], shape)


# ------------------------------------------------------------------------------------------------ 2.0.3 dead run

K6 = "Killed: %s - K6 (the pre-registered probe missed)"
DOCS = ("11_PROPOSAL/PROPOSAL.md", "11_PROPOSAL/ONE-PAGER.md", "10_ARCHITECTURE/README.md", "12_HANDOFF.md")


@unittest.skipUnless(tl.stubs_available(), "B4 stubs or B2 bs.py missing")
class Dead203RunRendersItsDocumentsAgain(Base):
    def setUp(self):
        super().setUp()
        g14 = mock.patch.object(handoff, "g14", lambda ctx: {"handoff": "ce", "publish": True})
        g14.start()
        self.addCleanup(g14.stop)

    def dead_203(self):
        """A finished run as kit 2.0.3 left it after `probe-result MISSED` with no runner-up: the K6 line only in
        08_DECISION.md, run.json probe {result, at} with no idea and no decision_log, every document as it was."""
        ctx = tl.full_auto_ctx(self, mode="quick", variant="growth", run_name="2026-09-01-n-dead")
        self.assertEqual(tl.drive(ctx)["type"], "DONE")
        s = ctx.state
        s["kit_version"] = "2.0.3"
        s["choice"]["runner_up"] = None
        s["probe"] = {"result": "MISSED", "at": "2026-09-02T10:00:00Z"}
        s.pop("decision_log", None)
        ctx.write("08_DECISION.md", ctx.read("08_DECISION.md").rstrip() + "\n%s\n" % (K6 % s["choice"]["idea"]))
        probe = re.sub(r"(?m)^RESULT: PENDING\s*$\n?", "", ctx.read("09_PROBE.md"))
        ctx.write("09_PROBE.md", probe.rstrip() + "\n\n## Result\n1 of 10\nRESULT: MISSED (K6)\n")
        st.save(ctx.run_dir, s)
        for rel in DOCS:
            self.assertNotIn(render.KILLED_BANNER, ctx.read(rel), rel)
        return ctx

    def assert_killed(self, ctx, deps):
        s = st.load(ctx.run_dir, persist=False)
        self.assertTrue(render.k6_dead(s))
        for rel in DOCS:
            self.assertIn(render.KILLED_BANNER, ctx.read(rel), rel)
        seed = ctx.read("handoff/ce-seed.md")
        self.assertNotIn(handoff.CLOSING, seed)
        self.assertIn(handoff.K6_WARNING, seed)
        published = textio.read_text(os.path.join(self.project, "docs", s["run"], "11_PROPOSAL", "PROPOSAL.md"))
        self.assertIn("Status: %s" % render.KILLED_BANNER, published)
        self.assertEqual(ctx.read("08_DECISION.md").count(K6 % s["choice"]["idea"]), 1)
        ledger = textio.read_text(os.path.join(self.project, "brainstorm", "LEDGER.md"))
        self.assertEqual(ledger.count("probe missed"), 1)  # the row kit 2.0.3 never wrote, once
        self.assertEqual(deps.batch.launched, [])  # no paid call

    def test_continue_renders_them_once(self):
        ctx = self.dead_203()
        deps = tl.stub_deps()
        rc, card = self.run_ub("continue", ctx.run_dir, "--json", deps=deps)
        self.assertEqual((rc, card["type"]), (0, "DONE"), card)
        self.assertIn("PROPOSAL.md (KILLED (K6))", card["show"])
        self.assert_killed(ctx, deps)
        before = textio.read_bytes(st.run_json_path(ctx.run_dir))
        for args in (["continue", ctx.run_dir], ["probe-result", ctx.run_dir, "MISSED"]):
            rc, card = self.run_ub(*(args + ["--json"]), deps=deps)
            self.assertEqual((rc, card["type"]), (0, "DONE"), card)
        self.assertEqual(textio.read_bytes(st.run_json_path(ctx.run_dir)), before)  # nothing re-armed again
        self.assert_killed(ctx, deps)

    def test_the_same_missed_again_renders_them(self):
        ctx = self.dead_203()
        deps = tl.stub_deps()
        rc, card = self.run_ub("probe-result", ctx.run_dir, "MISSED", "--json", deps=deps)
        self.assertEqual((rc, card["type"]), (0, "DONE"), card)
        self.assert_killed(ctx, deps)


if __name__ == "__main__":
    unittest.main()
