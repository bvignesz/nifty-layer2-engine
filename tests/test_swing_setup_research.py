from datetime import date,timedelta
import pytest
from eod_scanner.swing_setup_research import features,ema

def series():
    start=date(2026,1,1)
    return [{"date":(start+timedelta(days=i)).isoformat(),
      "open":100+i*.3,"high":101+i*.3,"low":99+i*.3,
      "close":100.5+i*.3,"volume":100000} for i in range(45)]

def test_swing_features_have_defined_ranges():
    result=features(series())
    assert result["trend_ema"]
    assert -100<=result["wr3"]<=0
    assert result["larry_ad"]>0
    assert result["research_only"]
    assert not result["bull_bof_support_sweep"]

def test_bof_support_sweep_and_reclaim():
    bars=series()
    support=min(x["low"] for x in bars[-21:-1])
    bars[-1].update(low=support-1,open=support+1,
                    close=support+2,high=support+3)
    result=features(bars)
    assert result["bull_bof_support_sweep"]

def test_invalid_bars_and_short_ema():
    with pytest.raises(ValueError):
        features(series()[:9])
    with pytest.raises(ValueError):
        features(series()+[series()[-1]])
    with pytest.raises(ValueError):
        ema([1,2],10)
