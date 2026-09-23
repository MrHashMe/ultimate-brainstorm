<!-- ub-template: PROPOSAL-REDTEAM v1 kind=redteam -->
Do not load or invoke any skill; this prompt is the whole task.
STAGE 13 - PROPOSAL RED-TEAM. You did not write this proposal. Find the load-bearing claims it rests on and how each
could fail. Steelman each claim before you attack it. Never invent a weakness; fewer items is fine. Read no files and
run no commands. Language of your text: {{LANG}}.

THE PROPOSAL
{{SECTIONS_ALL}}

For at most 8 load-bearing claims:
- claim: the claim with its section number;
- steelman: its strongest honest version;
- fails_if: a falsifiable "Fails if ...";
- impact, likelihood and cheapness (how cheap it is to test): H, M or L each;
- cheapest_test: the cheapest test that would reveal the failure within two weeks;
- kill_criterion: the result that should stop the project.

OUTPUT RULE
Return only one JSON object with the items array that matches the schema below: no prose, no code fence.
{{SCHEMA_TEXT}}
{{OUTPUT_RULE}}
