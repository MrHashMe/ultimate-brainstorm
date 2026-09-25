# Pipeline: stages, gates, cards and resume (ultimate-brainstorm v2)

This file replaces v1 `stages.md`. The engine (`scripts/ub.py`) runs every step below; the host agent only follows
cards. Read this when the user asks what happens next, why a gate exists, or how to resume, redo or switch.

Conventions: `RUN` = `<project>/brainstorm/<YYYY-MM-DD>-<slug>/` (the run folder). S = script step (engine or
`bs.py`), D = dispatch (model jobs run by background workers), H = HUMAN gate, T = HOST task in the main conversation.

## 1. Modes

| Mode | Replies (guided) | Wall time | Model calls (3 families) | Contents |
|---|---|---|---|---|
| quick | 3-4 | 30-50 min | 25-40 | G0 brief (5 ideas, 3 criteria, 1 hard constraint) -> one generation pass on 2 families -> QUICK-CURATE -> quick-pick -> both-order judging by the other families -> gut pick -> decide -> QUICK-PROBE -> architecture lite -> proposal lite -> sign-off. Stamped "Novelty NOT checked" |
| standard | 6-7 | 3-5 h, mostly unattended | 75-110 | Stages 0-14 in full |
| deep | 10-14 | 6-10 h | 180-350 | Standard plus BMAD seeds, ce-ideate go deep, S3 x100, LENS L1-L6, dupcheck, 2 gap rounds, per-pair judging (6 or fewer finalists), rebuttal, forge, 10-day probe, 4 architecture candidates, 4 review lenses, PR/FAQ, G10 and G12 |
| proposal | 4-5 | 1.5-2.5 h | 35-55 | The user's idea: frame -> ground -> the idea as I-001 (primary) + 2 contrast variants -> checks -> cards -> tournament -> red-team all 3 -> decide (default = the user's idea) -> probe -> Stages 12-14 |

All numbers are estimates; `ub plan` recomputes them for the families actually available. Budget caps (`max_calls`):
quick 60, standard 180, deep 600, proposal 90. The GB gate asks before the cap is exceeded.

Invocation text is parsed deterministically. Leading tokens, in any order: mode (`quick`, `standard`, `deep`,
`proposal`), variant (`software`, `product`, `growth`, `research`, `marketing`, `creative`, `naming`, `general`),
autopilot (`guided`, `full-auto`, `hands-on`), options (`private`, `with-ce-ideate`), commands (`continue`, `status`,
`doctor`, `stop`). The rest is the topic (proposal mode: the idea). Without a variant token the engine infers one from
keywords and shows it on the kickoff card.

## 2. Autopilot presets

| Gate or step | hands-on | guided (default) | full-auto |
|---|---|---|---|
| G0 kickoff (plan, cost, vendors, privacy, seeds inline) | ask | ask (the same reply can carry seeds) | only if privacy defaults are unset in config |
| G1 seeds | ask (file, 10 min) | inline in G0, optional | skipped (recorded) |
| Frame | grilling up to 3 rounds (+ domain-modeling in software/growth) or express, then G2c | grilling 1 round if installed, otherwise express G2 | FRAME-DRAFT (every item ASSUMED) |
| G3 round 2 | ask | no (map shown in PROGRESS.md) | no |
| G4 rescues, G5 K4 | ask | auto: K4 candidates are PARKED, never killed; flags shown at G8a/G8b | auto-park |
| G6, G7 | ask | auto (6 finalists rule; top 3 + gut #1) | auto |
| G8a gut pick | before any judge runs | while judges run sealed | skipped |
| G8b decide | ask | ask (`ok` accepts the suggestion) | rule default, stamped AUTO-DECISION |
| G9 probe | wait for the result | designed; result later via `probe-result` | designed only |
| G10 drivers | ask | auto (ASSUMED tags) | auto |
| G11 architecture | ask | ask | leader, AUTO-DECISION |
| G12 ADRs | one by one | bundled into G13 | stay `proposed` |
| G13 sign-off | ask | ask | DRAFT + "AUTOPILOT DRAFT: no human decisions were made" |
| G14 handoff | ask | ask (offer) | skipped |
| S1 engine | ce-ideate if installed | S1F (say `with-ce-ideate` to use ce-ideate) | S1F |

Rule default for G8b (full-auto) and the guided suggestion: among the red-teamed ideas, the most BACK + BACK IF
verdicts, then the higher debiased tournament %, then the gut pick #1. The card calls it "Suggested by rule; you
decide". GX (stop the whole effort?) always asks, even in full-auto.

## 3. Stages 0-11

| ID | Type | When | What | Outputs |
|---|---|---|---|---|
| 0.1 | S | always | init: run folder, detect families, preflight PING, seats, plan estimate | run.json, 00_RUN.md, PROGRESS.md |
| 0.2 | H | always | G0 kickoff | answers/G0.json |
| 0.3 | S | always | apply G0; seeds in v1 format; recompute seats | 00_HUMAN_SEEDS.md |
| 1.1 | H | hands-on, no seeds in G0 | G1: the user writes the seeds file alone | - |
| 1.2 | T | deep + bmad installed | host/BMAD-SEEDS | seeds import |
| 2.0 | S | software/growth in a repo | CONTEXT snapshot + git baseline | CONTEXT.before.md |
| 2.1g | T | grilling installed, not terminal, not full-auto, not quick | host/FRAME-GRILL (software/growth with domain-modeling: FRAME-GRILL-DOCS) | 01_FRAME.md, criteria.json (+ CONTEXT.proposed.md) |
| 2.1q / 2.1a / 2.1w | D / H / D | express path | FRAME-QUESTIONS -> G2 answers -> FRAME-FINAL | frame/*.json, 01_FRAME.md, criteria.json |
| 2.1f | D | full-auto | FRAME-DRAFT | 01_FRAME.md, criteria.json |
| 2.1k | S | quick | mini frame from the G0 brief | 01_FRAME.md, criteria.json |
| 2.2 | S | always | lint-frame; criteria normalization; footprint check -> G2f if repo files changed | frame/lint.json |
| 2.3 | H | hands-on | G2c confirm | - |
| 3.1 | D | not quick | P-GROUND (web unless privacy says no) | 02_CONTEXT.md |
| 4.1c / 4.1f | T / D | S1 engine | host/S1-CE + `ub attach-s1`, or S1F | pool/S1_* |
| 4.2 | D | not quick | S2-VS, S3-EDE, S4-TRANSFER, S5-OPS (research: S5-RESEARCH); deep: LENS L1-L6; min 3 of 5 | pool/* |
| 4.3 | S | | pool/_families.json from seats + provisional | - |
| 5.1 | D | not quick | CURATOR (JSON) -> v1 merges.json + 03_POOL_NOTES.md | merges.json |
| 5.2 | S | | `bs.py map` (deep: dupcheck + second curator pass) | 03_POOL.md, coverage.json |
| 5.3 | D | homogenized or empty cells, rounds left | GAP (up to 6 cells) + REOPEN, then curator + map | pool/G*, pool/R* |
| 5.4 | H | hands-on | G3 round 2 | 00b_HUMAN_ROUND2.md |
| 6.1-6.3 | S/D/S | not quick | screen header, `bs.py prepare-screen`, judges (every idea, JSON), `bs.py screen` | 04_SHORTLIST.md |
| 6.4 | H | hands-on | G4 rescues and flags | - |
| 7.1 | D | not quick | CHECK per shortlisted, rescued and primary idea (checker family differs from the idea's origin) | checks/<ID>.md |
| 7.2 | S | | K4 candidates: hands-on -> G5; otherwise PARK | - |
| 8.1 / 8.2 | D | fewer than 6 survivors, or deep | EVOLVE + CHECK on each E idea; otherwise "skipped" | 05_EVOLVED.md |
| 9.1 | S | | finalists (at most 8; primary always) | - |
| 9.2 | D | | NORMALIZER cards | tournament/cards.md |
| 9.3 | S | | tournament header, `bs.py prepare-tournament` | prompts + maps |
| 9.4 | D | | judges x 2 orders (guided/quick/proposal: launched sealed during G8a) | *.out.json |
| 9.5 | H | not full-auto | G8a gut pick | tournament/precommit.md |
| 9.6 | S | | `bs.py tournament` | 06_TOURNAMENT.md |
| 10.1 | S | | top 3 by debiased % + gut #1 (hands-on: G7) | 07_TOP.md |
| 10.2 | D | | PRECOMMIT (before any review exists) | redteam/00_precommit.md |
| 10.3 | D | | REVIEWER: ADVOCATE and CRITIC from different families; deep: REBUTTAL | redteam/* |
| 10.4 | D | | SYNTHESIS (WHOLE-EFFORT line; STOP -> GX) | 07_REDTEAM.md |
| 10.5 | H | | G8b decide (raw verdict lines shown before the synthesis) | - |
| 10.6 | S | | decision in the user's words; LEDGER rows | 08_DECISION.md |
| 11.1 | D | | PROBE (ends `RESULT: PENDING`) | 09_PROBE.md |
| 11.2 | H | hands-on | G9 probe result | 09_PROBE.md result |

Quick mode replaces 2.1-10.6 with Q.2 QUICK-GEN (host family + one other family), Q.3 QUICK-CURATE, Q.4 `bs.py
quick-pick`, Q.5 tournament 9.3-9.6 with the non-host families judging both orders, Q.6 QUICK-PROBE, Q.7 G8b, Q.8
QUICK_DECISION.md. Proposal mode inserts P.1 (the idea becomes I-001, origin human, primary) and P.2 EVOLVE-CONTRAST
(E-01 simplification, E-02 different mechanism) after 3.1, then runs 7.1 on the 3 ideas, 9.2-9.6 and 10.2-10.6 with
the default choice I-001.

## 4. Stages 12-14

Stage 12 builds the architecture package (`10_ARCHITECTURE/`, see references/architecture.md): brief, drivers,
2-4 blind candidates, blind judging, the trade-off matrix, a pre-mortem, G11, the package, ADRs, risks, verified stack,
review lenses and one fix pass. Build type `approach` (research, marketing, creative, naming) writes approach.md
instead and has no G11.

Stage 13 writes the proposal (`11_PROPOSAL/`, see references/proposal.md): evidence packs, sections in three parallel
parts, the executive summary and one-pager, assembly with appendices, rubric and red-team review, one fix pass, the
HTML pack, and G13 sign-off.

Stage 14 hands off:

| ID | Type | What |
|---|---|---|
| 14.1 | T | software/growth with CONTEXT.proposed.md: host/CONTEXT-MERGE (per-term yes, per-ADR yes) |
| 14.2 | H | G14: publish copies (`10_ARCHITECTURE/` -> `docs/architecture/`, `adr/` -> `docs/adr/`, `11_PROPOSAL/` -> `docs/proposal/`), each with its own yes. A target holding another run's package or files the kit did not publish stays untouched: the copy goes to `docs/<run>/<item>/` and the card shows that target (and names the other run when one holds the folder). Re-publishing this run's own copy moves each file it replaces or no longer has to `_superseded/<stamp>/published/<item>/` (in a fixed folder last written by kit 2.0.2 or earlier, files its marker listed that the package lacks stay in place, and replacing such a file with other content is warned about). A link or junction on the way, or a taken `docs/<run>/<item>/`, means that item is not published; the card says why and what to move aside (then `redo <run> 14.2`). Without `RESULT: PASSED` the card warns "riskiest assumption untested" |
| 14.3 | S | the handoff seed: HANDOFF-CE (default for software/growth), HANDOFF-SPECKIT (greenfield), HANDOFF-SUPERPOWERS or HANDOFF-OPENSPEC (only when the repo already uses them); every seed ends "Do not reopen the choice of idea or architecture." |
| 14.4 | S | 12_HANDOFF.md, LEDGER update, DONE card with links |

## 5. The card protocol

Every `ub` command prints exactly one card (`--json`: one JSON object; also saved to `.ub/last_card.json`).

| type | Host action |
|---|---|
| AUTO | work is running; run `then` again (say nothing unless `say` names a new stage) |
| HUMAN | show `show` exactly; wait; write a NEW `answer_file` from `answer_template` with `reply` = the user's exact words; run `answer_cmd`. The same gate with `error` set means: ask the user that |
| HOST | read `task.template` (a file under templates/host/), do it in the main conversation, write the files in `task.writes`, run `task.done_cmd` |
| HOST_BATCH | one fresh sub-agent per job in `jobs` ("Read <prompt_file> and follow it exactly. Write only the requested output to <out>. Reply with one line."), then run `then` |
| DONE | show `show` and `links`; stop |
| BLOCKED | show `say` and every `fix` command; stop |

Answer rules: `--choice X`, `--default` and `--skip` are shell-safe shortcuts for letters, IDs and yes/no. Free text
always goes through the answer file, never through the command line. The engine validates the file and archives it
to `answers/<GATE>.json`.

Gates and their answer fields:

| Gate | When | Fields beyond `reply` |
|---|---|---|
| G0 kickoff | all modes | confirm, topic, mode, variant, autopilot, private, privacy{web,vendors,code}, families, with_ce_ideate, seeds{problem,primary,ideas,obvious,off_limits}, skip_seeds, quick{criteria,hard_constraint}, idea |
| G1 seeds | hands-on without seeds | done, skip |
| G2 / G2c / G2f | framing | answers[{q,a}], accept_defaults / confirm, corrections / restore |
| G3 round 2 | hands-on | ideas[], cells[] |
| G4 / G5 / G6 / G7 | hands-on | rescue[{id,reason}], confirm_flags[] / kill[], keep[] / finalists[] / picks[] |
| G8a gut pick | not full-auto | picks[] (up to 3, ordered), skip, notes |
| G8b decide | all | chosen, runner_up, bundle[] (growth), park[], why (the user's words), accept_recommendation |
| G9 probe | hands-on | result (PASSED, MISSED, INCONCLUSIVE), note |
| G10 drivers | hands-on, deep | confirm, corrections |
| G11 architecture | standard, deep, proposal | choice, steal[{from,element}], notes, accept_recommendation |
| G12 ADRs | hands-on, deep | accept[], reject[] |
| G13 sign-off | all | action (approve, changes, switch, runner-up), changes, switch_to |
| G14 handoff | all but full-auto | publish, merge_terms, terms[], handoff (ce, speckit, superpowers, openspec, none) |
| GB budget | cap reached | raise_to, stop |
| GX whole effort | frame kill condition or synthesis STOP | action (reframe, continue, stop) |

## 6. Execution model

`ub next RUN --wait-s W` takes the driver lock (`.ub/lock.json`, stale after 120 s), then loops for at most W seconds:
script steps run in-process or as a `bs.py` subprocess; dispatch steps build job files, launch pending jobs and
relaunch dead ones within the global concurrency (4), each family's limit and the call budget; HUMAN steps first
launch their `prelaunch` jobs (tournament judges during G8a) and then return the gate; when W runs out the engine
returns an AUTO card with progress.

- One detached worker per model call (`family.py job`), with a heartbeat. Workers outlive the `ub` call that started
  them, so a host command timeout never loses finished work.
- A job is done when its output exists, validates against its contract, and its `.meta.json` says `ok` with the
  SHA-256 of the current prompt. Anything else is re-run; finished work is never redone.
- A dead worker is relaunched up to 3 times per prompt; then the card is BLOCKED and offers the terminal route.
- Missing results go through the job's fallback family (`<family>-alt`), recorded as PROVISIONAL in run.json and the
  card notes. Still short of `min_ok`: BLOCKED with fixes.
- Terminal mode (`ub run`) uses the same loop with no time limit and asks the gates on stdin.

Host wait values: Claude Code W=540 (Bash timeout 600000), Kimi Code W=270 (Bash timeout 300000), Codex W=100
(timeout_ms 120000 where available), ZCode and others W=50.

## 7. Resume, redo, switch, import

- `continue` picks the newest run under `./brainstorm/` (fallback: `UB_HOME/runs.json`) without `12_HANDOFF.md` that is
  not signed off, and says which one it picked. `continue --host H` from another agent re-detects families; seats
  whose family disappeared are re-seated and recorded in `provisional` (hands-on asks first).
- `redo RUN STEP` moves the outputs of STEP and everything downstream to `_superseded/<ISO>/` (never deleted), clears
  the downstream gates and shows the cost preview first (asks unless `--yes`).
- `switch RUN --arch B` records G11 = B and redoes from 12.10; `switch RUN --idea I-014` records the new choice (and
  the switch in 08_DECISION.md) and redoes from 12.1.
- `probe-result RUN PASSED|MISSED|INCONCLUSIVE [--note-file F]` appends the result to 09_PROBE.md. MISSED = K6: the
  runner-up is proposed. INCONCLUSIVE is never a pass.
- `import FILE [RUN]` copies an existing idea list to `pool/IMPORT_<name>.md` and resumes at Stage 5.
- A v1 run folder (00_RUN.md without run.json) is migrated automatically (`legacy_v1: true`, families claude/gpt). A v1
  run that already has `10_HANDOFF.md` is offered "extend with architecture + proposal".

## 8. What each output file is

| File | Content |
|---|---|
| run.json | engine state: mode, variant, autopilot, privacy, families, seats, gates, steps, choice, budget |
| 00_RUN.md | human view with the v1 lines (v1 `bs.py status` still reads it) |
| PROGRESS.md | progress, ETA, families, calls, stage checklist; rewritten after every step |
| 00_HUMAN_SEEDS.md, 00b_HUMAN_ROUND2.md | the human's ideas (v1 format) |
| 01_FRAME.md, criteria.json | the frame (question-only) and weighted criteria |
| 02_CONTEXT.md | A FACTS (shown to generators), A2 domain terms, B LANDSCAPE (withheld from blind generators), C SEARCH BOUNDARY |
| pool/, pool/_families.json | raw generator outputs; prefix -> family map |
| merges.json, 03_POOL_NOTES.md, 03_POOL.md, clusters.json, origins.json, primary.json, coverage.json | curated pool, map, yield, coverage |
| screen/, 04_SHORTLIST.md | screen prompts and outputs; the shortlist with KILL/FAIL rows, flags, parked, `Rescued:` |
| checks/<ID>.md | prior-art verdict, steelman, claims, kill-assumptions |
| 05_EVOLVED.md | evolved ideas or "skipped" |
| tournament/, 06_TOURNAMENT.md | cards, judge prompts and outputs, result; pre-commit, raw and debiased standings, contested pairs, audits |
| 07_TOP.md, redteam/, 07_REDTEAM.md | red-team set, reviews, synthesis |
| 08_DECISION.md | the decision in the user's words, runner-up, parked, killed, not doing |
| 09_PROBE.md | the pre-registered riskiest-assumption test; `RESULT:` line |
| QUICK_DECISION.md, quick/ | quick mode decision and curation |
| 10_ARCHITECTURE/ | architecture package (references/architecture.md) |
| 11_PROPOSAL/ | proposal, one-pager, HTML pack (references/proposal.md) |
| 12_HANDOFF.md | what was handed to which tool, with paths |
| sources.json, sources.md | the S-### source registry |
| gates/, answers/ | exact gate texts shown; accepted answers |
| jobs/, prompts/, logs/, .ub/ | job specs, filled prompts, call logs, engine locks and markers |
| _superseded/ | outputs moved aside by redo and switch |
