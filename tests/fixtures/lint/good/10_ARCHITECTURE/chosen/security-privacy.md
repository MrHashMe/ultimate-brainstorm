# Security and privacy

## Data classification

| data | class | where |
|---|---|---|
| staff names | personal | C-3 |
| phone numbers | personal, sensitive | C-3, encrypted |
| swap history | internal | C-3 |

## Authentication and authorization

Nurses sign in with the hospital single sign-on. The Swap API checks that a nurse can only post swaps for shifts that
the roster assigns to them, and that a claim comes from a nurse with the same qualification on the same ward. Ward
managers get a separate role that can approve and cancel swaps.

## STRIDE-lite per trust boundary

Between the browser and the API the main threats are spoofing and tampering, handled by single sign-on and signed
session cookies. Between the API and the roster the main threat is information disclosure, handled by a read-only
service account and TLS. Between the API and the SMS gateway the main threat is leaking phone numbers, handled by
sending only a short link and never the shift details.

## Compliance scope

The data stays in the EU and is covered by the hospital's existing data processing agreement with the cloud
provider. A data protection impact assessment is needed before the pilot.
