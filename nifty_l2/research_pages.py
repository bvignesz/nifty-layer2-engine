"""Read-only research pages, deliberately independent of the valuation engine."""
from datetime import datetime
from html import escape
from .storage import IST
from .research_readmodel import research_history,expiry_matrix,readiness

def esc(x):
    return escape(str(x if x is not None else "—"))

def page(title,body):
    css="body{background:#0b1020;color:#e4edf9;font:14px system-ui;margin:0}main{max-width:1600px;margin:auto;padding:22px}a{color:#92beff}nav{display:flex;gap:16px;flex-wrap:wrap;margin:20px 0}section{background:#121e30;border:1px solid #30405a;border-radius:12px;padding:16px;overflow:auto}table{border-collapse:collapse;width:100%;min-width:850px}td,th{border-bottom:1px solid #324158;padding:11px;text-align:left}th{color:#a7bcd7;font-size:11px;text-transform:uppercase}small{color:#a8bad2}input,button{background:#14243d;color:white;border:1px solid #50637d;padding:8px;border-radius:6px}code{font-size:11px}"
    return ('<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>'+esc(title)+'</title><style>'+css+'</style><main><h2>PRO TRADER ACADEMY · '+esc(title)+'</h2><small>Stored FYERS research · not live trading signals</small><nav><a href="/">Strike terminal</a><a href="/research">Nine checks</a><a href="/expiries">Expiry matrix</a><a href="/eod">EOD scanner</a><a href="/validation">Validation</a></nav>'+body+'</main></html>')

def render(directory,tab,params):
    day=params.get("date",[datetime.now(IST).date().isoformat()])[0]
    if tab=="research":
        result=research_history(directory,day)
        rows=[]
        for x in result["rows"]:
            m=x["meta"]
            flags=" ".join(str(q["number"])+":"+esc(q["bull"])+"/"+esc(q["bear"]) for q in x["checks"])
            rows.append("<tr>"+''.join("<td>"+esc(v)+"</td>" for v in (x["observed_at_utc"],x["quality_status"],x["classification"],x["original_verdict"],m["spot"],m["gex"],m["put_wall"],m["call_wall"],flags))+"</tr>")
        html='<section><form><input type="date" name="date" value="'+esc(day)+'"><button>Load</button></form><h3>Historical nine-check results</h3><table><tr>'+''.join("<th>"+x+"</th>" for x in ("Observed UTC","Quality","Validated","Legacy verdict","Spot","GEX scenario","PE wall","CE wall","Checks B/B"))+'</tr>'+(''.join(rows) or '<tr><td>No stored results</td></tr>')+'</table></section>'
        return page("Nine-check history",html)
    if tab=="expiries":
        strike=params.get("strike",["24450"])[0]
        data=expiry_matrix(directory,day,strike)
        cols=("expiry","side","observed_at_ist","symbol","ltp","bid","ask","oi","iv","delta","gamma","theta","vega")
        rows=['<tr>'+''.join('<td>'+esc(r.get(k))+'</td>' for k in cols)+'</tr>' for r in data["rows"]]
        html='<section><form><input type="date" name="date" value="'+esc(day)+'"><input type="number" name="strike" value="'+esc(strike)+'" min="1"><button>Load</button></form><h3>Real saved expiries only</h3><small>Missing W1/W2 expiries remain unavailable, not simulated.</small><table><tr>'+''.join('<th>'+x+'</th>' for x in cols)+'</tr>'+(''.join(rows) or '<tr><td>No saved contracts for this selection</td></tr>')+'</table></section>'
        return page("Expiry matrix",html)
    if tab=="eod":
        return page("EOD scanner",'<section><h3>Not yet connected</h3><p>Separate FYERS EOD migration must preserve the original two-track RS–W%R3–POC strategy. No stock signals are fabricated.</p></section>')
    if tab=="validation":
        data=readiness(directory)
        return page("Validation readiness",'<section><table>'+''.join('<tr><th>'+esc(k)+'</th><td>'+esc(v)+'</td></tr>' for k,v in data.items())+'</table><p>No ML training until outcome labels and freshness are independently validated.</p></section>')
    raise ValueError("Unknown research page")
