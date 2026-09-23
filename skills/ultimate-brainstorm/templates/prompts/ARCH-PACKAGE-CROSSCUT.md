<!-- ub-template: ARCH-PACKAGE-CROSSCUT v1 kind=writer -->
Do not load or invoke any skill; this prompt is the whole task.
STAGE 12 - ARCHITECTURE PACKAGE, CROSS-CUTTING CONCERNS. The architecture below was chosen by the human and its
structure is written. Write the cross-cutting documents. Never change a decision; add detail, not direction. Reuse the
container ids (C-n), external ids (EXT-n), QG and QAS ids exactly. Every number you did not receive is an
[ASSUMPTION: ...] or an [ESTIMATE: range; basis]. Read no files and run no commands.
Variant: {{VARIANT}}. Date: {{DATE}}. Language: {{LANG}} (headings, ids and file names stay in English).

FROZEN BRIEF
{{ARCH_BRIEF}}

DRIVERS
{{DRIVERS_JSON}}

CHOSEN CANDIDATE
{{CHOSEN_CANDIDATE}}

STRUCTURE FILES ALREADY WRITTEN
{{STRUCTURE_FILES}}

PRE-MORTEM
{{PREMORTEM}}

FILES TO WRITE (paths relative to 10_ARCHITECTURE/; each of the first three at least 120 words, or named in
chosen/deferred.md with the reason)
chosen/deployment.md
  Environments, hosting, CI/CD, infrastructure as code, observability (logs, metrics, alerts), backup and disaster
  recovery with RTO and RPO numbers.
chosen/security-privacy.md
  A data classification table, authentication and authorization, STRIDE-lite per trust boundary (spoofing,
  tampering, repudiation, information disclosure, denial of service, elevation of privilege), PII handling, and the
  compliance scope.
chosen/cost-model.md - exactly these headings:
  ## Assumptions - table | id | assumption | value | source | (source is a reference or [ASSUMPTION])
  ## Monthly run cost - table | item | MVP | 10x | 100x |
  ## Per active user
  ## LLM and API costs
  ## Build cost - a person-weeks range
  ## Sensitivity - the effect of +50% and -50% on the top cost driver
chosen/deferred.md
  Table | decision | why deferred | trigger | decide by |. Decisions that are not needed before Milestone 0 belong
  here, not in an ADR.
Replace every angle-bracket placeholder; write no TODO, TBD or XXX. Mermaid blocks, if any, follow the same rules as
the structure files: diagram type on the first line, balanced brackets and quotes on every line, no tabs.

OUTPUT RULE
Print each file as a FILE block, then the STATUS block, and nothing else. Allowed paths: {{ALLOWED_FILES}}.
=== FILE: chosen/deployment.md ===
(content)
=== END FILE ===
(one block per file)
=== STATUS ===
{"status": "complete", "assumptions": ["..."], "open_questions": ["..."], "reason": ""}
=== END STATUS ===
status is complete, partial (say what is missing in reason) or blocked.
{{OUTPUT_RULE}}
