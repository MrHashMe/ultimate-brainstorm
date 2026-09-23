# Contributor rules for ultimate-brainstorm

These rules are for people and coding agents who change this repository. The binding build spec is
[`docs/design/KIT_SPEC.md`](docs/design/KIT_SPEC.md); where this file and the spec disagree, the spec wins.

## Layout

```
.claude-plugin/ .codex-plugin/ .agents/plugins/ .kimi-plugin/   plugin and marketplace manifests (one repo = plugin root
                                                                = marketplace root for Claude Code, Codex and Kimi)
bundles/stack/                 experimental Claude bundle (the installer never uses it)
skills/ultimate-brainstorm/    the only skill: SKILL.md, agents/openai.yaml, references/, templates/, scripts/
  scripts/ub.py                engine CLI (pipeline state machine, one card per call)
  scripts/family.py            model-family adapter and worker entry point
  scripts/bs.py                bookkeeping (map, screen, tournament, arch-matrix, lints)
  scripts/ublib/               shared library (textio, schema_lite, validate, filesproto, proc, redact, ...)
install/                       install.py, targets.json, components.json, bootstrap shims
profiles/                      launch.py and the launcher / Codex-home / Z.ai MCP templates
docs/                          user docs (GUIDE, INSTALL, HOSTS, FAMILIES, PRIVACY, TROUBLESHOOTING, ACCEPTANCE)
docs/design/KIT_SPEC.md        the binding build spec
research/                      the research behind the method: prompt, tool landscape report, candidate CSV
tests/                         unit, integration, e2e, static (no __init__.py anywhere under tests/)
tools/                         ci.py, validate_kit.py, release.py
```

Hard rules for the tree:
- Exactly one file named `SKILL.md` exists: `skills/ultimate-brainstorm/SKILL.md`. Fixtures use `SKILL.md.fixture`.
- No root `plugin.json`, `agents/`, `bin/`, `hooks/`, `.mcp.json` or `commands/`. Each of them changes how Claude Code,
  Codex or Kimi load the plugin.
- Manifest paths use forward slashes and start with `./`.
- `VERSION` holds the version. The same string appears in every manifest, the SKILL.md `metadata.version`, the
  `--version` output of `ub.py`, `family.py`, `bs.py`, `install.py version`, and the top heading of `CHANGELOG.md`.

## Code

- Python 3.9 or newer, standard library only, at runtime and in tests (`unittest`). Optional imports stay behind `try`.
  No `match` statements and no runtime `X | Y` type unions.
- Never `shell=True`. Resolve executables with `shutil.which` and pass the full path. For `.cmd` / `.bat` targets,
  refuse arguments containing `" & | < > ^ % !`, CR or LF.
- Text files: UTF-8 without BOM, LF endings. `.cmd`, `.bat`, `.ps1` (and their `.tpl` sources) use CRLF; see
  `.gitattributes`. Reads are tolerant of BOMs and UTF-16.
- Templates under `skills/ultimate-brainstorm/templates/` are ASCII only and never contain `${`. The profile templates
  under `profiles/` are ASCII only.
- Paths are absolute internally and written with forward slashes in JSON, cards and docs.
- `--json` output is exactly one JSON object with `ensure_ascii=True`. Timestamps are UTC ISO-8601 with `Z`.
- Secrets come only from environment variables. They go only into per-call temporary files with owner-only permissions
  that are deleted in `finally`. Never put a secret in argv, logs, meta files, cards or docs.
- No telemetry. Only model backends, the installer's downloads and component commands, and `--live` checks touch the
  network.
- Behavior that no vendor document confirms is tagged `# [U-n]` (see the spec's section 15) and sits behind detection
  or a config key with a safe default. `grep -rn "\[U-" .` lists every open assumption.
- No new dependencies, hooks, MCP servers or symlinks.

## Running the tests

```
python tools/ci.py all            # every suite, each in its own process
python tools/ci.py unit           # or: integration, e2e, static
python -m unittest discover -s tests/unit -t tests/unit -p "test_*.py"
python tools/validate_kit.py      # static checks only
```

Tests never call a real model CLI or the network. They use the fake CLIs in `tests/harness/`, the stubs in
`skills/ultimate-brainstorm/scripts/ublib/stubs.py`, and temporary directories for `HOME`, `UB_HOME` and every agent
home. Real calls happen only in the manual checklist `docs/ACCEPTANCE.md` (with `UB_LIVE=1`).

## Releasing

`python tools/release.py --version 2.0.2 --out dist/` builds the archives, `SHA256SUMS` and the rendered bootstrap
shims for the GitHub repository `MrHashMe/ultimate-brainstorm`. A fork passes `--owner <github-user>`; the owner name is
then replaced only in the archive copy, never in the repository. Pushing a `vX.Y.Z` tag runs the same build in
`.github/workflows/release.yml` and publishes the GitHub release.
