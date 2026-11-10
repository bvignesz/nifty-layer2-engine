"""Manual import/query of verified Market Memory cases, no implicit labeling.

Input must be independently validated replay cases carrying evidence SHA256,
feature observation time, outcome maturity and net P&L after costs. No
synthetic candidates, no automated import of legacy nine-check state.
"""
import argparse,json
from datetime import datetime,timezone
from pathlib import Path
from .market_memory import import_cases,search_cases,memory_status
from .quality_filter import assess_quality
from .expired_options_probe import save_report

def run(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    sub=p.add_subparsers(dest="command",required=True)
    for name in ("import","search","status"):
        cmd=sub.add_parser(name)
        cmd.add_argument("--db",type=Path,required=True)
        if name=="import":
            cmd.add_argument("--cases",type=Path,required=True)
        elif name=="search":
            cmd.add_argument("--query-json",type=Path,required=True,
                             help="Feature vector and observed_at_utc from current setup")
            cmd.add_argument("--report",type=Path,required=True)
    args=p.parse_args(argv)
    if args.command=="import":
        data=json.loads(args.cases.read_text(encoding="utf-8"))
        result=import_cases(args.db,data)
    elif args.command=="search":
        query=json.loads(args.query_json.read_text(encoding="utf-8"))
        if not isinstance(query,dict):
            raise ValueError("expected query object")
        result=assess_quality(args.db,at=query["observed_at_utc"],
          features=query["features"],strategy=query["strategy"],
          regime=query.get("regime"),original_bias=query.get("original_bias","UNAVAILABLE"))
        save_report(args.report,result)
    else:
        result=memory_status(args.db)
    print(json.dumps({k:v for k,v in result.items() if k!="history"},allow_nan=False))
    return 0 if result["status"] in ("CASES_IMPORTED","AVAILABLE",
        "NO_VERIFIED_MEMORY","RESEARCH_CONTEXT_AVAILABLE") else 2

if __name__=="__main__":
    raise SystemExit(run())
