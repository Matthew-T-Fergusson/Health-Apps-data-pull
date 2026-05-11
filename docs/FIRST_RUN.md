# First Run: Clone, Configure, and Sync Your Own Data

Audience: a technical friend/collaborator cloning this repo and running it against their own Garmin and/or Strava data.

Goal: get from a clean clone to a verified first sync in under two hours, without needing Matthew to explain the setup live.

This is not a one-click consumer app. It is a personal data pipeline: you will create a local Python environment, point it at PostgreSQL, add your own credentials, bootstrap the schema, run a small first sync, and verify rows landed.

## Prerequisites

Required:

- Git
- Python 3.11+
- Terminal comfort
- PostgreSQL 15+ for your live data store
- A Garmin Connect account and/or a Strava account

Recommended:

- Docker + Docker Compose for the easiest local PostgreSQL path
- A password manager for `.env` values
- A private machine/account. Do not run this with credentials on a shared box unless you understand the security tradeoffs.

## Step 0: Clone and create the Python environment

```bash
git clone https://github.com/Matthew-T-Fergusson/Health-Apps-data-pull.git
cd Health-Apps-data-pull
make venv
cp .env.example .env
```

Keep `.env` private. It is intentionally ignored by git.

Run the local checks before touching live data:

```bash
make test
make quality
```

Optional but recommended: run isolated integration tests against the repo's disposable Postgres container:

```bash
cp .env.test.example .env.test
make test-integration
make test-db-down
```

These tests use `APP_ENV=test`, database name `health_ops_test`, and host port `55432` so they do not touch your live database.

## Step 1: Pick your live PostgreSQL setup

The friend/default path is Docker-first because it is easiest to reproduce. Local PostgreSQL is also fine if you already manage Postgres yourself.

### Option A: Docker-first live Postgres

Create a live Postgres container outside the integration-test stack:

```bash
docker volume create health_ops_pgdata

docker run -d \
  --name health-ops-postgres \
  -e POSTGRES_DB=health_ops \
  -e POSTGRES_USER=lex \
  -e POSTGRES_PASSWORD='replace-with-a-real-password' \
  -p 5432:5432 \
  -v health_ops_pgdata:/var/lib/postgresql/data \
  postgres:15
```

Then set these in `.env`:

```dotenv
APP_ENV=production
WORKSPACE_DIR=/absolute/path/to/Health-Apps-data-pull
PGHOST=127.0.0.1
PGPORT=5432
PGDATABASE=health_ops
PGUSER=lex
PGPASSWORD=replace-with-a-real-password
```

### Option B: Local Postgres install

If you already run PostgreSQL locally, create a database and user similar to:

```sql
CREATE DATABASE health_ops;
CREATE USER lex WITH PASSWORD 'replace-with-a-real-password';
GRANT ALL PRIVILEGES ON DATABASE health_ops TO lex;
```

On some installs, you may also need to connect to `health_ops` as an admin and grant schema creation rights:

```sql
GRANT CREATE ON DATABASE health_ops TO lex;
```

Then use the same `.env` fields shown above, adjusted for your host/port/user.

## Step 2: Choose source setup: Garmin, Strava, or both

You can start with either source or both. Choose the path that matches what you care about first.

| Choice | Best for | Setup friction | Notes |
| --- | --- | --- | --- |
| Garmin only | Daily wellness metrics, sleep, HRV, stress, body battery, Garmin activities | Medium | Uses community Garmin Connect access; avoid repeated login attempts. |
| Strava only | Workout/activity history from Strava | Medium/high | Requires a Strava API app and OAuth refresh token. |
| Garmin + Strava | Richest data coverage and cross-source activity matching | Highest | Best long-term, but more setup on day one. |

A practical day-one path is: configure one source, prove the pipeline works, then add the other.

## Step 3: Configure Garmin credentials

In `.env`:

```dotenv
GARMIN_EMAIL=your-garmin-email@example.com
GARMIN_PASSWORD=your-garmin-password
GARMIN_TOKENSTORE_DIR=./output/garmin/tokenstore
GARMIN_LOCKOUT_STATE_PATH=./output/garmin/lockout_state.json
GARMIN_LOCKOUT_COOLDOWN_SECONDS=43200
GARMIN_SYNC_DAYS=7
GARMIN_ACTIVITY_LOOKBACK_DAYS=14
GARMIN_ACTIVITY_DETAIL_LOOKBACK_DAYS=14
GARMIN_READINESS_DAYS=14
```

The first Garmin run seeds a local tokenstore under `output/garmin/tokenstore`. After that, the pipeline prefers tokenstore login and avoids repeated full SSO logins.

### Garmin 429 / lockout warning

Garmin Connect does not provide a stable public API for this use case. The community login flow can hit rate limits or SSO lockouts, especially if you retry many times quickly.

If you hit a 429 or lockout on first setup:

1. Stop retrying.
2. Wait for the cooldown shown in `output/garmin/lockout_state.json`, or wait 12 hours if unsure.
3. Confirm your `.env` values are correct before trying again.
4. Run one controlled attempt, not a loop.

## Step 4: Configure Strava credentials

If you are not using Strava yet, leave the `STRAVA_*` values as placeholders and run Garmin-only commands below.

If you want Strava on day one:

1. Go to the Strava API/developer settings page while logged into your Strava account.
2. Create an app.
3. Copy the app's client ID and client secret into `.env`:

```dotenv
STRAVA_CLIENT_ID=your-client-id
STRAVA_CLIENT_SECRET=your-client-secret
```

4. Generate an initial refresh token for your account. The exact OAuth flow can change, but the high-level process is:
   - authorize your app for your own account
   - include activity read scope such as `activity:read_all` if you need private activities
   - exchange the authorization code for access/refresh tokens
   - copy the returned refresh token into `.env`

```dotenv
STRAVA_REFRESH_TOKEN=your-refresh-token
STRAVA_TOKEN_EXPIRES_AT=
```

The Strava sync updates `STRAVA_REFRESH_TOKEN` and `STRAVA_TOKEN_EXPIRES_AT` in `.env` after token refresh.

## Step 5: Bootstrap and validate the database

```bash
.venv/bin/python scripts/db_cli.py bootstrap
.venv/bin/python scripts/db_cli.py migrate
.venv/bin/python scripts/db_cli.py validate
```

Expected result: validation exits successfully and reports that required health schema objects exist.

If validation fails, fix that before running source syncs. The orchestrator also runs validation as a preflight and refuses to ingest when the DB is not ready.

## Step 6: Run a small first sync

Use a short recent window first. Do not begin with a huge historical backfill.

### Garmin-only first run

```bash
.venv/bin/python scripts/garmin_primary_ingest_orchestrator.py \
  --workspace "$PWD" \
  --env-file "$PWD/.env"
```

### Garmin + Strava first run

```bash
.venv/bin/python scripts/garmin_primary_ingest_orchestrator.py \
  --workspace "$PWD" \
  --env-file "$PWD/.env" \
  --with-strava
```

### Strava-only first run

There is not currently a Strava-only orchestrator mode, but you can run the Strava worker directly after bootstrap/validate:

```bash
.venv/bin/python scripts/strava_daily_sync.py
.venv/bin/python scripts/health_qa_daily.py
```

The friend/default wrapper is:

```bash
scripts/health_primary_sync_safe.sh
```

That wrapper routes through the orchestrator and includes Strava. Use it once both Garmin and Strava are configured.

## Step 7: Inspect run artifacts

Friend/default layout keeps run outputs inside the repo so they are easy to inspect:

```text
output/garmin_primary_ingest_orchestrator_last_run.json
output/health_primary_sync_last_run.json
output/health_qa_daily_latest.json
output/garmin/tokenstore/
output/garmin/lockout_state.json
```

Useful commands:

```bash
cat output/garmin_primary_ingest_orchestrator_last_run.json
cat output/health_qa_daily_latest.json
```

A successful orchestrator artifact should have:

- top-level `status: "ok"`
- step entries with `status: "OK"`
- a recent `started_at` and `ended_at`

If a source returns no recent data, the run may complete but QA may still report missing user-facing metrics. Treat QA output as the truth for data usefulness.

## Step 8: Verify data landed with SQL

Use `psql` or your preferred SQL client.

Recent daily metrics:

```sql
SELECT metric_date, steps, sleep_seconds, resting_hr, hrv_ms, stress_avg, body_battery_avg, pulled_at
FROM health.daily_metrics
ORDER BY metric_date DESC
LIMIT 14;
```

Source lineage:

```sql
SELECT metric_date, source_system, metric_name, metric_value, pulled_at, consent_version, storage_table
FROM health.data_lineage
WHERE metric_date >= current_date - interval '14 days'
ORDER BY metric_date DESC, source_system, metric_name;
```

Recent operational metrics:

```sql
SELECT observed_at, source, metric_name, metric_value, metric_text, status, tags
FROM health.metrics_log
ORDER BY observed_at DESC
LIMIT 50;
```

Open quarantine items:

```sql
SELECT quarantine_id, source_system, entity_type, entity_id, severity, reason, recommended_action, created_at
FROM health.data_quarantine_open
ORDER BY created_at DESC
LIMIT 25;
```

## Step 9: Run one-off syncs after workouts

Daily scheduling is enough for normal use. If you just finished a workout and want to pull data immediately, run one manual one-off sync:

```bash
scripts/health_primary_sync_safe.sh
```

Or, if you are still in Garmin-only setup:

```bash
.venv/bin/python scripts/garmin_primary_ingest_orchestrator.py --workspace "$PWD" --env-file "$PWD/.env"
```

Avoid rapid repeated runs against Garmin. If data has not appeared yet, wait before retrying; Garmin may lag before making activity/wellness details available.

## File layout choices: simple vs production-style

### Environment/secrets file

This is where machine-specific settings and credentials live: database password, Garmin login, Strava credentials, token paths, and environment flags.

| Layout | Example | Pros | Cons |
| --- | --- | --- | --- |
| Repo-local `.env` | `/path/to/repo/.env` | Easiest to understand; no `sudo`; matches this repo's default loader; simplest for first run and debugging. | Must be careful not to commit/share the repo folder with `.env`; less traditional for a long-running Linux service. |
| System env file | `/etc/health-sync/health-sync.env` | Cleaner production pattern; secrets live outside code checkout; works naturally with systemd services. | Requires `sudo`; more permissions/setup complexity; harder for a first-time friend to debug. |

Recommendation for friend handoff: start with repo-local `.env`. Move to `/etc/health-sync/health-sync.env` later if this becomes a hardened server install.

### Logs and artifacts

This is where the pipeline writes evidence of what happened: latest run JSON, QA output, tokenstore files, lockout state, and troubleshooting material.

| Layout | Example | Pros | Cons |
| --- | --- | --- | --- |
| Repo-local output/logs | `/path/to/repo/output/`, `/path/to/repo/logs/` | Easiest to inspect; no permissions surprises; best for first-run troubleshooting; current repo defaults already use it. | The repo folder can get cluttered; backups/deploys need care; not the cleanest long-term Linux layout. |
| System paths | `/var/lib/health-sync/`, `/var/log/health-sync/` | Traditional service layout; code, state, and logs are separated; cleaner for long-running server operations. | Requires ownership/permission setup; more confusing for first run; paths must be wired carefully into env/systemd config. |

Recommendation for friend handoff: use repo-local `output/` and `logs/` first. If you later run this as a real server service, consider `/var/lib/health-sync` for state/artifacts and `/var/log/health-sync` for logs.

## Troubleshooting

### 1. Postgres is not reachable

Symptoms:

- `db_cli.py validate` fails
- connection refused
- password authentication failed

Fixes:

- Confirm Postgres is running.
- Confirm `.env` has the right `PGHOST`, `PGPORT`, `PGDATABASE`, `PGUSER`, and `PGPASSWORD`.
- If using Docker, check:

```bash
docker ps | grep health-ops-postgres
```

### 2. Missing env var

Symptoms:

- script exits with `Missing GARMIN_EMAIL/GARMIN_PASSWORD`
- script exits with missing Strava credential

Fixes:

- Confirm you edited `.env`, not `.env.example`.
- Confirm you are running from repo root or passing `--env-file "$PWD/.env"`.
- Confirm `ENV_PATH` is absolute when running from cron/systemd.

### 3. Garmin 429 / SSO lockout

Symptoms:

- Garmin auth step fails
- lockout artifact appears under `output/garmin/lockout_state.json`

Fixes:

- Stop retrying.
- Wait for cooldown.
- Verify credentials once.
- Run one controlled retry.

### 4. Empty first sync

Symptoms:

- run status is OK, but `health.daily_metrics` has nulls/missing recent days
- QA reports critical missing metrics

Fixes:

- Confirm the account actually has recent Garmin/Strava data.
- Increase only the lookback window you need, e.g. `GARMIN_SYNC_DAYS=14`.
- Re-run once after the source has had time to publish data.
- Use backfill only after the basic recent sync works.

### 5. Strava token failure

Symptoms:

- Strava sync fails during token refresh
- HTTP auth errors

Fixes:

- Re-check client ID/client secret.
- Generate a fresh refresh token with the needed scopes.
- Confirm `.env` can be updated by the sync script, because Strava refresh can rotate the refresh token.

## After first success: backfill conservatively

Once the recent-window sync is verified, expand history gradually.

Garmin daily wellness backfill example:

```bash
.venv/bin/python scripts/garmin_daily_sync.py \
  --mode backfill \
  --since 2026-05-01 \
  --until 2026-05-07 \
  --delay-seconds 3
```

Keep backfills small at first. The code is designed to be merge-safe, but upstream source behavior and rate limits still matter.
