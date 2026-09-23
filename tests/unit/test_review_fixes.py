"""Regressions for the integration review's security findings: executable lookup, secrets, redirects, lock,
atomic writes, parser recursion (KIT_SPEC 3.1, 4.6, 5.3, 5.4). No network: the redirect test uses a local server."""

import http.server
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest

_KIT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_SCRIPTS = os.path.join(_KIT, "skills", "ultimate-brainstorm", "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

from ublib import filesproto, proc, redact, textio, validate  # noqa: E402
from ublib import backends  # noqa: E402
from ublib.backends import claude_cli, http_openai  # noqa: E402
from ublib.engine import state as st  # noqa: E402


class TmpCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ub-review-")
        self._cwd = os.getcwd()

    def tearDown(self):
        os.chdir(self._cwd)
        shutil.rmtree(self.tmp, ignore_errors=True)


class ExecutableLookup(TmpCase):
    def test_current_folder_is_never_searched(self):
        name = "ubplanted"
        planted = os.path.join(self.tmp, name + (".cmd" if os.name == "nt" else ""))
        with open(planted, "w") as f:
            f.write("@echo planted\n" if os.name == "nt" else "#!/bin/sh\necho planted\n")
        if os.name != "nt":
            os.chmod(planted, 0o755)
        os.chdir(self.tmp)
        empty = os.path.join(self.tmp, "empty-bin")
        os.makedirs(empty)
        self.assertIsNone(proc.resolve_exe(name, {"PATH": empty}))
        self.assertIsNone(proc.which(name, path=os.pathsep.join(["", ".", empty])))
        self.assertEqual(os.path.normcase(proc.which(name, path=self.tmp)), os.path.normcase(planted))

    @unittest.skipUnless(os.name == "nt", "Windows .cmd shims only")
    def test_cmd_shim_path_with_metacharacters_is_refused(self):
        with self.assertRaises(proc.UnsafeArgument):
            proc.check_cmd_args(r"C:\Users\R&D\AppData\Roaming\npm\claude.cmd", ["--version"])


class Secrets(TmpCase):
    def test_key_like_names_are_secret(self):
        for name in ("OPENROUTER_KEY", "DEEPSEEK_KEY", "AZURE_OPENAI_KEY", "MY_GLM_KEY", "KEY"):
            self.assertTrue(redact.is_secret_name(name), name)
        for name in ("KEYBOARD", "MONKEY", "key_env"):
            self.assertFalse(redact.is_secret_name(name), name)

    def test_stale_call_folders_are_swept(self):
        dead = subprocess.Popen([sys.executable, "-c", "pass"])
        dead.wait()
        tmp = os.path.join(self.tmp, "tmp")
        stale = os.path.join(tmp, "call-%d-job-abc" % dead.pid)
        live = os.path.join(tmp, "call-%d-job-def" % os.getpid())
        for d in (stale, live):
            os.makedirs(d)
            with open(os.path.join(d, "settings-1.json"), "w") as f:
                f.write('{"env": {"ANTHROPIC_AUTH_TOKEN": "secret"}}')
        self.assertEqual(backends.sweep_stale_calls(self.tmp), 1)
        self.assertFalse(os.path.exists(stale))
        self.assertTrue(os.path.exists(live))


class _Redirect(http.server.BaseHTTPRequestHandler):
    seen = []

    def do_POST(self):  # noqa: N802
        self.seen.append(self.headers.get("Authorization"))
        self.send_response(302)
        self.send_header("Location", "http://127.0.0.1:%d/other" % self.server.server_port)
        self.end_headers()

    def do_GET(self):  # noqa: N802
        self.seen.append(self.headers.get("Authorization"))
        body = json.dumps({"choices": [{"message": {"content": "hijacked"}}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


class Http(TmpCase):
    def test_redirects_are_not_followed(self):
        srv = http.server.HTTPServer(("127.0.0.1", 0), _Redirect)
        t = threading.Thread(target=srv.serve_forever, daemon=True)
        t.start()
        try:
            _Redirect.seen = []
            url = "http://127.0.0.1:%d/v1/chat/completions" % srv.server_port
            try:
                http_openai.post_json(url, {"Authorization": "Bearer sk-test-SECRET-0000"}, {"x": 1}, 10,
                                      max_retries=0)
            except Exception:  # noqa: BLE001 - any failure is fine; following the redirect is not
                pass
            self.assertEqual(len(_Redirect.seen), 1, "the redirect target never receives the key")
        finally:
            srv.shutdown()
            srv.server_close()

    def test_plain_http_is_refused_except_localhost(self):
        base = dict(type="openai-chat-http", key_env="UB_TEST_KEY", model="m")
        env = {"UB_TEST_KEY": "k-0123456789"}
        ctx = backends.CallContext(backend_id="x", bcfg=dict(base, url="http://api.example.com/v1"), base_env=env)
        self.assertEqual(http_openai.precheck(ctx)[2]["error_class"], "policy")
        ctx = backends.CallContext(backend_id="x", bcfg=dict(base, url="http://127.0.0.1:9/v1"), base_env=env)
        self.assertIsNone(http_openai.precheck(ctx)[2])


class Parsers(unittest.TestCase):
    def test_deep_nesting_never_raises(self):
        deep = "[" * 5000
        ok, errors, _p = validate.check_contract(deep, {"type": "json"}, ".")
        self.assertFalse(ok)
        self.assertIsNone(claude_cli._find_result(deep))


class Writes(TmpCase):
    def test_split_writes_nothing_when_one_target_is_a_folder(self):
        os.makedirs(os.path.join(self.tmp, "b.md"))
        with self.assertRaises(filesproto.PathError):
            filesproto.write_file_blocks({"a.md": "A\n", "b.md": "B\n"}, self.tmp, None)
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "a.md")))

    def test_reserved_names_with_trailing_space(self):
        for rel in ("CON .md", "conin$.md", "CONOUT$.md"):
            with self.assertRaises(filesproto.PathError, msg=rel):
                filesproto.check_relpath(rel)

    def test_parallel_appends_keep_every_line(self):
        path = os.path.join(self.tmp, "calls.jsonl")
        code = ("import sys, json; sys.path.insert(0, %r)\nfrom ublib import textio\n"
                "for i in range(300): textio.append_line(sys.argv[1], json.dumps({'w': sys.argv[2], 'i': i, "
                "'pad': 'x' * 2000}))\n" % _SCRIPTS)
        ps = [subprocess.Popen([sys.executable, "-c", code, path, str(k)]) for k in range(6)]
        for p in ps:
            p.wait()
        good = 0
        with open(path, encoding="utf-8") as f:
            for line in f:
                json.loads(line)
                good += 1
        self.assertEqual(good, 1800)


class DriverLock(TmpCase):
    def test_only_one_process_acquires(self):
        run = os.path.join(self.tmp, "run")
        os.makedirs(run)
        code = ("import sys, time; sys.path.insert(0, %r)\nfrom ublib.engine import state as st\n"
                "l = st.Lock(sys.argv[1]); t = float(sys.argv[2])\n"
                "while time.time() < t: pass\n"
                "print('1' if l.acquire() else '0'); sys.stdout.flush(); time.sleep(2)\n" % _SCRIPTS)
        import time
        start = time.time() + 1.5
        ps = [subprocess.Popen([sys.executable, "-c", code, run, repr(start)], stdout=subprocess.PIPE)
              for _ in range(4)]
        outs = [p.communicate()[0].decode().strip() for p in ps]
        self.assertEqual(outs.count("1"), 1, outs)

    def test_stale_lock_is_taken_over(self):
        run = os.path.join(self.tmp, "run")
        os.makedirs(os.path.join(run, ".ub"))
        textio.write_json_atomic(os.path.join(run, ".ub", "lock.json"),
                                 {"pid": 999999, "host": "x", "heartbeat_ts": 0})
        lock = st.Lock(run)
        self.assertTrue(lock.acquire())
        self.assertTrue(lock.still_ours())
        lock.release()


if __name__ == "__main__":
    unittest.main()
