"""XGBoost *shadow* training from externally validated real session labels.

Never trains on legacy five unlabeled rows, random splits or unverified events.
No live trading inference, no orders. Uses chronological day-level holdout with
a full-day embargo, disables silently missing data, and saves only metrics.
"""
from datetime import date,datetime,timezone
import math

FEATURES=("wall_cut_ce_pct","wall_cut_pe_pct","oi_speed_ce","oi_speed_pe",
          "futures_price_delta","futures_oi_delta","vix_change_pct",
          "spot_vs_pdva","spot_vs_opening_range","volume_strength")
MIN_ROWS=1000
MIN_SESSIONS=45

def validate_training_rows(rows,*,min_rows=MIN_ROWS,min_sessions=MIN_SESSIONS):
    if not isinstance(rows,list) or len(rows)<min_rows:
        return {"status":"INSUFFICIENT_SAMPLES","rows":len(rows) if isinstance(rows,list) else 0}
    days=set()
    outcomes=set()
    timestamps=set()
    for row in rows:
        if not isinstance(row,dict):
            return {"status":"INVALID_ROWS"}
        try:
            day=date.fromisoformat(row["session_date"])
            ts=row["observed_at_utc"]
            observed=datetime.fromisoformat(ts.replace("Z","+00:00"))
            completed=datetime.fromisoformat(
                row["future_label_available_at_utc"].replace("Z","+00:00"))
            if observed.tzinfo is None or completed.tzinfo is None:
                return {"status":"INVALID_TIMESTAMP"}
            if observed.astimezone(timezone.utc).date()!=day:
                return {"status":"SESSION_DATE_TIMESTAMP_MISMATCH"}
            for col in FEATURES:
                v=row[col]
                if not isinstance(v,(int,float)) or isinstance(v,bool) or not math.isfinite(v):
                    return {"status":"UNVERIFIED_FEATURES","field":col}
            y=row["label_net_positive_after_costs"]
            if y not in (0,1) or isinstance(y,bool):
                return {"status":"INVALID_LABEL"}
            if row.get("source")!="VERIFIED_HISTORICAL_REPLAY":
                return {"status":"UNVERIFIED_SOURCE"}
            if completed<=observed:
                return {"status":"LOOKAHEAD_LABEL"}
        except (KeyError,TypeError,ValueError):
            return {"status":"INVALID_ROWS"}
        if ts in timestamps:return {"status":"DUPLICATE_TIMESTAMP"}
        timestamps.add(ts)
        days.add(day)
        outcomes.add(y)
    if len(days)<min_sessions:
        return {"status":"INSUFFICIENT_SESSIONS","sessions":len(days)}
    if len(outcomes)!=2:
        return {"status":"SINGLE_CLASS"}
    return {"status":"READY_FOR_SHADOW_TRAIN","rows":len(rows),
        "sessions":len(days),"features":list(FEATURES)}

def chronological_split(rows,*,holdout_fraction=.2):
    if not 0.10<=holdout_fraction<=0.35:raise ValueError("holdout fraction out of bounds")
    days=sorted({r["session_date"] for r in rows})
    n=max(2,int(len(days)*holdout_fraction))
    # Drop one full day before test to avoid overlapping intraday outcome horizons.
    train_days=set(days[:-(n+1)])
    test_days=set(days[-n:])
    return ([r for r in rows if r["session_date"] in train_days],
            [r for r in rows if r["session_date"] in test_days])

def train_shadow(rows,*,min_rows=MIN_ROWS,min_sessions=MIN_SESSIONS):
    quality=validate_training_rows(rows,min_rows=min_rows,min_sessions=min_sessions)
    if quality["status"]!="READY_FOR_SHADOW_TRAIN":
        return {"status":quality["status"],"quality":quality,
            "model_trained":False,"orders_enabled":False}
    try:
        import numpy as np
        from xgboost import XGBClassifier
        from sklearn.metrics import roc_auc_score,brier_score_loss
    except ImportError:
        return {"status":"DEPENDENCIES_MISSING","quality":quality,
                "model_trained":False,"orders_enabled":False}
    train,test=chronological_split(rows)
    y_train=np.asarray([int(r["label_net_positive_after_costs"]) for r in train])
    y_test=np.asarray([int(r["label_net_positive_after_costs"]) for r in test])
    if len(set(y_train))!=2 or len(set(y_test))!=2:
        return {"status":"SINGLE_CLASS_HOLDOUT","model_trained":False,
                "orders_enabled":False}
    x_train=np.asarray([[r[k] for k in FEATURES] for r in train],dtype=float)
    x_test=np.asarray([[r[k] for k in FEATURES] for r in test],dtype=float)
    model=XGBClassifier(n_estimators=120,max_depth=3,learning_rate=.04,
       subsample=.8,colsample_bytree=.8,objective="binary:logistic",
       eval_metric="logloss",random_state=46,n_jobs=1)
    model.fit(x_train,y_train)
    probabilities=model.predict_proba(x_test)[:,1]
    baseline=float(y_train.mean())
    return {"status":"SHADOW_MODEL_EVALUATED","model_trained":True,
       "train_rows":len(train),"test_rows":len(test),
       "train_sessions":len(set(r["session_date"] for r in train)),
       "holdout_sessions":len(set(r["session_date"] for r in test)),
       "holdout_auc":round(float(roc_auc_score(y_test,probabilities)),5),
       "holdout_brier":round(float(brier_score_loss(y_test,probabilities)),5),
       "baseline_brier":round(float(brier_score_loss(y_test,[baseline]*len(test))),5),
       "features":list(FEATURES),
       "prediction_release":"SHADOW_ONLY","orders_enabled":False,
       "note":"One chronological holdout is not proof of real-market edge. Requires walk-forward, CPCV and cost stress."}
