from datetime import datetime,timedelta,timezone,date
import pytest
from eod_scanner.nse_universe_history import parse_constituents_csv,import_snapshot,members_asof
from nifty_l2.historical_option_replay import replay_expired_contract
from nifty_l2.xgboost_shadow import validate_training_rows,chronological_split,train_shadow,FEATURES

def test_constituent_snapshot_asof_and_not_backfilled(tmp_path):
    raw=b"Symbol,Industry\nABC,Finance\nXYZ,IT\n"
    csv=tmp_path/"nifty500-2026-01-01.csv"
    csv.write_bytes(raw)
    db=tmp_path/"universe_history.db"
    out=import_snapshot(db,csv,as_of="2026-01-01")
    assert out["member_count"]==2
    assert members_asof(db,"2025-12-01")["status"]=="NO_POINT_IN_TIME_MEMBERSHIP"
    assert members_asof(db,"2026-02-01")["members"]==["ABC","XYZ"]
    with pytest.raises(Exception):
        import_snapshot(db,csv,as_of="2026-01-01")
    assert db.stat().st_mode&0o777==0o600

def test_universe_rejects_duplicate_members():
    with pytest.raises(ValueError,match="duplicate"):
        parse_constituents_csv(b"Symbol\nABC\nABC\n",
             as_of="2026-01-01",source_name="NSE_INDICES_DATED_CONSTITUENTS")

def test_replay_next_bar_after_completed_signal_and_cost():
    start=int(datetime(2026,10,29,4,0,tzinfo=timezone.utc).timestamp())
    bars=[{"ts":start+60*i,"open":100+i,"close":100+i+.5}
           for i in range(15)]
    report={"status":"PASS_DATA_AVAILABLE","bars":bars}
    result=replay_expired_contract(report,[{"signal_id":"x",
             "signal_bar_start_epoch":start}],side="CE",quantity=65,
             horizon_minutes=9,brokerage_total=40,statutory_charges=10)
    assert result["replayed"]==1
    assert result["results"][0]["entry_bar_start_epoch"]==start+60
    assert result["results"][0]["exit_bar_start_epoch"]==start+540
    assert result["results"][0]["model_outcome"]["net_pnl"]==502.5
    assert result["results"][0]["model_outcome"]["total_costs"]==50

def test_replay_rejects_omitted_candle():
    start=int(datetime(2026,10,29,4,0,tzinfo=timezone.utc).timestamp())
    bars=[{"ts":start+60*i,"open":100,"close":100} for i in range(12) if i!=5]
    res=replay_expired_contract({"status":"PASS_DATA_AVAILABLE","bars":bars},
      [{"signal_id":"x","signal_bar_start_epoch":start}],
      side="CE",quantity=65,horizon_minutes=9)
    assert res["replayed"]==0
    assert res["results"][0]["status"]=="SKIPPED_GAP"

def test_ml_gate_rejects_unverified_and_few_sessions():
    assert train_shadow([])["status"]=="INSUFFICIENT_SAMPLES"
    rows=[{"session_date":"2026-01-01","observed_at_utc":f"2026-01-01T00:{i//60:02d}:{i%60:02d}+00:00",
       "future_label_available_at_utc":"2026-01-02T00:00:00+00:00",
       "source":"VERIFIED_HISTORICAL_REPLAY","label_net_positive_after_costs":i%2,
       **{k:float(i%10) for k in FEATURES}} for i in range(1000)]
    assert validate_training_rows(rows)["status"]=="INSUFFICIENT_SESSIONS"
    rows[0]["source"]="LEGACY_UNVALIDATED"
    assert validate_training_rows(rows)["status"]=="UNVERIFIED_SOURCE"
