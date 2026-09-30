"""E2: the Codex backend's tool policy is an allowlist, and the argv switches off what widens a worker's surface
(findings 22 and 63; reviewer notes R-backends-0 and P3-backends-3; contract C7).

- `-c mcp_servers={}` is gone: Codex deep-merges -c overrides into config.toml, so the empty table changed nothing, and
  under the replace semantics the spec assumed it would have broken config loading together with the per-name
  overrides. Each server of the Codex home's config.toml is disabled by name (U-40).
- default-on features no worker needs are off on every call (U-42): connectors (apps), plugins, sub-agents
  (multi_agent), hooks, memories, browser and computer use, image generation; jobs without read also lose view_image.
- parse() accepts only the item types a job may produce; a sub-agent (collab_tool_call), a type it does not know or an
  item without a type makes the attempt refused (policy, exit 7). backends.<id>.allow_items admits a new harmless type
  but never a tool type.
- codex needs `exec --ephemeral` (0.100.0 and later): an older CLI is unavailable at detection, for the provider
  variants too.
Process calls are mocked at ublib.proc.run, except where a real child process streams its output.
"""

import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

_KIT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(_KIT, "tests", "fixtures", "adapter"))

import adapter_testlib as tl  # noqa: E402
from ublib import adapter, detect, families, textio  # noqa: E402
from ublib.backends import CallContext, codex_cli  # noqa: E402

ANSWER = "Final answer text from codex."
ALWAYS_OFF = ("apps", "plugins", "multi_agent", "hooks", "memories", "browser_use", "computer_use",
              "image_generation")


def transcript(*types, **kw):
    lines = [{"type": "thread.started", "thread_id": "t"}, {"type": "turn.started"}]
    for i, itype in enumerate(types):
        item = {"id": "item_%d" % i}
        if itype is not None:
            item["type"] = itype
        lines.append({"type": "item.completed", "item": item})
    lines.append({"type": "item.completed", "item": {"id": "last", "type": "agent_message", "text": ANSWER}})
    lines.append({"type": "turn.completed", "usage": {"input_tokens": 10, "output_tokens": 5}})
    return ("\n".join(json.dumps(x) for x in lines) + "\n").encode("utf-8")


def writes_last(stdout):
    def respond(call):
        argv = call["argv"]
        with open(argv[argv.index("-o") + 1], "w", encoding="utf-8") as f:
            f.write(ANSWER)
        return tl.PR(0, stdout)
    return respond


def pairs(argv):
    return [argv[i + 1] for i, a in enumerate(argv[:-1]) if a == "-c"]


class ArgvTests(tl.AdapterTestCase):
    def argv_for(self, tools, job_id=None, chain=("codex-cli",), family="gpt"):
        fake = tl.FakeRun([writes_last(transcript())])
        job = self.make_job(family=family, tools=tools, job_id=job_id or "a-" + tools.replace("+", "-"))
        det = tl.chain_detect({family: list(chain)}, host_family="claude")
        with mock.patch("ublib.proc.run", side_effect=fake), \
                mock.patch("ublib.proc.resolve_exe", side_effect=tl.fake_resolve()):
            meta = adapter.execute_job(job, detect_result=det)
        self.assertEqual(meta["status"], "ok", meta)
        return fake.calls[0]["argv"]

    def test_no_empty_mcp_table_but_each_named_server_is_disabled(self):
        textio.write_text_atomic(os.path.join(os.environ["CODEX_HOME"], "config.toml"),
                                 '[mcp_servers.node_repl]\ncommand = "node"\n[mcp_servers.docs]\nurl = "https://x"\n')
        c = pairs(self.argv_for("none"))
        self.assertNotIn("mcp_servers={}", c)
        self.assertEqual([x for x in c if x.startswith("mcp_servers")],
                         ["mcp_servers.docs.enabled=false", "mcp_servers.node_repl.enabled=false"])
        self.assertIn("notify=[]", c)

    def test_default_on_features_are_off_on_every_job(self):
        for tools in ("none", "read", "web", "read+web"):
            c = pairs(self.argv_for(tools))
            for feature in ALWAYS_OFF:
                self.assertIn("features.%s=false" % feature, c, tools)
            no_read = "read" not in tools
            for feature in ("shell_tool", "js_repl", "view_image"):
                self.assertEqual("features.%s=false" % feature in c, no_read, (tools, feature))

    def test_provider_variants_get_the_same_switches(self):
        os.environ["ZAI_API_KEY"] = "zai-test-token-abcdef0123456789"
        os.makedirs(os.path.join(self.home, "codex-homes", "glm"))
        c = pairs(self.argv_for("none", job_id="g1", chain=("codex-cli@glm",), family="glm"))
        for feature in ALWAYS_OFF:
            self.assertIn("features.%s=false" % feature, c)

    def test_disable_features_key_turns_the_switches_off(self):
        self.write_families_override({"backends": {"codex-cli": {"disable_features": False}}})
        c = pairs(self.argv_for("none"))
        self.assertFalse([x for x in c if x.split("=")[0] in ["features.%s" % f for f in ALWAYS_OFF]], c)
        self.assertIn("features.shell_tool=false", c, "disable_shell is a key of its own")

    def test_default_config_pins_the_ephemeral_codex(self):
        cfg = families.load_families()
        for bid in ("codex-cli", "codex-cli@glm", "codex-cli@kimi"):
            self.assertEqual(cfg["backends"][bid].get("min_version"), "0.100.0", bid)
            self.assertIs(cfg["backends"][bid].get("disable_features"), True, bid)


class AllowlistTests(unittest.TestCase):
    """codex_cli.parse() alone."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ub-e2-codex-")
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def parse(self, tools, stdout, bcfg=None):
        last = os.path.join(self.tmp, "last.txt")
        textio.write_text_atomic(last, ANSWER)
        ctx = CallContext(bcfg=dict({"web": True}, **(bcfg or {})), btype="codex-cli", backend_id="codex-cli",
                          timeout_s=5, tools=tools)
        return codex_cli.parse(tl.PR(0, stdout), ctx, "codex exec", last), last

    def assert_refused(self, r, last, *words):
        self.assertEqual((r["status"], r["error_class"], r["text"], r["retryable"]), ("refused", "policy", None, False))
        self.assertFalse(os.path.exists(last), "the -o file is discarded")
        for w in words:
            self.assertIn(w, r["error"])

    def test_a_sub_agent_is_refused_on_every_job(self):
        for tools in ("none", "read", "web", "read+web"):
            r, last = self.parse(tools, transcript("collab_tool_call"))
            self.assert_refused(r, last, "collab_tool_call")

    def test_an_unknown_item_type_is_refused_with_the_way_out(self):
        r, last = self.parse("none", transcript("reasoning", "image_view"))
        self.assert_refused(r, last, "image_view", "allow_items")
        r, _last = self.parse("none", transcript("reasoning", "image_view"), {"allow_items": ["image_view"]})
        self.assertEqual((r["status"], r["text"]), ("ok", ANSWER))

    def test_allow_items_never_admits_a_tool(self):
        for itype in ("mcp_tool_call", "command_execution", "file_change", "collab_tool_call"):
            r, last = self.parse("none", transcript(itype), {"allow_items": [itype]})
            self.assert_refused(r, last, itype)

    def test_an_item_without_a_type_is_refused(self):
        r, last = self.parse("none", transcript(None))
        self.assert_refused(r, last)

    def test_the_known_harmless_items_pass(self):
        r, _last = self.parse("none", transcript("reasoning", "todo_list", "error", "agent_message"))
        self.assertEqual((r["status"], r["text"]), ("ok", ANSWER))


class DetectVersionTests(tl.AdapterTestCase):
    def detect_with(self, version):
        def run(argv, cwd=None, env=None, stdin_bytes=None, timeout_s=None, **_kw):
            return tl.PR(0, "codex-cli %s\n" % version)
        os.environ["ZAI_API_KEY"] = "zai-test-token-abcdef0123456789"
        os.makedirs(os.path.join(self.home, "codex-homes", "glm"), exist_ok=True)
        with mock.patch("ublib.proc.resolve_exe", side_effect=tl.fake_resolve()), \
                mock.patch("ublib.proc.run", side_effect=run):
            return detect.detect(only=["gpt", "glm"])

    def test_a_server_no_override_can_reach_is_reported(self):
        textio.write_text_atomic(os.path.join(os.environ["CODEX_HOME"], "config.toml"),
                                 '[mcp_servers."team.docs"]\ncommand = "x"\n[mcp_servers.ok_name]\ncommand = "y"\n')
        notes = [n for n in self.detect_with("0.156.1")["families"]["gpt"]["notes"]
                 if n.startswith(detect.USER_CONTEXT_NOTE)]
        self.assertTrue([n for n in notes if "team.docs" in n and "ok_name" not in n], notes)

    def test_a_codex_without_exec_ephemeral_is_unavailable(self):
        res = self.detect_with("0.99.0")
        self.assertNotIn("codex-cli", res["families"]["gpt"]["chain"])
        self.assertNotIn("codex-cli@glm", res["families"]["glm"]["chain"])
        self.assertIn("codex older than 0.100.0", " ".join(res["families"]["gpt"]["notes"]))
        res = self.detect_with("0.156.1")
        self.assertIn("codex-cli", res["families"]["gpt"]["chain"])
        self.assertIn("codex-cli@glm", res["families"]["glm"]["chain"])


if __name__ == "__main__":
    unittest.main()
