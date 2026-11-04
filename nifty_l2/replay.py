"""Transactional offline replay of recorded FYERS responses. No FYERS SDK or network.

Legacy timing and freshness defects are preserved for parity research; classification
in the validated signals table is always No Trade until the live pipeline is validated.
"""
from contextlib import contextmanager, redirect_stdout
from copy import deepcopy
from datetime import datetime
import importlib.util
import io
from pathlib import Path
from types import SimpleNamespace
from .storage import canonical, digest, timestamp


class RecordedFyers:
    def __init__(self, calls):
        self.calls = deepcopy(calls)
        self.position = 0

    def __getattr__(self, method):
        if method not in ('optionchain', 'quotes', 'history'):
            raise AttributeError(method)
        def call(*, data):
            if self.position >= len(self.calls):
                raise ValueError('Recorded response exhausted')
            item = self.calls[self.position]
            self.position += 1
            if item['method'] != method or item['request'] != data:
                raise ValueError('Recorded FYERS request mismatch')
            return deepcopy(item['response'])
        return call


def replay(store, *, observed_at, calls):
    utc = timestamp(observed_at)
    dt = datetime.fromisoformat(utc.replace('Z', '+00:00'))
    spec = importlib.util.spec_from_file_location('_nifty_offline_replay', Path(__file__).with_name('legacy_engine.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    client = RecordedFyers(calls)
    module.get_fyers_client = lambda: client
    module.now_ist = lambda: dt.astimezone(module.IST)
    module.time = SimpleNamespace(time=lambda: dt.timestamp())
    with store.transaction() as conn:
        @contextmanager
        def connection(_):
            yield conn
        module._storage_connection = connection
        # Raw records are copied before the original engine mutates option greeks.
        eid = store.event(conn, observed_at=utc, kind='offline_replay', source='recorded-fyers',
                          payload={'calls': calls,
                                   'engine_sha256': digest(Path(__file__).with_name('legacy_engine.py').read_text()),
                                   'configuration': {key: getattr(module, key) for key in (
                                       'ACTIVE_INDEX', 'NIFTY_LOT_SIZE', 'NIFTY_STRIKE_STEP',
                                       'MAX_ALLOWED_SPREAD', 'DEFAULT_STOP_PTS', 'TOP5_WEIGHTS',
                                       'HYPOTHESIS_THRESHOLDS', 'MIN_DTE_INTRADAY')},
                                   'risk_budget_rs': float(module.os.environ.get('RISK_PER_TRADE_RS', '7500.0'))},
                          status='LEGACY_UNVALIDATED')
        if conn.execute('SELECT 1 FROM signals WHERE event_id=?', (eid,)).fetchone():
            return {'event_id': eid, 'duplicate': True}
        with redirect_stdout(io.StringIO()):
            state = module.poll_and_evaluate()
        if client.position != len(client.calls):
            raise ValueError('Unused recorded FYERS responses')
        # Persist original verdict for audit without authorizing research signals.
        conn.execute('INSERT INTO signals VALUES (?, ?, 1, ?)', (eid, 'No Trade', canonical(state)))
        checks = state.get('scorecard', [])
        for number in range(1, 10):
            row = checks[number - 1] if number <= len(checks) else {}
            for side, label in [('BULL', 'Bull'), ('BEAR', 'Bear')]:
                conn.execute('INSERT INTO check_results VALUES (?,?,?,?,?)',
                             (eid, number, side, row.get(f'{label}_Status', 'UNAVAILABLE'), canonical(row)))
        for item in calls:
            response = item['response']
            if item['method'] == 'optionchain':
                for leg in response.get('data', {}).get('optionsChain', []):
                    if leg.get('option_type') not in ('CE', 'PE'):
                        continue
                    conn.execute('INSERT INTO option_snapshots VALUES (?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT DO NOTHING',
                                 (eid, leg['symbol'], leg['strike_price'], leg['option_type'],
                                  None, leg.get('ltp'), leg.get('bid'), leg.get('ask'), leg.get('oi'), leg.get('volume'), canonical(leg)))
            if item['method'] == 'history' and item['request']['symbol'].endswith('FUT'):
                symbol = item['request']['symbol']
                # Full candles retained, including their exchange epochs. No fabricated timestamp.
                candles = response.get('candles', [])
                if candles:
                    conn.execute('INSERT OR REPLACE INTO futures_data VALUES (?,?,?,?,?,?,?)',
                                 (eid, symbol, timestamp(candles[-1][0]), candles[-1][4], None,
                                  candles[-1][6] if len(candles[-1]) > 6 else None, canonical(response)))
    return {'event_id': eid, 'duplicate': False, 'state': state, 'classification': 'No Trade',
            'status': 'LEGACY_UNVALIDATED'}
