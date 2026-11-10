"""Leakage-aware replay of actual expired-contract option candles.

A signal at the *close* of one completed minute enters at the *next* minute
OPEN. Exits at an explicitly selected subsequent close. No invented bid/ask;
spread, slippage and charges must be supplied. This simulator cannot claim
marketability or real trading performance.
"""
from .option_pnl_research import simulate_long_option

def replay_expired_contract(report,signals,*,side,quantity,horizon_minutes=9,
   entry_spread=0.,exit_spread=0.,entry_slippage=0.,exit_slippage=0.,
   brokerage_total=0.,statutory_charges=0.):
    if report.get("status")!="PASS_DATA_AVAILABLE":
        raise ValueError("Only validated broker historical candles accepted")
    bars=report.get("bars",[])
    if not bars:raise ValueError("No candles")
    if horizon_minutes not in (9,15,30):
        raise ValueError("Supported research horizons are 9, 15, 30 minutes")
    index={}
    for b in bars:
        stamp=b["ts"]
        if stamp in index:raise ValueError("duplicate candle")
        index[stamp]=b
    results=[]
    if len(signals)>10000:raise ValueError("too many signals")
    for sig in signals:
        signal_id=sig.get("signal_id")
        at=sig.get("signal_bar_start_epoch")
        if not isinstance(at,int) or not isinstance(signal_id,str) or not signal_id:
            raise ValueError("invalid signal")
        # Signal becomes known at at+60. Enter at the immediately following bar
        # starting at at+60; exit at closing of horizon's final future bar.
        enter=index.get(at+60)
        exit_=index.get(at+60*horizon_minutes)
        if at not in index or not enter or not exit_:
            results.append({"signal_id":signal_id,"status":"SKIPPED_MISSING_CANDLE"})
            continue
        if any(at+i*60 not in index for i in range(1,horizon_minutes+1)):
            results.append({"signal_id":signal_id,"status":"SKIPPED_GAP"})
            continue
        outcome=simulate_long_option(side=side,entry_premium=enter["open"],
           exit_premium=exit_["close"],quantity=quantity,
           entry_spread=entry_spread,exit_spread=exit_spread,
           entry_slippage=entry_slippage,exit_slippage=exit_slippage,
           brokerage_total=brokerage_total,statutory_charges=statutory_charges)
        results.append({"signal_id":signal_id,"status":"REPLAYED",
           "signal_bar_start_epoch":at,"entry_bar_start_epoch":at+60,
           "exit_bar_start_epoch":at+60*horizon_minutes,
           "model_outcome":outcome,
           "historical_quote_spread_observed":False,
           "source":"FYERS_EXPIRED_FO_COMPLETED_CANDLES"})
    executed=[r["model_outcome"] for r in results if r["status"]=="REPLAYED"]
    return {"status":"REPLAY_COMPLETE","total_signals":len(signals),
       "replayed":len(executed),"results":results,
       "net_pnl_inr":round(sum(r["net_pnl"] for r in executed),2),
       "win_rate_pct":round(100*sum(r["net_pnl"]>0 for r in executed)/len(executed),2) if executed else None,
       "assumed_round_trip_costs_inr":round(sum(r["total_costs"] for r in executed),2),
       "no_lookahead_assumption":"signal known at close, next bar open entry",
       "research_only":True,"orders_enabled":False,
       "warning":"Price bars do NOT prove achievable bid/ask or slippage. Results are scenarios."}
