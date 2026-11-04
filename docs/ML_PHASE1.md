# XGBoost Phase 1 — dataset export

This phase exports existing research observations for audit. It does NOT train XGBoost or create future-return labels.

## Run on the AWS host

From the project directory:

```bash
.venv/bin/pytest -q tests/test_ml_dataset.py
.venv/bin/python -m nifty_l2.ml_dataset --db /home/ubuntu/.config/nifty-layer2/web-runtime/research.db --out /home/ubuntu/nifty-ml-research-20261104.csv
```

The source SQLite file is opened read-only. The exporter refuses to overwrite an existing output CSV. Each row represents one stored research event, not one completed three-minute candle. The event_kind column distinguishes scheduled from manual observations; separate them before training.

## Data contract

- observed_at_utc is receipt/observation time, NOT necessarily an exchange timestamp.
- exchange_at_utc is blank when unverified; never fill it from receipt time.
- Missing numeric fields are blank, not zero.
- Original verdict and check counts are unvalidated research values.
- Seller lead and model GEX are scenario/proxy values, not observed dealer trades.
- label_status is NOT_AVAILABLE for every row; do not train a supervised model with this file.
- An export can be empty if no events were collected.

## Next steps

1. Verify FYERS exchange timestamps and contract identity using real redacted payloads.
2. Record spot observations with exchange timestamps and exact 9/15/30-minute future matches within the same session.
3. Exclude stale/partial observations and duplicates, and split by trading session with purging.
4. Train XGBoost against baseline predictors only when independently validated labels exist.
5. Keep the live trading decision at No Trade until walk-forward results and cost-aware option execution checks pass.

Do not upload private raw FYERS tokens, app secrets or OAuth callback URLs.
