"""v1 bs.py scenarios shared by make_goldens.py (run against the v1 copy) and test_bs_legacy.py (run against the
kit bs.py). Each scenario writes inputs and runs bs.py commands in a temporary brainstorm/ folder without run.json.

Ported cases: the v1 test_bs.py harness (scenario sp_basic) and judge-uxtest (scenario ux_judges), plus
map/dupcheck, every status check, screen rules and tournament audits.

The golden of a scenario = every file under brainstorm/ that a bs.py command created or changed (inputs the scenario
wrote are excluded) + stdout.txt (the command transcript, with the run folder shown as <RUN>).
"""

import json
import os
import random
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
V1_BS = os.path.join(HERE, "v1", "bs_v1.py")
NO_ST = os.path.join(HERE, "no_st")
# v2 writes these extra files in v1 runs as well (additive; no v1 file changes)
V2_EXTRA_FILES = ("coverage.json", "tournament/result.json")

CRIT = {"Value": 30, "Feasibility": 25, "Fit": 20, "Distinctiveness": 15, "Evidence": 10}


class Runner(object):
    def __init__(self, bs_path, base, name):
        self.bs_path = bs_path
        self.base = os.path.abspath(base)
        self.root = os.path.join(self.base, "brainstorm")
        self.run = os.path.join(self.root, name)
        os.makedirs(self.run, exist_ok=True)
        self.inputs = {}
        self.log = []

    def path(self, rel):
        return os.path.join(self.run, *rel.split("/"))

    def w(self, rel, text, enc="utf-8"):
        p = self.path(rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        data = text.encode(enc)
        with open(p, "wb") as f:
            f.write(data)
        self.inputs[os.path.relpath(p, self.root).replace("\\", "/")] = data

    def wj(self, rel, obj, enc="utf-8"):
        self.w(rel, json.dumps(obj), enc)

    def rm(self, rel):
        os.remove(self.path(rel))
        self.inputs.pop(os.path.relpath(self.path(rel), self.root).replace("\\", "/"), None)

    def read_json(self, rel):
        with open(self.path(rel), "r", encoding="utf-8") as f:
            return json.load(f)

    def bs(self, cmd, *rest):
        env = dict(os.environ)
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONPATH"] = NO_ST
        env.pop("PYTHONHOME", None)
        proc = subprocess.run([sys.executable, self.bs_path, cmd, self.run] + list(rest), cwd=self.base,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
        out = proc.stdout.decode("utf-8", "replace").replace("\r\n", "\n")
        err = proc.stderr.decode("utf-8", "replace").replace("\r\n", "\n")
        text = "=== %s%s (rc=%d) ===\n%s" % (cmd, "".join(" " + a for a in rest), 0 if proc.returncode == 0 else 1,
                                             self._mask(out))
        if err.strip():
            text += "STDERR:\n" + self._mask(err)
        self.log.append(text)
        return proc

    def _mask(self, text):
        for p, tag in ((self.run, "<RUN>"), (self.root, "<ROOT>")):
            for form in (p, p.replace("\\", "/"), os.path.normpath(p)):
                text = text.replace(form, tag)
        return text.replace("\\", "/")

    def outputs(self):
        """{relpath under brainstorm/: bytes} for files bs.py created or changed."""
        out = {}
        for dirpath, _dirs, files in os.walk(self.root):
            for name in files:
                p = os.path.join(dirpath, name)
                rel = os.path.relpath(p, self.root).replace("\\", "/")
                with open(p, "rb") as f:
                    data = f.read()
                if self.inputs.get(rel) == data:
                    continue
                out[rel] = data
        return out

    def transcript(self):
        return "".join(self.log)


# ---------------------------------------------------------------- scenarios

def sp_basic(r):
    """Port of the v1 test_bs.py harness."""
    ids = ["I-%03d" % i for i in range(1, 9)]
    r.wj("criteria.json", CRIT)
    r.w("screen/header.md", "HEADER\n")
    r.w("screen/ideas.md", "\n".join("%s | title %s | pitch | mech" % (i, i) for i in ids) + "\n")
    r.wj("clusters.json", {i: "C%d" % (n % 4) for n, i in enumerate(ids)})
    r.wj("origins.json", {i: ["claude", "gpt", "human", "mixed"][n % 4] for n, i in enumerate(ids)})
    r.bs("schemas")
    r.bs("prepare-screen")
    rng = random.Random(7)

    def scores(kill_id=None, floor_id=None, str_scores=False, missing_key=False):
        out = []
        for i in ids:
            c = {k: rng.randint(2, 5) for k in CRIT}
            if i == floor_id:
                c = {k: 1 for k in CRIT}
            if str_scores:
                c = {k: str(v) for k, v in c.items()}
            if missing_key and i == "I-008":
                c.pop("Evidence")
            out.append({"id": i, "g1": i != kill_id, "g2": True, "g3": True, "c": c, "risk": "r"})
        return {"scores": out}

    r.wj("screen/claude.out.json", scores(kill_id="I-002", floor_id="I-003"))
    r.w("screen/gpt.out.json", "Here you go:\n```json\n" + json.dumps(
        scores(kill_id="I-002", floor_id="I-003", str_scores=True, missing_key=True)) + "\n```\n")
    r.bs("screen")
    r.w("tournament/cards.md", "".join("## %s\nTitle: t%s\nProblem: p\nMechanism: m\n\n" % (i, i) for i in ids[:6]))
    r.w("tournament/header.md", "TOURNAMENT HEADER\n")
    r.bs("prepare-tournament")

    def verdicts(fam, order, biased):
        m = r.read_json("tournament/%s_%s.map.json" % (fam, order))
        out = []
        for pid, p in m["pairs"].items():
            if biased:
                win = "FIRST"
            else:
                better = min(p["first"], p["second"])
                win = "FIRST" if p["first"] == better else "SECOND"
            out.append({"pair_id": pid, "winner": win, "confidence": 0.7, "decisive_reason": "x"})
        return {"verdicts": out}

    r.wj("tournament/claude_fwd.out.json", verdicts("claude", "fwd", True))
    r.wj("tournament/claude_rev.out.json", verdicts("claude", "rev", True))
    r.wj("tournament/gpt_fwd.out.json", verdicts("gpt", "fwd", False), enc="utf-16")
    # gpt_rev missing on purpose -> warning + split points
    r.bs("tournament")


def ux_judges(r):
    """Port of judge-uxtest (setup.py + judges.py): floor kill, single-judge gate flag, biased gpt judge,
    fenced and UTF-16 outputs."""
    ids = ["I-%03d" % i for i in range(1, 9)]
    r.wj("criteria.json", CRIT)
    r.wj("clusters.json", {k: "C%d" % ((i % 4) + 1) for i, k in enumerate(ids)})
    r.wj("origins.json", {"I-001": "human", "I-002": "claude", "I-003": "gpt", "I-004": "mixed", "I-005": "claude",
                          "I-006": "gpt", "I-007": "claude", "I-008": "gpt"})
    r.w("screen/ideas.md", "\n".join("%s | t | p | m" % k for k in ids) + "\n")
    r.w("screen/header.md", "HEADER\n")
    r.bs("schemas")
    r.bs("prepare-screen")
    rng = random.Random(7)
    for fam in ("claude", "gpt"):
        sc = []
        for k in ids:
            c = {x: rng.randint(2, 5) for x in CRIT}
            if k == "I-008":
                c["Fit"] = 1  # floor kill
            sc.append({"id": k, "g1": not (k == "I-006" and fam == "gpt"), "g2": True, "g3": True, "c": c,
                       "risk": "r"})
        r.wj("screen/%s.out.json" % fam, {"scores": sc})
    r.bs("screen")
    r.w("tournament/cards.md", "".join("## %s\nTitle: %s\nProblem: x\n" % (k, k) for k in ids[:5]))
    r.w("tournament/header.md", "JUDGE HEADER\n")
    r.bs("prepare-tournament")
    strength = {"I-001": 5, "I-002": 4, "I-003": 3, "I-004": 2, "I-005": 1}
    for fam in ("claude", "gpt"):
        for o in ("fwd", "rev"):
            m = r.read_json("tournament/%s_%s.map.json" % (fam, o))
            v = []
            for pid, p in m["pairs"].items():
                if fam == "gpt":
                    w = "FIRST"  # position-biased judge
                else:
                    w = "FIRST" if strength[p["first"]] >= strength[p["second"]] else "SECOND"
                v.append({"pair_id": pid, "winner": w, "confidence": 0.7, "decisive_reason": "x"})
            txt = json.dumps({"verdicts": v})
            if fam == "claude" and o == "rev":
                txt = "```json\n" + txt + "\n```"  # fenced output
            r.w("tournament/%s_%s.out.json" % (fam, o), txt, enc="utf-16" if (fam == "gpt" and o == "rev") else "utf-8")
    r.bs("tournament")


def map_and_dupcheck(r):
    """init, map (axes, human and primary ideas, warnings, pool notes, non-ASCII text), schemas, dupcheck fallback."""
    r.bs("init")
    r.bs("status")
    merges = {
        "strategy_family": {"S1": "claude", "S2": "claude", "S3": "gpt", "S4": "claude", "S5": "gpt", "G1": "gpt"},
        "axes": {"Stage": ["onboarding", "shift", "handover"], "Channel": ["app", "sms"]},
        "ideas": [
            {"key": "shift-swap-board", "title": "Shift swap board", "pitch": "Nurses post and claim shifts.",
             "mechanism": "A board with | pipes | in text", "aliases": ["S1-01", "S3-04", "H-02"],
             "cluster": "Scheduling", "cell": ["shift", "app"], "siblings": ["handover-voice"], "primary": True},
            {"key": "handover-voice", "title": "Handover voice notes \u2014 caf\xe9 edition",
             "pitch": "Record the handover.", "mechanism": "Voice memos tied to beds.", "aliases": ["S2-01"],
             "cluster": "Handover", "cell": ["handover", "app"], "baseline": True},
            {"key": "sms-nudges", "title": "SMS nudges", "pitch": "Text reminders for night staff.",
             "mechanism": "Scheduled SMS with opt-out.", "aliases": ["S5-02", "S5-03"], "cluster": "Scheduling",
             "cell": ["shift", "sms"]},
            {"key": "buddy-onboarding", "title": "Buddy onboarding", "pitch": "Pair new nurses with a buddy.",
             "mechanism": "Matching by ward and shift.", "aliases": ["HP-01"], "cluster": "Onboarding",
             "cell": ["onboarding", "app"]},
            {"key": "gap-fill", "title": "Gap fill", "pitch": "Fill open shifts fast.",
             "mechanism": "Broadcast to qualified staff.", "aliases": ["G1-01", "S3-04", "X9-01"],
             "cluster": "Scheduling", "cell": ["weekend", "fax"]},
            {"key": "quiet-room", "title": "Quiet room finder", "pitch": "Find a quiet room on break.",
             "mechanism": "Room sensors and a map.", "aliases": ["S4-01", "S4-02"], "cluster": "Wellbeing",
             "cell": ["shift", "app"]},
        ],
    }
    r.wj("merges.json", merges)
    r.w("03_POOL_NOTES.md", "## RE-RUN\nnone\n\n## LEAK CHECK\nclean\n")
    r.bs("map")
    r.wj("criteria.json", CRIT)
    r.bs("schemas")
    r.bs("dupcheck")
    r.bs("dupcheck", "--threshold", "0.05")


def status_walk(r):
    """Every status check, step by step (standard mode), then a quick-mode run folder."""
    r.w("00_RUN.md", "# Run: status-walk\n- mode: standard\n- strategy -> family map: S1=claude S2=claude S3=gpt "
                     "S4=claude S5=gpt\n")
    r.bs("status")
    r.w("00_HUMAN_SEEDS.md", "# Human seeds\n\n## Problem\nnight shifts\n\n## Ideas\n\n## Obvious\n")
    r.bs("status")
    r.w("00_HUMAN_SEEDS.md", "# Human seeds\n\nSKIPPED: no time\n")
    r.bs("status")
    r.w("00_HUMAN_SEEDS.md", "# Human seeds\n\n## Primary idea (to pressure-test)\nswap board\n\n## Ideas\n")
    r.w("01_FRAME.md", "# FRAME: x\n")
    r.w("criteria.json", json.dumps(CRIT))
    r.w("02_CONTEXT.md", "# Context\n")
    r.w("pool/S1_frames.md", "x\n")
    r.w("pool/S2_vs.md", "x\n")
    r.w("pool/S3.md", "x\n")
    r.bs("status")
    r.w("pool/S4_transfer.md", "x\n")
    r.w("pool/S5_ops.md", "x\n")
    for f in ("03_POOL.md", "clusters.json", "origins.json", "screen/ideas.md"):
        r.w(f, "{}\n")
    r.bs("status")
    r.w("04_SHORTLIST.md", "# Shortlist\nRescued: I-009 (human reason), E-01\n")
    r.w("screen/shortlist.json", json.dumps({"shortlist": [{"id": "I-001"}, {"id": "I-004"}]}))
    r.w("checks/I-001.md", "x\n")
    r.bs("status")
    r.w("checks/I-004.md", "x\n")
    r.w("checks/I-009.md", "x\n")
    r.w("checks/E-01.md", "x\n")
    r.w("05_EVOLVED.md", "# Evolved\n## E-01 a\n## E-02 b\n")
    r.bs("status")
    r.w("checks/E-02.md", "x\n")
    for f in ("tournament/result.md", "06_TOURNAMENT.md", "07_REDTEAM.md", "08_DECISION.md"):
        r.w(f, "x\n")
    r.w("09_PROBE.md", "# Probe\nno result yet\n")
    r.bs("status")
    r.w("09_PROBE.md", "# Probe\nRESULT: PASSED\n")
    r.bs("status")
    r.w("10_HANDOFF.md", "x\n")
    r.bs("status")
    r.w("00_RUN.md", "# Run: status-walk\n- mode: quick\n")
    r.bs("status")
    r.w("tournament/cards.md", "## Q-01\n")
    r.w("QUICK_DECISION.md", "x\n")
    r.bs("status")


def screen_rules(r):
    """Gate kills (both judges) vs flags (one judge), K3 floor, tail slot, human slot, primary ideas (killed and
    floored), borderline, one-judge warning, then criteria without Distinctiveness (tail slot skipped)."""
    ids = ["I-%03d" % i for i in range(1, 15)]
    r.wj("criteria.json", CRIT)
    r.wj("clusters.json", {i: ["Alpha", "Beta", "Gamma", "Delta", "Alpha", "Beta", "Gamma"][n % 7]
                           for n, i in enumerate(ids)})
    r.wj("origins.json", {i: ["claude", "gpt", "human-mixed", "ai-mixed", "gpt", "claude", "human"][n % 7]
                          for n, i in enumerate(ids)})
    r.wj("primary.json", ["I-004", "I-011", "I-099"])
    rng = random.Random(11)

    def judge(fam):
        out = []
        for i in ids:
            if fam == "gpt" and i == "I-014":
                continue  # only claude scored I-014
            c = {k: rng.randint(2, 5) for k in CRIT}
            if i == "I-011":
                c["Evidence"] = 1  # floor
            if i == "I-007":
                c = {"Value": 2, "Feasibility": 3, "Fit": 2, "Distinctiveness": 5, "Evidence": 2}
            g1 = not (i in ("I-004", "I-006") or (i == "I-009" and fam == "claude"))
            out.append({"id": i, "g1": g1, "g2": True, "g3": i != "I-012" or fam == "gpt", "c": c,
                        "risk": "risk %s %s" % (fam, i)})
        return {"scores": out}

    r.wj("screen/claude.out.json", judge("claude"))
    r.wj("screen/gpt.out.json", judge("gpt"))
    r.bs("screen")
    r.wj("criteria.json", {"Value": 50, "Fit": 30, "Evidence": 20})
    r.bs("screen")


def tourn_selfpref(r):
    """A self-preferring claude judge (flagged), then the same run marked PROVISIONAL (audit skipped)."""
    ids = ["I-%03d" % i for i in range(1, 6)]
    r.wj("origins.json", {"I-001": "claude", "I-002": "gpt", "I-003": "claude", "I-004": "human", "I-005": "gpt"})
    r.w("tournament/cards.md", "".join("## %s\nTitle: %s\nProblem: x\nMechanism: y\n\n" % (k, k) for k in ids))
    r.w("tournament/header.md", "JUDGE HEADER\n")
    r.bs("prepare-tournament")
    strength = {"I-001": 1, "I-002": 5, "I-003": 2, "I-004": 4, "I-005": 3}
    origins = r.read_json("origins.json")
    for fam in ("claude", "gpt"):
        for o in ("fwd", "rev"):
            m = r.read_json("tournament/%s_%s.map.json" % (fam, o))
            v = []
            for pid, p in sorted(m["pairs"].items()):
                a, b = p["first"], p["second"]
                if fam == "claude" and (origins[a] == "claude") != (origins[b] == "claude"):
                    win = "FIRST" if origins[a] == "claude" else "SECOND"
                elif strength[a] == strength[b]:
                    win = "TIE"
                else:
                    win = "FIRST" if strength[a] > strength[b] else "SECOND"
                v.append({"pair_id": pid, "winner": win, "confidence": 0.8, "decisive_reason": "x"})
            r.wj("tournament/%s_%s.out.json" % (fam, o), {"verdicts": v})
    r.bs("tournament")
    r.w("00_RUN.md", "# Run: x\n- mode: standard\n- host family: claude (claude-code)\n"
                     "- other family: none -> PROVISIONAL (claude-alt)\n")
    r.bs("tournament")


def tourn_perpair(r):
    """Batched prepare, then per-pair prepare (stale prompts removed); per-pair verdicts with a fenced, a UTF-16,
    a preamble, a garbage and a missing output, TIE verdicts and an unknown pair id."""
    ids = ["I-%03d" % i for i in range(1, 5)]
    r.wj("origins.json", {"I-001": "gpt", "I-002": "claude", "I-003": "human-mixed", "I-004": "ai-mixed"})
    r.w("tournament/cards.md", "intro line ignored\n" + "".join("## %s\nTitle: %s\n\nProblem: x\n" % (k, k)
                                                                 for k in ids))
    r.w("tournament/header.md", "JUDGE HEADER\r\nsecond line\r\n")
    r.bs("prepare-tournament")
    r.bs("prepare-tournament", "--per-pair")
    n = 0
    for fam in ("claude", "gpt"):
        for k in range(1, 7):
            for o in ("fwd", "rev"):
                n += 1
                base = "tournament/%s_%s_%03d" % (fam, o, k)
                p = r.read_json(base + ".map.json")["pairs"]["P01"]
                better = min(p["first"], p["second"])
                win = "FIRST" if p["first"] == better else "SECOND"
                if fam == "claude" and k == 2:
                    win = "FIRST"  # position bias on one pair
                if fam == "gpt" and k == 5:
                    win = "TIE"
                body = {"verdicts": [{"pair_id": "P01", "winner": win, "confidence": 0.6, "decisive_reason": "x"},
                                     {"pair_id": "P09", "winner": "FIRST", "confidence": 0.1,
                                      "decisive_reason": "unknown pair"}]}
                if fam == "claude" and k == 1 and o == "fwd":
                    r.w(base + ".out.json", "```json\n" + json.dumps(body) + "\n```\n")
                elif fam == "claude" and k == 3 and o == "rev":
                    r.wj(base + ".out.json", body, enc="utf-16")
                elif fam == "gpt" and k == 1 and o == "rev":
                    r.w(base + ".out.json", "Sure! Here is the JSON: " + json.dumps(body) + " Hope it helps.")
                elif fam == "gpt" and k == 2 and o == "fwd":
                    r.w(base + ".out.json", "I cannot comply.")
                elif fam == "gpt" and k == 6 and o == "rev":
                    continue  # missing output
                else:
                    r.wj(base + ".out.json", body)
    r.bs("tournament")


SCENARIOS = [
    ("sp_basic", "2026-09-23-sp-basic", sp_basic),
    ("ux_judges", "2026-09-23-ux-judges", ux_judges),
    ("map_and_dupcheck", "2026-09-23-night-shift-map", map_and_dupcheck),
    ("status_walk", "2026-09-23-status-walk", status_walk),
    ("screen_rules", "2026-09-23-screen-rules", screen_rules),
    ("tourn_selfpref", "2026-09-23-self-pref", tourn_selfpref),
    ("tourn_perpair", "2026-09-23-per-pair", tourn_perpair),
]


def run_scenario(bs_path, base, name):
    """Run one scenario with bs_path inside base. Returns (outputs {rel: bytes}, transcript str)."""
    for sname, run_name, fn in SCENARIOS:
        if sname == name:
            r = Runner(bs_path, base, run_name)
            fn(r)
            return r.outputs(), r.transcript()
    raise KeyError(name)
