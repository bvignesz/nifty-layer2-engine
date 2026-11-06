"""Standalone read-only development preview of the NIFTY research desk.

Loopback-bound, SSH-tunnel-only; no FYERS credentials or writes, no forms,
no login, no collector, no production service restarts. An exact research.db
file path is required and opened only by the underlying SQLite read models.
"""
import argparse
from datetime import datetime
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import json
from pathlib import Path
from urllib.parse import parse_qs,urlparse
from .storage import IST
from .desk_readmodel import desk_snapshot
from .desk_pages import render_desk

def make_handler(db_path):
    database=Path(db_path).expanduser().resolve()
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*_):
            pass
        def do_GET(self):
            parsed=urlparse(self.path)
            if parsed.path not in ("/desk","/api/v1/desk","/"):
                self.send_error(404);return
            query=parse_qs(parsed.query)
            day=query.get("date",[datetime.now(IST).date().isoformat()])[0]
            try:
                data=desk_snapshot(database.parent,day,
                    limit=query.get("limit",["40"])[0])
                is_json=parsed.path=="/api/v1/desk"
                body=(json.dumps(data,ensure_ascii=False,allow_nan=False)
                    if is_json else render_desk(data)).encode("utf-8")
            except (ValueError,OverflowError):
                self.send_error(400,"Bad date or limit");return
            self.send_response(200)
            self.send_header("Content-Type",
                "application/json; charset=utf-8" if is_json
                else "text/html; charset=utf-8")
            self.send_header("Cache-Control","no-store")
            self.send_header("X-Content-Type-Options","nosniff")
            self.send_header("Referrer-Policy","no-referrer")
            self.send_header("Content-Security-Policy",
               "default-src 'none'; style-src 'unsafe-inline'; frame-ancestors 'none'; base-uri 'none'")
            self.send_header("Content-Length",str(len(body)))
            self.end_headers()
            self.wfile.write(body)
    return Handler

def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db",type=Path,required=True,help="Existing research.db, read only")
    parser.add_argument("--port",type=int,default=8787)
    args=parser.parse_args(argv)
    p=args.db.expanduser().resolve()
    if p.name!="research.db" or not p.is_file():
        parser.error("Pass an existing research.db path; no database is created")
    if not (1024<=args.port<=65535):
        parser.error("Use a nonprivileged port")
    server=ThreadingHTTPServer(("127.0.0.1",args.port),make_handler(p))
    print(f"Read-only research preview at http://127.0.0.1:{args.port}/desk")
    print("Use SSH port forwarding; do not expose this unauthenticated preview publicly.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()

if __name__=="__main__":
    main()
