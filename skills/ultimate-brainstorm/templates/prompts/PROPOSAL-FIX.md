<!-- ub-template: PROPOSAL-FIX v1 kind=fixer -->
Do not load or invoke any skill; this prompt is the whole task.
STAGE 13 - PROPOSAL FIX. Revise the proposal sections and ONE-PAGER.md to answer the review items and the lint report
below, and nothing else. Do not reopen the choice of idea or architecture. Read no files and run no commands.
Date: {{DATE}}.

RULES FOR EVERY PROPOSAL SECTION
1. Use only facts from the proposal and the sources. Cite them as [S-###].
2. Every number, market claim or competitor claim without a source carries [ASSUMPTION: ...] or
   [ESTIMATE: range; basis].
3. Never invent customers, quotes, metrics or moats. Never use the word "novel".
4. Never change an architecture decision; only summarize it.
5. Say what is not being done.
6. Write in {{LANG}}. File names, IDs and section numbers stay in English.

THE PROPOSAL AS IT IS NOW (the sections, then ONE-PAGER.md after the line "--- FILE: ONE-PAGER.md ---")
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
2. Fix every lint FAIL, and every P11 item (a money figure or date that differs between ONE-PAGER.md and the
   sections).
3. ONE-PAGER.md summarizes the sections and is the file people forward. When a change alters a figure, a date, a
   milestone or the ask that ONE-PAGER.md states, or a lint item names ONE-PAGER.md, print ONE-PAGER.md in full too:
   its title line, then exactly these headings: ## Problem, ## Solution, ## Why now, ## Who, ## Differentiation,
   ## Architecture at a glance (keep its mermaid flowchart), ## MVP, ## Roadmap, ## Budget, ## Top risks, ## Metrics,
   ## The ask; at most 550 words; every figure, date and condition (such as "no earlier than") exactly as the
   sections state it.
4. Keep section 1 at most 300 words: put new detail in the later sections, not in section 1.
5. Print only the files you change, each in full (a section starting with its original heading, ONE-PAGER.md with
   its title line); plus review/resolution.md: a table | item | ADDRESSED/ACCEPTED-RISK/REJECTED | where or reason |.
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
