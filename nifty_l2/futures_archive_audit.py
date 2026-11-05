"""Read-only provenance audit of recorded FYERS futures API calls.

The original live runner archives full FYERS calls in events.payload_json but
does not populate futures_data. This tool reports archived futures evidence;
it NEVER writes or backfills any SQLite column and never equates a receipt
timestamp with an exchange candle timestamp.
"""
from collections import Counter
from datetime import datetime, timedelta, timezone
import argparse
import json
from pathlib import Path
import sqlite3

from .storage import IST

def _utc(raw):
    dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError("Naive timestamp")
    return dt.astimezone(timezone.utc)

def _valid_close(bar, observed, minutes):
    if not isinstance(bar,(tuple,list)) or len(bar)<6:
        return False, False
    try:
        start = datetime.fromtimestamp(float(bar[0]), timezone.utc)
        close = start + timedelta(minutes=minutes)
        values = [float(bar[i]) for i in range(1,6)]
        if any(not __import__("math").isfinite(v) for v in values):
            return False, False
        o,h,l,c,v = values
        if l<=0 or c<l or c>h or o<l or o>h or v<0:
            return False, False
        # A completed candle must have finished at capture time.
        if close > observed or close.astimezone(IST).date() != start.astimezone(IST).date():
            return False, False
        if len(bar)<7 or bar[6] is None:
            return True, False
        oi=float(bar[6])
        return True, __import__("math").isfinite(oi) and oi>0
    except (ValueError,OverflowError,TypeError,OSError,IndexError):
        return False, False

def audit_archived_futures(path):
    path=Path(path).expanduser().resolve()
    result={"status":"FAIL","counts":{},"futures_symbols":[],"warnings":[],
            "production_data_modified":False}
    if not path.is_file():
        result["warnings"].append("Database not found")
        return result
    with sqlite3.connect(path.as_uri()+"?mode=ro",uri=True,timeout=10) as db:
        db.execute("PRAGMA query_only=ON")
        saved=db.execute("SELECT COUNT(*) FROM futures_data").fetchone()[0]
        rows=db.execute("""SELECT observed_at_utc,payload_json FROM events
            WHERE kind IN ('manual_research','scheduled_research')
            ORDER BY observed_at_utc""")
        metrics=Counter()
        symbols=Counter()
        for observed_at,blob in rows:
            metrics["research_events"]+=1
            try:
                observed=_utc(observed_at)
                payload=json.loads(blob)
                calls=payload.get("calls",[])
            except (ValueError,TypeError,AttributeError):
                metrics["invalid_archived_payloads"]+=1
                continue
            if not isinstance(calls,list):
                metrics["invalid_archived_payloads"]+=1
                continue
            has_fut=False
            for call in calls:
                if not isinstance(call,dict) or call.get("method")!="history":
                    continue
                params=call.get("request",{})
                if not isinstance(params,dict):
                    continue
                symbol=params.get("symbol")
                if not isinstance(symbol,str) or not symbol.endswith("FUT"):
                    continue
                has_fut=True
                metrics["futures_history_calls"]+=1
                # Symbol is from stored market request, not inferred contract identity.
                symbols[symbol]+=1
                response=call.get("response",{})
                candles=response.get("candles",[]) if isinstance(response,dict) else []
                if not isinstance(candles,list):
                    metrics["invalid_history_responses"]+=1
                    continue
                metrics["futures_candles_total"]+=len(candles)
                resolution=params.get("resolution")
                try:
                    minutes=int(resolution)
                except (TypeError,ValueError):
                    metrics["unrecognized_resolution_calls"]+=1
                    continue
                if minutes not in (1,3,5,15):
                    metrics["unrecognized_resolution_calls"]+=1
                    continue
                for bar in candles:
                    good,oi=_valid_close(bar,observed,minutes)
                    metrics["completed_futures_candles"]+=bool(good)
                    metrics["completed_futures_candles_with_positive_oi"]+=bool(oi)
            if has_fut:
                metrics["research_events_with_futures_history"]+=1
        result["counts"]={
            k:metrics[k] for k in (
                "research_events","research_events_with_futures_history",
                "futures_history_calls","futures_candles_total",
                "completed_futures_candles",
                "completed_futures_candles_with_positive_oi",
                "invalid_archived_payloads","invalid_history_responses",
                "unrecognized_resolution_calls")}
        result["counts"]["futures_data_table_rows"]=saved
        result["futures_symbols"]=[{"symbol":s,"call_count":n} for s,n in symbols.most_common(10)]
        if saved==0 and metrics["futures_history_calls"]:
            result["warnings"].append(
                "Futures response(s) are archived in events but not normalized into futures_data; existing live runner does not write this table")
        if not metrics["futures_history_calls"]:
            result["warnings"].append("No archived futures history calls found")
        if not metrics["completed_futures_candles_with_positive_oi"]:
            result["warnings"].append("No completed archived futures candles with positive OI detected")
        result["warnings"].append(
            "Option chain receipt time is not an exchange timestamp; no event.exchange_at_utc is reconstructed")
        result["status"]=(
            "ARCHIVED_FUTURES_WITH_OI" if metrics["completed_futures_candles_with_positive_oi"]
            else "FUTURES_UNVERIFIED")
    return result

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--db",type=Path,required=True)
    p.add_argument("--report",type=Path)
    a=p.parse_args(argv)
    result=audit_archived_futures(a.db)
    summary=json.dumps(result,indent=2,allow_nan=False)
    print(summary)
    if a.report:
        a.report.parent.mkdir(parents=True,exist_ok=True)
        with a.report.open("x",encoding="utf-8") as f:
            f.write(summary+"\n")
        a.report.chmod(0o600)
    return 1 if result["status"]=="FAIL" else 0

if __name__=="__main__":
    raise SystemExit(main())
