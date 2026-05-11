#!/usr/bin/env python3
import os
from pathlib import Path

import psycopg2

WORKSPACE_DIR = Path(__file__).resolve().parents[1]
ENV_PATH = os.getenv("ENV_PATH", str(WORKSPACE_DIR / ".env"))


def load_env(path):
    for line in Path(path).read_text().splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            os.environ[k.strip()] = v.strip().strip('"').strip("'")


def main():
    load_env(ENV_PATH)
    conn = psycopg2.connect(
        host=os.getenv("PGHOST", "127.0.0.1"),
        port=os.getenv("PGPORT", "5432"),
        dbname=os.getenv("PGDATABASE", "health_ops"),
        user=os.getenv("PGUSER", "lex"),
        password=os.getenv("PGPASSWORD") or os.getenv("POSTGRES_PASSWORD"),
    )
    conn.autocommit = False
    cur = conn.cursor()

    cur.execute("TRUNCATE health.activity_matches")

    # pass 1: close start time + same type
    cur.execute(
        """
        INSERT INTO health.activity_matches (
          strava_external_activity_id,
          garmin_external_activity_id,
          match_confidence,
          match_method
        )
        SELECT
          s.external_activity_id,
          g.external_activity_id,
          0.90,
          'time_type_window'
        FROM health.activities_strava_raw s
        JOIN LATERAL (
          SELECT g1.*
          FROM health.activities_garmin_raw g1
          WHERE abs(extract(epoch from (s.start_time_utc - g1.start_time_utc))) <= 900
            AND lower(coalesce(s.activity_type,'')) = lower(coalesce(g1.activity_type,''))
          ORDER BY abs(extract(epoch from (s.start_time_utc - g1.start_time_utc))) ASC
          LIMIT 1
        ) g ON true
        ON CONFLICT DO NOTHING
        """
    )

    # pass 2: close start time + duration similarity (for type naming mismatches)
    cur.execute(
        """
        INSERT INTO health.activity_matches (
          strava_external_activity_id,
          garmin_external_activity_id,
          match_confidence,
          match_method
        )
        SELECT
          s.external_activity_id,
          g.external_activity_id,
          0.75,
          'time_duration_window'
        FROM health.activities_strava_raw s
        LEFT JOIN health.activity_matches m ON m.strava_external_activity_id = s.external_activity_id
        JOIN LATERAL (
          SELECT g1.*
          FROM health.activities_garmin_raw g1
          LEFT JOIN health.activity_matches m2 ON m2.garmin_external_activity_id = g1.external_activity_id
          WHERE m2.garmin_external_activity_id IS NULL
            AND abs(extract(epoch from (s.start_time_utc - g1.start_time_utc))) <= 900
            AND abs(coalesce(s.moving_time_s,0) - coalesce(g1.moving_time_s,0)) <= 300
          ORDER BY abs(extract(epoch from (s.start_time_utc - g1.start_time_utc))) ASC
          LIMIT 1
        ) g ON true
        WHERE m.strava_external_activity_id IS NULL
        ON CONFLICT DO NOTHING
        """
    )

    conn.commit()
    cur.execute("SELECT count(*) FROM health.activity_matches")
    n = cur.fetchone()[0]
    conn.close()
    print({"ok": True, "matches": n})


if __name__ == "__main__":
    main()
