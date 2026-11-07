"""Render enhanced research desk using the established video-style wide table."""
from html import escape
from .microstructure_terminal import render as render_microstructure

def render_desk(data):
    html=render_microstructure(data)
    flags=data["readiness"]
    counts=data["counts"]
    journal=data.get("journal",{})
    memory=data.get("market_memory",{})
    states=[
      ("Stored research runs",counts["research_runs"]),
      ("Completed futures records",counts["futures_bars"]),
      ("Validated forward labels",counts["valid_outcomes"]),
      ("Live option exchange stamps","verified in events" if flags["live_option_exchange_timestamps_verified"] else "not verified"),
      ("Historical bid/ask option fills","not verified"),
      ("Trading mode","MANUAL REVIEW ONLY"),
      ("Manual trades recorded",journal.get("total",0)),
      ("Journal mean realized R",journal.get("mean_realized_r") if journal.get("mean_realized_r") is not None else "—"),
      ("Historical market cases",memory.get("cases",0)),
      ("Verified case sessions",memory.get("sessions",0)),
      ("AI quality filter", "Data required" if not memory.get("trained_meta_model") else "Shadow only")]
    cards=''.join('<div style="background:#101d32;border:1px solid #283b53;border-radius:7px;padding:12px">'
          '<div style="color:#98b2ce;font-size:11px">'+escape(str(label))+'</div>'
          '<strong style="display:block;margin-top:6px">'+escape(str(value))+'</strong></div>'
          for label,value in states)
    header=('<section aria-label="Research desk data status" style="margin:14px 0 22px">'
       '<h2 style="font-size:15px">RESEARCH DESK · FYERS DATA READINESS</h2>'
       '<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:8px">'
       +cards+'</div><p class="meta">BULLISH WATCH and BEARISH WATCH describe the original '
       'research engine. They are not trade instructions or validated confidence estimates. '
       'Option OI timestamps and dealer positioning remain unresolved. '
       'Historical Market Memory shows cases only from verified mature replay outcomes. '
       'Similarity is descriptive, not a calibrated probability or trade recommendation.</p>'
       '<p><a href="/api/v1/desk?date='+escape(data["date_ist"],quote=True)+
       '">JSON research desk readout</a></p></section>')
    html=html.replace('action="/microstructure"','action="/desk"')
    html=html.replace('<a href="/">Home</a>','<a href="/">Home</a> · <a href="/microstructure">Raw microstructure</a>')
    html=html.replace('<div class="panel">',header+'<div class="panel">',1)
    return html
