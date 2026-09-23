<!-- ub-template: EXEC-ONEPAGER v1 kind=writer -->
Do not load or invoke any skill; this prompt is the whole task.
STAGE 13 - EXECUTIVE SUMMARY AND ONE-PAGER. Sections 2-13 of the proposal are written (below). Summarize them; add no
new facts. Read no files and run no commands. Date: {{DATE}}.

RULES FOR EVERY PROPOSAL SECTION
1. Use only facts from the sections below. Keep their [S-###] citations.
2. Every number, market claim or competitor claim without a source carries [ASSUMPTION: ...] or
   [ESTIMATE: range; basis].
3. Never invent customers, quotes, metrics or moats. Never use the word "novel".
4. Never change an architecture decision; only summarize it.
5. Say what is not being done.
6. Write in {{LANG}}. File names, IDs and section numbers stay in English.

THE PROPOSAL SECTIONS
{{SECTIONS_ALL}}

SOURCES
{{SOURCES_TABLE}}

FILES TO WRITE (paths relative to 11_PROPOSAL/)
sections/01.md - starts with "## 1. Executive Summary"; standalone, at most 300 words: the problem, the solution, why
  now, the ask, the Milestone 0 test and what is not being done.
ONE-PAGER.md - at most 550 words, starting with "# <title>" and then exactly these headings: ## Problem, ## Solution,
  ## Why now, ## Who, ## Differentiation, ## Architecture at a glance (one mermaid flowchart with at most 8 nodes;
  balanced brackets and quotes on every line, no tabs), ## MVP, ## Roadmap, ## Budget, ## Top risks (3, each with its
  test), ## Metrics, ## The ask.
Replace every angle-bracket placeholder; write no TODO, TBD or XXX.

OUTPUT RULE
Print both files as FILE blocks, then the STATUS block, and nothing else. Allowed paths: {{ALLOWED_FILES}}.
=== FILE: sections/01.md ===
(content)
=== END FILE ===
=== FILE: ONE-PAGER.md ===
(content)
=== END FILE ===
=== STATUS ===
{"status": "complete", "assumptions": ["..."], "open_questions": ["..."], "reason": ""}
=== END STATUS ===
{{OUTPUT_RULE}}
