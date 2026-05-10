CREATE TABLE IF NOT EXISTS health.readiness_daily (
  id BIGSERIAL PRIMARY KEY,
  source TEXT NOT NULL DEFAULT 'garmin_custom',
  metric_date DATE NOT NULL,

  -- comparable Garmin readiness
  garmin_readiness_score DOUBLE PRECISION,
  garmin_readiness_level TEXT,
  garmin_feedback_short TEXT,
  garmin_recovery_time_h DOUBLE PRECISION,
  garmin_acute_load DOUBLE PRECISION,

  -- inputs used for custom score
  resting_hr DOUBLE PRECISION,
  resting_hr_baseline_14d DOUBLE PRECISION,
  hrv_ms DOUBLE PRECISION,
  hrv_baseline_28d DOUBLE PRECISION,
  stress_avg DOUBLE PRECISION,
  body_battery_avg DOUBLE PRECISION,
  sleep_seconds INTEGER,
  sleep_score DOUBLE PRECISION,
  training_load_prev_day DOUBLE PRECISION,

  -- custom output
  custom_readiness_score DOUBLE PRECISION,
  custom_readiness_level TEXT,
  score_delta_vs_garmin DOUBLE PRECISION,
  notes TEXT,

  raw_json JSONB,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now(),
  UNIQUE(source, metric_date)
);

CREATE INDEX IF NOT EXISTS idx_readiness_daily_date
  ON health.readiness_daily(metric_date DESC);
