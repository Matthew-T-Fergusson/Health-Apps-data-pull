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
from datetime import datetime, timezone, timedelta

import psycopg2
from psycopg2.extras import Json

WORKSPACE_DIR = Path(__file__).resolve().parents[1]
ENV_PATH = os.getenv("ENV_PATH", str(WORKSPACE_DIR / ".env"))


def load_env(path):
    p = Path(path)
    if not p.exists():
        return
    for line in p.read_text().splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def q1(cur, sql, args=None):
    cur.execute(sql, args or ())
    r = cur.fetchone()
    return r[0] if r else None


def main():
    load_env(ENV_PATH)

    warn_hours = int(os.getenv("HEALTH_QA_WARN_HOURS", "8"))
    fail_hours = int(os.getenv("HEALTH_QA_FAIL_HOURS", "24"))

    conn = psycopg2.connect(
        host=os.getenv("PGHOST", "127.0.0.1"),
        port=os.getenv("PGPORT", "5432"),
        dbname=os.getenv("PGDATABASE", "health_ops"),
        user=os.getenv("PGUSER", "lex"),
        password=os.getenv("PGPASSWORD", "lexpass_change_me"),
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

    coverage["daily_metrics_days_14"] = q1(
        cur,
        """
        select count(distinct metric_date)
        from health.daily_metrics
        where source='garmin' and metric_date >= current_date - interval '14 day'
        """,
    )
    if (coverage["daily_metrics_days_14"] or 0) < 10:
        issues.append({"severity": "warn", "type": "coverage", "metric": "daily_metrics_days_14", "value": coverage["daily_metrics_days_14"]})

    coverage["readiness_days_14"] = q1(
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
               sum((body_battery_avg is null)::int)
        from health.daily_metrics
        where source='garmin' and metric_date >= current_date - interval '30 day'
        """
    )
    n, n_hrv, n_stress, n_bb = cur.fetchone()
    n = n or 1
    nulls["hrv_null_rate_30d"] = round((n_hrv or 0) / n, 3)
    nulls["stress_null_rate_30d"] = round((n_stress or 0) / n, 3)
    nulls["body_battery_null_rate_30d"] = round((n_bb or 0) / n, 3)

    if nulls["hrv_null_rate_30d"] > 0.2:
        issues.append({"severity": "warn", "type": "null_rate", "metric": "hrv", "value": nulls["hrv_null_rate_30d"]})
    if nulls["stress_null_rate_30d"] > 0.1:
        issues.append({"severity": "warn", "type": "null_rate", "metric": "stress", "value": nulls["stress_null_rate_30d"]})
    if nulls["body_battery_null_rate_30d"] > 0.1:
        issues.append({"severity": "warn", "type": "null_rate", "metric": "body_battery", "value": nulls["body_battery_null_rate_30d"]})

    # Match integrity
    match_stats = {}
    match_stats["matches_30d"] = q1(
        cur,
        """
        select count(*)
        from health.activity_matches
        where created_at >= now() - interval '30 day'
        """,
    )
    match_stats["routes_raw"] = q1(cur, "select count(*) from health.activity_routes")
    match_stats["routes_deduped"] = q1(cur, "select count(*) from health.activity_routes_deduped")

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

    conn.commit()
    cur.close()
    conn.close()

    print(json.dumps(payload, indent=2))

    # non-zero exit only on hard fail (good for cron alerting)
    if qa_status == "fail":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
