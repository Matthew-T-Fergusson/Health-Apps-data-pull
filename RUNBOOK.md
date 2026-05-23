# RUNBOOK

Operational guide for the **Personal Health Data Platform** (Garmin, Strava, Apple Health, manual activity, and manual nutrition).

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

## 3a) Contributor quickstart
For a first-time contributor/reviewer, the intended path is Docker-first but not Docker-only:

```bash
make venv
cp .env.example .env
cp .env.test.example .env.test
make test
make test-integration
make test-db-down
```

Use `CONTRIBUTING.md` for branch naming, PR expectations, issue template guidance, schema rules, and the short “new data source” checklist.

For a first-time live install against your own Garmin/Strava data, use `docs/FIRST_RUN.md`. It walks through Postgres setup, source credential choices, a small recent-window first sync, SQL verification, and the common auth/env/Postgres failure modes.

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

Daily scheduling examples live in `deploy/`:

- `deploy/health-sync.service` + `deploy/health-sync.timer` — recommended long-running Linux/systemd path.
- `deploy/crontab.example` — simpler cron fallback.
- `deploy/logrotate.conf.example` — weekly rotation for repo-local logs.

Use daily scheduling for normal operation and manual one-off runs after workouts when immediate data is useful.

## 6) Run QA only
```bash
.venv/bin/python scripts/health_qa_daily.py
```

## 6a) Inspect durable metrics
Key emitters write operational metrics to `health.metrics_log` without making metrics failures block ingestion by default.

Initial emitters:
- `garmin_primary_ingest_orchestrator.py`: run status/duration, step status/duration, Garmin lockout/429 signals
- `garmin_daily_sync.py`: dates attempted/ok, critical missing days, errors, backfill success/empty/failed counts
- `health_qa_daily.py`: QA status, issue count, critical missing days, Garmin source-empty days

Recent pipeline metrics:

```sql
SELECT observed_at, source, metric_name, metric_value, metric_text, status, tags
FROM health.metrics_log
ORDER BY observed_at DESC
LIMIT 50;
```

Latest critical completeness signal:

```sql
SELECT observed_at, metric_value AS critical_missing_days, status, meta
FROM health.metrics_log
WHERE source='health_qa_daily' AND metric_name='critical_missing_days'
ORDER BY observed_at DESC
LIMIT 10;
```

Safety behavior:
- Metrics use one flexible table: `metric_name`, numeric/text value, source, run_id, status, tags, meta.
- Metrics write failures warn to stderr and do not break ingestion unless `HEALTH_METRICS_STRICT=1`.

## 6b) Inspect source lineage / consent metadata
The repo uses consent version `health-consent-2026-05-11` for current source integrations. See `CONSENT.md` for source-by-source scope, disable paths, and purge design.

Inspect recent lineage:

```sql
SELECT metric_date, source_system, metric_name, metric_value, pulled_at, consent_version, storage_table
FROM health.data_lineage
WHERE metric_date >= current_date - interval '7 day'
ORDER BY metric_date DESC, source_system, metric_name;
```

Use this view to answer: “Where did this metric come from, when was it pulled, and what consent version applies?”

Revocation vs purge:
- Revocation = stop future collection from a source by disabling credentials/schedules.
- Purge = remove/tombstone already-stored source data. Destructive purge is intentionally deferred to `MTF-168` and should start with a dry-run/table-count report.

## 7) Garmin daily wellness backfill / outage recovery
Use first-class backfill mode when Garmin returns empty/placeholder wellness data for completed days, or after an upstream outage.

Example conservative recovery run:

```bash
.venv/bin/python scripts/garmin_daily_sync.py \
  --mode backfill \
  --since 2026-05-01 \
  --until 2026-05-05 \
  --delay-seconds 3
```

Safety behavior:
- Backfill requires an explicit `--since` and `--until` range.
- `--until` cannot be in the future.
- Backfill defaults to max 31 days unless `--max-days` is raised intentionally.
- Writes use **merge-safe** policy: fill missing values, preserve existing non-null values, and record value conflicts instead of blindly overwriting.
- Job audit tables:
  - `health.backfill_jobs` — parent job/status/range/write policy
  - `health.backfill_job_dates` — one row per attempted date with success/empty/failed status
- `health.backfill_value_conflicts` — old/new value conflicts and the kept-existing decision
- Resume behavior: `--resume-job-id <job_id>` retries only dates from that job that are not already `success` or `skipped`.

Inspect recent backfill status:

```sql
SELECT *
FROM health.backfill_jobs
ORDER BY started_at DESC
LIMIT 5;

SELECT metric_date, status, rows_written, conflict_count, error_message
FROM health.backfill_job_dates
WHERE job_id = <job_id>
ORDER BY metric_date;
```

Resume a partial job:

```bash
.venv/bin/python scripts/garmin_daily_sync.py \
  --mode backfill \
  --since 2026-05-01 \
  --until 2026-05-05 \
  --resume-job-id <job_id> \
  --delay-seconds 3
```

Operational playbook for “Garmin was blank for 3 days”:
1. Confirm failing dates in QA output or `health.daily_metrics`.
2. Run `garmin_daily_sync.py --mode backfill --since <first_blank_day> --until <last_blank_day> --delay-seconds 3`.
3. Inspect `health.backfill_job_dates` for `empty_payload` or `failed` dates.
4. Re-run QA. If values remain missing, treat as upstream/source-data failure rather than job success.

## 7a) Data quarantine and recovery decision narratives
Use `health.data_quarantine` for records that fail validation but should not block the entire pipeline. Quarantine is for **operator/AI-agent decisioning**, not silent deletion.

Inspect open quarantine items:

```sql
SELECT quarantine_id, source_system, entity_type, entity_id, metric_date,
       detection_signal, severity, recommended_action, reason, created_at
FROM health.data_quarantine_open;
```

Insert pattern for a non-blocking bad record:

```sql
INSERT INTO health.data_quarantine (
  source_system, entity_type, entity_id, metric_date,
  detection_signal, severity, reason, recommended_action, raw_payload, evidence
) VALUES (
  'apple_health', 'daily_export_record', 'export-row-123', DATE '2026-05-01',
  'validation_failed', 'warn', 'Malformed duration field; skipped from daily rollup',
  'review', '{"example":"payload"}'::jsonb, '{"parser":"apple_health_phase1_import.py"}'::jsonb
);
```

Decision tree: duplicate Strava/Garmin activities
- Detection signal: same start time/duration/distance window, or `activity_matches` conflict.
- Automated response: preserve raw Garmin and Strava rows; create/keep one match if confidence is high; quarantine ambiguous duplicates with `recommended_action='merge'`.
- Escalation path: operator reviews route/evidence and sets quarantine `status='resolved'` with notes.
- Audit evidence: `health.activity_matches`, source raw tables, `health.data_quarantine`.

Decision tree: malformed Apple Health export rows
- Detection signal: XML parse error, unsupported unit, impossible negative duration, or missing required timestamp.
- Automated response: skip the malformed record, continue import, quarantine the raw/evidence snapshot with `recommended_action='review'` or `fix_source`.
- Escalation path: if many rows fail, stop treating it as isolated bad data and escalate the export/import format.
- Audit evidence: `health.apple_health_daily` aggregate counts, import logs, `health.data_quarantine`.

Decision tree: manual-vs-device activity conflict
- Detection signal: manual activity overlaps Garmin/Strava device activity but differs materially in distance/duration/calories.
- Automated response: do not double-count; keep manual record unlinked or link with low confidence; quarantine the conflict with `recommended_action='merge'`.
- Escalation path: operator chooses device value, manual correction, or ignored duplicate and records resolution notes.
- Audit evidence: `health.activities_manual_raw`, `health.activity_manual_links`, `health.activities_unified_with_manual`, `health.data_quarantine`.

Decision tree: stale data after long source outage
- Detection signal: QA freshness failure, critical missing days, Garmin lockout/429 metrics, or source-empty wellness payloads.
- Automated response: do not mark pipeline healthy based only on job freshness; run conservative backfill for the missing date range.
- Escalation path: if backfill returns `empty_payload` or repeated failures, leave source issue open and escalate as upstream/source availability.
- Audit evidence: `health.metrics_log`, `health.backfill_jobs`, `health.backfill_job_dates`, `health.data_quarantine` for repeated unresolved source failures.

Decision tree: schema changes mid-sync
- Detection signal: parser/key errors, raw JSON schema drift, missing expected fields, or sudden null-rate increase.
- Automated response: preserve raw payload where safe, quarantine affected records with `recommended_action='fix_source'`, and continue unaffected records.
- Escalation path: update parser/schema baseline, add regression test, resolve quarantine rows after reprocessing/backfill.
- Audit evidence: raw source tables, future schema-drift output, `health.data_quarantine`, tests/commit history.

## 8) Manual activity capture (watch-miss fallback)
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

## 9) Manual nutrition capture (photo/chat estimates)
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

## 10) Key artifacts to inspect
- `output/garmin_primary_ingest_orchestrator_last_run.json`
- `output/health_primary_sync_last_run.json`
- `output/health_qa_daily_latest.json`

## 11) Common failures + fixes

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

## 12) Scheduling recommendation
- Use orchestrator wrapper every 6 hours:
  - `scripts/health_primary_sync_safe.sh`
- Keep anti-rate-limit cadence; avoid aggressive retries.
