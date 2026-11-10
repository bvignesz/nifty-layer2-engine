from nifty_l2.premarket_regime import classify_regime

ARGS=dict(spot=24550,previous_value_high=24500,
   previous_value_low=24300,opening_high=24520,opening_low=24440,
   futures_price=24560,futures_vwap=24490,
   vix_now=14,vix_prior=13.8,quotes_fresh=True,
   completed_bar_verified=True)

def test_expansion_bull_and_bear():
    result=classify_regime(**ARGS)
    assert result["regime"]=="TREND_EXPANSION"
    assert result["bias"]=="BULLISH_RESEARCH"
    bear=dict(ARGS,spot=24250,futures_price=24240,
              futures_vwap=24320)
    assert classify_regime(**bear)["bias"]=="BEARISH_RESEARCH"
def test_missing_data_and_event_blocks():
    assert classify_regime(**{**ARGS,"quotes_fresh":False})["bias"]=="IGNORE"
    assert classify_regime(**{**ARGS,"scheduled_event":True})["regime"]=="EVENT_VOLATILITY"
def test_range_is_ignore():
    result=classify_regime(**{**ARGS,"spot":24475,
        "futures_price":24470,"futures_vwap":24490})
    assert result["regime"]=="RANGE_OR_MIXED"
