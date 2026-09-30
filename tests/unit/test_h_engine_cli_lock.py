"""Phase H, engine CLI: the driver's .ub/lock.json record in an upgrade window with kit 2.0.3 drivers (KIT_SPEC 6.3;
audit item F79 and the reviewer claim on the heartbeat ten years ahead).

- the record is claimed exclusively before run.json is read, so a 2.0.3 driver cannot take the run meanwhile
- its 2.0.3 heartbeat is kept fresh while this kit drives, so a killed holder's record goes stale for 2.0.3 after 120 s
- a record of this kit (it has `since`) is never taken for a 2.0.3 driver; a live 2.0.3 record is never replaced

The 2.0.3 side is the rule of kit 2.0.3's state.Lock, restated here: it creates lock.json with O_EXCL and takes an
existing record only when its heartbeat_ts is more than 120 s old or its pid is dead.
"""

import json
import os
import subprocess
import sys
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fixtures", "engine"))
import engine_testlib as tl  # noqa: E402

from ublib import textio  # noqa: E402
from ublib.engine import state as st  # noqa: E402

sys.path.insert(0, tl.SCRIPTS)
import ub  # noqa: E402

# kit 2.0.3's Lock.acquire on lock.json, as a separate process (it prints what it did)
LEGACY_ACQUIRE = r'''
import json, os, sys, time
sys.path.insert(0, sys.argv[2])
from ublib.proc import pid_alive
path = sys.argv[1]
try:
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_BINARY", 0), 0o644)
except FileExistsError:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    age = time.time() - float(data.get("heartbeat_ts", 0) or 0)
    print("refused" if age <= 120 and pid_alive(data.get("pid", -1)) else "stale")
    sys.exit(0)
with os.fdopen(fd, "w", encoding="utf-8") as f:
    f.write(json.dumps({"pid": os.getpid(), "host": "codex", "heartbeat_at": "", "heartbeat_ts": time.time()}))
print("acquired")
'''

HOLD_AND_WAIT = ("import sys, time\nsys.path.insert(0, %r)\nfrom ublib.engine import state as st\n"
                 "lk = st.DriverLock(sys.argv[1], 'claude-code')\nassert lk.acquire()\n"
                 "(getattr(lk, 'claim', None) or lk.announce)()\n"  # announce: the record before this fix
                 "open(sys.argv[2], 'w').close()\ntime.sleep(600)\n" % tl.SCRIPTS)


def legacy_takes(rec, now):
    """Whether a 2.0.3 driver takes this record at `now` (its holder() rule), the pid aside."""
    return now - float(rec.get("heartbeat_ts", 0) or 0) > 120


def wait_for(path, proc, timeout=60):
    end = time.monotonic() + timeout
    while not os.path.exists(path):
        if proc.poll() is not None or time.monotonic() > end:
            raise AssertionError("the helper never reached its barrier")
        time.sleep(0.02)


class Base(tl.EngineTestCase):
    def run_dir(self):
        ctx = self.make_ctx()
        st.save(ctx.run_dir, ctx.state)
        return ctx.run_dir

    def live_process(self):
        p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
        self.addCleanup(lambda: (p.kill(), p.wait()))
        return p


class Claim(Base):
    def test_a_2_0_3_driver_cannot_take_the_run_while_run_json_is_read(self):
        """F79: a 2.0.3 driver that tries while this command reads run.json (lock.json not yet written on T0) must
        find a live record; before, it created its own, and both drove the run."""
        run = self.run_dir()
        info = os.path.join(run, ".ub", "lock.json")
        seen = []
        real = ub.load_ctx

        def load_ctx(*a, **kw):
            if not seen:
                seen.append(subprocess.run([sys.executable, "-c", LEGACY_ACQUIRE, info, tl.SCRIPTS],
                                           capture_output=True, text=True, timeout=120).stdout.strip())
            return real(*a, **kw)
        with mock.patch.object(ub, "load_ctx", load_ctx):
            out = ub.with_run(run, tl.FakeDeps(), lambda ctx, lock: lock.holder())
        self.assertEqual(seen, ["refused"])
        self.assertEqual(out["pid"], os.getpid())
        self.assertFalse(os.path.exists(info), "the record outlived the command")

    def test_a_live_2_0_3_record_is_never_replaced(self):
        run = self.run_dir()
        p = self.live_process()
        info = os.path.join(run, ".ub", "lock.json")
        rec = {"pid": p.pid, "host": "codex", "heartbeat_at": textio.now_iso(), "heartbeat_ts": time.time()}
        textio.write_json_atomic(info, rec)
        lock = st.DriverLock(run, "claude-code")
        self.assertTrue(lock.acquire())
        try:
            self.assertEqual(lock.claim(), rec)
        finally:
            lock.release()
        self.assertEqual(textio.read_json(info), rec)

    def test_a_gone_holders_record_is_replaced(self):
        """A record of this kit whose holder died (the kernel lock is ours now) and a stale 2.0.3 record."""
        run = self.run_dir()
        p = self.live_process()
        info = os.path.join(run, ".ub", "lock.json")
        for rec in ({"pid": p.pid, "host": "codex", "since": "2026-01-01T00:00:00Z", "heartbeat_ts": time.time()},
                    {"pid": p.pid, "host": "codex", "heartbeat_ts": time.time() - 121}):
            textio.write_json_atomic(info, rec)
            lock = st.DriverLock(run, "claude-code")
            self.assertTrue(lock.acquire())
            try:
                self.assertIsNone(lock.claim())
                mine = textio.read_json(info)
                self.assertEqual((mine["pid"], mine["host"]), (os.getpid(), "claude-code"))
                self.assertIn("since", mine)
            finally:
                lock.release()
            self.assertEqual([n for n in os.listdir(os.path.dirname(info)) if n.startswith("lock.json")], [])


class Heartbeat(Base):
    def test_a_killed_holders_record_goes_stale_for_2_0_3(self):
        """The reviewer claim: a hard-killed holder left a heartbeat ten years ahead, so a 2.0.3 driver was refused for
        as long as any process reused its pid. Now the record's heartbeat is at most the last beat, so 2.0.3 takes it
        LEGACY_STALE_S after the kill, even under pid reuse; and it is marked as this kit's (`since`)."""
        run = self.run_dir()
        barrier = os.path.join(self.tmp, "claimed")
        p = subprocess.Popen([sys.executable, "-c", HOLD_AND_WAIT, run, barrier])
        self.addCleanup(lambda: (p.kill(), p.wait()))
        wait_for(barrier, p)
        p.kill()  # hard: no release, the record stays
        p.wait()
        rec = textio.read_json(os.path.join(run, ".ub", "lock.json"))
        self.assertIn("since", rec)
        now = time.time()
        self.assertLessEqual(rec["heartbeat_ts"], now)
        self.assertFalse(legacy_takes(rec, now - 1))  # the 2.0.3 rule while the holder still beat
        self.assertTrue(legacy_takes(rec, now + st.LEGACY_STALE_S + 1))

    def test_the_heartbeat_is_fresh_while_this_kit_drives(self):
        """#79: a 2.0.3 driver judges a record stale after 120 s, so the holder's record is refreshed while it drives
        (every LEGACY_BEAT_S; shortened here), and the beat stops before the record is removed."""
        run = self.run_dir()
        info = os.path.join(run, ".ub", "lock.json")
        with mock.patch.object(st, "LEGACY_BEAT_S", 0.05):
            lock = st.DriverLock(run, "claude-code")
            self.assertTrue(lock.acquire())
            try:
                self.assertIsNone(lock.claim())
                first = None
                end = time.monotonic() + 30
                while True:
                    self.assertLess(time.monotonic(), end, "the heartbeat was never refreshed")
                    beat = textio.read_json_or(info, {})  # {} while a beat replaces the file
                    if first is None:
                        first = beat or None
                    elif beat and beat["heartbeat_ts"] != first["heartbeat_ts"]:
                        break
                    time.sleep(0.02)
                self.assertEqual((beat["pid"], beat["since"]), (os.getpid(), first["since"]))
                self.assertFalse(legacy_takes(beat, time.time()))
                thread = lock._beat[0]
            finally:
                lock.release()
            self.assertFalse(thread.is_alive())
            self.assertFalse(os.path.exists(info))

    def test_a_record_of_this_kit_is_never_a_2_0_3_driver(self):
        """A fresh record of another live process: a 2.0.x driver without `since`; this kit's record (with `since`)
        is decided by the kernel lock alone."""
        run = self.run_dir()
        p = self.live_process()
        info = os.path.join(run, ".ub", "lock.json")
        lock = st.DriverLock(run)
        rec = {"pid": p.pid, "host": "codex", "heartbeat_at": textio.now_iso(), "heartbeat_ts": time.time()}
        textio.write_json_atomic(info, rec)
        self.assertEqual(lock.legacy_holder(), rec)
        textio.write_json_atomic(info, dict(rec, since=textio.now_iso()))
        self.assertIsNone(lock.legacy_holder())


if __name__ == "__main__":
    unittest.main()
