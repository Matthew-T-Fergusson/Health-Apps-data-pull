# Health Data Consent and Source Lineage

This project stores personal health and fitness data for a private data-ops prototype. The consent model is intentionally explicit so future AI recommendations can be audited back to source data, purpose, and consent version.

Current consent version: `health-consent-2026-05-11`

## Scope and purposes

Allowed purposes under the current project consent version:

- Personal health/fitness dashboarding
- Data quality monitoring and recovery operations
- Source outage/backfill handling
- Manual correction/fallback capture
- Future AI-assisted summaries/recommendations, only when recommendations can cite the underlying data used

Not in current scope:

- Selling or sharing health data
- Public dashboards containing private data
- Training third-party models on personal raw health data
- Destructive source purging without an explicit dry-run/review flow

## Source inventory

### Garmin

Data pulled/stored:

- Daily wellness: steps, sleep, resting heart rate, HRV, stress, body battery, calories
- Body composition where available: weight/body-fat style fields
- Activities and activity details: activity type, start time, distance, duration, HR, zones/laps/splits/weather where available
- Readiness and lifting/set details where available
- Raw/source payloads where useful for troubleshooting and schema drift detection

Storage examples:

- `health.daily_metrics`
- `health.sleep_sessions`
- `health.body_composition_daily`
- `health.activities_garmin_raw`
- `health.activities`
- `health.readiness_daily`
- Garmin enrichment/lifting tables

Disable going forward:

- Remove Garmin credentials/tokenstore from the runtime environment.
- Disable scheduled Garmin sync/orchestrator runs.

Revocation/purge design:

- A future `--purge-source garmin --dry-run` flow should enumerate all Garmin-owned raw and curated rows before deletion/tombstoning.
- Derived/matched rows must be reviewed before deletion because they may connect to Strava or manual entries.

### Strava

Data pulled/stored:

- Activities: type, start time, distance, duration, elevation, heart-rate/calorie fields where available
- Raw activity payloads
- Match links between Strava and Garmin activities

Storage examples:

- `health.activities_strava_raw`
- `health.activity_matches`
- unified activity views

Disable going forward:

- Remove Strava API credentials/token from runtime environment.
- Disable Strava sync in orchestrator or scheduled jobs.

Revocation/purge design:

- A future `--purge-source strava --dry-run` flow should report Strava raw rows and match links that would be removed.
- Garmin/manual activity records should not be deleted simply because a Strava match is removed.

### Apple Health export

Data pulled/stored:

- Export-derived daily aggregates: steps, walking/running distance, active/basal energy, flights climbed, sleep seconds
- Weight/body-composition fallback where available from export
- Record counts and summarized raw metadata, not necessarily every source record

Storage examples:

- `health.apple_health_daily`
- `health.body_composition_daily` rows with `source='apple_health'`
- synthesized daily views

Disable going forward:

- Stop importing Apple Health export files.
- Remove export files from local staging/storage where applicable.

Revocation/purge design:

- A future `--purge-source apple_health --dry-run` flow should enumerate Apple Health aggregate rows and Apple-sourced body-composition rows.

### Manual activity

Data pulled/stored:

- User-provided manual workout/activity facts from chat/screenshots/fallback capture
- Notes/evidence metadata when supplied
- Optional links to Garmin or Strava records to prevent duplicate counting

Storage examples:

- `health.activities_manual_raw`
- `health.activity_manual_links`
- `health.activities_unified_with_manual`

Disable going forward:

- Stop submitting manual activity captures.

Revocation/purge design:

- A future purge should distinguish user-entered manual facts from device/imported source data.
- Deleting manual activity should also remove manual links, but not device records.

### Manual nutrition

Data pulled/stored:

- User-provided meal entries, item estimates, macro estimates, notes/evidence metadata
- Daily nutrition rollups derived from manual entries

Storage examples:

- `health.nutrition_manual_raw`
- `health.nutrition_manual_items`
- `health.nutrition_daily_totals`
- `health.health_daily_combined`

Disable going forward:

- Stop submitting manual nutrition captures.

Revocation/purge design:

- A future purge should remove manual meal raw/items and allow daily rollups/views to naturally reflect removal.

## Lineage view

`health.data_lineage` provides source-level provenance for key metrics and entities. It answers:

- What source system produced this value?
- What table stores it?
- When was it pulled/updated?
- Which consent version applies?
- What entity/date does it describe?

Example:

```sql
SELECT metric_date, source_system, metric_name, metric_value, pulled_at, consent_version, storage_table
FROM health.data_lineage
WHERE metric_date >= current_date - interval '7 day'
ORDER BY metric_date DESC, source_system, metric_name;
```

## Revocation vs purge

Revocation means: stop collecting future data from a source.

Purge means: remove or tombstone already-stored data from a source.

Purge is intentionally not implemented in this task because it is destructive and source relationships are non-trivial. The safe implementation belongs in `MTF-168` and should include:

1. `--dry-run` by default.
2. Table-by-table affected row counts.
3. Explicit source mapping.
4. Confirmation before destructive delete/tombstone.
5. Audit record of request, execution, affected counts, and errors.
6. Derived-data handling rules so Garmin/Strava/manual cross-source relationships are not accidentally destroyed.

## Responsible AI note

Future AI insights should not simply say “the AI recommends X.” They should cite the source metrics that support the recommendation and record the consent version tied to the input data snapshot.
