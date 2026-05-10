CREATE TABLE IF NOT EXISTS health.garmin_exercise_sets_raw (
  id BIGSERIAL PRIMARY KEY,
  garmin_activity_id BIGINT UNIQUE NOT NULL,
  activity_start_utc TIMESTAMPTZ,
  pulled_at_utc TIMESTAMPTZ NOT NULL DEFAULT now(),
  raw_json JSONB NOT NULL,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_garmin_ex_sets_raw_start
  ON health.garmin_exercise_sets_raw(activity_start_utc DESC);

CREATE TABLE IF NOT EXISTS health.lifting_set_facts (
  id BIGSERIAL PRIMARY KEY,
  garmin_activity_id BIGINT NOT NULL,
  activity_start_utc TIMESTAMPTZ,
  set_index INTEGER NOT NULL,
  message_index INTEGER,
  set_start_utc TIMESTAMPTZ,
  set_type TEXT,
  exercise_name TEXT,
  exercise_category TEXT,
  exercise_detect_prob DOUBLE PRECISION,
  reps INTEGER,
  weight_kg DOUBLE PRECISION,
  duration_s DOUBLE PRECISION,
  volume_kg DOUBLE PRECISION,
  is_work_set BOOLEAN,
  is_warmup BOOLEAN,
  source TEXT NOT NULL DEFAULT 'garmin',
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now(),
  UNIQUE(garmin_activity_id, set_index)
);

CREATE INDEX IF NOT EXISTS idx_lifting_facts_exercise_date
  ON health.lifting_set_facts(exercise_name, set_start_utc DESC);
CREATE INDEX IF NOT EXISTS idx_lifting_facts_activity
  ON health.lifting_set_facts(garmin_activity_id);
