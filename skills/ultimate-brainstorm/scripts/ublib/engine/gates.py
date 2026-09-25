"""HUMAN gates (KIT_SPEC 4.12, 6.2): policies per autopilot preset, answer templates and defaults, the deterministic
reply parser, validation, application and the display text written to gates/<GATE>.md.

apply() returns a list of effects that pipeline.apply_effects executes (reset steps, redo, stop).
"""

import copy
import os
import re
import shutil

from .. import textio
from . import (AUTOPILOTS, FAMILY_ORDER, MODES, TEMPLATES_DIR, VARIANTS, base_family)
from . import registry
from . import state as st

ID_RE = re.compile(r"\b([IEQ]-\d+)\b")

# answer_template fields beyond "reply" (4.12 gate list), with their empty values.
FIELDS = {
    "G0": {"confirm": None, "topic": None, "mode": None, "variant": None, "autopilot": None, "private": None,
           "privacy": {"web": None, "vendors": None, "code": None}, "families": None, "with_ce_ideate": None,
           "seeds": {"problem": None, "primary": None, "ideas": [], "obvious": [], "off_limits": []},
           "skip_seeds": None, "quick": {"criteria": [], "hard_constraint": None}, "idea": None},
    "G1": {"done": None, "skip": None},
    "G2": {"answers": [], "accept_defaults": None},
    "G2c": {"confirm": None, "corrections": None},
    "G2f": {"restore": None},
    "G3": {"ideas": [], "cells": []},
    "G4": {"rescue": [], "confirm_flags": []},
    "G5": {"kill": [], "keep": []},
    "G6": {"finalists": []},
    "G7": {"picks": []},
    "G8a": {"picks": [], "skip": None, "notes": None},
    "G8b": {"chosen": None, "runner_up": None, "bundle": [], "park": [], "why": None, "accept_recommendation": None},
    "G9": {"result": None, "note": None},
    "G10": {"confirm": None, "corrections": None},
    "G11": {"choice": None, "steal": [], "notes": None, "accept_recommendation": None},
    "G12": {"accept": [], "reject": []},
    "G13": {"action": None, "changes": None, "switch_to": None},
    "G14": {"publish": None, "merge_terms": None, "terms": [], "handoff": None},
    "GB": {"raise_to": None, "stop": None},
    "GX": {"action": None},
}

DEFAULTS = {
    "G0": {"reply": "", "confirm": True, "skip_seeds": True},
    "G1": {"reply": "", "skip": True},
    "G2": {"reply": "", "accept_defaults": True},
    "G2c": {"reply": "", "confirm": True},
    "G2f": {"reply": "", "restore": False},
    "G3": {"reply": ""},
    "G4": {"reply": ""},
    "G5": {"reply": ""},
    "G6": {"reply": ""},
    "G7": {"reply": ""},
    "G8a": {"reply": "", "skip": True},
    "G8b": {"reply": "", "accept_recommendation": True},
    "G9": {"reply": "", "result": "INCONCLUSIVE"},
    "G10": {"reply": "", "confirm": True},
    "G11": {"reply": "", "accept_recommendation": True},
    "G12": {"reply": "", "accept": [], "reject": []},
    "G13": {"reply": "", "action": "approve"},
    "G14": {"reply": "", "publish": False, "handoff": "none"},
    "GB": {"reply": "", "stop": True},
    "GX": {"reply": "", "action": "continue"},
}

TITLES = {
    "G0": "Kickoff", "G1": "Your seeds", "G2": "Frame questions", "G2c": "Confirm the frame",
    "G2f": "Repository docs changed", "G3": "Human round 2", "G4": "Rescues", "G5": "Confirm K4 kills",
    "G6": "Finalists", "G7": "Red-team picks", "G8a": "Gut pick", "G8b": "Decision", "G9": "Probe result",
    "G10": "Architecture drivers", "G11": "Architecture choice", "G12": "ADRs", "G13": "Sign-off",
    "G14": "Handoff", "GB": "Budget", "GX": "Whole effort",
}

HOW_TO_REPLY = {
    "G0": "Reply `go` to start (your own ideas, typed as above, go first in the same reply). You may also "
          "change anything above: a mode (quick, standard, deep), a variant, an autopilot (hands-on, guided, "
          "full-auto), `private`, or `web: no` / `vendors: no` / `code: yes`.",
    "G1": "Write your ideas in the seeds file shown above, then reply `done` (or `skip`).",
    "G2": "Answer by number (`1: ...`, one per line). A question with a default accepts it when you skip it; reply "
          "`defaults` to accept every default.",
    "G2c": "Reply `ok` to confirm, or write your corrections.",
    "G2f": "Reply `restore` to put CONTEXT.md back as it was before framing, or `keep`.",
    "G3": "Add ideas one per line (optional), and `cells: <a / b>; <c / d>` for cells you want filled. Reply `skip` "
          "to continue.",
    "G4": "Rescue up to 2 ideas (`rescue I-012: <reason>`), and confirm (`confirm I-004`, it is killed) or clear "
          "(`clear I-004`) each single-judge flag. Reply `ok` to accept the shortlist as it is.",
    "G5": "For each K4 candidate: `kill <ID>` or `keep <ID>`. Reply `ok` to keep them all (parked).",
    "G6": "Reply with up to 8 finalist IDs, or `ok` for the suggested set.",
    "G7": "Reply with 3-4 IDs to red-team, or `ok` for the suggested set.",
    "G8a": "Your gut top 3 IDs, in order, one line each with a reason (or `skip`).",
    "G8b": "Reply `ok` to accept the suggestion, or an ID and why (optional `runner-up: <ID>`, `park: <ID>`).",
    "G9": "Reply `passed`, `missed` or `inconclusive`, with the observed numbers.",
    "G10": "Reply `ok` to confirm, or write corrections.",
    "G11": "Reply `ok` for the suggestion, a letter (A, B, C, D), or a letter plus elements to take from another "
           "candidate (`B + steal A: offline cache`; `B+steal` takes the whole steal list).",
    "G12": "Reply `ok` to accept all, or `accept 1 2 4, reject 3`.",
    "G13": "Reply `approve`, `changes: <what to change>`, `switch <letter>` (another architecture) or `runner-up`.",
    "G14": "Reply `publish` (or `publish architecture`, `publish proposal`, `publish adr`) or `no`, and a handoff: "
           "`ce`, `speckit`, `superpowers`, `openspec` or `none`.",
    "GB": "Reply `raise to <number of calls>` to continue, or `stop`.",
    "GX": "Reply `reframe`, `continue` or `stop`.",
}

KEYWORDS = set(MODES) | set(VARIANTS) | set(AUTOPILOTS) | {"private", "with-ce-ideate", "go", "ok", "yes", "y",
                                                             "start", "okay", "sure", "continue"}


# ================================================================ templates and defaults

def answer_template(gid):
    t = {"reply": None}
    t.update(copy.deepcopy(FIELDS.get(gid, {})))
    return t


def default_answer(gid):
    return copy.deepcopy(DEFAULTS.get(gid, {"reply": ""}))


def all_gates():
    return sorted(FIELDS)


# ================================================================ policy (6.2)

def policy(ctx, gid):
    """'ask', 'auto' (default answer applied, by: auto) or 'skip' for a gate reached in the pipeline."""
    ap = ctx.autopilot
    mode = ctx.mode
    if gid == "G0":
        if ap != "full-auto":
            return "ask"
        explicit = (ctx.state.get("options") or {}).get("explicit_privacy")
        if explicit or st.config_get("privacy_defaults") is not None:
            return "auto"
        return "ask"
    if gid in ("G2f", "GX"):
        return "ask"
    if gid == "GB":
        return "skip" if ap == "full-auto" else "ask"
    if gid == "G2":
        return "auto" if ap == "full-auto" else "ask"
    if gid in ("G1", "G2c", "G3", "G6", "G7", "G9"):
        return "ask" if ap == "hands-on" else "skip"
    if gid in ("G4", "G5"):
        return "ask" if ap == "hands-on" else "auto"
    if gid == "G8a":
        if ap == "full-auto":
            return "skip"
        if mode in ("quick", "proposal") and ap != "hands-on":
            return "skip"  # 6.1: optional in quick and proposal mode (their guided reply counts are 3-4 and 4-5)
        return "ask"
    if gid == "G8b":
        return "auto" if ap == "full-auto" else "ask"
    if gid == "G10":
        if ap == "hands-on" or (mode == "deep" and ap == "guided"):
            return "ask"
        return "auto"
    if gid == "G11":
        if mode == "quick" or ap == "full-auto":
            return "auto"
        return "ask"
    if gid == "G12":
        if ap == "hands-on" or (mode == "deep" and ap == "guided"):
            return "ask"
        return "skip"
    if gid == "G13":
        return "auto" if ap == "full-auto" else "ask"
    if gid == "G14":
        return "skip" if ap == "full-auto" else "ask"
    return "ask"


# ================================================================ reply parsing (deterministic)

def _ids(text):
    return ID_RE.findall(text or "")


def _yesno(text):
    t = (text or "").strip().lower()
    if t in ("yes", "y", "true", "ok", "okay", "go", "sure", "approve", "done", "accept", "1"):
        return True
    if t in ("no", "n", "false", "0", "nope"):
        return False
    return None


def _strip_bullet(s):
    return re.sub(r"^\s*(?:[-*]|\d+[.)])\s*", "", s).strip()


def parse_kickoff(text):
    """G0 reply -> fields. A line is a keyword line only when EVERY word is a known keyword, so a seed like
    'deep learning ideas' stays a seed."""
    out = {"seeds": {"ideas": [], "obvious": [], "off_limits": []}, "privacy": {}, "quick": {}}
    for raw in (text or "").split("\n"):
        line = raw.strip()
        if not line:
            continue
        low = line.lower()
        toks = [t for t in re.split(r"[\s,]+", low) if t]
        if toks and all(t in KEYWORDS for t in toks):
            for t in toks:
                if t in MODES:
                    out["mode"] = t
                elif t in VARIANTS:
                    out["variant"] = t
                elif t in AUTOPILOTS:
                    out["autopilot"] = t
                elif t == "private":
                    out["private"] = True
                elif t == "with-ce-ideate":
                    out["with_ce_ideate"] = True
                else:
                    out["confirm"] = True
            continue
        if low in ("skip", "skip seeds", "no seeds", "none"):
            out["skip_seeds"] = True
            out["confirm"] = True
            continue
        m = re.match(r"^(primary(?: idea)?|problem|obvious|off[- ]limits|topic|idea|criteria|hard constraint|"
                     r"constraint|families|web|vendors|code)\s*:\s*(.*)$", line, re.I)
        if m:
            key, val = m.group(1).lower(), m.group(2).strip()
            if key.startswith("primary"):
                out["seeds"]["primary"] = val
            elif key == "problem":
                out["seeds"]["problem"] = val
            elif key == "obvious":
                out["seeds"]["obvious"].append(val)
            elif key.startswith("off"):
                out["seeds"]["off_limits"].append(val)
            elif key == "topic":
                out["topic"] = val
            elif key == "idea":
                out["idea"] = val
            elif key == "criteria":
                out["quick"]["criteria"] = [c.strip() for c in re.split(r"[,;]", val) if c.strip()][:3]
            elif key in ("hard constraint", "constraint"):
                out["quick"]["hard_constraint"] = val
            elif key == "families":
                out["families"] = [f.strip() for f in re.split(r"[,\s]+", val.lower()) if f.strip()]
            elif key in ("web", "vendors", "code"):
                yn = _yesno(val)
                if yn is not None:
                    out["privacy"][key] = yn
            continue
        seed = _strip_bullet(line)
        if seed:
            out["seeds"]["ideas"].append(seed)
    return out


def parse_reply(gid, text, ctx=None):
    """Structured fields from a free-text reply (terminal mode, --choice and hosts that fill only `reply`)."""
    t = (text or "").strip()
    low = t.lower()
    if gid == "G0":
        return parse_kickoff(t)
    if gid == "G1":
        if low.startswith("skip"):
            return {"skip": True}
        return {"done": True} if t else {}
    if gid == "G2":
        answers = []
        for m in re.finditer(r"^\s*(?:Q)?(\d+)\s*[.):-]\s*(.+)$", t, re.M | re.I):
            answers.append({"q": m.group(1), "a": m.group(2).strip()})
        out = {"answers": answers}
        if low in ("ok", "okay", "go", "yes", "defaults", "accept", "accept defaults", "") or \
                re.search(r"\b(ok|defaults)\b", low) and not answers:
            out["accept_defaults"] = True
        elif answers:
            out["accept_defaults"] = bool(re.search(r"\b(ok|defaults? for the rest)\b", low))
        return out
    if gid in ("G2c", "G10"):
        yn = _yesno(low)
        if yn is True or not t:
            return {"confirm": True}
        return {"confirm": False, "corrections": t}
    if gid == "G2f":
        if "restore" in low:
            return {"restore": True}
        return {"restore": False}
    if gid == "G3":
        if low in ("skip", "ok", "none", "no", ""):
            return {"ideas": [], "cells": []}
        ideas, cells = [], []
        for ln in t.split("\n"):
            m = re.match(r"^\s*cells?\s*:\s*(.+)$", ln, re.I)
            if m:
                cells += [c.strip() for c in m.group(1).split(";") if c.strip()]
            elif _strip_bullet(ln):
                ideas.append(_strip_bullet(ln))
        return {"ideas": ideas, "cells": cells}
    if gid == "G4":
        rescue, confirm = [], []
        if low in ("ok", "okay", "go", "yes", "none", "no", ""):
            return {"rescue": [], "confirm_flags": []}
        for ln in re.split(r"[\n;]", t):
            ids = _ids(ln)
            if not ids:
                continue
            if re.match(r"^\W*confirm\b", ln, re.I):
                confirm += ids
                continue
            if re.match(r"^\W*clear\b", ln, re.I):
                continue
            reason = re.sub(r"^.*?\b%s\b\W*(because\W*)?" % re.escape(ids[0]), "", ln, flags=re.I).strip()
            rescue.append({"id": ids[0], "reason": reason or "rescued by the user"})
        return {"rescue": rescue, "confirm_flags": confirm}
    if gid == "G5":
        kill, keep = [], []
        for ln in t.split("\n"):
            if re.search(r"\bkill\b", ln, re.I):
                kill += _ids(ln)
            elif re.search(r"\bkeep\b", ln, re.I):
                keep += _ids(ln)
        return {"kill": kill, "keep": keep}
    if gid in ("G6",):
        return {"finalists": _ids(t)}
    if gid in ("G7",):
        return {"picks": _ids(t)}
    if gid == "G8a":
        if low.startswith("skip") or not t:
            return {"skip": True}
        return {"picks": _ids(t)[:3], "notes": t}
    if gid == "G8b":
        out = {}
        if re.match(r"^(ok|okay|yes|y|go|accept|agreed?|fine)\b[.!]*$", low) or not t:
            out["accept_recommendation"] = True
            return out
        m = re.search(r"runner[- ]?up\s*:?\s*([IEQ]-\d+)", t, re.I)
        if m:
            out["runner_up"] = m.group(1)
        park = []
        for pm in re.finditer(r"park\s*:?\s*((?:[IEQ]-\d+[\s,]*)+)", t, re.I):
            park += _ids(pm.group(1))
        if park:
            out["park"] = park
        rest = t
        for rm in (m,):
            if rm:
                rest = rest.replace(rm.group(0), " ")
        ids = [i for i in _ids(rest) if i not in park]
        if ids:
            out["chosen"] = ids[0]
            out["accept_recommendation"] = False
        elif re.match(r"^(ok|okay|yes|accept)\b", low):
            out["accept_recommendation"] = True
        out["why"] = t
        return out
    if gid == "G9":
        m = re.search(r"\b(passed|missed|inconclusive)\b", low)
        return {"result": m.group(1).upper() if m else None, "note": t}
    if gid == "G11":
        if re.match(r"^(ok|okay|yes|y|go|accept)\b", low) or not t:
            return {"accept_recommendation": True}
        m = re.match(r"^\s*(?:choose\s+|pick\s+|candidate\s+)?([A-Fa-f])\b\s*(\+\s*steal\b)?", t)
        if m:
            steal = []
            for sm in re.finditer(r"steal\s+(?:from\s+)?([A-Fa-f])\s*:\s*([^;\n]+)", t, re.I):
                steal.append({"from": sm.group(1).upper(), "element": sm.group(2).strip()})
            if not steal and m.group(2):
                steal = ["*"]
            return {"choice": m.group(1).upper(), "accept_recommendation": False, "steal": steal, "notes": t}
        return {"notes": t}
    if gid == "G12":
        if re.match(r"^(ok|okay|yes|accept all|approve)\b", low) or re.search(r"accept\s+all", low):
            return {"accept": ["all"], "reject": []}

        def nums(key):
            m = re.search(key + r"([^a-z]*)", low)
            return ["%04d" % int(n) for n in re.findall(r"\d{1,4}", m.group(1))] if m else []
        return {"accept": nums("accept"), "reject": nums("reject")}
    if gid == "G13":
        if low.startswith("approve") or low in ("ok", "yes", "go"):
            return {"action": "approve"}
        m = re.match(r"^\s*changes?\s*:?\s*(.*)$", t, re.I | re.S)
        if m:
            return {"action": "changes", "changes": m.group(1).strip() or t}
        m = re.match(r"^\s*switch\s+(?:to\s+)?(?:architecture\s+)?([A-Da-d])\b", t, re.I)
        if m:
            return {"action": "switch", "switch_to": m.group(1).upper()}
        if re.match(r"^\s*runner[- ]?up\b", low):
            return {"action": "runner-up"}
        return {"action": "changes", "changes": t} if t else {"action": "approve"}
    if gid == "G14":
        out = {}
        if re.search(r"\bpublish\b", low) and not re.search(r"\b(no|don'?t)\s+publish\b", low):
            items = [x for x in ("architecture", "adr", "proposal") if x in low]
            out["publish"] = items if items else True
        elif re.search(r"\b(no|none|skip)\b", low):
            out["publish"] = False
        hm = re.search(r"handoff\s*:?\s*(ce|speckit|superpowers|openspec|none)\b", low)
        if hm:
            out["handoff"] = hm.group(1)
        else:
            for h in ("ce", "speckit", "superpowers", "openspec"):
                if re.search(r"\b%s\b" % h, low):
                    out["handoff"] = h
                    break
        if "handoff" not in out and re.match(r"^\s*(no|none|skip)\b", low):
            out["handoff"] = "none"
        m = re.search(r"merge\s*:?\s*(all|some|none|defer)", low)
        if m:
            out["merge_terms"] = m.group(1)
        return out
    if gid == "GB":
        m = re.search(r"\b(\d{1,5})\b", t)
        if m:
            return {"raise_to": int(m.group(1)), "stop": False}
        return {"stop": True} if "stop" in low or not t else {}
    if gid == "GX":
        for a in ("reframe", "continue", "stop"):
            if a in low:
                return {"action": a}
        return {}
    return {}


def merge_answer(gid, provided, ctx=None):
    """answer_template <- provided fields; then the reply fills fields that are still empty."""
    ans = answer_template(gid)
    for k, v in (provided or {}).items():
        if isinstance(v, dict) and isinstance(ans.get(k), dict):
            for kk, vv in v.items():
                if vv is not None:
                    ans[k][kk] = vv
        elif v is not None:
            ans[k] = v
    reply = ans.get("reply")
    if reply:
        parsed = parse_reply(gid, reply, ctx)
        for k, v in parsed.items():
            cur = ans.get(k)
            if isinstance(v, dict) and isinstance(cur, dict):
                for kk, vv in v.items():
                    if cur.get(kk) in (None, [], "") and vv not in (None, [], ""):
                        cur[kk] = vv
            elif cur in (None, [], "") and v not in (None, [], ""):
                ans[k] = v
    return ans


def from_choice(gid, choice):
    ans = {"reply": choice}
    return ans


# ================================================================ validation

def validate(ctx, gid, ans):
    """Errors (list of str) for an answer; the gate is re-asked with the first error."""
    errs = []
    if gid == "G0":
        for key, allowed in (("mode", MODES), ("variant", VARIANTS), ("autopilot", AUTOPILOTS)):
            if ans.get(key) and ans[key] not in allowed:
                errs.append("%s must be one of %s" % (key, ", ".join(allowed)))
        if ans.get("families"):
            bad = [f for f in ans["families"] if base_family(f) not in FAMILY_ORDER]
            if bad:
                errs.append("unknown families: %s (use %s)" % (", ".join(bad), ", ".join(FAMILY_ORDER)))
        topic = ans.get("topic") or ctx.state.get("topic")
        if not (topic or "").strip():
            errs.append("What is the topic? Reply with it in one line (for example `topic: AI tutor for "
                        "night-shift nurses`).")
        mode = ans.get("mode") or ctx.mode
        if mode == "proposal" and not (ans.get("idea") or ctx.state.get("idea_text") or topic):
            errs.append("Proposal mode needs your idea in one sentence (`idea: ...`).")
        lite = (ctx.state.get("interrupt") or {}).get("gate") == "G0"
        if ans.get("confirm") is False and not lite and not any(ans.get(k) for k in ("mode", "variant", "autopilot",
                                                                                     "topic")):
            errs.append("Tell me what to change, or reply `go`.")
    elif gid == "G1":
        if ans.get("done") and not ans.get("skip"):
            text = ctx.read("00_HUMAN_SEEDS.md")
            if not (registry.section(text, "Ideas") or registry.section(text, "Primary idea") or
                    re.search(r"^\W*SKIPPED\b", text, re.M)):
                errs.append("The seeds file has no ideas yet: write them in the Ideas section (or reply `skip`).")
        elif not ans.get("done") and not ans.get("skip"):
            errs.append("Reply `done` when the seeds file is written, or `skip`.")
    elif gid == "G2":
        if not ans.get("answers") and not ans.get("accept_defaults") and not (ans.get("reply") or "").strip():
            errs.append("Answer the questions by number, or reply `ok` to accept the defaults.")
    elif gid in ("G2c", "G10"):
        if ans.get("confirm") is None and not ans.get("corrections"):
            errs.append("Reply `ok` to confirm, or write your corrections.")
    elif gid == "G4":
        if len(ans.get("rescue") or []) > 2:
            errs.append("At most 2 rescues.")
        known = set(registry.idea_lines(ctx))
        for r in ans.get("rescue") or []:
            if isinstance(r, dict) and known and r.get("id") not in known:
                errs.append("unknown idea %s" % r.get("id"))
    elif gid == "G6":
        fin = ans.get("finalists") or []
        if len(fin) > 8:
            errs.append("At most 8 finalists.")
    elif gid == "G7":
        if ans.get("picks") and not 1 <= len(ans["picks"]) <= 4:
            errs.append("Pick 3 or 4 ideas.")
    elif gid == "G8a":
        picks = ans.get("picks") or []
        fin = ctx.state.get("finalists") or []
        if not ans.get("skip") and not picks:
            errs.append("Name up to 3 finalist IDs (for example I-014), or reply `skip`.")
        bad = [p for p in picks if fin and p not in fin]
        if bad:
            errs.append("%s is not a finalist (finalists: %s)" % (", ".join(bad), ", ".join(fin)))
        if len(picks) > 3:
            errs.append("At most 3 picks.")
    elif gid == "G8b":
        allowed = ctx.state.get("top") or ctx.state.get("finalists") or []
        if not ans.get("accept_recommendation") and not ans.get("chosen"):
            errs.append("Name the idea you choose (an ID such as %s), or reply `ok` for the suggestion."
                        % (allowed[0] if allowed else "I-001"))
        if ans.get("chosen") and allowed and ans["chosen"] not in (ctx.state.get("finalists") or allowed):
            errs.append("%s is not one of the finalists (%s)" % (ans["chosen"], ", ".join(allowed)))
    elif gid == "G9":
        if (ans.get("result") or "").upper() not in ("PASSED", "MISSED", "INCONCLUSIVE"):
            errs.append("Reply `passed`, `missed` or `inconclusive`.")
    elif gid == "G11":
        labels = registry.arch_labels(ctx)
        if not ans.get("accept_recommendation") and not ans.get("choice"):
            errs.append("Reply `ok` for the suggestion or a letter (%s)." % ", ".join(labels or ["A", "B"]))
        if ans.get("choice") and labels and ans["choice"] not in labels:
            errs.append("%s is not a candidate (%s)" % (ans["choice"], ", ".join(labels)))
    elif gid == "G13":
        if ans.get("action") not in ("approve", "changes", "switch", "runner-up"):
            errs.append("Reply `approve`, `changes: ...`, `switch <letter>` or `runner-up`.")
        if ans.get("action") == "switch":
            labels = registry.arch_labels(ctx)
            if not ans.get("switch_to") or (labels and ans["switch_to"] not in labels):
                errs.append("Name the architecture to switch to (%s)." % ", ".join(labels))
        if ans.get("action") == "runner-up" and not (ctx.state.get("choice") or {}).get("runner_up"):
            errs.append("No runner-up was recorded at the decision.")
        if ans.get("action") == "changes" and int((ctx.state.get("counters") or {}).get("g13_loops", 0)) >= 2:
            errs.append("Two change rounds are already done; reply `approve`, `switch` or `runner-up`.")
    elif gid == "G14":
        if ans.get("handoff") and ans["handoff"] not in ("ce", "speckit", "superpowers", "openspec", "none"):
            errs.append("handoff must be ce, speckit, superpowers, openspec or none")
    elif gid == "GB":
        if not ans.get("stop") and not ans.get("raise_to"):
            errs.append("Reply a new cap (a number) or `stop`.")
        if ans.get("raise_to"):
            try:
                if int(ans["raise_to"]) <= int((ctx.state.get("counters") or {}).get("launched", 0)):
                    errs.append("The new cap must be above the %s calls already made."
                                % (ctx.state.get("counters") or {}).get("launched", 0))
            except (TypeError, ValueError):
                errs.append("raise_to must be a number")
    elif gid == "GX":
        if ans.get("action") not in ("reframe", "continue", "stop"):
            errs.append("Reply `reframe`, `continue` or `stop`.")
    return errs


# ================================================================ application

def apply(ctx, gid, ans, by="human"):
    """Apply an accepted answer to the run. Returns a list of effects for the pipeline:
    ("reset", [step ids]) | ("redo", step_id) | ("stop", reason) | ("interrupt_clear",)."""
    s = ctx.state
    effects = []
    fn = _APPLY.get(gid)
    if fn:
        effects = fn(ctx, ans, by) or []
    state_name = "auto" if by == "auto" else "answered"
    st.record_gate(s, gid, state_name, by, ans)
    try:
        textio.write_json_atomic(ctx.path("answers", "%s.json" % gid), ans)
    except OSError:
        pass
    return effects


def _apply_g0(ctx, ans, by):
    s = ctx.state
    intr = s.get("interrupt") or {}
    if intr.get("gate") == "G0" and (ans.get("reply") or "").strip().lower() in ("stop", "no", "n", "cancel"):
        return [("interrupt_clear",), ("stop", "the user declined to extend the v1 run")]
    if ans.get("topic"):
        s["topic"] = ans["topic"]
    if ans.get("mode") and ans["mode"] != s.get("mode"):
        s["mode"] = ans["mode"]
        s["budget"]["max_calls"] = st.budget_cap(ans["mode"])
    if ans.get("variant"):
        s["variant"] = ans["variant"]
        s["build_type"] = st.build_type_for(ans["variant"])
    if ans.get("autopilot"):
        s["autopilot"] = ans["autopilot"]
    if ans.get("idea"):
        s["idea_text"] = ans["idea"]
    if s.get("mode") == "proposal" and not s.get("idea_text"):
        s["idea_text"] = s.get("topic", "")
    priv = s.setdefault("privacy", {})
    if ans.get("private"):
        priv.update({"web": False, "vendors": False, "code": False})
        s.setdefault("options", {})["private"] = True
    for k in ("web", "vendors", "code"):
        v = (ans.get("privacy") or {}).get(k)
        if v is not None:
            priv[k] = bool(v)
    if ans.get("with_ce_ideate"):
        s.setdefault("options", {})["with_ce_ideate"] = True
    if ans.get("families"):
        keep = set(base_family(f) for f in ans["families"]) | {ctx.host_family}
        for f, info in (s.get("families") or {}).items():
            if f not in keep and info.get("status") == "ok":
                info["status"] = "excluded"
                info["reason"] = "excluded at kickoff"
    q = ans.get("quick") or {}
    if q.get("criteria") or q.get("hard_constraint"):
        s["quick"] = {"criteria": q.get("criteria") or [], "hard_constraint": q.get("hard_constraint")}
    return []


def _apply_g1(ctx, ans, by):
    if ans.get("skip"):
        text = ctx.read("00_HUMAN_SEEDS.md")
        if not (registry.section(text, "Ideas") or registry.section(text, "Primary idea")):
            ctx.write("00_HUMAN_SEEDS.md", "SKIPPED: the user skipped the seeds at G1\n")
    return []


def _norm_qid(q):
    m = re.match(r"^\D*0*(\d+)$", str(q or "").strip())
    return m.group(1) if m else str(q or "").strip()


def _apply_g2(ctx, ans, by):
    # answers by number ("1: ...") are mapped onto the question ids (Q01 ...) in asking order
    qs = registry.frame_questions(ctx)
    by_num = dict((str(n), q["id"]) for n, q in enumerate(qs, 1))
    by_norm = dict((_norm_qid(q["id"]), q["id"]) for q in qs)
    answers = []
    for a in ans.get("answers") or []:
        if not isinstance(a, dict):
            continue
        key = _norm_qid(a.get("q"))
        qid = by_num.get(key) or by_norm.get(key) or a.get("q")
        answers.append({"q": qid, "a": a.get("a")})
    data = {"answers": answers, "accept_defaults": bool(ans.get("accept_defaults")),
            "reply": ans.get("reply") or ""}
    ctx.write_json("frame/answers.json", data)
    return []


def _apply_g2c(ctx, ans, by):
    if ans.get("corrections"):
        c = ctx.state.setdefault("counters", {})
        c["g2c_loops"] = int(c.get("g2c_loops", 0)) + 1
        fr = ctx.read("01_FRAME.md")
        ctx.write("01_FRAME.md", fr.rstrip() + "\n\n## User corrections\n%s\n" % ans["corrections"])
    return []


def _apply_g2f(ctx, ans, by):
    if ans.get("restore"):
        pd = ctx.state.get("project_dir")
        src = ctx.path("CONTEXT.before.md")
        if pd and os.path.exists(src):
            shutil.copy2(src, os.path.join(pd, "CONTEXT.md"))
    return []


def _apply_g3(ctx, ans, by):
    ideas = [i for i in ans.get("ideas") or [] if i]
    if ideas:
        ctx.write("00b_HUMAN_ROUND2.md", "# Human round 2\n\n## Ideas\n%s\n" % "\n".join("- %s" % i for i in ideas))
    return []


def _apply_g4(ctx, ans, by):
    """Rescues join the shortlist (the Rescued: line of 04_SHORTLIST.md); a confirmed single-judge flag kills."""
    confirm = [i for i in ans.get("confirm_flags") or [] if i]
    if confirm:
        ctx.state["killed"] = sorted(set((ctx.state.get("killed") or []) + confirm))
    registry.render_shortlist(ctx)
    return []


def _apply_g5(ctx, ans, by):
    s = ctx.state
    kill = [k for k in ans.get("kill") or []]
    keep = set(ans.get("keep") or [])
    cands = s.get("k4_candidates") or []
    s["killed"] = sorted(set((s.get("killed") or []) + kill))
    parked = s.setdefault("parked", [])
    for c in cands:
        if c not in kill and c not in keep and c not in parked:
            parked.append(c)
    registry.render_shortlist(ctx)
    return []


def _apply_g6(ctx, ans, by):
    if ans.get("finalists"):
        ctx.state["finalists"] = list(ans["finalists"])[:8]
    return []


def _apply_g7(ctx, ans, by):
    if ans.get("picks"):
        ctx.state["top"] = list(ans["picks"])[:4]
    return []


def _apply_g8a(ctx, ans, by):
    if ans.get("skip") and not ans.get("picks"):
        text = "SKIPPED: no gut pick (%s)\n" % ("autopilot" if by == "auto" else "the user skipped it")
    else:
        lines = ["# Pre-commit (gut pick, written before any tally)", ""]
        for n, p in enumerate(ans.get("picks") or [], 1):
            lines.append("%d. %s" % (n, p))
        if ans.get("notes") or ans.get("reply"):
            lines += ["", "In the user's words: %s" % (ans.get("reply") or ans.get("notes"))]
        text = "\n".join(lines) + "\n"
    ctx.write("tournament/precommit.md", text)
    return []


def _apply_g8b(ctx, ans, by):
    s = ctx.state
    sug, rule = registry.suggestion(ctx)
    chosen = ans.get("chosen")
    if ans.get("accept_recommendation") or not chosen:
        chosen = sug
        ans["rule"] = rule
    ans["chosen"] = chosen
    runner = ans.get("runner_up")
    if not runner:
        pct = registry.debiased_pct(ctx)
        rest = [i for i in (s.get("top") or s.get("finalists") or []) if i != chosen]
        rest.sort(key=lambda i: (-pct.get(i, 0.0), i))
        runner = rest[0] if rest else None
    s["choice"]["idea"] = chosen
    s["choice"]["runner_up"] = runner
    return []


def _apply_g9(ctx, ans, by):
    return probe_result(ctx, (ans.get("result") or "INCONCLUSIVE").upper(), ans.get("note") or ans.get("reply"))


def probe_result(ctx, result, note):
    """Append the result to 09_PROBE.md; MISSED -> K6: the runner-up becomes the chosen idea."""
    text = ctx.read("09_PROBE.md")
    label = {"PASSED": "PASSED", "MISSED": "MISSED (K6)", "INCONCLUSIVE": "INCONCLUSIVE"}[result]
    # one RESULT line only: the pre-registered 'RESULT: PENDING' is replaced, never left above the real result
    text = re.sub(r"(?m)^RESULT: PENDING\s*$\n?", "", text)
    block = "\n## Result\n%s\nRESULT: %s\n" % ((note or "").strip() or "(no numbers reported)", label)
    ctx.write("09_PROBE.md", text.rstrip() + "\n" + block)
    ctx.state.setdefault("probe", {}).update({"result": result, "at": textio.now_iso()})
    effects = []
    if result in ("PASSED", "INCONCLUSIVE"):
        # re-render every status-bearing document (architecture README, PROPOSAL.md, ONE-PAGER, index.html,
        # 12_HANDOFF.md); steps the run never reached are skipped by reset
        done = [sid for sid in ("12.15", "13.4b", "13.7", "13.9", "14.4") if st.step_state(ctx.state, sid) == "done"]
        if done:
            effects.append(("reset", done))
    if result == "MISSED":
        ch = ctx.state.get("choice") or {}
        dec = ctx.read("08_DECISION.md")
        ctx.write("08_DECISION.md", dec.rstrip() + "\nKilled: %s - K6 (the pre-registered probe missed)\n"
                  % ch.get("idea"))
        if ch.get("runner_up"):
            ctx.state["choice"]["idea"], ctx.state["choice"]["runner_up"] = ch["runner_up"], None
            effects.append(("supersede", "11.1"))
    return effects


def _apply_g10(ctx, ans, by):
    if ans.get("corrections"):
        c = ctx.state.setdefault("counters", {})
        c["g10_loops"] = int(c.get("g10_loops", 0)) + 1
        brief = ctx.read("10_ARCHITECTURE/00_BRIEF.md")
        ctx.write("10_ARCHITECTURE/00_BRIEF.md", brief.rstrip() + "\n\n## User corrections\n%s\n"
                  % ans["corrections"])
        if c["g10_loops"] <= 2:
            return [("reset", ["12.2", "12.3"])]
    return []


def _apply_g11(ctx, ans, by):
    matrix = ctx.read_json("10_ARCHITECTURE/matrix.json", {}) or {}
    label = ans.get("choice")
    if ans.get("accept_recommendation") or not label:
        label = matrix.get("leader") or (registry.arch_labels(ctx) or ["A"])[0]
        ans["choice"] = label
    if ans.get("steal") == ["*"]:
        ans["steal"] = [{"from": x.get("from"), "element": x.get("element")} for x in matrix.get("steal") or []
                        if isinstance(x, dict) and x.get("from") != label]
    m = ctx.read_json("10_ARCHITECTURE/candidates/map.json", {}) or {}
    fam = (m.get(label) or {}).get("family")
    ctx.state["choice"]["arch"] = label
    ctx.state["choice"]["arch_family"] = fam
    ctx.state.setdefault("seats", {})["arch_writer"] = fam or ctx.host_family
    return []


def _apply_g12(ctx, ans, by):
    statuses = ctx.read_json("10_ARCHITECTURE/adr_status.json", {}) or {}
    adrs = sorted(os.path.basename(p)[:4] for p in _adr_files(ctx))
    acc = ans.get("accept") or []
    if "all" in acc:
        acc = adrs
    for n in acc:
        statuses[n] = "accepted"
    for n in ans.get("reject") or []:
        statuses[n] = "rejected"
    ctx.write_json("10_ARCHITECTURE/adr_status.json", statuses)
    from . import render_arch
    render_arch.rerender_adrs(ctx)
    return []


def _adr_files(ctx):
    import glob
    return glob.glob(ctx.path("10_ARCHITECTURE", "adr", "*.md"))


def _apply_g13(ctx, ans, by):
    s = ctx.state
    action = ans.get("action") or "approve"
    if action == "approve":
        s["signed_off"] = by != "auto"
        if by != "auto":
            statuses = ctx.read_json("10_ARCHITECTURE/adr_status.json", {}) or {}
            for p in _adr_files(ctx):
                n = os.path.basename(p)[:4]
                if statuses.get(n) != "rejected":
                    statuses[n] = "accepted"
            ctx.write_json("10_ARCHITECTURE/adr_status.json", statuses)
            from . import render_arch
            render_arch.rerender_adrs(ctx)
        # the architecture README carries the status banner too (DRAFT -> APPROVED)
        return [("reset", ["12.15", "13.4b", "13.7"])]
    if action == "changes":
        c = s.setdefault("counters", {})
        c["g13_loops"] = int(c.get("g13_loops", 0)) + 1
        s["user_changes"] = ans.get("changes") or ans.get("reply") or ""
        return [("reset", ["13.6", "13.4b", "13.7", "13.8"])]
    if action == "switch":
        return [("switch_arch", ans.get("switch_to"))]
    if action == "runner-up":
        return [("switch_idea", (s.get("choice") or {}).get("runner_up"))]
    return []


def _apply_g14(ctx, ans, by):
    return []


def _apply_gb(ctx, ans, by):
    if ans.get("raise_to") and not ans.get("stop"):
        ctx.state["budget"]["max_calls"] = int(ans["raise_to"])
        return [("interrupt_clear",)]
    return [("interrupt_clear",), ("stop", "stopped at the budget cap")]


def _apply_gx(ctx, ans, by):
    a = ans.get("action")
    if a == "stop":
        return [("stop", "the user stopped the whole effort")]
    if a == "reframe":
        return [("supersede", "2.1g")]
    ctx.state.setdefault("facts", {})["gx_continue"] = True
    return []


_APPLY = {"G0": _apply_g0, "G1": _apply_g1, "G2": _apply_g2, "G2c": _apply_g2c, "G2f": _apply_g2f,
          "G3": _apply_g3, "G4": _apply_g4, "G5": _apply_g5, "G6": _apply_g6, "G7": _apply_g7, "G8a": _apply_g8a,
          "G8b": _apply_g8b, "G9": _apply_g9, "G10": _apply_g10, "G11": _apply_g11, "G12": _apply_g12,
          "G13": _apply_g13, "G14": _apply_g14, "GB": _apply_gb, "GX": _apply_gx}


def kickoff_note(ctx):
    s = ctx.state
    return "mode %s, variant %s, autopilot %s, families %s" % (
        s.get("mode"), s.get("variant"), s.get("autopilot"), ", ".join((s.get("seats") or {}).get("families") or []))


def _families_line(ctx):
    from . import progress
    return progress.families_line(ctx)


# ================================================================ gate template values (templates/gates/<G>.md)

def provisional_banner(ctx):
    """'PROVISIONAL: <reason>' when any seat runs as <family>-alt or was re-seated; '' otherwise."""
    s = ctx.state
    reasons = []
    if st.single_family(s) and s.get("families"):
        reasons.append("only one model family is available, so every cross-family seat is %s-alt"
                       % ((s.get("host") or {}).get("family") or "host"))
    prov = [p for p in s.get("provisional") or [] if isinstance(p, dict)]
    if prov:
        reasons.append("%d seat(s) ran on a substitute (%s)" % (len(prov), "; ".join(
            "%s: %s -> %s" % (p.get("stage"), p.get("seat"), p.get("actual")) for p in prov[:3])))
    return ("PROVISIONAL: " + "; ".join(reasons)) if reasons else ""


def _bullets(items, empty="none"):
    items = [i for i in items if i]
    return "\n".join("- %s" % i for i in items) if items else empty


def _title(ctx, iid):
    return registry.idea_lines(ctx).get(iid, {}).get("title", "")


def _v_g0(ctx):
    from . import progress
    s = ctx.state
    plan = progress.plan_for_state(ctx)
    extra = []
    if s.get("legacy_v1"):
        extra.append("This is a v1 run. Reply `go` to extend it with an architecture package and a full proposal, "
                     "or `stop`.")
    if not (s.get("topic") or "").strip():
        extra.append("No topic yet: reply with `topic: <your topic>`.")
    extra.append("Variant: %s%s. Seeds file: %s" % (
        s.get("variant"), " (inferred; start your reply with another variant to change it)"
        if (s.get("options") or {}).get("variant_inferred") else "", textio.to_posix(ctx.path("00_HUMAN_SEEDS.md"))))
    if s.get("mode") == "proposal":
        extra.append("Your idea competes as I-001 against two contrast variants: %s" % (s.get("idea_text") or
                                                                                       s.get("topic")))
    if s.get("mode") == "quick":
        extra.append("Quick mode: also give up to 5 ideas, 3 criteria (`criteria: a, b, c`) and one hard constraint "
                     "(`constraint: ...`); defaults otherwise. Novelty is NOT checked in quick mode.")
    vendors = (s.get("privacy") or {}).get("allowed_vendors") or []
    extra.append("Vendors that will see idea text: %s." % (", ".join(vendors) or "the host vendor only"))
    if s.get("autopilot") == "full-auto":
        extra.append("Full-auto remembers this privacy choice for later full-auto runs (change it with `ub config set "
                     "privacy_defaults ...`); `private` or `web: no` / `vendors: no` still apply per run.")
    notes = ["Note: %s" % n for n in s.get("notes") or []]
    return {"PLAN_LINE": "About %d model calls (%d-%d), about %.1f-%.1fM tokens, about %d-%d minutes (estimates; %s)"
                         % (plan["calls"]["expected"], plan["calls"]["min"], plan["calls"]["max"],
                            plan["tokens"][0] / 1e6, plan["tokens"][1] / 1e6, plan["minutes"][0],
                            plan["minutes"][1], plan.get("cost") or "counts against your plans"),
            "FAMILIES_LINE": _families_line(ctx), "PRIVACY_LINE": g0_privacy_line(s),
            "GATE_EXTRA": "\n".join(extra), "CARD_NOTES": "\n".join(notes)}


def g0_privacy_line(state):
    """The kickoff card's privacy settings in plain words, each with the reply key that changes it."""
    priv = state.get("privacy") or {}
    web = priv.get("web", True)
    vendors = priv.get("vendors", True)
    return ("Web search: %s | Other AI vendors see your idea text: %s | Your repo code goes to other vendors: %s"
            % ("on (`web: no` turns it off)" if web else "off (`web: yes` turns it on)",
               "yes (`vendors: no`)" if vendors else "no (`vendors: yes`)",
               "yes (`code: no`)" if priv.get("code") else "no (`code: yes`)"))


def _v_g1(ctx):
    return {"SEEDS_PATH": textio.to_posix(ctx.path("00_HUMAN_SEEDS.md"))}


def _v_g2(ctx):
    lines = []
    for n, q in enumerate(registry.frame_questions(ctx), 1):
        d = (" (default: %s)" % q["default"]) if q.get("default") else ""
        lines.append("%d. %s%s" % (n, q["text"], d))
    return {"QUESTIONS_BLOCK": "\n".join(lines) or "(no questions: reply `defaults`)"}


def _v_g2c(ctx):
    fr = ctx.read("01_FRAME.md")
    stated, assumed = [], []
    for ln in fr.split("\n"):
        s = ln.strip()
        if not s or s.startswith("#"):
            continue
        if "ASSUMED" in s:
            assumed.append(s.lstrip("-* "))
    stated = [x for x in (registry.section(fr, "Job statement"), registry.section(fr, "Problem"),
                          registry.section(fr, "Success looks like")) if x]
    crit = "; ".join("%s %g" % (k, v) for k, v in registry.criteria(ctx).items())
    axes = "; ".join("%s: %s" % (k, " | ".join(v)) for k, v in registry.axes(ctx).items()) or "none"
    return {"FRAME_SUMMARY": "FRAME: %s\nSTATED:\n%s\nASSUMED:\n%s\nCriteria (weights): %s\nAxes: %s" % (
        textio.to_posix(ctx.path("01_FRAME.md")), _bullets(stated), _bullets(assumed[:12]), crit, axes)}


def _v_g2f(ctx):
    pd = ctx.state.get("project_dir") or ""
    base = ctx.read_json("frame/footprint.json", {}) or {}
    now = registry.footprint(pd) if pd and os.path.isdir(pd) else {}
    lines = []
    for rel in sorted(set(base) | set(now)):
        if base.get(rel) != now.get(rel):
            lines.append("- %s: %s" % (rel, "new" if rel not in base else ("deleted" if rel not in now else
                                                                              "changed")))
    return {"FOOTPRINT_DIFF": "\n".join(lines) or "- (no file differences found)"}


def _v_g3(ctx):
    cl = ctx.read_json("clusters.json", {}) or {}
    by = {}
    for iid, c in cl.items():
        by.setdefault(c, []).append(iid)
    lines = []
    for c in sorted(by):
        titles = [_title(ctx, i) or i for i in sorted(by[c])[:5]]
        lines.append("- %s: %s" % (c, "; ".join(titles)))
    cells = registry.gap_cells(ctx, 20)
    land = [ln for ln in registry.context_section(ctx, "B").split("\n") if ln.strip()][:5]
    return {"CLUSTER_MAP": "\n".join(lines) or "- (no clusters)",
            "EMPTY_CELLS": "\n".join("- %s" % " | ".join(c) for c in cells) or "- none",
            "LANDSCAPE_SUMMARY": "\n".join(land) or "NOT SEARCHED"}


def _v_g4(ctx):
    data = ctx.read_json("screen/shortlist.json", {}) or {}
    short = ["%s %s (score %s): %s" % (s.get("id"), _title(ctx, s.get("id")), s.get("score"), s.get("reason"))
             for s in data.get("shortlist") or [] if isinstance(s, dict)]
    killed = ["%s %s (K1: gate failed by 2+ judges)" % (i, _title(ctx, i)) for i in data.get("killed_gate") or []]
    killed += ["%s %s (K3: below the floor; you may rescue it)" % (i, _title(ctx, i))
               for i in data.get("floor_fail") or []]
    flags = ["%s %s" % (i, _title(ctx, i)) for i in data.get("flagged_gate") or []]
    return {"SHORTLIST_SUMMARY": "Shortlist:\n" + _bullets(short), "KILLED_LIST": _bullets(killed),
            "FLAGS_LIST": _bullets(flags)}


def _v_g5(ctx):
    lines = []
    for i in ctx.state.get("k4_candidates") or []:
        v, d = registry.check_verdict(ctx, i)
        lines.append("- %s %s: VERDICT %s; DIFFERENTIATOR %s (checks/%s.md)" % (i, _title(ctx, i), v, d, i))
    return {"K4_CANDIDATES": "\n".join(lines) or "- none"}


def _v_g6(ctx):
    scores = registry.screen_scores(ctx)
    surv = registry.survivors(ctx)
    return {"SURVIVORS_LIST": "\n".join("- %s %s (screen %.2f)" % (i, _title(ctx, i), scores.get(i, 0.0))
                                        for i in surv) or "- none",
            "PROPOSED_FINALISTS": ", ".join(ctx.state.get("finalists") or []) or "none"}


def _v_g7(ctx):
    pct = registry.debiased_pct(ctx)
    fin = ctx.state.get("finalists") or []
    gut = registry.gut_picks(ctx)
    ranked = sorted(fin, key=lambda i: (-pct.get(i, 0.0), i))
    lines = ["- %s %s: %.0f%%%s" % (i, _title(ctx, i), pct.get(i, 0.0), " (your gut #1)" if gut and gut[0] == i
                                     else "") for i in ranked]
    default = ranked[:3] + ([gut[0]] if gut and gut[0] in fin and gut[0] not in ranked[:3] else [])
    lines.append("Default red-team set: %s" % ", ".join(default))
    return {"TOP_PROPOSAL": "\n".join(lines)}


def _v_g8a(ctx):
    fin = ctx.state.get("finalists") or []
    blocks = ["## %s\n%s" % (i, registry.card_text(ctx, i)) for i in fin]
    return {"FINALIST_COUNT": str(len(fin)), "CARDS_BLOCK": "\n\n".join(blocks) or "(no cards)"}


def _v_g8b(ctx):
    s = ctx.state
    gut = registry.gut_picks(ctx)
    pct = registry.debiased_pct(ctx)
    fin = s.get("finalists") or []
    ranked = sorted(fin, key=lambda i: (-pct.get(i, 0.0), i))
    standings = "\n".join("%d. %s %s %.0f%%" % (n, i, _title(ctx, i), pct.get(i, 0.0)) for n, i in enumerate(ranked,
                                                                                                          1))
    res = registry.tournament_result(ctx)
    contested = ["- %s vs %s (%s)" % (c[0], c[1], c[2] if len(c) > 2 else "the judges disagree")
                 for c in res.get("contested") or [] if isinstance(c, (list, tuple)) and len(c) >= 2]
    verdicts = registry.review_verdicts(ctx)
    vlines = []
    for i in s.get("top") or fin:
        for v in verdicts.get(i, []):
            vlines.append("- %s" % re.sub(r"\s*\((%s)(-alt)?\)" % "|".join(FAMILY_ORDER), "", v))
    synth = registry.section(ctx.read("07_REDTEAM.md"), "2") or registry.first_line(ctx.read("07_REDTEAM.md"))
    if s.get("mode") == "quick":
        synth = synth or "Quick mode: no red-team; novelty NOT checked."
    flags = ["%s %s (CROWDED, no differentiator)" % (p, _title(ctx, p)) for p in s.get("parked") or []]
    sug, rule = registry.suggestion(ctx)
    return {"GUT_PICK": ", ".join(gut) or "skipped", "STANDINGS": standings or "(no tally)",
            "CONTESTED": "\n".join(contested) or "none", "VERDICT_LINES": "\n".join(vlines) or "none",
            "SYNTHESIS_SUMMARY": synth or "(no synthesis)", "K4_FLAGS": "\n".join(flags) or "none",
            "SUGGESTION": "%s %s (%s)" % (sug, _title(ctx, sug), rule) if sug else "none",
            "BUNDLE_HINT": ', "bundle: <IDs in test order>"' if s.get("variant") == "growth" else ""}


def _v_g9(ctx):
    probe = ctx.read("09_PROBE.md")
    parts = registry.sections_by_prefix(probe, ["3", "4"]) or probe.strip()
    return {"PROBE_SUMMARY": parts or "(09_PROBE.md is missing)"}


def _v_g10(ctx):
    d = registry.drivers(ctx)
    lines = ["Quality goals (weights sum to 70; a fixed 30 goes to generic criteria):"]
    for q in d.get("quality_goals") or []:
        if isinstance(q, dict):
            lines.append("- %s %s: weight %s [%s]" % (q.get("id"), q.get("name"), q.get("weight"), q.get("source")))
    lines.append("Hard constraints:")
    for h in d.get("hard_constraints") or []:
        if isinstance(h, dict):
            lines.append("- %s %s [%s]" % (h.get("id"), h.get("text"), h.get("source")))
    hq = [q for q in d.get("qas") or [] if isinstance(q, dict) and q.get("importance") == "H"]
    if hq:
        lines.append("H-importance scenarios:")
        lines += ["- %s (%s): %s -> %s" % (q.get("id"), q.get("qg"), q.get("stimulus"), q.get("measure")) for q in hq]
    return {"DRIVERS_SUMMARY": "\n".join(lines)}


def _v_g11(ctx):
    m = ctx.read_json("10_ARCHITECTURE/matrix.json", {}) or {}
    lines = []
    for c in m.get("candidates") or []:
        if isinstance(c, dict):
            lines.append("- %s%s: score %s, rank %s (range %s), veto %s%s%s" % (
                c.get("label"), _candidate_gist(ctx, c.get("label")), c.get("score"), c.get("rank"),
                registry.fmt_range(c.get("range")), c.get("veto"),
                (" (%s)" % "; ".join(c.get("veto_reasons") or [])) if c.get("veto_reasons") else "",
                ("; judges disagree on %s" % ", ".join(c.get("disagreements"))) if c.get("disagreements") else ""))
    for x in m.get("steal") or []:
        if isinstance(x, dict):
            lines.append("  steal from %s: %s" % (x.get("from"), x.get("element")))
    lines.append("Matrix: %s" % textio.to_posix(ctx.path("10_ARCHITECTURE/tradeoff-matrix.md")))
    pm = ""
    for ln in ctx.read("10_ARCHITECTURE/premortem.md").split("\n"):
        if ln.strip().upper().startswith("TOP RISK"):
            pm = ln.strip()
    if not pm and ctx.mode == "quick":
        pm = "(quick mode: no pre-mortem)"
    return {"MATRIX_SUMMARY": "\n".join(lines), "PREMORTEM_TOP": pm or "(none)",
            "ARCH_SUGGESTION": "%s (%s)" % (m.get("leader") or "?", m.get("leader_status") or "close-call")}


def _candidate_gist(ctx, label):
    """' (<paradigm>): <first sentence of the summary>; about $a-b/month at MVP; x-y person-weeks' for a blind
    candidate (candidates/map.json -> candidates/<n>.json); '' when unknown. The author family stays hidden."""
    info = (ctx.read_json("10_ARCHITECTURE/candidates/map.json", {}) or {}).get(label) or {}
    cand = ctx.read_json("10_ARCHITECTURE/candidates/%s.json" % info["n"], None) if info.get("n") else None
    if not isinstance(cand, dict):
        return ""
    parts = []
    summary = registry.clean(cand.get("summary") or "")
    if summary:
        parts.append(re.split(r"(?<=[.!?])\s", summary, maxsplit=1)[0])
    cost = cand.get("cost_monthly_usd") if isinstance(cand.get("cost_monthly_usd"), dict) else {}
    if cost.get("mvp_low") is not None and cost.get("mvp_high") is not None:
        parts.append("about $%s-%s/month at MVP" % (cost["mvp_low"], cost["mvp_high"]))
    pw = cand.get("build_person_weeks") if isinstance(cand.get("build_person_weeks"), dict) else {}
    if pw.get("low") is not None and pw.get("high") is not None:
        parts.append("%s-%s person-weeks" % (pw["low"], pw["high"]))
    head = (" (%s)" % registry.clean(cand.get("paradigm"))) if cand.get("paradigm") else ""
    return head + ((": " + "; ".join(parts)) if parts else "") + (";" if parts else "")


def _v_g12(ctx):
    lines = []
    for n, p in enumerate(sorted(_adr_files(ctx)), 1):
        t = textio.read_text(p)
        mt = re.search(r"^# ADR-\d{4}: (.*)$", t, re.M)
        mc = re.search(r'^Chosen option: "([^"]*)"', t, re.M)
        lines.append("%d. %s - chosen: %s" % (n, mt.group(1).strip() if mt else os.path.basename(p),
                                              mc.group(1) if mc else "?"))
    return {"ADR_LIST": "\n".join(lines) or "(no ADRs)"}


def _v_g13(ctx):
    lines = []
    import glob as _g
    for p in sorted(_g.glob(ctx.path("11_PROPOSAL", "review", "rubric_*.json"))):
        if p.endswith(".meta.json"):
            continue
        try:
            data = textio.read_json(p)
        except (OSError, ValueError):
            continue
        sc = (data or {}).get("scores") or {}
        judge = os.path.basename(p)[len("rubric_"):-len(".json")]
        lines.append("Rubric (%s, 1-5): %s" % (judge, ", ".join("%s %s" % (k.replace("_", " "), v)
                                                                for k, v in sorted(sc.items()))))
    for i in registry.ranked_redteam(ctx)[:3]:
        lines.append("Red-team: %s (fails if %s)" % (i.get("claim"), i.get("fails_if")))
    lint = ctx.read_json("11_PROPOSAL/lint.json", {}) or {}
    alint = ctx.read_json("10_ARCHITECTURE/lint.json", {}) or {}
    lines.append("Lint: proposal %s, architecture %s" % (lint.get("status", "?"), alint.get("status", "?")))
    oq = ctx.read("11_PROPOSAL/open-questions.md")
    lines.append("Open questions: %d (11_PROPOSAL/open-questions.md)" % len(
        [ln for ln in oq.split("\n") if ln.startswith("| Q-")]))
    lines.append("ADRs: %d, status proposed until you approve" % len(_adr_files(ctx)))
    for u in ctx.state.get("unresolved") or []:
        lines.append("Unresolved: %s" % u)
    ch = ctx.state.get("choice") or {}
    if ch.get("arch"):
        lines.append("Architecture: candidate %s (written by %s)" % (ch["arch"], ch.get("arch_family")))
    links = [textio.to_posix(ctx.path(r)) for r in ("11_PROPOSAL/PROPOSAL.md", "11_PROPOSAL/ONE-PAGER.md",
                                                     "11_PROPOSAL/index.html", "10_ARCHITECTURE/README.md")
             if ctx.exists(r)]
    return {"PROPOSAL_SUMMARY": "\n".join(lines), "LINKS_BLOCK": " | ".join(links)}


def _v_g14(ctx):
    from . import handoff
    targets = [handoff.card_line(handoff.plan_target(ctx, key)) for key in ("architecture", "adr", "proposal")]
    options = g14_options(ctx)
    terms = ""
    if ctx.exists("CONTEXT.proposed.md") and not ctx.state.get("context_merge"):
        terms = "Proposed domain terms are waiting in CONTEXT.proposed.md: add `merge: all|some|none|defer`."
    return {"PROBE_WARNING": "" if "RESULT: PASSED" in ctx.read("09_PROBE.md") else
            "Riskiest assumption untested: 09_PROBE.md has no RESULT: PASSED.",
            "PUBLISH_TARGETS": "\n".join(targets), "HANDOFF_OPTIONS": ", ".join(
                "`%s` (%s)" % (o, HANDOFF_NAMES[o]) for o in options) + " (default: %s)" % (
                "ce" if ctx.variant in ("software", "growth") else "none"), "TERMS_BLOCK": terms}


HANDOFF_NAMES = {"ce": "Compound Engineering ce-plan", "speckit": "Spec Kit", "superpowers": "Superpowers",
                 "openspec": "OpenSpec", "none": "no seed"}


def g14_options(ctx):
    """The handoff seeds offered at G14 (the card body and 'How to answer' use this one list)."""
    pd = ctx.state.get("project_dir") or "."
    options = ["ce", "speckit"]
    if os.path.isdir(os.path.join(pd, "docs", "superpowers")) or os.path.isdir(os.path.join(pd, ".superpowers")):
        options.append("superpowers")
    if os.path.isdir(os.path.join(pd, "openspec")):
        options.append("openspec")
    options.append("none")
    return options


def _v_gb(ctx):
    from . import progress
    c = ctx.state.get("counters") or {}
    rest = progress.plan_for_state(ctx)
    try:
        from . import pipeline
        seq = pipeline.simulate(ctx, remaining_only=True)
        left = sum(int(round((i["count"][0] + i["count"][1]) / 2.0)) for i in seq)
    except Exception:
        left = rest["calls"]["expected"]
    return {"BUDGET_LINE": "Calls used: %s of %s (budget.max_calls). About %d more calls are needed to finish."
                           % (c.get("launched", 0), (ctx.state.get("budget") or {}).get("max_calls"), left)}


def _v_gx(ctx):
    line = registry.final_line(ctx.read("07_REDTEAM.md"))
    kill = registry.section(registry.frame_text(ctx), "Kill condition")
    parts = []
    if line.upper().startswith("WHOLE-EFFORT"):
        parts.append("The synthesis says: %s" % line)
    if kill:
        parts.append("The frame's kill condition for the whole effort: %s" % " ".join(kill.split()))
    return {"GX_REASON": "\n".join(parts) or "The whole effort is in question."}


_VALUES = {"G0": _v_g0, "G1": _v_g1, "G2": _v_g2, "G2c": _v_g2c, "G2f": _v_g2f, "G3": _v_g3, "G4": _v_g4,
           "G5": _v_g5, "G6": _v_g6, "G7": _v_g7, "G8a": _v_g8a, "G8b": _v_g8b, "G9": _v_g9, "G10": _v_g10,
           "G11": _v_g11, "G12": _v_g12, "G13": _v_g13, "G14": _v_g14, "GB": _v_gb, "GX": _v_gx}


# SUMMARY: the gate body composed from the gate's own values, in the order the evidence rules require (for gate
# templates that use {{SUMMARY}} instead of the individual placeholders). (label, key); label None = the value alone.
_SUMMARY_ORDER = {
    "G0": [(None, "PROVISIONAL_BANNER"), ("Topic", "TOPIC"), ("Plan", "PLAN_DESC"), ("Model families", "FAMILIES_LINE"),
           ("Privacy", "PRIVACY_LINE"), (None, "GATE_EXTRA"), (None, "CARD_NOTES")],
    "G1": [("Seeds file", "SEEDS_PATH"),
           (None, "SEEDS_HELP")],
    "G2": [(None, "QUESTIONS_BLOCK")],
    "G2c": [(None, "FRAME_SUMMARY")],
    "G2f": [("Changed since the baseline", "FOOTPRINT_DIFF")],
    "G3": [("Clusters (all of them, unranked)", "CLUSTER_MAP"), ("Empty cells", "EMPTY_CELLS"),
           ("What already exists (LANDSCAPE)", "LANDSCAPE_SUMMARY")],
    "G4": [(None, "SHORTLIST_SUMMARY"), ("Killed or failed", "KILLED_LIST"),
           ("Flagged by one judge only (you decide)", "FLAGS_LIST")],
    "G5": [("K4 candidates (CROWDED with no differentiator; a wrong verdict kills a good idea)", "K4_CANDIDATES")],
    "G6": [("Survivors", "SURVIVORS_LIST"), ("Proposed finalists", "PROPOSED_FINALISTS")],
    "G7": [("Standings (debiased) and your gut pick", "TOP_PROPOSAL")],
    "G8a": [(None, "FINALISTS_HEAD"), (None, "CARDS_BLOCK")],
    "G8b": [(None, "PROVISIONAL_BANNER"), ("Your gut pick (before any score)", "GUT_PICK"),
            ("Tournament standings (debiased)", "STANDINGS"), ("Contested pairs (your call)", "CONTESTED"),
            ("Red-team verdict lines, raw, before any summary", "VERDICT_LINES"), ("Synthesis", "SYNTHESIS_SUMMARY"),
            ("Flags (parked by prior art, not killed)", "K4_FLAGS"),
            ("Suggested by rule; you decide", "SUGGESTION")],
    "G9": [("The pre-registered test", "PROBE_SUMMARY")],
    "G10": [(None, "DRIVERS_SUMMARY")],
    "G11": [(None, "PROVISIONAL_BANNER"), ("Candidates (judged blind; families revealed after your choice)",
                                           "MATRIX_SUMMARY"),
            ("Top pre-mortem risk of the leader", "PREMORTEM_TOP"), ("Suggested", "ARCH_SUGGESTION")],
    "G12": [("ADRs (status proposed)", "ADR_LIST")],
    "G13": [(None, "PROVISIONAL_BANNER"), (None, "PROPOSAL_SUMMARY"), ("Files", "LINKS_BLOCK")],
    "G14": [(None, "PROBE_WARNING"), ("Publish copies into the repository (each needs its own yes)", "PUBLISH_TARGETS"),
            ("Handoff seed for the next tool", "HANDOFF_OPTIONS"), (None, "TERMS_BLOCK")],
    "GB": [(None, "BUDGET_LINE")],
    "GX": [(None, "GX_REASON")],
}


def compose_summary(gid, vals):
    out = []
    for label, key in _SUMMARY_ORDER.get(gid, []):
        v = str(vals.get(key) or "").strip("\n")
        if not v.strip():
            continue
        if label is None:
            out.append(v)
        elif "\n" in v:
            out.append("%s:\n%s" % (label, v))
        else:
            out.append("%s: %s" % (label, v))
    return "\n".join(out)


def gate_values(ctx, gid):
    """Every placeholder a gate template may use: the common ones, the gate's own, and the composed SUMMARY with
    TITLE, GATE and HOW_TO_REPLY (for templates that show one body block)."""
    s = ctx.state
    vals = {"RUN_NAME": s.get("run", ""), "PROVISIONAL_BANNER": provisional_banner(ctx), "TOPIC": s.get("topic", ""),
            "MODE": s.get("mode", ""), "VARIANT": s.get("variant", ""), "AUTOPILOT": s.get("autopilot", ""),
            "GATE": gid, "TITLE": TITLES.get(gid, gid), "HOW_TO_REPLY": HOW_TO_REPLY.get(gid, ""),
            "RUN_PATH": textio.to_posix(ctx.run_dir) if ctx.run_dir else "",
            "SEEDS_FILE": textio.to_posix(ctx.path("00_HUMAN_SEEDS.md")) if ctx.run_dir else "",
            "FAMILIES": _families_line(ctx), "SUGGESTION": ""}
    if gid == "G11":
        vals["SUGGESTION"] = (ctx.read_json("10_ARCHITECTURE/matrix.json", {}) or {}).get("leader") or ""
    fn = _VALUES.get(gid)
    if gid == "G14" and ctx.run_dir:
        vals["HOW_TO_REPLY"] = ("Reply `publish` (or `publish architecture`, `publish proposal`, `publish adr`) or "
                                "`no`, and a handoff: %s." % ", ".join("`%s`" % o for o in g14_options(ctx)))
    if fn:
        try:
            vals.update(fn(ctx))
        except Exception as e:  # a display value must never block a gate
            vals["_error"] = str(e)
    vals["PLAN_DESC"] = "%s mode, %s variant, %s autopilot. %s" % (s.get("mode"), s.get("variant"),
                                                                   s.get("autopilot"), vals.get("PLAN_LINE", ""))
    vals["SEEDS_HELP"] = ("Write alone, before seeing any AI idea (about 10 minutes): Problem, Primary idea "
                          "(optional), Ideas (one per line; include one 'dumb' idea and one that deletes something), "
                          "Obvious, Off-limits.")
    vals["FINALISTS_HEAD"] = "%s finalists, unscored and in neutral wording (the judges work sealed meanwhile):" % (
        vals.get("FINALIST_COUNT") or "0")
    vals["SUMMARY"] = compose_summary(gid, vals) or vals.get("_error", "")
    return vals


def display(ctx, gid, error=None):
    """The exact text for the HUMAN card (templates/gates/<G>.md filled); also written to gates/<G>.md."""
    from . import builders
    vals = gate_values(ctx, gid)
    tpl = registry.load_template(gid, "gates", raw=True)
    text = None
    if tpl is not None:
        mapping = dict(vals)
        for name in builders.placeholders_in(tpl):
            mapping.setdefault(name, "(n/a)")
        text = builders.fill_doc(tpl, mapping)
    if text is None:
        body = "\n".join("%s: %s" % (k, v) for k, v in sorted(vals.items()) if v and k not in ("RUN_NAME",))
        text = "ultimate-brainstorm - %s (%s)\n%s\n\n%s" % (TITLES.get(gid, gid), s_run(ctx), body,
                                                          HOW_TO_REPLY.get(gid, ""))
    text = text.strip("\n")
    if error:
        text = "PLEASE FIX: %s\n\n%s" % (error, text)
    try:
        ctx.write("gates/%s.md" % gid, text.rstrip() + "\n")
    except OSError:
        pass
    return text.rstrip() + "\n"


def s_run(ctx):
    return ctx.state.get("run", "")
