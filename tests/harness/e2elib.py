"""Helpers for the end-to-end dry runs (KIT_SPEC 11.6). Owner: B4 (written at integration).

Every e2e test runs the real engine (`ub.py`) in a TmpHome with `UB_FAKE_FAMILIES=1` (all families via the stub
backend, tests/harness/stubs.py) and detached workers (`UB_NO_DETACH=0`), unless the test says otherwise (E8 uses the real
backends against fake CLIs).
"""

import json
import os
import threading

import paths
from ublib import textio  # paths puts SK/scripts on sys.path

TOPIC = "shift-swap app for nurses"

# Files every finished run has (4.1), per mode family. Paths are relative to the run folder.
COMMON = ("run.json", "00_RUN.md", "PROGRESS.md", "00_HUMAN_SEEDS.md", "01_FRAME.md", "criteria.json",
          "sources.json", "sources.md", "origins.json", "06_TOURNAMENT.md", "tournament/cards.md",
          "tournament/header.md", "tournament/precommit.md", "tournament/result.md", "tournament/result.json",
          "08_DECISION.md", "09_PROBE.md", "12_HANDOFF.md", "logs/calls.jsonl", ".ub/last_card.json",
          "gates/G0.md", "answers/G0.json")
ARCH_COMMON = ("00_BRIEF.md", "brief.json", "drivers.json", "goals-constraints.md", "quality-scenarios.md",
               "context.md", "candidates/map.json", "review/sheet_A.md", "review/sheet_B.md", "tradeoff-matrix.md",
               "matrix.json", "decisions.json", "risks.md", "stack.json", "chosen/stack.md", "chosen/containers.md",
               "chosen/data-model.md", "lint.md", "lint.json", "README.md")
ARCH_FULL = ("premortem.md", "chosen/runtime.md", "chosen/api.md", "chosen/deployment.md",
             "chosen/security-privacy.md", "chosen/cost-model.md", "chosen/deferred.md", "review/sheet_C.md",
             "review/resolution.md")
PROP_COMMON = ("PROPOSAL.md", "ONE-PAGER.md", "assumptions.md", "open-questions.md", "lint.md", "lint.json",
               "index.html", "README.md", "sections/01.md")
PROP_FULL = tuple("sections/%02d.md" % n for n in range(1, 14)) + ("review/redteam.json", "review/resolution.md")
QUICK = ("quick/curated.json", "quick/finalists.json", "QUICK_DECISION.md", "pool/_families.json")
POOLED = ("02_CONTEXT.md", "pool/_families.json", "merges.json", "03_POOL.md", "clusters.json", "coverage.json",
          "04_SHORTLIST.md", "screen/shortlist.json", "05_EVOLVED.md", "07_TOP.md", "07_REDTEAM.md")
PROPOSAL_MODE = ("02_CONTEXT.md", "primary.json", "clusters.json", "05_EVOLVED.md", "07_TOP.md", "07_REDTEAM.md")


def expected_files(mode):
    files = list(COMMON)
    files += ["10_ARCHITECTURE/" + f for f in ARCH_COMMON]
    files += ["11_PROPOSAL/" + f for f in PROP_COMMON]
    if mode == "quick":
        files += list(QUICK)
    else:
        files += ["10_ARCHITECTURE/" + f for f in ARCH_FULL]
        files += ["11_PROPOSAL/" + f for f in PROP_FULL]
        files += list(PROPOSAL_MODE if mode == "proposal" else POOLED)
    if mode == "deep":
        files += ["11_PROPOSAL/PRFAQ.md", "10_ARCHITECTURE/review/sheet_D.md"]
    return files


def fake_env(th, **extra):
    env = dict(th.env)
    env.update({"UB_FAKE_FAMILIES": "1", "UB_NO_DETACH": "0"})
    for k, v in extra.items():
        if v is None:
            env.pop(k, None)
        else:
            env[k] = str(v)
    return env


def ub(args, env, cwd, timeout=1500, input_text=None):
    return paths.run_py(paths.UB_PY, args, env=env, cwd=cwd, timeout=timeout, input_text=input_text)


def run_dirs(root):
    base = os.path.join(root, "brainstorm")
    if not os.path.isdir(base):
        return []
    return sorted(os.path.join(base, d) for d in os.listdir(base)
                  if os.path.isfile(os.path.join(base, d, "run.json")))


def the_run(tc, root):
    runs = run_dirs(root)
    tc.assertEqual(len(runs), 1, "expected exactly one run folder under %s, found %r" % (root, runs))
    return runs[0]


def read(path):
    """A run file's text. Workers and the engine replace run files atomically; textio retries a read that lands in
    such a replace (Windows: PermissionError) instead of failing the test on it."""
    return textio.read_text(path)


def read_json(path):
    """Strict JSON (a corrupt file fails the test), read like read()."""
    return json.loads(read(path))


def run_json(run):
    return read_json(os.path.join(run, "run.json"))


def last_card(run):
    return read_json(os.path.join(run, ".ub", "last_card.json"))


def calls(run):
    path = os.path.join(run, "logs", "calls.jsonl")
    out = []
    if not os.path.isfile(path):
        return out
    for line in read(path).split("\n"):
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except ValueError:
                pass
    return out


def ok_calls(run):
    return [c for c in calls(run) if c.get("status") == "ok"]


def jobs(run):
    d = os.path.join(run, "jobs")
    out = []
    if not os.path.isdir(d):
        return out
    for name in sorted(os.listdir(d)):
        if name.endswith(".json"):
            try:
                out.append(read_json(os.path.join(d, name)))
            except ValueError:
                pass
    return out


def assert_files(tc, run, files):
    missing = [f for f in files if not os.path.isfile(os.path.join(run, f.replace("/", os.sep)))]
    tc.assertFalse(missing, "missing run files: %s" % missing)


def assert_done(tc, proc, run):
    tc.assertEqual(proc.returncode, 0, paths.describe(proc))
    card = last_card(run)
    tc.assertEqual(card.get("type"), "DONE", "last card is not DONE: %r\n%s" % (
        {k: card.get(k) for k in ("type", "step", "say", "error", "fix")}, paths.describe(proc)))
    return card


def no_duplicate_ok(tc, run):
    seen = {}
    dups = []
    for c in ok_calls(run):
        key = (c.get("id"), c.get("prompt_sha256"))
        if key in seen:
            dups.append(key)
        seen[key] = True
    tc.assertFalse(dups, "jobs with status ok recorded twice for the same prompt: %s" % dups[:10])


def parallel(funcs):
    """Run callables in threads; returns their results (exceptions are returned, not raised)."""
    results = [None] * len(funcs)

    def wrap(i, fn):
        try:
            results[i] = fn()
        except BaseException as e:  # noqa: B902 - reported by the caller
            results[i] = e

    threads = [threading.Thread(target=wrap, args=(i, fn)) for i, fn in enumerate(funcs)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return results
