<!-- ub-template: PROPOSAL-RUBRIC v1 kind=rubric -->
Do not load or invoke any skill; this prompt is the whole task.
STAGE 13 - PROPOSAL RUBRIC. You did not write this proposal. Score it for the people who must decide on it; ignore
polish, length and confident tone. Quote or cite the section for every score. Read no files and run no commands.
Language of your comments: {{LANG}}.

THE PROPOSAL (PROPOSAL.md and ONE-PAGER.md)
{{SECTIONS_ALL}}

LINT REPORT
{{LINT_REPORT}}

CRITERIA (integer 1-5 each; 5 = a decision-maker could act on it today, 3 = usable with gaps, 1 = misleading or empty)
- decision_readiness: the ask, the options and the decision needed are explicit.
- substance_over_theater: claims carry sources, [ASSUMPTION] or [ESTIMATE] tags; no invented customers, quotes,
  metrics or moats.
- strategic_coherence: problem, solution, architecture, roadmap and metrics tell one story.
- doneness_clarity: each milestone has exit criteria; Milestone 0 is the pre-registered probe with its kill criterion.
- scope_honesty: what is not being done, the risks and the open questions are stated plainly.
- downstream_usability: a team could start planning from it without reopening the decisions.
- shape_fit: the length and structure fit the decision (one-pager within limits, sections complete).
must_fix: at most 6 items a sponsor would reject the proposal for (section, issue, fix). top_fixes: the 3-5 most
valuable improvements in one line each.

OUTPUT RULE
Return only one JSON object that matches the schema below: no prose, no code fence.
{{SCHEMA_TEXT}}
{{OUTPUT_RULE}}
