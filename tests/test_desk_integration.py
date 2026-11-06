"""Acceptance tests for the integrated private research desk."""
import json
from datetime import datetime,timedelta
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
import threading

from nifty_l2.desk_readmodel import desk_snapshot
from nifty_l2.desk_pages import render_desk
from nifty_l2.storage import Store,IST
from nifty_l2.web import App,handler_for

def test_desk_no_data_explains_readiness(tmp_path):
    store=Store(tmp_path/"research.db")
    data=desk_snapshot(tmp_path,"2026-11-05")
    assert data["status"]=="NO_DATA"
    assert data["readiness"]["orders_enabled"] is False
    assert data["readiness"]["xgboost_live_trained"] is False
    assert data["counts"]["valid_outcomes"]==0
    assert data["rows"]==[]
    html=render_desk(data)
    assert "RESEARCH DESK" in html
    assert "MANUAL REVIEW ONLY" in html

def test_saved_bull_signal_keeps_watch_but_not_trade_permission(tmp_path):
    directory=tmp_path
    store=Store(directory/"research.db")
    at=datetime(2026,11,5,10,30,tzinfo=IST)
    with store.transaction() as conn:
        for dt in (at-timedelta(minutes=3),at):
            ts=int(dt.timestamp())
            conn.execute("INSERT INTO header_snapshots (ts,ist_time,spot,fut_close,fut_vwap,fut_oi,expiry_date) VALUES (?,?,?,?,?,?,?)",
                (ts,dt.isoformat(),24500,24510,24500,1000000,"09-11-2026"))
            for side,oi in (("CE",50000),("PE",65000)):
                conn.execute("INSERT INTO strike_snapshots (ts,strike,opt_type,symbol,oi,volume,ltp,gamma) VALUES (?,?,?,?,?,?,?,?)",
                    (ts,24500,side,"NSE:TEST"+side,oi,1000,100,0.002))
        eid=store.event(conn,observed_at=at,kind="manual_research",source="test",payload={"kind":"fixture"})
        conn.execute("INSERT INTO signals (event_id,classification,research_only,payload_json) VALUES (?,?,?,?)",
           (eid,"No Trade",1,json.dumps({"final_verdict":"BULL","meta":{"bull_score":7,"bear_score":0,"gex":25.2}})))
    data=desk_snapshot(directory,"2026-11-05")
    row=data["rows"][0]
    assert row["research_watch"]=="CE WATCH"
    assert row["validated_classification"]=="No Trade"
    assert row["trade_permission"]=="MANUAL_REVIEW_ONLY"
    assert "No automatic orders" in row["alert_preview"]
    assert row["data_readiness"]=="COMPARABLE_RECEIPTS"
    assert "BULLISH WATCH" in render_desk(data)

def test_desk_api_uses_existing_auth_guard_and_readonly_database(tmp_path):
    app=App("https://research.example.com","","APP","SECRET",
        tmp_path/"private"/"token.json",require_login=False)
    Store(app.runner.directory/"research.db")
    server=ThreadingHTTPServer(("127.0.0.1",0),handler_for(app))
    thread=threading.Thread(target=server.serve_forever,daemon=True)
    thread.start()
    conn=HTTPConnection(*server.server_address,timeout=5)
    try:
        conn.request("GET","/desk?date=2026-11-05")
        res=conn.getresponse()
        body=res.read()
        assert res.status==200
        assert b"RESEARCH DESK" in body
        conn.request("GET","/api/v1/desk?date=2026-11-05")
        res=conn.getresponse()
        data=json.loads(res.read())
        assert res.status==200
        assert data["status"]=="NO_DATA"
        assert not data["orders_enabled"]
        assert res.getheader("Cache-Control")=="no-store"
        conn.request("GET","/api/v1/desk?date=not-a-date")
        res=conn.getresponse()
        assert res.status==400
        res.read()
    finally:
        conn.close()
        server.shutdown()
        server.server_close()
        thread.join()
