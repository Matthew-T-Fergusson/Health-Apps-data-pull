# Known Limitations

1. **Provider completeness**
   - Pipeline can only ingest what Garmin/Strava APIs return for the connected account.

2. **Mixed activity IDs**
   - Garmin can emit non-numeric/manual IDs for some activities.
   - Handled safely in current code, but edge cases should continue to be regression-tested.

3. **Data model evolution**
   - Some fields (e.g., steps) may still be stored in JSON payloads instead of first-class columns.

4. **Environment dependency**
   - Requires valid `.env` and reachable Postgres schema (`health.*`).

5. **Community Garmin access**
   - Garmin ingestion relies on community library behavior and may require conservative retry cadence.
