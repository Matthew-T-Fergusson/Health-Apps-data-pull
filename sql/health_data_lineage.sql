-- Data lineage + consent metadata for responsible AI / auditability.
-- Keep this layer mostly additive: existing data remains valid, and source-specific
-- purge implementation is documented separately before destructive behavior exists.

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
  updated_at TIMESTAMPTZ DEFAULT now(),
  pulled_at TIMESTAMPTZ,
  consent_version TEXT DEFAULT 'health-consent-2026-05-11'
);

ALTER TABLE health.daily_metrics ADD COLUMN IF NOT EXISTS pulled_at TIMESTAMPTZ;
ALTER TABLE health.daily_metrics ADD COLUMN IF NOT EXISTS consent_version TEXT DEFAULT 'health-consent-2026-05-11';
ALTER TABLE health.sleep_sessions ADD COLUMN IF NOT EXISTS pulled_at TIMESTAMPTZ;
ALTER TABLE health.sleep_sessions ADD COLUMN IF NOT EXISTS consent_version TEXT DEFAULT 'health-consent-2026-05-11';
ALTER TABLE health.body_composition_daily ADD COLUMN IF NOT EXISTS pulled_at TIMESTAMPTZ;
ALTER TABLE health.body_composition_daily ADD COLUMN IF NOT EXISTS consent_version TEXT DEFAULT 'health-consent-2026-05-11';
ALTER TABLE health.activities ADD COLUMN IF NOT EXISTS pulled_at TIMESTAMPTZ;
ALTER TABLE health.activities ADD COLUMN IF NOT EXISTS consent_version TEXT DEFAULT 'health-consent-2026-05-11';
ALTER TABLE health.activities_strava_raw ADD COLUMN IF NOT EXISTS pulled_at TIMESTAMPTZ;
ALTER TABLE health.activities_strava_raw ADD COLUMN IF NOT EXISTS consent_version TEXT DEFAULT 'health-consent-2026-05-11';
ALTER TABLE health.activities_garmin_raw ADD COLUMN IF NOT EXISTS pulled_at TIMESTAMPTZ;
ALTER TABLE health.activities_garmin_raw ADD COLUMN IF NOT EXISTS consent_version TEXT DEFAULT 'health-consent-2026-05-11';
ALTER TABLE health.readiness_daily ADD COLUMN IF NOT EXISTS pulled_at TIMESTAMPTZ;
ALTER TABLE health.readiness_daily ADD COLUMN IF NOT EXISTS consent_version TEXT DEFAULT 'health-consent-2026-05-11';
ALTER TABLE health.activities_manual_raw ADD COLUMN IF NOT EXISTS pulled_at TIMESTAMPTZ;
ALTER TABLE health.activities_manual_raw ADD COLUMN IF NOT EXISTS consent_version TEXT DEFAULT 'health-consent-2026-05-11';
ALTER TABLE health.nutrition_manual_raw ADD COLUMN IF NOT EXISTS pulled_at TIMESTAMPTZ;
ALTER TABLE health.nutrition_manual_raw ADD COLUMN IF NOT EXISTS consent_version TEXT DEFAULT 'health-consent-2026-05-11';

CREATE OR REPLACE VIEW health.data_lineage AS
SELECT
  'daily_metric'::text AS entity_type,
  source AS source_system,
  metric_date,
  metric_date::text AS entity_id,
  'steps'::text AS metric_name,
  steps::text AS metric_value,
  COALESCE(pulled_at, updated_at, created_at) AS pulled_at,
  COALESCE(consent_version, 'health-consent-2026-05-11') AS consent_version,
  'health.daily_metrics'::text AS storage_table,
  jsonb_build_object('raw_json_present', raw_json IS NOT NULL) AS meta
FROM health.daily_metrics
WHERE steps IS NOT NULL
UNION ALL
SELECT 'daily_metric', source, metric_date, metric_date::text, 'sleep_seconds', sleep_seconds::text,
       COALESCE(pulled_at, updated_at, created_at), COALESCE(consent_version, 'health-consent-2026-05-11'),
       'health.daily_metrics', jsonb_build_object('raw_json_present', raw_json IS NOT NULL)
FROM health.daily_metrics WHERE sleep_seconds IS NOT NULL
UNION ALL
SELECT 'daily_metric', source, metric_date, metric_date::text, 'hrv_ms', hrv_ms::text,
       COALESCE(pulled_at, updated_at, created_at), COALESCE(consent_version, 'health-consent-2026-05-11'),
       'health.daily_metrics', jsonb_build_object('raw_json_present', raw_json IS NOT NULL)
FROM health.daily_metrics WHERE hrv_ms IS NOT NULL
UNION ALL
SELECT 'daily_metric', source, metric_date, metric_date::text, 'resting_hr', resting_hr::text,
       COALESCE(pulled_at, updated_at, created_at), COALESCE(consent_version, 'health-consent-2026-05-11'),
       'health.daily_metrics', jsonb_build_object('raw_json_present', raw_json IS NOT NULL)
FROM health.daily_metrics WHERE resting_hr IS NOT NULL
UNION ALL
SELECT 'daily_metric', source, metric_date, metric_date::text, 'stress_avg', stress_avg::text,
       COALESCE(pulled_at, updated_at, created_at), COALESCE(consent_version, 'health-consent-2026-05-11'),
       'health.daily_metrics', jsonb_build_object('raw_json_present', raw_json IS NOT NULL)
FROM health.daily_metrics WHERE stress_avg IS NOT NULL
UNION ALL
SELECT 'daily_metric', source, metric_date, metric_date::text, 'body_battery_avg', body_battery_avg::text,
       COALESCE(pulled_at, updated_at, created_at), COALESCE(consent_version, 'health-consent-2026-05-11'),
       'health.daily_metrics', jsonb_build_object('raw_json_present', raw_json IS NOT NULL)
FROM health.daily_metrics WHERE body_battery_avg IS NOT NULL
UNION ALL
SELECT 'body_composition', source, metric_date, metric_date::text, 'weight_kg', weight_kg::text,
       COALESCE(pulled_at, updated_at, created_at), COALESCE(consent_version, 'health-consent-2026-05-11'),
       'health.body_composition_daily', jsonb_build_object('raw_json_present', raw_json IS NOT NULL)
FROM health.body_composition_daily WHERE weight_kg IS NOT NULL
UNION ALL
SELECT 'apple_health_daily', 'apple_health', metric_date, metric_date::text, 'apple_steps', steps::text,
       COALESCE(pulled_at, updated_at, created_at), COALESCE(consent_version, 'health-consent-2026-05-11'),
       'health.apple_health_daily', jsonb_build_object('records_count', records_count)
FROM health.apple_health_daily WHERE steps IS NOT NULL
UNION ALL
SELECT 'activity', source, start_time_utc::date, external_activity_id, 'activity', activity_type,
       COALESCE(pulled_at, updated_at, created_at), COALESCE(consent_version, 'health-consent-2026-05-11'),
       'health.activities', jsonb_build_object('distance_m', distance_m, 'duration_s', moving_time_s)
FROM health.activities
UNION ALL
SELECT 'activity_raw', 'strava', start_time_utc::date, external_activity_id, 'activity', activity_type,
       COALESCE(pulled_at, updated_at, created_at), COALESCE(consent_version, 'health-consent-2026-05-11'),
       'health.activities_strava_raw', jsonb_build_object('distance_m', distance_m, 'duration_s', moving_time_s)
FROM health.activities_strava_raw
UNION ALL
SELECT 'activity_raw', 'garmin', start_time_utc::date, external_activity_id, 'activity', activity_type,
       COALESCE(pulled_at, updated_at, created_at), COALESCE(consent_version, 'health-consent-2026-05-11'),
       'health.activities_garmin_raw', jsonb_build_object('distance_m', distance_m, 'duration_s', moving_time_s)
FROM health.activities_garmin_raw
UNION ALL
SELECT 'manual_activity', 'manual_activity', start_time_utc::date, external_activity_id, 'activity', activity_type,
       COALESCE(pulled_at, updated_at, created_at), COALESCE(consent_version, 'health-consent-2026-05-11'),
       'health.activities_manual_raw', jsonb_build_object('capture_source', capture_source, 'confidence', 'manual')
FROM health.activities_manual_raw
UNION ALL
SELECT 'manual_nutrition', 'manual_nutrition', meal_time_utc::date, external_meal_id, 'meal', meal_name,
       COALESCE(pulled_at, updated_at, created_at), COALESCE(consent_version, 'health-consent-2026-05-11'),
       'health.nutrition_manual_raw', jsonb_build_object('capture_source', capture_source, 'confidence_level', confidence_level)
FROM health.nutrition_manual_raw;
