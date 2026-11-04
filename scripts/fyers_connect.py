"""Interactive FYERS OAuth and read-only connection check. No collector or orders.

Uses documented REST endpoints; no SDK request logs or credentials in arguments.
"""
import argparse
from datetime import datetime, timezone
from getpass import getpass
import hashlib
import json
import math
import os
from pathlib import Path
import secrets
import sys
import tempfile
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

from nifty_l2.fyers import TOKEN_PATH, DEFAULT_REDIRECT, request, parse_callback, save_token


def login(path=TOKEN_PATH):
    client_id = input('New FYERS App ID (complete ID from dashboard): ').strip()
    secret_key = getpass('New FYERS App Secret (hidden): ').strip()
    redirect_uri = input(f'Registered redirect URL [{DEFAULT_REDIRECT}]: ').strip() or DEFAULT_REDIRECT
    parsed = urlparse(redirect_uri)
    if not client_id or not secret_key:
        raise ValueError('App ID and App Secret are required')
    if parsed.scheme != 'https' or not parsed.netloc or parsed.username or parsed.fragment:
        raise ValueError('Use a registered HTTPS redirect URL')
    state = secrets.token_urlsafe(32)
    url = 'https://api-t1.fyers.in/api/v3/generate-authcode?' + urlencode({
        'client_id': client_id, 'redirect_uri': redirect_uri, 'response_type': 'code', 'state': state,
    })
    print('\nOpen this URL in your browser and complete FYERS login:\n' + url)
    callback = getpass('\nPaste the FULL final redirected URL here (hidden): ')
    auth_code = parse_callback(callback, redirect_uri, state)
    result = request('exchange', payload={
        'grant_type': 'authorization_code',
        'appIdHash': hashlib.sha256(f'{client_id}:{secret_key}'.encode()).hexdigest(),
        'code': auth_code,
    })
    token = result.get('access_token')
    if not isinstance(token, str) or not token:
        raise RuntimeError('FYERS did not return an access token')
    credentials = {'client_id': client_id, 'access_token': token, 'redirect_uri': redirect_uri,
                   'created_at_utc': datetime.now(timezone.utc).isoformat()}
    # Verify authentication before replacing an existing saved token.
    request('profile', credentials=credentials)
    save_token(path, credentials)
    print(f'FYERS authentication verified. Token saved privately to {path}')
    print('Run the check command next to test NIFTY market-data access.')


def check(path=TOKEN_PATH):
    path = Path(path)
    if path.stat().st_mode & 0o077:
        raise ValueError('Token file must be private; run chmod 600 on the token file')
    credentials = json.loads(path.read_text())
    if not credentials.get('client_id') or not credentials.get('access_token'):
        raise ValueError('Token file is incomplete; run login again')
    request('profile', credentials=credentials)
    print('FYERS authentication: OK')
    result = request('quote', credentials=credentials)
    items = [item for item in result.get('d', []) if item.get('n') == 'NSE:NIFTY50-INDEX' and item.get('s') == 'ok']
    if len(items) != 1:
        raise RuntimeError('FYERS returned no unique successful NIFTY quote')
    price = float(items[0].get('v', {}).get('lp', 0))
    if not math.isfinite(price) or price <= 0:
        raise RuntimeError('FYERS returned an invalid NIFTY price')
    print(f'NIFTY quote: {price:.2f}')
    print('Market-data access: OK (quote freshness has not been validated)')
    print('Collector remains stopped. No orders were placed.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('login', 'check'))
    args = parser.parse_args()
    if args.action == 'login' and not sys.stdin.isatty():
        parser.error('Login requires your interactive VPS terminal; do not paste credentials into chat')
    try:
        (login if args.action == 'login' else check)()
    except (ValueError, RuntimeError, OSError, KeyError) as error:
        if isinstance(error, OSError):
            print('Local token file unavailable; run login or check its permissions.', file=sys.stderr)
        elif isinstance(error, (ValueError, KeyError)):
            print('Invalid login/callback/token data; check your entries and try again.', file=sys.stderr)
        else:
            print(str(error), file=sys.stderr)
        raise SystemExit(1)
    except (KeyboardInterrupt, EOFError):
        print('\nLogin cancelled; no engine was started.', file=sys.stderr)
        raise SystemExit(1)


if __name__ == '__main__':
    main()
