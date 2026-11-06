"""Optional, separate FYERS multi-expiry data probe. No change to L2 collector.

Produces an atomic JSON snapshot (not trading signals or GEX) from actual FYERS
expiry IDs. Intended to run manually for validation before scheduled use.
"""
from datetime import datetime,timezone
import json
import os
from pathlib import Path
import tempfile

from . import fyers

def collect_expiries(credentials,symbol="NSE:NIFTY50-INDEX",count=3,transport=None,
                     observed_at=None):
    if symbol not in ("NSE:NIFTY50-INDEX","NSE:NIFTYBANK-INDEX","BSE:SENSEX-INDEX"):
        raise ValueError("Unsupported index symbol")
    if not 1<=count<=4:raise ValueError("1–4 actual expiries only")
    transport=transport or fyers.request
    now=observed_at or datetime.now(timezone.utc)
    if now.tzinfo is None:raise ValueError("UTC observation timestamp required")
    initial=transport("optionchain",params={"symbol":symbol,"strikecount":1,"timestamp":""},
                      credentials=credentials)
    expiries=initial.get("data",{}).get("expiryData",[])
    if not isinstance(expiries,list) or not expiries:
        raise ValueError("No FYERS expiry data")
    out={"status":"CAPTURED_UNVERIFIED","index":symbol,"observed_at_utc":now.isoformat(),
         "expiries":[],"note":"Broker receipt time only; exchange quote timestamps unverified."}
    seen=set()
    for item in expiries:
        if len(out["expiries"])>=count:break
        if not isinstance(item,dict):continue
        exp=item.get("date")
        epoch=item.get("expiry")
        if not exp or not epoch or str(epoch) in seen:continue
        seen.add(str(epoch))
        response=transport("optionchain",params={"symbol":symbol,"strikecount":10,
                       "timestamp":str(epoch),"greeks":"1"},credentials=credentials)
        chain=response.get("data",{}).get("optionsChain",[])
        if not isinstance(chain,list):continue
        legs=[]
        for leg in chain:
            if not isinstance(leg,dict) or leg.get("option_type") not in ("CE","PE"):
                continue
            # Explicit allowlist: never copy token / credentials / account information.
            legs.append({key:leg.get(key) for key in
                ("symbol","strike_price","option_type","ltp","bid","ask",
                 "oi","volume","oich","oichp","greeks")})
        out["expiries"].append({"date":str(exp),"id":str(epoch),"legs":legs})
    return out

def write_snapshot(data,destination):
    path=Path(destination).expanduser()
    if path.exists():
        raise FileExistsError("Refusing to overwrite an existing expiry snapshot")
    path.parent.mkdir(parents=True,exist_ok=True)
    fd,temp=tempfile.mkstemp(prefix=".expiry-",suffix=".tmp",dir=path.parent)
    try:
        with os.fdopen(fd,"w",encoding="utf-8") as f:
            json.dump(data,f,allow_nan=False)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(temp,0o600)
        os.link(temp,path)  # create-only: cannot clobber existing snapshot
    finally:
        Path(temp).unlink(missing_ok=True)
    return path
