# Architecture: shift swap board

## Summary

A modular monolith on managed services. The chosen candidate is A. It meets QG1 with a managed database and a
retrying job queue, QG2 with field-level encryption, and QG3 with a thin mobile web client.

## Alternatives considered

Candidate B (event-driven) scored lower on operational simplicity. See tradeoff-matrix.md.

## Decision index

| ADR | title | status |
|---|---|---|
| [ADR-0001](adr/0001-use-postgres.md) | Use a managed Postgres database | proposed |
| [ADR-0002](adr/0002-job-queue.md) | Use a managed job queue for SMS alerts | proposed |

## Provenance

Authors and judges are listed in the run record.
