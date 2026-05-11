from __future__ import annotations

import json
import os
import sys
from datetime import UTC, datetime
from typing import Any

from psycopg2.extras import Json


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def ensure_metrics_table(cur) -> None:
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS health.metrics_log (
          id BIGSERIAL PRIMARY KEY,
          metric_name TEXT NOT NULL,
          metric_value DOUBLE PRECISION,
          metric_text TEXT,
          source TEXT NOT NULL,
          run_id TEXT,
          status TEXT,
          tags JSONB DEFAULT '{}'::jsonb,
          meta JSONB DEFAULT '{}'::jsonb,
          observed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    cur.execute("CREATE INDEX IF NOT EXISTS idx_metrics_log_observed ON health.metrics_log(observed_at DESC)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_metrics_log_source_name ON health.metrics_log(source, metric_name, observed_at DESC)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_metrics_log_run_id ON health.metrics_log(run_id)")


def _to_jsonable(value: Any) -> Any:
    try:
        json.dumps(value)
        return value
    except TypeError:
        return str(value)


def emit_metric(
    cur,
    metric_name: str,
    *,
    source: str,
    metric_value: float | int | None = None,
    metric_text: str | None = None,
    run_id: str | None = None,
    status: str | None = None,
    tags: dict[str, Any] | None = None,
    meta: dict[str, Any] | None = None,
    observed_at: str | None = None,
) -> None:
    ensure_metrics_table(cur)
    cur.execute(
        """
        INSERT INTO health.metrics_log (
          metric_name, metric_value, metric_text, source, run_id, status, tags, meta, observed_at
        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,COALESCE(%s::timestamptz, now()))
        """,
        (
            metric_name,
            float(metric_value) if metric_value is not None else None,
            metric_text,
            source,
            run_id,
            status,
            Json(_to_jsonable(tags or {})),
            Json(_to_jsonable(meta or {})),
            observed_at,
        ),
    )


def emit_many(cur, metrics: list[dict[str, Any]]) -> None:
    if not metrics:
        return
    ensure_metrics_table(cur)
    for metric in metrics:
        emit_metric(cur, **metric)


def warn_metrics_failure(context: str, exc: Exception) -> None:
    if os.getenv("HEALTH_METRICS_STRICT", "0") == "1":
        raise exc
    print(f"metrics warning ({context}): {exc}", file=sys.stderr)
