from datetime import datetime,timedelta
import pytest
from nifty_l2.synchronized_greeks_capture import capture,save_new

def test_bracket_option_chain_with_futures_quotes_and_no_orders(tmp_path):
    t=datetime.fromisoformat("2026-11-05T10:30:00+05:30")
    ticks=iter([t+timedelta(seconds=i) for i in range(8)])
    called=[]
    def broker(op,*,params,credentials):
        called.append((op,params))
        if op=="optionchain" and params["strikecount"]==1:
            return {"s":"ok","data":{"expiryData":[{"expiry":111,"date":"09-11-2026"}]}}
        if op=="optionchain":
            return {"s":"ok","data":{"optionsChain":[
                {"option_type":"CE","symbol":"NSE:C","strike_price":24500,
                "oi":65000,"greeks":{"gamma":.0002,"iv":15,"delta":.5}}]}}
        if op=="quotes":
            return {"s":"ok","d":[{"n":"NSE:NIFTY26NOVFUT","v":{"lp":24500}}]}
        raise AssertionError("Unknown or forbidden endpoint")
    result=capture({}, "NSE:NIFTY26NOVFUT",transport=broker,clock=lambda:next(ticks))
    assert result["status"]=="RECEIPT_BRACKET_UNVERIFIED"
    assert result["exchange_oi_timestamp_verified"] is False
    assert result["oi_units_verified"] is False
    assert len(result["legs"])==1
    assert [x[0] for x in called]==["optionchain","quotes","optionchain","quotes"]
    p=tmp_path/"one.json"
    save_new(p,result)
    assert p.exists()
    with pytest.raises(FileExistsError):
        save_new(p,result)

def test_bracket_rejects_market_price_drift():
    t=datetime.fromisoformat("2026-11-05T10:30:00+05:30")
    ticks=iter([t+timedelta(seconds=i) for i in range(8)])
    price_calls=iter([24500,24700])
    def broker(op,*,params,credentials):
        if op=="optionchain" and params["strikecount"]==1:
            return {"s":"ok","data":{"expiryData":[{"expiry":111,"date":"09-11-2026"}]}}
        if op=="optionchain":
            return {"s":"ok","data":{"optionsChain":[
                {"option_type":"PE","symbol":"NSE:P","strike_price":24500,
                "oi":65000,"greeks":{"gamma":.0002,"iv":15}}]}}
        if op=="quotes":
            return {"s":"ok","d":[{"n":"NSE:NIFTY26NOVFUT","v":{"lp":next(price_calls)}}]}
    result=capture({}, "NSE:NIFTY26NOVFUT",transport=broker,clock=lambda:next(ticks))
    assert result["status"]=="UNSTABLE_QUOTE_BRACKET"
    assert "gamma_model" not in result
