# Milestone 1: calculation preservation contract (legacy-v1)

## Intent

Freeze the existing NIFTY Layer 2 valuation implementation so an upcoming Gemini-style UI, SQLite read model, new microstructure calculations, or XGBoost feature pipeline cannot silently change the original baseline.

**Scope: tests and documentation only**. No changes to `nifty_l2/legacy_engine.py`, `nifty_l2/runner.py`, `nifty_l2/replay.py`, FYERS authentication, service schedules, existing SQLite schema, live orders (none), or production dashboard configuration.

## What is actually frozen

`tests/test_calculation_preservation.py`:

1. Verifies the literal bytes of `nifty_l2/legacy_engine.py` using the Git blob SHA read from `main` at baseline creation. Even whitespace changes trigger review; a new engine version must not quietly update this digest.
2. Constructs **three deterministic synthetic option-chain and futures responses** using existing project fixtures. Feeds identical deep-copied FYERS responses into both `nifty_l2.replay.replay` (offline archival path) and `nifty_l2.runner.evaluate_once` (live worker's core calculation path) using mocked transport. No live FYERS connection.
3. Compares the **entire canonical output JSON** per observation, including all original nine checks, scores, Greeks scenarios, walls, vetoes, and metadata wherever the engine returns them. It also checks all nine directional statuses and selected critical metadata keys.
4. Checks SQLite research results are `No Trade` / `LEGACY_UNVALIDATED`, checks rows remain eighteen per observation, and checks header/strike snapshot counts, recorded responses and integrity in two isolated temporary databases.
5. Ensures a malformed recorded API sequence rolls back the test database.

**Important:** Matching two executions of the same legacy engine is *calculation preservation*, not independent economic validation. Original Greek assumptions, questionable freshness and any inherited bugs are deliberately held constant for baseline comparison. Actual FYERS observations from your AWS `research.db` are **not part of this initial test**. A later milestone should add safe sequential replay of archived market responses after validating their completeness, timestamps, credentials exclusion and source hashes.

## Test without changing production checkout

```bash
cd ~/nifty-layer2-engine
git fetch origin
git worktree add ~/nifty-preservation origin/test/legacy-calculation-preservation-v1
cd ~/nifty-preservation
/home/ubuntu/nifty-layer2-engine/.venv/bin/python -m pytest -q tests/test_calculation_preservation.py tests/test_engine.py tests/test_runner.py
/home/ubuntu/nifty-layer2-engine/.venv/bin/python -m pytest -q
```

Neither command accesses or modifies the live research database, FYERS tokens, collector services or web process. If any check fails, do not merge and do not overwrite the golden source hash: investigate the mismatch first.

## Versioning rule

- `legacy-v1`: original engine frozen byte-for-byte and original research-only output.
- `research-v2`: any proposed new gamma/OI/wall logic, calculated separately with version and assumptions recorded.
- UI changes: may change layout and read model but never baseline signal calculations.
- Zero, absent, stale and estimated inputs must be distinguishable; future models must not present estimated seller activity as observed facts.

## Current limitations

The fixture is deterministic and synthetic, not an authenticated real trading-day capture. It exercises three consecutive sessions **within one trading day**, not all historical paths, expiries, rollover scenarios or market regimes. Additional fixtures are required to test sensitivity of individual checks and numeric valuation against independent closed-form references. No performance/edge claim is made.
