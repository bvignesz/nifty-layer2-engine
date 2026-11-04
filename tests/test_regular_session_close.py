"""Regression tests for regular and special NSE research sessions."""
from datetime import date, datetime

from nifty_l2.market_calendar import IST, session, slots


def test_regular_session_ends_at_1530():
    opening, closing = session(date(2026, 11, 5))
    assert opening.strftime('%H:%M') == '09:15'
    assert closing.strftime('%H:%M') == '15:30'
    samples = slots(date(2026, 11, 5))
    assert samples[0].strftime('%H:%M') == '09:15'
    assert samples[-1].strftime('%H:%M') == '15:27'
    assert len(samples) == 125


def test_muhurat_session_keeps_exchange_override():
    opening, closing = session(date(2026, 11, 8))
    assert (opening.strftime('%H:%M'), closing.strftime('%H:%M')) == ('14:20', '15:40')
    assert all(t < closing for t in slots(date(2026, 11, 8)))
