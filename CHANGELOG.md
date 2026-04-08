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

### Changed
- Path handling made portable (repo-relative/env-driven)
- Added architecture/scope/coverage/limitations docs

### Fixed
- Mixed numeric/text Garmin activity ID handling in detail + route sync
- Transaction resilience for per-activity failures
