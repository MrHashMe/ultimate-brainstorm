# Risks and technical debt

## Risks

| id | risk | likelihood | impact | mitigation | owner | early warning | source |
|---|---|---|---|---|---|---|---|
| R-001 | The roster export is not available | M | H | CSV import as a fallback | tech lead | no API access after 2 weeks | premortem |
| R-002 | SMS costs grow faster than use | L | M | cap SMS per nurse | product owner | cost report | candidate |

## Technical debt

| id | debt | why accepted | payoff trigger |
|---|---|---|---|
| TD-01 | no offline mode | pilot wards have signal | a ward without signal joins |
