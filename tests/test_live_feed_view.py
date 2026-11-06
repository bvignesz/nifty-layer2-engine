from datetime import datetime,timezone
from nifty_l2.live_feed import store_once
from nifty_l2.live_feed_view import live_readmodel,render_live_feed

NOW=datetime(2026,11,6,5,15,tzinfo=timezone.utc)
def packet(at,ceoi):
    stamp=at.isoformat()
    return {"receipt_utc":stamp,"request_start_utc":stamp,"request_end_utc":stamp,
        "source":"FYERS_READONLY","expiry_id":"1793990000","expiry_date":None,
        "future_symbol":"NSE:NIFTY26NOVFUT",
        "options":{"legs":[
          {"symbol":"NSE:EXAMPLECE","side":"CE","strike":24500,"oi":ceoi,"volume_cumulative":500,"ltp":120},
          {"symbol":"NSE:EXAMPLEPE","side":"PE","strike":24450,"oi":12000,"volume_cumulative":400,"ltp":90}]},
        "futures":{"status":"VALIDATED_1M_FUTURES","rows":[{
          "symbol":"NSE:NIFTY26NOVFUT","ts":int(at.timestamp())-60,
          "bar_close_utc":stamp,"close":24495,"oi":500000,"open":24490,
          "high":24500,"low":24480,"volume":5000}]}}

def test_feed_screen_displays_broker_data_and_preserves_provenance(tmp_path):
    data=live_readmodel(tmp_path,now=NOW)
    assert data["status"]=="NO_FEED"
    db=tmp_path/"market_feed.db"
    from datetime import timedelta
    earlier=NOW-timedelta(minutes=3)
    store_once(db,packet(earlier,15000))
    store_once(db,packet(NOW,14500))
    result=live_readmodel(tmp_path,now=NOW)
    assert result["status"]=="LIVE_RECEIPT"
    assert result["ce_wall"]["oi"]==14500
    assert result["wall_oi_delta"]["ce_wall"]==-500
    assert result["futures_1m"]["close"]==24495
    assert result["oi_synchronized_with_futures"] is False
    assert "OI_UNITS" in result["gex"]["status"]
    html=render_live_feed(result)
    assert "14500" in html and "1m futures" in html

def test_stale_feed_disables_live_label(tmp_path):
    from datetime import timedelta
    db=tmp_path/"market_feed.db"
    store_once(db,packet(NOW-timedelta(minutes=10),14500))
    data=live_readmodel(tmp_path,now=NOW)
    assert data["status"]=="STALE_OR_FUTURE_RECEIPT"
