from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from health_metrics import emit_metric, ensure_metrics_table


class FakeCursor:
    def __init__(self):
        self.calls = []

    def execute(self, sql, params=None):
        self.calls.append((sql, params))


def test_ensure_metrics_table_creates_table_and_indexes():
    cur = FakeCursor()
    ensure_metrics_table(cur)
    sql = "\n".join(call[0] for call in cur.calls)
    assert "CREATE TABLE IF NOT EXISTS health.metrics_log" in sql
    assert "idx_metrics_log_source_name" in sql
    assert "idx_metrics_log_run_id" in sql


def test_emit_metric_inserts_flexible_numeric_metric():
    cur = FakeCursor()
    emit_metric(
        cur,
        "days_attempted",
        source="garmin_daily",
        metric_value=7,
        run_id="run-1",
        status="ok",
        tags={"mode": "incremental"},
        meta={"note": "test"},
    )
    insert_calls = [c for c in cur.calls if "INSERT INTO health.metrics_log" in c[0]]
    assert insert_calls
    params = insert_calls[-1][1]
    assert params[0] == "days_attempted"
    assert params[1] == 7.0
    assert params[3] == "garmin_daily"
    assert params[4] == "run-1"
    assert params[5] == "ok"
