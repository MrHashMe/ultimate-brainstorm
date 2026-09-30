# Where ultimate-brainstorm runs

A "host" is the agent you type the command into. The host shows you the questions and drives the pipeline; the model
calls themselves run as background processes, so a long run survives the host's command time limits.

## Status marks

| Mark | Meaning |
|---|---|
| OK | Documented by the vendor, and everything the kit uses is confirmed |
| OK* | Works through a documented path; a few details are not yet confirmed, and the kit has a fallback for each |
| MANUAL | You do one step in the app's settings |
| - | Not supported |

## Hosts

| Host | Windows | macOS | Linux / WSL | How the kit gets there | You type | Its own model family |
|---|---|---|---|---|---|---|
| Claude Code (terminal) | OK* | OK | OK | installer: native plugin (copy if older than 2.1.268) | `/ultimate-brainstorm <topic>` | claude (or glm / kimi through a launcher) |
| Claude Code desktop app / IDE | OK* | OK* | OK* | the same plugin | the same | the same |
| Codex CLI | OK* | OK | OK | installer: native plugin (0.156+), or a copy in `~/.agents/skills` | `$ultimate-brainstorm <topic>` | gpt (or glm / kimi through `CODEX_HOME`) |
| Codex app | OK* | OK* | - | the same | the same | gpt |
| Codex IDE extension | OK* | OK* | OK* | copy only (the extension has no plugins): install with `--agents codex --no-native` [U-31] | `$ultimate-brainstorm <topic>` | gpt |
| Kimi Code CLI 2.0+ | OK* (needs Git for Windows) | OK | OK | installer: copy to `~/.kimi-code/skills`, or MANUAL `/plugins install` | `/skill:ultimate-brainstorm <topic>` | kimi |
| ZCode desktop | OK* | OK* | OK* | installer: copy to `~/.zcode/skills`; the plugin screen is MANUAL | `$ultimate-brainstorm <topic>` | glm |
| Claude Code on GLM (`claude-glm`) | OK* | OK* | OK* | as Claude Code | `/ultimate-brainstorm <topic>` | glm |
| Codex on GLM (`codex-glm`) | OK* | OK* | OK* | the plugin is installed into that Codex home | `$ultimate-brainstorm <topic>` | glm |
| Claude Code on Kimi (`claude-kimi`) | OK* | OK* | OK* | as Claude Code | `/ultimate-brainstorm <topic>` | kimi |
| Codex on Kimi (`codex-kimi`) | OK* | OK* | OK* | the plugin is installed into that Codex home | `$ultimate-brainstorm <topic>` | kimi |
| Terminal only (`ub run`) | OK | OK | OK | installer (`~/.ultimate-brainstorm/bin/ub`) | `ub run "<topic>"` | none; it uses whatever families are set up |

Which model families can take part from each host: every host can call the Claude, Codex and Kimi CLIs you have
installed, plus GLM through Claude Code or Codex when `ZAI_API_KEY` is set - except from a Kimi Code host, where GLM
plan keys are never used (GLM then takes part only when it is the host family, or through the pay-as-you-go HTTP
route). See [FAMILIES.md](FAMILIES.md).

Codex IDE extension users: install with `install.py install --agents codex --no-native`; the extension cannot load
plugins, and the installer otherwise picks the native plugin whenever the Codex CLI is 0.156 or newer [U-31]. Claude
Code desktop / IDE and the Codex app without their CLI on PATH are detected by their settings folder and get the copy
route.

## Notes per host

### Claude Code

- Start `claude` in your project folder and type `/ultimate-brainstorm <topic>`.
- On Windows, Claude Code runs commands through Git Bash or its PowerShell tool; both work.
- Commands may run up to 10 minutes each. The kit waits at most 9 minutes per step and then checks again, so nothing
  times out.
- Interactive helpers (grilling, ce-ideate) run in your main conversation. Model jobs that must run inside Claude
  itself use fresh general-purpose sub-agents, never forks.
- Nested `claude -p` calls from inside a Claude Code session are checked once at the start of a run (a "PONG" test).
  If they do not work, the kit runs those jobs as sub-agents instead.

### Codex

- Start `codex` in your project folder and type `$ultimate-brainstorm <topic>`. If `$ultimate-brainstorm` is not
  recognized, check `/skills`: a plugin skill may be listed under a longer, namespaced name; use the name shown there.
  `doctor` prints what Codex reports.
- The kit starts other model CLIs, which need network access. Codex asks for permission the first time: choose to
  always allow the `ub` command for this session.
- On native Windows, Codex runs commands in PowerShell. Codex's command time limit on Windows is not documented, so the
  kit uses short waits (about 100 seconds) and continues in the background.
- If Codex stops background work before model calls finish, the kit tells you and offers the terminal route
  (`ub run --continue`).
- The Codex IDE extension is not tested yet; use the Codex CLI or app.

### Kimi Code

- Start `kimi` in your project folder and type `/skill:ultimate-brainstorm <topic>`.
- On Windows, Kimi Code needs Git for Windows (Git Bash) or `KIMI_SHELL_PATH` pointing to a bash.
- Approve the Bash command prefix once when Kimi asks.
- Commands may run up to 5 minutes; commands that take longer keep running in the background. The kit waits about
  4.5 minutes per step.
- The old `kimi-cli` 1.x (folder `~/.kimi`) is not supported. Upgrade: `npm install -g @moonshot-ai/kimi-code`, then
  `kimi migrate`.

### ZCode

- Open the project and type `$ultimate-brainstorm <topic>`.
- ZCode's own model family is GLM. Other families join when their CLIs are installed.
- ZCode's sub-agent and shell behavior with this kit is not confirmed yet. If ZCode has no sub-agent tool, jobs that
  need the host model run one by one and are marked PROVISIONAL.
- The kit never uses the command-line `zcode` tool.

### Claude Code or Codex on GLM or Kimi models

`install.py setup-glm --launcher --codex` and `install.py setup-kimi --launcher --codex` add launchers to
`~/.ultimate-brainstorm/bin/`:

| Launcher | What it starts |
|---|---|
| `claude-glm` (`.cmd`, `.ps1`) | Claude Code talking to Z.ai GLM, for this session only |
| `claude-kimi` (`.cmd`, `.ps1`) | Claude Code talking to Moonshot Kimi (or the Kimi Code membership endpoint with `--provider kimi-code`) |
| `codex-glm`, `codex-kimi` | Codex with its own settings folder (`~/.ultimate-brainstorm/codex-homes/glm` or `/kimi`) |
| `ub` (`.cmd`, `.ps1`) | the terminal mode |

Start them like this:

```
Git Bash / macOS / Linux:  ~/.ultimate-brainstorm/bin/claude-glm
PowerShell:                & "$HOME\.ultimate-brainstorm\bin\claude-glm.cmd"
cmd:                       %USERPROFILE%\.ultimate-brainstorm\bin\claude-glm.cmd
Codex on GLM:              ~/.ultimate-brainstorm/bin/codex-glm
            (PowerShell):  & "$HOME\.ultimate-brainstorm\bin\codex-glm.cmd"
```

In PowerShell prefer the `.cmd` launchers: the `.ps1` files run only when your execution policy allows local scripts
(`Get-ExecutionPolicy` shows RemoteSigned or Unrestricted). Use the `codex-glm` / `codex-kimi` launchers rather than
setting `CODEX_HOME` yourself: a `CODEX_HOME` set in a shell stays set for every later `codex` in that window, and the
launchers also check the key and tell the kit which family the host is.

Your normal `~/.claude/settings.json` and `~/.codex/config.toml` are never changed; the launchers pass their
settings for that one session. `claude-glm` and `claude-kimi` pick the endpoint and models from
`~/.ultimate-brainstorm/families.json` by the same rule as the pipeline's calls to that provider. Behind Z.ai or
Moonshot, Claude Code's own web search may not work, so the kit gives the research jobs to another family.
`setup-glm --zai-mcp` only adds Z.ai web tools to your interactive `claude-glm` session; the pipeline's research jobs
never use them [U-19].

### Terminal only

`~/.ultimate-brainstorm/bin/ub run "<topic>"` (PowerShell: `& "$HOME\.ultimate-brainstorm\bin\ub.cmd" run "<topic>"`)
runs the whole pipeline in a terminal and asks the questions there. The words after `run` are the topic; for text with
quotes, `$` or backticks, write it to a file and use `ub run --text-file <file>`. It has no time limits, so it is the
most robust choice for long unattended runs. Continue a stopped run with `ub run --continue`. While the terminal waits
for your answer it does not hold the run, so you can also answer from an agent; the terminal then does not apply its
own late answer and shows where the run is.

## Moving between hosts

All state lives in `brainstorm/<run>/`. You can start in Claude Code and type `continue` in Codex later (or the other
way round). The kit re-checks which model families are available; if one has disappeared, it gives that seat to
another family and notes it as PROVISIONAL in the run files. Jobs that have not run yet are rebuilt for the new seats.

One session drives a run at a time. A second session that runs a command meanwhile gets the card "another session is
driving this run" and retries by itself; nothing it asked for is lost. A host task (an interview, a batch of
sub-agent jobs) belongs to the session it was handed to; `continue` in another session, or `ub run --continue` in a
terminal, takes it over.
