from __future__ import annotations

import sys
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from garmin_daily_sync import build_sync_dates


def test_build_backfill_dates_requires_explicit_range():
    args = SimpleNamespace(mode="backfill", since=None, until="2026-05-03", max_days=31)
    with pytest.raises(SystemExit):
        build_sync_dates(args, date(2026, 5, 11))


def test_build_backfill_dates_is_inclusive_and_forward_order():
    args = SimpleNamespace(mode="backfill", since="2026-05-01", until="2026-05-03", max_days=31)
    assert build_sync_dates(args, date(2026, 5, 11)) == ["2026-05-01", "2026-05-02", "2026-05-03"]


def test_build_backfill_dates_rejects_too_large_range():
    args = SimpleNamespace(mode="backfill", since="2026-05-01", until="2026-05-03", max_days=2)
    with pytest.raises(SystemExit):
        build_sync_dates(args, date(2026, 5, 11))


def test_build_backfill_dates_rejects_future_until():
    args = SimpleNamespace(mode="backfill", since="2026-05-11", until="2026-05-12", max_days=31)
    with pytest.raises(SystemExit):
        build_sync_dates(args, date(2026, 5, 11))
