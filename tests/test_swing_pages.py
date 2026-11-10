"""Dedicated swing page: read-only actual EOD results, no fabricated stock tips."""
import csv,json,threading
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
import pytest
from nifty_l2.swing_pages import swing_snapshot,render_swing
from nifty_l2.desk_preview import make_handler
from nifty_l2.storage import Store

def write_csv(path):
    data=[
        {"Symbol":"SAMPLE_A","As_Of":"2026-11-05",
         "Strategy_Track":"EMA_PULLBACK","Research_State":"WATCH",
         "Actionability":"RESEARCH_ONLY","Close":"102",
         "RS_Excess_20D_Pct":"4.1","Williams_R_3":"-45",
         "Setup_POC":"","VAL":"","VAH":"",
         "Stop_Loss_Structural":"97","Risk_Reward_Ratio":"2.1",
         "Data_Quality":"UNVERIFIED"},
        {"Symbol":"SAMPLE_B","As_Of":"2026-11-05",
         "Strategy_Track":"RS_WR3_POC","Research_State":"WATCH",
         "Actionability":"RESEARCH_ONLY","Close":"220",
         "RS_Excess_20D_Pct":"5.2","Williams_R_3":"-88",
         "Setup_POC":"216","VAL":"210","VAH":"227",
         "Stop_Loss_Structural":"208","Risk_Reward_Ratio":"1.9",
         "Data_Quality":"UNVERIFIED"},
        {"Symbol":"SAMPLE_C","As_Of":"2026-11-05",
         "Strategy_Track":"LARRY_AD_BOF","Research_State":"WATCH",
         "Actionability":"RESEARCH_ONLY","Close":"180",
         "RS_Excess_20D_Pct":"3.0","Williams_R_3":"-65",
         "Setup_POC":"","VAL":"","VAH":"",
         "Stop_Loss_Structural":"173","Risk_Reward_Ratio":"2.0",
         "Data_Quality":"UNVERIFIED"}]
    with path.open("w",newline="") as f:
        w=csv.DictWriter(f,fieldnames=data[0])
        w.writeheader()
        w.writerows(data)

def test_no_data_is_explicit_not_demo_stock(tmp_path):
    data=swing_snapshot(tmp_path)
    assert data["status"]=="NO_DATA"
    assert data["rows"]==[]
    assert not data["orders_enabled"]
    html=render_swing(data)
    assert "No saved candidates" in html
    assert "/desk" in html

def test_all_three_strategies_and_filter(tmp_path):
    write_csv(tmp_path/"eod_scanner_results.csv")
    data=swing_snapshot(tmp_path)
    assert data["displayed"]==3
    assert "SAMPLE_A" in render_swing(data)
    assert "SAMPLE_C" in render_swing(data)
    assert swing_snapshot(tmp_path,track="EMA_PULLBACK")["rows"][0]["Symbol"]=="SAMPLE_A"
    assert swing_snapshot(tmp_path,track="RS_WR3_POC")["rows"][0]["Symbol"]=="SAMPLE_B"
    assert swing_snapshot(tmp_path,track="LARRY_AD_BOF")["rows"][0]["Symbol"]=="SAMPLE_C"
    with pytest.raises(ValueError):
        swing_snapshot(tmp_path,track="UNKNOWN")

def test_preview_swing_routes_readonly(tmp_path):
    Store(tmp_path/"research.db")
    write_csv(tmp_path/"eod_scanner_results.csv")
    server=ThreadingHTTPServer(("127.0.0.1",0),make_handler(tmp_path/"research.db"))
    thread=threading.Thread(target=server.serve_forever,daemon=True)
    thread.start()
    conn=HTTPConnection(*server.server_address,timeout=5)
    try:
        conn.request("GET","/swing")
        res=conn.getresponse()
        html=res.read()
        assert res.status==200
        assert b"INDIAN SWING ENGINE" in html
        assert b"SAMPLE_B" in html
        conn.request("GET","/api/v1/swing?track=EMA_PULLBACK")
        res=conn.getresponse()
        data=json.loads(res.read())
        assert data["displayed"]==1
        assert data["rows"][0]["Symbol"]=="SAMPLE_A"
        conn.request("GET","/swing?track=INVALID")
        res=conn.getresponse()
        assert res.status==400
        res.read()
    finally:
        conn.close()
        server.shutdown()
        server.server_close()
        thread.join()
