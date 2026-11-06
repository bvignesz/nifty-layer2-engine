"""Archive completed FYERS futures candles without changing legacy valuations."""
from datetime import datetime, timedelta, timezone, time
from math import isfinite
from .storage import IST, canonical, timestamp

def latest_completed_future(calls, observed_at, max_age_seconds=900):
    observed = observed_at if isinstance(observed_at, datetime) else datetime.fromisoformat(str(observed_at).replace("Z", "+00:00"))
    if observed.tzinfo is None:
        raise ValueError("Observation time must include timezone")
    observed = observed.astimezone(timezone.utc)
    candidates = []
    for call in calls:
        if not isinstance(call, dict) or call.get("method") != "history":
            continue
        req, res = call.get("request"), call.get("response")
        if not isinstance(req, dict) or not isinstance(res, dict):
            continue
        symbol = req.get("symbol")
        if not isinstance(symbol, str) or not symbol.startswith("NSE:") or not symbol.endswith("FUT"):
            continue
        try:
            minutes = int(req.get("resolution"))
        except (ValueError, TypeError):
            continue
        if minutes not in (1, 3, 5, 15) or res.get("s") != "ok":
            continue
        for bar in res.get("candles", []):
            if not isinstance(bar, (tuple, list)) or len(bar) < 7:
                continue
            try:
                start = datetime.fromtimestamp(float(bar[0]), timezone.utc)
                close_time = start + timedelta(minutes=minutes)
                o, h, l, close, volume, oi = map(float, bar[1:7])
            except (TypeError, ValueError, OverflowError, OSError):
                continue
            if not all(isfinite(v) for v in (o, h, l, close, volume, oi)):
                continue
            if l <= 0 or not (l <= o <= h and l <= close <= h) or volume < 0 or oi <= 0:
                continue
            start_ist, end_ist = start.astimezone(IST), close_time.astimezone(IST)
            if start_ist.date() != end_ist.date() or not (time(9,15) <= start_ist.time() and end_ist.time() <= time(15,40)):
                continue
            age = (observed - close_time).total_seconds()
            if not 0 <= age <= max_age_seconds:
                continue
            candidates.append((start, symbol, close, oi, res))
    if not candidates:
        return None
    start, symbol, close, oi, response = max(candidates, key=lambda item: item[0])
    return {"start": start, "symbol": symbol, "close": close, "oi": oi, "response": response}

def persist_futures(conn, event_id, calls, observed_at):
    row = latest_completed_future(calls, observed_at)
    if row is None:
        return False
    conn.execute(
        """INSERT INTO futures_data (event_id,symbol,exchange_at_utc,close,vwap,oi,payload_json)
           VALUES (?,?,?,?,?,?,?) ON CONFLICT(event_id,symbol) DO NOTHING""",
        (event_id, row["symbol"], timestamp(row["start"]), row["close"], None, row["oi"], canonical(row["response"]))
    )
    return True
