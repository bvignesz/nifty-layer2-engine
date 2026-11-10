"""Single-purpose homepage: broker connection + run + premarket/news.

All tables and option valuation live on dedicated pages. No extra FYERS
market calls and no scraper are invoked from the page renderer.
"""
from html import escape
from datetime import datetime
import json
from .premarket_brief import read_brief
from .storage import IST

CSS="""body{margin:0;background:#09111f;color:#e0edfc;font:14px system-ui}
main{max-width:1450px;margin:auto;padding:20px}nav{display:flex;gap:14px;flex-wrap:wrap;margin:16px 0 24px}
nav a,a{color:#93c5fd}.brand{font-size:23px;font-weight:800}
small,.muted{color:#96acc7}h2{font-size:18px;margin:0 0 13px}
.card{background:#111d30;border:1px solid #2a4059;border-radius:13px;padding:17px;margin-bottom:16px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:14px}
ul{padding-left:20px}li{margin:10px 0}
table{width:100%;border-collapse:collapse}th,td{border-bottom:1px solid #31445d;text-align:left;padding:10px}
th{color:#b4cce5;font-size:11px;letter-spacing:1px}
button{background:#2463d6;color:white;border:0;padding:10px 15px;border-radius:7px;cursor:pointer}
.pill{display:inline-block;background:#25394e;padding:5px 8px;border-radius:5px;font:11px monospace}
.warn{color:#f5c97c}.ok{color:#52d9a9}
footer{color:#9cb2cd;margin:20px 0}p{line-height:1.6}
"""
def _e(x):
    return escape(str(x),quote=True)
def render_home(app,message=""):
    saved=app.token_path.exists()
    run=app.runner.status()
    running=run.get("status")=="RUNNING"
    brief=read_brief(app.runner.directory)
    csrf='<input type="hidden" name="csrf" value="'+_e(app.csrf)+'">'
    def button(action,label):
        return '<form method="post" action="'+action+'">'+csrf+'<button>'+_e(label)+'</button></form>'
    # Compatibility with private manual-login callback route.
    manual=(
      '<form method="post" action="/oauth/callback">'+csrf+
      '<label>Full FYERS redirect URL <input type="password" name="callback_url" required></label>'
      '<button>Complete connection</button></form>'
      ) if app.origin.startswith("http:") else ""
    checks="".join('<tr><td>'+_e(x["label"])+'</td><td class="'+
        ('ok' if x["status"]=="VERIFIED" else 'warn')+'">'+_e(x["status"])+'</td><td>'+
        _e(x["note"] or "Waiting for verified timestamped input")+'</td></tr>'
        for x in brief["checks"])
    headlines="".join('<li><a href="'+_e(x["url"])+
        '" target="_blank" rel="noopener noreferrer">'+_e(x["title"])+
        '</a><br><small>'+_e(x["source"])+' · '+
        _e(x["published_at_utc"])+'</small></li>' for x in brief["news"])
    try:
        result=json.loads((app.runner.directory/"result.json").read_text())
        verdict=_e(result.get("state",{}).get("final_verdict","UNAVAILABLE"))
    except (OSError,ValueError,TypeError,AttributeError):
        verdict="UNAVAILABLE"
    notice='<div class="card" role="status">'+_e(message)+'</div>' if message else ""
    refresh='<meta http-equiv="refresh" content="5;url=/">' if running else ""
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8">'+refresh+
      '<meta name="viewport" content="width=device-width,initial-scale=1">'
      '<title>Pro Trader Academy · Market Control Center</title><style>'+CSS+
      '</style></head><body><main><div class="brand">PRO TRADER ACADEMY</div>'
      '<p class="muted">Home · Pre-market intelligence and operator controls</p>'
      '<nav><a href="/">Home</a><a href="/desk">Options Desk</a>'
      '<a href="/swing">Swing Trading</a><a href="/quantum">Quantum Alignment</a>'
      '<a href="/microstructure">Microstructure</a><a href="/research">Nine Checks</a>'
      '<a href="/strike-terminal">Strike Snapshot Archive</a>'
      '<a href="/settings">Settings</a></nav>'+notice+
      '<div class="grid"><section class="card"><h2>1 · Connect FYERS</h2>'
      '<p><span class="pill">'+("TOKEN SAVED · NOT REVERIFIED" if saved else "NOT CONNECTED")+'</span></p>'+
      button("/connect","Connect FYERS")+
      (button("/quote","Verify & fetch quote") if saved else "")+manual+
      '<p class="muted">FYERS OTP remains with FYERS. Token freshness requires verification.</p></section>'
      '<section class="card"><h2>2 · Run nine-check script</h2>'
      '<p><span class="pill">'+_e(run.get("status","IDLE"))+'</span> · '+
      _e(run.get("message",""))+'</p>'+
      button("/run/stop","Stop run") if False else '')
