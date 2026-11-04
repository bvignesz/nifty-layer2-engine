"""Offline tests for read-only collector health check."""
from datetime import datetime, timezone
from unittest.mock import patch

from nifty_l2.collector_health import check
from nifty_l2.storage import Store


def test_waiting_after_hours(tmp_path):
    db = tmp_path / "research.db"
    Store(db)
    with patch("nifty_l2.collector_health.service_state", return_value="active"):
        report = check(db, now=datetime(2026, 11, 4, 16, 30, tzinfo=timezone.utc))
    assert report["status"] == "WAITING_OUTSIDE_REGULAR_WINDOW"


def test_missing_observations_in_session(tmp_path):
    db = tmp_path / "research.db"
    Store(db)
    with patch("nifty_l2.collector_health.service_state", return_value="active"):
        report = check(db, now=datetime(2026, 11, 5, 4, 15, tzinfo=timezone.utc))
    assert report["status"] == "WARN"
    assert report["scheduled_today"] == 0


def test_recent_scheduled_event(tmp_path):
    db = tmp_path / "research.db"
    store = Store(db)
    with store.transaction() as conn:
        store.event(conn, observed_at="2026-11-05T09:42:00+05:30",
                    kind="scheduled_research", source="test", payload={})
    with patch("nifty_l2.collector_health.service_state", return_value="active"):
        report = check(db, now=datetime(2026, 11, 5, 4, 15, tzinfo=timezone.utc))
    assert report["status"] == "OK"
    assert report["scheduled_today"] == 1


def test_inactive_service_fails(tmp_path):
    db = tmp_path / "research.db"
    Store(db)
    with patch("nifty_l2.collector_health.service_state", return_value="inactive"):
        report = check(db, now=datetime(2026, 11, 4, 16, 30, tzinfo=timezone.utc))
    assert report["status"] == "FAIL"


def test_missing_database_does_not_create(tmp_path):
    db = tmp_path / "missing.db"
    with patch("nifty_l2.collector_health.service_state", return_value="active"):
        report = check(db, now=datetime(2026, 11, 4, 16, 30, tzinfo=timezone.utc))
    assert report["status"] == "FAIL"
    assert not db.exists()
