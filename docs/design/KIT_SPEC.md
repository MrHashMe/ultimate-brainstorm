# ultimate-brainstorm kit v2.0: final build spec

Status: final, ready to build. Date: 2026-09-23. Written by the lead architect after judging three designs:
plugin-native (D1), portable-runner (D2) and easiest-ux (D3).

Note for readers of the published repository: the build-time inputs listed below and the `.build/` builder
notes this spec refers to were local to the original build and are not part of this repository.

- **Where the kit goes:** `<kit>/`. This is a new git repository; B1 runs
  `git init` first.
- **Read-only inputs:** builders never edit these.
  - `<workspace>/ULTIMATE_BRAINSTORMING_WORKFLOW.md` (the guide)
  - `<workspace>/ultimate-brainstorm/**` (the v1 skill: SKILL.md, references/*.md,
    scripts/bs.py, agents/openai.yaml)
  - `<workspace>/BRAINSTORMING_TOOLS_REPORT.md`
  - the Kimi Code docs in `<scratchpad>/kdocs/`,
    the old bs.py test harnesses in the same scratchpad (`test_bs.py` and `judge-uxtest/`), and the Claude Code, Codex
    and Z.ai reference copies in its `zai/` folder

**Evidence tags.** Every behavior in this spec carries one of three tags:

| Tag | Meaning | What builders do |
|---|---|---|
| [V] | Verified in vendor docs or source as of 2026-09-23 | Use as is |
| [L] | Likely | Put the tag in a code comment next to the code that relies on it |
| [U] | Unverified | Keep it behind detection or a config key, with the fallback named in section 15. Put the tag in a code comment |

**Reading order for a builder:**
1. Section 2: the tree and who owns each file.
2. Section 3: shared conventions.
3. Section 4: the interfaces. These are binding.
4. Your own detail section: B2 = 5, B3 = 6-9, B1 = 10, B4 = 11.
5. Your work package in section 12.

**Precedence.** This spec overrides the three designs. Where it is silent, pick the most conservative option and log it
in your notes file (section 3.6).

---

## 0. Decision record

### 0.1 Scores

Scores run from 0 to 10. For build effort, 10 means cheapest to build. D2 and D3 reached the judge truncated: D2 from its
section 3.2 onward, D3 from row 15 of its section 3.2 stage table. Their packaging and installer sections were not
visible, so their scores cover only the parts that were.

| Design | Ease for user | Automation depth | Cross-agent correctness | Robustness / testability | Fidelity to evidence rules | Build effort | Total /60 |
|---|---|---|---|---|---|---|---|
| D1 plugin-native ("greenlight") | 8 | 9 | 8 | 7 | 9 | 5 | **46** |
| D2 portable-runner | 8 | 9 | 8 | 8 | 9 | 4 | **46** |
| D3 easiest-ux ("idea-forge") | 9 | 8 | 7 | 7 | 8 | 4 | **43** |

Why each design scored as it did:

**D1 plugin-native**
- Strengths:
  - Packaging is complete and follows the research. One repo serves as the Claude, Codex and Kimi plugin, is a plugin
    ZCode can read, and is also an `npx skills` source.
  - Coverage rule, plan-first installer, verification ledger.
- Weaknesses:
  - Its budgeted blocking waves never start a job whose timeout is longer than the host budget. Example: a 600 s
    researcher job never starts under Codex's 280 s budget.
  - It routes Kimi prompts that contain `${` through `-p`. That hits the 8191-character limit of Windows `.cmd` files.

**D2 portable-runner**
- Strengths: the most robust engine.
  - Detached worker per call, with heartbeat and a content-addressed cache.
  - Answer files, so user replies never go through shell quoting.
  - Environment denylist with add-back.
  - A contested-pair rule that reduces to v1 when N=2.
  - `--from-idea` mode.
  - Architecture and proposal records emitted as JSON and rendered by a script.
- Weakness: the most machinery to build.

**D3 easiest-ux**
- Strengths:
  - Best user experience: a plain-language `say` line on every card, `STATUS.md`, a single HTML proposal pack,
    terminal mode, `private` keyword, quick mode in 4 replies.
  - Strong enforcement: seed-leak check, origin-word check, K4 only flags, Milestone 0 in the roadmap.
- Weaknesses:
  - ce-ideate runs only in deep mode, so the strategy portfolio drifts from the guide.
  - Fewer verified backend details are visible.
  - `--text "{reply}"` quoting breaks on PowerShell 5.1.

### 0.2 Backbone and grafts

**Backbone: D1 plugin-native.** D1 and D2 tie at 46. D1 wins because distribution is the part the user asked for first
("plugin or script ... to download this stack"). D1 specifies distribution completely, in line with the research, while
D2's packaging section was not visible.

**What we keep from D1:**
- One repo that is the plugin root and the marketplace root.
- One entry skill that drives a Python state machine through compact cards.
- Python standard library only.
- The installer design:
  - it prints a plan by default;
  - ownership markers;
  - SHA-256 manifest;
  - atomic, copy-only installs;
  - `doctor`;
  - the coverage rule.
- `bs.py` extended to N families, with own-idea exclusion and debiased standings.
- The Stage 12-14 package: architecture, proposal, handoff.
- Autopilot presets: hands-on, guided, full-auto.
- The GLM launcher via `claude --settings`, and CODEX_HOME isolation.

**Grafted from D2 (portable-runner):**
1. **Execution engine.** One detached worker process per model call, with a heartbeat file and a content-addressed
   "done" rule. The driver only launches and collects work, so host command timeouts never lose finished work.
2. **Answer files.** The host writes a JSON answer file; free text never passes through shell quoting.
3. **Environment policy.** A denylist, then per-backend add-back. This stops a GLM-configured host from silently turning
   the "claude" family into GLM.
4. **Policy refusal.** Exit code 7.
5. **Contested pair for N families.** No order-consistent family, or the modal winner holds less than 2/3 of the
   order-consistent families. With N=2 this equals v1.
6. **`proposal <idea>` mode.** The user already has an idea: check it, red-team it, then write the architecture and
   proposal.
7. **Script rendering.** ADRs, risks, the stack table and judge sheets are rendered by script from JSON registers
   (numbering and format are deterministic).
8. **Sectioned proposal.** Proposal calls are split by section, with a `sources.json` S-### registry.
9. **Commands** `switch` / `redo` / `probe-result`, plus v1 run migration.
10. **Kimi guards.** `--skills-dir <empty>` guard, and no `--json-schema` through `.cmd` shims.

**Grafted from D3 (easiest-ux):**
1. **Progress reporting.** Every card has a plain-language `say` line and a progress line; `PROGRESS.md` is rewritten
   after each step.
2. **Single-file HTML proposal pack:** `11_PROPOSAL/index.html`.
3. **Seed-leak check** before any generator job is dispatched.
4. **Origin-label check** on judge prompts.
5. **K4 as a flag.** K4 never kills in guided mode; the human sees the flag at the gut pick.
6. **Milestone 0 = the pre-registered probe**, checked by lint.
7. **Architecture archetypes:** A boring, B variant-specific, C contrarian, D cost-minimal (deep). Software variants
   get their own archetypes.
8. **Weights.** Quality goals sum to 70; a fixed 30 goes to generic criteria.
9. **Veto rule.** A veto by 2 judges excludes a candidate; a veto by 1 judge only flags it.
10. **STACK-VERIFY web step.**
11. **Terminal mode** `ub run`.
12. **`private` keyword.**

### 0.3 Fixes beyond all three designs

1. **Engine budget.** A job may start whenever the concurrency limit allows. Waiting is bounded per `ub next` call by
   `--wait-s`, not per job. Workers outlive the `ub next` call that started them.
2. **Kimi prompt transport.**
   - The whole prompt goes into the body of the `--agent-file`, with frontmatter `tools: []`. [V]: `tools: []` disables
     all tools, and a body without `${base_prompt}` owns the entire prompt.
   - `-p` carries only a fixed short instruction.
   - Every `${identifier}` in the body is escaped to `$ {identifier}`.
   - No prompt text ever goes into argv.
3. **Name.** Keep `ultimate-brainstorm` for the plugin, the skill and the marketplace. This keeps the guide, v1 runs and
   docs continuous. The short terminal command is `ub`.
4. **Skill frontmatter** uses portable keys only: name, description, license, compatibility, metadata.
   - The skill can be picked by the model in Claude Code, Kimi and ZCode.
   - It is explicit-only in Codex, via `agents/openai.yaml` `allow_implicit_invocation: false`, because `codex exec`
     calls load the user's skills.
5. **One staged kit.** The installer copies the kit to `~/.ultimate-brainstorm/kit/` and registers that folder as a
   local marketplace for the native Claude Code and Codex routes. Installs work before any GitHub release exists, and
   every agent runs the same version.
6. **Codex web search:** `codex exec -c web_search=live` with no quotes. [V] A value that is not valid TOML is read as a
   string, and this avoids quote characters passing through `.cmd` shims.
7. **Structured output.**
   - Claude `--json-schema` is off by default. [U] Its interaction with `--tools ""` and with `.cmd` quoting is untested.
   - Codex `--output-schema` is used only on the OpenAI backend.
   - Every other JSON job puts the schema in the prompt, validates locally and allows one repair call.
8. **Deterministic rendering.** The C4 context diagram is rendered from `drivers.json`. Architecture judge sheets are
   rendered from each candidate's JSON tail; this replaces an LLM normalizer. ADRs, risks and the stack table are
   rendered from JSON registers.
9. **GLM traffic** goes only through Claude Code or Codex, which are Z.ai-supported tools. Raw HTTP to GLM requires a
   separate pay-as-you-go key. Kimi Code CLI never carries GLM.

---

## 1. The product in one screen

**What it promises the user:**
- One installer command sets up the stack for every agent it finds: the kit skill, Compound Engineering, and mattpocock
  grilling + domain-modeling. It also prints how to add the Codex, Claude Code and Kimi CLIs and a GLM key, and sets
  those up on request.
- In any agent, one command runs the whole guide end to end:
  - Claude Code: `/ultimate-brainstorm <topic>`
  - Codex: `$ultimate-brainstorm <topic>`
  - Kimi Code: `/skill:ultimate-brainstorm <topic>`
  - ZCode: `$ultimate-brainstorm <topic>`
- The user answers about 6 short questions: kickoff, frame, gut pick, decision, architecture choice, sign-off.
- The output is:
  - a decided idea;
  - an architecture package (`10_ARCHITECTURE/`);
  - a full proposal (`11_PROPOSAL/PROPOSAL.md`, `ONE-PAGER.md`, `index.html`).
- Every evidence rule of the guide still applies.

```
 user <-> host agent: Claude Code | Codex | Kimi Code CLI v2 | ZCode | Claude Code or Codex running GLM or Kimi models
            skill "ultimate-brainstorm" (SKILL.md: the driver loop, hard rules, host notes)          [B3]
                 | runs:  PY "SK/scripts/ub.py" next "<run>" --wait-s W --json
                 v
   ub.py engine [B3]: pipeline.json state machine -> one card per call:
                      AUTO | HUMAN | HOST | HOST_BATCH | DONE | BLOCKED
        |  writes jobs/<id>.json from templates/prompts/*          |  runs deterministic steps
        v                                                           v
   family.py job [B2] (one detached worker per model call)      bs.py [B2]: map, screen, tournament (N families),
     backends: claude -p | codex exec | kimi -p |                 arch-matrix, lint-*, split, sources,
               claude -p --settings (Z.ai / Moonshot endpoints) |  assumptions, quick-pick
               codex exec with CODEX_HOME=glm|kimi | HTTP | stub [B4 stubs] | host (HOST_BATCH)
 state: <project>/brainstorm/<YYYY-MM-DD>-<slug>/   (run.json + files; any host can resume)
 install [B1]: install/install.py -> ~/.ultimate-brainstorm/{kit,bin,codex-homes,tmp,backups} + native plugins or copies
```

**Non-goals for v2.0:**
- no hooks, MCP servers, Claude workflows, agent teams, plugin `userConfig` or `commands/`;
- no symlink installs;
- no Node installer twin;
- no automatic logins;
- the headless zcode CLI is not used;
- no PDF engine.

---

## 2. Kit file tree and owners

`SK` means `kit/skills/ultimate-brainstorm`. Ownership is disjoint: no file has two owners. A builder creates or edits
only its own files. The only exceptions are its notes file (section 3.6) and, for B1, the one-time repo skeleton
commands in section 12.1.

```
kit/                                          repo root = plugin root = marketplace root
  .claude-plugin/plugin.json                  B1  Claude Code manifest (ZCode also reads it; npx skills discovers it)
  .claude-plugin/marketplace.json             B1  marketplace "ultimate-brainstorm" (+ experimental bundle entry)
  .codex-plugin/plugin.json                   B1  Codex manifest (no root plugin.json anywhere)
  .agents/plugins/marketplace.json            B1  Codex marketplace (read before .claude-plugin/marketplace.json)
  .kimi-plugin/plugin.json                    B1  Kimi Code manifest (Kimi never reads .claude-plugin)
  .kimi-plugin/marketplace.json               B1  Kimi custom marketplace, version "2"
  bundles/stack/.claude-plugin/plugin.json    B1  EXPERIMENTAL Claude bundle: name, author + dependencies
  skills/ultimate-brainstorm/
    SKILL.md                                  B3  driver (<= 12 KB, portable frontmatter)
    agents/openai.yaml                        B1  Codex display + allow_implicit_invocation: false
    references/                               B3  pipeline.md hosts.md families.md components.md variants.md
                                                  techniques.md kill-rules.md architecture.md proposal.md install.md
                                                  troubleshooting.md
    templates/prompts/*.md                    B3  one ASCII template per isolated call (section 6.12)
    templates/host/*.md                       B3  procedures for HOST cards
    templates/gates/*.md                      B3  display text for each HUMAN gate
    templates/docs/*.md                       B3  skeletons that the engine renders (run view, shortlist, ADR, ...)
    templates/docs/index.html.tpl             B3  HTML shell for the proposal pack
    templates/schemas/*.schema.json           B3  static JSON schemas (section 7.4, 8.4)
    scripts/ub.py                             B3  engine CLI
    scripts/pipeline.json                     B3  steps as data
    scripts/estimates.json                    B3  token, time and call priors per job kind
    scripts/bs.py                             B2  bookkeeping CLI (v1-compatible + N families + new commands)
    scripts/family.py                         B2  model-family adapter CLI and worker entry point
    scripts/families.default.json             B2  families, backends, providers (dated)
    scripts/ublib/__init__.py                 B2
    scripts/ublib/textio.py                   B2  tolerant reads, atomic writes, JSON extraction, hashing
    scripts/ublib/schema_lite.py              B2  JSON-schema subset validator
    scripts/ublib/validate.py                 B2  output contracts (section 4.5)
    scripts/ublib/filesproto.py               B2  FILE protocol parse + path guards (section 4.6)
    scripts/ublib/proc.py                     B2  process runner: argv, cwd, env, stdin, timeout, tree kill (test seam)
    scripts/ublib/redact.py                   B2  secret redaction for logs and meta
    scripts/ublib/families.py                 B2  load + merge families config, resolve backend chains
    scripts/ublib/detect.py                   B2  CLI/key/endpoint detection, reclassification, preflight
    scripts/ublib/adapter.py                  B2  execute_job(): backend chain, retries, validation, repair
    scripts/ublib/batch.py                    B2  detached worker launch, heartbeat, job state, foreground batch
    scripts/ublib/lints.py                    B2  lint-arch, lint-proposal, lint-frame rules
    scripts/ublib/backends/__init__.py        B2
    scripts/ublib/backends/claude_cli.py      B2
    scripts/ublib/backends/codex_cli.py       B2
    scripts/ublib/backends/kimi_cli.py        B2
    scripts/ublib/backends/http_openai.py     B2
    scripts/ublib/backends/http_anthropic.py  B2
    scripts/ublib/backends/stub.py            B2  thin: calls ublib.stubs.respond()
    scripts/ublib/stubs.py                    B4  deterministic stub outputs for every contract type
    scripts/ublib/engine/__init__.py          B3
    scripts/ublib/engine/state.py             B3  run.json load/save/migrate, locks
    scripts/ublib/engine/pipeline.py          B3  pipeline.json interpreter (steps, predicates, fanouts)
    scripts/ublib/engine/registry.py          B3  named predicates, fanout sources, placeholders, scripts
    scripts/ublib/engine/builders.py          B3  job construction from templates
    scripts/ublib/engine/gates.py             B3  HUMAN gates, answer templates, answer parsing
    scripts/ublib/engine/cards.py             B3  card JSON + text rendering, say lines
    scripts/ublib/engine/seats.py             B3  family seat assignment
    scripts/ublib/engine/progress.py          B3  PROGRESS.md, ETA, plan/cost preview, budgets
    scripts/ublib/engine/privacy.py           B3  vendor gating, code stripping, seed-leak + origin-label checks
    scripts/ublib/engine/render.py            B3  Markdown subset -> index.html pack; export via pandoc
    scripts/ublib/engine/render_arch.py       B3  drivers/decisions/stack JSON -> Markdown docs, ADRs, context view
    scripts/ublib/engine/handoff.py           B3  publish, context merge, handoff seeds
    scripts/ublib/engine/migrate.py           B3  v1 run -> run.json
    scripts/ublib/engine/terminal.py          B3  `ub run` stdin gate prompts
  install/
    install.py                                B1  stdlib installer (plan/install/update/uninstall/doctor/list/setup-*)
    targets.json                              B1  agents, paths, routes, min versions (dated)
    components.json                           B1  stack components and extras (dated, pinned)
    install.sh                                B1  POSIX bootstrap shim template (rendered at release)
    install.ps1                               B1  PowerShell 5.1 bootstrap shim template (rendered at release)
  profiles/
    launch.py                                 B1  claude-glm/claude-kimi/codex-glm/codex-kimi launcher logic
    launcher.sh.tpl  launcher.cmd.tpl  launcher.ps1.tpl                  B1
    codex-home.glm.toml.tpl  codex-home.kimi.toml.tpl  zai-mcp.json.tpl  B1
  docs/
    GUIDE.md                                  B1  the guide, updated with the kit chapters (section 10.9)
    INSTALL.md  HOSTS.md  FAMILIES.md  PRIVACY.md  TROUBLESHOOTING.md    B1
    ACCEPTANCE.md                             B4  manual live acceptance checklist
  tests/                                      (not Python packages: no __init__.py anywhere under tests/)
    unit/test_textio.py test_schema_lite.py test_validate.py test_filesproto.py test_proc.py
         test_family_claude.py test_family_codex.py test_family_kimi.py test_family_http.py test_detect.py
         test_batch.py test_bs_legacy.py test_bs_nfamily.py test_bs_arch_matrix.py test_bs_misc.py
         test_lints.py                                                   B2
    unit/test_engine_state.py test_engine_pipeline.py test_engine_builders.py test_engine_gates.py
         test_engine_seats.py test_engine_privacy.py test_engine_progress.py test_render.py test_templates.py  B3
    harness/fakecli.py shims.py tmphome.py http_stub.py answerer.py fsnap.py paths.py     B4
    integration/test_installer_plan.py test_installer_apply.py test_installer_update_uninstall.py
         test_installer_doctor.py test_launchers.py test_bootstrap.py test_fake_backends.py              B4
    e2e/test_dryrun_modes.py test_guided_protocol.py test_resume_crash.py test_cross_host.py
         test_privacy_modes.py test_fakecli_quick.py                                                    B4
    static/test_manifests.py test_skill_frontmatter.py test_versions.py test_no_stray_skill_md.py      B4
    fixtures/bs/**  fixtures/lint/**  fixtures/adapter/**  golden/bs/**                               B2
    fixtures/engine/**                                                                                   B3
    fixtures/installer/**  fixtures/e2e/**                                                               B4
  tools/
    release.py                                B1  archives + SHA256SUMS + rendered shims
    ci.py                                     B4  runs every suite in its own process
    validate_kit.py                           B4  static checks, also callable outside tests
  .github/workflows/release.yml               B1
  .github/workflows/ci.yml  .github/workflows/drift.yml                  B4
  README.md  AGENTS.md  CLAUDE.md  CHANGELOG.md  LICENSE  NOTICE.md  VERSION  .gitattributes  .gitignore  B1
  .build/B1-notes.md .build/B2-notes.md .build/B3-notes.md .build/B4-notes.md   each builder its own (not released)
```

Rules for the tree:
- There is exactly one file named `SKILL.md` in the repo: `SK/SKILL.md`. Fixtures that need one use the name
  `SKILL.md.fixture` and rename it at test time. `test_no_stray_skill_md.py` enforces this.
- There is no root `plugin.json`, no root `agents/`, no root `bin/`, no root `hooks/`, no root `.mcp.json` and no
  `commands/`.
  - A root `plugin.json` changes where Codex looks for the manifest.
  - A root `agents/` is loaded by Claude Code and by Kimi.
  - A root `bin/` is added to Claude Code's Bash PATH.
- All manifest paths use forward slashes and start with `./`.

---

## 3. Shared conventions (all builders)

### 3.1 Runtime and code

1. **Python and dependencies.** Python 3.9 or newer, standard library only, at runtime and in tests (unittest).
   - Optional imports stay behind `try`: `tomllib` (3.11+) falls back to a regex; `sentence_transformers` is used only in
     `bs.py dupcheck`.
   - Do not use `match` statements or `X | Y` type unions evaluated at runtime (both need 3.10+).
2. **Processes.** Never use `shell=True`. Resolve executables with `shutil.which` and pass the full path. When the
   resolved path ends in `.cmd` or `.bat`, apply the argument-safety check: reject an argument containing any of
   `" & | < > ^ % !`, CR or LF, and fail with a clear message.
3. **Text files.** UTF-8 without BOM, LF line endings. `.cmd`, `.bat` and `.ps1` files use CRLF (set in
   `.gitattributes`). Reads are tolerant: BOM, UTF-16 BOM, fenced JSON.
4. **Templates** under `SK/templates/` are ASCII only (tested) and contain no `${`.
5. **Paths.**
   - Internally, everything is absolute (`pathlib.Path.resolve()`).
   - Paths in JSON, cards and docs are written with forward slashes (`as_posix()`).
   - Run-relative paths inside run files are relative to the run folder.
6. **Output.**
   - `--json` output is exactly one JSON object on stdout, `ensure_ascii=True`.
   - Text output calls `sys.stdout.reconfigure(encoding="utf-8", errors="replace")` when available.
7. **Timestamps** are UTC ISO-8601 with a trailing `Z`.
   **Job IDs** match `^[A-Za-z0-9._-]{1,80}$`.
8. **Network** is touched only by model backends, the installer's downloads and component commands, and `--live`
   checks. No telemetry anywhere. When the kit runs `npx skills`, it sets `DISABLE_TELEMETRY=1`.
9. **Secrets.**
   - They are read only from environment variables and written only into per-call temporary files with permission 0600
     (on Windows, `icacls <f> /inheritance:r /grant:r "<USERNAME>:F"`). These files are deleted in a `finally` block.
   - They never appear in argv, logs, meta files, cards or docs. `ublib.redact` scrubs any known key value from any
     logged text.
10. **Unverified behavior.** Every [U] behavior reads a config key with a safe default (section 15), and its code
    carries a `# [U] <id>` comment.

### 3.2 Paths and names

| Name | Value |
|---|---|
| Kit root | `<kit>/` (the repo) |
| `SK` | `<kit>/skills/ultimate-brainstorm` |
| `UB_HOME` | `$UB_HOME`, otherwise `~/.ultimate-brainstorm`. Contains `kit/` (staged runtime copy), `bin/`, `codex-homes/{glm,kimi}/`, `tmp/` (0700), `backups/`, `config.json`, `families.json` (user overrides), `install-manifest.json`, `install.log`, `runs.json` (index of runs) |
| Run root | `<project cwd>/brainstorm/`. If the cwd is the home folder or a drive root, it is `~/ultimate-brainstorm-runs/brainstorm/`, and the kickoff card says so |
| Run folder | `<run root>/<YYYY-MM-DD>-<slug>/`. The slug is 3-5 lowercase ASCII words from the topic, with `-` between them; a suffix `-2`, `-3` is added on collision |
| Names | plugin, marketplace and skill are all `ultimate-brainstorm`. Claude invocation: `ultimate-brainstorm@ultimate-brainstorm` |
| Repo slug | `OWNER/ultimate-brainstorm`. `OWNER` is a placeholder that `tools/release.py --owner` fills in; it lives only in manifests, `targets.json` and the docs |

### 3.3 Environment variables

| Variable | Set by | Read by | Meaning |
|---|---|---|---|
| `UB_HOME` | user or tests | all | Kit home override |
| `UB_HOST` | engine (from `--host`) | engine, adapter | `claude-code`, `codex`, `kimi`, `zcode`, `terminal` or `other` |
| `UB_HOST_FAMILY` | launchers (`claude-glm` etc.) | detect | Forces the host family: `claude`, `gpt`, `kimi` or `glm` |
| `UB_JOB_ID`, `UB_JOB_FILE` | adapter, in every child process | fakes (B4) | Test seam. Carries no secrets |
| `UB_FAKE_FAMILIES=1` | tests | detect, families | Every family is available through the `stub` backend |
| `UB_FAKE_DISABLE=a,b` | tests | detect | Families to report as unavailable in fake mode |
| `UB_FAKE_HOST_BACKEND=glm` | tests | families | Forces a family's backend chain to `host` (exercises HOST_BATCH) |
| `UB_FAKE_SCENARIO`, `UB_FAKE_LOG` | tests | fake CLIs | Scenario file and log file for the fake CLIs (section 4.18) |
| `UB_STUB_DELAY_S`, `UB_STUB_HOMOGENIZED=1`, `UB_STUB_FAIL=<job-id-regex>` | tests | stubs | Controls stub timing, pool shape and injected failures |
| `UB_TEST_CRASH_AT=<step-id>` | tests | engine | After that step's jobs finish, exit 99 before marking the step done |
| `UB_INSTALL_OFFLINE=1` | tests | installer | No network; component rows become `manual` |
| `UB_RELEASE_DIR` | tests | bootstrap shims | Use a local folder instead of downloading release assets |
| `UB_ALLOW_ROOT=1` | user | shims, installer | Allow running as root (refused otherwise) |
| `UB_NO_DETACH=1` | tests, user | batch | Run workers attached (foreground) instead of detached |
| `UB_HEARTBEAT_STALE_S` | tests | batch | Stale-heartbeat threshold in seconds (default 60) |
| `UB_LIVE=1` | user | live tests | Allow real model calls in `tests/live` (manual only) |
| `CLAUDE_CONFIG_DIR`, `CODEX_HOME`, `KIMI_CODE_HOME` | user | installer, detect, adapter | Agent home overrides [V] |
| `ZAI_API_KEY` | user | adapter, launchers | GLM Coding Plan key. Used only via Claude Code or Codex |
| `ZAI_PAYG_API_KEY` | user | adapter | Z.ai pay-as-you-go key. The only key allowed for HTTP to GLM |
| `KIMI_API_KEY` | user | adapter, launchers | Moonshot Platform key, for Claude Code or Codex against Moonshot. Kimi Code CLI ignores it [V] |
| `KIMI_CODE_API_KEY` | user | adapter, launchers | Kimi Code membership key (Anthropic-compatible coding endpoint) |
| `OPENAI_API_KEY`, `ANTHROPIC_API_KEY` | user | adapter | HTTP fallbacks, and the user's own CLI auth when the user relies on keys |

### 3.4 Versioning

The file `VERSION` contains `2.0.0`. The same string must appear in:
- every manifest `version`;
- the SKILL.md `metadata.version`;
- `ub.py --version`, `family.py --version`, `bs.py --version`, `install.py version`;
- the top heading of `CHANGELOG.md`.

`tests/static/test_versions.py` enforces this.

### 3.5 What every builder must NOT do

- Edit another builder's files. If you need a change there, write it in your notes file and code to this spec.
- Hard-code an [U] item without its fallback (section 15).
- Guess model IDs. `null` means "the CLI's default".
- Add dependencies, hooks, MCP servers or symlinks.
- Write outside `kit/` at build time. Tests write only inside temporary directories.
- Put a secret in argv or in a file that is not deleted in `finally`.

### 3.6 Notes

Each builder keeps `kit/.build/Bn-notes.md`, covering:
- deviations from this spec, with the reason;
- [U] items it touched;
- open questions for integration.

---

## 4. Interfaces (binding contracts between builders)

### 4.1 Run folder layout (v2)

```
brainstorm/
  LEDGER.md                                   cross-run log (v1 format, bs.py init creates it)
  <YYYY-MM-DD>-<slug>/
    run.json                                  engine state (4.2)                                   B3 writes
    00_RUN.md                                 human view with v1-compatible lines (4.3)            B3 writes
    PROGRESS.md                               progress view (6.9)                                  B3 writes
    00_HUMAN_SEEDS.md  [00b_HUMAN_ROUND2.md]  seeds (v1 format)
    01_FRAME.md  criteria.json  [CONTEXT.before.md  CONTEXT.proposed.md]   v1 formats
    frame/questions.json  frame/answers.json  frame express path
    02_CONTEXT.md                             v1 format (A FACTS, A2 terms, B LANDSCAPE, C SEARCH BOUNDARY)
    sources.json  sources.md                  S-### registry (bs.py sources)
    jobs/<job-id>.json                        job specs (4.4)                                      B3 writes, B2 runs
    prompts/<job-id>.prompt.md                filled prompts                                       B3 writes
    pool/*  pool/_families.json               generator outputs; prefix -> family (B3 writes the map)
    merges.json  03_POOL_NOTES.md  03_POOL.md  clusters.json  origins.json  primary.json  coverage.json
    screen/  04_SHORTLIST.md  checks/<ID>.md  05_EVOLVED.md
    tournament/{cards.md,header.md,precommit.md,*.prompt.md,*.map.json,*.out.json,result.md,result.json}
    06_TOURNAMENT.md  07_TOP.md  redteam/  07_REDTEAM.md  08_DECISION.md  09_PROBE.md
    quick/curated.json  quick/finalists.json  QUICK_DECISION.md          quick mode only
    10_ARCHITECTURE/  (7.1)     11_PROPOSAL/  (8.1)     12_HANDOFF.md
    gates/<GATE>.md                           exact display text of each HUMAN card
    answers/<GATE>.json                       accepted answers (archived by the engine)
    logs/calls.jsonl  logs/<job-id>.log       one line per model-call attempt; per-job stderr tail
    .ub/lock.json  .ub/jobs/<job-id>.running.json  .ub/events.jsonl  .ub/last_card.json
    _superseded/<ISO>/...                     outputs moved aside by redo/switch (never deleted)
```

Every generated file is also one of the following:
- **v1 compatible.** A v1 `bs.py status` still understands a v2 run folder, because `00_RUN.md` keeps the v1 lines.
- **New and listed above.**

### 4.2 `run.json` (schema 2)

B3 writes it. B2's `bs.py` reads `seats`, `provisional`, `mode` and `host`. B4 reads it in assertions.

```json
{
  "schema": 2,
  "kit_version": "2.0.0",
  "run": "2026-09-23-night-tutor",
  "created_at": "2026-09-23T09:00:00Z",
  "topic": "AI tutor for night-shift nurses",
  "lang": "en",
  "mode": "standard",
  "variant": "product",
  "build_type": "system",
  "autopilot": "guided",
  "host": {"agent": "claude-code", "family": "claude", "family_source": "env|endpoint|default|user"},
  "python": "py -3",
  "runner": "py -3 \"C:/Users/U/.ultimate-brainstorm/kit/skills/ultimate-brainstorm/scripts/ub.py\"",
  "privacy": {"web": true, "vendors": true, "code": false, "allowed_vendors": ["anthropic", "openai", "moonshot"]},
  "families": {
    "claude": {"status": "ok", "backend": "claude-cli", "web": true, "reason": ""},
    "gpt": {"status": "ok", "backend": "codex-cli", "web": true, "reason": ""},
    "kimi": {"status": "ok", "backend": "kimi-cli", "web": false, "reason": ""},
    "glm": {"status": "unavailable", "backend": null, "web": false, "reason": "ZAI_API_KEY not set"}
  },
  "components": {"grilling": "mattpocock-skills:grilling", "domain_modeling": null, "ce_ideate": "compound-engineering:ce-ideate",
                 "ce_brainstorm": "compound-engineering:ce-brainstorm", "bmad_brainstorming": null, "bmad_forge_idea": null,
                 "lateral_thinking": null, "claude_council": null, "speckit": null},
  "seats": {
    "s1_engine": "s1f",
    "generators": {"S1": "claude", "S2": "claude", "S3": "gpt", "S4": "claude", "S5": "kimi"},
    "researcher": ["claude"],
    "checker_pool": ["claude", "gpt"],
    "screen_judges": ["claude", "gpt", "kimi"],
    "tournament_judges": ["claude", "gpt", "kimi"],
    "redteam_rotation": ["claude", "gpt", "kimi"],
    "arch_authors": ["gpt", "kimi", "claude"],
    "arch_judges": ["claude", "gpt", "kimi"],
    "arch_writer": null,
    "proposal": {"drafter": "claude", "rubric": ["gpt", "kimi"], "redteam": "kimi"}
  },
  "provisional": [{"stage": "screen", "seat": "gpt", "actual": "gpt-alt", "reason": "codex exec failed twice"}],
  "gates": {"G0": {"state": "answered", "by": "human", "at": "2026-09-23T09:02:00Z", "answer": {}}},
  "steps": {"4.2": {"state": "done", "at": "2026-09-23T09:40:00Z", "jobs": ["4.2-S2", "4.2-S3"], "note": ""}},
  "choice": {"idea": null, "runner_up": null, "arch": null, "arch_family": null},
  "budget": {"max_calls": 180, "max_usd": null},
  "exec": {"wait_s": 540},
  "legacy_v1": false
}
```

**Allowed values:**

| Field | Values |
|---|---|
| `mode` | `quick`, `standard`, `deep`, `proposal` |
| `variant` | `software`, `product`, `growth`, `research`, `marketing`, `creative`, `naming`, `general` |
| `build_type` | `system` or `approach` (6.15) |
| `autopilot` | `hands-on`, `guided`, `full-auto` |
| gate `state` | `pending`, `answered`, `auto`, `skipped` |
| gate `by` | `human`, `auto` |
| step `state` | `pending`, `running`, `done`, `failed`, `skipped`, `blocked` |

**Family labels.** A seat family can be `<family>-alt`, meaning same vendor, alternate model or fresh context. That seat
is always PROVISIONAL.

### 4.3 `00_RUN.md` (v1-compatible human view)

B3 renders it from `run.json` on every save. v1 `bs.py` parses lines that begin exactly as follows. B2 keeps those
parsers.

```
# Run: <slug>
- mode: <quick|standard|deep|proposal>
- variant: <...>
- topic: <...>
- autopilot: <...>
- host family: <family> (<agent>)
- other family: <comma list "gpt via codex-cli, kimi via kimi-cli">  or  "none -> PROVISIONAL (<fam>-alt)"
- privacy: (a) web + other vendors: <yes|no>   (b) code facts / repo files to other vendors: <yes|no>
- python: <py -3|python3|python>
- detected tools: <components, exact names>
- strategy -> family map: S1=claude S2=claude S3=gpt S4=claude S5=kimi
- human saw S1 ranking: <yes|no|n/a>
- session plan: one session is fine (all state is in files; any agent can resume)
- stage log:
  - <ISO> <step> <state> <note>
```

### 4.4 Job JSON (`jobs/<job-id>.json`)

B3 writes it. B2 executes it (`family.py job`). B4's stubs read it.

```json
{
  "schema": 1,
  "run": "C:/p/brainstorm/2026-09-23-night-tutor",
  "id": "4.2-S3",
  "step": "4.2",
  "kind": "generator",
  "template": "S3-EDE",
  "family": "gpt",
  "tier": "default",
  "prompt_file": "prompts/4.2-S3.prompt.md",
  "out": "pool/S3_enumerate.md",
  "tools": "none",
  "cwd": "empty",
  "repo_root": null,
  "timeout_s": 420,
  "retries": 1,
  "contract": {"type": "idea-blocks", "prefix": "S3", "min": 10},
  "schema_file": null,
  "split": null,
  "fallback": ["gpt-alt"],
  "provisional": false,
  "privacy": {"vendor_ok": true, "web_ok": true, "code_ok": false},
  "host_prompt_file": null,
  "stub": {"axes": {"Stage": ["onboarding", "shift"], "Channel": ["app", "sms"]}}
}
```

**Fields:**

| Field | Values and meaning |
|---|---|
| `kind` | `ping`, `generator`, `researcher`, `curator`, `judge`, `checker`, `normalizer`, `reviewer`, `synthesis`, `writer`, `arch-author`, `arch-judge`, `rubric`, `redteam`, `fixer`, `frame` |
| `family` | A family ID, `<family>-alt`, or `host` |
| `tier` | `default` or `fast` |
| `tools` | `none`, `web`, `read` or `read+web` |
| `cwd` | `empty` (a fresh empty temp directory) or `repo` (`repo_root`, read-only use) |
| `schema_file` | Run-relative. Used only by backends with `native_schema: true`. Otherwise the schema text is already inside the prompt, placed there by B3 |
| `split` | `{"root": "10_ARCHITECTURE", "allowed": ["chosen/*.md", "chosen/api/*"], "status_out": "10_ARCHITECTURE/_raw/12.9a.status.json"}` when the output uses the FILE protocol (4.6) |
| `fallback` | Families to try after the chain fails. Results are labeled PROVISIONAL |
| `privacy` | Stamped by the engine. The adapter re-checks it and exits 7 on a mismatch |
| `host_prompt_file` | The HOST_BATCH variant of the prompt. It ends with an `OUTPUT FILE: <abs out>` rule |
| `stub` | Facts for stubs only (4.17) |

**When a job counts as done:**
- `<out>` exists;
- the contract validates;
- `<out>.meta.json` exists with `status: "ok"` and a `prompt_sha256` equal to the SHA-256 of the current prompt file.

Anything else is re-run. This is the content-addressed cache.

### 4.5 Contract types

| Type | Fields | Validator (B2 `ublib.validate`) | Stub (B4 `ublib.stubs`) |
|---|---|---|---|
| `text` | `min_chars` (default 20), optional `regex` (must match somewhere), optional `final_line` (regex on the last non-empty line) | length and regex checks | lorem-free plain sentences that satisfy the regexes. `final_line` is taken from `stub.final_line` |
| `idea-blocks` | `prefix`, `min` | at least `min` blocks with headings `^### <prefix>-\d+ .+`. Each block contains lines starting `- Pitch:`, `- Mechanism:`, `- Fails if:` | `min` blocks with every GEN-HEADER line. `Cell` values are taken from `stub.axes` |
| `json` | `schema` (run-relative or `SK:templates/schemas/<f>`), optional `cover: {"array": "scores", "key": "id", "ids": [...]}` | tolerant extract -> schema_lite -> every cover ID present | instance generated from the schema. Every cover ID gets one array item. Enums take the first value, integers the midpoint of min/max (default 3), booleans `true`, strings `"stub"` |
| `sections` | `headings` (ordered list of `#`-line prefixes, case-insensitive), optional `final_line`, `json_tail` (schema), `max_words` {heading: n} | each heading appears in order; the final-line regex holds; the last fenced ```json block validates; word caps hold | headings in order with 2 sentences each, the final line, and a JSON tail generated from the schema |
| `cards` | `ids`, `lines` (ordered line prefixes) | one `## <ID>` per ID, each with every line prefix | cards with 1-sentence values |
| `files` | `allowed` (globs relative to `split.root`), `required` (paths), optional `per_file` {path: {"headings": [...], "mermaid": ["flowchart"]}}, `status_trailer` (bool) | FILE protocol (4.6) parses; required files present; per-file headings and mermaid block types present; STATUS present if required | every required file with its headings and minimal valid mermaid blocks, plus a STATUS trailer |

All validators return `(ok: bool, errors: list[str], parsed: object|None)`.

A JSON job whose output fails validation gets one repair call on the same backend, with this prompt:

`Your previous output failed validation: <errors, max 1500 chars>. Return only the corrected output.`

followed by the previous output. The repair uses the same contract.

The repair call is only for output that fails validation. Valid output that cannot be written (an `OSError` while
writing `<out>` or the FILE-protocol files) is retried locally, 3 tries in all. If it still fails, the job ends with
status `failed` and `error_class` `internal`. It never costs a repair call, because a repair repeats a model call whose
answer was fine and records a second `ok` call for the same job and prompt.

### 4.6 FILE protocol and STATUS trailer

```
=== FILE: chosen/containers.md ===
...content...
=== END FILE ===
=== FILE: chosen/runtime.md ===
...
=== END FILE ===
=== STATUS ===
{"status":"complete","assumptions":["..."],"open_questions":["..."],"reason":""}
=== END STATUS ===
```

Rules, enforced by `ublib.filesproto` (B2):
1. Paths are relative to `split.root` and use forward slashes. Rejected: `..`, absolute paths, drive letters, and names
   starting with `.`.
2. The extension must be one of `.md`, `.yaml`, `.yml`, `.json`, `.mmd`. The path must match at least one `allowed`
   glob.
3. Content must not be empty. If a path appears twice, the last copy wins and a warning is logged. Text outside the
   blocks is ignored.
4. Files are written atomically. Nothing is written unless the whole output validates.
5. The STATUS block is saved to `split.status_out`. `status` is one of `complete`, `partial`, `blocked`.
6. Every target must resolve inside `split.root` after symlinks and junctions are resolved. On Windows,
   `os.path.realpath()` sometimes returns the `\\?\` extended-length form, for example when a parallel worker creates
   the same new folder mid-call (13.2-A/B/C all write `11_PROPOSAL/sections/`). That prefix is dropped before the
   comparison (`textio.real_path`), so a sibling's `mkdir` is never reported as "resolves outside the output root".

### 4.7 Worker protocol (B2 implements, B3 drives, B4 tests)

**Launch.** `batch.launch_job(job_path)` starts `PY SK/scripts/family.py job --job <abs job.json>` as a detached
process:
- POSIX: `start_new_session=True`, stdin DEVNULL, stdout/stderr appended to `logs/<job-id>.log`.
- Windows: `creationflags = CREATE_NEW_PROCESS_GROUP | DETACHED_PROCESS | CREATE_BREAKAWAY_FROM_JOB`. If this raises
  `OSError` (breakaway not allowed), retry without `CREATE_BREAKAWAY_FROM_JOB`.
- When `UB_NO_DETACH=1`, the worker runs attached (tests, and terminal mode on request).
- `launch_job` decides under the job's execution lock (below). It does not launch a job that is done (4.4), whose lock
  another process holds, or whose running marker is live. In that case it returns
  `{"pid": <holder or null>, "job_id": ..., "launched": false, "state": "done"|"running"}`, and the driver counts
  nothing against `budget.max_calls`. A dead marker is removed and the relaunch is counted. If its pid still runs and
  verifiably is its worker (it started no later than the marker), that process is stopped first. If it cannot be
  stopped (for example, access denied), nothing is launched, the state is `"stuck"`, and the driver returns a BLOCKED
  card that suggests `ub stop`. The detached launch writes the running marker with the child's pid and a random launch
  `token` (`attempt` 0, `backend` null) before it releases the lock, and passes the same token to the child in
  `UB_LAUNCH_TOKEN`. The child needs the lock to start, so nothing races that write. The worker recognizes that marker
  as its own by the token, not by the pid: in a Windows venv `sys.executable` is a redirector, so the pid the launcher
  sees belongs to the redirector and the worker is its child.

**Execution lock (one worker per job).** `.ub/jobs/<job-id>.lock` is an OS file lock: `msvcrt.locking` (LockFile) on
Windows, `fcntl.flock` on POSIX. It sits on a byte beyond EOF, so the file stays empty. The file is never deleted.
- The worker (`family.py job`) takes the lock before it writes its marker. It holds the lock until after it has
  deleted the marker. The OS releases the lock when the worker ends, also when it is killed, so a dead worker never
  leaves a stale claim behind.
- A starting worker waits up to 30 s for its launcher to let go. It stops waiting at once when the marker names
  another live worker (not its own launch marker). If it cannot take the lock, it exits 0 without a call, printing
  `skipped ... another worker holds this job`.
- Holding the lock, the worker re-checks the done rule (4.4). If the job is already done for the current prompt, it
  exits 0 without a call (`skipped ... already done`), and the cached result stands. It also exits 0 without a call
  when a meta for the current prompt appeared or changed while it waited for the lock (another worker ran the job,
  even if that run failed; `skipped ... another worker ran this job`).
- So a running or finished job is never called twice, whoever launches it: a second driver, `family.py batch`, or a
  manual `family.py job`.
- On a file system without file locks the lock is a no-op, and the marker rules alone apply.
- Known limit: on POSIX a backend CLI runs in its own session. When a worker is killed hard (SIGKILL), its backend
  process can keep running; neither the lock nor `stop_all` stops it, so a relaunch may overlap with it. That costs a
  call but never records a second result: only the worker writes outputs and meta.

**Running marker.** The worker writes `.ub/jobs/<job-id>.running.json`:

```json
{"pid": 1234, "started_at": "...", "heartbeat_at": "...", "attempt": 1, "backend": "codex-cli", "token": "..."}
```

- It refreshes `heartbeat_at` every 10 s from a thread.
- It deletes the file on exit, success or failure.
- A heartbeat older than 60 s means the worker is dead, unless its execution lock is held.

**Concurrent reads.** Markers, heartbeats, job, meta and result files are replaced atomically (`os.replace`) while
other processes read them. On Windows, an `open()` that lands inside a replace fails with `PermissionError` for a
moment. Every `textio` read (`read_text`, `read_json`, `read_json_or`, `read_bytes`, `sha256_file`) retries that for up
to 1 s. A missing file (`FileNotFoundError`) is never retried: it is a real state, and a replace never causes it. No
job state is decided on a file that was only mid-replace. Tests and harness code that read these files use the same
helpers.

**Outputs, all written atomically:**
- `<out>`, only when valid.
- `<out>.meta.json`, always:

```json
{"schema":1,"id":"4.2-S3","family":"gpt","vendor":"openai","backend":"codex-cli","model":null,"tier":"default",
 "provisional":false,"status":"ok","attempts":1,"exit_code":0,"error_class":null,"started":"...","duration_s":142.3,
 "prompt_sha256":"...","out_sha256":"...","usage":{"input_tokens":null,"output_tokens":null,"cost_usd":null,
 "source":"reported|estimated|none"},"tools":"none","web_used":false,"cwd":"empty","repaired":false,
 "cmd":"codex exec -C <empty> ... (redacted)","stderr_tail":""}
```

- `<out>.failed.md` on final failure. Its first line is `FAMILY CALL FAILED: <reason>`.
- One line appended to `logs/calls.jsonl` per attempt: the same keys as meta, plus `ts`.

**`status`** is one of `ok`, `failed`, `invalid`, `timeout`, `refused`, `unavailable`.
**`error_class`** is one of `auth`, `network`, `rate_limit`, `timeout`, `bad_output`, `policy`, `not_found`,
`sandbox_network`, `internal`.

**Worker exit codes:**

| Code | Meaning |
|---|---|
| 0 | ok |
| 2 | usage |
| 3 | family unavailable |
| 4 | failed after retries and backend chain |
| 5 | output invalid after repair |
| 6 | timeout |
| 7 | refused by policy |

**Driver-side job state** (`batch.job_state(run_dir, job) -> str`):

| State | Condition |
|---|---|
| `done` | the done rule in 4.4 holds |
| `running` | a process holds the job's execution lock (whatever the heartbeat says), or a live running marker exists |
| `dead` | a stale marker exists, no process holds the lock, and no done output |
| `failed` | meta status is not `ok` and no running marker |
| `pending` | none of the above |

`job_state` reads the marker and the lock before it checks the done rule. A worker writes `<out>` and its meta, then
deletes its marker, then releases its lock. So "no marker and no lock holder" means that a finished worker's outputs are
already on disk.

The driver relaunches `dead` jobs up to 3 times per prompt hash, counted in `.ub/jobs/<id>.relaunch`. After that it
returns a BLOCKED card (6.3).

### 4.8 `family.py` CLI and Python API (B2)

```
family.py --version
family.py detect   [--json] [--live] [--families claude,gpt,kimi,glm]
family.py job      --job FILE                                  worker entry point (4.7)
family.py call     --family F --prompt-file P --out O [--kind K] [--tools none|web|read|read+web]
                   [--cwd empty|repo] [--repo DIR] [--contract-file F | --contract-json JSON] [--schema F]
                   [--tier default|fast] [--timeout S] [--retries N] [--meta M] [--json]   ad hoc single call
family.py batch    --jobs FILE [--parallel 4] [--budget-s 540] [--json]    foreground batch (terminal, tests)
family.py selftest [--family F|all] [--live]                   fake round trip; --live sends "Reply with PONG"
family.py explain  --family F [--tools T] [--tier T]           prints argv and env var NAMES, never values
exit codes: as in 4.7 (0, 2, 3, 4, 5, 6, 7)
```

**Python API.** These signatures are frozen; B3 and B4 import them.

```python
# ublib/textio.py
read_text(path) -> str                          # UTF-8 / BOM / UTF-16 tolerant; retries a read that lands in a
                                                # concurrent replace (Windows PermissionError, up to 1 s; 4.7)
write_text_atomic(path, text) -> None           # UTF-8 no BOM, LF; tmp file in same dir + os.replace
write_json_atomic(path, obj) -> None            # indent=1, ensure_ascii=False, trailing newline
extract_json(text) -> object                    # fenced / preamble tolerant; ValueError if none
sha256_text(text) -> str ; sha256_file(path) -> str ; is_ascii(text) -> bool
# ublib/schema_lite.py
validate(instance, schema) -> list              # errors; supports type, required, properties,
                                                # additionalProperties, items, enum, minItems, maxItems,
                                                # minimum, maximum, minLength, maxLength
# ublib/validate.py
check_contract(text, contract, run_dir) -> tuple   # (ok, errors, parsed)
# ublib/filesproto.py
parse_file_blocks(text) -> tuple                # ({relpath: content}, status_dict_or_None, warnings)
write_file_blocks(files, root, allowed_globs) -> list   # written abs paths; raises PathError
# ublib/families.py
load_families(scripts_dir=None, ub_home=None) -> dict   # families.default.json deep-merged with UB_HOME/families.json
resolve_chain(cfg, family, detect_result) -> list        # ordered backend ids usable now
provider_settings_env(cfg, provider, tier="default", region=None) -> dict  # env block WITHOUT the token value
# ublib/detect.py
detect(cfg=None, live=False, only=None) -> dict          # shape below
# ublib/adapter.py
execute_job(job: dict) -> dict                  # runs the chain in-process; returns meta dict; writes outputs
# ublib/batch.py
launch_job(job_path) -> dict                    # {"pid": int, "job_id": str}; + "launched": false and "state"
                                                # when the job is done, held by another process or stuck (4.7)
job_state(run_dir, job) -> str                  # done|running|dead|failed|pending
running_jobs(run_dir) -> list                   # job ids with live markers
stop_all(run_dir) -> int                        # tree-kills live workers; returns count
run_foreground(jobs, parallel=4, budget_s=None) -> dict   # {"done": [...], "failed": [...], "pending": [...]}
# ublib/lints.py
lint_arch(run_dir, lite=False) -> dict ; lint_proposal(run_dir, lite=False) -> dict ; lint_frame(run_dir) -> dict
# each returns {"status": "pass|warn|fail", "items": [{"id","severity","file","message"}]} and writes lint.md/lint.json
```

**`detect --json` shape:**

```json
{"schema":1,"generated_at":"...","fake":false,
 "host":{"agent":"claude-code","family":"claude","source":"env|endpoint|default"},
 "clis":{"claude":{"path":"C:/.../claude.exe","version":"2.1.280","shim":false},
         "codex":{"path":"...","version":"0.156.1","shim":true},
         "kimi":{"path":null,"version":null,"legacy":false}},
 "keys":{"ZAI_API_KEY":false,"ZAI_PAYG_API_KEY":false,"KIMI_API_KEY":false,"KIMI_CODE_API_KEY":false,
         "OPENAI_API_KEY":false,"ANTHROPIC_API_KEY":false},
 "families":{"claude":{"available":true,"backend":"claude-cli","chain":["claude-cli"],"web":true,"vendor":"anthropic","notes":[]},
             "gpt":{"available":true,"backend":"codex-cli","chain":["codex-cli"],"web":true,"vendor":"openai","notes":[]},
             "kimi":{"available":false,"backend":null,"chain":[],"web":false,"vendor":"moonshot","notes":["kimi not on PATH"]},
             "glm":{"available":false,"backend":null,"chain":[],"web":false,"vendor":"zhipu","notes":["ZAI_API_KEY not set"]}},
 "reclassified":[{"cli":"claude","source":"~/.claude/settings.json","endpoint":"api.z.ai","as":"glm"}],
 "live":{"claude":"PONG ok 4.1s"}}
```

### 4.9 `families.default.json` (B2 owns; B1 launchers read `providers`)

This is the full content. It is dated. Model IDs are copied from vendor docs dated 2026-09-23. `null` means the CLI's
default.

```json
{
  "schema": 1,
  "verified": "2026-09-23: Claude Code 2.1.280, Codex rust-v0.156.1, Kimi Code 2.0.2, Z.ai devpack docs, Moonshot platform docs",
  "order": ["claude", "gpt", "kimi", "glm"],
  "region": "global",
  "defaults": {
    "parallel": 4,
    "retries": 1,
    "timeouts_s": {"ping": 60, "frame": 420, "generator": 420, "curator": 480, "judge": 300, "researcher": 600,
                   "checker": 480, "normalizer": 300, "reviewer": 420, "synthesis": 420, "writer": 720,
                   "arch-author": 600, "arch-judge": 420, "rubric": 300, "redteam": 420, "fixer": 600}
  },
  "families": {
    "claude": {"vendor": "anthropic", "limit": 3, "alt_model": "sonnet",
               "backends": ["claude-cli", "anthropic-http"]},
    "gpt":    {"vendor": "openai", "limit": 3, "alt_model": null,
               "backends": ["codex-cli", "openai-http"]},
    "kimi":   {"vendor": "moonshot", "limit": 3, "alt_model": null,
               "backends": ["kimi-cli", "claude-cli@kimi", "claude-cli@kimi-code", "codex-cli@kimi", "openai-http@kimi"]},
    "glm":    {"vendor": "zhipu", "limit": 2, "alt_model": null, "allow_scripted_plan_use": true,
               "backends": ["claude-cli@glm", "codex-cli@glm", "openai-http@glm-payg"]}
  },
  "backends": {
    "claude-cli":           {"type": "claude-cli", "exe": "claude", "min_version": null, "web": true, "native_schema": false},
    "claude-cli@glm":       {"type": "claude-cli", "exe": "claude", "provider": "glm", "web": false, "native_schema": false},
    "claude-cli@kimi":      {"type": "claude-cli", "exe": "claude", "provider": "kimi", "web": false, "native_schema": false},
    "claude-cli@kimi-code": {"type": "claude-cli", "exe": "claude", "provider": "kimi-code", "web": false, "native_schema": false},
    "codex-cli":            {"type": "codex-cli", "exe": "codex", "min_version": null, "codex_home": null, "model": null,
                             "web": true, "native_schema": true},
    "codex-cli@glm":        {"type": "codex-cli", "exe": "codex", "codex_home": "~/.ultimate-brainstorm/codex-homes/glm",
                             "token_env": "ZAI_API_KEY", "model": null, "web": false, "native_schema": false},
    "codex-cli@kimi":       {"type": "codex-cli", "exe": "codex", "codex_home": "~/.ultimate-brainstorm/codex-homes/kimi",
                             "token_env": "KIMI_API_KEY", "model": null, "web": false, "native_schema": false},
    "kimi-cli":             {"type": "kimi-cli", "exe": "kimi", "min_version": "2.0.0", "model": null, "fast_model": null,
                             "web": false, "env_model": false},
    "anthropic-http":       {"type": "anthropic-http", "url": "https://api.anthropic.com/v1/messages",
                             "key_env": "ANTHROPIC_API_KEY", "model": null, "enabled": true},
    "openai-http":          {"type": "openai-chat-http", "url": "https://api.openai.com/v1/chat/completions",
                             "key_env": "OPENAI_API_KEY", "model": null, "enabled": true},
    "openai-http@kimi":     {"type": "openai-chat-http", "url": "https://api.moonshot.ai/v1/chat/completions",
                             "key_env": "KIMI_API_KEY", "model": "kimi-k3", "enabled": false},
    "openai-http@glm-payg": {"type": "openai-chat-http", "url": "https://api.z.ai/api/paas/v4/chat/completions",
                             "key_env": "ZAI_PAYG_API_KEY", "model": "glm-5.3", "policy": "payg-only", "enabled": false}
  },
  "providers": {
    "glm": {"token_env": "ZAI_API_KEY", "token_var": "ANTHROPIC_AUTH_TOKEN",
            "base_url": {"global": "https://api.z.ai/api/anthropic", "cn": "https://open.bigmodel.cn/api/anthropic"},
            "models": {"default": "glm-5.3[1m]", "fast": "glm-5.3-flash[1m]"},
            "env": {"API_TIMEOUT_MS": "3000000", "CLAUDE_CODE_AUTO_COMPACT_WINDOW": "1000000",
                    "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1"}},
    "kimi": {"token_env": "KIMI_API_KEY", "token_var": "ANTHROPIC_AUTH_TOKEN",
             "base_url": {"global": "https://api.moonshot.ai/anthropic"},
             "models": {"default": "kimi-k3[1m]", "fast": "kimi-k2.7-code"},
             "env": {"CLAUDE_CODE_AUTO_COMPACT_WINDOW": "1000000", "CLAUDE_CODE_EFFORT_LEVEL": "max",
                     "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1"}},
    "kimi-code": {"token_env": "KIMI_CODE_API_KEY", "token_var": "ANTHROPIC_API_KEY",
                  "base_url": {"global": "https://api.kimi.ai/coding/", "cn": "https://api.kimi.com/coding/"},
                  "models": {"default": "k3-256k", "fast": "k3-256k"},
                  "env": {"CLAUDE_CODE_AUTO_COMPACT_WINDOW": "262144", "CLAUDE_CODE_MAX_CONTEXT_TOKENS": "262144",
                          "CLAUDE_CODE_EFFORT_LEVEL": "high", "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1"}}
  }
}
```

**`provider_settings_env(cfg, provider, tier, region)`** returns:
- `ANTHROPIC_BASE_URL = base_url[region or cfg.region]`
- `ANTHROPIC_MODEL = models[tier]`
- `ANTHROPIC_DEFAULT_OPUS_MODEL = ANTHROPIC_DEFAULT_SONNET_MODEL = ANTHROPIC_DEFAULT_FABLE_MODEL = models.default`
- `ANTHROPIC_DEFAULT_HAIKU_MODEL = models.fast`
- `CLAUDE_CODE_SUBAGENT_MODEL = models.default`
- plus the provider's `env` block.

Callers add `{token_var: os.environ[token_env]}` only when writing the 0600 settings file. Z.ai documents only the
OPUS, SONNET and HAIKU tiers. Setting FABLE as well is harmless, and Moonshot says to set every tier [V].

### 4.10 `bs.py` CLI (B2)

The legacy commands keep v1 semantics and output files: `init`, `status`, `schemas`, `map`, `prepare-screen`,
`screen`, `prepare-tournament [--per-pair]`, `tournament`, `dupcheck [--threshold T]`. New commands and changes:

```
bs.py --version
bs.py map RUN                 + reads pool/_families.json when present (authoritative prefix->family), else merges.json
                                strategy_family (v1); + writes coverage.json
bs.py prepare-screen RUN      judge families = run.json seats.screen_judges (v1 runs: claude, gpt)
bs.py screen RUN              + "## Judge agreement" and "## Own-origin gap" sections (5.7)
bs.py prepare-tournament RUN [--per-pair]   judge families = run.json seats.tournament_judges
bs.py tournament RUN          N families; writes result.md + result.json (5.7)
bs.py quick-pick RUN          quick/curated.json -> quick/finalists.json, tournament/cards.md, origins.json
bs.py arch-matrix RUN         10_ARCHITECTURE/{drivers.json,candidates/map.json,review/judge_*.out.json}
                                -> 10_ARCHITECTURE/{tradeoff-matrix.md,matrix.json}
bs.py lint-arch RUN [--lite]  -> 10_ARCHITECTURE/lint.md + lint.json      exit 0 pass/warn, 1 fail
bs.py lint-proposal RUN [--lite] -> 11_PROPOSAL/lint.md + lint.json       exit 0 pass/warn, 1 fail
bs.py lint-frame RUN          -> frame/lint.json (warnings only; exit 0)
bs.py split RUN --in FILE --root REL --allow GLOB [--allow GLOB ...] [--status-out REL]   exit 0 ok, 5 invalid
bs.py sources RUN             -> sources.json + sources.md (stable S-### ids)
bs.py assumptions RUN         -> 11_PROPOSAL/assumptions.md + 11_PROPOSAL/open-questions.md
bs.py status RUN              + v2 stages when run.json schema 2 exists (12 Architecture: 10_ARCHITECTURE/README.md;
                                13 Proposal: 11_PROPOSAL/PROPOSAL.md; 14 Handoff: 12_HANDOFF.md; stage 11 accepts
                                "RESULT: PENDING" as "designed")
```

**Exit codes:** 0 ok, 1 lint fail, 2 usage, 4 missing input, 5 invalid input. Errors go to stderr.

The engine (B3) runs `bs.py` only as a subprocess and checks the exit code.

`pool/_families.json` (B3 writes it; `bs.py map` reads it) maps every pool prefix to its family:

```json
{"S1": "claude", "S2": "claude", "S3": "gpt", "S4": "claude", "S5": "kimi-alt", "G1": "gpt", "R1": "kimi",
 "L1": "gpt", "IMP": "import", "H": "human", "HP": "human", "H2": "human"}
```

- Human prefixes (`H`, `HP`, `H2`, `H<name>`) are always `human`.
- A substitute run is recorded as `<family>-alt`.

**CURATOR output conversion.** The CURATOR job returns JSON in the `merges` schema:

```
{"axes": [{"name", "values": []}],
 "ideas": [{"key", "title", "pitch", "mechanism", "aliases": [], "cluster", "cell": [], "siblings": [],
            "baseline", "primary"}],
 "notes": {"rerun": [], "leak_check": [], "merge_log": []}}
```

The schema has no free-form maps. The engine converts it into the v1 `merges.json`:
- `axes` becomes a map;
- `strategy_family` is copied from `pool/_families.json`.

The engine also writes `03_POOL_NOTES.md` with sections RE-RUN, LEAK CHECK and Merge log.

`coverage.json`:

```json
{"axes": {"...": ["..."]}, "empty": [["a","b","c"]], "single": [["..."]], "homogenized": true,
 "largest_cluster": {"name": "...", "share": 0.31}, "clusters": 9, "ideas": 64}
```

### 4.11 `ub.py` CLI (B3)

```
ub.py --version
ub.py init      --host H --text "<raw user text>" [--components LIST] [--root DIR] [--lang CODE]
                [--mode M] [--variant V] [--autopilot A] [--families auto|LIST] [--privacy default|private]
                [--seeds-file F] [--idea-file F] [--no-preflight] [--json]          -> prints the G0 card
ub.py next      [RUN] [--wait-s N] [--json]                                          -> one card
ub.py answer    RUN GATE (--file F | --choice X | --default | --skip) [--json]       -> next card
ub.py done      RUN STEP [--json]                               HOST step finished -> validate -> next card
ub.py continue  [RUN] [--host H] [--root DIR] [--json]          newest unfinished run -> its current card
ub.py status    [RUN] [--json]
ub.py plan      [RUN] | --mode M --variant V --families LIST [--json]      calls/tokens/time preview (6.9)
ub.py run       --text "<topic...>" [init options] | --continue [RUN]      terminal mode (6.3)
ub.py stop      RUN                                              tree-kill running workers
ub.py redo      RUN STEP [--yes]                                  supersede STEP and everything downstream
ub.py switch    RUN (--arch LABEL | --idea ID) [--yes]            G13 shortcuts: --arch records G11=LABEL, then redo 12.10;
                                                                  --idea records the new choice, then redo 12.1
ub.py probe-result RUN (PASSED|MISSED|INCONCLUSIVE) [--note-file F]
ub.py import    FILE [RUN]                                        v1 import (pool/IMPORT_<name>.md, resume at stage 5)
ub.py attach-s1 RUN --doc P --raw P                               ce-ideate outputs -> pool/S1_ce-ideate*.md
ub.py render    RUN [--zip]                                       11_PROPOSAL/index.html (+ zip)
ub.py export    RUN --format docx|html                            docx via pandoc when on PATH
ub.py doctor    [--live] [--json]                                 runtime health (family.py detect + engine checks)
ub.py config    get|set KEY [VALUE]                               UB_HOME/config.json
ub.py list      [--root DIR] [--json]                             runs with state
```

**Exit codes:** 0 whenever a card or result was printed (the status lives inside the JSON), 2 usage, 1 internal error.
On an internal error the engine still prints a BLOCKED card when it can.

**`--text` parsing is deterministic.** Leading tokens are consumed while they match, in any order:

| Group | Tokens |
|---|---|
| mode | `quick`, `standard`, `deep`, `proposal` |
| variant | `software`, `product`, `growth`, `research`, `marketing`, `creative`, `naming`, `general` |
| autopilot | `guided`, `full-auto`, `hands-on` |
| options | `private`, `with-ce-ideate` |
| commands | `continue`, `status`, `doctor`, `stop` |

The rest of the text is the topic. In `proposal` mode the rest is the idea. An empty topic produces a HUMAN card that
asks for one.

**Variant inference** runs when no variant token is given:
1. Keyword rules, first match wins:
   - activation, onboarding, retention, churn or conversion -> `growth`;
   - research question, hypothesis, study, paper -> `research`;
   - campaign, ad, brand, marketing -> `marketing`;
   - name for, naming -> `naming`;
   - story, film, art, song, creative -> `creative`;
   - feature, refactor, codebase, API, bug, in this repo -> `software`, when the cwd is a git repo with source files;
   - startup, product, app, business, SaaS, platform -> `product`;
   - otherwise `general`.
2. The kickoff card shows the inferred variant and says how to change it.

### 4.12 Cards, answer files and gates

**Card JSON.** The engine prints it with `--json` and also writes it to `.ub/last_card.json`.

```json
{
  "ub": "2.0.0",
  "run": "C:/p/brainstorm/2026-09-23-night-tutor",
  "runner": "py -3 \"C:/Users/U/.ultimate-brainstorm/kit/skills/ultimate-brainstorm/scripts/ub.py\"",
  "type": "HUMAN",
  "step": "10.5",
  "stage": 10,
  "gate": "G8b",
  "say": "Decision time: 4 red-teamed finalists; the tournament and reviews are done.",
  "progress": {"pct": 71, "stage": 10, "of": 14, "line": "[##########....] 10/14 Decision | 64 ideas -> 11 -> 4 | 91 calls",
               "calls": {"done": 91, "failed": 1, "running": 0, "provisional": 1}, "eta_s": [2400, 4200]},
  "show": "exact text to display",
  "show_file": "C:/p/brainstorm/2026-09-23-night-tutor/gates/G8b.md",
  "answer_file": "C:/p/brainstorm/2026-09-23-night-tutor/answers/G8b.json",
  "answer_template": {"reply": null, "chosen": null, "runner_up": null, "bundle": [], "park": [], "why": null,
                      "accept_recommendation": null},
  "answer_cmd": "py -3 \"C:/.../ub.py\" answer \"C:/p/brainstorm/2026-09-23-night-tutor\" G8b --file \"C:/p/brainstorm/2026-09-23-night-tutor/answers/G8b.json\" --json",
  "default_answer": {"reply": "", "accept_recommendation": true},
  "error": null,
  "task": null,
  "jobs": null,
  "then": "py -3 \"C:/.../ub.py\" next \"C:/p/brainstorm/2026-09-23-night-tutor\" --wait-s 540 --json",
  "next_wait_s": 540,
  "fix": [],
  "notes": ["kimi judged screen as PROVISIONAL kimi-alt (kimi login expired)"]
}
```

**Card types:**

| `type` | Extra fields | Host action |
|---|---|---|
| `AUTO` | `progress`, `then` | Run `then` again |
| `HUMAN` | `gate`, `show`, `answer_file`, `answer_template`, `answer_cmd`, `default_answer`, `error` | Show, wait, write the answer file, run `answer_cmd` |
| `HOST` | `task: {"template": "<abs path SK/templates/host/X.md>", "skill": "<component name or null>", "argument_file": "<abs>", "writes": ["<abs>", ...], "done_cmd": "<runner> done <run> <step> --json"}` | Follow the template, write the files, run `done_cmd` |
| `HOST_BATCH` | `jobs: [{"id", "prompt_file" (abs host variant), "out" (abs), "tools"}]`, `then` | Run one fresh sub-agent per job, then run `then` |
| `DONE` | `show`, plus `links: {"proposal": ..., "pack": ..., "architecture": ...}` | Show and stop |
| `BLOCKED` | `say`, `fix: [commands]`, `error` | Show and stop |

**Answer protocol:**
1. When the engine issues a HUMAN card, it deletes any stale `answer_file`. The host writes a NEW file there
   containing `answer_template` with the fields filled in. `reply` must hold the user's exact words.
2. `ub answer ... --file` validates the file and archives it to `answers/<GATE>.json`.
   - If the answer is valid, the engine returns the next card.
   - If not, it returns the same gate with `error` set.
3. The simple forms `--choice X`, `--default` and `--skip` exist for letters, IDs and yes/no answers. They are safe in
   every shell.

**Gate list** (answer_template fields; the `default_answer` is used in full-auto and by the test answerer):

| Gate | When | Fields beyond `reply` | Default |
|---|---|---|---|
| G0 kickoff | all modes | `confirm` (bool), `topic`, `mode`, `variant`, `autopilot`, `private` (bool), `privacy`{`web`,`vendors`,`code`}, `families` (list), `with_ce_ideate` (bool), `seeds`{`problem`,`primary`,`ideas`[],`obvious`[],`off_limits`[]}, `skip_seeds` (bool), `quick`{`criteria`[3 names], `hard_constraint`}, `idea` (proposal mode) | `confirm: true, skip_seeds: true` (full-auto asks G0 once only when `config.privacy_defaults` is unset) |
| G1 seeds | hands-on, when no seeds came with G0 | `done` (bool), `skip` (bool) | not used |
| G2 frame questions | express frame path | `answers`[{`q`: id, `a`: text}], `accept_defaults` (bool) | `accept_defaults: true` |
| G2c frame confirm | hands-on | `confirm` (bool), `corrections` | `confirm: true` |
| G2f footprint | software/growth, only when CONTEXT.md or docs/adr changed during framing | `restore` (bool) | never auto; always asks |
| G3 round 2 | hands-on | `ideas`[], `cells`[] | not used |
| G4 rescues | hands-on | `rescue`[{`id`,`reason`}], `confirm_flags`[] | not used |
| G5 K4 confirm | hands-on | `kill`[], `keep`[] | not used |
| G6 finalists | hands-on, more than 8 survivors | `finalists`[] | not used |
| G7 red-team picks | hands-on | `picks`[] | not used |
| G8a gut pick | all except full-auto | `picks`[] (up to 3 IDs, ordered), `skip` (bool), `notes` | `skip: true` |
| G8b decide | all | `chosen`, `runner_up`, `bundle`[] (growth), `park`[], `why` (user words), `accept_recommendation` (bool) | `accept_recommendation: true` (stamped AUTO-DECISION) |
| G9 probe result | hands-on (blocking); other presets use `ub probe-result` later | `result` (PASSED, MISSED or INCONCLUSIVE), `note` | not used |
| G10 drivers | hands-on, deep | `confirm`, `corrections` | `confirm: true` |
| G11 architecture | standard, deep, proposal (quick: auto) | `choice` (label), `steal`[{`from`,`element`}], `notes`, `accept_recommendation` | `accept_recommendation: true` |
| G12 ADRs | hands-on, deep | `accept`[], `reject`[] | not used (guided bundles ADR acceptance into G13) |
| G13 sign-off | all | `action` (`approve`, `changes`, `switch` or `runner-up`), `changes`, `switch_to` | `action: approve` in guided; in full-auto the result stays DRAFT with the AUTOPILOT banner |
| G14 handoff | all but full-auto | `publish` (bool), `merge_terms` (all, some, none or defer), `terms`[], `handoff` (ce, speckit, superpowers, openspec or none) | `publish: false, handoff: none` |
| GB budget | cap reached | `raise_to` (int), `stop` (bool) | full-auto: stop (BLOCKED) |
| GX whole effort | FRAME kill condition met, or synthesis says STOP | `action` (`reframe`, `continue` or `stop`) | always asks, even in full-auto |

### 4.13 Host rules (SKILL.md <-> engine)

- The host never computes anything the engine prints.
- The host never opens `tournament/`, `screen/` or `review/` outputs while a HUMAN card is pending.
- On HUMAN cards the host shows `show` exactly. A faithful translation is allowed when the user writes in another
  language.
- When a card has 2-4 options, Claude Code and Kimi may ask the question with their question tool. Everything else is
  asked in plain text.

The full SKILL.md skeleton is in section 6.13.

### 4.14 Installer CLI, plan JSON, manifest, marker (B1 implements, B4 tests)

```
install.py [plan] [--json]                       default; detects and prints the plan; writes nothing
install.py install [--yes] [--json]              plan -> one confirmation (needs a TTY or --yes) -> apply
install.py update  [--yes] [--json]              re-stage kit (local source or --tag) -> plan -> apply
install.py uninstall [--yes] [--purge] [--json]
install.py doctor [--live] [--json]              read-only; exit 1 on any FAIL
install.py list [--json]
install.py setup-glm  [--region global|cn] [--launcher] [--codex] [--zai-mcp] [--yes]
install.py setup-kimi [--provider kimi|kimi-code] [--region global|cn] [--launcher] [--codex] [--yes]
install.py version
common flags: --agents auto|claude-code,codex,kimi,zcode   --scope user|project   --project-dir DIR
              --source DIR|github   --tag vX.Y.Z   --components core|none|core,+<extra>,...
              --with-clis claude,codex,kimi   --login   --force   --migrate-v1   --routing-block
              --claude-config-dir DIR   --codex-home DIR   --kimi-home DIR   --no-native   --backup-dir DIR
```

**Exit codes:**

| Code | Meaning |
|---|---|
| 0 | ok (including "nothing to do") |
| 1 | failure |
| 2 | usage |
| 3 | no supported agent detected and none named (prints how to install one) |
| 4 | blocked rows present with `--yes` |
| 5 | cancelled by the user |

**Plan JSON.** The text plan shows the same rows as a table.

```json
{"schema":1,"kit":{"name":"ultimate-brainstorm","version":"2.0.0","source":"<kit>","commit":"local"},
 "system":{"os":"windows","python":"3.11.9 (py -3)","git":"2.51.0","node":"24.1.0","git_bash":"C:/Program Files/Git/bin/bash.exe"},
 "agents":{"claude-code":{"detected":true,"version":"2.1.280","home":"C:/Users/U/.claude","route":"native"},
           "codex":{"detected":true,"version":"0.156.1","home":"C:/Users/U/.codex","route":"native"},
           "kimi":{"detected":true,"version":"2.0.2","home":"C:/Users/U/.kimi-code","route":"copy"},
           "zcode":{"detected":false,"route":"skip"}},
 "rows":[{"n":1,"agent":"all","item":"stage kit","action":"create","how":"copy","path":"C:/Users/U/.ultimate-brainstorm/kit","commands":[]},
         {"n":2,"agent":"claude-code","item":"plugin ultimate-brainstorm","action":"install","how":"native",
          "path":null,"commands":[["claude","plugin","marketplace","add","C:/Users/U/.ultimate-brainstorm/kit"],
                                  ["claude","plugin","install","ultimate-brainstorm@ultimate-brainstorm","--scope","user"]]}],
 "warnings":["~/.claude/skills/ultimate-brainstorm exists (v1, not owned): use --migrate-v1 to back it up and replace it"],
 "manual":["In Kimi Code: /plugins install https://github.com/EveryInc/compound-engineering-plugin then /reload"],
 "next":["Start Claude Code in your project and type: /ultimate-brainstorm <your topic>"]}
```

**Row `action`** is one of `create`, `update`, `unchanged`, `backup+update`, `install`, `remove`, `skip-not-owned`,
`migrate-v1`, `manual`, `blocked`.
**Row `how`** is one of `copy`, `native`, `npx`, `npm`, `print`.

**Manifest** `UB_HOME/install-manifest.json`:

```json
{"schema":1,"kit":"ultimate-brainstorm","version":"2.0.0","commit":"local","installed_at":"...",
 "entries":[{"agent":"kimi","route":"copy","path":"C:/Users/U/.kimi-code/skills/ultimate-brainstorm",
             "files":{"SKILL.md":"<sha256>","scripts/ub.py":"<sha256>"}},
            {"agent":"claude-code","route":"native","marketplace":"ultimate-brainstorm",
             "plugin":"ultimate-brainstorm@ultimate-brainstorm","scope":"user","config_dir":"C:/Users/U/.claude"}],
 "components":[{"id":"compound-engineering","agent":"claude-code","route":"native","ref":"compound-engineering-v3.28.2"}],
 "launchers":["C:/Users/U/.ultimate-brainstorm/bin/claude-glm"],
 "routing_blocks":[]}
```

**Marker** `<copy dir>/.ub-owned`:

```json
{"kit":"ultimate-brainstorm","version":"2.0.0","installed_at":"...","manifest":"<abs manifest path>"}
```

### 4.15 `targets.json` and `components.json` (B1)

```json
{
  "schema": 1,
  "verified": "2026-09-23: claude-code 2.1.280, codex rust-v0.156.1, kimi-code 2.0.2, skills 1.7.0, ZCode docs 3.4.0",
  "kit": {"name": "ultimate-brainstorm", "repo": "OWNER/ultimate-brainstorm", "skill": "ultimate-brainstorm",
          "marker": ".ub-owned", "marketplace": "ultimate-brainstorm", "plugin": "ultimate-brainstorm"},
  "runtime_paths": [".claude-plugin", ".codex-plugin", ".agents", ".kimi-plugin", "bundles", "skills", "profiles",
                    "install", "docs", "README.md", "LICENSE", "NOTICE.md", "VERSION", "CHANGELOG.md"],
  "agents": {
    "claude-code": {
      "detect": {"bin": "claude", "home": ["$CLAUDE_CONFIG_DIR", "~/.claude"]},
      "native": {"min": "2.1.268",
        "marketplace_add": ["claude", "plugin", "marketplace", "add", "{kit_dir}"],
        "install": ["claude", "plugin", "install", "ultimate-brainstorm@ultimate-brainstorm", "--scope", "{claude_scope}"],
        "list": ["claude", "plugin", "list", "--json"],
        "uninstall": ["claude", "plugin", "uninstall", "ultimate-brainstorm@ultimate-brainstorm"],
        "marketplace_remove": ["claude", "plugin", "marketplace", "remove", "ultimate-brainstorm"]},
      "copy": {"user": "{claude_home}/skills", "project": "{project}/.claude/skills"},
      "invoke": "/ultimate-brainstorm <topic>", "reload": "start a new session or run /reload-plugins"},
    "codex": {
      "detect": {"bin": "codex", "home": ["$CODEX_HOME", "~/.codex"]},
      "native": {"min": "0.156.0",
        "marketplace_add": ["codex", "plugin", "marketplace", "add", "{kit_dir}", "--json"],
        "install": ["codex", "plugin", "add", "ultimate-brainstorm@ultimate-brainstorm", "--json"],
        "list": ["codex", "plugin", "list", "--json"],
        "uninstall": ["codex", "plugin", "remove", "ultimate-brainstorm@ultimate-brainstorm", "--json"],
        "marketplace_remove": ["codex", "plugin", "marketplace", "remove", "ultimate-brainstorm", "--json"]},
      "copy": {"user": "~/.agents/skills", "project": "{project}/.agents/skills"},
      "invoke": "$ultimate-brainstorm <topic>", "reload": "restart Codex"},
    "kimi": {
      "detect": {"bin": "kimi", "min": "2.0.0", "home": ["$KIMI_CODE_HOME", "~/.kimi-code"], "legacy_home": "~/.kimi",
                 "windows_requires": "git-bash"},
      "copy": {"user": "{kimi_home}/skills", "project": "{project}/.kimi-code/skills"},
      "manual_native": "/plugins install {kit_dir}   then /reload",
      "invoke": "/skill:ultimate-brainstorm <topic>", "reload": "/reload or /new"},
    "zcode": {
      "detect": {"home": ["~/.zcode"], "apps": ["/Applications/ZCode.app"]},
      "copy": {"user": "~/.zcode/skills", "project": "{project}/.zcode/skills"},
      "manual_native": "ZCode > Settings > Plugins > add a local directory or GitHub marketplace: {kit_dir}",
      "invoke": "$ultimate-brainstorm <topic>", "reload": "restart ZCode"}
  }
}
```

```json
{
  "schema": 1,
  "verified": "2026-09-23",
  "core": ["compound-engineering", "mattpocock-grilling"],
  "components": {
    "compound-engineering": {
      "ref": "compound-engineering-v3.28.2",
      "claude-code": {"steps": [["claude","plugin","marketplace","add","EveryInc/compound-engineering-plugin@compound-engineering-v3.28.2"]],
                      "install_resolve": {"plugin": "compound-engineering", "source_match": "EveryInc/compound-engineering-plugin"},
                      "manual": "/plugin marketplace add EveryInc/compound-engineering-plugin  then  /plugin install compound-engineering"},
      "codex": {"steps": [["codex","plugin","marketplace","add","EveryInc/compound-engineering-plugin@compound-engineering-v3.28.2","--json"],
                          ["codex","plugin","add","compound-engineering@compound-engineering-plugin","--json"]]},
      "kimi": {"manual": "/plugins install https://github.com/EveryInc/compound-engineering-plugin/releases/tag/compound-engineering-v3.28.2  then /reload"},
      "zcode": {"manual": "ZCode > Settings > Plugins > add marketplace EveryInc/compound-engineering-plugin"}},
    "mattpocock-grilling": {
      "needs": {"node": "22.20.0"}, "env": {"DISABLE_TELEMETRY": "1"},
      "claude-code": {"steps": [["npx","-y","skills@1.7.0","add","mattpocock/skills","--skill","grilling","--skill","domain-modeling","-g","-a","claude-code","--copy","-y"]]},
      "codex":       {"cwd": "~", "steps": [["npx","-y","skills@1.7.0","add","mattpocock/skills","--skill","grilling","--skill","domain-modeling","-a","codex","-y"]]},
      "kimi":        {"steps": [["npx","-y","skills@1.7.0","add","mattpocock/skills","--skill","grilling","--skill","domain-modeling","-g","-a","kimi-code-cli","--copy","-y"]],
                      "skip_if_codex_step_ran": true},
      "zcode":       {"steps": [["npx","-y","skills@1.7.0","add","mattpocock/skills","--skill","grilling","--skill","domain-modeling","-g","-a","zcode","--copy","-y"]]}},
    "pm-skills": {"extra": true, "claude-code": {"steps": [["claude","plugin","marketplace","add","phuryn/pm-skills"],["claude","plugin","install","pm-product-discovery@pm-skills"],["claude","plugin","install","pm-execution@pm-skills"]]},
                  "codex": {"steps": [["codex","plugin","marketplace","add","phuryn/pm-skills","--json"],["codex","plugin","add","pm-product-discovery@pm-skills","--json"],["codex","plugin","add","pm-execution@pm-skills","--json"]]}},
    "speckit": {"extra": true, "all": {"steps": [["uv","tool","install","specify-cli"]]}},
    "bmad": {"extra": true, "all": {"manual": "npx bmad-method install  (pick your tool; needs Node 20.12+, uv, Python 3.10+)"}},
    "claude-council": {"extra": true, "claude-code": {"manual": "/plugin marketplace add hex/claude-marketplace  then  /plugin install claude-council"}},
    "idea-reality": {"extra": true, "claude-code": {"manual": "claude mcp add --env GITHUB_TOKEN=<token> --transport stdio idea-reality -- uvx idea-reality-mcp"}}
  },
  "clis": {
    "codex":  {"npm": "@openai/codex", "login": ["codex", "login"]},
    "claude": {"npm": "@anthropic-ai/claude-code", "login_hint": "run `claude` once and sign in"},
    "kimi":   {"npm": "@moonshot-ai/kimi-code", "node": "22.19.0", "login": ["kimi", "login"],
               "windows_requires": "Git for Windows (Git Bash) or KIMI_SHELL_PATH"}
  }
}
```

**`install_resolve` for Compound Engineering in Claude Code** [U]. The name of CE's Claude marketplace is not verified.
1. After `marketplace add`, run `claude plugin marketplace list --json`.
2. Find the entry whose source matches `source_match` and read its name.
3. Run `claude plugin install compound-engineering@<name> --scope user`.
4. If the list output cannot be parsed, the row becomes `manual` with the guide's in-session commands.

### 4.16 Launchers and Codex homes (B1)

**Launchers.** `install.py setup-glm --launcher` and `setup-kimi --launcher` write launchers into `UB_HOME/bin/` from
the `profiles/*.tpl` templates:
- `claude-glm`, `claude-glm.cmd`, `claude-glm.ps1`
- `claude-kimi` (and the `.cmd` and `.ps1` forms)
- `codex-glm`, `codex-kimi` (with `--codex`)
- `ub`, `ub.cmd`, `ub.ps1` (always)

Each launcher calls `PY UB_HOME/kit/profiles/launch.py <tool> --provider <p> -- <args>`. `launch.py`:

1. Loads `SK/scripts/families.default.json`, deep-merged with `UB_HOME/families.json`. B1 writes its own small merge;
   it does not import `ublib`.
2. Requires the provider's `token_env` in the environment. If it is missing, prints `Set <VAR> first (see
   docs/FAMILIES.md)` and exits 2.
3. For `claude`:
   - Writes `UB_HOME/tmp/launch-<pid>-<rand>.json` with mode 0600 and content
     `{"env": provider_settings_env(...) + {token_var: value}}`.
   - Sets `UB_HOST_FAMILY=<glm|kimi>`.
   - Runs `claude --settings <file> <args>`, waits for it, deletes the file in `finally`, and returns claude's exit code.
   - With `--zai-mcp` (GLM only), it also renders `zai-mcp.json.tpl` to a temporary 0600 file and adds
     `--mcp-config <file>`.
4. For `codex`: sets `CODEX_HOME=UB_HOME/codex-homes/<p>` and `UB_HOST_FAMILY`, then runs `codex <args>`.
5. The user's `~/.claude/settings.json` and `~/.codex/config.toml` are never touched. [V] `--settings` outranks user
   settings for that session, and settings-file env beats shell exports.

**Codex homes.** These are written by `setup-glm --codex` and `setup-kimi --codex`, never contain secrets, and are also
used by the adapter's `codex-cli@glm` and `codex-cli@kimi` backends:

```toml
# UB_HOME/codex-homes/glm/config.toml   (cn region: base_url = "https://open.bigmodel.cn/api/v1")
model = "glm-5.3"
model_provider = "zai"
model_reasoning_effort = "high"
[model_providers.zai]
name = "Z.ai"
base_url = "https://api.z.ai/api/v1"
env_key = "ZAI_API_KEY"
wire_api = "responses"
```

```toml
# UB_HOME/codex-homes/kimi/config.toml
model = "kimi-k3"
model_provider = "kimi"
model_context_window = 1048576
[model_providers.kimi]
name = "Kimi"
base_url = "https://api.moonshot.ai/v1"
env_key = "KIMI_API_KEY"
wire_api = "responses"
```

Notes on the Codex homes:
- Never use `experimental_bearer_token`, `wire_api = "chat"` or `[profiles.*]` tables. [V] All three are discouraged or
  removed.
- `model_catalog_json` is omitted [U], so Codex prints a metadata warning. That is expected.
- `setup-glm --codex` / `setup-kimi --codex` then runs the Codex plugin commands with `CODEX_HOME` set to that home, so
  Codex running on GLM or Kimi also has the kit.

### 4.17 Stub responder API (B4 implements; the B2 `stub` backend calls it)

```python
# SK/scripts/ublib/stubs.py
def respond(job: dict, prompt_text: str) -> str:
    """Return raw model-like output text that satisfies job["contract"] (and FILE protocol + STATUS for "files").
    Deterministic: seeded by job["id"]. Reads optional job["stub"] facts. Honors UB_STUB_FAIL (raise StubFailure for
    matching job ids), UB_STUB_DELAY_S (sleep), UB_STUB_HOMOGENIZED (curator puts > 25% of ideas in one cluster)."""
class StubFailure(Exception): ...
```

**Facts B3 must put in `job["stub"]`** (a stub with no facts must still produce valid, generic output):

| Job | Facts |
|---|---|
| generators | `axes`: {axis: [values]} |
| curator | `aliases`: [raw alias IDs found in the pool], `axes`, `primary_aliases`: [...] |
| screen judge | IDs come from `contract.cover` |
| checker | `idea_id` |
| normalizer | IDs come from `contract.ids` |
| tournament judge | pair IDs come from `contract.cover` |
| reviewer | `stance`, `idea_id` |
| arch-author | `qas_ids`, `hc_ids` |
| arch-judge | `labels`, `criteria` (QG ids + fixed) |
| package writers | `containers` (from the chosen candidate JSON), `qg_ids`, `ext_ids`, `r_ids` |
| proposal writers | `sections` (required heading list), `adr_numbers`, `r_ids`, `source_ids` |

Expectations for stub output:
- **Must:** the pipeline reaches DONE in every mode.
- **Should:** stub packages also pass `lint-arch` and `lint-proposal`, using the facts above.

### 4.18 Fake CLI protocol (B4)

`tests/harness/fakecli.py <tool> [args...]`, where `<tool>` is `claude`, `codex`, `kimi` or `npx`.
`tests/harness/shims.py` installs the fakes into a temporary `bin/`:
- POSIX: executable copies with a shebang.
- Windows: `.cmd` shims `@"%UB_FAKE_PY%" "%~dp0fakecli.py" <tool> %*`, so the real `.cmd` quoting path is exercised.

**Scenario rules** come from the JSON list at `UB_FAKE_SCENARIO`; the first match wins:

```json
[{"tool": "codex", "argv_regex": "\\bexec\\b", "action": "stub"},
 {"tool": "claude", "argv_regex": "--version", "stdout": "2.1.280 (Claude Code)\n", "exit": 0},
 {"tool": "kimi", "argv_regex": "-p", "action": "fail", "exit": 1, "stderr": "not logged in"},
 {"tool": "codex", "argv_regex": "plugin list --json", "stdout": "{\"plugins\":[]}", "exit": 0},
 {"tool": "npx", "argv_regex": "skills@1.7.0 add", "action": "record", "create_dirs": ["~/.claude/skills/grilling"]}]
```

**Actions:**

| Action | Behavior |
|---|---|
| `stub` | Read `UB_JOB_FILE`, call `ublib.stubs.respond`, emit in the tool's native format (below) |
| `fail` | Exit with the given code and stderr |
| `sleep` | Sleep `sleep_s` seconds |
| `garbage`, `fence`, `utf16`, `bom`, `empty`, `is_error` | Output corruption cases |
| `record` | Log the call and create the listed dirs |
| `static` | Print the given `stdout` |

**Native formats:**

| Tool | Format |
|---|---|
| `claude -p` | stdout `{"type":"result","subtype":"success","is_error":false,"result":"<text>","total_cost_usd":0,"session_id":"fake"}` (`is_error` case: `subtype` `error_during_execution`) |
| `codex exec` | Writes `<text>` to the `-o` file. With `--json`, prints JSONL `{"type":"thread.started"}`, `{"type":"item.completed","item":{"type":"agent_message","text":"<text>"}}`, `{"type":"turn.completed","usage":{"input_tokens":10,"output_tokens":20}}` |
| `kimi -p --output-format stream-json` | Reads the prompt from the `--agent-file` body. Prints `{"role":"assistant","content":"<text>"}`. A variant scenario emits a tool call, a tool message, then the final assistant message with content given as `[{"type":"text","text":"..."}]` |

**Logging.** Every call appends this to `UB_FAKE_LOG`:

```json
{"tool": "codex", "argv": ["exec", "--skip-git-repo-check", "..."], "cwd": "C:/tmp/ub-empty-1",
 "env_names": ["CODEX_HOME", "UB_JOB_ID", "UB_JOB_FILE"], "stdin_sha256": "<hex>", "job_id": "4.2-S3"}
```

`env_names` lists variable NAMES only.

### 4.19 Test hooks in product code (allowed, and only these)

| Hook | Where | Effect |
|---|---|---|
| `UB_TEST_CRASH_AT` | engine | Exit 99 after the named step's jobs finish, before the step is marked done |
| `UB_FAKE_*`, `UB_STUB_*` | detect, families, stubs | Fake families and stub behavior |
| `UB_NO_DETACH` | batch | Workers run attached |
| `UB_HEARTBEAT_STALE_S` | batch | Overrides the 60 s stale-heartbeat threshold (tests use 3) |
| `UB_INSTALL_OFFLINE`, `UB_RELEASE_DIR` | installer, shims | No network; local release assets |

No other test-only branches may exist.

---

## 5. Model-family adapter and bookkeeping (B2 detail)

### 5.1 Families, seats and backends

- A **family** is a model vendor line: `claude`, `gpt`, `kimi` or `glm`.
- A **seat** is a role in the pipeline. B3 assigns seats (section 6.6).
- A **backend** is how a family is reached. The family is decided by the endpoint, not by the binary. For example,
  `claude -p` against api.z.ai is the `glm` family.
- `<family>-alt` means the same vendor with `alt_model` if one is set, otherwise the same model in a fresh context.
  It is always PROVISIONAL.

### 5.2 Backend command lines (exact)

All backends start their process with an argv list, read the prompt from `prompt_file` (UTF-8), and never place prompt
text in argv.

**Claude Code CLI** (`claude-cli`, plus the provider variants `@glm`, `@kimi`, `@kimi-code`):

```
argv: [claude, "-p", "Follow the instructions in the piped input exactly. Output only the requested result.",
       "--output-format", "json", "--no-session-persistence",
       "--strict-mcp-config", "--mcp-config", UB_HOME/tmp/empty-mcp.json, "--disallowedTools", "mcp__*"]
  tools none : + ["--tools", "", "--max-turns", "3"]
  tools web  : + ["--tools", "WebSearch,WebFetch", "--allowedTools", "WebSearch,WebFetch", "--max-turns", "40"]
  tools read : + ["--tools", "Read,Grep,Glob", "--allowedTools", "Read,Grep,Glob", "--max-turns", "30"]
  tier fast (native only) : + ["--model", "haiku"]        alt seat (native only): + ["--model", alt_model]
  provider backends: + ["--settings", <0600 temp file: {"env": provider_settings_env(...) + {token_var: token}}>]
                     (tier is expressed by ANTHROPIC_MODEL inside the settings env; no --model flag)
stdin: prompt bytes          cwd: empty temp dir (none/web) | repo_root (read)
empty-mcp.json: {"mcpServers":{}}  written once by the adapter
parse: stdout = one JSON object with type "result": ok iff is_error == false and subtype == "success"; text = .result;
       usage from .usage and .total_cost_usd when present. Auth-looking failures (401/403, "login", "invalid api key")
       -> error_class auth, no retry, family unavailable for this run.
never: --bare (drops OAuth), --json-schema unless backend native_schema true AND the exe is not .cmd/.bat [U-12],
       inline --settings JSON (would be visible in the process list).
```

- `--tools ""` passes an empty argv element. If the `.cmd`-shim test shows the element is dropped, switch to the
  `--tools=` spelling for `.cmd` executables only. [U-13]

**Codex CLI** (`codex-cli`, plus the variants `@glm`, `@kimi`):

```
argv: [codex, "exec", "--skip-git-repo-check", "--ephemeral", "-s", "read-only", "-C", CWD,
       "-o", <tmp>/last.txt, "--json"]
  native_schema true (OpenAI backend) and job has schema_file: + ["--output-schema", <abs schema>]
  model configured: + ["-m", model]             web jobs: + ["-c", "web_search=live"]   [L; U-5 fallback]
  final element: "-"          (prompt on stdin)
env: CODEX_HOME = backend codex_home for provider variants; user CODEX_HOME otherwise
parse: text = <tmp>/last.txt (tolerant decode); usage = last "turn.completed" JSONL event when present.
never: --full-auto (removed 2026-07-30), --yolo, --dangerously-*, wire_api="chat", [profiles.*]
cwd (process) = CWD as well.
```

**Kimi Code CLI v2** (`kimi-cli`):

```
files: <tmp>/ub-<job-id>-agent.md :
  ---
  name: ub-oneshot
  description: Isolated one-shot worker for ultimate-brainstorm. The final message is the complete result.
  tools: []                      # web: [WebSearch, FetchURL]   read: [Read, Grep, Glob]
  subagents: []
  ---
  <prompt, with every "${identifier}" rewritten as "$ {identifier}">
  <tmp>/ub-empty-skills/  (empty dir)
argv: [kimi, "--agent-file", <agent.md>, "--skills-dir", <empty-skills>, "--output-format", "stream-json",
       ("-m", model when configured), "-p", "Carry out the task in your system instructions now. Output only the requested result."]
cwd: empty temp dir (process cwd; there is no --work-dir flag [V]); no .git there, so no project skills or agents load
env add: KIMI_CODE_NO_AUTO_UPDATE=1, KIMI_CODE_BACKGROUND_PRINT_BACKGROUND_MODE=exit,
         KIMI_LOOP_MAX_STEPS_PER_TURN=4 (none) | 40 (web/read)        [all V]
parse (tolerant, [U-2]): each stdout line is JSON; role = obj.role or obj.type or obj.message.role; keep objects with
      role "assistant"; content = string | list of {type:"text",text} | obj.message.content; drop objects that carry a
      non-empty tool_calls; the result = the text of the LAST assistant object after the last tool message. Save the raw
      JSONL of the first 3 live calls to UB_HOME/tmp/kimi-samples/ for fixture capture.
never: --yolo, --auto, --plan (rejected together with -p [V]); never a GLM Coding Plan key via KIMI_MODEL_* (policy)
```

**HTTP backends** (`openai-chat-http`, `anthropic-http`) use stdlib `urllib`, are off unless configured, and require a
model.
- OpenAI chat: `POST url` with `Authorization: Bearer $KEY` and body
  `{"model", "messages":[{"role":"user","content":P}], "max_tokens": 16000}`. The output is
  `choices[0].message.content`.
- Anthropic: `POST url` with `x-api-key: $KEY` and `anthropic-version: 2023-06-01`, and body
  `{"model", "max_tokens": 16000, "messages":[...]}`. The output is the concatenated text blocks.
- On 429 or 5xx, back off exponentially and honor `Retry-After`, with at most 2 retries. HTTP backends have no tools.

**`stub`.** When `UB_FAKE_FAMILIES=1`, the chain is `["stub"]`. Output is `ublib.stubs.respond(job, prompt)`, run
through the same validation path.

**`host`.** A worker never executes this backend. When the driver sees a job whose resolved chain is `["host"]`, it
emits a HOST_BATCH card (section 6.3).

### 5.3 Environment policy for child processes

**Denylist.** These are removed from every child environment:
- `ANTHROPIC_*`
- `CLAUDE_CODE_SUBAGENT_MODEL`, `CLAUDE_CODE_MAX_CONTEXT_TOKENS`, `CLAUDE_CODE_AUTO_COMPACT_WINDOW`,
  `CLAUDE_CODE_EFFORT_LEVEL`
- `CLAUDECODE`, `CLAUDE_CODE_CHILD_SESSION`
- `OPENAI_API_KEY`, `OPENAI_BASE_URL`, `CODEX_API_KEY`, `CODEX_HOME`
- `KIMI_MODEL_*`, `KIMI_API_KEY`, `KIMI_CODE_API_KEY`
- `ZAI_API_KEY`, `ZAI_PAYG_API_KEY`, `Z_AI_API_KEY`
- `API_TIMEOUT_MS`
- `UB_HOST_FAMILY`

**Always set:** `UB_JOB_ID`, `UB_JOB_FILE`, `NO_COLOR=1`. `UB_FAKE_*` and `UB_STUB_*` pass through.

**Add-back per backend:**

| Backend | Added back |
|---|---|
| `claude-cli` (native) | The user's `ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN` and `ANTHROPIC_BASE_URL`, only when the original `ANTHROPIC_BASE_URL` is unset or on an `anthropic.com` host. Otherwise nothing, so the child uses the subscription login |
| `claude-cli@<provider>` | Nothing. The token goes only into the settings file |
| `codex-cli` (native) | The user's `OPENAI_API_KEY`, `CODEX_API_KEY`, `OPENAI_BASE_URL`, `CODEX_HOME` |
| `codex-cli@<p>` | `CODEX_HOME` = the backend home, plus the backend's `token_env` value |
| `kimi-cli` | Nothing extra. `KIMI_CODE_HOME` and `KIMI_SHELL_PATH` are not on the denylist. With `env_model: true`, the user's `KIMI_MODEL_*` are also added back |

Why: a host started by `claude-glm` exports `ANTHROPIC_BASE_URL=z.ai`. Without the denylist, the "claude" family would
silently become GLM.

### 5.4 Safe defaults for every call

| Aspect | Rule |
|---|---|
| Tools | `none` for generators, judges, curator, normalizer, synthesis, document writers, rubric and fixer. `web` only for researcher, checker, S4-TRANSFER, STACK-VERIFY and the review lens `web-verified tech`. `read` only for researcher and checker in software/growth runs, and only on the host vendor's family unless privacy `code` = yes |
| Isolation | Empty cwd. Every prompt is assembled by the engine from files, never from pool content inside a generator prompt. Every isolated-call template starts with `Do not load or invoke any skill; this prompt is the whole task.` |
| Writes | The adapter writes only `out`, `<out>.meta.json`, `<out>.failed.md`, split files inside `split.root` that match the allowlist, the status file, logs and temporary files under `UB_HOME/tmp` |
| Timeouts | Per kind (`families.default.json`). On timeout the process tree is killed: Windows `taskkill /PID <pid> /T /F`; POSIX `killpg` with SIGTERM, then SIGKILL after 5 s |
| Retries | 1 retry after a non-zero exit, empty output or unparseable output. No retry after auth errors or policy refusals. One repair call after invalid output |
| Chain | Try backends in chain order. Move to the next backend only on `unavailable`, `auth`, `not_found` or `network` errors, or after retries are exhausted |
| Fallback | After the whole chain fails, the driver (B3) applies `job.fallback` as a new job with suffix `~<fam>` and `provisional: true`. Never silent: `<out>.failed.md` is kept |
| Output cap | 2 MB. Larger output is truncated and counts as invalid |
| Secrets | Read only from environment variables into 0600 temp files, which are deleted afterwards. Logs, meta and `calls.jsonl` are redacted |
| Windows | Python handles all piping. `.cmd` argument-safety check (3.1). Output decoded as UTF-8 with errors="replace" |

### 5.5 Detection, reclassification, preflight

- **CLIs.** Run `claude --version`, `codex --version`, `kimi --version`, each with a 15 s timeout, and parse the
  versions. Kimi below 2.0 means the legacy archived kimi-cli: the family is marked unavailable with the note
  `upgrade: npm install -g @moonshot-ai/kimi-code, then kimi migrate`.
- **Which family a `claude-cli` install really serves:**
  1. Look at `env.ANTHROPIC_BASE_URL` in `$CLAUDE_CONFIG_DIR/settings.json` (or `~/.claude/settings.json`), then at the
     process environment.
  2. Unset or `anthropic.com` means the family is `claude`.
  3. `z.ai` or `bigmodel.cn` means `glm`. `moonshot`, `kimi.ai` or `kimi.com` means `kimi`. Any other host becomes
     `custom:<host>` and is unused.
  4. If the settings file itself is foreign, the native `claude-cli` backend of the `claude` family is unavailable. It
     is re-listed as an extra backend of the family it really serves, and the change goes into `reclassified`.
- **Codex:** read `$CODEX_HOME/config.toml` (default `~/.codex`), using `tomllib` when available and otherwise a regex
  for the top-level `model_provider` and that provider's `base_url`. The provider `openai` or unset means `gpt`;
  `z.ai` or `bigmodel` means `glm`; `moonshot` means `kimi`.
- **Kimi credentials:** check for `$KIMI_CODE_HOME/credentials/` (default `~/.kimi-code/credentials/`) or
  `KIMI_MODEL_NAME`. If neither exists, the family is unavailable with the note `run: kimi login`.
- **Provider backends** are available when their `token_env` is set and their exe exists. `codex-cli@glm` and
  `codex-cli@kimi` also need their Codex home folder.
- **Host family, in order:** `UB_HOST_FAMILY`; the host agent's resolved endpoint (same rules as above); the default
  for the agent (claude-code = claude, codex = gpt, kimi = kimi, zcode = glm).
- **Web capability** comes from the static `web` flag of the selected backend. Kimi web is `false` unless the user sets
  `kimi-cli.web: true`. [U-3]
- **Live preflight** (`--live`, and B3 at init unless `--no-preflight`): one parallel `ping` job per candidate family,
  prompt `Reply with the single word PONG.`, contract `text` with regex `PONG`, 60 s timeout. A failure marks the
  family unavailable and records the fix (for example `kimi login`).

### 5.6 Policy guards (worker exit 7, `error_class` policy)

The worker refuses a job, with exit 7, in these cases:
1. The job family's vendor is not in `run.json.privacy.allowed_vendors`.
2. `tools` includes `web` while `privacy.web` is false.
3. `cwd: repo` on a family that is not the host vendor while `privacy.code` is false.
4. An `openai-chat-http` backend whose URL host is `api.z.ai` or `open.bigmodel.cn`, when its `key_env` is `ZAI_API_KEY`
   or its URL path contains `/coding/`. The GLM Coding Plan may only be used through supported tools.
5. A `kimi-cli` job with `env_model: true` whose `KIMI_MODEL_BASE_URL` points at `z.ai` or `bigmodel.cn`. Kimi Code is
   not a GLM-supported tool.
6. `families.glm.allow_scripted_plan_use` is false and the job would call `claude-cli@glm` or `codex-cli@glm` from a
   worker. In this strict mode GLM runs only as the host family, through HOST_BATCH.

### 5.7 `bs.py` generalized to N families

**Common rules:**
- Judge family lists come from `run.json` (`seats.screen_judges`, `seats.tournament_judges`). Runs without `run.json`
  (v1) use `["claude", "gpt"]` and v1 behavior. v1 golden outputs must match byte for byte.
- Vendor map: `claude` = anthropic, `gpt` = openai, `kimi` = moonshot, `glm` = zhipu. `X-alt` has the vendor of X. Any
  other label is its own vendor.
- Provisional judge seats come from `run.json.provisional` entries for that stage. They are labeled `(PROVISIONAL)` and
  left out of self-preference audits.

**Screen.**
- The v1 math is unchanged: means over the judges present; K1 needs at least 2 judges who all failed the same gate;
  a single judge's failure only flags; K3 floor; ±25% ranges; quotas; primary ideas.
- New section `## Judge agreement`: pairwise Spearman correlation of each judge's weighted scores over commonly scored
  ideas. WARN when a judge's best correlation is below 0.2.
- New section `## Own-origin gap`: for each judge family f with at least 3 ideas whose origin vendor matches f, the mean
  weighted score f gave them minus the mean the other judges gave the same ideas. Flag when the gap exceeds 0.5.
  Report only; it does not change the shortlist.

**Tournament.**
- prepare: batched mode writes `<fam>_{fwd,rev}.prompt.md` per judge family (2F prompts). Per-pair mode writes
  `<fam>_{fwd,rev}_{NNN}` (2F·C(n,2) prompts). Shuffles stay per `rng(run, "tournament-<fam>-<order>")`.
- tally, per (family, pair): 1/0 when both orders name the same winner, otherwise 0.5/0.5 (v1).
- **Raw standings:** the sum over families. The maximum is F·(n-1).
- **Contested pair:**
  - no family is order-consistent, or
  - the modal winner holds less than 2/3 of the order-consistent families.

  With N=2 this equals v1.
- **Position consistency** per family. Below 60% is flagged.
- **Debiased standings,** the default for recommendations:
  - drop (family f, pair) when exactly one card's origin vendor equals vendor(f); `human`, `human-mixed` and `ai-mixed`
    count as nobody's own;
  - drop every family flagged for position consistency;
  - score = points / possible, in percent, where possible = the number of remaining (family, pair) entries that involve
    the card.
- **Self-preference audit,** for each judging vendor f with own-vendor finalists: f's win share for own ideas in mixed
  pairs, minus the mean share the other non-provisional judges gave the same pairs. Flag when the difference exceeds
  0.15.
- If any family is flagged, also print `## Standings excluding flagged families`.
- `result.json`:

```json
{"families":["claude","gpt","kimi"],"raw":[{"id":"I-031","points":7.5,"max":9}],
 "debiased":[{"id":"I-031","pct":81.2,"n":6}],"contested":[["I-014","I-031","families disagree"]],
 "consistency":{"claude":0.83},"flags":{"position":[],"self_preference":["gpt"]},"provisional":[]}
```

**`arch-matrix`.**
- Inputs:
  - `drivers.json` quality goals with weights summing to 70;
  - fixed criteria `time_to_mvp` 10, `team_fit` 5, `run_cost` 5, `reversibility` 5, `operational_simplicity` 5;
  - `candidates/map.json` `{label: {"family", "archetype", "job"}}`;
  - `review/judge_<fam>.out.json` (schema in 7.4).
- **Eligible judges** for candidate X are judges whose family differs from X's author. If none, all judges are used,
  and the matrix notes it.
- The score per criterion is the mean of eligible judges' 1-5 scores. `W = Σ w·mean / Σ w` over criteria that have
  data.
- **Veto:** 2 or more eligible judges veto: EXCLUDED. Exactly 1 vetoes: FLAGGED. If the only eligible judge vetoes:
  FLAGGED, with the note "single-judge veto: the human decides".
- **Rank ranges:** each weight at ±25%, as in screen.
- **Disagreement:** any criterion where the eligible judges' scores span 2 or more points.
- **Leader:** the top candidate that is not EXCLUDED. `leader_status` is `clear` when the leader's range is [1,1] and
  no other candidate's range reaches 1. Otherwise it is `close-call`.
- Outputs:
  - `tradeoff-matrix.md`: weights table, scores table with ranges and vetoes, disagreements, merged sensitivity and
    trade-off points, steal list, leader line.
  - `matrix.json`:

```json
{"criteria":[{"id":"QG1","weight":25}],"candidates":[{"label":"A","score":3.84,"rank":1,"range":[1,1],
 "veto":"none|flagged|excluded","veto_reasons":[],"means":{"QG1":4.0},"judges":["gpt","kimi"],
 "disagreements":["QG2"]}],"leader":"A","leader_status":"clear","steal":[{"from":"B","element":"...","why":"..."}],"warnings":[]}
```

**`quick-pick`.**
- Input `quick/curated.json`:

```
{ideas:[{id:"Q-01", title, pitch, mechanism, cluster, origin, gates:{g1,g2,g3},
         scores:[{criterion, score (1-5)}], fails_if, problem, for_whom, first_version}]}
```

- Selection:
  - keep ideas whose gates all pass;
  - take the best of each cluster by weighted score (criteria.json);
  - add the tail slot: the highest Distinctiveness with Feasibility at least 3;
  - add the best human-origin idea;
  - cap at 5, with at least 2 (otherwise exit 5).
- Writes `quick/finalists.json`, `origins.json` for the Q IDs, and `tournament/cards.md` with v1 card lines. The
  `Prior art:` line is `NOT CHECKED`.

### 5.8 Lint rules (B2 implements in `ublib/lints.py`; `bs.py` exposes them)

**lint-arch.** Files are relative to `10_ARCHITECTURE/`. `--lite` requires only the files marked (L).

| ID | Severity | Rule |
|---|---|---|
| A1 | FAIL | Required files exist: README.md (L), goals-constraints.md (L), quality-scenarios.md (L), context.md (L), tradeoff-matrix.md, chosen/containers.md (L), chosen/runtime.md, chosen/data-model.md (L), chosen/deployment.md, chosen/security-privacy.md, chosen/cost-model.md, chosen/stack.md (L), chosen/deferred.md, risks.md (L), and at least 1 `adr/NNNN-*.md` (L) |
| A2 | FAIL | No placeholder outside code fences: `TODO`, `TBD`, `XXX`, `lorem`, `{{`, `<[a-z][a-z0-9 _-]{1,40}>` |
| A3 | FAIL | Every ADR has frontmatter `status:` and `date:`; headings `## Context and Problem Statement`, `## Decision Drivers`, `## Considered Options` (at least 2 bullets), `## Decision Outcome`, `### Consequences`, `### Confirmation`; every `R-\d{3}` it cites exists in risks.md |
| A4 | FAIL/WARN | stack.md table: every row has a version. Empty or `latest` = FAIL; `UNVERIFIED` or `TO-VERIFY` = WARN (count reported) |
| A5 | FAIL | Mermaid: the first non-empty line is one of `C4Context`, `C4Container`, `C4Component`, `C4Dynamic`, `C4Deployment`, `flowchart`, `graph`, `sequenceDiagram`, `erDiagram`, `stateDiagram-v2`, `classDiagram`; `()`, `[]`, `{}` and `"` balance on every line; no tab characters; every `C4*` block is followed by a `flowchart` or `graph` block in the same file |
| A6 | FAIL | Traceability: every QG id in drivers.json appears in README.md or in chosen/containers.md's "How each quality goal is met" table; every `EXT-\d+` in context.md appears in containers.md; every `C-\d+` in containers.md appears in runtime.md; runtime.md has a `## F-` heading containing "failure" or "recovery" |
| A7 | FAIL | deployment.md, security-privacy.md and cost-model.md each have at least 120 words, or are named in deferred.md; cost-model.md has a `## Assumptions` table and a `Sensitivity` heading or row |
| A8 | FAIL | risks.md: R-ids are unique; both `## Risks` and `## Technical debt` headings exist |
| A9 | WARN | The README decision index lists exactly the files in adr/ |

**lint-proposal.** Files are relative to `11_PROPOSAL/`. `--lite` requires sections 1, 2, 3, 6, 7, 11, 12, 13 and
appendices A, B, F.

| ID | Severity | Rule |
|---|---|---|
| P1 | FAIL | PROPOSAL.md has headings in order: `## 1. Executive Summary`, `## 2. Problem and Evidence`, `## 3. Solution`, `## 4. Users and Market`, `## 5. Differentiation vs Prior Art`, `## 6. Architecture Summary` (or `## 6. Approach`), `## 7. Scope and MVP`, `## 8. Roadmap and Milestones`, `## 9. Team and Effort`, `## 10. Budget and Cost`, `## 11. Risks and Mitigations`, `## 12. Success Metrics and Validation Plan`, `## 13. Open Questions`, `## Appendix A. ADR Index`, `## Appendix B. Assumptions Index`, `## Appendix C. Candidate Comparison`, `## Appendix D. Idea Selection Record`, `## Appendix E. Glossary`, `## Appendix F. Sources` |
| P2 | FAIL | No placeholders (A2 rule) |
| P3 | WARN | In §2, §4, §5 and §10, a sentence containing a digit, `%` or `$` carries `[S-\d{3}]`, a URL, `[ASSUMPTION` or `[ESTIMATE` (count reported) |
| P4 | FAIL | §1 has at most 300 words; ONE-PAGER.md has at most 550 words |
| P5 | FAIL | §8 mentions `Milestone 0` and the probe's `kill criterion` |
| P6 | FAIL | Every cited `S-###` exists in `../sources.json`; every `ADR-NNNN` and `R-NNN` cited exists |
| P7 | FAIL | Every §13 item has `Owner:` and `Decide by:` |
| P8 | FAIL | Every `[ASSUMPTION` occurrence is listed in assumptions.md |
| P9 | WARN | The word "novel" appears anywhere |
| P10 | WARN | A `$` figure in §10 is not found in `../10_ARCHITECTURE/chosen/cost-model.md` |

**lint-frame.** Always exits 0.
- `01_FRAME.md` has the v1 P-FRAME sections.
- `criteria.json` weights sum to 100 ± 0.5.
- A key containing `feasib` and one containing `distinct` both exist (WARN if not; the tail slot is then skipped).
- Solution-like phrases in the Job statement or Problem section give a WARN: `(an?|the) (app|platform|tool|bot|AI
  assistant|marketplace|dashboard) (that|to|for)`.

### 5.9 `split`, `sources`, `assumptions`

- **split:** implements the rules in 4.6. The CLI is a thin wrapper over `ublib.filesproto`.
- **sources:**
  - Scans `02_CONTEXT.md`, `checks/*.md`, `10_ARCHITECTURE/stack.json`, `10_ARCHITECTURE/review/*.json` and
    `redteam/*.md` for URLs matching `https?://[^\s)>\]"']+`, stripping trailing `.,;:`.
  - Keeps existing IDs stable, assigns new ones as `S-001`... in first-seen order, and records `title` (the surrounding
    line, at most 80 chars), `accessed` (a date on the same line if present, else the run date) and `used_in`.
  - Writes `sources.json` `{"S-001": {"url","title","accessed","used_in":[...]}}` and a `sources.md` table.
- **assumptions:**
  - Collects `[ASSUMPTION: text]`, `[ASSUMPTION] <sentence>` and `[ESTIMATE: range; basis]` from
    `10_ARCHITECTURE/**/*.md` and `11_PROPOSAL/sections/*.md`, plus `assumptions[]` and `open_questions[]` from every
    `*.status.json`.
  - Writes `11_PROPOSAL/assumptions.md` (`| A-001 | text | where |`) and `11_PROPOSAL/open-questions.md`
    (`| Q-001 | question | source | owner | decide by |`; blank cells read `to assign`).

---

## 6. Pipeline, autopilot and skill content (B3 detail)

### 6.1 Modes

All numbers are estimates. `ub plan` recomputes them for the actual families.

| Mode | Replies (guided) | Wall time | Model calls (3 families) | Tokens | Contents |
|---|---|---|---|---|---|
| quick | 3-4 | 30-50 min | 25-40 | 0.2-0.5M | G0 brief + 5 ideas + 3 criteria -> one generation pass on 2 families -> QUICK-CURATE -> quick-pick -> both-order judging by the other families -> gut pick -> decide -> QUICK-PROBE -> arch-lite -> proposal-lite -> sign-off. Stamped "Novelty NOT checked" |
| standard | 6-7 | 3-5 h (mostly unattended) | 75-110 | 1.0-2.5M | Stages 0-14 in full |
| deep | 10-14 | 6-10 h | 180-350 | 3-6M | Standard plus v1 deep extras (BMAD seeds, ce-ideate go deep, S3 x100, LENS L1-L6, dupcheck, 2 gap rounds, per-pair judging when there are 6 or fewer finalists, rebuttal, forge, 10-day probe), 4 architecture candidates, 4 review lenses, PR/FAQ, G10 and G12 |
| proposal | 4-5 | 1.5-2.5 h | 35-55 | 0.6-1.2M | The user's idea: G0 -> frame -> ground -> the idea as I-001 (primary) + 2 contrast variants -> checks -> cards -> tournament (gut pick optional) -> red-team all 3 -> decide (default = the user's idea) -> probe -> Stage 12 -> 13 -> 14 |

Default budget caps (`max_calls`): quick 60, standard 180, deep 600, proposal 90. `GB` asks before the cap is exceeded.

### 6.2 Autopilot presets

| Gate or step | hands-on | guided (default) | full-auto |
|---|---|---|---|
| G0 kickoff (plan, cost, vendors, privacy, seeds inline) | ask | ask (the same reply can carry seeds) | only if privacy defaults are unset in config |
| G1 seeds | ask (file, 10 min) | inline in G0, optional | SKIPPED (recorded) |
| Frame | grilling up to 3 rounds (+ domain-modeling in software/growth) or express, then G2c | grilling 1 round if installed, otherwise express G2 | FRAME-DRAFT (all ASSUMED) |
| G3 round 2 | ask | no (map shown in PROGRESS.md) | no |
| G4 rescues, G5 K4 | ask | auto: K4 candidates are PARKED, never killed; flags shown at G8a/G8b | auto-park |
| G6, G7 | ask | auto (6 finalists rule; top 3 + gut #1) | auto |
| G8a gut pick | before any judge runs | while judges run sealed | skipped |
| G8b decide | ask | ask (`ok` accepts the suggestion) | rule default, stamped AUTO-DECISION |
| G9 probe | wait for the result | designed; result later via `probe-result` | designed only |
| G10 drivers | ask | auto (ASSUMED tags) | auto |
| G11 architecture | ask | ask | leader, AUTO-DECISION |
| G12 ADRs | one by one | bundled into G13 | stay `proposed` |
| G13 sign-off | ask | ask | DRAFT + "AUTOPILOT DRAFT: no human decisions were made" |
| G14 handoff | ask | ask (offer) | skipped |
| S1 engine | ce-ideate if installed | S1F (say `with-ce-ideate` to use ce-ideate) | S1F |

The **rule default** for G8b (full-auto) and the suggestion (guided): among the red-teamed ideas, pick the most
BACK + BACK IF verdicts, then the higher debiased tournament %, then the gut pick #1. The card calls it "Suggested by
rule; you decide".

### 6.3 Execution model (driver + detached workers)

`ub next RUN --wait-s W`:
1. Take the driver lock `.ub/lock.json` (`{pid, host, heartbeat_at}`; stale after 120 s). If another live driver holds
   it, return AUTO with the say line "another session is driving this run" and wait 30 s.
2. Loop, polling every 2 s, until a card is ready or W seconds have passed:
   - **SCRIPT steps** run in-process (or through a `bs.py` subprocess), then the step advances.
   - **DISPATCH steps:**
     - Build the job files if they are missing or stale.
     - Get each job's state with `batch.job_state`.
     - Launch `pending` jobs and relaunch `dead` ones, within the global `parallel` (4), the per-family `limit` and
       `budget.max_calls`.
     - When every job has reached a final state, apply the step's `min_ok` rule. Missing results go through
       `fallback`, recorded as PROVISIONAL in `run.json.provisional` and in the card notes. If still short, the step is
       BLOCKED with fixes.
     - Then run the `after` scripts and advance.
   - **HUMAN steps:**
     - Launch any `prelaunch` jobs declared for this gate (for example tournament judges during G8a).
     - Write `gates/<G>.md` and return a HUMAN card.
   - **HOST steps:** return a HOST card.
   - **HOST_BATCH:** return the card once every non-host job of the step is launched and only `host` jobs remain.
   - **DONE / BLOCKED:** return the card.
3. When W runs out, return an AUTO card with `progress` and `next_wait_s`.

Rules for workers and hosts:
- Workers keep running after `ub next` exits.
- A host that kills the process tree only causes relaunches.
- If the same job is relaunched 3 times without finishing, the card is BLOCKED:

  > Your agent stops background work before model calls finish. Run this in a terminal instead: `<runner> run
  > --continue "<run>"` (it asks the remaining questions there), or raise the command timeout (see
  > references/hosts.md).

**Host wait values**, also in SKILL.md:

| Host | W | Host command timeout |
|---|---|---|
| Claude Code | 540 | Bash `timeout: 600000` [V: maximum 10 min] |
| Kimi Code | 270 | Bash `timeout: 300000` [V: maximum 5 min; commands that time out keep running in the background] |
| Codex | 100 | `timeout_ms` of 120000 or more where the shell tool accepts it [U-9] |
| ZCode, other | 50 | |

**Terminal mode** (`ub run`) uses the same loop with no W limit:
- HUMAN gates are asked on stdin. `show` is printed, then the user types; an empty line ends the answer. The answer is
  parsed deterministically: letters, IDs, `ok`, `go`, `skip`, `approve`, `changes: ...`. The rest goes into `reply`.
- HOST steps use their engine alternatives: express frame, S1F, built-in FORGE skipped.
- A family whose chain resolves to `host` is dropped, and the run is marked PROVISIONAL.

### 6.4 Step map, stages 0-11

Types:
- **S** = SCRIPT (engine or `bs.py`)
- **D** = DISPATCH (jobs)
- **H** = HUMAN
- **T** = HOST task

Prompt templates live in `SK/templates/prompts/<NAME>.md`.

| ID | Type | When | What | Outputs |
|---|---|---|---|---|
| 0.1 | S | always | `ub init`: `bs.py init`; run folder + v2 dirs; detect; preflight; seats; plan estimate; 00_RUN.md, PROGRESS.md, seeds template | run.json |
| 0.2 | H | always | G0 kickoff | answers/G0.json |
| 0.3 | S | always | Apply G0: mode, variant, autopilot, privacy, families, seeds (-> 00_HUMAN_SEEDS.md in v1 format; `Primary` from the proposal idea), recompute seats | 00_HUMAN_SEEDS.md |
| 1.1 | H | hands-on and no seeds in G0 | G1: the user writes the seeds file; the engine checks it (`bs.py status` @seeds) | - |
| 1.2 | T | deep + bmad installed + host can run skills | host/BMAD-SEEDS | seeds import |
| 2.0 | S | software/growth, in a repo | CONTEXT snapshot + `git status --porcelain` baseline (P-GRILL-DOCS step 0) | CONTEXT.before.md |
| 2.1g | T | grilling installed, host is not terminal, not full-auto, not quick | host/FRAME-GRILL (software/growth with domain-modeling: host/FRAME-GRILL-DOCS); round cap: guided 1, others 3 | 01_FRAME.md, criteria.json (+ CONTEXT.proposed.md) |
| 2.1q | D | not 2.1g, not full-auto, not quick | FRAME-QUESTIONS (host family, json) | frame/questions.json |
| 2.1a | H | after 2.1q | G2 answers | frame/answers.json |
| 2.1w | D | after G2 | FRAME-FINAL (files: 01_FRAME.md, criteria.json) | same |
| 2.1f | D | full-auto | FRAME-DRAFT (files) | same |
| 2.1k | S | quick | mini frame from the G0 brief + criteria | 01_FRAME.md, criteria.json |
| 2.2 | S | always | lint-frame; criteria normalization (missing weights -> defaults + warning); footprint check -> G2f if changed | frame/lint.json |
| 2.3 | H | hands-on | G2c confirm | - |
| 3.1 | D | not quick | P-GROUND (researcher seat; web unless privacy says no; read only on the host vendor in software/growth) | 02_CONTEXT.md |
| 3.1b / 3.2 | D / S | deep | second researcher (other family) -> append its section B as "B (second family)" | 02_CONTEXT.md |
| 4.1c | T | s1_engine = ce-ideate | host/S1-CE -> `ub attach-s1` | pool/S1_ce-ideate*.md |
| 4.1f | D | s1_engine = s1f | S1F (host family) | pool/S1_frames.md |
| 4.2 | D | not quick | fanout `strategies`: S2-VS (host), S3-EDE, S4-TRANSFER (web family), S5-OPS (research variant: S5-RESEARCH), deep: LENS L1-L6 (json, `bs.py schemas` first) + variant extras; `min_ok` 3 of 5 | pool/* |
| 4.3 | S | after 4.x | write pool/_families.json from seats + provisional | - |
| 5.1 | D | not quick | CURATOR (host family, json, pool inlined) -> the engine writes merges.json (v1 format) + 03_POOL_NOTES.md | merges.json |
| 5.2 | S | after 5.1 | `bs.py map`; deep: `bs.py dupcheck` -> 5.2d CURATOR pass 2 -> map | 03_POOL.md, coverage.json |
| 5.3 | D | homogenized or empty cells, and rounds left (standard 1, deep 2) | GAP x up to 6 cells (alternating families) + REOPEN (standard 1 other family, deep 2) -> 5.3c CURATOR + map; stop early when a round is SATURATED | pool/G*, pool/R* |
| 5.4 | H | hands-on | G3 round 2 | 00b_HUMAN_ROUND2.md |
| 6.1 | S | not quick | `bs.py schemas`; screen/header.md from SCREEN-HEADER; `bs.py prepare-screen` | screen/*.prompt.md |
| 6.2 | D | not quick | judges fanout over seats.screen_judges (json, cover all IDs) | screen/<fam>.out.json |
| 6.3 | S | | `bs.py screen`; render 04_SHORTLIST.md (shortlist, KILL/FAIL rows, flags, borderline, `Rescued:` line) | 04_SHORTLIST.md |
| 6.4 | H | hands-on | G4 | - |
| 7.1 | D | not quick | CHECK fanout over shortlist, rescued and primary (web; checker family differs from the idea's origin where possible) | checks/<ID>.md |
| 7.2 | S | | K4 candidates: hands-on -> G5; otherwise PARK (listed in 04_SHORTLIST.md "Parked (K4 candidate)") | - |
| 8.1 / 8.2 | D | fewer than 6 survivors, or deep | EVOLVE + CHECK on each E idea; otherwise write 05_EVOLVED.md "skipped" | 05_EVOLVED.md |
| 9.1 | S | | finalists (at most 8; primary always; more survivors: 6 by score + tail slot + best human + primary; hands-on -> G6) | - |
| 9.2 | D | | NORMALIZER (cards) | tournament/cards.md |
| 9.3 | S | | tournament/header.md; `bs.py prepare-tournament` (`--per-pair` in deep with 6 or fewer finalists) | prompts, maps |
| 9.4 | D | | judges fanout: tournament judges x 2 orders; guided/quick/proposal: `prelaunch` during G8a (sealed) | *.out.json |
| 9.5 | H | not full-auto | G8a gut pick -> tournament/precommit.md (hands-on: before 9.4) | precommit.md |
| 9.6 | S | after G8a | `bs.py tournament`; 06_TOURNAMENT.md (precommit, standings raw + debiased, contested, audits) | 06_TOURNAMENT.md |
| 10.1 | S | | 07_TOP.md: top 3 by debiased % + gut #1 (hands-on -> G7) | 07_TOP.md |
| 10.2 | D | | PRECOMMIT (host family; cards + checks only) | redteam/00_precommit.md |
| 10.3 | D | | REVIEWER: ADVOCATE and CRITIC from different families, rotating; deep: + 10.3r REBUTTAL | redteam/* |
| 10.4 | D | | SYNTHESIS (ends with `WHOLE-EFFORT: CONTINUE|STOP - <reason>`) -> STOP triggers GX | 07_REDTEAM.md |
| 10.5 | H | | G8b decide (show raw verdict lines BEFORE the synthesis summary) | - |
| 10.6 | S | | 08_DECISION.md in the user's words (DECISION doc template); LEDGER rows | 08_DECISION.md |
| 11.1 | D | | PROBE (ends with `RESULT: PENDING`) | 09_PROBE.md |
| 11.2 | H | hands-on | G9 (blocking) | 09_PROBE.md result |

Quick mode replaces 2.1-10.6 with:

| ID | Type | What |
|---|---|---|
| Q.2 | D | QUICK-GEN on the host family plus one other family, in parallel |
| Q.3 | D | QUICK-CURATE (json -> quick/curated.json) |
| Q.4 | S | `bs.py quick-pick` |
| Q.5 | - | 9.3-9.6 with the non-host families as judges, both orders; G8a optional |
| Q.6 | D | QUICK-PROBE (json) |
| Q.7 | H | G8b decide |
| Q.8 | S | QUICK_DECISION.md |

Proposal mode inserts these after 3.1:

| ID | Type | What |
|---|---|---|
| P.1 | S | The idea becomes I-001 (primary; origins `human`) |
| P.2 | D | EVOLVE-CONTRAST (E-01 simplification, E-02 different mechanism) |
| - | - | Then 7.1 (checks on 3 ideas), 9.2-9.6, 10.2-10.6 with default chosen = I-001 |

### 6.5 Stages 12-14

Stages 12-14 are specified in sections 7-9.

### 6.6 Seat assignment (deterministic; stored in run.json)

Let F = available ∩ privacy-allowed families, ordered with the host family first and then `order`.

- **Only one family in F:** every "other" seat becomes `<host>-alt`. A PROVISIONAL banner appears in 00_RUN.md,
  PROGRESS.md, every card and the proposal header.
- **Generators:**
  - S1 and S2 go to the host family.
  - S4 goes to a web-capable family, preferring the host.
  - S3, S5, LENS and GAP go round-robin over the non-host families, or `<host>-alt` when there are none.
  - REOPEN goes to non-host families.
- **Researcher:** the host family if it has web, otherwise the first web-capable family. Deep adds a second family.
- **Checker:** for each idea, a web-capable family that differs from the idea's origin vendor, preferring the host.
  With privacy `web` = no, the verdict is `NOT CHECKED`, which can never trigger K4.
- **Screen and tournament judges:** quick = 1 non-host family (or `<host>-alt`); standard = the host plus up to 2
  others; deep = all of F, up to 4.
- **Red-team:** ADVOCATE and CRITIC always come from different families. The advocating family rotates over F.
- **Architecture authors:** up to K distinct families (K = 2 quick, 3 standard/proposal, 4 deep), taken round-robin
  over F starting with the non-host families. Archetypes are assigned by `rng(run, "arch")`. Fewer families than K:
  repeat families with different archetypes and add the badge "same-family bake-off".
- **Architecture judges:** families that authored nothing, if any exist, plus the host family. If there are none, all
  of F, with the own-candidate exclusion in the matrix.
- **Pre-mortem:** a family that differs from the leader's author.
- **Package writer:** the chosen candidate's author family.
- **Review lenses:** families other than the writer, round-robin. STACK-VERIFY goes to a web-capable family.
- **Proposal:** drafter = the host family. Rubric = other families (1 in quick, 2 in standard, all in deep).
  Red-team = one family that is not the drafter.

### 6.7 Evidence rules and where the kit enforces them

| Guide rule | Enforcement |
|---|---|
| 1 Human ideas first | G0 comes before any model call except the preflight PING. Cards never show AI ideas before G0 is answered. `privacy.seed_leak_check`: before dispatching any generator, curator-excluded or judge job, the engine refuses (BLOCKED) if the prompt contains a line of 20 or more characters from the seed sections Ideas, Primary idea or Obvious (the curator is the only job allowed to see seeds) |
| 2 Question-only framing | Template rules (FRAME-QUESTIONS allows defaults only for constraint, scope and timeline questions), the P-GRILL argument, and lint-frame warnings |
| 3 Isolated strategy portfolio | One job per strategy, no tools, empty cwd, prompts built from FRAME + FACTS only. Generator prompts are checked for pool text: a title line of 20 or more characters from any pool file blocks dispatch |
| 4 No early selection | Only the curator merges, and only exact mechanism-key duplicates. Rejected or ce-ideate raw ideas enter as PARKED |
| 5 Novelty only from evidence | Judges score Distinctiveness only. CHECK verdicts name matches. Lint P9. Proposal template rule |
| 6 Debiased judging | Neutral lines and cards. N families, both orders. Consistency and self-preference audits. Debiased standings. `privacy.origin_label_check` refuses judge prompts containing alias IDs (`\b(S\d+|G\d+|R\d+|L\d+|H|HP|H2|IMP|S1R)-\d+\b`) or the words `origin:`, `strategy:`, `generated by` |
| 7 Debate only narrows | Red-team only after the tournament. At most one rebuttal (deep) |
| 8 The human decides | G8a comes before any tally is shown. G8b records the user's words. Full-auto is stamped AUTO-DECISION everywhere |
| 9 Test before build | The probe is pre-registered in 09_PROBE.md, becomes Milestone 0 in the roadmap (lint P5) and is checked by the handoff gate (G14 warns without `RESULT: PASSED`) |
| 10 Everything in files | run.json + files. Any host can `continue` |

### 6.8 Privacy

- `privacy.web` = false:
  - no job gets `web` tools;
  - LANDSCAPE is `NOT SEARCHED`;
  - checks are `NOT CHECKED`;
  - STACK-VERIFY rows are `NOT SEARCHED`.
- `privacy.vendors` = false (or `private`): F = {host family}, and every other seat becomes `<host>-alt` (PROVISIONAL).
- `privacy.code` = false (the default): prompts to families whose vendor differs from the host vendor get these
  changes:
  - FACTS keep file paths but drop file contents and fenced code blocks;
  - A2 terms keep only those marked "proposed";
  - `cwd: repo` is never used.
- The adapter re-checks every rule (5.6).

### 6.9 Progress, estimates, budgets

**`PROGRESS.md`** is rewritten after every step:

```
# ultimate-brainstorm: <slug> (standard, product, guided)                  updated <HH:MM>
71% | stage 10/14 Decision | ETA 40-70 min | NEXT: your turn - decide (G8b)
Families: claude OK (host) | gpt OK (web) | kimi PROVISIONAL->kimi-alt at screen | glm not set up
Calls: 91 done, 0 running, 1 failed, 1 provisional | ~1.1M tokens (est.)
[x] 0 Kickoff 09:02  [x] 1 Seeds (4 ideas)  [x] 2 Frame  [x] 3 Ground  [x] 4 Diverge 5/5  [x] 5 Map (64 ideas, 9 clusters)
[x] 6 Screen (11)  [x] 7 Checks 11/11 (2 CROWDED -> parked)  [x] 8 Evolve (skipped)  [x] 9 Tournament  [~] 10 Decision
[ ] 11 Probe  [ ] 12 Architecture  [ ] 13 Proposal  [ ] 14 Handoff
Files: 03_POOL.md | 04_SHORTLIST.md | 06_TOURNAMENT.md | 07_REDTEAM.md
```

**`estimates.json`** (B3) holds per-kind priors:

```json
{"generator": {"in_tokens": 6000, "out_tokens": 8000, "seconds": 180},
 "judge": {"in_tokens": 9000, "out_tokens": 3000, "seconds": 120},
 "researcher": {"in_tokens": 5000, "out_tokens": 4000, "seconds": 360}}
```

It has one entry per job kind in 4.4.

**`ub plan`:**
- calls = the exact counts from pipeline fanouts and seats, with min/max for conditional steps;
- tokens = Σ priors × [0.7, 1.6];
- wall time = critical path of waves / concurrency, recalibrated from the median durations in `calls.jsonl` once
  observed;
- dollars only when the user sets `prices` in `UB_HOME/families.json`; otherwise "counts against your plans".

The output is `{"calls":{"min":..,"max":..,"expected":..,"by_family":{..}},"tokens":[lo,hi],"minutes":[lo,hi]}`.

**Budget:** at `budget.max_calls` the engine issues GB (guided/hands-on) or BLOCKED (full-auto).

### 6.10 Resume, redo, cross-host, v1 runs

- **`continue`** picks the newest run under `./brainstorm/` (fallback: `UB_HOME/runs.json`) that has no `12_HANDOFF.md`
  and is not signed off, and says which one it picked.
- **Redo:**
  - `redo RUN STEP` moves the outputs of STEP and every downstream step to `_superseded/<ISO>/`, clears downstream
    gates, and prints the cost preview first (asks unless `--yes`).
  - `switch --arch B` records G11 = B (by: human, via switch), then redoes from 12.10.
  - `switch --idea I-014` = redo 12.1 with that idea (08_DECISION.md records the switch).
- **Cross-host:**
  - `continue --host H` re-detects families.
  - Seated families that have disappeared are re-seated, following section 6.6 on what is left. Guided and full-auto do
    this automatically; hands-on asks.
  - Every re-seat is recorded in `provisional`.
  - If `run.json.kit_version` differs from the runner version, the card warns.
- **v1 runs:** a run folder with `00_RUN.md` and no `run.json` is migrated by `migrate.py`:
  - it parses mode, variant, host and other family, privacy, python and the strategy map;
  - it writes `run.json` with `legacy_v1: true` and families claude/gpt;
  - the run then continues.

  A v1 run that already has `10_HANDOFF.md` gets the offer "extend with architecture + proposal", as a G0-lite card.

### 6.11 `pipeline.json` format

```json
{"schema": 1,
 "steps": [
  {"id": "4.2", "stage": 4, "title": "Diverge", "type": "DISPATCH",
   "when": ["not_quick"], "after_steps": ["4.1f|4.1c"],
   "fanout": "strategies",
   "job": {"template": "{item.template}", "kind": "generator", "family": "{item.family}", "tools": "{item.tools}",
           "cwd": "empty", "out": "pool/{item.out}", "contract": {"type": "idea-blocks", "prefix": "{item.id}", "min": 10},
           "fallback": ["{item.family}-alt"]},
   "min_ok": "3/5",
   "after": ["write_pool_families"]},
  {"id": "9.5", "stage": 9, "title": "Gut pick", "type": "HUMAN", "gate": "G8a", "when": ["not_full_auto"],
   "prelaunch": ["9.4"]}
 ]}
```

`pipeline.py` implements the registries:

| Registry | Contents |
|---|---|
| predicates | `not_quick`, `mode_is:<m>`, `variant_in:<a,b>`, `autopilot_is:<p>`, `hands_on`, `not_full_auto`, `has_component:<c>`, `host_can_run_skills`, `homogenized_or_gaps`, `survivors_lt:<n>`, `deep`, `repo_variant`, `build_type:<t>`, `privacy_web` |
| fanouts | `strategies`, `lenses`, `gap_cells`, `screen_judges`, `shortlist`, `evolved`, `tournament_prompts`, `redteam_pairs`, `arch_authors`, `arch_judges`, `review_lenses`, `rubric_families` |
| placeholders | 6.12 |
| scripts | named functions |

Step IDs are the ones in sections 6.4, 7.2, 8.2 and 9.

### 6.12 Template inventory

**Rules for every template** (B3; tested by `test_templates.py`):
- ASCII only.
- The first line is `<!-- ub-template: <NAME> v1 kind=<kind> -->`.
- Isolated-call templates have this second line:
  `Do not load or invoke any skill; this prompt is the whole task.`
- Placeholders are `{{UPPER_SNAKE}}`, every one resolvable by the registry. No `${`.
- The output contract is stated in words at the end (OUTPUT RULE).
- JSON templates embed `{{SCHEMA_TEXT}}` when the backend is not native-schema.

**Prompts** (`templates/prompts/`). v1 texts are ported from `references/prompts.md` with only the changes marked.

| Name | Kind | Contract | Notes |
|---|---|---|---|
| PING | ping | text regex PONG | preflight |
| FRAME-QUESTIONS | frame | json `frame-questions` | new; question-only; defaults only for constraint, scope, timeline; includes the variant add-ons |
| FRAME-FINAL | frame | files 01_FRAME.md + criteria.json | new; P-FRAME step 7 format |
| FRAME-DRAFT | frame | files | new; full-auto; every item ASSUMED |
| P-GROUND | researcher | sections A. FACTS / B. LANDSCAPE / C. SEARCH BOUNDARY (+A2) | v1 |
| GEN-HEADER | (partial) | - | v1; included by generators; OUTPUT RULE = "Print only the result." |
| S1F, S2-VS, S3-EDE, S4-TRANSFER, S5-OPS, S5-RESEARCH, GAP, REOPEN | generator | idea-blocks | v1; S5-RESEARCH from variants.md research lens quota |
| LENS | generator | json lens (bs.py schema) | v1 |
| QUICK-GEN | generator | idea-blocks Q | v1 QUICK |
| CURATOR | curator | json `merges` (merges + notes) | v1, changed to take the pool inline and return JSON only |
| QUICK-CURATE | curator | json `quick-curated` | new |
| SCREEN-HEADER, TOURNAMENT-HEADER | (partials) | - | v1; bs.py appends ideas or cards |
| CHECK | checker | sections 1-4(5) + final `^VERDICT: (CROWDED|ADJACENT|NOT LOCATED|NOT CHECKED); DIFFERENTIATOR: .+$` | v1 |
| EVOLVE, EVOLVE-CONTRAST | generator | idea-blocks E | v1 / new |
| NORMALIZER | normalizer | cards (v1 7 lines) | v1 |
| PRECOMMIT | synthesis | text | v1 (a model job) |
| REVIEWER | reviewer | sections 1-5 + final `^VERDICT: (BACK IF .+|BACK|DON'T BACK); confidence (0(\.\d+)?|1(\.0+)?)$` | v1, changed to use a machine-readable last line |
| REBUTTAL | reviewer | text | v1 |
| SYNTHESIS | synthesis | sections + final `^WHOLE-EFFORT: (CONTINUE|STOP)` | v1 + the WHOLE-EFFORT line |
| PROBE | writer | sections + final `^RESULT: PENDING$` | v1 |
| QUICK-PROBE | writer | json `quick-probe` | new |
| ARCH-DRIVERS, ARCH-CANDIDATE, ARCH-JUDGE, ARCH-PREMORTEM, ARCH-PACKAGE-STRUCTURE, ARCH-PACKAGE-CROSSCUT, ARCH-DECISIONS, ARCH-PACKAGE-LITE, STACK-VERIFY, ARCH-REVIEW, ARCH-FIX, APPROACH | 7.x | 7.4 / 7.5 | new |
| PROPOSAL-A, PROPOSAL-B, PROPOSAL-C, EXEC-ONEPAGER, PRFAQ, PROPOSAL-LITE, PROPOSAL-RUBRIC, PROPOSAL-REDTEAM, PROPOSAL-FIX | 8.x | 8.3 / 8.4 | new |

**Other template folders:**

| Folder | Files |
|---|---|
| `templates/host/` | FRAME-GRILL, FRAME-GRILL-DOCS (v1 P-GRILL / P-GRILL-DOCS + P-FRAME steps 3, 3b, 4, 6, 7, with a round cap placeholder), S1-CE (v1 S1-CE + attach-s1), BMAD-SEEDS, FORGE (v1), CONTEXT-MERGE (v1 Stage 12 step 1), HOST-BATCH (per-host sub-agent instructions), HANDOFF-RUN (how to start ce-brainstorm / Spec Kit / Superpowers / OpenSpec in a fresh session) |
| `templates/gates/` | G0, G1, G2, G2c, G2f, G3, G4, G5, G6, G7, G8a, G8b, G9, G10, G11, G12, G13, G14, GB, GX |
| `templates/docs/` | RUN (00_RUN.md), PROGRESS, SHORTLIST, TOURNAMENT, DECISION, QUICK-DECISION, GOALS-CONSTRAINTS, QUALITY-SCENARIOS, CONTEXT-VIEW, ARCH-README, ADR-MADR, RISKS, STACK, PROPOSAL-APPENDICES, HANDOFF, SEEDS (v1 template), `index.html.tpl` |
| `templates/schemas/` | frame-questions, merges, quick-curated, quick-probe, arch-drivers, arch-candidate, arch-judge, arch-decisions, stack-verify, findings, rubric, redteam (7.4, 8.4). Screen, verdicts and lens schemas stay generated by `bs.py schemas` |

**Handoff seeds** are doc templates, not model prompts: HANDOFF-CE, HANDOFF-SPECKIT, HANDOFF-SUPERPOWERS,
HANDOFF-OPENSPEC.

**Standard placeholders** (registry; privacy filtering is applied per target family):
`BRIEF`, `FACTS`, `LANDSCAPE`, `AXES`, `HMW`, `AUDIENCE`, `HARD_CONSTRAINTS`, `CRITERIA_ANCHORS`,
`CRITERIA_WEIGHTS`, `STRATEGY_ID`, `IDEA`, `CARD`, `CHECKS`, `CELL`, `CLUSTER_NAMES`, `LEDGER_TITLES`, `POOL_BUNDLE`,
`SEEDS_BUNDLE`, `FRAME_FULL`, `DECISION`, `PROBE`, `ARCH_BRIEF`, `QAS_TABLE`, `ARCHETYPE`, `OTHER_ARCHETYPES`,
`CANDIDATE_SHEETS`, `CHOSEN_CANDIDATE`, `DRIVERS_JSON`, `STRUCTURE_FILES`, `PREMORTEM`, `FINDINGS`, `LINT_REPORT`,
`PACK_A`, `PACK_B`, `PACK_C`, `SOURCES_TABLE`, `SECTIONS_ALL`, `RUBRIC_FIXES`, `REDTEAM_ITEMS`, `USER_CHANGES`, `LANG`,
`VARIANT`, `MODE`, `DATE`, `RUN_NAME`, `OUTPUT_RULE`, `SCHEMA_TEXT`, `ALLOWED_FILES`, `ROUND_CAP`, `COMPONENT_NAME`.

### 6.13 SKILL.md

This is the required content. B3 may improve the wording but must keep every rule and the host table. The file must
stay at 12 KB or less.

```markdown
---
name: ultimate-brainstorm
description: "Evidence-based idea-to-proposal pipeline. Use when the user wants to brainstorm or decide what to build, compare or choose among ideas, or turn a topic or an existing idea into an architecture package and a full project proposal. Human ideas first, question-only framing, isolated multi-strategy generation across model families (Claude, GPT, Kimi, GLM), debiased both-order judging, prior-art checks, a human decision, competing architectures judged blind, and a cited proposal with a one-pager. Autopilot asks about 6 short questions; resumable from any agent. Modes: quick, standard, deep, proposal <your idea>."
license: MIT
compatibility: "Claude Code 2.1.268+, Codex 0.156+, Kimi Code CLI 2.0+, ZCode. Needs Python 3.9+. The claude, codex and kimi CLIs or a GLM key add model families."
metadata:
  version: "2.0.0"
---

# Ultimate Brainstorm (driver)
You drive a scripted pipeline. ub.py decides every step and returns one card per call. Run it, do exactly what the card
says, and talk to the user only on HUMAN cards and at the end. Never invent stages, skip gates, score, count or
assemble documents yourself. All state is in files, so any session and any agent can resume.

## Setup
- KIT = the folder of this SKILL.md: Claude Code ${CLAUDE_SKILL_DIR}; Kimi ${KIMI_SKILL_DIR}; Codex, ZCode, others:
  the path of this skill in your skills list. Use whichever is an absolute path.
- PY = the first of `py -3`, `python3`, `python` whose --version prints Python 3.9+ (Windows: skip the WindowsApps stub).
- UB = PY "KIT/scripts/ub.py". After the first card, use the card's "runner" field instead.
- HOST = claude-code | codex | kimi | zcode | other (the product you run in).

## Commands
- Start: UB init --host HOST --text "<everything the user typed after the command>" --components "<list>" --json
  (replace double quotes in the user's text with single quotes). --components = the installed skills from your skills
  list among grilling, domain-modeling, ce-ideate, ce-brainstorm, ce-plan, bmad-brainstorming, bmad-forge-idea,
  lateral-thinking, claude-council, speckit, spelled exactly as listed (for example mattpocock-skills:grilling).
- Continue: UB continue --host HOST --json   Status: UB status --json   Doctor: UB doctor --json
- stop -> UB stop "<run>"; probe passed|missed|inconclusive -> UB probe-result "<run>" <RESULT> --note-file <file>;
  redo <step> -> UB redo "<run>" <step>; switch architecture/idea -> UB switch ...; import <file> -> UB import <file>.

## The loop
1. Run the card's "then" command (or UB next "<run>" --wait-s W --json) with your shell timeout above W (table).
2. By card "type":
   AUTO: work is running. Say nothing unless "say" names a new stage; go to 1.
   HUMAN: show "show" to the user exactly (a faithful translation is fine). Stop and wait. Then write a NEW file at
     "answer_file" containing "answer_template" filled in: "reply" = the user's exact words; fill only fields the
     reply clearly states; leave the rest null. Run "answer_cmd". If the same gate comes back with "error", ask the
     user exactly that.
   HOST: read "task.template" and do it here in the main conversation (for example run the named installed skill with
     the argument file). Write the files it names, then run "task.done_cmd".
   HOST_BATCH: run every job in a FRESH sub-agent (table), each told exactly: "Read <prompt_file> and follow it
     exactly. Write only the requested output to <out>. Reply with one line." Wait for all, then go to 1.
   DONE: show "show" and the links, then stop.   BLOCKED: show "say" and each "fix" command, then stop.
3. If your turn must end before DONE or a HUMAN card, tell the user to type: <entry> continue.
If any UB command is interrupted or times out, run step 1 again (use a smaller W). Nothing is lost.

## Hosts
| Host | Entry | W | Shell timeout | Fresh sub-agents |
|---|---|---|---|---|
| Claude Code | /ultimate-brainstorm | 540 | Bash timeout 600000 | Agent tool, subagent_type general-purpose, never a fork |
| Codex | $ultimate-brainstorm | 100 | timeout_ms 120000 when available; run UB with escalated permissions and approve this command prefix for the session (model CLIs need network) | "spawn one new agent per job with no conversation context" |
| Kimi Code | /skill:ultimate-brainstorm | 270 | Bash timeout 300000 | AgentSwarm, prompt_template "Read {{item}} and follow it exactly.", items = the prompt files; or one Agent per job |
| ZCode, other | $ultimate-brainstorm | 50 | default | your sub-agent tool; if none, run each job yourself one by one (reported as PROVISIONAL) |

## Hard rules
1. Human first: show, suggest or summarize no AI idea before the kickoff card is answered.
2. Framing asks questions; never propose solutions, examples or idea categories while framing.
3. Never paste pool/, seeds, other generators' output or judge results into any prompt; ub builds every prompt.
4. Edit no run file yourself except answer files, the files a HOST card names, and the seeds file when the user asks.
5. Never call anything "novel"; only CHECK verdicts speak to novelty ("not located within this search").
6. The human decides: never answer a HUMAN card for the user; never rewrite the user's ideas; record their words.
7. Write only inside brainstorm/<run>/ unless a card names another path after the user's explicit yes. Never commit,
   push, install software or change settings.
8. Report the failures and PROVISIONAL notes the cards mention; never switch model families yourself.
9. Privacy answers are binding.
10. Interactive skills (grilling, domain-modeling, ce-ideate, bmad-*) run in this main conversation, never in a
    sub-agent. Plan mode off while framing.
11. If you are a sub-agent executing one prompt file for this pipeline, follow only that file; never start this skill.
```

### 6.14 References

Existing v1 files are ported; new ones are added. The files are agent-facing, each at most 25 KB.

| File | Must contain |
|---|---|
| pipeline.md | Stages 0-14 table, gates per autopilot preset, the card protocol, the execution model, resume/redo/switch, and what each output file is (replaces v1 stages.md) |
| hosts.md | Per host: install location, invocation, wait/timeout, sub-agent spawning, approvals (Codex escalation, Kimi Bash approval), Windows shells (Claude Code: Git Bash or the PowerShell tool; Codex: PowerShell; Kimi: Git Bash required), launchers (claude-glm, claude-kimi, codex-glm, codex-kimi), and ZCode caveats |
| families.md | Families, backends, env policy, policy guards (GLM plan terms), how to add a family in UB_HOME/families.json (e.g. a local model via openai-http), PROVISIONAL rules (replaces the family part of v1 tools.md) |
| components.md | Per-tool integration (v1 tools.md section 4, updated): grilling, domain-modeling (P-GRILL-DOCS rules), ce-ideate (menu, attach-s1), ce-brainstorm/ce-plan, BMAD, claude-council, pm-skills, K-Dense, ARIS, marketingskills, creative-director (CC BY 4.0 line), naming, Superpowers/OpenSpec, Spec Kit |
| variants.md | v1 content plus build types (6.15) and variant architecture archetypes |
| techniques.md | v1, unchanged |
| kill-rules.md | K1-K6, park, whole effort, and the guided-mode K4 park rule |
| architecture.md | Section 7 in agent-facing form |
| proposal.md | Section 8 in agent-facing form |
| install.md | Pointer to docs/INSTALL.md; the routing block for Claude/Codex/Kimi/ZCode instruction files; conflict settings (v1 section 5, updated for Kimi and ZCode) |
| troubleshooting.md | BLOCKED card causes and fixes: auth, network or sandbox, legacy kimi, Windows Git Bash, stale workers, budget |

The v1 `references/prompts.md`, `stages.md` and `tools.md` are not shipped. Their content moves into templates and the
files above.

### 6.15 Variants and build types

`build_type` is `system` for software, product, growth and general. It is `approach` for research, marketing, creative
and naming. The user can override it at G11 or with `ub config`.

**`approach` build type:**
- 12.1 brief, then 12.a APPROACH (host family, files: `10_ARCHITECTURE/approach.md`). Sections by variant:
  - research: hypotheses and rival explanations, design, measures, data, analysis plan with decision rule, compute,
    ethics, timeline, risks;
  - marketing/creative: channels, assets, production, measurement, budget, timeline;
  - naming: shortlist rollout, availability and trademark checks (manual), launch plan.
- Then one ARCH-REVIEW lens (a family other than the writer) and lint A2 only.
- The proposal uses `## 6. Approach`.
- There is no G11.

**Software and growth:**
- Archetype A is "smallest change to the current architecture (cite files)"; B is "one new bounded component or
  service".
- The architecture brief includes repo FACTS (paths only for other vendors unless privacy `code` = yes).
- Writers for the host vendor may use `read` tools.

---

## 7. Stage 12: Architecture

B3 owns content and flow; B2 owns the matrix and lint math.

### 7.1 Files (`10_ARCHITECTURE/`)

```
00_BRIEF.md  brief.json          frozen brief (script-assembled)
drivers.json                     ARCH-DRIVERS output
goals-constraints.md  quality-scenarios.md  context.md     rendered from drivers.json (render_arch.py)
candidates/<n>.md  candidates/<n>.json  candidates/map.json   raw author outputs; map = label -> family, archetype
review/sheet_<L>.md              neutral judge sheets rendered from candidate JSON
review/judge_<fam>.out.json      ARCH-JUDGE outputs
tradeoff-matrix.md  matrix.json  bs.py arch-matrix
premortem.md                     ARCH-PREMORTEM
chosen/containers.md runtime.md data-model.md api.md api/openapi.yaml (or api/cli.md) deployment.md
chosen/security-privacy.md cost-model.md deferred.md stack.md
decisions.json                   ARCH-DECISIONS output (ADRs + risks + debt)
adr/NNNN-<slug>.md  risks.md     rendered from decisions.json
stack.json                       STACK-VERIFY output (rendered to chosen/stack.md)
review/<lens>_<fam>.json  review/resolution.md
lint.md  lint.json  README.md
_raw/                            raw FILE-protocol outputs and status files
```

### 7.2 Steps

| ID | Type | What |
|---|---|---|
| 12.1 | S | Brief. Deterministic, by headings, from 01_FRAME.md (job, audience, success, hard/soft constraints, non-goals), 08_DECISION.md (chosen card, scope, Not doing), checks/<chosen>.md, 07_REDTEAM.md kill-assumptions, 09_PROBE.md riskiest assumption, and privacy flags -> 00_BRIEF.md + brief.json |
| 12.2 | D | ARCH-DRIVERS (host family; json `arch-drivers`). Missing facts are tagged `[ASSUMPTION]`; quality-goal weights must sum to 70 (the engine normalizes with a warning) -> drivers.json -> render goals-constraints.md, quality-scenarios.md, context.md (C4Context + flowchart fallback, generated from drivers.context) |
| 12.3 | H | G10 (hands-on/deep) |
| 12.4 | D | ARCH-CANDIDATE x K (4.4 seats; fresh contexts; same frozen brief; archetype seed). Contract: sections (the 12 headings in 7.5) + json_tail `arch-candidate`. At least 2 valid candidates are required; otherwise one recovery launch on another family; otherwise BLOCKED |
| 12.5 | S | Labels A..D by `rng(run,"arch-labels")`; map.json; render review/sheet_<L>.md from each JSON tail (fixed field order, each string truncated to 60 words; no archetype or family names) |
| 12.6 | D | ARCH-JUDGE x J (json `arch-judge`, cover = labels x criteria) on the sheets + 00_BRIEF.md + quality-scenarios.md |
| 12.7 | S | `bs.py arch-matrix` |
| 12.8 | D | ARCH-PREMORTEM on the leader, by a family other than its author -> premortem.md (5 causes: technical, cost, team, vendor, scale; each with early warning, likelihood, mitigation, proposed R-id) |
| 12.9 | H | G11 (quick: auto-leader, shown at G13 with `switch`). Families are revealed only after the choice |
| 12.10 | D | ARCH-PACKAGE-STRUCTURE (writer family; files: chosen/containers.md, runtime.md, data-model.md, api.md, api/openapi.yaml or api/cli.md). Input: brief, drivers, chosen candidate (full md + json), steal notes from G11, premortem |
| 12.11 | D | In parallel after 12.10: ARCH-PACKAGE-CROSSCUT (files: chosen/deployment.md, security-privacy.md, cost-model.md, deferred.md) and ARCH-DECISIONS (json `arch-decisions` -> decisions.json) and STACK-VERIFY (web family; json `stack-verify` over the chosen stack + additions found in STRUCTURE -> stack.json) |
| 12.12 | S | Render adr/NNNN-<slug>.md (MADR 4.0 minimal, `status: proposed`), risks.md, chosen/stack.md; then `bs.py lint-arch` |
| 12.13 | D | ARCH-REVIEW lenses (json `findings`): standard = L1 web-verified tech + L2 divergence adversary; deep adds L3 failure modes + prior art and L4 security/privacy; each lens on a family other than the writer |
| 12.14 | D | ARCH-FIX (writer family; files allowlist chosen/**, deferred.md, decisions.json, review/resolution.md): apply P0/P1 findings and lint FAILs; one pass (deep: two). Then re-render and lint again. Remaining FAILs and unresolved P0 findings go into 11_PROPOSAL open questions and the G13 card |
| 12.15 | S | README.md: summary, chosen candidate and why (Alternatives Considered from the matrix), quality goals -> mechanisms, ADR index, file map, provenance (authors revealed, judges, PROVISIONAL badges, lint and review status) |
| 12.16 | H | G12 (hands-on/deep) |

**Lite, used in quick mode:**
- 12.2 (drivers);
- 12.4 with 2 candidates (A and C);
- 12.6 with 1 judge;
- 12.7;
- auto leader;
- ARCH-PACKAGE-LITE: one call, files chosen/containers.md, chosen/data-model.md, decisions.json (3 ADRs + risks);
- stack.json from the candidate JSON, every row UNVERIFIED;
- render;
- `lint-arch --lite`;
- no review.

### 7.3 Archetype seeds (`templates/prompts/ARCH-CANDIDATE.md` table; the engine picks)

| Seed | Text |
|---|---|
| A | "Boring by default: a modular monolith on managed services (managed database, managed auth). Use at most 3 innovation tokens. Build the simplest design that meets every H-importance quality scenario." |
| B | Variant rule: privacy-heavy (a hard constraint mentions PII, on-prem, offline or data residency) -> "Local-first / offline-first"; tight budget (planning assumption budget marked low, or a solo team) -> "Buy-and-integrate: SaaS plus glue code"; otherwise -> "Event-driven / serverless: managed functions, queues and events; scale to zero" |
| C | "The approach the other candidates would not pick. The others are: {{OTHER_ARCHETYPES}}. Make its strongest case, and still meet every hard constraint." |
| D (deep) | "Cost-minimal: the cheapest design that still meets the H-importance quality scenarios." |
| Software/growth | A = "Smallest change to the current architecture (cite files)"; B = "One new bounded component or service"; C and D as above |

### 7.4 Schemas (`templates/schemas/`)

Every schema is compatible with structured output:
- every object is `additionalProperties: false`, with every property required;
- there are no free-form maps;
- the only keywords used are `type`, `properties`, `required`, `additionalProperties`, `items`, `enum` and
  `description` [U-32].

Counts, ranges and sums are checked by the engine in Python, not in the schema: 3-5 quality goals, 5-10 QAS, scores
1-5, weights summing to 70.

```json
{"$id":"arch-drivers","type":"object","additionalProperties":false,
 "required":["product_goal","quality_goals","hard_constraints","soft_constraints","not_in_scope","qas","context","planning_assumptions","open_questions"],
 "properties":{
  "product_goal":{"type":"string"},
  "quality_goals":{"type":"array","items":{"type":"object","additionalProperties":false,
    "required":["id","name","weight","why","source"],"properties":{"id":{"type":"string"},"name":{"type":"string"},
    "weight":{"type":"number"},"why":{"type":"string"},"source":{"type":"string","enum":["STATED","ASSUMPTION"]}}}},
  "hard_constraints":{"type":"array","items":{"type":"object","additionalProperties":false,"required":["id","text","source"],
    "properties":{"id":{"type":"string"},"text":{"type":"string"},"source":{"type":"string","enum":["FRAME","DECISION","ASSUMPTION"]}}}},
  "soft_constraints":{"type":"array","items":{"type":"string"}},
  "not_in_scope":{"type":"array","items":{"type":"string"}},
  "qas":{"type":"array","items":{"type":"object","additionalProperties":false,
    "required":["id","qg","source","stimulus","artifact","environment","response","measure","importance","difficulty"],
    "properties":{"id":{"type":"string"},"qg":{"type":"string"},"source":{"type":"string"},"stimulus":{"type":"string"},
    "artifact":{"type":"string"},"environment":{"type":"string"},"response":{"type":"string"},"measure":{"type":"string"},
    "importance":{"type":"string","enum":["H","M","L"]},"difficulty":{"type":"string","enum":["H","M","L"]}}}},
  "context":{"type":"object","additionalProperties":false,"required":["system","actors","external"],"properties":{
    "system":{"type":"object","additionalProperties":false,"required":["name","description"],"properties":{"name":{"type":"string"},"description":{"type":"string"}}},
    "actors":{"type":"array","items":{"type":"object","additionalProperties":false,"required":["id","name","description"],"properties":{"id":{"type":"string"},"name":{"type":"string"},"description":{"type":"string"}}}},
    "external":{"type":"array","items":{"type":"object","additionalProperties":false,"required":["id","name","description","relationship"],"properties":{"id":{"type":"string"},"name":{"type":"string"},"description":{"type":"string"},"relationship":{"type":"string"}}}}}},
  "planning_assumptions":{"type":"array","items":{"type":"object","additionalProperties":false,"required":["id","item","value","source"],
    "properties":{"id":{"type":"string"},"item":{"type":"string"},"value":{"type":"string"},"source":{"type":"string"}}}},
  "open_questions":{"type":"array","items":{"type":"object","additionalProperties":false,"required":["q","default"],
    "properties":{"q":{"type":"string"},"default":{"type":"string"}}}}}}
```

ID formats: `QG1..QG5`, `HC-1..`, `QAS-01..`, `EXT-1..`, `ACT-1..`, `AS-1..`. The engine checks the formats and that the
weights sum to 70.

**Other schemas, same style:**

| Schema | Fields |
|---|---|
| `arch-candidate` | `paradigm`, `summary` (≤60 words), `containers`[{`id` C-n, `name`, `tech`, `responsibility`, `data_owned`, `interface`}], `external`[{`id` EXT-n, `name`}], `qas_mechanisms`[{`qas`, `mechanism`, `residual_risk`}], `stack`[{`layer`, `component`, `choice`, `version`}], `data`{`entities`[string], `storage`}, `deployment`, `security_threats`[{`threat`, `mitigation`}], `cost_monthly_usd`{`mvp_low`, `mvp_high`, `x10_low`, `x10_high`}, `build_person_weeks`{`low`, `high`}, `tradeoffs`[string], `rejected`[{`approach`, `why`}], `risks`[string], `innovation_tokens`[string] |
| `arch-judge` | `candidates`[{`label`, `veto` bool, `veto_reason`, `scores`[{`criterion`, `score` int 1-5, `reason`}], `sensitivity_points`[], `tradeoff_points`[], `risks`[], `non_risks`[]}], `steal`[{`from`, `element`, `why`}], `confidence` number (D1 schema) |
| `arch-decisions` | `adrs`[{`title`, `context`, `drivers`[QG ids], `options`[{`name`, `pros`[], `cons`[]}] (min 2), `chosen`, `justification`, `good`[string], `bad`[{`text`, `risk_ids`[]}], `confirmation`, `more_info`}], `risks`[{`id` R-NNN, `text`, `likelihood` H/M/L, `impact` H/M/L, `mitigation`, `owner`, `early_warning`, `source`}], `debt`[{`id` TD-NN, `text`, `why`, `payoff_trigger`}] |
| `stack-verify` | `rows`[{`layer`, `component`, `choice`, `version`, `release_date`, `source_url`, `status` (VERIFIED, UNVERIFIED or NOT SEARCHED), `license`, `eol_note`, `alternatives`, `innovation_token` bool}] |
| `findings` | `findings`[{`id`, `lens`, `severity` P0-P3, `file`, `issue`, `fix`, `evidence`}] |

### 7.5 Prompt outlines

**ARCH-CANDIDATE.** The output uses exactly these headings, in this order:
- `## 1 Paradigm`
- `## 2 Container view` (Mermaid flowchart, one subgraph per boundary, at most 12 nodes)
- `## 3 Stack` (component | choice | why | alternative rejected; versions `[TO VERIFY]` unless given)
- `## 4 Quality mechanisms` (QAS id | mechanism | expected response measure)
- `## 5 Data`
- `## 6 Deployment and operations`
- `## 7 Security and privacy` (top 3 threats + mitigations)
- `## 8 Cost` (build person-weeks range; monthly run cost at MVP, 10x and 100x; LLM tokens if any)
- `## 9 Trade-offs` (sensitivity points)
- `## 10 Risks` (top 5, "Fails if ...")
- `## 11 Rejected approaches` (at least 2)
- `## 12 Innovation tokens`

These are followed by one fenced `json` block matching `arch-candidate`. The framing reads: "You are ONE independent
architect; others design alternatives you will never see. Keep every hard requirement identical; the archetype is a
starting stance, not a cage. Never state a version, price or limit as fact unless the brief gives it: mark
[ASSUMPTION] or [TO VERIFY]."

**ARCH-JUDGE.** "You score candidate architectures against a brief fixed before they existed. You did not write them.
Neutral labels, random order. Ignore wording and length; judge mechanisms and evidence. Check hard constraints first
(veto with reason)." Then one score per criterion (QG ids plus the fixed criteria) with anchors:
- 5 = meets every H-importance scenario with a named mechanism and margin;
- 3 = meets them with caveats;
- 1 = misses an H-importance scenario.

The judge also lists sensitivity points, trade-off points, risks, non-risks and the steal list.

**ARCH-PACKAGE-STRUCTURE, ARCH-PACKAGE-CROSSCUT, ARCH-DECISIONS:**
- They take the formats in 7.6.
- They must reuse the candidate's container IDs (`C-n`) and external IDs (`EXT-n`) and the drivers' QG and QAS IDs.
- ARCH-DECISIONS writes an ADR only for a choice that is hard to reverse, surprising without context and a real
  trade-off. Considered options include the rejected candidates' approaches.
- Risks absorb the pre-mortem causes and the candidate's risks. Risks and technical debt stay separate.

**STACK-VERIFY.** "For each component, find the current stable version on the web: the vendor's release page or the
package registry. Record the URL and date. Never take versions from memory; if not found write UNVERIFIED."

**ARCH-REVIEW lenses:**

| Lens | Question |
|---|---|
| L1 web-verified tech | Check every committed technology, version and capability claim |
| L2 divergence adversary | "Two teams build two containers independently, both obeying every ADR. Where do they still diverge (IDs, time, auth, errors, formats, versioning)? List the missing decisions" |
| L3 failure modes + prior art | For each runtime path: what fails, whether it is detected, whether it is recovered. A path with no test, no error handling and a silent failure is P0. Also: what already exists (built-ins, managed services) |
| L4 security and privacy | STRIDE gaps, secrets, authorization holes, PII, compliance |

**ARCH-FIX.** Applies P0/P1 findings and lint FAILs only. It prints only replaced files plus `review/resolution.md`
(`| finding | FIXED/DEFERRED/REJECTED | reason |`).

### 7.6 Document formats (rendered or written; the lint in 5.8 checks them)

| File | Format |
|---|---|
| goals-constraints.md | `# Goals and constraints`; `## Product goal`; `## Quality goals` (id, goal, weight, why, source); `## Hard constraints`; `## Soft constraints`; `## Not in scope`; `## Planning assumptions`; `## Open questions` |
| quality-scenarios.md | `## Utility tree` (nested list QG -> QAS); `## Scenarios` (id, attribute, source, stimulus, artifact, environment, response, response measure, importance, difficulty) |
| context.md | `## System context` paragraph; a mermaid `C4Context` block and a mermaid `flowchart` fallback with the same elements; `## Actors`; `## External systems` (EXT table) |
| chosen/containers.md | `## Containers` (mermaid C4Container + flowchart fallback); table (id, name, technology, responsibility, data owned, interface); `## How each quality goal is met` (QG, mechanism, containers, QAS, expected response) |
| chosen/runtime.md | `## F-1 <title>` sections, each with a sequenceDiagram; at least one `## F-n Failure and recovery: <title>` |
| chosen/data-model.md | erDiagram + `## Entities` (entity, fields, owner container, retention, PII) |
| chosen/deployment.md | environments, hosting, CI/CD, IaC, observability, backup/DR with RTO/RPO numbers |
| chosen/security-privacy.md | data classification table, authn/authz, STRIDE-lite per trust boundary, PII handling, compliance scope |
| chosen/cost-model.md | `## Assumptions` (id, assumption, value, source or [ASSUMPTION]); `## Monthly run cost` (item, MVP, 10x, 100x); `## Per active user`; `## LLM and API costs`; `## Build cost` (person-weeks range); `## Sensitivity` (±50% on the top driver) |
| chosen/stack.md | table (layer, component, choice, version, release date, source, status, license, EOL note, alternatives, innovation token) |
| chosen/deferred.md | table (decision, why deferred, trigger, decide by) |
| adr/NNNN-slug.md | see below |
| risks.md | `## Risks` (id, risk, likelihood, impact, mitigation, owner, early warning, source); `## Technical debt` (id, debt, why accepted, payoff trigger) |

ADR format (MADR 4.0 minimal):

```
---
status: proposed
date: YYYY-MM-DD
decision-makers: <role>
---
# ADR-NNNN: <title>
## Context and Problem Statement
## Decision Drivers
## Considered Options
## Decision Outcome
Chosen option: "<option>", because <justification>.
### Consequences
* Good, because ...
* Bad, because ... (R-NNN)
### Confirmation
## More Information
```

---

## 8. Stage 13: Proposal

### 8.1 Files (`11_PROPOSAL/`)

- `PROPOSAL.md` (assembled)
- `sections/01.md` .. `sections/13.md`
- `ONE-PAGER.md`
- `PRFAQ.md` (deep only)
- `assumptions.md`, `open-questions.md`
- `review/rubric_<fam>.json`, `review/redteam.json`, `review/resolution.md`
- `lint.md`, `lint.json`
- `index.html`, `export/`
- `README.md` (file map)

### 8.2 Steps

| ID | Type | What |
|---|---|---|
| 13.1 | S | `bs.py sources`; evidence packs: PACK_A (FRAME, 02_CONTEXT A+B, checks of the chosen idea, 08_DECISION, card), PACK_B (architecture README, containers view block, top ADRs, matrix summary, deferred, 09_PROBE, drivers), PACK_C (cost-model, risks, premortem, red-team kill-assumptions, FRAME success, open questions); SOURCES_TABLE |
| 13.2 | D | PROPOSAL-A (§2-5), PROPOSAL-B (§6-9), PROPOSAL-C (§10-13), in parallel (drafter family; files sections/NN.md) |
| 13.3 | D | EXEC-ONEPAGER after 13.2 (files sections/01.md + ONE-PAGER.md); deep: PRFAQ |
| 13.4 | S | Assemble PROPOSAL.md: title block + status banner (DRAFT, APPROVED, AUTOPILOT DRAFT or PENDING MILESTONE 0) + sections + appendices A-F (A ADR index, B assumptions index, C candidate comparison from matrix.json, D idea selection record from 06_TOURNAMENT/07_REDTEAM/08_DECISION incl. audits and PROVISIONAL badges, E glossary from FRAME Domain language + terms, F sources); `bs.py assumptions`; `bs.py lint-proposal` |
| 13.5 | D | PROPOSAL-RUBRIC (rubric families, json `rubric`) and PROPOSAL-REDTEAM (a non-drafter family, json `redteam`) |
| 13.6 | D | PROPOSAL-FIX (drafter; files sections/NN.md + review/resolution.md): answer every must_fix and the top 5 red-team items as ADDRESSED (where) / ACCEPTED-RISK (moved to §11) / REJECTED (reason); then 13.4 again |
| 13.7 | S | `ub render` -> index.html |
| 13.8 | H | G13: approve -> PROPOSAL status Approved + ADRs `accepted` (date); changes -> 13.6 with USER_CHANGES (at most 2 loops); switch -> redo 12.10; runner-up -> redo 12.1 (cost preview first) |

**Lite, used in quick mode:** PROPOSAL-LITE is one call writing sections 01, 02, 03, 06, 07, 11, 12, 13 and
ONE-PAGER.md. Then 13.4 lite, 1 rubric family, no red-team, render, G13.

### 8.3 Rules in every proposal prompt, and section contents

**Rules:**
1. Use only facts from the pack. Cite them as `[S-###]`.
2. Every number, market claim or competitor claim without a source carries `[ASSUMPTION: ...]` or
   `[ESTIMATE: range; basis]`.
3. Never invent customers, quotes, metrics or moats. Never use the word "novel".
4. Never change an architecture decision; only summarize it.
5. Say what is not being done.
6. Write in `{{LANG}}`. File names, IDs and section numbers stay in English.

**Section contents:**

| Section | Contents |
|---|---|
| §1 | Standalone, at most 300 words |
| §2 | Who hurts, today's workaround, cost of the status quo, evidence with source and confidence |
| §3 | Experience and outcome, not implementation |
| §4 | Segments by job-to-be-done, non-users, bottom-up size `[ESTIMATE]` |
| §5 | Alternatives table from CHECK verdicts, an honest moat |
| §6 | Container diagram copied verbatim from chosen/containers.md, top ADRs, why this candidate beat the others ("Alternatives considered") |
| §7 | In scope, out of scope, non-goals |
| §8 | Milestone 0 = run the pre-registered probe with its kill criterion; relative timeframes; exit criteria per milestone |
| §9 | Roles, effort ranges with confidence, AI-assisted vs human-only |
| §10 | Build and run cost copied from cost-model.md, unit economics or break-even |
| §11 | Top R-ids + pre-mortem + red-team kill-assumptions |
| §12 | Leading and lagging metrics, SMART key results, cheapest test per load-bearing assumption |
| §13 | Each item with `Owner: <role>` and `Decide by: <milestone>` |

**ONE-PAGER.md** (at most 550 words) has these headings: `## Problem`, `## Solution`, `## Why now`, `## Who`,
`## Differentiation`, `## Architecture at a glance` (one mermaid flowchart), `## MVP`, `## Roadmap`, `## Budget`,
`## Top risks` (3, each with its test), `## Metrics`, `## The ask`.

### 8.4 Schemas

**`rubric`:**

```
{"scores": {"decision_readiness", "substance_over_theater", "strategic_coherence", "doneness_clarity",
            "scope_honesty", "downstream_usability", "shape_fit"}      (each an integer 1-5)
 "evidence": {the same 7 keys: string},
 "must_fix": [{"section", "issue", "fix"}],
 "top_fixes": [string],
 "overall_comment": string}
```

The score range is checked in Python.

**`redteam`:**

```
{"items": [{"claim", "steelman", "fails_if", "impact", "likelihood", "cheapness",
            "cheapest_test", "kill_criterion"}]}          (impact, likelihood, cheapness: H/M/L)
```

The list has at most 8 items. The script ranks them by the product of impact, likelihood and cheapness (H/M/L = 3/2/1).

### 8.5 HTML pack (`render.py`, B3)

- **File.** A single `index.html` with inline CSS: system font stack, light and dark via `prefers-color-scheme`, print
  CSS with a page break before each h2, and a table of contents hidden when printing.
- **Markdown subset converter:** headings, paragraphs, lists, GFM tables, fenced code, emphasis, links, blockquotes.
- **Mermaid.** Blocks become `<pre class="mermaid">`. Mermaid ESM loads from `https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.esm.min.mjs`,
  which is one constant `MERMAID_CDN` [U-26]. Offline, the source text stays visible.
- **Layout:**
  1. Cover: title, pitch, date, status badge.
  2. One-pager card.
  3. Sticky table of contents.
  4. The 13 sections.
  5. Architecture: diagrams, ADR cards, risk table.
  6. Appendices.
- `ub render --zip` zips index.html, PROPOSAL.md, ONE-PAGER.md and `10_ARCHITECTURE/`.
- `ub export --format docx` runs `pandoc PROPOSAL.md -o export/PROPOSAL.docx` only when pandoc is on PATH.

---

## 9. Stage 14: Handoff (B3)

| ID | Type | What |
|---|---|---|
| 14.1 | T | software/growth with CONTEXT.proposed.md: host/CONTEXT-MERGE (the v1 Stage 12 step 1 flow, with the per-term yes and per-ADR yes) |
| 14.2 | H | G14: publish? Copy `10_ARCHITECTURE/` -> `docs/architecture/`, `adr/` -> `docs/adr/`, `11_PROPOSAL/` -> `docs/proposal/`. Each copy needs its own yes; the ADRs go with the copies that link to them: `architecture` and `proposal` also publish the adr copy. ADRs are published once, to the adr copy; the architecture copy leaves out `adr/`, and the ADR links of the architecture and proposal copies (README decision index, `chosen/`, Appendix A, sections, `index.html`) are rewritten, in the bytes, to point there. When no adr folder can be placed, the ADR links are left as they are and the card says so. Every copy gets its new files before any old file leaves, and a file that a published copy of this run not in the answer links to is never moved; the card says where the ADRs go. A target that holds another run's package (its `.ub-published` marker names another run) or files the kit did not publish (OS files such as `.DS_Store` aside) is never written: that item goes to `docs/<run>/<item>/` instead, and the card shows that target and, when another run holds the folder, warns and names it. Only this run's own earlier copy (also a 2.0.x `docs/<item>/ub-<run>/`) is updated in place: every file it replaces, and every file of it that the run's package no longer has, goes to `_superseded/<stamp>/published/<item>/` first (never over an older backup); unchanged files are left alone. The same holds when the package has no files any more. Exception: files that a pre-schema marker (kit 2.0.2 or earlier) of a fixed folder lists but the package does not have may be another run's; they stay in place, the card warns, and the marker keeps them apart as `legacy_files`; replacing a file of such a folder with other content is warned about too (it is backed up first). The marker (schema 2) is written before the first change, so an interrupted publish resumes in place. OS and editor files are never published and never make a folder taken. A fixed folder that is (or holds) a link or junction counts as taken (the copy goes to `docs/<run>/<item>/`); the item is not published, and the card says why and which folder to move aside, when `docs/` is a link, or when the fixed folder is taken and `docs/<run>/<item>/` is (or holds) a link or is taken too. When this run has two copies of an item (made while a folder was a link, say), the other one moves to the backup, except files a published copy links to; an item with no files shows "nothing to publish" unless this run published it before. Probe gate: without `RESULT: PASSED` the card warns "riskiest assumption untested" and the handoff seed carries it |
| 14.3 | S | Write the handoff seed: HANDOFF-CE (default for software/growth), HANDOFF-SPECKIT (greenfield: `specify init <proj> --integration <agent>` then /speckit.specify with PROPOSAL §3, §6-8 and chosen/), HANDOFF-SUPERPOWERS or HANDOFF-OPENSPEC (only when the repo already uses them). Every seed ends with "Do not reopen the choice of idea or architecture." |
| 14.4 | S | 12_HANDOFF.md (what was handed to which tool, with paths) + LEDGER update + DONE card with links |

The CE seed follows the v1 shape and adds: "Architecture decisions: brainstorm/<run>/10_ARCHITECTURE/README.md (ADRs
accepted). Milestone 0 (09_PROBE.md) runs first; do not plan beyond its kill criterion."

---

## 10. Installer and packaging (B1 detail)

### 10.1 Manifests (exact content; `OWNER` stays a placeholder)

```json
// .claude-plugin/plugin.json
{"$schema": "https://json.schemastore.org/claude-code-plugin-manifest.json",
 "name": "ultimate-brainstorm", "displayName": "Ultimate Brainstorm", "version": "2.0.0",
 "description": "Your ideas -> decided idea -> architecture package -> full proposal, across Claude, GPT, Kimi and GLM.",
 "author": {"name": "OWNER"}, "homepage": "https://github.com/OWNER/ultimate-brainstorm",
 "repository": "https://github.com/OWNER/ultimate-brainstorm", "license": "MIT",
 "keywords": ["brainstorming", "ideation", "architecture", "proposal", "multi-model", "kimi", "glm"]}
```

```json
// .claude-plugin/marketplace.json
{"$schema": "https://json.schemastore.org/claude-code-marketplace.json",
 "name": "ultimate-brainstorm", "owner": {"name": "OWNER", "url": "https://github.com/OWNER"},
 "description": "Evidence-based idea -> decision -> architecture -> proposal pipeline",
 "allowCrossMarketplaceDependenciesOn": ["claude-plugins-official"],
 "plugins": [
  {"name": "ultimate-brainstorm", "source": "./", "category": "productivity",
   "description": "Pipeline driver skill and scripts. Works alone; uses Compound Engineering and mattpocock skills when installed."},
  {"name": "ultimate-brainstorm-stack", "source": "./bundles/stack", "category": "productivity",
   "description": "EXPERIMENTAL: ultimate-brainstorm + mattpocock-skills in one install."}]}
```

```json
// bundles/stack/.claude-plugin/plugin.json   (experimental; the installer never uses it) [U-15]
{"name": "ultimate-brainstorm-stack", "version": "2.0.0", "description": "Installs ultimate-brainstorm and mattpocock-skills.",
 "author": {"name": "OWNER"},
 "dependencies": ["ultimate-brainstorm", {"name": "mattpocock-skills", "marketplace": "claude-plugins-official"}]}
```

```json
// .codex-plugin/plugin.json
{"name": "ultimate-brainstorm", "version": "2.0.0",
 "description": "Idea -> decision -> architecture -> proposal across model families.",
 "author": {"name": "OWNER"}, "homepage": "https://github.com/OWNER/ultimate-brainstorm",
 "repository": "https://github.com/OWNER/ultimate-brainstorm", "license": "MIT",
 "keywords": ["brainstorming", "architecture", "proposal"], "skills": "./skills/",
 "interface": {"displayName": "Ultimate Brainstorm",
   "shortDescription": "Idea -> architecture -> proposal with several model families",
   "longDescription": "Human ideas first, isolated multi-strategy generation, debiased both-order judging across model families, prior-art checks, a human decision, competing architectures judged blind, and a cited proposal.",
   "developerName": "OWNER", "category": "Productivity", "capabilities": ["Interactive", "Read", "Write"],
   "defaultPrompt": ["$ultimate-brainstorm standard product <your topic>", "$ultimate-brainstorm proposal <your idea>"]}}
```

```json
// .agents/plugins/marketplace.json
{"name": "ultimate-brainstorm",
 "plugins": [{"name": "ultimate-brainstorm", "source": {"source": "local", "path": "./"},
              "policy": {"installation": "AVAILABLE", "authentication": "ON_INSTALL"}, "category": "Productivity"}]}
```

```json
// .kimi-plugin/plugin.json
{"name": "ultimate-brainstorm", "version": "2.0.0", "license": "MIT",
 "description": "Idea -> decision -> architecture -> proposal across model families.",
 "homepage": "https://github.com/OWNER/ultimate-brainstorm", "skills": "./skills/",
 "systemPrompt": "The ultimate-brainstorm plugin is installed. When the user wants to brainstorm, decide what to build, or turn an idea into an architecture and a proposal, use the ultimate-brainstorm skill (/skill:ultimate-brainstorm <topic>).",
 "interface": {"displayName": "Ultimate Brainstorm", "shortDescription": "Idea -> architecture -> proposal",
               "developerName": "OWNER", "websiteURL": "https://github.com/OWNER/ultimate-brainstorm"}}
```

```json
// .kimi-plugin/marketplace.json
{"version": "2", "plugins": [{"id": "ultimate-brainstorm", "displayName": "Ultimate Brainstorm",
  "source": "https://github.com/OWNER/ultimate-brainstorm"}]}
```

```yaml
# skills/ultimate-brainstorm/agents/openai.yaml
interface:
  display_name: "Ultimate Brainstorm"
  short_description: "Idea -> decision -> architecture -> proposal across model families"
  default_prompt: "$ultimate-brainstorm standard general <your topic>"
policy:
  allow_implicit_invocation: false
```

Notes on the Kimi manifest:
- No `sessionStart.skill`: Kimi plugins are installed per user, so it would load into every session.
- No Kimi `commands`.

### 10.2 Install routes

The README shows all three routes, in this order.

1. **Installer (recommended).**
   - Local clone, today: `py -3 <kit>/install/install.py` prints the plan, then
     `py -3 <kit>/install/install.py install` applies it (it asks once).
   - After a release: the `curl | sh` and `irm | iex` shims in section 13.
   - No-pipe route: `git clone ... && python install/install.py install`.
2. **Native marketplaces, without the installer.**
   - Claude Code: `claude plugin marketplace add OWNER/ultimate-brainstorm@v2.0.0`, then
     `claude plugin install ultimate-brainstorm@ultimate-brainstorm --scope user`.
   - Codex: `codex plugin marketplace add OWNER/ultimate-brainstorm@v2.0.0`, then
     `codex plugin add ultimate-brainstorm@ultimate-brainstorm`, then restart Codex.
   - Kimi (TUI): `/plugins install https://github.com/OWNER/ultimate-brainstorm/releases/tag/v2.0.0`, then `/reload`.
   - ZCode: Settings > Plugins > add marketplace [U-21].
   - Components are then installed with the guide's section 3 commands.
3. **Universal:** `DISABLE_TELEMETRY=1 npx -y skills@1.7.0 add OWNER/ultimate-brainstorm -g -a claude-code -a kimi-code-cli -a zcode --copy -y`
   (Node 22.20+).
   - Kimi's global target is `~/.agents/skills`, which Codex also scans.
   - Never add `-a codex -g`: it writes the deprecated `~/.codex/skills`, and Codex would then list the skill twice.

### 10.3 Coverage rule: every agent sees exactly one `ultimate-brainstorm`

| Agent | Preferred route | Fallback | Skipped when |
|---|---|---|---|
| Claude Code | native plugin from the local marketplace `UB_HOME/kit`, `--scope user` (claude 2.1.268+) | copy to `{claude_home}/skills/ultimate-brainstorm` | - |
| Codex | native plugin from the local marketplace (codex 0.156+) | copy to `~/.agents/skills/ultimate-brainstorm` | - |
| Kimi | copy to `{kimi_home}/skills/ultimate-brainstorm` (Codex never scans it) | - | a Kimi plugin install is detected in `$KIMI_CODE_HOME/plugins/installed.json`, or the Codex fallback copy exists in `~/.agents/skills` (Kimi reads it) |
| ZCode | copy to `~/.zcode/skills/ultimate-brainstorm` | - | - |

- **Project scope** (`--scope project --project-dir D`):
  - Claude: `--scope local` (never `project`: that writes the tracked `.claude/settings.json`);
  - Codex and Kimi: copy to `D/.agents/skills`;
  - ZCode: `D/.zcode/skills`.
  - Kimi needs a `.git` folder in D to find the project root [L]; when it is missing, the plan warns and offers
    `--git-init`.
- **Named but not detected.** An agent named in `--agents` whose CLI is not installed gets the copy route, because
  native routes need the CLI. This supports installing before the agent itself.
- **v1 migration.** A folder named `ultimate-brainstorm` without the marker whose SKILL.md says `version: "1.0"` is
  reported as `migrate-v1`. With `--migrate-v1` (or an interactive yes), it is backed up and replaced. Otherwise
  `skip-not-owned` plus a warning.

### 10.4 Apply, ownership, atomicity, limits

1. **Stage the kit.** Copy `runtime_paths` from the source (the repo containing `install.py`, or the downloaded and
   SHA-256-verified release archive) to `UB_HOME/kit.new-<rand>`:
   - rename the current `UB_HOME/kit` to `kit.old-<rand>`;
   - rename `kit.new-<rand>` to `kit`;
   - delete the old folder.

   On failure, restore and report. Exclude `__pycache__`, `*.pyc`, `.git`, `tests`, `tools`, `.github` and `.build`.
2. **Native steps.**
   - Check the host's plugin list first (`--json`). Skip work that is already done.
   - Log every command and its exit code to `install.log`.
   - Run with `CLAUDE_CONFIG_DIR` / `CODEX_HOME` when the matching flag is given.
3. **Copies.**
   - Stage into `<dest>.ub-new-<rand>` on the same volume, then swap as in step 1. Write the `.ub-owned` marker. Record
     SHA-256 per file in the manifest.
   - Never replace a folder without the marker (`skip-not-owned`; with `--force` the folder is backed up first).
   - An owned file whose hash differs from the manifest was edited by the user: move it to
     `UB_HOME/backups/<ISO>/<agent>/...` before replacing it.
4. **Components** (default `core`: Compound Engineering + mattpocock grilling/domain-modeling) follow
   `components.json`:
   - Node older than 22.20 turns `npx` rows into `manual`.
   - `UB_INSTALL_OFFLINE=1` turns every network row into `manual`.
5. **CLIs.** With `--with-clis`, run `npm install -g <pkg>` per CLI after confirmation. Never use sudo. On Windows,
   check first that Git Bash exists for Kimi. With `--login`, run `codex login` and `kimi login` in the foreground (the
   user completes them) and print the Claude sign-in hint.
6. **Launchers.** Always write `UB_HOME/bin/ub`, `ub.cmd` and `ub.ps1`. Never edit PATH; print how to add `UB_HOME/bin`.
7. **Routing block.** Only with `--routing-block`: insert the guide's routing block between
   `<!-- ultimate-brainstorm:begin -->` and `<!-- ultimate-brainstorm:end -->` markers into `~/.claude/CLAUDE.md`,
   `~/.codex/AGENTS.md`, `~/.kimi-code/AGENTS.md` and `~/.zcode/AGENTS.md`, for detected agents only.
8. **Hard limits:**
   - no sudo or admin;
   - refuse to run as root without `UB_ALLOW_ROOT=1`;
   - no PATH or rc edits;
   - never read or write API key values (only env var names are checked);
   - no edits to `settings.json`, `config.toml`, `CLAUDE.md` or `AGENTS.md` outside the flags above.
9. **Interaction.** Without `--yes`, a TTY is required to confirm; without a TTY, the plan is printed, the installer
   exits 0 and it says "re-run with --yes".

### 10.5 update, uninstall, doctor, list

- **update:**
  1. Re-stage the kit: local `--source`, or `--tag`/latest via `https://github.com/OWNER/ultimate-brainstorm/releases/latest` [L].
  2. Claude native loads in place from the local marketplace, so nothing more is needed. It also runs
     `claude plugin marketplace update ultimate-brainstorm` [U-16], which is allowed to fail.
  3. Codex native: `codex plugin marketplace upgrade ultimate-brainstorm --json`, then `codex plugin add ...` [U-10].
     On failure: `remove` + `add`.
  4. Copies: hash-based update with backups.
- **uninstall:**
  - native removals (`claude plugin uninstall ...`, `claude plugin marketplace remove ultimate-brainstorm`,
    `codex plugin remove ... --json`, `codex plugin marketplace remove ... --json`);
  - delete marker-owned copies whose hashes match the manifest;
  - remove the routing blocks between markers and the launchers;
  - print the manual steps (Kimi `/plugins remove ultimate-brainstorm`, the ZCode UI);
  - keep run folders and backups. `--purge` also removes `UB_HOME` except `backups/`.
- **doctor.** Read-only; PASS, WARN or FAIL, each with a fix; exit 1 on any FAIL.
  - Output shape: `{"checks":[{"id","status","detail","fix"}],"exit":0}`.
  - Environment: Python/git/Node versions; Git Bash on Windows (and `KIMI_SHELL_PATH`).
  - Agents: versions against their minimums; the skill present per agent, with its hash; SKILL.md frontmatter
    (description at most 1024 characters, `name` equal to the folder name).
  - Duplicates: the same skill name across all directories each agent scans, including `~/.codex/skills` against
    `~/.agents/skills`, for `ultimate-brainstorm`, `grilling` and `domain-modeling`.
  - Legacy installs: a v1 copy; the legacy `~/.kimi`.
  - Stack: components present; families (runs `PY UB_HOME/kit/skills/ultimate-brainstorm/scripts/family.py detect --json [--live]`
    and reports its families block); stale backups older than 90 days.
  - Invocation hint per agent.
- **list:** installed items per agent (owned or foreign, route, version).

### 10.6 setup-glm, setup-kimi

- **`setup-glm`:**
  - Checks `ZAI_API_KEY` (name only). If it is missing, prints how to set it for the current OS shell:

    ```
    PowerShell: [Environment]::SetEnvironmentVariable("ZAI_API_KEY","<key>","User")
    bash:       export ZAI_API_KEY=<key> in your profile
    ```

  - `--launcher` writes `claude-glm` (sh/cmd/ps1).
  - `--codex` writes `codex-homes/glm/config.toml` and the `codex-glm` launchers, and installs the Codex plugin into
    that home.
  - `--zai-mcp` renders `zai-mcp.json.tpl`: the web-search-prime and web-reader HTTP servers with an
    `Authorization: Bearer` header filled in at launch time.
  - `--region cn` switches every base URL to `open.bigmodel.cn`.
  - It prints the policy note: "The GLM Coding Plan may be used only in supported tools; this kit sends GLM traffic only
    through Claude Code or Codex."
- **`setup-kimi`:** the same pattern with `--provider kimi` (Platform key `KIMI_API_KEY`) or `kimi-code` (membership
  key `KIMI_CODE_API_KEY`). It never tells users to `export KIMI_API_KEY` for the Kimi Code CLI itself (that CLI
  ignores it [V]); for Kimi Code CLI it prints `kimi login`.

### 10.7 Bootstrap shims and release

- **`install.sh`** (POSIX sh; also works in Git Bash):
  - `main() { ... }` with `main "$@" || exit 1` on the last line.
  - Refuses root unless `UB_ALLOW_ROOT=1`.
  - Finds `python3`, `python` or `py -3` at version 3.9+; with no Python, prints the install hint (`brew install python`
    or `winget install Python.Python.3.12`) and exits 1.
  - Downloads `ultimate-brainstorm-<ver>.tar.gz` from
    `https://github.com/OWNER/ultimate-brainstorm/releases/download/v<ver>/` (or copies from `UB_RELEASE_DIR`).
  - Verifies the SHA-256 embedded in the script (`sha256sum`, `shasum -a 256`, or Python `hashlib`).
  - Extracts to a temp dir and runs `python install/install.py "$@"`, with stdin from `/dev/tty` when it exists.
  - Cleans up.
- **`install.ps1`** (PowerShell 5.1):
  - Sets TLS 1.2.
  - `function Main { param([string[]]$Rest) ... }` with `Main $args` last.
  - `$ErrorActionPreference = 'Stop'` inside `Main`, so any error (even a cmdlet that fails to load) ends the
    script with a non-zero exit instead of skipping the hash check and exiting 0.
  - Downloads the `.zip` (or copies from `UB_RELEASE_DIR`), checks it with `Get-FileHash -Algorithm SHA256`, and
    extracts it with `Expand-Archive`.
  - Finds Python: `py -3`, then `python` when its path does not contain `WindowsApps`.
  - Runs the installer.
- **`tools/release.py --version 2.0.0 --owner <gh-user> --out dist/`:**
  - substitutes `OWNER` in the manifests, `targets.json` and the docs, in the archive copy only (never in the repo);
  - builds the `.tar.gz` and `.zip` of `runtime_paths`;
  - computes SHA-256, renders `install.sh` and `install.ps1` with the version, owner and hashes, and writes
    `SHA256SUMS`.
- **`.github/workflows/release.yml`** runs `python tools/ci.py all`, then `release.py`, then uploads the assets with
  `gh release`.

### 10.8 README.md and user docs

**README** (at most 250 lines), in order:
1. What it is (5 lines + the pipeline diagram).
2. Install: the three routes, installer first.
3. Quickstart per host, one line each.
4. Model families: how to add GPT, Claude, Kimi and GLM (link to FAMILIES.md).
5. Privacy (5 lines + PRIVACY.md).
6. What you get (file list).
7. Troubleshooting link.
8. Credits (NOTICE.md).

**User docs:**

| File | Contents |
|---|---|
| `docs/INSTALL.md` | Every command in section 13, per OS; components; uninstall |
| `docs/HOSTS.md` | The platform matrix (section 14) in user words |
| `docs/FAMILIES.md` | Per family: CLI install, login, keys, launchers, costs and plan notes (GLM Coding Plan tool policy; Kimi K2 discontinued; the Kimi CLI ignores `KIMI_API_KEY`) |
| `docs/PRIVACY.md` | What goes to which vendor; `private`; the `code` flag |
| `docs/TROUBLESHOOTING.md` | The BLOCKED-card fixes, installer doctor fixes and Windows notes |

**Repo files:**
- `AGENTS.md` (contributor rules: layout, stdlib only, ASCII templates, running tests) and `CLAUDE.md` containing
  `@AGENTS.md`.
- `NOTICE.md` attributions:
  - BMAD PRD rubric and brief ideas (MIT);
  - pm-skills red-team method (MIT);
  - Compound Engineering bake-off pattern (MIT);
  - MADR 4.0 (MIT OR CC0);
  - arc42 section names and C4 (names only);
  - Semantic-Anchors traceability rules (paraphrased);
  - creative-director CC BY 4.0 line, kept wherever its rules are reused;
  - the v1 guide's sources.
- `LICENSE` (MIT).

### 10.9 docs/GUIDE.md

Start from `ULTIMATE_BRAINSTORMING_WORKFLOW.md`, copied as is. Then:
1. Insert after the title a new section `## 0. The kit (v2)`: a one-screen summary of sections 1, 6.1 and 6.2 of this
   spec, and the host commands.
2. Section 3 (install guide): put the installer first. Keep the manual commands as "without the installer", and add
   Kimi Code, ZCode and GLM rows.
3. Add `### Stage 12 - Architecture`, `### Stage 13 - Proposal` and `### Stage 14 - Handoff` after section 4's
   Stage 11, summarizing sections 7-9. The v1 Stage 12 becomes Stage 14.
4. Update the stack table in section 1: the "second model family" row becomes "model families (N)", with Kimi and GLM.
5. Change nothing in sections 2 and 6 except cross-references.
6. Mark every changed section with `(updated in v2)`.

---

## 11. Test harness and CI (B4 detail)

### 11.1 Isolation for every test that touches the filesystem

`tests/harness/tmphome.py` provides a context manager with these settings:
- `HOME`, `USERPROFILE`, `APPDATA`, `LOCALAPPDATA`, `XDG_CONFIG_HOME`, `CLAUDE_CONFIG_DIR`, `CODEX_HOME`,
  `KIMI_CODE_HOME` and `UB_HOME` point into a temporary directory;
- `PATH` = the fake bin folder + the directory of `sys.executable` (+ `C:/Windows/System32` on Windows);
- `UB_FAKE_PY` = `sys.executable`.

`fsnap.py` snapshots a tree (path -> sha256, mtime) before and after, and asserts which paths changed.

### 11.2 Fake CLIs and the HTTP stub

- **Fakes** follow section 4.18. `shims.py` builds them per OS.
- **`http_stub.py`** runs a `ThreadingHTTPServer` on `127.0.0.1:0` serving `/v1/chat/completions` and `/v1/messages`,
  with scripted sequences (for example 429 with `Retry-After: 1`, then 200).

### 11.3 Stubs (`ublib/stubs.py`)

Implements section 4.17. Generation for each contract type:
- **json:** walk the schema; honor `cover`. Deterministic values come from `random.Random(sha256(job id))`.
- **idea-blocks:** `min` blocks, with `Cell` values from `stub.axes` so that the pool does not homogenize (unless
  `UB_STUB_HOMOGENIZED`).
- **Curator:** assign each alias to a canonical idea, 3 aliases per idea, cluster count between 6 and 12, cells cycling
  over the axes, `primary: true` for ideas with `HP-` aliases.
- **Final lines:** reviewer verdicts cycle BACK, BACK IF, DON'T BACK; check verdicts cycle NOT LOCATED, ADJACENT,
  CROWDED; SYNTHESIS gives `WHOLE-EFFORT: CONTINUE`; PROBE gives `RESULT: PENDING`.
- **files:** every required file with its headings and minimal valid mermaid, plus STATUS. Packages built from
  `stub.containers` are coherent enough to pass lint (a should-level requirement).

### 11.4 Installer tests (`tests/integration/test_installer_*.py`)

**Plan:**
- The plan writes nothing (`fsnap`).
- Golden plans for: no agents (exit 3); all 4 agents detected; only Codex; Codex 0.140 (copy route); claude 2.1.200
  (copy route); Kimi 1.x (legacy warning, unavailable); `CLAUDE_CONFIG_DIR`, `CODEX_HOME` and `KIMI_CODE_HOME`
  honored.

**Install:**
- `install --yes` creates the markers, the manifest with correct SHA-256 and `UB_HOME/kit`. Native rows execute exactly
  the argv lists in `targets.json` (checked in `UB_FAKE_LOG`). A second run shows every row `unchanged` and modifies no
  mtimes.
- Coverage: Kimi's copy is skipped when the Codex copy route wrote `~/.agents/skills`; when Codex is native, Kimi gets
  its own copy.
- An edited owned file gives `backup+update`, and the backup exists.
- A foreign folder gives `skip-not-owned`; with `--force` it is backed up and replaced. A v1 folder gives `migrate-v1`.
- Atomicity: a failure injected during the swap (monkeypatch `os.replace` to raise once) leaves the old tree intact and
  cleans up the temp folders.
- Components: CE and grilling rows produce the exact argv. Node 20 turns npx rows into manual.
  `UB_INSTALL_OFFLINE=1` gives manual rows.
- Non-TTY without `--yes`: prints the plan, exits 0, applies nothing.
- `--routing-block`: inserted exactly once between the markers, and removed exactly by uninstall.
- Argv audit: no install command contains any environment value named `*_KEY` or `*_TOKEN`.

**Update, uninstall, doctor:**
- update re-stages the kit and re-runs Codex `add`. On a simulated failure it falls back to remove + add.
- uninstall removes only owned paths and marker-verified copies, keeps backups and runs, and prints the manual steps.
  `--purge` keeps `backups/`.
- doctor: each check reaches PASS, WARN and FAIL in at least one case. A duplicate `ultimate-brainstorm` in both
  `~/.agents/skills` and `~/.codex/skills` gives FAIL and exit 1. A fake `~/.claude/settings.json` with a z.ai base URL
  gives WARN "claude family reclassified as glm". `--json` shape.

**Launchers** (`test_launchers.py`), with a fake `claude`:
- `claude-glm --version` passes `--settings <file>`; the file exists while the fake runs, has mode 0600 (POSIX), holds
  the expected env block and is deleted afterwards.
- The token never appears in argv or in `UB_FAKE_LOG`.
- A missing `ZAI_API_KEY` gives exit 2 with the message.
- `codex-glm` sets `CODEX_HOME`.

**Bootstrap** (`test_bootstrap.py`):
- `sh -n install.sh` passes.
- Git Bash, on Windows when available: rendered `install.sh` with `UB_RELEASE_DIR` succeeds; a wrong hash aborts before
  extraction; root is refused (POSIX CI only).
- PowerShell 5.1 (`powershell -NoProfile -File`, when available): the same cases for `install.ps1`, plus a parse check
  via `[System.Management.Automation.Language.Parser]::ParseFile`.

### 11.5 Adapter tests against fake executables (`tests/integration/test_fake_backends.py`)

**claude:**
- argv contains `-p`, `--output-format json`, `--no-session-persistence`, `--strict-mcp-config`,
  `--disallowedTools mcp__*`, and `--tools ""` for tools `none`. It never contains `--bare`, prompt text or a secret.
- The prompt arrives on stdin (sha matches). The cwd is empty and outside the run folder.
- The parent's `ANTHROPIC_BASE_URL=https://api.z.ai/...` does not reach the child for family claude.
- The `@glm` settings file exists during the call and is gone afterwards.

**codex:**
- argv contains `exec --skip-git-repo-check --ephemeral -s read-only -C <dir> -o <file> --json` and ends with `-`.
- `-c web_search=live` appears only for web jobs. `--output-schema` appears only on the native OpenAI backend.
- `CODEX_HOME` is set for `@glm`.

**kimi:**
- argv contains `--agent-file`, `--skills-dir`, `--output-format stream-json`, and `-p` with the fixed text. It never
  contains `--yolo`, `--auto` or `--plan`.
- The agent file has `tools: []` and the escaped body.
- The env holds `KIMI_CODE_NO_AUTO_UPDATE=1` and `KIMI_CODE_BACKGROUND_PRINT_BACKGROUND_MODE=exit`.
- Stream-json parsing works with tool-call noise and text-part lists.

**All backends:**
- On Windows each fake runs through a `.cmd` shim, and paths with spaces and the argument `glm-5.3[1m]` survive.
  An argument containing `&` is refused.
- Scenarios `timeout` (the fake spawns a child; the whole tree dies; exit 6), `fail_once` (the retry succeeds),
  `garbage` (invalid, repair, then exit 5), `utf16`, `bom`, `fence` (all parse), `is_error` (exit 4, no auth retry).
- Worker protocol: running marker plus heartbeat; kill the worker -> the state becomes `dead` after 60 s (a test
  override `UB_HEARTBEAT_STALE_S=3` is allowed as a `UB_TEST_*`-style constant in batch.py) -> relaunch.

### 11.6 End-to-end dry runs (`tests/e2e/`)

Each runs in a temporary project with `UB_FAKE_FAMILIES=1`, `UB_NO_DETACH=0` and the stubs.

| Test | Command and assertions |
|---|---|
| E1 modes | `ub run --text "shift-swap app for nurses" --mode M --autopilot full-auto --root <tmp>` for M in quick, standard, deep, proposal. Exit 0, DONE. Every file in 4.1, 7.1 and 8.1 for that mode exists. PROGRESS.md shows 100%. `calls.jsonl` ok-count lies within `ub plan --json` [min, max]. run.json gates are `by: auto`. PROPOSAL.md has the AUTOPILOT DRAFT banner. fsnap: no writes outside `<tmp>` and `UB_HOME` |
| E2 variants | research (approach build type, `## 6. Approach`, no G11) and software (archetype A text = "Smallest change...") |
| E3 guided protocol | `answerer.py` drives `ub init/next/answer/done --json` like a host: HUMAN -> `default_answer`, except scripted choices at G8b (a non-leader ID) and G11 (label B); HOST (frame-grill with `--components grilling`) -> writes the fixture frame files and runs `done_cmd`; HOST_BATCH (`UB_FAKE_HOST_BACKEND=glm`) -> for each job, reads the job JSON and prompt, calls `ublib.stubs.respond(job, prompt)` and writes `out`. Asserts DONE; 08_DECISION.md names the scripted idea and quotes `why`; `10_ARCHITECTURE/README.md` names candidate B |
| E4 crash/resume | `UB_TEST_CRASH_AT=6.2` and 12.11 -> `ub run --continue` reaches DONE. No job with status ok appears twice in `calls.jsonl` for the same (id, prompt_sha256). Killing live workers mid-step (via `stop`) followed by continue completes |
| E5 cross-host | init with `--host claude-code`, run to G8a, then `continue --host codex` with `UB_FAKE_DISABLE=kimi` -> re-seat recorded in `run.json.provisional`, and the run completes |
| E6 privacy | `private`: only host-family jobs, every other seat `-alt`, no job with `web` tools, PROVISIONAL banner. `code=false` in a fake repo: jobs for other vendors never have `cwd: repo`, and their FACTS contain no fenced code |
| E7 seed leak | a doctored generator prompt containing a seed line -> BLOCKED card naming the rule |
| E8 fake-CLI quick | quick mode, full-auto, with the REAL backends against fake executables on PATH (claude, codex, kimi) including Windows `.cmd` shims -> DONE; argv audit of `UB_FAKE_LOG` (no prompt text, required flags present) |

### 11.7 Static checks (`tests/static/`, also callable as `tools/validate_kit.py`)

- Every manifest parses and has its required fields:
  - Claude `name`; marketplace `owner` and `plugins[].source`;
  - Codex `skills` and `interface.defaultPrompt` (at most 3, each at most 128 characters);
  - Kimi `name` matches `^[a-z0-9][a-z0-9_-]{0,63}$`; Kimi marketplace `version` "2".
- Every `./` path exists. No path contains a backslash. No root `plugin.json`, `agents/`, `bin/`, `hooks/` or
  `.mcp.json`.
- SKILL.md:
  - the first line is `---`;
  - frontmatter keys are a subset of {name, description, license, compatibility, metadata, allowed-tools};
  - `name` equals the folder name;
  - description at most 1024 characters; compatibility at most 500 characters;
  - file at most 12 KB.
- `openai.yaml` has `allow_implicit_invocation: false`.
- Exactly one SKILL.md exists in the repo.
- Versions are equal everywhere (3.4).
- `targets.json` and `components.json` validate against their shape. `families.default.json` has every backend it
  references.

### 11.8 CI

**`.github/workflows/ci.yml`:**
- Matrix: {ubuntu-latest, macos-latest, windows-latest} × Python {3.9 (where setup-python provides it), 3.12, 3.14}.
  Each runs `python tools/ci.py all`.
- Extra Windows jobs:
  - `shell: bash` (Git Bash) runs the install.sh bootstrap test;
  - `shell: powershell` (5.1) runs the install.ps1 bootstrap test.
- Optional job (`continue-on-error: true`): `npm install -g @anthropic-ai/claude-code` then
  `claude plugin validate . --strict` [U-17].

**`tools/ci.py`** takes `unit`, `integration`, `e2e`, `static` or `all`. It runs each suite in its own process:
`python -m unittest discover -s tests/<suite> -t tests/<suite> -p "test_*.py"`. It prints a summary and returns non-zero
on any failure.

**`.github/workflows/drift.yml`** runs weekly. It fetches `vercel-labs/skills` `src/agents.ts` and diffs the
claude-code, codex, kimi-code-cli and zcode paths against `targets.json`. It opens an issue on a mismatch; it never
auto-edits.

### 11.9 docs/ACCEPTANCE.md (manual, on real machines)

For each host (Claude Code, Codex, Kimi Code, Claude Code on GLM, Codex on GLM, ZCode):
1. `install.py doctor --live`: PONG from every family.
2. A quick run to DONE.
3. One standard run on at least 2 hosts.
4. `continue` from a second host.

Record the result of every item in section 15, and capture sanitized fixtures (Kimi stream-json, Codex JSONL, the
Claude result JSON) into `tests/fixtures/adapter/live/`.

---

## 12. Builder work packages

The builders work in parallel.

**Dependencies:**
- B2's `ublib/textio.py`, `schema_lite.py`, `validate.py` and `filesproto.py` come first; B3 and B4 import them. B2
  lands those four modules and their tests before anything else.
- Otherwise every builder codes against section 4. Until a dependency lands, a builder may monkeypatch it in its own
  tests.

### 12.1 B1: installer, packaging manifests, README and user docs

**Files it creates** (exclusive; see section 2):
- the manifests in 10.1;
- `SK/agents/openai.yaml`;
- `install/*` (install.py, targets.json, components.json, install.sh, install.ps1);
- `profiles/*`;
- `tools/release.py`, `.github/workflows/release.yml`;
- `README.md`, `AGENTS.md`, `CLAUDE.md`, `CHANGELOG.md`, `LICENSE`, `NOTICE.md`, `VERSION`, `.gitattributes`,
  `.gitignore`;
- `docs/GUIDE.md`, `docs/INSTALL.md`, `docs/HOSTS.md`, `docs/FAMILIES.md`, `docs/PRIVACY.md`,
  `docs/TROUBLESHOOTING.md`;
- `.build/B1-notes.md`.

**One-time skeleton:**
- run `git init` in `kit/`;
- `.gitignore` covering `__pycache__/`, `*.pyc`, `dist/` and `.build/*.tmp`;
- `.gitattributes` per 3.1.

B1 creates no other builder's files.

**Interfaces it must honor:**

| Section | Interface |
|---|---|
| 4.14 | Installer CLI, plan JSON, manifest, marker, exit codes |
| 4.15 | `targets.json` and `components.json` content |
| 4.16 | Launchers and codex homes. Reads `families.default.json` `providers` itself |
| 10.x | Manifests exact, coverage rule, apply rules, limits |
| 3.3 | Env vars (`UB_HOME`, `UB_INSTALL_OFFLINE`, `UB_RELEASE_DIR`, `UB_ALLOW_ROOT`, agent homes) |
| 3.4 | Versions |
| doctor | Calls `family.py detect --json` as a subprocess and treats a missing kit or a failure as WARN |

**Acceptance.** B4 writes the tests; B1 must pass them:
- `tests/integration/test_installer_*.py`, `test_launchers.py`, `test_bootstrap.py`;
- `tests/static/test_manifests.py`, `test_versions.py`.
- Manual on this machine:
  - `py -3 kit/install/install.py` prints a plan and writes nothing. With no agent CLIs installed, it exits 3 and lists
    `--with-clis` hints.
  - `py -3 kit/install/install.py install --agents kimi --yes` (pre-install for a named agent) copies the skill into
    `~/.kimi-code/skills/ultimate-brainstorm` with its marker and manifest.
  - `uninstall --yes` removes it.
- `python tools/release.py --version 2.0.0 --owner test --out dist/` produces the 2 archives, `SHA256SUMS` and the
  rendered shims.
- The GUIDE.md diff touches only the sections listed in 10.9.

**Definition of done:** every acceptance item passes on Windows 11 with Python 3.11 and 3.14, and in CI on the
3 OSes. `.build/B1-notes.md` lists every [U] item touched.

### 12.2 B2: model-family adapter, `bs.py` N-family generalization, lints, tests

**Files it creates:**
- `SK/scripts/family.py`, `bs.py` (started from a copy of v1 `bs.py`), `families.default.json`;
- `SK/scripts/ublib/{__init__,textio,schema_lite,validate,filesproto,proc,redact,families,detect,adapter,batch,lints}.py`;
- `SK/scripts/ublib/backends/{__init__,claude_cli,codex_cli,kimi_cli,http_openai,http_anthropic,stub}.py`;
- `tests/unit/test_{textio,schema_lite,validate,filesproto,proc,family_claude,family_codex,family_kimi,family_http,detect,batch,bs_legacy,bs_nfamily,bs_arch_matrix,bs_misc,lints}.py`;
- `tests/fixtures/{bs,lint,adapter}/**`, `tests/golden/bs/**`;
- `.build/B2-notes.md`.

**Interfaces it must honor:**

| Section | Interface |
|---|---|
| 4.4-4.10 | Job JSON, contract types, FILE protocol, worker protocol, `family.py` CLI and Python API (frozen signatures), `families.default.json` content, `bs.py` CLI and outputs |
| 5.x | Argv, env policy, safe defaults, detection, policy guards, bookkeeping math, lint rules |
| 3.3 | Test seams (`UB_JOB_FILE`/`UB_JOB_ID` in every child env; `UB_FAKE_FAMILIES`, `UB_FAKE_DISABLE`, `UB_FAKE_HOST_BACKEND`, `UB_NO_DETACH`) |

B2 unit tests mock the process boundary at `ublib.proc.run(argv, cwd, env, stdin_bytes, timeout_s) -> ProcResult(returncode, stdout_bytes, stderr_bytes, timed_out)`.
That function is the single seam; every backend goes through it.

**Acceptance tests** (B2 writes and passes; stdlib unittest):

*bs.py legacy:*
- `test_bs_legacy.py`: both v1 harnesses (the scratchpad `test_bs.py` and the `judge-uxtest/` cases) ported into
  unittest. With no `run.json`, outputs are byte-identical to the goldens produced by v1 `bs.py` on the same inputs
  (generate the goldens once with v1 and commit them). Covered: gate kills and floor, human slot, both-order tallies,
  a position-biased judge, a self-preferring judge, per-pair mode, fenced/UTF-16/missing outputs, dupcheck fallback,
  and every status check.

*bs.py N families* (`test_bs_nfamily.py`):
- N=3 and N=4: the maximum points = F(n-1);
- the 2/3 contested rule (and that N=2 reproduces v1);
- debiased standings drop own-vendor pairs and inconsistent families;
- `-alt` and provisional judges are excluded from the audit;
- the own-origin gap flag;
- judge agreement WARN;
- `result.json` shape.

*arch-matrix* (`test_bs_arch_matrix.py`):
- the own-family exclusion (and the sole-judge fallback);
- veto semantics: 2 judges -> excluded; 1 judge -> flagged; the only judge -> flagged with the note;
- rank ranges; `leader_status` clear or close-call;
- the steal merge.

*Other bookkeeping and lints:*
- `test_bs_misc.py`: quick-pick selection rules; split path guards (`..`, absolute, drive letter, disallowed extension,
  empty file, duplicates); sources ID stability across re-runs; assumptions extraction; `coverage.json`.
- `test_lints.py`: one good and one bad fixture per rule A1-A9, P1-P10 and frame; lite mode.

*Validators and adapter:*
- `test_validate.py`: every contract type, positive and negative; the repair prompt text.
- `test_family_*.py`:
  - argv exactly as in 5.2 per backend, tools profile, tier, alt and provider;
  - env policy (the z.ai base URL scrubbed for claude and restored for anthropic.com; provider tokens never in env or
    argv);
  - the settings file is 0600 and deleted;
  - the Kimi agent file has correct frontmatter and `${x}` escaped;
  - parsing: claude JSON (success, is_error, auth), codex `-o` file and JSONL usage, kimi stream-json variants
    (string, parts, tool noise), HTTP shapes, 429 then 200;
  - retries, chain order and repair;
  - policy exits 7 for every rule in 5.6;
  - timeout tree-kill (a real subprocess spawning a child);
  - redaction of a known key value in meta and logs.
- `test_detect.py`: claude settings pointing at z.ai -> reclassified glm; codex config with a ZAI provider -> glm;
  kimi 1.x -> unavailable with the migrate note; provider backends gated by the key env var; fake mode.
- `test_batch.py`: detached launch (a real worker running the stub backend), heartbeat, stale detection, relaunch
  counter, `run_foreground` budget stop, `stop_all`.

**Definition of done:** `python tools/ci.py unit` passes for B2's files on Windows (3.11 and 3.14) and in CI. v1
goldens are unchanged.

### 12.3 B3: skill content, autopilot engine, new Architecture and Proposal stages

**Files it creates:**
- `SK/SKILL.md`;
- `SK/references/*.md` (6.14);
- `SK/templates/{prompts,host,gates,docs,schemas}/*`;
- `SK/scripts/{ub.py,pipeline.json,estimates.json}`;
- `SK/scripts/ublib/engine/*.py`;
- `tests/unit/test_engine_*.py`, `test_render.py`, `test_templates.py`;
- `tests/fixtures/engine/**`;
- `.build/B3-notes.md`.

**Interfaces it must honor:**

| Section | Interface |
|---|---|
| 4.1-4.3 | Run layout, run.json, 00_RUN.md v1 lines |
| 4.4 | Emits job JSON with contracts |
| 4.11-4.13 | `ub.py` CLI, card JSON, answer protocol, gate templates |
| 4.17 | Fills `job.stub` facts |
| 4.19 | Only the listed test hooks (`UB_TEST_CRASH_AT`) |
| 6.x-9.x | Steps, gates, seats, evidence enforcement, privacy, progress, templates, SKILL.md, references, stages 12-14 formats and flows |

B3 uses B2 only through the frozen API (4.8), the `bs.py` subprocess and the `family.py` worker.

**Acceptance tests** (B3 writes and passes):
- `test_engine_pipeline.py`: step sequences for every mode × autopilot combination match the gate table in 6.2
  (golden lists of step IDs and gate IDs); predicates and fanouts; `min_ok`, fallback and BLOCKED logic, using a fake
  `batch` module.
- `test_engine_gates.py`:
  - every gate has a template, an `answer_template` and a `default_answer`;
  - answer validation, errors and re-ask;
  - the deterministic terminal parser (G0 keywords vs seed lines, including "deep learning ideas" staying a seed;
    G8a IDs; G13 `changes:`).
- `test_engine_seats.py`: tables for 1-4 families, host variants (claude, gpt, kimi, glm), privacy `vendors=false`,
  and web capabilities.
- `test_engine_privacy.py`: seed-leak and pool-leak detection; origin-label refusal; code stripping for other vendors.
- `test_engine_builders.py`: every template resolves every placeholder for fixture runs; host prompt variants end with
  `OUTPUT FILE:`; the `job.stub` facts listed in 4.17 are present.
- `test_engine_state.py`: run.json round trip; v1 migration of a fixture v1 run (from the v1 golden run folder); lock
  staleness; redo moves to `_superseded/`.
- `test_engine_progress.py`: `ub plan` monotonic in families and mode; PROGRESS.md format; budget gate.
- `test_render.py`: index.html of a fixture proposal has the table of contents, `pre.mermaid` blocks, the badge and the
  appendix anchors; zip contents.
- `test_templates.py`: ASCII only, header line, skill-guard line for isolated templates, no `${`, placeholders known.
- SKILL.md is at most 12 KB and has the frontmatter per 6.13 (B4's static test checks it too).

**Definition of done:** `python tools/ci.py unit` passes for B3's files, and B4's e2e suite passes once B2 and B4 land.

### 12.4 B4: test harness, fake CLIs, installer and e2e tests, stubs, CI

**Files it creates:**
- `SK/scripts/ublib/stubs.py`;
- `tests/harness/*`;
- `tests/integration/*`, `tests/e2e/*`, `tests/static/*`;
- `tests/fixtures/{installer,e2e}/**`;
- `tools/ci.py`, `tools/validate_kit.py`;
- `.github/workflows/{ci,drift}.yml`;
- `docs/ACCEPTANCE.md`;
- `.build/B4-notes.md`.

**Interfaces it must honor:**
- 4.17 (stubs), 4.18 (fakes), 4.19 (hooks);
- 4.14 and 4.15 (asserting the installer);
- 4.4-4.8 (jobs, contracts, worker, adapter CLI);
- 4.11-4.12 (driving the engine like a host);
- 3.3 (env);
- 3.1 (stdlib unittest only, no network in default suites).

**Acceptance.**
- B4's own harness self-tests:
  - `fakecli.py` emits each native format, validated by parsing it back;
  - `.cmd` shims pass `%*` intact for the argv cases in 11.5;
  - `tmphome` isolates `HOME` and `USERPROFILE`;
  - stubs produce contract-valid output for every contract type and every template kind listed in 6.12.
- Every test in 11.4-11.7 exists and runs. They pass against a correct B1, B2 and B3; the tests themselves follow this
  spec, not builder quirks.
- `python tools/ci.py all` runs every suite and summarizes. CI YAML is valid; `ci.yml` runs on the 3 OSes.

**Definition of done:** all suites pass after integration on Windows 11 (Python 3.11 and 3.14, PS 5.1 and Git Bash)
and in CI.

### 12.5 Integration (lead, after the builders finish)

1. Run `python tools/ci.py all`.
2. For each failure, find the owner by file, fix it against this spec, and record the fix in that builder's notes file.
3. If a spec ambiguity caused the failure, write the resolution back into this spec as a numbered erratum at the end.
4. Run the section 11.9 checklist on at least 2 real hosts before tagging v2.0.0.

---

## 13. User journey (exact commands)

### 13.1 Install

**Local clone, works today with no release:**
```
Windows PowerShell:  py -3 <kit>/install/install.py
                     py -3 <kit>/install/install.py install --with-clis claude,codex,kimi --login
Git Bash / macOS / Linux:
                     python3 ~/path/to/kit/install/install.py
                     python3 ~/path/to/kit/install/install.py install --with-clis claude,codex,kimi --login
```

**After a GitHub release:**
```
macOS / Linux / WSL / Git Bash:
  curl -fsSL https://github.com/OWNER/ultimate-brainstorm/releases/download/v2.0.0/install.sh | sh -s -- install
Windows PowerShell 5.1+:
  & ([scriptblock]::Create((irm https://github.com/OWNER/ultimate-brainstorm/releases/download/v2.0.0/install.ps1))) install
Inspect first:
  curl -fsSL <url>/install.sh | less      irm <url>/install.ps1 | more
No pipe (PowerShell 5.1 has no &&):
  git clone --depth 1 --branch v2.0.0 https://github.com/OWNER/ultimate-brainstorm
  py -3 ultimate-brainstorm/install/install.py install
```

**Model families.** Pick any; with 2 or more families, judging is cross-family:
```
GPT (Codex CLI):       npm install -g @openai/codex        then  codex login
Claude (Claude Code):  npm install -g @anthropic-ai/claude-code   then run `claude` once and sign in
Kimi (Kimi Code CLI):  npm install -g @moonshot-ai/kimi-code  (Windows: install Git for Windows first)  then  kimi login
GLM (Z.ai):            set ZAI_API_KEY (Coding Plan key), then:
                       py -3 <kit>/install/install.py setup-glm --launcher --codex   [--region cn]
Kimi via Claude Code or Codex (optional): set KIMI_API_KEY (Platform) or KIMI_CODE_API_KEY (membership), then
                       py -3 <kit>/install/install.py setup-kimi --launcher --codex [--provider kimi-code]
Check:                 py -3 <kit>/install/install.py doctor --live
```

### 13.2 Run

| Host | Launch | Command |
|---|---|---|
| Claude Code | `claude` in the project folder | `/ultimate-brainstorm AI tutor for night-shift nurses` |
| Codex | `codex` in the project folder; approve "always" for the ub command prefix when asked (nested model CLIs need network) | `$ultimate-brainstorm AI tutor for night-shift nurses` |
| Kimi Code | `kimi` in the project folder (Windows: Git Bash present); approve the Bash prefix once | `/skill:ultimate-brainstorm AI tutor for night-shift nurses` |
| ZCode | open the project | `$ultimate-brainstorm AI tutor for night-shift nurses` |
| Claude Code on GLM | `~/.ultimate-brainstorm/bin/claude-glm` (PowerShell: `& "$HOME\.ultimate-brainstorm\bin\claude-glm.ps1"`) | `/ultimate-brainstorm ...` |
| Codex on GLM | `~/.ultimate-brainstorm/bin/codex-glm` (or `CODEX_HOME=~/.ultimate-brainstorm/codex-homes/glm codex`; PowerShell: `$env:CODEX_HOME="$HOME\.ultimate-brainstorm\codex-homes\glm"; codex`) | `$ultimate-brainstorm ...` |
| Claude Code or Codex on Kimi | `claude-kimi` / `codex-kimi` | as above |
| Terminal only | `~/.ultimate-brainstorm/bin/ub run "AI tutor for night-shift nurses"` (PowerShell: `& "$HOME\.ultimate-brainstorm\bin\ub.ps1" run "..."`) | answers at the prompts |

**Variants of the command:**
- `quick <topic>`, `deep <topic>`
- `proposal <my idea in one sentence>`
- `software <feature>` (inside the repo)
- `full-auto <topic>`, `hands-on <topic>`
- `private <topic>`
- `continue`, `status`, `stop`
- `probe passed <note>`
- `switch architecture B`
- `doctor`

### 13.3 What the user sees (standard, guided)

1. **G0 (one screen).** The plan: mode, variant, families, about 85 calls and about 1-2M tokens (estimates), vendors,
   privacy. "Type your own ideas now, one per line (optional `Primary: <idea to test>`), or reply `go`."
2. **Frame.** grilling asks one round of questions with recommended answers for constraints only. The user answers,
   then confirms.
3. About 1.5-2.5 h unattended: grounding, 5 isolated strategies across families, map, screen, checks, cards. The user
   can leave and later type `continue`.
4. **G8a.** "7 finalists, unscored. Your gut top 3?" Judges run sealed in the meantime.
5. **G8b.** The gut pick, debiased standings, contested pairs, raw red-team verdict lines, the synthesis, and "Suggested
   by rule; you decide". The user answers with an ID and why.
6. About 30-50 min. **G11**: the architecture options matrix (A/B/C with ranges and vetoes), the pre-mortem's top risk,
   the suggestion. The user replies `ok`, a letter, or `B+steal`.
7. About 30-60 min. **G13**: "Proposal ready" (rubric scores, red-team, lint, open questions, ADRs Proposed). The user
   replies `approve`, `changes: ...`, `switch B` or `runner-up`.
8. **G14 and DONE.** Publish to docs/? Handoff seed (ce-plan or Spec Kit)? Then links to `PROPOSAL.md`, `index.html`
   and `10_ARCHITECTURE/README.md`.

---

## 14. Platform matrix

**Status key:**

| Mark | Meaning |
|---|---|
| OK | Documented, and every feature this kit uses is [V] |
| OK* | Works through a documented path, with [U] parts that have fallbacks |
| MANUAL | The user performs one UI step |
| - | Not supported |

**By host:**

| Host / surface | Windows | macOS | Linux / WSL | Kit install route | Invocation | Host family | Nested families | HOST tasks (grilling, ce-ideate) | Notes |
|---|---|---|---|---|---|---|---|---|---|
| Claude Code CLI | OK* (Git Bash or PowerShell tool) | OK | OK | native plugin (user) via installer; copy fallback | `/ultimate-brainstorm` | claude (or glm/kimi via launcher) | codex exec, kimi -p, claude -p (nested [U-14]) | OK (main conversation) | Bash max 10 min; HOST_BATCH via general-purpose sub-agents |
| Claude Code desktop / IDE | OK* | OK* | OK* | same plugin | same | same | same | OK | [L]; same config dir |
| Codex CLI | OK* (PowerShell; unified exec off by default on Windows [V]) | OK | OK | native plugin (0.156+) or copy to `~/.agents/skills` | `$ultimate-brainstorm` [U-4 form] | gpt (or glm/kimi via CODEX_HOME) | needs escalation approval | OK* (ce-ideate native; grilling via ~/.agents/skills) | shell timeout [U-9] -> short waits + detached workers |
| Codex app | OK* | OK* | - | same | same | same | same | OK* | [L] |
| Codex IDE extension | OK* | OK* | OK* | skills copy only (no plugins [V]) | `$ultimate-brainstorm` | gpt | limited | ce-ideate unavailable | [U-31] |
| Kimi Code CLI v2 | OK* (needs Git for Windows) | OK | OK | copy to `~/.kimi-code/skills` (installer) or MANUAL `/plugins install` | `/skill:ultimate-brainstorm` | kimi | codex exec, claude -p (never GLM plan keys) | OK* (grilling via ~/.agents/skills; CE via MANUAL plugin) | Bash max 5 min, auto-backgrounds; AskUserQuestion available |
| ZCode desktop | OK* | OK* | OK* | copy to `~/.zcode/skills` (installer); plugin UI MANUAL [U-21] | `$ultimate-brainstorm` | glm | claude -p/codex exec if installed; GLM via claude-cli@glm (key) or HOST_BATCH | OK* | sub-agent and shell behavior [U-21] |
| Claude Code on GLM (`claude-glm`) | OK* | OK* | OK* | same as Claude Code | `/ultimate-brainstorm` | glm | as Claude Code | OK | WebSearch off behind Z.ai [L]; research seats go to other families or opt-in Z.ai MCP [U-19] |
| Codex on GLM (`codex-glm`) | OK* | OK* | OK* | plugin installed into that CODEX_HOME | `$ultimate-brainstorm` | glm | as Codex | OK* | env_key auth; metadata warning expected |
| Claude Code on Kimi (`claude-kimi`) | OK* | OK* | OK* | same as Claude Code | `/ultimate-brainstorm` | kimi | as Claude Code | OK | Moonshot-documented env |
| Codex on Kimi (`codex-kimi`) | OK* | OK* | OK* | plugin into that CODEX_HOME | `$ultimate-brainstorm` | kimi | as Codex | OK* | |
| Terminal (`ub run`) | OK | OK | OK | installer (`UB_HOME/bin/ub`) | `ub run "<topic>"` | none (families only) | all headless backends | engine alternatives only | the most robust for long unattended runs |

**Families by backend:**

| Family | Backend | Needs | Web | Status |
|---|---|---|---|---|
| claude | claude-cli | Claude Code login (or ANTHROPIC_API_KEY) | yes | OK |
| gpt | codex-cli | `codex login` | yes (`-c web_search=live` [L]) | OK |
| kimi | kimi-cli | Kimi Code CLI v2 + `kimi login` | off by default [U-3] | OK* (stream-json parse [U-2]) |
| kimi | claude-cli@kimi / @kimi-code | KIMI_API_KEY / KIMI_CODE_API_KEY | no | OK (vendor-documented env) |
| kimi | codex-cli@kimi | KIMI_API_KEY + codex home | no | OK* |
| glm | claude-cli@glm | ZAI_API_KEY (Coding Plan OK: Claude Code is a supported tool) | no | OK* (scripted-use reading [U-20]) |
| glm | codex-cli@glm | ZAI_API_KEY + codex home | no | OK* |
| glm | openai-http@glm-payg | ZAI_PAYG_API_KEY, enabled by user | no | OK* (path [U-23]) |
| any | host (HOST_BATCH) | a host with sub-agents | host's | OK* |

---

## 15. Unverified items: never hard-code without the fallback

| # | Item | Where it is used | Required fallback or default | How it gets verified |
|---|---|---|---|---|
| U-1 | `kimi -p` reading the prompt from stdin | adapter | Not used. The prompt goes in the agent-file body | none needed |
| U-2 | Exact Kimi stream-json field names | kimi parser | Tolerant parser (5.2); raw samples saved; unparseable -> `bad_output` -> next backend in the chain | live fixture (11.9) |
| U-3 | WebSearch/FetchURL availability in `kimi -p` (host-injected search, login type) | seats | `kimi-cli.web: false` by default; web seats go to claude/gpt | live probe; user opt-in |
| U-4 | Codex plugin skill invocation form (`$ultimate-brainstorm` vs namespaced) | docs, SKILL.md | Document both; doctor prints what `codex plugin list --json` shows | live |
| U-5 | `codex exec -c web_search=live` honored in exec | codex web jobs | If the live probe shows no search (output says it cannot browse), mark gpt web=false and re-seat | live |
| U-6 | `model_providers` inside a Codex `--profile` file | Codex on GLM/Kimi | Not used: CODEX_HOME isolation | none needed |
| U-7 | Codex `--output-schema` against GLM/Kimi Responses endpoints | codex provider backends | `native_schema: false` for them; schema in prompt + local validation + repair | live |
| U-8 | Nested codex/claude/kimi processes inside the Codex sandbox | Codex host | Instruct escalation for the ub prefix; `error_class sandbox_network` -> BLOCKED card with the fix | live |
| U-9 | Codex host shell command timeout / unified exec on Windows | SKILL.md waits | W=100, detached workers, safe re-run; repeated relaunch -> terminal route | live |
| U-10 | Whether `codex plugin add` upgrades an installed plugin | installer update | remove + add | live |
| U-11 | Codex user skills dir (`~/.agents/skills` vs deprecated `~/.codex/skills`) | installer | Install to `~/.agents/skills` only; doctor flags duplicates | live |
| U-12 | Claude `--json-schema` together with `--tools ""`, and through `.cmd` shims | claude backend | `native_schema: false` default | live |
| U-13 | Empty `--tools ""` argv element through npm `.cmd` shims | claude backend | Fake-shim test; switch to `--tools=` for `.cmd` exes if the element is dropped | CI (fake shim) + live |
| U-14 | Nested `claude -p` inside a live Claude Code session | claude family from a Claude Code host | Env scrub of `CLAUDECODE`/`CLAUDE_CODE_CHILD_SESSION`; preflight PING; on failure the family's chain becomes `host` (HOST_BATCH) | live preflight |
| U-15 | Claude cross-marketplace plugin dependencies (bundle) | bundles/stack | Experimental; the installer never uses it | live |
| U-16 | `claude plugin marketplace update` / plugin update semantics | installer update | Local marketplace loads in place; failure ignored; uninstall + install as last resort | live |
| U-17 | `claude plugin validate` in CI without login | CI optional job | `continue-on-error: true` | CI |
| U-18 | `claude plugin list --json` and `marketplace list --json` shapes; the CE Claude marketplace name | installer idempotency, CE install | Tolerant parsing; unknown -> attempt + treat "already installed" errors as unchanged; CE -> `manual` row with the guide's commands | live |
| U-19 | WebSearch behind Z.ai/Moonshot endpoints; the Z.ai MCP via `--mcp-config` and allowedTools names | glm/kimi web | Web seats never on claude-cli@glm/@kimi; Z.ai MCP opt-in for the host launcher only | live |
| U-20 | Z.ai Coding Plan: script-launched Claude Code/Codex counted as "supported tool" use | glm backends | Kickoff policy note; `families.glm.allow_scripted_plan_use` (default true) -> false = GLM only as host via HOST_BATCH | vendor confirmation |
| U-21 | ZCode: marketplace file path, honoring `disable-model-invocation` (unused), sub-agent/shell tools, timeouts, plugin UI for CE | ZCode route | Copy route; generic HOST_BATCH text; MANUAL rows; never the zcode CLI | live |
| U-22 | China Anthropic endpoint for Moonshot (`api.moonshot.cn/anthropic`, third-party source only) | kimi provider | Not included; `cn` region only for `kimi-code` (vendor-documented `api.kimi.com/coding/`) | vendor docs |
| U-23 | `/chat/completions` paths on Moonshot and Z.ai HTTP bases | HTTP backends | `enabled: false` by default; the user enables after a live selftest | live selftest |
| U-24 | Detached workers surviving host cleanup (Windows job objects, Codex sandbox, IDE terminals) | batch | Breakaway attempt; relaunch; after 3 relaunches BLOCKED -> terminal route | live |
| U-25 | mermaid-cli invocation | lint | Lint-only (heuristic); no mmdc calls in v2.0 | - |
| U-26 | Mermaid CDN major version | render | One constant `MERMAID_CDN`; offline shows the source | live |
| U-27 | Pinning `npx skills` sources to an upstream commit | components | Pin the CLI version (`skills@1.7.0`) only; doctor records the installed skill hashes | - |
| U-28 | Codex `model_catalog_json` format for GLM | codex home | Omitted; the metadata warning is accepted | live |
| U-29 | Kimi project root without `.git` (project scope installs) | installer project scope | Warn; offer `--git-init` | live |
| U-30 | Claude Code copying settings `env` into Bash-tool child processes (for host-family detection under launchers) | detect | `UB_HOST_FAMILY` set by the launchers (process env, inherited) is the primary signal | live |
| U-31 | Codex IDE extension: skill loading from `~/.agents/skills`, shell tool and sub-agents | Codex IDE surface | Documented as "unsupported until tested"; the CLI and app are the supported Codex surfaces | live |
| U-32 | Native structured output keywords beyond type/properties/required/additionalProperties/items/enum (e.g. minItems) | codex `--output-schema` | Schema files use only those keywords; counts and ranges are checked in Python (7.4) | live |

Builders tag the code for each item as `# [U-<n>]`, so a grep lists every assumption still waiting on live
verification.

---

## 16. Milestones

| Milestone | Scope | Exit |
|---|---|---|
| M0 (day 0) | B1 skeleton + `git init`; B2 textio / schema_lite / validate / filesproto + tests | imports available to B3/B4 |
| M1 | B2 adapter + bs.py; B3 engine stages 0-11 + templates; B4 fakes, stubs, static tests; B1 installer plan/install/doctor | each builder's unit suite green |
| M2 | B3 stages 12-14 + render; B4 e2e + installer integration; B1 launchers, shims, release, docs | `tools/ci.py all` green locally (Windows) |
| M3 (integration) | 12.5 | CI green on 3 OSes; errata recorded |
| M4 (live) | 11.9 on at least 2 hosts; resolve section 15 items; tag v2.0.0 | release assets published |
