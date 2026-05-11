-- Core operational tables
CREATE TABLE IF NOT EXISTS health.sync_state (
  source TEXT PRIMARY KEY,
  last_cursor TEXT,
  last_sync_at TIMESTAMPTZ,
  status TEXT,
  meta JSONB,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS health.daily_metrics (
  id BIGSERIAL PRIMARY KEY,
  source TEXT NOT NULL,
  metric_date DATE NOT NULL,
  resting_hr INTEGER,
  hrv_ms DOUBLE PRECISION,
  stress_avg DOUBLE PRECISION,
  body_battery_avg DOUBLE PRECISION,
  steps INTEGER,
  calories_total DOUBLE PRECISION,
  sleep_seconds INTEGER,
  raw_json JSONB,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now(),
  UNIQUE(source, metric_date)
);

CREATE TABLE IF NOT EXISTS health.sleep_sessions (
  id BIGSERIAL PRIMARY KEY,
  source TEXT NOT NULL,
  external_sleep_id TEXT NOT NULL,
  sleep_start_utc TIMESTAMPTZ,
  sleep_end_utc TIMESTAMPTZ,
  duration_s INTEGER,
  deep_s INTEGER,
  light_s INTEGER,
  rem_s INTEGER,
  awake_s INTEGER,
  sleep_score DOUBLE PRECISION,
  raw_json JSONB,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now(),
  UNIQUE(source, external_sleep_id)
);

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
);

CREATE TABLE IF NOT EXISTS health.activities (
  id BIGSERIAL PRIMARY KEY,
  source TEXT NOT NULL,
  external_activity_id TEXT NOT NULL,
  activity_type TEXT,
  start_time_utc TIMESTAMPTZ NOT NULL,
  moving_time_s INTEGER,
  elapsed_time_s INTEGER,
  distance_m DOUBLE PRECISION,
  elevation_gain_m DOUBLE PRECISION,
  avg_hr INTEGER,
  max_hr INTEGER,
  calories DOUBLE PRECISION,
  raw_json JSONB,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now(),
  UNIQUE(source, external_activity_id)
);

-- Raw source tables
CREATE TABLE IF NOT EXISTS health.activities_strava_raw (
  id BIGSERIAL PRIMARY KEY,
  external_activity_id TEXT UNIQUE NOT NULL,
  start_time_utc TIMESTAMPTZ NOT NULL,
  activity_type TEXT,
  moving_time_s INTEGER,
  elapsed_time_s INTEGER,
  distance_m DOUBLE PRECISION,
  elevation_gain_m DOUBLE PRECISION,
  avg_hr INTEGER,
  max_hr INTEGER,
  calories DOUBLE PRECISION,
  raw_json JSONB,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS health.activities_garmin_raw (
  id BIGSERIAL PRIMARY KEY,
  external_activity_id TEXT UNIQUE NOT NULL,
  start_time_utc TIMESTAMPTZ NOT NULL,
  activity_type TEXT,
  moving_time_s INTEGER,
  elapsed_time_s INTEGER,
  distance_m DOUBLE PRECISION,
  elevation_gain_m DOUBLE PRECISION,
  avg_hr INTEGER,
  max_hr INTEGER,
  calories DOUBLE PRECISION,
  raw_json JSONB,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_strava_raw_start ON health.activities_strava_raw(start_time_utc DESC);
CREATE INDEX IF NOT EXISTS idx_garmin_raw_start ON health.activities_garmin_raw(start_time_utc DESC);

-- Match table between sources
CREATE TABLE IF NOT EXISTS health.activity_matches (
  id BIGSERIAL PRIMARY KEY,
  strava_external_activity_id TEXT NOT NULL REFERENCES health.activities_strava_raw(external_activity_id) ON DELETE CASCADE,
  garmin_external_activity_id TEXT NOT NULL REFERENCES health.activities_garmin_raw(external_activity_id) ON DELETE CASCADE,
  match_confidence DOUBLE PRECISION NOT NULL,
  match_method TEXT,
  created_at TIMESTAMPTZ DEFAULT now(),
  UNIQUE(strava_external_activity_id),
  UNIQUE(garmin_external_activity_id)
);

-- Unified analysis view
CREATE OR REPLACE VIEW health.activities_unified AS
WITH matched AS (
  SELECT
    s.external_activity_id AS strava_external_activity_id,
    g.external_activity_id AS garmin_external_activity_id,
    COALESCE(s.start_time_utc, g.start_time_utc) AS start_time_utc,
    COALESCE(s.activity_type, g.activity_type) AS activity_type,
    COALESCE(s.distance_m, g.distance_m) AS distance_m,
    COALESCE(s.moving_time_s, g.moving_time_s) AS moving_time_s,
    COALESCE(s.elapsed_time_s, g.elapsed_time_s) AS elapsed_time_s,
    COALESCE(s.elevation_gain_m, g.elevation_gain_m) AS elevation_gain_m,
    COALESCE(s.avg_hr, g.avg_hr) AS avg_hr,
    COALESCE(s.max_hr, g.max_hr) AS max_hr,
    COALESCE(s.calories, g.calories) AS calories,
    'matched'::text AS unified_source,
    m.match_confidence,
    s.raw_json AS strava_raw_json,
    g.raw_json AS garmin_raw_json
  FROM health.activity_matches m
  JOIN health.activities_strava_raw s ON s.external_activity_id = m.strava_external_activity_id
  JOIN health.activities_garmin_raw g ON g.external_activity_id = m.garmin_external_activity_id
),
strava_unmatched AS (
  SELECT
    s.external_activity_id AS strava_external_activity_id,
    NULL::text AS garmin_external_activity_id,
    s.start_time_utc,
    s.activity_type,
    s.distance_m,
    s.moving_time_s,
    s.elapsed_time_s,
    s.elevation_gain_m,
    s.avg_hr,
    s.max_hr,
    s.calories,
    'strava_only'::text AS unified_source,
    NULL::double precision AS match_confidence,
    s.raw_json AS strava_raw_json,
    NULL::jsonb AS garmin_raw_json
  FROM health.activities_strava_raw s
  LEFT JOIN health.activity_matches m ON m.strava_external_activity_id = s.external_activity_id
  WHERE m.strava_external_activity_id IS NULL
),
garmin_unmatched AS (
  SELECT
    NULL::text AS strava_external_activity_id,
    g.external_activity_id AS garmin_external_activity_id,
    g.start_time_utc,
    g.activity_type,
    g.distance_m,
    g.moving_time_s,
    g.elapsed_time_s,
    g.elevation_gain_m,
    g.avg_hr,
    g.max_hr,
    g.calories,
    'garmin_only'::text AS unified_source,
    NULL::double precision AS match_confidence,
    NULL::jsonb AS strava_raw_json,
    g.raw_json AS garmin_raw_json
  FROM health.activities_garmin_raw g
  LEFT JOIN health.activity_matches m ON m.garmin_external_activity_id = g.external_activity_id
  WHERE m.garmin_external_activity_id IS NULL
)
SELECT * FROM matched
UNION ALL SELECT * FROM strava_unmatched
UNION ALL SELECT * FROM garmin_unmatched;
