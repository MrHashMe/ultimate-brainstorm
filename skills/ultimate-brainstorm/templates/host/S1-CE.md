<!-- ub-template: S1-CE v1 kind=host -->
# HOST TASK: strategy S1 with Compound Engineering ce-ideate (Stage 4)

Run it in the MAIN conversation, never in a sub-agent: ce-ideate is interactive, dispatches its own sub-agents and ends
with a menu. Card fields used below: run, runner, task.skill, task.argument_file, task.writes, task.done_cmd.

1. Read task.argument_file: it is the focus text for ce-ideate.
2. Tell the user, before starting: "ce-ideate may print its ranked survivors and ends with a menu. I will answer the
   menu for you; please do not read or react to its ranked list - your gut pick comes later, blind."
3. Invoke the skill named exactly as task.skill (for example `compound-engineering:ce-ideate`) with the focus text.
   Claude Code: the Skill tool. Codex: open ce-ideate's SKILL.md from your skills list and follow it with the same
   focus text (not available in the Codex IDE extension). Windows: ce-ideate creates its scratch folder with a POSIX
   shell snippet; run it where Git Bash (or WSL) is available.
4. At ce-ideate's final menu (Open / Brainstorm one idea / Discuss / Done), reply in free text: "Print the absolute
   paths of this run's ideation document and of its raw-candidates.md." Then reply `discard` (ce-ideate deletes the
   ideation document only if this run created it). If you keep the document instead, choose Done and decline the
   commit offer that follows inside a git repo.
5. Run: <runner> attach-s1 "<run>" --doc "<ideation document path>" --raw "<raw-candidates.md path>"
   (runner and run are the card fields). The engine copies both into pool/ and records the raw-candidates path.
6. If task.writes names a file ending in s1_seen.json, write {"human_saw_s1_ranking": true} when the ranked list was
   shown in the conversation, otherwise false.
7. Run task.done_cmd.
If ce-ideate is missing or fails, do not improvise ideas yourself: run task.done_cmd; the engine falls back to S1F.

## Argument
<!-- ub-argument:begin -->
{{HMW}} Treat {{RUN_DIR}}/01_FRAME.md as the directive brief (constraints, non-goals, axes). Do not read anything
else under brainstorm/. The folder brainstorm/ is not part of the codebase: exclude it from codebase scans and
grounding. Do not print the ranked list in chat; write it only to the file. output:md {{S1_DIALS}}
<!-- ub-argument:end -->
