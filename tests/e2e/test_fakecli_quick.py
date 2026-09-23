"""E8 fake-CLI quick run (KIT_SPEC 11.6, 5.2, 4.18). Owner: B4 (written at integration).

Quick mode, full-auto, with the REAL backends (claude-cli, codex-cli, kimi-cli) against the fake executables on PATH
(`.cmd` shims on Windows) -> DONE. Then an argv audit of UB_FAKE_LOG: no prompt text in any argv, and the required
flags of 5.2 are present on every model call.
"""

import json
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "harness"))
import e2elib  # noqa: E402
import paths  # noqa: E402
from tmphome import TmpHome  # noqa: E402

TOPIC_WORDS = (e2elib.TOPIC, "for nurses")  # the run slug (in paths) uses hyphens, the prompt text spaces


def _model_call(entry):
    argv = entry.get("argv") or []
    tool = entry.get("tool")
    if tool == "claude":
        return "-p" in argv
    if tool == "codex":
        return "exec" in argv
    if tool == "kimi":
        return "-p" in argv or "--prompt" in argv
    return False


class FakeCliQuick(unittest.TestCase):

    def setUp(self):
        paths.require(paths.UB_PY, paths.FAMILY_PY, paths.FAMILIES_DEFAULT, owner="B2/B3")

    def test_quick_with_real_backends(self):
        with TmpHome(tools=("claude", "codex", "kimi")) as th:
            th.kimi_login()
            env = dict(th.env)
            env["UB_NO_DETACH"] = "0"
            for k in ("UB_FAKE_FAMILIES", "UB_FAKE_HOST_BACKEND", "UB_FAKE_DISABLE"):
                env.pop(k, None)
            proc = e2elib.ub(["run", "--text", e2elib.TOPIC, "--mode", "quick", "--autopilot", "full-auto",
                              "--root", th.project], env, th.project)
            run = e2elib.the_run(self, th.project)
            e2elib.assert_done(self, proc, run)
            rj = e2elib.run_json(run)
            backends = set(f.get("backend") for f in rj["families"].values() if f.get("status") == "ok")
            self.assertTrue({"claude-cli", "codex-cli", "kimi-cli"} & backends, rj["families"])
            self.assertNotIn("stub", backends, "the stub backend must not be used without UB_FAKE_FAMILIES")

            entries = th.fake_calls()
            model = [e for e in entries if _model_call(e)]
            self.assertTrue(model, "no model call reached a fake CLI")
            used = set(e["tool"] for e in model)
            self.assertTrue(len(used) >= 2, "only %s answered model calls" % sorted(used))
            ok = [c for c in e2elib.ok_calls(run) if c.get("backend") != "host"]
            self.assertTrue(ok)

            for e in model:
                argv = [str(a) for a in e.get("argv") or []]
                joined = " ".join(argv)
                for w in TOPIC_WORDS:
                    self.assertNotIn(w, joined, "prompt text in %s argv: %s" % (e["tool"], argv))
                self.assertNotIn("Do not load or invoke any skill", joined)
                if e["tool"] == "claude":
                    for flag in ("-p", "--output-format", "--no-session-persistence", "--strict-mcp-config",
                                 "--disallowedTools"):
                        self.assertIn(flag, argv, "claude argv lacks %s: %s" % (flag, argv))
                    self.assertNotIn("--bare", argv)
                elif e["tool"] == "codex":
                    for flag in ("exec", "--skip-git-repo-check", "--ephemeral", "-s", "-C", "-o", "--json"):
                        self.assertIn(flag, argv, "codex argv lacks %s: %s" % (flag, argv))
                    self.assertEqual(argv[-1], "-")
                elif e["tool"] == "kimi":
                    for flag in ("--agent-file", "--output-format"):
                        self.assertIn(flag, argv, "kimi argv lacks %s: %s" % (flag, argv))
                    for bad in ("--yolo", "--auto", "--plan"):
                        self.assertNotIn(bad, argv)
            # secrets never reach the log
            log = th.log_text()
            for c in e2elib.calls(run):
                self.assertNotIn("sk-", json.dumps(c.get("cmd", "")))
            self.assertNotIn("ANTHROPIC_API_KEY=", log)


if __name__ == "__main__":
    unittest.main()
