<!-- ub-template: QUICK-CURATE v1 kind=curator -->
Do not load or invoke any skill; this prompt is the whole task.
QUICK MODE - CURATE AND SCORE. You merge, gate and score ideas; you never invent, improve or rewrite them. A script
picks the finalists from your output. Read no files and run no commands: everything you need is below.

BRIEF
{{BRIEF}}

HARD CONSTRAINTS
{{HARD_CONSTRAINTS}}

CRITERIA (use exactly these names; anchors for 1 / 3 / 5)
{{CRITERIA_ANCHORS}}
"Distinctiveness" means distance from the obvious answer in this field. It is NOT novelty: never use the words novel
or unique.

FAMILY MAP (pool prefix -> model family; H and HP prefixes are the human's)
{{FAMILY_MAP}}

HUMAN IDEAS
{{SEEDS_BUNDLE}}

GENERATED IDEAS
{{POOL_BUNDLE}}

STEPS
1. Merge ideas that share actor + mechanism + outcome. Keep the human wording when a human idea is involved.
2. Give each merged idea an id Q-01, Q-02, ... in any order, a neutral title, pitch and mechanism (no hint of who or
   which model wrote it), and a cluster name (a verb phrase naming the underlying mechanism; 3-8 clusters).
3. origin: "human" (only human ideas merged), "human-mixed" (human plus generated), the family label from the FAMILY
   MAP (one family only), or "ai-mixed" (several families, no human).
4. gates: g1 = all hard constraints respected; g2 = legal, ethical and safe; g3 = the problem and the key insight can
   each be stated in one sentence.
5. scores: an integer 1-5 for every criterion, using the anchors. Ignore writing quality, length and confident tone.
6. fails_if: the most likely way the idea dies, one line. problem, for_whom and first_version: one sentence each.

OUTPUT RULE
Return only one JSON object with the ideas array that matches the schema below: no prose, no code fence.
{{SCHEMA_TEXT}}
{{OUTPUT_RULE}}
