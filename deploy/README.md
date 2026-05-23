# Deployment and Scheduling Examples

This directory contains examples for running the health sync repeatedly after first setup.

For friend handoff, the recommended path is:

1. Complete `docs/FIRST_RUN.md`.
2. Keep `.env`, `output/`, and `logs/` repo-local at first.
3. Schedule one daily sync.
4. Run one-off manual syncs after workouts when you want immediate data.

## Recommended scheduler: systemd timer

Use systemd for a machine that will run this long-term. It is more explicit than cron, easier to inspect, and gives you service/timer status commands.

Example install, assuming the repo lives at `/opt/personal-health-data-platform` and a `healthsync` user owns it:

```bash
sudo cp deploy/health-sync.service /etc/systemd/system/health-sync.service
sudo cp deploy/health-sync.timer /etc/systemd/system/health-sync.timer
sudo systemctl daemon-reload
sudo systemctl enable --now health-sync.timer
```

Check status:

```bash
systemctl list-timers health-sync.timer
systemctl status health-sync.service
journalctl -u health-sync.service -n 100 --no-pager
```

Run one sync immediately:

```bash
sudo systemctl start health-sync.service
```

If you keep the repo somewhere else, edit `WorkingDirectory`, `Environment=ENV_PATH=...`, `ExecStart`, and `ReadWritePaths` in `health-sync.service`.

## Simpler fallback: cron

Use cron if you want the simplest scheduler and do not need systemd service status.

Example:

```bash
crontab deploy/crontab.example
```

Then inspect logs:

```bash
tail -100 logs/health-sync-cron.log
tail -100 logs/health-qa-cron.log
```

Cron gotchas:

- cron has a minimal `PATH`
- use absolute paths
- `cd` into the repo before running scripts
- set `ENV_PATH` to an absolute path
- make sure the repo-local virtualenv already exists via `make venv`

## Daily cadence and one-off runs

Daily sync is sufficient for normal use. The source platforms may lag after workouts, and Garmin in particular should not be hammered with rapid retries.

Default schedule:

- full sync daily at 7:00 AM local server time
- optional QA-only run daily at 7:30 AM local server time

One-off run after a workout:

```bash
cd /opt/personal-health-data-platform
ENV_PATH=/opt/personal-health-data-platform/.env ./scripts/health_primary_sync_safe.sh
```

If you are still in Garmin-only first-run mode, use the orchestrator directly without `--with-strava`:

```bash
cd /opt/personal-health-data-platform
ENV_PATH=/opt/personal-health-data-platform/.env ./.venv/bin/python scripts/garmin_primary_ingest_orchestrator.py --workspace "$PWD" --env-file "$PWD/.env"
```

## File layout choices

### Environment/secrets file

The environment file stores machine-specific secrets and settings: database credentials, Garmin login, Strava OAuth credentials, token paths, and runtime flags.

| Layout | Example | Pros | Cons |
| --- | --- | --- | --- |
| Repo-local `.env` | `/opt/personal-health-data-platform/.env` | Simplest; no `sudo`; matches the default loader; easiest for first-run debugging. | You must avoid committing/sharing `.env`; less clean for a hardened server service. |
| System env file | `/etc/health-sync/health-sync.env` | Production-style; secrets live outside the code checkout; works naturally with systemd `EnvironmentFile=`. | Requires `sudo`; more permissions/setup complexity; slightly harder to troubleshoot. |

Friend/default recommendation: start with repo-local `.env`. Move to `/etc/health-sync/health-sync.env` only when hardening the install.

### Logs, artifacts, and state

Artifacts are the evidence files the pipeline writes after a run: latest orchestrator JSON, QA JSON, Garmin tokenstore, lockout state, and scheduler logs.

| Layout | Example | Pros | Cons |
| --- | --- | --- | --- |
| Repo-local output/logs | `/opt/personal-health-data-platform/output/`, `/opt/personal-health-data-platform/logs/` | Easiest to inspect; no permissions surprises; current repo defaults already use it; best for handoff. | Repo folder gets operational state mixed with code; backups/deploys need care. |
| System paths | `/var/lib/health-sync/`, `/var/log/health-sync/` | Traditional Linux service layout; separates code, state, and logs; cleaner for long-running servers. | Requires ownership/permission setup; paths must be wired into env and service files carefully. |

Friend/default recommendation: keep `output/` and `logs/` repo-local. For a hardened server, move state to `/var/lib/health-sync` and logs to `/var/log/health-sync` after the first successful setup.

## Log rotation

For repo-local logs, adapt `deploy/logrotate.conf.example` and install it as:

```bash
sudo cp deploy/logrotate.conf.example /etc/logrotate.d/health-sync
```

The example rotates weekly and keeps eight weeks.

## Common scheduling failures

### `python` or package not found

Run `make venv` first and use the repo-local `.venv/bin/python`. Cron/systemd may not load your shell profile.

### `.env` not found

Use an absolute `ENV_PATH`, especially from cron/systemd.

### Permission denied writing output

Ensure the scheduler user owns or can write:

```text
output/
logs/
```

For systemd, also update `ReadWritePaths=` if you change locations.

### Garmin lockout after repeated runs

Stop retrying. Check:

```bash
cat output/garmin/lockout_state.json
```

Wait until the cooldown expires before trying again.
