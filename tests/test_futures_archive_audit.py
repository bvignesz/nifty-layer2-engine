from datetime import datetime,timedelta,timezone
import json
from nifty_l2.storage import Store
from nifty_l2.futures_archive_audit import audit_archived_futures

def test_futures_archive_audit_detects_stored_history_without_backfilling(tmp_path):
    store=Store(tmp_path/"research.db")
    observed=datetime.fromisoformat("2026-11-05T10:30:00+05:30")
    stamp=int((observed-timedelta(minutes=6)).timestamp())
    calls=[{"method":"history",
            "request":{"symbol":"NSE:NIFTY26NOVFUT","resolution":"3"},
            "response":{"s":"ok","candles":[[
                stamp,24500,24510,24490,24505,10000,250000]]}}]
    with store.transaction() as conn:
        store.event(conn,observed_at=observed,kind="scheduled_research",
                    source="test",status="LEGACY_UNVALIDATED",payload={"calls":calls})
    result=audit_archived_futures(store.path)
    assert result["status"]=="ARCHIVED_FUTURES_WITH_OI"
    assert result["counts"]["research_events_with_futures_history"]==1
    assert result["counts"]["completed_futures_candles_with_positive_oi"]==1
    assert result["counts"]["futures_data_table_rows"]==0
    assert result["futures_symbols"][0]["symbol"]=="NSE:NIFTY26NOVFUT"
    with store.connect() as db:
        assert db.execute("SELECT count(*) FROM futures_data").fetchone()[0]==0

def test_futures_archive_audit_rejects_incomplete_or_missing_oi(tmp_path):
    store=Store(tmp_path/"research.db")
    observed=datetime.fromisoformat("2026-11-05T10:30:00+05:30")
    start=int((observed-timedelta(minutes=1)).timestamp())
    calls=[{"method":"history",
            "request":{"symbol":"NSE:NIFTY26NOVFUT","resolution":"3"},
            "response":{"s":"ok","candles":[[
                start,24500,24510,24490,24505,10000,0]]}}]
    with store.transaction() as conn:
        store.event(conn,observed_at=observed,kind="scheduled_research",
                    source="test",status="LEGACY_UNVALIDATED",payload={"calls":calls})
    result=audit_archived_futures(store.path)
    assert result["status"]=="FUTURES_UNVERIFIED"
    assert result["counts"]["completed_futures_candles_with_positive_oi"]==0
    assert result["counts"]["futures_data_table_rows"]==0
