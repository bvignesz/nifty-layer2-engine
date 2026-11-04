"""Offline tests for the Phase 1 ML feature export."""
import csv
import json
import sqlite3

import pytest
from nifty_l2.ml_dataset import extract, export
from nifty_l2.storage import Store


def seed(db):
    store = Store(db)
    with store.transaction() as conn:
        event_id = store.event(
            conn, observed_at='2026-11-04T09:18:00+05:30',
            kind='scheduled_research', source='fyers-read-only',
            status='LEGACY_UNVALIDATED',
            payload={'input_quality':{'exchange_quote_freshness':'UNVERIFIED'}})
        conn.execute('INSERT INTO signals VALUES (?,?,1,?)',
                     (event_id,'No Trade',json.dumps({
                         'final_verdict':'BULL','meta':{'spot':24100,'vix':15,'gex':'unknown'}})))
        for side in ('BULL','BEAR'):
            for number in range(1,10):
                conn.execute('INSERT INTO check_results VALUES (?,?,?,?,?)',
                             (event_id,number,side,'PASS' if side=='BULL' else 'FAIL','{}'))
    return event_id


def test_read_only_export_preserves_nulls_and_no_labels(tmp_path):
    db=tmp_path/'research.db'
    event_id=seed(db)
    output=tmp_path/'dataset.csv'
    assert export(db,output)==1
    with output.open(newline='') as handle:
        row=next(csv.DictReader(handle))
    assert row['event_id']==event_id
    assert row['spot']=='24100.0'
    assert row['gex_scenario']==''
    assert row['bull_checks_pass']=='9'
    assert row['bear_checks_pass']=='0'
    assert row['label_status']=='NOT_AVAILABLE'
    assert row['exchange_at_utc']==''
    assert row['feature_status']=='RESEARCH_UNVALIDATED'
    with pytest.raises(FileExistsError):
        export(db,output)
    with sqlite3.connect(db) as conn:
        assert conn.execute('SELECT COUNT(*) FROM events').fetchone()[0]==1


def test_missing_db_is_not_created(tmp_path):
    missing=tmp_path/'missing.db'
    with pytest.raises(FileNotFoundError):
        extract(missing)
    assert not missing.exists()


def test_empty_database_exports_only_header(tmp_path):
    db=tmp_path/'empty.db'
    Store(db)
    assert export(db,tmp_path/'empty.csv')==0
    assert (tmp_path/'empty.csv').read_text().startswith('event_id,')
