"""Phase J2 (J2B-gates-registry), the cross-package requests on the gates, the registry, bs.py and pipeline.json
(KIT_SPEC 4.12, 6.1, 6.4, 6.8, 7.2).

- G0: a keyword line is read without the punctuation around its words, and a confirmation phrase ('go ahead',
  'Sounds good, let's go!') reads as `go`, so neither becomes a seed idea that 0.3 adds to the user's seeds file
- G1 `skip` keeps a Problem, Obvious or Off-limits the user wrote (the prompts quote them) and puts the SKIPPED line
  above it
- bs.py @checks reads the Rescued: line as the engine does: an ID in the parenthesized reason an older kit wrote there
  is not rescued (and the reading is linear in the line)
- an invalid curation (a key or id listed twice, an empty field) blocks bs.py map (5.2, 5.3m, 5.4m), quick-pick (Q.4)
  and Q.3p with the redo of the curation that wrote it, not the doctor
- P-GROUND asks for one A2 term per line with its source mark, the shape the A2 filter reads
- CHECK section 5 (Codebase fit) is not asked in a software run whose project folder has no git repository
- refs.import_from_quick: a quick-mode `ub import` curates again from Q.3
"""

import os
import re
import sys
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fixtures", "engine"))
import engine_testlib as tl  # noqa: E402

import bs  # noqa: E402
from ublib.engine import EngineError, builders, gates, pipeline, registry  # noqa: E402
from ublib.engine import privacy as pv  # noqa: E402
from ublib.engine import state as st  # noqa: E402


def step(sid):
    return pipeline.step_by_id(pipeline.load_steps(), sid)


# ------------------------------------------------------------------------------------------------ G0 keyword lines

class KickoffConfirmations(tl.EngineTestCase):
    CONFIRMATIONS = ("Go!", "go ahead", "Yes please.", "Sounds good, let's go!", "Let’s go", "`go`", "OK.",
                     "Looks good, thanks!")

    def test_a_confirmation_is_no_seed_idea(self):
        for reply in self.CONFIRMATIONS:
            p = gates.parse_kickoff(reply)
            self.assertEqual(p["seeds"]["ideas"], [], reply)
            self.assertTrue(p.get("confirm"), reply)

    def test_keywords_with_punctuation(self):
        p = gates.parse_kickoff("Standard, guided.\nprivate!")
        self.assertEqual((p.get("mode"), p.get("autopilot"), p.get("private")), ("standard", "guided", True))
        self.assertEqual(p["seeds"]["ideas"], [])
        for reply in ("skip.", "No seeds!", "None."):
            p = gates.parse_kickoff(reply)
            self.assertEqual((p.get("skip_seeds"), p["seeds"]["ideas"]), (True, []), reply)

    def test_seed_ideas_stay_seeds(self):
        p = gates.parse_kickoff("deep learning ideas\n- deep\nGreat, let us go\ngo to the ward: a paper rota")
        self.assertEqual(p["seeds"]["ideas"], ["deep learning ideas", "deep", "Great, let us go",
                                               "go to the ward: a paper rota"])
        self.assertIsNone(p.get("mode"))

    def test_0_3_adds_no_confirmation_to_the_users_seeds_file(self):
        """P2 (JC): 0.3 now merges the G0 reply's seeds into the user's file, so a confirmation read as a seed idea
        landed in the Ideas section the curator reads."""
        ctx = self.make_ctx()
        ctx.write("00_HUMAN_SEEDS.md", st.seeds_doc(ideas=["a shared swap board per ward"]))
        ans, notes, errs = gates.prepare_answer(ctx, "G0", {"reply": "Sounds good, go ahead!"})
        self.assertEqual(errs, [])
        gates.apply(ctx, "G0", ans)
        registry.write_seeds(ctx, ans)
        self.assertEqual(registry.seeds_section(ctx, "Ideas"), "- a shared swap board per ward")
        self.assertTrue(ans["confirm"])

    def test_a_g2c_or_g10_confirmation_is_no_correction(self):
        """'Yes.' at G2c or G10 was a correction appended to the frame (only the bare word confirmed)."""
        for gid in ("G2c", "G10"):
            for reply in ("Yes.", "ok!", "Looks good, thanks!", "Approve."):
                self.assertEqual(gates.parse_reply(gid, reply), {"confirm": True}, (gid, reply))
            self.assertEqual(gates.parse_reply(gid, "No, the users are nurses."),
                             {"confirm": False, "corrections": "No, the users are nurses."})
        self.assertIs(gates.parse_kickoff("web: no.")["privacy"]["web"], False)


# ------------------------------------------------------------------------------------------------ G1 skip

class G1Skip(tl.EngineTestCase):
    def skip(self, seeds):
        ctx = self.make_ctx(autopilot="hands-on")
        ctx.write("00_HUMAN_SEEDS.md", seeds)
        ans, notes, errs = gates.prepare_answer(ctx, "G1", {"reply": "skip"})
        self.assertEqual(errs, [])
        gates.apply(ctx, "G1", ans)
        return ctx

    def test_skip_keeps_the_problem_obvious_and_off_limits(self):
        ctx = self.skip(st.seeds_doc(problem="Nurses swap shifts by phone at 3 a.m.", obvious=["a WhatsApp group"],
                                     off_limits=["anything needing new hardware"]))
        text = ctx.read("00_HUMAN_SEEDS.md")
        self.assertEqual(registry.seeds_section(ctx, "Problem"), "Nurses swap shifts by phone at 3 a.m.")
        self.assertEqual(registry.seeds_section(ctx, "Obvious"), "- a WhatsApp group")
        self.assertEqual(registry.seeds_section(ctx, "Off-limits"), "- anything needing new hardware")
        self.assertRegex(text, r"(?m)^SKIPPED: the user skipped the seeds at G1\n\n## Problem")
        self.assertIn("Off-limits: - anything needing new hardware", registry.brief_text(ctx))
        # the seeds count as given: G1 is not asked again, and bs.py's @seeds is done
        self.assertFalse(registry.PREDICATES["no_seeds"](ctx, None))
        self.assertEqual(bs.seeds_done(ctx.run_dir), (True, ""))

    def test_skip_on_an_empty_file_writes_the_line_alone(self):
        ctx = self.skip(st.seeds_doc())
        self.assertEqual(ctx.read("00_HUMAN_SEEDS.md"), "SKIPPED: the user skipped the seeds at G1\n")


# ------------------------------------------------------------------------------------------------ bs.py @checks

class RescuedLine(tl.EngineTestCase):
    OLD_LINE = ("Rescued: I-012 (it is more practical than I-003 (the cheap one)), I-004 (rescued by the user)\n")

    def screened(self, rescued_line):
        ctx = self.make_ctx()
        ctx.write_json("screen/shortlist.json", {"shortlist": [{"id": "I-001"}, {"id": "I-002"}]})
        ctx.write("04_SHORTLIST.md", "# Shortlist\n\n" + rescued_line)
        return ctx

    def test_an_id_in_an_older_kits_reason_needs_no_check(self):
        ctx = self.screened(self.OLD_LINE)
        for iid in ("I-001", "I-002", "I-012", "I-004"):
            ctx.write("checks/%s.md" % iid, "VERDICT: ADJACENT; DIFFERENTIATOR: d\n")
        self.assertEqual(bs.check_item(ctx.run_dir, "@checks"), (True, ""))
        os.remove(ctx.path("checks", "I-004.md"))
        self.assertEqual(bs.check_item(ctx.run_dir, "@checks"), (False, "no check for I-004"))

    def test_the_rescued_line_is_read_in_linear_time(self):
        deep = 60000
        ctx = self.screened("Rescued: I-006 " + "(" * deep + "I-005" + ")" * deep + " I-007\n")
        t0 = time.time()
        ids = registry.shortlist_ids(ctx)
        self.assertLess(time.time() - t0, 3.0)
        self.assertEqual(ids, ["I-001", "I-002", "I-006", "I-007"])
        self.assertEqual(registry.rescued_ids("Rescued: a) I-001 (b I-002"), ["I-001", "I-002"])  # unbalanced stays


# ------------------------------------------------------------------------------------------------ redo fixes

MERGES_TWICE = {"strategy_family": {"S1": "claude"}, "axes": {},
                "ideas": [{"key": "k", "title": "t", "pitch": "p", "mechanism": "m", "aliases": ["S1-01"],
                           "cluster": "c"},
                          {"key": "k", "title": "t2", "pitch": "p2", "mechanism": "m2", "aliases": ["S1-02"],
                           "cluster": "c"}]}


class CurationRedoFix(tl.EngineTestCase):
    def redo(self, ctx, sid):
        return 'python ub.py redo "%s" %s --yes' % (ctx.run_dir.replace("\\", "/"), sid)

    def blocked(self, ctx, script, sid):
        with self.assertRaises(EngineError) as cm:
            registry.run_script(ctx, script, step(sid))
        return cm.exception

    def test_a_map_of_an_invalid_curation_redoes_that_curation(self):
        ctx = self.make_ctx(deps=tl.FakeDeps(bs=tl.real_bs))
        ctx.write_json("merges.json", MERGES_TWICE)
        e = self.blocked(ctx, "bs_map", "5.2")
        self.assertIn("duplicate mechanism key in merges.json: k", str(e))
        self.assertEqual(e.fix, [self.redo(ctx, "5.1")])

    def test_each_map_step_redoes_its_own_curation(self):
        fake = tl.FakeBs({"map": lambda args, run_dir: (5, "", "merges.json ideas[3] lacks 'aliases'")})
        ctx = self.make_ctx(mode="deep", autopilot="hands-on", deps=tl.FakeDeps(bs=fake))
        self.assertEqual(self.blocked(ctx, "bs_map", "5.4m").fix, [self.redo(ctx, "5.4c")])
        self.assertEqual(self.blocked(ctx, "gap_round_end", "5.3m").fix, [self.redo(ctx, "5.3c")])
        self.assertEqual((ctx.state.get("counters") or {}).get("gap_rounds", 0), 0)  # nothing counted

    def test_another_exit_keeps_the_doctor(self):
        fake = tl.FakeBs({"map": lambda args, run_dir: (4, "", "merges.json missing")})
        ctx = self.make_ctx(deps=tl.FakeDeps(bs=fake))
        self.assertEqual(self.blocked(ctx, "bs_map", "5.2").fix, ["python ub.py doctor --json"])

    def test_a_quick_pick_of_an_invalid_curation_redoes_q_3(self):
        ctx = self.make_ctx(mode="quick", deps=tl.FakeDeps(bs=tl.real_bs))
        ctx.write_json("criteria.json", {"Value": 60, "Feasibility": 40})
        ctx.write_json("quick/curated.json", {"ideas": [{"id": "Q-01", "title": "a"}, {"id": "Q-01", "title": "b"}]})
        e = self.blocked(ctx, "quick_pick", "Q.4")
        self.assertIn("duplicate id in quick/curated.json: Q-01", str(e))
        self.assertEqual(e.fix, [self.redo(ctx, "Q.3")])

    def test_the_quick_screen_redoes_q_3(self):
        ctx = self.make_ctx(mode="quick")
        for ideas, message in (([{"id": "Q-01", "title": "a"}, {"id": "Q-01", "title": "b"}], "appears twice"),
                               ([{"title": "a"}], "an idea without an id"), ([], "has no ideas")):
            ctx.write_json("quick/curated.json", {"ideas": ideas})
            e = self.blocked(ctx, "prepare_quick_screen", "Q.3p")
            self.assertIn(message, str(e))
            self.assertEqual(e.fix, [self.redo(ctx, "Q.3")], message)

    def test_the_blocked_card_names_the_redo(self):
        ctx = self.make_ctx(deps=tl.FakeDeps(bs=tl.real_bs))
        steps = pipeline.load_steps()
        for s in steps[:pipeline.index_of(steps, "5.2")]:
            st.set_step(ctx.state, s["id"], "done")
        ctx.write_json("merges.json", MERGES_TWICE)
        card = pipeline.advance(ctx, steps, 0)
        self.assertEqual((card["type"], card["fix"]), ("BLOCKED", [self.redo(ctx, "5.1")]))


# ------------------------------------------------------------------------------------------------ P-GROUND A2 terms

class GroundTermShape(unittest.TestCase):
    def test_the_prompt_asks_for_the_shape_the_filter_reads(self):
        """Under 'Mark each term's source (proposed | CONTEXT.md)' an answer that grouped its terms under a source
        heading, wrote '(source: FRAME)' or wrapped a definition onto a second line lost every approved term or sent
        part of a CONTEXT.md definition to other vendors. The prompt now names the two one-line forms."""
        text = registry.load_template("P-GROUND")
        a2 = registry.section(text, "A2")
        forms = re.findall(r"^- \*\*Term\*\* \[[^\]\n]+\]: definition$", a2, re.M)
        self.assertEqual(forms, ["- **Term** [proposed]: definition", "- **Term** [CONTEXT.md]: definition"])
        self.assertIn("one line of its own", a2)
        self.assertIn("no tables, numbered lists", a2)
        answer = "\n".join(["## A2. DOMAIN TERMS (today's system)", "These words describe the system as it is today.",
                            forms[0].replace("Term", "Swap").replace("definition", "an exchange of two shifts"),
                            forms[1].replace("Term", "Rota slot").replace("definition", "a fixed shift")])
        self.assertEqual(pv.filter_a2_terms(answer).split("\n")[2:],
                         ["- **Swap** [proposed]: an exchange of two shifts"])
        for form in forms:  # the kit's own prompt text reaches another vendor's researcher as written
            self.assertIn(form, pv.strip_code(text))


# ------------------------------------------------------------------------------------------------ CHECK section 5

class CodebaseFitWithoutGit(tl.EngineTestCase):
    def check_job(self, ctx, origin):
        ctx.write_json("origins.json", {"I-001": origin})
        ctx.write("screen/ideas.md", "I-001 | Ward ledger | Nurses swap on a ledger. | A shared ledger.\n")
        return builders.make_job(ctx, {"id": "7.1"}, registry._check_item(ctx, "I-001"))

    def assert_no_section_5(self, ctx, job):
        self.assertEqual(job["cwd"], "empty")
        self.assertNotIn("## 5. Codebase fit", job["contract"]["headings"])
        prompt = ctx.read(job["prompt_file"])
        self.assertNotIn("Codebase fit", prompt)
        self.assertNotIn("cite file:line", prompt)

    def test_a_software_run_without_git_asks_no_codebase_fit(self):
        ctx = self.make_ctx(variant="software", families=("claude", "gpt"))  # the project folder has no .git
        job = self.check_job(ctx, "human")
        self.assertEqual(job["family"], "claude")
        self.assert_no_section_5(ctx, job)
        ctx = self.make_ctx(variant="growth", families=("claude", "gpt"), privacy={"code": True},
                            run_name="2026-09-27-growth-code")
        job = self.check_job(ctx, "claude")
        self.assertEqual(job["family"], "gpt")
        self.assert_no_section_5(ctx, job)

    def test_a_git_repository_still_asks_it(self):
        os.makedirs(os.path.join(self.project, ".git"))
        ctx = self.make_ctx(variant="software", families=("claude", "gpt"))
        job = self.check_job(ctx, "human")
        self.assertEqual((job["family"], job["cwd"]), ("claude", "repo"))
        self.assertIn("## 5. Codebase fit", job["contract"]["headings"])


# ------------------------------------------------------------------------------------------------ refs

class QuickImportRef(tl.EngineTestCase):
    def test_a_quick_import_curates_again_from_q_3(self):
        self.assertEqual(pipeline.check_data(pipeline.load_data()), [])
        self.assertEqual(pipeline.step_ref("import_from", self.make_ctx(mode="quick")), "Q.3")
        self.assertEqual(pipeline.step_ref("import_from", self.make_ctx(run_name="2026-09-27-std")), "5.1")


if __name__ == "__main__":
    unittest.main()
