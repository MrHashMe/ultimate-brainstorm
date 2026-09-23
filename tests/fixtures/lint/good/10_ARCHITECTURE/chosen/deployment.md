# Deployment

## Environments

There are two environments: a staging environment that mirrors production with synthetic rosters, and a production
environment in an EU region of a managed cloud provider. Every change goes to staging first and is promoted by a
manual approval after the smoke tests pass.

## Hosting and CI/CD

The Swap API runs as a managed container service with two instances behind a load balancer. The database is a managed
Postgres instance with automatic minor upgrades. The pipeline builds one image per commit, runs the unit tests and the
contract tests against the roster stub, and deploys with a rolling update. Infrastructure is described as code in one
repository so that a new environment can be created from scratch in under an hour.

## Observability

Structured logs go to the provider's log service. Alerts fire when the swap queue is older than ten minutes or when
the error rate passes two percent over five minutes.

## Backup and disaster recovery

Point-in-time recovery is enabled with a recovery point objective of five minutes and a recovery time objective of
one hour. A restore drill runs every quarter.
