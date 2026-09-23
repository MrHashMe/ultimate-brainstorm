"""v1 run folder -> run.json (KIT_SPEC 6.10).

A folder with 00_RUN.md and no run.json is migrated: mode, variant, topic, host and other family, privacy, python and
the strategy map are parsed from the v1 lines; families are claude/gpt; `legacy_v1: true`. Steps whose v1 outputs
exist are marked done so the run continues where it stopped. A v1 run that already has 10_HANDOFF.md gets the offer
"extend with architecture + proposal" as a G0-lite card.
"""

import glob
import os
import re

from .. import textio
from . import VENDORS
from . import state as st


def _line(text, key):
    m = re.search(r"^\W*" + key + r"\s*:\s*(.*)$", text, re.M | re.I)
    return m.group(1).strip() if m else ""


def parse_run_md(text):
    out = {}
    m = re.search(r"^#\s*Run:\s*(.+)$", text, re.M)
    out["slug"] = m.group(1).strip() if m else ""
    mode = _line(text, "mode").split()[0].lower() if _line(text, "mode") else "standard"
    out["mode"] = mode if mode in ("quick", "standard", "deep") else "standard"
    variant = (_line(text, "variant").split() or ["general"])[0].lower()
    out["variant"] = variant
    out["topic"] = _line(text, "topic")
    hf = _line(text, "host family")
    m = re.match(r"^\s*(claude|gpt)\b", hf, re.I)
    out["host_family"] = m.group(1).lower() if m else "claude"
    other = ""
    m = re.search(r"other family\s*:\s*(.*)$", text, re.M | re.I)
    if m:
        other = m.group(1).strip()
    out["other_family"] = other
    out["other_ok"] = bool(other) and not re.search(r"\bnone\b|provisional", other, re.I)
    priv = _line(text, "privacy")
    a = re.search(r"\(a\)[^:]*:\s*(yes|no)", priv, re.I)
    b = re.search(r"\(b\)[^:]*:\s*(yes|no)", priv, re.I)
    out["privacy"] = {"web": (a.group(1).lower() == "yes") if a else True,
                      "vendors": (a.group(1).lower() == "yes") if a else True,
                      "code": (b.group(1).lower() == "yes") if b else False}
    out["python"] = _line(text, "python") or "python"
    out["tools"] = _line(text, "detected tools")
    smap = {}
    m = re.search(r"strategy\s*->\s*family map\s*:\s*(.*)$", text, re.M | re.I)
    if m:
        for k, v in re.findall(r"(?<![\w-])([A-Z]+\d*)(?:-[A-Za-z-]+)?\s*[=:]\s*([A-Za-z-]+)", m.group(1)):
            smap[k] = v.lower()
    out["strategies"] = smap
    return out


# (stage steps, v1 outputs that prove the stage is done)
STAGE_PROOF = [
    (["0.1", "0.2", "0.3", "1.1", "1.2"], ["@seeds"]),
    (["2.0", "2.1g", "2.1gd", "2.1q", "2.1a", "2.1w", "2.1f", "2.1k", "2.2", "2.2f", "2.3"],
     ["01_FRAME.md", "criteria.json"]),
    (["3.1", "3.1b", "3.2"], ["02_CONTEXT.md"]),
    (["4.1c", "4.1f", "4.2", "4.3"], ["pool/*"]),
    (["5.1", "5.2", "5.2d", "5.2m", "5.3", "5.3c", "5.3m", "5.4", "5.4c", "5.4m"],
     ["03_POOL.md", "clusters.json", "origins.json", "screen/ideas.md"]),
    (["6.1", "6.2", "6.3", "6.4"], ["04_SHORTLIST.md", "screen/shortlist.json"]),
    (["7.1", "7.2", "7.3"], ["checks/*.md"]),
    (["8.0", "8.1", "8.1a", "8.2"], ["05_EVOLVED.md"]),
    (["9.1", "9.1h", "9.2", "9.3", "9.5", "9.4", "9.6"], ["tournament/result.md", "06_TOURNAMENT.md"]),
    (["10.1", "10.1h", "10.2", "10.3", "10.3r", "10.3f", "10.4", "10.4x", "10.5", "10.6"],
     ["07_REDTEAM.md", "08_DECISION.md"]),
    (["11.1", "11.2"], ["09_PROBE.md"]),
]
QUICK_PROOF = [
    (["0.1", "0.2", "0.3", "1.1", "2.1k", "2.2"], ["@seeds", "criteria.json"]),
    (["Q.2"], ["pool/*"]),
    (["Q.3", "Q.4"], ["tournament/cards.md"]),
    (["9.3", "9.5", "9.4", "9.6"], ["tournament/result.md"]),
    (["Q.6", "Q.7", "Q.8"], ["QUICK_DECISION.md"]),
]


def _proved(run_dir, items):
    for it in items:
        if it == "@seeds":
            text = ""
            for p in glob.glob(os.path.join(run_dir, "00_HUMAN_SEEDS*.md")):
                text += textio.read_text(p)
            if not (re.search(r"^\W*SKIPPED\b", text, re.M) or re.search(r"^##\s*(Ideas|Primary idea)[^\n]*\n\s*\S",
                                                                        text, re.M)):
                return False
        elif not glob.glob(os.path.join(run_dir, *it.split("/"))):
            return False
    return True


def migrate_v1(run_dir):
    text = textio.read_text(os.path.join(run_dir, "00_RUN.md"))
    info = parse_run_md(text)
    host = info["host_family"]
    other = "gpt" if host == "claude" else "claude"
    agent = "claude-code" if host == "claude" else "codex"
    state = st.new_state(run_dir, info["topic"], agent, host, "user", mode=info["mode"],
                         variant=info["variant"] if info["variant"] in (
                             "software", "product", "growth", "research", "marketing", "creative", "naming",
                             "general") else "general",
                         autopilot="guided", python=info["python"], runner="",
                         project_dir=os.path.dirname(os.path.dirname(os.path.abspath(run_dir))))
    state["legacy_v1"] = True
    state["privacy"].update(info["privacy"])
    state["families"] = {
        host: {"status": "ok", "backend": "claude-cli" if host == "claude" else "codex-cli", "web": True,
               "reason": ""},
        other: {"status": "ok" if info["other_ok"] else "unavailable",
                "backend": ("claude-cli" if other == "claude" else "codex-cli") if info["other_ok"] else None,
                "web": True, "reason": "" if info["other_ok"] else "v1 run: other family none (PROVISIONAL)"},
    }
    fams = [host] + ([other] if info["other_ok"] else [])
    state["privacy"]["allowed_vendors"] = sorted({VENDORS[f] for f in fams}) if state["privacy"]["vendors"] \
        else [VENDORS[host]]
    from . import seats as seats_mod
    web = dict((f, True) for f in fams)
    state["seats"] = seats_mod.assign(state["run"], host, fams, web, state["mode"], state["variant"], "s1f")
    if info["strategies"]:
        state["seats"]["generators"] = info["strategies"]
    state["seats"]["screen_judges"] = ["claude", "gpt"] if info["other_ok"] else [host, host + "-alt"]
    state["seats"]["tournament_judges"] = list(state["seats"]["screen_judges"])
    proofs = QUICK_PROOF if state["mode"] == "quick" else STAGE_PROOF
    for ids, items in proofs:
        if _proved(run_dir, items):
            for sid in ids:
                st.set_step(state, sid, "done", note="v1 output present")
        else:
            break
    if st.step_state(state, "0.2") == "done":
        st.record_gate(state, "G0", "answered", "human", {"reply": "(v1 run)"})
    dec = os.path.join(run_dir, "08_DECISION.md")
    if os.path.exists(dec):
        d = textio.read_text(dec)
        m = re.search(r"Chosen[^:]*:\s*([IEQ]-\d+)", d)
        r = re.search(r"Runner-up\s*:\s*([IEQ]-\d+)", d)
        state["choice"]["idea"] = m.group(1) if m else None
        state["choice"]["runner_up"] = r.group(1) if r else None
        st.record_gate(state, "G8b", "answered", "human", {"reply": "(v1 decision)", "chosen": state["choice"]["idea"]})
    cards_md = os.path.join(run_dir, "tournament", "cards.md")
    if os.path.exists(cards_md):
        ids = re.findall(r"^##\s+([IEQ]-\d+)", textio.read_text(cards_md), re.M)
        state["finalists"] = ids
        state["top"] = ids[:4]
    if os.path.exists(os.path.join(run_dir, "10_HANDOFF.md")):
        for ids, _ in proofs:
            for sid in ids:
                st.set_step(state, sid, "done", note="v1 run complete")
        state["interrupt"] = {"gate": "G0", "lite": True}
        st.add_note(state, "v1 run migrated: extend with architecture + proposal?")
    else:
        st.add_note(state, "v1 run migrated (legacy_v1); it continues with the v2 engine")
    return state
