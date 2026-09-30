"""Phase L (LE-bs): round-5 findings in bs.py's section 13 parser and the tournament cards.

- bs.py assumptions: a bracket an Owner: or Decide by: value opens itself stays in the value ('Owner: Alice (CTO)'),
  '[Owner: ...]' is a field like '(Owner: ...)', and a question or value drops '.', '*' and dashes at its ends, so
  open-questions.md has one row per question (KIT_SPEC 5.7 assumptions)
- bs.py prepare-tournament reads the cards of run.json's finalists, as registry.canonical_cards wrote them at 9.3: a
  curated quick id such as 'Q 01' or 'Q-04b' neither stops 9.3 nor drops out of the tournament (9.3)
"""

import contextlib
import io
import json
import os
import sys
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fixtures", "engine"))
import engine_testlib as tl  # noqa: E402

from ublib.engine import registry  # noqa: E402

sys.path.insert(0, tl.SCRIPTS)
import bs  # noqa: E402

QCRIT = {"Value": 40, "Feasibility": 30, "Distinctiveness": 30}


def quiet(fn, *args, **kw):
    with contextlib.redirect_stdout(io.StringIO()):
        return fn(*args, **kw)


def wfile(run, rel, obj):
    p = os.path.join(run, *rel.split("/"))
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8", newline="\n") as f:
        f.write(obj if isinstance(obj, str) else json.dumps(obj))


def rfile(run, rel):
    with open(os.path.join(run, *rel.split("/")), encoding="utf-8") as f:
        return f.read()


class Section13Tests(tl.EngineTestCase):
    """_q_fields ended a value at its first ')', so 'Owner: Alice (CTO)' became 'Alice (CTO' with the ')' left on the
    question, and the question no longer matched the STATUS trailer's: open-questions.md listed it twice."""

    def test_a_bracket_the_value_opens_stays_in_the_value(self):
        cases = [
            ("- Which cloud? Owner: Alice (CTO); Decide by: M1", ("Which cloud?", "Alice (CTO)", "M1")),
            ("- Which cloud? (Owner: Alice (CTO); Decide by: M1)", ("Which cloud?", "Alice (CTO)", "M1")),
            ("- Which cloud? Owner: Bob (CTO)", ("Which cloud?", "Bob (CTO)", None)),
            ("- Which cloud? (Owner: CTO; Decide by: M1 (before pilot))", ("Which cloud?", "CTO", "M1 (before pilot)")),
            ("- Which cloud? Decide by: M1 (after Q2; tentative)", ("Which cloud?", None, "M1 (after Q2; tentative)")),
            ("- Which cloud? [Owner: CTO; Decide by: M0]", ("Which cloud?", "CTO", "M0")),
            ("- Which cloud? — Owner: CTO — Decide by: M0", ("Which cloud?", "CTO", "M0")),
            ("- Which cloud? *(Owner: CTO)*", ("Which cloud?", "CTO", None)),
            ("- Which cloud? (Owner: CTO).", ("Which cloud?", "CTO", None)),
            # unchanged: a bracket before the field is the question's, a field's own closer is the field's
            ("- Keep option (b)? (Owner: CEO)", ("Keep option (b)?", "CEO", None)),
            ("- Which DB? (see notes, Owner: Bob)", ("Which DB? (see notes)", "Bob", None)),
            ("- Which cloud? (Owner: CTO) (Decide by: M0)", ("Which cloud?", "CTO", "M0")),
        ]
        for line, want in cases:
            self.assertEqual(bs._section13_questions(line), [want], line)

    def test_the_register_keeps_one_row_per_question(self):
        run = os.path.join(self.tmp, "brainstorm", "2026-09-27-l-oq")
        wfile(run, "11_PROPOSAL/sections/13.md", "## 13. Open Questions\n\n"
              "- Which EHR do we integrate first? Owner: CTO; Decide by: M1 (before pilot)\n"
              "- Who signs the data agreement? Owner: Head of Nursing (interim); Decide by: M0\n")
        wfile(run, "11_PROPOSAL/_raw/part.status.json", {"status": "ok", "assumptions": [], "open_questions": [
            "Which EHR do we integrate first?", "Who signs the data agreement?"]})
        quiet(bs.assumptions, run)
        rows = [ln for ln in rfile(run, "11_PROPOSAL/open-questions.md").split("\n") if ln.startswith("| Q-")]
        self.assertEqual(len(rows), 2, rows)
        self.assertNotIn("?)", "".join(rows))

    def test_bracket_floods_cost_linear_time(self):
        n = 40000
        lines = ["- q owner: " + "(" * n + "x", "- q owner: " + "[" * n + ";" * n, "- q owner: " + "()" * n,
                 "- q" + " [" * n + " owner: z" + "]" * n, "- q owner: (" + " owner: (" * (n // 9)]
        start = time.perf_counter()
        for line in lines:
            bs._section13_questions(line)
        self.assertLess(time.perf_counter() - start, 2.0)


CARD_LINES = ["Title: t", "Problem: p", "Mechanism: m", "For whom: w", "First version: v", "Main risk: r",
              "Prior art: NOT CHECKED"]


class QuickIdCardTests(tl.EngineTestCase):
    """bs.py prepare-tournament read the headings of tournament/cards.md without the finalists, so only a leading
    '<letters>-<digits>' token named a card: a quick curator's 'Q 01' stopped 9.3 ('found 0') and 'Q-04b' silently
    left the tournament, though every earlier step accepted these ids."""

    def prepare(self, ids, finalists=True):
        def prep(args, run_dir):
            quiet(bs.prepare_tournament, args[1], "--per-pair" in args)
            return 0, "", ""

        def schemas(args, run_dir):
            quiet(bs.schemas, args[1])
            return 0, "", ""
        ctx = self.make_ctx(mode="quick", families=("claude", "gpt"), run_name="2026-09-27-l-%d" % len(self.seen),
                            deps=tl.FakeDeps(bs=tl.FakeBs({"prepare-tournament": prep, "schemas": schemas})))
        self.seen.append(ctx)
        if finalists:
            ctx.state["finalists"] = list(ids)
        tl.st.save(ctx.run_dir, ctx.state)
        ctx.write_json("criteria.json", QCRIT)
        # the cards as bs.py quick-pick writes them
        ctx.write("tournament/cards.md", "\n".join("\n".join(["## %s" % i] + CARD_LINES) + "\n" for i in ids))
        quiet(registry.SCRIPTS["prepare_tournament"], ctx, {"id": "9.3"})
        d = ctx.path("tournament")
        maps = [tl.read_json(os.path.join(d, n)) for n in os.listdir(d) if n.endswith(".map.json")]
        return sorted(set(x for m in maps for p in m["pairs"].values() for x in (p["first"], p["second"])))

    def setUp(self):
        tl.EngineTestCase.setUp(self)
        self.seen = []

    def test_every_curated_quick_id_reaches_the_tournament(self):
        for ids in (["Q-01", "Q-02", "Q-03"], ["Q 01", "Q 02", "Q 03"], ["Q-01a", "Q-02a", "Q-03a"],
                    ["Q-01", "Q-02", "Q-03", "Q-04b"]):
            self.assertEqual(self.prepare(ids), sorted(ids), ids)

    def test_a_run_without_finalists_reads_each_headings_leading_id(self):
        # a run.json without finalists (bs.py run by hand): the headings' leading ID tokens, as before
        self.assertEqual(self.prepare(["I-001", "I-002", "I-003"], finalists=False), ["I-001", "I-002", "I-003"])

    def test_a_quick_run_with_such_ids_reaches_done_with_every_finalist_ranked(self):
        if not tl.stubs_available():
            self.skipTest("tests/harness/stubs.py not present")
        sys.path.insert(0, tl.HARNESS)
        import stubs
        rename = {"Q-01": "Q 01", "Q-02": "Q-02b", "Q-03": "Q 03", "Q-04": "Q-04b", "Q-05": "Q 05", "Q-06": "Q-06b"}
        curated = stubs._quick_curated

        def renamed(ctx):
            out = curated(ctx)
            for idea in out["ideas"]:
                idea["id"] = rename[idea["id"]]
            return out
        with mock.patch.object(stubs, "_quick_curated", renamed):
            ctx = tl.full_auto_ctx(self, mode="quick", families=("claude", "gpt"))
            card = tl.drive(ctx)
        self.assertEqual(card["type"], "DONE", card.get("say"))
        fin = ctx.state["finalists"]
        self.assertTrue(len(fin) >= 2 and set(fin) <= set(rename.values()), fin)
        ranked = [r["id"] for r in ctx.read_json("tournament/result.json")["raw"]]
        self.assertEqual(sorted(ranked), sorted(fin))


if __name__ == "__main__":
    unittest.main()
