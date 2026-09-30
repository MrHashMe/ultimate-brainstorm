"""E2: codex and kimi output is read line by line as it arrives, so a long run is neither buffered nor killed at 8 MB
(findings 32 and 43, reviewer note P3-backends-1).

- proc.run(on_line=...) passes every stdout line on while the child runs; memory stays bounded however long the
  stream, stdout_bytes keeps only its head, and a line past proc.LINE_CAP_BYTES arrives as its head (whole=False);
- a 10+ MB codex stream (a repo job's command output) with its answer in -o last.txt comes back ok, and a 10+ MB kimi
  stream (tool results) with its final message too; the tool policy still sees every event of a 20 MB stream;
- claude-cli keeps kill-and-invalid, at 6 x the 2 MB answer cap + 64 KB (one JSON object); every cap follows the
  backend key max_stdout_mb;
- a kimi sample keeps at most the first 1 MB of the stream.
Real child processes are the current Python interpreter only; no model CLI and no network.
"""

import json
import os
import shutil
import sys
import tempfile
import threading
import tracemalloc
import unittest
from unittest import mock

_KIT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(_KIT, "tests", "fixtures", "adapter"))

import adapter_testlib as tl  # noqa: E402
from ublib import adapter, backends, families, proc, textio  # noqa: E402
from ublib.backends import CallContext, codex_cli, kimi_cli  # noqa: E402

PY = sys.executable
MB = 1024 * 1024

# A codex stand-in: argv <last.txt> <MB of command output> <tool item type in the middle or "">. It writes the
# answer to the -o file and prints `codex exec --json` events.
FAKE_CODEX = r'''
import json, sys
last, mb, middle = sys.argv[1], int(sys.argv[2]), sys.argv[3]
open(last, "w").write("the answer from last.txt")
out = sys.stdout
item = {"type": "item.completed", "item": {"id": "c", "type": "command_execution", "command": "rg x",
        "aggregated_output": "o" * 65000, "exit_code": 0}}
line = json.dumps(item) + "\n"
n = mb * 1024 * 1024 // len(line) + 1
for i in range(n):
    out.write(line)
    if middle and i == n // 2:
        out.write(json.dumps({"type": "item.completed", "item": {"id": "m", "type": middle}}) + "\n")
out.write(json.dumps({"type": "item.completed", "item": {"id": "a", "type": "agent_message", "text": "stream"}}) + "\n")
out.write(json.dumps({"type": "turn.completed", "usage": {"input_tokens": 3, "output_tokens": 4}}) + "\n")
'''

# A kimi stand-in: argv <MB of tool results>. Tool calls and results, then the final assistant message.
FAKE_KIMI = r'''
import json, sys
mb = int(sys.argv[1])
call = json.dumps({"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "FetchURL"}}]})
tool = json.dumps({"role": "tool", "content": "page text " * 6000})
n = mb * 1024 * 1024 // (len(call) + len(tool)) + 1
for _ in range(n):
    sys.stdout.write(call + "\n" + tool + "\n")
sys.stdout.write(json.dumps({"role": "assistant", "content": "FINAL ANSWER"}) + "\n")
'''


class Base(tl.AdapterTestCase):
    def ctx(self, btype, bid, tools="read", **kw):
        cfg = families.load_families()
        call_dir = tempfile.mkdtemp(prefix="call-", dir=self.tmp)
        return CallContext(job={"id": "s1"}, job_id="s1", prompt="Do the task.", backend_id=bid,
                           bcfg=families.backend_cfg(cfg, bid), btype=btype, cfg=cfg, family=kw.pop("family", "gpt"),
                           tools=tools, call_dir=call_dir, run_dir=self.run_dir, timeout_s=300, ub_home=self.home, **kw)

    def run_codex(self, mb, middle="", tools="read"):
        ctx = self.ctx("codex-cli", "codex-cli", tools=tools)
        seen = {}

        def argv(c, paths):
            seen["last"] = paths["last"]
            return [PY, "-c", FAKE_CODEX, paths["last"], str(mb), middle]
        with mock.patch.object(codex_cli, "build_argv", side_effect=argv):
            return codex_cli.run(ctx), seen


class ProcStreamingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ub-e2-stream-")
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_lines_arrive_as_they_come_and_nothing_is_buffered(self):
        code = ("import sys\nw = sys.stdout.buffer.write\nline = b'x' * 1000 + b'\\n'\n"
                "for i in range(30000):\n    w(line)\nw(b'last\\r\\nno newline at the end')\n")  # about 30 MB
        got = {"n": 0, "bytes": 0, "last": None, "whole": set(), "thread": set()}

        def on_line(line, whole):
            got["n"] += 1
            got["bytes"] += len(line)
            got["last"] = line
            got["whole"].add(whole)
            got["thread"].add(threading.current_thread() is threading.main_thread())
        tracemalloc.start()
        try:
            r = proc.run([PY, "-c", code], cwd=self.tmp, timeout_s=120, max_stdout=None, on_line=on_line)
            peak = tracemalloc.get_traced_memory()[1]
        finally:
            tracemalloc.stop()
        self.assertEqual((r.returncode, r.overflow, r.timed_out), (0, False, False))
        self.assertEqual(got["n"], 30002)
        self.assertEqual(got["last"], b"no newline at the end")
        self.assertEqual(got["whole"], {True})
        self.assertEqual(got["thread"], {False}, "on_line runs on the reader thread")
        self.assertEqual(len(r.stdout_bytes), proc.STREAM_HEAD_BYTES, "only the head of the stream is kept")
        self.assertLess(peak, 6 * MB, "the stream was buffered: peak %d bytes" % peak)

    def test_a_line_past_the_line_cap_arrives_as_its_head(self):
        code = "import sys\nsys.stdout.buffer.write(b'a' * 50000 + b'\\n' + b'short\\n' + b'b' * 9000)\n"
        got = []
        with mock.patch.object(proc, "LINE_CAP_BYTES", 4096):
            proc.run([PY, "-c", code], cwd=self.tmp, timeout_s=60, on_line=lambda line, whole: got.append(
                (len(line), line[:1], whole)))
        self.assertEqual(got, [(4096, b"a", False), (5, b"s", True), (4096, b"b", False)])

    def test_the_stream_cap_still_kills_a_flood(self):
        code = "import sys\nb = b'y' * 65535 + b'\\n'\nwhile True:\n    sys.stdout.buffer.write(b)\n"
        n = []
        r = proc.run([PY, "-c", code], cwd=self.tmp, timeout_s=120, max_stdout=4 * MB,
                     on_line=lambda line, whole: n.append(1))
        self.assertTrue(r.overflow)
        self.assertFalse(r.timed_out)
        self.assertLessEqual(len(n), 4 * MB // 65536 + 1)

    def test_an_on_line_error_is_raised_once_the_child_is_gone(self):
        def boom(line, whole):
            raise ValueError("parser bug")
        with self.assertRaises(ValueError):
            proc.run([PY, "-c", "print('a'); print('b')"], cwd=self.tmp, timeout_s=60, on_line=boom)

    def test_buffered_mode_is_unchanged(self):
        r = proc.run([PY, "-c", "print('hi')"], cwd=self.tmp, timeout_s=60)
        self.assertEqual(r.stdout_bytes.strip(), b"hi")


class CodexStreamTests(Base):
    def test_a_long_codex_run_is_ok_with_its_answer_from_last_txt(self):
        res, _seen = self.run_codex(10)
        self.assertEqual((res["status"], res["text"]), ("ok", "the answer from last.txt"), res.get("error"))
        self.assertEqual(res["usage"]["output_tokens"], 4)

    def test_the_policy_sees_an_event_in_the_middle_of_a_long_stream(self):
        res, seen = self.run_codex(20, middle="mcp_tool_call")
        self.assertEqual((res["status"], res["error_class"]), ("refused", "policy"), res.get("error"))
        self.assertIn("mcp_tool_call", res["error"])
        self.assertFalse(os.path.exists(seen["last"]), "the answer of a refused attempt is discarded")

    def test_an_oversized_event_counts_by_the_type_in_its_head(self):
        with mock.patch.object(proc, "LINE_CAP_BYTES", 16 * 1024):  # each command item line is about 65 KB
            res, _seen = self.run_codex(1, tools="none")
            self.assertEqual(res["status"], "refused")
            self.assertIn("command_execution", res["error"])
            res, _seen = self.run_codex(1, tools="read")
            self.assertEqual(res["status"], "ok", res.get("error"))


class KimiStreamTests(Base):
    def test_a_long_kimi_run_is_ok_and_its_sample_keeps_one_megabyte(self):
        ctx = self.ctx("kimi-cli", "kimi-cli", tools="web", family="kimi")
        with mock.patch.object(kimi_cli, "build_argv", side_effect=lambda c, p: [PY, "-c", FAKE_KIMI, "10"]):
            res = kimi_cli.run(ctx)
        self.assertEqual((res["status"], res["text"], res["web_used"]), ("ok", "FINAL ANSWER", True), res.get("error"))
        sample = os.path.join(self.run_dir, "logs", "kimi-samples", "sample-1.jsonl")
        size = os.path.getsize(sample)
        self.assertLessEqual(size, kimi_cli.SAMPLE_CAP_BYTES)
        self.assertGreater(size, kimi_cli.SAMPLE_CAP_BYTES // 2)
        self.assertTrue(textio.read_bytes(sample).endswith(b"\n"), "cut after a whole line")

    def test_a_mocked_sample_is_capped_too(self):
        raw = (json.dumps({"role": "tool", "content": "t" * 900}) + "\n").encode() * 3000  # about 2.8 MB
        ctx = self.ctx("kimi-cli", "kimi-cli", tools="web", family="kimi")
        kimi_cli._save_sample(ctx, raw)
        data = textio.read_bytes(os.path.join(self.run_dir, "logs", "kimi-samples", "sample-1.jsonl"))
        self.assertLessEqual(len(data), kimi_cli.SAMPLE_CAP_BYTES)
        self.assertTrue(all(json.loads(x) for x in data.decode().splitlines()), "whole lines only")


class CapTests(tl.AdapterTestCase):
    def caps(self):
        seen = {}
        for family, chain in (("claude", "claude-cli"), ("gpt", "codex-cli"), ("kimi", "kimi-cli")):
            fake = tl.FakeRun([tl.PR(1, b"", b"boom")])
            job = self.make_job(family=family, job_id="cap-%s" % family, retries=0)
            with mock.patch("ublib.proc.run", side_effect=fake), \
                    mock.patch("ublib.proc.resolve_exe", side_effect=tl.fake_resolve()):
                adapter.execute_job(job, detect_result=tl.chain_detect({family: [chain]}, host_family="claude"))
            seen[chain] = (fake.calls[0]["max_stdout"], fake.calls[0]["on_line"] is not None)
        return seen

    def test_claude_is_capped_and_buffered_codex_and_kimi_are_streamed(self):
        self.assertEqual(backends.CLAUDE_STDOUT_CAP_BYTES, 6 * 2 * MB + 64 * 1024)
        self.assertEqual(self.caps(), {"claude-cli": (backends.CLAUDE_STDOUT_CAP_BYTES, False),
                                       "codex-cli": (backends.STREAM_CAP_BYTES, True),
                                       "kimi-cli": (backends.STREAM_CAP_BYTES, True)})

    def test_max_stdout_mb_sets_the_cap(self):
        self.write_families_override({"backends": {"claude-cli": {"max_stdout_mb": 20},
                                                    "codex-cli": {"max_stdout_mb": 0.5},
                                                    "kimi-cli": {"max_stdout_mb": "x"}}})
        caps = self.caps()
        self.assertEqual(caps["claude-cli"][0], 20 * MB)
        self.assertEqual(caps["codex-cli"][0], MB // 2)
        self.assertEqual(caps["kimi-cli"][0], backends.STREAM_CAP_BYTES, "a value that is not a number is ignored")

    def test_the_overflow_reason_names_the_cap(self):
        flood = proc.ProcResult(-9, b"{", b"", False, True)
        fake = tl.FakeRun([flood])
        job = self.make_job(family="claude", job_id="cap-o")
        with mock.patch("ublib.proc.run", side_effect=fake), \
                mock.patch("ublib.proc.resolve_exe", side_effect=tl.fake_resolve()):
            meta = adapter.execute_job(job, detect_result=tl.chain_detect({"claude": ["claude-cli"]}, "claude"))
        self.assertEqual(meta["status"], "invalid")
        self.assertIn("printed more than the 12.1 MB stdout cap", meta["reason"])


if __name__ == "__main__":
    unittest.main()
