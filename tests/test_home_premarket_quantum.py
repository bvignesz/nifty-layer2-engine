"""Home navigation, daily context and macro/news fail-closed acceptance tests."""
from datetime import datetime,timedelta,timezone
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
import json,threading
import pytest
from nifty_l2.daily_alignment import evaluate_daily,alignment_gate
from nifty_l2.premarket_brief import read_brief,validate_brief
from nifty_l2.premarket_news import parse_feed,refresh_news
from nifty_l2.quantum_pages import quantum_snapshot,render_quantum
from nifty_l2.web import App,handler_for

NOW=datetime(2026,11,10,3,0,tzinfo=timezone.utc) # 08:30 IST
def history():
    from datetime import date
    end=date(2026,11,9)
    days=[]
    d=end
    while len(days)<230:
        if d.weekday()<5:
            days.append(d.isoformat())
        d-=timedelta(days=1)
    rows=[]
    for i,day in enumerate(reversed(days)):
        px=20000+i*5
        rows.append({"date":day,"open":px-3,"high":px+7,"low":px-6,
            "close":px,"volume":1000000+i,
            "bar_status":"COMPLETED","source":"VERIFIED_EOD"})
    return rows

def test_daily_nine_context_strict_no_current_day_lookahead():
    x=history()
    today="2026-11-10"
    model=evaluate_daily(x,x,asof=today)
    assert len(model["factors"])==9
    assert model["status"]=="VERIFIED_PREVIOUS_SESSION_CONTEXT"
    assert model["bias"] in ("BULL","BEAR","MIXED")
    with pytest.raises(ValueError):
        evaluate_daily([*x,dict(x[-1],date=today)],x,asof=today)
    with pytest.raises(ValueError,match="last completed"):
        evaluate_daily(x[:-1],x[:-1],asof=today)
    with pytest.raises(ValueError):
        evaluate_daily(x,[*x[:-1]],asof=today)

def test_final_gate_never_places_trade():
    gate=alignment_gate(premarket={"status":"VERIFIED","bias":"BULL"},
        daily={"status":"VERIFIED_PREVIOUS_SESSION_CONTEXT","bias":"BULL"},
        intraday={"status":"VERIFIED_COMPLETED_INTRADAY","bias":"BULL"},
        greeks={"status":"VERIFIED_CONTRACT_CONTEXT","direction":"BULL","quote_fresh":True})
    assert gate["status"]=="ALIGNED_RESEARCH"
    assert gate["verdict"]=="BULL WATCH"
    assert gate["trade_allowed"] is False
    gate=alignment_gate(premarket={"status":"VERIFIED","bias":"BULL"},
        daily={"status":"VERIFIED_PREVIOUS_SESSION_CONTEXT","bias":"BEAR"},
        intraday={"status":"VERIFIED_COMPLETED_INTRADAY","bias":"BULL"},
        greeks={"status":"VERIFIED_CONTRACT_CONTEXT","direction":"BULL","quote_fresh":True})
    assert gate["verdict"]=="IGNORE"

def test_premarket_news_escapes_and_rejects_untrusted_domain(tmp_path):
    data={"date_ist":"2026-11-10","observed_at_utc":NOW.isoformat(),
      "checks":{"INDIA_VIX":{"status":"VERIFIED",
                "observed_at_utc":NOW.isoformat(),"note":"VIX monitored"}},
      "news":[{"title":"<script>alert(1)</script>",
               "url":"https://rbi.org.in/scripts/BS_PressReleaseDisplay.aspx?prid=1",
               "published_at_utc":NOW.isoformat()},
              {"title":"Untrusted","url":"https://evil.invalid/news",
               "published_at_utc":NOW.isoformat()}]}
    f=tmp_path/"premarket-brief.json"
    f.write_text(json.dumps(data))
    brief=read_brief(tmp_path,now=NOW)
    assert brief["status"]=="BRIEF_AVAILABLE"
    assert len(brief["news"])==1
    assert brief["news"][0]["title"].startswith("<script>")
    assert brief["complete"] is False

def test_pib_rss_parser_and_no_write_on_both_feeds_failed(tmp_path):
    rss=(b"<rss><channel><item><title>Macro headline</title>"
         b"<link>https://www.rbi.org.in/Scripts/rss.aspx</link>"
         b"<pubDate>Tue, 10 Nov 2026 02:30:00 GMT</pubDate>"
         b"</item></channel></rss>")
    assert len(parse_feed(rss,source="RBI",at=NOW))==1
    assert parse_feed(b"<rss></rss>",source="RBI",at=NOW)==[]
    def fail(_):raise OSError("mock offline")
    result=refresh_news(tmp_path/"premarket-brief.json",now=NOW,fetch=fail)
    assert result["status"]=="RSS_UNAVAILABLE_NO_CHANGE"
    assert not (tmp_path/"premarket-brief.json").exists()

def test_home_and_quantum_pages_are_separate_and_no_duplicate_strike_table(tmp_path):
    app=App("https://example.com","private-password-123","APP","SECRET",
        tmp_path/"private"/"token.json",require_login=False)
    home=app.page()
    assert "Pre-market checklist" in home
    assert "Connect FYERS" in home and "Run script once" in home
    assert "STRIKE OI TERMINAL" not in home
    assert 'href="/swing"' in home and 'href="/desk"' in home
    assert "Awaiting verified" in home or "UNAVAILABLE" in home
    q=quantum_snapshot(app.runner.directory,now=NOW)
    assert q["decision"]["verdict"]=="IGNORE"
    assert q["daily"]["status"]=="UNAVAILABLE"
    assert "Daily timeframe" in render_quantum(q)
    server=ThreadingHTTPServer(("127.0.0.1",0),handler_for(app))
    t=threading.Thread(target=server.serve_forever,daemon=True)
    t.start()
    client=HTTPConnection(*server.server_address,timeout=5)
    try:
        for route,fragment in [("/quantum",b"Multi-Timeframe Alignment"),
             ("/api/v1/quantum",b"orders_enabled"),
             ("/settings",b"FYERS App Settings")]:
            client.request("GET",route)
            response=client.getresponse()
            assert response.status==200
            assert fragment in response.read()
    finally:
        client.close();server.shutdown();server.server_close();t.join()
