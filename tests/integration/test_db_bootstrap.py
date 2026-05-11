from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import psycopg2

ROOT = Path(__file__).resolve().parents[2]
ENV_PATH = ROOT / ".env.test"
CORE_TABLES = [
    ("health", "sync_state"),
    ("health", "daily_metrics"),
    ("health", "activities_garmin_raw"),
    ("health", "activities_strava_raw"),
    ("health", "activity_matches"),
    ("health", "activity_routes"),
    ("health", "readiness_daily"),
    ("health", "garmin_exercise_sets_raw"),
    ("meta", "schema_migrations"),
]


def load_test_env() -> dict[str, str]:
    if not ENV_PATH.exists():
        raise AssertionError("Missing .env.test; run `cp .env.test.example .env.test` before integration tests")
    env = os.environ.copy()
    for raw in ENV_PATH.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        env[key.strip()] = value.strip().strip('"').strip("'")
    if env.get("APP_ENV") != "test":
        raise AssertionError("Refusing to run integration tests unless APP_ENV=test")
    if env.get("PGDATABASE") == "health_ops" or env.get("PGPORT") == "5432":
        raise AssertionError("Refusing to run integration tests against default/live database settings")
    env["ENV_PATH"] = str(ENV_PATH)
    return env


def run_db_cli(command: str, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "scripts/db_cli.py", command],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def connect(env: dict[str, str]):
    return psycopg2.connect(
        host=env["PGHOST"],
        port=env["PGPORT"],
        dbname=env["PGDATABASE"],
        user=env["PGUSER"],
        password=env["PGPASSWORD"],
    )


def test_bootstrap_migrate_validate_against_isolated_postgres():
    env = load_test_env()

    bootstrap = run_db_cli("bootstrap", env)
    assert bootstrap.returncode == 0, bootstrap.stdout + bootstrap.stderr
    assert "bootstrap: ok" in bootstrap.stdout

    migrate = run_db_cli("migrate", env)
    assert migrate.returncode == 0, migrate.stdout + migrate.stderr
    assert "migrate: ok" in migrate.stdout

    validate = run_db_cli("validate", env)
    assert validate.returncode == 0, validate.stdout + validate.stderr
    assert "validate: ok" in validate.stdout

    with connect(env) as conn, conn.cursor() as cur:
        for schema, table in CORE_TABLES:
            cur.execute(
                """
                SELECT 1
                FROM information_schema.tables
                WHERE table_schema=%s AND table_name=%s
                """,
                (schema, table),
            )
            assert cur.fetchone(), f"missing {schema}.{table}"


def test_bootstrap_is_idempotent_against_isolated_postgres():
    env = load_test_env()
    first = run_db_cli("bootstrap", env)
    second = run_db_cli("bootstrap", env)
    assert first.returncode == 0, first.stdout + first.stderr
    assert second.returncode == 0, second.stdout + second.stderr
