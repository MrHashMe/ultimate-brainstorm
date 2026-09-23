<!-- ub-template: ARCH-FIX v1 kind=fixer -->
Do not load or invoke any skill; this prompt is the whole task.
STAGE 12 - ARCHITECTURE FIX. Apply the P0 and P1 review findings and the lint FAILs below to the package, and nothing
else. Do not reopen the choice of architecture or add features. Keep every id (C-n, EXT-n, QG, QAS, R-NNN, TD-NN,
ADR numbers) stable. Read no files and run no commands. Date: {{DATE}}. Language: {{LANG}}.

DRIVERS
{{DRIVERS_JSON}}

THE PACKAGE AS IT IS NOW (files of 10_ARCHITECTURE/chosen/, decisions.json)
{{STRUCTURE_FILES}}

REVIEW FINDINGS (P0 and P1)
{{FINDINGS}}

LINT REPORT (FAIL items)
{{LINT_REPORT}}

RULES
- Print only the files you replace, each in full. A decision change goes into decisions.json (print the whole object
  again, matching its existing structure); a decision you cannot make now goes into chosen/deferred.md.
- Write review/resolution.md: a table | finding | FIXED/DEFERRED/REJECTED | reason | with one row for every P0 and P1
  finding and every lint FAIL (use the lint id, for example A6).
- Mermaid blocks keep the rules: diagram type on the first line, balanced brackets and quotes on every line, no tabs,
  a flowchart block after every C4 block. Write no TODO, TBD or XXX.

OUTPUT RULE
Print each replaced file and review/resolution.md as FILE blocks, then the STATUS block, and nothing else. Allowed
paths: {{ALLOWED_FILES}}.
=== FILE: review/resolution.md ===
(content)
=== END FILE ===
=== STATUS ===
{"status": "complete", "assumptions": ["..."], "open_questions": ["each finding or FAIL left unresolved"], "reason": ""}
=== END STATUS ===
{{OUTPUT_RULE}}
