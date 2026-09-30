# Live acceptance checklist

This is the manual check before a release is tagged. It runs on real machines with real logins and keys, so it makes
real model calls and counts against your plans. The automated suites (`python tools/ci.py all`) never do this: they
use fake CLIs and stub outputs.

Run it on at least 2 hosts before tagging a release. Record every result in the tables below and commit the filled
copy with the release. tools/release.py refuses to build a release while this record has a check without a live
result (see AGENTS.md, Releasing); an `Acceptance override: <reason>` line in the version's CHANGELOG section releases
anyway and lists the unverified checks in the release notes. Releases 2.0.0 to 2.0.3 were tagged without a live record. Every Result cell below says "not
yet verified live" until someone runs the check and writes down what they saw.

## Procedure

1. Install the kit from the release candidate: `python install/install.py install --yes` (or the bootstrap shim).
2. Sign in to each CLI you test (`claude`, `codex login`, `kimi login`) and export the keys you use
   (`ZAI_API_KEY`, `KIMI_CODE_API_KEY`, ...).
3. Set `UB_LIVE=1` in the shell you use for these checks (bash: `export UB_LIVE=1`; PowerShell:
   `$env:UB_LIVE = "1"`). It marks the shell as a live session; the automated suites never set it and never make a
   real call.
4. Note the versions: `claude --version`, `codex --version`, `kimi --version`, `python --version`, the OS.
5. Run the per-host checks, the platform checks, then every row of "Unverified items" you can reach from that host.
   For a row, replace "not yet verified live" with "confirmed", "different: <what you saw>" or "not tested", and fill
   the host, version and date. A "different" result means the fallback in the spec's section 15 is what users get:
   open an issue.
6. Keep the evidence (card JSON, `logs/calls.jsonl` lines, CLI output) with the release notes, with keys removed.

## Per host

Hosts: Claude Code, Codex, Kimi Code, Claude Code on GLM (`claude-glm`), Codex on GLM (`codex-glm`), ZCode.

| # | Check | How | Pass when |
|---|---|---|---|
| 1 | Doctor | `python install/install.py doctor --live` | PONG from every family you have |
| 2 | Quick run | In the host: `/ultimate-brainstorm quick <topic>` (Codex: `$ultimate-brainstorm quick <topic>`) | DONE card; `11_PROPOSAL/PROPOSAL.md` exists |
| 3 | Standard run | Same, `standard` (on at least 2 hosts) | DONE; `10_ARCHITECTURE/lint.md` has no FAIL |
| 4 | Cross-host continue | Start on one host, stop at G8a, then `continue` from a second host | The run finishes; re-seats show as PROVISIONAL |
| 5 | Cost against the plan | After run 3: compare the plan (`ub plan "<run>" --json`, its `calls` and `requests`) with what the run used (`ub status "<run>" --json`: `budget.used` = backend requests sent, the sum of `requests` in `logs/calls.jsonl`; `budget.launches` = job launches) | The requests sent lie inside the plan's `requests` range; write down requests per launch |

| Host | Versions | 1 Doctor | 2 Quick | 3 Standard | 4 Continue | 5 Requests / plan | Notes |
|---|---|---|---|---|---|---|---|
| Claude Code | | | | | | | |
| Codex | | | | | | | |
| Kimi Code | | | | | | | |
| Claude Code on GLM | | | | | | | |
| Codex on GLM | | | | | | | |
| ZCode | | | | | | | |

## Platform checks

| Check | How | Pass when | Result | Host and version | Date |
|---|---|---|---|---|---|
| Windows PowerShell 5.1 kickoff | In PowerShell 5.1 (Codex on Windows), with no optional skill installed, run the SKILL.md Start line with an empty component list: `& py -3 "<KIT>/scripts/ub.py" init --host codex --text-file brainstorm/.kickoff.txt --components="" --json` | The G0 card appears (before 2.1.0: `usage error: argument --components: expected one argument`, exit 2) | not yet verified live | | |

## Unverified items

One row per `[U-n]` tag in the code (`grep -rn "\[U-" .` lists every place), plus the section-15 items of the build
spec that live only in configuration or documentation (marked "no code tag"). Each row names the live check that
settles it. The fallback the kit uses until then is in the spec's section 15.

| Item | Where | Live check to run | Result | Host and version | Date |
|---|---|---|---|---|---|
| U-1 `kimi -p` reading the prompt from stdin (unused) | `ublib/backends/kimi_cli.py` | none needed: `family.py explain --family kimi` shows no prompt text in argv (the prompt is the agent-file body) | not yet verified live | | |
| U-2 Kimi stream-json field names | `ublib/backends/kimi_cli.py` | run a PING through `family.py call --family kimi`; compare `<run>/logs/kimi-samples/sample-1.jsonl` of a live run with the parser's fields; capture the live fixture (below) | not yet verified live | | |
| U-3 web search inside `kimi -p` (no code tag: `kimi-cli` `web: false` in families.default.json) | `families.default.json`, seats | in a scratch UB_HOME set `{"backends": {"kimi-cli": {"web": true}}}`, run `family.py call --family kimi --tools web` with "search the web and give one URL" | not yet verified live | | |
| U-4 Codex plugin skill invocation form | `install/install.py` (doctor) | after a native install, `install.py doctor`; in Codex type `$ultimate-brainstorm` and record the name `/skills` lists | not yet verified live | | |
| U-5 `codex exec -c web_search=live` honored | `ublib/backends/codex_cli.py`, `ublib/detect.py`, `ub.py` (preflight web probe) | `ub init` with gpt available: `<run>/logs/ping/gpt.web.txt` holds a real URL and no web-probe note appears | not yet verified live | | |
| U-6 `model_providers` in a Codex `--profile` file (unused) | `profiles/launch.py` | none needed: `codex-glm` starts with its own `CODEX_HOME` and answers | not yet verified live | | |
| U-7 Codex `--output-schema` on GLM and Kimi Responses endpoints | `ublib/backends/codex_cli.py` (`native_schema: false` for them) | with `native_schema: true` for `codex-cli@glm` in a scratch families.json, run a judge-schema job through `family.py call --family glm --schema <file>`; record accepted or rejected | not yet verified live | | |
| U-8 nested model CLIs inside the Codex sandbox | `ublib/detect.py`, `ublib/backends/__init__.py`, `ublib/engine/pipeline.py` | Codex host: start a run without approving the `ub` prefix (expect the BLOCKED sandbox card with its fix), then approve "always" (expect the run to go on) | not yet verified live | | |
| U-9 Codex host command timeout on Windows (no code tag: SKILL.md W=100) | SKILL.md Hosts table | Codex on Windows: `UB next "<run>" --wait-s 100 --json` returns a card without being killed | not yet verified live | | |
| U-10 `codex plugin add` upgrades an installed plugin | `install/install.py` | native install of the previous release, then `install.py update`: `codex plugin list --json` shows the new version | not yet verified live | | |
| U-11 Codex user skills folder `~/.agents/skills` | `install/install.py` | copy-route install (`--no-native`): Codex lists the skill exactly once | not yet verified live | | |
| U-12 claude `--json-schema` with `--tools ""` and through `.cmd` shims | `ublib/backends/claude_cli.py` | with `native_schema: true` in a scratch families.json, a judge-schema job through `family.py call --family claude --schema <file>` in bash and through the Windows npm shim | not yet verified live | | |
| U-13 an empty `--tools ""` argument through npm `.cmd` shims | `ublib/backends/claude_cli.py`, `ublib/proc.py` | Windows: `family.py explain --family claude` shows `--tools=`; a PING through the npm shim answers PONG with no tools | not yet verified live | | |
| U-14 nested `claude -p` inside a live Claude Code session | `ub.py` (preflight), `ublib/detect.py` | Claude Code host: the kickoff preflight gets PONG from claude; if it fails, claude jobs arrive as HOST_BATCH cards | not yet verified live | | |
| U-16 `claude plugin marketplace update` semantics | `install/install.py` | `install.py update` on a native install: record the row detail; after a restart `/ultimate-brainstorm` runs the new version | not yet verified live | | |
| U-17 `claude plugin validate` without a login | `.github/workflows/ci.yml` (optional job) | the optional CI job's result on the release commit | not yet verified live | | |
| U-18 `plugin list --json` / `marketplace list --json` shapes; the CE marketplace name | `install/install.py` | save the output of `claude plugin list --json`, `claude plugin marketplace list --json` and the codex twins; a second `install.py install` shows every row unchanged | not yet verified live | | |
| U-19 web search behind Z.ai / Moonshot; the Z.ai MCP through `--mcp-config` | `profiles/launch.py`, `install/install.py` | in a `claude-glm` session ask for a web search; with `setup-glm --zai-mcp`, the Z.ai tools are listed | not yet verified live | | |
| U-20 Z.ai Coding Plan: script-launched Claude Code / Codex counts as supported-tool use | `ublib/adapter.py`, `ublib/detect.py`, `ublib/families.py` | vendor confirmation (Z.ai documentation or support); record the answer and its date | not yet verified live | | |
| U-21 ZCode marketplace, sub-agent and shell tools, timeouts | `install/install.py` | ZCode: the copied skill runs a quick run; HOST_BATCH jobs run in its sub-agent tool; W=50 is not killed | not yet verified live | | |
| U-22 China Anthropic endpoint for Moonshot | `profiles/launch.py`, `ublib/families.py` | Moonshot documentation check; `setup-kimi --region cn` is offered for `kimi-code` only | not yet verified live | | |
| U-23 `/chat/completions` on Moonshot and Z.ai HTTP bases (no code tag: `enabled: false` in families.default.json) | HTTP backends | enable `openai-http@glm-payg` (or `openai-http@kimi`) in a scratch families.json, then `family.py selftest --family glm --live` | not yet verified live | | |
| U-24 detached workers surviving host cleanup | `ublib/batch.py` | in each host a standard run's workers outlive the host's command timeouts (no "stops background work" BLOCKED card) | not yet verified live | | |
| U-26 Mermaid pinned build (11.17.2, SRI) on jsDelivr | `ublib/engine/render.py` | open `11_PROPOSAL/index.html` online: the diagrams draw and the browser console shows no integrity error | not yet verified live | | |
| U-27 component skills from the pinned commit archive (codeload) | `install/install.py` | a fresh `install.py install` installs grilling and domain-modeling with the row detail `commit c55ee46073ed verified`; `doctor` shows no `stack.*.drift`; after editing an installed file, the drift WARN appears | not yet verified live | | |
| U-28 Codex `model_catalog_json` for GLM (omitted) | `profiles/launch.py` | `codex-glm` prints the metadata warning and answers | not yet verified live | | |
| U-29 Kimi project root without `.git` | `install/install.py` | project-scope install into a folder without `.git`: the plan warns and offers `--git-init`; after it Kimi finds the skill | not yet verified live | | |
| U-30 settings `env` in Claude Code Bash children (no code tag: the launchers set `UB_HOST_FAMILY`) | launchers, detection | in a `claude-glm` session the Bash tool prints `glm` for `echo $UB_HOST_FAMILY`, and the kickoff card names glm as the host family | not yet verified live | | |
| U-31 Codex IDE extension (no code tag) | Codex IDE surface | install with `--agents codex --no-native`; in the extension `$ultimate-brainstorm quick <topic>` reaches the G0 card | not yet verified live | | |
| U-32 structured-output keywords beyond the verified subset | `ublib/schema_lite.py`, codex `--output-schema` | a codex job with a schema that uses `minItems`: record accepted or rejected | not yet verified live | | |
| U-33 Z.ai Responses endpoint (`api.z.ai/api/v1`) for Coding Plan keys in the Codex home | `profiles/launch.py`, `install/install.py` | after `setup-glm --codex`, `install.py doctor --live` gets PONG from Codex on GLM | not yet verified live | | |
| U-34 Kimi Code `config.toml` layout (the base_url of the provider of `default_model`, or of the `-m` name) | `ublib/detect.py`, `ublib/backends/kimi_cli.py` | `family.py detect --json` on a machine with Kimi Code set up names the right endpoint for kimi; with `backends.kimi-cli.model` set to another model of that config.toml, `family.py detect --live --families kimi` gets PONG (the call passes `-m <name>`) | not yet verified live | | |
| U-40 codex `mcp_servers.<name>.enabled=false` (merged into config.toml; no empty-table override), `-c notify=[]` | `ublib/backends/codex_cli.py`, `ublib/detect.py` | with a user MCP server and a notify program in `~/.codex/config.toml`, a tools-none job shows no MCP startup and no `mcp_tool_call` item, and notify does not run | not yet verified live | | |
| U-41 codex `-c web_search=disabled` | `ublib/backends/codex_cli.py` | a tools-none job asked to search the web shows no `web_search` item | not yet verified live | | |
| U-42 codex `features.<key>=false`: shell_tool, js_repl, view_image (no read); apps, plugins, multi_agent, hooks, memories, browser_use, computer_use, image_generation, unbounded_connection_retries (every job) | `ublib/backends/codex_cli.py` | a tools-none job asked to run `echo probe` shows no `command_execution` item and still answers; `codex features list` with the same `-c` flags shows each feature false; with an unreachable provider endpoint, `codex exec` with the kit's argv exits with an error well before the attempt's timeout; with a ChatGPT login, a tools-none job asked to use a connector or a sub-agent shows no `mcp_tool_call` / `collab_tool_call` item | not yet verified live | | |
| U-43 claude `--setting-sources project` keeps the login and drops user hooks and memory | `ublib/backends/claude_cli.py`, `ublib/detect.py` | with a SessionStart hook, a user CLAUDE.md rule ("answer in French") and an `env` block (a proxy) or `apiKeyHelper` in `~/.claude/settings.json`, a PING worker answers PONG in English, reaches the API through the carried settings, and the hook does not run | not yet verified live | | |
| U-44 claude deny rules for the run folders (`Read(//<runs>/**)` ...) | `ublib/backends/claude_cli.py` | a repo-reading claude job asked to read a file under `brainstorm/<run>/` reports it cannot, and still reads the repository | not yet verified live | | |
| U-50 marketplace list source fields (claude, codex) | `install/install.py` | `claude plugin marketplace list --json` and the codex twin name `UB_HOME/kit` for the kit; `doctor` shows `agent.<a>.plugin_source` PASS | not yet verified live | | |
| U-51 marketplace clone HEAD equals the pinned commit | `install/install.py` | a Compound Engineering install: the row detail does not say "pinned commit ... not verified" | not yet verified live | | |
| U-52 `gh attestation verify` for release assets | `install/install.py`, `install/install.sh`, `install/install.ps1` | the release provenance check below (with `--signer-workflow` and `--source-ref`), signed in and signed out; with an old gh the note says to update it; with a second, broken gh account or host each of them still verifies (`gh auth status --active --hostname github.com`), and with `tuf-repo-cdn.sigstore.dev` blocked each gives the "could not build its Sigstore verifier" note | not yet verified live | | |
| U-60 Mermaid renders under the pack's Content-Security-Policy | `ublib/engine/render.py` | open `index.html` online: every diagram renders and the console shows no CSP report | not yet verified live | | |
| U-70 the OS frees a hard-killed driver's lock within about a second | `ublib/engine/state.py` (driver lock) | hard-kill a `ub run` driver (`kill -9`, `taskkill /F`), then run `ub next "<run>"` after 1 s: no "another session is driving this run" card | not yet verified live | | |
| U-75 Windows `LongPathsEnabled` = 1 lets Python open paths longer than 259 characters | `ublib/engine/state.py` | with long paths on, `ub doctor` reports `long_paths` PASS and a run under a deep `--root` writes files beyond 259 characters | not yet verified live | | |
| U-80 Windows Job Object around every backend CLI | `ublib/proc.py` | Windows: run each CLI through `family.py call`; `ub stop`, and a hard kill of the worker, leave no CLI process behind (Task Manager) | not yet verified live | | |
| U-85 codex `--output-schema` with `minimum` / `maximum` | `ublib/backends/codex_cli.py` | run a judge job with a 1-5 bounded schema passed unstripped; if the endpoint accepts it, the stripping can go | not yet verified live | | |
| U-95 agents' Grep/Glob and Codex search skip git-ignored run files | `ublib/engine/builders.py` | a repo-reading job's tool log never lists files under `brainstorm/` | not yet verified live | | |

Retired items (nothing to check): U-15 (Claude cross-marketplace plugin dependencies; the experimental bundle that used
them was removed in 2.1.0) and U-25 (mermaid-cli; never called).

## Release provenance

Run once on the first release built by the release workflow, and record the output:

```
gh release download vX.Y.Z --repo MrHashMe/ultimate-brainstorm --dir rel
cd rel && sha256sum -c SHA256SUMS
for f in *.tar.gz *.zip install.sh install.ps1 SHA256SUMS; do gh attestation verify "$f" --repo MrHashMe/ultimate-brainstorm --signer-workflow MrHashMe/ultimate-brainstorm/.github/workflows/release.yml --source-ref refs/tags/vX.Y.Z; done
gh api repos/MrHashMe/ultimate-brainstorm/immutable-releases     # {"enabled":true,...}
gh release verify vX.Y.Z --repo MrHashMe/ultimate-brainstorm
```

Also run that release's `install.sh` and `install.ps1` once with gh signed in (expect no note, exit 0 for `version`)
and once with gh off PATH (expect the "provenance not checked" note).

## Evaluation of the acceptance runs

Run `python tools/eval.py brainstorm/` over the release's acceptance runs and attach the Markdown report (yield per
strategy and family, Kendall's W of the judges, position consistency, self-preference) to the release notes.

`tools/eval.py` counts a screen judge as the family that answered its file (a fallback copy is not a second judge).
It re-aggregates the pipeline's own statistics; it cannot tell whether the judges are right or whether the pipeline
beats a simpler method. That needs human labels, which the kit does not fabricate, so it is a manual protocol:

1. Judge validity (once per release that changes judging). Take 3 finished acceptance runs of different variants. From
   each, take 30-40 pairs of cards: every finalist pair of the tournament plus pairs of screened-out ideas. Two people
   who did not see the rankings label each pair "A better", "B better" or "tie" against the run's criteria, alone and in
   a fixed random order (store the pair list and labels in a private folder, never in the repository). Compute, over
   the pairs both people labelled the same way, the share of pairs where the debiased ranking (06_TOURNAMENT.md) and the
   raw standings agree with the label, with a 90% bootstrap interval over pairs. Record both numbers; the debiased
   ranking should not be worse than raw.
2. Baseline arm (once per minor release). Pick 3 fixed topics. For each, run the pipeline (standard mode) and one strong
   single prompt ("list 10 ideas for <topic>, pick the best 3, explain") on the host model at a comparable call budget
   (repeat the single prompt until the call count matches). Blind the two top-3 lists (same card format, shuffled,
   source removed) and have 2 people rate each card 1-5 on the run's criteria. Report the mean per arm per topic and a
   Bradley-Terry fit over the 6 cards per topic; record it in the release notes. Do not claim "fairer" or "better"
   without this table.
3. Diversity: over the same runs, have one person sort all canonical ideas into clusters without seeing the curator's
   clusters; report the number of clusters per arm and the curator's cluster count next to it.

Confounding that stays: S1 and S2 always run on the host and, with 2 families, S3 and S5 always on the other family,
so their yield cannot be separated from the family's (`eval.py` lists such strategies as confounded).

## Live fixtures

Capture one sanitized sample of each native output format into `tests/fixtures/adapter/live/`:
- Kimi stream-json (`kimi-stream.jsonl`);
- Codex JSONL events (`codex-events.jsonl`);
- the Claude result JSON (`claude-result.json`).

Before you commit them, remove every key, token, account ID, e-mail address and local path.
