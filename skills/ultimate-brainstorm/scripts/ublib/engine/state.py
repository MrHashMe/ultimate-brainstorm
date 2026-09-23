"""Run state: run.json (4.2) load/save, 00_RUN.md (4.3), locks, events, run discovery, supersede (6.10).

Every save writes run.json atomically and re-renders 00_RUN.md, whose v1-compatible lines `bs.py` parses.
"""

import datetime
import glob
import json
import os
import re
import shutil
import time

from .. import textio
from . import (BUDGET_CAPS, ENGINE_VERSION, EngineError, FAMILY_ORDER, HOST_WAIT_S, VENDORS, base_family,
               vendor_of)

RUN_FILE = "run.json"
RUN_MD = "00_RUN.md"
LOCK_STALE_S = 120
V2_DIRS = ("prompts", "pool", "screen", "checks", "tournament", "redteam", "logs", "jobs", "frame", "gates",
           "answers", "quick", ".ub", ".ub/jobs")
V1_SUBDIRS = ("prompts", "pool", "screen", "checks", "tournament", "redteam", "logs")
LEDGER_HEADER = (
    "# Brainstorm ledger (append-only; one row per finalist, parked or killed shortlist idea)\n\n"
    "| date | run | id | title | status | reason / K-rule | revive trigger |\n"
    "|---|---|---|---|---|---|---|\n"
)
SEEDS_TEMPLATE = (
    "# Human seeds (write alone, before seeing any AI idea; or replace everything with 'SKIPPED: <reason>')\n\n"
    "## Problem\n\n## Primary idea (to pressure-test)\n\n## Ideas\n\n## Obvious\n\n## Off-limits\n"
)
SLUG_STOP = set("a an the and or for of to in on at by with from into about my our your their this that these "
                "those is are be it its as we i you me how what why which who".split())


# ---------------------------------------------------------------- homes and config

def ub_home():
    """UB_HOME, otherwise ~/.ultimate-brainstorm (3.2)."""
    env = os.environ.get("UB_HOME")
    if env:
        return os.path.abspath(os.path.expanduser(env))
    return os.path.join(os.path.expanduser("~"), ".ultimate-brainstorm")


def config_path():
    return os.path.join(ub_home(), "config.json")


def load_config():
    path = config_path()
    if not os.path.exists(path):
        return {}
    try:
        value = textio.read_json(path)
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def save_config(cfg):
    textio.write_json_atomic(config_path(), cfg)


def config_get(key, default=None):
    cur = load_config()
    for part in str(key).split("."):
        if not isinstance(cur, dict) or part not in cur:
            return default
        cur = cur[part]
    return cur


def config_set(key, value):
    cfg = load_config()
    cur = cfg
    parts = str(key).split(".")
    for part in parts[:-1]:
        if not isinstance(cur.get(part), dict):
            cur[part] = {}
        cur = cur[part]
    cur[parts[-1]] = value
    save_config(cfg)
    return cfg


def parse_config_value(text):
    """`ub config set` values: JSON when it parses (true, 3, {"a":1}), otherwise the raw string."""
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        return text


# ---------------------------------------------------------------- run roots and names

def _is_home_or_drive_root(path):
    p = os.path.normcase(os.path.abspath(path)).rstrip("\\/")
    home = os.path.normcase(os.path.abspath(os.path.expanduser("~"))).rstrip("\\/")
    if p == home:
        return True
    drive, rest = os.path.splitdrive(os.path.abspath(path))
    return rest in ("", "\\", "/")


def run_root(root=None, cwd=None):
    """Run root (3.2): --root DIR, else <cwd>/brainstorm, else ~/ultimate-brainstorm-runs/brainstorm when the cwd is
    the home folder or a drive root. Returns (abs path, note or None)."""
    if root:
        root = os.path.abspath(os.path.expanduser(root))
        if os.path.basename(root.rstrip("\\/")) != "brainstorm":
            root = os.path.join(root, "brainstorm")
        return root, None
    cwd = os.path.abspath(cwd or os.getcwd())
    if _is_home_or_drive_root(cwd):
        alt = os.path.join(os.path.expanduser("~"), "ultimate-brainstorm-runs", "brainstorm")
        return alt, "Your current folder is the home folder or a drive root, so runs go to %s." % textio.to_posix(alt)
    return os.path.join(cwd, "brainstorm"), None


def slugify(topic, max_words=5):
    """3-5 lowercase ASCII words from the topic, joined by '-' (3.2)."""
    text = (topic or "").lower()
    text = text.encode("ascii", "ignore").decode("ascii")
    words = re.findall(r"[a-z0-9]+", text)
    kept = [w for w in words if w not in SLUG_STOP] or words
    kept = kept[:max_words]
    if not kept:
        return "untitled-run"
    if len(kept) < 3 and len(words) >= 3:
        kept = words[:max(3, len(kept))][:max_words]
    return "-".join(kept)[:60].strip("-") or "untitled-run"


def today_utc():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")


def new_run_dir(root, topic, date=None):
    """<root>/<YYYY-MM-DD>-<slug>, with -2, -3 ... on collision. The folder is created here (an atomic mkdir), so two
    `ub init` calls with the same topic never share one run folder."""
    base = "%s-%s" % (date or today_utc(), slugify(topic))
    os.makedirs(root, exist_ok=True)
    cand = os.path.join(root, base)
    n = 2
    while True:
        try:
            os.mkdir(cand)
            return cand
        except FileExistsError:
            cand = os.path.join(root, "%s-%d" % (base, n))
            n += 1


def ensure_run_dirs(run_dir):
    """The v1 `bs.py init` behavior plus the v2 folders (idempotent)."""
    for sub in V1_SUBDIRS + V2_DIRS:
        os.makedirs(os.path.join(run_dir, *sub.split("/")), exist_ok=True)
    ledger = os.path.join(os.path.dirname(os.path.abspath(run_dir)), "LEDGER.md")
    if not os.path.exists(ledger):
        textio.write_text_atomic(ledger, LEDGER_HEADER)
    seeds = os.path.join(run_dir, "00_HUMAN_SEEDS.md")
    if not os.path.exists(seeds):
        textio.write_text_atomic(seeds, seeds_doc())


def seeds_doc(problem="", primary=None, ideas=None, obvious=None, off_limits=None):
    """00_HUMAN_SEEDS.md in the v1 format (templates/docs/SEEDS.md); empty values give the v1 empty template."""
    def lst(v):
        if not v:
            return ""
        if isinstance(v, str):
            v = [v]
        return "\n".join("- %s" % x for x in v if x)
    mapping = {"SEEDS_PROBLEM": problem or "", "SEEDS_PRIMARY": lst(primary), "SEEDS_IDEAS": lst(ideas),
               "SEEDS_OBVIOUS": lst(obvious), "SEEDS_OFF_LIMITS": lst(off_limits)}
    try:
        from . import builders
        text = builders.render_doc("SEEDS", mapping)
    except Exception:
        text = None
    if text:
        return text
    if not any(mapping.values()):
        return SEEDS_TEMPLATE
    return ("# Human seeds\n\n## Problem\n%s\n\n## Primary idea (to pressure-test)\n%s\n\n## Ideas\n%s\n\n"
            "## Obvious\n%s\n\n## Off-limits\n%s\n" % (mapping["SEEDS_PROBLEM"], mapping["SEEDS_PRIMARY"],
                                                       mapping["SEEDS_IDEAS"], mapping["SEEDS_OBVIOUS"],
                                                       mapping["SEEDS_OFF_LIMITS"]))


# ---------------------------------------------------------------- run.json

def new_state(run_dir, topic, host_agent, host_family, family_source="default", mode="standard", variant="general",
              autopilot="guided", lang="en", python="python", runner="", project_dir=None):
    """A fresh schema-2 state (4.2)."""
    variant = variant or "general"
    return {
        "schema": 2,
        "kit_version": ENGINE_VERSION,
        "run": os.path.basename(os.path.abspath(run_dir)),
        "created_at": textio.now_iso(),
        "topic": topic or "",
        "lang": lang or "en",
        "mode": mode,
        "variant": variant,
        "build_type": build_type_for(variant),
        "autopilot": autopilot,
        "host": {"agent": host_agent, "family": host_family, "family_source": family_source},
        "python": python,
        "runner": runner,
        "privacy": {"web": True, "vendors": True, "code": False, "allowed_vendors": []},
        "families": {},
        "components": {},
        "seats": {},
        "provisional": [],
        "gates": {},
        "steps": {},
        "choice": {"idea": None, "runner_up": None, "arch": None, "arch_family": None},
        "budget": {"max_calls": budget_cap(mode), "max_usd": None},
        "exec": {"wait_s": HOST_WAIT_S.get(host_agent, 50)},
        "legacy_v1": False,
        # Engine extras (not read by other builders).
        "project_dir": textio.to_posix(project_dir or os.getcwd()),
        "options": {"with_ce_ideate": False, "explicit_privacy": False, "private": False},
        "counters": {"launched": 0, "gap_rounds": 0, "g13_loops": 0, "g2c_loops": 0, "g10_loops": 0},
        "interrupt": None,
        "status": "active",
        "notes": [],
        "idea_text": "",
    }


def budget_cap(mode):
    """budget.max_calls for a mode: `ub config set budget.<mode> N` (UB_HOME/config.json), else the 6.1 default."""
    try:
        v = int(config_get("budget.%s" % mode))
        if v > 0:
            return v
    except (TypeError, ValueError):
        pass
    return BUDGET_CAPS.get(mode, 180)


def build_type_for(variant):
    return "approach" if variant in ("research", "marketing", "creative", "naming") else "system"


def run_json_path(run_dir):
    return os.path.join(run_dir, RUN_FILE)


def exists(run_dir):
    return os.path.exists(run_json_path(run_dir))


def load(run_dir):
    """Load run.json. A v1 folder (00_RUN.md, no run.json) is migrated first (6.10)."""
    path = run_json_path(run_dir)
    if not os.path.exists(path):
        if os.path.exists(os.path.join(run_dir, RUN_MD)):
            from . import migrate
            state = migrate.migrate_v1(run_dir)
            save(run_dir, state)
            return state
        raise EngineError("no run.json in %s" % textio.to_posix(run_dir),
                          fix=["check the run path, or start a new run with: ub init --text \"<topic>\""])
    try:
        state = textio.read_json(path)
    except (OSError, ValueError) as e:
        raise EngineError("run.json is unreadable: %s" % e)
    if not isinstance(state, dict) or state.get("schema") != 2:
        raise EngineError("run.json has an unknown schema (expected 2)")
    _fill_defaults(state, run_dir)
    return state


def _fill_defaults(state, run_dir):
    fresh = new_state(run_dir, state.get("topic", ""), (state.get("host") or {}).get("agent", "other"),
                      (state.get("host") or {}).get("family", "claude"))
    for key, value in fresh.items():
        if key not in state:
            state[key] = value
    for key in ("options", "counters"):
        for k, v in fresh[key].items():
            state[key].setdefault(k, v)
    state.setdefault("choice", {})
    for k in ("idea", "runner_up", "arch", "arch_family"):
        state["choice"].setdefault(k, None)


def save(run_dir, state):
    """Atomic run.json write + 00_RUN.md render."""
    textio.write_json_atomic(run_json_path(run_dir), state)
    textio.write_text_atomic(os.path.join(run_dir, RUN_MD), render_run_md(state))


# ---------------------------------------------------------------- 00_RUN.md (4.3)

def other_family_line(state):
    fams = state.get("families") or {}
    host = (state.get("host") or {}).get("family")
    others = []
    for f in FAMILY_ORDER:
        info = fams.get(f) or {}
        if f == host or info.get("status") != "ok":
            continue
        if not family_allowed(state, f):
            continue
        others.append("%s via %s" % (f, info.get("backend") or "?"))
    if others:
        return ", ".join(others)
    return "none -> PROVISIONAL (%s-alt)" % (host or "host")


def family_allowed(state, fam):
    allowed = (state.get("privacy") or {}).get("allowed_vendors")
    if not allowed:
        return True
    return vendor_of(fam) in allowed


def strategy_map_line(state):
    gens = ((state.get("seats") or {}).get("generators")) or {}
    if not gens:
        return "(assigned after kickoff)"
    return " ".join("%s=%s" % (k, gens[k]) for k in sorted(gens, key=_strategy_sort_key))


def _strategy_sort_key(k):
    m = re.match(r"^([A-Z]+)(\d*)", k)
    if not m:
        return (k, 0)
    return (m.group(1), int(m.group(2) or 0))


def _yes(v):
    return "yes" if v else "no"


def stage_log_lines(state):
    """'  - <ISO> <step> <state> <note>' lines (steps skipped because they are not in this mode are left out)."""
    entries = []
    for sid, st in (state.get("steps") or {}).items():
        if st.get("at") and st.get("state") in ("done", "failed", "skipped", "blocked"):
            if st.get("state") == "skipped" and st.get("note") in ("not in this mode/preset", None, ""):
                continue
            entries.append((st["at"], sid, st.get("state"), st.get("note", "")))
    for gid, g in (state.get("gates") or {}).items():
        if g.get("at") and g.get("state") in ("answered", "auto", "skipped"):
            entries.append((g["at"], gid, g.get("state"), "by %s" % g.get("by", "?")))
    entries.sort()
    return ["  - %s %s %s %s" % (at, sid, st, " ".join(str(note or "").split())) for at, sid, st, note in
            entries[-200:]]


def render_run_md(state):
    """00_RUN.md from templates/docs/RUN.md (v1-compatible lines); built-in layout when the template is missing."""
    priv = state.get("privacy") or {}
    host = state.get("host") or {}
    comps = state.get("components") or {}
    detected = ", ".join("%s" % v for k, v in sorted(comps.items()) if v) or "none"
    seats = state.get("seats") or {}
    s1 = seats.get("s1_engine")
    saw = state.get("human_saw_s1")
    if saw is None:
        saw = "n/a" if s1 != "ce-ideate" else "no"
    banner = ""
    if single_family(state) and state.get("families"):
        banner = "PROVISIONAL: only one model family is available; every other seat is %s-alt" % host.get(
            "family", "host")
    elif state.get("provisional"):
        banner = "PROVISIONAL: %d seat(s) ran on a substitute (see run.json provisional)" % len(state["provisional"])
    try:
        from . import builders
        text = builders.render_doc("RUN", {
            "SLUG": state.get("run", ""), "PROVISIONAL_BANNER": banner, "MODE": state.get("mode", "standard"),
            "VARIANT": state.get("variant", "general"), "TOPIC": " ".join(str(state.get("topic", "")).split()),
            "AUTOPILOT": state.get("autopilot", "guided"), "HOST_FAMILY": host.get("family", "?"),
            "HOST_AGENT": host.get("agent", "?"), "OTHER_FAMILIES": other_family_line(state),
            "PRIVACY_A": _yes(priv.get("web") and priv.get("vendors")), "PRIVACY_B": _yes(priv.get("code")),
            "PYTHON": state.get("python", "python"), "DETECTED_TOOLS": detected,
            "STRATEGY_MAP": strategy_map_line(state), "S1_SEEN": saw,
            "STAGE_LOG": "\n".join(stage_log_lines(state))})
    except Exception:
        text = None
    if text:
        return text
    lines = [
        "# Run: %s" % state.get("run", ""),
        "- mode: %s" % state.get("mode", "standard"),
        "- variant: %s" % state.get("variant", "general"),
        "- topic: %s" % " ".join(str(state.get("topic", "")).split()),
        "- autopilot: %s" % state.get("autopilot", "guided"),
        "- host family: %s (%s)" % (host.get("family", "?"), host.get("agent", "?")),
        "- other family: %s" % other_family_line(state),
        "- privacy: (a) web + other vendors: %s   (b) code facts / repo files to other vendors: %s"
        % (_yes(priv.get("web") and priv.get("vendors")), _yes(priv.get("code"))),
        "- python: %s" % state.get("python", "python"),
        "- detected tools: %s" % detected,
        "- strategy -> family map: %s" % strategy_map_line(state),
        "- human saw S1 ranking: %s" % saw,
        "- session plan: one session is fine (all state is in files; any agent can resume)",
    ]
    if single_family(state):
        lines.append("- PROVISIONAL: only one model family is available; every other seat is %s-alt"
                     % host.get("family", "host"))
    if state.get("legacy_v1"):
        lines.append("- migrated from a v1 run (legacy_v1)")
    lines.append("- stage log:")
    lines += stage_log_lines(state)
    return "\n".join(lines).rstrip() + "\n"


def single_family(state):
    fams = state.get("families") or {}
    ok = [f for f in FAMILY_ORDER if (fams.get(f) or {}).get("status") == "ok" and family_allowed(state, f)]
    return len(ok) <= 1


# ---------------------------------------------------------------- step and gate bookkeeping

def step_state(state, sid):
    return ((state.get("steps") or {}).get(sid) or {}).get("state", "pending")


def set_step(state, sid, st, note=None, **extra):
    steps = state.setdefault("steps", {})
    cur = steps.setdefault(sid, {"state": "pending", "at": None, "jobs": [], "note": ""})
    cur["state"] = st
    cur["at"] = textio.now_iso()
    if note is not None:
        cur["note"] = note
    if st == "pending":
        for k in ("originals", "fallback_of", "exhausted"):
            cur.pop(k, None)
    cur.update(extra)
    return cur


def gate_state(state, gid):
    return ((state.get("gates") or {}).get(gid) or {}).get("state", "pending")


def record_gate(state, gid, st, by, answer):
    state.setdefault("gates", {})[gid] = {"state": st, "by": by, "at": textio.now_iso(), "answer": answer}


def add_note(state, text):
    notes = state.setdefault("notes", [])
    if text and text not in notes:
        notes.append(text)
    del notes[:-30]


def add_provisional(state, stage, seat, actual, reason):
    entry = {"stage": str(stage), "seat": seat, "actual": actual, "reason": reason or ""}
    prov = state.setdefault("provisional", [])
    if entry not in prov:
        prov.append(entry)


# ---------------------------------------------------------------- events, last card

def append_event(run_dir, kind, **data):
    rec = {"ts": textio.now_iso(), "event": kind}
    rec.update(data)
    try:
        textio.append_line(os.path.join(run_dir, ".ub", "events.jsonl"), json.dumps(rec, ensure_ascii=True))
    except OSError:
        pass


def write_last_card(run_dir, card):
    try:
        textio.write_json_atomic(os.path.join(run_dir, ".ub", "last_card.json"), card)
    except OSError:
        pass


# ---------------------------------------------------------------- driver lock (6.3)

def _pid_alive(pid):
    try:
        from .. import proc
        return proc.pid_alive(int(pid))
    except Exception:
        return False


def _int(v, default=-1):
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


class Lock(object):
    """The driver lock .ub/lock.json {pid, host, heartbeat_at}; stale after 120 s or when the pid is dead."""

    def __init__(self, run_dir, host="other", stale_s=LOCK_STALE_S):
        self.path = os.path.join(run_dir, ".ub", "lock.json")
        self.host = host
        self.stale_s = stale_s
        self.held = False

    def _read(self):
        try:
            data = textio.read_json(self.path)
            return data if isinstance(data, dict) else None
        except (OSError, ValueError):
            return None

    def holder(self):
        """The live foreign holder's record, or None."""
        data = self._read()
        if not data:
            return None
        if _int(data.get("pid")) == os.getpid():
            return None
        try:
            age = time.time() - float(data.get("heartbeat_ts", 0) or 0)
        except (TypeError, ValueError):
            age = self.stale_s + 1
        if age > self.stale_s or not _pid_alive(data.get("pid", -1)):
            return None
        return data

    def _record(self):
        return {"pid": os.getpid(), "host": self.host, "heartbeat_at": textio.now_iso(), "heartbeat_ts": time.time()}

    def acquire(self):
        """Take the lock with an atomic create (O_EXCL), so two drivers can never both hold it. A stale lock (dead
        pid or old heartbeat) is moved aside and the create is retried once."""
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        for _attempt in range(2):
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_BINARY", 0), 0o644)
            except FileExistsError:
                data = self._read()
                if data is not None and _int(data.get("pid")) == os.getpid():
                    self.held = True  # re-entrant: this process already holds it
                    self.beat()
                    return True
                if data is None:
                    try:  # another driver may be writing its record right now
                        if time.time() - os.path.getmtime(self.path) < 5:
                            return False
                    except OSError:
                        continue
                elif self.holder() is not None:
                    return False
                if not self._move_stale(data):
                    return False
                continue
            except OSError:
                return False
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(json.dumps(self._record(), ensure_ascii=True) + "\n")
            self.held = True
            return True
        return False

    def _move_stale(self, seen):
        """Move the stale lock file aside; if what was moved is not the record judged stale (another driver replaced
        it meanwhile), put it back. True when the path is free for a new O_EXCL create."""
        aside = "%s.stale-%s" % (self.path, os.urandom(4).hex())
        try:
            os.replace(self.path, aside)
        except OSError:
            return os.path.exists(self.path) is False
        moved = None
        try:
            moved = textio.read_json(aside)
        except (OSError, ValueError):
            moved = None
        same = (seen is None and moved is None) or (isinstance(moved, dict) and isinstance(seen, dict) and
                                                    moved.get("pid") == seen.get("pid") and
                                                    moved.get("heartbeat_ts") == seen.get("heartbeat_ts"))
        if not same:
            try:
                os.link(aside, self.path)  # fails when a new lock already exists: then that one wins
            except OSError:
                pass
            try:
                os.remove(aside)
            except OSError:
                pass
            return False
        try:
            os.remove(aside)
        except OSError:
            pass
        return True

    def still_ours(self):
        """False when this process held the lock but the file now names another pid (another driver took over)."""
        if not self.held:
            return True
        data = self._read()
        return data is None or _int(data.get("pid")) == os.getpid()

    def beat(self):
        """Refresh the heartbeat. Only while the lock file still names this process; returns False (and drops
        `held`) when another driver has taken the lock."""
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        if self.held and not self.still_ours():
            self.held = False
            return False
        textio.write_json_atomic(self.path, self._record())
        return True

    def release(self):
        if not self.held:
            return
        data = self._read()
        if data and _int(data.get("pid")) == os.getpid():
            try:
                os.remove(self.path)
            except OSError:
                pass
        self.held = False


# ---------------------------------------------------------------- run discovery (6.10)

def is_finished(run_dir):
    if os.path.exists(os.path.join(run_dir, "12_HANDOFF.md")):
        return True
    try:
        st = textio.read_json(run_json_path(run_dir))
    except (OSError, ValueError):
        return False
    if st.get("status") in ("done", "stopped"):
        return True
    g13 = (st.get("gates") or {}).get("G13") or {}
    return g13.get("state") == "answered" and (g13.get("answer") or {}).get("action") == "approve" and \
        step_state(st, "14.4") == "done"


def list_runs(root):
    """Run folders under a run root (newest first by folder mtime, then name)."""
    if not os.path.isdir(root):
        return []
    out = []
    for d in glob.glob(os.path.join(root, "*")):
        if os.path.isdir(d) and (os.path.exists(os.path.join(d, RUN_FILE)) or
                                 os.path.exists(os.path.join(d, RUN_MD))):
            out.append(os.path.abspath(d))
    out.sort(key=lambda d: (_mtime(d), os.path.basename(d)), reverse=True)
    return out


def _mtime(d):
    best = 0.0
    for name in (RUN_FILE, RUN_MD, "PROGRESS.md"):
        p = os.path.join(d, name)
        if os.path.exists(p):
            best = max(best, os.path.getmtime(p))
    return best


def runs_index_path():
    return os.path.join(ub_home(), "runs.json")


def register_run(run_dir, topic=""):
    path = runs_index_path()
    try:
        data = textio.read_json(path) if os.path.exists(path) else {}
    except (OSError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    runs = data.setdefault("runs", [])
    posix = textio.to_posix(run_dir)
    runs = [r for r in runs if r.get("path") != posix]
    runs.append({"path": posix, "topic": topic, "created_at": textio.now_iso()})
    data["runs"] = runs[-200:]
    try:
        textio.write_json_atomic(path, data)
    except OSError:
        pass


def indexed_runs():
    path = runs_index_path()
    try:
        data = textio.read_json(path)
    except (OSError, ValueError):
        return []
    out = []
    for r in reversed((data or {}).get("runs", [])):
        p = r.get("path")
        if p and os.path.isdir(p):
            out.append(os.path.abspath(p))
    return out


def newest_unfinished(root=None):
    """(run_dir, how) for `continue`: newest unfinished run under the run root, else UB_HOME/runs.json."""
    rroot, _ = run_root(root)
    for d in list_runs(rroot):
        if not is_finished(d):
            return d, "newest unfinished run under %s" % textio.to_posix(rroot)
    for d in indexed_runs():
        if not is_finished(d):
            return d, "newest unfinished run in %s" % textio.to_posix(runs_index_path())
    return None, None


# ---------------------------------------------------------------- supersede (6.10)

def iso_stamp():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def supersede_paths(run_dir, relpaths, stamp=None):
    """Move run-relative files (or folders) to _superseded/<ISO>/ keeping their relative paths. Never deletes.
    Returns the list of moved relpaths."""
    stamp = stamp or iso_stamp()
    dest_root = os.path.join(run_dir, "_superseded", stamp)
    moved = []
    for rel in relpaths:
        rel = rel.replace("\\", "/").strip("/")
        if not rel or rel.startswith("_superseded") or rel in (RUN_FILE, RUN_MD):
            continue
        src = os.path.join(run_dir, *rel.split("/"))
        if not os.path.exists(src):
            continue
        dst = os.path.join(dest_root, *rel.split("/"))
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        if os.path.exists(dst):
            continue
        shutil.move(src, dst)
        moved.append(rel)
    return moved


def expand_globs(run_dir, patterns):
    out = []
    for pat in patterns:
        for p in glob.glob(os.path.join(run_dir, *pat.split("/"))):
            rel = os.path.relpath(p, run_dir).replace("\\", "/")
            if rel not in out:
                out.append(rel)
    return out


# ---------------------------------------------------------------- the per-call context

class Ctx(object):
    """Everything a predicate, fanout, placeholder or script needs: the run folder, its state and the deps.

    `sim` is a dict of facts used instead of reading files when the pipeline is simulated (`ub plan`, tests).
    """

    def __init__(self, run_dir, state, deps=None, sim=None):
        self.run_dir = os.path.abspath(run_dir) if run_dir else None
        self.state = state
        self.deps = deps
        self.sim = sim
        self.cache = {}

    # paths
    def path(self, *rel):
        parts = []
        for r in rel:
            parts.extend(str(r).replace("\\", "/").split("/"))
        return os.path.join(self.run_dir, *parts)

    def exists(self, rel):
        return bool(self.run_dir) and os.path.exists(self.path(rel))

    def read(self, rel, default=""):
        if not self.run_dir:
            return default
        p = self.path(rel)
        if not os.path.exists(p):
            return default
        try:
            return textio.read_text(p)
        except OSError:
            return default

    def read_json(self, rel, default=None):
        if not self.run_dir:
            return default
        p = self.path(rel)
        if not os.path.exists(p):
            return default
        try:
            return textio.read_json(p)
        except (OSError, ValueError):
            return default

    def write(self, rel, text):
        p = self.path(rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        textio.write_text_atomic(p, text)
        return p

    def write_json(self, rel, obj):
        p = self.path(rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        textio.write_json_atomic(p, obj)
        return p

    # state shortcuts
    @property
    def mode(self):
        return self.state.get("mode", "standard")

    @property
    def variant(self):
        return self.state.get("variant", "general")

    @property
    def autopilot(self):
        return self.state.get("autopilot", "guided")

    @property
    def host_family(self):
        return (self.state.get("host") or {}).get("family") or "claude"

    @property
    def host_agent(self):
        return (self.state.get("host") or {}).get("agent") or "other"

    @property
    def seats(self):
        return self.state.setdefault("seats", {})

    def fact(self, name, default=None):
        if self.sim is not None:
            return self.sim.get(name, default)
        return None

    def family_backend(self, label):
        info = (self.state.get("families") or {}).get(base_family(label)) or {}
        return info.get("backend")

    def is_host_chain(self, label):
        return self.family_backend(label) == "host"

    def family_web(self, label):
        if not (self.state.get("privacy") or {}).get("web", True):
            return False
        info = (self.state.get("families") or {}).get(base_family(label)) or {}
        return bool(info.get("web"))

    def date(self):
        created = self.state.get("created_at") or textio.now_iso()
        return created[:10]


def vendors_for(families):
    return sorted({VENDORS.get(f, f) for f in families})
