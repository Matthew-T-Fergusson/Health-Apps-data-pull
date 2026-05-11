# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]
### Added
- RUNBOOK with setup/run/QA/recovery operations
- requirements.txt for reproducible environment setup
- bootstrap helper script (`scripts/bootstrap.sh`)
- PR template for consistent change documentation
- Manual activity pipeline:
  - `scripts/manual_activity_capture.py`
  - `sql/health_manual_activity_tables.sql`
  - `health.activities_manual_raw` + `health.activity_manual_links`
  - `health.activities_unified_with_manual` view
- Manual nutrition pipeline:
  - `scripts/manual_nutrition_capture.py`
  - `sql/health_manual_nutrition_tables.sql`
  - `health.nutrition_manual_raw` + `health.nutrition_manual_items`
  - `health.nutrition_daily_totals` + `health.health_daily_combined` views
- Apple Health export fallback/import helpers:
  - `scripts/apple_health_phase1_import.py`
  - `scripts/apple_health_fetch_and_import.sh`
- Operational helpers that were missing from the published repo:
  - `scripts/health_pipeline_status.py`
  - `scripts/garmin_smoke_test.py`
  - `scripts/rebuild_activity_matches.py`
  - `scripts/sync_strava_raw_from_core.py`
  - `sql/health_weight_trend_view.sql`
- Health ingest and nutrition-imputation docs.

### Changed
- Path handling made portable (repo-relative/env-driven)
- Added architecture/scope/coverage/limitations docs
- Garmin daily QA now reports placeholder/empty Garmin wellness source days and reload attempts separately from parser/runtime failures.

### Fixed
- Mixed numeric/text Garmin activity ID handling in detail + route sync
- Transaction resilience for per-activity failures
- Garmin daily sync preserves existing non-null wellness values when Garmin temporarily returns all-null placeholder payloads.
