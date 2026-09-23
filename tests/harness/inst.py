"""Helpers for the installer integration tests (KIT_SPEC 4.14, 10, 11.4). Owner: B4.

    with installer_home(("claude", "codex", "kimi", "npx", "node")) as th:
        plan = run_plan(th)                         # plan --json (asserts exit 0 unless exit=... is given)
        rows(plan, agent="kimi", how="copy")
        proc = run(th, "install", "--yes", "--components", "none")

Placeholders used by the golden plan fixtures (tests/fixtures/installer/plans/*.json):
    {root} {home} {ub_home} {kit_dir} {claude_home} {codex_home} {kimi_home} {project}
"""

import contextlib
import json
import os
import re
import shutil

import paths
from tmphome import TmpHome

PLAN_FIXTURES = os.path.join(paths.FIX_INSTALLER, "plans")
SKILL = "ultimate-brainstorm"
MARKER = ".ub-owned"
RUNTIME_EXCLUDE = {".git", "tests", "tools", ".github", ".build", "__pycache__", "dist"}


def require_installer():
    paths.require(paths.INSTALL_PY, paths.TARGETS_JSON, paths.COMPONENTS_JSON, owner="B1")


@contextlib.contextmanager
def installer_home(tools=("claude", "codex", "kimi", "npx", "node"), versions=None, extra_env=None, kimi_login=True,
                   zcode=False, scenario=None):
    with TmpHome(tools=tools, versions=versions, extra_env=extra_env, scenario=scenario) as th:
        if kimi_login and "kimi" in tools:
            th.kimi_login()
        if zcode:
            os.makedirs(os.path.join(th.home, ".zcode"), exist_ok=True)
        yield th


def run(th, *args, **kw):
    """python install/install.py <args...> in the tmphome; returns the process (out/err decoded)."""
    env = dict(th.env)
    env.update(kw.pop("env_extra", None) or {})
    return paths.run_py(kw.pop("script", paths.INSTALL_PY), list(args), env=env, cwd=kw.pop("cwd", th.project),
                        timeout=kw.pop("timeout", 600), input_text=kw.pop("input_text", None))


def run_json(th, *args, **kw):
    expect = kw.pop("exit", 0)
    proc = run(th, *(list(args) + ["--json"]), **kw)
    if expect is not None and proc.returncode != expect:
        raise AssertionError("install.py %s: expected exit %s\n%s" % (" ".join(args), expect, paths.describe(proc)))
    try:
        return paths.last_json(proc.out), proc
    except ValueError:
        raise AssertionError("install.py %s printed no JSON\n%s" % (" ".join(args), paths.describe(proc)))


def run_plan(th, *args, **kw):
    return run_json(th, "plan", *args, **kw)[0]


def rows(plan, **match):
    out = []
    for r in plan.get("rows") or []:
        ok = True
        for k, v in match.items():
            if k == "item_re":
                ok = ok and re.search(v, str(r.get("item") or "")) is not None
            elif r.get(k) != v:
                ok = False
        if ok:
            out.append(r)
    return out


def placeholders(th):
    return {"{root}": th.root, "{home}": th.home, "{ub_home}": th.ub_home,
            "{kit_dir}": os.path.join(th.ub_home, "kit"), "{claude_home}": th.env.get("CLAUDE_CONFIG_DIR", th.claude_home),
            "{codex_home}": th.env.get("CODEX_HOME", th.codex_home),
            "{kimi_home}": th.env.get("KIMI_CODE_HOME", th.kimi_home), "{project}": th.project}


def expand(value, th):
    if isinstance(value, str):
        for k, v in sorted(placeholders(th).items(), key=lambda kv: -len(kv[0])):
            value = value.replace(k, paths.posix(v))
        return value
    if isinstance(value, list):
        return [expand(v, th) for v in value]
    if isinstance(value, dict):
        return {k: expand(v, th) for k, v in value.items()}
    return value


def norm(value):
    """Compare paths case-insensitively on Windows, always with forward slashes."""
    if isinstance(value, str):
        v = value.replace("\\", "/")
        return v.lower() if os.name == "nt" else v
    if isinstance(value, list):
        return [norm(v) for v in value]
    if isinstance(value, dict):
        return {k: norm(v) for k, v in value.items()}
    return value


def subset(expected, actual):
    if isinstance(expected, dict):
        return isinstance(actual, dict) and all(k in actual and subset(v, actual[k]) for k, v in expected.items())
    return norm(expected) == norm(actual)


def load_case(name):
    with open(os.path.join(PLAN_FIXTURES, name + ".json"), "r", encoding="utf-8") as f:
        return json.load(f)


def calls_matching(th, tool, prefix):
    """Fake-log entries of `tool` whose argv starts with `prefix` (paths compared with norm)."""
    out = []
    for c in th.fake_calls(tool):
        if norm(c["argv"][:len(prefix)]) == norm(list(prefix)):
            out.append(c)
    return out


def copy_dest(th, agent):
    base = {"claude-code": os.path.join(th.env.get("CLAUDE_CONFIG_DIR", th.claude_home), "skills"),
            "codex": os.path.join(th.home, ".agents", "skills"),
            "kimi": os.path.join(th.env.get("KIMI_CODE_HOME", th.kimi_home), "skills"),
            "zcode": os.path.join(th.home, ".zcode", "skills")}[agent]
    return os.path.join(base, SKILL)


def read_manifest(th):
    path = os.path.join(th.ub_home, "install-manifest.json")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def kit_source_copy(dest):
    """Copy the kit's runtime files to dest (a --source for update tests); returns dest."""
    def ignore(d, names):
        return [n for n in names if n in RUNTIME_EXCLUDE or n.endswith(".pyc")]
    shutil.copytree(paths.KIT, dest, ignore=ignore)
    return dest


def home_snapshot_ignores():
    """Files the harness itself writes (fake registry, logs) that snapshots of HOME must ignore."""
    return [".fakecli-registry.json", "*.fakecli-hits.json"]


def find_files(root, pattern):
    rx = re.compile(pattern)
    hits = []
    for dirpath, _dirs, files in os.walk(root):
        for n in files:
            p = os.path.join(dirpath, n)
            if rx.search(p.replace("\\", "/")):
                hits.append(p)
    return hits


def read(path):
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return f.read()
