# Containers

## Containers

```mermaid
C4Container
  title Swap app containers
  Person(nurse, "Nurse")
  Container(web, "Web client", "HTML", "C-1")
  Container(api, "Swap API", "Python", "C-2")
  ContainerDb(db, "Database", "Postgres", "C-3")
  System_Ext(roster, "Rostering system", "EXT-1")
  System_Ext(sms, "SMS gateway", "EXT-2")
  Rel(nurse, web, "Uses")
  Rel(web, api, "JSON over HTTPS")
  Rel(api, db, "SQL")
  Rel(api, roster, "Reads shifts")
  Rel(api, sms, "Sends alerts")
```

```mermaid
flowchart LR
  subgraph Swap app
    web[C-1 Web client] --> api[C-2 Swap API]
    api --> db[(C-3 Database)]
  end
  api --> roster[EXT-1 Rostering system]
  api --> sms[EXT-2 SMS gateway]
```

| id | name | technology | responsibility | data owned | interface |
|---|---|---|---|---|---|
| C-1 | Web client | HTML and a small script | shows the board | none | HTTPS |
| C-2 | Swap API | Python service | swap rules, alerts | none | JSON API |
| C-3 | Database | managed Postgres | swaps, staff | swaps, staff | SQL |

External systems: EXT-1 rostering system (read only), EXT-2 SMS gateway.

## How each quality goal is met

| QG | mechanism | containers | QAS | expected response |
|---|---|---|---|---|
| QG1 | queue swaps when the roster is down | C-2, C-3 | QAS-01 | posted within 5 s |
| QG2 | field-level encryption of phone numbers | C-3 | QAS-02 | no plain numbers |
| QG3 | server-rendered pages | C-1 | QAS-03 | under 2 s |
