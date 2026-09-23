<!-- ub-template: FRAME-DRAFT v1 kind=frame -->
Do not load or invoke any skill; this prompt is the whole task.
STAGE 2 - DRAFT THE FRAME (autopilot: nobody answers questions in this run). Write 01_FRAME.md and criteria.json from
the topic and the problem statement alone. Framing stays question-only: propose no solutions, example ideas or idea
categories anywhere in the frame. Everything the TOPIC or PROBLEM text does not state is your inference: tag every
such item "ASSUMED" in place, mark every Decision ledger row ASSUMED, and every premise NOT VERIFIED unless the text
states it. Put each question you would have asked the user under open_questions in STATUS, with the default you used.
Language: {{LANG}} (headings, file names and IDs stay in English). Variant: {{VARIANT}}. Mode: {{MODE}}. Date: {{DATE}}.

TOPIC
{{TOPIC}}

PROBLEM AND OFF-LIMITS (from the user's seeds file; may say SKIPPED)
{{SEED_PROBLEM}}

FACTS ALREADY KNOWN (may be empty)
{{FACTS}}

STRATEGY PLAN (fixed by the engine; copy it into the Strategy plan section)
{{STRATEGY_MAP}}

PRIVACY (fixed; copy it into the last section)
{{PRIVACY_LINE}}

FORMAT OF 01_FRAME.md - exactly these headings, in this order; replace every angle-bracket placeholder:
# FRAME: <short title>
## Job statement
  "When <situation>, <who> wants to <progress>, so they can <outcome>." Anchor-stripped: name no existing product,
  tool, library or current implementation; keep only real constraints; everyday words, no glossary terms.
## Problem
  "How might we <action> for <whom> so that <outcome>?" plus 1-2 sentences of context.
## Audience / boundary
## Success looks like
  Observable, measurable, by when; a baseline number and its source, or NOT VERIFIED.
## Hard constraints
  The gates. Include every ADR or rule the user called a hard constraint.
## Soft constraints
  Include every ADR or preference the user called reopenable.
## Non-goals
## Decision ledger
  Table | # | decision | answer | status | with status CONFIRMED, DEFAULT (accepted recommendation), ASSUMED or
  UNRESOLVED. A named solution type goes here with the user's answer: hard constraint (a gate), soft preference (a
  soft constraint) or hypothesis (kept out of the job statement).
## Premises
  P1..Pn, each OBSERVED (with source) or NOT VERIFIED (plus what would confirm it).
## Kill condition for the whole effort
  What would make us stop pursuing this problem at all.
## Domain language
  Software and growth only; omit this heading in other variants. Terms the user resolved, each with a one-line
  definition tagged NEW, CHANGED or MEASUREMENT, or "none resolved". These describe today's system, not the
  solution space.
## Criteria
  Table | criterion | weight | 1 = | 3 = | 5 = | with 3 to 5 criteria (the B2B product default has 6), weights
  summing to 100, and an anchor for scores 1, 3 and 5. Keep the names Feasibility and Distinctiveness when they fit
  (the scripts use them for the tail slot). Distinctiveness means distance from the obvious answer in this field; it
  is NOT novelty.
  Defaults by variant (use them unless the answers say otherwise):
  - general, marketing, creative: Value 30, Feasibility 25, Fit 20, Distinctiveness 15, Evidence 10
  - software: Value 30, Feasibility 25 (feasible HERE, cite file:line; a NOT VERIFIED feasibility claim scores at
    most 3), Fit 20 (architecture fit), Distinctiveness 15, Evidence 10
  - growth: <Activation|Retention|Conversion> impact 30 (named after the metric in Success), Evidence 20,
    Feasibility 20, Time to test 15, Distinctiveness 15
  - product: Value/pain 30, Reachability 20, Feasibility 20, Distinctiveness 15, Evidence of demand 15;
    B2B: Value/pain 25, Willingness to pay 20, Reachability 15, Feasibility 20, Distinctiveness 10,
    Evidence of demand 10
  - research: Significance 30, Testability 25, Feasibility 20, Distinctiveness 15, Evidence 10
  - naming: Metaphor strength 30, Memorability 25, Phone test 20, Searchability 15, Distinctiveness 10
    (availability is a hard constraint)
## Kill rules
  K1 a gate (hard constraint, legal, ethics, safety) failed by every screen judge that scored it (at least 2);
  K2 the problem or the insight cannot be stated in one sentence each; K3 any criterion mean <= 1.5 (the human may
  rescue with a reason); K4 prior art CROWDED with no differentiator (the human confirms; not for growth or
  existing-product software ideas); K5 a cheapest test confirms a high-likelihood kill-assumption; K6 the
  pre-registered probe threshold is missed (move to the runner-up). PARK instead of kill when only timing or a soft
  constraint blocks an idea. Keep these unless the user edited them.
## Axes
  3 orthogonal axes with 3-5 values each, in the topic's own words, one line per axis:
  "- <Axis name>: <value> | <value> | <value>". Axes describe the problem space, never solutions.
## Strategy plan
  Copy the STRATEGY PLAN line above.
## Mode, privacy, budget
  The mode, the PRIVACY line above, and the time box.

FORMAT OF criteria.json: one JSON object {"<criterion>": <weight>, ...} with exactly the criterion names of the
Criteria table and the same weights.

OUTPUT RULE
Print the two files in the FILE protocol, then the STATUS block, and nothing else. Allowed paths: {{ALLOWED_FILES}}.
=== FILE: 01_FRAME.md ===
(the frame)
=== END FILE ===
=== FILE: criteria.json ===
(the JSON object)
=== END FILE ===
=== STATUS ===
{"status": "complete", "assumptions": ["each ASSUMED item"],
 "open_questions": ["each question you would have asked, with the default you used"], "reason": ""}
=== END STATUS ===
status is complete, partial (say what is missing in reason) or blocked.
{{OUTPUT_RULE}}
