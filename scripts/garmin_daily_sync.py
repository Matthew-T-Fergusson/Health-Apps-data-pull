#!/usr/bin/env python3
import argparse
import json
import os
import time
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import psycopg2
from common_env import load_env
from garminconnect import Garmin
from health_metrics import emit_metric, warn_metrics_failure
from psycopg2.extras import Json

WORKSPACE_DIR = Path(__file__).resolve().parents[1]
ENV_PATH = os.getenv("ENV_PATH", str(WORKSPACE_DIR / ".env"))
ENRICH_SQL_PATH = os.getenv("HEALTH_GARMIN_ENRICH_SQL", str(WORKSPACE_DIR / "sql" / "health_garmin_enrichment_tables.sql"))
DEFAULT_TOKENSTORE = os.getenv("GARMIN_TOKENSTORE", str(WORKSPACE_DIR / "output" / "garmin" / "tokenstore"))

DAILY_METRIC_FIELDS = [
    "resting_hr",
    "hrv_ms",
    "stress_avg",
    "body_battery_avg",
    "steps",
    "calories_total",
    "sleep_seconds",
]


def parse_args():
    parser = argparse.ArgumentParser(description="Garmin daily wellness sync/backfill")
    parser.add_argument("--mode", choices=["incremental", "backfill"], default="incremental")
    parser.add_argument("--since", help="Inclusive backfill start date, YYYY-MM-DD")
    parser.add_argument("--until", help="Inclusive backfill end date, YYYY-MM-DD")
    parser.add_argument(
        "--delay-seconds",
        type=float,
        default=None,
        help="Delay between dates; backfill defaults to GARMIN_BACKFILL_DELAY_SECONDS or 3 seconds",
    )
    parser.add_argument("--max-days", type=int, default=int(os.getenv("GARMIN_BACKFILL_MAX_DAYS", "31")))
    parser.add_argument(
        "--resume-job-id",
        type=int,
        help="Resume an existing backfill job by retrying dates not already success/skipped",
    )
    return parser.parse_args()


def _parse_date(value: str, label: str) -> date:
    try:
        return date.fromisoformat(value)
    except Exception as exc:
        raise SystemExit(f"Invalid {label} date {value!r}; expected YYYY-MM-DD") from exc


def build_sync_dates(args, today: date) -> list[str]:
    if args.mode == "incremental":
        days = int(os.getenv("GARMIN_SYNC_DAYS", "7"))
        return [(today - timedelta(days=i)).isoformat() for i in range(1, days + 1)]

    if not args.since or not args.until:
        raise SystemExit("Backfill mode requires --since YYYY-MM-DD and --until YYYY-MM-DD")
    since = _parse_date(args.since, "--since")
    until = _parse_date(args.until, "--until")
    if since > until:
        raise SystemExit("Backfill --since must be <= --until")
    if until > today:
        raise SystemExit("Backfill --until cannot be in the future")
    total_days = (until - since).days + 1
    if total_days > args.max_days:
        raise SystemExit(
            f"Backfill range has {total_days} days; max is {args.max_days}. "
            "Raise --max-days intentionally if needed."
        )
    return [(since + timedelta(days=i)).isoformat() for i in range(total_days)]


def ensure_backfill_tables(cur):
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS health.backfill_jobs (
          job_id BIGSERIAL PRIMARY KEY,
          source TEXT NOT NULL,
          mode TEXT NOT NULL DEFAULT 'backfill',
          since_date DATE NOT NULL,
          until_date DATE NOT NULL,
          status TEXT NOT NULL DEFAULT 'running',
          write_policy TEXT NOT NULL DEFAULT 'merge_safe',
          requested_by TEXT,
          started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          finished_at TIMESTAMPTZ,
          last_progress_date DATE,
          dates_total INTEGER NOT NULL DEFAULT 0,
          dates_succeeded INTEGER NOT NULL DEFAULT 0,
          dates_empty INTEGER NOT NULL DEFAULT 0,
          dates_failed INTEGER NOT NULL DEFAULT 0,
          meta JSONB DEFAULT '{}'::jsonb
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS health.backfill_job_dates (
          job_id BIGINT NOT NULL REFERENCES health.backfill_jobs(job_id) ON DELETE CASCADE,
          metric_date DATE NOT NULL,
          status TEXT NOT NULL DEFAULT 'pending',
          started_at TIMESTAMPTZ,
          finished_at TIMESTAMPTZ,
          rows_written INTEGER NOT NULL DEFAULT 0,
          conflict_count INTEGER NOT NULL DEFAULT 0,
          error_message TEXT,
          meta JSONB DEFAULT '{}'::jsonb,
          PRIMARY KEY (job_id, metric_date)
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS health.backfill_value_conflicts (
          id BIGSERIAL PRIMARY KEY,
          job_id BIGINT REFERENCES health.backfill_jobs(job_id) ON DELETE SET NULL,
          metric_date DATE NOT NULL,
          table_name TEXT NOT NULL,
          field_name TEXT NOT NULL,
          existing_value TEXT,
          incoming_value TEXT,
          decision TEXT NOT NULL,
          reason TEXT NOT NULL,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )


def start_backfill_job(cur, source: str, dates: list[str], args) -> int | None:
    if args.mode != "backfill":
        return None
    ensure_backfill_tables(cur)
    cur.execute(
        """
        INSERT INTO health.backfill_jobs (
          source, mode, since_date, until_date, status, write_policy, requested_by, dates_total, meta
        ) VALUES (%s, 'backfill', %s, %s, 'running', 'merge_safe', %s, %s, %s)
        RETURNING job_id
        """,
        (
            source,
            dates[0],
            dates[-1],
            os.getenv("BACKFILL_REQUESTED_BY", "cli"),
            len(dates),
            Json({"delay_seconds": args.delay_seconds, "max_days": args.max_days}),
        ),
    )
    job_id = cur.fetchone()[0]
    for metric_date in dates:
        cur.execute(
            """
            INSERT INTO health.backfill_job_dates (job_id, metric_date, status)
            VALUES (%s, %s, 'pending')
            ON CONFLICT (job_id, metric_date) DO NOTHING
            """,
            (job_id, metric_date),
        )
    return job_id


def resume_backfill_job(cur, job_id: int) -> list[str]:
    ensure_backfill_tables(cur)
    cur.execute("SELECT 1 FROM health.backfill_jobs WHERE job_id=%s", (job_id,))
    if not cur.fetchone():
        raise SystemExit(f"No backfill job found for --resume-job-id {job_id}")
    cur.execute(
        """
        SELECT metric_date::text
        FROM health.backfill_job_dates
        WHERE job_id=%s AND status NOT IN ('success', 'skipped')
        ORDER BY metric_date
        """,
        (job_id,),
    )
    dates = [row[0] for row in cur.fetchall()]
    cur.execute(
        """
        UPDATE health.backfill_jobs
        SET status='running',
            finished_at=NULL,
            meta=COALESCE(meta, '{}'::jsonb) || %s::jsonb
        WHERE job_id=%s
        """,
        (json.dumps({"resumed": True}), job_id),
    )
    return dates


def mark_backfill_date(cur, job_id, metric_date: str, status: str, *, rows_written=0, conflict_count=0, error_message=None, meta=None):
    if not job_id:
        return
    cur.execute(
        """
        UPDATE health.backfill_job_dates
        SET status=%s,
            started_at=COALESCE(started_at, now()),
            finished_at=CASE WHEN %s IN ('success','empty_payload','failed','skipped') THEN now() ELSE finished_at END,
            rows_written=%s,
            conflict_count=%s,
            error_message=%s,
            meta=%s
        WHERE job_id=%s AND metric_date=%s
        """,
        (status, status, rows_written, conflict_count, error_message, Json(meta or {}), job_id, metric_date),
    )
    cur.execute(
        """
        UPDATE health.backfill_jobs
        SET last_progress_date=%s,
            dates_succeeded=(SELECT count(*) FROM health.backfill_job_dates WHERE job_id=%s AND status='success'),
            dates_empty=(SELECT count(*) FROM health.backfill_job_dates WHERE job_id=%s AND status='empty_payload'),
            dates_failed=(SELECT count(*) FROM health.backfill_job_dates WHERE job_id=%s AND status='failed')
        WHERE job_id=%s
        """,
        (metric_date, job_id, job_id, job_id, job_id),
    )


def finish_backfill_job(cur, job_id, status: str, meta: dict):
    if not job_id:
        return
    cur.execute(
        """
        UPDATE health.backfill_jobs
        SET status=%s,
            finished_at=now(),
            dates_succeeded=(SELECT count(*) FROM health.backfill_job_dates WHERE job_id=%s AND status='success'),
            dates_empty=(SELECT count(*) FROM health.backfill_job_dates WHERE job_id=%s AND status='empty_payload'),
            dates_failed=(SELECT count(*) FROM health.backfill_job_dates WHERE job_id=%s AND status='failed'),
            meta=COALESCE(meta, '{}'::jsonb) || %s::jsonb
        WHERE job_id=%s
        """,
        (status, job_id, job_id, job_id, json.dumps(meta), job_id),
    )


def log_daily_metric_conflicts(cur, job_id, metric_date: str, incoming: dict) -> int:
    if not job_id:
        return 0
    cur.execute(
        """
        SELECT resting_hr, hrv_ms, stress_avg, body_battery_avg, steps, calories_total, sleep_seconds
        FROM health.daily_metrics
        WHERE source='garmin' AND metric_date=%s
        """,
        (metric_date,),
    )
    row = cur.fetchone()
    if not row:
        return 0
    conflicts = 0
    existing = dict(zip(DAILY_METRIC_FIELDS, row, strict=True))
    for field in DAILY_METRIC_FIELDS:
        old = existing.get(field)
        new = incoming.get(field)
        if old is None or new is None or str(old) == str(new):
            continue
        conflicts += 1
        cur.execute(
            """
            INSERT INTO health.backfill_value_conflicts (
              job_id, metric_date, table_name, field_name, existing_value, incoming_value, decision, reason
            ) VALUES (%s,%s,'health.daily_metrics',%s,%s,%s,'kept_existing','merge_safe_conflict')
            """,
            (job_id, metric_date, field, str(old), str(new)),
        )
    return conflicts


def dt_from_ms(ms):
    if not ms:
        return None
    return datetime.fromtimestamp(ms / 1000, tz=UTC)


def _to_float(v: Any):
    try:
        if v is None:
            return None
        return float(v)
    except Exception:
        return None


def _first_num(d: dict, keys: list[str]):
    if not isinstance(d, dict):
        return None
    for k in keys:
        if k in d:
            n = _to_float(d.get(k))
            if n is not None:
                return n
    return None


def _latest_body_battery_value(values):
    """Extract the latest non-null Body Battery value from Garmin array payloads.

    Garmin currently returns Body Battery arrays in at least two shapes:
      - [timestamp_ms, value]
      - [timestamp_ms, descriptor, value, version]
    Placeholder days may include arrays full of nulls; ignore those.
    """
    if not isinstance(values, list):
        return None
    latest = None
    latest_ts = None
    for row in values:
        if not isinstance(row, list) or len(row) < 2:
            continue
        ts = row[0] if isinstance(row[0], (int, float)) else None
        candidates = []
        if len(row) >= 3 and isinstance(row[1], str):
            candidates.append(row[2])
        candidates.append(row[1])
        for candidate in candidates:
            n = _to_float(candidate)
            if n is None:
                continue
            if latest_ts is None or ts is None or ts >= latest_ts:
                latest = n
                latest_ts = ts
            break
    return latest


def _is_empty_wellness_payload(stats: dict, *, hrv_ms, stress_avg, body_battery_avg, sleep_seconds):
    if not isinstance(stats, dict):
        return True
    meaningful = [
        stats.get("restingHeartRate"),
        stats.get("totalSteps"),
        stats.get("totalKilocalories"),
        hrv_ms,
        stress_avg,
        body_battery_avg,
        sleep_seconds,
    ]
    return stats.get("includesWellnessData") is False and all(v is None for v in meaningful)


def _jsonish(v: Any):
    """Garmin GraphQL scalar fields sometimes arrive as JSON strings."""
    if isinstance(v, str):
        try:
            return json.loads(v)
        except Exception:
            return v
    return v


def _walk_dicts(v: Any):
    v = _jsonish(v)
    if isinstance(v, dict):
        yield v
        for child in v.values():
            yield from _walk_dicts(child)
    elif isinstance(v, list):
        for child in v:
            yield from _walk_dicts(child)


def _find_daily_record(v: Any, target_date: str):
    """Best-effort extractor for Garmin service/GraphQL payload variants."""
    for d in _walk_dicts(v):
        if d.get("calendarDate") == target_date or d.get("date") == target_date:
            return d
    return None


def _graphql_scalar(g: Garmin, query: str, key: str):
    try:
        payload = g.query_garmin_graphql({"query": query}) or {}
        return _jsonish((payload.get("data") or {}).get(key))
    except Exception:
        return None


def _graphql_daily_fallbacks(g: Garmin, d: str):
    """Pull the newer Garmin GraphQL scalar endpoints when classic endpoints are empty.

    This is intentionally defensive: python-garminconnect's demo now documents
    these endpoints, but Garmin returns different scalar/list/string shapes over
    time and by account. We keep the raw payloads and only extract fields when a
    date-specific record is present.
    """
    out: dict[str, Any] = {"summary": {}, "hrv": {}, "sleep": {}, "stress": {}}

    summary = _graphql_scalar(
        g,
        f'query{{userDailySummaryV2Scalar(startDate:"{d}", endDate:"{d}")}}',
        "userDailySummaryV2Scalar",
    )
    rec = _find_daily_record(summary, d)
    if isinstance(rec, dict):
        out["summary"] = rec

    hrv = _graphql_scalar(
        g,
        f'query{{heartRateVariabilityScalar(startDate:"{d}", endDate:"{d}")}}',
        "heartRateVariabilityScalar",
    )
    rec = _find_daily_record(hrv, d)
    if isinstance(rec, dict):
        out["hrv"] = rec

    sleep = _graphql_scalar(
        g,
        f'query{{sleepSummariesScalar(startDate:"{d}", endDate:"{d}")}}',
        "sleepSummariesScalar",
    )
    rec = _find_daily_record(sleep, d)
    if isinstance(rec, dict):
        out["sleep"] = rec

    stress = _graphql_scalar(
        g,
        f'query{{epochChartScalar(date:"{d}", include:["stress"])}}',
        "epochChartScalar",
    )
    if isinstance(stress, dict):
        out["stress"] = stress

    out["raw"] = {"summary": summary, "hrv": hrv, "sleep": sleep, "stress": stress}
    return out


def _extract_body_comp_kg(raw: dict):
    """Best-effort extraction from Garmin payload variants."""
    empty = {
        "weight_kg": None,
        "body_fat_pct": None,
        "muscle_mass_kg": None,
        "bone_mass_kg": None,
        "body_water_pct": None,
        "bmi": None,
        "visceral_fat": None,
        "metabolic_age": None,
        "physique_rating": None,
    }
    if not isinstance(raw, dict):
        return empty

    # some endpoints return nested values and list records
    nested_candidates = [raw]
    for k in ("dailyWeightSummary", "latestBodyComposition", "bodyComposition", "allMetrics", "totalAverage"):
        v = raw.get(k)
        if isinstance(v, dict):
            nested_candidates.append(v)

    for k in ("dateWeightList", "weightSamples", "bodyCompositionSamples"):
        v = raw.get(k)
        if isinstance(v, list):
            for item in v:
                if isinstance(item, dict):
                    nested_candidates.append(item)

    weight_kg = body_fat_pct = muscle_mass_kg = bone_mass_kg = body_water_pct = bmi = None
    visceral_fat = metabolic_age = physique_rating = None

    for d in nested_candidates:
        if weight_kg is None:
            weight_kg = _first_num(d, ["weight", "weightKg", "bodyWeight", "bodyWeightKg"])
            # Garmin often returns grams in `weight` (e.g., 90718)
            if weight_kg is not None and weight_kg > 500:
                weight_kg = weight_kg / 1000.0
            if weight_kg is None:
                g = _first_num(d, ["weightInGrams", "weightGrams"])
                if g is not None:
                    weight_kg = g / 1000.0
        if body_fat_pct is None:
            body_fat_pct = _first_num(d, ["bodyFat", "bodyFatPercentage", "bodyFatPct"])
        if muscle_mass_kg is None:
            muscle_mass_kg = _first_num(d, ["muscleMass", "muscleMassKg", "skeletalMuscleMass"])
        if bone_mass_kg is None:
            bone_mass_kg = _first_num(d, ["boneMass", "boneMassKg"])
        if body_water_pct is None:
            body_water_pct = _first_num(d, ["bodyWater", "bodyWaterPct", "bodyWaterPercentage"])
        if bmi is None:
            bmi = _first_num(d, ["bmi", "bodyMassIndex"])
        if visceral_fat is None:
            visceral_fat = _first_num(d, ["visceralFat"])
        if metabolic_age is None:
            metabolic_age = _first_num(d, ["metabolicAge"])
        if physique_rating is None:
            physique_rating = _first_num(d, ["physiqueRating"])

    return {
        "weight_kg": weight_kg,
        "body_fat_pct": body_fat_pct,
        "muscle_mass_kg": muscle_mass_kg,
        "bone_mass_kg": bone_mass_kg,
        "body_water_pct": body_water_pct,
        "bmi": bmi,
        "visceral_fat": visceral_fat,
        "metabolic_age": metabolic_age,
        "physique_rating": physique_rating,
    }


def main():
    args = parse_args()
    load_env(ENV_PATH)

    email = os.getenv("GARMIN_EMAIL")
    password = os.getenv("GARMIN_PASSWORD")
    if not email or not password:
        raise RuntimeError("Missing GARMIN_EMAIL or GARMIN_PASSWORD")

    conn = psycopg2.connect(
        host=os.getenv("PGHOST", "127.0.0.1"),
        port=os.getenv("PGPORT", "5432"),
        dbname=os.getenv("PGDATABASE", "health_ops"),
        user=os.getenv("PGUSER", "lex"),
        password=os.getenv("PGPASSWORD") or os.getenv("POSTGRES_PASSWORD"),
    )
    conn.autocommit = False
    cur = conn.cursor()

    # Ensure extended body composition table exists
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS health.body_composition_daily (
          id BIGSERIAL PRIMARY KEY,
          source TEXT NOT NULL,
          metric_date DATE NOT NULL,
          weight_kg DOUBLE PRECISION,
          body_fat_pct DOUBLE PRECISION,
          muscle_mass_kg DOUBLE PRECISION,
          bone_mass_kg DOUBLE PRECISION,
          body_water_pct DOUBLE PRECISION,
          bmi DOUBLE PRECISION,
          visceral_fat DOUBLE PRECISION,
          metabolic_age DOUBLE PRECISION,
          physique_rating DOUBLE PRECISION,
          raw_json JSONB,
          created_at TIMESTAMPTZ DEFAULT now(),
          updated_at TIMESTAMPTZ DEFAULT now(),
          UNIQUE(source, metric_date)
        )
        """
    )
    # forward-compatible add columns for existing deployments
    cur.execute("ALTER TABLE health.body_composition_daily ADD COLUMN IF NOT EXISTS visceral_fat DOUBLE PRECISION")
    cur.execute("ALTER TABLE health.body_composition_daily ADD COLUMN IF NOT EXISTS metabolic_age DOUBLE PRECISION")
    cur.execute("ALTER TABLE health.body_composition_daily ADD COLUMN IF NOT EXISTS physique_rating DOUBLE PRECISION")

    # additional Garmin enrichment tables
    enrich_sql = Path(ENRICH_SQL_PATH)
    if enrich_sql.exists():
        cur.execute(enrich_sql.read_text())

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

    today = date.today()
    sync_dates = build_sync_dates(args, today)
    if args.resume_job_id and args.mode != "backfill":
        raise SystemExit("--resume-job-id requires --mode backfill")
    if args.resume_job_id:
        backfill_job_id = args.resume_job_id
        sync_dates = resume_backfill_job(cur, backfill_job_id)
    else:
        backfill_job_id = start_backfill_job(cur, "garmin_daily", sync_dates, args)
    days = len(sync_dates)
    if backfill_job_id:
        conn.commit()

    if args.mode == "backfill" and not sync_dates:
        finish_backfill_job(cur, backfill_job_id, "ok", {"days_attempted": 0, "resume_empty": bool(args.resume_job_id)})
        conn.commit()
        cur.close()
        conn.close()
        print(json.dumps({"ok": True, "status": "ok", "mode": args.mode, "backfill_job_id": backfill_job_id, "days_attempted": 0}, indent=2))
        return

    delay_seconds = args.delay_seconds
    if delay_seconds is None and args.mode == "backfill":
        delay_seconds = float(os.getenv("GARMIN_BACKFILL_DELAY_SECONDS", "3"))
    elif delay_seconds is None:
        delay_seconds = 0

    ok = 0
    errors = []
    critical_missing_dates = []

    for idx, d in enumerate(sync_dates):
        try:
            mark_backfill_date(cur, backfill_job_id, d, "running")
            # stats+body is richer and includes weight on many accounts
            stats = g.get_stats_and_body(d) or {}
            sleep = g.get_sleep_data(d) or {}

            # best effort body composition endpoint (availability depends on account/device)
            body_comp_raw = {}
            try:
                body_comp_raw = g.get_body_composition(d) or {}
            except Exception:
                body_comp_raw = {}

            # best effort HRV endpoint
            hrv_raw = {}
            try:
                hrv_raw = g.get_hrv_data(d) or {}
            except Exception:
                hrv_raw = {}

            # best effort stress endpoint. Garmin sometimes returns an empty
            # usersummary payload while the wellness endpoint still has the
            # aggregate/epoch arrays, so use it as an explicit fallback.
            stress_raw = {}
            try:
                stress_raw = g.get_stress_data(d) or {}
            except Exception:
                stress_raw = {}

            # body battery daily/events
            bb_daily = []
            try:
                bb_daily = g.get_body_battery(d) or []
            except Exception:
                bb_daily = []

            bb_events = []
            try:
                bb_events = g.get_body_battery_events(d) or []
            except Exception:
                bb_events = []

            reload_requested = False
            reload_result = None
            gql_fallbacks = {"summary": {}, "hrv": {}, "sleep": {}, "stress": {}, "raw": {}}

            # Garmin sometimes offloads/withholds wellness epochs. The app's
            # "Reload chart" button maps to /wellness-service/wellness/epoch/request/{date};
            # trigger it automatically for placeholder payloads, then retry once.
            prelim_sleep_seconds = (sleep.get("dailySleepDTO") or {}).get("sleepTimeSeconds") if isinstance(sleep, dict) else None
            prelim_stress_avg = _first_num(stats, ["averageStressLevel", "avgStressLevel"])
            if prelim_stress_avg is None:
                prelim_stress_avg = _first_num(stress_raw, ["avgStressLevel", "averageStressLevel"])
            prelim_body_battery = _first_num(stats, ["bodyBatteryMostRecentValue", "bodyBatteryAtWakeTime", "bodyBatteryChargedValue"])
            if prelim_body_battery is None and isinstance(stress_raw, dict):
                prelim_body_battery = _latest_body_battery_value(stress_raw.get("bodyBatteryValuesArray"))
            prelim_hrv_summary = (hrv_raw or {}).get("hrvSummary") if isinstance(hrv_raw, dict) else {}
            prelim_hrv = _first_num(prelim_hrv_summary or {}, ["lastNightAvg", "weeklyAvg"])
            if prelim_hrv is None and isinstance(sleep, dict):
                prelim_hrv = _first_num(sleep, ["avgOvernightHrv"])

            if _is_empty_wellness_payload(
                stats,
                hrv_ms=prelim_hrv,
                stress_avg=prelim_stress_avg,
                body_battery_avg=prelim_body_battery,
                sleep_seconds=prelim_sleep_seconds,
            ):
                reload_requested = True
                try:
                    reload_result = g.request_reload(d)
                    wait_s = float(os.getenv("GARMIN_RELOAD_WAIT_SECONDS", "8"))
                    if wait_s > 0:
                        time.sleep(wait_s)
                    stats = g.get_stats_and_body(d) or {}
                    sleep = g.get_sleep_data(d) or {}
                    try:
                        hrv_raw = g.get_hrv_data(d) or {}
                    except Exception:
                        hrv_raw = {}
                    try:
                        stress_raw = g.get_stress_data(d) or {}
                    except Exception:
                        stress_raw = {}
                    try:
                        bb_daily = g.get_body_battery(d) or []
                    except Exception:
                        bb_daily = []
                    try:
                        bb_events = g.get_body_battery_events(d) or []
                    except Exception:
                        bb_events = []
                except Exception as e:
                    reload_result = {"error": str(e)}

            gql_fallbacks = _graphql_daily_fallbacks(g, d)

            dto = sleep.get("dailySleepDTO") or {}

            bb = (bb_daily[0] if isinstance(bb_daily, list) and bb_daily else {}) if bb_daily is not None else {}

            gql_summary = gql_fallbacks.get("summary") if isinstance(gql_fallbacks, dict) else {}
            gql_hrv = gql_fallbacks.get("hrv") if isinstance(gql_fallbacks, dict) else {}
            gql_sleep = gql_fallbacks.get("sleep") if isinstance(gql_fallbacks, dict) else {}

            stress_avg = _first_num(stats, ["averageStressLevel", "avgStressLevel"])
            if stress_avg is None:
                stress_avg = _first_num(stress_raw, ["avgStressLevel", "averageStressLevel"])
            if stress_avg is None and isinstance(gql_summary, dict):
                stress_avg = _first_num(gql_summary, ["averageStressLevel", "avgStressLevel", "stressAvg"])
            body_battery_avg = _first_num(
                stats,
                ["bodyBatteryMostRecentValue", "bodyBatteryAtWakeTime", "bodyBatteryChargedValue"],
            )
            if body_battery_avg is None:
                body_battery_avg = _latest_body_battery_value(stress_raw.get("bodyBatteryValuesArray"))
            if body_battery_avg is None:
                body_battery_avg = _latest_body_battery_value(bb.get("bodyBatteryValuesArray")) if isinstance(bb, dict) else None
            if body_battery_avg is None and isinstance(gql_summary, dict):
                body_battery_avg = _first_num(gql_summary, ["bodyBatteryMostRecentValue", "bodyBatteryAtWakeTime", "bodyBatteryChargedValue", "bodyBattery"])
            # HRV: prefer explicit overnight value from get_hrv_data
            hrv_summary = (hrv_raw or {}).get("hrvSummary") or {}
            hrv_ms = _first_num(hrv_summary, ["lastNightAvg", "weeklyAvg"])
            if hrv_ms is None:
                hrv_ms = _first_num(sleep, ["avgOvernightHrv"])
            if hrv_ms is None:
                hrv_ms = _first_num(stats, ["hrvValue", "hrvMs", "lastNightAvgHrv"])
            if hrv_ms is None and isinstance(gql_hrv, dict):
                hrv_ms = _first_num(gql_hrv, ["lastNightAvg", "lastNightAverage", "hrvValue", "hrvMs", "weeklyAvg"])
            if hrv_ms is None and isinstance(gql_sleep, dict):
                hrv_ms = _first_num(gql_sleep, ["avgOvernightHrv", "averageOvernightHrv", "lastNightAvg"])

            sleep_seconds = dto.get("sleepTimeSeconds")
            if sleep_seconds is None and isinstance(gql_sleep, dict):
                sleep_seconds = _first_num(gql_sleep, ["sleepTimeSeconds", "durationInSeconds", "totalSleepSeconds"])
            raw_daily = dict(stats) if isinstance(stats, dict) else {}
            raw_daily["_garmin_sources"] = {
                "stats_empty_wellness_payload": _is_empty_wellness_payload(
                    stats,
                    hrv_ms=hrv_ms,
                    stress_avg=stress_avg,
                    body_battery_avg=body_battery_avg,
                    sleep_seconds=sleep_seconds,
                ),
                "hrv_raw": hrv_raw if isinstance(hrv_raw, dict) else {},
                "stress_raw": stress_raw if isinstance(stress_raw, dict) else {},
                "bb_daily": bb_daily if isinstance(bb_daily, list) else [],
                "sleep_daily_keys": sorted(sleep.keys()) if isinstance(sleep, dict) else [],
                "reload_requested": reload_requested,
                "reload_result": reload_result,
                "graphql_fallbacks": gql_fallbacks,
            }

            critical_values = {
                "resting_hr": stats.get("restingHeartRate"),
                "hrv_ms": hrv_ms,
                "stress_avg": stress_avg,
                "body_battery_avg": body_battery_avg,
                "steps": stats.get("totalSteps"),
                "calories_total": stats.get("totalKilocalories"),
                "sleep_seconds": sleep_seconds,
            }
            empty_payload = all(v is None for v in critical_values.values())
            if empty_payload:
                critical_missing_dates.append(d)

            conflict_count = log_daily_metric_conflicts(cur, backfill_job_id, d, critical_values)

            # daily_metrics
            cur.execute(
                """
                INSERT INTO health.daily_metrics (
                  source, metric_date, resting_hr, hrv_ms, stress_avg, body_battery_avg,
                  steps, calories_total, sleep_seconds, raw_json, updated_at
                ) VALUES ('garmin', %s, %s, %s, %s, %s, %s, %s, %s, %s, now())
                ON CONFLICT (source, metric_date) DO UPDATE SET
                  resting_hr=COALESCE(EXCLUDED.resting_hr, health.daily_metrics.resting_hr),
                  hrv_ms=COALESCE(EXCLUDED.hrv_ms, health.daily_metrics.hrv_ms),
                  stress_avg=COALESCE(EXCLUDED.stress_avg, health.daily_metrics.stress_avg),
                  body_battery_avg=COALESCE(EXCLUDED.body_battery_avg, health.daily_metrics.body_battery_avg),
                  steps=COALESCE(EXCLUDED.steps, health.daily_metrics.steps),
                  calories_total=COALESCE(EXCLUDED.calories_total, health.daily_metrics.calories_total),
                  sleep_seconds=COALESCE(EXCLUDED.sleep_seconds, health.daily_metrics.sleep_seconds),
                  raw_json=CASE
                    WHEN EXCLUDED.resting_hr IS NULL
                     AND EXCLUDED.hrv_ms IS NULL
                     AND EXCLUDED.stress_avg IS NULL
                     AND EXCLUDED.body_battery_avg IS NULL
                     AND EXCLUDED.steps IS NULL
                     AND EXCLUDED.calories_total IS NULL
                     AND EXCLUDED.sleep_seconds IS NULL
                    THEN COALESCE(health.daily_metrics.raw_json, '{}'::jsonb)
                         || jsonb_build_object('_garmin_sources', EXCLUDED.raw_json->'_garmin_sources')
                    ELSE EXCLUDED.raw_json
                  END,
                  updated_at=now()
                """,
                (
                    d,
                    stats.get("restingHeartRate"),
                    hrv_ms,
                    stress_avg,
                    body_battery_avg,
                    stats.get("totalSteps"),
                    stats.get("totalKilocalories"),
                    sleep_seconds,
                    Json(raw_daily),
                ),
            )

            # daily vitals enrichment
            cur.execute(
                """
                INSERT INTO health.daily_vitals_garmin (
                  metric_date, avg_spo2, min_spo2, avg_respiration, min_respiration,
                  max_respiration, resting_respiration, floors_ascended, floors_descended,
                  active_seconds, highly_active_seconds, moderate_intensity_minutes,
                  vigorous_intensity_minutes, raw_json, updated_at
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,now())
                ON CONFLICT (metric_date) DO UPDATE SET
                  avg_spo2=EXCLUDED.avg_spo2,
                  min_spo2=EXCLUDED.min_spo2,
                  avg_respiration=EXCLUDED.avg_respiration,
                  min_respiration=EXCLUDED.min_respiration,
                  max_respiration=EXCLUDED.max_respiration,
                  resting_respiration=EXCLUDED.resting_respiration,
                  floors_ascended=EXCLUDED.floors_ascended,
                  floors_descended=EXCLUDED.floors_descended,
                  active_seconds=EXCLUDED.active_seconds,
                  highly_active_seconds=EXCLUDED.highly_active_seconds,
                  moderate_intensity_minutes=EXCLUDED.moderate_intensity_minutes,
                  vigorous_intensity_minutes=EXCLUDED.vigorous_intensity_minutes,
                  raw_json=EXCLUDED.raw_json,
                  updated_at=now()
                """,
                (
                    d,
                    _first_num(stats, ["averageSpo2"]),
                    _first_num(stats, ["lowestSpo2"]),
                    _first_num(stats, ["avgWakingRespirationValue", "averageRespiration"]),
                    _first_num(stats, ["lowestRespirationValue"]),
                    _first_num(stats, ["highestRespirationValue"]),
                    _first_num(stats, ["latestRespirationValue"]),
                    stats.get("floorsAscended"),
                    stats.get("floorsDescended"),
                    stats.get("activeSeconds"),
                    stats.get("highlyActiveSeconds"),
                    stats.get("moderateIntensityMinutes"),
                    stats.get("vigorousIntensityMinutes"),
                    Json(stats),
                ),
            )

            # body battery daily summary
            cur.execute(
                """
                INSERT INTO health.body_battery_daily_garmin (
                  metric_date, charged_value, drained_value, highest_value, lowest_value,
                  most_recent_value, at_wake_value, during_sleep_value,
                  start_utc, end_utc, raw_json, updated_at
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,now())
                ON CONFLICT (metric_date) DO UPDATE SET
                  charged_value=EXCLUDED.charged_value,
                  drained_value=EXCLUDED.drained_value,
                  highest_value=EXCLUDED.highest_value,
                  lowest_value=EXCLUDED.lowest_value,
                  most_recent_value=EXCLUDED.most_recent_value,
                  at_wake_value=EXCLUDED.at_wake_value,
                  during_sleep_value=EXCLUDED.during_sleep_value,
                  start_utc=EXCLUDED.start_utc,
                  end_utc=EXCLUDED.end_utc,
                  raw_json=EXCLUDED.raw_json,
                  updated_at=now()
                """,
                (
                    d,
                    _first_num(bb, ["charged"]),
                    _first_num(bb, ["drained"]),
                    _first_num(stats, ["bodyBatteryHighestValue"]),
                    _first_num(stats, ["bodyBatteryLowestValue"]),
                    _first_num(stats, ["bodyBatteryMostRecentValue"]),
                    _first_num(stats, ["bodyBatteryAtWakeTime"]),
                    _first_num(stats, ["bodyBatteryDuringSleep"]),
                    datetime.fromisoformat(str(bb.get("startTimestampGMT")).replace("Z", "+00:00")) if isinstance(bb, dict) and bb.get("startTimestampGMT") else None,
                    datetime.fromisoformat(str(bb.get("endTimestampGMT")).replace("Z", "+00:00")) if isinstance(bb, dict) and bb.get("endTimestampGMT") else None,
                    Json(bb if isinstance(bb, dict) else {}),
                ),
            )

            # body battery events (upsert by synthetic key)
            for ev in bb_events if isinstance(bb_events, list) else []:
                e = ev.get("event") if isinstance(ev, dict) else None
                if not isinstance(e, dict):
                    continue
                estart = e.get("eventStartTimeGmt")
                event_pk = f"{d}:{e.get('eventType')}:{estart}:{ev.get('activityId') or ''}"
                estart_dt = None
                try:
                    estart_dt = datetime.fromisoformat(str(estart).replace("Z", "+00:00")) if estart else None
                except Exception:
                    estart_dt = None
                cur.execute(
                    """
                    INSERT INTO health.body_battery_events_garmin (
                      event_pk, metric_date, event_type, event_start_utc, duration_ms,
                      body_battery_impact, feedback_type, short_feedback,
                      activity_id, activity_type, activity_name, raw_json, updated_at
                    ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,now())
                    ON CONFLICT (event_pk) DO UPDATE SET
                      metric_date=EXCLUDED.metric_date,
                      event_type=EXCLUDED.event_type,
                      event_start_utc=EXCLUDED.event_start_utc,
                      duration_ms=EXCLUDED.duration_ms,
                      body_battery_impact=EXCLUDED.body_battery_impact,
                      feedback_type=EXCLUDED.feedback_type,
                      short_feedback=EXCLUDED.short_feedback,
                      activity_id=EXCLUDED.activity_id,
                      activity_type=EXCLUDED.activity_type,
                      activity_name=EXCLUDED.activity_name,
                      raw_json=EXCLUDED.raw_json,
                      updated_at=now()
                    """,
                    (
                        event_pk,
                        d,
                        e.get("eventType"),
                        estart_dt,
                        e.get("durationInMilliseconds"),
                        _first_num(e, ["bodyBatteryImpact"]),
                        e.get("feedbackType"),
                        e.get("shortFeedback"),
                        ev.get("activityId"),
                        ev.get("activityType"),
                        ev.get("activityName"),
                        Json(ev),
                    ),
                )

            # body composition daily
            merged_body = {}
            merged_body.update(stats if isinstance(stats, dict) else {})
            if isinstance(body_comp_raw, dict):
                merged_body.update(body_comp_raw)
            if isinstance(hrv_raw, dict):
                merged_body["hrvSummary"] = hrv_raw.get("hrvSummary")
            bc = _extract_body_comp_kg(merged_body)
            cur.execute(
                """
                INSERT INTO health.body_composition_daily (
                  source, metric_date, weight_kg, body_fat_pct, muscle_mass_kg,
                  bone_mass_kg, body_water_pct, bmi, visceral_fat, metabolic_age,
                  physique_rating, raw_json, updated_at
                ) VALUES ('garmin', %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now())
                ON CONFLICT (source, metric_date) DO UPDATE SET
                  weight_kg=EXCLUDED.weight_kg,
                  body_fat_pct=EXCLUDED.body_fat_pct,
                  muscle_mass_kg=EXCLUDED.muscle_mass_kg,
                  bone_mass_kg=EXCLUDED.bone_mass_kg,
                  body_water_pct=EXCLUDED.body_water_pct,
                  bmi=EXCLUDED.bmi,
                  visceral_fat=EXCLUDED.visceral_fat,
                  metabolic_age=EXCLUDED.metabolic_age,
                  physique_rating=EXCLUDED.physique_rating,
                  raw_json=EXCLUDED.raw_json,
                  updated_at=now()
                """,
                (
                    d,
                    bc.get("weight_kg"),
                    bc.get("body_fat_pct"),
                    bc.get("muscle_mass_kg"),
                    bc.get("bone_mass_kg"),
                    bc.get("body_water_pct"),
                    bc.get("bmi"),
                    bc.get("visceral_fat"),
                    bc.get("metabolic_age"),
                    bc.get("physique_rating"),
                    Json(merged_body),
                ),
            )

            # sleep_sessions
            ss = dto
            external_sleep_id = str(ss.get("sleepStartTimestampGMT") or d)
            cur.execute(
                """
                INSERT INTO health.sleep_sessions (
                  source, external_sleep_id, sleep_start_utc, sleep_end_utc,
                  duration_s, deep_s, light_s, rem_s, awake_s, sleep_score, raw_json, updated_at
                ) VALUES ('garmin', %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now())
                ON CONFLICT (source, external_sleep_id) DO UPDATE SET
                  sleep_start_utc=EXCLUDED.sleep_start_utc,
                  sleep_end_utc=EXCLUDED.sleep_end_utc,
                  duration_s=EXCLUDED.duration_s,
                  deep_s=EXCLUDED.deep_s,
                  light_s=EXCLUDED.light_s,
                  rem_s=EXCLUDED.rem_s,
                  awake_s=EXCLUDED.awake_s,
                  sleep_score=EXCLUDED.sleep_score,
                  raw_json=EXCLUDED.raw_json,
                  updated_at=now()
                """,
                (
                    external_sleep_id,
                    dt_from_ms(ss.get("sleepStartTimestampGMT")),
                    dt_from_ms(ss.get("sleepEndTimestampGMT")),
                    ss.get("sleepTimeSeconds"),
                    ss.get("deepSleepSeconds"),
                    ss.get("lightSleepSeconds"),
                    ss.get("remSleepSeconds"),
                    ss.get("awakeSleepSeconds"),
                    ((sleep.get("dailySleepDTO") or {}).get("sleepScores") or {}).get("overall", {}).get("value"),
                    Json(sleep),
                ),
            )

            ok += 1
            mark_backfill_date(
                cur,
                backfill_job_id,
                d,
                "empty_payload" if empty_payload else "success",
                rows_written=0 if empty_payload else 1,
                conflict_count=conflict_count,
                meta={"write_policy": "merge_safe"},
            )
            if delay_seconds and idx < len(sync_dates) - 1:
                time.sleep(delay_seconds)
        except Exception as e:
            errors.append({"date": d, "error": str(e)})
            mark_backfill_date(cur, backfill_job_id, d, "failed", error_message=str(e))

    cur.execute(
        """
        INSERT INTO health.sync_state (source, last_cursor, last_sync_at, status, meta)
        VALUES ('garmin', %s, now(), %s, %s)
        ON CONFLICT (source) DO UPDATE SET
          last_cursor=EXCLUDED.last_cursor,
          last_sync_at=EXCLUDED.last_sync_at,
          status=EXCLUDED.status,
          meta=EXCLUDED.meta
        """,
        (
            today.isoformat(),
            "fail" if len(critical_missing_dates) == days else ("partial" if errors or critical_missing_dates else "ok"),
            Json({
                "days_attempted": days,
                "days_ok": ok,
                "critical_missing_days": len(critical_missing_dates),
                "critical_missing_dates": critical_missing_dates[:20],
                "errors": errors[:20],
            }),
        ),
    )

    result_status = "fail" if len(critical_missing_dates) == days else ("partial" if errors or critical_missing_dates else "ok")
    finish_backfill_job(
        cur,
        backfill_job_id,
        result_status,
        {
            "days_attempted": days,
            "days_ok": ok,
            "critical_missing_days": len(critical_missing_dates),
            "errors_count": len(errors),
        },
    )

    conn.commit()

    cur.execute("SAVEPOINT metrics_emit")
    try:
        run_id = os.getenv("INGEST_RUN_ID") or (str(backfill_job_id) if backfill_job_id else None)
        source_name = "garmin_daily_backfill" if args.mode == "backfill" else "garmin_daily"
        metric_tags = {"mode": args.mode}
        for name, value in [
            ("days_attempted", days),
            ("days_ok", ok),
            ("critical_missing_days", len(critical_missing_dates)),
            ("errors_count", len(errors)),
        ]:
            emit_metric(cur, name, source=source_name, metric_value=value, run_id=run_id, status=result_status, tags=metric_tags)
        if backfill_job_id:
            cur.execute(
                """
                SELECT dates_succeeded, dates_empty, dates_failed
                FROM health.backfill_jobs
                WHERE job_id=%s
                """,
                (backfill_job_id,),
            )
            row = cur.fetchone() or (0, 0, 0)
            for name, value in zip(["backfill_dates_succeeded", "backfill_dates_empty", "backfill_dates_failed"], row, strict=True):
                emit_metric(
                    cur,
                    name,
                    source=source_name,
                    metric_value=value,
                    run_id=run_id,
                    status=result_status,
                    tags={**metric_tags, "backfill_job_id": backfill_job_id},
                )
    except Exception as e:
        cur.execute("ROLLBACK TO SAVEPOINT metrics_emit")
        warn_metrics_failure("garmin_daily_sync", e)
    else:
        cur.execute("RELEASE SAVEPOINT metrics_emit")
    conn.commit()

    cur.close()
    conn.close()

    print(json.dumps({
        "ok": result_status == "ok",
        "status": result_status,
        "mode": args.mode,
        "backfill_job_id": backfill_job_id,
        "days_attempted": days,
        "days_ok": ok,
        "critical_missing_days": len(critical_missing_dates),
        "critical_missing_dates": critical_missing_dates,
        "errors": errors,
    }, indent=2))
    if result_status == "fail":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
