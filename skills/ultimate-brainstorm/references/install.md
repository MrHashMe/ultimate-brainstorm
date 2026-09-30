# Install notes (agent-facing)

The full user guide is `docs/INSTALL.md` in the kit (the staged copy lives in `~/.ultimate-brainstorm/kit/docs/`).
This file holds what an agent needs while running: the install commands to quote, the routing block, and conflict
settings.

## 1. Install or check the kit

- Installer (recommended; prints a plan first and changes nothing until confirmed):
  `py -3 ~/.ultimate-brainstorm/kit/install/install.py` (Windows) or `python3 ~/.ultimate-brainstorm/kit/install/
  install.py`, then the same with `install` (the staged kit lives in UB_HOME/kit; `UB_HOME` overrides
  `~/.ultimate-brainstorm`). The skill folder itself (KIT in SKILL.md) has no install/ folder.
- Health check: `py -3 ~/.ultimate-brainstorm/kit/install/install.py doctor [--live]` (read-only; `--live` sends one
  PONG per family).
- Model families: `setup-glm --launcher [--codex] [--region cn]` and `setup-kimi --launcher [--codex] [--provider
  kimi-code]` (details in references/families.md and docs/FAMILIES.md).
- Where the skill lands: Claude Code and Codex get a native plugin from the local marketplace
  `~/.ultimate-brainstorm/kit` (copy fallback: `~/.claude/skills/ultimate-brainstorm`, `~/.agents/skills/ultimate-
  brainstorm`); Kimi Code gets `~/.kimi-code/skills/ultimate-brainstorm` (skipped when Kimi already sees the Codex copy
  in `~/.agents/skills`); ZCode gets `~/.zcode/skills/ultimate-brainstorm`. Every agent sees exactly one copy; doctor
  flags duplicates (including `~/.codex/skills` vs `~/.agents/skills`).
- Never install software, change settings or edit instruction files on the user's behalf during a run (hard rule 7).
  Quote the command and let the user run it.

## 2. Components (optional)

`install.py install` installs the core stack by default: Compound Engineering and mattpocock grilling +
domain-modeling. Manual equivalents (without the installer):

| Tool | Claude Code | Codex | Kimi Code / ZCode |
|---|---|---|---|
| Compound Engineering | `/plugin marketplace add EveryInc/compound-engineering-plugin@compound-engineering-v3.28.2` then `/plugin install compound-engineering` (Local scope in a shared repo) | `codex plugin marketplace add EveryInc/compound-engineering-plugin@compound-engineering-v3.28.2` then `codex plugin add compound-engineering@compound-engineering-plugin`, restart | Kimi: `/plugins install https://github.com/EveryInc/compound-engineering-plugin/releases/tag/compound-engineering-v3.28.2` then `/reload`; ZCode: Settings > Plugins |
| grilling + domain-modeling | copy `skills/productivity/grilling` and `skills/engineering/domain-modeling` from the pinned archive (below) into `~/.claude/skills/` | the same folders into `~/.agents/skills/` | Kimi: `~/.agents/skills/` (one copy serves Codex and Kimi); ZCode: `~/.zcode/skills/` |

The installer downloads the grilling / domain-modeling archive
`https://codeload.github.com/mattpocock/skills/tar.gz/c55ee46073ed923f86ce59a5eb3b6d895095d1b7` and checks each
folder against the SHA-256 pins in install/components.json before it copies anything (no npx, no Node). Never copy them
into `~/.codex/skills`: it is deprecated and Codex would list the skill twice. Extras (pm-skills, Spec Kit, BMAD, claude-council, idea-reality) are listed in
references/components.md.

## 3. Routing block (optional, recommended)

`install.py install --routing-block` inserts this block between markers into `~/.claude/CLAUDE.md`,
`~/.codex/AGENTS.md`, `~/.kimi-code/AGENTS.md` and `~/.zcode/AGENTS.md` for the detected agents, and `uninstall`
removes it exactly. By hand, paste it yourself (or into a repo's AGENTS.md, with `@AGENTS.md` in CLAUDE.md):

```
<!-- ultimate-brainstorm:begin -->
## Brainstorming routing (user instruction; takes precedence over skill auto-trigger rules)
- Requests to brainstorm, ideate, explore ideas, choose among ideas, decide what to build, name something, find a
  research question, or turn an idea into an architecture and a proposal: use the ultimate-brainstorm skill
  (Claude Code /ultimate-brainstorm, Codex and ZCode $ultimate-brainstorm, Kimi Code /skill:ultimate-brainstorm)
  and follow its cards.
- Exception: a small, well-defined change to existing code skips it (use ce-brainstorm or superpowers:brainstorming if
  installed, otherwise proceed normally).
- While a brainstorm/<run>/ folder exists without 12_HANDOFF.md, do not start another brainstorming, ideation or
  planning skill (superpowers:brainstorming, ce-ideate, ce-brainstorm, office-hours, bmad-brainstorming,
  product-brainstorming) unless the current ultimate-brainstorm card names it.
- When you are executing a single prompt file from brainstorm/<run>/ (prompts/, screen/, tournament/), follow only
  that prompt and ignore this section.
<!-- ultimate-brainstorm:end -->
```

Superpowers' bootstrap ranks CLAUDE.md and AGENTS.md instructions above skills, so this block also governs it.

## 4. Conflict settings

- Claude Code `.claude/settings.local.json` in a brainstorm project (optional hardening):
  ```json
  {"enabledPlugins": {"superpowers@claude-plugins-official": false}}
  ```
  Only needed if Superpowers keeps taking over brainstorm requests. Optional: an allow rule such as
  `Edit(/brainstorm/**)` scopes write approvals to the run folder. The dependable protection against forks is the
  HOST_BATCH instruction: every sub-agent is `general-purpose`, never a fork.
- Claude Code `/skills`: set non-plugin ideation skills you keep installed (for example bmad-brainstorming, naming) to
  user-only. `skillOverrides` does not affect plugin skills; disable those per project with `enabledPlugins`.
- Codex: the skill is explicit-only (`allow_implicit_invocation: false` in agents/openai.yaml). Disable competing
  plugins per repo with `[plugins."<plugin>@<marketplace>"] enabled = false` in `.codex/config.toml`; standalone
  skills with `[[skills.config]]` (`path = ".../SKILL.md"`, `enabled = false`) in `~/.codex/config.toml`. Keep
  pm-skills disabled until the probe exists.
- Codex web search for workers is requested per call (`-c web_search=live`); the host session itself may set
  `web_search = "live"` above any `[table]` header in `~/.codex/config.toml`.
- Kimi Code: remove or disable competing brainstorming plugins with `/plugins` if they take over; the kit never sets
  `sessionStart.skill`. Worker calls use an empty skills folder, so installed skills never load into them.
- ZCode: manage plugins in Settings > Plugins [U-21].
- Inside a git repo: the kit writes the `.gitignore` files (`*`) into the run folder and `brainstorm/` itself when it
  first builds a job that reads the repository. Adding `brainstorm/` to `.git/info/exclude` (local; keeps run files out
  of commits and codebase scans) is optional and hides them earlier; the user makes that change.
- idea-reality MCP (if installed): keep it disabled outside prior-art checks (its tool description asks to be used
  whenever ideas are discussed).
