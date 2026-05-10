#!/usr/bin/env python3
import argparse
import os
import sys
from pathlib import Path

from common_env import load_env
from typing import List

import psycopg2

ROOT = Path(__file__).resolve().parents[1]
SQL_DIR = ROOT / "sql"
MIGRATIONS_DIR = ROOT / "migrations"

REQUIRED_TABLES = [
    ("health", "sync_state"),
    ("health", "daily_metrics"),
    ("health", "sleep_sessions"),
    ("health", "body_composition_daily"),
    ("health", "activities"),
    ("health", "activities_strava_raw"),
    ("health", "activities_garmin_raw"),
    ("health", "activity_matches"),
    ("health", "activity_routes"),
    ("health", "readiness_daily"),
    ("health", "activity_training_metrics_garmin"),
    ("health", "activity_lap_facts_garmin"),
    ("health", "activity_zone_facts_garmin"),
    ("health", "daily_vitals_garmin"),
    ("health", "body_battery_daily_garmin"),
    ("health", "body_battery_events_garmin"),
    ("health", "activity_weather_garmin"),
    ("health", "activity_typed_splits_garmin"),
    ("health", "garmin_exercise_sets_raw"),
    ("health", "lifting_set_facts"),
]

BOOTSTRAP_SQL_FILES = [
    "health_unified_schema.sql",
    "health_activity_detail_tables.sql",
    "health_garmin_enrichment_tables.sql",
    "health_readiness_daily.sql",
    "garmin_lifting_tables.sql",
    "health_activity_routes.sql",
    "health_activity_routes_deduped_view.sql",
]



def db_connect():
    password = os.getenv("PGPASSWORD") or os.getenv("POSTGRES_PASSWORD")
    if not password:
        raise RuntimeError("Missing PGPASSWORD or POSTGRES_PASSWORD")
    return psycopg2.connect(
        host=os.getenv("PGHOST", "127.0.0.1"),
        port=os.getenv("PGPORT", "5432"),
        dbname=os.getenv("PGDATABASE", "health_ops"),
        user=os.getenv("PGUSER", "lex"),
        password=password,
    )


def ensure_meta(cur):
    cur.execute("CREATE SCHEMA IF NOT EXISTS meta")
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS meta.schema_migrations (
          version TEXT PRIMARY KEY,
          applied_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          checksum TEXT,
          notes TEXT
        )
        """
    )


def migration_files() -> List[Path]:
    if not MIGRATIONS_DIR.exists():
        return []
    return sorted([p for p in MIGRATIONS_DIR.iterdir() if p.suffix == ".sql"], key=lambda p: p.name)


def apply_sql(cur, sql_text: str):
    cur.execute(sql_text)


def cmd_bootstrap(args) -> int:
    conn = db_connect()
    conn.autocommit = False
    try:
        cur = conn.cursor()
        ensure_meta(cur)
        cur.execute("CREATE SCHEMA IF NOT EXISTS health")
        for fname in BOOTSTRAP_SQL_FILES:
            p = SQL_DIR / fname
            if not p.exists():
                raise RuntimeError(f"Missing SQL file: {p}")
            apply_sql(cur, p.read_text())
        conn.commit()
        print("bootstrap: ok")
        return 0
    except Exception as e:
        conn.rollback()
        print(f"bootstrap: fail: {e}")
        return 1
    finally:
        conn.close()


def cmd_migrate(args) -> int:
    conn = db_connect()
    conn.autocommit = False
    try:
        cur = conn.cursor()
        ensure_meta(cur)
        files = migration_files()
        applied = []
        for p in files:
            ver = p.name
            cur.execute("SELECT 1 FROM meta.schema_migrations WHERE version=%s", (ver,))
            if cur.fetchone():
                continue
            sql_text = p.read_text()
            apply_sql(cur, sql_text)
            cur.execute(
                "INSERT INTO meta.schema_migrations(version, checksum, notes) VALUES (%s,%s,%s)",
                (ver, None, "applied by db migrate"),
            )
            applied.append(ver)
        conn.commit()
        print(f"migrate: ok; applied={len(applied)}")
        for v in applied:
            print(f" - {v}")
        return 0
    except Exception as e:
        conn.rollback()
        print(f"migrate: fail: {e}")
        return 1
    finally:
        conn.close()


def cmd_validate(args) -> int:
    conn = db_connect()
    try:
        cur = conn.cursor()
        missing = []
        for schema, table in REQUIRED_TABLES:
            cur.execute(
                """
                SELECT 1
                FROM information_schema.tables
                WHERE table_schema=%s AND table_name=%s
                """,
                (schema, table),
            )
            if not cur.fetchone():
                missing.append(f"{schema}.{table}")

        cur.execute("SELECT 1 FROM information_schema.tables WHERE table_schema='meta' AND table_name='schema_migrations'")
        has_meta = bool(cur.fetchone())

        if missing:
            print("validate: fail")
            print("Missing required tables:")
            for t in missing:
                print(f" - {t}")
            if not has_meta:
                print("Remediation: run `python3 scripts/db_cli.py bootstrap` first, then `python3 scripts/db_cli.py migrate`.")
            else:
                print("Remediation: run `python3 scripts/db_cli.py migrate`.")
            return 2

        print("validate: ok")
        return 0
    except Exception as e:
        print(f"validate: fail: {e}")
        return 1
    finally:
        conn.close()


def cmd_status(args) -> int:
    conn = db_connect()
    try:
        cur = conn.cursor()
        ensure_meta(cur)
        conn.commit()
        files = migration_files()
        cur.execute("SELECT version, applied_at FROM meta.schema_migrations ORDER BY version")
        applied_rows = cur.fetchall()
        applied = {r[0]: r[1] for r in applied_rows}
        pending = [p.name for p in files if p.name not in applied]

        print("status:")
        print(f" - total migrations: {len(files)}")
        print(f" - applied: {len(applied_rows)}")
        print(f" - pending: {len(pending)}")
        if pending:
            for p in pending:
                print(f"   * {p}")

        rc = cmd_validate(args)
        return 0 if rc == 0 else 2
    except Exception as e:
        print(f"status: fail: {e}")
        return 1
    finally:
        conn.close()


def main() -> int:
    load_env(Path(os.getenv("ENV_PATH", str(ROOT / ".env"))))

    ap = argparse.ArgumentParser(description="DB bootstrap/migrate/validate/status")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("bootstrap")
    sub.add_parser("migrate")
    sub.add_parser("validate")
    sub.add_parser("status")
    args = ap.parse_args()

    if args.cmd == "bootstrap":
        return cmd_bootstrap(args)
    if args.cmd == "migrate":
        return cmd_migrate(args)
    if args.cmd == "validate":
        return cmd_validate(args)
    if args.cmd == "status":
        return cmd_status(args)
    return 1


if __name__ == "__main__":
    sys.exit(main())
