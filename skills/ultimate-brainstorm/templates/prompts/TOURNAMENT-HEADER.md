<!-- ub-template: TOURNAMENT-HEADER v1 kind=partial -->
Do not load or invoke any skill; this prompt is the whole task.
You are a judge in a pairwise tournament. You did not write these ideas. The cards are normalized: ignore wording,
length and tone. The "Prior art" line is the only novelty information you may use. Read no files and run no commands.
BRIEF: {{HMW}}
AUDIENCE: {{AUDIENCE}}
HARD CONSTRAINTS:
{{HARD_CONSTRAINTS}}
CRITERIA AND WEIGHTS (criterion weight: anchor for 5):
{{CRITERIA_WEIGHTS}}
For each pair listed at the end, decide which card better achieves the brief under its constraints, weighting the
criteria. Judge each pair only on its two cards; earlier pairs must not influence later ones. Use TIE only if the two
are truly indistinguishable.
OUTPUT RULE
Return only JSON: {"verdicts":[{"pair_id":"P01","winner":"FIRST","confidence":0.7,"decisive_reason":"max 20 words"}]}
where winner is FIRST, SECOND or TIE, with one verdict for every pair listed at the end. It must match this schema:
{{SCHEMA_TEXT}}
{{OUTPUT_RULE}}
