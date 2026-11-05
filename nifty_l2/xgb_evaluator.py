"""Explicit, offline, research-only XGBoost walk-forward evaluation.

No automatic training or signal delivery. Requires VERIFIED labels and 20+
independent trading days. Model results are NOT a live buy/sell classifier.
"""
import csv
from datetime import datetime,timedelta
import json
from pathlib import Path
from .ml_shadow import FEATURES,MIN_DAYS,MIN_ROWS

def load_verified(path):
    with Path(path).open(newline="",encoding="utf-8") as f:
        rows=list(csv.DictReader(f))
    clean=[]
    import math
    for row in rows:
        if row.get("label_status")!="VALIDATED":continue
        try:
            instant=datetime.fromisoformat(row["observed_at_utc"].replace("Z","+00:00"))
            if instant.tzinfo is None:continue
            vals=[float(row[k]) for k in FEATURES]
            fwd=float(row["forward_return"])
            if all(math.isfinite(z) for z in vals+[fwd]):
                clean.append((instant,vals,int(fwd>0)))
        except (TypeError,KeyError,ValueError):continue
    clean.sort(key=lambda r:r[0])
    if len(clean)<MIN_ROWS or len({x[0].date() for x in clean})<MIN_DAYS:
        raise ValueError("Insufficient independently validated observations/days")
    return clean

def evaluate(path):
    data=load_verified(path)
    # Lazy imports: AWS live collector has no ML package requirement.
    try:
        from xgboost import XGBClassifier
        from sklearn.metrics import roc_auc_score,brier_score_loss,accuracy_score
    except ImportError as exc:
        raise RuntimeError("Offline research requires optional xgboost and scikit-learn") from exc
    days=sorted({r[0].date() for r in data})
    # Three strictly forward, non-overlapping day-level test partitions.
    cuts=[int(len(days)*x) for x in (.5,.65,.8,1.)]
    reports=[]
    for i in range(3):
        train_days=set(days[:cuts[i]])
        test_days=set(days[cuts[i]:cuts[i+1]])
        if not train_days or not test_days:continue
        first_test=min(x[0] for x in data if x[0].date() in test_days)
        # Purge/embargo the 30-minute maximum label horizon.
        cutoff=first_test-timedelta(minutes=30)
        train=[r for r in data if r[0].date() in train_days and r[0]<cutoff]
        test=[r for r in data if r[0].date() in test_days]
        if len(train)<60 or len(test)<15 or len({r[2] for r in train})<2:
            reports.append({"fold":i+1,"status":"INSUFFICIENT_SPLIT_DATA",
                            "train":len(train),"test":len(test)})
            continue
        model=XGBClassifier(n_estimators=120,max_depth=3,learning_rate=.04,
            subsample=.8,colsample_bytree=.8,reg_lambda=3,
            random_state=42,tree_method="hist",eval_metric="logloss",n_jobs=1)
        model.fit([r[1] for r in train],[r[2] for r in train])
        prob=model.predict_proba([r[1] for r in test])[:,1]
        actual=[r[2] for r in test]
        reports.append({"fold":i+1,"status":"EVALUATED",
            "train":len(train),"test":len(test),"test_start":first_test.isoformat(),
            "accuracy":float(accuracy_score(actual,prob>=.5)),
            "brier":float(brier_score_loss(actual,prob)),
            "roc_auc":float(roc_auc_score(actual,prob)) if len(set(actual))>1 else None,
            "positive_base_rate":sum(actual)/len(actual)})
    return {"model":"XGBoost research-only","features":list(FEATURES),
            "folds":reports,"strategy_profitability_verified":False,
            "note":"No transaction costs, trade fills, realized expectancy or data-source validation are implied."}

def main(argv=None):
    import argparse
    parser=argparse.ArgumentParser()
    parser.add_argument("--validated-csv",required=True)
    parser.add_argument("--report",required=True)
    args=parser.parse_args(argv)
    path=Path(args.report)
    if path.exists():parser.error("Refusing to overwrite existing report")
    report=evaluate(args.validated_csv)
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open("x",encoding="utf-8") as f:
        json.dump(report,f,indent=2,allow_nan=False)
    print("Research evaluation report:",path)

if __name__=="__main__":main()
