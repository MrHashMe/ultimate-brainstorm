# Quality scenarios

## Utility tree

- QG1 Availability at night
  - QAS-01 A nurse posts a swap at 03:00 while the roster system is down.
- QG2 Privacy of staff data
  - QAS-02 A ward manager exports a roster.
- QG3 Fast response on phones
  - QAS-03 A nurse opens the board on a weak mobile signal.

## Scenarios

| id | attribute | source | stimulus | artifact | environment | response | response measure | importance | difficulty |
|---|---|---|---|---|---|---|---|---|---|
| QAS-01 | QG1 | nurse | posts a swap | swap service | roster system down | swap is queued | posted within 5 s | H | M |
| QAS-02 | QG2 | manager | exports a roster | export | normal | names are masked | no plain phone numbers | H | L |
| QAS-03 | QG3 | nurse | opens the board | web client | 3G signal | board renders | under 2 s | M | M |
