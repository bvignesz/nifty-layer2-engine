# NIFTY Video-Reference Microstructure Terminal — Research & Implementation

Date: 2026-11-06. Scope: preserve the video-style horizontally-scannable readout while using *actual stored FYERS observations*. No orders; no upgrade to validated trades.

## Primary source cross-check

- FYERS official option-chain API: https://fyers.in/api-docs/v3/api/market-data/option-chain/
  * optionchain supplies `oi`, `oich`, `prev_oi`, `volume`, `ltp`, `bid`, `ask`, IV and broker Greeks with `greeks=1`.
  * `timestamp` is used in the implemented FYERS calls to select an **expiry**, not a verified exchange observation timestamp. The option underlying placeholder (`strike_price=-1`) may contain `fp` but is not an independently synchronized forward.
  * The API's OI quantity convention remains to be independently cross-verified before normalizing as contracts vs underlying units.
- FYERS historical data: https://fyers.in/api-docs/v3/api/market-data/historical-data
  * 1m / 3m completed **price** candles possible. Current minute can be partial; enforce bar closure, regular session, contract identity and response timestamps. `oi_flag=1` appends OI where supported.
- FYERS **expired F&O** data: https://fyers.in/api-docs/v3/api/market-data/expired-fo-data/get-expired-fo-data/
  * Supports exact contract 1-minute historical OHLCV plus optional **OI** and **Greeks** where entitlements/availability allow; use `include_oi=1` and `include_greeks=1`, validate `columns` response and `schema_version`, and account for data-plan restrictions. This is a promising pathway for independently replayable 1m rows, not evidence that prior option-chain receipt snapshots were exchange-synchronized.
- FYERS historical research guide: https://fyers.in/api-docs/v3/getting-started/guides/work-with-historical-market-data
  * Verify symbol master, requested time window, missing periods, timestamp correctness, product entitlement, and retain request provenance.
- NSE option chain: https://www.nseindia.com/option-chain
  * NSE's website explicitly labels its volume/OI values in contracts. Broker raw API quantity units are not automatically the same.
- FYERS terminology: https://support.fyers.in/portal/en/kb/articles/what-do-the-different-columns-in-the-fyers-options-chain-mean
  * FYERS' user-facing OI change is since previous trading session, not the same as the difference between adjacent *independent* API captures; cumulative volume must be differenced only on matched continuous counters.
- GEX sign-convention research (not validated for NIFTY): https://papers.ssrn.com/sol3/papers.cfm?abstract_id=7131778
  * Public option OI cannot reveal dealer inventory sign. CE-positive/PE-negative and gamma flip are **scenarios**, not observed dealer positioning or guaranteed hedging flows.

## Video-inspired feature / source / interpretation matrix

| Video display | Repo source | Availability now | Label / constraint |
|---|---|---|---|
| Completed candle time | `futures_data.exchange_at_utc`, future 1m historical endpoint | Only some verified 3m futures bars | Never call a receipt a candle close |
| Observation time | `header_snapshots.ts` | Yes | RECEIPT, IST |
| CE/PE strike walls | `strike_snapshots.oi` with `expiry_date` and CE/PE, by timestamp | Yes, per collected subset | Maximum captured OI, **not** market-wide largest wall |
| Strike wall cut | matched same-symbol wall ΔOI / prior OI | Only if gap 90–360 sec, time/contract aligned | ΔOI proxy; missing otherwise |
| OI strength | successive strike OI change vs rolling comparable baseline | Not built | Require a rolling baseline and warmup |
| Volume strength | cumulative-option-volume increments / time-of-day baseline | Matched incremental volume now; baseline not built | No bid/ask aggressor inference |
| Strike GEX and 1m ΔGEX | `gamma`, `oi`, exact forward, lot-unit convention | Model scenario only; 1m not valid | Broker Greeks; sign/units unverified |
| Seller neutralization | OI/volume proxy | Not directly observable | NEVER state actual seller exit confirmed |
| Writing/exit flow | CE/PE OI differences, premium change | OI deltas available for matched symbols | Use `OI BUILD/CUT PROXY` (not 'writer identified') |
| Futures long/short build | valid *completed* futures OHLCV + OI | 3m history available; terminal shows stored header futures | Only classify after verified comparable futures bars; do not infer actual participants |
| BULL / BEAR verdict | `signals.payload_json.final_verdict` | Yes (legacy hypothesis) | Research bias only |
| Trade decision | `signals.classification` | No Trade from preserved runner | NO TRADE until release/market validation |

## Implemented milestone

New `nifty_l2/microstructure_terminal.py` provides `/microstructure` and `/api/v1/microstructure` on the existing authenticated server:

- Read-only parameterized SQLite, bounded rows by selected IST date; no migrations.
- Per-record side-specific CE/PE OI walls from actually stored strikes, with OI, LTP, gamma retained in JSON.
- Same-contract `ΔOI` and incremental volume only with matching symbol and receipt gap 90–360s; counter resets and missingness show null.
- Stored futures close/VWAP/OI; no imaginary complete futures quadrant.
- Preserved legacy BULL/BEAR research bias, counts and pre-existing GEX scenario; validated action shown as No Trade.
- Clear and separate research-vs-execution cues; no one-minute claims without real candle bars.

To preview after updating the **development copy** and starting a **separately configured test server**, visit `/microstructure`. **Do not switch production to the feature branch without approval.**

```bash
cd ~/nifty-platform-validation
git fetch origin
git switch --detach origin/feat/research-platform-milestones-2-8
PY=/home/ubuntu/nifty-layer2-engine/.venv/bin/python
$PY -m pytest -q tests/test_microstructure_terminal.py
```

## Next implementation gates

1. Add a separate **read-only FYERS expired-contract 1m OHLCV/OI/Greeks probe** with strict schema-version parsing, rate limit and entitlement handling. Audit exact contract (not symbols guessed from date), complete bars and non-overlap in historical replay. Never silently backfill unknown values.
2. Store genuine 1m OHLCV+OI observations in a new versioned research table only after contract/expiry/time alignment and schema test passes, without altering legacy storage or valuation engine.
3. Build honest 1m row correlation: completed **spot/futures candle** + latest receipt-only chain snapshot; never call the two synchronized if they are not.
4. Develop conditional OI speed, wall cut, liquidity and futures quadrants on replayed and prospectively recorded data, with explicit warm-up and missing-data states.
5. Prove OI quantity convention and dealer-sign scenarios, calibrate gamma separately, then add scenario-only GEX and its observed-window changes.
6. Compare video-like alerts with forward outcomes only on leakage-safe walk-forward data, then independently review before enabling anything actionable.
