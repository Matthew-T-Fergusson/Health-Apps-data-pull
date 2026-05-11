#!/usr/bin/env python3
import json
import os
from datetime import UTC, datetime
from pathlib import Path

import psycopg2
from common_env import load_env
from garminconnect import Garmin
from psycopg2.extras import Json

WORKSPACE_DIR = Path(__file__).resolve().parents[1]
ENV_PATH = os.getenv("ENV_PATH", str(WORKSPACE_DIR / ".env"))
DEFAULT_TOKENSTORE = os.getenv("GARMIN_TOKENSTORE", str(WORKSPACE_DIR / "output" / "garmin" / "tokenstore"))
CUTOFF_DATE = "2025-04-02"  # requested backfill boundary


def parse_iso_utc(s):
    if not s:
        return None
    # Garmin often uses: 2026-02-27T13:41:16.0
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt.astimezone(UTC)
    except Exception:
        return None


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

    # Ensure tables exist
    schema_sql = (WORKSPACE_DIR / "sql" / "garmin_lifting_tables.sql").read_text()
    cur.execute(schema_sql)
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

    cur.execute(
        """
        SELECT external_activity_id::bigint, start_time_utc
        FROM health.activities_garmin_raw
        WHERE lower(activity_type) = 'strength_training'
          AND start_time_utc::date >= %s::date
        ORDER BY start_time_utc ASC
        """,
        (CUTOFF_DATE,),
    )
    acts = cur.fetchall()

    raw_upserts = 0
    fact_rows = 0
    errors = []

    raw_sql = """
    INSERT INTO health.garmin_exercise_sets_raw (
      garmin_activity_id, activity_start_utc, pulled_at_utc, raw_json, updated_at
    ) VALUES (%s, %s, now(), %s, now())
    ON CONFLICT (garmin_activity_id) DO UPDATE SET
      activity_start_utc = EXCLUDED.activity_start_utc,
      pulled_at_utc = EXCLUDED.pulled_at_utc,
      raw_json = EXCLUDED.raw_json,
      updated_at = now()
    """

    fact_insert = """
    INSERT INTO health.lifting_set_facts (
      garmin_activity_id, activity_start_utc, set_index, message_index,
      set_start_utc, set_type, exercise_name, exercise_category, exercise_detect_prob,
      reps, weight_kg, duration_s, volume_kg, is_work_set, is_warmup, updated_at
    ) VALUES (
      %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,now()
    )
    ON CONFLICT (garmin_activity_id, set_index) DO UPDATE SET
      activity_start_utc = EXCLUDED.activity_start_utc,
      message_index = EXCLUDED.message_index,
      set_start_utc = EXCLUDED.set_start_utc,
      set_type = EXCLUDED.set_type,
      exercise_name = EXCLUDED.exercise_name,
      exercise_category = EXCLUDED.exercise_category,
      exercise_detect_prob = EXCLUDED.exercise_detect_prob,
      reps = EXCLUDED.reps,
      weight_kg = EXCLUDED.weight_kg,
      duration_s = EXCLUDED.duration_s,
      volume_kg = EXCLUDED.volume_kg,
      is_work_set = EXCLUDED.is_work_set,
      is_warmup = EXCLUDED.is_warmup,
      updated_at = now()
    """

    for aid, start_utc in acts:
        try:
            payload = g.get_activity_exercise_sets(int(aid)) or {}
            cur.execute(raw_sql, (aid, start_utc, Json(payload)))
            raw_upserts += 1

            sets = payload.get("exerciseSets") or []

            # idempotent refresh per activity
            cur.execute("DELETE FROM health.lifting_set_facts WHERE garmin_activity_id = %s", (aid,))

            for idx, s in enumerate(sets):
                ex = (s.get("exercises") or [{}])[0]
                ex_name = ex.get("name")
                ex_cat = ex.get("category")
                ex_prob = ex.get("probability")
                reps = s.get("repetitionCount")
                weight = s.get("weight")
                duration = s.get("duration")
                set_type = s.get("setType")
                set_start = parse_iso_utc(s.get("startTime"))

                try:
                    reps_i = int(reps) if reps is not None else None
                except Exception:
                    reps_i = None

                try:
                    weight_f = float(weight) if weight is not None else None
                except Exception:
                    weight_f = None

                try:
                    dur_f = float(duration) if duration is not None else None
                except Exception:
                    dur_f = None

                vol = (reps_i * weight_f) if (reps_i is not None and weight_f is not None) else None
                is_warmup = (set_type or "").upper() == "WARMUP" or (ex_cat or "").upper() in {"WARM_UP", "CARDIO", "MOBILITY"}
                is_work = (set_type or "").upper() == "ACTIVE" and (reps_i or 0) > 0

                cur.execute(
                    fact_insert,
                    (
                        aid,
                        start_utc,
                        idx,
                        s.get("messageIndex"),
                        set_start,
                        set_type,
                        ex_name,
                        ex_cat,
                        float(ex_prob) if ex_prob is not None else None,
                        reps_i,
                        weight_f,
                        dur_f,
                        vol,
                        is_work,
                        is_warmup,
                    ),
                )
                fact_rows += 1

        except Exception as e:
            errors.append({"activity_id": aid, "error": str(e)})

    cur.execute(
        """
        INSERT INTO health.sync_state (source, last_cursor, last_sync_at, status, meta)
        VALUES ('garmin_lifting_sets', %s, now(), %s, %s)
        ON CONFLICT (source) DO UPDATE SET
          last_cursor = EXCLUDED.last_cursor,
          last_sync_at = EXCLUDED.last_sync_at,
          status = EXCLUDED.status,
          meta = EXCLUDED.meta
        """,
        (
            CUTOFF_DATE,
            "ok" if not errors else "partial",
            Json({
                "activities_considered": len(acts),
                "raw_upserts": raw_upserts,
                "fact_rows": fact_rows,
                "errors": errors[:20],
            }),
        ),
    )

    conn.commit()

    # quick ready metrics
    cur.execute("SELECT count(*) FROM health.garmin_exercise_sets_raw")
    raw_total = cur.fetchone()[0]
    cur.execute("SELECT count(*) FROM health.lifting_set_facts")
    fact_total = cur.fetchone()[0]
    cur.execute("SELECT min(activity_start_utc::date), max(activity_start_utc::date) FROM health.lifting_set_facts")
    dmin, dmax = cur.fetchone()

    conn.close()

    print(json.dumps({
        "ok": True,
        "activities_considered": len(acts),
        "raw_upserts": raw_upserts,
        "fact_rows_written": fact_rows,
        "raw_total": raw_total,
        "fact_total": fact_total,
        "date_range": [str(dmin) if dmin else None, str(dmax) if dmax else None],
        "errors": errors,
    }, indent=2))


if __name__ == "__main__":
    main()
