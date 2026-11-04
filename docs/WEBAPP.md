# NIFTY application

The application includes browser access without a dashboard login, private FYERS app settings, OAuth connection, a NIFTY quote check, script start/stop controls, all nine check results, and full script output. The script executes in a separate worker process with a 150-second timeout; overlapping runs are rejected. Runs can be started manually or by the market-session collector described below.

## Market-hours automation — deployed 4 November 2026

FYERS account profile verification succeeded live on 4 November 2026. The existing completed run at 12:35:24 UTC (18:05:24 IST, after market close) has one persisted signal and all eighteen directional check records. This confirms execution and storage, not data freshness or strategy validity.

`nifty-collector.service` is installed, active, enabled at boot and independent of the web browser. It samples at session open for warmup and every three minutes thereafter, anchored to the opening time, during the configured F&O session. Normal sessions are 09:15–15:40 IST. The final regular sample is 15:39. The service checks every five seconds and permits a maximum 20-second launch delay; later slots are recorded as MISSED rather than replayed with current prices. Worker timeout is 150 seconds. Manual and scheduled workers share an OS lock; a busy slot is recorded as SKIPPED. A unique database constraint prevents duplicate scheduled windows across restarts. Unexpectedly terminated workers become INTERRUPTED.

The dated calendar covers **4 November–31 December 2026**, excludes weekends and the remaining published holidays (10 November, 24 November, 25 December), and includes the 8 November Muhurat F&O session from 14:20–15:40 IST. Unknown dates pause collection until the calendar is updated. Sources: [NSE hours](https://www.nseindia.com/static/market-data/market-timings), [2026 F&O holidays](https://nsearchives.nseindia.com/content/circulars/FAOP71777.pdf), [Muhurat schedule](https://nsearchives.nseindia.com/content/circulars/FAOP76940.pdf). New exchange closure notices require calendar updates. The spot/equity underlying can close earlier than F&O; no claim of fresh spot data is made for the final F&O minutes.

The dashboard shows collector heartbeat, next run in IST, saved-result count, recent execution logs and pause/resume controls. Pause prevents future automatic runs; Stop run cancels the active worker, including one owned by the collector. Closing the website does not stop collection. Authentication is verified before each run; an expired FYERS token records a failure and requires Connect FYERS again. There is no automatic account-password or OTP login.

All records are stored in `/home/ubuntu/.config/nifty-layer2/web-runtime/research.db`:

- `run_log`: scheduled boundaries, actual start/finish time, manual/scheduled source, completion/failure/stop/interruption/missed status and associated result ID. Runs predating this feature remain in the existing event tables.
- `events`: raw market API responses and requests, engine version hash and configuration. API authorization headers and account credentials are excluded.
- `signals`, `check_results`: original full output and all nine bull/bear checks, committed atomically with a successful run log.
- `header_snapshots`, `strike_snapshots`: original engine analytical history.

The latest result and status JSON files support the web UI; SQLite retains the history. A verified SQLite backup was taken before deployment. There is no automatic deletion or daily backup timer. Startup after downtime records missed boundaries for the current session; earlier entire missed days are not backfilled.

This is **automated research sampling**, not a validated three-minute signal pipeline. Samples record actual observation time separately from the scheduled boundary. Existing engine freshness, instrument identity, futures fallback, gap handling and timing limitations still apply; classification remains `No Trade`, and there is no order placement. Raw tick-by-tick collection, historical catch-up and ML are not implemented.

Validation: 51 automated tests pass, including calendar boundaries, special sessions, holidays, duplicate prevention, restart recovery, overlap skipping, log atomicity, failure logging and cross-process stop requests. Live service activation, boot enablement, after-hours WAITING state, 5 November 09:15 IST next run, database integrity and the public dashboard were verified. The first live automatic in-session run is still pending the next opening.

## Current installation

**Public URL: https://13.211.127.67/**

`nifty-web.service` and `nifty-proxy.service` are installed, enabled and running on the verified VPS with public IP `13.211.127.67`. Public HTTPS has a trusted Let's Encrypt IP certificate; normal TLS verification passed. An unauthenticated public request returned HTTP 200 after dashboard login was disabled on 2026-11-04.

Caddy 2.11.7 handles HTTPS on port 443, proxies to the Python app at `127.0.0.1:8080`, and manages automatic certificate renewal. It uses the shortlived ACME profile with TLS-ALPN validation on port 443. Port 80 is blocked upstream and is not required by this configuration. Nginx was installed during setup but is disabled; it does not serve this application. No dashboard credentials or tokens are written to HTTP access logs.

Dashboard login is disabled (`NIFTY_WEB_REQUIRE_LOGIN=0` in the private `web.env` file). The deployed dashboard password has been removed. Anyone with the URL can access dashboard settings and controls. FYERS account login and OTP remain required by FYERS. To restore dashboard authentication, set `NIFTY_WEB_REQUIRE_LOGIN=1`, configure a `NIFTY_WEB_PASSWORD` of at least 16 characters and restart `nifty-web`.

## Optional private tunnel access

Forward the server port from your own desktop terminal, replacing `YOUR_VPS` with the real public IP/hostname:

```bash
ssh -L 8080:127.0.0.1:8080 ubuntu@YOUR_VPS
```

The deployed application uses its public HTTPS origin. To switch to private local mode, change `NIFTY_WEB_ORIGIN` to `http://127.0.0.1:8080` and restart the app first; then open `http://127.0.0.1:8080` on that desktop and sign in. Re-register the displayed FYERS callback for that mode. On Android, use an SSH client that supports local port forwarding, with the same local/remote port mapping, then open the loopback URL on the phone. The SSH connection carries the otherwise local HTTP traffic securely.

1. Expand **FYERS app settings**. Register the exact redirect displayed by the app in the FYERS app dashboard. In private local mode it is `https://trade.fyers.in/api-login/redirect-uri/index.html`.
2. Use fresh, rotated credentials for a data-only FYERS app. Enter its complete App ID and App Secret in the dashboard; these are saved on the server with mode 0600. Saving new settings disconnects the previous account. See [FYERS_CONNECT.md](FYERS_CONNECT.md) for the credential-rotation context.
3. Select **Connect FYERS**. Login opens in a new browser tab. Complete account login, OTP and consent on FYERS. Copy the entire final redirected address, return to the dashboard, paste it into **Full FYERS redirect URL**, and select **Complete connection**.
4. Select **Verify & fetch quote** to test authentication and NIFTY market-data access.
5. Select **Run script once**. The page refreshes while the worker runs. A completed result shows the original nine-check scorecard, market summary and expandable full script output. Use **Stop run** to cancel a running worker.

Never paste account passwords, OTPs, app secrets or tokens into chat.

## Alternative domain / Nginx deployment

The current deployment already uses Caddy at the public IP. The following is an alternative setup for a future domain, not an additional proxy to run alongside the installed service.

Supply the actual public domain/VPS identity before configuring external routing. The private hostname/IP of this workspace alone does not identify a reachable public endpoint.

1. Point the chosen domain at the VPS and obtain a valid TLS certificate. `deploy/nginx.conf.example` provides a loopback proxy template; replace its domain and certificate paths, install Nginx, validate with `sudo nginx -t`, and enable/reload Nginx. Keep callback query strings out of proxy logs. Permit the HTTPS port in the real VPS firewall/security group.
2. Change `NIFTY_WEB_ORIGIN` in the private `web.env` file to `https://YOUR_DOMAIN`, preserving the generated password. Restart with `sudo systemctl restart nifty-web`.
3. Register `https://YOUR_DOMAIN/oauth/callback` as the exact FYERS redirect. Open the HTTPS dashboard and reconnect. On HTTPS, login automatically returns to the application; pasting a callback is unnecessary.

The application remains single-owner, bound to loopback behind the HTTPS proxy. No public order endpoints exist. Reverse proxies must preserve the browser's Origin header.

## Runtime architecture and data

- `nifty_l2/web.py`: authenticated web UI, CSRF checks, browser-bound OAuth state, settings and process controls.
- `nifty_l2/fyers.py`: shared REST transport, strict callback validation and atomic private storage.
- `nifty_l2/runner.py`: isolated worker and an allowlisted read-only FYERS client (quotes, history, option chain).
- `nifty_l2/legacy_engine.py`: preserved original analytical functions. No notebook execution, arbitrary script upload, notebook package installation, Telegram sender or old tunnel startup.
- `scripts/install_web.py`: one-time local service installer; refuses to overwrite an existing private environment file.

Private runtime directory: `/home/ubuntu/.config/nifty-layer2/web-runtime/`. `research.db` holds live research event payloads, raw market responses, signal payloads and all eighteen directional check results. This is separate from the migration/replay database to avoid mixing synthetic/replayed histories into live research warmup. `result.json` is the last successful run; `status.json` is the current worker status. A failed run leaves the previous result visibly labelled with its original timestamp. Incomplete transactions roll back.

OAuth state is random, bound to an HttpOnly browser cookie, valid for ten minutes and consumed once. Profile verification succeeds before the access token replaces any existing token. Restarting the app cancels pending logins. App settings and tokens are never embedded in returned HTML, access logs, command arguments or worker output. Tokens are shared with the terminal login helper and must be renewed after FYERS expiry.

## Verification and limits

All **51 automated tests pass**, including local HTTP authentication/CSRF checks, OAuth callback success/failure, replay/expiry/browser binding, private settings, HTML escaping, isolated worker failure, overlap prevention and a complete nine-check engine execution with recorded FYERS responses. The installed service passed an actual authenticated HTTP smoke check. Public HTTPS and the authenticated public dashboard are now verified. FYERS profile authentication and one actual engine execution have been verified. Individual market-data field freshness and strategy validity remain unverified.

The original engine has known timing, missing-data, futures-resolution and reference-data limitations documented in [AUDIT.md](AUDIT.md). The UI labels its output as unvalidated research. Persisted validated classification is always **No Trade**, even if the original script's research verdict differs. Repeated manual runs do not establish valid three-minute observations. Automated exchange-calendar collection, strategy validation, ML training and order placement are not implemented.

Official protocol references: [authorization](https://fyers.in/api-docs/v3/api/authentication/individual-app/generate-auth-code/), [token exchange](https://fyers.in/api-docs/v3/api/authentication/individual-app/validate-auth-code/), [option chain](https://fyers.in/api-docs/v3/api/market-data/option-chain/) and [history](https://fyers.in/api-docs/v3/api/market-data/historical-data/).
