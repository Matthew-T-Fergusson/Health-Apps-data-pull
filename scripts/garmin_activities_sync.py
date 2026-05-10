#!/usr/bin/env python3
import os
import json
from pathlib import Path

from common_env import load_env
from datetime import date, timedelta, datetime, timezone

import psycopg2
from psycopg2.extras import Json
from garminconnect import Garmin

WORKSPACE_DIR = Path(__file__).resolve().parents[1]
ENV_PATH = os.getenv("ENV_PATH", str(WORKSPACE_DIR / ".env"))
DEFAULT_TOKENSTORE = os.getenv("GARMIN_TOKENSTORE", str(WORKSPACE_DIR / "output" / "garmin" / "tokenstore"))


def parse_ts(s):
    if not s:
        return None
    # e.g. 2026-02-27 13:41:16
    try:
        return datetime.strptime(s, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    except Exception:
        return None


def main():
    load_env(ENV_PATH)
    email = os.getenv("GARMIN_EMAIL")
    password = os.getenv("GARMIN_PASSWORD")
    if not email or not password:
        raise RuntimeError("Missing GARMIN_EMAIL/GARMIN_PASSWORD")

    conn = psycopg2.connect(
        host=os.getenv("PGHOST", "127.0.0.1"),
        port=os.getenv("PGPORT", "5432"),
        dbname=os.getenv("PGDATABASE", "health_ops"),
        user=os.getenv("PGUSER", "lex"),
        password=os.getenv("PGPASSWORD") or os.getenv("POSTGRES_PASSWORD"),
    )
    conn.autocommit = False
    cur = conn.cursor()

    tokenstore = os.getenv("GARMIN_TOKENSTORE", DEFAULT_TOKENSTORE)
    Path(tokenstore).parent.mkdir(parents=True, exist_ok=True)

    g = Garmin(email=email, password=password)
    try:
        g.login(tokenstore=tokenstore)
    except FileNotFoundError:
        if os.getenv("GARMIN_DISABLE_FALLBACK_LOGIN", "0") == "1":
            raise
        g.login()
        g.garth.dump(tokenstore)

    lookback_days = int(os.getenv("GARMIN_ACTIVITY_LOOKBACK_DAYS", "60"))
    start = (date.today() - timedelta(days=lookback_days)).isoformat()
    end = date.today().isoformat()

    activities = g.get_activities_by_date(start, end) or []

    upsert = """
    INSERT INTO health.activities_garmin_raw (
      external_activity_id, start_time_utc, activity_type,
      moving_time_s, elapsed_time_s, distance_m, elevation_gain_m,
      avg_hr, max_hr, calories, raw_json, updated_at
    ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s, now())
    ON CONFLICT (external_activity_id) DO UPDATE SET
      start_time_utc = EXCLUDED.start_time_utc,
      activity_type = EXCLUDED.activity_type,
      moving_time_s = EXCLUDED.moving_time_s,
      elapsed_time_s = EXCLUDED.elapsed_time_s,
      distance_m = EXCLUDED.distance_m,
      elevation_gain_m = EXCLUDED.elevation_gain_m,
      avg_hr = EXCLUDED.avg_hr,
      max_hr = EXCLUDED.max_hr,
      calories = EXCLUDED.calories,
      raw_json = EXCLUDED.raw_json,
      updated_at = now()
    """

    ok = 0
    for a in activities:
      aid = str(a.get("activityId")) if a.get("activityId") is not None else None
      if not aid:
          continue
      start_dt = parse_ts(a.get("startTimeGMT"))
      if not start_dt:
          continue
      cur.execute(upsert, (
        aid,
        start_dt,
        (a.get("activityType") or {}).get("typeKey") or a.get("activityName"),
        int(a.get("duration") or 0),
        int(a.get("elapsedDuration") or 0),
        float(a.get("distance") or 0),
        float(a.get("elevationGain") or 0),
        int(a.get("averageHR")) if a.get("averageHR") is not None else None,
        int(a.get("maxHR")) if a.get("maxHR") is not None else None,
        float(a.get("calories") or 0),
        Json(a),
      ))
      ok += 1

    cur.execute(
      """
      INSERT INTO health.sync_state (source, last_cursor, last_sync_at, status, meta)
      VALUES ('garmin_activities', %s, now(), 'ok', %s)
      ON CONFLICT (source) DO UPDATE SET
        last_cursor = EXCLUDED.last_cursor,
        last_sync_at = EXCLUDED.last_sync_at,
        status = EXCLUDED.status,
        meta = EXCLUDED.meta
      """,
      (end, Json({"lookback_days": lookback_days, "pulled": len(activities), "upserted": ok}))
    )

    conn.commit()
    cur.close(); conn.close()
    print(json.dumps({"ok": True, "pulled": len(activities), "upserted": ok}, indent=2))


if __name__ == "__main__":
    main()
