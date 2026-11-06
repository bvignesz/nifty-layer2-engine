# Trading Research Method v2.0 — NIFTY Options + Indian Equity Swing

Status: RESEARCH SPECIFICATION, NOT A VALIDATED STRATEGY. 2026-11-06.
Scope: manual trading decision support. Freeze original nine-check calculations; build separate versioned modules and experiments. No live trade or paper-trade approval based solely on this document.

## Research basis (evidence vs hypothesis)

**Empirically supported but not proved for our specific rules**:
- Time-series momentum across international futures: Moskowitz, Ooi, Pedersen, JFE 2012, doi:10.1016/j.jfineco.2011.11.003.
- Cross-sectional stock momentum: Jegadeesh, Titman, Journal of Finance 1993, doi:10.1111/j.1540-6261.1993.tb04702.x.
- Indian momentum and liquidity interaction: *Momentum, reversals and liquidity: Indian evidence*, 2023, https://www.sciencedirect.com/science/article/pii/S0927538X23002640.
- NSE Nifty500 Momentum 50 methodology ranks 6- and 12-month volatility-normalized momentum (https://www.niftyindices.com/indices/equity/strategy-indices/nifty500--momentum--50).
- Option hedging demand can move underlying prices: *Hedging demand and market intraday momentum*, JFE 2021, https://www.sciencedirect.com/science/article/pii/S0304405X21001598.
- Hedging mechanism does NOT identify dealer inventory or validate a NIFTY gamma-flip estimate from public OI.

**Risk/base rate**: SEBI 2026 equity derivatives profitability study (https://www.sebi.gov.in/reports-and-statistics/research/aug-2026/study-profitability-of-individual-traders-in-the-equity-derivatives-segment-fy25-fy26-_103835.html) reports 87.7% losing individual traders in FY26. Do not assume higher indicator complexity resolves negative expectancy.

**Data**:
- FYERS expired F&O API provides per-contract intraday candle OHLCV plus optional OI and IV/Greeks for expired contracts, subject to plan/entitlement and null data: https://fyers.in/api-docs/v3/api/market-data/expired-fo-data/get-expired-fo-data/.
- FYERS ordinary history supports 1-minute price/futures OHLCV/OI and cautions not to use partial current-minute candles: https://fyers.in/api-docs/v3/api/market-data/historical-data.
- NSE displayed option OI is in contracts (https://www.nseindia.com/option-chain); FYERS raw API optionchain OI basis remains unverified until independently reconciled. No unauthorized NSE scraping.
- Per 2026-04-01 exchange rates, option sell premium STT = 0.15% and exercised options STT on intrinsic value = 0.15% (https://www.nseindia.com/static/products-services/equity-derivatives-securities-transaction-tax); calculate all brokerage, slippage, exchange fees, GST, stamp and impact separately.

## A. NIFTY Intraday option-buyer hypotheses

Use a three-layer architecture with categorical output `BULLISH_WATCH / BEARISH_WATCH / IGNORE` for *research* and separately `NO_TRADE / MANUAL_REVIEW` for execution readiness. Always display both, rather than hiding directional bias or presenting it as approved entry.

Layer 1 — pre-market context (not entry trigger):
- Prior-day market profile POC/VAH/VAL and measured gap relative to VA; document actual session conventions, TPO method and timezone.
- India VIX level and opening move relative to the previous close and its own trailing distribution (percentile); avoid universal VIX 11–15.5 gating without Indian backtest.
- Prior-day NIFTY/BANKNIFTY breadth, major index constituents, global overnight gap, scheduled RBI/Fed/US CPI/NFP, policy and expiry events.
- Distinguish structural context from directional prediction. Save original as-of timestamps and source.

Layer 2 — one horizontal video-style row per verified time slice:
1. **Completed index or futures candle**: actual exchange start/close timestamp, source, verified closure, no stale/partial bars.
2. **CE and PE walls**: strongest captured OI strikes; provide chain coverage ATM±N, expiry, exact contract/lot, confidence. Never claim full-chain maximum when sampling subset.
3. **Wall cut/migration**: signed OI delta at *fixed* contract over consecutive comparable windows, normalized by previous OI; follow moving-strike separately, no asynchronous mixing.
4. **OI speed**: delta OI over matched intervals divided by same-time-of-day historical baseline, with warmup/min-sample and regularization; do not confuse FYERS session OI change with 1m delta.
5. **Volume activity**: traded volume over completed interval or monotonic session-cumulative delta; relative to same-time-of-day baseline. Never infer aggressor side from volume alone.
6. **Premium-price/OI quadrant**: price up/down × OI up/down is *descriptive proxy* for activity, not conclusive long build/short cover or writer identity.
7. **Futures confirmation**: completed futures bars, futures OI per-bar change, price vs prior close and valid VWAP, basis vs spot, source latency; veto if missing/stale or conflicting.
8. **Strike GEX**: gamma × OI × price² × 1% with independently verified gamma convention, OI basis, contract lot and exact expiry. Show **scenario sign assumptions** only; CE-positive/PE-negative not observed dealer positioning. One-minute ΔGEX only where matched high-quality synchronized inputs exist.
9. **Market-profile location**: spot relative to PDVAH/PDVAL/PDPOC, open range, prior-day high/low; as context rather than nine-check replacement.
10. **Execution constraints**: best bid/ask, spread percent, market depth, realistic limit fill, realized/forecast delta, theta, IV, IV crush risk and option liquidity.

Layer 3 — test EXACTLY THREE entry archetypes before adding more:
A. `WALL_BREAK_FOLLOW_THROUGH`: fixed opposing wall cut + close beyond strike + futures price/OI alignment + valid liquidity. Entry on subsequent executable option quote, not on signal-close print.
B. `FALSE_BREAK_REJECTION`: completed break and reversal back through wall, with futures disagreement and no strong OI follow-through. This is a *different hypothesis*, not the inverse of A.
C. `PROFILE_REVERSION`: rejected excursion beyond prior VAH/VAL on non-trend/low-expansion regime, target toward POC; avoid trend/major event days.

Each experimental rule gets a versioned definition, fixed threshold file, signal time, data quality/coverage, expiry, CE/PE contract selector, fill assumptions, stop, time exit, take profit and a null/IGNORE state. Start with A only; add B and C after A's baseline replay is complete. Avoid retraining to make historical losses disappear.

**Option selection experiment**: filter 1–3 strikes around ATM with delta range candidate 0.35–0.65, adequate volume/OI, absolute and % spread limits, price/lot budget and days to expiry; compare ATM vs one ITM vs one OTM after costs using actual quotes. No guaranteed optimal delta or expiry; compare expiry buckets separately. Prefer longer time-to-expiry for research baseline to reduce severe 0DTE theta/gamma sensitivity, not because profitability is established.

**Risk hypotheses for paper testing**, configurable and subject to user's capital:
- Per-trade risk cap suggested pilot: 0.25%–0.50% of dedicated options capital (not total household assets).
- Intraday stop after e.g. two full-risk losses or 1% session drawdown; total daily stop whichever tighter.
- No increase in risk after loss, no averaging down, no uncapped expiry-day exposures, no spread/latency fallback to a favorable assumed fill.
- An executable risk calculation = (entry ask - planned exit bid incl adverse slippage) × **verified contract lot** × quantity + taxes/fees, and cap overnight loss to premium paid when long-only; realistic gaps can exceed intended stop.
- No trades when key timestamps, lot size, option premium, fresh quotes or valid completion are missing.
- These numerical thresholds are **initial risk controls to evaluate, not an established optimal risk policy**.

## B. Swing-trading engine — higher evidence baseline, distinct from options

Universe: point-in-time Nifty 500 membership (avoid survivorship), filter ASM/GSM/ESM, price circuits, corporate actions, turnover > ₹1 crore/day median 20 sessions *as a candidate gate*, and per-trade spreads/impact.

Stage 1: rank by 6m and 12m volatility-adjusted price returns, with a one-month skip comparator and RS against Nifty 500. Sector/market breadth veto and earnings-event exclusion. Preserve the existing 252-session momentum rank as benchmark; do not silently replace it.

Stage 2: evaluate these separately, not as a single overfit score:
- `TREND_EMA_PULLBACK`: above SMA200; EMA10 > EMA30 and rising; controlled dip to EMA zone; reversal confirmation after close.
- `RS_WPR3_POC`: RS leader, short Williams %R washout and tested volume-profile POC support; require valid point-in-time profile levels.
- `LARRY_AD_BREAKOUT`: Larry Williams A/D line rising before breakout, plus price/volume and resistance. Check reproducible indicator definition against source.
- `BOF / STRUCTURAL_REJECTION`: breakout failure after sweep and close back inside validated range. Distinguish day-only BOF from multi-day setups.

Portfolio gates (preserve existing): max four concurrent positions, no more than two per sector, ≤4% total stop-risk, ≤25% capital per name; realistic position size = equity-risk budget / (entry-stop) rounded down. Independent exposure/correlation and gap stress tests, plus survivorship-safe dividends/splits/renames.

Compare next-open entry with gap rejection, spread+slippage, ATR and structural stops, 10/20-session time exits, trailing exits, and realistic taxes. Benchmark each strategy against Nifty 500 and a basic liquid-stock momentum baseline, not zero return.

## C. Research protocol — acceptance before promotion

1. Evidence capture: immutable UTC receipt and source-time metadata, symbol master, expiry/lot, raw FYERS payload provenance, DB copies for backfill, null propagation.
2. Baseline: three archetypes only for options; two/three pre-registered swing setups; frozen param grids and audit trail of every iteration.
3. Replay: no lookahead; option selection made using only as-of data; next executable bid/ask, stale quote veto, partial candle prohibition, IV/expiry effects.
4. Holdout: chronological walk-forward testing with purging/embargo for overlapping outcomes, full transaction costs, parameter stability across years, VIX regimes and market sessions.
5. Overfitting control: compare untouched baselines, multiple-testing counts, probability of backtest overfitting (PBO) or Deflated Sharpe; references https://escholarship.org/uc/item/4w1110bb and https://doi.org/10.3905/jpm.2014.40.5.094.
6. Outcome table: sample count, profit factor, win rate, avg win/avg loss, net expectancy in R, maximum drawdown, tail losses, median spread, signal availability, rejected signals and commission/tax sensitivity.
7. Shadow period: several trading weeks at minimum plus enough *independent signals* for confidence intervals; no guarantee based on a fixed count of trades. Review false positives and strategy drift; trader approval required to change status.
8. ML XGBoost LAST: after diverse genuine outcomes and timestamps, baseline comparison, cross-fitting and calibration. Use probability for research ranking, never infer edge from accuracy alone or from five labels.

## D. Tooling / architecture

- Keep **FYERS v3** for authenticated quotes, 1m completed spot/futures candles, contract metadata, optionchain and expired-options historical OI/Greeks.
- Keep **SQLite** immutable raw event journal and normalized read models; use separate data quality and artifact snapshots.
- **Python + pandas + numpy + scipy** for features and independent Black-76 Greek sensitivity. **pytest** for invariants.
- **vectorbt** for exploratory parameter sensitivity, **LEAN** if complex event-driven execution replay is needed; avoid running two overlapping backtest infrastructures prematurely.
- **XGBoost + scikit-learn** for shadow prediction only after data.
- **GitHub PR + CI + Codex** for development with human approval for any production change.
- **TradingView** for discretionary market-structure visualization; never substitute chart screenshots for exchange-level option OI data.
- **NSE Indices** for point-in-time universe/index methodology; licensed historical market data where applicable.
- **Telegram** for research status, data outage and threshold alerts, not automatic orders.
- Trade journal with setup ID, pre-registered thesis, planned stop, actual timestamp/quotes/fill, risk amount, screenshot link, outcome and decision-quality tags.

## E. Milestone sequencing and stopping conditions

M0 (NOW): read-only expired-F&O 1m exact-contract proof of data entitlement and field completeness; preserve old dashboard and collector. No backend signal promotions.
M1: option/futures timestamp and OI-unit/lot reconciliation; old nine checks audited without modification.
M2: matched 1m and completed 3m video-terminal with data provenance column; true unavailable data shown as blank.
M3: implement A (`WALL_BREAK_FOLLOW_THROUGH`) replay with realistic option fill/costs vs no-signal baseline. Report failures.
M4: implement swing momentum + EMA/POC baseline replay separately.
M5: expand to other ideas only if M3/M4 outcomes justify complexity.
M6: prospective paper trading, decision journal, bounded manual promotion after independent audit.

**Never call a forecast a validated profitable strategy; never auto-deploy or place orders.**
