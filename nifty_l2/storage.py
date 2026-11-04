"""WAL storage, explicit transactions, UTC timestamps, immutable event identities."""
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
from zoneinfo import ZoneInfo

UTC = timezone.utc
IST = ZoneInfo("Asia/Kolkata")
DEFAULT_DB = Path(os.environ.get("NIFTY_DB_PATH", "~/.local/share/nifty-layer2/nifty.db")).expanduser()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def digest(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def timestamp(value, *, legacy_ist=False):
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, (int, float)) or (isinstance(value, str) and value.replace('.', '', 1).isdigit()):
        number = float(value)
        dt = datetime.fromtimestamp(number / 1000 if number > 1e12 else number, UTC)
    else:
        text = str(value).strip()
        if text.endswith(" IST"):
            text = text[:-4]
            legacy_ist = True
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        if not legacy_ist:
            raise ValueError("Naive timestamp requires explicit legacy IST policy")
        dt = dt.replace(tzinfo=IST)
    return dt.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


class Store:
    def __init__(self, path=DEFAULT_DB):
        self.path = Path(path).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with self.connect() as conn:
            if conn.execute("PRAGMA user_version").fetchone()[0] not in (0, 1):
                raise ValueError("Unsupported schema version")
            conn.executescript(Path(__file__).with_name("schema.sql").read_text())
        os.chmod(self.path, 0o600)

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        try:
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("PRAGMA busy_timeout=30000")
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=FULL")
            yield conn
        finally:
            conn.close()

    @contextmanager
    def transaction(self):
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                yield conn
                conn.commit()
            except BaseException:
                conn.rollback()
                raise

    def event(self, conn, *, observed_at, kind, source, payload, status="UNVERIFIED", exchange_at=None):
        utc = timestamp(observed_at)
        exchange = timestamp(exchange_at) if exchange_at is not None else None
        serialized = canonical(payload)
        event_id = digest(canonical([source, kind, utc, exchange, status, serialized]))
        ist = datetime.fromisoformat(utc.replace('Z', '+00:00')).astimezone(IST).isoformat()
        conn.execute("INSERT INTO events VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT DO NOTHING",
                     (event_id, utc, exchange, ist, kind, source, status, serialized, digest(serialized)))
        return event_id

    def integrity(self):
        with self.connect() as conn:
            checks = [r[0] for r in conn.execute("PRAGMA integrity_check")]
            foreign_keys = conn.execute("PRAGMA foreign_key_check").fetchall()
            counts = {name: conn.execute(f'SELECT count(*) FROM "{name}"').fetchone()[0]
                      for name, in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        return {"ok": checks == ["ok"] and not foreign_keys, "integrity_check": checks,
                "foreign_key_violations": foreign_keys, "counts": counts, "database": str(self.path)}

    def backup(self, destination):
        destination = Path(destination).expanduser().resolve()
        if destination == self.path:
            raise ValueError("Backup must have a different path")
        destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        # Exclusive creation prevents accidental overwrite of a prior backup.
        fd = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(fd)
        try:
            with self.connect() as source:
                target = sqlite3.connect(destination)
                try:
                    source.backup(target)
                    if (target.execute("PRAGMA integrity_check").fetchall() != [("ok",)]
                            or target.execute("PRAGMA foreign_key_check").fetchall()):
                        raise ValueError("Backup integrity check failed")
                finally:
                    target.close()
        except BaseException:
            destination.unlink(missing_ok=True)
            raise
        return {"path": str(destination), "sha256": hashlib.sha256(destination.read_bytes()).hexdigest()}
