"""FYERS EOD OHLCV adapter. No strategy changes or automatic broker requests.

Supply exchange-verified instrument IDs from an authoritative symbol master.
Normalized frames are suitable for a later preserved two-track scanner integration.
"""
from datetime import datetime, timedelta, timezone
from math import isfinite
from zoneinfo import ZoneInfo
IST=ZoneInfo("Asia/Kolkata")

def validate_symbol(symbol):
    if not isinstance(symbol,str) or not symbol.startswith("NSE:"):
        raise ValueError("Explicit FYERS NSE symbol required; never guess tickers")
    if not (symbol.endswith("-EQ") or symbol.endswith("-INDEX")):
        raise ValueError("Only verified NSE equity/index symbols supported")
    if len(symbol)>80 or any(c in symbol for c in "\\n\\r\\t ,;"):
        raise ValueError("Malformed symbol")
    return symbol

def normalize_ohlcv(response,resolution,asof):
    """Converts existing FYERS history shape to closed, ordered candle records."""
    if resolution not in ("D","15"):raise ValueError("D or 15 only")
    if not isinstance(response,dict) or response.get("s")!="ok":
        raise ValueError("FYERS history response unavailable")
    seen=set()
    out=[]
    asof=asof if isinstance(asof,datetime) else datetime.fromisoformat(asof.replace("Z","+00:00"))
    if asof.tzinfo is None:raise ValueError("asof timezone required")
    for candle in response.get("candles",[]):
        if not isinstance(candle,(list,tuple)) or len(candle)<6:continue
        try:
            ts=int(candle[0])
            o,h,l,c,v=map(float,candle[1:6])
            start=datetime.fromtimestamp(ts,timezone.utc)
        except (TypeError,ValueError,OverflowError,OSError):continue
        if ts in seen or not all(isfinite(x) for x in (o,h,l,c,v)):continue
        if l<=0 or h<l or not(l<=o<=h and l<=c<=h) or v<0:continue
        local=start.astimezone(IST)
        if resolution=="15":
            closed=start+timedelta(minutes=15)
            if not (9<=local.hour<=15) or closed>asof:continue
        else:
            # Do not include a current daily bar before EOD finalization.
            closed=local.replace(hour=15,minute=45,second=0,microsecond=0)
            if closed>asof.astimezone(IST):continue
        seen.add(ts)
        out.append({"start_utc":start.isoformat(),"day_ist":local.date().isoformat(),
                    "open":o,"high":h,"low":l,"close":c,"volume":v})
    return sorted(out,key=lambda x:x["start_utc"])

def read_history(symbol,resolution,day_from,day_to,credentials,transport):
    """Read-only; transport injection allows offline tests without FYERS login."""
    validate_symbol(symbol)
    if resolution not in ("D","15"):raise ValueError("Invalid resolution")
    from datetime import date
    if date.fromisoformat(day_from)>date.fromisoformat(day_to):
        raise ValueError("Invalid date range")
    if not credentials:raise ValueError("FYERS credential required")
    params={"symbol":symbol,"resolution":resolution,"date_format":"1",
            "range_from":day_from,"range_to":day_to,"cont_flag":"1"}
    return transport("history",params=params,credentials=credentials)
