# Data Coverage Matrix (Current)

| Domain | Source | Table(s) | Status |
|---|---|---|---|
| Daily summary metrics | Garmin | `health.daily_metrics`, `health.daily_vitals_garmin` | Partial/Active |
| Readiness & sleep signals | Garmin | `health.readiness_daily` | Active |
| Activity raw feed | Garmin | `health.activities_garmin_raw` | Active |
| Activity raw feed | Strava | `health.activities_strava_raw` | Active |
| Activity training enrichment | Garmin | `health.activity_training_metrics_garmin` | Active |
| Lap details | Garmin | `health.activity_lap_facts_garmin` | Active |
| Typed splits | Garmin | `health.activity_typed_splits_garmin` | Active |
| Weather overlays | Garmin | `health.activity_weather_garmin` | Active |
| HR/Power zones | Garmin | `health.activity_zone_facts_garmin` | Active |
| Route geometry | Garmin/Strava | `health.activity_routes`, `health.activity_routes_deduped` | Active |

> Note: Coverage reflects current implemented pipeline and may not include every provider field.
