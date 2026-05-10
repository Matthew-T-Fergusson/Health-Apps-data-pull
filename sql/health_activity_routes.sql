CREATE TABLE IF NOT EXISTS health.activity_routes (
  id BIGSERIAL PRIMARY KEY,
  source TEXT NOT NULL,                -- garmin|strava
  external_activity_id TEXT NOT NULL,
  activity_start_utc TIMESTAMPTZ,
  activity_type TEXT,
  route_type TEXT NOT NULL,            -- strava_polyline|garmin_lap_path|strava_start_end
  point_count INTEGER,
  min_lat DOUBLE PRECISION,
  min_lon DOUBLE PRECISION,
  max_lat DOUBLE PRECISION,
  max_lon DOUBLE PRECISION,
  distance_m DOUBLE PRECISION,
  route_geojson JSONB,                 -- GeoJSON LineString (or minimal)
  route_json JSONB,                    -- raw route payload sidecar
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now(),
  UNIQUE(source, external_activity_id)
);

CREATE INDEX IF NOT EXISTS idx_activity_routes_start ON health.activity_routes(activity_start_utc DESC);
CREATE INDEX IF NOT EXISTS idx_activity_routes_source ON health.activity_routes(source);
