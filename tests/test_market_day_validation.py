from datetime import datetime,timezone
from nifty_l2.market_day_validation import market_day_report
from nifty_l2.live_feed import store_once

def test_market_validation_empty_and_real_receipts(tmp_path):
    db=tmp_path/"market_feed.db"
    assert market_day_report(db,"2026-11-06")["status"]=="NO_FEED"
    t=datetime(2026,11,6,5,0,tzinfo=timezone.utc).isoformat()
    packet={"receipt_utc":t,"request_start_utc":t,"request_end_utc":t,
       "expiry_id":"123","expiry_date":"2026-11-12",
       "future_symbol":"NSE:NIFTY26NOVFUT","source":"FYERS_READONLY",
       "options":{"legs":[{"symbol":"NSE:EXAMPLECE","side":"CE",
           "strike":24500,"oi":10000}]},
       "futures":{"status":"NO_COMPLETED_BARS","rows":[]}}
    store_once(db,packet)
    out=market_day_report(db,"2026-11-06")
    assert out["receipt_count"]==1
    assert out["status"]=="MARKET_VALIDATION_INCOMPLETE"
    assert out["option_oi_exchange_timestamp_verified"] is False
    assert not out["strategy_proven_profitable"]
