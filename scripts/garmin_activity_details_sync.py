#!/usr/bin/env python3
import os
import json
from pathlib import Path
from datetime import datetime, timezone, date, timedelta

import psycopg2
from psycopg2.extras import Json
from garminconnect import Garmin

ENV_PATH = "/home/matt69/.openclaw/.env"
DEFAULT_TOKENSTORE = "/home/matt69/.openclaw/workspace/output/garmin/tokenstore"
SQL_PATH = "/home/matt69/.openclaw/workspace/sql/health_activity_detail_tables.sql"
ENRICH_SQL_PATH = "/home/matt69/.openclaw/workspace/sql/health_garmin_enrichment_tables.sql"


def load_env(path):
    for line in Path(path).read_text().splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            os.environ[k.strip()] = v.strip().strip('"').strip("'")


def parse_ts(s):
    if not s:
        return None
    try:
        if "T" in s:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        else:
            dt = datetime.strptime(s, "%Y-%m-%d %H:%M:%S")
            dt = dt.replace(tzinfo=timezone.utc)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def f(v):
    try:
        return float(v) if v is not None else None
    except Exception:
        return None


def i(v):
    try:
        return int(v) if v is not None else None
    except Exception:
        return None


def upsert_training(cur, aid, start_utc, activity_type, payload):
    cur.execute(
        """
        INSERT INTO health.activity_training_metrics_garmin (
          garmin_activity_id, activity_start_utc, activity_type,
          training_load, aerobic_training_effect, anaerobic_training_effect,
          training_effect_label, vo2max_value, avg_speed_mps, max_speed_mps,
          avg_hr, max_hr, avg_cadence, max_cadence, avg_power, max_power,
          calories, moving_time_s, elapsed_time_s, distance_m, elevation_gain_m,
          raw_json, updated_at
        ) VALUES (
          %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,now()
        )
        ON CONFLICT (garmin_activity_id) DO UPDATE SET
          activity_start_utc=EXCLUDED.activity_start_utc,
          activity_type=EXCLUDED.activity_type,
          training_load=EXCLUDED.training_load,
          aerobic_training_effect=EXCLUDED.aerobic_training_effect,
          anaerobic_training_effect=EXCLUDED.anaerobic_training_effect,
          training_effect_label=EXCLUDED.training_effect_label,
          vo2max_value=EXCLUDED.vo2max_value,
          avg_speed_mps=EXCLUDED.avg_speed_mps,
          max_speed_mps=EXCLUDED.max_speed_mps,
          avg_hr=EXCLUDED.avg_hr,
          max_hr=EXCLUDED.max_hr,
          avg_cadence=EXCLUDED.avg_cadence,
          max_cadence=EXCLUDED.max_cadence,
          avg_power=EXCLUDED.avg_power,
          max_power=EXCLUDED.max_power,
          calories=EXCLUDED.calories,
          moving_time_s=EXCLUDED.moving_time_s,
          elapsed_time_s=EXCLUDED.elapsed_time_s,
          distance_m=EXCLUDED.distance_m,
          elevation_gain_m=EXCLUDED.elevation_gain_m,
          raw_json=EXCLUDED.raw_json,
          updated_at=now()
        """,
        (
            aid,
            start_utc,
            activity_type,
            f(payload.get("activityTrainingLoad")),
            f(payload.get("aerobicTrainingEffect")),
            f(payload.get("anaerobicTrainingEffect")),
            payload.get("trainingEffectLabel"),
            f(payload.get("vO2MaxValue")),
            f(payload.get("averageSpeed")),
            f(payload.get("maxSpeed")),
            i(payload.get("averageHR")),
            i(payload.get("maxHR")),
            f(payload.get("averageBikeCadenceInRevPerMinute") or payload.get("averageRunCadenceInStepsPerMinute") or payload.get("averageCadence")),
            f(payload.get("maxBikeCadenceInRevPerMinute") or payload.get("maxRunCadenceInStepsPerMinute") or payload.get("maxCadence")),
            f(payload.get("averagePower")),
            f(payload.get("maxPower")),
            f(payload.get("calories")),
            f(payload.get("movingDuration") or payload.get("duration")),
            f(payload.get("elapsedDuration")),
            f(payload.get("distance")),
            f(payload.get("elevationGain")),
            Json(payload),
        ),
    )


def sync_laps(cur, aid, laps):
    cur.execute("DELETE FROM health.activity_lap_facts_garmin WHERE garmin_activity_id=%s", (aid,))
    lap_list = laps
    if isinstance(laps, dict):
        lap_list = laps.get("lapDTOs") or []
    if not isinstance(lap_list, list):
        lap_list = []
    for idx, lap in enumerate(lap_list):
        cur.execute(
            """
            INSERT INTO health.activity_lap_facts_garmin (
              garmin_activity_id, lap_index, start_utc, duration_s, elapsed_duration_s,
              distance_m, avg_speed_mps, max_speed_mps, avg_hr, max_hr, avg_cadence,
              avg_power, elevation_gain_m, elevation_loss_m, calories, lap_type, raw_json, updated_at
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,now())
            ON CONFLICT (garmin_activity_id, lap_index) DO UPDATE SET
              start_utc=EXCLUDED.start_utc,
              duration_s=EXCLUDED.duration_s,
              elapsed_duration_s=EXCLUDED.elapsed_duration_s,
              distance_m=EXCLUDED.distance_m,
              avg_speed_mps=EXCLUDED.avg_speed_mps,
              max_speed_mps=EXCLUDED.max_speed_mps,
              avg_hr=EXCLUDED.avg_hr,
              max_hr=EXCLUDED.max_hr,
              avg_cadence=EXCLUDED.avg_cadence,
              avg_power=EXCLUDED.avg_power,
              elevation_gain_m=EXCLUDED.elevation_gain_m,
              elevation_loss_m=EXCLUDED.elevation_loss_m,
              calories=EXCLUDED.calories,
              lap_type=EXCLUDED.lap_type,
              raw_json=EXCLUDED.raw_json,
              updated_at=now()
            """,
            (
                aid,
                idx,
                parse_ts(lap.get("startTimeGMT") or lap.get("startTime")),
                f(lap.get("duration") or lap.get("movingDuration")),
                f(lap.get("elapsedDuration")),
                f(lap.get("distance")),
                f(lap.get("averageSpeed")),
                f(lap.get("maxSpeed")),
                i(lap.get("averageHR")),
                i(lap.get("maxHR")),
                f(lap.get("averageBikeCadenceInRevPerMinute") or lap.get("averageRunCadenceInStepsPerMinute") or lap.get("averageCadence")),
                f(lap.get("averagePower")),
                f(lap.get("elevationGain")),
                f(lap.get("elevationLoss")),
                f(lap.get("calories")),
                lap.get("lapType") or lap.get("intensityType"),
                Json(lap),
            ),
        )


def sync_zones(cur, aid, hr_zones, power_zones):
    cur.execute("DELETE FROM health.activity_zone_facts_garmin WHERE garmin_activity_id=%s", (aid,))

    def ins(source, arr):
        for idx, z in enumerate(arr or []):
            secs = f(z.get("secsInZone") or z.get("secondsInZone") or z.get("timeInZone") or z.get("secs"))
            pct = f(z.get("pctInZone") or z.get("percentTimeInZone") or z.get("zonePercent"))
            if pct is None and secs is not None:
                # infer if total provided in payload
                total = f((arr or [{}])[0].get("activityDuration"))
                if total and total > 0:
                    pct = (secs / total) * 100.0
            cur.execute(
                """
                INSERT INTO health.activity_zone_facts_garmin (
                  garmin_activity_id, zone_source, zone_index, zone_name,
                  seconds_in_zone, pct_in_zone, raw_json, updated_at
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,now())
                ON CONFLICT (garmin_activity_id, zone_source, zone_index) DO UPDATE SET
                  zone_name=EXCLUDED.zone_name,
                  seconds_in_zone=EXCLUDED.seconds_in_zone,
                  pct_in_zone=EXCLUDED.pct_in_zone,
                  raw_json=EXCLUDED.raw_json,
                  updated_at=now()
                """,
                (aid, source, idx, z.get("zoneName") or z.get("name") or f"Z{idx+1}", secs, pct, Json(z)),
            )

    ins("hr", hr_zones)
    ins("power", power_zones)


def sync_weather(cur, aid, weather):
    if not isinstance(weather, dict):
        weather = {}
    issue = parse_ts(weather.get("issueDate"))
    wtype = None
    wtd = weather.get("weatherTypeDTO")
    if isinstance(wtd, dict):
        wtype = wtd.get("desc") or wtd.get("weatherType") or wtd.get("id")
    cur.execute(
        """
        INSERT INTO health.activity_weather_garmin (
          garmin_activity_id, issue_utc, temp_c, apparent_temp_c, dew_point_c,
          humidity_pct, wind_direction_deg, wind_compass, wind_speed_kph, wind_gust_kph,
          latitude, longitude, weather_type, raw_json, updated_at
        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,now())
        ON CONFLICT (garmin_activity_id) DO UPDATE SET
          issue_utc=EXCLUDED.issue_utc,
          temp_c=EXCLUDED.temp_c,
          apparent_temp_c=EXCLUDED.apparent_temp_c,
          dew_point_c=EXCLUDED.dew_point_c,
          humidity_pct=EXCLUDED.humidity_pct,
          wind_direction_deg=EXCLUDED.wind_direction_deg,
          wind_compass=EXCLUDED.wind_compass,
          wind_speed_kph=EXCLUDED.wind_speed_kph,
          wind_gust_kph=EXCLUDED.wind_gust_kph,
          latitude=EXCLUDED.latitude,
          longitude=EXCLUDED.longitude,
          weather_type=EXCLUDED.weather_type,
          raw_json=EXCLUDED.raw_json,
          updated_at=now()
        """,
        (
            aid, issue, f(weather.get("temp")), f(weather.get("apparentTemp")), f(weather.get("dewPoint")),
            f(weather.get("relativeHumidity")), f(weather.get("windDirection")), weather.get("windDirectionCompassPoint"),
            f(weather.get("windSpeed")), f(weather.get("windGust")), f(weather.get("latitude")), f(weather.get("longitude")),
            wtype, Json(weather),
        ),
    )


def sync_typed_splits(cur, aid, typed):
    cur.execute("DELETE FROM health.activity_typed_splits_garmin WHERE garmin_activity_id=%s", (aid,))
    splits = typed.get("splits") if isinstance(typed, dict) else []
    if not isinstance(splits, list):
        splits = []
    for idx, s in enumerate(splits):
        cur.execute(
            """
            INSERT INTO health.activity_typed_splits_garmin (
              garmin_activity_id, split_index, split_type, start_utc, end_utc,
              duration_s, moving_duration_s, elapsed_duration_s, distance_m,
              avg_speed_mps, avg_hr, max_hr, total_exercise_reps,
              calories, lap_indexes_json, raw_json, updated_at
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,now())
            ON CONFLICT (garmin_activity_id, split_index) DO UPDATE SET
              split_type=EXCLUDED.split_type,
              start_utc=EXCLUDED.start_utc,
              end_utc=EXCLUDED.end_utc,
              duration_s=EXCLUDED.duration_s,
              moving_duration_s=EXCLUDED.moving_duration_s,
              elapsed_duration_s=EXCLUDED.elapsed_duration_s,
              distance_m=EXCLUDED.distance_m,
              avg_speed_mps=EXCLUDED.avg_speed_mps,
              avg_hr=EXCLUDED.avg_hr,
              max_hr=EXCLUDED.max_hr,
              total_exercise_reps=EXCLUDED.total_exercise_reps,
              calories=EXCLUDED.calories,
              lap_indexes_json=EXCLUDED.lap_indexes_json,
              raw_json=EXCLUDED.raw_json,
              updated_at=now()
            """,
            (
                aid, idx, s.get("type"), parse_ts(s.get("startTimeGMT")), parse_ts(s.get("endTimeGMT")),
                f(s.get("duration")), f(s.get("movingDuration")), f(s.get("elapsedDuration")), f(s.get("distance")),
                f(s.get("averageSpeed")), i(s.get("averageHR")), i(s.get("maxHR")), i(s.get("totalExerciseReps")),
                f(s.get("calories")), Json(s.get("lapIndexes") or []), Json(s),
            ),
        )


def main():
    load_env(ENV_PATH)

    conn = psycopg2.connect(
        host=os.getenv("PGHOST", "127.0.0.1"),
        port=os.getenv("PGPORT", "5432"),
        dbname=os.getenv("PGDATABASE", "health_ops"),
        user=os.getenv("PGUSER", "lex"),
        password=os.getenv("PGPASSWORD", "lexpass_change_me"),
    )
    conn.autocommit = False
    cur = conn.cursor()

    # schema
    cur.execute(Path(SQL_PATH).read_text())
    enrich = Path(ENRICH_SQL_PATH)
    if enrich.exists():
        cur.execute(enrich.read_text())
    conn.commit()

    email = os.getenv("GARMIN_EMAIL")
    password = os.getenv("GARMIN_PASSWORD")
    if not email or not password:
        raise RuntimeError("Missing GARMIN_EMAIL/GARMIN_PASSWORD")

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

    lookback_days = int(os.getenv("GARMIN_ACTIVITY_DETAIL_LOOKBACK_DAYS", "90"))
    cutoff = (date.today() - timedelta(days=lookback_days)).isoformat()

    cur.execute(
        """
        SELECT external_activity_id::bigint, start_time_utc, activity_type
        FROM health.activities_garmin_raw
        WHERE start_time_utc::date >= %s::date
          AND external_activity_id ~ '^[0-9]+$'
        ORDER BY start_time_utc DESC
        """,
        (cutoff,),
    )
    acts = cur.fetchall()

    ok = 0
    err = []
    laps_written = 0
    zones_written = 0
    typed_splits_written = 0
    weather_written = 0

    for aid, start_utc, activity_type in acts:
        cur.execute("SAVEPOINT garmin_activity_details_sp")
        try:
            detail = g.get_activity_details(int(aid)) or {}
            laps = g.get_activity_splits(int(aid)) or []
            typed = g.get_activity_typed_splits(int(aid)) or {}
            weather = g.get_activity_weather(int(aid)) or {}
            hr_zones = g.get_activity_hr_in_timezones(int(aid)) or []
            power_zones = g.get_activity_power_in_timezones(int(aid)) or []

            # summary-ish fields from raw table (not detail stream payload)
            cur.execute("select raw_json from health.activities_garmin_raw where external_activity_id=%s::text limit 1", (str(aid),))
            rr = cur.fetchone()
            summary = rr[0] if rr and isinstance(rr[0], dict) else {}

            merged = dict(summary)
            if isinstance(detail, dict):
                merged.update(detail)

            upsert_training(cur, aid, start_utc, activity_type, merged)
            sync_laps(cur, aid, laps)
            sync_typed_splits(cur, aid, typed)
            sync_weather(cur, aid, weather)
            sync_zones(cur, aid, hr_zones, power_zones)
            cur.execute("RELEASE SAVEPOINT garmin_activity_details_sp")

            lap_list = laps.get("lapDTOs") if isinstance(laps, dict) else (laps or [])
            laps_written += len(lap_list or [])
            typed_splits_written += len((typed or {}).get("splits") or []) if isinstance(typed, dict) else 0
            zones_written += len(hr_zones or []) + len(power_zones or [])
            weather_written += 1
            ok += 1
        except Exception as e:
            cur.execute("ROLLBACK TO SAVEPOINT garmin_activity_details_sp")
            err.append({"activity_id": int(aid), "error": str(e)})

    cur.execute(
        """
        INSERT INTO health.sync_state (source, last_cursor, last_sync_at, status, meta)
        VALUES ('garmin_activity_details', %s, now(), %s, %s)
        ON CONFLICT (source) DO UPDATE SET
          last_cursor=EXCLUDED.last_cursor,
          last_sync_at=EXCLUDED.last_sync_at,
          status=EXCLUDED.status,
          meta=EXCLUDED.meta
        """,
        (
            cutoff,
            "ok" if not err else "partial",
            Json({
                "lookback_days": lookback_days,
                "activities_considered": len(acts),
                "activities_ok": ok,
                "laps_written": laps_written,
                "typed_splits_written": typed_splits_written,
                "weather_written": weather_written,
                "zones_written": zones_written,
                "errors": err[:50],
            }),
        ),
    )

    conn.commit()
    cur.close()
    conn.close()

    print(json.dumps({
        "ok": True,
        "lookback_days": lookback_days,
        "activities_considered": len(acts),
        "activities_ok": ok,
        "laps_written": laps_written,
        "typed_splits_written": typed_splits_written,
        "weather_written": weather_written,
        "zones_written": zones_written,
        "errors": err,
    }, indent=2))


if __name__ == "__main__":
    main()
