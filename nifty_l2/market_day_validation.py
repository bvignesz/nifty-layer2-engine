"""Market-hours evidence audit of isolated FYERS market_feed.db.

Never turns receipt timestamps into option exchange timestamps. A favorable
report proves collection coverage only, not strategy edge or account access
unless this script was actually run on AWS with live broker evidence.
"""
import argparse,json,sqlite3
from datetime import date,datetime,time,timedelta,timezone
from pathlib import Path
from .storage import IST

def market_day_report(db_path,day):
    d=date.fromisoformat(day)
    start=datetime.combine(d,time(9,15),IST).astimezone(timezone.utc)
    end=datetime.combine(d,time(15,30),IST).astimezone(timezone.utc)
    path=Path(db_path).expanduser().resolve()
    result={"date_ist":day,"status":"NO_FEED",
      "receipt_count":0,"completed_futures_1m_count":0,
      "receipt_gap_over_6m":0,"missing_option_chain_receipts":0,
      "option_oi_exchange_timestamp_verified":False,
      "full_1m_option_oi_coverage":False,
      "strategy_proven_profitable":False,
      "research_only":True,"orders_enabled":False}
    if path.name!="market_feed.db" or not path.is_file():
        return result
    a,b=start.isoformat(),end.isoformat()
    with sqlite3.connect(path.as_uri()+"?mode=ro",uri=True,timeout=5) as db:
        receipts=db.execute("""SELECT receipt_utc,json_data,state FROM feed_receipts
          WHERE receipt_utc>=? AND receipt_utc<? ORDER BY receipt_utc""",(a,b)).fetchall()
        future=db.execute("""SELECT ts,symbol,close,oi FROM feed_future_bars
          WHERE ts>=? AND ts<? ORDER BY symbol,ts""",
          (int(start.timestamp()),int(end.timestamp()))).fetchall()
    result["receipt_count"]=len(receipts)
    result["completed_futures_1m_count"]=len(future)
    intervals=[]
    prior=None
    status_counts={}
    for stamp,raw,state in receipts:
        status_counts[state]=status_counts.get(state,0)+1
        t=datetime.fromisoformat(stamp)
        if prior is not None:
            interval=(t-prior).total_seconds()
            intervals.append(interval)
        prior=t
        try:
            obj=json.loads(raw)
            if not obj.get("options",{}).get("legs"):
                result["missing_option_chain_receipts"]+=1
        except (TypeError,ValueError):
            result["missing_option_chain_receipts"]+=1
    result["receipt_gap_over_6m"]=sum(x>360 for x in intervals)
    result["max_receipt_gap_seconds"]=round(max(intervals),2) if intervals else None
    result["future_status_counts"]=status_counts
    result["status"]=("NO_REGULAR_SESSION_DATA" if not receipts else
       "RESEARCH_FEED_RECOVERED" if len(receipts)>=80 and
       len(future)>=200 and result["receipt_gap_over_6m"]<=5 and
       result["missing_option_chain_receipts"]==0 else "MARKET_VALIDATION_INCOMPLETE")
    result["limitations"]=[
       "FYERS option-chain OI exchange timestamps have not been independently verified.",
       "Receipt sampling interval is at least three minutes, not exchange-synced 1m option OI.",
       "Market-day feed completeness is not options strategy profitability.",
       "Historical option fill slippage and underlying-quantity assumptions remain model-dependent."]
    return result

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--db",type=Path,required=True)
    p.add_argument("--date",required=True)
    args=p.parse_args(argv)
    report=market_day_report(args.db,args.date)
    print(json.dumps(report,indent=2,allow_nan=False))
    return 0 if report["status"]=="RESEARCH_FEED_RECOVERED" else 2

if __name__=="__main__":
    raise SystemExit(main())
