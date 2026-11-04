from datetime import datetime

from nifty_l2.storage import IST, Store
from nifty_l2.terminal import history_html, history_text, snapshots


def test_history_filters_ist_date_expiry_strike_and_pages(tmp_path):
    store = Store(tmp_path / 'research.db')
    start = int(datetime(2026, 11, 4, tzinfo=IST).timestamp())
    with store.connect() as conn:
        for index in range(15):
            ts = start + index * 180
            conn.execute('INSERT INTO header_snapshots(ts,expiry_date,fut_close) VALUES(?,?,?)',
                         (ts, '2026-11-09', 24000))
            for strike in (23900, 24000):
                for side in ('CE', 'PE'):
                    conn.execute('INSERT INTO strike_snapshots(ts,strike,opt_type,oi,volume,ltp) VALUES(?,?,?,?,?,?)',
                                 (ts, strike, side, index + 100, index * 1000, 50))
        conn.execute('INSERT INTO header_snapshots(ts,expiry_date) VALUES(?,?)',
                     (start - 1, '2026-11-02'))
    params = dict(date=['2026-11-04'], expiry=['2026-11-09'], strike=['23900'])
    data = snapshots(tmp_path, params)
    assert data['expiries'] == ['2026-11-09']
    assert data['strikes'] == ['23900', '24000']
    assert data['total'] == 15 and len(data['rows']) == 24
    assert data['rows'][0][0] == start + 14 * 180
    older = snapshots(tmp_path, dict(params, page=['1']))
    assert len(older['rows']) == 6
    assert older['rows'][-1][0] == start
    text = history_text(data)
    assert '00:42:00\tCE\t114.00' in text
    assert 'Stored gamma' in text and 'Unavailable' in text
    html = history_html(data)
    assert '/export?' in html and 'Older »' in html
    assert 'not completed candle times' in html
    assert snapshots(tmp_path, dict(params, expiry=['2026-11-02']))['rows'] == []


def test_history_empty_database_and_filter_escaping(tmp_path):
    data = snapshots(tmp_path, dict(expiry=['<script>'], strike=['23900']))
    assert data['rows'] == []
    assert '<script>' not in history_html(data)
    assert 'No snapshots' in history_text(data)
