"""Human-review Telegram message formatter; no network or auto-orders.

Use only as input to an explicitly configured Telegram notifier in future.
Never send auth tokens, raw broker payloads or unverified BUY instructions.
"""
from datetime import datetime

def format_research_alert(observation):
    if not isinstance(observation,dict):raise ValueError("observation dict required")
    allowed=("BULL","BEAR","NO TRADE","UNAVAILABLE")
    bias=observation.get("legacy_research_bias","UNAVAILABLE")
    if bias not in allowed:bias="UNAVAILABLE"
    ts=observation.get("observed_at_ist")
    try:
        clock=datetime.fromisoformat(ts).strftime("%d %b %Y %H:%M:%S IST")
    except (TypeError,ValueError):
        clock="timestamp unavailable"
    def wall(key):
        value=observation.get(key)
        if not isinstance(value,dict):return "unavailable"
        strike=value.get("strike")
        side=value.get("side")
        if not isinstance(strike,(int,float)) or side not in ("CE","PE"):
            return "unavailable"
        return str(strike)+" "+side
    spot=observation.get("spot")
    if not isinstance(spot,(int,float)) or isinstance(spot,bool):
        spot="unavailable"
    msg=("\U0001f4ca NIFTY OPTIONS RESEARCH | "+clock+
      "\nBias: "+bias+" (unvalidated nine-check hypothesis)"+
      "\nSpot: "+str(spot)+
      "\nPE wall: "+wall("pe_wall")+
      "\nCE wall: "+wall("ce_wall")+
      "\nFutures: "+str(observation.get("futures_observation_quadrant","UNAVAILABLE"))+
      "\nAction: WATCH / IGNORE only; manual review required."+
      "\nOption OI receipt time is NOT exchange-confirmed 1m OHLC."+
      "\nNo automatic orders. Not financial advice.")
    if len(msg)>1600:raise ValueError("message too large")
    return msg
