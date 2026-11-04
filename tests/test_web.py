import base64
from html import unescape
import re
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
import json
import threading
from urllib.parse import parse_qs, urlencode, urlparse

import pytest
from nifty_l2 import fyers
from nifty_l2.web import App, handler_for
from nifty_l2 import fyers


def app_for(tmp_path):
    return App('https://research.example.com', 'private-password-123', 'APP-ID', 'APP-SECRET', tmp_path / 'private/token.json')


def test_oauth_requires_browser_and_state_and_is_single_use(tmp_path, monkeypatch):
    app = app_for(tmp_path)
    url, browser = app.start()
    state = parse_qs(urlparse(url).query)['state'][0]
    callback = '/oauth/callback?' + urlencode(dict(state=state, auth_code='PRIVATE-CODE'))
    calls = []
    def request(operation, **kwargs):
        calls.append(operation)
        return {'access_token': 'PRIVATE-TOKEN'} if operation == 'exchange' else {'s': 'ok'}
    monkeypatch.setattr(fyers, 'request', request)
    with pytest.raises(ValueError):
        app.finish(callback, 'wrong-browser')
    assert not calls
    app.finish(callback, browser)
    assert calls == ['exchange', 'profile']
    assert app.token_path.stat().st_mode & 0o777 == 0o600
    assert 'APP-SECRET' not in app.token_path.read_text()
    assert json.loads(app.token_path.read_text())['access_token'] == 'PRIVATE-TOKEN'
    with pytest.raises(ValueError):
        app.finish(callback, browser)
    assert 'PRIVATE-TOKEN' not in app.page()


def test_expired_login_and_profile_failure_do_not_replace_token(tmp_path, monkeypatch):
    app = app_for(tmp_path)
    fyers.save_token(app.token_path, {'old': 'saved'})
    url, browser = app.start()
    state = parse_qs(urlparse(url).query)['state'][0]
    callback = '/oauth/callback?' + urlencode(dict(state=state, auth_code='CODE'))
    def request(operation, **kwargs):
        if operation == 'profile':
            raise RuntimeError('rejected')
        return {'access_token': 'unverified'}
    monkeypatch.setattr(fyers, 'request', request)
    with pytest.raises(RuntimeError):
        app.finish(callback, browser)
    assert json.loads(app.token_path.read_text()) == {'old': 'saved'}
    app.pending[state] = (browser, 0)
    with pytest.raises(ValueError):
        app.finish(callback, browser)


def test_http_auth_csrf_redirect_and_no_secret_output(tmp_path):
    app = app_for(tmp_path)
    server = ThreadingHTTPServer(('127.0.0.1', 0), handler_for(app))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    conn = HTTPConnection(*server.server_address, timeout=5)
    auth = 'Basic ' + base64.b64encode(b'owner:private-password-123').decode()
    try:
        conn.request('GET', '/')
        response = conn.getresponse()
        assert response.status == 401
        response.read()
        conn.request('GET', '/', headers={'Authorization': auth})
        response = conn.getresponse()
        page = response.read().decode()
        assert response.status == 200 and 'Connect FYERS' in page
        assert 'APP-SECRET' not in page
        assert response.getheader('Cache-Control') == 'no-store'
        conn.request('POST', '/connect', 'csrf=wrong', {'Authorization': auth, 'Origin': app.origin})
        response = conn.getresponse()
        assert response.status == 403
        response.read()
        conn.request('POST', '/connect', urlencode({'csrf': app.csrf}), {'Authorization': auth, 'Origin': app.origin})
        response = conn.getresponse()
        assert response.status == 200
        login_page = response.read().decode()
        assert 'http-equiv="refresh"' in login_page
        assert 'Open FYERS login</a>' in login_page
        assert 'https://api-t1.fyers.in/' in login_page
        assert 'HttpOnly' in response.getheader('Set-Cookie')
        assert 'Secure' in response.getheader('Set-Cookie')
        response.read()
        conn.request('GET', '/oauth/callback?state=wrong&auth_code=PRIVATE', headers={'Authorization': auth})
        response = conn.getresponse()
        assert response.status == 303 and response.getheader('Location') == '/?connection=expired-state'
        assert b'PRIVATE' not in response.read()
    finally:
        conn.close()
        server.shutdown()
        server.server_close()
        thread.join()


def test_remote_origin_requires_https(tmp_path):
    with pytest.raises(ValueError):
        App('http://example.com', 'private-password-123')
    with pytest.raises(ValueError):
        App('https://example.com', 'short')


def test_successful_callback_redirects_and_clears_browser_cookie(tmp_path, monkeypatch):
    app = app_for(tmp_path)
    url, browser = app.start()
    state = parse_qs(urlparse(url).query)['state'][0]
    calls = []
    def request(operation, **kwargs):
        calls.append(operation)
        return {'access_token': 'PRIVATE_TOKEN'} if operation == 'exchange' else {'s': 'ok'}
    monkeypatch.setattr(fyers, 'request', request)
    server = ThreadingHTTPServer(('127.0.0.1', 0), handler_for(app))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    conn = HTTPConnection(*server.server_address, timeout=5)
    auth = 'Basic ' + base64.b64encode(b'owner:private-password-123').decode()
    try:
        path = '/oauth/callback?' + urlencode(dict(state=state, auth_code='PRIVATE_CODE'))
        conn.request('GET', path, headers={'Authorization': auth, 'Cookie': f'fyers_browser={browser}'})
        response = conn.getresponse()
        assert response.status == 303
        assert response.getheader('Location') == '/?connection=verified'
        assert 'Max-Age=0' in response.getheader('Set-Cookie')
        assert b'PRIVATE' not in response.read()
        assert calls == ['exchange', 'profile']
    finally:
        conn.close()
        server.shutdown()
        server.server_close()
        thread.join()


def test_untrusted_result_html_is_escaped(tmp_path):
    app = app_for(tmp_path)
    fyers.save_token(app.runner.directory / 'result.json', {
        'observed_at': '2026-11-04T00:00:00Z',
        'state': {'final_verdict': '<script>alert(1)</script>', 'scorecard': []}})
    page = app.page()
    assert '<script>alert(1)</script>' not in page
    assert '&lt;script&gt;alert(1)&lt;/script&gt;' in page


def test_local_login_supports_private_callback_paste(tmp_path, monkeypatch):
    app = App('http://127.0.0.1:8080', 'private-password-123', 'APP', 'SECRET', tmp_path / 'config/token.json')
    assert app.callback == fyers.DEFAULT_REDIRECT
    url, browser = app.start()
    query = parse_qs(urlparse(url).query)
    assert query['redirect_uri'] == [fyers.DEFAULT_REDIRECT]
    callback = fyers.DEFAULT_REDIRECT + '?' + urlencode(dict(state=query['state'][0], auth_code='CODE'))
    monkeypatch.setattr(fyers, 'request', lambda operation, **kwargs: {'access_token': 'TOKEN'} if operation == 'exchange' else {'s': 'ok'})
    app.finish(callback, browser)
    assert json.loads(app.token_path.read_text())['access_token'] == 'TOKEN'
    assert 'Full FYERS redirect URL' in app.page()
    assert 'target="_blank"' in app.page()


def test_http_without_dashboard_login(tmp_path, monkeypatch):
    app = App('https://research.example.com', '', 'APP-ID', 'APP-SECRET',
              tmp_path / 'private/token.json', require_login=False)
    server = ThreadingHTTPServer(('127.0.0.1', 0), handler_for(app))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    conn = HTTPConnection(*server.server_address, timeout=5)
    try:
        conn.request('GET', '/')
        response = conn.getresponse()
        assert response.status == 200
        assert response.getheader('WWW-Authenticate') is None
        assert response.getheader('Referrer-Policy') == 'same-origin'
        assert b'Connect FYERS' in response.read()
        saved = []
        monkeypatch.setattr(app, 'configure', lambda client_id, secret: saved.append((client_id, secret)))
        body = urlencode({'csrf': app.csrf, 'client_id': 'TEST-APP', 'secret': 'TEST-SECRET'})
        for origin in ('null', 'https://other.example'):
            conn.request('POST', '/settings', body, {'Origin': origin})
            response = conn.getresponse()
            assert response.status == 403
            response.read()
        assert saved == []
        conn.request('POST', '/settings', body, {'Origin': app.origin})
        response = conn.getresponse()
        assert response.status == 200
        login_page = response.read().decode()
        location = urlparse(unescape(re.search(r'<a href="([^"]+)" rel="noreferrer">', login_page).group(1)))
        assert location.scheme == 'https' and location.netloc == 'api-t1.fyers.in'
        assert parse_qs(location.query)['redirect_uri'] == [app.callback]
        assert 'Secure' in response.getheader('Set-Cookie')
        assert 'HttpOnly' in response.getheader('Set-Cookie')
        assert "form-action 'self' https://api-t1.fyers.in;" in response.getheader('Content-Security-Policy')
        response.read()
        assert saved == [('TEST-APP', 'TEST-SECRET')]
        for origin in (None, 'null'):
            headers = {'Sec-Fetch-Site': 'same-origin'}
            if origin is not None:
                headers['Origin'] = origin
            conn.request('POST', '/settings', body, headers)
            response = conn.getresponse()
            assert response.status == 200
            response.read()
        conn.request('POST', '/settings', body, {'Origin': 'https://other.example', 'Sec-Fetch-Site': 'same-origin'})
        response = conn.getresponse()
        assert response.status == 403
        response.read()

        conn.request('POST', '/connect', 'csrf=wrong', {'Origin': app.origin})
        response = conn.getresponse()
        assert response.status == 403
        response.read()
    finally:
        conn.close()
        server.shutdown()
        server.server_close()
        thread.join()


def test_callback_failure_categories_preserve_browser_binding(tmp_path):
    from nifty_l2.web import LoginFailure
    app = app_for(tmp_path)
    with pytest.raises(LoginFailure, match='^missing-state$'):
        app.finish('/oauth/callback', '')
    url, browser = app.start()
    state = parse_qs(urlparse(url).query)['state'][0]
    callback = '/oauth/callback?' + urlencode({'state': state, 'auth_code': 'PRIVATE-CODE'})
    for cookie in ('', 'different-browser'):
        with pytest.raises(LoginFailure, match='^browser-cookie$'):
            app.finish(callback, cookie)
    with pytest.raises(LoginFailure, match='^no-auth-code$'):
        app.finish('/oauth/callback?' + urlencode({'state': state}), browser)
    assert state in app.pending
    app.pending[state] = (browser, 0)
    with pytest.raises(LoginFailure, match='^expired-state$'):
        app.finish(callback, browser)


def test_form_token_survives_app_restart(tmp_path):
    first = app_for(tmp_path)
    second = app_for(tmp_path)
    assert first.csrf == second.csrf
    path = first.token_path.parent / 'web-csrf.json'
    assert path.stat().st_mode & 0o777 == 0o600
