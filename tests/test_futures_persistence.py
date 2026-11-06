import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from nifty_l2.futures_persistence import latest_completed_future, persist_futures
from nifty_l2.futures_copy_backfill import backfill_copy
from nifty_l2.storage import Store

def recorded(observed, *, oi=50000, minutes_before=3, resolution="3"):
    start=int((observed-timedelta(minutes=minutes_before)).timestamp())
    return [{"method":"history","request":{
        "symbol":"NSE:NIFTY26NOVFUT","resolution":resolution},
        "response":{"s":"ok","candles":[
            [start,24000,24020,23990,24010,1000,oi]]}}]

def test_completed_futures_bar_saves_exchange_start_not_receipt(tmp_path):
    now=datetime.fromisoformat("2026-11-05T10:30:00+05:30")
    calls=recorded(now)
    actual=latest_completed_future(calls, now)
    assert actual["start"] == now-timedelta(minutes=3)
    store=Store(tmp_path/"db.sqlite")
    with store.transaction() as conn:
        eid=store.event(conn,observed_at=now,kind="scheduled_research",source="test",
                        payload={"calls":calls})
        assert persist_futures(conn,eid,calls,now)
        assert persist_futures(conn,eid,calls,now)
    with store.connect() as conn:
        rows=conn.execute("SELECT exchange_at_utc,close,oi FROM futures_data").fetchall()
        assert len(rows)==1
        assert rows[0][1:]==(24010,50000)
        assert rows[0][0].endswith("Z")
        assert conn.execute("SELECT exchange_at_utc FROM events").fetchone()[0] is None

def test_candle_and_oi_quality_rejections():
    now=datetime.fromisoformat("2026-11-05T10:30:00+05:30")
    assert latest_completed_future(recorded(now,oi=0),now) is None
    assert latest_completed_future(recorded(now,minutes_before=1),now) is None
    assert latest_completed_future(recorded(now,minutes_before=60),now) is None
    assert latest_completed_future(recorded(now,resolution="D"),now) is None

def test_backfill_produces_copy_only_preserving_original(tmp_path):
    origin=tmp_path/"live.db"
    target=tmp_path/"normalized.db"
    store=Store(origin)
    now=datetime.fromisoformat("2026-11-05T10:30:00+05:30")
    calls=recorded(now)
    with store.transaction() as conn:
        store.event(conn,observed_at=now,kind="scheduled_research",
                    source="test",payload={"calls":calls})
    report=backfill_copy(origin,target)
    assert report["new_futures_rows"]==1
    assert origin.exists() and target.exists()
    with sqlite3.connect(origin) as src, sqlite3.connect(target) as dst:
        assert src.execute("SELECT count(*) FROM futures_data").fetchone()[0]==0
        assert dst.execute("SELECT count(*) FROM futures_data").fetchone()[0]==1
        assert dst.execute("SELECT exchange_at_utc FROM events").fetchone()[0] is None
    try:
        backfill_copy(origin,target)
    except FileExistsError:
        pass
    else:
        raise AssertionError("A past normalized snapshot must never be overwritten")
