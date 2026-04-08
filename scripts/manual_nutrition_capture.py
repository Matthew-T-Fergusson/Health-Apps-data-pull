#!/usr/bin/env python3
"""
Manual nutrition capture from chat/photo-assisted estimates.

Decision log:
- Keep meal entries in raw table for traceability and later correction.
- Allow item-level macros so totals can be refined over time.
- Prefer human-estimated entries over forcing brittle database matches.
"""
import argparse
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

import psycopg2
from psycopg2.extras import Json

WORKSPACE_DIR = Path(__file__).resolve().parents[1]
ENV_PATH = os.getenv("ENV_PATH", str(WORKSPACE_DIR.parent / ".env"))
SQL_PATH = os.getenv("HEALTH_NUTRITION_SQL", str(WORKSPACE_DIR / "sql" / "health_manual_nutrition_tables.sql"))


def load_env(path: str):
    p = Path(path)
    if not p.exists():
        return
    for line in p.read_text().splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            os.environ[k.strip()] = v.strip().strip('"').strip("'")


def parse_dt(s: str) -> datetime:
    dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def f(v):
    try:
        return float(v) if v is not None else None
    except Exception:
        return None


def main():
    ap = argparse.ArgumentParser(description="Capture manual meal + item estimates")
    ap.add_argument("--when", required=True, help="ISO datetime for meal time")
    ap.add_argument("--meal-name", default="")
    ap.add_argument("--meal-type", default="other")
    ap.add_argument("--calories", type=float, default=None)
    ap.add_argument("--protein-g", type=float, default=None)
    ap.add_argument("--carbs-g", type=float, default=None)
    ap.add_argument("--fat-g", type=float, default=None)
    ap.add_argument("--confidence", default="estimate")
    ap.add_argument("--notes", default="")
    ap.add_argument("--capture-source", default="chat_photo")
    ap.add_argument("--external-id", default="")
    ap.add_argument("--items-json", default="[]", help='JSON array: [{"name":"chicken","qty":8,"unit":"oz","calories":380,...}]')
    ap.add_argument("--evidence-json", default="{}")
    args = ap.parse_args()

    load_env(ENV_PATH)

    meal_time_utc = parse_dt(args.when)
    external_id = args.external_id.strip() or f"manual_meal_{meal_time_utc.strftime('%Y%m%dT%H%M%SZ')}_{uuid.uuid4().hex[:8]}"
    items = json.loads(args.items_json or "[]")
    evidence = json.loads(args.evidence_json or "{}")

    # derive totals from items if not provided
    item_cals = sum(f(i.get("calories")) or 0 for i in items)
    item_pro = sum(f(i.get("protein_g")) or 0 for i in items)
    item_carbs = sum(f(i.get("carbs_g")) or 0 for i in items)
    item_fat = sum(f(i.get("fat_g")) or 0 for i in items)

    total_calories = args.calories if args.calories is not None else (item_cals if items else None)
    total_protein = args.protein_g if args.protein_g is not None else (item_pro if items else None)
    total_carbs = args.carbs_g if args.carbs_g is not None else (item_carbs if items else None)
    total_fat = args.fat_g if args.fat_g is not None else (item_fat if items else None)

    conn = psycopg2.connect(
        host=os.getenv("PGHOST", "127.0.0.1"),
        port=os.getenv("PGPORT", "5432"),
        dbname=os.getenv("PGDATABASE", "health_ops"),
        user=os.getenv("PGUSER", "lex"),
        password=os.getenv("PGPASSWORD", "lexpass_change_me"),
    )
    conn.autocommit = False
    cur = conn.cursor()

    cur.execute(Path(SQL_PATH).read_text())

    raw_payload = {
        "items_count": len(items),
        "entered_at_utc": datetime.now(timezone.utc).isoformat(),
        "notes": args.notes,
    }

    cur.execute(
        """
        INSERT INTO health.nutrition_manual_raw (
          external_meal_id, meal_time_utc, meal_name, meal_type,
          total_calories_kcal, total_protein_g, total_carbs_g, total_fat_g,
          confidence_level, notes, capture_source, evidence_json, raw_json, updated_at
        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,now())
        ON CONFLICT (external_meal_id) DO UPDATE SET
          meal_time_utc=EXCLUDED.meal_time_utc,
          meal_name=EXCLUDED.meal_name,
          meal_type=EXCLUDED.meal_type,
          total_calories_kcal=EXCLUDED.total_calories_kcal,
          total_protein_g=EXCLUDED.total_protein_g,
          total_carbs_g=EXCLUDED.total_carbs_g,
          total_fat_g=EXCLUDED.total_fat_g,
          confidence_level=EXCLUDED.confidence_level,
          notes=EXCLUDED.notes,
          capture_source=EXCLUDED.capture_source,
          evidence_json=EXCLUDED.evidence_json,
          raw_json=EXCLUDED.raw_json,
          updated_at=now()
        """,
        (
            external_id,
            meal_time_utc,
            args.meal_name or None,
            args.meal_type,
            total_calories,
            total_protein,
            total_carbs,
            total_fat,
            args.confidence,
            args.notes,
            args.capture_source,
            Json(evidence),
            Json(raw_payload),
        ),
    )

    cur.execute("DELETE FROM health.nutrition_manual_items WHERE external_meal_id=%s", (external_id,))
    for idx, item in enumerate(items):
        cur.execute(
            """
            INSERT INTO health.nutrition_manual_items (
              external_meal_id, item_index, item_name, quantity, unit,
              calories_kcal, protein_g, carbs_g, fat_g, notes, raw_json, updated_at
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,now())
            """,
            (
                external_id,
                idx,
                item.get("name") or f"item_{idx+1}",
                f(item.get("qty")),
                item.get("unit"),
                f(item.get("calories")),
                f(item.get("protein_g")),
                f(item.get("carbs_g")),
                f(item.get("fat_g")),
                item.get("notes"),
                Json(item),
            ),
        )

    conn.commit()
    cur.close()
    conn.close()

    print(json.dumps({
        "ok": True,
        "external_meal_id": external_id,
        "meal_time_utc": meal_time_utc.isoformat(),
        "meal_name": args.meal_name,
        "totals": {
            "calories_kcal": total_calories,
            "protein_g": total_protein,
            "carbs_g": total_carbs,
            "fat_g": total_fat,
        },
        "items_logged": len(items),
    }, indent=2))


if __name__ == "__main__":
    main()
