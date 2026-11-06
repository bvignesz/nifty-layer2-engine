# Trading Research Method v2.0 — NIFTY Option Buying + Indian Equity Swing
**Date:** 2026-11-06 · **Status:** RESEARCH SPECIFICATION / not validated · **Owner:** private manual execution desk

This specification *augments but does not modify* the frozen nine-check Layer 2 engine, original indicator calculations, existing strategies, or live AWS services. Any thresholds below are candidate values to backtest, NOT established profitable parameters. Preserve a record of all tested variants; no future-data leakage.

## Executive decision
Maintain TWO SEPARATE tracks sharing data plumbing, risk accounting, reproducible backtests, trade journaling and market regime research, but **never blend their P&L or invent a common win rate**:
- **Track O:** NIFTY intraday long-option decision support; decision = CE WATCH / PE WATCH / IGNORE, with execution manual only.
- **Track S:** NSE cash-equity daily swing ranking and alerting; action = setup watch / planned trade / reject, with manual execution only.

**Why this priority:** SEBI FY26 research reported ~87.7% of individual derivatives participants lost money and annual net losses of approximately ₹91,685 crore. Such descriptive population statistics cannot predict this user's results, but justify emphasizing trade rejection, genuine after-cost expectancy and drawdown control rather than more signals.

Source: https://www.sebi.gov.in/reports-and-statistics/research/aug-2026/study-profitability-of-individual-traders-in-the-equity-derivatives-segment-fy25-fy26-_103835.html

## Track O — Four stages, none bypassed

### O1. Market conditions and premarket context (Layer 1)
Observe and timestamp: prior-day NIFTY futures close and high/low; PDVAH/PDVAL/PDPOC *only where reproducibly calculated from valid price/volume or TPO profile data*; overnight gap; India VIX previous close/opening level and change; scheduled RBI/Fed/CPI/jobs earnings releases; broad-market index and selected high-weight constituents; price/futures VWAP and volume confirmation. FII/DII published category positions, when available, are prior-period **context**—never pretend they are live trader flow. NSE India VIX measures near-term 30-calendar-day implied volatility; a fixed threshold (e.g. 11–15.5) needs conditional calibration rather than being treated as universal.

Classify day regime as **TREND_CANDIDATE**, **RANGE_CANDIDATE**, **EVENT_RISK**, or **UNKNOWN** with explicit source, age, horizon, confidence, and missing fields. If UNKNOWN or critical stale data, default IGNORE, not opposite side.

Sources: https://www.nseindia.com/static/products-services/indices-indiavix-index ; https://www.nseindia.com/static/products-services/equity-derivatives-contract-specifications

### O2. Observable intraday microstructure (Layer 2)
Preserve existing nine checks for comparison as baseline; implement the following as *independent shadow features*, not hidden replacement:
1. **Wall persistence and migration:** max observed CE and PE OI by *same contract, same expiry*, restricted to captured strike coverage. Report wall level, relative OI, change (matched raw data) and persistence across ≥2 valid receipt observations. High OI does not prove resistance/support, seller sign or market-wide max.
2. **Wall cut and OI velocity:** ΔOI(OI_t − OI_previous) / prior positive OI, using nonoverlapping comparable receipt brackets, contract-level OI units, same expiry, no missingness, 90–360s gap. Rolling same-time-of-day baseline for velocity and warm-up. Report both raw and regularized changes; never divide by a near-zero denominator unprotected.
3. **Volume and churn:** incremental volume only if broker cumulative volume is monotonic and same-session same-contract. Vol/|ΔOI| measures turnover-to-positioning change; it does **not** reveal initiator side, seller exit or writing. Capture strike LTP and quote spread in parallel. Label empirical direction as **OI_BUILD_WITH_PRICE_UP/DOWN**, **OI_CUT_WITH_PRICE_UP/DOWN**, or **AMBIGUOUS**.
4. **Futures confirmation:** require two *completed exchange-timestamped* bars (not receipt proxies) of same futures contract, price and OI change with explicit OI basis. Quadrants: price↑ OI↑ = long-build proxy; price↓ OI↑ = short-build proxy; price↑ OI↓ = covering proxy; price↓ OI↓ = liquidation proxy. This is a convention, not proof of particular trader class.
5. **GEX scenarios:** broker gamma × normalized OI units × F² × 1% / 1e7 (INR Cr per +1% movement), track CE/PE and multi-strike coverage. Dealer sign assumed; report alternate all-positive/all-negative and CE+PE−. Never call a modeled gamma flip actual dealer positioning. Unit audit currently: 92/92 FYERS unique positive day-contract OI values divisible by lot 65; **not independent proof**. Lot sizes are contract-specific (NSE NIFTY new standard 65 vs historical 75).
6. **Price structure:** completed 1m spot/futures close beyond chosen strike/wall with 3m confirmation; independent of options receipt time. Measure false break / reclaim and continuation relative to pre-specified reference levels, with no lookahead.
7. **Integrity:** timestamp ordering, calendar/session alignment, FYERS token health, missing IV/gamma/quotes, duplicate conflict, conflicting OI, symbol roll, expiry roll, source latency, wide bid/ask, and mark release of each input.

The user-requested **video-style table** should remain dense: observed receipt, completed futures/spot candle (only if verified), CE/PE wall, ΔOI, OI velocity, volume increment, GEX scenario, futures quadrant, legacy BULL/BEAR research verdict, final independent decision and reason. Zero, unavailable and stale must be visually distinct.

API sources: https://fyers.in/api-docs/v3/api/market-data/option-chain/ ; https://fyers.in/api-docs/v3/api/market-data/expired-fo-data/get-expired-fo-data/ ; https://fyers.in/api-docs/v3/api/websockets/websocket-overview/

### O3. Independent decision policy (Layer 3)
Separate **BIAS** from **SETUP** from **TRADE-ELIGIBLE**:
- **BIAS:** BULL / BEAR / MIXED / UNKNOWN from preserved legacy + independently versioned shadow readings.
- **SETUP:** candidate breakout/retest or rejection near wall/PDVAH/PDVAL/VWAP (pre-declared family); confirm with completed price and comparable futures bars.
- **VETO:** invalid price bar, missing exact contract OI provenance, stale quotes, no 2-bar confirmation, unusually large spread, poor liquidity, expiry-day jump risk, imminent major scheduled event, contradictory futures data, too-large stop in option premium, daily loss limit hit, or no adequate after-cost reward. Dealer gamma scenario never overrides veto.
- **ELIGIBLE:** only after release gate *and prospective validation* can a recommendation be labeled CE WATCH/PE WATCH instead of research-only. Current production classification remains NO TRADE.

Proposed scoring **for experiments only**: 30% price/futures directional structure, 25% comparable option OI flows, 20% futures OI/volume quadrant, 15% execution liquidity/IV regime, 10% higher-timeframe context. GEX dealer-sign magnitude **excluded from primary scoring** until verified. These weights are NOT trained or empirically validated; register before testing to prevent cherry-picking.

### O4. Contract choice, fills, exits, measurable performance
After a directional candidate passes, **option selection is a distinct problem**. Compare ATM and adjacent ITM/OTM exact symbols for delta band **hypothesis** 0.40–0.65, bid/ask spread as % mid, min displayed volume, traded value and executable depth (quote age), IV relative to its own term/strike historical distribution, theta per expected hold, expiry DTE, vega exposure and available risk budget. Do NOT select the highest gamma merely for a directional forecast.

**Trade lifecycle:** define limit order with fill/slippage simulation, invalidation on underlying structural break and premium risk stop, time stop, and pre-registered profit-taking alternatives (1.5–2R candidate vs 2R benchmark) using walk-forward test. Profit targets don't imply expectancy. Account for STT, exchange charges, brokerage, GST and slippage for each fill at the correct date. Use actual contract multiplier in quantity.

**Suggested initial paper-trading constraints — unvalidated risk policy:** risk <=0.25% of options trading capital per trade; max 2 entries/day; max daily loss 0.75%; hard stop after two full-size losses; no averaging down; no overnight long index options until separately tested; no naked short option positions; do not execute automatically. If account size or minimum lot makes this impossible, **skip trade** rather than exceed limit.

Metrics: option-purchase fill-to-exit net R (not NIFTY points), median/mean R, expectancy R and INR, profit factor, return skew, maximum drawdown, volatility-regime breakdown, expiry/DTE breakdown, slippage, bid/ask cost, signal-to-fill latency, false breakout rate, missed-signal rate, abstention rate, opportunity cost, and full confidence intervals. Separate signal accuracy from trade profitability.

## Track S — NSE equities swing scanner
**Prior known baseline**: NIFTY 500 screened EOD; top-30 momentum (252 days excluding most recent 21, optionally volatility-scaled), EMA10>EMA30 and price>SMA200 for pullback, EMA10 slope and separation gates, NR7/BOF/VRZ/Wyckoff and Larry Williams A/D confirmation, RS–Williams %R3–POC as another separate setup family. Preserve historical stage versions rather than collapsing all into one opaque score.

Upgrade candidate:
1. Reconstruct **point-in-time tradable universe** of then-current NIFTY 500 constituents incl delisted and corporate actions; use NSE CM-UDiFF and security master, not today's survivors. Corporate action adjusted total-return series for signals, raw execution data with dated splits/bonus/dividends and tick-size regime.
2. **Market/sector filter**: NIFTY 500 and relevant sector relative strength; broad market above/below major moving-average range and breadth; only selectively take aggressive long momentum when breadth improves. The popular 200DMA is a design candidate, not empirically optimal.
3. **Rank once per EOD**: 12-2 momentum/volatility and 3–6 month RS; separate breakout, EMA pullback and RS–W%R3–POC experiments with label leakage protection. Add Larry A/D and volume as conditional tests. **Do not require all indicators**; too many correlated filters reduce sample count and falsely increase backtest appeal.
4. **Execution and liquidity**: prior 20-day median turnover at least ₹1 crore; avoid ASM/GSM/ESM, circuits, extreme gaps, unusual spread, and blackout around high-impact earnings/corporate actions. Signal after close; fill next tradable open/limit; explicit unfilled / gap-skip / paused cases.
5. **Risk policy** (prior user framework): max 4 open positions, <=2 per sector, <=4% aggregate open-stop risk, <=25% gross capital per name, 5-session order expiry. Start smaller when out-of-sample drawdown unknown; per-trade defined stop risk e.g. 0.5–1% capital, hard maximum, with gap/slippage modeled. Track correlation concentration, sector and regime exposure.
6. **Exits**: benchmark 3×ATR or EMA30 trailing, time stop at 20 sessions, monthly momentum decay, hard structural stop and gap-out; compare against static exit with unbiased testing. Reserve 1–3 year investment logic in a separate portfolio, no shared positions/accounting.

Research: 2020 IIMB momentum study identifies historical portfolio momentum in India; 2024 Indian relative-vs-absolute momentum research examines robustness; Daniel/Moskowitz show momentum crashes in panic/rebound regimes. **No cited study verifies our proprietary rules or guarantees profits.**
- https://www.sciencedirect.com/science/article/pii/S0970389617301647
- https://www.sciencedirect.com/science/article/pii/S1746880924000469
- https://www.nber.org/papers/w20439
- https://www.nseindia.com/all-reports

## Data architecture and measured experiment
| Store | Grain | Provenance |
|---|---|---|
| raw_market_events | immutable request/receipt per call, digest, plan and symbol | raw broker only, no fabricated exchange time |
| exchange_price_bars | symbol × bar-start × resolution, complete flag | actual exchange timestamp verified |
| option_chain_receipts | expiry × strike × side × receipt bracket | no claims of completed option price candle |
| option_contract_bars | exact option symbol × bar-start × resolution, OI/Greeks optional | expired-F&O endpoint probe with response columns |
| derived_features | config version × timestamp × origin keys | missingness flags and units |
| signal_events | candidate and veto reason; no order | BULL / BEAR / IGNORE and raw legacy comparison |
| paper_executions | simulated order intent × fill model | bid/ask/fees/time and rejected fills |
| manual_trade_journal | actual broker contract notes manually reconciled | observed, not backfilled synthetic |
| outcome_labels | future timestamp AFTER eligible signal | no accidental lookahead; never label missing futures |

Do not modify existing SQLite production tables for this specification. New migrations only on a copy, after tests and explicit install approval.

**Evidence test protocol**: start simple baseline, train/test date splits, purged walk-forward across expiry days + embargo, never feature-calc using future chain rows; assess CPCV/PBO/Deflated Sharpe as secondary robustness methods, not substitutes for genuinely untouched prospective paper trades. Hold out whole days/regimes rather than random 1-minute rows. Use a minimum pre-registered sample and report confidence intervals. No specific sample count automatically proves robustness: 100+ independent trades across several regimes is an initial monitoring target, not an approval threshold.

Sources: https://escholarship.org/uc/item/4w1110bb ; https://doi.org/10.3905/jpm.2014.40.5.094 ; https://doi.org/10.1093/rfs/hhaa010

## Priorities, each with a deliverable and stop condition
| Order | Project | Deliverable | Acceptance / no-go |
|---|---|---|---|
| P0 | Integrity and actual OI/time units | Exact contract data provenance + FYERS/NSE unit reconciliation | Misaligned/unknown units => GEX scenario only |
| P1 | Option replay data | Read-only **expired F&O 1m OI/Greeks** probe using genuine expired symbol and named columns | Endpoint entitlement, 1m closure, consistency; never guess stale values |
| P2 | Realistic risk/fill engine | Fee and bid/ask sensitivity, risk ledger and abstention gate | Cannot fill within spread/max risk => IGNORE |
| P3 | Two baseline setups | NIFTY wall-break/retest with completed futures and OI; cash swing momentum pullback | Reproducible costs, simple-vs-complex ablation |
| P4 | Video terminal | Dense six-panel single-row observation, status/coverage/age fields | no fictional 1m or seller identification |
| P5 | Prospective paper journal | immutable signals, independent outcomes and weekly metrics | sample/CI and drawdown before escalation |
| P6 | XGBoost shadow only | proper purged/embargoed walk-forward classification/calibration | must beat strong baseline after costs without leakage |
| P7 | Optional macro/news/market-profile | controlled, time-stamped gate, no cherry-picked feature explosion | only if incremental measured lift |

## Operator checklist
**Before market**: broker auth/expiry/session; risk budget; known events; regime; valid data; candidate levels; no predetermined forced trade.

**During market**: observe options flow and futures; require price confirmation; respect veto; only note predeclared setups; no trade from raw gamma sign.

**After market**: immutable snapshot, classify false alerts and missed data; reconcile real fills; run after-cost expectancy; do not retune based on a losing day.

**Weekly**: review specific missed/false alert classes, audit costs/latency/position sizing; add exactly ONE experimental change; evaluate an untouched holdout and retain versioned baseline.

## Research tooling order
- **FYERS v3**: connected read-only data, expiration-aware option chain, optional expired F&O OHLCV/OI/Greeks and WebSocket. Rate limits/entitlements vary; avoid polling full chain every second.
- **NSE reports/security master**: corporate actions, cash bhavcopy and position/derivatives statistics for independent reconciliation, respect exchange access terms.
- **Python/Pandas/SQLite + FastAPI**: deterministic collection/validation and versioned storage. Use current app infrastructure before rewriting in Rust/stack migration.
- **vectorbt / backtrader / custom event-driven replay**: candidate backtesting libraries; benchmark actual gap/slippage and instrument-specific option fills, don't blindly treat bars as executable.
- **scikit-learn/XGBoost**: calibration/shadow hypotheses after adequate outcomes and properly purged chronological validation.
- **TradingView**: price/market-profile chart and manual visual corroboration, not an option OI/GEX exchange source.
- **GitHub + Codex**: developer/tester with PR audit trail, strict no-production write; terminal/Telegram read-only alerts, never automatic orders.
- **Journal** (SQLite/CSV or dedicated application): real fills, reason codes, R, screenshot/time and post-trade audit.

## Critical guardrails
- Success = demonstrated, after-cost expectancy **and** acceptable tail risk across independent periods; no indicator or model guarantees success.
- Do not infer buyer vs seller from OI and volume alone.
- Do not assign completed 1m option candles to receipt-only optionchain.
- Don't optimize MTF leverage or long options sizing to chase arbitrary P&L targets.
- Never move from paper to live without independent checks and explicit owner approval.
