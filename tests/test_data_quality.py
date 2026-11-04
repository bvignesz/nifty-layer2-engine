"""Market-input quality regressions; no network access required."""
from copy import deepcopy
from datetime import datetime, timedelta
import pytest
from nifty_l2.data_quality import MarketDataQualityError, validate_calls
from test_engine import fixture_calls


def inputs():
    now = datetime.fromisoformat('2026-11-03T09:24:00+05:30')
    return now, fixture_calls(0, now)


def test_complete_recorded_sample_passes_minimum_gate():
    now, calls = inputs()
    result = validate_calls(calls, now)
    assert result['complete_strike_pairs'] == 5
    assert result['exchange_quote_freshness'] == 'UNVERIFIED'


def test_missing_atm_put_is_rejected():
    now, calls = inputs()
    chain = calls[1]['response']['data']['optionsChain']
    chain[:] = [leg for leg in chain if leg.get('option_type') != 'PE']
    with pytest.raises(MarketDataQualityError, match='CE/PE'):
        validate_calls(calls, now)


def test_stale_futures_history_is_rejected():
    now, calls = inputs()
    for candle in calls[4]['response']['candles']:
        candle[0] -= 3600
    with pytest.raises(MarketDataQualityError, match='stale'):
        validate_calls(calls, now)


def test_incomplete_futures_candle_is_rejected():
    now, calls = inputs()
    calls[4]['response']['candles'][-1][0] = int((now - timedelta(seconds=30)).timestamp())
    with pytest.raises(MarketDataQualityError, match='incomplete'):
        validate_calls(calls, now)


def test_futures_rollover_mismatch_is_rejected():
    now, calls = inputs()
    calls[4]['request']['symbol'] = 'NSE:NIFTY26DECFUT'
    with pytest.raises(MarketDataQualityError, match='rollover mismatch'):
        validate_calls(calls, now)


def test_missing_futures_quote_is_rejected():
    now, calls = inputs()
    calls[3]['response']['d'] = []
    with pytest.raises(MarketDataQualityError, match='futures quote'):
        validate_calls(calls, now)
