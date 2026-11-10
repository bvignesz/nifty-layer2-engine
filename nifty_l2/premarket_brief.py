"""Pre-market evidence and news read model. No implicit sentiment prediction.

Read a PRIVATE, timestamped, manually or separately sourced JSON brief. No
network calls on homepage, no unverified news used as trade permission.
The pre-open checklist is informative: direction can remain UNVERIFIED.
"""
from datetime import datetime,timezone
from pathlib import Path
from urllib.parse import urlparse
import json
from .storage import IST
from .market_calendar import session
ALLOWED_HOSTS=("rbi.org.in","www.rbi.org.in","nseindia.com","www.nseindia.com",
 "nsearchives.nseindia.com","niftyindices.com","www.niftyindices.com",
 "pib.gov.in","www.pib.gov.in")
CHECKLIST=(
 ("GLOBAL_SESSION","Global risk / overnight indices"),
 ("GIFT_NIFTY","GIFT NIFTY gap and prior close"),
 ("INDIA_VIX","VIX level and opening strength"),
 ("PREVIOUS_VALUE_AREA","Previous POC / VAH / VAL"),
 ("FII_DII_CONTEXT","FII/DII and participant positioning"),
 ("MACRO_EVENT_CALENDAR","RBI / inflation / global macro events"),
 ("NEWS_EVENT_RISK","Verified news / scheduled event risk"),
 ("FUTURES_CONTEXT","NIFTY futures premium and prior settlement"),
 ("MARKET_HOLIDAY","Exchange session calendar verified"),
)
def aware(value):
    t=datetime.fromisoformat(str(value).replace("Z","+00:00"))
    if t.tzinfo is None:raise ValueError("timestamp offset required")
    return t.astimezone(timezone.utc)

def validate_brief(data,*,now=None):
    now=now or datetime.now(timezone.utc)
    if now.tzinfo is None:raise ValueError("aware current time required")
    if not isinstance(data,dict):raise ValueError("brief must be object")
    day=now.astimezone(IST).date().isoformat()
    if data.get("date_ist")!=day:raise ValueError("brief is not for current IST day")
    received=aware(data["observed_at_utc"])
    lag=(now-received).total_seconds()
    if lag<0 or lag>12*3600:raise ValueError("brief receipt stale or future")
    raw=data.get("checks",{})
    if not isinstance(raw,dict):raise ValueError("checks object required")
    checks=[]
    for name,label in CHECKLIST:
        item=raw.get(name,{})
        if not isinstance(item,dict):raise ValueError("bad checklist item")
        state=item.get("status","UNAVAILABLE")
        if state not in ("VERIFIED","UNAVAILABLE","EVENT_RISK","STALE"):
            raise ValueError("unsupported checklist status")
        checked_at=item.get("observed_at_utc")
        if state in ("VERIFIED","EVENT_RISK"):
            if not checked_at or not 0<=(now-aware(checked_at)).total_seconds()<=12*3600:
                state="STALE"
        note=item.get("note","")
        if not isinstance(note,str):raise ValueError("invalid note")
        checks.append({"key":name,"label":label,"status":state,"note":note[:300]})
    news=[]
    for item in data.get("news",[])[:15]:
        if not isinstance(item,dict):continue
        url=item.get("url","")
        parsed=urlparse(url)
        if parsed.scheme!="https" or parsed.hostname not in ALLOWED_HOSTS:continue
        title=item.get("title")
        published=item.get("published_at_utc")
        if not isinstance(title,str) or not title.strip() or not published:continue
        try:
            when=aware(published)
        except (ValueError,TypeError):
            continue
        if when>now or (now-when).total_seconds()>3*86400:continue
        news.append({"title":title[:200],"url":url,"source":parsed.hostname,
            "published_at_utc":when.isoformat()})
    return {"status":"BRIEF_AVAILABLE","date_ist":day,
      "observed_at_utc":received.isoformat(),"checks":checks,"news":news,
      "complete":all(c["status"]=="VERIFIED" for c in checks),
      "event_risk":any(c["status"]=="EVENT_RISK" for c in checks),
      "bias":"UNVERIFIED",  # no automatic headline sentiment inference
      "research_only":True,"orders_enabled":False}

def _calendar_overlay(result,now):
    """Add independently checked exchange holiday context without fabricating other inputs."""
    try:
        trading=session(now.astimezone(IST).date())
    except ValueError:
        return result
    if trading is None:
        updated=[]
        for item in result["checks"]:
            if item["key"]=="MARKET_HOLIDAY":
                updated.append({**item,"status":"EVENT_RISK",
                    "note":"NSE F&O closed today per verified 2026 exchange holiday calendar"})
            else:updated.append(item)
        result={**result,"checks":updated,"event_risk":True,
                "market_session":"EXCHANGE_CLOSED",
                "complete":False}
    else:
        result={**result,"market_session":"SCHEDULED_SESSION"}
    return result

def read_brief(directory,*,now=None):
    now=now or datetime.now(timezone.utc)
    path=Path(directory)/"premarket-brief.json"
    unavailable={"status":"NOT_CONFIGURED","date_ist":now.astimezone(IST).date().isoformat(),
      "checks":[{"key":k,"label":label,"status":"UNAVAILABLE","note":""}
                for k,label in CHECKLIST],"news":[],"complete":False,
      "event_risk":False,"bias":"UNVERIFIED","orders_enabled":False}
    if not path.is_file():return _calendar_overlay(unavailable,now)
    try:
        if path.stat().st_size>128*1024:return _calendar_overlay({**unavailable,"status":"INVALID_OR_TOO_LARGE"},now)
        return _calendar_overlay(validate_brief(json.loads(path.read_text(encoding="utf-8")),now=now),now)
    except (ValueError,KeyError,TypeError,OSError):
        return _calendar_overlay({**unavailable,"status":"STALE_OR_INVALID_BRIEF"},now)
