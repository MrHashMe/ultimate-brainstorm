"""Run state: run.json (4.2) load/save, 00_RUN.md (4.3), the driver lock, events, run discovery, supersede (6.10).

Only the process that holds the run's driver lock (DriverLock) writes run.json, and every save is a compare-and-swap
on the integer `rev`: a run.json that changed since it was loaded raises Stale and is never overwritten. A save whose
state did not change writes nothing; otherwise it writes run.json atomically and re-renders 00_RUN.md, whose
v1-compatible lines `bs.py` parses.
"""

import datetime
import hashlib
import json
import os
import re
import threading
import time

from .. import textio
from . import BUDGET_CAPS, ENGINE_VERSION, EngineError, FAMILY_ORDER, HOST_WAIT_S, base_family

RUN_FILE = "run.json"
RUN_MD = "00_RUN.md"
RUN_MD_V1 = "00_RUN.v1.md"  # the untouched v1 00_RUN.md, kept by the migration
DRIVER_LOCK = "_driver"     # C1: .ub/jobs/_driver.lock, the kernel byte lock of batch.JobLock ("_" ids are reserved)
LEGACY_STALE_S = 120        # proc.LEGACY_DRIVER_STALE_S: a live 2.0.x driver with an older beat waits at a gate
LEGACY_BEAT_S = 30          # this kit's holder record: its 2.0.3 heartbeat is refreshed this often (#79)
CLAIM_WAIT_S = 2.5          # a claim retries a lock.json record it cannot move aside (held open) for this long
ABSENT_RECHECK_S = 0.05     # a record of this process found missing is looked for once more after this long: a 2.0.3
                            # driver that only checked it (its _move_stale) moves it aside and puts it back at once
STOP_FILE = "STOP"          # C3: <run>/.ub/STOP, written by `ub stop`
MOVE_ATTEMPTS = 8           # a move that meets a sharing violation is retried for about 2.5 s
# Windows without long paths (#98): a file path may have 259 characters, a folder 247. Past the run folder, a run
# writes at most RUN_REL_MAX characters (the longest is an ADR: 10_ARCHITECTURE/adr/NNNN-<40-character slug>.md, 68;
# temp names are 30), and a redo moves it under _superseded/<stamp>[-N]/ (SUPERSEDED_PREFIX more).
WIN_FILE_MAX = 259
WIN_DIR_MAX = 247
RUN_REL_MAX = 70
SUPERSEDED_PREFIX = 32
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


def path_limit():
    """WIN_FILE_MAX on Windows without long-path support, else None (no limit to budget for). Long paths count as on
    when HKLM\\SYSTEM\\CurrentControlSet\\Control\\FileSystem LongPathsEnabled is 1: the python.org interpreter is
    long-path aware, so it then opens longer paths.  # [U-75]"""
    return WIN_FILE_MAX if os.name == "nt" and not long_paths_enabled() else None


def long_paths_enabled():
    """True / False from the Windows registry (LongPathsEnabled); None when it cannot be read; True off Windows. The one
    reading is textio's (cached), which the worker side uses too."""
    return textio.long_paths_enabled()


def new_run_dir(root, topic, date=None):
    """<root>/<YYYY-MM-DD>-<slug>, with -2, -3 ... on collision. The folder is created here (an atomic mkdir), so two
    `ub init` calls with the same topic never share one run folder. On Windows without long paths (#98) the slug loses
    words from the end until every file a run writes, also moved under _superseded/, fits in 259 characters; when even
    one word does not fit, EngineError names --root."""
    slug = slugify(topic)
    limit = path_limit()
    stem = os.path.join(os.path.abspath(root), "%s-" % (date or today_utc()))
    if limit:
        room = limit - SUPERSEDED_PREFIX - RUN_REL_MAX - 4  # 4: "-NN" on a collision and the separator
        while len(stem) + len(slug) > room and "-" in slug:
            slug = slug.rsplit("-", 1)[0]
        if len(stem) + len(slug) > room:
            below = len(stem) + len(slug) + (limit - room) - len(os.path.abspath(root))
            raise EngineError("the run folder would be too deep for Windows paths: %s is %d characters, and a run "
                              "needs about %d more below it (Windows allows %d without long-path support)"
                              % (textio.to_posix(root), len(os.path.abspath(root)), below, limit),
                              fix=["start the run in a shorter folder: ub init --root <short path> ...",
                                   "or enable Windows long paths (LongPathsEnabled; see docs/TROUBLESHOOTING.md)"])
    base = "%s-%s" % (date or today_utc(), slug)
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
        "rev": 0,
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
        "budget": {"max_calls": budget_cap(mode)},  # backend requests (C6); `ub budget` changes it
        "exec": {"wait_s": HOST_WAIT_S.get(host_agent, 50)},
        "legacy_v1": False,
        # Engine extras (not read by other builders).
        "project_dir": textio.to_posix(project_dir or os.getcwd()),
        "options": {"with_ce_ideate": False, "explicit_privacy": False, "private": False},
        "counters": {"launched": 0, "gap_rounds": 0, "g13_loops": 0, "g10_loops": 0},
        "interrupt": None,
        "status": "active",
        "notes": [],
        "idea_text": "",
    }


def budget_cap(mode):
    """budget.max_calls (backend requests) of a new run in a mode: `ub config set budget.<mode> N`
    (UB_HOME/config.json), else the 6.1 default. A running run's cap changes only with `ub budget RUN --max-calls N`."""
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


class Stale(EngineError):
    """run.json changed since this process loaded it (C2): the save is refused, nothing is overwritten."""


# The rev and state digest this process last read or wrote, per run folder: a save of an unchanged state writes nothing.
_SAVED = {}


def _key(run_dir):
    return os.path.normcase(os.path.abspath(run_dir))


def _digest(state):
    body = dict((k, v) for k, v in state.items() if k != "rev")
    return hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=True, default=str).encode("utf-8")).hexdigest()


def _rev(state):
    return _int((state or {}).get("rev"), 0)


def load(run_dir, persist=True):
    """Load run.json. A v1 folder (00_RUN.md, no run.json) is migrated first (6.10). Only a caller that holds the
    driver lock passes persist=True, which writes the migration (after keeping the v1 00_RUN.md as 00_RUN.v1.md);
    read-only commands get the migrated state in memory and write nothing."""
    path = run_json_path(run_dir)
    if not os.path.exists(path):
        if os.path.exists(os.path.join(run_dir, RUN_MD)):
            from . import migrate
            state = _this_runner(migrate.migrate_v1(run_dir))
            state["legacy_v1_source"] = RUN_MD_V1
            if persist:
                _keep_v1_run_md(run_dir)
                # the v1 file asserts the families, it detected nothing: the command that migrated the run detects
                # them under the lock before it drives (ub.with_run, #20)
                state["exec"]["redetect"] = True
                save(run_dir, state)
            return state
        raise EngineError("no run.json in %s" % textio.to_posix(run_dir),
                          fix=["check the run path, or start a new run with: ub init --text-file <file>"])
    # named with its folder: a bare `continue` picks the newest unfinished run, which may be this one
    fix = ["restore or move away %s, or continue another run by its folder (ub list --json)" % textio.to_posix(path)]
    try:
        state = textio.read_json(path)
    except (OSError, ValueError) as e:
        raise EngineError("%s is unreadable: %s" % (textio.to_posix(path), e), fix=fix)
    if not _shape_ok(state) or state.get("schema") != 2:
        raise EngineError("%s has an unknown schema (expected 2)" % textio.to_posix(path), fix=fix)
    _this_runner(state)  # before the digest: a new runner alone is no change to save
    _SAVED[_key(run_dir)] = (_rev(state), _digest(state))
    _fill_defaults(state, run_dir)
    return state


def _this_runner(state):
    """Card commands start with the engine that prints them (4.12): the stored `runner` is replaced with this kit's
    (cards.default_runner(), what init stores). A runner of the kit that started the run points at an older or removed
    kit folder after an update, and one a copied run.json names could run anything, so neither is ever printed."""
    from . import cards  # lazy: cards imports this module
    state["runner"] = cards.default_runner()
    return state


def _keep_v1_run_md(run_dir):
    """Copy the v1 00_RUN.md (its dated stage log, tools and notes) to 00_RUN.v1.md before the first save replaces it.
    Write-if-absent, so a repeated migration never overwrites the original."""
    try:
        data = textio.read_bytes(os.path.join(run_dir, RUN_MD))
        fd = os.open(os.path.join(run_dir, RUN_MD_V1), os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_BINARY", 0),
                     0o644)
    except FileExistsError:
        return
    with os.fdopen(fd, "wb") as f:
        f.write(data)


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
    from . import migrate  # lazy: migrate imports this module
    migrate.upgrade_decisions(state, run_dir)


def save(run_dir, state):
    """Compare-and-swap save (C2): writes run.json with rev+1 and re-renders 00_RUN.md, only when the state changed
    since it was loaded or last saved (a no-op poll writes nothing). Raises Stale, and writes nothing, when the rev on
    disk is not the rev this state was loaded with. Returns True when it wrote."""
    key = _key(run_dir)
    rev = _rev(state)
    digest = _digest(state)
    path = run_json_path(run_dir)
    if _SAVED.get(key) == (rev, digest) and os.path.exists(path):
        return False
    try:
        disk = textio.read_json(path) if os.path.exists(path) else None
    except (OSError, ValueError):
        disk = None  # an unreadable run.json is replaced
    if isinstance(disk, dict) and _rev(disk) != rev:
        raise Stale("run.json is at rev %d, this session loaded rev %d" % (_rev(disk), rev),
                    say="This run changed in another session; nothing was overwritten.")
    state["rev"] = rev + 1
    textio.write_json_atomic(path, state)
    textio.write_text_atomic(os.path.join(run_dir, RUN_MD), render_run_md(state))
    _SAVED[key] = (rev + 1, digest)
    return True


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
    from . import privacy  # the one allowed-vendors rule (engine and worker); privacy imports nothing from here
    return privacy.vendor_allowed(state, fam)


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
        if st.get("at") and st.get("state") in ("done", "skipped", "blocked"):
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
        for k in ("originals", "fallback_of", "exhausted", "lease", "host_fp", "relaunch_base", "accepted"):
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


# ---------------------------------------------------------------- driver lock (6.3, C1)

def _int(v, default=-1):
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _put_back(aside, path):
    """Put a record moved aside back at path, never over a record created meanwhile (that one stands): a link, or a
    rename on Windows (which never replaces), fails when path exists. Where the file system has no hard links (exFAT,
    FAT32, some network shares) the bytes are copied back with an exclusive create instead, so the record is never
    lost."""
    try:
        (os.rename if os.name == "nt" else os.link)(aside, path)
        return
    except FileExistsError:
        return
    except OSError:
        pass
    try:
        data = textio.read_bytes(aside)
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_BINARY", 0), 0o644)
    except OSError:
        return
    with os.fdopen(fd, "wb") as f:
        f.write(data)


class DriverLock(object):
    """The run's driver lock (C1): the kernel byte lock batch.JobLock(run_dir, "_driver") on .ub/jobs/_driver.lock,
    the primitive the workers use. The OS drops it when its process ends, even on a hard kill, so it never goes stale
    while its holder lives and never outlives it: no heartbeat, no staleness guess. Every command that changes the run
    takes it BEFORE it reads run.json and keeps it until it has saved. .ub/lock.json records {pid, host, since} of the
    holder for the 'another session is driving' card. It is also all a kit 2.0.x driver on the same run (an upgrade
    window) knows (#79): this kit claims it the 2.0.3 way (claim: an exclusive create, before run.json is read) and
    keeps its 2.0.3 heartbeat fresh while it holds the lock, so a 2.0.3 driver respects a live holder and takes over the
    record of a killed one after 120 s, as among 2.0.3 drivers; this kit respects a live 2.0.x driver
    (legacy_holder: the installer's rule), and stops without saving once a 2.0.3 driver took its record over
    (still_ours). A record of this kit always has `since`; a 2.0.x record never has."""

    def __init__(self, run_dir, host="other"):
        from .. import batch  # B2 runtime module, imported lazily like everywhere in the engine
        self.run_dir = run_dir
        self.info_path = os.path.join(run_dir, ".ub", "lock.json")
        self.host = host
        self._lock = batch.JobLock(run_dir, DRIVER_LOCK)
        self._since = None
        self._beat = None  # (thread, stop event) of the heartbeat while this process drives
        self._writing = threading.Lock()
        self._owned = False  # lock.json held this process's record since the kernel lock was taken
        self.lost = False  # ... and then named another driver, or went away (still_ours)

    @property
    def held(self):
        return self._lock.held

    def acquire(self, timeout_s=0.0):
        """True when this process now drives the run; False while another process holds it. After a hard kill the OS
        frees the lock of the dead driver, so the next acquire succeeds (Windows documents that this release can lag
        behind the process exit; a refused acquire only shows the 'another session' card and is retried).  # [U-70]"""
        return self._lock.acquire(timeout_s)

    def claim(self, host=None):
        """Record this process as the driver, right after acquire() and before run.json is read: lock.json is created
        exclusively (O_EXCL), as a 2.0.3 driver creates it, so no 2.0.3 driver can take the run between this check and
        this record (#79). A record whose holder is gone (this kit's after a hard kill, a stale 2.0.x one) is moved
        aside first. Returns None once lock.json names this process; otherwise who holds the run, and the caller changes
        nothing: a live 2.0.x driver (legacy_holder), or a gone holder's record that another program holds open,
        so that for CLAIM_WAIT_S it can be neither moved aside nor replaced (a 2.0.3 driver would take it over too)."""
        self.host = host or self.host
        os.makedirs(os.path.dirname(self.info_path), exist_ok=True)
        seen, delay, deadline = {}, 0.02, time.monotonic() + CLAIM_WAIT_S
        while True:
            moved = False
            try:
                fd = os.open(self.info_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_BINARY", 0), 0o644)
            except FileExistsError:
                raw = textio.read_json_or(self.info_path)
                if not isinstance(raw, dict) and self._young():
                    return {"pid": None, "host": "a kit 2.0.3 session"}  # it is writing its record right now
                seen = raw if isinstance(raw, dict) else {}
                if self.legacy_holder(seen):
                    return seen
                moved = self._move_aside(raw)
            except OSError:
                pass  # tried again below (Windows: a name that is still being deleted cannot be created yet)
            else:
                self._since = textio.now_iso()
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    f.write(json.dumps(self._record(), ensure_ascii=True) + "\n")
                self._owned = True
                break
            if time.monotonic() >= deadline:
                # replace the record in place, and drive only when lock.json then names this process
                self._since = self._since or textio.now_iso()
                try:
                    textio.write_json_atomic(self.info_path, self._record())
                except OSError:
                    pass
                if _int(self.holder().get("pid")) != os.getpid():
                    return {"pid": seen.get("pid"), "host": "%s; another program holds .ub/lock.json open"
                            % seen.get("host", "?"), "held_open": True}
                self._owned = True
                break
            if not moved:
                time.sleep(delay)
                delay = min(delay * 2, 0.5)
        self.lost = False
        self._start_beat()
        return None

    def announce(self, host=None):
        """(Re)write this holder's record: with_run names the run's host agent once it has read run.json."""
        self.host = host or self.host
        self._since = self._since or textio.now_iso()
        self._write()
        self._start_beat()

    def _record(self):
        # heartbeat_at / heartbeat_ts in the 2.0.3 format, for 2.0.3 drivers only; `since` marks a record of this kit
        return {"pid": os.getpid(), "host": self.host, "since": self._since, "heartbeat_at": textio.now_iso(),
                "heartbeat_ts": time.time()}

    def _write(self):
        """Rewrite this process's record (announce, the beat); True when lock.json now holds it. Never over another
        driver's record: a kit 2.0.3 driver knows nothing of this process's locks, so a record it wrote between a check
        here and a replace would be replaced unseen. The record is moved aside instead, and the new one is created
        exclusively (O_EXCL, as claim and a 2.0.3 driver create theirs) only when the record moved was this process's.
        Any other record (a 2.0.3 takeover, or one still being written) is put back, and a record of this process that
        went away (a 2.0.3 driver moved it aside to take it over) is not recreated: the lock is then lost (still_ours).
        A 2.0.3 driver that arrives in the moment lock.json is moved aside takes the run, and this driver stops."""
        with self._writing:
            if self.lost:
                return False
            aside = "%s.beat-%s" % (self.info_path, os.urandom(4).hex())
            try:
                try:
                    textio._replace_with_retry(self.info_path, aside)
                except FileNotFoundError:
                    if not self._owned:
                        raise
                    time.sleep(ABSENT_RECHECK_S)  # a 2.0.3 driver that only checked it puts it back at once
                    textio._replace_with_retry(self.info_path, aside)
            except FileNotFoundError:
                aside = None  # no record yet (announce before a claim), or this process's went away
            except OSError:
                return False  # a reader holds the file: the next beat writes it
            fd = None
            try:
                if aside is None:
                    ours = not self._owned
                else:
                    prev = textio.read_json_or(aside)
                    ours = isinstance(prev, dict) and _int(prev.get("pid")) == os.getpid()
                if not ours:
                    self.lost = True
                    return False
                fd = os.open(self.info_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_BINARY", 0), 0o644)
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    f.write(json.dumps(self._record(), ensure_ascii=True) + "\n")
                self._owned = True
                return True
            except FileExistsError:
                self.lost = True  # another driver created its record meanwhile: it stands
                return False
            except OSError:
                return False  # the next beat writes it
            finally:
                if aside is not None:
                    if fd is None:
                        _put_back(aside, self.info_path)
                    try:
                        os.remove(aside)
                    except OSError:
                        pass

    def _start_beat(self):
        if self._beat is None:
            stop = threading.Event()
            thread = threading.Thread(target=self._beat_loop, args=(stop,), name="ub-driver-beat", daemon=True)
            thread.start()
            self._beat = (thread, stop)

    def _beat_loop(self, stop):
        # stops once a 2.0.3 driver took over the record this process let go stale (it stalled): _write never
        # replaces that record, and marks the lock lost
        while not self.lost and not stop.wait(LEGACY_BEAT_S):
            self._write()

    def still_ours(self):
        """False once lock.json, while this process holds the lock, names another driver, or lost the record this
        process wrote: a kit 2.0.3 driver took over the record it let go stale (it was suspended or stalled for more
        than 120 s; that driver may be done again, with its record). The driver then stops without saving, so the
        other driver's run.json writes stand (as among 2.0.3 drivers), and the beat stops. It stays False until the
        lock is released."""
        if self.held and not self.lost:
            with self._writing:  # never while this process's own beat replaces the record
                data = self.holder()
                if not data and self._owned:
                    time.sleep(ABSENT_RECHECK_S)  # a 2.0.3 driver that only checked it puts it back at once
                    data = self.holder()
            self.lost = _int(data.get("pid")) != os.getpid() and bool(data or self._owned)
        return not (self.held and self.lost)

    def _young(self):
        try:
            return time.time() - os.path.getmtime(self.info_path) < 5
        except OSError:
            return False

    def _move_aside(self, seen):
        """Move the record judged stale aside (False when it cannot be moved); when what was moved is not that record
        (a 2.0.3 driver replaced it meanwhile), put it back (_put_back: never over a new record, which then stands)."""
        aside = "%s.stale-%s" % (self.info_path, os.urandom(4).hex())
        try:
            os.replace(self.info_path, aside)
        except OSError:
            return False
        if textio.read_json_or(aside) != seen:
            _put_back(aside, self.info_path)
        try:
            os.remove(aside)
        except OSError:
            pass
        return True

    def legacy_holder(self, data=None):
        """The record of a live kit 2.0.x driver, which holds the run through lock.json alone (no kernel lock), or
        None: proc.legacy_driver_live, the one rule the installer applies too (6.3, 10.4 item 8), on this module's clock
        and never this process (a 2.0.x `ub run` waiting at a gate keeps the run while it runs)."""
        from .. import proc
        data = self.holder() if data is None else data
        live = proc.legacy_driver_live(data, self.run_dir, now=time.time(), exclude_pid=os.getpid())
        return data if live else None

    def holder(self):
        """{pid, host, since} of the session that announced itself as the driver, or {} (display only)."""
        data = textio.read_json_or(self.info_path)
        return data if isinstance(data, dict) else {}

    def release(self):
        if not self.held:
            return
        if self._beat is not None:
            thread, stop = self._beat
            stop.set()
            thread.join(10)  # no beat rewrites the record once it is removed
            self._beat = None
        if _int(self.holder().get("pid")) == os.getpid():
            try:
                os.remove(self.info_path)  # before the kernel lock goes, so the next holder's record is never removed
            except OSError:
                pass
        self._since, self._owned, self.lost = None, False, False
        self._lock.release()


# ---------------------------------------------------------------- stop (C3)

def stop_path(run_dir):
    return os.path.join(run_dir, ".ub", STOP_FILE)


def stop_requested(run_dir):
    """True while `ub stop` asked the run to stop: no driver launches a job and no worker starts a call."""
    return bool(run_dir) and os.path.exists(stop_path(run_dir))


def request_stop(run_dir):
    os.makedirs(os.path.dirname(stop_path(run_dir)), exist_ok=True)
    with open(stop_path(run_dir), "ab"):
        pass


def clear_stop(run_dir):
    try:
        os.remove(stop_path(run_dir))
    except OSError:
        pass


# ---------------------------------------------------------------- run discovery (6.10)

def read_run_json(run_dir):
    """run.json as an object, or None when it is missing, unreadable or not a run.json object (_shape_ok): run
    discovery (list, a bare continue) never fails on one odd run folder, and `continue` of that folder is BLOCKED
    with its path (load)."""
    try:
        data = textio.read_json(run_json_path(run_dir))
    except (OSError, ValueError):
        return None
    return data if _shape_ok(data) else None


# run.json keys (and keys of its objects) the engine and run discovery read without a type check, with the types
# new_state(), seats.assign() and a reseat write; null only where they write it
_NONE = type(None)
_SEAT_LISTS = ("families", "others", "web_families", "researcher", "checker_pool", "screen_judges", "tournament_judges",
               "redteam_rotation", "arch_authors", "arch_judges")
_SHAPES = dict([(k, dict) for k in ("host", "privacy", "families", "components", "seats", "gates", "steps", "choice",
                                     "budget", "exec", "options", "counters")] +
               [("provisional", list), ("notes", list), ("interrupt", (dict, _NONE)), ("supersede", (list, _NONE)),
                ("host.agent", (str, _NONE)), ("host.family", (str, _NONE)), ("exec.wait_s", int),
                ("seats.rotation", int), ("seats.rr_next", int), ("seats.host", str), ("seats.s1_engine", str),
                ("seats.arch_writer", (str, _NONE)), ("seats.single_family", bool), ("seats.arch_same_family", bool)] +
               [("seats." + k, dict) for k in ("generators", "proposal", "arch_archetypes")] +
               [("seats." + k, list) for k in _SEAT_LISTS])


def _shape_ok(data):
    """Whether run.json data is an object whose keys above (when present) have their type, whose steps, gates,
    families and supersede batches each hold an object, whose seat lists hold family labels (strings), and whose gate
    answers are objects (or null). A hand-edited or corrupted value is refused whole, never half read."""
    if not isinstance(data, dict):
        return False
    for path, t in _SHAPES.items():  # an object before its own keys
        obj, _, key = path.rpartition(".")
        where = (data.get(obj) or {}) if obj else data
        if key in where and not isinstance(where[key], t):
            return False
    seats = data.get("seats", {})
    records = list(data.get("steps", {}).values()) + list(data.get("gates", {}).values()) + \
        list(data.get("families", {}).values()) + (data.get("supersede") or [])
    return all(isinstance(r, dict) for r in records) and \
        all(isinstance(f, str) for k in _SEAT_LISTS for f in seats.get(k) or []) and \
        all(isinstance(g.get("answer") or {}, dict) for g in data.get("gates", {}).values())


def is_finished(run_dir):
    if os.path.exists(os.path.join(run_dir, "12_HANDOFF.md")):
        return True
    st = read_run_json(run_dir)
    if st is None:
        return False
    reason = str(st.get("stopped_reason") or "")
    if st.get("status") == "done" or (st.get("status") == "stopped" and reason != "user" and "budget" not in reason):
        return True  # a `ub stop` is a pause and a budget stop waits for `ub budget`: `continue` picks the run up
    from . import pipeline  # lazy: pipeline imports this module
    g13 = (st.get("gates") or {}).get("G13") or {}
    return g13.get("state") == "answered" and (g13.get("answer") or {}).get("action") == "approve" and \
        step_state(st, pipeline.step_ref("finished")) == "done"


def list_runs(root):
    """Run folders under a run root (newest first by folder mtime, then name)."""
    if not os.path.isdir(root):
        return []
    out = []
    for d in textio.glob_in(root, "*"):
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
    posix = textio.to_posix(run_dir)
    runs = [r for r in _indexed(data) if r["path"] != posix]
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
    return [os.path.abspath(r["path"]) for r in reversed(_indexed(data)) if r["path"] and os.path.isdir(r["path"])]


def _indexed(data):
    """The entries of runs.json that name a folder; anything else in the file (a hand edit, a sync tool) is skipped."""
    runs = data.get("runs") if isinstance(data, dict) else None
    return [r for r in runs if isinstance(r, dict) and isinstance(r.get("path"), str)] if isinstance(runs, list) else []


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


def _clean_rels(relpaths):
    out = []
    for rel in relpaths or []:
        rel = str(rel).replace("\\", "/").strip("/")
        if rel and not rel.startswith("_superseded") and rel not in (RUN_FILE, RUN_MD) and rel not in out:
            out.append(rel)
    return out


def _move_aside(run_dir, rel, stamp):
    """Move one run-relative file or folder to _superseded/<stamp>/<rel> with os.replace: the same volume, so never a
    copy that could leave a file in two places. An existing target gets a .2, .3 ... suffix, so nothing is
    overwritten and the source never stays in place. A sharing violation (a scanner, an indexer, a reader without
    share-delete) is retried with backoff; OSError when it persists. False when the source is already gone."""
    src = os.path.join(run_dir, *rel.split("/"))
    if not os.path.lexists(src):
        return False
    base = dst = os.path.join(run_dir, "_superseded", stamp, *rel.split("/"))
    n = 2
    while os.path.lexists(dst):
        dst = "%s.%d" % (base, n)
        n += 1
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    delay = 0.02
    for attempt in range(MOVE_ATTEMPTS):
        try:
            os.replace(src, dst)
            return True
        except PermissionError:
            if attempt == MOVE_ATTEMPTS - 1:
                raise
            time.sleep(delay)
            delay = min(delay * 2, 0.5)
    return False


def check_supersede_paths(run_dir, relpaths, stamp=None):
    """#98: EngineError before anything moves when a destination under _superseded/<stamp>/ would be longer than
    Windows allows without long paths (files 259, folders 247 characters), so a redo never stops half way."""
    limit = path_limit()
    if not limit:
        return
    root = os.path.join(os.path.abspath(run_dir), "_superseded", stamp or iso_stamp() + "-NN")
    for rel in _clean_rels(relpaths):
        src = os.path.join(run_dir, *rel.split("/"))
        deepest = [rel]
        if os.path.isdir(src):
            for dirpath, _dirs, files in os.walk(src):
                deepest += [os.path.relpath(os.path.join(dirpath, f), run_dir).replace("\\", "/") for f in files]
        for r in deepest:
            dst = os.path.join(root, *r.split("/"))
            if len(dst) > limit or len(os.path.dirname(dst)) > WIN_DIR_MAX:
                raise EngineError("%s cannot be moved to _superseded/: the new path would have %d characters, more "
                                  "than Windows allows without long-path support; nothing was moved"
                                  % (r, len(dst)),
                                  fix=["enable Windows long paths (LongPathsEnabled; see docs/TROUBLESHOOTING.md)",
                                       "or copy the run to a shorter folder and continue it there"])


def supersede_paths(run_dir, relpaths, stamp=None):
    """Move run-relative files (or folders) to _superseded/<ISO>/ keeping their relative paths. Never deletes, never
    overwrites. Returns the list of moved relpaths; OSError when a file stays locked (see supersede() for moves that
    must survive that)."""
    stamp = stamp or iso_stamp()
    check_supersede_paths(run_dir, relpaths, stamp)
    return [rel for rel in _clean_rels(relpaths) if _move_aside(run_dir, rel, stamp)]


def supersede(run_dir, state, relpaths, stamp=None):
    """Journaled supersede (I6). The caller has already reset the steps in `state`; the files to move are added to
    the journal state["supersede"] and committed with that reset in ONE compare-and-swap save, and only then moved. So
    run.json never marks a step done whose outputs are gone, and an interrupted or refused move is rolled forward later
    (finish_supersede). Returns the relpaths moved now."""
    rels = _clean_rels(relpaths)
    check_supersede_paths(run_dir, rels, stamp)
    if rels:
        if not stamp:
            stamp = base = iso_stamp()
            n = 2
            while os.path.exists(os.path.join(run_dir, "_superseded", stamp)):
                stamp = "%s-%d" % (base, n)  # a second supersede in the same second gets its own folder
                n += 1
        state.setdefault("supersede", []).append({"stamp": stamp, "paths": rels})
    save(run_dir, state)
    return finish_supersede(run_dir, state)


def finish_supersede(run_dir, state):
    """Roll the supersede journal forward: move what is still in place (a missing source was moved already, so a
    replay is idempotent), then clear the journal. A file that stays locked ends the pass: its batch keeps the rest and
    names it (`held`), the journal is saved, and the engine runs no step until a later command finishes the moves.
    Returns the relpaths moved in this pass."""
    journal = state.get("supersede")
    if journal is None:
        return []
    moved = []
    while journal:
        batch = journal[0]
        paths = batch.setdefault("paths", [])
        while paths:
            try:
                if _move_aside(run_dir, paths[0], batch.get("stamp") or iso_stamp()):
                    moved.append(paths[0])
            except OSError as e:
                batch["held"] = paths[0]
                batch["error"] = str(e)[:200]
                save(run_dir, state)
                return moved
            paths.pop(0)
        journal.pop(0)
    state.pop("supersede", None)
    save(run_dir, state)
    return moved


def expand_globs(run_dir, patterns):
    """Run-relative paths that match the run-relative glob patterns (the run folder's own path is literal)."""
    out = []
    for pat in patterns:
        for p in textio.glob_in(run_dir, *pat.split("/")):
            rel = os.path.relpath(p, run_dir).replace("\\", "/")
            if rel not in out:
                out.append(rel)
    return out


# ---------------------------------------------------------------- the per-call context

def _sha_or_none(path):
    """SHA-256 of a file's bytes, None when it cannot be read (as HOST steps record `host_fp` and `accepted`)."""
    try:
        return textio.sha256_file(path)
    except OSError:
        return None


class Ctx(object):
    """Everything a predicate, fanout, placeholder or script needs: the run folder, its state and the deps.

    `sim` is a dict of facts used instead of reading files when the pipeline is simulated (`ub plan`, tests).
    `lease` is the HOST / HOST_BATCH lease token this session presented (`--lease`) or was just given; `takeover` is
    set by `ub continue`, which takes a host task over from another session.
    """

    def __init__(self, run_dir, state, deps=None, sim=None):
        self.run_dir = os.path.abspath(run_dir) if run_dir else None
        self.state = state
        self.deps = deps
        self.sim = sim
        self.cache = {}
        self.lease = None
        self.takeover = False

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
        return self._write(rel, textio.write_text_atomic, text)

    def write_json(self, rel, obj):
        return self._write(rel, textio.write_json_atomic, obj)

    def _write(self, rel, write, data):
        """Every write of the engine. A file of an accepted HOST task that the engine rewrites (2.2 normalizes
        criteria.json, a G2c correction appends to 01_FRAME.md) stays accepted: its `accepted` hash follows the
        engine's write, so only a change the engine did not make is named as a late write (#96). A file that had
        changed before (a displaced session's late write) keeps its accepted hash, and stays named."""
        p = self.path(rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        key = str(rel).replace("\\", "/")
        acc = [s["accepted"] for s in (self.state.get("steps") or {}).values() if isinstance(s, dict) and
               s.get("state") == "done" and isinstance(s.get("accepted"), dict) and key in s["accepted"]]
        before = _sha_or_none(p) if acc else None
        write(p, data)
        for a in acc:
            if a[key] == before:
                a[key] = _sha_or_none(p)
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

    def family_chain(self, label):
        """The backend chain detection resolved for a family (families[f].chain; C13), or None (host sub-agents, or
        not known: the worker then detects it itself)."""
        info = (self.state.get("families") or {}).get(base_family(label)) or {}
        chain = info.get("chain")
        if info.get("backend") == "host" or not isinstance(chain, list):
            return None
        chain = [b for b in chain if isinstance(b, str) and b != "host"]
        return chain or None

    def family_web(self, label):
        if not (self.state.get("privacy") or {}).get("web", True):
            return False
        info = (self.state.get("families") or {}).get(base_family(label)) or {}
        return bool(info.get("web"))

    def date(self):
        created = self.state.get("created_at") or textio.now_iso()
        return created[:10]
