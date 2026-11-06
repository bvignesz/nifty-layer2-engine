# Indian Trading Research System — Methodology v2.0 (2026-11-06)

Status: **DESIGN / BACKTEST HYPOTHESES; not validated strategy.**
Owner-approved design direction: two separate research tracks (NIFTY options microstructure and NSE equity swing trading) with shared provenance, data quality, replay, risk controls, trade journal and analytics. This document does not modify production signals, frozen nine-check logic, EOD v0.7.0, FYERS credentials, or deployed AWS services.

## 0. Investment and trader-survival premise

A successful system must demonstrate **positive out-of-sample net expectancy after spread, fees, taxes, impact and missed fills**, plus manageable drawdown. Win rate alone is not evidence.

SEBI's *Profitability of Individual Traders in Equity Derivatives, FY25–FY26* (Aug 20, 2026) found 87.7% of individual equity-derivatives traders lost money in FY26; aggregate net losses were ₹91,685 crore. This is evidence of severe base-rate risk; it is NOT evidence this system must fail or succeed. https://www.sebi.gov.in/reports-and-statistics/research/aug-2026/study-profitability-of-individual-traders-in-the-equity-derivatives-segment-fy25-fy26-_103835.html

Operate **research/log-only**, then prospective shadow, then limited manual execution only after documented review. Never present scenario assumptions as dealer inventory or assured market direction.

## 1. Architecture and separation of concerns

**Layer 0 — Data & provenance**
- All raw FYERS/NSE/reference payloads append-only, timestamp request start/end UTC, response, symbol, expiry, instrument identity, exact option strike and contract lot, source schema/version, response latency, independent exchange timestamp if present, original raw-OI convention, price adjustment basis. Refuse invalid dates, stale responses and contradictory duplicate observations.
- Separate distinct *price candle exchange time* (bar-start, verified bar-close) from *option-chain receipt time*. A 3m chain poll is **not** a 1m option-chain candle.
- Price/volume/OI data freshness per instrument, not one global flag. No silently forward-filled quote/flow. No invented historical spot or futures values.
- Data access and licensing respected: FYERS Option Chain provides contract OI/Greeks for active contracts; FYERS Expired F&O Data API can provide historical contract OHLCV with optional OI and Greeks subject to entitlement. NSE UDiFF cash bhavcopy/derivatives contract master for independently sourced EOD reference and exact lot/expiry mapping. Different APIs do NOT imply synchronized exchange timestamps.
- Store three independent clocks: `exchange_bar_start_utc` (when genuinely present), `request_start_utc`, `received_utc`; source lineage in every dashboard cell and feature record.

**Layer 1 — Market regime / premarket context**
- Daily prior-session profile PDPOC, PDVAH, PDVAL from *verified input* distribution: if only candles available use VOLUME-BY-PRICE proxy, not genuine TPO/auction profile.
- Opening gap relative to value area; previous day high/low; opening range after completed 5–15m bars; India VIX level/change; NIFTY/BANKNIFTY sector breadth; verified event calendar, RBI/US macro, FII index futures *EOD* positioning with source date. Never treat yesterday's participant-wise position as intraday FII order flow.
- Classify regime `TREND_CANDIDATE | BALANCE_CANDIDATE | HIGH_VOL_RISK | UNAVAILABLE`. This gates hypothesis experiments, not a guarantee of today's price direction.

**Layer 2 — Microstructure research (NIFTY options)**
- Primary video-style dense horizontal terminal: one row per proven **completed 1m futures/spot candle**. Display linked option-chain receipt observations separately, with age and cadence. A 3m ATM strike-flip panel uses only completed 3m market candles and receipt-time option data.
- At each *fixed* selected expiry and captured universe ATM ±N:
  1. CE/PE *observed-subset* max-OI walls, distance from spot in points and ATR units; OI density and concentration, separate CE & PE; migration only on matched, same-expiry windows.
  2. Wall-cut `(oi_t - oi_prev)/oi_prev` at SAME symbol/strike/side/expiry and validated 90–360 s gap; distinguish new wall's rank movement from true contract OI movement.
  3. OI speed `abs(delta_oi) / rolling median(abs(delta_oi) at comparable time-of-day)` with a session/warmup threshold. Zero denominators and resets => UNAVAILABLE.
  4. Volume churn `delta_cumulative_volume / max(abs(delta_oi), eps)`, using **same-symbol, nondecreasing cumulative counters** only; high churn is ambiguous and not proof of writers or buyers.
  5. Futures confirmation from consecutive independently verified completed futures bars: `price Δ, futures OI Δ` quadrant; still a proxy for position flow, not an identified trader class.
  6. Strike break/reclaim: completed underlying close beyond fixed reference wall, buffer in ATR/bid-ask terms; defend vs break in multiple bars; test follow-through and false-break controls.
  7. GEX: show both CE/PE **unsigned magnitude** and alternative **sign scenarios**. Broker gamma model benchmarked to independent Black-76 with contemporaneous forward, IV, rate and verified exercise-time convention. Verify broker OI = contracts vs underlying units from independent NSE contract reference before using lot multiplier. Net dealer GEX/zero gamma NOT claimed to be observed.
  8. Vanna/charm are EXPERIMENTAL theoretical terms only: IV/rate/expiry convention important; do not substitute for observed dealer flow.
  9. Bid/ask spread, market depth if entitled, LTP, traded volume, ATM delta and IV change are execution/context gates, not *tick-aggressor* data unless a licensed feed with market-by-order/trade-direction evidence is present.
- Existing frozen nine checks: **do not rewrite**. Build a parallel `hypothesis_v2` scorer whose features have provenance, missingness and candidate labels. Compare against original on the SAME replay events.

**Layer 3 — Direction, decision and contract selection**
- Output 3 distinct fields, never collapse them:
  * `market_bias`: BULLISH / BEARISH / NEUTRAL / UNAVAILABLE — hypothesis only.
  * `data_confidence`: COMPLETE / DEGRADED / BLOCKED, with reasons and per-field age.
  * `action_state`: RESEARCH_ONLY / SHADOW_CANDIDATE / APPROVED_MANUAL / NO_TRADE.
- A `BUY_CE_CANDIDATE` (research) requires (A) direction: verified futures close above breakout/reclaim level and regime-compatible; (B) coherent matched OI wall defense/cut and/or corresponding futures build *confirmed* with at least two non-overlapping observation windows; (C) execution: option liquidity and spread thresholds, IV/vega risk, positive net projected option RR after costs; no contradictory flow, market event or stale source. PE is symmetric. These are *hypotheses to test*; thresholds to be derived on walk-forward calibration, not tuned on full data.
- For contract selection, compare nearest 2 eligible expiries and candidate strikes by actual premium/spread/depth, delta band (initial research 0.40–0.65, not a rule), theta per expected holding time, Vega/IV shock and actual current lot/contract. Compute `expected_option_pnl` by repricing the option across underlying move, time decay and IV-down/up scenarios; a spot-only R:R is inadequate.
- The video-style `BULL/BEAR ALERT` may remain conspicuous as *legacy research*, but never a verified order instruction while the release gate is BLOCKED.
- Overnight positions not assumed. No auto-order endpoint.

## 2. Test matrix: incremental effect, not more indicators

| Experiment | Baseline | Added feature | Null hypothesis / veto |
|---|---|---|---|
| O1 wall-break | completed futures breakout | matched wall cut | OI cut adds no net expectancy |
| O2 futures | O1 | fresh futures OI quadrant | futures OI label has no incremental predictive value |
| O3 gamma | O2 | verified gamma magnitude & sign scenario | GEX adds no net predictive value; dealer signs unknown |
| O4 opening | O2 | PDVA and opening regime | added context no improvement after multiple-testing correction |
| O5 volatility | O2 | IV change, VIX and optional theta cost | filters do not improve net premium returns |
| O6 trade execution | O2 | min spread/market depth, order delay | modeled gross edge disappears after costs |
| O7 ML | strongest validated simple model | XGBoost shadow ranker | no improvement in independent forward log-loss / net R |

All tests require event-time, source time and outcome time strictly segregated. Freeze parameter candidates *before* final holdout and prospective paper period. Track tests attempted (not only winners).

## 3. Indian equities swing track: independent engine (Nifty 500 universe)

**Academic rationale:** Time-series and cross-sectional momentum have a substantial research literature; the India-specific paper by Sehgal, Pandey and Sen compares relative/absolute/combined momentum. Evidence is general, not a validation of this implementation.

**Universe and eligibility:**
- point-in-time NIFTY 500 constituent membership and tradability, survivorship-safe delisted/history map; daily corporate actions/splits/bonus, earnings and ASM/GSM/ESM flags; avoid accidental backtest on today's survivors;
- median 20-session rupee turnover threshold, minimum traded days, price band and circuit constraints. Existing intended ₹1 crore threshold is an initial operational rule, not a proof of fill capacity.
- Market regime: NIFTY 500 above/below 200DMA, % members above 50DMA, realized vol and market breadth to cap risk rather than forecast every swing.

**Three playbooks; do NOT combine untested indicators into one opaque score:**

S1 Trend pullback (initial hypothesis):
- 6–12m volatility-scaled relative strength vs NIFTY 500, 21-trading-day skip; above SMA200; EMA10 > EMA30; actual lower-vol pullback near EMA10; Larry Williams Accumulation/Distribution *as a separate predeclared filter*, not a fallback 'must confirm everything'.
- Enter next day's OPEN/limit under explicit gap cap and fill logic; stop structure at swing low or ATR alternative selected before test; exit with trailing EMA30/ATR and 20-session time bound; do NOT look ahead to same-day full-bar signals.

S2 Value-area reclaim:
- fixed daily/weekly volume-by-price POC, VAL and VAH from available historical intraday trade volume; document proxy vs actual transaction-level profile; W%R(3) oversold then reclaim; relative strength filter, non-trivial volume; target VAH vs stop below VAL or reclaim pivot.
- Compare against the same reclaim **without** W%R and without Larry A/D to isolate incremental contribution.

S3 BOF / false-break Wyckoff:
- fixed pivot support/resistance 3-left/3-right confirmation only after 3 right-hand bars (no repaint), ATR-sized zones, 60-bar expiry and max three zones/side as already specified; failed breakdown with reclaim, A/D and time-of-day volume confirmation; objective invalidation & stop, benchmark against simple breakout.
- Avoid adding ORB, NR7, CPR, RSI2 and dozens of extra triggers simultaneously; test each hypothesis independently and require a meaningful sample.

**Portfolio policies for experiments:**
- no leverage/MTF in early validation; max four open positions, max two names/sector, <=25% capital/name and total initial stop risk <=4% with 0.25–0.50% of equity risked per individual exploratory trade as a *starting calibration range* (not a fixed personal recommendation);
- 1–2 day earnings blackout or narrower researched rule, exchange ASM/GSM/ESM veto, gap-overshoot kill switch, no buying at upper circuit, explicit borrow/fill availability for shorts;
- daily portfolio heat, sector correlation and common index beta; account for taxes/charges, gap loss beyond stop.

## 4. Common evaluation protocol: prove an edge, then optimize

- Partition by market regime/year and as-of universe; reserve untouched final walk-forward out-of-sample period.
- Use expanding/rolling chronological retrain, purge overlapping label horizons with embargo. CPCV, PBO and Deflated Sharpe as supplementary *multiple-testing/selection bias* diagnostics; **not a substitute for independent prospective results**.
- Outcomes OPTIONS: 9, 15, 30 minute forward underlying return plus actual option premium path with executable bid/ask, realistic slippage/fees, missed fills, IV/theta sensitivities, worst adverse excursion, MAE/MFE. NEVER train on current-session-only 5 rows or invented quote timestamps.
- Outcomes SWING: actual next-session filled trade, stop/gap simulation, tax/fees, delisting/suspensions, portfolio overlap.
- Report net R expectancy `win_rate*mean_win_R - loss_rate*mean_loss_R - average_cost_R`, median R, payoff ratio, profit factor, max drawdown, longest loss streak, false break rate, number of independent trades, trade-level bootstrapped uncertainty, drawdown and calibration by expiry/time/regime. No arbitrary '60% winning' success badge.
- Robustness: double slippage, +50% spread, 1-bar delayed entry, 20% larger stops (risk held constant), fewer data points, worst-quartile liquidity; candidate must retain useful behavior, not just one golden parameter.
- Shadow period: >=30 trading sessions **AND** >=100 truly independent signal opportunities to make initial stability review; extend until sample/effective-count and uncertainty adequate. Not a guarantee of statistical power; only cautious provisional gate.
- Approval for manual pilot requires positive net out-of-sample expectancy, meaningful confidence interval, stable sensitivity, minimal data gaps and independent risk review.

## 5. System architecture / product specification

Keep **two modules**: (a) NIFTY Options Desk, (b) NSE EOD Swing Engine. Share:
1. Data evidence store / collector health / exact schema, exchange calendar, original source stamps and contract master.
2. Strategy registry/versioned immutable features; v1 frozen, v2 experiments isolated.
3. Cost and risk engine, independent of direction model.
4. Replay API for a specific historical timestamp reproducing **exactly what was known then**.
5. Trade journal / manual decision capture: setup, screenshot/reason, quoted spread, fill, post-exit attribution, adherence.
6. Production monitoring / alert delivery: Telegram only when independent gates pass, with original evidence hash and staleness flags.

NIFTY video-style terminal primary page: `Completed PRICE Candle | CE/PE Walls | OI Δ & Speed | GEX Scenario | Flow Proxies | Futures OI Quadrant | BULL/BEAR Hypothesis | Manual Action Gate`. Each cell supports source, timestamp, timeframe, units and validity. No missing market-data substitution.

Swing terminal: `Ticker | regime | 6–12m RS | EMA trend | POC/VAL/VAH | W%R | Larry A/D | BOF state | entry/stop/target | estimated net R | event/liquidity flags | review state`.

## 6. Prioritized implementation backlog (best next steps)

P0: **Historical truth and contract identifiers**
  - Validate FYERS Expired F&O Data API entitlement for one known expired NIFTY option strike using official Get Expiry Dates -> Get Expired Contracts -> Get Expired F&O Data, resolution=1 include_oi=1 include_greeks=1, and separately futures OI with Greeks OFF. Use precise response schema, timezone, source/version and missing bar checks; do NOT alter production.
  - Cross-check matched FYERS OI with NSE contract OI and exact lot size/expiry; no gamma/lot scaling before proof.
  - Acceptance: raw test payload saved append-only with secure permissions, schema validated, correct bar completion/times, errors and entitlement status explicit.

P1: 1m immutable price/option historical replay and shadow baseline; pair futures candle closes with option observations by nearest *previous known* observation only, never future chain.
P2: O1/O2 simple option breakout/futures/wall OI pilot, transaction cost sensitivity, no extra GEX sign assumption.
P3: isolated S1 swing trend pullback replay with point-in-time NIFTY 500 and adjusted EOD data.
P4: POC reclaim / BOF alternative hypotheses and proper ablations.
P5: only then gamma/vanna/charm and XGBoost **shadow** experiments.
P6: after independent gates, optional manual alerts with a trade journal and hard risk limits.

## 7. Tools and source references

Core:
- FYERS V3 REST and data WebSocket (live quotes/Greeks/OI as supported); official expired F&O research endpoints, explicit entitlement probe: https://fyers.in/api-docs/v3/api/market-data/expired-fo-data/get-expired-fo-data/
- NSE official all reports (UDiFF EOD) and market surveillance flags (ASM/GSM/ESM), permitted contract-size lookup: https://www.nseindia.com/all-reports ; https://www.nseindia.com/regulations/exchange-market-surveillance-actions
- Python + SQLite WAL on AWS, DuckDB+Parquet for *offline analytics*, pytest, GitHub Actions and immutable sha-checked data reports. Do not replace stable production service as part of research.
- vectorbt (fast broad parameter screening, beware optimistic fill model): https://vectorbt.dev/
- Microsoft Qlib (future research pipeline and ML comparisons, not necessary for v1): https://github.com/microsoft/qlib
- OpenBB (heterogeneous economics/market context; does not furnish all NSE intraday OI): https://github.com/OpenBB-finance/OpenBB
- XGBoost ONLY with enough validated labels, time aware leakage control and model calibration; optional MLflow for versioned training evidence.
- TradingView for visual strategy verification, not the sole source of actual NIFTY option OI/Greeks; Telegram for delivery, journal and kill switches before trade automation.

Evidence:
- SEBI FY26 profitability study Aug 2026: https://www.sebi.gov.in/reports-and-statistics/research/aug-2026/study-profitability-of-individual-traders-in-the-equity-derivatives-segment-fy25-fy26-_103835.html
- Indian momentum research: Sehgal, Pandey and Sen (2024), https://www.sciencedirect.com/science/article/pii/S1746880924000469
- Moskowitz, Ooi and Pedersen (2012) Time-series momentum: https://doi.org/10.1016/j.jfineco.2011.11.003
- Ni, Pearson, Poteshman and White (2021), option hedging moves underlying prices conditional on inferred positions, *not* direct Indian deal-flow replication: https://academic.oup.com/rfs/article-abstract/34/4/1952/5873587
- Bailey and Lopez de Prado (2014) Deflated Sharpe Ratio https://doi.org/10.3905/jpm.2014.40.5.094
- NSE contract specs updated 2026 with Tuesday expiry convention: https://www.nseindia.com/static/products-services/equity-derivatives-contract-specifications
- NSE F&O lot revision circular NSE/FAOP/70616 (75->65 NIFTY applicable contracts): https://nsearchives.nseindia.com/content/circulars/FAOP70616.pdf

## 8. Non-negotiable disclosure

No verified historical win rate, net expectancy, profitable XGBoost or live strategy edge is demonstrated by the present repository tests. Passing unit tests confirms implementation correctness for test inputs, not forecast validity. All new features remain log-only/research candidates until market data, statistical, risk and security acceptance are independently satisfied.
