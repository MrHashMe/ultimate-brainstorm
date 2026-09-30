"""tools/ci.py --timeout ends a silent hang and its whole process tree (audit finding #74). Owner: WP7.

A test that blocks without printing a newline used to keep ci.py in readline() forever, so --timeout never fired.
"""

import os
import shutil
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "harness"))
import paths  # noqa: E402
from ublib import proc as ubproc  # noqa: E402

HANG_TEST = r'''
import os, subprocess, sys, threading, unittest

class Hang(unittest.TestCase):
    def test_fast(self):
        pass

    def test_silent_hang(self):
        # a grandchild that inherits the output pipe, then a wait that never ends and prints nothing
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(600)"])
        with open(os.environ["WP7_CHILD_PID"], "w") as f:
            f.write(str(child.pid))
        threading.Event().wait()
'''


class CiTimeout(unittest.TestCase):
    def test_silent_hang_is_killed_with_its_tree(self):
        kit = tempfile.mkdtemp(prefix="ub-ci-")
        try:
            os.makedirs(os.path.join(kit, "tools"))
            shutil.copyfile(os.path.join(paths.KIT, "tools", "ci.py"), os.path.join(kit, "tools", "ci.py"))
            os.makedirs(os.path.join(kit, "tests", "unit"))
            with open(os.path.join(kit, "tests", "unit", "test_hang.py"), "w", encoding="utf-8") as f:
                f.write(HANG_TEST)
            pid_file = os.path.join(kit, "child.pid")
            env = dict(os.environ, WP7_CHILD_PID=pid_file)
            for k in ("CI", "UB_CI_STRICT"):
                env.pop(k, None)
            t0 = time.monotonic()
            proc = paths.run([sys.executable, os.path.join(kit, "tools", "ci.py"), "unit", "--timeout", "20",
                              "--quiet"], env=env, cwd=kit, timeout=150)
            took = time.monotonic() - t0
            self.assertEqual(proc.returncode, 1, paths.describe(proc))
            self.assertRegex(proc.out, r"unit\s+TIMEOUT")
            self.assertLess(took, 120, "the timeout fired (a silent hang no longer blocks ci.py)")
            self.assertIn("test_silent_hang", proc.out, "the stack dump names the hanging test")
            with open(pid_file) as f:
                child = int(f.read().strip())
            self.assertFalse(ubproc.pid_alive(child), "the suite's grandchild was killed with the tree")
        finally:
            shutil.rmtree(kit, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
