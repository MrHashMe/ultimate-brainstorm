# Context

## System context

The swap app sits between nurses, the hospital rostering system and an SMS gateway.

```mermaid
C4Context
  title Shift swap board
  Person(nurse, "Nurse", "Works night shifts")
  System(app, "Swap app", "Shift swap board")
  System_Ext(roster, "Rostering system", "EXT-1")
  System_Ext(sms, "SMS gateway", "EXT-2")
  Rel(nurse, app, "Posts and claims swaps")
  Rel(app, roster, "Reads shifts")
  Rel(app, sms, "Sends alerts")
```

```mermaid
flowchart LR
  nurse[Nurse] --> app[Swap app]
  app --> roster[EXT-1 Rostering system]
  app --> sms[EXT-2 SMS gateway]
```

## Actors

- ACT-1 Nurse: works night shifts.

## External systems

| id | name | description | relationship |
|---|---|---|---|
| EXT-1 | Rostering system | Hospital roster | reads shifts |
| EXT-2 | SMS gateway | Sends texts | sends alerts |
