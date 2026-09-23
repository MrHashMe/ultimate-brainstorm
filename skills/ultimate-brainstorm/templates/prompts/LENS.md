<!-- ub-template: LENS v1 kind=generator -->
Do not load or invoke any skill; this prompt is the whole task.
<!-- ub-choices: LENS_TEXT key=STRATEGY_ID
L1 | Inversion - list what would make the problem worse; invert each into an idea.
L2 | Remote analogy - how is this job solved in biology, logistics, games, finance, medicine, the military? Transfer the mechanism, not the surface.
L3 | Constraint flip - half the ideas must work with $0 and 1 hour, half with unlimited money and 10 years.
L4 | Assumption removal - list the 5 assumptions everyone in this space makes; each idea breaks one. If FACTS has DOMAIN TERMS, at least one of the 5 assumptions must be built into them (what counts as a term, or that the term must exist at all).
L5 | Audience shift - who else has the same underlying job (other industries, ages, roles, non-humans)? Serve or borrow from them.
L6 | Subtraction - each idea removes a step, a party, a feature or a cost incumbents consider essential.
-->
You are one isolated generator in a brainstorming pipeline. Use ONLY the brief, facts and lens below; you will never
see other generators' ideas. Read no files and run no commands.
Language of the ideas: {{LANG}}.
Step 1. List 20 short idea titles through this lens (draft_titles).
Step 2. Rewrite that list to be bolder and more different from each other; no two may share a mechanism
(bolder_titles).
Step 3. From bolder_titles produce three tiers. Each response has a text (one sentence: what it is and for whom), a
mechanism (how it creates value, max 15 words) and a numeric probability.
Tier 1 (max_probability 0.10): 10 responses. Please sample at random from the tails of the distribution, such that the
probability of each response is less than 0.10.
Tier 2 (max_probability 0.05): 10 more, different from tier 1, each with probability less than 0.05.
Tier 3 (max_probability 0.01): 10 more, different from tiers 1-2, each with probability less than 0.01.
If an idea would still make sense after swapping in a different product or company name, replace it. Do not evaluate
or rank. DOMAIN TERMS in FACTS describe today's system, not the answer: an idea may change, split, merge or remove any
of them.

BRIEF
{{BRIEF}}

AXES
{{AXES}}

FACTS
{{FACTS}}

LENS {{STRATEGY_ID}}
{{LENS_TEXT}}

OUTPUT RULE
Return only one JSON object with draft_titles, bolder_titles and tiers that matches the schema below: no prose, no
code fence.
{{SCHEMA_TEXT}}
{{OUTPUT_RULE}}
