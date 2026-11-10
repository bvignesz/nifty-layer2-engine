"""Standalone preview serves data from an existing database without writes."""
import json
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
import threading
from nifty_l2.desk_preview import make_handler
from nifty_l2.storage import Store

def test_readonly_desk_preview_existing_database_only(tmp_path):
    db=tmp_path/"research.db"
    Store(db)
    before=db.stat().st_size
    server=ThreadingHTTPServer(("127.0.0.1",0),make_handler(db))
    assert server.server_address[0]=="127.0.0.1"
    t=threading.Thread(target=server.serve_forever,daemon=True)
    t.start()
    c=HTTPConnection(*server.server_address,timeout=5)
    try:
        c.request("GET","/desk?date=2026-11-05")
        r=c.getresponse()
        assert r.status==200
        assert b"RESEARCH DESK" in r.read()
        c.request("GET","/api/v1/desk?date=2026-11-05")
        r=c.getresponse()
        data=json.loads(r.read())
        assert data["status"]=="NO_DATA"
        assert data["readiness"]["orders_enabled"] is False
        c.request("GET","/api/v1/desk?date=bad")
        r=c.getresponse()
        assert r.status==400
        r.read()
        c.request("GET","/run")
        r=c.getresponse()
        assert r.status==404
        r.read()
    finally:
        c.close()
        server.shutdown()
        server.server_close()
        t.join()
    assert db.stat().st_size==before
