"""Phase J, the publish claim (KIT_SPEC 14.2): on a disk without hard links (exFAT, FAT32, some network shares) the
claim is still created whole in one step on Windows (a rename that never replaces a name), and an empty claim, which
an interrupted O_EXCL claim leaves (a POSIX disk without hard links, or kit 2.1 before its hard-linked claim), no
longer locks its own run out of publishing: the run whose record holds the claim's id takes it over once it is older
than the grace period, and a run that lost the claim never does (review: an interrupted claim on a disk without hard
links, or an empty claim, still locks the run out of publishing)."""

import os
import subprocess
import sys
import time
import unittest
from unittest import mock

FIXTURES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fixtures", "engine")
sys.path.insert(0, FIXTURES)
import engine_testlib as tl  # noqa: E402

from ublib import textio  # noqa: E402
from ublib.engine import handoff  # noqa: E402
from ublib.engine import state as st  # noqa: E402

RUN = "2026-09-27-j-claim"
ITEMS = ["architecture", "adr", "proposal"]
NO_LINKS = OSError(22, "Incorrect function", None, 1)  # what os.link raises on exFAT (CreateHardLinkW)

# a publish on a disk without hard links, killed at its first file call once the claim's name exists
CHILD = "\n".join([
    "import os, sys, time",
    "sys.path.insert(0, sys.argv[1])",
    "import engine_testlib as tl",
    "from ublib.engine import handoff, state as st",
    "project, run_dir, ready = sys.argv[2:5]",
    "state = st.new_state(run_dir, 't', 'claude-code', 'claude', runner='python ub.py', project_dir=project)",
    "ctx = st.Ctx(run_dir, state, tl.FakeDeps())",
    "claim = os.path.join(project, 'docs', os.path.basename(run_dir), handoff.CLAIM)",
    "def no_links(*a, **k):",
    "    raise OSError(22, 'Incorrect function', None, 1)",
    "def held(real):",
    "    def call(*a, **k):",
    "        if os.path.lexists(claim):  # the first file call once the claim's name exists: killed here",
    "            open(ready, 'w').close()",
    "            while True:",
    "                time.sleep(0.05)",
    "        return real(*a, **k)",
    "    return call",
    "os.link = no_links",
    "for name in ('write', 'fsync', 'close', 'unlink', 'replace', 'rename'):",
    "    setattr(os, name, held(getattr(os, name)))",
    "handoff.publish(ctx, ['architecture', 'adr', 'proposal'])",
])


def called_from(name):
    f = sys._getframe(2)
    while f is not None:
        if f.f_code.co_name == name:
            return True
        f = f.f_back
    return False


class ClaimCase(tl.EngineTestCase):
    def run_in(self, root, text="a"):
        run_dir = os.path.join(self.project, root, RUN)
        os.makedirs(run_dir, exist_ok=True)
        st.ensure_run_dirs(run_dir)
        state = st.new_state(run_dir, "t", "claude-code", "claude", runner="python ub.py", project_dir=self.project)
        ctx = st.Ctx(run_dir, state, tl.FakeDeps())
        ctx.write("10_ARCHITECTURE/README.md", "# Architecture %s\n" % text)
        ctx.write("10_ARCHITECTURE/adr/0001-use-postgres.md", "# ADR 0001 %s\n" % text)
        ctx.write("11_PROPOSAL/PROPOSAL.md", "# Proposal: %s\n\n## 1. Executive Summary\n%s\n" % (text, text))
        return ctx

    def claim(self):
        return os.path.join(self.project, "docs", RUN, handoff.CLAIM)

    def age(self, path, seconds):
        then = time.time() - seconds
        os.utime(path, (then, then))

    def empty_claim_left_by(self, ctx):
        """The state an interrupted O_EXCL claim leaves: the record holds the claim id, the claim is empty."""
        cid = "0123456789abcdef0123456789abcdef"
        ctx.write_json(handoff.PUBLISH_RECORD, {"schema": 1, "docs": "docs/%s" % RUN, "files": [], "claim": cid})
        os.makedirs(os.path.dirname(self.claim()), exist_ok=True)
        open(self.claim(), "wb").close()
        return cid


class NoHardLinkTests(ClaimCase):
    def test_a_claim_without_hard_links_is_created_whole(self):
        a = self.run_in("brainstorm")
        with mock.patch.object(handoff.os, "link", side_effect=NO_LINKS):
            res = handoff.publish(a, ITEMS)
        self.assertEqual(len(res["published"]), 3)
        claim = textio.read_json_or(self.claim())
        self.assertEqual(claim["id"], handoff._claim_id(a))
        self.assertEqual([n for n in os.listdir(os.path.dirname(self.claim())) if n.endswith(".tmp")], [])
        # a second run of the same name (another run root) is refused, also without hard links
        b = self.run_in("elsewhere", "b")
        with mock.patch.object(handoff.os, "link", side_effect=NO_LINKS):
            res = handoff.publish(b, ITEMS)
        self.assertEqual(res["published"], [])
        self.assertIsNone(handoff._claim_id(b))  # the loser keeps no claim id

    def test_a_publish_killed_while_it_claims_without_hard_links_does_not_lock_the_run_out(self):
        a = self.run_in("brainstorm")
        ready = os.path.join(self.tmp, "claimed.ready")
        proc = subprocess.Popen([sys.executable, "-c", CHILD, FIXTURES, self.project, a.run_dir, ready],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            deadline = time.time() + 120
            while not os.path.exists(ready):
                if proc.poll() is not None or time.time() > deadline:
                    _out, err = proc.communicate()
                    self.fail("the child did not reach its claim: %s" % err.decode("utf-8", "replace"))
                time.sleep(0.01)
        finally:
            proc.kill()
            proc.communicate()
        if os.name == "nt":
            self.assertIsInstance(textio.read_json_or(self.claim()), dict)  # renamed into place: whole
        else:
            self.assertEqual(os.path.getsize(self.claim()), 0)  # O_EXCL, killed before its write
            self.age(self.claim(), handoff.EMPTY_CLAIM_GRACE_S + 5)
        res = handoff.publish(self.run_in("brainstorm"), ITEMS)
        self.assertEqual(res["not_published"], [])
        self.assertEqual(len(res["published"]), 3)
        self.assertEqual(textio.read_json_or(self.claim())["id"], handoff._claim_id(a))


class EmptyClaimTests(ClaimCase):
    def test_the_run_that_left_an_empty_claim_takes_it_over(self):
        a = self.run_in("brainstorm")
        cid = self.empty_claim_left_by(a)
        res = handoff.publish(a, ITEMS)  # too young: another run may be writing it
        self.assertEqual(res["published"], [])
        self.assertIn("is empty", res["not_published"][0])
        self.age(self.claim(), handoff.EMPTY_CLAIM_GRACE_S + 5)
        res = handoff.publish(a, ITEMS)
        self.assertEqual(res["not_published"], [])
        self.assertEqual(len(res["published"]), 3)
        self.assertEqual(textio.read_json_or(self.claim())["id"], cid)
        self.assertEqual(handoff._claim_id(a), cid)

    def test_a_run_that_loses_the_claim_never_takes_over_the_empty_one(self):
        # b finds no claim; a's O_EXCL claim appears (and is interrupted) right then: b's create fails, and b must not
        # keep the claim id it saved first, or it would qualify to take a's empty claim over later
        a = self.run_in("brainstorm")
        b = self.run_in("elsewhere", "b")
        claim = os.path.normcase(os.path.abspath(self.claim()))
        real_lexists = os.path.lexists
        fired = []

        def lexists(path):
            found = real_lexists(path)
            if not fired and not found and os.path.normcase(os.path.abspath(path)) == claim and called_from("_claim"):
                fired.append(path)
                self.empty_claim_left_by(a)
            return found
        with mock.patch.object(handoff.os.path, "lexists", side_effect=lexists):
            res = handoff.publish(b, ITEMS)
        self.assertEqual(len(fired), 1)
        self.assertEqual(res["published"], [])
        self.assertIsNone(handoff._claim_id(b))
        self.age(self.claim(), handoff.EMPTY_CLAIM_GRACE_S + 5)
        res = handoff.publish(b, ITEMS)
        self.assertEqual(res["published"], [])
        self.assertIn("delete that file", res["not_published"][0])
        self.assertEqual(os.path.getsize(self.claim()), 0)
        self.assertEqual(len(handoff.publish(a, ITEMS)["published"]), 3)
        self.assertTrue(all(t.startswith("# ") and " b\n" not in t for t in self.texts()))

    def texts(self):
        out = []
        for dirpath, _dirs, files in os.walk(os.path.dirname(self.claim())):
            out += [textio.read_text(os.path.join(dirpath, f)) for f in files if f != handoff.CLAIM]
        return out


if __name__ == "__main__":
    unittest.main()
