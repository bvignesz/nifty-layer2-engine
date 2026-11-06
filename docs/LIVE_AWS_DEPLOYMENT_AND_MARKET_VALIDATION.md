# AWS staging deployment and market-hour proof (2026-11-06)

**Not a record of an actual EC2 deployment or actual FYERS entitlement test.** This is the fully reproducible operator procedure. No SSH tool or authorized EC2 shell was available to execute it from this GitHub workflow. Live FYERS token, plan, exchange hours and systemd permissions must be verified on the user's machine.

## Official API contract sources

- FYERS expired options API and plan restrictions: https://fyers.in/api-docs/v3/api/market-data/expired-fo-data/get-expired-fo-data/
- FYERS active NIFTY option chain: https://fyers.in/api-docs/v3/api/market-data/option-chain/
- FYERS active futures chain/expiry rollover: https://fyers.in/api-docs/v3/api/market-data/futures-chain/
- Official NSE daily EOD UDiFF / surveillance reports: https://www.nseindia.com/all-reports
- Nifty Indices NIFTY 500 *current* constituents (not point-in-time archive): https://www.niftyindices.com/indices/equity/broad-based-indices/NIFTY-500

## A. Isolated development code and offline tests

```bash
cd /home/ubuntu/nifty-platform-validation
git fetch origin
git switch --detach origin/feat/trading-platform-vnext-phase1
PY=/home/ubuntu/nifty-layer2-engine/.venv/bin/python
$PY -m pytest -q
```

Keep existing `nifty-collector.service`, `nifty-web.service`, production DB and credentials unchanged.

## B. FYERS live entitlement and exact expired-contract sample

First verify that `~/.config/nifty-layer2/fyers-token.json` belongs to the current AWS owner and mode 0600. FYERS authentication may require browser-based daily interaction with OTP on a separate trusted device. Never paste the token or private key into chat.

```bash
mkdir -p -m 700 ~/.config/nifty-layer2/live-runtime ~/.config/nifty-layer2/live-reports
$PY -m nifty_l2.expired_options_probe --live \
  --symbol NSE:NIFTY25MAR23000CE \
  --from-date 2025-03-26 --to-date 2025-03-27 \
  --token-path ~/.config/nifty-layer2/fyers-token.json \
  --report ~/.config/nifty-layer2/live-reports/expired-nifty-example-01.json
```

Use **exact actual expired symbols** from FYERS Get Expired Contracts or verify the documented example belongs to your plan. This is an **example**, not successful access evidence. The Standard plan's historical 1m API daily request quota may restrict bulk download; don't loop blindly. Inspect only the redacted status and count. Current program rejects incomplete/mismatched Greeks and clocks and will not silently fill missing data.

## C. One read-only market feed sample

```bash
$PY -m nifty_l2.live_feed --live --once --auto-expiry --auto-future \
  --db ~/.config/nifty-layer2/live-runtime/market_feed.db \
  --token-path ~/.config/nifty-layer2/fyers-token.json
```

This makes up to four **read-only** FYERS REST calls: current option expiry, current futures contract, selected option chain and one-minute futures history. Outside the regular NSE session it makes no API calls and prints an outside-session state, not synthetic data.

## D. Preview new UI independently

```bash
$PY -m nifty_l2.desk_preview \
  --db ~/.config/nifty-layer2/web-runtime/research.db --port 8787
```

The normal authenticated `nifty_l2.web` route `/desk` includes `market_feed.db` only if it is in the **same runtime directory** as `research.db`. The isolated preview currently uses the existing research DB parent and **does not automatically ingest the separate live-runtime path**. To show the new feed, configure an explicit and reviewed read-only path bridge or move both into an isolated copied runtime **before** production switch. Never overwrite the real production research DB.

## E. Optional continuously running development-only service

Template: `deployment/nifty-research-feed.service.example`. It uses 180-second cadence and actual broker front expiries/futures, keeps output in a dedicated `live-runtime/market_feed.db` with Unix permissions, and never places orders.

**Do not enable it until one sample and API request limits have passed.** Review template paths and operating user, then create a new service name rather than overwriting `nifty-collector.service`:

```bash
sudo install -m 0644 deployment/nifty-research-feed.service.example \
  /etc/systemd/system/nifty-research-feed.service
sudo systemctl daemon-reload
sudo systemctl start nifty-research-feed.service
sudo systemctl status nifty-research-feed.service --no-pager
sudo journalctl -u nifty-research-feed.service -n 50 --no-pager
```

To stop/rollback independently:

```bash
sudo systemctl stop nifty-research-feed.service
sudo systemctl disable nifty-research-feed.service
```

For unattended boot starts, enabling is a separate explicit operator decision. The FYERS authorization token still expires; no unsafe unattended OTP bypass is implemented. Beware concurrent FYERS read budgets if legacy collector is also running.

## F. Real market-hour acceptance test

After a complete open trading session:

```bash
$PY -m nifty_l2.market_day_validation \
  --db ~/.config/nifty-layer2/live-runtime/market_feed.db \
  --date YYYY-MM-DD
```

Minimum evidence:
- At least 80 receipts and 200 completed futures one-minute bars.
- No more than five receipt gaps greater than six minutes and no missing stored option legs.
- Matching exact symbols and expiries, no negative futures OI, receipt times distinct from candle exchange closes.
- FYERS token/entitlement and rate-limit errors recorded and independently reviewed.
- One successful browser preview with 200 OK, no public unauthenticated listener, no unexpected production DB changes.
- Cost-aware historical replay and real manual journal reconciled separately.
- XGBoost gate should remain blocked until 1,000+ true labeled, varied-regime rows over 45+ sessions; 1,000 rows is a minimum technical floor, not proof of statistical sufficiency.

A collector reaching `RESEARCH_FEED_RECOVERED` **does not** mean options OI has verified per-minute exchange timing or that trading signals are profitable. It is a data collection reliability milestone.

## G. Swing historical point-in-time data

Download and preserve genuine dated NIFTY 500 constituent snapshots from NSE Indices with documented **publication/effective date**. Import each dated CSV with `eod_scanner.nse_universe_history.import_snapshot` into a separate `universe_history.db`. For 2010–present backtests, current constituent membership MUST NOT be retroactively used as historic membership. Match NSE UDiFF daily OHLCV and corporate action adjustments to the FYERS equity EOD adapter.

## Release policy

Live signals are always research-only; execution manual. This branch is an unmerged draft PR #13 based on an unmerged draft PR #6. Do not deploy to production, switch main, restart the legacy services, or change auth/firewall unless the owner separately approves that specific operational action.
