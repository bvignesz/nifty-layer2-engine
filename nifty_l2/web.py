"""Private single-owner dashboard and FYERS OAuth callback. No order endpoints."""
import argparse
import base64
from datetime import datetime, timezone
import hashlib
from html import escape
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
import os
from pathlib import Path
import secrets
import threading
import time
from urllib.parse import parse_qs, urlencode, urlparse

from . import fyers
from .runner import Runner
from .storage import IST
from .terminal import CSS, snapshots, history_text
from .terminal_ui import UI_CSS, history_html
from .research_readmodel import research_history, expiry_matrix, readiness
from .research_pages import render as render_research_page
from .microstructure_terminal import read_rows as microstructure_rows, render as microstructure_page
from .desk_readmodel import desk_snapshot
from .desk_pages import render_desk
from .live_feed_view import live_readmodel, render_live_feed
from .swing_pages import swing_snapshot, render_swing
from .chat_archive import read_chat_archive, render_chat_archive
from .terminal_ui import history_html as strike_history_html
from .home_dashboard import render_home
from .quantum_pages import quantum_snapshot, render_quantum
import sqlite3


class LoginFailure(ValueError):
    """A fixed, credential-free login failure category."""


class App:
    def __init__(self, origin, password, client_id='', secret='', token_path=fyers.TOKEN_PATH, require_login=True):
        parsed = urlparse(origin)
        if (parsed.scheme not in ('http', 'https') or not parsed.netloc or
                parsed.path not in ('', '/') or parsed.query or parsed.fragment or parsed.username):
            raise ValueError('NIFTY_WEB_ORIGIN must be an origin without a path')
        if parsed.scheme != 'https' and parsed.hostname not in ('localhost', '127.0.0.1'):
            raise ValueError('Remote access requires an HTTPS origin')
        if require_login and len(password) < 16:
            raise ValueError('NIFTY_WEB_PASSWORD must contain at least 16 characters')
        self.require_login = require_login
        self.origin = origin.rstrip('/')
        self.password, self.client_id, self.secret = password, client_id, secret
        self.token_path = Path(token_path)
        self.settings_path = self.token_path.parent / 'web-settings.json'
        if not self.client_id or not self.secret:
            try:
                if self.settings_path.stat().st_mode & 0o077:
                    raise ValueError('FYERS settings file must be private (0600)')
                settings = json.loads(self.settings_path.read_text())
                self.client_id = settings['client_id']
                self.secret = settings['secret']
            except FileNotFoundError:
                pass
        self.runner = Runner(self.token_path.parent / 'web-runtime', self.token_path)
        csrf_path = self.token_path.parent / 'web-csrf.json'
        try:
            if csrf_path.stat().st_mode & 0o077:
                raise ValueError('Web form token file must be private (0600)')
            self.csrf = json.loads(csrf_path.read_text())['token']
            if not isinstance(self.csrf, str) or len(self.csrf) < 32:
                raise ValueError('Invalid saved web form token')
        except FileNotFoundError:
            self.csrf = secrets.token_urlsafe(32)
            fyers.save_token(csrf_path, {'token': self.csrf})
        self.pending = {}
        self.lock = threading.Lock()

    @property
    def callback(self):
        return fyers.DEFAULT_REDIRECT if self.origin.startswith('http:') else self.origin + '/oauth/callback'

    def start(self):
        if not self.client_id or not self.secret:
            raise ValueError('Configure FYERS_CLIENT_ID and FYERS_APP_SECRET on the server first')
        state, browser = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        with self.lock:
            now = time.monotonic()
            self.pending = {k: v for k, v in self.pending.items() if v[1] > now}
            if len(self.pending) >= 100:
                raise ValueError('Too many pending logins; wait ten minutes')
            self.pending[state] = (browser, now + 600)
        return ('https://api-t1.fyers.in/api/v3/generate-authcode?' + urlencode({
            'client_id': self.client_id, 'redirect_uri': self.callback,
            'response_type': 'code', 'state': state}), browser)

    def finish(self, path, browser):
        params = parse_qs(urlparse(path).query)
        states = params.get('state', [])
        if len(states) != 1:
            raise LoginFailure('missing-state')
        with self.lock:
            entry = self.pending.get(states[0])
            if not entry or entry[1] <= time.monotonic():
                raise LoginFailure('expired-state')
            if not browser or not secrets.compare_digest(entry[0], browser):
                raise LoginFailure('browser-cookie')
            if len(params.get('auth_code', [])) != 1:
                raise LoginFailure('no-auth-code')
            del self.pending[states[0]]
        code = fyers.parse_callback(path if path.startswith('https://') else self.origin + path, self.callback, states[0])
        result = fyers.request('exchange', payload={
            'grant_type': 'authorization_code',
            'appIdHash': hashlib.sha256(f'{self.client_id}:{self.secret}'.encode()).hexdigest(),
            'code': code})
        token = result.get('access_token')
        if not isinstance(token, str) or not token:
            raise ValueError('FYERS did not return an access token')
        credentials = dict(client_id=self.client_id, access_token=token,
                           redirect_uri=self.callback, created_at_utc=datetime.now(timezone.utc).isoformat())
        fyers.request('profile', credentials=credentials)
        fyers.save_token(self.token_path, credentials)

    def quote(self):
        if self.token_path.stat().st_mode & 0o077:
            raise ValueError('Token file must have private permissions (0600)')
        credentials = json.loads(self.token_path.read_text())
        if not isinstance(credentials, dict) or not credentials.get('client_id') or not credentials.get('access_token'):
            raise ValueError('Saved connection is incomplete; connect again')
        fyers.request('profile', credentials=credentials)
        result = fyers.request('quote', credentials=credentials)
        items = [x for x in result.get('d', []) if x.get('n') == 'NSE:NIFTY50-INDEX' and x.get('s') == 'ok']
        if len(items) != 1:
            raise ValueError('FYERS did not return a unique NIFTY quote')
        price = float(items[0].get('v', {}).get('lp', 0))
        if not math.isfinite(price) or price <= 0:
            raise ValueError('FYERS returned an invalid price')
        return f'NIFTY 50 · {price:,.2f} — retrieved {datetime.now(timezone.utc):%H:%M:%S UTC}. Quote freshness has not been validated.'

    def configure(self, client_id, secret):
        if not client_id or not secret or len(client_id) > 128 or len(secret) > 512:
            raise ValueError('Enter the complete FYERS App ID and App Secret')
        if self.runner.status().get('status') == 'RUNNING':
            raise ValueError('Wait for the script to finish before changing the app')
        fyers.save_token(self.settings_path, dict(client_id=client_id, secret=secret))
        with self.lock:
            self.client_id, self.secret = client_id, secret
            self.pending.clear()
        # A token for the previous app must not be reused with the new configuration.
        self.token_path.unlink(missing_ok=True)

    def page(self, message='', params=None):
        from .home_dashboard import render_home
        return render_home(self, message)

    def settings_page(self):
        csrf='<input type="hidden" name="csrf" value="'+escape(self.csrf,quote=True)+'">'
        return ('<!doctype html><html lang="en"><meta charset="utf-8">'
          '<meta name="viewport" content="width=device-width,initial-scale=1">'
          '<title>FYERS Settings</title><style>body{background:#09111f;color:#d8e7f7;'
          'font:14px system-ui;margin:30px auto;max-width:650px}a{color:#93c5fd}'
          'input{width:100%;box-sizing:border-box;margin:7px 0 16px;padding:10px}'
          'button{padding:11px;background:#2563eb;color:white;border:0;border-radius:6px}'
          '</style><a href="/">← Home</a><h1>FYERS App Settings</h1>'
          '<p>Registered redirect: <code>'+escape(self.callback)+'</code></p>'
          '<form method="post" action="/settings">'+csrf+
          '<label>App ID<input name="client_id" required maxlength="128"></label>'
          '<label>App Secret<input type="password" name="secret" required maxlength="512"></label>'
          '<button>Save FYERS settings</button></form>'
          '<p>Saving settings invalidates the previous token. Credentials are not displayed.</p>')


def handler_for(app):
    class Handler(BaseHTTPRequestHandler):
        # OAuth query strings and authorization headers must never enter access logs.
        def log_message(self, *_):
            pass

        def respond(self, code, body='', headers=(), content_type='text/html; charset=utf-8'):
            data = body.encode()
            self.send_response(code)
            for key, value in [('Content-Type', content_type), ('Cache-Control', 'no-store'),
                               ('Referrer-Policy', 'same-origin'), ('X-Content-Type-Options', 'nosniff'),
                               ('Content-Security-Policy', "default-src 'none'; style-src 'unsafe-inline'; script-src 'self'; connect-src 'self'; form-action 'self' https://api-t1.fyers.in; frame-ancestors 'none'; base-uri 'none'"), *headers]:
                self.send_header(key, value)
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def authorized(self):
            if not app.require_login:
                return True
            expected = 'Basic ' + base64.b64encode(('owner:' + app.password).encode()).decode()
            if secrets.compare_digest(self.headers.get('Authorization', '').encode(), expected.encode()):
                return True
            self.respond(401, 'Sign in with username owner and your web password.', [('WWW-Authenticate', 'Basic realm="NIFTY", charset="UTF-8"')])
            return False

        def do_GET(self):
            if not self.authorized():
                return
            path = urlparse(self.path).path
            if path == '/chat-archive':
                try:
                    q=parse_qs(urlparse(self.path).query)
                    data=read_chat_archive(app.runner.directory/"chat_archive.db",
                      conversation_id=q.get("id",[None])[0],
                      query=q.get("q",[""])[0])
                    self.respond(200,render_chat_archive(data))
                except (ValueError,OverflowError,sqlite3.Error):
                    self.respond(400,"Invalid chat archive request",
                      content_type="text/plain; charset=utf-8")
            elif path == '/quantum':
                self.respond(200,render_quantum(quantum_snapshot(app.runner.directory)))
            elif path == '/api/v1/quantum':
                self.respond(200,json.dumps(quantum_snapshot(app.runner.directory),
                    allow_nan=False),content_type='application/json; charset=utf-8')
            elif path == '/settings':
                self.respond(200,app.settings_page())
            elif path == '/strike-terminal':
                try:
                    data=snapshots(app.runner.directory,parse_qs(urlparse(self.path).query))
                    content=strike_history_html(data).replace('action="/" method="get"','action="/strike-terminal" method="get"')
                    html='<html><meta charset="utf-8"><title>Stored Strike Snapshots</title><style>'+CSS+UI_CSS+'</style><script defer src="/terminal.js"></script><main><p><a href="/">Home</a> · <a href="/desk">Options Desk</a></p>'+content+'</main></html>'
                    self.respond(200,html)
                except (ValueError,OverflowError,IndexError,sqlite3.Error):
                    self.respond(400,'Invalid snapshot filters',content_type='text/plain; charset=utf-8')
            elif path == '/swing':
                try:
                    q=parse_qs(urlparse(self.path).query)
                    payload=swing_snapshot(app.runner.directory,track=q.get('track',['ALL'])[0])
                    self.respond(200,render_swing(payload))
                except (ValueError,OverflowError,OSError):
                    self.respond(400,'Invalid swing filter',content_type='text/plain; charset=utf-8')
            elif path == '/desk':
                try:
                    params=parse_qs(urlparse(self.path).query)
                    day=params.get('date',[datetime.now(IST).date().isoformat()])[0]
                    desk=desk_snapshot(app.runner.directory,day)
                    live=live_readmodel(app.runner.directory)
                    page=render_desk(desk)
                    page=page.replace('<div class="panel">',render_live_feed(live)+'<div class="panel">',1)
                    self.respond(200,page)
                except (ValueError, OverflowError, sqlite3.Error):
                    self.respond(400,'Invalid desk date',content_type='text/plain; charset=utf-8')
            elif path == '/microstructure':
                try:
                    params=parse_qs(urlparse(self.path).query)
                    day=params.get('date',[datetime.now(IST).date().isoformat()])[0]
                    self.respond(200,microstructure_page(microstructure_rows(app.runner.directory,day)))
                except (ValueError, OverflowError, sqlite3.Error):
                    self.respond(400,'Invalid microstructure date',content_type='text/plain; charset=utf-8')
            elif path in ('/research','/expiries','/eod','/validation'):
                try:
                    self.respond(200, render_research_page(app.runner.directory, path.lstrip('/'), parse_qs(urlparse(self.path).query)))
                except (ValueError, OverflowError, sqlite3.Error):
                    self.respond(400, 'Invalid research filter', content_type='text/plain; charset=utf-8')
            elif path in ('/api/v1/research','/api/v1/expiries','/api/v1/readiness','/api/v1/microstructure','/api/v1/desk','/api/v1/live-feed','/api/v1/swing'):
                try:
                    q = parse_qs(urlparse(self.path).query)
                    day = q.get('date', [datetime.now(IST).date().isoformat()])[0]
                    if path == '/api/v1/swing':
                        payload = swing_snapshot(app.runner.directory,track=q.get('track',['ALL'])[0])
                    elif path == '/api/v1/live-feed':
                        payload = live_readmodel(app.runner.directory)
                    elif path == '/api/v1/desk':
                        payload = desk_snapshot(app.runner.directory,day,limit=q.get('limit',['40'])[0])
                    elif path == '/api/v1/microstructure':
                        payload = microstructure_rows(app.runner.directory,day,q.get('limit',['40'])[0])
                    elif path == '/api/v1/research':
                        payload = research_history(app.runner.directory, day, q.get('limit', ['40'])[0])
                    elif path == '/api/v1/expiries':
                        payload = expiry_matrix(app.runner.directory, day, q.get('strike', ['24450'])[0])
                    else:
                        payload = readiness(app.runner.directory)
                    self.respond(200, json.dumps(payload, ensure_ascii=False, allow_nan=False),
                                 content_type='application/json; charset=utf-8')
                except (ValueError, OverflowError, sqlite3.Error):
                    self.respond(400, json.dumps({'error':'Invalid research filter'}),
                                 content_type='application/json; charset=utf-8')
            elif path == '/':
                status = parse_qs(urlparse(self.path).query).get('connection', [''])[0]
                message = {'verified': 'FYERS authentication verified. Fetch a quote to check data access.',
                           'missing-state': 'FYERS returned without a login state. Use Connect FYERS to start login; do not open the callback URL directly.',
                           'expired-state': 'This login link expired or was already used. Return to the dashboard and select Connect FYERS once.',
                           'browser-cookie': 'The login browser cookie is missing or different. Open the dashboard and complete FYERS login in the same browser, with cookies enabled.',
                           'no-auth-code': 'FYERS returned without an authorization code. Check that the app is active and its registered callback exactly matches ' + app.callback,
                           'api-failed': 'FYERS could not complete token exchange or account verification. Check the App ID and App Secret, enable Profile permission in your FYERS app, then connect again.',
                           'failed': 'Login failed or expired. Start a fresh connection in this same browser. Ensure the registered FYERS callback is ' + app.callback}.get(status, '')
                self.respond(200, app.page(message, parse_qs(urlparse(self.path).query)))
            elif path == '/terminal.js':
                self.respond(200, Path(__file__).with_name('terminal.js').read_text(encoding='utf-8'),
                             content_type='text/javascript; charset=utf-8')
            elif path == '/export':
                try:
                    data = snapshots(app.runner.directory, parse_qs(urlparse(self.path).query))
                    self.respond(200, history_text(data),
                                 [('Content-Disposition', 'attachment; filename="nifty-snapshots.txt"')],
                                 content_type='text/plain; charset=utf-8')
                except (ValueError, OverflowError, IndexError):
                    self.respond(400, 'Invalid history filter', content_type='text/plain; charset=utf-8')
            elif path == '/oauth/callback':
                try:
                    cookies = SimpleCookie(self.headers.get('Cookie', ''))
                    cookie = cookies.get('fyers_browser')
                    app.finish(self.path, cookie.value if cookie else '')
                except LoginFailure as error:
                    print('FYERS callback rejected: ' + str(error), flush=True)
                    self.respond(303, headers=[('Location', '/?connection=' + str(error))])
                    return
                except RuntimeError:
                    print('FYERS callback rejected: api-failed', flush=True)
                    self.respond(303, headers=[('Location', '/?connection=api-failed')])
                    return
                except (ValueError, OSError, KeyError, TypeError):
                    # Redirect removes auth_code from the address bar and subsequent requests.
                    self.respond(303, headers=[('Location', '/?connection=failed')])
                    return
                self.respond(303, headers=[('Location', '/?connection=verified'), ('Set-Cookie', 'fyers_browser=; Path=/oauth/callback; Max-Age=0; HttpOnly; SameSite=Lax')])
            else:
                self.respond(404, 'Page not found')

        def redirect_to_fyers(self):
            url, browser = app.start()
            secure = '; Secure' if app.origin.startswith('https:') else ''
            # A form's CSP can also restrict downstream redirects on FYERS.
            # Finish the POST here and navigate from a document instead.
            target = escape(url, quote=True)
            body = ('<!doctype html><html><head><meta charset="utf-8">'
                    '<meta name="viewport" content="width=device-width, initial-scale=1">'
                    f'<meta http-equiv="refresh" content="0;url={target}">'
                    '<title>Open FYERS login</title></head><body>'
                    '<h1>Continue to FYERS</h1><p>Opening the FYERS login page…</p>'
                    f'<p><a href="{target}" rel="noreferrer">Open FYERS login</a></p>'
                    '<p>If it does not open automatically, tap the link above. '
                    'Complete login and OTP on FYERS.</p>'
                    '<p><a href="/">Return to dashboard</a></p></body></html>')
            self.respond(200, body, [('Set-Cookie', f'fyers_browser={browser}; Path=/oauth/callback; Max-Age=600; HttpOnly; SameSite=Lax{secure}')])

        def do_POST(self):
            if not self.authorized():
                return
            try:
                size = int(self.headers.get('Content-Length', '0'))
                if not 0 < size <= 4096 or self.headers.get('Transfer-Encoding'):
                    raise ValueError()
                params = parse_qs(self.rfile.read(size).decode())
                origin = self.headers.get('Origin')
                same_origin = origin == app.origin
                # Privacy browsers may omit Origin or send null. Fetch Metadata
                # is browser-controlled; allow that case only for same-origin requests.
                if origin in (None, 'null'):
                    same_origin = self.headers.get('Sec-Fetch-Site') == 'same-origin'
                if not same_origin:
                    print('Web form rejected: origin-check', flush=True)
                    self.respond(403, app.page('Your browser did not identify this as a request from this website. Open the dashboard in Chrome or Safari and try again.'))
                    return
                tokens = params.get('csrf', [])
                if len(tokens) != 1 or not secrets.compare_digest(tokens[0], app.csrf):
                    print('Web form rejected: stale-form-token', flush=True)
                    self.respond(403, app.page('This tab contains an older form. The form below is refreshed; enter your app settings and save again.'))
                    return
            except (ValueError, UnicodeError):
                self.respond(400, 'Invalid request')
                return
            try:
                if self.path == '/settings':
                    app.configure(params.get('client_id', [''])[0].strip(), params.get('secret', [''])[0].strip())
                    if app.origin.startswith('https:'):
                        self.redirect_to_fyers()
                    else:
                        self.respond(303, headers=[('Location', '/')])
                elif self.path == '/oauth/callback':
                    if not app.origin.startswith('http:'):
                        self.respond(404, 'Page not found')
                        return
                    cookies = SimpleCookie(self.headers.get('Cookie', ''))
                    cookie = cookies.get('fyers_browser')
                    app.finish(params.get('callback_url', [''])[0].strip(), cookie.value if cookie else '')
                    self.respond(303, headers=[('Location', '/?connection=verified'), ('Set-Cookie', 'fyers_browser=; Path=/oauth/callback; Max-Age=0; HttpOnly; SameSite=Lax')])
                elif self.path in ('/automation/pause', '/automation/resume'):
                    fyers.save_token(app.runner.directory / 'automation.json', {'enabled': self.path.endswith('/resume')})
                    self.respond(303, headers=[('Location', '/')])
                elif self.path == '/run':
                    app.runner.start()
                    self.respond(303, headers=[('Location', '/')])
                elif self.path == '/run/stop':
                    app.runner.stop()
                    self.respond(303, headers=[('Location', '/')])
                elif self.path == '/connect':
                    self.redirect_to_fyers()
                elif self.path == '/quote':
                    self.respond(200, app.page(app.quote()))
                else:
                    self.respond(404, 'Page not found')
            except (ValueError, RuntimeError, OSError, KeyError, TypeError):
                self.respond(200, app.page('Action could not complete. Check app settings and FYERS connection, and ensure no other run is active.'))
    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8080)
    args = parser.parse_args()
    try:
        app = App(os.environ.get('NIFTY_WEB_ORIGIN', f'http://127.0.0.1:{args.port}'),
                  os.environ.get('NIFTY_WEB_PASSWORD', ''), os.environ.get('FYERS_CLIENT_ID', ''),
                  os.environ.get('FYERS_APP_SECRET', ''),
                  require_login=os.environ.get('NIFTY_WEB_REQUIRE_LOGIN', '1') != '0')
    except ValueError as error:
        parser.error(str(error))
    server = ThreadingHTTPServer(('127.0.0.1', args.port), handler_for(app))
    print(f'NIFTY dashboard listening on http://127.0.0.1:{args.port}; use HTTPS proxy for remote access.', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        app.runner.stop()
        server.server_close()


if __name__ == '__main__':
    main()
