from datetime import datetime, timedelta
import fcntl
import json

import pytest

from nifty_l2 import fyers
from nifty_l2.collector import Collector
from nifty_l2.market_calendar import session, slots, next_slot
from nifty_l2.storage import timestamp


def at(value):
    return datetime.fromisoformat(value + '+05:30')


def collector_for(tmp_path):
    token = tmp_path / 'config/token.json'
    fyers.save_token(token, {'client_id': 'TEST', 'access_token': 'TEST'})
    return Collector(tmp_path / 'runtime', token)


def logs(collector):
    with collector.store.connect() as conn:
        return conn.execute('SELECT scheduled_at_utc,status FROM run_log ORDER BY scheduled_at_utc').fetchall()


def test_calendar_holiday_weekend_special_and_unknown():
    assert session(at('2026-11-10T10:00:00').date()) is None
    assert session(at('2026-11-07T10:00:00').date()) is None
    special = session(at('2026-11-08T10:00:00').date())
    assert special == (at('2026-11-08T14:20:00'), at('2026-11-08T15:40:00'))
    regular = slots(at('2026-11-05T10:00:00').date())
    assert regular[0] == at('2026-11-05T09:15:00')
    assert regular[-1] == at('2026-11-05T15:39:00')
    assert all(b - a == timedelta(minutes=3) for a, b in zip(regular, regular[1:]))
    assert next_slot(at('2026-11-06T16:00:00')) == at('2026-11-08T14:20:00')
    assert next_slot(at('2026-12-31T16:00:00')) is None
    with pytest.raises(ValueError, match='calendar'):
        session(at('2027-01-01T10:00:00').date())


def test_due_boundary_once_across_restarts_and_no_backfill(tmp_path, monkeypatch):
    collector = collector_for(tmp_path)
    started = []
    def start(**kwargs):
        started.append(kwargs)
        collector.record_slot(datetime.fromisoformat(kwargs['scheduled_at'].replace('Z', '+00:00')), 'COMPLETED', 'Test completion')
    monkeypatch.setattr(collector.runner, 'start', start)
    now = at('2026-11-05T09:21:04')
    status = collector.tick(now)
    assert status['status'] == 'ACTIVE'
    assert len(started) == 1
    assert started[0]['scheduled_at'] == timestamp(at('2026-11-05T09:21:00'))
    assert [row[1] for row in logs(collector)] == ['MISSED', 'MISSED', 'COMPLETED']
    collector.tick(now + timedelta(seconds=5))
    assert len(started) == 1
    restarted = Collector(collector.directory, collector.runner.token_path)
    monkeypatch.setattr(restarted.runner, 'start', lambda **kwargs: pytest.fail('Duplicate boundary launched'))
    restarted.tick(now + timedelta(seconds=10))
    restarted.tick(at('2026-11-05T09:24:40'))
    assert logs(restarted)[-1][1] == 'MISSED'


def test_closed_pause_missing_token_and_calendar_expiry(tmp_path, monkeypatch):
    collector = collector_for(tmp_path)
    monkeypatch.setattr(collector.runner, 'start', lambda **kwargs: pytest.fail('Worker launched outside market'))
    assert collector.tick(at('2026-11-05T08:00:00'))['status'] == 'WAITING'
    assert logs(collector) == []
    assert collector.tick(at('2026-11-07T10:00:00'))['status'] == 'WAITING'
    assert collector.tick(at('2026-11-10T10:00:00'))['status'] == 'WAITING'
    assert logs(collector) == []
    fyers.save_token(collector.directory / 'automation.json', {'enabled': False})
    assert collector.tick(at('2026-11-05T09:15:04'))['status'] == 'PAUSED'
    assert logs(collector) == []
    fyers.save_token(collector.directory / 'automation.json', {'enabled': True})
    collector.runner.token_path.unlink()
    collector.tick(at('2026-11-05T09:15:04'))
    assert logs(collector)[0][1] == 'BLOCKED'
    assert collector.tick(at('2027-01-01T09:15:04'))['status'] == 'CALENDAR_OR_CONFIG_ERROR'


def test_overlap_skipped_and_abandoned_worker_recovered(tmp_path, monkeypatch):
    collector = collector_for(tmp_path)
    # Simulate another process holding the shared execution lock.
    with open(collector.directory / 'run.lock', 'a') as handle:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        collector.tick(at('2026-11-05T09:15:04'))
        assert logs(collector)[0][1] == 'SKIPPED'
    with collector.store.transaction() as conn:
        conn.execute('INSERT INTO run_log VALUES (?,?,?,?,?,?,?,?)',
                     ('interrupted', 'manual', None, timestamp(at('2026-11-05T09:16:00')), None, 'RUNNING', 'Test worker', None))
    collector.recover()
    with collector.store.connect() as conn:
        assert conn.execute("SELECT status FROM run_log WHERE run_id='interrupted'").fetchone()[0] == 'INTERRUPTED'


def test_after_close_never_launches_worker(tmp_path, monkeypatch):
    collector = collector_for(tmp_path)
    monkeypatch.setattr(collector.runner, 'start', lambda **kwargs: pytest.fail('After-close launch'))
    assert collector.tick(at('2026-11-05T15:40:00'))['status'] == 'WAITING'
    assert all(row[1] == 'MISSED' for row in logs(collector))
