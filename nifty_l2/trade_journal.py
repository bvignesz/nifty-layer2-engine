"""Isolated, append-only manual trading journal (NOT the research.db).

Recording an executed trade requires actual fills supplied by the owner.
This application contains NO broker execution, no position management and no
automated order actions. All realized R values are based on documented costs.
"""
from datetime import datetime,timezone
from pathlib import Path
from math import isfinite
import json,os,sqlite3

DDL="""CREATE TABLE IF NOT EXISTS executed_trades(
 trade_id TEXT PRIMARY KEY,
 setup_family TEXT NOT NULL,
 instrument TEXT NOT NULL,
 category TEXT NOT NULL CHECK(category IN ('OPTION','EQUITY')),
 side TEXT NOT NULL CHECK(side IN ('LONG','SHORT')),
 entry_at_utc TEXT NOT NULL,
 exit_at_utc TEXT NOT NULL,
 entry_fill REAL NOT NULL CHECK(entry_fill>0),
 exit_fill REAL NOT NULL CHECK(exit_fill>=0),
 quantity INTEGER NOT NULL CHECK(quantity>0),
 total_costs REAL NOT NULL CHECK(total_costs>=0),
 planned_risk_inr REAL NOT NULL CHECK(planned_risk_inr>0),
 realized_pnl_inr REAL NOT NULL,
 realized_r REAL NOT NULL,
 source TEXT NOT NULL CHECK(source='OWNER_REPORTED_MANUAL_FILL'),
 notes TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS executed_trades_exit ON executed_trades(exit_at_utc);"""

def _utc(value):
    t=datetime.fromisoformat(str(value).replace("Z","+00:00"))
    if t.tzinfo is None:raise ValueError("timestamps must contain timezone")
    return t.astimezone(timezone.utc).isoformat()

def _numeric(v,positive=False):
    if isinstance(v,bool) or not isinstance(v,(int,float)) or not isfinite(v):
        raise ValueError("nonfinite numeric input")
    if positive and v<=0 or not positive and v<0:
        raise ValueError("negative or zero value")
    return float(v)

def calculate_trade(*,trade_id,setup_family,instrument,category,side,
                    entry_at_utc,exit_at_utc,entry_fill,exit_fill,quantity,
                    total_costs,planned_risk_inr,notes=""):
    if not all(isinstance(v,str) and 0<len(v)<=128 for v in
               (trade_id,setup_family,instrument)) or not isinstance(notes,str) or len(notes)>1000:
        raise ValueError("invalid journal text fields")
    if category not in ("OPTION","EQUITY") or side not in ("LONG","SHORT"):
        raise ValueError("invalid category or side")
    if category=="OPTION" and side!="LONG":
        raise ValueError("options journal currently supports long-only contracts")
    start,end=_utc(entry_at_utc),_utc(exit_at_utc)
    if end<start:raise ValueError("exit before entry")
    entry=_numeric(entry_fill,True)
    exit_=_numeric(exit_fill)
    fees=_numeric(total_costs)
    risk=_numeric(planned_risk_inr,True)
    if not isinstance(quantity,int) or isinstance(quantity,bool) or quantity<1:
        raise ValueError("quantity must be a whole number")
    gross=(exit_-entry)*quantity if side=="LONG" else (entry-exit_)*quantity
    net=gross-fees
    return {"trade_id":trade_id,"setup_family":setup_family,
      "instrument":instrument,"category":category,"side":side,
      "entry_at_utc":start,"exit_at_utc":end,
      "entry_fill":entry,"exit_fill":exit_,"quantity":quantity,
      "total_costs":fees,"planned_risk_inr":risk,
      "realized_pnl_inr":round(net,2),"realized_r":round(net/risk,5),
      "source":"OWNER_REPORTED_MANUAL_FILL","notes":notes}

def record_trade(db_path,trade):
    """Explicit journal write in a NEW, dedicated trade_journal.db only."""
    p=Path(db_path).expanduser().resolve()
    if p.name!="trade_journal.db":
        raise ValueError("journal must be a separate trade_journal.db file")
    safe=calculate_trade(**trade)
    p.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    with sqlite3.connect(p,timeout=10) as conn:
        conn.executescript(DDL)
        conn.execute("""INSERT INTO executed_trades VALUES
          (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
          tuple(safe[k] for k in ("trade_id","setup_family","instrument","category",
              "side","entry_at_utc","exit_at_utc","entry_fill","exit_fill",
              "quantity","total_costs","planned_risk_inr","realized_pnl_inr",
              "realized_r","source","notes")))
    os.chmod(p,0o600)
    return safe

def journal_summary(db_path):
    p=Path(db_path).expanduser().resolve()
    if p.name!="trade_journal.db" or not p.is_file():
        return {"status":"NO_TRADES","total":0,"win_rate_pct":None,
                "mean_realized_r":None,"net_pnl_inr":None}
    with sqlite3.connect(p.resolve().as_uri()+"?mode=ro",uri=True,timeout=5) as conn:
        rows=conn.execute("SELECT realized_pnl_inr,realized_r FROM executed_trades").fetchall()
    if not rows:
        return {"status":"NO_TRADES","total":0,"win_rate_pct":None,
            "mean_realized_r":None,"net_pnl_inr":None}
    return {"status":"OWNER_REPORTED_MANUAL_FILLS","total":len(rows),
      "wins":sum(pnl>0 for pnl,_ in rows),
      "win_rate_pct":round(100*sum(pnl>0 for pnl,_ in rows)/len(rows),2),
      "mean_realized_r":round(sum(r for _,r in rows)/len(rows),4),
      "net_pnl_inr":round(sum(pnl for pnl,_ in rows),2),
      "research_only":True,"data_source":"MANUAL_OWNER_REPORTED_FILLS",
      "note":"Trade journal relies on the owner's reported fills and charges; no broker statement reconciliation."}
