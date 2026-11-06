"""Read-only futures-bracketed option Greeks research capture; no orders."""
from datetime import datetime,timezone
import json,os
from pathlib import Path
from . import fyers
from .fyers_integration_probe import load_token
from .gamma_model_parity import compare_legs

def capture(creds, future_symbol, *, transport=None, clock=None, expiry_at=None):
    if not future_symbol.startswith("NSE:") or not future_symbol.endswith("FUT"):
        raise ValueError("Reviewed futures symbol required")
    call=transport or fyers.request
    now=clock or (lambda:datetime.now(timezone.utc))
    def read(op,params):
        t1=now()
        data=call(op,params=params,credentials=creds)
        t2=now()
        if (t2-t1).total_seconds()>30 or t2<t1:raise ValueError("Bad request timing")
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
    a,start,_=read("quotes",{"symbols":future_symbol})
    chain,cstart,cend=read("optionchain",{"symbol":"NSE:NIFTY50-INDEX",
        "strikecount":10,"timestamp":str(expiry),"greeks":"1"})
    b,_,end=read("quotes",{"symbols":future_symbol})
    pa,pb=price(a),price(b)
    legs=[{"symbol":r.get("symbol"),"strike_price":r.get("strike_price"),
           "option_type":r.get("option_type"),"oi":r.get("oi"),
           "greeks":{k:(r.get("greeks") or {}).get(k) for k in ("gamma","iv","delta")}}
          for r in chain.get("data",{}).get("optionsChain",[])
          if isinstance(r,dict) and r.get("option_type") in ("CE","PE")]
    if not legs or chain.get("s")!="ok":raise ValueError("Missing option Greek legs")
    drift=abs(pb-pa)/pa*100
    span=(end-start).total_seconds()
    status="RECEIPT_BRACKET_UNVERIFIED" if span<=30 and drift<=.1 else "UNSTABLE_QUOTE_BRACKET"
    result={"status":status,"expiry_id":str(expiry),"expiry_date":dates[0].get("date"),
       "future_symbol":future_symbol,"future_quote_before":pa,"future_quote_after":pb,
       "price_drift_pct":drift,"window_start":start.isoformat(),"window_end":end.isoformat(),
       "chain_requested_at":cstart.isoformat(),"chain_received_at":cend.isoformat(),
       "legs":legs,"exchange_oi_timestamp_verified":False,"oi_units_verified":False,
       "dealer_positions_observed":False,"gamma_independently_validated":False}
    if expiry_at and status=="RECEIPT_BRACKET_UNVERIFIED":
        result["gamma_model"]=compare_legs(legs,asof=cend,expiry_at=expiry_at,
                                           forward=(pa+pb)/2)
        result["gamma_model"]["forward_and_expiry_are_unverified_assumptions"]=True
    return result

def save_new(path,result):
    p=Path(path)
    p.parent.mkdir(parents=True,exist_ok=True)
    fd=os.open(p,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    with os.fdopen(fd,"w") as f:json.dump(result,f,indent=2,allow_nan=False)

def main():
    import argparse
    p=argparse.ArgumentParser()
    p.add_argument("--live",action="store_true")
    p.add_argument("--future-symbol",required=True)
    p.add_argument("--token-path",type=Path,required=True)
    p.add_argument("--report",type=Path,required=True)
    p.add_argument("--assumed-expiry-at")
    a=p.parse_args()
    if not a.live:p.error("Explicit --live required")
    d=capture(load_token(a.token_path),a.future_symbol,expiry_at=a.assumed_expiry_at)
    save_new(a.report,d)
    print(json.dumps({"status":d["status"],"legs":len(d["legs"]),
      "price_drift_pct":d["price_drift_pct"],"expiry_id":d["expiry_id"],
      "exchange_oi_timestamp_verified":False,"oi_units_verified":False},indent=2))
if __name__=="__main__":main()
