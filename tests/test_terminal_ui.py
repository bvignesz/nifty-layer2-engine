from datetime import datetime
from urllib.parse import parse_qs

from nifty_l2.storage import IST, Store
from nifty_l2.terminal import snapshots
from nifty_l2.terminal_ui import history_html


def test_ui_uses_existing_snapshot_values_without_fabricating_gex(tmp_path):
    store = Store(tmp_path / "research.db")
    ts = int(datetime(2026, 11, 5, 10, 21, tzinfo=IST).timestamp())
    with store.connect() as conn:
        conn.execute(
            "INSERT INTO header_snapshots(ts,expiry_date,fut_close) VALUES(?,?,?)",
            (ts, "2026-11-09", 23980.5))
        for side, oi, vol, gamma in [
            ("CE", 1000, 3000, 0.000012), ("PE", 1500, 2000, 0.000014)
        ]:
            conn.execute(
                "INSERT INTO strike_snapshots(ts,strike,opt_type,oi,volume,gamma) VALUES(?,?,?,?,?,?)",
                (ts, 23900, side, oi, vol, gamma))
    data = snapshots(tmp_path, {
        "date": ["2026-11-05"], "expiry": ["2026-11-09"], "strike": ["23900"]})
    html = history_html(data)
    assert "1,000" in html and "1,500" in html
    assert "+500" in html
    assert "23,980.50" in html
    assert "CE 0.000012 / PE 0.000014" in html
    assert "Notional GEX: unavailable" in html
    assert "no seller identification" in html
    assert "AFTER-HOURS · NOT COMPARABLE" in html
    assert "/export?" in html and "copy-snapshots" in html


def test_empty_snapshot_terminal_escapes_untrusted_filters(tmp_path):
    html = history_html(snapshots(tmp_path, {
        "expiry": ["<script>alert(1)</script>"], "strike": ["23900"]}))
    assert "<script>alert(1)</script>" not in html
    assert "No snapshots" in html
