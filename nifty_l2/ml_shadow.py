"""Offline XGBoost research gate. Never auto-trains on live collector events.

Inputs must have independently checked futures/underlying outcome labels.
"""
import csv
from datetime import datetime
from pathlib import Path

FEATURES=("bull_checks_pass","bear_checks_pass","spot","fut_close","vix")
MIN_ROWS=200
MIN_DAYS=20

def audit_training_csv(path):
    p=Path(path)
    if not p.is_file():raise ValueError("Dataset missing")
    with p.open(newline="",encoding="utf-8") as handle:
        reader=csv.DictReader(handle)
        required={"observed_at_utc","label_status","forward_return",*FEATURES}
        if not required.issubset(set(reader.fieldnames or [])):
            raise ValueError("Missing required labeled research columns")
        rows=list(reader)
    eligible=[]
    for r in rows:
        if r.get("label_status")!="VALIDATED":
            continue
        try:
            instant=datetime.fromisoformat(r["observed_at_utc"].replace("Z","+00:00"))
            if instant.tzinfo is None:continue
            vals=[float(r[k]) for k in FEATURES]
            target=float(r["forward_return"])
            import math
            if not all(math.isfinite(v) for v in vals+[target]):continue
            eligible.append((instant,vals,1 if target>0 else 0))
        except (ValueError,KeyError,TypeError):
            continue
    eligible.sort(key=lambda x:x[0])
    days={r[0].date() for r in eligible}
    status="READY_FOR_RESEARCH" if len(eligible)>=MIN_ROWS and len(days)>=MIN_DAYS and len({r[2] for r in eligible})==2 else "INSUFFICIENT_VALIDATED_LABELS"
    return {"status":status,"eligible_rows":len(eligible),"distinct_days":len(days),
            "unusable_rows":len(rows)-len(eligible),
            "note":"READY does not prove signal quality. Walk-forward testing required."}

def walk_forward_splits(timestamps,train_fraction=.6,embargo_minutes=30):
    """Chronological split with temporal embargo; no random shuffling."""
    if not timestamps:return []
    times=sorted(timestamps)
    threshold=max(1,int(len(times)*train_fraction))
    if threshold>=len(times):return []
    from datetime import timedelta
    cutoff=times[threshold]
    end_train=cutoff-timedelta(minutes=embargo_minutes)
    train=[i for i,t in enumerate(timestamps) if t<end_train]
    test=[i for i,t in enumerate(timestamps) if t>=cutoff]
    if not train or not test:return []
    return [(train,test)]

def train_shadow_model(path):
    """Explicitly disabled until audited labeled data and separate opt-in review."""
    report=audit_training_csv(path)
    if report["status"]!="READY_FOR_RESEARCH":
        raise ValueError("ML training blocked: "+report["status"])
    raise RuntimeError("Training not enabled: require walk-forward evaluator, market-cost model and approval")
