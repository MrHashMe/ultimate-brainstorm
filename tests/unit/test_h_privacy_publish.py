"""Phase H, publish (KIT_SPEC 8.5, 14.2): a claim on docs/<run>/ that appears after a run found none is judged, never
adopted, and a claim is created with its whole content in one step, so an interrupted publish never locks its run out
(finding 56); a page an older kit rendered (a floating mermaid import with no SRI, or any script in a run without web
access) is rendered again before the G14 card, a publish or an html export hands it out (finding 59)."""

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
from ublib.engine import handoff, render  # noqa: E402
from ublib.engine import state as st  # noqa: E402

RUN = "2026-09-27-h-publish"
ITEMS = ["architecture", "adr", "proposal"]
# what kit 2.0.3's step 13.7 left in a run: a floating mermaid@11 ESM import, no integrity, no CSP
OLD_PAGE = ('<!doctype html>\n<html><head><meta charset="utf-8"><title>Proposal</title></head><body>\n'
            '<pre class="mermaid">flowchart LR\n  A --> B</pre>\n<script type="module">\n'
            'const m = await import("https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.esm.min.mjs");\n'
            'm.default.initialize({startOnLoad: false, securityLevel: "strict"});\n</script>\n</body></html>\n')


def called_from(name):
    f = sys._getframe(2)
    while f is not None:
        if f.f_code.co_name == name:
            return True
        f = f.f_back
    return False


class PublishCase(tl.EngineTestCase):
    def run_in(self, root, text="a", privacy=None):
        """A run folder <project>/<root>/<RUN> with an architecture, an ADR and a proposal."""
        run_dir = os.path.join(self.project, root, RUN)
        os.makedirs(run_dir, exist_ok=True)
        st.ensure_run_dirs(run_dir)
        state = st.new_state(run_dir, "t", "claude-code", "claude", runner="python ub.py", project_dir=self.project)
        state["privacy"].update(privacy or {})
        ctx = st.Ctx(run_dir, state, tl.FakeDeps())
        ctx.write("10_ARCHITECTURE/README.md", "# Architecture %s\n" % text)
        ctx.write("10_ARCHITECTURE/adr/0001-use-postgres.md", "# ADR 0001 %s\n" % text)
        ctx.write("11_PROPOSAL/PROPOSAL.md", "# Proposal: %s\n\n## 1. Executive Summary\n%s\n" % (text, text))
        ctx.write("11_PROPOSAL/ONE-PAGER.md", "# One-pager\n\n## Problem\n%s\n" % text)
        return ctx

    def docs(self, *parts):
        return os.path.join(self.project, "docs", RUN, *parts)

    def published_texts(self):
        out = {}
        for dirpath, _dirs, files in os.walk(self.docs()):
            for f in files:
                if f != handoff.CLAIM:
                    full = os.path.join(dirpath, f)
                    out[os.path.relpath(full, self.docs()).replace("\\", "/")] = textio.read_text(full)
        return out


class ClaimRaceTests(PublishCase):
    def test_a_claim_that_appears_after_the_check_is_never_adopted(self):
        # finding 56: b found no claim; a claimed docs/<run>/ right then; b read a's claim as its own, adopted its id
        # and wrote into the folder (and kept doing so on every later publish)
        a = self.run_in("brainstorm", "alpha")
        b = self.run_in("elsewhere", "beta")
        claim = os.path.normcase(os.path.abspath(self.docs(handoff.CLAIM)))
        real_lexists = os.path.lexists
        fired = []

        def lexists(path):
            found = real_lexists(path)
            if (not fired and not found and os.path.normcase(os.path.abspath(path)) == claim
                    and called_from("_claim")):
                fired.append(path)
                handoff.publish(a, ITEMS)  # a claims (and fills) the folder right after b looked
            return found
        with mock.patch.object(handoff.os.path, "lexists", side_effect=lexists):
            res = handoff.publish(b, ITEMS)
        self.assertEqual(len(fired), 1)
        self.assertEqual(res["published"], [])
        self.assertEqual(len(res["not_published"]), 3)
        self.assertIn("belongs to the run at brainstorm/%s" % RUN, res["not_published"][0])
        texts = self.published_texts()
        self.assertTrue(texts and all("alpha" in t and "beta" not in t for t in texts.values()), texts)
        self.assertNotEqual(handoff._claim_id(b), handoff._claim_id(a))
        # later publishes stay apart too
        b.write("11_PROPOSAL/PROPOSAL.md", "# Proposal: beta v2\n")
        self.assertEqual(handoff.publish(b, ITEMS)["published"], [])
        self.assertTrue(all("beta" not in t for t in self.published_texts().values()))

    CHILD = "\n".join([
        "import os, sys, time",
        "sys.path.insert(0, sys.argv[1])",
        "import engine_testlib as tl",
        "from ublib.engine import handoff, state as st",
        "project, run_dir, ready = sys.argv[2:5]",
        "state = st.new_state(run_dir, 't', 'claude-code', 'claude', runner='python ub.py', project_dir=project)",
        "ctx = st.Ctx(run_dir, state, tl.FakeDeps())",
        "claim = os.path.join(project, 'docs', os.path.basename(run_dir), handoff.CLAIM)",
        "def held(real):",
        "    def call(*a, **k):",
        "        if os.path.lexists(claim):  # the first file call once the claim's name exists: killed here",
        "            open(ready, 'w').close()",
        "            while True:",
        "                time.sleep(0.05)",
        "        return real(*a, **k)",
        "    return call",
        "for name in ('write', 'fsync', 'close', 'unlink', 'replace', 'rename'):",
        "    setattr(os, name, held(getattr(os, name)))",
        "handoff.publish(ctx, ['architecture', 'adr', 'proposal'])",
    ])

    def test_a_publish_killed_while_it_claims_the_folder_does_not_lock_the_run_out(self):
        # finding 56: the claim was created empty (O_EXCL) and written after; a kill in between left a claim nobody
        # could read, and every later publish of the run was refused
        a = self.run_in("brainstorm")
        ready = os.path.join(self.tmp, "claimed.ready")
        proc = subprocess.Popen([sys.executable, "-c", self.CHILD, FIXTURES, self.project, a.run_dir, ready],
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
        claim = textio.read_json_or(self.docs(handoff.CLAIM))
        self.assertIsInstance(claim, dict)  # whole, or not there at all: never empty
        res = handoff.publish(self.run_in("brainstorm"), ITEMS)
        self.assertEqual(res["not_published"], [])
        self.assertEqual(len(res["published"]), 3)
        self.assertEqual(textio.read_text(self.docs("10_ARCHITECTURE", "README.md")), "# Architecture a\n")
        self.assertEqual([n for n in os.listdir(self.docs()) if n.endswith(".tmp")], [])  # the claim's temp is gone


class OldPageTests(PublishCase):
    def page(self, *parts):
        return textio.read_text(os.path.join(*parts))

    def test_a_page_an_older_kit_rendered_is_published_with_the_pinned_script(self):
        # finding 59: a 2.0.3 run continued with this kit published its floating, unchecked mermaid import
        a = self.run_in("brainstorm")
        a.write("11_PROPOSAL/index.html", OLD_PAGE)
        res = handoff.publish(a, ["proposal"])
        self.assertIn("11_PROPOSAL -> docs/%s/11_PROPOSAL" % RUN, res["published"])
        page = self.page(self.docs("11_PROPOSAL", "index.html"))
        self.assertNotIn("mermaid@11/", page)
        self.assertIn('integrity="%s"' % render.MERMAID_SRI, page)
        self.assertIn("Content-Security-Policy", page)
        self.assertEqual(page, a.read("11_PROPOSAL/index.html"))  # the run's page was rendered again, then copied
        self.assertTrue(render.page_is_current(a))
        a.write("11_PROPOSAL/index.html", OLD_PAGE)
        self.assertFalse(render.page_is_current(a))

    def test_a_private_run_publishes_a_page_without_any_script(self):
        a = self.run_in("brainstorm", privacy={"web": False, "vendors": False})
        a.write("11_PROPOSAL/index.html", OLD_PAGE)
        handoff.publish(a, ITEMS)
        page = self.page(self.docs("11_PROPOSAL", "index.html"))
        self.assertNotIn("<script", page.lower())
        self.assertNotIn("jsdelivr", page)
        self.assertIn("script-src 'none'", page)

    def test_the_g14_card_renders_it_again_before_the_user_opens_it(self):
        a = self.run_in("brainstorm", privacy={"web": False})
        a.write("11_PROPOSAL/index.html", OLD_PAGE)
        handoff.card_lines(a)
        self.assertNotIn("<script", a.read("11_PROPOSAL/index.html").lower())
        self.assertFalse(os.path.exists(self.docs()))  # the card writes nothing under docs/

    def test_an_html_export_renders_it_again(self):
        a = self.run_in("brainstorm")
        a.write("11_PROPOSAL/index.html", OLD_PAGE)
        out = render.export(a, "html")
        page = self.page(out["path"])
        self.assertIn('integrity="%s"' % render.MERMAID_SRI, page)
        self.assertNotIn("mermaid@11/", page)

    def test_a_current_page_and_a_page_without_a_script_are_left_alone(self):
        a = self.run_in("brainstorm")
        render.render_pack(a)
        current = a.read("11_PROPOSAL/index.html")
        self.assertFalse(render.refresh_page(a))
        self.assertEqual(a.read("11_PROPOSAL/index.html"), current)
        a.write("11_PROPOSAL/index.html", "<html><body>no script</body></html>\n")
        handoff.publish(a, ["proposal"])
        self.assertEqual(self.page(self.docs("11_PROPOSAL", "index.html")), "<html><body>no script</body></html>\n")
        # the adr item alone does not touch the proposal's page
        a.write("11_PROPOSAL/index.html", OLD_PAGE)
        handoff.publish(a, ["adr"])
        self.assertEqual(a.read("11_PROPOSAL/index.html"), OLD_PAGE)


if __name__ == "__main__":
    unittest.main()
