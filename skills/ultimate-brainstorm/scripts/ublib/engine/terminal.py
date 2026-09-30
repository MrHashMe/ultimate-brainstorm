"""Terminal mode `ub run` (KIT_SPEC 6.3): the same driver loop with no wait limit; HUMAN gates are asked on stdin.

`show` is printed, then the user types; an empty line ends the answer. The answer goes through the deterministic
reply parser of gates.py (letters, IDs, ok, go, skip, approve, changes: ...); the rest stays in `reply`.
When stdin is closed before any text arrives, the gate's default answer is used and recorded as `by: auto`.
HOST steps use their engine alternatives (they are excluded by the host_can_run_skills predicate); a HOST card that
still appears is skipped with a note. Families whose chain resolves to `host` were dropped at init.

The driver lock is never held while a person thinks (I3): it is released before stdin is read, so another session
can answer or drive meanwhile. After the answer the lock is taken again and run.json re-read; the answer is applied
only when the same gate is still waiting and nothing else changed the run, otherwise the current card is shown.
"""

import sys
import time

from .. import textio
from . import cards
from . import gates
from . import pipeline
from . import state as st

TERMINAL_WAIT_S = 3600
TERMINAL_POLL_S = 60  # the loop wakes at least this often to print progress, so a long stage never looks hung
RELOCK_WAIT_S = 300   # after an answer, how long to wait for another session that drives the run meanwhile


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
    ctx.takeover = False  # `run --continue` takes over only the host work held when it started, never a later lease
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
            if card.get("error") and not card["error"].startswith(gates.READBACK_HEAD):  # the card shows the reading
                _print(stdout, "ERROR: %s" % card["error"])
            _print(stdout, card.get("show") or "")
            if eof:
                text, empty = "", True
            else:
                rev = ctx.state.get("rev")
                if lock is not None:
                    lock.release()
                text, empty = read_answer(stdin, stdout)
                eof = empty
                if lock is not None:
                    if not _relock(lock, stdout):
                        return cards.blocked(ctx, "Another session is still driving this run, so your answer for %s "
                                                  "was not applied." % gid, fix=['%s run --continue "%s"' % (
                                                      cards.runner_of(ctx.state), textio.to_posix(ctx.run_dir))])
                    ctx.state = st.load(ctx.run_dir)
                    ctx.cache.clear()
                    if pipeline.pending_gate(ctx, steps)[0] != gid or ctx.state.get("rev") != rev:
                        _print(stdout, "This run changed in another session while you were answering, so your "
                                       "answer was not applied. This is where the run is now:")
                        card = pipeline.advance(ctx, steps, poll, lock)
                        continue
            if empty and not text:
                # a G0 that asks about a `vendors: no` in the kickoff text, or shows again after a typed reply that
                # did not apply (it may hold a no), is never answered with the saved yes
                if repeats[gid] > 2 or gid == "G0" and (
                        repeats[gid] > 1 or (ctx.state.get("options") or {}).get("privacy_unread")):
                    return pipeline.finalize(ctx, steps, cards.blocked(
                        ctx, "No answer for %s on stdin (input closed)." % gid,
                        fix=['%s run --continue "%s"' % (cards.runner_of(ctx.state), textio.to_posix(ctx.run_dir))]))
                _print(stdout, "(no input: using the default answer)")
                card = pipeline.answer_gate(ctx, steps, gid, gates.default_answer(gid), lock, by="auto")
            else:
                card = pipeline.answer_gate(ctx, steps, gid, {"reply": text}, lock, by="human")
            continue
        if t == "HOST":
            lost = pipeline.lost_lock(ctx, steps, lock)
            if lost:
                return lost  # a kit 2.0.3 driver took the run over while this terminal stalled: nothing is saved
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


def _relock(lock, stdout):
    """Take the driver lock back after an answer; wait up to RELOCK_WAIT_S for a session that drives the run now. A kit
    2.0.3 driver that took the run through lock.json meanwhile (it knows no kernel lock) counts as driving (#79)."""
    if not lock.acquire():
        h = lock.holder()
        _print(stdout, "Another session is driving this run (pid %s, %s); waiting for it..." % (h.get("pid"),
                                                                                             h.get("host")))
        if not lock.acquire(RELOCK_WAIT_S):
            return False
    if lock.claim("terminal"):
        lock.release()
        return False
    return True


def _print(stdout, text):
    if not text:
        return
    try:
        stdout.write(text.rstrip("\n") + "\n")
        stdout.flush()
    except (OSError, ValueError):
        pass
