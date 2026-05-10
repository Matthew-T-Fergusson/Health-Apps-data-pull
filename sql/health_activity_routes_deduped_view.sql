CREATE OR REPLACE VIEW health.activity_routes_deduped AS
WITH matched_candidates AS (
  SELECT
    m.id AS match_id,
    m.match_confidence,
    r.source,
    r.external_activity_id,
    r.activity_start_utc,
    r.activity_type,
    r.route_type,
    r.point_count,
    r.min_lat,
    r.min_lon,
    r.max_lat,
    r.max_lon,
    r.distance_m,
    r.route_geojson,
    r.route_json,
    m.strava_external_activity_id,
    m.garmin_external_activity_id,
    ROW_NUMBER() OVER (
      PARTITION BY m.id
      ORDER BY COALESCE(r.point_count,0) DESC,
               CASE WHEN r.source='strava' THEN 0 ELSE 1 END,
               r.updated_at DESC
    ) AS rn
  FROM health.activity_matches m
  JOIN health.activity_routes r
    ON (r.source='strava' AND r.external_activity_id=m.strava_external_activity_id)
    OR (r.source='garmin' AND r.external_activity_id=m.garmin_external_activity_id)
),
matched_pick AS (
  SELECT
    CONCAT('match:', match_id) AS canonical_route_id,
    'matched'::text AS dedupe_type,
    source AS selected_source,
    external_activity_id AS selected_external_activity_id,
    strava_external_activity_id,
    garmin_external_activity_id,
    match_confidence,
    activity_start_utc,
    activity_type,
    route_type,
    point_count,
    min_lat, min_lon, max_lat, max_lon,
    distance_m,
    route_geojson,
    route_json
  FROM matched_candidates
  WHERE rn=1
),
unmatched AS (
  SELECT
    CONCAT(r.source, ':', r.external_activity_id) AS canonical_route_id,
    'unmatched'::text AS dedupe_type,
    r.source AS selected_source,
    r.external_activity_id AS selected_external_activity_id,
    NULL::text AS strava_external_activity_id,
    NULL::text AS garmin_external_activity_id,
    NULL::double precision AS match_confidence,
    r.activity_start_utc,
    r.activity_type,
    r.route_type,
    r.point_count,
    r.min_lat, r.min_lon, r.max_lat, r.max_lon,
    r.distance_m,
    r.route_geojson,
    r.route_json
  FROM health.activity_routes r
  WHERE NOT EXISTS (
    SELECT 1 FROM health.activity_matches m
    WHERE (r.source='strava' AND r.external_activity_id=m.strava_external_activity_id)
       OR (r.source='garmin' AND r.external_activity_id=m.garmin_external_activity_id)
  )
)
SELECT * FROM matched_pick
UNION ALL
SELECT * FROM unmatched;
