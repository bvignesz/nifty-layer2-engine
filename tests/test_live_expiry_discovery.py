from datetime import datetime,timezone,timedelta
import pytest
from nifty_l2.live_feed import discover_front_expiry
def test_auto_expiry_uses_broker_expiry_ids_and_rollover():
    now=datetime(2026,11,6,5,tzinfo=timezone.utc)
    t=int(now.timestamp())
    calls=[]
    def transport(op,*,params):
        calls.append((op,params))
        return {"s":"ok","data":{"expiryData":[
           {"expiry":str(t-3600),"date":"expired"},
           {"expiry":str(t+7*86400),"date":"next-week"},
           {"expiry":str(t+2*86400),"date":"front"}]}}
    eid,label=discover_front_expiry(transport,now=now)
    assert eid==t+2*86400
    assert label=="front"
    assert calls[0][0]=="optionchain"
    assert calls[0][1]["timestamp"]==""
def test_auto_expiry_refuses_missing_broker_list():
    now=datetime(2026,11,6,5,tzinfo=timezone.utc)
    with pytest.raises(ValueError):
        discover_front_expiry(lambda *a,**k:{"s":"ok","data":{"expiryData":[]}},now=now)
