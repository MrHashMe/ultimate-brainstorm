"""Phase J, engine state and pipeline: the round-4 findings on the kickoff seeds, the gap-round count, the driver's
.ub/lock.json record in an upgrade window with kit 2.0.x drivers and the late-write card (KIT_SPEC 4.2, 6.3, 6.4,
6.10).

- 0.3 merges the G0 reply's seeds into the user's seeds file (a --seeds-file, or the file written while G0 waited)
  instead of replacing it, also in proposal mode, and a re-run of 0.3 merges into the user's version again
- a redo from 5.3c or 5.3m never counts a gap round a second time
- a kit 2.0.x record whose beat is old counts while the process that wrote it runs (a 2.0.x `ub run` waiting at a
  gate), as the installer counts it; a reused pid does not
- a claim that cannot put its own record into lock.json does not drive (a program holds the file open)
- a driver whose record a 2.0.3 driver took over (it stalled for more than 120 s) stops without saving
- the engine's own rewrite of an accepted host file (2.2 normalizes criteria.json, a G2c correction) is not a late
  write of a displaced session; a real late write still is
"""

import errno
import io
import json
import os
import subprocess
import sys
import threading
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fixtures", "engine"))
import engine_testlib as tl  # noqa: E402

from ublib import proc, textio  # noqa: E402
from ublib.engine import gates, pipeline, registry  # noqa: E402
from ublib.engine import state as st  # noqa: E402

sys.path.insert(0, tl.SCRIPTS)
import ub  # noqa: E402

SEEDS = ("# Human seeds\n\n## Problem\nNurses swap shifts by phone at 3 a.m.\n\n## Primary idea (to pressure-test)\n\n"
         "## Ideas\n- a shared swap board per ward\n- auto-match by skills\n- delete the phone tree entirely\n\n"
         "## Obvious\n- a WhatsApp group\n\n## Off-limits\n- anything needing new hardware\n")
USER_LINES = ("Nurses swap shifts by phone at 3 a.m.", "- a shared swap board per ward", "- auto-match by skills",
              "- delete the phone tree entirely", "- a WhatsApp group", "- anything needing new hardware")


# holds lock.json open the way any program that opens it with Python's open() does (no FILE_SHARE_DELETE on Windows,
# so the file can be neither replaced nor moved) until the release barrier appears
HOLD_OPEN = ("import os, sys, time\nf = open(sys.argv[1], 'rb')\nopen(sys.argv[2], 'w').close()\n"
             "while not os.path.exists(sys.argv[3]): time.sleep(0.02)\nf.close()\n")


class Base(tl.EngineTestCase):
    def run_ub(self, *args, **kw):
        out = io.StringIO()
        with mock.patch.object(sys, "stdout", out):
            rc = ub.main([str(a) for a in args], deps=kw.get("deps") or tl.FakeDeps(detect=tl.fake_detect()))
        text = out.getvalue()
        return rc, (json.loads(text) if text.strip().startswith("{") else text)

    def run_dir(self):
        ctx = self.make_ctx()
        st.save(ctx.run_dir, ctx.state)
        return ctx.run_dir

    def live_process(self):
        p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
        self.addCleanup(lambda: (p.kill(), p.wait()))
        return p

    def wait_for(self, cond, what, timeout=60):
        end = time.monotonic() + timeout
        while not cond():
            if time.monotonic() > end:
                raise AssertionError("timed out waiting for " + what)
            time.sleep(0.02)

    def to_2_1g(self, autopilot):
        rc, card = self.run_ub("init", "--host", "claude-code", "--text", "standard %s shift-swap app for nurses"
                               % autopilot, "--root", self.project, "--no-preflight", "--components", "grilling",
                               "--json")
        self.assertEqual(rc, 0, card)
        for _ in range(80):
            if card.get("type") == "HOST" and card.get("step") == "2.1g":
                return card["run"], card
            self.assertIn(card.get("type"), ("HUMAN", "AUTO"), card)
            if card.get("type") == "HUMAN":
                rc, card = self.run_ub("answer", card["run"], card["gate"], "--default", "--json")
            else:
                rc, card = self.run_ub("next", card["run"], "--wait-s", "0", "--json")
        self.fail("the run never reached 2.1g")

    def lease(self, card):
        return card["task"]["done_cmd"].split("--lease ")[1].split()[0]


# ------------------------------------------------------------------------------------------------ kickoff seeds

class KickoffSeeds(Base):
    def kickoff(self, ctx, reply):
        ans = gates.merge_answer("G0", {"reply": reply}, ctx)
        ctx.state.setdefault("gates", {})["G0"] = {"state": "answered", "by": "human", "answer": ans}
        registry.write_seeds(ctx, ans)
        return ctx.read("00_HUMAN_SEEDS.md")

    def assert_kept(self, text):
        for line in USER_LINES:
            self.assertIn(line, text)

    def test_reply_seeds_are_added_to_the_users_file(self):
        ctx = self.make_ctx()
        ctx.write("00_HUMAN_SEEDS.md", SEEDS)
        text = self.kickoff(ctx, "go\nlet charge nurses approve swaps\noff-limits: paid SMS")
        self.assert_kept(text)
        self.assertIn("- let charge nurses approve swaps", text)
        self.assertIn("- paid SMS", text)
        self.assertEqual(registry.section(text, "Off-limits").split("\n"),
                         ["- anything needing new hardware", "- paid SMS"])

    def test_proposal_go_keeps_the_file_and_sets_the_primary_idea(self):
        ctx = self.make_ctx(mode="proposal")
        ctx.state["idea_text"] = "a shared swap board per ward for nurses"
        ctx.write("00_HUMAN_SEEDS.md", SEEDS)
        text = self.kickoff(ctx, "go")
        self.assert_kept(text)
        self.assertEqual(registry.section(text, "Primary idea"), "- a shared swap board per ward for nurses")

    def test_a_file_with_only_obvious_and_off_limits_keeps_them(self):
        ctx = self.make_ctx()
        ctx.write("00_HUMAN_SEEDS.md", st.seeds_doc(obvious=["a WhatsApp group"],
                                                    off_limits=["anything needing new hardware"]))
        text = self.kickoff(ctx, "go")
        self.assertEqual(registry.section(text, "Off-limits"), "- anything needing new hardware")  # no SKIPPED in it
        self.assertEqual(registry.section(text, "Obvious"), "- a WhatsApp group")
        self.assertRegex(text, r"(?m)^SKIPPED: the user replied without seeds at kickoff$")

    def test_a_re_run_merges_into_the_users_version(self):
        """A redo or a new G0 answer runs 0.3 again: the first reply's lines neither pile up nor stay."""
        ctx = self.make_ctx()
        ctx.write("00_HUMAN_SEEDS.md", SEEDS)
        self.kickoff(ctx, "go\nfirst reply idea")
        text = self.kickoff(ctx, "go\nsecond reply idea")
        self.assert_kept(text)
        self.assertNotIn("first reply idea", text)
        self.assertEqual(text.count("- second reply idea"), 1)
        self.assertEqual(text.count("- a shared swap board per ward"), 1)

    def test_a_file_the_user_changed_after_0_3_is_their_version(self):
        ctx = self.make_ctx()
        ctx.write("00_HUMAN_SEEDS.md", SEEDS)
        text = self.kickoff(ctx, "go\nfirst reply idea")
        ctx.write("00_HUMAN_SEEDS.md", text.replace("- auto-match by skills\n", "") + "- written at G1\n")
        text = self.kickoff(ctx, "go\nsecond reply idea")
        self.assertIn("- written at G1", text)
        self.assertNotIn("auto-match by skills", text)
        self.assertIn("- second reply idea", text)

    def test_an_empty_file_still_gets_the_reply_or_a_skip(self):
        ctx = self.make_ctx()
        text = self.kickoff(ctx, "go\nmy own idea one\nPrimary: test this idea")
        self.assertEqual(registry.section(text, "Ideas"), "- my own idea one")
        self.assertEqual(registry.section(text, "Primary idea"), "- test this idea")
        ctx = self.make_ctx(run_name="second")
        self.assertEqual(self.kickoff(ctx, "go"), "SKIPPED: the user replied without seeds at kickoff\n")

    def test_seeds_file_and_a_g0_idea_through_the_cli(self):
        path = os.path.join(self.tmp, "my-seeds.md")
        with open(path, "w", encoding="utf-8") as f:
            f.write(SEEDS)
        rc, card = self.run_ub("init", "--host", "claude-code", "--text", "shift-swap app for nurses", "--root",
                               self.project, "--no-preflight", "--components=", "--seeds-file", path, "--json")
        self.assertEqual((rc, card.get("gate")), (0, "G0"), card)
        with open(card["answer_file"], "w", encoding="utf-8") as f:
            json.dump({"reply": "go\nlet charge nurses approve swaps"}, f)
        run = card["run"]
        rc, card = self.run_ub("answer", run, "G0", "--file", card["answer_file"], "--json")
        # a seed line is read back before it goes to the vendors (KIT_SPEC 4.12): confirm it
        self.assertEqual((rc, card.get("gate")), (0, "G0"), card)
        self.assertTrue((card.get("error") or "").startswith("I read your reply as: "), card)
        rc, card = self.run_ub("answer", run, "G0", "--choice", "yes", "--json")
        self.assertEqual(rc, 0, card)
        with open(os.path.join(run, "00_HUMAN_SEEDS.md"), encoding="utf-8") as f:
            text = f.read()
        self.assert_kept(text)
        self.assertIn("- let charge nurses approve swaps", text)


# ------------------------------------------------------------------------------------------------ gap rounds

class GapRoundCount(Base):
    ITEMS = ["G1", "G2", "R1"]

    def round_1_curated(self, run_name=None):
        """Deep mode (2 gap rounds): round 1's gap step 5.3 and its curator 5.3c ran."""
        ctx = self.make_ctx(mode="deep", run_name=run_name)
        for s in pipeline.load_steps():
            if s["id"] == "5.3m":
                break
            st.set_step(ctx.state, s["id"], "done", note="setup")
        ctx.state["counters"].update({"gap_rounds": 0, "gap_prefix": 0, "reopen_prefix": 0,
                                      "gap_round_items": list(self.ITEMS)})
        for rel in ("pool/G1_gap.md", "pool/G2_gap.md", "pool/R1_reopen.md"):
            ctx.write(rel, "### %s-01 idea\n" % rel.split("/")[1][:2])
        return ctx

    def round_end(self, ctx, gap_needed):
        """5.3m (gap_round_end) with a map that says whether another gap round is needed."""
        ctx.write_json("coverage.json", {"gap_needed": gap_needed})
        ctx.write("03_POOL.md", "# Pool\n")
        ctx.cache.pop("rearmed", None)
        with mock.patch.object(registry, "bs", lambda *a, **kw: None):
            note = registry.run_script(ctx, "gap_round_end", pipeline.step_by_id(pipeline.load_steps(), "5.3m"))
        return note, bool(ctx.cache.pop("rearmed", False))

    def counters(self, ctx):
        return dict((k, ctx.state["counters"].get(k)) for k in ("gap_rounds", "gap_prefix", "reopen_prefix"))

    def test_a_redo_after_the_round_was_counted_counts_it_once(self):
        """NEW-I-HA-engine-flow-1: round 1's 5.3m counted the round; a redo from 5.3c (or 5.3m) runs 5.3m again, and
        the re-curated pool now needs a gap: round 2 opens, numbered after round 1 (G3, R2)."""
        for redo in ("5.3c", "5.3m"):
            ctx = self.round_1_curated(run_name="redo-" + redo)
            note, rearmed = self.round_end(ctx, False)
            st.set_step(ctx.state, "5.3m", "done", note=note)
            self.assertEqual((note, rearmed), ("gap round 1 done", False))
            pipeline.supersede_from(ctx, pipeline.load_steps(), redo)
            note, rearmed = self.round_end(ctx, True)
            self.assertEqual((note, rearmed), ("gap round 1 done; another round follows", True), redo)
            self.assertEqual(self.counters(ctx), {"gap_rounds": 1, "gap_prefix": 2, "reopen_prefix": 1})
            with mock.patch.object(registry, "gap_cells", lambda c, limit=None: [("a", "b")]):
                items = registry.FANOUTS["gap_cells"](ctx, pipeline.step_by_id(pipeline.load_steps(), "5.3"))
            self.assertEqual([it["id"][:2] for it in items][:2], ["G3", "R2"])

    def test_every_round_still_counts(self):
        """Round 2 (new items) is counted after round 1, also when a round had no items at all."""
        ctx = self.round_1_curated()
        self.assertEqual(self.round_end(ctx, True)[1], True)
        ctx.state["counters"]["gap_round_items"] = ["G3", "R2"]
        self.assertEqual(self.round_end(ctx, True), ("gap round 2 done", False))
        self.assertEqual(self.counters(ctx), {"gap_rounds": 2, "gap_prefix": 3, "reopen_prefix": 2})
        ctx = self.round_1_curated(run_name="no-items")
        ctx.state["counters"]["gap_round_items"] = []
        self.assertEqual(self.round_end(ctx, True)[1], True)
        self.assertEqual(self.round_end(ctx, True), ("gap round 2 done", False))

    def test_a_redo_at_the_gap_step_counts_the_new_round(self):
        ctx = self.round_1_curated()
        note, _rearmed = self.round_end(ctx, False)
        st.set_step(ctx.state, "5.3m", "done", note=note)
        pipeline.supersede_from(ctx, pipeline.load_steps(), "5.3")
        self.assertEqual(self.counters(ctx), {"gap_rounds": 0, "gap_prefix": 0, "reopen_prefix": 0})
        ctx.state["counters"]["gap_round_items"] = list(self.ITEMS)  # the new round 1 reuses the numbers
        self.assertEqual(self.round_end(ctx, False)[0], "gap round 1 done")
        self.assertEqual(self.counters(ctx), {"gap_rounds": 1, "gap_prefix": 2, "reopen_prefix": 1})


# ------------------------------------------------------------------------------------------------ driver lock

class Later(object):
    """The clock of the state module `ahead` seconds later (only time.time; monotonic time and sleep are real)."""

    def __init__(self, ahead):
        self.ahead = ahead

    def time(self):
        return time.time() + self.ahead

    def __getattr__(self, name):
        return getattr(time, name)


class LegacyLiveness(Base):
    def record(self, pid, beat):
        return {"pid": pid, "host": "terminal", "heartbeat_at": "", "heartbeat_ts": beat}

    def test_a_2_0_x_terminal_waiting_at_a_gate_keeps_the_run(self):
        """Review (engine) P3: a 2.0.x `ub run` holds lock.json while it waits at a gate and beats no more. Its record
        counts while the process that wrote it runs (it started before that beat), as install.py counts it; the engine
        took the run after 120 s and both kits then drove it."""
        run = self.run_dir()
        p = self.live_process()
        started = proc.process_start_time(p.pid)
        self.assertIsNotNone(started)
        info = os.path.join(run, ".ub", "lock.json")
        rec = self.record(p.pid, started + 0.5)
        textio.write_json_atomic(info, rec)
        lock = st.DriverLock(run, "claude-code")
        self.assertTrue(lock.acquire())
        try:
            with mock.patch.object(st, "time", Later(st.LEGACY_STALE_S + 300)):
                self.assertEqual(lock.claim(), rec)
                self.assertEqual(lock.legacy_holder(), rec)
        finally:
            lock.release()
        self.assertEqual(textio.read_json(info), rec)

    def test_the_rule_is_the_installers(self):
        """A live pid, not this process, and a beat within 120 s, or an older beat of a process that started no later
        than 1 s after it; never a record with `since`, nor a beat more than 120 s ahead."""
        p = self.live_process()
        started = proc.process_start_time(p.pid)

        def live(record, now=None):  # as DriverLock.legacy_holder asks: never this process
            return proc.legacy_driver_live(record, self.tmp, now=now, exclude_pid=os.getpid())
        self.assertTrue(live(self.record(p.pid, started + 10), now=started + 20))
        self.assertTrue(live(self.record(p.pid, started + 10), now=started + 1000))
        self.assertFalse(live(self.record(p.pid, started - 5), now=started + 1000))  # a reused pid
        self.assertTrue(live(self.record(p.pid, started - 5), now=started + 60))  # a fresh beat decides alone
        self.assertFalse(live(self.record(p.pid, started + 200), now=started + 10))  # ahead by more than 120 s
        self.assertFalse(live(dict(self.record(p.pid, started + 10), since="x"), now=started + 20))
        self.assertFalse(live(self.record(os.getpid(), time.time())))
        self.assertFalse(live(self.record("x", time.time())))
        self.assertFalse(live(self.record(p.pid, "x")))
        p.kill()
        p.wait()
        self.assertFalse(live(self.record(p.pid, time.time())))


@unittest.skipUnless(os.name == "nt", "a file open in another program blocks a replace only on Windows")
class ClaimHeldOpen(Base):
    def hold_open(self, info):
        opened, release = os.path.join(self.tmp, "opened"), os.path.join(self.tmp, "release")
        h = subprocess.Popen([sys.executable, "-c", HOLD_OPEN, info, opened, release])
        self.addCleanup(lambda: (open(release, "w").close(), h.wait()))
        self.wait_for(lambda: os.path.exists(opened) or h.poll() is not None, "the helper to open lock.json")
        return h, release

    def test_a_record_that_cannot_be_replaced_is_not_driven_past(self):
        """Review (engine) P3: a stale 2.0.3 record that another program holds open can be neither moved aside nor
        replaced. The claim returned None and the command drove the run while lock.json still named the stale
        driver, so the next 2.0.3 driver took the run too. Now the command is refused and changes nothing."""
        run = self.run_dir()
        info = os.path.join(run, ".ub", "lock.json")
        stale = {"pid": 999999, "host": "codex", "heartbeat_at": "", "heartbeat_ts": time.time() - 500}
        textio.write_json_atomic(info, stale)
        before = textio.read_bytes(os.path.join(run, "run.json"))
        h, release = self.hold_open(info)
        called = []
        card = ub.with_run(run, tl.FakeDeps(), lambda ctx, lock: called.append(1), host="claude-code")
        self.assertEqual((card["type"], called), ("AUTO", []), card)
        self.assertIn("another session is driving this run", card["say"])
        self.assertEqual(textio.read_json(info), stale)
        self.assertEqual(textio.read_bytes(os.path.join(run, "run.json")), before)
        open(release, "w").close()
        h.wait()
        seen = ub.with_run(run, tl.FakeDeps(), lambda ctx, lock: lock.holder(), host="claude-code")
        self.assertEqual((seen["pid"], seen["host"]), (os.getpid(), "claude-code"))
        self.assertIn("since", seen)


class LostRecord(Base):
    SCRIPT = [{"id": "0.1", "stage": 0, "title": "No-op", "type": "SCRIPT", "script": "noop"}]

    def claimed(self):
        run = self.run_dir()
        lock = st.DriverLock(run, "claude-code")
        self.assertTrue(lock.acquire())
        self.addCleanup(lock.release)
        self.assertIsNone(lock.claim())
        return run, lock

    def take_over(self, run):
        """A kit 2.0.3 driver took lock.json over: it judged the record stale while this driver was suspended."""
        p = self.live_process()
        rec = {"pid": p.pid, "host": "codex", "heartbeat_at": textio.now_iso(), "heartbeat_ts": time.time()}
        textio.write_json_atomic(os.path.join(run, ".ub", "lock.json"), rec)
        return rec

    def test_a_driver_that_lost_its_record_stops_without_saving(self):
        """NEW-I-HB-engine-cli-1: after the stall this driver saved run.json on and the two drivers lost each other's
        updates; it must stop without saving, as kit 2.0.3 did."""
        run, lock = self.claimed()
        ctx = st.Ctx(run, st.load(run), tl.FakeDeps())
        rec = self.take_over(run)
        before = textio.read_bytes(os.path.join(run, "run.json"))
        card = pipeline.advance(ctx, self.SCRIPT, 0, lock)
        self.assertEqual(card["type"], "BLOCKED", card)
        self.assertIn("another session took over this run; this one stopped without saving", card["say"])
        self.assertEqual(textio.read_bytes(os.path.join(run, "run.json")), before)
        self.assertEqual(textio.read_json(os.path.join(run, ".ub", "lock.json")), rec)

    def test_the_beat_sees_the_takeover_and_never_writes_over_it(self):
        with mock.patch.object(st, "LEGACY_BEAT_S", 0.05):
            run, lock = self.claimed()
            rec = self.take_over(run)
            self.wait_for(lambda: not lock._beat[0].is_alive(), "the beat to stop")
        self.assertFalse(lock.still_ours())
        self.assertEqual(textio.read_json(os.path.join(run, ".ub", "lock.json")), rec)

    def beat_meets_takeover(self, when):
        """CI run 36714156939: a 2.0.3 takeover landed between the beat's check and its write; the beat wrote over it,
        then saw its own record, never stopped, and its driver would have saved over the other driver's run.json.
        Here the beat's first change to lock.json after the claim meets a 2.0.3 takeover: `before` it, `after` it (the
        record is moved aside), or the record is `gone` (a 2.0.3 driver moved it aside and has not created its own
        yet). The takeover stands (a record that went away is never recreated) and the beat stops."""
        armed, taken, real = {}, [], textio._replace_with_retry

        def replace(src, dst, *args):
            if taken or not armed or threading.current_thread().name != "ub-driver-beat":
                return real(src, dst, *args)
            taken.append(None)  # the takeover's own write passes through
            if when == "gone":
                os.remove(os.path.join(armed["run"], ".ub", "lock.json"))
            elif when == "before":
                taken[0] = self.take_over(armed["run"])
            real(src, dst, *args)
            if when == "after":
                taken[0] = self.take_over(armed["run"])
        with mock.patch.object(st, "LEGACY_BEAT_S", 0.05), \
                mock.patch.object(textio, "_replace_with_retry", side_effect=replace):
            run, lock = self.claimed()
            armed["run"] = run
            self.wait_for(lambda: not lock._beat[0].is_alive(), "the beat to stop")
        self.assertTrue(taken, "the beat never changed lock.json")
        self.assertFalse(lock.still_ours())
        info = os.path.join(run, ".ub", "lock.json")
        self.assertEqual(textio.read_json_or(info), taken[0])
        self.assertEqual([n for n in os.listdir(os.path.dirname(info)) if n.startswith("lock.json.")], [])

    def test_a_takeover_right_before_the_beat_writes_stands(self):
        self.beat_meets_takeover("before")

    def test_a_takeover_while_the_beat_writes_stands(self):
        self.beat_meets_takeover("after")

    def test_a_record_that_went_away_is_not_recreated_by_the_beat(self):
        self.beat_meets_takeover("gone")

    def test_a_takeover_is_put_back_where_hard_links_fail(self):
        """Review 2.1.1: on a file system without hard links (exFAT, FAT32, some network shares) the put-back link
        failed and the 2.0.3 record moved aside was deleted; its bytes are now copied back with an exclusive create."""
        with mock.patch.object(os, "rename" if os.name == "nt" else "link",
                               side_effect=PermissionError(errno.EPERM, "no hard links here")):
            self.beat_meets_takeover("before")

    def test_the_copy_back_never_writes_over_a_takeover(self):
        with mock.patch.object(os, "rename" if os.name == "nt" else "link",
                               side_effect=PermissionError(errno.EPERM, "no hard links here")):
            self.beat_meets_takeover("after")

    def test_a_takeover_while_a_command_announces_stops_it_without_saving(self):
        """Review 2.1.1: announce moves the record aside as the beat does, at the start of every command; a 2.0.3
        driver that creates its record in that moment takes the run. The command went on and saved run.json over the
        other driver's; it now stops before it saves anything."""
        run = self.run_dir()
        info = os.path.join(run, ".ub", "lock.json")
        before = textio.read_bytes(os.path.join(run, "run.json"))
        taken, real = [], textio._replace_with_retry

        def replace(src, dst, *args):
            if taken or os.path.normcase(src) != os.path.normcase(info) or                     threading.current_thread().name == "ub-driver-beat":
                return real(src, dst, *args)
            taken.append(None)
            real(src, dst, *args)
            taken[0] = self.take_over(run)
        with mock.patch.object(textio, "_replace_with_retry", side_effect=replace):
            card = ub.with_run(run, tl.FakeDeps(), lambda ctx, lock: self.fail("drove the run"))
        self.assertTrue(taken, "announce never moved lock.json aside")
        self.assertEqual(card["type"], "BLOCKED", card)
        self.assertIn("another session took over this run; this one stopped without saving", card["say"])
        self.assertEqual(textio.read_bytes(os.path.join(run, "run.json")), before)
        self.assertEqual(textio.read_json(info), taken[0])

    def meets_takeover(self, run, target, name, *args):
        """Review 2.1.1, the known gap: a 2.0.3 takeover that landed after the command's announce check, while it
        applied its one change, still saved that change over the other driver's run.json (a 2.0.3 save keeps the rev
        it loaded, so the rev check missed it). The takeover lands here as `target.name` runs; state.save refuses."""
        before = textio.read_bytes(os.path.join(run, "run.json"))
        taken, real = [], getattr(target, name)

        def take_over_first(*a, **kw):
            if not taken:
                taken.append(self.take_over(run))
            return real(*a, **kw)
        with mock.patch.object(target, name, side_effect=take_over_first):
            rc, card = self.run_ub(*args)
        self.assertTrue(taken, "%s never ran" % name)
        self.assertEqual(card["type"], "BLOCKED", card)
        self.assertIn("another session took over this run; this one stopped without saving", card["say"])
        self.assertIn("this %s was not applied" % args[0], card["notes"])
        self.assertTrue(card["fix"], card)
        self.assertEqual(textio.read_bytes(os.path.join(run, "run.json")), before)
        self.assertEqual(textio.read_json(os.path.join(run, ".ub", "lock.json")), taken[0])

    def test_a_takeover_before_a_gate_answer_saves_stops_it_without_saving(self):
        rc, card = self.run_ub("init", "--host", "claude-code", "--text", "standard guided shift-swap app for nurses",
                               "--root", self.project, "--no-preflight", "--json")
        self.assertEqual((card["type"], card["gate"]), ("HUMAN", "G0"), card)
        self.meets_takeover(card["run"], gates, "apply", "answer", card["run"], "G0", "--default", "--json")

    def test_a_takeover_before_a_host_done_saves_stops_it_without_saving(self):
        run, card = self.to_2_1g("guided")
        textio.write_text_atomic(os.path.join(run, "01_FRAME.md"), FRAME)
        textio.write_text_atomic(os.path.join(run, "criteria.json"), '{"Value": 60, "Feasibility": 40}\n')
        self.meets_takeover(run, pipeline, "_make_durable", "done", run, "2.1g", "--lease", self.lease(card), "--json")

    def test_a_takeover_while_a_terminal_run_drives_stops_it_without_saving(self):
        seen = []

        def loop(ctx, steps, lock=None, **kw):
            seen.append((self.take_over(ctx.run_dir), textio.read_bytes(ctx.path("run.json"))))
            st.add_note(ctx.state, "the terminal's change")
            st.save(ctx.run_dir, ctx.state)
            self.fail("saved over the takeover")
        with mock.patch("ublib.engine.terminal.run_loop", loop):
            rc, card = self.run_ub("run", "--text", "standard shift-swap app for nurses", "--root", self.project,
                                   "--no-preflight", "--json")
        self.assertEqual(card["type"], "BLOCKED", card)
        self.assertIn("another session took over this run; this one stopped without saving", card["say"])
        self.assertTrue(card["fix"], card)
        self.assertEqual(textio.read_bytes(os.path.join(card["run"], "run.json")), seen[0][1])
        self.assertEqual(textio.read_json(os.path.join(card["run"], ".ub", "lock.json")), seen[0][0])

    def test_a_takeover_before_stop_saves_names_the_other_session(self):
        run = self.run_dir()
        before = textio.read_bytes(os.path.join(run, "run.json"))
        taken, real = [], ub.load_ctx

        def load_ctx(run_dir, deps=None, persist=False):
            if persist and not taken:  # under the lock
                taken.append(self.take_over(run))
            return real(run_dir, deps, persist)
        with mock.patch.object(ub, "load_ctx", load_ctx):
            rc, res = self.run_ub("stop", run, "--json")
        self.assertTrue(taken, "stop never loaded the run under its lock")
        self.assertIn("A session of an older kit (2.0.3) is driving this run", res["say"])
        self.assertEqual(textio.read_bytes(os.path.join(run, "run.json")), before)

    def probed(self, run, back):
        """A kit 2.0.3 driver judged this driver's record stale (it stalled), moved it aside to take it over, saw the
        beat had rewritten it and puts it back (`back`), while this driver waits to look again; or it stays away."""
        info = os.path.join(run, ".ub", "lock.json")
        os.replace(info, info + ".stale-test")

        def sleep(_s):
            if back and not os.path.exists(info):
                os.replace(info + ".stale-test", info)
        return mock.patch.object(st, "time", mock.Mock(wraps=time, sleep=sleep))

    def test_a_record_put_back_at_once_is_still_ours(self):
        """Review 2.1.1: the lock counted as lost in the moment a 2.0.3 driver checked the record, and a command
        stopped for nothing ("another session took over this run")."""
        run, lock = self.claimed()
        with self.probed(run, back=True):
            self.assertTrue(lock.still_ours())
        with self.probed(run, back=True):
            self.assertTrue(lock._write())
        self.assertTrue(lock.still_ours())
        self.assertEqual(lock.holder().get("pid"), os.getpid())

    def test_a_record_that_stays_away_is_lost(self):
        run, lock = self.claimed()
        with self.probed(run, back=False):
            self.assertFalse(lock.still_ours())
        self.assertFalse(os.path.exists(os.path.join(run, ".ub", "lock.json")))

    def test_a_driver_that_keeps_its_record_saves(self):
        run, lock = self.claimed()
        ctx = st.Ctx(run, st.load(run), tl.FakeDeps())
        card = pipeline.advance(ctx, self.SCRIPT, 0, lock)
        self.assertEqual(card["type"], "DONE", card)
        self.assertTrue(lock.still_ours())
        self.assertEqual(st.step_state(st.load(run), "0.1"), "done")


# ------------------------------------------------------------------------------------------------ late writes

FRAME = ("# FRAME: shift-swap\n## Job statement (anchor-stripped)\nswap shifts\n## Problem\nHow might night nurses "
         "swap shifts?\n## Audience / boundary\nnurses\n## Success looks like\nswaps\n## Hard constraints (gates)\n"
         "none\n## Soft constraints\nnone\n## Non-goals\nnone\n## Criteria\n- Value 60\n- Feasibility 40\n"
         "## Axes\nnone\n## Mode, privacy, budget\nstandard\n")


class EngineRewrites(Base):
    """Review (engine) P3: session A's 2.1g task is taken over by session B (`continue`), whose done is accepted;
    then the engine changes an accepted file, and A, which wrote nothing, runs its done."""

    def displaced_done(self, autopilot, criteria, corrections=None, late_frame=None):
        run, card_a = self.to_2_1g(autopilot)
        rc, card_b = self.run_ub("continue", run, "--json")
        self.assertEqual((card_b["type"], card_b["step"]), ("HOST", "2.1g"), card_b)
        textio.write_text_atomic(os.path.join(run, "01_FRAME.md"), FRAME)
        textio.write_text_atomic(os.path.join(run, "criteria.json"), criteria)
        rc, card = self.run_ub("done", run, "2.1g", "--lease", self.lease(card_b), "--json")
        self.assertEqual(st.step_state(st.load(run), "2.1g"), "done", card)
        if late_frame is not None:  # session A really writes after the takeover (before the G2c answer)
            textio.write_text_atomic(os.path.join(run, "01_FRAME.md"), late_frame)
        if corrections is not None:
            self.assertEqual((card["type"], card.get("gate")), ("HUMAN", "G2c"), card)
            path = os.path.join(self.tmp, "g2c.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"corrections": corrections}, f)
            rc, card = self.run_ub("answer", run, "G2c", "--file", path, "--json")
            self.assertIn("## User corrections", textio.read_text(os.path.join(run, "01_FRAME.md")))
        rc, card = self.run_ub("done", run, "2.1g", "--lease", self.lease(card_a), "--json")
        return card

    def test_2_2_normalizing_the_criteria_is_no_late_write(self):
        card = self.displaced_done("guided", '{"Value": 0.6, "Feasibility": 0.4}\n')
        self.assertNotEqual(card["type"], "BLOCKED", card)
        self.assertIn("step 2.1g is not waiting for a host task", card.get("notes") or [])

    def test_a_g2c_correction_is_no_late_write(self):
        card = self.displaced_done("hands-on", '{"Value": 60, "Feasibility": 40}\n', corrections="Night shifts only.")
        self.assertNotEqual(card["type"], "BLOCKED", card)

    def test_a_late_write_before_the_correction_is_still_named(self):
        card = self.displaced_done("hands-on", '{"Value": 60, "Feasibility": 40}\n', corrections="Night shifts only.",
                                   late_frame=FRAME.replace("night nurses", "session A's nurses"))
        self.assertEqual(card["type"], "BLOCKED", card)
        self.assertIn("01_FRAME.md changed after that", card["say"])


if __name__ == "__main__":
    unittest.main()
