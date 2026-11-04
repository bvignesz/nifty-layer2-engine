> Automation update 2026-11-04: FYERS profile verified live; one completed engine result with 18 directional check records confirmed in SQLite. `nifty-collector.service` is active and enabled at boot, sampling every three minutes during dated NSE F&O sessions and storing execution history in `web-runtime/research.db`. Live state WAITING; next run 2026-11-05 09:15 IST. 51 tests pass. Calendar coverage ends 2026-12-31 and then pauses pending update. Read-only research sampling is enabled; validated signal collection, ML and trading remain pending. See [WEBAPP.md](WEBAPP.md). This supersedes older collector/authentication statements below.

> Access update 2026-11-04: Dashboard username/password login disabled at the user’s request; deployed password removed. Public HTTPS without credentials verified as HTTP 200. FYERS login remains required. This supersedes earlier dashboard authentication statements below.

> Public deployment update 2026-11-04: https://13.211.127.67 is live with a trusted Let’s Encrypt IP certificate. `nifty-proxy.service` handles automatic renewal over port 443 and forwards to `nifty-web.service`. Both services are enabled and active. Public unauthenticated HTTP 401 and authenticated HTTP 200 were verified with normal TLS validation. Register FYERS callback https://13.211.127.67/oauth/callback. Real account login remains pending. This supersedes older public-routing statements below.

> Update 2026-11-04: The protected Python application is installed, enabled and running as `nifty-web.service` on 127.0.0.1:8080. FYERS OAuth, private browser app settings, script start/stop and research results are implemented. All 41 tests pass; actual authenticated HTTP returned 200. Public HTTPS routing and real FYERS login remain pending. See [WEBAPP.md](WEBAPP.md). The older service/access statements below are historical and superseded by this update. Production calendar-based collection and ML remain pending.

# Verification, service and access status — 2026-11-03

## Actual verification

`docs/test-results.txt` and `docs/test-results.xml` contain the actual latest automated run. Twenty-four tests passed; zero test failures remain in the implemented scope. `requirements.lock` records the installed test/research environment; Python is 3.12 on this host. System `python3-venv` was installed because the host initially lacked ensurepip.

Covered: WAL/foreign keys; atomic rollback; repeat/copy/overlapping imports; unchanged source bytes; UTC/IST conversion and naive-time rejection; untimestamped scorecard policy; chain normalization; reconstruction of original nine-check flags and legacy futures; tamper detection through recomputed checksums; consistent backup/restore and overwrite refusal; all-nine-check replay over three synthetic observations; AST preservation of analytical functions; Greek/lot sanity; missing-data replay and exact request matching; incomplete/stale/malformed futures candles and duplicate conflicts; explicit unavailable checks; outcome availability horizons and immutable correction policy.

Limitations: synthetic replay demonstrates calculation execution and preservation, not strategy validity. The full production FYERS response parser, exchange-calendar scheduler, production endpoints and ML pipeline do not exist yet and have **not** passed tests. Real FYERS timestamp mappings, authenticated acquisition, holiday/special-session coverage and historical migration reconciliation require actual source data. A basic candle-array parser exists; it is not a complete session-calendar or feed validator.

Production SQLite integrity: `ok`; zero foreign-key violations; zero market events/imports/outcomes. Machine result: `database-status.json`. Initial local backup verified; actual path/hash: `backup-status.json`. No sample trades or model-performance metrics are claimed. A subsequent interactive FYERS login/quote-check helper is available; see `FYERS_CONNECT.md`. Its four tests use mocked responses. Actual user authentication is still pending.

## Running services

`systemctl list-unit-files 'nifty*' --no-pager` reported **0 unit files**. No NIFTY collector, terminal, OpenBB service or model service is installed/running. No public application port or tunnel was opened. This is the available workspace host; no separate Hostinger target identity or SSH deployment details were supplied or verified.

## Next collector stage

After historical import reconciliation and credential rotation: implement a dated authoritative NSE session source, including holidays, closures and special sessions; use 09:15–15:30 IST for regular sessions; collect timestamped raw snapshots; evaluate at completed three-minute boundaries anchored to session open, with explicit gaps and restart catch-up policy. Observe during windows and never substitute polling intervals for completed windows. Prevent duplicate window evaluations under restart or concurrent triggers. Correct and test stale-futures fallback, partial chains, instrument/expiry identity and missing-data propagation before enabling the service.

Use a long-running, session-aware worker under systemd with restart/backoff, token-expiry health reporting, structured journal logs and watchdog/monitoring. Add independent integrity/backup timers. Merely using a weekday systemd timer would not satisfy actual exchange sessions. Retain the original research logic and record any justified calculation correction/version with replay comparisons. Never include live-order code.

## ML stage is deliberately pending

Actual usable validated production sample size: **0**. XGBoost training, predictive metrics, net expectancy, feature dataset generation and walk-forward validation are not yet available. No model has been trained or enabled.

Future datasets must use only features available by each decision's `available_at`; preserve receipt and exchange time separately and use instrument/expiry-aware joins. Label spot returns at exactly 9/15/30-minute horizons within a session, with documented matching tolerance; missing or stale future observations remain unavailable. Split chronologically by sessions, purge training labels extending into test periods (at least the maximum 30-minute horizon), and prevent overlapping outcomes from contaminating folds. Fit preprocessing/tuning on training data only. Reserve a final untouched evaluation period and report effective independent sample counts as well as raw rows. Compare original strategy and XGBoost on the same dates, decision opportunities and cost assumptions. Spot-direction prediction alone cannot establish option-trade net expectancy; use executable bid/ask option observations plus fees, slippage and contract mapping. No claim of sufficient data or fixed sample threshold is justified yet. Validated data, sufficient independent sessions, out-of-sample evidence and explicit user model approval are required before ML-based live research signals.

## Android access

No terminal URL exists yet. Do not use the notebook's old temporary Cloudflare address. After the collector is validated and terminal deployed: open `https://<your-configured-domain>/` in Android Chrome, authenticate, verify the last exchange timestamp and quality banner, and optionally add the page to the home screen. A domain, certificate and authentication are still to be configured. If using hosted OpenBB Workspace, sign in to the licensed Workspace and add the authenticated HTTPS backend through its documented custom-backend flow; this has not been configured or tested. Backend secrets must never be embedded in a public HTML page or URL.
