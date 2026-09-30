# Stage 12: architecture package

The chosen idea gets competing architectures, written independently and judged blind against a brief frozen before
any of them existed; the human chooses; the chosen one is written up as a package with ADRs, risks, a verified stack
and review. The engine runs every step; this file explains what it does and what each file must contain.

## Files (`10_ARCHITECTURE/`)

| File | What |
|---|---|
| 00_BRIEF.md, brief.json | the frozen brief (12.1, assembled by script) |
| drivers.json | ARCH-DRIVERS output: product goal, 3-5 quality goals (weights sum to 70), hard and soft constraints, not in scope, 5-10 quality attribute scenarios (QAS), context, planning assumptions, open questions |
| goals-constraints.md, quality-scenarios.md, context.md | rendered from drivers.json |
| candidates/<n>.md, candidates/<n>.json, candidates/map.json | raw candidate outputs; map = label -> family, archetype, job |
| review/sheet_<L>.md | neutral judge sheets rendered from each candidate's JSON tail (no archetype or family names) |
| review/judge_<fam>.out.json | ARCH-JUDGE outputs |
| tradeoff-matrix.md, matrix.json | `bs.py arch-matrix` |
| premortem.md | ARCH-PREMORTEM on the leader |
| chosen/containers.md, runtime.md, data-model.md, api.md, api/openapi.yaml or api/cli.md | ARCH-PACKAGE-STRUCTURE |
| chosen/deployment.md, security-privacy.md, cost-model.md, deferred.md | ARCH-PACKAGE-CROSSCUT |
| decisions.json -> adr/NNNN-<slug>.md, risks.md | ARCH-DECISIONS output, rendered by script (MADR 4.0 minimal) |
| stack.json -> chosen/stack.md | STACK-VERIFY output, rendered |
| review/<lens>_<fam>.json, review/resolution.md | review lenses and the fix pass |
| lint.md, lint.json | `bs.py lint-arch` |
| README.md | summary, chosen candidate and why, alternatives considered, quality goals -> mechanisms, decision index, file map, provenance |
| approach.md | build type approach only (instead of the package) |
| _raw/ | raw FILE-protocol outputs and status files |

## Steps

| ID | Type | What |
|---|---|---|
| 12.1 | S | Brief, by headings: 01_FRAME.md (job, audience, success, hard/soft constraints, non-goals), 08_DECISION.md (chosen card, scope, not doing), checks of the chosen idea, the red-team kill-assumptions, the probe's riskiest assumption, privacy flags |
| 12.2 | D | ARCH-DRIVERS (host family, JSON). Missing facts are tagged [ASSUMPTION]; weights are normalized to 70 with a warning; goals, scenarios and the context view (C4Context + flowchart fallback) are rendered |
| 12.3 | H | G10 drivers (hands-on, deep) |
| 12.4 | D | ARCH-CANDIDATE x K (fresh contexts, the same frozen brief, one archetype seed each). At least 2 valid candidates; otherwise one recovery launch on another family; otherwise BLOCKED |
| 12.5 | S | labels A..D in random order; map.json; neutral sheets (fixed field order, each string cut to 60 words) |
| 12.6 | D | ARCH-JUDGE x J on the sheets + brief + scenarios (JSON, every label x every criterion) |
| 12.7 | S | `bs.py arch-matrix` |
| 12.8 | D | ARCH-PREMORTEM on the leader, by a family other than its author |
| 12.9 | H | G11 (quick: auto, but asked in hands-on and guided when the leader is vetoed, self-judged or confounded; with 2 families always, since the one arch judge is of an author family; an automatic leader is shown at G13 with `switch`). Author families are revealed only after the choice |
| 12.10 | D | ARCH-PACKAGE-STRUCTURE (the chosen candidate's author family) |
| 12.11 | D | in parallel: ARCH-PACKAGE-CROSSCUT, ARCH-DECISIONS, STACK-VERIFY (web family) |
| 12.12 | S | render ADRs (`status: proposed`), risks.md, chosen/stack.md; `bs.py lint-arch` |
| 12.13 | D | ARCH-REVIEW lenses: standard L1 + L2; deep adds L3 + L4; each on a family other than the writer |
| 12.14 | D | ARCH-FIX (writer family): P0/P1 findings and lint FAILs, one pass (deep: two); re-render and lint again. What remains goes to the proposal's open questions and the G13 card |
| 12.15 | S | README.md |
| 12.16 | H | G12 ADRs (hands-on, deep; guided bundles ADR acceptance into G13) |

Quick mode (lite): drivers; 2 candidates (A and C); 1 judge; matrix; automatic leader unless it is vetoed,
self-judged or confounded (then hands-on and guided are asked; 2 families: self-judged, so G11 asks);
ARCH-PACKAGE-LITE (containers, data model, decisions.json with 3 ADRs + risks); stack.json from the candidate with
every row UNVERIFIED; render; `lint-arch --lite`; no review.

Build type approach (research, marketing, creative, naming): 12.1, then APPROACH (host family, approach.md with the
variant's headings), one ARCH-REVIEW lens by another family, lint A2 only, no G11.

## Archetype seeds

| Seed | Text |
|---|---|
| A | Boring by default: a modular monolith on managed services (managed database, managed auth). At most 3 innovation tokens. The simplest design that meets every H-importance quality scenario |
| B | privacy-heavy (a hard constraint mentions PII, on-prem, offline or data residency) -> local-first / offline-first; tight budget (a low planning budget or a solo team) -> buy-and-integrate: SaaS plus glue code; otherwise -> event-driven / serverless: managed functions, queues and events, scale to zero |
| C | The approach the other candidates would not pick (the others are named); its strongest case, still meeting every hard constraint |
| D (deep) | Cost-minimal: the cheapest design that still meets the H-importance quality scenarios |
| software / growth | A = smallest change to the current architecture (cite files); B = one new bounded component or service; C and D as above |

Every candidate prompt says: "You are ONE independent architect; others design alternatives you will never see. Keep
every hard requirement identical; the archetype is a starting stance, not a cage. Never state a version, price or
limit as fact unless the brief gives it: mark [ASSUMPTION] or [TO VERIFY]."

## Candidate format

Headings in order: `## 1 Paradigm`, `## 2 Container view` (mermaid flowchart, one subgraph per boundary, at most 12
nodes), `## 3 Stack` (component | choice | why | alternative rejected; versions [TO VERIFY]), `## 4 Quality
mechanisms` (QAS id | mechanism | expected response measure), `## 5 Data`, `## 6 Deployment and operations`, `## 7
Security and privacy` (top 3 threats + mitigations), `## 8 Cost` (build person-weeks; monthly run cost at MVP, 10x
and 100x; LLM tokens), `## 9 Trade-offs` (sensitivity points), `## 10 Risks` (top 5, "Fails if ..."), `## 11 Rejected
approaches` (at least 2), `## 12 Innovation tokens`; then one fenced json block matching `arch-candidate`.

## Judging and the matrix

- Judges score against the brief, not against each other: neutral labels, random order; wording and length ignored;
  hard constraints first (veto with reason). Anchors: 5 = meets every H-importance scenario with a named mechanism and
  margin; 3 = meets them with caveats; 1 = misses an H-importance scenario.
- Criteria: the quality goals (weights summing to 70) plus fixed criteria time_to_mvp 10, team_fit 5, run_cost 5,
  reversibility 5, operational_simplicity 5.
- A judge's score of a candidate written by its own family does not count (when no other judge exists, all judges
  count and the matrix says so).
- Score = weighted mean of the eligible judges' scores after per-judge centering (each judge's mean per criterion moved
  to the panel mean), W over the criteria every ranked candidate has an eligible judge's score for; when candidates
  share no eligible judge and each has one own-family judge, every judge's centered score counts. Veto: any judge's veto counts (an author family vetoing its own candidate included): 2 or more
  -> EXCLUDED; exactly 1 -> FLAGGED (the only eligible judge: "single-judge veto: the human decides").
- Rank ranges with each weight at +/-25%. Disagreement = the counted judges' scores spanning 2 or more points. Leader =
  the top candidate that is not excluded; `self-judged` when only its author family's judge scored it or the
  runner-up (a failed judge, or 2-family quick mode, whose one judge is the host and wrote a candidate; not in a
  one-family run), `confounded` when it and the runner-up share no eligible judge, `clear` when its range is [1,1], no
  other range reaches 1, it is not tied, no judge that favours its own family's candidate tilts it against the
  runner-up, no flagged pair self-preference (two families judging each other's candidates) can reorder it with the
  other family's candidates and no criterion was left out of W, else `close-call`. The G11 default passes over a leader that a judge vetoed and asks about a self-judged or
  confounded one.
- The steal list (elements of other candidates that would improve the leader) is offered at G11: "B + steal A: ...".

## Document formats (the lint checks them)

| File | Format |
|---|---|
| goals-constraints.md | `# Goals and constraints`; `## Product goal`; `## Quality goals` (id, goal, weight, why, source); `## Hard constraints`; `## Soft constraints`; `## Not in scope`; `## Planning assumptions`; `## Open questions` |
| quality-scenarios.md | `## Utility tree` (QG -> QAS); `## Scenarios` (id, attribute, source, stimulus, artifact, environment, response, response measure, importance, difficulty) |
| context.md | `## System context`; a mermaid C4Context block and a mermaid flowchart fallback with the same elements; `## Actors`; `## External systems` (EXT table) |
| chosen/containers.md | `## Containers` (C4Container + flowchart fallback; table id, name, technology, responsibility, data owned, interface); `## How each quality goal is met` (QG, mechanism, containers, QAS, expected response) |
| chosen/runtime.md | `## F-1 <title>` sections with sequenceDiagrams; at least one `## F-n Failure and recovery: <title>` |
| chosen/data-model.md | erDiagram + `## Entities` (entity, fields, owner container, retention, PII) |
| chosen/deployment.md | environments, hosting, CI/CD, IaC, observability, backup/DR with RTO/RPO numbers |
| chosen/security-privacy.md | data classification table, authn/authz, STRIDE-lite per trust boundary, PII handling, compliance scope |
| chosen/cost-model.md | `## Assumptions`; `## Monthly run cost` (MVP, 10x, 100x); `## Per active user`; `## LLM and API costs`; `## Build cost`; `## Sensitivity` (+/-50% on the top driver) |
| chosen/stack.md | table: layer, component, choice, version, release date, source, status, license, EOL note, alternatives, innovation token |
| chosen/deferred.md | table: decision, why deferred, trigger, decide by |
| adr/NNNN-slug.md | MADR 4.0 minimal: frontmatter status, date, decision-makers; `# ADR-NNNN: <title>`; Context and Problem Statement; Decision Drivers; Considered Options (at least 2); Decision Outcome ("Chosen option: ..., because ..."); Consequences (Good / Bad with R-ids); Confirmation; More Information |
| risks.md | `## Risks` (id, risk, likelihood, impact, mitigation, owner, early warning, source); `## Technical debt` (id, debt, why accepted, payoff trigger) |

Lint rules (lint-arch): A1 required files; A2 no placeholders (TODO, TBD, XXX, lorem, `{{`, angle-bracket
placeholders; a type argument such as `list<string>` is none) outside code; A3 ADR structure and cited risks exist; A4
every stack row has a version (empty, `n/a` or `latest ...` fails and renders from stack.json as UNVERIFIED;
UNVERIFIED or TO-VERIFY warns); A5 mermaid (diagram type first, brackets and quotes balanced on every
line, no tabs, a flowchart after every C4 block); A6 traceability (QG ids, EXT ids, C-ids, a failure/recovery flow);
A7 deployment, security and cost at least 120 words each or deferred, cost-model has Assumptions and Sensitivity; A8
unique R-ids and both risk headings; A9 the README decision index matches adr/.

ADR rules: an ADR only for a choice that is hard to reverse, surprising without context and a real trade-off; the
considered options include the rejected candidates' approaches; risks absorb the pre-mortem causes and the candidate's
risks; risks and technical debt stay separate. At G13 approval the ADRs become `accepted` with the date.

Review lenses: L1 web-verified tech (every technology, version and capability claim); L2 divergence adversary (two
teams obeying every ADR still diverge where? list the missing decisions); L3 failure modes and prior art (a path with
no test, no error handling and a silent failure is P0; what already exists); L4 security and privacy (STRIDE gaps,
secrets, authorization, PII, compliance). ARCH-FIX applies P0/P1 findings and lint FAILs only and writes
review/resolution.md (finding | FIXED/DEFERRED/REJECTED | reason).
