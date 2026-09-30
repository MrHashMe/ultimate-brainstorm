<!-- ub-template: HOST-BATCH v1 kind=host -->
# HOST TASK: run model jobs in fresh sub-agents (HOST_BATCH cards)

A HOST_BATCH card lists jobs that only you (the host) can run, because their model family is your own family and no
headless route to it exists. Each job is one isolated model call: its sub-agent must see nothing but its prompt file.
Card fields used below: jobs[] (id, prompt_file, out, tools), then.

For EVERY job, start ONE FRESH sub-agent and give it exactly this task text, with the two paths filled in:
  Read <prompt_file> and follow it exactly. Write only the requested output to <out>. Reply with one line.

Per host:
- Claude Code: the Agent tool with subagent_type "general-purpose"; never the fork type, never /subtask (a fork
  inherits the whole conversation). Independent jobs may run at the same time.
- Codex: "Spawn one new agent per job, with no conversation context. Each reads its prompt file, writes its output
  file and replies with one line."
- Kimi Code: AgentSwarm with items = the prompt files and prompt_template "Read ITEM and follow it exactly.", where
  ITEM is AgentSwarm's item variable (the word item inside double curly braces); or one Agent per job with the task
  text above.
- ZCode and others: your sub-agent tool, one fresh sub-agent per job. If you have none, run each job yourself, one by
  one, reading only its prompt file; tell the user these results are PROVISIONAL.

Rules:
- Never paste pool files, seeds, other jobs' outputs or judge results into a sub-agent's task; the prompt file is
  complete.
- Give a sub-agent web tools only when the job's tools field includes "web".
- Do not read or summarize the outputs yourself; do not show them to the user.
- Wait until every job has replied, then run the card's then command. Missing or failed outputs are handled by the
  engine.
