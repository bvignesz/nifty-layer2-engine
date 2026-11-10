from datetime import datetime,timezone
import json
import os
import pytest
from nifty_l2.expired_options_probe import analyze_response,save_report

T=int(datetime(2026,10,29,4,0,tzinfo=timezone.utc).timestamp())
C=["timestamp","open","high","low","close","volume",
   "open_interest","delta","gamma","theta","vega","iv"]
SYM="NSE:NIFTY25MAR23000CE"
def response(rows=None,columns=None):
    return {"s":"ok","schema_version":1,"symbol":SYM,
       "resolution":"1","columns":columns or C,
       "candles":rows if rows is not None else
       [[T,100,102,99,101,1000,100000,.5,.002,-1,2,14],
        [T+60,101,102,100,101,1200,101000,.49,.002,-1,2,14]]}
def run(x):
    return analyze_response(x,symbol=SYM,date_from="2026-10-29",
      date_to="2026-10-29",retrieved_at=datetime(2026,10,30,tzinfo=timezone.utc))
def test_valid_named_columns_and_greeks():
    a=run(response())
    assert a["status"]=="PASS_DATA_AVAILABLE"
    assert a["accepted_bars"]==2
    assert a["bars"][0]["oi"]==100000
    assert a["bars"][0]["greeks"]["gamma"]==.002
    assert a["greeks_coverage"]["gamma"]["missing"]==0
def test_column_reordering_for_optional_fields():
    cols=C[:6]+["gamma","open_interest","iv","theta","delta","vega"]
    values={"timestamp":T,"open":100,"high":102,"low":99,"close":101,"volume":500,
       "open_interest":1000,"gamma":.005,"iv":16,"delta":.5,"theta":-2,"vega":4}
    a=run(response([[values[c] for c in cols]],cols))
    assert a["status"]=="PASS_DATA_AVAILABLE"
    assert a["bars"][0]["greeks"]["gamma"]==.005
def test_null_greeks_not_filled():
    r=response([[T,100,102,99,101,1000,100000,.5,None,None,None,14]])
    a=run(r)
    assert a["status"]=="PASS_DATA_AVAILABLE"
    assert a["bars"][0]["greeks"]["gamma"] is None
    assert a["greeks_coverage"]["gamma"]["missing"]==1
def test_duplicate_or_incomplete_or_outside_session():
    a=run(response([[T,100,102,99,101,1000,100000,.5,.002,-1,2,14]]*2))
    assert a["status"]=="INVALID_DATA"
    assert "DUPLICATE_OR_NONMONOTONIC_BARS" in a["issues"]
    a=run(response([[T+120,100,102,99,101,1000,100000,.5,.002,-1,2,14]]))
    assert a["status"]=="PASS_DATA_AVAILABLE"
    a=run(response([[T-3600,100,102,99,101,1000,100000,.5,.002,-1,2,14]]))
    assert a["status"]=="INVALID_DATA"
def test_schema_mismatch_and_no_data():
    bad=response(columns=C[:6])
    bad["candles"]=[]
    assert run(bad)["status"]=="SCHEMA_CHANGED"
    assert run({"s":"no_data","candles":[]})["status"]=="NO_DATA"
    mismatch=response()
    mismatch["symbol"]="NSE:OTHER"
    assert run(mismatch)["status"]=="SCHEMA_CHANGED"
def test_save_report_is_exclusive_and_private(tmp_path):
    p=tmp_path/"audit.json"
    save_report(p,{"status":"NO_DATA"})
    assert p.stat().st_mode & 0o777 ==0o600
    with pytest.raises(FileExistsError):save_report(p,{"status":"ERROR"})
    assert json.loads(p.read_text())["status"]=="NO_DATA"
