# Installing ultimate-brainstorm

This page has every install command, per operating system. If you only want the short version, see the
[README](../README.md#install).

`<kit>` below means the folder that contains `install/install.py`: your clone of the repository, or the release
archive you unpacked. `PY` means your Python 3.9+ command:

| System | PY |
|---|---|
| Windows (PowerShell or cmd) | `py -3` (if that is missing: `python`, as long as `where python` does not point into `WindowsApps`) |
| Git Bash on Windows | `py -3` or `python` |
| macOS, Linux, WSL | `python3` |

No Python yet? Windows: `winget install Python.Python.3.12`. macOS: `brew install python`. Linux: your package manager.

## 1. What you need

| Item | Needed for | Notes |
|---|---|---|
| Python 3.9+ | everything | standard library only; nothing to `pip install` |
| At least one agent | running the pipeline | Claude Code 2.1.268+, Codex 0.156+, Kimi Code CLI 2.0+, or ZCode. The terminal mode (`ub run`) needs no agent, only model CLIs |
| Node.js 22.20+ and npx | the mattpocock skills (`npx skills`) and installing CLIs with npm | older Node: those rows become manual steps |
| Git for Windows (Git Bash) | Kimi Code on Windows | Kimi Code runs its shell tool in Git Bash |
| git | cloning; Kimi project scope | |

## 2. Route 1: the installer (recommended)

The installer is one Python file with no dependencies. By default it only prints a plan and writes nothing.

### 2.1 One line from GitHub (any machine)

macOS / Linux / WSL / Git Bash:

```sh
curl -fsSL https://github.com/MrHashMe/ultimate-brainstorm/releases/latest/download/install.sh | sh -s -- install
```

Windows PowerShell 5.1+:

```powershell
& ([scriptblock]::Create((irm https://github.com/MrHashMe/ultimate-brainstorm/releases/latest/download/install.ps1))) install
```

The scripts download the release archive, check its SHA-256, unpack it to a temporary folder, run
`install/install.py` with your arguments, and clean up. The installer first prints its plan (which agents were found,
what goes where, and which steps you must do by hand) and asks once before it changes anything. Anything after
`install` is passed on, for example `... | sh -s -- install --with-clis codex --login`. Leave out `install` (use
`sh -s -- plan`) to print only the plan.

To pin a version, replace `latest/download` with `download/v2.0.0`. Inspect first:

```
curl -fsSL https://github.com/MrHashMe/ultimate-brainstorm/releases/latest/download/install.sh | less
irm https://github.com/MrHashMe/ultimate-brainstorm/releases/latest/download/install.ps1 | more
```

### 2.2 From a git clone (or any local copy)

No pipe needed (PowerShell 5.1 has no `&&`; run the lines one by one):

```
git clone https://github.com/MrHashMe/ultimate-brainstorm
cd ultimate-brainstorm
PY install/install.py
PY install/install.py install --with-clis claude,codex,kimi --login
```

Use `git clone --depth 1 --branch v2.0.0 ...` for a fixed version. The same two commands work from any copy of the
kit: replace `install/install.py` with `<kit>/install/install.py`.

The first line prints the plan: which agents were found, what goes where, and which steps you must do by hand. The
second applies it after one confirmation. Leave out `--with-clis ... --login` if the CLIs are already installed and
signed in. Without a terminal to answer the question (for example in a script), add `--yes`; without it the installer
prints the plan, says "re-run with --yes" and exits.

If no agent is found, the installer exits with code 3 and prints how to install one (`--with-clis` does that for you).

### 2.3 What the installer does

1. Copies the kit to `~/.ultimate-brainstorm/kit/` (the "staged kit"; set `UB_HOME` to use another folder). Every agent
   then runs the same version.
2. Makes the skill visible to each agent, exactly once per agent:

   | Agent | How | Where |
   |---|---|---|
   | Claude Code 2.1.268+ | native plugin from the staged kit (`claude plugin marketplace add <UB_HOME>/kit`, then `claude plugin install ultimate-brainstorm@ultimate-brainstorm --scope user`) | Claude's plugin folder |
   | Claude Code, older or not installed yet | copy | `~/.claude/skills/ultimate-brainstorm` (or `$CLAUDE_CONFIG_DIR/skills`) |
   | Codex 0.156+ | native plugin from the staged kit (`codex plugin marketplace add <UB_HOME>/kit --json`, then `codex plugin add ultimate-brainstorm@ultimate-brainstorm --json`) | Codex's plugin folder |
   | Codex, older or not installed yet | copy | `~/.agents/skills/ultimate-brainstorm` |
   | Kimi Code 2.0+ | copy | `~/.kimi-code/skills/ultimate-brainstorm` (or `$KIMI_CODE_HOME/skills`); skipped when Kimi already sees the skill through a Kimi plugin or through `~/.agents/skills` |
   | ZCode | copy | `~/.zcode/skills/ultimate-brainstorm` |

   A skill folder the installer did not create (for example from `npx skills add`) is never duplicated: that agent
   gets the copy route and the folder is left alone unless you pass `--force` (it is backed up first). Claude Code
   desktop / IDE and the Codex app without their CLI on PATH get the copy route. Codex IDE extension users: install
   with `--agents codex --no-native` (the extension cannot load plugins) [U-31].

3. Installs the core helper skills (section 5) unless you pass `--components none`.
4. Writes the terminal launchers `ub`, `ub.cmd` and `ub.ps1` into `~/.ultimate-brainstorm/bin/`. It never edits your
   PATH; it prints how to add that folder if you want to.
5. Records every file it wrote, with a SHA-256 hash, in `~/.ultimate-brainstorm/install-manifest.json`, and puts a
   `.ub-owned` marker in every folder it created.

It never uses sudo or admin rights, refuses to run as root or from an elevated (administrator) Windows shell (unless
`UB_ALLOW_ROOT=1`), never reads or writes API key values, and never edits `settings.json`, `config.toml`, `CLAUDE.md`
or `AGENTS.md` unless you ask with a flag below. The routing block is added only to UTF-8 files (other encodings are
left alone and reported), and the file is backed up to `~/.ultimate-brainstorm/backups/` before every change.

### 2.4 Installer commands and options

```
install.py [plan] [--json]                 print the plan (default); writes nothing
install.py install [--yes] [--json]        plan -> one confirmation -> apply
install.py update  [--yes] [--json]        re-stage the kit and update every install
install.py uninstall [--yes] [--purge] [--json]
install.py doctor [--live] [--json]        health check; read-only
install.py list [--json]                   what is installed where
install.py setup-glm  [--region global|cn] [--launcher] [--codex] [--zai-mcp] [--yes]
install.py setup-kimi [--provider kimi|kimi-code] [--region global|cn] [--launcher] [--codex] [--yes]
install.py version
```

| Option | Meaning |
|---|---|
| `--agents auto` or `--agents claude-code,codex,kimi,zcode` | which agents to install for (default: every one found). Naming an agent that is not installed yet uses the copy route, so it works once you install the agent |
| `--scope user` or `--scope project --project-dir DIR` | install for you (default) or only for one project (see 2.5) |
| `--source DIR` or `--source github`, `--tag vX.Y.Z` | where the kit comes from (default: the folder that holds `install.py`) |
| `--components core`, `none`, or `core,+pm-skills,...` | helper skills to add (section 5) |
| `--with-clis claude,codex,kimi` | also install these CLIs with `npm install -g` (after confirmation) |
| `--login` | run `codex login` and `kimi login` in the foreground (you finish them), and print how to sign in to Claude |
| `--migrate-v1` | back up and replace an old v1 copy of the skill (see 2.6) |
| `--force` | back up and replace a folder the installer does not own |
| `--routing-block` | add the brainstorming routing block (section 7) to your agents' instruction files |
| `--claude-config-dir DIR`, `--codex-home DIR`, `--kimi-home DIR` | non-default agent homes (the same as `CLAUDE_CONFIG_DIR`, `CODEX_HOME`, `KIMI_CODE_HOME`) |
| `--no-native` | use the copy route even where a native plugin route exists |
| `--backup-dir DIR` | where replaced files go (default `~/.ultimate-brainstorm/backups/`) |

Exit codes: 0 ok (also "nothing to do"), 1 failure, 2 usage error, 3 no agent found, 4 blocked rows with `--yes`,
5 cancelled.

### 2.5 Only for one project

```
py -3 <kit>/install/install.py install --scope project --project-dir C:\path\to\project
```

- Claude Code is installed with `--scope local` (never `project`, which would change the shared, tracked
  `.claude/settings.json`).
- Codex and Kimi get a copy in `<project>/.agents/skills/`; ZCode in `<project>/.zcode/skills/`.
- Kimi finds the project root through a `.git` folder. If the project has none, the plan warns you and offers
  `--git-init`.

### 2.6 Coming from v1

If you copied the v1 skill by hand (for example into `~/.claude/skills/ultimate-brainstorm`), the plan shows it as
`migrate-v1`. Add `--migrate-v1` (or answer yes) and the installer backs it up to `~/.ultimate-brainstorm/backups/`
and replaces it. Your v1 run folders keep working: `continue` upgrades them.

## 3. Route 2: native plugin systems, without the installer

| Agent | Where | Commands |
|---|---|---|
| Claude Code | terminal | `claude plugin marketplace add MrHashMe/ultimate-brainstorm@v2.0.0` then `claude plugin install ultimate-brainstorm@ultimate-brainstorm --scope user` |
| Codex | terminal | `codex plugin marketplace add MrHashMe/ultimate-brainstorm@v2.0.0` then `codex plugin add ultimate-brainstorm@ultimate-brainstorm`, then restart Codex |
| Kimi Code | inside the app | `/plugins install https://github.com/MrHashMe/ultimate-brainstorm/releases/tag/v2.0.0` then `/reload` |
| ZCode | app | Settings > Plugins > add a marketplace or local directory. Not yet confirmed for this kit; the installer's copy route is |

Then add the helper skills with the commands in section 5, and the terminal launcher is not installed (use the
installer's `install` later if you want `ub run`).

## 4. Route 3: the universal skills installer

Needs Node 22.20+. Git Bash / macOS / Linux:

```sh
DISABLE_TELEMETRY=1 npx -y skills@1.7.0 add MrHashMe/ultimate-brainstorm -g -a claude-code -a kimi-code-cli -a zcode --copy -y
```

PowerShell:

```powershell
$env:DISABLE_TELEMETRY = "1"
npx -y skills@1.7.0 add MrHashMe/ultimate-brainstorm -g -a claude-code -a kimi-code-cli -a zcode --copy -y
```

- Kimi's global target is `~/.agents/skills`, which Codex also reads, so Codex is covered.
- Never add `-a codex -g`: it writes the old `~/.codex/skills` folder and Codex would then list the skill twice.

## 5. Helper skills (components)

The pipeline works without them and uses built-in alternatives. With them, framing and idea generation are better.
The installer adds the core set by default; `--components none` skips it; `--components core,+pm-skills` adds extras.

### Core

**Compound Engineering** (pinned tag `compound-engineering-v3.28.2`): `ce-ideate` for the first idea strategy,
`ce-brainstorm` and `ce-plan` for the handoff.

| Agent | Commands the installer runs, or that you run by hand |
|---|---|
| Claude Code | `claude plugin marketplace add EveryInc/compound-engineering-plugin@compound-engineering-v3.28.2`, then `claude plugin install compound-engineering@<marketplace name> --scope user`. By hand in a session: `/plugin marketplace add EveryInc/compound-engineering-plugin` then `/plugin install compound-engineering` |
| Codex | `codex plugin marketplace add EveryInc/compound-engineering-plugin@compound-engineering-v3.28.2 --json`, then `codex plugin add compound-engineering@compound-engineering-plugin --json` |
| Kimi Code (by hand) | `/plugins install https://github.com/EveryInc/compound-engineering-plugin/releases/tag/compound-engineering-v3.28.2` then `/reload` |
| ZCode (by hand) | Settings > Plugins > add marketplace `EveryInc/compound-engineering-plugin` |

**mattpocock `grilling` + `domain-modeling`** (framing interview; needs Node 22.20+; the installer sets
`DISABLE_TELEMETRY=1`):

| Agent | Command |
|---|---|
| Claude Code | `npx -y skills@1.7.0 add mattpocock/skills --skill grilling --skill domain-modeling -g -a claude-code --copy -y` |
| Codex | run from your home folder, without `-g`: `cd ~; npx -y skills@1.7.0 add mattpocock/skills --skill grilling --skill domain-modeling -a codex -y` (lands in `~/.agents/skills`) |
| Kimi Code | `npx -y skills@1.7.0 add mattpocock/skills --skill grilling --skill domain-modeling -g -a kimi-code-cli --copy -y` (skipped when the Codex line already ran: Kimi reads `~/.agents/skills` too) |
| ZCode | `npx -y skills@1.7.0 add mattpocock/skills --skill grilling --skill domain-modeling -g -a zcode --copy -y` |

### Extras (only when you ask)

| Id | What | How |
|---|---|---|
| `pm-skills` | product discovery and experiments | Claude: `claude plugin marketplace add phuryn/pm-skills`, `claude plugin install pm-product-discovery@pm-skills`, `claude plugin install pm-execution@pm-skills`. Codex: the same with `codex plugin marketplace add phuryn/pm-skills --json` and `codex plugin add ...@pm-skills --json` |
| `speckit` | Spec Kit handoff | `uv tool install specify-cli` |
| `bmad` | deep-mode facilitation | by hand: `npx bmad-method install` (pick your tool; needs Node 20.12+, uv, Python 3.10+) |
| `claude-council` | extra council seats | by hand in Claude Code: `/plugin marketplace add hex/claude-marketplace` then `/plugin install claude-council` |
| `idea-reality` | prior-art counts for developer tools | by hand: `claude mcp add --env GITHUB_TOKEN=<token> --transport stdio idea-reality -- uvx idea-reality-mcp` |

## 6. CLIs and model families

The installer can install and sign in the CLIs for you (`--with-clis claude,codex,kimi --login`). By hand:

```
GPT (Codex CLI):       npm install -g @openai/codex        then  codex login
Claude (Claude Code):  npm install -g @anthropic-ai/claude-code   then run `claude` once and sign in
Kimi (Kimi Code CLI):  npm install -g @moonshot-ai/kimi-code  (Windows: install Git for Windows first)  then  kimi login
GLM (Z.ai):            set ZAI_API_KEY (Coding Plan key), then:
                       PY <kit>/install/install.py setup-glm --launcher --codex   [--region cn]
Kimi via Claude Code or Codex (optional): set KIMI_API_KEY (Platform) or KIMI_CODE_API_KEY (membership), then
                       PY <kit>/install/install.py setup-kimi --launcher --codex [--provider kimi-code]
Check:                 PY <kit>/install/install.py doctor --live
```

Setting a key permanently:

```
PowerShell: [Environment]::SetEnvironmentVariable("ZAI_API_KEY","<key>","User")    (then open a new window)
bash/zsh:   export ZAI_API_KEY=<key>    in your ~/.bashrc, ~/.zshrc or ~/.profile
```

What `setup-glm` and `setup-kimi` write, and what each family costs: [FAMILIES.md](FAMILIES.md).

## 7. Optional: the routing block

With `--routing-block`, the installer adds this block (between `<!-- ultimate-brainstorm:begin -->` and
`<!-- ultimate-brainstorm:end -->` markers) to `~/.claude/CLAUDE.md`, `~/.codex/AGENTS.md`, `~/.kimi-code/AGENTS.md`
and `~/.zcode/AGENTS.md`, for the agents it found. It makes brainstorming requests go to this kit instead of other
brainstorming skills. `uninstall` removes it again. The block text is in the skill's `references/install.md`.

## 8. Update

After a one-line install, the kit lives in `~/.ultimate-brainstorm/kit` (or `$UB_HOME/kit`):

```
PY ~/.ultimate-brainstorm/kit/install/install.py update          # fetches the latest GitHub release
PY ~/.ultimate-brainstorm/kit/install/install.py update --tag v2.0.1
```

From a git clone: `git pull`, then `PY install/install.py update`. From any other copy: `PY <kit>/install/install.py
update --source DIR`.

It re-stages the kit, updates the native plugins, and updates the copies. A copied file you edited yourself is backed
up to `~/.ultimate-brainstorm/backups/<date>/` before it is replaced. The plan shows the version change
(`stage kit 2.0.1 -> 2.0.2`) and refuses a downgrade unless you add `--force`. Run from the staged kit without
`--source`, `update` fetches the latest release (a kit installed by the bootstrap script has no local source).

## 9. Uninstall

```
PY <kit>/install/install.py uninstall         # asks once; --yes to skip the question
PY <kit>/install/install.py uninstall --purge # also removes ~/.ultimate-brainstorm (backups are kept)
```

It removes the native plugins it installed (a plugin you added yourself stays unless you add `--force`), the copies it
owns (only when their files are unchanged), the routing blocks, the launchers and the empty folders it created. It
keeps your run folders (`brainstorm/`) and backups; when an install replaced a folder of yours (`--force`,
`--migrate-v1`), it prints where that backup is. `--purge` deletes only what the kit creates in UB_HOME and refuses a
UB_HOME that holds no kit install. Two steps stay manual and are printed at the end:

- Kimi Code (if you installed the plugin there by hand): `/plugins remove ultimate-brainstorm`
- ZCode: remove the plugin in Settings > Plugins, if you added it there

Helper skills (Compound Engineering, mattpocock skills) are left installed; remove them with their own tools if you
want.

## 10. Check the install

```
PY <kit>/install/install.py doctor            # PASS / WARN / FAIL per check, each with a fix; exit 1 on any FAIL
PY <kit>/install/install.py doctor --live     # also sends one "Reply with PONG" call to each model family
PY <kit>/install/install.py list              # what is installed for which agent
```

Problems: [TROUBLESHOOTING.md](TROUBLESHOOTING.md). Which agent runs where: [HOSTS.md](HOSTS.md).
