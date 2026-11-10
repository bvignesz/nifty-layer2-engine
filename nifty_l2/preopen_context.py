"""Pre-open market-context hypothesis, independent of intraday candles.

Inputs must be supplied by trusted timestamped sources, never scraped or
invented in the browser. Conditions are RESEARCH DEFAULTS and have not been
backtested. A source label alone is not proof of authenticity.
"""
from datetime import datetime,timezone
from math import isfinite
from .market_calendar import session,IST

FIELDS=("gift_gap_pct","global_futures_pct","vix_change_pct",
        "fii_futures_ls_ratio","gift_vs_previous_value_area_pct")
def _utc(value):
    t=datetime.fromisoformat(str(value).replace("Z","+00:00"))
    if t.tzinfo is None:raise ValueError("aware quote required")
    return t.astimezone(timezone.utc)

def evaluate_preopen(data,*,now,event_risk=False):
    if now.tzinfo is None:raise ValueError("aware current time required")
    local=now.astimezone(IST)
    try:
        if session(local.date()) is None:
            return {"status":"EXCHANGE_CLOSED","bias":"IGNORE",
                "reason":"NSE F&O session holiday or weekend","research_only":True}
    except ValueError:
        return {"status":"CALENDAR_UNVERIFIED","bias":"IGNORE","research_only":True}
    if event_risk:
        return {"status":"HIGH_IMPACT_EVENT_RISK","bias":"IGNORE","research_only":True}
    if not isinstance(data,dict) or data.get("date_ist")!=local.date().isoformat():
        return {"status":"MISSING_PREOPEN_DATA","bias":"IGNORE","research_only":True}
    if not local.hour<10:
        return {"status":"PREOPEN_WINDOW_PASSED","bias":"IGNORE","research_only":True}
    measures={}
    for key in FIELDS:
        field=data.get(key)
        if not isinstance(field,dict) or field.get("source_verified") is not True:
            return {"status":"MISSING_OR_UNVERIFIED_"+key.upper(),
                "bias":"IGNORE","research_only":True}
        value=field.get("value")
        if (not isinstance(value,(int,float)) or isinstance(value,bool)
             or not isfinite(value)):
            return {"status":"INVALID_"+key.upper(),"bias":"IGNORE","research_only":True}
        try: age=(now-_utc(field["observed_at_utc"])).total_seconds()
        except (ValueError,KeyError,TypeError):
            return {"status":"MISSING_TIMESTAMP","bias":"IGNORE","research_only":True}
        # Prior-session FII numbers are a historical context field; others
        # should be recent pre-open observations.
        max_age=30*3600 if key=="fii_futures_ls_ratio" else 90*60
        if not 0<=age<=max_age:
            return {"status":"STALE_"+key.upper(),"bias":"IGNORE","research_only":True}
        measures[key]=float(value)
    gift=measures["gift_gap_pct"]
    global_risk=measures["global_futures_pct"]
    vix=measures["vix_change_pct"]
    fii=measures["fii_futures_ls_ratio"]
    va=measures["gift_vs_previous_value_area_pct"]
    bull=sum([gift>=.2,global_risk>0,vix<=0,fii>=1.05,va>0])
    bear=sum([gift<=-.2,global_risk<0,vix>=1,fii<.95,va<0])
    bias="BULL" if bull>=4 and bear<=1 else "BEAR" if bear>=4 and bull<=1 else "MIXED"
    return {"status":"PREOPEN_RESEARCH_CONTEXT","bias":bias,
      "bull_factors":bull,"bear_factors":bear,"checked_fields":list(FIELDS),
      "note":"Heuristic pre-open scenario, not a verified predictive edge.",
      "research_only":True,"orders_enabled":False}
