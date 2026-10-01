# The Ultimate Brainstorming Workflow for Claude Code and Codex

Checked against the component repositories, the Claude Code docs (v2.1.280) and the Codex docs (rust-v0.156.0) as of
2026-09-23. Time and token figures are estimates unless a source is named; the kit's call, token and time figures come
from its own planner, `ub plan` (section 0 says how). Anything not confirmed by a source is marked "likely",
"inferred" or "not documented".

---

## 0. The kit (v2)

Everything in this guide is automated by the **ultimate-brainstorm kit v2** (2.1.1). You install it once, type one
command in your agent, and answer about 7 short replies (standard mode, guided): kickoff, frame, gut pick, decision,
architecture choice, sign-off and handoff. Full-auto needs none after a one-time privacy confirmation.
Out come a decided idea, an architecture package (`10_ARCHITECTURE/`) and a full proposal (`11_PROPOSAL/PROPOSAL.md`,
`ONE-PAGER.md`, `index.html`). Every evidence rule in this guide still applies; the kit enforces them in code.

**Install** (details in section 3 and `docs/INSTALL.md`): `py -3 <kit>/install/install.py` prints a plan and writes
nothing; `py -3 <kit>/install/install.py install` applies it (macOS and Linux: `python3`). It sets up the kit for every
agent it finds, plus Compound Engineering and mattpocock `grilling` + `domain-modeling`, and prints how to add the Codex,
Claude Code and Kimi CLIs and a GLM key (`--with-clis claude,codex,kimi --login` and `setup-glm` do it for you).

**Run:**

| Host | Command |
|---|---|
| Claude Code | `/ultimate-brainstorm <topic>` |
| Codex | `$ultimate-brainstorm <topic>` (approve "always" for the `ub` command prefix: nested model CLIs need network) |
| Kimi Code CLI v2 | `/skill:ultimate-brainstorm <topic>` |
| ZCode | `$ultimate-brainstorm <topic>` |
| Claude Code or Codex on GLM or Kimi models | start `claude-glm`, `codex-glm`, `claude-kimi` or `codex-kimi` from `~/.ultimate-brainstorm/bin/`, then as above |
| Terminal only | `~/.ultimate-brainstorm/bin/ub run "<topic>"` (or `ub run --text-file <file>` for text with quotes or `$`) |

Inside an agent, the skill writes what you typed to `brainstorm/.kickoff.txt` and starts the run with `ub init
--text-file`, so no shell ever sees your words. Words before the topic choose the mode (`quick`, `deep`, `proposal
<your idea>`), the variant (`software`, `product`, `growth`, `research`, `marketing`, `creative`, `naming`), the
autopilot (`hands-on`, `full-auto`) and `private` (host vendor only, no web). `web: no`, `vendors: no` or `code: no`
before the topic or ending a line applies to that run; a no the kit cannot place as a setting (`(vendors: no)`, `no
vendors please`, `don't send anything to OpenAI`) makes the kickoff card ask, even in full-auto (docs/PRIVACY.md).
Other wordings (`No web.`, `web off`) are not read: type `web: no`, `vendors: no`, `code: no` or `private`.
Without a variant word the variant is guessed from keywords in the topic, and the first card says so ("inferred") and
how to change it. `continue`, `status`, `stop` and `doctor` work the same way, alone or followed by a run's folder
name or path; followed by anything else they are neither run nor started as a topic, and the card asks you to put a
mode word first (`/ultimate-brainstorm standard stop smoking coach for nurses`). `stop` pauses a run (running calls
are stopped and nothing new starts) until `continue` (or `run --continue` in a terminal; the agent's own polling never
resumes it), and does nothing on a finished run; `ub budget "<run>" --max-calls N` raises a run's request cap. Keep
runs out of folders whose path holds a `$` before a name (`pay$app`), a backtick or a double quote: the commands on
every card would lose it in the shell, so such a run is not started.

**How it runs.** The skill is a thin driver. A Python engine (`ub.py`) decides every step from a pipeline file and returns
one card per call: AUTO (work is running), HUMAN (a question for you), HOST (an interactive skill such as grilling runs
in your conversation), HOST_BATCH (fresh sub-agents run prompt files), DONE or BLOCKED (with fix commands). Each model
call is a detached worker (`family.py`) that survives the host's command timeouts; `bs.py` does all counting. All state
lives in `brainstorm/<run>/run.json` and plain files, so any agent can `continue` a run. One session drives a run
at a time (an operating-system lock that a crashed session never keeps); another session's command waits and
retries.

**Replies.** Answer a checkpoint in the words its card shows (`kill I-003`, `publish architecture, ce`, `raise to
300`). Where a reply acts (a kill, a publish, a switch, an extension, a raised budget), a word the kit does not read
next to the action is asked again instead of guessed (`publish everything, omit the proposal` gets "Your reply has
words I cannot read next to `proposal` ('omit')"): put a reason after `because`, in brackets or after ` # ` (`kill
I-003 (dup of I-007)`); a note that says no is read with the answer (`publish everything # not the proposal`
reads as publishing the rest). A question, a hedge, sarcasm (`why not`) and a reply that corrects itself (`A,
actually B`) are asked again too, wherever they stand (`raise to 300 (not sure)`, `idk, kill I-003`, `raise to 300
(no, 250)`). Text that is not your own answer (a colleague's line such as `Sam (Slack): 'reject 3'`, a pasted card, a
signature) is only a note, and a reply of nothing else is asked again. At the confirm checkpoints (G2c, G10) only a
reply that is all correction starts a redo: `ok, corrections to follow` or `fine by me, I don't know much about this`
is asked again.

**Read-backs.** A reply in the card's own words acts at once (`kill I-003`, `publish all, ce`, `raise to 300`, `ok`).
Any other reply the kit can read waits for you: the same card comes back with "I read your reply as: <what the kit will
do>. Reply yes to do that, or tell me what you want instead." Nothing has happened yet. Reply `yes` (or `ok`, `go
ahead`, `do it`, `alright`, `that's what I meant`, a thumbs-up) to do exactly that, `no` to be asked again, or say what
you want instead, which is read
afresh (and may be read back in turn). A question or an unclear reply brings the card back still offering the reading.
A yes or no with more words (`yes, and kill I-007 too`) is asked again: say the whole answer in one reply. A
correction at G2c or G10, `changes: ...` at G13 (a paid change round) and seed ideas at the start are always read
back, the seeds listed as the vendors will receive them. At G13, `approve` after a reading of a switch or a change
round is asked once; a second `approve` keeps the card's architecture. So is `go` after a reading that stops a v1 run
(`ok go` too): a second `go` extends it. So is `publish` after a publish reading that names a handoff or only some
items: a second `publish` publishes all three with no handoff. At the start, a new reply that leaves out the privacy
you asked for (`start` after `let's go, and keep it private`) brings the private reading back: `yes` keeps it. If the
run moves on before you answer (a stop and continue, a redo, a restore), a late `yes` is asked again rather than acting
on the old reading.
At the finalist, red-team and decision checkpoints, `ok` or the IDs alone act at once (`I-003, I-007, I-010`; at the
decision `I-007 because nurses already trust it`, with `runner-up: I-004` or `park: I-009` if you like). Other words
are read back with every consequence: `all but I-009` or `I-004 instead of I-001` as the set it leaves (and what it
drops or adds), `not I-003, take I-007` as the idea the probe, architecture and proposal are built for, with the
runner-up the rule records. A reply that both takes and leaves out an idea, names a range (`I-001 to I-004`), names an
idea the card does not offer or puts an idea next to a word the kit does not read as taking or leaving it (`I-008
trumps I-001`) is asked again. Your gut top 3 is recorded as you wrote it, without the ideas you leave out
(`cut I-009`, `I-003 out`), never read back.
Hosts write your answer to a read-back with only `reply` filled.

**Model families.** claude (Claude Code CLI), gpt (Codex CLI), kimi (Kimi Code CLI, or Claude Code / Codex on Moonshot)
and glm (Claude Code or Codex on Z.ai). With 2 or more, generation and judging are spread across families; with one,
every "other family" seat is the same vendor in a fresh context, labeled PROVISIONAL.

**Modes.** The call, time and token figures are the kit's own plan, produced with
`ub plan --mode <mode> --variant general --families claude,gpt,kimi --json` (and `--families claude,gpt,kimi,glm` for
the figures in brackets) on kit 2.1.0 with no user configuration; the software variant gives the same numbers. The
first card of every run shows the same estimate for the families you actually have, plus one preflight ping per family
(and one web probe for Codex).

| Mode | Replies (guided) | Model calls, 3 families (4) | Model time | Tokens | Contents |
|---|---|---|---|---|---|
| quick | 4-5 | 16 (16) | 33-77 min | 0.22-0.49M | brief + 5 ideas + 3 criteria, one generation pass on 2 families, a blind score by both of them (and by a third family when you have one), both-order judging by one other family, gut pick (hands-on only), decision, quick probe, lite architecture and proposal; "Novelty NOT checked" |
| standard | 6-7 | 55-74 (56-75) | 92-212 min, mostly unattended | 0.65-1.91M (0.67-1.94M) | Stages 0-14 in full |
| deep | 6-9 | 73-194 (78-227) | 130-299 min (136-312) | 0.82-4.30M (0.88-4.98M) | standard plus the deep extras of sections 4 and 7, 4 architecture candidates, 4 review lenses, PR/FAQ |
| proposal | 5-6 | 46-49 (47-50) | 77-176 min | 0.55-1.35M (0.57-1.39M) | your idea as the primary, 2 contrast variants, checks, tournament, red-team, decision (default: your idea), probe, Stages 12-14 |

Model time is the plan's estimate for the model calls alone (at most 4 run at once); your replies, interactive skills
such as grilling or ce-ideate, and the probe come on top. A call that succeeds the first time is one backend request.
The run's budget counts backend requests, retries and repair calls included: the caps are quick 60, standard 180, deep
600 and proposal 90, and a launch starts only when its worst case fits (`ub plan` prints that worst case as
`requests.max`, counting every retry, the repair call and every backend of the family). A guided run asks before a
launch would pass the cap (GB); full-auto stops, and `ub budget "<run>" --max-calls N` lets it go on.

**Autopilot presets:**

| | hands-on | guided (default) | full-auto |
|---|---|---|---|
| Kickoff (plan, cost, vendors, privacy, optional seeds) | asks | asks; the same reply can carry your seed ideas | asks until privacy defaults are saved, and again when a family from a new vendor is enabled |
| Frame | grilling up to 3 rounds, then confirm | grilling 1 round if installed, otherwise a short question form | drafted, every item ASSUMED |
| Round 2, rescues, K4 kills, finalists | asks | automatic; K4 candidates are parked, never killed | automatic |
| Gut pick, then decision | gut pick before any judge runs; decide | gut pick while sealed judges run (quick and proposal: no gut pick); decide (`ok` accepts the suggestion) | rule default, stamped AUTO-DECISION |
| Probe | waits for the result | designed; report later with `probe passed`, `probe missed` or `probe inconclusive` | designed only |
| Architecture choice | asks (plus drivers and each ADR; quick: the choice only when the leader is vetoed, self-judged or confounded) | asks (quick: only when the leader is vetoed, self-judged or confounded) | leader, AUTO-DECISION |
| Sign-off and handoff | asks | asks | DRAFT with "AUTOPILOT DRAFT: no human decisions were made" |

**File names in sections 5-9.** Those sections describe the v1 method and keep its names. In the kit, the handoff stage
is Stage 14 (v1 "Stage 12") and writes `12_HANDOFF.md` (v1 `10_HANDOFF.md`); `10_ARCHITECTURE/`, `11_PROPOSAL/`,
`run.json`, `PROGRESS.md` and `jobs/` are new, and the prompts live in `skills/ultimate-brainstorm/templates/prompts/`
instead of `references/prompts.md`.

---

## 1. The answer on one screen

Don't install ten brainstorming tools and let them fight over the word "brainstorm". Install one owner, give it two
model families, add three best-in-class components, and copy the best mechanisms of everything else as prompts. Then run
an evidence-first pipeline in which the human ideates first, generators work in isolation, judging is debiased, and the
human decides.

### The stack (updated in v2)

| Role | Pick | Status |
|---|---|---|
| Owner and orchestrator | The `ultimate-brainstorm` kit (section 0): the skill drives `ub.py`, a scripted engine for all 14 stages (built-in prompt templates, detached model-call workers, `bs.py` for deterministic tallies); set up by `install/install.py` | required |
| Model families (N) | Any of: claude (Claude Code CLI, `claude -p`), gpt (Codex CLI, `codex exec`), kimi (Kimi Code CLI v2, `kimi -p`; or Claude Code / Codex on Moonshot) and glm (Claude Code or Codex on Z.ai, GLM Coding Plan). The host's own family plus every other family it can reach; 2 or more give cross-family generation and judging, 3 recommended | strongly recommended |
| Divergent engine | Compound Engineering `ce-ideate` (grounding, 3-5 axes, 6 frames covered by 5 parallel ideation agents, evidence tag per idea, fresh-context refuting verifier) | recommended |
| Framing interview | Matt Pocock `grilling` (frontier question rounds, facts looked up, decisions asked, confirmation gate); in a repo (software, growth) `grilling` + `domain-modeling`, the pair `grill-with-docs` wraps, which adds glossary challenges and code-contradiction checks (section 2.4) | recommended |
| Spec and plan handoff (software) | Compound Engineering `ce-brainstorm` then `ce-plan` by default; Superpowers or OpenSpec only in repos that already use them | per repo |
| Extra council seats | hex `claude-council` (Gemini, Grok, Perplexity, OpenRouter, ollama seats) | optional |
| Prior-art counts (developer tools) | `idea-reality-mcp` (low ranking score, 42/100: counts only; Stage 7's built-in check is the gate) | optional |
| Deep human facilitation, forging | BMAD `bmad-brainstorming` (Facilitator stance), `bmad-forge-idea` | optional, deep mode |
| Variant modules | pm-skills (product), K-Dense `hypothesis-generation` (research), ARIS `novelty-check` (ML), marketingskills, creative-director, glacierphonk `naming` | per variant |
| Copied as prompts, not installed | Verbalized Sampling, gstack forcing questions, PAL stance guardrails, co-scientist evolve and tournament, lateral-thinking transfer method, idea-validation-agents risk test, GSD explore's admit/refute/abstain dispositions, Hermes anti-slop tests, and more (section 2.3) | built in |

### The pipeline at a glance (updated in v2)

```
 0 ROUTE     size check, detect tools, run folder, two privacy questions
 1 SEEDS     the human writes ideas alone (optionally a primary idea to pressure-test); no AI idea visible yet
 2 FRAME     question-only interview -> job statement, criteria, axes, kill condition
 3 GROUND    researcher: FACTS (shared with generators) | LANDSCAPE (held back from them)
 4 DIVERGE   5 isolated strategies across the model families
             S1 ce-ideate | S2 Verbalized Sampling ladder | S3 enumerate->diversify (other family)
             S4 cross-domain transfer (web) | S5 provocation operators (other family)
 5 MAP       dedup by mechanism (curator), IDs and counts by bs.py, clusters, coverage grid, HOMOGENIZED alarm,
             gap + landscape-aware reopening rounds, human round 2
 6 SCREEN    cross-family absolute rubric -> <= 12 (best per cluster + tail slot + human slot)
 7 CHECK     named prior art, steelman, falsifiable kill-assumptions
 8 EVOLVE    hybrids, simplification, repair: they compete, never replace
 9 TOURNEY   human blind pre-commit -> pairwise, both orders x N families -> audits
10 RED-TEAM  advocate and critic from different families -> synthesis -> HUMAN DECISION
11 PROBE     pre-registered riskiest-assumption test (spike, pretotype, pilot)
12 ARCH      frozen brief -> drivers -> 2-4 competing architectures from different families -> blind judging
             -> HUMAN CHOICE -> package, ADRs, verified stack, review lenses
13 PROPOSAL  cited sections from evidence packs -> one-pager -> rubric + red-team -> fix -> HTML pack
             -> HUMAN SIGN-OFF
14 HANDOFF   publish to docs/<run>/ on your yes; ce-brainstorm -> ce-plan | Spec Kit | one-pager; LEDGER rows
```

| Mode | Model calls, time and tokens (`ub plan`, 3 families) | What changes |
|---|---|---|
| quick | 16 calls, about 30-80 minutes of model work, 0.2-0.5M tokens | 5 human ideas and 3 criteria, one generation pass on 2 families, a blind score by both (and a third family), other-family both-order check, human pick plus risk test, then a lite architecture and proposal |
| standard | 55-74 calls, about 1.5-3.5 hours of model work (mostly unattended; about 6-7 replies), 0.6-1.9M tokens split across the families | the 14 stages above |
| deep | 73-194 calls, about 2-5 hours of model work, 0.8-4.3M tokens | adds a facilitated human round, more strategies, per-pair judging, forging, a 10-day build simulation, 4 architecture candidates and a PR/FAQ |
| proposal | 46-49 calls, about 1.3-2.9 hours of model work, 0.5-1.4M tokens | starts from your own idea: contrast variants, checks, red-team, decision, probe, then Stages 12-14 |

### The rules the pipeline never breaks

1. The human writes ideas alone, in writing, before seeing any AI idea.
2. Framing asks questions; it never proposes solutions.
3. Diversity comes from several isolated strategies, not from temperature, personas or extra vendors.
4. Nothing is thrown away before the full pool is deduplicated and mapped.
5. Novelty is decided by named prior art, never by an LLM judge.
6. Screen with absolute scores; rank with pairwise comparisons in both orders by two model families.
7. Debate and critique only narrow the field; they never generate it.
8. The human decides, after committing a gut ranking before seeing any judge's output.
9. Nothing is built before its riskiest assumption survives a pre-registered test.
10. Every artifact lives in a file, so any tool and any session can pick up the thread.

### How the stack fared in the full ranking (updated in v2)

This design was cross-checked against the separate landscape ranking in
[`research/BRAINSTORMING_TOOLS_REPORT.md`](../research/BRAINSTORMING_TOOLS_REPORT.md) (the companion report, in the
repository's `research/` folder): 2,283 deduplicated tools, 483 verified, 393 ranked on an
11-criterion rubric, with the top 61 re-scored by two adversarial reviewers (ranks and scores below are from that report).

| Design role | Tool | Rank / score | Verdict |
|---|---|---|---|
| Divergent engine | Compound Engineering `ce-ideate` + `ce-brainstorm` | #1 / 82 | Confirmed: the only tool combining a parallel divergence fleet, file:line grounding, fresh-context refutation and a planning handoff |
| Deep-mode human round | BMAD `bmad-brainstorming` | #2 / 73 | Confirmed: best human facilitation (108 techniques, resumable log) |
| Framing interview | mattpocock `grill-me` / `grilling` (+ `domain-modeling` in a repo) | #22 / 63 | Confirmed for framing only: it turns an idea into decisions and generates no alternatives, which is exactly the Stage 2 job. The ranking scored grill-me; grill-with-docs was not scored separately, since it is the same interview plus domain-modeling (section 2.4) |
| Spec handoff alternative | Superpowers `brainstorming` | #5 / 67 | Confirmed as a design gate, not a generator (only its architectural path proposes 2-3 alternatives) |
| Product module | phuryn `pm-skills` brainstorm-ideas | #18 / 63 | Confirmed |
| Marketing module | `marketing-ideas` + `marketing-council` | #19 / 63 | Confirmed; note its ideas come from a fixed catalog (retrieval, not generation) |
| Optional council seats | hex `claude-council` | #86 / 60 | Kept as optional seats only; see alternatives below |
| Optional prior-art counts | `idea-reality-mcp` | #340 / 42 | Low score: use only for quick GitHub/package counts; the built-in Stage 7 prior-art check is the real gate |

Top-ranked tools that are deliberately not installed, and why:
- **gstack office-hours (#4)**: divergence scored 2/5 and the install is very heavy; its forcing questions are ported as prompts.
- **ARIS idea-discovery (#3)**: ML-only; `AUTO_PROCEED` defaults to true and can launch GPU pilots unattended; reviewers found its
  "cross-family jury" is not independent (the same GPT thread generates and triages) and runs of about 10M tokens are reported.
  The research variant uses only its `novelty-check`.
- **K-Dense scientific-brainstorming (#6)**: a protocol for human groups that deliberately limits AI contribution.
- **idea-refine (#7)**: caps output at 5-8 ideas; its one-pager with "Not Doing" is kept for the handoff.
- **Google Co-Scientist (#8)**: no API, MCP or skill; its generate-debate-evolve-tournament design is copied into Stages 8-9.
- **ADHD (#20)**: isolated parallel frames with an independent blind benchmark, but no questions, no artifact and no grounding;
  Stage 4's isolated strategy portfolio covers the same mechanism.

Optional alternatives surfaced by the ranking (not wired into the skill's tool detection; install and use them by hand):
- **Council of High Intelligence (#23 / 63)** for a high-stakes Stage 10 deliberation: blind first round, anonymized
  cross-examination, dissent quotas. Caveats from the report: auto-routing is on by default and sends your problem to any
  external CLI it detects, and its Codex template runs `codex exec -c auto_approve=true`.
- **workshop from consult-llm (#12 / 64)** for independent cross-model design proposals plus a red-team risk register
  (tiny adoption).
- **lateral-thinking by danium (#36 / 62)** for provocation-style ideas in the creative variant.
- **Claude Design (#9 / 65)** for visual directions shown side by side (UI and visual concepting only).

---

## 2. Why this combination

### 2.1 What the research says and the rule it becomes

| Finding (source) | Rule | Stage |
|---|---|---|
| Nominal groups beat talking groups in 18 of 22 experiments (Diehl and Stroebe 1987); productivity loss vs. nominal groups was smaller when group members wrote their ideas rather than speaking them (Mullen et al. 1991); working alone then together gave more and better ideas and better selection (Girotra, Terwiesch, Ulrich 2010) | Sealed solo seeds; a second human round after the map; a solo gut ranking before the judges | 1, 5, 9 |
| Using an LLM from the start produced fewer original ideas and less ownership (Qin et al., CHI 2025); AI examples caused fixation (Wadinambiarachchi et al., CHI 2024); LLM help lowered later unassisted creativity (Kumar et al. 2024/25); AI raised individual quality but made stories more alike (Doshi and Hauser 2024) | No AI idea visible before the seeds; landscape examples withheld from blind generators | 1, 3, 4 |
| A model-led rewrite mode raised quality but cut diversity and ownership; question-and-suggest modes kept both (Maier et al., CHI 2026) | Question-only framing; the AI never rewrites the human's ideas | 2, 10 |
| Enumerate, then make bolder and different, then describe brought GPT-4 close to human-pool diversity; different prompt strategies overlap little; this chain's diversity advantage over the base prompt disappears after about 750-800 ideas as the pool depletes (Meincke, Mollick, Terwiesch 2024) | A portfolio of short, different strategies; a checked diversify step; no selection before mapping (a design rule) | 4, 5 |
| Verbalized Sampling gave 1.6-2.1x diversity over direct prompting in creative writing and +25.7% human-rated diversity; lower probability thresholds give more diversity (Zhang et al. 2025) | A VS ladder: full distribution, then below 0.10, then below 0.01 | 4 |
| Only about 5% of 4,000 LLM ideas were unique, even with "avoid repeats" in the prompt (Si, Yang, Hashimoto 2024) | Explicit mechanism-key dedup, yield tracking, strategy switching on saturation | 5 |
| Dense communication and dominant agents collapse diversity (Chen et al. 2026); agents that share critiques but revise alone stay divergent (LLM Review 2026, likely) | Generators never see each other; no agent teams for generation | 4 |
| LLM outputs are more alike than human outputs, across models too; within-model similarity above 0.8 in 79% of cases, cross-model 71-82% (Wenger and Kenett 2025; Artificial Hivemind 2025); feedback-tuned models homogenize co-written text (Padmakumar and He 2024) | Extra vendors de-bias judging; they are not the diversity engine | 4, 9 |
| Temperature is weakly related to novelty and moderately to incoherence (Peeperkorn et al. 2024) | No temperature tuning | 4 |
| Planned retrieval gave 3.4x more unique novel ideas (Nova 2024); comparing ideas with prior work raised novelty (SciMON 2024) | Retrieval-based transfer strategy; landscape-aware reopening round; prior-art checks | 4, 5, 7 |
| The best LLM evaluator (a Claude-3.5 pairwise ranker) agreed with experts 53.3% of the time vs 56.1% between human experts (other LLM evaluators 43.3-51.7%); LLMs were poorly calibrated at direct score prediction but reached non-trivial accuracy pairwise (pairwise did not beat direct scoring for every model); a human re-rank kept only 17 of the LLM ranker's 49 picks (Si et al. 2024) | Pairwise tournament; the human decides | 9, 10 |
| Swapping answer order let Vicuna-13B beat ChatGPT on 66 of 80 queries with ChatGPT as judge (Wang et al. 2023); judges favour their own outputs (Panickssery et al. 2024); position, verbosity and self-enhancement biases (Zheng et al. 2023) | Both orders, normalized cards, two judge families, consistency and self-preference audits | 6, 9 |
| Pairwise preferences flipped on distractors in about 35% of cases vs 9% for absolute scores (Tripathi et al. 2025); uncertainty-guided pairwise ranking beats direct scoring (PairS 2024) | Absolute screen first, pairwise among finalists | 6, 9 |
| LLM judges rated generated research questions as novel where experts did not (Sinhahajari et al. 2026); LLM judges did not track expert creative judgment (Chakrabarty et al., CHI 2024); fine-tuning on human ratings gave the most reliable originality scores (up to r=.81); prompted GPT-4 was weaker (r=.53-.70) but still well above semantic-distance methods (Organisciak et al. 2023) | Judges never score novelty; the human is the main judge for creative work | 6, 7, 9 |
| Debate improved reasoning and factual accuracy, with no creativity claim (Du et al. 2023); self-reflection degenerates, opposed debaters with capped rounds help (Liang et al.); debate did not reliably beat self-consistency (Smit et al.); diverse critics raised feasibility (Ueda et al., SIGDIAL 2025) | Opposed-stance, cross-family critique only in convergence; at most one rebuttal | 10 |
| Generate, debate, evolve with Elo tournaments and debate only for the top ideas; its authors warn Elo is not ground truth (Google co-scientist 2025) | Evolve adds variants that must compete; tournament results are advice | 8, 9 |
| LLM ideas lost significantly more score than expert ideas once actually executed (Si, Hashimoto, Yang 2025) | A pre-registered riskiest-assumption test before any build | 11 |
| Human outputs were rated more novel at the right tail; AI gave more value on average (Boussioux et al. 2024); ChatGPT excelled at incremental recombination (Lee and Chung 2024); high exposure to many varied AI ideas raised collective diversity (Ashkinaze et al. 2024) | Protected human slot in the shortlist; the human sees the whole cluster map, not one AI pick | 5, 6 |

### 2.2 Stage by stage: what won, what it beat, and why (updated in v2)

| Stage | Pick | Why it wins | Replaced (reason) |
|---|---|---|---|
| 1 Seeds | The human alone, 10 minutes, in a file (template written by `bs.py init`); deep: BMAD Facilitator stance (the AI supplies no ideas) | The only way to keep the human's unanchored ideas; BMAD adds a 108-technique library served by script and an append-only memlog | Starting with an AI brainstorm skill (Superpowers' Architectural path reaches 2-3 AI-proposed approaches within the same session; gstack office-hours starts with context gathering, then routes startup goals to a hard forcing-question diagnostic and other goals to a design-partner mode) |
| 2 Frame | `grilling` if installed; in software and growth runs `grilling` + `domain-modeling` (P-GRILL-DOCS, section 2.4); otherwise the built-in question-only interview (with the same domain moves in a repo); all write an anchor-stripped job statement, decision ledger, premises, a kill condition for the whole effort, weighted criteria with anchors, 3 axes | Frontier rounds with recommended answers, facts looked up by the agent, confirmation gate, about 500 tokens of instructions (plus about 1k for domain-modeling in software and growth) | gstack office-hours (one of gstack's largest skills: the repo says 25-35K tokens of behavior, about 20-22K loaded up front; YC framing; offers a CLAUDE.md routing block; its forcing questions are ported as text); Superpowers (on its Architectural path, after clarifying questions, it proposes 2-3 approaches; auto-commits the spec); OMC deep-interview (in Claude Code it comes with the oh-my-claudecode plugin, which also installs OMC's prompt hooks; the plugin can be scoped to one project and its hooks disabled with `DISABLE_OMC=1`; oh-my-codex ships its own copy for Codex) |
| 3 Ground | Built-in researcher: FACTS go to every generator, LANDSCAPE (solutions, where incumbents fail, mechanism analogues) is held back from blind generators | Retrieval raises novelty; withholding examples avoids fixation | Octopus discover (about 37 hook scripts on 18 events); unlabelled "research" dumps |
| 4 Diverge | 5 isolated strategies: ce-ideate (or a frame fan-out), VS ladder, enumerate-diversify with a "Changed: N of 40" check, cross-domain transfer with links marked ESTABLISHED/INFERRED (our formalization of lateral-thinking's established-vs-inferred note), provocation operators; S3 and S5 on the other model family | Low-overlap strategy pools, measured diversity gains, cross-family generation where it is cheap | ADHD (no grounding, npm package months behind main, broad trigger); BMAD "Ideate for me" (the AI generates the ideas itself in the main session, aiming past 100); agent teams (a lead agent collapses diversity); claude-brainstorm-multiagent (MCP launch path very likely broken); BeCreative (its default workflows show only the best of 5 hidden candidates); temperature and persona casts |
| 5 Map | Built-in curator for mechanism-key dedup and clusters; `bs.py map` for random neutral IDs, origins, coverage grid, yield per strategy and the HOMOGENIZED alarm; gap rounds into empty cells, landscape-aware reopening, human round 2 | No tool deduplicates across tools; counts come from a script, not an LLM; targeted gap filling keeps the map honest | Top-N survivor lists from single tools (ce-ideate keeps 5-7; its raw candidates and rejections are imported as PARKED) |
| 6 Screen | `bs.py`: two-family absolute rubric on neutral 25-word lines, gates, floor, weight sensitivity, quotas (best per cluster, tail slot, human slot, primary idea) | Absolute scores resist distractors; two families counter self-preference; quotas protect diversity | Single-model scoring (idea-refine 2x2, ADHD weighted rank) |
| 7 Check | Built-in prior-art verdicts (CROWDED / ADJACENT / NOT LOCATED with named matches), steelman, "Fails if" kill-assumptions; `idea-reality` for developer tools; ARIS `novelty-check` for ML | Novelty from evidence, not opinion; a CROWDED kill needs named matches and human confirmation | Judge-scored novelty in any tool |
| 8 Evolve | Built-in: 2 hybrids from different clusters, a simplification, a repair of the top kill-assumption (deep: a different mechanism for the same outcome) | Co-scientist-style evolution; evolved ideas meet their parents in the tournament | Letting the model "improve" ideas in place |
| 9 Tournament | `bs.py`: normalized 90-110 word cards, human blind pre-commit, every pair in both orders by both families (deep: one call per ordered pair), consistency and self-preference audits, contested pairs to the human | The best-evidenced ranking method, debiased | claude-council as a ranker (host writes the synthesis, software-consultant prompt, no order swap); PAL consensus (unmaintained, fresh installs crash on MCP SDK 2.0, unsafe under parallel calls); Karpathy llm-council (multi-model, but no label shuffle, models rank their own answer, no license); aiwithremy llm-council (Claude sub-agents only, no license); brainstorm-mcp (a participant synthesizes, history truncated); ECC council-multi-model (pinned to codex-cli 0.146.0); OMC `/ccg` (retired) |
| 10 Red-team | Built-in advocate and critic from different families with PAL-style stance guardrails, at most one rebuttal, orchestrator pre-commit, raw verdicts shown before synthesis; optional claude-council seats | Critique where it helps (convergence), with dissent preserved | Unstructured "what do you think" rounds |
| 11 Probe | Built-in walk-through, riskiest assumption (criticality x uncertainty), threshold written first; pm-skills experiments for products, K-Dense for research | Closes the ideation-execution gap | Straight to spec or code |
| 14 Handoff | CE `ce-brainstorm` (requirements-only plan with a Ready-for-Planning check) then `ce-plan` (stable R/U-IDs, final review and confidence check); Superpowers or OpenSpec where already in use; one-pager otherwise | Clean, file-based contracts | Superpowers as the whole workflow (strong spec gate, weak divergence) |

### 2.3 Left out on purpose, with the mechanism kept

| Component | Why it is not installed | Mechanism kept (where) |
|---|---|---|
| gstack office-hours / plan-ceo-review / design-shotgun | Heavy (office-hours and plan-ceo-review are among gstack's largest skills: the repo says 25-35K tokens of behavior, about 20-22K loaded up front and more on demand), Bun, CLAUDE.md routing offer, Stop hook, short command names | Six forcing questions routed by stage (product frame); cold-read asks (red-team item 4-5) |
| idea-refine (addyosmani) | Caps divergence at 5-8 ideas; single model | One-pager with "Not Doing" (handoff) |
| OpenSpec explore | Grounded in your codebase and part of OpenSpec's spec-driven change workflow; its commands are installed by `openspec init` (Codex skills go under `.agents/skills/`); the thinking conversation writes nothing, but capturing results as a change needs an OpenSpec root | Kept as an alternative spec owner |
| GSD core | Heavy hooks and statusline; auto-commits | The spirit of `/gsd-explore`'s research pass, which tags findings `[admit: <source>]` / `[refute: <source>]` / `[abstain: <why>]` and sends abstained claims to an Unresolved ledger (GSD's researcher otherwise tags `[VERIFIED: ...]` / `[CITED: ...]` / `[ASSUMED]`); our OBSERVED / NOT VERIFIED labels and dated search boundary are our own |
| SuperClaude | Its `/sc:brainstorm` is a Markdown behavioral prompt (a "context trigger", not executable code) inside a larger configuration framework (30 commands, 20 agents, 7 modes, optional MCP servers, a Python CLI); actively but lightly maintained (v4.3.0, March 2026) with parts of the docs out of date; no Codex path | none |
| LifeOS BeCreative | Ships only as part of the LifeOS Core install (no documented per-skill option); its instructions assume LifeOS paths and the Pulse voice server on :31337; its default workflows show only the best of 5 hidden candidates | Verbalized Sampling used directly |
| cc-thinking-skills | Manual-only in Claude Code; plugin install reported broken (issues #10, #12) | TRIZ contradiction template (software operator f) |
| ADHD | No grounding; stale npm; broad trigger | Ban the obvious answers; a protected non-obvious slot; anchor-stripped brief (from its main-branch reframe pass) |
| Hermes creative-ideation | Hermes-first packaging | Anti-slop five-test diagnostic |
| neurofoo agent-skills, Jamie-BitFlight brainstorming-skill | Thin templates / a hybrid of its own 14-category ideation pattern library and an unattributed design-gate workflow modeled on Superpowers' Feb-2026 brainstorming skill that has not tracked Superpowers' later changes | none |
| claude-night-market (attune, tome) | attune depends on leyline and abstract, and its war room delegates to conjure; it also uses superpowers and imbue when installed; tome depends on leyline and adds SessionStart/PreCompact hooks; war room is mandatory | Novelty capped without prior-art evidence |
| claude-brainstorm-multiagent | Broken MCP path, global hook | Coverage grid with under-filled cells targeted, and a TENSION escape adapted from its `tension_note` field |
| brainstorm-mcp, PAL, aiwithremy / Karpathy llm-council, OMC, Octopus, ECC | See section 3.6 | "Strongest disagreement, not watered down"; stance guardrails; "what did everyone miss"; anonymized cards; host pre-commit |
| idea-validation-agents | Takes over the workspace; several stub skills | Multiplicative floor, riskiest-assumption test, inverse kill criteria |
| Anthropic product-brainstorming, Dean Peters PM skills | Conversational only / CC BY-NC-SA, and its Codex ZIP ships its own top-level AGENTS.md that can clash with or replace yours | Mandatory "opposite" and "subtraction" ideas; "How are we part of the problem?" |

### 2.4 grilling, grill-me or grill-with-docs? (updated in v2)

The short answer: in a repo, yes, grill-with-docs' behavior beats grill-me's, so software and growth runs use it. But the
pipeline loads its two parts by name instead of calling `/grill-with-docs`. Everywhere else it stays with `grilling`.
Checked against the skill files and mattpocock's docs in [mattpocock/skills](https://github.com/mattpocock/skills)
(commit c55ee46, 2026-09-18):

| Skill | What its SKILL.md actually is | Who can start it |
|---|---|---|
| `grilling` | The interview itself: a design tree asked in frontier rounds, with a recommended answer per question; facts looked up by sub-agents, decisions asked; a confirmation gate | Model-invoked (the pipeline can call it) |
| `grill-me` | One line: "Call the Skill tool with "grilling"" | Manual only (`disable-model-invocation: true`) |
| `grill-with-docs` | One line: "Call the Skill tool twice, for "grilling" and "domain-modeling"" | Manual only (`disable-model-invocation: true`) |
| `domain-modeling` | Challenges terms against `CONTEXT.md`, pins one canonical term per concept (rejected synonyms under `_Avoid_`), stress-tests relationships with edge-case scenarios, quotes the code when a claim contradicts it; writes `CONTEXT.md` inline and offers ADRs that pass three gates | Model-invoked |

Why grill-with-docs' behavior is better for software and growth framing: a brainstorm framed in vague or wrong words
produces ideas for the wrong problem. `domain-modeling` catches that before any idea exists. It flags a term you use
differently from the glossary, pins down words like "activated" or "account", and catches a claim the code contradicts
("Your code cancels entire Orders, but you just said partial cancellation is possible", from domain-modeling's SKILL.md
and docs). mattpocock's own guide says to use `grill-with-docs` in a repo and `grill-me` when there is no working
directory.

What it costs, and how the pipeline limits it: pinned terms can anchor ideation on today's domain model (section 2.1:
fixation, incremental recombination). mattpocock's own docs note that a term and its plain-English expansion get the
same result from the model, so the glossary mainly aligns humans. The pipeline therefore sends generators at most 12
relevant terms, labeled as today's system, and tells them they may break any of them (GEN-HEADER rule 8); the
assumption-breaking operators (S5 (d), LENS L4) must target at least one of them. In growth, metric definitions are
pinned for measurement only. This is a design judgment; no study measures it.

Why the pipeline does not simply call `/grill-with-docs`:
1. It cannot. `disable-model-invocation: true` means Claude cannot invoke the skill at all; only you can, by typing it
   ([Claude Code skills docs](https://code.claude.com/docs/en/skills)). In Codex it sets `allow_implicit_invocation:
   false` (only an explicit `$grill-with-docs` starts it), and its one line names a Skill tool that Codex does not have
   under that name, so it works only if the model reads both SKILL.md files on its own.
2. Its docs report two open problems exactly in this setup: models often load `grilling` and skip `domain-modeling`,
   and when it runs inside another orchestration layer "the file-writing half is reported to silently not happen". The
   pipeline names both skills and checks that each one ran (P-GRILL-DOCS).
3. It writes `CONTEXT.md` and ADRs into your repo during the session. At Stage 2 no idea has been chosen, so the pipeline
   stages terms in `brainstorm/<run>/CONTEXT.proposed.md` and holds ADRs back. Because domain-modeling's own text says
   to write inline, the P-GRILL-DOCS argument explicitly overrides those rules, the skill snapshots `CONTEXT.md` before
   round 1, and after the interview it checks with `git status` that `CONTEXT.md`, the CONTEXT-MAP contexts and
   `docs/adr/` are unchanged (if not: it shows the diff, moves the terms into `CONTEXT.proposed.md` and, on your yes,
   restores from the snapshot, never with `git checkout`). At Stage 14, you see each proposed term marked KEEP or
   CHANGED BY DECISION, choose all, some or none, and answer each ADR candidate separately.

The pipeline's FRAME file also covers what grill-with-docs' docs call "the most substantive open complaint about the
skill": decisions that are neither a term nor an ADR land in "The conversation, and nowhere else". Here every answer
lands in the Decision ledger of `01_FRAME.md`.

Where it does not help: product, research, creative and naming runs usually have no codebase or glossary, and the skill
would create a stray `CONTEXT.md` in whatever folder you are in. Those runs use `grilling` alone, which fits grill-me's
docs: grill-with-docs is for "a codebase to align against", and grill-me's subject "doesn't have to be code". Outside
this pipeline, typing `/grill-with-docs` in a repo is fine; it needs `grilling` and `domain-modeling` installed. With the
plugin install, if `/grill-with-docs` fails to load its parts, run `/mattpocock-skills:grilling` and
`/mattpocock-skills:domain-modeling` yourself.

---

## 3. Install guide (updated in v2)

### 3.0 The installer (recommended) and the package (updated in v2)

The installer does everything in sections 3.2-3.3c for every agent it finds. It prints a plan first and writes nothing
until you confirm:

```text
# One line from GitHub, any machine (macOS / Linux / WSL / Git Bash)
curl -fsSL https://github.com/MrHashMe/ultimate-brainstorm/releases/latest/download/install.sh | sh -s -- install

# One line from GitHub, Windows PowerShell 5.1+
& ([scriptblock]::Create((irm https://github.com/MrHashMe/ultimate-brainstorm/releases/latest/download/install.ps1))) install

# Or from a git clone (python3 on macOS / Linux, py -3 on Windows)
git clone https://github.com/MrHashMe/ultimate-brainstorm
python ultimate-brainstorm/install/install.py                     # plan only
python ultimate-brainstorm/install/install.py install --with-clis claude,codex,kimi --login

# Update or remove later (the one-line install stages the kit in ~/.ultimate-brainstorm/kit)
python ~/.ultimate-brainstorm/kit/install/install.py update
python ~/.ultimate-brainstorm/kit/install/install.py uninstall

# Model families beyond the CLIs (see docs/FAMILIES.md)
py -3 <kit>/install/install.py setup-glm --launcher --codex          # needs ZAI_API_KEY; [--region cn]
py -3 <kit>/install/install.py setup-kimi --launcher --codex         # needs KIMI_API_KEY; [--provider kimi-code]
py -3 <kit>/install/install.py doctor --live                         # check everything
```

It stages the kit in `~/.ultimate-brainstorm/kit/`, installs it as a native plugin in Claude Code (2.1.268+) and Codex
(0.156+) from that folder, copies the skill for Kimi Code and ZCode, adds the core components (Compound Engineering and
mattpocock `grilling` + `domain-modeling`), and writes the `ub` terminal launcher. Every agent sees exactly one
`ultimate-brainstorm`. It never edits PATH, shell profiles, `settings.json`, `config.toml`, `CLAUDE.md` or `AGENTS.md`
unless a flag asks for it. Every option, update and uninstall: `docs/INSTALL.md`.

The package:

```
kit/                                  one repo = the plugin for Claude Code, Codex and Kimi Code, and a skills source
  install/install.py                  installer: plan, install, update, uninstall, doctor, list, setup-glm, setup-kimi
  profiles/                           launchers: claude-glm, claude-kimi, codex-glm, codex-kimi, ub
  skills/ultimate-brainstorm/
    SKILL.md                          the driver: runs ub.py and does what each card says (at most 12 KB)
    agents/openai.yaml                Codex display name; explicit invocation only
    references/                       pipeline, hosts, families, components, variants, techniques, kill rules,
                                      architecture, proposal, install, troubleshooting
    templates/                        one ASCII prompt template per isolated call, gate texts, doc skeletons, schemas
    scripts/ub.py                     engine: the 14-stage state machine, one card per call
    scripts/family.py                 model-family adapter; one detached worker per model call
    scripts/bs.py                     Python 3.9+ standard library: init, status, schemas, map, screen, tournament
                                      (N families), quick-pick, arch-matrix, lint-*, split, sources, assumptions
  docs/                               this guide, INSTALL, HOSTS, FAMILIES, PRIVACY, TROUBLESHOOTING
```

bs.py works on v2 run folders (run.json); a `ub` command that drives the run (`ub continue "<run>"`) migrates a v1
run folder once; `ub status` only reads it. Its behavior (gate kills and floor, human slot, both-order tallies,
position and self-preference audits, per-pair mode, tolerant reads of model output, status checks) is covered by the
kit's test suite (`python tools/ci.py all`), which uses fake CLIs and never calls a real model.

The sections below are the manual route, **without the installer**.

### 3.1 Prerequisites, CLIs and keys (updated in v2)

| Item | Needed for | Notes |
|---|---|---|
| Claude Code, Codex, Kimi Code CLI v2 or ZCode | host | Codex IDE extension has no plugin support (ce-ideate unavailable there); the kit's terminal mode (`ub run`) needs no host |
| Codex CLI (`npm install -g @openai/codex`, `codex login`) | GPT family when the host is Claude Code | ChatGPT plan or OpenAI API key |
| Claude Code CLI (`npm install -g @anthropic-ai/claude-code`, run `claude` once) | Claude family when the host is Codex | a Pro, Max, Team, Enterprise or Console account (the free claude.ai plan does not include Claude Code), or a third-party provider (Amazon Bedrock, Google Cloud's Agent Platform, Microsoft Foundry); with `ANTHROPIC_API_KEY` set, Claude Code asks once to approve the key instead of opening a browser |
| Python 3.9+ | the installer, `ub.py`, `family.py`, `bs.py` (standard library only) | the first of `py -3`, `python3`, `python` that works; on Windows `python3` is often the Microsoft Store stub |
| Kimi Code CLI 2.0+ (`npm install -g @moonshot-ai/kimi-code`, `kimi login`) | kimi family; Kimi Code as host | Windows: Git for Windows (Git Bash) or `KIMI_SHELL_PATH` required; the CLI ignores `KIMI_API_KEY` (log in with `kimi login`); the archived 1.x `kimi-cli` is not supported |
| ZCode desktop | host (glm family) | the skill is copied to `~/.zcode/skills`; its plugin screen is a manual step |
| `ZAI_API_KEY` (GLM Coding Plan) | glm family through Claude Code or Codex; the `claude-glm` / `codex-glm` launchers | `install.py setup-glm --launcher --codex`; the plan may be used only in supported tools, so the kit sends GLM traffic only through Claude Code or Codex |
| `KIMI_API_KEY` (Moonshot Platform) or `KIMI_CODE_API_KEY` (Kimi Code membership) | kimi family through Claude Code or Codex; `claude-kimi` / `codex-kimi` | optional; `install.py setup-kimi` |
| Node.js and npm | installers; the agent CLIs' npm installs need Node 22.20+ | BMAD's installer needs Node.js 20.12+; the mattpocock skills need no Node (the installer copies them from a pinned archive) |
| Git for Windows (Git Bash) | bash commands, claude-council, Superpowers hook; ce-ideate's scratch-dir setup is a bash snippet (our inference; not a documented CE requirement) | Windows only; Codex on native Windows runs PowerShell (or use WSL) |
| `GITHUB_TOKEN` | idea-reality search rate limits | optional |
| `GEMINI_API_KEY`, `PERPLEXITY_API_KEY`, `XAI_API_KEY`, `OPENROUTER_API_KEY` or CLIs (`agy` as the separate `antigravity` seat, `grok`, `ollama`) | claude-council seats | optional; bash (Git Bash on Windows), curl and jq required |
| uv | idea-reality (the documented setup uses `uvx`, with Python >= 3.11); BMAD (uv plus Python 3.10+ on stable 6.12.0, 3.11+ on main) | optional |

### 3.2 Claude Code, without the installer (updated in v2)

```text
# Shell: the kit as a native plugin (Claude Code 2.1.268+) from a local copy or the GitHub repo; this replaces the
# skill copy below. After a release: claude plugin marketplace add MrHashMe/ultimate-brainstorm@v2.1.1
claude plugin marketplace add <abs path to kit>
claude plugin install ultimate-brainstorm@ultimate-brainstorm --scope user

# Shell: another model family
npm install -g @openai/codex
codex login

# Shell: the orchestrator skill (personal scope); create the skills folder first, or the copy lands in the wrong place
mkdir -p ~/.claude/skills && cp -r kit/skills/ultimate-brainstorm ~/.claude/skills/            # Git Bash, macOS, Linux
New-Item -ItemType Directory -Force "$HOME\.claude\skills" | Out-Null; Copy-Item -Recurse .\kit\skills\ultimate-brainstorm "$HOME\.claude\skills\"   # PowerShell

# In a Claude Code session, inside the project: Compound Engineering. The dialog offers User, Project and Local scope;
# pick Local in a shared repo (Project writes the tracked .claude/settings.json for everyone)
/plugin marketplace add EveryInc/compound-engineering-plugin@compound-engineering-v3.28.2
/plugin install compound-engineering
# Optional pin against fast releases (shell; tag name taken from the release name; `claude plugin install` without
# --scope installs at user scope):
#   claude plugin marketplace add EveryInc/compound-engineering-plugin@compound-engineering-v3.28.2

# grilling + domain-modeling (used by the pipeline): the installer copies them (install.py install --components core);
# by hand: download https://codeload.github.com/mattpocock/skills/tar.gz/c55ee46073ed923f86ce59a5eb3b6d895095d1b7
# and copy skills/productivity/grilling and skills/engineering/domain-modeling into ~/.claude/skills/
#   or, in a session: /plugin install mattpocock-skills@claude-plugins-official  (the whole set; never both routes;
#   the plugin's skills are then called mattpocock-skills:grilling and mattpocock-skills:domain-modeling)
# Optional, your own choice (the kit does not install them): the grill-with-docs / grill-me wrappers for typing
# yourself outside the pipeline, user scope. --copy: without it the CLI keeps the canonical copy in ~/.agents/skills,
# which Codex also scans (and symlinks can fail on Windows without Developer Mode)
DISABLE_TELEMETRY=1 npx -y skills@1.7.0 add mattpocock/skills#c55ee46073ed923f86ce59a5eb3b6d895095d1b7 --skill grill-with-docs --skill grill-me -g -a claude-code --copy

# Optional: council seats from more vendors
/plugin marketplace add hex/claude-marketplace
/plugin install claude-council
/claude-council:status

# Optional, shell: prior-art counts for developer-tool ideas (documented option order: options, then the name)
claude mcp add --env GITHUB_TOKEN=<token> --transport stdio idea-reality -- uvx idea-reality-mcp@0.5.0
```

Check: `/skills` lists `ultimate-brainstorm` (and `compound-engineering:ce-ideate`, and `grilling` / `domain-modeling`
or their `mattpocock-skills:` names, if installed).
Start: `/ultimate-brainstorm standard product "<your topic>"`. Resume later with `/ultimate-brainstorm continue <run>`
(without `<run>` it picks the newest unfinished run and says which).

### 3.3 Codex, without the installer (updated in v2)

```text
# Shell: the kit as a native plugin (Codex 0.156+), then restart Codex; this replaces the skill copy below.
# After a release: codex plugin marketplace add MrHashMe/ultimate-brainstorm@v2.1.1
codex plugin marketplace add <abs path to kit> --json
codex plugin add ultimate-brainstorm@ultimate-brainstorm --json

# Shell: another model family (skip for Codex-only: the kit then gives every other-family seat to a fresh GPT
# context, labeled PROVISIONAL)
npm install -g @anthropic-ai/claude-code        # then run `claude` once to sign in

# Shell: the orchestrator skill (personal scope); create the skills folder first
mkdir -p ~/.agents/skills && cp -r kit/skills/ultimate-brainstorm ~/.agents/skills/
New-Item -ItemType Directory -Force "$HOME\.agents\skills" | Out-Null; Copy-Item -Recurse .\kit\skills\ultimate-brainstorm "$HOME\.agents\skills\"   # PowerShell

# Shell: Compound Engineering, then restart Codex
codex plugin marketplace add EveryInc/compound-engineering-plugin@compound-engineering-v3.28.2
codex plugin add compound-engineering@compound-engineering-plugin

# grilling + domain-modeling, user scope: the installer copies them (install.py install --components core); by hand:
# download https://codeload.github.com/mattpocock/skills/tar.gz/c55ee46073ed923f86ce59a5eb3b6d895095d1b7
# and copy skills/productivity/grilling and skills/engineering/domain-modeling into ~/.agents/skills/, the user folder
# Codex scans (learn.chatgpt.com/docs/build-skills). Not ~/.codex/skills: a deprecated location Codex still loads for
# backward compatibility (codex-rs/ext/skills/src/host_roots.rs) but no longer documents. Skip grill-me and
# grill-with-docs in Codex: each is one line naming a Skill tool that Codex does not have under that name, so they are
# unreliable there.

# ~/.codex/config.toml, top-level key above any [table] header (default search mode is "cached")
web_search = "live"

# Optional: claude-council direct scripts (bash, curl, jq; API keys for other vendors)
git clone https://github.com/hex/claude-council.git ~/claude-council
# Optional: prior-art counts (matches Codex's documented syntax; the repo documents no Codex command; untested)
codex mcp add idea-reality --env GITHUB_TOKEN=<token> -- uvx idea-reality-mcp@0.5.0
```

Launch: `codex --sandbox workspace-write --ask-for-approval on-request --search` (`--search` gives live web search if
`config.toml` was not changed). Check: `/skills` lists ultimate-brainstorm, ce-ideate, grilling and domain-modeling.
Start: `$ultimate-brainstorm standard product "<your topic>"` (or pick it in `/skills`; a plugin skill may be listed
under a namespaced name). The kit's model calls are nested `claude -p`, `codex exec` and `kimi -p` processes that need
network access, which the workspace-write sandbox blocks, so Codex asks for escalation: approve the `ub` command prefix
for the session. On native Windows, Codex runs commands in PowerShell; the kit's Python engine does all piping and
quoting itself, so the PowerShell forms in section 5.3 are needed only for manual calls.

Moving an existing Claude Code setup: Codex's `/import` migrates instruction files, skills, plugins, MCP config,
hooks, slash commands and subagents without changing the original.

### 3.3a Kimi Code, without the installer (updated in v2)

```text
# Shell: Kimi Code CLI v2 (Windows: install Git for Windows first); the old kimi-cli 1.x is not supported
npm install -g @moonshot-ai/kimi-code
kimi login

# Shell: the skill. Kimi reads ~/.kimi-code/skills (or $KIMI_CODE_HOME/skills) and also ~/.agents/skills, so skip this
# when the Codex copy in section 3.3 exists (one copy per agent)
mkdir -p ~/.kimi-code/skills && cp -r kit/skills/ultimate-brainstorm ~/.kimi-code/skills/
#   or, in a Kimi session (plugin route): /plugins install <abs path to kit>   then /reload

# grilling + domain-modeling (skip when section 3.3 already put them in ~/.agents/skills): the installer copies them
# (install.py install --components core); by hand: download
# https://codeload.github.com/mattpocock/skills/tar.gz/c55ee46073ed923f86ce59a5eb3b6d895095d1b7
# and copy skills/productivity/grilling and skills/engineering/domain-modeling into ~/.agents/skills/

# In a Kimi session: Compound Engineering
/plugins install https://github.com/EveryInc/compound-engineering-plugin/releases/tag/compound-engineering-v3.28.2
/reload
```

Start: `/skill:ultimate-brainstorm standard product "<your topic>"`. Approve the Bash command prefix once. Kimi's Bash
tool allows 5 minutes per command and keeps longer ones running in the background; the kit waits about 4.5 minutes per
step.

### 3.3b ZCode, without the installer (updated in v2)

```text
# Shell: the skill
mkdir -p ~/.zcode/skills && cp -r kit/skills/ultimate-brainstorm ~/.zcode/skills/
# grilling + domain-modeling: the installer copies them (install.py install --components core); by hand: download
# https://codeload.github.com/mattpocock/skills/tar.gz/c55ee46073ed923f86ce59a5eb3b6d895095d1b7
# and copy skills/productivity/grilling and skills/engineering/domain-modeling into ~/.zcode/skills/
# ZCode > Settings > Plugins > add marketplace EveryInc/compound-engineering-plugin (manual; not yet verified here)
```

Start: `$ultimate-brainstorm standard product "<your topic>"`. ZCode's own family is glm; other families join through
the claude, codex and kimi CLIs. ZCode's sub-agent and shell behavior with the kit is not yet verified: without a
sub-agent tool, host-family jobs run one by one and are labeled PROVISIONAL. The headless `zcode` CLI is never used.

### 3.3c GLM and Kimi models through Claude Code or Codex (updated in v2)

```text
# GLM (Z.ai Coding Plan key); --region cn uses open.bigmodel.cn
[Environment]::SetEnvironmentVariable("ZAI_API_KEY","<key>","User")      # PowerShell (new window afterwards)
export ZAI_API_KEY=<key>                                                  # bash: in your profile
py -3 <kit>/install/install.py setup-glm --launcher --codex [--region cn] [--zai-mcp]

# Kimi models (Moonshot Platform key KIMI_API_KEY, or Kimi Code membership key KIMI_CODE_API_KEY)
py -3 <kit>/install/install.py setup-kimi --launcher --codex [--provider kimi-code]
```

This writes `claude-glm`, `claude-kimi`, `codex-glm` and `codex-kimi` (each also as `.cmd` and `.ps1`) into
`~/.ultimate-brainstorm/bin/`, and the Codex homes `~/.ultimate-brainstorm/codex-homes/{glm,kimi}/config.toml`. The
Claude launchers pass the provider settings for one session through `claude --settings <temporary file>`; the Codex
launchers set `CODEX_HOME`. Codex also keeps its own data there (sessions, history) when you use codex-glm /
codex-kimi; `uninstall --purge` moves that data to backups/. Your own `~/.claude/settings.json` and
`~/.codex/config.toml` are never changed, and keys stay in environment variables. The GLM Coding Plan may be used
only in supported tools: the kit sends GLM traffic only through Claude Code or Codex, never through Kimi Code or plain
HTTP (a separate pay-as-you-go key, `ZAI_PAYG_API_KEY`, can be enabled for HTTP). Details: `docs/FAMILIES.md`.

### 3.4 Global or per project (updated in v2)

| Component | Scope | Why |
|---|---|---|
| `ultimate-brainstorm`, routing block | user | the single owner of brainstorm requests |
| Codex CLI / Claude Code CLI / Kimi Code CLI | machine | cross-family calls |
| Kimi Code and ZCode skill copies | user (`~/.kimi-code/skills`, `~/.zcode/skills`) or project (`<project>/.agents/skills`, `<project>/.zcode/skills`) | `install.py --scope project --project-dir D`; Kimi needs a `.git` folder to find the project root |
| GLM / Kimi launchers and Codex homes | user (`~/.ultimate-brainstorm/bin`, `~/.ultimate-brainstorm/codex-homes/`) | per-session provider settings; nothing in the agents' own config files |
| grilling, domain-modeling (+ grill-with-docs, grill-me) | user | tiny; grilling and domain-modeling are model-invoked (grilling's description targets requests to stress-test a plan, decision or idea, or any "grill" phrasing; domain-modeling's targets codebase terminology, CONTEXT.md and ADRs); grill-with-docs and grill-me are user-only one-line wrappers (dependable in Claude Code; unreliable in Codex) |
| Compound Engineering | project (Local scope in a shared repo) | 36 skills crowd the skill listing; ce-ideate writes an ideation doc on every run; ce-brainstorm silently edits an existing CONCEPTS.md. User scope also works if you brainstorm in many folders; the routing block keeps it from taking over |
| claude-council | user or project | its Stop hook does nothing unless `.claude/council-stop-gate.json` enables it |
| idea-reality | local | keep disabled until Stage 7 |
| Variant modules | project | their descriptions overlap brainstorm triggers |
| Superpowers or OpenSpec | only repos that use them | one spec owner per repo |

### 3.5 Conflict settings (updated in v2)

Routing block for `~/.claude/CLAUDE.md`, `~/.codex/AGENTS.md`, `~/.kimi-code/AGENTS.md` and `~/.zcode/AGENTS.md` (or a
repo AGENTS.md plus `@AGENTS.md` in CLAUDE.md, which the Claude Code docs prefer over a symlink on Windows).
`install.py install --routing-block` inserts it between `<!-- ultimate-brainstorm:begin -->` and
`<!-- ultimate-brainstorm:end -->` markers for the agents it finds, and `uninstall` removes it:

```markdown
## Brainstorming routing (user instruction; takes precedence over skill auto-trigger rules)
- Requests to brainstorm, ideate, explore ideas, choose among ideas, name something or find a research question: use the
  ultimate-brainstorm skill (Claude Code /ultimate-brainstorm, Codex and ZCode $ultimate-brainstorm, Kimi Code
  /skill:ultimate-brainstorm) and follow its cards.
- Exception: a small, well-defined change to existing code skips it (use superpowers:brainstorming or ce-brainstorm if
  installed, otherwise proceed normally).
- While a brainstorm/<run>/ folder exists without 08_DECISION.md, do not start another brainstorming, ideation or planning
  skill (superpowers:brainstorming, ce-ideate, ce-brainstorm, office-hours, bmad-brainstorming, product-brainstorming)
  unless the current ultimate-brainstorm stage names it.
- When you are executing a single generator, judge, researcher or reviewer prompt file from brainstorm/<run>/prompts/,
  brainstorm/<run>/tournament/ or another brainstorm/<run>/ folder, follow only that prompt and ignore this section.
```

Superpowers' bootstrap ranks CLAUDE.md and AGENTS.md instructions above skills, so this block also governs it.

In Codex the kit is already explicit-only (`allow_implicit_invocation: false` in `agents/openai.yaml`), because
`codex exec` calls load the user's skills. Prefer that it never starts on its own in Claude Code either? Add
`disable-model-invocation: true` to the SKILL.md frontmatter of a copied skill (a plugin install is replaced on update).

Optional Claude Code hardening in the brainstorm project's `.claude/settings.local.json`:

```json
{
  "permissions": { "deny": ["Agent(fork)"] },
  "enabledPlugins": { "superpowers@claude-plugins-official": false }
}
```

The `Agent(fork)` deny rule is meant to stop Claude from spawning conversation forks, which inherit the whole context
(fork mode is on by default in interactive sessions; named and general-purpose subagents start fresh). This rule syntax
is unverified: check the permissions docs. The dependable protection is the skill's hard rule 3, which requires
`subagent_type: general-purpose` on every generator, judge and reviewer call. Add the `enabledPlugins` line only if
Superpowers keeps taking over brainstorm requests. Optional: an allow rule such as `Edit(/brainstorm/**)` scopes write
approvals to the run folder. In a git repo the kit writes `brainstorm/.gitignore` (`*`) when a job first reads the
repository, which keeps run files out of `git status`, commits and code searches; add `brainstorm/` to
`.git/info/exclude` (local, never committed) to hide them earlier, for example from ce-ideate's codebase scan.

| Auto-triggering component | Trigger | Control |
|---|---|---|
| Superpowers (SessionStart hook injects the "1% rule"; brainstorming says "You MUST use this before any creative work") | almost any build request | routing block; per-project `enabledPlugins` false if needed |
| ce-ideate, ce-brainstorm | "wants ideas", "brainstorm or scope what to build" | local scope, routing block, invoke as `/compound-engineering:ce-ideate` |
| bmad-brainstorming (every install route) | its description: "help me brainstorm" or "help me ideate" (auto-triggering depends on the host model matching it) | non-plugin copies: `/skills`, set to user-only (skillOverrides); plugin install: disable the plugin per project |
| idea-reality tool | its description asks for use whenever ideas are discussed | `/mcp disable idea-reality` until Stage 7 |
| naming, marketing-ideas, pm-skills brainstorm-ideas-* | naming, marketing and ideation phrases | project scope; `/skills` user-only for non-plugin copies |
| Any Codex plugin | description match | `[plugins."<plugin>@<marketplace>"] enabled = false` in the repo's `.codex/config.toml` |
| Any Codex standalone skill | description match | `[[skills.config]]` with `path` and `enabled = false`, or `policy.allow_implicit_invocation: false` in its `agents/openai.yaml` |

`skillOverrides` does not affect plugin skills: for those, disable the plugin per project. Check the skill listing with
`/skill-doctor` (Claude Code v2.1.252+) or `/context`: it is capped at 1% of the context window, and when it overflows the descriptions of the
least-used skills are dropped.

### 3.6 Do not install together

| Do not | Why |
|---|---|
| Superpowers active in the brainstorm project while another tool owns brainstorming | Competing triggers and gates; use the routing block, or disable it per project |
| Superpowers from both the official and the community marketplace | Same plugin name in two marketplaces; namespace behaviour is not documented |
| Jamie-BitFlight brainstorming-skill | Its design-gate workflow closely paraphrases Superpowers' Feb-2026 brainstorming skill (unattributed), on top of its own ideation pattern library; its trigger is an extended version of Superpowers' trigger sentence, so the two compete for the same requests |
| PAL MCP | No commits since 2025-12; fresh installs crash on MCP SDK 2.0; `consensus` is not safe under parallel calls; by default `clink`'s presets run the sub-CLIs with relaxed permissions (Codex with its sandbox bypassed, Gemini with `--yolo`, Claude with `acceptEdits`): remove those flags or use it only in trusted workspaces |
| oh-my-claudecode | Keyword hooks on every prompt (switch off with `DISABLE_OMC=1` or `OMC_SKIP_HOOKS=keyword-detector`); `omc-setup --global` overwrites `~/.claude/CLAUDE.md` by default; `/ccg` is retired |
| claude-octopus | About 37 hook scripts on 18 events; its invoke-mode router takes "ideas" and "what if" prompts |
| ECC full plugin | GateGuard denies the first Write or Edit of every file (it breaks artifact writing); 292 skills in the listing; council-multi-model is pinned to codex-cli 0.146.0 |
| gstack full install next to this pipeline | CLAUDE.md routing offer, Stop hook, colliding short names |
| claude-brainstorm-multiagent | A global SubagentStop hook writes an unread file in every project |
| LifeOS BeCreative | Only available through the full LifeOS Core install; its instructions call the Pulse voice server on localhost:31337 and write to `~/.claude/LIFEOS/` paths |
| ARIS next to another `codex` MCP server | `/aris:setup` replaces other user-scope `codex` registrations; `AUTO_PROCEED` defaults to true in its core research pipelines (idea-discovery, research-pipeline, paper-writing), so selection checkpoints report and continue unless you set `— AUTO_PROCEED: false` |
| phuryn pm-skills and deanpeters Product-Manager-Skills | Both marketplaces are named `pm-skills` |
| The Dean Peters Codex ZIP in a repo root | It ships its own top-level AGENTS.md; unzipping it into the repo root as documented can clash with or replace yours, so back up or merge first |
| mattpocock plugin and skills.sh copies; BMAD npx install and plugin route | Likely overlapping copies of the same skills; BMAD's README says to choose one install route |
| Two council skills: aiwithremy's llm-council and ngmeyer's council-review (ngmeyer/skills) | Five identical trigger phrases ("council this", "run the council", "war room this", "pressure-test this", "stress-test this"); the aiwithremy repo has no license file |
| brainstorm-mcp with default CLI auto-registration | By default (`BRAINSTORM_CLI_PROVIDERS=auto`) it registers every supported agent CLI on PATH (claude, codex, gemini, cursor-agent, opencode, qwen, kimi, droid); an API-mode debate without an explicit `models` list uses all of them as subprocess debaters, visible only in the stderr startup log and the result's Models line. Set `BRAINSTORM_CLI_PROVIDERS=off` or always pass `models`. Context and style are dropped when `participate=false` |
| Any guide that adds `codex mcp-server` | Deprecated in August 2026 and removed in September 2026 (openai/codex #39657, #42993; absent at rust-v0.156.0). Use `codex exec`, or OpenAI's Claude Code plugin openai/codex-plugin-cc (`/codex:*` commands such as `/codex:rescue`; it wraps the Codex app server, exposes no MCP tools, and OpenAI has not called it the replacement for the MCP server) |

---

## 4. The workflow, stage by stage (updated in v2)

With the kit, `ub.py` runs every stage below automatically and stops only at the questions listed in section 0; the
commands in this section show what happens underneath, and remain the manual route without the kit.

Commands below assume Claude Code as host; the Codex form follows each block. `R` is the run folder, for example
`brainstorm/2026-09-23-translator-clients`. Suggested sessions: A = stages 0-3, B (fresh) = 4, C = 5-7, D = 8-10,
E = 11-14 (Stage 14 in the target repo for software and growth; the same folder otherwise). Every stage reads and writes files,
so `/clear` (Codex: `/new`) between sessions loses nothing. `bs.py status` checks real completion (every planned
strategy file, a check per shortlisted idea, the tournament result, a probe RESULT line), so `continue` never skips a
half-done stage.

The "Time" line of each stage gives the kit's figures for that stage from `ub plan` (a standard run with claude, gpt
and kimi unless another mode is named): the model calls, the minutes they take (at most 4 at once) and their tokens.
The time you spend answering and the host's interactive skills (grilling, ce-ideate, ce-brainstorm) come on top.

### Stage 0 - Route and set up
- Goal: decide whether the pipeline is needed, create the run, detect tools and model families, set privacy.
- Run: `/ultimate-brainstorm [quick|standard|deep] [variant] <topic>` (Codex: `$ultimate-brainstorm ...`). The skill finds
  a working Python (`py -3`, then `python`, then `python3`), runs `bs.py init R` (which also writes an empty seeds
  template), checks its skill list and `codex --version` / `claude --version`, and asks two privacy questions: (a) may
  idea text go to web search and a second vendor? (b) may code facts and repo files go to a second vendor or council
  seats? In a git repo the kit writes `brainstorm/.gitignore` (`*`) itself when a job first reads the repository (you
  can add `brainstorm/` to `.git/info/exclude` to hide run files earlier); for a new product with no repo it suggests
  `mkdir <slug>; cd <slug>; git init` and relaunching there (never commit). Codex host: it checks `web_search = "live"`
  and suggests approving the nested-CLI command prefix for the session.
- Variants: software, product, growth (activation, onboarding, conversion, retention or churn of an existing product),
  research, marketing, creative, naming, general.
- In -> out: topic -> `R/00_RUN.md` (mode, variant, families, privacy (a) and (b), Python command, detected tools,
  strategy -> family map, session plan).
- Checkpoint: confirm mode, variant and privacy. Reply `go`, a setting on a line of its own (`deep`, `hands-on`,
  `private`, `web: no`), your seed ideas one per line, or `no seeds, go`. A line that reads as a privacy wish (`only
  use Claude`, `keep it confidential`, `no web search`) or a setting in a sentence (`Quick mode is enough for me`) is
  asked again rather than sent to the vendors as an idea; as a list item (`- a Claude plugin for nurses`) it is a seed,
  while `- web: no` stays a setting. `Don't start yet`, two modes (`standard and deep`) and a line meant for another
  checkpoint (`publish all, ce`) are asked again.
- Time: about 2 minutes: one preflight ping per family (and one web-search probe for Codex).
- Fallback: small, clear code changes are routed to `superpowers:brainstorming` (Spike or Bounded) or `ce-brainstorm`
  (Lightweight) instead.

### Stage 1 - Sealed human seeds
- Goal: the human's own ideas exist before any AI idea is visible.
- Run: the skill shows the absolute path of `R/00_HUMAN_SEEDS.md` and asks you to spend 10 minutes alone filling it
  (Problem, optional Primary idea to pressure-test, Ideas, Obvious, Off-limits). A primary idea is always carried to the
  screen shortlist and the tournament finals. Teams write one file per person without talking. Deep: a BMAD Facilitator
  session (`/bmad-brainstorming`, Codex `$bmad-brainstorming`), whose memlog idea lines are imported (Facilitator mode
  logs the user's ideas as `(idea)`; Creative Partner mode as `(idea by user)`).
- Out: `00_HUMAN_SEEDS.md`.
- Checkpoint: the Ideas or Primary idea section is filled. `SKIP-SEEDS` is allowed and recorded. A `--seeds-file`
  without these sections (an idea list, free text, `###` headings) is kept: its text goes under Ideas, or under the
  section its heading names.
- Time: 10 minutes of human time (deep 20-40), almost no tokens.

### Stage 2 - Frame (question-only)
- Goal: job statement, problem, audience, measurable success, hard and soft constraints, non-goals, decision ledger,
  premises, kill condition for the whole effort, 3-5 weighted criteria with 1/3/5 anchors, 3 axes, strategy plan.
- Run: with grilling installed, the skill runs it with "problem only; no solutions even in recommended answers; at most 3
  rounds". In software and growth runs it loads `grilling` and `domain-modeling` together (P-GRILL-DOCS, the pair
  `grill-with-docs` wraps; section 2.4), in the main conversation with plan mode off (plan mode also blocks the
  CONTEXT.proposed.md writes): your terms are checked against `CONTEXT.md` (at most 5 resolved, only those the frame
  needs), vague words get one canonical term, edge cases are asked about today's behavior only, claims are checked
  against the code (file:line), relevant ADRs are classed as gate or reopenable, and resolved terms go to
  `brainstorm/<run>/CONTEXT.proposed.md`, not to the repo. The skill snapshots `CONTEXT.md` first and afterwards checks
  with `git status` that `CONTEXT.md`, the CONTEXT-MAP contexts and `docs/adr/` are unchanged. It then asks the questions grilling does not cover (how are we part of the problem, who benefits if it is never
  solved, whether a named solution type is a constraint or a hypothesis, the variant add-ons, STATED vs ASSUMED),
  presents criteria, anchors and axes as defaults to confirm, and writes the FRAME. Otherwise its built-in
  frontier-round interview. In both paths, variant questions come from `references/variants.md` (startup forcing
  questions, one per message and exempt from the round cap; growth baseline questions; research observation freeze;
  creative and naming briefs). Success must name a baseline number and its source, or be marked NOT VERIFIED.
- Out: `01_FRAME.md`, `criteria.json` (default: Value 30, Feasibility 25, Fit 20, Distinctiveness 15, Evidence 10); in
  software and growth also a "Domain language" section in the FRAME (terms inline, relevant ADRs, code contradictions),
  `CONTEXT.before.md` (a safety snapshot) and `CONTEXT.proposed.md` when any term resolved. Stage 3 copies up to 12
  relevant terms into FACTS as a description of today's system; generators may break them.
- Checkpoint: confirm STATED vs ASSUMED, the FRAME and the proposed terms.
- Time: the interview is your time (grilling runs 1 round in guided mode and up to 3 in hands-on; software and
  growth add glossary reads and code checks). Without grilling the kit's express path makes 2 model calls: about 2-7
  minutes, 8-19k tokens.
- Fallback: without grilling, the built-in P-FRAME interview. Do not run Stage 2 in plan mode (Claude Code plan mode or
  Codex `/plan`).

### Stage 3 - Ground
- Goal: shared FACTS; a LANDSCAPE of existing solutions, where incumbents fail, and mechanism analogues from distant
  fields; a dated search boundary.
- Run: one researcher subagent with the P-GROUND prompt (deep: both families, merged).
- Out: `02_CONTEXT.md` (A FACTS, B LANDSCAPE, C SEARCH BOUNDARY). Labels: FACT (source), INFERENCE, ASSUMPTION;
  "not located within this search" instead of "does not exist".
- Growth: you paste or export funnel counts (signup to activation, last 4-8 weeks), or an authenticated analytics MCP is
  queried; the researcher also lists uninstrumented funnel steps and walks the first-session code path.
- Software and growth: section A2 DOMAIN TERMS (today's system) holds at most 12 terms from the FRAME, headed by a note
  that ideas may split, merge, rename, redefine or remove them; code contradictions and relevant ADRs become FACTs. With
  privacy (b) = no, the other family gets only the terms you confirmed at Stage 2, not text from the repo's CONTEXT.md.
- Time: 1 model call (deep 2), about 4-10 minutes (deep 8-20), 6-14k tokens (deep 13-29k).
- Fallback: privacy (a) = no means local sources only.

### Stage 4 - Diverge (isolated strategy portfolio)
- Goal: many ideas from structurally different strategies that never see each other, across two model families.
- Run (fresh session): you type `/ultimate-brainstorm continue <run>` (Codex: `$ultimate-brainstorm continue <run>`);
  the orchestrator invokes ce-ideate through the Skill tool (Codex: by following its SKILL.md); ce-ideate's final menu
  then needs you; after that the orchestrator resumes with S2-S5.
  - S1: ce-ideate with the focus text `<problem>. Treat brainstorm/<run>/01_FRAME.md as the directive brief. Do not read anything else under brainstorm/. The folder brainstorm/ is not part of the codebase: exclude it from codebase scans and grounding. Do not print the ranked list in chat; write it only to the file. output:md`
    (deep adds `go deep`; privacy (a) or (b) = no adds `no external research`). ce-ideate may still print its ranked
    survivors, so answer its menu without reading the list; the skill records `human saw S1 ranking: yes/no`. At the
    menu, ask in free text for the absolute paths of the ideation doc and `raw-candidates.md`; the skill copies both into
    `pool/`, then you reply `discard` (ce-ideate deletes the doc only if this run created it), or choose Done and decline
    the commit offer. Without CE: a built-in frame fan-out (pain, leverage, automation/removal).
  - S2 Verbalized Sampling ladder and S4 cross-domain transfer: host subagents (`subagent_type: general-purpose`).
  - S3 enumerate-diversify-elaborate and S5 provocation operators: the other family, run from an empty folder outside
    the repo so the generator cannot browse `brainstorm/`, one call per Bash call with a 10-minute timeout, for example
    `codex exec -C "<abs empty dir>" --skip-git-repo-check --sandbox read-only --ephemeral -o "<abs R>/pool/S3_enumerate.md" - < "<abs R>/prompts/S3.prompt.md"`.
  - Deep adds S3 with 100 titles, LENS L1-L6 (JSON with `draft_titles` and `bolder_titles` via `--output-schema`),
    and the lateral-thinking skill if installed.
- Out: `pool/S1_ce-ideate.md`, `pool/S1_ce-ideate_raw.md`, `pool/S2_vs.md`, `pool/S3_enumerate.md`, `pool/S4_transfer.md`,
  `pool/S5_operators.md` (plus `L*.json` in deep). `bs.py status` requires a file for every strategy in the 00_RUN.md map.
- Checkpoint: none. The human stays out until the map.
- Time: 5 model calls (the built-in S1 frame fan-out plus S2-S5; deep 11), run in parallel: about 4-10 minutes (deep
  8-20), 49-112k tokens (deep 108-246k). ce-ideate as S1 comes on top: it reads roughly 30k+ tokens of instructions and
  runs about a dozen or more subagents on a default repo run (our estimate; CE prints the actual cost line before
  dispatching).
- Codex host: S2 and S4 run as Codex subagents (each spawned as a new agent with no conversation context); S3 and S5 run
  through `claude -p` (approve the network escalation):
  `cat "<abs R>/prompts/S3.prompt.md" | claude -p "Follow the instructions in the piped input exactly. Print only the requested output." --output-format text --no-session-persistence --tools "" --disallowedTools "mcp__*" > "<abs R>/pool/S3_enumerate.md"`.
  PowerShell on native Windows (not from the Claude docs; test it once):
  `$OutputEncoding = [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()` then
  `Get-Content -Raw -Encoding UTF8 "$R\prompts\S3.prompt.md" | claude -p "Follow the instructions in the piped input exactly. Print only the requested output." --output-format text --no-session-persistence --tools= --disallowedTools "mcp__*" | Out-File -Encoding utf8 "$R\pool\S3_enumerate.md"`
  (same for S5 with `S5.prompt.md` and `S5_operators.md`).
  No second vendor: S3 and S5 run on the `bs-alt` custom agent (or `codex exec -m <alt>`) and are labeled PROVISIONAL.

### Stage 5 - Merge, map, gap rounds, human round 2
- Goal: one deduplicated, mapped pool with honest yield numbers, holes filled, and a second human round.
- Run: the curator subagent gives every raw idea an alias ID, merges only same mechanism keys (`<actor> | <verb + object>
  | <outcome>`), clusters by mechanism, assigns each idea an axis cell, runs a leak check on S1 and marks BASELINE and
  PRIMARY ideas, writing `merges.json` and `03_POOL_NOTES.md`. Then `bs.py map R` does the bookkeeping an LLM gets
  wrong: random neutral IDs `I-###`, origins, yield per strategy, the coverage grid, the HOMOGENIZED alarm (largest
  cluster above 25%) and the covered share of the axis cells. Gap round when the alarm fires or fewer than 80% of the
  cells hold an idea: one
  cell-targeted generator per chosen cell (max 6: empty cells next to populated clusters first, then cells you marked,
  skipping combinations the FRAME rules out; alternating families; "do not reinterpret the cell; output TENSION if it is
  incoherent") plus one landscape-aware REOPEN generator that must do what existing solutions cannot.
- Out: `merges.json`, `03_POOL.md`, `clusters.json`, `origins.json` (human, human-mixed, claude, gpt, ai-mixed, or
  `gpt-alt` / `claude-alt` for a same-vendor substitute), `primary.json`, `ideas.json`, `screen/ideas.md`.
- Checkpoint: you see every cluster (unranked), the empty cells and a 5-line landscape summary, and may add
  `00b_HUMAN_ROUND2.md` aimed at gaps and at what incumbents cannot copy.
- Time: 1-9 model calls (the curator, then per gap round up to 6 cell generators, a REOPEN generator and a curator
  pass; deep 1-19), about 9-21 minutes (deep 11-26), 29-291k tokens (deep up to 560k).

### Stage 6 - Two-family absolute screen
- Goal: cut to at most 12 without losing diversity.
- Run: `bs.py schemas R`, write `screen/header.md`, `bs.py prepare-screen R` (a different shuffle per family), host
  judge subagent plus `codex exec --output-schema R/screen/screen.schema.json ...`, then `bs.py screen R`.
- Out: `screen/table.md`, `screen/shortlist.json`, `04_SHORTLIST.md`: gates (KILL only when at least two judges scored
  the idea and all of them failed the same gate; a single failing judge only flags), K3 floor, weighted score, rank range
  under +/-25% weights, best idea per cluster (max 10) + the most distinctive still-feasible idea + the best idea with a
  human seed behind it + every primary idea. `04_SHORTLIST.md` ends with a `Rescued: <IDs>` line (IDs only) and a
  `- <ID>: <reason>` line per rescue. Every judge's scores count; a judge's preference for
  its own vendor's ideas is measured against another judge on the ideas neither vendor wrote and taken off its
  own-vendor scores when it is larger than its noise (1.5 standard errors of the per-idea differences; a smaller gap
  is reported, not corrected), after centering each judge on the ideas no
  judge's vendor wrote, so it does not decide a cluster. With two judge families and fewer than 3 ideas that neither judge's vendor
  wrote (no human or merged ideas), that preference cannot be told from leniency and nothing is corrected: the screen
  reports the pair's combined gap under `## Own-origin gap` in `04_SHORTLIST.md` (WARN above 0.5; the G4 card repeats
  every WARN and FLAG), and the tournament and your G4 review decide.
- Quick mode has a short version of this screen: after the curation, the two families that generated the ideas both
  score the curated one-line versions blind (no source labels, each in its own order), with 3 or more families also a
  third family that generated nothing (one more call; it lets each generator family's preference be measured and
  corrected without human ideas), and the finalists come from their scores with the same own-origin correction. With one model family there is no second scorer, so the curator's
  own scores pick the finalists and the run says so (quick/finalists.json `scoring: curator`, a run note, and
  quick/screen.md).
- Checkpoint: rescue up to 2 ideas with a reason; confirm flagged gates.
- Time: 3 judge calls (one per screen judge family), about 1-4 minutes, 25-58k tokens.
- Codex host: the host judge is a Codex subagent and the other judge is `claude -p` ("Output only the JSON object").
  No second vendor: Codex-only sends the `claude.*` file to `bs-alt` (read 'claude' as 'alt'); Claude-only uses a
  different-model subagent; both are labeled PROVISIONAL. No Python: the host applies the same rules by hand
  (error-prone).

### Stage 7 - Reality checks
- Goal: evidence-based prior art and falsifiable risks per shortlisted idea.
- Run: researcher subagents (3 ideas each) with the CHECK prompt; from Claude Code, Claude-origin ideas are checked by GPT
  (`codex exec -c web_search=live ...`; the override is likely but not confirmed). Developer tools: enable idea-reality
  and call `idea_check` with depth "deep" on two paraphrases; the released 0.5.0 counts failed sources as 0, so a low
  score means unknown. ML research: `/aris:novelty-check "<idea>"`.
- Out: `checks/<ID>.md`: verdict CROWDED / ADJACENT / NOT LOCATED with named matches, differentiator, steelman, OBSERVED /
  NOT VERIFIED claims, up to 3 "Fails if" kill-assumptions with cheapest test and kill criterion; software and growth
  add a codebase-fit item (does the product already do this, file:line; conflicts; files that would change).
- Checkpoint: confirm every K4 kill. Growth (and software ideas for an existing product): K4 does not apply, because
  prior art is evidence the idea works; kill only if our product already shipped and measured it.
- Time: 4-12 checker calls (one per shortlisted, rescued or primary idea), about 5-13 minutes, 22-154k tokens.
- Codex host: checks stay on Codex subagents, which can use web search if it is enabled for the session
  (`web_search = "live"` for live results; the default is cached). A `claude -p` checker has no web tools.
  privacy (a) = no: the verdict is "NOT CHECKED" and cannot trigger K4.

### Stage 8 - Evolve
- Goal: add up to 4 (deep: 5) variants that must win on merit.
- Run: standard runs it only when fewer than 6 ideas survive or you ask; deep always. Evolved ideas get their own checks.
  Evolved ideas inherit their parents' screen score; with more than 8 ideas in the pool, at least two evolved ideas
  (best CHECK verdict first) reach the finalists.
- Out: `05_EVOLVED.md` (or "skipped").
- Time: standard usually skips it; deep 0-6 calls (the evolve call plus a check per evolved idea), about 4-12 minutes,
  up to 86k tokens.

### Stage 9 - Tournament
- Goal: a debiased ranking of up to 8 finalists: one Bradley-Terry fit on one share per pair (self-interested verdicts
  left out), with 90% intervals, a Condorcet winner and majority cycles reported; raw points when no bias-free
  comparison connects the finalists.
- Run: primary ideas are always finalists; normalizer writes `tournament/cards.md`; you write a gut top 3 into
  `tournament/precommit.md` before any judge runs; `bs.py prepare-tournament R` (deep with 6 or fewer finalists:
  `--per-pair`); judge every prompt file (host family: fresh subagents; other family: `codex exec --output-schema`, one
  call per Bash call); `bs.py tournament R`.
- Out: `tournament/result.md`, `06_TOURNAMENT.md` (pre-commit copied in): standings (a family's point counts only if its
  verdict survives the order swap), contested pairs, position consistency per judge family (below 60%: discount),
  self-preference audit (own-family win share more than 15 points above the other judge: discount; skipped when the
  second judge is a same-vendor substitute).
- Checkpoint: standings next to your pre-commit; you pick 3-4 for the red-team and decide contested pairs.
- Time: 7 calls (the normalizer and 6 judge prompts: 3 judge families x 2 orders), about 4-11 minutes, 59-134k
  tokens. Deep per-pair mode makes 2 x F x C(n,2) judge calls: 90 for 6 finalists and F = 3 judge families (deep
  7-91 calls, about 18-43 minutes).
- Codex host: Codex subagents judge the `gpt_*` files, `claude -p` calls judge the `claude_*` files. No second vendor:
  Codex-only sends the `claude_*` files to `bs-alt` (fallback: `codex exec -m <another model>`); Claude-only uses a
  subagent on another model family alias; both are labeled PROVISIONAL, and `result.md` notes that 'claude' means 'alt'.

### Stage 10 - Red-team and decision
- Goal: stress-test the top 3-4 across families, then decide.
- Run: the orchestrator writes a one-line pre-commit per idea; an ADVOCATE and a CRITIC from different families review each
  idea independently (steelman, OBSERVED claims, "Fails if" with cheapest test, the premise most likely wrong, the 48-hour
  test, verdict); optionally one rebuttal round; optionally claude-council seats:
  `/claude-council:ask --file=brainstorm/<run>/07_TOP.md --debate --roles=devil,simplicity --no-auto-context --output=brainstorm/<run>/redteam/council.md "<question>"`.
  You see every raw verdict line, then the synthesis (recommendation, tradeoffs, strongest disagreement, what everyone
  missed, the untested shared premise, a 3-cause pre-mortem). Deep: forge the top 3 with bmad-forge-idea or the built-in
  FORGE prompt.
- Out: `07_REDTEAM.md`, `08_DECISION.md` (chosen, or for growth an optional bundle of 2-4 ideas with a test order;
  runner-up, parked with revisit trigger, killed with K-rule, dissent, Not doing, and a pointer to the test that Stage 11
  pre-registers in `09_PROBE.md`), rows in `brainstorm/LEDGER.md`.
- Checkpoint: the human decision.
- Time: 8-10 calls (pre-commit, an ADVOCATE and a CRITIC per red-teamed idea, synthesis; deep adds the rebuttals:
  14-18), about 8-21 minutes (deep 13-30), 66-179k tokens (deep 104-294k), plus your decision.
- Codex host: the Claude reviewer runs through `claude -p` without web tools (its claims stay NOT VERIFIED);
  claude-council runs through its direct scripts (section 5.3). Codex-only: ADVOCATE = host subagent, CRITIC = `bs-alt`
  (PROVISIONAL); for real cross-vendor critique, run claude-council's direct script with non-OpenAI seats only
  (`--providers=gemini,perplexity`). Skip claude-council for creative topics: its provider prompt is framed for
  software. Keep `--no-auto-context` when privacy (b) = no.

### Stage 11 - Probe
- Goal: try to falsify the riskiest assumption before committing.
- Run: a two-week walk-through (deep: 10 working days, day by day), riskiest assumption = highest criticality x
  uncertainty, the cheapest probe with the pass threshold, sample and deadline written first. Software: a spike in
  `git worktree add ../<repo>-spike -b spike/<slug>` (you install dependencies and copy local env files into the
  worktree, or run the spike behind a feature flag in a scratch branch). Growth: a feature-flagged experiment on the
  units entering the target window (new signups for activation, teams reaching day 30 for second-month churn) with
  metric, baseline, minimum detectable effect, sample size per arm, duration and guardrails written first (over 4
  weeks: a leading indicator measurable within 4 weeks, or for activation a moderated 5-user first-session test or a
  fake door). Product: an XYZ pretotype via pm-skills (B2B: 8-12
  problem interviews, a concierge pilot or LOIs; "demand unverified": interviews first). Research: a pilot with a
  written decision rule. Creative: a 24-hour re-read and 5 target-audience reactions.
- Out: `09_PROBE.md` (plus a pointer line in `08_DECISION.md`); after you report, `## Result` and
  `RESULT: PASSED | MISSED (K6) | INCONCLUSIVE`.
- Checkpoint: run it and report. Missed threshold: K6, the runner-up goes through the probe; with no runner-up left
  the run stops before the architecture (a finished run says so on its documents, handoff seed, published copies
  and DONE card: its status banner reads KILLED (K6)), and you switch to another finalist (`switch` refuses an idea its own probe killed).
  INCONCLUSIVE never counts as a pass: extend the test or run the qualitative test.
- Time: 1 call to design it (about 4-10 minutes, 16-37k tokens); hours to 2 weeks to run.
- Codex host: run the spike with `codex exec --sandbox workspace-write -C ../<repo>-spike -o <absolute run path>/09_SPIKE.md - < <spike prompt>`;
  never merge the spike branch.

### Stage 12 - Architecture (updated in v2)
- Goal: turn the decided idea into a reviewed architecture package without reopening the decision.
- Run: a script freezes the brief from `01_FRAME.md` (job, audience, success, constraints, non-goals), `08_DECISION.md`,
  the chosen idea's check, the red-team kill-assumptions, the probe's riskiest assumption and the privacy flags.
  ARCH-DRIVERS (host family) turns it into 3-5 quality goals with weights summing to 70 (a fixed 30 goes to time to MVP
  10, team fit 5, run cost 5, reversibility 5, operational simplicity 5), 5-10 quality scenarios and the system context;
  missing facts are tagged `[ASSUMPTION]`. Then K independent architects (2 quick, 3 standard and proposal, 4 deep),
  from different families where possible, each design one candidate from the same brief with an archetype seed: A boring
  by default (a modular monolith on managed services, at most 3 innovation tokens), B variant-specific (local-first when
  privacy-heavy, buy-and-integrate when the budget is tight, otherwise event-driven / serverless), C the approach the
  others would not pick, D cost-minimal (deep). Software and growth use A = smallest change to the current architecture
  (citing files) and B = one new bounded component. Candidates get random neutral labels; judge sheets are rendered by
  script from each candidate's JSON (no archetype or family names), and judges (families that authored nothing, plus the
  host when two or more families authored nothing; otherwise every family) score every candidate on every criterion 1-5
  (a judge's score of its own family's candidate counts only when no other family's judge scored it, or in the balanced
  two-family design) and may veto on a hard constraint (2 vetoes exclude, 1 flags). `bs.py arch-matrix` centers each
  judge on its own mean, computes weighted scores, rank ranges under +/-25% weights, disagreements, a clear, close-call,
  confounded or self-judged leader and a steal list. A pre-mortem by another family names 5 causes of failure. After
  your choice the writer family produces the package; ADRs (MADR 4.0, status proposed), risks and technical debt are
  rendered by script from JSON; STACK-VERIFY looks up every version on the web (UNVERIFIED otherwise); `bs.py lint-arch`
  checks files, placeholders, ADR format, versions, mermaid, traceability and cost; review lenses from other families
  (web-verified tech and a divergence adversary; deep adds failure modes with prior art, and security and privacy) feed
  one fix pass.
- Out: `10_ARCHITECTURE/` with `00_BRIEF.md`, `drivers.json`, `goals-constraints.md`, `quality-scenarios.md`,
  `context.md` (C4 context plus a flowchart), `candidates/`, `review/`, `tradeoff-matrix.md`, `premortem.md`,
  `chosen/` (containers, runtime flows with failure and recovery, data model, API, deployment, security and privacy,
  cost model, deferred decisions, stack), `adr/NNNN-*.md`, `risks.md`, `lint.md` and a `README.md` with the decision
  index and provenance (authors revealed, judges, PROVISIONAL badges).
- Checkpoint: G11, the architecture choice: reply `ok` (the suggestion), a letter, or a letter plus elements to steal
  (`B+steal`). One chosen letter counts whatever you say of the others (`Not A. B.`, `C please, A looks too complex`);
  two chosen letters, a hedge (`maybe B`) or a question (`Should I pick B?`) are asked again. Families are revealed
  only after the choice. Hands-on and deep also confirm the drivers (G10) and each
  ADR (G12); guided bundles ADR acceptance into the sign-off.
- Quick: lite path with 2 candidates (A and C), 1 judge, an automatic leader (switchable at sign-off; hands-on and
  guided runs are asked when a judge vetoed the leader or its lead is self-judged or confounded), one package call,
  versions left UNVERIFIED, a lite lint and no review. With 2 families the one judge is your host's family, which also
  wrote one of the two candidates: that candidate is scored by its own family only, the lead is marked self-judged, and
  G11 asks you (hands-on and guided) instead of taking the leader silently.
- Research, marketing, creative and naming runs (build type `approach`) write `10_ARCHITECTURE/approach.md` instead
  (research: hypotheses and rival explanations, design, measures, analysis plan with a decision rule; marketing and
  creative: channels, assets, production, measurement, budget; naming: rollout, availability and trademark checks), with
  one review lens and no G11.
- Time: 15 calls in standard (deep 19, quick 5), about 28-64 minutes (deep 32-75, quick 14-35), 215-491k tokens
  (deep 269-614k).

### Stage 13 - Proposal (updated in v2)
- Goal: a cited proposal that a decision-maker can act on, plus a one-pager, without new claims.
- Run: `bs.py sources` gives every URL a stable `S-###` id. Three writers (drafter = host family) work in parallel from
  evidence packs: sections 2-5 (problem, solution, users and market, differentiation vs prior art), 6-9 (architecture
  summary, scope and MVP, roadmap, team and effort) and 10-13 (budget, risks, success metrics and validation, open
  questions); then the executive summary and `ONE-PAGER.md`. A script assembles `PROPOSAL.md` with a status banner and
  appendices A-F (ADR index, assumptions index, candidate comparison, idea selection record with the audits, glossary,
  sources) and runs `bs.py assumptions` and `bs.py lint-proposal`. Rubric judges from other families score 7 criteria
  and list must-fix items; a red-team from a non-drafter family attacks the claims; one fix pass answers every item as
  ADDRESSED, ACCEPTED-RISK (moved to the risks section) or REJECTED with a reason, and keeps `ONE-PAGER.md` in line with
  the sections. When a lint FAIL, or a figure or date that differs between the one-pager and the proposal (P11), is
  still left, a second fix pass runs; whatever remains is listed on the G13 card. `ub render` builds the single-file
  `index.html` pack (table of contents, diagrams, ADR cards, print styles).
- Rules in every proposal prompt: use only facts from the pack and cite them `[S-###]`; every unsourced number, market
  or competitor claim carries `[ASSUMPTION: ...]` or `[ESTIMATE: range; basis]`; never invent customers, quotes, metrics
  or moats, and never use the word "novel"; never change an architecture decision, only summarize it; say what is not
  being done. The roadmap starts with Milestone 0 = the pre-registered probe with its kill criterion, and every open
  question has an owner and a decide-by milestone (all checked by lint).
- Out: `11_PROPOSAL/PROPOSAL.md`, `sections/`, `ONE-PAGER.md`, `assumptions.md`, `open-questions.md`, `review/`,
  `lint.md`, `index.html` (deep: `PRFAQ.md`); `ub export --format docx` uses pandoc when it is installed.
- Checkpoint: G13, sign-off: `approve` (the proposal becomes Approved and the ADRs accepted), `changes: ...` (at most two
  loops), `switch B` (another architecture, from the package step) or `runner-up` (the runner-up idea, from its own
  probe at Stage 11). The card shows the step each of those two redoes from and about how many requests it costs.
  `approve it`, `I approve`, `sign off`, `sign it off` and `Looks good, thanks` approve; `Please fix the proposal` is a
  change round; `use B instead` switches and `switch to the runner-up` is `runner-up`. A reply the engine cannot read
  one way (`ok, but shorten section 4`, `approve and publish`, `switch to a simpler architecture`, `Switch to B? Costs
  matter more`, `switch B / runner-up`), that says no change (`stop`, `not
  yet`, `Great work`) or that is not yet a decision (`Should I switch to B?`, `Let me think about it overnight`) is
  asked again with the reason, never taken as a change round. Full-auto leaves it a DRAFT with the AUTOPILOT banner.
- Quick: one PROPOSAL-LITE call (sections 1, 2, 3, 6, 7, 11, 12, 13 and the one-pager), one rubric family, no red-team.
- Time: 8 calls in standard (deep 9, quick 2), about 14-34 minutes (quick 5-14), 153-349k tokens.

### Stage 14 - Handoff (updated in v2)
- Goal: turn the decision into the next artifact without reopening it.
- Domain docs first (software, growth; before any handoff): if `CONTEXT.proposed.md` exists, the skill re-reads the
  current `CONTEXT.md`, marks each proposed term KEEP (still true under `08_DECISION.md`), CHANGED BY DECISION (old and
  new definition shown) or MEASUREMENT, and asks: merge all, some, defer, or none. Only after your answer does
  `domain-modeling` merge the chosen terms into the right `CONTEXT.md` (per context when `CONTEXT-MAP.md` exists). ADR
  candidates (ADR-CANDIDATE rows in the FRAME's Decision ledger plus decisions in `08_DECISION.md` that pass its three
  gates: hard to reverse, surprising without context, a real trade-off) are asked about one by one; zero ADRs is normal.
  The outcome is recorded in `00_RUN.md` and `12_HANDOFF.md`. Nothing is committed.
- Publish (G14, all modes but full-auto): on your yes, each copy goes into `docs/<run>/`, with the run's own layout:
  `architecture` copies `10_ARCHITECTURE/` (with its ADRs) to `docs/<run>/10_ARCHITECTURE/`, `adr` copies only the
  ADRs, and `proposal` copies `11_PROPOSAL/` to `docs/<run>/11_PROPOSAL/` together with the ADRs it links to. Each
  copy needs its own yes. The files are copied byte for byte, so every link in them (the decision index, Appendix A,
  `index.html`) resolves just as in the run folder. Only `docs/<run>/` is written: two runs never mix, your own
  `docs/adr/` log is never touched, and two runs can publish at the same time. Publishing again is safe: unchanged
  files are left alone, a file it replaces goes to `_superseded/<stamp>/published/` first, and a file the run no
  longer has (the old ADRs after `ub switch --arch`, say) moves there too, once you publish every copy again (with a
  partial answer it stays, so no copy loses a file it links to). Files you add to `docs/<run>/` yourself stay. What
  was published is recorded in `brainstorm/<run>/handoff/published.json`, so an interrupted publish just runs again
  (on a Linux or macOS disk without hard links, such as exFAT, a publish interrupted while it claims `docs/<run>/`
  leaves an empty claim, which the same run takes over a minute later). If `docs/` or `docs/<run>/` is a link or junction, nothing is written through it: the card says what to move aside,
  then `redo <run> 14.2` asks G14 again. Copies made by kit 2.0.x (`docs/architecture/`, `docs/adr/`,
  `docs/proposal/`, `docs/<item>/ub-<run>/`) are left as they are and no longer updated; the card names them so you
  can move or delete them. Without `RESULT: PASSED` in `09_PROBE.md` the card warns "riskiest assumption untested"
  and the seed carries that warning.
- Reply: `publish` (or `publish all`, `publish architecture`, `publish architecture, proposal`) or `no`, and one
  handoff (`publish all, speckit`, `no, none`). Other words are read back before anything is copied: `publish all but
  the proposal` and `publish everything, keep the proposal private` read as the architecture and the ADRs, `No
  publishing. Spec-Kit please.` as nothing published with the Spec Kit handoff. A software or growth
  run asks which handoff when the reply names none; `yes` alone, a question (`publish?`), a condition (`publish the
  architecture if the tests pass`) or a keep that names nothing (`publish it but keep it private`) is asked again, and
  `I'll publish it myself` publishes nothing.
- Seed: the kit writes the handoff seed: CE (default for software and growth), Spec Kit for greenfield projects
  (`specify init <proj> --integration <agent>`, then `/speckit.specify` with PROPOSAL sections 3 and 6-8 and
  `chosen/`), Superpowers or OpenSpec only in repos that already use them. The CE seed adds "Architecture decisions:
  brainstorm/<run>/10_ARCHITECTURE/README.md (ADRs accepted). Milestone 0 (09_PROBE.md) runs first; do not plan beyond
  its kill criterion." Every seed ends with "Do not reopen the choice of idea or architecture." Once the chosen
  idea's probe missed with no runner-up left, `12_HANDOFF.md` ends with a K6 warning instead (do not build this
  idea; switch to another finalist first), and the seed is written again with it, without the closing line.
- Run (fresh session in the target repo): `/compound-engineering:ce-brainstorm <seed>` then "Create the implementation
  plan" (Codex: `$ce-brainstorm <seed>`); Superpowers or OpenSpec in repos that use them; a one-pager otherwise. If you
  declined the terms, the seed tells ce-brainstorm not to copy them into any repo doc.
- Out: `12_HANDOFF.md` (what went to which tool, with paths), LEDGER rows, the downstream spec or plan (CE: `docs/plans/YYYY-MM-DD-HHMM-<type>-<topic>-plan.md`); on your
  yes, updated `CONTEXT.md` and any ADRs in `docs/adr/`.
- Time: no model calls by the kit (the seed is written by script); the handoff session is yours: ce-brainstorm reads
  roughly 35-45k tokens of instructions on Standard or Deep runs (our estimate).
- Fallback: without CE, use the repo's Superpowers or OpenSpec prompt from section 5.3 (the Codex Superpowers copy is
  v6.3.0, so keep "Stop after the spec for my review"), or the one-pager.

---

## 5. The handoff contract

### 5.1 Folder layout

```
brainstorm/
  LEDGER.md                    cross-run log: date | run | id | title | status | reason / K-rule | revive trigger
  <YYYY-MM-DD>-<slug>/
    00_RUN.md                  mode, variant, families, privacy (a)/(b), python, detected tools, strategy->family map,
                               human saw S1 ranking, stage log
    00_HUMAN_SEEDS.md          sealed human round, incl. optional Primary idea (team: 00_HUMAN_SEEDS_<name>.md)
    00b_HUMAN_ROUND2.md        human round after the cluster map
    01_FRAME.md  criteria.json
    CONTEXT.before.md          software/growth: snapshot of CONTEXT.md taken before Stage 2 (a safety copy)
    CONTEXT.proposed.md        software/growth: terms resolved in Stage 2 (tagged NEW / CHANGED / MEASUREMENT); merged at Stage 12 on a yes
    02_CONTEXT.md              A FACTS | B LANDSCAPE (B1 solutions, B2 where incumbents fail, B3 analogues) | C SEARCH BOUNDARY
    prompts/                   one filled prompt per generator, checker or reviewer call; lens.schema.json
    pool/                      S1_ce-ideate.md, S1_ce-ideate_raw.md, S2_vs.md, S3_enumerate.md, S4_transfer.md,
                               S5_operators.md, G*.md (gap), R*.md (reopen), L*.json (deep), IMPORT_*.md
    merges.json  03_POOL_NOTES.md   curator output (merges, clusters, cells; RE-RUN, leak check, merge log)
    03_POOL.md  clusters.json  origins.json  primary.json   written by bs.py map
    screen/                    ideas.md, header.md, *.prompt.md, *.out.json, screen.schema.json, table.md, shortlist.json
    04_SHORTLIST.md
    checks/<ID>.md
    05_EVOLVED.md
    tournament/                cards.md, precommit.md, header.md, *.prompt.md, *.map.json, *.out.json,
                               verdicts.schema.json, result.md
    06_TOURNAMENT.md           human pre-commit, standings, contested pairs, audits
    07_TOP.md  redteam/  07_REDTEAM.md
    08_DECISION.md
    09_PROBE.md                pre-registered test; later "## Result" and a RESULT: line
    10_HANDOFF.md
    logs/                      stderr of CLI calls
```

### 5.2 Formats that other tools read

- Idea block (every generator): `### <P>-NN <title>` with Pitch, Mechanism, For whom / when, Basis
  (`direct:` / `external:` / `reasoned:`, the CE convention), p (verbalized probability), Cell, Fails if.
- Screen line (`screen/ideas.md`): `I-### | title | pitch | mechanism`, neutral, no origin hints.
- Card (`tournament/cards.md`): `## <ID>` then Title, Problem, Mechanism, For whom, First version, Main risk, Prior art.
- Alias IDs (curator): `<P>-NN` for generator blocks, `S1-NN` / `S1R-NN` for ce-ideate ideas and raw candidates,
  `L<k>-NN` for LENS, `IMP-NN` for imports, `H-NN` / `HP-NN` / `H2-NN` for human seeds, primary ideas and round 2.
- Origins (`origins.json`, computed by `bs.py map`): `human`, `human-mixed`, `claude`, `gpt`, `ai-mixed`, or
  `gpt-alt` / `claude-alt` for a same-vendor substitute. Only `human` and `human-mixed` can take the protected human
  slot; `primary.json` lists the ideas that always reach the shortlist.

### 5.3 Exact prompts and commands between tools

Dispatch to the other family:

```bash
# From Claude Code (GPT); generators and judges run from an empty folder outside the repo (-C) so they cannot browse
# brainstorm/; CHECK and REVIEWER calls run from the repo root without -C. Add --output-schema <file> for JSON,
# -c web_search=live for web (likely), -m <model>. One call per Bash call, timeout 600000; absolute paths only.
codex exec -C "<abs empty dir>" --skip-git-repo-check --sandbox read-only --ephemeral -o "<abs O>" - < "<abs P>" > /dev/null 2>> "<abs R>/logs/codex.log"

# From Codex (Claude); approve the network escalation. --tools "" removes the built-in tools; --disallowedTools
# "mcp__*" also removes MCP tools, which --tools does not affect
cat "<abs P>" | claude -p "Follow the instructions in the piped input exactly. Print only the requested output." --output-format text --no-session-persistence --tools "" --disallowedTools "mcp__*" > "<abs O>"
```

```powershell
# Windows PowerShell 5.1 (not from the Claude docs; test once). Set both encodings: $OutputEncoding for text piped
# into native programs, [Console]::OutputEncoding for decoding their output.
$OutputEncoding = [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
Get-Content -Raw -Encoding UTF8 $P | codex exec -C <abs empty dir> --skip-git-repo-check --sandbox read-only --ephemeral -o $O - | Out-Null
Get-Content -Raw -Encoding UTF8 $P | claude -p "Follow the instructions in the piped input exactly. Print only the requested output." --output-format text --no-session-persistence --tools= --disallowedTools "mcp__*" | Out-File -Encoding utf8 $O
```

`cat file | claude -p "query"`, `--output-format`, `--no-session-persistence`, `--tools` (`""` disables all built-in
tools) and `--disallowedTools` are in the Claude Code CLI reference. `--tools=` in the PowerShell line is an undocumented
equivalent spelling of `--tools ""`, used because Windows PowerShell 5.1 can drop empty `""` arguments passed to native
programs; 5.1's `Out-File -Encoding utf8` writes a BOM, which `bs.py` reads. `--bare` would also skip MCP servers,
plugins, hooks and CLAUDE.md, but it needs `ANTHROPIC_API_KEY`. The Codex non-interactive docs cover `-`, `-o`,
`--ephemeral`, `--skip-git-repo-check`, `--sandbox` and `--output-schema`; `-m` and `-c` are global flags documented in
the Codex CLI reference. `-C` (`--cd`) sets the working directory; confirm it with `codex exec --help` on your version.

Seed for ce-brainstorm (the same shape ce-ideate uses for its own handoff):

```
<title> - <one-sentence description>. Basis: <evidence from checks/>. Why it matters: <rationale>. Known tradeoffs:
<kill-assumptions and the strongest disagreement>. Settled decisions: <from 08_DECISION.md, including Not doing>.
Probe result: <09_PROBE.md verdict>. Domain language (software, growth): use the terms in CONTEXT.md.<merge deferred:
" Also use the terms the user approved in brainstorm/<run>/CONTEXT.proposed.md: <list>."><merge declined: " The terms
in brainstorm/<run>/CONTEXT.proposed.md were NOT accepted into the glossary: do not copy them into CONTEXT.md,
CONCEPTS.md or any other repo doc."> (Seeded from ultimate-brainstorm: brainstorm/<run>/08_DECISION.md and
brainstorm/<run>/09_PROBE.md - do not reopen the choice of idea.)
```

Superpowers (repos that already use it; `/superpowers:brainstorming <text>`, Codex: Brainstorming in `/skills`):

```
Architectural path. Inputs: brainstorm/<run>/08_DECISION.md and brainstorm/<run>/09_PROBE.md - read both fully first.
The decision, scope, Not doing list and kill criteria are approved by me; do not reopen the choice of idea or propose
alternative concepts. Ask only about open questions and NOT VERIFIED premises. Present the design in sections, write
the spec, then hand off to writing-plans. In the plan header, copy the kill criteria into Global Constraints and the
"Fails if" list into Review Focus. Stop after the spec for my review.
```

OpenSpec (repos that use it): `/opsx:explore Direction already chosen: brainstorm/<run>/08_DECISION.md. Test it against
the current specs and code and raise conflicts one question at a time. Do not write anything until I ask.` When the idea
is clear, hand off with `/opsx:propose <name>` (Codex: `$openspec-explore`, then `$openspec-propose`), which creates the
change and writes all planning artifacts the schema needs; or ask explore to capture it, which runs
`openspec new change "<name>"` and writes only the artifacts you name. Capturing needs an OpenSpec root (`openspec init`
or a registered store).

claude-council question (Claude Code command in Stage 10; Codex: `bash scripts/query-council.sh --file=<abs path>/07_TOP.md
--debate --roles=devil,simplicity --no-auto-context -- "<question>" > council.json` then `bash scripts/format-output.sh <
council.json > <abs run path>/redteam/council.md`, from the clone; `--debate` is documented in the script's usage; on
Windows call Git Bash's bash.exe explicitly):

```
These are candidate ideas, not code. For EACH idea in the attached file: (1) steelman it in one sentence, (2) the single
most likely way it fails, written "Fails if ___", (3) the cheapest test that would reveal that within 2 weeks, (4) back /
back if / don't back, with one reason. Then name the idea everyone underrates and one thing all the ideas miss. Judge
substance, not wording. Do not rewrite ideas into new ideas.
```

pm-skills chain (product variant, Stage 11): `/pm-product-discovery:identify-assumptions-new` on the chosen idea, then
`/pm-product-discovery:prioritize-assumptions` (it rates Impact x Risk, with Risk = (1 - Confidence) x Effort; to let
uncertainty drive the ranking, add "rank by impact x lack of evidence (1 - confidence); do not let effort raise the risk
score"), then `/pm-product-discovery:brainstorm-experiments-new`. Codex: type `$` or run `/skills` and pick each skill;
it may be listed under its plugin namespace (for example `pm-product-discovery:identify-assumptions-new`). Paste the
idea text into each call and copy the results into `09_PROBE.md`. Never run `/discover` inside the funnel.

Import from another tool: `/ultimate-brainstorm import <file> <run>` copies the idea list to `pool/IMPORT_<name>.md`,
and the pool is curated again with it (from step 5.1; quick mode: Q.3; a finished run goes on from there). A proposal
run has no idea pool, so an import into one is refused.

The full built-in prompt set (generators, curator, screen header, checks, evolve, normalizer, tournament header,
reviewers, synthesis, decision, probe, quick) is in `ultimate-brainstorm/references/prompts.md`.

---

## 6. Anti-homogenization and convergence playbook

### 6.1 How the design avoids 50 versions of one idea

| Lever | Mechanism | Evidence | Where | Check |
|---|---|---|---|---|
| Human first | Sealed seeds; human round 2 after the map | Qin 2025; Doshi and Hauser 2024; Boussioux 2024 | 1, 5 | human-only canonical ideas in YIELD |
| Strategy portfolio | 5 structurally different, short strategies | Meincke 2024 | 4 | "only here" count per strategy |
| Isolation | Separate contexts; no shared drafts; no lead agent; never forks | Chen 2026 | 4 | generators never read pool/ |
| Tail sampling | VS ladder: full distribution, below 0.10, below 0.01 | Zhang 2025 | 4 | spread of p values; BASELINE share |
| Checked diversify step | "Changed: N of 40" or `bolder_titles` vs `draft_titles` | Meincke 2024 (step skipped in about 15% of runs) | 4-5 | RE-RUN list |
| Planned retrieval | Mechanism transfer from 6 distant fields, ESTABLISHED/INFERRED links, what does not port (our additions to the lateral-thinking method) | Nova 2024; SciMON 2024 | 4, 5 | share of `external:` basis |
| Defixation | 3 warm-up ideas discarded; mechanism, not category; competitor-swap test; mandatory opposite and subtraction ideas | IDEAFix 2026 (likely); Girotra 2023 recommend asking for novelty in the prompt (a recommendation, not a tested result) | all generators | BASELINE share |
| Withheld examples | LANDSCAPE hidden from blind strategies, used only for reopening and checks | Wadinambiarachchi 2024 | 3-5 | - |
| Mechanism-key dedup | Merge only same actor, mechanism, outcome; siblings kept | Si 2024 | 5 | unique share per strategy |
| Coverage steering | Axis grid (counted by `bs.py map`); gap rounds into empty cells; TENSION escape | MAP-Elites-style cell targeting as in claude-brainstorm-multiagent, which feeds under-filled cells as hints and has a `tension_note` escape (heuristic) | 5 | cells covered |
| HOMOGENIZED alarm and saturation stop | Largest cluster above 25% or under 80% of the axis cells covered: mandatory gap round; a round with 40% or more duplicates is saturated | heuristics from the designs, not measured | 5 | 03_POOL.md |
| Quotas | Best per cluster, protected tail slot, protected human slot, primary idea | design rule to keep diversity through the cut; ARIS "name the high-upside idea"; Boussioux 2024 | 6 | clusters represented |
| Evolve, never replace | Variants must beat their parents | co-scientist; Girotra 2010 | 8-9 | - |
| Suggest, never rewrite | The AI asks and suggests | Maier 2026 | 2, 10 | - |

Not used: temperature, persona casts for generation, "just ask another model", banlists on their own (Si 2024 shows they
do not stop repeats; the LEDGER banlist is only a secondary hint in gap rounds).

### 6.2 Convergence funnel

1. Criteria and anchors are fixed at Stage 2, before any idea exists.
2. Annotate, don't eliminate: until Stage 5 only exact duplicates disappear; tools' rejected ideas enter as PARKED.
3. Absolute two-family screen with noncompensatory gates, a floor (any criterion mean at or below 1.5 after
   centering, or a criterion every judge scored 1), weight sensitivity and diversity quotas.
4. Prior-art verdicts with named matches; falsifiable kill-assumptions with cheapest tests.
5. Evolved variants compete with their parents.
6. Human blind pre-commit, then the both-order, two-family pairwise tournament with audits; contested pairs are the
   human's call.
7. Opposed-stance cross-family red-team; dissent preserved; unanimity treated as a warning.
8. Human decision recorded with reasons, parked ideas and triggers.
9. Pre-registered probe; a miss moves to the runner-up.

### 6.3 Kill and stop rules

| Rule | Condition | Override |
|---|---|---|
| K1 | A gate (hard constraint, legal, ethics, safety) failed by both screen judges | one judge only (or only one judge scored the idea): the human confirms |
| K2 | The problem or the insight cannot be stated in one sentence each | - |
| K3 | Any criterion mean at or below 1.5 (after centering), or a criterion every judge scored 1 | human rescue with a written reason |
| K4 | CROWDED (>= 2 named matches, same actor and mechanism) and no differentiator | human confirms; not used for growth or existing-product software ideas (prior art is evidence there; kill only if our product already shipped and measured it) |
| K5 | A cheapest test confirms a high-likelihood "Fails if" | - |
| K6 | The pre-registered probe threshold is missed (`RESULT: MISSED`; INCONCLUSIVE is not a pass) | move to the runner-up (never an idea its own probe killed); with none, switch to another finalist |
| Park | Blocked only by timing or a soft constraint | record a revisit trigger |
| Whole effort | The FRAME's kill condition is met, or every finalist fails the same premise | go back to Stage 2 |

---

## 7. Variants

| Variant | Key changes |
|---|---|
| Software feature or project in an existing codebase | Run in the repo (`brainstorm/` in `.git/info/exclude`); frame with grilling + domain-modeling (P-GRILL-DOCS: glossary challenges, code-contradiction checks, terms staged in `CONTEXT.proposed.md`, and generators get at most 12 relevant terms as today's system, which they may break); ce-ideate in repo mode (codebase scan, learnings, web prior art, "open issues" to cluster tracker themes); Feasibility means feasible here with file:line citations (NOT VERIFIED caps it at 3); TRIZ contradiction operator; codebase-fit check item; spike in a git worktree with Given/When/Then thresholds (you install dependencies and copy env files, or use a feature flag in a scratch branch); handoff to ce-brainstorm then ce-plan (or the repo's existing Superpowers or OpenSpec) |
| Growth of an existing product (activation, retention, conversion) | Frame with grilling + domain-modeling as for software, pinning the measurement definition of "activated" (ideas may still propose a different activation event); it checks the activation event, window, baseline rate and source, cohort and the weekly number of units entering the target window (signups for activation, for example teams reaching day 30 for second-month churn), and restates impossible goals (10x a 30% rate) as a confirmed alternative target; grounding from a funnel export or analytics MCP plus an instrumentation grep and a first-session code walk; criteria Target-metric impact 30 (Activation, Retention or Conversion impact), Evidence 20, Feasibility 20, Time to test 15, Distinctiveness 15; K4 off (prior art is evidence; kill only if already shipped and measured); codebase-fit check; probe = feature-flagged experiment with MDE, sample size per arm, duration and guardrails (over 4 weeks: a leading indicator, or for activation a moderated 5-user test); decision may be a bundle of 2-4 ideas with a test order |
| New product or startup | First ask the stage (pre-product, has users, paying customers, infrastructure), then stage-routed forcing questions (demand reality, status quo, desperate specificity, narrowest wedge, observation and surprise, future-fit; one per message, at most one push-back, exempt from the round cap); a named solution type ("AI agents for X") is classified as constraint, preference or hypothesis; criteria Value/pain 30, Reachability 20, Feasibility 20, Distinctiveness 15, Evidence of demand 15 (B2B: Value/pain 25, Willingness to pay 20, Reachability 15, Feasibility 20, Distinctiveness 10, Evidence of demand 10, plus buyer vs user, budget, integrations, liability, regulated data and seasonality questions); landscape includes today's workarounds; optional `/pm-execution:red-team-prd` (a command; Codex: the strategy-red-team skill); pm-skills assumption and pretotype chain (consumer: at most 2 weeks and $100, at least 30 responses or 100 visitors; B2B: 8-12 problem interviews, a concierge pilot or 3+ LOIs; threshold first); one-pager, build only after the test passes |
| Research idea | Freeze the observation, claim type, PICO/PECO, dated search boundary; criteria Significance 30, Testability 25, Feasibility 20, Distinctiveness 15, Evidence 10; S5 replaced by a research lens quota adapted from Phase 1 of Orchestra's brainstorming-research-ideas skill (5 tensions or trade-offs, 3 recent shifts used to revisit old negative results, 2 failure or boundary probes, 1 adjacent-field import, 1 compose/decompose, then up/down/sideways variants); CROWDED only with named papers (ARIS novelty-check: ABANDON only with a named paper; crowded with a stated delta is PROCEED); K-Dense `hypothesis-generation` for rival explanations; pilot with a written decision rule; pre-registration scaffold |
| Creative, marketing, naming | Human is the main judge (LLM judges do not track expert creative judgment); marketing context via `/product-marketing` and a `/marketing-ideas` coverage sweep of its 17 categories after the map; `/marketing-council` as red-team; campaigns add `/creative-director` as a strategy (ask it to find an insight, then generate concepts; CC BY 4.0 attribution line required); naming adds `/naming` (Claude Code), which by design shows only 3-5 vetted finalists, with an explicit override to list every territory and raw candidate (undocumented) and a manual trademark check; probe = 24-hour re-read and 5 audience reactions |
| 15-minute quick mode (manual route; the kit's quick mode makes about 16 model calls, section 0) | Minute 0-3 human brief, 5 ideas, 3 criteria; 3-7 one VS plus operators pass (plus the other family in parallel if available); 7-9 merge, gate, pick 4 finalist cards (best per cluster, the most distinctive feasible idea, your best idea); 9-12 other-family both-order check with `bs.py`; 12-15 gut pick first, then the tally, then your decision with the riskiest assumption, a threshold and a kill criterion in `QUICK_DECISION.md`, stamped "Novelty NOT checked" |
| Codex-only | Host Codex; second model = a `bs-alt` custom agent in `~/.codex/agents/bs-alt.toml` with its own `model` (no nested CLI, no network escalation; fallback `codex exec -m <another model>`), labeled PROVISIONAL; it takes the `claude.*` / `claude_*` judge files, S3/S5 and the red-team CRITIC; origins labeled `gpt-alt`; self-preference audit skipped; ce-ideate native (not in the IDE extension; on native Windows prefer WSL for it); grilling + domain-modeling via the skills CLI run from your home folder without `-g` (grill-me and grill-with-docs are unreliable in Codex: their one-line bodies name a Skill tool Codex does not have under that name); claude-council's direct script with non-OpenAI seats (`--providers=gemini,perplexity`) restores cross-vendor critique; every built-in prompt says "Do not load or invoke any skill"; the Codex Superpowers copy is v6.3.0, so add "Stop after the spec for my review"; all tokens bill to one ChatGPT plan, so check usage before Session B |
| Claude-only | Host Claude Code; second judge = a general-purpose subagent with a different model family alias (PROVISIONAL; self-preference audit skipped); claude-council seats (Gemini via GEMINI_API_KEY or the agy CLI's separate `antigravity` seat, Perplexity, Grok, OpenRouter, ollama) restore cross-vendor critique |
| Cross-model maximum | Claude Code host, `codex exec` as second family, claude-council seats from 2-3 more vendors in Stage 10; vendors mainly de-bias judging, strategies drive diversity |

Details for each variant are in `ultimate-brainstorm/references/variants.md`.

---

## 8. Pitfalls and anti-patterns

| Anti-pattern | What happens | Fix built into the workflow |
|---|---|---|
| Starting with an AI brainstorm | The human anchors on AI ideas; fewer original ideas; group output converges | Sealed seeds; no AI idea before the file exists |
| Several brainstorm skills with auto-triggers | Competing interviews and gates, nondeterministic routing | One owner, routing block, namespaced invocation, per-project disables |
| Diversity by temperature, personas or extra vendors | Incoherence, or the same ideas from every model | Strategy portfolio in isolated contexts |
| Generators that see each other (agent teams, a lead agent, forks, `/subtask`) | Diversity collapse | `subagent_type: general-purpose` on every call, or fresh CLI processes run from an empty folder; "Read no files" in every generator prompt; optional `Agent(fork)` deny (syntax unverified) |
| Taking a tool's top 5 as the pool | The pool loses everything the tool filtered out before mapping | Raw candidates and rejections imported as PARKED |
| "Avoid repeats" as the dedup plan | About 95% duplicates at scale | Mechanism-key dedup, yield tracking, saturation stop |
| Believing "this is novel" from a model | The novelty mirage | Novelty only from named prior art; judges score Distinctiveness |
| One judge, one order | Position and self-preference bias decide the winner | Both orders, two families, audits, human pre-commit |
| Debate as an idea generator | Convergence, not creativity | Debate only in the red-team |
| Hidden candidates (one "best" answer) | You lose the spread you asked for | Every strategy writes all its ideas |
| Interactive skills in subagents | Claude Code removes AskUserQuestion from every non-fork subagent, so a question-driven skill there cannot ask the user its multiple-choice questions | grilling and domain-modeling (they wait for your answers every round), BMAD's interactive modes and ce-ideate (it ends with a menu and dispatches its own subagents) run in the main conversation (our recommendation; not a documented rule of those tools) |
| Letting an LLM do the bookkeeping | An LLM curator miscounts IDs, yields and coverage at 120-180 raw ideas | The curator only merges and clusters; `bs.py map` counts |
| A repo-rooted run folder | `brainstorm/` shows in `git status`, gets scanned by ce-ideate and can be committed by accident | `.git/info/exclude`; "brainstorm/ is not part of the codebase" in the ce-ideate focus text |
| Long single sessions | Compaction keeps only the first 5,000 tokens of each invoked skill within a 25,000-token budget | One stage group per session; state in files; `continue <run>` |
| Too many installed skills | The skill listing (1% of context) drops the least-used descriptions | Few core components; variant modules per project; check with `/context` or `/skill-doctor` (v2.1.252+) |
| Misreading idea-reality | A low score read as "no competition" | 0.5.0 counts failed sources as 0: low = unknown; `GITHUB_TOKEN`; web check |
| Leaking private ideas or code | Web search and other vendors see the idea; FACTS and council auto-context carry repo files | Two privacy questions at Stage 0 (idea text; code facts and repo files); local-only mode; file paths without contents; `--no-auto-context` |
| Cost blowups | Hours of subagents | Modes; caps (8 finalists, 4 red-team ideas, 2 gap rounds); a per-run budget of backend requests that asks or stops before a launch could pass it (`ub budget` raises it); no claude-council `--agents` (about 456k tokens measured for 8 seats) |
| Windows encoding and quoting | `?` in prompts, garbled non-ASCII output, empty arguments dropped, `python3` resolving to the Store stub, bash commands failing in Codex's PowerShell | ASCII prompt files; in PowerShell 5.1 set both `$OutputEncoding` (text piped into native commands) and `[Console]::OutputEncoding` (decoding their output) to UTF-8 and read prompts with `Get-Content -Raw -Encoding UTF8`; `--tools=` in PowerShell (`--tools ""` in bash); Git Bash for Claude Code, PowerShell forms or WSL for Codex; Python detected in the order `py -3`, `python`, `python3`; `bs.py` reads UTF-16 and BOM |
| Long `codex exec` calls from Claude Code | The Bash tool's 2-minute default timeout (10-minute maximum) kills big generators and judge batches; shell variables vanish between calls | One call per Bash call with timeout 600000 or `run_in_background`; literal absolute paths |
| `continue` after a crash | A stage that looks done on disk is half done | `bs.py status` checks every planned strategy file, a check per shortlisted/rescued/primary idea, the tournament result and a probe RESULT line |
| Tool drift | Behaviour changes between releases (CE shipped 3 releases on 2026-09-22) | Pin marketplaces with `@ref`; rerun quick mode after updates |
| Building before testing | Ideas that looked best fail when executed | Pre-registered probe before the handoff |

---

## 9. Sources

Component repositories: https://github.com/obra/superpowers - https://github.com/mattpocock/skills -
https://github.com/garrytan/gstack - https://github.com/addyosmani/agent-skills/tree/main/skills/idea-refine -
https://github.com/Fission-AI/OpenSpec - https://github.com/open-gsd/gsd-core - https://github.com/bmad-code-org/BMAD-METHOD -
https://github.com/bmad-code-org/bmad-module-creative-intelligence-suite - https://github.com/EveryInc/compound-engineering-plugin -
https://github.com/SuperClaude-Org/SuperClaude_Framework - https://github.com/danielmiessler/LifeOS -
https://github.com/CHATS-lab/verbalized-sampling - https://github.com/tjboudreaux/cc-thinking-skills -
https://github.com/UditAkhourii/adhd - https://github.com/NousResearch/hermes-agent/tree/main/optional-skills/creative/creative-ideation -
https://github.com/neurofoo/agent-skills - https://github.com/Jamie-BitFlight/claude_skills/tree/main/plugins/brainstorming-skill -
https://github.com/athola/claude-night-market - https://github.com/giordanorec/claude-brainstorm-multiagent -
https://github.com/ogiberstein/lateral-thinking-skill - https://github.com/abpai/skills - https://github.com/spranab/brainstorm-mcp -
https://github.com/BeehiveInnovations/pal-mcp-server - https://github.com/aiwithremy/claude-skills-llm-council -
https://github.com/hex/claude-council - https://github.com/Yeachan-Heo/oh-my-claudecode - https://github.com/nyldn/claude-octopus -
https://github.com/affaan-m/ECC - https://github.com/karpathy/llm-council - https://github.com/mnemox-ai/idea-reality-mcp -
https://github.com/MaxKmet/idea-validation-agents - https://github.com/phuryn/pm-skills -
https://github.com/anthropics/knowledge-work-plugins/tree/main/product-management - https://github.com/deanpeters/Product-Manager-Skills -
https://github.com/K-Dense-AI/scientific-agent-skills - https://github.com/Orchestra-Research/AI-Research-SKILLs -
https://github.com/wanshuiyin/Auto-claude-code-research-in-sleep - https://github.com/coreyhaines31/marketingskills -
https://github.com/smixs/creative-director-skill - https://github.com/glacierphonk/naming - https://github.com/openai/codex-plugin-cc -
https://github.com/vercel-labs/skills

Claude Code docs: https://code.claude.com/docs/en/skills - https://code.claude.com/docs/en/sub-agents -
https://code.claude.com/docs/en/cli-reference - https://code.claude.com/docs/en/permissions -
https://code.claude.com/docs/en/discover-plugins - https://code.claude.com/docs/en/plugins-reference -
https://code.claude.com/docs/en/plugin-marketplaces - https://code.claude.com/docs/en/mcp - https://code.claude.com/docs/en/memory -
https://code.claude.com/docs/en/settings-reference - https://code.claude.com/docs/en/hooks - https://code.claude.com/docs/en/agent-teams -
https://code.claude.com/docs/en/workflows - https://code.claude.com/docs/en/changelog

Codex and Agent Skills docs: https://learn.chatgpt.com/docs/build-skills - https://learn.chatgpt.com/docs/plugins -
https://learn.chatgpt.com/docs/build-plugins - https://learn.chatgpt.com/docs/extend/mcp -
https://learn.chatgpt.com/docs/agent-configuration/agents-md - https://learn.chatgpt.com/docs/agent-configuration/subagents -
https://learn.chatgpt.com/docs/non-interactive-mode - https://learn.chatgpt.com/docs/web-search -
https://learn.chatgpt.com/docs/config-file/config-reference - https://learn.chatgpt.com/docs/import -
https://learn.chatgpt.com/docs/mcp-server - https://agentskills.io/specification

Research: Si, Yang, Hashimoto 2024 https://arxiv.org/abs/2409.04109 - Si, Hashimoto, Yang 2025 https://arxiv.org/abs/2506.20803 -
Zhang et al. 2025 (Verbalized Sampling) https://arxiv.org/abs/2510.01171 - Meincke, Mollick, Terwiesch 2024 https://arxiv.org/abs/2402.01727 -
Girotra et al. 2023 https://mackinstitute.wharton.upenn.edu/wp-content/uploads/2023/08/LLM-Ideas-Working-Paper.pdf -
Doshi and Hauser 2024 https://arxiv.org/abs/2312.00506 - Google co-scientist https://arxiv.org/abs/2502.18864 -
Du et al. 2023 https://arxiv.org/abs/2305.14325 - Liang et al. https://arxiv.org/abs/2305.19118 - Smit et al. https://arxiv.org/abs/2311.17371 -
Chen et al. 2026 https://arxiv.org/abs/2604.18005 - LLM Review 2026 https://arxiv.org/abs/2601.08003 - Li-Chun Lu et al. 2024, "LLM Discussion" (COLM 2024) https://arxiv.org/abs/2405.06373 -
Ueda et al. 2025 https://arxiv.org/abs/2507.08350 - Solo Performance Prompting https://arxiv.org/abs/2307.05300 -
Anderson et al. 2024 https://arxiv.org/abs/2402.01536 - Padmakumar and He 2024 https://arxiv.org/abs/2309.05196 -
Wenger and Kenett 2025 https://arxiv.org/abs/2501.19361 - Artificial Hivemind 2025 https://arxiv.org/abs/2510.22954 -
Meincke, Nave, Terwiesch 2025, "ChatGPT decreases idea diversity in brainstorming", Nature Human Behaviour https://mackinstitute.wharton.upenn.edu/2025/new-in-nature-chatgpt-decreases-idea-diversity-in-brainstorming/ -
Peeperkorn et al. 2024 https://arxiv.org/abs/2405.00492 - IDEAFix 2026 https://arxiv.org/abs/2606.00875 -
Kumar et al. https://arxiv.org/abs/2410.03703 - Ashkinaze et al. https://arxiv.org/abs/2401.13481 - Qin et al. 2025 https://arxiv.org/abs/2502.06197 -
Wadinambiarachchi et al. 2024 https://arxiv.org/abs/2403.11164 - Maier et al. 2026 https://arxiv.org/abs/2510.23324 -
Lee and Chung 2024 https://www.uh.edu/news-events/stories/2024/august/08202024-chatgpt-study.php - Boussioux et al. https://github.com/leobix/creative -
Shaer et al. 2024 https://arxiv.org/abs/2402.14978 -
Diehl and Stroebe 1987 https://homepages.se.edu/cvonbergen/files/2013/01/Productivity-Loss-In-Brainstorming_Toward-the-Solution-of-a-Riddle.pdf -
Mullen et al. 1991 https://dynamic.decorrespondent.nl/downloads/michiel-de-hoog/Mullen-1991-Productivity-Loss-in-Brainstorming-Groups.pdf -
Girotra, Terwiesch, Ulrich 2010 https://faculty.wharton.upenn.edu/wp-content/uploads/2012/04/Girotra-Terwiesch-Ulrich-(MS-2010).pdf -
Zheng et al. 2023 https://arxiv.org/abs/2306.05685 - Wang et al. 2023 https://arxiv.org/abs/2305.17926 - Panickssery et al. 2024 https://arxiv.org/abs/2404.13076 -
PairS 2024 https://arxiv.org/abs/2403.16950 - Tripathi et al. 2025 https://arxiv.org/abs/2504.14716 - Sinhahajari et al. 2026 https://arxiv.org/abs/2606.12071 -
Chakrabarty et al. 2024 https://arxiv.org/abs/2309.14556 - Organisciak et al. 2023 https://files.eric.ed.gov/fulltext/ED629879.pdf -
The AI Scientist (Chris Lu et al. 2024) https://arxiv.org/abs/2408.06292 - Nova 2024 https://arxiv.org/abs/2410.14255 - SciMON 2024 https://arxiv.org/abs/2305.14259
