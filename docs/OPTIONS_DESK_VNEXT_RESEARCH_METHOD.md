# OPTIONS DESK vNext — research-first decision method (2026-11-06)

**Owner goal:** NIFTY CE BUY / PE BUY / IGNORE research recommendation, manually traded, displayed in the user's video-reference one-row-per-observation terminal. **Do not change the frozen nine-check legacy engine.** This document sets hypotheses and gates only; none of the proposed filters is an empirically established profitable strategy.

## Research rationale and evidence

- SEBI's August 2026 FY25–FY26 profitability study reports 87.7% loss incidence and Rs 91,685 crore net losses for individual equity-derivatives participants. Study: https://www.sebi.gov.in/reports-and-statistics/research/aug-2026/study-profitability-of-individual-traders-in-the-equity-derivatives-segment-fy25-fy26-_103835.html . Trade costs and expiry concentration materially matter.
- NSE option-sale STT is **0.15% of premium** from 1 Apr 2026: https://www.nseindia.in/static/products-services/equity-derivatives-securities-transaction-tax . Settlement/exercise levies differ: use scenario-specific tax accounting.
- Baltussen, Da, Lammers and Martens, *Hedging demand and market intraday momentum* (JFE, 2021), show hedging-related intraday predictability across futures; not a proof of NIFTY dealer positioning or CE/PE wall efficacy: https://www.sciencedirect.com/science/article/pii/S0304405X21001598
- FYERS official docs (Oct 2026): expired F&O API can request 1-minute contract OHLCV, OI and option Greeks, with history and plan restrictions: https://fyers.in/api-docs/v3/api/market-data/expired-fo-data/get-expired-fo-data/ . Live price/depth comes via FYERS WebSocket, not direct exchange-time updates of option-chain OI: https://fyers.in/api-docs/v3/api/websockets/data-socket/overview
- Public OI cannot identify trade aggressor, trader identity or market-maker net inventory. Call-positive/put-negative GEX, zero-gamma flip and Vanna/Charm are **scenario models**, not observed hedging demand. No guaranteed directional inference from isolated PE/CE OI changes.

## Three layers, one dashboard

### Layer 1: opening and market-regime context (not automatic directional veto)
Inputs: overnight gap; PDVAH, PDVAL, PDPOC calculated from reproducible traded-volume profile (or explicitly labeled TPO method); opening range high/low (09:15–09:30); NIFTY futures vs session VWAP; previous-day high/low; India VIX level/change vs its own recent baseline; significant scheduled economic and earnings events; prior-session futures OI; external markets as context only. FII/DII aggregate flows are often lagged; retain publication timestamp and never treat daily values as intraday flows.

Four **testable** regimes:
1. TREND_EXPANSION: completed underlying closes beyond opening/previous-value range; futures price and OI expansion; low choppiness.
2. RANGE_MEAN_REVERSION: price repeatedly rejects VAH/VAL, reverts toward POC, limited range expansion; avoid directional breakout chase.
3. EVENT_HIGH_VOL: scheduled event or abrupt IV/realized-vol jump; require wider risk, reduced size or no trade (policy determined by backtest).
4. DATA_UNVERIFIED: gaps, stale quote, missing time/contract provenance -> IGNORE regardless of other positive hypotheses.

Do not assume a VIX interval such as 11–15.5 is universally optimal. Test VIX *percentile*, VIX change and IV/RV spread by market regime.

### Layer 2: raw observations and microstructure confluence
Retain all existing nine checks and labels as legacy research for A/B evaluation. Proposed versioned features (NOT replacements until independently approved):

- CE/PE maximum OI **within exactly declared ATM±N strike universe**, with expiry ID, missing legs, coverage percent. Wall rank/migration must compare same expiry and same strike set.
- `wall_cut_ratio = (OI_previous - OI_current) / OI_previous` at the identical symbol; compare 2- or 3-frame persistence only when observation brackets are comparable. Always report OI quantity convention.
- `oi_speed = abs(ΔOI)/elapsed_seconds`; normalized against time-of-day median for matching strike moneyness/expiry, not a universal constant. OI changes from successive chain receipts are not independently exchange-timed.
- `volume_interval = max(0,cumulative_volume_t - cumulative_volume_prev)` only if contract identity and cumulative counter semantics are continuous. Track `ΔOI / volume_interval` as churn proxy; no buyer/seller identity inference.
- **Futures quadrant**, only from two completed and timestamp-validated futures observations: rising price+OI (long buildup proxy), falling price+OI (short buildup proxy), rising price/falling OI (short covering proxy), falling price/falling OI (long liquidation proxy). A quadrant is an aggregate *proxy*, not an exact trade initiator.
- **Strike break / structural acceptance:** two completed 1- or 3-minute index/futures bars on one side of a specified wall plus pre-declared buffer/ATR and bid-ask liquidity; test once-and-retest vs two-bar hold as competing hypotheses.
- **Options scenario GEX:** exact lot-size / raw OI units, broker gamma consistency, finite Greeks, limited-chain coverage and *explicit dealer-sign scenario*. Expose unverified status; no automatic directional gating until falsifiable experiment supports it.
- **Market-depth absorption (EXPERIMENTAL):** FYERS five-level depth or TBT if available and affordable; snapshot imbalance can be spoofed and is not volume delta. Retain update sequence and latency; do not infer informed flow from a single depth snapshot.

### Layer 3: direction, option selection, risk, and time-to-exit

Separate into three independent assessments:
A. **Underlying direction**: bullish / bearish / sideways / unverified, with named supporting and contradicting facts.
B. **Option purchase economics**: forecast price move over a declared horizon vs option breakeven, spread, IV/RV, projected theta, skew, expiry DTE, realized liquidity, forecast move uncertainty.
C. **Trade permission**: candidate (research only) if A and B pass, freshness passes, risk budget passes; otherwise IGNORE.

Do **not** emit 'BUY CE' solely from PE OI dominance or positive GEX. Both PE/CE OI are inventory totals, not market maker positions.

#### Versioned test candidates (NOT profit-backed thresholds)
- Initial eligible contracts: ATM or one strike ITM, prefer reasonable delta (e.g. 0.40–0.65 absolute) and liquid bid/ask. Test against OTM alternatives.
- Initial ordinary-session research excludes same-day expiry until adequate expiry-day options backtest establishes viability. Compare 1–3 days vs 4–7 days DTE on actual historical contract data.
- Liquidity reject if spread above 1% of mid premium **or** above a verified instrument-specific tick/slippage guard; threshold is exploratory and must be stress-tested.
- Buy only after a completed underlying-price confirmation and execution-quote validity; order candidate is priced at realistic ask, exit at realistic bid.
- Stop is structural spot/futures invalidation **and** max option-premium risk (explicit time-and-price exits); premium may gap beyond planned stop. Never imply capped realized loss from an unenforceable stop.
- An option is rejected when implied-volatility compression or time decay makes the required move unrealistic within the holding horizon; compute actual delta/gamma/theta scenarios and worst-case confidence intervals, not a deterministic payoff estimate.
- Basic initial simulation risk policy: at most **0.25% of paper equity at risk per option idea**, maximum **0.75% planned new risk per day**, 2 trades/day, stop after 3 consecutive losses. These are conservative **starting hypotheses**, not prescribed sizing for the real account. Simulate slippage/gaps and only authorize real money after independent review.

#### Prototype recommendation readout
```text
13:39 IST | NIFTY FUTURE COMPLETED 3M  [exchange timestamp]
Layer 1: TREND_EXPANSION · PDVAH reclaimed · opening-range breakout
Layer 2: PE wall 24,450  [captured strike-universe coverage 7/7]
          CE wall 24,500  [same-expiry]  / CE OI cut 1.6% over 3 comparable snapshots
          PE OI build +... [OI INCREASE PROXY; not proven put-writing]
          Futures: ↑price ↑OI long-buildup proxy [bars validated]
          GEX: SIGNED-OI SCENARIO; dealer inventory unknown
Direction hypothesis: BULLISH [support 3, contradict 1]
Option economics: DTE 3; |Δ| 0.52; quoted spread 0.7%; IV percentile 62
Candidate: CE WATCH / IGNORE [research gate], never an automatic order
Invalidation: spot < structural level; maximum modeled premium risk Rs X
Confidence: RESEARCH ONLY / coverage, age, scenario caveats
```
All example numbers are placeholders, never historical data.

## Market-data architecture, provenance and missing-data handling

1. FYERS Data WebSocket for price and depth with source timestamps if provided; exchange clock vs transport receipt are independent fields. Persist raw event and schema version, latency, contract symbol and UTC received_at.
2. FYERS Option Chain REST (or licensed alternative) at sustainable cadence, preserving request-start/request-end brackets and expiry. **Do not label this data as 1m exchange-timed OI**.
3. Futures 1m and 3m history completed-bar validator; strict session calendar and contract rollover. Futures proxy `oi_flag=1` should be validated against contract-level source.
4. Expired F&O 1m OHLCV + OI + Greeks history probe; use `columns` names, track null Greeks and current plan entitlements, no invented Greek values. Reconstruct actual historical option premiums for evaluation.
5. SQLite ingestion `raw_events` -> immutable `validated_observations` -> `features_v2` -> `research_signals_v2` -> `forward_labels`. Migrations only on a DB **copy**; no overwrite of current production tables.
6. Dashboard: display exact feature provenance with REPORTED, DERIVED, SCENARIO, UNAVAILABLE statuses. Keep the video-style wide table as primary, with cards optional, not a substitute.
7. Inference latency, current-data age, missing strikes and stale futures -> fail-closed for actionable outcomes. Historical replay uses only values actually known by the simulated decision timestamp.

## Evaluation and falsification — required before model promotion

Hold signal definitions frozen during a prospective recording period. Collect multiple market regimes including expiry and non-expiry sessions.

- Primary metrics: *net* option premium trade expectancy in R (including brokerage, bid/ask, slippage, statutory levies, exercise tax, invalidation gaps), realized maximum drawdown, profit factor, median MAE/MFE, confidence interval by trading day, and trade count.
- Secondary: direction precision, alert precision/recall, average latency, missed/truncated option OI snapshots, trade frequency, selective coverage and time spent IGNORE.
- Ablation: baseline price/futures-only -> +OI wall -> +OI persistence/volume -> +GEX scenario -> +regime/VIX -> +option selection. Keep feature only when **net out-of-sample** improvement is robust in multiple regimes; avoid cherry-picking.
- Splits: chronological walk-forward with purging/embargo over overlapping horizons, never randomly mix overlapping minutes. Evaluate holdout days, full market weeks and expiry windows.
- PBO/deflated Sharpe / bootstrap by *session* for uncertainty. No XGBoost live recommendations until 1m provenance, label coverage and meaningful sample sizes have been demonstrated.
- Simulate broker rate limits and data gaps; compare to no-trade baseline and basic ORB/VWAP strategies. A visually striking video or few winning days is not strategy validation.
- Reject rule if improvement disappears under doubled slippage, changed lot, realistic latency or a reasonable parameter perturbation.

## Prioritized backlog

P0. **One completed-bar data lineage audit**: expired-options one-minute candle+OI+Greeks data entitlements; exact symbol, schema, cutoff, contract month, lot and historical price match; immutable sample; no production changes.
P1. **Executable futures/spot + price/volume-only baseline**, logged outcome labels, costs and latency, with GEX/OI inactive in decisions.
P2. **OI wall/volume experiments** across comparable receipts and 1m expired contract history where semantics fit; forbid fabricated 'writing/exit'.
P3. **Options contract selector and option P&L simulator** including spreads and IV/theta decay.
P4. **Regime/market-profile overlay**, test trend/range/event separately.
P5. **GEX and Vanna scenario sensitivity** and unit verification; keep as research even if useful.
P6. **XGBoost shadow ranking** on pre-registered validated features; calibrated forecast probabilities and rejection option; no auto-execution.

## External tools to consider
FYERS v3 DataSocket/REST; NSE official UDiFF and F&O reports; SQLite/DuckDB for research; Python pandas+Polars, NumPy/SciPy; pytest and GitHub Actions; vectorbt/backtesting.py (after prices and fills corrected); Optuna only within leakage-safe train folds; MLflow/Parquet artifacts for experiment tracking; Grafana/Prometheus for collector health. Do NOT treat model/dashboard sophistication as alpha.

### Promotion rule
**Promote no proposed rule to production until** deterministic replay parity, truly timestamped complete bars, independently reviewed cost model, multiple out-of-sample regimes, data-quality alerting and human approval pass. Existing dashboard and legacy checks must remain available unchanged.
