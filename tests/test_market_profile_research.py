import pytest
from nifty_l2.market_profile_research import approximate_volume_profile,opening_range

def candle(ts,lo,hi,vol,sec=180):
    return {"ts":ts,"open":lo,"high":hi,"low":lo,"close":hi,
            "volume":vol,"seconds":sec}

def test_approximate_value_area_profile_is_deterministic():
    rows=[candle(1,100,100,100),candle(2,100,101,60),
          candle(3,101,102,20)]
    out=approximate_volume_profile(rows,tick_size=1,value_area_fraction=.7)
    assert out["poc"]==100
    assert out["val"]==100
    assert out["vah"]==100  # POC alone covers 130/180 > 70%
    assert out["bar_count"]==3
    assert abs(out["total_volume"]-180)<1e-8
    assert out["tick_accurate"] is False
    assert out["status"]=="APPROXIMATE_FROM_OHLCV"

def test_gapped_volume_distribution_and_value_area_fraction():
    rows=[candle(1,100,100,10),candle(2,102,102,90)]
    out=approximate_volume_profile(rows,tick_size=1)
    assert out["poc"]==102
    assert out["coverage_fraction"]>=.7

def test_profile_rejects_duplicate_bad_bars_and_missing_volume():
    with pytest.raises(ValueError,match="duplicate"):
        approximate_volume_profile([candle(1,1,2,4),candle(1,1,2,4)])
    with pytest.raises(ValueError):
        approximate_volume_profile([candle(1,100,99,2)])
    with pytest.raises(ValueError,match="no traded"):
        approximate_volume_profile([candle(1,100,101,0)])
    with pytest.raises(ValueError,match="out of order"):
        approximate_volume_profile([candle(3,99,100,2),candle(1,99,100,2)])

def test_opening_range_uses_only_completed_bars():
    bars=[candle(0,100,105,50),candle(180,102,108,60),
          candle(360,98,110,80)]
    out=opening_range(bars,start_epoch=0,end_epoch=360)
    assert out["high"]==108 and out["low"]==100
    assert out["observed_bars"]==2

def test_opening_range_rejects_boundary_overlap_and_gaps():
    bars=[candle(120,100,104,50)]
    with pytest.raises(ValueError,match="partial bar"):
        opening_range(bars,start_epoch=0,end_epoch=180)
    with pytest.raises(ValueError,match="missing"):
        opening_range([candle(360,100,104,50)],start_epoch=0,end_epoch=180)
