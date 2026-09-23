# ultimate-brainstorm

## What it is

ultimate-brainstorm turns a topic, or an idea you already have, into three things: a decided idea, an architecture
package and a full project proposal. You write your own ideas first. Then several AI model families (Claude, GPT, Kimi,
GLM) generate more ideas in isolation, judge them fairly in both orders, check for existing products, and argue for and
against the best ones. You make every real decision. It works inside Claude Code, Codex, Kimi Code and ZCode, needs
about 7 short replies from you (standard mode, guided; full-auto needs none after a one-time privacy confirmation), and
keeps everything in files so you can stop and continue at any time.

```
 your ideas -> frame -> research -> 5 isolated idea strategies -> map -> screen -> prior-art checks
   -> tournament (both orders, several model families) -> red team -> YOU DECIDE -> probe
   -> competing architectures judged blind -> YOU CHOOSE -> cited proposal + one-pager + HTML pack -> handoff
```

The method behind it, with the research it rests on, is in [docs/GUIDE.md](docs/GUIDE.md). The raw research (the
prompt, the ranked landscape of 393 brainstorming tools and the full candidate list) is in [research/](research/).

## Install

You need Python 3.9 or newer and at least one of the agents: Claude Code, Codex, Kimi Code CLI 2.0+ or ZCode. There
are three ways to install. The installer is the easiest; it shows you a plan first and changes nothing until you say
yes.

### Route 1: the installer (recommended)

One line downloads the latest checked release from GitHub and runs the installer. It works from any machine.

macOS / Linux / WSL / Git Bash:

```sh
curl -fsSL https://github.com/MrHashMe/ultimate-brainstorm/releases/latest/download/install.sh | sh -s -- install
```

Windows PowerShell 5.1 or newer:

```powershell
& ([scriptblock]::Create((irm https://github.com/MrHashMe/ultimate-brainstorm/releases/latest/download/install.ps1))) install
```

Prefer git? Clone the repository and run the installer from the clone (PowerShell 5.1 has no `&&`, so run the lines
one by one; on macOS/Linux use `python3` instead of `python`):

```sh
git clone https://github.com/MrHashMe/ultimate-brainstorm
cd ultimate-brainstorm
python install/install.py            # prints the plan only
python install/install.py install    # applies it after one question
```

The installer always shows you a plan first (what goes where, for which agent) and changes nothing until you say yes.
Leave out `install` to see only the plan. It installs the kit for every agent it finds, plus the helper skills the
pipeline uses (Compound Engineering, and mattpocock `grilling` + `domain-modeling`). Add
`--with-clis claude,codex,kimi --login` to also install the agent command-line tools and sign in, for example
`... | sh -s -- install --with-clis codex --login`.

Prefer to read a script before running it? Open the URL in a browser, or use `curl -fsSL <url> | less` /
`irm <url> | more`. To pin a version, replace `latest/download` with `download/v2.0.2`.

Check everything at any time with `python ~/.ultimate-brainstorm/kit/install/install.py doctor` (Windows:
`py -3 "$HOME\.ultimate-brainstorm\kit\install\install.py" doctor`).

#### Update / uninstall

```sh
# macOS / Linux / Git Bash
python3 ~/.ultimate-brainstorm/kit/install/install.py update      # fetches the latest release and updates every agent
python3 ~/.ultimate-brainstorm/kit/install/install.py uninstall   # asks once; your brainstorm/ run folders are kept
```

```powershell
# Windows PowerShell
py -3 "$HOME\.ultimate-brainstorm\kit\install\install.py" update
py -3 "$HOME\.ultimate-brainstorm\kit\install\install.py" uninstall
```

Installed from a git clone? `git pull` in the clone, then `python install/install.py update`.

### Route 2: your agent's own plugin system (no installer)

| Agent | Commands |
|---|---|
| Claude Code (terminal) | `claude plugin marketplace add MrHashMe/ultimate-brainstorm@v2.0.2` then `claude plugin install ultimate-brainstorm@ultimate-brainstorm --scope user` |
| Codex (terminal) | `codex plugin marketplace add MrHashMe/ultimate-brainstorm@v2.0.2` then `codex plugin add ultimate-brainstorm@ultimate-brainstorm`, then restart Codex |
| Kimi Code (inside the app) | `/plugins install https://github.com/MrHashMe/ultimate-brainstorm/releases/tag/v2.0.2` then `/reload` |
| ZCode | Settings > Plugins > add a marketplace (this route is not yet confirmed; the installer's copy route is) |

With this route you add the helper skills yourself; the commands are in [docs/INSTALL.md](docs/INSTALL.md).

### Route 3: the universal skills installer

Needs Node 22.20 or newer:

```sh
DISABLE_TELEMETRY=1 npx -y skills@1.7.0 add MrHashMe/ultimate-brainstorm -g -a claude-code -a kimi-code-cli -a zcode --copy -y
```

This also covers Codex, because Codex reads the same `~/.agents/skills` folder. Do not add `-a codex -g`: that writes
an old folder and Codex would then list the skill twice. In PowerShell, set the variable first:
`$env:DISABLE_TELEMETRY = "1"`, then run the same `npx` line without the `DISABLE_TELEMETRY=1` prefix.

Full details, uninstall and every option: [docs/INSTALL.md](docs/INSTALL.md).

## Quickstart

Open your agent in the project folder and type one line:

| Agent | Type this |
|---|---|
| Claude Code | `/ultimate-brainstorm AI tutor for night-shift nurses` |
| Codex | `$ultimate-brainstorm AI tutor for night-shift nurses` (approve "always" for the `ub` command when asked) |
| Kimi Code | `/skill:ultimate-brainstorm AI tutor for night-shift nurses` (Windows: Git for Windows must be installed) |
| ZCode | `$ultimate-brainstorm AI tutor for night-shift nurses` |
| Claude Code on GLM | start `~/.ultimate-brainstorm/bin/claude-glm` (PowerShell: `& "$HOME\.ultimate-brainstorm\bin\claude-glm.cmd"`), then `/ultimate-brainstorm ...` |
| Codex on GLM | start `~/.ultimate-brainstorm/bin/codex-glm` (PowerShell: `& "$HOME\.ultimate-brainstorm\bin\codex-glm.cmd"`), then `$ultimate-brainstorm ...` |
| Claude Code or Codex on Kimi | start `claude-kimi` or `codex-kimi` from the same folder, then as above |
| Just a terminal | `~/.ultimate-brainstorm/bin/ub run "AI tutor for night-shift nurses"` (PowerShell: `& "$HOME\.ultimate-brainstorm\bin\ub.cmd" run "..."`) |

In PowerShell use the `.cmd` launchers: the `.ps1` twins run only when your execution policy allows local scripts
(`Get-ExecutionPolicy` is RemoteSigned or Unrestricted); Windows PowerShell's default policy blocks them.

Useful words to put before your topic:

- `quick <topic>` (about 30-50 minutes) or `deep <topic>` (most of a day); the default is `standard` (3-5 hours,
  mostly unattended)
- `proposal <my idea in one sentence>`: you already have the idea; it gets checked, red-teamed, designed and written up
- `software <feature>` (run it inside the repo), `product`, `growth`, `research`, `marketing`, `creative`, `naming`
- `full-auto <topic>`: no questions after a one-time privacy confirmation (the first full-auto run asks once and
  remembers the answer for later full-auto runs; change it with `ub config set privacy_defaults ...`, see
  [docs/PRIVACY.md](docs/PRIVACY.md)); the result is a draft only. Or `hands-on <topic>` (you confirm every step)
- `private <topic>`: nothing leaves your main agent's vendor, and no web search
- `continue`, `status`, `stop`, `doctor`, `probe passed <note>`, `switch architecture B`

You can close the agent at any time. Type `continue` later, in the same agent or a different one, and it picks up
where it stopped.

## Model families

The pipeline is fairer when two or more model families take part, because judges then never grade only their own
vendor's ideas. It works with one family too; results are then marked PROVISIONAL. Add any of these:

```
GPT (Codex CLI):       npm install -g @openai/codex        then  codex login
Claude (Claude Code):  npm install -g @anthropic-ai/claude-code   then run `claude` once and sign in
Kimi (Kimi Code CLI):  npm install -g @moonshot-ai/kimi-code  (Windows: install Git for Windows first)  then  kimi login
GLM (Z.ai):            set ZAI_API_KEY (your Coding Plan key), then:
                       py -3 <kit>/install/install.py setup-glm --launcher --codex   [--region cn]
Kimi via Claude Code or Codex (optional): set KIMI_API_KEY (Platform) or KIMI_CODE_API_KEY (membership), then
                       py -3 <kit>/install/install.py setup-kimi --launcher --codex [--provider kimi-code]
Check:                 py -3 <kit>/install/install.py doctor --live
```

On macOS and Linux use `python3` instead of `py -3`. Costs, plans, keys and the rules each vendor sets are explained in
[docs/FAMILIES.md](docs/FAMILIES.md). Which agents and systems are supported: [docs/HOSTS.md](docs/HOSTS.md).

## Privacy

- Your topic and ideas go to the model families you have set up, and to web search for research and prior-art checks.
- At the first question you can turn off web search, other vendors, or both. Type `private` to keep everything with
  your main agent's vendor.
- Code and file contents from your repo go only to your main agent's vendor unless you allow more.
- API keys are read from environment variables only; the kit never stores them and never puts them on a command line.
- No telemetry. Details: [docs/PRIVACY.md](docs/PRIVACY.md).

## What you get

Everything lands in `brainstorm/<date>-<topic>/` inside your project folder:

| File | What it is |
|---|---|
| `PROGRESS.md` | Where the run is, what is next, estimated time left |
| `00_HUMAN_SEEDS.md`, `01_FRAME.md` | Your own ideas, and the problem framed as questions and criteria |
| `03_POOL.md` | Every idea, deduplicated and mapped into clusters |
| `04_SHORTLIST.md`, `06_TOURNAMENT.md` | The screen and the both-order tournament, with bias audits |
| `07_REDTEAM.md`, `08_DECISION.md` | Arguments for and against the finalists, and your decision in your words |
| `09_PROBE.md` | The cheapest test of the riskiest assumption, written before anything is built |
| `10_ARCHITECTURE/README.md` | The chosen architecture: diagrams, decision records (ADRs), risks, stack, costs |
| `11_PROPOSAL/PROPOSAL.md` | The full proposal, with sources, assumptions and open questions |
| `11_PROPOSAL/ONE-PAGER.md` | A one-page summary |
| `11_PROPOSAL/index.html` | The whole proposal as one web page you can open, print or share |
| `12_HANDOFF.md` | What was handed to your planning or spec tool next |

## Troubleshooting

Run `doctor` first (inside the agent: type `doctor` after the command; in a terminal:
`py -3 <kit>/install/install.py doctor`). It says what is wrong and how to fix it. Common problems, Windows notes and
every message the pipeline can stop with are in [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md).

To remove the kit: `py -3 <kit>/install/install.py uninstall` (your run folders are kept). `<kit>` is your clone, or
`~/.ultimate-brainstorm/kit` after a one-line install.

## Credits

ultimate-brainstorm is MIT licensed ([LICENSE](LICENSE)). It builds on ideas, formats and research credited in
[NOTICE.md](NOTICE.md), including BMAD, pm-skills, Compound Engineering, MADR, arc42 and C4. Contributors: see
[AGENTS.md](AGENTS.md).
