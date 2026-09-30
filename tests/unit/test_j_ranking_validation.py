"""Phase J (JD-ranking-validation): round-4 findings in ranking, parsing and validation.

- own-origin pairs: two judges whose self-preference was each measured against a third judge are no unattributable
  pair (KIT_SPEC 5.7): the quick screen's third family and a standard screen with a small third vendor no longer print
  "neither score is corrected" next to two corrected judges
- cards: a NORMALIZER heading '## I-001 - Title' is the card of I-001 for every reader (4.5 cards, 9.3)
- red-team files: only redteam/<ID>_<STANCE>_<family>.md files are reviews; a kept <out>.failed.md and a rebuttal
  are no review, no rebuttal job and no G8b verdict line (10.3, 10.3r, 10.5)
- curator contracts: a repeated idea id or key and an empty required value fail the contract, so the repair call runs
  (4.5 json `unique` and `nonempty`)
- A4: a STACK-VERIFY version 'latest (...)' renders as UNVERIFIED (one unpinned-version rule for renderer and lint)
- A2/P2: a lowercase generic type (list<string>, Promise<void>) is no '<...>' placeholder
- bs.py assumptions: section 13 questions and owners keep no ')', '|' or ',' of their fields
- bs.py sources: the adapter's records (*.meta.json, *.failed.md, *.status.json) are no sources
- merge_ground, the seed-leak check and migrate's @seeds proof read sections with textio's fence rule
"""

import contextlib
import io
import json
import os
import sys
import unittest
from unittest import mock

_FIXTURES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fixtures")
sys.path.insert(0, os.path.join(_FIXTURES, "engine"))
sys.path.insert(0, os.path.join(_FIXTURES, "adapter"))
import adapter_testlib as atl  # noqa: E402
import engine_testlib as tl  # noqa: E402

from ublib import adapter, lints, validate  # noqa: E402
from ublib.engine import gates, migrate, privacy, registry, render_arch  # noqa: E402

sys.path.insert(0, tl.SCRIPTS)
import bs  # noqa: E402

CRIT = {"Value": 30, "Feasibility": 25, "Fit": 20, "Distinctiveness": 15, "Evidence": 10}
QCRIT = {"Value": 40, "Feasibility": 30, "Distinctiveness": 30}


def quiet(fn, *args, **kw):
    with contextlib.redirect_stdout(io.StringIO()):
        return fn(*args, **kw)


def rec(i, v, crit=CRIT):
    """A screen record that scores every criterion v (the weighted score is v)."""
    return {"id": i, "g1": True, "g2": True, "g3": True, "c": dict((k, v) for k in crit), "risk": "r"}


def wfile(run, rel, obj):
    p = os.path.join(run, *rel.split("/"))
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8", newline="\n") as f:
        f.write(obj if isinstance(obj, str) else json.dumps(obj))


def rfile(run, rel):
    with open(os.path.join(run, *rel.split("/")), encoding="utf-8") as f:
        text = f.read()
    return json.loads(text) if rel.endswith(".json") else text


class OwnOriginPairTests(tl.EngineTestCase):
    """NEW-I-HC-ranking-seats-2: the pair line and own_origin_pairs warn:true said a self-preference was left
    uncorrected and unattributable while the per-judge lines above it showed both judges measured and lowered."""

    def test_quick_third_judge_measures_both_generators_and_reports_no_pair(self):
        # the quick screen seats [host] + two others (F51); the third family wrote no idea, so each generator's
        # self-preference is measured against it on the other generator's ideas
        run = os.path.join(self.tmp, "brainstorm", "2026-09-27-j-quick")
        ideas, rows = [], {"claude": [], "gpt": [], "kimi": []}
        for n in range(6):
            for fam, prefix in (("claude", "QA"), ("gpt", "QB")):
                iid = "Q-%02d" % (len(ideas) + 1)
                ideas.append({"id": iid, "title": "t", "pitch": "p", "mechanism": "m", "cluster": "c%d%s" % (n, fam),
                              "aliases": ["%s-%02d" % (prefix, n + 1)],
                              "gates": {"g1": True, "g2": True, "g3": True},
                              "scores": [{"criterion": k, "score": 3} for k in QCRIT]})
                q = (4, 3, 2)[n % 3]
                for judge in rows:
                    rows[judge].append(rec(iid, q + (1 if judge == fam else 0), QCRIT))
        wfile(run, "run.json", {"schema": 2, "run": "2026-09-27-j-quick", "mode": "quick",
                                "seats": {"screen_judges": ["claude", "gpt", "kimi"], "tournament_judges": ["gpt"]}})
        wfile(run, "criteria.json", QCRIT)
        wfile(run, "pool/_families.json", {"QA": "claude", "QB": "gpt", "H": "human"})
        wfile(run, "quick/curated.json", {"ideas": ideas})
        for judge, rs in rows.items():
            wfile(run, "screen/%s.out.json" % judge, {"scores": rs})
        quiet(bs.quick_pick, run, "blind")
        fin = rfile(run, "quick/finalists.json")
        self.assertEqual(fin["lowered"], {"claude": 1.0, "gpt": 1.0})
        self.assertEqual(fin["own_origin_pairs"], [])
        self.assertNotIn("together", rfile(run, "quick/screen.md"))

    def test_a_small_third_vendor_is_the_baseline_and_the_g4_card_has_no_pair(self):
        # standard screen: kimi wrote 2 ideas (fewer than 3), so claude and gpt are never compared with each other,
        # but each is measured against kimi on the other's ideas
        ids = ["I-%03d" % n for n in range(1, 15)]
        origins = dict((i, "claude" if n < 6 else "gpt" if n < 12 else "kimi") for n, i in enumerate(ids))
        outs = dict((j, [rec(i, 3 + (1 if origins[i] == j and j != "kimi" else 0)) for i in ids])
                    for j in ("claude", "gpt", "kimi"))
        ctx = self.make_ctx(families=("claude", "gpt", "kimi"), run_name="2026-09-27-j-pair")
        run = ctx.run_dir
        wfile(run, "run.json", {"schema": 2, "run": "2026-09-27-j-pair",
                                "seats": {"screen_judges": ["claude", "gpt", "kimi"]}})
        wfile(run, "criteria.json", CRIT)
        wfile(run, "origins.json", origins)
        wfile(run, "clusters.json", dict((i, "c%d" % (n % 6)) for n, i in enumerate(ids)))
        wfile(run, "screen/ideas.md", "".join("%s | t | p | m\n" % i for i in ids))
        for label, rows in outs.items():
            wfile(run, "screen/%s.out.json" % label, {"scores": rows})
        quiet(bs.screen, run)
        sl = rfile(run, "screen/shortlist.json")
        self.assertEqual(sl["lowered"], {"claude": 1.0, "gpt": 1.0})
        self.assertEqual(sl["own_origin_pairs"], [])
        self.assertNotIn("together", rfile(run, "screen/table.md"))
        summary = gates.gate_values(ctx, "G4")["SUMMARY"]
        self.assertIn("- claude: own-origin gap +1.00", summary)
        self.assertNotIn("together", summary)
        self.assertNotIn("not correctable", summary)


class QuickG11ReferenceTests(unittest.TestCase):
    def test_the_reference_says_a_two_family_quick_run_asks_g11(self):
        # NEW-I-HC-ranking-seats-3: with 2 families the one quick arch judge is of an author family, so the lead is
        # self-judged and hands-on and guided runs are asked (engine: test_h_ranking_arch); references/architecture.md
        # told the agent the leader is taken automatically
        with open(os.path.join(tl.SK, "references", "architecture.md"), encoding="utf-8") as f:
            text = f.read()
        row = next(ln for ln in text.split("\n") if ln.startswith("| 12.9 |"))
        self.assertIn("with 2 families always", row)
        lite = " ".join(text[text.index("Quick mode (lite)"):].split())
        self.assertIn("2 families: self-judged, so G11 asks", lite)


CARD = ("Title: model title {i}\nProblem: p.\nMechanism: m.\nFor whom: nurses\nFirst version: v.\nMain risk: r.\n"
        "Prior art: NOT CHECKED - differentiator: d\n")


class CardHeadingTests(tl.EngineTestCase):
    """'## I-001 - Title' passed the NORMALIZER contract (the validator matches the ID as a prefix), but the readers
    keyed a card by the whole heading: the tournament ranked ids that match no finalist and the debiasing was off."""

    FIN = ["I-001", "I-002", "I-003"]

    def ctx_with_cards(self, cards_text):
        def prep(args, run_dir):
            quiet(bs.prepare_tournament, args[1], "--per-pair" in args)
            return 0, "", ""

        def schemas(args, run_dir):
            quiet(bs.schemas, args[1])
            return 0, "", ""
        ctx = self.make_ctx(families=("claude", "gpt"), run_name="2026-09-27-j-cards",
                            deps=tl.FakeDeps(bs=tl.FakeBs({"prepare-tournament": prep, "schemas": schemas})))
        ctx.state["finalists"] = list(self.FIN)
        tl.st.save(ctx.run_dir, ctx.state)
        ctx.write("screen/ideas.md", "".join("%s | Pool title %s | p | m\n" % (i, i) for i in self.FIN))
        ctx.write_json("criteria.json", CRIT)
        ctx.write_json("origins.json", {"I-001": "claude", "I-002": "gpt", "I-003": "human"})
        ctx.write("tournament/cards.md", cards_text)
        return ctx

    def tally(self, ctx):
        # every judge prefers I-003 > I-002 > I-001 in both orders
        strength = {"I-001": 0, "I-002": 1, "I-003": 2}
        d = ctx.path("tournament")
        for name in sorted(os.listdir(d)):
            if name.endswith(".map.json"):
                meta = rfile(d, name)
                v = [{"pair_id": pid, "winner": "FIRST" if strength.get(p["first"], -1) > strength.get(p["second"], -1)
                      else "SECOND", "reason": "r"} for pid, p in meta["pairs"].items()]
                wfile(d, name.replace(".map.json", ".out.json"), {"verdicts": v})
        quiet(bs.tournament, ctx.run_dir)
        return ctx.read_json("tournament/result.json")

    def test_titled_headings_are_the_finalists_cards(self):
        text = ("# Cards\n\n## I-001: Ward swap\n" + CARD.format(i=1) + "\n## I-002 - Shift ledger\n" + CARD.format(i=2)
                + "\n## I-003\n" + CARD.format(i=3) + "\n## Notes\nThe cards above are neutral.\n")
        ctx = self.ctx_with_cards(text)
        contract = registry.FANOUTS["normalizer"](ctx, {"id": "9.2"})[0]["contract"]
        self.assertEqual(validate.check_contract(text, contract, ctx.run_dir)[:2], (True, []))
        registry.SCRIPTS["prepare_tournament"](ctx, {"id": "9.3"})
        cards = ctx.read("tournament/cards.md")
        self.assertEqual([ln for ln in cards.split("\n") if ln.startswith("#")], ["## I-001", "## I-002", "## I-003"])
        self.assertNotIn("Notes", cards)
        self.assertIn("Title: Pool title I-002", cards)  # the pool title is pinned under a titled heading too
        maps = [rfile(ctx.path("tournament"), n) for n in os.listdir(ctx.path("tournament")) if n.endswith(".map.json")]
        self.assertTrue(maps)
        self.assertEqual(set(x for m in maps for p in m["pairs"].values() for x in (p["first"], p["second"])),
                         set(self.FIN))
        res = self.tally(ctx)
        self.assertEqual(sorted(r["id"] for r in res["debiased"]), self.FIN)
        self.assertTrue(res["audit"])  # claude and gpt judged their own vendor's finalists in mixed pairs
        rk = registry.ranking(ctx)
        self.assertEqual(registry.rank_finalists(ctx, self.FIN, rk), ["I-003", "I-002", "I-001"])
        self.assertEqual(registry.default_top(ctx, self.FIN, rk)[0], "I-003")
        self.assertTrue(registry.card_text(ctx, "I-001").startswith("Title: Pool title I-001"))

    def test_the_card_rule_is_the_contracts(self):
        text = ("## I-001 - A\nTitle: a\n## Notes\nnot a card\n```\n## I-002\n```\n## I-0010\nTitle: x\n"
                "## I-002: B\nTitle: b\n# Appendix\ntail\n## Q1\nTitle: q\n")
        self.assertEqual(registry.parse_cards(text), (["I-001", "I-0010", "I-002", "Q1"], {
            "I-001": ["Title: a"], "I-0010": ["Title: x"], "I-002": ["Title: b"], "Q1": ["Title: q"]}))
        self.assertEqual(registry.parse_cards(text, ["I-001", "I-002"])[0], ["I-001", "I-002"])
        ctx = self.make_ctx(run_name="2026-09-27-j-card-text")
        ctx.write("tournament/cards.md", text)
        self.assertEqual(registry.card_text(ctx, "I-002"), "Title: b")


REVIEW = "## 1\na\n## 2\nb\n## 3\nFails if nurses do not swap.\n## 4\nd\n## 5\ne\nVERDICT: %s\n"


class RedteamFileTests(tl.EngineTestCase):
    """redteam/*_*_*.md with '(.+)\\.md$' took a kept <out>.failed.md and every rebuttal for a review: duplicate
    10.3r job ids with families like 'gpt.md.failed', rebuttal prose and failure records as G8b verdict lines with
    the family unhidden, and failure records fed to SYNTHESIS as reviews."""

    def ctx_with_redteam(self):
        ctx = self.make_ctx(mode="deep", run_name="2026-09-27-j-redteam")
        ctx.state["finalists"] = ["I-001", "I-003"]
        ctx.state["top"] = ["I-001", "I-003"]
        files = {
            "I-001_ADVOCATE_claude.md": REVIEW % "BACK",
            "I-001_CRITIC_gpt.md": REVIEW % "DON'T BACK",  # written by gpt-alt after gpt failed once
            "I-001_CRITIC_gpt.md.failed.md": "FAMILY CALL FAILED: timeout\n- at: 2026-09-27T02:08:41Z\n",
            "I-001_ADVOCATE_claude.rebuttal.md": "Item 1: HOLD - VERDICT: BACK stays\n",
            "I-001_CRITIC_gpt.rebuttal.md.failed.md": "FAMILY CALL FAILED: refused\n",
            "I-003_ADVOCATE_gpt.md": REVIEW % "BACK IF the ward pilots it",
            "I-003_CRITIC_kimi.md.failed.md": "FAMILY CALL FAILED: unavailable\n",  # no fallback answered
        }
        for name, text in files.items():
            ctx.write("redteam/%s" % name, text)
        return ctx

    def test_only_review_files_are_verdicts(self):
        ctx = self.ctx_with_redteam()
        self.assertEqual(registry.review_verdicts(ctx), {
            "I-001": ["I-001 ADVOCATE (claude): VERDICT: BACK", "I-001 CRITIC (gpt): VERDICT: DON'T BACK"],
            "I-003": ["I-003 ADVOCATE (gpt): VERDICT: BACK IF the ward pilots it"]})
        lines = gates.gate_values(ctx, "G8b")["VERDICT_LINES"]
        for bad in ("(", "rebuttal", "FAMILY CALL FAILED", ".md"):
            self.assertNotIn(bad, lines)

    def test_the_rebuttal_fanout_pairs_the_two_reviews_only(self):
        ctx = self.ctx_with_redteam()
        orig = registry.textio.glob_in
        for order in (lambda xs: xs, lambda xs: list(reversed(xs))):  # never depends on the directory order
            with tl.mock.patch.object(registry.textio, "glob_in", lambda *a, **k: order(orig(*a, **k))):
                items = registry.FANOUTS["rebuttals"](ctx, {"id": "10.3r"})
            self.assertEqual(sorted((i["id"], i["family"], i["out"]) for i in items), [
                ("I-001_ADVOCATE", "claude", "redteam/I-001_ADVOCATE_claude.rebuttal.md"),
                ("I-001_CRITIC", "gpt", "redteam/I-001_CRITIC_gpt.rebuttal.md")])
            other = dict((i["id"], i["vars"]["OTHER_REVIEW"]) for i in items)
            self.assertIn("Fails if nurses do not swap.", other["I-001_ADVOCATE"])
            self.assertNotIn("FAMILY CALL FAILED", " ".join(other.values()))

    def test_synthesis_reads_reviews_and_rebuttals_not_failure_records(self):
        ctx = self.ctx_with_redteam()
        text = registry.PLACEHOLDERS["REVIEWS"](ctx, {})
        self.assertEqual([ln for ln in text.split("\n") if ln.startswith("--- REVIEW")], [
            "--- REVIEW I-001 ADVOCATE ---", "--- REVIEW I-001 ADVOCATE REBUTTAL ---", "--- REVIEW I-001 CRITIC ---",
            "--- REVIEW I-003 ADVOCATE ---"])
        self.assertNotIn("FAMILY CALL FAILED", text)


def merges_idea(key, aliases):
    return {"key": key, "title": "t", "pitch": "p", "mechanism": "m", "aliases": aliases, "cluster": "c",
            "cell": [], "siblings": [], "baseline": False, "primary": False}


def merges(ideas):
    return json.dumps({"axes": [], "ideas": ideas, "notes": {"rerun": [], "leak_check": [], "merge_log": []}})


def quick_idea(qid):
    return {"id": qid, "title": "t", "pitch": "p", "mechanism": "m", "cluster": "c", "aliases": ["QA-01"],
            "gates": {"g1": True, "g2": True, "g3": True}, "scores": [], "fails_if": "f", "problem": "p",
            "for_whom": "w", "first_version": "v"}


class CuratorContractTests(tl.EngineTestCase):
    """Curator outputs with a repeated idea key or id, or an empty aliases list, passed their contracts; bs.py map,
    quick-pick and Q.3p then refused them and the run blocked with no repair call."""

    def contracts(self):
        ctx = self.make_ctx(mode="quick", run_name="2026-09-27-j-curator")
        curator = registry.FANOUTS["curator"](ctx, {"id": "5.1"})[0]["contract"]
        quick = registry.FANOUTS["quick_curate"](ctx, {"id": "Q.3"})[0]["contract"]
        return ctx, curator, quick

    def test_the_curator_contract_refuses_what_bs_map_refuses(self):
        ctx, curator, _quick = self.contracts()
        good = [merges_idea("k-1", ["S1-01"]), merges_idea("k-2", ["S1-02"])]
        self.assertEqual(validate.check_contract(merges(good), curator, ctx.run_dir)[:2], (True, []))
        ok, errors, _p = validate.check_contract(merges(good + [merges_idea(" k-1", ["S1-03"])]), curator,
                                                 ctx.run_dir)
        self.assertFalse(ok)
        self.assertIn("unique: ideas lists key 'k-1' more than once", errors)
        for field, empty in (("aliases", []), ("title", "  "), ("key", ""), ("cluster", "")):
            bad = merges_idea("k-3", ["S1-03"])
            bad[field] = empty
            ok, errors, _p = validate.check_contract(merges(good + [bad]), curator, ctx.run_dir)
            self.assertFalse(ok, field)
            self.assertIn("nonempty: ideas[2].%s is empty" % field, errors)

    def test_the_quick_curate_contract_refuses_a_repeated_or_empty_id(self):
        ctx, _curator, quick = self.contracts()
        ok, errors, _p = validate.check_contract(json.dumps({"ideas": [quick_idea("Q-01"), quick_idea("Q-02")]}),
                                                 quick, ctx.run_dir)
        self.assertEqual((ok, errors), (True, []))
        ok, errors, _p = validate.check_contract(json.dumps({"ideas": [quick_idea("Q-01"), quick_idea("Q-01 ")]}),
                                                 quick, ctx.run_dir)
        self.assertIn("unique: ideas lists id 'Q-01' more than once", errors)
        ok, errors, _p = validate.check_contract(json.dumps({"ideas": [quick_idea("Q-01"), quick_idea(" ")]}),
                                                 quick, ctx.run_dir)
        self.assertIn("nonempty: ideas[1].id is empty", errors)


class CuratorRepairTests(atl.AdapterTestCase):
    def test_a_repeated_key_earns_the_repair_call(self):
        # the real adapter with the engine's CURATOR contract: the first answer lists one idea twice, the repair call
        # (4.5) answers well, and the job ends ok with repaired=true instead of blocking bs.py map at 5.2
        good = [merges_idea("k-1", ["S1-01"]), merges_idea("k-2", ["S1-02"])]

        def answer(text):
            return json.dumps({"type": "result", "subtype": "success", "is_error": False, "result": text,
                               "session_id": "fixture", "usage": {"input_tokens": 1, "output_tokens": 1}}).encode()
        job = self.make_job(job_id="5.1", family="claude", kind="curator", out="merges.raw.5.1.json",
                            contract=registry.tcontract("CURATOR"))
        fake = atl.FakeRun([atl.PR(0, answer(merges(good + [merges_idea("k-1", ["S1-03"])]))),
                            atl.PR(0, answer(merges(good)))])
        with mock.patch("ublib.proc.run", side_effect=fake), \
                mock.patch("ublib.proc.resolve_exe", side_effect=atl.fake_resolve()):
            meta = adapter.execute_job(job, detect_result=atl.chain_detect({"claude": ["claude-cli"]}, "claude"))
        self.assertEqual((meta["status"], meta["repaired"]), ("ok", True))
        with open(self.out_path(job), encoding="utf-8") as f:
            self.assertEqual([i["key"] for i in json.load(f)["ideas"]], ["k-1", "k-2"])


class StackVersionTests(unittest.TestCase):
    """A STACK-VERIFY version 'latest (managed service)' was rendered as-is into chosen/stack.md, which lint A4 fails
    (it starts with 'latest'); no fixer may write stack.json, so the FAIL survived every ARCH-FIX pass."""

    def test_an_unpinned_version_renders_as_unverified_and_passes_a4(self):
        for version in ("latest (managed service)", "Latest stable", "latest", "", "n/a", "none", "?", "-"):
            stack = render_arch.render_stack([{"layer": "runtime", "component": "Web app", "choice": "TypeScript SPA",
                                               "version": version, "status": "VERIFIED"}])
            self.assertIn("| UNVERIFIED |", stack, version)
            items = lints._check_stack(stack, "chosen/stack.md")
            self.assertEqual([i["severity"] for i in items], ["warn"], (version, items))
        stack = render_arch.render_stack([{"layer": "db", "component": "store", "choice": "PostgreSQL",
                                           "version": "16.4", "status": "VERIFIED"}])
        self.assertIn("| 16.4 |", stack)
        self.assertEqual(lints._check_stack(stack, "chosen/stack.md"), [])

    def test_the_lint_fails_every_unpinned_version_it_is_shown(self):
        table = "| layer | component | choice | version | status |\n|---|---|---|---|---|\n"
        for version in ("latest (managed service)", "none", "?", "N/A", ""):
            items = lints._check_stack(table + "| a | b | c | %s | VERIFIED |\n" % version, "chosen/stack.md")
            self.assertEqual([i["severity"] for i in items], ["fail"], version)


class GenericTypeTests(tl.EngineTestCase):
    """Lint A2/P2's '<...>' pattern took lowercase generic type arguments (list<string>, Promise<void>) for
    placeholders: a false FAIL, an ARCH-FIX prompt asked to fix it and an 'unresolved' line at G13."""

    def test_type_arguments_are_no_placeholders(self):
        for text in ("| SWAP | id: uuid, tags: list<string>, audit: Vec<u8> |", "wraps every call in Promise<void>",
                     "a std::vector<int> and Option<u64> and set<text>", "tags: Array<shift>", "`<owner name>`",
                     "line<br>break"):
            self.assertEqual(lints.placeholder_hits(text), [], text)
        for text in ("| SWAP | <owner name>, id |", "Owner: <team>", "(<value>)", "list <string>"):
            self.assertEqual([h[1] for h in lints.placeholder_hits(text)], ["<...>"], text)

    def test_approach_checks_placeholders_like_lint_a2(self):
        # approach_after had its own copy of the A2 patterns: a type argument, inline code and the HTML allow-list
        # were placeholders there
        ctx = self.make_ctx(variant="research", run_name="2026-09-27-j-approach")
        ctx.write("10_ARCHITECTURE/approach.md", "# Approach\n\nScores are a list<float>, read as `list<float>`.<br>\n"
                  "Quoted: neque porro quisquam est qui dolorem ipsum.\n")
        render_arch.approach_after(ctx, {"id": "12.a"})
        self.assertEqual(ctx.read_json("10_ARCHITECTURE/lint.json"), {"status": "pass", "items": []})
        self.assertEqual(ctx.state["unresolved"], [])
        ctx.write("10_ARCHITECTURE/approach.md", "# Approach\n\nOwner: <team lead>\n\nBudget: TODO\n")
        render_arch.approach_after(ctx, {"id": "12.a"})
        lint = ctx.read_json("10_ARCHITECTURE/lint.json")
        self.assertEqual((lint["status"], [i["message"] for i in lint["items"]]),
                         ("fail", ["placeholder <team lead> (line 3)", "placeholder TODO (line 5)"]))
        self.assertEqual(ctx.state["unresolved"], ["approach.md placeholder <team lead> (line 3)",
                                                   "approach.md placeholder TODO (line 5)"])


class Section13Tests(tl.EngineTestCase):
    """_q_fields removed the '(' before 'Owner:' but left the matching ')' and the '|' separators in the question, and
    owners kept a trailing ',': 'Which database do we pick?)', 'Is HIPAA in scope? ||', 'CFO,' in open-questions.md,
    and the stray characters also broke the dedup against the STATUS trailers' questions."""

    def test_fields_take_their_own_separators(self):
        cases = [
            ("- Which database do we pick? (Owner: Bob; Decide by: Milestone 1)",
             ("Which database do we pick?", "Bob", "Milestone 1")),
            ("- Pricing tier? (Owner: CFO, Decide by: 2026-11-01)", ("Pricing tier?", "CFO", "2026-11-01")),
            ("1. Is HIPAA in scope? | Owner: Legal | Decide by: before M1",
             ("Is HIPAA in scope?", "Legal", "before M1")),
            ("- Which cloud? (Owner: CTO) (Decide by: M0)", ("Which cloud?", "CTO", "M0")),
            ("- Which cloud? Owner: CTO, Decide by: M0", ("Which cloud?", "CTO", "M0")),
            ("- Which cloud? - Owner: CTO - Decide by: M0", ("Which cloud?", "CTO", "M0")),
            ("- Keep option (b)? Owner: CEO", ("Keep option (b)?", "CEO", None)),
            ("- Which DB? (see notes, Owner: Bob)", ("Which DB? (see notes)", "Bob", None)),
            ("- Keep the free plan? | Owner: CEO |", ("Keep the free plan?", "CEO", None)),
        ]
        for line, want in cases:
            self.assertEqual(bs._section13_questions(line), [want], line)

    def test_the_register_dedups_section_13_against_the_status_trailer(self):
        run = os.path.join(self.tmp, "brainstorm", "2026-09-27-j-oq")
        wfile(run, "11_PROPOSAL/sections/13.md", "## 13. Open Questions\n\n"
              "- Which database do we pick? (Owner: Bob; Decide by: Milestone 1)\n"
              "- Pricing tier? (Owner: CFO, Decide by: 2026-11-01)\n"
              "1. Is HIPAA in scope? | Owner: Legal | Decide by: before M1\n")
        wfile(run, "11_PROPOSAL/_raw/part.status.json", {"status": "ok", "assumptions": [], "open_questions": [
            "Which database do we pick?", "Pricing tier?", "Is HIPAA in scope?"]})
        quiet(bs.assumptions, run)
        rows = [ln for ln in rfile(run, "11_PROPOSAL/open-questions.md").split("\n") if ln.startswith("| Q-")]
        self.assertEqual(len(rows), 3, rows)
        self.assertNotIn(")", "".join(rows))
        self.assertNotIn("//", "".join(rows))


class SourcesTests(tl.EngineTestCase):
    """bs.py sources scanned the adapter's own records next to the outputs: an HTTP backend's endpoint from
    <out>.meta.json ('cmd': 'POST <url>') and the failure reason or invalid last output of a kept <out>.failed.md
    became cited sources, in the proposal and in other vendors' prompts."""

    def run_dir(self):
        run = os.path.join(self.tmp, "brainstorm", "2026-09-27-j-sources")
        wfile(run, "checks/I-001.md", "## 1. Prior art\n- Ward app https://example.org/ward-app 2026-09-01\n")
        wfile(run, "checks/I-001.md.failed.md", "FAMILY CALL FAILED: HTTP 401: see "
              "https://platform.openai.com/account/api-keys\n")
        wfile(run, "10_ARCHITECTURE/review/L2_kimi.json", {"findings": [
            {"issue": "Postgres docs", "evidence": "https://www.postgresql.org/docs/16/"}]})
        wfile(run, "10_ARCHITECTURE/review/L2_kimi.json.meta.json", {
            "status": "ok", "cmd": "POST https://llm-gateway.corp.internal/moonshot/v1/chat/completions"})
        wfile(run, "10_ARCHITECTURE/review/L2_kimi.status.json", {"status": "ok", "note": "https://status.example/x"})
        wfile(run, "redteam/I-001_CRITIC_kimi.md.failed.md", "FAMILY CALL FAILED: invalid\nlast output: "
              "https://unverified.example.net/made-up-claim\n")
        return run

    def test_only_model_outputs_are_scanned(self):
        run = self.run_dir()
        quiet(bs.sources, run)
        src = rfile(run, "sources.json")
        self.assertEqual(sorted(e["url"] for e in src.values()),
                         ["https://example.org/ward-app", "https://www.postgresql.org/docs/16/"])
        self.assertNotIn("corp.internal", rfile(run, "sources.md"))

    def test_an_old_entry_cited_only_by_a_record_is_dropped_and_its_id_not_reused(self):
        run = self.run_dir()
        wfile(run, "sources.json", {
            "S-001": {"url": "https://llm-gateway.corp.internal/moonshot/v1/chat/completions", "title": "POST",
                      "accessed": "2026-09-20", "used_in": ["10_ARCHITECTURE/review/L2_kimi.json.meta.json"]},
            "S-002": {"url": "https://example.org/ward-app", "title": "Ward app", "accessed": "2026-09-01",
                      "used_in": ["checks/I-001.md", "checks/I-001.md.failed.md"]},
            "S-003": {"url": "https://example.org/kept-by-hand", "title": "kept", "accessed": "2026-09-01",
                      "used_in": []}})
        quiet(bs.sources, run)
        src = rfile(run, "sources.json")
        self.assertEqual(sorted(src), ["S-002", "S-003", "S-004"])
        self.assertEqual(src["S-002"]["used_in"], ["checks/I-001.md"])
        self.assertEqual(src["S-004"]["url"], "https://www.postgresql.org/docs/16/")


F = "```"


class SharedSectionReaderTests(tl.EngineTestCase):
    """NEW-I-HF-parsers-2: merge_ground, the seed-leak check and migrate's @seeds proof read '## ' sections with their
    own regexes, so a '## ' line inside a fence cut a section short or started one early (and merge_ground left an
    unclosed fence in 02_CONTEXT.md); they now use the contract's rule (textio's headings and fences)."""

    def test_merge_ground_takes_the_whole_landscape(self):
        ctx = self.make_ctx(run_name="2026-09-27-j-ground")
        ctx.write("02_CONTEXT.md", "## A. FACTS\n- f\n## B. LANDSCAPE\n- first family\n## C. SEARCH BOUNDARY\n- q\n")
        ctx.write("ground/02_CONTEXT.second.md", "## A. FACTS\n- a fact, with an example:\n" + F + "md\n"
                  "## B. an example heading\n" + F + "\n## B. LANDSCAPE\n- tool X\n" + F + "bash\n"
                  "## C. comment in a script\n" + F + "\n- tool Y\n## C. SEARCH BOUNDARY\n- q2\n")
        registry.SCRIPTS["merge_ground"](ctx, {"id": "3.2"})
        merged = ctx.read("02_CONTEXT.md")
        second = merged[merged.index("## B (second family)\n"):]
        self.assertEqual(second, "## B (second family)\n- tool X\n" + F + "bash\n## C. comment in a script\n" + F +
                         "\n- tool Y\n")
        self.assertNotIn("an example heading", second)

    def test_the_seed_leak_check_reads_the_seed_sections_as_the_engine_does(self):
        ctx = self.make_ctx(run_name="2026-09-27-j-seedleak")
        ctx.write("00_HUMAN_SEEDS.md", "# Seeds\n\n## Problem\nLike this:\n" + F + "md\n## Ideas\n"
                  "- an example line inside a fence, never a seed\n" + F + "\n## Ideas\n"
                  "- a nurse-led swap board for night shifts\n" + F + "\n## Obvious\n" + F + "\n"
                  "- a paging bot that texts the charge nurse\n## Obvious\n- a spreadsheet everyone edits\n")
        lines = privacy.seed_lines(ctx.run_dir)
        self.assertIn("a paging bot that texts the charge nurse", lines)
        self.assertIn("a spreadsheet everyone edits", lines)
        self.assertNotIn("an example line inside a fence, never a seed", lines)

    def test_migrate_proves_the_seeds_step_as_the_engine_reads_it(self):
        ctx = self.make_ctx(run_name="2026-09-27-j-migrate")
        fenced = "# Seeds\n" + F + "\n## Ideas\n- an example in a fence\n" + F + "\n## Ideas\n\n## Obvious\n- x\n"
        cases = {fenced: False,
                 "# Seeds\n\n## Ideas\n\n## Obvious\n- x\n": False,
                 "# Seeds\n\n## Primary idea\n- a swap board\n": True,
                 "SKIPPED: full-auto\n": True}
        for text, proved in cases.items():
            ctx.write("00_HUMAN_SEEDS.md", text)
            self.assertEqual(migrate._proved(ctx.run_dir, ["@seeds"]), proved, text)
            self.assertEqual(registry.eval_when(ctx, ["no_seeds"]), not proved, text)
        # a round-2 seeds file without a final newline no longer glues the next file's heading to its last line
        ctx.write("00_HUMAN_SEEDS.md", "# Seeds\n\n## Ideas\n")
        ctx.write("00_HUMAN_SEEDS_2.md", "notes without a newline")
        ctx.write("00_HUMAN_SEEDS_3.md", "## Ideas\n- a second-round idea\n")
        self.assertTrue(migrate._proved(ctx.run_dir, ["@seeds"]))


if __name__ == "__main__":
    unittest.main()
