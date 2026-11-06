"""Independent Black-76 gamma plausibility audit, independent of legacy functions.

Research-only. Explicit forward and expiry time are deliberately required:
an optionchain expiry ID is not guaranteed to represent the exact exercise
cutoff; an index quote is not automatically an option-pricing forward.
No GEX re-scaling or dealer-position inference is performed.

Compare broker gamma with analytic Black-76 per underlying point using
broker-provided implied volatility (percent). Theoretical vs broker
differences can reflect forward, rates, time cutoff, model and stale inputs.
"""
import argparse
from datetime import datetime,timezone
import json
from math import exp,isfinite,log,pi,sqrt
from pathlib import Path
import sqlite3
from statistics import median

def parse_time(value):
    dt=datetime.fromisoformat(str(value).replace("Z","+00:00"))
    if dt.tzinfo is None:
        raise ValueError("Timezone offset required")
    return dt.astimezone(timezone.utc)

def finite_positive(value):
    try:
        number=float(value)
        return number if isfinite(number) and number>0 else None
    except (ValueError,TypeError,OverflowError):
        return None

def black76_gamma(forward,strike,vol_decimal,tenor_years,rate=0.0):
    values=[forward,strike,vol_decimal,tenor_years]
    if any(finite_positive(v) is None for v in values):
        raise ValueError("Positive forward, strike, sigma, tenor required")
    if not isfinite(rate):
        raise ValueError("Finite rate required")
    d1=(log(forward/strike)+0.5*vol_decimal*vol_decimal*tenor_years)/(vol_decimal*sqrt(tenor_years))
    return exp(-rate*tenor_years)*exp(-0.5*d1*d1)/(sqrt(2*pi)*forward*vol_decimal*sqrt(tenor_years))

def compare_legs(legs,*,asof,expiry_at,forward,rate=0.0):
    asof=parse_time(asof)
    expiry=parse_time(expiry_at)
    f=finite_positive(forward)
    if f is None:raise ValueError("Positive assumed forward required")
    if asof>=expiry:
        return {"status":"UNAVAILABLE","reason":"At or after assumed expiry"}
    tenor=(expiry-asof).total_seconds()/(365*86400)
    included=[]
    skipped={"invalid_strike":0,"missing_broker_gamma":0,"invalid_iv":0,"invalid_leg":0}
    for leg in legs:
        if not isinstance(leg,dict) or leg.get("option_type") not in ("CE","PE"):
            continue
        k=finite_positive(leg.get("strike_price"))
        g=leg.get("greeks")
        if k is None:skipped["invalid_strike"]+=1;continue
        if not isinstance(g,dict):skipped["invalid_leg"]+=1;continue
        broker=finite_positive(g.get("gamma"))
        iv=finite_positive(g.get("iv"))
        if broker is None:skipped["missing_broker_gamma"]+=1;continue
        if iv is None or iv>500:skipped["invalid_iv"]+=1;continue
        estimate=black76_gamma(f,k,iv/100,tenor,rate)
        if estimate<=1e-15:continue
        ratio=broker/estimate
        included.append({"ratio":ratio,"abs_relative_error":abs(ratio-1),
                         "model":estimate,"broker":broker,
                         "strike":k,"type":leg["option_type"]})
    if not included:
        return {"status":"UNAVAILABLE","usable_legs":0,"skipped":skipped}
    ratios=sorted(x["ratio"] for x in included)
    errors=sorted(x["abs_relative_error"] for x in included)
    return {"status":"MODEL_COMPARISON_UNVERIFIED",
            "usable_legs":len(included),"skipped":skipped,
            "median_broker_over_black76":median(ratios),
            "median_absolute_relative_error":median(errors),
            "ratio_min":ratios[0],"ratio_max":ratios[-1],
            "fraction_within_20pct":sum(.8<=v<=1.2 for v in ratios)/len(ratios),
            "assumed_forward":f,"assumed_expiry_at_utc":expiry.isoformat(),
            "assumed_rate":rate,"time_to_expiry_years":tenor,
            "oi_units_verified":False,"broker_gamma_convention_verified":False,
            "dealer_position_observed":False,"greeks_independently_validated":False,
            "note":"Analytic model consistency only; without synchronized forward and true expiry cutoff, deviations are not broker errors."}

def audit_archive(path,*,forward,expiry_at,rate=0.0,max_events=200):
    path=Path(path).expanduser().resolve()
    outcomes=[]
    with sqlite3.connect(path.as_uri()+"?mode=ro",uri=True,timeout=10) as conn:
        conn.execute("PRAGMA query_only=ON")
        for stamp,raw in conn.execute("""SELECT observed_at_utc,payload_json FROM events
            WHERE kind IN ('scheduled_research','manual_research')
            ORDER BY observed_at_utc DESC LIMIT ?""",(max_events,)):
            try:
                payload=json.loads(raw)
                calls=payload.get("calls",[])
                chains=[]
                for call in calls:
                    if not isinstance(call,dict) or call.get("method")!="optionchain":continue
                    req=call.get("request",{})
                    res=call.get("response",{})
                    if not isinstance(req,dict) or not isinstance(res,dict):continue
                    if not req.get("timestamp"):continue
                    chains=res.get("data",{}).get("optionsChain",[])
                    if isinstance(chains,list) and chains:break
                if not chains:continue
                result=compare_legs(chains,asof=stamp,expiry_at=expiry_at,forward=forward,rate=rate)
                if result["status"]!="UNAVAILABLE":outcomes.append((stamp,result))
            except (TypeError,ValueError,KeyError,OverflowError):
                continue
    return {
        "status":"MODEL_COMPARISON_UNVERIFIED" if outcomes else "INSUFFICIENT_MATCHING_DATA",
        "events_with_comparable_greeks":len(outcomes),
        "median_event_broker_over_black76":median([v["median_broker_over_black76"] for _,v in outcomes]) if outcomes else None,
        "median_event_abs_relative_error":median([v["median_absolute_relative_error"] for _,v in outcomes]) if outcomes else None,
        "sample_events":[{"observed_at_utc":s,"usable_legs":r["usable_legs"],
                          "median_gamma_ratio":r["median_broker_over_black76"],
                          "fraction_within_20pct":r["fraction_within_20pct"]}
                         for s,r in outcomes[:8]],
        "assumed_forward":forward,"assumed_expiry_at":str(expiry_at),
        "assumed_rate":rate,"source":"ARCHIVED_FYERS_BROKER_IV_AND_GAMMA",
        "broker_gamma_convention_verified":False,
        "source_forward_timestamp_verified":False,
        "oi_units_verified":False,"dealer_inventory_observed":False,
        "production_db_modified":False,
        "limitations":"An explicit assumed forward is reused for all events; this is a plausibility test, not historical mark-by-mark parity."
    }

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--db",type=Path,required=True)
    p.add_argument("--assumed-forward",type=float,required=True)
    p.add_argument("--expiry-at",required=True,help="Explicit date/time and offset, e.g. 2026-11-09T15:40:00+05:30")
    p.add_argument("--rate",type=float,default=0.0)
    p.add_argument("--report",type=Path,required=True)
    a=p.parse_args(argv)
    result=audit_archive(a.db,forward=a.assumed_forward,expiry_at=a.expiry_at,rate=a.rate)
    a.report.parent.mkdir(parents=True,exist_ok=True)
    with a.report.open("x",encoding="utf-8") as handle:
        json.dump(result,handle,indent=2,allow_nan=False)
    a.report.chmod(0o600)
    print(json.dumps(result,indent=2,allow_nan=False))
    return 0
if __name__=="__main__":
    raise SystemExit(main())
