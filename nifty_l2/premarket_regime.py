"""Pre-market and intraday NIFTY regime context from explicitly supplied observations.

No network API calls or automatic orders. News/calendar/FII fields remain
external timestamped inputs; absent fields are not inferred or invented.
"""
from math import isfinite

def _finite(x):
    return isinstance(x,(int,float)) and not isinstance(x,bool) and isfinite(x)

def classify_regime(*,spot,previous_value_high,previous_value_low,
    opening_high=None,opening_low=None,futures_price=None,futures_vwap=None,
    vix_now=None,vix_prior=None,scheduled_event=False,
    quotes_fresh=False,completed_bar_verified=False):
    numbers=(spot,previous_value_high,previous_value_low)
    if not all(_finite(x) and x>0 for x in numbers):
        return {"regime":"DATA_UNVERIFIED","bias":"IGNORE",
            "reasons":["INVALID_PRICE_OR_VALUE_AREA"],"research_only":True}
    if previous_value_high<previous_value_low:
        raise ValueError("VAH below VAL")
    reasons=[]
    if not quotes_fresh:reasons.append("STALE_QUOTES")
    if not completed_bar_verified:reasons.append("UNVERIFIED_COMPLETED_BAR")
    if any(not _finite(x) or x<=0 for x in
       (opening_high,opening_low,futures_price,futures_vwap,vix_now,vix_prior)):
        reasons.append("MISSING_REGIME_INPUTS")
    if reasons:
        return {"regime":"DATA_UNVERIFIED","bias":"IGNORE",
            "reasons":reasons,"research_only":True}
    if opening_high<opening_low:
        raise ValueError("Opening high below low")
    delta_vix=(vix_now/vix_prior-1)*100
    if scheduled_event:
        return {"regime":"EVENT_VOLATILITY","bias":"IGNORE",
                "vix_change_pct":round(delta_vix,3),
                "reasons":["SCHEDULED_EVENT"],"research_only":True}
    up=(spot>max(previous_value_high,opening_high)
        and futures_price>futures_vwap)
    down=(spot<min(previous_value_low,opening_low)
        and futures_price<futures_vwap)
    if up:
        regime,bias="TREND_EXPANSION","BULLISH_RESEARCH"
    elif down:
        regime,bias="TREND_EXPANSION","BEARISH_RESEARCH"
    else:
        regime,bias="RANGE_OR_MIXED","IGNORE"
    return {"regime":regime,"bias":bias,
      "vix_change_pct":round(delta_vix,3),
      "reasons":[],"research_only":True,
      "note":"Regime is a rule-based context hypothesis; not validated trade profitability."}
