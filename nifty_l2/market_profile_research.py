"""Deterministic price-volume profile and opening-range research indicators.

For OHLCV bars, traded volume-by-price is not observed. Uniform distribution
over crossed bins is an EXPLICIT approximation, NOT tick-accurate volume profile.
No lookahead: caller must supply fully completed, timestamp-valid session bars.
No trading/order logic.
"""
from math import floor,isfinite

def _number(x, *, positive=False):
    try:
        y=float(x)
        if not isfinite(y) or (positive and y<=0):
            raise ValueError("invalid number")
        return y
    except (ValueError,TypeError,OverflowError):
        raise ValueError("invalid OHLCV or parameter") from None

def _bars(records):
    checked=[]
    seen=set()
    for bar in records:
        stamp=bar["ts"]
        if stamp in seen:raise ValueError("duplicate candle timestamp")
        seen.add(stamp)
        low=_number(bar["low"])
        high=_number(bar["high"])
        op=_number(bar["open"])
        close=_number(bar["close"])
        vol=_number(bar["volume"])
        if low<=0 or high<low or vol<0 or not(low<=op<=high and low<=close<=high):
            raise ValueError("invalid OHLCV")
        checked.append(dict(ts=stamp,open=op,high=high,low=low,close=close,volume=vol))
    if not checked:raise ValueError("no completed bars")
    stamps=[r["ts"] for r in checked]
    if stamps!=sorted(stamps):raise ValueError("candles out of order")
    return checked

def approximate_volume_profile(bars, *, tick_size=1.0,value_area_fraction=.70):
    """Uniformly apportion OHLCV volume to all intersected price bins.

    Output POC/VAH/VAL are approximate; use exchange ticks for true VAP.
    Value area grows contiguously from POC by comparing adjacent bin volumes.
    """
    if not (0<_number(value_area_fraction)<1):raise ValueError("bad value area")
    tick=_number(tick_size,positive=True)
    if len(bars)>20000:raise ValueError("too many bars")
    records=_bars(bars)
    levels={}
    for b in records:
        lo=floor(b["low"]/tick+1e-9)
        hi=floor(b["high"]/tick+1e-9)
        if hi-lo>10000:raise ValueError("too many price levels")
        weight=b["volume"]/(hi-lo+1)
        for level in range(lo,hi+1):
            levels[level]=levels.get(level,0.0)+weight
    if len(levels)>25000:raise ValueError("too many profile bins")
    total=sum(levels.values())
    if total<=0:raise ValueError("no traded volume")
    # Tie-break POC toward the volume-weighted central bin.
    center=sum(k*v for k,v in levels.items())/total
    poc=min(levels,key=lambda k:(-levels[k],abs(k-center),k))
    target=total*_number(value_area_fraction)
    left=right=poc
    included=levels[poc]
    while included+1e-10<target and (left>min(levels) or right<max(levels)):
        lv=levels.get(left-1,-1)
        rv=levels.get(right+1,-1)
        if lv>=rv and lv>=0:
            left-=1
            included+=lv
        elif rv>=0:
            right+=1
            included+=rv
        else:break
    return {
      "status":"APPROXIMATE_FROM_OHLCV",
      "poc":round(poc*tick,8),"vah":round(right*tick,8),
      "val":round(left*tick,8),
      "value_area_fraction":value_area_fraction,
      "coverage_fraction":included/total,
      "total_volume":total,
      "bin_count":len(levels),"bar_count":len(records),
      "method":"UNIFORM_OHLCV_RANGE_ALLOCATION",
      "tick_accurate":False,"research_only":True,
      "note":"Not exchange volume-at-price: each candle's volume is spread uniformly over its traded range."
    }

def opening_range(completed_bars, *, end_epoch, start_epoch):
    """Opening range from bars with explicit epoch start and interval seconds.

    Rejects bars overlapping either boundary to prevent partial bar lookahead.
    Caller must supply an exchange session calendar and verified completed bars.
    """
    bars=_bars(completed_bars)
    start=int(start_epoch)
    end=int(end_epoch)
    if end<=start:raise ValueError("invalid range boundaries")
    selected=[]
    for bar in bars:
        ts=int(bar["ts"])
        seconds=int(next(b["seconds"] for b in completed_bars if b["ts"]==bar["ts"]))
        if seconds<=0:raise ValueError("invalid candle interval")
        if ts<end and ts+seconds>start and not (ts>=start and ts+seconds<=end):
            raise ValueError("partial bar overlaps opening-range boundary")
        if start<=ts and ts+seconds<=end:selected.append(bar)
    if not selected:raise ValueError("missing opening-range candles")
    return {"high":max(b["high"] for b in selected),
            "low":min(b["low"] for b in selected),
            "observed_bars":len(selected),
            "status":"COMPLETED_PRICE_BARS_ONLY"}
