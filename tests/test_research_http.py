import json
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
import threading
from nifty_l2.web import App,handler_for
from nifty_l2.storage import Store

def test_research_json_routes_and_pages_are_safe(tmp_path):
    app=App("https://research.example.com","", "APP", "SECRET",
            tmp_path/"private"/"token.json",require_login=False)
    Store(app.runner.directory/"research.db")
    server=ThreadingHTTPServer(("127.0.0.1",0),handler_for(app))
    thread=threading.Thread(target=server.serve_forever,daemon=True)
    thread.start()
    conn=HTTPConnection(*server.server_address,timeout=5)
    try:
        for path in ("/api/v1/research?date=2026-11-05",
                     "/api/v1/expiries?date=2026-11-05&strike=24450",
                     "/api/v1/readiness"):
            conn.request("GET",path)
            response=conn.getresponse()
            payload=json.loads(response.read())
            assert response.status==200
            assert response.getheader("Cache-Control")=="no-store"
            assert payload["status"] in ("NO_DATA","RESEARCH_ONLY")
        conn.request("GET","/api/v1/research?date=not-a-date")
        resp=conn.getresponse()
        assert resp.status==400
        resp.read()
        for path in ("/research","/expiries","/eod","/validation"):
            conn.request("GET",path)
            resp=conn.getresponse()
            assert resp.status==200
            assert b"PRO TRADER ACADEMY" in resp.read()
    finally:
        conn.close()
        server.shutdown()
        server.server_close()
        thread.join()
