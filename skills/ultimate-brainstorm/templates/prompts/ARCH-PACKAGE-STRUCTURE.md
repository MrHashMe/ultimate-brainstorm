<!-- ub-template: ARCH-PACKAGE-STRUCTURE v1 kind=writer -->
Do not load or invoke any skill; this prompt is the whole task.
STAGE 12 - ARCHITECTURE PACKAGE, STRUCTURE. The architecture below was chosen by the human. Write its structural
documents. Never change a decision the chosen candidate made; add detail, not direction. Reuse the candidate's
container ids (C-n) and external ids (EXT-n) and the drivers' QG and QAS ids exactly. Never state a version, price or
limit as fact unless the inputs give it: mark [ASSUMPTION] or [TO VERIFY]. Read no files and run no commands unless
this job gives you read access to the repository; then cite files as path:line.
Variant: {{VARIANT}}. Date: {{DATE}}. Language: {{LANG}} (headings, ids and file names stay in English).

FROZEN BRIEF
{{ARCH_BRIEF}}

DRIVERS
{{DRIVERS_JSON}}

CHOSEN CANDIDATE (full text and JSON)
{{CHOSEN_CANDIDATE}}

ELEMENTS TO STEAL FROM OTHER CANDIDATES (chosen by the human; may be empty)
{{STEAL_NOTES}}

PRE-MORTEM
{{PREMORTEM}}

FILES TO WRITE (paths relative to 10_ARCHITECTURE/)
chosen/containers.md
  ## Containers - a mermaid C4Container block immediately followed by a mermaid flowchart block with the same
  elements; then a table | id | name | technology | responsibility | data owned | interface | with one row per C-n.
  ## How each quality goal is met - table | QG | mechanism | containers | QAS | expected response | with a row for
  every QG id in DRIVERS. Every EXT-n of the brief appears somewhere in this file.
chosen/runtime.md
  One "## F-1 <title>", "## F-2 <title>", ... section per key runtime flow, each with a mermaid sequenceDiagram. At
  least one section is "## F-n Failure and recovery: <title>" (what fails, how it is detected, how it recovers).
  Every C-n from containers.md appears in at least one flow.
chosen/data-model.md
  A mermaid erDiagram, then ## Entities - table | entity | fields | owner container | retention | PII |.
chosen/api.md
  The interfaces between containers and to the outside: style, authentication, versioning, error format, and the
  main operations.
chosen/api/openapi.yaml (only when the system exposes an HTTP API) or chosen/api/cli.md (when it is a command-line
  tool): a minimal but valid description of the main operations.

MERMAID RULES (a linter checks them)
- The first line inside each mermaid block is the diagram type: C4Container, flowchart, sequenceDiagram or
  erDiagram.
- On every line, (), [], {} and double quotes are balanced; never open a { block in C4 diagrams (no
  System_Boundary blocks); group with subgraph ... end in the flowchart instead.
- No tab characters. Node ids are plain words such as C1, EXT1; put "C-1" and "EXT-1" in the labels.
Replace every angle-bracket placeholder; write no TODO, TBD or XXX.

OUTPUT RULE
Print each file as a FILE block, then the STATUS block, and nothing else. Allowed paths: {{ALLOWED_FILES}}.
=== FILE: chosen/containers.md ===
(content)
=== END FILE ===
(one block per file)
=== STATUS ===
{"status": "complete", "assumptions": ["..."], "open_questions": ["..."], "reason": ""}
=== END STATUS ===
status is complete, partial (say what is missing in reason) or blocked.
{{OUTPUT_RULE}}
