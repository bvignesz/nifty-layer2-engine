from datetime import datetime,timedelta
import json
import math
import pytest

from nifty_l2.gamma_model_parity import black76_gamma,compare_legs,audit_archive
from nifty_l2.storage import Store

def test_black76_gamma_closed_form_atm_and_input_guards():
    f=24500.0
    sigma=.15
    t=7/365
    expected=1/(math.sqrt(2*math.pi)*f*sigma*math.sqrt(t))*math.exp(-(sigma*math.sqrt(t)/2)**2/2)
    assert black76_gamma(f,f,sigma,t)==pytest.approx(expected)
    with pytest.raises(ValueError):
        black76_gamma(0,f,sigma,t)

def test_analytic_broker_gamma_comparison_is_not_approval():
    at=datetime.fromisoformat("2026-11-05T10:00:00+05:30")
    expiry=at+timedelta(days=5)
    f=24500.0
    t=5/365
    gamma=black76_gamma(f,f,.16,t)
    legs=[
        {"option_type":"CE","strike_price":24500,"greeks":{"iv":16,"gamma":gamma}},
        {"option_type":"PE","strike_price":24500,"greeks":{"iv":16,"gamma":gamma*1.05}},
        {"option_type":"CE","strike_price":24000,"greeks":{"iv":0,"gamma":.0001}},
    ]
    result=compare_legs(legs,asof=at,expiry_at=expiry,forward=f)
    assert result["status"]=="MODEL_COMPARISON_UNVERIFIED"
    assert result["usable_legs"]==2
    assert result["skipped"]["invalid_iv"]==1
    assert result["median_broker_over_black76"]==pytest.approx(1.025)
    assert result["broker_gamma_convention_verified"] is False
    assert result["oi_units_verified"] is False
    assert result["dealer_position_observed"] is False
    assert compare_legs(legs,asof=expiry,expiry_at=expiry,forward=f)["status"]=="UNAVAILABLE"

def test_immutable_archive_analysis_does_not_touch_exchange_timestamp(tmp_path):
    store=Store(tmp_path/"research.db")
    at=datetime.fromisoformat("2026-11-05T10:00:00+05:30")
    expiry=at+timedelta(days=5)
    f=24500.0
    g=black76_gamma(f,f,.16,5/365)
    with store.transaction() as db:
        store.event(db,observed_at=at,kind="scheduled_research",source="test",
          payload={"calls":[{"method":"optionchain",
             "request":{"timestamp":"1794219000"},
             "response":{"data":{"optionsChain":[
                 {"option_type":"CE","strike_price":24500,
                  "oi":1000,"greeks":{"iv":16,"gamma":g}}]}}}]})
    result=audit_archive(store.path,forward=f,expiry_at=expiry)
    assert result["events_with_comparable_greeks"]==1
    assert result["median_event_broker_over_black76"]==pytest.approx(1)
    assert result["source_forward_timestamp_verified"] is False
    assert result["production_db_modified"] is False
    with store.connect() as db:
        assert db.execute("SELECT exchange_at_utc FROM events").fetchone()==(None,)
