"""Cards (KIT_SPEC 4.12): one JSON object per engine call, AUTO | HUMAN | HOST | HOST_BATCH | DONE | BLOCKED.

Every card carries the same keys; unused ones are null. The engine prints the card with --json and writes it to
.ub/last_card.json. render_text() gives the plain-text form for humans (terminal and no --json).
"""

import os
import re
import sys

from .. import textio
from . import ENGINE_VERSION, STAGE_NAMES, UB_PY
from . import state as st

CARD_TYPES = ("AUTO", "HUMAN", "HOST", "HOST_BATCH", "DONE", "BLOCKED")

# What bash and PowerShell (the shells hosts run card commands in, 6.13) change inside a double-quoted argument: a
# double quote (PowerShell also ends the string at U+201C, U+201D and U+201E), a backtick, a line break, and a $ that
# can start a name or an expression (a $ before / or at the end stays: //srv/c$/)
_CHANGED_IN_QUOTES = re.compile('["`\r\n\u201c\u201d\u201e]|\\$(?!/|$)')


def unquotable(path):
    """The first character of `path`, written as the cards write it (forward slashes, in double quotes), that bash or
    PowerShell would change, or None. A run folder or kit folder holding one breaks every card command (4.11)."""
    m = _CHANGED_IN_QUOTES.search(textio.to_posix(path))
    return m.group(0)[0] if m else None


def default_runner():
    return '%s "%s"' % (python_launcher(), textio.to_posix(UB_PY))


def python_launcher():
    """A launcher string that works in every shell: 'py -3' (Windows), 'python3' or 'python'; else the quoted
    interpreter path. The WindowsApps store stub is skipped."""
    from ..proc import which  # never the current folder (a planted py.exe there must not be suggested)
    if os.name == "nt":
        py = which("py")
        if py and "windowsapps" not in py.lower():
            return "py -3"
    for name in ("python3", "python"):
        p = which(name)
        if p and "windowsapps" not in p.lower():
            return name
    return '"%s"' % textio.to_posix(sys.executable)


def runner_of(state):
    return (state or {}).get("runner") or default_runner()


def next_cmd(state, run_dir, wait_s=None, lease=None):
    w = wait_s if wait_s is not None else int(((state or {}).get("exec") or {}).get("wait_s", 540))
    return '%s next "%s" --wait-s %d%s --json' % (runner_of(state), textio.to_posix(run_dir), w,
                                                  (" --lease %s" % lease) if lease else "")


def with_lease(cmd, lease):
    """cmd with `--lease <token>` (before its trailing --json): the command of the session that holds the current
    step's lease (6.3). Unchanged without a lease or when it has one."""
    if not lease or not cmd or " --lease " in cmd:
        return cmd
    if cmd.endswith(" --json"):
        return "%s --lease %s --json" % (cmd[:-len(" --json")], lease)
    return "%s --lease %s" % (cmd, lease)


def base(ctx, ctype, step=None):
    s = ctx.state if ctx else {}
    run_dir = ctx.run_dir if ctx else None
    stage = int((step or {}).get("stage", 0)) if step else None
    card = {
        "ub": ENGINE_VERSION,
        "run": textio.to_posix(run_dir) if run_dir else None,
        "runner": runner_of(s),
        "type": ctype,
        "step": (step or {}).get("id"),
        "stage": stage,
        "gate": None,
        "say": "",
        "progress": None,
        "show": None,
        "show_file": None,
        "answer_file": None,
        "answer_template": None,
        "answer_cmd": None,
        "default_answer": None,
        "error": None,
        "task": None,
        "jobs": None,
        "then": next_cmd(s, run_dir) if run_dir else None,
        "next_wait_s": int((s.get("exec") or {}).get("wait_s", 540)) if s else None,
        "fix": [],
        "notes": list((s or {}).get("notes") or [])[-8:],
    }
    if s and st.single_family(s) and s.get("families"):
        card["notes"].append("PROVISIONAL: one model family only; cross-family seats are %s-alt substitutes"
                             % ((s.get("host") or {}).get("family") or "host"))
    if s and s.get("kit_version") and s.get("kit_version") != ENGINE_VERSION:
        card["notes"].append("this run was started by kit %s; the runner is %s" % (s.get("kit_version"),
                                                                                    ENGINE_VERSION))
    return card


def auto(ctx, step, say, progress=None, wait_s=None):
    c = base(ctx, "AUTO", step)
    c["say"] = say
    c["progress"] = progress
    if wait_s is not None:
        c["next_wait_s"] = wait_s
        c["then"] = next_cmd(ctx.state, ctx.run_dir, wait_s)
    return c


def human(ctx, step, gid, show, answer_template, default_answer, error=None, progress=None, say=None):
    from . import gates
    c = base(ctx, "HUMAN", step)
    c["gate"] = gid
    c["say"] = say or "Your turn: %s (%s)." % (gates.TITLES.get(gid, gid), gid)
    c["show"] = show
    c["show_file"] = textio.to_posix(ctx.path("gates", gid + ".md"))
    c["answer_file"] = textio.to_posix(ctx.path("answers", gid + ".json"))
    c["answer_template"] = answer_template
    c["default_answer"] = default_answer
    c["answer_cmd"] = '%s answer "%s" %s --file "%s" --json' % (runner_of(ctx.state), textio.to_posix(ctx.run_dir),
                                                               gid, c["answer_file"])
    c["error"] = error
    c["progress"] = progress
    c["then"] = None
    return c


def host(ctx, step, task, say, progress=None):
    c = base(ctx, "HOST", step)
    c["task"] = task
    c["say"] = say
    c["progress"] = progress
    c["then"] = None
    return c


def host_batch(ctx, step, jobs, say, progress=None, lease=None):
    c = base(ctx, "HOST_BATCH", step)
    c["jobs"] = jobs
    c["say"] = say
    c["progress"] = progress
    if lease:
        c["then"] = next_cmd(ctx.state, ctx.run_dir, lease=lease)  # the lease holder's poll reads the outputs
    return c


def done(ctx, show, links, progress=None, say="Done."):
    c = base(ctx, "DONE", None)
    c["say"] = say
    c["show"] = show
    c["links"] = links
    c["progress"] = progress
    c["then"] = None
    return c


def blocked(ctx, say, fix=None, error=None, step=None, progress=None):
    c = base(ctx, "BLOCKED", step) if ctx else base(None, "BLOCKED")
    c["say"] = say
    c["fix"] = list(fix or [])
    c["error"] = error or say
    c["progress"] = progress
    c["then"] = None
    return c


def render_text(card):
    """Plain-text form of a card (for terminals and callers without --json)."""
    t = card.get("type")
    lines = []
    prog = card.get("progress") or {}
    if prog.get("line"):
        lines.append(prog["line"])
    if t == "AUTO":
        lines.append(card.get("say") or "working...")
        if card.get("then"):
            lines.append("next: %s" % card["then"])
    elif t == "HUMAN":
        if card.get("error"):
            lines.append("ERROR: %s" % card["error"])
        lines.append(card.get("show") or "")
    elif t == "HOST":
        lines.append(card.get("say") or "")
        task = card.get("task") or {}
        lines.append("template: %s" % task.get("template"))
        lines.append("then run: %s" % task.get("done_cmd"))
    elif t == "HOST_BATCH":
        lines.append(card.get("say") or "")
        for j in card.get("jobs") or []:
            lines.append("- %s: read %s, write %s" % (j.get("id"), j.get("prompt_file"), j.get("out")))
        lines.append("then run: %s" % card.get("then"))
    elif t == "DONE":
        lines.append(card.get("show") or "Done.")
        for k, v in sorted((card.get("links") or {}).items()):
            if v:
                lines.append("%s: %s" % (k, v))
    elif t == "BLOCKED":
        lines.append("BLOCKED: %s" % (card.get("say") or card.get("error")))
        for f in card.get("fix") or []:
            lines.append("  fix: %s" % f)
    for n in card.get("notes") or []:
        lines.append("note: %s" % n)
    return "\n".join(x for x in lines if x is not None) + "\n"


def stage_title(stage):
    return STAGE_NAMES.get(int(stage or 0), "")
