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
  is always PROVISIONAL. A one-family run whose host family has `alt_model: null` seats one screen judge and one
  tournament judge (the host), not the same model twice. A run an older kit seated with both gets one at its next
  command; a judge step not done yet then drops its `<host>-alt` judge (job, worker, output and prompt).

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
- Working directory: a fresh empty temp folder. Codex workers get no shell on jobs without read, none of the MCP
  servers the user's config.toml names (except names no per-call switch can reach, and every server when part of
  config.toml cannot be read without Python 3.11+; detect lists both), no connectors, plugins, sub-agents, hooks or
  notify program, and any item the job may not produce (a shell, a file edit, an MCP or sub-agent call, an unrequested
  web search, an unknown item type) is refused.
- Claude workers: `--no-session-persistence --strict-mcp-config` with an empty MCP config, `--disallowedTools mcp__*`
  (plus Read/Grep/Glob rules for the run folders on jobs that read the repository) and `--setting-sources project`
  (the user's login and route keys travel in the call's own settings file); never `--bare` (it drops the subscription
  login). Codex workers: `exec --skip-git-repo-check --ephemeral -s read-only -c notify=[]`, each configured MCP server
  disabled by name (none when part of config.toml could not be read), the connector, plugin, sub-agent, hook and memory
  features off, `-c web_search=disabled` unless the job has web. Kimi workers: `--skills-dir <empty>`; never `--yolo`,
  `--auto` or `--plan`.
- Timeouts per job kind; on timeout the whole process tree is killed. One retry after an empty, failed or unparseable
  output, after a jittered back-off (or the server's Retry-After); one repair call after invalid output; no retry after
  auth errors, policy refusals, model refusals or setup (`config`) errors; every attempt of one job ends within twice
  its timeout. Codex and Kimi output is read as it arrives (a long run is fine); a flood past 256 MB, or a Claude
  answer past 12 MB, is stopped and the job reported invalid.
- Every attempt is one row of `logs/calls.jsonl` with the backend requests it sent (`requests`); the run's budget
  counts them (references/pipeline.md 6).
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
| claude-cli@provider | nothing; the token goes only into the temporary settings file (CLAUDE_CODE_USE_BEDROCK, _VERTEX and _FOUNDRY are removed too) |
| codex-cli (native) | the user's OPENAI_API_KEY, CODEX_API_KEY and CODEX_HOME; OPENAI_BASE_URL only when its host serves the call's family |
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
- Kimi Code serves the kimi family only from a Kimi endpoint: when its `config.toml` points a model the kit passes
  (its default, or the configured `model`, `fast_model`, `alt_model`) at z.ai, OpenAI, Anthropic or any other host,
  kimi-cli is unavailable (`Kimi Code is configured for ...`) and never re-listed elsewhere; a worker checks this
  again before each call. A provider without `base_url` counts as the `*_BASE_URL` key of its `[providers.<p>.env]`
  table, else as its `type`'s own endpoint (`anthropic`, `openai`, `google-genai`, ...). With `env_model`,
  `KIMI_MODEL_NAME` without `KIMI_MODEL_BASE_URL` counts as `KIMI_MODEL_PROVIDER_TYPE`'s endpoint (default `kimi`).
- A `claude-cli@<provider>` backend needs the provider's `http(s)://` base URL for the run's region: without one (or
  with a blank or other value) it is unavailable (`provider <p> has no base_url in families config`), and a worker
  never starts claude with the provider's token on Anthropic's endpoint. A provider entry of the wrong shape leaves
  only that provider's backends unavailable, with a note naming the key (`providers.<p>.<key> in families config
  must be ...`).
- Host family, in order: `UB_HOST_FAMILY` (set by the launchers), the host agent's resolved endpoint, the default for
  the agent (claude-code = claude, codex = gpt, kimi = kimi, zcode = glm).
- Preflight at init (unless `--no-preflight`): one PING per family; a failure marks the family unavailable for this run
  and records the fix (for example `kimi login`). A failed authentication later in the run does the same (never for
  the host family) until you log in again and run `continue` (same host or another) or `run --continue`, or retry the
  BLOCKED step: each detects it again.
- A CLI that resolves to a `.cmd`/`.bat` shim while UB_HOME holds one of `" & | < > ^ % !` is unavailable, with a
  note naming the folder and the fix; so is one whose calls would get such a run folder or repository (only a family
  of the host's vendor in a repository run gets those paths).
- `user context:` notes name what still reaches a family's workers: inherited Claude settings (`user_context:
  inherit`, or a reclassified native CLI), `CLAUDE.md` files above UB_HOME/tmp, the user's `$CODEX_HOME/AGENTS.md`,
  Codex MCP servers whose names no per-call switch can reach. The kickoff card and `ub doctor` list them.

## 5. Policy guards (worker exit 7)

A worker refuses a job, and the card reports it, when:
1. the family's vendor is not in the run's allowed vendors (privacy);
2. the job wants web tools while privacy `web` is off;
3. a family of another vendor would read the repository, or would get a prompt that still contains code, while
   privacy `code` is off (the worker reads the prompt itself);
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
  round-robin over the other families (or `<host>-alt`), starting at a seeded offset (`seats.rotation`), so across runs
  every strategy meets every family; REOPEN on other families from the same offset.
- Researcher: the host family if it has web, otherwise the first web-capable family (deep adds a second family).
- Checker: per idea, a web-capable family that differs from the idea's origin vendor (host preferred). With web off,
  the verdict is NOT CHECKED, which can never trigger K4.
- Screen and tournament judges: quick: the tournament judge is 1 non-host family (or `<host>-alt`), and the screen
  judges are the two quick generator families, the host and the first other family, plus with 3 or more families the
  second other family, which generated nothing, as a neutral judge (the blind quick screen, Q.3s; one family: no quick
  screen); standard = the host plus up to 2 others; deep = all of F, up to 4.
- Red-team: ADVOCATE and CRITIC always from different families; the advocating family rotates.
- Architecture authors: up to K distinct families (quick 2, standard/proposal 3, deep 4), non-host families first;
  fewer families than K repeat families with different archetypes ("same-family bake-off" badge). Judges: families
  that authored nothing plus the host when at least two families authored nothing; otherwise all families, each judging
  the candidates it did not author (own-candidate exclusion in the matrix); quick seats the first only. Pre-mortem: not
  the leader's author. Package writer: the chosen candidate's author. Review lenses: not the writer.
- Proposal: drafter = the host family; rubric = other families (1 quick, 2 standard, all deep); red-team = one family
  that is not the drafter.

## 7. PROVISIONAL rules

- Every `-alt` seat, every fallback after a failed chain, and every re-seat after `continue` on another host is
  recorded in `run.json.provisional` and shown in the card notes. Never substitute silently: the failed call keeps its
  `<out>.failed.md` ("FAMILY CALL FAILED: <reason>").
- Provisional judges are labeled `(PROVISIONAL)` and left out of self-preference audits. A judge is counted as the
  family that actually answered its call (a fallback call counts as that family's single vote).
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
