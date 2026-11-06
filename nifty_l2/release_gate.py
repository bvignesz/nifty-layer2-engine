"""Fail-closed consolidated release gate. DOES NOT deploy or install anything.

This is a verification report of evidence collected on the actual AWS host.
Passing CI tests alone cannot change any real-market-validation status.
"""
import argparse
import json
from pathlib import Path

HIST_REQUIRED=("sqlite_integrity","schema_present","records_present",
               "research_safety","strike_integrity","nine_checks_recorded",
               "exchange_timestamp_coverage")
FYERS_REQUIRED=("profile","index_quote","actual_expiry_optionchain",
                "equity_daily","equity_15m","futures_3m")

def evaluate(historical,fyers,eod_parity=None,greeks_audit=None,
             outcome_audit=None,security_audit=None):
    h=historical.get("checks",{}) if isinstance(historical,dict) else {}
    fsteps=fyers.get("checks",[]) if isinstance(fyers,dict) else []
    fs={r.get("name"):r.get("status") for r in fsteps if isinstance(r,dict)}
    details={
        "historical":{k:bool(h.get(k)) for k in HIST_REQUIRED},
        "fyers":{k:fs.get(k)=="PASS" for k in FYERS_REQUIRED},
        "eod_source_parity":bool((eod_parity or {}).get("verified")),
        "gex_units_and_greeks":bool((greeks_audit or {}).get("verified")),
        "outcome_labeling":bool((outcome_audit or {}).get("verified")),
        "web_access_controls":bool((security_audit or {}).get("verified")),
    }
    passed=(all(details["historical"].values())
            and all(details["fyers"].values())
            and all(details[k] for k in ("eod_source_parity","gex_units_and_greeks",
                "outcome_labeling","web_access_controls")))
    return {"status":"READY_FOR_MANUAL_DEPLOYMENT_REVIEW" if passed else "BLOCKED",
            "checks":details,"auto_deploy":False,"orders_enabled":False,
            "note":"This is an evidence gate; audit documents must be independently verified. No strategy profitability claim."}

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--historical",type=Path,required=True)
    p.add_argument("--fyers",type=Path,required=True)
    p.add_argument("--eod-parity",type=Path)
    p.add_argument("--greeks-audit",type=Path)
    p.add_argument("--outcome-audit",type=Path)
    p.add_argument("--security-audit",type=Path)
    p.add_argument("--report",type=Path,required=True)
    a=p.parse_args(argv)
    def read(path):
        if path is None:return None
        with path.open(encoding="utf-8") as f:return json.load(f)
    result=evaluate(read(a.historical),read(a.fyers),read(a.eod_parity),
                    read(a.greeks_audit),read(a.outcome_audit),read(a.security_audit))
    with a.report.open("x",encoding="utf-8") as f:
        json.dump(result,f,indent=2)
    a.report.chmod(0o600)
    print(result["status"])
    return 0 if result["status"]=="READY_FOR_MANUAL_DEPLOYMENT_REVIEW" else 2

if __name__=="__main__":
    raise SystemExit(main())
