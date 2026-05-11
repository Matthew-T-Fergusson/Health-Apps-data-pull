# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]
### Added
- README/project framing as an AI-assisted data ops prototype with Streamlit-first visualization direction.
- Public roadmap for collaborative hardening, visualization, and AI automation layers.
- Mermaid architecture diagram in README.
- Multi-version Python CI matrix for 3.11, 3.12, and 3.13.
- Focused tests for QA critical completeness failure logic.
- Makefile and `requirements-dev.txt` for repo-local virtualenv setup and consistent local test commands.
- Isolated Docker Compose/Postgres integration test stack with `.env.test.example`, `make test-integration`, and CI integration job.
- First-class Garmin daily wellness backfill mode with explicit date ranges, conservative pacing, merge-safe writes, parent/per-date job tracking, and value-conflict logging.
- Durable `health.metrics_log` operational metrics path with initial emitters in the orchestrator, Garmin daily sync, and QA.
- Consent/source-lineage framework with `CONSENT.md`, additive consent metadata, and `health.data_lineage` view.
- Data quarantine schema and RUNBOOK recovery decision narratives for duplicate activities, malformed Apple Health rows, manual/device conflicts, stale source data, and schema changes.
- Contributor quickstart polish with `CONTRIBUTING.md` and focused GitHub issue templates.
- Ruff linting and mypy type-checking with local `make quality` targets and CI enforcement.
- Friend-handoff first-run walkthrough in `docs/FIRST_RUN.md` covering live Postgres, Garmin/Strava credential choices, first sync, SQL verification, one-off runs, and troubleshooting.
- Deployment examples in `deploy/` for systemd timers, cron fallback, and log rotation, including simple repo-local vs production-style path tradeoffs.
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
- Replaced manual activity matching magic numbers with named constants and clearer helper variable names.
- Renamed terse scalar-conversion/fetch helpers to descriptive names.
- Path handling made portable (repo-relative/env-driven)
- Added architecture/scope/coverage/limitations docs
- Garmin daily QA now reports placeholder/empty Garmin wellness source days and reload attempts separately from parser/runtime failures.

### Fixed
- Mixed numeric/text Garmin activity ID handling in detail + route sync
- Transaction resilience for per-activity failures
- Garmin daily sync preserves existing non-null wellness values when Garmin temporarily returns all-null placeholder payloads.
