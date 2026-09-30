"""Installer guards (audit findings #67, #70, #71, #76, #78). Owner: WP7.

#67 update/install refuse to swap kit trees while a run has live workers or a live driver (--force goes ahead).
#70 uninstall --purge moves Codex's own data out of the provider homes into backups/ instead of deleting it.
#71 a downloaded release is checked with `gh attestation verify` when gh can run [U-52].
#76 a broken profiles/launch.py blocks the launcher and Codex-home rows instead of writing other text.
#78 UB_RELEASE_DIR picks the newest archive by number (2.0.10 over 2.0.9).
"""

import contextlib
import importlib.util
import io
import json
import os
import shutil
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "harness"))
import paths  # noqa: E402
import inst  # noqa: E402
from ublib import batch, textio  # noqa: E402

TOKEN = "zai-guards-TOKEN-77a1"


def change_source(th):
    """A --source kit whose content differs from the staged one, so update swaps the kit and the copies."""
    src = inst.kit_source_copy(os.path.join(th.root, "src kit"))
    with open(os.path.join(src, "skills", "ultimate-brainstorm", "references", "wp7-note.md"), "w",
              encoding="utf-8") as f:
        f.write("a changed kit\n")
    return src


def make_run(th, root, register=False):
    run = os.path.join(root, "2026-09-26-night-tutor")
    os.makedirs(os.path.join(run, ".ub", "jobs"), exist_ok=True)
    if register:
        with open(os.path.join(th.ub_home, "runs.json"), "w", encoding="utf-8") as f:
            json.dump({"runs": [{"path": paths.posix(run), "topic": "night tutor"}]}, f)
    return run


class LiveRuns(unittest.TestCase):
    def setUp(self):
        inst.require_installer()

    def test_live_worker_blocks_the_swap(self):
        with inst.installer_home(tools=("kimi", "node")) as th:
            self.assertEqual(inst.run(th, "install", "--yes", "--components", "none").returncode, 0)
            src = change_source(th)
            run = make_run(th, os.path.join(th.project, "brainstorm"))
            marker = os.path.join(run, ".ub", "jobs", "gen-01.running.json")
            with open(marker, "w", encoding="utf-8") as f:  # this process plays the live worker
                json.dump({"id": "gen-01", "pid": os.getpid(), "heartbeat_at": textio.now_iso()}, f)
            kit_version_file = os.path.join(th.ub_home, "kit", "skills", "ultimate-brainstorm", "references",
                                            "wp7-note.md")
            data, _proc = inst.run_json(th, "update", "--yes", "--components", "none", "--source", src, exit=4)
            blocked = [r for r in data["rows"] if r["action"] == "blocked"]
            self.assertTrue(any(r["item"].startswith("stage kit") for r in blocked), data["rows"])
            self.assertTrue(any(r["item"] == "skill ultimate-brainstorm" for r in blocked), data["rows"])
            self.assertTrue(any("live worker" in w and "ub stop" in w for w in data["warnings"]), data["warnings"])
            self.assertFalse(os.path.exists(kit_version_file), "nothing was swapped")
            os.remove(marker)
            proc = inst.run(th, "update", "--yes", "--components", "none", "--source", src)
            self.assertEqual(proc.returncode, 0, paths.describe(proc))
            self.assertTrue(os.path.isfile(kit_version_file))

    def test_live_driver_blocks_and_force_goes_ahead(self):
        with inst.installer_home(tools=("kimi", "node")) as th:
            self.assertEqual(inst.run(th, "install", "--yes", "--components", "none").returncode, 0)
            src = change_source(th)
            run = make_run(th, os.path.join(th.root, "elsewhere", "brainstorm"), register=True)
            driver = batch.JobLock(run, "_driver")
            self.assertTrue(driver.try_acquire())
            try:
                data, _proc = inst.run_json(th, "update", "--yes", "--components", "none", "--source", src, exit=4)
                self.assertTrue(any("a live driver" in w for w in data["warnings"]), data["warnings"])
                proc = inst.run(th, "update", "--yes", "--force", "--components", "none", "--source", src)
                self.assertEqual(proc.returncode, 0, paths.describe(proc))
            finally:
                driver.release()


class PurgeKeepsCodexData(unittest.TestCase):
    def setUp(self):
        inst.require_installer()

    def test_codex_sessions_move_to_backups(self):
        with inst.installer_home(tools=("claude", "codex", "node")) as th:
            self.assertEqual(inst.run(th, "install", "--yes", "--agents", "claude-code", "--components",
                                      "none").returncode, 0)
            proc = inst.run(th, "setup-glm", "--launcher", "--codex", "--yes", env_extra={"ZAI_API_KEY": TOKEN})
            self.assertEqual(proc.returncode, 0, paths.describe(proc))
            home = os.path.join(th.ub_home, "codex-homes", "glm")
            th.write(os.path.join(home, "sessions", "2026", "09", "26", "rollout-1.jsonl"), '{"turn": 1}\n')
            th.write(os.path.join(home, "history.jsonl"), '{"text": "my question"}\n')
            plan = inst.run_json(th, "uninstall", "--purge")[0]
            moved = [w for w in plan["warnings"] if "Codex's own data" in w]
            self.assertEqual(len(moved), 2, plan["warnings"])
            proc = inst.run(th, "uninstall", "--yes", "--purge")
            self.assertEqual(proc.returncode, 0, paths.describe(proc))
            self.assertEqual(sorted(os.listdir(th.ub_home)), ["backups"])
            rollout = inst.find_files(os.path.join(th.ub_home, "backups"), r"codex-homes/glm/sessions/.*rollout-1")
            history = inst.find_files(os.path.join(th.ub_home, "backups"), r"codex-homes/glm/history\.jsonl$")
            self.assertEqual(len(rollout), 1, "the session transcript survives in backups/")
            self.assertEqual(inst.read(history[0]), '{"text": "my question"}\n')
            self.assertFalse(inst.find_files(os.path.join(th.ub_home, "backups"), r"codex-homes/glm/config\.toml$"),
                             "the installer's own config.toml is deleted, not kept")


class BrokenLaunchPy(unittest.TestCase):
    def setUp(self):
        inst.require_installer()

    def test_blocked_rows_instead_of_other_text(self):
        with inst.installer_home(tools=("claude", "codex", "node")) as th:
            self.assertEqual(inst.run(th, "install", "--yes", "--agents", "claude-code", "--components",
                                      "none").returncode, 0)
            ub = os.path.join(th.ub_home, "bin", "ub")
            before = inst.read(ub)
            bad = inst.kit_source_copy(os.path.join(th.root, "bad kit"))
            launch = os.path.join(bad, "profiles", "launch.py")
            with open(launch, encoding="utf-8") as f:
                text = f.read()
            with open(launch, "w", encoding="utf-8", newline="\n") as f:
                f.write('raise RuntimeError("injected defect")\n' + text)
            data, _proc = inst.run_json(th, "setup-glm", "--launcher", "--codex", "--yes", "--source", bad,
                                        env_extra={"ZAI_API_KEY": TOKEN}, exit=4)
            blocked = sorted(r["item"] for r in data["rows"] if r["action"] == "blocked")
            self.assertEqual(blocked, ["codex home glm", "launchers claude-glm", "launchers codex-glm",
                                       "launchers ub"], data["rows"])
            self.assertTrue(any("injected defect" in w for w in data["warnings"]), data["warnings"])
            self.assertEqual(inst.read(ub), before, "no launcher is rewritten")
            self.assertFalse(os.path.exists(os.path.join(th.ub_home, "codex-homes", "glm", "config.toml")))


def build_release(th, version, out):
    """Real release assets of a kit copy whose VERSION is `version` (tools/release.py)."""
    src = inst.kit_source_copy(os.path.join(th.root, "kit-" + version))
    shutil.copytree(os.path.join(paths.KIT, "tools"), os.path.join(src, "tools"))
    with open(os.path.join(src, "VERSION"), "w", encoding="utf-8") as f:
        f.write(version + "\n")
    tmp = os.path.join(th.root, "dist-" + version)
    proc = paths.run_py(os.path.join(src, "tools", "release.py"), ["--version", version, "--out", tmp,
                                                                  "--no-acceptance"], cwd=src)
    if proc.returncode != 0:
        raise AssertionError(paths.describe(proc))
    name = "ultimate-brainstorm-%s.tar.gz" % version
    shutil.copyfile(os.path.join(tmp, name), os.path.join(out, name))
    with open(os.path.join(tmp, "SHA256SUMS"), encoding="utf-8") as f:
        return [line for line in f.read().splitlines() if line.endswith(name)]


class ReleaseDir(unittest.TestCase):
    def setUp(self):
        inst.require_installer()
        paths.require(paths.RELEASE_PY, owner="B1")

    def test_newest_by_number(self):
        with inst.installer_home(tools=("kimi", "node")) as th:
            rel = th.mkdir("releases")
            sums = build_release(th, "2.1.9", rel) + build_release(th, "2.1.10", rel)
            with open(os.path.join(rel, "SHA256SUMS"), "w", encoding="utf-8", newline="\n") as f:
                f.write("\n".join(sums) + "\n")
            plan = inst.run_plan(th, "--source", "github", "--components", "none",
                                 env_extra={"UB_RELEASE_DIR": rel})
            self.assertEqual(plan["kit"]["version"], "2.1.10", plan["kit"])
            self.assertTrue(any("provenance" in w and "UB_RELEASE_DIR" in w for w in plan["warnings"]),
                            plan["warnings"])


def load_installer():
    spec = importlib.util.spec_from_file_location("ub_install_wp7_prov", paths.INSTALL_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class Provenance(unittest.TestCase):
    """verify_provenance against a fake gh (tests never reach the network)."""

    def setUp(self):
        inst.require_installer()

    def check(self, th, version="2.1.0", require=False, path=None):
        mod = load_installer()
        argv = ["update"] + (["--require-attestation"] if require else [])
        env = {k: v for k, v in th.env.items() if k != "UB_RELEASE_DIR"}
        if path is not None:
            env["PATH"] = path  # only these folders: a real gh next to the system python must not be found
        ctx = mod.Ctx(mod.build_parser().parse_args(argv), environ=env)
        archive = th.write(os.path.join(th.root, "ultimate-brainstorm-%s.tar.gz" % version), "archive bytes\n")
        err = None
        with contextlib.redirect_stderr(io.StringIO()):
            try:
                mod.verify_provenance(ctx, archive, version)
            except mod.InstallError as exc:
                err = str(exc)
        calls = [c["argv"] for c in th.fake_calls("gh")]
        return err, ctx.notes, calls

    def test_verified(self):
        with inst.installer_home(tools=("gh",)) as th:
            err, notes, calls = self.check(th)
            self.assertIsNone(err)
            self.assertEqual(notes, [])
            self.assertEqual(calls[-1][:2], ["attestation", "verify"])  # after `auth status`, `attestation --help`
            self.assertIn("MrHashMe/ultimate-brainstorm", calls[-1])

    def test_failed_verification_refuses(self):
        with inst.installer_home(tools=("gh",)) as th:
            th.set_scenario([{"tool": "gh", "argv_regex": "^attestation verify", "action": "fail", "exit": 1,
                              "stderr": "Error: no attestations found for subject"}])
            err, _notes, _calls = self.check(th)
            self.assertIn("provenance check failed", err or "")

    def test_unusable_gh_is_a_note_unless_required(self):
        with inst.installer_home(tools=("gh",)) as th:
            th.set_scenario([{"tool": "gh", "argv_regex": "^attestation verify", "action": "fail", "exit": 4,
                              "stderr": "To get started with GitHub CLI, please run:  gh auth login"}])
            err, notes, _calls = self.check(th)
            self.assertIsNone(err)
            self.assertTrue(notes and "not checked" in notes[0], notes)
            err, _notes, _calls = self.check(th, require=True)
            self.assertIn("--require-attestation", err or "")

    def test_no_gh_and_old_releases(self):
        with inst.installer_home(tools=("node",)) as th:
            only = os.pathsep.join([th.bin] + ([os.path.join(os.environ.get("SYSTEMROOT", r"C:\Windows"), "System32")]
                                               if os.name == "nt" else []))
            err, notes, _calls = self.check(th, path=only)
            self.assertIsNone(err)
            self.assertIn("gh is not installed", notes[0])
            err, _notes, _calls = self.check(th, require=True, path=only)
            self.assertIn("--require-attestation", err or "")
        with inst.installer_home(tools=("gh",)) as th:
            err, notes, calls = self.check(th, version="2.0.3")
            self.assertIsNone(err)
            self.assertIn("predates", notes[0])
            self.assertEqual(calls, [], "releases before attestations are not checked")


if __name__ == "__main__":
    unittest.main()
