# Components: installed skills the pipeline uses or offers

Everything here is optional. The engine detects the names the host passes with `--components` (spelled exactly as the
host's skills list shows them, for example `mattpocock-skills:grilling`) and uses them through HOST cards; when a
component is missing, a built-in template runs instead. Components that the pipeline does not call itself are listed
as optional extras the host may offer the user between cards. This file replaces the tool part of v1 tools.md.

## Detection names

| Look for | Tool | Used at |
|---|---|---|
| `grilling` or `mattpocock-skills:grilling` | Matt Pocock skills | Stage 2 (host/FRAME-GRILL) |
| `domain-modeling` or `mattpocock-skills:domain-modeling` | Matt Pocock skills | Stage 2 in software/growth (host/FRAME-GRILL-DOCS), Stage 14 (host/CONTEXT-MERGE) |
| `ce-ideate` or `compound-engineering:ce-ideate` | Compound Engineering | Stage 4 strategy S1 (host/S1-CE) |
| `ce-brainstorm`, `ce-plan` | Compound Engineering | Stage 14 handoff (HANDOFF-CE) |
| `bmad-brainstorming` | BMAD Method | Stage 1 in deep mode (host/BMAD-SEEDS) |
| `bmad-forge-idea` | BMAD Method (core since v6.9.0) | Stage 10 forge in deep mode (host/FORGE) |
| `lateral-thinking` or `lateral-thinking:lateral-thinking` | abpai lateral-thinking | optional extra strand (S4-TRANSFER already uses its method) |
| `claude-council:ask` | hex claude-council | optional extra vendor seats at Stage 10 |
| `speckit` (the `specify` CLI) | GitHub Spec Kit | Stage 14 handoff (HANDOFF-SPECKIT) |
| `superpowers:brainstorming`, `opsx:explore` / `openspec-explore` | Superpowers, OpenSpec | Stage 14 alternatives, only when the repo already uses them |
| pm-skills, K-Dense, ARIS, marketingskills, creative-director, naming | see below | optional extras per variant |

## grilling (Stage 2)

- Invoke by the exact name from the skills list (a plugin install is namespaced: `mattpocock-skills:grilling`). Claude
  Code: the Skill tool. Codex, Kimi Code, ZCode: open its SKILL.md and run the interview from the argument text.
- Interactive (it waits for the user's answers every round, no async mode): main conversation only, never a sub-agent,
  plan mode off. Round cap: 1 in guided, 3 otherwise (the argument says so).
- It writes no file. After it, the host asks the remaining framing questions (part-of-the-problem, solution type,
  variant add-ons), shows STATED vs ASSUMED, and writes 01_FRAME.md and criteria.json in the FRAME-FINAL format.
- Never go through `grill-me` or `grill-with-docs`: both are one-line manual wrappers (`disable-model-invocation:
  true`; explicit-only in Codex) whose dependency loads are reported as unreliable. The pipeline loads the primitives.

## domain-modeling (Stage 2 in software and growth; Stage 14)

- Loaded right after grilling, with the same argument (host/FRAME-GRILL-DOCS). Claude Code: both Skill calls in the
  same turn before asking anything, grilling first. Codex: read its SKILL.md and CONTEXT-FORMAT.md, then re-read the
  argument last.
- What it adds: challenges terms against CONTEXT.md, proposes one canonical term for vague or overloaded words (with
  `_Avoid_` synonyms), edge-case scenarios about today's behavior, and quotes the code back when a claim and the code
  disagree.
- Its default writes (CONTEXT.md inline, ADRs in docs/adr/) are overridden: resolved terms go to
  `brainstorm/<run>/CONTEXT.proposed.md`, ADR candidates go to the frame's Decision ledger. The engine snapshots
  CONTEXT.md first (CONTEXT.before.md) and checks the footprint afterwards (G2f offers a restore).
- Known issues: models often load grilling and skip domain-modeling, and the file-writing half "is reported to
  silently not happen" inside other orchestration layers; the host checks that CONTEXT.proposed.md exists when terms
  resolved. CONTEXT.md tends to grow into a spec: keep it to terms.
- Stage 14 (host/CONTEXT-MERGE): merges only the terms the user approves, one yes per ADR.

## Compound Engineering ce-ideate (Stage 4, strategy S1)

- Used when installed and the user says `with-ce-ideate` (guided) or in hands-on mode; otherwise S1F runs.
- Main conversation only: it is interactive, dispatches its own sub-agents and ends with a menu. Not available in the
  Codex IDE extension. On Windows it creates its scratch folder with a POSIX snippet: run it where Git Bash exists.
- Focus text (the argument): the HMW sentence, "treat 01_FRAME.md as the directive brief", "do not read anything else
  under brainstorm/", "do not print the ranked list", `output:md`, plus the dials `go deep` (deep mode) and `no
  external research` (privacy web or code = no, because its web researcher sends the problem statement out).
- At its final menu (Open / Brainstorm one idea / Discuss / Done): ask for the absolute paths of the ideation document
  and `raw-candidates.md`, then reply `discard`. The host then runs `ub attach-s1 RUN --doc <path> --raw <path>`,
  which copies both into `pool/S1_ce-ideate*.md`. Raw candidates and rejections enter the pool as PARKED ideas.
- ce-ideate may print its ranked survivors anyway; the host records whether the user saw them.
- Side effects: it writes an ideation document on every run (repo mode: `<docs root>/ideation/`); a commit offer
  appears only after Done inside a git repo - decline it.

## Compound Engineering ce-brainstorm, then ce-plan (handoff)

- Claude Code: `/compound-engineering:ce-brainstorm <HANDOFF-CE seed>`, then choose "Create the implementation plan".
  Codex: `$ce-brainstorm <seed>`. Start it in a fresh session in the target repo.
- Output: a requirements-only plan in `docs/plans/`. It silently refines an existing CONCEPTS.md.

## BMAD bmad-brainstorming (Stage 1, deep) and bmad-forge-idea (Stage 10, deep)

- bmad-brainstorming: interactive, main conversation. Answer its compound kickoff with the Problem line; choose the
  Facilitator stance (the AI supplies no ideas); pick 3-4 techniques; take another batch or wrap up, never converge.
  Import every `(idea)` line (Creative Partner mode: `(idea by user)`) of
  `<output_folder>/brainstorming/brainstorm-<slug>-<date>/.memlog.md` (default output folder `_bmad-output`) into the
  seeds file under Ideas. Never import `--by coach` ideas as human seeds.
- bmad-forge-idea: interactive only. Missing: the built-in FORGE (two voices per turn, one question per message,
  outcome HARDENED, KILLED or CLEARER) runs instead.
- Install: `npx bmad-method@6.12.0 install` (Node 20.12+, uv, Python 3.10+).

## Spec Kit (handoff, greenfield)

- `specify init <project> --integration <agent>` in a shell, then `/speckit.specify` with the HANDOFF-SPECKIT seed
  (proposal sections 3 and 6-8 plus the chosen/ architecture files). Install (v1.0.12):
  `uv tool install specify-cli --from git+https://github.com/github/spec-kit.git@e77daa9021d20db26b878f7dfa5640fe5a42d04e`.

## Superpowers and OpenSpec (handoff alternatives; one spec owner per repo)

- Only when the repository already uses them. Superpowers: `/superpowers:brainstorming <seed>` (the Codex marketplace
  copy has no staged gate: keep "Stop after the spec for my review"); kill criteria go into the plan's Global
  Constraints and the "Fails if" list into Review Focus. OpenSpec: `/opsx:explore <seed>`, then `/opsx:propose <name>`
  (Codex: `$openspec-explore`, then `$openspec-propose`); explore itself writes nothing.

## Optional extras (the host may offer them; the engine does not call them)

### claude-council (extra vendor seats at Stage 10)
- Claude Code: `/claude-council:ask --file=brainstorm/<run>/07_TOP.md --debate --roles=devil,simplicity
  --no-auto-context --output=brainstorm/<run>/redteam/council.md "<question>"`. Codex: the clone's
  `scripts/query-council.sh` with the same flags (bash, curl, jq; on Windows call Git Bash's bash.exe explicitly).
- Keep `--no-auto-context` when privacy code = no (auto-context sends up to 5 repo files to the seats). Avoid
  `--agents` (one measured 8-seat run used about 456k tokens). Its synthesis treats unanimity as a caution.
- A council file is advisory; the pipeline's red-team, synthesis and the human decision stay as they are.

### idea-reality-mcp (developer-tool ideas)
- `idea_check(idea_text, depth="deep")`. The released 0.5.0 counts failed sources as 0: a low score means UNKNOWN,
  never "no competition". Needs GITHUB_TOKEN. Workers run with an empty MCP config, so the engine's CHECK jobs never
  call it; the user may run it by hand and add the result to the checks. Skip when privacy web = no.

### pm-skills (product variant)
- identify-assumptions-new, prioritize-assumptions, brainstorm-experiments-new (plugin `pm-product-discovery`) and
  strategy-red-team / `/pm-execution:red-team-prd` (plugin `pm-execution`; commands do not run in Codex). Useful after
  09_PROBE.md exists, to cross-check the probe. prioritize-assumptions rates Impact x Risk with Risk = (1 - Confidence)
  x Effort; to let uncertainty drive the ranking, say "rank by impact x lack of evidence (1 - confidence); do not let
  effort raise the risk score". Never run `/discover` inside a run: it brainstorms a fresh idea set.

### K-Dense (research variant)
- `/hypothesis-generation` on the top 1-3 ideas (rival explanations, discriminating predictions, falsifiers), and the
  pre-registration scaffold `python3 scripts/generate_preregistration_scaffold.py record.json -o preregistration.md`
  from its skill folder. Its SKILL.md asks for a K-Dense citation in deliverables; tell it not to if unwanted.

### ARIS (research variant, ML)
- `/aris:novelty-check "<idea>"`: PROCEED / PROCEED WITH CAUTION / ABANDON; ABANDON only with a named paper that
  already contains the result. `/aris:setup` replaces any other user-scope MCP server named `codex`; its core
  pipelines default to AUTO_PROCEED true (add "AUTO_PROCEED: false" to pause at gates).

### marketingskills (marketing variant)
- `/product-marketing` writes `.agents/product-marketing.md` (usable as grounding facts). After the map,
  `/marketing-ideas` can list which of its 17 catalog categories have no ideas in 03_POOL.md (gap targets to name at
  G3). `/marketing-council` is an alternative red-team view. Plugin install names: `/marketing-skills:<name>`.

### creative-director (campaign variant)
- `/creative-director`: ask it to find an insight, then generate concepts; its output can be imported
  (`ub import <file>`) as an extra strand before the map. Its anti-inflation rules are adapted in the screen header.
  CC BY 4.0: keep the line "Serge Shima - github.com/smixs/creative-director-skill" on any reuse of its text or case
  library.

### naming (naming variant; Claude Code)
- `/naming <what it does>` with the frame fields. By design it shows only 3-5 vetted finalists; for the wider pool,
  override explicitly: "Also list every metaphor territory and every raw candidate before filtering, and write them
  to a file", then `ub import <file>`. Pass the platforms to its availability check. Trademark screening stays manual.
