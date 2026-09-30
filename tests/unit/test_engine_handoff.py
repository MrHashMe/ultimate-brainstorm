"""B3 engine: Stage 14 publish (KIT_SPEC 9, 14.2). Every run publishes into its own docs/<run>/, keeping the run's
layout (docs/<run>/10_ARCHITECTURE/ with its adr/, docs/<run>/11_PROPOSAL/), so no file is rewritten and every link
resolves; two runs never mix, also when they publish at the same moment; a republish is idempotent, backs up what it
replaces and moves what the run no longer has; an interrupted publish runs again to the same result; links are never
written through; published files get the umask mode; the kit 2.0.x folders are left alone and named on the card."""

import os
import re
import shutil
import stat
import subprocess
import sys
import time
import unittest
from unittest import mock

FIXTURES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fixtures", "engine")
sys.path.insert(0, FIXTURES)
import engine_testlib as tl  # noqa: E402

from ublib import textio  # noqa: E402
from ublib.engine import EngineError, gates, handoff, registry  # noqa: E402

RUN_A = "2026-09-24-act-principal-ai-research-scientist"
RUN_B = "2026-09-24-need-create-best-every-binary"
ITEMS = ["architecture", "adr", "proposal"]
STAMP = "20260925T000000Z"
LINK_RE = re.compile(r'\]\(([^)\s]+)\)|href="([^"]+)"')


def make_dir_link(link, target):
    """A directory symlink, or a junction on Windows without the symlink privilege; False when neither works."""
    try:
        os.symlink(target, link, target_is_directory=True)
        return True
    except (OSError, NotImplementedError, AttributeError):
        pass
    try:
        import _winapi
        _winapi.CreateJunction(target, link)
        return True
    except (ImportError, OSError, AttributeError):
        return False


def snapshot(root):
    """{path: bytes} under root; the run's claim on its docs folder (handoff.CLAIM) is not part of a copy."""
    out = {}
    for dirpath, _dirs, files in os.walk(root):
        for f in files:
            if f == handoff.CLAIM:
                continue
            full = os.path.join(dirpath, f)
            with open(full, "rb") as fh:
                out[os.path.relpath(full, root).replace("\\", "/")] = fh.read()
    return out


class PublishCase(tl.EngineTestCase):
    def run_ctx(self, name, adr_slug="x", readme="# Architecture\n", adrs=True):
        ctx = self.make_ctx(run_name=name)
        ctx.write("10_ARCHITECTURE/README.md", readme)
        if adrs:
            ctx.write("10_ARCHITECTURE/adr/0001-%s.md" % adr_slug, "# ADR 0001 %s\n" % adr_slug)
        ctx.write("11_PROPOSAL/PROPOSAL.md", "# Proposal %s\n" % name)
        return ctx

    def linked_run(self, name, adrs=("0001-a", "0002-b")):
        """A run whose README, chosen/, proposal, sections and index.html link to its ADRs the way the kit writes
        them (adr/..., ../adr/..., ../10_ARCHITECTURE/adr/..., ../../10_ARCHITECTURE/adr/...)."""
        ctx = self.make_ctx(run_name=name)
        rows = "\n".join("| [ADR-%s](adr/%s.md) | %s | accepted |" % (a[:4], a, a) for a in adrs)
        ctx.write("10_ARCHITECTURE/README.md", "# Architecture\n\n## Decision index\n| ADR | title | status |\n"
                  "|---|---|---|\n%s\n\nSee [the containers](chosen/containers.md) and "
                  "[MADR](https://adr.github.io/madr/adr/).\n" % rows)
        ctx.write("10_ARCHITECTURE/chosen/containers.md", "# Containers\nDecided in [ADR-%s](../adr/%s.md).\n"
                  % (adrs[-1][:4], adrs[-1]))
        for a in adrs:
            ctx.write("10_ARCHITECTURE/adr/%s.md" % a, "---\nstatus: accepted\n---\n# ADR-%s: %s\n" % (a[:4], a))
        rows = "\n".join("| [ADR-%s](../10_ARCHITECTURE/adr/%s.md) | %s | accepted |" % (a[:4], a, a) for a in adrs)
        ctx.write("11_PROPOSAL/PROPOSAL.md", "# Proposal\n\n## Appendix A. ADR Index\n%s\n" % rows)
        ctx.write("11_PROPOSAL/sections/03.md", "## 3. Solution\nSee [ADR-%s](../../10_ARCHITECTURE/adr/%s.md).\n"
                  % (adrs[0][:4], adrs[0]))
        ctx.write("11_PROPOSAL/index.html", "<html><body>%s</body></html>\n" % "".join(
            '<a href="../10_ARCHITECTURE/adr/%s.md">ADR-%s</a>' % (a, a[:4]) for a in adrs))
        return ctx

    def switch(self, ctx, adrs):
        """`ub switch --arch` / a redo: the run's ADR set, README index and proposal appendix change."""
        shutil.rmtree(ctx.path("10_ARCHITECTURE"))
        shutil.rmtree(ctx.path("11_PROPOSAL"))
        return self.linked_run(os.path.basename(ctx.run_dir), adrs=adrs)

    def docs(self, *parts):
        return os.path.join(self.project, "docs", *parts)

    def read(self, *parts):
        return textio.read_text(self.docs(*parts))

    def record(self, ctx):
        return ctx.read_json(handoff.PUBLISH_RECORD)

    def broken_links(self):
        """Every relative link in the published Markdown and HTML that does not resolve to a file."""
        out = []
        for dirpath, _dirs, files in os.walk(self.docs()):
            for f in files:
                if not f.endswith((".md", ".html")):
                    continue
                for m in LINK_RE.finditer(textio.read_text(os.path.join(dirpath, f))):
                    link = (m.group(1) or m.group(2)).split("#")[0]
                    if link and not re.match(r"^[a-z]+:", link) and not os.path.isfile(os.path.join(dirpath, link)):
                        out.append("%s -> %s" % (os.path.relpath(os.path.join(dirpath, f), self.docs()), link))
        return out


class LayoutTests(PublishCase):
    def test_publish_mirrors_the_run_under_its_own_docs_folder(self):
        a = self.linked_run(RUN_A)
        res = handoff.publish(a, ITEMS)
        self.assertEqual(res, {"published": [
            "10_ARCHITECTURE -> docs/%s/10_ARCHITECTURE" % RUN_A,
            "10_ARCHITECTURE/adr -> docs/%s/10_ARCHITECTURE/adr (in the architecture copy)" % RUN_A,
            "11_PROPOSAL -> docs/%s/11_PROPOSAL" % RUN_A], "not_published": []})
        self.assertEqual(os.listdir(self.docs()), [RUN_A])
        published = snapshot(self.docs(RUN_A))
        expected = dict(("10_ARCHITECTURE/" + k, v) for k, v in snapshot(a.path("10_ARCHITECTURE")).items())
        expected.update(("11_PROPOSAL/" + k, v) for k, v in snapshot(a.path("11_PROPOSAL")).items())
        self.assertEqual(published, expected)  # byte for byte: nothing is rewritten
        self.assertEqual(self.broken_links(), [])
        record = self.record(a)
        self.assertEqual(record, {"schema": 1, "docs": "docs/" + RUN_A, "files": sorted(expected),
                                  "claim": record["claim"]})
        claim = textio.read_json(self.docs(RUN_A, handoff.CLAIM))
        self.assertEqual(claim, {"schema": 1, "run": RUN_A, "id": record["claim"], "run_dir": "brainstorm/" + RUN_A})
        self.assertRegex(record["claim"], "^[0-9a-f]{32}$")

    def test_no_published_file_is_rewritten_not_even_inside_code(self):
        a = self.linked_run(RUN_A)
        raw = ("\ufeff# Architecture\r\n| [ADR-0001](adr/0001-a.md) |\r\n```md\r\n[x](adr/0001-a.md)\r\n```\r\n"
               "Inline `[y](adr/0002-b.md)` and <a href='adr/0002-b.md'>b</a>\r\n\r\n    [z](adr/0001-a.md)\r\n"
               "Caf\u00e9\r\n").encode("utf-8")
        with open(a.path("10_ARCHITECTURE", "README.md"), "wb") as fh:
            fh.write(raw)
        handoff.publish(a, ITEMS)
        with open(self.docs(RUN_A, "10_ARCHITECTURE", "README.md"), "rb") as fh:
            self.assertEqual(fh.read(), raw)
        self.assertEqual(self.broken_links(), [])

    def test_the_proposal_brings_the_adrs_it_links_to(self):
        a = self.linked_run(RUN_A)
        self.assertEqual(handoff.publish(a, ["proposal"])["published"], [
            "10_ARCHITECTURE/adr -> docs/%s/10_ARCHITECTURE/adr (published with the proposal, which links to it)"
            % RUN_A, "11_PROPOSAL -> docs/%s/11_PROPOSAL" % RUN_A])
        self.assertEqual(os.listdir(self.docs(RUN_A, "10_ARCHITECTURE")), ["adr"])
        self.assertEqual(self.broken_links(), [])

    def test_adr_alone_publishes_only_the_adrs(self):
        a = self.linked_run(RUN_A)
        self.assertEqual(handoff.publish(a, ["adr"])["published"],
                         ["10_ARCHITECTURE/adr -> docs/%s/10_ARCHITECTURE/adr" % RUN_A])
        self.assertEqual(sorted(os.listdir(self.docs(RUN_A, "10_ARCHITECTURE", "adr"))), ["0001-a.md", "0002-b.md"])
        self.assertEqual(sorted(os.listdir(self.docs(RUN_A))), [handoff.CLAIM, "10_ARCHITECTURE"])

    def test_zero_adrs_means_nothing_to_publish(self):
        b = self.run_ctx(RUN_B, adrs=False)
        self.assertIn("- adr: nothing to publish (10_ARCHITECTURE/adr has no files)\n", gates.display(b, "G14"))
        self.assertEqual(handoff.publish(b, ["adr"]), {"published": [],
                                                       "not_published": ["10_ARCHITECTURE/adr (no files)"]})
        self.assertFalse(os.path.exists(self.docs()))
        self.assertEqual(handoff.publish(b, ["proposal"])["published"], ["11_PROPOSAL -> docs/%s/11_PROPOSAL" % RUN_B])

    def test_litter_in_the_package_is_never_published(self):
        a = self.run_ctx(RUN_A, "a", adrs=False)
        a.write("10_ARCHITECTURE/adr/.DS_Store", "x\n")
        a.write("10_ARCHITECTURE/desktop.ini", "[.ShellClassInfo]\n")
        a.write("11_PROPOSAL/.PROPOSAL.md.swp", "x\n")
        a.write("11_PROPOSAL/.PROPOSAL.md.k2j4x9ab.tmp", "partial\n")
        self.assertEqual(handoff.plan_target(a, "adr")["state"], "empty")
        self.assertEqual(handoff.publish(a, ITEMS)["not_published"], ["10_ARCHITECTURE/adr (no files)"])
        self.assertEqual(sorted(snapshot(self.docs(RUN_A))),
                         ["10_ARCHITECTURE/README.md", "11_PROPOSAL/PROPOSAL.md"])


class CardTests(PublishCase):
    def test_card_on_a_fresh_project_names_the_runs_own_folder(self):
        text = gates.display(self.run_ctx(RUN_A), "G14")
        self.assertIn("- architecture: 10_ARCHITECTURE -> docs/%s/10_ARCHITECTURE\n" % RUN_A, text)
        self.assertIn("- adr: 10_ARCHITECTURE/adr -> docs/%s/10_ARCHITECTURE/adr\n" % RUN_A, text)
        self.assertIn("- proposal: 11_PROPOSAL -> docs/%s/11_PROPOSAL\n" % RUN_A, text)
        self.assertIn("Each copy goes to docs/%s/, a folder no other run writes, and keeps the run's layout, so its "
                      "links resolve unchanged: `architecture` holds the ADRs and `proposal` brings them along."
                      % RUN_A, text)
        self.assertNotIn("Kit 2.0.x", text)

    def test_card_after_a_change_says_what_is_backed_up_and_what_moves(self):
        a = self.linked_run(RUN_A)
        handoff.publish(a, ITEMS)
        a = self.switch(a, ("0001-a", "0003-c"))
        text = gates.display(a, "G14")
        self.assertIn("- architecture: 10_ARCHITECTURE -> docs/%s/10_ARCHITECTURE (this run published it before; 2 "
                      "files it replaces are backed up to _superseded/ first; 1 file this run no longer has moves to "
                      "_superseded/)\n" % RUN_A, text)
        self.assertIn("- proposal: 11_PROPOSAL -> docs/%s/11_PROPOSAL (this run published it before; 2 files it "
                      "replaces are backed up to _superseded/ first)\n" % RUN_A, text)
        self.assertIn("Files this run no longer has leave only when every copy it published is published again", text)

    def test_the_2_0_x_copies_are_named_and_left_untouched(self):
        for rel, run in (("adr", RUN_A), ("architecture/ub-" + RUN_A, RUN_A), (RUN_A + "/proposal", RUN_A),
                         ("proposal", RUN_B)):
            folder = self.docs(*rel.split("/"))
            textio.write_text_atomic(os.path.join(folder, "0001-old.md"), "# old\n")
            textio.write_json_atomic(os.path.join(folder, handoff.LEGACY_MARKER),
                                     {"run": run, "files": ["0001-old.md"]})
        before = snapshot(self.docs())
        a = self.linked_run(RUN_A)
        self.assertIn("Kit 2.0.x published this run to docs/architecture/ub-%s, docs/adr, docs/%s/proposal: those "
                      "copies are left as they are and no longer updated (move or delete them yourself)."
                      % (RUN_A, RUN_A), gates.display(a, "G14"))
        handoff.publish(a, ITEMS)
        after = snapshot(self.docs())
        self.assertEqual(dict((k, v) for k, v in after.items() if not k.startswith(RUN_A + "/1")), before)
        self.assertEqual(self.broken_links(), [])

    def test_a_run_name_that_is_not_a_folder_name_is_refused(self):
        a = self.run_ctx(RUN_A)
        a.state["run"] = "a run: with spaces"
        plan = handoff.plan_target(a, "proposal")
        self.assertEqual((plan["dst"], plan["why"]), (None, "the run name is not a safe folder name"))
        self.assertEqual(handoff.publish(a, ["proposal"])["not_published"],
                         ["10_ARCHITECTURE/adr (the run name is not a safe folder name)",
                          "11_PROPOSAL (the run name is not a safe folder name)"])
        self.assertFalse(os.path.exists(self.docs()))


class CrossRunTests(PublishCase):
    def test_a_second_run_never_touches_the_first(self):
        handoff.publish(self.linked_run(RUN_A), ITEMS)
        before = snapshot(self.docs(RUN_A))
        b = self.linked_run(RUN_B, adrs=("0001-c",))
        self.assertEqual(handoff.publish(b, ITEMS)["published"][0],
                         "10_ARCHITECTURE -> docs/%s/10_ARCHITECTURE" % RUN_B)
        self.assertEqual(snapshot(self.docs(RUN_A)), before)
        self.assertEqual(sorted(os.listdir(self.docs())), sorted([RUN_A, RUN_B]))
        self.assertEqual(os.listdir(self.docs(RUN_B, "10_ARCHITECTURE", "adr")), ["0001-c.md"])
        self.assertFalse(os.path.exists(b.path("_superseded")))
        self.assertEqual(self.broken_links(), [])

    CHILD = "\n".join([
        "import json, os, sys, time",
        "sys.path.insert(0, sys.argv[1])",
        "import engine_testlib as tl",
        "from ublib.engine import handoff, state as st",
        "project, run, slug, go, ready, out, offset = sys.argv[2:9]",
        "run_dir = os.path.join(project, 'brainstorm', run)",
        "os.makedirs(run_dir, exist_ok=True)",
        "st.ensure_run_dirs(run_dir)",
        "state = st.new_state(run_dir, 't', 'claude-code', 'claude', mode='standard', variant='product',",
        "                     runner='python ub.py', project_dir=project)",
        "ctx = st.Ctx(run_dir, state, tl.FakeDeps())",
        "ctx.write('10_ARCHITECTURE/README.md', '# %s\\n\\nSee [ADR-0001](adr/0001-%s.md).\\n' % (slug, slug))",
        "for i in range(6):",
        "    ctx.write('10_ARCHITECTURE/sections/%02d.md' % i, '# s%d %s\\n' % (i, slug))",
        "    ctx.write('10_ARCHITECTURE/adr/%04d-%s.md' % (i + 1, slug), '# ADR %d %s\\n' % (i + 1, slug))",
        "ctx.write('11_PROPOSAL/PROPOSAL.md', '# Proposal %s\\n' % slug)",
        "ctx.write('11_PROPOSAL/README.md', '# Proposal files %s\\n' % slug)",
        "open(ready, 'w').close()",
        "while not os.path.exists(go):",
        "    pass",
        "from ublib import textio",
        "start = float(textio.read_text(go)) + float(offset) / 1000.0  # retries a Windows sharing violation",
        "while time.time() < start:",
        "    pass",
        "res = handoff.publish(ctx, ['architecture', 'adr', 'proposal'])",
        "with open(out, 'w') as fh:",
        "    json.dump(res, fh)",
    ])

    def race(self, offset_ms, trial):
        """Two processes publish two runs into one project, B starting offset_ms after A (both spin on the clock)."""
        project = os.path.join(self.tmp, "race-%d-%d" % (offset_ms, trial), "project")
        os.makedirs(project)
        sync = os.path.dirname(project)
        procs = []
        for run, slug, off in ((RUN_A, "alpha", 0), (RUN_B, "beta", offset_ms)):
            procs.append(subprocess.Popen(
                [sys.executable, "-c", self.CHILD, FIXTURES, project, run, slug, os.path.join(sync, "go"),
                 os.path.join(sync, slug + ".ready"), os.path.join(sync, slug + ".json"), str(off)],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE))
        deadline = time.time() + 120
        while not all(os.path.exists(os.path.join(sync, s + ".ready")) for s in ("alpha", "beta")):
            self.assertTrue(time.time() < deadline and all(p.poll() is None for p in procs), "a child did not start")
            time.sleep(0.005)
        textio.write_text_atomic(os.path.join(sync, "go"), repr(time.time() + 0.1))
        for p in procs:
            _out, err = p.communicate(timeout=120)
            self.assertEqual(p.returncode, 0, err.decode("utf-8", "replace"))
        return project

    def test_two_runs_publishing_at_the_same_moment_never_mix(self):
        for trial, offset_ms in enumerate((0, 0, 1, 2, 3, 5)):
            project = self.race(offset_ms, trial)
            docs = os.path.join(project, "docs")
            self.assertEqual(sorted(os.listdir(docs)), sorted([RUN_A, RUN_B]), (offset_ms, trial))
            for run, mine, other in ((RUN_A, b"alpha", b"beta"), (RUN_B, b"beta", b"alpha")):
                tree = snapshot(os.path.join(docs, run))
                source = dict(("10_ARCHITECTURE/" + k, v) for k, v in snapshot(os.path.join(
                    project, "brainstorm", run, "10_ARCHITECTURE")).items())
                source.update(("11_PROPOSAL/" + k, v) for k, v in snapshot(os.path.join(
                    project, "brainstorm", run, "11_PROPOSAL")).items())
                self.assertEqual(tree, source, (offset_ms, trial, run))
                self.assertTrue(all(mine in v and other not in v for v in tree.values()), (offset_ms, trial, run))
                self.assertFalse(os.path.exists(os.path.join(project, "brainstorm", run, "_superseded")))


class UpdateTests(PublishCase):
    def test_a_republish_is_idempotent(self):
        a = self.linked_run(RUN_A)
        first = handoff.publish(a, ITEMS)
        before, record = snapshot(self.docs()), self.record(a)
        self.assertEqual(handoff.publish(a, ITEMS), first)
        self.assertEqual(snapshot(self.docs()), before)
        self.assertEqual(self.record(a), record)
        self.assertFalse(os.path.exists(a.path("_superseded")))
        self.assertEqual(handoff.plan_target(a, "architecture")["state"], "update")

    def test_a_republish_replaces_changed_files_with_a_backup(self):
        a = self.run_ctx(RUN_A, "use-sqlite", readme="# v1\n")
        handoff.publish(a, ["architecture"])
        a.write("10_ARCHITECTURE/README.md", "# v2\n")
        a.write("10_ARCHITECTURE/risks.md", "# Risks\n")
        with mock.patch.object(handoff.st, "iso_stamp", return_value=STAMP):
            self.assertEqual(handoff.publish(a, ["architecture"])["published"],
                             ["10_ARCHITECTURE -> docs/%s/10_ARCHITECTURE" % RUN_A])
        self.assertEqual(self.read(RUN_A, "10_ARCHITECTURE", "README.md"), "# v2\n")
        self.assertEqual(textio.read_text(a.path("_superseded", STAMP, "published", "10_ARCHITECTURE", "README.md")),
                         "# v1\n")
        self.assertIn("10_ARCHITECTURE/risks.md", self.record(a)["files"])

    def test_a_switched_architecture_replaces_the_old_adr_set(self):
        a = self.linked_run(RUN_A)
        handoff.publish(a, ITEMS)
        a = self.switch(a, ("0001-pg",))
        with mock.patch.object(handoff.st, "iso_stamp", return_value=STAMP):
            res = handoff.publish(a, ITEMS)
        self.assertEqual(res["published"][0], "10_ARCHITECTURE -> docs/%s/10_ARCHITECTURE (2 old files moved to "
                                              "_superseded)" % RUN_A)
        self.assertEqual(os.listdir(self.docs(RUN_A, "10_ARCHITECTURE", "adr")), ["0001-pg.md"])
        self.assertTrue(os.path.isfile(a.path("_superseded", STAMP, "published", "10_ARCHITECTURE", "adr",
                                              "0001-a.md")))
        self.assertNotIn("10_ARCHITECTURE/adr/0001-a.md", self.record(a)["files"])
        self.assertEqual(self.broken_links(), [])

    def test_a_partial_answer_keeps_old_files_a_copy_left_out_may_link_to(self):
        a = self.linked_run(RUN_A)
        handoff.publish(a, ITEMS)
        a = self.switch(a, ("0001-pg",))
        plan = handoff.plan_target(a, "adr", ["adr"])
        self.assertEqual((plan["stale"], plan["kept"]), ([], ["10_ARCHITECTURE/adr/0001-a.md",
                                                              "10_ARCHITECTURE/adr/0002-b.md"]))
        self.assertIn("2 files this run no longer has stay: a copy not in the answer may link to them",
                      handoff.card_line(plan))
        self.assertEqual(handoff.publish(a, ["adr"])["published"], [
            "10_ARCHITECTURE/adr -> docs/%s/10_ARCHITECTURE/adr (2 old files kept: a copy not in the answer may link "
            "to them)" % RUN_A])
        self.assertEqual(self.broken_links(), [])  # the old architecture and proposal copies still resolve
        handoff.publish(a, ITEMS)  # every copy published again: the old ADRs go
        self.assertEqual(os.listdir(self.docs(RUN_A, "10_ARCHITECTURE", "adr")), ["0001-pg.md"])
        self.assertEqual(self.broken_links(), [])

    def test_an_emptied_package_moves_this_runs_old_copy_to_the_backup(self):
        a = self.run_ctx(RUN_A, "use-sqlite")
        handoff.publish(a, ITEMS)
        shutil.rmtree(a.path("10_ARCHITECTURE", "adr"))  # `ub switch --arch` chose an architecture with zero ADRs
        self.assertIn("- adr: 10_ARCHITECTURE/adr -> docs/%s/10_ARCHITECTURE/adr (this run published it before; its "
                      "package now has no files; 1 file this run no longer has moves to _superseded/)" % RUN_A,
                      gates.display(a, "G14"))
        self.assertEqual(handoff.publish(a, ITEMS)["published"][:2], [
            "10_ARCHITECTURE -> docs/%s/10_ARCHITECTURE (1 old file moved to _superseded)" % RUN_A,
            "10_ARCHITECTURE/adr -> docs/%s/10_ARCHITECTURE/adr (in the architecture copy)" % RUN_A])
        self.assertEqual(os.listdir(self.docs(RUN_A, "10_ARCHITECTURE")), ["README.md"])  # the empty adr/ is gone
        self.assertEqual(handoff.plan_target(a, "adr")["state"], "empty")

    def test_a_file_added_to_the_published_folder_never_forks_the_run(self):
        a = self.run_ctx(RUN_A, "one")
        handoff.publish(a, ITEMS)
        textio.write_text_atomic(self.docs(RUN_A, "10_ARCHITECTURE", "adr", "0002-team.md"), "# ours\n")
        a.write("10_ARCHITECTURE/adr/0001-one.md", "# ADR 0001 one v2\n")
        plan = handoff.plan_target(a, "adr")
        self.assertEqual((plan["dst"], plan["other"]), ("docs/%s/10_ARCHITECTURE/adr" % RUN_A,
                                                        ["10_ARCHITECTURE/adr/0002-team.md"]))
        self.assertIn("1 file this run did not publish stays as it is", handoff.card_line(plan))
        res = handoff.publish(a, ITEMS)
        self.assertIn("1 file this run did not publish left as it is", res["published"][0])
        self.assertEqual(self.read(RUN_A, "10_ARCHITECTURE", "adr", "0001-one.md"), "# ADR 0001 one v2\n")
        self.assertEqual(self.read(RUN_A, "10_ARCHITECTURE", "adr", "0002-team.md"), "# ours\n")
        copies = [os.path.join(d, f) for d, _s, fs in os.walk(self.docs()) for f in fs if f.startswith("0001-")]
        self.assertEqual(len(copies), 1, copies)  # one copy of ADR-0001, updated where it was published

    def test_a_file_already_at_a_planned_name_is_backed_up_first(self):
        textio.write_text_atomic(self.docs(RUN_A, "11_PROPOSAL", "PROPOSAL.md"), "# someone else's\n")
        a = self.run_ctx(RUN_A)
        self.assertIn("- proposal: 11_PROPOSAL -> docs/%s/11_PROPOSAL (1 file it replaces is backed up to "
                      "_superseded/ first)" % RUN_A, gates.display(a, "G14"))
        with mock.patch.object(handoff.st, "iso_stamp", return_value=STAMP):
            handoff.publish(a, ["proposal"])
        self.assertEqual(textio.read_text(a.path("_superseded", STAMP, "published", "11_PROPOSAL", "PROPOSAL.md")),
                         "# someone else's\n")
        self.assertEqual(self.read(RUN_A, "11_PROPOSAL", "PROPOSAL.md"), "# Proposal %s\n" % RUN_A)

    def test_same_second_publishes_never_overwrite_a_backup(self):
        a = self.run_ctx(RUN_A, readme="# v1\n")
        handoff.publish(a, ["architecture"])
        with mock.patch.object(handoff.st, "iso_stamp", return_value=STAMP):
            for text in ("# v2\n", "# v3\n"):
                a.write("10_ARCHITECTURE/README.md", text)
                handoff.publish(a, ["architecture", "architecture"])
        sup = a.path("_superseded")
        self.assertEqual(textio.read_text(os.path.join(sup, STAMP, "published", "10_ARCHITECTURE", "README.md")),
                         "# v1\n")
        self.assertEqual(textio.read_text(os.path.join(sup, STAMP + "-2", "published", "10_ARCHITECTURE",
                                                       "README.md")), "# v2\n")

    def test_a_case_only_rename_leaves_one_name(self):
        a = self.run_ctx(RUN_A, "X")
        handoff.publish(a, ["adr"])
        shutil.rmtree(a.path("10_ARCHITECTURE", "adr"))
        a.write("10_ARCHITECTURE/adr/0001-x.md", "# lower\n")
        plan = handoff.plan_target(a, "adr", ["adr"])
        if not plan["renamed"]:
            self.skipTest("the disk is case-sensitive")
        self.assertEqual(handoff.publish(a, ["adr"])["published"],
                         ["10_ARCHITECTURE/adr -> docs/%s/10_ARCHITECTURE/adr (1 old file moved to _superseded)"
                          % RUN_A])
        self.assertEqual(os.listdir(self.docs(RUN_A, "10_ARCHITECTURE", "adr")), ["0001-x.md"])
        self.assertEqual(self.record(a)["files"], ["10_ARCHITECTURE/adr/0001-x.md"])


class InterruptTests(PublishCase):
    def outcome(self, failing=None):
        """Publish, switch the architecture, publish again (first under `failing`, which must raise, then again):
        the published tree and the record."""
        shutil.rmtree(self.docs(), ignore_errors=True)
        shutil.rmtree(os.path.join(self.project, "brainstorm"), ignore_errors=True)
        a = self.linked_run(RUN_A)
        handoff.publish(a, ITEMS)
        a = self.switch(a, ("0001-pg", "0002-b"))
        if failing:
            with failing, self.assertRaises(PermissionError):
                handoff.publish(a, ITEMS)
        handoff.publish(a, ITEMS)
        self.assertEqual(self.broken_links(), [])
        record = dict(self.record(a))
        self.assertRegex(record.pop("claim"), "^[0-9a-f]{32}$")  # a random id per run
        return snapshot(self.docs()), record

    def fail_nth_docs_write(self, n):
        real = handoff._write_public
        calls = []

        def write(path, data, mode):
            if os.sep + "docs" + os.sep in os.path.abspath(path):
                calls.append(path)
                if len(calls) == n:
                    raise PermissionError("locked")
            return real(path, data, mode)
        return mock.patch.object(handoff, "_write_public", side_effect=write)

    def fail_old_file_moves(self):
        real = shutil.move

        def move(src, dst, *a, **k):
            if os.sep + "docs" + os.sep in os.path.abspath(src):
                raise PermissionError("locked")
            return real(src, dst, *a, **k)
        return mock.patch.object(handoff.shutil, "move", side_effect=move)

    def test_an_interrupted_publish_runs_again_to_the_same_result(self):
        control = self.outcome()
        self.assertEqual(sorted(k for k in control[0] if "/adr/" in k),
                         [RUN_A + "/10_ARCHITECTURE/adr/0001-pg.md", RUN_A + "/10_ARCHITECTURE/adr/0002-b.md"])
        for n in (1, 2, 4):
            self.assertEqual(self.outcome(self.fail_nth_docs_write(n)), control, n)
        self.assertEqual(self.outcome(self.fail_old_file_moves()), control)

    def test_temp_files_of_a_killed_write_are_removed(self):
        a = self.run_ctx(RUN_A, "a")
        handoff.publish(a, ITEMS)
        folder = self.docs(RUN_A, "10_ARCHITECTURE")
        for name in (".README.md.k2j4x9ab.tmp", "notes.tmp", ".README.md.backup.tmp"):
            textio.write_text_atomic(os.path.join(folder, name), "partial\n")
        a.write("10_ARCHITECTURE/README.md", "# changed\n")
        handoff.publish(a, ITEMS)
        self.assertEqual(sorted(os.listdir(folder)), [".README.md.backup.tmp", "README.md", "adr", "notes.tmp"])


class LinkTests(PublishCase):
    def test_a_link_above_the_copy_is_never_written_through(self):
        outside = os.path.join(self.tmp, "outside")
        os.makedirs(outside)
        os.makedirs(self.docs())
        if not make_dir_link(self.docs(RUN_A), outside):
            self.skipTest("cannot create a directory link here")
        a = self.run_ctx(RUN_A, "a")
        plan = handoff.plan_target(a, "proposal")
        self.assertIsNone(plan["dst"])
        self.assertEqual(handoff.card_line(plan), "- proposal: 11_PROPOSAL -> not published (docs/%s is a link or "
                                                  "junction). To publish it, move docs/%s aside and redo step 14.2."
                         % (RUN_A, RUN_A))
        res = handoff.publish(a, ITEMS)
        self.assertEqual(res["published"], [])
        self.assertEqual(len(res["not_published"]), 3)
        self.assertEqual(os.listdir(outside), [])
        self.assertIsNone(self.record(a))

    def test_a_link_inside_the_copy_is_never_written_through(self):
        outside = os.path.join(self.tmp, "outside")
        os.makedirs(outside)
        os.makedirs(self.docs(RUN_A, "10_ARCHITECTURE"))
        if not make_dir_link(self.docs(RUN_A, "10_ARCHITECTURE", "adr"), outside):
            self.skipTest("cannot create a directory link here")
        a = self.run_ctx(RUN_A, "a")
        res = handoff.publish(a, ITEMS)
        why = "docs/%s/10_ARCHITECTURE/adr is a link or junction" % RUN_A
        self.assertEqual(res, {"published": ["11_PROPOSAL -> docs/%s/11_PROPOSAL" % RUN_A], "not_published": [
            "10_ARCHITECTURE (%s)" % why, "10_ARCHITECTURE/adr (%s)" % why]})
        self.assertEqual(os.listdir(outside), [])

    def test_a_hard_link_in_the_copy_is_replaced_not_written_through(self):
        a = self.run_ctx(RUN_A, readme="# v1\n")
        handoff.publish(a, ["architecture"])
        outside = os.path.join(self.tmp, "outside.md")
        textio.write_text_atomic(outside, "OUTSIDE\n")
        target = self.docs(RUN_A, "10_ARCHITECTURE", "README.md")
        os.remove(target)
        try:
            os.link(outside, target)
        except (OSError, AttributeError, NotImplementedError):
            self.skipTest("cannot create a hard link here")
        a.write("10_ARCHITECTURE/README.md", "# v2\n")
        handoff.publish(a, ["architecture"])
        self.assertEqual(textio.read_text(outside), "OUTSIDE\n")
        self.assertEqual(textio.read_text(target), "# v2\n")

    def test_a_file_link_at_a_planned_name_is_moved_aside_not_followed(self):
        outside = os.path.join(self.tmp, "outside.md")
        textio.write_text_atomic(outside, "OUTSIDE\n")
        os.makedirs(self.docs(RUN_A, "11_PROPOSAL"))
        try:
            os.symlink(outside, self.docs(RUN_A, "11_PROPOSAL", "PROPOSAL.md"))
        except (OSError, NotImplementedError, AttributeError):
            self.skipTest("cannot create a file symlink here")
        a = self.run_ctx(RUN_A)
        with mock.patch.object(handoff.st, "iso_stamp", return_value=STAMP):
            handoff.publish(a, ["proposal"])
        self.assertEqual(textio.read_text(outside), "OUTSIDE\n")
        self.assertFalse(os.path.islink(self.docs(RUN_A, "11_PROPOSAL", "PROPOSAL.md")))
        self.assertTrue(os.path.islink(a.path("_superseded", STAMP, "published", "11_PROPOSAL", "PROPOSAL.md")))

    def test_a_tampered_record_never_reaches_outside_the_copy(self):
        victim = os.path.join(self.project, "victim.md")
        textio.write_text_atomic(victim, "# keep me\n")
        a = self.run_ctx(RUN_A)
        a.write_json(handoff.PUBLISH_RECORD, {"schema": 1, "docs": "docs/" + RUN_A,
                                              "files": ["../../victim.md", "/victim.md", "C:/victim.md",
                                                        "11_PROPOSAL/../../../victim.md"]})
        handoff.publish(a, ITEMS)
        self.assertEqual(textio.read_text(victim), "# keep me\n")
        self.assertNotIn("victim.md", " ".join(self.record(a)["files"]))


class ModeTests(PublishCase):
    def test_every_published_file_gets_the_umask_mode(self):
        # the mode is set on the temp file before the rename, so a published file never exists owner-only
        a = self.linked_run(RUN_A)
        chmods, renamed = {}, {}
        real_replace = handoff.textio._replace_with_retry

        def replace(src, dst, *args, **kw):
            renamed[os.path.normcase(os.path.abspath(dst))] = os.path.normcase(os.path.abspath(src))
            return real_replace(src, dst, *args, **kw)
        with mock.patch.object(handoff, "_POSIX_MODES", True), \
                mock.patch.object(handoff.os, "chmod",
                                  side_effect=lambda p, m: chmods.__setitem__(os.path.normcase(p), m)), \
                mock.patch.object(handoff.textio, "_replace_with_retry", side_effect=replace):
            handoff.publish(a, ITEMS)
        modes = {}
        for rel in self.record(a)["files"]:
            tmp = renamed[os.path.normcase(os.path.abspath(self.docs(RUN_A, *rel.split("/"))))]
            modes[rel] = chmods.get(tmp)
        self.assertEqual(set(modes.values()), {handoff._public_mode()}, modes)

    def test_an_unchanged_file_keeps_the_mode_it_has(self):
        # P3 review note: a republish chmod-ed an owner-only file that had not changed back to the umask mode, so a
        # proposal someone made private on purpose became readable by everyone
        a = self.linked_run(RUN_A)
        handoff.publish(a, ITEMS)
        docs = os.path.normcase(self.docs()) + os.sep
        real_stat = os.stat

        def owner_only(path, *args, **kw):  # every published file reads as mode 0600 (what a user set)
            st = real_stat(path, *args, **kw)
            if isinstance(path, str) and os.path.normcase(os.path.abspath(path)).startswith(docs) \
                    and stat.S_ISREG(st.st_mode):
                return os.stat_result((stat.S_IFREG | 0o600,) + tuple(st)[1:])
            return st
        calls = []
        with mock.patch.object(handoff, "_POSIX_MODES", True), \
                mock.patch.object(handoff.os, "chmod", side_effect=lambda p, m: calls.append((p, m))), \
                mock.patch.object(handoff.os, "stat", side_effect=owner_only):
            handoff.publish(a, ITEMS)
        self.assertEqual(calls, [])

    @unittest.skipUnless(os.name == "posix", "POSIX file modes")
    def test_published_files_are_readable_by_others_under_umask_022(self):
        old = os.umask(0o022)
        self.addCleanup(os.umask, old)
        a = self.run_ctx(RUN_A, "a")
        handoff.publish(a, ITEMS)
        adr = self.docs(RUN_A, "10_ARCHITECTURE", "adr", "0001-a.md")
        for rel in self.record(a)["files"]:
            self.assertEqual(stat.S_IMODE(os.stat(self.docs(RUN_A, *rel.split("/"))).st_mode), 0o644, rel)
        self.assertEqual(stat.S_IMODE(os.stat(a.path("10_ARCHITECTURE", "README.md")).st_mode), 0o600)
        for chosen in (0o600, 0o640):  # a mode someone chose stays while the bytes are the run's
            os.chmod(adr, chosen)
            handoff.publish(a, ITEMS)
            self.assertEqual(stat.S_IMODE(os.stat(adr).st_mode), chosen)
        a.write("10_ARCHITECTURE/adr/0001-a.md", "# changed\n")  # a new version gets the umask mode
        handoff.publish(a, ITEMS)
        self.assertEqual(stat.S_IMODE(os.stat(adr).st_mode), 0o644)


class RecordTests(PublishCase):
    def test_handoff_records_what_was_published_and_what_was_not(self):
        b = self.run_ctx(RUN_B, adrs=False)
        b.state.setdefault("gates", {})["G14"] = {"answer": {"publish": ["adr", "proposal"], "handoff": "none"}}
        note = handoff.handoff_seed(b, {"id": "14.3"})
        self.assertEqual(b.state["published"], ["11_PROPOSAL -> docs/%s/11_PROPOSAL" % RUN_B])
        self.assertEqual(b.state["not_published"], ["10_ARCHITECTURE/adr (no files)"])
        self.assertIn("; not published: 10_ARCHITECTURE/adr (no files)", note)
        handoff.handoff_final(b, {"id": "14.4"})
        text = b.read("12_HANDOFF.md")
        self.assertIn("- Published: 11_PROPOSAL -> docs/%s/11_PROPOSAL\n" % RUN_B, text)
        self.assertIn("- Not published: 10_ARCHITECTURE/adr (no files)\n", text)

    def test_the_seed_comes_from_its_template(self):
        a = self.run_ctx(RUN_A)
        text = handoff.seed_text(a, "ce")
        self.assertIn("Architecture decisions: brainstorm/%s/10_ARCHITECTURE/README.md (ADRs accepted)" % RUN_A, text)
        self.assertTrue(text.endswith(handoff.CLOSING + "\n"))
        self.assertNotIn("{{", text)
        with mock.patch.object(registry, "load_template", return_value=None):
            with self.assertRaises(EngineError) as cm:
                handoff.seed_text(a, "ce")
        self.assertIn("HANDOFF-CE", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
