"""Historical Market Memory: immutable, independently verified past setup cases.

A case is admitted only if its historical feature values were known at signal
time and its net-after-cost outcome had matured. Cases are stored in a separate
SQLite file; they never modify the nine-check engine, live feed, or trade journal.

Similarity retrieval is time-causal: event time < query time and outcome
availability <= query time; source/provenance checks apply to every row.
Similarity and empirical historical rates are RESEARCH ONLY, not probabilities
of profit or permission to place a trade.
"""
from datetime import datetime,timezone
from math import isfinite,sqrt
from pathlib import Path
import hashlib,json,os,sqlite3
from .xgboost_shadow import FEATURES

SCHEMA="""CREATE TABLE IF NOT EXISTS market_cases (
 case_id TEXT PRIMARY KEY, observed_at_utc TEXT NOT NULL,
 outcome_available_at_utc TEXT NOT NULL, session_date TEXT NOT NULL,
 strategy TEXT NOT NULL, symbol TEXT NOT NULL,
 regime TEXT NOT NULL, label_after_costs INTEGER NOT NULL CHECK(label_after_costs IN(0,1)),
 net_pnl_inr REAL NOT NULL, features_json TEXT NOT NULL,
 feature_observed_at_utc TEXT NOT NULL,
 source TEXT NOT NULL CHECK(source='VERIFIED_HISTORICAL_REPLAY'),
 evidence_sha256 TEXT NOT NULL,
 inserted_at_utc TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS market_cases_time ON market_cases(observed_at_utc,outcome_available_at_utc);
CREATE INDEX IF NOT EXISTS market_cases_strategy ON market_cases(strategy,regime,observed_at_utc);
"""
def aware(value):
    t=datetime.fromisoformat(str(value).replace("Z","+00:00"))
    if t.tzinfo is None:raise ValueError("timezone is mandatory")
    return t.astimezone(timezone.utc)

def finite(value):
    return isinstance(value,(int,float)) and not isinstance(value,bool) and isfinite(value)

def validated_features(features):
    if not isinstance(features,dict) or set(features)!=set(FEATURES):
        raise ValueError("all exact model features required")
    if any(not finite(features[k]) for k in FEATURES):
        raise ValueError("non-finite historical feature")
    return {k:float(features[k]) for k in FEATURES}

def validate_case(case):
    required=("case_id","observed_at_utc","outcome_available_at_utc",
      "feature_observed_at_utc","session_date","strategy","symbol","regime",
      "label_after_costs","net_pnl_inr","features","source",
      "evidence_sha256")
    if not isinstance(case,dict) or any(k not in case for k in required):
        raise ValueError("missing case provenance")
    if any(not isinstance(case[k],str) or not case[k] or len(case[k])>200
       for k in ("case_id","session_date","strategy","symbol","regime","source")):
        raise ValueError("bad case identity")
    if case["source"]!="VERIFIED_HISTORICAL_REPLAY":
        raise ValueError("research case needs broker replay provenance")
    h=case["evidence_sha256"]
    if not isinstance(h,str) or len(h)!=64 or any(c not in "0123456789abcdef" for c in h):
        raise ValueError("evidence SHA256 required")
    observed=aware(case["observed_at_utc"])
    feature=aware(case["feature_observed_at_utc"])
    available=aware(case["outcome_available_at_utc"])
    if feature>observed or available<=observed:
        raise ValueError("feature lookahead or outcome time invalid")
    from .storage import IST
    if observed.astimezone(IST).date().isoformat()!=case["session_date"]:
        raise ValueError("case session date mismatch")
    y=case["label_after_costs"]
    pnl=case["net_pnl_inr"]
    if isinstance(y,bool) or y not in (0,1) or not finite(pnl) or (pnl>0)!=(y==1):
        raise ValueError("outcome must agree with cost-adjusted P&L")
    values=validated_features(case["features"])
    return {**{k:case[k] for k in required if k!="features"},
            "features":values,
            "observed_at_utc":observed.isoformat(),
            "feature_observed_at_utc":feature.isoformat(),
            "outcome_available_at_utc":available.isoformat()}

def import_cases(db_path,cases,*,at=None):
    """Atomic append-only import, explicit market_memory.db required."""
    path=Path(db_path).expanduser().resolve()
    if path.name!="market_memory.db":raise ValueError("dedicated market_memory.db required")
    if not isinstance(cases,list) or not 1<=len(cases)<=100000:
        raise ValueError("1 to 100000 source cases per import")
    now=aware(at or datetime.now(timezone.utc))
    normalized=[validate_case(c) for c in cases]
    if len(set(c["case_id"] for c in normalized))!=len(normalized):
        raise ValueError("duplicate cases in batch")
    if any(aware(c["outcome_available_at_utc"])>now for c in normalized):
        raise ValueError("cannot import an outcome that has not occurred")
    path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    with sqlite3.connect(path,timeout=10) as db:
        db.execute("PRAGMA foreign_keys=ON")
        db.executescript(SCHEMA)
        db.executemany("""INSERT INTO market_cases VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
          [(c["case_id"],c["observed_at_utc"],c["outcome_available_at_utc"],
            c["session_date"],c["strategy"],c["symbol"],c["regime"],
            c["label_after_costs"],c["net_pnl_inr"],
            json.dumps(c["features"],sort_keys=True,allow_nan=False),
            c["feature_observed_at_utc"],c["source"],c["evidence_sha256"],
            now.isoformat()) for c in normalized])
    os.chmod(path,0o600)
    return {"status":"CASES_IMPORTED","added":len(normalized),
      "research_only":True,"orders_enabled":False}

def search_cases(db_path,*,at,features,strategy,regime=None,limit=30,
                 min_neighbors=30,min_sessions=10):
    """As-of nearest neighbors; avoids current/future information leakage."""
    query_at=aware(at)
    q=validated_features(features)
    if not isinstance(strategy,str) or not strategy.strip():
        raise ValueError("strategy required")
    if not isinstance(limit,int) or not 1<=limit<=100:
        raise ValueError("limit out of bounds")
    path=Path(db_path).expanduser().resolve()
    base={"status":"NO_VERIFIED_MEMORY","neighbors":[],"sample_count":0,
      "unique_sessions":0,"positive_outcome_fraction":None,
      "empirical_mean_net_pnl_inr":None,"quality_decision":"UNAVAILABLE",
      "prediction_is_calibrated":False,"orders_enabled":False,
      "research_only":True}
    if path.name!="market_memory.db" or not path.is_file():return base
    with sqlite3.connect(path.as_uri()+"?mode=ro",uri=True,timeout=5) as db:
        rows=db.execute("""SELECT case_id,observed_at_utc,outcome_available_at_utc,
          session_date,strategy,symbol,regime,label_after_costs,net_pnl_inr,
          features_json FROM market_cases WHERE observed_at_utc<?
          AND outcome_available_at_utc<=? AND strategy=?
          ORDER BY observed_at_utc DESC LIMIT 25000""",
          (query_at.isoformat(),query_at.isoformat(),strategy)).fetchall()
    cases=[]
    for r in rows:
        cid,observed,available,day,track,symbol,rreg,y,pnl,raw=r
        if regime is not None and rreg!=regime:continue
        f=json.loads(raw)
        cases.append((cid,observed,available,day,track,symbol,rreg,y,pnl,f))
    if not cases:return base
    # Scale every feature by *historical* dispersions only; min denominator
    # avoids overstating distances on nearly constant features.
    means={k:sum(c[9][k] for c in cases)/len(cases) for k in FEATURES}
    scales={k:max(1e-6,sqrt(sum((c[9][k]-means[k])**2
              for c in cases)/len(cases))) for k in FEATURES}
    scored=[]
    for c in cases:
        distance=sqrt(sum(((c[9][k]-q[k])/scales[k])**2
                  for k in FEATURES)/len(FEATURES))
        scored.append((distance,c))
    scored.sort(key=lambda item:(item[0],item[1][1],item[1][0]))
    nearest=scored[:limit]
    sessions={c[3] for _,c in nearest}
    samples=len(nearest)
    sufficient=samples>=min_neighbors and len(sessions)>=min_sessions
    base.update(status="SUFFICIENT_HISTORICAL_NEIGHBORS" if sufficient else
          "INSUFFICIENT_SIMILAR_CASES",sample_count=samples,
          unique_sessions=len(sessions),
          neighbors=[{"case_id":c[0],"observed_at_utc":c[1],
            "symbol":c[5],"regime":c[6],"distance":round(dist,5),
            "label_after_costs":c[7],"net_pnl_inr":c[8]}
            for dist,c in nearest])
    if sufficient:
        base["positive_outcome_fraction"]=round(sum(c[7] for _,c in nearest)/samples,4)
        base["empirical_mean_net_pnl_inr"]=round(sum(c[8] for _,c in nearest)/samples,2)
        base["quality_decision"]="HISTORICAL_CONTEXT_ONLY"
    return base

def memory_status(db_path):
    path=Path(db_path).expanduser().resolve()
    if path.name!="market_memory.db" or not path.is_file():
        return {"status":"NO_VERIFIED_MEMORY","cases":0,"sessions":0,"orders_enabled":False}
    with sqlite3.connect(path.as_uri()+"?mode=ro",uri=True) as db:
        count,days=db.execute("SELECT count(*),count(distinct session_date) FROM market_cases").fetchone()
    return {"status":"AVAILABLE" if count else "NO_VERIFIED_MEMORY",
      "cases":count,"sessions":days,"orders_enabled":False}
