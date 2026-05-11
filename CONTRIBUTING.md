# Contributing

This repo is a working health-data automation prototype. Contributions should make it easier to run, safer to operate, or clearer to review without overstating it as a finished health app.

## First 15 minutes

1. Clone the repo and enter it.
2. Create the repo-local virtualenv:

   ```bash
   make venv
   ```

3. Copy env examples:

   ```bash
   cp .env.example .env
   cp .env.test.example .env.test
   ```

4. Run local checks:

   ```bash
   make test
   ```

5. Run isolated Postgres integration checks:

   ```bash
   make test-integration
   make test-db-down
   ```

If those pass, your local development environment is good enough to start.

## Setup paths

### Docker-first, not Docker-only

Use Docker Compose for the isolated test Postgres. This avoids accidentally touching a local/live health database.

- Test DB host port: `55432`
- Test DB name: `health_ops_test`
- Test DB user: `health_test`
- Guardrails: integration tests require `APP_ENV=test` and refuse default/live DB settings like `PGPORT=5432` or `PGDATABASE=health_ops`.

### Local Python

Use the repo-local virtualenv managed by `make`; do not rely on system Python packages.

```bash
make venv
make test
```

## Branch naming

Use short, descriptive branch names:

- `feature/metrics-log`
- `fix/garmin-null-hrv`
- `docs/lineage-consent`
- `test/backfill-resume`

## Pull request expectations

Before opening a PR, run the smallest meaningful validation set:

```bash
make test
make ci-smoke
make test-integration
make test-db-down
```

In the PR, include:

- what changed
- why the design choice was made
- validation commands and results
- DB/schema impact, if any
- rollback plan

Use `.github/pull_request_template.md`.

## Secrets and private data

Never commit:

- `.env`
- real Garmin/Strava/API credentials
- raw private exports unless explicitly sanitized
- generated artifacts containing private data

Use `.env.example` and `.env.test.example` for shareable configuration shape.

## Data quality rule

Do not describe the pipeline as healthy only because a job ran. For Garmin daily wellness, recent completed days must have user-facing values populated:

- steps
- sleep seconds
- resting HR
- HRV
- stress
- body battery

If these are missing, report a data-completeness failure even if sync freshness is OK.

## Schema and migrations

For bootstrap-safe schema additions:

1. Add SQL under `sql/`.
2. Add it to `BOOTSTRAP_SQL_FILES` in `scripts/db_cli.py` if it is part of baseline setup.
3. Add required tables/views to validation/integration tests.
4. Run `make test-integration`.

For existing deployments, prefer additive/idempotent SQL:

- `CREATE TABLE IF NOT EXISTS`
- `CREATE INDEX IF NOT EXISTS`
- `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`
- `CREATE OR REPLACE VIEW`

## Adding a new data source

A full new-source tutorial belongs in `MTF-170`, but the short version is:

1. Define source scope and consent implications in `CONSENT.md`.
2. Add raw storage first, then curated tables/views.
3. Add sync state and metrics emission.
4. Add QA checks for user-facing completeness.
5. Add integration/bootstrap validation.
6. Document recovery and quarantine behavior.

## Issue types to use

Use focused issue templates when possible:

- data quality failure
- new source request
- feature proposal
- bug report

## Style

Keep changes practical and auditable:

- clear function names over cleverness
- source/raw payload preservation when safe
- non-blocking handling for record-level bad data
- documented operational decisions in RUNBOOK/ROADMAP/CONSENT where relevant
