"""Server-rendered option snapshot browser; no external assets or fabricated candles."""
from datetime import date, datetime, time, timedelta
from html import escape
import sqlite3
from urllib.parse import urlencode

from .storage import IST


CSS = '''
:root{color-scheme:dark;font-family:Inter,system-ui,sans-serif;background:#0b0f19;color:#e5e7eb}
*{box-sizing:border-box}body{margin:0}main{max-width:1440px;margin:auto;padding:16px}
header{display:flex;align-items:center;justify-content:space-between;gap:16px;padding:16px;background:#131c2e;border:1px solid #1e293b;border-radius:8px;flex-wrap:wrap}
.brand{display:flex;align-items:center;gap:12px;color:#34d399;font-size:14px;letter-spacing:1px}.logo{display:grid;place-items:center;border-radius:50%;background:#059669;color:white;width:36px;height:36px;font-weight:700}.brand small{display:block;letter-spacing:0;margin-top:5px}
h1{font-size:22px;margin:24px 0 8px}h2{font-size:14px;margin:0 0 12px}p{color:#94a3b8;line-height:1.6}small,.muted{font-size:12px;color:#94a3b8}.tag{font-size:11px;color:#34d399}.grid,.metrics{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:12px;margin:16px 0}
article,.notice{background:#131c2e;border:1px solid #1e293b;border-radius:8px;padding:18px;margin:16px 0}.grid article{margin:0}.metrics>div{padding:14px;background:#0b0f19;border:1px solid #1e293b;border-radius:6px}.metrics strong{display:block;margin-top:10px;font:600 18px ui-monospace,monospace;color:#60a5fa}
form{display:inline-block;margin:4px 8px 4px 0}button,.button{display:inline-block;background:#2563eb;color:#fff;border:1px solid #3b82f6;border-radius:5px;padding:9px 12px;font:600 12px system-ui;cursor:pointer;text-decoration:none}button:hover,.button:hover{background:#3b82f6}a{color:#60a5fa}button:focus-visible,input:focus-visible,select:focus-visible,a:focus-visible{outline:2px solid #fff;outline-offset:3px}
label{display:block;margin:10px 0 6px;font-size:11px;color:#94a3b8}input:not([type=hidden]),select{background:#0b0f19;color:#fff;border:1px solid #334155;border-radius:4px;padding:9px;font:12px ui-monospace,monospace;max-width:100%}details form{display:block}details input{display:block;width:440px}summary{cursor:pointer;color:#94a3b8}pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:12px}code{overflow-wrap:anywhere}
.table{overflow:auto;border:1px solid #1e293b;border-radius:6px}table{width:100%;border-collapse:collapse;text-align:left;font:12px ui-monospace,monospace}th,td{padding:14px;border-right:1px solid #1e293b;border-bottom:1px solid #1e293b;white-space:nowrap}th{background:#0b0f19;color:#94a3b8;text-transform:uppercase;font-size:11px}td:first-child,th:first-child{position:sticky;left:0;background:#131c2e}tr:hover td{background:#1a263d}.toolbar{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap;margin:12px 0}.filters{display:flex;align-items:end;gap:10px;flex-wrap:wrap}.filters label{margin:0}.filters input,.filters select{display:block;margin-top:5px}.positive{color:#34d399}.negative{color:#fb7185}footer{border-top:1px solid #1e293b;padding:18px 0;color:#64748b;font-size:12px}::-webkit-scrollbar{width:6px;height:6px}::-webkit-scrollbar-thumb{background:#334155;border-radius:3px}
@media(max-width:600px){main{padding:10px}.grid,.metrics{grid-template-columns:1fr}.filters>*{flex:1 1 120px}article{padding:12px}h1{font-size:19px}}
'''


def snapshots(directory, params):
    """Read one IST date and expiry, keeping all queries bounded and parameterized."""
    day = date.fromisoformat(params.get('date', [datetime.now(IST).date().isoformat()])[0])
    expiry = params.get('expiry', [''])[0]
    strike = params.get('strike', [''])[0]
    page = max(0, min(int(params.get('page', ['0'])[0]), 100000))
    start = int(datetime.combine(day, time.min, IST).timestamp())
    end = int(datetime.combine(day + timedelta(days=1), time.min, IST).timestamp())
    result = dict(day=day.isoformat(), expiry=expiry, strike=strike, page=page,
                  expiries=[], strikes=[], rows=[], prior_rows=[], total=0, error='')
    database = directory / 'research.db'
    if not database.exists():
        return result
    try:
        with sqlite3.connect(database.as_uri() + '?mode=ro', uri=True, timeout=5) as conn:
            result['expiries'] = [r[0] for r in conn.execute(
                'SELECT DISTINCT expiry_date FROM header_snapshots WHERE ts>=? AND ts<? AND expiry_date IS NOT NULL ORDER BY expiry_date', (start, end))]
            if not expiry and result['expiries']:
                expiry = result['expiry'] = result['expiries'][0]
            base = ' FROM strike_snapshots s JOIN header_snapshots h ON h.ts=s.ts WHERE s.ts>=? AND s.ts<? AND h.expiry_date=?'
            args = (start, end, expiry)
            result['strikes'] = [str(r[0]) for r in conn.execute('SELECT DISTINCT s.strike' + base + ' ORDER BY s.strike', args)]
            if not strike and result['strikes']:
                strike = result['strike'] = result['strikes'][len(result['strikes']) // 2]
            if strike:
                strike_number = int(strike)
                result['total'] = conn.execute('SELECT count(DISTINCT s.ts)' + base + ' AND s.strike=?', (*args, strike_number)).fetchone()[0]
                times = [r[0] for r in conn.execute('SELECT DISTINCT s.ts' + base + ' AND s.strike=? ORDER BY s.ts DESC LIMIT 12 OFFSET ?', (*args, strike_number, page * 12))]
                if times:
                    # Read exactly one older snapshot for the oldest visible observation.
                    # This makes deltas at page boundaries correct; no across-day lookback.
                    preceding = conn.execute('SELECT MAX(s.ts)' + base +
                        ' AND s.strike=? AND s.ts<?', (*args, strike_number, min(times))).fetchone()[0]
                    all_times = times + ([preceding] if preceding is not None else [])
                    marks = ','.join('?' for _ in all_times)
                    selected = conn.execute(
                        'SELECT s.ts,s.opt_type,s.oi,s.volume,s.ltp,s.bid,s.ask,s.gamma,'
                        'h.fut_close,h.fut_oi,h.spot' + base +
                        f' AND s.strike=? AND s.ts IN ({marks}) ORDER BY s.ts DESC,s.opt_type',
                        (*args, strike_number, *all_times)).fetchall()
                    result['rows'] = [r for r in selected if r[0] in times]
                    result['prior_rows'] = [r for r in selected if r[0] == preceding] if preceding is not None else []
    except sqlite3.Error:
        result['error'] = 'Snapshot history is temporarily unavailable.'
    return result


HEADERS = ('Observed (IST)', 'Side', 'Open interest', 'Cumulative volume', 'LTP ₹', 'Bid ₹', 'Ask ₹', 'Stored gamma', 'Futures ₹')


def display_rows(data):
    for row in data['rows']:
        yield (datetime.fromtimestamp(row[0], IST).strftime('%H:%M:%S'), row[1], *(
            'Unavailable' if value is None else format(value, ',.6f' if index == 7 else ',.2f')
            for index, value in enumerate(row[2:9], 2)))


def history_html(data):
    def options(values, selected):
        return '<option value="">Select</option>' + ''.join(
            f'<option value="{escape(value, quote=True)}"' + (' selected' if value == selected else '') + '>' + escape(value) + '</option>' for value in values)
    def link():
        return '/?' + urlencode(dict(date=data['day'], expiry=data['expiry'], strike=data['strike'], page=data['page']))
    query = dict(date=data['day'], expiry=data['expiry'], strike=data['strike'])
    html = '<article><div class="toolbar"><h2>STRIKE OI · STORED OPTION SNAPSHOTS</h2><a class="button" href="/export?' + escape(urlencode(dict(query, page=data['page'])), quote=True) + '">Export table as text</a></div>'
    html += '<form class="filters" method="get" action="/"><label>DATE · IST<input type="date" name="date" value="' + data['day'] + '" required></label>'
    html += '<label>EXPIRY<select name="expiry">' + options(data['expiries'], data['expiry']) + '</select></label>'
    html += '<label>STRIKE<select name="strike">' + options(data['strikes'], data['strike']) + '</select></label><button>Apply filters</button><a class="button" href="' + escape(link(), quote=True) + '">Refresh</a></form>'
    html += '<p class="muted">Collected snapshots · scheduled every 3 minutes. Observation times are not completed candle times. Volume is cumulative; gamma is the stored model estimate. Seller flow and strict 1-minute candles are unavailable.</p>'
    html += '<div class="table"><table><thead><tr>' + ''.join('<th>' + escape(h) + '</th>' for h in HEADERS) + '</tr></thead><tbody>'
    html += ''.join('<tr>' + ''.join('<td>' + escape(value) + '</td>' for value in row) + '</tr>' for row in display_rows(data))
    if not data['rows']:
        html += '<tr><td colspan="9">' + escape(data['error'] or 'No snapshots for this selection. Select a date and apply to load its expiries and strikes.') + '</td></tr>'
    html += '</tbody></table></div><div class="toolbar"><small>' + str(data['total']) + ' stored observations · page ' + str(data['page'] + 1) + '</small><div>'
    for label, number in [('« Newer', data['page'] - 1), ('Older »', data['page'] + 1)]:
        if number >= 0 and (number < data['page'] or number * 12 < data['total']):
            html += '<a class="button" href="/?' + escape(urlencode(dict(query, page=number)), quote=True) + '">' + label + '</a> '
    return html + '</div></div></article>'


def history_text(data):
    return '\n'.join([
        'PRO TRADER ACADEMY · NIFTY STRIKE OI SNAPSHOTS',
        f"Date (IST): {data['day']} | Expiry: {data['expiry']} | Strike: {data['strike']} | Page: {data['page'] + 1}",
        'Observed snapshots, not completed candles. Volume is cumulative. Gamma is a model estimate.',
        '\t'.join(HEADERS), *('\t'.join(row) for row in display_rows(data)),
        data['error'] or ('' if data['rows'] else 'No snapshots for this selection.'),
    ])
