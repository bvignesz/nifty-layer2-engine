import json
from datetime import datetime,timedelta
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
import threading

from nifty_l2.microstructure_terminal import read_rows, render
from nifty_l2.storage import Store,IST
from nifty_l2.web import App,handler_for

def test_microstructure_uses_real_same_contract_deltas_and_no_trade(tmp_path):
    directory=tmp_path/"runtime"
    store=Store(directory/"research.db")
    a=datetime(2026,11,5,10,0,tzinfo=IST)
    b=a+timedelta(minutes=3)
    with store.transaction() as db:
        for dt,oi,vol in ((a,65000,200),(b,66300,230)):
            ts=int(dt.timestamp())
            db.execute("INSERT INTO header_snapshots (ts,ist_time,spot,fut_close,fut_vwap,fut_oi,expiry_date) VALUES (?,?,?,?,?,?,?)",
                (ts,dt.isoformat(),24500,24520,24510,1200000,"09-11-2026"))
            db.execute("""INSERT INTO strike_snapshots (ts,strike,opt_type,symbol,oi,volume,ltp,gamma)
                VALUES (?,?,?,?,?,?,?,?)""",(ts,24500,"CE","NSE:EXAMPLECE",oi,vol,125,.0002))
            db.execute("""INSERT INTO strike_snapshots (ts,strike,opt_type,symbol,oi,volume,ltp,gamma)
                VALUES (?,?,?,?,?,?,?,?)""",(ts,24500,"PE","NSE:EXAMPLEPE",42000,100,115,.0002))
        eid=store.event(db,observed_at=b,kind="scheduled_research",
             source="test",payload={"test":True})
        db.execute("INSERT INTO signals (event_id,classification,research_only,payload_json) VALUES (?,?,?,?)",
            (eid,"No Trade",1,json.dumps({"final_verdict":"BULL","meta":{"bull_score":6,"bear_score":1,"gex":25}})))
    data=read_rows(directory,"2026-11-05")
    assert data["status"]=="AVAILABLE"
    assert data["rows"][0]["ce_wall_delta"]["oi_delta"]==1300
    assert data["rows"][0]["ce_wall_delta"]["volume_increment"]==30
    assert data["rows"][0]["ce_observed_subset"]["oi_delta"]==1300
    assert data["rows"][0]["ce_observed_subset"]["volume_increment"]==30
    assert data["rows"][0]["pe_observed_subset"]["oi_delta"]==0
    assert data["rows"][0]["one_minute_candle_verified"] is False
    assert data["rows"][0]["legacy_research_bias"]=="BULL"
    assert data["rows"][0]["validated_classification"]=="No Trade"
    assert data["rows"][1]["ce_wall_delta"]["oi_delta"] is None
    html=render(data)
    assert "NO TRADE" in html
    assert "BULL" in html
    assert "NOT a completed one-minute" in html

def test_microstructure_rejects_noncomparable_contract_or_volume_reset(tmp_path):
    directory=tmp_path/"runtime"
    store=Store(directory/"research.db")
    a=datetime(2026,11,5,10,0,tzinfo=IST)
    b=a+timedelta(minutes=3)
    with store.transaction() as db:
        for dt,sym,vol in ((a,"NSE:OLD",80),(b,"NSE:NEW",70)):
            ts=int(dt.timestamp())
            db.execute("INSERT INTO header_snapshots (ts,spot,expiry_date) VALUES (?,?,?)",
                       (ts,24500,"09-11-2026"))
            db.execute("INSERT INTO strike_snapshots (ts,strike,opt_type,symbol,oi,volume) VALUES (?,?,?,?,?,?)",
                      (ts,24500,"CE",sym,65000,vol))
    data=read_rows(directory,"2026-11-05")
    assert data["rows"][0]["ce_wall_delta"]=={"oi_delta":None,"volume_increment":None}
    assert data["rows"][0]["ce_observed_subset"]["oi_delta"] is None

def test_microstructure_routes_require_login_and_render_empty(tmp_path):
    app=App("https://research.example.com","","APP","SECRET",
          tmp_path/"private"/"token.json",require_login=False)
    Store(app.runner.directory/"research.db")
    server=ThreadingHTTPServer(("127.0.0.1",0),handler_for(app))
    t=threading.Thread(target=server.serve_forever,daemon=True)
    t.start()
    conn=HTTPConnection(*server.server_address,timeout=5)
    try:
        conn.request("GET","/microstructure?date=2026-11-05")
        response=conn.getresponse()
        content=response.read()
        assert response.status==200
        assert b"NIFTY MICROSTRUCTURE" in content
        conn.request("GET","/api/v1/microstructure?date=2026-11-05")
        response=conn.getresponse()
        data=json.loads(response.read())
        assert response.status==200
        assert data["status"]=="NO_DATA"
        conn.request("GET","/api/v1/microstructure?date=bad")
        response=conn.getresponse()
        assert response.status==400
        response.read()
    finally:
        conn.close()
        server.shutdown()
        server.server_close()
        t.join()
