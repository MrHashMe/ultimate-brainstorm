# POOL: 6 canonical ideas from 12 raw ideas (IDs and counts computed by bs.py map)

## YIELD

| strategy | family | raw | canonical credited | unique share | only here | duplicate share | saturated |
|---|---|---|---|---|---|---|---|
| G1 | gpt | 1 | 1 | 100% | 0 | 100% | SATURATED |
| H | human | 1 | 1 | 100% | 0 | 100% | SATURATED |
| HP | human | 1 | 1 | 100% | 1 | 0% |  |
| S1 | claude | 1 | 1 | 100% | 0 | 100% | SATURATED |
| S2 | claude | 1 | 1 | 100% | 1 | 0% |  |
| S3 | gpt | 2 | 2 | 100% | 0 | 100% | SATURATED |
| S4 | claude | 2 | 1 | 50% | 1 | 50% | SATURATED |
| S5 | gpt | 2 | 1 | 50% | 1 | 50% | SATURATED |
| X9 | ? | 1 | 1 | 100% | 0 | 100% | SATURATED |

Duplicate share = share of a strategy's raw ideas that are not 'only here'. The saturation stop applies to gap (G*) and reopen (R*) rounds.

## COVERAGE

Axes: Stage x Channel. Cells: 6; covered: 4; empty: 2; single-idea: 3.
Empty cells: onboarding / sms; handover / sms
Single-idea cells: onboarding / app; shift / sms; handover / app
Ideas whose cell does not match the axes: I-005

## HOMOGENIZED

yes: largest cluster 'Scheduling' holds 3/6 = 50% (limit 25%); 4 clusters for 6 canonical ideas (at least 8 needed when ideas >= 40).

## CLUSTERS

### Scheduling (3)
- I-004 Shift swap board [PRIMARY] - Nurses post and claim shifts. Mechanism: A board with / pipes / in text Key: shift-swap-board. Origin: human-mixed. Cell: shift / app. Aliases: S1-01, S3-04, H-02. Siblings: I-003.
- I-005 Gap fill - Fill open shifts fast. Mechanism: Broadcast to qualified staff. Key: gap-fill. Origin: ai-mixed. Cell: weekend / fax. Aliases: G1-01, S3-04, X9-01.
- I-006 SMS nudges - Text reminders for night staff. Mechanism: Scheduled SMS with opt-out. Key: sms-nudges. Origin: gpt. Cell: shift / sms. Aliases: S5-02, S5-03.

### Handover (1)
- I-003 Handover voice notes — café edition [BASELINE] - Record the handover. Mechanism: Voice memos tied to beds. Key: handover-voice. Origin: claude. Cell: handover / app. Aliases: S2-01.

### Onboarding (1)
- I-002 Buddy onboarding - Pair new nurses with a buddy. Mechanism: Matching by ward and shift. Key: buddy-onboarding. Origin: human. Cell: onboarding / app. Aliases: HP-01.

### Wellbeing (1)
- I-001 Quiet room finder - Find a quiet room on break. Mechanism: Room sensors and a map. Key: quiet-room. Origin: claude. Cell: shift / app. Aliases: S4-01, S4-02.

## Warnings

- alias S3-04 appears under two canonical ideas
- prefix X9 not in strategy_family: origin '?'

---

## RE-RUN
none

## LEAK CHECK
clean

