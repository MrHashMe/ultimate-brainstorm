<!-- ub-template: PROPOSAL-B v1 kind=writer -->
Do not load or invoke any skill; this prompt is the whole task.
STAGE 13 - PROPOSAL, PART B (sections 6-9). You write four sections of a project proposal for an idea the human
already chose, with an architecture (or approach) the human already chose. Read no files and run no commands: the
evidence pack below is all you may use. Build type: {{BUILD_TYPE}}. Date: {{DATE}}.

RULES FOR EVERY PROPOSAL SECTION
1. Use only facts from the evidence pack. Cite them as [S-###] with the ids of the SOURCES table.
2. Every number, market claim or competitor claim without a source carries [ASSUMPTION: ...] or
   [ESTIMATE: range; basis].
3. Never invent customers, quotes, metrics or moats. Never use the word "novel": only the prior-art checks speak to
   novelty, as "not located within this search".
4. Never change an architecture decision; only summarize it.
5. Say what is not being done.
6. Write in {{LANG}}. File names, IDs and section numbers stay in English.

EVIDENCE PACK B (architecture README, container view, top ADRs, matrix summary, deferred decisions, probe, drivers)
{{PACK_B}}

SOURCES
{{SOURCES_TABLE}}

FILES TO WRITE (paths relative to 11_PROPOSAL/; each file starts with its heading exactly as shown)
sections/06.md - build type system: "## 6. Architecture Summary": the container diagram copied verbatim (the whole
  mermaid block) from chosen/containers.md, the top ADRs by number (ADR-NNNN) with one line each, and "Alternatives
  considered": why this candidate beat the others, from the matrix. Build type approach: "## 6. Approach": the
  approach in one screen, from approach.md.
sections/07.md - "## 7. Scope and MVP": in scope, out of scope, non-goals.
sections/08.md - "## 8. Roadmap and Milestones": Milestone 0 = run the pre-registered probe, with its kill criterion
  copied from the probe; then milestones with relative timeframes (week 1-2, month 2, ...) and exit criteria for each.
  Nothing after Milestone 0 starts before its result.
sections/09.md - "## 9. Team and Effort": roles, effort ranges with confidence, and what is AI-assisted vs human-only.
Replace every angle-bracket placeholder; write no TODO, TBD or XXX.

OUTPUT RULE
Print each file as a FILE block, then the STATUS block, and nothing else. Allowed paths: {{ALLOWED_FILES}}.
=== FILE: sections/06.md ===
(content)
=== END FILE ===
(one block per file)
=== STATUS ===
{"status": "complete", "assumptions": ["..."], "open_questions": ["..."], "reason": ""}
=== END STATUS ===
{{OUTPUT_RULE}}
