# Changelog 2.0.0

All notable changes to ultimate-brainstorm are listed here, newest first.

## 2.0.0 - 2026-09-23

First public release of the kit (v2). It replaces the single v1 skill with an installable package that runs in
Claude Code, Codex, Kimi Code and ZCode.

### Added

- One-line installers for macOS, Linux, WSL, Git Bash (`install.sh`) and Windows PowerShell 5.1 or newer
  (`install.ps1`). Each downloads one release archive, checks its SHA-256 and then runs the Python installer.
- `install/install.py` with `plan`, `install`, `update`, `uninstall` and `doctor`. It shows a plan first, changes
  nothing until you agree, records what it wrote in an install manifest and can undo it exactly.
- Plugin manifests for Claude Code and Codex, plus a universal skills layout (`.agents/skills`) for other hosts.
- A full pipeline, from sealed human seeds to handoff: frame, research, five isolated idea strategies, map, screen,
  prior-art checks, a tournament judged in both orders by several model families, red team, your decision, probe,
  competing architectures judged blind, and a cited proposal with a one-pager and an HTML pack.
- Model family routing for Claude, GPT (Codex), Kimi and GLM (Z.ai), with launchers and per-family overrides
  (`docs/FAMILIES.md`).
- Standard (guided) and full-auto modes. Every run is kept in files under `brainstorm/<date>-<topic>/`, so you can stop
  and continue at any time.
- Privacy controls at the first question: turn off web search, other vendors or both, or type `private`. API keys are
  read from environment variables only. There is no telemetry.
- `doctor` checks for every host, and `docs/TROUBLESHOOTING.md` lists every message the pipeline can stop with.
- Reproducible release builds (`tools/release.py`) with `SHA256SUMS`, and CI that runs every test suite first.

### Changed

- The v1 `bs.py` engine is kept, and its old test harnesses have been ported into the kit's own test suite.
- `docs/GUIDE.md` has been updated for v2: the stack, the pipeline and install steps for each host.
