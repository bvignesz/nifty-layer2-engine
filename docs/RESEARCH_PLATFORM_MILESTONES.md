# NIFTY Research Platform — pre-installation development branch

**Branch:** `feat/research-platform-milestones-2-8`

**Do not deploy yet.** This branch is intentionally isolated from AWS `nifty-web.service`, `nifty-collector.service`, FYERS credentials and the live `research.db`. Nothing here modifies `legacy_engine.py`, `runner.py`, `collector.py` or `schema.sql`. All original nine-check formulas, scores, vetoes, GEX/VEX/CHEX scenarios and original validated `No Trade` classification remain intact.

## What is implemented

| Area | Code | Verification / limitation |
|---|---|---|
| 2. Read-only analytics API | `nifty_l2/research_readmodel.py`, `web.py` | `/api/v1/research`, `/api/v1/expiries`, `/api/v1/readiness` using bounded read-only SQLite; offline tests |
| 2. Terminal navigation | `nifty_l2/research_pages.py` | Nine-check history, expiry quotes, EOD and validation tabs; no frontend valuation code |
| 3. Greek/GEX research | `nifty_l2/research_quality.py` | Unit-explicit scenario calculator + completed-candle/timestamp checks. NOT independent validation of source gamma, dealer sign or production valuations |
| 4. Actual multi-expiry feed | `nifty_l2/expiry_probe.py`, `expiry_archive.py` | An **optional separate** broker probe of returned expiry IDs and legs. No new live collector schedule. Missing W1/W2 remains absent |
| 5. Original EOD v0.7.0 preservation | `eod_scanner/frozen/` | 3216-line uploaded original, byte-frozen by Git blob hash test |
| 5. FYERS EOD bridge | `eod_scanner/fyers_bridge.py`, `eod_scanner/runner.py` | Uses explicit reviewed symbol map; daily and 15m OHLCV; original strategy code unchanged. Corporate action adjustments and historical parity **not verified** |
| 5. EOD webpage | `eod_scanner/readmodel.py`, `research_pages.py` | Shows actual `eod_scanner_results.csv` when produced. No fake stock signals |
| 6. Forward outcome groundwork | `nifty_l2/research_outcomes.py` | Candidate 9/15/30-min labels only from exact completed target timestamps; explicitly UNVALIDATED, no writes to live outcomes |
| 7–8. ML evaluation groundwork | `ml_shadow.py`, `xgb_evaluator.py` | Hard gates on validated labels and multiple days; optional offline expanding chronological XGBoost evaluator with embargo. **No model trained and no production predictions** |
| Tests/CI | `tests/test_research_*.py`, `tests/test_eod_bridge.py`, `tests/test_expiry_probe.py`, `.github/workflows/research-platform-ci.yml` | CI compiles Python and runs full existing + new offline test suite; AWS run not yet done |

## Data/source limitations that still block completion of the production milestones

1. Existing `header_snapshots`/`strike_snapshots` hold receipt-time observations; no evidence of fully validated 3-minute option candles or dealer positioning.
2. Verified FYERS symbol master and benchmark mapping are needed for EOD. The existing strategy expects Yahoo-adjusted prices; the FYERS bridge does not provide a verified corporate-action-adjusted equivalent. Historical parity is mandatory before relying on scanner classifications.
3. Every expiry seen in the UI must be a real broker-returned expiry from the matching date. The optional probe is intentionally separate and is not yet scheduled.
4. GEX accuracy is not demonstrated. Validate quantity units, repeated model gamma values, IV, expiry/rates and dealer scenario assumptions.
5. Outcome generator produces **candidates**, not validated labels. Audit actual exchange bar timestamps, continuity, underlying/futures identity, contract rollover, horizon and costs.
6. The new XGBoost evaluator is offline only. No trainable dataset with verified future outcomes has been demonstrated. Walk-forward metrics are not trade expectancy; realistic execution costs and a shadow-trading period remain required.
7. The original EOD scanner retains Yahoo-named symbols and switches the data provider through a compatibility shim; test its coverage, calendar adjustment, price/volume basis, one-shot scheduling and output persistence before use.
8. Public website authentication is still as configured; this branch does not alter it.
9. Separate UI-only derived-column PR #4 is not part of this branch until independently reviewed/merged.
10. API/UI views are a development first cut, not a proven institutional-grade trading product.

## Development acceptance (separate from final installation)

From a **separate git worktree**, not the active production checkout:

```bash
git -C ~/nifty-layer2-engine fetch origin
git -C ~/nifty-layer2-engine worktree add ~/nifty-platform-dev origin/feat/research-platform-milestones-2-8
cd ~/nifty-platform-dev
/home/ubuntu/nifty-layer2-engine/.venv/bin/python -m compileall -q nifty_l2 eod_scanner tests
/home/ubuntu/nifty-layer2-engine/.venv/bin/python -m pytest -q
```

Do not merge or restart services if any regression test fails. Production installation and migration are intentionally deferred until research data/API correctness, EOD equivalence and access controls have been reviewed.

## Service separation for eventual release

- Existing `nifty-collector.service`: keep original scheduling and legacy valuation intact.
- Existing `nifty-web.service`: consume read-only API and render research tabs.
- Optional EOD collector: separate service/timer and separate CSV/SQLite state, after FYERS symbol/adjustment parity.
- Optional expiry collector: separate service and immutable dated snapshots, rate-limit aware.
- Offline XGBoost: manual, historical validation only; no autonomous orders or direct live decision badge until verified.

*This code introduces capability scaffolding. It does not claim that all eight production milestones are validated or ready to install.*
