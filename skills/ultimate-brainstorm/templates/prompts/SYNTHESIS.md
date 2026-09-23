<!-- ub-template: SYNTHESIS v1 kind=synthesis -->
Do not load or invoke any skill; this prompt is the whole task.
STAGE 10 - SYNTHESIS. Read the pre-commit, every review and the frame below. Do not choose for the user. Read no files
and run no commands. Language: {{LANG}} (headings and the final line stay in English).
Tiebreaker, declared in advance: when reviewers conflict, weigh the brief's highest-weighted criterion first.
Count a point as consensus only if at least two reviewers raised it independently. Treat unanimity as a warning, not
as proof.

CRITERIA AND WEIGHTS
{{CRITERIA_WEIGHTS}}

IDEAS (cards, checks, tournament record)
{{TOP_CARDS}}

PRE-COMMIT (written before any review)
{{PRECOMMIT_NOTE}}

REVIEWS
{{REVIEWS}}

FRAME
{{FRAME_FULL}}

Write these sections:
## 1. Per idea
For each idea a "### <ID>" block with:
- Recommendation (2-3 sentences; take a position)
- Key tradeoffs (2-3 bullets)
- Strongest disagreement: each side's best argument - do not water it down
- What every reviewer missed
- If the reviewers agree: the shared premise nobody tested
- Pre-mortem: "It is 6 months later and this failed because..." (3 causes, each with an early warning sign)
- Did the reviews change the pre-commit? yes/no and why
## 2. Decision brief
One screen: per idea its pitch, tournament record, prior-art verdict, top kill-assumption with its cheapest test.
## 3. Whole effort
Is the frame's kill condition for the whole effort met, or does every idea fail the same premise? Say which, with the
evidence, or say neither.

OUTPUT RULE
Print sections 1-3, then end with exactly one line:
WHOLE-EFFORT: CONTINUE - <reason>   or   WHOLE-EFFORT: STOP - <reason>
Write STOP only when the frame's kill condition is met or every idea fails the same premise.
{{OUTPUT_RULE}}
