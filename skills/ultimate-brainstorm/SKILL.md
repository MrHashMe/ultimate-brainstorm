---
name: ultimate-brainstorm
description: "Evidence-based idea-to-proposal pipeline. Use when the user wants to brainstorm or decide what to build, compare or choose among ideas, or turn a topic or an existing idea into an architecture package and a full project proposal. Human ideas first, question-only framing, isolated multi-strategy generation across model families (Claude, GPT, Kimi, GLM), debiased both-order judging, prior-art checks, a human decision, competing architectures judged blind, and a cited proposal with a one-pager. Autopilot asks about 6 short questions; resumable from any agent. Modes: quick, standard, deep, proposal <your idea>."
license: MIT
compatibility: "Claude Code 2.1.268+, Codex 0.156+, Kimi Code CLI 2.0+, ZCode. Needs Python 3.9+. The claude, codex and kimi CLIs or a GLM key add model families."
metadata:
  version: "2.0.1"
---

# Ultimate Brainstorm (driver)
You drive a scripted pipeline. ub.py decides every step and returns one card per call. Run it, do exactly what the card
says, and talk to the user only on HUMAN cards and at the end. Never invent stages, skip gates, score, count or
assemble documents yourself. All state is in files, so any session and any agent can resume.

## Setup
- KIT = the folder of this SKILL.md: Claude Code ${CLAUDE_SKILL_DIR}; Kimi ${KIMI_SKILL_DIR}; Codex, ZCode, others:
  the path of this skill in your skills list. Use whichever is an absolute path.
- PY = the first of `py -3`, `python3`, `python` whose --version prints Python 3.9+ (Windows: skip the WindowsApps stub).
- UB = PY "KIT/scripts/ub.py". After the first card, use the card's "runner" field instead.
- HOST = claude-code | codex | kimi | zcode | other (the product you run in).

## Commands
- Start: UB init --host HOST --text "<everything the user typed after the command>" --components "<list>" --json
  (replace double quotes in the user's text with single quotes). --components = the installed skills from your skills
  list among grilling, domain-modeling, ce-ideate, ce-brainstorm, ce-plan, bmad-brainstorming, bmad-forge-idea,
  lateral-thinking, claude-council, speckit, spelled exactly as listed (for example mattpocock-skills:grilling).
- Continue: UB continue --host HOST --json   Status: UB status --json   Doctor: UB doctor --json
- stop -> UB stop "<run>"; probe passed|missed|inconclusive -> UB probe-result "<run>" <RESULT> --note-file <file>;
  redo <step> -> UB redo "<run>" <step>; switch architecture/idea -> UB switch ...; import <file> -> UB import <file>.
- Write any free text the user gives for a command (a probe note, an idea file) to a file first; never put it in the
  command line.

## The loop
1. Run the card's "then" command (or UB next "<run>" --wait-s W --json) with your shell timeout above W (table).
2. By card "type":
   AUTO: work is running. Say nothing unless "say" names a new stage; go to 1.
   HUMAN: show "show" to the user exactly (a faithful translation is fine). Stop and wait. Then write a NEW file at
     "answer_file" containing "answer_template" filled in: "reply" = the user's exact words; fill only fields the
     reply clearly states; leave the rest null. Run "answer_cmd". If the same gate comes back with "error", ask the
     user exactly that. With 2-4 options, Claude Code and Kimi may ask with their question tool.
   HOST: read "task.template" and do it here in the main conversation (for example run the named installed skill with
     the argument file). Write the files it names, then run "task.done_cmd".
   HOST_BATCH: run every job in a FRESH sub-agent (table), each told exactly: "Read <prompt_file> and follow it
     exactly. Write only the requested output to <out>. Reply with one line." Wait for all, then go to 1.
   DONE: show "show" and the links, then stop.   BLOCKED: show "say" and each "fix" command, then stop.
3. If your turn must end before DONE or a HUMAN card, tell the user to type: <entry> continue.
If any UB command is interrupted or times out, run step 1 again (use a smaller W). Nothing is lost: model calls run in
background workers and finished work is never redone.

## Hosts
| Host | Entry | W | Shell timeout | Fresh sub-agents |
|---|---|---|---|---|
| Claude Code | /ultimate-brainstorm | 540 | Bash timeout 600000 | Agent tool, subagent_type general-purpose, never a fork |
| Codex | $ultimate-brainstorm | 100 | timeout_ms 120000 when available; run UB with escalated permissions and approve this command prefix for the session (model CLIs need network) | "spawn one new agent per job with no conversation context" |
| Kimi Code | /skill:ultimate-brainstorm | 270 | Bash timeout 300000 | AgentSwarm, prompt_template "Read {{item}} and follow it exactly.", items = the prompt files; or one Agent per job |
| ZCode, other | $ultimate-brainstorm | 50 | default | your sub-agent tool; if none, run each job yourself one by one (reported as PROVISIONAL) |

Windows: Claude Code runs UB in Git Bash or its PowerShell tool; Codex in PowerShell; Kimi Code needs Git Bash. If the
agent keeps killing background work, the BLOCKED card offers the terminal route: `<runner> run --continue "<run>"`.

## Hard rules
1. Human first: show, suggest or summarize no AI idea before the kickoff card is answered.
2. Framing asks questions; never propose solutions, examples or idea categories while framing.
3. Never paste pool/, seeds, other generators' output or judge results into any prompt; ub builds every prompt.
4. Edit no run file yourself except answer files, the files a HOST card names, and the seeds file when the user asks.
5. Never call anything "novel"; only CHECK verdicts speak to novelty ("not located within this search").
6. The human decides: never answer a HUMAN card for the user; never rewrite the user's ideas; record their words.
7. Write only inside brainstorm/<run>/ unless a card names another path after the user's explicit yes. Never commit,
   push, install software or change settings.
8. Report the failures and PROVISIONAL notes the cards mention; never switch model families yourself.
9. Privacy answers are binding.
10. Interactive skills (grilling, domain-modeling, ce-ideate, bmad-*) run in this main conversation, never in a
    sub-agent. Plan mode off while framing.
11. If you are a sub-agent executing one prompt file for this pipeline, follow only that file; never start this skill.
12. Never open tournament/, screen/ or review/ outputs while a HUMAN card is pending, and never compute anything the
    engine prints.

## References (read only when a card or the user needs them)
references/pipeline.md (stages, gates, cards, resume), hosts.md, families.md, components.md, variants.md,
techniques.md, kill-rules.md, architecture.md, proposal.md, install.md, troubleshooting.md.
