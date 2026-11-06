# INDIAN EQUITY SWING ENGINE vNext — source-backed hypothesis plan (2026-11-06)

**Purpose:** Build consistent, manual NSE swing-trade selection from NIFTY 500/EOD; separate from intraday NIFTY option microstructure. No promise of positive expectancy. Preserve frozen RS–W%R3–POC v0.7.0 and existing breakout / Larry A-D / BOF rules until historical A/B validation.

## Source grounding
- NSE Nifty500 Momentum 50 explicitly uses volatility-adjusted six- and twelve-month momentum to rank members of Nifty 500: https://www.niftyindices.com/indices/equity/strategy-indices/nifty500--momentum--50
- Sehgal, Pandey & Sen, 2024, *Relative, absolute or combined strength momentum strategies: what works for India?*, examines enhancements to momentum on NSE-listed firms: https://www.sciencedirect.com/science/article/pii/S1746880924000469 . Research supports testing factors, not particular EMA/POC signal profitability.
- NSE official UDiFF Common Bhavcopy, historical price, delivery, corporate-action-related resources: https://www.nseindia.com/all-reports . Avoid obsolete pre-2024 filenames.
- Backtest overfitting paper Bailey et al. https://escholarship.org/uc/item/4w1110bb . A visually excellent parameter optimization on the same data is not independent evidence.

## Pipeline

### 0. Data quality and point-in-time universe
- Real NIFTY 500 constituents **as-of each historical rebalance date**, not just today's 500; track listings/delistings, splits, bonuses, symbol change, dividends, ASM/GSM, price bands, pledge and missing periods.
- Validate FYERS daily historical bars against NSE UDiFF raw close/volume and adjusted total-return data, retain provenance and adjustment flags.
- Require 20-session median traded value >= Rs 1 crore (existing policy); test more conservative Rs 2–5 crore liquidity tiers to reduce impact/slippage.
- Exclude corporate events around earnings/events with a pre-declared blackout (e.g. 1–2 sessions before/after, to be validated). Freeze list at EOD to avoid lookahead.

### 1. Market and sector regime first
- Broad index NIFTY 500 relative to SMA200 and its 20-session slope; separate regime RISK_ON, MIXED, RISK_OFF.
- Sector 1/3/6-month excess return vs NIFTY 500, sector breadth, advance/decline, trend concentration.
- Default long-only cash swing candidates require regime RISK_ON or case-defined MIXED; do NOT assume no winners in RISK_OFF. Test trade frequency, exposures and returns by regime.
- Capture market gap and IV/event risk for next-session execution.

### 2. Relative strength shortlist (top 30)
- Pre-register momentum score: volatility-normalized 6m and 12m returns, monthly rebalance as baseline; compare existing 252-bar return skipping last 21 sessions and 20-day RS improvement.
- Add a distinct RS trend feature (positive slope for 10–20 days vs NIFTY 500). **Don't combine duplicate momentum measures blindly**; test incremental effect.
- Favor liquid names with multiple months of strength and emerging 20/60-day sector leadership rather than only one-day price spikes.
- Keep value-based rankings and features in SQLite; do not expose today's screen as if it were the historical universe.

### 3. Exactly three independently evaluated entry families
A. **EMA trend pullback** (existing): EMA10>EMA30, price>SMA200, EMA10 rising; first/second pullback near EMA10/20, no trend breakdown, strong relative strength.
B. **RS–W%R3–POC value-area reclaim** (existing separate frozen scanner): RS positive, W%R3 oversold then recovers, price regains a *properly calculated* prior-session/rolling volume-profile POC or VAL; POC based on OHLCV estimates must be labeled as **estimated** (true tick volume-at-price not available in EOD).
C. **Larry Williams A/D + Wyckoff BOF/breakout** (existing idea): prior high/resistance swept and reclaimed with close, A/D accumulation divergence, meaningful volume and range contraction/expansion. Distinguish BOF support bounce from valid breakout; test separately.
Each entry family must produce its own `setup_family`, `entry_trigger`, `invalid_level`, `data_time`, `snapshot_version`, `funding_mode` and `expected_horizon`. Do not average scores of incompatible strategies into a mysterious '10/10'.

### 4. Entries and stops as executable hypotheses
- Candidate next-session buy-stop above signal-day high, or prior-close-reclaim trigger, or next-day open only if gap <=2% (existing test policy): compare with realistic broker fills and gap skips. No using unavailable intra-day sequence on EOD signals.
- Structural stop below recent reaction low / BOF low or an ATR-based trailing alternative; no fixed universal 2% stop. Initial minimum reward/risk *screen* e.g. 1.8 or 2.0 to resistance/VAH, but don't treat theoretical target as realized expectancy.
- Time-based exit 10/20 sessions, EMA30 close trail, 3xATR trail, monthly RS deterioration. Test exit methods without tuning to the same sample that chose entries.
- Handle price circuit, gap-through-stop, stop execution failure, liquidity and market impact. Risk cap based on *worst credible adverse gap*, not a guarantee.

### 5. Portfolio-level risk controls
Existing user's desired portfolio baseline: max 4 concurrent positions, at most 2 in a sector, total initial planned risk <=4%, <=25% of capital per position, orders expire after 5 sessions, manually executed. Preserve as a **maximum constraint**, not a target to fully deploy each week.
Conservative research comparator: initial 0.5–0.75% equity risk per cash swing, 2% portfolio risk ceiling, no leveraged MTF until a separate margin-interest, margin-call and gap-loss model passes. Test less/more risk on the same fixed *unlevered* signal set.
Require rising correlation penalty: 4 banking stocks are not diversified simply because they're 4 separate tickers. Measure common industry beta and large sector clusters.
Before scaling exposure, establish whether returns are driven by broad NIFTY rallies rather than stock-selection alpha.

## Scorecard visible in dashboard
```text
EOD 20:00 IST — NIFTY 500 SWING SHORTLIST [RESEARCH]
SYMBOL  RS-RANK  SECTOR-RS  REGIME  SETUP             TRIGGER  STOP   R-TO-TGT  LIQUIDITY
ABC     8/500    +...       RISK_ON EMA10-PULLBACK    Rs X     Rs Y   2.1x      PASS
XYZ    23/500    +...       MIXED   POC-RECLAIM        Rs X     Rs Y   1.8x      PASS
...
SETUP STATUS: WATCH / CONFIRMED ON NEXT BAR / REJECTED
ORDER STATUS: MANUAL ONLY — NOT PLACED
```
No example market prices without independently fetched data.

## Evaluation sequence (pre-registered)
1. Data integrity audit: adjusted daily equities, historical NIFTY 500 membership, delisted firms, corporate actions and costs.
2. Historical 2010-present **where authentic history exists**; split across 2010–2017 development, 2018–2022 validation, 2023–2026 holdout as an initial proposed scheme, *not* dates already proved complete. Alternative rolling walk-forward with fully chronological split.
3. Triple-entry ablation with one common universe, same slippage and costs, identical point-in-time market regime, clear denominators.
4. Compare to NIFTY 500 total-return and simple RS/EMA baseline; report win rate, net R expectancy, profit factor, Sortino, drawdown, time-in-market, exposure by sector, turnover and hit ratio at 1/3/5/10 days.
5. Deflated Sharpe, probability of backtest overfitting / combinatorially symmetric cross-validation for model selection, **without leakage** from overlapping trades; nested research partitions where needed.
6. Paper trade 60–100 signals or at least three market regimes, with full next-session fill audit; thresholds should be pre-registered and adapted to signal scarcity, not a guarantee of external validity.
7. Promotion requires positive net expectancy under realistic+stressed costs and independently inspected failures; preserve original scanner untouched until evidence supports the change.

## Options vs swing: operational separation
- Options: event-level intraday, minutes, extremely latency/premium/IV-sensitive; annualizing daily swing metrics is inappropriate.
- Cash swing: completed EOD input, days/weeks hold, asset adjustments and point-in-time universes are critical; gamma wall concepts do not belong in EOD cash swing ranking absent separate evidence.
- **One shared journal**: `idea_id,setup_family,regime,signal_time,entry_eligibility,risk_R,actual_fill,exit_reason,realized_R,data_quality_flags`.
- Compare *net expected reward per unit research time and capital*; the best trade is often no trade.

## Highest-value implementation step
Audit one FYERS EOD price series against NSE UDiFF + corporate-action data and construct a point-in-time symbol/date/corporate-action table; build a reproducible small historical example before mass-ranking NIFTY 500. Without this, every backtest can be misleading.
