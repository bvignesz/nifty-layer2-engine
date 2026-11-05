"""Independent research checks; NEVER injected into the preserved legacy engine."""
from datetime import datetime, timedelta, timezone
from math import isfinite
from zoneinfo import ZoneInfo

IST=ZoneInfo("Asia/Kolkata")

def _finite_positive(value):
    try:
        v=float(value)
        return isfinite(v) and v>0
    except (TypeError,ValueError,OverflowError):
        return False

def gamma_scenario(*,future_price,call_gamma,put_gamma,call_oi,put_oi,oi_unit="underlying_units"):
    """Signed OI gamma scenario in ₹Cr / 1% move. NOT actual dealer exposure."""
    if oi_unit!="underlying_units":
        raise ValueError("Explicit underlying-equivalent OI quantity required")
    values=(future_price,call_gamma,put_gamma,call_oi,put_oi)
    if not all(_finite_positive(x) for x in values):
        return {"status":"UNAVAILABLE","reason":"Missing, nonpositive or invalid GEX inputs"}
    f,cg,pg,co,po=map(float,values)
    ce=.01*f*f*cg*co/1e7
    pe=-.01*f*f*pg*po/1e7
    return {"status":"SCENARIO_ESTIMATE","ce_gex_cr":ce,"pe_gex_cr":pe,
            "net_gex_cr":ce+pe,"unit":"INR crore per 1% underlying move",
            "assumption":"Calls positive; puts negative; OI signed by scenario only",
            "dealer_inventory_observed":False}

def completed_candle(timestamp,observed_at,minutes,*,max_delay_seconds=180):
    """Return state only for a bar whose exchange-start epoch and closure are known."""
    if minutes not in (1,3,5,15):
        raise ValueError("Unsupported candle timeframe")
    try:
        start=datetime.fromtimestamp(float(timestamp),timezone.utc)
        received=observed_at if isinstance(observed_at,datetime) else datetime.fromisoformat(observed_at.replace("Z","+00:00"))
        if received.tzinfo is None:raise ValueError("Timestamp must be timezone aware")
        close=start+timedelta(minutes=minutes)
        lag=(received.astimezone(timezone.utc)-close).total_seconds()
        if lag<0:return {"status":"INCOMPLETE","closed_at_utc":close.isoformat()}
        if lag>max_delay_seconds:return {"status":"STALE","closed_at_utc":close.isoformat()}
        if close.astimezone(IST).date()!=start.astimezone(IST).date():
            return {"status":"OUTSIDE_SESSION","closed_at_utc":close.isoformat()}
        return {"status":"COMPLETED","closed_at_utc":close.isoformat()}
    except (ValueError,OverflowError,OSError,TypeError):
        return {"status":"UNAVAILABLE","closed_at_utc":None}

def validate_snapshot_sequence(previous,current,max_gap_seconds=360):
    """Validate two UTC exchange timestamps, not merely receipt timestamps."""
    try:
        a=datetime.fromisoformat(previous.replace("Z","+00:00"))
        b=datetime.fromisoformat(current.replace("Z","+00:00"))
        if a.tzinfo is None or b.tzinfo is None:return "UNVERIFIED"
        difference=(b-a).total_seconds()
        if difference<=0:return "NON_MONOTONIC"
        if difference>max_gap_seconds:return "GAP"
        if a.astimezone(IST).date()!=b.astimezone(IST).date():return "CROSS_SESSION"
        return "COMPARABLE"
    except (ValueError,AttributeError,TypeError):
        return "UNVERIFIED"
