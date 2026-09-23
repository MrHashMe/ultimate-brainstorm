<!-- ub-template: S3-EDE v1 kind=generator -->
Do not load or invoke any skill; this prompt is the whole task.
{{GEN_HEADER}}

STRATEGY {{STRATEGY_ID}} - ENUMERATE, DIVERSIFY, ELABORATE
Mode: {{MODE}}. In deep mode use 100 titles and redo Step 2 while fewer than 75 changed ("Changed: N of 100");
otherwise use 40 titles as written below.
Step 1: List 40 short titles for ideas that meet the brief.
Step 2: Make the ideas bolder and more different from each other; no two may share a mechanism. Show Step 1 and
Step 2 side by side as a two-column table, then write the line "Changed: N of 40". If N < 30, redo Step 2.
Step 3: Write output-format blocks for the Step 2 titles only.

OUTPUT RULE
Print the Step 1 / Step 2 table, the "Changed: N of M" line, then one output-format block per Step 2 title (at least
10), and nothing else.
{{OUTPUT_RULE}}
