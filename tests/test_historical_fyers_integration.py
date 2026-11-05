"""Offline end-to-end integration tests for saved historical data and FYERS reads."""
from datetime import datetime, timezone
import json

from nifty_l2.storage import Store
from nifty_l2.historical_validation import inspect_db
from nifty_l2.fyers_integration_probe import evaluate_live,load_token


def test_historical_audit_validates_without_writing(tmp_path):
    path=tmp_path/"research.db"
    store=Store(path)
    observed="2026-11-05T10:21:00+05:30"
    with store.transaction() as conn:
        eid=store.event(conn,observed_at=observed,kind="scheduled_research",
                        source="fixture",status="LEGACY_UNVALIDATED",payload={})
        conn.execute("INSERT INTO signals VALUES(?,?,1,?)",
                     (eid,"No Trade",json.dumps({"final_verdict":"NO TRADE"})))
        for n in range(1,10):
            for side in ("BULL","BEAR"):
                conn.execute("INSERT INTO check_results VALUES(?,?,?,?,?)",
                             (eid,n,side,"PASS",json.dumps({"n":n})))
        ts=int(datetime.fromisoformat(observed).timestamp())
        conn.execute("INSERT INTO header_snapshots(ts,expiry_date) VALUES(?,?)",
                     (ts,"09-11-2026"))
        for side in ("CE","PE"):
            conn.execute("""INSERT INTO strike_snapshots(ts,strike,opt_type,oi,ltp,volume,gamma)
                            VALUES(?,?,?,?,?,?,?)""",(ts,24450,side,1000,120,4000,.0001))
    initial=path.stat().st_size
    report=inspect_db(path)
    assert report["status"]=="REQUIRES_MARKET_VALIDATION"
    assert report["checks"]["sqlite_integrity"]
    assert report["checks"]["nine_checks_recorded"]
    assert report["checks"]["research_safety"]
    assert not report["checks"]["exchange_timestamp_coverage"]
    assert report["metrics"]["research_missing_exchange_time"]==1
    assert report["metrics"]["orphan_strike_rows"]==0
    assert path.stat().st_size==initial


def test_historical_invalid_strikes_fail(tmp_path):
    path=tmp_path/"research.db"
    store=Store(path)
    ts=int(datetime.fromisoformat("2026-11-05T10:21:00+05:30").timestamp())
    with store.transaction() as conn:
        conn.execute("INSERT INTO strike_snapshots(ts,strike,opt_type,oi) VALUES(?,?,?,?)",
                     (ts,24450,"CE",-100))
    report=inspect_db(path)
    assert report["status"]=="FAIL"
    assert not report["checks"]["strike_integrity"]


def _mock_api(op,*,params=None,credentials=None):
    if op=="profile":return {"s":"ok"}
    if op=="quotes":
        return {"s":"ok","d":[{"n":"NSE:NIFTY50-INDEX","v":{"lp":24500}}]}
    if op=="optionchain":
        if params["strikecount"]==1:
            return {"s":"ok","data":{"expiryData":[{"date":"09-11-2026","expiry":111}]}}
        return {"s":"ok","data":{"optionsChain":[
            {"option_type":"CE","strike_price":24500,"symbol":"NSE:CE",
             "oi":25000,"ltp":120,"greeks":{"gamma":.00011}},
            {"option_type":"PE","strike_price":24500,"symbol":"NSE:PE",
             "oi":20000,"ltp":110,"greeks":{"gamma":.00012}}]}}
    if op=="history":
        start=int(datetime.fromisoformat("2026-11-04T10:00:00+05:30").timestamp())
        return {"s":"ok","candles":[[start,100,105,98,102,40000,12345]]}
    raise AssertionError("Unapproved API operation attempted: "+op)


def test_mock_fyers_all_endpoints_success_without_orders():
    report=evaluate_live(_mock_api,
        now=datetime.fromisoformat("2026-11-05T16:00:00+05:30"),
        future_symbol="NSE:NIFTY26NOVFUT")
    assert report["status"]=="API_READS_PASS_DATA_QUALITY_PENDING"
    assert {x["name"] for x in report["checks"]}=={
        "profile","index_quote","actual_expiry_optionchain","equity_daily",
        "equity_15m","futures_3m"}
    assert all(x["status"]=="PASS" for x in report["checks"])
    assert report["api_calls"]==7
    assert report["order_calls"]==0
    assert "access_token" not in json.dumps(report)


def test_mock_fyers_missing_historical_api_blocks_release():
    def rejected(op,*,params=None,credentials=None):
        if op=="history":return {"s":"error","candles":[]}
        return _mock_api(op,params=params,credentials=credentials)
    report=evaluate_live(rejected,
        now=datetime.fromisoformat("2026-11-05T16:00:00+05:30"))
    assert report["status"]=="FAIL"
    assert {x["name"] for x in report["checks"] if x["status"]=="FAIL"}=={
        "equity_daily","equity_15m"}


def test_token_file_must_be_private(tmp_path):
    path=tmp_path/"token.json"
    path.write_text('{"client_id":"APP","access_token":"FAKE"}')
    path.chmod(0o600)
    assert load_token(path)["client_id"]=="APP"
    path.chmod(0o644)
    import pytest
    with pytest.raises(ValueError,match="private"):
        load_token(path)
