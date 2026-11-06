from datetime import datetime,timezone
import pytest
from nifty_l2.live_feed import discover_front_future

def test_future_rollover_uses_broker_chain_not_guessed_symbol():
    now=datetime(2026,11,6,5,tzinfo=timezone.utc)
    t=int(now.timestamp())
    def transport(op,*,params):
        assert op=="futureschain"
        assert params["symbol"]=="NSE:NIFTY50-INDEX"
        return {"s":"ok","data":[
            {"symbol":"NSE:NIFTY50-INDEX","expiry":""},
            {"symbol":"NSE:NIFTY26NOVFUT","expiry":str(t+20*86400)},
            {"symbol":"NSE:NIFTY26DECFUT","expiry":str(t+48*86400)},
            {"symbol":"NSE:NIFTY26OCTFUT","expiry":str(t-7*86400)}
        ]}
    assert discover_front_future(transport,now=now)=="NSE:NIFTY26NOVFUT"

def test_future_discovery_fails_closed_when_no_contract():
    now=datetime(2026,11,6,5,tzinfo=timezone.utc)
    with pytest.raises(ValueError):
        discover_front_future(lambda *a,**k:{"s":"ok","data":[]},now=now)
