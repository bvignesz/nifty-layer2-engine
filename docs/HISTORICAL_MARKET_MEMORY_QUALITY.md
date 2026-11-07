# Market Memory + second-stage Trade Quality — operator guide

This is a **research-only**, conservative module. It does not place trades,
promote the original nine-check result to a buy/sell order, or claim a trained
AI model exists. The only reliable basis for similar-case evidence is a
verified archive with timestamps and outcomes that were already observable at
the requested decision time.

## Architecture

- `nifty_l2/market_memory.py`: separate append-only SQLite archive of past
  validated, net-after-cost setup cases.
- `nifty_l2/quality_filter.py`: causal nearest-neighbor retrieval + Wilson
  descriptive uncertainty interval; every output stays manual review.
- `nifty_l2/market_memory_cli.py`: import, search and status workflow.
- `nifty_l2/desk_readmodel.py` and `desk_pages.py`: dashboard evidence
  availability (case counts, sessions, trained model state).
- `nifty_l2/xgboost_shadow.py`: existing training experiment, separately
  requires 1,000+ complete labeled rows and 45+ independent sessions.

## Data inputs and provenance

One case is a JSON object with:

```json
{
  "case_id": "your-unique-replay-event-id",
  "observed_at_utc": "2026-10-29T04:45:00+00:00",
  "feature_observed_at_utc": "2026-10-29T04:44:00+00:00",
  "outcome_available_at_utc": "2026-10-29T05:00:00+00:00",
  "session_date": "2026-10-29",
  "strategy": "NIFTY_L2_WALL_BREAK",
  "symbol": "NSE:NIFTY50-INDEX",
  "regime": "TREND_UP",
  "label_after_costs": 1,
  "net_pnl_inr": 250.0,
  "source": "VERIFIED_HISTORICAL_REPLAY",
  "evidence_sha256": "REPLACE_WITH_64_CHARACTER_SHA256_HEX_OF_SOURCE_DATA",
  "features": {
    "wall_cut_ce_pct": 1.5,
    "wall_cut_pe_pct": 0.2,
    "oi_speed_ce": 2.0,
    "oi_speed_pe": 0.8,
    "futures_price_delta": 20.0,
    "futures_oi_delta": 1000.0,
    "vix_change_pct": 1.2,
    "spot_vs_pdva": 12.0,
    "spot_vs_opening_range": 5.0,
    "volume_strength": 1.3
  }
}
```

**Illustrative schema only — these numbers are not actual research events.**
The archive validates syntax, chronology, complete finite features, positive
P&L/label consistency and evidence hashes, but the importer cannot itself
authenticate that FYERS or NSE produced the raw dataset. Independently audit
the source reports. A claimed source tag is not proof of data entitlement,
real options bid/ask, or actual fills. Do not create fake verified labels.

## AWS isolated use

```bash
cd ~/nifty-platform-validation
git fetch origin
git switch --detach origin/feat/trading-platform-vnext-phase1
PY=/home/ubuntu/nifty-layer2-engine/.venv/bin/python
$PY -m pytest -q
mkdir -p -m 700 ~/.config/nifty-layer2/market-memory

# Import only audited mature historical research cases, from a private file.
$PY -m nifty_l2.market_memory_cli import \
  --db ~/.config/nifty-layer2/market-memory/market_memory.db \
  --cases /path/to/verified_market_cases.json

# Inspect sample and session counts; private read-only access.
$PY -m nifty_l2.market_memory_cli status \
  --db ~/.config/nifty-layer2/market-memory/market_memory.db

# Query at a specific event time with all named features and strategy.
$PY -m nifty_l2.market_memory_cli search \
  --db ~/.config/nifty-layer2/market-memory/market_memory.db \
  --query-json /path/to/current_verified_feature_query.json \
  --report ~/.config/nifty-layer2/market-memory/quality_result_01.json
```

Query JSON requires `observed_at_utc`, `features`, `strategy`,
optionally `regime` and `original_bias`. Use a unique report file path.

## What the screen shows

The integrated /desk and /api/v1/desk display *historical case count*,
*independent session count* and whether a separate calibrated/validated ML
model exists. Without enough mature cases, research quality is
`BLOCKED_NO_EVIDENCE` and the watch stays unverified. With 30+ nearest
historical cases from at least 10 sessions, the tool returns historical
outcome frequency and mean historical P&L, clearly marked descriptive.
It never returns a calibrated predictive probability or actionable BUY/SELL.

## Next-stage science

Before model release: ensure point-in-time market data (including expiry and
strike), unbiased case selection, no overlap across validation folds,
walk-forward and CPCV evaluation, realistic historical spread/slippage,
segmented cost and regime attribution, and ongoing drift alarms. Even a
statistically positive research score does not guarantee individual profits.
