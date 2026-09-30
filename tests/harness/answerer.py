"""Drive `ub.py` like a host agent does (KIT_SPEC 4.11-4.13, 11.6 E3). Owner: B4.

    a = Answerer(env=th.env, cwd=th.project, choices={"G11": {"choice": "B", "accept_recommendation": False}})
    card = a.ub("init", "--host", "claude-code", "--text", "shift-swap app for nurses", "--json")
    final = a.drive(card)          # DONE, BLOCKED, or the card for which stop_at(card) returned True

Per card type:
    AUTO        run the card's `then` command (its --wait-s capped at `wait_s`)
    HUMAN       write a NEW answer file = answer_template filled from default_answer, then the scripted choice for
                that gate (a dict, or a callable(card) -> dict); run the answer command (`answer_cmd`). A card
                that reads the reply back ('I read your reply as: ...') is confirmed with only `reply` = yes
    HOST        write every path in task.writes from the fixture folder (by template name, then by basename; generic
                content otherwise) and run task.done_cmd
    HOST_BATCH  for each job: read jobs/<id>.json and its host prompt, call stubs.respond(job, prompt), write
                `out`; then run `then`
    DONE        stop            BLOCKED   stop (the caller asserts)

Commands printed by the engine start with the runner (for example `py -3 "C:/.../ub.py"`); the answerer keeps the
arguments after `ub.py` exactly and runs them with sys.executable and the kit's ub.py, so the command strings the
engine prints are what gets exercised.
"""

import json
import os
import re
import sys

import paths

HOST_FIXTURES = os.path.join(paths.FIX_E2E, "host")


class DriveError(AssertionError):
    pass


def tokenize(cmd):
    """Split a printed command line on whitespace, honoring double quotes; no escape processing."""
    out, cur, quoted, have = [], [], False, False
    for ch in cmd:
        if ch == '"':
            quoted = not quoted
            have = True
        elif ch.isspace() and not quoted:
            if have:
                out.append("".join(cur))
            cur, have = [], False
        else:
            cur.append(ch)
            have = True
    if have:
        out.append("".join(cur))
    return out


def ub_args(cmd, script="ub.py"):
    """The arguments after the ub.py (or `script`) token of a printed command."""
    toks = tokenize(cmd or "")
    names = set([script.lower(), "ub.py"])
    for i, t in enumerate(toks):
        if os.path.basename(t.replace("\\", "/")).lower() in names:
            return toks[i + 1:]
    # launcher form: `ub next ...` or `ub.cmd next ...`
    for i, t in enumerate(toks):
        base = os.path.basename(t.replace("\\", "/")).lower()
        if base in ("ub", "ub.cmd", "ub.ps1"):
            return toks[i + 1:]
    raise DriveError("cannot find ub.py in command %r" % cmd)


IDEA_ID = re.compile(r"\b(?:I-\d{3}|E-\d{2}|Q-\d{2})\b")
READBACK = "I read your reply as: "


def pick_non_leader(card):
    """For G8b: an idea ID shown on the card that is not the one on the 'Suggested' line."""
    show = card.get("show") or ""
    ids = []
    for m in IDEA_ID.finditer(show):
        if m.group(0) not in ids:
            ids.append(m.group(0))
    suggested = None
    for line in show.splitlines():
        if re.search(r"(?i)suggest|recommend", line):
            m = IDEA_ID.search(line)
            if m:
                suggested = m.group(0)
                break
    if suggested is None and ids:
        suggested = ids[0]
    others = [i for i in ids if i != suggested]
    return others[0] if others else suggested


class Answerer(object):
    def __init__(self, env, cwd, ub_py=None, wait_s=20, choices=None, host_fixtures=HOST_FIXTURES, timeout=1800,
                 max_cards=600, stop_at=None):
        self.env = env
        self.cwd = cwd
        self.ub_py = ub_py or paths.UB_PY
        self.wait_s = wait_s
        self.choices = dict(choices or {})
        self.host_fixtures = host_fixtures
        self.timeout = timeout
        self.max_cards = max_cards
        self.stop_at = stop_at
        self.trace = []
        self.answers = {}
        self.commands = []

    # ------------------------------------------------------------ process
    def ub(self, *args):
        argv = [sys.executable, self.ub_py] + [str(a) for a in args]
        self.commands.append([str(a) for a in args])
        proc = paths.run(argv, env=self.env, cwd=self.cwd, timeout=self.timeout)
        if proc.returncode != 0:
            raise DriveError("ub %s failed: %s" % (" ".join(str(a) for a in args[:3]), paths.describe(proc)))
        try:
            card = paths.last_json(proc.out)
        except ValueError:
            raise DriveError("ub %s printed no card: %s" % (args[:2], paths.describe(proc)))
        self.trace.append({"type": card.get("type"), "step": card.get("step"), "gate": card.get("gate"),
                           "say": card.get("say")})
        return card

    def run_printed(self, cmd):
        args = ub_args(cmd, os.path.basename(self.ub_py))
        if "--wait-s" in args:
            i = args.index("--wait-s")
            if i + 1 < len(args):
                try:
                    args[i + 1] = str(min(int(float(args[i + 1])), self.wait_s))
                except ValueError:
                    pass
        return self.ub(*args)

    # ------------------------------------------------------------ card handlers
    def answer_for(self, card):
        gate = card.get("gate")
        tmpl = card.get("answer_template") or {}
        answer = dict(tmpl) if isinstance(tmpl, dict) else {}
        default = card.get("default_answer") or {}
        if isinstance(default, dict):
            answer.update(default)
        choice = self.choices.get(gate)
        if callable(choice):
            choice = choice(card)
        if isinstance(choice, dict):
            answer.update(choice)
        if answer.get("reply") is None:
            answer["reply"] = ""
        return answer

    def on_human(self, card):
        path = card.get("answer_file")
        if not path:
            raise DriveError("HUMAN card without answer_file: %r" % card)
        readback = (card.get("error") or card.get("show") or "").startswith(READBACK)
        if card.get("error") and not readback:
            raise DriveError("gate %s rejected the answer: %s (answer was %r)" % (
                card.get("gate"), card.get("error"), self.answers.get(card.get("gate"))))
        if readback:  # the engine read the reply back (KIT_SPEC 4.12): confirm it with only `reply` filled
            answer = dict(card.get("answer_template") or {}, reply="yes")
        else:
            answer = self.answer_for(card)
            if os.path.exists(path):
                raise DriveError("stale answer file was not deleted by the engine: %s" % path)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            json.dump(answer, f, indent=1)
        self.answers[card.get("gate")] = answer
        if card.get("answer_cmd"):
            return self.run_printed(card["answer_cmd"])
        return self.ub("answer", card["run"], card["gate"], "--file", path, "--json")

    def _fixture_for(self, template, target):
        base = os.path.basename(target)
        name = os.path.splitext(os.path.basename(template or ""))[0]
        for cand in (os.path.join(self.host_fixtures, name, base), os.path.join(self.host_fixtures, base)):
            if os.path.isfile(cand):
                with open(cand, "r", encoding="utf-8") as f:
                    return f.read()
        return None

    def on_host(self, card):
        task = card.get("task") or {}
        for target in task.get("writes") or []:
            content = self._fixture_for(task.get("template"), target)
            if content is None:
                if target.endswith(".json"):
                    content = "{}\n"
                else:
                    content = "# Host step output\n\nWritten by the test answerer for %s.\n" % \
                              os.path.basename(target)
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with open(target, "w", encoding="utf-8", newline="\n") as f:
                f.write(content)
        if task.get("done_cmd"):
            return self.run_printed(task["done_cmd"])
        return self.ub("done", card["run"], card["step"], "--json")

    def on_host_batch(self, card):
        import stubs  # tests/harness/stubs.py, next to this file
        run = card["run"]
        for j in card.get("jobs") or []:
            job_path = os.path.join(run, "jobs", j["id"] + ".json")
            with open(job_path, "r", encoding="utf-8") as f:
                job = json.load(f)
            with open(j["prompt_file"], "r", encoding="utf-8") as f:
                prompt = f.read()
            text = stubs.respond(job, prompt)
            out = j["out"]
            os.makedirs(os.path.dirname(out), exist_ok=True)
            with open(out, "w", encoding="utf-8", newline="\n") as f:
                f.write(text)
        return self.run_printed(card["then"]) if card.get("then") else self.ub("next", run, "--wait-s",
                                                                                 self.wait_s, "--json")

    def step(self, card):
        t = card.get("type")
        if t == "AUTO":
            if card.get("then"):
                return self.run_printed(card["then"])
            return self.ub("next", card["run"], "--wait-s", self.wait_s, "--json")
        if t == "HUMAN":
            return self.on_human(card)
        if t == "HOST":
            return self.on_host(card)
        if t == "HOST_BATCH":
            return self.on_host_batch(card)
        raise DriveError("unknown card type %r" % t)

    def drive(self, card):
        for _ in range(self.max_cards):
            if card.get("type") in ("DONE", "BLOCKED"):
                return card
            if self.stop_at is not None and self.stop_at(card):
                return card
            card = self.step(card)
        raise DriveError("no DONE after %d cards; last: %r" % (self.max_cards, self.trace[-5:]))
