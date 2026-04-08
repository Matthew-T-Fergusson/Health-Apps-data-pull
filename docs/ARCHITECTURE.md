# Architecture

## Flow
1. Source APIs (Garmin, Strava)
2. Ingest workers write raw + curated tables in Postgres (`health.*`)
3. Route builder derives GeoJSON and bounding boxes (`health.activity_routes`)
4. QA pass computes freshness/coverage/null-rate checks (`health_qa_daily.py`)
5. Artifacts written to `output/*.json` for cron/ops visibility

## Core scripts
- `scripts/garmin_primary_ingest_orchestrator.py` — orchestrates all steps and lockout logic
- `scripts/garmin_activity_details_sync.py` — activity-level enrichment (laps/splits/weather/zones/training)
- `scripts/sync_activity_routes.py` — route geometry extraction + upsert
- `scripts/health_qa_daily.py` — QA + status artifact

## Reliability controls
- Garmin SSO rate-limit lockout persistence
- Per-step status capture in orchestrator artifacts
- Transaction savepoint behavior in detail sync to isolate bad records
- Mixed-ID handling for numeric + manual activity IDs
