from datetime import datetime,timezone
import pytest
from nifty_l2.trade_journal import calculate_trade,record_trade,journal_summary
B=dict(trade_id="example-1",setup_family="NIFTY_OPTION_WATCH",
       instrument="NSE:EXAMPLECE",category="OPTION",side="LONG",
       entry_at_utc="2026-11-05T04:00:00Z",
       exit_at_utc="2026-11-05T04:15:00Z",
       entry_fill=100.0,exit_fill=120.0,quantity=65,
       total_costs=50.0,planned_risk_inr=1000.0)

def test_manual_trade_ledger_uses_actual_fills_and_costs(tmp_path):
    db=tmp_path/"trade_journal.db"
    assert journal_summary(db)["status"]=="NO_TRADES"
    entry=record_trade(db,B)
    assert entry["realized_pnl_inr"]==1250.0
    assert entry["realized_r"]==1.25
    assert db.stat().st_mode&0o777==0o600
    summary=journal_summary(db)
    assert summary["total"]==1
    assert summary["win_rate_pct"]==100
    assert summary["mean_realized_r"]==1.25
    with pytest.raises(Exception):
        record_trade(db,B)  # append-only unique trade ID

def test_invalid_or_fabricated_inputs_rejected():
    with pytest.raises(ValueError):
        calculate_trade(**{**B,"category":"OPTION","side":"SHORT"})
    with pytest.raises(ValueError):
        calculate_trade(**{**B,"entry_at_utc":"2026-11-05T04:00:00"})
    with pytest.raises(ValueError):
        calculate_trade(**{**B,"quantity":0})
    with pytest.raises(ValueError):
        calculate_trade(**{**B,"exit_at_utc":"2026-11-05T03:59:00Z"})
    with pytest.raises(ValueError):
        calculate_trade(**{**B,"total_costs":-1})

def test_separate_database_required(tmp_path):
    with pytest.raises(ValueError):
        record_trade(tmp_path/"research.db",B)
