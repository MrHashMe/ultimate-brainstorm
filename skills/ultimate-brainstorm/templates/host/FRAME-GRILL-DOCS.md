<!-- ub-template: FRAME-GRILL-DOCS v1 kind=host -->
# HOST TASK: frame the problem with grilling + domain-modeling (Stage 2, software and growth)

This is the pair that mattpocock's grill-with-docs wraps; the pipeline loads the two skills by name because
grill-with-docs itself is manual-only. Run it in the MAIN conversation, never in a sub-agent, with plan mode off (plan
mode also blocks the CONTEXT.proposed.md writes). The engine already saved CONTEXT.before.md and the git baseline, and
it runs the footprint check after you finish. Card fields used below: task.skill (the grilling skill),
task.argument_file, task.writes, task.done_cmd. The domain-modeling skill name is on the "skills:" line of the
argument text.

1. Read task.argument_file. Tell the user in one line: "Resolved terms go to <the CONTEXT.proposed.md path in the
   argument>; CONTEXT.md and docs/adr/ stay untouched until the handoff."
2. If CONTEXT.proposed.md already exists (a resumed Stage 2), read it, tell the user which terms are already staged,
   and append to it instead of overwriting.
3. Load both skills with the WHOLE argument text as the argument of BOTH calls, grilling first, then domain-modeling:
   - Claude Code: in the same turn, before asking anything, call the Skill tool for grilling, then for
     domain-modeling (the argument then directly follows domain-modeling's write rule, so its override wins).
   - Codex, Kimi Code, ZCode, others: open grilling's SKILL.md, domain-modeling's SKILL.md and its
     CONTEXT-FORMAT.md from your skills list, then re-read the argument text last and run the interview yourself.
   If a call fails, or only one skill is installed, run the interview from the argument text yourself.
4. Let the interview run (the argument caps the rounds). Propose no solutions, example ideas or idea categories. If
   the user mentions a solution idea, append it to 00_HUMAN_SEEDS.md under "## Ideas" (when the user agrees).
5. Check that both skills took effect: if any term resolved, CONTEXT.proposed.md must exist. If domain-modeling was
   skipped or failed, say so and ask its domain moves (term challenges, at most 3 edge-case scenarios about today's
   behavior, ADR gate-or-reopenable questions) as one extra round (allowed beyond the round cap).
6. Then ask once, if not settled: "How are we (or the current approach) part of the problem?", "Who benefits if this
   problem is never solved?", the solution-type question (hard constraint, soft preference or hypothesis) when the
   topic names one, and the variant add-ons in references/variants.md (growth: pin the measurement definitions of
   activated, retained and converted with event, window and source, tagged [MEASUREMENT]).
7. Write back STATED (the user's words) and ASSUMED (your inferences), the criteria with anchors and the axes as
   defaults (defaults by variant are in templates/prompts/FRAME-FINAL.md). Ask for corrections; wait for
   confirmation.
8. After the user confirms, write the files listed in task.writes (01_FRAME.md and criteria.json, in the format of
   templates/prompts/FRAME-FINAL.md, including the "## Domain language" section copied from CONTEXT.proposed.md with
   each term's NEW, CHANGED or MEASUREMENT tag, the relevant ADRs as "ADR-NNNN | decision | gate or reopenable", and
   every code contradiction as "claim | what the code does | file:line").
9. Never create, edit or rewrite CONTEXT.md, CONTEXT-MAP.md or anything under docs/adr/ in this stage. Run
   task.done_cmd.

## Argument
<!-- ub-argument:begin -->
Do not read anything under brainstorm/ except {{RUN_DIR}}/CONTEXT.proposed.md; it is not part of the codebase. Give
every fact-finding sub-agent the same rule.
The problem as I wrote it (Problem and Off-limits sections of my seeds file):
{{SEED_PROBLEM}}
Topic: {{TOPIC}}
Grill me on the PROBLEM ONLY: who has it, the job they are trying to get done, what success looks like, real
constraints, non-goals, and what has been tried. Do not propose solutions, example ideas or idea categories - not even
inside your recommended answers or multiple-choice options. Recommended answers are allowed only for constraints,
scope, timeline and terminology. Look facts up yourself and ask me only for decisions. At most {{ROUND_CAP}} rounds,
then wait for my confirmation.
Also apply domain-modeling to the EXISTING domain this problem lives in:
- Read CONTEXT.md (or CONTEXT-MAP.md and the CONTEXT.md files it points to) and docs/adr/ if they exist.
- When I use a term that conflicts with the glossary, or a vague or overloaded term, call it out and propose one
  precise canonical term. A term names something that already exists; never propose a new feature or solution as a
  term.
- Resolve at most 5 terms, and only those needed to state the problem, success, constraints or premises. If the repo
  has no CONTEXT.md, do not build a glossary: resolve only the terms those sections need.
- Stress-test domain relationships with at most 3 edge-case scenarios, each asked about today's behavior ("What happens
  today when ...?"), never as a proposal ("What if we let ...?").
- Put term challenges and scenarios into the numbered rounds (they count toward the questions per round and the round
  cap); do not interrupt between rounds.
- When I state how something works, check the code and quote file:line for any contradiction.
- For each ADR that bears on this problem, ask once whether it is a hard constraint for this brainstorm (a gate) or
  open to reopening (a soft constraint).
- OVERRIDE of domain-modeling's file rules for this whole session (this wins over its "Update CONTEXT.md inline",
  "Create files lazily" and "Offer ADRs sparingly"): whenever domain-modeling says to create or update CONTEXT.md (or a
  per-context CONTEXT.md), write to {{RUN_DIR}}/CONTEXT.proposed.md instead, the moment the term resolves, using the
  skeleton below. Never create, edit or rewrite CONTEXT.md, CONTEXT-MAP.md or anything under docs/adr/ during this
  session. Do not offer ADRs; when a decision passes all three ADR gates, add it to the Decision ledger marked
  ADR-CANDIDATE. The handoff stage asks me about terms and ADRs.
Skeleton of CONTEXT.proposed.md:
  # Proposed domain terms - {{RUN_NAME}}
  Target: CONTEXT.md | (the path from CONTEXT-MAP.md)
  ## Language            (with CONTEXT-MAP.md: one "## (context name)" heading per context, matching the map)
  **(Term)** [NEW]:
  (1-2 sentences: what it IS; no implementation details)
  _Avoid_: (synonyms)
  **(Existing term)** [CHANGED; was: "(current definition)"]:
  (new definition)
  _Avoid_: (old plus new synonyms)
  Growth metric terms ("activated", "retained", "converted") get the tag [MEASUREMENT] and the note "(measurement
  definition; ideas may propose a different one)".
  Write only terms that are new or changed and specific to this project; a term confirmed unchanged is not written.
skills: grilling = the skill you were started with; domain-modeling = {{COMPONENT_NAME}}
(For the orchestrator, not the interview: variant {{VARIANT}}; strategy plan {{STRATEGY_MAP}}; privacy
{{PRIVACY_LINE}}.)
<!-- ub-argument:end -->
