# Architecture Decision Record — Home → Pre-market → Greeks → Intraday/1D → Quantum Research

Status: **Research feature branch; NOT an AWS deployment claim**. No automatic orders. This does not replace or modify the frozen original nine-check method.

## Problem corrected

Previously `/` embedded the complete strike-OI snapshot terminal, the original scorecard, automated collector controls, and export workflows. Yet `/desk`, `/microstructure`, `/research`, `/eod` and `/swing` already held near-duplicate views. The owner wants the home screen to contain only FYERS connection/run actions, premarket checklist and news.

| Route | Single responsibility | Retention |
| --- | --- | --- |
| `/` | Broker connect, quote verification, run/stop, premarket checklist, official news | **New lean homepage** |
| `/settings` | FYERS App ID/secret management via CSRF-guarded existing POST | Separated from home |
| `/desk` | CE/PE OI walls, completed futures history, GEX assumptions | Primary Options Desk |
| `/quantum` | Five-stage confirmation: macro/Greek/intraday/daily/review | New Quantum Desk |
| `/swing` | Indian EOD multi-strategy cash equity scanner | Primary Swing Desk |
| `/research` | Original nine-check historic scorecards | Detailed audit view |
| `/microstructure` | Stored per-receipt options wall table | Raw diagnostic view |
| `/strike-terminal` | Historic strike-snapshot tables, filters, exports | Archive, **removed from home** |
| `/eod` | Original EOD CSV research legacy page | Compatibility/archive |
| `/validation` | Recorded research integrity | Diagnostic |
| `/api/v1/quantum` | Research-only structured quantum state | New JSON endpoint |

**No destructive file deletion:** `terminal_ui.py` still powers snapshot archives, `research_pages.py` still powers legacy deep links and tests. Deleting either would break existing users. Remove dead assets only after dependency tests and a reviewed PR. Homepage no longer executes redundant `snapshots()`/strike table generation.

## The correct institutional-style workflow

### Stage 0: Confirm market session
The exchange calendar is a blocking gate. Example: **10 November 2026 is a listed equity/F&O trading holiday**. This is not a bearish prediction; market status is CLOSED and decision is IGNORE. Calendar must be reviewed after 31 December 2026.

### Stage 1: Pre-market context (before opening)
Nine checklist fields cover GIFT gap, global risk, India VIX, prior POC/VAH/VAL, FII positioning, event calendar, news risk, futures premium and session status. News sources are RBI and PIB RSS, explicitly downloaded through `nifty_l2.premarket_news`; NSE RSS page is linked for manual inspection. News headlines are **never** treated as bullish/bearish signals without independently validated measurements.

`nifty_l2/preopen_context.py` evaluates *five separate source-dated measurements* in `web-runtime/preopen-signals.json`: `gift_gap_pct`, `global_futures_pct`, `vix_change_pct`, `fii_futures_ls_ratio`, `gift_vs_previous_value_area_pct`. The 4-of-5 BULL/BEAR rule is a **research hypothesis**, not a proven statistical edge. All five inputs require explicit timestamps and source review. Missing/stale fields, high-impact event, exchange holiday or mixed evidence = IGNORE. FII is previous-session context; not a current-minute FII trade.

### Stage 2: Option-contract economics and Greeks
Must use real exact contract, correct expiry, actual quote time, verified delta/gamma/IV, half-spread, liquidity and risk budget. CE/PE wall data are 3-minute **receipt** snapshots; they cannot be relabeled exchange-synced one-minute option OI. Signed GEX is dealer-position scenario, not observed dealer books. If any required field is unverified, contract selection remains unavailable. Original read-only FYERS collector is unchanged.

### Stage 3: Intraday nine-checks
The original nine checks are for option-chain and intraday microstructure. Their outputs remain stored in the same schema; source clock/option-chain observations are not automatically promoted to validated trade evidence. No new speculative check numbers were inserted into the frozen engine.

### Stage 4: **Separate daily nine-factor confirmation**
`nifty_l2/daily_alignment.py` computes nine completed **previous session** price/regime factors from 221+ actual verified EOD bars for NIFTY and a chosen verified benchmark. These are NOT the original nine option-chain checks: (1) close > EMA10; (2) EMA10 > EMA30; (3) close > SMA200; (4) EMA10 rising over 5 days; (5) close > prior 20-day midpoint; (6) 20-day relative strength vs supplied benchmark; (7) Larry Williams A/D increasing over five days; (8) close > prior close; (9) bullish daily candle. At least 7/9 positives produces BULL daily context, at least 7/9 negatives produces BEAR daily context; otherwise MIXED. These thresholds must be backtested, including bear-side asymmetry.

EOD JSON input must have `index_bars` and `benchmark_bars`, each at least 221 ascending completed bars with `source: VERIFIED_EOD`, `bar_status: COMPLETED`, ISO date, OHLCV. A source label alone does not authenticate broker data, so operator must check sources and corporate actions. Save to `~/.config/nifty-layer2/web-runtime/daily-context.json` mode 0600. A current-day partial candle is explicitly rejected; the model is **prior day only** and independent of intraday wall logic.

### Stage 5: Quantum final research desk
`/quantum` shows five stages. `alignment_gate` requires matching BULL/BEAR from verified premarket, previous daily context, independently verified completed intraday checks and a fresh verified contract Greeks context. Any conflicting/missing layer => **IGNORE**. Even all-aligned outcomes say `BULL WATCH` or `BEAR WATCH` and `trade_allowed: false`, not "BUY".

Current `/quantum` intentionally does not promote the legacy intraday nine checks or optionchain receipt-time quotes to `VERIFIED`. Those require an audited data-provenance layer with genuine per-contract exchange timestamps and realistic option costs. **Do not confuse the presence of the UI with live evidence completion.**

## Deploy safely to AWS (not yet executed here)

1. Make SQLite backup, enforce Basic Auth on the HTTPS dashboard (your earlier documentation showed `NIFTY_WEB_REQUIRE_LOGIN=0` — unsafe for a privileged research-control website). Keep FYERS secrets and token server-side mode 0600.
2. `cd ~/nifty-platform-validation && git fetch origin && git switch --detach origin/feat/trading-platform-vnext-phase1` in **dev worktree only**, then `python -m pytest -q`. Do not switch the live service without a reviewed fixed commit and rollback.
3. Test `/ `, `/desk`, `/swing`, `/quantum`, `/research`, `/strike-terminal` behind your protected HTTPS proxy. All action routes retain CSRF and Origin checks.
4. To refresh official news *manually* without making network calls inside the web process: `python -m nifty_l2.premarket_news --directory ~/.config/nifty-layer2/web-runtime`. The fetch returns an error without modifying existing brief if either source is unreachable; verify the external RSS URL access and formatting on AWS.
5. Optional automation templates are `deployment/nifty-premarket-news.service.example` and `.timer.example`. Inspect environment paths before installation, do not autoenable without testing. RSS fetches are confined to pinned RBI and PIB URLs.
6. Load audited premarket checklist, previous day's completed EOD candles, and current externally verified regime context; verify `/api/v1/quantum` returns **IGNORE** until every layer is properly validated.
7. Keep the existing production option-collector and swing EOD scheduler unchanged until verified new inputs and service units are accepted.

## Known gaps

- No authenticated automatic GIFT NIFTY, global index, India VIX, FII and real news-to-event-calendar data adapters for all nine checklist fields.
- No fully validated completed intraday option-exchange OI timestamps, seller identity, or real dealer position.
- No genuinely verified intraday nine-check/Greek-layer promotion in the Quantum gate. It is intentionally fail-closed.
- Real multi-session historical evaluation and option execution-cost backtest needed before BUY CE/PE suggestions or an actual statistical confidence value.
- Never delete older UI/library modules until existing imports, service files, migrations, tests, and rollback dependencies are audited.


## FYERS previous-session daily data — exact runnable adapter

FYERS documents daily `D` candles in at-most-366-day request windows.
`nifty_l2/daily_fyers_collector.py` chunks 520 calendar days into <=331-day
requests for both the NIFTY index and the **exact operator-verified benchmark**
and refuses missing/corrupted/old data. It drops current-day candles, requires
at least 221 historical sessions, aligns the latest session with the verified
NSE exchange calendar, and stores `daily-context.json` atomically (0600).

Run the adapter during a valid server-maintenance window with your existing
private broker token, after verifying the benchmark symbol is actually
supported by FYERS. The example label is intentionally a placeholder:

```bash
cd ~/nifty-platform-validation
PY=/home/ubuntu/nifty-layer2-engine/.venv/bin/python
$PY -m nifty_l2.daily_fyers_collector --live \
  --index-symbol NSE:NIFTY50-INDEX \
  --benchmark-symbol 'NSE:EXACT_VERIFIED_BENCHMARK_INDEX' \
  --asof 2026-11-10 \
  --token-path ~/.config/nifty-layer2/fyers-token.json \
  --output ~/.config/nifty-layer2/web-runtime/daily-context.json
```

`2026-11-10` is a trading holiday; the last completed regular session should
be 9 November 2026. Replace `--asof` with the actual IST current session
date for ordinary operation. A successful FYERS history response is **not**
proof of strategy profitability or that volume/adjustment conventions match
another source. The collector is one-shot; nothing installs or schedules it
automatically.

## News refresh (official feeds only)

```bash
$PY -m nifty_l2.premarket_news \
  --directory ~/.config/nifty-layer2/web-runtime
```

This fetches the pinned official RBI press-release RSS and PIB RSS into the
private premarket brief. Headlines are displayed as links with publication
timestamps, **not** classified into bullish/bearish signals. It refuses
redirects and unapproved linked domains. Optional scheduling templates:
`deployment/nifty-premarket-news.service.example` and
`deployment/nifty-premarket-news.timer.example`.
Do not install the templates without adjusting the paths and testing DNS/TLS,
feed format and the existing dashboard authentication.

## Pre-open source input format

`preopen-signals.json` is an **operator-verified, timestamped** JSON object
stored in the private `web-runtime` directory. It contains
`date_ist` and five objects:
`gift_gap_pct`, `global_futures_pct`, `vix_change_pct`,
`fii_futures_ls_ratio`, `gift_vs_previous_value_area_pct`.
Each object has `value`, `observed_at_utc` and
`source_verified: true`. The software cannot attest the truth of a
user-provided `source_verified` flag, so underlying broker/economic source
records must be audited first. An invalid, stale or missing input yields
IGNORE. On holidays the engine marks exchange closed.

For live `market-regime.json` context, the earlier
`nifty_l2.premarket_regime.classify_regime` may be used after the opening
range is complete with verified fresh data. That **is not** a genuine pre-open
prediction and is separately identified in the Quantum desk.
