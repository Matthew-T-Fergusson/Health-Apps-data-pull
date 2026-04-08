# RUNBOOK

Operational guide for **Health Apps Data Pull** (Garmin + Strava).

## 1) Prerequisites
- Python 3.11+
- PostgreSQL with `health` schema access
- Repo checked out locally
- `.env` created from `.env.example`

## 2) First-time setup
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 3) DB setup/validation
If your project includes `scripts/db_cli.py`:
```bash
python3 scripts/db_cli.py bootstrap
python3 scripts/db_cli.py migrate
python3 scripts/db_cli.py validate
```

## 4) Run a one-shot ingest
```bash
scripts/health_primary_sync_safe.sh
```

## 5) Run QA only
```bash
python3 scripts/health_qa_daily.py
```

## 6) Manual activity capture (watch-miss fallback)
```bash
python3 scripts/manual_activity_capture.py \
  --start "2026-04-08T15:00:00-04:00" \
  --activity-type treadmill_manual \
  --duration-min 32 \
  --distance-mi 2.1 \
  --calories 280 \
  --notes "Captured from screenshot"
```
- Writes `health.activities_manual_raw`
- Attempts optional auto-link into `health.activity_manual_links` to prevent duplicate counting

## 7) Key artifacts to inspect
- `output/garmin_primary_ingest_orchestrator_last_run.json`
- `output/health_primary_sync_last_run.json`
- `output/health_qa_daily_latest.json`

## 7) Common failures + fixes

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

## 8) Scheduling recommendation
- Use orchestrator wrapper every 6 hours:
  - `scripts/health_primary_sync_safe.sh`
- Keep anti-rate-limit cadence; avoid aggressive retries.
