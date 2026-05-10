CREATE TABLE IF NOT EXISTS health.activity_training_metrics_garmin (
  id BIGSERIAL PRIMARY KEY,
  garmin_activity_id BIGINT UNIQUE NOT NULL,
  activity_start_utc TIMESTAMPTZ,
  activity_type TEXT,
  training_load DOUBLE PRECISION,
  aerobic_training_effect DOUBLE PRECISION,
  anaerobic_training_effect DOUBLE PRECISION,
  training_effect_label TEXT,
  vo2max_value DOUBLE PRECISION,
  avg_speed_mps DOUBLE PRECISION,
  max_speed_mps DOUBLE PRECISION,
  avg_hr INTEGER,
  max_hr INTEGER,
  avg_cadence DOUBLE PRECISION,
  max_cadence DOUBLE PRECISION,
  avg_power DOUBLE PRECISION,
  max_power DOUBLE PRECISION,
  calories DOUBLE PRECISION,
  moving_time_s DOUBLE PRECISION,
  elapsed_time_s DOUBLE PRECISION,
  distance_m DOUBLE PRECISION,
  elevation_gain_m DOUBLE PRECISION,
  raw_json JSONB,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_activity_training_metrics_start
  ON health.activity_training_metrics_garmin(activity_start_utc DESC);

CREATE TABLE IF NOT EXISTS health.activity_lap_facts_garmin (
  id BIGSERIAL PRIMARY KEY,
  garmin_activity_id BIGINT NOT NULL,
  lap_index INTEGER NOT NULL,
  start_utc TIMESTAMPTZ,
  duration_s DOUBLE PRECISION,
  elapsed_duration_s DOUBLE PRECISION,
  distance_m DOUBLE PRECISION,
  avg_speed_mps DOUBLE PRECISION,
  max_speed_mps DOUBLE PRECISION,
  avg_hr INTEGER,
  max_hr INTEGER,
  avg_cadence DOUBLE PRECISION,
  avg_power DOUBLE PRECISION,
  elevation_gain_m DOUBLE PRECISION,
  elevation_loss_m DOUBLE PRECISION,
  calories DOUBLE PRECISION,
  lap_type TEXT,
  raw_json JSONB,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now(),
  UNIQUE(garmin_activity_id, lap_index)
);

CREATE INDEX IF NOT EXISTS idx_activity_lap_facts_activity
  ON health.activity_lap_facts_garmin(garmin_activity_id);

CREATE TABLE IF NOT EXISTS health.activity_zone_facts_garmin (
  id BIGSERIAL PRIMARY KEY,
  garmin_activity_id BIGINT NOT NULL,
  zone_source TEXT NOT NULL, -- hr|power
  zone_index INTEGER NOT NULL,
  zone_name TEXT,
  seconds_in_zone DOUBLE PRECISION,
  pct_in_zone DOUBLE PRECISION,
  raw_json JSONB,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now(),
  UNIQUE(garmin_activity_id, zone_source, zone_index)
);

CREATE INDEX IF NOT EXISTS idx_activity_zone_facts_activity
  ON health.activity_zone_facts_garmin(garmin_activity_id);
