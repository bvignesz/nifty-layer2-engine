"""Historical integrity checks on the EXISTING SQLite DB, opened read-only.

This is not a backtest and does not infer missing exchange timestamps. Each
finding includes a precise reason; statuses are explicit, never silent zeroes.
"""
import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3

from .storage import IST
from .market_calendar import session

def _utc(value):
    return datetime.fromisoformat(str(value).replace("Z","+00:00")).astimezone(timezone.utc)

def inspect_db(path):
    path=Path(path).expanduser().resolve()
    if not path.is_file():
        return {"status":"FAIL","checks":{"database_exists":False},"reason":"DB does not exist"}
    report={"status":"FAIL","database":str(path),"checks":{},"metrics":{},
            "warnings":[],"hard_failures":[]}
    with sqlite3.connect(path.as_uri()+"?mode=ro",uri=True,timeout=10) as db:
        db.execute("PRAGMA query_only=ON")
        integrity=db.execute("PRAGMA quick_check").fetchone()[0]
        report["checks"]["sqlite_integrity"]=(integrity=="ok")
        if integrity!="ok":report["hard_failures"].append("SQLite quick_check failed")
        names={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        required={"events","signals","check_results","header_snapshots",
                  "strike_snapshots","futures_data"}
        report["checks"]["schema_present"]=required<=names
        if not required<=names:
            report["hard_failures"].append("Required research tables missing")
            return report
        counts={name:db.execute('SELECT COUNT(*) FROM "'+name+'"').fetchone()[0] for name in required}
        report["metrics"]["table_counts"]=counts
        report["checks"]["records_present"]=(counts["events"]>0 and counts["strike_snapshots"]>0)
        if not report["checks"]["records_present"]:
            report["warnings"].append("Not enough stored events/strikes to validate historical coverage")
        events=db.execute("""SELECT e.event_id,e.observed_at_utc,e.exchange_at_utc,e.kind,
                          e.status,s.classification FROM events e
                          LEFT JOIN signals s ON e.event_id=s.event_id
                          ORDER BY e.observed_at_utc""").fetchall()
        invalid_times=0
        missing_exchange=0
        research_count=0
        no_trade_violations=0
        previous=None
        gaps=0
        for event,received,exchange,kind,status,classification in events:
            if kind not in ("manual_research","scheduled_research"):continue
            research_count+=1
            if classification!="No Trade":no_trade_violations+=1
            try:
                observed=_utc(received)
                if previous and observed.date()==previous.date() and (observed-previous).total_seconds()>360:
                    gaps+=1
                previous=observed
                if exchange:
                    actual=_utc(exchange)
                    if actual>observed or (observed-actual).total_seconds()>180:
                        invalid_times+=1
                else:missing_exchange+=1
            except (ValueError,TypeError):
                invalid_times+=1
        report["metrics"].update(research_events=research_count,
            research_missing_exchange_time=missing_exchange,
            research_invalid_or_stale_exchange_time=invalid_times,
            observation_gaps_over_6min=gaps,
            non_no_trade_classifications=no_trade_violations)
        report["checks"]["research_safety"]=no_trade_violations==0
        if no_trade_violations:
            report["hard_failures"].append("Unvalidated research events classified as trade signals")
        report["checks"]["exchange_timestamp_coverage"]=(research_count>0 and missing_exchange==0 and invalid_times==0)
        if not report["checks"]["exchange_timestamp_coverage"]:
            report["warnings"].append("Exchange timestamps absent/stale/invalid: observed_at is receipt time, not completed candle time")
        bad_strikes=db.execute("""SELECT COUNT(*) FROM strike_snapshots
                           WHERE strike<=0 OR opt_type NOT IN ('CE','PE') OR
                                 oi<0 OR volume<0 OR ltp<0 OR (bid IS NOT NULL AND bid<0)
                                 OR (ask IS NOT NULL AND ask<0)""").fetchone()[0]
        orphan=db.execute("""SELECT COUNT(*) FROM strike_snapshots s
                            LEFT JOIN header_snapshots h ON h.ts=s.ts WHERE h.ts IS NULL""").fetchone()[0]
        repeated_gamma=db.execute("""SELECT COUNT(*) FROM (
                            SELECT ts FROM strike_snapshots
                            WHERE gamma IS NOT NULL GROUP BY ts
                            HAVING COUNT(*)>=10 AND COUNT(DISTINCT gamma)=1)""").fetchone()[0]
        report["metrics"].update(invalid_strike_rows=bad_strikes,
                                 orphan_strike_rows=orphan,
                                 timestamps_with_constant_gamma=repeated_gamma)
        report["checks"]["strike_integrity"]=bad_strikes==0 and orphan==0
        if bad_strikes or orphan:report["hard_failures"].append("Invalid or orphan strike data")
        if repeated_gamma:report["warnings"].append("Repeated constant gamma: audit fallback/units before any GEX conclusions")
        check_counts=db.execute("""SELECT event_id, COUNT(*) FROM check_results
                                  GROUP BY event_id""").fetchall()
        bad_checks=sum(cnt!=18 for _,cnt in check_counts)
        report["metrics"]["events_with_incomplete_18_directional_checks"]=bad_checks
        report["checks"]["nine_checks_recorded"]=(research_count>0 and bad_checks==0)
        if bad_checks:report["warnings"].append("Some check events lack all 18 directional results")
        report["checks"]["historical_model_validated"]=False
        report["warnings"].append("A database integrity audit is not independent model or profitable-trading validation")
    report["status"]="FAIL" if report["hard_failures"] else (
        "REQUIRES_MARKET_VALIDATION" if not report["checks"]["exchange_timestamp_coverage"]
        or not report["checks"]["historical_model_validated"] else "PASS")
    return report

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--db",type=Path,required=True)
    p.add_argument("--report",type=Path)
    args=p.parse_args(argv)
    result=inspect_db(args.db)
    text=json.dumps(result,indent=2,allow_nan=False)
    print(text)
    if args.report:
        args.report.parent.mkdir(parents=True,exist_ok=True)
        with args.report.open("x",encoding="utf-8") as handle:handle.write(text+"\n")
    return 1 if result["status"]=="FAIL" else 0

if __name__=="__main__":
    raise SystemExit(main())
