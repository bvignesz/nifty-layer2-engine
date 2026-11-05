"""Opt-in read-only FYERS option OI capture with receipt time brackets.

A safe research-only acquisition for a specific expiry. Avoids interpreting
the FYERS optionchain timestamp argument as a historical time selector.
Each capture is new and immutable. Never changes the existing collector.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import time

from . import fyers
from .fyers_integration_probe import load_token
from .option_observation_gate import snapshot_from_response, comparable_pair

def capture_one(credentials, *, transport=None, now=None, strikes=10):
    if not 1<=int(strikes)<=50:raise ValueError("Invalid strike count")
    transport=transport or fyers.request
    def call(params):
        request_at=(now or (lambda:datetime.now(timezone.utc)))()
        response=transport("optionchain",params=params,credentials=credentials)
        received_at=(now or (lambda:datetime.now(timezone.utc)))()
        return response, request_at, received_at

    initial,_,_=call({"symbol":"NSE:NIFTY50-INDEX","strikecount":1,"timestamp":""})
    choices=initial.get("data",{}).get("expiryData",[])
    if not isinstance(choices,list) or not choices or not isinstance(choices[0],dict):
        raise ValueError("Missing FYERS expiry")
    expiry=choices[0].get("expiry")
    if expiry is None:raise ValueError("Missing FYERS expiry ID")
    params={"symbol":"NSE:NIFTY50-INDEX","strikecount":int(strikes),
            "timestamp":str(expiry),"greeks":"1"}
    response,start,end=call(params)
    data=snapshot_from_response(response,requested_at=start,received_at=end,expiry_id=expiry)
    if data["meta"]["status"]!="RECEIPT_ONLY":
        raise ValueError("No valid bracketed option snapshot")
    # Archive contract identity and OI, not account or access-token fields.
    data["expiry_date"]=choices[0].get("date")
    data["data_source"]="FYERS_OPTIONCHAIN_RECEIPT_ONLY"
    data["broker_schema_exchange_time_verified"]=False
    return data

def write_capture(path,data):
    path=Path(path).expanduser()
    path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    # Create-only; mode 0600 and no overwrite, e.g. -20261105-0930.json
    import os
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,"w",encoding="utf-8") as handle:
        json.dump(data,handle,ensure_ascii=False,indent=2,allow_nan=False)
    return path

def compare_files(first,second):
    with Path(first).open(encoding="utf-8") as f:prior=json.load(f)
    with Path(second).open(encoding="utf-8") as f:recent=json.load(f)
    return comparable_pair(prior,recent)

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    group=p.add_mutually_exclusive_group(required=True)
    group.add_argument("--live",action="store_true")
    group.add_argument("--compare",nargs=2,metavar=("PREVIOUS_JSON","LATEST_JSON"))
    p.add_argument("--token-path",type=Path,default=fyers.TOKEN_PATH)
    p.add_argument("--strikecount",type=int,default=10)
    p.add_argument("--report",type=Path)
    args=p.parse_args(argv)
    if args.compare:
        result=compare_files(*args.compare)
        print(json.dumps(result,indent=2,allow_nan=False))
        return 0 if result["status"]=="COMPARABLE_RECEIPT_DELTA_UNVERIFIED" else 2
    if not args.report:p.error("--report required with --live")
    credentials=load_token(args.token_path)
    data=capture_one(credentials,strikes=args.strikecount)
    write_capture(args.report,data)
    # Never print per-contract OI, credentials, or raw responses by default.
    print(json.dumps({"status":data["meta"]["status"],
                      "expiry_id":data["meta"]["expiry_id"],
                      "expiry_date":data["expiry_date"],
                      "option_leg_count":len(data["legs"]),
                      "requested_at_utc":data["meta"]["requested_at_utc"],
                      "received_at_utc":data["meta"]["received_at_utc"],
                      "exchange_time_verified":False,
                      "report":str(args.report)},indent=2))
    return 0
if __name__=="__main__":
    raise SystemExit(main())
