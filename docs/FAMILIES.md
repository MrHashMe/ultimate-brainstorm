# Model families

A **model family** is one vendor's line of models: `claude` (Anthropic), `gpt` (OpenAI), `kimi` (Moonshot) and `glm`
(Zhipu / Z.ai). The pipeline gives each job (generating ideas, judging, checking, writing) to a family, and makes sure
judges from one family never decide alone about ideas from their own family.

- **One family** works. Every "other family" seat then uses the same vendor in a fresh context, and the results are
  marked PROVISIONAL (less protection against a model favoring its own ideas).
- **Two or more families** give real cross-family judging. Three is a good target.
- Your host agent counts as one family (Claude Code = claude, Codex = gpt, Kimi Code = kimi, ZCode = glm). The others
  join through their command-line tools or keys, as below.

Check what the kit sees at any time:

```
py -3 <kit>/install/install.py doctor --live       (macOS/Linux: python3 ...)
```

`--live` sends one tiny "Reply with PONG" call to each family, so you know logins and keys work before a long run.

## Summary

| Family | How the kit reaches it | What you need | Web search | Notes |
|---|---|---|---|---|
| claude | Claude Code CLI (`claude -p`) | a Claude Code login (Pro, Max, Team, Enterprise or Console), or `ANTHROPIC_API_KEY` | yes | the free claude.ai plan does not include Claude Code |
| gpt | Codex CLI (`codex exec`) | `codex login` (ChatGPT plan) or `OPENAI_API_KEY` | yes (checked by `doctor --live`; off if the probe finds no search) [U-5] | |
| kimi | Kimi Code CLI 2.0+ (`kimi -p`) | `kimi login` | off by default | Windows needs Git for Windows |
| kimi | Claude Code or Codex pointed at Moonshot | `KIMI_API_KEY` (Moonshot Platform) or `KIMI_CODE_API_KEY` (Kimi Code membership) | no | optional second route |
| glm | Claude Code or Codex pointed at Z.ai | `ZAI_API_KEY` (GLM Coding Plan) | no | see the plan rules below |
| glm | direct HTTP (off by default) | `ZAI_PAYG_API_KEY` (pay-as-you-go) | no | you switch it on yourself |

## GPT (Codex CLI)

```
npm install -g @openai/codex
codex login
```

Codex 0.156 or newer is recommended (the installer's native plugin route needs it). Usage counts against your ChatGPT
plan, or your OpenAI API account if you use a key. The kit calls Codex in a read-only sandbox, in an empty folder, with
no saved session.

## Claude (Claude Code CLI)

```
npm install -g @anthropic-ai/claude-code
claude          (run it once and sign in)
```

Claude Code 2.1.268 or newer is recommended. The kit calls `claude -p` with no tools (or only web search for research
jobs), no MCP servers, and no saved session. If your normal Claude Code is set up to talk to another provider (for
example a `~/.claude/settings.json` that points at Z.ai), the kit notices and counts that install as that provider's
family instead of `claude`; `doctor` shows this as "reclassified".

## Kimi (Kimi Code CLI)

```
npm install -g @moonshot-ai/kimi-code
kimi login
```

- On Windows, install Git for Windows first (Kimi Code runs its shell in Git Bash), or set `KIMI_SHELL_PATH`.
- Kimi Code CLI 2.0 or newer is required. The old `kimi-cli` 1.x (folder `~/.kimi`) is not supported:
  `npm install -g @moonshot-ai/kimi-code`, then `kimi migrate`.
- **The Kimi Code CLI ignores `KIMI_API_KEY`.** Setting that variable does not log the CLI in; use `kimi login`.
  (`KIMI_API_KEY` is only for the optional Claude Code / Codex route below.)
- Web search inside `kimi -p` is off by default, because it is not confirmed to work in that mode; research jobs go
  to a family with web search.
- The original Kimi K2 models are discontinued. Do not pin old `kimi-k2-*` model IDs in your overrides; the kit's
  defaults (`kimi-k3`, and `kimi-k2.7-code` for fast jobs) come from Moonshot's docs dated 2026-09-23.

### Optional: Kimi through Claude Code or Codex

With a Moonshot Platform key (`KIMI_API_KEY`) or a Kimi Code membership key (`KIMI_CODE_API_KEY`), the kit can also
reach Kimi models through Claude Code or Codex, and you can run those agents on Kimi models:

```
set the key first (see "Setting a key" below), then:
py -3 <kit>/install/install.py setup-kimi --launcher --codex                        (Platform key, KIMI_API_KEY)
py -3 <kit>/install/install.py setup-kimi --launcher --provider kimi-code           (membership key, KIMI_CODE_API_KEY)
```

- `--launcher` writes `claude-kimi` (and `.cmd`, `.ps1`) into `~/.ultimate-brainstorm/bin/`.
- `--codex` writes `~/.ultimate-brainstorm/codex-homes/kimi/config.toml` and `codex-kimi`, and installs the kit into
  that Codex home. It needs `KIMI_API_KEY`.
- `--region cn` exists only for `kimi-code` (`api.kimi.com/coding/`). A China endpoint for the Platform route is not
  documented by Moonshot, so the kit does not offer one.

## GLM (Z.ai)

GLM runs only through Claude Code or Codex, which Z.ai lists as supported tools for the GLM Coding Plan.

```
set ZAI_API_KEY (your Coding Plan key; see "Setting a key" below), then:
py -3 <kit>/install/install.py setup-glm --launcher --codex        (add --region cn for open.bigmodel.cn)
```

- `--launcher` writes `claude-glm` (and `.cmd`, `.ps1`): Claude Code on GLM, for that session only.
- `--codex` writes `~/.ultimate-brainstorm/codex-homes/glm/config.toml` and `codex-glm`, and installs the kit into that
  Codex home. Codex prints a warning about missing model metadata; that is expected.
- `--zai-mcp` makes `claude-glm` also load Z.ai's web search and web reader tools, for your own interactive session
  only (the pipeline's research jobs never use them [U-19]). Your key goes to Z.ai in a request header; on your machine
  it is written only to a temporary file that is deleted when the session ends.
- The kit also uses GLM as a family from other hosts (for example a Claude Code host calls `claude -p` pointed at Z.ai)
  whenever `ZAI_API_KEY` is set - except from a Kimi Code host, which never uses GLM plan keys.
- The Codex route's Z.ai endpoint for Coding Plan keys is not vendor-confirmed [U-33]: run `install.py doctor --live`
  once to confirm that Codex on GLM answers. `providers.glm.codex_base_url` in `~/.ultimate-brainstorm/families.json`
  overrides the URL without editing the kit.

**Plan rules.** The GLM Coding Plan may be used only in supported tools; this kit sends GLM traffic only through Claude
Code or Codex. Whether Z.ai counts script-launched Claude Code or Codex calls as supported-tool use is not confirmed.
If you want to be strict, add this to `~/.ultimate-brainstorm/families.json`:

```json
{"families": {"glm": {"allow_scripted_plan_use": false}}}
```

GLM then takes part only as your host's own model (for example inside `claude-glm` or ZCode), never through background
calls. The Kimi Code CLI is never used to carry GLM, and the Coding Plan key is never sent over plain HTTP.

**Pay-as-you-go.** A separate Z.ai pay-as-you-go key (`ZAI_PAYG_API_KEY`) can be used over direct HTTP. It is off by
default because its path is not confirmed yet. Switch it on only after checking it works:

```json
{"backends": {"openai-http@glm-payg": {"enabled": true}}}
```

## Launchers

| Launcher | Needs | Starts |
|---|---|---|
| `claude-glm` | `ZAI_API_KEY` | Claude Code on GLM |
| `claude-kimi` | `KIMI_API_KEY` (or `KIMI_CODE_API_KEY` if set up with `--provider kimi-code`) | Claude Code on Kimi |
| `codex-glm` | `ZAI_API_KEY` and `setup-glm --codex` | Codex on GLM |
| `codex-kimi` | `KIMI_API_KEY` and `setup-kimi --codex` | Codex on Kimi |
| `ub` | nothing | the terminal mode |

How they work: each launcher reads the key from your environment at start, writes the provider settings for that
session into a temporary file only you can read (`~/.ultimate-brainstorm/tmp/`), starts `claude --settings <file>` (or
`codex` with its own settings folder), and deletes the file when the session ends. Your own `~/.claude/settings.json`
and `~/.codex/config.toml` are never changed. A missing key stops the launcher with `Set <VAR> first`.

Start them from `~/.ultimate-brainstorm/bin/` (Git Bash, macOS, Linux), with `& "$HOME\.ultimate-brainstorm\bin\<name>.cmd"`
(PowerShell) or `%USERPROFILE%\.ultimate-brainstorm\bin\<name>.cmd` (cmd). The `.ps1` twins work in PowerShell only
when your execution policy allows local scripts (`Get-ExecutionPolicy` is RemoteSigned or Unrestricted). To type just the name, add
`~/.ultimate-brainstorm/bin` to your PATH yourself; the installer never edits PATH.

## Setting a key

Keys are read only from environment variables. The kit never stores them, never puts them on a command line, and
removes them from its logs.

```
PowerShell (permanent, for your user):  [Environment]::SetEnvironmentVariable("ZAI_API_KEY","<key>","User")
                                        then open a new terminal window
PowerShell (this window only):          $env:ZAI_API_KEY = "<key>"
bash / zsh:                             export ZAI_API_KEY=<key>      (put it in ~/.bashrc, ~/.zshrc or ~/.profile)
```

The same works for `KIMI_API_KEY`, `KIMI_CODE_API_KEY`, `ZAI_PAYG_API_KEY`, `OPENAI_API_KEY` and `ANTHROPIC_API_KEY`.

## Costs

A standard run makes about 75-110 model calls and uses about 1-2.5 million tokens in total, spread over the families
you have set up (quick: 25-40 calls; deep: 180-350). Most of it counts against your existing plans (Claude, ChatGPT,
Kimi, GLM Coding Plan). The first question of every run shows the estimate for your setup, and the run asks before it
goes over its call budget (quick 60, standard 180, deep 600, proposal 90). The kit shows dollar amounts only if you
add your own prices in `~/.ultimate-brainstorm/families.json`; the skill's `references/families.md` explains the format.

## Your own overrides

`~/.ultimate-brainstorm/families.json` is merged over the kit's defaults (`scripts/families.default.json`). Use it to
switch a backend on or off, pin a model, set a region, or add a family such as a local model reached over an
OpenAI-compatible HTTP endpoint. The skill's `references/families.md` has the full format and examples. `doctor`
shows the result.
