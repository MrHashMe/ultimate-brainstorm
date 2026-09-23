"""B2 adapter tests: detached workers, running marker + heartbeat, job states, relaunch counter, foreground batch
budget stop, stop_all (KIT_SPEC 4.4 done rule, 4.7). Real worker processes run family.py with the stub backend
(UB_FAKE_FAMILIES=1; ublib.stubs from B4). No model CLI and no network."""

import json
import os
import subprocess
import sys
import time
import unittest

_KIT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(_KIT, "tests", "fixtures", "adapter"))

import adapter_testlib as tl  # noqa: E402
from ublib import batch, proc, textio  # noqa: E402
_KIT_V = open(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "VERSION"),
              encoding="utf-8").read().strip()  # kit version, so a release bump needs no test edits

try:
    from ublib import stubs as _stubs  # noqa: F401  (B4)
    HAVE_STUBS = True
except ImportError:  # pragma: no cover
    HAVE_STUBS = False

FAMILY_PY = os.path.join(tl.SCRIPTS, "family.py")
TEXT = {"type": "text", "min_chars": 5}


def read_marker(path):
    """The marker dict, or {} while it is missing or mid-replace (Windows sharing violation)."""
    try:
        return textio.read_json(path) if os.path.isfile(path) else {}
    except (OSError, ValueError):
        return {}


def wait_until(pred, timeout=30.0, step=0.1):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pred():
            return True
        time.sleep(step)
    return pred()


class BatchBase(tl.AdapterTestCase):
    def setUp(self):
        super(BatchBase, self).setUp()
        os.environ["UB_FAKE_FAMILIES"] = "1"
        os.environ["UB_HEARTBEAT_STALE_S"] = "3"
        self.addCleanup(self._kill_leftovers)

    def _kill_leftovers(self):
        try:
            batch.stop_all(self.run_dir)
        except OSError:
            pass

    def job(self, job_id, **kw):
        job = self.make_job(job_id=job_id, family=kw.pop("family", "claude"), contract=kw.pop("contract", TEXT), **kw)
        path = self.write_job(job)
        job["_path"] = path
        return job, path

    def write_marker(self, job_id, pid, age_s):
        ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - age_s))
        textio.write_json_atomic(batch.marker_path(self.run_dir, job_id),
                                 {"pid": pid, "started_at": ts, "heartbeat_at": ts, "attempt": 1, "backend": "stub"})


class StateTests(BatchBase):
    """job_state without processes: the done rule, markers, failed, pending."""

    def write_done(self, job, text="A valid answer text.", status="ok", sha=None):
        out = self.out_path(job)
        textio.write_text_atomic(out, text)
        prompt = os.path.join(self.run_dir, job["prompt_file"])
        textio.write_json_atomic(out + ".meta.json", {"schema": 1, "id": job["id"], "status": status,
                                                      "prompt_sha256": sha or textio.sha256_file(prompt)})

    def test_pending_done_and_prompt_change(self):
        job, _p = self.job("s1")
        self.assertEqual(batch.job_state(self.run_dir, job), "pending")
        self.write_done(job)
        self.assertEqual(batch.job_state(self.run_dir, job), "done")
        self.assertTrue(batch.is_done(self.run_dir, job))
        # content-addressed: a changed prompt makes the output stale
        textio.write_text_atomic(os.path.join(self.run_dir, job["prompt_file"]), "A different prompt now.\n")
        self.assertEqual(batch.job_state(self.run_dir, job), "pending")

    def test_invalid_out_is_not_done(self):
        job, _p = self.job("s2", contract={"type": "text", "regex": "MUST-APPEAR"})
        self.write_done(job)
        self.assertNotEqual(batch.job_state(self.run_dir, job), "done")

    def test_failed_state(self):
        job, _p = self.job("s3")
        self.write_done(job, status="failed")
        os.remove(self.out_path(job))
        self.assertEqual(batch.job_state(self.run_dir, job), "failed")
        self.write_done(job, status="failed", sha="0" * 64)
        self.assertEqual(batch.job_state(self.run_dir, job), "pending")

    def test_running_and_dead_markers(self):
        job, _p = self.job("s4")
        self.write_marker("s4", os.getpid(), age_s=0)
        self.assertEqual(batch.job_state(self.run_dir, job), "running")
        self.assertEqual(batch.running_jobs(self.run_dir), ["s4"])
        self.write_marker("s4", os.getpid(), age_s=30)  # stale heartbeat (threshold 3 s)
        self.assertEqual(batch.job_state(self.run_dir, job), "dead")
        self.assertEqual(batch.running_jobs(self.run_dir), [])
        dead = subprocess.Popen([sys.executable, "-c", "pass"])
        dead.wait()
        self.write_marker("s4", dead.pid, age_s=0)  # fresh heartbeat but the process is gone
        self.assertEqual(batch.job_state(self.run_dir, job), "dead")

    def test_stale_marker_after_failed_meta_is_failed(self):
        job, _p = self.job("s6")
        dead = subprocess.Popen([sys.executable, "-c", "pass"])
        dead.wait()
        self.write_marker("s6", dead.pid, age_s=30)  # marker from this launch (started 30 s ago), worker gone
        prompt = os.path.join(self.run_dir, job["prompt_file"])
        started = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 5))
        textio.write_json_atomic(self.out_path(job) + ".meta.json",
                                 {"schema": 1, "id": "s6", "status": "failed", "started": started,
                                  "prompt_sha256": textio.sha256_file(prompt)})
        self.assertEqual(batch.job_state(self.run_dir, job), "failed")
        # an older meta (a previous launch) does not hide a worker that died during this launch
        older = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 300))
        textio.write_json_atomic(self.out_path(job) + ".meta.json",
                                 {"schema": 1, "id": "s6", "status": "failed", "started": older,
                                  "prompt_sha256": textio.sha256_file(prompt)})
        self.assertEqual(batch.job_state(self.run_dir, job), "dead")

    def test_path_argument_accepted(self):
        _job, path = self.job("s5")
        self.assertEqual(batch.job_state(self.run_dir, path), "pending")

    def test_stale_threshold_default(self):
        os.environ.pop("UB_HEARTBEAT_STALE_S")
        self.assertEqual(batch.stale_after_s(), 60.0)


@unittest.skipUnless(HAVE_STUBS, "ublib.stubs (B4) not present")
class WorkerTests(BatchBase):
    def test_detached_launch_heartbeat_and_done(self):
        os.environ["UB_STUB_DELAY_S"] = "4"
        job, path = self.job("w1")
        info = batch.launch_job(path)
        self.assertEqual(info["job_id"], "w1")
        self.assertIsInstance(info["pid"], int)
        self.assertIn(batch.job_state(self.run_dir, job), ("running", "done"))
        marker = batch.marker_path(self.run_dir, "w1")
        self.assertTrue(wait_until(lambda: read_marker(marker).get("backend") == "stub", timeout=15),
                        "the worker never recorded its attempt")
        first = read_marker(marker).get("heartbeat_at")
        self.assertTrue(wait_until(lambda: read_marker(marker).get("heartbeat_at") not in (None, first), timeout=6),
                        "heartbeat not refreshed")
        self.assertIn("w1", batch.running_jobs(self.run_dir))
        self.assertTrue(wait_until(lambda: batch.job_state(self.run_dir, job) == "done", timeout=40))
        self.assertTrue(wait_until(lambda: not os.path.exists(marker), timeout=10))
        meta = self.read_meta(job)
        self.assertEqual((meta["status"], meta["backend"]), ("ok", "stub"))
        self.assertTrue(os.path.isfile(os.path.join(self.run_dir, "logs", "w1.log")))
        self.assertEqual(len(self.calls_log()), 1)

    def test_attached_mode(self):
        os.environ["UB_NO_DETACH"] = "1"
        job, path = self.job("w2")
        info = batch.launch_job(path)
        self.assertEqual(info["exit_code"], 0)
        self.assertEqual(batch.job_state(self.run_dir, job), "done")
        self.assertFalse(os.path.exists(batch.marker_path(self.run_dir, "w2")))

    def test_worker_exit_codes(self):
        _job, path = self.job("w3")
        env = dict(os.environ, UB_STUB_FAIL="^w3$")
        rc = subprocess.run([sys.executable, FAMILY_PY, "job", "--job", path], env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE).returncode
        self.assertEqual(rc, 4)
        env = dict(os.environ, UB_FAKE_DISABLE="claude")
        rc = subprocess.run([sys.executable, FAMILY_PY, "job", "--job", path], env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE).returncode
        self.assertEqual(rc, 3)
        bad = os.path.join(self.tmp, "bad.json")
        textio.write_text_atomic(bad, '{"id": "bad id with spaces"}')
        rc = subprocess.run([sys.executable, FAMILY_PY, "job", "--job", bad], env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE).returncode
        self.assertEqual(rc, 2)

    def test_relaunch_counter(self):
        job, path = self.job("w4")
        self.write_marker("w4", 999999, age_s=30)
        self.assertEqual(batch.job_state(self.run_dir, job), "dead")
        self.assertEqual(batch.relaunch_count(self.run_dir, job), 0)
        os.environ["UB_NO_DETACH"] = "1"
        info = batch.launch_job(path)
        self.assertEqual(info["relaunches"], 1)
        self.assertEqual(batch.relaunch_count(self.run_dir, job), 1)
        self.assertEqual(batch.job_state(self.run_dir, job), "done")
        data = textio.read_json(os.path.join(self.run_dir, ".ub", "jobs", "w4.relaunch"))
        self.assertEqual(data["count"], 1)
        # counted per prompt hash: a new prompt starts from zero
        textio.write_text_atomic(os.path.join(self.run_dir, job["prompt_file"]), "Another prompt for PONG.\n")
        self.assertEqual(batch.relaunch_count(self.run_dir, job), 0)

    def test_run_foreground_all_done(self):
        jobs = [self.job("f%d" % i)[0] for i in range(3)]
        res = batch.run_foreground(jobs, parallel=2)
        self.assertEqual(sorted(res["done"]), ["f0", "f1", "f2"])
        self.assertEqual((res["failed"], res["pending"]), ([], []))
        again = batch.run_foreground(jobs, parallel=2)  # cache: nothing re-runs
        self.assertEqual(sorted(again["done"]), ["f0", "f1", "f2"])
        self.assertEqual(len(self.calls_log()), 3)

    def test_run_foreground_failed(self):
        os.environ["UB_STUB_FAIL"] = "^x1$"
        jobs = [self.job("x0")[0], self.job("x1")[0]]
        res = batch.run_foreground(jobs, parallel=2)
        self.assertEqual(res["done"], ["x0"])
        self.assertEqual(res["failed"], ["x1"])

    def test_run_foreground_budget_stop(self):
        os.environ["UB_STUB_DELAY_S"] = "6"
        jobs = [self.job("b%d" % i)[0] for i in range(3)]
        t0 = time.monotonic()
        res = batch.run_foreground(jobs, parallel=1, budget_s=1)
        self.assertLess(time.monotonic() - t0, 5)
        self.assertEqual(res["done"], [])
        self.assertEqual(sorted(res["pending"]), ["b0", "b1", "b2"])
        self.assertTrue(wait_until(lambda: batch.running_jobs(self.run_dir) == ["b0"], timeout=10))

    def test_stop_all_kills_live_workers(self):
        os.environ["UB_STUB_DELAY_S"] = "60"
        job, path = self.job("k1")
        info = batch.launch_job(path)
        self.assertTrue(wait_until(lambda: batch.running_jobs(self.run_dir) == ["k1"], timeout=15))
        self.assertTrue(wait_until(lambda: textio.read_json(batch.marker_path(self.run_dir, "k1")).get("backend")
                                   == "stub", timeout=15))
        pid = textio.read_json(batch.marker_path(self.run_dir, "k1"))["pid"]
        self.assertEqual(batch.stop_all(self.run_dir), 1)
        self.assertTrue(wait_until(lambda: not proc.pid_alive(pid), timeout=15))
        self.assertFalse(proc.pid_alive(info["pid"]) and info["pid"] == pid)
        self.assertEqual(batch.running_jobs(self.run_dir), [])
        self.assertNotEqual(batch.job_state(self.run_dir, job), "done")

    def test_family_batch_cli(self):
        jobs = [self.job("c%d" % i)[1] for i in range(2)]
        jobs_file = os.path.join(self.tmp, "jobs.json")
        textio.write_json_atomic(jobs_file, {"jobs": jobs})
        cp = subprocess.run([sys.executable, FAMILY_PY, "batch", "--jobs", jobs_file, "--json"],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.assertEqual(cp.returncode, 0, cp.stderr)
        res = json.loads(cp.stdout.decode("ascii"))
        self.assertEqual(sorted(res["done"]), ["c0", "c1"])


@unittest.skipUnless(HAVE_STUBS, "ublib.stubs (B4) not present")
class CliTests(tl.AdapterTestCase):
    def run_cli(self, *args, **env):
        e = dict(os.environ)
        e.update(env)
        return subprocess.run([sys.executable, FAMILY_PY] + list(args), env=e, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE)

    def test_version_and_usage(self):
        cp = self.run_cli("--version")
        self.assertEqual(cp.returncode, 0)
        self.assertIn(_KIT_V, cp.stdout.decode())
        self.assertEqual(self.run_cli().returncode, 2)
        self.assertEqual(self.run_cli("call", "--family", "claude").returncode, 2)

    def test_detect_json_fake(self):
        cp = self.run_cli("detect", "--json", UB_FAKE_FAMILIES="1")
        self.assertEqual(cp.returncode, 0)
        res = json.loads(cp.stdout.decode("ascii"))
        self.assertTrue(res["fake"])
        self.assertEqual(res["families"]["gpt"]["chain"], ["stub"])

    def test_call_adhoc(self):
        prompt = os.path.join(self.tmp, "p.md")
        textio.write_text_atomic(prompt, "Reply with the single word PONG.\n")
        out = os.path.join(self.tmp, "adhoc", "o.txt")
        meta_path = os.path.join(self.tmp, "m.json")
        cp = self.run_cli("call", "--family", "gpt", "--prompt-file", prompt, "--out", out, "--contract-json",
                          '{"type":"text","regex":"PONG","min_chars":1}', "--meta", meta_path, "--json",
                          UB_FAKE_FAMILIES="1")
        self.assertEqual(cp.returncode, 0, cp.stderr)
        meta = json.loads(cp.stdout.decode("ascii"))
        self.assertEqual(meta["status"], "ok")
        self.assertTrue(os.path.isfile(out))
        self.assertEqual(textio.read_json(meta_path)["status"], "ok")
        self.assertEqual([n for n in os.listdir(os.path.join(self.home, "tmp")) if n.endswith(".job.json")], [])

    def test_selftest_fake(self):
        cp = self.run_cli("selftest", "--json")
        self.assertEqual(cp.returncode, 0, cp.stdout)
        res = json.loads(cp.stdout.decode("ascii"))
        self.assertEqual(sorted(res["families"]), ["claude", "glm", "gpt", "kimi"])

    def test_explain_never_prints_values(self):
        secret = "zai-explain-secret-0123456789"
        cp = self.run_cli("explain", "--family", "glm", "--json", ZAI_API_KEY=secret)
        self.assertEqual(cp.returncode, 0, cp.stderr)
        out = cp.stdout.decode("ascii")
        self.assertNotIn(secret, out)
        res = json.loads(out)
        self.assertEqual([b["backend"] for b in res["backends"]],
                         ["claude-cli@glm", "codex-cli@glm", "openai-http@glm-payg"])
        self.assertIn("ANTHROPIC_AUTH_TOKEN", res["backends"][0]["settings_env_names"])
        self.assertIn("--settings", res["backends"][0]["argv"])
        cp = self.run_cli("explain", "--family", "kimi", "--tools", "web")
        self.assertEqual(cp.returncode, 0)
        self.assertIn("KIMI_LOOP_MAX_STEPS_PER_TURN", cp.stdout.decode())


if __name__ == "__main__":
    unittest.main()
