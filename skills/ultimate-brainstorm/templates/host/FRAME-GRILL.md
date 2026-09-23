<!-- ub-template: FRAME-GRILL v1 kind=host -->
# HOST TASK: frame the problem with the grilling skill (Stage 2)

You run this in the MAIN conversation, never in a sub-agent: grilling is interactive and waits for the user every
round. Plan mode must be off. Card fields used below: task.skill, task.argument_file, task.writes, task.done_cmd.

1. Read task.argument_file. Its text is the argument for the skill.
2. Invoke the installed skill named exactly as task.skill (for example `mattpocock-skills:grilling`), with the whole
   argument text as its argument. Claude Code: the Skill tool. Kimi Code: the skill tool or `/skill:<name>` as your
   skills list shows it. Codex, ZCode and others: open that skill's SKILL.md from your skills list, then re-read the
   argument text last and run the interview yourself. Never call grill-me or grill-with-docs.
3. Let the skill run its rounds (the argument caps them). Look facts up yourself; ask the user only for decisions.
   Propose no solutions, example ideas or idea categories - not even inside recommended answers. If the user mentions
   a solution idea, append it to the seeds file 00_HUMAN_SEEDS.md under "## Ideas" (only when the user agrees) and
   keep it out of the frame.
4. After the grilling rounds, ask these once, in one message, if the interview has not settled them:
   - "How are we (or the current approach) part of the problem?" and "Who benefits if this problem is never solved?"
   - If the topic names a solution type, technology or business model: is it (a) a hard constraint, (b) a soft
     preference, or (c) a hypothesis to test against alternatives?
   - The variant add-on questions in references/variants.md that apply (product forcing questions: one per message,
     at most one push-back each).
5. Write back your understanding as two lists, STATED (the user's words) and ASSUMED (your inferences), plus the
   criteria with anchors and the axes as defaults (defaults by variant are listed in
   templates/prompts/FRAME-FINAL.md). Ask for corrections, then wait for the user's confirmation.
6. After the user confirms, write exactly the files listed in task.writes (normally 01_FRAME.md and criteria.json in
   the run folder) in the format of templates/prompts/FRAME-FINAL.md (FORMAT OF 01_FRAME.md and FORMAT OF
   criteria.json). Copy the Strategy plan and the privacy line from the argument text.
7. Run task.done_cmd. If the next card reports a problem with the frame, fix the file and run task.done_cmd again.

## Argument
<!-- ub-argument:begin -->
Do not read anything under brainstorm/; it is not part of the codebase. Give every fact-finding sub-agent the same
rule.
The problem as I wrote it (Problem and Off-limits sections of my seeds file):
{{SEED_PROBLEM}}
Topic: {{TOPIC}}
Grill me on the PROBLEM ONLY: who has it, the job they are trying to get done, what success looks like, real
constraints, non-goals, and what has been tried. Do not propose solutions, example ideas or idea categories - not even
inside your recommended answers or multiple-choice options. Recommended answers are allowed only for constraints,
scope and timeline. Look facts up yourself and ask me only for decisions. At most {{ROUND_CAP}} rounds, then wait for
my confirmation.
(For the orchestrator, not the interview: variant {{VARIANT}}; strategy plan {{STRATEGY_MAP}}; privacy
{{PRIVACY_LINE}}.)
<!-- ub-argument:end -->
