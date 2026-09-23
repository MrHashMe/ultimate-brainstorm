"""Terminal mode `ub run` (KIT_SPEC 6.3): the same driver loop with no wait limit; HUMAN gates are asked on stdin.

`show` is printed, then the user types; an empty line ends the answer. The answer goes through the deterministic
reply parser of gates.py (letters, IDs, ok, go, skip, approve, changes: ...); the rest stays in `reply`.
When stdin is closed before any text arrives, the gate's default answer is used and recorded as `by: auto`.
HOST steps use their engine alternatives (they are excluded by the host_can_run_skills predicate); a HOST card that
still appears is skipped with a note. Families whose chain resolves to `host` were dropped at init.
"""

import sys
import time

from . import cards
from . import gates
from . import pipeline
from . import state as st

TERMINAL_WAIT_S = 3600
TERMINAL_POLL_S = 60  # the loop wakes at least this often to print progress, so a long stage never looks hung


def read_answer(stdin, stdout):
    """Lines until an empty line or EOF. Returns (text, eof_without_text)."""
    lines = []
    while True:
        try:
            stdout.write("> ")
            stdout.flush()
        except (OSError, ValueError):
            pass
        line = stdin.readline()
        if line == "":
            return "\n".join(lines).strip(), not lines
        line = line.rstrip("\r\n")
        if not line.strip():
            if lines:
                return "\n".join(lines).strip(), False
            continue
        lines.append(line)


def run_loop(ctx, steps, lock=None, stdin=None, stdout=None, wait_s=TERMINAL_WAIT_S, max_cards=10000):
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    poll = max(1, min(int(wait_s or 1), TERMINAL_POLL_S))
    card = pipeline.advance(ctx, steps, poll, lock)
    last_say = None
    last_line = None
    eof = False
    repeats = {}
    for _ in range(max_cards):
        t = card.get("type")
        if t == "AUTO":
            line = (card.get("progress") or {}).get("line") or ""
            if card.get("say") != last_say or line != last_line:
                if line:
                    _print(stdout, "[%s] %s" % (time.strftime("%H:%M"), line))
                if card.get("say") != last_say:
                    _print(stdout, card.get("say") or "")
                last_say, last_line = card.get("say"), line
            card = pipeline.advance(ctx, steps, poll, lock)
            continue
        if t == "HUMAN":
            gid = card.get("gate")
            repeats[gid] = repeats.get(gid, 0) + 1
            if card.get("error"):
                _print(stdout, "ERROR: %s" % card["error"])
            _print(stdout, card.get("show") or "")
            if eof:
                text, empty = "", True
            else:
                text, empty = read_answer(stdin, stdout)
                eof = empty
            if empty and not text:
                if repeats[gid] > 2:
                    return pipeline.finalize(ctx, steps, cards.blocked(
                        ctx, "No answer for %s on stdin (input closed)." % gid,
                        fix=['%s run --continue "%s"' % (cards.runner_of(ctx.state), ctx.run_dir)]))
                _print(stdout, "(no input: using the default answer)")
                card = pipeline.answer_gate(ctx, steps, gid, gates.default_answer(gid), lock, by="auto")
            else:
                card = pipeline.answer_gate(ctx, steps, gid, {"reply": text}, lock, by="human")
            continue
        if t == "HOST":
            sid = card.get("step")
            st.set_step(ctx.state, sid, "skipped", note="terminal mode: host task replaced by the engine path")
            st.add_note(ctx.state, "terminal mode skipped host task %s" % sid)
            st.save(ctx.run_dir, ctx.state)
            card = pipeline.advance(ctx, steps, wait_s, lock)
            continue
        if t == "HOST_BATCH":
            return pipeline.finalize(ctx, steps, cards.blocked(
                ctx, "A model family in this run can only be reached through an agent's sub-agents (HOST_BATCH), "
                     "which terminal mode cannot do.",
                fix=["continue this run inside your agent: <entry> continue"]))
        return card
    return card


def _print(stdout, text):
    if not text:
        return
    try:
        stdout.write(text.rstrip("\n") + "\n")
        stdout.flush()
    except (OSError, ValueError):
        pass
