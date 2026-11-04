import importlib.util
import json
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse
import pytest

spec = importlib.util.spec_from_file_location('fyers_connect', Path(__file__).resolve().parents[1] / 'scripts/fyers_connect.py')
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)


def test_callback_requires_matching_state_and_redirect():
    url = helper.DEFAULT_REDIRECT + '?auth_code=EXAMPLE&state=random-state'
    assert helper.parse_callback(url, helper.DEFAULT_REDIRECT, 'random-state') == 'EXAMPLE'
    for bad in (url.replace('random-state', 'wrong'), url.replace('trade.fyers.in', 'example.org'), url + '&auth_code=OTHER'):
        with pytest.raises(ValueError):
            helper.parse_callback(bad, helper.DEFAULT_REDIRECT, 'random-state')


def test_private_token_storage(tmp_path):
    path = tmp_path / 'config/token.json'
    helper.save_token(path, {'client_id': 'example', 'access_token': 'EXAMPLE_TOKEN'})
    assert path.stat().st_mode & 0o777 == 0o600
    assert path.parent.stat().st_mode & 0o777 == 0o700
    assert json.loads(path.read_text())['client_id'] == 'example'


def test_login_verifies_profile_and_does_not_print_secrets(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr('builtins.input', lambda prompt: 'EXAMPLE-ID' if 'App ID' in prompt else '')
    def prompt(text):
        if 'App Secret' in text:
            return 'EXAMPLE_SECRET'
        output = capsys.readouterr().out
        url = next(line for line in output.splitlines() if line.startswith('https://'))
        state = parse_qs(urlparse(url).query)['state'][0]
        assert 'EXAMPLE_SECRET' not in output
        return helper.DEFAULT_REDIRECT + '?' + urlencode({'auth_code': 'EXAMPLE_CODE', 'state': state})
    monkeypatch.setattr(helper, 'getpass', prompt)
    calls = []
    def request(operation, **kwargs):
        calls.append(operation)
        return {'s': 'ok', 'access_token': 'EXAMPLE_TOKEN'} if operation == 'exchange' else {'s': 'ok'}
    monkeypatch.setattr(helper, 'request', request)
    path = tmp_path / 'config/token.json'
    helper.login(path)
    assert calls == ['exchange', 'profile']
    assert 'EXAMPLE_SECRET' not in path.read_text()
    assert 'EXAMPLE_TOKEN' not in capsys.readouterr().out


def test_check_uses_only_read_endpoints(tmp_path, monkeypatch, capsys):
    path = tmp_path / 'config/token.json'
    helper.save_token(path, {'client_id': 'EXAMPLE-ID', 'access_token': 'EXAMPLE_TOKEN'})
    calls = []
    def request(operation, **kwargs):
        calls.append(operation)
        return {'s': 'ok', 'd': [{'s': 'ok', 'n': 'NSE:NIFTY50-INDEX', 'v': {'lp': 24000}}]}
    monkeypatch.setattr(helper, 'request', request)
    helper.check(path)
    assert calls == ['profile', 'quote']
    assert '24000.00' in capsys.readouterr().out


def test_transport_uses_fyers_compatible_user_agent(monkeypatch):
    from nifty_l2 import fyers
    import io
    requests = []
    class Opener:
        def open(self, request, timeout):
            requests.append(request)
            return io.StringIO('{"s": "ok"}')
    monkeypatch.setattr(fyers, 'build_opener', lambda *args: Opener())
    fyers.request('exchange', payload={'code': 'TEST-CODE'})
    fyers.request('profile', credentials={'client_id': 'TEST', 'access_token': 'TEST-TOKEN'})
    assert len(requests) == 2
    assert all(request.get_header('User-agent').startswith('Mozilla/5.0') for request in requests)
    assert requests[0].get_header('Content-type') == 'application/json'
    assert requests[1].get_header('Authorization') == 'TEST:TEST-TOKEN'
