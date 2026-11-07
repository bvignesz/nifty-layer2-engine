from datetime import datetime,timedelta,timezone
import pytest
from nifty_l2.research_candidate_gate import (
    assess_option_candidate,assess_underlying_bias,DEFAULT_POLICY)

NOW=datetime(2026,11,6,10,10,tzinfo=timezone.utc)
def args(**overrides):
    base=dict(side="CE",symbol="NSE:NIFTY26NOV24500CE",
       bid=99.8,ask=100,delta=.52,dte_days=3,
       quote_at=NOW-timedelta(seconds=2),decision_at=NOW,
       account_equity=10_000_000,premium_risk_per_unit=30,lot_size=65,
       data_verified=True,verified_lot=True,
       direction_evidence_verified=True)
    return {**base,**overrides}

def test_clean_candidate_separated_from_execution():
    result=assess_option_candidate(**args())
    assert result["status"]=="RESEARCH_CANDIDATE"
    assert result["orders_enabled"] is False
    assert result["market_edge_validated"] is False
    assert result["research_only"] is True
    assert result["lot_count_model"]==3
    assert result["planned_full_premium_stress_risk"]==19500
    assert result["spread_pct_mid"]<.3

def test_unverified_and_stale_is_ignore():
    result=assess_option_candidate(**args(
       quote_at=NOW-timedelta(minutes=5),
       data_verified=False,verified_lot=False,
       direction_evidence_verified=False))
    assert result["status"]=="IGNORE"
    assert {"STALE_OR_FUTURE_QUOTE","UNVERIFIED_MARKET_DATA",
            "LOT_SIZE_UNVERIFIED","DIRECTION_UNVERIFIED"}<=set(result["reasons"])
    assert result["lot_count_model"]==0

def test_full_premium_risk_cap_not_stop_loss_only():
    result=assess_option_candidate(**args(
       account_equity=100000,premium_risk_per_unit=1))
    assert result["status"]=="IGNORE"
    assert "INSUFFICIENT_RISK_BUDGET" in result["reasons"]

def test_reject_invalid_spread_gaps_and_daily_limit():
    result=assess_option_candidate(**args(
       bid=101,ask=100,trades_today=2))
    assert result["status"]=="IGNORE"
    assert "INVALID_BID_ASK" in result["reasons"]
    result=assess_option_candidate(**args(trades_today=2))
    assert "DAILY_TRADE_LIMIT" in result["reasons"]

def test_reject_unjustified_direction_and_strong_score_without_futures():
    assert assess_underlying_bias(9,0)["action"]=="IGNORE"
    assert assess_underlying_bias(8,0,data_verified=True,
                completed_futures_confirmed=True)=={
         "hypothesis":"BULLISH_RESEARCH","action":"REVIEW_CE_ECONOMICS"}
    assert assess_underlying_bias(0,8,data_verified=True,
                completed_futures_confirmed=True)["action"]=="REVIEW_PE_ECONOMICS"
    assert assess_underlying_bias(9,0,data_verified=True,
                completed_futures_confirmed=True,contradiction=True)["action"]=="IGNORE"

def test_reject_bad_policy():
    with pytest.raises(ValueError):
        assess_option_candidate(**args(),policy={"unreviewed_field":1})
