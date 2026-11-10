"""Opt-in official RBI/PIB RSS news importer for the premarket homepage.

Fetches ONLY two pinned official RSS URLs with bounded payload and timeout.
No arbitrary URL, no page-time network calls, no headline sentiment or
automatic trading decisions. Leaves all existing checklist observations alone.
"""
from datetime import datetime,timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.request import build_opener,Request,HTTPRedirectHandler
from urllib.parse import urlparse
import argparse,json,os,tempfile,xml.etree.ElementTree as ET
from .storage import IST
from .premarket_brief import validate_brief,ALLOWED_HOSTS

FEEDS={
 "RBI":"https://rbi.org.in/pressreleases_rss.xml",
 "PIB":"https://pib.gov.in/RssMain.aspx?ModId=6&Lang=1&Regid=1",
}
class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):
        raise ValueError("Unreviewed RSS redirect refused")

def parse_feed(payload,*,source,at):
    if source not in FEEDS:raise ValueError("Unapproved official feed")
    if not isinstance(payload,bytes) or len(payload)>1_000_000:raise ValueError("RSS too large")
    if b"<!DOCTYPE" in payload.upper() or b"<!ENTITY" in payload.upper():
        raise ValueError("DTD/ENTITY not permitted")
    root=ET.fromstring(payload)
    output=[]
    for element in root.findall(".//item")[:30]:
        title=(element.findtext("title") or "").strip()
        link=(element.findtext("link") or "").strip()
        d=(element.findtext("pubDate") or "").strip()
        parsed=urlparse(link)
        if parsed.scheme!="https" or parsed.hostname not in ALLOWED_HOSTS or not title:
            continue
        try:
            published=parsedate_to_datetime(d).astimezone(timezone.utc)
        except (ValueError,TypeError,AttributeError):
            continue
        if not 0<=(at-published).total_seconds()<=3*86400:continue
        output.append({"title":title[:200],"url":link,
            "published_at_utc":published.isoformat()})
    return output

def download_feed(source,*,opener=None):
    if source not in FEEDS:raise ValueError("Unapproved feed")
    op=opener or build_opener(NoRedirect())
    req=Request(FEEDS[source],headers={"User-Agent":"NiftyResearch/1.0",
       "Accept":"application/rss+xml,application/xml,text/xml"})
    with op.open(req,timeout=8) as response:
        body=response.read(1_000_001)
    if len(body)>1_000_000:raise ValueError("Oversized official feed")
    return body

def refresh_news(path,*,now=None,fetch=None):
    now=now or datetime.now(timezone.utc)
    if now.tzinfo is None:raise ValueError("aware time required")
    dest=Path(path).expanduser().resolve()
    if dest.name!="premarket-brief.json":raise ValueError("private premarket-brief.json only")
    existing={}
    if dest.exists():
        if dest.stat().st_size>128_000:raise ValueError("existing brief oversized")
        existing=json.loads(dest.read_text())
    day=now.astimezone(IST).date().isoformat()
    checks=(existing.get("checks",{}) if existing.get("date_ist")==day else {})
    headlines=[]
    failed=[]
    for source in FEEDS:
        try:
            payload=(fetch or download_feed)(source)
            headlines+=parse_feed(payload,source=source,at=now)
        except (OSError,ValueError,ET.ParseError,TimeoutError):
            failed.append(source)
    if failed or not headlines:
        return {"status":"RSS_UNAVAILABLE_NO_CHANGE","failed":failed,
            "news_found":len(headlines)}
    items={x["url"]:x for x in headlines}
    prior=(existing.get("news",[]) if existing.get("date_ist")==day else [])
    for item in prior:
        if isinstance(item,dict) and item.get("url") not in items:
            items[item.get("url")]=item
    data={"date_ist":day,"observed_at_utc":now.isoformat(),
          "checks":checks,"news":list(items.values())[:15]}
    validated=validate_brief(data,now=now)
    dest.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    fd,temp=tempfile.mkstemp(prefix=".brief-",dir=dest.parent)
    try:
        with os.fdopen(fd,"w") as f:
            json.dump(data,f,ensure_ascii=False,allow_nan=False)
            f.flush();os.fsync(f.fileno())
        os.chmod(temp,0o600)
        os.replace(temp,dest)
    finally:
        Path(temp).unlink(missing_ok=True)
    return {"status":"OFFICIAL_RSS_REFRESHED","news_found":len(validated["news"]),
      "failed":[],"orders_enabled":False}

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--directory",type=Path,required=True)
    args=p.parse_args(argv)
    out=refresh_news(args.directory/"premarket-brief.json")
    print(json.dumps(out))
    return 0 if out["status"]=="OFFICIAL_RSS_REFRESHED" else 2

if __name__=="__main__":
    raise SystemExit(main())
