from datetime import datetime
from nifty_l2.storage import IST, Store
from nifty_l2.terminal import snapshots, history_text
from nifty_l2.terminal_ui import history_html


def _insert(conn, ts, *, ce_oi, pe_oi, ce_premium, pe_premium, ce_vol, pe_vol, fut=24500, fut_oi=800000):
    conn.execute("INSERT INTO header_snapshots(ts,expiry_date,fut_close,fut_oi) VALUES(?,?,?,?)",
                 (ts, "09-11-2026", fut, fut_oi))
    for side, oi, premium, volume in (
        ("CE", ce_oi, ce_premium, ce_vol), ("PE", pe_oi, pe_premium, pe_vol)):
        conn.execute(
            "INSERT INTO strike_snapshots(ts,strike,opt_type,oi,ltp,volume,gamma) VALUES(?,?,?,?,?,?,?)",
            (ts, 24450, side, oi, premium, volume, 0.001))


def test_populates_oi_premium_proxies_and_futures_from_stored_data(tmp_path):
    store = Store(tmp_path / "research.db")
    start = int(datetime(2026, 11, 5, 15, 36, 2, tzinfo=IST).timestamp())
    with store.connect() as conn:
        _insert(conn, start, ce_oi=1751555, pe_oi=2382640, ce_premium=206.45,
                pe_premium=121, ce_vol=126069645, pe_vol=61488635, fut=24578.7, fut_oi=800000)
        _insert(conn, start+181, ce_oi=1702805, pe_oi=2326935, ce_premium=208,
                pe_premium=121.5, ce_vol=126287135, pe_vol=61846785, fut=24580, fut_oi=810000)
    params = dict(date=["2026-11-05"], expiry=["09-11-2026"], strike=["24450"])
    data = snapshots(tmp_path, params)
    html = history_html(data)
    assert "-48,750" in html
    assert "-55,705" in html
    assert "+217,490" in html
    assert "+358,150" in html
    assert "SHORT-COVERING-LIKE" not in html  # rendered as exit proxy value instead
    assert "LONG BUILDUP · proxy" in html
    assert "+10,000" in html
    assert "+1.55" in html
    assert "Notional GEX: unavailable" in html
    assert "126,287,135" not in html  # volume increments rather than cumulative totals
    assert "09-11-2026" in html
    assert "Stored gamma" in history_text(data)


def test_after_hours_row_never_generates_flow_proxy(tmp_path):
    store = Store(tmp_path / "research.db")
    start = int(datetime(2026, 11, 5, 15, 39, tzinfo=IST).timestamp())
    late = int(datetime(2026, 11, 5, 17, 57, tzinfo=IST).timestamp())
    with store.connect() as conn:
        _insert(conn, start, ce_oi=1000, pe_oi=1200, ce_premium=200,
                pe_premium=130, ce_vol=3000, pe_vol=3200)
        _insert(conn, late, ce_oi=1100, pe_oi=1400, ce_premium=210,
                pe_premium=140, ce_vol=3900, pe_vol=4200)
    data = snapshots(tmp_path, dict(date=["2026-11-05"], expiry=["09-11-2026"], strike=["24450"]))
    html = history_html(data)
    assert "AFTER-HOURS · NOT COMPARABLE" in html
    assert "15:39:00 IST" in html
    assert "17:57:00 IST" not in html  # latest-session card intentionally excludes afterhours
    assert "+200" in html  # latest in-session PE minus CE


def test_page_boundary_has_comparable_prior_row(tmp_path):
    store = Store(tmp_path / "research.db")
    first = int(datetime(2026, 11, 5, 10, 0, tzinfo=IST).timestamp())
    with store.connect() as conn:
        for i in range(14):
            _insert(conn, first+180*i, ce_oi=1000+100*i, pe_oi=1200+20*i,
                    ce_premium=200-i, pe_premium=100-i,
                    ce_vol=3000+i*1000, pe_vol=4000+i*500)
    data = snapshots(tmp_path, dict(date=["2026-11-05"], expiry=["09-11-2026"],
                                   strike=["24450"], page=["0"]))
    assert len(data["rows"]) == 24 and len(data["prior_rows"]) == 2
    html = history_html(data)
    assert "+100" in html
