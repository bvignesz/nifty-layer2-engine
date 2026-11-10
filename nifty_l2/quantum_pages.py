"""Higher-timeframe alignment desk — three evidence layers, no order signals.

PREMARKET: timestamped checklist & macro news, informational until verified
market context is supplied.
DAILY: nine independent previous-session price/relative-strength factors.
INTRADAY: preserved nine-check research output, not a daily calculation.
GREEKS: require fresh exact-quote and contract-level Greeks.

Missing or conflicting evidence -> IGNORE. No automatic trades.
"""
from datetime import datetime,timezone
from html import escape
from pathlib import Path
import json
from .storage import IST
from .premarket_brief import read_brief
from .premarket_regime import classify_regime
from .daily_alignment import evaluate_daily,alignment_gate
from .live_feed_view import live_readmodel

def _read(path,max_bytes=8_000_000):
    p=Path(path)
    if not p.is_file() or p.stat().st_size>max_bytes:return None
    try:return json.loads(p.read_text(encoding="utf-8"))
    except (ValueError,OSError,UnicodeError):return None

def quantum_snapshot(directory,*,now=None):
    now=now or datetime.now(timezone.utc)
    if now.tzinfo is None:raise ValueError("aware timestamp required")
    directory=Path(directory)
    brief=read_brief(directory,now=now)
    day=now.astimezone(IST).date().isoformat()
    daily={"status":"UNAVAILABLE","bias":"MIXED","factors":[],
           "note":"Import 221+ verified previous-session EOD bars and benchmark; no daily OI invented."}
    daily_input=_read(directory/"daily-context.json")
    if isinstance(daily_input,dict):
        try:
            daily=evaluate_daily(daily_input["index_bars"],
               daily_input["benchmark_bars"],asof=day)
        except (KeyError,ValueError,TypeError):
            daily["status"]="INVALID_DAILY_CONTEXT"
    pm={"status":"UNVERIFIED","bias":"UNVERIFIED",
        "reasons":["PREMARKET_DATA_NOT_AUTHENTICATED"]}
    market=_read(directory/"market-regime.json",max_bytes=16000)
    if isinstance(market,dict) and market.get("date_ist")==day:
        try:
            obs=datetime.fromisoformat(market["observed_at_utc"].replace("Z","+00:00"))
            if obs.tzinfo is not None and 0<=(now-obs).total_seconds()<=300:
                values=market["inputs"]
                regime=classify_regime(**values)
                if (regime.get("bias") in ("BULLISH_RESEARCH","BEARISH_RESEARCH")
                   and brief["status"]=="BRIEF_AVAILABLE" and
                   brief["complete"] and not brief["event_risk"]):
                    pm={"status":"VERIFIED",
                        "bias":"BULL" if regime["bias"]=="BULLISH_RESEARCH" else "BEAR",
                        "regime":regime["regime"],"reasons":[]}
                else:
                    pm={"status":"UNVERIFIED","bias":"UNVERIFIED",
                        "reasons":regime.get("reasons",["CHECKLIST_NOT_COMPLETE"])}
        except (KeyError,TypeError,ValueError,OverflowError):
            pass
    run=_read(directory/"result.json",max_bytes=200000)
    intraday={"status":"UNVERIFIED","bias":"UNVERIFIED","bull":None,"bear":None}
    if isinstance(run,dict) and isinstance(run.get("state"),dict):
        state=run["state"]
        intraday.update(bias=state.get("final_verdict","UNVERIFIED"),
                        bull=state.get("meta",{}).get("bull_score"),
                        bear=state.get("meta",{}).get("bear_score"))
        # The original nine checks remain observations, not independently
        # verified completed 1m options microstructure observations.
        intraday["status"]="LEGACY_NINE_CHECKS_UNVALIDATED"
    feed=live_readmodel(directory,now=now)
    greeks={"status":"UNVERIFIED","direction":None,"quote_fresh":False}
    # A fresh broker receipt alone does not establish its option Greeks
    # timestamp, underlying units, dealer sign or all 9 institutional checks.
    decision=alignment_gate(premarket=pm,daily=daily,
       intraday=intraday,greeks=greeks)
    return {"status":"RESEARCH_ONLY","date_ist":day,"premarket":pm,
      "premarket_checklist":brief["checks"],"news_count":len(brief["news"]),
      "daily":daily,"intraday":intraday,"greeks":greeks,
      "feed_freshness_seconds":feed["freshness_seconds"],
      "decision":decision,
      "pipeline":["PREMARKET_CONTEXT","OPTION_GREEKS","NINE_CHECK_INTRADAY",
                  "NINE_FACTOR_DAILY_ALIGNMENT","HUMAN_REVIEW"],
      "orders_enabled":False}

def render_quantum(data):
    def e(x):return escape(str(x),quote=True)
    blocks=[
       ("1 · PRE-MARKET CONTEXT",data["premarket"].get("bias"),
         data["premarket"].get("status")),
       ("2 · OPTIONS GREEKS",data["greeks"].get("direction"),
         data["greeks"].get("status")),
       ("3 · INTRADAY NINE CHECKS",data["intraday"].get("bias"),
         data["intraday"].get("status")),
       ("4 · DAILY NINE-FACTOR CONTEXT",data["daily"].get("bias"),
         data["daily"].get("status")),
       ("5 · FINAL RESEARCH VERDICT",data["decision"]["verdict"],
         data["decision"]["status"])]
    cards="".join('<section class="card"><small>'+e(label)+'</small><h2>'+
        e(bias or "UNAVAILABLE")+'</h2><p>'+e(status)+'</p></section>'
        for label,bias,status in blocks)
    daily_rows="".join('<tr><td>'+e(i+1)+'</td><td>'+e(f["name"])+
       '</td><td>'+e(f["bull"])+'</td><td>'+e(f["bear"])+
       '</td></tr>' for i,f in enumerate(data["daily"].get("factors",[])))
    return ('''<!doctype html><html><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Pro Trader Academy · Quantum Decision Desk</title>
<style>body{background:#09111f;color:#dbeafe;font:14px system-ui;margin:0}
main{max-width:1540px;padding:22px;margin:auto}a{color:#93c5fd}
nav{display:flex;gap:18px;margin:15px 0;flex-wrap:wrap}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px}
.card{background:#101e32;border:1px solid #2d445f;border-radius:12px;padding:17px}
.card h2{font-size:20px}.card small{color:#96b3d0}p{color:#acbfd6}
table{border-collapse:collapse;width:100%}td,th{padding:9px;border-bottom:1px solid #304560;text-align:left}
th{color:#9fbfe6}</style><main><h1>QUANTUM DESK · Multi-Timeframe Alignment</h1>
<nav><a href="/">Home</a><a href="/desk">Options Desk</a>
<a href="/swing">Swing Engine</a><a href="/research">Original Nine Checks</a></nav>
<p>Previous completed trading-day direction must align with intraday
nine-check options signals and verified Greeks. Any missing layer means IGNORE.</p>
<div class="grid">'''+cards+'''</div>
<section class="card"><h2>Daily timeframe · Nine independent factors</h2>
<p>These are daily trend and relative-strength factors, not a duplicate
of the intraday OI-wall nine checks. No completed daily data = no daily alignment.</p>
<table><thead><tr><th>#</th><th>FACTOR</th><th>BULL</th><th>BEAR</th></tr>
</thead><tbody>'''+(daily_rows or
    '<tr><td colspan="4">Awaiting verified EOD history</td></tr>')+
    '''</tbody></table></section>
<section class="card"><h2>Institutional-style decision policy</h2>
<p>Macro risk → completed daily context → fresh instrument Greeks →
intraday nine-check confirmation → manual review. This is a research
workflow, not evidence of an institution's actual proprietary method.</p>
<strong>'''+e(data["decision"]["verdict"])+''' · NO AUTOMATIC ORDERS</strong>
</section></main></html>''')
