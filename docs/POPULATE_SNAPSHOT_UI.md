# Populate saved option snapshot columns safely

This change is intentionally **read-only presentation logic**. No change to FYERS authentication, collector scheduling, nine-check valuation, Greeks calculations, order execution, or DB schema.

Existing `nifty_l2.terminal.snapshots` loads CE/PE OI, cumulative volume, LTP, stored gamma, futures close **plus futures OI**. It also fetches one preceding timestamp for correct deltas at page boundaries.

The UI now shows:
- Per-side stored OI, previous snapshot OI change, same-strike PE−CE change.
- Per-side cumulative-volume increments and premium changes, compared only with the preceding observation (time gap <=360 seconds, both times within 09:15–15:40 IST on the same day, no negative volume counters).
- Exploratory **writing-like** (OI up / premium down), **long-addition-like** (OI up / premium up), **short-covering-like** (OI down / premium up), or **long-unwinding-like** (OI down / premium down) tags. These are **NOT actual trade direction or seller-only attribution**; premium prices also reflect underlying movement and IV.
- Futures price and OI differences with provisional four-quadrant labels **only if both OI readings are nonzero**.
- After-hours rows clearly labeled, with change-based classifications disabled.
- CE/PE saved Greek gamma displayed unchanged. **No rupee GEX** is invented or recomputed. Existing research summary remains unchanged.

The "Copy Table as Text" and "Export TXT" functions now use `/export/terminal`, a read-only TSV of the populated columns; legacy raw `/export` remains unchanged.

## Before deployment

```bash
cd ~/nifty-layer2-engine
git fetch origin
git worktree add ~/nifty-ui-v2 origin/feat/populate-snapshot-derived-columns
cd ~/nifty-ui-v2
/home/ubuntu/nifty-layer2-engine/.venv/bin/python -m pytest -q tests/test_terminal.py tests/test_terminal_ui.py tests/test_snapshot_derived.py tests/test_web.py
/home/ubuntu/nifty-layer2-engine/.venv/bin/python -m pytest -q
```

These tests must pass before merging to main. Do not restart collector or overwrite SQLite. The output remains **research-only**. Snapshot trade-side metrics cannot be inferred as ground truth. Market-close 15:40 applies to existing F&O collection configuration and does not guarantee underlying spot quote freshness.
