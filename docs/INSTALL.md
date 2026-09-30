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
| Node.js 22.20+ and npm | installing the agent CLIs with npm (`--with-clis`) | the mattpocock skills no longer need Node: the installer copies them from a pinned commit archive |
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

The scripts download the release archive, check its SHA-256 and (when the GitHub CLI is signed in) its build
provenance, unpack it to a temporary folder, run `install/install.py` with your arguments, and clean up. The
installer first prints its plan (which agents were found, what goes where, and which steps you must do by hand) and
asks once before it changes anything. Anything after
`install` is passed on, for example `... | sh -s -- install --with-clis codex --login`. Leave out `install` (use
`sh -s -- plan`) to print only the plan.

To pin a version, replace `latest/download` with `download/v2.1.0`. Inspect first: download the script once, verify
it, read it, then run that same file.

```
curl -fsSLO https://github.com/MrHashMe/ultimate-brainstorm/releases/download/vX.Y.Z/install.sh
gh attestation verify install.sh --repo MrHashMe/ultimate-brainstorm --signer-workflow MrHashMe/ultimate-brainstorm/.github/workflows/release.yml --source-ref refs/tags/vX.Y.Z
less install.sh
sh install.sh install
```

PowerShell:

```
irm https://github.com/MrHashMe/ultimate-brainstorm/releases/download/vX.Y.Z/install.ps1 -OutFile install.ps1
gh attestation verify install.ps1 --repo MrHashMe/ultimate-brainstorm --signer-workflow MrHashMe/ultimate-brainstorm/.github/workflows/release.yml --source-ref refs/tags/vX.Y.Z
notepad install.ps1
powershell -ExecutionPolicy Bypass -File install.ps1 install
```

#### Release authenticity

Every asset of a release from 2.1.0 on (archives, `install.sh`, `install.ps1`, `SHA256SUMS`) carries a GitHub build
provenance attestation made by the release workflow. With the GitHub CLI installed and signed in, the shims and
`install.py update` check the archive before they run anything from it, and require the attestation to come from the
release workflow for that version's tag (a run of any other workflow in the repository could attest too):
`gh attestation verify ultimate-brainstorm-X.Y.Z.tar.gz --repo MrHashMe/ultimate-brainstorm --signer-workflow
MrHashMe/ultimate-brainstorm/.github/workflows/release.yml --source-ref refs/tags/vX.Y.Z --hostname github.com`.
They stop when the check fails. Without gh (or with a gh that is not signed in or too old for those flags) they print
a note and go on; add `--require-attestation` to make that an error. They ask only whether gh's active github.com
account is signed in (`gh auth status --active --hostname github.com`: a broken second account or enterprise host does
not skip the check), and a gh that cannot reach Sigstore's trust root (`error creating Sigstore verifier`, for example
behind a proxy) is a note too. When gh cannot reach GitHub or Sigstore from this machine, run the check by hand where
it can and install the checked archive's extracted folder with `install.py update --source DIR`. `install.py update`
also refuses an archive whose `VERSION` is not its tag's version, and a "latest" release older than 2.1.0 (the first
attested one); to install an older release, name it with `--tag`. Published releases are never replaced: a changed
build gets a new version.

### 2.2 From a git clone (or any local copy)

No pipe needed (PowerShell 5.1 has no `&&`; run the lines one by one):

```
git clone https://github.com/MrHashMe/ultimate-brainstorm
cd ultimate-brainstorm
PY install/install.py
PY install/install.py install --with-clis claude,codex,kimi --login
```

Use `git clone --depth 1 --branch v2.1.0 ...` for a fixed version. The same two commands work from any copy of the
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
| `--login` | run `codex login` and `kimi login` in the foreground (you finish them; with `--codex-home` / `--kimi-home` they sign in to that home), and print how to sign in to Claude |
| `--migrate-v1` | back up and replace an old v1 copy of the skill (see 2.6) |
| `--force` | back up and replace a folder the installer does not own (the whole folder, `.git` included) |
| `--routing-block` | add the brainstorming routing block (section 7) to your agents' instruction files |
| `--claude-config-dir DIR`, `--codex-home DIR`, `--kimi-home DIR` | non-default agent homes (the same as `CLAUDE_CONFIG_DIR`, `CODEX_HOME`, `KIMI_CODE_HOME`) |
| `--no-native` | use the copy route even where a native plugin route exists |
| `--backup-dir DIR` | where replaced files go (default `~/.ultimate-brainstorm/backups/`) |
| `--require-attestation` | a downloaded release must pass `gh attestation verify`; without it, a check that cannot run is only a note |

Exit codes: 0 ok (also "nothing to do"), 1 failure, 2 usage error, 3 no agent found, 4 blocked rows with `--yes`,
5 cancelled. `install.sh` and `install.ps1` pass on the same codes (the scriptblock one-liner sets `$LASTEXITCODE`);
their own failures (download, hash, provenance) are 1.

With `--with-clis`, the plan is made again once a CLI is installed (its agent now has rows too). With `--yes`, a
blocked row in that plan stops after the CLI rows (exit 4); interactively, a changed plan is shown and asked about
again.

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
| Claude Code | terminal | `claude plugin marketplace add MrHashMe/ultimate-brainstorm@v2.1.0` then `claude plugin install ultimate-brainstorm@ultimate-brainstorm --scope user` |
| Codex | terminal | `codex plugin marketplace add MrHashMe/ultimate-brainstorm@v2.1.0` then `codex plugin add ultimate-brainstorm@ultimate-brainstorm`, then restart Codex |
| Kimi Code | inside the app | `/plugins install https://github.com/MrHashMe/ultimate-brainstorm/releases/tag/v2.1.0` then `/reload` |
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

Every component source is pinned: mattpocock skills to a commit (`mattpocock/skills#<sha>`), Compound Engineering and
pm-skills to a release tag whose commit the installer checks when it can read the marketplace clone, spec-kit to a
commit, bmad and idea-reality to exact versions. claude-council has no release tag and is marked UNPINNED. `doctor`
warns (`stack.<skill>.drift`) when an installed component skill no longer matches what was installed, and
(`stack.<skill>.unpinned`) when a grilling or domain-modeling folder the installer did not install (for example one
kit 2.0.x installed unpinned) is not the pinned content.

### Core

**Compound Engineering** (pinned tag `compound-engineering-v3.28.2`): `ce-ideate` for the first idea strategy,
`ce-brainstorm` and `ce-plan` for the handoff.

| Agent | Commands the installer runs, or that you run by hand |
|---|---|
| Claude Code | `claude plugin marketplace add EveryInc/compound-engineering-plugin@compound-engineering-v3.28.2`, then `claude plugin install compound-engineering@<marketplace name> --scope user`. By hand in a session: `/plugin marketplace add EveryInc/compound-engineering-plugin@compound-engineering-v3.28.2` then `/plugin install compound-engineering` |
| Codex | `codex plugin marketplace add EveryInc/compound-engineering-plugin@compound-engineering-v3.28.2 --json`, then `codex plugin add compound-engineering@compound-engineering-plugin --json` |
| Kimi Code (by hand) | `/plugins install https://github.com/EveryInc/compound-engineering-plugin/releases/tag/compound-engineering-v3.28.2` then `/reload` |
| ZCode (by hand) | Settings > Plugins > add marketplace `EveryInc/compound-engineering-plugin` |

**mattpocock `grilling` + `domain-modeling`** (framing interview): the installer downloads
`https://codeload.github.com/mattpocock/skills/tar.gz/c55ee46073ed923f86ce59a5eb3b6d895095d1b7`, checks the content of
`skills/productivity/grilling` and `skills/engineering/domain-modeling` against the SHA-256 pins in
install/components.json, and copies the two folders (no npx, no Node). Where they go:

| Agent | Folder |
|---|---|
| Claude Code | `~/.claude/skills/` (or `$CLAUDE_CONFIG_DIR/skills/`) |
| Codex | `~/.agents/skills/` |
| Kimi Code | `~/.agents/skills/` (skipped when the Codex row installs them: Kimi reads that folder too) |
| ZCode | `~/.zcode/skills/` |

By hand: download that archive and copy the two folders there. A skill folder already present is kept as it is.
`UB_COMPONENTS_DIR=<folder>` makes the installer copy the archive (named
`mattpocock-skills-c55ee46073ed923f86ce59a5eb3b6d895095d1b7.tar.gz`) from that folder instead of downloading it,
also with `UB_INSTALL_OFFLINE=1` (an offline machine).

### Extras (only when you ask)

| Id | What | How |
|---|---|---|
| `pm-skills` | product discovery and experiments (tag v2.1.0) | Claude: `claude plugin marketplace add phuryn/pm-skills@v2.1.0`, `claude plugin install pm-product-discovery@pm-skills`, `claude plugin install pm-execution@pm-skills`. Codex: the same with `codex plugin marketplace add phuryn/pm-skills@v2.1.0 --json` and `codex plugin add ...@pm-skills --json` |
| `speckit` | Spec Kit handoff (v1.0.12) | `uv tool install specify-cli --from git+https://github.com/github/spec-kit.git@e77daa9021d20db26b878f7dfa5640fe5a42d04e` |
| `bmad` | deep-mode facilitation (6.12.0) | by hand: `npx bmad-method@6.12.0 install` (pick your tool; needs Node 20.12+, uv, Python 3.10+) |
| `claude-council` | extra council seats (UNPINNED) | by hand in Claude Code: `/plugin marketplace add hex/claude-marketplace` then `/plugin install claude-council`. This marketplace has no release tag; review it first |
| `idea-reality` | prior-art counts for developer tools (0.5.0) | by hand: `claude mcp add --env GITHUB_TOKEN=<token> --transport stdio idea-reality -- uvx idea-reality-mcp@0.5.0` |

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
PY ~/.ultimate-brainstorm/kit/install/install.py update --tag v2.1.0
```

From a git clone: `git pull`, then `PY install/install.py update`. `update` run from a kit copy (a clone, an unpacked
release) stages that copy; `PY <kit>/install/install.py update --source DIR` stages DIR instead.

It re-stages the kit, updates the native plugins, and updates the copies. A copied file you edited yourself is backed
up to `~/.ultimate-brainstorm/backups/<date>/` before it is replaced. The plan shows the version change
(`stage kit 2.0.3 -> 2.1.0`) and refuses a downgrade unless you add `--force`: every row that would take the older
kit is blocked, so nothing is applied. Run from the staged kit without `--source` (also through a symlink or junction
to UB_HOME), `update` re-stages the clone you installed from, or, when there is none (a kit installed by the bootstrap
script), fetches the latest release and checks its build provenance as described in 2.1.

While a brainstorm run has live workers (or a live `ub run` driver), `install` and `update` do not swap the kit under
them: the affected rows are blocked with the run's name. Wait for it, stop it (`ub stop <run>`), or pass `--force`.
A kit 2.0.x `ub run` session is named with its pid; `ub stop` does not end it: answer it or close it (Ctrl+C in its
terminal), then run the command again.
Only one installer applies changes at a time (`UB_HOME/install.lock`). Exit 4 also means the install changed after the
plan was made (another installer applied, or a run started under a tree the plan swaps): nothing was applied; run the
command again. An install that was cut short keeps its
records: the next `install` or `update` records the copies and plugins again and removes its leftover staging
folders.

## 9. Uninstall

```
PY <kit>/install/install.py uninstall         # asks once; --yes to skip the question
PY <kit>/install/install.py uninstall --purge # also removes ~/.ultimate-brainstorm (backups are kept)
```

It removes the native plugins it installed (a plugin you added yourself stays unless you add `--force`), the copies it
owns (only when their files are unchanged and you added nothing, such as a `.git` folder; `--force` backs such a copy
up first), the routing blocks, the launchers and the empty folders it created. It
keeps your run folders (`brainstorm/`) and backups; when an install replaced a folder of yours (`--force`,
`--migrate-v1`), it prints where that backup is. `--purge` deletes what the kit created in UB_HOME and keeps
`backups/` and anything else; it refuses a UB_HOME that holds no kit install. Codex's own data in the provider homes
(`codex-homes/<p>/`: sessions, history, logs; written when you use codex-glm / codex-kimi) is moved to
`backups/<time>/codex-homes/<p>/` instead of being deleted. If a plugin removal fails, `UB_HOME/kit` (the folder the
plugin loads from) is kept and the command exits 1; run uninstall again. Each plugin is removed from the agent home it
was installed in (for example the `--claude-config-dir` of that install), whatever flags you give uninstall. A
`--scope project` install whose project folder you deleted or moved still uninstalls: the kit's marketplace is
removed and a warning names the command to run in a moved project. When a plugin's CLI (claude, codex) is not on
PATH, uninstall prints the commands to remove the plugin by hand and keeps UB_HOME/kit (the plugin may still load from
it); run uninstall again once the CLI is back, or, if you no longer use that agent, `uninstall --purge`. Two steps
stay manual and are printed at the end:

- Kimi Code (if you installed the plugin there by hand): `/plugins remove ultimate-brainstorm`
- ZCode: remove the plugin in Settings > Plugins, if you added it there

Helper skills (Compound Engineering, mattpocock skills) are left installed. Remove Compound Engineering with your
agent's plugin commands if you want; uninstall lists the mattpocock skill folders the installer copied, which you can
delete by hand.

## 10. Check the install

```
PY <kit>/install/install.py doctor            # PASS / WARN / FAIL per check, each with a fix; exit 1 on any FAIL
PY <kit>/install/install.py doctor --live     # also sends one "Reply with PONG" call to each model family
PY <kit>/install/install.py list              # what is installed for which agent
```

Problems: [TROUBLESHOOTING.md](TROUBLESHOOTING.md). Which agent runs where: [HOSTS.md](HOSTS.md).
