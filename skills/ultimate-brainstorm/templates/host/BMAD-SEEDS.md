<!-- ub-template: BMAD-SEEDS v1 kind=host -->
# HOST TASK: human seeds with a BMAD brainstorming session (Stage 1, deep mode)

The point of this step is that the HUMAN produces ideas before any AI idea is visible. Run it in the MAIN
conversation, never in a sub-agent. Card fields used below: task.skill, task.argument_file, task.writes,
task.done_cmd.

1. Read task.argument_file (the kickoff answer for BMAD).
2. Invoke the skill named exactly as task.skill (for example `bmad-brainstorming`; Codex: `$bmad-brainstorming`),
   interactively. Its kickoff is one compound question (topic, goal, inputs): answer it with the argument text.
3. Choose the Facilitator stance (the AI supplies no ideas). Let the user pick 3-4 techniques. When a batch is spent it
   offers three paths (another batch, converge, wrap up): choose another batch or wrap up, never converge.
4. Import: copy every "(idea)" line (in Creative Partner mode: every "(idea by user)" line) of
   <output_folder>/brainstorming/brainstorm-<slug>-<date>/.memlog.md (output_folder defaults to _bmad-output) into the
   seeds file named in task.writes, under "## Ideas", one per line. Never import ideas marked "--by coach".
5. Run task.done_cmd.
If the skill is missing or the user prefers, skip the session: the user writes the seeds file alone instead, then run
task.done_cmd.

## Argument
<!-- ub-argument:begin -->
Topic: {{TOPIC}}
Goal: my own ideas, before any AI idea, for this problem:
{{SEED_PROBLEM}}
Inputs: none (Facilitator stance; do not supply ideas).
<!-- ub-argument:end -->
