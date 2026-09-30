"""Kit paths, dependency checks and small process helpers for the B4 test suites (KIT_SPEC 11).

Test modules are not packages (section 2), so every test file does:

    import os, sys
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "harness"))
    import paths

`paths` then puts SK/scripts and tests/harness on sys.path, so `import ublib` and `import stubs` work.

Missing dependencies. B1, B2 and B3 land in parallel with B4. A test that needs another builder's file calls
`paths.require(path, owner)`. When the file is missing the test is skipped with a reason that starts with
"MISSING DEPENDENCY", which tools/ci.py counts and prints. In strict mode (UB_CI_STRICT=1, `tools/ci.py --strict`, or
GitHub Actions where CI=true, unless UB_CI_LENIENT=1) the same call fails the test instead, so integration and CI never
pass by skipping.
"""

import os
import subprocess
import sys
import unittest

HARNESS = os.path.dirname(os.path.abspath(__file__))
TESTS = os.path.dirname(HARNESS)
KIT = os.path.dirname(TESTS)
SK = os.path.join(KIT, "skills", "ultimate-brainstorm")
SCRIPTS = os.path.join(SK, "scripts")
FIXTURES = os.path.join(TESTS, "fixtures")
FIX_INSTALLER = os.path.join(FIXTURES, "installer")
FIX_E2E = os.path.join(FIXTURES, "e2e")

INSTALL_PY = os.path.join(KIT, "install", "install.py")
TARGETS_JSON = os.path.join(KIT, "install", "targets.json")
COMPONENTS_JSON = os.path.join(KIT, "install", "components.json")
INSTALL_SH = os.path.join(KIT, "install", "install.sh")
INSTALL_PS1 = os.path.join(KIT, "install", "install.ps1")
LAUNCH_PY = os.path.join(KIT, "profiles", "launch.py")
RELEASE_PY = os.path.join(KIT, "tools", "release.py")
VALIDATE_KIT_PY = os.path.join(KIT, "tools", "validate_kit.py")
UB_PY = os.path.join(SCRIPTS, "ub.py")
FAMILY_PY = os.path.join(SCRIPTS, "family.py")
BS_PY = os.path.join(SCRIPTS, "bs.py")
FAMILIES_DEFAULT = os.path.join(SCRIPTS, "families.default.json")
SKILL_MD = os.path.join(SK, "SKILL.md")
PIPELINE_JSON = os.path.join(SCRIPTS, "pipeline.json")
FAKECLI_PY = os.path.join(HARNESS, "fakecli.py")

IS_WINDOWS = os.name == "nt"
MISSING = "MISSING DEPENDENCY"

for _p in (SCRIPTS, HARNESS):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def strict():
    """True when missing dependencies must fail instead of skip."""
    if os.environ.get("UB_CI_LENIENT", "") == "1":
        return False
    if os.environ.get("UB_CI_STRICT", "") == "1":
        return True
    return os.environ.get("CI", "").lower() == "true"


def require(*files, **kw):
    """Skip (or fail in strict mode) unless every file exists. owner="B1|B2|B3" names who builds it."""
    owner = kw.get("owner", "another builder")
    missing = [f for f in files if not os.path.exists(f)]
    if not missing:
        return
    rel = ", ".join(os.path.relpath(f, KIT).replace("\\", "/") for f in missing)
    msg = "%s (%s): %s" % (MISSING, owner, rel)
    if strict():
        raise AssertionError(msg)
    raise unittest.SkipTest(msg)


def require_module(name, owner="B2"):
    """Import SK/scripts/<name> (dotted) or skip/fail like require()."""
    import importlib
    path = os.path.join(SCRIPTS, *name.split(".")) + ".py"
    require(path, owner=owner)
    return importlib.import_module(name)


def posix(path):
    return str(path).replace("\\", "/")


def same_path(a, b):
    if a is None or b is None:
        return False
    na = os.path.normcase(os.path.normpath(str(a).replace("/", os.sep)))
    nb = os.path.normcase(os.path.normpath(str(b).replace("/", os.sep)))
    return na == nb


def run_py(script, args=(), env=None, cwd=None, timeout=300, input_text=None):
    """Run `python <script> <args...>` without a shell. stdin is DEVNULL unless input_text is given."""
    argv = [sys.executable, script] + [str(a) for a in args]
    return run(argv, env=env, cwd=cwd, timeout=timeout, input_text=input_text)


def run(argv, env=None, cwd=None, timeout=300, input_text=None):
    kwargs = dict(cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
    if input_text is None:
        kwargs["stdin"] = subprocess.DEVNULL
    else:
        kwargs["input"] = input_text.encode("utf-8")
    proc = subprocess.run([str(a) for a in argv], **kwargs)
    proc.out = proc.stdout.decode("utf-8", "replace")
    proc.err = proc.stderr.decode("utf-8", "replace")
    return proc


def last_json(text):
    """The last top-level JSON object printed in text (tolerates log lines before it)."""
    import json
    text = text.strip()
    try:
        return json.loads(text)
    except ValueError:
        pass
    dec = json.JSONDecoder()
    found = None
    i = 0
    while i < len(text):
        j = text.find("{", i)
        if j < 0:
            break
        try:
            obj, end = dec.raw_decode(text, j)
        except ValueError:
            i = j + 1
            continue
        found = obj
        i = end
    if found is None:
        raise ValueError("no JSON object in output: %r" % text[-400:])
    return found


def describe(proc):
    """Short failure text for assertion messages."""
    return "exit %s\n--- stdout (tail)\n%s\n--- stderr (tail)\n%s" % (
        proc.returncode, proc.out[-3000:], proc.err[-3000:])
