<!-- ub-template: ARCH-DECISIONS v1 kind=writer -->
Do not load or invoke any skill; this prompt is the whole task.
STAGE 12 - ARCHITECTURE DECISIONS, RISKS AND DEBT. Record the decisions the chosen architecture already made; decide
nothing new. Read no files and run no commands. Date: {{DATE}}. Language: {{LANG}} (ids, enum values and JSON keys
stay in English).

FROZEN BRIEF
{{ARCH_BRIEF}}

DRIVERS
{{DRIVERS_JSON}}

CHOSEN CANDIDATE
{{CHOSEN_CANDIDATE}}

THE OTHER CANDIDATES (neutral sheets; their approaches are considered options)
{{CANDIDATE_SHEETS}}

STRUCTURE FILES
{{STRUCTURE_FILES}}

PRE-MORTEM
{{PREMORTEM}}

RULES
1. adrs: write an ADR only for a choice that is hard to reverse, surprising without context, AND the result of a real
   trade-off (usually 3-7 ADRs). Each has at least 2 options; the considered options include the rejected
   candidates' approaches where they apply. drivers are QG ids. chosen is the exact name of one option. Every "bad"
   consequence names the risk ids it creates (risk_ids), or [] when none. confirmation says how compliance is
   checked (a test, a review, a metric).
2. risks: ids R-001, R-002, ... in order. They absorb the five pre-mortem causes and the candidate's own risks;
   likelihood and impact H/M/L; owner is a role; early_warning is observable; source names where the risk came from
   (pre-mortem, candidate, brief).
3. debt: technical debt accepted on purpose, ids TD-01, TD-02, ..., with why and the payoff trigger. Risks and debt
   stay separate.
Never state a version, price or limit as fact unless the inputs give it.

OUTPUT RULE
Return only one JSON object with adrs, risks and debt that matches the schema below: no prose, no code fence.
{{SCHEMA_TEXT}}
{{OUTPUT_RULE}}
