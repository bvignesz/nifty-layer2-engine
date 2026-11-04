"""Persistent three-minute research sampler. No order placement or replay catch-up."""
import argparse
from datetime import datetime, timezone
import fcntl
import json
from pathlib import Path
import signal
import threading

from . import fyers
from .market_calendar import IST, slots, session, next_slot
from .runner import Runner
from .storage import Store, timestamp


class Collector:
    def __init__(self, directory, token_path):
        self.runner = Runner(directory, token_path)
        self.directory = self.runner.directory
        self.store = Store(self.directory / 'research.db')

    def record_slot(self, slot, status, message):
        value = timestamp(slot)
        with self.store.transaction() as conn:
            conn.execute('INSERT OR IGNORE INTO run_log VALUES (?,?,?,?,?,?,?,?)',
                         ('slot-' + value, 'scheduled', value, None,
                          timestamp(datetime.now(timezone.utc)), status, message, None))

    def recover(self):
        # Hold the execution lock during recovery, so a concurrently started
        # manual worker cannot be incorrectly marked interrupted.
        with open(self.directory / 'run.lock', 'a') as handle:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return
            with self.store.transaction() as conn:
                conn.execute("UPDATE run_log SET status='INTERRUPTED', finished_at_utc=?, message=? WHERE status='RUNNING'",
                             (timestamp(datetime.now(timezone.utc)), 'Worker exited before committing a result.'))

    def tick(self, now=None):
        now = now or datetime.now(timezone.utc)
        local = now.astimezone(IST)
        self.recover()
        if self.runner.process:
            self.runner.process.poll()
        status = {'status': 'WAITING', 'message': 'Waiting for the next exchange session.',
                  'updated_at': now.isoformat(), 'interval_minutes': 3,
                  'next_run': None}
        try:
            try:
                enabled = json.loads((self.directory / 'automation.json').read_text()).get('enabled') is True
            except FileNotFoundError:
                enabled = True
            if not enabled:
                status.update(status='PAUSED', message='Automatic collection is paused.')
            else:
                hours = session(local.date())
                upcoming = next_slot(now)
                status['next_run'] = upcoming.isoformat() if upcoming else None
                missed = [timestamp(slot) for slot in slots(local.date())
                          if (local - slot).total_seconds() > 20]
                if missed:
                    with self.store.transaction() as conn:
                        conn.executemany('INSERT OR IGNORE INTO run_log VALUES (?,?,?,?,?,?,?,?)',
                                         [('slot-' + value, 'scheduled', value, None, timestamp(now),
                                           'MISSED', 'Not sampled at this boundary; no historical snapshot fabricated.', None)
                                          for value in missed])
                if hours and hours[0] <= local < hours[1]:
                    status.update(status='ACTIVE', message='Sampling FYERS every three minutes during the exchange session.')
                    for slot in slots(local.date()):
                        if not 0 <= (local - slot).total_seconds() <= 20:
                            continue
                        value = timestamp(slot)
                        with self.store.connect() as conn:
                            exists = conn.execute('SELECT 1 FROM run_log WHERE scheduled_at_utc=?', (value,)).fetchone()
                        if exists:
                            continue
                        if not self.runner.token_path.exists():
                            self.record_slot(slot, 'BLOCKED', 'Connect FYERS to enable market-data collection.')
                            continue
                        try:
                            self.runner.start(trigger='scheduled', scheduled_at=value)
                        except ValueError:
                            self.record_slot(slot, 'SKIPPED', 'Another run is active or this boundary was already recorded.')
                        except OSError:
                            self.record_slot(slot, 'FAILED', 'Could not launch research worker.')
                elif hours:
                    status['message'] = 'Outside market hours; automatic collection resumes at the next session.'
                else:
                    status['message'] = 'Exchange holiday or weekend; waiting for the next session.'
        except (ValueError, KeyError, TypeError):
            status.update(status='CALENDAR_OR_CONFIG_ERROR', message='Calendar or automation settings need an update. Collection is paused.')
        fyers.save_token(self.directory / 'collector-status.json', status)
        return status


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', default=str(fyers.TOKEN_PATH.parent / 'web-runtime'))
    parser.add_argument('--token-path', default=str(fyers.TOKEN_PATH))
    args = parser.parse_args()
    collector = Collector(args.directory, args.token_path)
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    # Independent singleton lock; workers hold run.lock across web/service restarts.
    with open(collector.directory / 'collector.lock', 'a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        last = None
        while not stop.is_set():
            status = collector.tick()
            current = (status['status'], status['message'])
            if current != last:
                print(json.dumps({'status': current[0], 'message': current[1]}), flush=True)
                last = current
            stop.wait(5)
    collector.runner.stop()


if __name__ == '__main__':
    main()
