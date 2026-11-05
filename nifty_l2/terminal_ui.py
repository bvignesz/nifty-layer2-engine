"""Presentation-only NIFTY strike snapshot terminal.

Never calculates or modifies valuation, signal, GEX, or dealer-flow metrics.
Everything displayed is backed by existing SQLite snapshot columns.
"""
from collections import defaultdict
from datetime import datetime
from html import escape
from urllib.parse import urlencode

from .storage import IST

UI_CSS = """
main{max-width:1740px;padding:20px 24px}
body{background:radial-gradient(ellipse at top left,#12213a 0,#080d17 48%,#080d17 100%)}
header{background:#101c30;border-color:#2a3853;border-radius:14px;box-shadow:0 12px 36px #0003}
.brand{color:#e5efff;font-weight:700}.brand small{color:#91a6c3}
.logo{background:#145a9c;border-radius:12px}
h1{letter-spacing:-.03em;font-size:26px}
article{border-radius:14px;background:#111b2d;border-color:#27364d;box-shadow:0 8px 20px #0002}
.metrics>div{border-radius:10px}
.snapshot-shell{margin:16px 0 24px;padding:0;overflow:hidden}
.snapshot-top{padding:18px 20px;border-bottom:1px solid #283650;display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:12px}
.snapshot-title{font-size:17px;font-weight:750;letter-spacing:.02em;color:#f1f5f9}
.snapshot-sub{font-size:12px;color:#9db1cd;margin-top:5px}
.snapshot-pills{display:flex;gap:7px;align-items:center;flex-wrap:wrap}
.snapshot-pill{display:inline-block;border:1px solid #38506d;border-radius:6px;padding:7px 10px;font:650 11px ui-monospace,monospace;color:#a7c8fa;background:#14233b}
.snapshot-pill.disabled{opacity:.48;cursor:not-allowed}
.snapshot-pill.active{border-color:#3b82f6;background:#183865;color:#e4efff}
.snapshot-cards{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px;padding:16px 20px}
.snapshot-card{background:#0b1425;border:1px solid #273955;border-radius:10px;padding:17px;min-width:0}
.snapshot-card small{font-size:11px;color:#90a5c4;text-transform:uppercase;letter-spacing:.07em}
.snapshot-card strong{display:block;font:750 clamp(19px,2.2vw,28px) ui-monospace,monospace;margin:10px 0 4px;overflow-wrap:anywhere}
.snapshot-card p{font-size:11px;margin:0;color:#9baeca}
.snapshot-card.ce strong{color:#3bddaa}.snapshot-card.pe strong{color:#fb7185}.snapshot-card.neutral strong{color:#7cb5ff}
.snapshot-toolbar{padding:12px 20px;border-top:1px solid #263650;border-bottom:1px solid #263650;display:flex;gap:12px;justify-content:space-between;align-items:center;flex-wrap:wrap}
.snapshot-toolbar .filters{margin:0}.snapshot-toolbar .filters label{font-size:11px}
.snapshot-toolbar .filters input,.snapshot-toolbar .filters select{background:#0b1628}
.snapshot-table{overflow:auto;max-width:100%;max-height:670px}
.snapshot-table table{min-width:1530px;width:100%;font:12px ui-monospace,SFMono-Regular,monospace}
.snapshot-table th{position:sticky;top:0;z-index:2;background:#17253b;color:#a7b8d2;padding:13px 12px;font-size:10px;letter-spacing:.07em}
.snapshot-table th:first-child{z-index:3;background:#17253b}
.snapshot-table td{padding:13px 12px;vertical-align:top;background:#0d1728;line-height:1.6}
.snapshot-table td:first-child{background:#101e32;z-index:1;font-weight:700;color:#dae9fd}
.snapshot-table tr:nth-child(even) td{background:#101c30}
.snapshot-table tr:nth-child(even) td:first-child{background:#14223a}
.snapshot-table tr:hover td{background:#1b2c47}
.snapshot-table .mono-sub{font-size:10px;color:#91a5c5}
.snapshot-table .good{color:#4be0b2}.snapshot-table .bad{color:#ff899a}.snapshot-table .unknown{color:#8295b0}
.snapshot-foot{padding:12px 20px;border-top:1px solid #263650;display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap}
.snapshot-note{margin:0;padding:0 20px 14px;font-size:11px;color:#9aacbf}
.snapshot-foot .button,.snapshot-top .button{background:#1c3f68;border-color:#426697}
.snapshot-copy{background:#2563eb;border-color:#4b8af4}
#copy-status{font-size:11px;color:#9dddc8}
@media(max-width:820px){main{padding:10px}.snapshot-cards{grid-template-columns:1fr;padding:12px}.snapshot-top,.snapshot-toolbar,.snapshot-foot{padding:12px}.snapshot-table{max-height:550px}}
"""


def _number(value, decimals=0):
    if value is None:
        return '—'
    try:
        return f'{float(value):,.{decimals}f}'
    except (ValueError, TypeError, OverflowError):
        return '—'


def _td(main, sub='', cls=''):
    return '<td class="' + escape(cls, quote=True) + '">' + escape(str(main)) + (
        '<div class="mono-sub">' + escape(str(sub)) + '</div>' if sub else '') + '</td>'



def _valid_session(stamp):
    from datetime import time
    local = datetime.fromtimestamp(stamp, IST)
    return time(9, 15) <= local.time() <= time(15, 40)


def _delta(current, previous, index):
    if current is None or previous is None:
        return None
    try:
        a, b = float(current[index]), float(previous[index])
        import math
        return a - b if math.isfinite(a) and math.isfinite(b) else None
    except (TypeError, ValueError, IndexError):
        return None


def _signed(value, places=0):
    return ('+' if value > 0 else '') + _number(value, places) if value is not None else '—'


def _activity(doi, dprice, dvolume):
    """A descriptive OI/price proxy; never buyer/seller trade identification."""
    if doi is None or dprice is None or dvolume is None or dvolume < 0:
        return None
    if doi > 0 and dprice < 0:
        return 'WRITING-LIKE'
    if doi > 0 and dprice > 0:
        return 'LONG-ADDITION-LIKE'
    if doi < 0 and dprice > 0:
        return 'SHORT-COVERING-LIKE'
    if doi < 0 and dprice < 0:
        return 'LONG-UNWINDING-LIKE'
    return 'UNCONFIRMED'


def _futures_quad(dp, doi):
    if dp is None or doi is None:
        return 'OI unavailable'
    if dp > 0 and doi > 0:
        return 'LONG BUILDUP · proxy'
    if dp < 0 and doi > 0:
        return 'SHORT BUILDUP · proxy'
    if dp > 0 and doi < 0:
        return 'SHORT COVERING · proxy'
    if dp < 0 and doi < 0:
        return 'LONG UNWINDING · proxy'
    return 'FLAT / UNCONFIRMED'


def history_html(data):
    """Populate observed market quantities and time-aligned descriptive proxies."""
    def options(values, selected):
        return '<option value="">Select</option>' + ''.join(
            '<option value="' + escape(str(v), quote=True) + '"' +
            (' selected' if str(v) == str(selected) else '') + '>' +
            escape(str(v)) + '</option>' for v in values)

    query = dict(date=data['day'], expiry=data['expiry'], strike=data['strike'])
    export_url = '/export?' + urlencode(dict(query, page=data['page']))
    stamps = defaultdict(dict)
    for row in data['rows']:
        stamps[row[0]][row[1]] = row
    all_stamps = defaultdict(dict)
    for row in data['rows'] + data.get('prior_rows', []):
        all_stamps[row[0]][row[1]] = row
    sorted_times = sorted(all_stamps)
    previous_time = {stamp: sorted_times[i - 1] if i else None for i, stamp in enumerate(sorted_times)}
    regular = [t for t in stamps if _valid_session(t)]
    latest_ts = max(regular) if regular else None
    latest = stamps[latest_ts] if latest_ts is not None else {}
    latest_ce = latest.get('CE', [None, None, None])[2]
    latest_pe = latest.get('PE', [None, None, None])[2]
    balance = float(latest_pe) - float(latest_ce) if latest_ce is not None and latest_pe is not None else None
    last_seen = datetime.fromtimestamp(latest_ts, IST).strftime('%d %b %Y %H:%M:%S IST') if latest_ts else 'No regular-session observations'
    html = [
        '<article class="snapshot-shell" id="strike-terminal">',
        '<div class="snapshot-top"><div><div class="snapshot-title">PRO TRADER ACADEMY · NIFTY STRIKE OI TERMINAL</div>',
        '<div class="snapshot-sub">Expiry ' + escape(data['expiry'] or '—') +
        ' · Strike ' + escape(data['strike'] or '—') +
        ' · Latest session observation ' + escape(last_seen) + '</div></div>',
        '<div class="snapshot-pills"><span class="snapshot-pill disabled">1 MIN · NOT COLLECTED</span>',
        '<span class="snapshot-pill active">3 MIN · OBSERVATIONS</span>',
        '<span class="snapshot-pill">OI / PREMIUM PROXIES · NOT TRADE SIGNALS</span></div></div>',
        '<div class="snapshot-cards">',
        '<div class="snapshot-card ce"><small>CE open interest · latest in-session</small><strong>' + _number(latest_ce) +
        '</strong><p>Observed CE OI · not CE GEX</p></div>',
        '<div class="snapshot-card pe"><small>PE open interest · latest in-session</small><strong>' + _number(latest_pe) +
        '</strong><p>Observed PE OI · not PE GEX</p></div>',
        '<div class="snapshot-card neutral"><small>PE − CE OI · latest in-session</small><strong>' +
        _signed(balance) + '</strong><p>Same-strike difference only, not net GEX</p></div></div>',
        '<div class="snapshot-toolbar"><form class="filters" action="/" method="get">',
        '<label>SESSION DATE · IST<input type="date" name="date" value="' + escape(data['day'], quote=True) + '" required></label>',
        '<label>EXPIRY<select name="expiry">' + options(data['expiries'], data['expiry']) + '</select></label>',
        '<label>STRIKE<select name="strike">' + options(data['strikes'], data['strike']) + '</select></label>',
        '<button type="submit">Apply filters</button>',
        '<a class="button" href="/?' + escape(urlencode(query), quote=True) + '">Refresh</a></form>',
        '<div><button class="snapshot-copy" type="button" data-export-url="' + escape(export_url, quote=True) +
        '" id="copy-snapshots">📋 Copy Table as Text</button> <a class="button" href="' +
        escape(export_url, quote=True) + '">Export TXT</a> <span id="copy-status" role="status"></span></div></div>',
        '<div class="snapshot-table" role="region" aria-label="Stored option snapshots" tabindex="0"><table>',
        '<thead><tr><th>Observed<br>IST</th><th>Strike OI<br>CE / PE Δ</th>',
        '<th>Stored gamma<br>not GEX</th><th>OI neutralization<br>writing-like proxy</th>',
        '<th>PE writing<br>proxy</th><th>CE writing<br>proxy</th>',
        '<th>PE buying<br>proxy</th><th>CE buying<br>proxy</th>',
        '<th>PE seller exit<br>proxy</th><th>CE seller exit<br>proxy</th>',
        '<th>Futures<br>price &amp; OI</th></tr></thead><tbody>'
    ]
    for stamp in sorted(stamps, reverse=True):
        pair = stamps[stamp]
        c, p = pair.get('CE'), pair.get('PE')
        before = previous_time.get(stamp)
        valid = (before is not None and _valid_session(stamp) and _valid_session(before)
                 and 0 < stamp - before <= 360
                 and datetime.fromtimestamp(before, IST).date() == datetime.fromtimestamp(stamp, IST).date())
        prior = all_stamps.get(before, {}) if valid else {}
        data_by_side = {}
        for side, row in [('CE', c), ('PE', p)]:
            old = prior.get(side)
            oi_diff = _delta(row, old, 2) if valid else None
            vol_diff = _delta(row, old, 3) if valid else None
            premium_diff = _delta(row, old, 4) if valid else None
            if vol_diff is not None and vol_diff < 0:  # reject session resets and revised counters
                vol_diff = None
            signal = _activity(oi_diff, premium_diff, vol_diff)
            data_by_side[side] = (row, oi_diff, vol_diff, premium_diff, signal)
        _, cd, cv, cp, ca = data_by_side['CE']
        _, pd, pv, pp, pa = data_by_side['PE']

        def field(row, idx, places=0):
            return _number(row[idx], places) if row is not None else '—'

        ce_oi, pe_oi = field(c, 2), field(p, 2)
        ce_gamma, pe_gamma = field(c, 7, 6), field(p, 7, 6)
        lead = None
        if cd is not None and pd is not None:
            lead = pd - cd
        classification = 'PE writing-like' if pa == 'WRITING-LIKE' else 'CE writing-like' if ca == 'WRITING-LIKE' else 'No writing-like flow'
        if pa == 'WRITING-LIKE' and ca == 'WRITING-LIKE':
            classification = 'Both sides writing-like'
        futrow = c if c is not None else p
        oldfut = prior.get('CE') or prior.get('PE')
        fp = _delta(futrow, oldfut, 8) if valid else None
        fo = _delta(futrow, oldfut, 9) if valid and futrow is not None and oldfut is not None and futrow[9] and oldfut[9] else None
        futdesc = _futures_quad(fp, fo) if valid else 'Outside comparable session window'
        fmt = lambda side, expected: (
            (_signed(data_by_side[side][1]) + ' OI | Δvol ' + _signed(data_by_side[side][2]))
            if data_by_side[side][4] == expected else '—'
        )
        stamp_label = datetime.fromtimestamp(stamp, IST).strftime('%H:%M:%S')
        html.append('<tr>')
        html.append(_td(stamp_label, 'IN-SESSION OBSERVATION' if _valid_session(stamp) else 'AFTER-HOURS · NOT COMPARABLE'))
        html.append(_td('CE ' + ce_oi + ' | PE ' + pe_oi,
                        'CE Δ ' + _signed(cd) + ' | PE Δ ' + _signed(pd) +
                        (' | PE−CE Δ ' + _signed(lead) if lead is not None else '')))
        html.append(_td('CE ' + ce_gamma + ' / PE ' + pe_gamma,
                        'Notional GEX: unavailable · no new valuation'))
        html.append(_td(classification if valid else 'Not comparable',
                        'PE Δ ' + _signed(pd) + ' | CE Δ ' + _signed(cd) + ' · no seller identification'))
        html.append(_td(fmt('PE', 'WRITING-LIKE'), 'Premium Δ ' + _signed(pp, 2) + ' | model proxy'))
        html.append(_td(fmt('CE', 'WRITING-LIKE'), 'Premium Δ ' + _signed(cp, 2) + ' | model proxy'))
        html.append(_td(fmt('PE', 'LONG-ADDITION-LIKE'), 'Premium Δ ' + _signed(pp, 2) + ' | model proxy'))
        html.append(_td(fmt('CE', 'LONG-ADDITION-LIKE'), 'Premium Δ ' + _signed(cp, 2) + ' | model proxy'))
        html.append(_td(fmt('PE', 'SHORT-COVERING-LIKE'), 'Premium Δ ' + _signed(pp, 2) + ' | model proxy'))
        html.append(_td(fmt('CE', 'SHORT-COVERING-LIKE'), 'Premium Δ ' + _signed(cp, 2) + ' | model proxy'))
        html.append(_td('Fut ' + field(futrow, 8, 2),
                        'Δprice ' + _signed(fp, 2) + ' | ΔOI ' + _signed(fo) + ' | ' + futdesc))
        html.append('</tr>')
    if not stamps:
        html.append('<tr><td colspan="11">' +
                    escape(data['error'] or 'No snapshots for this date, expiry and strike.') + '</td></tr>')
    html.extend(['</tbody></table></div>',
        '<div class="snapshot-foot"><small>' + str(data['total']) +
        ' saved timestamps · page ' + str(data['page'] + 1) + '</small><div>'])
    for label, number in [('« Newer', data['page'] - 1), ('Older »', data['page'] + 1)]:
        if number >= 0 and (number < data['page'] or number * 12 < data['total']):
            html.append('<a class="button" href="/?' +
                        escape(urlencode(dict(query, page=number)), quote=True) + '">' + label + '</a> ')
    html.append('</div></div><p class="snapshot-note">Calculated values are same-contract, consecutive observation differences, not exchange trade-side data. Writing, buying and seller-exit labels are descriptive OI/premium proxies only, not actual counterparty identification. No 1-minute bars or dealer notional GEX are reconstructed. Outside-session snapshots and gaps over 6 minutes have no change-based classification.</p></article>')
    return ''.join(html)
