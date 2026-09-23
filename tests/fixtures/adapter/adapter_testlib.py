"""Shared helpers for the B2 adapter unit tests (test_family_*.py, test_detect.py, test_batch.py).

Not a test module (unittest discovery only loads test_*.py). Each test file puts this folder on sys.path.
Every test runs with an isolated UB_HOME / CLAUDE_CONFIG_DIR / CODEX_HOME / KIMI_CODE_HOME in a temp folder and a
scrubbed environment. No real model CLI and no network is ever used: CLI calls are mocked at ublib.proc.run (the
single process seam, KIT_SPEC 12.2); the few real subprocesses are the current Python interpreter.
"""

import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

FIXTURES = os.path.dirname(os.path.abspath(__file__))
KIT = os.path.dirname(os.path.dirname(os.path.dirname(FIXTURES)))
SCRIPTS = os.path.join(KIT, "skills", "ultimate-brainstorm", "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

from ublib import proc  # noqa: E402
from ublib import textio  # noqa: E402

# Variables a test run must not inherit from the developer's shell.
_SCRUB_PREFIXES = ("ANTHROPIC_", "KIMI_MODEL_", "UB_", "CLAUDE_CODE_")
_SCRUB_EXACT = ("CLAUDECODE", "OPENAI_API_KEY", "OPENAI_BASE_URL", "CODEX_API_KEY", "CODEX_HOME", "KIMI_API_KEY",
                "KIMI_CODE_API_KEY", "ZAI_API_KEY", "ZAI_PAYG_API_KEY", "Z_AI_API_KEY", "API_TIMEOUT_MS",
                "CLAUDE_CONFIG_DIR", "KIMI_CODE_HOME", "KIMI_SHELL_PATH")


def fixture_path(*parts):
    return os.path.join(FIXTURES, *parts)


def fixture_text(*parts):
    return textio.read_text(fixture_path(*parts))


def fixture_bytes(*parts):
    with open(fixture_path(*parts), "rb") as f:
        return f.read()


def PR(returncode=0, stdout=b"", stderr=b"", timed_out=False):
    if isinstance(stdout, str):
        stdout = stdout.encode("utf-8")
    if isinstance(stderr, str):
        stderr = stderr.encode("utf-8")
    return proc.ProcResult(returncode, stdout, stderr, timed_out)


class FakeRun(object):
    """A side_effect for mock.patch("ublib.proc.run"): records every call and plays scripted responses.

    responses: a list of ProcResult or callables(call_dict) -> ProcResult; the last one repeats.
    Each recorded call: {"argv", "cwd", "env", "stdin", "timeout_s", "cwd_listing"}.
    """

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, argv, cwd=None, env=None, stdin_bytes=None, timeout_s=None):
        call = {"argv": list(argv), "cwd": cwd, "env": dict(env or {}), "stdin": stdin_bytes, "timeout_s": timeout_s,
                "cwd_listing": sorted(os.listdir(cwd)) if cwd and os.path.isdir(cwd) else None}
        self.calls.append(call)
        idx = min(len(self.calls) - 1, len(self.responses) - 1)
        r = self.responses[idx]
        return r(call) if callable(r) else r


def fake_resolve(mapping=None):
    """A replacement for proc.resolve_exe: name -> fake absolute path (".cmd" names allowed)."""
    mapping = dict(mapping or {})

    def resolve(name, env=None):
        if name in mapping:
            return mapping[name]
        if os.path.isabs(str(name)):
            return name
        return os.path.join(os.path.abspath(os.sep), "fakebin", name)
    return resolve


def chain_detect(chains, host_family=None):
    """A minimal detect result for resolve_chain: {family: [backend ids]}."""
    fams = {}
    for f, chain in chains.items():
        fams[f] = {"available": bool(chain), "backend": chain[0] if chain else None, "chain": list(chain),
                   "web": False, "vendor": f, "notes": [] if chain else ["test: unavailable"]}
    return {"schema": 1, "fake": False, "host": {"agent": "other", "family": host_family, "source": "default"},
            "clis": {}, "keys": {}, "families": fams, "reclassified": [], "live": {}}


class AdapterTestCase(unittest.TestCase):
    """Isolated environment + run-folder helpers."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ub-adapter-")
        self.home = os.path.join(self.tmp, "ubhome")
        self.run_dir = os.path.join(self.tmp, "project", "brainstorm", "2026-09-23-test-run")
        os.makedirs(self.run_dir)
        os.makedirs(self.home)
        env = {k: v for k, v in os.environ.items()
               if not (k.upper().startswith(_SCRUB_PREFIXES) or k.upper() in _SCRUB_EXACT)}
        env.update({"UB_HOME": self.home,
                    "CLAUDE_CONFIG_DIR": os.path.join(self.tmp, "claude-config"),
                    "CODEX_HOME": os.path.join(self.tmp, "codex-home"),
                    "KIMI_CODE_HOME": os.path.join(self.tmp, "kimi-home")})
        self._env = mock.patch.dict(os.environ, env, clear=True)
        self._env.start()
        self.addCleanup(self._env.stop)
        self.addCleanup(shutil.rmtree, self.tmp, True)

    # ---- config
    def write_families_override(self, obj):
        textio.write_json_atomic(os.path.join(self.home, "families.json"), obj)

    # ---- runs and jobs
    def make_job(self, job_id="4.2-S3", family="gpt", prompt="Do not load or invoke any skill; this prompt is the "
                 "whole task.\nWrite one sentence about PONG.\n", contract=None, **fields):
        prompt_rel = "prompts/%s.prompt.md" % job_id
        textio.write_text_atomic(os.path.join(self.run_dir, prompt_rel), prompt)
        job = {"schema": 1, "run": textio.to_posix(self.run_dir), "id": job_id, "step": "4.2", "kind": "generator",
               "template": "S3-EDE", "family": family, "tier": "default", "prompt_file": prompt_rel,
               "out": "pool/%s.md" % job_id, "tools": "none", "cwd": "empty", "repo_root": None, "timeout_s": 60,
               "retries": 1, "contract": contract or {"type": "text", "min_chars": 5}, "schema_file": None,
               "split": None, "fallback": [], "provisional": False,
               "privacy": {"vendor_ok": True, "web_ok": True, "code_ok": False}, "host_prompt_file": None,
               "stub": {}}
        job.update(fields)
        return job

    def write_job(self, job):
        path = os.path.join(self.run_dir, "jobs", "%s.json" % job["id"])
        textio.write_json_atomic(path, job)
        return path

    def write_run_json(self, **over):
        run = {"schema": 2, "kit_version": "2.0.0", "run": os.path.basename(self.run_dir), "mode": "standard",
               "host": {"agent": "claude-code", "family": "claude", "family_source": "default"},
               "privacy": {"web": True, "vendors": True, "code": False,
                           "allowed_vendors": ["anthropic", "openai", "moonshot", "zhipu"]}}
        for k, v in over.items():
            run[k] = v
        textio.write_json_atomic(os.path.join(self.run_dir, "run.json"), run)
        return run

    def out_path(self, job):
        return os.path.join(self.run_dir, job["out"])

    def read_meta(self, job):
        return textio.read_json(self.out_path(job) + ".meta.json")

    def calls_log(self):
        path = os.path.join(self.run_dir, "logs", "calls.jsonl")
        if not os.path.isfile(path):
            return []
        return [json.loads(line) for line in textio.read_text(path).splitlines() if line.strip()]

    def all_output_text(self):
        """Every file the adapter wrote in the run folder and UB_HOME, concatenated (for secret audits)."""
        chunks = []
        for root in (self.run_dir, self.home):
            for dirpath, _dirs, files in os.walk(root):
                for n in files:
                    try:
                        chunks.append(textio.read_text(os.path.join(dirpath, n)))
                    except OSError:
                        pass
        return "\n".join(chunks)
