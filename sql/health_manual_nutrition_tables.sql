-- Manual nutrition capture tables + daily rollups

CREATE TABLE IF NOT EXISTS health.nutrition_manual_raw (
  id BIGSERIAL PRIMARY KEY,
  external_meal_id TEXT UNIQUE NOT NULL,
  meal_time_utc TIMESTAMPTZ NOT NULL,
  meal_name TEXT,
  meal_type TEXT, -- breakfast|lunch|dinner|snack|other
  total_calories_kcal DOUBLE PRECISION,
  total_protein_g DOUBLE PRECISION,
  total_carbs_g DOUBLE PRECISION,
  total_fat_g DOUBLE PRECISION,
  confidence_level TEXT DEFAULT 'estimate', -- estimate|high|verified
  notes TEXT,
  capture_source TEXT DEFAULT 'chat',
  evidence_json JSONB,
  raw_json JSONB,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_nutrition_manual_time ON health.nutrition_manual_raw(meal_time_utc DESC);

CREATE TABLE IF NOT EXISTS health.nutrition_manual_items (
  id BIGSERIAL PRIMARY KEY,
  external_meal_id TEXT NOT NULL REFERENCES health.nutrition_manual_raw(external_meal_id) ON DELETE CASCADE,
  item_index INTEGER NOT NULL,
  item_name TEXT NOT NULL,
  quantity DOUBLE PRECISION,
  unit TEXT,
  calories_kcal DOUBLE PRECISION,
  protein_g DOUBLE PRECISION,
  carbs_g DOUBLE PRECISION,
  fat_g DOUBLE PRECISION,
  notes TEXT,
  raw_json JSONB,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now(),
  UNIQUE(external_meal_id, item_index)
);

CREATE INDEX IF NOT EXISTS idx_nutrition_manual_items_meal ON health.nutrition_manual_items(external_meal_id);

CREATE OR REPLACE VIEW health.nutrition_daily_totals AS
SELECT
  (meal_time_utc AT TIME ZONE 'UTC')::date AS metric_date,
  count(*) AS meals_logged,
  sum(coalesce(total_calories_kcal,0)) AS calories_kcal,
  sum(coalesce(total_protein_g,0)) AS protein_g,
  sum(coalesce(total_carbs_g,0)) AS carbs_g,
  sum(coalesce(total_fat_g,0)) AS fat_g,
  max(updated_at) AS updated_at
FROM health.nutrition_manual_raw
GROUP BY 1;

-- Combined daily view: nutrition + activity/recovery markers
CREATE OR REPLACE VIEW health.health_daily_combined AS
SELECT
  d.metric_date,
  d.resting_hr,
  d.hrv_ms,
  d.stress_avg,
  d.body_battery_avg,
  d.steps,
  d.sleep_seconds,
  d.calories_total AS activity_calories_kcal,
  n.meals_logged,
  n.calories_kcal AS nutrition_calories_kcal,
  n.protein_g,
  n.carbs_g,
  n.fat_g,
  r.garmin_readiness_score,
  r.sleep_score,
  CASE
    WHEN n.calories_kcal IS NULL OR d.calories_total IS NULL THEN NULL
    ELSE n.calories_kcal - d.calories_total
  END AS intake_minus_activity_kcal
FROM health.daily_metrics d
LEFT JOIN health.nutrition_daily_totals n ON n.metric_date = d.metric_date
LEFT JOIN health.readiness_daily r ON r.metric_date = d.metric_date;
