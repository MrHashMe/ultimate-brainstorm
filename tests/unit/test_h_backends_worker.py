"""H: worker-side follow-ups of the round-3 review (reviewer claims on the launcher sweep, `ub stop` and the process
seam).

- The launcher-file sweeps (ublib.backends and profiles/launch.py) kept a dead launcher's provider-token file whenever
  the process now holding its pid had a different `ps` identity, "because a ps start time depends on the caller's
  time zone". proc._ps_start runs ps in UTC, so a `ps` identity is as exact as the Windows and Linux ones: on macOS a
  reused pid no longer keeps the file.
- `ub stop` kept the marker of a dead worker whose pid Windows had reused for a process this user cannot read (a
  service, another user's program) and told the user to stop that process by hand. A worker always runs as this user,
  so an identity this user cannot read, while identities are readable here, is another process: the marker goes.
- The process seam of KIT_SPEC 12 (ublib.proc.run) is documented with on_line, which every CLI backend passes.
Process state is mocked at ublib.proc."""

import importlib.util
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

_KIT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_SCRIPTS = os.path.join(_KIT, "skills", "ultimate-brainstorm", "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

from ublib import backends, batch, proc, textio  # noqa: E402

PID = 4242
NAME = "launch-%d-0123456789ab.json" % PID


def load_launch():
    spec = importlib.util.spec_from_file_location("ub_launch_h", os.path.join(_KIT, "profiles", "launch.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class PsIdentityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ub-h-sweep-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.path = os.path.join(self.tmp, NAME)
        with open(self.path, "w", encoding="utf-8") as f:
            f.write('{"env": {"ANTHROPIC_AUTH_TOKEN": "secret"}}\n')

    def gone(self, recorded, now):
        with open(self.path + ".id", "w", encoding="utf-8") as f:
            f.write(recorded + "\n")
        launch = load_launch()
        with mock.patch.object(proc, "pid_alive", return_value=True), \
                mock.patch.object(proc, "process_identity", return_value=now), \
                mock.patch.object(proc, "process_start_time", return_value=None):
            return (backends._launcher_gone(PID, self.path, 0.0), launch._launcher_gone(PID, self.path, 0.0))

    def test_a_reused_pid_with_another_ps_identity_is_swept(self):
        self.assertEqual(self.gone("ps:Fri Sep 25 09:00:00 2026", "ps:Sat Sep 26 10:00:00 2026"), (True, True))

    def test_the_same_ps_identity_keeps_the_file(self):
        self.assertEqual(self.gone("ps:Fri Sep 25 09:00:00 2026", "ps:Fri Sep 25 09:00:00 2026"), (False, False))

    def test_identities_of_different_kinds_are_not_compared(self):
        self.assertEqual(self.gone("linux:b:10", "ps:Fri Sep 25 09:00:00 2026"), (False, False))


class StopForeignProcessTests(unittest.TestCase):
    """A leftover marker (its worker was killed hard) whose pid now belongs to a process this user cannot read."""

    DEAD_WORKER = "win:133000000000000000"
    PID = 7331

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ub-h-stop-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.run_dir = os.path.join(self.tmp, "run")
        env = mock.patch.dict(os.environ, {"UB_HOME": os.path.join(self.tmp, "ubhome")})
        env.start()
        self.addCleanup(env.stop)

    def marker(self, pid, **fields):
        path = batch.marker_path(self.run_dir, "4.2-S3")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        data = {"pid": pid, "ident": self.DEAD_WORKER, "started_at": "2026-09-20T10:00:00Z",
                "heartbeat_at": "2026-09-20T10:05:00Z", "attempt": 1, "backend": "codex-cli"}
        data.update(fields)
        for k in [k for k, v in data.items() if v is Ellipsis]:
            del data[k]
        textio.write_json_atomic(path, data)
        return path

    def stop(self, own_identity):
        """ub stop while PID runs and cannot be read; this process's own identity reads as own_identity."""
        def identity(pid):
            return own_identity if pid == os.getpid() else None
        with mock.patch.object(proc, "pid_alive", side_effect=lambda pid: int(pid) in (self.PID, os.getpid())), \
                mock.patch.object(proc, "process_identity", side_effect=identity), \
                mock.patch.object(proc, "kill_tree") as kill:
            res = batch.stop_workers(self.run_dir)
        self.assertFalse(kill.called, "nothing is killed")
        return res

    def test_another_users_process_is_not_a_worker_on_windows_and_linux(self):
        for own in ("win:133000000000000999", "linux:b:4711"):
            path = self.marker(self.PID)
            self.assertEqual(self.stop(own), {"stopped": 0, "unverified": []}, own)
            self.assertFalse(os.path.exists(path), "the marker of a dead worker goes: " + own)

    def test_a_2_0_3_marker_on_another_users_pid_goes_too(self):
        path = self.marker(self.PID, ident=Ellipsis)
        self.assertEqual(self.stop("win:133000000000000999"), {"stopped": 0, "unverified": []})
        self.assertFalse(os.path.exists(path))

    def test_where_identities_cannot_be_read_the_marker_is_kept(self):
        for own in (None, "ps:Fri Sep 25 09:00:00 2026"):  # no identities here; ps (macOS) reads every user's process
            path = self.marker(self.PID)
            self.assertEqual(self.stop(own), {"stopped": 0, "unverified": [self.PID]}, own)
            self.assertTrue(os.path.exists(path), own)
            os.remove(path)

    @unittest.skipUnless(os.name == "nt", "Windows: the System process (pid 4) cannot be opened by a user")
    def test_a_real_system_process(self):
        self.assertTrue(proc.pid_alive(4))
        self.assertIsNone(proc.process_identity(4))
        path = self.marker(4)
        self.assertEqual(batch.stop_workers(self.run_dir), {"stopped": 0, "unverified": []})
        self.assertFalse(os.path.exists(path))


class SeamDocTests(unittest.TestCase):
    def test_the_documented_process_seam_is_proc_run(self):
        import inspect
        import re
        with open(os.path.join(_KIT, "docs", "design", "KIT_SPEC.md"), encoding="utf-8") as f:
            spec = f.read()
        m = re.search(r"mock the process boundary at `ublib\.proc\.run\(([^)]*)\)", spec)
        self.assertTrue(m, "KIT_SPEC 12 names the seam")
        documented = [p.split("=")[0].strip() for p in m.group(1).split(",")]
        self.assertEqual(documented, list(inspect.signature(proc.run).parameters))


if __name__ == "__main__":
    unittest.main()
