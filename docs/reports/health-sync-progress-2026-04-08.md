# Health Sync Progress Report
**Date:** 2026-04-08  
**Owner:** Matt / Lex  
**Scope:** Garmin + Strava primary ingest pipeline, DB freshness, route geometry integrity, cron automation

---

## 1) Executive Summary
Today we restored and validated end-to-end health ingest reliability for the primary Garmin/Strava pipeline.

### Outcome
- ✅ Primary sync wrapper runs end-to-end.
- ✅ Garmin + Strava ingestion passes current QA checks.
- ✅ Readiness/sleep data is current through latest available provider date.
- ✅ Route geometry pipeline remains active and populated.
- ✅ Health cron job is re-enabled for ongoing automated runs.

### Remaining caveat
- No newer activities were returned by Garmin/Strava beyond 2026-03-23 during verification; this appears to be source-data availability (not pipeline failure).

---

## 2) Problem Statement
Pipeline was intermittently failing and freshness checks showed stale domains.

### Primary failure observed
`garmin_activity_details_sync.py` crashed with Postgres bigint-cast errors due to mixed activity ID formats, e.g.:
- numeric IDs (`22274193981`)
- manual/non-numeric IDs (`manual_treadmill_20260323T161224Z_c4a440b9`)

This caused transaction abort behavior and blocked downstream freshness success signals.

### Secondary failure observed
`sync_activity_routes.py` also assumed numeric IDs and failed when encountering non-numeric external activity IDs.

---

## 3) Fixes Applied

### A) `scripts/garmin_activity_details_sync.py`
1. Added filter to avoid bigint-casting non-numeric IDs in initial selection query.
2. Replaced fragile lookup cast with text-safe lookup against external activity ID.
3. Added per-activity savepoint/rollback safety so one bad record does not poison entire transaction.

### B) `scripts/sync_activity_routes.py`
1. Added mixed-ID handling logic.
2. Only performs int() conversion where ID is numeric.
3. Preserves route writes for valid records while safely skipping incompatible casts.

### C) Operational
1. Re-ran full primary wrapper (`health_primary_sync_safe.sh`).
2. Re-ran health QA (`health_qa_daily.py`).
3. Rebuilt route sync and revalidated freshness state.
4. Re-enabled cron job for 6-hour health primary sync cadence.

---

## 4) Validation Evidence

## 4.1 Pipeline / QA status
- QA overall status: **ok**
- Domains passing freshness:
  - strava_daily
  - garmin_daily
  - garmin_activities
  - garmin_activity_details
  - garmin_readiness
  - activity_routes
  - garmin_lifting

## 4.2 Source-level verification (API)
Direct provider checks confirmed latest returned activity timestamps are currently:
- Strava: `2026-03-23T16:29:07Z`
- Garmin: `2026-03-23 16:29:07`

Interpretation: system is synced through current run time; provider accounts returned no newer activity items at test time.

## 4.3 DB verification highlights
- `health.daily_vitals_garmin` latest metric date: `2026-04-07`
- `health.readiness_daily` latest metric date: `2026-04-07`
- Sleep fields present through latest date.
- Route inventory:
  - `health.activity_routes`: 393 rows
  - rows with `route_geojson`: 143
  - deduped routes: 279

---

## 5) Security/Publishing Notes
No hardcoded runtime credentials were required in code for these fixes.

### Runtime auth model
- Credentials are loaded from environment (`~/.openclaw/.env`) at execution time.
- Garmin auth also uses local tokenstore cache under output paths.

### Publish hygiene requirements before pushing repo
- Do **not** commit:
  - `.env`
  - tokenstore files
  - generated outputs/logs containing sensitive context
- Keep `.env.example` placeholders only.
- Run pre-push secret check.

---

## 6) Cron Status
Health cron job updated:
- **Job:** `health-primary-garmin-strava-sync-6h`
- **Enabled:** `true`
- **Schedule:** `20 */6 * * *` (UTC)
- **Payload:** runs `scripts/health_primary_sync_safe.sh` with post-run status summary requirement.

---

## 7) Known Risks / Follow-ups
1. Mixed-ID handling is now robust, but should be covered by explicit regression tests.
2. Step counts in daily vitals currently live in `raw_json` (not normalized top-level column).
3. If expected post-3/23 workouts exist, investigate alternate account/device sync lane.

---

## 8) Recommended Next Actions
1. Add regression tests for mixed numeric/non-numeric activity IDs.
2. Create a normalized analytics view exposing key daily metrics (steps/sleep/readiness) for dashboards.
3. Prepare public repo packaging:
   - sanitized `.gitignore`
   - setup docs
   - architecture overview
   - this report as initial progress artifact.

---

## 9) Artifact References
- `output/garmin_primary_ingest_orchestrator_last_run.json`
- `output/health_qa_daily_latest.json`
- `output/health_primary_sync_last_run.json`
- `scripts/garmin_activity_details_sync.py`
- `scripts/sync_activity_routes.py`
