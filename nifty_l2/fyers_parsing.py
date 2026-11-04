"""Conservative validation of the notebook's FYERS candle-array format.

Not a complete FYERS collector. Quote/chain exchange-time mappings must be
verified against actual rotated-account responses before live operation.
"""
from datetime import datetime, timedelta
import math
from .storage import IST, timestamp


def completed_futures(raw, *, now, max_age_seconds=300):
    now = datetime.fromisoformat(timestamp(now).replace('Z', '+00:00'))
    accepted, rejected = {}, []
    for row in raw:
        try:
            if len(row) < 7:
                raise ValueError('UNAVAILABLE_OI')
            utc = datetime.fromisoformat(timestamp(row[0]).replace('Z', '+00:00'))
            values = [float(v) for v in row[1:7]]
            o, h, l, c, volume, oi = values
            if not all(math.isfinite(v) for v in values) or not 0 < l <= min(o, c) <= max(o, c) <= h or min(volume, oi) < 0:
                raise ValueError('INVALID_VALUES')
            local = utc.astimezone(IST)
            minute = local.hour * 60 + local.minute
            if not 555 <= minute < 930 or (minute - 555) % 3 or local.second or local.microsecond:
                raise ValueError('OUTSIDE_REGULAR_WINDOW_GRID')
            if utc + timedelta(minutes=3) > now:
                raise ValueError('INCOMPLETE_OR_FUTURE')
            key = timestamp(utc)
            bar = {'exchange_at': key, 'open': o, 'high': h, 'low': l, 'close': c, 'volume': volume, 'oi': oi}
            if key in accepted and accepted[key] != bar:
                raise ValueError('CONFLICTING_DUPLICATE')
            accepted[key] = bar
        except (TypeError, ValueError, OverflowError, OSError) as error:
            rejected.append({'row': row, 'reason': str(error)})
    bars = [accepted[k] for k in sorted(accepted)]
    status = 'UNAVAILABLE'
    if bars:
        last = datetime.fromisoformat(bars[-1]['exchange_at'].replace('Z', '+00:00'))
        age = (now - last - timedelta(minutes=3)).total_seconds()
        status = 'STALE' if age > max_age_seconds else 'VALID'
    if any(r['reason'] == 'CONFLICTING_DUPLICATE' for r in rejected):
        status = 'UNAVAILABLE'
    return {'status': status, 'bars': bars, 'rejected': rejected}
