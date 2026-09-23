# Data model

```mermaid
erDiagram
  NURSE ||--o{ SWAP : posts
  SHIFT ||--o{ SWAP : covers
  NURSE {
    string id PK
    string ward
  }
  SWAP {
    string id PK
    string state
  }
```

## Entities

| entity | fields | owner container | retention | PII |
|---|---|---|---|---|
| NURSE | id, ward, phone | C-3 | while employed | yes |
| SWAP | id, state, shift | C-3 | 2 years | no |
