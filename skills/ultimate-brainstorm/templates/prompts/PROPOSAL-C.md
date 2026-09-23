<!-- ub-template: PROPOSAL-C v1 kind=writer -->
Do not load or invoke any skill; this prompt is the whole task.
STAGE 13 - PROPOSAL, PART C (sections 10-13). You write four sections of a project proposal for an idea the human
already chose. Read no files and run no commands: the evidence pack below is all you may use. Date: {{DATE}}.

RULES FOR EVERY PROPOSAL SECTION
1. Use only facts from the evidence pack. Cite them as [S-###] with the ids of the SOURCES table.
2. Every number, market claim or competitor claim without a source carries [ASSUMPTION: ...] or
   [ESTIMATE: range; basis].
3. Never invent customers, quotes, metrics or moats. Never use the word "novel": only the prior-art checks speak to
   novelty, as "not located within this search".
4. Never change an architecture decision; only summarize it.
5. Say what is not being done.
6. Write in {{LANG}}. File names, IDs and section numbers stay in English.

EVIDENCE PACK C (cost model, risks, pre-mortem, red-team kill-assumptions, frame success, open questions)
{{PACK_C}}

SOURCES
{{SOURCES_TABLE}}

FILES TO WRITE (paths relative to 11_PROPOSAL/; each file starts with its heading exactly as shown)
sections/10.md - "## 10. Budget and Cost": build and run cost copied from the cost model (the same dollar figures),
  and unit economics or a break-even estimate marked [ESTIMATE: range; basis].
sections/11.md - "## 11. Risks and Mitigations": the top risks by id (R-NNN) from the risk register, the pre-mortem
  causes and the red-team kill-assumptions, each with its mitigation or test.
sections/12.md - "## 12. Success Metrics and Validation Plan": leading and lagging metrics, SMART key results, and
  the cheapest test for each load-bearing assumption.
sections/13.md - "## 13. Open Questions": one bullet per question, each with "Owner: <role>" and
  "Decide by: <milestone>".
Replace every angle-bracket placeholder; write no TODO, TBD or XXX.

OUTPUT RULE
Print each file as a FILE block, then the STATUS block, and nothing else. Allowed paths: {{ALLOWED_FILES}}.
=== FILE: sections/10.md ===
(content)
=== END FILE ===
(one block per file)
=== STATUS ===
{"status": "complete", "assumptions": ["..."], "open_questions": ["..."], "reason": ""}
=== END STATUS ===
{{OUTPUT_RULE}}
