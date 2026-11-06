# Trading Method v2.0 — NIFTY Options Desk + Indian Equity Swing Engine
**Status:** research specification only | **Date:** 2026-11-06 | **Execution:** manual | **Preservation:** do not change legacy nine checks.  
**This is an auditable hypothesis and risk framework, not a proven profitable strategy.**

## Purpose and evidence hierarchy
Two separate alpha hypotheses share data engineering, execution-quality, risk and research tools:
(A) **NIFTY option buying**: find an independently confirmed **underlying directional move**, then select a *liquid option whose expected value after IV, theta, spread and fees is acceptable*.
(B) **NSE equity swing**: favor liquid stocks with relative/absolute momentum and defined support/risk, using Larry Williams A/D and market profile as *testable refinements*, not assumed edge.

Evidence from SEBI: 93% of individual equity F&O participants lost money over FY22–FY24 (Sep 2024), FY25 SEBI study reported 91% loss-making; optimizing alerts is not equivalent to positive net expectancy. SEBI equity intraday study: ~71% lost money FY23. Indian studies: Chui et al. (2023) finds intermediate/long momentum especially in liquid stocks; Jain, Varma & Agarwalla (2019) finds Indian options IV contains forward-volatility information and option pricing reasonably fits a smile-adjusted model. Academic literature supports *study designs*, not a guaranteed signal.

**Evidence tags for every dashboard column:** EXCHANGE_COMPLETE (verified bar close), BROKER_RECEIPT (not necessarily exchange-time), DERIVED (definition + inputs + coverage), SCENARIO (unverified dealer sign / OI units), MISSING, STALE. Store timestamps for request, receipt, source bar, expiry, symbol, contract lot and schema version. Never promote a scenario to observation.

## Layer 1 — Daily pre-market context, not a directional oracle
Document expected market condition; do not vote every metric into a single score.
- Previous-day market profile POC/VAH/VAL from reproducible 5m volume profile, previous day high/low, gap relative to value, and NIFTY 50 / BANKNIFTY context.
- Event calendar: RBI policy, major global central banks, key US macro prints, NSE holidays, major heavyweight earnings; event blackout if release time overlaps setup. Data publisher, timezone and timestamp required.
- India VIX: level, **opening change**, term structure if reliably sourced, compare to historical regime distribution; fixed 11–15.5 threshold remains a hypothesis, not universal.
- Gap size versus recent realized-volatility expectation and opening range; benchmark against no-gate models. FII futures longs/shorts only as lagged context sourced with publication timestamp.
- Output one of: TREND_CANDIDATE, RANGE_CANDIDATE, EVENT_RISK, UNCERTAIN. Never force CE/PE side based on pre-market alone.

## Layer 2 — Video-style NIFTY microstructure terminal
One horizontal row per **verified timestamp**, preserving video columns and the frozen original nine-check output.
- **Completed underlying bar:** exact spot/futures timestamp, 1m close after 1m ends; completed 3m confirmation, 3m bar start/end; never call a 3m optionchain receipt a 1m exchange candle.
- **Wall:** nearest-expiry *captured-subset* max CE/PE OI, distance in points, same-contract wall cut ΔOI, migration requiring stable capture universes. Also add normalized share of chain OI captured to avoid claiming whole-market wall.
- **Flow:** incremental OI and volume for matched identical symbols, same expiry, same units, same trading date. Distinguish OI price quadrants from true trade initiator. Labels `OI_BUILD_PROXY`, `OI_CUT_PROXY`, `VOLUME_BURST`, `UNKNOWN`. Do not assert seller-only, confirmed writing, or forced exits.
- **Futures:** price Δ + OI Δ quadrant: ↑↑ long-build proxy; ↓↑ short-build proxy; ↑↓ short-cover proxy; ↓↓ long-liquidation proxy; stale OI -> UNKNOWN; compare price with VWAP/PDVA, historical time-of-day baseline. These four labels are *heuristics*, not participant identity.
- **GEX:** validate broker gamma and OI contracts/underlying units, lot per contract, forward, expiry and surface. Display CE-positive/PE-negative **signed OI scenario**, coverage and 1m/3m change only if both matched, time-consistent snapshots exist. Dealer inventory and dealer gamma flip are unobservable without inventory evidence; no automatic price-target extrapolation.
- **Original nine checks:** always show BULL/BEAR check statuses and original verdict separately, unchanged.
- **Final research bias:** BULL / BEAR / IGNORE (for the user), with `evidence_state`: FRESH_VALIDATED_INPUTS, RECEIPT_ONLY, STALE, INCOMPLETE, UNTESTED_MODEL, etc. **Trade eligibility** is an independent gate with default NOT_APPROVED. Avoid suppressing the research bias just because deployment approval has not been granted.

## Layer 3 — Option buyer economic decision gate (most important new addition)
Run this **after** underlying direction; options have nonlinear payoff and can lose on correct direction.
1. **Underlying setup:** breakout/acceptance above resistance for CE or breakdown/acceptance below support for PE, or post-break retest. Choose one primary rule initially, no discretionary combinations.
2. **Independent confirmation:** a completed 3m candle, futures price+OI quadrant and at least one independent wall/flow observation where truly time-comparable. With incomplete OI: record RESEARCH_BIAS_ONLY; no automatic entry.
3. **Contract selector:** check exact tradable symbol, expiry/lot, spread/ask/depth, delta and gamma, sufficient time-to-expiry, theta/day, IV and volume. Compare ATM and one adjacent ITM candidate (not deep OTM by default). Default to avoiding final-hours/expiry trades until separate evaluation supports them.
4. **Option premium expected return (NOT just spot point target):** Scenario simulator under underlying paths (up/down/flat), plausible IV shifts and time decay, repriced using a declared consistent model. Input option ASK for entry; BID for exit, plus estimated slippage and full FYERS/exchange tax/fee schedule. Include IV crush, gamma and stop gap risk. No numeric profitability claim without measured distribution.
5. **Conservative trade quality:** positive net expectancy across out-of-sample observations, adequate expected reward/cost, bounded maximum premium at risk, enough order-book liquidity, trade frequency cap. Otherwise IGNORE. Define thesis invalidation in underlying terms; check option stop executable after spreads, not a guaranteed loss cap.
6. **Trade ticket (manual):** one candidate CE/PE or IGNORE, evidence and as-of time, selected strike, premium ASK/BID, spread %, delta, IV percentile, expiry/lot, estimated cost round-trip, estimated stop/target range, max premium exposure, reason codes.
7. **Competing baselines:** a simple futures-price/volume breakout with no OI/GEX; same rule plus OI; then add GEX regime. Added complexity wins promotion only if it improves **out-of-sample net expectancy, drawdown and robustness**.

## Option buying risk policy (INITIAL research defaults, not universal)
- Separate option buying from swing and long-term accounts; no automatic brokerage orders.
- First live phase = **paper trading with realistic bid/ask fill and costs**. Later only explicitly approved small-lot manual deployment.
- Research maximum intended loss per option trade: **0.25–0.5% of dedicated options capital**, conditional on affordability of the *entire premium*. Premium paid is actual maximum long-option loss and can exceed intended stop risk.
- Daily stop: **1% options capital**, weekly stop: **2.5%** (policy hypotheses, require user approval). Stop new signals after max drawdown or stale data; no averaging down, martingale, recovery trades, or unhedged overnight option carry by default.
- Limit candidate entries per session and avoid overstated confidence from correlated CE/PE OI features.
- Track true cash premium paid, lot multiplier, bid/ask spread, round-trip broker/SEBI/STT/GST/stamp/exchange fees, partial fills, IV moves and mark-to-market; use actual FYERS contract note to reconcile costs.

## Swing-trading track — separate scanner and position book
**Universe:** rolling Nifty 500 constituents with survivorship-bias-aware point-in-time membership, corporate-action adjusted OHLCV, liquidity turnover >= ₹1 crore 20d median (research gate), exclude ASM/GSM/ESM and bands/circuits using dated NSE sources.
**Regime:** Nifty 500 above 200d MA and market breadth rising -> full candidate set; weak/bear regimes -> fewer trades or cash.
**Candidate ranking:** 12-1/12-2 month momentum vs Nifty 500, 3–6m RS confirmation, sector-relative strength, adjusted 20–60d volume/turnover, avoid extreme illiquidity. Cite and validate liquidity interactions rather than assuming RSI-2 or A/D is causal.
**Setups (separately backtested):**
- Track S1: EMA10 > EMA30, positive EMA10 slope, price > SMA200, controlled pullback to EMA10/30 without structural breakdown, Larry Williams accumulation/distribution positive or rising; buy on confirmation and stop below swing low / ATR rule.
- Track S2: breakout above reproducible compression/range with increasing traded value and Nifty-relative strength; avoid large gap-to-entry.
- Track S3 exploratory: BOF/VRZ/POC/VAL/VAH and RSI-2/W%R3 low near support, only after independent replay proves incremental benefit, not because indicator is popular.
**Capital:** preserve existing personal risk guards (max 4 positions, <=2/sector, max portfolio open-trade risk 4%, no individual position >25% notional, new orders expire after 5 sessions); review whether 4% portfolio open-risk is prudent. No MTF leverage before proven stability. Choose predeclared trade exits (structural/ATR stop; EMA30 trend trail; maximum 20 trading sessions) in separate trials, not opportunistically after observing outcome.
**Success metrics:** time-weighted net return, CAGR, max DD, pain/recovery, expected R/trade, hit rate, average win/loss, turnover and costs, exposure-adjusted alpha vs Nifty 500. Do not optimize win rate alone.

## ML / XGBoost — restricted to shadow research
- Engineer **as-of** snapshots: only source timestamps <= decision cut, contract identity and dated point-in-time universe. Save data lineage and hashes.
- Targets: forward *tradable premium* returns at 3/9/15/30 minutes for options and R-multiple at 5/10/20 sessions for swing; horizon-specific labels and cost-aware outcomes. Avoid using future whole-day IV or OI to predict earlier bars.
- Walk-forward chronological splits with purging/embargo for overlapping labels; CSCV/PBO and deflated Sharpe when selecting many configurations, plus independent untouched prospective paper results. Train a simple logistic/XGBoost baseline *only after enough independent events* (111 receipt-only events are not enough). Select thresholds on training/validation only, and evaluate locked out-of-sample once.
- Model controls: calibration curves/Brier score, class imbalance, trade/no-trade precision, missingness, drift, fee stress tests, ablation per additional feature, never override explicit hard-risk gates.

## Acceptance gates and dashboard fields
Each proposed indicator must define: source, unit, refresh rate, timestamp provenance, formula, lookback/warmup, session boundary, missing behavior, stale cutoff, cross-contract normalization, test, hypothesis, and deactivation condition.

| Gate | Pass criteria |
|---|---|
| A Data provenance | exact contract expiry/lot; no missing exchange-start for claimed closed price bar; option OI receipt provenance explicit |
| B Accuracy | contract volume/price/OI unit parity; timestamp/candle completion; corporate actions for swing; historical replay reproducible |
| C Incremental evidence | performance improvement vs cheap baseline after fees out of sample; PBO/DSR and stability documented |
| D Execution | ASK entry/BID exit, measured spreads and actual contract-note fees, depth/slippage stress |
| E Live readiness | weeks of prospective paper observations across trending/ranging/event regimes, reliability, rollback |
| F Risk | per-trade/daily/weekly stop and missing-data veto exercised in tests |

A chart full of green alerts is NOT an accepted signal until A–F have passed.

## Highest-value next 6 development increments
1. **Expired F&O 1m FYERS read-only probe** for exact expired NIFTY CE/PE from broker contract listing, including `include_oi=1`, `include_greeks=1`, schema-version and named columns; record entitlement, missingness and actual confirmed completed bars. FYERS Standard documentation states just **10 intraday expired-FO API requests/day**; avoid broad scraping.
2. **Premium Economics Simulator**: spot path × IV change × time decay × ASK/BID exit + charges; compare ATM vs one ITM. Required before recommending strike.
3. **Source-provenance diagnostic on every visible dashboard field**, particularly BULL/BEAR, seller proxy and GEX scenario. Mark incomplete and stale, don't hide research bias.
4. **Futures and OI replay baseline** and independent out-of-sample outcome labels; ablate nine checks, GEX, profile, volume filters without altering frozen original.
5. **Swing Track S1 baseline** 2010–present point-in-time data where available; compare momentum-only vs Larry A/D vs profile; risk/cost modeling.
6. **Risk journal + paper execution reconciliation** and weekly scorecard. Promote no strategy merely because dashboard has attractive signals.

## Toolchain decision
- Data: FYERS API v3, authorized NSE official circulars/contract specs and permitted EOD corporate actions. Don't automate unauthorized NSE website extraction.
- Service/DB: existing Python collectors, FastAPI (later migration if approved), SQLite WAL now; Postgres only once write concurrency warrants it. AWS first; Hostinger after operations testing.
- Research: pandas, NumPy, scipy, Jupyter, vectorbt for fast parameter screening, dedicated event-driven replay for fills/costs, pytest, GitHub Actions.
- ML: scikit-learn and XGBoost shadow; model ledger, no production decisions.
- Display: current video-style microstructure table, Plotly optional; Telegram alerts with OBSERVED/SCENARIO tags; no unattended order execution.
- Trader workflow: TradingView for visual inspection and manual alerts; FYERS terminal for order placement and account verification; NSE disclosures for events/lot/holidays; QuantStats for risk/return tear sheets; personal journal (CSV/SQLite) for planned vs realized metrics.

## Sources (checked Nov 6, 2026)
- SEBI F&O research FY22–FY24: https://www.sebi.gov.in/media-and-notifications/press-releases/sep-2024/updated-sebi-study-reveals-93-of-individual-traders-incurred-losses-in-equity-fando-between-fy22-and-fy24-aggregate-losses-exceed-1-8-lakh-crores-over-three-years_86906.html
- SEBI cash intraday: https://www.sebi.gov.in/media-and-notifications/press-releases/jul-2024/sebi-study-finds-that-7-out-of-10-individual-intraday-traders-in-equity-cash-segment-make-losses_84948.html
- FYERS expired derivatives minute data and optional Greeks: https://fyers.in/api-docs/v3/api/market-data/expired-fo-data/get-expired-fo-data/
- FYERS optionchain: https://fyers.in/api-docs/v3/api/market-data/option-chain
- NSE contracts: https://www.nseindia.com/static/products-services/equity-derivatives-contract-specifications
- NSE surveillance and GSM: https://www.nseindia.com/regulations/exchange-market-surveillance-actions
- NSE website OI in contracts: https://www.nseindia.com/option-chain
- Chui et al 2023 (liquidity and Indian momentum): https://www.sciencedirect.com/science/article/pii/S0927538X23002640
- Jain et al 2019 (Indian option IV): https://onlinelibrary.wiley.com/doi/10.1002/fut.21971
- Bailey et al (PBO): https://escholarship.org/uc/item/4w1110bb
- Bailey and Lopez de Prado (DSR): https://doi.org/10.3905/jpm.2014.40.5.094
- FYERS charges: https://fyers.in/charges-list
