"""One-contract FYERS expired-options historical research probe.

Read-only. Uses documented FYERS v3 SDK fno_historical_data, *not* a guessed
endpoint. One broker call, no retries. Raw saved only as a private, create-only
JSON report; no production DB writes, no trading endpoints.
"""
import argparse
from datetime import date,datetime,timedelta,timezone
import json
import math
import os
from pathlib import Path
import stat
from zoneinfo import ZoneInfo

IST=ZoneInfo("Asia/Kolkata")
CORE=("timestamp","open","high","low","close","volume")
GREEKS=("iv","delta","gamma","theta","vega")

def _finite(value,*,positive=False):
    if isinstance(value,bool) or not isinstance(value,(int,float)):
        return False
    return math.isfinite(value) and (value>0 if positive else value>=0)

def analyze_response(response,*,symbol,date_from,date_to,retrieved_at=None):
    """Fail closed for mismatched or corrupt bars; preserve explicit null Greeks."""
    retrieved_at=retrieved_at or datetime.now(timezone.utc)
    if retrieved_at.tzinfo is None:raise ValueError("aware retrieval timestamp required")
    date_from=date.fromisoformat(date_from)
    date_to=date.fromisoformat(date_to)
    if date_to<date_from or (date_to-date_from).days>100:
        raise ValueError("invalid 100-day data window")
    result={"status":"SCHEMA_CHANGED","symbol":symbol,"schema_version":None,
            "returned_bars":0,"accepted_bars":0,"bars":[],"greeks_coverage":{},
            "issues":[],"requested_range":[date_from.isoformat(),date_to.isoformat()],
            "retrieved_at_utc":retrieved_at.astimezone(timezone.utc).isoformat(),
            "research_only":True,"orders_enabled":False}
    if not isinstance(response,dict):
        result["issues"].append("RESPONSE_NOT_OBJECT")
        return result
    result["schema_version"]=response.get("schema_version")
    if response.get("s")=="no_data":
        result["status"]="NO_DATA"
        return result
    if response.get("s")!="ok":
        result["status"]="ERROR"
        result["issues"].append("FYERS_ERROR_CODE_"+str(response.get("code","UNKNOWN")))
        return result
    if response.get("symbol")!=symbol or response.get("resolution")!="1":
        result["issues"].append("CONTRACT_OR_RESOLUTION_MISMATCH")
        return result
    cols=response.get("columns")
    rows=response.get("candles")
    if not isinstance(cols,list) or any(not isinstance(c,str) for c in cols) or len(set(cols))!=len(cols) or not isinstance(rows,list):
        result["issues"].append("INVALID_COLUMNS_OR_ROWS")
        return result
    # First six are stable according to FYERS official documentation.
    if tuple(cols[:6])!=CORE:
        result["issues"].append("CORE_COLUMN_MISMATCH")
        return result
    if "open_interest" not in cols or "gamma" not in cols or not (
       "iv" in cols or "implied_volatility" in cols):
        result["issues"].append("REQUIRED_OI_GREEKS_MISSING")
        return result
    if not isinstance(result["schema_version"],int) or result["schema_version"]<1:
        result["issues"].append("INVALID_SCHEMA_VERSION")
        return result
    if not rows:
        result["status"]="NO_DATA"
        return result
    result["returned_bars"]=len(rows)
    names={c:i for i,c in enumerate(cols)}
    prev=None
    null_counts={k:0 for k in GREEKS}
    for raw in rows:
        if not isinstance(raw,list) or len(raw)!=len(cols):
            result["issues"].append("ROW_LENGTH_INVALID")
            break
        item=dict(zip(cols,raw))
        t=item["timestamp"]
        if isinstance(t,bool) or not isinstance(t,(int,float)) or not math.isfinite(t):
            result["issues"].append("INVALID_BAR_TIMESTAMP")
            break
        t=int(t)
        now=int(retrieved_at.timestamp())
        bar_utc=datetime.fromtimestamp(t,timezone.utc)
        local=bar_utc.astimezone(IST)
        if prev is not None and t<=prev:
            result["issues"].append("DUPLICATE_OR_NONMONOTONIC_BARS")
            break
        if not date_from<=local.date()<=date_to or t+60>now:
            result["issues"].append("OUT_OF_RANGE_OR_INCOMPLETE_BAR")
            break
        if not (local.hour==9 and local.minute>=15 or 10<=local.hour<=14
                or local.hour==15 and local.minute<30):
            result["issues"].append("OUTSIDE_REGULAR_SESSION")
            break
        if t%60:
            result["issues"].append("NON_MINUTE_BOUNDARY")
            break
        prices=[item[k] for k in ("open","high","low","close")]
        volume=item["volume"]
        if not all(_finite(p,positive=True) for p in prices) or not _finite(volume):
            result["issues"].append("INVALID_OHLCV")
            break
        if not item["low"]<=min(item["open"],item["close"])<=max(item["open"],item["close"])<=item["high"]:
            result["issues"].append("BAD_OHLC_RELATION")
            break
        if item["open_interest"] is not None and not _finite(item["open_interest"]):
            result["issues"].append("BAD_OPEN_INTEREST")
            break
        values={}
        for name in GREEKS:
            v=item.get(name,item.get("implied_volatility") if name=="iv" else None)
            if v is None:null_counts[name]+=1
            elif not isinstance(v,(int,float)) or isinstance(v,bool) or not math.isfinite(v):
                result["issues"].append("INVALID_GREEK_"+name)
                break
            values[name]=v
        if result["issues"]:break
        if values.get("iv") is not None and not 0<values["iv"]<1000:
            result["issues"].append("IMPLIED_VOL_UNIT_OUT_OF_RANGE")
            break
        result["bars"].append({"ts":t,"open":item["open"],"high":item["high"],
            "low":item["low"],"close":item["close"],"volume":volume,
            "oi":item["open_interest"],"greeks":values})
        prev=t
    result["accepted_bars"]=len(result["bars"])
    result["greeks_coverage"]={k:{"present":len(result["bars"])-v,
         "missing":v} for k,v in null_counts.items()}
    result["status"]="PASS_DATA_AVAILABLE" if not result["issues"] else "INVALID_DATA"
    if result["status"]=="PASS_DATA_AVAILABLE":
        result["warnings"]=["OI_UNITS_NOT_INDEPENDENTLY_CONFIRMED","OPTIONS_BID_ASK_NOT_IN_HISTORICAL_CANDLES",
                            "NO_PROFITABILITY_CLAIM"]
    return result

def save_report(path,result):
    path=Path(path).expanduser()
    path.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
    fd=os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    with os.fdopen(fd,"w",encoding="utf-8") as f:
        json.dump(result,f,indent=2,allow_nan=False)
        f.flush()
        os.fsync(f.fileno())

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--live",action="store_true")
    p.add_argument("--symbol",required=True,help="Exact expired NIFTY CE or PE from FYERS expired-contract discovery")
    p.add_argument("--from-date",required=True)
    p.add_argument("--to-date",required=True)
    p.add_argument("--token-path",type=Path,required=True)
    p.add_argument("--report",type=Path,required=True)
    args=p.parse_args(argv)
    if not args.live:p.error("--live required for FYERS read")
    if not args.symbol.startswith("NSE:NIFTY") or not args.symbol.endswith(("CE","PE")):
        p.error("Provide exact expired NSE:NIFTY option contract")
    start,end=date.fromisoformat(args.from_date),date.fromisoformat(args.to_date)
    if end<start or (end-start).days>100 or end>=datetime.now(IST).date():
        p.error("Use past dates within one 100-day window")
    if args.report.expanduser().exists():p.error("Report already exists; use a new filename")
    token=args.token_path.expanduser()
    if not stat.S_ISREG(token.stat().st_mode) or token.stat().st_mode&0o077:
        p.error("Token file must be private (0600)")
    credentials=json.loads(token.read_text())
    if not credentials.get("client_id") or not credentials.get("access_token"):
        p.error("FYERS saved credentials incomplete")
    try:
        from fyers_apiv3 import fyersModel
    except ImportError:
        p.error("Install fyers-apiv3 in this venv before running")
    client=fyersModel.FyersModel(client_id=credentials["client_id"],
        token=credentials["access_token"],is_async=False,log_path="")
    request={"symbol":args.symbol,"resolution":"1","date_format":"1",
        "range_from":args.from_date,"range_to":args.to_date,
        "include_oi":"1","include_greeks":"1"}
    # No login/OAuth or order calls. One market-data request.
    response=client.fno_historical_data(request)
    result=analyze_response(response,symbol=args.symbol,
        date_from=args.from_date,date_to=args.to_date)
    # Do not persist raw broker response; normalized private research evidence only.
    save_report(args.report,result)
    print("FYERS expired option history:",result["status"])
    print("Rows:",result["accepted_bars"],"/",result["returned_bars"])
    print("Report:",args.report)
    return 0 if result["status"] in ("PASS_DATA_AVAILABLE","NO_DATA") else 2

if __name__=="__main__":
    raise SystemExit(main())
