# Pipeline: stages, gates, cards and resume (ultimate-brainstorm v2)

The engine (`scripts/ub.py`) runs every step below; the host agent only follows cards. Read this when the user asks
what happens next, why a gate exists, or how to resume, redo or switch.

Conventions: `RUN` = `<project>/brainstorm/<YYYY-MM-DD>-<slug>/` (the run folder). S = script step (engine or
`bs.py`), D = dispatch (model jobs run by background workers), H = HUMAN gate, T = HOST task in the main conversation.

## 1. Modes

| Mode | Replies (guided) | Model time | Model calls, 3 families (4) | Contents |
|---|---|---|---|---|
| quick | 4-5 | 33-77 min | 16 (16) | G0 brief (5 ideas, 3 criteria, 1 hard constraint) -> one generation pass on 2 families -> QUICK-CURATE -> blind quick screen by both generating families and a third family -> quick-pick -> both-order judging by one other family -> gut pick (hands-on only) -> decide -> QUICK-PROBE -> architecture lite -> proposal lite -> sign-off. Stamped "Novelty NOT checked" |
| standard | 6-7 | 92-212 min, mostly unattended | 55-74 (56-75) | Stages 0-14 in full |
| deep | 6-9 | 130-299 min | 73-194 (78-227) | Standard plus BMAD seeds, ce-ideate go deep, S3 x100, LENS L1-L6, 2 gap rounds, per-pair judging (6 or fewer finalists), rebuttal, forge, 10-day probe, 4 architecture candidates, 4 review lenses, PR/FAQ, G10 and G12 |
| proposal | 5-6 | 77-176 min | 46-49 (47-50) | The user's idea: frame -> ground -> the idea as I-001 (primary) + 2 contrast variants -> checks -> cards -> tournament -> red-team all 3 -> decide (default = the user's idea) -> probe -> Stages 12-14 |

The numbers are the engine's own plan: `ub plan --mode M --variant general --families claude,gpt,kimi --json` (and
`claude,gpt,kimi,glm` in brackets), kit 2.1.0, no user configuration; tokens (3 families): quick 0.22-0.49M, standard
0.65-1.91M, deep 0.82-4.30M, proposal 0.55-1.35M. Model time counts the model calls only (4 at once); replies, host
skills and the probe come on top. `ub plan "<run>"` recomputes them for the families actually available, and the G0
card adds one preflight PING per family (plus one web probe for Codex).

Budget caps (`max_calls`, backend requests): quick 60, standard 180, deep 600, proposal 90. A call that succeeds the
first time is one request; retries, repair calls and HTTP retries count too (`ub plan` prints the worst case as
`requests.max`). The GB gate asks before a job could pass the cap; `ub budget "<run>" --max-calls N` raises it (a
full-auto run then goes on by itself).

Invocation text reaches the engine through a file (`ub init --text-file brainstorm/.kickoff.txt`, written by the host,
never through shell quoting) and is parsed deterministically. Leading tokens, in any order: mode (`quick`, `standard`,
`deep`, `proposal`), variant (`software`, `product`, `growth`, `research`, `marketing`, `creative`, `naming`,
`general`), autopilot (`guided`, `full-auto`, `hands-on`), options (`private`, `with-ce-ideate`), commands (`continue`,
`status`, `doctor`, `stop`). The rest is the topic (proposal mode: the idea). A command word counts only alone or
before a run folder (a mistyped one is BLOCKED "run folder not found"); before other text `init` is BLOCKED with the
hint to put a mode word first, and `ub run` starts that topic. Without a variant token the engine infers one from whole
words (KIT_SPEC 4.11), marked "(inferred; ...)" on the kickoff card.

## 2. Autopilot presets

| Gate or step | hands-on | guided (default) | full-auto |
|---|---|---|---|
| G0 kickoff (plan, cost, vendors, privacy, seeds inline) | ask | ask (the same reply can carry seeds) | only if no privacy defaults cover its vendors |
| G1 seeds | ask (file, 10 min) | inline in G0, optional | skipped (recorded) |
| Frame | grilling up to 3 rounds (+ domain-modeling in software/growth) or express, then G2c | grilling 1 round if installed, otherwise express G2 | FRAME-DRAFT (every item ASSUMED) |
| G3 round 2 | ask | no (map shown in PROGRESS.md) | no |
| G4 rescues, G5 K4 | ask | auto: K4 candidates are PARKED, never killed; flags shown at G8a/G8b | auto-park |
| G6, G7 | ask | auto (finalist cut; top 3 by the ranking + Condorcet winner + gut #1) | auto |
| G8a gut pick | before any judge runs | while judges run sealed (quick and proposal: skipped) | skipped |
| G8b decide | ask | ask (`ok` accepts the suggestion) | rule default, stamped AUTO-DECISION |
| G9 probe | wait for the result | designed; result later via `probe-result` | designed only |
| G10 drivers | ask | auto (ASSUMED tags) | auto |
| G11 architecture | ask (quick: as guided) | ask (quick: auto unless the leader is vetoed, self-judged or confounded) | leader, AUTO-DECISION |
| G12 ADRs | one by one | bundled into G13 | stay `proposed` |
| G13 sign-off | ask | ask | DRAFT + "AUTOPILOT DRAFT: no human decisions were made" |
| G14 handoff | ask | ask (offer) | skipped |
| S1 engine | ce-ideate if installed | S1F (say `with-ce-ideate` to use ce-ideate) | S1F |

Rule default for G8b (full-auto) and the guided suggestion: among the red-teamed ideas, the most BACK + BACK IF
verdicts, then the better tournament rank (raw points when the ranking fell back), then the gut pick #1. The card
calls it "Suggested by rule; you decide". GX (stop the whole effort?) always asks, even in full-auto. The G11 default
takes the matrix leader unless a judge vetoed it; then the best-ranked candidate without a veto, with the reason (a
self-judged or confounded leader is kept with a note).

## 3. Stages 0-11

| ID | Type | When | What | Outputs |
|---|---|---|---|---|
| 0.1 | S | always | init: run folder, detect families, preflight PING, seats, plan estimate | run.json, 00_RUN.md, PROGRESS.md |
| 0.2 | H | always | G0 kickoff | answers/G0.json |
| 0.3 | S | always | apply G0; the reply's seeds join the seeds file (v1 format; the user's own text stays); recompute seats | 00_HUMAN_SEEDS.md |
| 1.1 | H | hands-on, no seeds in G0 | G1: the user writes the seeds file alone (`skip` keeps what it holds) | - |
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
| 5.2 | S | | `bs.py map` | 03_POOL.md, ideas.json, coverage.json |
| 5.3 | D | coverage.json `gap_needed` (largest cluster above 25%, or under 80% of the axis cells covered), rounds left (standard 1, deep 2) | GAP (up to 6 cells) + REOPEN, then curator + map; a second round moves the first round's curator and job files to `_superseded/` first | pool/G*, pool/R* |
| 5.4 | H | hands-on | G3 round 2 | 00b_HUMAN_ROUND2.md |
| 6.1-6.3 | S/D/S | not quick | screen header, `bs.py prepare-screen`, judges (every idea, JSON), `bs.py screen` | 04_SHORTLIST.md |
| 6.4 | H | hands-on | G4 rescues and flags | - |
| 7.1 | D | not quick | CHECK per shortlisted, rescued and primary idea (checker family differs from the idea's origin) | checks/<ID>.md |
| 7.2 | S | | K4 candidates: hands-on -> G5; otherwise PARK | - |
| 8.1 / 8.2 | D | fewer than 6 survivors, or deep | EVOLVE + CHECK on each E idea; otherwise "skipped" | 05_EVOLVED.md |
| 9.1 | S | | finalists (at most 8: protected survivors, 2 evolved ideas by CHECK verdict, then screen score; primary always; a pool above 8 in hands-on -> G6) | - |
| 9.2 | D | | NORMALIZER cards | tournament/cards.md |
| 9.3 | S | | tournament header, `bs.py prepare-tournament` | prompts + maps |
| 9.4 | D | | judges x 2 orders (launched sealed while a guided G8a waits) | *.out.json |
| 9.5 | H | standard and deep: not full-auto; quick and proposal: hands-on only | G8a gut pick | tournament/precommit.md |
| 9.6 | S | | `bs.py tournament` | 06_TOURNAMENT.md |
| 10.1 | S | | top 3 by the tournament ranking + Condorcet winner + gut #1 (at most 4; hands-on: G7) | 07_TOP.md |
| 10.2 | D | | PRECOMMIT (before any review exists) | redteam/00_precommit.md |
| 10.3 | D | | REVIEWER: ADVOCATE and CRITIC from different families; deep: REBUTTAL | redteam/* |
| 10.4 | D | | SYNTHESIS (WHOLE-EFFORT line; STOP -> GX) | 07_REDTEAM.md |
| 10.5 | H | | G8b decide (raw verdict lines shown before the synthesis) | - |
| 10.6 | S | | decision in the user's words; LEDGER rows | 08_DECISION.md |
| 11.1 | D | | PROBE (ends `RESULT: PENDING`) | 09_PROBE.md |
| 11.2 | H | hands-on | G9 probe result | 09_PROBE.md result |

Quick mode replaces 2.1-10.6 with Q.2 QUICK-GEN (host family + one other family), Q.3 QUICK-CURATE (blind to the
model families; bs.py quick-pick derives each idea's origin from its aliases), Q.3p/Q.3s the blind quick screen (both
quick generator families, and with 3 or more families a third family that generated nothing, score the curated neutral
lines with the SCREEN-HEADER prompt; skipped with one family), Q.4
`bs.py quick-pick` (the finalists by the blind scores with the screen's own-origin correction; a one-family run keeps
the curator's scores, flagged), Q.5 tournament 9.3-9.6 with one non-host family (or `<host>-alt`) judging both
orders, Q.6 QUICK-PROBE, Q.7 G8b, Q.8 QUICK_DECISION.md.
Proposal mode inserts P.1 (the idea becomes I-001, origin human, primary) and P.2 EVOLVE-CONTRAST (E-01
simplification, E-02 different mechanism) after 3.1, then runs 7.1 on the 3 ideas, 9.2-9.6 and 10.2-10.6 with the
default choice I-001.

## 4. Stages 12-14

Stage 12 builds the architecture package (`10_ARCHITECTURE/`; references/architecture.md): brief, drivers,
2-4 blind candidates, blind judging, the trade-off matrix, a pre-mortem, G11, the package, ADRs, risks, verified stack,
review lenses and one fix pass. Build type `approach` (research, marketing, creative, naming) writes approach.md
instead and has no G11.

Stage 13 writes the proposal (`11_PROPOSAL/`, see references/proposal.md): evidence packs, sections in three parallel
parts, the executive summary and one-pager, assembly with appendices, rubric and red-team review, fix passes, the
HTML pack, and G13 sign-off.

Stage 14 hands off:

| ID | Type | What |
|---|---|---|
| 14.1 | T | software/growth with CONTEXT.proposed.md: host/CONTEXT-MERGE (per-term yes, per-ADR yes) |
| 14.2 | H | G14: publish copies, each with its own yes, into `docs/<run>/` in the run's layout (`architecture` -> `10_ARCHITECTURE/` with its `adr/`, `adr` -> `10_ARCHITECTURE/adr/`, `proposal` -> `11_PROPOSAL/` with the ADRs it links to), byte for byte, so every link resolves and runs never mix. Interrupted FILE-protocol writes there are finished first; journals and temp files are never published. A republish leaves unchanged files alone and moves each replaced file, and (when the answer covers every copy this run published) each file the run no longer has, to `_superseded/<stamp>/published/`. `handoff/published.json` records what was published; an interrupted publish just runs again. An item is not published when `docs/`, `docs/<run>/` or a folder of the copy is a link or junction (the card says what to move aside, then `redo <run> 14.2`). Kit 2.0.x copies (`docs/architecture`, `docs/adr`, ...) are left alone; the card names them. Without `RESULT: PASSED` the card warns "riskiest assumption untested" |
| 14.3 | S | the handoff seed: HANDOFF-CE (default for software/growth), HANDOFF-SPECKIT (greenfield), HANDOFF-SUPERPOWERS or HANDOFF-OPENSPEC (only when the repo already uses them); every seed ends "Do not reopen the choice of idea or architecture." (not for an idea K6 killed) |
| 14.4 | S | 12_HANDOFF.md, the LEDGER probe row (once, and only for the chosen idea's probe), DONE card with links |

## 5. The card protocol

Every `ub` command prints exactly one card (`--json`: one JSON object; also saved to `.ub/last_card.json`).

| type | Host action |
|---|---|
| AUTO | work is running; run `then` again (say nothing unless `say` names a new stage) |
| HUMAN | show `show` exactly; wait; write a NEW `answer_file` from `answer_template` with `reply` = the user's exact words; run `answer_cmd`. The same gate with `error` set: ask the user that (a read-back: fill only `reply`) |
| HOST | read `task.template` (a file under templates/host/), do it in the main conversation, write the files in `task.writes`, run `task.done_cmd` (it carries the task's `--lease`; a task that changed none of its files is recorded `skipped`) |
| HOST_BATCH | follow templates/host/HOST-BATCH.md (the one source of the sub-agent task text and the per-host tool): one fresh sub-agent per job in `jobs`, then run `then` (it carries the batch's `--lease`) |
| DONE | show `show` and `links`; stop |
| BLOCKED | show `say` and every `fix` command; stop |

Answer rules: `--choice X`, `--default` and `--skip` are shell-safe shortcuts for letters, IDs and yes/no; free text
goes only through the answer file. The engine type-checks the answer against the gate's fields: an unknown field is
refused (the error lists the fields), obvious slips are repaired with a card note (a comma list where a list of idea
IDs belongs, "yes"/"no" for a boolean), and IDs are checked against the run. A reply not in the card's words is read
back first: nothing is applied until the user says yes. `answers/<GATE>.json` records the applied answer; run.json
holds the one the engine uses.

Gates and their answer fields:

| Gate | When | Fields beyond `reply` |
|---|---|---|
| G0 kickoff | all modes | confirm, topic, mode, variant, autopilot, private, privacy{web,vendors,code}, families, with_ce_ideate, seeds{problem,primary,ideas,obvious,off_limits}, skip_seeds, quick{criteria,hard_constraint}, idea |
| G1 seeds | hands-on without seeds | done, skip |
| G2 / G2c / G2f | framing | answers[{q,a}], accept_defaults / confirm, corrections / restore |
| G3 round 2 | hands-on | ideas[], cells[] |
| G4 / G5 / G6 / G7 | hands-on | rescue[{id,reason}], confirm_flags[] / kill[], keep[] / finalists[] / picks[] |
| G8a gut pick | standard and deep, not full-auto; quick and proposal only in hands-on | picks[] (up to 3, ordered), skip, notes |
| G8b decide | all | chosen, runner_up, bundle[] (growth), park[], why (the user's words), accept_recommendation |
| G9 probe | hands-on | result (PASSED, MISSED, INCONCLUSIVE), note |
| G10 drivers | hands-on, deep | confirm, corrections |
| G11 architecture | standard, deep, proposal (quick: when contested, section 2) | choice, steal[{from,element}], notes, accept_recommendation |
| G12 ADRs | hands-on, deep | accept[], reject[] (the ADR numbers the card shows; accept may be all) |
| G13 sign-off | all | action (approve, changes, switch, runner-up), changes, switch_to |
| G14 handoff | all but full-auto | publish, merge_terms, terms[], handoff (ce, speckit, superpowers, openspec, none) |
| GB budget | the next job could pass the request cap | raise_to (requests), stop |
| GX whole effort | frame kill condition or synthesis STOP | action (reframe, continue, stop) |

## 6. Execution model

`ub next RUN --wait-s W` takes the run's driver lock (an OS lock on `.ub/jobs/_driver.lock`, freed when its process
ends; `.ub/lock.json` names the holder) before it reads run.json, then loops for at most W seconds: script steps run
in-process or as a `bs.py` subprocess; dispatch steps build job files (rebuilding jobs that have not run when their
inputs changed), launch pending jobs and relaunch dead ones within the global concurrency (4), each family's limit and
the request budget; HUMAN steps first launch their `prelaunch` jobs (tournament judges during G8a) and then return the
gate; when W runs out the engine returns an AUTO card with progress. If another process holds the lock, or a kit
2.0.x driver (also one waiting at a gate) holds `.ub/lock.json`, the card is AUTO "another session is driving this
run" and its `then` retries; nothing is written. A driver that stalled while a 2.0.3 driver took its record over
returns BLOCKED "another session took over this run; this one stopped without saving".

- One detached worker per model call (`family.py job`), holding the job's own OS lock. Workers outlive the `ub` call
  that started them, so a host command timeout never loses finished work.
- A job is done when its output exists and its `.meta.json` says `ok` for this job id, with the SHA-256 of the current
  prompt and of the output as it is now (the contract was checked when the output was written). Anything else is
  re-run; finished work is never redone.
- A dead worker is relaunched up to 3 times since the step started or was last retried; then the card is BLOCKED and
  offers the terminal route. A retry allows 3 more; after 6 relaunches for the same prompt the job is failed and its
  fallback runs.
- Budget: each launch needs its worst case (`adapter.request_reserve`: every backend of its chain x (retries + 1) x its
  requests per attempt, plus one repair call; KIT_SPEC 4.8) to fit under `max_calls` next to the requests already sent
  (the `requests` of `logs/calls.jsonl`). Otherwise GB (guided, hands-on) or a BLOCKED budget stop (full-auto).
- A family (not the host's) whose call fails authentication is unavailable until you log in again and run `continue`
  (any host) or `run --continue`, or retry the BLOCKED step (each detects it again); meanwhile its jobs go to the
  fallback.
- Missing results go through the job's fallback family (`<family>-alt`; a judge seat then tries the families that hold
  no judge seat in that step, then the host), recorded as PROVISIONAL in run.json and the card notes. Still short of
  `min_ok`: BLOCKED with fixes.
- HOST and HOST_BATCH work is leased to the session that got the card; another session's poll waits, `continue` and
  `run --continue` take it over. The session that holds a HOST_BATCH lease gets `--lease` in every AUTO `then` of that
  step, in the `answer_cmd` of a HUMAN card (GB) and in the `next`, `answer` and `budget` fix commands of a card it
  gets meanwhile; the lease ends as soon as every host job has its outcome. A holder that polls with `next` instead
  adds the `--lease` of its last `then` or `task.done_cmd` and gets its card back. `done` fsyncs a HOST task's files
  before it records the task (a file another program holds open: close it, run `done_cmd` again). A session whose
  task was taken over and accepted elsewhere, and that changed its files afterwards, gets a BLOCKED card for its
  `done`: check the files or redo the step.
- `ub stop RUN` creates `.ub/STOP`, kills the workers and records `status: stopped` (`stopped_reason: user`): a
  pause. No job is launched and no worker calls a model while STOP exists. Only `continue` and `run --continue` lift a
  `ub stop`; the agent's `next` returns the stopped card and launches nothing. A finished run has nothing to stop.
  Workers whose identity cannot be read are not killed; the stop card lists their pids.
- Terminal mode (`ub run`) runs the same loop with no time limit and asks the gates on stdin, releasing the driver
  lock while it waits; it applies an answer only if the run did not change meanwhile.

Host wait values: Claude Code W=540 (Bash timeout 600000), Kimi Code W=270 (Bash timeout 300000), Codex W=100
(timeout_ms 120000 where available), ZCode and others W=50.

## 7. Resume, redo, switch, import

- `continue` picks the newest run under `./brainstorm/` (fallback: `UB_HOME/runs.json`) without `12_HANDOFF.md` that is
  not signed off, and says which one it picked. `continue --host H` from another agent re-detects families; seats
  whose family disappeared are re-seated and recorded in `provisional` (hands-on asks first).
- `redo RUN STEP` moves the outputs of STEP and every later step of this run to `_superseded/<ISO>/` (never
  deleted), clears the downstream gates and shows the cost preview first (asks unless `--yes`). Steps of another mode
  and skipped steps move nothing, so an earlier step's files stay even when a later step of another mode names them
  (quick Q.3p's screen prompts, proposal P.1's idea files). The moves go through a journal in run.json: a file
  another program holds open leaves the redo pending (BLOCKED "A redo could not move <file> ..."), and no step runs
  until it is finished. A redo also drops what the redone steps own (parked and killed ideas,
  finalists, top, the choice and its decision log, the probe), and starts their relaunch counts over. The gap-round
  counters start over only when the redo runs 5.3 itself (a redo from 5.3c or later keeps every round's ideas, and
  the round it re-curates is counted once).
- `switch RUN --arch B` records G11 = B and redoes from 12.10; `switch RUN --idea I-014` (a finalist that is not the
  chosen idea or K6-killed) records the new choice and redoes from 11.1 (quick mode: Q.6), so the new idea gets its
  own probe. The switch line is kept in run.json `decision_log`, which every rewrite of 08_DECISION.md renders (quick
  Q.8 writes the file again).
- `probe-result RUN PASSED|MISSED|INCONCLUSIVE [--note-file F]` is accepted once the run is done and 09_PROBE.md
  exists; it records the result for the chosen idea. MISSED = K6: the idea is killed ("Killed: <idea> - K6" in
  08_DECISION.md, kept in `decision_log` like a switch) and the runner-up is chosen and probed; with no runner-up left
  (or only one its own probe killed) the documents and handoff seed are rendered again and the DONE card names the
  finalists to switch to. The same result again changes nothing. INCONCLUSIVE is never a pass.
- `budget RUN --max-calls N` sets the request cap; N must cover the requests sent plus the next launch's worst case. A
  run stopped at its cap is not finished: `continue` picks it, and it goes on once the cap no longer binds.
- `import FILE [RUN]` copies an existing idea list to `pool/IMPORT_<name>.md`; the pool is curated again from 5.1
  (quick: Q.3), superseding that step and later ones if they ran (the note says which). A proposal run (no pool)
  refuses the import.
- A v1 run folder (00_RUN.md without run.json) is migrated under the driver lock (`legacy_v1: true`, families
  claude/gpt; the original is kept as `00_RUN.v1.md`); read-only commands migrate in memory only. A v1 run that
  already has `10_HANDOFF.md` is offered "extend with architecture + proposal".

## 8. What each output file is

| File | Content |
|---|---|
| run.json | engine state: mode, variant, autopilot, privacy, families, seats, gates, steps, choice, budget; `rev` counts its writes |
| 00_RUN.md | human view with the v1 lines |
| PROGRESS.md | progress, ETA, families, calls, stage checklist; rewritten after every step |
| 00_HUMAN_SEEDS.md, 00b_HUMAN_ROUND2.md | the human's ideas (v1 format) |
| 01_FRAME.md, criteria.json | the frame (question-only) and weighted criteria |
| 02_CONTEXT.md | A FACTS (shown to generators), A2 domain terms, B LANDSCAPE (withheld from blind generators), C SEARCH BOUNDARY |
| pool/, pool/_families.json | raw generator outputs; prefix -> family map |
| merges.json, 03_POOL_NOTES.md, 03_POOL.md, clusters.json, origins.json, primary.json, ideas.json, coverage.json | curated pool, map, yield, coverage |
| screen/, 04_SHORTLIST.md | screen prompts and outputs; the shortlist with KILL/FAIL rows, flags, parked, `Rescued:` |
| checks/<ID>.md | prior-art verdict, steelman, claims, kill-assumptions |
| 05_EVOLVED.md | evolved ideas or "skipped" |
| tournament/, 06_TOURNAMENT.md | cards, judge prompts and outputs, result; pre-commit, raw standings and the debiased ranking, contested pairs, audits |
| 07_TOP.md, redteam/, 07_REDTEAM.md | red-team set, reviews, synthesis |
| 08_DECISION.md | the decision in the user's words, runner-up, parked, killed, not doing; then the switches and K6 kills since (run.json `decision_log`) |
| 09_PROBE.md | the pre-registered riskiest-assumption test; `RESULT:` line |
| QUICK_DECISION.md, quick/ | quick mode decision and curation; quick/screen.md: how the finalists were scored |
| 10_ARCHITECTURE/ | architecture package (references/architecture.md) |
| 11_PROPOSAL/ | proposal, one-pager, HTML pack (references/proposal.md) |
| 12_HANDOFF.md, handoff/published.json | what was handed to which tool, with paths; what G14 published under `docs/<run>/` |
| sources.json, sources.md | the S-### source registry |
| gates/, answers/ | exact gate texts shown; audit copies of the applied answers |
| jobs/, prompts/, logs/, .ub/ | job specs, filled prompts, call logs (`logs/calls.jsonl`: one row per attempt with its `requests`), the driver and job locks, markers, `.ub/STOP` while the run is stopped |
| _superseded/ | outputs moved aside by redo, switch, import and resets (never deleted, never overwritten) |
