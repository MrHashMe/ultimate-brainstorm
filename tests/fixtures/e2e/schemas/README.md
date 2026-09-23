# e2e and stub fixtures (B4)

- `schemas/*.schema.json`: B4's transcriptions of the KIT_SPEC 7.4 / 8.4 schemas (and the v1 `bs.py schemas`
  shapes for screen, verdicts and lens). The stub self-tests validate against these and, when present, against B3's
  `skills/ultimate-brainstorm/templates/schemas/`. `quick-probe` and `frame-questions` are not specified in detail by
  the spec; these two files are B4 guesses used only for the stub tests.
- `host/FRAME-GRILL/`: files the e2e answerer writes for the HOST frame-grill step (01_FRAME.md, criteria.json).
- `host-seedleak/FRAME-GRILL/`: the same frame with one seed idea line pasted into the Problem section (E7).
