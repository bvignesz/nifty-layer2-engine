"""One-shot FYERS DAILY candle collector for NIFTY + benchmark Quantum gate.

Uses the documented history resolution D (max 366 calendar days/request).
No orders, no intraday collector changes, no guessed benchmark ticker:
the operator supplies the EXACT verified broker symbol.
All source responses must pass schema checks. Atomic mode 0600 output.
"""
from datetime import date,datetime,timedelta,timezone
from math import isfinite
from pathlib import Path
import argparse,json,os,tempfile
from .storage import IST
from . import fyers
from .fyers_integration_probe import load_token
from .daily_alignment import evaluate_daily

def normalise_daily(responses,*,asof):
    day=date.fromisoformat(asof)
    if not isinstance(responses,list) or not responses:raise ValueError("broker history responses required")
    known={}
    for response in responses:
        if not isinstance(response,dict) or response.get("s")!="ok":
            raise ValueError("FYERS DAILY history unavailable/permission denied")
        rows=response.get("candles")
        if not isinstance(rows,list):raise ValueError("missing FYERS daily candles")
        for row in rows:
            if not isinstance(row,(list,tuple)) or len(row)<6:
                raise ValueError("invalid FYERS daily bar")
            ts,o,h,l,c,v=row[:6]
            if not isinstance(ts,(int,float)) or isinstance(ts,bool) or not isfinite(ts):
                raise ValueError("invalid daily timestamp")
            stamp=datetime.fromtimestamp(int(ts),timezone.utc).astimezone(IST).date()
            if stamp>=day:
                continue  # Exclude an in-progress/current-day candle by design.
            data={"date":stamp.isoformat(),"open":o,"high":h,
                  "low":l,"close":c,"volume":v,
                  "bar_status":"COMPLETED","source":"VERIFIED_EOD"}
            for x in (o,h,l,c,v):
                if not isinstance(x,(int,float)) or isinstance(x,bool) or not isfinite(x):
                    raise ValueError("invalid daily numerical field")
            if not (0<l<=min(o,c)<=max(o,c)<=h and v>=0):
                raise ValueError("invalid daily OHLCV")
            old=known.get(stamp)
            if old is not None and old!=data:
                raise ValueError("conflicting duplicate daily candle")
            known[stamp]=data
    return [known[d] for d in sorted(known)]

def windows(*,asof,days=520):
    day=date.fromisoformat(asof)
    if not 300<=days<=1600:raise ValueError("unsupported daily lookback")
    start=day-timedelta(days=days)
    end=day-timedelta(days=1)
    result=[]
    while start<=end:
        last=min(end,start+timedelta(days=330))
        result.append((start.isoformat(),last.isoformat()))
        start=last+timedelta(days=1)
    return result

def collect_daily(transport,*,asof,index_symbol,benchmark_symbol):
    if (not isinstance(index_symbol,str) or not isinstance(benchmark_symbol,str)
      or not index_symbol.startswith("NSE:") or not benchmark_symbol.startswith("NSE:")
      or index_symbol==benchmark_symbol):
        raise ValueError("two distinct reviewed NSE index symbols required")
    source={}
    for role,symbol in (("index_bars",index_symbol),("benchmark_bars",benchmark_symbol)):
        responses=[]
        for start,end in windows(asof=asof):
            response=transport("history",params={"symbol":symbol,"resolution":"D",
                 "date_format":"1","range_from":start,"range_to":end,
                 "cont_flag":"1"})
            responses.append(response)
        source[role]=normalise_daily(responses,asof=asof)
        if len(source[role])<221:
            raise ValueError("at least 221 completed daily records required for "+role)
    decision=evaluate_daily(source["index_bars"],source["benchmark_bars"],asof=asof)
    return {**source,"date_ist":asof,"symbols":{
          "index":index_symbol,"benchmark":benchmark_symbol},
          "verified_daily_context":decision,"research_only":True,
          "orders_enabled":False,"provenance_note":
          "FYERS authenticated historical D bars; operator must review index symbol and timestamp mapping."}

def save_daily(path,payload):
    path=Path(path).expanduser().resolve()
    if path.name!="daily-context.json":raise ValueError("daily-context.json destination required")
    path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    fd,tmp=tempfile.mkstemp(prefix=".daily-",dir=path.parent)
    try:
        with os.fdopen(fd,"w",encoding="utf-8") as handle:
            json.dump(payload,handle,allow_nan=False)
            handle.flush();os.fsync(handle.fileno())
        os.chmod(tmp,0o600)
        os.replace(tmp,path)
    finally:
        Path(tmp).unlink(missing_ok=True)

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--live",action="store_true")
    p.add_argument("--index-symbol",default="NSE:NIFTY50-INDEX")
    p.add_argument("--benchmark-symbol",required=True,
        help="Exact broker-confirmed index ticker, e.g. verified NIFTY500 symbol")
    p.add_argument("--asof",default=datetime.now(IST).date().isoformat())
    p.add_argument("--token-path",type=Path,default=fyers.TOKEN_PATH)
    p.add_argument("--output",type=Path,required=True)
    args=p.parse_args(argv)
    if not args.live:p.error("Explicit --live is required")
    creds=load_token(args.token_path)
    def transport(operation,*,params):
        return fyers.request(operation,params=params,credentials=creds)
    result=collect_daily(transport,asof=args.asof,index_symbol=args.index_symbol,
                         benchmark_symbol=args.benchmark_symbol)
    save_daily(args.output,result)
    print(json.dumps({"status":"VERIFIED_COMPLETED_DAILY_CONTEXT",
       "latest_date":result["verified_daily_context"]["last_completed_session"],
       "index_rows":len(result["index_bars"]),
       "benchmark_rows":len(result["benchmark_bars"]),
       "bias":result["verified_daily_context"]["bias"],
       "orders_enabled":False}))
    return 0

if __name__=="__main__":
    raise SystemExit(main())
