# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]
### Added
- RUNBOOK with setup/run/QA/recovery operations
- requirements.txt for reproducible environment setup
- bootstrap helper script (`scripts/bootstrap.sh`)
- PR template for consistent change documentation

### Changed
- Path handling made portable (repo-relative/env-driven)
- Added architecture/scope/coverage/limitations docs

### Fixed
- Mixed numeric/text Garmin activity ID handling in detail + route sync
- Transaction resilience for per-activity failures
