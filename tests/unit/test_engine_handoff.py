"""B3 engine: Stage 14 publish (KIT_SPEC 9, 14.2). The first run publishes into docs/architecture, docs/adr and
docs/proposal; a later run whose targets hold another run's package (or the project's own files) publishes into
docs/<run>/<item> and never touches what is there; the G14 card names the real target and the other run. A run's own
earlier copy is updated in place, an interrupted publish resumes in place, and links are never written through."""

import os
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
        self.assertEqual(res, {"published": ["10_ARCHITECTURE -> docs/architecture", "10_ARCHITECTURE/adr -> docs/adr",
                                             "11_PROPOSAL -> docs/proposal"], "not_published": []})
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
            "10_ARCHITECTURE -> docs/%s/architecture (docs/architecture holds run %s)" % (RUN_B, RUN_A),
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
        self.assertEqual(handoff.publish(b, ["architecture"])["published"],
                         ["10_ARCHITECTURE -> docs/%s/architecture" % RUN_B])
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

    def test_a_mocked_link_target_is_refused(self):
        os.makedirs(self.docs("adr"))
        a = self.run_ctx(RUN_A, "a")
        real = handoff._is_link
        with mock.patch.object(handoff, "_is_link", side_effect=lambda p: p.endswith("adr") or real(p)):
            self.assertEqual(handoff.publish(a, ["adr"])["not_published"],
                             ["10_ARCHITECTURE/adr (docs/adr is a link or junction)"])
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
        self.assertEqual(plan["dst"], None)
        self.assertIn("docs/architecture/adr is a link or junction", plan["why"])
        handoff.publish(a, ["architecture"])
        self.assertEqual(textio.read_text(self.docs("adr", "0001-ours.md")), "# ours\n")

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
        self.assertEqual(res["published"], ["10_ARCHITECTURE -> docs/architecture"])
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
        self.assertEqual(sorted(os.listdir(self.docs("architecture"))), [handoff.PUBLISHED_MARKER, "README.md", "adr"])
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
            self.assertEqual(len(handoff.publish(a, ["architecture", "architecture"])["published"]), 1)
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

        def fail_on_proposal(src, dst):
            if "proposal" in dst.replace("\\", "/"):
                raise PermissionError("locked")
            return real(src, dst)
        with mock.patch.object(handoff, "_copy_replace", side_effect=fail_on_proposal), \
                self.assertRaises(PermissionError):
            handoff.publish(a, ITEMS)
        res = handoff.publish(a, ITEMS)
        self.assertEqual(res["published"][0], "10_ARCHITECTURE -> docs/architecture (1 old file moved to _superseded)")
        self.assertEqual(textio.read_text(self.docs("proposal", "PROPOSAL.md")), "# changed\n")
        # a new G14 answer starts a new record
        self.answered(a, at="2026-09-25T11:00:00Z")
        self.assertEqual(handoff.publish(a, ITEMS)["published"][0], "10_ARCHITECTURE -> docs/architecture")

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

        def fail_on_zz(src, dst):
            if dst.endswith("zz.md"):
                raise PermissionError("locked")
            return real(src, dst)
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
