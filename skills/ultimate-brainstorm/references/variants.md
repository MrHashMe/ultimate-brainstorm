# Variants and build types

The engine infers the variant from the topic (or the user names it) and shows it on the kickoff card. Only the items
listed here change; everything else follows references/pipeline.md.

| Variant | Build type | Proposal section 6 |
|---|---|---|
| software, product, growth, general | system | `## 6. Architecture Summary` |
| research, marketing, creative, naming | approach | `## 6. Approach` |

The build type follows the variant: to change it, change the variant at G0 (the kickoff card marks an inferred variant
"(inferred; ...)"; a keyword line such as `product` in the reply changes it).

## software - a feature or project inside an existing codebase

- Run inside the repo. Generators never read `brainstorm/`; every focus text says "do not read anything under
  brainstorm/; it is not part of the codebase". The kit writes the `.gitignore` files (`*`) into the run folder and
  `brainstorm/` itself when it first builds a job that reads the repository; adding `brainstorm/` to
  `.git/info/exclude` (local, never committed) is optional and hides run files earlier.
- For growing an existing product (activation, retention, conversion) use `growth` instead.
- Frame: grilling + domain-modeling (host/FRAME-GRILL-DOCS): terms are challenged against CONTEXT.md, claims are
  checked against the code (file:line), and resolved terms go to `brainstorm/<run>/CONTEXT.proposed.md`; the repo's
  CONTEXT.md and ADRs are touched only at the handoff, after a yes.
- Frame add-ons: which modules are involved (looked up), what exists already, which changes must stay reversible. Axes
  example: user-journey stage x system layer (UI, API, data, infra) x horizon.
- Criteria: Value 30, Feasibility 25 (feasible HERE: cite file:line; a NOT VERIFIED feasibility claim scores at most
  3), Fit 20 (architecture fit), Distinctiveness 15, Evidence 10.
- Ground: FACTS cite file paths; the researcher on the host vendor may read the repo. Other vendors get paths only
  unless privacy `code` = yes.
- S1 = ce-ideate in repo mode when used (codebase scan, learnings, web prior art). S5-OPS adds operator (f)
  Contradiction (TRIZ).
- Checks add item 5, codebase fit (does the product already do this, file:line; conflicts with the architecture,
  CONCEPTS.md, flags or analytics; which files would change), in a git repository, for checkers of the host vendor,
  or of any vendor when privacy `code` = yes; otherwise (another vendor with `code` = no, or a folder without git) a
  checker answers items 1-4 only. For ideas that extend an existing product, K4 does not apply.
- Probe: a throwaway spike in a separate git worktree, or behind a feature flag in a scratch branch, with 2-5
  Given/When/Then checks and thresholds written first; verdict VALIDATED / INVALIDATED / PARTIAL. A new worktree has no
  installed dependencies and no local `.env*` files, and the pipeline never installs software: the user runs the
  install. INVALIDATED promotes the runner-up. The spike branch is never merged.
- Architecture: archetype A = "Smallest change to the current architecture (cite files)"; B = "One new bounded
  component or service"; C and D as in references/architecture.md. The brief includes repo FACTS; writers on the host
  vendor may read files.
- Handoff: HANDOFF-CE (ce-brainstorm, then ce-plan), or the repo's existing Superpowers or OpenSpec (only one).

## growth - activation, retention or conversion of an existing product

- Run inside the product's repo, as for software. Topics about activation, onboarding, conversion, retention or churn
  route here.
- Frame: as for software, and pin "activated", "retained" and "converted" as MEASUREMENT definitions (event, window,
  source), tagged [MEASUREMENT] with "(measurement definition; ideas may propose a different one)". They are not
  design constraints: an idea that proposes a different activation event is kept and scored on Evidence that the new
  event predicts retention; its probe still reports the pinned metric as a guardrail.
- Frame add-ons: the exact event and window; today's rate, source and cohort; restate goals that exceed 100% of the
  baseline ("10x activation" from 30%) as a confirmed alternative target; whether the event is tracked (looked up);
  how many units enter the target window per week (sets the test's sample size).
- Criteria: <Metric> impact 30 (Activation, Retention or Conversion impact), Evidence 20, Feasibility 20 (file:line),
  Time to test 15, Distinctiveness 15.
- Ground: funnel steps with counts for the last 4-8 weeks (pasted by the user or from an analytics MCP), each labeled
  FACT (source, date); tracking calls on the onboarding path; uninstrumented steps; first-session empty states.
- Checks: item 5 (codebase fit), as for software. K4 does not apply: prior art is evidence (record the reported lift
  and source).
- Probe: a feature-flagged experiment on the units entering the target window with metric, baseline, minimum
  detectable effect, sample size per arm, duration and guardrails written first; longer than 4 weeks -> a leading
  indicator, or for activation a moderated first-session test with 5 new users or a fake door.
- Decision: G8b may choose a bundle of 2-4 ideas with a test order and one pre-registered test each; ideas that
  interact must not share a test window.
- Architecture: as for software. Handoff: HANDOFF-CE.

## product - a new product or startup

- First question: pre-product, has users, paying customers, or infrastructure? Then the stage-routed forcing
  questions (ported from gstack /office-hours; "interest is not demand"): pre-product -> demand reality (who would be
  upset if a solution vanished - name them), status quo (what they do today and what it costs), desperate specificity
  (the single most specific person, role or situation); has users -> status quo, narrowest wedge (the smallest version
  someone would pay for this week), observation and surprise; paying customers -> narrowest wedge, observation,
  future-fit (why this becomes more essential in 3 years); infrastructure -> status quo, narrowest wedge. One per
  message, at most one push-back each; exempt from the round cap. Every answer becomes a numbered premise. If the
  first three are all NOT VERIFIED, add the premise "demand unverified" and make customer interviews the default probe.
- A named solution type ("AI agents for accounting firms") is classified as a hard constraint, a soft preference or a
  hypothesis to test.
- B2B add-ons: economic buyer vs user; current spend and budget line; required integrations (looked up); liability for
  errors; confidential or regulated data as a hard gate (verify the rule for the jurisdiction); seasonality.
- Criteria: Value/pain 30, Reachability 20, Feasibility 20, Distinctiveness 15, Evidence of demand 15. B2B: Value/pain
  25, Willingness to pay 20, Reachability 15, Feasibility 20, Distinctiveness 10, Evidence of demand 10.
- Ground: the LANDSCAPE covers competitors AND today's workarounds (the workaround is the real competitor).
- Checks: CROWDED needs named products for the same user through the same channel.
- Probe: a behavior test (landing page, concierge, pre-order, fake door): "At least X% of Y will do Z by <date>".
  Consumer defaults: at most 2 weeks, at most $100, at least 30 responses or 100 visitors, threshold fixed first. B2B:
  8-12 problem interviews with qualified buyers (past behavior only), a concierge pilot with 1-3 customers, or at least
  3 letters of intent or paid deposits; avoid the audience's peak season.
- Optional extras: pm-skills assumption chain and red-team (references/components.md).
- Build the product only after the probe passes; the proposal's Milestone 0 says so.

## research - a research question or hypothesis

- Frame add-ons: freeze the observation (measurement, population, units, uncertainty, whether the pattern was selected
  after looking at results); claim type (descriptive, associational, predictive, causal, mechanistic); question frame
  (PICO/PECO or construct-context-outcome); a dated search boundary. Human seeds matter most here.
- Criteria: Significance 30, Testability 25 (a discriminating prediction exists), Feasibility 20, Distinctiveness 15,
  Evidence 10.
- Diverge: S2-S4 as usual (S4 retrieves papers across fields); S5-OPS is replaced by S5-RESEARCH, the research lens
  quota adapted from Phase 1 of Orchestra's brainstorming-research-ideas skill (5 tensions or trade-offs, 3 recent
  shifts used to revisit old negative results, 2 failure or boundary probes, 1 adjacent-field import, 1 compose or
  decompose, then up/down/sideways variants).
- Checks: CROWDED needs named papers that already contain the result (ARIS's rule: a stated delta is not crowded).
- Probe: a pilot with the decision rule written in advance. Optional extras: K-Dense hypothesis-generation and the
  pre-registration scaffold, ARIS novelty-check for ML ideas.
- Build type approach: approach.md with hypotheses and rival explanations, design, measures, data, analysis plan with
  decision rule, compute, ethics, timeline, risks.

## marketing, creative and naming

- LLM judges are least reliable on taste: the human is the primary judge and the tournament is advisory. The screen
  header applies anti-inflation rules adapted from creative-director (no 5 without named real analogues; re-score if
  every idea scores 4+ or the mean is above 3.5; Distinctiveness at most 2 when a competitor's brand can be swapped
  in). Keep its CC BY 4.0 attribution line on any reuse of its text.
- Probe: a 24-hour re-read plus reactions from 5 people in the target audience.
- Marketing: optional `/product-marketing` facts and a `/marketing-ideas` coverage sweep after the map (gap targets at
  G3). Build type approach: channels, assets, production, measurement, budget, timeline.
- Creative / campaigns: optional `/creative-director` as an imported extra strand. Build type approach as marketing.
- Naming: frame fields = what it does in one sentence, audience, desired feel, brand family, off-limits words,
  platforms that must be available. S2-S5 use metaphor territories as the axes. Criteria default: Metaphor strength
  30, Memorability 25, Phone test 20, Searchability 15, Distinctiveness 10; availability is a hard constraint.
  Trademark screening is manual. Build type approach: shortlist rollout, availability and trademark checks (manual),
  launch plan.

## general

The default pipeline with the default criteria: Value 30, Feasibility 25, Fit 20, Distinctiveness 15, Evidence 10.

## Architecture archetypes by variant (Stage 12)

| Seed | Default | software and growth |
|---|---|---|
| A | Boring by default: a modular monolith on managed services, at most 3 innovation tokens | Smallest change to the current architecture (cite files) |
| B | privacy-heavy -> local-first / offline-first; tight budget or solo team -> buy-and-integrate (SaaS plus glue); otherwise event-driven / serverless | One new bounded component or service |
| C | the approach the other candidates would not pick, strongest case, every hard constraint met | same |
| D (deep) | cost-minimal: the cheapest design that meets the H-importance scenarios | same |

Quick mode uses A and C.

## Single family, private runs and cross-model runs

- Only one family available, or `private` (no other vendors): every "other" seat becomes `<host>-alt` (an alternate
  model of the same vendor, or the same model in a fresh context). Results are PROVISIONAL; the banner appears on every
  card, in 00_RUN.md and in the proposal header; self-preference audits are skipped.
- Add families to restore cross-vendor judging: install the Codex, Claude Code or Kimi Code CLI, or set up GLM or Kimi
  keys (references/families.md). Optional claude-council seats add vendors at the red-team step.
- Maximum diversity: 3-4 families. Vendors mainly de-bias judging; strategies drive idea diversity, so do not add
  vendors instead of strategies.
