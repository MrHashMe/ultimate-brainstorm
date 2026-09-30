"""WP1a: two sessions on one run, with real `ub.py` processes (KIT_SPEC 6.3, 6.10; audit P1-1, P2-2, P2-12).

Every step waits on observable state (the holder record .ub/lock.json, the terminal's prompt, process exit), never on
a fixed sleep:
- a terminal `ub run` lets go of the driver lock while it waits for the human; a second session answers the gate;
  the terminal's later answer is not applied, nothing is rolled back, the private choice holds, no other vendor runs
- `continue --host` against a live driver changes nothing and is retried by its card; the re-seat then persists
- a hard-killed driver frees the lock at once
- `ub stop` under a live driver: the driver stops at its next poll and relaunches nothing; the agent's next `next`
  keeps the stop, only `continue` lifts it
"""

import json
import os
import subprocess
import sys
import threading
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "harness"))
import e2elib  # noqa: E402
import paths  # noqa: E402
from answerer import ub_args  # noqa: E402
from tmphome import TmpHome  # noqa: E402

from ublib import batch, families  # noqa: E402


class Output(object):
    """Collects a child's stdout from a thread, so the test can wait for a prompt that has no newline."""

    def __init__(self, stream):
        self.chunks = []
        self.thread = threading.Thread(target=self._pump, args=(stream,), daemon=True)
        self.thread.start()

    def _pump(self, stream):
        while True:
            data = stream.read1(4096) if hasattr(stream, "read1") else stream.read(1)
            if not data:
                return
            self.chunks.append(data)

    def text(self):
        return b"".join(self.chunks).decode("utf-8", "replace")

    def wait_for_prompt(self, proc, timeout=300):
        """Until the child printed the stdin prompt '> ' and blocks on it (nothing follows the prompt)."""
        end = time.monotonic() + timeout
        while not self.text().endswith("> "):
            if proc.poll() is not None or time.monotonic() > end:
                raise AssertionError("never saw the prompt; output:\n%s" % self.text()[-3000:])
            time.sleep(0.05)


def start(args, env, cwd, stdin=None):
    """A ub.py process. Its stdout goes to a pipe only when the test writes its stdin (the terminal); otherwise to a
    file, so a full pipe can never block it."""
    stamp = "%d-%d" % (os.getpid(), int(time.time() * 1000))
    err = open(os.path.join(env["TEMP"], "stderr-%s.txt" % stamp), "wb")
    out_path = os.path.join(env["TEMP"], "stdout-%s.txt" % stamp)
    out = subprocess.PIPE if stdin is not None else open(out_path, "wb")
    p = subprocess.Popen([sys.executable, paths.UB_PY] + list(args), env=env, cwd=cwd,
                         stdin=stdin if stdin is not None else subprocess.DEVNULL, stdout=out, stderr=err)
    p.files = [err] + ([out] if out is not subprocess.PIPE else [])
    p.out_path = out_path
    return p


def printed(proc):
    for f in proc.files:
        f.flush()
    return e2elib.read(proc.out_path)


def wait_driving(run, proc, timeout=120):
    """Until the holder record names proc as the run's driver."""
    path = os.path.join(run, ".ub", "lock.json")
    end = time.monotonic() + timeout
    while True:
        try:
            if json.loads(e2elib.read(path)).get("pid") == proc.pid:
                return
        except (OSError, ValueError):
            pass
        if proc.poll() is not None or time.monotonic() > end:
            raise AssertionError("process %s never became the driver (exit %s)" % (proc.pid, proc.poll()))
        time.sleep(0.05)


def events(run, kind):
    path = os.path.join(run, ".ub", "events.jsonl")
    out = []
    for line in e2elib.read(path).split("\n"):
        if line.strip():
            rec = json.loads(line)
            if rec.get("event") == kind:
                out.append(rec)
    return out


class TwoSessions(unittest.TestCase):

    def setUp(self):
        paths.require(paths.UB_PY, paths.PIPELINE_JSON, owner="B3")
        paths.require(os.path.join(paths.KIT, "tests", "harness", "stubs.py"), owner="B4")

    def init(self, th, env, *extra):
        p = e2elib.ub(["init", "--host", "claude-code", "--text", e2elib.TOPIC, "--mode", "quick", "--autopilot",
                       "guided", "--root", th.project, "--no-preflight", "--json"] + list(extra), env, th.project)
        card = paths.last_json(p.out)
        self.assertEqual(card.get("gate"), "G0", paths.describe(p))
        return card["run"]

    def cleanup(self, th, env, run, *procs):
        for p in procs:
            if p.poll() is None:
                p.kill()
            p.wait()
            for f in p.files + ([p.stdout] if p.stdout else []):
                f.close()
        e2elib.ub(["stop", run], env, th.project, timeout=120)

    def test_the_terminal_lets_go_at_a_gate_and_never_rolls_back_another_session(self):
        with TmpHome(tools=()) as th:
            env = e2elib.fake_env(th)
            run = self.init(th, env)
            term = start(["run", "--continue", run], env, th.project, stdin=subprocess.PIPE)
            try:
                out = Output(term.stdout)
                out.wait_for_prompt(term)  # the terminal shows G0 and waits for the human
                answer = os.path.join(th.tmp, "g0.json")
                with open(answer, "w", encoding="utf-8") as f:
                    json.dump({"reply": "go", "private": True}, f)
                b = e2elib.ub(["answer", run, "G0", "--file", answer, "--json"], env, th.project)
                card = paths.last_json(b.out)
                self.assertNotIn("another session is driving", card.get("say") or "",
                                 "the terminal held the driver lock while it waited for input")
                rj = e2elib.run_json(run)
                self.assertEqual((rj["gates"]["G0"]["by"], rj["privacy"]["vendors"]), ("human", False))
                term.stdin.write(b"go\n\n")  # the terminal user answers the G0 prompt still on the screen
                term.stdin.close()
                term.wait(timeout=1200)
                self.assertIn("changed in another session", out.text())
                rj = e2elib.run_json(run)
                self.assertFalse(rj["privacy"]["vendors"], "the terminal rolled the private choice back")
                self.assertEqual(rj["privacy"]["allowed_vendors"], ["anthropic"])
                self.assertEqual(rj["gates"]["G0"]["answer"].get("private"), True)
                self.assertEqual(len([e for e in events(run, "gate_answered") if e.get("gate") == "G0"]), 1)
                other = [c for c in e2elib.calls(run) if families.vendor_of(c.get("family")) != "anthropic"]
                self.assertEqual(other, [], "a model call went to another vendor after the private answer")
                self.assertEqual(e2elib.last_card(run).get("type"), "DONE", out.text()[-2000:])
            finally:
                self.cleanup(th, env, run, term)

    def test_continue_with_another_host_under_a_live_driver_persists(self):
        with TmpHome(tools=()) as th:
            env = e2elib.fake_env(th, UB_STUB_DELAY_S="30")
            run = self.init(th, env)
            e2elib.ub(["answer", run, "G0", "--default", "--json"], env, th.project)  # workers now run 30 s
            a = start(["next", run, "--wait-s", "12", "--json"], env, th.project)
            try:
                wait_driving(run, a)
                env2 = e2elib.fake_env(th, UB_STUB_DELAY_S="30", UB_FAKE_DISABLE="kimi")
                b = e2elib.ub(["continue", run, "--host", "codex", "--json"], env2, th.project)
                card = paths.last_json(b.out)
                self.assertIn("another session is driving", card.get("say") or "", paths.describe(b))
                a.wait(timeout=120)
                self.assertEqual(e2elib.run_json(run)["host"]["agent"], "claude-code")
                retry = e2elib.ub(ub_args(card["then"]), env2, th.project)  # the card retries the refused command
                self.assertEqual(retry.returncode, 0, paths.describe(retry))
                rj = e2elib.run_json(run)
                self.assertEqual((rj["host"]["agent"], rj["exec"]["wait_s"]), ("codex", 100),
                                 "the host switch was lost")
                self.assertTrue(rj.get("provisional"), "the re-seat left no PROVISIONAL record")
            finally:
                self.cleanup(th, env, run, a)

    def test_a_killed_driver_frees_the_lock_at_once(self):
        with TmpHome(tools=()) as th:
            env = e2elib.fake_env(th, UB_STUB_DELAY_S="30")
            run = self.init(th, env)
            e2elib.ub(["answer", run, "G0", "--default", "--json"], env, th.project)
            a = start(["next", run, "--wait-s", "60", "--json"], env, th.project)
            try:
                wait_driving(run, a)
                self.assertTrue(batch.lock_state(run, "_driver"), "the driver holds no OS lock")
                a.kill()  # TerminateProcess / SIGKILL: no cleanup runs
                a.wait()
                t0 = time.monotonic()
                lk = batch.JobLock(run, "_driver")
                while not lk.try_acquire():
                    self.assertLess(time.monotonic() - t0, 1.0, "the dead driver's lock was not freed")
                    time.sleep(0.01)
                lk.release()
                b = e2elib.ub(["next", run, "--wait-s", "0", "--json"], env, th.project)
                self.assertNotIn("another session is driving", paths.last_json(b.out).get("say") or "")
            finally:
                self.cleanup(th, env, run, a)

    def test_stop_under_a_live_driver_relaunches_nothing(self):
        with TmpHome(tools=()) as th:
            env = e2elib.fake_env(th, UB_STUB_DELAY_S="30")
            run = self.init(th, env)
            e2elib.ub(["answer", run, "G0", "--default", "--json"], env, th.project)
            a = start(["next", run, "--wait-s", "90", "--json"], env, th.project)
            try:
                wait_driving(run, a)
                self.assertTrue(batch.running_jobs(run), "no worker was running before the stop")
                launched = len(events(run, "launch"))
                t0 = time.monotonic()
                stop = e2elib.ub(["stop", run, "--json"], env, th.project, timeout=120)
                self.assertEqual(stop.returncode, 0, paths.describe(stop))
                a.wait(timeout=120)
                self.assertLess(time.monotonic() - t0, 60, "the live driver did not stop at its next poll")
                card = paths.last_json(printed(a))
                self.assertEqual(card.get("type"), "DONE", card)
                self.assertIn("stopped (user)", card.get("show") or "")
                self.assertEqual(len(events(run, "launch")), launched, "a stopped job was launched again")
                rj = e2elib.run_json(run)
                self.assertEqual((rj["status"], rj.get("stopped_reason")), ("stopped", "user"))
                # the agent's own poll (`next`, every AUTO card's `then`) keeps the stop and relaunches nothing
                n = e2elib.ub(["next", run, "--wait-s", "0", "--json"], env, th.project)
                self.assertIn("stopped (user)", (paths.last_json(n.out).get("show") or ""))
                self.assertEqual(e2elib.run_json(run)["status"], "stopped")
                self.assertTrue(os.path.exists(os.path.join(run, ".ub", "STOP")))
                self.assertEqual(len(events(run, "launch")), launched, "`next` relaunched a stopped job")
                # an explicit resume lifts the stop
                c = e2elib.ub(["continue", run, "--json"], env, th.project)
                self.assertNotIn("stopped", (paths.last_json(c.out).get("show") or ""))
                self.assertEqual(e2elib.run_json(run)["status"], "active")
                self.assertFalse(os.path.exists(os.path.join(run, ".ub", "STOP")))
            finally:
                self.cleanup(th, env, run, a)


if __name__ == "__main__":
    unittest.main()
