"""Independent EOD swing setup observables; not replacement for frozen v0.7.

All bars must be ascending completed/adjusted OHLCV, free of future timestamps.
Williams %R and Larry Williams A/D are formula-based indicators, not trading
alpha. POC cannot be computed from EOD daily bars without approximation.
"""
from math import isfinite

def _bars(data):
    if not isinstance(data,list) or len(data)<35:
        raise ValueError("at least 35 completed EOD bars required")
    checked=[]
    last=None
    for r in data:
        day=r["date"]
        if last is not None and day<=last:
            raise ValueError("out-of-order or duplicated EOD date")
        last=day
        o,h,l,c,v=(r[k] for k in ("open","high","low","close","volume"))
        if not all(isinstance(z,(int,float)) and not isinstance(z,bool) and isfinite(z) for z in (o,h,l,c,v)):
            raise ValueError("nonfinite EOD bar")
        if not l>0 or h<l or min(o,c)<l or max(o,c)>h or v<0:
            raise ValueError("invalid EOD bar")
        checked.append((day,float(o),float(h),float(l),float(c),float(v)))
    return checked

def ema(values,window):
    if len(values)<window or window<2:raise ValueError("insufficient EMA data")
    alpha=2/(window+1)
    value=sum(values[:window])/window
    for v in values[window:]:
        value=alpha*v+(1-alpha)*value
    return value

def features(bars):
    rows=_bars(bars)
    close=[b[4] for b in rows]
    hi=max(b[2] for b in rows[-3:])
    lo=min(b[3] for b in rows[-3:])
    wr3=-100*(hi-close[-1])/(hi-lo) if hi>lo else None
    # Larry Williams Accumulation/Distribution: true high/low vs prev close.
    ad=0.
    ad_series=[]
    for i,b in enumerate(rows):
        if i:
            prev=close[i-1]
            true_high=max(b[2],prev)
            true_low=min(b[3],prev)
            if close[i]>prev:step=close[i]-true_low
            elif close[i]<prev:step=close[i]-true_high
            else:step=0.
            ad+=step
        ad_series.append(ad)
    ema10=ema(close,10)
    ema30=ema(close,30)
    recent_low=min(b[3] for b in rows[-5:])
    prev_swing_low=min(b[3] for b in rows[-11:-1])
    previous_resistance=max(b[2] for b in rows[-21:-1])
    # BOF bullish: prior resistance sweep is not a bounce; track distinct
    # prior support sweep and reclaim at close after a day below support.
    support=min(b[3] for b in rows[-21:-1])
    bull_bof=rows[-1][3]<support and rows[-1][4]>support
    breakout=rows[-1][4]>previous_resistance
    return {"date":rows[-1][0],"ema10":ema10,"ema30":ema30,
      "wr3":wr3,"larry_ad":ad,"ad_change_5":ad-ad_series[-6],
      "trend_ema":ema10>ema30,
      "last_close":close[-1],"previous_resistance":previous_resistance,
      "previous_support":support,
      "bull_bof_support_sweep":bull_bof,
      "breakout_close_above_20d":breakout,
      "recent_five_day_low":recent_low,
      "note":"POC/market profile requires separate intraday traded-volume data or an explicitly labeled OHLCV approximation.",
      "research_only":True}
