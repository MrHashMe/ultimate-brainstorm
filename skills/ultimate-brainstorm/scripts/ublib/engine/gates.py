"""HUMAN gates (KIT_SPEC 4.12, 6.2): policies per autopilot preset, answer templates and defaults, the deterministic
reply parser, validation, application and the display text written to gates/<GATE>.md.

apply() returns a list of effects that pipeline.apply_effects executes (reset steps, redo, stop).
"""

import bisect
import copy
import difflib
import json
import os
import re
import unicodedata

from .. import schema_lite, textio
from . import (AUTOPILOTS, FAMILY_ORDER, MODES, VARIANTS, EngineError, base_family)
from . import privacy as privacy_mod
from . import registry
from . import state as st

ID_RE = re.compile(r"\b([IEQ]-\d+)\b", re.I)  # read in upper case (_ids): 'kill i-003' names I-003

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
    "G12": "Reply `ok` to accept all, `ok, reject 3`, or `accept 1 2 4, reject 3`.",
    "G13": "Reply `approve`, `changes: <what to change>`, `switch <letter>` (another architecture) or `runner-up`.",
    "G14": "Reply `publish` (or `publish architecture`, `publish proposal`, `publish adr`) or `no`, and a handoff: "
           "`ce`, `speckit`, `superpowers`, `openspec` or `none`.",
    "GB": "Reply `raise to <number of requests>` to continue, or `stop`.",
    "GX": "Reply `reframe`, `continue` or `stop`.",
}

# ---------------------------------------------------------------- the one reader of free-text replies (4.12)
# Every gate reads a reply the same way: in clauses (split at , ; ! ? ( . line breaks, dashes and before but / except /
# because / since), each word without the punctuation around it, a clause with a negation refusing what it names (and
# so does a clause a bare refusal follows, 'B? no.', and an echoed question whose answer is no yes, 'Publish? Probably
# not.'), and one confirmation vocabulary (G0, G2c/G10, G8b, G11, G12, G13 and every yes/no field).
YES_WORDS = frozenset((
    "yes", "y", "yep", "yeah", "yup", "ok", "okay", "sure", "fine", "confirm", "confirmed", "correct", "right", "lgtm",
    "approve", "approved", "accept", "accepted", "agree", "agreed", "go", "proceed", "perfect", "good", "thanks", "thx",
    "please", "exactly", "accurate", "absolutely", "definitely", "certainly", "indeed", "ack", "acked", "alright",
    "aye"))
# each reads as the one word `ok` ('thank you' as `thanks`), so 'Go ahead!' or "Sounds good, let's go" is a yes
YES_PHRASES = sorted((tuple(p.split()) for p in (
    "go ahead", "yes please", "sounds good", "sounds great", "looks good", "looks great", "all good", "let's go",
    "lets go", "let us go", "let's start", "lets start", "let us start", "go for it", "sure thing", "that's right",
    "that is right", "fine by me", "good to go", "works for me", "thank you", "that's correct", "that is correct",
    "i agree", "we agree", "looks right", "sounds right", "spot on", "that works", "as is", "all correct", "of course",
    "sign off", "signed off", "all set", "we're good", "we are good", "let's do it", "lets do it", "move on",
    "move forward", "move ahead",
    "carry on", "please do", "i think so", "why not", "checks out", "sign it off", "lock it in", "rubber stamp it",
    "rubber-stamp it", "all right", "make it so", "that's what i meant", "that is what i meant", "that's what i want")),
    key=len, reverse=True)
_PHRASE_HEADS = frozenset(p[0] for p in YES_PHRASES)
# texting forms and the plain yes / thanks words of other languages read as the word they stand for ('k', 'ya',
# 'pls', 'thats right', 'tayeb', 'oui', 'shukran'); yalla and inshallah are courtesy words like please, and khalas
# ('enough') is left out: it may mean done, stop or go
_ALIAS = {"ty": "thanks", "tysm": "thanks", "np": "ok", "yea": "yes", "rn": "now", "tbh": "honestly", "u": "you",
          "ur": "your", "im": "i'm", "didnt": "didn't",
          "continuing": "continue", "k": "ok", "kk": "ok", "ya": "yes", "yah": "yes", "pls": "please", "plz": "please",
          "thats": "that's",
          "bc": "because", "cuz": "because", "yalla": "please", "inshallah": "please", "khalas": None,
          "kindly": "please", "noted": "thanks", "ta": "thanks", "cheers": "thanks", "lovely": "good", "si": "yes",
          "s\u00ed": "yes", "oui": "yes", "haan": "yes", "hai": "yes", "aywa": "yes", "tayeb": "ok", "tayyib": "ok",
          "sawa": "ok", "vale": "ok", "d'accord": "ok", "achha": "ok", "theek": "fine", "perfecto": "perfect",
          "shukran": "thanks", "merci": "thanks", "gracias": "thanks", "shukriya": "thanks", "danke": "thanks",
          "non": "no", "nein": "no", "nee": "no", "nahi": "no", "nahin": "no", "nej": "no", "nei": "no", "niet": "no",
          "nicht": "not"}
NO_WORDS = frozenset(("no", "n", "nope", "nah", "false", "0"))
# deferring or calling off refuses too ('publish later', 'hold off', 'can wait', 'cancel publishing'); such a word
# defers only where it governs: first in its clause, last in it, or before off / on ('the wait list' defers nothing)
_HOLD = frozenset(("stop", "wait", "hold", "later", "cancel", "defer", "postpone", "pause"))
# a clause with one of these words, or a word ending in n't, is negated: what it names is refused, never chosen
NEG_WORDS = frozenset((
    "not", "no", "nope", "nah", "never", "nothing", "none", "neither", "nor", "avoid", "drop", "skip", "reject",
    "rejected", "against", "without", "too", "except", "cannot", "dont", "wont", "cant", "hardly", "nowhere",
    "false")) | _HOLD
_NOT = frozenset(("not", "never", "don't", "dont"))
# a clause made only of these, one of them a refusal, is a bare refusal ('no', 'Not really.', 'nope', 'Sadly not',
# 'not yet', 'No thanks', 'hold off', 'stop', 'Probably not.', "I'd rather not.", 'Not even close'): it refuses what
# the clause before it names
_REFUSALS = frozenset(("no", "n", "nope", "nah", "hardly", "nowhere", "false")) | _NOT | _HOLD
_BARE = _REFUSALS | frozenset((
    "way", "really", "sadly", "unfortunately", "at", "all", "yet", "now", "thanks", "please", "sorry", "afraid", "i",
    "i'm", "think", "so", "of", "course", "quite", "definitely", "certainly", "absolutely", "for", "on", "off", "it",
    "that", "this", "one", "do", "time", "probably", "maybe", "perhaps", "actually", "well", "hmm", "hm", "um", "uh",
    "oh", "ah", "honestly", "frankly", "let's", "lets", "today", "rather", "better", "sure", "need", "needed", "i'd",
    "say", "even", "close", "near", "thank", "you", "chance", "but", "though", "ok"))
# a clause of these alone says nothing ('Hmm,', 'Actually,'): the reader looks past it for the answer or the refusal
_COURTESY = frozenset(("please", "thanks", "thx"))  # words that confirm nothing on their own ('no, thanks')
_INTERJ = frozenset(("actually", "well", "hmm", "hm", "um", "uh", "oh", "ah", "honestly", "frankly", "sadly",
                     "unfortunately", "so"))
# words that may stand before a deferral that leads its clause ("let's wait", 'we should hold off', 'but stop')
_LEAD = frozenset(("please", "let's", "lets", "let", "us", "i", "i'd", "i'll", "we", "we'd", "we'll", "should", "can",
                   "could", "just", "but", "and", "so", "then", "ok", "maybe", "perhaps", "better")) | _INTERJ
# apostrophes read as ' (the acute accent and the backtick of many keyboard layouts too); a thumbs-down or a cross
# mark is a `no`
_QUOTES = {0x2018: "'", 0x2019: "'", 0x02bc: "'", 0x201b: "'", 0x00b4: "'", 0x0060: "'", 0x2032: "'", 0xff07: "'",
           0x274c: " no ", 0x1f44e: " no "}
_WORD = re.compile(r"[^\W_]+(?:['-][^\W_]+)*")  # a dash, an ellipsis or an emoji is no word; don't, full-auto are
_CLAUSE_END = re.compile(r"[,;!?(\n\u2026]|\.(?!\S)|\s[-\u2013\u2014]+(?=\s)|\u2014|\s(?=(?:but|except|although|"
                         r"though|however|because|since|bc|cuz)\b)", re.I)
_BULLET = re.compile(r"^\s*(?:[-*\u2022]|\d+[.)])(?=\s)")  # a list item stays a seed idea ('- deep'; '**go**' is none)
KEYWORDS = set(MODES) | set(VARIANTS) | set(AUTOPILOTS) | {"private", "privacy", "with-ce-ideate", "start", "continue"}
# beside a setting: 'go ahead with standard please', 'keep it private', 'switch to deep mode'
_G0_FILLER = frozenset(("with", "and", "in", "mode", "autopilot", "variant", "keep", "it", "make", "use", "switch",
                        "to", "set", "change", "the"))
# anywhere in a G0 line: chat that is no idea ('Looks good to me - go ahead, thanks!', "That's all I have.", 'Hi!')
_G0_CHAT = frozenset(("hi", "hello", "hey", "so", "much", "to", "me", "just", "anyway", "sorry", "then", "now",
                      "that's", "it", "all", "i", "have", "yet", "from", "cheers", "my", "our", "side", "end", "for",
                      "the", "as", "shown", "above", "below", "settings", "with", "you", "ideas", "are", "follows",
                      "plan", "looks", "brainstorming", "morning", "regards", "best", "team", "moment", "at", "this",
                      "time", "needful", "do", "note", "happy", "of", "that", "whenever", "ready", "you're", "hai",
                      "karo"))


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

def vendor_set(ctx):
    """The vendors the G0 card lists as seeing idea text when other vendors are allowed: the host's and those of the
    enabled families (full-auto saves it beside the privacy defaults)."""
    fams = [f for f, info in (ctx.state.get("families") or {}).items() if (info or {}).get("status") == "ok"]
    return privacy_mod.allowed_vendors(ctx.host_family, fams, True)


def new_vendors(ctx):
    """The vendors this run would send idea text to that the saved full-auto privacy choice never listed; None when
    that choice needs asking as a whole (none saved, or saved before the vendor set was kept). `vendors: no` keeps
    the idea text with the host's vendor, so no enabled family widens it."""
    d = st.config_get("privacy_defaults")
    if not isinstance(d, dict) or (d.get("vendors") is not False and not isinstance(d.get("vendor_set"), list)) or \
            any(k in d and not isinstance(d[k], bool) for k in ("web", "vendors", "code")):
        return None  # a value that is no boolean ('no' set as a string) is no saved answer
    return [] if d.get("vendors") is False else [v for v in vendor_set(ctx) if v not in d["vendor_set"]]


def policy(ctx, gid):
    """'ask', 'auto' (default answer applied, by: auto) or 'skip' for a gate reached in the pipeline."""
    ap = ctx.autopilot
    mode = ctx.mode
    if gid == "G0":
        if ap != "full-auto":
            return "ask"
        opts = ctx.state.get("options") or {}
        if opts.get("privacy_unread"):
            return "ask"  # a `vendors: no` typed where the kickoff text does not read it as a setting (never lost)
        return "auto" if opts.get("explicit_privacy") or new_vendors(ctx) == [] else "ask"  # a new vendor asks again
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
            return "skip"  # 6.1: optional in quick and proposal mode (their guided reply counts are 4-5 and 5-6)
        return "ask"
    if gid == "G8b":
        return "auto" if ap == "full-auto" else "ask"
    if gid == "G10":
        if ap == "hands-on" or (mode == "deep" and ap == "guided"):
            return "ask"
        return "auto"
    if gid == "G11":
        if mode == "quick" or ap == "full-auto":
            # a vetoed or confounded leader is not taken silently while a person is there to decide
            return "ask" if ap != "full-auto" and g11_contested(ctx) else "auto"
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
    return [i.upper() for i in ID_RE.findall(text or "")]


def _tokens(text):
    """The words of `text` as (lower case, as written) pairs, without the punctuation around them; each confirmation
    phrase is the one word `ok` ('thank you': `thanks`)."""
    raw = [w for w in _WORD.findall((text or "").translate(_QUOTES)) if _ALIAS.get(w.lower(), 1)]
    low = [_ALIAS.get(w.lower()) or w.lower() for w in raw]
    out, i = [], 0
    while i < len(raw):
        p = next((p for p in YES_PHRASES if tuple(low[i:i + len(p)]) == p), None) if low[i] in _PHRASE_HEADS else None
        if p and p == ("all", "right") and low[i + 2:i + 3] in (["now"], ["away"]):
            p = None  # 'publish all right now'
        if p:
            word = "thanks" if p[0] == "thank" else "ok"
            out.append((word, word))
            i += len(p)
        else:
            out.append((low[i], raw[i]))
            i += 1
    return out


def _words(text):
    return [w for w, _ in _tokens(text)]


_LEAD_NO = re.compile(r"(\s*(?:no|nah|nope)\b)(?=\s+[^\W_])", re.I)


def _clauses(text):
    """(clause, asks) for each clause of a reply that has a word in it, as written (apostrophes made plain); `asks`
    when a question mark ends it ('Publish?'). The no that answers a question is a clause of its own ('stop? no
    continue')."""
    t = (text or "").translate(_QUOTES)
    out, at = [], 0
    for m in list(_CLAUSE_END.finditer(t)) + [None]:
        c = t[at:m.start()] if m else t[at:]
        no = _LEAD_NO.match(c) if out and out[-1][1] else None
        if no:
            out.append((no.group(1), False))
            c = c[no.end():]
        if _WORD.search(c):
            out.append((c, bool(m) and "?" in m.group(0)))
        at = m.end() if m else at
    return out


def _unrefused(words):
    """Two negations cancel out when the negation governs the hold word right after it: "don't stop", "can't
    wait" (not 'wait not yet', 'wait, not the proposal')."""
    w = list(words)
    return any((x in _NOT or x.endswith("n't")) and bool(set(w[i + 1:i + 3]) & _HOLD) for i, x in enumerate(w))


def _negated(words, is_key=None):
    """A negation word or a word ending in n't, and not two that cancel out; a keyword of the gate (`stop` at GB and
    GX, `skip` at G1) is never one. Later, postpone and defer defer anywhere ("I'll publish later myself"); the other
    deferral words count where they govern their clause: first (after _LEAD words: "let's wait"), last ('publish
    later please') or before off / on ('hold off'); 'can hold more traffic', 'the wait list' and 'continue and wait
    for the probe' defer nothing."""
    key = is_key or (lambda x: False)
    w = list(words)
    if _unrefused([x for x in w if not key(x)]):
        return False
    n = len(w)
    while n and w[n - 1] in ("please", "thanks", "thx", "ok"):
        n -= 1
    lead = True
    for i, x in enumerate(w):
        if key(x):
            lead = False  # 'continue and wait for the probe': the wait does not lead
        elif x in _HOLD:
            if lead or i == n - 1 or w[i + 1:i + 2] in (["off"], ["on"]) or x in ("later", "postpone", "defer"):
                return True
        elif x in NEG_WORDS or x.endswith("n't"):
            return True
        lead = lead and x in _LEAD
    return False


def _bare_no(words):
    # 'not this time' refuses; 'no time' is a reason ('skip, no time')
    return any(w in _REFUSALS for w in words) and all(w in _BARE for w in words) and not _unrefused(words) and \
        ("time" not in words or "this" in words)


# a negation that governs the keyword after it ('restore not keep': it refuses keep, not restore; 'passed without
# issues' refuses nothing), unless one of _SCOPE_VERB stands before it ('the proposal is not final' still refuses it)
_SCOPE_NOT = frozenset(("not", "no", "never", "dont", "don't", "nah", "nope", "without"))
_SCOPE_VERB = frozenset(("is", "are", "was", "were", "be", "been", "am", "it's", "that's", "its", "do", "does", "did",
                         "will", "would", "should", "can", "could"))
# a question that asks for the action is a request, not an echo ('Can you publish the architecture? Thanks')
_REQUEST = re.compile(r"\s*(?:(?:or|and|but|so)\s+)?(?:please\b|(?:can|could|would|will)\s+(?:you|we|u)\b)", re.I)


def _scoped(c, key):
    """The parts of a clause without a colon that each negation governs: a negation after a keyword starts a part,
    and so does a keyword after a negated keyword or after `no <word>` ('restore not keep', 'passed no issues', 'dont
    stop continue', 'no ideas skip')."""
    if ":" in c:
        return [c]
    cuts, has, neg, negkey, x, last, nt = [0], False, False, False, "", "", False
    for m in _WORD.finditer(c):
        last2, last, x = last, x, m.group(0).lower()
        nt = nt or x.endswith("n't") or x in ("not", "never")
        if x in _SCOPE_NOT:
            if has and last not in _SCOPE_VERB:
                cuts.append(m.start())
                has, negkey = False, False
            neg = True
        elif key(x):
            # 'no one missed'; 'no to C' refuses C ("I can't say no to A" does not)
            if negkey or last2 == "no" and not key(last) and last not in _SCOPE_NOT and last not in (
                    "one", "need", "needed") and (  # 'no need restore' refuses the restore
                    last != "to" or nt):
                cuts.append(m.start())
                neg, negkey = False, False
            negkey, has = neg, True
    return [c[a:b] for a, b in zip(cuts, cuts[1:] + [len(c)])]


def _read(text, is_key=None, names=None, scope=None):
    """The clauses of a reply as [clause, words, negated, refused]. A clause is `refused` when a bare refusal refuses
    it or when it is an echoed question whose answer is no yes:
    - a bare refusal ('no', 'Probably not.', "I'd rather not.") refuses the nearest clause before it, looking past
      clauses of interjections alone ('Publish? Hmm, no.') and, with `names`, past clauses that name nothing the gate
      reads ('Passed? Close, but no.');
    - a question ('B?', 'Publish?') is refused when the next clause that is not interjections alone is negated or has
      no yes word in it ('Passed? Not sure.', "passed? we didn't hit the target", 'Passed? 8 of 10'), unless that
      answer names something of its own ('Publish? Just the architecture.') or is courtesy alone ('Publish? Please.').
      A question led by please or can / could / would / will you / we asks for the action and is no echo.
    `names(clause, words)` says whether a clause names what the gate reads (a keyword, a letter, an ID, an ADR
    number); with is_key (the keywords of G1, G2f, G9, GB, GX) it is any keyword. With is_key, a clause that is only
    keywords is no bare refusal, and a clause whose part before a colon is keywords alone reads its note apart without
    the keywords in it, so a negation in the note refuses nothing ('missed: we did not reach 10', 'stop: too
    expensive', 'missed: only 3 of 10 passed'); a note that is a bare refusal refuses the keyword ('passed: no').
    `scope(word)` (is_key by default) splits a clause into the parts its negations govern (_scoped)."""
    key = is_key or (lambda w: False)
    scope = scope or is_key
    if names is None and is_key:
        names = lambda c, w: any(key(x) for x in w)  # noqa: E731
    rows, groups = [], []  # a group: [first row, rows, kind (said / interj / bare), asks, names something]
    target = None  # the nearest said group a bare refusal refuses (kept as we go: linear on 'no, no, no, ...')
    for c, asks in ((c, a) for c0, a0 in _clauses(text) for c, a in _parts(c0, a0, scope)):
        w = _words(c)
        named = bool(names and names(c, w))
        if not any(key(x) for x in w) and _bare_no(w):
            if target is not None:
                for r in rows[target[0]:target[0] + target[1]]:
                    r[3] = True
            groups.append([len(rows), 1, "bare", asks, named])
            rows.append([c, w, True, False])
            continue
        kind = "interj" if all(x in _INTERJ for x in w) else "said"
        m = re.match(r"([^:]*):(.*)$", c, re.S) if is_key else None
        head = _words(m.group(1)) if m else []
        if m and head and all(key(x) for x in head) and _WORD.search(m.group(2)):
            note = [x for x in _words(m.group(2)) if not key(x)]
            bare = _bare_no(note)
            groups.append([len(rows), 2, kind, asks, named])
            rows += [[m.group(1), head, _negated(head, is_key), bare],
                     [m.group(2), note, bare or _negated(note, is_key), False]]
        else:
            groups.append([len(rows), 1, kind, asks, named])
            rows.append([c, w, _negated(w, is_key), False])
        if kind == "said" and (named or not names):
            target = groups[-1]
    answer, refuses = None, False  # the next group that is not interjections alone, and whether it refuses a question
    for g in reversed(groups):
        if g[3] and answer is not None and not (names and answer[4]) and refuses:
            for r in rows[g[0]:g[0] + g[1]]:
                r[3] = True
        if g[2] != "interj":
            said = [x for r in rows[g[0]:g[0] + g[1]] for x in r[1]]
            answer, refuses = g, any(r[2] for r in rows[g[0]:g[0] + g[1]]) or not any(
                x in YES_WORDS and x not in _COURTESY for x in said) and not all(
                x in _COURTESY for x in said)
    return rows


def _parts(c, asks, scope):
    """(part, asks) for the parts of a clause (_scoped); the last one asks when the clause does, unless it is a
    request (_REQUEST)."""
    parts = _scoped(c, scope) if scope else [c]
    asks = asks and not _REQUEST.match(c)
    return [(p, asks and i == len(parts) - 1) for i, p in enumerate(parts) if _WORD.search(p)]


def _is_yes(words):
    """Every word is a confirmation: 'Yes.', 'LGTM', 'OK - go ahead', 'Looks good, thanks!'."""
    return bool(words) and all(w in YES_WORDS for w in words)


# G2c/G10/G13: words that neither confirm nor say what to change ('I approve it as is', 'Great work'), words about
# whether anything changes ('no changes needed', 'nothing to fix') and hedges ('maybe', 'not sure')
_SAYS_NOTHING = frozenset((
    "it", "its", "it's", "all", "everything", "the", "this", "that", "that's", "these", "both", "is", "are", "as",
    "as-is", "to", "me", "i", "i'm", "we", "you", "and", "but", "so", "far", "very", "much", "really", "just", "looks",
    "look", "seems", "sounds", "now", "yet", "proposal", "architecture", "drivers", "frame", "keep", "have", "has",
    "for", "one", "with", "happy", "glad", "satisfied", "great", "nice", "excellent", "awesome", "amazing",
    "brilliant", "wonderful", "fantastic", "love", "like", "well", "done", "work", "job", "ship", "cool", "solid",
    "neat", "on", "off", "can", "way", "continue", "next", "a", "an", "leave", "whatever", "see", "wrong", "missing",
    "thing", "new", "here", "from", "find", "bad", "unhappy", "better", "worse", "could", "couldn't", "be", "said",
    "says", "got", "same", "above", "stated", "in", "order", "reviewed", "found", "approval", "summary", "whatsoever"))
# asking for a change ('Please fix the proposal', 'add more'), unless negated ('no changes needed')
_CHANGE_ASKS = frozenset(("change", "changes", "changed", "changing", "edit", "edits", "fix", "fixes", "correction",
                          "corrections", "add", "needed", "required", "need", "needs", "adjustment", "adjustments",
                          "revision", "revisions", "amendment", "amendments", "modification", "modifications", "tweak",
                          "tweaks", "alteration", "alterations", "update", "updates", "rework", "redo", "rewrite"))
# whether anything changes: with a negation, nothing does ('no notes', 'no issues', 'nothing to change')
_CHANGE = _CHANGE_ASKS | frozenset((
    "further", "anything", "any", "nothing", "none", "more", "else", "issue", "issues", "objection", "objections",
    "note", "notes", "comment", "comments", "problems", "concern", "concerns", "complaint", "complaints", "fault",
    "faults", "quibble", "quibbles", "gripe", "gripes", "problem"))
_HEDGES = frozenset(("unsure", "maybe", "perhaps", "idk", "dunno", "hmm", "hm", "know", "idea"))
# 'not sure', 'not 100% sure', 'not entirely sure'
_NOT_SURE = r"not\s+(?:\d+\s*%\s+|(?:entirely|completely|totally|fully|quite|so|too|very|really|that)\s+)?sure"
_PRAISE = frozenset(("great", "nice", "excellent", "awesome", "amazing", "brilliant", "wonderful", "fantastic", "happy",
                     "glad", "satisfied", "solid", "cool", "neat", "nailed", "bang", "spot", "keeper", "kiss",
                     "chef's", "signed", "sealed", "delivered", "happier", "killer", "superb", "stellar", "flawless",
                     "impressive", "lovely", "beautiful"))
_SAID = YES_WORDS | NEG_WORDS | _BARE | _SAYS_NOTHING | _CHANGE | _HEDGES | _PRAISE


def _change_kind(words, neg, refused):
    """How a G2c/G10/G13 clause reads: 'content' (something to change: a word outside the vocabularies above, or an
    unnegated change request, 'Please fix the proposal'), 'mixed' (a confirmation or praise beside words outside the
    vocabularies: 'Quality goals are fine', 'approve and publish'), 'yes' (a confirmation, or nothing to change: 'no
    changes needed', 'No notes'), 'no' (a refusal, a deferral or a hedge: 'no', 'stop', 'not yet', "don't approve",
    'not sure', or any clause a bare refusal or an unanswered echo refuses) or 'none' (praise or filler alone: 'Great
    work')."""
    if refused:
        return "no"
    if words[:1] and words[0] in NO_WORDS and any(x not in _COURTESY for x in words[1:]) and all(
            x in YES_WORDS for x in words[1:]):
        return "yes"  # 'nope, all good': nothing to change
    yes = any(x in YES_WORDS and x not in _COURTESY or x in _PRAISE for x in words)
    if any(x not in _SAID and not x.endswith("n't") for x in words):
        return "mixed" if yes and not neg else "content"
    if not neg and any(x in _CHANGE_ASKS for x in words):
        return "mixed" if yes else "content"
    if neg and any(x in _CHANGE for x in words) and not any(x in _HOLD for x in words):
        return "yes"
    if neg or any(x in _HEDGES for x in words):
        return "no"
    return "yes" if any(x in YES_WORDS for x in words) else "none"


# G2c/G10/G13: a clause that puts the decision off ('Not yet, I want to read them again', 'Hold on', 'let me check',
# 'still need to read the rest', 'corrections to follow', "I'll send corrections later")
_DEFER = re.compile(r"(?:\b(?:i|we|he|she|they)\s+|\bbut\s+)(?:haven't|have\s+not|hasn't|has\s+not|didn't|did\s+not)"
                    r"\s+(?:(?:\w+\s+){0,2}(?:read|review|check|look)\w*|finish\w*\W*$)|\bno\s+decision\b|\bnothing\s+"
                    r"(?:was\s+|is\s+)?decided\b|\b(?:asked|wants?)\s+(?:us\s+|me\s+|you\s+)?to\s+hold\b|"
                    r"\bto\s+follow\s+after\b|\b(?:i|we|he|she|they|user|client|team|boss|manager)(?:'ll|\s+will)\s+"
                    r"(?:\w+\s+){0,3}(?:send|change|want|review|revisit|get\s+back|come\s+back)\b[^.;!?\n]{0,120}?"
                    r"\b(?:after\s+lunch|later|next\s+(?:week|sprint|month)|tomorrow|tonight)\b|"
                    r"\bnot\s+(?:\w+\s+)?yet\b|n't\s+(?:\w+\s+){1,3}yet\b|\blet\s+me\b|\bthink\s+about\b|\bstill\s+(?:"
                    r"(?:need|have|want|got)\s+to\s+)?(?:review|read|check|go\s+through)\w*|\b(?:need|have|got)\s+to\s+"
                    r"(?:read|review|go\s+through)\w*\s+(?:\w+\s+){0,3}(?:first|later)\b|^\W*(?:(?:please|just|ok|but|"
                    r"so|and)\W+)?(?:wait|hold|pause|later|postpone|defer)\b|\b(?:later|to\s+follow)\b(?:\s+\w+)?\W*$|"
                    r"(?:\bi|\bwe|')(?:'ll|\s+will)\s+[^.;!?\n]{0,200}\b(?:tomorrow|tonight)\W*$",
                    re.I)
# an edit request (2): a clause with content and one of these words, an imperative ('shorten the exec summary',
# 'Mention the nurses', also after a label: 'Executive summary: mention the pilot budget'; _imperative) or a clause
# led by but / except / however right after a confirmation ('yes but the users are nurses'; not 'Security is
# overstated, but it is tagged, so leave it'); a statement that corrects (1): a negation ('Security is not a driver
# here'; not 'fine too' or 'Although I never said ...'), a number ('value 40 feasibility 15'), a > ('security > speed')
# or content right after a refusal ('No, the users are nurses.'). Any other statement ('I read it all', 'B looks
# cheaper', 'my boss will read it tomorrow', _REMARK) asks again.
_EDITS = _CHANGE_ASKS | frozenset(("remove", "replace", "delete", "rename", "update", "should", "must", "instead",
                                   "rather", "make", "set", "move", "use", "drop", "prepone"))
# words that call something wrong: a statement that corrects (0.5), so a confirmation beside it confirms ('fine, the
# error budget is right')
_WRONG = frozenset(("wrong", "missing", "incorrect", "inaccurate", "outdated", "typo", "error", "mistake", "shorter",
                    "longer", "lower", "higher", "bigger", "smaller", "fewer"))
_REMARK = re.compile(r"^\W*(?:(?:and\s+)?(?:from\s+now\s+on|in\s+(?:the\s+)?future|next\s+time)\b|(?:wow|interesting|"
                     r"hmm|long)\b\W*(?:\w+\W*){0,2}$|(?:i|we|they|my\s+\w+|our\s+\w+|the\s+"
                     r"(?:team|board|boss|client|manager|users?)|(?-i:[A-F]))(?:'ll|'d)?\s+(?:(?:will|would|could|"
                     r"might|have|just|already|also)\s+)*(?:read|show|check|review|skim|share|like|love|look|seem|"
                     r"work)\w*\b)", re.I)
_EDIT_VERBS = frozenset(("add", "remove", "replace", "delete", "rename", "update", "change", "fix", "edit", "make",
                         "set", "move", "use", "drop", "prepone"))
_IMP_LEAD = frozenset(("please", "also", "and", "then", "just", "can", "could", "would", "you", "do", "so", "pls"))
_IMP_OBJECT = frozenset(("the", "a", "an", "this", "that", "these", "those", "it", "them", "all", "every", "each",
                         "some", "more", "less", "its", "our", "my", "their", "any", "one"))
_APPROVALS = frozenset(("sign", "lock", "wrap", "rubber-stamp", "stamp", "seal", "finalize", "finalise", "greenlight",
                        "green-light", "okay", "bless", "publish", "ship", "launch", "release", "deploy", "approve",
                        "go", "proceed", "continue",
                        "start", "run", "keep", "leave", "accept", "love", "like", "because", "since", "as", "if",
                        "when", "while", "although", "though", "but", "except", "however", "or", "than", "that",
                        "which", "who", "where", "why", "what", "how", "whether", "unless", "until", "after", "before",
                        "once", "for", "with", "without", "about", "from", "into", "of", "on", "in", "at", "by", "to"))
# a statement that corrects in these words ('Security is overstated', 'The ASSUMED bit about pay is off', 'latency
# matters more than cost')
_CORRECTS = re.compile(r"\b(?:(?:over|under)(?:stated|estimated|blown|rated)|exaggerated|inflated|is\s+off|(?:more|"
                       r"less|higher|lower|better|worse)\s+than(?!\s+(?:me|us|myself|(?:i|we)\s+(?:do|am|are|can|could|"
                       r"would|will)\b)))\b|^\W*[-+]\s", re.I | re.M)
# a clause that asks for no change ('please don't touch the weights', 'keep them') and one that sets a condition ('if
# you like frames from 2005')
_KEEP_ASK = re.compile(r"^\W*(?:(?:and|but|just|please)\s+)*(?:don't|do\s+not|never)\s+(?:touch|change|alter|modify|"
                       r"edit)\b|^\W*(?:keep|leave)\s+(?:them|it|those|these|the\s+\w+)(?:\s+(?:as\s+(?:they|it)\s+"
                       r"(?:are|is)|as\s+is|alone|unchanged|untouched))?\W*$", re.I)
# a note to someone else ('@sam should double check', 'ask Sam about the HIPAA bit', 'Maria needs to review this')
_COLLEAGUE = re.compile(r"(?<![\w.])@\w|(?:^|[.,;!?]\s*|\b(?i:but|and|also|please|pls|then)\s+)(?i:ask)\s+"
                        r"[A-Z][a-z]\w*\b|(?<=[a-z,;] )[A-Z][a-z]+\s+(?i:should|needs?\s+to|"
                        r"has\s+to|must|will|can|could)\s+(?i:(?:double[\s-]?)?check|look|review|read|answer|verify|"
                        r"weigh\s+in|sign\s+off)\b")
_ELSEWHERE = re.compile(r"\b(?:changes?|corrections?|edits?|points?|comments?|feedback|notes?|ones?|things?|items?)"
                        r"\s+(?:that\s+)?(?:(?:we|i|you)\s+)?(?:discussed|mentioned|agreed|talked\s+about|shared|sent|"
                        r"raised|noted|went\s+(?:over|through)|covered)\b|\b(?:like|as|"
                        r"what)\s+(?:we|i|you|he|she|they)\s+(?:discussed|agreed|said|decided|mentioned)\b|\bsame\s+"
                        r"\w+\s+as\s+(?:last\s+time|before)\b|\bas\s+(?:discussed|agreed|mentioned)\b", re.I)
# a reply that only says there are changes ('needs changes', 'I want some changes', 'the proposal needs work')
_VAGUE_NOUN = frozenset(("changes", "edits", "corrections", "fixes", "tweaks", "work", "rework"))
_VAGUE = _VAGUE_NOUN | frozenset(("i", "we", "you", "think", "know", "want", "need", "needs", "needed", "it", "this",
                                  "that", "the", "proposal", "frame", "drivers", "some", "a", "few", "minor", "small",
                                  "more", "are", "is", "still", "required", "necessary", "please", "do", "does", "to",
                                  "be", "make", "made", "has", "have", "got", "there"))
# a pointer instead of what to change ('Change that one', 'Remove both of them', 'She said change it', 'He wants
# changes')
_POINTER = frozenset(("it", "them", "that", "this", "those", "these", "one", "ones", "both", "of", "he", "she", "they",
                      "said", "says", "wants", "want"))
_IF_LEAD = re.compile(r"^\W*(?:if|unless|provided|assuming)\b", re.I)
# a labelled aside ('Background: we run 3 wards', 'FYI ...'): it corrects only when nothing beside it confirms
_ASIDE = re.compile(r"\W*(?:background|fyi|context|for\s+(?:context|info\w*)|btw|by\s+the\s+way|ps|side\s+note)\b",
                    re.I)
_QUOTED = re.compile("\"[^\"\\n]*\"|\u201c[^\u201d\\n]*\u201d|(?<!\\w)'[^'\\n]*'(?!\\w)")
_ONE_WORD = "Your reply is one word the kit does not know: reply `ok`, or write your corrections."
# a clause that says nothing changes ('Remove nothing', 'None of that changes the drivers', 'none of that is a driver
# change', 'no errors'): beside it nothing is a correction
_NO_CHANGE = re.compile(r"\b(?:(?:remove|change|add|delete|fix|edit|correct)\w*\s+nothing|nothing\s+to\s+(?:remove|"
                        r"change|add|delete|fix|edit|correct)|none\s+of\s+(?:that|this|"
                        r"these|those|it|them)\s+(?:\w+\s+){0,3}?(?:changes?|affects?|matters?)|nothing\s+(?:here\s+)?"
                        r"(?:changes|is\s+(?:a\s+)?(?:\w+\s+)?change))\b|^\W*(?:and\s+)?(?:no|zero)\s+(?:(?:real|major|"
                        r"obvious|other)\s+)?(?:errors?|mistakes?|typos?|issues?|problems?)\W*$", re.I)


def _imperative(w, digits=True):
    """A clause that reads as an order to edit: a verb the vocabularies do not know, then an object ('shorten the exec
    summary', 'Please mention the nurses', 'Do mention it'); not 'Publish it' or 'Users are nurses'."""
    w = list(w)
    while w and w[0] in _IMP_LEAD:
        w.pop(0)
    return len(w) > 1 and w[0] not in _SAID and w[0] not in _APPROVALS and not ID_RE.fullmatch(w[0]) and \
        not w[0][:1].isdigit() and (w[1] in _IMP_OBJECT or digits and w[1][:1].isdigit())


def _split_scoped(t):
    """G13: each clause split where a negation governs approve / switch / runner-up ('approve not switch')."""
    key = lambda x: x in ("approve", "approved", "switch", "runner-up")  # noqa: E731
    out, at = [], 0
    for m in list(_CLAUSE_END.finditer(t)) + [None]:
        out.append(",".join(_scoped(t[at:m.start()] if m else t[at:], key)) + (m.group(0) if m else ""))
        at = m.end() if m else at
    return "".join(out)


def _review(text, gid=None):
    """The clauses of a G2c/G10/G13 reply as (clause, words, negated, kind (_change_kind; 'refused' for a clause a
    bare refusal or an unanswered echo refuses), edit), or why the reply is asked again. Quoted text is content
    ('Replace "on-prem" with "cloud is ok"'), unless the quote is the whole reply. The bare refusal that answers a
    refused echo, or that leads a confirmation, says nothing more ('Switch to B? No, approve.', 'No, all good'). A
    reply that defers and says more ('Not yet, I want to read them again', 'let me check'), a clause with content that
    asks ('Is the off-limits list mine to fill in?') and an if ... otherwise are asked again, and so is a reply that
    points to changes it does not write ('the changes discussed in the meeting'). A note in brackets after a
    confirmation is no change ('ok. (weights sum to 100, checked)'), unless it asks for an edit, and so is a labelled
    aside beside one ('ok. Background: we run 3 wards')."""
    t = text.translate(_QUOTES).strip()
    t = t[1:-1] if _QUOTED.fullmatch(t) else _QUOTED.sub(" quoted ", t)
    t = re.sub(r"\b(?:from|on)\s+(?:my|our)\s+(?:side|end|part)\b|\bfrom\s+(?:him|her|them|the\s+(?:user|client|team|"
               r"boss|manager)|(?-i:[A-Z][a-z]+))\b", " ", t, flags=re.I)  # 'No corrections from my end / from her'
    # a relayed bare no ('Legal says no') is the bare no
    t = re.sub(r"^\W*(?:the\s+)?\w[\w'-]*\s+(?:says|said)\W+(?=(?:no|nope|nah)\W*$)", "", t, flags=re.I)
    # the G10 card's own keep option ('correct them here or leave them tagged') changes nothing
    t = re.sub(r"\bleave\s+(?:them|it|these|those|the\s+(?:assumption\s+)?items)\s+(?:as\s+)?tagged\b", "as is", t,
               flags=re.I)
    if _COLLEAGUE.search(t):
        return "Your reply speaks to someone else: reply `ok`, or write your corrections."
    if re.fullmatch(r"\W*(?:raise|lower|increase|decrease|set|change|make)\s+(?:it\s+)?to\s+\d[\d.,%]*\W*", t, re.I):
        return "Your reply does not say what to change: reply `ok`, or say what is wrong and what it should be."
    bare = re.sub(r"\([^()\n]*\)", " ", t)
    if bare != t and _WORD.search(bare) and not any(set(_words(p)) & (_EDITS | _WRONG) or _imperative([
            x for x in _words(p) if x not in ("but", "however")], False) or _note_turns(gid, p) or re.search(
            r"\b(?:is|are|looks?|seems?)\s+off\b", p, re.I)
            for p in re.findall(r"\(([^()\n]*)\)", t)):
        t = bare
    if _ELSEWHERE.search(t):
        return "Your reply points to changes the kit cannot see: write them out, or reply `ok`."
    vw = set(_words(t))
    if vw <= _VAGUE and vw & _VAGUE_NOUN or vw <= _VAGUE | _EDIT_VERBS | _POINTER and vw & (_EDIT_VERBS | _VAGUE_NOUN) \
            and vw & _POINTER:
        return "Your reply does not say what to change: write what to change, or reply `ok`."
    read, rows, defer, said_no, nochange = _read(t), [], False, False, False
    imp, jud = set(), set()
    for i, ((c, w, neg, no), (_c, asks)) in enumerate(zip(read, _clauses(t))):
        nxt = read[i + 1][1] if i + 1 < len(read) else []
        if _bare_no(w) and (i and read[i - 1][3] or not rows and _is_yes(nxt) and not _COURTESY.issuperset(nxt)):
            said_no = True
            continue
        kind = "refused" if no else _change_kind(w, neg, no)
        if kind == "content" and re.fullmatch(r"\W*(?:and\s+|but\s+)?(?:no|zero)\s+[\w'-]+(?:\s+(?:needed|required|"
                                              r"necessary|whatsoever|at\s+all|please|thanks))*\W*", c, re.I) and \
                not any(j != i and r[1] and not r[3] and _change_kind(r[1], r[2], r[3]) in ("content", "mixed")
                        for j, r in enumerate(read)):
            # 'no updates', 'no emojis': nothing to change, or what to change? asked, never read as either
            return ("Your reply says %r, and I cannot tell whether that means nothing changes or what to change: "
                    "reply `ok`, or write what to change." % c.strip()[:60])
        if _NO_CHANGE.search(c):
            other = bool(re.search(r"\bother\b", c, re.I))  # 'Remove X. No other issues.': the edit stands
            kind, nochange = "none" if other else "yes", nochange or not other
        defer = defer or bool(_DEFER.search(c))
        at = next((j for j, x in enumerate(w) if x not in _IMP_LEAD), len(w))
        lead = w[at:at + 2]
        if kind == "mixed" and lead[:1] and lead[0] in _EDIT_VERBS and (
                lead[1:] and lead[1] in _IMP_OBJECT or re.search(r"\b%s\s*:" % lead[0], c, re.I)):
            kind = "content"  # 'Add: swaps must be approved by the charge nurse'
        if kind in ("content", "mixed") and (asks or _QUESTION.match(c)) and not _REQUEST.match(c) or \
                kind == "refused" and asks and \
                _QUESTION.match(c) and not (nxt and _bare_no(nxt)):
            return "Your reply asks a question: answer it, or reply `ok` or your corrections."
        if kind in ("content", "mixed") and re.search(r"\b(?:%s|unsure|no\s+idea|(?:don't|do\s+not|can't|cannot)\s+"
                                                      r"(?:really\s+)?(?:understand|follow|judge|tell)|(?:i|we)\s+"
                                                      r"(?:don't|do\s+not|can't|cannot)\s+(?:really\s+)?know\s+what\b"
                                                      r"[^.;!?\n]{0,60}\bmeans?|not\s+my\s+(?:area|field|thing))\b"
                                                      % _NOT_SURE, c, re.I):
            # 'The frame is fine but I am not sure about the weights', "I can't judge the technical parts", "I don't
            # know what ASSUMED means" (a question about the card)
            kind = "no"
        if kind in ("content", "mixed") and _IF_LEAD.match(c):
            return "Your reply sets a condition the kit cannot check: reply without one."
        if kind == "content" and _KEEP_ASK.match(c):
            kind = "none"
        but_led = bool(re.match(r"\W*(?:but|except|however)\b", c, re.I))
        strong = kind == "content" and bool(set(w) & (_EDITS - _VAGUE_NOUN) or _imperative(w) or ":" in c and
                                            _imperative(_words(c.split(":", 1)[1])) or rows and but_led and
                                            rows[-1][3] in ("yes", "mixed") or re.match(
                                                r"\W*corrections?\s*:\s*\w", c, re.I)) and not re.search(
            r"\b(?:later|someday|eventually)\b", c, re.I)  # "yes, but I'll want to change things later"
        if strong and not set(w) & _EDITS and not any(x[:1].isdigit() for x in w) and not but_led:
            imp.add(len(rows))  # 'email this to my boss', '(checked the weights)': beside a yes it asks
        if kind == "content" and not strong and _REMARK.match(c):
            kind = "none"  # 'I read it all', 'the team liked section 4': a remark
        nots = w[:-1] if w[-1:] == ["too"] else w  # 'fine too'
        negw = any(x in NEG_WORDS - _HOLD or x.endswith("n't") for x in nots) and not re.match(
            r"\W*(?:although|though|even)\b", c, re.I)
        weak = kind == "content" and (">" in c or any(x[:1].isdigit() for x in w) or bool(rows) and (
            rows[-1][3] == "no" or rows[-1][3] == "refused" and said_no))
        # corrects unless the reply also confirms: a statement that calls something wrong or off, and (past G2c,
        # where the redo is paid) a negated one ("fine by me, I don't know much about this")
        judged = kind == "content" and bool(_CORRECTS.search(c) or set(w) & _WRONG)
        if judged:
            jud.add(len(rows))
        rows.append((c, w, neg, kind, 0.5 if kind == "content" and _ASIDE.match(c) else 2 if strong else 1 if weak else
                     (1 if gid == "G2c" and not re.match(r"\W*(?:i|i'm|i've|we|we're)\b", c, re.I) else 0.75)
                     if kind == "content" and negw else 0.5 if judged else 0))
        said_no = False
    if any(r[3] in ("yes", "mixed") for r in rows):
        # a clause judged wrong stands when the only confirmation is a later clause with its own subject ('The
        # latency driver is wrong: ..., a 1-hour delay is fine'); a bare or leading one ('fine, but ...') cancels it
        own = bool(jud) and all(r[3] == "mixed" and i > min(jud) and r[1][:1] and r[1][0] not in YES_WORDS
                                for i, r in enumerate(rows) if r[3] in ("yes", "mixed"))
        rows = [r if r[4] not in (0.5, 0.75) and i not in imp and not nochange or own and i in jud else r[:4] + (0,)
                for i, r in enumerate(rows)]
    if any(r[4] for r in rows) and any(r[3] == "no" and (set(r[1]) & _HEDGES or re.search(
            _NOT_SURE, r[0], re.I)) for r in rows):
        return "Your reply is not sure yet: reply once you have decided."
    if defer and any(r[3] not in ("no", "refused") for r in rows):  # a bare 'not yet' or 'wait' says no
        return "Your reply puts the decision off: reply once you have decided."
    if re.search(r"\bif\b", t, re.I) and re.search(r"\botherwise\b", t, re.I):
        return "Your reply sets a condition the kit cannot check: reply without one."
    return rows


_OFFER_DONE = re.compile(r"\b(?:done|finished|enough|that(?:'s|\s+is)\s+all|all\s+(?:set|good)|nothing\s+(?:more|"
                         r"else)|(?:i'm|i\s+am|we're|we\s+are)\s+(?:good|fine|ok(?:ay)?|happy|set)|as\s+(?:it\s+)?"
                         r"is)\b", re.I)
_STOP_IDIOM = re.compile(r"\b(?:call\s+it\s+a\s+day|pull\s+the\s+plug)\b", re.I)  # GB, GX, the v1-run offer
_OFFER_KEYS = frozenset(("go", "stop", "cancel"))
# a clause that limits the extension names a part of it or leads with a limiting word ('go, but no proposal', 'go,
# just the architecture'); 'Please proceed, no further questions from my side' limits nothing
_OFFER_PART = frozenset(("architecture", "arch", "proposal", "package", "adr", "adrs", "decisions", "handoff"))
_OFFER_LIMIT = re.compile(r"\W*(?:but|except|only|just|however|without)\b", re.I)
# the words of a clause that goes ('Okay, go ahead with the full package.')
_OFFER_WORDS = YES_WORDS | _G0_CHAT | frozenset((
    "go", "with", "the", "and", "architecture", "package", "proposal", "full", "run", "v1", "both", "a", "an", "ahead",
    "extension", "same"))


def _offer(text):
    """The v1-run offer reply: 'go' (extend the run), 'stop' (for good) or None (asked again). extend, extension,
    proceed, continue and keep going say go. The one of go / stop no negation refuses decides ('go not stop', "Don't
    stop, go!", 'Extend it? No.'), unless another clause limits the go ('go, but no proposal', 'go, just the
    architecture'); without either, the first clause that says something does: a refusal stops ("No thanks, I'm done",
    'not now') and a clause of confirmations goes ('Hmm. Okay, go ahead.'; courtesy alone, 'thank you', does not). A
    question, a hedge, a deferral ('wait', 'go later', 'not yet'), 'why not', a word of not understanding, a word the
    offer does not read, a polite decline ("I'm done, thanks", "I'm good") and a sign-off ('sign it off': approve the
    extension, or wrap the run up?) are asked again."""
    said, only = _unwrap(text, "G0v1")
    said = re.sub(r"[^\S\n]+(?:#|//)[^\S\n]", ", ", said.translate(_QUOTES))  # a kept note: 'go # no proposal'
    if only or _lookalike(said) or re.search(r"\bwhy\s+not\b|\bsign(?:ed)?\s+(?:it\s+)?off\b", said, re.I):
        return None
    said = re.sub(r"\b(?:extend(?:ed|ing)?|extension|proceed|continue|keep\s+going|carry\s+on)\b", "go",
                  _STOP_IDIOM.sub("stop", said), flags=re.I)
    w = _words(said)
    if not w or _unsure(said, True, "G0v1") or _KICKOFF_HEDGE.search(said) or "yet" in w or _uncovered(
            "G0v1", said) or any(
            x in _HOLD and x not in ("stop", "cancel") or x in (
                "unsure", "idk", "dunno", "know", "understand", "mean", "means", "meaning", "what", "why", "how")
            for x in w):
        return None
    if "without" in w:
        return None  # 'go without the proposal': a part left out, like 'go, but no proposal' (not a refused go)
    negs = lambda w: [x in ("not", "no", "never", "against", "nor") or x.endswith("n't") for x in w]
    if any("go" in r[1] and sum(negs(r[1])) - (r[1][0] in ("no", "nope", "nah") and negs(r[1][1:2]) == [True]) > 1
           for r in _read(said)):
        return None  # two negations before go ("I'm not against extending", 'no reason not to extend'): asked ('no
        # don't extend' refuses twice)
    chosen, refused = _named(said, lambda x: x in _OFFER_KEYS)
    left = set("stop" if x == "cancel" else x for x in chosen) - set(refused)
    if chosen:
        if left == set(["go"]) and any((r[2] or r[3] or set(r[1]) & set(("only", "just"))) and not _bare_no(r[1]) and
                                       not set(r[1]) & _OFFER_KEYS and (set(r[1]) & _OFFER_PART or
                                                                        _OFFER_LIMIT.match(r[0])) for r in _read(said)):
            return None  # 'go, but no proposal': part of the extension refused
        return left.pop() if len(left) == 1 else None
    if refused:
        if len(set(refused)) > 1:
            return None
        if refused[0] != "go" and any(a and re.search(r"\b(?:stop|cancel)\b", c, re.I) for c, a in _clauses(said)) \
                and any(x in YES_WORDS and x not in _COURTESY for r in _read(said) for x in r[1]):
            return "go"  # 'Stop? No, please go ahead.'
        # 'stop, no thanks' refuses nothing: only a negated stop ("don't stop") goes
        return "stop" if refused[0] == "go" else "go" if any(
            r[2] and set(r[1]) & set(("stop", "cancel")) for r in _read(said, lambda x: x in _OFFER_KEYS)) else None
    rows = [r for r in _read(said) if not _INTERJ.issuperset(r[1])]
    if rows and (rows[0][2] or NO_WORDS & set(rows[0][1][:1]) or "enough" in rows[0][1]):
        return None if any(x in YES_WORDS and x not in _COURTESY for x in rows[0][1][1:] + [
            x for r in rows[1:] for x in r[1]]) else "stop"  # 'no no no yes' is asked again
    if _OFFER_DONE.search(said):
        return None
    return "go" if any(all(x in _OFFER_WORDS for x in r[1]) and any(
        x in YES_WORDS and x not in _COURTESY for x in r[1]) for r in rows) and not any(r[2] or r[3] for r in rows) \
        else None


def _v1_offer(ans):
    """_offer for a G0 answer at the v1-run offer. A `confirm` the host filled itself (not what the reply reads) wins,
    and so does an empty reply: false stops, anything else goes."""
    reply, confirm = (ans.get("reply") or "").strip(), ans.get("confirm")
    if not reply or confirm is not None and confirm != parse_kickoff(reply).get("confirm"):
        return "stop" if confirm is False else "go"
    return _offer(reply)


def _yesno(text):
    """True, False or None (neither): confirmation words alone (and `true`, `done`, `1`) are yes; no words alone (with
    `thanks` or `please` at most) are no."""
    w = _words(text)
    if w and all(x in YES_WORDS or x in ("true", "done", "1") for x in w):
        return True
    if any(x in NO_WORDS for x in w) and all(x in NO_WORDS or x in ("thanks", "please") for x in w):
        return False
    return None


def _say(why, text):
    if why is not None:
        why.append(text)


def _named(text, is_key):
    """(chosen, refused) for the keywords of a reply (is_key(word)): a keyword in a negated clause, or in the clause
    before a bare refusal ('Passed? No.', 'Passed? Not really.'), is refused."""
    chosen, refused = [], []
    for _c, w, neg, no in _read(text, is_key):
        (refused if neg or no else chosen).extend(x for x in w if is_key(x))
    return chosen, refused


def _pick(text, keys, why=None):
    """The one keyword of `keys` a reply chooses (G1, G2f, G9, GX), or None. Words match whole ('discontinue' is no
    `continue`). It is the one keyword named outside a negation that no negation refuses ('Passed? No. Missed');
    two such keywords, or only refused ones, are asked again ('passed, missed', 'Passed? Sadly not.')."""
    chosen, refused = _named(text, lambda w: w in keys)
    named = set(chosen) | set(refused)
    left = set(chosen) - set(refused)
    if len(left) == 1:
        return left.pop()
    _say(why, "Your reply names %s, so it is unclear which one you mean." % " and ".join(
        "`%s`" % k for k in sorted(named)) if len(named) > 1 else "Your reply names `%s` in a negation." % named.pop()
        if named else "Your reply names none of them.")
    return None


def _strip_bullet(s):
    return re.sub(r"^\s*(?:[-*\u2022]|\d+[.)])\s*", "", s).strip()


_PRIVACY_OFF = NO_WORDS | frozenset(("off", "none", "disable", "disabled", "never", "deny", "denied", "block",
                                     "blocked", "disallow", "disallowed", "forbid", "forbidden", "prohibit",
                                     "prohibited", "refuse", "refused", "reject", "rejected"))
_PRIVACY_ON = YES_WORDS | frozenset(("on", "true", "1", "enable", "enabled", "allow", "allowed"))


def _privacy_value(val):
    """False or True for the value of `web:`, `vendors:` or `code:` ('no', 'off', 'none', 'disabled'; 'yes', 'on',
    'allowed'), or None when it is neither ('maybe')."""
    w = [x for x in _words(val) if x not in ("thanks", "please", "thx")]
    if w and all(x in _PRIVACY_OFF for x in w):
        return False
    if w and all(x in _PRIVACY_ON for x in w):
        return True
    return None


_KICKOFF_HEDGE = re.compile(r"\b(?:let\s+me|(?:don't|dont|do\s+not)\s+know|not\s+sure|no\s+(?:idea|clue)|hold\s+(?:on|"
                            r"off|up|your\s+horses)|hang\s+on|brb|(?:a|one)\s+(?:sec|second|moment|minute)|need\s+to\s+"
                            r"think)\b|^\W*wait\b", re.I)
# a G0 seed line that reads as a privacy request: these always ('keep it confidential', 'no web-search', 'offline,
# go', 'keep everything local', a setting without its colon at a line or clause start: 'web off'; not 'an
# offline-first app', 'qr code on the wall')...
_PRIVACY_SAID = re.compile(
    r"\b(?:priv(?:at|ad|\u00e9)\w*|confiden(?:ti|ci)\w*|vertrau\w*|vertrouw\w*|riservat\w*|geheim\w*|nda|"
    r"in-house|internal\s+only|under\s+wraps|secret\w*|sensitive|proprietary|web\W?(?:search|access|"
    r"lookup|brows)\w*|"
    r"offline(?!-)|(?:other|third|outside)[\s-]+(?:\w+[\s-]+)?(?:compan(?:y|ies)|part(?:y|ies)|models?|providers?)|"
    r"local\s+(?:only|models?)|(?:keep|stay|run)\w*\s+(?:\w+\s+){0,2}local(?:ly)?|leav\w*\s+(?:my|this|the)\s+"
    r"(?:machine|computer|laptop|device|network))|(?:^|[^\w\s])\s*(?:web|vendors?|code)\s*(?:=|(?:off|on|yes|no|true|"
    r"false)\b)|"
    # 'no internet' and 'only Claude' in Arabic, Hindi, Chinese, French, Portuguese and Turkish
    r"(?:\u0628\u062f\u0648\u0646|\u0628\u0644\u0627)\s*(?:\u0627\u0644)?(?:\u0627\u0646\u062a\u0631\u0646\u062a|\u0625"
    r"\u0646\u062a\u0631\u0646\u062a|\u0628\u062d\u062b|\u0648\u064a\u0628)|(?:\u0641\u0642\u0637|\u0938\u093f\u0930"
    r"\u094d\u092b|\u0915\u0947\u0935\u0932|\bseulement|\bapenas|\bsomente|\bsadece)\s+claude\b|\u092c\u093f\u0928"
    r"\u093e\s*\u0907\u0902\u091f\u0930\u0928\u0947\u091f|\u4e0d\u8981?\u8054\u7f51|\u4e0d(?:\u8981|\u7528)?\u4e0a"
    r"\u7f51|\u79bb\u7ebf|\bpas\s+(?:de\s+|d')?(?:recherche\s+)?(?:internet|web)\b|\bsem\s+internet\b|"
    r"\binternetsiz\b", re.I)
# ...and these beside a negation, `only`, `outside` or `avoid` ("don't send this to OpenAI", 'claude only', 'no
# internet'; not 'a Claude plugin for nurses')
_PRIVACY_NAMED = re.compile(r"\b(?:internet\w*|\u0438\u043d\u0442\u0435\u0440\u043d\u0435\u0442\w*|online|"
                            r"web(?:suche)?|"
                            r"claude|anthropic|gpt\w*|chatgpt|openai|codex|kimi|moonshot|glm|"
                            r"zhipu|z\.ai|gemini|googl\w*|send\w*|shar\w*|lookups?|brows\w*|search\w*|llms?|ais?|"
                            r"models?|providers?)\b", re.I)
_PRIVACY_LIMIT = frozenset(("only", "outside", "avoid", "except", "nothing", "without", "exclusively", "just", "solely",
                            "sin", "sans", "ohne", "senza", "bina", "kein", "keine", "geen", "nessun", "nessuna",
                            "off", "disable", "disabled", "external", "nur", "sirf", "bas", "faqat", "bez", "tolko",
                            "\u0431\u0435\u0437", "\u0442\u043e\u043b\u044c\u043a\u043e", "yok", "sem", "zonder",
                            "utan"))
# a short seed line (up to 3 words beside go and courtesy) that names the web or a model is a privacy request in any
# language ('uniquement Claude', 'bidoon internet', "Claude'dan baska kullanma", 'hors ligne'): asked, not a seed
_PRIVACY_NOUN = re.compile(r"\b(?:internet\w*|online|offline|web|claude|anthropic|gpt\w*|chatgpt|openai|codex|kimi|"
                           r"moonshot|glm|zhipu|gemini|googl\w*|hors\s+ligne)\b(?!-)|"
                           r"\u0627\u0646\u062a\u0631\u0646\u062a|"
                           r"\u0625\u0646\u062a\u0631\u0646\u062a|\u0907\u0902\u091f\u0930\u0928\u0947\u091f", re.I)
# a G0 seed line that names a setting in a sentence ('Please make it quick mode, ...', 'I want full-auto for this',
# "I'd kill for a quick run", 'deep, this matters a lot', 'go deep on this'): a mode or autopilot word on a line that
# is no list item, unless it describes the noun after it ('deep learning for rota prediction', 'a quick way to swap')
_SETTING_SAID = re.compile(r"\b(?:thorough\w*|in[\s-]depth|by\s+yourself|on\s+your\s+own|(?:don't|do\s+not)\s+ask\s+"
                           r"me|(?:quick|standard|deep|proposal|guided)\s+(?:mode|autopilot|run)|hands[\s-]on|"
                           r"full[\s-]auto|autopilot|(?:quick|standard|deep|guided)(?=[^\S\n]*(?:$|[^\w\s-]|(?:please|"
                           r"pls|plz|thanks|one|dive|version|option|setting|plan|and|or|is|it|on|for|then|instead|too|"
                           r"would|will|should|seems|sounds|looks|works|mode|autopilot|run)\b)))", re.I)
# a G0 line that says there are no seeds ('no seeds, go', 'skip the seeds please', "I don't have any ideas yet",
# 'Nothing to add, go')
_NO_SEEDS = re.compile(r"\b(?:(?:no|skip|without)(?:\s+(?:the|any|my))?\s+(?:seeds?|ideas?)|(?:don't|dont|do\s+not)\s+"
                       r"have\s+(?:any\s+)?(?:seeds?|ideas?)|nothing\s+(?:else\s+)?to\s+add)\b")
# a G0 phrase that changes nothing ('Go ahead with the default settings, no changes needed.', 'Nothing to change, go.')
_G0_NOTHING = re.compile(r"\b(?:no\s+changes?(?:\s+(?:needed|required))?|nothing\s+to\s+change|(?:the\s+)?defaults?"
                         r"(?:\s+settings)?|(?:i\s+)?(?:don't|do\s+not)\s+(?:want|need)\s+to\s+change\s+anything|"
                         r"with\s+reference\s+to|as\s+discussed|as\s+is|that(?:'s|\s+is)\s+(?:all|it|(?:my|our|the)\s+"
                         r"(?:idea|seed|problem)s?(?:\s+to\s+(?:test|try|explore))?))\b", re.I)
# a G0 line led by a confirmation ('go with 200 calls max', 'Please proceed with the following seed ideas ...') or
# ending with one ('that ship has sailed, just go')
_G0_LEADS = frozenset(("go", "proceed", "start", "continue", "ok", "okay", "yes", "yep", "yeah", "yup", "y", "confirm",
                       "confirmed"))
# a G0 line that ends a clause with a go word ('The user says go.', 'She said go ahead'; not 'nurses on the go') or
# defers to the kit ('Do what you suggested.', 'Use your recommendation and go.') mixes the reply with other words
_G0_DEFER = re.compile(r"\b(?:(?:what|as)\s+you\s+(?:suggest|recommend)\w*|your\s+(?:recommendation|suggestion)s?)\b",
                       re.I)
# a G0 line that says not to start ("Don't start yet", 'do not proceed')
_NOT_STARTING = re.compile(r"\b(?:don't|dont|do\s+not|not|never)\s+(?:\w+\s+)?(?:start|go|proceed|begin|run|consent|"
                           r"kick\s+(?:it\s+)?off)(?:\s+(?:it|this|anything|the\s+run|yet|now|just))*(?:\s+(?:until|"
                           r"till|"
                           r"before|without)\b[^.;!?\n]*)?(?:\W+(?:thanks|thank\s+you|thx|please))?\W*$", re.I)
# ("Don't start anything yet, thanks", 'never start without me', "don't go until I say so")
_KICKOFF_KEY = re.compile(r"(?:\W*(?:web|vendors?|code)\s*:\s*(?:no|yes|on|off|none|true|false)\b)+\W*$", re.I)
# a G0 line that is an idiom for go
_GO_IDIOM = re.compile(r"^\W*(?:(?:ok(?:ay)?|sure|alright|right)\W+)?(?:let's\s+get\s+(?:this|the)\s+(?:show|"
                       r"party|ball)\s+(?:on\s+the\s+road|started|rolling)|hit\s+it|fire\s+away|let's\s+(?:roll|go|"
                       r"do\s+(?:it|this)|begin|rock)|go\s+for\s+it|off\s+we\s+go|make\s+it\s+so|full\s+steam\s+ahead|"
                       r"kick\s+(?:it|things)\s+off|do\s+it|lgtm(?:\W+ship\s+it)?|ship\s+it|(?:looks|sounds)\s+good"
                       r"(?:\s+to\s+me)?|(?:we\s+|i\s+)?(?:give\s+(?:my\s+|our\s+)?)?consent(?:\s+given|\s+to\s+proceed"
                       r"(?:\s+on\s+the\s+standard\s+terms)?)?|"
                       r"proceed)\W*$", re.I)


# a G0 line that only takes the reply back ('nvm', 'jk not yet', 'wait a sec'): asked beside `go` too
_TAKE_BACK = re.compile(
    r"\W*(?:(?:actually|oh|um|hmm|ok|so)\W+)?(?:nvm|never\s*mind|jk|just\s+kidding|wait|hold\s+on|hang\s+on)\b"
    r"(?:\W+(?:a|one)(?:\s+more)?\s+(?:sec|second|moment|minute|min))?(?:\W+(?:not\s+yet|hold\s+on|wait))?\W*|"
    r"\W*(?:wait\s+)?(?:a|one)(?:\s+more)?\s+(?:sec|second|moment|minute|min)\W*", re.I)


def _kickoff_doubt(line, toks):
    """('privacy', why) for a G0 seed line that reads as a privacy request ('keep my idea private', 'no web search',
    "don't send my idea to other vendors", 'only use Claude'), ('setting', why) for one that names a setting in a
    sentence, ('reply', why) for one that refuses to start or reads as the reply to another card ("Don't start yet",
    'publish all, ce'), ('seed', why) for one with a bare refusal, a hedge or a question in it ('not yet, let me
    think', 'Hmm, not sure', 'no, make it deep', 'Can we do quick instead?'), else None."""
    said = line.translate(_QUOTES)
    if any(t in ("private", "privacy", "vendor", "vendors") for t in toks) or _PRIVACY_SAID.search(said) or (
            _negated(toks) or any(t in NO_WORDS or t in _PRIVACY_LIMIT for t in toks)) and _PRIVACY_NAMED.search(
            said) or _PRIVACY_NOUN.search(said) and len([t for t in said.split() if t.strip(".,;:!?").lower() not in
                                                         _G0_LEADS | _COURTESY]) <= 3:
        return ("privacy", "Did you mean a privacy setting (%r)? Reply `private`, or `web: no` / `vendors: no` / "
                           "`code: yes`, then `go`; an idea that mentions these goes in as a list item (`- ...`)."
                % line[:60])
    if _SETTING_SAID.search(said):
        return ("setting", "Did you mean a setting (%r)? Reply it on a line of its own (`deep`, `hands-on`), then "
                           "`go`; an idea that mentions it goes in as a list item (`- ...`)." % line[:60])
    if any(_NOT_STARTING.search(c) for c, _a in _clauses(said) + [(said, False)]) or _TAKE_BACK.fullmatch(said) or \
            re.search(r"\bhold(?:ing)?\s+off\b", said, re.I):  # "don't go yet, I want to add ideas"
        return ("reply", "Your reply says not to start yet: reply `go` when you are ready.")
    rest = [t for t in toks if t not in _COURTESY]
    if "?" in line or _QUESTION.match(said) or any(
            t in ("unsure", "maybe", "perhaps", "idk", "dunno", "hmm", "hm") for t in toks) or len(
            rest) <= 2 and any(difflib.get_close_matches(re.sub(r"(.)\1{2,}", r"\1", t), _G0_LEADS, 1, 0.75)
                               for t in rest) or len("".join(rest)) <= 3 or any(  # 'lets gooo'; 'fo', '+1'
            _bare_no(r[1]) for r in _read(line)) or _KICKOFF_HEDGE.search(said) or _SARCASM.search(said) or \
            toks[:1] and toks[0] in NO_WORDS and any(t in YES_WORDS for t in toks[1:]):  # 'no go'
        return ("seed", "Start with %r as a seed idea? Reply `go` with your ideas (one per line), or a mode (`quick`, "
                        "`standard`, `deep`) to change it." % line[:60])
    if rest[:1] and rest[0] in ("publish", "passed", "missed", "inconclusive", "kill", "rescue", "reframe", "reject",
                                "accept", "restore", "switch") and any(
            rest[0] in _ANCHORS[g] and all(_known(g, x, x) for x in toks) for g in _ANCHORS):
        return ("reply", "Your line %r reads as the reply to another card: reply `go` (with your ideas, one per line) "
                         "to start." % line[:60])  # 'publish all, ce', 'passed, 14 of 20'
    if any(re.match(r"\W*(?:sorry|ugh|whatever\s+you|up\s+to\s+you|your\s+call|you\s+decide)\b", c, re.I) or
           _QUESTION.match(c) for c, _a in _clauses(said)):
        return ("reply", "Your line %r reads as a remark, not an idea: put `go` on a line of its own and each seed "
                         "idea on its own line (`- ...`)." % line[:60])
    parts = [w for w in (_words(c) for c, _a in _clauses(said)) if w]
    leads = [[x for x in p if x not in _COURTESY and x not in _INTERJ][:1] for p in parts]
    if any(x and x[0] in _G0_LEADS | frozenset(("begin",)) for x in leads) or _NO_SEEDS.search(" ".join(toks)) or \
            any(p[-1] in _G0_LEADS and "the" not in p[-3:-1] or p[-2:] == ["go", "ahead"] and "the" not in p[-4:-2]
                for p in parts) or _G0_DEFER.search(said) or parts and len(parts) > 1 and all(
                x in YES_WORDS or x in _G0_CHAT for x in parts[-1]) and any(x in _G0_LEADS for x in parts[-1]):
        # 'go with 200 calls max', 'skip seeds; deep; go', 'that ship has sailed, just go', 'Looks fine, start whenever'
        return ("reply", "Your line %r mixes your reply with other words: put `go` (or `skip`) on a line of its own "
                         "and each seed idea on its own line (`- ...`)." % line[:60])
    return None


def parse_kickoff(text, doubts=None):
    """G0 reply -> fields. A line is a keyword line only when every word (read by _words; 'hands on' and 'full auto'
    as one) is a setting (a mode, variant or autopilot, `private` or `privacy`, `with-ce-ideate`), a confirmation
    (YES_WORDS, YES_PHRASES, `start`, `continue`) or chat (_G0_CHAT: 'Sounds great, thanks so much! Go ahead'); beside
    a setting the words of _G0_FILLER may stand too ('OK, go ahead with standard please', 'keep it private', 'switch
    to deep mode'). A line that says there are no seeds, with chat or a confirmation at most, skips them ('no seeds,
    go', "I don't have ideas yet, sorry! Go ahead"). A list item ('- deep') or any other line ('deep learning ideas') is
    a seed; a line without a word (dashes, emoji) or that ends with a colon ('My ideas:') is nothing, and a bare
    refusal ('no', 'stop', 'not now') sets `confirm` false. Every `web:`, `vendors:` and `code:` pair of a line is read
    ('web: no, vendors: off'). `doubts` (a list), when given, gets (kind, why) for an unreadable privacy value and for
    each seed line that is not a list item and reads as a privacy request, a setting or a deferral (_kickoff_doubt):
    validate() asks again rather than send it to the vendors."""
    out = {"seeds": {"ideas": [], "obvious": [], "off_limits": []}, "privacy": {}, "quick": {}}
    lines = []
    t, only = _unwrap(text, "G0")
    odd = only if isinstance(only, str) else "Your reply only quotes other text: reply with your own answer." if \
        only else _lookalike(t)
    if odd:  # never a seed: asked again
        _say(doubts, ("text", odd))
        return out
    for raw in t.split("\n"):
        parts = re.split(r"(?<=[.;!,])[^\S\n]+", raw.strip())
        # 'Ok. web: no. go.', 'deep, hands-on, web: no': a line of keywords and `key: value` pairs is one line each
        lines += parts if len(parts) > 1 and all(_KICKOFF_KEY.match(p) or all(
            x in KEYWORDS or x in YES_WORDS or x in _G0_CHAT for x in _words(p)) for p in parts) else [raw]
    for raw in lines:
        line = raw.strip()
        line = "go" if _GO_IDIOM.match(line.translate(_QUOTES)) else line  # 'Hit it', 'Fire away'
        toks = _words(re.sub(r"\b(hands|full)\s+(on|auto)\b", r"\1-\2", line, flags=re.I))  # 'hands on', 'full auto'
        if not toks or not _BULLET.match(line) and re.fullmatch(_CLOSING, line, re.I) and not set(toks) & _G0_LEADS:
            continue  # an email closing before `go` ('Looking forward to the results.\ngo') is no idea
        if _BULLET.match(line) and _KICKOFF_KEY.match(_strip_bullet(line)):
            line = _strip_bullet(line)  # '- web: no' is the setting
        if _BULLET.match(line) and all(t in _G0_LEADS or t in _COURTESY for t in toks):
            _say(doubts, ("reply", "Your list item %r is a reply: put `go` on a line of its own." % line[:60]))
            continue
        if not _BULLET.match(line) and (line.endswith(":") or re.match(r"(?:#|//)", line)):
            # a header ('My ideas:') or a comment line ('# no seeds this time') is no idea; a privacy wish or a setting
            # in it is asked again ('Keep this private. My ideas:')
            doubt = _kickoff_doubt(line, toks)
            if doubt and doubt[0] in ("privacy", "setting"):
                _say(doubts, doubt)
            if not re.match(r"(?:primary(?: idea)?|problem|obvious|off[- ]limits|topic|idea|criteria|hard constraint|"
                            r"constraint|families|web|vendors?|code)\s*:", line, re.I):
                continue
        if not _BULLET.match(line):
            toks = _words(_G0_NOTHING.sub(" ", " ".join(toks)))  # 'no changes needed' is chat
            if not toks:
                continue
        setting = any(t in MODES or t in VARIANTS or t in AUTOPILOTS or t in ("private", "privacy") for t in toks)
        if not _BULLET.match(line) and all(t in KEYWORDS or t in YES_WORDS or t in _G0_CHAT or setting and
                                           t in _G0_FILLER for t in toks):
            for i, t in enumerate(toks):
                key = "mode" if t in MODES else "autopilot" if t in AUTOPILOTS else None
                if key and out.get(key) not in (None, t) and toks[i - 1:i] != ["to"]:  # 'quick standard deep'
                    _say(doubts, ("setting", "Your reply names two %ss (`%s` and `%s`): reply one." % (
                        key, out[key], t)))
                if t in MODES:
                    out["mode"] = t
                elif t in VARIANTS:
                    out["variant"] = t
                elif t in AUTOPILOTS:
                    out["autopilot"] = t
                elif t in ("private", "privacy"):
                    out["private"] = True
                elif t == "with-ce-ideate":
                    out["with_ce_ideate"] = True
                elif t not in _G0_FILLER and t not in _G0_CHAT:
                    out["confirm"] = True
            continue
        rest = _NO_SEEDS.sub(" ", " ".join(toks)).split()
        if toks in (["skip"], ["none"]) or rest != toks and all(t in YES_WORDS or t in _G0_CHAT for t in rest):
            out["skip_seeds"] = True
            out["confirm"] = True
            continue
        if _bare_no(toks):  # 'no', 'stop', 'not now': no seed idea, and validate() asks again
            out["confirm"] = False
            continue
        m = re.match(r"^(primary(?: idea)?|problem|obvious|off[- ]limits|topic|idea|criteria|hard constraint|"
                     r"constraint|families|web|vendors?|code)\s*:\s*(.*)$", line, re.I)
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
            else:  # web, vendors, code: every pair of the line ('web: no, vendors: no')
                for k, v in re.findall(r"\b(web|vendors?|code)\s*:\s*([^,;/|\n]*?)(?=[,;/|\n]|\.(?:\s|$)|$)", line,
                                       re.I):
                    k = "vendors" if k.lower().startswith("vendor") else k.lower()
                    yn = _privacy_value(v.split("(")[0])  # 'vendors: no (client NDA)'
                    if yn is None:
                        _say(doubts, ("privacy", "`%s: %s` is unclear: reply `%s: no` or `%s: yes`." % (
                            k, v.strip()[:40], k, k)))
                    else:
                        out["privacy"][k] = yn
            continue
        seed = _strip_bullet(line)
        if seed and (_BULLET.match(line) or not line.endswith(":")):  # 'My ideas:' heads a list, it is no idea
            out["seeds"]["ideas"].append(seed)
            doubt = None if _BULLET.match(line) else _kickoff_doubt(line, toks)
            if doubt:
                _say(doubts, doubt)
    return out


# G4/G5: a piece starts at each verb with an idea ID right after it (no , or ; between them), never at a plain comma (a
# rescue reason may name another ID). It starts where the verb's clause starts, or after the ID before the verb in the
# same clause, so the words before the verb stay with it ("don't kill I-003", "I don't want to kill I-003", 'no need
# to confirm I-004'). The verb takes the IDs of its list ('kill I-003 and I-007', 'rescue I-004, I-005', 'kill idea
# I-003', 'clear the flag on I-004'); a list goes on to a next ID only when that ID ends it ('kill I-003, I-007 too';
# 'kill I-003, I-007 is fine' kills I-003 alone).
_ID_LIST = (r"[IEQ]-\d+(?:(?:\s*[,&/+]\s*(?:and\s+)?|\s+(?:and(?:\s+also)?|plus|as\s+well\s+as)\s+|\s+)[IEQ]-\d+"
            r"(?=\s*(?:[,&/+;:.!?)\]}\-\u2013\u2014]|(?:and|because|since|too|also|as\s+well|both|please|pls|plz|"
            r"thanks|thx)\b|"
            r"$)))*")
# G14: a publish the user does himself ("I'll publish it myself", 'by hand') publishes nothing
_SELF_PUB = re.compile(r"\b(?:myself|ourselves|by\s+hand|manually|on\s+(?:my|our)\s+own)\b", re.I)
# an ID range ('kill I-003..I-007', 'confirm I-004 to I-006') is asked again at G4 and G5
_ID_RANGE = re.compile(r"[IEQ]-\d+[^\S\n]*(?:\.\.+|[-\u2013\u2014]|\b(?:to|through|thru)\b)[^\S\n]*(?:[IEQ]-)?\d", re.I)
_SHORT_ID = re.compile(r"(?<![\w-])[IEQ]-\d{1,2}(?![\w-])", re.I)  # 'I-4' is no ID of the run (I-004)
_ALL_OF_THEM = r"\b(%s)\b\W*(?:(?:th)?em\s+)?(?:both|all|them|every\w*)\b"
# a verb before a bare number, #3 or i3 (or #3 / i3 before a verb) names no ID: 'kill 3 and 7', 'rescue #12', '#7 kill'
_BY_NUMBER = r"\b(?:%s)\b\W*i?\d|(?:#|\bi)\d+\W*(?:%s)\b"
# a G4/G5 reply that places no idea closes the gate only with one of these words (or a yes, or a negation): 'keep
# them', 'no kills', 'kill none', "don't kill"; 'wait', 'stop' or 'kill' alone are asked again
_KEEPS = frozenset(("keep", "kept", "park", "parked", "none", "neither", "nothing", "no", "nah", "nope", "nor"))


_CONFIRMS = frozenset(("confirm", "confirmed", "confirms", "clear", "cleared", "clears"))


def _keeps_all(words):
    return any(x in _KEEPS or x in _NOT or x.endswith("n't") or x in YES_WORDS and x not in _COURTESY
               for x in words)


# the words that may stand between a denial and its verb ('I do not want to kill', 'no need to confirm')
_DENY_FILLER = frozenset(("i", "we", "you", "really", "just", "want", "need", "to", "should", "would", "will", "be",
                          "going", "gonna", "do", "please", "let's", "lets", "reason", "point"))
# a G4/G5 piece put off ('kill I-003 later') is asked again
_PUT_OFF = re.compile(r"\b(?:later|postpon\w*|defer\w*|not\s+(?:now|yet)|hold\s+off)\b", re.I)
# G5: a kill of no ID that names none ('kill none'); the words before a verbless ID that make it no order ('it
# duplicates I-007', 'a copy of I-007')
_NONE_OF = frozenset(("none", "nothing", "neither", "nor", "no"))
_NOT_AN_ORDER = frozenset(("it", "this", "that", "which", "who", "they", "he", "she", "i", "we", "of", "than", "like",
                           "to", "with", "from", "as", "is", "are", "was", "not", "and", "or", "vs", "versus"))


def _verb_clauses(line, verbs):
    """(piece, verb) for each piece of a G4/G5 line; `verb` is the match of the verb (group 1) and its ID list (group
    2), or None for a piece with no such verb ('I-003: kill, I-007: keep' names each ID before its verb)."""
    line = _it_id(re.sub(r"[^\S\n]+", " ", line.translate(_QUOTES)), verbs)
    at = re.compile(r"\b(%s)\b[^\w,;]*(?:(?:the\s+)?(?:idea|flags?\s+(?:on|for|of))\s+)?(%s)" % (verbs, _ID_LIST),
                    re.I)
    marks = sorted([0] + [m.end() for m in _CLAUSE_END.finditer(line)] + [m.end() for m in ID_RE.finditer(line)])
    cuts = sorted(set([0] + [marks[bisect.bisect_right(marks, m.start()) - 1] for m in at.finditer(line)]))
    pieces = [line[a:b] for a, b in zip(cuts, cuts[1:] + [len(line)]) if line[a:b].strip()]
    return [(c, at.search(c)) for c in pieces]


def _it_id(line, verbs):
    """`line` with each pronoun object of a verb ('kill it', 'confirm this one') written as the one ID its sentence
    names before it ('I-003 should go, kill it'); with two IDs there it stays ('I-003 duplicates I-007, kill it')."""
    out, at, seen = [], 0, set()
    for m in re.finditer(r"(?P<end>[.!;\n])|\b(?P<id>[IEQ]-\d+)\b|\b(?:%s)\s+(?P<it>it|th(?:is|at)\s+one)\b" % verbs,
                         line, re.I):
        if m.group("end"):
            seen = set()
        elif m.group("id"):
            seen.add(m.group("id").upper())
        elif len(seen) == 1:
            out += [line[at:m.start("it")], next(iter(seen))]
            at = m.end("it")
    return "".join(out) + line[at:]


def _denies(words):
    """The words before a G4/G5 verb deny it ("don't kill", 'I do not want to kill', 'no need to confirm', 'never
    kill'); "I don't see the point so kill" and "I'd rather confirm" do not."""
    w = list(words)
    while w and w[-1] in _DENY_FILLER:
        w.pop()
    if w[-1:] == ["not"] and w[-2:-1] and (w[-2] in ("not", "never", "cannot") or w[-2].endswith("n't")):
        return False  # "I can't not rescue I-012" rescues it
    return bool(w) and (w[-1] in ("not", "never", "no", "dont", "cannot") or w[-1].endswith("n't"))


def _spoken_against(piece, v=None):
    """A G4/G5 piece names nothing when a bare refusal refuses it ('kill I-003? no.', 'rescue I-004? wait'), when it
    defers before its first ID ('hold off: kill I-003', 'later: kill I-003') or when a bare refusal or a deferral ends
    it ('kill I-003 later', 'kill I-003 - not now'), unless that end follows an ID of a later clause than the verb `v`
    ('kill I-003, we can revisit I-007 later'). A deferral inside a reason ('rescue I-012: it could stop burnout',
    "keep I-007, its cancel flow is the differentiator") defers nothing."""
    first, last = ID_RE.search(piece), None
    for last in ID_RE.finditer(piece):
        pass
    if v and last and last.start() >= v.end() and _CLAUSE_END.search(piece[v.end():last.start()]):
        last = None
    before = _words(piece[:first.start()]) if first else []
    defers = any(x in ("later", "postpone", "defer", "cancel") or x in _HOLD and before[i + 1:i + 2] in (
        ["off"], ["on"], ["until"]) for i, x in enumerate(before))
    return defers or any(r[3] for r in _read(piece, names=lambda c, w: bool(ID_RE.search(c) or re.search(
        _ALL_OF_THEM % "kill|keep|confirm|clear|rescue|save", c, re.I)))) or \
        bool(last) and (_bare_no(_words(piece[last.end():])) or any(
            _bare_no(_words(c)) for c, _a in _clauses(piece[last.end():])[:1]))


# G11: a letter is the choice where the reply names it as one: after nothing but confirmations, verbs and nouns
# ('ok, go with candidate B.'), or right after a choosing verb anywhere ('I think I'd take C')
_G11_LEAD = frozenset(("with", "choose", "pick", "take", "prefer", "want", "use", "select", "let's", "lets", "let",
                       "us", "i", "i'd", "i'll", "we", "we'll", "would", "like", "then", "candidate", "option",
                       "architecture", "to", "will", "letter", "switch"))
_G11_VERBS = frozenset(("choose", "pick", "take", "prefer", "want", "use", "select"))
_G11_NOUNS = frozenset(("candidate", "option", "architecture", "letter"))
# a clause that takes the suggestion: confirmations and these words ('yes, go with your suggestion', 'go ahead with
# your pick', 'accept the recommendation', 'whatever you suggest'), with a confirmation or one of _G11_POINTS in it
_G11_POINTS = frozenset(("suggestion", "suggested", "recommendation", "recommended", "default", "pick", "leader",
                         "suggest", "recommend"))
_G11_FILLER = _G11_LEAD | frozenset(("the", "your", "my", "one", "it", "that", "choice", "is", "was", "are", "whatever",
                                     "you"))
# a whole reply that calls one letter fine ('A is fine', 'option B looks good to me') chooses it
_G11_FINE = re.compile(r"^\W*(?:(?:ok|okay|yes|well|then)\W+)?(?:(?:option|candidate|architecture)\s+)?(?-i:([A-F]))\s+"
                       r"(?:is|looks|seems|sounds)\s+(?:fine|good|ok|okay|great|right|perfect)(?:\s+(?:to|for|with)\s+"
                       r"(?:me|us))?(?:\W+(?:thanks|thank\s+you|please))?\W*$", re.I)
# the words that may follow a chosen letter to the end of its clause ('C please', 'B is the one', 'B it is', 'B for me')
_G11_AFTER = frozenset(("please", "thanks", "ok", "then", "is", "it", "the", "one", "for", "me", "my", "choice", "pick",
                        "best", "instead"))
# 'steal from A: the cache' / 'steal A the cache' (a capital letter), or 'steal the SMS gateway from B'
# (the element starts at a non-space and one space stands before `from`, so a run of spaces stays linear)
_G11_STEAL = re.compile(r"(?:steal|borrow)\s+(?:from\s+)?(?:([A-Fa-f])\s*:\s*|(?-i:([A-F]))(?:'s)?\s+)([^;\n]+)|"
                        r"(?:steal|borrow)\s+(\S[^;\n]{0,79}?)\sfrom\s+(?-i:([A-F]))\b", re.I)


def _g11_letters(clause):
    """(chosen, named): the candidate letters a G11 clause chooses, and every letter it names (a capital A-F alone, or
    a lower-case one where it would be chosen: the article 'a' is never candidate A). A letter said twice is one ('B
    B'). One pass each way, so a flood of letters stays linear."""
    toks = _tokens(clause)
    toks = [t for i, t in enumerate(toks) if not (i and len(t[1]) == 1 and t[1] == toks[i - 1][1])]
    lw = [w for w, _ in toks]
    n = len(lw)
    # head[i]: every word before i is a confirmation or a lead word; led[i]: a verb, a noun or `with` stands before i;
    # ends[i]: every word after i is one of _G11_AFTER (the letter ends its clause: 'C please')
    head, led, ends = [True] * (n + 1), [False] * (n + 1), [True] * (n + 1)
    for i, x in enumerate(lw):
        head[i + 1] = head[i] and (x in YES_WORDS or x in _G11_LEAD)
        led[i + 1] = led[i] or x in _G11_VERBS or x in _G11_NOUNS or x == "with"
    for i in range(n - 1, -1, -1):
        ends[i] = ends[i + 1] and lw[i] in _G11_AFTER
    chosen, named = set(), set()
    for i, (w, raw) in enumerate(toks):
        if len(raw) != 1 or raw.lower() not in "abcdef":
            continue
        cap, end = raw.isupper(), ends[i + 1]
        prev, prev2 = (lw[i - 1] if i else ""), (lw[i - 2] if i > 1 else "")
        after_verb = prev in _G11_VERBS or prev in _G11_NOUNS and prev2 in _G11_VERBS or \
            prev == "with" and prev2 in ("go", "going", "stick", "stay", "ok", "roll", "rolling")
        choice = head[i] and (end or cap and led[i] or lw[i + 1:i + 2] in (["because"], ["since"])) or \
            after_verb and (cap or end)
        if cap or choice:
            named.add(raw.upper())
            if choice:
                chosen.add(raw.upper())
    return chosen, named


# the gates whose answer acts (overwrites a file, kills, rescues, switches, publishes, spends or stops; G6 and G7 pick
# the ideas the tournament and the red team spend on): a reply that is not yet a decision is asked again there
# (_unsure)
_ACT_GATES = frozenset(("G2f", "G4", "G5", "G6", "G7", "G8b", "G9", "G11", "G12", "G13", "G14", "GB", "GX"))
_ASKING = re.compile(r"\s*(?:(?:or|and|but|so)\s+)?(?:should|shall)\b", re.I)
# a question without its question mark: an auxiliary before its subject ('do I kill I-003', 'is it time to stop', 'is
# 300 enough', 'am I done'; not 'will do', 'would like B', 'is fine', 'do it'), or what / how / why before a word that
# is no subject ('what does reframe cost', "what's next"; not 'what we have is enough'); a request ('could you publish
# everything') is none
_QUESTION = re.compile(r"\W*(?:(?:or|and|but|so)\s+)?(?:(?:do|does|did|is|are|was|were|can|could|would|will|shall|"
                       r"should|am|has|have)\s+(?:i|we|"
                       r"you|it|they|he|she|this|that|there|the|my|our|your|[IEQ]-\d+|\d+|(?-i:[A-F]))\b|(?:what|how|"
                       r"why(?!\s+not\b))(?:'s|'re|\s+(?!(?:i|we|you|it|they|he|she|this|that|the|a|an|my|our|your)\b)"
                       r"\w))", re.I)
_HEDGE = re.compile(r"\b(?:maybe|perhaps|almost|prob(?:ably)?\b(?!\s+not\b)|sort\s+of|(?<!the\s)(?<!this\s)"
                    r"(?<!what\s)(?<!that\s)kind\s+of|kinda|sorta|more\s+or\s+less)\b", re.I)
_SOFT_HEDGE = re.compile(r"\b(?:maybe|perhaps)\b|\bmostly\W*$", re.I)
_AFTERWORDS = frozenset(("though", "tho", "anyway", "anyways"))
_HEDGE_LAST = re.compile(r"\b" + _NOT_SURE + r"\b|\b(?:unsure|idk|dunno|no\s+idea|(?:don't|dont|do\s+not)\s+know|"
                         r"let\s+me|(?:i|we|he|she|they|user|client|team|boss|manager|legal|but)\s+(?:\w+\s+)?"
                         r"(?:needs?|wants?|has|have)\s+to\s+(?:double[\s-]?)?(?:check|confirm|verify|review)|"
                         r"(?:i|we)\s+(?:think|guess|believe|suppose|assume)\s+(?:he|she|they|the\s+\w+|"
                         r"(?-i:[A-Z][a-z]+))\s+(?:wants?|meant|means)|(?:kindly|please)\s+(?:advise|confirm\s+(?:that|"
                         r"whether|if)))\b", re.I)
# a precondition in a clause that names no idea ID ('tell me the cost first', 'check with legal first', 'after you
# show me the numbers'; not 'confirm I-004 first'); bounded, so a flood of `check` stays linear
_FIRST = re.compile(r"\b(?:(?:check|confirm|verify|tell|show|send|give|explain)\w*\s[^.;!?\n]{0,200}?\b(?:first|1st)|"
                    r"after\s+(?:you|we|i)\s+(?:\w+\s+)?(?:tell|show|send|give|explain|see|read|check|confirm|"
                    r"verify)\w*|(?:tell|show|give)\s+(?:me|us)\s+(?:the\s+|what\s+(?:it|this|that)\s+)?(?:cost|price|"
                    r"estimate))\b", re.I)  # 'yes but tell me the cost 1st', 'go, but tell me the cost'
# a modal before an action word ('I might kill I-003', 'it may have passed')
_MODAL = re.compile(r"\b(?:i|we|it|you|they)\s+(?:might|may|could)\s+(?:(?:have|just|also|well|still)\s+)*(\w+)", re.I)
# a reply that stops mid-sentence ('Change the security goal to', 'I wrote four ideas and then Sam called and'), unless
# `to` ends an elliptic phrase ('happy to', 'if you want to')
_CUT_OFF = re.compile(r"\b(?:to|the|and|or|but|should|must|would|than|because)[^\w\n]*\Z", re.I)
_ELLIPTIC_TO = frozenset(("happy", "glad", "have", "has", "had", "need", "needs", "want", "wants", "love", "like",
                          "ought", "going", "got", "able", "agreed", "meant", "supposed", "used", "allowed"))
# an action put off to a time ('publish tomorrow', 'kill it next week'; not 'as soon as possible')
_LATER = re.compile(r"\b(?:tomorrow|tonight|(?<!as\s)soon(?!\s+as\s+(?:possible|you\s+can|we\s+can))|eventually|"
                    r"next\s+(?:week|month|time|sprint)|at\s+some\s+point|in\s+"
                    r"a\s+(?:bit|while)|on\s+(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday))\b", re.I)
# G12: the words that reject the ADR numbers after them
_G12_REJECT = frozenset(("reject", "rejected", "except", "but", "not", "no", "drop", "without"))
# G9: the words of the K6 kill a MISSED sets off ("Missed, but don't kill it")
_KILL = frozenset(("kill", "killing", "killed", "drop", "dropping", "dropped", "discard", "scrap"))
# G9: a MISSED beside words that keep the idea ('missed, but keep it', 'missed, just retest it', "I'd rather not lose
# the idea") is asked again
_KEEP_IDEA = re.compile(r"\b(?:(?:keep|keeping|rescue|save|park)\s+(?:it|this|that|them|the\s+idea|[IEQ]-\d+)|re-?test|"
                        r"re-?run\w*|alive|(?:run|test|try)\w*\s+(?:\w+\s+){0,2}again|not\s+lose|n't\s+lose)\b", re.I)
# a question put as a request: 'would you call it passed'
_OPINION = re.compile(r"\W*(?:would|could|do|will)\s+you\s+(?:call|consider|say|count|rate|judge|think|reckon|deem)\b",
                      re.I)
_SELF_FIX = re.compile(r"\b(?:wait\W+no|no\W+wait|i\s+meant)\b|\w\W+(?:never\s*mind|scratch\s+that)\b|"
                       r"\w[,;-][^\S\n]*(?:no|nope)[^\S\n]*[,;:-]+[^\S\n]*(?:[IEQ]-\d|\d|(?-i:[A-F])\b|\b[b-f]\b)|"
                       r"\w[^\S\n]*[-–—,;][^\S\n]*(?:(?:but|no)[^\S\n]+)?wait(?:[^\S\n]*[-–—,;:]+[^\S\n]*|"
                       r"[^\S\n]+(?!(?:for|until|till)\b))\w", re.I)  # 'done, wait one more'; not 'wait until Friday'
# an echo its answer narrows ('kill I-003 and I-007? Hmm, only I-003') and a reply that may be sarcasm ('why not
# throw good money after bad', an eye-roll)
_NARROWED = re.compile(r"\?[^\S\n]*(?:(?:hmm+|hm|well|ok|okay|yes|yeah|no)\W+){0,2}(?:only|just)\W+(?:[IEQ]-\d|\d|"
                       r"(?-i:[A-F])\b)", re.I)
_SARCASM = re.compile("\U0001F644|\\bwhy\\s+not\\b|\\byeah,?\\s+right\\b", re.I)
_CONDITION = re.compile(r"\b(?:if(?!\s+(?:at\s+all|ever|anything)\b)|unless|in\s+case|(?:as|so)\s+long\s+as|pending|"
                        r"subject\s+to|awaiting|contingent\s+(?:on|upon)|depend(?:ing|ent)\s+(?:on|upon)|(?<!as\s)"
                        r"provided|providing|assuming|on\s+condition|only\s+(?:when|after)|(?<!at\s)(?<!least\s)"
                        r"(?<!most\s)once(?!\s+(?:again|or\s+(?:more|twice)|and\s+for\s+all)\b)|when\s+(?!(?:you|we|i)"
                        r"\s+(?:get|have|find)\s+(?:a\s+)?(?:chance|"
                        r"moment|minute|sec)|possible|convenient)(?![^.,;:!?\n]{0,120}?(?:\b(?:was|were|did|had|went|"
                        r"came|ran|got|saw|said|made|began|found|left|met|told)\b|(?<!\bis)(?<!\bare)(?<!\bbe)"
                        r"(?<!\bgets)(?<!'s)(?<!'re)\s\w+ed\b))(?=\w))\b", re.I)
# what a condition may govern: an idea ID, a number, a candidate letter or an action word
_GOVERNS = re.compile(r"\b(?:[IEQ]-\d+|\d+|kill\w*|keep\w*|rescue\w*|confirm\w*|clear|sav(?:e|ing)|drop\w*|restor\w*|"
                      r"pass(?:ed)?|miss(?:ed)?|inconclusive|publish\w*|switch\w*|runner|approv\w*|accept\w*|reject\w*|"
                      r"raise|stop\w*|continu\w*|reframe\w*|choose|pick|take|go)\b|(?-i:\b[A-F]\b)", re.I)


def _echo_unanswered(gid, said):
    """An echoed question that names what the gate acts on ('publish?', 'kill I-003?') whose next clause answers
    nothing: no yes leads it, it is no refusal or negation, and it names nothing the gate reads ('publish? @sam has to
    OK anything that goes in the repo')."""
    for (c, a), (n, _b) in zip(said, said[1:]):
        if not a or _REQUEST.match(c) or not _anchored(gid, c, _words(c)):
            continue
        w = _words(n)
        rest = [x for x in w if x not in _COURTESY and x not in _INTERJ]
        if not (_bare_no(w) or _negated(w) or not rest or rest[0] in YES_WORDS or _anchored(gid, n, w)):
            return True
    return False


# an and / then clause with its own subject and no modal is a remark on another action ('publish all, and we launch
# next week', 'publish all and then I present it tomorrow'), not the gate's action put off
_OWN_CLAUSE = re.compile(r"\b(?:and|then)\s+(?:then\s+)?(?:we|i|they|you|he|she)\s+(?!(?:will|shall|would|can|could|"
                         r"should|might|may|must)\b)", re.I)


def _unsure(text, act=True, gid=None):
    """Why a reply at an action gate is not yet a decision, or None: its last clause asks ('passed?', 'should I
    publish', 'do I kill I-003', 'what does reframe cost'; not interjections alone), it hedges ('maybe reframe',
    'almost passed', 'passed, sort of'; 'idk', 'not sure', 'let me think' or 'I need to check ... first' anywhere),
    it has not decided or holds off ('wait, stop', 'not decided yet: publish'), it corrects itself ('kill I-003, wait
    no, I-007', 'B - wait, C', 'B. Actually C', 'reject 3 (sorry, 4)', 'kill I-003 (no, I-007)'), it puts the action off
    to a time ('publish tomorrow'; a clause that names what gate `gid` acts on) or it sets a condition the kit cannot
    check ('publish the architecture if the tests pass', 'as long as', 'once', '...; otherwise stop'). A note after a
    colon or after because / since keeps its hedges and conditions ('rescue I-012: it could work if hospitals adopt
    it'), and `changes: ...` is a change list; a note in brackets or after ` # ` is read too ('raise to 300 (not
    sure)'), and so is a clause before the action ('idk, kill I-003') and the part before a colon that names no action
    ('Once legal has signed off: publish all'). A reply cut off mid-sentence asks at every gate. At G1, G2c and G10
    (not `act`), where the reply is the text of a correction, only a question asks, only maybe / perhaps hedge, and a
    condition is content."""
    s = text.rstrip()
    m = _CUT_OFF.search(s)
    lw = _words(s)[-1:] if s[-1:].isalpha() else []  # or ends in a clipped keyword ('accept 1 2, rej')
    if m and not (m.group(0)[:2].lower() == "to" and _words(s[:m.start()])[-1:] and
                  _words(s[:m.start()])[-1] in _ELLIPTIC_TO) or gid in _ANCHORS and lw and len(lw[0]) > 2 and \
            lw[0] not in _GRAMMAR.get(gid, ()) and any(a.startswith(lw[0]) for a in _ANCHORS[gid]):
        return "Your reply seems cut off: send the whole reply."
    if re.search(r"(?:^|[,.;:!(]|\s-)\s*or\s+(?:maybe\s+)?not\W*$", s, re.I):  # a take-back ('kill I-003. or not.')
        return "Your reply is not sure yet: reply once you have decided."
    if re.match(r"\s*changes?\s*:", text, re.I):
        return "Your reply is not sure yet: reply once you have decided." if _HEDGE_LAST.search(text) else None
    if act and (re.search(r"\b(?:don't|dont|do\s+not|doesn't|didn't|never|not)\s+(?:not|never)\b", text, re.I) or
                gid not in ("G4", "G5") and re.search(  # at G4 and G5 "can't not rescue I-012" rescues (_denies)
                    r"\b\w+n't\s+(?:not|never)\b|\bnever\s+(?:don't|do\s+not)\b|\bnot\s+that\s+\w+\s+(?:\w+n't|do\s+"
                    r"not)\b|\b\w+n't\s+say\s+not\b", text.translate(_QUOTES), re.I)):
        # "I don't not want", "I wouldn't not extend", "I didn't say not to publish"
        return "Your reply has a double negation: reply plainly with one of the replies above."
    bare = re.sub(r"\([^()?\n]*\)", " ", text)  # a bracket asks nothing ('raise to 400 (was 300)'; its hedge does)
    said = [(c, a) for c, a in _clauses(bare if _WORD.search(bare) else text)
            if not (_INTERJ | _AFTERWORDS).issuperset(_words(c))]  # 'publish all, not 100% sure though'
    last = said[-1] if said else ("", False)
    lines = [ln for ln in text.split("\n") if _WORD.search(ln)]
    # the part before a colon when it names an action ('rescue I-012: it could work if ...'), else the whole line; a
    # reason after because / since up to the next action ('keep I-003 because ... and kill I-007 next week')
    heads = [re.sub(r"\b(?:because|since|bc|cuz)\b(?:(?!\b(?:and|then)\s+(?:kill|keep|rescue|confirm|clear|save|drop|"
                    r"restore|publish|switch|approve|accept|reject|raise|stop|continue|reframe)\b).)*", " ", s,
                    flags=re.I | re.S) for ln in lines
             for s in re.split(r"[.!?;]", ln.split(":", 1)[0] if _GOVERNS.search(ln.split(":", 1)[0]) and not
                               _field_head(gid, ln.split(":", 1)[0]) else ln)]
    mid = bare[:bare.rfind(last[0])].rstrip().endswith(",") and re.match(
        r"\W*(?:is|was|are|were|has|had)\s+(?!(?:i|we|you|it|they|he|she|this|that|there)\b)", last[0], re.I)
    if last[1] and not (gid == "G1" and _REQUEST.match(last[0]) or gid in ("G2c", "G10", "G13") and _REQUEST.match(
            last[0]) and set(_words(last[0])) & _EDITS) or _QUESTION.match(last[0]) and not mid and not re.match(
            r"\W*d(?:o|id)\s+(?:it|that)\W*$", last[0], re.I) and not (
            _REQUEST.match(last[0]) and not _OPINION.match(last[0])) or act and _ASKING.match(last[0]) or \
            act and gid in _ANCHORS and gid != "G13" and _echo_unanswered(gid, said):
        return "Your reply ends with a question: answer it with one of the replies above."
    if act and any(_HEDGE_LAST.search(ln) for ln in lines) or any(
            (_HEDGE if act else _SOFT_HEDGE).search(h) or act and (_HEDGE_LAST.search(h) or any(
            _FIRST.search(c) and not ID_RE.search(c) for c, _a in _clauses(h)) or any(
            _GOVERNS.fullmatch(m.group(1)) for m in _MODAL.finditer(h))) for h in heads):
        return "Your reply is not sure yet: reply once you have decided."
    turn = re.compile(r"\W*(?:actually|on\s+second\s+thoughts?)\b", re.I)  # 'B. Actually C', 'A, actually B'
    cl = [c for h in heads for c, _a in _clauses(h)]  # 'kill I-003 and I-007 - actually no, just I-003'
    if any(_SELF_FIX.search(h) for h in heads) or (act or gid == "G1") and (
            any(turn.match(h) for h in heads[1:]) or any(
            turn.match(c) and _GOVERNS.search(" ".join(cl[i:i + 2])) for i, c in enumerate(cl) if i) or
                                                          _NARROWED.search(text) or any(
            (set(_words(a + b)) & _FIX_WORDS or re.match(r"\W*(?:no|nope)\W+(?:[IEQ]-\d|\d|(?-i:[A-F])\b)", a + b,
                                                            re.I)) and _note_turns(gid, a + b)
            for a, b in _NOTES.findall(text))):  # 'kill I-003 (no, I-007)'
        return "Your reply corrects itself: reply once more with only what you want."
    if act and any(_LATE_NO.fullmatch(c) and (i and not said[i - 1][1] and not _negated(_words(said[i - 1][0])) or
                                              not i and len(said) == 1 and gid != "G0v1")
                   for i, (c, _a) in enumerate(said)):
        # 'kill I-003\nwait not yet'; 'wait not yet' alone (the v1-run offer reads a lone 'not now' as its stop)
        return "Your reply puts the action off: reply once you have decided."
    if act and _SARCASM.search(text):
        return "Your reply may not mean what it says: reply plainly with one of the replies above."
    if (act or gid == "G1") and any(_LATER.search(_OWN_CLAUSE.split(c, 1)[0]) and (
            _anchored(gid, c, _words(c)) if gid in _ANCHORS else _GOVERNS.search(c)) or
                   re.match(r"\W*(?:(?:but|and|then)\s+)?(?:(?:(?:let's|let\s+us|we'll|i'll|we\s+will|i\s+will)\s+)?"
                            r"wait\s+(?:for|until|till)|"
                            r"(?:only\s+)?(?:after|until|till)\s+(?:the|a|an|we|you|i|they|legal|it|our|my|next))\b",
                            c, re.I) or re.search(r"(?<!\bis )(?<!\bare )(?<!\bwas )(?<!'re )(?<!'s )\bnot\s+(?:until|"
                                                  r"till|before|today|tonight)\b", c, re.I) or \
                   _NOT_YET.search(c) or re.match(
                       r"\W*(?:but|and|then)\b", c, re.I) and _LATER.search(re.sub(r"\bnext\s+time\b", " ", c,
                                                                                 flags=re.I)) and not
                   _OWN_CLAUSE.match(c, re.match(r"\W*", c).end())
                   for h in heads for c, _a in _clauses(h)):
        # 'wait for the results, then stop', 'wait, stop', 'not decided yet: publish', 'publish, after the board ...',
        # 'raise to 300 but not until Monday', 'raise to 300, just not today', 'raise to 300 but next week' ('...,
        # but next time ask me' is a remark)
        return "Your reply puts the action off: reply once you have decided."
    if act and any(":" in ln and not _GOVERNS.search(ln.split(":", 1)[0]) and re.search(
            r"\b(?:after|until|till|before)\b", ln.split(":", 1)[0], re.I) for ln in lines):
        return "Your reply puts the action off: reply once you have decided."  # 'After the board meeting: publish'
    if act and any(re.search(r"\botherwise\b", h, re.I) or _CONDITION.search(h) and _GOVERNS.search(h) for h in heads):
        return "Your reply sets a condition the kit cannot check: reply without one."
    return None


# ---------------------------------------------------------------- what a reply says (4.12)
# A reply is read in NFKC form without format characters (a fullwidth or zero-width-split `go` is `go`), and
# without what only wraps it: the lines it quotes ('> Reply `go` ...', a colleague's quoted words: 'Sam: "reject 3"',
# a quoted line after 'Maria wrote:'), `cc` lines, a greeting line that holds no answer ('Dear team,'; not 'Hi, B'),
# a sign-off block ('Regards,\nB. Kumar', '-- \nAhmed', 'ok thx - Ahmed'), a trailing ' # comment' or ' // comment',
# and the dictation slips 'know' for 'no' ('Know publishing please') and a spoken comma or period in a reply with no
# typed punctuation; at G4 and G5 'I dash 003' and 'kill I 003' are I-003. A reply of quoted lines alone is asked
# again. Every pattern is linear on a flood.
_GREETING = re.compile(r"\A[^\S\n]*(?:dear|hi|hello|hey|good[^\S\n]+(?:morning|afternoon|evening))\b(?:(?:[^\S\n]+|"
                       r"[^\S\n]*[,/][^\S\n]*)(?:team|all|everyone|there|folks|guys|colleagues|sir|madam|"
                       r"(?-i:[A-Z])[\w.'-]*))*[^\S\n]*(?:[,:!.][^\S\n]*)?\n", re.I)
# an email closing line before the sign-off, or in its place ('Looking forward to the results.', 'Thanks in advance!')
_CLOSING = (r"(?:looking[^\S\n]+forward[^\S\n]+to|thanks?[^\S\n]+(?:you[^\S\n]+)?in[^\S\n]+advance|waiting[^\S\n]+for"
            r"[^\S\n]+your|have[^\S\n]+a[^\S\n]+(?:nice|good|great)[^\S\n]+(?:day|week|weekend|one|evening))\b[^\n]*")
_SIGNOFF = re.compile(r"(?:\n[^\S\n]*" + _CLOSING + r"(?=\n))?\n[^\S\n]*(?:" + _CLOSING + r"|--[^\S\n]*(?=\n)|"
                      r"(?:best|kind|warm|warmest|many)[^\S\n]+(?:regards|wishes|"
                      r"thanks)|regards|best|"
                      r"cheers|sincerely|yours(?:[^\S\n]+(?:truly|sincerely|faithfully))?|thanks(?:[^\S\n]+(?:and|&)"
                      r"[^\S\n]+regards)?|thank[^\S\n]+you|sent[^\S\n]+from[^\S\n]+my[^\S\n]+\w+)[^\S\n]*(?:[,.!]"
                      r"[^\S\n]*)?(?:\n[^\S\n]*(?-i:[A-Z])[\w.'-]*:?(?:[^\S\n]+(?:(?-i:[A-Z])[\w.'-]*|of|and|&|at|the|"
                      r"for|[-|/:]|\+?\d[\d().-]*))*[^\S\n]*[,.]?){0,4}\Z", re.I)  # also 'Mobile 050 123 4567'
# a note (' # ...', ' // ...' or in brackets) that turns the answer stays in the reply and is read: a refusal or
# correction word beside what the gate acts on ('publish all # not the proposal', 'raise to 300 (no, 250)', 'ok (not
# 3)', 'approve (switch to B)', 'raise to 300 (make it 250)', '# oops, only the architecture'), and a hedge anywhere
# ('raise to 300 (not sure)', 'go # idk'); at G0, G1, G2c and G10 any refusal or correction word turns it
_TURN = frozenset(("no", "not", "never", "nope", "except", "excluding", "without", "instead", "rather", "actually",
                   "wait", "reject", "switch", "cancel", "skip", "sorry", "oops", "correction", "mean", "meant", "make",
                   "or", "just", "only"))
_GO_ON = frozenset(("go", "proceed", "continue", "raise", "stop"))  # at any gate ('stop (no, continue)')
# the words of a note that corrects the answer (_unsure), and the notes: in brackets, or after ' # ' / ' // '
_FIX_WORDS = frozenset(("sorry", "oops", "correction", "mean", "meant", "make", "or", "instead", "actually",
                        "rather"))
_NOTES = re.compile(r"\(([^()\n]*)\)|(?<=\S)[^\S\n]+(?:#|//)[^\S\n]([^\n]*)")
# a clause that has not decided or holds the action off ('I have not decided yet', 'wait', 'hold on'; a bare 'not
# yet' refuses)
# a late 'not yet' / 'not now' (after wait / hold on) after an action clause puts the action off
_LATE_NO = re.compile(r"\W*(?:(?:wait|hold\s+on|hang\s+on)\W+)?not\s+(?:yet|now)\W*", re.I)
_NOT_YET = re.compile(r"\bundecided\b|\bno\s+decision\b|\bnothing\s+(?:was\s+|is\s+)?decided\b|\b(?:get|come|revert)\s+"
                      r"back\s+to\s+(?:you|u)\b|(?:\bnot|n't)\s+"
                      r"(?:\w+\s+){0,2}(?:decid\w*|made\s+up)\b|^\W*(?:(?:please|just|ok|but|so|and|actually)\W+)?"
                      r"(?:(?:wait|hold\s+on|hang\s+on)(?:\W+(?:a|one)(?:\s+more)?\s+(?:sec|second|moment|minute|"
                      r"min))?|give\s+me\s+(?:a|one)(?:\s+more)?\s+(?:sec|second|moment|minute|min))\W*$", re.I)
# the user's own words after a label (`changes:`, `rescue <ID>:`, a G0 `topic:`) are read like a whole reply (4.12): a
# take-back, a deferral, a relayed answer or a pointer to words the kit cannot see asks again; a question, a hedge, a
# condition that leads a clause and pointer words alone ('changes: fix it') make the reply no documented form
# 'second thoughts' (or '2nd', 'second-thoughts') is a take-back as the user's own words: 'on second thought', a
# first-person subject with up to four words between ("I'm having", "we've had", 'I kinda have', 'I got'), 'me having',
# 'having', 'had', 'getting' or 'got' that leads a clause (also after 'but', 'and', 'so'), or all a clause or line says
# at the end ('I-003. second thoughts'); not 'let users have second thoughts before paying'. 'changed my mind',
# 'second guessing', 'oops' and 'cancel that' (not 'cancel that subscription flow') take back too
_TAKEN_BACK = re.compile(r"\b(?:never\s*mind|nvm|jk|j/k|(?:just\s+)?kidding|scratch\s+that|forget\s+(?:it|that|this)|"
                         r"ignore\s+(?:it|that|this)|(?:disregard|strike|cancel|belay)\s+(?:it|that|this)"
                         r"(?![^\S\n]+\w)|changed\s+(?:my|our)\s+mind|second[- ]guess\w*|oops)\b|(?:^\W*|\bon\s+|"
                         r"(?:(?:^|[^\w\s']|\n)[^\S\n]*(?:(?:\w+ly|really|still|now|also|just)\s+)?|"
                         r"\b(?:but|and|so)\s+)(?:having|had|getting|got)\s+(?:(?:some|a)\s+)?|"
                         r"\bme\s+(?:having|getting)\s+(?:(?:some|a)\s+)?|"
                         r"\b(?:i|we)(?:['’](?:ve|m|re|d)|m|ve)?\s+(?:(?:\w+ly|really|still|now|also|just|kinda|do|"
                         r"did|am|are|have|had|having|got|get|getting|keep|been|starting|started|to|a|some|serious)"
                         r"\s+){0,4})"
                         r"(?:second|2nd)[\s-]+thoughts?\b|(?:[^\w\s']|\n)[^\S\n]*(?:second|2nd)[\s-]+thoughts?\W*$",
                         re.I)
_DEFERRED = re.compile(r"\b(?:tbd|tba|tbc|to\s+follow|to\s+be\s+(?:decided|confirmed|determined)|(?:will|'ll|shall)"
                       r"\s+(?:\w+\s+)?(?:send|share|follow|forward|get\s+back|write|tell)|waiting\s+(?:on|for)|"
                       r"(?:haven't|havent|hasn't|have\s+not|has\s+not|didn't|did\s+not|not)\s+(?:yet\s+)?(?:read|"
                       r"seen|looked|checked|reviewed|finished))\b|(?:^\W*|\b(?:i|we)(?:'m|'re|\s+am|\s+are)?\s+)"
                       r"still\s+(?:reading|reviewing|going\s+through)\b|^\W*(?:later|tomorrow|soon|next\s+week)\b|"
                       r"^\W*(?:pending(?:\s+\w+(?:['’-]\w+)*){0,3}|coming\s+soon|(?:\w+\s+){0,2}(?:is\s+)?"
                       r"(?:still\s+)?pending)\W*$|"
                       # a label body that is only a status ('changes: to come', 'in progress', 'still thinking',
                       # 'halfway through reading', 'on hold until Friday', 'I will decide tomorrow'), not 'still
                       # missing the budget table'
                       r"^\W*(?:to\s+come|(?:work\s+)?in\s+progress|wip|(?:i'm\s+|i\s+am\s+|we're\s+|we\s+are\s+)?"
                       r"(?:still|halfway|half\s+way|partway|midway)(?:\s+through)?\s+\w+ing|on\s+hold(?:\s+until\s+"
                       r"\w+)?|under\s+review|(?:i|we)(?:'ll|\s+will)\s+decide(?:\s+\w+){0,2})\W*$", re.I)
    # 'pending legal', 'pending the board'; not 'pending approvals are handled by HR'
# a longer 'X is still pending' status ('the legal review is still pending', 'the decision is still pending on my
# side') in a reason or note; not after `changes:`, where 'note that the pilot results are still pending' is content
_DEFERRED_WIDE = re.compile(r"^\W*(?:\w+\s+){0,6}(?:(?:is|are)\s+)?(?:still\s+)?pending"
                            r"(?:\s+(?:on|at)\s+(?:my|our|the)\s+(?:side|end))?\W*$", re.I)
_RELAYED =re.compile(r"\b(?:says?|said)\s+(?:no|yes|ok|so|not)\b(?!\s+to\b)|\bsee\s+(?:the\s+|my\s+|our\s+|his\s+|"
                      r"her\s+)?"
                      r"(?:e-?mail|mail|message|doc|thread|slack|notes?|comments?|attachment|attached|chat|ticket|"
                      r"above|below)\b|\bper\s+(?:the\s+|my\s+|our\s+)?(?:e-?mail|call|meeting|chat|discussion|"
                      r"conversation|talk|thread|notes)\b|^\W*(?:(?:see|in|per|as)\s+)?(?:the\s+|my\s+|our\s+)?"
                      r"attach(?:ed|ment)(?:\s+\w+)?\W*$", re.I)  # 'attached', 'in the attached file'


def _label_doubt(text, weak=True):
    """Why the user's own words after a label are no decision yet (above), or None; without `weak`, only a take-back,
    a deferral and words the kit cannot see (the rest of a `changes:` text is read back)."""
    t = _reading(text or "")[0].translate(_QUOTES)
    if _TAKEN_BACK.search(t) or _SELF_FIX.search(t):
        return "Your reply takes itself back: reply once more with only what you want."
    if _DEFERRED.search(t) or _NOT_YET.search(t) or weak and _DEFERRED_WIDE.search(t):
        return "Your reply puts the decision off: reply once you have decided."
    if _RELAYED.search(t) or _ELSEWHERE.search(t) or _COLLEAGUE.search(t):
        return "Your reply points to words the kit cannot see: write them in the reply."
    if not weak:
        return None
    if "?" in t:
        return "Your reply asks a question: answer it with one of the replies above."
    if _HEDGE_LAST.search(t) or _SOFT_HEDGE.search(t):
        return "Your reply is not sure yet: reply once you have decided."
    if any(_CONDITION.match(re.sub(r"^\W*(?:only\s+)?", "", c, flags=re.I)) or re.search(r"\botherwise\b", c, re.I)
           for c, _a in _clauses(t)):
        return "Your reply sets a condition the kit cannot check: reply without one."
    w = _words(t)
    if w and all(x in _VAGUE or x in _POINTER or x in _EDIT_VERBS or x in _CHANGE_ASKS for x in w):
        return "Your reply does not say what to change: say what is wrong and what it should be."
    return None


def _note_turns(gid, note):
    """A note that turns the answer (above)."""
    w = _words(note)
    if _HEDGE_LAST.search(note) or _HEDGE.search(note):
        return True
    return any(x in _TURN or x.endswith("n't") for x in w) and (
        gid not in _ANCHORS or gid in ("G1", "G0v1") or any(
            x in _ANCHORS[gid] or x in _GO_ON or ID_RE.fullmatch(x) for x in w) or
        gid in ("G12", "GB") and any(x.isdigit() for x in w) or
        gid in ("G11", "G13") and bool(re.search(r"\b[A-F]\b", note)))


def _drop_notes(gid, rx, t):
    """`t` without what `rx` finds, except a note in brackets that turns the answer (above)."""
    return rx.sub(lambda m: m.group(0) if m.group(0)[:1] in "([" and _note_turns(gid, m.group(0)[1:-1]) else " ", t)


# a line of someone else's quoted words: 'Sam: "reject 3"', "Maria (Slack) said: 'publish'", or a quoted line after
# 'From: ...' or '... wrote:'
_QUOTE_LINE = re.compile(r"[^\S\n]*(?:\w[^\n:]{0,40}:[^\S\n]*)?['\"\u2018\u201c].*['\"\u2019\u201d][^\S\n]*$")
_SPEAKER = re.compile(r"[^\S\n]*(?-i:[A-Z])[\w.'-]*(?:[^\S\n]+[\w.'-]+){0,2}[^\S\n]*(?:\([^()\n]{1,20}\))?(?:[^\S\n]+"
                      r"(?:said|says|wrote|writes))?[^\S\n]*:")
_SPEAKER_MARKED = re.compile(r"[^\S\n]*(?:from[^\S\n]+)?(?-i:[A-Z])[\w.'-]*(?:[^\S\n]+[\w.'-]+){0,2}[^\S\n]*"
                             r"(?:\([^()\n]{1,20}\)|[^\S\n]+(?:said|says|wrote|writes))[^\S\n]*:", re.I)
_OWN_LABEL = re.compile(r"[^\S\n]*(?:me|my\s+\w+|decision|answer|reply|reason|note|notes|except|exception|choice|"
                        r"result|verdict|final\s+answer|letter|option|pick|selection)[^\S\n]*:", re.I)


def _own_label(ln, gid):
    """A line led by the user's own label ('Decision: kill I-003', 'Except: the proposal', 'Handoff: ce'), no
    speaker's name."""
    w = _words(ln.split(":", 1)[0])
    return bool(_OWN_LABEL.match(ln)) or bool(w) and (w[0] in _ANCHORS.get(gid, ()) or w[0] in FIELDS.get(gid, {}))


_QUOTE_HEAD = re.compile(r"[^\S\n]*(?:from[^\S\n]*:.*|.{1,60}\bwrote[^\S\n]*:[^\S\n]*)$", re.I)
# the time of a chat line ('[17:01] me: go', '[5:00 PM] Joe: ...', '[29/09/26, 17:00:12] Sam: ...'): it goes, and a line
# of it led by someone else's name is theirs, not the user's
_CHAT_TIME = re.compile(r"[^\S\n]*\[(?:\d{1,4}[./-]\d{1,2}[./-]\d{1,4},?[^\S\n]*)?\d{1,2}:\d{2}(?::\d{2})?"
                        r"(?:[^\S\n]*[AaPp]\.?[Mm]\.?)?\][^\S\n]*")
_ME_LABEL = re.compile(r"[^\S\n]*(?:me|my\s+(?:answer|reply|decision))[^\S\n]*:", re.I)
# the words of an own line that only agrees with someone else's ('me: yes', 'me: +1', 'agreed, rest ok')
_AGREE = YES_WORDS | frozenset(("same", "rest", "too", "ditto", "exactly", "true"))


# a markdown checkbox ('- [x]', '1. [ ]', 'a. [x]', '(2) [ ]', '100. [x]', '[]', '[-]') or a ballot box
_BOX = re.compile(r"^[^\S\n]*(?:(?:[-*+\u2022]|\(?(?:\d{1,4}|[a-zA-Z])[.)])[^\S\n]+)?(?:\[([^\S\n]*|[xX-])\]|"
                  r"([\u2610-\u2612]))[^\S\n]*", re.M)


def _box_on(groups):
    """A ticked box: [x], [X] or a ballot box with a tick or cross."""
    return groups[0] in ("x", "X") or groups[1] in ("\u2611", "\u2612")


def _unwrap(text, gid=None):
    """(`text` without what only wraps the reply (above), whether the reply is quoted lines alone, or why it is not
    read: a list of boxes none of which is ticked)."""
    t = "\u2026".join(re.sub("[^\xb5\xb2\xb3\xb9\u2070-\u209f]+", lambda m: unicodedata.normalize("NFKC", m.group(0)),
                              p) for p in (text or "").replace("\xb4", "'").split("\u2026"))
    t = "".join(c for c in t if unicodedata.category(c) != "Cf").strip()
    closed = set(x.lower() for x in re.findall(r"</([A-Za-z][A-Za-z0-9]*)[^\S\n]*>", t))
    t = re.sub(r"</?([A-Za-z][A-Za-z0-9]*)(?:[^\S\n][^<>\n]{0,200})?(/?)>", lambda m: "" if m.group(2) or
               m.group(1).lower() in closed or m.group(1).lower() in ("br", "hr") else m.group(0), t)  # '<p>go</p>'
    boxes = [m.groups() for m in _BOX.finditer(t)]
    if boxes and not any(_box_on(b) for b in boxes):
        return t, "Your reply ticks no box: reply with only what you want."
    if boxes:  # '- [x] kill I-003\n- [ ] kill I-007': the ticked lines are the reply, without their boxes
        t = "\n".join(_BOX.sub("", ln) for ln in t.split("\n") if not _BOX.match(ln) or _box_on(
            _BOX.match(ln).groups()))
    elif len(set(ln.lstrip()[:1] for ln in t.split("\n") if ln.strip() and unicodedata.category(
            ln.lstrip()[:1]) == "So")) > 1:  # 'U+2705 kill I-003\nU+2B1C kill I-007': which of them is ticked?
        return t, "Your reply marks its lines with signs I cannot read as ticked or not: reply with only what you want."
    lines = t.split("\n")
    stamped = set(i for i, ln in enumerate(lines) if _CHAT_TIME.match(ln))
    if stamped:
        lines = [_CHAT_TIME.sub("", ln, 1) if i in stamped else ln for i, ln in enumerate(lines)]
        t = "\n".join(lines)
    mine = [i for i, ln in enumerate(lines) if _ME_LABEL.match(ln)]
    speaker = lambda ln: _SPEAKER.match(ln) and not _own_label(ln, gid)
    theirs = set(i for i, ln in enumerate(lines) if (mine and i < mine[-1] or i in stamped) and speaker(ln))
    quoted = theirs | set(i for i, ln in enumerate(lines) if _QUOTE_LINE.match(ln) and (
        gid in _ACT_GATES and gid != "G13" and (speaker(ln) or i and _QUOTE_HEAD.match(lines[i - 1])) or
        _SPEAKER_MARKED.match(ln)))
    kept = [ln for i, ln in enumerate(lines) if i not in quoted and not ln.lstrip().startswith(">")]
    if quoted and _words(" ".join(kept[:3]))[:1] and _words(" ".join(kept[:3]))[0] in NO_WORDS:
        kept = [ln for ln in lines if not ln.lstrip().startswith(">")]  # "Sam: 'publish all'\nno, ...": the no answers
    elif theirs:  # 'Mia: kill I-003\nme: yes': the yes takes up her words, read back; a text or record-only gate asks
        w = _words(re.sub(r"\+1\b", " agree ", " ".join(_ME_LABEL.sub(" ", ln, 1) for ln in kept)))
        if w and all(x in _AGREE for x in w):
            if gid not in READBACK_GATES or gid in ("G0", "G2c", "G10"):
                return t, "Your reply agrees with someone else's line: reply with your own answer in your own words."
            kept = [ln for ln in lines if not ln.lstrip().startswith(">")]
    only = len(kept) != len(lines) and not any(_WORD.search(ln) for ln in kept)
    if len(kept) != len(lines) and not only:
        t = "\n".join(kept).strip()
    m = _GREETING.match(t)
    if m and _WORD.search(t[m.end():]) and not (gid in _ANCHORS and any(
            x in _ANCHORS[gid] or ID_RE.fullmatch(x) or x.isdigit() or r in ("A", "B", "C", "D", "E", "F")
            for x, r in _tokens(m.group(0)))):  # 'Hi, B\nthanks': that line holds the answer
        t = t[m.end():].strip()
    m = _SIGNOFF.search(t)
    if m and _WORD.search(t[:m.start()]):
        t = t[:m.start()].rstrip()
    lines = t.split("\n")
    furn = r"[^\S\n]*(?:.{1,200}\bwrote[^\S\n]*:[^\S\n]*$|-{3,}|_{5,}|(?:from|subject|sent|to|date)[^\S\n]*:)"
    own = next((i for i, ln in enumerate(lines) if _WORD.search(ln) and not re.match(furn, ln, re.I)), len(lines))
    cut = next((i for i in range(own + 1, len(lines)) if re.match(furn, lines[i], re.I) and not re.match(
        r"[^\S\n]*(?:subject|to|date)[^\S\n]*:", lines[i], re.I)), None)
    if cut is not None:  # the user's answer above a quoted or forwarded message ('On Mon, Sam <s@x> wrote:')
        lines = lines[:cut]
    head = [i for i, ln in enumerate(lines) if re.match(r"[^\S\n]*(?:from|subject|sent|to|date)[^\S\n]*:", ln, re.I)]
    cc = lambda ln: re.match(r"[^\S\n]*b?cc\b", ln, re.I) and (":" in ln[:6] or len(ln.split()) <= 4)
    kept = [ln for i, ln in enumerate(lines) if not (cc(ln) or re.match(r"[^\S\n]*-{3,}", ln) or
                                                    len(head) > 1 and i in head)]  # 'cc: Sam', 'cc Maria', a header
    if (cut is not None or len(kept) != len(lines)) and any(_WORD.search(ln) for ln in kept):
        t = "\n".join(kept).strip()
    m = re.search("(?<=\\w)[^\\S\\n]+[-\u2013\u2014]{1,2}[^\\S\\n]*(?-i:[A-Z][a-z]+)\\.?[^\\S\\n]*\\Z", t)
    if m and _words(t[:m.start()]) and all(x in YES_WORDS or x in _COURTESY for x in _words(t[:m.start()])):
        t = t[:m.start()]  # 'ok thx - Ahmed'
    c = re.sub(r"(^|[.,;:!?\n]|[^\S\n][-–—]+(?=[^\S\n]))[^\S\n]*(?:sorry[^\S\n]+(?:for|about|it[^\S\n]+"
               r"took)\b[^.,;:!?\n]*|ugh+|finally|(?:i['’]m|i[^\S\n]+am)[^\S\n]+(?:so[^\S\n]+)?(?:tired|exhausted)|"
               r"i[^\S\n]+trust[^\S\n]+you)[^\S\n]*(?=[.,;:!?\n]|[^\S\n][-–—]+[^\S\n]|$)", r"\1", t, flags=re.I)
    if c != t and _WORD.search(c):
        t = c  # chatter beside the answer: 'go, sorry for the delay', 'confirmed, I trust you'
    t = re.sub(r"(?<=\S)[^\S\n]+(?:#|//)[^\S\n](.*)", lambda m: m.group(0) if _note_turns(gid, m.group(1)) or (
        gid in _ANCHORS and re.match(r"[^\S\n]*(?:\d|[IEQ]-\d)", m.group(1), re.I)) else "", t)
    t = re.sub(r"(^|[.,;:!?\n]|\b(?:done|ok|okay|yes|finished|approved?|confirmed?)\b)([^\S\n]*)know(?=[^\S\n]+"
               r"(?:(?:more|further)[^\S\n]+)?(?:publish\w*|changes?|seeds?|ideas?|handoff|corrections?)\b)",
               r"\1\2no", t, flags=re.I)
    if gid in (None, "G0", "G2c", "G10", "G13"):
        # a seed idea or a correction keeps its words ('the billing period'): a spoken comma or period goes only from
        # a reply of confirmations ('go ahead period', 'approve period')
        if not re.search(r"[,.;:!?]", t) and all(x in YES_WORDS or x in KEYWORDS or x in ("comma", "period", "full",
                                                                                         "stop") for x in _words(t)):
            t = re.sub(r"(?<![^\S\n])[^\S\n]+(?:comma|period|full[^\S\n]+stop)\b", "", t, flags=re.I)
        return t, only
    if not re.search(r"[,.;:!?]", t):
        t = re.sub(r"(?<=\S)(?<!\ba)(?<!\bthe)[^\S\n]+(comma|period|full[^\S\n]+stop)\b",
                   lambda m: "," if m.group(1).lower() == "comma" else ".", t, flags=re.I)
    if gid in ("G4", "G5"):
        t = re.sub(r"\b([IEQ])[^\S\n]*(?:dash|hyphen)[^\S\n]*(\d{3})\b", r"\1-\2", t, flags=re.I)
        t = re.sub(r"\b(kill|keep|rescue|confirm|clear|save|and)[^\S\n]+([IEQ])[^\S\n]+(\d{3})\b", r"\1 \2-\3", t,
                   flags=re.I)
    return t, only


# A reply written as the answer file reads as those fields ('{"choice": "C"}', 'choice: B', '--choice B',
# 'publish=false', 'confirm_flags: [I-004]', 'corrections: []', 'action=switch switch_to=C') when every line of it is
# pairs of the gate's own fields and every value reads, in full, as one the field takes ('kill: I-003 later' and
# 'publish: all?' are no field value); a text field (corrections, changes, a note) takes only an empty value unless
# another field stands beside it. false / no / off / 0 refuse.
_FIELD_ON = frozenset(("true", "yes", "y", "on", "1", "ok"))
_FIELD_OFF = frozenset(("false", "no", "n", "off", "0", "none", "null", "nothing"))
_FIELD_EMPTY = frozenset(("", "n/a", "na", "none", "nothing", "null", "-", "no", "nil"))
_NOPE = object()
_FIELD_SEP = re.compile(r"(?:[\s\[\]\"'`,;&+/]|\band\b)*", re.I)  # between the values of a list field


def _field_value(gid, k, v):
    """The value of field `k` read from `v` (text; a JSON value is left to the type check), or _NOPE."""
    if gid == "G14" and k == "publish" and isinstance(v, list) and all(isinstance(x, str) for x in v):
        v = ", ".join(v) or "none"  # '{"publish": ["arch"]}'
    if not isinstance(v, str):
        return v
    s = v.strip().strip("\"'`").strip()
    low = s.lower()
    bare = low.strip("[] ")
    typ = ANSWER_TYPES.get(gid, {}).get(k) or {}
    want = typ.get("type")
    want = want if isinstance(want, list) else [want]
    if k in ID_LISTS.get(gid, ()):
        ids = list(dict.fromkeys(_ids(s)))
        return ids if ids and _FIELD_SEP.fullmatch(ID_RE.sub(" ", s)) or bare in _FIELD_EMPTY else _NOPE
    if gid == "G12":
        got = re.findall(r"\d{1,4}|\ball\b", low)
        return ["all" if x == "all" else adr_key(x) for x in got] if got and _FIELD_SEP.fullmatch(
            re.sub(r"\d{1,4}|\ball\b", " ", low)) or bare in _FIELD_EMPTY else _NOPE
    if gid == "G14" and k == "publish":
        if not _FIELD_SEP.fullmatch(re.sub(r"[^\W_]+", " ", low)):
            return _NOPE  # 'all?', 'yes (after the board meeting)': the reader reads it
        w = [{"arch": "architecture", "adrs": "adr", "proposals": "proposal"}.get(x, x) for x in _words(low)
             if x not in ("and", "the")]
        if w and all(x in _FIELD_ON or x in ("all", "everything") for x in w):
            return True
        if not w or all(x in _FIELD_OFF for x in w):
            return False
        return list(dict.fromkeys(w)) if all(x in ("architecture", "adr", "proposal") for x in w) else _NOPE
    if "boolean" in want:
        return True if low in _FIELD_ON else False if low in _FIELD_OFF else _NOPE
    if "integer" in want:
        return int(low) if low.isdecimal() and len(low) <= 9 else _NOPE
    if "enum" in typ:
        x = "runner-up" if re.fullmatch(r"runner[\s_-]?up", low) else low
        return x if x in typ["enum"] else _NOPE
    if gid == "G9" and k == "result":
        return low.upper() if low in ("passed", "missed", "inconclusive") else _NOPE
    if k in ("choice", "switch_to"):
        return s.upper() if re.fullmatch(r"[A-Fa-f]", s) else _NOPE
    if k == "steal":
        m = re.fullmatch(r"([A-Fa-f])\s*:\s*(\S.*)", s)
        return [{"from": m.group(1).upper(), "element": m.group(2).strip()}] if m else _NOPE
    if "array" in want or k in ("chosen", "runner_up"):
        return _NOPE  # G3 ideas, G4 rescue, G8b: the gate reads these itself
    return None if bare in _FIELD_EMPTY else s


def _field_answer(gid, text):
    """The fields of a reply written as the answer file (above), or None."""
    fields = FIELDS.get(gid)
    if not fields or gid == "G0":
        return None
    t = re.sub(r"(?m)^[^\S\n]*`{3}[^\n`]*$", "", text).strip()
    if t[:1] == "{":
        try:
            obj = json.loads(t)
        except ValueError:
            return None
        if not isinstance(obj, dict):
            return None
        pairs = list(obj.items())
    else:
        names = "|".join(sorted(fields, key=len, reverse=True))
        at = re.compile(r"(?<![\w-])(?:--(%s)(?:[^\S\n]*=[^\S\n]*|[^\S\n]+)|(%s)[^\S\n]*[:=][^\S\n]*)" % (names, names),
                        re.I)
        pairs = []
        for ln in t.split("\n"):
            ms = list(at.finditer(ln))
            if not ms:
                if ln.strip(" \t,;{}"):
                    return None
                continue
            if ln[:ms[0].start()].strip(" \t,;{-*"):
                return None
            for m, nxt in zip(ms, ms[1:] + [None]):
                pairs.append(((m.group(1) or m.group(2)).lower(),
                              ln[m.end():nxt.start() if nxt else len(ln)].strip(" \t,;}")))
    if not pairs or any(k not in fields for k, _v in pairs):
        return None
    out = {}
    for k, v in pairs:
        v = _field_value(gid, k, v)
        if v is _NOPE:
            return None
        out[k] = v
    typ = ANSWER_TYPES.get(gid, {})
    text_only = all((typ.get(k) or {}).get("type") == ["string", "null"] and "enum" not in (typ.get(k) or {}) and
                    k not in ("choice", "switch_to", "result") for k in out)
    if text_only and t[:1] == "{" and gid in ("G2c", "G10", "G13") and len(out) == 1 and isinstance(
            out.get("corrections", out.get("changes")), str) and not re.fullmatch(
            r"\W*(?:none|no|n/?a|nothing|nil)?\W*", out.get("corrections", out.get("changes")), re.I):
        v = out.get("corrections", out.get("changes"))  # '{"corrections": "availability 99.9% not 99.5%"}'
        return {"action": "changes", "changes": v} if gid == "G13" else {"confirm": False, "corrections": v}
    if text_only and (any(v is not None for v in out.values()) or gid == "G13"):
        return None  # 'corrections: the users are nurses', 'changes: none': the gate reads the text itself
    if gid in ("G2c", "G10") and "confirm" not in out:
        out["confirm"] = not out.get("corrections")
    elif gid == "G11" and out.get("choice"):
        out.setdefault("accept_recommendation", False)
    elif gid == "G13" and not out.get("action"):
        out["action"] = "switch" if out.get("switch_to") else "changes" if out.get("changes") else \
            "approve" if "changes" in out else None
    elif gid == "GB" and out.get("raise_to") and "stop" not in out:
        out["stop"] = False
    return dict((k, v) for k, v in out.items() if v is not None)


# ---------------------------------------------------------------- the closed world (4.12)
# An answer an action gate would act on is taken only when every clause that names what the gate acts on (an anchor:
# a keyword or its synonym, a verb, a chosen letter, an item, and at G12 and GB a number) has no word outside the
# gate's grammar: its keywords and their synonyms, the yes / no vocabulary, courtesy and filler words, negations and
# quantity words (_COMMON, _G_WORDS). A word the reader does not know may turn the action around ('publish after the
# board meeting', 'publish the proposal as a draft'), so such a reply is asked again. Notes are read apart first:
# text in brackets, a reason after because / since / as <it, the, we ...> or before `so` ('Too much overlap so kill
# I-003'), a note after `<anchor>:` up to the next clause that names an anchor ('rescue I-012: nurses love it',
# 'reject 1: too costly, reject 3 too'), the text after a label ('Decision: kill I-003'), the reason after the IDs of a
# rescue or a kill ('kill I-007 its a copy of uber'), what a reframe is about (GX), a keyword someone else said (GX) and
# what follows the result (G9). A clause that names no anchor is a note; a hedge, a deferral, a condition, a
# self-correction or a question anywhere in the reply is asked again by _unsure, and a bare refusal refuses the clause
# before it (_read). At G4 and G5 only a clause with a verb is checked: an ID named without one is read by the gate
# ('I-003 is a duplicate, kill it').
_COMMON = YES_WORDS | NO_WORDS | NEG_WORDS | _BARE | _COURTESY | _INTERJ | _LEAD | frozenset((
    "i", "me", "my", "myself", "we", "us", "our", "you", "your", "he", "she", "him", "her", "his", "their", "it", "its",
    "it's", "this", "that", "these", "those", "them", "em", "they", "the", "a", "an", "all", "both", "each", "every",
    "everything", "any", "anything", "one", "ones", "other", "others", "rest", "remaining", "same", "either", "is",
    "are", "was", "were", "be", "been", "being", "am", "i'm", "i'd", "i'll", "i've", "we're", "we'll", "we'd", "we've",
    "you're", "that's", "there", "there's", "here", "here's", "do", "does", "did", "doing", "have", "has", "had",
    "will", "would", "shall", "should", "can", "could", "may", "might", "must", "let", "let's", "and", "also", "too",
    "as", "then", "so", "just", "only", "with", "for", "to", "of", "on", "in", "at", "by", "from", "about", "now",
    "still", "again", "already", "really", "very", "quite", "pretty", "want", "wants", "wanted", "like", "think",
    "guess", "feel", "believe", "reckon", "decided", "decide", "go", "going", "gonna", "wanna", "need", "needs",
    "prefer", "rather", "happy", "glad", "fine", "good", "great", "thank", "hi", "hello", "hey", "cheers", "right",
    "away", "ahead", "choice", "answer", "reply", "call", "decision", "final", "surely", "id", "ids", "idea", "ideas",
    "which", "mine", "ours", "yours", "own", "sounds", "looks", "look", "seems", "fair", "enough", "cool", "nice",
    "perfect", "done", "said", "say", "says", "suggested", "suggestion", "above", "below", "listed", "shown", "card",
    "run", "step", "thing", "things", "way", "sir", "madam", "folks", "guys", "team", "everyone", "request",
    "requested", "hereby", "anyway", "anyways", "instead", "though", "although", "basically", "simply", "ever",
    "even", "more", "less", "much", "many", "lot", "lots", "most", "time",
    "today", "please", "happy", "fine", "sure", "totally", "fully", "entirely", "completely", "definitely", "go",
    "exactly", "plus", "well", "either", "way", "am", "same", "etc", "list", "one", "whole", "lol", "haha", "reason",
    "point", "needful", "risky", "expensive", "costly", "cheap", "late", "slow", "hard", "easy", "worth", "useful",
    "bad", "better", "worse", "best", "worst", "suitable", "unsuitable", "feasible", "simple", "strict", "once",
    "soon", "asap", "possible", "provided"))
_G_WORDS = {
    "G0v1": "go extend extension extended extending proceed continue stop cancel run v1 keep going carry on call day "
            "pull plug wrap up architecture package full proposal both yes interested budget side end cost money "
            "processed arch true needful",
    "G1": "done finished finish completed complete filled fill written wrote write writing added add updated saved "
          "skip skipping skipped seeds seed file ideas idea list step section ready over page them in dusted idk nvm "
          "dunno now",
    "G2f": "restore restored restoring keep kept keeping leave context md context.md file original version changes "
           "state form content contents text wording docs doc repository repo readme "
           "change edits edit back undo revert reverted put roll discard as before framing mine undone new old "
           "current updated latest previous earlier one version",
    "G4": "rescue rescues rescued save saved saving confirm confirms confirmed clear clears cleared flag flags kill "
          "killed "
          "flagged shortlist single judge single-judge number both idea ideas these those",
    "G5": "kill killed kills keep kept drop dropped park parked candidate candidates stay stays k4 number both off "
          "these those",
    "G9": "passed pass missed miss inconclusive result probe test was it failed fail fails barely just narrowly "
          "clearly easily comfortably it's probe's test's total complete clear note mark marked record recorded "
          "considered consider deemed treated count counted called",
    "G11": "candidate option architecture letter suggestion suggested recommendation recommended default pick leader "
           "choose take use select stick stay steal go with going option whatever roll rolling switch to",
    "G12": "accept accepted accepting reject rejected approve approved drop keep adr adrs decision decisions number "
           "numbers rest others remaining except but three objection objections right correct look",
    "G13": "approve approved approval switch switching runner-up runner up architecture candidate option sign off "
           "signed choose pick take use select go with prefer stick instead",
    "G14": "publish published publishing copy copied copying architecture arch archs architectures adr adrs "
           "decisions decision records record proposal proposals handoff hand-off hand off none ce speckit spec kit "
           "superpowers openspec repository repo into docs folder items item package everything merge terms two three "
           "defer manually myself ourselves n apart than besides excluding minus including leave leaving out bar "
           "documents document files use give send seed seeds keep stay stays private here local locally",
    "GB": "raise raised cap budget limit requests request calls stop to max maximum new total make "
          "continue money spend spending set increase bump up extend lift higher finish finished complete completed "
          "max-calls",
    "GX": "reframe continue stop effort whole keep going carry on proceed plan current probe wait results result "
          "problem frame framing question scope planned course",
}
# the anchors of each gate: the words that name what it acts on (with G11 and G13 a chosen letter, with G12 and GB a
# number)
_ANCHORS = {
    "G0v1": frozenset(("go", "extend", "extension", "proceed", "continue", "stop", "cancel")) | YES_WORDS,
    "G1": frozenset(("done", "skip", "finished", "completed", "filled")),
    "G2f": frozenset(("restore", "restored", "keep", "revert", "reverted", "undo", "discard")),
    "G4": frozenset(("rescue", "save", "confirm", "clear")),
    "G5": frozenset(("kill", "keep", "drop")),
    "G9": frozenset(("passed", "missed", "inconclusive", "miss", "failed", "fail")),
    "G11": _G11_POINTS | YES_WORDS - _COURTESY,
    "G12": frozenset(("accept", "accepted", "reject", "rejected", "approve", "approved", "drop", "except", "ok", "okay",
                      "yes", "yep", "yeah", "lgtm", "agree", "agreed")),
    "G13": frozenset(("approve", "approved", "switch", "runner-up")),
    "G14": frozenset(("publish", "published", "publishing", "architecture", "adr", "adrs", "proposal", "handoff", "ce",
                      "speckit", "superpowers", "openspec")),
    "GB": frozenset(("stop",)),
    "GX": frozenset(("reframe", "continue", "stop")),
}
_GRAMMAR = dict((g, _COMMON | frozenset(w.split()) | _ANCHORS[g] | (_SAID if g == "G13" else frozenset()))
                for g, w in _G_WORDS.items())
# G12: a clause led by one of these excludes an ADR ('except SMS', 'but not Postgres'), unless a subject follows it
# ("but I can't think of a better channel")
_SUBJECTS = frozenset(("i", "we", "you", "it", "it's", "its", "they", "that", "that's", "this", "there", "there's",
                       "he", "she", "i'm", "i'd", "i'll", "i've", "we're", "we'll", "we'd", "you're", "they're",
                       "nobody"))
_REASON = re.compile(r"\b(?:because|since|cause|bc|cuz|as\s+(?:it|it's|its|this|that|they|we|i|he|she|you|the|there|"
                     r"our|my|nobody|no\s+one|otherwise|per|agreed|discussed)|so\s+that|in\s+order\s+to)\b", re.I)
_SO = re.compile(r"\b(?:so|therefore|hence|thus)\b", re.I)
_SENT_END = re.compile(r"(?:\.(?!\S)|[;!?\n])+")
_NOTE_OR_SIDE = re.compile(r"\([^()\n]*\)|\[[^\[\]\n]*\]|\b(?:from|on)\s+(?:my|our)\s+(?:side|end|part)\b", re.I)


def _known(gid, x, raw):
    """A word the gate reads: its grammar, a negation, an idea ID, a number, a letter (G11, G13)."""
    return x in _GRAMMAR[gid] or x.endswith("n't") or bool(ID_RE.fullmatch(x)) or any(c.isdigit() for c in x) or \
        gid in ("G11", "G13") and len(raw) == 1 and raw.lower() in "abcdef"


def _anchored(gid, c, w):
    """A clause (text c, words w) names what the gate acts on."""
    anchors = _ANCHORS[gid]
    if any(x in anchors for x in w):
        return True
    if gid == "G12":
        lead = [x for x in w if x not in ("and", "ok", "okay", "please")]
        return any(x.isdigit() for x in w) or bool(lead) and lead[0] in _G12_REJECT and lead[1:2] != ["no"] and \
            not set(lead[1:2]) & _SUBJECTS
    if gid == "GB":
        return any(x.isdigit() for x in w)
    return gid in ("G11", "G13") and bool(_g11_letters(c)[0]) and not any(
        x in NEG_WORDS or x.endswith("n't") for x in w)  # 'A is not suitable' names no choice


def _field_head(gid, head):
    """A head before a colon that is only the name of a list field ('publish:', 'kill:', 'reject:'): what follows is
    its value, not a note ('keep: true', 'stop: we lost the grant' keep their notes)."""
    w, f = _words(head.replace("_", " ")), FIELDS.get(gid, {})
    return 0 < len(w) <= 2 and all(isinstance(f.get(x), list) or gid == "G4" and x in ("confirm", "flags", "clear") or
                                   gid == "G14" and x in ("publish", "handoff") for x in w)


def _without_notes(gid, t):
    """The reply without the notes of the closed world (above) that a colon or a label marks."""
    out, at = [], 0
    for m in list(_SENT_END.finditer(t)) + [None]:
        sen, end = t[at:m.start() if m else len(t)], m.group(0) if m else ""
        at = m.end() if m else len(t)
        if ":" in sen:
            head, note = sen.split(":", 1)
            hw = _words(head)
            if _anchored(gid, head, hw) or any(ID_RE.fullmatch(x) for x in hw):
                keep = [c for c, _a in _clauses(note)]
                i = next((i for i, c in enumerate(keep) if any(x in _ANCHORS[gid] for x in _words(c))), len(keep))
                sen = head + (", " + ", ".join(keep[i:]) if i < len(keep) else "")
            elif len(hw) <= 3 and not any(x in NEG_WORDS or x.endswith("n't") for x in hw):
                sen = note  # a label: 'Decision: kill I-003', 'My answer: publish'
            else:
                sen = head
        out.append(sen + end)
    return "".join(out)


# GX: a keyword someone else said, or the synthesis verdict named as a thing ('The synthesis said STOP but I
# disagree', 'continue, the STOP was wrong')
_GX_CITED = re.compile(r"\b(said|says|suggested|suggests|recommended|recommends|wants\s+to)\W+(?:reframe|continue|"
                       r"stop)\b|\b(the)\s+(?:reframe|continue|stop)(?=\s+(?:was|is|call|verdict)\b)", re.I)


def _uncovered(gid, text, adrs=None):
    """Why an answer at an action gate is asked again under the closed world (above), or None; `adrs` (G12) holds
    the run's ADR numbers, and a clause whose numbers are none of them is a note ('costs add up across 40 wards')."""
    if gid not in _GRAMMAR or not text:
        return None
    t = _drop_notes(gid, _NOTE_OR_SIDE, text.translate(_QUOTES))  # a bracket, and 'approved from my side'
    t = re.sub(r"\bnothing\s+else\b", "only", t, flags=re.I)
    if gid in ("G4", "G5"):  # the reason after the IDs of a rescue or a kill, up to the next action; a deferral stays
        verbs = "rescue|save" if gid == "G4" else "kill|keep|drop"
        t = re.sub(r"(\b(?:%s)\b[^\w,;]*(?:(?:the\s+)?idea\s+)?%s)((?:(?!\b(?:and|then)\s+(?:%s|confirm|clear)\b)(?:"
                   r"[^\n;.!?]|\.(?=\S)))*)" % (verbs, _ID_LIST, verbs),
                   lambda m: m.group(0) if re.match(r"\W*(?:after(?!\s+all\b)|until|till)\b", m.group(2), re.I) else
                   m.group(1) if gid == "G4" or not ID_RE.search(m.group(2)) else m.group(0), t, flags=re.I)
    elif gid == "GB":
        t = _drop_notes(gid, _GB_CITED, t)
    elif gid == "GX":  # what the reframe is about, and a keyword someone else said
        t = re.sub(r"\breframe\b(?:[^\S\n]+(?:it|this|that|the\s+\w+))?[^\S\n]+(?:to|around|as|towards?|into|on|for|"
                   r"with|so)\b[^.;!?\n]*", "reframe", t, flags=re.I)
        t = _GX_CITED.sub(r"\1\2", t)
    t = _without_notes(gid, t)
    for c, _asks in _clauses(t):
        m = _REASON.search(c)
        if m:  # the reason, up to the next action ('keep I-003 as the backup and kill I-007 after the pilot')
            nxt = re.search(r"\b(?:and|then)\s+(?:%s)\b" % "|".join(map(re.escape, _ANCHORS[gid])), c[m.end():], re.I)
            c = c[:m.start()] + (" " + c[m.end() + nxt.start():] if nxt else "")
        m = _SO.search(c)
        if m and not _anchored(gid, c[:m.start()], _words(c[:m.start()])):
            c = c[m.end():]  # 'Too much overlap so kill I-003'
        toks = _tokens(c)
        w = [x for x, _r in toks]
        if gid == "G9":  # what follows the result is a note ('passed 8 of 10 paid')
            at = next((i for i, x in enumerate(w) if x in _ANCHORS["G9"]), None)
            toks, w = (toks[:at + 1], w[:at + 1]) if at is not None else (toks, w)
        if not _anchored(gid, c, w) or adrs and not any(x in _ANCHORS[gid] for x in w) and not any(
                adr_key(x) in adrs for x in w if x.isdigit()) and not set(w) & _G12_REJECT:
            continue
        odd = [r for x, r in toks if not _known(gid, x, r)]
        if odd:
            what = next((r for x, r in toks if x in _ANCHORS[gid]), None) or next(
                (r for x, r in toks if x.isdigit() or len(r) == 1 and r.isupper()), w[0])
            return "Your reply has words I cannot read next to `%s` (%s): reply in the words of the card, and put a " \
                   "reason in brackets (a comma ends a reason after `because`)." % (
                       what, ", ".join("'%s'" % x for x in odd[:3]))
    return None


def parse_reply(gid, text, ctx=None, why=None):
    """Structured fields from a free-text reply (terminal mode, --choice and hosts that fill only `reply`). A reply
    this reader finds unclear or contradictory fills no deciding field, so validate() asks the gate again; `why` (a
    list), when given, gets the sentence that says what was unclear. A paid, irreversible or budget action is read
    only from a clause that names it with no refusal, deferral or miss applying to it; a reply with no word in it
    ('?', '...', an emoji) fills nothing."""
    if gid == "G0":
        out = parse_kickoff(text)
        if ctx is not None and out.get("idea") and (out.get("mode") or ctx.mode) != "proposal":
            out["seeds"]["ideas"].append(out.pop("idea"))  # 'Idea: ...' in a standard run is a seed idea
        return out
    raw, only = _unwrap(text, gid)
    t, lo, hi = _reading(raw)
    low = t.lower()
    if t and not _WORD.search(t):
        return {}
    # text that is not the user's own answer (quoted lines alone, the card pasted back, a look-alike word), a
    # question, a hedge, a self-correction, a condition or a cut-off decides nothing, whatever form the reply takes
    doubt = only if isinstance(only, str) else "Your reply only quotes other text: reply with your own answer." if \
        only else \
        "Your reply only repeats the card: reply with your own answer." if _echo(ctx, gid, t) else \
        "Your reply holds pasted text (%r): reply with your own answer." % _pasted(t, gid).group(0).strip() \
        if _pasted(t, gid) else _lookalike(t) or (
            _unsure(t, gid in _ACT_GATES, gid) if t and (gid in _ACT_GATES or gid in ("G1", "G2c", "G10")) else None)
    if doubt:
        _say(why, doubt)
        return {}
    fields = _field_answer(gid, t) if t else None
    if fields is not None:  # the answer file's fields typed as the reply ('choice: B', '{"publish": false}')
        return _own_words(fields, raw, t, lo, hi)
    said = []
    out = _gate_reply(gid, t, low, ctx, said)
    if why is not None:
        why.extend(said)
    # the closed world: an answer the gate would act on is taken only when it has no word the gate does not read
    if out and not said and t and (gid != "G13" or out.get("action") in ("approve", "runner-up") or
                                   out.get("switch_to")):
        doubt = _uncovered(gid, t, set(os.path.basename(p)[:4] for p in _adr_files(ctx))
                           if gid == "G12" and ctx is not None else None)
        if doubt:
            _say(why, doubt)
            return {}
    return _own_words(out, raw, t, lo, hi)


# forms read as others ('ok w/o I-005', 'B b/c cheap', 'go w/ b', 'reject 2 n 3', and a contraction typed without its
# apostrophe: 'dont approve yet', 'cant', 'isnt'); the reader matches on a copy with them rewritten, never the text it
# stores ('A/B/C testing', French 'dont')
_READ_AS = re.compile(r"(?<![\w/])(?:(b/c)|(w/o))(?![\w/])|(?<![\w/])(w/)[^\S\n]*|\b(do|does|did|is|are|was|were|"
                      r"has|have|had|should|could|would|must|ca|wo)nt\b|"
                      r"(?<=\d)[^\S\n]+n[^\S\n]+(?=(?:[IEQ]-)?\d)", re.I)


def _reading(raw):
    """The copy of `raw` the reader matches on (_READ_AS rewritten), and for each of its characters where in `raw` it
    starts (lo) and ends (hi)."""
    out, lo, hi, pos = [], [], [], 0
    for m in _READ_AS.finditer(raw):
        new = "because" if m.group(1) else "without" if m.group(2) else "with " if m.group(3) else \
            m.group(4) + "n't" if m.group(4) else " and "
        out += [raw[pos:m.start()], new]
        lo += list(range(pos, m.start())) + [m.start()] * len(new)
        hi += list(range(pos + 1, m.start() + 1)) + [m.end()] * len(new)
        pos = m.end()
    out.append(raw[pos:])
    lo += list(range(pos, len(raw)))
    hi += list(range(pos + 1, len(raw) + 1))
    return "".join(out), lo, hi


def _own_words(out, raw, t, lo, hi):
    """`out` with every text it stores (a correction, a change, a note, a reason, a steal element) put back in the
    user's own words: the span of `raw` that the reading copy `t` (_reading) made it from."""
    if t == raw or not out:
        return out
    at = [0]  # the texts are stored in the order they were typed: the next one is looked for after the last one

    def whole(a, b):  # t[a:b] neither starts nor ends inside a rewritten form ('with' inside the copy of 'w/o')
        return not (a and lo[a] == lo[a - 1] and not t[a - 1].isspace()) and not (
            b < len(t) and lo[b] == lo[b - 1] and not t[b].isspace())

    def look(v, i):
        i = t.find(v, i)
        while i >= 0 and not whole(i, i + len(v)):
            i = t.find(v, i + 1)
        return i

    def own(v):
        if isinstance(v, list):
            return [own(x) for x in v]
        i = look(v, at[0]) if isinstance(v, str) and v else -1
        i = look(v, 0) if i < 0 and at[0] and isinstance(v, str) and v else i
        if i < 0:
            return v
        at[0] = i + len(v)
        s = raw[lo[i]:hi[i + len(v) - 1]]
        return s.strip() if v == v.strip() else s

    for k in ("corrections", "changes", "notes", "note", "why"):
        if k in out:
            out[k] = own(out[k])
    at[0] = 0
    for x in out.get("answers") or []:
        if isinstance(x, dict) and isinstance(x.get("a"), str):
            x["a"] = own(x["a"])
    for k in ("ideas", "cells"):
        at[0] = 0
        if isinstance(out.get(k), list):
            out[k] = own(out[k])
    at[0] = 0
    for x in [y for k in ("rescue", "steal") if isinstance(out.get(k), list) for y in out[k]]:
        if isinstance(x, dict):
            for k in ("reason", "element"):
                if k in x:
                    x[k] = own(x[k])
    return out


def _echo(ctx, gid, t):
    """The reply is a stretch of the gate's card pasted back (its own reply hint, or gates/<gate>.md)."""
    def norm(x):
        return " %s " % " ".join(_WORD.findall(x.translate(_QUOTES).lower()))
    said = norm(t)
    if len(said.split()) < (6 if "`" in t else 10):
        return False
    card = HOW_TO_REPLY.get(gid, "") + ("\n" + (ctx.read("gates/%s.md" % gid) or display(ctx, gid))
                                        if ctx is not None and ctx.run_dir else "")
    return said in norm(card)


def _lookalike(t):
    """Why a reply with a word that mixes Latin letters with Greek or Cyrillic look-alikes (`publish` with a Cyrillic
    i) is asked again."""
    odd = next((w for w in _WORD.findall(t) if re.search(r"[a-zA-Z]", w) and re.search("[\\u0370-\\u04ff]", w)), None)
    if odd:
        return "Your reply has a word with look-alike letters (%r): retype it in plain letters." % odd
    m = re.search(r"(?<![\w'-])[a-z](?:[^\S\n][a-z])+(?![\w'-])", t)  # 'g o', 'p u b l i s h'; not 'b c'
    return m and not set(m.group(0).split()) <= set("abcdefi") and \
        "Your reply has spaced-out letters (%r): retype the word." % m.group(0)[:30]


# text pasted from the run's documents, or a role label: no reply of the user's own ('Executive summary: ...',
# 'Candidate B (buy and integrate): ...', 'ADR 0003 Use SMS. Status: proposed', 'CONTEXT.md:', 'SYSTEM: ...')
_PASTED = re.compile(r"^[^\w\n]*(?:executive\s+summary|candidate\s+[A-F][^\S\n]*\([^()\n]{1,60}\)|adr[\s-]?\d{1,4}\b"
                     r"[^:\n]{0,80}\bstatus|context\.md|kill\s+criterion[^:\n]{0,40}|system|assistant|developer)"
                     r"[^\S\n]*:", re.I | re.M)


def _pasted(t, gid=None):
    """_PASTED's match, unless it is a section label before the user's own change request ('Executive summary: cut
    it to one page', 'Kill criterion: should be 15 of 40'; at G2c and G10 'System: the backend must be on-prem')."""
    m = _PASTED.search(t)
    first = re.split(r"[.;!?\n]", t[m.end():], maxsplit=1)[0] if m else ""
    rest = _words(first)
    own = r"executive\s+summary|kill\s+criterion" + (r"|system" if gid in ("G2c", "G10") else "")
    return m if m and not (re.match(r"[^\w\n]*(?:%s)" % own, m.group(0), re.I) and (
        set(rest) & (_EDITS | _WRONG) or _imperative(rest) or re.search(r"\btoo\s+\w+", first, re.I))) else None


# G1: the seeds file said done in other words, unless a later time is in the reply ('I will revert once completed')
_G1_DONE = re.compile(r"\b(?:completed|finished|filled(?:\s+in)?|written|wrote|added|updated|"
                      r"did(?=\s+(?:it|them|that)\b))\b", re.I)
_GB_CITED = re.compile(r"\([^()\n]*\)|\b(?:budget|limit)\s+of\s+\d+(?:\s+requests)?|\b(?:card|it)\s+says\s+(?:about\s+|"
                       r"around\s+|roughly\s+|~\s*)?\d+\s+more\b", re.I)
_G12_VERB = r"\b(?:accept|reject|approve|drop|keep)\w*"
_G12_NOTE = re.compile(r"\((?![^()\n]*%s)[^()\n]*\)|\b(?:because|since|cause|cuz)\b(?:(?!%s)(?:[^,;.!?\n]|\.(?=\S)))*"
                       % (_G12_VERB, _G12_VERB), re.I)
_G1_LATER = re.compile(r"\b(?:once|when|after|until|till|will|shall|going\s+to|gonna|soon|later|yet|tomorrow|"
                       r"tonight|first)\b|'ll\b", re.I)


def _cut_reason(ln):
    """G14: `ln` without its reason clause, keeping a handoff named after it ('publish all bc team needs it, ce')."""
    m = _REASON.search(ln)
    if not m:
        return ln
    h = re.search(r"[,;]\s*(?:hand\s*-?\s*off\W*)?(?:to\s+)?(?:ce|speckit|superpowers|openspec|none)\W*$", ln[m.end():])
    return ln[:m.start()] + (ln[m.end() + h.start():] if h else "")


# ---------------------------------------------------------------- G6, G7, G8a, G8b: the IDs a reply picks (4.12)
# A reply names the IDs it takes and the IDs it leaves out. An exclusion word leaves out the list of IDs right after it
# ('but not I-009', 'except I-002 and I-005', 'without I-004', 'other than I-011', 'drop I-009', 'no I-009', "I don't
# want I-009", 'all but I-004'); a contrast takes one ID and leaves out the other side ('I-007 instead of / rather than
# / in place of / over I-003', 'replace I-009 with I-012', 'swap I-011 for I-010'; at G8a `over` only ranks), and
# 'I-003? no.' leaves out I-003. IDs in brackets, on a line led by '# ', in a reason after an ID (after because / since
# / a colon / a spaced dash, up to the next clause an ID leads) and, at G8b, in a remark on a later idea ('I-003 is a
# close second') are notes: never taken, while their exclusions count. At G6 and G7 a reply that only leaves out or
# swaps, or says `ok`, `add`, `plus`, `as well`, `the rest`, `all` or `everything`, edits the suggested set. At G6, G7
# and G8b any other negation, an ID both taken and left out, `all` beside a list of IDs and leaving out an ID the
# suggested set does not hold ask again; at G8b so do a second idea and a runner-up or park the reader cannot place.
# The reader works on the reply with each run of blanks made one space, so every pattern stays linear.
_PICK_LIST = r"[IEQ]-\d+(?:(?: ?[,&/] ?| )(?:(?:and|or|nor) )?[IEQ]-\d+)*"
_PICK_OUT = re.compile(r"(?<!n't )(?<!nt )(?<!not )(?<!never )"
                       r"\b(?:(all|everything|any(?:one|thing)?) (?:but|except(?: for)?)|not|no|never|neither|nor|"
                       r"without|except(?: for)?|excluding|exclude|other than|apart from|minus|drop|remove|leave out|"
                       r"cut|scrap|ditch|bin|dismiss|discharge|reject|kill|discard|delete|lose|forget|take out|"
                       r"veto|nix|axe|strike|skip|no to|"
                       r"kick out|throw out|get rid of|(?:don't|dont|do not) (?:want|need|include|take|pick|choose)) "
                       r"(?:the )?(?:ideas? )?(" + _PICK_LIST + ")", re.I)
# one ID left out after it ('leave I-009 out', 'I-009 is out', '~~I-009~~'): a list here would swallow the picks
_PICK_OUT_POST = re.compile(r"(?:\bleave |~~ ?)?\b([IEQ]-\d+)(?: ?~~| (?:is |are )?(?:out|excluded|dropped|removed|"
                            r"cut)\b)", re.I)
_PICK_OVER = re.compile(r"\b([IEQ]-\d+) (?:instead of|rather than|in place of|in lieu of|(over|beats|outranks|"
                        r"(?:is )?better than)) (?:the )?(" + _PICK_LIST + ")", re.I)
_PICK_SWAP = re.compile(r"\b(?:replace|swap(?: out)?|exchange|trade) (" + _PICK_LIST + r") (?:with|for|by) (" +
                        _PICK_LIST + ")", re.I)
_PICK_NO = re.compile(r"\b([IEQ]-\d+) ?\?+ ?(?:no|nope|nah|not really)\b", re.I)
_PICK_RUNNER = re.compile(r"\brunner[- ]?up(?: ?:| is)?(?: ?\n)? ?(?:the )?([IEQ]-\d+)|"
                          r"\b([IEQ]-\d+) (?:as|for|is) (?:the |a |my |our )?runner[- ]?up\b", re.I)
_PICK_PARK = re.compile(r"\bpark(?:ed|ing)?(?: ?:)?(?: ?\n)? ?(?:the )?(" + _PICK_LIST + ")", re.I)
_PICK_NOTE = re.compile(r"\([^()\n]*\)|\[[^\[\]\n]*\]|^ ?(?:#+|//) [^\n]*", re.M)
_PICK_WHY = re.compile(_REASON.pattern + r"|:| [-\u2013\u2014]+ ", re.I)
_PICK_NEXT = re.compile(r"[,;] ?(?:(?:and|then|next|also|plus|or|but) )?(?=[IEQ]-\d)", re.I)
_PICK_SAID = re.compile(r"\b[IEQ]-\d+ (?:is|was|are|were|has|had|seems|looks|feels)\b[^,;.!?\n]*", re.I)
_PICK_REST = re.compile(r"\b(?:not|no|none|nothing|never)(?: of)?(?: the| any)? (?:others?|other ones|rest|else|"
                        r"more)\b", re.I)
# the words that keep the suggested set (G6, G7) or accept the suggestion (G8b), and those that add to the set
_PICK_BASE = frozenset(("ok", "okay", "yes", "yep", "yeah", "yup", "sure", "fine", "lgtm", "approve", "approved",
                        "accept", "accepted", "agree", "agreed", "good", "perfect", "correct", "confirm", "confirmed",
                        "suggested", "suggestion", "proposal", "proposed", "recommended", "recommendation", "default"))
_PICK_MORE = re.compile(r"\b(?:rest|add|adding|plus|also|too|additionally|as well|in addition)\b", re.I)
# 'not the rest', 'discharge the rest': the rest refused, not added (the reply's own IDs are the set)
_PICK_NO_REST = re.compile(r"\b(?:(?:not|no|none|nothing|never)(?: of)?|drop|cut|discharge|scrap|dismiss|remove|ditch|"
                           r"lose|bin|reject|kill|exclude|leave out|skip)(?: all)?(?: of)? (?:the )?rest\b", re.I)
# 'keep the rest', 'rest ok', 'the rest as suggested': the rest kept ('forget the rest', 'the rest can go' ask)
_PICK_REST_KEEP = re.compile(r"\b(?:keep|keeping|and|plus|with|add|include|take|all)(?: of)? (?:the )?rest\b|"
                             r"\b(?:the )?rest (?:too|also|as well|as is|as suggested|as proposed|ok|okay|fine|stays?|"
                             r"(?:is|are) (?:fine|ok|okay))\b", re.I)
# 'I-001-I-004', 'I-001 to I-004', 'I-001..I-004': a range, not its two ends
_PICK_RANGE = re.compile(r"[IEQ]-\d+(?:[^\S\n]*\.\.+[^\S\n]*|[-–—]|[^\S\n]+(?:to|through|thru)[^\S\n]+)"
                         r"[IEQ]-\d", re.I)
_PICK_ALL = frozenset(("all", "everything"))
# The word before an ID a reply takes, in its stretch of the reply (from the last separator or ID), is one the reader
# knows: a join or a rank ('I-003 and I-007', 'first I-003'), a take verb ('go with I-003', 'red-team I-004'), a hedge
# ('maybe I-003') or nothing. Filler words ('my pick is I-003', 'vote for I-003') are stepped over. Any other word
# ('veto I-009', 'I-008 trumps I-001', 'I-001 until I-004') may leave the ID out, so the reply is asked again: an ID
# next to a verb the reader does not know is not a pick. So is an ID a modal follows ('I-009 can go'), one after a
# negation in its stretch ("I don't like I-009", 'never fund I-009') or put away after it ('take I-009 off', 'put I-009
# aside'), and one after 'with' or 'back' that follows a word the reader does not know ('done with I-009', 'push back
# on I-009'; 'go with I-003' is a pick).
_PICK_SEP = re.compile(r"[,;:\n()>&/+.!?]")
_PICK_LEAD = frozenset((
    "and", "or", "then", "plus", "also", "next", "n", "with", "over", "after", "team", "first", "second", "third",
    "1st", "2nd", "3rd", "top", "gut", "pick", "picks", "picked", "choice", "choices", "vote", "votes", "voting",
    "winner", "fav", "fave", "favorite", "favourite", "favorites", "favourites", "best", "answer", "final", "finalists",
    "shortlist", "take", "takes", "taking", "took", "choose", "chooses", "chose", "chosen", "select", "selected",
    "keep", "keeps", "keeping", "include", "includes", "including", "add", "adds", "adding", "want", "wants", "prefer",
    "prefers", "preferred", "like", "go", "going", "advance", "back", "backing", "fund", "funding", "favor", "favour",
    "support", "admit", "forward", "pack", "greenlight", "elect", "ship", "ratify", "fast-track", "build", "make", "do",
    "try", "run", "bet", "put", "bring", "promote", "move", "use", "approve", "accept", "red-team", "redteam",
    "attack", "test", "stress-test", "pen-test", "cross-examine", "peer-review", "fuzz", "challenge", "scrutinize",
    "scrutinise", "probe", "review", "examine", "audit", "grill", "target", "check", "maybe", "probably", "perhaps",
    "prob", "likely", "think", "guess", "feel", "say", "says", "said", "suppose", "reckon", "believe", "meant", "mean",
    "actually", "definitely", "def", "clearly", "obviously", "really", "still", "just", "only", "ok", "okay", "yes",
    "yeah", "sure", "fine", "please", "pls", "plz", "now", "honestly", "personally", "tbh", "imo",
    # the same joins, ranks and 'only' in the languages the corpora saw
    "y", "e", "o", "u", "und", "oder", "et", "ou", "ve", "veya", "aur", "ya", "wa", "dann", "puis", "luego", "sonra",
    "solo", "nur", "seulement", "sirf", "sadece", "bas", "pehla", "doosra", "teesra", "primero", "segundo",
    "tercero", "erst", "zuerst", "d'abord", "\u00f6nce", "awal", "thani", "thalith", "\u548c", "\u53ea\u8981",
    "\u7b2c\u4e00", "\u7b2c\u4e8c", "\u7b2c\u4e09"))
_PICK_FILL = frozenset(("the", "a", "an", "my", "our", "is", "are", "was", "be", "as", "for", "on", "in", "to", "of",
                        "at", "it", "its", "it's", "idea", "ideas", "i", "i'd", "i'll", "i'm", "we", "we'd", "we'll",
                        "let's", "lets", "me", "us", "one", "would", "will", "gonna", "wanna"))
# after the ID, before the next separator: the ID put away ('take I-009 off the list', 'put I-009 on hold')
_PICK_AWAY = re.compile(r"[^,;:\n()>&/+.!?]{0,24}?\b(?:off|aside|hold|away)\b", re.I)
# right after a taken ID: a negation or a rejection ('I-009 is not good', 'I-009 no', 'I-009 won't work', a line
# ending 'I-009, no', group 2) or a modal asks at every pick gate; a remark ('I-009 is gone', group 1) asks where the
# IDs edit a suggested set
_PICK_MODAL = re.compile(r"\b[IEQ]-\d+(?: (?:(?:is|are|was|were)\s+(?:not|never)|won't|wouldn't|doesn't|don't|isn't|"
                         r"aren't|wasn't|not|never|nah|nope|no|reject(?:ed)?|can(?!['’]t)|could|should|must|may|"
                         r"might|shall|cannot|can't|cant|couldn't|"
                         r"shouldn't|mustn't|gotta|ought|(?:needs?|has|have) to|"
                         # the exclusion verbs of _PICK_OUT, put after the ID ('I-009 vetoed', 'I-009 scrap'); not
                         # when they turn on the others ('I-003, I-007 kill the others')
                         r"(?:veto|nix|ax|axe|ditch|scrap|skip|bin|kill|delete|remove|exclude|eliminate|abandon|avoid|"
                         r"ignore|dismiss|discard|drop|cancel|pass)(?:e?d|ped|ned|led)?"
                         r"(?![^\S\n]+(?:all\s+)?(?:the\s+)?(?:others?|rest|remaining|remainder|everything|all)\b)|"
                         r"forget|forgot|forgotten|"
                         r"strike|struck|cut|dead|withdrawn|shelved|denied|declined|refused|"
                         r"(is|are|was|were|has|had|seems|looks|feels|goes|gone|went|stays?))\b|"
                         # a line ending in a no after a run of punctuation or 'thanks,' ('I-009 -- no', 'I-009 [no]')
                         r"([^\S\n]*(?:(?:thanks|thx)[^\S\n]*)?[^\w\s]+[^\S\n]*(?:no|not|never|nah|nope)\b"
                         r"(?:[^\S\n]+(?:thanks|thank\s+you|thx))?[.!\])]*[^\S\n]*(?=\n|$)))", re.I)
# G8a (no read-back) only: an ID taken, then a separator and a rejection ('I-007: not good', "I-007, doesn't work");
# 'not sure', 'not I-009' and a plain 'no' stay a hedge, an exclusion and a note
_PICK_G8A_NO = re.compile(r"\b[IEQ]-\d+ ?(?:--+|[,;:(=–—-]) ?(?:not|never|nope|nah|rejected|bad|"
                          r"(?:doesn|won|don|isn|wasn)'?t)\b(?! (?:sure|[IEQ]-\d))", re.I)


def _pick_lead(cur, took_at, said=False, whole=None):
    """The first stretch of `cur` with an ID it takes (at a position of `took_at`) that the lead check above does
    not know, from the stretch's start to the ID's end, or None. With `said` (G6, G7: the IDs edit a suggested set) a
    remark on a taken ID ('ok, I-009 is gone') asks too. A no that ends the line after an ID is read in `whole`, the
    reply before its notes were blanked (same positions): 'I-009 - nope.' is no note."""
    seps = [m.end() for m in _PICK_SEP.finditer(cur)]
    prev, j = 0, 0
    for m in ID_RE.finditer(cur):
        while j < len(seps) and seps[j] <= m.start():
            j += 1
        start = max(prev, seps[j - 1] if j else 0)
        prev = m.end()
        if m.start() not in took_at:
            continue
        if re.search(r"\b(?:should|shall|can|could|do|would|will|may|must)\s+(?:i|we)\b", cur[start:m.start()], re.I):
            return cur[start:m.end()]  # 'ok or should I add I-004': a question, however its lead reads
        ws = _words(cur[start:m.start()])
        away = _PICK_AWAY.match(cur, m.end())
        if _negated(ws) or away:  # "I don't like I-009", 'never fund I-009', 'put I-009 aside', 'take I-009 off'
            return cur[start:away.end() if away else m.end()]
        for k in range(len(ws) - 1, -1, -1):
            if ws[k] in _PICK_LEAD or ws[k].isdigit():
                if ws[k] in ("with", "back") and k and ws[k - 1] not in _PICK_LEAD and ws[k - 1] not in _PICK_FILL:
                    return cur[start:m.end()]  # "I'm done with I-009", 'push back on I-009'; not 'go with I-003'
                break
            if ws[k] not in _PICK_FILL:
                return cur[start:m.end()]
    m = next((m for m in _PICK_MODAL.finditer(cur) if m.start() in took_at and (said or not m.group(1))), None)
    m = m or next((m for m in _PICK_MODAL.finditer(whole or cur) if m.start() in took_at and m.group(2)), None)
    return m.group(0) if m else None


def _g8a_doubt(t):
    """G8a records a gut pick and acts on nothing: a take-back, a self-correction or a question asks again (a hedge
    is a gut feeling too)."""
    if _TAKEN_BACK.search(t) or re.search(r"\bor\s+(?:maybe\s+)?not\W*$", t, re.I):
        return "Your reply takes itself back: reply once more with only what you want."
    if _SELF_FIX.search(t):
        return "Your reply corrects itself: reply once more with only what you want."
    said = _clauses(t)
    if said and (said[-1][1] or _QUESTION.match(said[-1][0])):
        return "Your reply ends with a question: answer it with one of the replies above."
    return None


def pick_base(ctx, gid):
    """The suggested set of G6 (the proposed finalists) or G7 (the default red-team set, 10.1)."""
    if ctx is None:
        return []
    return list(ctx.state.get("finalists") or []) if gid == "G6" else registry.suggested_top(ctx)


def _pick_reply(gid, t, ctx, why):
    """parse_reply for G6, G7, G8a and G8b (above): the answer's fields, or {} with `why` said when it is unclear."""
    if gid == "G8b" and (not t or _yesno(t)):
        return {"accept_recommendation": True}
    if not t:
        return {"skip": True} if gid == "G8a" else {}
    if gid == "G8a":
        doubt = _g8a_doubt(t)
        if doubt:
            _say(why, doubt)
            return {}
    elif gid in ("G6", "G7") and _form_words(t) == ["skip"]:
        return {}  # `ub answer ... --skip`: the suggested set, as the step takes it without this gate
    s = re.sub(r"[^\S\n]+", " ", t.translate(_QUOTES))
    main, kind, clash, quiet = list(s), {}, [], list(s)  # kind: where an ID starts -> (out | swap | runner | park, ID)

    def blank(a, b, note=False):
        main[a:b] = " " * (b - a)
        if note:  # a note or a reason: out of the range check too
            quiet[a:b] = " " * (b - a)

    def mark(m, g, what):
        for i in ID_RE.finditer(s, m.start(g), m.end(g)):
            if kind.setdefault(i.start(), (what, i.group(1).upper()))[0] != what:
                clash.append(i.group(1).upper())

    def text():
        return "".join(main)

    if gid == "G8b":
        for m in _PICK_RUNNER.finditer(s):
            mark(m, 1 if m.group(1) else 2, "runner")
            blank(m.start(), m.end())
        for m in _PICK_PARK.finditer(s):
            mark(m, 1, "park")
            blank(m.start(), m.end())
    for m in _PICK_NOTE.finditer(s):
        blank(m.start(), m.end(), True)
    every, joined = False, None
    for rx, g in ((_PICK_OUT, 2), (_PICK_NO, 1), (_PICK_OUT_POST, 1)):  # a note's exclusions count too
        for m in rx.finditer(s):
            every = every or rx is _PICK_OUT and bool(m.group(1))
            if rx is _PICK_OUT_POST and not m.group(0).endswith("~") and not re.match(r"~|leave", m.group(0), re.I):
                j = re.search(r"[IEQ]-\d+(?: ?[&/] ?| (?:and|or|nor) |(, ?))$", s[max(0, m.start() - 16):m.start()],
                              re.I)  # 'I-009 and I-011 out', 'I-009, I-011 are out' ('I-007, I-009 out' is a list)
                j = j if j and (not j.group(1) or re.search(r" are ", m.group(0), re.I)) else None
                joined = joined or (j and s[m.start() - len(j.group(0)):m.end()])
            mark(m, g, "out")
            blank(m.start(), m.end())
    for rx in (_PICK_OVER, _PICK_SWAP):
        for m in rx.finditer(text()):
            if rx is _PICK_OVER and m.group(2) and gid == "G8a":
                blank(m.start(2), m.end(2))
                continue  # 'I-007 over I-003, then I-001' ranks
            mark(m, 1, "swap" if rx is _PICK_OVER else "out")
            mark(m, 3 if rx is _PICK_OVER else 2, "out" if rx is _PICK_OVER else "swap")
            blank(m.start(), m.end())
    cur, at = text(), 0
    for end in [m.start() for m in _SENT_END.finditer(cur)] + [len(cur)]:
        pos = at
        while True:  # a reason after an ID is a note, up to the next clause an ID leads
            first = ID_RE.search(s, pos, end)
            w = _PICK_WHY.search(cur, first.end(), end) if first else None
            if not w:
                break
            n = _PICK_NEXT.search(cur, w.end(), end)
            pos = n.start() if n else end
            blank(w.start(), pos, True)
        at = end
    rng = _PICK_RANGE.search("".join(quiet))
    if rng:  # 'I prefer I-004 to I-009' compares two ideas (in a note or a reason it picks nothing)
        _say(why, "Your reply compares ideas instead of naming the ones you want: name each idea you want by its ID."
             if re.search(r"\b(?:prefer(?:s|red)?|rather(?:\s+have)?)(?:\s+\w+){0,2}\s+$",
                          s[max(0, rng.start() - 40):rng.start()], re.I) else
             "Your reply names a range of ideas: name each idea you want by its ID (no ranges).")
        return {}
    if gid == "G8b":
        cur = text()
        first = ID_RE.search(cur)
        for m in _PICK_SAID.finditer(cur):
            if first and first.start() < m.start():  # 'I-007 but I-003 is a close second'
                blank(m.start(), m.end())
    cur = text()
    got = [(p, k) for p, k in sorted(kind.items())] + [
        (m.start(), ("take", m.group(1).upper())) for m in ID_RE.finditer(cur) if m.start() not in kind]
    got.sort()
    took = [i for _p, (k, i) in got if k == "take"]
    picks = [i for _p, (k, i) in got if k in ("take", "swap")]
    left = [i for _p, (k, i) in got if k == "out"]
    named = [i for _p, (k, i) in got if k != "out"]
    runner = list(dict.fromkeys(i for _p, (k, i) in got if k == "runner"))
    park = list(dict.fromkeys(i for _p, (k, i) in got if k == "park"))
    both = sorted(set(clash) | set(left) & set(named))
    if both:
        _say(why, "Your reply both takes and leaves out %s: reply with only the IDs you want." % _ids_text(both))
        return {}
    lead = joined or _pick_lead(cur, set(p for p, (k, _i) in got if k == "take"), gid in ("G6", "G7"), s)
    if not lead and gid == "G8a":  # 'I-007: not good': G8a has no read-back, so a rejection after an ID asks
        no = _PICK_G8A_NO.search(s)
        lead = no.group(0) if no else None
    if lead:
        _say(why, "Your reply says %s, and I cannot tell whether it takes or leaves out %s: %s." % (
            _quote(lead.strip(), 60), _ids_text([ID_RE.findall(lead)[0].upper()]),
            "name the idea you choose" if gid == "G8b" else
            "name up to 3 finalist IDs in order, or `skip`" if gid == "G8a" else "name the IDs you want"))
        return {}
    said = [c for c, _a in _clauses(cur)]
    words = set(x for c in said for x in _words(c))
    if gid == "G8a":
        skip = any("skip" in _words(c) and set(_words(c)) <= set(("skip", "it", "this", "that", "please", "thanks",
                                                                  "ok", "for", "now", "just", "gut", "pick"))
                   for c in said)
        if every or skip and picks:
            _say(why, "Your reply is not a gut pick I can record: name up to 3 finalist IDs in order, or `skip`.")
            return {}
        return {"skip": True} if skip else {"picks": picks, "notes": t} if picks else {}
    neg = next((c for c in said if _negated(_words(c)) and not _PICK_REST.search(c)), None)
    if neg is not None:
        _say(why, "Your reply says %s, and I cannot tell which idea it leaves out: %s." % (
            _quote(neg.strip(), 60), "name the IDs you want" if gid != "G8b" else "name the idea you choose"))
        return {}
    if gid == "G8b":
        chosen = list(dict.fromkeys(picks))
        if len(chosen) > 1 or len(runner) > 1 or re.search(r"\b(?:runners?|park(?:ed|ing)?)\b", cur, re.I):
            _say(why, "Your reply names more than one idea, or a runner-up or a parked idea I cannot place: reply "
                      "with the one idea you choose, and `runner-up: <ID>` or `park: <ID>` beside it.")
            return {}
        out = {"why": t}
        if runner:
            out["runner_up"] = runner[0]
        if park:
            out["park"] = park
        if chosen:
            out.update(chosen=chosen[0], accept_recommendation=False)
        elif words & _PICK_BASE:
            out["accept_recommendation"] = True
        return out
    if re.search(r"\brest\b", _PICK_REST_KEEP.sub(" ", _PICK_NO_REST.sub(" ", cur)), re.I):
        _say(why, "Your reply says `the rest`, and I cannot tell whether it keeps or leaves out the rest: name the "
                  "IDs you want, or `ok` for the suggested set.")
        return {}
    base = pick_base(ctx, gid)
    every = every or bool(words & _PICK_ALL)
    edits = every or bool(words & _PICK_BASE) or bool(_PICK_MORE.search(_PICK_NO_REST.sub(" ", cur))) or \
        not took and bool(left or picks)
    if not (picks or left or edits):
        _say(why, "Your reply names no idea ID: reply with the IDs you want, or `ok` for the suggested set.")
        return {}
    ids = picks
    if edits:
        stray = [i for i in left if i not in base]
        if every and took or stray:
            _say(why, "Your reply leaves out %s, which the suggested set (%s) does not hold: reply with the IDs you "
                      "want." % (_ids_text(stray), _ids_text(base)) if stray else
                      "Your reply says `all` beside a list of IDs: reply with only the IDs you want.")
            return {}
        ids = [i for i in base if i not in left] + [i for i in dict.fromkeys(picks) if i not in base]
        if ids == base:
            return {}  # the suggested set as it is
    return {"finalists" if gid == "G6" else "picks": ids}


def _gate_reply(gid, t, low, ctx, why):
    """parse_reply for one gate, after what every gate shares (the reply without its wrapping, its answer-file
    fields, its doubts)."""
    if gid == "G1":
        # moving on with the seeds as they are ('not yet', "skip? no, I'm still writing", 'almost done', 'done in 5
        # minutes' are asked again; 'done, wrote 5 ideas in 10 minutes' is done)
        m = re.search(r"\b(?:almost|nearly)\s+(?:done|finished)\b|\bdone\s+(?:soon|shortly|in\s+(?:\d+|a\s+(?:few|"
                     r"moment|minute)|(?:\w+\s+){1,2}(?:min|hour|sec|moment)\w*\b))|\b(?:now|still)\s+(?:writing|"
                     r"working|adding)\b|(?:\b(?:i|we|but|and|yet)\s+|(?:^|[,.;:!?\n(-])[^\S\n]*)(?:still\s+|also\s+|"
                     r"just\s+)?(?:need|have|got|want|going)\s+to\s+(?:add|write|finish|put)\b|\bmore\s+to\s+(?:add|"
                     r"write|come|follow)\b", t, re.I)
        if m and not (re.search(r"\bto\s+(?:add|write|finish|put)\b", m.group(0), re.I) and re.match(
                r"[^.;!?\n]*\blater\b", t[m.end():], re.I)):
            # 'done in five minutes', 'Done with the problem, now writing', 'I still need to add', 'done, I have to
            # add two more', 'done, one more to add' (not 'done - nurses still have to add their shifts by hand
            # today', a line of the seeds, nor 'done, but I want to add more later')
            _say(why, "Reply `done` once the seeds file is written (or `skip`).")
            return {}
        if re.search(r"\bnot\s+(?:in\s+)?the\s+seeds?\s+file\b|\b(?:in|into|on)\s+(?:the|my|our|a|his|her|their)\s+"
                     r"(?:(?!seeds?\b)\w+\s+){0,2}(?:doc|docs|document|notes|email|mail|chat|sheet|spreadsheet|slack|"
                     r"notion|notebook)\b", t, re.I):  # 'I wrote them in my notes', "Done, they're in the Google doc"
            _say(why, "The kit reads the ideas only from the seeds file: put them there, then reply `done` (or "
                      "`skip`).")
            return {}
        k = "done" if _yesno(t) else _pick(t, ("done", "skip")) if t else None
        if not k and t and not _G1_LATER.search(t):  # 'I have completed the seeds file', 'Ideas are added'
            k = _pick(_G1_DONE.sub("done", re.sub(r"^\W*skipping\b", "skip", t, flags=re.I)), ("done", "skip"))
        if not k and t:
            _pick(t, ("done", "skip"), why)
        return {k: True} if k else {}
    if gid == "G2":
        # an answer is the rest of its own line: [^\S\n] (any space but a line feed: a no-break or ideographic space
        # too), never \s, so no match crosses a line break (a number with nothing after it answers nothing) and a
        # flood of blank lines stays linear (#34)
        answers = []
        for m in re.finditer(r"^[^\S\n]*(?:Q)?(\d+)[^\S\n]*[.):-][^\S\n]*(\S.*)$", t, re.M | re.I):
            answers.append({"q": m.group(1), "a": m.group(2).strip()})
        out = {"answers": answers}
        if low in ("ok", "okay", "go", "yes", "defaults", "accept", "accept defaults", "") or \
                re.search(r"\b(ok|defaults)\b", low) and not answers:
            out["accept_defaults"] = True
        elif answers:
            out["accept_defaults"] = bool(re.search(r"\b(ok|defaults? for the rest)\b", low))
        return out
    if gid in ("G2c", "G10"):
        # a correction is a paid redo at G10: only a reply that says something to correct is one; a refusal, a
        # deferral, a hedge or praise alone ('no', 'stop', 'not yet', 'not sure', 'Great') is asked again, and so is a
        # confirmation that says more in the same clause ('The problem statement is right'), or beside a clause that
        # changes nothing ('Confirmed. Leave the tags as they are.'; with an edit it is a correction: 'Correct, except
        # the uptime target should be 99.5%') (_review); after `corrections:` a take-back, a deferral or a pointer
        # asks, as after G13 `changes:`
        m = re.match(r"\W*corrections?\s*:\s*(.*)$", t, re.I | re.S)
        doubt = m and _label_doubt(m.group(1), weak=False)
        if doubt:  # 'corrections: will send tomorrow', 'corrections: nvm', 'corrections: as discussed'
            _say(why, doubt)
            return {}
        rows = _review(t, gid)
        kinds = [r[3] for r in rows] if not isinstance(rows, str) else []
        if isinstance(rows, str) or kinds == ["content"] and len(rows[0][1]) == 1:  # 'aprove', 'gud'
            _say(why, rows if isinstance(rows, str) else _ONE_WORD)
            return {}
        if any(r[4] for r in rows):
            return {"confirm": False, "corrections": t}
        if not t or "yes" in kinds and not set(kinds) & set(("no", "mixed", "content")):
            return {"confirm": True}
        _say(why, "A bare `no` does not say what to correct." if "no" in kinds else
             "Your reply confirms and also says more: reply `ok`, or write your corrections."
             if "yes" in kinds or "mixed" in kinds else
             "Your reply does not say what to change: reply `ok`, or say what is wrong and what it should be."
             if "content" in kinds else "Your reply neither confirms nor says what to correct.")
        return {}
    if gid == "G2f":
        # `restore` rewrites the user's CONTEXT.md, `keep` leaves it: 'revert', 'undo', 'put it back' and "don't
        # keep" say `restore`; the one keyword no negation refuses is the answer, and a refused `restore` alone keeps
        # ("don't restore", 'restore? no'; a deferred one, 'restore later', is asked again); anything else, an empty
        # reply and a refused `keep` too, is asked again
        if re.search(r"\b(?:keep\w*|discard\w*)\s+(?:\w+\s+)?(?:original|old|previous|earlier|my|mine|ours|as\s+before)"
                     r"\b|\b(?:restor\w*|revert\w*)\s+(?:\w+\s+)?(?:new|current|latest|updated)\b", t, re.I):
            _say(why, "Your reply names the old CONTEXT.md: reply `restore` to put it back, or `keep`.")
            return {}  # "I'd rather keep my original", 'discard the old version', 'restore the new version'
        if any(re.match(r"[^\w\n]*[^:\n]{1,40}:[^\S\n]*\S", ln) and not re.match(r"\W*(?:restore|keep)\b", ln, re.I) and
               not _own_label(re.sub(r".*[.!?][^\S\n]+", "", ln.split(":", 1)[0]) + ":", gid)
               for ln in t.split("\n")):
            _say(why, "Your reply reads like pasted text: reply `restore` or `keep`.")
            return {}
        said = re.sub(r"\b(?:revert(?:ed)?|undo|undone|roll\s+(?:it\s+)?back|put\s+(?:it\s+)?back|(?:the\s+)?original"
                      r"\s+back|go\s+back|discard)\b", "restore", t.translate(_QUOTES), flags=re.I)
        said = re.sub(r"\b(?:don't|dont|do\s+not|never)\s+keep\b", "restore", said, flags=re.I)
        # 'Leave it as it is', 'the file may be restored'
        said = re.sub(r"\bleave\s+(?:(?:it|this|that|the\s+file|context\.md)(?:\s+as\s+(?:it\s+)?is)?|as\s+"
                      r"(?:it\s+)?is)\b", "keep", said,
                      flags=re.I)
        said = re.sub(r"\b(?:be|been|is|was|being|get|gets|got)\s+restored\b|\bput\s+(?:context\.md|the\s+(?:file|"
                      r"original))\s+back\b|\breject\s+(?:the|these|those|its|their)\s+(?:changes|edits)\b", "restore",
                      said, flags=re.I)  # 'reject the changes', 'Put CONTEXT.md back'
        chosen, refused = _named(said, lambda w: w in ("restore", "keep"))
        left = set(chosen) - set(refused)
        if len(left) == 1:
            return {"restore": left.pop() == "restore"}
        if not chosen and set(refused) == set(["restore"]):
            if re.search(r"\b(?:later|wait|hold|pause|postpone|defer|yet)\b|\bnot\s+now\b", said, re.I):
                _say(why, "A restore put off is no answer yet: reply `restore` or `keep` now.")  # 'restore later'
                return {}
            return {"restore": False}
        _pick(said, ("restore", "keep"), why)
        return {}
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
        # an ID no piece places ('I-004 is a dud') and a reply that places nothing and keeps nothing ('wait', 'rescue
        # 12') are asked again; 'I-004's flag is fine, confirm it' places I-004 in its second piece
        rescue, confirm, cleared, placed, loose = [], [], [], set(), []
        by_id = "Name each idea by its ID (`rescue I-012: <reason>`, `confirm I-004`)."
        if not t or _yesno(t) is not None and not (set(_words(t)) & _CONFIRMS) or low == "none":
            return {"rescue": [], "confirm_flags": []}
        if _ID_RANGE.search(t) or _SHORT_ID.search(t):  # 'confirm I-004..I-006', 'confirm I-4'
            _say(why, by_id)
            return {"rescue": [], "confirm_flags": []}
        for seg in re.split(r"[\n;]", t):
            for ln, v in _verb_clauses(seg, "confirm|clear|rescue|save"):
                ids = _ids(ln)
                if not ids:
                    if re.search(_ALL_OF_THEM % "clear", ln, re.I):
                        placed.add("all")  # 'clear all flags' kills nothing
                    elif re.search(_ALL_OF_THEM % "confirm|rescue|save", ln, re.I) or \
                            re.search(_BY_NUMBER % (("confirm|clear|rescue|save",) * 2), ln, re.I):
                        _say(why, by_id)
                    continue
                if _spoken_against(ln, v):
                    placed.update(ids)
                    if _PUT_OFF.search(ln):  # 'confirm I-004 later', 'rescue I-012 later'
                        _say(why, "Your reply puts %s off: decide it now (`rescue`, `confirm` or `clear`)." % ids[0])
                    continue  # 'rescue I-004? no': nothing
                if v:
                    verb, got = v.group(1).lower(), _ids(v.group(2))
                    placed.update(got)
                    if _denies(_words(ln[:v.start()])):
                        if verb == "clear":  # "don't clear I-004" would kill it: asked again
                            _say(why, "Reply `confirm %s` (it is killed) or `clear %s`." % (got[0], got[0]))
                        continue  # "don't confirm I-004" clears it; a denied rescue names nothing
                    if verb == "confirm":
                        confirm += got
                    elif verb == "clear":
                        cleared += got
                    else:  # a rescue: every ID of its list, and the rest of the piece as the reason
                        reason = re.sub(r"^[\s,:;\-\u2013\u2014\])'\"`]*(?:because\b\W*)?", "", ln[v.end():]).strip()
                        if re.search(r"(?:^|[,.]|\b(?:and|then)\b)\s*(?:then\s+)?(?:confirm|clear|rescue|save|kill|"
                                     r"drop)\b",
                                     reason, re.I):  # 'rescue I-012 and confirm every flag'
                            _say(why, "Put each instruction in a clause of its own (`rescue I-012: <reason>; confirm "
                                      "I-004`).")
                        elif _TAKEN_BACK.search(reason):  # 'rescue I-012: jk'
                            _say(why, "Your reply takes itself back: reply once more with only what you want.")
                        rescue += [{"id": i, "reason": reason.rstrip(" ,") or "rescued by the user"} for i in got]
                    continue
                pairs = re.findall(r"([IEQ]-\d+)[^\w,;]*(confirm|clear)\b", ln, re.I)
                w = _words(ln)
                if pairs:  # 'I-004: confirm, I-005: clear'
                    confirm += [i.upper() for i, x in pairs if x.lower() == "confirm"]
                    cleared += [i.upper() for i, x in pairs if x.lower() == "clear"]
                    placed.update(i.upper() for i, _x in pairs)
                elif any(x in ("rescue", "rescued", "save", "saved") for x in w) and not _negated(w):
                    # 'I-012: rescue it' rescues the first ID; the rest of the piece is its reason
                    reason = re.sub(r"^.*?\b%s\b\W*(because\W*)?" % re.escape(ids[0]), "", ln, flags=re.I).strip()
                    rescue.append({"id": ids[0], "reason": reason.rstrip(" ,") or "rescued by the user"})
                    placed.add(ids[0])
                else:  # 'kill I-004', 'I-004 is a dud': G4 rescues, confirms or clears; anything else is asked again
                    loose.append(ids[0])
        for i in loose:
            if i not in placed:
                _say(why, "Your reply names %s without `rescue`, `confirm` or `clear`." % i)
        for i in sorted(set(confirm) & set(cleared))[:1]:
            _say(why, "%s is both confirmed and cleared: name it once." % i)
        if not placed and not loose and not _keeps_all([x for x in _words(t) if x not in _CONFIRMS]):
            _say(why, by_id)  # 'confirm' or 'clear' alone names no flag
        return {"rescue": rescue, "confirm_flags": confirm}
    if gid == "G5":
        # 'drop I-003' kills; one verb for two IDs that are no list ('Kill the fax one, I-003. I-007 stays.'), a keep
        # beside `not <ID>` ('keep I-003, not I-007') and a reply that places nothing and keeps nothing ('wait', 'kill',
        # 'I-003 can go') are asked again
        kill, keep, answered, placed, loose, unkept = [], [], False, set(), [], []
        by_id = "Name each idea by its ID (`kill I-003`, `keep I-007`), or reply `ok` to park them all."
        cands = list((ctx.state.get("k4_candidates") if ctx is not None else None) or [])
        if _ID_RANGE.search(t) or _SHORT_ID.search(t) or re.search(r"\b(?:kill[^\S\n]+keep|keep[^\S\n]+kill)\b", t,
                                                                   re.I):  # 'kill I-003..I-007', 'kill I-3'
            _say(why, by_id)
            return {"kill": [], "keep": []}
        # 'kill both. no, keep both': the two verbs of every candidate are a self-correction
        if len(set(x.lower() for x in re.findall(_ALL_OF_THEM % "kill|keep", t, re.I))) > 1:
            _say(why, "Your reply corrects itself: reply once more with only what you want.")
            return {"kill": [], "keep": []}
        for ln in t.split("\n"):
            ln = re.sub(r"\bdrop(?=\s+(?:[IEQ]-\d|it\b|them\b|both\b|all\b|idea\b))", "kill", ln, flags=re.I)
            ln = re.sub(r"\bkill(?=\s+for\b)", "love", ln, flags=re.I)  # "I'd kill for I-003" kills nothing
            for c, v in _verb_clauses(ln, "kill|keep"):
                if _spoken_against(c, v):
                    answered = True
                    placed.update(_ids(c))
                    if _PUT_OFF.search(c) and _ids(c) and "kill" in _words(c):  # 'kill I-003 later' (a keep parks)
                        _say(why, "Your reply puts %s off: `kill` or `keep` it now, or reply `ok` to park them "
                                  "all." % _ids(c)[0])
                    continue  # 'kill I-003? no.': parked
                said = set(x.lower() for x in re.findall(r"\b(kill|keep)\b", c, re.I))
                ids = _ids(v.group(2)) if v else _ids(c)
                both = None if v else re.search(_ALL_OF_THEM % "kill|keep", c, re.I)
                if both and (not ids or re.search(r"\b(?:not|except|excluding|without|minus|but)\s+[IEQ]-\d", c,
                                                  re.I)):  # 'kill both', 'keep them all': every K4 candidate
                    if not cands or re.search(r"\b(?:not|except|excluding|without|minus|but)\s+[IEQ]-\d", t,
                                              re.I):
                        _say(why, by_id)
                        continue
                    v, ids = both, cands
                if v:
                    verb = v.group(1).lower()
                    nots = re.findall(r"\bnot\s+([IEQ]-\d+)", c[v.end():], re.I)
                    pre = _words(c[:v.start()])
                    if _denies(pre) and not (verb == "keep" and set(pre) <= set(("no", "nope", "nah"))):
                        # "don't kill I-003" and 'no need to kill I-003' keep it; "don't keep I-003" names nothing,
                        # and is asked again unless the reply kills it too ('no reason to keep I-003. kill it'); a bare
                        # no before keep answers a kill ('no, keep them' keeps them)
                        if verb == "keep":
                            unkept.extend(ids)
                        verb, answered = "keep" if verb == "kill" else None, True
                    elif verb == "keep" and nots:
                        _say(why, "Reply `kill %s` or `keep %s`: your reply says `not %s`." % ((nots[0].upper(),) * 3))
                        continue
                elif re.search(_BY_NUMBER % ("kill|keep", "kill|keep"), c, re.I):  # 'kill 3 and 7', 'kill i3'
                    _say(why, by_id)
                    continue
                elif _negated(_words(c)):
                    verb = None  # a negation and no verb before the ID ('I-003 is not a duplicate'): parked
                elif len(said) > 1:  # each verb after its ID: 'I-003: kill, I-007: keep'
                    for i, x in re.findall(r"([IEQ]-\d+)[^\w,;]*(kill|keep)\b", c, re.I):
                        (kill if x.lower() == "kill" else keep).append(i.upper())
                    continue
                else:
                    verb = said.pop() if said else None
                    if verb and len(set(ids)) > 1 and set(_ids(re.search(_ID_LIST, c, re.I).group(0))) != set(ids):
                        _say(why, "Your reply names %s with one `%s`: reply `kill <ID>` or `keep <ID>` for each." % (
                            " and ".join(sorted(set(ids))), verb))
                        continue
                if verb:
                    (kill if verb == "kill" else keep).extend(ids)
        for c, _a in _clauses(_it_id(t, "kill|keep")):
            w, first = _words(c), ID_RE.search(c)
            if "kill" in w and not first and not re.search(_ALL_OF_THEM % "kill", c, re.I) and not set(w) & _NONE_OF \
                    and not _negated(w):
                _say(why, by_id)  # 'keep I-007, kill the other one'
            elif first and not set(w) & set(("kill", "keep")) and len(_words(c[:first.start()])) <= 2 and not set(
                    _words(c[:first.start()])) & _NOT_AN_ORDER and all(x in _COURTESY or x in ("too", "also", "as",
                                                                                         "well") for x in _words(
                    ID_RE.sub(" ", c[first.end():]))):
                loose += [i for i in _ids(c) if i not in placed and i not in kill and i not in keep]
        for i in loose[:1]:  # 'Bin I-003', 'Kill I-003 as it is a duplicate. Also I-007 please.'
            _say(why, "Your reply names %s without `kill` or `keep`." % i)
        if not (kill or keep or _ids(t)) and re.search(r"\bneedful\b|\bkill(?:s|ing)\b|\bas\s+(?:suggested|"
                                                       r"recommended|proposed)\b", t, re.I) and not _negated(_words(t)):
            _say(why, by_id)  # 'Please do the needful', 'proceed with the kills as suggested'
        if t and not (kill or keep or answered) and _yesno(t) is None and (_ids(t) or not _keeps_all(_words(t))):
            _say(why, by_id)
        for i in [i for i in unkept if i not in kill][:1]:
            _say(why, "Your reply says not to keep %s: reply `kill %s`, or `ok` to park them all." % (i, i))
        return {"kill": kill, "keep": keep}
    if gid in ("G6", "G7", "G8a", "G8b"):
        return _pick_reply(gid, t, ctx, why)
    if gid == "G9":
        # a PASSED on a missed probe skips K6: a miss said in other words ('a miss', 'failed', 'did not pass', 'fell
        # short', 'below the bar', 'not even close') is `missed`; short, below and under are a miss only in such a
        # phrase or in a reply that names no result ('passed, latency under 200 ms'); `pass` alone is no result
        # ('pass rate: 3 of 10'), and two results, or a refused one ('Passed? Not really.'), are asked again
        # a negation ends at a colon before a bare result: 'not passed, not missed: inconclusive'
        said = re.sub(r"(\bnot\s+(?:passed|missed|inconclusive))[^\S\n]*:(?=[^\S\n]*(?:passed|missed|inconclusive)"
                      r"\W*$)", r"\1;", t.translate(_QUOTES), flags=re.I)
        said = re.sub(r"\bpass(?:ed|es|ing)?\s+(?:(?:it|this|that|them)\s+(?:on|along|over|to)|(?:(?:the|my|our)\s+"
                      r"(?:\w+\s+){1,2})?(?:on|along|over)\s+to|the\s+(?:results?|numbers?|data|report)\s+to)\b",
                      "handed", re.sub(r"\bagainst\b", "versus", said, flags=re.I),
                      flags=re.I)  # 'passed it on to Sam', '4 swaps against a target of 10'
        bare = not re.search(r"\b(?:passed|missed|inconclusive|miss|fail(?:ed|s|ing)?)\b", said, re.I)
        said = re.sub(r"\b(?:not|never|\w+n't|didnt|doesnt|hasnt|havent)\s+pass\b|\b(?:miss|fail(?:ed|s|ing)?)\b|"
                      r"\bnot\s+even\s+close\b|"
                      r"\b(?:fell|falls?|falling|came|comes?|was|were|is|are)\s+short\b|\bshort\s+of\b|"
                      r"\b(?:below|under)\s+(?:the\s+)?(?:\w+\s+)?(?:bar|target|goal|threshold|mark)\b|"
                      r"\b(?:below|under)\s+the\s+\d+\s+we\s+(?:needed|wanted|set)\b" + (
                          r"|\b(?:short|below|under)\b" if bare else ""), "missed", said, flags=re.I)
        r = _pick(said, ("passed", "missed", "inconclusive"), why)
        rows = _read(said)
        # 'passed, 11 of 20, but Maria thinks the target was 12'
        if r == "passed" and any(w[:1] and w[0] in ("but", "though", "although", "however") and (
                neg or "only" in w and any(x.isdigit() for x in w) or set(w) & _G9_DOUBTS) for _c, w, neg, _no in rows):
            # "passed, but we didn't hit the target", 'passed but only 3 of 10' ('but only just' passes): the 'but'
            # clause speaks against it
            _say(why, "Your reply says `passed` and then speaks against it ('but ...').")
            r = None
        if r == "missed" and (re.search(r"\b(?:instead\s+of|rather\s+than)\s+(?:kill|drop|discard|scrap)", said, re.I)
                              or _KEEP_IDEA.search(said) or any(set(w) & _KILL and _negated(
                                  [x for x in w if x not in _KILL]) for _c, w, _neg, _no in rows)):
            # "Missed, but please don't kill it yet": MISSED is the K6 kill the reply refuses
            _say(why, "MISSED kills the idea (K6); reply `missed` to accept that, or `inconclusive` to keep it.")
            r = None
        return {"result": r.upper() if r else None, "note": t}
    if gid == "G11":
        tt = t.translate(_QUOTES)
        # a steal takes an element from another letter, never chooses it; "don't steal anything from A" is no steal
        clauses = [sm for sm in _G11_STEAL.finditer(tt)
                   if not _negated(_words(re.split(r"[.;!?\n]", tt[max(0, sm.start() - 40):sm.start()])[-1]))]
        steal = [{"from": (sm.group(1) or sm.group(2) or sm.group(5)).upper(),
                  "element": (sm.group(3) or sm.group(4)).strip()} for sm in clauses]
        if not steal and re.search(r"\+\s*steal\b", tt, re.I):
            steal = ["*"]
        for sm in clauses:
            tt = tt.replace(sm.group(0), ";")
        chosen, named, refused, accept, said_yes, pointed = set(), set(), set(), True, False, set()
        for c, w, neg, no in _read(re.sub(r"\+\s*steal\b", ";", tt, flags=re.I),
                                   names=lambda c, w: bool(_g11_letters(c)[1]),
                                   scope=lambda x: len(x) == 1 and x in "abcdef"):
            ch, nm = _g11_letters(c)
            if neg or no:  # 'avoid A', 'B? no.'
                refused |= nm
            else:
                chosen |= ch
                if len(nm) == 1 and set(w) & _G11_POINTS and all(x in YES_WORDS or x in _G11_POINTS or
                                                                 x in _G11_FILLER or x.upper() in nm for x in w):
                    pointed |= nm  # 'suggestion A', 'the suggested A'
            named |= nm
            yes = not (nm or neg or no) and any(x in YES_WORDS or x in _G11_POINTS for x in w) and \
                all(x in YES_WORDS or x in _G11_POINTS or x in _G11_FILLER for x in w) and not (
                    w[-1] in _G11_VERBS and w[-2:-1] and w[-2] in ("i", "we", "i'll", "we'll", "i'd", "we'd"))
            said_yes = said_yes or yes  # 'I pick' (and no letter) takes nothing
            accept = accept and yes
        # one letter, named as the choice and never in a negation, is the choice, whatever the reply says of the others
        # ('Not A. B.', 'C please, A looks too complex'); the suggestion only when every clause takes it and no letter
        # is named; anything else ('A bit unsure; B', 'avoid A', "I don't want C", 'Yes, go ahead. C seemed overkill')
        # is asked again
        if len(chosen) == 1 and not chosen & refused:
            return {"choice": chosen.pop(), "accept_recommendation": False, "steal": steal, "notes": t}
        fine = _G11_FINE.match(tt)
        if not chosen and not refused and named == (set([fine.group(1)]) if fine else pointed) and len(named) == 1 and (
                fine or ctx is not None and g11_recommendation(ctx)[0] in named):
            # 'A is fine'; 'lgtm, suggestion A' where A is the suggestion
            return {"choice": named.pop(), "accept_recommendation": False, "steal": steal, "notes": t}
        if not named and accept:
            return dict({"accept_recommendation": True}, **({"steal": steal} if steal else {}))
        letters = " and ".join(sorted(named))
        _say(why, "Your reply names %s; name the one you choose." % letters if len(named) > 1 else
             "Your reply takes the suggestion and also names %s." % letters if named and said_yes else
             "Your reply names %s in a negation." % letters if refused else
             "Your reply names %s without choosing it (`%s` or `go with %s` chooses it)." % (letters, letters, letters)
             if named else "Your reply names no candidate.")
        return {"notes": t}
    if gid == "G12":
        # every clause says accept or reject before its numbers ('accept all, reject 3', 'ok, reject 3', 'approve all
        # but ADR 3'); the numbers that lead a clause continue the list before it ('reject 3, 4', 'accept 1,2 reject
        # 3'). The accept-all words (all, everything, the rest) count only when no ADR is accepted by number. A number
        # no verb places ('3 is wrong'), or one in a clause with "don't", "never" or a deferral, or refused by a bare
        # refusal ('reject 3? no'), is asked again, and so is an exclusion that names no number ('Accept all except
        # the SMS one'). The text after 'reject 1:' is its reason. A range ('reject 2-3') is its numbers; a reversed
        # or long one ('3-1') is asked again.
        acc, rej, all_ok, loose, carry = [], [], False, [], None
        known = set(os.path.basename(p)[:4] for p in _adr_files(ctx)) if ctx is not None else set()
        t = re.sub(r"\ball\s+(?:two|three|four|five|six|seven|eight|nine|ten)\b", "all", t, flags=re.I)  # 'all three'
        # a note in brackets that accepts or rejects nothing ('ok (all 3 look right)'), a reason ('reject 3 because
        # Twilio costs 0.0079 per SMS') and 'No objection to any of the ADRs'
        t = _drop_notes(gid, _G12_NOTE, t)
        t = re.sub(r"^([^\w\n]*(?:ok|okay|yes|yep|yeah|lgtm|sure|fine)\b)(?=[^\S\n]+(?:reject|rejected|except|drop|but|"
                   r"not|without)\b)", r"\1,", t, flags=re.I | re.M)  # 'ok reject 3' is the card's 'ok, reject 3'
        t = re.sub(r"\bno\s+objections?(?:\s+(?:to|with|against)\s+(?:any|all|either|them|these|the\s+(?:adrs?|"
                   r"decisions?))(?:\s+of\s+(?:them|these|the\s+(?:adrs?|decisions?)))?)?\b", "ok", t, flags=re.I)
        if re.search(r"\b(?:two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|first|second|third)\b", t, re.I):
            _say(why, "Name the ADRs by number, e.g. `ok, reject 3`.")  # 'accept all comma except three period'
            return {}
        t = re.sub(r"(?<![\w-])(\d{1,4})[^\S\n]*\.\.+[^\S\n]*(\d{1,4})(?![\w-])", r"\1-\2", t)  # 'accept 1..3'
        spans = [(int(a), int(b)) for a, b in re.findall(r"(?<![\w-])(\d{1,4})-(\d{1,4})(?![\w-])", t)]
        if any(not a <= b <= a + 20 for a, b in spans) or sum(b - a for a, b in spans) > 50:
            _say(why, "Name the ADRs one by one (`reject 2 3`).")
            return {}
        t = re.sub(r"(?<![\w-])(\d{1,4})-(\d{1,4})(?![\w-])",
                   lambda m: " ".join(str(n) for n in range(int(m.group(1)), int(m.group(2)) + 1)), t)
        t = re.sub(r"\b(?:everything|every\s+one|everyone|(?:all\s+)?(?:the\s+)?(?:rest|others|remaining(?:\s+ones)?|"
                   r"other\s+ones?))\b", "all", re.sub(r"(\d)\s*:(?:(?!\b(?:accept|reject|approve|drop|keep)\w*\b)"
                                                       r"[^.;!?\n])*", r"\1 ", t, flags=re.I), flags=re.I)
        # 'everything except 3', 'every ADR except 3' and 'all ADRs but 3' say what 'accept all except 3' says
        t = re.sub(r"(^|[.;,!?\n][^\S\n]*)(?:(?:accept|approve)[^\S\n]+)?(?:all(?:[^\S\n]+(?:of[^\S\n]+)?"
                   r"(?:the[^\S\n]+)?(?:adrs|decisions))?|(?:every|each)[^\S\n]+(?:adr|decision|one))(?=[^\S\n]+(?:but|"
                   r"except|save)\b)",
                   r"\1accept all", t, flags=re.I)
        # 'Reject 3, the rest are fine.'
        t = re.sub(r"\ball\s+(?:(?:is|are|looks?|seems?)\s+)?(?:fine|ok|okay|good|great|right|correct|accepted|"
                   r"approved)\b", "accept all", t, flags=re.I)
        for _c, w, _neg, no in _read(t, names=lambda c, w: "all" in w or bool(re.search(r"\d", c)) or _is_yes(w)):
            neg = no or any(x == "never" or x.endswith("n't") or x == "dont" or x in _HOLD for x in w) or any(
                a == "no" and b in ("to", "need", "needed") for a, b in zip(w, w[1:]))  # 'No to accept all.'
            if _is_yes(w) and not neg:
                all_ok, carry = True, None
                continue
            nums = [adr_key(x) if re.match(r"^(?:adr-?)?\d{1,4}(?:-.*)?$", x) else None for x in w]
            nxt = next((x for n, x in zip(nums, w) if not (n or x in ("and", "adr", "adrs", "please", "thanks"))), None)
            if nxt is not None and nxt not in _G12_REJECT and not (nxt in YES_WORDS or nxt == "keep"):
                carry = None  # leading numbers continue the clause before ('2 reject 3'; not '3 is wrong')
            mode, run, placed = carry, carry is not None, False
            # an exclusion: a clause led by a reject word that names an ADR in words ('except the SMS one', 'but not
            # the monolith decision'); 'but fine for now' and "we're not using SMS" are reasons
            head = [x for x in w if x not in ("and", "ok", "please")][:1]
            if carry == "reject" and head and head[0] in ("not", "but", "except", "without") and any(nums):
                _say(why, "Your reply rejects ADRs and then excludes one: name only what you reject (`reject 3`).")
                return {}
            excludes = bool(head) and head[0] in _G12_REJECT and head[0] != "no" and bool(
                set(w) & set(("the", "adr", "adrs", "one", "decision", "decisions"))) or not any(nums) and bool(
                set(w) & set(("one", "adr", "decision"))) and bool(
                set(w) & set(("wrong", "bad", "off", "incorrect", "outdated")))  # 'the SMS one is wrong'
            for x, n in zip(w, nums):
                if x in _G12_REJECT:
                    mode, run = "reject", True
                elif x in YES_WORDS and x not in _COURTESY or x == "keep":
                    mode, run = "accept", True
                elif x == "all" and run and not neg:
                    if mode == "accept":
                        all_ok = True
                    else:
                        rej.append("all")
                elif n and run and not neg:
                    (acc if mode == "accept" else rej).append(n)
                    placed, excludes = True, excludes and mode != "reject"
                elif n and (not known or n in known or all(_known(gid, y, y) for y in w)):  # not '... 40 wards'
                    loose.append(str(int(n)))
                elif x not in ("and", "adr", "adrs", "number", "numbers", "them", "these", "those"):
                    run = False
            if excludes and "all" not in w and not neg or not placed and not neg and "all" not in w and set(w) & set((
                    "reject", "rejected", "drop")) and not set(w) & set(("nothing", "none", "anything", "any")):
                # an exclusion that placed no number, and a reject that names no ADR ('ok reject')
                _say(why, "Name the ADR you reject by number, e.g. `ok, reject 3`.")
                return {}
            carry = mode if run and placed else None
        if loose:
            _say(why, "Your reply names ADR %s where it is unclear whether you accept or reject it." % ", ".join(loose))
            return {}
        if not (acc or rej or all_ok):
            _say(why, "Your reply accepts or rejects no ADR.")
            return {}
        return {"accept": acc or (["all"] if all_ok else []), "reject": rej}
    if gid == "G13":
        if not t:
            return {"action": "approve"}
        m = re.match(r"^\s*changes?\s*:\s*(.*)$", t, re.I | re.S)
        if m:
            if re.search(r"\bswitch\w*\s+(?:to\s+)?(?:(?:architecture|candidate|option)\s+)?[A-F]\b|\brunner[- ]?up\b",
                         m.group(1), re.I):  # 'changes: fix the budget. and switch to B'
                _say(why, "Your reply both switches and asks for changes.")
                return {}
            doubt = _label_doubt(m.group(1), weak=False)
            if doubt:  # 'changes: nvm, approve', 'changes: will send tomorrow', 'changes: Legal says no'
                _say(why, doubt)
                return {}
            if "content" in [_change_kind(w, neg, no) for _c, w, neg, no in _read(m.group(1))]:
                return {"action": "changes", "changes": m.group(1).strip()}
            _say(why, "`changes:` needs what to change after it.")
            return {}
        # every clause is a yes, a switch, the runner-up, a refused one of these, a no, praise alone or something to
        # change (_change_kind); a change round and a switch are paid redos, so only a reply that says what to change
        # is a change round ('I approve', 'Great work', 'not yet' and "don't approve" never are), and a yes, a switch
        # or the runner-up together with something to change is asked again (_review), and so is a refused or unanswered
        # switch beside other content ('Switch to B? Costs matter more'). A letter chosen as at G11 ('use B
        # instead', 'go with C') is a switch, and a switch keeps its reasons ("switch to C, A turned out too heavy")
        rows = _review(_split_scoped(t), gid)
        if isinstance(rows, str):
            _say(why, rows)
            return {}
        kinds, switch_to, edit, off, strong = [], None, False, False, False
        for c, w, neg, kind, ed in rows:
            if re.search(r"\bno\s+to\s+(?:(?:architecture|candidate|option)\s+)?(?-i:[A-F])\b", c, re.I):
                kinds.append("refused")  # 'No to B.'
                off = True
                continue
            runner = re.search(r"\brunner[- ]?up\b", c, re.I)
            letter = _g11_letters(c)[0] if kind != "refused" and not neg else set()
            if "switch" in w or runner or len(letter) == 1:
                kinds.append("refused" if neg or kind == "refused" else "runner-up" if runner and "switch" not in w
                             else "switch")
                sm = re.search(r"(?i:\bswitch\s+(?:to\s+)?(?:(?:architecture|candidate|option)\s+)?)([A-F]\b|[a-f]$)",
                               " ".join(c.split()))
                off = off or kinds[-1] == "refused"
                if runner and kinds[-1] == "switch":  # 'switch B / runner-up' names both; 'switch to the runner-up'
                    kinds[-1:] = ["runner-up"] if re.fullmatch(
                        r"\W*(?:(?:let'?s|please|ok|then|we|i)\s+)*switch\w*\s+to\s+(?:the\s+)?runner[- ]?up(?:\s+"
                        r"(?:idea|one|instead|please))?\W*", c, re.I) else ["switch", "runner-up"]
                if kinds[-1] == "switch" and (sm or letter):
                    switch_to = sm.group(1).upper() if sm else letter.pop()
            else:
                kinds.append(kind)
                edit, strong = edit or bool(ed), strong or ed == 2  # a switch keeps its reasons ('A is too heavy')
        acts = set(k for k in kinds if k in ("switch", "runner-up"))
        if kinds == ["content"] and len(rows[0][1]) == 1:
            _say(why, _ONE_WORD)
            return {}
        if "content" in kinds and off and not acts:  # 'Switch to B? Costs matter more'
            _say(why, "Your reply mentions a switch and also says more: reply only the one you want.")
            return {}
        if "content" in kinds and not acts and "yes" not in kinds and edit:
            return {"action": "changes", "changes": t}
        cur = ((ctx.state.get("choice") or {}).get("arch") if ctx is not None else None) or ""
        if switch_to and switch_to == cur.upper() and re.search(r"\bapprov\w*\b", t, re.I) and not re.search(
                r"\bswitch", t, re.I):  # 'Runner-up? No, approve A.': A is the current one
            kinds = ["yes" if k == "switch" else k for k in kinds]
            acts.discard("switch")
        if acts and "yes" in kinds and re.search(r"\bapprov\w*", t, re.I):  # 'approve (switch to B)'
            _say(why, "Your reply both approves and switches: reply one of them.")
            return {}
        if len(acts) == 1 and not strong and ("no" not in kinds or kinds[0] == "no" and "no" not in kinds[1:]):
            # 'no, switch to C': the no refuses the proposal as it is
            act = acts.pop()
            return {"action": act, "switch_to": switch_to} if act == "switch" and switch_to else {"action": act}
        if "yes" in kinds and set(kinds) <= set(("yes", "refused", "none")):
            return {"action": "approve"}
        _say(why, "Your reply both %s and asks for changes." % ("approves" if "yes" in kinds else "switches")
             if "content" in kinds and (edit or acts) else "Your reply names both `switch` and `runner-up`."
             if len(acts) > 1 else "Your reply says no without saying what to change."
             if set(kinds) & set(("no", "refused")) else
             "Your reply approves and also says more: reply `approve`, or `changes: <what to change>`."
             if "yes" in kinds or "mixed" in kinds else
             "Your reply does not say what to change: reply `approve`, or `changes: <what to change>`."
             if "content" in kinds else "Your reply neither approves nor says what to change.")
        return {}
    if gid == "G14":
        # publishing copies the run into the user's repository: `publish` in a negated or deferring clause ('publish
        # nothing', 'hold off on publishing', 'publishing can wait'), or before a bare refusal ('Publish? No.',
        # 'publish? not yet'), refuses it; `publishing` / `published` consent only beside a confirmation ('publishing
        # is fine'); a clause led by `but` after a publish drops what it names ('publish everything but the ADRs'); a
        # reply that publishes and refuses, or refuses and names what to publish ("don't publish, just the
        # architecture"), is asked again. An exclusion in other words is `except` ('apart from', 'other than',
        # 'excluding', 'minus', 'leave out', 'all bar'), and so is a clause after a publish that keeps an item
        # ('keep the proposal private'); 'the proposal too' and 'as well' add, 'and nothing else' is `only`, and a
        # clause of `none` alone is the handoff none ('Sure, publish. None.')
        out, tt = {}, t.translate(_QUOTES).lower()
        if re.search(r"\bno\W+really\b|\bpublish\w*[^\S\n]+(?:no|nope|nah)\b(?![^\S\n]+handoff\b)", tt):
            # 'Publish. No, really.', 'publish no ce speckit none'
            _say(why, "Publish (all, or which of architecture / adr / proposal) or `no`?")
            return out
        # a note in brackets ('(it links ADR 0001-0003)'), and an emoji between two words ('publish <thumbs-up> none')
        tt = re.sub(r"\((?:it|this|that|they|which|as|because|since|e\.g\.|i\.e\.|see|note|fyi)\b[^()\n]*\)", " ", tt)
        tt = re.sub("(?<=\\w)[^\\S\\n]+[^\\w\\s\\x00-\\x7f–—]+[^\\S\\n]+(?=\\w)", ", ", tt)
        tt = re.sub(r"^([^\w\n]*publish)[^\S\n]*:", r"\1,", tt, flags=re.M)  # 'publish: not the proposal'
        # the card's long name of a handoff ('Compound Engineering ce-plan')
        tt = re.sub(r"\bcompound[^\S\n]+engineering(?:[^\S\n]+ce-plan)?\b|\bce-plan\b", "ce", tt)
        tt = re.sub(r"\b(?:arch|archs|architectures)\b", "architecture", tt)
        tt = re.sub(r"\b(?:adrs|decisions|decision records?)\b", "adr", re.sub(r"\bproposals\b", "proposal", tt))
        tt = re.sub(r"\bspec[\s-]?kit\b", "speckit", tt)
        # the card: 'Publish copies into the repository'; a copy after an article, a possessive or an adjective is the
        # noun ('I already have a copy', 'the paper copy on the fridge'), no publish
        tt = re.sub(r"\b(?:(a|an|the|my|our|your|his|her|their|its|own|one|another|extra|spare|paper|hard|printed|"
                    r"backup|local|pdf)\s+)?(cop(?:y|ied|ying))\b", lambda m: m.group(0) if m.group(1) else {
                        "copy": "publish", "copied": "published"}.get(m.group(2), "publishing"), tt)
        tt = re.sub(r"\b(?:apart\s+from|other\s+than|besides|excluding|minus|not\s+including|leav(?:e|ing)\s+out|"
                    r"without)\b", " except", tt)
        tt = re.sub(r"\b(all|everything)\s+(?:bar|save)\b", r"\1 except", tt)
        tt = re.sub(r"\b(publish\w*)\s+including\b", r"\1 all including", tt)  # 'publish including the proposal'
        tt = re.sub(r"\btoo\b(?=(?:\s+(?:please|pls|thanks|thx))?\s*(?:[,;.!?)]|$))", "also",
                    re.sub(r"\b(?:and\s+)?nothing\s+else\b", "only", tt))
        # a note after `publish:` that names nothing to publish ('publish: the team asked why we did not share it'),
        # and a reason ('publish everything as the team hasn't seen it')
        m = re.match(r"(\W*publish\w*(?:\s+(?:it\s+)?(?:all|everything))?)\s*:(.*)$", tt, re.S)
        if m and not re.search(r"\b(?:architecture|adr|proposal|all|everything|none|no|nothing|ce|speckit|"
                               r"superpowers|openspec|handoff)\b|^\W*(?:not|never|later|wait|hold|\w+n't)\b",
                               m.group(2)):
            tt = m.group(1)
        tt = "\n".join(_cut_reason(ln) for ln in tt.split("\n"))
        # 'publish all, don't share it' refuses what it publishes; a report of the past is no order ('publish: the
        # team asked why we did not share it')
        tt = re.sub(r"(\b(?:did|didn't|didnt|has|have|had|hasn't|haven't|hadn't|was|wasn't|were|weren't)\s+(?:not\s+|"
                    r"never\s+|yet\s+|been\s+)*)?\b(?:shar|distribut|releas)(?:e|es|ed|ing)\b",
                    lambda m: m.group(0) if m.group(1) else "publish", tt)
        publish = refuse = every = hold = False
        items, dropped, named, refused, loose, prev, stray, after_no = [], set(), [], set(), [], [], set(), False
        keys = ("publish", "architecture", "adr", "proposal", "ce", "speckit", "superpowers", "openspec")
        for _c, w, neg, no in _read(tt, names=lambda c, w: bool(re.search(
                r"\b(?:publish\w*|architecture|adr|proposal|ce|speckit|superpowers|openspec|handoff)\b", c)),
                scope=lambda x: x in keys):
            neg = neg or no or bool(_SELF_PUB.search(_c))  # "I'll publish it myself"
            if after_no and not neg and not set(w) & set(keys) and "handoff" not in w and not any(
                    x.startswith("publish") for x in w) and w[:1] not in (
                    ["i"], ["we"], ["i'm"], ["we're"], ["i've"], ["we've"], ["it's"], ["they"]):
                stray.update(w)  # a clause after a bare no that neither publishes nor names a handoff ('none,
                # Compound Eng.'), not a remark with its own subject ('no, I already have a copy')
            after_no = after_no or bool(w) and set(w) - _COURTESY <= NO_WORDS | set(("none", "nothing", "skip"))
            says = "publish" in w or any(x in ("publishing", "published") for x in w) and (
                neg or any(x in YES_WORDS or x in ("like", "want", "wants") for x in w))
            got = [x for x in ("architecture", "adr", "proposal") if x in w]
            every = every or says and not neg and bool(set(w) & set(("all", "everything")))
            if says and neg and not got and prev and set(w) & set(("it", "them", "that", "those")):
                dropped.update(prev)  # "The proposal isn't final, so don't publish it": `it` is the item before
                continue
            prev = got
            if says:
                publish, refuse = publish or not neg, refuse or neg
            keeps = set(w) & set(("keep", "stay", "stays", "private", "local", "confidential"))
            if neg or publish and not says and (w[:1] == ["but"] and not set(w) & set(("also", "and", "well")) or
                                                keeps or set(w) & set(("here", "leave"))):
                dropped.update(got)
                hold = hold or not got and not neg and bool(keeps)  # 'publish it but keep it private'
            else:
                items.extend(got)
                loose.extend([] if says else got)
            hs = [h for h in ("ce", "speckit", "superpowers", "openspec") if h in w]
            (refused.update if neg else named.extend)(hs)
            if "handoff" in w and not hs and ("none" in w or neg) or [x for x in w if x not in ("and", "then")] == [
                    "none"]:
                named.append("none")  # 'handoff: none', 'no handoff', a clause of `none` alone
        if publish and refuse or (refuse or re.match(r"\W*(?:no|nah|nope)\b", tt)) and (loose or dropped):
            # 'no, just the architecture'
            _say(why, "Your reply both publishes and refuses to publish.")
        elif publish and hold:
            _say(why, "Your reply publishes and keeps it private: name what to publish, or reply `no`.")
        elif publish:
            # 'everything, the proposal too' ('everything, just the architecture' publishes the architecture)
            items = ["architecture", "adr", "proposal"] if every and items and not re.search(
                r"\b(?:just|only)\b", tt) else items
            got = [x for x in ("architecture", "adr", "proposal") if (x in items or not items) and x not in dropped]
            if not items and not dropped and not every and re.search(
                    r"\b(?:(?:that|this|the|which)\s+one|(?:one|two)\s+of\s+(?:them|those|these))\b", tt):
                _say(why, "Your reply points to an item without naming it: name what to publish (architecture, adr, "
                          "proposal), or `publish` for all.")
                return out
            if "adr" in dropped and set(got) & set(("architecture", "proposal")):
                _say(why, "The ADRs go with the architecture and proposal copies: publish them too, or leave those "
                          "out.")
                return out
            out["publish"] = (got or False) if items or dropped else True
        elif refuse or not items and re.search(r"\b(no|nah|nope|none|skip|nothing)\b", tt):  # 'proposal, none' asks
            out["publish"] = False
        elif items or "\u2705" in tt or set(_words(tt)) & set(("all", "everything")) or any(
                x in YES_WORDS and x not in _COURTESY for x in _words(tt)) or \
                set(_words(tt)) - set(keys) - _COURTESY - _G14_HANDOFF_FILL:
            # 'polish all, ce', 'all + ce', 'publica todo, ce': words beside the handoff
            _say(why, "Publish (all, or which of architecture / adr / proposal) or `no`?")
        named = [h for h in dict.fromkeys(named) if h not in refused]
        if len(named) == 1:
            out["handoff"] = named[0]
        elif named:
            _say(why, "Your reply names more than one handoff (%s)." % ", ".join(named))
        elif re.match(r"^\s*(no|nah|nope|none|skip)\b", tt):
            out["handoff"] = "none"
        if out.get("publish") is False and out.get("handoff") == "none" and stray - _COURTESY - _G14_HANDOFF_FILL - \
                NO_WORDS - set(("none", "nothing", "skip", "now", "yet", "thank", "you", "today", "it")):
            # 'none, Compound Eng.': a handoff in words the reader cannot read is no `none`
            del out["handoff"]
            _say(why, "Your reply has words I cannot read beside `no`: name the handoff (ce, speckit, superpowers, "
                      "openspec) or reply `none`.")
        m = re.search(r"merge\s*(?::\s*)?(all|some|none|defer)", tt)
        if m:
            out["merge_terms"] = m.group(1)
        return out
    if gid == "GB":
        if not t:
            return {"stop": True}
        # a raise spends more requests: one cap no negation refuses ('raise to 300? no.') and no `stop`; `stop` and a
        # cap ('stop at 120') are asked again, and so is a raise by an amount ('raise by 50', '100 more'). A cap has
        # at most 9 digits (int() refuses a 4301-digit text). A note in brackets and a number the reply cites ('the
        # card says 65 more', 'the budget of 180 requests') are no cap; a raise with no cap beside `stop` ('raise the
        # cap, then stop') is asked again.
        t = _STOP_IDIOM.sub("stop", _drop_notes(gid, _GB_CITED, t))
        t = re.sub(_REASON.pattern + r"[^,;.!?\n]*", " ", t, flags=re.I)  # its numbers are no cap ('bc ~65 more')
        if re.search(r"\bby\s+\d|\badd\s+\d|(?<!\d)\d+\s+more\b|\banother\s+\d|\bextra\s+\d|\+\s*\d", t, re.I):
            _say(why, "Reply the new cap as the total number of requests (`raise to 300`), or `stop`.")
            return {}
        chosen, refused = _named(re.sub(r"(?<=\d),(?=\d{3}(?!\d))", "", t),
                                 lambda w: w == "stop" or w.isdecimal() and len(w) <= 9)
        caps = set(int(x) for x in chosen if x != "stop" and x not in refused)
        if "stop" in chosen and "stop" not in refused and not caps:
            if any(not a and re.search(r"\b(?:raise|increase|bump|lift|extend|double|up\s+(?:the|it|my|our))\b", c,
                                       re.I) and not re.search(
                    r"\b(?:will|shall|going\s+to|later|next)\b|'ll\b", c, re.I) and not _negated(
                    [x for x in _words(c) if x != "stop"]) for c, a in _clauses(t)):  # not 'raise to 300? no, stop'
                _say(why, "Your reply names a raise and `stop`: reply the new cap, or `stop`.")
                return {}
            return {"stop": True}
        if len(caps) == 1 and "stop" not in chosen:
            return {"raise_to": caps.pop(), "stop": False}
        _say(why, "Your reply names `stop` and a cap." if caps and "stop" in chosen else
             "Your reply names more than one cap." if caps else
             "Your reply names %s in a negation." % " and ".join("`%s`" % x for x in sorted(set(refused)))
             if refused else "Your reply names neither a cap nor `stop`.")
        return {}
    if gid == "GX":
        # 'keep going', 'go on', 'carry on' say continue; a keyword someone else said is no answer ('The synthesis
        # said STOP but I disagree')
        said = re.sub(r"\b(?:keep\s+(?:going|at\s+it)|go\s+on|carry\s+on|proceed|(?:be|been|is|being)\s+continued)\b",
                      "continue", _STOP_IDIOM.sub("stop", t), flags=re.I)  # 'Please proceed with the plan'
        said = _GX_CITED.sub(r"\1\2", said)
        a = _pick(said, ("reframe", "continue", "stop"), why)
        # 'continue but change the question a bit'
        if a == "continue" and (re.search(r"\b(?:change|reword|rephrase|different|new|edit|adjust|tweak|alter|"
                                          r"narrow|widen)\w*\s+(?:\w+\s+){0,3}(?:question|problem|frame|framing)\b",
                                          said, re.I) or any(w[:1] == ["but"] and _imperative(w[1:])
                                                             for _c, w, _n, _o in _read(said))):
            _say(why, "Your reply continues and changes the question: reply `reframe` to change it, or `continue`.")
            return {}
        return {"action": a} if a else {}
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
    if gid == "G11" and (provided or {}).get("choice") and (provided or {}).get("accept_recommendation") is None:
        ans["accept_recommendation"] = False  # a choice the host wrote wins over an acceptance only the parser read
    if gid == "G13" and (provided or {}).get("switch_to") and not (provided or {}).get("action"):
        ans["action"] = "switch"  # an architecture the host wrote wins over the reply's `yes` (approve)
    return ans


def from_choice(gid, choice):
    ans = {"reply": choice}
    return ans


# ================================================================ answer types (#16)

_STR = {"type": ["string", "null"]}
_BOOL = {"type": ["boolean", "null"]}
_STRS = {"type": "array", "items": {"type": "string"}}
_ADRS = {"type": "array", "items": {"type": ["string", "integer"]}}  # G12: the ADR numbers the card shows (3 or "3")


def _enum(*values):
    return {"type": ["string", "null"], "enum": list(values) + [None]}


# The type of every field of every gate's answer (answer_template plus "reply"); prepare_answer checks the merged answer
# against it with schema_lite, and a field that is not listed is refused.
ANSWER_TYPES = {
    "G0": {"confirm": _BOOL, "topic": _STR, "mode": _enum(*MODES), "variant": _enum(*VARIANTS),
           "autopilot": _enum(*AUTOPILOTS), "private": _BOOL,
           "privacy": {"type": "object", "properties": {"web": _BOOL, "vendors": _BOOL, "code": _BOOL},
                       "additionalProperties": False},
           "families": {"type": ["array", "null"], "items": {"type": "string"}}, "with_ce_ideate": _BOOL,
           "seeds": {"type": "object", "properties": {"problem": _STR, "primary": _STR, "ideas": _STRS,
                                                      "obvious": _STRS, "off_limits": _STRS},
                     "additionalProperties": False},
           "skip_seeds": _BOOL, "idea": _STR,
           "quick": {"type": "object", "properties": {"criteria": _STRS, "hard_constraint": _STR},
                     "additionalProperties": False}},
    "G1": {"done": _BOOL, "skip": _BOOL},
    "G2": {"answers": {"type": "array", "items": {"type": "object", "properties": {
        "q": {"type": ["string", "integer"]}, "a": _STR}, "required": ["q"]}}, "accept_defaults": _BOOL},
    "G2c": {"confirm": _BOOL, "corrections": _STR},
    "G2f": {"restore": _BOOL},
    "G3": {"ideas": _STRS, "cells": {"type": "array", "items": {"type": ["string", "array"],
                                                                "items": {"type": "string"}}}},
    "G4": {"rescue": {"type": "array", "items": {"type": "object", "properties": {"id": {"type": "string"},
                                                                                   "reason": _STR},
                                                 "required": ["id"]}}, "confirm_flags": _STRS},
    "G5": {"kill": _STRS, "keep": _STRS},
    "G6": {"finalists": _STRS},
    "G7": {"picks": _STRS},
    "G8a": {"picks": _STRS, "skip": _BOOL, "notes": _STR},
    "G8b": {"chosen": _STR, "runner_up": _STR, "bundle": _STRS, "park": _STRS, "why": _STR,
            "accept_recommendation": _BOOL},
    "G9": {"result": _STR, "note": _STR},
    "G10": {"confirm": _BOOL, "corrections": _STR},
    "G11": {"choice": _STR, "steal": {"type": "array", "items": {"type": ["object", "string"]}}, "notes": _STR,
            "accept_recommendation": _BOOL},
    "G12": {"accept": _ADRS, "reject": _ADRS},
    "G13": {"action": _enum("approve", "changes", "switch", "runner-up"), "changes": _STR, "switch_to": _STR},
    "G14": {"publish": {"type": ["boolean", "array", "null"], "items": {"enum": ["architecture", "adr", "proposal"]}},
            "merge_terms": _enum("all", "some", "none", "defer"), "terms": _STRS,
            "handoff": _enum("ce", "speckit", "superpowers", "openspec", "none")},
    "GB": {"raise_to": {"type": ["integer", "null"], "minimum": 1}, "stop": _BOOL},
    "GX": {"action": _enum("reframe", "continue", "stop")},
}
# list fields that hold idea IDs: a string there is read with ID_RE
ID_LISTS = {"G4": ("confirm_flags",), "G5": ("kill", "keep"), "G6": ("finalists",), "G7": ("picks",),
            "G8a": ("picks",), "G8b": ("bundle", "park")}


def answer_schema(gid):
    props = {"reply": _STR}
    props.update(ANSWER_TYPES.get(gid, {}))
    return {"type": "object", "properties": props, "additionalProperties": False}


NO_IDS = ("", "none", "no", "nothing", "-", "ok", "skip")  # an ID-list field written as one of these means []


def _coerce(gid, provided):
    """Obvious shape slips in an answer file, repaired with a note each: a string where a list of idea IDs belongs is
    read with ID_RE ("I-003" -> ["I-003"]; "none" -> []), a string where a list of texts belongs becomes a one-item
    list, "yes" / "no" where a boolean belongs becomes true / false, a number written as text becomes a number.
    Anything else is left for the type check. Text with no idea ID in an ID-list field (G5 {"kill": "all"}) is an
    error, never an empty list. Returns (provided copy, notes, errors)."""
    types = ANSWER_TYPES.get(gid, {})
    out, notes, errs = {}, [], []
    for k, v in (provided or {}).items():
        want = (types.get(k) or {}).get("type")
        want = want if isinstance(want, list) else [want]
        if isinstance(v, str) and k in ID_LISTS.get(gid, ()):
            ids = list(dict.fromkeys(_ids(v)))
            if not ids and v.strip().lower() not in NO_IDS:
                errs.append("%s: %r names no idea ID; write the IDs (for example [\"I-003\"]) or [] (the answer for "
                            "%s)" % (k, v[:40], gid))
            notes.append("%s %s: the text %r was read as the list %s" % (gid, k, v[:40], ids))
            v = ids
        elif isinstance(v, str) and "boolean" in want and _yesno(v) is not None:
            notes.append("%s %s: %r was read as %s" % (gid, k, v, str(_yesno(v)).lower()))
            v = _yesno(v)
        elif isinstance(v, str) and "array" in want:
            v = [x for x in re.split(r"[,\s]+", v) if x] if k == "families" or gid == "G12" else [v]
            notes.append("%s %s: the text was read as the list %s" % (gid, k, v))
        elif isinstance(v, str) and "integer" in want and v.strip().isdecimal() and len(v.strip()) <= 9:
            notes.append("%s %s: %r was read as the number %s" % (gid, k, v, int(v)))
            v = int(v)
        elif gid == "G14" and k == "publish" and v == []:
            notes.append("G14 publish: [] was read as false (publish nothing)")
            v = False
        out[k] = v
    return out, notes, errs


def prepare_answer(ctx, gid, provided):
    """An answer file (or --choice / default / terminal reply) -> (answer, notes, errors) (#16). The answer is an
    object like the answer template, or a string (the reply); any other JSON value is refused. Unknown fields are
    refused, and so is a `reply` that is not text (it is parsed before the type check); obvious shape slips are repaired
    with a note (_coerce); an idea ID named twice in a list counts once (a note says so); the merged answer is
    type-checked against ANSWER_TYPES (schema_lite) before validate() checks its content (IDs against the run's ideas,
    counts, choices)."""
    if isinstance(provided, str):
        provided = {"reply": provided}
    elif not isinstance(provided, dict):
        return merge_answer(gid, {}, ctx), [], [
            "the answer must be a JSON object like the answer template, or the reply as a JSON string; got %s (the "
            "answer for %s)" % (schema_lite._type_of(provided), gid)]
    known = set(answer_template(gid))
    unknown = sorted(k for k in provided if k not in known)
    if unknown:
        return merge_answer(gid, {}, ctx), [], ["%s has no field %s; its fields are: %s" % (
            gid, ", ".join(unknown), ", ".join(sorted(known)))]
    errs = _type_errors(gid, {"reply": provided.get("reply")}, {"type": "object", "properties": {"reply": _STR}})
    if errs:
        return merge_answer(gid, {}, ctx), [], errs
    provided, notes, errs = _coerce(gid, provided)
    if errs:
        return merge_answer(gid, {}, ctx), notes, errs
    ans = merge_answer(gid, provided, ctx)
    for k in ID_LISTS.get(gid, ()):
        ids = ans.get(k)
        if isinstance(ids, list) and all(isinstance(i, str) for i in ids) and len(set(ids)) < len(ids):
            ans[k] = list(dict.fromkeys(ids))  # the count rules (G6 at least 2, G7 3 or 4) count distinct ideas
            notes.append("%s %s: duplicate IDs removed (%s)" % (gid, k, ", ".join(ans[k])))
    errs = _type_errors(gid, ans, answer_schema(gid))
    if gid == "G12" and not errs:
        # the ADRs by their number ('0003'), however the answer names them: 3, "3", "ADR-0003", "0003-slug"
        for k in ("accept", "reject"):
            ans[k] = list(dict.fromkeys("all" if str(x).strip().lower() == "all" else adr_key(x) or x
                                        for x in ans.get(k) or []))
    return ans, notes, errs or validate(ctx, gid, ans)


def _type_errors(gid, value, schema):
    return ["%s (the answer for %s)" % (e.replace("$.", "", 1), gid) for e in schema_lite.validate(value, schema)]


# ================================================================ validation

def validate(ctx, gid, ans):
    """Errors (list of str) for an answer; the gate is re-asked with the first error."""
    reply = ans.get("reply") or ""
    if reply.strip() and not _WORD.search(reply) and all(_empty(v) for k, v in ans.items() if k != "reply"):
        return ["Your reply has no words in it. " + how_to_reply(ctx, gid)]  # '?', '...', an emoji
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
        settings = any(ans.get(k) for k in ("mode", "variant", "autopilot", "topic"))
        doubts = []
        parse_kickoff(reply, doubts)
        # a privacy request, a setting in a sentence or an unreadable privacy value is asked again always (the reply
        # would reach the vendors), a line that mixes the reply with other words at the kickoff; a seed line that
        # reads as a deferral or a hedge only when the reply confirms nothing and changes nothing
        doubt = next((w for k, w in doubts if k in ("privacy", "setting", "text") or k == "reply" and not lite),
                     None) or next(
            (w for k, w in doubts if k == "seed" and not lite and ans.get("confirm") is not True and not settings),
            None)
        if doubt:
            errs.append(doubt)
        elif ans.get("confirm") is False and not lite and not settings:
            errs.append("Tell me what to change, or reply `go`.")
        if lite and not settings and _v1_offer(ans) is None:
            errs.append(how_to_reply(ctx, gid))  # the v1-run offer extends only on a `go`, stops only on a refusal
    elif gid == "G1":
        if ans.get("done") and not ans.get("skip"):
            text = ctx.read("00_HUMAN_SEEDS.md")
            if not (registry.section(text, "Ideas") or registry.section(text, "Primary idea") or
                    re.search(r"^[^\w\n]*SKIPPED\b", text, re.M)):
                errs.append("The seeds file has no ideas yet: write them in the Ideas section (or reply `skip`).")
        elif not ans.get("done") and not ans.get("skip"):
            errs.append("Reply `done` when the seeds file is written, or `skip`." + _unclear(ctx, gid, ans))
    elif gid == "G2":
        if not ans.get("answers") and not ans.get("accept_defaults") and not (ans.get("reply") or "").strip():
            errs.append("Answer the questions by number, or reply `ok` to accept the defaults.")
    elif gid in ("G2c", "G10"):
        if not ans.get("confirm") and not ans.get("corrections"):
            errs.append("Reply `ok` to confirm, or write your corrections." + _unclear(ctx, gid, ans))
    elif gid == "G2f":
        if ans.get("restore") is None:
            errs.append("Reply `restore` or `keep`." + _unclear(ctx, gid, ans))
    elif gid == "G4":
        if len(ans.get("rescue") or []) > 2:
            errs.append("At most 2 rescues.")
        known = set(registry.idea_lines(ctx))
        for r in ans.get("rescue") or []:
            if isinstance(r, dict) and known and r.get("id") not in known:
                errs.append("unknown idea %s" % r.get("id"))
        errs += _unknown_ids(ans.get("confirm_flags"), known, "an idea of this run")
        rescued = [r.get("id") for r in ans.get("rescue") or [] if isinstance(r, dict)]
        errs += ["%s is both confirmed (killed) and rescued: name it once" % i
                 for i in ans.get("confirm_flags") or [] if i in rescued]
        why = _unclear(ctx, gid, ans)
        if why:
            errs.append(HOW_TO_REPLY["G4"] + why)
    elif gid == "G5":
        errs += _unknown_ids((ans.get("kill") or []) + (ans.get("keep") or []), ctx.state.get("k4_candidates") or [],
                             "a K4 candidate")
        errs += ["%s is both killed and kept: name it once" % i for i in ans.get("kill") or []
                 if i in (ans.get("keep") or [])]
        why = _unclear(ctx, gid, ans)
        if why:
            errs.append(HOW_TO_REPLY["G5"] + why)
    elif gid == "G6":
        fin = ans.get("finalists") or []
        why = "" if fin else _unclear(ctx, gid, ans)
        if why:
            errs.append(HOW_TO_REPLY["G6"] + why)
        if len(fin) > 8:
            errs.append("At most 8 finalists.")
        if fin and len(fin) < 2:
            errs.append("Name at least 2 finalists (the tournament compares pairs), or reply `ok`.")
        errs += _unknown_ids(fin, registry.finalist_pool(ctx), "in the finalist pool")
    elif gid == "G7":
        fin = ctx.state.get("finalists") or []
        why = "" if ans.get("picks") else _unclear(ctx, gid, ans)
        if why:
            errs.append(HOW_TO_REPLY["G7"] + why)
        errs += _unknown_ids(ans.get("picks"), fin, "a finalist")
        if ans.get("picks") and not min(3, len(fin) or 1) <= len(ans["picks"]) <= 4:
            errs.append("Pick 3 or 4 ideas." if len(fin) >= 3 else "Pick %d to 4 ideas." % len(fin))
    elif gid == "G8a":
        picks = ans.get("picks") or []
        fin = ctx.state.get("finalists") or []
        if not ans.get("skip") and not picks:
            errs.append("Name up to 3 finalist IDs (for example I-014), or reply `skip`." + _unclear(ctx, gid, ans))
        bad = [p for p in picks if fin and p not in fin]
        if bad:
            errs.append("%s is not a finalist (finalists: %s)" % (", ".join(bad), ", ".join(fin)))
        if len(picks) > 3:
            errs.append("At most 3 picks.")
    elif gid == "G8b":
        allowed = ctx.state.get("top") or ctx.state.get("finalists") or []
        if not ans.get("accept_recommendation") and not ans.get("chosen"):
            errs.append("Name the idea you choose (an ID such as %s), or reply `ok` for the suggestion."
                        % (allowed[0] if allowed else "I-001") + _unclear(ctx, gid, ans))
        if ans.get("chosen") and allowed and ans["chosen"] not in (ctx.state.get("finalists") or allowed):
            errs.append("%s is not one of the finalists (%s)" % (ans["chosen"], ", ".join(allowed)))
        errs += _unknown_ids(([ans["runner_up"]] if ans.get("runner_up") else []) + (ans.get("park") or []) +
                             (ans.get("bundle") or []), ctx.state.get("finalists") or allowed, "a finalist")
        if ans.get("runner_up"):  # the idea _apply_g8b records as chosen
            chosen = ans.get("chosen") if ans.get("chosen") and not ans.get("accept_recommendation") else \
                registry.suggestion(ctx)[0]
            if ans["runner_up"] == chosen:
                errs.append("The runner-up must be another idea than the chosen one (%s)." % chosen)
        chosen = ans.get("chosen") if ans.get("chosen") and not ans.get("accept_recommendation") else \
            registry.suggestion(ctx)[0]
        errs += ["%s is both %s and parked: name it once" % (i, "chosen" if i == chosen else "the runner-up")
                 for i in ans.get("park") or [] if i in (chosen, ans.get("runner_up"))]
    elif gid == "G9":
        if (ans.get("result") or "").upper() not in ("PASSED", "MISSED", "INCONCLUSIVE"):
            errs.append("Reply `passed`, `missed` or `inconclusive`." + _unclear(ctx, gid, ans))
    elif gid == "G11":
        labels = registry.arch_labels(ctx)
        if not ans.get("accept_recommendation") and not ans.get("choice"):
            errs.append("Reply `ok` for the suggestion or a letter (%s)." % ", ".join(labels or ["A", "B"]) +
                        _unclear(ctx, gid, ans))
        if ans.get("choice") and labels and ans["choice"] not in labels:
            errs.append("%s is not a candidate (%s)" % (ans["choice"], ", ".join(labels)))
        elif ans.get("choice") and ans.get("accept_recommendation"):
            sug = g11_recommendation(ctx)[0]
            if ans["choice"] != sug:
                errs.append("You named %s and also accepted the suggestion (%s): reply the letter you choose, or "
                            "`ok`." % (ans["choice"], sug))
    elif gid == "G13":
        if ans.get("action") not in ("approve", "changes", "switch", "runner-up"):
            errs.append("Reply `approve`, `changes: ...`, `switch <letter>` or `runner-up`." +
                        _unclear(ctx, gid, ans))
        if ans.get("action") == "switch":
            cur = (ctx.state.get("choice") or {}).get("arch")
            others = [x for x in registry.arch_labels(ctx) if x != cur]
            if ans.get("switch_to") and ans["switch_to"] == cur:
                errs.append("%s is the current architecture: name another one (%s), or reply `approve`."
                            % (cur, ", ".join(others) or "none"))
            elif not ans.get("switch_to") or (others and ans["switch_to"] not in others):
                errs.append("Name the architecture to switch to (%s)." % ", ".join(others))
        elif ans.get("switch_to") and ans.get("action") in ("approve", "changes", "runner-up"):
            errs.append("Your answer names architecture %s but does not switch: reply `switch %s`, or `%s`."
                        % (ans["switch_to"], ans["switch_to"], ans["action"]))
        if ans.get("action") == "runner-up" and not (ctx.state.get("choice") or {}).get("runner_up"):
            errs.append("No runner-up was recorded at the decision.")
        if ans.get("action") == "changes" and int((ctx.state.get("counters") or {}).get("g13_loops", 0)) >= 2:
            errs.append("Two change rounds are already done; reply `approve`, `switch` or `runner-up`.")
    elif gid == "G12":
        # prepare_answer keyed every ADR it could read by its number; an ADR the run does not have is asked again
        known = sorted(os.path.basename(p)[:4] for p in _adr_files(ctx))
        names = ", ".join(str(int(n)) if n.isdigit() else n for n in known) or "none"
        acc, rej = ans.get("accept") or [], ans.get("reject") or []
        bad = [x for x in acc if x != "all" and x not in known] + [x for x in rej if x != "all" and x not in known]
        if bad:
            errs.append("ADR %s does not exist (ADRs: %s)" % (", ".join(
                str(int(x)) if adr_key(x) == x else repr(x) for x in bad), names))
        if "all" in rej:
            errs.append("Name the ADRs you reject by number (ADRs: %s)." % names)
        both = [x for x in acc if x in rej and x in known]
        if both:
            errs.append("ADR %s is both accepted and rejected: name it once" % ", ".join(str(int(x)) for x in both))
        if not acc and not rej and (ans.get("reply") or "").strip():
            errs.append("Reply `ok` to accept every ADR, or name them by number: `ok, reject 3` or `accept 1 2, "
                        "reject 3`." + _unclear(ctx, gid, ans))
    elif gid == "G14":
        options = g14_options(ctx)
        if ans.get("handoff") and ans["handoff"] not in options:
            errs.append("The handoff must be one of %s." % ", ".join(options))
        # a reply that settles neither publish nor a handoff is asked again, and so is one that leaves the handoff to
        # the variant default when that default is a handoff (handoff.chosen_handoff: ce on a software or growth run);
        # a field the host filled itself wins (_unclear)
        why = _unclear(ctx, gid, ans) if ans.get("publish") is None or ans.get("handoff") is None else ""
        if not why and reply.strip() and not _host_filled(ctx, gid, ans):
            if ans.get("publish") is None and ans.get("handoff") is None:
                why = " Publish (all, or which of architecture / adr / proposal) or `no`?"
            elif ans.get("handoff") is None and ctx.variant in ("software", "growth"):
                why = " Which handoff: %s?" % ", ".join("`%s`" % o for o in options)
        if why:
            errs.append("Reply `publish` (or `publish architecture`, `publish proposal`, `publish adr`) or `no`, and "
                        "one handoff." + why)
    elif gid == "GB":
        if not ans.get("stop") and not ans.get("raise_to"):
            errs.append("Reply a new cap (a number of requests) or `stop`." + _unclear(ctx, gid, ans))
        elif ans.get("stop") and ans.get("raise_to"):  # {'reply': 'stop', 'raise_to': 300}
            errs.append("Reply a new cap (a number of requests) or `stop`, not both.")
        if ans.get("raise_to") and not ans.get("stop"):
            err = cap_error(ctx, ans["raise_to"])
            if err:
                errs.append(err)
    elif gid == "GX":
        if ans.get("action") not in ("reframe", "continue", "stop"):
            errs.append("Reply `reframe`, `continue` or `stop`." + _unclear(ctx, gid, ans))
    return errs


def _empty(v):
    return v in (None, "", [], {}) or isinstance(v, dict) and all(_empty(x) for x in v.values())


def _unclear(ctx, gid, ans):
    """' <why>' when the reply alone left the answer unclear (what parse_reply could not read in it), else ''. Nothing
    is unclear when the host filled a field itself (a value the reply does not give it): the host's fields win."""
    why = []
    if (ans.get("reply") or "").strip() and not _host_filled(ctx, gid, ans, why):
        return " " + why[0] if why else ""
    return ""


def _host_filled(ctx, gid, ans, why=None):
    got = parse_reply(gid, ans.get("reply") or "", ctx, why)
    return any(not _empty(v) and v != got.get(k) for k, v in ans.items() if k != "reply")


def _unknown_ids(ids, allowed, what):
    """One error for the IDs (of a list field) that are not in `allowed` (when the run knows its IDs yet)."""
    bad = [i for i in ids or [] if allowed and i not in allowed]
    return ["%s %s not %s (%s)" % (", ".join(bad), "is" if len(bad) == 1 else "are", what,
                                   ", ".join(sorted(allowed)))] if bad else []


def cap_error(ctx, cap):
    """Why `cap` cannot be the new budget.max_calls (it must cover the requests sent and the refused launch), or
    None. Used by GB and `ub budget`."""
    from . import progress
    try:
        cap = int(cap)
    except (TypeError, ValueError):
        return "the new cap must be a number of requests"
    b = progress.budget_status(ctx)
    if cap < b["used"] + max(1, b["need"]):
        return ("The new cap must be at least %d: %d requests were sent and the next job can send up to %d."
                % (b["used"] + max(1, b["need"]), b["used"], max(1, b["need"])))
    return None


# ================================================================ read-back (4.12)
# A reply the host wrote alone (every other field of the answer empty) acts at once only in a documented form: it says
# nothing but its own reading in the card's words (canonical). Any other reply is read back: nothing is applied, the
# reading waits in run.json ("readback") and the card asks with what the engine would do; a yes applies it
# (pipeline.answer_gate). The autopilot and defaults never read back, nor do G2 and G3 (the answers to the framing
# questions and the seed ideas are the user's own words, stored as written and shown in the files they fill) and G8a
# (the gut pick is only recorded: it changes no step, and a later gate shows it).
READBACK_GATES = frozenset(("G0", "G1", "G2c", "G2f", "G4", "G5", "G6", "G7", "G8b", "G9", "G10", "G11", "G12", "G13",
                            "G14", "GB", "GX"))
READBACK_HEAD = "I read your reply as: "
_FORM_CHARS = re.compile(r"[\w\s.,;:!&*`'+/%-]*")  # no question mark, quote, bracket, note sign or emoji
_CONFIRM_FILL = frozenset(("do", "it", "that", "that's", "this", "is", "what", "i", "we", "want", "meant", "mean",
                           "just", "then", "sir"))  # 'yes, do it', "yes, that's what I meant", 'ok then'
_G9_COUNTS = frozenset(("of", "out", "in", "per", "percent", "vs"))  # 'passed: 8 of 10'
# words that doubt a probe result ('passed, 11 of 20, but Maria thinks the target was 12')
_G9_DOUBTS = frozenset(("may", "might", "maybe", "perhaps", "think", "thinks", "unsure", "unclear", "doubt", "doubts",
                        "disputes", "disputed", "says", "said", "claims"))
# courtesy before or after a documented form ('please B', 'B, thanks'), matched from each end (the tail on the reversed
# text), so a flood stays linear
_COURTESY_HEAD = re.compile(r"(?:\W*\b(?:please|pls|plz)\b)+", re.I)
_COURTESY_TAIL = re.compile(r"\W*(?:\b(?:esaelp|slp|zlp|sknaht|uoy\s+knaht|xht|yt)\b\W*)+", re.I)


def _uncourteous(text):
    m = _COURTESY_HEAD.match(text)
    text = text[m.end():] if m else text
    m = _COURTESY_TAIL.match(text[::-1])
    return text[:len(text) - m.end()] if m else text


def _form_words(text):
    """The words of a reply in a documented form, without courtesy, `and` and the thousands comma ('raise to 1,000')."""
    return [w for w in _words(re.sub(r"(?<=\d),(?=\d{3}(?!\d))", "", text)) if w not in _COURTESY and w != "and"]


def _bare_form(text):
    return bool(_FORM_CHARS.fullmatch((text or "").translate(_QUOTES)))


def confirms_only(text):
    """The reply is confirmation words only: YES_WORDS, YES_PHRASES and their aliases, courtesy ('yes', 'Go ahead!',
    'ok thanks', "yes, that's what I meant")."""
    w = _form_words(text or "")
    return _bare_form(text) and bool(w) and all(x in YES_WORDS or x in _CONFIRM_FILL for x in w) and any(
        x in YES_WORDS for x in w)


def refuses_only(text):
    """A plain `no` ('no', 'nope', 'no thanks')."""
    return _bare_form(text) and _yesno(text or "") is False


# a thumbs-up, an OK hand or a check mark (with a skin tone or the emoji selector) says yes to a reading
_THUMBS = re.compile("[\U0001F44D\U0001F44C\u2705\u2714\u2611][\U0001F3FB-\U0001F3FF\uFE0F]*")
_AMENDS = re.compile(r"\W*(?:yes|yeah|yep|yup|ya|y|ok|okay|k|sure|correct|right|no|nope|nah|n)\b\W*\w", re.I)


def _card_word(w, reading, text=""):
    """The card's own word beside a stored reading it contradicts: G13 `approve` beside a switch, the runner-up or a
    change round; `go` at the v1-run offer beside a stop, anywhere in the reply ('ok go', 'go go', "let's go"; not
    'go ahead', a yes to the reading)."""
    ans = (reading or {}).get("answer") or {}
    if w == ["publish"] and (reading or {}).get("gate") == "G14":  # beside a handoff or a narrower list
        return isinstance(ans.get("publish"), list) or ans.get("handoff") not in (None, "none")
    if ans.get("action") in ("switch", "runner-up", "changes"):
        return bool(set(w) & set(("approve", "approved")))
    return bool(re.search(r"\bgo\b(?!\W+ahead\b)", text, re.I)) and ((reading or {}).get("interrupt") or {}).get(
        "gate") == "G0" and _v1_offer(ans) == "stop"


def confirms_reading(text, reading=None):
    """A yes to a stored reading (4.12): confirmation words only (confirms_only), a thumbs-up, and `do it` / `do that`
    ('please do it', 'just do that'). Only the second turn reads these; a documented form is unchanged, so the card's
    own word beside a reading it contradicts (`reading`, the stored one: G13 `approve` to a switch, `go` to a v1 stop)
    is asked (approve_beside)."""
    t = _THUMBS.sub(" yes ", text or "")
    w = _form_words(t)
    if _card_word(w, reading, t):
        return False
    return confirms_only(t) or _bare_form(t) and w[-2:] in (["do", "it"], ["do", "that"]) and all(
        x in _CONFIRM_FILL for x in w)


def amends_reading(text):
    """A yes or no to a stored reading with more words after it ('yes and also kill I-007', 'no, I meant B')."""
    t = (text or "").translate(_QUOTES)
    return bool(_AMENDS.match(t)) and not confirms_reading(t) and not refuses_only(t)


def yes_beside(ctx, gid, text, ans, held):
    """A yes among other words ('The user says yes', a long reply ending 'So yes, do that.') that reads as the card's
    own confirmation (its `ok`) while another reading waits: a yes to the reading or the card's `ok`, so it is asked."""
    if not re.search(r"\b(?:yes|yeah|yep|yup)\b", text or "", re.I):  # a plain yes, not the card's own verb
        return False
    ok, _notes, errs = prepare_answer(ctx, gid, "ok")
    return not errs and describe(ctx, gid, ans) == describe(ctx, gid, ok) != describe(ctx, gid, held.get("answer"))


def _strict(ans):
    return bool(ans.get("private")) or any(v is False for v in (ans.get("privacy") or {}).values())


def drops_privacy(gid, ans, held):
    """G0 kickoff: a new reading, while one waits that keeps the run private (`private`, web or vendors off), that
    names no privacy of its own ('start', 'go now' beside "let's go, and keep it private"): it would send the reply to
    every vendor with web search on, so it is asked, and a yes still applies the waiting reading."""
    return gid == "G0" and _strict((held or {}).get("answer") or {}) and ans.get("private") is None and all(
        v is None for v in (ans.get("privacy") or {}).values())


def approve_beside(text, held):
    """The card's own word (_card_word: G13 `approve`, `go` at the v1-run offer), alone or with yes words ('yes,
    approve'), while a reading it contradicts waits: a yes to the reading or the card's word, so it is asked once; the
    word a second time is the card's own."""
    t = _THUMBS.sub(" yes ", text or "")
    w = _form_words(t)
    return _card_word(w, held, t) and not held.get("approve_asked") and _bare_form(t) and \
        all(x in YES_WORDS or x in _CONFIRM_FILL or x in ("approve", "approved", "publish") for x in w)


def drop_reading(ctx, gid):
    """The user answered `gid`: its reading (pending or a marker the run moved past) is used up. A reading or marker
    of another gate stays, so a late yes there still asks again."""
    rb = ctx.state.get("readback")
    if not isinstance(rb, dict):
        return
    rest = [g for g in rb.get("stale") or [] if g != gid]
    if rb.get("gate") in (gid, None):
        if rest:
            ctx.state["readback"] = {"stale": rest}
        else:
            ctx.state.pop("readback", None)
    elif rest:
        rb["stale"] = rest
    else:
        rb.pop("stale", None)


def _canon_g0(ctx, reply, ans):
    if (ctx.state.get("interrupt") or {}).get("gate") == "G0":  # the v1-run offer
        offer = _v1_offer(ans)
        return offer == "go" and (confirms_only(reply) or _bare_form(reply) and _form_words(reply) == [
            "extend"]) or offer == "stop" and _bare_form(reply) and _form_words(reply) == ["stop"]  # the card's words
    seeds = ans.get("seeds") or {}
    if any(seeds.get(k) for k in ("problem", "ideas", "obvious", "off_limits")) or ans.get("families") or \
            ans.get("with_ce_ideate") or ans.get("confirm") is False:
        return False  # a seed is free text: it is read back with the seeds as they will be stored
    got, priv, quick = {}, {}, {}
    for line in reply.split("\n"):
        m = re.match(r"\s*(topic|idea|primary(?:\s+idea)?|criteria|(?:hard\s+)?constraint)\s*:\s*(\S.*)$",
                     line.rstrip(), re.I)
        if m:  # a label and the user's own words after it; words that are no decision yet are read back
            key, val = m.group(1).lower(), m.group(2)
            if _label_doubt(val):
                return False
            if key.startswith("primary"):
                got["primary"] = val
            elif key == "criteria":
                quick["criteria"] = [c.strip() for c in re.split(r"[,;]", val) if c.strip()][:3]
            elif key.endswith("constraint"):
                quick["hard_constraint"] = val
            else:
                got[key] = val
            continue
        if not _bare_form(line):
            return False
        for k, v in re.findall(r"\b(web|vendors|code)\s*:\s*(yes|no)\b", line, re.I):
            priv[k.lower()] = v.lower() == "yes"
        line = re.sub(r"\b(?:web|vendors|code)\s*:\s*(?:yes|no)\b", " ", line, flags=re.I)
        toks = _form_words(re.sub(r"\b(hands|full)\s+(on|auto)\b", r"\1-\2", line, flags=re.I))
        for i, t in enumerate(toks):
            key = "mode" if t in MODES else "variant" if t in VARIANTS else "autopilot" if t in AUTOPILOTS else \
                "private" if t == "private" else "skip_seeds" if t == "skip" or toks[i:i + 2] == ["no", "seeds"] \
                else None  # `no seeds, go` (GUIDE)
            t = "skip" if key == "skip_seeds" else t
            if key and got.get(key, t) != t:
                return False
            if key:
                got[key] = t
            elif not (t in YES_WORDS or t == "mode" and toks[i + 1:i + 2] and toks[i + 1] in MODES or
                      toks[i - 1:i + 1] == ["no", "seeds"]):
                return False
    for key in ("mode", "variant", "autopilot", "topic", "idea"):
        if (ans.get(key) or None) != got.get(key):
            return False
    ans_priv = dict((k, v) for k, v in (ans.get("privacy") or {}).items() if v is not None)
    ans_quick = dict((k, v) for k, v in (ans.get("quick") or {}).items() if v)
    return bool(ans.get("private")) == ("private" in got) and bool(ans.get("skip_seeds")) == (
        "skip_seeds" in got) and ans_priv == priv and ans_quick == quick and (seeds.get("primary") or None) == \
        got.get("primary")


def _canon_g4(ctx, reply, ans):
    rescue = dict((r.get("id"), r.get("reason")) for r in ans.get("rescue") or [] if isinstance(r, dict))
    flags = set(ans.get("confirm_flags") or [])
    if not rescue and not flags and confirms_only(reply):
        return True
    got, confirm, clear = {}, set(), set()
    for seg in re.split(r"[\n;]", reply):
        m = re.match(r"\s*rescue\s+([IEQ]-\d+)\s*(?::\s*(.*))?$", seg.rstrip(), re.I | re.S)
        if m:  # `rescue I-012: <reason>`: the reason is the user's own words
            i = m.group(1).upper()
            if i in got:
                return False
            got[i] = (m.group(2) or "").rstrip(" ,") or "rescued by the user"
            if m.group(2) and (_label_doubt(m.group(2)) or ID_RE.search(m.group(2)) or re.search(
                    r"\b(?:kill|drop|confirm|clear|rescue|save|discard|scrap|keep|park)\w*|\b(?:others?|rest|remaining|"
                    r"else|everything|anything|all|any|every|each|both|leftovers?)\b", m.group(2), re.I)):
                # a reason that names another idea, an action, or any word for the other ideas ('cheap, get rid of the
                # rest', 'the leftovers can go', 'get rid of everything else'), or is no decision yet, is read back
                return False
            continue
        if not _bare_form(seg):
            return False
        verb = None
        for x in _form_words(seg):
            if x in ("confirm", "clear"):
                verb = x
            elif verb and ID_RE.fullmatch(x):
                (confirm if verb == "confirm" else clear).add(x.upper())
            else:
                return False
    return got == rescue and confirm == flags and not clear & (flags | set(got))


def _canon_g5(ctx, reply, ans):
    kill, keep = set(ans.get("kill") or []), set(ans.get("keep") or [])
    if not kill and not keep and confirms_only(reply):
        return True
    placed, verb = {}, None
    for x in _form_words(reply) if _bare_form(reply) else [None]:
        if x in ("kill", "keep"):
            verb = x
        elif verb and x and ID_RE.fullmatch(x) and x.upper() not in placed:
            placed[x.upper()] = verb
        else:
            return False
    return set(i for i, v in placed.items() if v == "kill") == kill and \
        set(i for i, v in placed.items() if v == "keep") == keep


def _canon_g11(ctx, reply, ans):
    steal = ans.get("steal") or []
    if ans.get("accept_recommendation"):
        return not steal and confirms_only(reply)
    # `B`, `go with B` (the ask message's form), `B+steal`, `B + steal A: offline cache`; a bare letter also in
    # markdown, with a closing . or ! and in lower case ('**B**', 'B.', 'b'; a lone `a` may be the article: read back)
    s = _uncourteous(reply)
    m = re.match(r"[\s*'`]*(?:(?i:go\s+with)\s+[\s*'`]*)?(?:([A-F])\s*(\+\s*(?i:steal)\b(?:\s+([A-Fa-f])\s*:\s*"
                 r"(\S.*))?)\s*|([A-F]|[b-f])[\s.!*'`]*)$", s, re.S)
    if not m or (m.group(1) or m.group(5)).upper() != ans.get("choice") or not _bare_form(
            s[:m.start(4)] if m.group(4) else s):
        return False
    if not m.group(2):
        return not steal
    if not m.group(3):
        return steal == ["*"]
    return len(steal) == 1 and isinstance(steal[0], dict) and steal[0].get("from") == m.group(3).upper() and \
        (steal[0].get("element") or "").strip() == m.group(4).strip() and not _label_doubt(m.group(4))


def _canon_g12(ctx, reply, ans):
    acc, rej = ans.get("accept") or [], ans.get("reject") or []
    if not _bare_form(reply):
        return False
    every, mode, got, dangling = False, None, {"accept": [], "reject": []}, False
    for x in _form_words(reply):
        if x in ("accept", "reject"):
            mode, dangling = x, x == "reject"  # `ok reject` names no ADR: not this form
            every = every or x == "accept"  # `accept` alone accepts every ADR
        elif x in YES_WORDS and mode is None:
            every = True  # `ok`, `ok, reject 3`
        elif x == "all" and mode == "accept":
            pass
        elif mode and re.fullmatch(r"\d{1,4}", x):
            got[mode].append(adr_key(x))
            dangling = False
        elif x not in ("adr", "adrs"):
            return False
    want = got["accept"] or (["all"] if every else [])
    return not dangling and not (every and got["accept"] and "accept" not in _form_words(reply)[:1]) and \
        sorted(want) == sorted(acc) and sorted(got["reject"]) == sorted(rej)


def _canon_g13(ctx, reply, ans):
    act = ans.get("action")
    if act == "approve":
        return confirms_only(reply)
    if act == "changes":  # `changes: <what to change>` starts a paid round with the user's own words: always read back
        return False
    want = ["switch", (ans.get("switch_to") or "").lower()] if act == "switch" else ["runner-up"]
    return _bare_form(reply) and _form_words(reply) == want


def _canon_g14(ctx, reply, ans):
    if not _bare_form(reply):
        return False
    w = [{"arch": "architecture", "adrs": "adr"}.get(x, x) for x in _form_words(reply)]
    said, items, no, handoff, merge = False, [], w[:1] == ["no"], None, None
    for i, x in enumerate(w):
        if x == "publish" and not no and not said:
            said = True
        elif x in ("architecture", "adr", "proposal") and said and x not in items:
            items.append(x)
        elif x in ("all", "everything") and w[i - 1:i] == ["publish"]:
            pass  # `publish all, ce` (GUIDE) is `publish, ce`
        elif x in HANDOFF_NAMES and handoff is None and w[i - 1:i] != ["merge"]:
            handoff = x
        elif x == "merge" and w[i + 1:i + 2] and w[i + 1] in ("all", "some", "none", "defer"):
            merge = w[i + 1]
        elif not (x == "no" and i == 0 or x == "handoff" or w[i - 1:i] == ["merge"]):
            return False
    pub = ans.get("publish")
    want = False if no else (items or True) if said else None
    # a bare `no` names no handoff: it reads as `none` at once only where that is the card's default (not software or
    # growth, whose default hands off to ce); elsewhere it is read back
    return (sorted(pub) == sorted(want) if isinstance(pub, list) and isinstance(want, list) else pub is want) and \
        ans.get("handoff") == (handoff or ("none" if no else None)) and ans.get("merge_terms") == merge and \
        bool(handoff or not no or ctx.variant not in ("software", "growth"))


def _canon_ids(ctx, reply, ans, key):
    """G6, G7: `ok` for the suggested set, or the IDs alone (separators, a markdown list, bold, backticks, courtesy)."""
    ids = ans.get(key) or []
    if not ids:
        return confirms_only(reply) or _bare_form(reply) and _form_words(reply) == ["skip"]
    body = re.sub(r"(?m)^[^\S\n]*(?:[-*+\u2022]|\d{1,2}[.)])(?=\s)", " ", reply)
    w = _form_words(body) if _bare_form(body) else []
    return bool(w) and all(ID_RE.fullmatch(x) for x in w) and set(x.upper() for x in w) == set(ids)


# G14: the words beside a handoff that say nothing more ('use ce', 'hand off to ce', 'handoff: none')
_G14_HANDOFF_FILL = frozenset(("handoff", "hand", "off", "to", "use", "and", "then", "with", "the", "a", "via", "for"))


def _canon_g8b(ctx, reply, ans):
    """`ok`, or `<ID>` with an optional reason that is the user's own words and turns nothing (no other ID, negation,
    contrast, condition, deferral, take-back, question or hedge), each optionally with `runner-up: <ID>` and
    `park: <IDs>` after a `;`, a line break or a comma. A remark after a comma or a dash is a reason only with 3 words
    or more and no I / we leading it: a shorter one or one about the user is read back ('I-007, I suppose', 'I-007 -
    for now', 'I-007 - guessing'); `because`, `since` and a colon mark a reason of any length."""
    segs = [x.strip() for x in re.split(r"[;\n]|,(?=[^\S\n]*(?i:runner[- ]?up|park)[^\S\n]*:)", reply)]
    runner, park = None, []
    for seg in segs[1:]:
        m = re.fullmatch(r"(?:(runner[- ]?up)|park)[^\S\n]*:[^\S\n]*(" + _PICK_LIST.replace(" ", "[^\\S\\n]") +
                         r")[^\S\n]*\.?", seg, re.I)
        if not m or m.group(1) and (runner or len(_ids(m.group(2))) > 1):
            return False
        if m.group(1):
            runner = m.group(2).upper()
        else:
            park += _ids(m.group(2))
    if runner != ans.get("runner_up") or sorted(park) != sorted(ans.get("park") or []) or ans.get("bundle"):
        return False
    if ans.get("accept_recommendation"):
        return confirms_only(segs[0])
    m = re.match(r"[\s*'`]*([IEQ]-\d+)[\s*'`!.,]*(?:(because|since|:|[-\u2013\u2014]|,)[^\S\n]*(\S.*))?$",
                 _uncourteous(segs[0]), re.I | re.S)
    reason = _reading(m.group(3))[0] if m and m.group(3) else None
    return bool(m) and m.group(1).upper() == ans.get("chosen") and _bare_form(segs[0]) and not (reason and (
        m.group(2).lower() not in ("because", "since", ":") and (len(_words(reason)) < 3 or re.match(
            r"\W*(?:i|we|i'm|i'd|i've|we're|we'd)\b", reason, re.I)) or
        _label_doubt(reason) or ID_RE.search(reason) or _LATER.search(reason) or re.search(
            r"n't\b|\b(?:not|no|never|none|nothing|nor|without|except|instead|rather|over|than|unlike|but|however|"
            r"although|though|yet|or|may|might|could|would|should|maybe|perhaps|probably|possibly|guess|tentative\w*|"
            r"if|unless|runner|"
            r"park|choose|chose|pick|take|drop)\b", reason, re.I)))


def _canon_words(ctx, reply, ans, gid):
    """G1, G2f, G9, GB, GX: the reply is the keyword of its reading (G9: with the observed numbers; GB: the cap)."""
    w = _form_words(reply) if _bare_form(reply) else []
    if gid == "G1":
        return w == ["done"] and ans.get("done") is True and not ans.get("skip") or w == ["skip"] and \
            ans.get("skip") is True and not ans.get("done")
    if gid == "G2f":  # the keyword, alone or with the file the card names ('restore CONTEXT.md')
        return w[:1] == ["restore" if ans.get("restore") else "keep"] and w[1:] in ([], ["context", "md"])
    if gid == "G9":  # `passed, 18/20 used it`: the result, then a note with the observed numbers that decides nothing
        note = _form_words(_reading(reply)[0])[1:] if w else []
        tail = re.sub(r"^\W*\w+\W+\d[^\s,;]*\W*", "", reply, count=1)  # the note after the result and its count
        return w[:1] == [(ans.get("result") or "").lower()] and (all(
            any(c.isdigit() for c in x) or x in _G9_COUNTS for x in note) or any(
            c.isdigit() for x in note for c in x) and not _label_doubt(reply) and not _label_doubt(
            tail, False) and not re.search(
            r"\s(?-i:[A-Z][a-z])", reply) and not any(  # 'passed 11/20 - Maria disputes the target' is read back
            x in NO_WORDS or x in NEG_WORDS or x.endswith("n't") or x in _ANCHORS["G9"] or x in _G9_DOUBTS or x in (
                "but", "though", "although", "however", "except") for x in note))
    if gid == "GB":
        cap = ans.get("raise_to")
        return w == ["stop"] if ans.get("stop") else bool(cap) and w in (["raise", "to", str(cap)],
                                                                          ["raise", str(cap)], [str(cap)])
    return w == [ans.get("action")]


_CANON = {"G0": _canon_g0, "G4": _canon_g4, "G5": _canon_g5, "G11": _canon_g11, "G12": _canon_g12,
          "G13": _canon_g13, "G14": _canon_g14, "G8b": _canon_g8b,
          "G6": lambda ctx, r, a: _canon_ids(ctx, r, a, "finalists"),
          "G7": lambda ctx, r, a: _canon_ids(ctx, r, a, "picks"),
          "G2c": lambda ctx, r, a: a.get("confirm") is True and not a.get("corrections") and confirms_only(r),
          "G10": lambda ctx, r, a: a.get("confirm") is True and not a.get("corrections") and confirms_only(r)}


def canonical(ctx, gid, ans):
    """The reply says nothing but its own reading, in the words the card documents (HOW_TO_REPLY): the reading
    rendered in that syntax matches the reply's words, once case, punctuation, separators (, ; . : and & line breaks),
    courtesy and the aliases of one item (adr / adrs, arch / architecture, an ID's case) are set aside. A confirmation
    reading (`ok`, confirm, approve, `go`) is canonical in confirmation words only; the text after `changes:`,
    `rescue <ID>:`, `steal <letter>:` and a G0 label (`topic:`, `idea:`, `Primary:`) is the user's own."""
    reply = (ans.get("reply") or "").translate(_QUOTES).strip()
    fn = _CANON.get(gid)
    if fn is None:
        return gid in ("G1", "G2f", "G9", "GB", "GX") and _canon_words(ctx, reply, ans, gid)
    return bool(reply) and fn(ctx, reply, ans)


def _ids_text(ids):
    return ", ".join(ids)


def _quote(text, n=160):
    text = " ".join(str(text or "").split())
    return '"%s"' % (text if len(text) <= n else text[:n - 3] + "...")


def describe(ctx, gid, ans):
    """What applying `ans` does, in one line named the way the card names it (the read-back, 4.12)."""
    s = ctx.state
    if gid == "G0" and (s.get("interrupt") or {}).get("gate") == "G0":
        return "extend this v1 run with an architecture package and a full proposal (paid model calls)" if \
            _v1_offer(ans) == "go" else "stop this run for good (it is not extended)"
    if gid == "G0":
        priv = dict(s.get("privacy") or {})
        if ans.get("private"):
            priv.update({"web": False, "vendors": False, "code": False})
        priv.update(dict((k, v) for k, v in (ans.get("privacy") or {}).items() if v is not None))
        fams = [f for f, info in (s.get("families") or {}).items() if (info or {}).get("status") == "ok"]
        vendors = privacy_mod.allowed_vendors(ctx.host_family, fams, priv.get("vendors", True))
        seeds = ans.get("seeds") or {}
        listed = [("primary idea", [seeds.get("primary")]), ("problem", [seeds.get("problem")]),
                  ("ideas", seeds.get("ideas")), ("obvious", seeds.get("obvious")),
                  ("off-limits", seeds.get("off_limits"))]
        said = "; ".join("%s %s" % (k, ", ".join(_quote(x) for x in v if x)) for k, v in listed if any(v or []))
        return ("start the run (paid model calls): %s mode, %s variant, %s autopilot, topic %s; %s go to %s; web "
                "search %s, your repo code %s" % (
                    ans.get("mode") or s.get("mode"), ans.get("variant") or s.get("variant"),
                    ans.get("autopilot") or s.get("autopilot"), _quote(ans.get("topic") or s.get("topic")),
                    "the topic and your seeds (%s)" % said if said else "the topic (no seeds of yours%s)" % (
                        ", skipped" if ans.get("skip_seeds") else ""), ", ".join(vendors) or "no vendor",
                    "on" if priv.get("web", True) else "off", "goes to other vendors" if priv.get("code") else
                    "stays here"))
    if gid == "G1":
        return "the seeds file is written: go on to framing (paid model calls)" if ans.get("done") else \
            "skip your seeds: the run goes on without your own ideas"
    if gid in ("G2c", "G10"):
        what = "the frame" if gid == "G2c" else "the architecture drivers"
        if not ans.get("corrections"):
            return "confirm %s as %s and go on (paid model calls)" % (what, "it is" if gid == "G2c" else "they are")
        redo = gid == "G10" and int((s.get("counters") or {}).get("g10_loops", 0)) < 2
        return "add this correction to %s%s: %s" % (what, " and redo the drivers (paid model calls)" if redo else
                                                    "", _quote(ans["corrections"], 300))
    if gid == "G2f":
        return "put CONTEXT.md in your repository back as it was before framing (later edits to it are lost)" if \
            ans.get("restore") else "keep CONTEXT.md in your repository as it is now"
    if gid == "G4":
        parts = ["rescue %s into the shortlist (reason: %s)" % (r.get("id"), _quote(r.get("reason"), 80))
                 for r in ans.get("rescue") or [] if isinstance(r, dict)]
        if ans.get("confirm_flags"):
            parts.append("confirm the single-judge flag on %s: killed" % _ids_text(ans["confirm_flags"]))
        return "; ".join(parts + ["clear every other flag (those ideas stay)"]) if parts else \
            "accept the shortlist as it is: no rescue, and no flagged idea is killed"
    if gid == "G5":
        kill, keep = ans.get("kill") or [], ans.get("keep") or []
        park = [c for c in s.get("k4_candidates") or [] if c not in kill and c not in keep]
        parts = (["kill %s (K4)" % _ids_text(kill)] if kill else ["kill no K4 candidate"]) + (
            ["keep %s" % _ids_text(keep)] if keep else []) + (["park %s" % _ids_text(park)] if park else [])
        return "; ".join(parts)
    if gid in ("G6", "G7"):
        base = pick_base(ctx, gid)
        ids = ans.get("finalists" if gid == "G6" else "picks") or base
        drop, add = [i for i in base if i not in ids], [i for i in ids if i not in base]
        return "%s %s (paid model calls)%s%s%s" % (
            "take to the tournament as the finalists:" if gid == "G6" else "red-team", _ids_text(ids),
            "" if drop or add else ", the suggested set", "; this drops %s from the suggested set" % _ids_text(drop)
            if drop else "", "; this adds %s" % _ids_text(add) if add else "")
    if gid == "G8b":
        sug = registry.suggestion(ctx)[0]
        chosen = sug if ans.get("accept_recommendation") or not ans.get("chosen") else ans["chosen"]
        runner = ans.get("runner_up") or registry.default_runner(ctx, chosen)
        return "choose %s %s%s: the probe, the architecture and the proposal are built for it (paid model calls); " \
            "runner-up: %s%s%s" % (
                chosen, _title(ctx, chosen), " (the suggestion)" if chosen == sug else ", not the suggestion %s" % sug
                if sug else "", runner or "none", "" if ans.get("runner_up") or not runner else
                " (by rule: the best-ranked other idea)", "; park %s" % _ids_text(ans["park"]) if ans.get("park")
                else "")
    if gid == "G9":
        res = (ans.get("result") or "INCONCLUSIVE").upper()
        iid = registry.chosen_idea(ctx) or "the chosen idea"
        if res != "MISSED":
            return "record the probe of %s as %s" % (iid, res)
        runner = (s.get("choice") or {}).get("runner_up")
        runner = runner if runner not in registry.k6_killed(s) else None
        return "record the probe of %s as MISSED: %s is killed (K6)%s" % (
            iid, iid, ", and the runner-up %s becomes the chosen idea (its probe is designed again, paid model calls)"
            % runner if runner else ", and no runner-up is left")
    if gid == "G11":
        label = g11_recommendation(ctx)[0] if ans.get("accept_recommendation") or not ans.get("choice") else \
            ans["choice"]
        steal = ans.get("steal") or []
        took = "the whole steal list" if steal == ["*"] else ", ".join(
            "%s from %s" % (_quote(x.get("element"), 60), x.get("from")) for x in steal if isinstance(x, dict))
        return "choose architecture %s%s%s: the package is written for it (paid model calls)" % (
            label, " (the suggestion)" if ans.get("accept_recommendation") else "", ", taking %s" % took if took
            else "")
    if gid == "G12":
        acc, rej = ans.get("accept") or [], ans.get("reject") or []
        num = lambda xs: ", ".join(str(int(x)) if str(x).isdigit() else str(x) for x in xs)  # noqa: E731
        parts = (["accept every ADR" + (" except ADR %s" % num(rej) if rej else "")] if "all" in acc else
                 ["accept ADR %s" % num(acc)] if acc else []) + (["reject ADR %s" % num(rej)] if rej else [])
        left = [n for n in sorted(os.path.basename(p)[:4] for p in _adr_files(ctx)) if "all" not in acc and
                n not in acc and n not in rej]
        return "; ".join(parts + (["leave ADR %s proposed" % num(left)] if left else []))
    if gid == "G13":
        act = ans.get("action")
        if act == "approve":
            return "approve: sign the proposal off, and every ADR you did not reject is accepted"
        if act == "changes":
            return "change round %d of 2, redoing the proposal (paid model calls): %s" % (
                int((s.get("counters") or {}).get("g13_loops", 0)) + 1, _quote(ans.get("changes"), 300))
        from . import pipeline
        sid = pipeline.step_ref("switch_arch_from" if act == "switch" else "probe_from", ctx)
        try:
            cost = " (about %d requests)" % redo_plan(ctx, sid)["calls"]["expected"]
        except Exception:  # the read-back never fails over its cost
            cost = ""
        return "%s: redo from step %s onward%s" % (
            "switch to architecture %s" % ans.get("switch_to") if act == "switch" else
            "switch to the runner-up idea %s" % (s.get("choice") or {}).get("runner_up"), sid, cost)
    if gid == "G14":
        from . import handoff  # a local import: handoff's builders import this module
        pub = ans.get("publish")
        items = ["architecture", "adr", "proposal"] if pub is True else pub if isinstance(pub, list) else []
        if "adr" not in items and set(items) & set(("architecture", "proposal")) and handoff._source_files(
                ctx.path(handoff.PUBLISH["adr"])):  # the ADRs go with the copies that link to them (_layout)
            items = [i for i in handoff.ALL_ITEMS if i in items or i == "adr"]
        names = {"architecture": "the architecture", "adr": "the ADRs", "proposal": "the proposal"}
        what = "publish %s as copies into your repository (docs/%s/)" % (
            " and ".join(names[i] for i in items), os.path.basename(s.get("run") or "run")) if items else \
            "publish nothing"
        ho = ans.get("handoff") or ("ce" if ctx.variant in ("software", "growth") else "none")  # chosen_handoff
        return "%s; handoff: %s (%s)%s%s" % (what, ho, HANDOFF_NAMES.get(ho, ho), "" if ans.get("handoff") else
                                             ", the default", "; merge the proposed terms: %s" % ans["merge_terms"]
                                             if ans.get("merge_terms") else "")
    if gid == "GB":
        return "stop the run at the budget cap" if ans.get("stop") else \
            "raise the budget cap to %s requests and go on" % ans.get("raise_to")
    if gid == "GX":
        return {"reframe": "reframe: the frame and every later step are redone (paid model calls)",
                "continue": "continue the whole effort as it is",
                "stop": "stop the whole effort"}.get(ans.get("action"), str(ans.get("action")))
    return "apply your answer"


def read_back(ctx, gid, provided, ans):
    """The read-back of a prepared answer (4.12): the card's error that shows the reading when it is to act only after
    a yes, else None (it acts now). Only a reply the host wrote alone is read back, never a documented form."""
    if gid not in READBACK_GATES:
        return None
    provided = {"reply": provided} if isinstance(provided, str) else provided
    if not isinstance(provided, dict) or not (provided.get("reply") or "").strip() or any(
            not _empty(v) for k, v in provided.items() if k != "reply") or canonical(ctx, gid, ans):
        return None
    return READBACK_HEAD + describe(ctx, gid, ans) + ". Reply yes to do that, or tell me what you want instead."


def only_reply(ctx, gid, provided, held=None):
    """The host wrote nothing but the reply: every other field is empty or holds what the reply itself reads as (a
    `confirm: true` beside the reply `yes`). Beside a stored reading (`held`) only that yes flag is the reply's own:
    any other field the host filled (G1 `done`, G13 `action`) is the host's answer and wins (4.12)."""
    if isinstance(provided, str):
        return True
    if not isinstance(provided, dict) or set(provided) - set(answer_template(gid)) or not isinstance(
            provided.get("reply") or "", str):
        return False
    fields, _notes, _errs = _coerce(gid, dict((k, v) for k, v in provided.items() if k != "reply"))
    if held and any(not _empty(v) for k, v in fields.items() if k != "confirm"):
        return False
    got = parse_reply(gid, provided.get("reply") or "", ctx)
    return all(_empty(v) or v == got.get(k) for k, v in fields.items())


def how_to_reply(ctx, gid):
    if gid == "G0" and (ctx.state.get("interrupt") or {}).get("gate") == "G0":
        return "Reply `go` to extend this v1 run with an architecture package and a full proposal, or `stop`."
    return HOW_TO_REPLY.get(gid, "")


def pending_readback(ctx, gid):
    """The stored reading (run.json "readback") that the card of `gid` still asks about, or None. It is pending only
    while nothing in the run changed since the card showed it (the state's rev), so every other path (another pending
    gate, redo, stop, switch, supersede, a default answer) leaves it behind as a marker (drop_reading)."""
    rb = ctx.state.get("readback")
    if isinstance(rb, dict) and rb.get("gate") == gid and rb.get("rev") == st._rev(ctx.state) and \
            rb.get("interrupt") == ctx.state.get("interrupt"):
        return rb
    return None


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
    if intr.get("gate") == "G0" and _v1_offer(ans) == "stop":
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
    priv.pop("kickoff_vendors", None)  # a kickoff answered again (a redo) is listed anew at the next host move
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
            # a Problem, Obvious or Off-limits the user wrote stays (the prompts quote them); the line goes above it
            ctx.write("00_HUMAN_SEEDS.md", registry.skipped_seeds(text, "the user skipped the seeds at G1"))
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
        fr = ctx.read("01_FRAME.md")
        ctx.write("01_FRAME.md", fr.rstrip() + "\n\n## User corrections\n%s\n" % ans["corrections"])
    return []


def _apply_g2f(ctx, ans, by):
    """`restore`: CONTEXT.md gets its content from before framing back. It is the user's file, so it keeps its own
    permissions (a new one gets the umask default), never the run file's owner-only mode."""
    if ans.get("restore"):
        pd = ctx.state.get("project_dir")
        src = ctx.path("CONTEXT.before.md")
        if pd and os.path.exists(src):
            dst = os.path.join(pd, "CONTEXT.md")
            try:
                mode = os.stat(dst).st_mode & 0o7777
            except OSError:
                umask = os.umask(0o022)
                os.umask(umask)
                mode = 0o666 & ~umask
            textio._write_bytes_atomic(dst, textio.read_bytes(src))
            if os.name != "nt":
                os.chmod(dst, mode)
    return []


def _apply_g3(ctx, ans, by):
    ideas = [i for i in ans.get("ideas") or [] if i]
    if ideas:
        ctx.write("00b_HUMAN_ROUND2.md", "# Human round 2\n\n## Ideas\n%s\n" % "\n".join("- %s" % i for i in ideas))
    return []


def _apply_g4(ctx, ans, by):
    """Rescues join the shortlist (the Rescued: line of 04_SHORTLIST.md, rendered from this answer: apply() records the
    gate only after this); a confirmed single-judge flag kills."""
    confirm = [i for i in ans.get("confirm_flags") or [] if i]
    if confirm:
        ctx.state["killed"] = sorted(set((ctx.state.get("killed") or []) + confirm))
    registry.render_shortlist(ctx, g4=ans)
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
    runner = ans.get("runner_up") or registry.default_runner(ctx, chosen)
    s["choice"]["idea"] = chosen
    s["choice"]["runner_up"] = runner
    return []


def _apply_g9(ctx, ans, by):
    return probe_result(ctx, (ans.get("result") or "INCONCLUSIVE").upper(), ans.get("note") or ans.get("reply"))


K6_STOP = "the chosen idea's probe missed (K6) and no runner-up is left"


def probe_result(ctx, result, note):
    """Record the result of the probe in 09_PROBE.md for the idea it tests (the chosen idea: a switch re-designs the
    probe). The same result for the same idea again changes nothing (a retried command); another result replaces the
    last one. MISSED -> K6: the probed idea's ledger row is written now, and the runner-up (never an idea its own
    probe killed) becomes the chosen idea, whose own probe is designed again. Without a runner-up the chosen idea is
    dead: before the architecture (G9 at 11.2) the run stops there (K6_STOP; `switch --idea` goes on with another
    finalist), and a finished run renders its documents again, so they and the DONE card say so."""
    s = ctx.state
    iid = registry.chosen_idea(ctx)
    probe = s.get("probe") or {}
    if probe.get("idea") == iid and probe.get("result") == result:
        return []
    text = ctx.read("09_PROBE.md")
    label = {"PASSED": "PASSED", "MISSED": "MISSED (K6)", "INCONCLUSIVE": "INCONCLUSIVE"}[result]
    # one RESULT line only: the pre-registered 'RESULT: PENDING' (or an earlier result) is replaced, never left above
    text = re.sub(r"(?m)^RESULT: PENDING\s*$\n?", "", text)
    text = re.sub(r"\n## Result\n(?:(?!\n## ).)*\Z", "", text.rstrip() + "\n", flags=re.S)
    block = "\n## Result\n%s\nRESULT: %s\n" % ((note or "").strip() or "(no numbers reported)", label)
    ctx.write("09_PROBE.md", text.rstrip() + "\n" + block)
    s["probe"] = {"idea": iid, "result": result, "at": textio.now_iso()}
    s["ledger_probe_written"] = False  # a new result gets its own ledger row at 14.4
    effects = []
    from . import pipeline  # lazy: pipeline imports this module
    # every status-bearing document (architecture README, PROPOSAL.md, ONE-PAGER, index.html, 12_HANDOFF.md, the
    # handoff seed and its G14 publish at 14.3) is rendered again; steps the run never reached are skipped by reset
    rerender = [sid for sid in pipeline.step_ref("probe_rerender") if st.step_state(ctx.state, sid) == "done"]
    if result in ("PASSED", "INCONCLUSIVE") and rerender:
        effects.append(("reset", rerender))
    if result == "MISSED":
        ch = s.get("choice") or {}
        s["ledger_probe_written"] = True  # the row names the idea whose probe missed, never the runner-up
        runner = ch.get("runner_up") if ch.get("runner_up") not in registry.k6_killed(s) else None
        if runner:
            s["choice"]["idea"], s["choice"]["runner_up"] = runner, None
            effects.append(("supersede", pipeline.step_ref("probe_from", ctx)))
        elif ch.get("runner_up"):
            s["choice"]["runner_up"] = None  # its own probe killed it: never the chosen idea again
        # the decision line and the ledger row are written after the supersede commits the kill (#11), so a refused
        # supersede leaves nothing that the retried command writes a second time
        effects.append(("append", "08_DECISION.md", "Killed: %s - K6 (the pre-registered probe missed)\n" % iid))
        effects.append(("ledger", ["| %s | %s | %s | %s | probe missed | 09_PROBE.md | - |" % (
            textio.now_iso()[:10], s.get("run"), iid, registry.clean(registry.idea_lines(ctx).get(iid, {}).get(
                "title", "")))]))
        if not runner:
            effects.append(("reset", rerender) if rerender else ("stop", K6_STOP))
    return effects


def _apply_g10(ctx, ans, by):
    if ans.get("corrections"):
        c = ctx.state.setdefault("counters", {})
        c["g10_loops"] = int(c.get("g10_loops", 0)) + 1
        brief = ctx.read("10_ARCHITECTURE/00_BRIEF.md")
        ctx.write("10_ARCHITECTURE/00_BRIEF.md", brief.rstrip() + "\n\n## User corrections\n%s\n"
                  % ans["corrections"])
        if c["g10_loops"] <= 2:
            from . import pipeline
            return [("reset", pipeline.step_ref("drivers_redo"))]
    return []


def g11_recommendation(ctx):
    """(label, why) the G11 default takes: the matrix leader, unless one judge vetoed it (veto flagged); then the
    best-ranked candidate no judge vetoed. With every candidate EXCLUDED (no leader, none ranked) it is the one with
    the best weighted score. `why` says so, or that the lead is self-judged (only an author family's judge scored the
    leader or the runner-up) or confounded (it compares two judges' scales), else ''."""
    m = ctx.read_json("10_ARCHITECTURE/matrix.json", {}) or {}
    cands = sorted([c for c in m.get("candidates") or [] if isinstance(c, dict) and c.get("rank")],
                   key=lambda c: (c.get("rank"), str(c.get("label"))))
    every = _all_excluded(m)
    if every:
        def score(c):
            return c["score"] if isinstance(c.get("score"), (int, float)) else float("-inf")
        best = sorted(every, key=lambda c: (-score(c), str(c["label"])))[0]["label"]
        return best, "every candidate is EXCLUDED by vetoes (%s): no leader; %s has the best weighted score" % (
            "; ".join("%s: %s" % (c["label"], "; ".join(dict.fromkeys(str(x) for x in c.get("veto_reasons") or []))
                                  or "no reason given") for c in every), best)
    leader = m.get("leader") or (registry.arch_labels(ctx) or ["A"])[0]
    lead = next((c for c in cands if c.get("label") == leader), {})
    if lead.get("veto") == "flagged":
        alt = next((c for c in cands if c.get("veto") == "none"), None)
        if alt:
            return alt["label"], ("leader %s was vetoed by a judge (%s); %s is the best-ranked candidate without a "
                                  "veto" % (leader, "; ".join(lead.get("veto_reasons") or []) or "no reason given",
                                            alt["label"]))
        return leader, "leader %s was vetoed by a judge and every other candidate too" % leader
    if m.get("leader_status") == "self-judged":
        own = [str(x) for x in m.get("self_judged") or []]
        who = leader if leader in own else next((str(c.get("label")) for c in cands if c.get("rank") == 2), "?")
        author = base_family(str(((ctx.read_json("10_ARCHITECTURE/candidates/map.json", {}) or {}).get(who) or {})
                                 .get("family") or ""))
        seated = [base_family(str(f)) for f in ctx.seats.get("arch_judges") or []]
        cause = ("its arch judge failed or its output is missing" if not seated or any(f != author for f in seated)
                 else "quick mode seats one arch judge, of that family" if ctx.mode == "quick" else
                 "no arch judge of another family was seated")
        return leader, ("the lead of %s is self-judged: only the author family's judge scored %s (no judge of "
                        "another family did; %s)" % (leader, "it" if who == leader else "the runner-up %s" % who,
                                                     cause))
    if m.get("leader_status") == "confounded":
        return leader, ("the lead of %s compares two judges' scales (confounded): no judge scored both leading "
                        "candidates" % leader)
    return leader, ""


def _all_excluded(matrix):
    """The candidates of a matrix without a leader in which none is ranked (every one EXCLUDED by 2+ vetoes); []."""
    every = [c for c in matrix.get("candidates") or [] if isinstance(c, dict) and c.get("label")]
    return every if not matrix.get("leader") and not any(c.get("rank") for c in every) else []


def g11_contested(ctx):
    """True when the G11 default rests on a vetoed or confounded leader: a person should decide."""
    return bool(ctx.sim is None and g11_recommendation(ctx)[1])


def _apply_g11(ctx, ans, by):
    matrix = ctx.read_json("10_ARCHITECTURE/matrix.json", {}) or {}
    label = ans.get("choice")
    if ans.get("accept_recommendation") or not label:
        label, why = g11_recommendation(ctx)
        ans["choice"] = label
        if why:
            ans["rule"] = why
            st.add_note(ctx.state, "G11 %s: %s" % (by, why))
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
    statuses = adr_statuses(ctx)
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
    return textio.glob_in(ctx.run_dir, "10_ARCHITECTURE", "adr", "*.md")


_ADR_REF = re.compile(r"^\s*(?:adr[-\s]*)?0*(\d{1,4})(?:[-\s:.].*)?$", re.I | re.S)


def adr_key(ref):
    """The ADR number an answer names, as the ADR files and adr_status.json key it: 3, "3", "ADR-0003" and
    "0003-use-sms" -> "0003"; None when `ref` names no number."""
    if isinstance(ref, bool):
        return None
    m = _ADR_REF.match(str(ref))
    return "%04d" % int(m.group(1)) if m else None


def adr_statuses(ctx):
    """10_ARCHITECTURE/adr_status.json keyed by ADR number. A key an older kit stored as the answer file named the ADR
    ("3", "ADR-0003") is read as that number, and it wins over the 'accepted' a G13 approve then stored under the
    number (it is the user's own G12 answer)."""
    raw = ctx.read_json("10_ARCHITECTURE/adr_status.json", {}) or {}
    out = {}
    for k in sorted(raw if isinstance(raw, dict) else {}, key=lambda k: adr_key(k) != k):
        if adr_key(k):
            out[adr_key(k)] = raw[k]
    return out


def _apply_g13(ctx, ans, by):
    s = ctx.state
    action = ans.get("action") or "approve"
    if action == "approve":
        s["signed_off"] = by != "auto"
        if by != "auto":
            statuses = adr_statuses(ctx)
            for p in _adr_files(ctx):
                n = os.path.basename(p)[:4]
                if statuses.get(n) != "rejected":
                    statuses[n] = "accepted"
            ctx.write_json("10_ARCHITECTURE/adr_status.json", statuses)
            from . import render_arch
            render_arch.rerender_adrs(ctx)
        # the architecture README carries the status banner too (DRAFT -> APPROVED)
        from . import pipeline
        return [("reset", pipeline.step_ref("approve_rerender"))]
    if action == "changes":
        from . import pipeline
        c = s.setdefault("counters", {})
        c["g13_loops"] = int(c.get("g13_loops", 0)) + 1
        s["user_changes"] = ans.get("changes") or ans.get("reply") or ""
        return [("reset", pipeline.step_ref("changes_redo"))]
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
        ctx.state["budget"].pop("need", None)
        return [("interrupt_clear",)]
    return [("interrupt_clear",), ("stop", "stopped at the budget cap")]


def _apply_gx(ctx, ans, by):
    a = ans.get("action")
    if a == "stop":
        return [("stop", "the user stopped the whole effort")]
    if a == "reframe":
        # the first frame step in pipeline order (2.1gd before 2.1g): every frame path is evaluated again (#14)
        from . import pipeline
        return [("supersede", pipeline.step_ref("reframe_from"))]
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
    extra.append("Vendors that will see idea text: %s." % (", ".join(vendors) or "none"))
    extra += ["Still reaching worker calls: %s" % n for n in user_context_lines(s)]
    if s.get("autopilot") == "full-auto":
        new = new_vendors(ctx)
        if new:
            extra.append("Asked again: your saved full-auto privacy choice did not list %s." % ", ".join(new))
        extra.append("Full-auto remembers this privacy choice and the vendors listed here for later full-auto runs, "
                     "and asks again when a family from another vendor is enabled (change it with `ub config set "
                     "privacy_defaults ...`); `private` or `web: no` / `vendors: no` still apply per run.")
    notes = ["Note: %s" % n for n in s.get("notes") or []]
    return {"PLAN_LINE": "About %d model calls (%d-%d), about %.1f-%.1fM tokens, about %d-%d minutes (estimates; %s)"
                         % (plan["calls"]["expected"], plan["calls"]["min"], plan["calls"]["max"],
                            plan["tokens"][0] / 1e6, plan["tokens"][1] / 1e6, plan["minutes"][0],
                            plan["minutes"][1], plan.get("cost") or "counts against your plans"),
            "FAMILIES_LINE": _families_line(ctx), "PRIVACY_LINE": g0_privacy_line(s),
            "GATE_EXTRA": "\n".join(extra), "CARD_NOTES": "\n".join(notes)}


def user_context_lines(state):
    """The user-context notes (`ub init` family_table: user instructions that still reach worker calls, #28) of every
    available family the run seats, in seat order."""
    fams = state.get("families") or {}
    out = []
    for f in (state.get("seats") or {}).get("families") or []:
        info = fams.get(f) or {}
        if info.get("status") == "ok" and info.get("backend") != "host" and st.family_allowed(state, f):
            out += [str(n) for n in info.get("user_context") or []]
    return out


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
            # web research quoted into the conversation: a DATA block, never instructions (#94)
            "LANDSCAPE_SUMMARY": privacy_mod.fence_data("LANDSCAPE", "\n".join(land)) if land else "NOT SEARCHED"}


def _v_g4(ctx):
    data = ctx.read_json("screen/shortlist.json", {}) or {}
    short = ["%s %s (score %s): %s" % (s.get("id"), _title(ctx, s.get("id")), s.get("score"), s.get("reason"))
             for s in data.get("shortlist") or [] if isinstance(s, dict)]
    killed = ["%s %s (K1: gate failed by 2+ judges)" % (i, _title(ctx, i)) for i in data.get("killed_gate") or []]
    killed += ["%s %s (K3: below the floor; you may rescue it)" % (i, _title(ctx, i))
               for i in data.get("floor_fail") or []]
    flags = ["%s %s" % (i, _title(ctx, i)) for i in data.get("flagged_gate") or []]
    # the screen's own-origin audit (5.7), where the human reviews it: a FLAGged judge, corrected only when the screen
    # lowered it (`lowered`: the corrections applied; a gap within noise, or a 2.0.x shortlist, corrected nothing),
    # and a WARNed pair of judges (not correctable: nothing was changed, so the shortlist may still lean to one vendor)
    def num(row):
        return isinstance(row, dict) and isinstance(row.get("gap"), (int, float))

    lowered = data.get("lowered") if isinstance(data.get("lowered"), dict) else {}

    def correction(row):
        cut = lowered.get(row.get("judge"))
        if isinstance(cut, (int, float)) and cut > 0:
            return "its own-vendor scores were lowered by %.2f" % cut
        se = row.get("se")
        return "not corrected%s; check whether the shortlist leans to its vendor" % (
            ": within noise, SE %.2f" % se if isinstance(se, (int, float)) else "")

    audit = ["%s: own-origin gap %+.2f (%s)" % (r.get("judge"), r["gap"], correction(r))
             for r in data.get("own_origin_gap") or [] if num(r) and r.get("flag")]
    audit += ["%s and %s together: %+.2f on their own vendors' ideas; not correctable (too few ideas from neither "
              "vendor), so check whether the shortlist leans to one of them" % (p.get("a"), p.get("b"), p["gap"])
              for p in data.get("own_origin_pairs") or [] if num(p) and p.get("warn")]
    return {"SHORTLIST_SUMMARY": "Shortlist:\n" + _bullets(short), "KILLED_LIST": _bullets(killed),
            "FLAGS_LIST": _bullets(flags), "SCREEN_AUDIT": _bullets(audit, empty="")}


def _v_g5(ctx):
    lines = []
    for i in ctx.state.get("k4_candidates") or []:
        v, d = registry.check_verdict(ctx, i)
        lines.append("- %s %s: VERDICT %s; DIFFERENTIATOR %s (checks/%s.md)" % (i, _title(ctx, i), v, d, i))
    return {"K4_CANDIDATES": "\n".join(lines) or "- none"}


def _v_g6(ctx):
    scores = registry.screen_scores(ctx)
    pool, ev = registry.finalist_pool(ctx), set(registry.evolved_ids(ctx))
    rows = []
    for i in pool:
        verdict = registry.check_verdict(ctx, i)[0]
        rows.append("- %s %s (screen %.2f%s%s)" % (i, _title(ctx, i), scores.get(i, 0.0),
                                                   ", from its parents" if i in ev else "",
                                                   "; check %s" % verdict if verdict else ""))
    return {"SURVIVORS_LIST": "\n".join(rows) or "- none",
            "PROPOSED_FINALISTS": ", ".join(ctx.state.get("finalists") or []) or "none"}


def _pct(pct, i):
    return "%.0f%%" % pct[i] if pct.get(i) is not None else "n/a"


def _v_g7(ctx):
    rk = registry.ranking(ctx)
    pct = rk["score"]
    fin = ctx.state.get("finalists") or []
    gut = registry.gut_picks(ctx)
    ranked = registry.rank_finalists(ctx, fin, rk)
    lines = (["Note: the %s." % rk["note"]] if rk["note"] else []) + [
        "- %s %s: %s%s" % (i, _title(ctx, i), _pct(pct, i), " (your gut #1)" if gut and gut[0] == i else "")
        for i in ranked]
    lines.append("Default red-team set: %s" % ", ".join(registry.default_top(ctx, fin, rk)))
    return {"TOP_PROPOSAL": "\n".join(lines)}


def _v_g8a(ctx):
    fin = ctx.state.get("finalists") or []
    blocks = ["## %s\n%s" % (i, registry.card_text(ctx, i)) for i in fin]
    return {"FINALIST_COUNT": str(len(fin)), "CARDS_BLOCK": "\n\n".join(blocks) or "(no cards)"}


def _v_g8b(ctx):
    s = ctx.state
    gut = registry.gut_picks(ctx)
    rk = registry.ranking(ctx)
    fin = s.get("finalists") or []
    ranked = registry.rank_finalists(ctx, fin, rk)
    standings = "\n".join((["Note: the %s." % rk["note"]] if rk["note"] else []) + [
        "%d. %s %s %s" % (n, i, _title(ctx, i), _pct(rk["score"], i)) for n, i in enumerate(ranked, 1)])
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
    own = set(str(x) for x in m.get("self_judged") or [])
    cmap = ctx.read_json("10_ARCHITECTURE/candidates/map.json", {}) or {}
    lines = []
    for c in m.get("candidates") or []:
        if isinstance(c, dict):
            # a candidate no other family's judge scored lists its author family's judges (the matrix's fallback)
            author = base_family(str((cmap.get(c.get("label")) or {}).get("family") or ""))
            js = [str(j) for j in c.get("judges") or []]
            n = len([j for j in js if base_family(j) != author])
            lines.append("- %s%s: score %s, rank %s (range %s), veto %s%s; %s%s" % (
                c.get("label"), _candidate_gist(ctx, c.get("label")), c.get("score"), c.get("rank"),
                registry.fmt_range(c.get("range")), c.get("veto"),
                (" (%s)" % "; ".join(c.get("veto_reasons") or [])) if c.get("veto_reasons") else "",
                "scored by %d judge%s of other families" % (n, "" if n == 1 else "s") if n or not js else
                "scored by its author family's judge only" + ("" if c.get("label") in own else
                                                               " (one model family: no other family's judge)"),
                ("; judges disagree on %s" % ", ".join(c.get("disagreements"))) if c.get("disagreements") else ""))
    for x in m.get("steal") or []:
        if isinstance(x, dict):
            lines.append("  steal from %s: %s" % (x.get("from"), x.get("element")))
    warns = [str(w) for w in m.get("warnings") or [] if w]
    if warns:
        lines.append("Matrix warnings:")
        lines += ["  - %s" % w for w in warns]
    lines.append("Matrix: %s" % textio.to_posix(ctx.path("10_ARCHITECTURE/tradeoff-matrix.md")))
    pm = ""
    for ln in ctx.read("10_ARCHITECTURE/premortem.md").split("\n"):
        if ln.strip().upper().startswith("TOP RISK"):
            pm = ln.strip()
    if not pm and ctx.mode == "quick":
        pm = "(quick mode: no pre-mortem)"
    label, why = g11_recommendation(ctx)
    # the status is the leader's; a candidate that replaces a vetoed leader shows why it is suggested instead
    status = ("best-ranked without a veto" if m.get("leader") and label != m.get("leader") else
              "no leader: every candidate is EXCLUDED" if _all_excluded(m) else
              m.get("leader_status") or "close-call")
    return {"MATRIX_SUMMARY": "\n".join(lines), "PREMORTEM_TOP": pm or "(none)",
            "ARCH_SUGGESTION": "%s (%s)%s" % (label or "?", status, ("; " + why) if why else "")}


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
        key = adr_key(os.path.basename(p))  # the ADR's own number: what accept and reject name
        lines.append("%d. %s - chosen: %s" % (int(key) if key else n, mt.group(1).strip() if mt else
                                              os.path.basename(p), mc.group(1) if mc else "?"))
    return {"ADR_LIST": "\n".join(lines) or "(no ADRs)"}


def _v_g13(ctx):
    lines = []
    for p in sorted(textio.glob_in(ctx.run_dir, "11_PROPOSAL", "review", "rubric_*.json")):
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
    from . import render
    try:
        render.refresh_page(ctx)  # a page an older kit rendered (no pinned script) is rendered again before the link
    except (EngineError, OSError):
        pass  # the card still names the page; G14, a publish and an export render it again
    links = [textio.to_posix(ctx.path(r)) for r in ("11_PROPOSAL/PROPOSAL.md", "11_PROPOSAL/ONE-PAGER.md",
                                                     "11_PROPOSAL/index.html", "10_ARCHITECTURE/README.md")
             if ctx.exists(r)]
    return {"PROPOSAL_SUMMARY": "\n".join(lines), "LINKS_BLOCK": " | ".join(links), "REDO_COST": _redo_cost(ctx)}


def redo_plan(ctx, sid):
    """The plan (progress.plan) of a redo from step `sid`: that step and every later one pending, under the default
    simulation facts. `ub redo` and `ub switch` preview it, and the G13 card shows it for `switch` and `runner-up`."""
    from . import pipeline, progress
    shadow = st.Ctx(ctx.run_dir, copy.deepcopy(ctx.state), ctx.deps, sim=dict(pipeline.DEFAULT_SIM))
    steps = pipeline.load_steps()
    for s in steps[pipeline.index_of(steps, sid):]:
        st.set_step(shadow.state, s["id"], "pending")
    return progress.plan(shadow, pipeline.simulate(shadow, remaining_only=True))


def _redo_cost(ctx):
    """The G13 cost preview: the step `switch <letter>` and `runner-up` redo from, and about how many requests."""
    from . import pipeline
    runner = (ctx.state.get("choice") or {}).get("runner_up")
    try:
        todo = [("`switch <letter>`", pipeline.step_ref("switch_arch_from"))]
        if runner:
            todo.append(("`runner-up` (%s)" % runner, pipeline.step_ref("probe_from", ctx)))
        return "Cost before anything is redone: %s." % "; ".join(
            "%s redoes %s onward (about %d requests)" % (what, sid, redo_plan(ctx, sid)["calls"]["expected"])
            for what, sid in todo)
    except Exception:  # the card never fails over its cost line
        return ""


def _v_g14(ctx):
    from . import handoff
    targets = handoff.card_lines(ctx)
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
    """Requests (the budget unit) and job launches, separately, and about how many more requests the run needs."""
    from . import progress
    try:
        from . import pipeline
        seq = pipeline.simulate(ctx, remaining_only=True)
        left = sum(int(round((i["count"][0] + i["count"][1]) / 2.0)) for i in seq)
    except Exception:
        left = progress.plan_for_state(ctx)["calls"]["expected"]
    return {"BUDGET_LINE": "%s About %d more requests are needed to finish (one per job when nothing is retried)."
                           % (progress.budget_line(ctx), left)}


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
           ("Flagged by one judge only (you decide)", "FLAGS_LIST"),
           ("Judge self-preference (04_SHORTLIST.md, Own-origin gap)", "SCREEN_AUDIT")],
    "G5": [("K4 candidates (CROWDED with no differentiator; a wrong verdict kills a good idea)", "K4_CANDIDATES")],
    "G6": [("Finalist pool (survivors and checked evolved ideas)", "SURVIVORS_LIST"),
           ("Proposed finalists", "PROPOSED_FINALISTS")],
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
    "G13": [(None, "PROVISIONAL_BANNER"), (None, "PROPOSAL_SUMMARY"), ("Files", "LINKS_BLOCK"), (None, "REDO_COST")],
    "G14": [(None, "PROBE_WARNING"), ("Publish copies into the repository (each needs a yes)", "PUBLISH_TARGETS"),
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
    rb = None if error else pending_readback(ctx, gid)
    if rb:  # the card shown again (`ub next`) still asks about its reading, which stays pending past this card's save
        error, rb["rev"] = rb.get("say"), st._rev(ctx.state) + 1
    # a reading the run moved past is not shown, and stays in run.json: a late yes to it asks again (answer_gate)
    if error:
        text = ("%s\n\n%s" if error.startswith(READBACK_HEAD) else "PLEASE FIX: %s\n\n%s") % (error, text)
    try:
        ctx.write("gates/%s.md" % gid, text.rstrip() + "\n")
    except OSError:
        pass
    return text.rstrip() + "\n"


def s_run(ctx):
    return ctx.state.get("run", "")
