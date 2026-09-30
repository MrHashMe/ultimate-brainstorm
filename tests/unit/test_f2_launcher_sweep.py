"""F2 (request X9, reviewer note P3-publish-installer-2): the worker-side sweep of launcher secret files.

ublib.backends.sweep_stale_calls deletes the launch-<pid>-*.json / zai-mcp-<pid>-*.json files (a claude-glm or
claude-kimi session's provider token) of launchers that ended without cleanup. It judged a live launcher by its
wall-clock start time, so a clock step (Linux recomputes btime) or a DST hour could delete the settings file of a
running session. It now uses profiles/launch.py's own rule: the <file>.id the launcher wrote holds its process
identity, and a file goes only when its pid is free or the identity differs (exact kinds only). The .id file goes with
its secret file. Process state is mocked at ublib.proc, except in the live-process test.
"""

import importlib.util
import itertools
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

_KIT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_SCRIPTS = os.path.join(_KIT, "skills", "ultimate-brainstorm", "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

from ublib import backends, proc  # noqa: E402

PID = 4242
NAME = "launch-%d-0123456789ab.json" % PID


def load_launch():
    spec = importlib.util.spec_from_file_location("ub_launch_f2", os.path.join(_KIT, "profiles", "launch.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class SweepCase(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="ub-f2-sweep-")
        self.addCleanup(shutil.rmtree, self.home, True)
        self.tmp = os.path.join(self.home, "tmp")
        os.makedirs(self.tmp)

    def put(self, name=NAME, ident=None):
        path = os.path.join(self.tmp, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write('{"env": {"ANTHROPIC_AUTH_TOKEN": "secret"}}\n')
        if ident is not None:
            with open(path + ".id", "w", encoding="utf-8") as f:
                f.write(ident + "\n")
        return path

    def sweep(self, identity, start_offset=None, alive=True):
        """Sweep with PID alive (or not), holding `identity` now; its start time looks start_offset seconds later than
        the file (a clock step moves it), or is unknown."""
        mtime = os.path.getmtime(os.path.join(self.tmp, NAME)) if os.path.exists(os.path.join(self.tmp, NAME)) else 0
        start = None if start_offset is None else mtime + start_offset
        with mock.patch.object(proc, "pid_alive", return_value=alive), \
                mock.patch.object(proc, "process_identity", return_value=identity), \
                mock.patch.object(proc, "process_start_time", return_value=start):
            return backends.sweep_stale_calls(self.home)

    def left(self):
        return sorted(os.listdir(self.tmp))


class IdentityRule(SweepCase):
    def test_a_live_launchers_file_survives_a_clock_step(self):
        for ident in ("win:133000000000000000", "linux:3f1c:4711", "ps:Sat Sep 26 10:00:00 2026"):
            path = self.put(ident=ident)
            self.assertEqual(self.sweep(ident, start_offset=5.0), 0, ident)
            self.assertEqual(self.left(), [NAME, NAME + ".id"], "the session's settings file must stay: " + ident)
            os.remove(path + ".id")

    def test_a_reused_pid_is_swept_with_its_id_file(self):
        for recorded, now in (("win:1", "win:2"), ("linux:3f1c:10", "linux:3f1c:11"), ("linux:3f1c:10", "linux:9a:10"),
                              ("ps:Sat Sep 26 10:00:00 2026", "ps:Sat Sep 26 11:00:00 2026")):
            self.put(ident=recorded)
            self.assertEqual(self.sweep(now), 1, (recorded, now))  # no start time is needed to see the reuse
            self.assertEqual(self.left(), [], (recorded, now))

    def test_inexact_or_foreign_identities_keep_the_file(self):
        # an identity of another kind cannot be compared (a ps identity is exact: ps runs in UTC)
        for recorded, now in (("linux:3f1c:10", "win:5"), ("win:5", "ps:x")):
            self.put(ident=recorded)
            self.assertEqual(self.sweep(now, start_offset=100.0), 0, (recorded, now))
            self.assertEqual(self.left(), [NAME, NAME + ".id"])

    def test_an_unknown_identity_keeps_the_file(self):
        self.put()
        self.assertEqual(self.sweep(None, start_offset=100.0), 0)
        self.assertEqual(self.left(), [NAME])

    def test_a_file_without_id_uses_the_creation_time_on_windows_only(self):
        self.put()
        self.assertEqual(self.sweep("linux:3f1c:10", start_offset=100.0), 0, "kept while its pid runs")
        self.assertEqual(self.sweep("ps:x", start_offset=100.0), 0, "kept while its pid runs")
        self.assertEqual(self.sweep("win:5", start_offset=0.5), 0, "started before the write")
        self.assertEqual(self.sweep("win:5"), 0, "an unknown creation time keeps the file")
        self.assertEqual(self.sweep("win:5", start_offset=100.0), 1, "a Windows creation time does not move")
        self.assertEqual(self.left(), [])

    def test_a_dead_launchers_file_goes_with_its_id_file(self):
        self.put(ident="win:1")
        self.assertEqual(self.sweep(None, alive=False), 1)
        self.assertEqual(self.left(), [])

    def test_an_orphan_id_file_is_left_to_the_launcher_sweep(self):
        orphan = os.path.join(self.tmp, NAME + ".id")
        with open(orphan, "w", encoding="utf-8") as f:
            f.write("win:1\n")
        self.assertEqual(self.sweep(None, alive=False), 0)
        self.assertEqual(self.left(), [NAME + ".id"])


class SameRuleAsTheLauncher(SweepCase):
    def test_backends_and_launch_py_agree(self):
        launch = load_launch()
        self.assertEqual(launch.IDENT_SUFFIX, backends._LAUNCH_ID_SUFFIX)
        self.assertTrue(launch.SECRET_FILE_RE.match(NAME) and backends._LAUNCH_FILE_RE.match(NAME))
        path = self.put()
        mtime = os.path.getmtime(path)
        idents = (None, "win:1", "win:2", "linux:b:1", "linux:b:2", "ps:a", "ps:b")
        for alive, now, recorded, offset in itertools.product((True, False), idents, idents, (None, 0.5, 100.0)):
            if recorded:
                with open(path + ".id", "w", encoding="utf-8") as f:
                    f.write(recorded + "\n")
            elif os.path.exists(path + ".id"):
                os.remove(path + ".id")
            start = None if offset is None else mtime + offset
            with mock.patch.object(proc, "pid_alive", return_value=alive), \
                    mock.patch.object(proc, "process_identity", return_value=now), \
                    mock.patch.object(proc, "process_start_time", return_value=start):
                self.assertEqual(backends._launcher_gone(PID, path, mtime), launch._launcher_gone(PID, path, mtime),
                                 (alive, now, recorded, offset))


class LiveProcess(SweepCase):
    def test_the_real_identity_of_a_running_launcher_keeps_its_file(self):
        live = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(600)"], stdin=subprocess.DEVNULL)
        self.addCleanup(live.wait)
        self.addCleanup(live.kill)
        ident = proc.process_identity(live.pid)
        if not ident:
            self.skipTest("no process identity on this system")
        name = "zai-mcp-%d-0123456789ab.json" % live.pid
        path = self.put(name, ident=ident)
        mtime = os.path.getmtime(path)
        with mock.patch.object(proc, "process_start_time", return_value=mtime + 5.0):  # the clock stepped forward
            self.assertEqual(backends.sweep_stale_calls(self.home), 0)
        self.assertEqual(self.left(), [name, name + ".id"])


if __name__ == "__main__":
    unittest.main()
