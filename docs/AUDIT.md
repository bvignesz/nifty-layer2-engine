# Notebook and repository audit — 2026-11-03

Scope: `final.ipynb` (all six cells, including saved outputs), `layer2`, and both commits reachable from all fetched refs. Baseline HEAD: `e6ae4b24460dfdd2ddd14a7fe89d077c5f3e134e`. `git fetch --all --tags` completed. This cannot cover inaccessible/deleted remote objects, forks, caches, or private refs. Machine-readable line inventory and redacted findings: `audit-inventory.json`.

## Credentials — rotation required before live use

FYERS client ID and app secret appear as literal environment-variable defaults in cell 4; the access-token assignment itself is a paste-in placeholder. Saved authentication output contains a JWT-shaped token. Treat the app secret, access tokens and exposed authorization artifacts as compromised. The identifier itself is not a password, but its associated credentials require rotation. Token validity was not tested and no exposed credential was used. Telegram token/chat ID are placeholders in the inspected history; no literal Telegram bot credential was found.

Working notebook credential assignments now read environment variables and saved cell outputs are cleared. This does **not** remove past exposure. Rotate the FYERS app secret, revoke/regenerate the tokens through FYERS, and review FYERS app activity. Do not send credentials in chat or commit them. Any subsequent Git history cleanup must follow rotation and coordinate with clone owners; history was not rewritten or pushed here. Drive data was not accessed or modified.

## Every cell

| Zero-based cell | Contents | Finding |
|---|---|---|
| 0 | Colab badge | No analytical logic or writes |
| 1 | pip upgrades | Unpinned FYERS/FastAPI/pandas/scipy stack; package-install output |
| 2 | pip bottleneck upgrade | Duplicate setup |
| 3 | Installation, cloudflared download, Drive mount | Writes executable to `/usr/local/bin/cloudflared`, changes permissions, mounts `/content/drive`, creates Drive output directory |
| 4 | FYERS authentication, configuration, Telegram settings | Exposed FYERS values and saved auth output; writes process environment; interactive daily-token flow unsuitable for unattended service |
| 5 | 2,013-line engine, separate auction research, SQLite, CSV, UI, tunnel, loop | Calculations mixed with persistence, network I/O and import-time startup |

## Storage and side effects

Cell 3 and cell 5 both set `/content/drive/MyDrive/Nifty50_Option_Engine` and create it. Cell 5 sets these paths:

| File | Behavior | Contents / loss risk |
|---|---|---|
| `nifty_oc_history.db` | SQLite `header_snapshots`, `strike_snapshots`; insert-or-replace | Header PK is receipt epoch seconds. Strike PK is epoch/strike/type; no instrument/expiry in strike PK. No raw response archive, WAL policy, outcome tracking or backup |
| `nifty_live_chain.csv` | Replaced every evaluation | Paired CE/PE legs, prices, OI, Greeks, strike GEX; older versions unavailable unless separately retained |
| `nifty_6check_scorecard.csv` | Replaced every evaluation | Actually **nine** checks; no capture timestamp; cannot reconstruct past scorecards from its current version |
| `nifty_signals_log.csv` | Header on creation; append and fsync | 27 columns, two sets of nine pass flags, spot/futures/VIX/GEX/walls/research trade plan; no explicit final-verdict column |
| `nifty_layer2_corrected_audit.csv` | Header on creation; append and fsync | Verdict, scores/pillars, vetoes, freshness, exposures and contract |

Cell 5 calls `os.sync()` after logs. No JSON file logger or `json.dump` operation exists in the baseline notebook. JSON is used for API payloads/responses, FastAPI responses, TradingView input and Telegram requests. FYERS SDK internal logging is unspecified (`log_path=""`); the new offline package does not load that SDK. The notebook launches a public Cloudflare tunnel and can send Telegram alerts. Neither side effect is retained in the new runtime.

## Engine input/output contract

Inputs include receipt clock; active index and strike step; lot size; minimum DTE; risk/spread/stop configuration; nine hypothesis thresholds; FYERS expiry list and option chain (underlying LTP, CE/PE symbol, strike, bid/ask, LTP, OI, OI change, cumulative volume, optional Greeks); India VIX and percentage change; five constituent quotes and VWAP; current/next-month futures quote candidates; three-minute futures OHLCV/OI history; preceding SQLite headers/strikes; optional TradingView side, spot stop and target. The target argument is accepted but does not affect the calculation in the baseline. Separate auction research uses 12 days of five-minute spot OHLCV history.

| Check | Inputs | Original calculation / output |
|---|---|---|
| 1 Wall ratio + price | ATM ±3 strikes' OI, walls, futures price/change | PE/CE or CE/PE ≥1.20 plus price confirmation |
| 2 Opposing cuts | Fixed wall OI at t,t−1,t−2, adjacent strike | Current cut ≤−1.20%, prior cut <0; migration/reduction annotation |
| 3 Supporting speed | Positive dOI history, near-strike dOI, option LTP, futures change | Signed historical/fallback mean; ≥1.40× plus writing corroboration |
| 4 Churn | Three-minute cumulative-volume difference and dOI, lot size | Volume lots / absolute dOI lots ≤12, minimum 25 dOI lots |
| 5 Futures/breadth | Futures close/VWAP, five weights, trigger side | Direction agrees with normalized breadth ≥0.55 |
| 6 Futures quadrant | Futures price/OI changes, ATM IV change, VIX percentage | Directional quadrant with asymmetric IV/VIX bounds |
| 7 Fixed pivot flip | Previous spot, fixed-strike OI/volume and prices | Two-observation OI persistence, price crossing and ≥1.20× volume |
| 8 Scenario exposures | OI, model Greeks, futures price, wall cuts | Signed OI GEX and swept gamma-flip estimate plus wall-break alternative |
| 9 Migration/clock | Fixed-strike dOI, opening gap, IST clock | Migration with gap corroboration; 09:20–15:15 gate |

Outputs: eighteen directional pass/fail results; raw bull/bear scores /9; four grouped pillars; contradiction/veto reasons; BULL/BEAR/NO TRADE verdict; walls/ATM ownership/migration; scenario GEX/VEX/CEX/flip; price/VIX/breadth metadata; research option contract, stop/size/risk; auction TPO/VRZ/BOF research state; database and CSV records; mobile HTML and webhook JSON. No order-placement call was found. Check scores alone are not the final decision: freshness, clock, pillars and contradictions also gate it. See baseline final-decision block for exact expressions.

## Corrections required before collector operation

1. `sleep(180)` drifts, runs overnight/weekends/holidays and starts mid-window. No authoritative session calendar or special-session handling exists.
2. Latest futures candle can be incomplete; timestamp age accepts future epochs. Historical fallback can mark old futures fresh and substitute spot movement for futures movement.
3. Option-chain and constituent exchange timestamps are not validated. Breadth “fresh” means enough weight is present, not that quotes are fresh.
4. Two prior snapshots have only maximum-age bounds, no 180-second interval requirement, same-session requirement or guaranteed fixed-strike coverage. Repeated webhook calls can masquerade as three-minute observations. Historical baseline is only the last 20 same-expiry snapshots, not a robust multi-session time-of-day baseline.
5. Futures identity is not persisted in the analytical cache; rollover can mix contracts. Rollover chooses any positive quote in guessed current/next-month symbols, not the verified exchange contract master. Lot size, weights and expiry assumptions require dated reference data.
6. Missing OI/volume/Greeks frequently become zeros or model estimates. Partial option chains can trigger missing ATM-leg errors. OI/volume contract-versus-underlying units need confirmation from actual FYERS responses.
7. GEX is a signed-OI **scenario**, not measured dealer positioning. Model Greeks, rates, DTE rounding and gamma-flip extrapolation need empirical review; unchanged in replay.
8. Minimum lot count can exceed the stated risk budget. Trade-plan text is research output; live-order capability must remain absent.
9. Public unauthenticated webhook/mobile endpoints, global mutable state, HTML interpolation, concurrent polls and stale scorecard retention on error are inappropriate for production.

## Changes and preservation evidence

`legacy_engine.py` is generated from the analytical cell by `scripts/extract_engine.py`. The nine checks, thresholds, aggregation, Greeks and auction formulas remain AST-equivalent after explicitly removing CSV writes, `fsync`/global sync, internal commit and Telegram dispatch. Colab setup, credentials, public web server, tunnel and infinite loop are not extracted. SQLite access is injected into a single outer replay transaction. Each replay receives a fresh module and a strict recorded-response client; no FYERS network client is available.

These defects are **not silently corrected in the legacy replay**. Its original verdict remains inspectable in signal payload JSON; the validated classification column is forced to `No Trade`, and the event status is `LEGACY_UNVALIDATED`. Independent completed-futures parsing rejects unfinished/future bars, missing OI, invalid prices and duplicate conflicts, with explicit stale/unavailable states. This helper is tested but is not yet a complete production collector.
