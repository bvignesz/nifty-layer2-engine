"""Read-only latest actual-expiry archive, separate from the nine-check cache."""
from datetime import datetime
import json
from pathlib import Path
from .storage import IST

def read_archive(directory,day,strike):
    files=sorted(Path(directory).glob("expiry-*.json"),reverse=True)
    if len(files)>100:files=files[:100]
    for path in files:
        if not path.is_file() or path.stat().st_size>3_000_000:continue
        try:
            with path.open(encoding="utf-8") as f:data=json.load(f)
            captured=datetime.fromisoformat(data["observed_at_utc"].replace("Z","+00:00"))
            if captured.tzinfo is None or captured.astimezone(IST).date().isoformat()!=day:
                continue
            rows=[]
            for exp in data.get("expiries",[]):
                for leg in exp.get("legs",[]):
                    if int(leg.get("strike_price",0))!=int(strike):continue
                    if leg.get("option_type") not in ("CE","PE"):continue
                    g=leg.get("greeks") or {}
                    if not isinstance(g,dict):g={}
                    rows.append({
                        "expiry":exp.get("date"),"side":leg["option_type"],
                        "observed_at_ist":captured.astimezone(IST).isoformat(),
                        "symbol":leg.get("symbol"),"ltp":leg.get("ltp"),
                        "bid":leg.get("bid"),"ask":leg.get("ask"),
                        "oi":leg.get("oi"),"cumulative_volume":leg.get("volume"),
                        "iv":g.get("iv"),"delta":g.get("delta"),"gamma":g.get("gamma"),
                        "theta":g.get("theta"),"vega":g.get("vega"),
                        "quality":"BROKER_RECEIPT_ONLY"})
            return rows
        except (OSError,ValueError,KeyError,TypeError):
            continue
    return []
