"""H: backend follow-ups of the round-3 review (NEW-G3-backends-1, -3 and the worker-backends reviewer claims).

- Codex 0.158+ retries an unreachable endpoint until the attempt's timeout: every job now switches
  features.unbounded_connection_retries off, so the attempt fails and the chain falls back.
- Without tomllib (Python 3.9/3.10, or a config.toml tomllib rejects) the regex reading missed MCP servers defined as
  inline tables or dotted keys (they started on every worker call and detect did not name them), read a table header
  inside a multi-line string as a server (a name Codex does not define breaks every call) and cut `[mcp_servers."a#b"]`
  at the '#'. The subset reader reads the TOML structure; a statement it cannot read switches no server off and is
  reported.
- A settings.json whose "env" is not an object made every native claude-cli call fail before the CLI started; such
  an env is no longer carried into the call's settings file.
No real CLI and no network: the CLI is mocked at ublib.proc.run."""

import json
import os
import sys
import unittest
from unittest import mock

_KIT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(_KIT, "tests", "fixtures", "adapter"))

import adapter_testlib as tl  # noqa: E402
from ublib import adapter, detect, textio  # noqa: E402

ANSWER = "Final answer text from codex."
NO_TOMLLIB = {"tomllib": None}  # what Python 3.9 / 3.10 see


def codex_ok(call):
    argv = call["argv"]
    with open(argv[argv.index("-o") + 1], "w", encoding="utf-8") as f:
        f.write(ANSWER)
    return tl.PR(0, json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": ANSWER}}) + "\n")


def overrides(argv):
    return [argv[i + 1] for i, a in enumerate(argv[:-1]) if a == "-c"]


class CodexArgvTests(tl.AdapterTestCase):
    def codex_argv(self, config=None):
        if config is not None:
            textio.write_text_atomic(os.path.join(os.environ["CODEX_HOME"], "config.toml"), config)
        fake = tl.FakeRun([codex_ok])
        with mock.patch("ublib.proc.run", side_effect=fake), \
                mock.patch("ublib.proc.resolve_exe", side_effect=tl.fake_resolve()):
            meta = adapter.execute_job(self.make_job(family="gpt"),
                                       detect_result=tl.chain_detect({"gpt": ["codex-cli"]}, "claude"))
        self.assertEqual(meta["status"], "ok", meta)
        return overrides(fake.calls[0]["argv"])

    def test_endless_reconnects_are_off_on_every_job(self):
        self.assertIn("features.unbounded_connection_retries=false", self.codex_argv())

    def test_disable_features_also_keeps_the_reconnect_switch_off_the_argv(self):
        self.write_families_override({"backends": {"codex-cli": {"disable_features": False}}})
        self.assertNotIn("features.unbounded_connection_retries=false", self.codex_argv())

    def test_an_inline_table_server_is_switched_off_without_tomllib(self):
        config = '[mcp_servers]\nalpha = { command = "npx", args = ["-y", "alpha-mcp"] }\n'
        with mock.patch.dict(sys.modules, NO_TOMLLIB):
            c = self.codex_argv(config)
        self.assertIn("mcp_servers.alpha.enabled=false", c)


class TomlSubsetTests(tl.AdapterTestCase):
    """Each config is read with tomllib (when this Python has it) and without: both must give the same names."""

    CASES = [
        ("table", '[mcp_servers.alpha]\ncommand = "npx"\nargs = ["-y", "alpha-mcp"]\n', ["alpha"], []),
        ("inline in the table", '[mcp_servers]\nalpha = { command = "npx", args = ["-y", "alpha-mcp"] }\n',
         ["alpha"], []),
        ("dotted keys", 'mcp_servers.alpha.command = "npx"\nmcp_servers.alpha.args = ["-y", "alpha-mcp"]\n',
         ["alpha"], []),
        ("dotted keys in the table", '[mcp_servers]\nalpha.command = "npx"\nalpha.args = ["-y"]\n', ["alpha"], []),
        ("one inline table", 'mcp_servers = { alpha = { command = "x" }, "b-2" = { url = "https://x" } }\n',
         ["alpha", "b-2"], []),
        ("a header inside multi-line strings",
         'developer_instructions = """\nUse this:\n[mcp_servers.fake]\nfake.command = "x"\n"""\n'
         "note = '''\n[mcp_servers.fake2]\n'''\n[mcp_servers.foo]\ncommand = \"x\"\n", ["foo"], []),
        ("a multi-line array", '[mcp_servers.foo]\nargs = [\n  "-y",\n  ["nested"]\n]\nenv = { A = "1" }\n'
         '[mcp_servers.bar]\ncommand = "y"\n', ["bar", "foo"], []),
        ("quoted names", '[mcp_servers."a#b"]\ncommand = "x"\n[mcp_servers."team.docs"]\ncommand = "y"\n'
         '[mcp_servers."ok"]\ncommand = "z"\n', ["ok"], ["a#b", "team.docs"]),
        ("comments", '# [mcp_servers.old]\n[mcp_servers.foo] # the docs server\nurl = "https://x/#frag"  # c\n',
         ["foo"], []),
        ("other tables", 'model = "gpt-5.5"\n[profiles.p.mcp_servers.bar]\ncommand = "x"\n[[skills]]\nname = "s"\n'
         '[mcp_servers.foo.env]\nX = "1"\n', ["foo"], []),
    ]

    def names(self, text):
        textio.write_text_atomic(os.path.join(self.tmp, "config.toml"), text)
        return detect.codex_mcp_servers(self.tmp), detect.codex_mcp_servers(self.tmp, unsafe=True)

    def test_every_form_of_mcp_server_is_read_without_tomllib(self):
        for label, text, safe, unsafe in self.CASES:
            with mock.patch.dict(sys.modules, NO_TOMLLIB):
                self.assertEqual(self.names(text), (safe, unsafe), label)

    def test_the_subset_reading_agrees_with_tomllib(self):
        try:
            import tomllib  # noqa: F401
        except ImportError:
            self.skipTest("Python 3.11+")
        for label, text, _safe, _unsafe in self.CASES:
            with_tomllib = detect._parse_toml(text)
            with mock.patch.dict(sys.modules, NO_TOMLLIB):
                without = detect._parse_toml(text)
            self.assertEqual(sorted(without.get("mcp_servers", {})), sorted(with_tomllib.get("mcp_servers", {})),
                             label)
        text = 'x = "a \\"quoted\\" \\u00e9"\ny = \'lit\\n\'\n[t]\n"k.1" = """\nline"""\n'
        with mock.patch.dict(sys.modules, NO_TOMLLIB):
            self.assertEqual(detect._parse_toml(text), tomllib.loads(text))

    def test_providers_and_profiles_still_read_without_tomllib(self):
        text = ('profile = "k"\n[profiles.k]\nmodel_provider = "moonshot"  # the provider\n'
                '[model_providers.moonshot]\nbase_url = "https://api.moonshot.ai/v1"\nenv_key = "MOONSHOT_API_KEY"\n'
                'query_params = { "api-version" = "2025-04-01" }\nstream_max_retries = 3\n')
        with mock.patch.dict(sys.modules, NO_TOMLLIB):
            data = detect._parse_toml(text)
        self.assertEqual(data["profiles"]["k"]["model_provider"], "moonshot")
        self.assertEqual(data["model_providers"]["moonshot"]["base_url"], "https://api.moonshot.ai/v1")
        self.assertEqual(data["model_providers"]["moonshot"]["query_params"], {"api-version": "2025-04-01"})

    def test_an_unreadable_statement_switches_no_server_off_and_is_listed(self):
        text = '[mcp_servers.foo]\ncommand = "x\n[mcp_servers.bar]\ncommand = "y"\n'  # line 2: no closing quote
        with mock.patch.dict(sys.modules, NO_TOMLLIB):
            self.assertEqual(self.names(text), ([], []))
            self.assertEqual(detect.codex_mcp_unread(self.tmp), [2])
        self.assertEqual(self.names(text), ([], []), "tomllib rejects the file: the same subset reading")
        self.assertEqual(detect.codex_mcp_unread(self.tmp), [2])

    def test_a_broken_statement_does_not_swallow_the_rest(self):
        text = 'a = [1, 2\n[mcp_servers.foo]\ncommand = "x"\n'  # an unclosed array: Codex rejects this file
        with mock.patch.dict(sys.modules, NO_TOMLLIB):
            unread = []
            detect._parse_toml(text, unread)
        self.assertEqual(unread, [1])

    def test_the_subset_reading_is_linear(self):
        text = "".join('[mcp_servers.s%d]\ncommand = "x"\nargs = ["a", "b"]\n' % i for i in range(20000))
        text += 'x = "' + "\\\\" * 50000 + '\n' + "[" * 50000 + "\n" + '"""' + '"' * 50000 + "\n"
        with mock.patch.dict(sys.modules, NO_TOMLLIB):
            unread = []
            data = detect._parse_toml(text, unread)
        self.assertEqual(len(data["mcp_servers"]), 20000)
        self.assertTrue(unread)


class CodexMcpDocsTests(unittest.TestCase):
    """NEW-G3-backends-4: the user docs no longer claim that every Codex MCP server is kept out of worker calls."""

    def doc(self, *parts):
        return " ".join(textio.read_text(os.path.join(_KIT, *parts)).split())

    def test_privacy_and_families_name_the_servers_that_still_start(self):
        privacy, families = self.doc("docs", "PRIVACY.md"), self.doc("docs", "FAMILIES.md")
        self.assertNotIn("your Codex MCP servers, hooks, memories and notify program, are kept out", privacy)
        self.assertIn("the MCP servers named in your `~/.codex/config.toml`, are kept out of these calls", privacy)
        self.assertIn("or one from a system or project Codex config, still starts, and so does every server of that "
                      "config.toml when the kit cannot read part of the file without Python 3.11+", privacy)
        self.assertIn("any call to such a server is refused", privacy)
        self.assertNotIn("Codex's own shell, your MCP servers,", families)
        self.assertIn("the MCP servers in your `~/.codex/config.toml` (except names with a character", families)


class ClaudeEnvNotAnObjectTests(tl.AdapterTestCase):
    """A settings.json whose "env" is a string or a list: the native call runs (it failed with 'backend error:
    AttributeError' before any process started, and every attempt still counted a request)."""

    def settings(self, data):
        d = os.environ["CLAUDE_CONFIG_DIR"]
        os.makedirs(d, exist_ok=True)
        textio.write_json_atomic(os.path.join(d, "settings.json"), data)

    def test_a_non_object_env_is_not_carried(self):
        success = tl.fixture_bytes("claude", "success.json")
        for env in ("HTTPS_PROXY=http://proxy:3128", ["HTTPS_PROXY=http://proxy:3128"]):
            self.settings({"env": env, "apiKeyHelper": "/usr/local/bin/get-key"})
            seen = []

            def respond(call):
                argv = call["argv"]
                seen.append(textio.read_json(argv[argv.index("--settings") + 1]) if "--settings" in argv else None)
                return tl.PR(0, success)
            fake = tl.FakeRun([respond])
            with mock.patch("ublib.proc.run", side_effect=fake), \
                    mock.patch("ublib.proc.resolve_exe", side_effect=tl.fake_resolve()):
                meta = adapter.execute_job(self.make_job(family="claude", job_id="env-%s" % type(env).__name__),
                                           detect_result=tl.chain_detect({"claude": ["claude-cli"]}, "claude"))
            self.assertEqual((meta["status"], meta["requests"]), ("ok", 1), meta["reason"])
            self.assertEqual(seen, [{"apiKeyHelper": "/usr/local/bin/get-key"}], env)
            self.assertEqual(detect.claude_carried_settings(), {"apiKeyHelper": "/usr/local/bin/get-key"})

    def test_explain_lists_no_names_for_a_string_env(self):
        self.settings({"env": "HTTPS_PROXY=x"})
        import family  # noqa: E402  (scripts/family.py)
        from ublib import families
        entry = family._explain_backend(families.load_families(), "claude-cli", "claude", "none", "default")
        self.assertNotIn("carried_settings", entry)


class DetectNoteTests(tl.AdapterTestCase):
    def detect_notes(self, config):
        textio.write_text_atomic(os.path.join(os.environ["CODEX_HOME"], "config.toml"), config)

        def run(argv, cwd=None, env=None, stdin_bytes=None, timeout_s=None, **_kw):
            return tl.PR(0, "codex-cli 0.158.0\n")
        with mock.patch("ublib.proc.resolve_exe", side_effect=tl.fake_resolve()), \
                mock.patch("ublib.proc.run", side_effect=run), mock.patch.dict(sys.modules, NO_TOMLLIB):
            res = detect.detect(only=["gpt"])
        return [n for n in res["families"]["gpt"]["notes"] if n.startswith(detect.USER_CONTEXT_NOTE)]

    def test_an_unaddressable_dotted_key_server_is_reported_without_tomllib(self):
        notes = self.detect_notes('mcp_servers."team.docs".command = "x"\n')
        self.assertTrue([n for n in notes if "team.docs" in n], notes)

    def test_a_config_that_cannot_be_read_is_reported(self):
        notes = self.detect_notes('[mcp_servers.foo]\ncommand = "x\n')
        self.assertTrue([n for n in notes if "could not read line 2" in n and "config.toml" in n], notes)


if __name__ == "__main__":
    unittest.main()
