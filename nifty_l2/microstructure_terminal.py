"""Read-only video-style NIFTY microstructure terminal from stored SQLite data.

An observation is NOT a completed price candle. Option-chain OI has receipt
time, not independently verified exchange update time. Per-leg volume is
cumulative; deltas are computed only for identical contracts within a bounded
same-day observation gap. Dealer identity, net writing, one-minute GEX changes
and true exchange-time option candle closes are not available here.
"""
from datetime import date,datetime,time,timedelta,timezone
from html import escape
import json
from pathlib import Path
import sqlite3
from .storage import IST

def _num(v, decimals=0):
    if v is None:return "—"
    try:return f"{float(v):,.{decimals}f}"
    except (ValueError,TypeError,OverflowError):return "—"

def read_rows(directory,day,limit=40):
    target=date.fromisoformat(day)
    limit=int(limit)
    if not 1<=limit<=120:raise ValueError("limit out of bounds")
    start=int(datetime.combine(target,time.min,IST).timestamp())
    stop=int(datetime.combine(target+timedelta(days=1),time.min,IST).timestamp())
    path=Path(directory)/"research.db"
    result={"status":"NO_DATA","date_ist":day,"rows":[],"version":1,
            "cadence":"stored receipts; nominal collection interval 3 minutes",
            "exchange_time_verified":False,"option_one_minute_delta_available":False}
    if not path.is_file():return result
    with sqlite3.connect(path.resolve().as_uri()+"?mode=ro",uri=True,timeout=5) as db:
        db.execute("PRAGMA query_only=ON")
        headers=db.execute("""SELECT ts,ist_time,spot,fut_close,fut_vwap,fut_oi,expiry_date
             FROM header_snapshots WHERE ts>=? AND ts<? ORDER BY ts DESC LIMIT ?""",
             (start,stop,limit+1)).fetchall()
        if not headers:return result
        times=[h[0] for h in headers]
        symbols=','.join('?' for _ in times)
        raw=db.execute("""SELECT ts,strike,opt_type,symbol,oi,volume,ltp,gamma
             FROM strike_snapshots WHERE ts IN ("""+symbols+""")
             ORDER BY ts DESC,strike,opt_type""",times).fetchall()
        by_time={}
        for ts,strike,side,symbol,oi,vol,ltp,gamma in raw:
            by_time.setdefault(ts,{})[(str(strike),side)]={
                "strike":int(strike),"side":side,"symbol":symbol,
                "oi":oi,"volume_cumulative":vol,"ltp":ltp,"gamma":gamma}
        # Use only saved classifications; never promote the legacy verdict.
        begin=datetime.fromtimestamp(start,timezone.utc).isoformat()
        finish=datetime.fromtimestamp(stop,timezone.utc).isoformat()
        signals=db.execute("""SELECT e.observed_at_utc,s.classification,s.payload_json
               FROM events e JOIN signals s ON s.event_id=e.event_id
               WHERE e.observed_at_utc>=? AND e.observed_at_utc<?
               ORDER BY e.observed_at_utc""",(begin,finish)).fetchall()
    tagged=[]
    for stamp,classification,raw_state in signals:
        try:
            t=datetime.fromisoformat(stamp.replace("Z","+00:00")).timestamp()
            state=json.loads(raw_state)
            tagged.append((t,classification,state))
        except (ValueError,TypeError):
            continue
    previous={}
    for index,h in enumerate(headers[:-1] if len(headers)>limit else headers):
        ts,ist_time,spot,fut_close,fut_vwap,fut_oi,expiry=h
        legs=by_time.get(ts,{})
        calls=[x for x in legs.values() if x["side"]=="CE" and isinstance(x["oi"],(int,float)) and x["oi"]>0]
        puts=[x for x in legs.values() if x["side"]=="PE" and isinstance(x["oi"],(int,float)) and x["oi"]>0]
        ce=max(calls,key=lambda x:x["oi"]) if calls else None
        pe=max(puts,key=lambda x:x["oi"]) if puts else None
        old_ts=headers[index+1][0] if index+1<len(headers) else None
        old=by_time.get(old_ts,{}) if old_ts is not None else {}
        gap=ts-old_ts if old_ts is not None else None
        comparable=(gap is not None and 90<=gap<=360
                    and datetime.fromtimestamp(old_ts,IST).date()==target)
        def deltas(leg):
            if not comparable or leg is None:return {"oi_delta":None,"volume_increment":None}
            ref=old.get((str(leg["strike"]),leg["side"]))
            if ref is None or ref["symbol"]!=leg["symbol"]:
                return {"oi_delta":None,"volume_increment":None}
            o,v=leg["oi"],leg["volume_cumulative"]
            oi_delta=o-ref["oi"] if o is not None and ref["oi"] is not None else None
            dv=v-ref["volume_cumulative"] if v is not None and ref["volume_cumulative"] is not None else None
            # Volume must be monotonic for a same-session cumulative metric.
            return {"oi_delta":oi_delta,"volume_increment":dv if dv is not None and dv>=0 else None}
        ce_delta=deltas(ce)
        pe_delta=deltas(pe)
        nearest=min(tagged,key=lambda r:abs(r[0]-ts)) if tagged else None
        if nearest and abs(nearest[0]-ts)<=30:
            classification,state=nearest[1],nearest[2]
            meta=state.get("meta",{}) if isinstance(state,dict) else {}
            bias=state.get("final_verdict","UNAVAILABLE")
            bull=meta.get("bull_score")
            bear=meta.get("bear_score")
            gex=meta.get("gex")
        else:
            classification="No Trade";bias="UNAVAILABLE";bull=bear=gex=None
        if classification not in ("Bullish","Bearish","No Trade"):
            classification="No Trade"
        result["rows"].append({
          "observed_at_ist":datetime.fromtimestamp(ts,IST).isoformat(),
          "observed_epoch":ts,"expiry":expiry,"spot":spot,
          "futures_close_stored":fut_close,"futures_vwap_stored":fut_vwap,
          "futures_oi_stored":fut_oi,
          "futures_price_vs_vwap":("ABOVE" if fut_close>fut_vwap else "BELOW" if fut_close<fut_vwap else "EQUAL")
             if isinstance(fut_close,(int,float)) and isinstance(fut_vwap,(int,float)) and fut_vwap>0 else "UNAVAILABLE",
          "ce_wall":ce,"pe_wall":pe,
          "ce_wall_delta":ce_delta,"pe_wall_delta":pe_delta,
          "snapshot_gap_seconds":gap,"contract_delta_comparable":comparable,
          "legacy_research_bias":bias,"bull_checks":bull,"bear_checks":bear,
          "legacy_gex_scenario":gex,"validated_classification":classification,
          "seller_identity_observed":False,"gex_units_verified":False,
          "one_minute_candle_verified":False})
    result["status"]="AVAILABLE" if result["rows"] else "NO_DATA"
    return result

def render(data):
    def td(value,kind=""):
        return '<td'+(' class="'+kind+'"' if kind else '')+'>'+escape(str(value))+'</td>'
    rows=[]
    for r in data["rows"]:
        when=datetime.fromisoformat(r["observed_at_ist"]).strftime("%H:%M:%S")
        ce,pe=r["ce_wall"],r["pe_wall"]
        def wall(x,delta):
            if x is None:return "Unavailable"
            return (str(x["strike"])+" "+x["side"]+" | OI "+_num(x["oi"])
              +" | ΔOI "+_num(delta["oi_delta"])+" | ΔVol "+_num(delta["volume_increment"]))
        def cls(bias):
            return "up" if bias in ("BULL","BULLISH") else "down" if bias in ("BEAR","BEARISH") else ""
        cells=[
            td(when+" IST | RECEIPT", "time"),
            td(str(r["legacy_research_bias"])+" | B:"+str(r["bull_checks"] or "—")
               +" / S:"+str(r["bear_checks"] or "—"),cls(r["legacy_research_bias"])),
            td(wall(pe,r["pe_wall_delta"])),
            td(wall(ce,r["ce_wall_delta"])),
            td(_num(r["legacy_gex_scenario"],2)+" | MODEL SCENARIO"),
            td("ΔOI proxy only; seller identity unavailable"),
            td("Fut "+_num(r["futures_close_stored"],2)+
               " | VWAP "+_num(r["futures_vwap_stored"],2)+
               " | OI "+_num(r["futures_oi_stored"])),
            td("NO TRADE | unvalidated","neutral")]
        rows.append("<tr>"+''.join(cells)+"</tr>")
    title="PRO TRADER ACADEMY · NIFTY MICROSTRUCTURE"
    style="""body{margin:0;background:#09111f;color:#d8e7f7;font:13px system-ui}
main{padding:20px;max-width:1900px;margin:auto}h1{font-size:20px}
a{color:#87b9ff}.meta{color:#a8b8d0}
.panel{background:#101d32;border:1px solid #283b53;border-radius:12px;padding:16px}
.scroll{overflow:auto;max-height:75vh}
table{border-collapse:collapse;min-width:1510px;width:100%;font:12px ui-monospace,monospace}
th,td{padding:13px 11px;border:1px solid #293d58;text-align:left;vertical-align:top}
th{background:#13243b;position:sticky;top:0;color:#b9cbe1;z-index:2}
td:first-child,th:first-child{position:sticky;left:0;background:#13233a;z-index:3}
.up{color:#47daac}.down{color:#ff8b95}.neutral{color:#f3c478}.time{color:#b5cffe}
small{display:block;margin:10px 0;color:#9cacc5}
nav{margin:12px 0}"""
    header='<nav><a href="/">Home</a> · <a href="/research">Nine checks</a> · <a href="/validation">Validation</a></nav>'
    explanation=('<p class="meta">One row per stored observation (nominal 3-minute collection), '
       'NOT a completed one-minute option candle. OI and volume changes require '
       'matching symbols and a 90–360 second receipt gap. Futures OI quadrant and '
       'seller/buyer identity are not independently established. GEX is a model scenario.</p>')
    heads=("Observed receipt","Legacy bias","PE wall / change","CE wall / change",
        "GEX scenario","Writing / seller exit","Futures snapshot","Validated action")
    table='<div class="scroll"><table><thead><tr>'+''.join("<th>"+escape(h)+"</th>" for h in heads)+'</tr></thead><tbody>'
    table+=''.join(rows) or '<tr><td colspan="8">No stored observations for the selected date</td></tr>'
    table+='</tbody></table></div>'
    return '<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>'+title+'</title><style>'+style+'</style><main>'+header+'<h1>'+title+'</h1><div class="panel"><form method="get" action="/microstructure"><label>Date (IST) <input type="date" name="date" value="'+escape(data["date_ist"],quote=True)+'"></label> <button>Load</button></form>'+explanation+table+'<small>Saved data only · no executable trading signals · original nine-check calculations unchanged</small></div></main></html>'
