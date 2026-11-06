from datetime import datetime,timezone
from nifty_l2.futures_one_minute import normalize_completed_futures_1m,futures_oi_quadrant

# 2026-11-06 04:00 UTC = 09:30 IST
T=int(datetime(2026,11,6,4,0,tzinfo=timezone.utc).timestamp())
NOW=datetime(2026,11,6,4,3,tzinfo=timezone.utc)
S="NSE:NIFTY26NOVFUT"

def test_completed_bar_and_futures_long_build():
    a=normalize_completed_futures_1m({"s":"ok","candles":[
      [T,24400,24420,24390,24410,1000,100000],
      [T+60,24410,24425,24400,24420,1100,100200]]},
      symbol=S,retrieved_at=NOW)
    assert a["status"]=="VALIDATED_1M_FUTURES"
    assert a["rows"][0]["completed"]
    assert futures_oi_quadrant(*a["rows"])=="LONG_BUILDUP_PROXY"
    assert not a["option_oi_one_minute_verified"]

def test_conflicting_duplicates_and_missing_oi_are_blocked():
    a=normalize_completed_futures_1m({"s":"ok","candles":[
      [T,24400,24420,24390,24410,1000,100000],
      [T,24400,24420,24390,24411,1000,100000]]},
      symbol=S,retrieved_at=NOW)
    assert a["status"]=="DATA_QUALITY_BLOCKED"
    assert "CONFLICTING_DUPLICATE_BAR" in a["issues"]
    assert a["rows"]==[]
    b=normalize_completed_futures_1m({"s":"ok","candles":[
      [T,24400,24420,24390,24410,1000]]},symbol=S,retrieved_at=NOW)
    assert "MISSING_OI_OR_INVALID_ROW" in b["issues"]

def test_incomplete_future_bar_skipped():
    a=normalize_completed_futures_1m({"s":"ok","candles":[
      [T+120,24400,24420,24390,24410,1000,100000]]},
      symbol=S,retrieved_at=datetime(2026,11,6,4,2,30,tzinfo=timezone.utc))
    assert a["status"]=="NO_COMPLETED_BARS"

def test_quadrant_requires_exact_adjacent_completed_same_symbol():
    a={"ts":T,"symbol":S,"close":24410,"oi":200,"completed":True}
    b={"ts":T+120,"symbol":S,"close":24420,"oi":100,"completed":True}
    assert futures_oi_quadrant(a,b)=="UNAVAILABLE"
