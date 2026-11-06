# Development validation evidence — 6 November 2026

Research only. No deployment or strategy approval. This report distinguishes
software behavior from market-data and economic validation.

## Development baseline and change log

Parent branch: `feat/research-platform-milestones-2-8`, commit
`a9cb37181d84ed87a4ebe0b7632595a4e933a815`; reviewed existing draft PR #6,
its diff, architecture/runbooks and related tests before editing.
New branch: `feat/greeks-capture-evidence-safety`.

- `nifty_l2/synchronized_greeks_capture.py`: reserves the real report file with
  O_CREAT|O_EXCL and mode 0600 before token loading or broker access. A collision
  preserves evidence and asks for a new filename. The same descriptor receives
  the serialized result, flush and fsync. Failed captures leave a sanitized
  failure record; interrupted processes may leave an empty/partial reserved
  report. Neither is valid successful market evidence. No deletion or replacement.
- Capture schema v2 retains both futures source quote objects, all four bracket
  request/response times, per-request latency, option bid/ask/LTP, missing fields,
  unknown stale-data status, partial-chain coverage and explicit research gates.
  All times normalize to UTC; naive or backward capture times are rejected.
- Contract lot size/source remain null and unverified rather than being guessed
  from the legacy 75 or assumed 65. No verified contract-master ingestion exists
  yet. Expiry selection remains the broker-returned first expiry, with its ID/date;
  a returned symbol is recorded, but its expiry mapping is not independently
  verified. The quote is a futures proxy, not a verified option-pricing forward.
- `nifty_l2/futures_persistence.py`: identical eligible duplicates are accepted;
  conflicting eligible OHLCV/OI duplicates return no row. Latest-start contract or
  resolution ambiguity also returns no row. There is no keep-first/last/average
  correction policy. This also affects copy-only backfill; it is not deployed.
- `nifty_l2/gex_assumption_audit.py`: scenario output explicitly labels
  **SIGNED-OI GEX SCENARIO — UNVERIFIED** and records unverified lot size.
- Regression tests cover collision before credentials/broker access, concurrent
  reservations, dangling symlinks, private permissions, sanitized failure evidence,
  timing/coverage metadata and OHLCV/OI conflicts in both input orders.

## Test results

Baseline: 104 passed. Final AWS offline suite: 110 passed in 9.02 seconds.
Compileall passed for `nifty_l2`, `eod_scanner`, `tests`; diff whitespace check passed.
An intermediate assertion compared equivalent UTC/IST strings literally; it was
corrected to assert normalized UTC. Final suite has no failures.
Frozen legacy source and nine-check parity tests passed. No legacy formula,
production checkout, schema, token, service configuration or database was edited.
GitHub Actions uses the existing full offline regression workflow; consult the
new draft PR checks for the final commit status.

## Read-only historical data-quality audit

Private create-only evidence directory:
`/home/ubuntu/nifty-validation-reports/codex-20261106T060656Z/`.
Files: `historical.json`, `option-time.json`, `futures-archive.json`,
`oi-units-assumed65.json`, `gex-assumed65.json`, `greeks-live.json`.
No raw private broker payload or credentials are included in this repository.
Each archive audit used SQLite URI `mode=ro` and `PRAGMA query_only=ON`.
The collector remained active, so these separate reads are not a common database
snapshot; counts refer to their read times around 06:06 UTC.

| Finding | Observed value |
| --- | ---: |
| Research events / signal rows / headers | 132 / 132 / 132 |
| Strike rows / directional check rows | 5,544 / 2,376 |
| Normalized futures table rows | 0 |
| Missing verified event exchange timestamps | 132 |
| Observation gaps over six minutes | 6 |
| Invalid/orphan strike rows | 0 / 0 |
| Non-NO-TRADE research classifications | 0 |
| Events with usable raw broker Greeks | 132 / 132 |
| Option-chain calls / legs inspected for timestamp fields | 264 / 6,336 |
| Recognized candidate option timestamp fields | 0 |
| Positive unique day-contract OI divisible by assumed 65 | 136 / 136 |

SQLite quick check, schema, research safety, strike integrity and recorded nine
checks passed. Historical status remains REQUIRES_MARKET_VALIDATION. Futures
archive contains 132 history calls and 62,990 completed positive-OI rows before
cross-response deduplication; these are not unique independent observations.
No backfill or transformation was run against production or an existing copy.

Existing private `futures-oi-duplicates-reviewed.json` has 903 rows, 896 eligible,
128 duplicates (63 identical, 65 conflicting). Later
`futures-oi-conflict-breakdown.json` has the same total/eligible counts and 128
identical duplicates, zero conflicts. The later response does not invalidate or
repair the earlier evidence. Conflicting inputs must remain excluded.

## FYERS live read-only validation

One four-call run used the exact futures symbol present in all 132 archived
history requests: `NSE:NIFTY26NOVFUT`. It called expiry discovery, futures quotes,
option-chain Greeks, futures quotes. No profile/account or order endpoint,
refresh, retry loop, token modification or collector change occurred.

- Successful authenticated market-data reads on 2026-11-06.
- Receipt bracket: 06:07:15.431692–06:07:16.224905 UTC (0.793213 seconds).
- Option-chain latency: 0.301567 seconds; futures drift: 0%.
- Broker expiry selector: `1794219000`, returned date `09-11-2026`.
- 42 CE/PE legs retained exact source symbols, OI, IV, delta, gamma, bid, ask, LTP.
- Only reported missing field: verified contract lot size (all legs).
- Status RECEIPT_BRACKET_UNVERIFIED, trade_eligible=false. Fresh receipt timing
  is not evidence of fresh exchange OI. No expiry selector is used as an
  observation timestamp, and no completed option candle is claimed.

## GEX and gamma acceptance

Unresolved: FYERS OI units, exact contract lot evidence, independent time-aligned
NSE OI, broker Greek convention, pricing forward, rate, IV units and authoritative
expiry cutoff. Divisibility is structural evidence only. A lot value of 65 in
archive audits is an explicit sensitivity assumption across those observations,
not verified historical contract metadata. Legacy GEX was not multiplied by 65.

Analytic Black-76 tests pass, including a synthetic median broker/model gamma
ratio of 1.025. This is a fixture result, not observed market parity. No live or
historical gamma parity statistics were produced because verified forward,
rate/cutoff evidence was absent; no arbitrary inputs were substituted.
Existing scenario tooling exposes alternative signs and quantity interpretations,
but full-chain coverage, actual dealer inventory and dealer gamma flip remain
unverified. Source quote brackets cannot certify synchronization.

## Historical replay and ML readiness

Existing deterministic recorded-response replay and frozen-engine preservation
remain available; replay was not run into production. Candidate 9/15/30-minute
labels require exact completed target observations and stay unvalidated. No
validated labels or trainable dataset were established by this audit. Missing
option observation provenance, contract/rollover matching, continuity and source
coverage must be addressed before labeling/training acceptance.

Existing XGBoost scaffolding is offline/shadow only, requires validated input and
multiple independent days, uses chronological folds and a 30-minute embargo.
It still lacks a fully audited dataset, deterministic baseline comparison,
precision/recall/confusion-matrix reporting, calibration curves and cost-adjusted
performance. Do not treat scaffolding or fixture results as completed ML
validation. Implementation/acceptance of these later phases is deferred until the
explicit data-quality prerequisite in the handover passes.

## Production and rollback

No production service was stopped, restarted or reconfigured; no deployment,
merge, production database write, historical deletion or order execution occurred.
The development worktree shares Git metadata with production, but only the new
feature branch/worktree was changed. Existing PR #6 remains intact.

Rollback for this undeployed work: keep production on its existing checkout;
discard/revert the new development commit if review rejects it. Preserve every
private evidence file, including failed/partial reports. Any eventual deployment
requires separate approval, a consistent SQLite backup, recorded service/checkout
state, copy-based validation and a tested rollback to the approved prior release.
No release procedure or production permission is requested here.

## Highest-priority next action

Obtain one permitted independent, contemporaneous NSE contract-count OI reference
with authoritative contract metadata for the captured expiry.

Validation checklist:
- Match exact option symbol, expiry, strike, CE/PE and per-contract lot source.
- Retain source timestamps and bound receipt/reference skew; reject ambiguous
  matches and do not claim exchange synchronization from receipt proximity.
- Run OI reconciliation with a new output filename; investigate inconsistencies.
- Keep quantity convention unverified until independently reviewed evidence
  supports acceptance; keep the signed-OI scenario label and NO TRADE gates.
