"""FYERS option OI time-quality gate. Receipt-time observations, NOT exchange bars.

The FYERS optionchain 'timestamp' argument is an EXPIRY identifier.
Until an authoritative per-option-OI exchange update time is available,
never promote option observations into verified 1m/3m candles.
"""
from datetime import datetime, timezone
from math import isfinite

def _dt(value):
    dt=value if isinstance(value,datetime) else datetime.fromisoformat(str(value).replace("Z","+00:00"))
    if dt.tzinfo is None:
        raise ValueError("Timezone-aware timestamp required")
    return dt.astimezone(timezone.utc)

def bracket_snapshot(*, requested_at, received_at, expiry_id, response):
    """Label one fresh broker response with actual request/receipt bounds."""
    start,end=_dt(requested_at),_dt(received_at)
    if end<start:
        raise ValueError("Receipt predates request")
    elapsed=(end-start).total_seconds()
    data=response.get("data",{}) if isinstance(response,dict) else {}
    legs=data.get("optionsChain",[]) if isinstance(data,dict) else []
    valid=[x for x in legs if isinstance(x,dict) and x.get("option_type") in ("CE","PE")
           and isinstance(x.get("symbol"),str) and x.get("symbol")]
    return {
        "status":"RECEIPT_ONLY" if response.get("s")=="ok" and valid and elapsed<=30 else "UNUSABLE",
        "requested_at_utc":start.isoformat(),"received_at_utc":end.isoformat(),
        "request_duration_seconds":elapsed,"expiry_id":str(expiry_id),
        "chain_legs":len(valid),"exchange_oi_timestamp":None,
        "exchange_timestamp_verified":False,"completed_option_candle":False,
        "note":"FYERS optionchain timestamp selects expiry; this is a receipt-window OI snapshot."
    }

def comparable_pair(previous,current,*,max_receipt_gap_seconds=360,
                    min_receipt_gap_seconds=90,max_request_seconds=30):
    """Conservative matched-contract receipt delta, never a timed exchange bar."""
    a,b=previous["meta"],current["meta"]
    if any(x.get("status")!="RECEIPT_ONLY" for x in (a,b)):
        return {"status":"BLOCKED","reason":"Unusable response"}
    if a["expiry_id"]!=b["expiry_id"]:
        return {"status":"BLOCKED","reason":"Expiry mismatch"}
    left=_dt(a["received_at_utc"])
    right_start=_dt(b["requested_at_utc"])
    right=_dt(b["received_at_utc"])
    gap=(right-left).total_seconds()
    if gap<min_receipt_gap_seconds or gap>max_receipt_gap_seconds or right_start<left:
        return {"status":"BLOCKED","reason":"Receipt gap, overlap or ordering failure"}
    if max(a["request_duration_seconds"],b["request_duration_seconds"])>max_request_seconds:
        return {"status":"BLOCKED","reason":"Request latency exceeds guard"}
    if left.date()!=right.date():
        return {"status":"BLOCKED","reason":"Cross-day comparison"}
    previous_legs=previous.get("legs",{})
    current_legs=current.get("legs",{})
    if not previous_legs or not current_legs:
        return {"status":"BLOCKED","reason":"No matching contracts"}
    if set(previous_legs)!=set(current_legs):
        return {"status":"BLOCKED","reason":"Incomplete or changed option universe"}
    changes={}
    for symbol in previous_legs:
        left_oi,right_oi=previous_legs[symbol],current_legs[symbol]
        try:
            x,y=float(left_oi),float(right_oi)
        except (TypeError,ValueError):
            return {"status":"BLOCKED","reason":"Missing OI"}
        if not all(isfinite(z) and z>=0 for z in (x,y)):
            return {"status":"BLOCKED","reason":"Invalid OI"}
        changes[symbol]=y-x
    return {"status":"COMPARABLE_RECEIPT_DELTA_UNVERIFIED",
            "receipt_gap_seconds":gap,"delta_oi_by_symbol":changes,
            "exchange_timestamp_verified":False,
            "completed_option_candle":False,
            "note":"Change occurred between response captures; exact update time and seller identity unknown."}

def snapshot_from_response(response,*,requested_at,received_at,expiry_id):
    meta=bracket_snapshot(requested_at=requested_at,received_at=received_at,
                          expiry_id=expiry_id,response=response)
    chain=response.get("data",{}).get("optionsChain",[])
    legs={}
    seen=set()
    for row in chain:
        if not isinstance(row,dict) or row.get("option_type") not in ("CE","PE"):
            continue
        key=row.get("symbol")
        if not isinstance(key,str) or not key or key in seen:
            meta["status"]="UNUSABLE"
            continue
        seen.add(key)
        legs[key]=row.get("oi")
    return {"meta":meta,"legs":legs}
