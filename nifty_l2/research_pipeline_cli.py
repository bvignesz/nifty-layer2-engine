"""Command-line research workflows: replay, train, and NSE membership import.

All inputs must come from verified broker or dated official data. No live
broker calls and no order endpoints. Output is exclusive private JSON evidence.
"""
import argparse,json
from pathlib import Path
from .expired_options_probe import save_report
from .historical_option_replay import replay_expired_contract
from .xgboost_shadow import train_shadow
from eod_scanner.nse_universe_history import import_snapshot

def run(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    sub=p.add_subparsers(dest="mode",required=True)
    back=sub.add_parser("replay")
    back.add_argument("--contract-report",type=Path,required=True)
    back.add_argument("--signals",type=Path,required=True)
    back.add_argument("--side",choices=("CE","PE"),required=True)
    back.add_argument("--quantity",type=int,required=True)
    back.add_argument("--horizon",type=int,choices=(9,15,30),default=9)
    back.add_argument("--entry-spread",type=float,default=0.0)
    back.add_argument("--exit-spread",type=float,default=0.0)
    back.add_argument("--entry-slippage",type=float,default=0.0)
    back.add_argument("--exit-slippage",type=float,default=0.0)
    back.add_argument("--brokerage",type=float,required=True)
    back.add_argument("--statutory-charges",type=float,required=True)
    back.add_argument("--report",type=Path,required=True)
    train=sub.add_parser("train")
    train.add_argument("--features-json",type=Path,required=True)
    train.add_argument("--report",type=Path,required=True)
    imp=sub.add_parser("nse-import")
    imp.add_argument("--constituents-csv",type=Path,required=True)
    imp.add_argument("--as-of",required=True)
    imp.add_argument("--db",type=Path,required=True)
    args=p.parse_args(argv)
    if args.mode=="replay":
        dataset=json.loads(args.contract_report.read_text())
        signals=json.loads(args.signals.read_text())
        output=replay_expired_contract(dataset,signals,side=args.side,
            quantity=args.quantity,horizon_minutes=args.horizon,
            entry_spread=args.entry_spread,exit_spread=args.exit_spread,
            entry_slippage=args.entry_slippage,exit_slippage=args.exit_slippage,
            brokerage_total=args.brokerage,
            statutory_charges=args.statutory_charges)
        save_report(args.report,output)
    elif args.mode=="train":
        rows=json.loads(args.features_json.read_text())
        output=train_shadow(rows)
        save_report(args.report,output)
    else:
        output=import_snapshot(args.db,args.constituents_csv,as_of=args.as_of)
    print(json.dumps({k:v for k,v in output.items() if k not in ("results","bars","rows","symbols")},
                     ensure_ascii=False,allow_nan=False))
    if args.mode=="replay":
        return 0 if output["replayed"]>0 else 2
    if args.mode=="train":
        return 0 if output["status"]=="SHADOW_MODEL_EVALUATED" else 2
    return 0

if __name__=="__main__":
    raise SystemExit(run())
