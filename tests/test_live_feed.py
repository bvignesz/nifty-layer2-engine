from datetime import datetime,timezone
import pytest
from nifty_l2.live_feed import normalize_chain,collect_once,store_once,latest_feed

NOW=datetime(2026,11,6,5,0,tzinfo=timezone.utc)
BAR=NOW.timestamp()-180
FUT="NSE:NIFTY26NOVFUT"
CHAIN={"s":"ok","data":{"optionsChain":[
  {"symbol":"NSE:TEST24500CE","strike_price":24500,"option_type":"CE",
    "oi":10000,"volume":5000,"ltp":122,"bid":121,"ask":123,
    "greeks":{"gamma":.001}},
  {"symbol":"NSE:TEST24500PE","strike_price":24500,"option_type":"PE",
    "oi":9000,"volume":4000,"ltp":112,"bid":111,"ask":113,
    "greeks":{"gamma":.0012}}]}}
def fake(op,*,params):
    assert op in ("optionchain","history")
    if op=="optionchain":
        assert params["timestamp"]=="1793990000"
        return CHAIN
    assert params["oi_flag"]=="1"
    return {"s":"ok","candles":[
      [int(BAR),24500,24512,24490,24505,10000,500000],
      [int(BAR)+60,24505,24515,24500,24510,11000,500100]]}

def test_market_feed_one_sample_injectable_and_dedicated(tmp_path):
    packet=collect_once(transport=fake,now=NOW,
        expiry_id=1793990000,future_symbol=FUT)
    assert packet["options"]["exchange_oi_timestamp_verified"] is False
    assert packet["options"]["strike_coverage"]==2
    assert packet["orders_enabled"] is False
    assert packet["futures"]["status"]=="VALIDATED_1M_FUTURES"
    db=tmp_path/"market_feed.db"
    store_once(db,packet)
    assert db.stat().st_mode & 0o777 ==0o600
    current=latest_feed(db)
    assert current["status"]=="RECORDED"
    assert current["receipt"]["options"]["legs"][0]["oi"]==10000
    with pytest.raises(Exception):
        store_once(db,packet) # duplicate receipt not overwritten
    with pytest.raises(ValueError):
        store_once(tmp_path/"research.db",packet)

def test_invalid_duplicate_leg_blocks_and_missing_source_is_empty(tmp_path):
    chain={**CHAIN,"data":{"optionsChain":[*CHAIN["data"]["optionsChain"],CHAIN["data"]["optionsChain"][0]]}}
    with pytest.raises(ValueError,match="Duplicate"):
        normalize_chain(chain,"1",observed_at=NOW)
    assert latest_feed(tmp_path/"market_feed.db")["status"]=="NO_FEED"
