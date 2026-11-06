"""One-shot or continuous read-only FYERS market feed, separate from legacy.

Option-chain samples have *receipt* timestamps, not exchange-timed OI.
Completed 1m futures candles have bar-close times. NEVER merge the two as if
they were a synchronized trade tape. Isolated market_feed.db; no orders.
"""
import argparse,fcntl,json,os,sqlite3,time
from datetime import datetime,timezone
from pathlib import Path
from . import fyers
from .fyers_integration_probe import load_token
from .futures_one_minute import normalize_completed_futures_1m
from .storage import IST
from .market_calendar import session

DDL="""CREATE TABLE IF NOT EXISTS feed_receipts(
 receipt_utc TEXT PRIMARY KEY, request_start_utc TEXT NOT NULL,
 request_end_utc TEXT NOT NULL, source TEXT NOT NULL, expiry_id TEXT NOT NULL,
 expiry_date TEXT, future_symbol TEXT NOT NULL, json_data TEXT NOT NULL,
 state TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS feed_future_bars(
 symbol TEXT NOT NULL, ts INTEGER NOT NULL, close REAL NOT NULL,
 open REAL NOT NULL, high REAL NOT NULL, low REAL NOT NULL,
 volume REAL NOT NULL, oi REAL NOT NULL,
 receipt_utc TEXT NOT NULL, PRIMARY KEY(symbol,ts)
);
CREATE INDEX IF NOT EXISTS feed_receipts_latest ON feed_receipts(receipt_utc);
"""

def _utc(d):
    return d.astimezone(timezone.utc).isoformat()

def normalize_chain(response,expiry_id,*,observed_at):
    if not isinstance(response,dict) or response.get("s")!="ok":
        raise ValueError("FYERS optionchain rejected")
    payload=response.get("data")
    if not isinstance(payload,dict):raise ValueError("Missing FYERS optionchain data")
    raw=payload.get("optionsChain")
    if not isinstance(raw,list):raise ValueError("Missing optionsChain")
    legs=[]
    seen=set()
    for leg in raw:
        if not isinstance(leg,dict) or leg.get("option_type") not in ("CE","PE"):
            continue
        symbol=leg.get("symbol")
        strike=leg.get("strike_price")
        if not isinstance(symbol,str) or not symbol.startswith("NSE:") or (
            not isinstance(strike,(int,float)) or strike<=0):
            continue
        if symbol in seen:raise ValueError("Duplicate contract")
        seen.add(symbol)
        def value(key):
            v=leg.get(key)
            return v if isinstance(v,(int,float)) and not isinstance(v,bool) and float("-inf")<v<float("inf") else None
        g=leg.get("greeks") if isinstance(leg.get("greeks"),dict) else {}
        legs.append({"symbol":symbol,"strike":strike,"side":leg["option_type"],
            "oi":value("oi"),"volume_cumulative":value("volume"),
            "ltp":value("ltp"),"bid":value("bid"),"ask":value("ask"),
            "gamma":g.get("gamma") if isinstance(g.get("gamma"),(float,int)) else None})
    if not legs:raise ValueError("No valid option legs")
    return {"expiry_id":str(expiry_id),
      "receipt_utc":_utc(observed_at),
      "exchange_oi_timestamp_verified":False,
      "legs":legs,"strike_coverage":len(legs)}

def collect_once(*,transport,now,expiry_id,future_symbol,history_days=None):
    """Injected transport; at most two broker market-data requests."""
    if now.tzinfo is None:raise ValueError("aware clock required")
    if not future_symbol.startswith("NSE:") or "FUT" not in future_symbol:
        raise ValueError("reviewed futures symbol required")
    start=datetime.now(timezone.utc)
    index="NSE:NIFTY50-INDEX"
    chain=transport("optionchain",params={"symbol":index,"strikecount":10,
        "timestamp":str(expiry_id),"greeks":"1"})
    today=now.astimezone(IST).date().isoformat()
    hist=transport("history",params={"symbol":future_symbol,"resolution":"1",
        "date_format":"1","range_from":today,"range_to":today,"cont_flag":"1",
        "oi_flag":"1"})
    end=datetime.now(timezone.utc)
    options=normalize_chain(chain,expiry_id,observed_at=end)
    future=normalize_completed_futures_1m(hist,symbol=future_symbol,retrieved_at=end)
    return {"request_start_utc":_utc(start),"request_end_utc":_utc(end),
      "receipt_utc":_utc(end),"expiry_id":str(expiry_id),
      "expiry_date":None,"future_symbol":future_symbol,"options":options,
      "futures":future,"source":"FYERS_READONLY","orders_enabled":False}

def store_once(db_path,packet):
    path=Path(db_path).expanduser().resolve()
    if path.name!="market_feed.db":
        raise ValueError("use dedicated market_feed.db only")
    path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    with sqlite3.connect(path,timeout=10) as db:
        db.executescript(DDL)
        db.execute("INSERT INTO feed_receipts VALUES(?,?,?,?,?,?,?,?,?)",
            (packet["receipt_utc"],packet["request_start_utc"],
             packet["request_end_utc"],packet["source"],packet["expiry_id"],
             packet["expiry_date"],packet["future_symbol"],
             json.dumps(packet,allow_nan=False),
             packet["futures"]["status"]))
        if packet["futures"]["status"]=="VALIDATED_1M_FUTURES":
            for b in packet["futures"]["rows"]:
                db.execute("""INSERT OR IGNORE INTO feed_future_bars
                   (symbol,ts,close,open,high,low,volume,oi,receipt_utc)
                   VALUES(?,?,?,?,?,?,?,?,?)""",
                   (b["symbol"],b["ts"],b["close"],b["open"],b["high"],
                    b["low"],b["volume"],b["oi"],packet["receipt_utc"]))
    os.chmod(path,0o600)
    return packet["receipt_utc"]

def latest_feed(db_path):
    path=Path(db_path).expanduser().resolve()
    if path.name!="market_feed.db" or not path.is_file():
        return {"status":"NO_FEED","receipt":None}
    with sqlite3.connect(path.as_uri()+"?mode=ro",uri=True,timeout=5) as db:
        row=db.execute("SELECT json_data FROM feed_receipts ORDER BY receipt_utc DESC LIMIT 1").fetchone()
    return {"status":"RECORDED" if row else "NO_FEED",
            "receipt":json.loads(row[0]) if row else None}

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--live",action="store_true",help="Authorize FYERS market-data requests")
    p.add_argument("--once",action="store_true",help="One 2-request sample")
    p.add_argument("--every-seconds",type=int,default=180)
    p.add_argument("--expiry-id",required=True,help="FYERS actual expiry epoch, discovered via chain")
    p.add_argument("--future-symbol",required=True)
    p.add_argument("--db",type=Path,required=True)
    p.add_argument("--token-path",type=Path,default=fyers.TOKEN_PATH)
    args=p.parse_args(argv)
    if not args.live:p.error("--live required")
    if not 180<=args.every_seconds<=3600:
        p.error("Minimum 180-second sampling cadence")
    creds=load_token(args.token_path)
    path=args.db.expanduser().resolve()
    path.parent.mkdir(parents=True,exist_ok=True)
    with open(path.parent/"market-feed.lock","a") as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        def transport(op,*,params):
            return fyers.request(op,params=params,credentials=creds)
        while True:
            now=datetime.now(timezone.utc)
            local=now.astimezone(IST)
            hours=session(local.date())
            if hours and hours[0]<=local<hours[1]:
                try:
                    packet=collect_once(transport=transport,now=now,
                      expiry_id=args.expiry_id,future_symbol=args.future_symbol)
                    store_once(path,packet)
                    print("FYERS_READONLY saved",packet["receipt_utc"],
                         packet["futures"]["status"],flush=True)
                except (RuntimeError,ValueError,OSError,sqlite3.Error):
                    print("Market feed: broker read or validation failed; no fake values written",flush=True)
            else:
                print("Outside NSE regular session; no sample",flush=True)
            if args.once:break
            time.sleep(args.every_seconds)

if __name__=="__main__":
    main()
