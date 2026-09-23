<!-- ub-template: GAP v1 kind=generator -->
Do not load or invoke any skill; this prompt is the whole task.
{{GEN_HEADER}}

STRATEGY {{STRATEGY_ID}} - GAP CELL
Target cell: {{CELL}}
Generate 3 ideas that live exactly in this cell. Do not reinterpret the cell. If the cell is incoherent, output only
the line "TENSION: <why>". If filling the cell needs a domain concept to change, change it and name the DOMAIN TERM you
break (rule 8).
Mechanisms already covered - do not produce variants of them:
{{CLUSTER_NAMES}}
Previously considered in earlier runs (do not restate unless you say what changed):
{{LEDGER_TITLES}}

OUTPUT RULE
Print 3 output-format blocks whose Cell is exactly the target cell, or only the single line "TENSION: <why>".
{{OUTPUT_RULE}}
