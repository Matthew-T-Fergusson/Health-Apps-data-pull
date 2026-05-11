from __future__ import annotations

import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from health_qa_daily import summarize_critical_completeness  # noqa: E402
from manual_activity_capture import find_best_link, gen_manual_id  # noqa: E402
from sync_activity_routes import decode_polyline, upsert_route  # noqa: E402


class FakeCursor:
    def __init__(self, rows=None):
        self.rows = rows or []
        self.executed = []

    def execute(self, sql, params=None):
        self.executed.append((sql, params))

    def fetchall(self):
        return self.rows


class RouteAndManualHelperTests(unittest.TestCase):
    def test_decode_polyline_known_google_example(self):
        coords = decode_polyline("_p~iF~ps|U_ulLnnqC_mqNvxq`@")
        self.assertEqual(
            coords,
            [
                (38.5, -120.2),
                (40.7, -120.95),
                (43.252, -126.453),
            ],
        )

    def test_upsert_route_preserves_non_numeric_external_id_as_string(self):
        cur = FakeCursor()
        upsert_route(
            cur,
            source="garmin",
            external_id="manual_treadmill_20260408T150000Z_abcd1234",
            start_utc=datetime(2026, 4, 8, 15, 0, tzinfo=timezone.utc),
            activity_type="treadmill_manual",
            route_type="manual_no_route",
            distance_m=3200,
            coords=[],
            route_json={"source": "test"},
        )
        params = cur.executed[0][1]
        self.assertEqual(params[1], "manual_treadmill_20260408T150000Z_abcd1234")

    def test_find_best_link_rejects_weak_match(self):
        cur = FakeCursor(rows=[("garmin", "123", 5400, 1800, "cycling")])
        result = find_best_link(
            cur,
            start_utc=datetime(2026, 4, 8, 15, 0, tzinfo=timezone.utc),
            moving_time_s=1800,
            activity_type="treadmill_manual",
        )
        self.assertIsNone(result)

    def test_gen_manual_id_is_stable_prefix_and_non_numeric(self):
        manual_id = gen_manual_id("Treadmill Manual", datetime(2026, 4, 8, 15, 0, tzinfo=timezone.utc))
        self.assertTrue(manual_id.startswith("manual_treadmill_manual_20260408T150000Z_"))
        self.assertFalse(manual_id.isdigit())

    def test_critical_completeness_fails_when_recent_days_have_no_core_metrics(self):
        critical, issues = summarize_critical_completeness(
            (
                7,  # expected_days
                4,  # steps_days
                4,  # sleep_days
                4,  # resting_hr_days
                4,  # hrv_days
                4,  # stress_days
                4,  # body_battery_days
                3,  # all_critical_missing_days
                ["2026-05-01", "2026-05-02", "2026-05-03"],
                3,  # source_empty_days
            )
        )

        self.assertEqual(critical["all_critical_missing_days"], 3)
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0]["severity"], "fail")
        self.assertEqual(issues[0]["type"], "critical_metrics_missing")
        self.assertEqual(issues[0]["dates"], ["2026-05-01", "2026-05-02", "2026-05-03"])

    def test_critical_completeness_passes_when_core_metrics_are_present(self):
        critical, issues = summarize_critical_completeness(
            (
                7, 7, 7, 7, 7, 7, 7,
                0,
                [],
                0,
            )
        )

        self.assertEqual(critical["all_critical_missing_days"], 0)
        self.assertEqual(issues, [])


if __name__ == "__main__":
    unittest.main()
