from copy import deepcopy
from datetime import datetime
import fcntl
import json
import time

import pytest

from nifty_l2 import fyers
from nifty_l2.runner import ReadOnlyClient, Runner, evaluate_once
from nifty_l2.storage import Store
from test_engine import fixture_calls


def test_live_adapter_executes_nine_checks_and_archives_raw_inputs(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv('ACTIVE_INDEX', 'NIFTY')
    monkeypatch.setenv('NIFTY_FUT_SYMBOL', '')
    dt = datetime.fromisoformat('2026-11-03T09:24:00+05:30')
    expected = fixture_calls(0, dt)
    # Auction history is optional; successful empty input becomes INSUFFICIENT_DATA.
    expected[-1]['response']['s'] = 'ok'
    pending = deepcopy(expected)
    def request(operation, *, params, credentials):
        item = pending.pop(0)
        assert operation == item['method'] and params == item['request']
        return deepcopy(item['response'])
    monkeypatch.setattr(fyers, 'request', request)
    client = ReadOnlyClient({'client_id': 'APP', 'access_token': 'PRIVATE_TOKEN'})
    store = Store(tmp_path / 'research.db')
    with store.transaction() as conn:
        conn.execute('INSERT INTO run_log VALUES (?,?,?,?,?,?,?,?)',
                     ('test-run', 'scheduled', dt.isoformat(), dt.isoformat(), None, 'RUNNING', 'Test run', None))
    result = evaluate_once(store, client, now=dt, run_id='test-run', scheduled_at=dt.isoformat(), trigger='scheduled')
    assert not pending
    assert len(result['state']['scorecard']) == 9
    assert result['classification'] == 'No Trade'
    assert result['status'] == 'LEGACY_UNVALIDATED'
    with store.connect() as conn:
        payload = conn.execute('SELECT payload_json FROM events').fetchone()[0]
        assert json.loads(payload)['calls'] == expected
        assert 'PRIVATE_TOKEN' not in payload
        assert conn.execute('SELECT count(*) FROM check_results').fetchone()[0] == 18
        assert conn.execute('SELECT status,event_id FROM run_log').fetchone() == ('COMPLETED', result['event_id'])
        assert conn.execute('SELECT kind FROM events').fetchone()[0] == 'scheduled_research'
    assert 'PRIVATE_TOKEN' not in capsys.readouterr().out
    with pytest.raises(AttributeError):
        client.place_order(data={})


def test_incomplete_market_data_does_not_persist_result(tmp_path, monkeypatch):
    class Client:
        calls = []
        def optionchain(self, *, data):
            return {'s': 'error'}
    store = Store(tmp_path / 'research.db')
    with pytest.raises(RuntimeError, match='incomplete'):
        evaluate_once(store, Client())
    assert store.integrity()['counts']['events'] == 0


def test_runner_rejects_overlap(tmp_path):
    token = tmp_path / 'config/token.json'
    fyers.save_token(token, {})
    runner = Runner(tmp_path / 'runtime', token)
    with open(runner.directory / 'run.lock', 'a') as handle:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(ValueError, match='already'):
            runner.start()


def test_real_worker_reports_failure_without_disclosing_credentials(tmp_path):
    token = tmp_path / 'config/token.json'
    # Incomplete credentials fail locally before any API call.
    fyers.save_token(token, {'secret': 'PRIVATE_SECRET'})
    runner = Runner(tmp_path / 'runtime', token)
    runner.start()
    deadline = time.monotonic() + 10
    while runner.process.poll() is None and time.monotonic() < deadline:
        time.sleep(0.05)
    try:
        assert runner.process.poll() is not None
        status = runner.status()
        assert status['status'] == 'FAILED'
        with Store(runner.directory / 'research.db').connect() as conn:
            log = conn.execute('SELECT status,message FROM run_log').fetchone()
            assert log[0] == 'FAILED'
            assert 'PRIVATE_SECRET' not in log[1]
        assert 'PRIVATE_SECRET' not in json.dumps(status)
        assert not (runner.directory / 'result.json').exists()
    finally:
        runner.stop()


def test_settings_saved_privately_and_not_rendered(tmp_path):
    from nifty_l2.web import App
    app = App('https://research.example.com', 'password-of-16-or-more', token_path=tmp_path / 'config/token.json')
    app.configure('APP-ID', 'PRIVATE_SECRET')
    assert app.settings_path.stat().st_mode & 0o777 == 0o600
    assert 'PRIVATE_SECRET' not in app.page()
    reopened = App(app.origin, app.password, token_path=app.token_path)
    assert reopened.secret == 'PRIVATE_SECRET'
    assert reopened.client_id == 'APP-ID'


def test_stop_can_reach_worker_owned_by_collector(tmp_path, monkeypatch):
    runner = Runner(tmp_path / 'runtime', tmp_path / 'token.json')
    monkeypatch.setattr(runner, 'status', lambda: {'status': 'RUNNING', 'run_id': 'scheduled-worker'})
    runner.stop()
    assert json.loads((runner.directory / 'stop-request.json').read_text()) == {'run_id': 'scheduled-worker'}
