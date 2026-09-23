<!-- ub-template: HANDOFF-RUN v1 kind=host -->
# HOST TASK: start the downstream tool with the handoff seed (after Stage 14)

The run is decided; the seed file in the run folder carries the decision, the architecture and Milestone 0. Show the
user how to start the chosen tool in a FRESH session in the target repository (one spec owner per repository), and do
not start it in this session unless the user asks. Card fields used below: task.argument_file (the seed file).
Every seed ends with "Do not reopen the choice of idea or architecture."

- Compound Engineering (default for software and growth):
  Claude Code: /compound-engineering:ce-brainstorm <the seed text>, then choose "Create the implementation plan"
  (ce-plan). Codex: $ce-brainstorm <the seed text>. Kimi Code and ZCode: invoke ce-brainstorm from your skills list.
- Spec Kit (greenfield): in a shell, specify init <project> --integration <agent>; then in the agent
  /speckit.specify with the seed text (proposal sections 3 and 6-8 and the chosen/ architecture files).
- Superpowers (only when the repository already uses it): Claude Code /superpowers:brainstorming <the seed text>;
  Codex: pick Brainstorming in /skills and keep "Stop after the spec for my review" in the text (the Codex
  marketplace copy has no staged gate). In the plan header, the kill criteria go into Global Constraints and the
  "Fails if" list into Review Focus.
- OpenSpec (only when the repository already uses it): Claude Code /opsx:explore <the seed text>, then
  /opsx:propose <name>; Codex: $openspec-explore, then $openspec-propose.
- No tool: give the user the paths of PROPOSAL.md, ONE-PAGER.md and 10_ARCHITECTURE/README.md.
Milestone 0 (09_PROBE.md) runs first; do not plan beyond its kill criterion until its result is PASSED.
