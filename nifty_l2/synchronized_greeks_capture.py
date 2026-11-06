"""Read-only futures-bracketed option Greeks research capture; no orders."""
from datetime import datetime,timezone
import json,os
from pathlib import Path
from . import fyers
from .fyers_integration_probe import load_token
from .gamma_model_parity import compare_legs, parse_time

def capture(creds, future_symbol, *, transport=None, clock=None, expiry_at=None):
    if not future_symbol.startswith("NSE:") or not future_symbol.endswith("FUT"):
        raise ValueError("Reviewed futures symbol required")
    call=transport or fyers.request
    now=clock or (lambda:datetime.now(timezone.utc))
    def read(op,params):
        t1=parse_time(now())
        data=call(op,params=params,credentials=creds)
        t2=parse_time(now())
        if (t2-t1).total_seconds()>30 or t2<t1:raise ValueError("Bad request timing")
        if not isinstance(data,dict) or data.get("s")!="ok":
            raise ValueError("Unsuccessful market-data response")
        return data,t1,t2
    first,_,_=read("optionchain",{"symbol":"NSE:NIFTY50-INDEX","strikecount":1,"timestamp":""})
    dates=first.get("data",{}).get("expiryData",[])
    if not dates or not dates[0].get("expiry"):raise ValueError("No expiry")
    expiry=dates[0]["expiry"]
    def price(data):
        rows=[r for r in data.get("d",[]) if r.get("n")==future_symbol]
        if len(rows)!=1:raise ValueError("Missing exact futures quote")
        v=float(rows[0].get("v",{}).get("lp",0))
        if not 0<v<1000000:raise ValueError("Invalid futures price")
        return v
    a,start,aend=read("quotes",{"symbols":future_symbol})
    chain,cstart,cend=read("optionchain",{"symbol":"NSE:NIFTY50-INDEX",
        "strikecount":10,"timestamp":str(expiry),"greeks":"1"})
    b,bstart,end=read("quotes",{"symbols":future_symbol})
    pa,pb=price(a),price(b)
    legs=[{"symbol":r.get("symbol"),"strike_price":r.get("strike_price"),
           "option_type":r.get("option_type"),"oi":r.get("oi"),
           "bid":r.get("bid"),"ask":r.get("ask"),"ltp":r.get("ltp"),
           "lot_size":None,"lot_size_source":None,"lot_size_verified":False,
           "greeks":{k:(r.get("greeks") or {}).get(k) for k in ("gamma","iv","delta")}}
          for r in chain.get("data",{}).get("optionsChain",[])
          if isinstance(r,dict) and r.get("option_type") in ("CE","PE")]
    if not legs or chain.get("s")!="ok":raise ValueError("Missing option Greek legs")
    drift=abs(pb-pa)/pa*100
    span=(end-start).total_seconds()
    if not start<=aend<=cstart<=cend<=bstart<=end:
        raise ValueError("Non-monotonic capture timing")
    missing=[]
    for index,leg in enumerate(legs):
        fields=[key for key in ("symbol","strike_price","oi","bid","ask","ltp","lot_size")
                if leg.get(key) is None]
        fields += ["greeks."+key for key in ("gamma","iv","delta")
                   if leg["greeks"].get(key) is None]
        if fields:missing.append({"leg_index":index,"fields":fields})
    status="RECEIPT_BRACKET_UNVERIFIED" if span<=30 and drift<=.1 else "UNSTABLE_QUOTE_BRACKET"
    result={"schema_version":2,"gex_label":"SIGNED-OI GEX SCENARIO — UNVERIFIED",
       "research_only":True,"trade_eligible":False,
       "status":status,"expiry_id":str(expiry),"expiry_date":dates[0].get("date"),
       "future_symbol":future_symbol,"future_quote_before":pa,"future_quote_after":pb,
       "price_drift_pct":drift,"window_start":start.isoformat(),"window_end":end.isoformat(),
       "chain_requested_at":cstart.isoformat(),"chain_received_at":cend.isoformat(),
       "future_quotes":[
           {"requested_at":start.isoformat(),"received_at":aend.isoformat(),
            "latency_seconds":(aend-start).total_seconds(),"symbol":future_symbol,
            "source":"FYERS_QUOTES","quote":next(r["v"] for r in a["d"] if r.get("n")==future_symbol)},
           {"requested_at":bstart.isoformat(),"received_at":end.isoformat(),
            "latency_seconds":(end-bstart).total_seconds(),"symbol":future_symbol,
            "source":"FYERS_QUOTES","quote":next(r["v"] for r in b["d"] if r.get("n")==future_symbol)}],
       "chain_latency_seconds":(cend-cstart).total_seconds(),
       "missing_fields":missing,"stale_data_status":"UNKNOWN_EXCHANGE_TIMESTAMPS_UNVERIFIED",
       "coverage_complete":False,"coverage_scope":"REQUESTED_STRIKE_WINDOW",
       "lot_sizes_verified":False,"legs":legs,"exchange_oi_timestamp_verified":False,"oi_units_verified":False,
       "dealer_positions_observed":False,"gamma_independently_validated":False}
    if expiry_at and status=="RECEIPT_BRACKET_UNVERIFIED":
        result["gamma_model"]=compare_legs(legs,asof=cend,expiry_at=expiry_at,
                                           forward=(pa+pb)/2)
        result["gamma_model"]["forward_and_expiry_are_unverified_assumptions"]=True
    return result

def reserve_report(path):
    """Reserve the actual output inode before credentials or broker access.

    Exclusive creation rejects existing files and symlinks atomically. Keep
    failed/partial evidence; a retry must use a new filename.
    """
    p=Path(path).expanduser()
    p.parent.mkdir(parents=True,exist_ok=True)
    fd=os.open(p,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    return os.fdopen(fd,"w",encoding="utf-8")

def write_report(handle,result):
    # Serialize before writing so invalid values cannot leave half-written JSON.
    payload=json.dumps(result,indent=2,allow_nan=False)
    handle.write(payload+"\n")
    handle.flush()
    os.fsync(handle.fileno())

def save_new(path,result):
    with reserve_report(path) as handle:
        write_report(handle,result)

def main(argv=None):
    import argparse
    p=argparse.ArgumentParser()
    p.add_argument("--live",action="store_true")
    p.add_argument("--future-symbol",required=True)
    p.add_argument("--token-path",type=Path,required=True)
    p.add_argument("--report",type=Path,required=True)
    p.add_argument("--assumed-expiry-at")
    a=p.parse_args(argv)
    if not a.live:p.error("Explicit --live required")
    if a.assumed_expiry_at:
        parse_time(a.assumed_expiry_at)
    try:
        handle=reserve_report(a.report)
    except FileExistsError:
        p.error("Report already exists; preserved. Choose a new --report filename.")
    except OSError:
        p.error("Cannot reserve report; check parent directory and permissions before retrying.")
    with handle:
        try:
            d=capture(load_token(a.token_path),a.future_symbol,expiry_at=a.assumed_expiry_at)
            write_report(handle,d)
        except Exception:
            if handle.tell()==0:
                write_report(handle,{"status":"CAPTURE_FAILED","research_only":True,
                    "trade_eligible":False,"reason":"Capture failed; retry with a new report filename."})
            # Broker exceptions may include credentials. Do not echo their text.
            p.exit(1,"Capture failed; report preserved. Check inputs/authentication and use a new --report filename.\n")
    print(json.dumps({"status":d["status"],"legs":len(d["legs"]),
      "price_drift_pct":d["price_drift_pct"],"expiry_id":d["expiry_id"],
      "exchange_oi_timestamp_verified":False,"oi_units_verified":False},indent=2))
if __name__=="__main__":main()
