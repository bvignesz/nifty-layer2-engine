"""Offline regression tests for timestamp provenance and futures OI."""
import json
from datetime import datetime,timedelta,timezone
from nifty_l2.storage import Store
from nifty_l2.option_time_audit import inspect_option_timestamps
from nifty_l2.futures_oi_probe import summarize_futures

def test_option_timestamp_keys_not_mistaken_for_verified_exchange_time(tmp_path):
    store=Store(tmp_path/"research.db")
    now=datetime.fromisoformat("2026-11-05T10:30:00+05:30")
    ts=int((now-timedelta(seconds=20)).timestamp())
    calls=[{"method":"optionchain","request":{"symbol":"NSE:NIFTY50-INDEX"},
            "response":{"s":"ok","data":{"optionsChain":[
                {"option_type":"CE","symbol":"NSE:OPT-CE","timestamp":ts,
                 "ltp":100,"oi":1000},
                {"option_type":"PE","symbol":"NSE:OPT-PE","ltt":ts-800,
                 "ltp":120,"oi":1100}]}}}]
    with store.transaction() as conn:
        store.event(conn,observed_at=now,kind="scheduled_research",
                    source="fixture",status="LEGACY_UNVALIDATED",payload={"calls":calls})
    result=inspect_option_timestamps(store.path)
    assert result["optionchain_calls"]==1
    assert result["option_legs"]==2
    assert result["candidate_parseable"]=={"timestamp":1,"ltt":1}
    assert result["candidate_stale_over_180s"]=={"ltt":1}
    assert result["exchange_timestamp_verified"] is False
    assert result["production_db_modified"] is False
    with store.connect() as conn:
        assert conn.execute("SELECT exchange_at_utc FROM events").fetchone()==(None,)

def test_no_candidate_key_never_promotes_receipt_time(tmp_path):
    store=Store(tmp_path/"research.db")
    now=datetime.fromisoformat("2026-11-05T10:30:00+05:30")
    with store.transaction() as conn:
        store.event(conn,observed_at=now,kind="manual_research",
                    source="test",payload={"calls":[{"method":"optionchain",
                    "response":{"data":{"optionsChain":[{"option_type":"CE","oi":100}]}}}]})
    result=inspect_option_timestamps(store.path)
    assert result["events_with_any_parseable_candidate"]==0
    assert result["exchange_timestamp_verified"] is False

def _candle(start,oi=2000):
    return [int(start.timestamp()),100,103,99,102,1000,oi]

def test_futures_history_oi_unique_valid_and_gap_count():
    at=datetime.fromisoformat("2026-11-05T09:15:00+05:30")
    asof=at+timedelta(minutes=27)
    bars=[_candle(at+timedelta(minutes=3*i)) for i in (0,1,2,4,5,6)]
    bars.append(bars[0])  # exact duplicate
    bars.append(_candle(at+timedelta(minutes=27))) # unfinished
    summary=summarize_futures({"s":"ok","candles":bars},asof=asof)
    assert summary["status"]=="FUTURES_HISTORY_OI_PRESENT_UNVERIFIED"
    assert summary["unique_completed_bars"]==6
    assert summary["duplicate_timestamps"]==1
    assert summary["non_3min_spacing"]==1
    assert summary["unfinished_rows"]==1
    assert summary["option_exchange_time_verified"] is False

def test_missing_or_zero_futures_oi_fails():
    at=datetime.fromisoformat("2026-11-05T09:15:00+05:30")
    bars=[_candle(at+timedelta(minutes=3*i),oi=0) for i in range(6)]
    result=summarize_futures({"s":"ok","candles":bars},asof=at+timedelta(hours=1))
    assert result["status"]=="FAIL"
    assert result["unique_completed_bars"]==6
    assert result["positive_oi_bars"]==0
    assert summarize_futures({"s":"error","candles":[]},asof=at)["status"]=="FAIL"

def test_futures_duplicate_conflict_is_not_silently_deduplicated():
    at=datetime.fromisoformat("2026-11-05T09:15:00+05:30")
    bars=[_candle(at+timedelta(minutes=3*i)) for i in range(6)]
    exact=bars[0].copy()
    different=bars[0].copy()
    different[6]=9999
    summary=summarize_futures({"s":"ok","candles":[*bars,exact,different]},
                              asof=at+timedelta(minutes=25))
    assert summary["duplicate_timestamps"]==2
    assert summary["identical_duplicate_rows"]==1
    assert summary["conflicting_duplicate_rows"]==1
    assert summary["unique_completed_bars"]==6
    assert summary["status"]=="FUTURES_HISTORY_CONFLICTS_REVIEW_REQUIRED"
    assert summary["conflict_samples_ist"]==[at.isoformat()]

def test_session_exclusions_keep_local_samples_and_1540_fo_close():
    at=datetime.fromisoformat("2026-11-05T15:33:00+05:30")
    # 15:33 start + 3m is valid for the NSE equity derivatives 15:40 close.
    valid=[_candle(at)]
    outside=_candle(at+timedelta(minutes=6)) # 15:39+3m=15:42
    summary=summarize_futures({"s":"ok","candles":[*valid,outside]},
                              asof=at+timedelta(minutes=20))
    assert summary["completed_rows"]==1
    assert summary["after_session_rows"]==1
    assert summary["after_session_samples_ist"]==[
        (at+timedelta(minutes=6)).isoformat()]
