#!/usr/bin/env python3
"""
Builds route geometry records from provider-specific raw activity feeds.

Why we keep provider raw tables separate first:
- Garmin and Strava use different identifiers and payload shapes.
- Some Garmin activities can be manual/non-numeric IDs; Strava IDs are numeric but separate namespace.
- Keeping raw sources isolated prevents accidental overwrite/collision during ingest.

Why this script exists:
- Create a normalized route layer (`health.activity_routes`) from both raw feeds.
- Preserve source attribution for traceability/debugging.
- Prepare clean geometry inputs for dedupe/matching logic downstream.

Dedupe strategy note:
- We do not force cross-provider merge here.
- This step is source-preserving by design; cross-source matching/deduping is handled later
  so we keep reversible lineage and avoid destructive assumptions.
"""
import json
import os
from pathlib import Path
import psycopg2
from psycopg2.extras import Json

WORKSPACE_DIR = Path(__file__).resolve().parents[1]
ENV_PATH = os.getenv("ENV_PATH", str(WORKSPACE_DIR / ".env"))
SQL_PATH = os.getenv("HEALTH_ACTIVITY_ROUTES_SQL", str(WORKSPACE_DIR / "sql" / "health_activity_routes.sql"))


def load_env(path):
    for line in Path(path).read_text().splitlines():
        if '=' in line and not line.strip().startswith('#'):
            k, v = line.split('=', 1)
            os.environ[k.strip()] = v.strip().strip('"').strip("'")


def decode_polyline(polyline_str):
    # Google polyline decoder (lat, lon)
    if not polyline_str:
        return []
    index, lat, lng = 0, 0, 0
    coordinates = []
    length = len(polyline_str)
    while index < length:
        shift = result = 0
        while True:
            b = ord(polyline_str[index]) - 63
            index += 1
            result |= (b & 0x1f) << shift
            shift += 5
            if b < 0x20:
                break
        dlat = ~(result >> 1) if (result & 1) else (result >> 1)
        lat += dlat

        shift = result = 0
        while True:
            b = ord(polyline_str[index]) - 63
            index += 1
            result |= (b & 0x1f) << shift
            shift += 5
            if b < 0x20:
                break
        dlng = ~(result >> 1) if (result & 1) else (result >> 1)
        lng += dlng

        coordinates.append((lat / 1e5, lng / 1e5))
    return coordinates


def bbox(coords):
    if not coords:
        return (None, None, None, None)
    lats = [c[0] for c in coords]
    lons = [c[1] for c in coords]
    return (min(lats), min(lons), max(lats), max(lons))


def to_linestring(coords):
    # GeoJSON lon/lat
    return {
        "type": "LineString",
        "coordinates": [[lon, lat] for (lat, lon) in coords]
    }


def upsert_route(cur, source, external_id, start_utc, activity_type, route_type, distance_m, coords, route_json):
    mnlat, mnlon, mxlat, mxlon = bbox(coords)
    geo = to_linestring(coords) if coords else None
    cur.execute(
        """
        INSERT INTO health.activity_routes (
          source, external_activity_id, activity_start_utc, activity_type,
          route_type, point_count, min_lat, min_lon, max_lat, max_lon,
          distance_m, route_geojson, route_json, updated_at
        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,now())
        ON CONFLICT (source, external_activity_id) DO UPDATE SET
          activity_start_utc=EXCLUDED.activity_start_utc,
          activity_type=EXCLUDED.activity_type,
          route_type=EXCLUDED.route_type,
          point_count=EXCLUDED.point_count,
          min_lat=EXCLUDED.min_lat,
          min_lon=EXCLUDED.min_lon,
          max_lat=EXCLUDED.max_lat,
          max_lon=EXCLUDED.max_lon,
          distance_m=EXCLUDED.distance_m,
          route_geojson=EXCLUDED.route_geojson,
          route_json=EXCLUDED.route_json,
          updated_at=now()
        """,
        (
            source,
            str(external_id),
            start_utc,
            activity_type,
            route_type,
            len(coords) if coords else 0,
            mnlat,
            mnlon,
            mxlat,
            mxlon,
            distance_m,
            Json(geo) if geo else None,
            Json(route_json) if route_json is not None else None,
        ),
    )


def sync_strava(cur):
    cur.execute("""
        SELECT external_activity_id, start_time_utc, activity_type, distance_m, raw_json
        FROM health.activities_strava_raw
        ORDER BY start_time_utc ASC
    """)
    rows = cur.fetchall()
    ok = 0
    for ext_id, start_utc, activity_type, distance_m, raw in rows:
        raw = raw or {}
        coords = []
        route_type = "strava_start_end"
        map_obj = raw.get('map') if isinstance(raw, dict) else None
        poly = (map_obj or {}).get('summary_polyline') if isinstance(map_obj, dict) else None
        if poly:
            try:
                coords = decode_polyline(poly)
                route_type = "strava_polyline"
            except Exception:
                coords = []

        if not coords:
            start_ll = raw.get('start_latlng') if isinstance(raw, dict) else None
            end_ll = raw.get('end_latlng') if isinstance(raw, dict) else None
            if isinstance(start_ll, (list, tuple)) and len(start_ll) == 2:
                coords.append((float(start_ll[0]), float(start_ll[1])))
            if isinstance(end_ll, (list, tuple)) and len(end_ll) == 2:
                coords.append((float(end_ll[0]), float(end_ll[1])))

        upsert_route(cur, 'strava', ext_id, start_utc, activity_type, route_type, distance_m, coords, {
            'map': raw.get('map') if isinstance(raw, dict) else None,
            'start_latlng': raw.get('start_latlng') if isinstance(raw, dict) else None,
            'end_latlng': raw.get('end_latlng') if isinstance(raw, dict) else None,
        })
        ok += 1
    return len(rows), ok


def sync_garmin(cur):
    cur.execute("""
        SELECT g.external_activity_id, g.start_time_utc, g.activity_type, g.distance_m
        FROM health.activities_garmin_raw g
        ORDER BY g.start_time_utc ASC
    """)
    acts = cur.fetchall()
    ok = 0
    for ext_id, start_utc, activity_type, distance_m in acts:
        laps = []
        ext_id_str = str(ext_id)
        if ext_id_str.isdigit():
            cur.execute("""
                SELECT lap_index, start_utc,
                       COALESCE((raw_json->>'startLatitude')::double precision, NULL) AS start_lat,
                       COALESCE((raw_json->>'startLongitude')::double precision, NULL) AS start_lon,
                       COALESCE((raw_json->>'endLatitude')::double precision, NULL) AS end_lat,
                       COALESCE((raw_json->>'endLongitude')::double precision, NULL) AS end_lon
                FROM health.activity_lap_facts_garmin
                WHERE garmin_activity_id = %s
                ORDER BY lap_index
            """, (int(ext_id_str),))
            laps = cur.fetchall()
        coords = []
        for _, _, slat, slon, elat, elon in laps:
            if slat is not None and slon is not None:
                pt = (float(slat), float(slon))
                if not coords or coords[-1] != pt:
                    coords.append(pt)
            if elat is not None and elon is not None:
                pt = (float(elat), float(elon))
                if not coords or coords[-1] != pt:
                    coords.append(pt)

        route_type = "garmin_lap_path" if len(coords) >= 2 else "garmin_anchor_only"
        route_json = {
            'lap_count': len(laps),
            'built_from': 'activity_lap_facts_garmin.start/end latlon',
        }
        upsert_route(cur, 'garmin', ext_id, start_utc, activity_type, route_type, distance_m, coords, route_json)
        ok += 1
    return len(acts), ok


def main():
    load_env(ENV_PATH)

    conn = psycopg2.connect(
        host=os.getenv('PGHOST', '127.0.0.1'),
        port=os.getenv('PGPORT', '5432'),
        dbname=os.getenv('PGDATABASE', 'health_ops'),
        user=os.getenv('PGUSER', 'lex'),
        password=os.getenv('PGPASSWORD', 'lexpass_change_me'),
    )
    conn.autocommit = False
    cur = conn.cursor()
    cur.execute(Path(SQL_PATH).read_text())

    s_total, s_ok = sync_strava(cur)
    g_total, g_ok = sync_garmin(cur)

    cur.execute(
        """
        INSERT INTO health.sync_state (source, last_cursor, last_sync_at, status, meta)
        VALUES ('activity_routes', now()::text, now(), 'ok', %s)
        ON CONFLICT (source) DO UPDATE SET
          last_cursor=EXCLUDED.last_cursor,
          last_sync_at=EXCLUDED.last_sync_at,
          status=EXCLUDED.status,
          meta=EXCLUDED.meta
        """,
        (Json({
            'strava_total': s_total,
            'strava_ok': s_ok,
            'garmin_total': g_total,
            'garmin_ok': g_ok,
        }),),
    )

    conn.commit()
    cur.close()
    conn.close()

    print(json.dumps({
        'ok': True,
        'strava_total': s_total,
        'strava_ok': s_ok,
        'garmin_total': g_total,
        'garmin_ok': g_ok,
    }, indent=2))


if __name__ == '__main__':
    main()
