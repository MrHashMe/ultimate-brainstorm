<!-- ub-template: ARCH-PACKAGE-LITE v1 kind=writer -->
Do not load or invoke any skill; this prompt is the whole task.
QUICK MODE - ARCHITECTURE PACKAGE (LITE). The architecture below leads the comparison. Write its minimal package in one
pass. Never change a decision the candidate made. Reuse its container ids (C-n), external ids (EXT-n), and the
drivers' QG and QAS ids exactly. Never state a version, price or limit as fact unless the inputs give it: mark
[ASSUMPTION] or [TO VERIFY]. Read no files and run no commands.
Date: {{DATE}}. Language: {{LANG}} (headings, ids, file names and JSON keys stay in English).

FROZEN BRIEF
{{ARCH_BRIEF}}

DRIVERS
{{DRIVERS_JSON}}

CANDIDATE (full text and JSON)
{{CHOSEN_CANDIDATE}}

FILES TO WRITE (paths relative to 10_ARCHITECTURE/)
chosen/containers.md
  ## Containers - a mermaid C4Container block immediately followed by a mermaid flowchart block with the same
  elements; then a table | id | name | technology | responsibility | data owned | interface |.
  ## How each quality goal is met - table | QG | mechanism | containers | QAS | expected response | with a row for
  every QG id in DRIVERS. Every EXT-n of the brief appears in this file.
chosen/data-model.md
  A mermaid erDiagram, then ## Entities - table | entity | fields | owner container | retention | PII |.
decisions.json
  One JSON object with adrs (exactly 3 ADRs: the hardest-to-reverse choices, each with at least 2 options),
  risks (ids R-001, ...) and debt (ids TD-01, ...; may be empty), matching the schema below.

MERMAID RULES: the diagram type is the first line of each block; (), [], {} and double quotes balance on every line;
no { blocks in C4 diagrams; no tab characters; node ids are plain words (C1, EXT1) with "C-1" in the labels.
Replace every angle-bracket placeholder; write no TODO, TBD or XXX.

FORMAT OF decisions.json (every key present; no other keys)
{"adrs": [{"title": "", "context": "", "drivers": ["QG1"], "options": [{"name": "", "pros": [""], "cons": [""]}],
  "chosen": "<one option name>", "justification": "", "good": [""], "bad": [{"text": "", "risk_ids": ["R-001"]}],
  "confirmation": "how we will know the decision holds", "more_info": ""}],
 "risks": [{"id": "R-001", "text": "", "likelihood": "H|M|L", "impact": "H|M|L", "mitigation": "", "owner": "<role>",
  "early_warning": "", "source": "candidate|premortem|check"}],
 "debt": [{"id": "TD-01", "text": "", "why": "", "payoff_trigger": ""}]}
Every R-NNN an ADR cites exists in risks.

OUTPUT RULE
Print each file as a FILE block, then the STATUS block, and nothing else. Allowed paths: {{ALLOWED_FILES}}.
=== FILE: chosen/containers.md ===
(content)
=== END FILE ===
(one block per file)
=== STATUS ===
{"status": "complete", "assumptions": ["..."], "open_questions": ["..."], "reason": ""}
=== END STATUS ===
{{OUTPUT_RULE}}
