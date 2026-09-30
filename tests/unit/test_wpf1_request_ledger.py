"""WPF1: the request ledger (contract C6) audited over every backend type and chain shape.

- every logs/calls.jsonl row the adapter writes carries an integer "requests" (the backend requests that attempt
  sent: 0 before any contact, 1 per CLI run, the HTTP requests including the internal retries), and the rows of a job
  add up to its meta "requests";
- a job refused before any attempt writes no row;
- adapter.request_reserve(job, cfg) bounds what one launch can send, for a driver-resolved chain and for the family
  fallback (configured backends that are switched on, plus the native CLIs detection can re-seat there), and the
  bound is reached exactly by the worst case (every attempt of every backend, then the one repair call).
Local 127.0.0.1 HTTP stubs and mocked CLI processes only; the back-off clock is a fake.
"""

import json
import os
import shutil
import sys
import unittest
from unittest import mock

_KIT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(_KIT, "tests", "fixtures", "adapter"))
sys.path.insert(0, os.path.join(_KIT, "tests", "harness"))

import adapter_testlib as tl  # noqa: E402
from http_stub import HttpStub  # noqa: E402
from ublib import adapter, backends, detect, families, proc, textio  # noqa: E402

KEY = "sk-local-test-key-0123456789abcdef"
SUCCESS = tl.fixture_bytes("claude", "success.json")
AUTH = tl.fixture_bytes("claude", "auth.json")
SHELL_EVENT = json.dumps({"type": "item.completed", "item": {"type": "command_execution", "command": "ls"}})


class Clock(object):
    def __init__(self):
        self.t = 1000.0

    def now(self):
        return self.t

    def sleep(self, s):
        self.t += s


class LedgerBase(tl.AdapterTestCase):
    def setUp(self):
        super(LedgerBase, self).setUp()
        os.environ["NO_PROXY"] = os.environ["no_proxy"] = "127.0.0.1,localhost"
        clock = Clock()
        for name, fn in (("_clock", clock.now), ("_sleep", clock.sleep)):
            p = mock.patch.object(backends, name, side_effect=fn)
            p.start()
            self.addCleanup(p.stop)

    def run_chain(self, job, chain, responses=(tl.PR(1, b"", b"unused"),)):
        family = families.split_label(job["family"])[0]
        det = tl.chain_detect({family: list(chain)}, host_family="claude")
        fake = tl.FakeRun(list(responses))
        with mock.patch("ublib.proc.run", side_effect=fake), \
                mock.patch("ublib.proc.resolve_exe", side_effect=tl.fake_resolve()):
            meta = adapter.execute_job(job, detect_result=det)
        return meta, fake

    def rows(self, job_id):
        return [r for r in self.calls_log() if r.get("id") == job_id]

    def check_ledger(self, job, meta, chain, want):
        """want: the requests of each row, in order."""
        rows = self.rows(job["id"])
        for r in rows:
            self.assertIsInstance(r.get("requests"), int, r)
            self.assertNotIsInstance(r.get("requests"), bool, r)
        self.assertEqual([r["requests"] for r in rows], want, [(r["backend"], r["status"]) for r in rows])
        self.assertEqual(meta["requests"], sum(want))
        self.assertLessEqual(meta["requests"], adapter.request_reserve(dict(job, chain=list(chain))))


class RowTests(LedgerBase):
    def test_claude_cli_and_an_unkeyed_http_backend(self):
        job = self.make_job(family="claude", job_id="r-claude")
        meta, _f = self.run_chain(job, ["claude-cli", "anthropic-http"], [tl.PR(1, AUTH)])
        self.assertEqual(meta["status"], "unavailable")
        self.check_ledger(job, meta, ["claude-cli", "anthropic-http"], [1, 0])

    def test_codex_retries_then_http_internal_retries(self):
        os.environ["OPENAI_API_KEY"] = KEY
        with HttpStub([{"status": 529}] * 20) as hs:
            self.write_families_override({"backends": {"openai-http": {"url": hs.url(), "model": "m"}}})
            job = self.make_job(family="gpt", job_id="r-gpt", retries=1)
            meta, fake = self.run_chain(job, ["codex-cli", "openai-http"], [tl.PR(1, b"", b"boom")])
        self.assertEqual((meta["status"], len(fake.calls), len(hs.requests)), ("failed", 2, 6))
        self.check_ledger(job, meta, ["codex-cli", "openai-http"], [1, 1, 3, 3])

    def test_refusals_before_contact_count_zero(self):
        job = self.make_job(family="glm", job_id="r-glm")
        meta, fake = self.run_chain(job, ["claude-cli@glm", "codex-cli@glm", "openai-http@glm-payg"])
        self.assertEqual((meta["status"], fake.calls), ("unavailable", []))
        self.check_ledger(job, meta, ["claude-cli@glm", "codex-cli@glm", "openai-http@glm-payg"], [0, 0, 0])

    def test_a_missing_cli_counts_zero(self):
        job = self.make_job(family="kimi", job_id="r-kimi")

        def missing(argv, **_kw):
            raise proc.ExecutableNotFound("executable not found: kimi")
        meta, _f = self.run_chain(job, ["kimi-cli"], [missing])
        self.check_ledger(job, meta, ["kimi-cli"], [0])

    def test_codex_tool_refusal_and_stdout_overflow_count_one(self):
        job = self.make_job(family="gpt", job_id="r-refused")
        meta, _f = self.run_chain(job, ["codex-cli"], [tl.PR(0, SHELL_EVENT + "\n")])
        self.assertEqual(meta["status"], "refused")
        self.check_ledger(job, meta, ["codex-cli"], [1])
        job = self.make_job(family="kimi", job_id="r-flood")
        meta, _f = self.run_chain(job, ["kimi-cli"], [proc.ProcResult(-9, b"x" * 64, b"", False, True)])
        self.assertEqual(meta["status"], "invalid")
        self.check_ledger(job, meta, ["kimi-cli"], [1])

    def test_repair_rows(self):
        job = self.make_job(family="claude", job_id="r-repair", contract={"type": "text", "regex": "NEVER-MATCHES"})
        meta, _f = self.run_chain(job, ["claude-cli"], [tl.PR(0, SUCCESS)])
        self.assertEqual((meta["status"], meta["attempts"]), ("invalid", 2))
        self.check_ledger(job, meta, ["claude-cli"], [1, 1])

    def test_stub_rows(self):
        job = self.make_job(family="gpt", job_id="r-stub")
        meta, _f = self.run_chain(job, ["stub"])
        self.assertEqual(meta["status"], "ok")
        self.check_ledger(job, meta, ["stub"], [1])

    def test_a_policy_refusal_writes_no_row(self):
        self.write_run_json(privacy={"web": False, "vendors": True, "code": False,
                                     "allowed_vendors": ["anthropic", "openai"]})
        job = self.make_job(family="gpt", job_id="r-policy", tools="web")
        meta, fake = self.run_chain(job, ["codex-cli"])
        self.assertEqual((meta["status"], meta["requests"], fake.calls), ("refused", 0, []))
        self.assertEqual(self.rows("r-policy"), [])


class WorstCaseTests(LedgerBase):
    def test_the_reserve_is_reached_exactly(self):
        """Two HTTP backends, retries 1: 529 on every internal try of every attempt, the last attempt answers
        invalid output, and so does its repair call: (1 + 1) x (3 + 3) + 3 = 15 requests."""
        os.environ["OPENAI_API_KEY"] = os.environ["ANTHROPIC_API_KEY"] = KEY
        rate = {"status": 529}
        script = [rate] * 9 + [rate, rate, {"text": "an answer the contract rejects"}] * 2
        with HttpStub(script) as hs:
            self.write_families_override({"backends": {
                "openai-http": {"url": hs.url(), "model": "m"},
                "anthropic-http": {"url": hs.url("/v1/messages"), "model": "m"}}})
            chain = ["openai-http", "anthropic-http"]
            job = self.make_job(family="claude", job_id="w1", retries=1, timeout_s=600,
                                contract={"type": "text", "regex": "NEVER-MATCHES"})
            meta, _f = self.run_chain(job, chain)
        self.assertEqual((meta["status"], meta["repaired"]), ("invalid", False))
        reserve = adapter.request_reserve(dict(job, chain=chain))
        self.assertEqual(reserve, 15)
        self.assertEqual(len(hs.requests), reserve)
        self.check_ledger(job, meta, chain, [3, 3, 3, 3, 3])


class ReserveShapeTests(tl.AdapterTestCase):
    def reserve(self, **job):
        job.setdefault("retries", 1)
        return adapter.request_reserve(job, families.load_families())

    def test_chain_shapes(self):
        self.assertEqual(self.reserve(family="gpt", chain=["host", "openai-http"]), 2 * 3 + 3)
        self.assertEqual(self.reserve(family="gpt", chain=[]), 0)
        self.assertEqual(self.reserve(family="host"), 0)
        self.assertEqual(self.reserve(family="nobody"), 0)
        self.assertEqual(self.reserve(family="gpt", retries=0, chain=["codex-cli", "openai-http"]), 4 + 3)
        # the kimi fallback: 4 CLI backends + the natives detection can re-seat (claude-cli, codex-cli); the
        # disabled openai-http@kimi sends nothing
        self.assertEqual(self.reserve(family="kimi-alt"), 2 * 6 + 1)
        self.write_families_override({"backends": {"openai-http@kimi": {"enabled": True}}})
        self.assertEqual(self.reserve(family="kimi"), 2 * 9 + 3)

    def test_fake_modes(self):
        os.environ["UB_FAKE_FAMILIES"] = "1"
        self.assertEqual(self.reserve(family="gpt"), 2 + 1)
        os.environ["UB_FAKE_DISABLE"] = "gpt"
        self.assertEqual(self.reserve(family="gpt"), 0)
        os.environ["UB_FAKE_HOST_BACKEND"] = "claude"
        self.assertEqual(self.reserve(family="claude"), 0)

    def test_strict_glm_drops_what_the_worker_drops(self):
        self.write_families_override({"families": {"glm": {"allow_scripted_plan_use": False}}})
        self.assertEqual(self.reserve(family="glm"), 0)
        self.assertEqual(self.reserve(family="glm", chain=["claude-cli@glm", "openai-http@glm-payg"]), 2 * 3 + 3)

    def test_the_fallback_bounds_every_chain_detection_can_resolve(self):
        """Reclassified natives join other families' chains (5.5): the family fallback covers them."""
        for name in ("ZAI_API_KEY", "KIMI_API_KEY", "KIMI_CODE_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY",
                     "ZAI_PAYG_API_KEY"):
            os.environ[name] = KEY
        for p in ("glm", "kimi"):
            os.makedirs(os.path.join(self.home, "codex-homes", p))
        os.makedirs(os.path.join(os.environ["KIMI_CODE_HOME"], "credentials"))
        os.makedirs(os.environ["CLAUDE_CONFIG_DIR"])
        shutil.copy(tl.fixture_path("detect", "claude_settings_zai.json"),
                    os.path.join(os.environ["CLAUDE_CONFIG_DIR"], "settings.json"))
        os.makedirs(os.environ["CODEX_HOME"])
        shutil.copy(tl.fixture_path("detect", "codex_config_kimi.toml"),
                    os.path.join(os.environ["CODEX_HOME"], "config.toml"))
        self.write_families_override({"backends": {b: {"model": "m", "enabled": True} for b in (
            "anthropic-http", "openai-http", "openai-http@kimi", "openai-http@glm-payg")}})
        cfg = families.load_families()

        def resolve(name, env=None):
            return os.path.join(os.path.abspath(os.sep), "fakebin", name + ".exe")
        with mock.patch("ublib.proc.resolve_exe", side_effect=resolve), \
                mock.patch("ublib.proc.run", return_value=tl.PR(0, "2.1.280\n")):
            det = detect.detect(cfg)
        self.assertTrue(det["reclassified"], "the fixture configs re-seat the native CLIs")
        for f in ("claude", "gpt", "kimi", "glm"):
            job = {"family": f, "retries": 1}
            resolved = [b for b in families.resolve_chain(cfg, f, det) if b != "host"]
            self.assertEqual(set(resolved) - set(adapter._chain_ids(job, cfg)), set(), f)
            self.assertLessEqual(adapter.request_reserve(dict(job, chain=resolved), cfg),
                                 adapter.request_reserve(job, cfg), f)


if __name__ == "__main__":
    unittest.main()
