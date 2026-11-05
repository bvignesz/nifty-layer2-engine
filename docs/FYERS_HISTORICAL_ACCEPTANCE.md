# Stage 2–8: historical quality + live FYERS acceptance (PRE-INSTALL)

This runbook is intentionally **not a deployment procedure**. Use it on AWS only after the offline GitHub CI tests are green. Do not merge PR #6, restart systemd, update working production checkout or touch live tokens.

## Offline tests

GitHub Actions runs the complete repository test suite on Python 3.12 and includes the frozen nine-check source hash. Offline mocked FYERS success proves request orchestration but **does not prove** that your real FYERS account has historical OI access or that it returns correct data.

## AWS real-data evidence (only after manual command)

Use a separate worktree and the existing virtual environment. This keeps your production web/collector files intact.

```bash
git -C ~/nifty-layer2-engine fetch origin
git -C ~/nifty-layer2-engine worktree add ~/nifty-platform-validation origin/feat/research-platform-milestones-2-8
cd ~/nifty-platform-validation
PY=/home/ubuntu/nifty-layer2-engine/.venv/bin/python
$PY -m pytest -q
mkdir -p ~/nifty-validation-reports
chmod 700 ~/nifty-validation-reports
```

Run the historical audit against the actual SQLite storage file **read-only**. Do not copy database content into a public bug report:

```bash
$PY -m nifty_l2.historical_validation \
  --db /home/ubuntu/.config/nifty-layer2/web-runtime/research.db \
  --report ~/nifty-validation-reports/historical.json
```

It reports missing exchange timestamps, stale/gapped observation chains, invalid or orphan strikes, incomplete directional nine checks, and suspiciously constant gamma. It will classify data as `REQUIRES_MARKET_VALIDATION` when the database lacks independently timestamped exchange observations; this is **expected** in the current baseline.

Run the FYERS integration test **after reconnecting FYERS if the token has expired**. It requires the existing private 0600 token file. There is no order placement, token renewal, token printout, or collector modification. The test makes at most 7 read-only requests when a future is supplied (verify account rate limits).

```bash
$PY -m nifty_l2.fyers_integration_probe --live \
  --token-path /home/ubuntu/.config/nifty-layer2/fyers-token.json \
  --equity-symbol NSE:TCS-EQ \
  --future-symbol NSE:NIFTY26NOVFUT \
  --report ~/nifty-validation-reports/fyers-probe.json
```

**Important:** `NSE:NIFTY26NOVFUT` is an *example*; replace it with the actual currently trading contract from your approved FYERS symbol master. Do not blindly reuse a guessed symbol. The probe does not refresh tokens or place orders.

Inspect the resulting **status summaries only** (avoid sharing credentials or raw market response files). The probe intentionally marks `market_data_verified=false` even when every API request succeeds. Validated exchange timestamps and corporate-action equivalence are separate tasks.

## Consolidated release gate

The gate requires `historical.json` and `fyers-probe.json`, plus separately approved audit evidence for:
- `eod-parity.json`: matching adjusted-price/corporate-action handling and sample daily/15m OHLCV for reference symbols;
- `greeks-audit.json`: actual OI units, gamma/IV consistency, expiry scaling and scenario assumptions;
- `outcome-audit.json`: verified exchange candle close stamps and held-out future-label provenance, without lookahead;
- `security-audit.json`: browser authentication, OAuth/CSRF isolation, backup/rollback and exposure review.

Passing a mocked test is **not** the required evidence for these audits; review independently before writing `{"verified":true}`.

```bash
$PY -m nifty_l2.release_gate \
  --historical ~/nifty-validation-reports/historical.json \
  --fyers ~/nifty-validation-reports/fyers-probe.json \
  --report ~/nifty-validation-reports/release-gate.json
```

With outstanding audit files absent or incomplete, this **must say BLOCKED**. That is correct behavior, not a software failure.

## Deferred: controlled production installation

Only after all required gates are independently verified: record production systemd unit definitions, backup SQLite via the SQLite backup API, record checkout SHA, test APIs/UI with a copy of the DB, then release only the approved commit to the web service with rollback, **without restarting the NIFTY collector or rewriting historical research**.

No installation or merge is authorized by this development/validation runbook.

## Historical futures persistence correction (2026-11-05)

The AWS validation found 111 research events and 111 missing event-level exchange timestamps; `futures_data` had 0 rows. This is **not** enough to claim a missing futures feed: the existing `runner.evaluate_once` archives FYERS calls in `events.payload_json` but (unlike `replay.replay`) did not populate `futures_data`.

The development branch now calls `persist_futures` inside the existing atomic research transaction to persist the **latest actual completed, bounded-age futures candle** with its source-provided candle-start UTC timestamp and OI. If no eligible completed candle with OI exists, no row is written. It **does not** set `events.exchange_at_utc` from a futures candle, and it never changes the nine-check valuation result.

Inspect existing archived data **read only**:

```bash
cd ~/nifty-platform-validation
PY=/home/ubuntu/nifty-layer2-engine/.venv/bin/python
$PY -m nifty_l2.futures_archive_audit \\
  --db /home/ubuntu/.config/nifty-layer2/web-runtime/research.db \\
  --report ~/nifty-validation-reports/futures-archive-audit.json
```

To assess recoverable futures records, use **copy-only** normalization (never live DB):

```bash
$PY -m nifty_l2.futures_copy_backfill \\
  --source /home/ubuntu/.config/nifty-layer2/web-runtime/research.db \\
  --output ~/nifty-validation-reports/research-futures-copy.db
```

This second command creates a new private SQLite copy and refuses overwrites. It does NOT install, merge, restart web/collector or mutate production. Neither backfill nor futures provenance can retroactively supply a valid option-chain exchange timestamp. The six historical collection gaps remain visible and are excluded from comparable three-minute change calculations. Existing market-quality gates remain blocked until trustworthy exchange-time evidence is available.
