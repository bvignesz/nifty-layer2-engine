# Full trading-platform implementation program

Approved scope: **implement all research recommendations**, without treating them as proven strategies, modifying the frozen nine-check engine, enabling automatic orders, or deploying without human acceptance.

Existing details: 
- [Options vNext method](OPTIONS_DESK_VNEXT_RESEARCH_METHOD.md)
- [Swing vNext method](INDIAN_SWING_ENGINE_VNEXT_RESEARCH_METHOD.md)
- [Prioritized Codex backlog](TRADING_ENGINE_IMPLEMENTATION_PRIORITY_2026.md)
- [Video terminal specification and provenance](VIDEO_MICROSTRUCTURE_DASHBOARD_RESEARCH.md)

## Tracking and release sequence

| Track | Issue | Evidence required |
|---|---|---|
| P0: 1m archived options Greeks, OI, schema and timestamps | #8 | Genuine contract-level market observations, entitlement and completed-bar audit |
| P1: Five Fingers opening market profile, VIX and events | #9 | Reproducible historical price/volume profile and pre-market timestamps |
| P2: CE/PE wall and futures interpretations | #10 | Same-contract expiry alignment, measured OI changes, replay and ablation |
| P3: Options contract, costs and portfolio risk | #11 | Actual bid/ask and fill/cost sensitivity, premium-loss model, verified contract lot |
| P4: Indian cash equity swing factors and patterns | #12 | Point-in-time constituent universe and audited corporate-action adjusted data |
| P5: Purged labels, replay, statistics and shadow XGBoost | Planned | Chronological tests, post-cost expectancy and prospective paper evidence |
| P6: Full video-style dashboard, health and Telegram research alerts | Planned | Source-visible cell provenance, permission/privacy, stale states and complete screenshot audit |
| P7: Security and manual release review | Planned | No regressions; full rollback; no implicit live deployment |

## Phase 1 implemented

`nifty_l2/research_candidate_gate.py` implements an **independent, never-ordering** decision aid with two separate steps:

1. `assess_underlying_bias`: research-only BULLISH/BEARISH/MIXED hypothesis based on pre-gated verified completed futures evidence and explicit score thresholds. Does not modify nine checks or claim score probability calibration.
2. `assess_option_candidate`: separate quote-age, contract identity, bid/ask, absolute delta, expiry, verified lot, market evidence and stress-risk budget validation. The worst-case simulated exposure per purchased lot is no less than **full option premium** (rather than relying on a hypothetical stop execution). Outputs `RESEARCH_CANDIDATE` or `IGNORE`, never a trade order.

Research-only default exploration parameters: quote age <= 15 seconds; relative bid/ask spread <= 1% mid; |delta| between 0.40 and 0.65; DTE >= 1 day; 0.25% model equity risk per idea, 0.75% daily new-risk budget, <=2 modeled trades/day. **No parameter is an empirically established optimal value**. All can be changed only by a separate versioned experiment.

Limitations: no realized slippage/tax/IV-decay model yet, no FYERS read integrated here, no daily realized P&L. Risk ceilings deliberately result in IGNORE for small accounts when a full option lot cannot fit the conservative risk budget. These are simulation labels, not personal recommendations.

## Next mandatory component

**Read-only one-minute expired F&O option history probe**, tracked by issue #8. Verify FYERS contract discovery, active API version, fields, permissions and timestamps *before* building it. Protect token, use a unique private immutable report file, and fail closed on missing OI/Greeks. Then implement baseline completed futures, price-only labels and a full actual-options-cost backtest.

Only after this data acceptance: multi-strike OI velocity/volume persistence, independently tested GEX sensitivity, Five Fingers regime overlay, the separate NIFTY500 EOD swing strategy study, and shadow XGBoost.

## Production / acceptance

- This work belongs to an isolated branch based on the open draft PR #6. Do not merge main automatically.
- Do not run new live broker requests in CI.
- Do not rewrite the current `nifty_l2/legacy_engine.py`, existing SQLite, AWS collector, FYERS auth or dashboard.
- Require green automated tests and human review of market evidence, realistic fills and model promotion. Existing successful CI is **software verification only**.
