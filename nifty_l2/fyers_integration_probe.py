"""Explicit read-only FYERS API integration probe; safe for existing AWS setup.

No token contents or raw account response is printed or archived. This cannot
be run by GitHub Actions: on AWS it uses the locally saved FYERS token, never
attempts login, refresh, writes, orders, or modifies the production collector.
"""
import argparse
from datetime import datetime,timedelta,timezone
import json
from pathlib import Path
import stat

from . import fyers
from .eod_fyers_adapter import normalize_ohlcv,validate_symbol
from .expiry_probe import collect_expiries
from .storage import IST

def _status(name,ok,message,**summary):
    return {"name":name,"status":"PASS" if ok else "FAIL","message":message,
            "summary":summary}

def _positive(value):
    try:return float(value)>0
    except (ValueError,TypeError,OverflowError):return False

def evaluate_live(client, *, now=None,equity_symbol="NSE:TCS-EQ",future_symbol=None):
    """Injected transport makes every API leg integration-testable offline."""
    now=now or datetime.now(timezone.utc)
    if now.tzinfo is None:raise ValueError("Current time must be timezone-aware")
    if equity_symbol:validate_symbol(equity_symbol)
    steps=[]
    request_count=0
    def call(operation,*,params=None,credentials=None):
        nonlocal request_count
        request_count+=1
        return client(operation,params=params,credentials=credentials)
    # Caller creates bound transport that handles credentials. A failed step
    # does not prevent later independent read-only endpoints being checked.
    try:
        response=call("profile")
        ok=response.get("s")=="ok"
        steps.append(_status("profile",ok,"FYERS account API authenticated" if ok else "Profile endpoint rejected"))
    except (RuntimeError,ValueError,TypeError,KeyError) as exc:
        steps.append(_status("profile",False,"Profile request failed"))
    try:
        response=call("quotes",params={"symbols":"NSE:NIFTY50-INDEX"})
        matches=[x for x in response.get("d",[]) if x.get("n")=="NSE:NIFTY50-INDEX"]
        ltp=matches[0].get("v",{}).get("lp") if len(matches)==1 else None
        steps.append(_status("index_quote",_positive(ltp),
                    "Valid NIFTY quote" if _positive(ltp) else "Missing valid NIFTY quote",
                    has_positive_price=_positive(ltp)))
    except (RuntimeError,ValueError,TypeError,KeyError):
        steps.append(_status("index_quote",False,"Index quote request failed"))
    try:
        dates=collect_expiries(None,count=2,transport=call,observed_at=now)
        legs=sum(len(e["legs"]) for e in dates["expiries"])
        populated=sum(_positive(l.get("oi")) for e in dates["expiries"] for l in e["legs"])
        gamma=sum(_positive((l.get("greeks") or {}).get("gamma")) for e in dates["expiries"] for l in e["legs"])
        ok=len(dates["expiries"])>=1 and legs>=2 and populated>=2
        steps.append(_status("actual_expiry_optionchain",ok,
                    "Actual broker expiry IDs and chain received" if ok else "Option chain incomplete",
                    expiry_count=len(dates["expiries"]),leg_count=legs,
                    legs_with_positive_oi=populated,legs_with_positive_gamma=gamma,
                    **{"gamma_input_review_required":True}))
    except (RuntimeError,ValueError,TypeError,KeyError):
        steps.append(_status("actual_expiry_optionchain",False,"Option-chain request failed"))
    start=(now.astimezone(IST).date()-timedelta(days=10)).isoformat()
    end=now.astimezone(IST).date().isoformat()
    for name,symbol,resolution in [
        ("equity_daily",equity_symbol,"D"),("equity_15m",equity_symbol,"15"),
        ("futures_3m",future_symbol,"3")]:
        if not symbol:continue
        try:
            raw=call("history",params={"symbol":symbol,"resolution":resolution,
                "date_format":"1","range_from":start,"range_to":end,
                "cont_flag":"1",**({"oi_flag":"1"} if name=="futures_3m" else {})})
            candles=raw.get("candles",[])
            # FUT: verify OHLCV+OI explicitly; do not trust a made-up derived OI.
            if name=="futures_3m":
                valid=[r for r in candles if isinstance(r,list) and len(r)>=7
                       and _positive(r[4]) and _positive(r[6])]
            else:
                valid=normalize_ohlcv(raw,resolution,now)
            required_bars=2 if name=="equity_daily" else 5
            ok=len(valid)>=required_bars
            steps.append(_status(name,ok,
                "Sufficient basic historical bars for API smoke test" if ok else
                "Too few valid completed historical bars to assess continuity",
                returned_rows=len(candles),usable_rows=len(valid),
                minimum_required=required_bars,
                futures_oi_present=bool(valid) if name=="futures_3m" else None))
        except (RuntimeError,ValueError,TypeError,KeyError,OverflowError):
            steps.append(_status(name,False,"Historical API read or candle validation failed"))
    required={"profile","index_quote","actual_expiry_optionchain"}
    if equity_symbol:required.update(("equity_daily","equity_15m"))
    if future_symbol:required.add("futures_3m")
    passed={x["name"] for x in steps if x["status"]=="PASS"}
    return {
        "status":"API_READS_PASS_DATA_QUALITY_PENDING" if required<=passed else "FAIL",
        "as_of_utc":now.astimezone(timezone.utc).isoformat(),
        "checks":steps,"api_calls":request_count,"order_calls":0,
        "secrets_in_report":False,"market_data_verified":False,
        "warning":"Read-only API connectivity is not proof of accurate historical data, timestamp provenance, gamma units or corporate-action parity."
    }

def load_token(path):
    path=Path(path).expanduser()
    mode=path.stat().st_mode
    if not stat.S_ISREG(mode) or mode & 0o077:
        raise ValueError("FYERS token must be a private regular 0600 file")
    with path.open(encoding="utf-8") as handle:credentials=json.load(handle)
    if not isinstance(credentials,dict) or not credentials.get("client_id") or not credentials.get("access_token"):
        raise ValueError("Missing saved FYERS client ID or access token")
    return credentials

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--live",action="store_true",help="Explicit opt-in to read-only FYERS requests")
    p.add_argument("--token-path",type=Path,default=fyers.TOKEN_PATH)
    p.add_argument("--equity-symbol",default="NSE:TCS-EQ")
    p.add_argument("--future-symbol",default=None)
    p.add_argument("--report",type=Path,required=True)
    args=p.parse_args(argv)
    if not args.live:p.error("Pass --live to authorize the small read-only API probe")
    if args.future_symbol and not args.future_symbol.startswith("NSE:"):
        p.error("Provide a reviewed NSE futures symbol")
    creds=load_token(args.token_path)
    last_call=[0.0]
    def transport(operation,*,params=None,credentials=None):
        # Standard FYERS quotas may be restrictive. Throttle even during a
        # one-time probe and never retry rejected market-data requests blindly.
        import time
        elapsed=time.monotonic()-last_call[0]
        if elapsed<0.35:time.sleep(0.35-elapsed)
        last_call[0]=time.monotonic()
        return fyers.request(operation,params=params,credentials=creds)
    report=evaluate_live(transport,equity_symbol=args.equity_symbol,
                         future_symbol=args.future_symbol)
    # never archive credentials or raw account/market responses
    args.report.parent.mkdir(parents=True,exist_ok=True)
    with args.report.open("x",encoding="utf-8") as f:
        json.dump(report,f,indent=2,allow_nan=False)
    args.report.chmod(0o600)
    print("FYERS probe:",report["status"])
    for step in report["checks"]:
        print(step["name"],step["status"],step["summary"])
    print("Private report:",args.report)
    return 0 if report["status"]=="API_READS_PASS_DATA_QUALITY_PENDING" else 1

if __name__=="__main__":
    raise SystemExit(main())
