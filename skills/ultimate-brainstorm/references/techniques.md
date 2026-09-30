# Technique cards

Each card: what it does, where it runs in the pipeline, a ready-to-use snippet, and, for most cards, an evidence or
source note (cards 3, 9, 10, 11 and 24 are design rationale or heuristics). Full prompt texts are in templates/prompts/ (one file per prompt). Evidence labels follow the research summary this skill was built from; "(likely)" marks
preprints or items checked only through summaries.

---

## 1. Sealed solo seeding (brainwriting, nominal group)
- Stage 1. The human writes ideas alone, in writing, before any AI idea is visible. Teams write separately, then pool.
- Snippet: P-SEEDS.
- Evidence: nominal groups beat talking groups in 18 of 22 experiments (Diehl and Stroebe 1987); productivity loss vs.
  nominal groups was smaller when group members wrote their ideas rather than speaking them (Mullen et al. 1991);
  alone-then-together gave more and better ideas and better selection (Girotra, Terwiesch, Ulrich 2010);
  LLM-first reduced original ideas (Qin et al., CHI 2025); AI examples caused fixation (Wadinambiarachchi et al., CHI 2024).

## 2. Question-only frontier interview
- Stage 2. Ask every question whose prerequisites are settled as one numbered round; defaults only for constraints; facts
  are looked up, decisions are asked. Mechanism from mattpocock grilling. In a repo (software, growth), add the domain
  moves from mattpocock domain-modeling: challenge terms against the glossary, pin one canonical term per concept, test
  relationships with edge cases, quote the code where a claim contradicts it; stage resolved terms in the run folder.
  Generators get at most 12 relevant terms labeled as today's system, which they may break (GEN-HEADER rule 8), so the
  glossary sharpens the frame without fixing the solution space.
- Snippet: P-GRILL, P-GRILL-DOCS (software, growth) or P-FRAME (step 1b holds the domain moves).
- Evidence: the AI asking and suggesting (not rewriting) preserved diversity and ownership (Maier et al., CHI 2026). We
  did not find a study that directly measures the effect of a framing or clarifying interview on brainstorming outcomes
  (Maier et al. on question-based, human-led modes is the closest), so the interview is capped at 3 rounds.

## 3. Anchor-stripped job statement plus How-Might-We
- Stage 2. "When <situation>, <who> wants to <progress>, so they can <outcome>." Name no existing tool or implementation.
  Then "How might we <action> for <whom> so that <outcome>?"
- Why: every generator sees the same brief; an anchor in the brief leaks into every branch. Idea from ADHD's optional
  anchor-stripping reframe, which exists only in its main-branch CLI/library (not npm 0.1.4 and not its SKILL.md skill);
  every ADHD divergent branch also bans the first ~3 obvious answers.

## 4. Verbalized Sampling (VS)
- Stage 4 (S2-VS, LENS), quick mode. Ask for k responses, each with a text and a numeric probability; then sample the tails.
- Snippet (README wording): "Generate 5 responses to the user query, each within a separate <response> tag. Each
  <response> must include a <text> and a numeric <probability>. Please sample at random from the tails of the
  distribution, such that the probability of each response is less than 0.10."
- Ladder: full distribution -> < 0.10 -> < 0.10 with new mechanisms -> < 0.01. VS-Multi continues the same
  conversation with a follow-up such as "Tell 5 more with probabilities" (paper Table 1) or "Generate N alternative
  responses to the original input prompt" (paper appendix).
- Evidence: 1.6-2.1x diversity over direct prompting in creative writing, human-rated diversity +25.7%, lower probability
  thresholds = more diversity (Zhang et al. 2025; the threshold results report diversity only). Treat the probabilities
  as rough, uncalibrated relative signals: they often keep rank order but are not reliable absolute likelihoods, so
  never decide on the exact numbers. Do not use the Python package's `tau` floor filter: it removes tail ideas.

## 5. Enumerate -> diversify -> elaborate
- Stage 4 (S3-EDE, LENS). 40 titles -> rewrite them bolder and more different (no shared mechanism) -> describe only the
  rewritten ones. Show both lists and count the changed titles so a skipped step is visible.
- Evidence: this chain brought GPT-4 idea pools close to human-pool diversity; the step was skipped in about 15% of runs;
  its diversity advantage over the base prompt disappears after about 750-800 ideas as the pool depletes; pools from
  different strategies overlap little (Meincke, Mollick, Terwiesch 2024).

## 6. Lens rotation (not persona rotation) for generators
- Stage 4. Give each isolated generator a different lens: pain/friction, leverage/compounding, automation/removal,
  inversion, remote analogy, constraint flip, assumption removal, audience shift, subtraction.
- Personas: modest effect for generation (Meincke 2024); multi-persona self-collaboration helps only strong models
  (SPP, NAACL 2024). Use personas and diverse critics for critique instead (Ueda et al., SIGDIAL 2025: diverse critics
  raised feasibility).
- Keep generators isolated: dense communication and dominant lead agents collapse diversity (Chen et al. 2026); share
  critiques, not drafts (LLM Review 2026, likely).

## 7. Provocation operators
- Stage 4 (S5-OPS). Inversion, subtraction, constraint flip ($0/1 day vs unlimited/10 years), assumption reversal, worst
  idea then invert. Always include one "opposite" and one "remove something" idea.
- Evidence: defixation prompting raises originality (IDEAFix 2026, likely); Girotra et al. (2023) recommend putting
  novelty in the prompt when it is the goal (a recommendation, not a tested result).

## 8. Cross-domain mechanism transfer (planned retrieval)
- Stage 4 (S4-TRANSFER), REOPEN. Reduce the problem to a 2-sentence mechanism skeleton; search 6 distant fields for the same
  skeleton; map each link as ESTABLISHED or INFERRED; name what does not port (scale, incentives, rates, distributions);
  say why it is not already known; give a falsifier. Drop metaphor-only mappings.
- Evidence: planned retrieval gave 3.4x more unique novel ideas (Nova 2024); comparing with prior work raises novelty
  (SciMON, ACL 2024). Adapted from the lateral-thinking skill (ogiberstein original; abpai adaptation): mechanism
  skeleton, distant-field raids, mechanism chain, adversarial pass (SURVIVES / DOWNRANKED / KILLED). The
  ESTABLISHED/INFERRED labels formalize the original's "which links are established vs. inferred"; "what does not
  port" adapts its math-portability check; the falsifier follows the abpai version.

## 9. TRIZ contradiction and separation
- Stage 4 (software variant operator f). "We need X to be A for B1 but not-A for B2" -> separate A and not-A in time,
  space, condition or scale; reuse existing resources first.
- Snippet: "State the contradiction as 'We need <parameter> to be <state 1> for <benefit 1> BUT <state 2> for
  <benefit 2>'. Try separation in time, space, condition and scale, in that order, before any other move."

## 10. SCAMPER
- Stage 8 only (it needs a base idea). Substitute, Combine, Adapt, Modify, Put to other use, Eliminate, Reverse.
- Snippet: "Apply each SCAMPER move once to <idea>; keep only variants whose mechanism differs from the original."

## 11. Morphological grid and cell targeting
- Stage 2 axes, Stage 5 COVERAGE and GAP rounds. Map every idea to one cell of 3 axes; generate only into empty cells;
  "do not reinterpret the cell; output TENSION: <why> if it is incoherent".
- Stop rule: a round with >= 40% duplicates is saturated; switch strategy or stop (heuristic).
- Source: claude-brainstorm-multiagent's MAP-Elites grid, which feeds under-filled cells as hints to its divergent
  agents and has a `tension_note` escape for semantically inconsistent cells; our TENSION line adapts it.

## 12. Research lens quota
- Research variant, replaces S5. 5 tensions or trade-offs, 3 recent shifts ("what changed": compute, data, regulation,
  used to revisit old negative results), 2 failure/boundary probes on popular methods, 1 idea imported from an adjacent
  field, 1 compose/decompose, then up/down/sideways abstraction variants of each candidate (target 10-20 candidates).
  Source: Phase 1 (Diverge) of Orchestra AI-Research-SKILLs' brainstorming-research-ideas skill ("research lens quota"
  is our label; the other ideation skill, creative-thinking-for-research, has no such counts).

## 13. Metaphor territories (naming)
- Naming variant. Reduce to "This product <does what> for <whom>"; ask what does this job in the physical world, in nature,
  as a tool, as a role, as the dramatic version, as the quiet version; map 2-3 territories; generate inside them.
  Source: glacierphonk naming.

## 14. Mechanism-key dedup and yield
- Stage 5. Key = "<actor> | <verb + object> | <outcome>". Merge only exact key matches; same mechanism for another actor
  is a sibling. Track unique share and "only here" per strategy. Near-duplicates are merged by the curator's mechanism
  keys only (there is no embedding pass).
- Evidence: only about 5% of 4,000 LLM ideas were unique even with "avoid repeats" in the prompt (Si et al. 2024). The
  counting is done by `bs.py map`, not by the LLM curator.

## 15. Anti-slop five-test diagnostic
- Stage 5 BASELINE marks and Stage 6 screen. Five tests: (1) could the idea have been generated for a different prompt
  by changing a noun? (2) does it name no actual people, places, materials, mechanisms or works? (3) is nothing in it
  surprising or in need of explanation? (4) can you not describe how using, reading or experiencing it would feel in
  concrete sensory terms? (5) would a sharp peer in the domain be embarrassed to pitch it? An idea must pass all five;
  failing two or more means rewriting it. Source: Hermes creative-ideation references/anti-slop.md (separate from its
  10-item self-check, where failing three or more means regenerate).

## 16. Absolute rubric with gates, floor and sensitivity
- Stage 6. Criteria and anchors fixed before any idea; noncompensatory gates (constraints, legal, ethics, safety); floor
  (any criterion mean <= 1.5 kills); weighted score; rank ranges under +/-25% weight changes; quotas per cluster plus a
  tail slot and a human slot.
- Evidence: absolute scores flip on distractors about 9% of the time vs 35% for pairwise (Tripathi et al. 2025), so screen
  with absolute scores first. Floor idea from idea-validation-agents; gates and sensitivity from K-Dense.

## 17. Prior-art verdict ladder
- Stage 7. CROWDED (>= 2 named matches, same actor and mechanism) / ADJACENT / NOT LOCATED within a dated search boundary.
  Never "novel"; proximity is information, not a veto.
- Evidence: LLM judges see novelty experts reject (Sinhahajari et al. 2026). Verdict limits from ARIS novelty-check.

## 18. Pairwise tournament, both orders, two families
- Stage 9. Normalized 90-110 word cards; every pair judged in both orders by two model families; a family's point counts
  only if its verdict survives the order swap; contested pairs go to the human; audits for position consistency and
  self-preference.
- Evidence: uncertainty-guided pairwise ranking beats direct scoring (PairS 2024); in Si et al. (2024) LLMs were poorly
  calibrated at direct score prediction but reached non-trivial accuracy pairwise, and the best LLM evaluator (a
  Claude-3.5 pairwise ranker) agreed with experts 53.3% of the time vs 56.1% between human experts (others 43.3-51.7%;
  pairwise did not beat direct scoring for every model); order swaps let Vicuna-13B beat ChatGPT on 66 of 80 queries
  with ChatGPT as judge (Wang et al. 2023); judges prefer their own outputs (Panickssery et al. 2024).

## 19. Opposed-stance council
- Stage 10. ADVOCATE and CRITIC from different families; "the stance changes how you present, not whether you acknowledge
  the truth" (PAL consensus guardrails); at most one rebuttal round; synthesis keeps the strongest disagreement (our
  rule; claude-council's debate mode adds "strongest criticisms" and "unresolved tensions") and, following claude-council's
  synthesis rules, reports only divergence that changes the decision and treats unanimity as a caution by naming the
  assumption the whole answer rests on that no reviewer could test.
- Evidence: debate helps reasoning and factuality, not creativity (Du et al. 2023); self-reflection degenerates, opposed
  debaters help with capped rounds (Liang et al.); debate does not reliably beat ensembles (Smit et al.), so it is used
  only to converge.

## 20. Steelman then attack
- Stages 7 and 10. Steelman in 2 sentences, then "Fails if ___" (falsifiable) with likelihood, impact, cheapest test and
  kill criterion; "never invent a weakness". Source: adapted from pm-skills strategy-red-team, which steelmans each
  load-bearing claim, ranks failure modes by impact x likelihood x cheapness to test (ranking factors, not per-item
  fields) and writes Claim / Fails if / Evidence to get this week / Kill criterion / Cheapest test for the top 3-5; its
  text says "Never invent a weakness the plan doesn't have."

## 21. Pre-mortem and inversion
- Stage 10 synthesis. "It is 6 months later and this failed because..." 3 causes, each with an early warning sign.
  Source: the imagine-it-failed pre-mortem (generally credited to Gary Klein, HBR 2007; none of the repos below cite
  him). pm-skills' /pre-mortem sorts risks into Tigers, Paper Tigers and Elephants; K-Dense's scientific-brainstorming
  has a "premortem and alternatives" step (assume the favoured idea gave an uninterpretable or harmful result, and name
  at least two mechanisms that predict the same apparent success); idea-validation-agents also uses a pre-mortem.

## 22. Riskiest-assumption test and XYZ pretotype
- Stage 11. Riskiest = highest criticality x uncertainty; a behaviour test within 2 weeks and a minimal budget; pass
  threshold written before running; kill criterion = inverse threshold. Product form: "At least X% of Y will do Z by <date>".
- Evidence: LLM ideas lost more of their score than expert ideas once executed (Si, Hashimoto, Yang 2025).

## 23. Evolve without replacing
- Stage 8. Two hybrids from different clusters, one simplification, one repair around the top kill-assumption, (deep) one
  different mechanism for the same outcome. Evolved ideas compete; originals stay.
- Evidence: the co-scientist generate-debate-evolve design; AI is good at incremental recombination (Lee and Chung 2024);
  building on others' ideas did not help human groups (Girotra 2010), so evolved ideas must win on merit.

## 24. Decision record with a ledger
- Stages 10-12. Chosen, runner-up, parked (revisit trigger), killed (K-rule), dissent, Not doing, pre-registered test;
  rows appended to brainstorm/LEDGER.md so later runs do not rediscover killed ideas.
