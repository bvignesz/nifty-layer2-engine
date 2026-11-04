from datetime import datetime
from nifty_l2.fyers_parsing import completed_futures


def epoch(local):
    return int(datetime.fromisoformat('2026-11-03T' + local + '+05:30').timestamp())


def test_completed_only_and_sorted():
    a = [epoch('09:15:00'), 24000, 24010, 23990, 24005, 100, 500]
    b = [epoch('09:18:00'), 24005, 24020, 24000, 24015, 120, 520]
    result = completed_futures([b, a], now='2026-11-03T09:18:00+05:30')
    assert result['status'] == 'VALID'
    assert len(result['bars']) == 1
    assert result['rejected'][0]['reason'] == 'INCOMPLETE_OR_FUTURE'


def test_stale_missing_oi_nan_and_wrong_grid():
    a = [epoch('09:15:00'), 24000, 24010, 23990, 24005, 100, 500]
    assert completed_futures([a], now='2026-11-03T09:30:00+05:30')['status'] == 'STALE'
    for row in (a[:6], [epoch('09:16:00')] + a[1:], a[:4] + [float('nan')] + a[5:]):
        assert completed_futures([row], now='2026-11-03T09:18:00+05:30')['status'] == 'UNAVAILABLE'


def test_duplicate_conflict_fails_closed():
    a = [epoch('09:15:00'), 24000, 24010, 23990, 24005, 100, 500]
    b = a.copy(); b[4] = 24006
    assert completed_futures([a, b], now='2026-11-03T09:18:00+05:30')['status'] == 'UNAVAILABLE'
