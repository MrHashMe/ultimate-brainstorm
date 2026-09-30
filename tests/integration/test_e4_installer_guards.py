"""Installer guards that hold between plan and apply, and ownership edge cases (audit findings #64, #67, #68, #69,
reviewer notes P3-publish-installer-0/1). Owner: E4.

#64 / P3-1 install.lock is taken after the plan (and after the confirmation question). Once it is held, the plan is
    checked again: another installer that applied meanwhile (install-manifest.json changed) or a run that became live
    under a tree a planned row swaps refuses the apply with exit 4, nothing applied, instead of writing a stale
    manifest over the other installer's records or swapping trees under running processes.
#67 / P3-0 A kit 2.0.x driver holds .ub/lock.json with a heartbeat, not .ub/jobs/_driver.lock: a fresh heartbeat of a
    live pid counts as a live driver, also in a run folder without .ub/jobs.
#68 uninstall keeps UB_HOME/kit while a recorded plugin cannot be removed because its CLI is not on PATH, and a re-run
    after a partial removal only runs what is left (no `plugin uninstall` of a plugin that is no longer listed).
#69 A kit marketplace registered from a folder that no longer exists (an earlier UB_HOME) is never trusted by name.
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
import shims  # noqa: E402
from ublib import textio  # noqa: E402
from ublib.proc import process_start_time  # noqa: E402

PLUGIN = "ultimate-brainstorm@ultimate-brainstorm"
NOTE = os.path.join("skills", "ultimate-brainstorm", "references", "e4-note.md")


def run_in_process(th, argv, patch=None):
    """install.py main(argv) in this process with th's environment; patch(mod) may replace functions first."""
    out, err = io.StringIO(), io.StringIO()
    cwd = os.getcwd()
    with th.patched_environ():
        os.chdir(th.project)
        try:
            spec = importlib.util.spec_from_file_location("ub_install_e4_%d" % id(th), paths.INSTALL_PY)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            if patch:
                patch(mod)
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                rc = mod.main(argv)
        finally:
            os.chdir(cwd)
    return rc, out.getvalue(), err.getvalue()


def before_lock(mod, action):
    """Run action() when the apply is about to take install.lock (the plan is made and confirmed)."""
    real = mod.InstallLock.acquire

    def acquire(self):
        action()
        return real(self)
    mod.InstallLock.acquire = acquire


def entries(th):
    return sorted((e.get("agent"), e.get("route")) for e in inst.read_manifest(th).get("entries", []))


def changed_source(th):
    src = inst.kit_source_copy(os.path.join(th.root, "src kit"))
    with open(os.path.join(src, NOTE), "w", encoding="utf-8") as f:
        f.write("a changed kit\n")
    return src


def make_run(th, lock=None):
    """A registered run folder (UB_HOME/runs.json) with .ub/ only, like a kit 2.0.x run before its first job."""
    run = os.path.join(th.root, "runs", "2026-09-26-night-tutor")
    os.makedirs(os.path.join(run, ".ub"), exist_ok=True)
    with open(os.path.join(th.ub_home, "runs.json"), "w", encoding="utf-8") as f:
        json.dump({"runs": [{"path": paths.posix(run), "topic": "night tutor"}]}, f)
    if lock is not None:
        with open(os.path.join(run, ".ub", "lock.json"), "w", encoding="utf-8") as f:
            json.dump(lock, f)
    return run


def dead_pid():
    p = subprocess.Popen([sys.executable, "-c", "pass"])
    p.wait()
    return p.pid


def registry(th, tool="claude"):
    path = os.path.join(th.home, ".fakecli-registry.json")
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    key = [k for k in data if k.startswith(tool + "|")][0]
    return path, data, key


class ChangedWhilePlanWaited(unittest.TestCase):
    def setUp(self):
        inst.require_installer()

    def test_another_installer_applied_meanwhile(self):
        with inst.installer_home(tools=("kimi", "node"), zcode=True) as th:
            def other_installer():
                proc = inst.run(th, "install", "--yes", "--components", "none", "--agents", "zcode")
                self.assertEqual(proc.returncode, 0, paths.describe(proc))
            rc, out, err = run_in_process(th, ["install", "--yes", "--components", "none", "--agents", "kimi"],
                                          lambda mod: before_lock(mod, other_installer))
            self.assertEqual(rc, 4, out + err)
            self.assertIn("another install.py changed this install", err)
            self.assertEqual(entries(th), [("zcode", "copy")], "the other installer's records are kept")
            self.assertFalse(os.path.exists(inst.copy_dest(th, "kimi")), "nothing was applied")
            proc = inst.run(th, "install", "--yes", "--components", "none", "--agents", "kimi")
            self.assertEqual(proc.returncode, 0, paths.describe(proc))
            self.assertEqual(entries(th), [("kimi", "copy"), ("zcode", "copy")])

    def test_a_run_that_became_live_blocks_the_swap(self):
        with inst.installer_home(tools=("kimi", "node")) as th:
            self.assertEqual(inst.run(th, "install", "--yes", "--components", "none").returncode, 0)
            src = changed_source(th)
            run = make_run(th)

            def worker_starts():  # this process plays a worker that started while the plan waited
                os.makedirs(os.path.join(run, ".ub", "jobs"), exist_ok=True)
                with open(os.path.join(run, ".ub", "jobs", "gen-01.running.json"), "w", encoding="utf-8") as f:
                    json.dump({"id": "gen-01", "pid": os.getpid(), "heartbeat_at": textio.now_iso()}, f)
            rc, out, err = run_in_process(th, ["update", "--yes", "--components", "none", "--source", src],
                                          lambda mod: before_lock(mod, worker_starts))
            self.assertEqual(rc, 4, out + err)
            self.assertIn("runs became active after this plan was made", err)
            self.assertFalse(os.path.exists(os.path.join(th.ub_home, "kit", NOTE)), "nothing was swapped")
            rc, out, err = run_in_process(th, ["update", "--yes", "--force", "--components", "none", "--source", src],
                                          lambda mod: before_lock(mod, lambda: None))
            self.assertEqual(rc, 0, out + err)
            self.assertTrue(os.path.isfile(os.path.join(th.ub_home, "kit", NOTE)))


class LegacyDriver(unittest.TestCase):
    """A kit 2.0.x `ub run` holds .ub/lock.json {pid, host, heartbeat_at, heartbeat_ts} for the whole run."""

    def setUp(self):
        inst.require_installer()

    def update(self, th, lock, code):
        make_run(th, lock)
        data, _proc = inst.run_json(th, "update", "--yes", "--components", "none", "--source", changed_source(th),
                                    exit=code)
        return data

    def test_a_live_heartbeat_blocks_the_swap(self):
        with inst.installer_home(tools=("kimi", "node")) as th:
            self.assertEqual(inst.run(th, "install", "--yes", "--components", "none").returncode, 0)
            data = self.update(th, {"pid": os.getpid(), "host": "claude", "heartbeat_at": textio.now_iso(),
                                    "heartbeat_ts": time.time()}, 4)
            self.assertTrue(any("a live driver" in w for w in data["warnings"]), data["warnings"])
            self.assertTrue(any(r["item"].startswith("stage kit") and r["action"] == "blocked" for r in data["rows"]))
            self.assertFalse(os.path.exists(os.path.join(th.ub_home, "kit", NOTE)))

    def test_stale_dead_or_new_format_records_do_not(self):
        started = process_start_time(os.getpid()) or time.time()
        cases = [{"pid": os.getpid(), "host": "claude", "heartbeat_ts": started - 600},  # stale: a pid reused since
                 {"pid": dead_pid(), "host": "claude", "heartbeat_ts": time.time()},  # dead driver
                 {"pid": os.getpid(), "host": "claude", "since": textio.now_iso()}]  # 2.1 record: decides nothing
        for lock in cases:
            with inst.installer_home(tools=("kimi", "node")) as th:
                self.assertEqual(inst.run(th, "install", "--yes", "--components", "none").returncode, 0)
                self.update(th, lock, 0)
                self.assertTrue(os.path.isfile(os.path.join(th.ub_home, "kit", NOTE)), lock)


class UninstallKeepsWhatAPluginNeeds(unittest.TestCase):
    def setUp(self):
        inst.require_installer()

    def test_no_cli_on_path_keeps_the_kit(self):
        with inst.installer_home(tools=("claude", "node")) as th:
            proc = inst.run(th, "install", "--yes", "--agents", "claude-code", "--components", "none")
            self.assertEqual(proc.returncode, 0, paths.describe(proc))
            shims.remove_fake(th.bin, "claude")
            data, _proc = inst.run_json(th, "uninstall", "--yes")
            kept = [r for r in data["results"] if r["item"] == "staged kit (kept)"]
            self.assertEqual([r["status"] for r in kept], ["skip-not-owned"], data["results"])
            self.assertTrue(os.path.isdir(os.path.join(th.ub_home, "kit")), "the plugin still loads from it")
            self.assertTrue(any("remove the plugin by hand" in m for m in data["manual"]), data["manual"])
            self.assertTrue(any(e["route"] == "native" for e in inst.read_manifest(th)["entries"]),
                            "the plugin's record stays until it is removed")

    def test_a_rerun_after_a_partial_removal_finishes(self):
        with inst.installer_home(tools=("claude", "node")) as th:
            proc = inst.run(th, "install", "--yes", "--agents", "claude-code", "--components", "none")
            self.assertEqual(proc.returncode, 0, paths.describe(proc))
            path, data, key = registry(th)
            data[key]["plugins"].pop(PLUGIN)  # the first uninstall removed the plugin, then stopped
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f)
            th.clear_log()
            proc = inst.run(th, "uninstall", "--yes")
            self.assertEqual(proc.returncode, 0, paths.describe(proc))
            calls = [c["argv"][:3] for c in th.fake_calls("claude")]
            self.assertNotIn(["plugin", "uninstall", PLUGIN], calls, "nothing to uninstall any more")
            self.assertIn(["plugin", "marketplace", "remove"], calls)
            self.assertFalse(os.path.exists(os.path.join(th.ub_home, "kit")))
            self.assertFalse(os.path.exists(os.path.join(th.ub_home, "install-manifest.json")))

    def test_a_record_whose_plugin_and_marketplace_are_gone_is_dropped(self):
        with inst.installer_home(tools=("claude", "node")) as th:
            proc = inst.run(th, "install", "--yes", "--agents", "claude-code", "--components", "none")
            self.assertEqual(proc.returncode, 0, paths.describe(proc))
            path, data, key = registry(th)
            data[key] = {"marketplaces": {}, "plugins": {}}  # removed by hand, the manifest still records them
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f)
            th.clear_log()
            proc = inst.run(th, "uninstall", "--yes")
            self.assertEqual(proc.returncode, 0, paths.describe(proc))
            calls = [" ".join(c["argv"]) for c in th.fake_calls("claude")]
            self.assertFalse([c for c in calls if c.startswith(("plugin uninstall", "plugin marketplace remove"))],
                             calls)
            self.assertFalse(os.path.exists(os.path.join(th.ub_home, "kit")))
            self.assertFalse(os.path.exists(os.path.join(th.ub_home, "install-manifest.json")))


class StaleMarketplaceFolder(unittest.TestCase):
    def setUp(self):
        inst.require_installer()

    def test_a_folder_that_no_longer_exists_is_not_the_kit(self):
        with inst.installer_home(tools=("claude", "node")) as th:
            gone = os.path.join(th.root, "old ub home", "kit")
            path = os.path.join(th.home, ".fakecli-registry.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"claude|%s" % os.path.normcase(th.env["CLAUDE_CONFIG_DIR"]): {
                    "marketplaces": {"ultimate-brainstorm": {"source": gone}},
                    "plugins": {PLUGIN: {"scope": "user"}}}}, f)
            data, _proc = inst.run_json(th, "install", "--yes", "--agents", "claude-code", "--components", "none",
                                        exit=4)
            rows = [r for r in data["rows"] if r["item"] == "plugin ultimate-brainstorm"]
            self.assertEqual([r["action"] for r in rows], ["blocked"], data["rows"])
            self.assertTrue(any("no longer exists" in w for w in data["warnings"]), data["warnings"])
            self.assertFalse(os.path.exists(os.path.join(th.ub_home, "install-manifest.json")), "nothing recorded")
            doc, _p = inst.run_json(th, "doctor", exit=None)
            src = [c for c in doc["checks"] if c["id"] == "agent.claude-code.plugin_source"]
            self.assertEqual([c["status"] for c in src], ["WARN"], doc["checks"])
            proc = inst.run(th, "install", "--yes", "--force", "--agents", "claude-code", "--components", "none")
            self.assertEqual(proc.returncode, 0, paths.describe(proc))
            _p, data, key = registry(th)
            self.assertTrue(paths.same_path(data[key]["marketplaces"]["ultimate-brainstorm"]["source"],
                                            os.path.join(th.ub_home, "kit")), "--force re-adds it from the kit")


if __name__ == "__main__":
    unittest.main()
