"""Offline, lookahead-safe forward-label evaluator for vetted completed candles.

No writes to production database; no automatic assumption that cached FYERS
quotes or collector receipt times are exchange timestamps.
"""
from datetime import datetime, timedelta, timezone, time
from zoneinfo import ZoneInfo
from math import isfinite

IST=ZoneInfo("Asia/Kolkata")
HORIZONS=(9,15,30)

def _dt(value):
    d=value if isinstance(value,datetime) else datetime.fromisoformat(str(value).replace("Z","+00:00"))
    if d.tzinfo is None:raise ValueError("Naive time")
    return d.astimezone(timezone.utc)

def label_one(observed_at,entry_price,closed_bars,horizon_minutes,*,max_lag_seconds=180):
    """First completed bar ending on/after horizon, only if exact target close."""
    if horizon_minutes not in HORIZONS:raise ValueError("Unsupported horizon")
    start=_dt(observed_at)
    if not isinstance(entry_price,(int,float)) or not isfinite(entry_price) or entry_price<=0:
        return {"status":"UNAVAILABLE","reason":"Missing verified entry price"}
    target=start+timedelta(minutes=horizon_minutes)
    if (target.astimezone(IST).date()!=start.astimezone(IST).date()\n        or start.astimezone(IST).time()<time(9,15)\n        or target.astimezone(IST).time()>time(15,30)):
        return {"status":"CROSSES_SESSION","reason":"Target outside same session"}
    valid=[]
    for row in closed_bars:
        try:
            end=_dt(row["end_utc"])
            price=float(row["close"])
            if isfinite(price) and price>0:valid.append((end,price))
        except (KeyError,ValueError,TypeError,OverflowError):continue
    # No forward-fill or nearest quote beyond the target timestamp.
    matching=[price for end,price in valid if end==target]
    if len(matching)!=1:
        return {"status":"UNAVAILABLE","reason":"Exact completed target candle missing or duplicate"}
    return {"status":"CANDIDATE_UNVALIDATED","horizon_minutes":horizon_minutes,
            "target_at_utc":target.isoformat(),
            "forward_return":matching[0]/entry_price-1,
            "reason":"Candidate outcome; provenance and slippage review required"}

def label_horizons(observed_at,entry_price,closed_bars):
    return {str(h):label_one(observed_at,entry_price,closed_bars,h) for h in HORIZONS}
