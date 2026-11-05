import json
from datetime import datetime
import pytest

from nifty_l2.storage import Store
from nifty_l2.research_readmodel import research_history,expiry_matrix,readiness
from nifty_l2.research_pages import render
from nifty_l2.research_quality import gamma_scenario,completed_candle,validate_snapshot_sequence
from nifty_l2.eod_fyers_adapter import validate_symbol,normalize_ohlcv
from nifty_l2.research_outcomes import label_one


def _populate(tmp_path):
    store=Store(tmp_path/"research.db")
    timestamp=int(datetime.fromisoformat("2026-11-05T10:21:00+05:30").timestamp())
    state={"final_verdict":"BULL","scorecard":[{"Check":str(i),"Bull_Status":"PASS","Bear_Status":"FAIL"} for i in range(1,10)],
           "meta":{"spot":24500,"gex":"+100 Cr/1% (POS_GEX_SCENARIO_EST)","put_wall":24400,"call_wall":24600},
           "layer2_audit":{"gex_units":"+100 ₹Cr / 1% Spot (OI-Signed Scenario)"}}
    with store.transaction() as conn:
        event_id=store.event(conn,observed_at="2026-11-05T10:21:00+05:30",
                             kind="scheduled_research",source="test",status="LEGACY_UNVALIDATED",payload={})
        conn.execute("INSERT INTO signals VALUES(?,?,1,?)",(event_id,"No Trade",json.dumps(state)))
        conn.execute("INSERT INTO header_snapshots(ts,expiry_date,spot) VALUES(?,?,?)",(timestamp,"09-11-2026",24500))
        for side in ("CE","PE"):
            conn.execute("INSERT INTO strike_snapshots(ts,strike,opt_type,ltp,oi,iv,gamma) VALUES(?,?,?,?,?,?,?)",
                        (timestamp,24450,side,100,2000,15,.0001))
    return store


def test_readonly_research_history_expiries_and_no_synthetic_contracts(tmp_path):
    _populate(tmp_path)
    history=research_history(tmp_path,"2026-11-05")
    assert len(history["rows"])==1
    row=history["rows"][0]
    assert row["classification"]=="No Trade"
    assert row["original_verdict"]=="BULL"
    assert len(row["checks"])==9
    assert "OI-Signed Scenario" in row["scenario"]["gex_units"]
    matrix=expiry_matrix(tmp_path,"2026-11-05",24450)
    assert matrix["status"]=="AVAILABLE"
    assert {r["side"] for r in matrix["rows"]}=={"CE","PE"}
    assert {r["expiry"] for r in matrix["rows"]}=={"09-11-2026"}
    assert not expiry_matrix(tmp_path,"2026-11-05",24000)["rows"]
    assert readiness(tmp_path)["ml_training_ready"] is False
    html=render(tmp_path,"research",{"date":["2026-11-05"]})
    assert "Nine-check history" in html and "BULL" in html
    assert "No Trade" in html


def test_missing_db_is_not_created(tmp_path):
    assert research_history(tmp_path,"2026-11-05")["rows"]==[]
    assert readiness(tmp_path)["status"]=="NO_DATABASE"
    assert not (tmp_path/"research.db").exists()


def test_filters_reject_invalid_inputs(tmp_path):
    _populate(tmp_path)
    with pytest.raises(ValueError):
        research_history(tmp_path,"not-a-date")
    with pytest.raises(ValueError):
        research_history(tmp_path,"2026-11-05",9999)
    with pytest.raises(ValueError):
        expiry_matrix(tmp_path,"2026-11-05",-1)


def test_gex_is_scenario_and_invalid_missing_stays_unavailable():
    result=gamma_scenario(future_price=24000,call_gamma=.0001,put_gamma=.0001,
                          call_oi=10000,put_oi=8000)
    assert result["status"]=="SCENARIO_ESTIMATE"
    assert result["dealer_inventory_observed"] is False
    assert result["net_gex_cr"]>0
    assert gamma_scenario(future_price=24000,call_gamma=0,put_gamma=.0001,
                          call_oi=10000,put_oi=8000)["status"]=="UNAVAILABLE"
    with pytest.raises(ValueError):
        gamma_scenario(future_price=24000,call_gamma=.0001,put_gamma=.0001,
                       call_oi=10000,put_oi=8000,oi_unit="lots")


def test_time_quality_and_eod_validation():
    start=int(datetime.fromisoformat("2026-11-05T10:21:00+05:30").timestamp())
    assert completed_candle(start,"2026-11-05T10:25:00+05:30",3)["status"]=="COMPLETED"
    assert completed_candle(start,"2026-11-05T10:22:00+05:30",3)["status"]=="INCOMPLETE"
    assert validate_snapshot_sequence("2026-11-05T10:21:00+05:30","2026-11-05T10:24:00+05:30")=="COMPARABLE"
    assert validate_symbol("NSE:TCS-EQ")=="NSE:TCS-EQ"
    with pytest.raises(ValueError):
        validate_symbol("TCS.NS")
    raw={"s":"ok","candles":[[start,100,103,99,102,500]]}
    assert normalize_ohlcv(raw,"15","2026-11-05T10:40:00+05:30")[0]["close"]==102
    assert normalize_ohlcv(raw,"15","2026-11-05T10:30:00+05:30")==[]


def test_outcomes_never_fill_missing_future_candle():
    observed="2026-11-05T10:21:00+05:30"
    target="2026-11-05T05:00:00+00:00"
    good=label_one(observed,100,[{"end_utc":target,"close":102}],9)
    assert good["status"]=="CANDIDATE_UNVALIDATED"
    assert good["forward_return"]==pytest.approx(.02)
    assert label_one(observed,100,[],9)["status"]=="UNAVAILABLE"
