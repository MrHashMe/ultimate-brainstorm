"""The launcher's token files never outlive the launcher (audit finding #66). Owner: WP7.

- A launch first deletes the token files of launchers that died without any cleanup (their pid is gone, or was reused
  by a process that started later); a live launcher's file is kept.
- SIGTERM (POSIX) and a console close (Windows) delete the files before the launcher ends.
- The console handler deletes the files for close/logoff/shutdown and keeps waiting on Ctrl+Break.
"""

import importlib.util
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "harness"))
import paths  # noqa: E402
import inst  # noqa: E402
from ublib import proc as ubproc  # noqa: E402

TOKEN = "zai-secret-TOKEN-66f0"


def launcher(th, name):
    base = os.path.join(th.ub_home, "bin", name)
    return base + ".cmd" if os.name == "nt" else base


def secret_files(th):
    tmp = os.path.join(th.ub_home, "tmp")
    return sorted(n for n in os.listdir(tmp) if n.startswith(("launch-", "zai-mcp-"))) if os.path.isdir(tmp) else []


def dead_pid():
    p = subprocess.Popen([sys.executable, "-c", "pass"])
    p.wait()
    return p.pid


def wait_for(pred, timeout=60.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if pred():
            return True
        time.sleep(0.05)
    return False


def load_launch():
    spec = importlib.util.spec_from_file_location("ub_launch_wp7", paths.LAUNCH_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class Setup(object):
    def setup_glm(self, th):
        proc = inst.run(th, "install", "--yes", "--agents", "claude-code", "--components", "none")
        self.assertEqual(proc.returncode, 0, paths.describe(proc))
        proc = inst.run(th, "setup-glm", "--launcher", "--yes", env_extra={"ZAI_API_KEY": TOKEN})
        self.assertEqual(proc.returncode, 0, paths.describe(proc))


class Sweep(Setup, unittest.TestCase):
    def setUp(self):
        inst.require_installer()
        paths.require(paths.LAUNCH_PY, owner="B1")

    def test_next_launch_sweeps_dead_launchers_files(self):
        with inst.installer_home(tools=("claude", "node")) as th:
            self.setup_glm(th)
            tmp = th.mkdir("home", ".ultimate-brainstorm", "tmp")
            t0 = time.time()
            gone = dead_pid()
            stale = [th.write(os.path.join(tmp, "launch-%d-0123456789ab.json" % gone), '{"env": {"T": "x"}}\n'),
                     th.write(os.path.join(tmp, "zai-mcp-%d-ba9876543210.json" % gone), "{}\n")]
            for p in stale:  # written before that pid's process ran: a process reusing the pid now started later
                os.utime(p, (t0 - 60, t0 - 60))
            live = th.write(os.path.join(tmp, "launch-%d-00000000abcd.json" % os.getpid()), "{}\n")
            other = th.write(os.path.join(tmp, "call-1-job-x"), "not a launcher file\n")
            proc = paths.run([launcher(th, "claude-glm"), "--version"], env=dict(th.env, ZAI_API_KEY=TOKEN),
                             cwd=th.project)
            self.assertEqual(proc.returncode, 0, paths.describe(proc))
            for p in stale:
                self.assertFalse(os.path.exists(p), "a dead launcher's token file is swept: %s" % p)
            self.assertTrue(os.path.isfile(live), "a live launcher's file is never touched")
            self.assertTrue(os.path.isfile(other))
            self.assertEqual(secret_files(th), [os.path.basename(live)])

    def test_console_handler(self):
        mod = load_launch()
        with tempfile.TemporaryDirectory() as d:
            files = [os.path.join(d, n) for n in ("launch-1-aaaaaaaaaaaa.json", "zai-mcp-1-bbbbbbbbbbbb.json")]
            for p in files:
                with open(p, "w") as f:
                    f.write("secret\n")
            mod._SECRET_FILES[:] = list(files)
            self.assertIs(mod._on_console_event(0), False, "Ctrl+C is left to Python")
            self.assertIs(mod._on_console_event(1), True, "Ctrl+Break: keep waiting for the child")
            self.assertTrue(all(os.path.exists(p) for p in files))
            self.assertIs(mod._on_console_event(2), True)  # CTRL_CLOSE_EVENT
            self.assertFalse([p for p in files if os.path.exists(p)], "the console close deletes the token files")


class AbnormalExit(Setup, unittest.TestCase):
    def setUp(self):
        inst.require_installer()
        paths.require(paths.LAUNCH_PY, owner="B1")

    def start(self, th, **kw):
        th.set_scenario([{"tool": "claude", "action": "sleep", "sleep_s": 120, "then": "exit"}])
        th.clear_log()
        env = dict(th.env, ZAI_API_KEY=TOKEN)
        return subprocess.Popen([launcher(th, "claude-glm"), "--version"], env=env, cwd=th.project,
                                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **kw)

    @unittest.skipIf(os.name == "nt", "SIGTERM is POSIX; the Windows console close is tested below")
    def test_sigterm_deletes_the_token_file(self):
        with inst.installer_home(tools=("claude", "node")) as th:
            self.setup_glm(th)
            p = self.start(th)
            try:
                self.assertTrue(wait_for(lambda: th.fake_calls("claude")), "claude never started")
                self.assertTrue(secret_files(th))
                os.kill(p.pid, signal.SIGTERM)  # the launcher script execs python: this pid is launch.py
                self.assertEqual(p.wait(60), 128 + signal.SIGTERM)
            finally:
                ubproc.kill_tree(p.pid, proc=p)
            self.assertEqual(secret_files(th), [])

    @unittest.skipUnless(os.name == "nt", "the console close event is Windows only")
    def test_console_close_deletes_the_token_file(self):
        with inst.installer_home(tools=("claude", "node")) as th:
            self.setup_glm(th)
            th.set_scenario([{"tool": "claude", "action": "sleep", "sleep_s": 120, "then": "exit"}])
            th.clear_log()
            driver = os.path.join(th.root, "close_driver.py")
            with open(driver, "w", encoding="utf-8") as f:
                f.write(CLOSE_DRIVER)
            result = os.path.join(th.root, "close.json")
            env = dict(th.env, ZAI_API_KEY=TOKEN)
            proc = paths.run([sys.executable, driver, launcher(th, "claude-glm"), th.log, result], env=env,
                             cwd=th.project, timeout=180)
            with open(result, encoding="utf-8") as f:
                res = json.load(f)
            if not res.get("posted"):
                self.skipTest("no console window to close here: %s %s" % (res, paths.describe(proc)))
            self.assertTrue(res.get("started"), res)
            self.assertTrue(res.get("exited"), res)
            self.assertEqual(secret_files(th), [], "the token file is gone after the console closed")


# Runs in its own process: it attaches to the launcher's console, which a test runner must never do itself.
CLOSE_DRIVER = r'''
import ctypes, json, os, subprocess, sys, time
exe, ready, result = sys.argv[1:4]
res = {"started": False, "posted": False, "exited": False}
si = subprocess.STARTUPINFO()
si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
si.wShowWindow = 0
p = subprocess.Popen([exe, "--version"], creationflags=subprocess.CREATE_NEW_CONSOLE, startupinfo=si)
try:
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline and not res["started"]:
        res["started"] = os.path.isfile(ready)  # the child claude runs (and holds its console handler)
        time.sleep(0.05)
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    u = ctypes.WinDLL("user32", use_last_error=True)
    k.GetConsoleWindow.restype = ctypes.c_void_p
    u.PostMessageW.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p, ctypes.c_void_p]
    k.FreeConsole()
    if res["started"] and k.AttachConsole(p.pid):
        hwnd = k.GetConsoleWindow()
        k.FreeConsole()
        res["posted"] = bool(hwnd) and bool(u.PostMessageW(hwnd, 0x0010, None, None))  # WM_CLOSE
    if res["posted"]:
        try:
            p.wait(60)
            res["exited"] = True
        except subprocess.TimeoutExpired:
            pass
finally:
    subprocess.run(["taskkill", "/PID", str(p.pid), "/T", "/F"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    with open(result, "w", encoding="utf-8") as f:
        json.dump(res, f)
'''


if __name__ == "__main__":
    unittest.main()
