"""Dated NSE F&O session policy; unknown dates fail closed.

Sources checked 2026-11-04:
https://www.nseindia.com/static/market-data/market-timings
https://nsearchives.nseindia.com/content/circulars/FAOP71777.pdf
https://nsearchives.nseindia.com/content/circulars/FAOP76940.pdf
This calendar must be updated for new years or unscheduled exchange notices.
"""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

IST = ZoneInfo('Asia/Kolkata')
VALID_FROM = '2026-11-04'
VALID_UNTIL = '2026-12-31'
HOLIDAYS = {'2026-11-10', '2026-11-24', '2026-12-25'}
SPECIAL = {'2026-11-08': ('14:20', '15:40')}
INTERVAL = timedelta(minutes=3)


def session(day):
    key = day.isoformat()
    if not VALID_FROM <= key <= VALID_UNTIL:
        raise ValueError('Exchange calendar needs an update before automation can run')
    if key in SPECIAL:
        opening, closing = SPECIAL[key]
    elif day.weekday() >= 5 or key in HOLIDAYS:
        return None
    else:
        opening, closing = '09:15', '15:40'
    return tuple(datetime.fromisoformat(key + 'T' + t).replace(tzinfo=IST)
                 for t in (opening, closing))


def slots(day):
    hours = session(day)
    if hours is None:
        return []
    opening, closing = hours
    # The first observation is a warmup snapshot at open. Subsequent snapshots
    # are anchored to the session, not to process startup or worker duration.
    result = []
    slot = opening
    while slot < closing:
        result.append(slot)
        slot += INTERVAL
    return result


def next_slot(now):
    local = now.astimezone(IST)
    for offset in range(370):
        day = local.date() + timedelta(days=offset)
        if day.isoformat() > VALID_UNTIL:
            return None
        for slot in slots(day):
            if slot > local:
                return slot
    return None
