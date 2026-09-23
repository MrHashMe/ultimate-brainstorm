<!-- ub-template: PROPOSAL-FIX v1 kind=fixer -->
Do not load or invoke any skill; this prompt is the whole task.
STAGE 13 - PROPOSAL FIX. Revise the proposal sections to answer the review items below, and nothing else. Do not reopen
the choice of idea or architecture. Read no files and run no commands. Date: {{DATE}}.

RULES FOR EVERY PROPOSAL SECTION
1. Use only facts from the proposal and the sources. Cite them as [S-###].
2. Every number, market claim or competitor claim without a source carries [ASSUMPTION: ...] or
   [ESTIMATE: range; basis].
3. Never invent customers, quotes, metrics or moats. Never use the word "novel".
4. Never change an architecture decision; only summarize it.
5. Say what is not being done.
6. Write in {{LANG}}. File names, IDs and section numbers stay in English.

THE PROPOSAL AS IT IS NOW (sections/NN.md files and ONE-PAGER.md)
{{SECTIONS_ALL}}

RUBRIC MUST-FIX ITEMS
{{RUBRIC_FIXES}}

RED-TEAM ITEMS (the top 5 by impact x likelihood x cheapness)
{{REDTEAM_ITEMS}}

CHANGES THE USER ASKED FOR (may be empty; they take priority)
{{USER_CHANGES}}

LINT REPORT
{{LINT_REPORT}}

STEPS
1. Answer every must-fix item, every listed red-team item and every user change as ADDRESSED (say where),
   ACCEPTED-RISK (moved into section 11) or REJECTED (with the reason).
2. Fix every lint FAIL in the sections.
3. Print only the section files you change, each in full, starting with its original heading; plus
   review/resolution.md: a table | item | ADDRESSED/ACCEPTED-RISK/REJECTED | where or reason |.
Replace every angle-bracket placeholder; write no TODO, TBD or XXX.

OUTPUT RULE
Print each changed file and review/resolution.md as FILE blocks, then the STATUS block, and nothing else. Allowed
paths: {{ALLOWED_FILES}}.
=== FILE: review/resolution.md ===
(content)
=== END FILE ===
=== STATUS ===
{"status": "complete", "assumptions": ["..."], "open_questions": ["..."], "reason": ""}
=== END STATUS ===
{{OUTPUT_RULE}}
