"""Explicit opt-in Telegram RESEARCH alert delivery.

Single one-shot send, not an autonomous bot or a trading order.
Only current-session comparable saved receipts, not fabricated one-minute data.
Requires Telegram credentials from environment; never log them.
"""
import argparse
from datetime import datetime,timezone
import hashlib,json,os
from pathlib import Path
from urllib.request import Request,urlopen
from urllib.error import HTTPError,URLError
from .desk_readmodel import desk_snapshot
from .storage import IST

def prepare_alert(data,*,now=None,max_age_seconds=240):
    now=now or datetime.now(timezone.utc)
    if now.tzinfo is None:raise ValueError("aware clock required")
    if data.get("date_ist")!=now.astimezone(IST).date().isoformat():
        return {"status":"SKIPPED_OLD_SESSION"}
    rows=data.get("rows",[])
    if not rows:return {"status":"SKIPPED_NO_DATA"}
    row=rows[0]
    bias=row.get("legacy_research_bias")
    if bias not in ("BULL","BEAR"):
        return {"status":"SKIPPED_NO_DIRECTIONAL_WATCH"}
    if row.get("data_readiness")!="COMPARABLE_RECEIPTS":
        return {"status":"SKIPPED_UNVERIFIED_RECEIPTS"}
    ts=row.get("observed_epoch")
    if not isinstance(ts,int):
        return {"status":"SKIPPED_MISSING_TIME"}
    age=now.timestamp()-ts
    if age<0 or age>max_age_seconds:
        return {"status":"SKIPPED_STALE_DATA"}
    date=now.astimezone(IST)
    if not (date.hour==9 and date.minute>=15 or date.hour in (10,11,12,13,14)
      or date.hour==15 and date.minute<30):
        return {"status":"SKIPPED_OUTSIDE_REGULAR_SESSION"}
    message=row.get("alert_preview")
    if not isinstance(message,str) or not message:
        return {"status":"SKIPPED_MISSING_MESSAGE"}
    key=hashlib.sha256((str(ts)+"|"+bias).encode()).hexdigest()
    return {"status":"READY_RESEARCH_ONLY","key":key,"text":message}

def _send_https(token,chat_id,message):
    url="https://api.telegram.org/bot"+token+"/sendMessage"
    body=json.dumps({"chat_id":chat_id,"text":message,
        "disable_web_page_preview":True}).encode()
    req=Request(url,data=body,headers={"Content-Type":"application/json"},
                method="POST")
    try:
        with urlopen(req,timeout=12) as response:
            data=json.load(response)
    except (HTTPError,URLError,TimeoutError,OSError,ValueError):
        raise RuntimeError("Telegram delivery failed") from None
    if not data.get("ok"):
        raise RuntimeError("Telegram delivery not acknowledged")

def deliver_once(prepared,*,token,chat_id,marker_dir,transport=None):
    if prepared.get("status")!="READY_RESEARCH_ONLY":
        return {"status":prepared.get("status","SKIPPED")}
    if not token or not chat_id:
        return {"status":"CONFIGURATION_MISSING"}
    marker_dir=Path(marker_dir).expanduser().resolve()
    marker_dir.mkdir(parents=True,exist_ok=True,mode=0o700)
    key=prepared["key"]
    if not isinstance(key,str) or len(key)!=64 or any(c not in "0123456789abcdef" for c in key):
        raise ValueError("invalid message key")
    flag=marker_dir/(key+".sent")
    # Pre-create sentinel to avoid concurrent duplicate submissions. A failed
    # attempt removes it; an uncertain remote response may still duplicate.
    try:
        fd=os.open(flag,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    except FileExistsError:
        return {"status":"SKIPPED_ALREADY_SUBMITTED"}
    os.close(fd)
    try:
        (transport or _send_https)(token,chat_id,prepared["text"])
    except Exception:
        flag.unlink(missing_ok=True)
        return {"status":"DELIVERY_FAILED"}
    return {"status":"RESEARCH_ALERT_SENT","orders_enabled":False}

def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db",type=Path,required=True)
    parser.add_argument("--send",action="store_true",help="Actually send one eligible research alert")
    parser.add_argument("--marker-dir",type=Path,required=True)
    args=parser.parse_args(argv)
    db=args.db.expanduser().resolve()
    if db.name!="research.db" or not db.is_file():
        parser.error("Existing research.db required; collector not modified")
    day=datetime.now(IST).date().isoformat()
    data=desk_snapshot(db.parent,day,limit=5)
    prepared=prepare_alert(data)
    if not args.send:
        print("Dry-run:",prepared.get("status"),"key:",prepared.get("key","none"))
        return 0
    result=deliver_once(prepared,
        token=os.environ.get("NIFTY_TELEGRAM_BOT_TOKEN",""),
        chat_id=os.environ.get("NIFTY_TELEGRAM_CHAT_ID",""),
        marker_dir=args.marker_dir)
    print(result["status"])
    return 0 if result["status"] in ("RESEARCH_ALERT_SENT",
         "SKIPPED_ALREADY_SUBMITTED","SKIPPED_NO_DATA",
         "SKIPPED_NO_DIRECTIONAL_WATCH","SKIPPED_STALE_DATA",
         "SKIPPED_UNVERIFIED_RECEIPTS","SKIPPED_OUTSIDE_REGULAR_SESSION",
         "SKIPPED_OLD_SESSION") else 2

if __name__=="__main__":
    raise SystemExit(main())
