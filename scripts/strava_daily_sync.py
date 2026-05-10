#!/usr/bin/env python3
import json
import os

from common_env import load_env
import sys
import time
from datetime import datetime, timezone

import requests
import psycopg2
from psycopg2.extras import Json

WORKSPACE_DIR = Path(__file__).resolve().parents[1]
ENV_PATH = os.getenv("ENV_PATH", str(WORKSPACE_DIR / ".env"))


def require(name: str) -> str:
    v = os.getenv(name)
    if not v:
        raise RuntimeError(f"Missing required env var: {name}")
    return v


def refresh_strava_token(client_id: str, client_secret: str, refresh_token: str):
    r = requests.post(
        "https://www.strava.com/oauth/token",
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        },
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


def get_activities(access_token: str, after_epoch: int | None = None, per_page: int = 200):
    page = 1
    all_items = []
    headers = {"Authorization": f"Bearer {access_token}"}

    while True:
        params = {"per_page": per_page, "page": page}
        if after_epoch:
            params["after"] = after_epoch

        r = requests.get(
            "https://www.strava.com/api/v3/athlete/activities",
            headers=headers,
            params=params,
            timeout=30,
        )
        r.raise_for_status()
        items = r.json()
        if not items:
            break

        all_items.extend(items)
        if len(items) < per_page:
            break
        page += 1

    return all_items


def parse_dt(dt_s: str):
    # Strava format: 2026-02-27T13:41:16Z
    return datetime.fromisoformat(dt_s.replace("Z", "+00:00"))


def upsert_env_values(path: str, updates: dict[str, str | int]):
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    found = {k: False for k in updates.keys()}
    out = []
    for line in lines:
        if "=" in line and not line.lstrip().startswith("#"):
            k = line.split("=", 1)[0].strip()
            if k in updates:
                out.append(f"{k}={updates[k]}\n")
                found[k] = True
                continue
        out.append(line)

    for k, was_found in found.items():
        if not was_found:
            out.append(f"{k}={updates[k]}\n")

    with open(path, "w", encoding="utf-8") as f:
        f.writelines(out)


def main():
    load_env(ENV_PATH)

    strava_client_id = require("STRAVA_CLIENT_ID")
    strava_client_secret = require("STRAVA_CLIENT_SECRET")
    strava_refresh_token = require("STRAVA_REFRESH_TOKEN")

    db_host = os.getenv("PGHOST", "127.0.0.1")
    db_port = int(os.getenv("PGPORT", "5432"))
    db_name = os.getenv("PGDATABASE", "health_ops")
    db_user = os.getenv("PGUSER", "lex")
    db_pass = os.getenv("PGPASSWORD") or os.getenv("POSTGRES_PASSWORD")
    if not db_pass:
        raise RuntimeError("Missing PGPASSWORD or POSTGRES_PASSWORD")

    conn = psycopg2.connect(
        host=db_host,
        port=db_port,
        dbname=db_name,
        user=db_user,
        password=db_pass,
    )
    conn.autocommit = False

    try:
        cur = conn.cursor()

        # read last cursor
        cur.execute("SELECT last_cursor FROM health.sync_state WHERE source = 'strava'")
        row = cur.fetchone()
        after_epoch = int(row[0]) if row and row[0] and row[0].isdigit() else None

        # refresh token every run (simple + reliable)
        token_payload = refresh_strava_token(strava_client_id, strava_client_secret, strava_refresh_token)
        access_token = token_payload["access_token"]
        new_refresh_token = token_payload.get("refresh_token", strava_refresh_token)
        expires_at = int(token_payload.get("expires_at", 0))

        # fetch activities incrementally
        acts = get_activities(access_token, after_epoch=after_epoch)

        max_start_epoch = after_epoch or 0
        upsert_sql = """
        INSERT INTO health.activities (
            source,
            external_activity_id,
            activity_type,
            start_time_utc,
            moving_time_s,
            elapsed_time_s,
            distance_m,
            elevation_gain_m,
            avg_hr,
            max_hr,
            calories,
            raw_json,
            updated_at
        ) VALUES (
            'strava', %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now()
        )
        ON CONFLICT (source, external_activity_id)
        DO UPDATE SET
            activity_type = EXCLUDED.activity_type,
            start_time_utc = EXCLUDED.start_time_utc,
            moving_time_s = EXCLUDED.moving_time_s,
            elapsed_time_s = EXCLUDED.elapsed_time_s,
            distance_m = EXCLUDED.distance_m,
            elevation_gain_m = EXCLUDED.elevation_gain_m,
            avg_hr = EXCLUDED.avg_hr,
            max_hr = EXCLUDED.max_hr,
            calories = EXCLUDED.calories,
            raw_json = EXCLUDED.raw_json,
            updated_at = now()
        """

        for a in acts:
            start_dt = parse_dt(a["start_date"])
            start_epoch = int(start_dt.timestamp())
            if start_epoch > max_start_epoch:
                max_start_epoch = start_epoch

            cur.execute(
                upsert_sql,
                (
                    str(a.get("id")),
                    a.get("type"),
                    start_dt,
                    a.get("moving_time"),
                    a.get("elapsed_time"),
                    a.get("distance"),
                    a.get("total_elevation_gain"),
                    a.get("average_heartrate"),
                    a.get("max_heartrate"),
                    a.get("calories"),
                    Json(a),
                ),
            )

        cur.execute(
            """
            INSERT INTO health.sync_state (source, last_cursor, last_sync_at, status, meta)
            VALUES ('strava', %s, now(), 'ok', %s)
            ON CONFLICT (source)
            DO UPDATE SET
              last_cursor = EXCLUDED.last_cursor,
              last_sync_at = EXCLUDED.last_sync_at,
              status = EXCLUDED.status,
              meta = EXCLUDED.meta
            """,
            (
                str(max_start_epoch),
                Json(
                    {
                        "activities_fetched": len(acts),
                        "token_expires_at": expires_at,
                        "run_utc": datetime.now(timezone.utc).isoformat(),
                    }
                ),
            ),
        )

        conn.commit()

        # persist refreshed token so next run always works
        upsert_env_values(
            ENV_PATH,
            {
                "STRAVA_REFRESH_TOKEN": new_refresh_token,
                "STRAVA_TOKEN_EXPIRES_AT": expires_at,
            },
        )

        print(json.dumps({
            "ok": True,
            "activities_fetched": len(acts),
            "new_last_cursor": max_start_epoch,
            "env_updated": ["STRAVA_REFRESH_TOKEN", "STRAVA_TOKEN_EXPIRES_AT"],
        }, indent=2))

    except Exception as e:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(json.dumps({"ok": False, "error": str(e)}))
        sys.exit(1)
