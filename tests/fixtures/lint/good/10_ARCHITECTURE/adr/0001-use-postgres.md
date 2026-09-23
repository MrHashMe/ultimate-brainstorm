---
status: proposed
date: 2026-09-23
decision-makers: tech lead
---
# ADR-0001: Use a managed Postgres database

## Context and Problem Statement

Swaps and staff records need durable storage in the EU with point-in-time recovery.

## Decision Drivers

* QG1 availability at night
* QG2 privacy of staff data

## Considered Options

* Managed Postgres
* A document database
* The hospital's existing SQL server

## Decision Outcome

Chosen option: "Managed Postgres", because it gives point-in-time recovery and field encryption with no operations work.

### Consequences

* Good, because backups and failover are managed.
* Bad, because the roster import still depends on an export we do not control (R-001).

### Confirmation

A restore drill in staging before the pilot.

## More Information

See chosen/data-model.md.
