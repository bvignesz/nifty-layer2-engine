from datetime import datetime, timedelta
import json
import pytest
from nifty_l2.option_observation_gate import snapshot_from_response, comparable_pair
from nifty_l2.gex_assumption_audit import gex_sensitivity,audit_archived
from nifty_l2.storage import Store


def _chain(ce_oi=1000, pe_oi=800):
    return {"s":"ok","data":{"optionsChain":[
        {"strike_price":-1,"option_type":"","ltp":24000,"fp":24000},
        {"symbol":"NSE:CE","option_type":"CE","strike_price":24000,"oi":ce_oi,
         "greeks":{"gamma":0.0001,"iv":15}},
        {"symbol":"NSE:PE","option_type":"PE","strike_price":24000,"oi":pe_oi,
         "greeks":{"gamma":0.0002,"iv":16}}
    ]}}

def test_snapshot_receipt_brackets_are_not_exchange_candle_times():
    first=datetime.fromisoformat("2026-11-05T10:00:00+05:30")
    s1=snapshot_from_response(_chain(),requested_at=first,
       received_at=first+timedelta(seconds=1),expiry_id=1793894400)
    s2=snapshot_from_response(_chain(1100,700),requested_at=first+timedelta(minutes=3),
       received_at=first+timedelta(minutes=3,seconds=2),expiry_id=1793894400)
    result=comparable_pair(s1,s2)
    assert result["status"]=="COMPARABLE_RECEIPT_DELTA_UNVERIFIED"
    assert result["delta_oi_by_symbol"]=={"NSE:CE":100,"NSE:PE":-100}
    assert result["exchange_timestamp_verified"] is False
    assert result["completed_option_candle"] is False
    other=snapshot_from_response(_chain(),requested_at=first+timedelta(minutes=6),
       received_at=first+timedelta(minutes=6,seconds=1),expiry_id=999)
    assert comparable_pair(s2,other)["status"]=="BLOCKED"

def test_receipt_gap_and_missing_leg_are_fail_closed():
    at=datetime.fromisoformat("2026-11-05T10:00:00+05:30")
    s1=snapshot_from_response(_chain(),requested_at=at,received_at=at,expiry_id=1)
    s2=snapshot_from_response(_chain(),requested_at=at+timedelta(minutes=10),
                              received_at=at+timedelta(minutes=10),expiry_id=1)
    assert comparable_pair(s1,s2)["status"]=="BLOCKED"
    s3=snapshot_from_response({"s":"ok","data":{"optionsChain":[
        {"option_type":"CE","symbol":"NSE:CE","oi":1500}]}},
        requested_at=at+timedelta(minutes=3),received_at=at+timedelta(minutes=3),
        expiry_id=1)
    assert comparable_pair(s1,s3)["status"]=="BLOCKED"

def test_gex_oi_convention_and_inventory_ambiguity():
    raw=_chain()["data"]["optionsChain"]
    report=gex_sensitivity(raw,underlying=24000,lot_size=65)
    assert report["status"]=="OI_UNITS_UNVERIFIED"
    assert report["counts"]["usable_legs"]==2
    assert report["if_oi_is_contracts_cr_per_1pct"]==pytest.approx(
        65*report["unscaled_oi_interpretation_cr_per_1pct"])
    assert report["dealer_inventory_observed"] is False
    assert report["dealer_all_long_gamma_cr_per_1pct"]>0
    assert report["dealer_all_short_gamma_cr_per_1pct"]<0
    assert report["coverage_complete"] is False
    units=gex_sensitivity(raw,underlying=24000,lot_size=65,oi_basis="contracts")
    assert units["call_positive_put_negative_cr_per_1pct"]==pytest.approx(
        report["if_oi_is_contracts_cr_per_1pct"])
    with pytest.raises(ValueError):
        gex_sensitivity(raw,underlying=24000,lot_size=0)

def test_gex_archive_does_not_promote_fyers_receipts_or_change_db(tmp_path):
    store=Store(tmp_path/"research.db")
    now=datetime.fromisoformat("2026-11-05T10:00:00+05:30")
    with store.transaction() as con:
        store.event(con,observed_at=now,kind="scheduled_research",
                    source="test",payload={"calls":[{"method":"optionchain",
                    "request":{"timestamp":"1793894400"},"response":_chain()}],
                    "configuration":{"NIFTY_LOT_SIZE":75}})
    audit=audit_archived(store.path,lot_size=65)
    assert audit["available_greek_events"]==1
    assert audit["legacy_default_lot_mismatch"] is True
    assert audit["examples"][0]["legacy_lot_size_recorded"]==75
    assert audit["production_db_modified"] is False
    assert audit["exchange_oi_timestamp_verified"] is False
    with store.connect() as con:
        assert con.execute("SELECT exchange_at_utc FROM events").fetchone()==(None,)
