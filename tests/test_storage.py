from datetime import datetime, timezone
import json
import shutil
import sqlite3
import pytest
from nifty_l2.storage import Store, timestamp
from nifty_l2.migration import import_file, verify_import
from nifty_l2.observations import record_observation, record_outcome


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / 'test.db')


def test_wal_foreign_keys_and_rollback(store):
    with store.connect() as conn:
        assert conn.execute('PRAGMA journal_mode').fetchone()[0] == 'wal'
        assert conn.execute('PRAGMA foreign_keys').fetchone()[0] == 1
    with pytest.raises(RuntimeError):
        with store.transaction() as conn:
            store.event(conn, observed_at='2026-11-03T09:15:00+05:30', kind='test', source='test', payload={})
            raise RuntimeError('failed evaluation')
    assert store.integrity()['counts']['events'] == 0
    assert store.integrity()['ok']


def test_csv_repeat_copy_and_source_unchanged(store, tmp_path):
    source = tmp_path / 'history.csv'
    data = b'IST_Time,Final_Verdict,Spot\n2026-11-03 09:18:00 IST,BULL,24000\n2026-11-03 09:21:00 IST,NO TRADE,24010\n'
    source.write_bytes(data)
    result = import_file(store, source)
    assert result['ok'] and result['verified_rows'] == 2
    assert result['min_time_utc'] == '2026-11-03T03:48:00.000000Z'
    assert result['max_time_utc'] == '2026-11-03T03:51:00.000000Z'
    assert import_file(store, source)['duplicate_file']
    copied = tmp_path / 'renamed.csv'
    shutil.copyfile(source, copied)
    assert import_file(store, copied)['duplicate_file']
    assert store.integrity()['counts']['events'] == 2
    assert store.integrity()['counts']['signals'] == 2
    assert source.read_bytes() == data


def test_row_dedup_across_changed_files(store, tmp_path):
    a = tmp_path / 'a.json'; b = tmp_path / 'b.json'
    row = {'ts': 1793677500, 'value': 1}
    a.write_text(json.dumps([row, row]))
    b.write_text(json.dumps([row], indent=2))
    assert import_file(store, a)['verified_rows'] == 2
    assert import_file(store, b)['verified_rows'] == 1
    counts = store.integrity()['counts']
    assert counts['events'] == 1 and counts['import_rows'] == 3


def test_import_failure_rolls_back_entire_file(store, tmp_path):
    source = tmp_path / 'bad.json'
    source.write_text(json.dumps([{'ts': 1793677500}, {'bad': 'missing timestamp'}]))
    with pytest.raises(ValueError, match='no timestamp'):
        import_file(store, source)
    assert store.integrity()['counts']['events'] == 0
    assert store.integrity()['counts']['import_files'] == 0


def test_scorecard_requires_explicit_time(store, tmp_path):
    source = tmp_path / 'scorecard.csv'
    source.write_text('Check,Bull_Status,Bear_Status\n1. Wall gap,PASS,FAIL\n')
    with pytest.raises(ValueError):
        import_file(store, source)
    assert import_file(store, source, observed_at='2026-11-03T09:18:00+05:30')['ok']
    assert store.integrity()['counts']['check_results'] == 2


def test_chain_roundtrip(store, tmp_path):
    source = tmp_path / 'chain.json'
    source.write_text(json.dumps([{'IST_Time': '2026-11-03 09:18:00 IST', 'Strike': 24000, 'CE_OI': 100, 'PE_OI': 120}]))
    assert import_file(store, source)['ok']
    assert store.integrity()['counts']['option_snapshots'] == 2


def test_checksum_detects_corruption(store, tmp_path):
    source = tmp_path / 'data.json'; source.write_text('{"ts":1793677500}')
    result = import_file(store, source)
    with store.transaction() as conn:
        conn.execute("UPDATE events SET payload_json='{}'")
        assert not verify_import(conn, result['file_sha256'])['ok']


def test_backup_and_restore(store, tmp_path):
    with store.transaction() as conn:
        store.event(conn, observed_at=datetime.now(timezone.utc), kind='test', source='test', payload={'value': 1})
    path = tmp_path / 'backup.db'
    assert len(store.backup(path)['sha256']) == 64
    assert Store(path).integrity()['counts'] == store.integrity()['counts']
    with pytest.raises(FileExistsError):
        store.backup(path)


def test_timestamp_policy():
    with pytest.raises(ValueError, match='Naive'):
        timestamp('2026-11-03 09:18:00')
    assert timestamp('2026-11-03 09:18:00 IST') == '2026-11-03T03:48:00.000000Z'
    assert timestamp('2026-11-03T09:18:00+05:30') == timestamp('2026-11-03T03:48:00Z')


def test_atomic_observation_and_point_in_time_outcomes(store):
    checks = [{'number': n, 'side': s, 'status': 'PASS'} for n in range(1, 10) for s in ('BULL', 'BEAR')]
    args = dict(observed_at='2026-11-03T09:18:00+05:30', exchange_at=None, raw_option_chain=[],
                futures=[], checks=checks, state={'classification': 'Bullish'}, quality='UNAVAILABLE')
    eid = record_observation(store, **args)
    assert record_observation(store, **args) == eid
    with store.connect() as conn:
        assert conn.execute('SELECT classification FROM signals').fetchone()[0] == 'No Trade'
        assert conn.execute('SELECT count(*) FROM check_results WHERE status="UNAVAILABLE"').fetchone()[0] == 18
    with pytest.raises(ValueError, match='before its horizon'):
        record_outcome(store, event_id=eid, horizon_minutes=9, available_at='2026-11-03T09:26:00+05:30', forward_return=0.001)
    record_outcome(store, event_id=eid, horizon_minutes=9, available_at='2026-11-03T09:27:00+05:30', forward_return=0.001)
    assert store.integrity()['counts']['outcomes'] == 1
    with pytest.raises(ValueError, match='Conflicting'):
        record_outcome(store, event_id=eid, horizon_minutes=9, available_at='2026-11-03T09:27:00+05:30', forward_return=0.002)


def test_invalid_check_rolls_back(store):
    checks = [{'number': n, 'side': s, 'status': 'BOGUS'} for n in range(1, 10) for s in ('BULL', 'BEAR')]
    with pytest.raises(sqlite3.IntegrityError):
        record_observation(store, observed_at='2026-11-03T09:18:00+05:30', exchange_at='2026-11-03T09:17:59+05:30',
                           raw_option_chain=[], futures=[], checks=checks, state={}, quality='VALID')
    assert store.integrity()['counts']['events'] == 0


def test_original_signals_csv_recovers_flags_and_futures(store, tmp_path):
    source = tmp_path / 'signals.json'
    flags = ' '.join(f'C{n}:Y' for n in range(1, 10))
    source.write_text(json.dumps({'IST_Time': '2026-11-03 09:18:00 IST', 'Signal_Banner': 'legacy',
                                 'Bull_Checks_Passed': flags, 'Bear_Checks_Passed': flags.replace(':Y', ':N'),
                                 'Fut_Close': '24000', 'Fut_VWAP': '23990'}))
    assert import_file(store, source)['ok']
    assert store.integrity()['counts']['check_results'] == 18
    with store.connect() as conn:
        assert conn.execute('SELECT symbol,exchange_at_utc,close FROM futures_data').fetchone() == ('legacy:UNKNOWN_FUTURES', None, 24000)
        # The original 27-column signals CSV has no explicit final verdict.
        assert conn.execute('SELECT count(*) FROM signals').fetchone()[0] == 0
