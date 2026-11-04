PRAGMA user_version = 1;
CREATE TABLE IF NOT EXISTS events (
 event_id TEXT PRIMARY KEY, observed_at_utc TEXT NOT NULL,
 exchange_at_utc TEXT, display_time_ist TEXT NOT NULL,
 kind TEXT NOT NULL, source TEXT NOT NULL, status TEXT NOT NULL,
 payload_json TEXT NOT NULL CHECK(json_valid(payload_json)), payload_sha256 TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS events_time_kind ON events(observed_at_utc,kind);
CREATE INDEX IF NOT EXISTS events_exchange ON events(exchange_at_utc);
CREATE TABLE IF NOT EXISTS option_snapshots (
 event_id TEXT NOT NULL REFERENCES events(event_id), symbol TEXT NOT NULL,
 strike REAL NOT NULL, option_type TEXT NOT NULL CHECK(option_type IN ('CE','PE')),
 expiry TEXT, ltp REAL, bid REAL, ask REAL, oi REAL, volume REAL,
 payload_json TEXT NOT NULL CHECK(json_valid(payload_json)),
 PRIMARY KEY(event_id,symbol)
);
CREATE INDEX IF NOT EXISTS options_contract ON option_snapshots(symbol,event_id);
CREATE TABLE IF NOT EXISTS futures_data (
 event_id TEXT NOT NULL REFERENCES events(event_id), symbol TEXT NOT NULL,
 exchange_at_utc TEXT, close REAL, vwap REAL, oi REAL,
 payload_json TEXT NOT NULL CHECK(json_valid(payload_json)), PRIMARY KEY(event_id,symbol)
);
CREATE INDEX IF NOT EXISTS futures_exchange ON futures_data(symbol,exchange_at_utc);
CREATE TABLE IF NOT EXISTS check_results (
 event_id TEXT NOT NULL REFERENCES events(event_id), check_number INTEGER NOT NULL CHECK(check_number BETWEEN 1 AND 9),
 side TEXT NOT NULL CHECK(side IN ('BULL','BEAR')),
 status TEXT NOT NULL CHECK(status IN ('PASS','FAIL','UNAVAILABLE','STALE')),
 payload_json TEXT NOT NULL CHECK(json_valid(payload_json)), PRIMARY KEY(event_id,check_number,side)
);
CREATE TABLE IF NOT EXISTS signals (
 event_id TEXT PRIMARY KEY REFERENCES events(event_id),
 classification TEXT NOT NULL CHECK(classification IN ('Bullish','Bearish','No Trade')),
 research_only INTEGER NOT NULL DEFAULT 1 CHECK(research_only=1),
 payload_json TEXT NOT NULL CHECK(json_valid(payload_json))
);
CREATE TABLE IF NOT EXISTS outcomes (
 event_id TEXT NOT NULL REFERENCES events(event_id), horizon_minutes INTEGER NOT NULL CHECK(horizon_minutes IN (9,15,30)),
 available_at_utc TEXT NOT NULL, forward_return REAL, status TEXT NOT NULL,
 payload_json TEXT NOT NULL CHECK(json_valid(payload_json)), PRIMARY KEY(event_id,horizon_minutes)
);
CREATE INDEX IF NOT EXISTS outcomes_available ON outcomes(available_at_utc);
CREATE TABLE IF NOT EXISTS import_files (
 file_sha256 TEXT PRIMARY KEY, byte_count INTEGER NOT NULL, file_name TEXT NOT NULL,
 imported_at_utc TEXT NOT NULL, row_count INTEGER NOT NULL,
 row_checksum TEXT NOT NULL, min_time_utc TEXT, max_time_utc TEXT
);
CREATE TABLE IF NOT EXISTS import_rows (
 file_sha256 TEXT NOT NULL REFERENCES import_files(file_sha256), row_number INTEGER NOT NULL,
 row_sha256 TEXT NOT NULL, event_id TEXT NOT NULL REFERENCES events(event_id),
 PRIMARY KEY(file_sha256,row_number)
);
CREATE INDEX IF NOT EXISTS imported_event ON import_rows(event_id);

-- Legacy analytical cache for replay and unvalidated research observations.
CREATE TABLE IF NOT EXISTS header_snapshots (
                ts INTEGER PRIMARY KEY, ist_time TEXT, spot REAL, vix REAL, vix_chp REAL,
                fut_close REAL, fut_vwap REAL, fut_oi INTEGER,
                top5_bull INTEGER, top5_bear INTEGER, expiry_date TEXT, dte INTEGER
            );
CREATE TABLE IF NOT EXISTS strike_snapshots (
                ts INTEGER, strike INTEGER, opt_type TEXT, symbol TEXT,
                ltp REAL, bid REAL, ask REAL, oi INTEGER, oich INTEGER, oichp REAL,
                volume INTEGER, iv REAL, delta REAL, gamma REAL, theta REAL, vega REAL,
                PRIMARY KEY (ts, strike, opt_type)
            );
CREATE INDEX IF NOT EXISTS legacy_headers_expiry_time ON header_snapshots(expiry_date,ts);

-- Durable execution history; missed slots never become fabricated market data.
CREATE TABLE IF NOT EXISTS run_log (
 run_id TEXT PRIMARY KEY,
 trigger TEXT NOT NULL CHECK(trigger IN ('manual','scheduled')),
 scheduled_at_utc TEXT UNIQUE,
 started_at_utc TEXT,
 finished_at_utc TEXT,
 status TEXT NOT NULL,
 message TEXT NOT NULL,
 event_id TEXT REFERENCES events(event_id)
);
CREATE INDEX IF NOT EXISTS run_log_time ON run_log(started_at_utc,scheduled_at_utc);
