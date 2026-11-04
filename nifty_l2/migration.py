"""Non-destructive, atomic, content-addressed legacy CSV/JSON import."""
import csv
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
from .storage import canonical, digest, timestamp


def read_rows(raw, suffix):
    text = raw.decode('utf-8-sig')
    if suffix.lower() == '.csv':
        reader = csv.DictReader(io.StringIO(text))
        if not reader.fieldnames or len(set(reader.fieldnames)) != len(reader.fieldnames):
            raise ValueError('Missing or duplicate CSV headers')
        rows = list(reader)
        if any(None in r or any(v is None for v in r.values()) for r in rows):
            raise ValueError('Malformed CSV row width')
    elif suffix.lower() == '.json':
        value = json.loads(text)
        rows = value if isinstance(value, list) else [value]
    else:
        raise ValueError('Expected .csv or .json')
    if any(not isinstance(row, dict) for row in rows):
        raise ValueError('Rows must be JSON objects')
    return rows


def classify(row):
    if 'Strike' in row and 'CE_OI' in row:
        return 'legacy_chain'
    if 'Check' in row and 'Bull_Status' in row:
        return 'legacy_check'
    if 'Final_Verdict' in row or 'Signal_Banner' in row:
        return 'legacy_signal'
    return 'legacy_record'


def observed(row, fallback=None):
    for field in ('observed_at_utc', 'IST_Time', 'ist_time', 'ts', 'timestamp'):
        if row.get(field) not in (None, ''):
            return timestamp(row[field], legacy_ist=field in ('IST_Time', 'ist_time'))
    if fallback is None:
        raise ValueError('Row has no timestamp; supply --observed-at with known provenance (scorecard overwrites have no timestamp)')
    return timestamp(fallback)


def normalize(conn, event_id, row, kind):
    if kind == 'legacy_chain':
        for side in ('CE', 'PE'):
            expiry = row.get('Expiry')
            symbol = row.get(f'{side}_Symbol') or f"legacy:{expiry or 'UNKNOWN'}:{row['Strike']}:{side}"
            def number(key):
                value = row.get(f'{side}_{key}')
                return float(value) if value not in ('', None) else None
            conn.execute('INSERT INTO option_snapshots VALUES (?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT DO NOTHING',
                         (event_id, symbol, float(row['Strike']), side, expiry, number('LTP'), number('Bid'),
                          number('Ask'), number('OI'), number('Volume'), canonical(row)))
    if kind == 'legacy_check':
        number = int(str(row['Check']).split('.')[0])
        for side, label in [('BULL', 'Bull'), ('BEAR', 'Bear')]:
            conn.execute('INSERT INTO check_results VALUES (?,?,?,?,?) ON CONFLICT DO NOTHING',
                         (event_id, number, side, row[f'{label}_Status'], canonical(row)))
    if row.get('Fut_Close') not in ('', None):
        # The original CSV did not record contract identity or exchange time.
        symbol = row.get('Fut_Symbol') or 'legacy:UNKNOWN_FUTURES'
        def optional_number(key):
            return float(row[key]) if row.get(key) not in ('', None) else None
        conn.execute('INSERT INTO futures_data VALUES (?,?,?,?,?,?,?) ON CONFLICT DO NOTHING',
                     (event_id, symbol, None, optional_number('Fut_Close'), optional_number('Fut_VWAP'),
                      optional_number('Fut_OI'), canonical(row)))
    if kind == 'legacy_signal':
        for side, field in [('BULL', 'Bull_Checks_Passed'), ('BEAR', 'Bear_Checks_Passed')]:
            if field in row:
                import re
                flags = re.findall(r'C([1-9]):([YN])', row[field])
                if len(flags) != 9 or {int(n) for n, _ in flags} != set(range(1, 10)):
                    raise ValueError('Malformed nine-check flags')
                for n, flag in flags:
                    conn.execute('INSERT INTO check_results VALUES (?,?,?,?,?) ON CONFLICT DO NOTHING',
                                 (event_id, int(n), side, 'PASS' if flag == 'Y' else 'FAIL', canonical(row)))
        verdict = row.get('Final_Verdict')
        # Do not infer a verdict from a prose banner.
        classification = {'BULL': 'Bullish', 'BEAR': 'Bearish', 'NO TRADE': 'No Trade'}.get(verdict)
        if classification:
            conn.execute('INSERT INTO signals VALUES (?,?,1,?) ON CONFLICT DO NOTHING', (event_id, classification, canonical(row)))


def import_file(store, path, *, observed_at=None):
    path = Path(path)
    raw = path.read_bytes()
    sha = hashlib.sha256(raw).hexdigest()
    rows = read_rows(raw, path.suffix)
    times = []
    hashes = []
    with store.transaction() as conn:
        existing = conn.execute('SELECT row_count FROM import_files WHERE file_sha256=?', (sha,)).fetchone()
        if existing:
            report = verify_import(conn, sha)
            report['duplicate_file'] = True
            return report
        # Manifest and all events commit together, or nothing is imported.
        conn.execute('INSERT INTO import_files VALUES (?,?,?,?,?,?,?,?)',
                     (sha, len(raw), path.name, timestamp(datetime.now(timezone.utc)), 0, '', None, None))
        for i, row in enumerate(rows, 1):
            utc = observed(row, observed_at)
            times.append(utc)
            kind = classify(row)
            eid = store.event(conn, observed_at=utc, kind=kind, source='legacy-drive', payload=row,
                              status='IMPORTED_UNVERIFIED_EXCHANGE_TIME')
            normalize(conn, eid, row, kind)
            row_hash = digest(canonical(row))
            hashes.append(row_hash)
            conn.execute('INSERT INTO import_rows VALUES (?,?,?,?)', (sha, i, row_hash, eid))
        conn.execute('UPDATE import_files SET row_count=?,row_checksum=?,min_time_utc=?,max_time_utc=? WHERE file_sha256=?',
                     (len(rows), digest(''.join(hashes)), min(times) if times else None, max(times) if times else None, sha))
        report = verify_import(conn, sha)
        report['duplicate_file'] = False
        if not report['ok']:
            raise ValueError('Import verification failed')
    if hashlib.sha256(path.read_bytes()).hexdigest() != sha:
        raise ValueError('Source changed during import; committed manifest describes the original bytes; rerun after source is stable')
    return report


def verify_import(conn, sha):
    manifest = conn.execute('SELECT row_count,row_checksum,min_time_utc,max_time_utc FROM import_files WHERE file_sha256=?', (sha,)).fetchone()
    if manifest is None:
        raise ValueError('Unknown import')
    rows = conn.execute('SELECT r.row_sha256,e.payload_json,e.observed_at_utc,e.payload_sha256 FROM import_rows r JOIN events e USING(event_id) WHERE r.file_sha256=? ORDER BY r.row_number', (sha,)).fetchall()
    hashes = [digest(canonical(json.loads(payload))) for _, payload, _, _ in rows]
    times = [row[2] for row in rows]
    checksum = digest(''.join(hashes))
    actual_range = (min(times), max(times)) if times else (None, None)
    ok = (len(rows) == manifest[0] and checksum == manifest[1] and actual_range == tuple(manifest[2:])
          and all(h == row[0] == row[3] for h, row in zip(hashes, rows)))
    return {'ok': ok, 'file_sha256': sha, 'source_rows': manifest[0], 'verified_rows': len(rows),
            'row_checksum': checksum, 'min_time_utc': actual_range[0], 'max_time_utc': actual_range[1]}
