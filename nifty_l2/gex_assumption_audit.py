"""Independent GEX model-assumption audit. No trading recommendation.

The legacy formula uses OI directly as underlying units:
    gamma * OI_units * F^2 * .01 / 1e7 (INR crore per 1% move).
We compute sensitivity to broker OI quantity convention and to UNKNOWN
dealer-position signs. We never claim that CE-positive/PE-negative represents
observed dealer inventory or exact hedging flows.
"""
from collections import Counter
import argparse
from datetime import datetime,timezone
import json
from math import isfinite
from pathlib import Path
import sqlite3

def _positive(value):
    try:
        x=float(value)
        return x if isfinite(x) and x>0 else None
    except (TypeError,ValueError,OverflowError):
        return None

def gex_sensitivity(legs, *, underlying, lot_size, oi_basis="unknown"):
    """OI basis: 'underlying_units' or 'contracts'; defaults UNKNOWN."""
    f=_positive(underlying)
    if f is None or not isinstance(lot_size,int) or lot_size<=0:
        raise ValueError("Positive underlying and explicit contract lot required")
    if oi_basis not in ("unknown","underlying_units","contracts"):
        raise ValueError("Unsupported OI basis")
    counts=Counter()
    call=put=0.0
    for leg in legs:
        if not isinstance(leg,dict) or leg.get("option_type") not in ("CE","PE"):
            continue
        counts["option_legs"]+=1
        g=leg.get("greeks")
        if not isinstance(g,dict) or _positive(g.get("gamma")) is None:
            counts["missing_or_invalid_broker_gamma"]+=1
            continue
        oi=_positive(leg.get("oi"))
        if oi is None:
            counts["missing_or_invalid_oi"]+=1
            continue
        counts["usable_legs"]+=1
        raw_gamma=float(g["gamma"])
        # This reproduces the legacy numeric GEX unit expression for input OI.
        contribution=.01*f*f*raw_gamma*oi/1e7
        if leg["option_type"]=="CE":
            call+=contribution
        else:
            put+=contribution
    if counts["usable_legs"]==0:
        return {"status":"UNAVAILABLE","reason":"No complete broker gamma/OI legs",
                "counts":dict(counts)}
    # OI in contracts means each contract must be multiplied by lot_size.
    scale=lot_size if oi_basis=="contracts" else 1
    ce,pe=call*scale,put*scale
    output={
        "label":"SIGNED-OI GEX SCENARIO — UNVERIFIED",
        "lot_size_verified":False,
        "status":"SCENARIO_ONLY" if oi_basis!="unknown" else "OI_UNITS_UNVERIFIED",
        "counts":dict(counts),
        "oi_basis":oi_basis,"lot_size":lot_size,
        "call_magnitude_cr_per_1pct":ce,"put_magnitude_cr_per_1pct":pe,
        "call_positive_put_negative_cr_per_1pct":ce-pe,
        "dealer_all_long_gamma_cr_per_1pct":ce+pe,
        "dealer_all_short_gamma_cr_per_1pct":-ce-pe,
        "unscaled_oi_interpretation_cr_per_1pct":call-put,
        "if_oi_is_contracts_cr_per_1pct":(call-put)*lot_size,
        "dealer_inventory_observed":False,"exchange_oi_timestamp_verified":False,
        "gamma_source":"FYERS_OPTIONCHAIN_BROKER_MODEL",
        "coverage_complete":False,
        "note":"Sign and total-chain exposure unknown. No exact dealer gamma flip."
    }
    return output

def audit_archived(path, *, lot_size=65, max_events=500):
    """Read saved raw FYERS option legs; keep aggregated counts only."""
    path=Path(path).expanduser().resolve()
    result={"status":"NO_DATA","research_events":0,
            "available_greek_events":0,"missing_greek_events":0,
            "unverified_oi_basis_events":0,
            "lot_size_assumed":lot_size,
            "legacy_default_lot_size":75,
            "legacy_default_lot_mismatch":lot_size!=75,
            "examples":[],"exchange_oi_timestamp_verified":False,
            "dealer_inventory_observed":False,"production_db_modified":False}
    with sqlite3.connect(path.as_uri()+"?mode=ro",uri=True,timeout=10) as db:
        db.execute("PRAGMA query_only=ON")
        rows=db.execute("""SELECT observed_at_utc,payload_json FROM events
             WHERE kind IN ('scheduled_research','manual_research')
             ORDER BY observed_at_utc DESC LIMIT ?""",(max_events,))
        for stamp,raw in rows:
            result["research_events"]+=1
            try:
                payload=json.loads(raw)
            except (TypeError,ValueError):
                result["missing_greek_events"]+=1
                continue
            configs=payload.get("configuration",{}) if isinstance(payload,dict) else {}
            calls=payload.get("calls",[]) if isinstance(payload,dict) else []
            # Store legacy configuration information in counts, not secrets.
            legacy_lot=configs.get("NIFTY_LOT_SIZE")
            chosen=None
            for call in calls:
                if not isinstance(call,dict) or call.get("method")!="optionchain":
                    continue
                res=call.get("response")
                if not isinstance(res,dict):
                    continue
                data=res.get("data",{})
                legs=data.get("optionsChain",[]) if isinstance(data,dict) else []
                if not isinstance(legs,list) or not legs:
                    continue
                first=next((item for item in legs if isinstance(item,dict)
                            and item.get("strike_price")==-1),{})
                price=_positive(first.get("fp")) or _positive(first.get("ltp"))
                if price is None:
                    continue
                candidate=gex_sensitivity(legs,underlying=price,lot_size=lot_size)
                if candidate["counts"].get("usable_legs",0)>0:
                    chosen=candidate
                    break
            if chosen is None:
                result["missing_greek_events"]+=1
            else:
                result["available_greek_events"]+=1
                result["unverified_oi_basis_events"]+=1
                if len(result["examples"])<5:
                    result["examples"].append({
                        "observed_at_utc":stamp,
                        "legacy_lot_size_recorded":legacy_lot,
                        "leg_counts":chosen["counts"],
                        "unscaled_scenario_cr_per_1pct":chosen["unscaled_oi_interpretation_cr_per_1pct"],
                        "contract_oi_scenario_cr_per_1pct":chosen["if_oi_is_contracts_cr_per_1pct"]})
    result["status"]="ASSUMPTIONS_UNVERIFIED" if result["available_greek_events"] else "BROKER_GAMMA_UNAVAILABLE"
    return result

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--db",required=True,type=Path)
    p.add_argument("--lot-size",required=True,type=int)
    p.add_argument("--report",required=True,type=Path)
    a=p.parse_args(argv)
    r=audit_archived(a.db,lot_size=a.lot_size)
    a.report.parent.mkdir(parents=True,exist_ok=True)
    with a.report.open("x",encoding="utf-8") as f:
        json.dump(r,f,indent=2,allow_nan=False)
    a.report.chmod(0o600)
    print(json.dumps(r,indent=2,allow_nan=False))
    return 0
if __name__=="__main__":
    raise SystemExit(main())
