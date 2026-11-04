"""Phase 1: read-only, point-in-time research feature export; no model fitting."""
import argparse
import csv
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import sqlite3

FIELDS = ('event_id','event_kind','observed_at_utc','exchange_at_utc','quality_status',
          'original_verdict','bull_score','bear_score','spot','fut_close','vix',
          'gex_scenario','put_wall','call_wall','seller_lead',
          'bull_checks_pass','bear_checks_pass','unavailable_checks',
          'feature_status','label_status')


def numeric(value):
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def extract(db_path):
    """Read immutable events without inferring labels or future information."""
    db_path = Path(db_path).expanduser().resolve()
    if not db_path.is_file():
        raise FileNotFoundError('Research database does not exist')
    with sqlite3.connect(db_path.as_uri() + '?mode=ro', uri=True) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("""
            SELECT e.event_id,e.kind AS event_kind,e.observed_at_utc,e.exchange_at_utc,e.status,
                   e.payload_json,s.payload_json AS signal_json
            FROM events e JOIN signals s ON s.event_id=e.event_id
            WHERE e.kind IN ('scheduled_research','manual_research')
            ORDER BY e.observed_at_utc,e.event_id
        """).fetchall()
        result = []
        for event in rows:
            payload = json.loads(event['payload_json'])
            state = json.loads(event['signal_json'])
            meta = state.get('meta') or {}
            if not isinstance(meta, dict):
                meta = {}
            checks = conn.execute(
                'SELECT side,status FROM check_results WHERE event_id=?',
                (event['event_id'],)).fetchall()
            # Do not silently treat absent checks as failed checks.
            complete = len(checks) == 18 and all(
                sum(1 for x in checks if x['side']==side)==9 for side in ('BULL','BEAR'))
            passes = {side:sum(x['status']=='PASS' for x in checks if x['side']==side)
                      for side in ('BULL','BEAR')}
            unavailable = sum(x['status'] in ('UNAVAILABLE','STALE') for x in checks)
            quality = payload.get('input_quality')
            status = ('RESEARCH_UNVALIDATED' if complete and
                      isinstance(quality, dict) and
                      quality.get('exchange_quote_freshness') == 'UNVERIFIED'
                      else 'INCOMPLETE_OR_UNVERIFIED')
            result.append(dict(
                event_id=event['event_id'],
                event_kind=event['event_kind'],
                observed_at_utc=event['observed_at_utc'],
                exchange_at_utc=event['exchange_at_utc'] or '',
                quality_status=event['status'],
                original_verdict=str(state.get('final_verdict') or ''),
                bull_score=numeric(meta.get('bull_score')),
                bear_score=numeric(meta.get('bear_score')),
                spot=numeric(meta.get('spot')),
                fut_close=numeric(meta.get('fut_close')),
                vix=numeric(meta.get('vix')),
                gex_scenario=numeric(meta.get('gex')),
                put_wall=numeric(meta.get('put_wall')),
                call_wall=numeric(meta.get('call_wall')),
                seller_lead=str(meta.get('seller_lead') or ''),
                bull_checks_pass=passes['BULL'] if complete else None,
                bear_checks_pass=passes['BEAR'] if complete else None,
                unavailable_checks=unavailable if complete else None,
                feature_status=status,
                label_status='NOT_AVAILABLE'))
    return result


def export(db_path, output):
    output = Path(output).expanduser().resolve()
    if output.exists():
        raise FileExistsError('Refusing to overwrite an existing dataset')
    rows = extract(db_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('x', newline='', encoding='utf-8') as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', required=True, help='Existing research.db (read only)')
    parser.add_argument('--out', required=True, help='New CSV path; overwrite forbidden')
    args = parser.parse_args()
    count = export(args.db, args.out)
    print(f'Exported {count} research rows. No labels or ML training generated.')


if __name__ == '__main__':
    main()
