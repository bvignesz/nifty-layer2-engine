import csv
from datetime import datetime,timezone,timedelta
import pytest
from nifty_l2.ml_shadow import audit_training_csv,walk_forward_splits,train_shadow_model

def test_ml_training_is_blocked_without_verified_outcomes(tmp_path):
    path=tmp_path/"features.csv"
    with path.open("w",newline="") as handle:
        wr=csv.DictWriter(handle,fieldnames=[
            "observed_at_utc","label_status","forward_return","bull_checks_pass",
            "bear_checks_pass","spot","fut_close","vix"])
        wr.writeheader()
        wr.writerow(dict(observed_at_utc="2026-11-05T04:30:00Z",
            label_status="NOT_AVAILABLE",forward_return="",
            bull_checks_pass=5,bear_checks_pass=2,spot=24500,fut_close=24510,vix=15))
    report=audit_training_csv(path)
    assert report["eligible_rows"]==0
    assert report["status"]=="INSUFFICIENT_VALIDATED_LABELS"
    with pytest.raises(ValueError,match="blocked"):
        train_shadow_model(path)

def test_temporal_embargo_prevents_overlap():
    base=datetime(2026,11,1,tzinfo=timezone.utc)
    timestamps=[base+timedelta(minutes=10*i) for i in range(30)]
    folds=walk_forward_splits(timestamps,embargo_minutes=30)
    assert len(folds)==1
    train,test=folds[0]
    assert max(timestamps[i] for i in train)+timedelta(minutes=30)<min(timestamps[i] for i in test)
    assert not set(train).intersection(test)
