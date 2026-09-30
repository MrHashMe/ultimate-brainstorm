"""WPF1: worker-backend follow-ups (KIT_SPEC 4.7, 5.2-5.5).

- a CLI stdout past proc.run's cap ends the job invalid / bad_output: no retry, repair or next backend (32, 43);
- the codex and kimi parsers hold no per-event copies of a large stream (32, 43);
- codex --output-schema gets a copy without the unverified bound keywords [U-85];
- claude jobs that read the repository are denied the run folders by tool rules [U-44];
- a provider backend (claude-cli@glm/@kimi) honors the alt seat's model;
- workers sweep the secret files of dead launchers; a worker imports every backend before its call;
- the fake-mode stub loads its harness once, even when parallel pings start together (the preflight flake);
- project memory above the worker folder is reported (28); split warnings reach the meta; the prompt is read once;
- job paths are contained after resolving links; job locks share textio's lock primitive.
Process calls are mocked at ublib.proc.run; no model CLI and no network.
"""

import json
import os
import subprocess
import sys
import threading
import time
import tracemalloc
import types
import unittest
from unittest import mock

_KIT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(_KIT, "tests", "fixtures", "adapter"))

import adapter_testlib as tl  # noqa: E402
from ublib import adapter, backends, batch, detect, proc, textio  # noqa: E402
from ublib.backends import CallContext, claude_cli, codex_cli, kimi_cli, stub  # noqa: E402

SUCCESS = tl.fixture_bytes("claude", "success.json")
FAMILY_PY = os.path.join(tl.SCRIPTS, "family.py")


def ok_json(text):
    return json.dumps({"type": "result", "subtype": "success", "is_error": False, "result": text}).encode("utf-8")


def flood(returncode=-9, timed_out=False):
    """What proc.run returns when a CLI printed past its stdout cap (the tree was killed)."""
    return proc.ProcResult(returncode, b'{"type":"item.completed"}\n' * 64, b"stderr before the kill", timed_out, True)


def run_job(job, responses, family, chain, resolve=None):
    fake = tl.FakeRun(responses)
    det = tl.chain_detect({family: list(chain)}, host_family="claude")
    with mock.patch("ublib.proc.run", side_effect=fake), \
            mock.patch("ublib.proc.resolve_exe", side_effect=resolve or tl.fake_resolve()):
        meta = adapter.execute_job(job, detect_result=det)
    return meta, fake


def no_http(*_a, **_k):
    raise AssertionError("the chain moved on to an HTTP backend")


# ---------------------------------------------------------------- 1. stdout cap: final invalid (R36, R37)

class StdoutOverflowTests(tl.AdapterTestCase):
    CASES = (("claude", ["claude-cli", "anthropic-http"]), ("gpt", ["codex-cli", "openai-http"]),
             ("kimi", ["kimi-cli", "openai-http@kimi"]))

    def test_each_cli_overflow_ends_the_job_invalid(self):
        for family, chain in self.CASES:
            job = self.make_job(family=family, job_id="o-%s" % family, retries=1)
            with mock.patch("ublib.backends.http_openai.run", side_effect=no_http), \
                    mock.patch("ublib.backends.http_anthropic.run", side_effect=no_http):
                meta, fake = run_job(job, [flood()], family, chain)
            self.assertEqual((meta["status"], meta["error_class"], meta["attempts"], len(fake.calls)),
                             ("invalid", "bad_output", 1, 1), family)
            self.assertEqual(adapter.exit_code_for(meta["status"]), 5)
            self.assertIn("stdout cap", meta["reason"])
            self.assertEqual(meta["requests"], 1, "the CLI ran: one request")
            self.assertFalse(os.path.exists(self.out_path(job)))
            self.assertTrue(textio.read_text(self.out_path(job) + ".failed.md").startswith("FAMILY CALL FAILED:"))
        rows = self.calls_log()
        self.assertEqual([(r["status"], r["error_class"], r["requests"]) for r in rows],
                         [("invalid", "bad_output", 1)] * len(self.CASES))

    def test_overflow_wins_over_a_timeout(self):
        job = self.make_job(family="claude")
        meta, fake = run_job(job, [flood(timed_out=True)], "claude", ["claude-cli"])
        self.assertEqual((meta["status"], len(fake.calls)), ("invalid", 1))

    def test_an_overflowing_repair_call_is_reported(self):
        job = self.make_job(family="claude", contract={"type": "text", "regex": "NEVER-MATCHES"})
        meta, fake = run_job(job, [tl.PR(0, SUCCESS), flood()], "claude", ["claude-cli"])
        self.assertEqual((meta["status"], meta["attempts"], len(fake.calls)), ("invalid", 2, 2))
        self.assertIn("stdout cap", meta["reason"])

    def test_an_oversized_repair_answer_fails_its_own_cap_check(self):
        """R23: the repair branch has no cap check of its own; check_contract reports the repair answer's size."""
        job = self.make_job(family="claude", contract={"type": "text", "regex": "NEVER-MATCHES"})
        big = ok_json("x" * (2 * 1024 * 1024 + 10))
        meta, _fake = run_job(job, [tl.PR(0, SUCCESS), tl.PR(0, big)], "claude", ["claude-cli"])
        self.assertEqual(meta["status"], "invalid")
        self.assertIn("output exceeds the 2 MB cap", meta["reason"])


class ParserMemoryTests(unittest.TestCase):
    """32 / 43: parsing a multi-MB stream allocates about one line at a time, not copies of the whole stream."""

    def peak(self, fn):
        tracemalloc.start()
        try:
            fn()
            return tracemalloc.get_traced_memory()[1]
        finally:
            tracemalloc.stop()

    def test_codex_stream(self):
        item = {"type": "item.completed", "item": {"id": "x", "type": "command_execution", "command": "cat f",
                                                   "aggregated_output": "o" * 500, "exit_code": 0}}
        lines = [json.dumps(item)] * 12000 + [json.dumps({"type": "item.completed", "item": {
            "type": "agent_message", "text": "FINAL"}}), json.dumps({"type": "turn.completed", "usage": {
                "input_tokens": 3, "output_tokens": 4}})]
        raw = ("\n".join(lines) + "\n").encode("utf-8")
        self.assertGreater(len(raw), 6 * 1024 * 1024)
        ctx = CallContext(bcfg={}, btype="codex-cli", tools="read", timeout_s=5)
        out = {}
        used = self.peak(lambda: out.update(r=codex_cli.parse(tl.PR(0, raw), ctx, "cmd", None)))
        self.assertEqual((out["r"]["status"], out["r"]["text"]), ("ok", "FINAL"))
        self.assertLess(used, 1024 * 1024, "codex parse held %d bytes for a %d byte stream" % (used, len(raw)))

    def test_kimi_stream(self):
        call = {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "Read"}}]}
        tool = {"role": "tool", "content": "t" * 500}
        lines = [json.dumps(x) for _ in range(6000) for x in (call, tool)]
        lines.append(json.dumps({"role": "assistant", "content": "FINAL"}))
        raw = ("\n".join(lines) + "\n").encode("utf-8")
        ctx = CallContext(bcfg={}, btype="kimi-cli", timeout_s=5)
        out = {}
        used = self.peak(lambda: out.update(r=kimi_cli.parse(tl.PR(0, raw), ctx, "cmd")))
        self.assertEqual((out["r"]["status"], out["r"]["text"]), ("ok", "FINAL"))
        self.assertLess(used, 1024 * 1024, "kimi parse held %d bytes for a %d byte stream" % (used, len(raw)))


# ---------------------------------------------------------------- 2. codex --output-schema [U-85] (R19)

class CodexSchemaTests(tl.AdapterTestCase):
    SCHEMA = {"type": "object", "additionalProperties": False, "required": ["score", "minimum"],
              "properties": {"score": {"type": "integer", "minimum": 1, "maximum": 5},
                             "minimum": {"type": "string", "description": "a property that shares a keyword name"},
                             "list": {"type": "array", "items": {"type": "integer", "minimum": 0}},
                             "tags": {"type": "object", "minProperties": 1, "maxProperties": 3,
                                      "additionalProperties": {"type": "number", "maximum": 9}},
                             "any": {"anyOf": [{"type": "integer", "maximum": 3}, {"type": "null"}]}},
              "$defs": {"n": {"type": "number", "minimum": 0}}}
    STRIPPED = {"type": "object", "additionalProperties": False, "required": ["score", "minimum"],
                "properties": {"score": {"type": "integer"},
                               "minimum": {"type": "string", "description": "a property that shares a keyword name"},
                               "list": {"type": "array", "items": {"type": "integer"}},
                               "tags": {"type": "object", "additionalProperties": {"type": "number"}},
                               "any": {"anyOf": [{"type": "integer"}, {"type": "null"}]}},
                "$defs": {"n": {"type": "number"}}}

    def test_bound_keywords_are_dropped_at_schema_positions_only(self):
        self.assertEqual(codex_cli.cli_schema(self.SCHEMA), self.STRIPPED)

    def test_the_cli_gets_the_copy_and_the_run_keeps_its_schema(self):
        rel = "schemas/j.schema.json"
        textio.write_json_atomic(os.path.join(self.run_dir, rel), self.SCHEMA)
        seen = {}

        def respond(call):
            argv = call["argv"]
            seen["schema"] = textio.read_json(argv[argv.index("--output-schema") + 1])
            with open(argv[argv.index("-o") + 1], "w", encoding="utf-8") as f:
                f.write('{"score": 3, "minimum": "x"}')
            return tl.PR(0, b"")
        job = self.make_job(family="gpt", schema_file=rel, contract={"type": "json", "schema": rel})
        meta, _fake = run_job(job, [respond], "gpt", ["codex-cli"])
        self.assertEqual(meta["status"], "ok")
        self.assertEqual(seen["schema"], self.STRIPPED)
        self.assertEqual(textio.read_json(os.path.join(self.run_dir, rel)), self.SCHEMA)


# ---------------------------------------------------------------- 3. claude: run folders and alt model (R31, R49)

class ClaudeRunFolderTests(tl.AdapterTestCase):
    def repo_job(self, job_id="rf1", tools="read"):
        repo = os.path.join(self.tmp, "project")
        self.write_run_json()
        return self.make_job(family="claude", tools=tools, cwd="repo", repo_root=repo, job_id=job_id)

    def rules(self, argv):
        i = argv.index("--disallowedTools")
        end = next((k for k in range(i + 1, len(argv)) if argv[k].startswith("--")), len(argv))
        return argv[i + 1:end]

    def test_rule_path_form(self):
        p = os.path.join(os.path.abspath(os.sep), "work", "brainstorm")
        drive = os.path.splitdrive(p)[0]
        want = ("//%s/work/brainstorm" % drive[0].lower()) if drive.endswith(":") else "//work/brainstorm"
        self.assertEqual(claude_cli.rule_path(p), want)

    def test_repo_readers_are_denied_the_run_folders(self):
        job = self.repo_job()
        meta, fake = run_job(job, [tl.PR(0, SUCCESS)], "claude", ["claude-cli"])
        self.assertEqual(meta["status"], "ok")
        runs = claude_cli.rule_path(os.path.dirname(self.run_dir))
        self.assertTrue(runs.startswith("//") and runs.endswith("/brainstorm"), runs)
        self.assertEqual(self.rules(fake.calls[0]["argv"]),
                         ["mcp__*", "Read(%s/**)" % runs, "Grep(%s/**)" % runs, "Glob(%s/**)" % runs])

    def test_other_jobs_and_the_config_key(self):
        _m, fake = run_job(self.repo_job("rf2", tools="web"), [tl.PR(0, SUCCESS)], "claude", ["claude-cli"])
        self.assertEqual(self.rules(fake.calls[0]["argv"]), ["mcp__*"], "no read tools: nothing to deny")
        job = self.make_job(family="claude", tools="read", job_id="rf3")
        _m, fake = run_job(job, [tl.PR(0, SUCCESS)], "claude", ["claude-cli"])
        self.assertEqual(self.rules(fake.calls[0]["argv"]), ["mcp__*"], "an empty cwd: nothing to deny")
        self.write_families_override({"backends": {"claude-cli": {"exclude_runs": False}}})
        _m, fake = run_job(self.repo_job("rf4"), [tl.PR(0, SUCCESS)], "claude", ["claude-cli"])
        self.assertEqual(self.rules(fake.calls[0]["argv"]), ["mcp__*"], "exclude_runs false turns them off")


class ProviderAltModelTests(tl.AdapterTestCase):
    def settings_env(self, family):
        os.environ["ZAI_API_KEY"] = "zai-test-token-0123456789"
        seen = {}

        def respond(call):
            argv = call["argv"]
            seen["env"] = textio.read_json(argv[argv.index("--settings") + 1])["env"]
            return tl.PR(0, SUCCESS)
        meta, fake = run_job(self.make_job(family=family, job_id=family), [respond], "glm", ["claude-cli@glm"])
        self.assertNotIn("--model", fake.calls[0]["argv"])
        return meta, seen["env"]

    def test_the_alt_seat_model_reaches_the_settings_file(self):
        self.write_families_override({"families": {"glm": {"alt_model": "glm-alt-test"}}})
        meta, env = self.settings_env("glm-alt")
        self.assertEqual((env["ANTHROPIC_MODEL"], meta["model"], meta["provisional"]), ("glm-alt-test", "glm-alt-test",
                                                                                         True))
        meta, env = self.settings_env("glm")
        self.assertEqual((env["ANTHROPIC_MODEL"], meta["model"]), ("glm-5.3[1m]", "glm-5.3[1m]"))


# ---------------------------------------------------------------- 4. launcher secret files (R12)

class SweepLauncherFilesTests(tl.AdapterTestCase):
    def put(self, name, mtime=None):
        path = os.path.join(self.home, "tmp", name)
        textio.write_text_atomic(path, '{"env": {"ANTHROPIC_AUTH_TOKEN": "x"}}\n')
        if mtime is not None:
            os.utime(path, (mtime, mtime))
        return path

    def test_files_of_gone_launchers_are_removed_never_by_age(self):
        gone = subprocess.Popen([sys.executable, "-c", "pass"])
        gone.wait(timeout=60)
        me = os.getpid()
        started = proc.process_start_time(me)
        self.assertIsNotNone(started)
        dead = self.put("launch-%d-0123456789ab.json" % gone.pid)
        live = self.put("zai-mcp-%d-0123456789ab.json" % me)
        reused = self.put("launch-%d-ba9876543210.json" % me, mtime=started - 100)  # older than our process
        other = self.put("launch-notes.json")
        ident = proc.process_identity(me) or ""
        exact = ident.split(":", 1)[0] in ("win", "linux")  # a ps identity (macOS) never proves a reuse (F2 / X9)
        if exact:  # written by another process that had our pid
            textio.write_text_atomic(reused + ".id", ident + "0\n")
        self.assertEqual(backends.sweep_stale_calls(self.home), 2 if exact else 1)
        self.assertEqual([os.path.exists(p) for p in (dead, live, reused, other)], [False, True, not exact, True])
        self.assertFalse(os.path.exists(reused + ".id"))
        old = self.put("launch-%d-00000000aaaa.json" % me, mtime=time.time() - 7 * 3600)
        with mock.patch.object(proc, "process_start_time", return_value=time.time() - 8 * 3600):
            self.assertEqual(backends.sweep_stale_calls(self.home), 0, "a live launcher's file has no age limit")
        self.assertTrue(os.path.exists(old))
        with mock.patch.object(proc, "process_start_time", return_value=None):
            os.utime(old, (started - 100, started - 100))
            self.assertEqual(backends.sweep_stale_calls(self.home), 0, "an unknown start time keeps the file")


# ---------------------------------------------------------------- 5. the worker imports every backend first (R13)

PRELOAD_PROBE = r'''
import json, sys
sys.path.insert(0, sys.argv[1])
import family
seen = []

def execute(job, **_kw):
    seen.extend(sorted(m for m in sys.modules if m.startswith("ublib.backends.") or m == "ublib.engine.privacy"))
    return {"status": "failed", "id": job["id"], "reason": "probe"}

family.adapter.execute_job = execute
family.main(["job", "--job", sys.argv[2]])
sys.stdout.write("\nMODULES " + json.dumps(seen) + "\n")
'''


class WorkerPreloadTests(tl.AdapterTestCase):
    def test_backend_modules_are_loaded_before_the_call(self):
        job = self.make_job(family="claude", job_id="pre1")
        path = self.write_job(job)
        cp = subprocess.run([sys.executable, "-c", PRELOAD_PROBE, tl.SCRIPTS, path], env=dict(os.environ),
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=300)
        line = [ln for ln in cp.stdout.decode("utf-8", "replace").splitlines() if ln.startswith("MODULES ")]
        self.assertTrue(line, cp.stderr.decode("utf-8", "replace"))
        loaded = set(json.loads(line[-1][len("MODULES "):]))
        want = set("ublib.backends." + m for m in ("claude_cli", "codex_cli", "kimi_cli", "http_openai",
                                                   "http_anthropic", "stub")) | {"ublib.engine.privacy"}
        self.assertEqual(want - loaded, set())


# ---------------------------------------------------------------- 6. the stub harness loads once (preflight flake)

class _ProbeLock(object):
    """A lock that records when a caller has to wait for it."""

    def __init__(self):
        self.lock = threading.Lock()
        self.waited = threading.Event()

    def __enter__(self):
        if not self.lock.acquire(False):
            self.waited.set()
            self.lock.acquire()
        return self

    def __exit__(self, *_exc):
        self.lock.release()
        return False


HARNESS = '''import sys
gate = sys.modules["ub_wpf1_gate"]
gate.entered.set()
gate.release.wait(60)


class StubFailure(Exception):
    pass


def respond(job, prompt):
    return "PONG"
'''


class StubLoadRaceTests(tl.AdapterTestCase):
    """The flaky FakeModeTests.test_live_preflight_in_fake_mode: its three pings run in threads and all load the harness
    module on first use. A ping that arrived while another thread was still executing the module found it (already
    in sys.modules, half-initialized) and failed with 'stub error: AttributeError'."""

    def test_a_second_caller_waits_for_the_load(self):
        harness = os.path.join(self.tmp, "stubs.py")
        textio.write_text_atomic(harness, HARNESS)
        gate = types.ModuleType("ub_wpf1_gate")
        gate.entered, gate.release = threading.Event(), threading.Event()
        saved = sys.modules.pop(stub._MODULE, None)
        sys.modules["ub_wpf1_gate"] = gate

        def restore():
            sys.modules.pop("ub_wpf1_gate", None)
            sys.modules.pop(stub._MODULE, None)
            if saved is not None:
                sys.modules[stub._MODULE] = saved
        self.addCleanup(restore)
        self.addCleanup(gate.release.set)
        probe = _ProbeLock()
        results = {}

        def ping(name):
            ctx = CallContext(job={"id": "ping-%s" % name, "template": "PING"}, prompt="PING", btype="stub")
            results[name] = stub.run(ctx)
        with mock.patch.object(stub, "HARNESS_STUBS", harness), mock.patch.object(stub, "_LOAD_LOCK", probe,
                                                                                   create=True):
            first = threading.Thread(target=ping, args=("first",))
            first.start()
            self.assertTrue(gate.entered.wait(60), "the harness module never started loading")
            second = threading.Thread(target=ping, args=("second",))
            second.start()
            # release the load once the second ping waits for it (or, without the lock, has already answered)
            self.assertTrue(tl_wait(lambda: probe.waited.is_set() or "second" in results, 60))
            gate.release.set()
            first.join(60)
            second.join(60)
        self.assertEqual({k: (v["status"], v["error"]) for k, v in results.items()},
                         {"first": ("ok", ""), "second": ("ok", "")})


def tl_wait(pred, timeout):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pred():
            return True
        time.sleep(0.01)
    return bool(pred())


# ---------------------------------------------------------------- 7. small adapter and detect follow-ups

class WorkerMemoryNoteTests(tl.AdapterTestCase):
    """28: CLAUDE.md files above UB_HOME/tmp reach claude-cli workers as project memory: detect names them."""

    def test_memory_above_the_worker_folder_is_reported(self):
        memory = os.path.join(self.tmp, "CLAUDE.md")
        textio.write_text_atomic(memory, "Always answer in French.\n")
        self.assertIn(memory, detect.claude_worker_memory(self.home))

        def resolve(name, env=None):
            return os.path.join(os.path.abspath(os.sep), "fakebin", name + ".exe")
        with mock.patch("ublib.proc.resolve_exe", side_effect=resolve), \
                mock.patch("ublib.proc.run", return_value=tl.PR(0, "2.1.280 (Claude Code)\n")):
            res = detect.detect(None)
        notes = [n for n in res["families"]["claude"]["notes"] if n.startswith(detect.USER_CONTEXT_NOTE)]
        self.assertTrue([n for n in notes if textio.to_posix(memory) in n], notes)


class AdapterFollowUpTests(tl.AdapterTestCase):
    def test_split_warnings_reach_the_meta(self):
        """R29 (rule 4.6.3): a split warning (here a duplicate STATUS block) is logged in the meta, not dropped. A
        duplicate FILE block is not a warning but invalid framing (round 3, #40)."""
        text = ("=== FILE: a.md ===\nsecond\n=== END FILE ===\n=== STATUS ===\n{\"status\": \"partial\"}\n"
                "=== END STATUS ===\n=== STATUS ===\n{\"status\": \"complete\"}\n=== END STATUS ===\n")
        job = self.make_job(family="claude", contract={"type": "files", "allowed": ["a.md"], "required": ["a.md"]},
                            split={"root": "parts", "allowed": ["a.md"]})
        meta, _fake = run_job(job, [tl.PR(0, ok_json(text))], "claude", ["claude-cli"])
        self.assertEqual(meta["status"], "ok")
        self.assertEqual(textio.read_text(os.path.join(self.run_dir, "parts", "a.md")), "second\n")
        self.assertTrue([w for w in meta.get("split_warnings") or [] if "duplicate STATUS block" in w], meta)
        self.assertEqual(self.read_meta(job)["split_warnings"], meta["split_warnings"])

    def test_the_prompt_is_read_once(self):
        """R30: policy_check gets the prompt execute_job already read."""
        self.write_run_json()
        job = self.make_job(family="gpt", privacy={"vendor_ok": True, "code_filtered": True})
        with mock.patch.object(adapter, "_prompt_text", side_effect=AssertionError("read a second time")):
            meta, _fake = run_job(job, [tl.PR(0, b"")], "gpt", ["stub"])
        self.assertEqual(meta["status"], "ok", meta)

    def test_job_paths_are_contained_after_resolving_links(self):
        """R22: filesproto.inside is the one containment test; an out path through a link leaves the run folder."""
        outside = os.path.join(self.tmp, "outside")
        os.makedirs(outside)
        link = os.path.join(self.run_dir, "link")
        try:
            if os.name == "nt":
                import _winapi
                _winapi.CreateJunction(outside, link)
            else:
                os.symlink(outside, link)
        except (ImportError, AttributeError, OSError, NotImplementedError):
            self.skipTest("cannot create a link here")
        with self.assertRaises(adapter.JobError):
            adapter.check_job(self.make_job(out="link/x.md"))
        adapter.check_job(self.make_job(out="pool/x.md"))

    def test_job_locks_use_the_textio_primitive(self):
        """R28: a held JobLock is the byte lock textio.try_lock_fd takes, so a second open of the file cannot."""
        lock = batch.JobLock(self.run_dir, "lk1")
        self.assertTrue(lock.try_acquire())
        try:
            if not lock.exclusive:
                self.skipTest("no file locks on this file system")
            fd = os.open(lock.path, os.O_RDWR | getattr(os, "O_BINARY", 0))
            try:
                self.assertIs(textio.try_lock_fd(fd), False)
            finally:
                os.close(fd)
        finally:
            lock.release()
        self.assertIs(batch.lock_state(self.run_dir, "lk1"), False)
        self.assertFalse(hasattr(batch, "_os_lock"))


if __name__ == "__main__":
    unittest.main()
