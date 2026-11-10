# NIFTY integrated desk: AWS isolated preview and manual operator runbook

Branch: `feat/trading-platform-vnext-phase1`. Safe to test on a **separate** AWS development worktree; DO NOT switch production services, migrate the production SQLite schema or store OAuth tokens in GitHub.

## Current program boundaries
- `nifty_l2/desk_preview.py` only serves the existing stored research data via a loopback-bound HTTP port with no orders, auth workflow, FYERS calls or write endpoints. It reads `research.db` using `mode=ro`.
- `/desk` displays video-style per-receipt CE/PE walls, OI change, futures read and BULLISH WATCH / BEARISH WATCH research labels plus counts and journal results; it **does not** produce independently verified 1m option-chain data.
- `/api/v1/desk` is read-only JSON. The existing full `nifty_l2.web` also exposes these routes behind its Basic Auth.
- `nifty_l2/trade_journal.py` writes to **separate** `trade_journal.db` only when the operator explicitly records verified manual fills. No broker order events are inferred.
- `nifty_l2/telegram_delivery.py` is an opt-in, one-shot message tool, not an autonomous trader. Default mode is dry-run; `--send` requires env credentials. It deduplicates research alerts and refuses stale or mismatched receipt data.

## Preview without changing live service
On AWS Ubuntu, use the already configured isolated development worktree. SSH from your own machine with your private key (never paste key into chat).

```bash
cd ~/nifty-platform-validation
git fetch origin
git switch --detach origin/feat/trading-platform-vnext-phase1
PY=/home/ubuntu/nifty-layer2-engine/.venv/bin/python
$PY -m pytest -q
$PY -m nifty_l2.desk_preview \
  --db /home/ubuntu/.config/nifty-layer2/web-runtime/research.db \
  --port 8787
```

The last command serves **only localhost** on port 8787. From your own PC/terminal, open a second SSH connection with local forwarding (never permit public ingress to 8787):

```bash
ssh -i YOUR_AWS_KEY.pem -L 8787:127.0.0.1:8787 ubuntu@13.211.127.67
```

Open `http://127.0.0.1:8787/desk` in the local browser. Opening this from the server without SSH forwarding or from a separate Android device will not work. A security-group rule for TCP 22 restricted to your IP is still required. The URL `13.211.127.67` can change unless associated with an Elastic IP.

## Data-provenance audit (run *only* with valid FYERS credentials)
The separate expired-option probe requires the exact instrument found via FYERS expired-contract discovery, permitted history dates and account access. Do not use a fabricated contract, assume historical bid/ask or promote backtest performance without costs.

```bash
$PY -m nifty_l2.expired_options_probe --live \
  --symbol 'NSE:EXACT_EXPIRED_NIFTY_CONTRACT_CE' \
  --from-date YYYY-MM-DD --to-date YYYY-MM-DD \
  --token-path /home/ubuntu/.config/nifty-layer2/fyers-token.json \
  --report ~/nifty-validation-reports/unique-expired-fo-report.json
```

Replace the placeholder with a verified *real* expired contract and dates, and use a new report filename. Do not reuse a report path; reports are create-only mode 0600.

## Telegram one-shot optional use
First configure `NIFTY_TELEGRAM_BOT_TOKEN` and `NIFTY_TELEGRAM_CHAT_ID` in the **shell environment** on AWS, not in the repository or chat, and use an isolated private marker directory.

```bash
$PY -m nifty_l2.telegram_delivery \
  --db ~/.config/nifty-layer2/web-runtime/research.db \
  --marker-dir ~/.config/nifty-layer2/telegram-delivery
```

This is **dry-run**; add `--send` explicitly to send one fresh, comparable, current-session BULL/BEAR research alert. Delivery does not prove profitable signal quality; the Telegram API may fail or duplicate during ambiguous network outcomes.

## Journal
The journal is independent of the broker. Use the `calculate_trade`, `record_trade` APIs with explicit manually recorded entry/exit price, quantity, fees, planned risk and timestamps. Only `trade_journal.db` may be written. No fabricated fills; reconcile data with your actual broker contract note.

## Still required before live release
1. Verified FYERS option history response and account permissions; one-minute chain update timestamps remain unverified.
2. Collector integration for 1m futures and approved option-chain cadence with rate-limit and expiry handling.
3. Live pre-market news, macro, NSE constituent and true volume-at-price data, plus archived contract fill assumptions.
4. Data-complete feature table and historical/paper outcomes; backtesting, cost attribution and shadow XGBoost performance evaluation.
5. Secure HTTPS private production ingress, identity, rollback, snapshot/backup and market-hours end-to-end validation.
6. Only after all of those: staged live dashboard deployment and optional alerts. Trading remains manual.
