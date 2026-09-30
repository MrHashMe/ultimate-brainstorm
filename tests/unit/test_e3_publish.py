"""Phase E3, publish and render (KIT_SPEC 8.5, 9, 14.2): docs/<run>/ belongs to the run that claimed it (finding 56),
the temp files of an interrupted write are removed whatever the file name's length (review R-publish-installer-0),
a replaced file's backup is written like every other file (finding 4), a run without web access gets an index.html
that loads no script (finding 59), and many identical headings get their anchors in linear time (finding 34)."""

import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

FIXTURES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fixtures", "engine")
sys.path.insert(0, FIXTURES)
import engine_testlib as tl  # noqa: E402

from ublib import textio  # noqa: E402
from ublib.engine import handoff, render  # noqa: E402
from ublib.engine import state as st  # noqa: E402

RUN = "2026-09-26-e3-publish"
ITEMS = ["architecture", "adr", "proposal"]
ADR = "0001-use-postgres-for-storage.md"


class PublishCase(tl.EngineTestCase):
    def run_in(self, root, name=RUN, text="a"):
        """A run folder <project>/<root>/<name> with an architecture, an ADR and a proposal."""
        run_dir = os.path.join(self.project, root, name)
        os.makedirs(run_dir, exist_ok=True)
        st.ensure_run_dirs(run_dir)
        state = st.new_state(run_dir, "t", "claude-code", "claude", runner="python ub.py", project_dir=self.project)
        ctx = st.Ctx(run_dir, state, tl.FakeDeps())
        ctx.write("10_ARCHITECTURE/README.md", "# Architecture %s\n" % text)
        ctx.write("10_ARCHITECTURE/adr/" + ADR, "# ADR 0001 %s\n" % text)
        ctx.write("11_PROPOSAL/PROPOSAL.md", "# Proposal %s\n" % text)
        return ctx

    def docs(self, *parts):
        return os.path.join(self.project, "docs", RUN, *parts)


class ClaimTests(PublishCase):
    def test_a_run_of_the_same_name_in_another_root_never_writes_the_folder(self):
        # finding 56: two runs with one name (same day and slug) in two run roots of one project both wrote
        # docs/<run>/, backing up and replacing each other's files
        a = self.run_in("brainstorm", text="alpha")
        b = self.run_in("elsewhere", text="beta")
        handoff.publish(a, ITEMS)
        before = textio.read_text(self.docs("11_PROPOSAL", "PROPOSAL.md"))
        plan = handoff.plan_target(b, "proposal")
        self.assertIsNone(plan["dst"])
        self.assertEqual(plan["blocker"], "docs/" + RUN)
        self.assertIn("docs/%s belongs to the run at brainstorm/%s" % (RUN, RUN), plan["why"])
        self.assertIn("To publish it, move docs/%s aside and redo step 14.2." % RUN, handoff.card_line(plan))
        res = handoff.publish(b, ITEMS)
        self.assertEqual(res["published"], [])
        self.assertEqual(len(res["not_published"]), 3)
        self.assertEqual(textio.read_text(self.docs("11_PROPOSAL", "PROPOSAL.md")), before)
        self.assertEqual(before, "# Proposal alpha\n")
        self.assertFalse(os.path.exists(b.path("_superseded")))
        # the owner keeps publishing into its folder
        a.write("11_PROPOSAL/PROPOSAL.md", "# Proposal alpha v2\n")
        handoff.publish(a, ITEMS)
        self.assertEqual(textio.read_text(self.docs("11_PROPOSAL", "PROPOSAL.md")), "# Proposal alpha v2\n")

    def test_a_claim_taken_between_plan_and_publish_refuses_the_whole_publish(self):
        a = self.run_in("brainstorm", text="alpha")
        b = self.run_in("elsewhere", text="beta")
        real = handoff._owner
        calls = []

        def late_owner(ctx, base):  # b's plan saw a free folder; a claims it before b's publish writes anything
            calls.append(ctx.run_dir)
            if ctx.run_dir == b.run_dir and len(calls) == 1:
                handoff.publish(a, ITEMS)
                return None
            return real(ctx, base)
        with mock.patch.object(handoff, "_owner", side_effect=late_owner):
            res = handoff.publish(b, ITEMS)
        self.assertEqual(res["published"], [])
        self.assertEqual(textio.read_text(self.docs("10_ARCHITECTURE", "README.md")), "# Architecture alpha\n")

    def test_the_claim_is_ignored_litter_and_holds_no_absolute_path(self):
        a = self.run_in("brainstorm")
        handoff.publish(a, ITEMS)
        claim = textio.read_json(self.docs(handoff.CLAIM))
        self.assertEqual(claim["run_dir"], "brainstorm/" + RUN)
        self.assertNotIn(self.project.replace("\\", "/"), textio.read_text(self.docs(handoff.CLAIM)))
        self.assertTrue(handoff._ignored(handoff.CLAIM))
        self.assertEqual(handoff.plan_target(a, "architecture")["other"], [])

    def test_a_moved_run_keeps_its_folder_by_its_claim_id(self):
        a = self.run_in("brainstorm")
        handoff.publish(a, ITEMS)
        moved = os.path.join(self.project, "runs", RUN)
        os.makedirs(os.path.dirname(moved))
        shutil.move(a.run_dir, moved)
        m = st.Ctx(moved, a.state, tl.FakeDeps())
        self.assertIsNotNone(handoff.plan_target(m, "proposal")["dst"])


class SameNameRaceTests(PublishCase):
    CHILD = "\n".join([
        "import json, os, sys, time",
        "sys.path.insert(0, sys.argv[1])",
        "import engine_testlib as tl",
        "from ublib import textio",
        "from ublib.engine import handoff, state as st",
        "project, root, run, slug, go, ready, out = sys.argv[2:9]",
        "run_dir = os.path.join(project, root, run)",
        "os.makedirs(run_dir, exist_ok=True)",
        "st.ensure_run_dirs(run_dir)",
        "state = st.new_state(run_dir, 't', 'claude-code', 'claude', runner='python ub.py', project_dir=project)",
        "ctx = st.Ctx(run_dir, state, tl.FakeDeps())",
        "for i in range(6):",
        "    ctx.write('10_ARCHITECTURE/adr/%04d-%s-decision.md' % (i + 1, slug), '# ADR %d %s\\n' % (i + 1, slug))",
        "    ctx.write('10_ARCHITECTURE/sections/%02d.md' % i, '# s%d %s\\n' % (i, slug))",
        "ctx.write('10_ARCHITECTURE/README.md', '# %s\\n' % slug)",
        "ctx.write('11_PROPOSAL/PROPOSAL.md', '# Proposal %s\\n' % slug)",
        "open(ready, 'w').close()",
        "while not os.path.exists(go):",
        "    pass",
        "start = float(textio.read_text(go))",
        "while time.time() < start:",
        "    pass",
        "res = handoff.publish(ctx, ['architecture', 'adr', 'proposal'])",
        "with open(out, 'w') as fh:",
        "    json.dump(res, fh)",
    ])

    def test_two_runs_of_one_name_publishing_at_once_never_mix(self):
        # finding 56: the verifier's same-name race mixed the two runs 4 times in 4 and crashed on the other's temp file
        for trial in range(4):
            project = os.path.join(self.tmp, "race-%d" % trial, "project")
            os.makedirs(project)
            sync = os.path.dirname(project)
            procs = []
            for root, slug in (("brainstorm", "alpha"), ("elsewhere", "beta")):
                procs.append(subprocess.Popen(
                    [sys.executable, "-c", self.CHILD, FIXTURES, project, root, RUN, slug, os.path.join(sync, "go"),
                     os.path.join(sync, slug + ".ready"), os.path.join(sync, slug + ".json")],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE))
            deadline = time.time() + 120
            while not all(os.path.exists(os.path.join(sync, s + ".ready")) for s in ("alpha", "beta")):
                self.assertTrue(time.time() < deadline and all(p.poll() is None for p in procs), "a child did not start")
                time.sleep(0.005)
            textio.write_text_atomic(os.path.join(sync, "go"), repr(time.time() + 0.1))
            for p in procs:
                _out, err = p.communicate(timeout=120)
                self.assertEqual(p.returncode, 0, err.decode("utf-8", "replace"))
            results = dict((s, textio.read_json(os.path.join(sync, s + ".json"))) for s in ("alpha", "beta"))
            winners = [s for s, r in results.items() if r["published"]]
            self.assertEqual(len(winners), 1, (trial, results))
            loser = "beta" if winners == ["alpha"] else "alpha"
            self.assertEqual(results[loser]["published"], [], trial)
            published = []
            for dirpath, _dirs, files in os.walk(os.path.join(project, "docs", RUN)):
                published += [textio.read_bytes(os.path.join(dirpath, f)) for f in files if f != handoff.CLAIM]
            self.assertEqual(len(published), 14, trial)  # README, 6 sections, 6 ADRs, PROPOSAL.md: one run's
            self.assertTrue(all(winners[0].encode() in b and loser.encode() not in b for b in published), trial)


class TidyTests(PublishCase):
    def test_a_long_named_files_temp_is_removed(self):
        # R-publish-installer-0: _tidy matched '.' + name[:40] + '.' while textio names temps with the first 16
        # characters, so a killed ADR write left '.0001-use-postgre.<8>.tmp' in docs/<run>/ for good
        a = self.run_in("brainstorm")
        handoff.publish(a, ITEMS)
        folder = self.docs("10_ARCHITECTURE", "adr")
        fd, left = tempfile.mkstemp(prefix=textio.temp_prefix(os.path.join(folder, ADR)), suffix=".tmp", dir=folder)
        os.write(fd, b"partial")
        os.close(fd)
        self.assertTrue(os.path.basename(left).startswith(".0001-use-postgre."))
        a.write("10_ARCHITECTURE/adr/" + ADR, "# ADR 0001 changed\n")
        handoff.publish(a, ITEMS)
        self.assertEqual(os.listdir(folder), [ADR])


class BackupTests(PublishCase):
    def test_a_replaced_file_is_backed_up_through_an_atomic_write(self):
        # finding 4 (c): the backup of a user-edited published file was a shutil.copy2 without fsync
        a = self.run_in("brainstorm")
        handoff.publish(a, ITEMS)
        textio.write_text_atomic(self.docs("10_ARCHITECTURE", "README.md"), "# edited by a user\n")
        a.write("10_ARCHITECTURE/README.md", "# Architecture v2\n")
        writes = []
        real = textio._write_bytes_atomic

        def spy(path, data):
            writes.append(os.path.normcase(os.path.abspath(path)))
            return real(path, data)
        with mock.patch.object(handoff.shutil, "copy2", side_effect=AssertionError("unsynced copy")), \
                mock.patch.object(handoff.textio, "_write_bytes_atomic", side_effect=spy), \
                mock.patch.object(handoff.st, "iso_stamp", return_value="20260926T000000Z"):
            handoff.publish(a, ITEMS)
        backup = a.path("_superseded", "20260926T000000Z", "published", "10_ARCHITECTURE", "README.md")
        self.assertEqual(textio.read_text(backup), "# edited by a user\n")
        self.assertIn(os.path.normcase(os.path.abspath(backup)), writes)


class OfflinePageTests(tl.EngineTestCase):
    def build(self, privacy=None):
        ctx = self.make_ctx(run_name="2026-09-26-e3-page", privacy=privacy)
        ctx.write("11_PROPOSAL/PROPOSAL.md", "# Proposal: x\n\n## 1. Executive Summary\n\n```mermaid\nflowchart LR\n"
                                             "  A --> B\n```\n")
        ctx.write("11_PROPOSAL/ONE-PAGER.md", "# One-pager\n\n## Problem\nx\n")
        return render.build_index_html(ctx)

    def test_a_run_without_web_access_loads_no_script(self):
        # finding 59: a private run's index.html still contacted cdn.jsdelivr.net when opened online
        page = self.build({"web": False})
        self.assertNotIn("jsdelivr", page)
        self.assertNotIn("<script", page.lower())
        self.assertIn("script-src 'none'", page)
        self.assertIn('<pre class="mermaid">flowchart LR', page)  # the diagram source stays readable
        self.assertIn("loads no script", page)

    def test_a_run_with_web_access_keeps_the_pinned_script(self):
        page = self.build()
        self.assertIn('src="%s" integrity="%s"' % (render.MERMAID_CDN, render.MERMAID_SRI), page)
        self.assertNotIn("script-src 'none'", page)


class AnchorTests(unittest.TestCase):
    def test_identical_headings_cost_linear_time(self):
        # finding 34: every duplicate heading probed base-2 .. base-N again (20k identical headings took 57 s)
        md = "## x\n" * 20000
        start = time.perf_counter()
        out = render.md_to_html(md)
        self.assertLess(time.perf_counter() - start, 5.0)
        self.assertIn('<h2 id="x">', out)
        self.assertIn('<h2 id="x-20000">', out)
        used = render.Anchors(["x-3"])
        self.assertEqual([render.anchor("x", used) for _ in range(4)], ["x", "x-2", "x-4", "x-5"])
        plain = set(["x"])  # a plain set still works
        self.assertEqual(render.anchor("x", plain), "x-2")


if __name__ == "__main__":
    unittest.main()
