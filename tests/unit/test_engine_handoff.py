"""B3 engine: Stage 14 publish (KIT_SPEC 9, 14.2). The first run publishes into docs/architecture, docs/adr and
docs/proposal; a later run whose targets hold another run's package (or the project's own files) publishes into
docs/<run>/<item> and never touches what is there; the G14 card names the real target and the other run. A run's own
earlier copy is updated in place, an interrupted publish resumes in place, and links are never written through."""

import os
import re
import shutil
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fixtures", "engine"))
import engine_testlib as tl  # noqa: E402

from ublib import textio  # noqa: E402
from ublib.engine import gates, handoff  # noqa: E402

RUN_A = "2026-09-24-act-principal-ai-research-scientist"
RUN_B = "2026-09-24-need-create-best-every-binary"
ITEMS = ["architecture", "adr", "proposal"]


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


class PublishCase(tl.EngineTestCase):
    def run_ctx(self, name, adr_slug="x", readme="# Architecture\n", adrs=True):
        ctx = self.make_ctx(run_name=name)
        ctx.write("10_ARCHITECTURE/README.md", readme)
        if adrs:
            ctx.write("10_ARCHITECTURE/adr/0001-%s.md" % adr_slug, "# ADR 0001 %s\n" % adr_slug)
        ctx.write("11_PROPOSAL/PROPOSAL.md", "# Proposal %s\n" % name)
        return ctx

    def docs(self, *parts):
        return os.path.join(self.project, "docs", *parts)

    def answered(self, ctx, at="2026-09-25T10:00:00Z"):
        ctx.state.setdefault("gates", {})["G14"] = {"state": "answered", "at": at, "answer": {"publish": True}}
        return ctx

    def marker(self, *parts):
        return textio.read_json(self.docs(*(parts + (handoff.PUBLISHED_MARKER,))))

    def snapshot(self, root):
        out = {}
        for dirpath, _dirs, files in os.walk(root):
            for f in files:
                full = os.path.join(dirpath, f)
                with open(full, "rb") as fh:
                    out[os.path.relpath(full, root).replace("\\", "/")] = fh.read()
        return out


class CrossRunTests(PublishCase):
    def test_first_run_publishes_at_the_fixed_paths(self):
        a = self.run_ctx(RUN_A, "run-the-whole-system-on-one")
        res = handoff.publish(a, ITEMS)
        self.assertEqual(res, {"published": ["10_ARCHITECTURE -> docs/architecture (its ADRs are in docs/adr)",
                                             "10_ARCHITECTURE/adr -> docs/adr", "11_PROPOSAL -> docs/proposal"],
                               "not_published": []})
        self.assertTrue(os.path.isfile(self.docs("adr", "0001-run-the-whole-system-on-one.md")))
        self.assertTrue(os.path.isfile(self.docs("proposal", "PROPOSAL.md")))
        self.assertEqual(self.marker("adr"), {"schema": 2, "run": RUN_A,
                                              "files": ["0001-run-the-whole-system-on-one.md"]})
        self.assertEqual(handoff.plan_target(a, "adr")["state"], "update")

    def test_second_run_goes_to_its_own_folder_and_leaves_the_first_untouched(self):
        a = self.run_ctx(RUN_A, "run-the-whole-system-on-one")
        handoff.publish(a, ITEMS)
        before = self.snapshot(self.docs())
        b = self.run_ctx(RUN_B, "admit-claims-only-through-a-pure", readme="# Other architecture\n")
        res = handoff.publish(b, ITEMS)
        self.assertEqual(res["published"], [
            "10_ARCHITECTURE -> docs/%s/architecture (docs/architecture holds run %s; its ADRs are in docs/%s/adr)"
            % (RUN_B, RUN_A, RUN_B),
            "10_ARCHITECTURE/adr -> docs/%s/adr (docs/adr holds run %s)" % (RUN_B, RUN_A),
            "11_PROPOSAL -> docs/%s/proposal (docs/proposal holds run %s)" % (RUN_B, RUN_A)])
        after = self.snapshot(self.docs())
        for rel, data in before.items():
            self.assertEqual(after.get(rel), data, rel)  # the first run's package, markers included, is unchanged
        # one ADR set per folder: no two unrelated 0001 files side by side
        self.assertEqual(sorted(os.listdir(self.docs("adr"))),
                         [handoff.PUBLISHED_MARKER, "0001-run-the-whole-system-on-one.md"])
        self.assertEqual(sorted(os.listdir(self.docs(RUN_B, "adr"))),
                         [handoff.PUBLISHED_MARKER, "0001-admit-claims-only-through-a-pure.md"])
        self.assertEqual(textio.read_text(self.docs(RUN_B, "architecture", "README.md")), "# Other architecture\n")
        self.assertEqual(self.marker(RUN_B, "adr")["run"], RUN_B)
        self.assertFalse(os.path.exists(b.path("_superseded")))  # nothing was overwritten, so nothing backed up

    def test_g14_card_warns_about_the_other_run(self):
        a = self.run_ctx(RUN_A, "run-the-whole-system-on-one")
        handoff.publish(a, ITEMS)
        b = self.run_ctx(RUN_B, "admit-claims-only-through-a-pure")
        text = gates.display(b, "G14")
        self.assertIn("- adr: 10_ARCHITECTURE/adr -> docs/%s/adr. WARNING: docs/adr already holds another run's "
                      "package (%s); nothing there is changed." % (RUN_B, RUN_A), text)
        self.assertIn("-> docs/%s/proposal. WARNING: docs/proposal" % RUN_B, text)
        self.assertNotIn("your own files stay", text)
        # the first run's own card: its earlier copy is updated in place
        self.assertIn("- adr: 10_ARCHITECTURE/adr -> docs/adr (this run published here before; files it replaces "
                      "are backed up first)\n", gates.display(a, "G14"))

    def test_card_on_a_fresh_project_shows_the_fixed_paths(self):
        text = gates.display(self.run_ctx(RUN_A), "G14")
        self.assertIn("- architecture: 10_ARCHITECTURE -> docs/architecture\n", text)
        self.assertIn("- adr: 10_ARCHITECTURE/adr -> docs/adr\n", text)
        self.assertIn("- proposal: 11_PROPOSAL -> docs/proposal\n", text)

    def test_second_run_republishes_into_its_own_folder(self):
        handoff.publish(self.run_ctx(RUN_A, "a"), ITEMS)
        b = self.run_ctx(RUN_B, "b", readme="# b1\n")
        handoff.publish(b, ITEMS)
        b.write("10_ARCHITECTURE/README.md", "# b2\n")
        plan = handoff.plan_target(b, "architecture")
        self.assertEqual((plan["state"], plan["dst"]), ("update", "docs/%s/architecture" % RUN_B))
        self.assertEqual(handoff.publish(b, ["architecture"])["published"][0],
                         "10_ARCHITECTURE -> docs/%s/architecture (its ADRs are in docs/%s/adr)" % (RUN_B, RUN_B))
        self.assertEqual(textio.read_text(self.docs(RUN_B, "architecture", "README.md")), "# b2\n")
        self.assertEqual(textio.read_text(self.docs("architecture", "README.md")), "# Architecture\n")

    def test_the_projects_own_files_are_never_touched(self):
        os.makedirs(self.docs("adr"))
        textio.write_text_atomic(self.docs("adr", "0001-record-architecture-decisions.md"), "# ours\n")
        a = self.run_ctx(RUN_A, "run-the-whole-system-on-one")
        plan = handoff.plan_target(a, "adr")
        self.assertEqual((plan["state"], plan["dst"]), ("foreign", "docs/%s/adr" % RUN_A))
        self.assertIn("docs/adr already holds files the kit did not publish; nothing there is changed.",
                      handoff.card_line(plan))
        handoff.publish(a, ["adr"])
        self.assertEqual(sorted(os.listdir(self.docs("adr"))), ["0001-record-architecture-decisions.md"])
        self.assertTrue(os.path.isfile(self.docs(RUN_A, "adr", "0001-run-the-whole-system-on-one.md")))

    def test_a_same_run_marker_with_extra_files_is_not_claimed(self):
        a = self.run_ctx(RUN_A, "a")
        handoff.publish(a, ["adr"])
        textio.write_text_atomic(self.docs("adr", "0002-added-by-hand.md"), "# by hand\n")
        self.assertEqual(handoff.plan_target(a, "adr")["dst"], "docs/%s/adr" % RUN_A)

    def test_an_empty_folder_with_a_stale_marker_is_free(self):
        os.makedirs(self.docs("adr"))
        textio.write_json_atomic(self.docs("adr", handoff.PUBLISHED_MARKER), {"run": RUN_A, "files": ["gone.md"]})
        b = self.run_ctx(RUN_B, "b")
        self.assertEqual(handoff.publish(b, ["adr"])["published"], ["10_ARCHITECTURE/adr -> docs/adr"])
        self.assertEqual(self.marker("adr"), {"schema": 2, "run": RUN_B, "files": ["0001-b.md"]})

    def test_os_and_editor_litter_does_not_count(self):
        os.makedirs(self.docs("proposal"))
        for name in ("Thumbs.db", ".gitkeep", "desktop.ini"):
            textio.write_text_atomic(self.docs("proposal", name), "x\n")
        a = self.run_ctx(RUN_A, "a")
        self.assertEqual(handoff.plan_target(a, "proposal")["state"], "new")  # a placeholder folder is free
        handoff.publish(self.run_ctx(RUN_A, "a"), ITEMS)
        handoff.publish(self.run_ctx(RUN_B, "b"), ["adr"])
        for d in (self.docs("adr"), self.docs(RUN_B, "adr")):
            textio.write_text_atomic(os.path.join(d, ".DS_Store"), "x\n")
            textio.write_text_atomic(os.path.join(d, "._0001-b.md"), "x\n")
        textio.write_text_atomic(self.docs("adr", "..ub-published.k2j4.tmp"), "{}\n")
        self.assertEqual(handoff.plan_target(a, "adr")["dst"], "docs/adr")
        b = self.run_ctx(RUN_B, "b")
        self.assertEqual((handoff.plan_target(b, "adr")["state"], handoff.plan_target(b, "adr")["dst"]),
                         ("update", "docs/%s/adr" % RUN_B))


class RefusalTests(PublishCase):
    def test_taken_run_folder_is_refused(self):
        handoff.publish(self.run_ctx(RUN_A, "a"), ["adr"])
        os.makedirs(self.docs(RUN_B, "adr"))
        textio.write_text_atomic(self.docs(RUN_B, "adr", "notes.md"), "# mine\n")
        b = self.run_ctx(RUN_B, "b")
        res = handoff.publish(b, ["adr"])
        self.assertEqual(res, {"published": [], "not_published": [
            "10_ARCHITECTURE/adr (docs/adr holds run %s; docs/%s/adr holds files the kit did not publish)"
            % (RUN_A, RUN_B)]})
        self.assertEqual(sorted(os.listdir(self.docs(RUN_B, "adr"))), ["notes.md"])
        self.assertIn("-> not published (docs/adr holds run %s; " % RUN_A,
                      handoff.card_line(handoff.plan_target(b, "adr")))

    def test_a_link_at_the_fixed_folder_diverts_and_a_link_on_both_refuses(self):
        os.makedirs(self.docs("adr"))
        a = self.run_ctx(RUN_A, "a")
        real = handoff._is_link
        blocked = os.path.normcase(self.docs("adr"))
        with mock.patch.object(handoff, "_is_link", side_effect=lambda q: os.path.normcase(q) == blocked or real(q)):
            plan = handoff.plan_target(a, "adr")
            self.assertEqual((plan["state"], plan["dst"]), ("linked", "docs/%s/adr" % RUN_A))
            self.assertIn("-> docs/%s/adr. docs/adr is a link or junction; nothing is written through it." % RUN_A,
                          handoff.card_line(plan))
        os.makedirs(self.docs(RUN_A, "adr"))
        with mock.patch.object(handoff, "_is_link", side_effect=lambda q: q.endswith("adr") or real(q)):
            self.assertEqual(handoff.publish(a, ["adr"])["not_published"], [
                "10_ARCHITECTURE/adr (docs/adr is a link or junction; docs/%s/adr is a link or junction)" % RUN_A])
        self.assertEqual(os.listdir(self.docs("adr")), [])

    def test_a_link_above_the_run_folder_is_never_written_through(self):
        handoff.publish(self.run_ctx(RUN_A, "a"), ["adr"])
        outside = os.path.join(self.tmp, "outside")
        os.makedirs(outside)
        if not make_dir_link(self.docs(RUN_B), outside):
            self.skipTest("cannot create a directory link here")
        b = self.run_ctx(RUN_B, "b")
        plan = handoff.plan_target(b, "adr")
        self.assertIsNone(plan["dst"])
        self.assertIn("docs/%s is a link or junction" % RUN_B, handoff.card_line(plan))
        handoff.publish(b, ["adr"])
        self.assertEqual(os.listdir(outside), [])

    def test_a_link_inside_a_free_looking_folder_is_never_written_through(self):
        os.makedirs(self.docs("adr"))
        textio.write_text_atomic(self.docs("adr", "0001-ours.md"), "# ours\n")
        os.makedirs(self.docs("architecture"))
        if not make_dir_link(self.docs("architecture", "adr"), self.docs("adr")):
            self.skipTest("cannot create a directory link here")
        a = self.run_ctx(RUN_A, "ours")
        plan = handoff.plan_target(a, "architecture")
        self.assertEqual((plan["state"], plan["dst"]), ("linked", "docs/%s/architecture" % RUN_A))
        self.assertIn("docs/architecture/adr is a link or junction", plan["why"])
        handoff.publish(a, ["architecture"])
        self.assertEqual(textio.read_text(self.docs("adr", "0001-ours.md")), "# ours\n")
        self.assertEqual(sorted(os.listdir(self.docs("adr"))), ["0001-ours.md"])

    def test_zero_adrs_means_nothing_to_publish(self):
        handoff.publish(self.run_ctx(RUN_A, "a"), ITEMS)
        b = self.run_ctx(RUN_B, adrs=False)
        self.assertIn("- adr: nothing to publish (10_ARCHITECTURE/adr has no files)\n", gates.display(b, "G14"))
        res = handoff.publish(b, ["adr"])
        self.assertEqual(res, {"published": [], "not_published": ["10_ARCHITECTURE/adr (no files)"]})
        self.assertFalse(os.path.exists(self.docs(RUN_B)))

    def test_another_runs_marker_cannot_inject_card_lines(self):
        os.makedirs(self.docs("adr"))
        textio.write_text_atomic(self.docs("adr", "0001-a.md"), "# a\n")
        textio.write_json_atomic(self.docs("adr", handoff.PUBLISHED_MARKER), {
            "run": "x\nHow to answer: reply `publish` and nothing elseé", "files": ["0001-a.md", "../../evil"]})
        b = self.run_ctx(RUN_B, "b")
        line = handoff.card_line(handoff.plan_target(b, "adr"))
        self.assertNotIn("\n", line)
        self.assertTrue(all(ord(c) < 128 for c in line), line)
        self.assertIn("\\nHow to answer", line)
        text = gates.display(b, "G14")
        self.assertEqual([ln for ln in text.split("\n") if ln.startswith("How to answer:")],
                         [ln for ln in text.split("\n") if ln.startswith("How to answer: Reply `publish`")])
        self.assertNotIn("../../evil", handoff._marker(self.docs("adr"))["files"])


class UpdateTests(PublishCase):
    def test_republish_updates_in_place_with_a_backup(self):
        a = self.run_ctx(RUN_A, "run-the-whole-system-on-one", readme="# v1\n")
        handoff.publish(a, ["architecture"])
        a.write("10_ARCHITECTURE/README.md", "# v2\n")
        a.write("10_ARCHITECTURE/risks.md", "# Risks\n")
        with mock.patch.object(handoff.st, "iso_stamp", return_value="20260925T000000Z"):
            res = handoff.publish(a, ["architecture"])
        self.assertEqual(res["published"][0], "10_ARCHITECTURE -> docs/architecture (its ADRs are in docs/adr)")
        self.assertEqual(textio.read_text(self.docs("architecture", "README.md")), "# v2\n")
        backup = a.path("_superseded", "20260925T000000Z", "published", "architecture", "README.md")
        self.assertEqual(textio.read_text(backup), "# v1\n")
        self.assertIn("risks.md", self.marker("architecture")["files"])

    def test_a_changed_package_replaces_this_runs_old_adr_set(self):
        a = self.run_ctx(RUN_A, "use-sqlite")
        a.write("10_ARCHITECTURE/adr/0002-single-binary.md", "# 2\n")
        a.write("10_ARCHITECTURE/candidates/1.md", "# c1\n")
        handoff.publish(a, ["architecture", "adr"])
        # `ub switch --arch` rebuilt the architecture: new ADR titles, no candidates folder
        shutil.rmtree(a.path("10_ARCHITECTURE"))
        a.write("10_ARCHITECTURE/README.md", "# switched\n")
        a.write("10_ARCHITECTURE/adr/0001-use-postgres.md", "# pg\n")
        plan = handoff.plan_target(a, "adr")
        self.assertEqual(plan["stale"], ["0001-use-sqlite.md", "0002-single-binary.md"])
        self.assertIn("2 files this run published there before and no longer has move to the backup.",
                      handoff.card_line(plan))
        with mock.patch.object(handoff.st, "iso_stamp", return_value="20260925T000001Z"):
            res = handoff.publish(a, ["architecture", "adr"])
        self.assertEqual(res["published"][1], "10_ARCHITECTURE/adr -> docs/adr (2 old files moved to _superseded)")
        self.assertEqual(sorted(os.listdir(self.docs("adr"))), [handoff.PUBLISHED_MARKER, "0001-use-postgres.md"])
        self.assertEqual(sorted(os.listdir(self.docs("architecture"))), [handoff.PUBLISHED_MARKER, "README.md"])
        self.assertEqual(self.marker("adr")["files"], ["0001-use-postgres.md"])
        moved = a.path("_superseded", "20260925T000001Z", "published", "adr", "0001-use-sqlite.md")
        self.assertEqual(textio.read_text(moved), "# ADR 0001 use-sqlite\n")
        self.assertTrue(os.path.isfile(a.path("_superseded", "20260925T000001Z", "published", "architecture",
                                              "candidates", "1.md")))

    def test_a_folder_mixed_by_kit_2_0_2_is_flagged_and_left_as_is(self):
        os.makedirs(self.docs("adr"))
        textio.write_text_atomic(self.docs("adr", "0001-a-thing.md"), "# A's ADR\n")
        textio.write_text_atomic(self.docs("adr", "0001-b-thing.md"), "# ADR 0001 b-thing\n")
        textio.write_json_atomic(self.docs("adr", handoff.PUBLISHED_MARKER),
                                 {"run": RUN_B, "files": ["0001-a-thing.md", "0001-b-thing.md"]})
        b = self.run_ctx(RUN_B, "b-thing")
        plan = handoff.plan_target(b, "adr")
        self.assertEqual((plan["state"], plan["stale"], plan["kept"]), ("update", [], ["0001-a-thing.md"]))
        self.assertIn("WARNING: it also holds 1 file that this run's package does not have, published by kit 2.0.2 "
                      "or earlier and possibly from another run; it stays in place.", handoff.card_line(plan))
        self.assertEqual(handoff.publish(b, ["adr"])["published"],
                         ["10_ARCHITECTURE/adr -> docs/adr (1 file from kit 2.0.2 or earlier left in place)"])
        self.assertTrue(os.path.isfile(self.docs("adr", "0001-a-thing.md")))  # never moved
        self.assertEqual(self.marker("adr"), {"schema": 2, "run": RUN_B, "files": ["0001-b-thing.md"],
                                              "legacy_files": ["0001-a-thing.md"]})
        # later publishes keep the pre-2.0.3 leftover apart: this run's own old ADRs still move to the backup
        shutil.rmtree(b.path("10_ARCHITECTURE", "adr"))
        b.write("10_ARCHITECTURE/adr/0001-zeta.md", "# z\n")
        plan = handoff.plan_target(b, "adr")
        self.assertEqual((plan["stale"], plan["kept"]), (["0001-b-thing.md"], ["0001-a-thing.md"]))
        handoff.publish(b, ["adr"])
        self.assertEqual(sorted(os.listdir(self.docs("adr"))),
                         [handoff.PUBLISHED_MARKER, "0001-a-thing.md", "0001-zeta.md"])

    def test_a_clean_2_0_2_copy_gets_the_new_marker(self):
        os.makedirs(self.docs("adr"))
        textio.write_text_atomic(self.docs("adr", "0001-a.md"), "# old\n")
        textio.write_json_atomic(self.docs("adr", handoff.PUBLISHED_MARKER), {"run": RUN_A, "files": ["0001-a.md"]})
        a = self.run_ctx(RUN_A, "a")
        plan = handoff.plan_target(a, "adr")
        self.assertEqual((plan["state"], plan["stale"], plan["kept"]), ("update", [], []))
        handoff.publish(a, ["adr"])
        self.assertEqual(self.marker("adr"), {"schema": 2, "run": RUN_A, "files": ["0001-a.md"]})

    def test_the_2_0_x_fallback_folder_is_still_this_runs_copy(self):
        os.makedirs(self.docs("adr", "ub-" + RUN_A))
        textio.write_text_atomic(self.docs("adr", "0001-ours.md"), "# ours\n")
        textio.write_text_atomic(self.docs("adr", "ub-" + RUN_A, "0001-a.md"), "# old\n")
        textio.write_json_atomic(self.docs("adr", "ub-" + RUN_A, handoff.PUBLISHED_MARKER),
                                 {"run": RUN_A, "files": ["0001-a.md"]})
        a = self.run_ctx(RUN_A, "a")
        self.assertEqual(handoff.publish(a, ["adr"])["published"], ["10_ARCHITECTURE/adr -> docs/adr/ub-%s" % RUN_A])
        self.assertEqual(textio.read_text(self.docs("adr", "ub-" + RUN_A, "0001-a.md")), "# ADR 0001 a\n")
        self.assertFalse(os.path.exists(self.docs(RUN_A)))


class InterruptTests(PublishCase):
    def fail_second_copy(self):
        real = shutil.copy2
        calls = {"n": 0}

        def copy2(src, dst, *a, **k):
            calls["n"] += 1
            if calls["n"] == 2:
                raise PermissionError("locked")
            return real(src, dst, *a, **k)
        return mock.patch.object(handoff.shutil, "copy2", side_effect=copy2)

    def test_an_interrupted_first_publish_resumes_in_place(self):
        a = self.run_ctx(RUN_A, "a")
        a.write("10_ARCHITECTURE/adr/0002-b.md", "# 2\n")
        with self.fail_second_copy(), self.assertRaises(PermissionError):
            handoff.publish(a, ["adr"])
        self.assertEqual(handoff.plan_target(a, "adr")["dst"], "docs/adr")
        self.assertEqual(handoff.publish(a, ["adr"])["published"], ["10_ARCHITECTURE/adr -> docs/adr"])
        self.assertEqual(sorted(os.listdir(self.docs("adr"))), [handoff.PUBLISHED_MARKER, "0001-a.md", "0002-b.md"])

    def test_an_interrupted_publish_into_the_run_folder_resumes_there(self):
        handoff.publish(self.run_ctx(RUN_A, "a"), ["adr"])
        b = self.run_ctx(RUN_B, "b")
        b.write("10_ARCHITECTURE/adr/0002-c.md", "# 2\n")
        with self.fail_second_copy(), self.assertRaises(PermissionError):
            handoff.publish(b, ["adr"])
        res = handoff.publish(b, ["adr"])
        self.assertEqual(res["published"], ["10_ARCHITECTURE/adr -> docs/%s/adr" % RUN_B])
        self.assertEqual(sorted(os.listdir(self.docs(RUN_B, "adr"))),
                         [handoff.PUBLISHED_MARKER, "0001-b.md", "0002-c.md"])


class Round2Tests(PublishCase):
    def test_litter_in_the_package_is_never_published(self):
        a = self.run_ctx(RUN_A, "a", adrs=False)
        a.write("10_ARCHITECTURE/adr/.DS_Store", "x\n")
        a.write("10_ARCHITECTURE/desktop.ini", "[.ShellClassInfo]\n")
        a.write("11_PROPOSAL/.PROPOSAL.md.swp", "x\n")
        self.assertEqual(handoff.plan_target(a, "adr")["state"], "empty")
        res = handoff.publish(a, ITEMS)
        self.assertEqual(res["not_published"], ["10_ARCHITECTURE/adr (no files)"])
        self.assertEqual(self.marker("architecture")["files"], ["README.md"])
        self.assertFalse(os.path.exists(self.docs("architecture", "desktop.ini")))
        self.assertFalse(os.path.exists(self.docs("proposal", ".PROPOSAL.md.swp")))

    def test_duplicate_items_and_same_second_publishes_never_overwrite_a_backup(self):
        a = self.run_ctx(RUN_A, readme="# v1\n")
        handoff.publish(a, ["architecture"])
        a.write("10_ARCHITECTURE/README.md", "# v2\n")
        with mock.patch.object(handoff.st, "iso_stamp", return_value="20260925T000002Z"):
            res = handoff.publish(a, ["architecture", "architecture"])["published"]
            self.assertEqual(len([ln for ln in res if ln.startswith("10_ARCHITECTURE ->")]), 1)
            a.write("10_ARCHITECTURE/README.md", "# v3\n")
            handoff.publish(a, ["architecture"])
        sup = a.path("_superseded")
        self.assertEqual(textio.read_text(os.path.join(sup, "20260925T000002Z", "published", "architecture",
                                                       "README.md")), "# v1\n")
        self.assertEqual(textio.read_text(os.path.join(sup, "20260925T000002Z-2", "published", "architecture",
                                                       "README.md")), "# v2\n")

    def test_an_unchanged_republish_backs_up_nothing(self):
        a = self.run_ctx(RUN_A, "a")
        handoff.publish(a, ITEMS)
        handoff.publish(a, ITEMS)
        self.assertFalse(os.path.exists(a.path("_superseded")))

    def test_a_hard_link_in_the_target_is_replaced_not_written_through(self):
        a = self.run_ctx(RUN_A, readme="# v1\n")
        handoff.publish(a, ["architecture"])
        outside = os.path.join(self.tmp, "outside.md")
        textio.write_text_atomic(outside, "OUTSIDE\n")
        os.remove(self.docs("architecture", "README.md"))
        try:
            os.link(outside, self.docs("architecture", "README.md"))
        except (OSError, AttributeError, NotImplementedError):
            self.skipTest("cannot create a hard link here")
        a.write("10_ARCHITECTURE/README.md", "# v2\n")
        handoff.publish(a, ["architecture"])
        self.assertEqual(textio.read_text(outside), "OUTSIDE\n")
        self.assertEqual(textio.read_text(self.docs("architecture", "README.md")), "# v2\n")

    def test_a_link_name_is_escaped_on_the_card(self):
        os.makedirs(self.docs("architecture"))
        target = os.path.join(self.tmp, "elsewhere")
        os.makedirs(target)
        if not make_dir_link(self.docs("architecture", "Entw\u00fcrfe"), target):
            self.skipTest("cannot create a directory link here")
        line = handoff.card_line(handoff.plan_target(self.run_ctx(RUN_A), "architecture"))
        self.assertTrue(all(ord(c) < 128 for c in line), line)
        self.assertIn("Entw\\u00fcrfe", line)

    def test_an_update_interrupted_after_its_moves_resumes_in_place_and_says_so(self):
        for where in ("fixed", "fallback"):
            with self.subTest(where=where):
                shutil.rmtree(self.docs(), ignore_errors=True)
                a = self.answered(self.run_ctx(RUN_A, "use-sqlite"))
                if where == "fallback":
                    textio.write_text_atomic(self.docs("adr", "0001-ours.md"), "# ours\n")
                    rel = "docs/adr/ub-" + RUN_A
                    textio.write_text_atomic(self.docs("adr", "ub-" + RUN_A, "0001-use-sqlite.md"), "# old\n")
                    textio.write_json_atomic(self.docs("adr", "ub-" + RUN_A, handoff.PUBLISHED_MARKER),
                                             {"run": RUN_A, "files": ["0001-use-sqlite.md"]})
                else:
                    rel = "docs/adr"
                    handoff.publish(a, ["adr"])
                shutil.rmtree(a.path("10_ARCHITECTURE", "adr"))
                a.write("10_ARCHITECTURE/adr/0001-use-postgres.md", "# pg\n")
                failing = mock.patch.object(handoff, "_copy_replace", side_effect=PermissionError("locked"))
                with failing, self.assertRaises(PermissionError):
                    handoff.publish(a, ["adr"])
                self.assertEqual(handoff.plan_target(a, "adr")["dst"], rel)
                self.assertEqual(handoff.publish(a, ["adr"])["published"],
                                 ["10_ARCHITECTURE/adr -> %s (1 old file moved to _superseded)" % rel])
                folder = os.path.join(self.project, *rel.split("/"))
                self.assertEqual(sorted(os.listdir(folder)), [handoff.PUBLISHED_MARKER, "0001-use-postgres.md"])
                self.assertNotIn("pending_moves", textio.read_json(os.path.join(folder, handoff.PUBLISHED_MARKER)))


class Round3Tests(PublishCase):
    def test_an_emptied_package_moves_this_runs_old_copy_to_the_backup(self):
        a = self.run_ctx(RUN_A, "use-sqlite")
        handoff.publish(a, ITEMS)
        shutil.rmtree(a.path("10_ARCHITECTURE", "adr"))  # `ub switch --arch` chose an architecture with zero ADRs
        plan = handoff.plan_target(a, "adr")
        self.assertEqual((plan["state"], plan["empty"], plan["stale"]), ("update", True, ["0001-use-sqlite.md"]))
        self.assertIn("-> docs/adr (this run published here before; its package now has no files). 1 file this run "
                      "published there before and no longer has moves to the backup.", handoff.card_line(plan))
        res = handoff.publish(a, ["adr"])
        self.assertEqual(res["published"], ["10_ARCHITECTURE/adr -> docs/adr (the package has no files; nothing "
                                            "copied; 1 old file moved to _superseded)"])
        self.assertEqual(os.listdir(self.docs("adr")), [handoff.PUBLISHED_MARKER])
        self.assertEqual(handoff.card_line(handoff.plan_target(a, "adr")),
                         "- adr: 10_ARCHITECTURE/adr -> docs/adr (this run published here before; its package now "
                         "has no files)")
        # with no earlier copy, an empty package is still "nothing to publish"
        self.assertEqual(handoff.plan_target(self.run_ctx(RUN_B, adrs=False), "adr")["state"], "empty")

    def test_a_case_only_rename_is_reported_as_moved(self):
        a = self.run_ctx(RUN_A, "X")
        handoff.publish(a, ["adr"])
        shutil.rmtree(a.path("10_ARCHITECTURE", "adr"))
        a.write("10_ARCHITECTURE/adr/0001-x.md", "# lower\n")
        self.assertEqual(handoff.publish(a, ["adr"])["published"],
                         ["10_ARCHITECTURE/adr -> docs/adr (1 old file moved to _superseded)"])
        self.assertEqual(sorted(os.listdir(self.docs("adr"))), [handoff.PUBLISHED_MARKER, "0001-x.md"])

    def test_moves_of_an_item_finished_before_a_crash_are_still_reported(self):
        a = self.answered(self.run_ctx(RUN_A, "a"))
        a.write("10_ARCHITECTURE/candidates/1.md", "# c1\n")
        handoff.publish(a, ITEMS)
        os.remove(a.path("10_ARCHITECTURE", "candidates", "1.md"))
        a.write("11_PROPOSAL/PROPOSAL.md", "# changed\n")
        real = handoff._copy_replace

        def fail_on_proposal(src, dst, data=None):
            if "proposal" in dst.replace("\\", "/"):
                raise PermissionError("locked")
            return real(src, dst, data)
        with mock.patch.object(handoff, "_copy_replace", side_effect=fail_on_proposal), \
                self.assertRaises(PermissionError):
            handoff.publish(a, ITEMS)
        res = handoff.publish(a, ITEMS)
        self.assertEqual(res["published"][0], "10_ARCHITECTURE -> docs/architecture (its ADRs are in docs/adr; 1 old "
                                              "file moved to _superseded)")
        self.assertEqual(textio.read_text(self.docs("proposal", "PROPOSAL.md")), "# changed\n")
        # a new G14 answer starts a new record
        self.answered(a, at="2026-09-25T11:00:00Z")
        self.assertEqual(handoff.publish(a, ITEMS)["published"][0],
                         "10_ARCHITECTURE -> docs/architecture (its ADRs are in docs/adr)")

    def test_a_cut_name_is_visibly_cut(self):
        shown = handoff._shown("docs/architecture/" + "\u00e9" * 200)
        self.assertTrue(shown.endswith('..."'), shown)
        self.assertTrue(all(ord(c) < 128 for c in shown))
        self.assertEqual(handoff._shown("docs/adr"), "docs/adr")

    def test_temp_files_of_an_interrupted_publish_are_cleaned_up(self):
        a = self.run_ctx(RUN_A, "a")
        handoff.publish(a, ["adr"])
        for name in (".ub-copy.k2j4x.tmp", "..ub-published.9fz.tmp"):
            textio.write_text_atomic(self.docs("adr", name), "partial\n")
        a.write("10_ARCHITECTURE/adr/0002-b.md", "# 2\n")
        handoff.publish(a, ["adr"])
        self.assertEqual(sorted(os.listdir(self.docs("adr"))), [handoff.PUBLISHED_MARKER, "0001-a.md", "0002-b.md"])

    def test_an_empty_folder_of_the_user_is_left_alone(self):
        os.makedirs(self.docs("proposal", "drafts"))
        handoff.publish(self.run_ctx(RUN_A, "a"), ["proposal"])
        self.assertTrue(os.path.isdir(self.docs("proposal", "drafts")))

    def test_litter_listed_by_an_old_marker_is_not_a_leftover(self):
        os.makedirs(self.docs("adr"))
        textio.write_text_atomic(self.docs("adr", "0001-a.md"), "# ADR 0001 a\n")
        textio.write_text_atomic(self.docs("adr", ".DS_Store"), "x\n")
        textio.write_json_atomic(self.docs("adr", handoff.PUBLISHED_MARKER),
                                 {"run": RUN_A, "files": ["0001-a.md", ".DS_Store"]})
        plan = handoff.plan_target(self.run_ctx(RUN_A, "a"), "adr")
        self.assertEqual((plan["state"], plan["kept"], plan["clash"]), ("update", [], []))

    def test_replacing_a_file_an_old_mixed_publish_left_is_flagged(self):
        os.makedirs(self.docs("architecture"))
        textio.write_text_atomic(self.docs("architecture", "README.md"), "# A's readme\n")
        textio.write_text_atomic(self.docs("architecture", "matrix.json"), "{}\n")
        textio.write_json_atomic(self.docs("architecture", handoff.PUBLISHED_MARKER),
                                 {"run": RUN_B, "files": ["README.md", "matrix.json"]})
        b = self.run_ctx(RUN_B, adrs=False, readme="# B's readme\n")
        plan = handoff.plan_target(b, "architecture")
        self.assertEqual((plan["kept"], plan["clash"]), (["matrix.json"], ["README.md"]))
        self.assertIn("WARNING: it replaces 1 file that kit 2.0.2 or earlier published there, possibly another "
                      "run's (backed up first).", handoff.card_line(plan))
        with mock.patch.object(handoff.st, "iso_stamp", return_value="20260925T000003Z"):
            res = handoff.publish(b, ["architecture"])
        self.assertIn("1 file from kit 2.0.2 or earlier replaced, backed up", res["published"][0])
        self.assertEqual(textio.read_text(b.path("_superseded", "20260925T000003Z", "published", "architecture",
                                                 "README.md")), "# A's readme\n")

    def test_the_clash_warning_survives_an_interrupted_publish(self):
        os.makedirs(self.docs("architecture"))
        textio.write_text_atomic(self.docs("architecture", "README.md"), "# A's readme\n")
        textio.write_text_atomic(self.docs("architecture", "matrix.json"), "{}\n")
        textio.write_json_atomic(self.docs("architecture", handoff.PUBLISHED_MARKER),
                                 {"run": RUN_B, "files": ["README.md", "matrix.json"]})
        b = self.answered(self.run_ctx(RUN_B, adrs=False, readme="# B's readme\n"))
        b.write("10_ARCHITECTURE/zz.md", "# zz\n")
        real = handoff._copy_replace

        def fail_on_zz(src, dst, data=None):
            if dst.endswith("zz.md"):
                raise PermissionError("locked")
            return real(src, dst, data)
        # interrupted before anything was replaced: the re-asked card still warns
        with mock.patch.object(handoff, "_copy_replace", side_effect=PermissionError("locked")), \
                self.assertRaises(PermissionError):
            handoff.publish(b, ["architecture"])
        self.assertEqual(handoff.plan_target(b, "architecture")["clash"], ["README.md"])
        # interrupted after README.md was replaced: the record still says so
        with mock.patch.object(handoff, "_copy_replace", side_effect=fail_on_zz), self.assertRaises(PermissionError):
            handoff.publish(b, ["architecture"])
        res = handoff.publish(b, ["architecture"])
        self.assertIn("1 file from kit 2.0.2 or earlier replaced, backed up", res["published"][0])
        self.assertEqual(self.marker("architecture"), {"schema": 2, "run": RUN_B, "files": ["README.md", "zz.md"],
                                                       "legacy_files": ["matrix.json"]})

    def test_a_folder_left_holding_only_another_runs_new_marker_is_not_taken_over(self):
        handoff.publish(self.run_ctx(RUN_A, "a"), ["adr"])
        os.remove(self.docs("adr", "0001-a.md"))  # an interrupted update of run A moved it out
        plan = handoff.plan_target(self.run_ctx(RUN_B, "b"), "adr")
        self.assertEqual((plan["state"], plan["dst"]), ("other-run", "docs/%s/adr" % RUN_B))


LINK_RE = re.compile(r'\]\(([^)\s]+)\)|href="([^"]+)"')
STAMP = "20260925T000000Z"


class AdrLocationTests(PublishCase):
    """ADRs are published once (KIT_SPEC 14.2), only to the adr copy (docs/adr or docs/<run>/adr); `architecture` and
    `proposal` publish it too, and the architecture copy never holds adr/. Every ADR link in the published Markdown
    and HTML points at that one place, and no old ADR file leaves while a published copy still links to it."""

    def linked_run(self, name, adrs=("0001-a", "0002-b")):
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

    def read(self, *parts):
        return textio.read_text(self.docs(*parts))

    def adr_folder_blocked(self):
        """docs/adr is a link or junction (the kit never writes through it)."""
        real = handoff._is_link
        blocked = os.path.normcase(self.docs("adr"))
        return mock.patch.object(handoff, "_is_link", side_effect=lambda q: os.path.normcase(q) == blocked or real(q))

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

    def test_publish_all_copies_the_adrs_once_and_points_every_link_at_them(self):
        a = self.linked_run(RUN_A)
        res = handoff.publish(a, ITEMS)
        self.assertEqual(res["published"], ["10_ARCHITECTURE -> docs/architecture (its ADRs are in docs/adr)",
                                            "10_ARCHITECTURE/adr -> docs/adr", "11_PROPOSAL -> docs/proposal"])
        self.assertEqual(sorted(os.listdir(self.docs("adr"))), [handoff.PUBLISHED_MARKER, "0001-a.md", "0002-b.md"])
        self.assertFalse(os.path.exists(self.docs("architecture", "adr")))
        self.assertFalse([f for f in self.marker("architecture")["files"] if f.startswith("adr/")])
        readme = self.read("architecture", "README.md")
        self.assertIn("| [ADR-0001](../adr/0001-a.md) |", readme)
        self.assertIn("[the containers](chosen/containers.md)", readme)  # other links stay as they are
        self.assertIn("[MADR](https://adr.github.io/madr/adr/)", readme)
        self.assertIn("[ADR-0002](../../adr/0002-b.md)", self.read("architecture", "chosen", "containers.md"))
        self.assertIn("| [ADR-0001](../adr/0001-a.md) |", self.read("proposal", "PROPOSAL.md"))
        self.assertIn("[ADR-0001](../../adr/0001-a.md)", self.read("proposal", "sections", "03.md"))
        self.assertIn('<a href="../adr/0002-b.md">', self.read("proposal", "index.html"))
        self.assertEqual(self.broken_links(), [])
        # the run's own package is untouched: its README still links to its own adr/
        self.assertIn("| [ADR-0001](adr/0001-a.md) |", a.read("10_ARCHITECTURE/README.md"))
        # an unchanged republish rewrites nothing and backs up nothing
        self.assertEqual(handoff.publish(a, ITEMS)["published"], res["published"])
        self.assertFalse(os.path.exists(a.path("_superseded")))

    def test_architecture_and_proposal_publish_the_adrs_too(self):
        a = self.linked_run(RUN_A)
        res = handoff.publish(a, ["architecture", "proposal"])
        self.assertEqual(res["published"], ["10_ARCHITECTURE -> docs/architecture (its ADRs are in docs/adr)",
                                            "10_ARCHITECTURE/adr -> docs/adr (published with the copies that link to "
                                            "it)", "11_PROPOSAL -> docs/proposal"])
        self.assertFalse(os.path.exists(self.docs("architecture", "adr")))
        self.assertIn("| [ADR-0001](../adr/0001-a.md) |", self.read("proposal", "PROPOSAL.md"))
        self.assertEqual(self.broken_links(), [])

    def test_adr_alone_publishes_only_docs_adr(self):
        a = self.linked_run(RUN_A)
        self.assertEqual(handoff.publish(a, ["adr"])["published"], ["10_ARCHITECTURE/adr -> docs/adr"])
        self.assertEqual(sorted(os.listdir(self.docs())), ["adr"])

    def test_proposal_alone_publishes_the_adrs_too(self):
        a = self.linked_run(RUN_A)
        self.assertEqual(handoff.publish(a, ["proposal"])["published"], [
            "10_ARCHITECTURE/adr -> docs/adr (published with the copies that link to it)",
            "11_PROPOSAL -> docs/proposal"])
        self.assertIn("| [ADR-0001](../adr/0001-a.md) |", self.read("proposal", "PROPOSAL.md"))
        self.assertEqual(self.broken_links(), [])

    def test_a_linked_adr_folder_sends_the_adrs_to_the_runs_own_folder(self):
        a = self.linked_run(RUN_A)
        os.makedirs(self.docs("adr"))
        with self.adr_folder_blocked():
            res = handoff.publish(a, ITEMS)
        self.assertEqual(res["published"][1], "10_ARCHITECTURE/adr -> docs/%s/adr (docs/adr is a link or junction)"
                         % RUN_A)
        self.assertFalse(os.path.exists(self.docs("architecture", "adr")))
        self.assertIn("| [ADR-0001](../%s/adr/0001-a.md) |" % RUN_A, self.read("architecture", "README.md"))
        self.assertIn("| [ADR-0001](../%s/adr/0001-a.md) |" % RUN_A, self.read("proposal", "PROPOSAL.md"))
        self.assertEqual(os.listdir(self.docs("adr")), [])
        self.assertEqual(self.broken_links(), [])

    def test_with_no_usable_adr_folder_the_links_are_left_as_they_are(self):
        a = self.linked_run(RUN_A)
        os.makedirs(self.docs("adr"))
        os.makedirs(self.docs(RUN_A, "adr"))
        real = handoff._is_link
        with mock.patch.object(handoff, "_is_link", side_effect=lambda q: q.endswith("adr") or real(q)):
            self.assertIn("The adr folder cannot be used (see above), so the ADR links of the architecture and "
                          "proposal copies are left as they are and will not resolve", gates.display(a, "G14"))
            res = handoff.publish(a, ["proposal"])
        self.assertEqual(res["published"], ["11_PROPOSAL -> docs/proposal (its ADR links are not rewritten: the adr "
                                            "folder cannot be used)"])
        self.assertEqual(self.read("proposal", "PROPOSAL.md"), a.read("11_PROPOSAL/PROPOSAL.md"))

    def test_second_run_links_to_its_own_adr_folder(self):
        handoff.publish(self.linked_run(RUN_A), ITEMS)
        b = self.linked_run(RUN_B, adrs=("0001-c",))
        handoff.publish(b, ITEMS)
        self.assertFalse(os.path.exists(self.docs(RUN_B, "architecture", "adr")))
        self.assertIn("[ADR-0001](../adr/0001-c.md)", self.read(RUN_B, "architecture", "README.md"))
        self.assertIn("[ADR-0001](../adr/0001-c.md)", self.read(RUN_B, "proposal", "PROPOSAL.md"))
        self.assertIn("[ADR-0001](../adr/0001-a.md)", self.read("architecture", "README.md"))  # run A untouched
        self.assertEqual(self.broken_links(), [])

    def test_links_cross_folders_when_only_docs_adr_is_taken(self):
        os.makedirs(self.docs("adr"))
        textio.write_text_atomic(self.docs("adr", "0001-record-architecture-decisions.md"), "# ours\n")
        a = self.linked_run(RUN_A)
        res = handoff.publish(a, ITEMS)
        self.assertEqual(res["published"][:2], [
            "10_ARCHITECTURE -> docs/architecture (its ADRs are in docs/%s/adr)" % RUN_A,
            "10_ARCHITECTURE/adr -> docs/%s/adr (docs/adr holds files the kit did not publish)" % RUN_A])
        self.assertIn("[ADR-0001](../%s/adr/0001-a.md)" % RUN_A, self.read("architecture", "README.md"))
        self.assertIn("[ADR-0001](../%s/adr/0001-a.md)" % RUN_A, self.read("proposal", "PROPOSAL.md"))
        self.assertEqual(sorted(os.listdir(self.docs("adr"))), ["0001-record-architecture-decisions.md"])
        self.assertEqual(self.broken_links(), [])

    def test_republishing_architecture_alone_refreshes_the_adrs_it_links_to(self):
        a = self.linked_run(RUN_A)
        handoff.publish(a, ITEMS)
        self.assertEqual(handoff._layout(a, ["architecture"])["home"], "docs/adr")
        self.assertEqual(handoff.publish(a, ["architecture"])["published"],
                         ["10_ARCHITECTURE -> docs/architecture (its ADRs are in docs/adr)",
                          "10_ARCHITECTURE/adr -> docs/adr (published with the copies that link to it)"])
        self.assertFalse(os.path.exists(self.docs("architecture", "adr")))
        self.assertEqual(self.broken_links(), [])

    def old_architecture_copy_with_adrs(self, a, proposal_links_there=False):
        """The layout the previous kit version published: docs/architecture held adr/ too (schema-2 marker)."""
        files = [r for r, _f in handoff._source_files(a.path("10_ARCHITECTURE"))]
        for r in files:
            os.makedirs(os.path.dirname(self.docs("architecture", *r.split("/"))), exist_ok=True)
            shutil.copy2(a.path("10_ARCHITECTURE", *r.split("/")), self.docs("architecture", *r.split("/")))
        textio.write_json_atomic(self.docs("architecture", handoff.PUBLISHED_MARKER),
                                 {"schema": 2, "run": RUN_A, "files": files})
        if proposal_links_there:
            textio.write_text_atomic(self.docs("proposal", "PROPOSAL.md"),
                                     "# Proposal\n[ADR-0001](../architecture/adr/0001-a.md) "
                                     "[ADR-0002](../architecture/adr/0002-b.md)\n")
            textio.write_json_atomic(self.docs("proposal", handoff.PUBLISHED_MARKER),
                                     {"schema": 2, "run": RUN_A, "files": ["PROPOSAL.md"]})

    def test_adr_copies_inside_an_older_architecture_copy_move_out(self):
        a = self.linked_run(RUN_A)
        self.old_architecture_copy_with_adrs(a)
        self.assertIn("- architecture: 10_ARCHITECTURE -> docs/architecture (this run published here before; files it "
                      "replaces are backed up first). Its old copies of 2 ADRs (ADRs live only in the adr copy now) "
                      "move to the backup.", gates.display(a, "G14"))
        with mock.patch.object(handoff.st, "iso_stamp", return_value=STAMP):
            res = handoff.publish(a, ITEMS)
        self.assertEqual(res["published"][0], "10_ARCHITECTURE -> docs/architecture (its ADRs are in docs/adr; 2 old "
                                              "files moved to _superseded)")
        self.assertFalse(os.path.exists(self.docs("architecture", "adr")))
        backup = a.path("_superseded", STAMP, "published", "architecture", "adr", "0001-a.md")
        self.assertEqual(textio.read_text(backup), a.read("10_ARCHITECTURE/adr/0001-a.md"))
        self.assertEqual(self.broken_links(), [])

    def test_old_adr_copies_stay_while_a_copy_not_republished_links_to_them(self):
        a = self.linked_run(RUN_A)
        self.old_architecture_copy_with_adrs(a, proposal_links_there=True)
        plan = handoff.plan_target(a, "architecture", ["architecture"])
        self.assertIn("Its old copies of 2 ADRs stay, because another published copy of this run links to them",
                      handoff.card_line(plan))
        res = handoff.publish(a, ["architecture"])
        self.assertIn("2 old files kept: another published copy of this run links to them", res["published"][0])
        self.assertTrue(os.path.isfile(self.docs("architecture", "adr", "0001-a.md")))
        self.assertEqual(self.broken_links(), [])
        res = handoff.publish(a, ["architecture", "proposal"])  # now nothing links to them any more
        self.assertIn("2 old files moved to _superseded", res["published"][0])
        self.assertFalse(os.path.exists(self.docs("architecture", "adr")))
        self.assertEqual(self.broken_links(), [])

    def test_a_2_0_2_double_copy_keeps_its_old_architecture_adrs_with_a_warning(self):
        # the 2.0.2 layout: docs/architecture/adr and docs/adr both hold this run's ADRs, markers without schema
        a = self.linked_run(RUN_A)
        for rel, folder in (("10_ARCHITECTURE", "architecture"), ("10_ARCHITECTURE/adr", "adr")):
            files = [r for r, _f in handoff._source_files(a.path(rel))]
            for r in files:
                os.makedirs(os.path.dirname(self.docs(folder, *r.split("/"))), exist_ok=True)
                shutil.copy2(a.path(rel, *r.split("/")), self.docs(folder, *r.split("/")))
            textio.write_json_atomic(self.docs(folder, handoff.PUBLISHED_MARKER), {"run": RUN_A, "files": files})
        self.assertIn("WARNING: it also holds 2 files that this run's package does not have, published by kit 2.0.2 "
                      "or earlier and possibly from another run; they stay in place.", gates.display(a, "G14"))
        res = handoff.publish(a, ["architecture"])
        self.assertIn("2 files from kit 2.0.2 or earlier left in place", res["published"][0])
        self.assertTrue(os.path.isfile(self.docs("architecture", "adr", "0001-a.md")))
        self.assertIn("[ADR-0001](../adr/0001-a.md)", self.read("architecture", "README.md"))
        self.assertEqual(self.marker("adr"), {"schema": 2, "run": RUN_A, "files": ["0001-a.md", "0002-b.md"]})
        self.assertEqual(self.broken_links(), [])

    def test_g14_card_says_where_the_adrs_go(self):
        a = self.linked_run(RUN_A)
        text = gates.display(a, "G14")
        self.assertIn("- proposal: 11_PROPOSAL -> docs/proposal\nADRs are published once, to docs/adr: `architecture` "
                      "and `proposal` publish them there too, and their ADR links point there.", text)
        b = self.linked_run(RUN_B)
        handoff.publish(a, ITEMS)
        self.assertIn("ADRs are published once, to docs/%s/adr" % RUN_B, gates.display(b, "G14"))

    def test_a_run_without_adrs_has_no_adr_note(self):
        a = self.make_ctx(run_name=RUN_A)
        a.write("10_ARCHITECTURE/README.md", "# Approach\n")
        a.write("11_PROPOSAL/PROPOSAL.md", "# Proposal\n")
        text = gates.display(a, "G14")
        self.assertNotIn("ADRs are published once", text)
        self.assertNotIn("adr folder cannot be used", text)
        self.assertIsNone(handoff._layout(a, ITEMS)["home"])
        self.assertEqual(handoff.publish(a, ITEMS)["published"], ["10_ARCHITECTURE -> docs/architecture",
                                                                  "11_PROPOSAL -> docs/proposal"])

    def switch(self, ctx, adrs):
        """`ub switch --arch` / a redo: the run's ADR set, README index and proposal appendix change."""
        shutil.rmtree(ctx.path("10_ARCHITECTURE"))
        shutil.rmtree(ctx.path("11_PROPOSAL"))
        fresh = self.linked_run(os.path.basename(ctx.run_dir), adrs=adrs)
        return fresh

    def test_a_switched_adr_set_is_published_with_the_copies_that_link_to_it(self):
        a = self.linked_run(RUN_A)
        handoff.publish(a, ITEMS)
        a = self.switch(a, ("0001-pg",))
        handoff.publish(a, ["architecture", "proposal"])
        self.assertEqual(sorted(os.listdir(self.docs("adr"))), [handoff.PUBLISHED_MARKER, "0001-pg.md"])
        self.assertFalse(os.path.exists(self.docs("architecture", "adr")))
        self.assertEqual(self.broken_links(), [])

    def test_adr_and_proposal_after_a_switch_keep_what_the_architecture_copy_links_to(self):
        a = self.linked_run(RUN_A)
        handoff.publish(a, ["architecture"])
        a = self.switch(a, ("0001-pg",))
        res = handoff.publish(a, ["adr", "proposal"])
        self.assertIn("2 old files kept", res["published"][0])
        self.assertEqual(sorted(os.listdir(self.docs("adr"))),
                         [handoff.PUBLISHED_MARKER, "0001-a.md", "0001-pg.md", "0002-b.md"])
        self.assertIn("[ADR-0001](../adr/0001-pg.md)", self.read("proposal", "PROPOSAL.md"))
        self.assertEqual(self.broken_links(), [])

    def test_moving_adrs_never_breaks_a_copy_that_is_not_republished(self):
        a = self.linked_run(RUN_A)
        handoff.publish(a, ITEMS)
        a = self.switch(a, ("0001-pg",))
        res = handoff.publish(a, ["architecture"])  # the proposal copy still links to the old ADRs
        self.assertIn("2 old files kept: another published copy of this run links to them", res["published"][1])
        self.assertEqual(self.broken_links(), [])
        res = handoff.publish(a, ITEMS)
        self.assertIn("2 old files moved to _superseded", res["published"][1])
        self.assertEqual(sorted(os.listdir(self.docs("adr"))), [handoff.PUBLISHED_MARKER, "0001-pg.md"])
        self.assertEqual(self.broken_links(), [])

    def test_republishing_adr_alone_after_a_switch_keeps_the_files_other_copies_link_to(self):
        a = self.linked_run(RUN_A)
        handoff.publish(a, ITEMS)
        a = self.switch(a, ("0001-pg",))
        plan = handoff.plan_target(a, "adr", ["adr"])
        self.assertEqual((plan["stale"], plan["pinned"]), ([], ["0001-a.md", "0002-b.md"]))
        self.assertIn("2 files this run no longer has stay, because another published copy of this run links to them",
                      handoff.card_line(plan))
        handoff.publish(a, ["adr"])
        self.assertEqual(sorted(os.listdir(self.docs("adr"))),
                         [handoff.PUBLISHED_MARKER, "0001-a.md", "0001-pg.md", "0002-b.md"])
        self.assertEqual(self.broken_links(), [])
        handoff.publish(a, ITEMS)  # everything republished: the old ADRs go
        self.assertEqual(sorted(os.listdir(self.docs("adr"))), [handoff.PUBLISHED_MARKER, "0001-pg.md"])
        self.assertEqual(self.broken_links(), [])

    def test_architecture_alone_after_an_adr_rename_links_to_the_fresh_copy(self):
        a = self.linked_run(RUN_A)
        handoff.publish(a, ITEMS)
        a = self.switch(a, ("0001-a", "0002-renamed"))
        handoff.publish(a, ["architecture"])
        self.assertTrue(os.path.isfile(self.docs("adr", "0002-renamed.md")))
        self.assertTrue(os.path.isfile(self.docs("adr", "0002-b.md")))  # the proposal copy still links to it
        self.assertIn("../adr/0002-renamed.md", self.read("architecture", "README.md"))
        self.assertEqual(self.broken_links(), [])

    def test_an_old_copy_left_at_another_place_keeps_its_links(self):
        a = self.linked_run(RUN_A)
        handoff.publish(a, ITEMS)
        a = self.switch(a, ("0001-pg",))
        textio.write_text_atomic(self.docs("proposal", "my-notes.md"), "# mine\n")  # docs/proposal is not ours now
        res = handoff.publish(a, ITEMS)
        self.assertIn("11_PROPOSAL -> docs/%s/proposal" % RUN_A, res["published"][2])
        self.assertIn("2 old files kept", res["published"][1])  # docs/proposal still links to them
        self.assertEqual(self.broken_links(), [])

    def test_an_interrupted_publish_never_leaves_a_link_dangling_whatever_the_next_answer(self):
        a = self.answered(self.linked_run(RUN_A))
        handoff.publish(a, ITEMS)
        a = self.answered(self.switch(a, ("0001-pg",)), at="2026-09-25T11:00:00Z")
        real = handoff._copy_replace

        def fail_on_proposal(src, dst, data=None):
            if "proposal" in dst.replace("\\", "/"):
                raise PermissionError("locked")
            return real(src, dst, data)
        with mock.patch.object(handoff, "_copy_replace", side_effect=fail_on_proposal), \
                self.assertRaises(PermissionError):
            handoff.publish(a, ITEMS)
        self.assertEqual(self.broken_links(), [])  # nothing left before every copy pointed at the new ADRs
        handoff.publish(a, ["adr"])  # answered differently on the redo
        self.assertEqual(self.broken_links(), [])

    def test_zero_adrs_now_say_what_happens_to_the_old_adr_copy(self):
        a = self.linked_run(RUN_A)
        handoff.publish(a, ITEMS)
        shutil.rmtree(a.path("10_ARCHITECTURE", "adr"))
        self.assertIn("This run has no ADRs now: `adr` moves its old ADR copy in docs/adr to the backup",
                      gates.display(a, "G14"))
        self.assertEqual(len(handoff.publish(a, ["proposal"])["published"]), 1)  # the ADRs do not come along

    def test_the_adrs_do_not_come_along_when_the_copy_that_links_to_them_is_not_published(self):
        handoff.publish(self.linked_run(RUN_A), ITEMS)
        os.makedirs(self.docs(RUN_B, "proposal"))
        textio.write_text_atomic(self.docs(RUN_B, "proposal", "notes.md"), "# mine\n")
        b = self.linked_run(RUN_B)
        res = handoff.publish(b, ["proposal"])
        self.assertEqual(res["published"], [])
        self.assertFalse(os.path.exists(self.docs(RUN_B, "adr")))

    def test_a_case_only_adr_rename_is_never_kept_as_a_second_name(self):
        a = self.linked_run(RUN_A, adrs=("0001-A", "0002-b"))
        handoff.publish(a, ITEMS)
        a = self.switch(a, ("0001-a", "0002-b"))
        handoff.publish(a, ["proposal"])  # the architecture copy still links to 0001-A.md
        names = self.marker("adr")["files"]
        self.assertIn("0001-a.md", names)
        on_disk = sorted(f for f in os.listdir(self.docs("adr")) if f != handoff.PUBLISHED_MARKER)
        self.assertEqual(sorted(names), on_disk)
        a = self.switch(a, ("0003-c",))
        handoff.publish(a, ["adr", "proposal"])
        self.assertEqual(self.broken_links(), [])
        self.assertEqual(sorted(self.marker("adr")["files"]),
                         sorted(f for f in os.listdir(self.docs("adr")) if f != handoff.PUBLISHED_MARKER))

    def test_a_case_only_rename_interrupted_before_its_move_resumes_in_place(self):
        a = self.answered(self.linked_run(RUN_A))
        handoff.publish(a, ITEMS)
        a = self.answered(self.switch(a, ("0001-A", "0002-b")), at="2026-09-25T11:00:00Z")
        plan = handoff.plan_target(a, "adr", ["adr"])
        if not plan["renamed"]:
            self.skipTest("the disk is case-sensitive")
        with mock.patch.object(handoff.shutil, "move", side_effect=PermissionError("locked")), \
                self.assertRaises(PermissionError):
            handoff.publish(a, ["adr"])
        self.assertEqual(handoff.plan_target(a, "adr", ["adr"])["dst"], "docs/adr")  # still this run's folder
        handoff.publish(a, ["adr"])
        self.assertEqual(sorted(self.marker("adr")["files"]),
                         sorted(f for f in os.listdir(self.docs("adr")) if f != handoff.PUBLISHED_MARKER))
        self.assertEqual(self.broken_links(), [])

    def test_a_copy_made_while_docs_adr_was_a_link_is_retired_when_it_works_again(self):
        a = self.linked_run(RUN_A)
        handoff.publish(a, ["architecture", "adr"])
        with self.adr_folder_blocked():
            handoff.publish(a, ["adr", "proposal"])  # docs/<run>/adr; the proposal links there
        self.assertTrue(os.path.isfile(self.docs(RUN_A, "adr", "0001-a.md")))
        self.assertIn("This run's other copy in docs/%s/adr moves to the backup" % RUN_A,
                      handoff.card_line(handoff.plan_target(a, "adr", ["proposal"])))
        res = handoff.publish(a, ["proposal"])
        self.assertIn("this run's other copy in docs/%s/adr: 2 files moved to _superseded" % RUN_A, res["published"][0])
        self.assertFalse(os.path.exists(self.docs(RUN_A)))
        self.assertIn("[ADR-0001](../adr/0001-a.md)", self.read("proposal", "PROPOSAL.md"))
        self.assertEqual(self.broken_links(), [])

    def test_a_2_0_2_leftover_that_is_a_case_variant_of_a_new_adr_is_replaced_not_kept(self):
        a = self.linked_run(RUN_A)
        os.makedirs(self.docs("adr"))
        for f in ("0001-a.md", "0002-b.md"):
            textio.write_text_atomic(self.docs("adr", f), a.read("10_ARCHITECTURE/adr/" + f))
        textio.write_json_atomic(self.docs("adr", handoff.PUBLISHED_MARKER),
                                 {"run": RUN_A, "files": ["0001-a.md", "0002-b.md", "old.md"]})
        textio.write_text_atomic(self.docs("adr", "old.md"), "# old\n")  # makes the marker "mixed"
        a = self.switch(a, ("0001-A", "0002-b"))
        plan = handoff.plan_target(a, "adr", ["adr"])
        if not any(f.lower() == "0001-a.md" and f != "0001-A.md" for f in os.listdir(self.docs("adr"))) or \
                not os.path.exists(self.docs("adr", "0001-A.md")):
            self.skipTest("the disk is case-sensitive")
        self.assertNotIn("0001-a.md", plan["kept"])
        handoff.publish(a, ["adr"])
        self.assertNotIn("0001-a.md", self.marker("adr").get("legacy_files", []))

    def test_the_card_never_promises_an_adr_copy_that_is_not_there(self):
        a = self.linked_run(RUN_A)
        self.old_architecture_copy_with_adrs(a)
        shutil.rmtree(a.path("10_ARCHITECTURE", "adr"))  # zero ADRs now
        text = gates.display(a, "G14")
        self.assertIn("Its old copies of 2 ADRs (the architecture copy holds no ADRs now) move to the backup.", text)
        self.assertNotIn("live only in the adr copy", text)

    def test_the_adr_note_names_only_copies_that_can_be_published(self):
        handoff.publish(self.linked_run(RUN_A), ITEMS)
        for item in ("architecture", "proposal"):
            os.makedirs(self.docs(RUN_B, item))
            textio.write_text_atomic(self.docs(RUN_B, item, "notes.md"), "# mine\n")
        b = self.linked_run(RUN_B)
        text = gates.display(b, "G14")
        self.assertIn("ADRs are published once, to docs/%s/adr.\n" % RUN_B, text)
        self.assertNotIn("publish them there too", text)

    def test_a_link_at_docs_gives_one_reason(self):
        a = self.run_ctx(RUN_A, "a")
        os.makedirs(self.docs())
        real = handoff._is_link
        docs = os.path.normcase(self.docs())
        with mock.patch.object(handoff, "_is_link", side_effect=lambda q: os.path.normcase(q) == docs or real(q)):
            line = handoff.card_line(handoff.plan_target(a, "adr"))
        self.assertEqual(line.count("docs is a link or junction"), 1)

    def test_one_old_adr_copy_is_worded_in_the_singular(self):
        a = self.linked_run(RUN_A, adrs=("0001-a",))
        self.old_architecture_copy_with_adrs(a)
        self.assertIn("Its old copy of 1 ADR (ADRs live only in the adr copy now) moves to the backup.",
                      gates.display(a, "G14"))

    def test_reference_links_with_crlf_or_a_title_count_as_links(self):
        raw = b"See [x][d].\r\n[d]: ../adr/0002-b.md\r\n[e]: ../adr/0001-a.md \"ADR 1\"\n"
        found = set(m.group(3) for m in handoff._LINK_TARGET_RE.finditer(raw) if m.group(3))
        self.assertEqual(found, {b"../adr/0002-b.md", b"../adr/0001-a.md"})

    def test_relinking_keeps_encoding_bom_and_line_endings_and_catches_other_link_forms(self):
        a = self.linked_run(RUN_A)
        raw = ("\ufeff# Architecture\r\n| [ADR-0001](adr/0001-a.md) |\r\n[b](<./adr/0002-b.md>)\r\n"
               "[ref]: adr/0001-a.md\r\n<a href='adr/0002-b.md'>b</a>\r\nCaf\u00e9\r\n").encode("utf-8")
        with open(a.path("10_ARCHITECTURE", "README.md"), "wb") as fh:
            fh.write(raw)
        handoff.publish(a, ITEMS)
        with open(self.docs("architecture", "README.md"), "rb") as fh:
            out = fh.read()
        self.assertTrue(out.startswith(b"\xef\xbb\xbf"))
        self.assertEqual(out.count(b"\r\n"), 6)
        self.assertIn("Caf\u00e9".encode("utf-8"), out)
        for link in (b"](../adr/0001-a.md)", b"](<../adr/0002-b.md>)", b"[ref]: ../adr/0001-a.md",
                     b"href='../adr/0002-b.md'"):
            self.assertIn(link, out)

    def test_a_relinked_file_is_written_through_a_temp_file_and_resumes(self):
        a = self.answered(self.linked_run(RUN_A))
        real = handoff._copy_replace

        def fail_on_relinked(src, dst, data=None):
            if data is not None:
                raise PermissionError("locked")
            return real(src, dst, data)
        with mock.patch.object(handoff, "_copy_replace", side_effect=fail_on_relinked), \
                self.assertRaises(PermissionError):
            handoff.publish(a, ITEMS)
        handoff.publish(a, ITEMS)
        self.assertIn("| [ADR-0001](../adr/0001-a.md) |", self.read("architecture", "README.md"))
        self.assertFalse([f for r, _d, fs in os.walk(self.docs()) for f in fs if f.endswith(".tmp")])
        self.assertEqual(self.broken_links(), [])


class RecordTests(PublishCase):
    def test_handoff_records_where_each_copy_went_and_what_was_not_published(self):
        handoff.publish(self.run_ctx(RUN_A, "a"), ITEMS)
        os.makedirs(self.docs(RUN_B, "proposal"))
        textio.write_text_atomic(self.docs(RUN_B, "proposal", "notes.md"), "# mine\n")
        b = self.run_ctx(RUN_B, "b")
        b.state.setdefault("gates", {})["G14"] = {"answer": {"publish": ["adr", "proposal"], "handoff": "none"}}
        note = handoff.handoff_seed(b, {"id": "14.3"})
        self.assertEqual(b.state["published"], ["10_ARCHITECTURE/adr -> docs/%s/adr (docs/adr holds run %s)"
                                                % (RUN_B, RUN_A)])
        self.assertEqual(len(b.state["not_published"]), 1)
        self.assertIn("docs/%s/adr" % RUN_B, note)
        self.assertIn("; not published: 11_PROPOSAL (docs/proposal holds run", note)
        handoff.handoff_final(b, {"id": "14.4"})
        text = b.read("12_HANDOFF.md")
        self.assertIn("- Published: 10_ARCHITECTURE/adr -> docs/%s/adr (docs/adr holds run %s)\n" % (RUN_B, RUN_A),
                      text)
        self.assertIn("- Not published: 11_PROPOSAL (docs/proposal holds run %s; docs/%s/proposal holds files the kit "
                      "did not publish)\n" % (RUN_A, RUN_B), text)


if __name__ == "__main__":
    unittest.main()
