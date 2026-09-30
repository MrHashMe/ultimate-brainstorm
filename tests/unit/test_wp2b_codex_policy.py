"""WP2b: the Codex backend enforces the job's tools (audit P1-3, findings 22 and 63; contract C7).

A tools=none job used to get the same argv as a read job, and parse() ignored every tool item: a transcript in which
codex ran `cat ~/.ssh/id_rsa` or called an MCP tool came back "ok". Now the JSONL items are checked against the job's
tools (refused, error_class policy, no retry, repair or fallback), the argv disables the shell for jobs without read,
the user's MCP servers and notify program, and web search unless the job has web. Process calls are mocked."""

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
from ublib import adapter, textio  # noqa: E402
from ublib.backends import CallContext, codex_cli  # noqa: E402

CMD = ("command_execution", {"command": "cat ~/.ssh/id_rsa", "aggregated_output": "PRIVATE-KEY-MARKER",
                             "exit_code": 0, "status": "completed"})
MCP = ("mcp_tool_call", {"server": "node_repl", "tool": "eval", "status": "completed"})
WEB = ("web_search", {"query": "official python website"})
FILE = ("file_change", {"changes": [{"path": "notes.md", "kind": "add"}], "status": "completed"})
ANSWER = "Final answer text that quotes PRIVATE-KEY-MARKER."


def transcript(*items, **kw):
    """codex exec --json output: each tool item is started and completed, then the agent message and usage."""
    lines = [{"type": "thread.started", "thread_id": "t"}, {"type": "turn.started"}]
    for i, (itype, extra) in enumerate(items):
        item = dict({"id": "item_%d" % i, "type": itype}, **extra)
        if not kw.get("completed_only"):
            lines.append({"type": "item.started", "item": item})
        if not kw.get("started_only"):
            lines.append({"type": "item.completed", "item": item})
    lines.append({"type": "item.completed", "item": {"id": "last", "type": "agent_message", "text": ANSWER}})
    lines.append({"type": "turn.completed", "usage": {"input_tokens": 10, "output_tokens": 5}})
    return ("\n".join(json.dumps(x) for x in lines) + "\n").encode("utf-8")


def writes_last(stdout, text=ANSWER):
    def respond(call):
        argv = call["argv"]
        with open(argv[argv.index("-o") + 1], "w", encoding="utf-8") as f:
            f.write(text)
        return tl.PR(0, stdout)
    return respond


class ParseGuardTests(unittest.TestCase):
    """codex_cli.parse() alone: which item types each tools value refuses."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ub-wp2b-codex-")
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def parse(self, tools, stdout, web=True):
        last = os.path.join(self.tmp, "last.txt")
        textio.write_text_atomic(last, ANSWER)
        ctx = CallContext(bcfg={"web": web}, btype="codex-cli", timeout_s=5, tools=tools)
        return codex_cli.parse(tl.PR(0, stdout), ctx, "codex exec", last), last

    def test_refusal_table(self):
        refused = {"none": {"command_execution", "mcp_tool_call", "web_search", "file_change"},
                   "read": {"mcp_tool_call", "web_search", "file_change"},
                   "web": {"command_execution", "mcp_tool_call", "file_change"},
                   "read+web": {"mcp_tool_call", "file_change"}}
        for tools, banned in refused.items():
            for item in (CMD, MCP, WEB, FILE):
                with self.subTest(tools=tools, item=item[0]):
                    r, last = self.parse(tools, transcript(item))
                    if item[0] in banned:
                        self.assertEqual((r["status"], r["error_class"]), ("refused", "policy"))
                        self.assertIsNone(r["text"])
                        self.assertFalse(r["retryable"])
                        self.assertIn(item[0], r["error"])
                        self.assertFalse(os.path.exists(last), "the -o file is discarded")
                    else:
                        self.assertEqual(r["status"], "ok", r)
                        self.assertEqual(r["text"], ANSWER)

    def test_started_or_completed_alone_counts(self):
        for kw in ({"started_only": True}, {"completed_only": True}):
            r, _last = self.parse("none", transcript(CMD, **kw))
            self.assertEqual(r["status"], "refused", kw)

    def test_web_used_comes_from_web_search_items(self):
        r, _last = self.parse("web", transcript(WEB))
        self.assertEqual(r["status"], "ok")
        self.assertTrue(r["web_used"])
        r, _last = self.parse("web", transcript())
        self.assertFalse(r["web_used"], "a web job that never searched did not use the web")
        r, _last = self.parse("none", transcript(WEB), web=False)
        self.assertEqual(r["status"], "refused")
        self.assertTrue(r["web_used"])

    def test_plain_transcript_is_ok(self):
        r, _last = self.parse("none", transcript())
        self.assertEqual((r["status"], r["text"], r["requests"]), ("ok", ANSWER, 1))


class AdapterRefusalTests(tl.AdapterTestCase):
    """execute_job(): a refused attempt is final (C7): exit 7, no retry, no repair, no next backend, no <out>."""

    def run_job(self, job, responses, chain=("codex-cli", "openai-http")):
        fake = tl.FakeRun(responses)
        det = tl.chain_detect({"gpt": list(chain)}, host_family="claude")
        with mock.patch("ublib.proc.run", side_effect=fake), \
                mock.patch("ublib.proc.resolve_exe", side_effect=tl.fake_resolve()), \
                mock.patch("ublib.backends.http_openai.run") as http_run:
            meta = adapter.execute_job(job, detect_result=det)
        return meta, fake, http_run

    def test_shell_use_on_a_tools_none_job_is_refused(self):
        job = self.make_job(family="gpt", retries=1)
        meta, fake, http_run = self.run_job(job, [writes_last(transcript(CMD))])
        self.assertEqual((meta["status"], meta["error_class"]), ("refused", "policy"))
        self.assertEqual(adapter.exit_code_for(meta["status"]), 7)
        self.assertEqual(len(fake.calls), 1, "no retry and no repair")
        http_run.assert_not_called()
        self.assertEqual(meta["attempts"], 1)
        self.assertFalse(os.path.exists(self.out_path(job)))
        self.assertNotIn("PRIVATE-KEY-MARKER", self.all_output_text())
        self.assertEqual([(r["status"], r["requests"]) for r in self.calls_log()], [("refused", 1)])

    def test_mcp_tool_call_is_refused_even_with_read(self):
        repo = os.path.join(self.tmp, "repo")
        os.makedirs(repo)
        self.write_run_json(privacy={"web": True, "vendors": True, "code": True,
                                     "allowed_vendors": ["anthropic", "openai"]})
        job = self.make_job(family="gpt", tools="read", cwd="repo", repo_root=repo,
                            privacy={"vendor_ok": True, "web_ok": True, "code_ok": True})
        meta, fake, _h = self.run_job(job, [writes_last(transcript(CMD, MCP))])
        self.assertEqual(meta["status"], "refused")
        self.assertIn("mcp_tool_call", meta["reason"])
        self.assertNotIn("command_execution", meta["reason"], "a read job may run commands")

    def test_read_job_may_run_commands(self):
        repo = os.path.join(self.tmp, "repo")
        os.makedirs(repo)
        self.write_run_json(privacy={"web": True, "vendors": True, "code": True,
                                     "allowed_vendors": ["anthropic", "openai"]})
        job = self.make_job(family="gpt", tools="read", cwd="repo", repo_root=repo,
                            privacy={"vendor_ok": True, "web_ok": True, "code_ok": True})
        meta, _fake, _h = self.run_job(job, [writes_last(transcript(CMD))])
        self.assertEqual(meta["status"], "ok")
        self.assertTrue(meta["repo_read"])


class ArgvTests(tl.AdapterTestCase):
    def argv_for(self, tools, **job_fields):
        fake = tl.FakeRun([writes_last(transcript())])
        job = self.make_job(family="gpt", tools=tools, job_id="a-" + tools.replace("+", "-"), **job_fields)
        det = tl.chain_detect({"gpt": ["codex-cli"]}, host_family="claude")
        with mock.patch("ublib.proc.run", side_effect=fake), \
                mock.patch("ublib.proc.resolve_exe", side_effect=tl.fake_resolve()):
            meta = adapter.execute_job(job, detect_result=det)
        self.assertEqual(meta["status"], "ok", meta)
        return fake.calls[0]["argv"]

    def pairs(self, argv):
        return [argv[i + 1] for i, a in enumerate(argv[:-1]) if a == "-c"]

    def test_tools_none_and_read_differ(self):
        none, read, web = self.pairs(self.argv_for("none")), self.pairs(self.argv_for("read")), \
            self.pairs(self.argv_for("web"))
        for c in (none, read, web):
            self.assertNotIn("mcp_servers={}", c)  # R-backends-0: merged, never replaced; each server by name
            self.assertIn("notify=[]", c)
        self.assertIn("features.shell_tool=false", none)
        self.assertIn("features.js_repl=false", none)
        self.assertNotIn("features.shell_tool=false", read)
        self.assertNotEqual(none, read)
        self.assertIn("web_search=disabled", none)
        self.assertIn("web_search=disabled", read)
        self.assertIn("web_search=live", web)
        self.assertNotIn("web_search=disabled", web)

    def test_disable_shell_key_turns_the_flag_off(self):
        self.write_families_override({"backends": {"codex-cli": {"disable_shell": False}}})
        self.assertNotIn("features.shell_tool=false", self.pairs(self.argv_for("none")))

    def test_each_user_mcp_server_is_disabled(self):
        home = os.environ["CODEX_HOME"]
        textio.write_text_atomic(os.path.join(home, "config.toml"),
                                 '[mcp_servers.node_repl]\ncommand = "node"\n'
                                 '[mcp_servers.idea-reality]\ncommand = "uvx"\n'
                                 '[mcp_servers."bad name&x"]\ncommand = "x"\n')
        c = self.pairs(self.argv_for("none"))
        self.assertIn("mcp_servers.node_repl.enabled=false", c)
        self.assertIn("mcp_servers.idea-reality.enabled=false", c)
        self.assertFalse([x for x in c if "bad name" in x], "names unsafe for a -c key path are never passed")


if __name__ == "__main__":
    unittest.main()
