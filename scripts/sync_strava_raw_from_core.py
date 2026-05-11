#!/usr/bin/env python3
import os
from pathlib import Path

import psycopg2

WORKSPACE_DIR = Path(__file__).resolve().parents[1]
ENV_PATH = os.getenv("ENV_PATH", str(WORKSPACE_DIR / ".env"))

for line in Path(ENV_PATH).read_text().splitlines():
    if "=" in line and not line.strip().startswith("#"):
        k, v = line.split("=", 1)
        os.environ[k.strip()] = v.strip().strip('"').strip("'")

conn = psycopg2.connect(
    host=os.getenv("PGHOST", "127.0.0.1"),
    port=os.getenv("PGPORT", "5432"),
    dbname=os.getenv("PGDATABASE", "health_ops"),
    user=os.getenv("PGUSER", "lex"),
    password=os.getenv("PGPASSWORD") or os.getenv("POSTGRES_PASSWORD"),
)
cur = conn.cursor()
cur.execute('''
INSERT INTO health.activities_strava_raw (
  external_activity_id,start_time_utc,activity_type,moving_time_s,elapsed_time_s,distance_m,elevation_gain_m,avg_hr,max_hr,calories,raw_json,updated_at
)
SELECT external_activity_id,start_time_utc,activity_type,moving_time_s,elapsed_time_s,distance_m,elevation_gain_m,avg_hr,max_hr,calories,raw_json,now()
FROM health.activities WHERE source='strava'
ON CONFLICT (external_activity_id) DO UPDATE SET
  start_time_utc=EXCLUDED.start_time_utc,
  activity_type=EXCLUDED.activity_type,
  moving_time_s=EXCLUDED.moving_time_s,
  elapsed_time_s=EXCLUDED.elapsed_time_s,
  distance_m=EXCLUDED.distance_m,
  elevation_gain_m=EXCLUDED.elevation_gain_m,
  avg_hr=EXCLUDED.avg_hr,
  max_hr=EXCLUDED.max_hr,
  calories=EXCLUDED.calories,
  raw_json=EXCLUDED.raw_json,
  updated_at=now()
''')
conn.commit()
cur.execute("SELECT count(*) FROM health.activities_strava_raw")
print({"ok": True, "rows": cur.fetchone()[0]})
conn.close()
