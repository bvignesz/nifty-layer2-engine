"""Read-only FYERS OI-unit reconciliation.

Two evidence levels:
(1) structural divisibility by a *verified* contract lot (cannot prove units);
(2) optional manually sourced NSE OI-in-CONTRACTS CSV, matched by exact symbol,
    expiry/strike/type and reasonably close capture time. NEVER scrape NSE.

NSE's website states OI display is in contracts. FYERS API documentation says
'oi' but does not make the API quantity convention explicit. This audit does not
mutate stored observations, make external calls, or convert the original engine.
"""
import argparse
from collections import Counter
import csv
from datetime import datetime, timezone
import json
from math import isfinite
from pathlib import Path
import sqlite3

def _time(value):
    dt=datetime.fromisoformat(str(value).replace("Z","+00:00"))
    if dt.tzinfo is None:
        raise ValueError("Timestamp must include timezone")
    return dt.astimezone(timezone.utc)

def _number(v):
    try:
        x=float(v)
        return x if isfinite(x) and x>=0 else None
    except (ValueError,TypeError,OverflowError):
        return None

def archived_legs(db_path):
    """Select latest FYERS chain event per day, retaining expiry identifier."""
    path=Path(db_path).expanduser().resolve()
    records=[]
    with sqlite3.connect(path.as_uri()+"?mode=ro",uri=True,timeout=10) as db:
        db.execute("PRAGMA query_only=ON")
        for stamp, raw in db.execute("""SELECT observed_at_utc,payload_json FROM events
            WHERE kind IN ('scheduled_research','manual_research')
            ORDER BY observed_at_utc"""):
            try:
                observed=_time(stamp)
                payload=json.loads(raw)
            except (TypeError,ValueError):
                continue
            for item in payload.get("calls",[]):
                if not isinstance(item,dict) or item.get("method")!="optionchain":
                    continue
                req,res=item.get("request"),item.get("response")
                if not isinstance(req,dict) or not isinstance(res,dict):
                    continue
                expiry=str(req.get("timestamp",""))
                if not expiry or expiry=="0":
                    continue
                chain=res.get("data",{}).get("optionsChain",[])
                if not isinstance(chain,list):
                    continue
                for leg in chain:
                    if not isinstance(leg,dict) or leg.get("option_type") not in ("CE","PE"):
                        continue
                    oi=_number(leg.get("oi"))
                    strike=_number(leg.get("strike_price"))
                    symbol=leg.get("symbol")
                    if oi is None or strike is None or not symbol:
                        continue
                    records.append({"observed_at":observed,"expiry_id":expiry,
                                    "symbol":symbol,"strike":int(strike),
                                    "type":leg["option_type"],"oi":oi})
    return records

def structural_audit(records,lot):
    latest={}
    for r in records:
        latest[(r["observed_at"].date(),r["symbol"],r["expiry_id"])]=r
    vals=[r["oi"] for r in latest.values() if r["oi"]>0]
    multiples=sum(float(v).is_integer() and int(v)%lot==0 for v in vals)
    return {"unique_day_contract_observations":len(vals),
            "oi_multiples_of_lot":multiples,
            "fraction_multiple_of_lot":multiples/len(vals) if vals else None,
            "not_proof_of_quantity_basis":True}

def reconcile(records,reference_csv,lot,*,max_skew_seconds=180):
    """Require matching expiry, strike, type, symbol, bounded time difference.

    NSE reference CSV columns:
    observed_at_utc,expiry_id,symbol,strike,option_type,nse_oi_contracts
    The symbol must be the exact FYERS symbol from contract master/manual mapping.
    A mismatched/late reference is excluded, never guessed.
    """
    refs=[]
    with Path(reference_csv).open(newline="",encoding="utf-8-sig") as f:
        reader=csv.DictReader(f)
        expected={"observed_at_utc","expiry_id","symbol","strike","option_type","nse_oi_contracts"}
        if not expected.issubset(set(reader.fieldnames or [])):
            raise ValueError("Reference CSV lacks required columns")
        for row in reader:
            nse=_number(row["nse_oi_contracts"])
            if nse is None or nse<=0:
                continue
            try:
                ts=_time(row["observed_at_utc"])
                strike=int(row["strike"])
            except (ValueError,TypeError):
                continue
            refs.append({"at":ts,"expiry":row["expiry_id"],"symbol":row["symbol"],
                         "strike":strike,"type":row["option_type"],"contracts":nse})
    results=[]
    for ref in refs:
        matches=[r for r in records if
            r["expiry_id"]==ref["expiry"] and r["symbol"]==ref["symbol"]
            and r["strike"]==ref["strike"] and r["type"]==ref["type"]
            and abs((r["observed_at"]-ref["at"]).total_seconds())<=max_skew_seconds]
        if not matches:
            results.append({"contract":ref["symbol"],"status":"NO_TIME_ALIGNED_MATCH"})
            continue
        # Multiple equally plausible captures remain unverified; require unique nearest.
        ranked=sorted(matches,key=lambda r:abs((r["observed_at"]-ref["at"]).total_seconds()))
        nearest=ranked[0]
        if len(ranked)>1 and abs((ranked[1]["observed_at"]-ref["at"]).total_seconds()) == abs((nearest["observed_at"]-ref["at"]).total_seconds()):
            results.append({"contract":ref["symbol"],"status":"AMBIGUOUS_CAPTURE"})
            continue
        ratio=nearest["oi"]/ref["contracts"]
        # NSE reported contracts; FYERS could be contracts or underlying units.
        # 3% ratio tolerance only screens approximate matches, not verification.
        cls=("CONTRACTS_CANDIDATE" if abs(ratio-1)<=.03 else
             "UNDERLYING_UNITS_CANDIDATE" if abs(ratio-lot)/lot<=.03 else
             "INCONSISTENT")
        results.append({"contract":ref["symbol"],"status":cls,
                        "fyers_oi":nearest["oi"],"nse_contracts":ref["contracts"],
                        "ratio":ratio,
                        "capture_skew_seconds":abs((nearest["observed_at"]-ref["at"]).total_seconds())})
    candidates=[r["status"] for r in results if r["status"].endswith("_CANDIDATE")]
    return {"reference_rows":len(refs),"matched_candidate_rows":len(candidates),
            "candidate_contracts":candidates.count("CONTRACTS_CANDIDATE"),
            "candidate_underlying_units":candidates.count("UNDERLYING_UNITS_CANDIDATE"),
            "outcomes":results[:50],
            "oi_basis_independently_verified":False,
            "note":"Requires matching exchange-time snapshots or separately licensed synchronized reference. Receipt skew can invalidate ratio."}

def audit(db,lot,reference=None):
    if lot<=0:raise ValueError("Lot must be positive")
    rec=archived_legs(db)
    out={"status":"RESEARCH_ONLY","lot_size":lot,
         "source":"FYERS_ARCHIVED_OPTIONCHAIN","raw_observations":len(rec),
         "structural":structural_audit(rec,lot),
         "nse_oi_display_basis":"CONTRACTS",
         "fyers_oi_basis":"UNVERIFIED",
         "production_db_modified":False}
    if reference:
        out["manual_reference"]=reconcile(rec,reference,lot)
    return out

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--db",type=Path,required=True)
    p.add_argument("--lot-size",type=int,required=True)
    p.add_argument("--nse-reference-csv",type=Path)
    p.add_argument("--report",type=Path,required=True)
    a=p.parse_args(argv)
    result=audit(a.db,a.lot_size,a.nse_reference_csv)
    a.report.parent.mkdir(parents=True,exist_ok=True)
    with a.report.open("x",encoding="utf-8") as f:
        json.dump(result,f,indent=2,allow_nan=False)
    a.report.chmod(0o600)
    print(json.dumps(result,indent=2,allow_nan=False))
    return 0

if __name__=="__main__":
    raise SystemExit(main())
