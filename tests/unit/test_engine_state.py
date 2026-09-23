"""B3 engine: run.json round trip, 00_RUN.md v1 lines, v1 migration, driver lock, redo / supersede (KIT_SPEC 4.1-4.3,
6.3, 6.10)."""

import json
import os
import re
import shutil
import sys
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fixtures", "engine"))
import engine_testlib as tl  # noqa: E402

from ublib import textio  # noqa: E402
from ublib.engine import migrate, pipeline  # noqa: E402
from ublib.engine import state as st  # noqa: E402
_KIT_V = open(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "VERSION"),
              encoding="utf-8").read().strip()  # kit version, so a release bump needs no test edits


class RunJsonTests(tl.EngineTestCase):
    def test_round_trip_and_schema(self):
        ctx = self.make_ctx()
        st.save(ctx.run_dir, ctx.state)
        loaded = st.load(ctx.run_dir)
        self.assertEqual(loaded["schema"], 2)
        self.assertEqual(loaded["kit_version"], _KIT_V)
        for key in ("run", "created_at", "topic", "lang", "mode", "variant", "build_type", "autopilot", "host",
                    "python", "runner", "privacy", "families", "components", "seats", "provisional", "gates",
                    "steps", "choice", "budget", "exec", "legacy_v1"):
            self.assertIn(key, loaded)
        self.assertEqual(loaded["seats"], ctx.state["seats"])
        self.assertTrue(re.match(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$", loaded["created_at"]))
        self.assertEqual(loaded["budget"]["max_calls"], 180)
        # run.json is UTF-8 without BOM, LF only
        with open(st.run_json_path(ctx.run_dir), "rb") as f:
            raw = f.read()
        self.assertFalse(raw.startswith(b"\xef\xbb\xbf"))
        self.assertNotIn(b"\r\n", raw)

    def test_unknown_schema_is_an_engine_error(self):
        ctx = self.make_ctx()
        textio.write_json_atomic(st.run_json_path(ctx.run_dir), {"schema": 9})
        with self.assertRaises(Exception):
            st.load(ctx.run_dir)

    def test_build_type_and_budget_caps(self):
        self.assertEqual(st.build_type_for("research"), "approach")
        self.assertEqual(st.build_type_for("naming"), "approach")
        self.assertEqual(st.build_type_for("software"), "system")
        for mode, cap in (("quick", 60), ("standard", 180), ("deep", 600), ("proposal", 90)):
            s = st.new_state(self.tmp, "t", "claude-code", "claude", mode=mode)
            self.assertEqual(s["budget"]["max_calls"], cap)


class RunMdTests(tl.EngineTestCase):
    def test_v1_lines_present(self):
        ctx = self.make_ctx(families=("claude", "gpt"))
        st.set_step(ctx.state, "0.1", "done", note="run created")
        st.set_step(ctx.state, "1.1", "skipped", note="not in this mode/preset")
        st.save(ctx.run_dir, ctx.state)
        text = textio.read_text(os.path.join(ctx.run_dir, "00_RUN.md"))
        self.assertTrue(text.startswith("# Run: "))
        for prefix in ("- mode: standard", "- variant: product", "- topic: shift-swap app for nurses",
                       "- autopilot: guided", "- host family: claude (claude-code)", "- other family: gpt via gpt-cli",
                       "- privacy: (a) web + other vendors: yes   (b) code facts / repo files to other vendors: no",
                       "- python: ", "- detected tools: ", "- strategy -> family map: S1=claude S2=claude",
                       "- human saw S1 ranking: n/a", "- session plan: ", "- stage log:"):
            self.assertIn("\n" + prefix if not prefix.startswith("#") else prefix, "\n" + text)
        self.assertIn("0.1 done run created", text)
        self.assertNotIn("1.1 skipped", text)  # mode skips are noise in the stage log

    def test_single_family_is_provisional(self):
        ctx = self.make_ctx(families=("claude",))
        st.save(ctx.run_dir, ctx.state)
        text = textio.read_text(os.path.join(ctx.run_dir, "00_RUN.md"))
        self.assertIn("- other family: none -> PROVISIONAL (claude-alt)", text)
        self.assertIn("PROVISIONAL", text.split("- mode:")[0] + text)

    def test_seeds_template_is_v1(self):
        text = st.seeds_doc()
        self.assertEqual(text, st.SEEDS_TEMPLATE)
        filled = st.seeds_doc("my problem", "my primary", ["a", "b"], ["obvious"], ["nope"])
        self.assertIn("## Ideas\n- a\n- b", filled)
        self.assertIn("## Primary idea (to pressure-test)\n- my primary", filled)


class NamingTests(tl.EngineTestCase):
    def test_slug_and_collision(self):
        self.assertEqual(st.slugify("AI tutor for night-shift nurses"), "ai-tutor-night-shift-nurses")
        self.assertEqual(st.slugify(""), "untitled-run")
        root = os.path.join(self.tmp, "brainstorm")
        a = st.new_run_dir(root, "habit coach app", date="2026-09-23")
        self.assertTrue(os.path.isdir(a), "new_run_dir creates the folder atomically")
        b = st.new_run_dir(root, "habit coach app", date="2026-09-23")
        self.assertTrue(b.endswith("-2"))

    def test_run_root_rules(self):
        root, note = st.run_root(None, cwd=self.project)
        self.assertEqual(root, os.path.join(self.project, "brainstorm"))
        self.assertIsNone(note)
        root, note = st.run_root(os.path.join(self.tmp, "x"))
        self.assertTrue(root.endswith(os.path.join("x", "brainstorm")))
        home = os.path.expanduser("~")
        root, note = st.run_root(None, cwd=home)
        self.assertIn("ultimate-brainstorm-runs", root)
        self.assertTrue(note)


class LockTests(tl.EngineTestCase):
    def test_lock_acquire_release_and_staleness(self):
        ctx = self.make_ctx()
        lock = st.Lock(ctx.run_dir, "claude-code")
        self.assertTrue(lock.acquire())
        self.assertTrue(os.path.exists(lock.path))
        # a live foreign holder blocks
        other = st.Lock(ctx.run_dir, "codex")
        data = textio.read_json(lock.path)
        data["pid"] = os.getppid() if hasattr(os, "getppid") else 1
        textio.write_json_atomic(lock.path, data)
        with tl.mock.patch.object(st, "_pid_alive", return_value=True):
            self.assertIsNotNone(other.holder())
            self.assertFalse(other.acquire())
            # stale after 120 s
            data["heartbeat_ts"] = time.time() - 200
            textio.write_json_atomic(lock.path, data)
            self.assertIsNone(other.holder())
            self.assertTrue(other.acquire())
        other.release()
        self.assertFalse(os.path.exists(lock.path))

    def test_dead_pid_is_stale(self):
        ctx = self.make_ctx()
        lock = st.Lock(ctx.run_dir)
        os.makedirs(os.path.dirname(lock.path), exist_ok=True)
        textio.write_json_atomic(lock.path, {"pid": 999999, "host": "x", "heartbeat_ts": time.time()})
        with tl.mock.patch.object(st, "_pid_alive", return_value=False):
            self.assertIsNone(lock.holder())


class MigrationTests(tl.EngineTestCase):
    def copy_fixture(self, name):
        dst = os.path.join(self.project, "brainstorm", name)
        shutil.copytree(tl.fixture_path("v1_run", name), dst)
        return dst

    def test_v1_run_is_migrated_and_resumes_after_stage_5(self):
        run = self.copy_fixture("2026-01-10-habit-coach")
        state = st.load(run)
        self.assertTrue(state["legacy_v1"])
        self.assertEqual(state["mode"], "standard")
        self.assertEqual(state["variant"], "product")
        self.assertEqual(state["host"]["family"], "claude")
        self.assertEqual(sorted(f for f, i in state["families"].items() if i["status"] == "ok"), ["claude", "gpt"])
        self.assertEqual(state["seats"]["generators"]["S3"], "gpt")
        self.assertEqual(state["seats"]["screen_judges"], ["claude", "gpt"])
        self.assertEqual(state["privacy"]["code"], False)
        for sid in ("0.2", "2.2", "3.1", "4.2", "5.2"):
            self.assertEqual(st.step_state(state, sid), "done", sid)
        self.assertEqual(st.step_state(state, "6.1"), "pending")
        self.assertTrue(os.path.exists(os.path.join(run, "run.json")))
        ctx = st.Ctx(run, state, tl.FakeDeps())
        cur = pipeline.current_step(ctx, pipeline.load_steps())
        self.assertEqual(cur["id"], "6.1")

    def test_finished_v1_run_gets_the_extend_offer(self):
        run = self.copy_fixture("2026-01-02-done-run")
        state = st.load(run)
        self.assertEqual((state.get("interrupt") or {}).get("gate"), "G0")
        self.assertEqual(state["choice"]["idea"], "I-002")
        self.assertEqual(state["choice"]["runner_up"], "I-001")
        self.assertEqual(st.step_state(state, "11.1"), "done")

    def test_parse_run_md(self):
        text = textio.read_text(tl.fixture_path("v1_run", "2026-01-10-habit-coach", "00_RUN.md"))
        info = migrate.parse_run_md(text)
        self.assertEqual(info["host_family"], "claude")
        self.assertTrue(info["other_ok"])
        self.assertEqual(info["strategies"], {"S1": "claude", "S2": "claude", "S3": "gpt", "S4": "claude",
                                              "S5": "gpt"})


class SupersedeTests(tl.EngineTestCase):
    def test_redo_moves_outputs_to_superseded_and_resets(self):
        ctx = self.make_ctx()
        steps = pipeline.load_steps()
        for s in steps:
            if s["id"] in ("12.1", "12.2", "13.4"):
                break
            st.set_step(ctx.state, s["id"], "done")
        st.set_step(ctx.state, "12.1", "done")
        ctx.write("10_ARCHITECTURE/00_BRIEF.md", "brief\n")
        ctx.write("10_ARCHITECTURE/brief.json", "{}\n")
        ctx.write("08_DECISION.md", "decision\n")
        ctx.state["signed_off"] = True
        moved = pipeline.supersede_from(ctx, steps, "12.1", stamp="20260923T000000Z")
        self.assertIn("10_ARCHITECTURE/00_BRIEF.md", moved)
        self.assertFalse(ctx.exists("10_ARCHITECTURE/00_BRIEF.md"))
        self.assertTrue(os.path.exists(os.path.join(ctx.run_dir, "_superseded", "20260923T000000Z", "10_ARCHITECTURE",
                                                    "00_BRIEF.md")))
        self.assertTrue(ctx.exists("08_DECISION.md"))  # upstream outputs stay
        self.assertEqual(st.step_state(ctx.state, "12.1"), "pending")
        self.assertEqual(st.step_state(ctx.state, "10.6"), "done")
        self.assertFalse(ctx.state["signed_off"])

    def test_supersede_never_deletes(self):
        ctx = self.make_ctx()
        ctx.write("a/b.md", "x\n")
        st.supersede_paths(ctx.run_dir, ["a/b.md"], "S1")
        ctx.write("a/b.md", "y\n")
        st.supersede_paths(ctx.run_dir, ["a/b.md"], "S1")  # the target exists: nothing is overwritten
        self.assertEqual(textio.read_text(os.path.join(ctx.run_dir, "_superseded", "S1", "a", "b.md")), "x\n")
        self.assertTrue(ctx.exists("a/b.md"))


class DiscoveryTests(tl.EngineTestCase):
    def test_newest_unfinished_and_index(self):
        a = self.make_ctx(run_name="2026-09-20-a")
        st.save(a.run_dir, a.state)
        b = self.make_ctx(run_name="2026-09-21-b")
        b.state["status"] = "done"
        st.save(b.run_dir, b.state)
        os.chdir(self.project)
        self.addCleanup(os.chdir, tl.KIT)
        run, how = st.newest_unfinished()
        self.assertEqual(os.path.basename(run), "2026-09-20-a")
        self.assertIn("newest unfinished run", how)
        st.register_run(a.run_dir, "a")
        self.assertIn(os.path.abspath(a.run_dir), st.indexed_runs())


class ConfigTests(tl.EngineTestCase):
    def test_config_get_set(self):
        self.assertIsNone(st.config_get("privacy_defaults"))
        st.config_set("budget.standard", st.parse_config_value("200"))
        self.assertEqual(st.config_get("budget.standard"), 200)
        st.config_set("x", st.parse_config_value("hello"))
        self.assertEqual(st.config_get("x"), "hello")
        self.assertTrue(os.path.exists(os.path.join(os.environ["UB_HOME"], "config.json")))


if __name__ == "__main__":
    unittest.main()
