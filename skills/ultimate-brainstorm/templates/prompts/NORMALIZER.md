<!-- ub-template: NORMALIZER v1 kind=normalizer -->
Do not load or invoke any skill; this prompt is the whole task.
STAGE 9 - NORMALIZE THE FINALIST CARDS. Rewrite each finalist below into a card of 90-110 words in plain, neutral
language. Keep the substance identical: do not improve, weaken or add facts. Remove every label that says where an
idea came from (person, model, strategy), every probability, hype words and formatting. Read no files and run no
commands. Language: {{LANG}} (the line labels stay in English).

FINALISTS (each with its check summary)
{{FINALISTS}}

CARD FORMAT: for each finalist a line "## <ID>" (the ID appears nowhere else in the card), then exactly these lines:
Title: (copy the given title exactly; never rename it)
Problem: (1 sentence)
Mechanism: (2 sentences)
For whom: ...
First version: (1 sentence)
Main risk: (the top kill-assumption from its check)
Prior art: CROWDED | ADJACENT | NOT LOCATED | NOT CHECKED - differentiator: ...

OUTPUT RULE
Print one card per finalist, in the order given, and nothing else.
{{OUTPUT_RULE}}
