<!-- ub-template: EVOLVE v1 kind=generator -->
Do not load or invoke any skill; this prompt is the whole task.
STAGE 8 - EVOLVE. You see the surviving shortlist entries and their checks below. Propose NEW ideas; never edit the
originals. Read no files and run no commands. Mode: {{MODE}}. Language: {{LANG}}.
- E-01, E-02: hybrids that combine the mechanisms of two surviving ideas from DIFFERENT clusters (name both parents).
- E-03: simplification - what stays valuable if the strongest idea loses half its scope?
- E-04: repair - redesign one idea around its most likely kill-assumption (name it); no new modules.
- E-05 (deep mode only): the same user outcome as the strongest idea, reached through a completely different
  mechanism.

BRIEF
{{BRIEF}}

AXES
{{AXES}}

SURVIVORS AND THEIR CHECKS
{{SURVIVORS}}

OUTPUT FORMAT (one block per idea)
### E-NN <title, max 8 words>
- Pitch: <one sentence>
- Mechanism: <1-2 sentences>
- For whom / when: <who, in which situation>
- Basis: direct:<fact> | external:<URL> | reasoned:<one-line argument>
- Cell: <one value per axis>
- Fails if: <the most likely way it dies, one line>
- Parents: <IDs>

OUTPUT RULE
Print the E-01 to E-04 blocks (deep mode: also E-05), and nothing else.
{{OUTPUT_RULE}}
