"""Research-only option candidate economics and permission gates.

No FYERS calls, orders, dealer-sign inference or modifications to legacy checks.
An underlying directional hypothesis is NOT an executable option trade.
Thresholds are versioned RESEARCH DEFAULTS, never presumed profitable.
"""
from dataclasses import dataclass,asdict
from datetime import datetime,timezone
from math import floor,isfinite
import json

DEFAULT_POLICY={
    "max_quote_age_seconds":15.0,
    "max_spread_pct_mid":1.0,
    "min_abs_delta":0.40,
    "max_abs_delta":0.65,
    "min_dte_days":1.0,
    "max_single_idea_risk_fraction":0.0025,
    "max_new_daily_risk_fraction":0.0075,
    "max_daily_trades":2,
}

def _valid(v,allow_zero=False):
    try:
        x=float(v)
        return x if isfinite(x) and (x>=0 if allow_zero else x>0)
    except (TypeError,ValueError,OverflowError):
        return False

def _utc(value):
    if isinstance(value,datetime):
        d=value
    else:
        d=datetime.fromisoformat(str(value).replace("Z","+00:00"))
    if d.tzinfo is None:
        raise ValueError("Timestamp requires offset")
    return d.astimezone(timezone.utc)

def assess_option_candidate(*,side,symbol,bid,ask,delta,dte_days,
                            quote_at,decision_at,account_equity,
                            premium_risk_per_unit,lot_size,
                            new_risk_today=0.0,trades_today=0,
                            data_verified=False,verified_lot=False,
                            direction_evidence_verified=False,
                            policy=None):
    """Return an inspectable candidate gate, not advice or a trade instruction.

    premium_risk_per_unit is an externally specified *stress-risk estimate*
    (not an automatic stop guarantee), in INR per share/unit. For minimum
    prudence candidate sizing uses full premium as the worst-case loss.
    """
    p=dict(DEFAULT_POLICY)
    if policy:
        unknown=set(policy)-set(p)
        if unknown:raise ValueError("Unsupported policy key")
        p.update(policy)
    if any(not _valid(v) for v in p.values()):
        raise ValueError("Invalid policy values")
    reasons=[]
    if side not in ("CE","PE"):reasons.append("INVALID_SIDE")
    if not isinstance(symbol,str) or not symbol.startswith("NSE:"):
        reasons.append("INVALID_SYMBOL")
    quote_age=None
    try:
        quote_age=(_utc(decision_at)-_utc(quote_at)).total_seconds()
        if quote_age<0 or quote_age>p["max_quote_age_seconds"]:
            reasons.append("STALE_OR_FUTURE_QUOTE")
    except (TypeError,ValueError,OverflowError):
        reasons.append("INVALID_QUOTE_TIMESTAMP")
    spread_pct=None
    mid=None
    if _valid(bid) and _valid(ask) and float(ask)>=float(bid):
        mid=(float(ask)+float(bid))/2
        spread_pct=100*(float(ask)-float(bid))/mid
        if spread_pct>p["max_spread_pct_mid"]:reasons.append("WIDE_SPREAD")
    else:
        reasons.append("INVALID_BID_ASK")
    abs_delta=None
    if _valid(abs(delta)) if isinstance(delta,(int,float)) else False:
        abs_delta=abs(float(delta))
        if not (p["min_abs_delta"]<=abs_delta<=p["max_abs_delta"]):
            reasons.append("DELTA_OUT_OF_RANGE")
    else:
        reasons.append("INVALID_DELTA")
    if not _valid(dte_days) or float(dte_days)<p["min_dte_days"]:
        reasons.append("NEAR_EXPIRY_OR_INVALID_DTE")
    if not data_verified:reasons.append("UNVERIFIED_MARKET_DATA")
    if not verified_lot:reasons.append("LOT_SIZE_UNVERIFIED")
    if not direction_evidence_verified:reasons.append("DIRECTION_UNVERIFIED")
    lot_count=0
    planned_risk=None
    affordable_risk=None
    if not (_valid(account_equity) and _valid(lot_size) and
            isinstance(lot_size,int) and _valid(premium_risk_per_unit) and
            _valid(new_risk_today,allow_zero=True) and
            isinstance(trades_today,int) and trades_today>=0):
        reasons.append("INVALID_RISK_INPUT")
    elif mid is not None:
        # Full-premium loss is possible on long options. A stop might not fill.
        # Stress-risk estimate cannot override the full premium cap.
        per_lot_worst=float(ask)*lot_size
        per_lot_stress=float(premium_risk_per_unit)*lot_size
        per_lot_budget=max(per_lot_worst,per_lot_stress)
        cap_single=float(account_equity)*p["max_single_idea_risk_fraction"]
        cap_daily=max(0.0,float(account_equity)*p["max_new_daily_risk_fraction"]-
                      float(new_risk_today))
        affordable_risk=min(cap_single,cap_daily)
        lot_count=floor(affordable_risk/per_lot_budget)
        planned_risk=lot_count*per_lot_budget
        if lot_count<1:reasons.append("INSUFFICIENT_RISK_BUDGET")
        if trades_today>=p["max_daily_trades"]:
            reasons.append("DAILY_TRADE_LIMIT")
    status="RESEARCH_CANDIDATE" if not reasons else "IGNORE"
    return {"status":status,"side":side,"symbol":symbol,
            "quote_age_seconds":quote_age,"mid_premium":mid,
            "spread_pct_mid":spread_pct,"abs_delta":abs_delta,
            "lot_count_model":lot_count if status=="RESEARCH_CANDIDATE" else 0,
            "planned_full_premium_stress_risk":planned_risk if status=="RESEARCH_CANDIDATE" else None,
            "available_risk_budget":affordable_risk,
            "reasons":sorted(set(reasons)),
            "research_only":True,"orders_enabled":False,"market_edge_validated":False,
            "note":"Risk model uses full long-option premium as a stress cap; ignores gaps, funding, taxes and actual execution outcomes. Model trade count is not an order."}

def assess_underlying_bias(bull_checks,bear_checks,*,data_verified=False,
                            completed_futures_confirmed=False,contradiction=False):
    """Keep directional hypothesis distinct from option permission."""
    if not data_verified or not completed_futures_confirmed:
        return {"hypothesis":"UNVERIFIED","action":"IGNORE"}
    if contradiction:
        return {"hypothesis":"MIXED","action":"IGNORE"}
    if not isinstance(bull_checks,int) or not isinstance(bear_checks,int):
        return {"hypothesis":"UNVERIFIED","action":"IGNORE"}
    if bull_checks>=6 and bear_checks<=2:
        return {"hypothesis":"BULLISH_RESEARCH","action":"REVIEW_CE_ECONOMICS"}
    if bear_checks>=6 and bull_checks<=2:
        return {"hypothesis":"BEARISH_RESEARCH","action":"REVIEW_PE_ECONOMICS"}
    return {"hypothesis":"MIXED","action":"IGNORE"}
