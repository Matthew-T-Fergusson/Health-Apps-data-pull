-- Manual activity capture tables + unified view extension

CREATE TABLE IF NOT EXISTS health.activities_manual_raw (
  id BIGSERIAL PRIMARY KEY,
  external_activity_id TEXT UNIQUE NOT NULL,
  start_time_utc TIMESTAMPTZ NOT NULL,
  activity_type TEXT NOT NULL,
  moving_time_s INTEGER,
  elapsed_time_s INTEGER,
  distance_m DOUBLE PRECISION,
  elevation_gain_m DOUBLE PRECISION,
  avg_hr INTEGER,
  max_hr INTEGER,
  calories DOUBLE PRECISION,
  notes TEXT,
  capture_source TEXT DEFAULT 'chat',
  evidence_json JSONB,
  raw_json JSONB,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_manual_raw_start ON health.activities_manual_raw(start_time_utc DESC);

CREATE TABLE IF NOT EXISTS health.activity_manual_links (
  id BIGSERIAL PRIMARY KEY,
  manual_external_activity_id TEXT NOT NULL REFERENCES health.activities_manual_raw(external_activity_id) ON DELETE CASCADE,
  linked_source TEXT NOT NULL, -- garmin|strava
  linked_external_activity_id TEXT NOT NULL,
  match_confidence DOUBLE PRECISION,
  match_method TEXT,
  status TEXT DEFAULT 'active', -- active|ignored
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now(),
  UNIQUE(manual_external_activity_id, linked_source, linked_external_activity_id)
);

CREATE INDEX IF NOT EXISTS idx_manual_links_manual ON health.activity_manual_links(manual_external_activity_id);

-- Optional extended view including manual entries that are not linked to Garmin/Strava.
CREATE OR REPLACE VIEW health.activities_unified_with_manual AS
WITH base AS (
  SELECT
    strava_external_activity_id,
    garmin_external_activity_id,
    start_time_utc,
    activity_type,
    distance_m,
    moving_time_s,
    elapsed_time_s,
    elevation_gain_m,
    avg_hr,
    max_hr,
    calories,
    unified_source,
    match_confidence,
    strava_raw_json,
    garmin_raw_json,
    NULL::text AS manual_external_activity_id,
    NULL::jsonb AS manual_raw_json,
    NULL::text AS manual_notes
  FROM health.activities_unified
),
manual_unlinked AS (
  SELECT
    NULL::text AS strava_external_activity_id,
    NULL::text AS garmin_external_activity_id,
    m.start_time_utc,
    m.activity_type,
    m.distance_m,
    m.moving_time_s,
    m.elapsed_time_s,
    m.elevation_gain_m,
    m.avg_hr,
    m.max_hr,
    m.calories,
    'manual_only'::text AS unified_source,
    NULL::double precision AS match_confidence,
    NULL::jsonb AS strava_raw_json,
    NULL::jsonb AS garmin_raw_json,
    m.external_activity_id AS manual_external_activity_id,
    m.raw_json AS manual_raw_json,
    m.notes AS manual_notes
  FROM health.activities_manual_raw m
  LEFT JOIN health.activity_manual_links l
    ON l.manual_external_activity_id = m.external_activity_id
   AND l.status = 'active'
  WHERE l.id IS NULL
)
SELECT * FROM base
UNION ALL
SELECT * FROM manual_unlinked;
