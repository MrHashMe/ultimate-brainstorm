# Kill, park and stop rules

Criteria and kill rules are fixed in the frame, before any idea exists. The engine applies them from judge outputs,
checks and probe results; the human confirms every kill that rests on a single judgment.

| Rule | Condition | Who confirms | Where |
|---|---|---|---|
| K1 | A gate (hard constraint, legal, ethics, safety) failed by every screen judge that scored the idea, and at least 2 judges scored it | automatic; a single failing judge (or a single scoring judge) only FLAGS, and the human decides (G4, or the flag is shown at G8a/G8b) | screen (`bs.py screen`) |
| K2 | The problem or the key insight cannot be stated in one sentence each (gate g3) | as K1 | screen |
| K3 | Any criterion mean <= 1.5 (after per-judge centering), or every judge scored a criterion 1 | automatic; the human may rescue with a written reason (G4, at most 2 rescues) | screen |
| K4 | Prior art CROWDED (at least 2 named matches with the same actor AND mechanism) and no differentiator | hands-on: the human confirms each kill at G5. guided and full-auto: never killed; the idea is PARKED ("Parked (K4 candidate)" in 04_SHORTLIST.md) and the flag is shown at G8a/G8b | checks |
| K5 | A cheapest test confirms a high-likelihood kill-assumption | the human | red-team, probe |
| K6 | The pre-registered probe threshold is missed (`RESULT: MISSED`) | recorded in 08_DECISION.md; the runner-up (never an idea its own probe killed) becomes the chosen idea; with none, the run stops before the architecture (or, when finished, its documents say so) and the DONE card lists the finalists to switch to (`switch --idea` refuses an idea K6 killed; the K6 lines a kit 2.0.3 run wrote count too) | probe |
| Park | Blocked only by timing or a soft constraint | record a revisit trigger | any stage |
| Whole effort | The frame's kill condition for the whole effort is met, or every finalist fails the same premise (SYNTHESIS ends `WHOLE-EFFORT: STOP`) | the human, at GX (always asked, even in full-auto): reframe, continue or stop | red-team |

Notes:
- K4 does not apply to growth ideas or to software ideas that extend an existing product: there prior art is evidence
  the idea works (record the reported lift and its source). The question becomes "does OUR product already do this?"
  (file:line); kill only if it already shipped and was measured.
- Research variant: CROWDED needs named papers that already contain the result; crowded ground with a stated delta is
  not CROWDED.
- Product variant: CROWDED needs named products for the same user through the same channel.
- With privacy `web` off, checks return NOT CHECKED, which can never trigger K4.
- `RESULT: INCONCLUSIVE` is never a pass: extend the test or run the qualitative test. Without `RESULT: PASSED` the
  handoff card warns "riskiest assumption untested", and the handoff seed carries the warning.
- Nothing is dropped before the curator except exact duplicates. Tools' rejected ideas (for example ce-ideate's raw
  candidates) enter the pool as PARKED ideas.
- Parked and killed ideas go to `brainstorm/LEDGER.md` with their rule and revive trigger; later runs see their titles
  only as "previously considered" in gap rounds.
