# Drive-to-SQLite migration report — 2026-11-03

Status: migration tooling and offline storage tested; **historical production migration pending source exports**. No Drive mount or Drive data exists in this checkout. No historical data was deleted or changed. Real imported row count: **0**. Real date range/checksums: unavailable until exports are supplied. Test rows are synthetic and live in pytest temporary databases, not the production database.

## Database

Default absolute path on this host: `/home/ubuntu/.local/share/nifty-layer2/nifty.db`. Override with `--db` or `NIFTY_DB_PATH`. Database file mode is 0600; newly created data directories use 0700. Schema: `nifty_l2/schema.sql`; version 1. All application connections enable WAL, FULL synchronous writes, foreign keys, and a 30-second busy timeout. Explicit `BEGIN IMMEDIATE` transactions roll back on exceptions. Connections close after use. One serialized SQLite writer is appropriate for this phase; a future API must use read-only connections.

| Table | Purpose / identity |
|---|---|
| events | Immutable content-addressed event, receipt UTC, nullable exchange UTC, IST display, quality, raw JSON and SHA-256 |
| option_snapshots | Event + symbol; raw option values and JSON |
| futures_data | Event + futures symbol; exchange time, close/VWAP/OI and raw JSON |
| check_results | Event + check 1–9 + BULL/BEAR; PASS/FAIL/UNAVAILABLE/STALE |
| signals | One research classification/event; original state in JSON; research-only constraint |
| outcomes | Event + 9/15/30-minute horizon; return, availability UTC, evidence and status |
| import_files | Source byte SHA-256, size/name, row count, row checksum, date range |
| import_rows | Source SHA + row ordinal; row hash and destination event mapping |
| header_snapshots / strike_snapshots | Original schema, used only as the offline replay's analytical cache |

Indexes cover event time/kind, exchange time, option symbols, futures exchange time, outcome availability, import-event links and legacy expiry/time. Event identity hashes source, kind, normalized observation/exchange time, quality and canonical payload. Exact repeated rows deduplicate even across exports; every source row keeps provenance, so manifest row counts can exceed unique-event counts. Changed payloads at the same timestamp remain separate auditable events rather than overwriting each other. Replay cache tables preserve original keys and are not a production feed.

Receipt and exchange times are distinct. Legacy `IST_Time`/`ist_time` are interpreted explicitly as Asia/Kolkata; timezone-aware strings and epoch seconds/milliseconds are supported. Other naive timestamp strings are rejected. Historical exchange time is NULL unless provided through a validated storage contract; receipt time is never presented as exchange time.

## Reproducible commands

From `/home/ubuntu/nifty-layer2-engine`:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.lock
.venv/bin/pip install --no-deps -e .
.venv/bin/nifty-l2 init
.venv/bin/nifty-l2 import /path/to/exports/nifty_live_chain.csv /path/to/exports/nifty_signals_log.csv /path/to/exports/nifty_layer2_corrected_audit.csv
.venv/bin/nifty-l2 verify-imports
.venv/bin/nifty-l2 integrity
.venv/bin/nifty-l2 backup /path/to/new/backup.db
```

For the untimestamped overwritten scorecard, provide its **known** capture time separately:

```bash
.venv/bin/nifty-l2 import /path/to/exports/nifty_6check_scorecard.csv --observed-at '2026-11-03T09:18:00+05:30'
```

Do not guess this time from today's date or a downloaded file's modification time. If it is unknown, retain the file outside the analytical timeline until provenance is resolved. A JSON file can contain one flat row object or an array of row objects; arbitrary object payloads are retained losslessly, but unknown nested export formats need a format-specific adapter. Files are processed atomically one at a time; a later file failing does not undo earlier successful files.

Imports read the source bytes, reject malformed CSV widths/duplicate headers, calculate a source SHA-256, retain original row values as JSON, and normalize known chain, check, futures and explicit verdict fields. Original signal CSV pass flags recover all eighteen checks. Missing futures contract identity is explicitly `legacy:UNKNOWN_FUTURES`; missing exchange timestamp is NULL. A prose signal banner is never converted into an invented final verdict. A different row type remains inspectable in events. Source snapshots/logs can represent the same moment without enough keys for a trustworthy join: the importer retains their distinct records and does not fabricate a joined evaluation.

A file SHA already in the manifest triggers destination verification without inserting rows. Verification reconstructs hashes from stored payloads and checks every row hash, row count, ordered aggregate checksum and UTC date range. After a new import the source bytes are rehashed to detect concurrent edits. `verify-imports` checks the database against saved manifests; rerunning `import` also checks the current source bytes. Empty import listings are not evidence of a successful production migration.

## Preserve the original SQLite database too

The notebook already has useful `nifty_oc_history.db` history. Keep it with the CSV/JSON exports. This phase's importer intentionally accepts CSV/JSON only; no old database was supplied. Before exporting its tables, make a consistent copy with SQLite's online backup API (or stop its writer and retain all associated files); copying only a live WAL database's main file can lose data. Export the copied `header_snapshots` and `strike_snapshots` rows to JSON with their `ts` keys and import them as lossless legacy records. Contract/expiry enrichment requires an explicit verified header/strike join and will be implemented after inspecting the actual historical database. Do not replace the new database file with the legacy one.

## Validation and cutover

Before declaring historical migration validated: inventory each export and the old SQLite copy; record source checksums and source row counts; run imports and repeat imports; inspect zero checksum/count/date-range failures; reconcile duplicate rows versus unique events and overlapping log streams; manually inspect sample rows at first/last timestamps and expiry boundaries; inspect integrity and backup restoration. Keep all originals and a source manifest after cutover. Older overwritten chain/scorecard versions cannot be recovered from their latest files alone.

The new package has no Google Colab/Drive dependency. The sanitized notebook remains a baseline reference and still contains its original Drive setup; it must not be run as the VPS service. Production cutover has not been declared successful.

## Integrity and backups

`integrity` runs full SQLite integrity and foreign-key checks and returns counts. `backup` uses SQLite's online backup API, works with WAL, verifies the copied database, computes SHA-256, and refuses to overwrite an existing destination. Initial empty-database backup: `/home/ubuntu/.local/share/nifty-layer2/backups/initial-20261103.db`; see `backup-status.json`. A test restored a populated backup and compared table counts and integrity. An empty initial backup is not historical-data protection.

Before production collection, add a systemd backup timer with unique UTC-dated destinations, retention and disk-space alerts, and periodically restore a backup into a separate path and run `integrity` and `verify-imports`. Backup automation is not installed in this phase. Local backups protect against logical/application mistakes; off-host encrypted backup is still needed for host loss. Never restore over a running writer or delete Drive originals to save space during validation.
