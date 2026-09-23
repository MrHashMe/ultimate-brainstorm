# AI Brainstorming Tools for Claude Code, Codex and Other Agents: What to Use (2026-09-23)

**Scope and method.** This report covers every AI brainstorming and ideation tool we could find that works with Claude Code, Claude.ai, OpenAI Codex or other coding agents: skills, plugins, slash commands, subagents, MCP servers, multi-model councils, spec-driven frameworks with an ideation phase, research-ideation systems, apps and prompt libraries. Twelve search lanes and twelve gap-hunting angles produced 2,371 raw candidates, which deduplicated to 2,283 tools. After screening, 150 were fully verified, 300 light-verified and the rest kept as metadata only. Of the 483 verified records, 393 are ranked, 46 were rejected as not really brainstorming, 40 are excluded as aggregator copies and 4 are directories. Each ranked tool is scored 0-100 on an 11-criterion rubric, and 61 of them were re-checked by two adversarial reviewers: one for evidence and adoption, one for ideation quality. Tiers are S (ranks 1-8), A (9-25), B (26-60) and C (61-393). The reader is assumed to know BMAD Method and the Superpowers brainstorming skill already. The aim is to tell you exactly which tool to use for each job, and what each tool really does compared with what it claims.

Research date: **2026-09-23**. Star counts, install counts and dates are as verified on or shortly before that date.

---

## 1. TL;DR: what to actually install

One finding shapes every recommendation below: **no tool in this survey has a controlled comparison showing that it produces better ideas than a well-written vanilla prompt.** The best tools earn their place through structure. They generate before judging, they use isolated parallel generators or several different models, they check ideas against evidence, and they leave a durable artifact. Pick tools for their mechanics, not their marketing.

| # | Install / use | Why, and for which job |
|---|---|---|
| 1 | **[ce-ideate + ce-brainstorm][r1]** (Compound Engineering, Every) | **The best overall pick (82/100).** It has the strongest real divergence engine for a codebase: 5-6 parallel subagents across six frames produce about 36-48 ideas, each tied to evidence. A fresh-context verifier then challenges them and the result is a ranked file that hands off to planning. It has native plugins for both Claude Code and Codex. |
| 2 | **[bmad-brainstorming][r2]** (BMAD-METHOD) | **Use it for a human-led session.** It has 108 techniques, three stances (you ideate, you trade ideas, or the AI ideates), a 100+ idea target and a resumable log. Before installing, patch or pin its scripts; see the risks in its card. |
| 3 | **[ADHD][r20]** | **Use it when you want the widest set of options on one hard question.** Five isolated subagents each work in a different frame, then a separate critic scores and clusters the results. One `npx skills add` covers Claude Code, Codex and about 50 agents. It asks you nothing during the run. |
| 4 | **[office-hours (gstack)][r4]** | **Use it to pressure-test a startup or product idea.** It asks six forcing questions one at a time, gets a cross-model cold read, and runs an adversarial review of the design doc. It is heavy to install, and it is not a generator. |
| 5 | **[brainstorming (Superpowers)][r5]** | **Keep it as your design-approval gate before code, not as an idea generator.** Its divergence scored 1/5. |
| 6 | **[idea-refine][r7]** | **The lightweight, low-risk choice (trust 5/5).** It takes a vague idea through 5-8 variations and an assumption audit to a one-pager with a Not Doing list. |
| 7 | **[workshop (consult-llm)][r12]** | **Cross-model divergence and critique for software design.** Claude interviews you, several model families propose independently, then they red-team the chosen design. |
| 8 | **[Council of High Intelligence][r23]** | **For decisions and strategy.** It runs blind analysis, anonymized cross-examination, dissent quotas and a minority report, and it can route seats across Claude, Codex and Gemini. |
| 9 | **[idea-discovery / idea-creator (ARIS)][r3]** | **For ML research ideas.** Lens subagents and two GPT generators feed a novelty check and then GPU pilots. It suits ML research only. |
| 10 | **[lateral-thinking (danium)][r36]** | **The cheapest, most portable technique library for getting unstuck.** It has eight sourced techniques with quantity targets and a rule that abandoned ideas stay visible. |
| 11 | **[grill-me][r22]** | **Run it before any of the above** to turn a loose idea into a dependency-ordered set of decisions. It has 1.2M installs and costs almost no context. |
| 12 | **[scientific-brainstorming (K-Dense)][r6]** | **Use it when a group has to decide.** It uses anchored weighted criteria, a sensitivity-tested matrix, non-originator red-teaming and a human decision log. |

**Avoid or quarantine:** [ResearchStudio][r25] (its `install.sh` silently writes a permission-bypassing `.claude/settings.json`); [DeepScientist][r24] (every runner defaults to no-approval, full-access mode, and maintainers have not responded since 2026-06-15); [oma-brainstorm][r57] (its installer offers to delete Superpowers and other tools, with Yes as the default); [PAL MCP][r323] (no commits since 2025-12-15). The browser-cdp companion of [oh-story][r52] copies Chrome cookie and login databases.

---

## 2. Quick picker

Tools in brackets link to their primary URL. "Codex" means Codex CLI or app unless noted otherwise.

| Job | Best for Claude Code | Best for Codex | Cross-agent / MCP option |
|---|---|---|---|
| **Feature/design brainstorming inside a codebase** | [ce-ideate][r1] to diverge, then [ce-brainstorm][r1] for requirements. Add [Superpowers brainstorming][r5] only as the final design gate. | The same plugin: `codex plugin add compound-engineering@compound-engineering-plugin`, then `$ce-ideate` / `$ce-brainstorm` | [ADHD][r20] via `npx skills add`. It needs a parallel-subagent tool. For spec-driven repos, use [openspec-explore][r21]. |
| **Product/startup ideation and validation** | [office-hours][r4] to pressure-test, then [idea-refine][r7] for the one-pager | [idea-refine][r7] (Codex plugin, `@idea-refine`); [brainstorm-ideas-new][r18] (skills run on Codex, its slash commands do not) | [bmad-brainstorming][r2], which also ships as Gemini Gem and ChatGPT GPT bundles; [idea-validation-agents][r29], which includes CLAUDE.md, AGENTS.md and .cursor rules |
| **Research-idea generation** | [ARIS idea-discovery][r3] (ML); [ResearchStudio IdeaSpark][r25] if you can isolate its installer | ARIS Codex route (`install_aris_codex.sh`). On Codex, GPT both generates and judges. | [scientific-brainstorming][r6] to converge; [AutoDiscovery][r17] for tabular datasets (CLI or hosted); [Co-Scientist][r8] is a reference design only: it has no API, MCP or skill, and access is a restricted Enterprise Preview or a Labs waitlist |
| **Creative / content / naming** | [lateral-thinking][r36] for provocations; [marketing-ideas + marketing-council][r19]; [Claude Design][r9] for visual directions | lateral-thinking (install through `$skill-installer`); the marketing skills via `npx skills add coreyhaines31/marketingskills` | [brand-ideation][r75] then [naming][r186], then [GoDaddy MCP][r266] for live domain checks; [Mobbin MCP][r179] for UI references |
| **Problem-solving / debug ideation** | [ADHD][r20], which generates classes of hypotheses; [agent-teams /team-debug][r237], where teammates try to disprove each other's root causes | [unstuck (Ouroboros)][r124], a Codex plugin; [creative-problem-solver][r98], a Codex-first skill with 8 transform axes | [cc-thinking-skills][r127] (TRIZ, pre-mortem, first principles) via `npx skills` |
| **Strategy / decisions** | [grill-me][r22] to frame, then [Council of High Intelligence][r23] | Council of HI: `./install.sh --codex-only`; grill-me via `npx skills@latest add mattpocock/skills` | [deliberation MCP][r262], which has a Claude Code plugin and a Codex marketplace entry; [the-fool][r74] for one critique mode at a time (Socratic, evidence falsification, dialectic, pre-mortem or red team) |
| **Multi-model "council" second opinions** | [workshop (consult-llm)][r12] for design; [claude-council][r86] for one-shot questions | `consult-llm install-skills --platform codex`; [argue][r250] | [brainstorm-mcp][r239] or [mcp-rubber-duck][r224] (any MCP client). Do not rely on PAL, which is unmaintained. |

---

## 3. Tier list

Score is 0-100: the sum of weight x (criterion score / 5) over 11 criteria (see Section 14). "full", "light" and "critic" show how each record was checked.

### S tier (ranks 1-8)

| Rank | Tool | Score | Why it is here |
|---|---|---|---|
| 1 | [ce-ideate + ce-brainstorm][r1] | 82 | It is the only tool that combines a real parallel divergence fleet, file:line grounding, fresh-context refutation, a ranked artifact and a handoff to planning, on 14 agents and with daily releases. |
| 2 | [bmad-brainstorming][r2] | 73 | It has the best human facilitation: 108 techniques, a stance choice, domain pivots, a 100+ idea target and a resumable log. It is held back by unguarded scripts and techniques that are only one line each. |
| 3 | [idea-discovery / idea-creator (ARIS)][r3] | 72 | Deepest research pipeline you can run from an agent: lens subagents plus two GPT generators, then a novelty check and GPU pilots. Useful for ML only. |
| 4 | [office-hours (gstack)][r4] | 69 | It has the best facilitation and critique for product ideas (forcing questions, cold read, adversarial review), but its divergence scores only 2/5 and it is very heavy to install. |
| 5 | [brainstorming (Superpowers)][r5] | 67 | It has huge adoption and a clean path to a spec, but it is a design gate. Only its architectural path proposes alternatives, and then only 2-3. |
| 6 | [scientific-brainstorming (K-Dense)][r6] | 66 | It has the most rigorous convergence (a sensitivity-tested weighted matrix), but it is a protocol for human groups that deliberately limits what the AI contributes. |
| 7 | [idea-refine][r7] | 65 | It gives a clean diverge-and-converge one-pager at very low risk. It caps output at 5-8 ideas and forbids 20 or more. |
| 8 | [Google Co-Scientist][r8] | 65 | It has the strongest evidence of any ideation system (Nature paper, wet-lab validations), but you cannot use it from Claude or Codex. |

### A tier (ranks 9-25)

| Rank | Tool | Score | Why it is here |
|---|---|---|---|
| 9 | [Claude Design][r9] | 65 | First-party canvas that shows 2-4 visual directions side by side, with handoff to Claude Code. It covers visual ideas only and has no scoring. |
| 10 | [nw-brainstorming / nw-diverge (nWave)][r10] | 64 | Requires SCAMPER coverage, a structural diversity test and a locked-weight matrix with a reviewer, but installs a large framework. |
| 11 | [DARE][r11] | 64 | The widest library of named creativity techniques found (10 campaigns), but it is a research pipeline with very high search cost. |
| 12 | [workshop (consult-llm)][r12] | 64 | Genuine cross-model independent proposals, then a red-team risk register. Adoption is tiny. |
| 13 | [sparring-partner + ideation (data2story)][r13] | 64 | A six-phase diverge/converge/pre-mortem session with rules against sycophancy and a living document. It is not packaged as a standalone install. |
| 14 | [ia-ideate / ia-brainstorming (Whetstone)][r14] | 64 | Grounded in the repo and git history. It generates 10-15 ideas under 7 lenses, kills weak ones and ranks the rest. Very low adoption. |
| 15 | [/explore-options (designer-skills)][r15] | 64 | UX-only, but it varies concepts along behavioural axes and records a revival condition for every rejected concept. |
| 16 | [design-shotgun + plan-ceo-review (gstack)][r16] | 64 | Forces visually distinct UI variants and structured ambition prompts. It is broken on a fresh Codex install and very heavy. |
| 17 | [Ai2 AutoDiscovery][r17] | 64 | A real search algorithm (MCTS with Bayesian surprise) tested against data and backed by a NeurIPS paper. It works only on datasets and has no agent integration. |
| 18 | [brainstorm-ideas-new / -existing (pm-skills)][r18] | 63 | A simple product-trio prompt (15 ideas, top 5) that feeds a strong discovery chain. Native on both Claude Code and Codex. |
| 19 | [marketing-ideas + marketing-council][r19] | 63 | Huge adoption and a council built on dissent. The ideas come from a fixed catalog; the skill retrieves rather than generates. |
| 20 | [ADHD][r20] | 63 | Real isolated parallel frames plus a separate weighted critic, and an independent blind benchmark exists. It asks you nothing and leaves no artifact. |
| 21 | [openspec-explore][r21] | 63 | Strong grounding in the repo and specs, with facilitation one question at a time. Divergence 1/5, and telemetry is on by default. |
| 22 | [grill-me][r22] | 63 | The best short skill for turning an idea into dependency-ordered decisions. It generates no alternatives. |
| 23 | [Council of High Intelligence][r23] | 63 | The most rigorous council: blind first round, anonymized cross-examination, dissent quota and multi-provider seats. It deliberates on a question; it does not generate options. |
| 24 | [DeepScientist][r24] | 63 | Rich lenses and gates, and its ideas are validated by experiments. Unsafe execution defaults and maintenance has stalled. |
| 25 | [ResearchStudio-Idea (Microsoft)][r25] | 63 | Deep literature grounding and a 100-seed benchmark. It produces one idea per run and its installer bypasses permissions. |

### B tier (ranks 26-60)

| Rank | Tool | Score | One-line reason |
|---|---|---|---|
| 26 | [gds-brainstorm-game][r26] | 63 | About 25 game-design techniques, a 100+ idea target and domain pivots every 10 ideas. Convergence is weak and it covers games only. |
| 27 | [vibe-check][r27] | 63 | Beginner-friendly validation with ODI scoring and verified quotes, producing a PRD. Divergence is only 4-8 Crazy 8 sketches, and SKILL.md is 78KB. |
| 28 | [Feature Dev plugin][r28] | 63 | Official Anthropic plugin: 2-3 parallel architect agents work on real code. No design document is kept. |
| 29 | [idea-validation-agents][r29] | 63 | Up to 10 distinct ideas grounded in trends, scored with a multiplicative floor. B2C apps only. |
| 30 | [unikit-gd-brainstorm][r30] | 63 | Five generators, then a two-pass Pugh matrix and a pre-mortem for games. Tiny adoption. |
| 31 | [parallel-concepts + concept-selection][r31] | 63 | The same toolset as #15, recorded a second time from a different URL. |
| 32 | [CCFA-Skills idea optimizer + reviewer][r32] | 63 | Lineage operators and a calibrated reviewer for academic ideas. Its own figures show 2.4-21x more tokens than the base. |
| 33 | [product-brainstorming (Anthropic)][r33] | 62 | Official PM sparring partner: 5-7+ ideas using SCAMPER and HMW. Output stays in chat. |
| 34 | [brainstorming-research-ideas (Orchestra)][r34] | 62 | Ten ML-research lenses and 10-20 ideas. No novelty check. |
| 35 | [scientific-problem-selection (Anthropic)][r35] | 62 | Fischbach's framework with strong de-risking. Biology-focused, and the user generates the ideas. |
| 36 | [lateral-thinking (danium)][r36] | 62 | Eight sourced techniques with quantity targets and visible abandonment of weak ideas. Hands nothing off to planning. |
| 37 | [trellis-brainstorm][r37] | 62 | Excellent one-question facilitation into a PRD. Its divergence step was removed in v0.6.0. |
| 38 | [academic-research-skills Socratic mode][r38] | 62 | Deliberately non-generative academic mentor. Hooks always on, non-commercial license. |
| 39 | [design-sprint (wondelai)][r39] | 62 | GV sprint guide written for human teams. The agent does not generate ideas itself. |
| 40 | [AI-DLC Ideation stage (AWS)][r40] | 62 | Traceable, gated artifacts. No divergence at all. |
| 41 | [/gsd:explore (GSD)][r41] | 62 | Disciplined Socratic routing into GSD artifacts. The original repo is archived and the tool has moved. |
| 42 | [specs.md Ideation flow][r42] | 62 | Enforces a domain wheel and a 50-idea target, converges with Six Hats and Disney. Tiny adoption; telemetry is opt-out. |
| 43 | [brainstorm-coach][r43] | 62 | User-first facilitation that records your wording verbatim. An uncredited rewrite of BMAD, with 16 installs. |
| 44 | [Research Companion][r44] | 62 | Web-grounded research diverge phase plus parallel critics. Costly in Opus tokens. |
| 45 | [creative-writing-skills][r45] | 62 | Real parallel subagents, one per angle, for fiction. Convergence is left to the author. |
| 46 | [show-me-the-money][r46] | 62 | Web-grounded business scans and a persona panel. Only 5 ideas; licensed CC BY-NC. |
| 47 | [brainstorm-assistant (universal-dev-standards)][r47] | 62 | Anti-anchoring pre-flight and a persona x lens grid. No web grounding, and its installer adds husky hooks. |
| 48 | [HarnessFlow][r48] | 62 | Blind archetype slots for coding plans. No license. |
| 49 | [brainstorm-panel (Constructor Studio)][r49] | 62 | Editable persona panel grounded in the repo. Heavy framework, 35 stars. |
| 50 | [jam (wicked-garden)][r50] | 62 | Evidence-backed persona panels plus a real multi-model council. 9 stars. |
| 51 | [Oh My Paper][r51] | 62 | Five ideas grounded in a gap matrix, then persona review. Academic use only. |
| 52 | [oh-story-claudecode][r52] | 62 | Topics for Chinese web novels, grounded in scraped market data. Its browser-cdp companion copies Chrome credentials (Snyk Fail). |
| 53 | [hypothesis-gen (Agent-Loop-Skills)][r53] | 62 | Generator, scout and judge loop with real literature checks. Science only. |
| 54 | [Junshi][r54] | 62 | Grounded in your own papers and remembers rejected directions. Sparse commit history. |
| 55 | [MassGen][r55] | 62 | Genuine multi-model parallel generation plus voting. Returns one winner, and the main repo has had no commits since June. |
| 56 | [brainstorm (Claude Code Game Studios)][r56] | 61 | Game concept document with pillars and director gates. Only 3 concepts. |
| 57 | [oma-brainstorm][r57] | 61 | TRIZ-lite plus a blind multi-lens review. Its installer deletes competing tools by default. |
| 58 | [reversa-brainstorm][r58] | 61 | Pre-mortem and killer-assumption tests. Thin divergence and prompts in Portuguese. |
| 59 | [/think (Waza)][r59] | 61 | Strong single-recommendation planner that works against divergence. Gen Agent Trust Hub rates it HIGH risk. |
| 60 | [EvoMap AutoResearch][r60] | 61 | Grounded in 10 signal channels plus a 3-model panel. A batch pipeline, with an author-identity incident. |

### C tier (ranks 61-393, scores 27-61), compact

All 333 are in the master table (Section 13). The ones worth knowing about:

- **Native planning modes. These are not ideation engines, but they are already installed:** [Codex Plan Mode][r78] (60), [Gemini CLI Plan Mode][r136] (57), [Cursor Plan Mode + /best-of-n][r137] (57), [Copilot Plan agent][r138] (57), [Claude Code Agent Teams][r163] (56, runtime for councils).
- **Useful single-purpose tools:** [bmad-party-mode][r73], [the-fool][r74] (red-team critique), [creative-director-skill][r72], [brand-ideation][r75], [unstuck (Ouroboros)][r124], [cc-thinking-skills][r127], [naming][r186], [Verbalized Sampling][r261], [idea-reality-mcp][r340], [GoDaddy MCP][r266], [Mobbin MCP][r179], [Miro MCP][r139].
- **Councils and debate:** [claude-council][r86], [council (ECC)][r140], [Claude Octopus][r141], [/debate (AgentSys)][r149], [deliberation][r262], [mcp-rubber-duck][r224], [brainstorm-mcp][r239], [argue][r250]; [PAL MCP][r323] and [LLM Council (karpathy)][r371] are unmaintained.
- **Research systems out of reach from agents:** [The AI Scientist v1][r168] and [v2][r257], [Kosmos][r238] / [Kosmos + Precedent][r164], [SciAgents][r370], [Chain of Ideas][r354], [Stanford Research Ideation Agent][r200].
- **Near-zero value:** [SPARC innovator][r390] (it calls an MCP tool that does not exist), [Roo Code Brainstorm mode][r391], [oblique-skill][r392], [Dreamtap][r393].

---

## 4. Category leaderboards

### 4.1 Brainstorming skills and plugins

| Rank | Tool | Score | Note |
|---|---|---|---|
| 1 | [ce-ideate + ce-brainstorm][r1] | 82 | Parallel frame fleet with a verifier |
| 2 | [bmad-brainstorming][r2] | 73 | 108 techniques, human-led |
| 4 | [office-hours][r4] | 69 | Product pressure test |
| 5 | [Superpowers brainstorming][r5] | 67 | Design gate |
| 6 | [scientific-brainstorming][r6] | 66 | Group convergence protocol |
| 7 | [idea-refine][r7] | 65 | Lightweight one-pager |
| 12 | [workshop (consult-llm)][r12] | 64 | Cross-model design workshop |
| 13 | [sparring-partner][r13] | 64 | Full diverge/converge/pre-mortem session |
| 14 | [ia-ideate][r14] | 64 | Codebase improvement ideas |
| 20 | [ADHD][r20] | 63 | Isolated parallel frames |

Domain-specific skills that rank in the same range are listed in 4.6 instead: the UX and visual-design tools at ranks 15 and 16, the product skills at 18 and the marketing pair at 19.

### 4.2 Methodologies / frameworks with an ideation phase

| Rank | Tool | Score | Ideation phase |
|---|---|---|---|
| 10 | [nWave DIVERGE][r10] | 64 | JTBD, research, then SCAMPER + Crazy 8s, then a locked-weight matrix |
| 21 | [openspec-explore][r21] | 63 | "Stance, not workflow" discovery |
| 29 | [idea-validation-agents][r29] | 63 | Trend mapping, then up to 10 ideas, then scoring |
| 40 | [AI-DLC Ideation][r40] | 62 | Gated questionnaires, no divergence |
| 41 | [/gsd:explore][r41] | 62 | Socratic routing |
| 42 | [specs.md Spark/Flame/Forge][r42] | 62 | Domain wheel, then Six Hats, then Disney |
| 48 | [HarnessFlow][r48] | 62 | Blind diversifier for plans |
| 58 | [reversa-brainstorm][r58] | 61 | Framer, Explorer, Challenger, Arbiter |
| 92 | [Pilot Shell /prd Ideate][r92] | 59 | 3-5 directions per round (proprietary) |
| 94 | [StartupKit][r94] | 59 | Problem mining toward 20-50 problems |

BMAD and Superpowers are frameworks too; their brainstorming skills are ranked under 4.1.

### 4.3 MCP servers

None reaches B tier. MCP servers add *capabilities*: other models, a board, market or domain data, stimuli. They do not add facilitation.

| Rank | Tool | Score | What it adds |
|---|---|---|---|
| 139 | [Miro MCP][r139] | 57 | A shared board for clustering and dot voting |
| 179 | [Mobbin MCP][r179] | 55 | Real UI screens as inspiration (paid) |
| 201 | [Haft][r201] | 54 | 3-5 variants that differ in kind, compared without scalar scores |
| 213 | [TRIZ Skills MCP][r213] | 53 | TRIZ contradiction solving over n8n |
| 217 | [InfraNodus MCP][r217] | 53 | Structural-gap questions from text graphs |
| 224 | [mcp-rubber-duck][r224] | 52 | Council, debate and vote across LLMs and CLI agents |
| 234 | [out-the-box-thinking][r234] | 52 | Stateful Six Hats sequencer |
| 239 | [brainstorm-mcp][r239] | 51 | Multi-round multi-model debate |
| 262 | [deliberation][r262] | 50 | Blind multi-model verdicts |
| 263 | [PatSnap MCP][r263] | 50 | TRIZ solution engine plus patent novelty checks |

### 4.4 Multi-model / multi-agent councils

These are grouped across categories. S&P means skills and plugins. The ranked records passed to this report carry per-criterion divergence and convergence scores only for ranks 1-60, so for the C-tier entries the last column shows the check level instead.

| Rank | Tool | Category | Score | Divergence / convergence (or check level) |
|---|---|---|---|---|
| 12 | [workshop (consult-llm)][r12] | S&P | 64 | 3 / 4 |
| 23 | [Council of High Intelligence][r23] | S&P | 63 | 3 / 4 |
| 50 | [jam (wicked-garden)][r50] | S&P | 62 | 3 / 4 |
| 55 | [MassGen][r55] | Council | 62 | 3 / 4 |
| 86 | [claude-council][r86] | S&P | 60 | not listed (light check) |
| 140 | [council (ECC)][r140] | S&P | 56 | not listed (full check) |
| 141 | [Claude Octopus][r141] | S&P | 56 | not listed (full check) |
| 149 | [/debate (AgentSys)][r149] | S&P | 56 | not listed (light check) |
| 163 | [Claude Code Agent Teams][r163] | Council | 56 | not listed (critic check; a runtime for councils, not a council itself) |
| 250 | [argue][r250] | Council | 51 | not listed (light check) |

### 4.5 Research-ideation systems

| Rank | Tool | Score | Usable from agents? |
|---|---|---|---|
| 3 | [ARIS idea-discovery][r3] | 72 | Yes (CC, Codex) |
| 8 | [Google Co-Scientist][r8] | 65 | No |
| 11 | [DARE][r11] | 64 | Yes, but Claude Code-centric |
| 17 | [Ai2 AutoDiscovery][r17] | 64 | No (CLI or hosted) |
| 24 | [DeepScientist][r24] | 63 | Yes, as a runner platform |
| 25 | [ResearchStudio-Idea][r25] | 63 | Yes (CC, Codex); filed as a skill pack (SP) in the master table |
| 60 | [EvoMap AutoResearch][r60] | 61 | Its execution stage runs in Claude Code |
| 85 | [InternAgent][r85] | 60 | Uses CC as a backend |
| 100 | [AutoResearchClaw][r100] | 59 | Via ACP |
| 113 | [AutoSci /novelty][r113] | 58 | Yes |

### 4.6 Domain packs

| Domain | Top picks (rank, score) |
|---|---|
| Product | [brainstorm-ideas-new][r18] (18, 63), [vibe-check][r27] (27, 63), [idea-validation-agents][r29] (29, 63), [product-brainstorming][r33] (33, 62), [show-me-the-money][r46] (46, 62), [pm-skills (product-on-purpose)][r77] (77, 60), [opportunity-solution-tree][r199] (199, 54), [lenny-skills][r220] (220, 52) |
| Creative / marketing / naming | [marketing-ideas + council][r19] (19, 63), [creative-writing-skills][r45] (45, 62), [oh-story][r52] (52, 62), [creative-director-skill][r72] (72, 60), [brand-ideation][r75] (75, 60), [short-drama-develop][r80] (80, 60), [screenwriting-skills][r148] (148, 56), [naming][r186] (186, 54) |
| UX / visual design | [Claude Design][r9] (9, 65), [/explore-options (designer-skills)][r15] (15, 64), [design-shotgun + plan-ceo-review][r16] (16, 64), [parallel-concepts + concept-selection][r31] (31, 63, a duplicate of #15), [Superdesign][r191] (191, 54) |
| Games | [gds-brainstorm-game][r26] (26, 63), [unikit-gd-brainstorm][r30] (30, 63), [CCGS brainstorm][r56] (56, 61), [game-concept][r96] (96, 59) |
| Strategy / decisions | [Council of HI][r23] (23, 63), [scientific-problem-selection][r35] (35, 62), [the-fool][r74] (74, 60), [dbs-chatroom][r111] (111, 58), [cc-thinking-skills][r127] (127, 57) |
| Science / academic | [scientific-brainstorming][r6] (6, 66), [brainstorming-research-ideas][r34] (34, 62), [academic-research-skills][r38] (38, 62), [Research Companion][r44] (44, 62), [hypothesis-gen][r53] (53, 62) |

### 4.7 Technique and prompt libraries

This table groups tools by function. In the master table most of them are categorized as skills and plugins (SP); only Fabric is filed as Tech, and Verbalized Sampling as Res.

| Rank | Tool | Score | What it offers |
|---|---|---|---|
| 36 | [lateral-thinking (danium)][r36] | 62 | 8 techniques, a symptom router, quantity targets |
| 123 | [creative-thinking-for-research][r123] | 57 | 8 frameworks for creative blocks |
| 127 | [cc-thinking-skills][r127] | 57 | 28 manual thinking procedures, including TRIZ |
| 128 | [bmad-advanced-elicitation][r128] | 57 | A catalog of methods for reworking any output |
| 131 | [triz (tome)][r131] | 57 | TRIZ with cross-domain search |
| 134 | [SCAMPER (v0lka)][r134] | 57 | Web-grounded SCAMPER with 5-12 variants per letter |
| 147 | [verbalized-sampling (AIWG)][r147] | 56 | Verbalized-probability tail sampling |
| 202 | [creative-ideation (Hermes)][r202] | 53 | Routes by phase to de Bono, TRIZ, pataphysics |
| 240 | [Fabric idea patterns][r240] | 51 | One-shot extraction and idea-compass prompts |
| 261 | [Verbalized Sampling (paper/library)][r261] | 50 | The underlying technique |

---

## 5. Deep-dive cards: S and A tiers

Install commands are copied from the verified records. "Not documented" means the source gives no command for that platform. Reviewer findings come from the adversarial evidence and ideation challenges. Where a tool was not challenged, its score is single-pass.

### #1 [ce-ideate + ce-brainstorm (Compound Engineering plugin)][r1] - S, 82

- **What it is:** Two skills inside Every Inc's Compound Engineering plugin (MIT; 30+ skills). The plugin is authored and maintained by Kieran Klaassen and Trevin Chow, and tmchow is the top committer. ce-ideate generates and ranks ideas. ce-brainstorm turns the chosen idea into requirements.
- **How it brainstorms:** ce-ideate settles the subject in at most 3 questions, with a "Surprise me" option. It then grounds in parallel: repo scan, learnings, web research, and optionally the issue tracker or Slack. It splits the topic into 3-5 orthogonal axes, and a scout collects file:line evidence for each one. The default fleet is 5 subagents (3 generation-tier plus 2 ceiling-tier) working six frames: pain/friction, inversion/removal/automation, assumption-breaking, leverage/compounding, cross-domain analogy and constraint-flipping. Together they produce about 36-48 raw ideas. The first few obvious ideas count as warm-up, and each idea is tagged with its basis (direct, external or reasoned). After merging, the skill combines ideas across frames and runs recovery agents for any empty axis. A fresh-context verifier then tries to refute each basis. The orchestrator ranks 5-7 survivors, each with a rejection reason list, a confidence of 0-100% and a complexity rating, and writes them to HTML or Markdown. ce-brainstorm then asks one question at a time, pressure-tests the idea for evidence, specificity, counterfactual and durability gaps, and offers 2-3 approaches (one non-obvious). It writes a requirements plan when the work warrants one.
- **Install, Claude Code:** `/plugin marketplace add EveryInc/compound-engineering-plugin`, then `/plugin install compound-engineering`. Invoke `/ce-ideate [focus] [output:md]` and `/ce-brainstorm [idea]`. Optionally run `/ce-setup` in a project.
- **Install, Codex:** `codex plugin marketplace add EveryInc/compound-engineering-plugin`, then `codex plugin add compound-engineering@compound-engineering-plugin`. Invoke as `$ce-ideate` / `$ce-brainstorm`. In the Codex app: Plugins > Add marketplace. Pi: `pi install git:github.com/EveryInc/compound-engineering-plugin`.
- **Best for:** Finding high-leverage improvements in an existing codebase, mining issue-tracker themes, and turning a chosen idea into a plan. It also works for non-software ideation such as naming, strategy and personal decisions.
- **Weaknesses and risks:** A default repo-grounded run costs roughly 10-16 subagent dispatches and about 130 KB of orchestrator instructions. The optional paths run bundled scripts: `elevation-dispatch.sh` invokes the claude CLI and may request Codex sandbox escalation, `packs-resolve.py` git-clones third-party packs, and there is a local webserver for visual probes. Ideation files in docs/ideation have no defined lifecycle (#1626). Releases come almost daily, so skill names drift. There are open portability issues for Pi subagents (#1507) and Devin (#1734).
- **Adoption and maintenance:** 25,216 stars. skills.sh counts ce-brainstorm at 3.6K and ce-ideate at 3.1K. Release v3.28.2 came out on 2026-09-22 and the repo was pushed 2026-09-23. The npm package is stuck at 3.8.3 and is no longer the install path, so its download counts mean little.
- **What reviewers found:** Snyk rates both skills **MEDIUM (W011)**, not "low", because they read issue-tracker or Slack content, which is a prompt-injection path. There is no eval of idea quality: the eval harness covers review and work skills only. Judgment is only partly deferred, because each agent cuts its own list before submitting. Ranking favors ideas with direct evidence in the repo over reasoned ones, which pushes results toward incremental ideas. A novelty/feasibility critic runs only under "go deep". In non-software Quick and Standard runs, all frames run in one context. Verdict on ideation: **confirmed as a real divergence-then-convergence engine.**

### #2 [bmad-brainstorming (BMAD-METHOD)][r2] - S, 73

- **What it is:** BMAD's core brainstorming skill. The same package holds bmad-forge-idea (persona attack/defend), Analyst Mary's brainstorming menu item and a Brainstorming Coach web bundle. MIT, by BMad Code, LLC.
- **How it brainstorms:** It opens with one compound question covering topic, goal and inputs. You then pick a stance: Facilitator, where the AI contributes no ideas; Partner, where you trade ideas with attribution; or Ideate-for-me. You also pick 3-4 techniques, in a browser composer page or in chat. The techniques come from a 108-row, 13-category CSV that `brain.py` serves lazily (list, random draw, show). The skill can also "invent N" new techniques. The rules: one prompt per message, no menus, aim past 100 ideas, shift domain every 5-10 turns. Everything goes to an append-only, resumable memlog. Convergence uses one method (affinity, impact-effort, NUF, forced ranking, PMI or MoSCoW), with up to 3 chained. Subagents then build an HTML keepsake and an intent doc for bmad-product-brief or a PRD.
- **Install, Claude Code:** `/plugin marketplace add bmad-code-org/bmad-plugins`. Skills CLI: `npx skills add bmad-code-org/BMAD-METHOD --skill bmad --skill bmod-core-tools --skill bmod-method --skill bmad-build`. Setup needs uv; then ask the `bmad` skill to run `bmad setup` and say "help me brainstorm". The docs disagree on the plugin name: the README says `bmad-core-tools`, but marketplace.json only lists `bmad-toolbox`, which contains bmad-brainstorming.
- **Install, Codex:** `codex plugin marketplace add bmad-code-org/bmad-plugins`, or the `npx skills` route above. Web bundles for Gemini Gems and ChatGPT GPTs are downloaded from bmadcode.com/web-bundles.
- **Best for:** Human-led product or feature ideation before a brief or PRD. Also good for getting a stuck person moving, and for running flat-rate planning sessions in Gemini or ChatGPT.
- **Weaknesses and risks:** On activation it runs `uv run {project-root}/_bmad/scripts/*.py` from the working tree with no provenance check (#2624; no maintainer response since July). The path-traversal fix **PR #2627 was closed unmerged**, so `resolve_detail()` is still unguarded (#2625 is open). A bare `uv run` can take over a Python project's `.venv` (#2823). Snyk shows Warn. The core skill does no web research.
- **Adoption and maintenance:** 53,360 stars. skills.sh shows 2.9K installs, but every BMAD skill has an almost identical curve, so these are bulk collection installs. Before 2026-08-20 there were only about 20-35 per week. v6.12.0 was released 2026-09-04, and the skill folder was committed 2026-09-21.
- **What reviewers found:** All 108 technique rows have an **empty detail field**, so each technique is one line, and how deeply it is applied depends on the model. There is no parallel or multi-model generation: in Ideate-for-me mode one context produces all 100+ ideas. In Facilitator mode the agent deliberately supplies no ideas. Convergence methods are one-liners, with no weighted scoring or tournament. bmad-forge-idea is strong but separate. Divergence dropped from 5 to 4 and convergence from 4 to 3.

### #3 [idea-discovery / idea-creator (ARIS)][r3] - S, 72

- **What it is:** Part of ARIS ("Auto-claude-code-research-in-sleep"), an autonomous ML research harness by wanshuiyin (Ruofeng Yang) with 78+ contributors. MIT. It has 84 skills.
- **How it brainstorms:** `/idea-discovery` chains research-lit, idea-creator, novelty-check, research-review and research-refine-pipeline. idea-creator surveys local PDFs plus 5 or more web queries and maps structural gaps. It gives one Claude subagent to each gap lens: method-transfer, contradiction, untested-assumption, scaling-regime and diagnostic. It also sends one identical bundle to two OpenAI models through Codex, asking each for 8-12 ideas. Candidates are deduplicated mechanically by slug. A cross-model devil's advocate triages them, novelty-check verifies the top picks, and GPU pilots re-rank them. Output: IDEA_REPORT.md, FINAL_PROPOSAL and EXPERIMENT_PLAN.
- **Install, Claude Code:** `claude plugin marketplace add wanshuiyin/Auto-claude-code-research-in-sleep`, then `claude plugin install aris@aris`, then `/aris:setup` once and restart. Invoke `/aris:idea-discovery "direction"`. Symlink route: `git clone https://github.com/wanshuiyin/Auto-claude-code-research-in-sleep.git`, then `bash Auto-claude-code-research-in-sleep/tools/install_aris.sh ~/your-project`. Reviewer setup: `npm install -g @openai/codex && codex login`, then `claude mcp add codex -s user -- python3 "$(pwd)/Auto-claude-code-research-in-sleep/mcp-servers/codex-exec/server.py"`.
- **Install, Codex:** `bash tools/install_aris_codex.sh ~/your-codex-project`, or `.\tools\install_aris.ps1 C:\path\to\your-codex-project -Platform codex`.
- **Best for:** Turning a broad ML research direction into ranked, novelty-checked, pilot-tested paper ideas, including overnight runs.
- **Weaknesses and risks:** `allowed-tools` includes `Bash(*)`. AUTO_PROCEED=true is the default, so it launches GPU pilots on its own (up to 8 GPU-hours). Research content goes to OpenAI. The skill tells the agent to write large files "silently". The prompts hard-code "senior ML researcher" and 8x RTX 3090, so product brainstorming is out of scope.
- **Adoption and maintenance:** 16,524 stars. skills.sh: idea-discovery 511, idea-creator 507. Last push and release v0.4.27 on 2026-09-18. The skills last changed 2026-09-06.
- **What reviewers found:** The authors' tech report (arXiv 2605.03042) admits "the absence of controlled evaluation". In issue #149 a heavy user found the forced workflow no better than a 30-minute plan. Issue #147 describes an 8-hour run that used about 10M tokens. The maintainer confirmed over-defensive novelty kills and fixed them in PR #419, and the lens fan-out (added 2026-05-29) and two-model union (2026-08-26) are new and unproven. **The "cross-family jury" is not independent:** triage runs on the same GPT thread that generated one of the candidate sets, and in the Codex mirror GPT both generates and judges. Issue #284: the fan-out can silently collapse into the model making up ideas itself. Interaction dropped to 2 and trust to 3.

### #4 [office-hours (gstack)][r4] - S, 69

- **What it is:** Garry Tan's YC-style "office hours" skill inside gstack. MIT.
- **How it brainstorms:** It reads CLAUDE.md, git log and the code, and asks which of six goals you have, which maps to Startup or Builder mode. Startup mode asks six forcing questions one at a time (demand reality, status quo, desperate specificity, narrowest wedge, observation, future-fit) under anti-sycophancy rules. Builder mode asks five generative questions such as "coolest version" and "10x version". It then greps prior design docs and runs a privacy-gated web search (explicitly "NOT competitive research"). It asks you to agree or disagree with each premise. An optional cold read by Codex or a Claude subagent follows. It requires 2 approaches, 3 preferred ("minimal viable" and "ideal architecture"; the lateral one is optional), with effort and risk for each, and you choose. The design doc then goes through an adversarial review of up to 3 rounds before handoff to `/plan-*-review`.
- **Install, Claude Code:** `git clone --single-branch --depth 1 https://github.com/garrytan/gstack.git ~/.claude/skills/gstack && cd ~/.claude/skills/gstack && ./setup`, then `/office-hours`.
- **Install, Codex:** `git clone --single-branch --depth 1 https://github.com/garrytan/gstack.git ~/gstack && cd ~/gstack && ./setup --host codex` (installs to `${CODEX_HOME:-~/.codex}/skills/gstack-*/`). Requires Git and Bun, plus Node on Windows. OpenClaw: `clawhub install gstack-openclaw-office-hours`.
- **Best for:** Pressure-testing a startup or internal venture idea before any code, and getting a second model to challenge your premises.
- **Weaknesses and risks:** SKILL.md is 85 KB, and a full Startup session loads about 136 KB. `./setup` builds binaries and registers a default-on Stop hook in `~/.claude/settings.json`. Remote telemetry is opt-in. The closing contains a YC pitch and `?ref=gstack` links. Socket and Snyk both show Warn.
- **Adoption and maintenance:** 133,943 stars. skills.sh counts the skill alone at 560. The skill last changed 2026-09-22 (v1.87.6.0).
- **What reviewers found:** The evals only score tone with a Sonnet judge; there is no baseline. Issue #1644: a doc was approved with a 9/10 self-score while 3 of its 7 premises were false. #1049: sessions marked "success" without a design doc. #2719: in Conductor the forcing questions are never asked. **On Codex, AskUserQuestion degrades and the model makes up answers (#1066).** OpenCode builds contain Claude-only tools (#2626). Divergence is thin: no technique library and no quantity target. Ease dropped to 1, portability to 3 and trust to 2.

### #5 [brainstorming (obra/superpowers)][r5] - S, 67

- **What it is:** The Superpowers design-first brainstorming skill by Jesse Vincent (Prime Radiant). MIT. You already know it; this card records what the verification found.
- **How it brainstorms:** It triggers on its own before creative work and routes each request to a spike, bounded or architectural path. **Only the architectural path** asks questions one at a time, proposes 2-3 approaches that lead with a recommendation, gets approval section by section, writes a dated spec to `docs/superpowers/specs`, self-reviews and hands off to writing-plans. Spike is a 2-3 sentence probe. Bounded is one short in-chat design with no alternatives and no spec.
- **Install, Claude Code:** `/plugin install superpowers@claude-plugins-official`, or `/plugin marketplace add obra/superpowers-marketplace` then `/plugin install superpowers@superpowers-marketplace`. Invoke with `/brainstorming`; it also triggers on its own.
- **Install, Codex:** Codex CLI: run `/plugins`, search for `superpowers` and choose Install Plugin (it is in the official Codex marketplace). Codex App: Plugins sidebar > Superpowers > +.
- **Best for:** Gating implementation behind an approved design. Requirements elicitation. Breaking big projects into sub-projects.
- **Weaknesses and risks:** A SessionStart hook injects a "1% chance ... ABSOLUTELY MUST invoke" directive, and the maintainer has declined requests for an off switch (#645, #938, #2000; one user logged 15 of 26 GPT-5.6 sessions auto-starting). The skill is about 2,600 words. The optional visual companion loads a logo from primeradiant.com with the version number attached (opt out with `SUPERPOWERS_DISABLE_TELEMETRY`).
- **Adoption and maintenance:** 290,246 stars. 1,009,371 installs on the Claude plugin page, and 372.8K on skills.sh for this skill. v6.4.1 was released 2026-09-19.
- **What reviewers found:** Open issue #1266: the first recommendation often flips when the agent is asked for deeper analysis. #2129: the skill does no prior-art research. It has no named techniques, no quantity targets and no deferred judgment. Leading with a recommendation, preferring multiple-choice questions and applying YAGNI all anchor on the model's first idea. The spec-reviewer subagent was removed for "no measurable quality gain". Divergence is 1/5.

### #6 [scientific-brainstorming (K-Dense Scientific Agent Skills)][r6] - S, 66

- **What it is:** A v1.2 facilitation and governance protocol for human research groups, from K-Dense's 166-skill collection. MIT.
- **How it brainstorms:** It has 10 steps: scope, diversify perspectives (real people), private idea generation, then share without judging, cluster, set weighted criteria with anchors, adversarial review by someone other than the originator, a literature check that reopens generation, ethics and feasibility gates, and a decision log kept by the human owner. The AI may act only after the human round is frozen, and only in limited, disclosed roles. Prompt families (SCAMPER, morphological analysis, constraint ladder, premortem) live in a reference file. Standard-library Python CLIs validate a JSON register and compute a weighted matrix with sensitivity analysis. The skill **never picks a winner**.
- **Install, Claude Code:** `npx skills add https://github.com/k-dense-ai/scientific-agent-skills --skill scientific-brainstorming`. Or `gh skill install K-Dense-AI/scientific-agent-skills <skill-name>` with `--agent claude-code`.
- **Install, Codex:** The same `npx skills` / `gh skill install ... --agent codex`. From a local checkout: `codex plugins install .` (the README says to confirm the flags).
- **Best for:** Lab or team sessions where the group must converge transparently and record dissent.
- **Weaknesses and risks:** SKILL.md tells the agent to insert K-Dense's own arXiv paper into your manuscripts or code releases and to tell you only afterwards. Mirrors (Smithery, aitmpl) serve a stale v1.0. Installing the whole collection costs about 7% of a 200K context window in descriptions.
- **Adoption and maintenance:** 46,157 stars for the collection. skills.sh shows 1.9K installs, about the same as every top skill in the collection, which suggests bulk installs. v2.69.0 was released 2026-09-11.
- **What reviewers found:** The collection paper (arXiv 2609.00065) reports "no task-level evaluation". For a single user, the skill mostly tells the agent to hold back its own ideas. Evidence 1, adoption 3, trust 3. The real strength is convergence (4/5).

### #7 [idea-refine (addyosmani/agent-skills)][r7] - S, 65

- **What it is:** Addy Osmani's idea-refinement and product-scoping skill. MIT. It is plain markdown, and its only script runs `mkdir docs/ideas`.
- **How it brainstorms:** Phase 1: restate the idea as a How-Might-We question, ask 3-5 sharpening questions in one AskUserQuestion batch, optionally scan the codebase, and generate 5-8 variations through seven lenses (inversion, constraint removal, audience shift, combination, simplification, 10x, expert). Phase 2, after you react: cluster the variations into 2-3 directions and stress-test value, feasibility and differentiation. Then run an assumption audit and a value x feasibility matrix. Phase 3: a one-pager with a "Not Doing" list, saved to `docs/ideas/` only if you confirm.
- **Install, Claude Code:** `npx skills add addyosmani/agent-skills --skill idea-refine`, or `/plugin marketplace add addyosmani/agent-skills` then `/plugin install agent-skills@addy-agent-skills`.
- **Install, Codex:** Codex CLI v0.122+: `codex plugin marketplace add addyosmani/agent-skills`, then `codex plugin add agent-skills@agent-skills`. Invoke with `@idea-refine`.
- **Best for:** Turning a vague product or feature concept into an MVP one-pager before writing a spec.
- **Weaknesses and risks:** Low. AskUserQuestion is Claude-specific, and other agents fall back to plain questions. Loading every reference costs about 40 KB. PR #424, which would make the skill agent-neutral, has been open since July.
- **Adoption and maintenance:** 98,483 stars. skills.sh shows 37.3K installs, but every skill in the pack has 32.5K-47.7K, so these are bundle installs; this skill ranks 16th of 25. It last changed 2026-06-25.
- **What reviewers found:** It forbids 20 or more ideas, which contradicts the "quantity breeds quality" principle. It judges ideas during Phase 1. frameworks.md is optional. The only eval has only been run as a dry run. It is refinement more than divergence.

### #8 [Google Co-Scientist][r8] - S, 65

- **What it is:** Google's six-agent hypothesis generator, offered in Gemini Enterprise (restricted Preview) and as Google Labs "Hypothesis Generation" (waitlist). Proprietary.
- **How it brainstorms:** A Supervisor turns your research goal into a plan configuration. Generation proposes hypotheses from literature search, simulated debates, assumption chaining and research expansion. Reflection runs six review types. Ranking runs an Elo tournament: pairwise debates, multi-turn for top pairs. Proximity clusters and deduplicates. Evolution combines, simplifies and adds out-of-box variants. Meta-review writes an overview, an NIH Specific Aims page and contacts.
- **Install, Claude Code:** Not documented (no API, MCP or skill).
- **Install, Codex:** Not documented. Enterprise: "contact your Google account team". Individuals: register interest at labs.google/science.
- **Best for:** Biomedical hypothesis generation, and as a **reference architecture** for building tournament-style ideation skills.
- **Weaknesses and risks:** Closed and cannot be audited. Your data goes to Google Cloud. It covers science only. In July 2026 Google removed its separate public-preview Idea Generation agent.
- **What reviewers found:** The Elo "validation" is a correlation with GPQA-diamond accuracy, and the system's own ranking agent computes the Elo, so the argument is circular. The expert study covered only 11 research goals. No wet-lab result is compared against hypotheses from a baseline LLM. Google itself calls the cf-PICI result an "independent rediscovery". Evidence 4, trust 3. The correct release-note date is 2026-07-14. **Duplicate record:** #71 is the same system under the DeepMind blog URL.

### #9 [Claude Design (Anthropic Labs)][r9] - A, 65

- **What it is:** Anthropic's first-party design canvas (research preview). It lives on claude.ai/design, in the Artifacts tab, and in Claude Code as `/design`.
- **How it brainstorms:** It takes in your design system from a repo, files or a URL, then may ask one batch of clarifying questions. It renders directions as artboards side by side, usually 2-4 in hands-on reports. You compare them and refine with inline comments, direct edits and Tweak sliders it generates. It checks output against your design system, then exports or hands off to Claude Code.
- **Install, Claude Code:** Nothing to install. You need a Pro, Max, Team or Enterprise plan and Claude Code v2.1.265 or later. Run `/design <brief>` and `/design-sync`.
- **Install, Codex:** Not documented / not supported.
- **Best for:** Exploring several UI, landing-page or slide directions before building.
- **Weaknesses and risks:** It covers visual ideas only and has no scoring; you pick by eye. It is token-hungry and uses the shared plan limit. There is no version history. A user lost access to all projects after unsubscribing (HN, 302 points). It is not available with ZDR, HIPAA or CMEK.
- **Adoption and maintenance:** Anthropic says more than 1M people used it in the first week. It got a major update on 2026-06-17, and `/design` arrived in Claude Code on 2026-08-17.
- **What reviewers found:** The Claude Code "types" mode commits to **one** look by default. The bundled canvas skill asks for 2-4 low-fi directions along named axes, each with a tradeoff. Several HN critics say output converges on safe, homogeneous UI. Trust is 3. Treat it as a visual exploration tool, not a general brainstormer.

### #10 [nw-brainstorming / nw-diverge (nWave)][r10] - A, 64

- **What it is:** The DIVERGE wave of the nWave methodology, run by the Flux agent. MIT.
- **How it brainstorms:** It runs four gated phases. JTBD: 5 Whys plus at least 3 ODI outcome statements. Research: at least 3 real competitors, one of them non-obvious. Brainstorm: a How-Might-We question with no embedded solution, one option per SCAMPER letter, plus 2-4 Crazy 8s. Options are cut to 6 with a mechanism/assumption/cost diversity test and must contain no judging language. Taste: DVF filter, a locked-weight matrix, top 3 with a dissenting case. A Prism reviewer (Haiku) critiques, with at most 2 revisions.
- **Install, Claude Code:** `sh -c "$(curl -fsSL https://raw.githubusercontent.com/nWave-ai/nWave/main/scripts/install/install.sh)"`, or `uv tool install nwave-ai` (or `pipx install nwave-ai`) then `nwave-ai install`. Plugin (beta, without DES hooks): `/plugin marketplace add nwave-ai/nwave` then `/plugin install nw@nwave-marketplace`. Usage: `/nw-diverge {feature-id}`.
- **Install, Codex:** `uv tool install nwave-ai`, then `nwave-ai install --platform codex`. This is documented for DES hooks only; diverge support is not documented.
- **Best for:** Greenfield products and pivots where you want SCAMPER coverage and a defensible matrix.
- **Weaknesses and risks:** The install is `curl | sh` and adds 23 agents, 197 skills and global hooks on 5 events. It enables commit attribution by default. A DIVERGE run takes 2-4 hours. Only about 9-11 raw options. Windows needs WSL.
- **Adoption and maintenance:** 617 stars and 7 skills.sh installs. v3.22.2 was released 2026-09-16.
- **What reviewers found:** Not challenged; the score is single-pass.

### #11 [DARE (de-anthropocentric-research-engine)][r11] - A, 64

- **What it is:** A research engine of about 920 markdown skills in four layers (campaign, strategy, tactic, SOP), by yogsoth-ai / Pthahnix. Apache-2.0.
- **How it brainstorms:** A creative-ideation entry skill routes to 10 campaigns: SCAMPER/TRIZ/SIT, bisociation, assumption destruction, biomimicry, synectics, Zwicky morphology, lateral thinking (PO, random entry, concept fan, Six Hats), concept blending, perspective forcing and enumeration. It runs 3-5 campaigns in parallel with Opus subagents. PO provocation requires at least 10 provocations. Saturation detection stops generation, a 5-part novelty score assigns tiers, and a convergence package ranks the results (AHP, Bradley-Terry, Pareto) before a stress test.
- **Install, Claude Code:** `npx skills add yogsoth-ai/de-anthropocentric-research-engine` (or with `-a claude-code -g`). Invoke `/de-anthropocentric-research-engine`, then `/executing-specs <spec path>`. Requires Node.js 22+.
- **Install, Codex:** `git clone https://github.com/yogsoth-ai/de-anthropocentric-research-engine.git ; cd de-anthropocentric-research-engine ; ./install/codex.sh --target /path/to/your/project` (Windows: `.\install\codex.ps1`).
- **Best for:** Escaping paradigm lock-in on research questions and mapping a design space exhaustively.
- **Weaknesses and risks:** Each strategy budgets 48-65 lookups, and the lateral-thinking campaign alone budgets 288. Subagents default to Opus. `creative-ideation` requires north-star and hypothesis-formation to run first. The descriptions total about 135k characters, which overflows Claude Code's skill listing too (#16: it falls back to "the obvious 3-5 skills"). Codex support is a workaround (#30 open).
- **Adoption and maintenance:** 498 stars, 25 skills.sh installs and 25 npm downloads a month. Last commit 2026-09-16, from a single maintainer.
- **What reviewers found:** RFC #21 admits there is no quality evaluation. The "random" words are chosen by the LLM, with no RNG. Bradley-Terry and Elo are computed in prose. The model scores its own novelty, and BREAKTHROUGH ideas pass regardless of feasibility. It asks you nothing during ideation. Evidence 1, portability 3, trust 3.

### #12 [workshop (consult-llm)][r12] - A, 64

- **What it is:** A design-workshop skill shipped with the consult-llm Rust CLI by Raine Virta. MIT.
- **How it brainstorms:** An optional `--consult-first` step has several models propose 4-8 clarifying questions. Phase 1 is an LLM-free AskUserQuestion dialogue, one question at a time, that produces a problem statement with constraints, success criteria and out-of-scope items. Phase 2 is one parallel consult-llm call in which each model independently proposes 2-3 approaches with trade-offs. The agent deduplicates, drops approaches that violate constraints, and ranks by how distinct they are (at most 4). You pick one or a hybrid. Phase 3 is co-design section by section. Phase 4 has the same model threads red-team the design: blind spots, a risk register and a ship/revise/rethink verdict. You triage each finding.
- **Install, Claude Code:** `brew install raine/consult-llm/consult-llm`, or `curl -fsSL https://raw.githubusercontent.com/raine/consult-llm/main/scripts/install.sh | bash`. Configure backends, for example `consult-llm config set gemini.backend gemini-cli` and `consult-llm config set openai.backend codex-cli`, then `consult-llm install-skills`. Usage: `/workshop <idea>`, with `--gemini --openai`, `--max-approaches N`, `--no-critique` and `--consult-first`.
- **Install, Codex:** `consult-llm install-skills --platform codex` (writes to `~/.codex/skills`).
- **Best for:** Architecture decisions where a single model anchors on one approach.
- **Weaknesses and risks:** Your problem statement and attached files go to third-party providers. Every prompt and response is logged to `~/.local/state/consult-llm/consult-llm.log`. Each run costs several paid calls. No named creativity techniques.
- **Adoption and maintenance:** 138 stars. skills.sh does not list the skill. v3.0.36 was released 2026-09-22.
- **What reviewers found:** Not challenged; the score is single-pass.

### #13 [sparring-partner + ideation (data2story)][r13] - A, 64

- **What it is:** A brainstorming and stress-test skill from the data2story team. MIT. Light-verified.
- **How it brainstorms:** A six-phase session with phase tags. Frame, then Diverge with judgment banned: analogy, assumption reversal, 10x/0.1x, SCAMPER, HMW, forced combination, worst idea. Then Converge (Pugh matrix, ICE/RICE) and Pressure-test (pre-mortem, inversion, "steelman plus 3 objections", a roast dial). A living markdown doc records decisions, rejected ideas and open questions.
- **Install, Claude Code:** No standalone install is documented. Put the skill folder under `~/.claude/skills/`. It is bundled in the data2story-pro plugin via `.claude-plugin/marketplace.json`.
- **Install, Codex:** Not documented beyond "ask Codex to read the SKILL.md".
- **Best for:** Developing and stress-testing a product, research or business idea with a partner that pushes back.
- **Weaknesses and risks:** It asks 1-3 questions per turn. No quantity targets. The surrounding plugin needs an OpenRouter key for media.
- **Adoption and maintenance:** 156 stars; installs unknown. Last changed 2026-07-02.
- **What reviewers found:** Not challenged; light check only.

### #14 [ia-ideate / ia-brainstorming (Whetstone)][r14] - A, 64

- **What it is:** Ideation commands in Ilia Alshanetsky's Whetstone plugin. MIT.
- **How it brainstorms:** `/ia-ideate` reads the repo, the last 20 commits, issues and docs. It generates 10-15 ideas across 6 categories, applies 7 lenses, critiques each idea adversarially, drops the weak ones, and ranks the rest by impact/effort into a top 5-8 saved to `docs/ideation/`. `ia-brainstorming` interviews you through AskUserQuestion, compares 2-3 approaches and writes a design doc.
- **Install, Claude Code:** `/plugin marketplace add https://github.com/iliaal/whetstone ; /plugin install whetstone@iliaal-marketplace ; /reload-plugins`. Usage: `/ia-ideate`, `/ia-brainstorm [idea]`.
- **Install, Codex:** `bash scripts/install-codex-plugin.sh` from a clone. Only the skills work; the commands are Claude-only.
- **Best for:** Codebase improvement ideas grounded in git history. A lighter alternative to ce-ideate.
- **Weaknesses and risks:** Software only and no web research. The plugin ships an injection hook (needs bash and jq) and an MCP server. It adds a lot of context.
- **Adoption and maintenance:** 34 stars; installs not documented. v4.6.1 was released 2026-09-20.
- **What reviewers found:** Not challenged; light check only.

### #15 [/explore-options + parallel-concepts + concept-selection (designer-skills)][r15] - A, 64

- **What it is:** A six-step UX command from MC Dean's prototyping-testing plugin. MIT, pure markdown.
- **How it brainstorms:** First it fixes falsifiable criteria, each marked threshold or trade-off, before any concept exists. It sizes the concept set and chooses one behavioural axis for the concepts to differ on: sequence, unit of interaction, division of labour, entry point or commitment point. Each concept gets a wireframe spec at matched fidelity. User-flow diagrams merge concepts that are really duplicates. Each concept gets its own Nielsen heuristic evaluation. The winner is chosen with its cost stated, and every rejected concept gets a record of what it tested, why it lost, and what would revive it.
- **Install, Claude Code:** `/plugin marketplace add Owl-Listener/designer-skills`, then `/plugin install prototyping-testing@designer-skills`. Usage: `/prototyping-testing:explore-options [design problem or current concept]`.
- **Install, Codex:** Not documented. A skills.sh page offers `npx skills add https://github.com/owl-listener/designer-skills --skill parallel-concepts`.
- **Best for:** Breaking out of refining the first UI direction by default, and writing a "why not the other way" record for stakeholders.
- **Weaknesses and risks:** Few ideas, and no clarifying-question loop. It does not name a file for the decision record. It misnames a co-author of the Dow et al. 2010 paper it cites. The skills are about three weeks old.
- **Adoption and maintenance:** 2,724 stars. About 268 skills.sh installs per skill. Last push 2026-09-05.
- **What reviewers found:** Critic-added; no challenge block. **Duplicate:** #31 is the same toolset recorded from a different URL.

### #16 [design-shotgun + plan-ceo-review (gstack)][r16] - A, 64

- **What it is:** Two unrelated gstack skills: visual UI variants, and an 11-section CEO/engineering plan review. MIT.
- **How it brainstorms:** design-shotgun builds a brief and writes 3 text concepts by default (up to 8). A hard rule requires each concept to use a different font, palette and layout. Parallel subagents render each concept with OpenAI image generation, and you rate, comment, remix or regenerate on a localhost board. A taste profile decays 5% per week. plan-ceo-review runs its "10x check", "platonic ideal" and "delight scan" (at least 5 items) **only in the expansion modes**. Every item is accepted, deferred or skipped, with S/M/L/XL effort.
- **Install, Claude Code:** The gstack clone from card #4, then `/design-shotgun` or `/plan-ceo-review`. design-shotgun needs an OpenAI API key (`$D setup` or `OPENAI_API_KEY`).
- **Install, Codex:** `git clone --single-branch --depth 1 https://github.com/garrytan/gstack.git ~/gstack && cd ~/gstack && ./setup --host codex`. OpenClaw (CEO review only): `clawhub install gstack-openclaw-ceo-review`.
- **Best for:** Several visually distinct UI directions, and pushing a plan to be more ambitious.
- **Weaknesses and risks:** design-shotgun is about 53 KB, and CEO review is about 164 KB once its sections load. **design-shotgun fails on a fresh Codex install** (#1159; fix PR #2891 not merged). Image generation was broken for 12 weeks (#1771). It ships a Stop hook.
- **Adoption and maintenance:** 133,953 stars. skills.sh: design-shotgun 349, plan-ceo-review 460. Changed 2026-09-22.
- **What reviewers found:** The anti-convergence rule is enforced only by the prompt, and the vision gate does not check diversity. The taste profile and DESIGN.md both push toward a narrow range ("won't diverge by default"). The reviewer's "no YAGNI" dimension penalizes ambitious additions. Evidence 1, portability 3, ease 1.

### #17 [Ai2 AutoDiscovery / asta-autodiscovery][r17] - A, 64

- **What it is:** Allen Institute for AI's open-ended hypothesis search over tabular datasets. Apache-2.0.
- **How it brainstorms:** An AG2 multi-agent loop. A generator proposes k=8 falsifiable hypotheses per tree node, following a data-subset, then variables, then relationships heuristic. A programmer writes Python, a sandbox runs it, an analyst checks the result and a reviewer critiques it. A belief agent samples the LLM's prior and posterior. The resulting "Bayesian surprise" rewards an MCTS search (UCB1 with progressive widening). Optionally, embedding clustering plus LLM votes remove duplicates. Output: a ranked table, code and an HTML report.
- **Install, Claude Code:** Not documented (no skill, plugin or MCP). Standalone: `pip install asta-autodiscovery`, then `auto-discovery --name "..." --description "..." --intent "..." --n_experiments 20 --out_dir ./results data/measurements.csv`.
- **Install, Codex:** Not documented. Hosted: https://asta-autodiscovery.allen.ai/runs (free credits until 2026-12-31).
- **Best for:** Finding surprising patterns in structured scientific data, with code you can reproduce.
- **Weaknesses and risks:** It executes LLM-written Python, and the `local` backend is the least isolated. Hundreds of statistical tests create multiple-comparison risk. "Surprise" is measured against the LLM's own prior. Runs take hours.
- **Adoption and maintenance:** 12 stars. The hosted platform generated 46,000+ hypotheses in early access. Pushed 2026-09-22; v1.0.1.
- **What reviewers found:** Critic-added. It has a peer-reviewed NeurIPS 2025 paper with a baseline and expert evaluation, so evidence is 4.

### #18 [brainstorm-ideas-new / -existing (phuryn/pm-skills)][r18] - A, 63

- **What it is:** Two product-discovery skills by Paweł Huryn (Product Compass). MIT, plain markdown.
- **How it brainstorms:** A prompt of about 40 lines. It confirms the opportunity, may run a web search, and generates 5 ideas each from a PM, a Designer and an Engineer persona (15 total). It then ranks a top 5 on stated criteria, with assumptions to test, and saves markdown. `/brainstorm` adds Impact/Effort tags. `/discover` chains into assumption mapping, Impact x Risk and experiments.
- **Install, Claude Code:** `claude plugin marketplace add phuryn/pm-skills ; claude plugin install pm-product-discovery@pm-skills`. Usage: `/brainstorm ideas new <desc>`, `/discover <idea>`.
- **Install, Codex:** `codex plugin marketplace add phuryn/pm-skills ; codex plugin add pm-product-discovery@pm-skills`. The skills work, but the slash commands do not run.
- **Best for:** A solo PM simulating a product trio, feeding a discovery chain.
- **Weaknesses and risks:** Thin: it generates and ranks in one pass. Snyk shows Warn with no reason given. Its Further Reading links promote the author's paid courses.
- **Adoption and maintenance:** 26,540 stars. skills.sh: about 3.0K and 2.8K. The skill text has not changed since 2026-03-03.
- **What reviewers found:** Not challenged; the score is single-pass.

### #19 [marketing-ideas + marketing-council (coreyhaines31/marketingskills)][r19] - A, 63

- **What it is:** Two marketing skills by Corey Haines. MIT.
- **How it brainstorms:** marketing-ideas asks about stage, budget and so on, then **picks 3-5 ideas from a static catalog of 139 SaaS tactics**. marketing-council seats 1, 3-5 or 12 marketer personas built from sourced dossiers, with at least one required dissenter. It then produces a disagreement map (2-4 conflicts, each with the evidence that would settle it) and a chair's synthesis with a tripwire.
- **Install, Claude Code:** `npx skills add coreyhaines31/marketingskills` (use `--skill` to pick). Or `/plugin marketplace add coreyhaines31/marketingskills` then `/plugin install marketing-skills`. From inside an agent, add `-a claude-code`.
- **Install, Codex:** No Codex-specific command is documented. The README says the npx skills CLI detects installed agents.
- **Best for:** SaaS growth-channel shortlists, and stress-testing pricing, positioning or launch decisions with conflicting lenses.
- **Weaknesses and risks:** Snyk rates the council MEDIUM (W011) because of its live research pass. It simulates living marketers. Nothing is saved to a file.
- **Adoption and maintenance:** 51,243 stars. skills.sh: 131.3K and 31.9K installs, both largely from bulk installs of the whole collection. The council has not changed since 2026-07-06.
- **What reviewers found:** marketing-ideas **retrieves; it does not generate**. The council is a critique panel. The two skills do not reference each other. There are no eval results.

### #20 [ADHD (Parallel Divergent Ideation)][r20] - A, 63

- **What it is:** A divergent-ideation skill plus a Node CLI/TS library by Udit Akhouri. MIT.
- **How it brainstorms:** A pre-flight gate skips the run unless you invoked it explicitly or the problem is open-ended and high-stakes. It picks 5 of 15 frames (regulator, a 10-year-old, adversary, biology, markets, inversion, $0/infinite budget, remove the assumption, speedrunner, ant colony and more), always including one wild frame. It spawns 5 parallel, **isolated** subagents that are forbidden to evaluate. Each writes 6 ideas and must skip the first three obvious ones. A critic then scores novelty, viability and fit (weights 0.35/0.40/0.25), flags traps, clusters ideas by underlying angle and deepens the top 3. Output: clusters, a starred non-obvious pick, a trap list and one provocation.
- **Install, Claude Code:** `npx skills add UditAkhourii/adhd` (flags `-g`, `-a claude-code`). Manual: curl SKILL.md into `~/.claude/skills/adhd/`. Plugin (from PR #41, not the README): `/plugin marketplace add UditAkhourii/adhd`, then `/plugin install adhd@adhd`. Invoke `/adhd "your problem"`. CLI: `npm install -g adhd-agent`.
- **Install, Codex:** `npx skills add UditAkhourii/adhd -a codex -g`, or `mkdir -p ~/.codex/skills/adhd && curl -fsSL https://raw.githubusercontent.com/UditAkhourii/adhd/main/skills/adhd/SKILL.md -o ~/.codex/skills/adhd/SKILL.md`.
- **Best for:** Architecture and API-surface choices, naming, fuzzy debugging hypotheses, splitting a monolith.
- **Weaknesses and risks:** 5-10x the tokens of a plain prompt, and about 10 calls taking 30-90 seconds. **Without a parallel subagent tool (some Codex builds), everything runs in one context, which the skill itself says defeats the method.** No clarifying questions and no durable artifact. Critics object to the name.
- **Adoption and maintenance:** 4,265 stars, 6.5K skills.sh installs, 227 npm downloads a month. Last commit 2026-09-17.
- **What reviewers found:** Not challenged. The record notes a reproducible 6-problem bench and one independent blind 2-problem test. Experts quoted in The New Stack call these too small and prone to same-stack bias.

### #21 [openspec-explore (OpenSpec /opsx:explore)][r21] - A, 63

- **What it is:** OpenSpec's discovery "stance" skill, installed by default with `openspec init`. MIT, Fission-AI.
- **How it brainstorms:** It runs read-only `openspec list`, then reads specs, config and code. It works as a thinking partner (reframing, analogies, "brainstorm multiple approaches", ASCII diagrams, tradeoff tables). When you are planning a change, it asks one focused question at a time in order of which decisions depend on which. Only with your explicit consent does it write proposal, design, spec or task artifacts, then point you to `/opsx:propose`.
- **Install, Claude Code:** `npm install -g @fission-ai/openspec@latest`, then `openspec init` (or `--tools claude`). Invoke `/opsx:explore [topic]`.
- **Install, Codex:** `openspec init --tools codex`, or skills only via `npx skills add Fission-AI/OpenSpec`. Invoke `$openspec-explore`.
- **Best for:** Scoping a vague change against real specs and code in a spec-driven repo.
- **Weaknesses and risks:** CLI telemetry is **on by default** (PostHog via edge.openspec.dev; opt out with `OPENSPEC_TELEMETRY=0`). `allowed-tools: Bash(openspec:*)` pre-approves CLI commands that can write. Past unrequested writes (#1715) are fixed. Auto-triggering in repos that never ran init (#1645) is still open.
- **Adoption and maintenance:** 69,885 stars and about 1.8M npm downloads a month for OpenSpec. skills.sh counts 2.8K installs of this skill. v1.13.1 was released 2026-09-17.
- **What reviewers found:** It is not a brainstorming engine: divergence 1, convergence 2. Its own examples converge quickly ("SQLite. Not even close."). Explorations stay in chat and are lost unless you capture them. Trust is 3.

### #22 [grill-me (mattpocock/skills)][r22] - A, 63

- **What it is:** Matt Pocock's interview skill. Its body just calls the `grilling` skill. MIT.
- **How it brainstorms:** It maps the subject as a design tree of dependent decisions and asks in rounds. Each round covers the full "frontier" of decisions whose prerequisites are settled, as numbered questions, each with options and a recommended answer. Sub-agents look up facts, and you make the decisions. It ends when the frontier is empty and you confirm. It writes no files; follow up with `/to-spec`.
- **Install, Claude Code:** `claude plugins install mattpocock-skills`, or `/plugin install mattpocock-skills` in a session. Type `/grill-me`; the model does not invoke it on its own. It needs the `grilling` skill installed too.
- **Install, Codex:** `npx skills@latest add mattpocock/skills` (choose the skills, including setup-matt-pocock-skills). Single skill: `npx skills add https://github.com/mattpocock/skills --skill grill-me`.
- **Best for:** Sharpening a loose idea before any brainstorming or spec work. Works for non-code decisions too.
- **Weaknesses and risks:** No divergence. Recommended answers can anchor you. Passively agreeing yields "a confident plan the agent effectively wrote". Loading one skill from another fails in some harnesses (Copilot, T3 Code).
- **Adoption and maintenance:** 267,909 stars and 1.2M skills.sh installs. It is in the official Anthropic marketplace. Last changed 2026-08-15.
- **What reviewers found:** Not challenged; the score is single-pass.
- **Editor's note (2026-09-23): grill-with-docs.** Its sibling `grill-with-docs` is also a one-line manual-only wrapper: "Call the Skill tool twice, for "grilling" and "domain-modeling"". `domain-modeling` adds glossary challenges against `CONTEXT.md`, one canonical term per concept, edge-case scenarios, code-contradiction checks (file:line), and inline `CONTEXT.md` / gated ADR writes. mattpocock's docs recommend `grill-with-docs` in a repo and `grill-me` without a working directory. So for brainstorming inside a codebase, `grilling` + `domain-modeling` is the stronger framing pair. [docs/GUIDE.md](../docs/GUIDE.md) section 2.4 explains how the pipeline uses it (loading both by name, staging terms in the run folder until the idea is chosen). It was not scored separately here.

### #23 [Council of High Intelligence (/council)][r23] - A, 63

- **What it is:** A council plugin with 18 historical-thinker persona subagents, by 0xNyk. MIT.
- **How it brainstorms:** It picks a panel (an auto-matched triad, a named triad, a profile, or all 18) and locks a domain seat with 1.5x weight. It can route seats across Claude, Codex, Gemini, Ollama, Cursor and NIM, keeping opposing pairs on different providers. Members restate the problem and offer an alternative framing, analyze blind in parallel, then cross-examine anonymized peers under an anti-conformity rule. Dissent quotas, a novelty gate and forced counterfactuals kick in when agreement passes 70%. The vote is a confidence-weighted 2/3 tally. A Chairman outside the panel writes the verdict: kill criteria, a minority report and the next step.
- **Install, Claude Code:** `/plugin marketplace add 0xNyk/council-of-high-intelligence`, then `/plugin install council@council-of-high-intelligence`. Or `git clone https://github.com/0xNyk/council-of-high-intelligence.git && cd council-of-high-intelligence && ./install.sh`. Usage: `/council [problem]`, `--quick`, `--duo`, `--triad strategy`, `--dry-route`.
- **Install, Codex:** `./install.sh --codex-only`, or `./install.sh --codex` for Claude Code plus Codex.
- **Best for:** High-stakes architecture, build-vs-buy and strategy calls, and reframing a badly posed question.
- **Weaknesses and risks:** **Auto-routing is on by default** and sends your problem to any external CLI it detects. The Codex template runs `codex exec -c auto_approve=true`. Personas are modeled on living people. The coordinator is 55 KB, and full mode runs up to 18 subagents.
- **Adoption and maintenance:** 4,469 stars and 115 skills.sh installs. Last human commit 2026-08-20.
- **What reviewers found:** Not challenged. Its record notes it deliberates on a question you pose and does not generate options.

### #24 [DeepScientist][r24] - A, 63

- **What it is:** An autonomous research platform (daemon, web UI and TUI) by ResearAI, with an "idea" stage skill. Apache-2.0.
- **How it brainstorms:** The idea stage runs only after a baseline and metric exist. It surveys 5-10 papers, builds a limitation map and generates 6-12 raw ideas from at least 3 of 10 lenses: abstraction ladder, tension hunting, why-now, causal analogy, constraint manipulation, inversion, composition, adjacent possible, stakeholder rotation and simplicity. It sets conservative, upside and elegance quotas and re-widens if the ideas are homogeneous. It then narrows to 5 directions and 2-3 candidates, writes challenge drafts, applies FINER and 0/1/2 gates, and commits a falsifiable selected idea to a git branch.
- **Install, Claude Code:** `npm install -g @researai/deepscientist`, `claude --version`, `ds doctor --runner claude`, `ds --here --runner claude`.
- **Install, Codex:** `npm install -g @researai/deepscientist`, then `codex login`, then `ds --here`.
- **Best for:** Empirical ML research loops where ideas must be validated against a metric.
- **Weaknesses and risks:** **Every runner defaults to no approvals:** Codex runs `danger-full-access`, Claude runs `bypassPermissions`, and Kimi runs in `yolo` mode. The launcher runs the astral.sh uv installer, with `-ExecutionPolicy ByPass` on Windows. The idea skill alone is about 73 KB. Quest repos can exceed 100 GB (#104).
- **Adoption and maintenance:** 3,334 stars and 237 npm downloads a month. The last code fix was 2026-06-15, and **no maintainer has responded to anything since then.**
- **What reviewers found:** The Claude Code runner is experimental and disabled by default. The code has no Bayesian optimization or UCB, despite the README. The 7/10 gate is not enforced in code. Everything happens in one agent and one context, grading its own work. The paper reports about 5,000 ideas and about 1,100 implemented, yielding 21 progress findings, at about $100k and 20,000 GPU hours. Evidence 3, trust 2.

### #25 [Microsoft ResearchStudio-Idea (IdeaSpark, Scoop-Check, Paper-Search)][r25] - A, 63

- **What it is:** Research-ideation skills from Microsoft Research with NTU. MIT.
- **How it brainstorms:** A Python `run.py next` navigator runs each step in an isolated sub-agent. It retrieves papers from arXiv, OpenAlex, OpenReview and Semantic Scholar with full text. It diagnoses the bottleneck, gaps and lineage, or refuses. It picks an anchor gap and 1-4 of 15 corpus-induced patterns, then writes **one** candidate. It executes a dry-run trace against a naive baseline, retrieves prior-art collisions, runs a blind audit and a falsification check, and allows at most 3 revise-or-abandon cycles. Output: bilingual idea cards (Markdown and PDF).
- **Install, Claude Code:** `npx github:microsoft/ResearchStudio` (interactive; non-interactive: `RS_PLUGINS=idea RS_SCOPE=global RS_AGENTS=claude,codex` with `--yes`). Or `git clone https://github.com/microsoft/ResearchStudio.git && cd ResearchStudio && bash install.sh` (`--idea --claude`). Usage: `/idea-spark ...`, `/scoop-check ...`, `/paper-search ...`.
- **Install, Codex:** The same installers with `--codex` or `RS_AGENTS=codex`. The Codex invocation syntax is not documented.
- **Best for:** Turning a vague ML direction into one proposal a reviewer could defend, and checking whether a claim has already been published.
- **Weaknesses and risks:** **`install.sh` silently writes `<repo>/.claude/settings.json` with `Bash(*)`, `defaultMode: dontAsk` and `skipDangerousModePermissionPrompt: true`, and a Codex config with `approval_policy: never` and `danger-full-access`.** It stores the OpenReview password in plaintext in `.env`. It never asks the user anything once running.
- **Adoption and maintenance:** 2,906 stars. skills.sh counts 85/81/68/43. Commit 2026-09-21 (PR #63, which also deleted the idea_spark self-tests).
- **What reviewers found:** In the 100-seed benchmark IdeaSpark scored 3.87 against 2.56 for bare Opus. But the judges ran on the **same model** as the generator, retrieval was not back-dated, and the GPT-5.5 baseline was degenerate (scored 1.00 with std 0). Issue #56: the validators passed while the core claim misdescribed 4 of 5 cited methods. Divergence is 2.

---

## 6. Head-to-head: BMAD vs Superpowers vs the strongest alternatives

Criterion scores are 0-5 from the verified records. "Ideas the AI produces" describes the default path.

| Tool | Score | Divergence | Convergence | Interaction | Handoff | Grounding | Evidence | What it really is | Ideas the AI produces |
|---|---|---|---|---|---|---|---|---|---|
| [ce-ideate + ce-brainstorm][r1] | 82 | 4 | 4 | 4 | 5 | 5 | 1 | Grounded AI divergence, then verification, then requirements | ~36-48 raw, 5-7 ranked survivors |
| [bmad-brainstorming][r2] | 73 | 4 | 3 | 5 | 5 | 2 | 1 | Human-led facilitation with a technique library | 0 in Facilitator mode; 100+ target in Ideate-for-me |
| [office-hours][r4] | 69 | 2 | 4 | 5 | 5 | 4 | 2 | Interrogation of the premise, then a design doc | 2-3 approaches |
| [Superpowers brainstorming][r5] | 67 | 1 | 2 | 4 | 5 | 2 | 2 | Design and approval gate before code | 0-3 (alternatives only on the architectural path) |
| [idea-refine][r7] | 65 | 2 | 3 | 3 | 3 | 2 | 1 | Refining one idea into an MVP one-pager | 5-8 variations |
| [workshop (consult-llm)][r12] | 64 | 3 | 4 | 4 | 4 | 3 | 1 | Cross-model design workshop | 2-3 per model, at most 4 shown |
| [ADHD][r20] | 63 | 4 | 4 | 1 | 2 | 2 | 3 | Isolated parallel frames with a separate critic | 30 raw, top 3 deepened |
| [grill-me][r22] | 63 | 1 | 3 | 4 | 2 | 3 | 2 | Interview that orders decisions by dependency | 0 (questions with a recommended answer each) |

**When to use which:**

- **BMAD vs Superpowers:** they do different jobs. BMAD is a *brainstorming session* in which a human generates ideas (or the AI does, one context at a time) and converges with a named method, producing an intent doc. Superpowers is a *design gate* that stops an agent coding before a design is approved, and it barely diverges. Use BMAD when the goal is many options and your own thinking. Use Superpowers when the goal is an agreed design before implementation.
- **Where ce-ideate beats both:** when you want the AI to generate breadth grounded in your repo, with checkable evidence per idea and a verifier that is not the generator. Neither BMAD nor Superpowers runs parallel isolated generators or refutes ideas against evidence.
- **Where office-hours beats both:** killing a weak startup premise. Its forcing questions and cross-model cold read are the best premise-challenge in the survey. It does not generate many options.
- **Where ADHD beats both:** a single hard technical question where you want 30 genuinely different angles in about a minute, with no interview. Your subagent tool must support parallel isolation.
- **Where idea-refine beats both:** you already have the idea and want a lean one-pager with a "Not Doing" list. Lowest risk of all.

**Combining them (recommended):**

1. [grill-me][r22] to frame, then [ce-ideate][r1] to diverge. Take the top 1-2 survivors into [ce-brainstorm][r1] for requirements. Keep [Superpowers][r5] only as the final architectural gate before code.
2. For a human workshop, use [bmad-brainstorming][r2] in Partner stance for generation, then [bmad-forge-idea][r2] for persona attack/defend. Hand the intent doc to your spec flow.
3. **Collision warnings from the data:**
   - Superpowers auto-triggers on any creative request and its maintainer refuses an off switch. With ce-brainstorm or BMAD also installed, several skills compete for the same prompt, so enable Superpowers per project or invoke skills explicitly.
   - [oma-brainstorm][r57]'s installer detects Superpowers, oh-my-claudecode, oh-my-opencode and oh-my-codex and asks "Remove all?" with **Yes as the default**. Never run it in an environment where you rely on those.
   - gstack ([office-hours][r4]) and Superpowers both register session hooks. Expect extra context in every session.

---

## 7. Recommended stacks

Each stack runs diverge, then converge, then hand off. Commands are from the cards above.

### Stack A: feature ideation inside an existing codebase (the default)

| Stage | Claude Code | Codex |
|---|---|---|
| Frame | [grill-me][r22] `/grill-me` | grill-me via `npx skills@latest add mattpocock/skills` |
| Diverge | [ce-ideate][r1] `/ce-ideate [focus]`. Use "go deep" to get the novelty/feasibility critic. | `$ce-ideate` |
| Converge | ce-ideate's verifier plus its ranked file; for disputed picks, [workshop][r12] critique (`/workshop --gemini --openai`) | ce-ideate; consult-llm via `--platform codex` |
| Hand off | [ce-brainstorm][r1], then the ce plan/work skills or [Superpowers][r5] writing-plans | `$ce-brainstorm` |

### Stack B: greenfield product or startup idea

| Stage | Claude Code | Codex |
|---|---|---|
| Diverge | [bmad-brainstorming][r2] (Partner or Ideate-for-me stance) or [brainstorm-ideas-new][r18] | bmad via `codex plugin marketplace add bmad-code-org/bmad-plugins`; pm-skills skills |
| Pressure-test | [office-hours][r4] (Startup mode) | office-hours runs via `./setup --host codex`, but AskUserQuestion degrades there (#1066). Prefer [Council of HI][r23] `--codex-only`. |
| Converge | [idea-refine][r7] Phase 2-3 (assumption audit, value x feasibility, Not Doing) | `@idea-refine` |
| Hand off | idea-refine one-pager, then [openspec-explore][r21] or Superpowers | the same |

### Stack C: one hard technical decision (architecture, API, migration)

| Stage | Claude Code | Codex |
|---|---|---|
| Diverge | [ADHD][r20] `/adhd "problem"` (30 ideas from 5 isolated frames) | `npx skills add UditAkhourii/adhd -a codex -g`. Check that your build has parallel subagents; if not, use consult-llm instead. |
| Cross-model check | [workshop (consult-llm)][r12] | `consult-llm install-skills --platform codex` |
| Decide | [Council of High Intelligence][r23] `/council --triad ...` (set routing deliberately) | `./install.sh --codex-only` |
| Hand off | workshop's design doc, then /implement or your planner | the same |

### Stack D: ML research ideas

| Stage | Claude Code | Codex |
|---|---|---|
| Diverge + ground | [ARIS][r3] `/aris:idea-discovery "direction"` with `AUTO_PROCEED=false` | `install_aris_codex.sh`. GPT judges its own ideas here; add an outside critic. |
| Prior-art check | ARIS novelty-check, or [ResearchStudio][r25] `/scoop-check` (install only in a disposable environment) | the same |
| Converge as a group | [scientific-brainstorming][r6]: weighted matrix plus sensitivity, human decision log | `gh skill install K-Dense-AI/scientific-agent-skills scientific-brainstorming --agent codex` (or `npx skills add`, which detects installed agents) |
| Hand off | ARIS experiment plan / research contract | the same |

### Stack E: marketing, content and naming

| Stage | Claude Code | Codex |
|---|---|---|
| Diverge | [lateral-thinking][r36] (random stimulus, PO provocation, worst idea) plus [marketing-ideas][r19] for known-good tactics | lateral-thinking via `$skill-installer`; marketing skills via `npx skills` |
| Stress-test | [marketing-council][r19] (mandatory dissenter, disagreement map) | the same |
| Naming | [brand-ideation][r75], then [naming][r186] (registry and domain checks), then [GoDaddy MCP][r266] | brand-ideation has a Codex dist; GoDaddy via any streamable-HTTP MCP client (Codex use not explicitly documented) |
| Visual | [Claude Design][r9] `/design <brief>` | not available |

### Stack F: human team workshop

| Stage | Tool |
|---|---|
| Frame + generate privately | [scientific-brainstorming][r6] (human-first round), or [bmad-brainstorming][r2] in Facilitator stance |
| Put it on a board | [Miro MCP][r139] (Claude Code: `claude plugin install miro@claude-plugins-official`; Codex: the plugin directory or the repo-local Codex plugin): sticky clusters, dot voting and polls, then the agent summarizes |
| Converge | K-Dense weighted matrix with sensitivity; [/explore-options][r15] for UX concepts, with revival conditions for rejected ideas |
| Hand off | bmad intent doc or K-Dense decision log |

---

## 8. Technique canon and what the evidence says

### 8.1 Mechanisms the best tools use

| Mechanism | What it does | Implemented by |
|---|---|---|
| **Isolated parallel generators** | Stops later ideas anchoring on earlier ones | [ce-ideate][r1] (5-6 frame subagents), [ADHD][r20] (5 frames), [ARIS][r3] (one subagent per lens), [DARE][r11] (3-5 campaigns), [creative-writing-skills][r45], [structured-brainstorming][r132], [ideate-fleet][r69] |
| **Cross-model divergence** | Different model families fail differently | [workshop][r12], [ARIS][r3] (two GPT models), [Council of HI][r23], [MassGen][r55], [jam][r50], [brainstorm-mcp][r239], [Mysti][r339], [EvoMap][r60] (3 or more models) |
| **Frame / lens rotation** | Forces coverage of distinct angles | ce-ideate (6 frames), ADHD (15), idea-refine (7), [Orchestra][r34] (10), [DeepScientist][r24] (10), [ia-ideate][r14] (7) |
| **Axis decomposition** | Splits the topic into orthogonal dimensions first | ce-ideate (3-5 axes), [nw-diverge][r10] (mechanism/assumption/cost), [/explore-options][r15] (5 behavioural axes), [brainstorm 1C][r95] (Zwicky) |
| **Technique libraries** | Named methods such as SCAMPER, TRIZ, PO and synectics | [BMAD][r2] (108), [DARE][r11] (10 campaigns), [lateral-thinking][r36] (8), [gds-brainstorm-game][r26] (~25), [cc-thinking-skills][r127] (28) |
| **Quantity targets + banning the obvious** | Pushes past the first plausible answers | ce-ideate (warm-up ideas dropped), ADHD (skip the first three), BMAD (100+), [specs.md][r42] (50), [Idea Wizard][r317] (30) |
| **Domain pivots / real random stimuli** | Breaks clustering | BMAD (pivot every 5-10 turns; `brain.py random` is real randomness), specs.md (12-domain wheel), lateral-thinking (categorized pools). Caveat: DARE's "random" words are chosen by the LLM. |
| **Verbalized / tail sampling** | Asks for low-probability responses to escape the typical answer | [Verbalized Sampling][r261], [verbalized-sampling (AIWG)][r147], [verbalized-sampling (gnurio)][r243], [divergent-agents][r106] (plus a `novelty.py` diversity gate), [NeoLab ToT][r162], [BeCreative][r268] |
| **Deferred judgment** | Generate before critique | Most tools claim it. It is only partly true for ce-ideate (agents cut their own lists) and false for [idea-refine][r7] (judges within Phase 1). |
| **Basis / evidence tagging** | Each idea must cite a checkable basis | ce-ideate (direct/external/reasoned plus file:line), [ResearchStudio][r25] (collision retrieval), [DeepScientist][r24] |
| **Fresh-context verifier / red team** | The critic is not the generator | ce-ideate verifier, [office-hours][r4] cold read, [Council of HI][r23] anonymized cross-exam, [the-fool][r74], [reversa][r58] Challenger |
| **Pairwise tournament** | Ranks by head-to-head comparison | [Co-Scientist][r8] (Elo), [research-ideation (EvoSkills)][r63] (Elo), [Co-Scientist (Kaimen)][r230], [Robin][r177]; DARE does it in prose only |
| **Weighted matrix with sensitivity** | Transparent, stress-tested ranking | [scientific-brainstorming][r6] (`evaluate_matrix.py`), [nw-diverge][r10] (locked weights), ADHD (0.35/0.40/0.25), [idea-validation-agents][r29] (multiplicative floor) |
| **Pre-mortem / kill criteria** | Names how the idea fails | idea-refine, reversa, office-hours, Council of HI, DeepScientist, [sparring-partner][r13] |
| **Human-first ideation** | The human writes ideas before any AI output, to avoid homogenization | [scientific-brainstorming][r6], [brainstorm-assistant (UDS)][r47] (3 ideas plus anti-goals before the AI speaks), [brainstorm-coach][r43] |
| **Rejected-idea log with revival conditions** | Keeps the reasoning for later | [/explore-options][r15], [unikit-gd-brainstorm][r30], [Junshi][r54], [reversa][r58] |
| **Real search algorithms** | Structured exploration of the space | [AutoDiscovery][r17] (MCTS + Bayesian surprise), [AI Scientist][r168] (idea archive), [mad][r173] (MAP-Elites) |

### 8.2 What the evidence in the data actually says

- **No brainstorming skill or plugin has a controlled comparison against vanilla prompting that measures idea quality.** Its evals test triggering, routing, tone or process compliance: office-hours, Superpowers, idea-refine, ce-ideate. Where A/B numbers exist they are self-reported and cannot be verified: [brainstorm-coach][r43] reports 95.8% vs 36.5% *process compliance*, and [CCFA][r32] reports gains of +0.01 to +0.06 at 2.4-21x the tokens.
- **Superpowers removed its subagent spec review** after measuring "no measurable quality gain" at about 25 extra minutes per run. That is the one negative result in the data.
- **[Google Co-Scientist][r8]** has the strongest evidence: a Nature paper, AML drug-repurposing in vitro, and liver-fibrosis targets in organoids. But its Elo is self-rated, the expert study covered 11 goals, no wet-lab result is compared against a baseline LLM, and the cf-PICI result was a rediscovery.
- **[AutoDiscovery][r17]** has a NeurIPS 2025 paper with a baseline and expert evaluation. This is the best peer-reviewed evidence among tools that are actually open.
- **[ResearchStudio][r25]** ran a 100-seed benchmark (3.87 vs 2.56), but the judge is the same model as the generator and there is no human study.
- **[DeepScientist][r24]**'s paper reports about 5,000 ideas, about 1,100 implemented and 21 progress findings, a 1-3% hit rate at about $100k.
- **[ARIS][r3]**'s own tech report and **[K-Dense][r6]**'s paper both state there is no task-level or controlled evaluation.
- **[ADHD][r20]** has a reproducible 6-problem bench and one independent blind 2-problem test. Experts call these small and prone to same-stack bias.
- **Research the tools cite:** [Verbalized Sampling][r261] reports 2-3x more diversity on creative tasks. [brainstorm-assistant][r47] cites Meincke, Mollick and Terwiesch (arXiv 2402.01727) for "CoT + persona" diversity, but the abstract credits chain-of-thought alone. The idea-refine critique cites Si et al. 2024 on a single model collapsing toward similar ideas; the [Stanford Research Ideation Agent][r200] is that group's pipeline. [scientific-brainstorming][r6] cites the human-group literature (Diehl & Stroebe on production blocking, and others). That supports its *process* design, not its agent behaviour.
- **Practical reading:** isolated parallel generation, cross-model generation, forced frames or axes, and a critic separate from the generator are the mechanisms with the strongest theoretical support (anti-anchoring, anti-mode-collapse). None has been shown to beat a strong prompt on idea quality for coding agents. Treat every tool here as a well-structured prompt with plumbing.

---

## 9. Portability: running Claude-style skills in Codex and vice versa

These claims are supported by the verified records. Where a record states something only for one tool, it is cited to that tool.

1. **SKILL.md is the common format.** Most tools here are plain `SKILL.md` folders (Agent Skills standard). The `npx skills add <owner>/<repo>` CLI (vercel-labs/skills, listed on skills.sh) installs them into many agents at once. ADHD claims "~50 agents", and the flags `-a claude-code` / `-a codex` / `-g` pick targets ([ADHD][r20], [DARE][r11], [K-Dense][r6], [bmad][r2]). The [marketing skills][r19] README warns that running the CLI from *inside* an agent may install only to `.agents/skills/`, "which Claude Code does not read". Pass `-a claude-code`.
2. **Codex has its own plugin marketplaces.** `codex plugin marketplace add <owner>/<repo>` then `codex plugin add <plugin>@<marketplace>` is documented for [ce][r1], [BMAD][r2], [idea-refine][r7], [pm-skills][r18] and [unstuck (Ouroboros)][r124]. [Superpowers][r5] is in the official OpenAI Codex marketplace (openai/plugins), which also holds the first-party [ideate (product-design)][r165] and [creative-production][r245].
3. **Where Codex skills live:** `~/.codex/skills` (consult-llm, ADHD manual install), `.agents/skills` ([OpenSpec][r21], [Trellis][r37], [Reversa][r58]), `${CODEX_HOME:-~/.codex}/skills/gstack-*/` (gstack). Invocation differs: `$ce-ideate`, `$openspec-explore`, `@idea-refine`. *Editor's note (verified 2026-09-23):* Codex's documented locations are `.agents/skills` from the working directory up to the repo root, `~/.agents/skills` for the user, `/etc/codex/skills` for admins, and bundled system skills ([Codex skills docs](https://learn.chatgpt.com/docs/build-skills)). `$CODEX_HOME/skills` (default `~/.codex/skills`) is a deprecated user location that is still loaded for backward compatibility (`codex-rs/ext/skills/src/host_roots.rs` in openai/codex). Tools that install there work today, but prefer `~/.agents/skills` for new installs. `npx skills add ... -a codex -g` writes to `~/.codex/skills` (vercel-labs/skills `src/agents.ts`).
4. **What breaks when moving Claude to Codex:**
   - **AskUserQuestion.** On Codex, office-hours "silently degrades" and the model makes up answers (#1066). Codex Desktop blocks when the tool is missing (#2274). idea-refine falls back to plain questions.
   - **Parallel subagents.** ADHD says isolation fails in agents without a parallel Task tool, "which defeats the method". DARE's subagent protocol is written for Claude's Agent tool. ce has open Pi and Devin subagent issues.
   - **Slash commands and hooks.** pm-skills commands do not run on Codex. Whetstone's commands are Claude-only. nWave documents only its hooks for Codex. design-shotgun fails on a fresh Codex install (#1159).
   - **Judge independence.** ARIS's Codex mirror lets GPT both generate and judge.
5. **What breaks when moving Codex to Claude:** [creative-problem-solver][r98] is Codex-first (`$creative-problem-solver`), but its plain SKILL.md is described as "trivially portable". [llm-council (am-will)][r203] is Codex-first with a documented skills.sh pattern. Codex Plan Mode is native only ([Codex Plan Mode][r78]).
6. **Using Codex as a second brain from Claude Code** is the most robust cross-agent pattern in the data. [workshop][r12] uses a `codex-cli` backend. [office-hours][r4] does a Codex cold read. [ARIS][r3] bridges to Codex over MCP (`claude mcp add codex ...`). [Council of HI][r23], [claude-council][r86], [claude-co-commands][r376] and [Mysti][r339] route to Codex CLI. The rejected openai/codex-plugin-cc does review and delegation, not ideation.
7. **MCP servers that work in any MCP client:**
   - Council and debate: [brainstorm-mcp][r239] (`claude mcp add brainstorm -- npx -y brainstorm-mcp`), [mcp-rubber-duck][r224], [deliberation][r262] (Claude plugin plus Codex marketplace), [owlex][r352], [gemini-mcp-tool][r308] (a non-commercial license despite "MIT" in the README), [PAL][r323] (stale).
   - Boards and references: [Miro MCP][r139] (listed for Codex and Claude), [Mobbin MCP][r179] (`codex mcp add mobbin ...` documented).
   - Grounding and reality checks: [InfraNodus][r217], [idea-reality-mcp][r340] (maintenance mode), [GoDaddy MCP][r266], [PatSnap][r263].
   - Stimulus and technique engines: [Creative Thinking MCP][r301], [TRIZ Skills MCP][r213] (a shared bearer token is published in its README), [Sideways][r338], [Haft][r201].

   **MCP adds capabilities, not facilitation.** None of these servers asks you good questions or keeps a session state machine except Creative Thinking MCP and out-the-box-thinking. Pair them with a skill.

---

## 10. Watchlist: new or promising, low adoption

| Tool | Why watch it | Adoption signal |
|---|---|---|
| [workshop (consult-llm)][r12] | The cleanest cross-model divergence plus critique design in the survey | 138 stars |
| [sparring-partner][r13] | A complete diverge/converge/pre-mortem session with anti-sycophancy rules | 156 stars, no standalone install |
| [ia-ideate (Whetstone)][r14] | Repo-grounded idea killing and ranking, a lightweight ce-ideate | 34 stars |
| [nw-diverge][r10] | SCAMPER-per-letter plus a structural diversity test | 617 stars, 7 installs |
| [unikit-gd-brainstorm][r30] | Five generators plus two-pass Pugh plus revival conditions | 17 stars |
| [divergent-agents][r106] | Verbalized sampling plus a `novelty.py` diversity gate that rejects low-diversity sets | 4 stars |
| [MultiAgent Decanting (mad)][r173] | MAP-Elites grid plus persona distinctness by embedding distance | 1 star |
| [structured-brainstorming][r132] | 4 parallel explorers, each with 2 of 8 methods, with codebase and web access | 30 stars |
| [ideate-fleet][r69] | Worktree subagents per strategy track with a human pick gate | 21 stars |
| [Haft][r201] | Variants that differ in kind, compared without a single score, with evidence tracking | 1,393 stars, maintainer quiet |
| [specs.md Ideation][r42] | An enforced domain wheel and a 50-idea target | 215 stars |
| [brainstorm-panel][r49] | An editable persona panel with repo exploration for each persona | 35 stars |
| [novel-idea-hunter][r156] | Ideas banned until isolated research lenses gather cited evidence | 6 stars |
| [Open Collider][r157] | 5-7 structurally distant domains with 15-20 ideas each | 0 stars |

---

## 11. Adjacent tools, directories, copies and rejected tools

### 11.1 Directories worth watching (sources, not ranked)

| Directory | Note |
|---|---|
| [VoltAgent/awesome-agent-skills](https://github.com/VoltAgent/awesome-agent-skills) | A README-only list of agent skills |
| [travisvn/awesome-claude-skills](https://github.com/travisvn/awesome-claude-skills) | Official Anthropic skills plus a small curated community set |
| [Build with Claude (davepoon/buildwithclaude)](https://github.com/davepoon/buildwithclaude) | 144 plugin folders plus the buildwithclaude.com index |
| [dsh-market](https://github.com/dsh-market/dsh-market) | A GUI installer for DeepSeek Harness plugins |

The lanes also crawled skills.sh, claudemarketplaces.com, the official Anthropic marketplaces (claude-plugins-official, 310 entries; claude-plugins-community, 2,282 plugins), openai/plugins, the MCP registry (112,980 server-version entries) and ClawHub. **Install counts on skills.sh are often bulk-collection artifacts.** BMAD, K-Dense, idea-refine, marketingskills, CCFA and gstack all show near-identical per-skill counts across their whole pack. Do not read them as demand for a specific skill.

### 11.2 Aggregator copies: install the original instead

40 copies were excluded. The most common pattern is a re-hosted [Superpowers brainstorming][r5]: davila7/claude-code-templates, sickn33/agentic-awesome-skills, superpowers-zh, MiMo Code compose:brainstorm, NeoLab SDD brainstorm, rsmdt/the-startup, umputun/cc-thingz, feiskyer codex-settings, ninehills brainstorming-cn, Expert-Coding-Harness, Claude-Cortex, ctf-super-hub, sprut-agent-kit, seedex spark, research-writing-skill, SuperAntigravity, antigravity-superpowers and orchestrator-supaconductor. Other copied originals are grill-me (alirezarezvani, RobMitt, ab-method), K-Dense scientific-brainstorming (OpenScience, SciAgent-Skills, jimmc414/Kosmos, ScienceClaw), ce-ideate (spec-first spec-ideate), ADHD (repowire, szarkans/multi), creative-director-skill (nexu-io/open-design), jamubc gemini-mcp-tool (cexll codex-mcp-server), DAIR llm-council (pro-workflow), Hermes creative-ideation (Algoticlab), aj-geddes BMAD skills (Dr. Claw, xmm codex-bmad-skills), Ole Lehmann's LLM Council (aiwithremy, tenfoldmarc), happy-skills (claude-code-templates feature-design-assistant) and obra/superpowers-skills problem-solving (claudekit-skills). **Copies drift:** Smithery and aitmpl still serve K-Dense v1.0 under the same name.

### 11.3 Rejected after verification (not really brainstorming): 46 tools

In compact form, with reasons:

- **Requirements / spec tools:** deep-interview + ralplan (oh-my-claudecode, oh-my-codex), GitHub Spec Kit, Agent OS, Conductor, kiro-discovery (cc-sdd), GAAI Discovery, Superspec, adversarial-spec, Taskmaster AI, Archon, Claude Code Plan Mode (implementation planning).
- **Critique or decision only:** Critical thinking mode agent, council (warpdotdev), premortem (Continuous-Claude-v3), boardroom, challenge-plan (GitLens), DSH Council, Plannotator, Codex plugin for Claude Code (openai/codex-plugin-cc: review and delegation).
- **Research or knowledge tools:** STORM/Co-STORM, last30days-skill, ai-co-scientist (sundial), startup-business-analyst, OpenEvolve.
- **Surfaces or hosts:** tldraw MCP App, Playground plugin, Claudian, CCB, krew-cli.
- **Misnamed:** BrainStorming workspace rules (Cline), Brainstormer (Excalidraw copilot), cs-brainstorm (deleted in v2), customer-ideation (AWS service selection), idea-generation for public equities, Sequential Thinking MCP, prompts.chat, agency-agents, nuwa-skill, design-sprint-plan, problem-framing-canvas, concept_planning, renaissance-architecture, awesome-pm-skills, project discovery commands.
- **Gone:** Creativity Engine MCP (its GitHub repo returns 404).

---

## 12. Gaps and a blueprint for an "ultimate brainstorming skill"

### 12.1 What no tool does well yet

1. **Evaluation.** No tool A/B tests its ideas against a strong vanilla prompt with blind judges from a *different* model family plus human raters. Judges are usually the generating model ([ResearchStudio][r25], [ARIS][r3], [DARE][r11]).
2. **Real diversity control.** No tool measures diversity across its own output with embeddings and then re-widens, apart from [DeepScientist][r24] (the LLM decides for itself whether ideas are "homogeneous"), [AutoDiscovery][r17] (Ward HAC dedup) and tiny projects ([divergent-agents][r106], [mad][r173]).
3. **Independent judging.** Cross-model "juries" often reuse the generating thread (ARIS), or fall back to the same model family when the other CLI is missing (office-hours, gstack).
4. **Breadth plus facilitation in one tool.** Tools are either good facilitators with little divergence (Superpowers, office-hours, grill-me, openspec-explore) or strong autonomous generators that ask nothing (ADHD, DARE, ResearchStudio, DeepScientist). Only [ce-ideate][r1] and [bmad-brainstorming][r2] partly bridge the two.
5. **Real randomness.** Most "random stimulus" steps let the LLM choose the random word. Among the well-adopted tools only BMAD's `brain.py random` draws from a real RNG. A few small tools also use a script: [jwynia brainstorming][r170] (random constraints from a Deno script), [force-associations][r327] (random dictionary words from a Python script), [oblique-skill][r392] (awk `rand` shuffle) and [Sideways][r338] (a random hand of cards from its MCP server).
6. **A durable idea backlog.** Few tools keep rejected ideas with revival conditions across sessions ([/explore-options][r15], [Junshi][r54], [unikit][r30]).
7. **Cost transparency.** Among the leading tools only ce-ideate prints a cost line before dispatch; the tiny [Open Collider][r157] also opens with a cost gate. Several tools silently burn tens of millions of tokens (ARIS #147) or GPU hours.

### 12.2 Blueprint: combining the best mechanisms found

| Phase | Design | Borrowed from |
|---|---|---|
| 0. Intake | Ask one question at a time, each with a recommended answer. Settle the dependency frontier first. Let the user choose a stance (you / together / AI). Print a cost estimate before any fan-out. | [grill-me][r22], [Superpowers][r5], [BMAD][r2], [ce-ideate][r1] |
| 1. Human seed | Collect 3 of the user's own ideas plus anti-goals before any AI output, and freeze them. | [brainstorm-assistant (UDS)][r47], [scientific-brainstorming][r6] |
| 2. Grounding | Repo scouts with file:line evidence; learnings and issue themes; a web and prior-art scan; a literature scan for research topics. Treat fetched content as untrusted (W011). | [ce-ideate][r1], [office-hours][r4], [ARIS research-lit][r3], [idea-reality-mcp][r340] |
| 3. Decompose | Split into 3-5 orthogonal axes and choose the behavioural or mechanism axis variants must differ on. | [ce-ideate][r1], [/explore-options][r15], [nw-diverge][r10] |
| 4. Diverge | Isolated parallel subagents, one per frame. At least two model families as generators, each on a fresh thread. Random stimuli drawn by a script. Verbalized tail sampling (p < 0.1). Drop the first 3 obvious ideas. 6-8 ideas per frame. PO provocations and worst-idea inversion as wildcard frames. | [ADHD][r20], [ce-ideate][r1], [workshop][r12], [BMAD brain.py][r2], [Verbalized Sampling][r261], [lateral-thinking][r36] |
| 5. Diversity gate | Cluster embeddings, then merge duplicates. If diversity is below a threshold, re-widen with unused frames. Recovery agents fill empty axes. | [AutoDiscovery][r17], [divergent-agents][r106], [DeepScientist][r24], [ce-ideate][r1] |
| 6. Critique | A fresh-context verifier refutes each idea's basis. A **different-family** judge works on a **fresh thread** with file paths only. Novelty/prior-art collision search. Pre-mortem: killer assumption, cheap test, point of no return. | [ce-ideate][r1], ARIS's own rule in fan-out-pattern.md (which ARIS itself violates), [ResearchStudio scoop-check][r25], [reversa][r58] |
| 7. Rank | Pairwise Elo tournament over the survivors, plus an anchored weighted matrix with one-at-a-time weight sensitivity. Non-compensatory gates for ethics and feasibility. The human makes the final call, and dissent is logged. | [Co-Scientist][r8], [EvoSkills research-ideation][r63], [scientific-brainstorming][r6], [Council of HI][r23] |
| 8. Hand off | A ranked HTML/MD artifact; a rejected-idea log with revival conditions; a resumable append-only memlog; a seeded handoff to requirements or spec. | [ce-ideate/ce-brainstorm][r1], [/explore-options][r15], [BMAD][r2], [openspec-explore][r21] |
| 9. Eval harness (new) | For every release: same prompts through the skill and through a strong vanilla prompt; blind judges from another model family plus human raters; diversity metrics; token cost. | Missing everywhere. ce's `tests/skill-eval-cell` harness is the closest base to extend. |

---

## 13. Master table: all 393 ranked tools

**Category:** SP = skills and plugins; Meth = methodologies/frameworks; Res = research-ideation; MCP = MCP servers; Council = multi-agent councils; App = apps with integration; Tech = technique and prompt libraries. **Platforms:** CC = Claude Code; CX = OpenAI Codex; CAI = Claude.ai / Claude Desktop; CUR = Cursor; GEM = Gemini CLI; COP = GitHub Copilot; OC = OpenCode; AG = Antigravity; WS = Windsurf; "+N" = more hosts. Stars are for the containing repo; "n/a" = not on GitHub. Last activity is the most relevant date in the record (repo push, release or skill change).

| Rank | Tool | Cat | Platforms | Stars | Last activity | Score | Tier | Checked |
|---|---|---|---|---|---|---|---|---|
| 1 | [ce-ideate + ce-brainstorm (Compound Engineering)][r1] | SP | CC, CX, CUR, COP, OC, Pi +8 | 25,216 | 2026-09-23 | 82 | S | full |
| 2 | [bmad-brainstorming (BMAD-METHOD)][r2] | SP | CC, CX, npx skills, Gemini Gems, ChatGPT GPTs | 53,360 | 2026-09-22 | 73 | S | full |
| 3 | [idea-discovery / idea-creator (ARIS)][r3] | Res | CC, CX, Copilot CLI, OpenClaw, CUR | 16,524 | 2026-09-18 | 72 | S | full |
| 4 | [office-hours (gstack)][r4] | SP | CC, CX, OC, CUR, Factory, Kiro +2 | 133,943 | 2026-09-23 | 69 | S | full |
| 5 | [brainstorming (obra/superpowers)][r5] | SP | CC, CX, CUR, GEM, COP, OC +10 | 290,246 | 2026-09-22 | 67 | S | full |
| 6 | [scientific-brainstorming (K-Dense)][r6] | SP | CC, Cowork, CX, CUR, GEM, AG | 46,157 | 2026-09-21 | 66 | S | full |
| 7 | [idea-refine (addyosmani/agent-skills)][r7] | SP | CC, CX, GEM, CUR, COP, OC +4 | 98,483 | 2026-09-20 | 65 | S | full |
| 8 | [Google Co-Scientist][r8] | Res | Gemini Enterprise, Google Labs | n/a | 2026-07-14 | 65 | S | critic |
| 9 | [Claude Design (Anthropic Labs)][r9] | App | CAI, CC, mobile | n/a | 2026-09-08 | 65 | A | critic |
| 10 | [nw-brainstorming / nw-diverge (nWave)][r10] | Meth | CC, OC (partial), CX (hooks only) | 617 | 2026-09-16 | 64 | A | full |
| 11 | [DARE (de-anthropocentric-research-engine)][r11] | Res | CC, CX, CUR, OC, Cline, Pi +3 | 498 | 2026-09-16 | 64 | A | full |
| 12 | [workshop (consult-llm)][r12] | SP | CC, CX, OC, Pi | 138 | 2026-09-22 | 64 | A | full |
| 13 | [sparring-partner + ideation (data2story)][r13] | SP | CC, CX, CUR, GEM, CAI | 156 | 2026-07-05 | 64 | A | light |
| 14 | [ia-ideate / ia-brainstorming (Whetstone)][r14] | SP | CC, CX (skills), OC, CUR/GEM | 34 | 2026-09-20 | 64 | A | light |
| 15 | [/explore-options + parallel-concepts + concept-selection][r15] | SP | CC, GEM, other SKILL.md hosts | 2,724 | 2026-09-05 | 64 | A | critic |
| 16 | [design-shotgun + plan-ceo-review (gstack)][r16] | SP | CC, CX, OC, CUR, Factory, Kiro +3 | 133,953 | 2026-09-22 | 64 | A | critic |
| 17 | [Ai2 AutoDiscovery / asta-autodiscovery][r17] | Res | Hosted web, Python CLI | 12 | 2026-09-22 | 64 | A | critic |
| 18 | [brainstorm-ideas-new / -existing (pm-skills)][r18] | SP | CC, Cowork, CX, GEM, OC, CUR, Kiro | 26,540 | 2026-09-14 | 63 | A | full |
| 19 | [marketing-ideas + marketing-council][r19] | SP | CC, CX, CUR, WS | 51,243 | 2026-09-05 | 63 | A | full |
| 20 | [ADHD (Parallel Divergent Ideation)][r20] | SP | CC, CAI, CX, CUR, GEM, CLI | 4,265 | 2026-09-17 | 63 | A | full |
| 21 | [openspec-explore (OpenSpec)][r21] | Meth | CC, CX, CUR, GEM, COP, WS +6 | 69,885 | 2026-09-22 | 63 | A | full |
| 22 | [grill-me (mattpocock/skills)][r22] | SP | CC, CX, skills.sh agents | 267,909 | 2026-09-18 | 63 | A | full |
| 23 | [Council of High Intelligence][r23] | SP | CC, CX, GEM, OC | 4,469 | 2026-09-22 | 63 | A | full |
| 24 | [DeepScientist][r24] | Res | CX, CC, Kimi, OC (runners) | 3,334 | 2026-06-28 | 63 | A | full |
| 25 | [Microsoft ResearchStudio-Idea][r25] | SP | CC, CX | 2,906 | 2026-09-21 | 63 | A | full |
| 26 | [gds-brainstorm-game (BMad Game Dev Studio)][r26] | SP | CC, CX, CUR | 240 | 2026-08-31 | 63 | B | light |
| 27 | [vibe-check][r27] | SP | CC, CX, AG, npx skills | 605 | 2026-07-17 | 63 | B | light |
| 28 | [Feature Dev plugin (/feature-dev)][r28] | SP | CC | 36,637 | 2026-09-22 | 63 | B | light |
| 29 | [idea-validation-agents][r29] | Meth | CC, CX, CUR | 467 | 2026-06-16 | 63 | B | light |
| 30 | [unikit-gd-brainstorm][r30] | SP | CC, CX, CUR, OC, AG | 17 | 2026-09-13 | 63 | B | light |
| 31 | [parallel-concepts + concept-selection + /explore-options (dup of #15)][r31] | SP | CC, GEM, Copilot CLI | 2,724 | 2026-09-05 | 63 | B | critic |
| 32 | [CCFA-Skills idea optimizer + reviewer][r32] | SP | CC, CX, CUR, GEM +5 | 2,781 | 2026-09-16 | 63 | B | critic |
| 33 | [product-brainstorming + /brainstorm (Anthropic)][r33] | SP | Cowork, CC | 25,441 | 2026-09-22 | 62 | B | full |
| 34 | [brainstorming-research-ideas (Orchestra)][r34] | SP | CC, CX, CUR, GEM, OC +4 | 12,954 | 2026-06-16 | 62 | B | full |
| 35 | [scientific-problem-selection (Anthropic)][r35] | SP | CC, CAI, Cowork | 25,442 | 2026-09-22 | 62 | B | full |
| 36 | [lateral-thinking (danium)][r36] | SP | CC, CX, SKILL.md hosts | 314 | 2026-09-13 | 62 | B | full |
| 37 | [trellis-brainstorm (Trellis)][r37] | SP | CC, CX, CUR, OC, GEM +10 | 14,776 | 2026-09-11 | 62 | B | full |
| 38 | [academic-research-skills (deep-research Socratic)][r38] | SP | CC, CAI, CX (sibling), Pi | 49,177 | 2026-09-21 | 62 | B | full |
| 39 | [design-sprint (wondelai/skills)][r39] | SP | CC, CAI, CX, CUR, WS | 2,243 | 2026-09-10 | 62 | B | full |
| 40 | [AI-DLC Ideation stage (AWS)][r40] | Meth | CC, CX, Kiro, CUR, OC, COP | 4,766 | 2026-09-23 | 62 | B | full |
| 41 | [/gsd:explore (GSD / GSD Core)][r41] | Meth | CC, CX, OC, Kilo, Kimi, COP +7 | 64,477 | 2026-09-23 | 62 | B | full |
| 42 | [specs.md Ideation flow][r42] | Meth | CC, CX, CUR, COP, AG, WS +6 | 215 | 2026-09-09 | 62 | B | light |
| 43 | [brainstorm-coach (tronghieu)][r43] | SP | CC, CX, CUR, ChatGPT | 73 | 2026-09-22 | 62 | B | light |
| 44 | [Research Companion][r44] | SP | CC, CX, GEM | 717 | 2026-04-13 | 62 | B | light |
| 45 | [creative-writing-skills (haowjy)][r45] | SP | CC, Cowork, CAI, CX | 479 | 2026-09-17 | 62 | B | light |
| 46 | [show-me-the-money][r46] | SP | CC (+CX/GEM/CUR claimed) | 874 | 2026-09-01 | 62 | B | light |
| 47 | [brainstorm-assistant (universal-dev-standards)][r47] | SP | CC, CX (partial), CUR | 75 | 2026-09-18 | 62 | B | light |
| 48 | [HarnessFlow (Diversifier + Devil's Advocate)][r48] | Meth | CC, CX, COP, Aider | 457 | 2026-09-12 | 62 | B | light |
| 49 | [brainstorm-panel (Constructor Studio)][r49] | SP | CC, CX, CUR, COP, WS | 35 | 2026-09-22 | 62 | B | light |
| 50 | [jam (wicked-garden)][r50] | SP | CC, CX, OC, Pi, AG | 9 | 2026-09-22 | 62 | B | light |
| 51 | [Oh My Paper (/omp:ideate)][r51] | SP | CC, CX | 736 | 2026-04-15 | 62 | B | light |
| 52 | [oh-story-claudecode][r52] | SP | CC, CX, AG, OC, ZCode, OpenClaw +1 | 7,059 | 2026-09-22 | 62 | B | light |
| 53 | [hypothesis-gen / tournament-autoresearch][r53] | SP | CC, CX, CUR | 172 | 2026-06-30 | 62 | B | light |
| 54 | [Junshi (research-junshi)][r54] | SP | CC, CX | 122 | 2026-09-16 | 62 | B | light |
| 55 | [MassGen][r55] | Council | CC, CX, CUR, COP, GEM, WS, CLI | 1,132 | 2026-06-12 | 62 | B | critic |
| 56 | [brainstorm (Claude Code Game Studios)][r56] | SP | CC | 25,365 | 2026-05-21 | 61 | B | full |
| 57 | [oma-brainstorm (oh-my-agent)][r57] | SP | CC, CX, CUR, AG, OC, Kiro +2 | 1,322 | 2026-09-22 | 61 | B | full |
| 58 | [reversa-brainstorm][r58] | Meth | CC, CX, CUR, GEM, WS +9 | 1,623 | 2026-09-08 | 61 | B | full |
| 59 | [/think (Waza)][r59] | SP | CC, CX, CUR, CAI, GEM +5 | 7,078 | 2026-09-22 | 61 | B | full |
| 60 | [EvoMap AutoResearch (Idea Forge)][r60] | Res | Linux CLI, LLM APIs, CC runtime | 3,201 | 2026-09-16 | 61 | B | full |
| 61 | [osborn + taixu-debate (Liam-Skills)][r61] | SP | CC, Qoder, Aone Copilot | 110 | 2026-08-12 | 61 | C | full |
| 62 | [think-tank (claude-code-templates)][r62] | SP | CC, skills.sh agents | 31,182 | 2026-09-23 | 61 | C | light |
| 63 | [research-ideation (EvoSkills)][r63] | SP | EvoScientist, CC, CX, OC, CUR, GEM | 437 | 2026-09-01 | 61 | C | light |
| 64 | [Arbor IDEATE gate][r64] | SP | CC, CX, Arbor CLI | 1,081 | 2026-09-08 | 61 | C | light |
| 65 | [K-Dense science-superpowers][r65] | SP | CC, CX, CUR, GEM, OC, Pi, AG | 338 | 2026-09-13 | 61 | C | light |
| 66 | [Kiln (brainstorm / sketchbook)][r66] | SP | CC | 223 | 2026-07-31 | 61 | C | light |
| 67 | [idea-thinking-skills][r67] | SP | CC, CX | 17 | 2026-08-26 | 61 | C | light |
| 68 | [viral-short-form-ideas][r68] | SP | CC, CAI, CUR | 118 | 2026-06-22 | 61 | C | light |
| 69 | [ideate-fleet (Harness Engineering)][r69] | SP | CC, CUR, GEM, CX, AG | 21 | 2026-09-22 | 61 | C | light |
| 70 | [ideation (nicknisi)][r70] | SP | CC, pi | 14 | 2026-09-02 | 61 | C | light |
| 71 | [Google Co-Scientist / Hypothesis Generation (dup of #8)][r71] | Res | Gemini for Science, Gemini Enterprise | n/a | 2026-09-22 | 61 | C | critic |
| 72 | [creative-director-skill (smixs)][r72] | SP | CC, CAI, CX, CUR, GEM, WS | 219 | 2026-08-08 | 60 | C | full |
| 73 | [bmad-party-mode][r73] | SP | CC, CX, npx skills | 53,360 | 2026-09-21 | 60 | C | full |
| 74 | [the-fool (Jeffallan)][r74] | SP | CC, CX, CUR, COP, GEM, OC +3 | 11,579 | 2026-08-07 | 60 | C | full |
| 75 | [brand-ideation (rampstackco)][r75] | SP | CC, CAI, API, CX, pi | 897 | 2026-09-15 | 60 | C | full |
| 76 | [sci-brain][r76] | SP | CC, CX, OC, pi | 97 | 2026-09-21 | 60 | C | full |
| 77 | [pm-skills (product-on-purpose)][r77] | SP | CC, CX, CUR, COP, WS, OC +4 | 692 | 2026-09-18 | 60 | C | full |
| 78 | [Codex Plan Mode][r78] | SP | Codex CLI / IDE / app | 126,006 | 2026-09-23 | 60 | C | full |
| 79 | [brainstorm (OrchestKit)][r79] | SP | CC, CUR, CX, pi, AG | 283 | 2026-09-22 | 60 | C | full |
| 80 | [short-drama-develop][r80] | SP | CC, CX | 2,194 | 2026-09-18 | 60 | C | light |
| 81 | [Finding-Unknowns skills][r81] | SP | CC, CX, CUR, Hermes, Kimi | 338 | 2026-09-16 | 60 | C | light |
| 82 | [shortform-ideation (rsc-harness)][r82] | SP | CC, CX, GEM, OC, CUR | 96 | 2026-09-22 | 60 | C | light |
| 83 | [Flux (simota/agent-skills)][r83] | SP | CC, CX, AG | 80 | 2026-09-18 | 60 | C | light |
| 84 | [brainstorming-ideas (cc-thingz)][r84] | SP | CC, CX, COP, CUR, Grok, Pi | 35 | 2026-09-15 | 60 | C | light |
| 85 | [InternAgent][r85] | Res | Python; CC/iFlow backends | 1,443 | 2026-07-29 | 60 | C | light |
| 86 | [claude-council (hex)][r86] | SP | CC (+ provider CLIs) | 784 | 2026-09-22 | 60 | C | light |
| 87 | [BuilderOS idea-generator + idea-validator][r87] | SP | CC, CX, CUR, COP, WS, GEM, Cline | 221 | 2026-07-07 | 60 | C | critic |
| 88 | [ideate (nelsonwerd idea-to-ship)][r88] | SP | CC, CX, CAI | 83 | 2026-08-04 | 59 | C | full |
| 89 | [octocode-brainstorming][r89] | SP | CC, CAI, CX, CUR, GEM, COP +2 | 943 | 2026-09-18 | 59 | C | full |
| 90 | [idea-evaluator (Supervisor-Skills)][r90] | SP | CC, CX, CUR, Doubao | 7,435 | 2026-09-05 | 59 | C | full |
| 91 | [/autoresearch:reason][r91] | SP | CC, CX, OC | 6,358 | 2026-08-12 | 59 | C | full |
| 92 | [Pilot Shell /prd Ideate step][r92] | Meth | CC, CX | 2,075 | 2026-09-18 | 59 | C | light |
| 93 | [diffmode_free (Growth Tactics)][r93] | SP | CC, CX | 162 | 2026-08-10 | 59 | C | light |
| 94 | [StartupKit][r94] | Meth | CC, CAI | 162 | 2026-04-22 | 59 | C | light |
| 95 | [brainstorm (1C agent-based dev framework)][r95] | SP | CC, CX, CUR | 108 | 2026-07-03 | 59 | C | light |
| 96 | [game-concept (novel-to-game)][r96] | SP | CC, CX, Kimi | 795 | 2026-09-21 | 59 | C | light |
| 97 | [brainstorm (optimus-claude)][r97] | SP | CC, CX | 74 | 2026-09-16 | 59 | C | light |
| 98 | [creative-problem-solver (tkersey)][r98] | SP | CX, CC | 70 | 2026-09-08 | 59 | C | light |
| 99 | [idea-brainstorm pipeline (research-units)][r99] | SP | CX, CC, rh CLI | 511 | 2026-09-12 | 59 | C | light |
| 100 | [AutoResearchClaw][r100] | Res | Python CLI, OpenClaw, CC, CX +4 | 14,505 | 2026-08-19 | 59 | C | light |
| 101 | [phaser-brainstorm][r101] | SP | CC, CX, CUR, OC | 24 | 2026-08-27 | 59 | C | light |
| 102 | [Gangsta Agents (The Grilling)][r102] | Meth | CC, CX, CUR, COP, OC, GEM, Pi | 82 | 2026-08-14 | 59 | C | light |
| 103 | [deep-brainstorm (mhylle)][r103] | SP | CC | 19 | 2026-09-02 | 59 | C | light |
| 104 | [the-midwife (gm-apprentice)][r104] | SP | CC, CAI | 14 | 2026-09-23 | 59 | C | light |
| 105 | [mindpowers][r105] | SP | CC, Cowork, CX, ChatGPT, CUR | 5 | 2026-08-08 | 59 | C | light |
| 106 | [divergent-agents (/diverge)][r106] | SP | CC, CX (claimed) | 4 | 2026-06-27 | 59 | C | light |
| 107 | [Ideate (LifeOS)][r107] | SP | CC, CX, SKILL.md hosts | 19,100 | 2026-09-04 | 58 | C | full |
| 108 | [BMAD Creative Intelligence Suite (CIS)][r108] | SP | CC, CX, npx skills | 186 | 2026-09-21 | 58 | C | full |
| 109 | [idea-generation (Anthropic financial-services)][r109] | SP | CC, Cowork, Managed Agents, CAI | 36,423 | 2026-09-21 | 58 | C | full |
| 110 | [research-ideation (claude-scholar)][r110] | SP | CC, CX, Kimi, OC | 5,609 | 2026-08-27 | 58 | C | full |
| 111 | [dbs-chatroom (dbskill)][r111] | SP | CC, CX, Doubao, WorkBuddy | 10,232 | 2026-09-07 | 58 | C | full |
| 112 | [cc-tree][r112] | SP | CC | 101 | 2026-09-03 | 58 | C | light |
| 113 | [AutoSci /novelty][r113] | Res | CC, CX, OC | 1,686 | 2026-09-18 | 58 | C | light |
| 114 | [HVE Core Design Thinking coach][r114] | SP | COP, Copilot CLI | 1,474 | 2026-09-23 | 58 | C | light |
| 115 | [auto-idea (autopus-adk)][r115] | SP | CC, CX, AG/GEM, OC, OMP | 111 | 2026-09-20 | 58 | C | light |
| 116 | [brainstorming (great_cto)][r116] | SP | CC, CX | 95 | 2026-09-22 | 58 | C | light |
| 117 | [Principia][r117] | Res | Local web app | 856 | 2026-09-15 | 58 | C | light |
| 118 | [ad-angles (superamped)][r118] | SP | CC, CX, CUR, OC | 70 | 2026-08-18 | 58 | C | light |
| 119 | [d-school (aparente)][r119] | SP | CC | 65 | 2026-08-19 | 58 | C | light |
| 120 | [marketing-os (Copy Lab + Hook Engine)][r120] | SP | CC, CX, CUR | 524 | 2026-08-17 | 58 | C | light |
| 121 | [scholar-brainstorm][r121] | SP | CC, CX, ZCode | 157 | 2026-09-18 | 58 | C | light |
| 122 | [libertee][r122] | SP | CC, Telegram | 17 | 2026-04-27 | 58 | C | light |
| 123 | [creative-thinking-for-research (Orchestra)][r123] | SP | CC, CX, GEM, CUR, OC +4 | 12,955 | 2026-06-16 | 57 | C | full |
| 124 | [unstuck (Ouroboros)][r124] | SP | CC, CX, OC, GEM, COP, Kiro +4 | 6,076 | 2026-09-21 | 57 | C | full |
| 125 | [game-changing-features (softaworks)][r125] | SP | CC, CX, CUR, CAI | 2,497 | 2026-03-05 | 57 | C | full |
| 126 | [FAROS][r126] | Res | Standalone web app | 3,037 | 2026-09-05 | 57 | C | full |
| 127 | [cc-thinking-skills][r127] | SP | CC, CAI, CX, COP, CUR | 1,325 | 2026-08-07 | 57 | C | full |
| 128 | [bmad-advanced-elicitation][r128] | SP | CC, CX, SKILL.md hosts | 53,361 | 2026-09-21 | 57 | C | light |
| 129 | [evanflow-brainstorming][r129] | SP | CC, npx skills | 418 | 2026-05-13 | 57 | C | light |
| 130 | [ai-team-orchestration (awesome-copilot)][r130] | SP | COP, CC, CX | 39,294 | 2026-09-07 | 57 | C | light |
| 131 | [triz (tome, claude-night-market)][r131] | SP | CC, npx skills | 337 | 2026-09-22 | 57 | C | light |
| 132 | [structured-brainstorming (fractional-cto)][r132] | SP | CC, Cowork, CX (skill) | 30 | 2026-08-06 | 57 | C | light |
| 133 | [brand-naming (Brand-building-skills)][r133] | SP | CC, CX, CUR, WS | 679 | 2026-06-11 | 57 | C | light |
| 134 | [SCAMPER ideas transformer (v0lka)][r134] | SP | CC, CX | 18 | 2026-09-20 | 57 | C | light |
| 135 | [Claude-Ideation-Planning-Plugin][r135] | SP | CC | 11 | 2026-08-17 | 57 | C | light |
| 136 | [Gemini CLI Plan Mode][r136] | SP | GEM | 107,132 | 2026-09-23 | 57 | C | critic |
| 137 | [Cursor Plan Mode + /best-of-n][r137] | SP | CUR | n/a | 2026-09-10 | 57 | C | critic |
| 138 | [GitHub Copilot Plan agent][r138] | SP | VS Code COP, Copilot CLI | 192,807 | 2026-09-23 | 57 | C | critic |
| 139 | [Miro MCP Server + miro plugin][r139] | MCP | CC, CAI, ChatGPT/CX, CUR, GEM, COP +6 | 154 | 2026-09-17 | 57 | C | critic |
| 140 | [council / council-multi-model (ECC)][r140] | SP | CC, CX, CUR, OC, GEM +2 | 265,504 | 2026-09-22 | 56 | C | full |
| 141 | [Claude Octopus][r141] | SP | CC, CX, CUR, OC, Factory | 4,094 | 2026-09-23 | 56 | C | full |
| 142 | [01-brainstorm (aidd-refine)][r142] | SP | CC, CX, CUR, COP, OC | 485 | 2026-09-23 | 56 | C | full |
| 143 | [idea-generator (claude-code-apple-skills)][r143] | SP | CC | 757 | 2026-07-24 | 56 | C | full |
| 144 | [generative-thinking (oaustegard)][r144] | SP | CC, CAI | 150 | 2026-09-23 | 56 | C | full |
| 145 | [brainstorm (robertguss toolkit)][r145] | SP | CC, CAI | 120 | 2026-09-16 | 56 | C | full |
| 146 | [Heuresis /ideate][r146] | SP | CC, CX | 162 | 2026-09-23 | 56 | C | light |
| 147 | [verbalized-sampling plugin (AIWG)][r147] | SP | CC, CX, CUR, COP, WS, Warp, Factory | 211 | 2026-09-22 | 56 | C | light |
| 148 | [screenwriting-skills][r148] | SP | CC, CX | 1,347 | 2026-09-22 | 56 | C | light |
| 149 | [/debate (AgentSys)][r149] | SP | CC, CX, OC, CUR, Kiro | 987 | 2026-09-13 | 56 | C | light |
| 150 | [brainstorm (Rune)][r150] | SP | CC, CX, CUR, WS, AG, OC +5 | 87 | 2026-08-16 | 56 | C | light |
| 151 | [gat-brainstorm (game-dev-skills)][r151] | SP | CC, CX | 79 | 2026-09-17 | 56 | C | light |
| 152 | [plan-plus (bkit)][r152] | SP | CC | 600 | 2026-09-20 | 56 | C | light |
| 153 | [Sounding (c11)][r153] | SP | c11, CC, CX, OC | 45 | 2026-09-21 | 56 | C | light |
| 154 | [claude-innovation-skills][r154] | SP | CAI, CC, CX | 5 | 2026-02-18 | 56 | C | light |
| 155 | [Lofn][r155] | Meth | CC, CX, OpenClaw | 23 | 2026-08-30 | 56 | C | light |
| 156 | [novel-idea-hunter][r156] | SP | CC, CX | 6 | 2026-08-28 | 56 | C | light |
| 157 | [Open Collider][r157] | SP | CC, CAI | 0 | 2026-06-25 | 56 | C | light |
| 158 | [brainstorm + brainstorm-techniques (Soleur)][r158] | SP | CC, CX, Devin, Grok | 15 | 2026-09-22 | 56 | C | light |
| 159 | [MITRE-ITK-Skills][r159] | SP | CC, CAI | 14 | 2026-07-21 | 56 | C | light |
| 160 | [arete][r160] | SP | CC, CX, OC, COP | 40 | 2026-05-09 | 56 | C | light |
| 161 | [idea-generator-skill (ludi-uni)][r161] | SP | CC, CAI, ChatGPT, CX | 4 | 2026-08-14 | 56 | C | light |
| 162 | [tree-of-thoughts + create-ideas (NeoLab)][r162] | SP | CC, GEM, AG, CX, CUR, OC | 1,719 | 2026-08-26 | 56 | C | critic |
| 163 | [Claude Code Agent Teams][r163] | Council | CC | 147,692 | 2026-09-22 | 56 | C | critic |
| 164 | [Edison Scientific Kosmos + Precedent][r164] | Res | Edison web, edison-client API | n/a | 2026-09-02 | 56 | C | critic |
| 165 | [ideate (openai/plugins product-design)][r165] | SP | Codex app, Codex CLI, ChatGPT | 7,119 | 2026-08-26 | 55 | C | full |
| 166 | [multi-agent-brainstorming (sickn33)][r166] | SP | CC, CX, CUR, GEM, AG, Kiro +2 | 46,800 | 2026-09-22 | 55 | C | full |
| 167 | [brainstorming (pm-claude-skills)][r167] | SP | CC, CAI, CX, CUR, WS +8 | 1,389 | 2026-09-22 | 55 | C | full |
| 168 | [The AI Scientist (v1)][r168] | Res | Python CLI | 14,602 | 2025-12-19 | 55 | C | full |
| 169 | [NanoResearch ideation][r169] | Res | CC, CX, Python CLI | 1,369 | 2026-08-25 | 55 | C | light |
| 170 | [brainstorming (jwynia)][r170] | SP | CC, CX | 160 | 2026-02-24 | 55 | C | light |
| 171 | [pm-advisory-board (SpaceZephyr)][r171] | SP | CC, CX, CUR | 1,091 | 2026-07-09 | 55 | C | light |
| 172 | [brainstorm (vgv-wingspan)][r172] | SP | CC | 105 | 2026-09-21 | 55 | C | light |
| 173 | [MultiAgent Decanting (mad)][r173] | SP | CC | 1 | 2026-08-30 | 55 | C | light |
| 174 | [Light Skills][r174] | SP | CC, CX, OC | 631 | 2026-07-06 | 55 | C | light |
| 175 | [neuroarxiv][r175] | SP | CC, CX | 429 | 2026-09-17 | 55 | C | light |
| 176 | [generate-design (Google Stitch)][r176] | SP | CX, CC, GEM, AG, CUR, OC | 8,353 | 2026-08-17 | 55 | C | light |
| 177 | [FutureHouse Robin][r177] | Council | Python, Edison platform | 714 | 2026-04-21 | 55 | C | light |
| 178 | [brainstorm (quiver)][r178] | SP | CC, CX, CUR, OC | 14 | 2026-09-21 | 55 | C | light |
| 179 | [Mobbin MCP][r179] | MCP | CC, CAI, CX, ChatGPT, CUR +14 | 45 | 2026-09-11 | 55 | C | critic |
| 180 | [unstuck (makerskills)][r180] | SP | CC, CX, CUR | 824 | 2026-09-04 | 54 | C | full |
| 181 | [brainstorm-diverge-converge (lyndonkl)][r181] | SP | CC, skills.sh agents | 160 | 2026-09-01 | 54 | C | full |
| 182 | [pstack (Cursor plugin)][r182] | SP | CUR (+ CC/CX ports) | 8,421 | 2026-09-23 | 54 | C | full |
| 183 | [brainstorm-ideas (borghei)][r183] | SP | CC, CAI, CX, CUR, GEM +6 | 812 | 2026-09-21 | 54 | C | full |
| 184 | [innovation-facilitator (babysitter)][r184] | SP | CC, Cowork, CX, CUR, GEM +3 | 1,808 | 2026-09-16 | 54 | C | full |
| 185 | [brainstorm (ClaudeKit /ck:brainstorm)][r185] | SP | CC, CX, CUR | n/a | 2026-07-14 | 54 | C | full |
| 186 | [naming (glacierphonk)][r186] | SP | CC, skills.sh agents | 105 | 2026-04-19 | 54 | C | full |
| 187 | [panning-for-gold (OB1)][r187] | SP | CC, CX, CUR | 4,636 | 2026-09-22 | 54 | C | full |
| 188 | [project-brainstorming (attune)][r188] | SP | CC, npx skills | 337 | 2026-09-22 | 54 | C | full |
| 189 | [trade-hypothesis-ideator][r189] | SP | CC, CAI | 2,878 | 2026-09-22 | 54 | C | full |
| 190 | [moai-foundation-thinking (MoAI-ADK)][r190] | SP | CC, CX | 1,219 | 2026-09-23 | 54 | C | light |
| 191 | [Superdesign skill][r191] | App | CC, CX, CUR | 592 | 2026-08-21 | 54 | C | light |
| 192 | [micode][r192] | SP | OC | 490 | 2026-09-21 | 54 | C | light |
| 193 | [story-ideator (Claude-Book)][r193] | SP | CC | 118 | 2026-01-22 | 54 | C | light |
| 194 | [brainstorm (hyperskills)][r194] | SP | CC, CX | 33 | 2026-09-05 | 54 | C | light |
| 195 | [WEIPING_LAB][r195] | Res | Python CLI + web UI | 119 | 2026-08-28 | 54 | C | light |
| 196 | [layers-skills][r196] | SP | CC, CX | 303 | 2026-05-30 | 54 | C | light |
| 197 | [ralph-ideate][r197] | SP | CC | 7 | 2026-09-21 | 54 | C | light |
| 198 | [SEED (typed project incubator)][r198] | SP | CC | 350 | 2026-06-03 | 54 | C | light |
| 199 | [opportunity-solution-tree (deanpeters)][r199] | SP | CC, CAI, CX, CUR | 7,049 | 2026-09-01 | 54 | C | critic |
| 200 | [Stanford Research Ideation Agent][r200] | Res | Python CLI | 408 | 2025-08-07 | 54 | C | critic |
| 201 | [Haft (/h-explore)][r201] | MCP | CC, CX, Grok, Pi +6 | 1,393 | 2026-08-11 | 54 | C | critic |
| 202 | [creative-ideation (Hermes Agent)][r202] | SP | Hermes, CC, CX | 248,134 | 2026-09-23 | 53 | C | full |
| 203 | [llm-council (am-will/codex-skills)][r203] | SP | CX, CC, GEM, OC | 1,032 | 2026-07-14 | 53 | C | full |
| 204 | [brainstormer agent (agentkits-marketing)][r204] | SP | CC, CAI, CUR, WS, Cline, COP | 606 | 2026-08-28 | 53 | C | full |
| 205 | [brainstorming-skill (Jamie-BitFlight)][r205] | SP | CC, CX (unverified) | 66 | 2026-09-23 | 53 | C | full |
| 206 | [Wonder Pill][r206] | SP | CAI, CC | 127 | 2026-09-02 | 53 | C | light |
| 207 | [council + idea-genie (agentops)][r207] | SP | CC, CX, CUR, GEM | 444 | 2026-09-22 | 53 | C | light |
| 208 | [research-ideation (awesome-econ-ai-stuff)][r208] | SP | CC, CUR, CX, GEM | 636 | 2026-08-31 | 53 | C | light |
| 209 | [cm-brainstorm-idea (CodyMaster)][r209] | SP | CC, CX, CUR, GEM +10 | 53 | 2026-08-25 | 53 | C | light |
| 210 | [content-ideas][r210] | SP | CC, CX, CAI, CUR, COP, GEM | 122 | 2026-05-30 | 53 | C | light |
| 211 | [ideation (gran-maestro)][r211] | SP | CC, CX | 24 | 2026-08-19 | 53 | C | light |
| 212 | [game-ideation + spark-lens (gstack-game)][r212] | SP | CC | 70 | 2026-05-31 | 53 | C | light |
| 213 | [TRIZ Skills (MCP)][r213] | MCP | CC, CAI | 10 | 2026-08-06 | 53 | C | light |
| 214 | [blueprint (forge-skills)][r214] | SP | CC | 15 | 2026-09-22 | 53 | C | light |
| 215 | [game-brainstorm (AlterLab GameForge)][r215] | SP | CC, CAI | 40 | 2026-03-30 | 53 | C | light |
| 216 | [AI2 CodeScientist][r216] | Res | Python web app | 351 | 2026-03-25 | 53 | C | light |
| 217 | [InfraNodus MCP Server][r217] | MCP | CC, CAI, CX, ChatGPT, CUR +3 | 103 | 2026-09-20 | 53 | C | critic |
| 218 | [/sc:brainstorm (SuperClaude)][r218] | SP | CC | 23,901 | 2026-09-15 | 52 | C | full |
| 219 | [bmad-brainstorm (aj-geddes BMAD skills)][r219] | SP | CC | 489 | 2026-06-20 | 52 | C | full |
| 220 | [lenny-skills (RefoundAI)][r220] | SP | CC, CUR | 1,344 | 2026-07-16 | 52 | C | full |
| 221 | [brainstorm (Claudest)][r221] | SP | CC | 275 | 2026-09-14 | 52 | C | light |
| 222 | [52-newsletter-ideas (gtm-skills)][r222] | SP | CC, CX, CUR, CAI | 159 | 2026-09-22 | 52 | C | light |
| 223 | [xs-bridge-ideas + xs-multi-agent][r223] | SP | CC, CX, Grok, xangi | 138 | 2026-08-18 | 52 | C | light |
| 224 | [mcp-rubber-duck][r224] | MCP | CC, CAI, CX, any MCP client | 176 | 2026-09-15 | 52 | C | light |
| 225 | [brainstorm-game (Summer Engine)][r225] | SP | CC, CX, CUR, WS | 67 | 2026-09-11 | 52 | C | light |
| 226 | [xiaoma-durex-copywriter][r226] | SP | CC, CAI | 577 | 2026-08-08 | 52 | C | light |
| 227 | [six-thinking-hats (jiamu-skills)][r227] | SP | CC, skills CLI agents | 137 | 2026-07-14 | 52 | C | light |
| 228 | [Ask LLM (/brainstorm, /brainstorm-all)][r228] | SP | CC, CX (MCP), CUR, Pi | 18 | 2026-09-22 | 52 | C | light |
| 229 | [research-idea-and-battle][r229] | SP | CC, CAI, CX | 94 | 2026-05-19 | 52 | C | light |
| 230 | [Co-Scientist (Kaimen-Inc)][r230] | Res | Python CLI, CC/CX backends | 264 | 2026-08-03 | 52 | C | light |
| 231 | [crazy-8s (cris-achiardi)][r231] | SP | CAI, CC | 70 | 2026-04-27 | 52 | C | light |
| 232 | [OpenClaw Agents (shenhao-stu)][r232] | Council | OpenClaw, chat channels | 456 | 2026-03-09 | 52 | C | light |
| 233 | [content-idea-generator (ai-marketing skills)][r233] | SP | CC, OpenClaw, CUR, WS, CX | 424 | 2026-03-19 | 52 | C | light |
| 234 | [out-the-box-thinking MCP][r234] | MCP | CC, CAI, CX | 1 | 2026-07-03 | 52 | C | light |
| 235 | [claude-youtube][r235] | SP | CC | 389 | 2026-04-10 | 52 | C | light |
| 236 | [idea-generation + novelty-assessment (lingzhi227)][r236] | SP | CC | 355 | 2026-02-27 | 52 | C | light |
| 237 | [agent-teams /team-debug + parallel-debugging][r237] | SP | CC, CX (skill), CUR, OC, COP +3 | 39,890 | 2026-09-21 | 52 | C | critic |
| 238 | [Kosmos (Edison Scientific)][r238] | Res | Edison web platform | n/a | 2026-09-02 | 52 | C | critic |
| 239 | [brainstorm-mcp][r239] | MCP | CC, CAI, VS Code/COP, any MCP | 70 | 2026-09-19 | 51 | C | full |
| 240 | [Fabric idea patterns][r240] | Tech | Fabric CLI, any LLM | 44,047 | 2026-09-21 | 51 | C | full |
| 241 | [brainstorm (AI DevKit)][r241] | SP | CC, CX, GEM, CUR, OC, COP | 1,635 | 2026-09-22 | 51 | C | full |
| 242 | [swarm-to-plan (dyad)][r242] | SP | CC (Agent Teams) | 21,602 | 2026-09-23 | 51 | C | full |
| 243 | [verbalized-sampling (gnurio)][r243] | SP | CC, CUR, CX | 112 | 2026-08-13 | 51 | C | full |
| 244 | [Microsoft TinyTroupe][r244] | Council | Python, OpenAI/Azure | 7,570 | 2026-07-03 | 51 | C | full |
| 245 | [creative-production (openai/plugins)][r245] | SP | Codex app, Codex CLI | 7,119 | 2026-08-27 | 51 | C | full |
| 246 | [lateral-thinking-skill (ogiberstein)][r246] | SP | CC | 16 | 2026-03-11 | 51 | C | light |
| 247 | [first-principles-thinking subagent (VoltAgent)][r247] | SP | CC | 25,272 | 2026-09-21 | 51 | C | light |
| 248 | [~prd (HelloAGENTS)][r248] | SP | CC, CX, GEM, Grok, CUR | 704 | 2026-09-06 | 51 | C | light |
| 249 | [/brainstorm (cc-blueprint-toolkit)][r249] | SP | CC | 194 | 2025-11-26 | 51 | C | light |
| 250 | [argue][r250] | Council | CC, CX, GEM, OC | 277 | 2026-07-31 | 51 | C | light |
| 251 | [innovation plugin (Panaversity)][r251] | SP | CC, Cowork | 32 | 2026-03-26 | 51 | C | light |
| 252 | [think (dot-skills)][r252] | SP | CC, CX, CUR | 210 | 2026-08-15 | 51 | C | light |
| 253 | [Agent Council (yogirk)][r253] | Council | CC, CX, GEM | 90 | 2026-04-07 | 51 | C | light |
| 254 | [team-brainstorm (Claude-Code-Workflow)][r254] | SP | CC, CX | 2,131 | 2026-06-18 | 51 | C | light |
| 255 | [design-loop brainstorm (orchflows)][r255] | SP | CC, CX, Kimi | 116 | 2026-09-23 | 51 | C | light |
| 256 | [s4h-creativity-brainstorm][r256] | SP | CC | 228 | 2026-07-15 | 50 | C | full |
| 257 | [The AI Scientist-v2 (ideation stage)][r257] | Res | Python CLI | 7,208 | 2025-12-19 | 50 | C | full |
| 258 | [idea-generation (Scientify)][r258] | SP | OpenClaw, CC/CX (partial) | 2,244 | 2026-09-08 | 50 | C | full |
| 259 | [Council (LifeOS)][r259] | SP | CC | 19,100 | 2026-09-04 | 50 | C | light |
| 260 | [/ideate (PM Brain)][r260] | SP | CC | 878 | 2026-05-20 | 50 | C | light |
| 261 | [Verbalized Sampling][r261] | Res | Any LLM, Python library | 811 | 2026-01-03 | 50 | C | light |
| 262 | [deliberation (MCP)][r262] | MCP | CC, CX, CUR, Kiro, OC, VS Code +5 | 161 | 2026-09-20 | 50 | C | light |
| 263 | [PatSnap MCP][r263] | MCP | CAI, CC, CUR, WS | 111 | 2026-08-20 | 50 | C | light |
| 264 | [brainstorm (digital-stoic-org)][r264] | SP | CC | 20 | 2026-09-21 | 50 | C | light |
| 265 | [prd-v10-continuous-discovery-torres][r265] | SP | CC | 179 | 2026-08-31 | 50 | C | light |
| 266 | [GoDaddy MCP (domain suggestions)][r266] | MCP | CAI, CC, ChatGPT, CUR | n/a | 2026-07 | 50 | C | critic |
| 267 | [Denario][r267] | Res | Python, Streamlit GUI | 599 | 2026-06-02 | 50 | C | critic |
| 268 | [BeCreative (LifeOS)][r268] | SP | CC, CX, CUR, Hermes | 19,100 | 2026-09-04 | 49 | C | full |
| 269 | [project-idea-validator (VoltAgent)][r269] | SP | CC, CX | 25,271 | 2026-09-21 | 49 | C | full |
| 270 | [thinking-partner (claudesidian)][r270] | SP | CC, CX, OC, CUR, Pi | 2,585 | 2026-04-11 | 49 | C | light |
| 271 | [/brainstorm (AWF)][r271] | SP | AG | 207 | 2026-05-22 | 49 | C | light |
| 272 | [council (kitze)][r272] | SP | CC, CX, CUR, GEM, Grok, OC | 197 | 2026-09-18 | 49 | C | light |
| 273 | [RIPER-5 /riper:innovate][r273] | Meth | CC | 95 | 2026-08-16 | 49 | C | light |
| 274 | [ideate (av/skills)][r274] | SP | CC, CX, OC, CUR | 15 | 2026-09-20 | 49 | C | light |
| 275 | [thinking-partner (mattnowdev)][r275] | SP | CC, CUR, WS, Cline, COP | 198 | 2026-03-31 | 49 | C | light |
| 276 | [fusion-harness][r276] | Council | Pi | 583 | 2026-08-23 | 49 | C | light |
| 277 | [brainstorming (JetBrains ThinkRail)][r277] | SP | ThinkRail (pi) | 481 | 2026-09-22 | 48 | C | full |
| 278 | [octto][r278] | SP | OC | 511 | 2026-09-17 | 48 | C | full |
| 279 | [hyperplan / Ultrawork Planner (oh-my-openagent)][r279] | Council | OC, OmO, CX (light) | 69,300 | 2026-09-23 | 48 | C | full |
| 280 | [slavingia/skills (Minimalist Entrepreneur)][r280] | SP | CC | 10,472 | 2026-04-14 | 48 | C | full |
| 281 | [Compound Knowledge (kw:brainstorm)][r281] | SP | CC | 421 | 2026-08-07 | 48 | C | light |
| 282 | [Cursor Memory Bank /creative][r282] | Meth | CUR | 3,062 | 2026-05-26 | 48 | C | light |
| 283 | [JARVIS (voice for Claude Code)][r283] | App | macOS, CC | 794 | 2026-09-10 | 48 | C | light |
| 284 | [brand-name-explore (az-skills)][r284] | SP | CC | 49 | 2026-07-16 | 48 | C | light |
| 285 | [product-ideation-pm (OPB-Skills)][r285] | SP | CC, CX, OC | 122 | 2026-02-11 | 48 | C | light |
| 286 | [ideation (ideation_team_skill)][r286] | SP | CC (Agent Teams) | 51 | 2026-03-01 | 48 | C | light |
| 287 | [Grok-mcp][r287] | MCP | CC, CAI | 152 | 2026-08-19 | 48 | C | light |
| 288 | [metaswarm /brainstorm][r288] | Council | CC, CX, GEM, CUR, OC | 419 | 2026-06-19 | 48 | C | light |
| 289 | [roblox-game-ideas][r289] | SP | CC | 10 | 2026-07-01 | 48 | C | light |
| 290 | [Debby (Omnigent)][r290] | Council | Omnigent CLI/web/app | 10,166 | 2026-09-23 | 47 | C | full |
| 291 | [Devils Advocate agent (awesome-copilot)][r291] | SP | COP | 39,293 | 2026-09-23 | 47 | C | full |
| 292 | [next-idea (CC Workflow Studio)][r292] | SP | CC | 5,387 | 2026-09-20 | 47 | C | full |
| 293 | [ideate (tome)][r293] | SP | CC, npx skills | 337 | 2026-09-22 | 47 | C | full |
| 294 | [AI-Researcher (HKUDS)][r294] | Res | Python, Gradio | 5,762 | 2025-10-16 | 47 | C | full |
| 295 | [/brainstorm + brainstorming (AG Kit)][r295] | Meth | AG, GEM, CC/CX (skill) | 8,181 | 2026-09-06 | 47 | C | full |
| 296 | [codex-brainstorm (sd0x-harness)][r296] | SP | CC, CX (opponent) | 189 | 2026-09-05 | 47 | C | full |
| 297 | [Aperant Ideation view][r297] | App | Electron desktop | 14,568 | 2026-06-14 | 47 | C | full |
| 298 | [game-design-brainstorm-methods][r298] | SP | OpenClaw, CC, CX | 69 | 2026-09-19 | 47 | C | full |
| 299 | [creativity-innovation (human-skill-tree)][r299] | SP | CC, CX, CUR, GEM | 561 | 2026-03-25 | 47 | C | light |
| 300 | [research-ideation-full (InnoClaw)][r300] | SP | InnoClaw, CC | 394 | 2026-08-10 | 47 | C | light |
| 301 | [Creative Thinking MCP Server][r301] | MCP | CC, CAI, any MCP | 0 | 2026-09-21 | 47 | C | light |
| 302 | [shrimp-brainstorming][r302] | SP | Hermes, CC/CX (manual) | 34 | 2026-07-19 | 47 | C | light |
| 303 | [InkOS][r303] | App | InkOS, OpenClaw, CC | 10,017 | 2026-08-25 | 47 | C | light |
| 304 | [Virtual Lab][r304] | Council | Python, OpenAI | 737 | 2025-12-31 | 47 | C | light |
| 305 | [awesome-ux-skills][r305] | SP | CC | 226 | 2026-08-10 | 47 | C | light |
| 306 | [agtx-brainstorm][r306] | SP | CC, CX, pi | 1,651 | 2026-09-19 | 46 | C | full |
| 307 | [brainstorm (Chorus AI-DLC)][r307] | SP | CC, CX, Kiro, OpenClaw, Pi +3 | 1,174 | 2026-09-22 | 46 | C | full |
| 308 | [gemini-mcp-tool (jamubc)][r308] | MCP | CC, CAI, any MCP | 2,283 | 2026-07-21 | 46 | C | full |
| 309 | [/consider:* (TACHES)][r309] | SP | CC | 1,981 | 2026-04-01 | 46 | C | light |
| 310 | [brainstorm (ComfyTV)][r310] | SP | ComfyTV bot, CC (MCP) | 1,032 | 2026-09-23 | 46 | C | light |
| 311 | [pm-brainstorm (nanopm)][r311] | SP | CC, CX, Mistral Vibe | 51 | 2026-07-06 | 46 | C | light |
| 312 | [ScholarScout][r312] | SP | Standalone web app | 41 | 2026-07-26 | 46 | C | light |
| 313 | [brainstorm (claude-code-blueprint)][r313] | SP | CC | 116 | 2026-03-04 | 46 | C | light |
| 314 | [campaign brainstorm (proposal-agent)][r314] | SP | CC | 31 | 2026-08-08 | 46 | C | light |
| 315 | [claude-skills-mental-models][r315] | SP | CC, CX, CUR, OC | 19 | 2026-09-10 | 46 | C | light |
| 316 | [macrothink (paperthin)][r316] | SP | CC, CX, OC, CUR, COP, AG | 1,114 | 2026-09-21 | 46 | C | critic |
| 317 | [The Idea Wizard][r317] | SP | CC, CX, GEM, CAI | 116 | 2026-09-22 | 45 | C | full |
| 318 | [napkin whiteboard (awesome-copilot)][r318] | SP | Copilot CLI, skills.sh | 39,294 | 2026-09-23 | 45 | C | light |
| 319 | [polymath ideate mode (production-grade)][r319] | SP | CC, CX, OC, Pi | 178 | 2026-08-19 | 45 | C | light |
| 320 | [six-thinking-hats (agentic-qe)][r320] | SP | CC, Kiro, OC, CX | 482 | 2026-09-22 | 45 | C | light |
| 321 | [expand-and-contract][r321] | SP | CAI, CC | 69 | 2026-05-28 | 45 | C | light |
| 322 | [Proven-Viral-Content-System][r322] | SP | CC, CX, CUR, OC, AG | 147 | 2026-08-09 | 45 | C | light |
| 323 | [PAL MCP Server (formerly Zen MCP)][r323] | MCP | CC, CAI, CX, GEM, Qwen, CUR | 11,757 | 2025-12-15 | 44 | C | full |
| 324 | [songwriting-and-ai-music (Hermes)][r324] | SP | Hermes, CC, CX | 248,145 | 2026-09-23 | 44 | C | full |
| 325 | [cw-brainstorm (Compound Writing)][r325] | SP | CC, CX | 288 | 2026-09-15 | 44 | C | full |
| 326 | [Idea Universe][r326] | Tech | Any chat LLM | 32 | 2026-07-20 | 44 | C | light |
| 327 | [force-associations][r327] | SP | CX, CC | 39 | 2026-08-07 | 44 | C | light |
| 328 | [/ideate (freelance-developer-harness)][r328] | SP | CC | 33 | 2026-08-10 | 44 | C | light |
| 329 | [ResearchTown][r329] | Res | Python | 212 | 2025-07-11 | 44 | C | light |
| 330 | [persona-ideation-strategist (SoDam)][r330] | SP | CX, CC | 11 | 2026-09-22 | 44 | C | light |
| 331 | [creative-ad-agent][r331] | App | Claude Agent SDK | 117 | 2026-09-06 | 44 | C | light |
| 332 | [domain-name-brainstormer (ComposioHQ)][r332] | SP | CC, CAI, API, CX, CUR, GEM | 75,500 | 2026-09-18 | 43 | C | full |
| 333 | [idea-evaluator (agentic-awesome-skills)][r333] | SP | CC, GEM, CX, AG | 46,800 | 2026-09-22 | 43 | C | light |
| 334 | [sixhats (neurofoo)][r334] | SP | CC, OC | 118 | 2026-01-19 | 43 | C | light |
| 335 | [brahma-bhaga (Agent Almanac)][r335] | SP | CC, CX, CUR, GEM, Aider, OC, WS | 34 | 2026-09-22 | 43 | C | light |
| 336 | [idea-miner (agent-idea-feed)][r336] | SP | CX, CC | 23 | 2026-07-22 | 43 | C | light |
| 337 | [Gauntlet (VerticalResearchGroup)][r337] | Council | Python (Anthropic + Gemini APIs) | 41 | 2026-02-14 | 43 | C | light |
| 338 | [Sideways (lateral-thinking MCP)][r338] | MCP | CC, CAI, CX, ChatGPT, CUR +13 | 0 | 2026-09-22 | 43 | C | critic |
| 339 | [Mysti][r339] | App | VS Code (CC/CX/GEM backends) | 1,138 | 2026-09-22 | 42 | C | full |
| 340 | [idea-reality-mcp][r340] | MCP | CC, CAI, CUR, WS, Cline | 822 | 2026-09-18 | 42 | C | full |
| 341 | [llm-council (DAIR.AI Academy)][r341] | SP | CC | 614 | 2026-07-21 | 42 | C | light |
| 342 | [scamper (neurofoo)][r342] | SP | CC, OC | 118 | 2026-01-19 | 42 | C | light |
| 343 | [gemini-mcp (RLabs)][r343] | MCP | CC, CAI | 219 | 2026-07-08 | 42 | C | light |
| 344 | [WEIPING_COUNCIL][r344] | Council | Web app, CLI | 132 | 2026-08-28 | 42 | C | light |
| 345 | [brainstorm + council (johnlindquist)][r345] | SP | CC | 26 | 2025-12-19 | 42 | C | light |
| 346 | [PolyClaude][r346] | SP | CC | 179 | 2026-03-22 | 42 | C | light |
| 347 | [claude-brainstorm (MadeByTokens)][r347] | SP | CC | 14 | 2026-01-23 | 41 | C | light |
| 348 | [brainstorming v2 (MadAppGang)][r348] | SP | CC | 282 | 2026-03-15 | 41 | C | light |
| 349 | [claudekit Brainstorm output style][r349] | SP | CC | 97 | 2026-07-22 | 41 | C | light |
| 350 | [dsh-solo-thinking][r350] | SP | DeepSeek Harness | 23 | 2026-08-21 | 41 | C | light |
| 351 | [AI-CoScientist (Swarm Corporation)][r351] | Council | Python (Swarms) | 129 | 2025-07-11 | 41 | C | light |
| 352 | [owlex][r352] | MCP | CC, any MCP client | 139 | 2026-03-15 | 41 | C | light |
| 353 | [ac-ideation (AlteredCraft)][r353] | SP | CC | 13 | 2026-05-18 | 41 | C | light |
| 354 | [Chain of Ideas (CoI-Agent)][r354] | Res | Python CLI | 511 | 2025-01-15 | 41 | C | critic |
| 355 | [Idea Generator agent (awesome-copilot)][r355] | SP | COP, CC (port) | 39,293 | 2026-09-23 | 40 | C | full |
| 356 | [Iterative Multi-Agent Brainstorming (pattern)][r356] | Res | CC (manual prompt) | 4,983 | 2026-08-25 | 40 | C | full |
| 357 | [brainstorming (microclaw)][r357] | SP | MicroClaw | 739 | 2026-09-05 | 40 | C | full |
| 358 | [brainstormer (Atris)][r358] | SP | Atris, CC, CX, GEM | 70 | 2026-09-21 | 40 | C | light |
| 359 | [trend-researcher (contains-studio)][r359] | SP | CC | 12,419 | 2025-07-28 | 40 | C | light |
| 360 | [LLM Council Plus][r360] | Council | Web app | 129 | 2026-09-08 | 40 | C | light |
| 361 | [MultiColleagues Brainstorm][r361] | Council | Web app | 7 | 2026-08-12 | 40 | C | light |
| 362 | [static-ad-concept-generator (Creatify)][r362] | SP | CC, CAI | 38 | 2026-03-03 | 40 | C | light |
| 363 | [superpowers-brainstorm (Antigravity port)][r363] | SP | AG | 837 | 2026-01-18 | 39 | C | light |
| 364 | [Ramify][r364] | SP | DeepSeek Harness web | 15 | 2026-09-21 | 39 | C | light |
| 365 | [/brainstorm (gemini-kit)][r365] | SP | GEM | 374 | 2026-03-07 | 39 | C | light |
| 366 | [Drunk Claude][r366] | SP | CC | 197 | 2026-06-27 | 38 | C | light |
| 367 | [debate-simulator (OneWave)][r367] | SP | CC, CX, CAI | 302 | 2026-09-23 | 38 | C | light |
| 368 | [Agent Council (team-attention)][r368] | SP | CC, CX | 139 | 2025-12-24 | 38 | C | light |
| 369 | [CycleResearcher][r369] | Res | Python (vLLM) | 402 | 2026-03-05 | 38 | C | light |
| 370 | [SciAgents (MIT LAMM)][r370] | Res | Python / Jupyter | 639 | 2025-05-10 | 38 | C | critic |
| 371 | [LLM Council (karpathy)][r371] | App | Local web app | 24,952 | 2025-11-22 | 37 | C | full |
| 372 | [brainstorm-premise (BMAD Creative Writing V4)][r372] | SP | CC, CUR | 53,361 | 2025-10-29 | 37 | C | light |
| 373 | [plugin-ideation (Plugin Freedom System)][r373] | SP | CC | 215 | 2025-11-19 | 37 | C | light |
| 374 | [flow-brainstorm commands][r374] | SP | CC | 38 | 2025-11-17 | 37 | C | light |
| 375 | [bgb-brainstorming-idea-bot][r375] | SP | CC, CX, MCP hosts | 582 | 2026-09-11 | 36 | C | full |
| 376 | [claude-co-commands (/co-brainstorm)][r376] | SP | CC, CX (via MCP) | 149 | 2026-02-19 | 36 | C | light |
| 377 | [problem-solving skill set (superpowers-skills)][r377] | SP | CC | 748 | 2025-10-14 | 36 | C | critic |
| 378 | [llm-council-skill (gcpdev)][r378] | SP | CC, CAI | 446 | 2026-01-08 | 35 | C | full |
| 379 | [ad-angle-multiplier][r379] | SP | CC, CX, CUR, WS, OpenClaw | 756 | 2026-03-26 | 35 | C | light |
| 380 | [how-to-earn-a-billion-dollars][r380] | SP | CC, CX | 104 | 2026-07-10 | 35 | C | light |
| 381 | [idea_lab (Claude-Cortex)][r381] | SP | CC | 42 | 2026-06-29 | 35 | C | light |
| 382 | [jamming][r382] | SP | CC, CX, AG, Pi, Hermes | 18 | 2026-09-08 | 34 | C | light |
| 383 | [Brainstormers (Azzedde)][r383] | SP | Web app | 639 | 2025-08-02 | 33 | C | light |
| 384 | [ralph-brainstormer][r384] | Council | CC, GEM, CX CLIs | 49 | 2026-01-07 | 33 | C | light |
| 385 | [Brainstorming Dev][r385] | App | Web | 49 | 2026-02-07 | 33 | C | light |
| 386 | [ideacao (Flowgrammers)][r386] | SP | CC, CAI, CUR, CX, WS | 114 | 2026-06-01 | 32 | C | light |
| 387 | [Cognitive Multi-Thinker mode (Roo)][r387] | Tech | Roo Code | 184 | 2026-09-03 | 31 | C | light |
| 388 | [/sg:brainstorm (SuperGemini)][r388] | SP | GEM | 245 | 2026-02-03 | 30 | C | light |
| 389 | [Heinrich: The Inventing Machine][r389] | SP | Python CLI | 20 | 2026-07-20 | 30 | C | light |
| 390 | [SPARC innovator mode (Ruflo)][r390] | SP | CC | 73,090 | 2026-09-22 | 29 | C | full |
| 391 | [Roo Code Brainstorm mode (issue #9061)][r391] | Tech | Roo Code | 24,299 | 2026-05-15 | 29 | C | light |
| 392 | [oblique-skill][r392] | SP | CC | 17 | 2025-12-23 | 28 | C | light |
| 393 | [Dreamtap][r393] | MCP | CAI, ChatGPT | n/a | 2025-09-26 | 27 | C | critic |

---

## 14. Methodology and limitations

### 14.1 Pipeline and counts

| Stage | Count |
|---|---|
| Sweep lanes | 12 (multi-model councils, Claude marketplaces, GitHub code, research ideation, methodologies, awesome lists, product/creative, international/niche, community, technique-first, Codex and other agents, MCP servers) |
| Gap-hunting angles | 12 (official vendors, recency, snowball from credits, vocabulary, personas, issues/discussions, media, marketplace deep-dive, packages/extensions, creative domains, decision/strategy, international round 2) |
| Raw candidates | 2,371 |
| Deduplicated tools | 2,283 (the long-tail CSV holds 2,281 rows: 150 full-verify, 300 light-verify and 1,831 metadata-only) |
| Full-verified | 150 |
| Light-verified | 300 |
| Metadata-only long tail | 1,831 |
| Verified records | 483 (= 393 ranked + 46 rejected + 40 copies + 4 directories) |
| Ranked | 393 (32 of them critic-added; 33 records were critic-added in total) |
| Adversarially challenged | 61 |

**Screening.** After the sweep, all 2,283 tools were screened on four signals: triage priority, GitHub stars (log-scaled), recency, and the number of lanes that found them. The top 150 were fully verified (at most 2 per repo), the next 300 light-verified, and the rest kept as metadata. The full long tail, with stars, last push, screening score and check tier for every tool, is in [**`data/all_candidates.csv`**](data/all_candidates.csv).

**Verification tiers.** "full" means the SKILL.md or source, the repo metadata, install docs, issues and adoption signals were read. "light" is a shorter check. "critic" means an adversarial reviewer added the tool as a missing peer. 61 records were challenged by two reviewers, one for evidence and adoption and one for ideation quality. Their corrections changed criterion scores (evidence, trust, ease, portability, divergence and others), and the challenged scores are final. The other 332 ranked tools keep single-pass scores.

### 14.2 Rubric

Score = sum over criteria of weight x (criterion score / 5), where each criterion is scored 0-5 and the weights total 100.

| Criterion | Weight | What it measures |
|---|---|---|
| Divergence | 15 | Real breadth machinery: techniques, quantity, isolation, multiple models, anti-mode-collapse |
| Convergence | 10 | Criteria, scoring, ranking, critique, pre-mortem |
| Interaction | 10 | Facilitation quality: questions, human control, resumability |
| Handoff | 10 | Durable artifacts and a pipeline into spec, plan or build |
| Grounding | 5 | Codebase, web, literature or data evidence |
| Evidence | 10 | Evals, benchmarks, practitioner reports showing it works |
| Adoption | 10 | Stars and installs (bulk-install artifacts were discounted where found) |
| Maintenance | 10 | Recency of commits and releases, issue handling |
| Portability | 10 | Claude Code, Codex and other hosts |
| Ease | 5 | Install friction and context cost |
| Trust | 5 | License, author, hooks, telemetry, scripts, security findings |

Example: ce-ideate is 4,4,4,5,5,1,5,5,5,3,4, which gives 12+8+8+10+5+2+10+10+10+3+4 = **82**.

### 14.3 Limitations and blind spots

- **The scores measure design, adoption and hygiene, not measured idea quality.** No ranked tool has a controlled comparison against vanilla prompting for coding agents, so the rubric cannot reward one.
- **Adoption signals are noisy.** skills.sh counts are often whole-collection bulk installs. Star inflation could not be ruled out: the GitHub stargazers endpoint returned 404 in this environment. Author fame drives stars (gstack).
- **Search coverage gaps.** Several gap lanes ran after the session's 200-search WebSearch budget was used up. They fell back to the gh CLI, registry APIs and WebFetch, so some web-only tools may be missing. Non-English coverage (Chinese, Japanese, Korean, Spanish, Portuguese, German, French, Russian) was searched but is thinner.
- **Closed products** (Claude Design, Co-Scientist, Cursor, Mobbin, GoDaddy, Kosmos) were judged from docs, release notes and third-party reports, not source code.
- **Duplicate records** stayed in the ranking because ranks are fixed: #8 and #71 (Co-Scientist), #15 and #31 (Owl-Listener designer-skills), #164 and #238 (Edison Kosmos). #4 and #16 share the gstack repo but are different skills.
- **Light-verified and unchallenged records** (332) may carry errors that the challenged ones had corrected, such as wrong risk ratings, stale install counts or overstated mechanisms. Treat their mechanism summaries as the authors' claims.
- **Fast churn.** Many tools release daily (ce, gstack, OpenSpec). Install commands and skill names can change within weeks of 2026-09-23.
- **Security findings** come from repo reading, issue trackers and skills.sh audit labels (Gen Agent Trust Hub, Socket, Snyk). Nothing was installed or executed during this research.

[r1]: https://github.com/EveryInc/compound-engineering-plugin/tree/main/skills/ce-ideate
[r2]: https://github.com/bmad-code-org/BMAD-METHOD/tree/main/skills/bmad-brainstorming
[r3]: https://github.com/wanshuiyin/Auto-claude-code-research-in-sleep/tree/main/skills/idea-discovery
[r4]: https://github.com/garrytan/gstack/tree/main/office-hours
[r5]: https://github.com/obra/superpowers/tree/HEAD/skills/brainstorming
[r6]: https://github.com/K-Dense-AI/scientific-agent-skills/tree/main/skills/scientific-brainstorming
[r7]: https://github.com/addyosmani/agent-skills/tree/main/skills/idea-refine
[r8]: https://docs.cloud.google.com/gemini/enterprise/docs/co-scientist-and-alphaevolve
[r9]: https://www.anthropic.com/news/claude-design-anthropic-labs
[r10]: https://github.com/nWave-ai/nWave/tree/main/nWave/skills/nw-brainstorming
[r11]: https://github.com/yogsoth-ai/de-anthropocentric-research-engine
[r12]: https://github.com/raine/consult-llm/tree/HEAD/skills/workshop
[r13]: https://github.com/QinghongLin/data2story-skill/tree/HEAD/skills/sparring-partner
[r14]: https://github.com/iliaal/whetstone/blob/HEAD/plugins/whetstone/commands/ia-ideate.md
[r15]: https://github.com/Owl-Listener/designer-skills/blob/HEAD/prototyping-testing/commands/explore-options.md
[r16]: https://github.com/garrytan/gstack/tree/main/design-shotgun
[r17]: https://allenai.org/blog/autodiscovery
[r18]: https://github.com/phuryn/pm-skills/tree/main/pm-product-discovery/skills/brainstorm-ideas-new
[r19]: https://github.com/coreyhaines31/marketingskills/tree/HEAD/skills/marketing-ideas
[r20]: https://github.com/UditAkhourii/adhd
[r21]: https://github.com/Fission-AI/OpenSpec/tree/main/skills/openspec-explore
[r22]: https://github.com/mattpocock/skills/tree/main/skills/productivity/grill-me
[r23]: https://github.com/0xNyk/council-of-high-intelligence
[r24]: https://github.com/ResearAI/DeepScientist
[r25]: https://github.com/microsoft/ResearchStudio
[r26]: https://github.com/bmad-code-org/bmad-module-game-dev-studio/tree/main/src/workflows/1-preproduction/gds-brainstorm-game
[r27]: https://github.com/TexasBedouin/vibe-check
[r28]: https://github.com/anthropics/claude-plugins-official/tree/main/plugins/feature-dev
[r29]: https://github.com/MaxKmet/idea-validation-agents
[r30]: https://github.com/NintendaDev/unikit-ai/tree/HEAD/skills/unikit-gd-brainstorm
[r31]: https://github.com/Owl-Listener/designer-skills/tree/HEAD/prototyping-testing/skills/parallel-concepts
[r32]: https://github.com/mikubaka88/CCFA-Skills/tree/HEAD/ccf-idea-optimizer
[r33]: https://github.com/anthropics/knowledge-work-plugins/tree/main/product-management/skills/product-brainstorming
[r34]: https://github.com/Orchestra-Research/AI-Research-SKILLs/tree/main/21-research-ideation/brainstorming-research-ideas
[r35]: https://github.com/anthropics/knowledge-work-plugins/tree/main/bio-research/skills/scientific-problem-selection
[r36]: https://github.com/danium/lateral-thinking
[r37]: https://github.com/mindfold-ai/Trellis/tree/main/.claude/skills/trellis-brainstorm
[r38]: https://github.com/Imbad0202/academic-research-skills
[r39]: https://github.com/wondelai/skills/tree/HEAD/design-sprint
[r40]: https://github.com/awslabs/aidlc-workflows/tree/HEAD/core/aidlc-common/stages/ideation
[r41]: https://github.com/gsd-build/get-shit-done/blob/HEAD/commands/gsd/explore.md
[r42]: https://github.com/fabriqaai/specs.md/tree/HEAD/src/flows/ideation
[r43]: https://github.com/tronghieu/agent-skills/tree/main/skills/brainstorm-coach
[r44]: https://github.com/andrehuang/research-companion
[r45]: https://github.com/haowjy/creative-writing-skills
[r46]: https://github.com/iamzifei/show-me-the-money
[r47]: https://github.com/AsiaOstrich/universal-dev-standards/tree/HEAD/locales/zh-CN/skills/brainstorm-assistant
[r48]: https://github.com/HangYu8123/HarnessFlow
[r49]: https://github.com/constructorfabric/studio/blob/HEAD/skills/studio/modules/brainstorm-panel.md
[r50]: https://github.com/mikeparcewski/wicked-garden/tree/HEAD/skills/jam
[r51]: https://github.com/LigphiDonk/Oh-my--paper
[r52]: https://github.com/zenstory-ai/oh-story-claudecode
[r53]: https://github.com/gaasher/Agent-Loop-Skills/tree/HEAD/loops/hypothesis-gen
[r54]: https://github.com/junshi-research/research-junshi
[r55]: https://github.com/massgen/MassGen
[r56]: https://github.com/Donchitos/Claude-Code-Game-Studios/tree/main/.claude/skills/brainstorm
[r57]: https://github.com/first-fluke/oh-my-agent/tree/HEAD/.agents/skills/oma-brainstorm
[r58]: https://github.com/sandeco/reversa/tree/HEAD/agents/reversa-brainstorm
[r59]: https://github.com/tw93/Waza/tree/main/skills/think
[r60]: https://github.com/EvoMap/AutoResearch
[r61]: https://github.com/fainshare/Liam-Skills/tree/HEAD/skills/osborn
[r62]: https://github.com/davila7/claude-code-templates/tree/HEAD/cli-tool/components/skills/productivity/think-tank
[r63]: https://github.com/EvoScientist/EvoSkills/tree/HEAD/skills/research-ideation
[r64]: https://github.com/RUC-NLPIR/Arbor/tree/HEAD/skills/arbor-agent-ideate
[r65]: https://github.com/K-Dense-AI/science-superpowers
[r66]: https://github.com/Fredasterehub/kiln
[r67]: https://github.com/BURIBURI-ZAEMON1/idea-thinking-skills
[r68]: https://github.com/vyralcontent/content-skills/tree/HEAD/skills/viral-short-form-ideas
[r69]: https://github.com/Intense-Visions/harness-engineering/blob/HEAD/.claude-plugin/commands/ideate-fleet.md
[r70]: https://github.com/nicknisi/ideation
[r71]: https://deepmind.google/blog/co-scientist-a-multi-agent-ai-partner-to-accelerate-research/
[r72]: https://github.com/smixs/creative-director-skill
[r73]: https://github.com/bmad-code-org/BMAD-METHOD/tree/HEAD/skills/bmad-party-mode
[r74]: https://github.com/Jeffallan/claude-skills/tree/main/skills/the-fool
[r75]: https://github.com/rampstackco/claude-skills/tree/HEAD/skills/brand-ideation
[r76]: https://github.com/QuantumBFS/sci-brain
[r77]: https://github.com/product-on-purpose/pm-skills
[r78]: https://github.com/openai/codex/blob/HEAD/codex-rs/collaboration-mode-templates/templates/plan.md
[r79]: https://github.com/yonatangross/orchestkit/tree/main/plugins/ork/skills/brainstorm
[r80]: https://github.com/zenstory-ai/drama-skills/tree/HEAD/skills/short-drama-develop
[r81]: https://github.com/Neeeophytee/finding-unknowns-skills
[r82]: https://github.com/ericrisco/rsc-harness/tree/HEAD/skills/shortform-ideation
[r83]: https://github.com/simota/agent-skills/tree/main/flux
[r84]: https://github.com/alexei-led/cc-thingz/tree/HEAD/dist/claude/discovery/skills/brainstorming-ideas
[r85]: https://github.com/InternScience/InternAgent
[r86]: https://github.com/hex/claude-council
[r87]: https://github.com/BuildGreatProducts/builder-os/tree/HEAD/skills/idea-generator
[r88]: https://github.com/nelsonwerd/idea-to-ship-skills
[r89]: https://github.com/bgauryy/octocode/tree/HEAD/skills/octocode-brainstorming
[r90]: https://github.com/HKUSTDial/Supervisor-Skills/tree/HEAD/skills/idea-evaluator
[r91]: https://github.com/uditgoenka/autoresearch/blob/HEAD/guide/autoresearch-reason.md
[r92]: https://github.com/maxritter/pilot-shell/blob/HEAD/pilot/skills/prd/steps/03-ideate.md
[r93]: https://github.com/acogood/diffmode_free
[r94]: https://github.com/mohamedameen-io/StartupKit
[r95]: https://github.com/SteelMorgan/1c-agent-based-dev-framework/tree/HEAD/framework/skills/framework-meta/brainstorm
[r96]: https://github.com/zenstory-ai/novel-to-game/tree/HEAD/skills/game-concept
[r97]: https://github.com/oprogramadorreal/optimus-claude/tree/HEAD/skills/brainstorm
[r98]: https://github.com/tkersey/dotfiles/tree/HEAD/codex/skills/creative-problem-solver
[r99]: https://github.com/WILLOSCAR/research-units-pipeline-skills
[r100]: https://github.com/aiming-lab/AutoResearchClaw
[r101]: https://github.com/Yakoub-ai/phaser4-gamedev/tree/HEAD/skills/phaser-brainstorm
[r102]: https://github.com/kucherenko/gangsta
[r103]: https://github.com/mhylle/claude-skills-collection/tree/HEAD/skills/deep-brainstorm
[r104]: https://github.com/AntTheLimey/gm-apprentice/blob/HEAD/skills/the-midwife/SKILL.md
[r105]: https://github.com/rohitgehe05/mindpowers
[r106]: https://github.com/SritejBommaraju/divergent-agents
[r107]: https://github.com/danielmiessler/LifeOS/tree/main/LifeOS/install/skills/Ideate
[r108]: https://github.com/bmad-code-org/bmad-module-creative-intelligence-suite
[r109]: https://github.com/anthropics/financial-services/tree/HEAD/plugins/vertical-plugins/equity-research/skills/idea-generation
[r110]: https://github.com/Galaxy-Dawn/claude-scholar/tree/HEAD/skills/research-ideation
[r111]: https://github.com/dontbesilent2025/dbskill/tree/HEAD/skills/dbs-chatroom
[r112]: https://github.com/skymanbp/cc-tree
[r113]: https://github.com/skyllwt/AutoSci
[r114]: https://github.com/microsoft/hve-core
[r115]: https://github.com/autopus-ai/autopus-adk/tree/HEAD/.omp/skills/auto-idea
[r116]: https://github.com/avelikiy/great_cto/tree/HEAD/skills/brainstorming
[r117]: https://github.com/pzqpzq/Principia
[r118]: https://github.com/superamped/ai-marketing-skills/tree/HEAD/skills/ads/ad-angles
[r119]: https://github.com/aparente/claude-skills/tree/master/skills/d-school
[r120]: https://github.com/Yuzzyuk/marketing-os
[r121]: https://github.com/joshzyj/open-scholar-skill
[r122]: https://github.com/worksystems-design/libertee
[r123]: https://github.com/Orchestra-Research/AI-Research-SKILLs/tree/main/21-research-ideation/creative-thinking-for-research
[r124]: https://github.com/Q00/ouroboros/tree/main/skills/unstuck
[r125]: https://github.com/softaworks/agent-toolkit/tree/HEAD/skills/game-changing-features
[r126]: https://github.com/OpenNSWM-Lab/FAROS
[r127]: https://github.com/tjboudreaux/cc-thinking-skills
[r128]: https://github.com/bmad-code-org/BMAD-METHOD/tree/main/skills/bmad-advanced-elicitation
[r129]: https://github.com/evanklem/evanflow/tree/HEAD/skills/evanflow-brainstorming
[r130]: https://github.com/github/awesome-copilot/blob/main/skills/ai-team-orchestration/SKILL.md
[r131]: https://github.com/athola/claude-night-market/tree/HEAD/plugins/tome/skills/triz
[r132]: https://github.com/oborchers/fractional-cto/tree/HEAD/structured-brainstorming
[r133]: https://github.com/arnabbagxd/Brand-building-skills/tree/HEAD/skills/brand-naming
[r134]: https://github.com/v0lka/skills/tree/main/research/scamper
[r135]: https://github.com/danielrosehill/Claude-Ideation-Planning-Plugin
[r136]: https://github.com/google-gemini/gemini-cli/blob/HEAD/docs/cli/plan-mode.md
[r137]: https://cursor.com/docs/agent/planning
[r138]: https://code.visualstudio.com/docs/agents/run/planning
[r139]: https://developers.miro.com/docs/miro-mcp
[r140]: https://github.com/affaan-m/ECC/tree/main/skills/council
[r141]: https://github.com/nyldn/claude-octopus
[r142]: https://github.com/ai-driven-dev/framework/tree/HEAD/plugins/aidd-refine/skills/01-brainstorm
[r143]: https://github.com/rshankras/claude-code-apple-skills/tree/HEAD/skills/product/idea-generator
[r144]: https://github.com/oaustegard/claude-skills/tree/HEAD/generative-thinking
[r145]: https://github.com/robertguss/claude-code-toolkit/tree/HEAD/skills/brainstorm
[r146]: https://github.com/jongwony/epistemic-protocols/tree/HEAD/heuresis/skills/ideate
[r147]: https://github.com/jmagly/aiwg/tree/HEAD/agentic/code/plugins/verbalized-sampling
[r148]: https://github.com/jtydhr88/screenwriting-skills
[r149]: https://github.com/agent-sh/debate
[r150]: https://github.com/Rune-kit/rune/tree/HEAD/skills/brainstorm
[r151]: https://github.com/Yuki001/game-dev-skills/tree/HEAD/gat
[r152]: https://github.com/ww-w-ai/bkit-claude-code/blob/HEAD/skills/plan-plus/SKILL.md
[r153]: https://github.com/Stage-11-Agentics/c11/tree/HEAD/skills/sounding
[r154]: https://github.com/thinkbigleaders/claude-innovation-skills
[r155]: https://github.com/LocalSymmetry/lofn
[r156]: https://github.com/lokicik/novel-idea-hunter
[r157]: https://github.com/1marcelserrano/open-collider/tree/main/skills/open-collider
[r158]: https://github.com/jikig-ai/soleur/tree/HEAD/plugins/soleur/skills/brainstorm
[r159]: https://github.com/deanpeters/MITRE-ITK-Skills
[r160]: https://github.com/jesgarram/arete
[r161]: https://github.com/ludi-uni/idea-generator-skill
[r162]: https://github.com/NeoLabHQ/context-engineering-kit/tree/HEAD/plugins/sadd/skills/tree-of-thoughts
[r163]: https://code.claude.com/docs/en/agent-teams
[r164]: https://docs.edisonscientific.com/agents
[r165]: https://github.com/openai/plugins/tree/HEAD/plugins/product-design/skills/ideate
[r166]: https://github.com/sickn33/agentic-awesome-skills/tree/HEAD/skills/multi-agent-brainstorming
[r167]: https://github.com/mohitagw15856/pm-claude-skills/blob/main/skills/brainstorming/SKILL.md
[r168]: https://github.com/SakanaAI/AI-Scientist
[r169]: https://github.com/OpenRaiser/NanoResearch
[r170]: https://github.com/jwynia/agent-skills/tree/HEAD/skills/general/ideation/brainstorming
[r171]: https://github.com/SpaceZephyr/pm-skills
[r172]: https://github.com/VeryGoodOpenSource/vgv-wingspan/tree/HEAD/skills/brainstorm
[r173]: https://github.com/giordanorec/multiagents-decanting
[r174]: https://github.com/Light0305/Light-skills
[r175]: https://github.com/UditAkhourii/neuroarxiv
[r176]: https://github.com/google-labs-code/stitch-skills/tree/HEAD/plugins/stitch-design/skills/generate-design
[r177]: https://github.com/Future-House/robin
[r178]: https://github.com/yagizdo/quiver/tree/HEAD/skills/brainstorm
[r179]: https://mobbin.com/mcp
[r180]: https://github.com/coreyhaines31/makerskills/tree/main/skills/unstuck
[r181]: https://github.com/lyndonkl/claude/tree/main/skills/brainstorm-diverge-converge
[r182]: https://github.com/cursor/plugins/tree/HEAD/pstack
[r183]: https://github.com/borghei/Claude-Skills/tree/HEAD/project-management/discovery/brainstorm-ideas
[r184]: https://github.com/a5c-ai/babysitter/tree/HEAD/library/specializations/domains/science/scientific-discovery/agents/innovation-facilitator
[r185]: https://docs.claudekit.cc/docs/engineer/skills/brainstorm/
[r186]: https://github.com/glacierphonk/naming
[r187]: https://github.com/NateBJones-Projects/OB1/tree/HEAD/skills/panning-for-gold
[r188]: https://github.com/athola/claude-night-market/tree/master/plugins/attune/skills/project-brainstorming
[r189]: https://github.com/tradermonty/claude-trading-skills/tree/main/skills/trade-hypothesis-ideator
[r190]: https://github.com/modu-ai/moai-adk/tree/main/.claude/skills/moai-foundation-thinking
[r191]: https://github.com/superdesigndev/superdesign-skill
[r192]: https://github.com/vtemian/micode
[r193]: https://github.com/ThomasHoussin/Claude-Book/tree/HEAD/.claude/skills/story-ideator
[r194]: https://github.com/hyperb1iss/hyperskills/tree/HEAD/skills/brainstorm
[r195]: https://github.com/appleweiping/WEIPING_LAB
[r196]: https://github.com/jamiemill/layers-skills
[r197]: https://github.com/fabianboth/ralph-ideate
[r198]: https://github.com/ChristopherKahler/seed
[r199]: https://github.com/deanpeters/Product-Manager-Skills/tree/main/skills/opportunity-solution-tree
[r200]: https://github.com/NoviScl/AI-Researcher
[r201]: https://github.com/m0n0x41d/haft
[r202]: https://github.com/NousResearch/hermes-agent/tree/main/optional-skills/creative/creative-ideation
[r203]: https://github.com/am-will/codex-skills/tree/main/skills/llm-council
[r204]: https://github.com/aitytech/agentkits-marketing/blob/HEAD/agents/brainstormer.md
[r205]: https://github.com/Jamie-BitFlight/claude_skills/tree/HEAD/plugins/brainstorming-skill
[r206]: https://github.com/ara-mkr/Wonder-Pill
[r207]: https://github.com/boshu2/agentops
[r208]: https://github.com/meleantonio/awesome-econ-ai-stuff/blob/HEAD/_skills/ideation/research-ideation/SKILL.md
[r209]: https://github.com/tody-agent/codymaster/tree/HEAD/skills/cm-brainstorm-idea
[r210]: https://github.com/bradautomates/content-ideas
[r211]: https://github.com/myrtlepn/gran-maestro/tree/HEAD/skills/ideation
[r212]: https://github.com/fagemx/gstack-game/tree/HEAD/skills/game-ideation
[r213]: https://github.com/Robert-Adunka/triz-skills
[r214]: https://github.com/radimsem/forge-skills/tree/HEAD/skills/blueprint
[r215]: https://github.com/AlterLab-IEU/AlterLab_GameForge/tree/HEAD/skills/workflows/game-brainstorm
[r216]: https://github.com/allenai/codescientist
[r217]: https://github.com/infranodus/mcp-server-infranodus
[r218]: https://github.com/SuperClaude-Org/SuperClaude_Framework/blob/HEAD/src/superclaude/commands/brainstorm.md
[r219]: https://github.com/aj-geddes/claude-code-bmad-skills/tree/HEAD/bmad-planning-orchestrator/skills/bmad-brainstorm
[r220]: https://github.com/RefoundAI/lenny-skills
[r221]: https://github.com/gupsammy/Claudest/tree/HEAD/plugins/claude-thinking/skills/brainstorm
[r222]: https://github.com/swan-gtm/gtm-skills/tree/HEAD/skills/daniel-bustamante/52-newsletter-ideas
[r223]: https://github.com/karaage0703/ai-assistant-workspace/tree/HEAD/skills/xs-bridge-ideas
[r224]: https://github.com/nesquikm/mcp-rubber-duck
[r225]: https://github.com/SummerEngine/summer/tree/HEAD/library/skills/brainstorm-game
[r226]: https://github.com/crawfordxx/xiaoma-durex-copywriter
[r227]: https://github.com/isjiamu/jiamu-skills/tree/main/six-thinking-hats
[r228]: https://github.com/Lykhoyda/ask-llm
[r229]: https://github.com/Punktheory/research-idea-and-battle
[r230]: https://github.com/Kaimen-Inc/Co-Scientist
[r231]: https://github.com/cris-achiardi/claude-skills/tree/HEAD/skills/crazy-8s
[r232]: https://github.com/shenhao-stu/openclaw-agents
[r233]: https://github.com/BrianRWagner/ai-marketing-claude-code-skills
[r234]: https://github.com/Halomix/out-the-box-thinking
[r235]: https://github.com/AgriciDaniel/claude-youtube
[r236]: https://github.com/lingzhi227/agent-research-skills/tree/HEAD/skills/idea-generation
[r237]: https://github.com/wshobson/agents/tree/HEAD/plugins/agent-teams
[r238]: https://edisonscientific.com/news/announcing-kosmos
[r239]: https://github.com/spranab/brainstorm-mcp
[r240]: https://github.com/danielmiessler/Fabric
[r241]: https://github.com/codeaholicguy/ai-devkit/tree/HEAD/skills/brainstorm
[r242]: https://github.com/dyad-sh/dyad/tree/HEAD/.claude/skills/swarm-to-plan
[r243]: https://github.com/gnurio/nurijanian-skills/tree/HEAD/skills/verbalized-sampling
[r244]: https://github.com/microsoft/TinyTroupe
[r245]: https://github.com/openai/plugins/tree/HEAD/plugins/creative-production
[r246]: https://github.com/ogiberstein/lateral-thinking-skill
[r247]: https://github.com/VoltAgent/awesome-claude-code-subagents/blob/HEAD/categories/10-research-analysis/first-principles-thinking.md
[r248]: https://github.com/hellowind777/helloagents/tree/HEAD/skills/commands/prd
[r249]: https://github.com/croffasia/cc-blueprint-toolkit/blob/HEAD/claude/commands/brainstorm.md
[r250]: https://github.com/onevcat/argue
[r251]: https://github.com/panaversity/agentfactory-business-plugins/tree/HEAD/innovation
[r252]: https://github.com/pproenca/dot-skills/tree/HEAD/skills/.curated/think
[r253]: https://github.com/yogirk/agent-council
[r254]: https://github.com/catlog22/Claude-Code-Workflow/tree/main/.claude/skills/team-brainstorm
[r255]: https://github.com/DanMcInerney/orchflows/tree/HEAD/example-workflows/design-loop
[r256]: https://github.com/human-avatar/skills-for-humanity/tree/HEAD/skills/s4h-creativity-brainstorm
[r257]: https://github.com/SakanaAI/AI-Scientist-v2/blob/HEAD/ai_scientist/perform_ideation_temp_free.py
[r258]: https://github.com/tsingyuai/scientify/tree/HEAD/skills/idea-generation
[r259]: https://github.com/danielmiessler/LifeOS/tree/main/LifeOS/install/skills/Council
[r260]: https://github.com/phuryn/pm-brain/blob/HEAD/example-brain/.claude/commands/ideate.md
[r261]: https://github.com/CHATS-lab/verbalized-sampling
[r262]: https://github.com/antonbabenko/deliberation
[r263]: https://github.com/patsnap/mcp
[r264]: https://github.com/digital-stoic-org/agent-skills/tree/main/cognitive/skills/brainstorm
[r265]: https://github.com/mattgierhart/PRD-driven-context-engineering/tree/HEAD/plugins/prd-ce/skills/prd-v10-continuous-discovery-torres
[r266]: https://developer.godaddy.com/mcp
[r267]: https://github.com/AstroPilot-AI/Denario
[r268]: https://github.com/danielmiessler/LifeOS/tree/HEAD/LifeOS/install/skills/BeCreative
[r269]: https://github.com/VoltAgent/awesome-claude-code-subagents/blob/HEAD/categories/10-research-analysis/project-idea-validator.md
[r270]: https://github.com/heyitsnoah/claudesidian/tree/HEAD/.agents/skills/thinking-partner
[r271]: https://github.com/TUAN130294/awf/blob/HEAD/workflows/brainstorm.md
[r272]: https://github.com/kitze/council
[r273]: https://github.com/tony/claude-code-riper-5
[r274]: https://github.com/av/skills/tree/HEAD/ideate
[r275]: https://github.com/mattnowdev/thinking-partner
[r276]: https://github.com/disler/fusion-harness
[r277]: https://github.com/JetBrains/thinkrail/tree/HEAD/packages/pi-thinkrail-workflow/skills/brainstorming
[r278]: https://github.com/vtemian/octto
[r279]: https://github.com/code-yeongyu/oh-my-openagent/tree/HEAD/.agents/skills/hyperplan
[r280]: https://github.com/slavingia/skills
[r281]: https://github.com/EveryInc/compound-knowledge-plugin
[r282]: https://github.com/vanzan01/cursor-memory-bank
[r283]: https://github.com/ethanplusai/jarvis
[r284]: https://github.com/zvadaadam/az-skills/tree/HEAD/skills/marketing/brand-name-explore
[r285]: https://github.com/chendongqi/OPB-Skills/tree/HEAD/skills/product-ideation-pm
[r286]: https://github.com/bladnman/ideation_team_skill
[r287]: https://github.com/LKbaba/Grok-mcp
[r288]: https://github.com/dsifry/metaswarm
[r289]: https://github.com/AshExplained/roblox-skills/tree/HEAD/roblox-game-ideas
[r290]: https://github.com/omnigent-ai/omnigent/tree/HEAD/examples/debby
[r291]: https://github.com/github/awesome-copilot/blob/main/agents/devils-advocate.agent.md
[r292]: https://github.com/breaking-brake/cc-wf-studio/tree/HEAD/.claude/skills/next-idea
[r293]: https://github.com/athola/claude-night-market/tree/HEAD/plugins/tome/skills/ideate
[r294]: https://github.com/HKUDS/AI-Researcher
[r295]: https://github.com/vudovn/ag-kit
[r296]: https://github.com/sd0xdev/sd0x-harness/tree/main/skills/codex-brainstorm
[r297]: https://github.com/AndyMik90/Aperant
[r298]: https://github.com/Stanestane/game-design-skills-bundle/tree/HEAD/game-design-brainstorm-methods
[r299]: https://github.com/24kchengYe/human-skill-tree/tree/HEAD/skills/06-creativity-innovation
[r300]: https://github.com/SpectrAI-Initiative/InnoClaw/blob/HEAD/.claude/skills/research-ideation-full/SKILL.md
[r301]: https://github.com/uddhav/creative-thinking
[r302]: https://github.com/tonbistudio/shrimp-brainstorming
[r303]: https://github.com/Narcooo/inkos
[r304]: https://github.com/zou-group/virtual-lab
[r305]: https://github.com/tommyjepsen/awesome-ux-skills
[r306]: https://github.com/fynnfluegge/agtx/tree/HEAD/skills/brainstorm
[r307]: https://github.com/Chorus-AIDLC/Chorus/tree/HEAD/plugins/chorus/skills/brainstorm
[r308]: https://github.com/jamubc/gemini-mcp-tool
[r309]: https://github.com/glittercowboy/taches-cc-resources/tree/HEAD/commands/consider
[r310]: https://github.com/jtydhr88/ComfyTV/tree/HEAD/skills/brainstorm
[r311]: https://github.com/nmrtn/nanopm/tree/HEAD/pm-brainstorm
[r312]: https://github.com/neej4/ScholarScout
[r313]: https://github.com/Aedelon/claude-code-blueprint/tree/HEAD/skills/brainstorm
[r314]: https://github.com/steveaimkt/proposal-agent-github/tree/HEAD/.claude/skills/brainstorm
[r315]: https://github.com/cyperx84/claude-skills-mental-models
[r316]: https://github.com/LilMGenius/paperthin/tree/HEAD/skills/depth/macrothink
[r317]: https://github.com/Dicklesworthstone/jeffreysprompts.com/blob/main/idea-wizard-SKILL.md
[r318]: https://github.com/github/awesome-copilot/blob/main/skills/napkin/SKILL.md
[r319]: https://github.com/nagisanzenin/production-grade/blob/HEAD/skills/polymath/modes/ideate.md
[r320]: https://github.com/proffesor-for-testing/agentic-qe/tree/HEAD/.claude/skills/six-thinking-hats
[r321]: https://github.com/Ishan7390/10skills-video
[r322]: https://github.com/swaroop2004/Proven-Viral-Content-System
[r323]: https://github.com/BeehiveInnovations/pal-mcp-server
[r324]: https://github.com/NousResearch/hermes-agent/tree/HEAD/skills/creative/songwriting-and-ai-music
[r325]: https://github.com/EveryInc/compound-writing/tree/HEAD/skills/cw-brainstorm
[r326]: https://github.com/dusk-futile/idea-universe
[r327]: https://github.com/iandanforth/force-associations
[r328]: https://github.com/10Legs/freelance-developer-harness/blob/HEAD/.claude/commands/ideate.md
[r329]: https://github.com/ulab-uiuc/research-town
[r330]: https://github.com/sodam-ai/SoDam-Persona-Codex/tree/HEAD/plugins/sodam-persona/skills/persona-ideation-strategist
[r331]: https://github.com/DV0x/creative-ad-agent
[r332]: https://github.com/ComposioHQ/awesome-claude-skills/tree/master/domain-name-brainstormer
[r333]: https://github.com/sickn33/agentic-awesome-skills/tree/main/skills/idea-evaluator
[r334]: https://github.com/neurofoo/agent-skills/tree/HEAD/sixhats
[r335]: https://github.com/pjt222/agent-almanac/tree/HEAD/skills/brahma-bhaga
[r336]: https://github.com/z2z23n0/idea-miner
[r337]: https://github.com/VerticalResearchGroup/Gauntlet
[r338]: https://usesideways.com
[r339]: https://github.com/DeepMyst/Mysti
[r340]: https://github.com/mnemox-ai/idea-reality-mcp
[r341]: https://github.com/dair-ai/dair-academy-plugins/tree/main/plugins/llm-council
[r342]: https://github.com/neurofoo/agent-skills/tree/HEAD/scamper
[r343]: https://github.com/RLabs-Inc/gemini-mcp
[r344]: https://github.com/appleweiping/WEIPING_COUNCIL
[r345]: https://github.com/johnlindquist/claude
[r346]: https://github.com/Riley-Coyote/polyclaude
[r347]: https://github.com/MadeByTokens/claude-brainstorm
[r348]: https://github.com/MadAppGang/claude-code/tree/HEAD/plugins/dev/skills/planning/brainstorming
[r349]: https://github.com/duthaho/claudekit
[r350]: https://github.com/fredalxin/dsh-solo-thinking
[r351]: https://github.com/The-Swarm-Corporation/AI-CoScientist
[r352]: https://github.com/agentic-box/owlex
[r353]: https://github.com/AlteredCraft/claude-code-plugins/tree/HEAD/plugins/ideation
[r354]: https://github.com/DAMO-NLP-SG/CoI-Agent
[r355]: https://github.com/github/awesome-copilot/blob/HEAD/agents/simple-app-idea-generator.agent.md
[r356]: https://github.com/nibzard/awesome-agentic-patterns/blob/main/patterns/iterative-multi-agent-brainstorming.md
[r357]: https://github.com/microclaw/microclaw/tree/HEAD/crates/microclaw-engine/skills/built-in/brainstorming
[r358]: https://github.com/atrislabs/atris/tree/HEAD/atris/team/brainstormer
[r359]: https://github.com/contains-studio/agents/blob/HEAD/product/trend-researcher.md
[r360]: https://github.com/DmitryBMsk/llm-council-plus
[r361]: https://github.com/kexinquan/multicolleagues-brainstorm
[r362]: https://github.com/creatify-ai/static-ad-concept-generator
[r363]: https://github.com/anthonylee991/gemini-superpowers-antigravity/tree/main/.agent/skills/superpowers-brainstorm
[r364]: https://github.com/yanglongyun/ramify-dsh
[r365]: https://github.com/nth5693/gemini-kit
[r366]: https://github.com/KorroAi/drunk-claude
[r367]: https://github.com/OneWave-AI/claude-skills/tree/main/debate-simulator
[r368]: https://github.com/team-attention/agent-council
[r369]: https://github.com/zhu-minjun/Researcher
[r370]: https://github.com/lamm-mit/SciAgentsDiscovery
[r371]: https://github.com/karpathy/llm-council
[r372]: https://github.com/bmad-code-org/BMAD-METHOD/tree/V4/expansion-packs/bmad-creative-writing
[r373]: https://github.com/glittercowboy/plugin-freedom-system/tree/HEAD/.claude/skills/plugin-ideation
[r374]: https://github.com/khgs2411/flow/tree/HEAD/framework/commands
[r375]: https://github.com/ruvnet/Bot-Generator-Bot/tree/HEAD/skills/bgb-brainstorming-idea-bot
[r376]: https://github.com/SnakeO/claude-co-commands
[r377]: https://github.com/obra/superpowers-skills/tree/main/skills/problem-solving
[r378]: https://github.com/gcpdev/llm-council-skill
[r379]: https://github.com/realkimbarrett/advertising-skills/tree/main/skills/operator-os/ad-angle-multiplier
[r380]: https://github.com/RhysSullivan/skills/tree/HEAD/skills/how-to-earn-a-billion-dollars
[r381]: https://github.com/NickCrew/Claude-Cortex/tree/main/skills/collaboration/idea_lab
[r382]: https://github.com/samirpatil2000/skills/tree/HEAD/jamming
[r383]: https://github.com/Azzedde/brainstormers
[r384]: https://github.com/alrightryanx/ralph-brainstormer
[r385]: https://github.com/OpenClaw-OPCC/brainstorming-dev
[r386]: https://github.com/ricneves-ai/flowgrammers-skills/tree/HEAD/direcao-criativa/ideacao
[r387]: https://github.com/jtgsystems/Custom-Modes-Roo-Code/tree/HEAD/custom_modes.d/cognitive-multi-thinker
[r388]: https://github.com/SuperClaude-Org/SuperGemini_Framework
[r389]: https://github.com/NickScherbakov/Heinrich-The-Inventing-Machine
[r390]: https://github.com/ruvnet/ruflo/blob/HEAD/.claude/commands/sparc/innovator.md
[r391]: https://github.com/RooCodeInc/Roo-Code/issues/9061
[r392]: https://github.com/jakedahn/oblique-skill
[r393]: https://dreamtap.xyz
