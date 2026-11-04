"""Shared FYERS transport, callback validation and private token storage."""
import json
import os
from pathlib import Path
import secrets
import tempfile
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlparse, urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener

TOKEN_PATH = Path.home() / '.config/nifty-layer2/fyers-token.json'
DEFAULT_REDIRECT = 'https://trade.fyers.in/api-login/redirect-uri/index.html'
ENDPOINTS = {
    'optionchain': ('GET', 'https://api-t1.fyers.in/data/options-chain-v3'),
    'quotes': ('GET', 'https://api-t1.fyers.in/data/quotes'),
    'history': ('GET', 'https://api-t1.fyers.in/data/history'),
    'exchange': ('POST', 'https://api-t1.fyers.in/api/v3/validate-authcode'),
    'profile': ('GET', 'https://api-t1.fyers.in/api/v3/profile'),
    'quote': ('GET', 'https://api-t1.fyers.in/data/quotes?symbols=NSE%3ANIFTY50-INDEX'),
}


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise RuntimeError('Unexpected API redirect; request stopped')


def request(operation, *, payload=None, credentials=None, params=None):
    method, url = ENDPOINTS[operation]
    if params is not None:
        if operation not in ('optionchain', 'quotes', 'history'):
            raise ValueError('Parameters are only supported for market-data reads')
        url += '?' + urlencode(params)
    # FYERS' edge rejects the default Python-urllib user agent before auth.
    headers = {'Accept': 'application/json',
               'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 '
                             '(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36'}
    if credentials:
        headers['Authorization'] = f"{credentials['client_id']}:{credentials['access_token']}"
    body = None
    if payload is not None:
        headers['Content-Type'] = 'application/json'
        body = json.dumps(payload).encode()
    req = Request(url, data=body, headers=headers, method=method)
    try:
        with build_opener(NoRedirect()).open(req, timeout=20) as response:
            result = json.load(response)
    except HTTPError as error:
        # Do not print response bodies, request headers or potentially sensitive URLs.
        raise RuntimeError(f'FYERS HTTP {error.code}; check app permissions and token') from None
    except (URLError, TimeoutError, OSError):
        raise RuntimeError('FYERS network request failed; check VPS connectivity and retry manually') from None
    except ValueError:
        raise RuntimeError('FYERS returned an invalid JSON response') from None
    if not isinstance(result, dict) or result.get('s') != 'ok':
        code = result.get('code') if isinstance(result, dict) else None
        code = code if isinstance(code, int) else 'unavailable'
        raise RuntimeError(f'FYERS rejected {operation}; error code {code}')
    return result


def parse_callback(callback, redirect_uri, expected_state):
    registered = urlparse(redirect_uri)
    actual = urlparse(callback.strip())
    if (actual.scheme, actual.netloc, actual.path) != (registered.scheme, registered.netloc, registered.path):
        raise ValueError('Redirect URL does not match the registered redirect')
    params = parse_qs(actual.query)
    for key, value in parse_qs(registered.query).items():
        if params.get(key) != value:
            raise ValueError('Registered redirect parameters do not match')
    states = params.get('state', [])
    if len(states) != 1 or not secrets.compare_digest(states[0], expected_state):
        raise ValueError('OAuth state mismatch; start login again')
    codes = params.get('auth_code', [])
    if len(codes) != 1 or not codes[0]:
        raise ValueError('Redirect has no unique auth_code; start login again')
    return codes[0]


def save_token(path, credentials):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path.parent, 0o700)
    fd, temporary = tempfile.mkstemp(prefix='.fyers-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as handle:
            json.dump(credentials, handle)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)  # mkstemp creates mode 0600
    finally:
        Path(temporary).unlink(missing_ok=True)

