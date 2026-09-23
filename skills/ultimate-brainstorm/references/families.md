# Model families, backends and seats

Model diversity de-biases judging; strategy diversity drives idea diversity. The kit therefore runs different
strategies in isolated calls and spreads judge, checker, reviewer and architect seats across model families. This file
replaces the family part of v1 tools.md.

## 1. Families, backends, seats

- A **family** is a model vendor line: `claude` (anthropic), `gpt` (openai), `kimi` (moonshot), `glm` (zhipu).
- A **backend** is how a family is reached. The family is decided by the endpoint, not by the binary: `claude -p`
  against api.z.ai is the `glm` family.
- A **seat** is a role in the pipeline (generator S3, screen judge, checker, architecture author, ...). The engine
  assigns seats deterministically and stores them in run.json (`seats`).
- `<family>-alt` means the same vendor with an alternate model (`alt_model`) or the same model in a fresh context. It
  is always PROVISIONAL.

| Family | Backends in chain order | Needs | Web |
|---|---|---|---|
| claude | claude-cli, anthropic-http | Claude Code login (or ANTHROPIC_API_KEY for HTTP) | yes |
| gpt | codex-cli, openai-http | `codex login` (or OPENAI_API_KEY for HTTP) | yes (`-c web_search=live`) [U-5] |
| kimi | kimi-cli, claude-cli@kimi, claude-cli@kimi-code, codex-cli@kimi, openai-http@kimi | Kimi Code CLI v2 + `kimi login`; or KIMI_API_KEY / KIMI_CODE_API_KEY for the provider routes | kimi-cli off by default [U-3] |
| glm | claude-cli@glm, codex-cli@glm, openai-http@glm-payg | ZAI_API_KEY (Coding Plan) for Claude Code / Codex; ZAI_PAYG_API_KEY for HTTP | no |
| any | host (HOST_BATCH) | a host with sub-agents | the host's |

`py -3 KIT/scripts/family.py detect --json` (KIT is the skill folder defined in SKILL.md Setup) shows what is available now; `--live` sends one PONG per family.
`family.py explain --family gpt` prints the exact argv and the NAMES of the environment variables (never values).

## 2. How calls are made (safe defaults)

- The prompt never goes into argv: Claude and Codex read it on stdin; Kimi Code gets it as the body of a one-shot
  agent file with `tools: []` (every `${identifier}` escaped), and `-p` carries only a fixed instruction.
- Tools: `none` for generators, judges, curator, normalizer, synthesis, writers, rubric and fixer. `web` only for the
  researcher, checker, S4-TRANSFER, STACK-VERIFY and review lens L1. `read` only for the researcher and checker (and
  architecture authors) in software/growth runs, and only on the host vendor's family unless privacy `code` = yes.
- Working directory: a fresh empty temp folder, so a worker cannot browse `brainstorm/`.
- Claude workers: `--no-session-persistence --strict-mcp-config` with an empty MCP config and `--disallowedTools
  mcp__*`; never `--bare` (it drops the subscription login). Codex workers: `exec --skip-git-repo-check --ephemeral -s
  read-only`. Kimi workers: `--skills-dir <empty>`; never `--yolo`, `--auto` or `--plan`.
- Timeouts per job kind; on timeout the whole process tree is killed. One retry after an empty, failed or unparseable
  output; one repair call after invalid output; no retry after auth errors or policy refusals.
- Secrets are read only from environment variables and written only into 0600 temp files that are deleted afterwards.
  Logs, meta files and cards are redacted.

## 3. Environment policy

Every child process starts from a scrubbed environment. Removed: `ANTHROPIC_*`, `CLAUDE_CODE_SUBAGENT_MODEL`,
`CLAUDE_CODE_MAX_CONTEXT_TOKENS`, `CLAUDE_CODE_AUTO_COMPACT_WINDOW`, `CLAUDE_CODE_EFFORT_LEVEL`, `CLAUDECODE`,
`CLAUDE_CODE_CHILD_SESSION`, `OPENAI_API_KEY`, `OPENAI_BASE_URL`, `CODEX_API_KEY`, `CODEX_HOME`, `KIMI_MODEL_*`,
`KIMI_API_KEY`, `KIMI_CODE_API_KEY`, `ZAI_API_KEY`, `ZAI_PAYG_API_KEY`, `Z_AI_API_KEY`, `API_TIMEOUT_MS`,
`UB_HOST_FAMILY`. Then each backend adds back only what it needs:

| Backend | Added back |
|---|---|
| claude-cli (native) | the user's ANTHROPIC_API_KEY, ANTHROPIC_AUTH_TOKEN and ANTHROPIC_BASE_URL, only when the base URL is unset or on anthropic.com |
| claude-cli@provider | nothing; the token goes only into the temporary settings file |
| codex-cli (native) | the user's OPENAI_API_KEY, CODEX_API_KEY, OPENAI_BASE_URL, CODEX_HOME |
| codex-cli@provider | CODEX_HOME = the backend's home, plus the backend's token variable |
| kimi-cli | nothing extra (KIMI_CODE_HOME and KIMI_SHELL_PATH are kept) |

Why: a host started by `claude-glm` exports `ANTHROPIC_BASE_URL=https://api.z.ai/...`. Without the scrub, the "claude"
family would silently become GLM and the judging would stop being cross-family.

## 4. Detection and reclassification

- CLIs: `claude --version`, `codex --version`, `kimi --version` (15 s each). Kimi below 2.0 is the archived legacy CLI:
  unavailable, with the note `upgrade: npm install -g @moonshot-ai/kimi-code, then kimi migrate`.
- A `claude` install whose settings point at z.ai or bigmodel.cn serves `glm`; moonshot, kimi.ai or kimi.com serves
  `kimi`. Codex with a ZAI or Moonshot model provider likewise. Such installs are re-listed under the family they
  really serve (`reclassified` in the detect output).
- Kimi credentials: `$KIMI_CODE_HOME/credentials/` (default `~/.kimi-code/credentials/`); otherwise `run: kimi login`.
- Host family, in order: `UB_HOST_FAMILY` (set by the launchers), the host agent's resolved endpoint, the default for
  the agent (claude-code = claude, codex = gpt, kimi = kimi, zcode = glm).
- Preflight at init (unless `--no-preflight`): one PING per family; a failure marks the family unavailable for this run
  and records the fix (for example `kimi login`).

## 5. Policy guards (worker exit 7)

A worker refuses a job, and the card reports it, when:
1. the family's vendor is not in the run's allowed vendors (privacy);
2. the job wants web tools while privacy `web` is off;
3. a family of another vendor would read the repository while privacy `code` is off;
4. an HTTP backend would send the GLM Coding Plan key (`ZAI_API_KEY`) or a `/coding/` URL to z.ai or bigmodel.cn:
   the Coding Plan may be used only through supported tools (Claude Code, Codex);
5. a kimi-cli job would carry a GLM endpoint through `KIMI_MODEL_*` (Kimi Code is not a GLM-supported tool);
6. `families.glm.allow_scripted_plan_use` is false and a worker would call `claude-cli@glm` or `codex-cli@glm`; in
   that strict mode GLM runs only as the host family, through HOST_BATCH [U-20].

GLM traffic goes only through Claude Code or Codex. HTTP to GLM needs a separate pay-as-you-go key
(`ZAI_PAYG_API_KEY`) and must be enabled by the user after a live selftest [U-23].

## 6. Seat assignment

Let F = the available families that privacy allows, host family first, then the configured order.

- One family only: every "other" seat becomes `<host>-alt`, with a PROVISIONAL banner in 00_RUN.md, PROGRESS.md,
  every card and the proposal header.
- Generators: S1 and S2 on the host family; S4 on a web-capable family (host preferred); S3, S5, LENS and GAP
  round-robin over the other families (or `<host>-alt`); REOPEN on other families.
- Researcher: the host family if it has web, otherwise the first web-capable family (deep adds a second family).
- Checker: per idea, a web-capable family that differs from the idea's origin vendor (host preferred). With web off,
  the verdict is NOT CHECKED, which can never trigger K4.
- Screen and tournament judges: quick = 1 non-host family (or `<host>-alt`); standard = the host plus up to 2 others;
  deep = all of F, up to 4.
- Red-team: ADVOCATE and CRITIC always from different families; the advocating family rotates.
- Architecture authors: up to K distinct families (quick 2, standard/proposal 3, deep 4), non-host families first;
  fewer families than K repeat families with different archetypes ("same-family bake-off" badge). Judges: families
  that authored nothing plus the host (otherwise all, with own-candidate exclusion in the matrix). Pre-mortem: not the
  leader's author. Package writer: the chosen candidate's author. Review lenses: not the writer.
- Proposal: drafter = the host family; rubric = other families (1 quick, 2 standard, all deep); red-team = one family
  that is not the drafter.

## 7. PROVISIONAL rules

- Every `-alt` seat, every fallback after a failed chain, and every re-seat after `continue` on another host is
  recorded in `run.json.provisional` and shown in the card notes. Never substitute silently: the failed call keeps its
  `<out>.failed.md` ("FAMILY CALL FAILED: <reason>").
- Provisional judges are labeled `(PROVISIONAL)` and left out of self-preference audits.
- The host must never switch families itself; it reports what the cards say.

## 8. Adding or tuning a family (UB_HOME/families.json)

User overrides live in `~/.ultimate-brainstorm/families.json` (or `$UB_HOME/families.json`) and are deep-merged over
`scripts/families.default.json`. Examples:

Enable the pay-as-you-go Z.ai HTTP route after a live selftest:
```json
{"backends": {"openai-http@glm-payg": {"enabled": true}}}
```

A local model through an OpenAI-compatible server, as its own family:
```json
{"order": ["claude", "gpt", "kimi", "glm", "local"],
 "families": {"local": {"vendor": "local", "limit": 1, "alt_model": null, "backends": ["openai-http@local"]}},
 "backends": {"openai-http@local": {"type": "openai-chat-http", "url": "http://127.0.0.1:11434/v1/chat/completions",
                                    "key_env": "LOCAL_LLM_KEY", "model": "your-model-name", "enabled": true}}}
```
HTTP backends need a model name and have no tools (no web). Give the full `order` list when you change it. Check the
result with `family.py detect --json` and `family.py selftest --family local --live`.

Turn on Kimi web search only after a live probe shows it works: `{"backends": {"kimi-cli": {"web": true}}}` [U-3].
Prices for dollar estimates: add a `prices` block; without it, `ub plan` reports "counts against your plans".
