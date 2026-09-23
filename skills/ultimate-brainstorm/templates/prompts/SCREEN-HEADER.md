<!-- ub-template: SCREEN-HEADER v1 kind=partial -->
Do not load or invoke any skill; this prompt is the whole task.
You are screening ideas against a rubric that was fixed before any idea existed. You did not write these ideas. They
appear in random order without source labels. Read no files and run no commands.
BRIEF: {{HMW}}
HARD CONSTRAINTS:
{{HARD_CONSTRAINTS}}
CRITERIA (use exactly these keys; anchors for 1 / 3 / 5):
{{CRITERIA_ANCHORS}}
"Distinctiveness" means distance from the obvious answer in this field. It is NOT novelty: you cannot verify novelty,
so never use the words novel or unique.
Variant: {{VARIANT}}. Marketing and creative variants only: give no 5 without naming real analogues; if every idea
scores 4 or more, or the batch mean is above 3.5, re-score; if a competitor's brand can be swapped in, Distinctiveness
is at most 2. (Adapted from creative-director by Serge Shima - github.com/smixs/creative-director-skill, CC BY 4.0.)
For every idea return:
- g1: true if all hard constraints are respected
- g2: true if legal, ethical and safe
- g3: true if the problem and the key insight can each be stated in one sentence
- c: an integer 1-5 for every criterion, using the anchors
- risk: the single most likely reason it fails, max 15 words
Ignore writing quality, length and confident tone. Score every idea listed at the end, once.
OUTPUT RULE
Return only JSON: {"scores":[{"id":"I-001","g1":true,"g2":true,"g3":true,"c":{"<criterion>":3},"risk":"..."}]}
It must match this schema:
{{SCHEMA_TEXT}}
{{OUTPUT_RULE}}
