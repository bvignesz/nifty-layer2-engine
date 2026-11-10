from datetime import date,datetime,timedelta,timezone
import pytest
from nifty_l2.daily_fyers_collector import collect_daily,save_daily,normalise_daily,windows
from nifty_l2.storage import IST

def fake_ohlcv(asof):
    end=date.fromisoformat(asof)-timedelta(days=1)
    days=[];d=end
    while len(days)<255:
        if d.weekday()<5:days.append(d)
        d-=timedelta(days=1)
    return [[int(datetime(day.year,day.month,day.day,
             tzinfo=timezone.utc).timestamp()),
             20000+i*4-2,20000+i*4+5,20000+i*4-4,
             20000+i*4,100000] for i,day in enumerate(reversed(days))]

def test_fyers_daily_converts_only_completed_1d_and_validates_last_session(tmp_path):
    asof="2026-11-10"
    rows=fake_ohlcv(asof)
    calls=[]
    def transport(op,*,params):
        assert op=="history"
        assert params["resolution"]=="D"
        calls.append(params)
        return {"s":"ok","candles":[r for r in rows if
            params["range_from"]<=datetime.fromtimestamp(r[0],timezone.utc).date().isoformat()<=params["range_to"]]}
    record=collect_daily(transport,asof=asof,index_symbol="NSE:NIFTY50-INDEX",
                         benchmark_symbol="NSE:BENCHMARK-INDEX")
    assert record["verified_daily_context"]["status"]=="VERIFIED_PREVIOUS_SESSION_CONTEXT"
    assert record["verified_daily_context"]["last_completed_session"]=="2026-11-09"
    assert len(record["index_bars"])==255
    assert len(calls)==2*len(windows(asof=asof))
    assert all((date.fromisoformat(p["range_to"])-date.fromisoformat(p["range_from"])).days<=330
                for p in calls)
    out=tmp_path/"daily-context.json"
    save_daily(out,record)
    assert out.stat().st_mode&0o777==0o600
    assert all(r["bar_status"]=="COMPLETED" for r in record["index_bars"])

def test_fyers_daily_rejects_missing_or_conflicting_source():
    asof="2026-11-10"
    rows=fake_ohlcv(asof)
    with pytest.raises(ValueError,match="unavailable"):
        normalise_daily([{"s":"error"}],asof=asof)
    bad=[*rows,[*rows[-1]]]
    bad[-1][4]=bad[-1][4]+4
    with pytest.raises(ValueError,match="conflicting"):
        normalise_daily([{"s":"ok","candles":bad}],asof=asof)

def test_fyers_daily_excludes_partial_current_day():
    asof="2026-11-10"
    bar=[int(datetime(2026,11,10,0,0,tzinfo=timezone.utc).timestamp()),
      100,110,90,105,10]
    assert normalise_daily([{"s":"ok","candles":[bar]}],asof=asof)==[]
