"""Static checks: the user docs agree with the code (KIT_SPEC 11.7, 11.9, 6.9).

- docs/ACCEPTANCE.md has one row per `[U-n]` tag in the code, each with a live check and a filled Result cell
  ("not yet verified live" until someone records a live result) (finding #91).
- The model-call, time and token figures in references/pipeline.md, docs/GUIDE.md, docs/FAMILIES.md and README.md are
  the ones `ub plan` prints for three families (claude, gpt, kimi) and four (plus glm) (finding #92).
"""

import io
import json
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "harness"))
import paths  # noqa: E402
from tmphome import TmpHome  # noqa: E402

ACCEPTANCE = os.path.join(paths.KIT, "docs", "ACCEPTANCE.md")
REF_PIPELINE = os.path.join(paths.SK, "references", "pipeline.md")
GUIDE = os.path.join(paths.KIT, "docs", "GUIDE.md")
FAMILIES_MD = os.path.join(paths.KIT, "docs", "FAMILIES.md")
README = os.path.join(paths.KIT, "README.md")

TAG = re.compile(r"\[U-(\d+)\]")
SKIP_DIRS = {".git", "__pycache__", "node_modules", "dist", ".venv", "venv", "docs"}
# the kit's own dot folders; any other (.build, .claude, editor folders) is local and not the kit, as in validate_kit
KIT_DOT_DIRS = (".github", ".claude-plugin", ".codex-plugin", ".agents", ".kimi-plugin")
MODES = ("quick", "standard", "deep", "proposal")
THREE = "claude,gpt,kimi"
FOUR = "claude,gpt,kimi,glm"


def read(path):
    with io.open(path, encoding="utf-8") as f:
        return f.read()


def code_tags():
    """{n: [files]} for every [U-n] tag outside Markdown files (code, config, workflows, templates, tests)."""
    tags = {}
    for dirpath, dirnames, filenames in os.walk(paths.KIT):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and (not d.startswith(".") or d in KIT_DOT_DIRS)]
        for fn in filenames:
            if fn.endswith((".md", ".pyc")):
                continue
            path = os.path.join(dirpath, fn)
            try:
                with io.open(path, encoding="utf-8", errors="ignore") as f:
                    text = f.read()
            except OSError:
                continue
            for n in TAG.findall(text):
                tags.setdefault(int(n), []).append(os.path.relpath(path, paths.KIT))
    return tags


def acceptance_rows():
    """{n: [cells]} for the `| U-n ...` rows of the Unverified items table."""
    rows = {}
    for ln in read(ACCEPTANCE).split("\n"):
        m = re.match(r"^\| U-(\d+) ", ln)
        if m:
            rows[int(m.group(1))] = [c.strip() for c in ln.strip().strip("|").split("|")]
    return rows


class AcceptanceCoversEveryTag(unittest.TestCase):
    def test_every_code_tag_has_a_row_with_a_live_check(self):
        paths.require(ACCEPTANCE, owner="docs")
        tags, rows = code_tags(), acceptance_rows()
        self.assertTrue(tags, "no [U-n] tag found in the code")
        missing = sorted(set(tags) - set(rows))
        self.assertEqual(missing, [], "docs/ACCEPTANCE.md has no row for: %s" % ", ".join(
            "U-%d (%s)" % (n, tags[n][0]) for n in missing))
        for n, cells in sorted(rows.items()):
            self.assertEqual(len(cells), 6, "U-%d: expected item | where | check | result | host | date" % n)
            item, where, check, result = cells[:4]
            self.assertTrue(where and check, "U-%d: the row names no place or no live check" % n)
            self.assertTrue(result, "U-%d: the Result cell is empty; write 'not yet verified live' or the result" % n)

    def test_procedure_names_ub_live(self):
        text = read(ACCEPTANCE)
        self.assertIn("UB_LIVE=1", text)
        self.assertIn("not yet verified live", text)


def plan(families, mode):
    with TmpHome(tools=()) as th:
        proc = paths.run_py(paths.UB_PY, ["plan", "--mode", mode, "--variant", "general", "--families", families,
                                          "--json"], env=th.env, cwd=th.project, timeout=300)
    if proc.returncode != 0:
        raise AssertionError(paths.describe(proc))
    return json.loads(proc.out)


def span(lo, hi):
    return "%d" % lo if lo == hi else "%d-%d" % (lo, hi)


class DocFiguresComeFromThePlan(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        paths.require(paths.UB_PY, owner="B3")
        cls.p3 = dict((m, plan(THREE, m)) for m in MODES)
        cls.p4 = dict((m, plan(FOUR, m)) for m in MODES)

    def calls(self, mode, four=False):
        c = (self.p4 if four else self.p3)[mode]["calls"]
        return span(c["min"], c["max"])

    def minutes(self, mode):
        m = self.p3[mode]["minutes"]
        return "%d-%d min" % (m[0], m[1])

    def tokens(self, mode, four=False):
        t = (self.p4 if four else self.p3)[mode]["tokens"]
        return "%.2f-%.2fM" % (t[0] / 1e6, t[1] / 1e6)

    def row(self, text, mode, where):
        rows = [ln for ln in text.split("\n") if ln.startswith("| %s | " % mode)]
        self.assertTrue(rows, "%s: no mode row for %s" % (where, mode))
        return rows[0]

    def test_reference_pipeline_mode_table(self):
        text = read(REF_PIPELINE)
        for mode in MODES:
            row = self.row(text, mode, "references/pipeline.md")
            self.assertIn("| %s (%s) |" % (self.calls(mode), self.calls(mode, True)), row, row)
            self.assertIn(self.minutes(mode), row, row)
            self.assertIn(self.tokens(mode)[:-1], text, "references/pipeline.md: %s tokens" % mode)

    def test_guide_mode_table(self):
        text = read(GUIDE)
        for mode in MODES:
            row = self.row(text, mode, "docs/GUIDE.md")
            self.assertIn("| %s (%s) |" % (self.calls(mode), self.calls(mode, True)), row, row)
            self.assertIn(self.minutes(mode), row, row)
            self.assertIn(self.tokens(mode), row, row)

    def test_prose_call_counts(self):
        for path in (FAMILIES_MD, README):
            text = read(path)
            for mode in MODES if path == FAMILIES_MD else ("quick", "standard", "deep"):
                rx = r"%s (model )?calls" % re.escape(self.calls(mode))
                self.assertRegex(text, rx, "%s: %s calls" % (os.path.basename(path), mode))

    def test_budget_caps_match_the_engine(self):
        from ublib.engine import BUDGET_CAPS
        line = "quick %d, standard %d, deep %d, proposal %d" % tuple(BUDGET_CAPS[m] for m in MODES)
        for path in (REF_PIPELINE, FAMILIES_MD):
            self.assertIn(line, read(path).replace("\n", " "), path)


if __name__ == "__main__":
    unittest.main()
