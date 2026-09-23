#!/usr/bin/env python3
"""Run the kit's test suites, each in its own process, and summarize (KIT_SPEC 11.8). Owner: B4.

Usage:
    python tools/ci.py all                    static, unit, integration, e2e (in that order)
    python tools/ci.py unit|static|integration|e2e [...]
    options:
      --strict          missing dependencies fail instead of skip (sets UB_CI_STRICT=1; default on GitHub Actions)
      --lenient         the opposite (sets UB_CI_LENIENT=1), also on CI
      --pattern P       unittest discovery pattern (default test_*.py), e.g. --pattern test_bootstrap.py
      --quiet           print only failures and the summary instead of the full verbose stream
      --timeout S       per-suite timeout in seconds (default: none)
      --failfast        stop each suite at its first failure, and stop after the first failing suite

Each suite runs:  python -m unittest discover -s tests/<suite> -t tests/<suite> -p "<pattern>" -v
with cwd = the kit root and stdin = DEVNULL. Exit code 0 only when every selected suite ran at least one test and
passed; 1 otherwise; 2 on usage errors.
"""

import argparse
import os
import re
import subprocess
import sys
import time

KIT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SUITES = ("static", "unit", "integration", "e2e")
MISSING = "MISSING DEPENDENCY"


def _out(text):
    try:
        sys.stdout.write(text)
    except UnicodeEncodeError:
        sys.stdout.write(text.encode("ascii", "replace").decode("ascii"))
    sys.stdout.flush()


def parse_summary(text):
    res = {"ran": 0, "failures": 0, "errors": 0, "skipped": 0, "expected_failures": 0, "unexpected_successes": 0,
           "seconds": 0.0, "ok": False, "missing": 0, "missing_reasons": []}
    m = None
    for m in re.finditer(r"^Ran (\d+) tests? in ([\d.]+)s", text, re.M):
        pass
    if m:
        res["ran"] = int(m.group(1))
        res["seconds"] = float(m.group(2))
    tail = text[m.end():] if m else text
    fm = re.search(r"^(OK|FAILED)(?: \(([^)]*)\))?\s*$", tail, re.M)
    if fm:
        res["ok"] = fm.group(1) == "OK"
        for part in (fm.group(2) or "").split(","):
            if "=" in part:
                k, v = part.strip().split("=", 1)
                key = k.strip().replace(" ", "_")
                if key in res and v.strip().isdigit():
                    res[key] = int(v.strip())
    reasons = re.findall(r"skipped '(%s[^']*)'" % MISSING, text)
    res["missing"] = len(reasons)
    seen = []
    for r in reasons:
        if r not in seen:
            seen.append(r)
    res["missing_reasons"] = seen
    return res


def run_suite(name, pattern, env, quiet, timeout, failfast):
    start = os.path.join(KIT, "tests", name)
    if not os.path.isdir(start):
        return {"suite": name, "status": "NO SUITE", "rc": 1, "ran": 0, "failures": 0, "errors": 0, "skipped": 0,
                "missing": 0, "missing_reasons": [], "seconds": 0.0}
    argv = [sys.executable, "-m", "unittest", "discover", "-s", start, "-t", start, "-p", pattern, "-v"]
    if failfast:
        argv.append("--failfast")
    _out("\n=== suite %s: %s\n" % (name, " ".join(argv[1:])))
    t0 = time.time()
    proc = subprocess.Popen(argv, cwd=KIT, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT)
    chunks = []
    timed_out = False
    deadline = t0 + timeout if timeout else None
    try:
        for raw in iter(proc.stdout.readline, b""):
            line = raw.decode("utf-8", "replace")
            chunks.append(line)
            if not quiet or re.search(r"\.\.\. (FAIL|ERROR)|^(FAIL|ERROR):|Traceback|^Ran |^OK|^FAILED", line):
                _out(line)
            if deadline and time.time() > deadline:
                timed_out = True
                proc.kill()
                break
        proc.wait()
    finally:
        proc.stdout.close()
    text = "".join(chunks)
    if quiet:
        # show the failure details block at the end of the run
        idx = text.find("\n======")
        if idx >= 0:
            _out(text[idx:])
    res = parse_summary(text)
    res["suite"] = name
    res["rc"] = proc.returncode
    res["seconds"] = round(time.time() - t0, 1)
    if timed_out:
        res["status"] = "TIMEOUT"
    elif res["ran"] == 0:
        res["status"] = "EMPTY"
    elif proc.returncode == 0 and res["ok"]:
        res["status"] = "OK"
    else:
        res["status"] = "FAILED"
    return res


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass
    ap = argparse.ArgumentParser(prog="ci.py", description="Run the kit's test suites.")
    ap.add_argument("suites", nargs="+", choices=SUITES + ("all",))
    ap.add_argument("--strict", action="store_true")
    ap.add_argument("--lenient", action="store_true")
    ap.add_argument("--pattern", default="test_*.py")
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--timeout", type=float, default=0)
    ap.add_argument("--failfast", action="store_true")
    args = ap.parse_args(argv)
    if args.strict and args.lenient:
        ap.error("--strict and --lenient exclude each other")
    selected = []
    for s in args.suites:
        for x in (SUITES if s == "all" else (s,)):
            if x not in selected:
                selected.append(x)
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    if args.strict:
        env["UB_CI_STRICT"] = "1"
        env.pop("UB_CI_LENIENT", None)
    if args.lenient:
        env["UB_CI_LENIENT"] = "1"
        env.pop("UB_CI_STRICT", None)
    strict = env.get("UB_CI_LENIENT") != "1" and (env.get("UB_CI_STRICT") == "1" or
                                                  env.get("CI", "").lower() == "true")
    _out("ultimate-brainstorm ci: python %s, kit %s, strict=%s\n" % (sys.version.split()[0], KIT, strict))
    results = []
    for name in selected:
        res = run_suite(name, args.pattern, env, args.quiet, args.timeout, args.failfast)
        results.append(res)
        if args.failfast and res["status"] != "OK":
            break
    _out("\n=== summary\n")
    _out("%-12s %-9s %6s %5s %5s %5s %8s %8s\n" % ("suite", "result", "tests", "fail", "err", "skip", "missing",
                                                   "seconds"))
    for r in results:
        _out("%-12s %-9s %6d %5d %5d %5d %8d %8.1f\n" % (r["suite"], r["status"], r["ran"], r["failures"],
                                                         r["errors"], r["skipped"], r["missing"], r["seconds"]))
    reasons = []
    for r in results:
        for m in r["missing_reasons"]:
            if m not in reasons:
                reasons.append(m)
    if reasons:
        _out("\nskipped for missing dependencies (these fail under --strict / on CI):\n")
        for m in reasons:
            _out("  - %s\n" % m)
    failed = [r["suite"] for r in results if r["status"] != "OK"]
    if len(results) < len(selected):
        failed += [s for s in selected[len(results):]]
    _out("\n%s\n" % ("ALL SUITES PASSED" if not failed else "FAILED: " + ", ".join(failed)))
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
