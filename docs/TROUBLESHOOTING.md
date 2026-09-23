# Troubleshooting

Start with `doctor`. Inside your agent, type the command followed by `doctor` (for example `/ultimate-brainstorm
doctor`). In a terminal:

```
py -3 <kit>/install/install.py doctor           (macOS/Linux: python3 ...)
py -3 <kit>/install/install.py doctor --live    (also tests each model family with one tiny call)
```

Every check prints PASS, WARN or FAIL with a fix. Nothing is changed by `doctor`.

A stopped run is never lost. After fixing the cause, type `continue` (for example `/ultimate-brainstorm continue`)
in any agent, or run `~/.ultimate-brainstorm/bin/ub run --continue` in a terminal.

## When the pipeline stops (BLOCKED)

When the pipeline cannot go on, it shows a short explanation and one or more fix commands. The common ones:

| What you see | Why | Fix |
|---|---|---|
| a family "not logged in", "auth" or "invalid api key" | a CLI login expired or a key is wrong | `codex login`, `kimi login`, or run `claude` once and sign in; check the key variable (see [FAMILIES.md](FAMILIES.md#setting-a-key)); then `continue`. The run can also go on without that family (marked PROVISIONAL) |
| "network" or "sandbox" errors from inside Codex | Codex's sandbox blocks the network for commands it starts | approve the `ub` command with "always" for this session when Codex asks, then `continue`. Or run the pipeline in a terminal: `ub run --continue` |
| "Your agent stops background work before model calls finish" | the host kills background processes (some IDE terminals and sandboxes do) | run it in a terminal: `<runner> run --continue "<run>"` (the card shows the exact line), or raise the agent's command timeout (see [HOSTS.md](HOSTS.md)) |
| "kimi 1.x" / "upgrade: npm install -g @moonshot-ai/kimi-code, then kimi migrate" | the old archived `kimi-cli` is installed | run exactly that; the old `~/.kimi` folder is then migrated |
| "run: kimi login" | Kimi Code is installed but not logged in | `kimi login`. Note: setting `KIMI_API_KEY` does not log the Kimi Code CLI in |
| Kimi fails on Windows / "bash not found" | Kimi Code needs Git Bash on Windows | install Git for Windows (`winget install Git.Git`), or set `KIMI_SHELL_PATH` to a bash.exe; restart Kimi |
| "budget" question (GB) or a BLOCKED budget card in full-auto | the run reached its call cap (quick 60, standard 180, deep 600, proposal 90) | answer the question with a higher number, or stop. In full-auto the card shows the command that raises the cap; then `continue` |
| "seed leak" | a prompt for an idea generator would have contained your own seed ideas (this protects the "human ideas first" rule) | usually caused by editing run files by hand; undo the edit or `redo` the step the card names |
| "origin label" | a judge prompt would have revealed where an idea came from | the same: undo manual edits, or `redo` the step |
| "not enough results" for a step (for example fewer than 3 of 5 idea strategies) | several families failed for the same step | fix the family (see the first rows), then `continue`; or `redo <step>` |
| a job "refused by policy" | the job would break your privacy answers or a vendor rule (for example the GLM Coding Plan over HTTP) | nothing is wrong with your setup; the card says which rule. Change the privacy answer only if you mean it |
| "another session is driving this run" | two agents are working on the same run folder | close one of them; the lock expires by itself after 2 minutes |
| "kit version differs" | the run was started with another kit version | usually fine; if something breaks, finish the run with the version that started it, or `redo` from a stage |
| the sign-off card lists lint FAILs or unresolved review findings | a generated architecture or proposal document still breaks a format rule after the automatic fix pass | they are also listed as open questions in the proposal. Reply `changes: <what to fix>` at sign-off, or `redo 12.14` to run the architecture fix pass again |

`status` (for example `/ultimate-brainstorm status`) shows where a run is. `PROGRESS.md` in the run folder always shows
the current stage, the next step and which families are OK.

## Installer and doctor messages

| Check | Meaning | Fix |
|---|---|---|
| "no supported agent detected" (exit 3) | none of Claude Code, Codex, Kimi Code or ZCode was found | install one: `install.py install --with-clis codex --login` (or `claude`, `kimi`), or name the agent you will install later with `--agents kimi` |
| "exists (v1, not owned)" | a v1 copy of the skill is in the way | `install.py install --migrate-v1` (it is backed up first) |
| "skip-not-owned" | a folder named `ultimate-brainstorm` was not created by the installer | check what it is; `--force` backs it up and replaces it |
| "backup+update" | you edited an installed file | nothing to do; your version is saved in `~/.ultimate-brainstorm/backups/` |
| "duplicate skill" (FAIL) | the same skill is in two folders one agent reads, for example both `~/.agents/skills` and `~/.codex/skills` | delete the older copy (usually `~/.codex/skills/<name>`); Codex would otherwise list it twice |
| "claude family reclassified as glm" (WARN) | your normal Claude Code is set up to talk to Z.ai (or Moonshot) | fine if intended: the kit counts it as that family. For real Claude models, set up GLM with `claude-glm` instead and restore `~/.claude/settings.json` |
| version below minimum (WARN) | an agent is older than the native plugin route needs (Claude Code 2.1.268, Codex 0.156) | update it (`npm install -g @anthropic-ai/claude-code` or `@openai/codex`); until then the copy route is used |
| Node older than 22.20 (WARN) | `npx skills` rows became manual | update Node, or run the printed manual commands |
| Compound Engineering row is "manual" | the kit could not read Claude Code's marketplace list | in a Claude Code session: `/plugin marketplace add EveryInc/compound-engineering-plugin` then `/plugin install compound-engineering` |
| "families" WARN | a model family is not available (not installed, not logged in, or no key) | follow the note next to it; `doctor --live` confirms the fix |
| stale backups (WARN) | backups older than 90 days | delete old folders in `~/.ultimate-brainstorm/backups/` if you do not need them |
| "re-run with --yes" | the installer had no terminal to ask you | run it again in a terminal, or add `--yes` |

## Windows notes

- **Python.** Use `py -3`. A plain `python` or `python3` may open the Microsoft Store instead (a stub in
  `...\WindowsApps\`). Install Python with `winget install Python.Python.3.12` if `py -3 --version` fails.
- **PowerShell will not run the `.ps1` launchers** ("running scripts is disabled on this system"): use the `.cmd`
  launcher instead (`%USERPROFILE%\.ultimate-brainstorm\bin\claude-glm.cmd`, which also works from PowerShell), or run
  the script with `powershell -ExecutionPolicy Bypass -File "$HOME\.ultimate-brainstorm\bin\claude-glm.ps1"`.
  Changing your execution policy is your decision; the kit never changes it.
- **Special characters.** The `claude`, `codex` and `kimi` commands installed by npm are `.cmd` files on Windows. The
  kit refuses arguments containing `" & | < > ^ % !` for them, because cmd.exe would misread them. Type such text
  inside the agent session instead of on the launcher's command line. Prompts never go on the command line, so runs
  are not affected.
- **Git Bash.** Kimi Code needs it; Claude Code can use it or its PowerShell tool; Codex uses PowerShell.
- **Encoding.** All kit files are UTF-8. If a terminal shows garbled characters, run `chcp 65001` in cmd, or in
  PowerShell 5.1: `$OutputEncoding = [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()`.
- **Long paths or antivirus.** If a copy or rename fails during install, run the installer again: it works in a
  temporary folder and swaps it in at the end, so a failed attempt leaves the old install intact.

## Codex notes

- `$ultimate-brainstorm` not found: open `/skills` and use the name listed there (plugin skills can appear with a
  namespace), or check `install.py list`. Restart Codex after installing.
- Codex asks for approval on every model call: choose "always" for the `ub` command prefix.

## Still stuck

Run `install.py doctor --json` and `ub doctor --json` (inside a run: `status`), and keep the run folder's
`logs/calls.jsonl`: it lists every model call with its result and error class, with keys removed.
