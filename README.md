# Athlete Ingest (Garmin + Strava)

Production-oriented ingestion pipeline for Garmin and Strava health/activity data into a private PostgreSQL store.

## Goals
- Private data ownership
- Resilient ingestion with rate-limit handling
- Raw + curated storage model
- Open-source deployability (no hardcoded local secrets)

## Scope statement
This project currently provides **core Garmin + Strava ingestion** with production-oriented reliability controls.
It should not yet be represented as complete "all datapoints" parity for every source endpoint.
See:
- `docs/DATA_COVERAGE_MATRIX.md`
- `docs/KNOWN_LIMITATIONS.md`
- `docs/SUPPORT_SCOPE.md`

## Quickstart
1. Create virtualenv and install deps.
2. Copy `.env.example` to `.env` and set credentials.
3. Bootstrap + migrate DB schema:
   - `python3 scripts/db_cli.py bootstrap`
   - `python3 scripts/db_cli.py migrate`
4. Validate DB readiness:
   - `python3 scripts/db_cli.py validate`
5. Run one-shot ingest:
   - `scripts/health_primary_sync_safe.sh`
6. Inspect artifacts:
   - `output/garmin_primary_ingest_orchestrator_last_run.json`
   - `output/health_qa_daily_latest.json`

## Architecture (high level)
- Orchestrator: `scripts/garmin_primary_ingest_orchestrator.py`
- Source workers: `scripts/garmin_*_sync.py`, `scripts/strava_daily_sync.py`
- QA: `scripts/health_qa_daily.py`
- SQL schema: `sql/*.sql`

## Operational behavior
- Circuit breaker on Garmin SSO 429
- Cooldown lockout persistence
- Structured run artifact output
- QA still runs when Garmin is lockout-skipped

## Security
- No credentials in source code.
- Use env vars + `.env` only.
- Do not commit `.env`.

## Community note
Garmin access uses community libraries against Garmin Connect endpoints (not a public official Garmin API product). Expect occasional auth/rate-limit variability and use conservative scheduling.

## Security and support docs
- `docs/SECURITY.md`
- `docs/SUPPORT_SCOPE.md`
- `docs/KNOWN_LIMITATIONS.md`

## Latest progress report
- `docs/reports/health-sync-progress-2026-04-08.md`
