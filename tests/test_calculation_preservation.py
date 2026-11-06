"""Calculation-preservation contract for the original NIFTY nine-check engine.

Offline only. Runs identical recorded synthetic FYERS responses through BOTH
production adapter and offline replay, in isolated temporary SQLite databases.
Checks complete normalized output, stored status and original source blob.
No broker login, no real market history, no orders, no writes to AWS runtime.

NOTE: This is parity evidence, NOT independent proof that the strategy is correct.
"""
from copy import deepcopy
from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path

import pytest

from nifty_l2 import fyers
from nifty_l2.replay import replay
from nifty_l2.runner import ReadOnlyClient, evaluate_once
from nifty_l2.storage import Store, canonical
from test_engine import fixture_calls


LEGACY_GIT_BLOB_SHA = "474494361771b4d68feb627f56d29bf289a9aea2"


def test_frozen_legacy_engine_source_is_unchanged():
    """Intentional engine changes require a conscious contract baseline revision."""
    engine = Path(__file__).resolve().parents[1] / "nifty_l2" / "legacy_engine.py"
    raw = engine.read_bytes()
    sha = hashlib.sha1(b"blob " + str(len(raw)).encode() + bytes([0]) + raw).hexdigest()
    assert sha == LEGACY_GIT_BLOB_SHA, (
        "Legacy valuation implementation changed. Do NOT auto-update this baseline: "
        "review rule/Greek/futures differences and explicitly version the new engine."
    )


def _counts(conn):
    return {
        name: conn.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]
        for name in ("signals", "events", "check_results", "header_snapshots",
                     "strike_snapshots", "option_snapshots", "futures_data")
    }


def _check_state_shape(state):
    """Exercise all 9 checks and the essential research/valuation output surface."""
    assert len(state.get("scorecard", [])) == 9
    for n, row in enumerate(state["scorecard"], 1):
        assert "Bull_Status" in row, f"Missing bull status for check {n}"
        assert "Bear_Status" in row, f"Missing bear status for check {n}"
    assert "final_verdict" in state
    assert "meta" in state
    meta = state["meta"]
    for key in ("spot", "fut_close", "put_wall", "call_wall", "gex"):
        assert key in meta, f"Missing original valuation field {key}"


def test_three_observation_full_state_parity_and_sqlite_safety(tmp_path, monkeypatch):
    monkeypatch.setenv("ACTIVE_INDEX", "NIFTY")
    monkeypatch.setenv("NIFTY_FUT_SYMBOL", "")
    base = datetime.fromisoformat("2026-11-03T09:24:00+05:30")
    replay_store = Store(tmp_path / "replay.db")
    runner_store = Store(tmp_path / "runner.db")

    for tick in range(3):
        dt = base + timedelta(minutes=3 * tick)
        calls = fixture_calls(tick, dt)
        # Both paths receive separate deep-copies: the original engine mutates
        # option Greeks in the returned chain, not the archived raw responses.
        offline = replay(replay_store, observed_at=dt, calls=deepcopy(calls))
        pending = deepcopy(calls)

        def transport(operation, *, params, credentials):
            assert pending, "Unexpected extra FYERS request"
            recorded = pending.pop(0)
            assert (operation, params) == (recorded["method"], recorded["request"])
            return deepcopy(recorded["response"])

        monkeypatch.setattr(fyers, "request", transport)
        client = ReadOnlyClient({"client_id": "OFFLINE", "access_token": "FAKE_TOKEN"})
        online_adapter = evaluate_once(runner_store, client, now=dt)
        assert not pending, "Did not consume all expected recorded responses"
        assert client.calls == calls
        assert offline["classification"] == online_adapter["classification"] == "No Trade"
        assert offline["status"] == online_adapter["status"] == "LEGACY_UNVALIDATED"
        _check_state_shape(offline["state"])
        assert canonical(offline["state"]) == canonical(online_adapter["state"]), (
            f"Full original engine result diverged at synthetic observation {tick}"
        )
        with replay_store.connect() as a, runner_store.connect() as b:
            for conn in (a, b):
                assert conn.execute("SELECT COUNT(*) FROM check_results").fetchone()[0] == 18 * (tick + 1)
                assert conn.execute("SELECT DISTINCT classification FROM signals").fetchall() == [("No Trade",)]
                assert conn.execute("SELECT DISTINCT status FROM events").fetchall() == [("LEGACY_UNVALIDATED",)]
                original = conn.execute("SELECT payload_json FROM signals ORDER BY rowid DESC LIMIT 1").fetchone()[0]
                assert canonical(json.loads(original)) == canonical(offline["state"])
            assert _counts(a)["header_snapshots"] == _counts(b)["header_snapshots"] == tick + 1
            assert _counts(a)["strike_snapshots"] == _counts(b)["strike_snapshots"] == 10 * (tick + 1)

    # Runner stores the real-time audit kind; offline replay preserves a
    # different kind/source. Their event IDs must *not* be expected to match.
    assert replay_store.integrity()["ok"]
    assert runner_store.integrity()["ok"]


def test_bad_recording_does_not_change_any_production_db(tmp_path):
    store = Store(tmp_path / "isolated.db")
    with pytest.raises(ValueError, match="mismatch"):
        replay(store, observed_at="2026-11-03T09:24:00+05:30",
               calls=[{"method": "quotes", "request": {}, "response": {}}])
    assert store.integrity()["counts"]["events"] == 0
