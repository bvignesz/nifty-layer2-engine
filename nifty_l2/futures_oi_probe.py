"""Read-only FYERS futures OI integration and timestamp-continuity test.

One read-only history request. This validates the broker's live account data
format, not actual dealer positioning, option exchange timestamps, or P&L.
"""
import argparse
from collections import Counter
from datetime import datetime, timedelta, timezone, time
import json
from math import isfinite
from pathlib import Path
from zoneinfo import ZoneInfo
from . import fyers
from .fyers_integration_probe import load_token

IST = ZoneInfo("Asia/Kolkata")

def summarize_futures(response, *, asof, resolution_minutes=3):
    if asof.tzinfo is None:
        raise ValueError("asof must be timezone-aware")
    result = {"status":"FAIL","raw_rows":0,"completed_rows":0,"unique_completed_bars":0,
              "positive_oi_bars":0,"missing_oi_bars":0,"invalid_ohlcv_bars":0,
              "unfinished_rows":0,"after_session_rows":0,"non_3min_spacing":0,
              "duplicate_timestamps":0,"latest_bar_start_utc":None,
              "oldest_bar_start_utc":None,"option_exchange_time_verified":False,
              "note":"Exchange history timestamp is candle START, not a chain update time."}
    if not isinstance(response,dict) or response.get("s")!="ok":
        result["error"]="FYERS returned an unsuccessful history response"
        return result
    bars=response.get("candles")
    if not isinstance(bars,list):
        result["error"]="FYERS candles not a list"
        return result
    result["raw_rows"]=len(bars)
    valid={}
    duplicates=0
    for bar in bars:
        if not isinstance(bar,(list,tuple)) or len(bar)<6:
            result["invalid_ohlcv_bars"]+=1
            continue
        try:
            start=datetime.fromtimestamp(float(bar[0]),timezone.utc)
            close=start+timedelta(minutes=resolution_minutes)
            o,h,l,c,v=map(float,bar[1:6])
            if not all(isfinite(x) for x in (o,h,l,c,v)) or l<=0 or not (l<=o<=h and l<=c<=h) or v<0:
                raise ValueError("invalid OHLCV")
        except (TypeError,ValueError,OverflowError,OSError):
            result["invalid_ohlcv_bars"]+=1
            continue
        start_local,close_local=start.astimezone(IST),close.astimezone(IST)
        if start_local.date()!=close_local.date() or not (
            time(9,15)<=start_local.time() and close_local.time()<=time(15,40)):
            result["after_session_rows"]+=1
            continue
        if close>asof.astimezone(timezone.utc):
            result["unfinished_rows"]+=1
            continue
        result["completed_rows"]+=1
        oi=None
        if len(bar)>6:
            try:
                candidate=float(bar[6])
                if isfinite(candidate) and candidate>0:oi=candidate
            except (TypeError,ValueError,OverflowError):
                pass
        if start in valid:
            duplicates+=1
            if oi is not None and valid[start] is None:
                valid[start]=oi
        else:
            valid[start]=oi
        if oi is None:result["missing_oi_bars"]+=1
        else:result["positive_oi_bars"]+=1
    keys=sorted(valid)
    result["unique_completed_bars"]=len(keys)
    result["duplicate_timestamps"]=duplicates
    result["oldest_bar_start_utc"]=keys[0].isoformat() if keys else None
    result["latest_bar_start_utc"]=keys[-1].isoformat() if keys else None
    for old,new in zip(keys,keys[1:]):
        secs=(new-old).total_seconds()
        # Overnight/session gaps are expected; only compare same IST day.
        if old.astimezone(IST).date()==new.astimezone(IST).date() and secs != resolution_minutes*60:
            result["non_3min_spacing"]+=1
    enough=len(keys)>=5 and sum(v is not None for v in valid.values())>=5
    result["status"]="FUTURES_HISTORY_OI_PRESENT_UNVERIFIED" if enough else "FAIL"
    result["source"]="FYERS_HISTORY_READ_ONLY"
    return result

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--live",action="store_true",help="Explicitly opt in to one broker read")
    p.add_argument("--future-symbol",required=True,help="Verified active NSE futures symbol")
    p.add_argument("--token-path",type=Path,default=fyers.TOKEN_PATH)
    p.add_argument("--report",type=Path,required=True)
    args=p.parse_args(argv)
    if not args.live:p.error("Use --live to authorize one read-only FYERS request")
    if not args.future_symbol.startswith("NSE:") or not args.future_symbol.endswith("FUT"):
        p.error("Provide exact NSE futures contract identifier")
    credentials=load_token(args.token_path)
    now=datetime.now(timezone.utc)
    local=now.astimezone(IST)
    params={"symbol":args.future_symbol,"resolution":"3","date_format":"1",
            "range_from":(local.date()-timedelta(days=7)).isoformat(),
            "range_to":local.date().isoformat(),
            "cont_flag":"1","oi_flag":"1"}
    raw=fyers.request("history",params=params,credentials=credentials)
    report=summarize_futures(raw,asof=now)
    report["symbol"]=args.future_symbol
    args.report.parent.mkdir(parents=True,exist_ok=True)
    with args.report.open("x",encoding="utf-8") as f:
        json.dump(report,f,indent=2,allow_nan=False)
    args.report.chmod(0o600)
    print(json.dumps(report,indent=2,allow_nan=False))
    return 0 if report["status"]=="FUTURES_HISTORY_OI_PRESENT_UNVERIFIED" else 2

if __name__=="__main__":
    raise SystemExit(main())
