# Stage 13: proposal

The decided idea and the chosen architecture become a cited project proposal, a one-pager and a single-file HTML pack.
Writers get evidence packs, not the whole run; every claim is cited or tagged; review is cross-family; the human signs
off.

## Files (`11_PROPOSAL/`)

- `PROPOSAL.md` (assembled: title block, status banner, sections 1-13, appendices A-F)
- `sections/01.md` .. `sections/13.md`
- `ONE-PAGER.md`
- `PRFAQ.md` (deep only)
- `assumptions.md`, `open-questions.md` (`bs.py assumptions`)
- `review/rubric_<fam>.json`, `review/redteam.json`, `review/resolution.md`
- `lint.md`, `lint.json` (`bs.py lint-proposal`)
- `index.html` (`ub render`), `export/` (`ub export --format docx` when pandoc is on PATH)
- `README.md` (file map)

## Steps

| ID | Type | What |
|---|---|---|
| 13.1 | S | `bs.py sources` (stable S-### ids for every URL in the run); evidence packs: PACK_A (frame, context A+B, checks of the chosen idea, decision, card), PACK_B (architecture README, container view, top ADRs, matrix summary, deferred, probe, drivers), PACK_C (cost model, risks, pre-mortem, red-team kill-assumptions, frame success, open questions) |
| 13.2 | D | PROPOSAL-A (sections 2-5), PROPOSAL-B (6-9), PROPOSAL-C (10-13), in parallel, drafter family |
| 13.3 | D | EXEC-ONEPAGER (sections/01.md + ONE-PAGER.md); deep: PRFAQ |
| 13.4 | S | assemble PROPOSAL.md: title block + status banner (DRAFT, APPROVED, AUTOPILOT DRAFT or PENDING MILESTONE 0) + sections + appendices (A ADR index, B assumptions index, C candidate comparison from matrix.json, D idea selection record with audits and PROVISIONAL badges, E glossary, F sources); `bs.py assumptions`; `bs.py lint-proposal` |
| 13.5 | D | PROPOSAL-RUBRIC (rubric families, JSON) and PROPOSAL-REDTEAM (a non-drafter family, JSON) |
| 13.6 | D | PROPOSAL-FIX (drafter): every must-fix and the top 5 red-team items answered as ADDRESSED (where), ACCEPTED-RISK (moved to section 11) or REJECTED (reason); then 13.4 again |
| 13.7 | S | `ub render` -> index.html |
| 13.8 | H | G13: approve -> status Approved and ADRs accepted (dated); `changes: ...` -> 13.6 with the user's changes (at most 2 loops); `switch B` -> redo 12.10; `runner-up` -> redo 12.1 (cost preview first) |

Quick mode (lite): PROPOSAL-LITE writes sections 01, 02, 03, 06, 07, 11, 12, 13 and ONE-PAGER.md in one call; then
assembly, 1 rubric family, no red-team, render, G13.

## Rules in every proposal prompt

1. Use only facts from the pack. Cite them as `[S-###]`.
2. Every number, market claim or competitor claim without a source carries `[ASSUMPTION: ...]` or
   `[ESTIMATE: range; basis]`.
3. Never invent customers, quotes, metrics or moats. Never use the word "novel" (only prior-art checks speak to
   novelty, as "not located within this search").
4. Never change an architecture decision; only summarize it.
5. Say what is not being done.
6. Write in the run language. File names, IDs and section numbers stay in English.

## Section contents

| Section | Heading | Contents |
|---|---|---|
| 1 | `## 1. Executive Summary` | standalone, at most 300 words |
| 2 | `## 2. Problem and Evidence` | who hurts, today's workaround, the cost of the status quo, evidence with source and confidence |
| 3 | `## 3. Solution` | experience and outcome, not implementation |
| 4 | `## 4. Users and Market` | segments by job-to-be-done, non-users, bottom-up size `[ESTIMATE]` |
| 5 | `## 5. Differentiation vs Prior Art` | alternatives table from the check verdicts, an honest moat |
| 6 | `## 6. Architecture Summary` (or `## 6. Approach`) | the container diagram copied verbatim from chosen/containers.md, top ADRs, why this candidate beat the others ("Alternatives considered") |
| 7 | `## 7. Scope and MVP` | in scope, out of scope, non-goals |
| 8 | `## 8. Roadmap and Milestones` | Milestone 0 = run the pre-registered probe with its kill criterion; relative timeframes; exit criteria per milestone |
| 9 | `## 9. Team and Effort` | roles, effort ranges with confidence, AI-assisted vs human-only |
| 10 | `## 10. Budget and Cost` | build and run cost copied from cost-model.md, unit economics or break-even |
| 11 | `## 11. Risks and Mitigations` | top R-ids + pre-mortem + red-team kill-assumptions |
| 12 | `## 12. Success Metrics and Validation Plan` | leading and lagging metrics, SMART key results, the cheapest test per load-bearing assumption |
| 13 | `## 13. Open Questions` | each item with `Owner: <role>` and `Decide by: <milestone>` |
| A-F | `## Appendix A. ADR Index` .. `## Appendix F. Sources` | assembled by script |

ONE-PAGER.md (at most 550 words): `## Problem`, `## Solution`, `## Why now`, `## Who`, `## Differentiation`,
`## Architecture at a glance` (one mermaid flowchart), `## MVP`, `## Roadmap`, `## Budget`, `## Top risks` (3, each
with its test), `## Metrics`, `## The ask`.

## Review

- Rubric (JSON): scores 1-5 for decision_readiness, substance_over_theater, strategic_coherence, doneness_clarity,
  scope_honesty, downstream_usability, shape_fit, each with evidence; must_fix items (section, issue, fix); top fixes;
  an overall comment. Adapted from the BMAD PRD rubric.
- Red-team (JSON): at most 8 load-bearing claims, each with steelman, "Fails if", impact, likelihood and cheapness
  (H/M/L), the cheapest test and a kill criterion; ranked by the product (H/M/L = 3/2/1). Adapted from the pm-skills
  strategy red-team.

## Lint (lint-proposal)

P1 headings in order (sections 1-13, appendices A-F); P2 no placeholders; P3 (warn) a sentence with a digit, % or $ in
sections 2, 4, 5 and 10 carries a source, a URL, [ASSUMPTION or [ESTIMATE; P4 section 1 at most 300 words and the
one-pager at most 550; P5 section 8 mentions Milestone 0 and the probe's kill criterion; P6 every cited S-###, ADR-NNNN
and R-NNN exists; P7 every section 13 item has Owner and Decide by; P8 every [ASSUMPTION is in assumptions.md; P9
(warn) the word "novel"; P10 (warn) a $ figure in section 10 not found in the cost model. `--lite` checks sections 1,
2, 3, 6, 7, 11, 12, 13 and appendices A, B, F.

## HTML pack

`ub render RUN` writes a single `index.html` with inline CSS: system fonts, light and dark themes, print CSS with a
page break before each h2 and the table of contents hidden. Layout: cover (title, pitch, date, status badge), the
one-pager card, a sticky table of contents, the 13 sections, the architecture (diagrams, ADR cards, risk table), the
appendices. Mermaid blocks become `<pre class="mermaid">` and render from the Mermaid CDN [U-26]; offline, the source
text stays visible. `ub render --zip` also zips index.html, PROPOSAL.md, ONE-PAGER.md and `10_ARCHITECTURE/`.

## Status banners

| Banner | When |
|---|---|
| DRAFT | before G13 |
| APPROVED | the user approved at G13 |
| AUTOPILOT DRAFT: no human decisions were made | full-auto |
| PENDING MILESTONE 0 | approved, but the probe has no `RESULT: PASSED` yet |
| PROVISIONAL | shown in addition when any seat ran as `<family>-alt` |
