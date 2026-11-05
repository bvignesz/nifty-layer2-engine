"""Read-only versioned views of stored research results. No model calculations."""
from datetime import date, datetime, time, timedelta, timezone
import json
from pathlib import Path
import sqlite3
from .storage import IST

def _db(directory):
    p = Path(directory) / "research.db"
    return sqlite3.connect(p.resolve().as_uri()+"?mode=ro",uri=True,timeout=5) if p.is_file() else None

def _day(day):
    d=date.fromisoformat(day)
    a=datetime.combine(d,time.min,IST).astimezone(timezone.utc)
    b=datetime.combine(d+timedelta(days=1),time.min,IST).astimezone(timezone.utc)
    return (a.isoformat(timespec="microseconds").replace("+00:00","Z"),
            b.isoformat(timespec="microseconds").replace("+00:00","Z"),
            int(a.timestamp()),int(b.timestamp()))

def research_history(directory,day,limit=40):
    limit=int(limit)
    if not 1<=limit<=120: raise ValueError("Invalid limit")
    a,b,_,_=_day(day)
    result={"version":1,"day_ist":day,"status":"NO_DATA","rows":[]}
    conn=_db(directory)
    if conn is None: return result
    try:
        rows=conn.execute("""SELECT e.event_id,e.observed_at_utc,e.exchange_at_utc,e.status,
          e.kind,s.classification,s.payload_json FROM events e
          JOIN signals s ON e.event_id=s.event_id
          WHERE e.observed_at_utc>=? AND e.observed_at_utc<?
          AND e.kind IN ('scheduled_research','manual_research')
          ORDER BY e.observed_at_utc DESC LIMIT ?""",(a,b,limit)).fetchall()
        for eid,observed,exchange,quality,kind,classification,payload in rows:
            state=json.loads(payload)
            meta=state.get("meta") if isinstance(state.get("meta"),dict) else {}
            audit=state.get("layer2_audit") if isinstance(state.get("layer2_audit"),dict) else {}
            checks=state.get("scorecard") if isinstance(state.get("scorecard"),list) else []
            result["rows"].append({
                "event_id":eid,"observed_at_utc":observed,"exchange_at_utc":exchange,
                "quality_status":quality,"kind":kind,"classification":classification,
                "research_only":True,"original_verdict":state.get("final_verdict"),
                "meta":{k:meta.get(k) for k in ("spot","fut_close","fut_sym",
                    "fut_vwap","put_wall","call_wall","gex","gamma_flip",
                    "vex_cex","seller_lead","bull_score","bear_score","data_mode")},
                "scenario":{k:audit.get(k) for k in ("gex_units","vex_units",
                    "cex_units","freshness_ok","no_trade_reasons")},
                "checks":[{"number":i,"name":r.get("Check"),"bull":r.get("Bull_Status"),
                    "bear":r.get("Bear_Status")} for i,r in enumerate(checks[:9],1)
                    if isinstance(r,dict)]})
        result["status"]="AVAILABLE" if rows else "NO_DATA"
    finally: conn.close()
    return result

def expiry_matrix(directory,day,strike):
    strike=int(strike)
    if not 1<=strike<=200000: raise ValueError("Invalid strike")
    _,_,a,b=_day(day)
    result={"version":1,"day_ist":day,"strike":strike,"status":"NO_DATA",
            "rows":[],"note":"Only actual saved expiries are shown; unavailable ones are omitted."}
    conn=_db(directory)
    from .expiry_archive import read_archive
    archive_rows=read_archive(directory,day,strike)
    if archive_rows:
        result["rows"]=archive_rows
        result["status"]="AVAILABLE"
        result["source"]="separate_multi_expiry_archive"
        return result
    if conn is None:return result
    try:
        rows=conn.execute("""SELECT h.expiry_date,s.opt_type,s.ts,s.symbol,
             s.ltp,s.bid,s.ask,s.oi,s.volume,s.iv,s.delta,s.gamma,s.theta,s.vega
             FROM strike_snapshots s JOIN header_snapshots h ON h.ts=s.ts
             WHERE s.ts>=? AND s.ts<? AND s.strike=?
             ORDER BY s.ts DESC LIMIT 500""",(a,b,strike)).fetchall()
        seen=set()
        for r in rows:
            expiry,side,ts,symbol,ltp,bid,ask,oi,volume,iv,delta,gamma,theta,vega=r
            if not expiry or side not in ("CE","PE") or (expiry,side) in seen:continue
            seen.add((expiry,side))
            result["rows"].append(dict(expiry=expiry,side=side,ts=ts,
                observed_at_ist=datetime.fromtimestamp(ts,IST).isoformat(),
                symbol=symbol,ltp=ltp,bid=bid,ask=ask,oi=oi,
                cumulative_volume=volume,iv=iv,delta=delta,gamma=gamma,
                theta=theta,vega=vega,quality="UNVERIFIED"))
        result["status"]="AVAILABLE" if seen else "NO_DATA"
    finally:conn.close()
    return result

def readiness(directory):
    conn=_db(directory)
    if conn is None:return {"status":"NO_DATABASE","research_events":0,
                              "outcomes_valid":0,"ml_training_ready":False}
    try:
        events=conn.execute("SELECT count(*) FROM events WHERE kind IN ('scheduled_research','manual_research')").fetchone()[0]
        outcomes=conn.execute("SELECT count(*) FROM outcomes WHERE status='VALID'").fetchone()[0]
        return {"status":"RESEARCH_ONLY","research_events":events,"outcomes_valid":outcomes,
                "ml_training_ready":False,"eod_ready":False,
                "note":"Validation of exchange timestamps and future labels is pending."}
    finally:conn.close()
