# Live acceptance checklist

This is the manual check before a release is tagged. It runs on real machines with real logins and keys, so it makes
real model calls and counts against your plans. The automated suites (`python tools/ci.py all`) never do this: they
use fake CLIs and stub outputs.

Run it on at least 2 hosts before tagging a release. Record every result in the tables below and commit the filled
copy with the release.

## Before you start

1. Install the kit from the release candidate: `python install/install.py install --yes` (or the bootstrap shim).
2. Sign in to each CLI you test (`claude`, `codex login`, `kimi login`) and export the keys you use
   (`ZAI_API_KEY`, `KIMI_CODE_API_KEY`, ...).
3. Set `UB_LIVE=1` in the shell you use for these checks.
4. Note the versions: `claude --version`, `codex --version`, `kimi --version`, `python --version`, the OS.

## Per host

Hosts: Claude Code, Codex, Kimi Code, Claude Code on GLM (`claude-glm`), Codex on GLM (`codex-glm`), ZCode.

| # | Check | How | Pass when |
|---|---|---|---|
| 1 | Doctor | `python install/install.py doctor --live` | PONG from every family you have |
| 2 | Quick run | In the host: `/ultimate-brainstorm quick <topic>` (Codex: `$ultimate-brainstorm quick <topic>`) | DONE card; `11_PROPOSAL/PROPOSAL.md` exists |
| 3 | Standard run | Same, `standard` (on at least 2 hosts) | DONE; `10_ARCHITECTURE/lint.md` has no FAIL |
| 4 | Cross-host continue | Start on one host, stop at G8a, then `continue` from a second host | The run finishes; re-seats show as PROVISIONAL |

| Host | Versions | 1 Doctor | 2 Quick | 3 Standard | 4 Continue | Notes |
|---|---|---|---|---|---|---|
| Claude Code | | | | | | |
| Codex | | | | | | |
| Kimi Code | | | | | | |
| Claude Code on GLM | | | | | | |
| Codex on GLM | | | | | | |
| ZCode | | | | | | |

## Unverified items

Record the observed behavior of every item from the build spec's section 15 (`grep -rn "\[U-" .` lists where each one
is used). Write "confirmed", "different: <what you saw>" or "not tested".

| Item | Result | Host and version | Date |
|---|---|---|---|
| U-1 kimi -p stdin (unused) | | | |
| U-2 Kimi stream-json field names | | | |
| U-3 web search in kimi -p | | | |
| U-4 Codex skill invocation form | | | |
| U-5 codex exec web_search=live | | | |
| U-6 model_providers in a Codex profile (unused) | | | |
| U-7 Codex --output-schema on GLM/Kimi endpoints | | | |
| U-8 nested CLIs in the Codex sandbox | | | |
| U-9 Codex host command timeout on Windows | | | |
| U-10 codex plugin add upgrades | | | |
| U-11 Codex user skills folder | | | |
| U-12 claude --json-schema with --tools "" | | | |
| U-13 empty --tools "" through .cmd shims | | | |
| U-14 nested claude -p in Claude Code | | | |
| U-15 Claude cross-marketplace dependencies | | | |
| U-16 claude plugin update semantics | | | |
| U-17 claude plugin validate without login | | | |
| U-18 claude plugin list --json shapes | | | |
| U-19 web search behind Z.ai / Moonshot | | | |
| U-20 Z.ai Coding Plan scripted use | | | |
| U-21 ZCode marketplace, tools, timeouts | | | |
| U-22 China Anthropic endpoint for Moonshot | | | |
| U-23 /chat/completions on Moonshot and Z.ai | | | |
| U-24 detached workers surviving host cleanup | | | |
| U-25 mermaid-cli (unused) | | | |
| U-26 Mermaid CDN major version | | | |
| U-27 npx skills source pinning | | | |
| U-28 Codex model_catalog_json for GLM | | | |
| U-29 Kimi project root without .git | | | |
| U-30 settings env in Claude Code Bash children | | | |
| U-31 Codex IDE extension | | | |
| U-32 structured-output keywords | | | |
| U-33 Z.ai Responses endpoint (`api.z.ai/api/v1`) for Coding Plan keys in the Codex home | | | |
| U-34 Kimi Code config.toml layout (default model provider base_url) | | | |

## Live fixtures

Capture one sanitized sample of each native output format into `tests/fixtures/adapter/live/`:
- Kimi stream-json (`kimi-stream.jsonl`);
- Codex JSONL events (`codex-events.jsonl`);
- the Claude result JSON (`claude-result.json`).

Before you commit them, remove every key, token, account ID, e-mail address and local path.
