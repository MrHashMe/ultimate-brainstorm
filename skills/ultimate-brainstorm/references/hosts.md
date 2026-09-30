# Hosts: where the skill runs and how to drive it

The same skill runs in every host. What differs: where it is installed, how it is invoked, how long one shell command
may run (W = the `--wait-s` value), how fresh sub-agents are started, and which approvals the host asks for. Unverified
behaviors carry their id from the kit spec (U-n) and have a fallback.

## Summary

| Host | Install location | Invocation | W | Shell timeout | Fresh sub-agents |
|---|---|---|---|---|---|
| Claude Code (CLI, desktop, IDE) | native plugin from the local marketplace `~/.ultimate-brainstorm/kit` (user scope); copy fallback `~/.claude/skills/ultimate-brainstorm` | `/ultimate-brainstorm <topic>` | 540 | Bash `timeout: 600000` (maximum 10 min) | Agent tool, `subagent_type: general-purpose`, never a fork |
| Codex (CLI, app) | native plugin (0.156+); copy fallback `~/.agents/skills/ultimate-brainstorm` | `$ultimate-brainstorm <topic>` (also `/skills`) [U-4] | 100 | `timeout_ms` 120000 or more where accepted [U-9] | "spawn one new agent per job with no conversation context" |
| Kimi Code CLI v2 | copy to `~/.kimi-code/skills/ultimate-brainstorm` (or `/plugins install`) | `/skill:ultimate-brainstorm <topic>` | 270 | Bash timeout 300000 (maximum 5 min; timed-out commands keep running in the background) | AgentSwarm or one Agent per job |
| ZCode | copy to `~/.zcode/skills/ultimate-brainstorm`; plugin UI manual [U-21] | `$ultimate-brainstorm <topic>` | 50 | default | its sub-agent tool; if none, run jobs yourself one by one (PROVISIONAL) |
| Terminal | `~/.ultimate-brainstorm/bin/ub` | `ub run "<topic>"` | none | none | not needed: every family runs headless |

## Claude Code

- Runner: `py -3 "KIT/scripts/ub.py"` (KIT = the skill folder, SKILL.md Setup) (Windows) or `python3 ...`; the first card's `runner` field is authoritative.
- Windows shell: Git Bash when installed, or the PowerShell tool. Both work because every free-text answer goes through
  an answer file, and the kickoff text through brainstorm/.kickoff.txt, never through quoting.
- Every UB call: one Bash call with `timeout: 600000` and `--wait-s 540`. If a call is cut off, just run it again.
- HOST_BATCH: templates/host/HOST-BATCH.md (the one source of the sub-agent task text): one Agent call per job,
  `general-purpose`, never a fork or `/subtask` (a fork inherits the whole conversation: seeds, pool, judge results).
- Interactive skills (grilling, domain-modeling, ce-ideate, bmad-*) run in the main conversation; non-fork sub-agents
  have no AskUserQuestion.
- The claude family nested from a Claude Code host: the adapter scrubs `CLAUDECODE` and `CLAUDE_CODE_CHILD_SESSION`
  and runs a preflight PING. If nested `claude -p` fails, the claude family's jobs come back as HOST_BATCH [U-14].
- Background sub-agents surface permission prompts in the main session. An allow rule such as `Edit(/brainstorm/**)`
  scopes write approvals to the run folder.

## Codex

- Nested model CLIs need network, which the default workspace-write sandbox blocks: approve the `ub` command prefix for
  the session ("always") when Codex asks, or run UB with escalated permissions. A sandbox network failure returns a
  BLOCKED card with this fix [U-8].
- Windows: Codex runs commands in PowerShell (unified exec is off by default on Windows). Use `py -3`.
- Shell command timeouts are short or unknown [U-9]: W=100, detached workers keep running, and re-running the command
  loses nothing. If Codex kills background workers repeatedly, the BLOCKED card offers the terminal route.
- HOST_BATCH: templates/host/HOST-BATCH.md: one new agent per job with no conversation context.
- The skill is explicit-only in Codex (`agents/openai.yaml` sets `allow_implicit_invocation: false`), because
  `codex exec` workers load the user's skills. Every worker prompt also starts with "Do not load or invoke any skill".
- Codex IDE extension: skills copy only, no plugins; unsupported until tested [U-31]. Use the CLI or the app.

## Kimi Code CLI v2

- Windows: Kimi needs Git for Windows (Git Bash) or `KIMI_SHELL_PATH`.
- Approve the Bash prefix for `ub` once.
- Bash commands time out at 5 minutes and keep running in the background: W=270.
- HOST_BATCH: templates/host/HOST-BATCH.md: AgentSwarm (its item variable is `{{item}}`) with the prompt files as
  `items`, or one Agent per job.
- Kimi Code ignores `KIMI_API_KEY`; sign in with `kimi login`. The legacy kimi-cli (version below 2.0) is not
  supported: `npm install -g @moonshot-ai/kimi-code`, then `kimi migrate`.
- AskUserQuestion is available for gates with 2-4 options.

## ZCode

- Copy route only; plugin marketplace UI steps are manual [U-21]. The headless zcode CLI is never used.
- Host family: glm. GLM seats run through `claude-cli@glm` or `codex-cli@glm` when installed with a key, otherwise as
  HOST_BATCH jobs in ZCode sub-agents.
- Sub-agent and shell behavior are unverified [U-21]: W=50; if no sub-agent tool exists, run each HOST_BATCH job
  yourself one by one, reading only its prompt file (the card notes mark those results PROVISIONAL).

## Launchers (Claude Code or Codex running GLM or Kimi models)

`install.py setup-glm --launcher [--codex]` and `setup-kimi --launcher [--codex]` write launchers into
`~/.ultimate-brainstorm/bin/`:

| Launcher | Runs | Host family |
|---|---|---|
| `claude-glm` (`.cmd`, `.ps1`) | `claude --settings <0600 temp file>` against the Z.ai Anthropic endpoint | glm |
| `claude-kimi` | `claude --settings ...` against Moonshot (or the Kimi Code membership endpoint) | kimi |
| `codex-glm` | `codex` with `CODEX_HOME=~/.ultimate-brainstorm/codex-homes/glm` | glm |
| `codex-kimi` | `codex` with `CODEX_HOME=~/.ultimate-brainstorm/codex-homes/kimi` | kimi |
| `ub` | the terminal driver | - |

Launchers set `UB_HOST_FAMILY`, so the engine knows the host family without reading settings [U-30]. The user's own
`~/.claude/settings.json` and `~/.codex/config.toml` are never touched. Behind Z.ai or Moonshot, Claude Code's web
search is not assumed [U-19]: research seats go to other families.

PowerShell: `& "$HOME\.ultimate-brainstorm\bin\claude-glm.cmd"` and `& "$HOME\.ultimate-brainstorm\bin\codex-glm.cmd"`
(the `.ps1` twins need an execution policy that allows local scripts). Prefer the launchers over setting `CODEX_HOME`
by hand: a shell-wide `CODEX_HOME` sends every later `codex` in that window to GLM.

## Terminal mode

`ub run "<topic>"` (the words after `run` are the topic; `--text-file F` reads it from a file), or
`ub run --continue "<run>"`, drives the same pipeline with no time limit and asks every gate on stdin: the gate text is
printed, the user types, an empty line ends the answer. While it waits it does not hold the run: another session may
answer or drive, and the terminal then applies its own answer only if the run did not change meanwhile. HOST steps use
their engine alternatives (express frame, S1F, no forge). A family that only the host could run is dropped
(PROVISIONAL). This is the most robust route for long unattended runs.
