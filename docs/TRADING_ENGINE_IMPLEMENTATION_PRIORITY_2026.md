# TRADING RESEARCH PLATFORM — Codex implementation backlog (2026-11-06)

This file maps the source-backed proposed methods to **separate, observable and testable** milestones. No order execution; no changes to frozen legacy signal logic; no deployment on AWS before manual acceptance.

Primary methods:
- [Options desk vNext](OPTIONS_DESK_VNEXT_RESEARCH_METHOD.md)
- [Indian swing engine vNext](INDIAN_SWING_ENGINE_VNEXT_RESEARCH_METHOD.md)
- [Video reference and existing FYERS data](VIDEO_MICROSTRUCTURE_DASHBOARD_RESEARCH.md)

## P0: data truth / one-minute historical option replay (NEXT IMPLEMENTATION)
Feature request: add a **read-only** `expired_fo_research_probe` using FYERS official API Get Expired F&O Data, for ONE known expired NIFTY option contract with explicit 1m history, optional OI+Greeks. Verify account plan permits it and obtain exact symbol from broker expired-contract API, no guessed symbols.

Acceptance:
- Exit states `PASS_DATA_AVAILABLE`, `NO_DATA`, `ENTITLEMENT_UNAVAILABLE`, `SCHEMA_CHANGED`, `INVALID_CONTRACT`, `RATE_LIMITED`, `INVALID_TIMESTAMP`, `ERROR`; never turn missing fields into zeros.
- Match response `columns` by name, record schema_version, request and receipt UTC, symbol, date range, completed bar close, tick-spacing, session calendar, OI nonnegative and Greek-null coverage.
- Persist report with atomic create-only private permissions. Raw source data only in secure new files; zero production DB mutation, no token print, no orders.
- Mocked tests for variable column order, absent columns, empty results, pre-market/after-hours bars, duplicate conflicting timestamps, expiry mismatch and missing entitlement; offline main-suite CI green.
- Do not call a historical expired contract result a proof that today's active-option chain exposes synchronized per-minute exchange OI. Compare prospectively where possible.

## P1: options baseline and cost simulator
- Completed-index/futures-bars-only ORB/PDVA/VWAP benchmark before introducing options features.
- Candidate contract selector based on bid/ask, volume, actual expiry, delta range and IV/RV scenario; use exact expired-contract historical premium bars for P&L.
- Cost model with correct effective-date statutory levies, spread, fills/slippage and gap-through-stop; test stressed 2x cost.
- Report (a) directional precision (b) **actual option premium net-R expectancy** (c) max DD (d) no-trade proportion. Distinguish backtest OOS vs future prospective paper.

## P2: wall-cut/OI model with honest receipts
- Use only exact contract identity, matched expiry/strike universe and contemporaneous receipt brackets; no inferred 1m option OI from 3m polling.
- Compare baseline with +OI signal via chronological test. Keep GEX scenarios non-gating until independently verified.
- Important: rising PE OI is **not verified PE-writing** and falling CE OI is **not verified CE short exit**.

## P3: swing source parity and baseline
- Pull point-in-time NIFTY 500 universe and NSE UDiFF bhavcopy, adjustments and corporate actions; independently verify FYERS close/volume parity.
- Rank 6/12-month volatility-normalized momentum then test three independent families: EMA pullback, RS-W%R3-POC, Larry A/D+Wyckoff BOF. No mixing families unless ablation supports.
- Score net-R, alpha vs benchmark, drawdown, sector exposure and actual manual fill outcomes.

## P4: regime + risk + human review
- Add pre-market 5-fingers market profile, opening range, VIX percentile/ΔVIX, scheduled event flag and optional stale FII context.
- Versioned hypotheses; no threshold tuning on OOS holdout.
- Research-only dashboard shows `underlying_bias`, `option_economics`, `data_quality`, `candidate_state` as separate fields; never hide BULL/BEAR or disguise unverified candidates as executable signals.
- Keep max 4 simultaneous cash swings/2 per sector/4% total planned risk as ceilings (not targets). Separate much smaller options risk research budget. No leverage defaults or real orders.

## Review and reporting
- Each change lands as a new isolated PR off latest development branch with pytest + CI, a schema audit, sample redacted evidence, deployment/rollback and an ablation experiment plan.
- Keep `nifty_l2/legacy_engine.py` frozen and the live AWS collector/DB unmodified.
- Prefer to fix correctness and cost first, model complexity second. Deployment acceptance is separate from strategy alpha acceptance.
