---
status: proposed
date: 2026-09-23
decision-makers: tech lead
---
# ADR-0002: Use a managed job queue for SMS alerts

## Context and Problem Statement

Alerts must still go out when the SMS gateway is slow, without blocking the swap request.

## Decision Drivers

* QG1 availability at night

## Considered Options

* Managed job queue
* Send the SMS inside the request

## Decision Outcome

Chosen option: "Managed job queue", because retries happen outside the request path.

### Consequences

* Good, because a slow gateway never blocks a swap.
* Bad, because a queue adds one more service to watch (R-002).

### Confirmation

A load test with a slowed SMS stub.

## More Information

See chosen/runtime.md F-2.
