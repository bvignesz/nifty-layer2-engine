"""Fail-closed checks for raw FYERS research inputs (not a signal validator)."""
from datetime import datetime, timezone
import math


class MarketDataQualityError(ValueError):
    pass


def validate_calls(calls, observed_at, *, max_futures_age_seconds=600):
    """Reject missing ATM legs, ambiguous futures identity and stale history.

    Quotes without exchange timestamps are deliberately *not* declared fresh.
    This guard is only a minimum input-integrity gate; it does not validate
    option-chain timestamps, dealer exposure or trading decisions.
    """
    if observed_at.tzinfo is None:
        raise MarketDataQualityError('Observation time must be timezone-aware')
    chains = [c['response'].get('data', {}).get('optionsChain') for c in calls
              if c.get('method') == 'optionchain' and isinstance(c.get('response'), dict)]
    chains = [c for c in chains if isinstance(c, list)]
    if not chains:
        raise MarketDataQualityError('Missing option chain')
    chain = chains[-1]
    by_strike = {}
    underlying = None
    for leg in chain:
        if not isinstance(leg, dict):
            continue
        strike = leg.get('strike_price')
        side = leg.get('option_type')
        if side not in ('CE', 'PE'):
            if isinstance(leg.get('ltp'), (int, float)) and leg['ltp'] > 0:
                underlying = float(leg['ltp'])
            continue
        if not isinstance(strike, (int, float)) or not math.isfinite(strike):
            continue
        if not isinstance(leg.get('symbol'), str) or not leg['symbol']:
            continue
        if not isinstance(leg.get('oi'), (int, float)) or not math.isfinite(leg['oi']) or leg['oi'] < 0:
            continue
        by_strike.setdefault(float(strike), set()).add(side)
    if underlying is None or not math.isfinite(underlying):
        raise MarketDataQualityError('Underlying price unavailable')
    complete = [strike for strike, sides in by_strike.items() if sides == {'CE', 'PE'}]
    if not complete:
        raise MarketDataQualityError('No complete CE/PE strike pairs')
    if min(abs(strike - underlying) for strike in complete) > 200:
        raise MarketDataQualityError('ATM CE/PE coverage missing')

    histories = [c for c in calls if c.get('method') == 'history'
                 and isinstance(c.get('request'), dict) and c['request'].get('oi_flag') == '1']
    if len(histories) != 1:
        raise MarketDataQualityError('Expected one identified futures OI history')
    history = histories[0]
    symbol = history['request'].get('symbol')
    if not isinstance(symbol, str) or not symbol.endswith('FUT'):
        raise MarketDataQualityError('Futures contract identity missing')
    candles = history.get('response', {}).get('candles', [])
    if not isinstance(candles, list) or not candles:
        raise MarketDataQualityError('Futures OI candles unavailable')
    latest = max((c for c in candles if isinstance(c, (list, tuple)) and len(c) >= 7),
                 key=lambda c: c[0], default=None)
    if latest is None:
        raise MarketDataQualityError('Futures OI candle fields missing')
    try:
        start = datetime.fromtimestamp(float(latest[0]), timezone.utc)
        close, oi = float(latest[4]), float(latest[6])
    except (TypeError, ValueError, OverflowError):
        raise MarketDataQualityError('Invalid futures candle') from None
    age = (observed_at.astimezone(timezone.utc) - start).total_seconds()
    if not 180 <= age <= max_futures_age_seconds:
        raise MarketDataQualityError('Futures candle incomplete, future or stale')
    if not all(map(math.isfinite, (close, oi))) or close <= 0 or oi < 0:
        raise MarketDataQualityError('Invalid futures price or OI')
    return {'futures_symbol': symbol, 'futures_age_seconds': age,
            'complete_strike_pairs': len(complete), 'exchange_quote_freshness': 'UNVERIFIED'}
