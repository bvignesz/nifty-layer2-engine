import csv
from datetime import datetime, timedelta
from nifty_l2.storage import Store
from nifty_l2.oi_unit_reconciliation import audit, reconcile

def _archive(tmp_path):
    store=Store(tmp_path/"research.db")
    now=datetime.fromisoformat("2026-11-05T10:03:00+05:30")
    calls=[{"method":"optionchain",
            "request":{"timestamp":"1794219000","strikecount":10},
            "response":{"s":"ok","data":{"optionsChain":[
                {"symbol":"NSE:NIFTY26NOV24500CE","strike_price":24500,
                 "option_type":"CE","oi":65000},
                {"symbol":"NSE:NIFTY26NOV24500PE","strike_price":24500,
                 "option_type":"PE","oi":130000}]}}}]
    with store.transaction() as db:
        store.event(db,observed_at=now,kind="scheduled_research",
                    source="test",payload={"calls":calls})
    return store,now

def _ref(tmp_path,now,symbol="NSE:NIFTY26NOV24500CE",contract_oi=1000,skew_seconds=0):
    path=tmp_path/"reference.csv"
    with path.open("w",newline="") as f:
        w=csv.DictWriter(f,fieldnames=["observed_at_utc","expiry_id","symbol",
              "strike","option_type","nse_oi_contracts"])
        w.writeheader()
        w.writerow({"observed_at_utc":(now+timedelta(seconds=skew_seconds)).isoformat(),
                    "expiry_id":"1794219000","symbol":symbol,"strike":24500,
                    "option_type":"CE","nse_oi_contracts":contract_oi})
    return path

def test_structural_lot_divisibility_not_a_verification(tmp_path):
    store,now=_archive(tmp_path)
    result=audit(store.path,65)
    assert result["raw_observations"]==2
    assert result["structural"]["oi_multiples_of_lot"]==2
    assert result["structural"]["not_proof_of_quantity_basis"] is True
    assert result["fyers_oi_basis"]=="UNVERIFIED"
    assert result["production_db_modified"] is False
    with store.connect() as db:
        assert db.execute("SELECT exchange_at_utc FROM events").fetchone()[0] is None

def test_manual_nse_contracts_ratio_and_skew(tmp_path):
    store,now=_archive(tmp_path)
    matched=audit(store.path,65,_ref(tmp_path,now))
    data=matched["manual_reference"]
    assert data["candidate_underlying_units"]==1
    assert data["candidate_contracts"]==0
    assert data["oi_basis_independently_verified"] is False
    out=audit(store.path,65,_ref(tmp_path,now,skew_seconds=500))
    assert out["manual_reference"]["outcomes"][0]["status"]=="NO_TIME_ALIGNED_MATCH"

def test_mismatched_symbol_or_expiry_not_accepted(tmp_path):
    store,now=_archive(tmp_path)
    out=audit(store.path,65,_ref(tmp_path,now,symbol="NSE:WRONG"))
    assert out["manual_reference"]["matched_candidate_rows"]==0
