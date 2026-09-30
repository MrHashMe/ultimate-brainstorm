#!/usr/bin/env python3
"""ub.py - the ultimate-brainstorm engine CLI (KIT_SPEC 4.11). Python 3.9+ standard library only.

  ub.py --version
  ub.py init      --host H (--text-file F | --text "<raw user text>") [--components LIST] [--root DIR]
                  [--lang CODE] [--mode M] [--variant V] [--autopilot A] [--families auto|LIST]
                  [--privacy default|private] [--seeds-file F] [--idea-file F] [--no-preflight] [--json]
                                                                                       -> prints the G0 card
  ub.py next      [RUN] [--wait-s N] [--lease T] [--json]                              -> one card
  ub.py answer    RUN GATE (--file F | --choice X | --default | --skip) [--lease T] [--json]   -> next card
  ub.py done      RUN STEP [--lease T] [--json]                   HOST step finished -> validate -> next card
  ub.py continue  [RUN] [--host H] [--root DIR] [--json]          newest unfinished run -> its current card
  ub.py status    [RUN] [--json]
  ub.py plan      [RUN] | --mode M --variant V --families LIST [--json]
  ub.py run       ["<topic...>" | --text "<topic...>" | --text-file F] [init options] | --continue [RUN]   terminal
  ub.py stop      RUN
  ub.py budget    RUN --max-calls N [--lease T]                       set the request cap; a budget stop goes on
  ub.py redo      RUN STEP [--yes]
  ub.py switch    RUN (--arch LABEL | --idea ID) [--yes]
  ub.py probe-result RUN (PASSED|MISSED|INCONCLUSIVE) [--note-file F]
  ub.py import    FILE [RUN]
  ub.py attach-s1 RUN --doc P --raw P
  ub.py render    RUN [--zip]
  ub.py export    RUN --format docx|html
  ub.py doctor    [--live] [--json]
  ub.py config    get|set KEY [VALUE]
  ub.py list      [--root DIR] [--json]

Exit codes: 0 whenever a card or result was printed (the status is inside the JSON), 2 usage, 1 internal error.
"""

import argparse
import importlib
import json
import os
import re
import sys
import time
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ublib import textio  # noqa: E402
from ublib.engine import (APPROACH_VARIANTS, AUTOPILOTS, ENGINE_VERSION, FAMILY_ORDER, HOST_DEFAULT_FAMILY,  # noqa
                          HOST_WAIT_S, HOSTS, MODES, REPO_VARIANTS, VARIANTS, EngineError, UsageError, base_family,
                          vendor_of)
from ublib.engine import cards  # noqa: E402
from ublib.engine import gates  # noqa: E402
from ublib.engine import pipeline  # noqa: E402
from ublib.engine import privacy as privacy_mod  # noqa: E402
from ublib.engine import progress  # noqa: E402
from ublib.engine import registry  # noqa: E402
from ublib.engine import state as st  # noqa: E402

# Loaded now, not first at a late stage: a driver that runs for hours never mixes engine versions when the kit is
# updated meanwhile (#67). The functions below keep their own lazy imports, which break import cycles.
for _late in ("builders", "handoff", "migrate", "render", "render_arch", "seats", "terminal"):
    importlib.import_module("ublib.engine." + _late)

COMMAND_TOKENS = ("continue", "status", "doctor", "stop")
OPTION_TOKENS = ("private", "with-ce-ideate")
COMPONENT_KEYS = {"grilling": "grilling", "domain-modeling": "domain_modeling", "ce-ideate": "ce_ideate",
                  "ce-brainstorm": "ce_brainstorm", "ce-plan": "ce_plan", "bmad-brainstorming": "bmad_brainstorming",
                  "bmad-forge-idea": "bmad_forge_idea", "lateral-thinking": "lateral_thinking",
                  "claude-council": "claude_council", "speckit": "speckit"}
SOURCE_EXT = (".py", ".js", ".ts", ".tsx", ".jsx", ".go", ".rs", ".java", ".kt", ".rb", ".cs", ".cpp", ".c", ".h",
              ".swift", ".php", ".scala", ".vue", ".svelte")


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise UsageError(message)


# ================================================================ output

def emit(obj, as_json):
    if as_json:
        sys.stdout.write(json.dumps(obj, ensure_ascii=True) + "\n")
    else:
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
        if isinstance(obj, dict) and obj.get("type") in cards.CARD_TYPES:
            sys.stdout.write(cards.render_text(obj))
        elif isinstance(obj, dict) and "progress_file" in obj and "step" in obj:
            sys.stdout.write(status_text(obj))
        elif isinstance(obj, dict) and isinstance(obj.get("runs"), list) and "root" in obj:
            sys.stdout.write(list_text(obj))
        else:
            sys.stdout.write(json.dumps(obj, indent=1, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def status_text(obj):
    """`ub status` for people (--json keeps the full object)."""
    p = obj.get("progress") or {}
    lines = ["%s: %s (%s, %s, %s)" % (os.path.basename(obj.get("run") or ""), obj.get("status") or "active",
                                      obj.get("mode"), obj.get("variant"), obj.get("autopilot")),
             p.get("line") or ""]
    if obj.get("step"):
        lines.append("Now: step %s %s%s" % (obj["step"], obj.get("step_title") or "",
                                            ("  (waiting for your answer: %s)" % obj["gate"]) if obj.get("gate") else ""))
    lines.append("Time left: about %s" % progress._fmt_eta(p.get("eta_s") or [0, 0]))
    lines.append("Families: %s" % obj.get("families"))
    lines.append("Details: %s" % obj.get("progress_file"))
    return "\n".join(ln for ln in lines if ln) + "\n"


def list_text(obj):
    """`ub list` for people: one line per run."""
    runs = obj.get("runs") or []
    if not runs:
        return "No runs under %s\n" % obj.get("root")
    out = []
    for r in runs:
        step = r.get("step")
        out.append("%-48s %-8s %s%s" % (os.path.basename(r.get("run") or ""), r.get("status") or "",
                                        ("step %s  " % step) if step else "", r.get("topic") or ""))
    return "\n".join(out) + "\n"


# ================================================================ --text parsing (4.11)

# `web: no`, `vendors: none`, `code: yes`: a one-word value followed by a blank, `,`, `;`, `.` or the end
PRIVACY_PAIR = re.compile(r"(?<![\w-])(web|vendors?|code)[^\S\n]*:[^\S\n]*([^\W_]+)(?![^\s,;.])(?:[,;]|\.(?!\.))?",
                          re.I)
# any pair-like text, also quoted, marked up or with `=` ('**vendors:** no', '"vendors": "no"', 'vendors = off', 'web
# search: no', 'vendors: ❌'): a no in it that is not taken as a setting makes the kickoff card ask (never lost silently)
PRIVACY_LOOSE = re.compile(r"(?<![\w-])(web(?:[ \t-]?search)?|vendors?|code)[*_'\"\])]*\s*[:=][\s*_'\"(\[{]*"
                           r"([^\W_]+)(?![\w-])", re.I)
# a no said in a sentence ('no other vendors please', "don't use web search", 'vendors - no', "don't send it to
# OpenAI", 'only Claude', 'Claude only') asks the same way
_NEG_WHAT = (r"(vendors?|web[ \t-]?search|open[ \t-]?ai|chat[ \t-]?gpt|gpt|codex|anthropic|claude|kimi|moonshot|glm|"
             r"zhipu)")
PRIVACY_NEG = re.compile(r"\b(?:no|not|without|never|don't|dont|avoid|skip|only)\b(?!-)(?:[^\w\n]+\w+){0,3}?[^\w\n]+"
                         + _NEG_WHAT + r"\b|(?<![\w-])" + _NEG_WHAT + r"(?:[^\S\n]*[-–—>]+[^\S\n]*(?:no|none|off|never|"
                         r"not)|[^\S\n]+(?:\w+[^\S\n]+)?only)\b", re.I)
LEADING_TOKENS = frozenset(MODES + VARIANTS + AUTOPILOTS + ("private", "with-ce-ideate"))
_BLANKS, _WORD, _PAIR_GAP = re.compile(r"\s*"), re.compile(r"\S+"), re.compile(r"[ \t,;.]*")
_LINE_ENDS = frozenset("\r\x0b\x0c\x1c\x1d\x1e\x85  ")  # what str.splitlines ends a line at, besides LF


def privacy_pairs(text):
    """([(key, value, start, end)], unread): the privacy pairs typed as settings, in the leading run of tokens and pairs
    or in a run of pairs that ends its line ('Platforms - web: no, kiosk: yes' and 'a code: yes/no bot' are topic), and
    the keys of any other pair-like text whose value reads as no. The text is read like a gate reply (NFKC, no format
    characters, every line break a LF); start (a `,` or `;` just before the pair included) and end index the text as
    typed."""
    import bisect
    import unicodedata
    chars, at = [], []
    for i, c in enumerate(text):
        if unicodedata.category(c) != "Cf":
            for n in unicodedata.normalize("NFKC", c):
                chars.append("\n" if n in _LINE_ENDS else n)
                at.append(i)
    norm = "".join(chars)
    pairs = [m for m in PRIVACY_PAIR.finditer(norm) if gates._privacy_value(m.group(2)) is not None]
    keep, starts, pos = set(), dict((m.start(), m) for m in pairs), 0
    while True:  # the leading run
        pos = _BLANKS.match(norm, pos).end()
        if pos in starts:
            keep.add(pos)
            pos = starts[pos].end()
            continue
        w = _WORD.match(norm, pos)
        if not w or w.group(0).lower().strip(",") not in LEADING_TOKENS:
            break
        pos = w.end()
    ends, frontier = [i for i, c in enumerate(norm) if c == "\n"], None
    for m in reversed(pairs):  # the runs that end their line; frontier: where the kept run after m starts
        k = bisect.bisect_left(ends, m.end())
        eol = ends[k] if k < len(ends) else len(norm)
        blank = _PAIR_GAP.match(norm, m.end()).end() >= (frontier if frontier is not None and frontier <= eol else eol)
        frontier = m.start() if blank else None
        if blank:
            keep.add(m.start())

    def start(i):  # 'HR team, vendors: none' and 'HR team,<line break>vendors: none' leave no comma
        j = i
        while j and norm[j - 1] in " \t\n":
            j -= 1
        r = at[j - 1] if j and norm[j - 1] in ",;、،؛" else at[i]
        while r and unicodedata.category(text[r - 1]) == "Cf":  # a mark typed around the pair goes with it
            r -= 1
        return r

    def end(i):
        while i < len(text) and unicodedata.category(text[i]) == "Cf":
            i += 1
        return i

    def key(k):  # 'web search', 'websearch' -> web; 'Vendor', 'OpenAI' -> vendors
        k = k.lower()
        return "web" if k.startswith("web") else "code" if k == "code" else "vendors"
    out = [(m.group(1).lower(), gates._privacy_value(m.group(2)), start(m.start()), end(at[m.end() - 1] + 1))
           for m in pairs if m.start() in keep]
    taken = set(key(k) for k, v, _, _ in out if v is False)
    said = norm.translate(gates._QUOTES)
    unread = set(key(m.group(1)) for m in PRIVACY_LOOSE.finditer(said) if gates._privacy_value(m.group(2)) is False)
    unread.update(key(m.group(1) or m.group(2)) for m in PRIVACY_NEG.finditer(said))
    return out, sorted(unread - taken)


def parse_text(text):
    """Leading tokens are consumed while they match; the rest is the topic (or the idea in proposal mode). `text` is
    the kickoff text without its privacy settings; `privacy_unread` the keys of a no left in it (the kickoff asks)."""
    out = {"mode": None, "variant": None, "autopilot": None, "private": False, "with_ce_ideate": False,
           "command": None, "rest": "", "privacy": {}}
    text, parts, pos = text or "", [], 0
    pairs, out["privacy_unread"] = privacy_pairs(text)
    for k, v, a, b in pairs:  # taken out of the text; per key a typed no stands over a typed yes
        k = "vendors" if k.startswith("vendor") else k
        out["privacy"][k] = out["privacy"].get(k, True) and v
        parts.append(text[pos:max(a, pos)])
        pos = b
    text = out["text"] = " ".join(parts + [text[pos:]])
    words = text.strip().split()
    i = 0
    while i < len(words):
        w = words[i].lower().strip(",")
        if w in MODES and out["mode"] is None:
            out["mode"] = w
        elif w in VARIANTS and out["variant"] is None:
            out["variant"] = w
        elif w in AUTOPILOTS and out["autopilot"] is None:
            out["autopilot"] = w
        elif w == "private":
            out["private"] = True
        elif w == "with-ce-ideate":
            out["with_ce_ideate"] = True
        elif w in COMMAND_TOKENS and i == 0:
            out["command"] = w
            i += 1
            break
        else:
            break
        i += 1
    out["rest"] = " ".join(words[i:]).strip()
    return out


def _words(rx):
    """rx as whole words that are not part of a hyphenated compound ('ad-free' and 'brand-new' are no ad, no brand)."""
    return r"(?<![\w-])(?:%s)(?![\w-])" % rx


# First match wins. Words that are common in app topics ('study planner', 'user story', 'state of the art', 'a film
# photo app') count only in a phrase that names the variant's own work. The plurals that name what a new product has
# ('an app with social features', 'public APIs', 'players squash bugs', 'tracks conversions') count only after a word
# that means changing this repo or product ('add social features', 'improve search features', 'our APIs', 'boost
# conversions'): one list for all four plurals (KIT_SPEC 4.11).
_CHANGE = r"(add|ship|implement|fix|improve|increase|boost|raise|lift|our|my|this) ([\w'-]+ ){0,2}"
VARIANT_RULES = [
    ("growth", _words(r"activation|onboarding|retention|churn|conversion|%sconversions" % _CHANGE)),
    ("research", _words(r"research questions?|hypothes[ie]s|literature reviews?|thesis|dissertation|"
                        r"(user|field|pilot|clinical|cohort|case-control) stud(y|ies)|stud(y|ies) (of|on|into|whether)|"
                        r"(research|white) papers?|papers? (on|about)")),
    ("marketing", _words(r"campaigns?|ads?|advert\w*|brand(s|ing)?|marketing|go-to-market")),
    ("naming", _words(r"names? for|naming")),
    ("creative", _words(r"short stor(y|ies)|stor(y|ies) (for|about)|novels? (for|about)|screenplay|films? (for|about)|"
                        r"artwork|art (piece|project|installation)s?|songs? (for|about)|lyrics|poems? (for|about)|"
                        r"creative")),
    ("software", _words(r"feature|refactor(ing)?|codebase|api|bug|in this repo|%s(features|apis|bugs)" % _CHANGE)),
    ("product", _words(r"startups?|products?|apps?|business(es)?|saas|platforms?|tools?")),
]
_PRODUCT = re.compile(dict(VARIANT_RULES)["product"])
_LINK_WORDS = r"for|of|about|on|in|into|to|with"
_LINK = re.compile(r"\b(%s)\b" % _LINK_WORDS)
# a product word that a link or relative word follows: what comes next is what the product handles
_PRODUCT_LINKED = re.compile(r"%s\s+(that|which|who|where|%s)\b" % (_PRODUCT.pattern, _LINK_WORDS))
# a main verb ends the subject's clause, so the subject's own link ('our app FOR nurses NEEDS a campaign') leads to no
# approach phrase after it; a verb at most one word after a relative word, or one or two after `whose` or a
# subordinator, is that clause's own ('an app that needs no ads', 'a platform where artists need campaigns', 'an app for
# salons whose owners have no marketing skills', 'a tool for farmers because farmers lack branding')
# ponytail: closed verb list; another verb ('our app for nurses launches a campaign') still reads as a link
_MAIN_VERB = re.compile(r"(\b(that|which|who|where)\s+([\w'-]+\s+)?|\bwhose\s+([\w'-]+\s+){1,2}|"
                        r"\b(because|since|while|when|if)\s+([a-z'-]+\s+){1,2})?"
                        r"\b(needs?(?! of\b)|wants?|requires?|lacks?|deserves?|is|are|has|have)\b")
_DETERMINERS = set("a an the this these those our my your their his her its".split())


def _product_handles(low, m):
    """Whether an approach phrase (match m) in a product topic names what the product handles, not the work itself:
    a link or relative word leads from a product word to it in its own clause ('an app that suggests songs for
    workouts', 'a tool for branding small shops'), or it modifies the product word right after it ('a thesis writing
    app', 'a brand monitoring SaaS'). A product word as the subject, a modifier or an object keeps the variant ('our
    SaaS product needs a go-to-market campaign', 'our app for nurses needs a marketing campaign', 'app store ads for
    our meditation app', 'advertising our app on TikTok', 'a marketing campaign for my SaaS product', 'a research
    paper comparing note-taking apps')."""
    start = 0
    for v in _MAIN_VERB.finditer(low, 0, m.start()):
        if not v.group(1):
            start = v.end()
    if _PRODUCT_LINKED.search(low, start, m.start()):
        return True
    after = _PRODUCT.search(low, m.end())
    if not after or _LINK.search(low, m.start(), after.start()):
        return False
    words = low[m.end():after.start()].split()
    return len(words) <= 1 and not _DETERMINERS.intersection(words)


def is_source_repo(cwd):
    if not privacy_mod.is_git_repo(cwd):  # a .git folder, or a worktree's or submodule's .git file
        return False
    for dirpath, dirs, files in os.walk(cwd):
        depth = os.path.relpath(dirpath, cwd).count(os.sep)
        dirs[:] = [d for d in dirs if not d.startswith(".") and d not in ("node_modules", "brainstorm")] \
            if depth < 2 else []
        if any(f.endswith(SOURCE_EXT) for f in files):
            return True
    return False


def infer_variant(topic, cwd=None):
    low = (topic or "").lower()
    for variant, rx in VARIANT_RULES:
        m = re.search(rx, low)
        if not m or (variant == "software" and not is_source_repo(cwd or os.getcwd())):
            continue
        # ponytail: word-order heuristic, no parser; 'a bedtime stories for kids app' still reads as creative, and 'a
        # research paper comparing apps' and 'branding local businesses' as product (G0 shows the inferred variant)
        if variant in APPROACH_VARIANTS and _product_handles(low, m):
            continue
        return variant
    return "general"


def component_map(text):
    comps = dict((v, None) for v in COMPONENT_KEYS.values())
    for raw in re.split(r"[,\s]+", text or ""):
        name = raw.strip()
        if not name:
            continue
        leaf = name.split(":")[-1].split("/")[-1].lower()
        key = COMPONENT_KEYS.get(leaf)
        if key and not comps.get(key):
            comps[key] = name
    return comps


# ================================================================ context helpers

def make_deps():
    return pipeline.Deps()


def open_run(run_arg, root=None):
    if run_arg:
        run_dir = os.path.abspath(os.path.expanduser(run_arg))
        if not os.path.isdir(run_dir):
            raise EngineError("run folder not found: %s" % textio.to_posix(run_dir),
                              fix=["ub list --json"])
        return run_dir, None
    run_dir, how = st.newest_unfinished(root)
    if not run_dir:
        raise EngineError("no unfinished run found", fix=['ub init --host <host> --text "<topic>" --json'])
    return run_dir, how


def load_ctx(run_dir, deps=None, persist=False):
    """A view of the run. Read-only unless persist: only a caller that holds the driver lock may write (C2)."""
    state = st.load(run_dir, persist=persist)
    return st.Ctx(run_dir, state, deps or make_deps())


SAFE_BARE_ARG = re.compile(r"^[A-Za-z0-9_+:./-]+$")  # the same word in bash, PowerShell and cmd.exe, unquoted
# no double-quoted form keeps these in all three shells; PowerShell also ends a double-quoted string at the typographic
# double quotes U+201C, U+201D and U+201E
UNQUOTABLE = set('"$`%!\r\n\u201c\u201d\u201e')


def shell_arg(arg):
    """One argument of a command line an agent runs in bash, PowerShell or cmd.exe: bare when it is a plain word,
    else in double quotes with backslashes as forward slashes (the way cards write paths); None when no quoting is safe
    in all three shells (a double quote, also a typographic one, $, a backtick, %, ! or a line break)."""
    arg = str(arg)
    if SAFE_BARE_ARG.match(arg):
        return arg
    if any(c in UNQUOTABLE for c in arg):
        return None
    return '"%s"' % arg.replace("\\", "/")


def retry_cmd(a, run_dir):
    """The refused command again (busy_card's `then` adds the runner prefix), or None when it cannot be repeated
    safely. It is rebuilt from the parsed arguments, never re-emitted as shell text: free text is never put back into
    a command line (the reason --text-file exists). `answer --choice <text>` is retried as `--file` of the answer
    written to <run>/.ub/retry/; any other argument that shell_arg cannot write makes the command unrepeatable."""
    argv = [str(x) for x in a.argv]
    if getattr(a, "cmd", None) == "answer" and getattr(a, "choice", None) is not None:
        path = os.path.join(run_dir, ".ub", "retry", "%s-%s.json" % (a.gate, os.urandom(4).hex()))
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            textio.write_json_atomic(path, {"reply": a.choice})
        except OSError:
            return None
        argv = ["answer", a.run, a.gate, "--file", path] + (["--lease", a.lease] if getattr(a, "lease", None) else
                                                             []) + (["--json"] if a.json else [])
    out = [shell_arg(x) for x in argv]
    return None if None in out else " ".join(out)


def with_run(run_dir, deps, fn, host=None, retry=None, resume=False, lease=None, takeover=False):
    """C1/C2: take the run's driver lock FIRST, then load run.json (a v1 folder is migrated here, under the lock, and
    its families detected), roll an interrupted supersede forward (I6), and run fn(ctx, lock); the lock is released
    when fn returns.

    A lock held by another process, or a live 2.0.3 driver that holds the run through lock.json alone (#79), returns
    the AUTO 'another session is driving' card and changes nothing; its `then` runs the refused command again (`retry`:
    the command's parsed arguments), so a mutation is retried, never dropped. While a supersede journal still lists
    files in place, no command changes the run (I6, #11): the BLOCKED supersede card is returned. A run.json that
    changed under this process (state.Stale; only possible without OS file locks) is never overwritten: the run's
    current card is shown instead. resume: an explicit resume (`continue`, `run --continue`) lifts a `ub stop` (C3)."""
    deps = deps or make_deps()
    lock = st.DriverLock(run_dir, host or "other")
    if not lock.acquire():
        return busy_card(run_dir, deps, lock, retry)
    try:
        claimed = lock.claim(host)  # before run.json is read: a live 2.0.3 driver holds the run through lock.json alone
        if claimed:
            return busy_card(run_dir, deps, lock, retry, holder=claimed)
        ctx = load_ctx(run_dir, deps, persist=True)
        ctx.lease, ctx.takeover = lease, takeover
        if not host:
            lock.announce(ctx.host_agent)
        if (ctx.state.get("exec") or {}).get("redetect"):
            reseat_for_host(ctx, host or ctx.host_agent)  # a migrated v1 run: its families were never detected (#20)
            ctx.state["exec"].pop("redetect", None)
            st.save(run_dir, ctx.state)
        if upgrade_seats(ctx):
            st.save(run_dir, ctx.state)
        if ctx.state.get("status") == "done" and st.stop_requested(run_dir):
            st.clear_stop(run_dir)  # a finished run has nothing to stop: a STOP there would stop its re-render
        if resume:
            pipeline.resume(ctx)
        st.finish_supersede(run_dir, ctx.state)
        if ctx.state.get("supersede"):
            card = pipeline.finalize(ctx, pipeline.load_steps(), pipeline.supersede_blocked(ctx))
            cmd = getattr(retry, "cmd", None)
            if cmd not in (None, "next", "continue"):
                card["notes"].insert(0, "this %s was not applied: run it again once the old outputs are moved" % cmd)
            return card
        try:
            return fn(ctx, lock)
        except st.Stale as e:
            ctx = load_ctx(run_dir, deps, persist=True)
            card = pipeline.advance(ctx, pipeline.load_steps(), 0, lock)
            card.setdefault("notes", []).insert(0, "%s (%s); this is the run's current card" % (e.say, e))
            return card
    finally:
        lock.release()


def upgrade_seats(ctx):
    """Seat fixes for a run an older kit started or a migrated v1 run (migrate.upgrade), applied by every command that
    drives the run, under its lock: a single-family run whose <host>-alt runs the host's model again
    (families.<host>.alt_model null) keeps one screen and tournament judge, not the same model twice (#89). A judge
    step of such a seat that is not done yet loses its <host>-alt judge (drop_seat_jobs). Returns the changed seat keys
    (a run note names them)."""
    from ublib.engine import migrate
    changed = migrate.upgrade(ctx.state, registry.alt_distinct(ctx, ctx.host_family))
    if changed:
        st.add_note(ctx.state, "%s: one judge (%s); %s-alt runs the same model, so it is not a second judge" % (
            " and ".join(changed), ctx.host_family, ctx.host_family))
        drop_seat_jobs(ctx, changed, "%s-alt" % ctx.host_family)
    return changed


# the steps that fan out a judge seat, and the files their prepare step wrote for each judge (%s: the judge's label)
SEAT_STEPS = {"screen_judges": ("screen_judges", ["screen/%s.prompt.md"]),
              "tournament_judges": ("tournament_prompts", ["tournament/%s_*.prompt.md", "tournament/%s_*.map.json"])}


def drop_seat_jobs(ctx, keys, label):
    """X12: a judge step of a seat that lost `label` and is not done yet (in flight when the kit was updated, or not
    started with its prompts prepared) keeps only the judges still seated: the jobs of `label` (and their fallback
    copies) leave the step, their workers stop, and their outputs and prepared prompts move to _superseded/ through
    the journal, so the tally never counts them. A done step keeps what it counted."""
    from ublib.engine import builders
    rel, gone = [], []
    for s in pipeline.load_steps():
        fan = [SEAT_STEPS[k] for k in keys if SEAT_STEPS[k][0] == s.get("fanout")]
        if not fan or st.step_state(ctx.state, s["id"]) == "done" or not registry.eval_when(ctx, s.get("when") or []):
            continue
        rel += st.expand_globs(ctx.run_dir, [p % label for p in fan[0][1]])
        sst = (ctx.state.get("steps") or {}).get(s["id"]) or {}
        fb_of = sst.get("fallback_of") or {}
        ids = list(sst.get("jobs") or [])
        roots = set(j for j in ids if j not in fb_of and (builders.load_job(ctx, j) or {}).get("family") == label)
        drop = [j for j in ids if fb_of.get(j, j) in roots]
        for j in drop:
            out = (builders.load_job(ctx, j) or {}).get("out")
            rel += ([out, out + ".meta.json", out + ".failed.md"] if out else []) + [
                "jobs/%s.json" % j, "prompts/%s.prompt.md" % j, "prompts/%s.host.md" % j]
        for key in ("jobs", "originals", "exhausted"):
            if key in sst:
                sst[key] = [j for j in sst[key] if j not in drop]
        for j in drop:
            fb_of.pop(j, None)
        gone += drop
    st.check_supersede_paths(ctx.run_dir, rel)  # before a worker stops (#98)
    if gone:
        keep = set()
        for v in (ctx.state.get("steps") or {}).values():
            keep.update(v.get("jobs") or [])  # the dropped jobs left their steps above
        try:
            ctx.deps.batch.stop_all(ctx.run_dir, keep=sorted(keep))
        except Exception:  # noqa: BLE001 - as in pipeline.supersede_from
            pass
    if rel:
        st.supersede(ctx.run_dir, ctx.state, rel)


def legacy_waiting(lock, h):
    """True when h is the record of a live kit 2.0.x driver whose last beat is more than st.LEGACY_STALE_S old: a 2.0.x
    `ub run` waiting at a gate for an answer in its terminal (it beats no more and counts while it runs; 6.3)."""
    if not lock.legacy_holder(h):
        return False
    try:
        return time.time() - float(h.get("heartbeat_ts")) > st.LEGACY_STALE_S
    except (TypeError, ValueError):
        return False


def who_text(h):
    """'pid <pid>, <host>' of a lock.json record; '?' for what an empty or unparseable record does not say."""
    return "pid %s, %s" % (h.get("pid") or "?", h.get("host") or "?")


def busy_card(run_dir, deps, lock, retry=None, holder=None):
    """The card for a command refused because another session drives the run. holder: who holds it, as claim() said
    (a live kit 2.0.x driver's record, or a gone holder's record that another program holds open, with that reason in
    its host); else lock.json is read. A 2.0.x driver waiting at a gate is named with its remedy. retry: the refused
    command's parsed arguments with its command line (`argv`); its `then` runs the command again (retry_cmd), or, when
    an argument cannot be repeated safely in a command line, the card is BLOCKED and says so (not applied)."""
    ctx = load_ctx(run_dir, deps)  # read-only: a refused command writes nothing to the run's state
    h = holder or lock.legacy_holder() or lock.holder()
    who = "another session is driving this run (%s)" % who_text(h)
    done = "once the other session is done"
    say = who + "; waiting"
    if legacy_waiting(lock, h):
        who = "a kit 2.0.x session (%s) is waiting for an answer in its terminal" % who_text(h)
        done = "once that session is answered in its terminal or closed (Ctrl+C)"
        say = who + ": answer it there, or close it (Ctrl+C), to continue here; waiting"
    c = cards.auto(ctx, None, say, wait_s=30)
    if retry is not None and getattr(retry, "argv", None):  # a command built without a command line: just wait
        again = retry_cmd(retry, run_dir)
        if again is None:
            return cards.blocked(ctx, "%s, so this %s was not applied; one of its arguments (a double quote, $, a "
                                      "backtick, %% or !) cannot be repeated safely in a command line."
                                 % (who[0].upper() + who[1:], getattr(retry, "cmd", "command")),
                                 fix=["run the same command again %s" % done, cards.next_cmd(ctx.state, run_dir, 30)])
        c["then"] = "%s %s" % (cards.runner_of(ctx.state), again)
        c["notes"].insert(0, "nothing was changed; `then` runs this command again")
    return c


# ================================================================ init

def user_context_notes(info):
    """The notes of one detected family that name user instructions still reaching its worker calls (detect's
    USER_CONTEXT_NOTE lines: Codex AGENTS.md, CLAUDE.md above UB_HOME/tmp, inherit mode, Codex MCP servers), without
    the prefix (#28). Only called for a family that detection found available."""
    from ublib.detect import USER_CONTEXT_NOTE as prefix
    return [str(n)[len(prefix):] for n in (info or {}).get("notes") or [] if str(n).startswith(prefix)]


def family_table(detect_result, host_agent, host_family, only=None, cfg=None):
    fams = {}
    dfam = (detect_result or {}).get("families") or {}
    for f in FAMILY_ORDER:
        info = dfam.get(f) or {}
        chain = list(info.get("chain") or [])
        ok = bool(info.get("available"))
        backend = info.get("backend") or (chain[0] if chain else None)
        if chain == ["host"] or backend == "host":
            backend = "host"
        reason = "; ".join(info.get("notes") or []) if not ok else ""
        fams[f] = {"status": "ok" if ok else "unavailable", "backend": backend if ok else None,
                   "web": bool(info.get("web")) if ok else False, "reason": reason, "chain": chain}
        ucx = user_context_notes(info) if ok else []
        if ucx:
            fams[f]["user_context"] = ucx  # the kickoff card lists them (#28)
        if only and f not in only and f != host_family:
            fams[f]["status"] = "excluded"
            fams[f]["reason"] = "not in --families"
    # the host family: a host agent can always answer through its own sub-agents (HOST_BATCH) [U-14]
    hf = fams.get(host_family)
    if host_agent != "terminal" and hf is not None and hf["status"] != "ok":
        hf.update({"status": "ok", "backend": "host", "web": False,
                   "reason": "no headless backend: the host agent runs these jobs (HOST_BATCH)"})
    if host_agent == "terminal":
        for f, info in fams.items():
            if info.get("backend") == "host":
                info.update({"status": "unavailable", "backend": None,
                             "reason": "reachable only through an agent's sub-agents; dropped in terminal mode"})
    return fams


def shim_problems(ctx, fams, repo_root=None, host_family=None, host_agent=None, agent_family=None):
    """#29: a family whose first CLI backend resolves to a .cmd/.bat shim that cannot receive this run's paths is
    unavailable, with detect.shim_path_problem's reason; the host agent's own family (agent_family, by default the
    host family) then runs through the host's sub-agents instead. Only paths that reach the family's command lines
    count: UB_HOME (every call), and the repository (codex -C) and the run folder (claude's run-folder deny rules) only
    for a family of the run's host family's vendor in a repository run (repo_root given, a git repository): no other
    family gets a job that reads the repository (registry.repo_access, 6.8). A metacharacter in the project or run
    folder alone never takes out another vendor's family."""
    host_family = host_family or ctx.host_family
    host_agent = host_agent or ctx.host_agent
    agent_family = agent_family or host_family
    try:
        from ublib import detect as detect_mod
        from ublib import families as fam_mod
        from ublib import proc
        cfg = ctx.deps.families_cfg() or fam_mod.load_families()
    except Exception:  # noqa: BLE001 - no detection module: the worker reports the problem at its first call
        return
    repo = privacy_mod.is_git_repo(repo_root)  # as registry.is_repo decides: a worktree's or submodule's .git is a file
    for f, info in fams.items():
        if info.get("status") != "ok" or info.get("backend") == "host":
            continue
        reads_repo = repo and vendor_of(f) == vendor_of(host_family)
        for bid in info.get("chain") or []:
            btype = fam_mod.backend_type(cfg, bid)
            if not btype.endswith("-cli"):
                continue
            exe = proc.resolve_exe(fam_mod.backend_cfg(cfg, bid).get("exe") or btype.split("-", 1)[0])
            problem = detect_mod.shim_path_problem(exe, fam_mod.ub_home(), ctx.run_dir if reads_repo else None,
                                                   repo_root if reads_repo else None)
            if problem and f == agent_family and host_agent != "terminal":
                info.update({"backend": "host", "web": False, "reason": problem + "; host sub-agents used"})
            elif problem:
                info.update({"status": "unavailable", "backend": None, "reason": problem})
            break


def preflight(ctx, fams):
    """One parallel PING per candidate family (5.5). A failure marks the family unavailable."""
    jobs = []
    probes = {}
    created = pipeline.step_ref("created")
    vendors_ok = (ctx.state.get("privacy") or {}).get("vendors", True)
    web_ok = (ctx.state.get("privacy") or {}).get("web", True)
    from ublib import detect as detect_mod
    from ublib import families as fam_mod
    fake = bool(fam_mod.fake_families())
    for f, info in fams.items():
        if info.get("status") != "ok" or info.get("backend") == "host":
            continue
        if not vendors_ok and f != ctx.host_family:
            continue  # private: no call of any kind goes to another vendor
        jid = "0.1-ping-%s" % f
        prompt_rel = "prompts/%s.prompt.md" % jid
        from ublib.engine import builders
        text = registry.load_template("PING")
        try:
            text = builders.fill(ctx, text, {"family": f, "template": "PING"}) if text else None
        except EngineError:
            text = None
        ctx.write(prompt_rel, (text or "Reply with the single word PONG.").strip() + "\n")
        job = {"schema": 1, "run": textio.to_posix(ctx.run_dir), "id": jid, "step": created, "kind": "ping",
               "template": "PING", "family": f, "tier": "fast", "prompt_file": prompt_rel,
               "out": "logs/ping/%s.txt" % f, "tools": "none", "cwd": "empty", "repo_root": None, "timeout_s": 60,
               "retries": 0, "contract": {"type": "text", "regex": "PONG", "min_chars": 4}, "schema_file": None,
               "split": None, "fallback": [], "provisional": False,
               "privacy": privacy_mod.job_privacy(ctx.state, f, "none", "empty"), "host_prompt_file": None,
               "stub": {}}
        if ctx.family_chain(f):
            job["chain"] = ctx.family_chain(f)  # C13: the worker needs no detection of its own
        ctx.write_json("jobs/%s.json" % jid, job)
        jobs.append(job)
        info["preflight"] = True
        # [U-5] `codex exec -c web_search=live` is not confirmed to search: one live web job checks it
        if info.get("web") and info.get("backend") == "codex-cli" and web_ok and not fake:
            wid = "0.1-webprobe-%s" % f
            wrel = "prompts/%s.prompt.md" % wid
            ctx.write(wrel, detect_mod.WEB_PROBE_PROMPT + "\n")
            wjob = dict(job, id=wid, prompt_file=wrel, out="logs/ping/%s.web.txt" % f, tools="web",
                        kind="researcher", tier="default", timeout_s=180,
                        contract={"type": "text", "min_chars": 1},
                        privacy=privacy_mod.job_privacy(ctx.state, f, "web", "empty"))
            ctx.write_json("jobs/%s.json" % wid, wjob)
            jobs.append(wjob)
            probes[f] = wjob
    if not jobs:
        return
    batch = ctx.deps.batch
    try:
        res = batch.run_foreground(jobs, parallel=4, budget_s=90)
    except TypeError:
        res = batch.run_foreground([ctx.path("jobs", j["id"] + ".json") for j in jobs], parallel=4, budget_s=90)
    done = set(res.get("done") or [])
    for j in jobs:
        if j["id"].startswith("0.1-webprobe-"):
            continue  # a failed web probe only turns web off (below); the family's PING decides availability
        f = j["family"]
        jid = j["id"]
        ok = jid in done or any(isinstance(d, dict) and d.get("id") == jid for d in res.get("done") or [])
        if not ok:
            meta = ctx.read_json(j["out"] + ".meta.json", {}) or {}
            reason = "preflight PING failed (%s)" % (meta.get("error_class") or meta.get("status") or "no answer")
            if meta.get("reason"):
                reason += ": %s" % str(meta["reason"])[:200]
            if f == ctx.host_family and ctx.host_agent != "terminal":
                fams[f].update({"backend": "host", "web": False, "reason": reason + "; host sub-agents used"})  # [U-14]
            else:
                fams[f].update({"status": "unavailable", "backend": None, "reason": reason})
    for f, wjob in probes.items():
        if fams[f].get("status") != "ok" or fams[f].get("backend") == "host":
            continue
        try:
            text = ctx.read(wjob["out"])
        except (OSError, ValueError):
            text = ""
        if not detect_mod.web_probe_passed(text):
            fams[f]["web"] = False
            st.add_note(ctx.state, "%s: the live web-search probe found no search results, so web jobs go to other "
                                   "families [U-5]" % f)


def read_arg_file(path, flag, normalize=True):
    """The text of a file the user named on the command line; a file that cannot be read is a usage error (exit 2),
    never an internal one."""
    try:
        return textio.read_text(path, normalize=normalize)
    except OSError as e:
        raise UsageError("cannot read %s %s: %s" % (flag, path, e))


def kickoff_text(a):
    """The raw kickoff text: --text-file (read as written, so no shell ever touches the user's words) or --text."""
    if not getattr(a, "text_file", None):
        return a.text or ""
    return read_arg_file(a.text_file, "--text-file", normalize=False)


def check_card_paths(root):
    """Every card writes the run folder and ub.py into its commands in double quotes (4.12): a character that bash or
    PowerShell changes there would send every command of the run to another folder, so such a run is never
    started."""
    for what, path, fix in (("run folder", root, "start the run in a folder without it (--root <folder>)"),
                            ("kit folder", cards.UB_PY, "install the kit in a folder without it")):
        c = cards.unquotable(path)
        if c:
            raise UsageError("the %s %s holds %r, which bash and PowerShell change inside the double quotes of the "
                             "card commands; %s" % (what, textio.to_posix(path), c, fix))


def terminal_resume_cmd(run_dir):
    """`run --continue` for a run whose folder the card commands cannot carry: the terminal drives the run in its own
    process and runs no card command. The path goes in single quotes, which keep $, backticks and double quotes in
    bash and PowerShell; a path with a single quote is left out (in the project folder, `run --continue` resumes the
    newest unfinished run)."""
    p = textio.to_posix(run_dir)
    if re.search("['\u2018\u2019\u201a\u201b\r\n]", p):
        return "%s run --continue (in the run's project folder)" % cards.default_runner()
    return "%s run --continue '%s'" % (cards.default_runner(), p)


def command_word_hint(raw, word):
    """The error (a BLOCKED card) for kickoff text whose first word is a command word and whose rest is no run folder
    (#82): on the agent path it is neither run as that command nor started as a topic ("stop the nurse run" would
    otherwise start a new run and stop nothing)."""
    text = " ".join(raw.split())
    example = text if len(text) <= 80 else text[:77] + "..."
    todo = ("To check the setup, send %s alone." % word if word == "doctor" else
            "To %s a run, give its folder name (ub list shows them)." % word)
    return EngineError('"%s" starts with the command word %s, and the rest is not a run folder. To brainstorm this '
                       'topic, start again with a mode word before it, for example: standard %s. %s'
                       % (example, word, example, todo),
                       fix=["ub list --json"] + (["ub doctor --json"] if word == "doctor" else []))


def cmd_init(a, deps=None, terminal=False):
    deps = deps or make_deps()
    raw = kickoff_text(a)
    parsed = parse_text(raw)
    if parsed["command"] and not terminal:
        # a command only before nothing or a run folder; any other text after the word is not run as a topic here
        ref = run_ref(after_word(raw), a.root)
        if ref is None:
            raise command_word_hint(raw, parsed["command"])
        rest = ref or None
        if parsed["command"] == "continue":
            # with the command line of `continue`, so a busy card retries it (retry_cmd)
            argv = ["continue"] + ([rest] if rest else []) + (["--host", a.host] if a.host else []) + (
                ["--root", a.root] if a.root else []) + (["--json"] if a.json else [])
            return cmd_continue(argparse.Namespace(cmd="continue", argv=argv, run=rest, host=a.host, root=a.root,
                                                   json=a.json), deps)
        if parsed["command"] == "status":
            return cmd_status(argparse.Namespace(run=rest, json=a.json, root=a.root), deps)
        if parsed["command"] == "doctor":
            return cmd_doctor(argparse.Namespace(live=False, json=a.json), deps)
        if parsed["command"] == "stop":
            return cmd_stop(argparse.Namespace(run=rest, json=a.json, root=a.root), deps)
    host = a.host or "other"
    if host not in HOSTS:
        raise UsageError("--host must be one of %s" % ", ".join(HOSTS))
    os.environ["UB_HOST"] = host
    mode = a.mode or parsed["mode"] or "standard"
    if a.idea_file:
        mode = "proposal"
    if mode not in MODES:
        raise UsageError("--mode must be one of %s" % ", ".join(MODES))
    topic = parsed["rest"]
    if parsed["command"]:
        topic = " ".join(parsed["text"].split())  # `ub run` ran the real commands already: the word starts the topic
    idea_text = ""
    if a.idea_file:
        idea_text = " ".join(read_arg_file(a.idea_file, "--idea-file").split())
        topic = topic or idea_text
    elif mode == "proposal":
        idea_text = topic
    # read before the run folder exists, so a file that cannot be read leaves no folder behind
    seeds_text = read_arg_file(a.seeds_file, "--seeds-file") if a.seeds_file else None
    if terminal and not (topic or idea_text):
        # never an 'untitled run' folder, which a plain `continue` would then pick up as the newest run (#82)
        raise UsageError('give a topic: ub run "<topic>" (or --text / --text-file); to resume a run: ub run --continue '
                         '[RUN]')
    inferred = not (a.variant or parsed["variant"])
    variant = a.variant or parsed["variant"] or infer_variant(topic)
    if variant not in VARIANTS:
        raise UsageError("--variant must be one of %s" % ", ".join(VARIANTS))
    autopilot = a.autopilot or parsed["autopilot"] or "guided"
    if autopilot not in AUTOPILOTS:
        raise UsageError("--autopilot must be one of %s" % ", ".join(AUTOPILOTS))
    root, root_note = st.run_root(a.root)
    check_card_paths(root)
    run_dir = st.new_run_dir(root, topic or "untitled run")
    os.makedirs(run_dir, exist_ok=True)
    try:
        rc, _, _ = deps.bs(["init", run_dir], run_dir)
    except EngineError:
        pass
    st.ensure_run_dirs(run_dir)
    only = None
    if a.families and a.families != "auto":
        only = [base_family(f.strip()) for f in a.families.split(",") if f.strip()]
    detect_result = {}
    st_note = None
    try:
        detect_result = deps.detect(live=False, only=None) or {}
    except EngineError as e:
        detect_result = {"families": {}, "host": {}}
        st_note = str(e)
    host_info = detect_result.get("host") or {}
    host_family = host_info.get("family") or os.environ.get("UB_HOST_FAMILY") or HOST_DEFAULT_FAMILY.get(host)
    family_source = host_info.get("source") or ("env" if os.environ.get("UB_HOST_FAMILY") else "default")
    fams = family_table(detect_result, host, host_family, only)
    if host == "terminal" or not host_family:
        avail = [f for f in FAMILY_ORDER if fams[f]["status"] == "ok"]
        if host_family not in avail:
            host_family = avail[0] if avail else "claude"
            family_source = "default"
    runner = cards.default_runner()
    state = st.new_state(run_dir, topic, host, host_family, family_source, mode=mode, variant=variant,
                         autopilot=autopilot, lang=a.lang or "en", python=cards.python_launcher(), runner=runner,
                         project_dir=os.getcwd())
    state["families"] = fams
    state["idea_text"] = idea_text
    state["raw_text"] = raw  # the kickoff text exactly as received (the topic above is its whitespace-joined rest)
    state["components"] = component_map(a.components)
    state["options"]["with_ce_ideate"] = bool(parsed["with_ce_ideate"])
    state["options"]["variant_inferred"] = inferred  # G0 then says how to change it
    private = parsed["private"] or a.privacy == "private"
    defaults = st.config_get("privacy_defaults")
    if private:
        state["privacy"].update({"web": False, "vendors": False, "code": False})
        state["options"]["private"] = True
    elif isinstance(defaults, dict):
        for k in ("web", "vendors", "code"):
            if isinstance(defaults.get(k), bool):  # 'no' (a string from `ub config set`) is no answer: G0 asks
                state["privacy"][k] = defaults[k]
    if not private:  # a `no` typed with the topic applies to this run over the defaults; a `yes` is G0's to give
        state["privacy"].update((k, False) for k, v in parsed["privacy"].items() if v is False)
    state["options"]["explicit_privacy"] = bool(private or a.privacy or parsed["privacy"].get("vendors") is False)
    if parsed["privacy_unread"] and not private:  # a no the text shows but not as a setting: G0 asks (6.2)
        state["options"]["privacy_unread"] = parsed["privacy_unread"]
        st.add_note(state, "your text seems to say %s inside the topic, so it is not applied yet: reply %s to apply "
                           "it" % (" and ".join("`%s: no`" % k for k in parsed["privacy_unread"]),
                                   ", ".join("`%s: no`" % k for k in parsed["privacy_unread"])))
    if root_note:
        st.add_note(state, root_note)
    if st_note:
        st.add_note(state, "family detection failed: %s" % st_note)
    ctx = st.Ctx(run_dir, state, deps)
    shim_problems(ctx, fams, os.getcwd() if variant in REPO_VARIANTS else None)
    if seeds_text is not None:
        ctx.write("00_HUMAN_SEEDS.md", seeds_text)
    if not a.no_preflight:
        try:
            preflight(ctx, fams)
        except EngineError as e:
            st.add_note(state, "preflight skipped: %s" % e)
    registry.reseat(ctx)
    for f, info in fams.items():
        if info.get("status") == "unavailable" and info.get("reason"):
            st.add_note(state, "%s: %s" % (f, info["reason"]))
    st.set_step(state, pipeline.step_ref("created"), "done", note="run created")
    keep_kickoff_file(a, root, run_dir)
    lock = st.DriverLock(run_dir, host)
    lock.acquire()  # the folder is new (an atomic mkdir), so no other session can hold its lock yet
    try:
        lock.claim()
        st.save(run_dir, state)
        st.register_run(run_dir, topic)
        st.append_event(run_dir, "init", host=host, mode=mode, variant=variant)
        steps = pipeline.load_steps()
        if terminal:
            from ublib.engine import terminal as terminal_mode
            state["exec"]["wait_s"] = terminal_mode.TERMINAL_WAIT_S
            return terminal_mode.run_loop(ctx, steps, lock)
        return pipeline.advance(ctx, steps, 0, lock)
    finally:
        lock.release()


def keep_kickoff_file(a, root, run_dir):
    """A --text-file the host wrote into the run root (SKILL.md: brainstorm/.kickoff.txt) moves into the new run
    (.ub/kickoff.txt), so the run root stays clean and a later start can never reuse it by mistake."""
    path = getattr(a, "text_file", None)
    if not path or os.path.normcase(os.path.dirname(os.path.abspath(path))) != os.path.normcase(os.path.abspath(root)):
        return
    try:
        os.replace(path, os.path.join(run_dir, ".ub", "kickoff.txt"))
    except OSError:
        pass


# ================================================================ commands

def cmd_next(a, deps=None):
    run_dir, how = open_run(a.run)
    steps = pipeline.load_steps()

    def go(ctx, lock):
        wait = a.wait_s if a.wait_s is not None else int(((ctx.state.get("exec") or {}).get("wait_s", 540)))
        return pipeline.advance(ctx, steps, wait, lock)
    # `next` is the agent's own poll: it never lifts a `ub stop` (only continue / run --continue do, C3). Its busy card
    # retries it with its --lease, so a lease holder never waits for itself (#96).
    return with_run(run_dir, deps, go, retry=a, lease=getattr(a, "lease", None))


def cmd_answer(a, deps=None):
    run_dir, _ = open_run(a.run)
    steps = pipeline.load_steps()
    gid = a.gate
    if gid not in gates.FIELDS:
        raise UsageError("unknown gate %s" % gid)
    if not (a.file or a.choice is not None or a.default or a.skip):
        raise UsageError("answer needs --file, --choice, --default or --skip")

    def go(ctx, lock):
        if a.file:
            try:
                provided = textio.read_json(a.file)
            except (OSError, ValueError) as e:
                pgid, step = pipeline.pending_gate(ctx, steps)
                return pipeline.finalize(ctx, steps, pipeline.human_card(
                    ctx, step, gid, error="the answer file is not valid JSON (%s); write it again" % e))
            # an object (the template) or a string (the reply); gates.prepare_answer re-asks any other JSON value
        elif a.choice is not None:
            provided = gates.from_choice(gid, a.choice)
        elif a.default:
            provided = gates.default_answer(gid)
        else:
            provided = {"reply": "skip"}
            if "skip" in gates.FIELDS[gid]:
                provided["skip"] = True
        card = pipeline.answer_gate(ctx, steps, gid, provided, lock, by="human")
        if a.file and os.path.normcase(os.path.dirname(os.path.abspath(a.file))) == os.path.normcase(
                os.path.join(ctx.run_dir, ".ub", "retry")):
            try:
                os.remove(a.file)  # a --choice a busy card kept for its retry (retry_cmd): answered, so used up
            except OSError:
                pass
        return card
    # --lease: a HUMAN card handed to the holder of the current step's lease (GB mid-step) carries it (#96)
    return with_run(run_dir, deps, go, retry=a, lease=getattr(a, "lease", None))


def cmd_done(a, deps=None):
    run_dir, _ = open_run(a.run)
    steps = pipeline.load_steps()
    return with_run(run_dir, deps, lambda ctx, lock: pipeline.host_done(ctx, steps, a.step, lock),
                    retry=a, lease=getattr(a, "lease", None))


def reseat_for_host(ctx, host):
    """Cross-host continue (6.10): re-detect families, re-seat what disappeared, record it as PROVISIONAL."""
    import copy as _copy
    from ublib.engine import seats as seats_mod
    s = ctx.state
    old_seats = _copy.deepcopy(s.get("seats") or {})
    old_host = ctx.host_family
    os.environ["UB_HOST"] = host
    try:
        det = ctx.deps.detect(live=False, only=None) or {}
    except EngineError:
        det = {}
    own = ((det.get("host") or {}).get("family")) or HOST_DEFAULT_FAMILY.get(host)  # None: a host of no known family
    agent_family = own or old_host
    base = family_table(det, host, agent_family)
    for f, info in (s.get("families") or {}).items():
        # a kickoff-list exclusion is not carried: the `if told:` loop below sets it again from the list and the host
        if info.get("status") == "excluded" and f in base and "was not listed" not in (info.get("reason") or ""):
            base[f]["status"] = "excluded"
    repo = s.get("project_dir") if ctx.variant in REPO_VARIANTS else None

    def checked(run_family):
        # the shim check for a run hosted by run_family: its vendor's families read the repository (#29)
        out = _copy.deepcopy(base)
        shim_problems(ctx, out, repo, run_family, host, agent_family)
        return out
    # consent never widens on a re-seat: once the kickoff is answered, a family of a vendor it never listed stays out
    # (the agent the user moved the run to sees the text anyway); before that, the kickoff card here lists the vendors
    was = (s.get("privacy") or {}).get("allowed_vendors")
    told = isinstance(was, list) and was and (((s.get("gates") or {}).get("G0") or {}).get("answer")
                                             or s.get("legacy_v1"))
    if told:  # the list the kickoff answered, kept apart: a `vendors: no` re-seat narrows allowed_vendors to one host
        was = s["privacy"].setdefault("kickoff_vendors", list(was))
    # the run keeps its host family while a real backend still reaches it, with the repository paths its jobs get;
    # otherwise the new agent's family (terminal: the first family available of a vendor the kickoff listed)
    # a host family of a vendor neither listed at the kickoff nor the new agent's (a terminal, or a host of no known
    # family, has none) is not kept
    fams = checked(old_host)
    listed = not told or vendor_of(old_host) in was or (host != "terminal" and bool(own) and
                                                        vendor_of(old_host) == vendor_of(own))
    keep = listed and (fams.get(old_host) or {}).get("status") == "ok" and \
        (fams.get(old_host) or {}).get("backend") != "host"
    run_host = old_host if keep or old_host == agent_family and listed else agent_family
    if not keep and (host == "terminal" or not own and not listed):
        run_host = old_host if listed else next((f for f in FAMILY_ORDER if vendor_of(f) in was), old_host)
        for f in FAMILY_ORDER:
            if told and vendor_of(f) not in was:
                continue
            cand = fams if vendor_of(f) == vendor_of(old_host) else checked(f)
            if (cand.get(f) or {}).get("status") == "ok":
                run_host, fams = f, cand
                break
    elif vendor_of(run_host) != vendor_of(old_host):
        fams = checked(run_host)
    if told:
        for f, info in fams.items():
            if info.get("status") == "ok" and vendor_of(f) not in was and vendor_of(f) != vendor_of(run_host):
                info.update(status="excluded", reason="%s was not listed at the kickoff" % vendor_of(f))
    s["families"] = fams
    s["host"] = {"agent": host, "family": run_host,
                 "family_source": (det.get("host") or {}).get("source", "default") if run_host == agent_family
                 else (s.get("host") or {}).get("family_source", "default")}
    s["exec"]["wait_s"] = HOST_WAIT_S.get(host, 50)
    registry.reseat(ctx)  # a full 6.6 assignment on what is left ...
    if told and s["privacy"].get("vendors", True):  # ... and a listed vendor this host lacks stays allowed for later
        s["privacy"]["allowed_vendors"] = sorted(set(s["privacy"]["allowed_vendors"]) | set(was))
    available = [f for f, i in fams.items() if i.get("status") == "ok" and st.family_allowed(s, f)]
    seats, changes = seats_mod.reseat_minimal(old_seats, s["seats"], available, run_host)  # ... applied minimally
    s["seats"] = seats
    if run_host != old_host:
        changes.insert(0, ("host family", old_host, run_host))
    for key, before, after in changes:
        st.add_provisional(s, "continue --host %s (%s)" % (host, key), before, after,
                           "%s is not available on this host" % before)
    return len(changes)


def cmd_continue(a, deps=None):
    """Resume a run here: under the driver lock, re-seat for a new host (or, on the same host, detect again the
    families an authentication failure took out), lift a `ub stop`, take over a HOST task or HOST_BATCH that another
    session holds, and return the current card."""
    run_dir, how = open_run(a.run, getattr(a, "root", None))
    bad = cards.unquotable(run_dir)
    if bad:
        # a run an older kit started there, or a folder renamed later: its card commands would reach another folder
        raise EngineError("the run folder %s holds %r, which bash and PowerShell change inside the double quotes of "
                          "the card commands, so an agent cannot drive this run" % (textio.to_posix(run_dir), bad),
                          fix=["move the run folder to a path without %r, then continue" % bad,
                               "or resume it in a terminal: %s" % terminal_resume_cmd(run_dir)])
    steps = pipeline.load_steps()
    host = getattr(a, "host", None)

    def go(ctx, lock):
        note = "continuing %s%s" % (os.path.basename(run_dir), (" (%s)" % how) if how else "")
        if host and host != ctx.host_agent:
            n = reseat_for_host(ctx, host)
            note += "; host is now %s (%d seats changed)" % (host, n)
            st.save(run_dir, ctx.state)
        else:
            lifted = pipeline.redetect_auth(ctx)
            if lifted:
                note += "; %s detected again: used again" % ", ".join(lifted)
                st.save(run_dir, ctx.state)
        card = pipeline.advance(ctx, steps, 0, lock)
        card.setdefault("notes", []).insert(0, note)
        return card
    return with_run(run_dir, deps, go, host=host, retry=a, resume=True, takeover=True)


def cmd_status(a, deps=None):
    run_dir, _ = open_run(a.run, getattr(a, "root", None))
    ctx = load_ctx(run_dir, deps)
    steps = pipeline.load_steps()
    cur = pipeline.current_step(ctx, steps)
    block = progress.progress_block(ctx, steps, cur)
    return {"ub": ENGINE_VERSION, "run": textio.to_posix(run_dir), "status": ctx.state.get("status"),
            "mode": ctx.mode, "variant": ctx.variant, "autopilot": ctx.autopilot,
            "step": cur["id"] if cur else None, "step_title": cur.get("title") if cur else None,
            "gate": cur.get("gate") if cur and cur.get("type") == "HUMAN" else None, "progress": block,
            "budget": dict((k, v) for k, v in progress.budget_status(ctx).items() if k != "need"),
            "families": progress.families_line(ctx), "provisional": ctx.state.get("provisional") or [],
            "progress_file": textio.to_posix(ctx.path("PROGRESS.md"))}


def synthetic_ctx(mode, variant, families, host="claude-code", deps=None):
    fams = [base_family(f) for f in families] or ["claude"]
    host_family = fams[0]
    state = st.new_state("plan-preview", "preview", host, host_family, mode=mode, variant=variant)
    state["run"] = "plan-preview"
    web_ok = {"claude": True, "gpt": True, "kimi": False, "glm": False}
    state["families"] = dict((f, {"status": "ok" if f in fams else "unavailable",
                                  "backend": "cli" if f in fams else None, "web": web_ok.get(f, False),
                                  "reason": ""}) for f in FAMILY_ORDER)
    ctx = st.Ctx(None, state, deps or make_deps(), sim=dict(pipeline.DEFAULT_SIM))
    registry.reseat(ctx)
    return ctx


def cmd_plan(a, deps=None):
    if a.run:
        run_dir, _ = open_run(a.run)
        ctx = load_ctx(run_dir, deps)
        ctx.sim = dict(pipeline.DEFAULT_SIM)
    else:
        mode = a.mode or "standard"
        variant = a.variant or "general"
        if mode not in MODES or variant not in VARIANTS:
            raise UsageError("plan needs a valid --mode and --variant")
        fams = [f.strip() for f in (a.families or "claude").split(",") if f.strip()]
        ctx = synthetic_ctx(mode, variant, fams, deps=deps)
    p = progress.plan(ctx)
    p["mode"], p["variant"] = ctx.mode, ctx.variant
    p["families"] = (ctx.state.get("seats") or {}).get("families")
    return p


STOP_LOCK_WAIT_S = 10  # `ub stop` waits this long for a live driver, which sees .ub/STOP within one poll and lets go


def _nothing_to_stop(state):
    """A finished run: done, or stopped for good (GX stop, a declined v1 extension). A `ub stop` pause and a budget
    stop are not finished."""
    reason = str(state.get("stopped_reason") or "")
    return state.get("status") == "done" or (state.get("status") == "stopped" and reason != "user" and
                                             "budget" not in reason)


def stop_workers(deps, run_dir):
    """(workers stopped, [pids of live workers that could not be verified]) from batch.stop_workers (#2): a worker
    whose process identity cannot be read (ps unavailable, another user's process) is never killed and keeps its
    marker. A batch module without stop_workers (a test double) gives stop_all's count and no pids."""
    fn = getattr(deps.batch, "stop_workers", None)
    if fn is None:
        return int(deps.batch.stop_all(run_dir) or 0), []
    res = fn(run_dir) or {}
    return int(res.get("stopped") or 0), sorted(int(p) for p in res.get("unverified") or [])


def unverified_text(pids):
    """The stop card's sentence for the workers `ub stop` could not verify, and so did not kill."""
    if not pids:
        return ""
    return (" %d worker(s) could not be verified (pid %s): stop them by hand (their process identity cannot be read, "
            "so they were not killed)." % (len(pids), ", ".join(str(p) for p in pids)))


def cmd_stop(a, deps=None):
    """C3: the sentinel .ub/STOP first (no driver launches and no worker starts a call while it exists), then the
    workers are killed, then the stop is recorded in run.json under the driver lock. When another session drives the
    run it records the stop itself at its next check; a kit 2.0.x driver never sees it (the card says to stop that
    session, or to close it when it waits at a gate), and a lock.json another program holds open keeps it from being
    recorded until stop runs again. `continue` and `run --continue` lift it; `next` does not. A
    finished run has nothing to stop: no STOP is written (it would stop a later probe-result, redo or switch halfway
    through), only leftover workers are stopped."""
    run_dir, _ = open_run(a.run, getattr(a, "root", None))
    deps = deps or make_deps()
    try:
        finished = _nothing_to_stop(load_ctx(run_dir, deps).state)  # read-only
    except EngineError:
        finished = False  # an unreadable run.json: its workers are stopped all the same
    if finished:
        n, unverified = stop_workers(deps, run_dir)
        st.append_event(run_dir, "stop", killed=n, finished=True, unverified=unverified)
        return {"ub": ENGINE_VERSION, "run": textio.to_posix(run_dir), "stopped": n, "unverified": unverified,
                "say": "This run is finished, so there is nothing to stop%s.%s" % (
                    " (%d leftover worker(s) stopped)" % n if n else "", unverified_text(unverified))}
    st.request_stop(run_dir)
    n, unverified = stop_workers(deps, run_dir)
    lock = st.DriverLock(run_dir, "stop")
    got = lock.acquire(STOP_LOCK_WAIT_S)
    legacy = None
    try:
        legacy = lock.claim() if got else None
        if got and not legacy:
            ctx = load_ctx(run_dir, deps, persist=True)
            if _nothing_to_stop(ctx.state):
                st.clear_stop(run_dir)  # it finished meanwhile
            else:
                ctx.state["status"], ctx.state["stopped_reason"] = "stopped", "user"
                st.save(run_dir, ctx.state)
        holder = legacy or lock.holder()
    finally:
        lock.release()
    st.append_event(run_dir, "stop", killed=n, unverified=unverified)
    say = "Stopped %d running worker(s).%s Continue later with: continue." % (n, unverified_text(unverified))
    if legacy and legacy_waiting(lock, legacy):
        say += (" A kit 2.0.x session (%s) is waiting for an answer in its terminal; it does not see the stop, "
                "so close it there (Ctrl+C)." % who_text(holder))
    elif legacy and not legacy.get("held_open") and (legacy.get("pid") is None or lock.legacy_holder(legacy)):
        # a live 2.0.x driver, or (no pid) a 2.0.3 driver writing its record right now
        say += (" A session of an older kit (2.0.3) is driving this run (%s); it does not see the stop, so "
                "stop that session too." % who_text(holder))
    elif legacy:  # a gone holder's record that another program holds open (DriverLock.claim)
        say += (" Another program holds .ub/lock.json open, so the stop is not recorded in run.json yet: close that "
                "program, then run stop again.")
    elif not got:
        say += " Another session is driving this run (%s); it stops at its next check." % who_text(holder)
    return {"ub": ENGINE_VERSION, "run": textio.to_posix(run_dir), "stopped": n, "unverified": unverified,
            "say": say}


def cmd_budget(a, deps=None):
    """`ub budget RUN --max-calls N` (#12): the run's request cap, set under the driver lock. N must cover the requests
    already sent and the launch the cap refused. A budget stop (full-auto) or a waiting GB that N no longer binds is
    lifted, and the run's next card is returned."""
    run_dir, _ = open_run(a.run)
    steps = pipeline.load_steps()

    def go(ctx, lock):
        err = gates.cap_error(ctx, a.max_calls)
        if err:
            raise EngineError(err, fix=[cards.with_lease(pipeline.budget_cmd(ctx), ctx.lease)])
        budget = ctx.state.setdefault("budget", {})
        old = budget.get("max_calls")
        budget["max_calls"] = int(a.max_calls)
        if (ctx.state.get("interrupt") or {}).get("gate") == "GB":
            st.record_gate(ctx.state, "GB", "answered", "human", {"reply": "ub budget", "raise_to": int(a.max_calls)})
        if not progress.budget_binds(ctx):
            pipeline.clear_budget_stop(ctx)
        st.append_event(run_dir, "budget", max_calls=int(a.max_calls), was=old)
        card = pipeline.advance(ctx, steps, 0, lock)
        card.setdefault("notes", []).insert(0, "budget.max_calls: %s -> %d requests" % (old, int(a.max_calls)))
        return card
    return with_run(run_dir, deps, go, retry=a, lease=getattr(a, "lease", None))


def cmd_redo(a, deps=None):
    run_dir, _ = open_run(a.run)
    steps = pipeline.load_steps()
    pipeline.index_of(steps, a.step)
    if not a.yes:
        ctx = load_ctx(run_dir, deps)
        prev = gates.redo_plan(ctx, a.step)
        return {"ub": ENGINE_VERSION, "run": textio.to_posix(run_dir), "redo": a.step, "preview": prev,
                "say": "Redo moves the outputs of %s and every later step to _superseded/ and runs them again "
                       "(about %d calls). Confirm with --yes." % (a.step, prev["calls"]["expected"]),
                "confirm_cmd": '%s redo "%s" %s --yes' % (cards.runner_of(ctx.state), textio.to_posix(run_dir),
                                                          a.step)}

    def go(ctx, lock):
        moved = pipeline.supersede_from(ctx, steps, a.step)
        card = pipeline.advance(ctx, steps, 0, lock)
        card.setdefault("notes", []).insert(0, "redo %s: %d files moved to _superseded/" % (a.step, len(moved)))
        return card
    return with_run(run_dir, deps, go, retry=a)


def switch_target(ctx, steps, a):
    """The step a switch redoes from, after checking the requested architecture or idea: an idea must be a finalist
    that its own probe did not kill (K6) and not the chosen idea."""
    if a.arch:
        if a.arch not in registry.arch_labels(ctx):
            raise EngineError("%s is not an architecture candidate (%s)" % (a.arch, ", ".join(registry.arch_labels(
                ctx)) or "none yet"))
        return pipeline.step_ref("switch_arch_from")
    finalists = ctx.state.get("finalists") or []
    if a.idea not in finalists:
        raise EngineError("%s is not one of the finalists (%s)" % (a.idea, ", ".join(finalists) or "none yet"))
    if a.idea in registry.k6_killed(ctx.state):
        left = pipeline.finalists_left(ctx.state)
        raise EngineError("%s was killed by its probe (K6); choose another finalist (%s)" % (a.idea, ", ".join(left))
                          if left else "%s was killed by its probe (K6), and no other finalist is left to test; start "
                                       "a new run with a reframed topic" % a.idea)
    if a.idea == registry.chosen_idea(ctx):
        raise EngineError("%s is already the chosen idea" % a.idea)
    return pipeline.step_ref("probe_from", ctx)


def cmd_switch(a, deps=None):
    run_dir, _ = open_run(a.run)
    steps = pipeline.load_steps()
    if not a.arch and not a.idea:
        raise UsageError("switch needs --arch LABEL or --idea ID")
    if not a.yes:
        ctx = load_ctx(run_dir, deps)
        target = switch_target(ctx, steps, a)
        prev = gates.redo_plan(ctx, target)
        return {"ub": ENGINE_VERSION, "run": textio.to_posix(run_dir), "switch": a.arch or a.idea, "redo": target,
                "preview": prev, "say": "Switching redoes %s onward (about %d calls). Confirm with --yes."
                                        % (target, prev["calls"]["expected"]),
                "confirm_cmd": '%s switch "%s" %s --yes' % (cards.runner_of(ctx.state), textio.to_posix(run_dir),
                                                            ("--arch %s" % a.arch) if a.arch else
                                                            ("--idea %s" % a.idea))}

    def go(ctx, lock):
        switch_target(ctx, steps, a)
        if a.arch:
            pipeline.switch_arch(ctx, steps, a.arch)
        else:
            pipeline.switch_idea(ctx, steps, a.idea)
        return pipeline.advance(ctx, steps, 0, lock)
    return with_run(run_dir, deps, go, retry=a)


def cmd_probe_result(a, deps=None):
    run_dir, _ = open_run(a.run)
    steps = pipeline.load_steps()
    result = a.result.upper()
    if result not in ("PASSED", "MISSED", "INCONCLUSIVE"):
        raise UsageError("result must be PASSED, MISSED or INCONCLUSIVE")
    note = read_arg_file(a.note_file, "--note-file") if a.note_file else ""

    def go(ctx, lock):
        # A result is for the probe the finished run handed out (its DONE card names it) for the chosen idea. After a
        # MISSED the runner-up's probe is designed again and the run is not done: a repeated MISSED is refused then.
        if ctx.state.get("status") != "done" or not ctx.exists("09_PROBE.md"):
            raise EngineError("no probe of %s is waiting for a result: report it after the run is done (its DONE card "
                              "names the probe to run)" % (registry.chosen_idea(ctx) or "the chosen idea"),
                              fix=[cards.next_cmd(ctx.state, ctx.run_dir)])
        effects = gates.probe_result(ctx, result, note)
        if ctx.state.get("status") == "done" and any(e[0] in ("reset", "supersede") for e in effects):
            ctx.state["status"] = "active"
        pipeline.apply_effects(ctx, steps, effects)
        card = pipeline.advance(ctx, steps, 0, lock)
        card.setdefault("notes", []).insert(0, "probe result recorded: %s" % result)
        return card
    return with_run(run_dir, deps, go, retry=a)


def cmd_import(a, deps=None):
    """An idea list from another tool joins the pool as pool/IMPORT_<name>.md, and the pool is curated again with it
    (refs.import_from: 5.1; quick mode Q.3). A curation step that already ran (or is running) is redone from there;
    one still pending reads the file when it runs. Proposal mode has no pool: refused."""
    run_dir, _ = open_run(a.run)
    steps = pipeline.load_steps()
    name = re.sub(r"[^A-Za-z0-9_-]+", "_", os.path.splitext(os.path.basename(a.file))[0])[:40] or "import"
    rel = "pool/IMPORT_%s.md" % name
    text = read_arg_file(a.file, "import FILE")

    def go(ctx, lock):
        if ctx.mode == "proposal":
            raise EngineError("proposal mode has no idea pool, so an imported list would never be read; import into a "
                              "quick, standard or deep run, or start one with --seeds-file")
        start = pipeline.step_ref("import_from", ctx)
        if not registry.eval_when(ctx, pipeline.step_by_id(steps, start).get("when") or []):
            raise EngineError("step %s, which curates the pool, does not run in this %s run, so an imported list "
                              "would never be read" % (start, ctx.mode),
                              fix=["reinstall the kit (engine and pipeline.json versions differ): install.py update"])
        ctx.write(rel, text)
        if st.step_state(ctx.state, start) in ("done", "running", "blocked"):
            pipeline.supersede_from(ctx, steps, start)
            note = "imported %s; the pool is curated again from step %s" % (rel, start)
        else:
            note = "imported %s; step %s curates it with the pool" % (rel, start)
        card = pipeline.advance(ctx, steps, 0, lock)
        card.setdefault("notes", []).insert(0, note)
        return card
    return with_run(run_dir, deps, go, retry=a)


def cmd_attach_s1(a, deps=None):
    run_dir, _ = open_run(a.run)
    ctx = load_ctx(run_dir, deps)
    doc = read_arg_file(a.doc, "--doc")  # both files first: a bad --raw leaves no half-done attach
    raw = read_arg_file(a.raw, "--raw") if a.raw else None
    ctx.write("pool/S1_ce-ideate.md", doc)
    if raw is not None:
        ctx.write("pool/S1_ce-ideate_raw.md", raw)
    return {"ub": ENGINE_VERSION, "run": textio.to_posix(run_dir), "ok": True,
            "written": [textio.to_posix(ctx.path("pool/S1_ce-ideate.md"))] +
            ([textio.to_posix(ctx.path("pool/S1_ce-ideate_raw.md"))] if a.raw else []),
            "then": '%s done "%s" 4.1c --json' % (cards.runner_of(ctx.state), textio.to_posix(run_dir))}


def cmd_render(a, deps=None):
    from ublib.engine import render
    run_dir, _ = open_run(a.run)
    ctx = load_ctx(run_dir, deps)
    if not ctx.exists("11_PROPOSAL/PROPOSAL.md"):
        raise EngineError("11_PROPOSAL/PROPOSAL.md does not exist yet")
    out = render.render_pack(ctx, make_zip=a.zip)
    return dict({"ub": ENGINE_VERSION, "run": textio.to_posix(run_dir), "ok": True}, **out)


def cmd_export(a, deps=None):
    from ublib.engine import render
    run_dir, _ = open_run(a.run)
    ctx = load_ctx(run_dir, deps)
    res = render.export(ctx, a.format)
    return dict({"ub": ENGINE_VERSION, "run": textio.to_posix(run_dir)}, **res)


def cmd_doctor(a, deps=None):
    from ublib.engine import SK_DIR, TEMPLATES_DIR, ESTIMATES_FILE, BS_PY, FAMILY_PY
    deps = deps or make_deps()
    checks = []

    def add(cid, ok, msg, warn=False):
        checks.append({"id": cid, "status": "PASS" if ok else ("WARN" if warn else "FAIL"), "message": msg})
    add("python", sys.version_info >= (3, 9), "Python %s" % sys.version.split()[0])
    try:
        steps = pipeline.load_steps()
        add("pipeline", True, "%d steps" % len(steps))
    except EngineError as e:
        add("pipeline", False, str(e))
        steps = []
    add("estimates", os.path.exists(ESTIMATES_FILE), textio.to_posix(ESTIMATES_FILE), warn=True)
    missing = []
    for s in steps:
        tpl = (s.get("job") or {}).get("template")
        if tpl and not os.path.exists(registry.template_path(tpl)):
            missing.append(tpl)
        if s.get("type") == "HUMAN" and not os.path.exists(os.path.join(TEMPLATES_DIR, "gates", s["gate"] + ".md")):
            missing.append("gates/" + s["gate"])
    add("templates", not missing, "missing: %s" % ", ".join(sorted(set(missing))) if missing else
        "all referenced templates present", warn=True)
    add("bs.py", os.path.exists(BS_PY), textio.to_posix(BS_PY))
    add("family.py", os.path.exists(FAMILY_PY), textio.to_posix(FAMILY_PY))
    if os.name == "nt":
        lp = st.long_paths_enabled()
        add("long_paths", bool(lp), "Windows long paths (LongPathsEnabled): %s" % (
            "on" if lp else "off: a run folder and its files must stay under 259 characters; keep projects in short "
                            "folders or use --root" if lp is False else "unknown"), warn=True)
    home = st.ub_home()
    try:
        os.makedirs(home, exist_ok=True)
        probe = os.path.join(home, ".ub-write-test")
        textio.write_text_atomic(probe, "ok\n")
        os.remove(probe)
        add("ub_home", True, textio.to_posix(home))
    except OSError as e:
        add("ub_home", False, "%s: %s" % (textio.to_posix(home), e))
    detect = None
    if os.path.exists(FAMILY_PY):
        from ublib import proc
        argv = [sys.executable, FAMILY_PY, "detect", "--json"] + (["--live"] if a.live else [])
        try:
            res = proc.run(argv, timeout_s=180)
            detect = textio.extract_json(textio.decode_bytes(res.stdout_bytes))
            add("detect", res.returncode == 0, "family.py detect exit %d" % res.returncode, warn=True)
        except Exception as e:
            add("detect", False, "family.py detect failed: %s" % e, warn=True)
    fams = (detect or {}).get("families") or {}
    n_ok = len([f for f, i in fams.items() if isinstance(i, dict) and i.get("available")])
    if detect is not None:
        add("families", n_ok >= 1, "%d model families available%s" % (
            n_ok, "" if n_ok >= 2 else " (cross-family judging needs 2; runs are PROVISIONAL)"), warn=n_ok >= 1)
    for f in FAMILY_ORDER:  # user instructions that still reach an available family's worker calls (#28)
        info = fams.get(f) if isinstance(fams.get(f), dict) else {}
        notes = user_context_notes(info) if info.get("available") else []
        if notes:
            add("user_context_%s" % f, False, "; ".join("Still reaching worker calls: %s" % n for n in notes),
                warn=True)
    status = "fail" if any(c["status"] == "FAIL" for c in checks) else (
        "warn" if any(c["status"] == "WARN" for c in checks) else "pass")
    return {"ub": ENGINE_VERSION, "status": status, "checks": checks, "detect": detect,
            "skill_dir": textio.to_posix(SK_DIR)}


def cmd_config(a, deps=None):
    if a.action == "get":
        return {"key": a.key, "value": st.config_get(a.key)}
    if a.value is None:
        raise UsageError("config set needs a VALUE")
    st.config_set(a.key, st.parse_config_value(a.value))
    return {"key": a.key, "value": st.config_get(a.key), "file": textio.to_posix(st.config_path())}


def cmd_list(a, deps=None):
    root, _ = st.run_root(a.root)
    out = []
    for d in st.list_runs(root):
        s = st.read_run_json(d) or {"legacy_v1": True}
        steps_state = s.get("steps") or {}
        cur = None
        for sid, v in steps_state.items():
            if v.get("state") in ("running", "blocked"):
                cur = sid
        status = "done" if st.is_finished(d) else (s.get("status") or "active")
        if status == "stopped" and "budget" in str(s.get("stopped_reason") or ""):
            status = "stopped (budget)"
        out.append({"run": textio.to_posix(d), "topic": s.get("topic"), "mode": s.get("mode"),
                    "status": status, "step": cur,
                    "created_at": s.get("created_at")})
    return {"ub": ENGINE_VERSION, "root": textio.to_posix(root), "runs": out}


RUN_NAME = re.compile(r"^\d{4}-\d{2}-\d{2}-\S+$")  # a run folder's name (<date>-<slug>, state.new_run_dir)
PATH_START = re.compile(r"^(?:[A-Za-z]:[\\/]|[\\/]|~(?:[\\/]|$)|\.{1,2}(?:[\\/]|$))")  # a drive, /, ~, ./ or ../


def after_word(text):
    """The text after its first word, as typed: parse_text joins the words with single spaces, which a path with two
    spaces in a row does not survive."""
    parts = (text or "").strip().split(None, 1)
    return parts[1].strip() if len(parts) > 1 else ""


def run_ref(text, root=None):
    """The run folder `text` (the text after a command word) names (#82): '' for no text, the folder when the text is
    an existing run folder (a path, or a run's name under the run root), else None: the text is a topic. Text that
    can only mean a run folder (a path, a word with a slash, or a run folder's name) and names none raises 'run folder
    not found', so a mistyped run is never started as a topic ("stop C:/runs/2026-09-27-x")."""
    text = (text or "").strip()
    if not text:
        return ""
    under = st.run_root(root)[0]
    for form in (text, " ".join(text.split())):
        for cand in (form, os.path.join(under, form)):
            path = os.path.abspath(os.path.expanduser(cand))
            if any(os.path.exists(os.path.join(path, name)) for name in (st.RUN_FILE, st.RUN_MD)):
                return path
    slash = re.search(r"[\\/]", text)
    if PATH_START.match(text) or (slash and not re.search(r"\s", text)) or RUN_NAME.match(
            re.split(r"[\\/]", text.rstrip("\\/"))[-1]):
        where = text if slash or text.startswith("~") else os.path.join(under, text)
        raise EngineError("run folder not found: %s" % textio.to_posix(os.path.abspath(os.path.expanduser(where))),
                          fix=["ub list --json"])
    return None


def cmd_run(a, deps=None):
    """Terminal mode: `ub run "<topic>"` (or --text / --text-file) starts a run, `ub run --continue [RUN]` resumes one;
    either way the run is driven here, asking the gates on stdin. The command words of 4.11 work here too (#82):
    `ub run continue [RUN]` is `--continue`, and `ub run status|stop|doctor [RUN]` run those commands, but only when
    nothing follows the word or what follows is an existing run folder; a path or a run folder's name that names no
    run is BLOCKED 'run folder not found'; any other text after the word starts the topic ("stop smoking coach for
    nurses")."""
    from ublib.engine import terminal
    deps = deps or make_deps()
    topic = " ".join(a.topic or []).strip()
    if topic and a.cont is not None:
        raise UsageError("--continue takes a run folder, not a topic")
    if topic and (a.text or a.text_file):
        raise UsageError("give the topic once: as words, with --text or with --text-file")
    text = topic or a.text or (kickoff_text(a) if a.text_file else "")
    parsed = parse_text(text)
    ref = run_ref(after_word(text), a.root) if parsed["command"] and a.cont is None else None
    if ref is not None:
        rest = ref or None
        if parsed["command"] == "status":
            return cmd_status(argparse.Namespace(run=rest, json=a.json, root=a.root), deps)
        if parsed["command"] == "doctor":
            return cmd_doctor(argparse.Namespace(live=False, json=a.json), deps)
        if parsed["command"] == "stop":
            return cmd_stop(argparse.Namespace(run=rest, json=a.json, root=a.root), deps)
        a.cont, topic, a.text = rest or "", "", ""  # continue
    a.text = a.text or topic
    if a.cont is not None or not (a.text or a.text_file):
        run_dir, _ = open_run(a.cont or None, a.root)
        steps = pipeline.load_steps()

        def go(ctx, lock):
            if ctx.host_agent != "terminal":
                reseat_for_host(ctx, "terminal")
            else:
                pipeline.redetect_auth(ctx)  # log in again, then run --continue: the family is used again
            st.save(run_dir, ctx.state)
            ctx.state.setdefault("exec", {})["wait_s"] = terminal.TERMINAL_WAIT_S
            return terminal.run_loop(ctx, steps, lock)
        # an explicit resume, like `continue`: it takes over a host task another session holds, so the terminal skips
        # it (or reports a HOST_BATCH) at once instead of waiting for that session's lease to expire
        return with_run(run_dir, deps, go, host="terminal", resume=True, takeover=True)
    a.host = "terminal"
    return cmd_init(a, deps, terminal=True)


# ================================================================ argument parsing

def add_init_options(p):
    p.add_argument("--host", default=None)
    g = p.add_mutually_exclusive_group()
    g.add_argument("--text", default="")
    g.add_argument("--text-file", dest="text_file", default=None)  # the kickoff text from a file: no shell quoting
    p.add_argument("--components", nargs="?", const="", default="")  # bare flag = none (PS 5.1 drops an empty "")
    p.add_argument("--root", default=None)
    p.add_argument("--lang", default=None)
    p.add_argument("--mode", default=None)
    p.add_argument("--variant", default=None)
    p.add_argument("--autopilot", default=None)
    p.add_argument("--families", default="auto")
    p.add_argument("--privacy", default=None, choices=["default", "private"])
    p.add_argument("--seeds-file", dest="seeds_file", default=None)
    p.add_argument("--idea-file", dest="idea_file", default=None)
    p.add_argument("--no-preflight", dest="no_preflight", action="store_true")


def build_parser():
    p = Parser(prog="ub.py", add_help=True, description="ultimate-brainstorm engine")
    p.add_argument("--version", action="store_true")
    sub = p.add_subparsers(dest="cmd")

    def sp(name):
        q = sub.add_parser(name)
        q.add_argument("--json", action="store_true")
        return q
    q = sp("init")
    add_init_options(q)
    q = sp("next")
    q.add_argument("run", nargs="?")
    q.add_argument("--wait-s", dest="wait_s", type=int, default=None)
    q.add_argument("--lease", default=None)
    q = sp("answer")
    q.add_argument("run")
    q.add_argument("gate")
    g = q.add_mutually_exclusive_group()
    g.add_argument("--file")
    g.add_argument("--choice")
    g.add_argument("--default", action="store_true")
    g.add_argument("--skip", action="store_true")
    q.add_argument("--lease", default=None)
    q = sp("done")
    q.add_argument("run")
    q.add_argument("step")
    q.add_argument("--lease", default=None)
    q = sp("continue")
    q.add_argument("run", nargs="?")
    q.add_argument("--host", default=None)
    q.add_argument("--root", default=None)
    q = sp("status")
    q.add_argument("run", nargs="?")
    q.add_argument("--root", default=None)
    q = sp("plan")
    q.add_argument("run", nargs="?")
    q.add_argument("--mode")
    q.add_argument("--variant")
    q.add_argument("--families")
    q = sp("run")
    add_init_options(q)
    q.add_argument("--continue", dest="cont", nargs="?", const="", default=None)
    q.add_argument("topic", nargs="*", default=[])  # `ub run "<topic>"`, the documented terminal start
    q = sp("stop")
    q.add_argument("run", nargs="?")
    q.add_argument("--root", default=None)
    q = sp("budget")
    q.add_argument("run")
    q.add_argument("--max-calls", dest="max_calls", type=int, required=True)
    q.add_argument("--lease", default=None)
    q = sp("redo")
    q.add_argument("run")
    q.add_argument("step")
    q.add_argument("--yes", action="store_true")
    q = sp("switch")
    q.add_argument("run")
    q.add_argument("--arch")
    q.add_argument("--idea")
    q.add_argument("--yes", action="store_true")
    q = sp("probe-result")
    q.add_argument("run")
    q.add_argument("result")
    q.add_argument("--note-file", dest="note_file")
    q = sp("import")
    q.add_argument("file")
    q.add_argument("run", nargs="?")
    q = sp("attach-s1")
    q.add_argument("run")
    q.add_argument("--doc", required=True)
    q.add_argument("--raw")
    q = sp("render")
    q.add_argument("run")
    q.add_argument("--zip", action="store_true")
    q = sp("export")
    q.add_argument("run")
    q.add_argument("--format", required=True, choices=["docx", "html"])
    q = sp("doctor")
    q.add_argument("--live", action="store_true")
    q = sp("config")
    q.add_argument("action", choices=["get", "set"])
    q.add_argument("key")
    q.add_argument("value", nargs="?")
    q = sp("list")
    q.add_argument("--root", default=None)
    return p


COMMANDS = {"init": cmd_init, "next": cmd_next, "answer": cmd_answer, "done": cmd_done, "continue": cmd_continue,
            "status": cmd_status, "plan": cmd_plan, "run": cmd_run, "stop": cmd_stop, "budget": cmd_budget,
            "redo": cmd_redo,
            "switch": cmd_switch, "probe-result": cmd_probe_result, "import": cmd_import, "attach-s1": cmd_attach_s1,
            "render": cmd_render, "export": cmd_export, "doctor": cmd_doctor, "config": cmd_config, "list": cmd_list}


def main(argv=None, deps=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    as_json = "--json" in argv
    try:
        args = build_parser().parse_args(argv)
    except UsageError as e:
        sys.stderr.write("usage error: %s\n" % e)
        return 2
    except SystemExit as e:  # --help
        return int(e.code or 0)
    if args.version:
        sys.stdout.write("ub.py %s\n" % ENGINE_VERSION)
        return 0
    if not args.cmd:
        sys.stderr.write(__doc__)
        return 2
    args.argv = argv
    try:
        result = COMMANDS[args.cmd](args, deps)
    except UsageError as e:
        sys.stderr.write("usage error: %s\n" % e)
        return 2
    except EngineError as e:
        emit(cards.blocked(None, e.say or str(e), fix=e.fix, error=str(e)), as_json)
        return 0
    except Exception as e:  # internal error: still print a BLOCKED card when possible
        sys.stderr.write(traceback.format_exc())
        try:
            emit(cards.blocked(None, "internal error: %s" % e, fix=["ub doctor --json"], error=repr(e)), as_json)
        except Exception:
            pass
        return 1
    emit(result, as_json)
    return 0


if __name__ == "__main__":
    sys.exit(main())
