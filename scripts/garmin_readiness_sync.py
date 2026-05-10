#!/usr/bin/env python3
import os
import json
from pathlib import Path

from common_env import load_env
from datetime import date, timedelta, datetime

import psycopg2
from psycopg2.extras import Json
from garminconnect import Garmin

WORKSPACE_DIR = Path(__file__).resolve().parents[1]
ENV_PATH = os.getenv("ENV_PATH", str(WORKSPACE_DIR / ".env"))
SQL_PATH = os.getenv("HEALTH_READINESS_SQL", str(WORKSPACE_DIR / "sql" / "health_readiness_daily.sql"))
DEFAULT_TOKENSTORE = os.getenv("GARMIN_TOKENSTORE", str(WORKSPACE_DIR / "output" / "garmin" / "tokenstore"))


def clamp(v, lo=0.0, hi=100.0):
    if v is None:
        return None
    return max(lo, min(hi, v))


def score_level(score):
    if score is None:
        return "unknown"
    if score >= 75:
        return "high"
    if score >= 55:
        return "moderate"
    if score >= 35:
        return "low"
    return "very_low"


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

    cur.execute(Path(SQL_PATH).read_text())
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

    days = int(os.getenv("GARMIN_READINESS_DAYS", "120"))
    today = date.today()

    upserts = 0
    errors = []

    for i in range(1, days + 1):
        d = (today - timedelta(days=i)).isoformat()
        try:
            # Garmin comparable score
            gr = g.get_morning_training_readiness(d) or {}

            # pull local inputs
            cur.execute(
                """
                SELECT resting_hr, hrv_ms, stress_avg, body_battery_avg, sleep_seconds
                FROM health.daily_metrics
                WHERE source='garmin' AND metric_date=%s
                """,
                (d,),
            )
            dm = cur.fetchone() or (None, None, None, None, None)
            resting_hr, hrv_ms, stress_avg, body_battery_avg, sleep_seconds = dm

            cur.execute(
                """
                SELECT sleep_score
                FROM health.sleep_sessions
                WHERE source='garmin'
                  AND sleep_start_utc::date >= (%s::date - INTERVAL '1 day')::date
                  AND sleep_start_utc::date <= %s::date
                ORDER BY sleep_start_utc DESC
                LIMIT 1
                """,
                (d, d),
            )
            row = cur.fetchone()
            sleep_score = row[0] if row else None

            cur.execute(
                """
                SELECT avg(resting_hr)::double precision
                FROM health.daily_metrics
                WHERE source='garmin'
                  AND metric_date < %s::date
                  AND metric_date >= (%s::date - INTERVAL '14 day')::date
                  AND resting_hr IS NOT NULL
                """,
                (d, d),
            )
            resting_hr_baseline = cur.fetchone()[0]

            cur.execute(
                """
                SELECT avg(hrv_ms)::double precision
                FROM health.daily_metrics
                WHERE source='garmin'
                  AND metric_date < %s::date
                  AND metric_date >= (%s::date - INTERVAL '28 day')::date
                  AND hrv_ms IS NOT NULL
                """,
                (d, d),
            )
            hrv_baseline = cur.fetchone()[0]

            # yesterday load from Garmin training metrics table
            cur.execute(
                """
                SELECT coalesce(sum(training_load),0)::double precision
                FROM health.activity_training_metrics_garmin
                WHERE activity_start_utc::date = (%s::date - INTERVAL '1 day')::date
                """,
                (d,),
            )
            training_load_prev_day = cur.fetchone()[0] or 0.0

            # custom score components
            sleep_component = clamp((sleep_seconds or 0) / 28800.0 * 100.0)
            if sleep_score is not None:
                sleep_component = (sleep_component * 0.5) + (float(sleep_score) * 0.5)

            stress_component = clamp(100.0 - float(stress_avg)) if stress_avg is not None else None
            body_battery_component = clamp(float(body_battery_avg)) if body_battery_avg is not None else None

            if hrv_ms is not None and hrv_baseline and hrv_baseline > 0:
                hrv_component = clamp((float(hrv_ms) / float(hrv_baseline)) * 100.0)
            elif hrv_ms is not None:
                hrv_component = clamp(float(hrv_ms))
            else:
                hrv_component = None

            if resting_hr is not None and resting_hr_baseline:
                delta = float(resting_hr) - float(resting_hr_baseline)
                rhr_component = clamp(100.0 - max(0.0, delta * 8.0))
            else:
                rhr_component = None

            # load component: 100 best, tapers as prior-day load rises
            load_component = clamp(100.0 - (float(training_load_prev_day) * 0.25))

            # weighted custom score
            weighted = []
            def add(v, w):
                if v is not None:
                    weighted.append((v, w))
            add(sleep_component, 0.25)
            add(hrv_component, 0.25)
            add(stress_component, 0.15)
            add(body_battery_component, 0.15)
            add(rhr_component, 0.10)
            add(load_component, 0.10)

            if weighted:
                wsum = sum(w for _, w in weighted)
                custom_score = sum(v * w for v, w in weighted) / wsum
            else:
                custom_score = None

            garmin_score = gr.get("score") if isinstance(gr, dict) else None
            delta_vs = (custom_score - float(garmin_score)) if (custom_score is not None and garmin_score is not None) else None

            notes = []
            if garmin_score is None:
                notes.append("garmin_readiness_missing")
            if sleep_seconds is None:
                notes.append("sleep_seconds_missing")
            if hrv_ms is None:
                notes.append("hrv_missing")

            cur.execute(
                """
                INSERT INTO health.readiness_daily (
                  source, metric_date,
                  garmin_readiness_score, garmin_readiness_level, garmin_feedback_short,
                  garmin_recovery_time_h, garmin_acute_load,
                  resting_hr, resting_hr_baseline_14d, hrv_ms, hrv_baseline_28d,
                  stress_avg, body_battery_avg, sleep_seconds, sleep_score,
                  training_load_prev_day,
                  custom_readiness_score, custom_readiness_level, score_delta_vs_garmin,
                  notes, raw_json, updated_at
                ) VALUES (
                  'garmin_custom', %s,
                  %s, %s, %s,
                  %s, %s,
                  %s, %s, %s, %s,
                  %s, %s, %s, %s,
                  %s,
                  %s, %s, %s,
                  %s, %s, now()
                )
                ON CONFLICT (source, metric_date) DO UPDATE SET
                  garmin_readiness_score=EXCLUDED.garmin_readiness_score,
                  garmin_readiness_level=EXCLUDED.garmin_readiness_level,
                  garmin_feedback_short=EXCLUDED.garmin_feedback_short,
                  garmin_recovery_time_h=EXCLUDED.garmin_recovery_time_h,
                  garmin_acute_load=EXCLUDED.garmin_acute_load,
                  resting_hr=EXCLUDED.resting_hr,
                  resting_hr_baseline_14d=EXCLUDED.resting_hr_baseline_14d,
                  hrv_ms=EXCLUDED.hrv_ms,
                  hrv_baseline_28d=EXCLUDED.hrv_baseline_28d,
                  stress_avg=EXCLUDED.stress_avg,
                  body_battery_avg=EXCLUDED.body_battery_avg,
                  sleep_seconds=EXCLUDED.sleep_seconds,
                  sleep_score=EXCLUDED.sleep_score,
                  training_load_prev_day=EXCLUDED.training_load_prev_day,
                  custom_readiness_score=EXCLUDED.custom_readiness_score,
                  custom_readiness_level=EXCLUDED.custom_readiness_level,
                  score_delta_vs_garmin=EXCLUDED.score_delta_vs_garmin,
                  notes=EXCLUDED.notes,
                  raw_json=EXCLUDED.raw_json,
                  updated_at=now()
                """,
                (
                    d,
                    float(garmin_score) if garmin_score is not None else None,
                    gr.get("level") if isinstance(gr, dict) else None,
                    gr.get("feedbackShort") if isinstance(gr, dict) else None,
                    (float(gr.get("recoveryTime", 0)) / 60.0) if isinstance(gr, dict) and gr.get("recoveryTime") is not None else None,
                    float(gr.get("acuteLoad")) if isinstance(gr, dict) and gr.get("acuteLoad") is not None else None,
                    float(resting_hr) if resting_hr is not None else None,
                    float(resting_hr_baseline) if resting_hr_baseline is not None else None,
                    float(hrv_ms) if hrv_ms is not None else None,
                    float(hrv_baseline) if hrv_baseline is not None else None,
                    float(stress_avg) if stress_avg is not None else None,
                    float(body_battery_avg) if body_battery_avg is not None else None,
                    int(sleep_seconds) if sleep_seconds is not None else None,
                    float(sleep_score) if sleep_score is not None else None,
                    float(training_load_prev_day) if training_load_prev_day is not None else None,
                    float(custom_score) if custom_score is not None else None,
                    score_level(custom_score),
                    float(delta_vs) if delta_vs is not None else None,
                    ",".join(notes) if notes else None,
                    Json({"garmin_training_readiness": gr}),
                ),
            )

            upserts += 1
        except Exception as e:
            errors.append({"date": d, "error": str(e)})

    cur.execute(
        """
        INSERT INTO health.sync_state (source, last_cursor, last_sync_at, status, meta)
        VALUES ('garmin_readiness', %s, now(), %s, %s)
        ON CONFLICT (source) DO UPDATE SET
          last_cursor=EXCLUDED.last_cursor,
          last_sync_at=EXCLUDED.last_sync_at,
          status=EXCLUDED.status,
          meta=EXCLUDED.meta
        """,
        (
            today.isoformat(),
            "ok" if not errors else "partial",
            Json({"days_attempted": days, "days_upserted": upserts, "errors": errors[:50]}),
        ),
    )

    conn.commit()
    cur.close()
    conn.close()

    print(json.dumps({"ok": True, "days_attempted": days, "days_upserted": upserts, "errors": errors}, indent=2))


if __name__ == "__main__":
    main()
