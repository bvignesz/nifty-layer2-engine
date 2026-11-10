from datetime import datetime,timedelta,timezone
from nifty_l2.preopen_context import evaluate_preopen,FIELDS
from nifty_l2.storage import IST
def inputs(now):
    vals={"gift_gap_pct":.45,"global_futures_pct":.2,
          "vix_change_pct":-1.0,"fii_futures_ls_ratio":1.15,
          "gift_vs_previous_value_area_pct":.3}
    return {"date_ist":now.astimezone(IST).date().isoformat(),
       **{k:{"value":v,"observed_at_utc":now.isoformat(),"source_verified":True}
         for k,v in vals.items()}}
def test_preopen_bullish_research_and_source_gate():
    now=datetime(2026,11,11,3,0,tzinfo=timezone.utc)
    assert evaluate_preopen(inputs(now),now=now)["bias"]=="BULL"
    assert evaluate_preopen(inputs(now),now=now,event_risk=True)["bias"]=="IGNORE"
    incomplete=inputs(now);incomplete["gift_gap_pct"]["source_verified"]=False
    assert evaluate_preopen(incomplete,now=now)["bias"]=="IGNORE"
    stale=inputs(now)
    stale["gift_gap_pct"]["observed_at_utc"]=(now-timedelta(hours=2)).isoformat()
    assert evaluate_preopen(stale,now=now)["status"].startswith("STALE")
def test_preopen_exchange_holiday_is_closed():
    now=datetime(2026,11,10,3,0,tzinfo=timezone.utc)
    assert evaluate_preopen(inputs(now),now=now)["status"]=="EXCHANGE_CLOSED"
