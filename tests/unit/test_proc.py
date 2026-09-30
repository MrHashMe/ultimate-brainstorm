"""Unit tests for ublib.proc (process seam, .cmd argument safety, tree kill) and ublib.redact (KIT_SPEC 3.1, 5.4).

These tests start real child processes (the current Python interpreter only); no model CLI and no network.
"""

import os
import shutil
import sys
import tempfile
import time
import unittest
from unittest import mock

_KIT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_SCRIPTS = os.path.join(_KIT, "skills", "ultimate-brainstorm", "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

from ublib import proc, redact  # noqa: E402

PY = sys.executable


def wait_until(pred, timeout=15.0, step=0.1):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pred():
            return True
        time.sleep(step)
    return pred()


class RunTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ub-proc-")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_result_shape(self):
        r = proc.run([PY, "-c", "print('hi')"], None, None, None, 30)
        self.assertIsInstance(r, proc.ProcResult)
        self.assertEqual(r._fields, ("returncode", "stdout_bytes", "stderr_bytes", "timed_out", "overflow"))
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stdout_bytes.strip(), b"hi")
        self.assertFalse(r.timed_out)
        self.assertFalse(r.overflow)
        self.assertFalse(proc.ProcResult(0, b"", b"", False).overflow, "the four-field seam still builds a result")

    def test_stdin_bytes_roundtrip_utf8(self):
        payload = ("prompt with ${x} and \"quotes\" & pipes | caf\u00e9\n" * 2000).encode("utf-8")
        code = "import sys; d = sys.stdin.buffer.read(); sys.stdout.buffer.write(d[::-1])"
        r = proc.run([PY, "-c", code], cwd=self.tmp, env=None, stdin_bytes=payload, timeout_s=60)
        self.assertEqual(r.returncode, 0, r.stderr_bytes)
        self.assertEqual(r.stdout_bytes, payload[::-1])

    def test_no_stdin_is_devnull(self):
        r = proc.run([PY, "-c", "import sys; print(repr(sys.stdin.read()))"], None, None, None, 30)
        self.assertEqual(r.stdout_bytes.strip(), b"''")

    def test_cwd_env_and_exit_code(self):
        env = dict(os.environ)
        env["UB_JOB_ID"] = "4.2-S3"
        env.pop("UB_SHOULD_NOT_EXIST", None)
        code = ("import os, sys; sys.stdout.write(os.getcwd() + '|' + os.environ.get('UB_JOB_ID', '') + '|' + "
                "str('UB_SHOULD_NOT_EXIST' in os.environ)); sys.stderr.write('err-text'); sys.exit(3)")
        r = proc.run([PY, "-c", code], cwd=self.tmp, env=env, stdin_bytes=None, timeout_s=30)
        self.assertEqual(r.returncode, 3)
        cwd, job, leaked = r.stdout_bytes.decode().split("|")
        self.assertEqual(os.path.normcase(os.path.realpath(cwd)), os.path.normcase(os.path.realpath(self.tmp)))
        self.assertEqual(job, "4.2-S3")
        self.assertEqual(leaked, "False")
        self.assertEqual(r.stderr_bytes, b"err-text")

    def test_minimal_env_still_runs(self):
        env = {"PATH": os.path.dirname(PY), "UB_X": "1"}
        r = proc.run([PY, "-c", "import os; print(os.environ['UB_X'])"], None, env, None, 30)
        self.assertEqual(r.returncode, 0, r.stderr_bytes)
        self.assertEqual(r.stdout_bytes.strip(), b"1")

    def test_resolves_bare_name_on_child_path(self):
        name = os.path.splitext(os.path.basename(PY))[0]
        env = dict(os.environ)
        env["PATH"] = os.path.dirname(PY)
        if os.name == "nt":
            env.pop("Path", None)
        r = proc.run([name, "-c", "print(42)"], None, env, None, 30)
        self.assertEqual(r.stdout_bytes.strip(), b"42")

    def test_not_found(self):
        with self.assertRaises(proc.ExecutableNotFound):
            proc.run(["ub-definitely-not-a-real-exe-9f1c"], None, None, None, 5)
        with self.assertRaises(FileNotFoundError):
            proc.run([os.path.join(self.tmp, "missing.exe")], None, None, None, 5)

    def test_bad_argv_and_env(self):
        with self.assertRaises(TypeError):
            proc.run([], None, None, None, 5)
        with self.assertRaises(TypeError):
            proc.run([PY, 1], None, None, None, 5)
        with self.assertRaises(TypeError):
            proc.run([PY, "-c", "pass"], None, {"PATH": os.environ.get("PATH", ""), "X": 1}, None, 5)

    def test_timeout_kills_the_whole_tree(self):
        pidfile = os.path.join(self.tmp, "grandchild.pid")
        code = ("import subprocess, sys, time\n"
                "g = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'])\n"
                "open(sys.argv[1], 'w').write(str(g.pid))\n"
                "time.sleep(120)\n")
        t0 = time.monotonic()
        r = proc.run([PY, "-c", code, pidfile], cwd=self.tmp, env=None, stdin_bytes=None, timeout_s=3)
        elapsed = time.monotonic() - t0
        self.assertTrue(r.timed_out)
        self.assertNotEqual(r.returncode, 0)
        self.assertLess(elapsed, 60)
        self.assertTrue(os.path.exists(pidfile), "grandchild never started")
        with open(pidfile) as f:
            gpid = int(f.read().strip())
        self.assertTrue(wait_until(lambda: not proc.pid_alive(gpid), 15), "grandchild %d survived" % gpid)

    def test_pid_alive(self):
        self.assertTrue(proc.pid_alive(os.getpid()))
        self.assertFalse(proc.pid_alive(0))
        self.assertFalse(proc.pid_alive("x"))
        import subprocess
        p = subprocess.Popen([PY, "-c", "pass"])
        p.wait()
        self.assertTrue(wait_until(lambda: not proc.pid_alive(p.pid), 10))

    def test_kill_tree_on_dead_pid_is_quiet(self):
        import subprocess
        p = subprocess.Popen([PY, "-c", "pass"])
        p.wait()
        proc.kill_tree(p.pid, grace_s=0.5)
        proc.kill_tree(0)


class CmdShimTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ub-cmd-")
        self.cmd = os.path.join(self.tmp, "fake.cmd")
        with open(self.cmd, "w", newline="\r\n") as f:
            f.write("@echo off\necho ARGS:%1:%2\n")
        if os.name != "nt":
            os.chmod(self.cmd, 0o755)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_check_cmd_args_rejects_each_metachar(self):
        for ch in '"&|<>^%!\r\n':
            with self.assertRaises(proc.UnsafeArgument, msg=repr(ch)):
                proc.check_cmd_args("C:/x/claude.CMD", ["-p", "a%sb" % ch])
            with self.assertRaises(proc.UnsafeArgument):
                proc.check_cmd_args("/x/tool.bat", ["a%sb" % ch])

    def test_check_cmd_args_allows_safe_and_non_cmd(self):
        proc.check_cmd_args("C:/x/claude.cmd", ["-p", "Follow the instructions in the piped input exactly.",
                                                "--tools", "", "C:/Users/U/My Folder/x.json", "mcp__*"])
        proc.check_cmd_args("C:/x/claude.exe", ['"&|<>^%!'])
        proc.check_cmd_args("/usr/bin/claude", ["100%"])

    def test_message_names_the_problem_not_the_value(self):
        with self.assertRaises(proc.UnsafeArgument) as cm:
            proc.check_cmd_args("C:/x/kimi.cmd", ["ok", "secret-ish & value"])
        msg = str(cm.exception)
        self.assertIn("argument 2", msg)
        self.assertIn("kimi.cmd", msg)
        self.assertNotIn("secret-ish", msg)

    def test_run_refuses_before_starting(self):
        with mock.patch.object(proc.subprocess, "Popen") as popen:
            with self.assertRaises(proc.UnsafeArgument):
                proc.run([self.cmd, "x & calc"], None, None, None, 5)
            popen.assert_not_called()

    @unittest.skipUnless(os.name == "nt", "real .cmd execution needs Windows")
    def test_real_cmd_runs_with_safe_args(self):
        r = proc.run([self.cmd, "alpha", "beta"], self.tmp, None, None, 30)
        self.assertEqual(r.returncode, 0, r.stderr_bytes)
        self.assertEqual(r.stdout_bytes.strip(), b"ARGS:alpha:beta")

    @unittest.skipUnless(os.name == "nt", "PATHEXT resolution is Windows-only")
    def test_bare_name_resolves_to_cmd(self):
        env = dict(os.environ)
        for k in list(env):
            if k.upper() == "PATH":
                del env[k]
        env["PATH"] = self.tmp
        r = proc.run(["fake", "one"], self.tmp, env, None, 30)
        self.assertEqual(r.stdout_bytes.strip(), b"ARGS:one:")


class RedactTests(unittest.TestCase):
    KEY = "zk-test-0123456789abcdef"

    def test_known_env_value_is_scrubbed(self):
        with mock.patch.dict(os.environ, {"ZAI_API_KEY": self.KEY}):
            out = redact.redact("auth failed for key %s (again %s)" % (self.KEY, self.KEY))
        self.assertNotIn(self.KEY, out)
        self.assertEqual(out.count(redact.MASK), 2)

    def test_custom_secret_name_and_extra_values(self):
        with mock.patch.dict(os.environ, {"MY_SERVICE_TOKEN": "tok-abcdefgh1234"}):
            self.assertIn("tok-abcdefgh1234", redact.known_secret_values())
            self.assertEqual(redact.redact("x tok-abcdefgh1234 y"), "x [REDACTED] y")
        self.assertEqual(redact.redact("v=literal-secret-99", secrets=["literal-secret-99"]), "v=[REDACTED]")

    def test_short_values_not_treated_as_secrets(self):
        with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "abc"}):
            self.assertEqual(redact.redact("abc abc"), "abc abc")

    def test_key_shapes(self):
        self.assertNotIn("sk-ant-abcdefghijklmnopqrstu", redact.redact("key sk-ant-abcdefghijklmnopqrstu end"))
        self.assertEqual(redact.redact("Authorization: Bearer abc.def-123456"), "Authorization: Bearer [REDACTED]")
        self.assertEqual(redact.redact('{"x-api-key": "k-12345678901"}'), '{"x-api-key": "[REDACTED]"}')

    def test_is_secret_name(self):
        for name in ("ZAI_API_KEY", "ANTHROPIC_AUTH_TOKEN", "GH_TOKEN", "db_password", "OPENAI_API_KEY"):
            self.assertTrue(redact.is_secret_name(name), name)
        for name in ("UB_JOB_FILE", "PATH", "token_env", "key_env", "input_tokens", "output_tokens",
                     "CLAUDE_CODE_MAX_CONTEXT_TOKENS", "ANTHROPIC_BASE_URL"):
            self.assertFalse(redact.is_secret_name(name), name)

    def test_redact_obj_meta(self):
        meta = {"cmd": "claude -p x --settings f", "stderr_tail": "401 invalid key %s" % self.KEY,
                "usage": {"input_tokens": 10}, "env": {"ANTHROPIC_AUTH_TOKEN": "whatever-value", "NO_COLOR": "1"},
                "list": [self.KEY, 3, None]}
        with mock.patch.dict(os.environ, {"KIMI_API_KEY": self.KEY}):
            out = redact.redact_obj(meta)
        self.assertNotIn(self.KEY, repr(out))
        self.assertEqual(out["env"]["ANTHROPIC_AUTH_TOKEN"], redact.MASK)
        self.assertEqual(out["env"]["NO_COLOR"], "1")
        self.assertEqual(out["usage"], {"input_tokens": 10})
        self.assertEqual(out["list"][1:], [3, None])
        self.assertIn(self.KEY, meta["stderr_tail"], "input must not be mutated")

    def test_format_cmd(self):
        with mock.patch.dict(os.environ, {"CODEX_API_KEY": self.KEY}):
            s = redact.format_cmd(["codex", "exec", "-C", "C:/tmp/my dir", "--tools", "", "-c", self.KEY])
        self.assertEqual(s, 'codex exec -C "C:/tmp/my dir" --tools "" -c [REDACTED]')


if __name__ == "__main__":
    unittest.main()
