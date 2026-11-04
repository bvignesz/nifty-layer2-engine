"""Isolated manual and scheduled legacy research execution. No trading or arbitrary scripts."""
import argparse
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
import fcntl
import importlib.util
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time
import uuid
from types import SimpleNamespace

from . import fyers
from .storage import Store, canonical, digest, timestamp


class ReadOnlyClient:
    def __init__(self, credentials):
        self.credentials = credentials
        self.calls = []

    def __getattr__(self, name):
        if name not in ('quotes', 'history', 'optionchain'):
            raise AttributeError(name)
        def read(*, data):
            result = fyers.request(name, params=data, credentials=self.credentials)
            self.calls.append(dict(method=name, request=deepcopy(data), response=deepcopy(result)))
            return result
        return read


def evaluate_once(store, client, now=None, *, run_id=None, scheduled_at=None, trigger='manual'):
    """Execute original analytical function, persisting raw inputs and research output atomically."""
    now = now or datetime.now(timezone.utc)
    source = Path(__file__).with_name('legacy_engine.py')
    spec = importlib.util.spec_from_file_location('_nifty_live_research', source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.get_fyers_client = lambda: client
    module.now_ist = lambda: now.astimezone(module.IST)
    module.time = SimpleNamespace(time=lambda: now.timestamp())
    with store.transaction() as conn:
        @contextmanager
        def connection(_):
            yield conn
        module._storage_connection = connection
        state = module.poll_and_evaluate()
        if state.get('status') != 'OK' or state.get('error'):
            raise RuntimeError('Market data was incomplete; no new result was saved')
        event_id = store.event(conn, observed_at=now, kind='scheduled_research' if trigger == 'scheduled' else 'manual_research', source='fyers-read-only',
                               status='LEGACY_UNVALIDATED', payload={
                                   'run_id': run_id, 'scheduled_at_utc': scheduled_at,
                                   'calls': client.calls, 'engine_sha256': digest(source.read_text()),
                                   'configuration': {k: getattr(module, k) for k in (
                                       'ACTIVE_INDEX', 'NIFTY_LOT_SIZE', 'NIFTY_STRIKE_STEP',
                                       'MAX_ALLOWED_SPREAD', 'DEFAULT_STOP_PTS', 'TOP5_WEIGHTS',
                                       'HYPOTHESIS_THRESHOLDS', 'MIN_DTE_INTRADAY')},
                                   'risk_budget_rs': float(os.environ.get('RISK_PER_TRADE_RS', '7500.0'))})
        conn.execute('INSERT INTO signals VALUES (?,?,1,?)', (event_id, 'No Trade', canonical(state)))
        for number in range(1, 10):
            rows = state.get('scorecard', [])
            row = rows[number - 1] if len(rows) >= number else {}
            for side, label in [('BULL', 'Bull'), ('BEAR', 'Bear')]:
                conn.execute('INSERT INTO check_results VALUES (?,?,?,?,?)',
                             (event_id, number, side, row.get(label + '_Status', 'UNAVAILABLE'), canonical(row)))
        if run_id:
            conn.execute("UPDATE run_log SET status='COMPLETED', finished_at_utc=?, message=?, event_id=? WHERE run_id=?",
                         (timestamp(datetime.now(timezone.utc)), 'Nine checks and raw inputs saved.', event_id, run_id))
    return {'run_id': run_id, 'event_id': event_id, 'observed_at': now.isoformat(), 'state': state,
            'classification': 'No Trade', 'status': 'LEGACY_UNVALIDATED'}


class Runner:
    def __init__(self, directory, token_path):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.directory, 0o700)
        self.token_path = Path(token_path)
        self.process = None
        self.mutex = threading.Lock()

    def status(self):
        try:
            data = json.loads((self.directory / 'status.json').read_text())
        except (OSError, ValueError):
            data = {'status': 'IDLE', 'message': 'Ready to run your research script.'}
        if data.get('status') == 'RUNNING':
            with open(self.directory / 'run.lock', 'a') as handle:
                try:
                    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    data = {**data, 'status': 'INTERRUPTED', 'message': 'The last run stopped before completing.'}
                except BlockingIOError:
                    pass
        return data

    def start(self, *, trigger='manual', scheduled_at=None):
        if trigger not in ('manual', 'scheduled'):
            raise ValueError('Invalid run trigger')
        with self.mutex:
            if not self.token_path.exists():
                raise ValueError('Connect FYERS before running the script')
            handle = open(self.directory / 'run.lock', 'a')
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                handle.close()
                raise ValueError('A script run is already in progress') from None
            try:
                run_id = uuid.uuid4().hex
                store = Store(self.directory / 'research.db')
                with store.transaction() as conn:
                    if scheduled_at and conn.execute('SELECT 1 FROM run_log WHERE scheduled_at_utc=?', (scheduled_at,)).fetchone():
                        raise ValueError('This scheduled window was already recorded')
                    conn.execute('INSERT INTO run_log VALUES (?,?,?,?,?,?,?,?)',
                                 (run_id, trigger, scheduled_at, timestamp(datetime.now(timezone.utc)),
                                  None, 'RUNNING', 'Fetching FYERS data.', None))
                fyers.save_token(self.directory / 'status.json', {
                    'status': 'RUNNING', 'run_id': run_id, 'trigger': trigger,
                    'message': 'Fetching data and running the nine-check script.',
                    'started_at': datetime.now(timezone.utc).isoformat()})
                self.process = subprocess.Popen([
                    sys.executable, '-m', 'nifty_l2.runner', '--directory', str(self.directory),
                    '--token-path', str(self.token_path), '--lock-fd', str(handle.fileno()),
                    '--run-id', run_id, '--trigger', trigger,
                    *(['--scheduled-at', scheduled_at] if scheduled_at else [])],
                    pass_fds=(handle.fileno(),), stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except Exception:
                fyers.save_token(self.directory / 'status.json', {'status': 'FAILED', 'message': 'Could not start the worker.'})
                if 'run_id' in locals():
                    finish_log(self.directory, run_id, 'FAILED', 'Could not start the worker.')
                raise
            finally:
                handle.close()

    def stop(self):
        with self.mutex:
            if self.process is None or self.process.poll() is not None:
                current = self.status()
                if current.get('status') == 'RUNNING' and current.get('run_id'):
                    fyers.save_token(self.directory / 'stop-request.json', {'run_id': current['run_id']})
                return
            if self.process and self.process.poll() is None:
                self.process.terminate()
                try:
                    self.process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(timeout=5)
                fyers.save_token(self.directory / 'status.json', {'status': 'STOPPED', 'message': 'Run stopped. Incomplete database writes were rolled back.'})


def finish_log(directory, run_id, status, message):
    if not run_id:
        return
    with Store(Path(directory) / 'research.db').transaction() as conn:
        conn.execute("UPDATE run_log SET status=?, finished_at_utc=?, message=? WHERE run_id=? AND status='RUNNING'",
                     (status, timestamp(datetime.now(timezone.utc)), message, run_id))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', required=True)
    parser.add_argument('--token-path', required=True)
    parser.add_argument('--lock-fd', type=int, required=True)
    parser.add_argument('--run-id')
    parser.add_argument('--trigger', choices=['manual', 'scheduled'], default='manual')
    parser.add_argument('--scheduled-at')
    args = parser.parse_args()
    directory = Path(args.directory)
    # Inherited locked descriptor prevents overlapping workers, including across web processes.
    os.fstat(args.lock_fd)
    def stopped(*_):
        raise SystemExit(1)
    started = time.monotonic()
    def check_control(*_):
        if time.monotonic() - started >= 150:
            stopped()
        try:
            request = json.loads((directory / 'stop-request.json').read_text())
            if args.run_id and request.get('run_id') == args.run_id:
                stopped()
        except (OSError, ValueError, TypeError):
            pass
    signal.signal(signal.SIGTERM, stopped)
    signal.signal(signal.SIGALRM, check_control)
    signal.setitimer(signal.ITIMER_REAL, 1, 1)
    stage = 'connection'
    try:
        path = Path(args.token_path)
        if path.stat().st_mode & 0o077:
            raise ValueError('Token permissions invalid')
        credentials = json.loads(path.read_text())
        if not credentials.get('client_id') or not credentials.get('access_token'):
            raise ValueError('Token incomplete')
        fyers.request('profile', credentials=credentials)
        stage = 'market-data'
        result = evaluate_once(Store(directory / 'research.db'), ReadOnlyClient(credentials),
                               run_id=args.run_id, scheduled_at=args.scheduled_at, trigger=args.trigger)
        fyers.save_token(directory / 'result.json', result)
        fyers.save_token(directory / 'status.json', {
            'status': 'COMPLETED', 'message': 'Script completed. Results are unvalidated research.',
            'completed_at': datetime.now(timezone.utc).isoformat()})
    except BaseException as error:
        message = ('Run stopped or timed out.' if isinstance(error, SystemExit) else
                   'FYERS connection check failed; reconnect FYERS.' if stage == 'connection' else
                   'Market data or engine evaluation failed; no new result saved.')
        finish_log(directory, args.run_id, 'STOPPED' if isinstance(error, SystemExit) else 'FAILED', message)
        fyers.save_token(directory / 'status.json', {
            'status': 'STOPPED' if isinstance(error, SystemExit) else 'FAILED',
            'message': message,
            'completed_at': datetime.now(timezone.utc).isoformat()})
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        os.close(args.lock_fd)


if __name__ == '__main__':
    main()
