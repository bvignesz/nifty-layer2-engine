"""Point-in-time NIFTY 500 swing research: returns, momentum ranking, risk.
No stock universes or historical constituents are guessed. Caller must provide
verified as-of constituent set and adjusted EOD price histories. No orders.
"""
from math import isfinite,sqrt
from statistics import pstdev

def _prices(rows,as_of):
    if not isinstance(rows,list) or not rows:raise ValueError("no price history")
    unique=set()
    records=[]
    for row in rows:
        d=row["date"]
        close=row["adj_close"]
        turnover=row["turnover_inr"]
        if not isinstance(d,str) or d in unique or d>as_of:
            raise ValueError("duplicate/future/invalid date")
        unique.add(d)
        if not all(isinstance(v,(int,float)) and not isinstance(v,bool)
             and isfinite(v) and v>0 for v in (close,turnover)):
            raise ValueError("invalid price or turnover")
        records.append((d,float(close),float(turnover)))
    if records!=sorted(records):
        raise ValueError("historical bars not sorted")
    return records

def rank_universe(history,as_of_members,*,as_of,min_turnover=100_000_000,
                  lookback=252,skip_recent=21,max_candidates=30):
    """252-session lagged momentum / daily-return volatility.

    Point-in-time memberships are supplied by caller. Do NOT substitute present
    NIFTY 500 constituents for historical backtests.
    """
    if not isinstance(as_of_members,(list,tuple,set)) or not as_of_members:
        raise ValueError("verified as-of members required")
    if lookback<=skip_recent+21 or skip_recent<0 or max_candidates<1:
        raise ValueError("invalid windows")
    output=[]
    rejects={}
    for symbol in sorted(set(as_of_members)):
        try:
            data=_prices(history.get(symbol,[]),as_of)
            if len(data)<lookback+1:
                rejects[symbol]="INSUFFICIENT_BARS";continue
            data=data[-(lookback+1):]
            if len(data)!=lookback+1:
                rejects[symbol]="INSUFFICIENT_BARS";continue
            turnover=sorted(row[2] for row in data[-20:])
            med=(turnover[9]+turnover[10])/2
            if med<min_turnover:
                rejects[symbol]="LOW_LIQUIDITY";continue
            values=[row[1] for row in data]
            ret=values[-skip_recent-1]/values[0]-1 if skip_recent else values[-1]/values[0]-1
            daily=[values[i]/values[i-1]-1 for i in range(1,len(values)-skip_recent)]
            vol=pstdev(daily)
            if vol<=1e-8:
                rejects[symbol]="ZERO_VOLATILITY";continue
            output.append({"symbol":symbol,"lagged_momentum_return":ret,
                "daily_volatility":vol,"momentum_score":ret/vol,
                "median_turnover_inr":med,"as_of":as_of,"research_only":True})
        except (KeyError,TypeError,ValueError):
            rejects[symbol]="INVALID_HISTORY"
    output.sort(key=lambda row:(-row["momentum_score"],row["symbol"]))
    for idx,r in enumerate(output,1):r["rank"]=idx
    return {"status":"AVAILABLE" if output else "NO_CANDIDATES",
       "as_of":as_of,"ranked":output[:max_candidates],
       "rejected":rejects,"observed_universe_size":len(set(as_of_members)),
       "method":"252_SESSIONS_SKIP_21_VOL_NORMALIZED",
       "point_in_time_membership_supplied":True,
       "no_lookahead_guarantee_requires_input_audit":True}
