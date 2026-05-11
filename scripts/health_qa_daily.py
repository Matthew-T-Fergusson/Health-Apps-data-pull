#!/usr/bin/env python3
"""
Decision log (why this script is designed this way)
- Decision: Convert multiple sync signals into a single status (ok/warn/fail).
  Why: Operators need fast decisioning, not raw timestamp spelunking.
- Decision: Keep warn/fail thresholds in env vars.
  Why: Tune sensitivity without code changes.
- Decision: Write QA output to both file artifact and sync_state row.
  Why: Supports cron notifications, dashboards, and historical audits.
- Decision: Exit non-zero only on fail.
  Why: Alerts should trigger on actionable breakage, not noisy warnings.
"""
import os
import json
from pathlib import Path

from common_env import load_env
from datetime import datetime, timezone, timedelta

import psycopg2
from psycopg2.extras import Json

from health_metrics import emit_metric, warn_metrics_failure

WORKSPACE_DIR = Path(__file__).resolve().parents[1]
ENV_PATH = os.getenv("ENV_PATH", str(WORKSPACE_DIR / ".env"))


def fetch_scalar(cur, sql, args=None):
    cur.execute(sql, args or ())
    r = cur.fetchone()
    return r[0] if r else None


def summarize_critical_completeness(row):
    (
        expected_days,
        steps_days,
        sleep_days,
        resting_hr_days,
        hrv_days,
        stress_days,
        body_battery_days,
        all_missing_days,
        all_missing_dates,
        source_empty_days,
    ) = row
    critical = {
        "lookback_completed_days": int(expected_days or 0),
        "steps_days": int(steps_days or 0),
        "sleep_days": int(sleep_days or 0),
        "resting_hr_days": int(resting_hr_days or 0),
        "hrv_days": int(hrv_days or 0),
        "stress_days": int(stress_days or 0),
        "body_battery_days": int(body_battery_days or 0),
        "all_critical_missing_days": int(all_missing_days or 0),
        "all_critical_missing_dates": [str(d) for d in (all_missing_dates or [])],
        "garmin_source_empty_days": int(source_empty_days or 0),
    }
    issues = []
    if critical["all_critical_missing_days"] > 0:
        issues.append({
            "severity": "fail",
            "type": "critical_metrics_missing",
            "metric": "daily_wellness_core",
            "days": critical["all_critical_missing_days"],
            "dates": critical["all_critical_missing_dates"],
            "note": "Sync freshness alone is insufficient: recent completed days have no steps/sleep/resting_hr/hrv/stress/body_battery values.",
        })
    return critical, issues


def main():
    load_env(ENV_PATH)

    warn_hours = int(os.getenv("HEALTH_QA_WARN_HOURS", "8"))
    fail_hours = int(os.getenv("HEALTH_QA_FAIL_HOURS", "24"))

    conn = psycopg2.connect(
        host=os.getenv("PGHOST", "127.0.0.1"),
        port=os.getenv("PGPORT", "5432"),
        dbname=os.getenv("PGDATABASE", "health_ops"),
        user=os.getenv("PGUSER", "lex"),
        password=os.getenv("PGPASSWORD") or os.getenv("POSTGRES_PASSWORD"),
    )
    conn.autocommit = False
    cur = conn.cursor()

    now = datetime.now(timezone.utc)
    warn_cut = now - timedelta(hours=warn_hours)
    fail_cut = now - timedelta(hours=fail_hours)

    sync_map = {
        "strava_daily": "strava",
        "garmin_daily": "garmin",
        "garmin_activities": "garmin_activities",
        "garmin_activity_details": "garmin_activity_details",
        "garmin_readiness": "garmin_readiness",
        "activity_routes": "activity_routes",
        "garmin_lifting": "garmin_lifting_sets",
    }

    freshness = {}
    issues = []

    for label, source in sync_map.items():
        cur.execute("select last_sync_at, status, meta from health.sync_state where source=%s", (source,))
        row = cur.fetchone()
        if not row:
            freshness[label] = {"state": "missing", "source": source}
            issues.append({"severity": "fail", "type": "missing_sync_state", "job": label})
            continue

        last_sync_at, status, meta = row
        state = "ok"
        sev = None
        if last_sync_at is None or last_sync_at < fail_cut:
            state = "stale_fail"
            sev = "fail"
        elif last_sync_at < warn_cut:
            state = "stale_warn"
            sev = "warn"

        if (status or "").lower() not in {"ok", "success"}:
            if state == "ok":
                state = "status_warn"
            sev = sev or "warn"

        freshness[label] = {
            "state": state,
            "source": source,
            "last_sync_at": last_sync_at.isoformat() if last_sync_at else None,
            "status": status,
            "meta": meta,
        }
        if sev:
            issues.append({"severity": sev, "type": "freshness", "job": label, "state": state})

    # Coverage checks (last 14 days)
    coverage = {}

    coverage["daily_metrics_days_14"] = fetch_scalar(
        cur,
        """
        select count(distinct metric_date)
        from health.daily_metrics
        where source='garmin' and metric_date >= current_date - interval '14 day'
        """,
    )
    if (coverage["daily_metrics_days_14"] or 0) < 10:
        issues.append({"severity": "warn", "type": "coverage", "metric": "daily_metrics_days_14", "value": coverage["daily_metrics_days_14"]})

    coverage["readiness_days_14"] = fetch_scalar(
        cur,
        """
        select count(distinct metric_date)
        from health.readiness_daily
        where source='garmin_custom' and metric_date >= current_date - interval '14 day'
        """,
    )
    if (coverage["readiness_days_14"] or 0) < 10:
        issues.append({"severity": "warn", "type": "coverage", "metric": "readiness_days_14", "value": coverage["readiness_days_14"]})

    # Null-rate checks (last 30 days)
    nulls = {}
    cur.execute(
        """
        select count(*) as n,
               sum((hrv_ms is null)::int),
               sum((stress_avg is null)::int),
               sum((body_battery_avg is null)::int),
               sum(((raw_json #>> '{_garmin_sources,stats_empty_wellness_payload}')::boolean is true)::int),
               sum(((raw_json #>> '{_garmin_sources,reload_requested}')::boolean is true)::int)
        from health.daily_metrics
        where source='garmin' and metric_date >= current_date - interval '30 day'
        """
    )
    n, n_hrv, n_stress, n_bb, n_source_empty, n_reload_requested = cur.fetchone()
    n = n or 1
    nulls["hrv_null_rate_30d"] = round((n_hrv or 0) / n, 3)
    nulls["stress_null_rate_30d"] = round((n_stress or 0) / n, 3)
    nulls["body_battery_null_rate_30d"] = round((n_bb or 0) / n, 3)
    nulls["garmin_source_empty_days_30d"] = int(n_source_empty or 0)
    nulls["garmin_reload_requested_days_30d"] = int(n_reload_requested or 0)

    if nulls["garmin_source_empty_days_30d"]:
        issues.append({
            "severity": "warn",
            "type": "garmin_source_empty",
            "metric": "wellness_payload",
            "days_30d": nulls["garmin_source_empty_days_30d"],
            "note": "Garmin returned placeholder/empty wellness payloads after reload attempts; this is source availability, not a parser crash.",
        })

    if nulls["hrv_null_rate_30d"] > 0.2:
        issues.append({"severity": "warn", "type": "null_rate", "metric": "hrv", "value": nulls["hrv_null_rate_30d"]})
    if nulls["stress_null_rate_30d"] > 0.1:
        issues.append({"severity": "warn", "type": "null_rate", "metric": "stress", "value": nulls["stress_null_rate_30d"]})
    if nulls["body_battery_null_rate_30d"] > 0.1:
        issues.append({"severity": "warn", "type": "null_rate", "metric": "body_battery", "value": nulls["body_battery_null_rate_30d"]})

    # Critical recent completeness checks (last completed days)
    critical = {}
    critical_lookback_days = int(os.getenv("HEALTH_QA_CRITICAL_LOOKBACK_DAYS", "7"))
    critical_start_expr = f"{critical_lookback_days} day"
    cur.execute(
        """
        with days as (
          select generate_series(
            current_date - (%s::text)::interval,
            current_date - interval '1 day',
            interval '1 day'
          )::date as metric_date
        ), rows as (
          select d.metric_date,
                 g.resting_hr, g.hrv_ms, g.stress_avg, g.body_battery_avg,
                 g.steps, g.sleep_seconds,
                 (g.raw_json #>> '{_garmin_sources,stats_empty_wellness_payload}')::boolean as source_empty
          from days d
          left join health.daily_metrics g
            on g.source='garmin' and g.metric_date=d.metric_date
        )
        select count(*) as expected_days,
               count(*) filter (where steps is not null) as steps_days,
               count(*) filter (where sleep_seconds is not null) as sleep_days,
               count(*) filter (where resting_hr is not null) as resting_hr_days,
               count(*) filter (where hrv_ms is not null) as hrv_days,
               count(*) filter (where stress_avg is not null) as stress_days,
               count(*) filter (where body_battery_avg is not null) as body_battery_days,
               count(*) filter (
                 where resting_hr is null and hrv_ms is null and stress_avg is null
                   and body_battery_avg is null and steps is null and sleep_seconds is null
               ) as all_critical_missing_days,
               coalesce(jsonb_agg(metric_date order by metric_date) filter (
                 where resting_hr is null and hrv_ms is null and stress_avg is null
                   and body_battery_avg is null and steps is null and sleep_seconds is null
               ), '[]'::jsonb) as all_critical_missing_dates,
               count(*) filter (where source_empty is true) as source_empty_days
        from rows
        """,
        (critical_start_expr,),
    )
    critical, critical_issues = summarize_critical_completeness(cur.fetchone())
    issues.extend(critical_issues)

    # Match integrity
    match_stats = {}
    match_stats["matches_30d"] = fetch_scalar(
        cur,
        """
        select count(*)
        from health.activity_matches
        where created_at >= now() - interval '30 day'
        """,
    )
    match_stats["routes_raw"] = fetch_scalar(cur, "select count(*) from health.activity_routes")
    match_stats["routes_deduped"] = fetch_scalar(cur, "select count(*) from health.activity_routes_deduped")

    # Severity
    has_fail = any(i["severity"] == "fail" for i in issues)
    has_warn = any(i["severity"] == "warn" for i in issues)
    qa_status = "fail" if has_fail else ("warn" if has_warn else "ok")

    payload = {
        "generated_at": now.isoformat(),
        "status": qa_status,
        "freshness": freshness,
        "coverage": coverage,
        "null_rates": nulls,
        "critical_completeness": critical,
        "match_stats": match_stats,
        "issues": issues,
    }

    out_path = Path(os.getenv("HEALTH_QA_OUTPUT_PATH", str(WORKSPACE_DIR / "output" / "health_qa_daily_latest.json")))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2))

    # persist in sync_state for monitoring
    cur.execute(
        """
        INSERT INTO health.sync_state (source, last_cursor, last_sync_at, status, meta)
        VALUES ('health_qa_daily', %s, now(), %s, %s)
        ON CONFLICT (source) DO UPDATE SET
          last_cursor=EXCLUDED.last_cursor,
          last_sync_at=EXCLUDED.last_sync_at,
          status=EXCLUDED.status,
          meta=EXCLUDED.meta
        """,
        (now.isoformat(), qa_status, Json(payload)),
    )

    cur.execute("SAVEPOINT metrics_emit")
    try:
        run_id = os.getenv("INGEST_RUN_ID")
        emit_metric(cur, "qa_status", source="health_qa_daily", metric_text=qa_status, run_id=run_id, status=qa_status)
        emit_metric(cur, "qa_issue_count", source="health_qa_daily", metric_value=len(issues), run_id=run_id, status=qa_status)
        emit_metric(
            cur,
            "critical_missing_days",
            source="health_qa_daily",
            metric_value=critical.get("all_critical_missing_days", 0),
            run_id=run_id,
            status=qa_status,
            meta={"critical_completeness": critical},
        )
        emit_metric(
            cur,
            "garmin_source_empty_days_30d",
            source="health_qa_daily",
            metric_value=nulls.get("garmin_source_empty_days_30d", 0),
            run_id=run_id,
            status=qa_status,
        )
    except Exception as e:
        cur.execute("ROLLBACK TO SAVEPOINT metrics_emit")
        warn_metrics_failure("health_qa_daily", e)
    else:
        cur.execute("RELEASE SAVEPOINT metrics_emit")

    conn.commit()
    cur.close()
    conn.close()

    print(json.dumps(payload, indent=2))

    # non-zero exit only on hard fail (good for cron alerting)
    if qa_status == "fail":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
