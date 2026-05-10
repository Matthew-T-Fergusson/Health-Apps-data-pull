CREATE TABLE IF NOT EXISTS health.daily_vitals_garmin (
  id BIGSERIAL PRIMARY KEY,
  metric_date DATE UNIQUE NOT NULL,
  avg_spo2 DOUBLE PRECISION,
  min_spo2 DOUBLE PRECISION,
  avg_respiration DOUBLE PRECISION,
  min_respiration DOUBLE PRECISION,
  max_respiration DOUBLE PRECISION,
  resting_respiration DOUBLE PRECISION,
  floors_ascended INTEGER,
  floors_descended INTEGER,
  active_seconds INTEGER,
  highly_active_seconds INTEGER,
  moderate_intensity_minutes INTEGER,
  vigorous_intensity_minutes INTEGER,
  raw_json JSONB,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS health.body_battery_daily_garmin (
  id BIGSERIAL PRIMARY KEY,
  metric_date DATE UNIQUE NOT NULL,
  charged_value DOUBLE PRECISION,
  drained_value DOUBLE PRECISION,
  highest_value DOUBLE PRECISION,
  lowest_value DOUBLE PRECISION,
  most_recent_value DOUBLE PRECISION,
  at_wake_value DOUBLE PRECISION,
  during_sleep_value DOUBLE PRECISION,
  start_utc TIMESTAMPTZ,
  end_utc TIMESTAMPTZ,
  raw_json JSONB,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS health.body_battery_events_garmin (
  id BIGSERIAL PRIMARY KEY,
  event_pk TEXT UNIQUE,
  metric_date DATE,
  event_type TEXT,
  event_start_utc TIMESTAMPTZ,
  duration_ms BIGINT,
  body_battery_impact DOUBLE PRECISION,
  feedback_type TEXT,
  short_feedback TEXT,
  activity_id BIGINT,
  activity_type TEXT,
  activity_name TEXT,
  raw_json JSONB,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_body_battery_events_start
  ON health.body_battery_events_garmin(event_start_utc DESC);

CREATE TABLE IF NOT EXISTS health.activity_weather_garmin (
  id BIGSERIAL PRIMARY KEY,
  garmin_activity_id BIGINT UNIQUE NOT NULL,
  issue_utc TIMESTAMPTZ,
  temp_c DOUBLE PRECISION,
  apparent_temp_c DOUBLE PRECISION,
  dew_point_c DOUBLE PRECISION,
  humidity_pct DOUBLE PRECISION,
  wind_direction_deg DOUBLE PRECISION,
  wind_compass TEXT,
  wind_speed_kph DOUBLE PRECISION,
  wind_gust_kph DOUBLE PRECISION,
  latitude DOUBLE PRECISION,
  longitude DOUBLE PRECISION,
  weather_type TEXT,
  raw_json JSONB,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS health.activity_typed_splits_garmin (
  id BIGSERIAL PRIMARY KEY,
  garmin_activity_id BIGINT NOT NULL,
  split_index INTEGER NOT NULL,
  split_type TEXT,
  start_utc TIMESTAMPTZ,
  end_utc TIMESTAMPTZ,
  duration_s DOUBLE PRECISION,
  moving_duration_s DOUBLE PRECISION,
  elapsed_duration_s DOUBLE PRECISION,
  distance_m DOUBLE PRECISION,
  avg_speed_mps DOUBLE PRECISION,
  avg_hr INTEGER,
  max_hr INTEGER,
  total_exercise_reps INTEGER,
  calories DOUBLE PRECISION,
  lap_indexes_json JSONB,
  raw_json JSONB,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now(),
  UNIQUE(garmin_activity_id, split_index)
);

CREATE INDEX IF NOT EXISTS idx_activity_typed_splits_activity
  ON health.activity_typed_splits_garmin(garmin_activity_id);
