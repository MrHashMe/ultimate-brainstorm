"""Shared helpers for the B3 engine unit tests (test_engine_*.py, test_render.py). Owner: B3.

Not a test module (unittest discovery only loads test_*.py); each test file puts this folder on sys.path.
Every test runs with an isolated UB_HOME in a temporary folder and a scrubbed environment. No model CLI and no
network is used: the engine reaches workers only through pipeline.Deps, and these tests pass FakeBatch (jobs are
"answered" in-process) and, where bs.py is not the subject, a fake bs runner.
"""

import copy
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

FIXTURES = os.path.dirname(os.path.abspath(__file__))
KIT = os.path.dirname(os.path.dirname(os.path.dirname(FIXTURES)))
SK = os.path.join(KIT, "skills", "ultimate-brainstorm")
SCRIPTS = os.path.join(SK, "scripts")
TEMPLATES = os.path.join(SK, "templates")
HARNESS = os.path.join(KIT, "tests", "harness")  # stubs.py, the fake-mode responder
for _p in (SCRIPTS, HARNESS):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from ublib import textio  # noqa: E402
from ublib.engine import pipeline  # noqa: E402
from ublib.engine import registry  # noqa: E402
from ublib.engine import state as st  # noqa: E402

FAMS = ("claude", "gpt", "kimi", "glm")
WEB = {"claude": True, "gpt": True, "kimi": False, "glm": False}

_SCRUB_PREFIXES = ("UB_", "ANTHROPIC_", "KIMI_MODEL_", "CLAUDE_CODE_")
_SCRUB_EXACT = ("CLAUDECODE", "OPENAI_API_KEY", "CODEX_HOME", "KIMI_API_KEY", "KIMI_CODE_API_KEY", "ZAI_API_KEY",
                "ZAI_PAYG_API_KEY", "CLAUDE_CONFIG_DIR", "KIMI_CODE_HOME")


def fixture_path(*parts):
    return os.path.join(FIXTURES, *parts)


class EngineTestCase(unittest.TestCase):
    """Temp folder + UB_HOME + scrubbed environment for every test."""

    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix="ub-engine-"))
        self.project = os.path.join(self.tmp, "project")
        os.makedirs(self.project)
        env = dict((k, v) for k, v in os.environ.items()
                   if not k.startswith(_SCRUB_PREFIXES) and k not in _SCRUB_EXACT)
        env["UB_HOME"] = os.path.join(self.tmp, "ub_home")
        self._env = mock.patch.dict(os.environ, env, clear=True)
        self._env.start()
        self.addCleanup(self._env.stop)
        self.addCleanup(shutil.rmtree, self.tmp, True)

    # ------------------------------------------------------------ builders of runs
    def make_ctx(self, mode="standard", variant="product", autopilot="guided", families=FAMS, host="claude",
                 agent="claude-code", topic="shift-swap app for nurses", deps=None, run_name=None, privacy=None,
                 sim=None, web=None):
        root = os.path.join(self.project, "brainstorm")
        run_dir = os.path.join(root, run_name or "2026-09-23-shift-swap-app-nurses")
        os.makedirs(run_dir, exist_ok=True)
        st.ensure_run_dirs(run_dir)
        state = st.new_state(run_dir, topic, agent, host, mode=mode, variant=variant, autopilot=autopilot,
                             runner="python ub.py", project_dir=self.project)
        web = web if web is not None else WEB
        state["families"] = dict((f, {"status": "ok" if f in families else "unavailable",
                                      "backend": ("%s-cli" % f) if f in families else None,
                                      "web": bool(web.get(f)) if f in families else False, "reason": ""})
                                 for f in FAMS)
        if privacy:
            state["privacy"].update(privacy)
        ctx = st.Ctx(run_dir, state, deps or FakeDeps(), sim=sim)
        registry.reseat(ctx)
        return ctx

    def write(self, ctx, rel, text):
        return ctx.write(rel, text)


# ---------------------------------------------------------------- fakes

class FakeBatch(object):
    """Worker stand-in: launch_job answers the job at once (or fails it). outputs: {job id: text} or a callable
    (job) -> text; fail: set of job ids (or a callable) that end with meta status 'failed'; dead: job ids whose worker
    is killed at once (every launch of one is a relaunch, counted like batch._note_relaunch); requests: backend
    requests each launch writes to logs/calls.jsonl (C6; None writes no ledger row). expect_gen is accepted (#5):
    gens[job id] is its outcome generation."""

    RELAUNCH_LIMIT = 3

    def __init__(self, outputs=None, fail=None, running=None, dead=None, requests=None):
        self.outputs = outputs
        self.fail = fail or set()
        self.running = set(running or [])
        self.dead = set(dead or [])
        self.requests = requests
        self.launched = []
        self.relaunches = {}
        self.gens = {}
        self.expected = []

    def _failing(self, job):
        return self.fail(job) if callable(self.fail) else job["id"] in self.fail

    def _ledger(self, job, status):
        if self.requests is None:
            return
        line = {"ts": textio.now_iso(), "id": job["id"], "family": job["family"], "status": status,
                "backend": "fake", "requests": self.requests}
        textio.append_line(os.path.join(job["run"], "logs", "calls.jsonl"), json.dumps(line))

    def job_gen(self, run_dir, job_id):
        return self.gens.get(job_id, 0)

    def reset_relaunch(self, run_dir, job_id):
        self.relaunches.pop(job_id, None)

    def launch_job(self, job_path, expect_gen=None):
        job = textio.read_json(job_path)
        self.expected.append((job["id"], expect_gen))
        self.launched.append(job["id"])
        run_dir = job["run"]
        out = os.path.join(run_dir, *job["out"].split("/"))
        prompt = os.path.join(run_dir, *job["prompt_file"].split("/"))
        sha = textio.sha256_file(prompt)
        os.makedirs(os.path.dirname(out), exist_ok=True)
        if job["id"] in self.dead:
            if self.launched.count(job["id"]) > 1:
                self.relaunches[job["id"]] = self.relaunches.get(job["id"], 0) + 1
            return {"pid": 1, "job_id": job["id"]}
        self.gens[job["id"]] = self.gens.get(job["id"], 0) + 1
        self._ledger(job, "failed" if self._failing(job) else "ok")
        if self._failing(job):
            textio.write_json_atomic(out + ".meta.json", {"id": job["id"], "family": job["family"], "status": "failed",
                                                          "error_class": "internal", "prompt_sha256": sha})
            textio.write_text_atomic(out + ".failed.md", "FAMILY CALL FAILED: fake failure\n")
            return {"pid": 1, "job_id": job["id"]}
        text = self.text_for(job, textio.read_text(prompt))
        textio.write_text_atomic(out, text)
        split = job.get("split")
        if split:
            from ublib import filesproto
            filesproto.split_output(text, os.path.join(run_dir, *split["root"].split("/")), split.get("allowed") or [],
                                    os.path.join(run_dir, *split["status_out"].split("/")) if split.get("status_out")
                                    else None)
        textio.write_json_atomic(out + ".meta.json", {"id": job["id"], "family": job["family"], "status": "ok",
                                                      "prompt_sha256": sha, "provisional": job.get("provisional")})
        return {"pid": 1, "job_id": job["id"]}

    def text_for(self, job, prompt):
        if callable(self.outputs):
            return self.outputs(job)
        if isinstance(self.outputs, dict) and job["id"] in self.outputs:
            return self.outputs[job["id"]]
        return "stub output for %s\n" % job["id"]

    def job_state(self, run_dir, job):
        if isinstance(job, str):
            job = textio.read_json(job)
        if job["id"] in self.running:
            return "running"
        dead = "dead" if job["id"] in self.dead and job["id"] in self.launched else "pending"
        out = os.path.join(run_dir, *job["out"].split("/"))
        prompt = os.path.join(run_dir, *job["prompt_file"].split("/"))
        try:
            meta = textio.read_json(out + ".meta.json")
        except (OSError, ValueError):
            return dead
        sha = textio.sha256_file(prompt) if os.path.exists(prompt) else None
        if meta.get("status") == "ok" and meta.get("prompt_sha256") == sha and os.path.exists(out):
            return "done"
        if meta.get("status") not in (None, "ok") and meta.get("prompt_sha256") == sha:
            return "failed"
        return dead

    def running_jobs(self, run_dir):
        return sorted(self.running)

    def stop_all(self, run_dir, keep=None):
        stopped = set(j for j in self.running if j not in set(keep or ()))
        self.running -= stopped
        self.stopped = getattr(self, "stopped", []) + sorted(stopped)
        return len(stopped)

    def relaunch_count(self, run_dir, job):
        return self.relaunches.get(job["id"] if isinstance(job, dict) else job, 0)


class StubBatch(FakeBatch):
    """A worker stand-in that answers with the harness stubs (when present) and applies the contract like the adapter:
    invalid output ends as meta status 'invalid'; `files` output is split into split.root; JSON is normalized."""

    def __init__(self, fail=None):
        FakeBatch.__init__(self, fail=fail)
        self.invalid = []

    def launch_job(self, job_path, expect_gen=None):
        import stubs
        from ublib import filesproto, validate
        job = textio.read_json(job_path)
        self.launched.append(job["id"])
        run_dir = job["run"]
        out = os.path.join(run_dir, *job["out"].split("/"))
        prompt_path = os.path.join(run_dir, *job["prompt_file"].split("/"))
        prompt = textio.read_text(prompt_path)
        sha = textio.sha256_file(prompt_path)
        os.makedirs(os.path.dirname(out), exist_ok=True)
        status = "ok"
        try:
            if self._failing(job):
                raise RuntimeError("injected failure")
            text = stubs.respond(job, prompt)
            ok, errors, parsed = validate.check_contract(text, job.get("contract") or {"type": "text"}, run_dir)
            if ok and (job.get("contract") or {}).get("type") == "json":
                text = json.dumps(parsed, indent=1) + "\n"
            split = job.get("split")
            if ok and split:
                res = filesproto.split_output(text, os.path.join(run_dir, *split["root"].split("/")),
                                              split.get("allowed") or [],
                                              os.path.join(run_dir, *split["status_out"].split("/"))
                                              if split.get("status_out") else None,
                                              (job.get("contract") or {}).get("required"),
                                              bool((job.get("contract") or {}).get("status_trailer")))
                ok, errors = res["ok"], res["errors"]
            if not ok:
                status = "invalid"
                self.invalid.append((job["id"], errors[:3]))
            else:
                textio.write_text_atomic(out, text)
        except Exception as e:  # noqa: BLE001 - any stub problem is a failed call
            status = "failed"
            self.invalid.append((job["id"], [repr(e)]))
        textio.write_json_atomic(out + ".meta.json", {"schema": 1, "id": job["id"], "family": job["family"],
                                                      "status": status, "prompt_sha256": sha,
                                                      "provisional": bool(job.get("provisional")),
                                                      "error_class": None if status == "ok" else "bad_output"})
        if status != "ok":
            textio.write_text_atomic(out + ".failed.md", "FAMILY CALL FAILED: %s\n" % status)
        line = {"ts": textio.now_iso(), "id": job["id"], "family": job["family"], "status": status,
                "prompt_sha256": sha, "kind": job.get("kind")}
        textio.append_line(os.path.join(run_dir, "logs", "calls.jsonl"), json.dumps(line))
        return {"pid": 1, "job_id": job["id"]}


def real_bs(args, run_dir=None):
    """bs.py (B2) as a subprocess, like pipeline.Deps does by default."""
    return pipeline.Deps().bs(args, run_dir)


def stub_deps():
    return FakeDeps(batch=StubBatch(), bs=real_bs)


def stubs_available():
    return os.path.exists(os.path.join(HARNESS, "stubs.py")) and os.path.exists(os.path.join(SCRIPTS, "bs.py"))


def drive(ctx, steps=None, answers=None, max_cards=400, trace=None):
    """Drive a run in-process like a host until DONE or BLOCKED: HUMAN -> default answer (or answers[gate]); HOST ->
    write every named file and run done; HOST_BATCH -> answer each job with the stubs. Returns the last card."""
    import stubs
    from ublib.engine import gates
    steps = steps or pipeline.load_steps()
    answers = answers or {}
    card = pipeline.advance(ctx, steps, 3600)
    for _ in range(max_cards):
        if trace is not None:
            trace.append((card["type"], card.get("step"), card.get("gate")))
        t = card["type"]
        if t in ("DONE", "BLOCKED"):
            return card
        if t == "AUTO":
            card = pipeline.advance(ctx, steps, 3600)
        elif t == "HUMAN":
            ans = answers.get(card["gate"])
            if callable(ans):
                ans = ans(card)
            card = pipeline.answer_gate(ctx, steps, card["gate"], ans or gates.default_answer(card["gate"]),
                                        by="human" if ans else "auto")
        elif t == "HOST":
            for w in card["task"]["writes"]:
                os.makedirs(os.path.dirname(w), exist_ok=True)
                if not os.path.exists(w) or not os.path.getsize(w):
                    textio.write_text_atomic(w, "{}\n" if w.endswith(".json") else "# host output\n")
            card = pipeline.host_done(ctx, steps, card["step"])
        elif t == "HOST_BATCH":
            for j in card["jobs"]:
                job = textio.read_json(os.path.join(ctx.run_dir, "jobs", j["id"] + ".json"))
                textio.write_text_atomic(j["out"], stubs.respond(job, textio.read_text(j["prompt_file"])))
            card = pipeline.advance(ctx, steps, 3600)
    raise AssertionError("no DONE after %d cards" % max_cards)


def full_auto_ctx(case, mode="standard", variant="product", families=FAMS, host="claude", **kw):
    """A run created like `ub init` would (full-auto, privacy defaults with every vendor saved, so G0 is
    automatic)."""
    st.config_set("privacy_defaults", {"web": True, "vendors": True, "code": False,
                                       "vendor_set": ["anthropic", "moonshot", "openai", "zhipu"]})
    ctx = case.make_ctx(mode=mode, variant=variant, autopilot="full-auto", families=families, host=host,
                        deps=stub_deps(), **kw)
    st.set_step(ctx.state, "0.1", "done", note="run created")
    st.save(ctx.run_dir, ctx.state)
    return ctx


class FakeBs(object):
    """bs.py stand-in: records calls; returns (0, '', '') unless a handler for the command is registered."""

    def __init__(self, handlers=None):
        self.calls = []
        self.handlers = dict(handlers or {})

    def __call__(self, args, run_dir=None):
        self.calls.append(list(args))
        h = self.handlers.get(args[0])
        if h:
            return h(args, run_dir)
        return 0, "", ""


def FakeDeps(batch=None, bs=None, detect=None, cfg=None):
    clock = {"t": 1000.0}

    def now():
        return clock["t"]

    def sleep(s):
        clock["t"] += s
    return pipeline.Deps(batch=batch or FakeBatch(), bs=bs or FakeBs(), detect=detect,
                         families_cfg=cfg if cfg is not None else {"defaults": {"parallel": 4, "retries": 1},
                                                                    "families": {}},
                         now=now, sleep=sleep)


def fake_detect(available=FAMS, host_family="claude", web=None):
    web = web if web is not None else WEB

    def detect(live=False, only=None):
        fams = {}
        for f in FAMS:
            ok = f in available
            fams[f] = {"available": ok, "backend": "stub" if ok else None, "chain": ["stub"] if ok else [],
                       "web": bool(web.get(f)) if ok else False, "notes": [] if ok else ["%s not set up" % f]}
        return {"schema": 1, "host": {"family": host_family, "source": "default"}, "families": fams}
    return detect


def deepcopy(x):
    return copy.deepcopy(x)


def read_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)
