# Health Ingest Runbook

## Deploy
1. Configure `.env` from `.env.example`.
2. Run `python3 scripts/db_cli.py bootstrap`.
3. Run `python3 scripts/db_cli.py migrate`.
4. Run `python3 scripts/db_cli.py validate`.
5. Execute: `scripts/health_primary_sync_safe.sh`.

## Scheduling
Use conservative cadence for Garmin (recommended 2-4 runs/day). Avoid aggressive retries.

## Failure classes
- Garmin 429: orchestrator opens lockout circuit and skips Garmin pulls.
- Auth/config failure: non-zero exit; fix env and rerun.
- QA fail: freshness/coverage issue, investigate source sync states.

## Key artifacts
- `output/garmin_primary_ingest_orchestrator_last_run.json`
- `output/health_primary_sync_last_run.json` (compat)
- `output/health_qa_daily_latest.json`
- `output/garmin/lockout_state.json`

## Recovery
1. Fix credentials/rate-limit conditions.
2. Wait for lockout expiration or clear lockout file intentionally.
3. Run orchestrator once manually before re-enabling scheduler.
