"""Installer recovery after an interrupted apply (audit findings #64, #65). Owner: WP7.

#64 An apply cut short (Ctrl+C, an unexpected error, a hard kill) keeps its ownership records: the manifest and
    install.log are written after every row, a row that raises something else than InstallError/OSError fails alone,
    and a plain re-run records again what the manifest lost, so uninstall removes it.
#65 A killed apply leaves no registrable half copy (SKILL.md is copied last); leftovers are reported by doctor and
    removed by the next install.
"""

import contextlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "harness"))
import paths  # noqa: E402
import inst  # noqa: E402
from ublib import proc as ubproc  # noqa: E402

PLUGIN = "ultimate-brainstorm@ultimate-brainstorm"
SKILL = "ultimate-brainstorm"


def registry(th, tool):
    try:
        with open(os.path.join(th.home, ".fakecli-registry.json"), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {"marketplaces": {}, "plugins": {}}
    out = {"marketplaces": {}, "plugins": {}}
    for key, reg in data.items():
        if key.startswith(tool + "|"):
            out["marketplaces"].update(reg.get("marketplaces", {}))
            out["plugins"].update(reg.get("plugins", {}))
    return out


def entries(th):
    path = os.path.join(th.ub_home, "install-manifest.json")
    if not os.path.isfile(path):
        return None
    return sorted((e.get("agent"), e.get("route")) for e in inst.read_manifest(th).get("entries", []))


def wait_for(pred, timeout=180.0):
    """Poll an observable condition (never a fixed sleep)."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if pred():
            return True
        time.sleep(0.1)
    return False


def load_installer(th):
    spec = importlib.util.spec_from_file_location("ub_install_wp7_%d" % id(th), paths.INSTALL_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def run_in_process(th, argv, patch=None):
    """install.py main(argv) in this process with th's environment; patch(mod) may replace functions first."""
    out, err = io.StringIO(), io.StringIO()
    cwd = os.getcwd()
    with th.patched_environ():
        os.chdir(th.project)
        try:
            mod = load_installer(th)
            if patch:
                patch(mod)
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                rc = mod.main(argv)
        finally:
            os.chdir(cwd)
    return rc, out.getvalue(), err.getvalue()


class InterruptedApply(unittest.TestCase):
    def setUp(self):
        inst.require_installer()

    def test_hard_kill_during_a_component_keeps_the_records(self):
        with inst.installer_home(tools=("claude", "node"), zcode=True) as th:
            th.set_scenario([{"tool": "claude", "argv_regex": "^plugin marketplace add EveryInc/", "action": "sleep",
                              "sleep_s": 300}])
            p = subprocess.Popen([sys.executable, paths.INSTALL_PY, "install", "--yes", "--components", "core",
                                  "--agents", "claude-code,zcode"], env=th.env, cwd=th.project,
                                 stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                started = lambda: [c for c in th.fake_calls("claude")  # noqa: E731
                                   if c["argv"][:3] == ["plugin", "marketplace", "add"] and "EveryInc/" in c["argv"][3]]
                self.assertTrue(wait_for(lambda: started() or p.poll() is not None),
                                "the Compound Engineering component step never started")
                self.assertIsNone(p.poll(), "the installer ended before the component step")
            finally:
                ubproc.kill_tree(p.pid, proc=p)  # a closed terminal: no Python handler runs
            self.assertEqual(entries(th), [("claude-code", "native"), ("zcode", "copy")],
                             "the rows applied before the kill are recorded")
            self.assertTrue(os.path.isfile(os.path.join(th.ub_home, "install.log")), "install.log is written too")
            th.set_scenario([])
            proc = inst.run(th, "uninstall", "--yes")
            self.assertEqual(proc.returncode, 0, paths.describe(proc))
            reg = registry(th, "claude")  # components (Compound Engineering) stay installed by design
            self.assertNotIn(PLUGIN, reg["plugins"])
            self.assertNotIn("ultimate-brainstorm", reg["marketplaces"])
            self.assertFalse(os.path.exists(inst.copy_dest(th, "zcode")))

    def test_rerun_records_what_the_manifest_lost(self):
        with inst.installer_home(tools=("claude", "node"), zcode=True) as th:
            proc = inst.run(th, "install", "--yes", "--components", "none", "--agents", "claude-code,zcode")
            self.assertEqual(proc.returncode, 0, paths.describe(proc))
            os.remove(os.path.join(th.ub_home, "install-manifest.json"))  # what an apply killed early leaves
            plan = inst.run_plan(th, "--components", "none", "--agents", "claude-code,zcode")
            self.assertTrue(any("records it again" in w for w in plan["warnings"]), plan["warnings"])
            proc = inst.run(th, "install", "--yes", "--components", "none", "--agents", "claude-code,zcode")
            self.assertEqual(proc.returncode, 0, paths.describe(proc))
            self.assertEqual(entries(th), [("claude-code", "native"), ("zcode", "copy")])
            dest = inst.copy_dest(th, "zcode")
            copy = [e for e in inst.read_manifest(th)["entries"] if e["route"] == "copy"][0]
            self.assertTrue(copy["files"] and all(len(h) == 64 for h in copy["files"].values()))
            proc = inst.run(th, "uninstall", "--yes")
            self.assertEqual(proc.returncode, 0, paths.describe(proc))
            self.assertFalse(os.path.exists(dest), "the re-recorded copy is removed")
            self.assertEqual(registry(th, "claude")["plugins"], {}, "the re-recorded plugin is removed")

    def test_second_run_writes_nothing_when_the_records_are_complete(self):
        with inst.installer_home(tools=("node",), zcode=True) as th:
            self.assertEqual(inst.run(th, "install", "--yes", "--components", "none").returncode, 0)
            plan = inst.run_plan(th, "--components", "none")
            self.assertFalse([w for w in plan["warnings"] if "records it again" in w], plan["warnings"])
            self.assertTrue(all(r["action"] == "unchanged" for r in plan["rows"]), plan["rows"])

    def test_an_unexpected_error_fails_only_its_row(self):
        with inst.installer_home(tools=("claude", "npx", "node"), zcode=True) as th:
            def patch(mod):
                def boom(ctx, row, updates, result):
                    raise ValueError("argument 2 for npx.cmd contains '&'")  # like proc.UnsafeArgument
                mod.do_component = boom
            rc, out, err = run_in_process(th, ["install", "--yes", "--json", "--components", "core",
                                               "--agents", "claude-code,zcode"], patch)
            self.assertEqual(rc, 1, err)
            plan = paths.last_json(out)
            failed = [r for r in plan["results"] if r["status"] == "failed"]
            self.assertTrue(failed and all("ValueError" in r["detail"] for r in failed), plan["results"])
            self.assertTrue(any(r["status"] == "ok" and r["item"].startswith("launchers") for r in plan["results"]),
                            "the rows after the failed one still ran")
            self.assertEqual(entries(th), [("claude-code", "native"), ("zcode", "copy")])

    def test_one_installer_applies_at_a_time(self):
        with inst.installer_home(tools=("node",), zcode=True) as th:
            with th.patched_environ():
                mod = load_installer(th)
            lock = mod.InstallLock(os.path.join(th.ub_home, "install.lock"))
            self.assertTrue(lock.acquire())
            try:
                proc = inst.run(th, "install", "--yes", "--components", "none")
                self.assertEqual(proc.returncode, 1, paths.describe(proc))
                self.assertIn("another install.py is applying changes", proc.err)
                self.assertFalse(os.path.exists(os.path.join(th.ub_home, "kit")), "nothing was applied")
            finally:
                lock.release()
            proc = inst.run(th, "install", "--yes", "--components", "none")
            self.assertEqual(proc.returncode, 0, paths.describe(proc))

    def test_ctrl_c_keeps_the_records(self):
        with inst.installer_home(tools=("claude", "npx", "node"), zcode=True) as th:
            def patch(mod):
                def interrupted(ctx, row, updates, result):
                    raise KeyboardInterrupt()
                mod.do_component = interrupted
            rc, _out, err = run_in_process(th, ["install", "--yes", "--components", "core",
                                                "--agents", "claude-code,zcode"], patch)
            self.assertEqual(rc, 5, err)
            self.assertEqual(entries(th), [("claude-code", "native"), ("zcode", "copy")])
            self.assertIn("exit=0", inst.read(os.path.join(th.ub_home, "install.log")))


class Leftovers(unittest.TestCase):
    def setUp(self):
        inst.require_installer()

    def test_skill_md_is_copied_last(self):
        with inst.installer_home(tools=("node",)) as th:
            order = []
            with th.patched_environ():
                mod = load_installer(th)
            real = mod.shutil.copy2

            def spy(src, dst, *a, **kw):
                order.append(os.path.basename(dst))
                return real(src, dst, *a, **kw)
            mod.shutil.copy2 = spy
            try:
                src = os.path.join(paths.KIT, "skills", SKILL)
                mod.copy_files(mod.walk_files(src, top_exclude=False), os.path.join(th.root, "copy"))
            finally:
                mod.shutil.copy2 = real
            self.assertGreater(len(order), 10)
            self.assertEqual(order[-1], "SKILL.md", "a copy cut short never holds a SKILL.md")
            self.assertEqual(order.count("SKILL.md"), 1)

    def test_leftovers_are_reported_and_removed(self):
        with inst.installer_home(tools=("node",), zcode=True) as th:
            self.assertEqual(inst.run(th, "install", "--yes", "--components", "none").returncode, 0)
            skills = os.path.dirname(inst.copy_dest(th, "zcode"))
            half = th.write(os.path.join(skills, SKILL + ".ub-new-ab12cd34", "SKILL.md"),
                            "---\nname: ultimate-brainstorm\ndescription: half a copy\n---\n")
            old = th.write(os.path.join(skills, SKILL + ".ub-old-zz99yy88", "x.txt"), "old tree\n")
            kit_new = th.write(os.path.join(th.ub_home, "kit.new-q1w2e3r4", "VERSION"), "2.0.3\n")
            trash = th.write(os.path.join(th.ub_home, "tmp", "old-a1b2c3d4", "y.txt"), "trash\n")
            keep = th.write(os.path.join(skills, SKILL + ".ub-new-NOTOURS", "SKILL.md"), "not a kit name\n")
            proc = inst.run(th, "doctor", "--json")
            checks = paths.last_json(proc.out)["checks"]
            fails = [c for c in checks if c["status"] == "FAIL" and c["id"].startswith("leftover:")]
            self.assertEqual(len(fails), 1, checks)
            self.assertIn(".ub-new-ab12cd34", fails[0]["id"])
            self.assertEqual(proc.returncode, 1)
            plan = inst.run_plan(th, "--components", "none")
            swept = sorted(r["item"] for r in plan["rows"] if r["item"].startswith("installer leftover"))
            self.assertEqual(len(swept), 4, plan["rows"])
            proc = inst.run(th, "install", "--yes", "--components", "none")
            self.assertEqual(proc.returncode, 0, paths.describe(proc))
            for p in (half, old, kit_new, trash):
                self.assertFalse(os.path.exists(os.path.dirname(p)), p)
            self.assertTrue(os.path.isfile(keep), "a name the installer never makes is left alone")
            self.assertTrue(os.path.isfile(os.path.join(inst.copy_dest(th, "zcode"), "SKILL.md")))
            proc = inst.run(th, "doctor", "--json")
            self.assertFalse([c for c in paths.last_json(proc.out)["checks"] if c["id"].startswith("leftover:")])


if __name__ == "__main__":
    unittest.main()
