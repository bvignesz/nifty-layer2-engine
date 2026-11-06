"""Run the unchanged v0.7.0 dual-track EOD scanner with a FYERS data shim.

Research-only, manual opt-in. No service scheduling, no OAuth automation, no
production SQLite access; choose private output/state paths.
"""
import argparse
import importlib.util
from pathlib import Path
import sys

from .fyers_bridge import FyersDownloadShim,load_credentials_and_map

def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mapping",type=Path,required=True)
    parser.add_argument("--token",type=Path,required=True)
    parser.add_argument("--symbols",required=True)
    parser.add_argument("--benchmark",required=True,
                        help="Existing screener benchmark key present in mapping JSON")
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--state-file",type=Path,required=True)
    args=parser.parse_args(argv)
    credentials,mapping=load_credentials_and_map(args.token,args.mapping)
    required=[args.benchmark,*[x.strip().upper()+".NS" for x in args.symbols.split(",")]]
    missing=[x for x in required if x not in mapping]
    if missing:parser.error("Approved mapping missing: "+", ".join(missing))
    source=Path(__file__).parent/"frozen"/"nifty500_rs_wpr_poc_screener_v0_7_0.py"
    spec=importlib.util.spec_from_file_location("_unchanged_eod_v070",source)
    module=importlib.util.module_from_spec(spec)
    sys.modules[spec.name]=module
    spec.loader.exec_module(module)
    shim=FyersDownloadShim(credentials,mapping)
    module.require_yfinance=lambda:shim
    original_argv=sys.argv
    try:
        # Existing strategy still receives its own original CLI argument parser.
        sys.argv=[str(source),"--symbols",args.symbols,
                  "--benchmark",args.benchmark,"--output",str(args.output),
                  "--state-file",str(args.state_file)]
        return module.main()
    finally:
        sys.argv=original_argv

if __name__=="__main__":
    raise SystemExit(main())
