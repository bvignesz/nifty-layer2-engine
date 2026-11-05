# Stage 2–8: historical quality + live FYERS acceptance (PRE-INSTALL)

This runbook is intentionally **not a deployment procedure**. Use it on AWS only after the offline GitHub CI tests are green. Do not merge PR #6, restart systemd, update working production checkout or touch live tokens.

## Offline tests

GitHub Actions runs the complete repository test suite on Python 3.12 and includes the frozen nine-check source hash. Offline mocked FYERS success proves request orchestration but **does not prove** that your real FYERS account has historical OI access or that it returns correct data.

## AWS real-data evidence (only after manual command)

Use a separate worktree and the existing virtual environment. This keeps your production web/collector files intact.

```bash
git -C ~/nifty-layer2-engine fetch origin
git -C ~/nifty-layer2-engine worktree add ~/nifty-platform-validation origin/feat/research-platform-milestones-2-8
cd ~/nifty-platform-validation
PY=/home/ubuntu/nifty-layer2-engine/.venv/bin/python
$PY -m pytest -q
mkdir -p ~/nifty-validation-reports
chmod 700 ~/nifty-validation-reports
```

Run the historical audit against the actual SQLite storage file **read-only**. Do not copy database content into a public bug report:

```bash
$PY -m nifty_l2.historical_validation \
  --db /home/ubuntu/.config/nifty-layer2/web-runtime/research.db \
  --report ~/nifty-validation-reports/historical.json
```

It reports missing exchange timestamps, stale/gapped observation chains, invalid or orphan strikes, incomplete directional nine checks, and suspiciously constant gamma. It will classify data as `REQUIRES_MARKET_VALIDATION` when the database lacks independently timestamped exchange observations; this is **expected** in the current baseline.

Run the FYERS integration test **after reconnecting FYERS if the token has expired**. It requires the existing private 0600 token file. There is no order placement, token renewal, token printout, or collector modification. The test makes at most 7 read-only requests when a future is supplied (verify account rate limits).

```bash
$PY -m nifty_l2.fyers_integration_probe --live \
  --token-path /home/ubuntu/.config/nifty-layer2/fyers-token.json \
  --equity-symbol NSE:TCS-EQ \
  --future-symbol NSE:NIFTY26NOVFUT \
  --report ~/nifty-validation-reports/fyers-probe.json
```

**Important:** `NSE:NIFTY26NOVFUT` is an *example*; replace it with the actual currently trading contract from your approved FYERS symbol master. Do not blindly reuse a guessed symbol. The probe does not refresh tokens or place orders.

Inspect the resulting **status summaries only** (avoid sharing credentials or raw market response files). The probe intentionally marks `market_data_verified=false` even when every API request succeeds. Validated exchange timestamps and corporate-action equivalence are separate tasks.

## Consolidated release gate

The gate requires `historical.json` and `fyers-probe.json`, plus separately approved audit evidence for:
- `eod-parity.json`: matching adjusted-price/corporate-action handling and sample daily/15m OHLCV for reference symbols;
- `greeks-audit.json`: actual OI units, gamma/IV consistency, expiry scaling and scenario assumptions;
- `outcome-audit.json`: verified exchange candle close stamps and held-out future-label provenance, without lookahead;
- `security-audit.json`: browser authentication, OAuth/CSRF isolation, backup/rollback and exposure review.

Passing a mocked test is **not** the required evidence for these audits; review independently before writing `{"verified":true}`.

```bash
$PY -m nifty_l2.release_gate \
  --historical ~/nifty-validation-reports/historical.json \
  --fyers ~/nifty-validation-reports/fyers-probe.json \
  --report ~/nifty-validation-reports/release-gate.json
```

With outstanding audit files absent or incomplete, this **must say BLOCKED**. That is correct behavior, not a software failure.

## Deferred: controlled production installation

Only after all required gates are independently verified: record production systemd unit definitions, backup SQLite via the SQLite backup API, record checkout SHA, test APIs/UI with a copy of the DB, then release only the approved commit to the web service with rollback, **without restarting the NIFTY collector or rewriting historical research**.

No installation or merge is authorized by this development/validation runbook.

## Historical futures persistence correction (2026-11-05)

The AWS validation found 111 research events and 111 missing event-level exchange timestamps; `futures_data` had 0 rows. This is **not** enough to claim a missing futures feed: the existing `runner.evaluate_once` archives FYERS calls in `events.payload_json` but (unlike `replay.replay`) did not populate `futures_data`.

The development branch now calls `persist_futures` inside the existing atomic research transaction to persist the **latest actual completed, bounded-age futures candle** with its source-provided candle-start UTC timestamp and OI. If no eligible completed candle with OI exists, no row is written. It **does not** set `events.exchange_at_utc` from a futures candle, and it never changes the nine-check valuation result.

Inspect existing archived data **read only**:

```bash
cd ~/nifty-platform-validation
PY=/home/ubuntu/nifty-layer2-engine/.venv/bin/python
$PY -m nifty_l2.futures_archive_audit \\
  --db /home/ubuntu/.config/nifty-layer2/web-runtime/research.db \\
  --report ~/nifty-validation-reports/futures-archive-audit.json
```

To assess recoverable futures records, use **copy-only** normalization (never live DB):

```bash
$PY -m nifty_l2.futures_copy_backfill \\
  --source /home/ubuntu/.config/nifty-layer2/web-runtime/research.db \\
  --output ~/nifty-validation-reports/research-futures-copy.db
```

This second command creates a new private SQLite copy and refuses overwrites. It does NOT install, merge, restart web/collector or mutate production. Neither backfill nor futures provenance can retroactively supply a valid option-chain exchange timestamp. The six historical collection gaps remain visible and are excluded from comparable three-minute change calculations. Existing market-quality gates remain blocked until trustworthy exchange-time evidence is available.


## Next diagnostic stage: option-chain time provenance and live futures OI

The original AWS SQLite audit showed 111 research events, all without event-level verified exchange time. The first futures recovery copy retained 104/111 eligible completed futures observations; seven manual observations were after NSE session, so the after-hours rejections must **not** be bypassed.

Two additional **read-only tools** were added:

```bash
cd ~/nifty-platform-validation
git fetch origin
git switch --detach origin/feat/research-platform-milestones-2-8
PY=/home/ubuntu/nifty-layer2-engine/.venv/bin/python
$PY -m pytest -q tests/test_market_provenance.py
```

**1) Audit option time-field provenance without modifying the production DB:**

```bash
$PY -m nifty_l2.option_time_audit \
  --db /home/ubuntu/.config/nifty-layer2/web-runtime/research.db \
  --report ~/nifty-validation-reports/option-time-audit.json
```

This counts only candidate timestamp keys in recorded FYERS option-chain **legs**, checks parseability and plausibility, and explicitly leaves `exchange_timestamp_verified=false`. A broker response may carry a last-trade time without providing an exchange-level OI snapshot time. Neither the candidate key name nor a plausible epoch is sufficient to claim option-chain freshness.

**2) Probe real FYERS 3-minute historical futures OI.**

The archived calls consistently used `NSE:NIFTY26NOVFUT`, but validate that this is still the relevant active contract when running the command. This test uses a saved private token, makes one read-only FYERS history request, and does **not** place orders:

```bash
$PY -m nifty_l2.futures_oi_probe --live \
  --token-path /home/ubuntu/.config/nifty-layer2/fyers-token.json \
  --future-symbol NSE:NIFTY26NOVFUT \
  --report ~/nifty-validation-reports/futures-oi-live.json
```

The futures test detects missing/zero OI, duplicate timestamps, unfinished candles, invalid OHLCV and same-day interval discontinuities. A passing futures response still does **not** validate option-chain timestamps or establish that gamma dealer inventory is observable.

**Deployment remains blocked** until the separate EOD parity, Greeks/OI units, outcome and browser/security evidence gates are satisfied. Do not mark these audit files `verified=true` without independent evidence. All production collector and legacy nine-check calculations remain unchanged.

## Real AWS result: 5 November 2026 broker futures OI probe

Live broker history for `NSE:NIFTY26NOVFUT` returned 903 rows, 896 completed/session-eligible rows, 768 unique timestamps, 128 repeated timestamps, 7 session exclusions, and 0 unique-timestamp spacing gaps. All 896 accepted rows carried positive OI. Separately, 5,328 archived option legs contained **no recognized candidate exchange-time keys**; they remain unverified. Source option-chain OI observations must never be relabeled as completed 3-minute candles.

The updated probe reports `identical_duplicate_rows` versus `conflicting_duplicate_rows` (including OI differences) and bounded `after_session_samples_ist`. A different OHLCV/OI payload for the same bar start returns `FUTURES_HISTORY_CONFLICTS_REVIEW_REQUIRED` and a nonzero exit code, rather than silently choosing one row. No duplicate is automatically a verified second observation.

NSE equity **derivatives** regular trading closes at 15:40 IST, per NSE market timings (https://www.nseindia.com/static/market-data/market-timings); the NSE equity cash close is different. Keep F&O session checks and cash-session checks separate.

After updating the development worktree, run the probe with a **new output name** (reports are create-only):

```bash
cd ~/nifty-platform-validation
git fetch origin
git switch --detach origin/feat/research-platform-milestones-2-8
PY=/home/ubuntu/nifty-layer2-engine/.venv/bin/python
$PY -m pytest -q tests/test_market_provenance.py
$PY -m nifty_l2.futures_oi_probe --live \
  --token-path /home/ubuntu/.config/nifty-layer2/fyers-token.json \
  --future-symbol NSE:NIFTY26NOVFUT \
  --report ~/nifty-validation-reports/futures-oi-duplicates-reviewed.json
```

The command remains **read-only** and makes one broker history request. No production deployment has occurred.

## 5 November 2026 duplicate conflict investigation — second live probe

The user's revised FYERS history probe confirms **128 duplicate bar-start rows**, split into **63 identical** and **65 conflicting** full OHLCV/OI signatures. These 65 are NOT necessarily 65 OI disagreements; differences may be in candle price, volume, or OI. Six tests for the prior probe passed on AWS. The 7 excluded bars are timestamped 15:39 IST: a full 3-minute candle would end at 15:42, after the configured NSE F&O 15:40 close. The option-chain audit found zero recognized candidate time fields across 5,328 legs and remains unverified.

The refined probe now reports `conflicts_price_ohlc`, `conflicts_volume`, `conflicts_oi`, `conflicts_only_oi`, `conflicts_only_volume` and up to eight bounded `conflict_examples` with numeric OI/volume pairs. **Do not automatically keep first, keep last, average, or merge conflicting historical OHLCV/OI rows.** Fail closed for backtest labels/training until a documented broker-source correction policy is independently tested.

Run from isolated worktree after fetching branch, using a NEW output file:

```bash
cd ~/nifty-platform-validation
git fetch origin
git switch --detach origin/feat/research-platform-milestones-2-8
PY=/home/ubuntu/nifty-layer2-engine/.venv/bin/python
$PY -m pytest -q tests/test_market_provenance.py
$PY -m nifty_l2.futures_oi_probe --live \
  --token-path /home/ubuntu/.config/nifty-layer2/fyers-token.json \
  --future-symbol NSE:NIFTY26NOVFUT \
  --report ~/nifty-validation-reports/futures-oi-conflict-breakdown.json
```

No live trading signals, production database changes or installs are authorized by this audit.

## Option OI timing and GEX assumptions — 2026-11-05

Authoritative FYERS Option Chain documentation:
- https://fyers.in/api-docs/v3/api/market-data/option-chain
- https://fyers.in/api-docs/ai/skills/option-chain/
- https://fyers.in/community/t/option-chain-update-frequqency/21050

**Critical:** FYERS option-chain request `timestamp` means the selected **expiry epoch**, not a historical exchange-time observation. FYERS support indicates that a time series must be stored locally or obtained through a separately suitable feed. Existing option-chain legs lacked exchange-time keys in all 5,328 inspected archived option legs. No historical 1/3-minute exchange-confirmed option OI candle can be retroactively produced from these snapshots.

`nifty_l2.option_observation_gate` exposes `bracket_snapshot`, `snapshot_from_response`, and `comparable_pair`. A separately instrumented collector can record **request start and response completion** from monotonic wall clocks for each option-chain API call, expiry ID, contract symbol, and OI. Only same-expiry, same-universe, non-overlapping receipt-time captures separated by 90–360 seconds with reasonable request latency can produce `COMPARABLE_RECEIPT_DELTA_UNVERIFIED`. No exchange-time bar, seller position, or intraday exchange OI freshness is implied. This module is research scaffolding; it is NOT attached to the live legacy runner.

`nifty_l2.gex_assumption_audit` estimates convention-specific signed OI GEX using FYERS-provided broker gamma where present and reveals the absence of direct dealer positions and independently verified option OI update times. Its `oi_basis` must be explicitly verified as **underlying units** vs **contracts** before using the numeric output. The engine's frozen default `NIFTY_LOT_SIZE=75` needs contract-specific verification: NSE/FAOP/70616 revised NIFTY standard lot from 75 to 65 for eligible contracts. Do not blindly replace lot size across historical/old contracts without contract-master validation.

The legacy `net_gex_cr` multiplies gamma × received OI × F² × 0.01 / 1e7, with **CE positive / PE negative** convention; dealer actual net gamma is unknown. Also audit whether the legacy `get_greeks_safe` generated fallback gamma (broker gamma absent) and whether the selected ATM window represents the total listed option market. Until these issues are independently resolved, **label GEX as a partial-chain signed-OI scenario, not true dealer gamma exposure**. Zero-gamma flip is a model scenario, not observed dealer flow.

Run read-only historical GEX audit in isolated AWS worktree:

```bash
cd ~/nifty-platform-validation
git fetch origin
git switch --detach origin/feat/research-platform-milestones-2-8
PY=/home/ubuntu/nifty-layer2-engine/.venv/bin/python
$PY -m pytest -q tests/test_option_timing_gex_assumptions.py
$PY -m nifty_l2.gex_assumption_audit \
  --db /home/ubuntu/.config/nifty-layer2/web-runtime/research.db \
  --lot-size 65 \
  --report ~/nifty-validation-reports/gex-assumptions.json
```

Keep the original historical DB, frozen nine-check code, and FYERS token unchanged. This audit does not certify GEX accuracy or authorize deployment.

### Clarification from original source audit

The legacy `net_gex_cr` formula does **not** multiply by `NIFTY_LOT_SIZE`; it treats the incoming `oi` number as underlying-equivalent quantity. The frozen default `75` affects other contract-quantity calculations and must be checked, but **merely changing the lot environment variable to 65 does not itself correct GEX**. `compute_swept_gamma_flip_scenario(..., lot_size)` accepts a lot-size argument yet currently computes its grid directly from raw OI without using that argument. Accordingly the critical GEX issue is determining what units FYERS `oi` represents and validating input gamma and contract identity.

`get_greeks_safe` substitutes a Black-style modeled gamma if broker gamma OR delta is zero. A broker-gamma-only audit cannot certify that every *legacy* output used broker gamma. Before publishing modeled dealer hedging, separately compare raw vs transformed Greeks and instrument multiplier; price-based gamma reprojection requires a validated time-to-expiry, dividend/rate convention, and specified price underlying.
