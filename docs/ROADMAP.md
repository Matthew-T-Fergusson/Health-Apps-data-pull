# Roadmap

This repo is an active work-in-progress. The near-term goal is not to claim a finished health app; it is to turn a real personal-data automation pipeline into a clean, reproducible, reviewable AI-assisted data ops prototype.

## Collaboration framing

The project is intended to be useful for collaborative review and extension:

- Reliable ingestion from imperfect third-party APIs and exports
- Raw + curated PostgreSQL data model
- QA gates that fail on user-facing data completeness, not just job success
- Recovery/backfill workflows for upstream outages
- Metrics and operational visibility
- Visualization layer that starts streamlined, then iterates toward a fuller platform-style construction
- Future AI automation layer for interpreting status, proposing fixes, and guiding onboarding workflows

## Current state

Implemented:

- Garmin daily wellness/activity/readiness/lifting ingestion
- Strava daily activity ingestion
- Apple Health export import fallback
- Manual activity capture fallback
- Manual nutrition capture fallback
- PostgreSQL schema/migration helpers
- Orchestrator with Garmin lockout handling
- QA checks for freshness, completeness, and missing critical wellness metrics
- Local status/run artifacts

Known gaps:

- Integration tests are still light; most tests are unit/helper-level today
- Backfill is currently lookback-window based, not a first-class resumable job system
- Metrics are mostly file/QA-artifact based, not yet emitted to a durable metrics table
- Visualization/dashboard layer is planned but not implemented

## Phase 1 — Shareable collaborative WIP

Goal: make the repo clean enough for technical friends/reviewers to understand, run, and contribute to without misreading it as finished product.

- [x] Add README architecture diagram
- [x] Add multi-version Python CI matrix
- [x] Name magic numbers and clean matching helper names
- [x] Add focused tests for QA completeness failure logic
- [ ] Confirm fresh-clone setup path and publish checklist

## Phase 2 — Strong-candidate foundation

Goal: demonstrate that the pipeline is implementable against real infrastructure and operable through failures.

- [ ] Add Docker Compose + Postgres integration test suite
- [ ] Add first-class backfill mode with `--since`, `--until`, and `--mode incremental|backfill`
- [ ] Add `health.backfill_jobs` tracking table
- [ ] Add durable metrics emission via `health.metrics_log`
- [ ] Instrument row counts, durations, 429s, and QA status

## Phase 3 — Senior-reviewer hardening

Goal: make the engineering judgment obvious to reviewers who care about maintainability, observability, and failure semantics.

- [ ] Add ruff and mypy to CI
- [ ] Add raw JSON schema drift detection
- [ ] Add retriable/fatal error taxonomy
- [ ] Add dead-letter table for repeated record-level failures

## Phase 4 — Visualization and AI automation layer

Goal: turn the pipeline into an end-to-end automation + decision-support system.

Visualization approach:

1. Start streamlined, likely with Streamlit, so the useful views can be built quickly and tested against real usage.
2. Iterate toward a more platform-style construction once the dashboard semantics are clear.
3. Use the progression deliberately to compare fast prototype dashboards with more durable product/data-platform patterns.

Candidate features:

- Health/training dashboard over `health.health_daily_combined`
- Data quality dashboard showing freshness, nulls, source gaps, and QA status
- Backfill/recovery dashboard showing historical gaps and job progress
- AI assistant workflows that summarize pipeline health, explain failures, and propose next remediation steps
- Client-onboarding-style demo flow: connect source, ingest, validate, detect issue, recover, visualize

## What feedback would be valuable

- Which dashboard views would make the system easiest to understand quickly?
- Which onboarding/automation workflow would best demonstrate client-facing AI POC skills?
- Are the schema boundaries clear enough between raw, curated, manual fallback, QA, and metrics?
- What would make this feel more reusable outside one personal health-data use case?
