"""Research-only latest broker feed presentation. No fabricated synchronization.

Futures completed exchange candle and optionchain receipt are independent.
OI wall cut uses only comparable exact-symbol receipt observations. The
probable GEX scenario is explicitly conditional on raw OI unit assumptions.
"""
from datetime import datetime,timezone
from html import escape
from pathlib import Path
import json,sqlite3
from .live_feed import latest_feed

def signed_gamma_scenario(legs,future_price,*,oi_unit=None,lot_size=None):
    """Signed-OI *scenario*, not observed dealer exposure; requires explicit unit assumption."""
    from math import isfinite
    if oi_unit not in ("underlying_units","contracts") or not isinstance(future_price,(int,float)) or future_price<=0:
        return {"status":"OI_UNITS_AND_DEALER_SIGN_UNVERIFIED"}
    if oi_unit=="contracts" and not (isinstance(lot_size,int) and lot_size>0):
        return {"status":"MISSING_VERIFIED_LOT_SIZE"}
    n=0
    sums={"CE":0.0,"PE":0.0}
    for leg in legs:
        side=leg.get("side")
        gamma=leg.get("gamma")
        oi=leg.get("oi")
        if side not in sums or not all(isinstance(x,(float,int)) and not isinstance(x,bool)
            and isfinite(x) and x>=0 for x in (gamma,oi)):
            continue
        multiplier=lot_size if oi_unit=="contracts" else 1
        sums[side]+=gamma*oi*multiplier
        n+=1
    if n==0:return {"status":"MISSING_GAMMA_INPUTS"}
    k=.01*future_price*future_price/1e7
    return {"status":"SIGNED_OI_SCENARIO","ce_gex_cr_per_1pct":sums["CE"]*k,
       "pe_gex_cr_per_1pct":-sums["PE"]*k,
       "net_gex_cr_per_1pct":(sums["CE"]-sums["PE"])*k,
       "legs_with_greeks":n,"oi_unit_assumption":oi_unit,
       "dealer_inventory_observed":False,"research_only":True}

def live_readmodel(directory,*,now=None,oi_unit=None,lot_size=None):
    now=now or datetime.now(timezone.utc)
    if now.tzinfo is None:raise ValueError("aware clock")
    path=Path(directory)/"market_feed.db"
    latest=latest_feed(path)
    base={"status":latest["status"],"observed_receipt":None,
      "freshness_seconds":None,"ce_wall":None,"pe_wall":None,
      "futures_1m":None,"gex":{"status":"OI_UNITS_AND_DEALER_SIGN_UNVERIFIED"},
      "oi_delta_basis":"ONLY_MATCHED_EXACT_CONTRACT_RECEIPT_PAIRS",
      "oi_synchronized_with_futures":False,"orders_enabled":False}
    if latest["status"]!="RECORDED":return base
    packet=latest["receipt"]
    recv=datetime.fromisoformat(packet["receipt_utc"].replace("Z","+00:00"))
    age=(now-recv.astimezone(timezone.utc)).total_seconds()
    base.update(observed_receipt=packet["receipt_utc"],
                freshness_seconds=round(age,1),
                status="LIVE_RECEIPT" if 0<=age<=300 else "STALE_OR_FUTURE_RECEIPT")
    opts=packet["options"]["legs"]
    def wall(side):
        legs=[l for l in opts if l["side"]==side and
              isinstance(l.get("oi"),(int,float)) and l["oi"]>0]
        return max(legs,key=lambda x:x["oi"]) if legs else None
    base["ce_wall"]=wall("CE")
    base["pe_wall"]=wall("PE")
    f=packet["futures"]
    if f.get("status")=="VALIDATED_1M_FUTURES":
        bars=f["rows"]
        bars=[b for b in bars if
            datetime.fromisoformat(b["bar_close_utc"])<=recv]
        if bars:
            base["futures_1m"]=bars[-1]
    if base["futures_1m"] is not None:
        base["gex"]=signed_gamma_scenario(opts,base["futures_1m"]["close"],
            oi_unit=oi_unit,lot_size=lot_size)
    if not path.exists():return base
    with sqlite3.connect(path.resolve().as_uri()+"?mode=ro",uri=True,timeout=5) as db:
        old=db.execute("SELECT json_data FROM feed_receipts WHERE receipt_utc<? ORDER BY receipt_utc DESC LIMIT 1",
                      (packet["receipt_utc"],)).fetchone()
    previous=json.loads(old[0]) if old else None
    deltas={}
    interval=None
    if previous and previous["expiry_id"]==packet["expiry_id"]:
        prior=datetime.fromisoformat(previous["receipt_utc"].replace("Z","+00:00"))
        interval=(recv-prior).total_seconds()
        if 60<=interval<=360 and recv.date()==prior.date():
            prevlegs={x["symbol"]:x for x in previous["options"]["legs"]}
            for side,key in (("CE","ce_wall"),("PE","pe_wall")):
                wallrow=base[key]
                pre=prevlegs.get(wallrow["symbol"]) if wallrow else None
                if pre and isinstance(wallrow.get("oi"),(int,float)) and isinstance(pre.get("oi"),(int,float)):
                    deltas[key]=wallrow["oi"]-pre["oi"]
    base["wall_oi_delta"]=deltas
    base["receipt_gap_seconds"]=interval
    return base

def render_live_feed(payload):
    def val(x):
        return escape(str(x)) if x is not None else "Unavailable"
    def wall(side):
        w=payload[side]
        if not w:return "Unavailable"
        return val(w["strike"])+" "+val(w["side"])+" | OI "+val(w.get("oi"))+" | LTP "+val(w.get("ltp"))
    f=payload["futures_1m"]
    future=(val(f["symbol"])+" | completed "+val(f["bar_close_utc"])+" | Close "+val(f["close"])+" | OI "+val(f["oi"])) if f else "Unavailable"
    return ('<section style="margin:12px 0;padding:16px;background:#0f1b2e;border:1px solid #34445b;border-radius:10px">'
     '<h2>FYERS MARKET FEED · LAST STORED RECEIPT</h2>'
     '<p>State: <strong>'+val(payload["status"])+'</strong> · Receipt age: '+val(payload["freshness_seconds"])+'s</p>'
     '<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:10px">'
     '<div>PE wall<br><strong>'+wall("pe_wall")+'</strong></div>'
     '<div>CE wall<br><strong>'+wall("ce_wall")+'</strong></div>'
     '<div>Completed 1m futures<br><strong>'+future+'</strong></div>'
     '<div>GEX<br><strong>'+val(payload["gex"]["status"])+'</strong></div>'
     '</div><p>Options OI is a REST receipt, not exchange-synchronized 1-minute OI. '
     'GEX cannot be scaled reliably without verified quantity units and assumed dealer signs. '
     'No trading orders are placed.</p></section>')
