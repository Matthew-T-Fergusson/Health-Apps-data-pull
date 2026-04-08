# Support Scope

## In scope
- Garmin + Strava ingest orchestration
- Activity enrichment (details/laps/zones/weather/typed splits)
- Route geometry extraction and dedupe-ready routing table
- QA freshness/coverage checks and run artifacts

## Out of scope (current)
- Full parity with every provider endpoint/metric
- Mobile app or UI productization
- Managed cloud deployment automation

## Operational expectation
- Run one-shot via `scripts/health_primary_sync_safe.sh`
- Schedule with conservative cadence (recommended every 6 hours)
- Monitor output artifacts in `output/`
