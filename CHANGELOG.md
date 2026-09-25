# Changelog 2.0.2

All notable changes to ultimate-brainstorm are listed here, newest first.

## Unreleased

### Fixed

- A second run's G14 publish mixed into the first run's `docs/architecture`, `docs/adr` and `docs/proposal`:
  the kit treated files listed in another run's `.ub-published` marker as its own, so `docs/adr` ended up with two
  unrelated ADR sets both numbered 0001, same-named files (README.md, PROPOSAL.md, ...) were replaced and the
  marker was rewritten to claim both runs' files. A folder that holds another run's package (or files the kit did
  not publish) is now never written: the run publishes into `docs/<run>/<item>/` instead. This replaces the old
  fallback `docs/<item>/ub-<run>/`, which is still updated in place when a run republishes. The G14 card shows the
  real target for each copy and warns, naming the other run; `12_HANDOFF.md` records where each copy went and, on
  a new `Not published:` line, what was not copied and why. ADRs are not renumbered: each run keeps its own ADR
  log.
- Publishing is safer in general. Only a run's own earlier copy is updated in place. A file it replaces, or a
  file it no longer has (the old ADR set after `ub switch --arch`, say, also when the new architecture has no ADRs),
  goes to `_superseded/<stamp>/published/<item>/` first (it was `_superseded/<stamp>/published/docs/<item>/`); an
  unchanged file is left alone and not backed up, and a backup never overwrites an older one. The `.ub-published`
  marker (now `schema: 2`) is written before the first change, so an interrupted publish resumes in the same
  folder, and `12_HANDOFF.md` still lists what the interrupted attempt moved or replaced. Files are written through a
  temp file and a rename, so a hard link in `docs/` is replaced, not written through; a link or junction at `docs/`,
  `docs/<run>/` or inside a target means that item is not published. OS and editor files
  (`.DS_Store`, `Thumbs.db`, `desktop.ini`, `.gitkeep`, swap files) are never published and never make a folder
  look taken. Names read from disk (another run's name, a link's name) are escaped before they go on the card. An
  item with no files (zero ADRs) shows "nothing to publish", unless this run published it before: then its old copy
  moves to the backup. Listing an item twice publishes it once.
- Folders last written by 2.0.2 or earlier are not repaired automatically, because their marker cannot tell one
  run's files from another's. When a run publishes into such a folder again, every file the old marker lists that
  the package does not have stays in place (it may be another run's, or this run's own old ADR), the card warns, and
  the new marker keeps those files apart (`legacy_files`); in a folder with such leftovers the card also warns before
  a file with another content is replaced (it is backed up first). To clear the leftovers, move them aside by hand.
  To split folders 2.0.2 mixed, move `docs/architecture`, `docs/adr` and `docs/proposal` aside and run
  `ub redo <run> 14.2 --yes` for each run, oldest first (it asks G14 again); the files 2.0.2 replaced are in the
  later run's `_superseded/<stamp>/published/`.

## 2.0.2 - 2026-09-23

Bug-fix release for two timing-dependent failures seen on Windows.

### Fixed

- The same model call could run twice for one job. When the three proposal-section workers (13.2) created the same
  new folder at the same moment, Windows sometimes reported the target path in a long `\\?\` form. The kit then
  wrongly rejected the valid answer as "outside the output root" and asked the model again. The path is now
  normalized first, and an answer that is valid but cannot be written is retried on disk instead of asking the model
  again.
- Only one worker can run a job at a time. Each worker now holds a lock file for its job (`.ub/jobs/<id>.lock`),
  which the operating system releases when the worker ends, even if it is killed. A job that is running, finished,
  or was just run by another worker is never called again, whoever starts it. The launcher and its worker recognize
  each other by a launch token, so this also works in a Windows virtual environment, where the launcher sees a
  different process id than the worker's. A late heartbeat no longer makes a live worker look dead.
- Reading a worker's status file on Windows could fail with "Permission denied" when it was read at the moment the
  worker was updating it. Reads now retry for up to a second, so the kit no longer mistakes a running or finished job
  for a stopped one, and `ub stop` no longer misses a live worker.
- A dead job whose old worker process cannot be stopped now shows a BLOCKED card that suggests `ub stop`, instead of
  waiting forever.
- Tests: the Retry-After check uses a monotonic clock, so wall-clock steps (seen under WSL2) no longer fail it.

## 2.0.1 - 2026-09-23

Bug-fix release. CI now runs every suite on Windows, macOS and Linux (Python 3.9, 3.12, 3.14) and is green.

### Fixed

- Background workers: the job-state check read the "done" marker before the "running" marker, so a model call that
  finished between the two reads looked pending and was launched a second time (duplicate calls and duplicate
  records). The running marker is now read first.
- `install.ps1` now stops on every error. Before, if a cmdlet such as `Get-FileHash` failed to load (for example when
  Windows PowerShell 5.1 inherits a PowerShell 7 module path), the bootstrap could exit 0 without verifying the
  download or installing anything.
- The experimental Claude bundle manifest has an `author`, so `claude plugin validate --strict` passes.
- Tests: the POSIX fake-CLI shims no longer depend on `dirname` being on PATH (this failed every fake CLI call on the
  GitHub Linux and macOS runners); golden files are compared with normalized line endings; bootstrap tests run on
  elevated Windows runners.

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
