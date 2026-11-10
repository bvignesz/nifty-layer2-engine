"""Private Indian cash swing terminal: display saved EOD scanner output only.

The existing scanner's output CSV remains the source of truth. No synthetic
rank, entry, stop, POC, expectancy or validation state is created here.
"""
from html import escape
from eod_scanner.readmodel import results

TRACKS=("ALL","EMA_PULLBACK","RS_WR3_POC","LARRY_AD_BOF","BREAKOUT")

def swing_snapshot(directory,*,track="ALL",limit=100):
    if track not in TRACKS:raise ValueError("Unknown setup track")
    if not isinstance(limit,int) or not 1<=limit<=100:raise ValueError("Invalid EOD limit")
    data=results(directory,limit=limit)
    rows=data["rows"]
    if track!="ALL":
        def match(row):
            value=(row.get("Strategy_Track") or "").upper().replace("-","_").replace(" ","_")
            if track=="RS_WR3_POC":
                return ("POC" in value and ("WR" in value or "W%R" in value))
            if track=="LARRY_AD_BOF":
                return "LARRY" in value or "BOF" in value or "WYCKOFF" in value
            if track=="EMA_PULLBACK":
                return "EMA" in value or "PULLBACK" in value
            return "BREAKOUT" in value
        rows=[r for r in rows if match(r)]
    return {**data,"rows":rows,"selected_track":track,
        "available_tracks":list(TRACKS),"displayed":len(rows),
        "data_timestamp_source":"As_Of column from uploaded EOD scanner CSV",
        "execution":"MANUAL_ONLY","orders_enabled":False,
        "strategy_profitability_verified":False}

def render_swing(data):
    esc=lambda x:escape(str(x)) if x is not None and x!="" else "—"
    fields=[
      ("Symbol","SYMBOL"),("As_Of","AS-OF"),("Strategy_Track","SETUP"),
      ("Research_State","RESEARCH STATE"),("Actionability","CANDIDATE"),
      ("Close","LAST CLOSE"),("RS_Excess_20D_Pct","RS 20D %"),
      ("Williams_R_3","W%R3"),("Setup_POC","EST. POC"),
      ("VAL","VAL"),("VAH","VAH"),("Stop_Loss_Structural","STRUCTURAL STOP"),
      ("Risk_Reward_Ratio","EST. R:R"),("Data_Quality","DATA QUALITY")]
    heads="".join("<th>"+esc(label)+"</th>" for _,label in fields)
    cells=[]
    for r in data["rows"]:
        fields_html=[]
        for field,_ in fields:
            value=r.get(field)
            cls=""
            if field=="Research_State" and value:
                if "CONFIRM" in value.upper():cls=' class="good"'
                elif "REJECT" in value.upper():cls=' class="bad"'
            fields_html.append("<td"+cls+">"+esc(value)+"</td>")
        cells.append("<tr>"+"".join(fields_html)+"</tr>")
    rows="".join(cells) or '<tr><td colspan="14">No saved candidates for this setup. Run or import the separate EOD scanner first; this screen does not fabricate symbols.</td></tr>'
    track=data["selected_track"]
    options="".join('<option value="'+esc(t)+'"'+(" selected" if t==track else "")+'>'+esc(t.replace("_"," "))+'</option>' for t in TRACKS)
    css="""body{margin:0;background:#09111f;color:#d8e7f7;font:13px system-ui}
main{padding:20px;max-width:1960px;margin:auto}h1{font-size:21px;margin-bottom:6px}
nav{display:flex;gap:15px;flex-wrap:wrap;margin:14px 0 20px}
a{color:#8fc5ff}.meta{color:#9cb0cc}
.card{border:1px solid #283b53;background:#101d32;border-radius:12px;padding:16px;margin:13px 0}
.scroll{overflow:auto;max-height:75vh}table{border-collapse:collapse;min-width:1750px;width:100%;font:12px ui-monospace,monospace}
th{background:#152943;position:sticky;top:0;z-index:2;color:#b9cbe1;text-align:left}
td,th{padding:11px;border:1px solid #293d58;white-space:nowrap}
td:first-child,th:first-child{position:sticky;left:0;background:#14263d;z-index:3}
.good{color:#54deae}.bad{color:#ff909e}
button,select{background:#1b344e;border:1px solid #496582;color:#eaf2ff;border-radius:6px;padding:8px}
.num{font-weight:800;font-size:21px}small{color:#a5b8d2}
"""
    return ('<!doctype html><html lang="en"><meta charset="utf-8">'
      '<meta name="viewport" content="width=device-width,initial-scale=1">'
      '<title>PRO TRADER ACADEMY · INDIAN SWING ENGINE</title><style>'+css+
      '</style><main><nav><a href="/desk">NIFTY Options Desk</a>'
      '<a href="/swing">Indian Swing Engine</a><a href="/quantum">Quantum Alignment</a><a href="/eod">Legacy EOD Archive</a>'
      '<a href="/validation">Validation</a></nav>'
      '<h1>PRO TRADER ACADEMY · INDIAN SWING ENGINE</h1>'
      '<p class="meta">NIFTY 500 research · Relative strength · EMA pullback · '
      'RS–W%R3–POC · Larry Williams A/D + BOF · Manual execution only</p>'
      '<div class="card"><strong>Saved EOD scanner</strong>'
      '<div class="num">'+str(data["displayed"])+' candidates</div>'
      '<p class="meta">Source status: '+esc(data["status"])+
      ' · Original CSV as-of timestamps · Historical alpha unverified</p></div>'
      '<div class="card"><form action="/swing" method="get">'
      '<label for="track">Setup family</label> <select id="track" name="track">'+options+
      '</select> <button type="submit">Filter</button></form>'
      '<p class="meta">RS/POC and risk targets are displayed only when produced by '
      'the original EOD scanner. Missing values remain unavailable.</p>'
      '<div class="scroll"><table><thead><tr>'+heads+'</tr></thead><tbody>'+rows+
      '</tbody></table></div></div>'
      '<small>Research only. NSE constituent history, corporate-action adjustment, '
      'liquidity constraints and actual broker fills still require end-to-end validation.</small>'
      '</main></html>')
