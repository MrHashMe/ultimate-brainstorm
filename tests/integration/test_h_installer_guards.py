"""Which .ub/lock.json records are a live kit 2.0.x driver, what the installer tells the user, how it reads gh, and
what doctor survives (audit finding #67, reviewer note P3-publish-installer-0, round-3 notes
NEW-G8-installer-supplychain-4 and -5, round-4 notes NEW-I-HG-installer-1 and -2, NEW-I-HE-backends-worker-2 and the
round-4 installer-release reviews). Owner: HG, JG.

#67 / P3-0 A kit 2.0.x `ub run` waiting at a human gate beats no more: its heartbeat grows old while the process that
    wrote it still runs. That process started before its last beat (a reused pid starts after it), so it still counts
    as a live driver and an update does not swap the kit under it. The block names the session (kit 2.0.x, its pid)
    and the way out that ends it (answer or close it in its terminal): 2.0.x's `ub stop` stops only its workers.
-4  Kit 2.1+ writes lock.json as a holder record that always carries "since" (and a 2.0.3-format heartbeat_ts its holder
    refreshes every 30 s, for 2.0.3 drivers only). Such a record never counts, also with a fresh beat or when its pid
    was reused after a hard kill, and neither does a 2.0.x heartbeat more than 120 s in the future.
-5  uninstall keeps UB_HOME/kit while a kept plugin may load from it. The remedy depends on why the plugin is kept: its
    CLI is not on PATH (--force changes nothing: put the CLI back, or `uninstall --purge`), or its source is
    unknown (remove it first, or pass --force).
HG-2 On POSIX a process start time is derived from the boot time, which a forward wall-clock step moves: a 2.0.x driver
    then looks started after its beat. Its command line (ub.py on this run) is the step-proof second signal. The rule
    is proc.legacy_driver_live, which the engine's DriverLock applies too.
gh  The sign-in pre-check asks about the account verify uses (`gh auth status --active --hostname github.com`), not
    every account on every host, and verify is pinned to github.com. gh's own "error creating Sigstore verifier" (its
    trust root is out of reach) is "not checked", never a refusal; a refusal names the way out (--source DIR).
doc doctor reports an unreadable file in a component skill folder as a WARN, and reads a settings.json whose env is not
    an object as no endpoint override (both crashed doctor before).
rec A re-install that keeps one component folder records it under the commit it came from (`commits`), not the new pin.
"""

import contextlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import types
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "harness"))
import paths  # noqa: E402
import inst  # noqa: E402
import shims  # noqa: E402
import test_e4_components as e4c  # noqa: E402
import test_e4_installer_guards as e4  # noqa: E402
from ublib import textio  # noqa: E402

TEN_YEARS = 10 * 365 * 86400.0
# a real kit 2.1 driver: takes the kernel lock, announces itself in lock.json, then is hard-killed (no release)
KILLED_21_DRIVER = r"""
import os, sys
sys.path.insert(0, %r)
from ublib.engine import state
lock = state.DriverLock(sys.argv[1], host="claude-code")
assert lock.acquire()
lock.announce()
os._exit(9)
""" % paths.SCRIPTS
# holds argv[1] open with no sharing (Windows: then no other process can read it) until its stdin closes
HOLD_EXCLUSIVE = r"""
import ctypes, sys
from ctypes import wintypes
k32 = ctypes.WinDLL("kernel32", use_last_error=True)
k32.CreateFileW.restype = wintypes.HANDLE
k32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD,
                            wintypes.DWORD, wintypes.HANDLE]
h = k32.CreateFileW(sys.argv[1], 0x80000000, 0, None, 3, 0x80, None)
if not h or h == ctypes.c_void_p(-1).value:
    sys.exit("CreateFileW failed: %d" % ctypes.get_last_error())
print("held", flush=True)
sys.stdin.read()
"""
RUN_NAME = "2026-09-26-night-tutor"
# real gh 2.97.0 with the Sigstore TUF repository out of reach (a proxy that blocks it)
NO_VERIFIER = ("Loaded digest sha256:0123abcd for file://ultimate-brainstorm-2.1.0.tar.gz\n"
               "error creating Sigstore verifier: no valid Sigstore verifiers could be initialized")
FORGED_NO_VERIFIER = [  # the phrase inside gh's quoted values (the certificate's identity) is no verdict
    'Error: expected SourceRepositoryRef to be "refs/tags/v2.1.0", got "error creating Sigstore verifier"',
    'Error: got "refs/heads/x\\nerror creating Sigstore verifier: y"']
NEW_PIN = "2222222222222222222222222222222222222222"


def load_installer():
    spec = importlib.util.spec_from_file_location("ub_install_hg_guards", paths.INSTALL_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def clock(offset):
    """A stand-in for install.py's time module whose clock runs `offset` seconds ahead (install.py reads time.time()
    only for the lock age and the backup cutoff)."""
    return types.SimpleNamespace(time=lambda: time.time() + offset, sleep=time.sleep)


def write_lock(run, record):
    with open(os.path.join(run, ".ub", "lock.json"), "w", encoding="utf-8") as f:
        json.dump(record, f)


def sleeper(*args, **kw):
    """A live process (it sleeps 300 s) whose command line ends with args."""
    return subprocess.Popen([sys.executable, "-c", "import time; time.sleep(300)"] + list(args), **kw)


@contextlib.contextmanager
def unreadable(path):
    """path cannot be read while this runs: held open with no sharing (Windows) or mode 000 (POSIX)."""
    if os.name == "nt":
        holder = subprocess.Popen([sys.executable, "-c", HOLD_EXCLUSIVE, path], stdin=subprocess.PIPE,
                                  stdout=subprocess.PIPE, universal_newlines=True)
        try:
            line = holder.stdout.readline().strip()
            if line != "held":
                raise AssertionError("the holder could not open %s: %r" % (path, line))
            yield
        finally:
            holder.stdin.close()
            holder.wait(timeout=60)
            holder.stdout.close()
        return
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        raise unittest.SkipTest("root reads a mode-000 file")
    os.chmod(path, 0)
    try:
        yield
    finally:
        os.chmod(path, 0o644)


class LegacyRecord(unittest.TestCase):
    """legacy_driver_alive on one record, with a live process as the recorded pid."""

    def setUp(self):
        inst.require_installer()
        self.mod = load_installer()
        self.driver = sleeper()
        self.beat = time.time()  # after the process started: a beat that process could have written
        self.addCleanup(self.driver.wait)
        self.addCleanup(self.driver.kill)

    def alive(self, record, offset=0.0):
        with tempfile.TemporaryDirectory() as run:
            os.makedirs(os.path.join(run, ".ub"))
            write_lock(run, record)
            self.mod.time = clock(offset)
            return self.mod.legacy_driver_alive(run)

    def legacy(self, beat, pid=None):
        return {"pid": pid or self.driver.pid, "host": "claude", "heartbeat_at": textio.now_iso(), "heartbeat_ts": beat}

    def test_a_driver_waiting_at_a_human_gate_still_counts(self):
        self.assertTrue(self.alive(self.legacy(self.beat), offset=300), "its last beat is 300 s old")
        self.assertFalse(self.alive(self.legacy(self.beat - 300)), "a pid reused after that beat")

    def test_kit_21_records_and_future_beats_decide_nothing(self):
        since = dict(self.legacy(self.beat), since=textio.now_iso())
        self.assertFalse(self.alive(since), "a 2.1 record with a fresh beat (what a 2.1 driver keeps writing)")
        self.assertFalse(self.alive(dict(since, heartbeat_ts=self.beat + TEN_YEARS)),
                         "an intermediate 2.1 tree's record (heartbeat ten years ahead)")
        self.assertFalse(self.alive(self.legacy(self.beat + 3600)), "a 2.0.x beat an hour ahead")
        self.assertTrue(self.alive(self.legacy(self.beat)), "a fresh 2.0.x beat")

    def test_a_clock_step_after_the_beat_is_told_apart_by_the_command_line(self):
        """The start time moved past the beat (a forward wall-clock step on POSIX): ub.py on this run still counts."""
        with tempfile.TemporaryDirectory() as root:
            run = os.path.join(root, "brainstorm", RUN_NAME)
            os.makedirs(os.path.join(run, ".ub"))
            write_lock(run, self.legacy(self.beat))
            self.mod.time = clock(4000)
            ub = os.path.join(root, "kit", "ub.py")
            cases = [([sys.executable, ub, "next", run, "--wait-s", "60"], None, True),
                     ([sys.executable, ub, "run", "--text", "night tutor"], root, True),  # <cwd>/brainstorm/<run>
                     ([sys.executable, ub, "run", "--root", root, "--text", "night tutor"], None, True),
                     ([sys.executable, "ub.py", "continue", RUN_NAME], None, True),
                     ([sys.executable, ub, "next", os.path.join(root, "brainstorm", "other")], None, False),
                     ([sys.executable, ub, "run", "--text", "night tutor"], os.path.join(root, "kit"), False),
                     ([sys.executable, os.path.join(root, "kit", "other.py"), run], root, False),
                     ([], None, False)]
            with mock.patch.object(self.mod.proc, "process_start_time", lambda pid: self.beat + 3600):
                for args, cwd, want in cases:
                    with mock.patch.object(self.mod.proc, "process_args", lambda pid, a=args, c=cwd: (a, c)):
                        self.assertEqual(bool(self.mod.legacy_driver_alive(run)), want, (args, cwd))

    @unittest.skipIf(os.name == "nt", "POSIX: Windows process start times do not move with the clock")
    def test_the_command_line_is_read_from_the_process(self):
        with tempfile.TemporaryDirectory() as root:
            run = os.path.join(root, "brainstorm", RUN_NAME)
            os.makedirs(os.path.join(run, ".ub"))
            driver = sleeper(os.path.join(root, "kit", "ub.py"), "next", run)
            self.addCleanup(driver.wait)
            self.addCleanup(driver.kill)
            write_lock(run, self.legacy(self.beat, pid=driver.pid))
            self.mod.time = clock(4000)
            with mock.patch.object(self.mod.proc, "process_start_time", lambda pid: self.beat + 3600):
                self.assertTrue(self.mod.legacy_driver_alive(run), self.mod.proc.process_args(driver.pid))
                write_lock(run, self.legacy(self.beat))  # the sleeper of setUp: no ub.py
                self.assertFalse(self.mod.legacy_driver_alive(run))


class LegacyDriverUpdate(unittest.TestCase):
    def setUp(self):
        inst.require_installer()

    def test_a_driver_idle_at_a_gate_blocks_the_swap(self):
        driver = sleeper()
        try:
            with inst.installer_home(tools=("kimi", "node")) as th:
                self.assertEqual(inst.run(th, "install", "--yes", "--components", "none").returncode, 0)
                e4.make_run(th, {"pid": driver.pid, "host": "terminal", "heartbeat_at": textio.now_iso(),
                                 "heartbeat_ts": time.time()})

                def later(mod):  # the update runs 300 s after the driver's last beat
                    mod.time = clock(300)
                rc, out, err = e4.run_in_process(th, ["update", "--yes", "--components", "none", "--source",
                                                      e4.changed_source(th)], later)
                self.assertEqual(rc, 4, out + err)
                self.assertIn("a live driver", out + err)
                reason = [ln for ln in (out + err).splitlines() if "runs are active" in ln][0]
                self.assertIn("a kit 2.0.x session (pid %d, terminal), probably waiting for an answer in its terminal"
                              % driver.pid, reason)
                self.assertIn("answer or close each kit 2.0.x session (Ctrl+C in its terminal", reason)
                self.assertNotIn("stop them (ub stop <run>)", reason, "2.0.x's ub stop stops only its workers")
                self.assertFalse(os.path.exists(os.path.join(th.ub_home, "kit", e4.NOTE)))
        finally:
            driver.kill()
            driver.wait()

    def test_the_record_of_a_killed_21_driver_with_a_reused_pid_blocks_nothing(self):
        with inst.installer_home(tools=("kimi", "node")) as th:
            self.assertEqual(inst.run(th, "install", "--yes", "--components", "none").returncode, 0)
            run = e4.make_run(th)
            os.makedirs(os.path.join(run, ".ub", "jobs"))
            self.assertEqual(subprocess.run([sys.executable, "-c", KILLED_21_DRIVER, run]).returncode, 9)
            record = textio.read_json(os.path.join(run, ".ub", "lock.json"))
            self.assertLess(abs(record["heartbeat_ts"] - time.time()), 60, "a 2.1 record's heartbeat is current")
            other = sleeper()
            try:
                write_lock(run, dict(record, pid=other.pid))  # the dead driver's pid, now another process's
                data, _proc = inst.run_json(th, "update", "--yes", "--components", "none", "--source",
                                            e4.changed_source(th))
                self.assertFalse([w for w in data["warnings"] if "runs are active" in w], data["warnings"])
                self.assertTrue(os.path.isfile(os.path.join(th.ub_home, "kit", e4.NOTE)))
            finally:
                other.kill()
                other.wait()


class UninstallRemedy(unittest.TestCase):
    def setUp(self):
        inst.require_installer()

    def kept(self, data):
        return [w for w in data["warnings"] if w.startswith("UB_HOME/kit is the marketplace")]

    def test_a_missing_cli_is_not_fixed_by_force(self):
        with inst.installer_home(tools=("claude", "node")) as th:
            proc = inst.run(th, "install", "--yes", "--agents", "claude-code", "--components", "none")
            self.assertEqual(proc.returncode, 0, paths.describe(proc))
            shims.remove_fake(th.bin, "claude")
            data, _proc = inst.run_json(th, "uninstall", "--yes", "--force")
            kept = self.kept(data)
            self.assertEqual(len(kept), 1, data["warnings"])
            self.assertIn("Claude Code: claude is not on PATH; put it on PATH, then run uninstall again (without "
                          "claude the installer cannot see a plugin removed by hand; if you no longer use Claude "
                          "Code, `uninstall --purge` also removes UB_HOME/kit).", kept[0])
            self.assertNotIn("--force", kept[0])
            self.assertTrue(os.path.isdir(os.path.join(th.ub_home, "kit")))

    def test_a_plugin_of_unknown_source_names_force(self):
        with inst.installer_home(tools=("claude", "node")) as th:
            proc = inst.run(th, "install", "--yes", "--agents", "kimi", "--components", "none")
            self.assertEqual(proc.returncode, 0, paths.describe(proc))
            with open(os.path.join(th.home, ".fakecli-registry.json"), "w", encoding="utf-8") as f:
                json.dump({"claude|%s" % os.path.normcase(th.env["CLAUDE_CONFIG_DIR"]): {
                    "marketplaces": {"ultimate-brainstorm": {"source": "somewhere"}},
                    "plugins": {e4.PLUGIN: {"scope": "user"}}}}, f)
            data, _proc = inst.run_json(th, "uninstall", "--yes")
            kept = self.kept(data)
            self.assertEqual(len(kept), 1, data["warnings"])
            self.assertIn("Claude Code: the plugin's source is unknown; remove the plugin first (or pass --force), "
                          "then run uninstall again", kept[0])


class GhProvenance(unittest.TestCase):
    """verify_provenance against a fake gh: which gh answers are a verdict and which only mean "not checked"."""

    def setUp(self):
        inst.require_installer()

    def check(self, th, require=False):
        mod = load_installer()
        env = {k: v for k, v in th.env.items() if k != "UB_RELEASE_DIR"}
        args = ["update"] + (["--require-attestation"] if require else [])
        ctx = mod.Ctx(mod.build_parser().parse_args(args), environ=env)
        archive = th.write(os.path.join(th.root, "ultimate-brainstorm-2.1.0.tar.gz"), "archive bytes\n")
        err = None
        with contextlib.redirect_stderr(io.StringIO()):
            try:
                mod.verify_provenance(ctx, archive, "2.1.0")
            except mod.InstallError as exc:
                err = str(exc)
        return err, ctx.notes

    def test_another_accounts_auth_problem_does_not_skip_the_check(self):
        """`gh auth status` exits 1 when any account on any host has a problem (a stale second account, an expired
        enterprise host) although github.com's active account can verify."""
        with inst.installer_home(tools=("gh",)) as th:
            th.set_scenario([{"tool": "gh", "argv_regex": "^auth status$", "action": "fail", "exit": 1,
                              "stderr": "ghe.example.invalid\n  X Failed to log in to ghe.example.invalid: The token "
                                        "in hosts.yml is invalid."}])
            err, notes = self.check(th)
            self.assertIsNone(err)
            self.assertEqual(notes, [])
            calls = [c["argv"] for c in th.fake_calls("gh")]
            self.assertIn(["auth", "status", "--active", "--hostname", "github.com"], calls)
            verify = [c for c in calls if c[:2] == ["attestation", "verify"]]
            self.assertEqual(len(verify), 1, calls)
            self.assertEqual(verify[0][-2:], ["--hostname", "github.com"], "verify asks the host it signed in to")

    def test_a_signed_out_github_account_is_a_note(self):
        with inst.installer_home(tools=("gh",)) as th:
            th.set_scenario([{"tool": "gh", "argv_regex": "^auth status --active --hostname github.com$",
                              "action": "fail", "exit": 1, "stderr": "You are not logged into any GitHub hosts."}])
            err, notes = self.check(th)
            self.assertIsNone(err)
            self.assertTrue(notes and "gh auth status --active --hostname github.com" in notes[0], notes)
            self.assertIn("--source-ref refs/tags/v2.1.0 --hostname github.com", notes[0],
                          "the manual command names the host too")
            self.assertFalse([c for c in th.fake_calls("gh") if c["argv"][:2] == ["attestation", "verify"]])

    def test_a_gh_that_cannot_build_its_verifier_has_not_checked(self):
        with inst.installer_home(tools=("gh",)) as th:
            th.set_scenario([{"tool": "gh", "argv_regex": "^attestation verify", "action": "fail", "exit": 1,
                              "stderr": NO_VERIFIER}])
            err, notes = self.check(th)
            self.assertIsNone(err)
            self.assertTrue(notes and "could not build its Sigstore verifier" in notes[0], notes)
            self.assertIn("not checked", notes[0])
            err, _notes = self.check(th, require=True)
            self.assertIn("--require-attestation", err or "")
            self.assertIn("could not build its Sigstore verifier", err or "")

    def test_a_refusal_is_no_dead_end(self):
        for text in FORGED_NO_VERIFIER + ["Error: failed to fetch attestations: dial tcp: no such host"]:
            with inst.installer_home(tools=("gh",)) as th:
                th.set_scenario([{"tool": "gh", "argv_regex": "^attestation verify", "action": "fail", "exit": 1,
                                  "stderr": text}])
                err, notes = self.check(th)
                self.assertIn("provenance check failed", err or "", (text, notes))
                self.assertNotIn("found no valid attestation", err, "gh may not have reached a verdict")
                self.assertIn("did not confirm", err)
                self.assertIn("--source DIR", err, "the way out when GitHub or Sigstore stays out of reach")


class DoctorSurvives(unittest.TestCase):
    def setUp(self):
        inst.require_installer()

    def test_an_unreadable_file_in_a_component_folder_is_a_warn(self):
        with inst.installer_home(tools=("claude", "node")) as th:
            own = os.path.join(th.claude_home, "skills", "grilling")
            th.write(os.path.join(own, "SKILL.md"), "---\nname: grilling\ndescription: my own\n---\nMine.\n")
            notes = th.write(os.path.join(own, "notes.md"), "my notes\n")
            with unreadable(notes):
                doc, proc = inst.run_json(th, "doctor", exit=None)
            warn = [c for c in doc["checks"] if c["id"].startswith("stack.grilling.unpinned:")]
            self.assertEqual([c["status"] for c in warn], ["WARN"], paths.describe(proc))
            self.assertIn("could not be compared", warn[0]["detail"])
            self.assertIn("notes.md", warn[0]["detail"])

    def test_an_unreadable_file_in_a_recorded_component_folder_is_a_warn(self):
        with inst.installer_home(tools=("claude", "node")) as th:
            script = e4c.pinned_kit(th, e4c.FILES)
            e4c.make_archive(e4c.archive_path(th), e4c.FILES)
            inst.run_json(th, "install", "--yes", "--agents", "claude-code", "--components", "core", script=script)
            with unreadable(os.path.join(th.claude_home, "skills", "grilling", "SKILL.md")):
                doc, proc = inst.run_json(th, "doctor", script=script, exit=None)
            warn = [c for c in doc["checks"] if c["id"].startswith("stack.grilling.drift:")]
            self.assertEqual([c["status"] for c in warn], ["WARN"], paths.describe(proc))
            self.assertIn("could not be checked", warn[0]["detail"])

    def test_a_settings_env_that_is_not_an_object(self):
        for env in ("ANTHROPIC_BASE_URL=https://api.z.ai/api/anthropic", ["ANTHROPIC_BASE_URL"], 7):
            with inst.installer_home(tools=("claude", "node")) as th:
                th.write(os.path.join(th.env.get("CLAUDE_CONFIG_DIR", th.claude_home), "settings.json"),
                         json.dumps({"env": env}))
                doc, proc = inst.run_json(th, "doctor", exit=None)
                ep = [c for c in doc["checks"] if c["id"] == "endpoint.claude"]
                self.assertEqual([c["status"] for c in ep], ["PASS"], (env, paths.describe(proc)))


class ComponentCommits(unittest.TestCase):
    def setUp(self):
        inst.require_installer()

    def bump(self, th, script):
        """A copy of the kit at script whose components.json pins NEW_PIN with other content (a later release)."""
        kit = os.path.join(th.root, "pinned kit B")
        shutil.copytree(os.path.dirname(os.path.dirname(script)), kit)
        path = os.path.join(kit, "install", "components.json")
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        c = data["components"][e4c.CID]
        old = c["commit"]
        c["commit"] = c["ref"] = NEW_PIN
        c["archive"]["file"] = c["archive"]["file"].replace(old, NEW_PIN)
        c["archive"]["url"] = c["archive"]["url"].replace(old, NEW_PIN)
        files = dict((rel, text.replace("test copy", "new pin")) for rel, text in e4c.FILES.items())
        for pin in c["archive"]["skills"].values():
            pin["sha256"] = e4c.content_sha256(files, pin["path"])
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            json.dump(data, f, indent=1)
        e4c.make_archive(os.path.join(th.env["UB_COMPONENTS_DIR"], c["archive"]["file"]), files,
                         top="skills-" + NEW_PIN)
        return os.path.join(kit, "install", "install.py"), old

    def test_a_kept_folder_keeps_the_commit_it_came_from(self):
        args = ("--agents", "claude-code", "--components", "core")
        with inst.installer_home(tools=("claude", "node")) as th:
            script = e4c.pinned_kit(th, e4c.FILES)
            e4c.make_archive(e4c.archive_path(th), e4c.FILES)
            inst.run_json(th, "install", "--yes", *args, script=script)
            script_b, old = self.bump(th, script)
            skills = os.path.join(th.claude_home, "skills")
            shutil.rmtree(os.path.join(skills, "domain-modeling"))
            data, _proc = inst.run_json(th, "install", "--yes", *args, script=script_b)
            self.assertIn("kept the existing", e4c.result(data, "component " + e4c.CID)[0]["detail"])
            rec = [c for c in inst.read_manifest(th)["components"] if c["id"] == e4c.CID][0]
            self.assertEqual(rec.get("commits"), {"grilling": old, "domain-modeling": NEW_PIN}, rec)
            self.assertEqual(rec["commit"], NEW_PIN, "the pin this install ran with")
            with open(os.path.join(skills, "grilling", "SKILL.md"), "a", encoding="utf-8") as f:
                f.write("edited after install\n")
            doc, _p = inst.run_json(th, "doctor", script=script_b, exit=None)
            drift = [c for c in doc["checks"] if c["id"].startswith("stack.grilling.drift:")]
            self.assertEqual([c["status"] for c in drift], ["WARN"], doc["checks"])
            self.assertIn("at %s" % old, drift[0]["detail"])
            self.assertNotIn(NEW_PIN, drift[0]["detail"])


if __name__ == "__main__":
    unittest.main()
