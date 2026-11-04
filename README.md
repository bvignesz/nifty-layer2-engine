# NIFTY Layer 2 — research-only SQLite migration

Phase 1 audit and Phase 2 migration tooling are implemented. Historical migration awaits original exports; market-hours research sampling and the web dashboard are enabled. Validated production signals, OpenBB deployment and ML training remain pending.

Read [audit](docs/AUDIT.md), [migration/schema/backup instructions](docs/MIGRATION.md), [OpenBB feasibility](docs/OPENBB.md) and [tests/services/Android access](docs/STATUS.md). Rotate exposed FYERS credentials before live use. The sanitized notebook is a historical reference, not the VPS entry point.

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.lock
.venv/bin/pip install --no-deps -e .
.venv/bin/nifty-l2 init
.venv/bin/pytest -q
```

Default database: `~/.local/share/nifty-layer2/nifty.db`. Storage/import CLI has no network or Google Drive dependency. Offline analytical replay requires the research dependencies in the lock file; it consumes recorded responses only and stores unvalidated original verdicts separately from the forced `No Trade` classification. No live-order client exists.

To authenticate FYERS from your private VPS terminal, follow [the connection guide](docs/FYERS_CONNECT.md). The helper verifies login and a quote without starting collection or placing orders.

The application is installed as `nifty-web.service` on this host. It includes **Connect FYERS**, private app settings, a quote check, isolated script start/stop controls and all nine research checks. See [access instructions and HTTPS deployment](docs/WEBAPP.md). The public application is live at https://13.211.127.67 with verified trusted TLS and automatic renewal. FYERS authentication and one completed live research run are verified. The background collector runs every three minutes during configured market sessions and stores run logs, raw market inputs and nine-check results in SQLite. It continues with the browser closed. Calendar coverage currently ends 31 December 2026. All 51 tests pass.
