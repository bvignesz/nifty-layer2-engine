import pytest
from nifty_l2.option_pnl_research import simulate_long_option,evaluate_completed_candle_trade

def test_long_ce_positive_net_after_costs():
    r=simulate_long_option(side="CE",entry_premium=100,exit_premium=125,
       quantity=65,entry_spread=2,exit_spread=2,entry_slippage=.5,
       exit_slippage=.5,brokerage_total=40,statutory_charges=20)
    assert r["status"]=="SIMULATED"
    assert r["entry_fill"]==101.5 and r["exit_fill"]==123.5
    assert r["net_pnl"]==1370
    assert not r["orders_enabled"]

def test_budget_uses_full_premium_and_cannot_infer_stop_fills():
    r=simulate_long_option(side="PE",entry_premium=100,exit_premium=0,quantity=65,
       max_premium_risk=5000)
    assert r["status"]=="RISK_BUDGET_REJECTED"
    r=simulate_long_option(side="PE",entry_premium=100,exit_premium=0,quantity=65)
    assert r["net_pnl"]==-6500

def test_same_contract_chronological_only():
    bars=[{"ts":1,"symbol":"NSE:TESTCE","open":100,"close":101},
          {"ts":2,"symbol":"NSE:TESTCE","open":102,"close":110}]
    r=evaluate_completed_candle_trade(bars=bars,entry_index=0,
       exit_index=1,quantity=65,side="CE")
    assert r["net_pnl"]==650
    with pytest.raises(ValueError):evaluate_completed_candle_trade(
       bars=[bars[0],{**bars[1],"symbol":"NSE:OTHER"}],
       entry_index=0,exit_index=1,quantity=65,side="CE")
    with pytest.raises(ValueError):evaluate_completed_candle_trade(
       bars=bars,entry_index=1,exit_index=0,quantity=65,side="CE")

def test_invalid_negative_cost_is_rejected():
    with pytest.raises(ValueError):
        simulate_long_option(side="CE",entry_premium=100,exit_premium=110,
            quantity=65,statutory_charges=-5)
