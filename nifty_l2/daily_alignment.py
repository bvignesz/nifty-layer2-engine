"""Completed daily-bar nine-factor context gate for intraday NIFTY options.

These are nine *daily-context factors*, NOT the original nine option-chain
checks. Requires verified day-completed historical OHLCV and benchmark.
Never pretends daily OI walls, dealer inventory, or order-flow are available.
"""
from datetime import date
from math import isfinite
from .storage import IST
from eod_scanner.swing_setup_research import ema,features as swing_features

FACTORS=("CLOSE_ABOVE_EMA10","EMA10_ABOVE_EMA30","CLOSE_ABOVE_SMA200",
 "EMA10_RISING_5D","CLOSE_ABOVE_PREV_20D_MID",
 "RELATIVE_STRENGTH_20D","LARRY_AD_5D_RISING",
 "CLOSE_ABOVE_PREV_CLOSE","POSITIVE_DAILY_CANDLE")

def _bars(rows,*,asof):
    if not isinstance(rows,list) or len(rows)<221:raise ValueError("221 completed daily bars required")
    prev=None
    values=[]
    for row in rows:
        d=date.fromisoformat(row["date"])
        if d>=asof or prev is not None and d<=prev:
            raise ValueError("daily bar must be completed before decision day and ordered")
        if row.get("bar_status")!="COMPLETED" or row.get("source")!="VERIFIED_EOD":
            raise ValueError("daily bar source/completion not verified")
        o,h,l,c,v=(row[k] for k in ("open","high","low","close","volume"))
        if any(not isinstance(x,(int,float)) or isinstance(x,bool) or not isfinite(x) for x in (o,h,l,c,v)):
            raise ValueError("invalid bar values")
        if not (0<l<=min(o,c)<=max(o,c)<=h and v>=0):
            raise ValueError("bad OHLCV")
        values.append((d,float(o),float(h),float(l),float(c),float(v)))
        prev=d
    return values

def evaluate_daily(bars,benchmark,*,asof):
    """Daily features are as-of previous session close, never current-day data."""
    day=date.fromisoformat(asof)
    base=_bars(bars,asof=day)
    bench=_bars(benchmark,asof=day)
    if base[-1][0]!=bench[-1][0]:
        raise ValueError("index and benchmark session mismatch")
    close=[r[4] for r in base]
    benchclose=[r[4] for r in bench]
    e10=ema(close,10)
    e30=ema(close,30)
    sma200=sum(close[-200:])/200
    lag_e10=ema(close[:-5],10)
    mid20=(max(r[2] for r in base[-21:-1])+min(r[3] for r in base[-21:-1]))/2
    rs20=(close[-1]/close[-21])-(benchclose[-1]/benchclose[-21])
    # Larry A/D computed on verified source bars by existing formula.
    sf=swing_features([{"date":str(d),"open":o,"high":h,"low":l,
                        "close":c,"volume":v} for d,o,h,l,c,v in base])
    flags=[
      close[-1]>e10,e10>e30,close[-1]>sma200,e10>lag_e10,
      close[-1]>mid20,rs20>0,sf["ad_change_5"]>0,
      close[-1]>close[-2],close[-1]>base[-1][1]]
    factors=[{"name":n,"bull":"PASS" if f else "FAIL",
      "bear":"PASS" if not f else "FAIL"} for n,f in zip(FACTORS,flags)]
    bull=sum(flags)
    bear=9-bull
    # Daily mixed states must not be forced into bullish or bearish.
    bias="BULL" if bull>=7 else "BEAR" if bear>=7 else "MIXED"
    return {"status":"VERIFIED_PREVIOUS_SESSION_CONTEXT","asof":asof,
      "last_completed_session":base[-1][0].isoformat(),"bias":bias,
      "bull_factors":bull,"bear_factors":bear,"factors":factors,
      "close":close[-1],"ema10":round(e10,3),"ema30":round(e30,3),
      "sma200":round(sma200,3),"rs20_excess":round(rs20,5),
      "note":"Nine DAILY trend/context factors, not the intraday nine OI checks.",
      "research_only":True,"orders_enabled":False}

def alignment_gate(*,premarket,daily,intraday,greeks):
    """Pure final review decision; incomplete source data ALWAYS blocks."""
    states={"BULL","BEAR"}
    if (premarket.get("status")!="VERIFIED" or
        daily.get("status")!="VERIFIED_PREVIOUS_SESSION_CONTEXT" or
        intraday.get("status")!="VERIFIED_COMPLETED_INTRADAY" or
        greeks.get("status")!="VERIFIED_CONTRACT_CONTEXT"):
        return {"status":"UNVERIFIED_LAYERS","verdict":"IGNORE",
            "trade_allowed":False,"reasons":["MISSING_VERIFIED_LAYER"]}
    sides=(premarket.get("bias"),daily.get("bias"),intraday.get("bias"))
    if not all(s in states for s in sides) or len(set(sides))!=1:
        return {"status":"CONFLICTING_TIMEFRAMES","verdict":"IGNORE",
            "trade_allowed":False,"reasons":["DIRECTION_DISAGREEMENT"]}
    if greeks.get("direction")!=sides[0] or greeks.get("quote_fresh") is not True:
        return {"status":"GREEKS_NOT_ALIGNED","verdict":"IGNORE",
            "trade_allowed":False,"reasons":["OPTION_CONTRACT_MISMATCH_OR_STALE"]}
    return {"status":"ALIGNED_RESEARCH","verdict":sides[0]+" WATCH",
        "trade_allowed":False,
        "reasons":["MANUAL_REVIEW_ONLY_NO_VALIDATED_ORDER_PERMISSION"],
        "research_only":True}
