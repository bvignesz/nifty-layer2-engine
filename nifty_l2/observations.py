"""Storage contract for a future validated collector; no network or live signals."""
from .storage import canonical, timestamp


def record_observation(store, *, observed_at, exchange_at, raw_option_chain, futures,
                       checks, state, quality):
    """Atomically store one immutable research observation and all nine checks.

    `quality` is VALID, UNAVAILABLE or STALE. VALID requires a validated exchange
    timestamp supplied by the collector; receipt time must never substitute for it.
    """
    if quality not in ('VALID', 'UNAVAILABLE', 'STALE'):
        raise ValueError('Invalid quality')
    if quality == 'VALID' and exchange_at is None:
        raise ValueError('Validated exchange timestamp required')
    if exchange_at is not None and timestamp(exchange_at) > timestamp(observed_at):
        raise ValueError('Exchange time is after observation')
    expected = {(n, side) for n in range(1, 10) for side in ('BULL', 'BEAR')}
    actual = {(c['number'], c['side']) for c in checks}
    if len(checks) != 18 or actual != expected:
        raise ValueError('Exactly nine checks for each side are required')
    verdict = state.get('classification', 'No Trade')
    if verdict not in ('Bullish', 'Bearish', 'No Trade'):
        raise ValueError('Invalid classification')
    if quality != 'VALID':
        verdict = 'No Trade'
    payload = {'option_chain': raw_option_chain, 'futures': futures, 'checks': checks, 'state': state, 'quality': quality}
    with store.transaction() as conn:
        eid = store.event(conn, observed_at=observed_at, exchange_at=exchange_at,
                          kind='research_observation', source='fyers', payload=payload, status=quality)
        for leg in raw_option_chain:
            conn.execute('INSERT INTO option_snapshots VALUES (?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT DO NOTHING',
                         (eid, leg['symbol'], leg['strike_price'], leg['option_type'], leg.get('expiry'),
                          leg.get('ltp'), leg.get('bid'), leg.get('ask'), leg.get('oi'), leg.get('volume'), canonical(leg)))
        for fut in futures:
            conn.execute('INSERT INTO futures_data VALUES (?,?,?,?,?,?,?) ON CONFLICT DO NOTHING',
                         (eid, fut['symbol'], timestamp(fut['exchange_at']) if fut.get('exchange_at') else None,
                          fut.get('close'), fut.get('vwap'), fut.get('oi'), canonical(fut)))
        for check in checks:
            status = check['status'] if quality == 'VALID' else quality
            conn.execute('INSERT INTO check_results VALUES (?,?,?,?,?) ON CONFLICT DO NOTHING',
                         (eid, check['number'], check['side'], status, canonical(check)))
        conn.execute('INSERT INTO signals VALUES (?,?,1,?) ON CONFLICT DO NOTHING', (eid, verdict, canonical(state)))
    return eid


def record_outcome(store, *, event_id, horizon_minutes, available_at, forward_return, status='AVAILABLE', evidence=None):
    from datetime import datetime, timedelta
    if horizon_minutes not in (9, 15, 30):
        raise ValueError('Unsupported horizon')
    available = timestamp(available_at)
    with store.transaction() as conn:
        row = conn.execute('SELECT observed_at_utc FROM events WHERE event_id=?', (event_id,)).fetchone()
        if row is None:
            raise ValueError('Unknown event')
        minimum = timestamp(datetime.fromisoformat(row[0].replace('Z', '+00:00')) + timedelta(minutes=horizon_minutes))
        if available < minimum:
            raise ValueError('Outcome cannot be available before its horizon')
        payload = canonical({'forward_return': forward_return, 'evidence': evidence})
        prior = conn.execute('SELECT available_at_utc,forward_return,status,payload_json FROM outcomes WHERE event_id=? AND horizon_minutes=?', (event_id, horizon_minutes)).fetchone()
        values = (available, forward_return, status, payload)
        if prior and tuple(prior) != values:
            raise ValueError('Conflicting outcome; retain original and audit correction separately')
        conn.execute('INSERT INTO outcomes VALUES (?,?,?,?,?,?) ON CONFLICT DO NOTHING',
                     (event_id, horizon_minutes, *values[:3], payload))
