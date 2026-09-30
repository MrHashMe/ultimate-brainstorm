"""Phase V (VB) parser checks: fenced 'Fails if' examples reach no reader of kill assumptions (4.5), bare
[ASSUMPTION] tags stay linear on one line, a JSON integer too large for a float is no crash, and extract_json does what
4.5 says about malformed documents. No model call."""

import json
import os
import sys
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fixtures", "engine"))
import engine_testlib as tl  # noqa: E402
import bs  # noqa: E402  (the scripts folder is on sys.path through engine_testlib)
from ublib import lints, textio, validate  # noqa: E402
from ublib.engine import handoff, progress, registry, render, render_arch  # noqa: E402

FENCED = "~~~markdown\n- Fails if FENCED-EXAMPLE nobody pays\n~~~\n"
RED = ("# Red team\n\n## 1. Per finalist\n\n### I-001\n- Fails if clinics refuse to share rosters\n\n"
       "Use this format:\n\n" + FENCED)
CHECK = ("## 1. Prior art\nq\n## 4. Kill-assumptions\nExample:\n" + FENCED
         + "- Fails if wards keep paper rosters\nVERDICT: ADJACENT; DIFFERENTIATOR: ward-visible\n")
BIG = "1" + "0" * 400


class FencedKillAssumptionTests(tl.EngineTestCase):
    def ctx(self):
        ctx = self.make_ctx(run_name="2026-09-28-vb-red")
        ctx.state["choice"] = {"idea": "I-001"}
        ctx.state["finalists"] = ["I-001"]
        ctx.write("screen/ideas.md", "I-001 | Ward ledger | Nurses swap on a ledger. | A shared ledger.\n")
        ctx.write("07_REDTEAM.md", RED)
        ctx.write("checks/I-001.md", CHECK)
        ctx.write("01_FRAME.md", "# Frame\n\n## Job statement\nshare rosters\n")
        return ctx

    def test_no_reader_takes_a_fenced_example(self):
        ctx = self.ctx()
        render_arch.arch_brief(ctx, {"id": "12.1"})
        render.proposal_packs(ctx, {"id": "13.1"})
        pack = ctx.read("11_PROPOSAL/_packs/PACK_C.md").split("## Red-team kill-assumptions", 1)[1]
        texts = {
            # the check's section 4 is quoted whole; its red-team lines are read line by line
            "KILL_ASSUMPTIONS": registry._ph_kill_assumptions(ctx, {}).split("From the red-team:", 1)[1],
            "FINALISTS": registry._ph_finalists(ctx, {}),
            "brief.json": json.dumps(ctx.read_json("10_ARCHITECTURE/brief.json")["kill_assumptions"]),
            "00_BRIEF.md": ctx.read("10_ARCHITECTURE/00_BRIEF.md"),
            "PACK_C": pack.split("\n## ", 1)[0],
            "seed": handoff.seed_text(ctx, "ce"),
        }
        for name, text in texts.items():
            with self.subTest(name):
                self.assertNotIn("FENCED-EXAMPLE", text)
        self.assertIn("Fails if clinics refuse", texts["PACK_C"])
        self.assertIn("Fails if wards keep paper rosters", texts["FINALISTS"])


class LinearAssumptionTests(unittest.TestCase):
    def test_a_line_of_bare_tags_stays_linear(self):
        start = time.perf_counter()
        found = lints.extract_assumptions("x [ASSUMPTION] " * 10000)
        self.assertLess(time.perf_counter() - start, 3.0)  # quadratic: about 18 s on a laptop
        self.assertTrue(found)

    def test_a_tagged_sentence_is_still_read(self):
        self.assertEqual(lints.extract_assumptions("[ASSUMPTION] Users pay monthly fees. Then more."),
                         lints.extract_assumptions("[ASSUMPTION] Users pay monthly fees. Then more." + " x" * 50))


class HugeIntegerTests(tl.EngineTestCase):
    def test_the_progress_block_skips_the_record(self):
        ctx = self.make_ctx(run_name="2026-09-28-vb-ovf")
        os.makedirs(os.path.join(ctx.run_dir, "logs"), exist_ok=True)
        textio.write_text_atomic(os.path.join(ctx.run_dir, "logs", "calls.jsonl"),
                                 '{"status": "ok", "kind": "judge", "duration_s": 12.5}\n'
                                 '{"status": "ok", "kind": "judge", "duration_s": %s}\n' % BIG)
        self.assertEqual(progress.observed_durations(ctx.run_dir), {"judge": [12.5], "all": [12.5]})

    def test_a_criteria_weight_is_dropped_not_raised(self):
        ctx = self.make_ctx(run_name="2026-09-28-vb-ovf2")
        textio.write_text_atomic(os.path.join(ctx.run_dir, "criteria.json"), '{"Value": %s, "Feasibility": 60}' % BIG)
        registry._s_frame_check(ctx, {"id": "2.2"})
        self.assertNotIn("Value", ctx.read_json("criteria.json"))

    def test_bs_reads_it_as_no_number(self):
        self.assertIsNone(bs.as_float(int(BIG)))


class ExtractJsonTests(unittest.TestCase):
    DOC = '{"adrs": [{"title": "A"}, {"title": "B"}'

    def test_a_text_that_starts_with_a_malformed_document_is_refused_in_neutral_words(self):
        for text in (self.DOC, '{"adrs": [{"title": "A"}}, "risks": []}'):
            with self.subTest(text):
                with self.assertRaises(ValueError) as cm:
                    textio.extract_json(text)
                self.assertIn("the text starts with JSON that is not valid", str(cm.exception))
                self.assertNotIn("output", str(cm.exception))

    def test_a_cut_off_draft_before_a_whole_document_is_salvaged(self):
        text = 'Draft:\n{"findings": [{"id": "x"\n\nFinal:\n{"findings": []}'
        self.assertEqual(textio.extract_json(text), {"findings": []})

    def test_a_cut_off_document_after_a_preamble_fails_its_kit_schema(self):
        # 4.5: such a text can yield an inner object; every kit json schema requires its top-level keys
        schema = "SK:templates/schemas/arch-decisions.schema.json"
        ok, errs, _parsed = validate.check_contract("Here are the decisions:\n" + self.DOC,
                                                    {"type": "json", "schema": schema}, None)
        self.assertFalse(ok)
        self.assertTrue(any("adrs" in e for e in errs), errs)


if __name__ == "__main__":
    unittest.main()
