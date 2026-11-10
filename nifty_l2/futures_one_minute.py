"""Normalize FYERS live/archived futures 1m OHLCV+OI history safely.

This validates FYERS' standard History API candle structure [ts,O,H,L,C,V,OI].
No network, no DB writes or orders. Exchange bar timestamps are bar-start.
"""
from datetime import datetime,timedelta,timezone
from math import isfinite
from .storage import IST

def normalize_completed_futures_1m(raw,*,symbol,retrieved_at):
    if not isinstance(raw,dict) or raw.get("s")!="ok":
        return {"status":"SOURCE_ERROR","rows":[],"issues":["FYERS_HISTORY_NOT_OK"]}
    if not symbol.startswith("NSE:"):
        raise ValueError("exact NSE contract symbol required")
    if not isinstance(retrieved_at,datetime) or retrieved_at.tzinfo is None:
        raise ValueError("retrieval timestamp must be aware")
    seen={}
    rows=[]
    issues=[]
    skipped=0
    for bar in raw.get("candles",[]):
        if not isinstance(bar,(list,tuple)) or len(bar)<7:
            issues.append("MISSING_OI_OR_INVALID_ROW")
            continue
        ts,o,h,l,c,v,oi=bar[:7]
        if not isinstance(ts,(int,float)) or isinstance(ts,bool) or not isfinite(ts):
            issues.append("INVALID_TIMESTAMP");continue
        ts=int(ts)
        if ts%60:issues.append("NON_MINUTE_BAR");continue
        barstart=datetime.fromtimestamp(ts,timezone.utc)
        end=barstart+timedelta(minutes=1)
        local=barstart.astimezone(IST)
        if end>retrieved_at.astimezone(timezone.utc):
            skipped+=1;continue
        if not ((local.hour==9 and local.minute>=15)
          or local.hour in (10,11,12,13,14)
          or local.hour==15 and local.minute<30):
            skipped+=1;continue
        nums=(o,h,l,c,v,oi)
        if any(not isinstance(x,(int,float)) or isinstance(x,bool)
          or not isfinite(x) for x in nums):
            issues.append("INVALID_NUMERIC_VALUE");continue
        if not (l>0 and l<=min(o,c) and max(o,c)<=h and v>=0 and oi>=0):
            issues.append("INVALID_FUTURES_BAR");continue
        value={"bar_start_utc":barstart.isoformat(),
          "bar_close_utc":end.isoformat(),"symbol":symbol,
          "ts":ts,"open":o,"high":h,"low":l,"close":c,
          "volume":v,"oi":oi,"completed":True}
        if ts in seen:
            if seen[ts]!=value:
                issues.append("CONFLICTING_DUPLICATE_BAR")
            else:
                skipped+=1
            continue
        seen[ts]=value
        rows.append(value)
    rows.sort(key=lambda x:x["ts"])
    if any(b["ts"]<=a["ts"] for a,b in zip(rows,rows[1:])):
        issues.append("TIMESTAMP_ORDER_VIOLATION")
    return {"status":"VALIDATED_1M_FUTURES" if rows and not issues else
       "DATA_QUALITY_BLOCKED" if issues else "NO_COMPLETED_BARS",
       "symbol":symbol,"rows":rows if not issues else [],
       "issues":sorted(set(issues)),"excluded_or_duplicate_rows":skipped,
       "source":"FYERS_HISTORY_1M","exchange_timestamp_semantics":"BAR_START",
       "option_oi_one_minute_verified":False,"research_only":True}

def futures_oi_quadrant(earlier,later):
    if not earlier or not later or (
         earlier.get("symbol")!=later.get("symbol") or
         later.get("ts",0)-earlier.get("ts",0)!=60):
        return "UNAVAILABLE"
    if not earlier.get("completed") or not later.get("completed"):
        return "UNAVAILABLE"
    dp=later["close"]-earlier["close"]
    oi=later["oi"]-earlier["oi"]
    if not dp or not oi:return "NEUTRAL"
    return ("LONG_BUILDUP_PROXY" if dp>0 and oi>0 else
      "SHORT_BUILDUP_PROXY" if dp<0 and oi>0 else
      "SHORT_COVERING_PROXY" if dp>0 and oi<0 else
      "LONG_LIQUIDATION_PROXY")
