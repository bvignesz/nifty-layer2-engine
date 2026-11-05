# Stored strike terminal UI (presentation only)

This branch changes presentation without changing the FYERS collector, the original nine-check valuation/decision logic, SQLite schema, or stored values.

- Reads existing `header_snapshots` and `strike_snapshots` through the unchanged, parameterized `nifty_l2.terminal.snapshots` query. Preserves date, expiry, strike, pagination, export and original full research summary.
- New `nifty_l2.terminal_ui` renders CE/PE OI latest values and the stored per-contract gamma alongside futures close, volume, and 11 terminal columns. Missing seller-only writing/buying/exit attribution, notional CE/PE/net GEX, and 1-minute flows are **unavailable**, never made up.
- The existing `/export` source provides data for the "Copy Table as Text" button. No external Tailwind dependency is introduced because the existing app's CSP blocks external styling.
- The `/terminal.js` static route permits clipboard copy under `script-src 'self'`; it doesn't touch broker settings or SQLite.
- Snapshot timestamps are observation times, not completed 1-minute candles. Even a scheduled 3-minute sample is not a verified completed 3-minute OHLC candle.
- The mock GEX values in the design request are not shown as real values.
- This does NOT change historical valuation, strike records, or any trading signal.

## Local checks (before merging/deploying)

```bash
git fetch origin
git switch feat/snapshot-terminal-ui-safe
.venv/bin/python -m pytest -q tests/test_terminal.py tests/test_terminal_ui.py tests/test_web.py
.venv/bin/python -m pytest -q
```

Inspect the dashboard in a browser while the service stays on its existing release. On the PR branch, the UI is not automatically deployed by GitHub.

## Release safety

Do not update the running AWS checkout or restart `nifty-web.service` until tests pass and the UI is reviewed. Backup `research.db` before deployment. If desired, run the web server on a separate localhost port with a separate test runtime directory and verify it with a copied SQLite database. Deployment is a separate step; leave production settings and the running FYERS collector unchanged.

## Limitations

The chosen strike table shows one CE/PE row pair per saved timestamp, up to 12 timestamps per page. It does not synthesize intermediate 1-minute candles, derive dealer exposure from raw Greeks, or infer buyer/seller identity from aggregate OI and volume. Read-only JS export requires a secure context for clipboard access; the Export TXT link is the fallback.
