#!/usr/bin/env python3
import argparse
import json
import os
import subprocess
import tempfile
import xml.etree.ElementTree as ET
import zipfile
from collections import defaultdict
from datetime import datetime
from pathlib import Path

WORKSPACE_DIR = Path(os.getenv("WORKSPACE_DIR", Path(__file__).resolve().parents[1]))
DEFAULT_ZIP_PATH = str(WORKSPACE_DIR / "data" / "apple_health" / "export_iphone_healthdata.zip")

TYPE_STEPS = "HKQuantityTypeIdentifierStepCount"
TYPE_DISTANCE = "HKQuantityTypeIdentifierDistanceWalkingRunning"
TYPE_ACTIVE_ENERGY = "HKQuantityTypeIdentifierActiveEnergyBurned"
TYPE_BASAL_ENERGY = "HKQuantityTypeIdentifierBasalEnergyBurned"
TYPE_FLIGHTS = "HKQuantityTypeIdentifierFlightsClimbed"
TYPE_WEIGHT = "HKQuantityTypeIdentifierBodyMass"
TYPE_SLEEP = "HKCategoryTypeIdentifierSleepAnalysis"

SLEEP_ASLEEP_VALUES = {
    "HKCategoryValueSleepAnalysisAsleep",
    "HKCategoryValueSleepAnalysisAsleepCore",
    "HKCategoryValueSleepAnalysisAsleepDeep",
    "HKCategoryValueSleepAnalysisAsleepREM",
    "HKCategoryValueSleepAnalysisAsleepUnspecified",
}


def parse_dt(s: str):
    return datetime.strptime(s, "%Y-%m-%d %H:%M:%S %z")


def to_float(v):
    try:
        return float(v)
    except Exception:
        return None


def weight_to_kg(value, unit):
    v = to_float(value)
    if v is None:
        return None
    u = (unit or "").lower()
    if u == "kg":
        return v
    if u in ("lb", "lbs", "pound", "pounds"):
        return v * 0.45359237
    if u == "g":
        return v / 1000.0
    return v


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--zip", dest="zip_path", default=DEFAULT_ZIP_PATH)
    args = parser.parse_args()
    zip_path = args.zip_path

    daily = defaultdict(lambda: {
        "steps": 0,
        "distance_walking_running_m": 0.0,
        "active_energy_kcal": 0.0,
        "basal_energy_kcal": 0.0,
        "flights_climbed": 0,
        "sleep_seconds": 0,
        "records_count": 0,
    })
    weight_by_day = {}

    with zipfile.ZipFile(zip_path) as z:
        with z.open("apple_health_export/export.xml") as f:
            for _ev, el in ET.iterparse(f, events=("end",)):
                if el.tag != "Record":
                    el.clear()
                    continue

                rtype = el.attrib.get("type")
                start = el.attrib.get("startDate")
                end = el.attrib.get("endDate")
                value = el.attrib.get("value")
                unit = el.attrib.get("unit")
                if not start:
                    el.clear()
                    continue

                start_dt = parse_dt(start)
                day = start_dt.date().isoformat()
                d = daily[day]
                d["records_count"] += 1

                if rtype == TYPE_STEPS:
                    v = to_float(value)
                    if v is not None:
                        d["steps"] += int(round(v))
                elif rtype == TYPE_DISTANCE:
                    v = to_float(value)
                    if v is not None:
                        d["distance_walking_running_m"] += v
                elif rtype == TYPE_ACTIVE_ENERGY:
                    v = to_float(value)
                    if v is not None:
                        d["active_energy_kcal"] += v
                elif rtype == TYPE_BASAL_ENERGY:
                    v = to_float(value)
                    if v is not None:
                        d["basal_energy_kcal"] += v
                elif rtype == TYPE_FLIGHTS:
                    v = to_float(value)
                    if v is not None:
                        d["flights_climbed"] += int(round(v))
                elif rtype == TYPE_SLEEP:
                    # Only count asleep categories, not in-bed/awake artifacts
                    cat = value
                    if cat in SLEEP_ASLEEP_VALUES and end:
                        end_dt = parse_dt(end)
                        secs = max(0, int((end_dt - start_dt).total_seconds()))
                        d["sleep_seconds"] += secs
                elif rtype == TYPE_WEIGHT:
                    kg = weight_to_kg(value, unit)
                    if kg is not None:
                        # keep latest sample of the day by timestamp
                        prev = weight_by_day.get(day)
                        ts = start_dt.timestamp()
                        if (prev is None) or (ts > prev[0]):
                            weight_by_day[day] = (ts, kg)

                el.clear()

    # Build SQL script
    sql_lines = []
    sql_lines.append("BEGIN;")
    sql_lines.append(
        """
CREATE TABLE IF NOT EXISTS health.apple_health_daily (
  metric_date DATE PRIMARY KEY,
  steps INTEGER,
  distance_walking_running_m DOUBLE PRECISION,
  active_energy_kcal DOUBLE PRECISION,
  basal_energy_kcal DOUBLE PRECISION,
  flights_climbed INTEGER,
  sleep_seconds INTEGER,
  records_count INTEGER,
  raw_json JSONB,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);
""".strip()
    )

    for day in sorted(daily.keys()):
        d = daily[day]
        raw = json.dumps({"source": "apple_export", "records_count": d["records_count"]})
        sql_lines.append(
            """
INSERT INTO health.apple_health_daily (
  metric_date, steps, distance_walking_running_m, active_energy_kcal,
  basal_energy_kcal, flights_climbed, sleep_seconds, records_count, raw_json, updated_at
)
VALUES (
  DATE '{day}', {steps}, {dist}, {active}, {basal}, {flights}, {sleep}, {rc}, '{raw}'::jsonb, now()
)
ON CONFLICT (metric_date) DO UPDATE SET
  steps=EXCLUDED.steps,
  distance_walking_running_m=EXCLUDED.distance_walking_running_m,
  active_energy_kcal=EXCLUDED.active_energy_kcal,
  basal_energy_kcal=EXCLUDED.basal_energy_kcal,
  flights_climbed=EXCLUDED.flights_climbed,
  sleep_seconds=EXCLUDED.sleep_seconds,
  records_count=EXCLUDED.records_count,
  raw_json=EXCLUDED.raw_json,
  updated_at=now();
""".format(
                day=day,
                steps=int(d["steps"]),
                dist=("NULL" if d["distance_walking_running_m"] == 0 else d["distance_walking_running_m"]),
                active=("NULL" if d["active_energy_kcal"] == 0 else d["active_energy_kcal"]),
                basal=("NULL" if d["basal_energy_kcal"] == 0 else d["basal_energy_kcal"]),
                flights=("NULL" if d["flights_climbed"] == 0 else int(d["flights_climbed"])),
                sleep=("NULL" if d["sleep_seconds"] == 0 else int(d["sleep_seconds"])),
                rc=int(d["records_count"]),
                raw=raw.replace("'", "''"),
            ).strip()
        )

    for day in sorted(weight_by_day.keys()):
        kg = weight_by_day[day][1]
        sql_lines.append(
            f"""
INSERT INTO health.body_composition_daily (source, metric_date, weight_kg, raw_json, updated_at)
VALUES ('apple_health', DATE '{day}', {kg}, '{{"source":"apple_export"}}'::jsonb, now())
ON CONFLICT (source, metric_date) DO UPDATE SET
  weight_kg=EXCLUDED.weight_kg,
  raw_json=EXCLUDED.raw_json,
  updated_at=now();
""".strip()
        )

    sql_lines.append(
        """
CREATE OR REPLACE VIEW health.daily_metrics_synthesized AS
WITH dates AS (
  SELECT metric_date FROM health.daily_metrics
  UNION
  SELECT metric_date FROM health.apple_health_daily
  UNION
  SELECT metric_date FROM health.body_composition_daily
),
garmin_weight AS (
  SELECT metric_date, weight_kg FROM health.body_composition_daily WHERE source='garmin'
),
apple_weight AS (
  SELECT metric_date, weight_kg FROM health.body_composition_daily WHERE source='apple_health'
)
SELECT
  d.metric_date,
  COALESCE(g.steps, a.steps) AS steps,
  CASE WHEN g.steps IS NOT NULL THEN 'garmin' WHEN a.steps IS NOT NULL THEN 'apple_health' END AS steps_source,
  COALESCE(gw.weight_kg, aw.weight_kg) AS weight_kg,
  CASE WHEN gw.weight_kg IS NOT NULL THEN 'garmin' WHEN aw.weight_kg IS NOT NULL THEN 'apple_health' END AS weight_source,
  COALESCE(g.sleep_seconds, a.sleep_seconds) AS sleep_seconds,
  CASE WHEN g.sleep_seconds IS NOT NULL THEN 'garmin' WHEN a.sleep_seconds IS NOT NULL THEN 'apple_health' END AS sleep_source,
  COALESCE(g.calories_total, a.active_energy_kcal) AS active_energy_kcal,
  CASE WHEN g.calories_total IS NOT NULL THEN 'garmin' WHEN a.active_energy_kcal IS NOT NULL THEN 'apple_health' END AS active_energy_source,
  a.basal_energy_kcal,
  a.distance_walking_running_m,
  a.flights_climbed,
  g.resting_hr,
  g.hrv_ms,
  g.body_battery_avg,
  g.stress_avg
FROM dates d
LEFT JOIN health.daily_metrics g ON g.metric_date=d.metric_date AND g.source='garmin'
LEFT JOIN health.apple_health_daily a ON a.metric_date=d.metric_date
LEFT JOIN garmin_weight gw ON gw.metric_date=d.metric_date
LEFT JOIN apple_weight aw ON aw.metric_date=d.metric_date;
""".strip()
    )
    sql_lines.append("COMMIT;")

    with tempfile.NamedTemporaryFile("w", delete=False, suffix=".sql") as tf:
        tf.write("\n\n".join(sql_lines))
        sql_path = tf.name

    postgres_container = os.getenv("POSTGRES_CONTAINER", "lex-postgres")
    subprocess.check_call([
        "docker", "cp", sql_path, f"{postgres_container}:/tmp/apple_phase1_import.sql"
    ])
    subprocess.check_call([
        "docker", "exec", postgres_container,
        "psql", "-U", os.getenv("PGUSER", "lex"),
        "-d", os.getenv("PGDATABASE", "health_ops"),
        "-f", "/tmp/apple_phase1_import.sql"
    ])

    print(f"Source zip: {zip_path}")
    print(f"Imported days: {len(daily)}")
    print(f"Imported weight days: {len(weight_by_day)}")


if __name__ == "__main__":
    main()
