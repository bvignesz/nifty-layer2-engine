"""Research-only long-option fill/P&L simulator on real contract candles.

The historical expired-contract endpoint supplies OHLCV, not historical bid/ask
at every entry/exit. Explicit spread/slippage assumptions are indispensable.
No broker orders, no execution guarantee, no inferred Greeks or option quotes.
"""
from math import isfinite

def _pos(v,allow_zero=False):
    return isinstance(v,(int,float)) and not isinstance(v,bool) and isfinite(v) and (
      v>=0 if allow_zero else v>0)

def simulate_long_option(*,side,entry_premium,exit_premium,quantity,
                         entry_spread=0.0,exit_spread=0.0,
                         entry_slippage=0.0,exit_slippage=0.0,
                         brokerage_total=0.0,statutory_charges=0.0,
                         max_premium_risk=None):
    """Costs stated in INR; spreads in premium units, round-trip per-share."""
    if side not in ("CE","PE"):raise ValueError("CE/PE long only")
    for name,v in (("entry_premium",entry_premium),("exit_premium",exit_premium),
                   ("quantity",quantity)):
        if not _pos(v,allow_zero=name=="exit_premium"):
            raise ValueError("invalid "+name)
    if not isinstance(quantity,int):raise ValueError("quantity must be whole units")
    for name,v in (("entry_spread",entry_spread),("exit_spread",exit_spread),
       ("entry_slippage",entry_slippage),("exit_slippage",exit_slippage),
       ("brokerage_total",brokerage_total),("statutory_charges",statutory_charges)):
        if not _pos(v,allow_zero=True):raise ValueError("invalid "+name)
    entry_fill=entry_premium+entry_spread/2+entry_slippage
    exit_fill=max(0.0,exit_premium-exit_spread/2-exit_slippage)
    gross=(exit_fill-entry_fill)*quantity
    fees=brokerage_total+statutory_charges
    net=gross-fees
    paid=entry_fill*quantity
    if max_premium_risk is not None and (not _pos(max_premium_risk)
       or paid>max_premium_risk):
        return {"status":"RISK_BUDGET_REJECTED","research_only":True,
                "premium_paid":paid,"max_long_option_premium_loss":paid,
                "orders_enabled":False}
    return {"status":"SIMULATED","side":side,"quantity":quantity,
       "entry_fill":round(entry_fill,4),"exit_fill":round(exit_fill,4),
       "gross_pnl":round(gross,2),"total_costs":round(fees,2),
       "net_pnl":round(net,2),"premium_paid":round(paid,2),
       "max_long_option_premium_loss":round(paid,2),
       "net_return_on_premium_pct":round(100*net/paid,3),
       "research_only":True,"orders_enabled":False,
       "notes":"Historical premium bars cannot establish live bid/ask execution. Tax and slippage inputs are explicit assumptions."}

def evaluate_completed_candle_trade(*,bars,entry_index,exit_index,quantity,
                                    side,entry_spread=0.,exit_spread=0.,
                                    entry_slippage=0.,exit_slippage=0.,
                                    brokerage_total=0.,statutory_charges=0.):
    """For replay: buy at next completed bar OPEN, exit at a later bar CLOSE.

    This is an OHLCV price approximation; it is NOT proof that limit orders
    could fill there. Fail on missing/mismatched symbol or bar ordering.
    """
    if not isinstance(entry_index,int) or not isinstance(exit_index,int) or (
        not 0<=entry_index<exit_index<len(bars)):
        raise ValueError("entry must precede exit")
    selected=bars[entry_index:exit_index+1]
    ts=[r.get("ts") for r in selected]
    if any(not isinstance(v,int) for v in ts) or any(b<=a for a,b in zip(ts,ts[1:])):
        raise ValueError("invalid candle chronology")
    symbols={r.get("symbol") for r in selected}
    if len(symbols)!=1 or not next(iter(symbols)):
        raise ValueError("unmatched contract")
    return simulate_long_option(side=side,entry_premium=selected[0]["open"],
        exit_premium=selected[-1]["close"],quantity=quantity,
        entry_spread=entry_spread,exit_spread=exit_spread,
        entry_slippage=entry_slippage,exit_slippage=exit_slippage,
        brokerage_total=brokerage_total,statutory_charges=statutory_charges)
