# RUNBOOK

Operational guide for **Health Apps Data Pull** (Garmin + Strava).

## 1) Prerequisites
- Python 3.11+
- PostgreSQL with `health` schema access
- Repo checked out locally
- `.env` created from `.env.example`

## 2) First-time setup
Prefer the repo-local virtualenv managed by `make` so tests do not accidentally run against system Python.

```bash
make venv
```

Equivalent manual setup:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
```

## 3) Local checks
Run the local smoke/test suite through the repo virtualenv:

```bash
make test
```

Run the same unittest smoke path used by CI:

```bash
make ci-smoke
```

Run integration tests against an isolated Docker/Postgres instance:

```bash
make test-integration
make test-db-down
```

Safety notes:
- Integration tests use `.env.test`, copied from `.env.test.example` if missing.
- The test database maps to port `55432`, not default Postgres `5432`.
- Tests refuse to run unless `APP_ENV=test`.
- Tests refuse default/live database settings such as `PGDATABASE=health_ops` or `PGPORT=5432`.

## 4) DB setup/validation
If your project includes `scripts/db_cli.py`:
```bash
.venv/bin/python scripts/db_cli.py bootstrap
.venv/bin/python scripts/db_cli.py migrate
.venv/bin/python scripts/db_cli.py validate
```

## 5) Run a one-shot ingest
```bash
scripts/health_primary_sync_safe.sh
```

## 6) Run QA only
```bash
.venv/bin/python scripts/health_qa_daily.py
```

## 7) Manual activity capture (watch-miss fallback)
```bash
.venv/bin/python scripts/manual_activity_capture.py \
  --start "2026-04-08T15:00:00-04:00" \
  --activity-type treadmill_manual \
  --duration-min 32 \
  --distance-mi 2.1 \
  --calories 280 \
  --notes "Captured from screenshot"
```
- Writes `health.activities_manual_raw`
- Attempts optional auto-link into `health.activity_manual_links` to prevent duplicate counting

## 8) Manual nutrition capture (photo/chat estimates)
```bash
.venv/bin/python scripts/manual_nutrition_capture.py \
  --when "2026-04-08T18:30:00-04:00" \
  --meal-name "Beef bowl" \
  --meal-type dinner \
  --items-json '[{"name":"ground beef","qty":10,"unit":"oz","calories":700,"protein_g":55,"fat_g":50}]' \
  --notes "Captured from photo + estimate"
```
- Writes `health.nutrition_manual_raw` + `health.nutrition_manual_items`
- Rolls up to `health.nutrition_daily_totals`
- Appears in `health.health_daily_combined` when the day exists in `health.daily_metrics`

## 9) Key artifacts to inspect
- `output/garmin_primary_ingest_orchestrator_last_run.json`
- `output/health_primary_sync_last_run.json`
- `output/health_qa_daily_latest.json`

## 10) Common failures + fixes

### Garmin rate-limit / lockout
- Symptom: lockout active or Garmin auth 429
- Action:
  1. wait for cooldown window
  2. run one-shot again
  3. keep schedule conservative (e.g., every 6h)

### Missing env vars
- Symptom: script exits with `Missing ...`
- Action: confirm `.env` values for Garmin/Strava/Postgres

### QA stale/fail
- Symptom: `health_qa_daily.py` exits non-zero
- Action:
  1. inspect `output/health_qa_daily_latest.json`
  2. run one-shot ingest
  3. re-run QA

## 11) Scheduling recommendation
- Use orchestrator wrapper every 6 hours:
  - `scripts/health_primary_sync_safe.sh`
- Keep anti-rate-limit cadence; avoid aggressive retries.
