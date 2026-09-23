# Installer fixtures (B4)

- `plans/*.json`: golden plan expectations for `install.py plan --json` (KIT_SPEC 11.4). Each case names the fake
  tools on PATH, fake `--version` strings, extra environment, the expected exit code, agents (subset match), rows that
  must be present (subset match; `commands` compared exactly), rows that must be absent, and warning regexes.
  Placeholders: `{root}`, `{home}`, `{ub_home}`, `{kit_dir}`, `{claude_home}`, `{codex_home}`, `{kimi_home}`,
  `{project}` (see tests/harness/inst.py). Paths compare with forward slashes, case-insensitively on Windows.
- `v1/SKILL.md.fixture`: a v1 skill (metadata.version "1.0", no marker). Tests copy it as `SKILL.md` into a temporary
  agent folder; the repo keeps exactly one real SKILL.md.
- `skill-v2/SKILL.md.fixture`: a v2-looking skill used to create duplicate installs for the doctor tests.
- `claude-settings-zai.json`: a `~/.claude/settings.json` that points Claude Code at Z.ai (doctor reclassification).
