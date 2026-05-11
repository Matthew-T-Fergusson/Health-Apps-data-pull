#!/usr/bin/env python3
"""
Manual activity capture + optional auto-linking to Garmin/Strava records.

Decision log:
- Keep manual captures in their own raw table for traceability.
- Do not overwrite provider raw tables with inferred/screenshot data.
- Optionally create linkage records to avoid double-counting when watch/app sync appears later.
"""
import argparse
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

from common_env import load_env

import psycopg2
from psycopg2.extras import Json


WORKSPACE_DIR = Path(__file__).resolve().parents[1]
ENV_PATH = os.getenv("ENV_PATH", str(WORKSPACE_DIR / ".env"))
SQL_PATH = os.getenv("HEALTH_MANUAL_SQL", str(WORKSPACE_DIR / "sql" / "health_manual_activity_tables.sql"))

MATCH_WINDOW_MINUTES = 90
MAX_TIME_DELTA_SECONDS = MATCH_WINDOW_MINUTES * 60
MAX_DURATION_DELTA_SECONDS = 30 * 60
TIME_SCORE_WEIGHT = 0.7
DURATION_SCORE_WEIGHT = 0.2
TYPE_MATCH_SCORE_BONUS = 0.1
MIN_LINK_SCORE = 0.45
LINK_MATCH_METHOD = "time_window_duration_type"


def parse_dt(s: str) -> datetime:
    dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def normalize_type(t: str) -> str:
    return (t or "manual").strip().lower().replace(" ", "_")


def gen_manual_id(activity_type: str, start_utc: datetime) -> str:
    stamp = start_utc.strftime("%Y%m%dT%H%M%SZ")
    return f"manual_{normalize_type(activity_type)}_{stamp}_{uuid.uuid4().hex[:8]}"


def find_best_link(cur, start_utc: datetime, moving_time_s: int | None, activity_type: str):
    # Heuristic: nearest timestamp within MATCH_WINDOW_MINUTES + duration proximity if available.
    cur.execute(
        """
        WITH candidates AS (
          SELECT 'garmin' AS src, external_activity_id, start_time_utc, moving_time_s, activity_type
          FROM health.activities_garmin_raw
          WHERE start_time_utc BETWEEN %s::timestamptz - make_interval(mins => %s) AND %s::timestamptz + make_interval(mins => %s)
          UNION ALL
          SELECT 'strava' AS src, external_activity_id, start_time_utc, moving_time_s, activity_type
          FROM health.activities_strava_raw
          WHERE start_time_utc BETWEEN %s::timestamptz - make_interval(mins => %s) AND %s::timestamptz + make_interval(mins => %s)
        )
        SELECT src, external_activity_id,
               abs(extract(epoch from (start_time_utc - %s::timestamptz))) AS dt_sec,
               CASE
                 WHEN %s::int IS NULL OR moving_time_s IS NULL THEN NULL
                 ELSE abs(moving_time_s - %s::int)
               END AS dur_diff,
               activity_type
        FROM candidates
        ORDER BY dt_sec ASC
        LIMIT 20
        """,
        (
            start_utc, MATCH_WINDOW_MINUTES, start_utc, MATCH_WINDOW_MINUTES,
            start_utc, MATCH_WINDOW_MINUTES, start_utc, MATCH_WINDOW_MINUTES,
            start_utc, moving_time_s, moving_time_s,
        ),
    )
    rows = cur.fetchall()
    if not rows:
        return None

    best = None
    best_score = -1.0
    normalized_manual_type = normalize_type(activity_type)
    for source, external_id, time_delta_seconds, duration_delta_seconds, source_type in rows:
        score = 1.0
        score -= min(float(time_delta_seconds or 0) / MAX_TIME_DELTA_SECONDS, 1.0) * TIME_SCORE_WEIGHT
        if duration_delta_seconds is not None:
            score -= min(float(duration_delta_seconds) / MAX_DURATION_DELTA_SECONDS, 1.0) * DURATION_SCORE_WEIGHT
        normalized_source_type = normalize_type(source_type or "")
        if normalized_manual_type and normalized_source_type and (
            normalized_manual_type in normalized_source_type or normalized_source_type in normalized_manual_type
        ):
            score += TYPE_MATCH_SCORE_BONUS
        if score > best_score:
            best_score = score
            best = (source, external_id, score, LINK_MATCH_METHOD)

    if best and best[2] >= MIN_LINK_SCORE:
        return best
    return None


def main():
    ap = argparse.ArgumentParser(description="Capture manual activity + optional auto-link.")
    ap.add_argument("--start", required=True, help="ISO datetime for activity start")
    ap.add_argument("--activity-type", required=True, help="e.g. treadmill_manual, strength_manual")
    ap.add_argument("--duration-min", type=float, default=None)
    ap.add_argument("--elapsed-min", type=float, default=None)
    ap.add_argument("--distance-mi", type=float, default=None)
    ap.add_argument("--distance-km", type=float, default=None)
    ap.add_argument("--calories", type=float, default=None)
    ap.add_argument("--avg-hr", type=int, default=None)
    ap.add_argument("--max-hr", type=int, default=None)
    ap.add_argument("--notes", default="")
    ap.add_argument("--capture-source", default="chat_screenshot")
    ap.add_argument("--external-id", default="")
    ap.add_argument("--evidence-json", default="{}", help="JSON string with screenshot/message metadata")
    ap.add_argument("--no-auto-link", action="store_true")
    args = ap.parse_args()

    load_env(ENV_PATH)

    start_utc = parse_dt(args.start)
    activity_type = normalize_type(args.activity_type)
    moving_time_s = int(args.duration_min * 60) if args.duration_min is not None else None
    elapsed_time_s = int(args.elapsed_min * 60) if args.elapsed_min is not None else moving_time_s

    distance_m = None
    if args.distance_km is not None:
        distance_m = float(args.distance_km) * 1000.0
    elif args.distance_mi is not None:
        distance_m = float(args.distance_mi) * 1609.344

    external_id = args.external_id.strip() or gen_manual_id(activity_type, start_utc)
    evidence = json.loads(args.evidence_json or "{}")

    conn = psycopg2.connect(
        host=os.getenv("PGHOST", "127.0.0.1"),
        port=os.getenv("PGPORT", "5432"),
        dbname=os.getenv("PGDATABASE", "health_ops"),
        user=os.getenv("PGUSER", "lex"),
        password=os.getenv("PGPASSWORD") or os.getenv("POSTGRES_PASSWORD"),
    )
    conn.autocommit = False
    cur = conn.cursor()

    # Ensure tables/view exist.
    cur.execute(Path(SQL_PATH).read_text())

    raw_payload = {
        "manual": True,
        "capture_source": args.capture_source,
        "notes": args.notes,
        "entered_at_utc": datetime.now(timezone.utc).isoformat(),
    }

    cur.execute(
        """
        INSERT INTO health.activities_manual_raw (
          external_activity_id, start_time_utc, activity_type,
          moving_time_s, elapsed_time_s, distance_m, calories,
          avg_hr, max_hr, notes, capture_source, evidence_json, raw_json, updated_at
        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,now())
        ON CONFLICT (external_activity_id) DO UPDATE SET
          start_time_utc=EXCLUDED.start_time_utc,
          activity_type=EXCLUDED.activity_type,
          moving_time_s=EXCLUDED.moving_time_s,
          elapsed_time_s=EXCLUDED.elapsed_time_s,
          distance_m=EXCLUDED.distance_m,
          calories=EXCLUDED.calories,
          avg_hr=EXCLUDED.avg_hr,
          max_hr=EXCLUDED.max_hr,
          notes=EXCLUDED.notes,
          capture_source=EXCLUDED.capture_source,
          evidence_json=EXCLUDED.evidence_json,
          raw_json=EXCLUDED.raw_json,
          updated_at=now()
        """,
        (
            external_id,
            start_utc,
            activity_type,
            moving_time_s,
            elapsed_time_s,
            distance_m,
            args.calories,
            args.avg_hr,
            args.max_hr,
            args.notes,
            args.capture_source,
            Json(evidence),
            Json(raw_payload),
        ),
    )

    link = None
    if not args.no_auto_link:
        link = find_best_link(cur, start_utc, moving_time_s, activity_type)
        if link:
            src, linked_id, confidence, method = link
            cur.execute(
                """
                INSERT INTO health.activity_manual_links (
                  manual_external_activity_id, linked_source, linked_external_activity_id,
                  match_confidence, match_method, status, updated_at
                ) VALUES (%s,%s,%s,%s,%s,'active',now())
                ON CONFLICT (manual_external_activity_id, linked_source, linked_external_activity_id)
                DO UPDATE SET
                  match_confidence=EXCLUDED.match_confidence,
                  match_method=EXCLUDED.match_method,
                  status='active',
                  updated_at=now()
                """,
                (external_id, src, linked_id, confidence, method),
            )

    conn.commit()
    cur.close()
    conn.close()

    print(
        json.dumps(
            {
                "ok": True,
                "manual_external_activity_id": external_id,
                "start_time_utc": start_utc.isoformat(),
                "activity_type": activity_type,
                "auto_link": {
                    "linked": bool(link),
                    "source": link[0] if link else None,
                    "linked_external_activity_id": link[1] if link else None,
                    "confidence": round(link[2], 3) if link else None,
                },
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
