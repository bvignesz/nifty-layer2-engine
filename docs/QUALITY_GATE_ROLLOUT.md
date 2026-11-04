# Research collector quality-gate rollout

This branch is research-only. It does not enable trading or validate exchange quote timestamps.

## Changes
- Regular session ends 15:30 IST; special sessions retain their configured times.
- Reject missing ATM CE/PE coverage, invalid futures OI history, incomplete or stale futures bars, and mismatched futures quote/history symbols.
- Successful research events persist input_quality; exchange_quote_freshness remains UNVERIFIED.
- Failed gates roll back the event transaction and retain the prior result timestamp.

## Required validation
1. Run `.venv/bin/pytest -q` in the checkout.
2. Obtain redacted FYERS option-chain, quotes and futures-history payloads from an actual market session. Never commit credentials or OAuth URLs.
3. Verify quote symbol, candle timestamp meaning, OI units, expiry, ATM step, and completed-bar behavior.
4. Replay valid, stale, partial and rollover samples; reject invalid data without discarding valid data.
5. Run a research-only session soak test and inspect run_log failure counts and exchange timestamps.
6. Merge only after passing tests; restart collector outside market hours with a verified SQLite backup.

## Outstanding
- Exchange-origin timestamps for chain, quotes and constituents.
- Authoritative futures contract master and rollover selection; this change only detects mismatches.
- Historical Drive/CSV/SQLite import requires original exports and reconciliation.
- Leakage-safe outcome labels, walk-forward evaluation and XGBoost require validated observations.
- Real-money option expectancy needs executable bid/ask, fees and slippage.

Dashboard login is intentionally unchanged for this test environment.
